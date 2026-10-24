import hashlib
import json
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field, StrictBool, ValidationError
from pypdf import PdfReader
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from .models import AnnotationCreate, CategoryInput, Metadata, Model, NoteCreate, Progress


router = APIRouter(prefix="/api")
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 100 * 1024 * 1024
MAX_PDF_BYTES = 100 * 1024 * 1024
PREVIEW_SECONDS = 1800


class RestoreRequest(Model):
    preview_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
    confirm: StrictBool


def _remove_temporary(path: Path, root: Path):
    path = path.resolve()
    if path == root.resolve() or not path.is_relative_to(root.resolve()):
        raise ValueError("Refusing to remove a path outside the temporary directory")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _has_table(connection, name):
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _active_jobs(store):
    with store.connection() as connection:
        return _has_table(connection, "translation_jobs") and connection.execute("SELECT 1 FROM translation_jobs WHERE status IN ('queued','running','cancelling') LIMIT 1").fetchone() is not None


def _snapshot_database(store, destination):
    with closing(sqlite3.connect(f"file:{store.db_path.as_posix()}?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(destination)) as target:
            source.backup(target)


def make_backup(store, destination):
    """Archive a consistent database plus portable, validated-library restore data. Never include secrets."""
    root = store.data_dir / "safety-tmp"
    root.mkdir(exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="backup-", dir=root))
    snapshot = temporary / "papers.sqlite3"
    try:
        _snapshot_database(store, snapshot)
        expanded_bytes = snapshot.stat().st_size
        if expanded_bytes > MAX_ARCHIVE_BYTES:
            raise ValueError("The database exceeds the supported 1 GB backup limit")
        with closing(sqlite3.connect(snapshot)) as connection, ZipFile(destination, "w", ZIP_DEFLATED) as archive:
            connection.row_factory = sqlite3.Row
            manifest = {"format": "paper-reader-library", "version": 1, "created_at": time.time(), "papers": [],
                        "categories": [dict(row) for row in connection.execute("SELECT id,name FROM categories")],
                        "database_sha256": _digest(snapshot), "api_jobs_count": 0, "unimported_reading_drafts_count": 0, "draftfiles_count": 0, "draft_files": []}
            if len(manifest["categories"]) > 10_000:
                raise ValueError("The backup contains too many categories")
            note_count, annotation_count = 0, 0
            for row in connection.execute("SELECT * FROM papers ORDER BY rowid"):
                paper = dict(row)
                paper["tags"] = json.loads(paper["tags"])
                paper["notes"] = []
                for note_row in connection.execute("SELECT * FROM notes WHERE paper_id=? ORDER BY sort_order,rowid", (paper["id"],)):
                    note = store.note_dict(note_row)
                    note["deleted_at"] = note_row["deleted_at"]
                    note["versions"] = [{"created_at": version["created_at"], "reason": version["reason"], "note": json.loads(version["snapshot"])}
                                        for version in connection.execute("SELECT * FROM note_versions WHERE note_id=? ORDER BY rowid", (note["id"],))]
                    paper["notes"].append(note)
                if len(paper["notes"]) > 10_000 or any(len(note["versions"]) > 100_000 for note in paper["notes"]):
                    raise ValueError("The backup contains too many notes or note versions")
                paper["category_ids"] = [item[0] for item in connection.execute("SELECT category_id FROM paper_categories WHERE paper_id=?", (paper["id"],))]
                paper["annotations"] = [store.annotation_dict(item) for item in connection.execute("SELECT * FROM annotations WHERE paper_id=? ORDER BY page,rowid", (paper["id"],))]
                if len(paper["annotations"]) > 10_000:
                    raise ValueError("The backup contains too many annotations")
                annotation_count += len(paper["annotations"])
                if annotation_count > 100_000:
                    raise ValueError("The backup contains too many annotations")
                paper["translations"] = [dict(item) for item in connection.execute("SELECT * FROM translation_pages WHERE paper_id=?", (paper["id"],))] if _has_table(connection, "translation_pages") else []
                original = Path(paper.pop("pdf_path"))
                source = original if original.is_absolute() else store.data_dir / original
                paper["original_pdf_reference"] = str(original)
                paper["pdf_member"] = None
                paper["pdf_sha256"] = None
                if source.is_file():
                    if source.stat().st_size > MAX_PDF_BYTES:
                        raise ValueError("A PDF exceeds the supported 100 MB backup limit")
                    expanded_bytes += source.stat().st_size
                    if expanded_bytes > MAX_ARCHIVE_BYTES or len(archive.filelist) >= 49_998:
                        raise ValueError("The expanded backup exceeds its size or member limit")
                    member = f"pdfs/{uuid.uuid4().hex}.pdf"
                    archive.write(source, member)
                    paper["pdf_member"] = member
                    paper["pdf_sha256"] = _digest(source)
                manifest["papers"].append(paper)
                note_count += len(paper["notes"])
                if len(manifest["papers"]) > 20_000 or note_count > 100_000:
                    raise ValueError("The backup contains too many papers or notes")
            if _has_table(connection, "translation_jobs"):
                manifest["api_jobs_count"] = connection.execute("SELECT COUNT(*) FROM translation_jobs").fetchone()[0]
            if _has_table(connection, "reading_runs"):
                manifest["unimported_reading_drafts_count"] = connection.execute("SELECT COUNT(*) FROM reading_runs WHERE imported_at IS NULL AND notes!='[]'").fetchone()[0]
                for run in connection.execute("SELECT r.id,r.notes,j.paper_id,p.title FROM reading_runs r JOIN translation_jobs j ON j.id=r.id LEFT JOIN papers p ON p.id=j.paper_id WHERE r.imported_at IS NULL AND r.notes!='[]'"):
                    try:
                        notes = [NoteCreate.model_validate(note).model_dump() for note in json.loads(run["notes"])]
                    except (ValueError, TypeError, ValidationError):
                        continue
                    draft = json.dumps({"schema_version": 1, "notes": notes}, ensure_ascii=False).encode("utf-8")
                    expanded_bytes += len(draft)
                    if expanded_bytes > MAX_ARCHIVE_BYTES or len(archive.filelist) >= 49_998:
                        raise ValueError("The expanded backup exceeds its size or member limit")
                    member = f"drafts/{uuid.uuid4().hex}.json"
                    archive.writestr(member, draft)
                    manifest["draftfiles_count"] += 1
                    manifest["draft_files"].append({"member": member, "paper_id": run["paper_id"], "paper_title": run["title"], "job_id": run["id"]})
            encoded = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
            if len(encoded) > MAX_MANIFEST_BYTES:
                raise ValueError("The library metadata exceeds the supported 100 MB backup limit")
            if expanded_bytes + len(encoded) > MAX_ARCHIVE_BYTES:
                raise ValueError("The expanded backup exceeds the supported 1 GB limit")
            archive.writestr("manifest.json", encoded)
            archive.write(snapshot, "papers.sqlite3")
    finally:
        _remove_temporary(temporary, root)


def _validated_note(value, page_count):
    note = NoteCreate.model_validate({name: value[name] for name in NoteCreate.model_fields if name in value})
    if note.page_end > page_count or any(item.page > page_count for item in note.evidence):
        raise ValueError("A note or evidence page is outside its PDF")
    return note.model_dump()


def _safe_member(info):
    path = PurePosixPath(info.filename)
    mode = (info.external_attr >> 16) & 0xFFFF
    if (not info.filename or "\\" in info.filename or "\\" in info.orig_filename or ":" in info.filename or path.is_absolute()
            or any(part in {"", ".", ".."} for part in info.filename.split("/"))
            or stat.S_IFMT(mode) not in {0, stat.S_IFREG} or info.is_dir() or info.flag_bits & 1):
        raise ValueError("The backup contains an unsafe archive path or file type")
    if info.file_size < 0 or info.file_size > MAX_ARCHIVE_BYTES:
        raise ValueError("A backup member exceeds the size limit")


def inspect_backup(store, path, temporary):
    with ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 50_000 or len({item.filename for item in infos}) != len(infos):
            raise ValueError("The backup has too many files or duplicate archive members")
        for info in infos:
            _safe_member(info)
        if sum(item.file_size for item in infos) > MAX_ARCHIVE_BYTES:
            raise ValueError("The expanded backup exceeds the 1 GB limit")
        if archive.getinfo("manifest.json").file_size > MAX_MANIFEST_BYTES:
            raise ValueError("The library manifest exceeds 100 MB")
        manifest = json.loads(archive.read("manifest.json"))
        if not isinstance(manifest, dict) or manifest.get("format") != "paper-reader-library" or manifest.get("version") != 1:
            raise ValueError("Unsupported library backup format")
        if not isinstance(manifest.get("papers"), list) or len(manifest["papers"]) > 20_000:
            raise ValueError("Invalid paper list")
        database = temporary / "papers.sqlite3"
        with archive.open("papers.sqlite3") as source, database.open("xb") as target:
            shutil.copyfileobj(source, target)
        if _digest(database) != manifest.get("database_sha256"):
            raise ValueError("Backup database checksum does not match")
        with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)) as connection:
            connection.execute("PRAGMA trusted_schema=OFF")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Backup database integrity check failed")
        ids = set()
        category_ids = set()
        categories = manifest.get("categories", [])
        if not isinstance(categories, list) or len(categories) > 10_000:
            raise ValueError("Invalid category list")
        for category in categories:
            CategoryInput.model_validate({"name": category["name"]})
            if not isinstance(category["id"], str) or category["id"] in category_ids:
                raise ValueError("Invalid category identifier")
            category_ids.add(category["id"])
        note_count, annotation_count, pdf_count, referenced_pdf_bytes, missing = 0, 0, 0, 0, []
        for paper in manifest["papers"]:
            # Filesystem paths are produced here, never accepted from an uploaded manifest.
            paper.pop("staged_pdf", None)
            metadata = Metadata.model_validate({name: paper[name] for name in Metadata.model_fields if name in paper})
            paper.update(metadata.model_dump())
            if not isinstance(paper.get("id"), str) or paper["id"] in ids:
                raise ValueError("Invalid or duplicate paper identifier")
            ids.add(paper["id"])
            page_count = paper.get("page_count")
            if type(page_count) is not int or not 1 <= page_count <= 100_000:
                raise ValueError("Invalid page count")
            if paper.get("deleted_at") is not None and not isinstance(paper["deleted_at"], str):
                raise ValueError("Invalid deletion timestamp")
            Progress.model_validate({"page": paper.get("page", 1), "zoom": paper.get("zoom", 1), "active_note_id": None})
            if paper.get("page", 1) > page_count:
                raise ValueError("Reading progress is outside its PDF")
            if not isinstance(paper.get("notes"), list) or len(paper["notes"]) > 10_000:
                raise ValueError("Invalid note list")
            annotations = paper.get("annotations", [])
            if not isinstance(annotations, list) or len(annotations) > 10_000:
                raise ValueError("Invalid annotation list")
            paper["annotations"] = [AnnotationCreate.model_validate({name: item[name] for name in AnnotationCreate.model_fields if name in item}).model_dump() for item in annotations]
            if any(item["page"] > page_count for item in paper["annotations"]):
                raise ValueError("Annotation page is outside its PDF")
            annotation_count += len(annotations)
            if annotation_count > 100_000:
                raise ValueError("The backup contains too many annotations")
            if not isinstance(paper.get("category_ids"), list) or not set(paper["category_ids"]).issubset(category_ids):
                raise ValueError("Invalid category membership")
            note_ids = set()
            for note in paper["notes"]:
                if not isinstance(note.get("id"), str) or note["id"] in note_ids:
                    raise ValueError("Invalid or duplicate note identifier")
                note_ids.add(note["id"])
                if note.get("deleted_at") is not None and not isinstance(note["deleted_at"], str):
                    raise ValueError("Invalid deletion timestamp")
                note.update(_validated_note(note, page_count))
                versions = note.get("versions", [])
                if not isinstance(versions, list) or len(versions) > 100_000:
                    raise ValueError("Invalid note version list")
                for version in versions:
                    version["note"] = _validated_note(version["note"], page_count)
            note_count += len(paper["notes"])
            if note_count > 100_000:
                raise ValueError("The backup contains too many notes")
            member = paper.get("pdf_member")
            if member is None:
                missing.append(metadata.title)
                continue
            if not isinstance(member, str) or not member.startswith("pdfs/") or not member.endswith(".pdf"):
                raise ValueError("Invalid PDF archive reference")
            info = archive.getinfo(member)
            referenced_pdf_bytes += info.file_size
            if referenced_pdf_bytes > MAX_ARCHIVE_BYTES:
                raise ValueError("The referenced PDF copies exceed the 1 GB limit")
            if info.file_size > MAX_PDF_BYTES:
                raise ValueError("A PDF exceeds 100 MB")
            destination = temporary / f"{uuid.uuid4().hex}.pdf"
            with archive.open(member) as source, destination.open("xb") as output:
                shutil.copyfileobj(source, output)
            if _digest(destination) != paper.get("pdf_sha256"):
                raise ValueError("PDF checksum does not match")
            with destination.open("rb") as stream:
                reader = PdfReader(stream, strict=True)
                if reader.is_encrypted or len(reader.pages) != page_count:
                    raise ValueError("PDF is encrypted or does not match its declared page count")
            paper["staged_pdf"] = str(destination)
            pdf_count += 1
        warnings = ["恢复会合并为新的文献记录，不覆盖现有文献、API Key 或费用账本；重复文献可能产生副本。"]
        if manifest.get("api_jobs_count") or manifest.get("unimported_reading_drafts_count"):
            warnings.append("历史 API 任务、费用记录保存在备份数据库中，不重新导入或自动运行；未追加精读草稿另存于备份的 drafts/*.json，可用普通解析导入恢复；已追加解析和译文会恢复。")
        if missing:
            warnings.append("部分 PDF 原文件已缺失，只能恢复对应文献记录与笔记。")
        existing_titles = {paper["title"].casefold() for paper in store.list_papers()}
        duplicates = sum(paper["title"].casefold() in existing_titles for paper in manifest["papers"])
        if duplicates:
            warnings.append(f"当前文献库已有 {duplicates} 条同名文献，确认恢复后会保留两个副本。")
        return manifest, {"papers_count": len(manifest["papers"]), "notes_count": note_count, "pdfs_count": pdf_count,
                          "annotations_count": annotation_count,
                          "draftfiles_count": manifest.get("draftfiles_count", 0), "missing_pdfs": missing, "warnings": warnings}


