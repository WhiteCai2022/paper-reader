import hashlib
import io
import json
import shutil
import sqlite3
import stat
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from backend.main import create_app
from backend import library_safety
from backend.models import NoteCreate
from backend.store import Store


def pdf_bytes():
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=600, height=800)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(data_dir=tmp_path / "data", frontend_dist=tmp_path / "dist"), base_url="http://127.0.0.1:8000") as value:
        yield value


def paper(client):
    result = client.post("/api/papers", files={"file": ("example.pdf", pdf_bytes(), "application/pdf")}, data={"title": "Library safety test"})
    assert result.status_code == 201, result.text
    return result.json()


def note(client, paper_id, **values):
    response = client.post(f"/api/papers/{paper_id}/notes", json={"title": "Evidence", "content": "Original content", "evidence": [{"page": 2, "quote": "A precise original source passage", "label": "Section 2"}], **values})
    assert response.status_code == 201, response.text
    return response.json()


def preview(client, content):
    response = client.post("/api/library/restore/preview", files={"file": ("backup.zip", content, "application/zip")})
    assert response.status_code == 200, response.text
    return response.json()


def test_evidence_validation_persistence_and_markdown_roundtrip(client):
    current = paper(client)
    created = note(client, current["id"], verification_status="verified")
    assert created["verification_status"] == "verified"
    assert created["evidence"][0]["page"] == 2
    assert client.get(f"/api/papers/{current['id']}").json()["notes"][0]["evidence"] == created["evidence"]
    invalid = [{"page": 4, "quote": "A passage at an invalid page"}, {"page": True, "quote": "Strict integer page is required"}, {"page": 1, "quote": "short"}]
    for evidence in invalid:
        result = client.post(f"/api/papers/{current['id']}/notes", json={"evidence": [evidence]})
        assert result.status_code == 422
    markdown = client.get(f"/api/papers/{current['id']}/export?format=markdown").content
    imported = client.post(f"/api/papers/{current['id']}/import", files={"file": ("notes.md", markdown, "text/markdown")}, data={"mode": "replace"})
    assert imported.status_code == 200, imported.text
    assert imported.json()["notes"][0]["evidence"] == created["evidence"]
    assert imported.json()["notes"][0]["verification_status"] == "verified"
    assert client.get("/api/library/trash").json()["items"][0]["id"] == created["id"]


def test_versions_preserve_original_and_restore_without_erasing_newer(client):
    current = paper(client)
    created = note(client, current["id"])
    base = f"/api/papers/{current['id']}/notes/{created['id']}"
    versions = client.get(base + "/versions").json()["versions"]
    assert versions[0]["note"]["content"] == "Original content"
    first_id = versions[0]["id"]
    updated = client.put(base, json={"content": "Second content", "verification_status": "needs_review"})
    assert updated.status_code == 200
    assert client.post(base + f"/versions/{first_id}/restore").json()["content"] == "Original content"
    versions = client.get(base + "/versions").json()["versions"]
    assert any(item["note"]["content"] == "Second content" for item in versions)
    assert versions[0]["reason"] == "restore"


def test_trash_paper_keeps_pdf_categories_notes_and_api_history(client):
    current = paper(client)
    created = note(client, current["id"])
    category = client.post("/api/categories", json={"name": "Safety"}).json()
    client.put(f"/api/papers/{current['id']}/categories", json={"category_ids": [category["id"]]})
    store = client.app.state.store
    path = Path(store.source(current["id"])["pdf_path"])
    with store.connection() as connection:
        connection.execute("INSERT INTO translation_jobs(id,paper_id,status,pages,total_pages) VALUES ('kept',?,'failed','[1]',1)", (current["id"],))
        connection.execute("INSERT INTO reading_runs(id,focus,source_hash,plan,notes) VALUES ('kept','','hash','[]','[]')")
        connection.execute("INSERT INTO translation_quotes(id,paper_id,data,expires,job_id) VALUES ('kept',?,'{}',0,'kept')", (current["id"],))
    assert client.delete(f"/api/papers/{current['id']}").status_code == 204
    assert path.is_file()
    assert store.source(current["id"]) is None
    assert client.get(f"/api/papers/{current['id']}").status_code == 404
    assert client.get(f"/api/papers/{current['id']}/pdf").status_code == 404
    assert client.get("/api/categories").json()[1]["paper_count"] == 0
    with store.connection() as connection:
        assert connection.execute("SELECT paper_id FROM translation_jobs WHERE id='kept'").fetchone()[0] == current["id"]
        assert connection.execute("SELECT COUNT(*) FROM reading_runs WHERE id='kept'").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM translation_quotes WHERE id='kept'").fetchone()[0] == 1
    trash = client.get("/api/library/trash").json()["items"]
    assert trash[0]["type"] == "paper"
    assert client.post(f"/api/library/trash/paper/{current['id']}/restore").status_code == 200
    restored = client.get(f"/api/papers/{current['id']}").json()
    assert restored["notes"][0]["id"] == created["id"]
    assert restored["category_ids"] == [category["id"]]
    assert client.get(f"/api/papers/{current['id']}/pdf").content == pdf_bytes()


