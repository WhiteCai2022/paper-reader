import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from backend.main import create_app, load_seeds


def pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(data_dir=tmp_path / "data", frontend_dist=tmp_path / "dist"), base_url="http://127.0.0.1:8000") as value:
        def unexpected_provider(*args, **kwargs):
            pytest.fail("Trash operations must not call a paid API")
        value.app.state.translator.call_provider = unexpected_provider
        value.app.state.reader.call_provider = unexpected_provider
        yield value


def paper(client, title="Trash test"):
    response = client.post("/api/papers", files={"file": ("example.pdf", pdf_bytes(), "application/pdf")}, data={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


def note(client, paper_id, title="Test note"):
    response = client.post(f"/api/papers/{paper_id}/notes", json={"title": title, "content": "Original note content"})
    assert response.status_code == 201, response.text
    return response.json()


def preview(client):
    response = client.post("/api/library/trash/empty/preview")
    assert response.status_code == 200, response.text
    return response.json()


def empty(client, token):
    return client.post("/api/library/trash/empty", json={"preview_id": token, "confirm": True})


def delete_paper(client, current):
    assert client.delete(f"/api/papers/{current['id']}").status_code == 204


def rows(store, table):
    with store.connection() as connection:
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def seed_history(store, paper_id, job_id, reading=False):
    with store.connection() as connection:
        connection.execute("""INSERT INTO translation_jobs(id,paper_id,status,pages,total_pages,completed_pages,cost_cny,task_type)
            VALUES (?,?,'failed','[1,2]',2,1,0.42,?)""", (job_id, paper_id, "reading" if reading else "translation"))
        connection.execute("""INSERT INTO translation_receipts(id,job_id,page,status,cost_cny,input_tokens,output_tokens)
            VALUES (?,?,1,'success',0.42,120,340)""", (job_id + "-receipt", job_id))
        connection.execute("INSERT INTO translation_quotes(id,paper_id,data,expires,job_id) VALUES (?,?,'{}',9999999999,?)", (job_id + "-quote", paper_id, job_id))
        connection.execute("""INSERT INTO translation_pages(paper_id,page,source_hash,source_text,content,model,reasoning_effort,input_tokens,output_tokens,cost_cny)
            VALUES (?,1,'hash','Original PDF source','Paid translation','deepseek-flash','none',120,340,0.42)""", (paper_id,))
        if reading:
            stage = {"kind": "detail", "label": "Read source", "first": 1, "last": 1, "max_tokens": 500}
            connection.execute("""INSERT INTO reading_runs(id,focus,source_hash,plan,notes,diagnostics,rejected_output,imported_at)
                VALUES (?,?,?,?,?,?,?,'2026-10-23 12:00:00')""", (job_id, "Private reading focus", "sourcehash", json.dumps([stage]), '[{"content":"Private draft"}]', '[{"output":"Private diagnostic"}]', "Rejected source-bearing output"))


def test_preview_is_read_only_and_confirmation_is_strict_single_use(client):
    current = paper(client)
    path = Path(client.app.state.store.source(current["id"])["pdf_path"])
    delete_paper(client, current)
    store = client.app.state.store
    before = {name: rows(store, name) for name in ("papers", "notes", "translation_jobs", "translation_receipts")}
    inspected = preview(client)
    assert inspected["papers_count"] == 1 and inspected["pdfs_count"] == 1
    assert before == {name: rows(store, name) for name in before}
    assert path.is_file()
    for confirmation in (False, "true", 1, None):
        response = client.post("/api/library/trash/empty", json={"preview_id": inspected["preview_id"], "confirm": confirmation})
        assert response.status_code == 422
    assert client.post("/api/library/trash/empty", json={"preview_id": "invalid", "confirm": True}).status_code == 422
    assert empty(client, "0" * 32).status_code == 409
    response = empty(client, inspected["preview_id"])
    assert response.status_code == 200, response.text
    assert response.json()["pdfs_deleted"] == 1 and not path.exists()
    assert empty(client, inspected["preview_id"]).status_code == 409


def test_expired_preview_does_not_delete(client):
    current = paper(client)
    delete_paper(client, current)
    inspected = preview(client)
    client.app.state.empty_trash_previews[inspected["preview_id"]]["expires"] = 0
    assert empty(client, inspected["preview_id"]).status_code == 409
    assert len(rows(client.app.state.store, "papers")) == 1


@pytest.mark.parametrize("change", ["new_trash", "restore", "file", "reference"])
def test_changed_snapshot_requires_new_confirmation(client, change):
    current, other = paper(client), paper(client)
    store = client.app.state.store
    path = Path(store.source(current["id"])["pdf_path"])
    delete_paper(client, current)
    inspected = preview(client)
    if change == "new_trash":
        delete_paper(client, other)
    elif change == "restore":
        assert client.post(f"/api/library/trash/paper/{current['id']}/restore").status_code == 200
    elif change == "file":
        path.write_bytes(path.read_bytes() + b"\nchanged")
    else:
        with store.connection() as connection:
            connection.execute("UPDATE papers SET pdf_path=? WHERE id=?", (str(path), other["id"]))
    assert empty(client, inspected["preview_id"]).status_code == 409
    assert path.is_file() and len(rows(store, "papers")) == 2


@pytest.mark.parametrize("status", ["queued", "running", "cancelling"])
def test_active_jobs_block_preview_and_execution(client, status):
    current = paper(client)
    delete_paper(client, current)
    inspected = preview(client)
    store = client.app.state.store
    with store.connection() as connection:
        connection.execute("INSERT INTO translation_jobs(id,paper_id,status,pages,total_pages) VALUES ('active',?,?, '[1]',1)", (current["id"], status))
    assert client.post("/api/library/trash/empty/preview").status_code == 409
    assert empty(client, inspected["preview_id"]).status_code == 409
    assert len(rows(store, "papers")) == 1


def test_purge_only_trash_cascades_content_and_preserves_fee_ledger(client):
    active, trashed = paper(client, "Active"), paper(client, "Deleted")
    active_note = note(client, active["id"], "Keep active")
    deleted_note = note(client, active["id"], "Delete independently")
    deleted_paper_notes = [note(client, trashed["id"], "Not individually deleted"), note(client, trashed["id"], "Also trashed")]
    category = client.post("/api/categories", json={"name": "Keep category"}).json()
    for current in (active, trashed):
        client.put(f"/api/papers/{current['id']}/categories", json={"category_ids": [category["id"]]})
    store = client.app.state.store
    seed_history(store, active["id"], "active-history")
    seed_history(store, trashed["id"], "deleted-history", reading=True)
    client.patch(f"/api/papers/{active['id']}/progress", json={"active_note_id": deleted_note["id"]})
    assert client.delete(f"/api/papers/{active['id']}/notes/{deleted_note['id']}").status_code == 204
    assert client.delete(f"/api/papers/{trashed['id']}/notes/{deleted_paper_notes[1]['id']}").status_code == 204
    delete_paper(client, trashed)
    jobs_before, receipts_before = rows(store, "translation_jobs"), rows(store, "translation_receipts")
    inspected = preview(client)
    assert inspected["papers_count"] == 1 and inspected["notes_count"] == 3
    result = empty(client, inspected["preview_id"])
    assert result.status_code == 200, result.text
    assert result.json()["notes_count"] == 3
    assert [row["id"] for row in rows(store, "papers")] == [active["id"]]
    assert [row["id"] for row in rows(store, "notes")] == [active_note["id"]]
    assert {row["note_id"] for row in rows(store, "note_versions")} == {active_note["id"]}
    assert [row["paper_id"] for row in rows(store, "paper_categories")] == [active["id"]]
    assert [row["paper_id"] for row in rows(store, "translation_pages")] == [active["id"]]
    assert [row["paper_id"] for row in rows(store, "translation_quotes")] == [active["id"]]
    jobs_after = rows(store, "translation_jobs")
    expected_jobs = [{**row, "paper_id": None} if row["id"] == "deleted-history" else row for row in jobs_before]
    assert jobs_after == expected_jobs
    assert rows(store, "translation_receipts") == receipts_before
    history = rows(store, "reading_runs")[0]
    assert history["imported_at"] == "2026-10-23 12:00:00"
    for field in ("focus", "source_hash", "rejected_output"):
        assert history[field] == ""
    for field in ("plan", "notes", "diagnostics"):
        assert history[field] == "[]"
    response = client.get("/api/reading/jobs/deleted-history")
    assert response.status_code == 200, response.text
    assert response.json()["notes"] == [] and response.json()["can_resume"] is False
    assert client.get("/api/reading/jobs/deleted-history/export").json()["notes"] == []
    assert client.get("/api/reading/jobs/deleted-history/rejected-output").status_code == 404
    assert client.get("/api/library/trash").json()["items"] == []
    assert store.get_paper(active["id"])["progress"]["active_note_id"] is None
    assert len(rows(store, "categories")) == 1


@pytest.mark.parametrize("kind", ["external", "shared", "outside_uploads", "symlink"])
def test_external_shared_and_unsafe_paths_are_never_unlinked(client, tmp_path, kind):
    current, active = paper(client), paper(client)
    store = client.app.state.store
    original = Path(store.source(current["id"])["pdf_path"])
    target = tmp_path / "external.pdf"
    target.write_bytes(pdf_bytes())
    managed, path = 1, target
    if kind == "external":
        managed = 0
    elif kind == "shared":
        path = original
        with store.connection() as connection:
            connection.execute("UPDATE papers SET pdf_path=? WHERE id=?", (str(path), active["id"]))
    elif kind == "symlink":
        path = store.uploads_dir / "outside-link.pdf"
        try:
            path.symlink_to(target)
        except OSError:
            pytest.skip("This Windows account cannot create symlinks")
    with store.connection() as connection:
        connection.execute("UPDATE papers SET pdf_path=?,managed=? WHERE id=?", (str(path), managed, current["id"]))
    delete_paper(client, current)
    inspected = preview(client)
    assert inspected["pdfs_count"] == 0 and inspected["external_pdfs_count"] == 1
    result = empty(client, inspected["preview_id"])
    assert result.status_code == 200, result.text
    assert result.json()["pdfs_deleted"] == 0 and result.json()["warnings"]
    assert path.exists() and target.is_file()


def test_missing_pdf_and_empty_trash_are_safe(client):
    current = paper(client)
    store = client.app.state.store
    Path(store.source(current["id"])["pdf_path"]).unlink()
    delete_paper(client, current)
    inspected = preview(client)
    assert inspected["pdfs_count"] == 0
    result = empty(client, inspected["preview_id"])
    assert result.status_code == 200 and result.json()["papers_count"] == 1
    inspected = preview(client)
    assert inspected["papers_count"] == 0 and inspected["notes_count"] == 0
    result = empty(client, inspected["preview_id"])
    assert result.status_code == 200 and result.json()["pdfs_deleted"] == 0


def test_unmanaged_reference_protects_pdf_even_when_both_papers_are_purged(client):
    managed, unmanaged = paper(client), paper(client)
    store = client.app.state.store
    path = Path(store.source(managed["id"])["pdf_path"])
    with store.connection() as connection:
        connection.execute("UPDATE papers SET pdf_path=?,managed=0 WHERE id=?", (str(path), unmanaged["id"]))
    for current in (managed, unmanaged):
        delete_paper(client, current)
    inspected = preview(client)
    assert inspected["papers_count"] == 2 and inspected["pdfs_count"] == 0
    assert inspected["external_pdfs_count"] == 1
    response = empty(client, inspected["preview_id"])
    assert response.status_code == 200, response.text
    assert response.json()["pdfs_deleted"] == 0 and response.json()["warnings"]
    assert path.is_file() and rows(store, "papers") == []


def test_deleted_seed_tombstone_survives_permanent_purge(client, tmp_path):
    store = client.app.state.store
    source = tmp_path / "seed-original.pdf"
    source.write_bytes(pdf_bytes())
    seed = {"id": "seed-paper", "title": "Seed paper", "pdf_path": str(source)}
    (store.data_dir / "seed.json").write_text(json.dumps([seed]), encoding="utf-8")
    load_seeds(store)
    assert store.get_paper("seed-paper")
    assert client.delete("/api/papers/seed-paper").status_code == 204
    assert empty(client, preview(client)["preview_id"]).status_code == 200
    assert store.seed_is_deleted("seed-paper") and source.is_file()
    load_seeds(store)
    assert store.get_paper("seed-paper") is None


def test_database_failure_rolls_back_before_deleting_pdf(client):
    current = paper(client)
    created = note(client, current["id"])
    store = client.app.state.store
    path = Path(store.source(current["id"])["pdf_path"])
    delete_paper(client, current)
    inspected = preview(client)
    with store.connection() as connection:
        connection.execute("CREATE TRIGGER refuse_purge BEFORE DELETE ON papers BEGIN SELECT RAISE(ABORT,'simulated failure'); END")
    before = {name: rows(store, name) for name in ("papers", "notes", "note_versions")}
    result = empty(client, inspected["preview_id"])
    assert result.status_code == 422, result.text
    assert path.is_file()
    assert before == {name: rows(store, name) for name in before}
    assert rows(store, "notes")[0]["id"] == created["id"]


def test_unlink_failure_reports_retained_pdf_without_undoing_db_purge(client, monkeypatch):
    current = paper(client)
    store = client.app.state.store
    path = Path(store.source(current["id"])["pdf_path"])
    delete_paper(client, current)
    inspected = preview(client)
    original_unlink = Path.unlink
    def denied_unlink(self, *args, **kwargs):
        if self == path:
            raise PermissionError("Simulated PDF in use")
        return original_unlink(self, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", denied_unlink)
    response = empty(client, inspected["preview_id"])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["papers_count"] == 1 and result["pdfs_deleted"] == 0
    assert result["retained_files_count"] == 1 and result["warnings"]
    assert path.is_file() and rows(store, "papers") == []
