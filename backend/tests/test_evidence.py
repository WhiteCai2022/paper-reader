from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import evidence
from backend.main import create_app
from backend.tests.test_api import upload


@pytest.fixture
def client(tmp_path, monkeypatch):
    app = create_app(data_dir=tmp_path / "data", frontend_dist=tmp_path / "dist")
    with TestClient(app, base_url="http://127.0.0.1:8000") as value:
        monkeypatch.setattr(evidence, "PdfReader", lambda path: SimpleNamespace(pages=["sample"] * 5))
        monkeypatch.setattr(evidence, "extract_source", lambda page: "We study adaptive partitioning for efficient inference.\nThe budget is limited.")
        app.state.reader.call_provider = lambda *args: pytest.fail("Evidence checks must not call a paid model")
        yield value


def test_quote_presence_is_local_and_not_semantic_verification(client):
    paper = upload(client)
    result = client.post(f"/api/papers/{paper['id']}/evidence/check", json={"page": 1, "quote": "We study adaptive\npartitioning for efficient inference."})
    assert result.status_code == 200, result.text
    assert result.json()["matched"] is True and result.json()["status"] == "matched"
    assert "不代表" in result.json()["message"]
    assert client.get("/api/translation/settings").json()["spent_cny"] == 0


def test_unknown_wrong_case_and_repeated_quotes_are_not_claimed_as_verified(client, monkeypatch):
    paper = upload(client)
    endpoint = f"/api/papers/{paper['id']}/evidence/check"
    assert client.post(endpoint, json={"page": 1, "quote": "We study an invented experimental result."}).json()["status"] == "not_found"
    assert client.post(endpoint, json={"page": 1, "quote": "WE STUDY ADAPTIVE PARTITIONING"}).json()["matched"] is False
    monkeypatch.setattr(evidence, "extract_source", lambda page: "Repeated evidence sentence. " * 2)
    result = client.post(endpoint, json={"page": 1, "quote": "Repeated evidence sentence."}).json()
    assert result["status"] == "ambiguous" and result["matched"] is False


def test_invalid_pages_missing_paper_and_unavailable_text(client, monkeypatch):
    paper = upload(client)
    endpoint = f"/api/papers/{paper['id']}/evidence/check"
    assert client.post(endpoint, json={"page": 6, "quote": "This quote is sufficiently long."}).status_code == 422
    assert client.post(endpoint, json={"page": True, "quote": "This quote is sufficiently long."}).status_code == 422
    assert client.post(endpoint, json={"page": 1, "quote": "short"}).status_code == 422
    assert client.post("/api/papers/missing/evidence/check", json={"page": 1, "quote": "This quote is sufficiently long."}).status_code == 404
    monkeypatch.setattr(evidence, "extract_source", lambda page: (_ for _ in ()).throw(ValueError("Unreadable")))
    result = client.post(endpoint, json={"page": 1, "quote": "This quote is sufficiently long."}).json()
    assert result["status"] == "unavailable" and result["matched"] is False
