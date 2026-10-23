import io
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend import bibliography, main
from backend.main import create_app
from backend.tests.test_api import add_note, upload


def pdf_data(info=None, xmp=None, content=None):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    if info:
        writer.add_metadata(info)
    if xmp is not None:
        stream = DecodedStreamObject()
        stream.set_data(xmp.encode("utf-8"))
        stream.update({NameObject("/Type"): NameObject("/Metadata"), NameObject("/Subtype"): NameObject("/XML")})
        writer.root_object[NameObject("/Metadata")] = writer._add_object(stream)
    if content:
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(content.encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


XMP = '''<x:xmpmeta xmlns:x="adobe:ns:meta/">
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/" rdf:about="">
<dc:title><rdf:Alt><rdf:li xml:lang="x-default">Actual Embedded Paper Title</rdf:li></rdf:Alt></dc:title>
<dc:creator><rdf:Seq><rdf:li>Alice Example</rdf:li><rdf:li>Bob Example</rdf:li><rdf:li>Bob Example</rdf:li></rdf:Seq></dc:creator>
</rdf:Description>
<rdf:Description xmlns:prism="http://prismstandard.org/namespaces/basic/3.0/" rdf:about="" prism:publicationName="Journal of Tests">
<prism:volume>12</prism:volume><prism:issueIdentifier>3</prism:issueIdentifier>
<prism:startingPage>10</prism:startingPage><prism:endingPage>19</prism:endingPage>
<prism:coverDisplayDate>March 2024</prism:coverDisplayDate><prism:doi>10.1234/test.paper</prism:doi>
</rdf:Description></rdf:RDF></x:xmpmeta>'''


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "data", tmp_path / "dist"), base_url="http://127.0.0.1:8000") as test_client:
        yield test_client


def preview(client, pdf, name="random_file.pdf"):
    return client.post("/api/papers/metadata", files={"file": (name, pdf, "application/pdf")})


def test_xmp_preview_prefills_full_bibliography_without_import_or_network(client, monkeypatch):
    monkeypatch.setattr(bibliography, "urlopen", lambda *args, **kwargs: pytest.fail("Local extraction must not access the network"))
    data = pdf_data({"/Title": "build_output.pdf", "/Author": "Only the first author", "/CreationDate": "D:20300101000000"}, XMP)
    response = preview(client, data)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["title"] == "Actual Embedded Paper Title"
    assert value["authors"] == "Alice Example; Bob Example"
    assert value["venue"] == "Journal of Tests 12(3):10-19"
    assert value["year"] == 2024
    assert value["doi"] == "10.1234/test.paper"
    assert value["page_count"] == 1
    assert value["sources"]["title"] == "xmp"
    assert client.get("/api/papers").json() == []
    assert list(client.app.state.store.uploads_dir.iterdir()) == []
    with client.app.state.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM translation_jobs").fetchone()[0] == 0


def test_upload_without_overrides_uses_detected_data_and_still_accepts_legacy_title(client):
    data = pdf_data(xmp=XMP)
    paper = client.post("/api/papers", files={"file": ("random.pdf", data)}).json()
    assert paper["title"] == "Actual Embedded Paper Title"
    assert paper["authors"] == "Alice Example; Bob Example"
    assert paper["year"] == 2024
    assert paper["doi"] == "10.1234/test.paper"
    assert paper["category_ids"] == []
    response = client.post("/api/papers", files={"file": ("random.pdf", data)}, data={"title": "Manual title", "short_title": "Short"})
    assert response.status_code == 201
    assert response.json()["title"] == "Manual title"
    assert response.json()["short_title"] == "Short"


def test_user_metadata_overrides_can_clear_detected_fields_and_preserve_categories(client):
    category = client.post("/api/categories", json={"name": "New"}).json()
    metadata = {"title": "Edited title", "authors": "", "venue": "Edited publication", "year": None, "doi": "https://doi.org/10.1234/edited", "short_title": "Custom"}
    response = client.post("/api/papers", files={"file": ("random.pdf", pdf_data(xmp=XMP))}, data={"metadata": json.dumps(metadata), "category_ids": category["id"]})
    assert response.status_code == 201, response.text
    paper = response.json()
    for key, value in metadata.items():
        assert paper[key] == ("10.1234/edited" if key == "doi" else value)
    assert paper["category_ids"] == [category["id"]]