def merge_restore(store, manifest):
    created_files, paper_ids = [], []
    try:
        with store.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            category_map = {}
            for category in manifest["categories"]:
                row = connection.execute("SELECT id FROM categories WHERE name=? COLLATE NOCASE", (category["name"],)).fetchone()
                category_id = row[0] if row else uuid.uuid4().hex
                if row is None:
                    connection.execute("INSERT INTO categories(id,name) VALUES (?,?)", (category_id, category["name"]))
                category_map[category["id"]] = category_id
            for paper in manifest["papers"]:
                paper_id = uuid.uuid4().hex
                paper_ids.append(paper_id)
                target = store.uploads_dir / f"{uuid.uuid4().hex}.pdf"
                if paper.get("staged_pdf"):
                    created_files.append(target)
                    shutil.copyfile(paper["staged_pdf"], target)
                names = ("title", "short_title", "authors", "venue", "year", "doi", "tags", "status", "page_count", "file_name", "pdf_path", "managed", "page", "zoom", "deleted_at")
                values = {name: paper.get(name) for name in names}
                values.update(tags=json.dumps(paper["tags"]), file_name=Path(str(paper.get("file_name", "restored.pdf"))).name[:240],
                              pdf_path=target.relative_to(store.data_dir).as_posix(), managed=1,
                              page=paper.get("page", 1), zoom=paper.get("zoom", 1), deleted_at=paper.get("deleted_at"))
                connection.execute("INSERT INTO papers(id," + ",".join(names) + ") VALUES (" + ",".join("?" for _ in range(len(names) + 1)) + ")", (paper_id, *(values[name] for name in names)))
                note_map = {}
                for annotation in paper.get("annotations", []):
                    store.insert_annotation(connection, paper_id, annotation)
                for note in paper["notes"]:
                    note_id = store.insert_note(connection, paper_id, note, note["sort_order"])
                    note_map[note["id"]] = note_id
                    if note.get("deleted_at"):
                        connection.execute("UPDATE notes SET deleted_at=? WHERE id=?", (note["deleted_at"], note_id))
                    for version in note.get("versions", []):
                        snapshot = {**version["note"], "id": note_id}
                        connection.execute("INSERT INTO note_versions(id,note_id,paper_id,snapshot,reason,created_at) VALUES (?,?,?,?,?,?)",
                                           (uuid.uuid4().hex, note_id, paper_id, json.dumps(snapshot, ensure_ascii=False), "backup_restore", str(version.get("created_at", ""))[:100]))
                active = note_map.get(paper.get("active_note_id"))
                if active and not next(item for item in paper["notes"] if note_map[item["id"]] == active).get("deleted_at"):
                    connection.execute("UPDATE papers SET active_note_id=? WHERE id=?", (active, paper_id))
                connection.executemany("INSERT INTO paper_categories(paper_id,category_id) VALUES (?,?)", [(paper_id, category_map[category_id]) for category_id in set(paper["category_ids"])])
                if _has_table(connection, "translation_pages"):
                    available = {row["name"] for row in connection.execute("PRAGMA table_info(translation_pages)")} - {"paper_id"}
                    for translation in paper.get("translations", []):
                        # Cached values are inert strings, never executable schema or scheduled jobs.
                        if not isinstance(translation, dict) or type(translation.get("page")) is not int or not 1 <= translation["page"] <= paper["page_count"]:
                            raise ValueError("Invalid cached translation")
                        names = sorted(available & translation.keys())
                        connection.execute("INSERT OR IGNORE INTO translation_pages(paper_id," + ",".join(names) + ") VALUES (" + ",".join("?" for _ in range(len(names) + 1)) + ")", (paper_id, *(translation[name] for name in names)))
        return {"papers_count": len(paper_ids), "notes_count": sum(len(paper["notes"]) for paper in manifest["papers"]),
                "annotations_count": sum(len(paper.get("annotations", [])) for paper in manifest["papers"]), "paper_ids": paper_ids}
    except Exception:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise


