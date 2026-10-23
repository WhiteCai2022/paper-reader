import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.tests.test_api import add_note, pdf_bytes, upload


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "data", tmp_path / "dist"), base_url="http://127.0.0.1:8000") as test_client:
        yield test_client


def create_category(client, name="Models"):
    response = client.post("/api/categories", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def assign(client, paper, category_ids):
    response = client.put(f"/api/papers/{paper['id']}/categories", json={"category_ids": category_ids})
    assert response.status_code == 200, response.text
    return response.json()


def counts(client):
    return {category["id"]: category["paper_count"] for category in client.get("/api/categories").json()}


def test_default_and_category_crud(client):
    assert client.get("/api/categories").json() == [{"id": "default", "name": "默认分类", "paper_count": 0, "is_default": True}]
    paper = upload(client)
    assert paper["category_ids"] == []
    assert counts(client) == {"default": 1}
    category = create_category(client, "  Models  ")
    assert category["name"] == "Models"
    assert category["paper_count"] == 0
    assert category["is_default"] is False
    assert client.post("/api/categories", json={"name": "models"}).status_code == 409
    second = create_category(client, "Queues")
    path = f"/api/categories/{category['id']}"
    assert client.patch(path, json={"name": "Queues"}).status_code == 409
    assert client.patch(path, json={"name": "Updated"}).json()["name"] == "Updated"
    assert client.patch("/api/categories/missing", json={"name": "Name"}).status_code == 404
    assert client.delete(path).status_code == 204
    assert client.delete(path).status_code == 404
    assert counts(client) == {"default": 1, second["id"]: 0}
    assert client.delete("/api/categories/default").status_code == 409
    assert client.patch("/api/categories/default", json={"name": "Other"}).status_code == 409


@pytest.mark.parametrize("name", ["", "   ", "a\nb", "a\rb", "\x00", "a\tb", "默认分类", "全部文献", "x" * 81])
def test_category_name_validation(client, name):
    assert client.post("/api/categories", json={"name": name}).status_code == 422
    assert len(client.get("/api/categories").json()) == 1


def test_multiple_categories_removal_and_atomic_validation(client):
    paper = upload(client)
    note = add_note(client, paper["id"], content="Keep notes intact")
    client.patch(f"/api/papers/{paper['id']}/progress", json={"page": 3, "active_note_id": note["id"]})
    a, b = create_category(client, "A"), create_category(client, "B")
    value = assign(client, paper, [b["id"], a["id"], b["id"]])
    assert value["category_ids"] == sorted([a["id"], b["id"]])
    assert value["notes"] == [note]
    assert value["progress"]["page"] == 3
    assert counts(client) == {"default": 0, a["id"]: 1, b["id"]: 1}
    assert client.get("/api/papers").json()[0]["category_ids"] == value["category_ids"]
    path = f"/api/papers/{paper['id']}/categories"
    for invalid in ({"category_ids": [a["id"], "missing"]}, {"category_ids": ["default"]}, {"category_ids": None}, {"category_ids": ["x"] * 101}, {}):
        assert client.put(path, json=invalid).status_code == 422
        assert client.get(f"/api/papers/{paper['id']}").json() == value
    assert client.put("/api/papers/missing/categories", json={"category_ids": []}).status_code == 404
    assign(client, paper, [b["id"]])
    assert counts(client) == {"default": 0, a["id"]: 0, b["id"]: 1}
    cleared = assign(client, paper, [])
    assert cleared["category_ids"] == []
    assert cleared["notes"] == [note]
    assert counts(client)["default"] == 1


def test_bulk_category_membership_only_changes_that_category(client):
    first, second, third = upload(client), upload(client), upload(client)
    a, b = create_category(client, "A"), create_category(client, "B")
    assign(client, first, [b["id"]])
    path = f"/api/categories/{a['id']}/papers"
    response = client.put(path, json={"paper_ids": [first["id"], second["id"], second["id"]]})
    assert response.status_code == 200
    assert response.json()["paper_count"] == 2
    assert counts(client) == {"default": 1, a["id"]: 2, b["id"]: 1}
    assert client.put(path, json={"paper_ids": [third["id"], "missing"]}).status_code == 422
    assert counts(client)[a["id"]] == 2
    assert client.put(path, json={"paper_ids": [third["id"]]}).json()["paper_count"] == 1
    assert client.get(f"/api/papers/{first['id']}").json()["category_ids"] == [b["id"]]
    assert client.get(f"/api/papers/{second['id']}").json()["category_ids"] == []
    assert client.put(path, json={"paper_ids": []}).json()["paper_count"] == 0
    assert client.put("/api/categories/default/papers", json={"paper_ids": []}).status_code == 409
    assert client.put("/api/categories/missing/papers", json={"paper_ids": []}).status_code == 404


def test_upload_into_categories_and_invalid_upload_cleanup(client):
    a, b = create_category(client, "A"), create_category(client, "B")
    response = client.post("/api/papers", files={"file": ("paper.pdf", pdf_bytes(), "application/pdf")}, data={"category_ids": [a["id"], b["id"]]})
    assert response.status_code == 201, response.text
    assert response.json()["category_ids"] == sorted([a["id"], b["id"]])
    files = set(client.app.state.store.uploads_dir.iterdir())
    for ids in (["missing"], [a["id"], "missing"], ["default"]):
        response = client.post("/api/papers", files={"file": ("bad.pdf", pdf_bytes(), "application/pdf")}, data={"category_ids": ids})
        assert response.status_code == 422
        assert set(client.app.state.store.uploads_dir.iterdir()) == files
        assert len(client.get("/api/papers").json()) == 1


def test_deleting_category_keeps_pdfs_notes_and_other_memberships(client):
    first, second = upload(client), upload(client)
    note = add_note(client, first["id"])
    a, b = create_category(client, "A"), create_category(client, "B")
    original_pdf = client.get(f"/api/papers/{first['id']}/pdf").content
    assign(client, first, [a["id"], b["id"]])
    assign(client, second, [a["id"]])
    assert client.delete(f"/api/categories/{a['id']}").status_code == 204
    assert counts(client) == {"default": 1, b["id"]: 1}
    assert client.get(f"/api/papers/{first['id']}").json()["notes"] == [note]
    assert client.get(f"/api/papers/{first['id']}").json()["category_ids"] == [b["id"]]
    assert client.get(f"/api/papers/{first['id']}/pdf").content == original_pdf
    assert client.get(f"/api/papers/{second['id']}").json()["category_ids"] == []
    assert client.delete(f"/api/papers/{first['id']}").status_code == 204
    assert counts(client)[b["id"]] == 0
    with client.app.state.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM paper_categories").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM translation_jobs").fetchone()[0] == 0


