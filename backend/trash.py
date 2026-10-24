"""Explicit, snapshot-confirmed permanent removal of library trash."""

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, StrictBool

from .library_safety import _active_jobs, _has_table
from .models import Model


router = APIRouter(prefix="/api/library/trash", tags=["回收站"])
PREVIEW_SECONDS = 300


class EmptyTrashRequest(Model):
    preview_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
    confirm: StrictBool


def _file_identity(path):
    value = path.stat()
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns]


def _upload_root(store):
    root = store.uploads_dir.resolve()
    if root == store.data_dir or not root.is_relative_to(store.data_dir):
        raise ValueError("The uploads directory is outside the library data directory")
    return root


def _pdf_plan(store, papers, all_papers):
    if not papers:
        return [], []
    files, retained = {}, set()
    targets = {paper["id"] for paper in papers}
    paths = {}
    for paper in all_papers:
        original = Path(paper["pdf_path"])
        paths[paper["id"]] = (original if original.is_absolute() else store.data_dir / original).resolve()
    root = _upload_root(store)
    for paper in papers:
        path = paths[paper["id"]]
        if not path.exists():
            continue
        shared = any((other["id"] not in targets or other["managed"] != 1) and paths[other["id"]] == path for other in all_papers)
        if paper["managed"] != 1 or shared or path == root or not path.is_relative_to(root) or not path.is_file():
            retained.add(str(path))
            continue
        files[str(path)] = _file_identity(path)
    return [{"path": path, "identity": identity} for path, identity in sorted(files.items())], sorted(retained)


def _snapshot(store, connection):
    papers = [dict(row) for row in connection.execute("SELECT id,pdf_path,managed,deleted_at FROM papers WHERE deleted_at IS NOT NULL ORDER BY id")]
    notes = [dict(row) for row in connection.execute("""SELECT n.id,n.paper_id,n.deleted_at FROM notes n JOIN papers p ON p.id=n.paper_id
        WHERE n.deleted_at IS NOT NULL OR p.deleted_at IS NOT NULL ORDER BY n.id""")]
    all_papers = [dict(row) for row in connection.execute("SELECT id,pdf_path,managed FROM papers")]
    files, retained = _pdf_plan(store, papers, all_papers)
    value = {"papers": papers, "notes": notes, "files": files, "retained": retained}
    fingerprint = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return value, fingerprint


def _summary(value):
    warnings = []
    if value["retained"]:
        warnings.append(f"{len(value['retained'])} 个外部、共享或不符合安全路径要求的 PDF 原文件将保留。")
    return {"papers_count": len(value["papers"]), "notes_count": len(value["notes"]), "pdfs_count": len(value["files"]),
            "external_pdfs_count": len(value["retained"]), "warnings": warnings}


@router.post("/empty/preview", summary="预览永久清空的范围，不删除资料、不调用模型")
def preview_empty_trash(request: Request):
    store = request.app.state.store
    with request.app.state.translator.lock:
        if _active_jobs(store):
            raise HTTPException(status_code=409, detail="请等待正在运行的 API 任务结束后再清空回收站。")
        try:
            with store.connection() as connection:
                connection.execute("BEGIN")
                value, fingerprint = _snapshot(store, connection)
        except (OSError, ValueError, sqlite3.Error) as error:
            raise HTTPException(status_code=422, detail="无法安全检查回收站文件，未删除任何资料。") from error
        previews = getattr(request.app.state, "empty_trash_previews", {})
        request.app.state.empty_trash_previews = previews
        for token, item in list(previews.items()):
            if item["expires"] < time.time():
                previews.pop(token, None)
        token = uuid.uuid4().hex
        previews[token] = {"fingerprint": fingerprint, "expires": time.time() + PREVIEW_SECONDS}
        return {"preview_id": token, **_summary(value)}


@router.post("/empty", summary="确认永久清空回收站，保留费用账本与外部 PDF")
def empty_trash(value: EmptyTrashRequest, request: Request):
    if not value.confirm:
        raise HTTPException(status_code=422, detail="请明确确认永久清空回收站。")
    store = request.app.state.store
    with request.app.state.translator.lock:
        if _active_jobs(store):
            raise HTTPException(status_code=409, detail="请等待正在运行的 API 任务结束后再清空回收站。")
        previews = getattr(request.app.state, "empty_trash_previews", {})
        preview = previews.get(value.preview_id)
        if preview is None or preview["expires"] < time.time():
            raise HTTPException(status_code=409, detail="清空预览已过期，请重新检查并确认。")
        try:
            with store.connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute("SELECT 1 FROM translation_jobs WHERE status IN ('queued','running','cancelling') LIMIT 1").fetchone():
                    raise HTTPException(status_code=409, detail="请等待正在运行的 API 任务结束后再清空回收站。")
                snapshot, fingerprint = _snapshot(store, connection)
                if fingerprint != preview["fingerprint"]:
                    raise HTTPException(status_code=409, detail="回收站条目或 PDF 文件已变化，未清空；请重新预览并确认。")
                # Jobs and receipts are the cost ledger. Remove source-bearing drafts, never those ledger rows.
                if _has_table(connection, "reading_runs"):
                    connection.execute("""UPDATE reading_runs SET focus='',source_hash='',plan='[]',notes='[]',diagnostics='[]',rejected_output=''
                        WHERE id IN (SELECT j.id FROM translation_jobs j JOIN papers p ON p.id=j.paper_id WHERE p.deleted_at IS NOT NULL)""")
                connection.execute("""UPDATE papers SET active_note_id=NULL WHERE active_note_id IN
                    (SELECT n.id FROM notes n JOIN papers p ON p.id=n.paper_id WHERE n.deleted_at IS NOT NULL OR p.deleted_at IS NOT NULL)""")
                connection.execute("DELETE FROM notes WHERE deleted_at IS NOT NULL")
                connection.execute("DELETE FROM papers WHERE deleted_at IS NOT NULL")
        except (OSError, ValueError, sqlite3.Error) as error:
            raise HTTPException(status_code=422, detail="无法完成清空；数据库未变更，PDF 原文件未删除。") from error
        previews.pop(value.preview_id, None)
        warnings = _summary(snapshot)["warnings"]
        deleted, failed = 0, 0
        for item in snapshot["files"]:
            path = Path(item["path"])
            try:
                root = _upload_root(store)
                if not path.exists():
                    continue
                if path.resolve() != path or not path.is_relative_to(root) or not path.is_file() or _file_identity(path) != item["identity"]:
                    raise ValueError("The file changed after confirmation")
                with store.connection() as connection:
                    for row in connection.execute("SELECT pdf_path FROM papers"):
                        reference = Path(row["pdf_path"])
                        reference = (reference if reference.is_absolute() else store.data_dir / reference).resolve()
                        if reference == path:
                            raise ValueError("Another paper now references this file")
                path.unlink()
                deleted += 1
            except FileNotFoundError:
                continue
            except (OSError, ValueError, sqlite3.Error):
                failed += 1
        if failed:
            warnings.append(f"回收站记录已永久清空，但有 {failed} 个托管 PDF 因占用、权限或文件变化而未删除。请检查 data/uploads；本次不会自动重试。")
        return {"papers_count": len(snapshot["papers"]), "notes_count": len(snapshot["notes"]), "pdfs_deleted": deleted,
                "retained_files_count": len(snapshot["retained"]) + failed, "warnings": warnings}