def test_note_delete_restore_and_repeated_delete(client):
    current = paper(client)
    created = note(client, current["id"])
    base = f"/api/papers/{current['id']}/notes/{created['id']}"
    client.patch(f"/api/papers/{current['id']}/progress", json={"active_note_id": created["id"]})
    assert client.delete(base).status_code == 204
    assert client.delete(base).status_code == 404
    assert client.get(f"/api/papers/{current['id']}").json()["notes"] == []
    assert client.post(f"/api/library/trash/note/{created['id']}/restore").status_code == 200
    assert client.get(f"/api/papers/{current['id']}").json()["notes"][0]["content"] == created["content"]
    assert client.get(base + "/versions").json()["versions"][0]["reason"] == "delete"


def test_backup_safe_merge_restore_preserves_fees_and_originals(client):
    current = paper(client)
    created = note(client, current["id"])
    store = client.app.state.store
    (store.data_dir / "translation.local.json").write_text('{"secret":"must-not-export"}', encoding="utf-8")
    with store.connection() as connection:
        connection.execute("INSERT INTO translation_jobs(id,paper_id,status,pages,total_pages) VALUES ('historical',?,'completed','[1]',1)", (current["id"],))
        connection.execute("INSERT INTO translation_receipts(id,job_id,page,status,cost_cny) VALUES ('receipt','historical',1,'success',0.42)")
        connection.execute("INSERT INTO reading_runs(id,focus,source_hash,plan,notes) VALUES ('historical','','hash','[]',?)", (json.dumps([NoteCreate(content="Partial valid draft").model_dump()]),))
    response = client.get("/api/library/backup")
    assert response.status_code == 200, response.text
    archive_content = response.content
    with ZipFile(io.BytesIO(archive_content)) as archive:
        names = archive.namelist()
        assert "papers.sqlite3" in names and "manifest.json" in names
        assert all("translation.local.json" not in name for name in names)
        draft = next(name for name in names if name.startswith("drafts/"))
        assert json.loads(archive.read(draft))["notes"][0]["content"] == "Partial valid draft"
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["papers"][0]["pdf_member"].startswith("pdfs/")
        assert manifest["draft_files"][0]["paper_title"] == current["title"]
        assert manifest["draft_files"][0]["member"] == draft
    inspected = preview(client, archive_content)
    assert inspected["papers_count"] == 1 and inspected["draftfiles_count"] == 1
    assert any("副本" in warning for warning in inspected["warnings"])
    assert len(store.list_papers()) == 1
    assert client.post("/api/library/restore", json={"preview_id": inspected["preview_id"], "confirm": False}).status_code == 422
    response = client.post("/api/library/restore", json={"preview_id": inspected["preview_id"], "confirm": True})
    assert response.status_code == 200, response.text
    restored = response.json()
    new_id = restored["paper_ids"][0]
    assert new_id != current["id"]
    assert (store.data_dir / "backups" / restored["backup_file"]).is_file()
    assert len(store.list_papers()) == 2
    assert store.get_paper(current["id"])["notes"][0]["id"] == created["id"]
    restored_note = store.get_paper(new_id)["notes"][0]
    assert restored_note["id"] != created["id"] and restored_note["evidence"] == created["evidence"]
    assert client.get(f"/api/papers/{new_id}/pdf").content == pdf_bytes()
    with store.connection() as connection:
        assert connection.execute("SELECT SUM(cost_cny) FROM translation_receipts").fetchone()[0] == 0.42
        assert connection.execute("SELECT COUNT(*) FROM translation_jobs").fetchone()[0] == 1
    assert client.post("/api/library/restore", json={"preview_id": inspected["preview_id"], "confirm": True}).status_code == 409


def test_managed_pdf_path_is_relative_and_portable(client, tmp_path):
    current = paper(client)
    store = client.app.state.store
    with store.connection() as connection:
        assert connection.execute("SELECT pdf_path FROM papers").fetchone()[0].startswith("uploads/")
    relocated = tmp_path / "relocated"
    shutil.copytree(store.data_dir, relocated)
    moved = Store(relocated)
    assert Path(moved.source(current["id"])["pdf_path"]).parent == relocated / "uploads"
    assert Path(moved.source(current["id"])["pdf_path"]).read_bytes() == pdf_bytes()