def test_categories_survive_restart_and_notes_import_does_not_change_them(tmp_path):
    data = tmp_path / "data"
    with TestClient(create_app(data), base_url="http://127.0.0.1:8000") as client:
        paper = upload(client)
        category = create_category(client)
        assign(client, paper, [category["id"]])
    with TestClient(create_app(data), base_url="http://127.0.0.1:8000") as client:
        assert counts(client) == {"default": 0, category["id"]: 1}
        document = {"schema_version": 1, "notes": [{"title": "New", "content": "Notes", "page_start": 1}]}
        response = client.post(f"/api/papers/{paper['id']}/import", files={"file": ("notes.json", json.dumps(document))}, data={"mode": "replace"})
        assert response.status_code == 200
        assert response.json()["category_ids"] == [category["id"]]


def test_existing_database_upgrade_is_additive(tmp_path):
    data = tmp_path / "data"
    with TestClient(create_app(data), base_url="http://127.0.0.1:8000") as client:
        paper = upload(client)
        add_note(client, paper["id"])
        client.patch(f"/api/papers/{paper['id']}/progress", json={"page": 4})
        original = client.get(f"/api/papers/{paper['id']}").json()
        pdf = Path(client.app.state.store.source(paper["id"])["pdf_path"])
        with client.app.state.store.connection() as connection:
            connection.execute("DROP TABLE paper_categories")
            connection.execute("DROP TABLE categories")
    with TestClient(create_app(data), base_url="http://127.0.0.1:8000") as client:
        assert client.get(f"/api/papers/{paper['id']}").json() == original
        assert pdf.read_bytes() == pdf_bytes()
        assert counts(client) == {"default": 1}


def test_category_endpoints_have_same_origin_protection(client):
    paper = upload(client)
    category = create_category(client)
    headers = {"Origin": "https://untrusted.example"}
    assert client.post("/api/categories", json={"name": "Other"}, headers=headers).status_code == 403
    assert client.put(f"/api/papers/{paper['id']}/categories", json={"category_ids": []}, headers=headers).status_code == 403
    assert client.put(f"/api/categories/{category['id']}/papers", json={"paper_ids": []}, headers=headers).status_code == 403
    assert client.delete(f"/api/categories/{category['id']}", headers=headers).status_code == 403