@pytest.mark.parametrize("metadata", ["not JSON", "[]", '{"title":" "}', '{"doi":"https://evil.example/x"}', '{"pdf_path":"C:/private.pdf"}', '{"year":2500}'])
def test_invalid_metadata_does_not_leave_registered_paper_or_files(client, metadata):
    response = client.post("/api/papers", files={"file": ("paper.pdf", pdf_data(xmp=XMP))}, data={"metadata": metadata})
    assert response.status_code == 422
    assert client.get("/api/papers").json() == []
    assert list(client.app.state.store.uploads_dir.iterdir()) == []


def test_missing_metadata_uses_filename_not_pdf_creation_year(client):
    response = preview(client, pdf_data({"/Title": "Microsoft Word", "/CreationDate": "D:20300101000000"}), "local_name.pdf")
    value = response.json()
    assert value["title"] == "local name"
    assert value["year"] is None
    assert value["venue"] == ""
    assert value["authors"] == ""
    assert value["sources"]["title"] == "filename"
    assert value["warnings"]


def test_first_page_fallback_handles_scaled_fonts_and_doi_without_using_body_dates(client):
    content = "BT /F1 1 Tf 20 0 0 20 50 700 Tm (A Scientific Title With Scaled Fonts) Tj ET\nBT /F1 10 Tf 50 600 Td (Digital Object Identifier 10.1234/scaled) Tj ET\nBT /F1 10 Tf 50 580 Td (The study collected data in 2019.) Tj ET"
    value = preview(client, pdf_data({"/Title": "output.pdf"}, content=content)).json()
    assert value["title"] == "A Scientific Title With Scaled Fonts"
    assert value["doi"] == "10.1234/scaled"
    assert value["sources"]["title"] == "first_page"
    assert value["year"] is None


def test_multiple_first_page_dois_are_not_silently_assigned(client):
    content = "BT /F1 12 Tf 50 700 Td (10.1234/one 10.1234/two) Tj ET"
    value = preview(client, pdf_data(content=content)).json()
    assert value["doi"] == ""
    assert any("多个 DOI" in warning for warning in value["warnings"])


@pytest.mark.parametrize("xmp", ["<not-valid-xml", '<!DOCTYPE x [<!ENTITY x "unexpected">]><x>&x;</x>'])
def test_bad_or_unsafe_xmp_does_not_erase_docinfo(client, xmp):
    value = preview(client, pdf_data({"/Title": "A Good DocInfo Title", "/Author": "Alice"}, xmp)).json()
    assert value["title"] == "A Good DocInfo Title"
    assert value["authors"] == "Alice"
    assert value["warnings"]


def test_preview_validation_and_size_cleanup(client, monkeypatch):
    assert preview(client, b"not a PDF").status_code == 422
    writer = PdfWriter(); writer.add_blank_page(width=600, height=800); writer.encrypt("password")
    stream = io.BytesIO(); writer.write(stream)
    assert preview(client, stream.getvalue()).status_code == 422
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 16)
    assert preview(client, pdf_data()).status_code == 413
    assert list(client.app.state.store.uploads_dir.iterdir()) == []


def record(**overrides):
    return {"DOI": "10.1234/test.paper", "title": ["A Study of H<sub>2</sub> &amp; Networks"], "author": [{"given": "Alice", "family": "Example"}, {"name": "Research Team"}], "container-title": ["Journal of Tests"], "volume": "12", "issue": "3", "page": "10-19", "published-print": {"date-parts": [[2024, 3]]}, "published-online": {"date-parts": [[2023, 12]]}, **overrides}


class FakeResponse(io.BytesIO):
    pass