@router.get("/papers/{paper_id}/notes/{note_id}/versions")
def versions(paper_id: str, note_id: str, request: Request):
    store = request.app.state.store
    if store.get_note(paper_id, note_id) is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"versions": store.note_versions(paper_id, note_id)}


@router.post("/papers/{paper_id}/notes/{note_id}/versions/{version_id}/restore")
def restore_version(paper_id: str, note_id: str, version_id: str, request: Request):
    try:
        note = request.app.state.store.restore_note_version(paper_id, note_id, version_id)
    except (ValueError, ValidationError) as error:
        raise HTTPException(status_code=422, detail="此版本内容或页码无效，未修改当前笔记") from error
    if note is None:
        raise HTTPException(status_code=404, detail="Note or version not found")
    return note


@router.get("/library/trash")
def trash(request: Request):
    return {"items": request.app.state.store.list_trash()}


@router.post("/library/trash/{kind}/{item_id}/restore")
def restore_trash(kind: Literal["paper", "note"], item_id: str, request: Request):
    result = request.app.state.store.restore_trash(kind, item_id)
    if result is None:
        raise HTTPException(status_code=404, detail="回收站条目不存在；请先恢复所属文献")
    return result


@router.get("/library/backup")
def backup(request: Request):
    store = request.app.state.store
    root = store.data_dir / "safety-tmp"
    root.mkdir(exist_ok=True)
    destination = root / f"library-{uuid.uuid4().hex}.zip"
    try:
        with request.app.state.translator.lock:
            if _active_jobs(store):
                raise HTTPException(status_code=409, detail="请等待或停止正在运行的 API 任务后再备份")
            make_backup(store, destination)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except (OSError, ValueError, sqlite3.Error) as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="无法完成文献库备份，请检查文件可读性和磁盘空间") from error
    return FileResponse(destination, media_type="application/zip", filename=f"paper-reader-backup-{time.strftime('%Y%m%d-%H%M%S')}.zip", background=BackgroundTask(destination.unlink, missing_ok=True))