@pytest.mark.parametrize("unsafe", ["../escape.pdf", "/absolute.pdf", "C:/escape.pdf", "pdfs\\escape.pdf"])
def test_backup_rejects_traversal_members(client, unsafe):
    paper(client)
    content = client.get("/api/library/backup").content
    output = io.BytesIO(content)
    with ZipFile(output, "a", ZIP_DEFLATED) as archive:
        member = ZipInfo("placeholder.pdf")
        member.filename = unsafe
        archive.writestr(member, b"bad")
    result = client.post("/api/library/restore/preview", files={"file": ("bad.zip", output.getvalue(), "application/zip")})
    assert result.status_code == 422
    assert len(client.app.state.store.list_papers()) == 1


def test_backup_rejects_symlink_and_checksum_mismatch(client):
    paper(client)
    content = client.get("/api/library/backup").content
    output = io.BytesIO(content)
    with ZipFile(output, "a") as archive:
        symlink = ZipInfo("pdfs/symlink.pdf")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(symlink, "/arbitrary/file")
    assert client.post("/api/library/restore/preview", files={"file": ("bad.zip", output.getvalue())}).status_code == 422
    output = io.BytesIO()
    with ZipFile(io.BytesIO(content)) as source, ZipFile(output, "w") as target:
        for name in source.namelist():
            value = source.read(name)
            if name == "manifest.json":
                manifest = json.loads(value)
                manifest["database_sha256"] = hashlib.sha256(b"not-the-database").hexdigest()
                value = json.dumps(manifest).encode()
            target.writestr(name, value)
    assert client.post("/api/library/restore/preview", files={"file": ("bad.zip", output.getvalue())}).status_code == 422


def test_restore_and_backup_are_blocked_while_api_job_active(client):
    current = paper(client)
    inspected = preview(client, client.get("/api/library/backup").content)
    with client.app.state.store.connection() as connection:
        connection.execute("INSERT INTO translation_jobs(id,paper_id,status,pages,total_pages) VALUES ('active',?,'running','[1]',1)", (current["id"],))
    assert client.get("/api/library/backup").status_code == 409
    assert client.post("/api/library/restore", json={"preview_id": inspected["preview_id"], "confirm": True}).status_code == 409
    assert len(client.app.state.store.list_papers()) == 1


def test_restore_missing_pdf_does_not_register_arbitrary_external_path(client):
    current = paper(client)
    source = Path(client.app.state.store.source(current["id"])["pdf_path"])
    source.unlink()
    content = client.get("/api/library/backup").content
    inspected = preview(client, content)
    assert inspected["missing_pdfs"] == [current["title"]]
    result = client.post("/api/library/restore", json={"preview_id": inspected["preview_id"], "confirm": True})
    assert result.status_code == 200, result.text
    restored = result.json()["paper_ids"][0]
    assert client.get(f"/api/papers/{restored}/pdf").status_code == 404
    assert Path(client.app.state.store.source(restored)["pdf_path"]).parent == client.app.state.store.uploads_dir


def test_migration_preserves_old_note_and_rebases_managed_upload(client):
    current = paper(client)
    created = note(client, current["id"])
    store = client.app.state.store
    original = store.source(current["id"])["pdf_path"]
    with store.connection() as connection:
        connection.execute("DROP TABLE note_versions")
        connection.execute("UPDATE papers SET pdf_path=? WHERE id=?", (original, current["id"]))
        connection.execute("ALTER TABLE notes DROP COLUMN evidence")
        connection.execute("ALTER TABLE notes DROP COLUMN verification_status")
        connection.execute("ALTER TABLE notes DROP COLUMN deleted_at")
        connection.execute("ALTER TABLE papers DROP COLUMN deleted_at")
    migrated = Store(store.data_dir)
    restored = migrated.get_note(current["id"], created["id"])
    assert restored["content"] == "Original content"
    assert restored["evidence"] == [] and restored["verification_status"] == "unverified"
    assert migrated.note_versions(current["id"], created["id"])[0]["reason"] == "baseline"
    with migrated.connection() as connection:
        assert connection.execute("SELECT pdf_path FROM papers").fetchone()[0].startswith("uploads/")


