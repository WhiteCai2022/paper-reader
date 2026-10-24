import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from backend import main
from backend.main import create_app
from backend.models import MAX_SORT_ORDER


def pdf_bytes(pages=5):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=600, height=800)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


@pytest.fixture
def client(tmp_path):
    app = create_app(data_dir=tmp_path / "data", frontend_dist=tmp_path / "dist")
    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        yield test_client


def upload(client, name="paper.pdf", title="Example paper", pages=5):
    response = client.post("/api/papers", files={"file": (name, pdf_bytes(pages), "application/pdf")}, data={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


def add_note(client, paper_id, **fields):
    value = {"title": "Concept", "page_start": 2, "page_end": 3, "kind": "concept", "content": "Some **Markdown**.", **fields}
    response = client.post(f"/api/papers/{paper_id}/notes", json=value)
    assert response.status_code == 201, response.text
    return response.json()


def logical_notes(paper):
    return [{name: value for name, value in note.items() if name != "id"} for note in paper["notes"]]


def test_health_list_and_paper_crud(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/papers").json() == []
    paper = upload(client)
    assert paper["page_count"] == 5
    assert paper["status"] == "unread"
    assert paper["progress"] == {"page": 1, "zoom": 1.0, "active_note_id": None}
    assert paper["year"] is None
    assert "pdf_path" not in paper
    assert client.get("/api/papers").json()[0]["id"] == paper["id"]
    response = client.patch(f"/api/papers/{paper['id']}", json={"title": "Updated", "authors": "A; B", "venue": "TMC", "year": 2026, "tags": ["DNN", "DNN", " reading "], "status": "reading"})
    assert response.status_code == 200
    assert response.json()["tags"] == ["DNN", "reading"]
    assert response.json()["year"] == 2026
    assert client.patch(f"/api/papers/{paper['id']}", json={"year": None}).json()["year"] is None
    assert client.get(f"/api/papers/{paper['id']}/pdf").content == pdf_bytes()
    source = client.app.state.store.source(paper["id"])
    assert Path(source["pdf_path"]).exists()
    assert client.delete(f"/api/papers/{paper['id']}").status_code == 204
    assert Path(source["pdf_path"]).exists()
    assert client.get(f"/api/papers/{paper['id']}").status_code == 404
    assert client.get(f"/api/papers/{paper['id']}/pdf").status_code == 404
    assert client.post(f"/api/library/trash/paper/{paper['id']}/restore").status_code == 200
    assert client.get(f"/api/papers/{paper['id']}/pdf").content == pdf_bytes()


def test_notes_crud_and_progress(client):
    paper = upload(client)
    note = add_note(client, paper["id"])
    second = add_note(client, paper["id"], title="Second")
    assert second["sort_order"] > note["sort_order"]
    response = client.put(f"/api/papers/{paper['id']}/notes/{note['id']}", json={"completed": True, "content": "Updated"})
    assert response.status_code == 200
    assert response.json()["completed"] is True
    progress = client.patch(f"/api/papers/{paper['id']}/progress", json={"page": 4, "zoom": 1.5, "active_note_id": note["id"], "status": "done"})
    assert progress.status_code == 200
    assert progress.json() == {"page": 4, "zoom": 1.5, "active_note_id": note["id"]}
    assert client.get(f"/api/papers/{paper['id']}").json()["status"] == "done"
    assert client.delete(f"/api/papers/{paper['id']}/notes/{note['id']}").status_code == 204
    detail = client.get(f"/api/papers/{paper['id']}").json()
    assert detail["progress"]["active_note_id"] is None
    assert detail["notes_count"] == 1
    assert client.delete(f"/api/papers/{paper['id']}/notes/{note['id']}").status_code == 404


@pytest.mark.parametrize("note", [
    {"page_start": 0}, {"page_start": -1}, {"page_start": 6}, {"page_start": 4, "page_end": 2},
    {"page_end": 6}, {"page_start": 1.5}, {"page_start": True}, {"kind": "unknown"}, {"completed": "false"},
])
def test_note_validation(client, note):
    paper = upload(client)
    response = client.post(f"/api/papers/{paper['id']}/notes", json={"page_start": 1, **note})
    assert response.status_code == 422
    assert client.get(f"/api/papers/{paper['id']}").json()["notes_count"] == 0


@pytest.mark.parametrize("value", [{"page": 0}, {"page": 6}, {"zoom": 0}, {"zoom": 5}, {"status": "invalid"}, {"page": None}, {"active_note_id": "missing"}])
def test_progress_validation(client, value):
    paper = upload(client)
    assert client.patch(f"/api/papers/{paper['id']}/progress", json=value).status_code == 422


def test_note_does_not_cross_papers(client):
    first, second = upload(client), upload(client)
    note = add_note(client, first["id"])
    assert client.put(f"/api/papers/{second['id']}/notes/{note['id']}", json={"content": "wrong"}).status_code == 404
    assert client.patch(f"/api/papers/{second['id']}/progress", json={"active_note_id": note["id"]}).status_code == 422


def test_upload_validation_and_safe_name(client, monkeypatch):
    response = client.post("/api/papers", files={"file": ("fake.pdf", b"%PDF-1.7\nnot really a PDF", "application/pdf")})
    assert response.status_code == 422
    paper = upload(client, name="../../outside.pdf")
    assert paper["file_name"] == "outside.pdf"
    source = Path(client.app.state.store.source(paper["id"])["pdf_path"])
    assert source.parent == client.app.state.store.uploads_dir
    assert source.name != paper["file_name"]
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 16)
    response = client.post("/api/papers", files={"file": ("large.pdf", pdf_bytes(), "application/pdf")})
    assert response.status_code == 413
    assert list(client.app.state.store.uploads_dir.glob("*.part")) == []
    assert len(client.get("/api/papers").json()) == 1


def test_encrypted_upload_is_rejected_without_leftovers(client):
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    writer.encrypt("password")
    stream = io.BytesIO()
    writer.write(stream)
    response = client.post("/api/papers", files={"file": ("encrypted.pdf", stream.getvalue(), "application/pdf")})
    assert response.status_code == 422
    assert list(client.app.state.store.uploads_dir.iterdir()) == []
    assert client.get("/api/papers").json() == []


def test_pdf_range_and_static_path_boundaries(client):
    paper = upload(client)
    response = client.get(f"/api/papers/{paper['id']}/pdf", headers={"Range": "bytes=0-31"})
    assert response.status_code == 206
    assert response.content == pdf_bytes()[:32]
    assert response.headers["content-range"] == f"bytes 0-31/{len(pdf_bytes())}"
    assert client.get("/..%2f..%2fREADME.md").status_code == 404
    assert client.get("/swagger/..%2f..%2fREADME.md").status_code == 404


def test_sort_order_integer_boundaries(client):
    paper = upload(client)
    path = f"/api/papers/{paper['id']}/notes"
    assert client.post(path, json={"sort_order": 10 ** 100}).status_code == 422
    first = add_note(client, paper["id"], sort_order=MAX_SORT_ORDER)
    second = add_note(client, paper["id"], title="Next")
    assert second["sort_order"] == MAX_SORT_ORDER
    assert client.put(f"{path}/{first['id']}", json={"sort_order": MAX_SORT_ORDER + 1}).status_code == 422
    detail = client.get(f"/api/papers/{paper['id']}").json()
    assert [note["id"] for note in detail["notes"]] == [first["id"], second["id"]]


def test_import_size_and_encoding_are_atomic(client, monkeypatch):
    paper = upload(client)
    existing = add_note(client, paper["id"])
    path = f"/api/papers/{paper['id']}/import"
    response = client.post(path, files={"file": ("notes.md", b"\xff\xfeinvalid")}, data={"mode": "replace"})
    assert response.status_code == 422
    monkeypatch.setattr(main, "MAX_IMPORT_BYTES", 8)
    assert client.post(path, files={"file": ("notes.md", b"123456789")}, data={"mode": "replace"}).status_code == 413
    assert client.get(f"/api/papers/{paper['id']}").json()["notes"] == [existing]


def test_import_json_validation_is_atomic(client):
    paper = upload(client)
    existing = add_note(client, paper["id"])
    value = {"schema_version": 1, "paper": {"title": "Must not change"}, "notes": [{"title": "Valid", "page_start": 2}, {"title": "Invalid", "page_start": 8}]}
    response = client.post(f"/api/papers/{paper['id']}/import", files={"file": ("notes.json", json.dumps(value), "application/json")}, data={"mode": "replace"})
    assert response.status_code == 422
    detail = client.get(f"/api/papers/{paper['id']}").json()
    assert detail["title"] == paper["title"]
    assert detail["notes"] == [existing]
    assert client.post(f"/api/papers/{paper['id']}/import", files={"file": ("bad.json", "{bad")}, data={"mode": "replace"}).status_code == 422
    assert client.get(f"/api/papers/{paper['id']}").json()["notes"] == [existing]


def test_import_database_failure_rolls_back(client, monkeypatch):
    paper = upload(client)
    existing = add_note(client, paper["id"])
    database = client.app.state.store
    original = database.insert_note
    calls = 0

    def failing_insert(connection, paper_id, note, order):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Simulated storage failure")
        return original(connection, paper_id, note, order)

    monkeypatch.setattr(database, "insert_note", failing_insert)
    with pytest.raises(RuntimeError):
        database.import_notes(paper["id"], [existing, existing], {"title": "Rolled back"}, "replace")
    assert database.get_paper(paper["id"])["notes"] == [existing]
    assert database.get_paper(paper["id"])["title"] == paper["title"]


@pytest.mark.parametrize("export_format,extension", [("json", "json"), ("markdown", "md")])
def test_export_round_trip(client, export_format, extension):
    source = upload(client)
    add_note(client, source["id"], completed=True, sort_order=4, content="# Header\n\nA formula: $x^2$.\n\n```md\n## [p. 99] Literal heading\n```", kind="method")
    add_note(client, source["id"], title="Second", page_start=5, page_end=5, sort_order=9, kind="exercise")
    client.patch(f"/api/papers/{source['id']}", json={"authors": "A; B", "tags": ["math"], "year": 2024, "status": "reading"})
    original = client.get(f"/api/papers/{source['id']}").json()
    exported = client.get(f"/api/papers/{source['id']}/export", params={"format": export_format})
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    target = upload(client, title="Destination")
    response = client.post(f"/api/papers/{target['id']}/import", files={"file": (f"notes.{extension}", exported.content)}, data={"mode": "replace"})
    assert response.status_code == 200, response.text
    restored = response.json()
    assert logical_notes(restored) == logical_notes(original)
    for name in ("title", "short_title", "authors", "venue", "year", "tags", "status"):
        assert restored[name] == original[name]


def test_plain_markdown_import_and_append(client):
    paper = upload(client)
    add_note(client, paper["id"], title="Original")
    markdown = "## [p. 2-3] Method\n\nBody\n\n## [p. 4] Experiment\n\nResults"
    response = client.post(f"/api/papers/{paper['id']}/import", files={"file": ("notes.md", markdown)})
    assert response.status_code == 200
    assert [note["title"] for note in response.json()["notes"]] == ["Original", "Method", "Experiment"]
    assert response.json()["notes"][1]["page_end"] == 3
    response = client.post(f"/api/papers/{paper['id']}/import", files={"file": ("whole.md", "# Whole\n\nText")}, data={"mode": "replace"})
    assert response.status_code == 200
    assert response.json()["notes_count"] == 1
    assert response.json()["notes"][0]["page_start"] == 1
    assert response.json()["notes"][0]["content"] == "# Whole\n\nText"


def test_invalid_markdown_does_not_replace(client):
    paper = upload(client)
    existing = add_note(client, paper["id"])
    response = client.post(f"/api/papers/{paper['id']}/import", files={"file": ("bad.md", "## [p. 2-20] Invalid\nBody")}, data={"mode": "replace"})
    assert response.status_code == 422
    assert client.get(f"/api/papers/{paper['id']}").json()["notes"] == [existing]


def test_seed_nonoverwrite_and_source_preservation(tmp_path, monkeypatch):
    directory = tmp_path / "data"
    directory.mkdir()
    original = tmp_path / "original.pdf"
    original.write_bytes(pdf_bytes())
    seed = [{"id": "P01", "title": "Seed title", "short_title": "Seed", "authors": "Author", "venue": "Venue", "year": 2025, "tags": ["seed"], "pdf_path": str(original), "notes": [{"title": "Seed note", "page_start": 1, "content": "Original"}]}]
    (directory / "seed.json").write_text(json.dumps(seed), encoding="utf-8")
    monkeypatch.setenv("PAPER_READER_DATA_DIR", str(directory))
    with TestClient(create_app(), base_url="http://127.0.0.1:8000") as first:
        assert first.get("/api/papers/P01").json()["title"] == "Seed title"
        first.patch("/api/papers/P01", json={"title": "User edit"})
        first.patch("/api/papers/P01/progress", json={"page": 4, "zoom": 1.5})
        note_id = first.get("/api/papers/P01").json()["notes"][0]["id"]
        first.put(f"/api/papers/P01/notes/{note_id}", json={"content": "User note"})
    with TestClient(create_app(), base_url="http://127.0.0.1:8000") as second:
        detail = second.get("/api/papers/P01").json()
        assert detail["title"] == "User edit"
        assert detail["progress"]["page"] == 4
        assert detail["notes_count"] == 1
        assert detail["notes"][0]["content"] == "User note"
        assert second.delete("/api/papers/P01").status_code == 204
    assert original.exists()
    assert original.read_bytes() == pdf_bytes()
    with TestClient(create_app(), base_url="http://127.0.0.1:8000") as third:
        assert third.get("/api/papers/P01").status_code == 404
        assert third.get("/api/papers").json() == []


def test_origin_protection(client):
    paper = upload(client)
    path = f"/api/papers/{paper['id']}"
    for origin in ("https://evil.example", "null", "http://127.0.0.1:9000", "http://localhost.evil.example:8000"):
        assert client.patch(path, json={"title": "Blocked"}, headers={"Origin": origin}).status_code == 403
    for origin in ("http://localhost:8000", "http://127.0.0.1:8000"):
        assert client.patch(path, json={"title": "Allowed"}, headers={"Origin": origin}).status_code == 200


def test_host_rebinding_protection(client):
    paper = upload(client)
    for path in ("/api/papers", f"/api/papers/{paper['id']}/pdf", "/api/docs"):
        assert client.get(path, headers={"Host": "evil.example:8000"}).status_code == 400
        assert client.get(path, headers={"Host": "localhost.evil.example:8000"}).status_code == 400
    assert client.get("/api/health", headers={"Host": "localhost:8000"}).status_code == 200


def test_spa_does_not_swallow_api_404_and_docs_are_local(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>Reader</html>", encoding="utf-8")
    swagger = dist / "swagger"
    swagger.mkdir()
    for name in ("swagger-ui-bundle.js", "swagger-ui.css", "favicon-32x32.png"):
        (swagger / name).write_bytes(b"local asset")
    with TestClient(create_app(tmp_path / "data", dist), base_url="http://127.0.0.1:8000") as client:
        assert client.get("/reading/P01").status_code == 200
        response = client.get("/api/missing")
        assert response.status_code == 404
        assert response.json()["detail"] == "API endpoint not found"
        assert client.get("/api/papers/missing/pdf").status_code == 404
        assert client.get("/api/openapi.json").status_code == 200
        docs = client.get("/api/docs").text
        assert 'src="/swagger/swagger-ui-bundle.js"' in docs
        assert 'href="/swagger/favicon-32x32.png"' in docs
        assert "cdn.jsdelivr.net" not in docs
        for name in ("swagger-ui-bundle.js", "swagger-ui.css", "favicon-32x32.png"):
            assert client.get(f"/swagger/{name}").content == b"local asset"
        assert client.get("/swagger/private.txt").status_code == 404


def test_import_schema_and_metadata_validation(client):
    paper = upload(client)
    for document in (
        {"schema_version": 2, "notes": []},
        {"schema_version": 1, "paper": {"pdf_path": "C:/private.pdf"}, "notes": []},
        {"schema_version": 1, "paper": {"title": " "}, "notes": []},
        {"schema_version": 1, "notes": [{"page_start": 2, "page_end": 1}]},
    ):
        response = client.post(f"/api/papers/{paper['id']}/import", files={"file": ("notes.json", json.dumps(document))}, data={"mode": "replace"})
        assert response.status_code == 422
    assert client.patch(f"/api/papers/{paper['id']}", json={"title": None}).status_code == 422


def test_reading_task_is_single_paper_read_only_and_free(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-must-not-appear")
    paper = upload(client, title="Only this paper", pages=5)
    note = add_note(client, paper["id"])
    upload(client, title="Another unrelated paper")
    source = client.app.state.store.source(paper["id"])
    response = client.get(f"/api/papers/{paper['id']}/reading-task", params={"focus": "Check queue assumptions"})
    assert response.status_code == 200
    value = response.json()
    assert value["paper_id"] == paper["id"]
    assert value["mode"] == "assistant-assisted"
    assert value["status"] == "prepared"
    assert value["calls_external_api"] is False
    assert value["reading_style"] == "learning-tutor-v1"
    text = value["request"]
    assert "Only this paper" in text
    assert "Another unrelated paper" not in text
    assert source["pdf_path"] in text.replace("\\\\", "\\")
    assert "Check queue assumptions" in text
    assert "sk-must-not-appear" not in text
    for requirement in ("不包含自测", "原文", "单位", "算法", "图表", "局限", "待核验", "replace", "schema_version"):
        assert requirement in text
    for requirement in ("学习导师", "教学构造，非论文实验", "拉格朗日", "公式逐步推导", "图表未读取", "至多一条"):
        assert requirement in text
    assert client.get(f"/api/papers/{paper['id']}").json()["notes"] == [note]
    with client.app.state.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM translation_jobs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM translation_receipts").fetchone()[0] == 0
    assert not (client.app.state.store.data_dir / "analyses").exists()


def test_reading_task_download_and_validation(client):
    paper = upload(client)
    path = f"/api/papers/{paper['id']}/reading-task"
    expected = client.get(path, params={"focus": "Math detail"}).json()["request"]
    download = client.get(path, params={"focus": "Math detail", "format": "markdown"})
    assert download.status_code == 200
    assert download.text == expected
    assert download.headers["content-type"].startswith("text/markdown")
    assert "attachment" in download.headers["content-disposition"]
    assert client.get(path, params={"focus": "a" * 2001}).status_code == 422
    assert client.get(path, params={"format": "exe"}).status_code == 422
    assert client.get("/api/papers/missing/reading-task").status_code == 404
    source = client.app.state.store.source(paper["id"])
    Path(source["pdf_path"]).unlink()
    assert client.get(path).status_code == 404