@router.post("/library/restore/preview")
async def restore_preview(request: Request, file: Annotated[UploadFile, File()]):
    store = request.app.state.store
    root = store.data_dir / "safety-tmp"
    root.mkdir(exist_ok=True)
    previews = getattr(request.app.state, "restore_previews", {})
    request.app.state.restore_previews = previews
    for key, value in list(previews.items()):
        if value["expires"] < time.time():
            _remove_temporary(value["directory"], root)
            previews.pop(key, None)
    temporary = Path(tempfile.mkdtemp(prefix="restore-", dir=root))
    archive = temporary / "upload.zip"
    try:
        size = 0
        with archive.open("xb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ARCHIVE_BYTES:
                    raise HTTPException(status_code=413, detail="备份文件超过 1 GB 限制")
                output.write(chunk)
        manifest, summary = await run_in_threadpool(inspect_backup, store, archive, temporary)
        token = uuid.uuid4().hex
        previews[token] = {"manifest": manifest, "directory": temporary, "expires": time.time() + PREVIEW_SECONDS}
        return {"preview_id": token, **summary}
    except HTTPException:
        _remove_temporary(temporary, root)
        raise
    except (BadZipFile, OSError, ValueError, TypeError, KeyError, sqlite3.Error, ValidationError) as error:
        _remove_temporary(temporary, root)
        raise HTTPException(status_code=422, detail="备份损坏、格式不受支持或内容未通过安全校验，未修改文献库") from error
    finally:
        await file.close()


@router.post("/library/restore")
def restore(value: RestoreRequest, request: Request):
    if not value.confirm:
        raise HTTPException(status_code=422, detail="请确认合并恢复")
    store = request.app.state.store
    root = store.data_dir / "safety-tmp"
    previews = getattr(request.app.state, "restore_previews", {})
    with request.app.state.translator.lock:
        if _active_jobs(store):
            raise HTTPException(status_code=409, detail="请等待或停止正在运行的 API 任务后再恢复")
        preview = previews.get(value.preview_id)
        if preview is None or preview["expires"] < time.time():
            raise HTTPException(status_code=409, detail="恢复预览已过期，请重新选择备份文件")
        backups = store.data_dir / "backups"
        backups.mkdir(exist_ok=True)
        before = backups / f"before-restore-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.zip"
        try:
            make_backup(store, before)
            result = merge_restore(store, preview["manifest"])
        except (OSError, ValueError, sqlite3.Error) as error:
            raise HTTPException(status_code=422, detail="恢复失败；数据库未变更，请检查磁盘空间和备份内容") from error
        previews.pop(value.preview_id, None)
        _remove_temporary(preview["directory"], root)
        return {**result, "backup_file": before.name}