def test_backup_restores_translations_without_importing_old_fee_receipts(client):
    current = paper(client)
    store = client.app.state.store
    with store.connection() as connection:
        connection.execute("""INSERT INTO translation_pages(paper_id,page,source_hash,source_text,content,model,reasoning_effort,input_tokens,output_tokens,cost_cny)
            VALUES (?,1,'source','Original text','Translated text','deepseek-flash','none',10,20,0.1)""", (current["id"],))
    inspected = preview(client, client.get("/api/library/backup").content)
    response = client.post("/api/library/restore", json={"preview_id": inspected["preview_id"], "confirm": True})
    assert response.status_code == 200, response.text
    new_id = response.json()["paper_ids"][0]
    with store.connection() as connection:
        translated = connection.execute("SELECT content,cost_cny FROM translation_pages WHERE paper_id=?", (new_id,)).fetchone()
        assert tuple(translated) == ("Translated text", 0.1)
        assert connection.execute("SELECT COUNT(*) FROM translation_receipts").fetchone()[0] == 0


def test_manifest_cannot_inject_server_file_path_as_staged_pdf(client):
    current = paper(client)
    store = client.app.state.store
    source = Path(store.source(current["id"])["pdf_path"])
    source.unlink()
    secret = store.data_dir / "not-a-pdf.txt"
    secret.write_text("private test-only value", encoding="utf-8")
    content = client.get("/api/library/backup").content
    output = io.BytesIO()
    with ZipFile(io.BytesIO(content)) as original, ZipFile(output, "w") as changed:
        for name in original.namelist():
            value = original.read(name)
            if name == "manifest.json":
                manifest = json.loads(value)
                manifest["papers"][0]["staged_pdf"] = str(secret)
                value = json.dumps(manifest).encode()
            changed.writestr(name, value)
    inspected = preview(client, output.getvalue())
    response = client.post("/api/library/restore", json={"preview_id": inspected["preview_id"], "confirm": True})
    assert response.status_code == 200
    assert client.get(f"/api/papers/{response.json()['paper_ids'][0]}/pdf").status_code == 404


def test_category_member_edit_keeps_hidden_trash_memberships(client):
    first, second = paper(client), paper(client)
    category = client.post("/api/categories", json={"name": "Keep hidden membership"}).json()
    for current in (first, second):
        client.put(f"/api/papers/{current['id']}/categories", json={"category_ids": [category["id"]]})
    client.delete(f"/api/papers/{first['id']}")
    assert client.put(f"/api/categories/{category['id']}/papers", json={"paper_ids": []}).status_code == 200
    assert client.post(f"/api/library/trash/paper/{first['id']}/restore").status_code == 200
    assert client.get(f"/api/papers/{first['id']}").json()["category_ids"] == [category["id"]]
    assert client.get(f"/api/papers/{second['id']}").json()["category_ids"] == []


def test_export_rejects_backup_above_restore_size_limit(client, monkeypatch):
    paper(client)
    monkeypatch.setattr(library_safety, "MAX_ARCHIVE_BYTES", 100)
    result = client.get("/api/library/backup")
    assert result.status_code == 422
    assert not list((client.app.state.store.data_dir / "safety-tmp").glob("*.zip"))


def test_failed_restore_removes_partial_pdf_and_rolls_back_library(client, monkeypatch):
    paper(client)
    store = client.app.state.store
    inspected = preview(client, client.get("/api/library/backup").content)
    original_files = set(store.uploads_dir.iterdir())
    original_copy = library_safety.shutil.copyfile

    def failing_copy(source, target, *args, **kwargs):
        if Path(target).parent == store.uploads_dir:
            Path(target).write_bytes(b"partial PDF")
            raise OSError("Simulated disk full")
        return original_copy(source, target, *args, **kwargs)

    monkeypatch.setattr(library_safety.shutil, "copyfile", failing_copy)
    response = client.post("/api/library/restore", json={"preview_id": inspected["preview_id"], "confirm": True})
    assert response.status_code == 422
    assert len(store.list_papers()) == 1
    assert set(store.uploads_dir.iterdir()) == original_files


@pytest.mark.parametrize("patch", [{"content": "Changed after verification"}, {"title": "Changed title"}, {"page_start": 2}, {"evidence": []}, {"kind": "experiment"}])
def test_changing_verified_note_content_requires_reverification(client, patch):
    current = paper(client)
    created = note(client, current["id"], verification_status="verified", page_end=3)
    base = f"/api/papers/{current['id']}/notes/{created['id']}"
    result = client.put(base, json=patch)
    assert result.status_code == 200, result.text
    assert result.json()["verification_status"] == "needs_review"


def test_progress_only_edit_retains_verification_and_explicit_override_is_allowed(client):
    current = paper(client)
    created = note(client, current["id"], verification_status="verified")
    base = f"/api/papers/{current['id']}/notes/{created['id']}"
    assert client.put(base, json={"completed": True}).json()["verification_status"] == "verified"
    assert client.put(base, json={"content": "Reviewed replacement", "verification_status": "verified"}).json()["verification_status"] == "verified"