def test_doi_lookup_uses_fixed_crossref_host_and_sends_no_pdf_or_api_key(client, monkeypatch):
    requests = []
    def fake_open(request, timeout):
        requests.append(request)
        assert request.data is None
        assert urlsplit(request.full_url).hostname == "api.crossref.org"
        assert not urlsplit(request.full_url).query
        assert timeout == 6
        assert not request.has_header("Authorization")
        return FakeResponse(json.dumps({"message": record()}).encode())
    monkeypatch.setattr(bibliography, "urlopen", fake_open)
    value = client.post("/api/metadata/doi", json={"doi": "https://doi.org/10.1234/test.paper"}).json()
    assert value["title"] == "A Study of H2 & Networks"
    assert value["authors"] == "Alice Example; Research Team"
    assert value["venue"] == "Journal of Tests 12(3):10-19"
    assert value["year"] == 2024
    assert value["sources"]["title"] == "crossref"
    assert len(requests) == 1
    assert client.get("/api/papers").json() == []


@pytest.mark.parametrize("value", ["", "  ", "https://evil.example/secret", "file:///private.pdf", "10.1/abc", "10.1234/a\nb"])
def test_invalid_doi_never_makes_network_request(client, monkeypatch, value):
    monkeypatch.setattr(bibliography, "urlopen", lambda *args, **kwargs: pytest.fail("Invalid DOI must not access network"))
    assert client.post("/api/metadata/doi", json={"doi": value}).status_code == 422


@pytest.mark.parametrize("error,status", [(HTTPError("url", 404, "Not found", {}, None), 404), (HTTPError("url", 429, "Slow down", {}, None), 503), (URLError("offline"), 503), (TimeoutError(), 503)])
def test_lookup_failures_are_safe_and_not_retried(client, monkeypatch, error, status):
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise error
    monkeypatch.setattr(bibliography, "urlopen", fail)
    assert client.post("/api/metadata/doi", json={"doi": "10.1234/test.paper"}).status_code == status
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [{"message": record(DOI="10.1234/wrong")}, {"message": record(title=[])}, {"message": "invalid"}, {"message": record(title="not an array")}, {"message": record(author="not an array")}])
def test_mismatched_or_incomplete_lookup_is_rejected(client, monkeypatch, payload):
    monkeypatch.setattr(bibliography, "urlopen", lambda *args, **kwargs: FakeResponse(json.dumps(payload).encode()))
    assert client.post("/api/metadata/doi", json={"doi": "10.1234/test.paper"}).status_code == 502


def test_doi_survives_persistence_and_export_and_metadata_endpoints_are_origin_protected(client):
    paper = upload(client)
    response = client.patch(f"/api/papers/{paper['id']}", json={"doi": "https://doi.org/10.1234/test.paper"})
    assert response.status_code == 200
    assert response.json()["doi"] == "10.1234/test.paper"
    exported = client.get(f"/api/papers/{paper['id']}/export").json()
    assert exported["paper"]["doi"] == "10.1234/test.paper"
    assert client.patch(f"/api/papers/{paper['id']}", json={"doi": None}).status_code == 422
    headers = {"Origin": "https://untrusted.example"}
    assert client.post("/api/metadata/doi", json={"doi": "10.1234/test.paper"}, headers=headers).status_code == 403
    assert client.post("/api/papers/metadata", files={"file": ("paper.pdf", pdf_data())}, headers=headers).status_code == 403


def test_doi_migration_does_not_change_existing_papers_notes_or_categories(tmp_path):
    data = tmp_path / "data"
    with TestClient(create_app(data), base_url="http://127.0.0.1:8000") as client:
        paper = upload(client)
        note = add_note(client, paper["id"])
        category = client.post("/api/categories", json={"name": "Existing"}).json()
        client.put(f"/api/papers/{paper['id']}/categories", json={"category_ids": [category["id"]]})
        with client.app.state.store.connection() as connection:
            connection.execute("ALTER TABLE papers DROP COLUMN doi")
    with TestClient(create_app(data), base_url="http://127.0.0.1:8000") as client:
        restored = client.get(f"/api/papers/{paper['id']}").json()
        assert restored["doi"] == ""
        assert restored["notes"] == [note]
        assert restored["category_ids"] == [category["id"]]
