import io
import json
from zipfile import ZipFile

import pytest

from backend.models import AnnotationCreate
from backend.store import Store
from backend.tests.test_api import client, upload


def annotation(**changes):
    return {"page": 2, "quote": "An important claim in the original paper.",
            "rects": [{"x": .12, "y": .25, "width": .4, "height": .02},
                      {"x": .12, "y": .28, "width": .2, "height": .02}],
            "content": "需要核对这个假设的适用范围。", **changes}


def add(client, paper):
    response = client.post(f"/api/papers/{paper['id']}/annotations", json=annotation())
    assert response.status_code == 201, response.text
    return response.json()


def test_annotation_crud_is_persistent_scoped_and_independent_of_notes(client):
    paper, other = upload(client), upload(client, title="Other")
    url = f"/api/papers/{paper['id']}/annotations"
    item = add(client, paper)
    assert item["quote"] == annotation()["quote"]
    assert item["rects"] == annotation()["rects"]
    assert item["created_at"] and item["updated_at"]
    assert client.get(url).json() == [item]
    assert client.get(f"/api/papers/{paper['id']}").json()["annotations"] == [item]
    assert client.get(f"/api/papers/{other['id']}/annotations").json() == []
    other_url = f"/api/papers/{other['id']}/annotations/{item['id']}"
    assert client.patch(other_url, json={"content": "Not mine"}).status_code == 404
    assert client.delete(other_url).status_code == 404
    updated = client.patch(f"{url}/{item['id']}", json={"content": "  修改后的批注\n保留换行  "}).json()
    assert updated["content"] == "修改后的批注\n保留换行"
    assert updated["quote"] == item["quote"] and updated["rects"] == item["rects"]
    store = Store(client.app.state.store.data_dir)
    assert store.get_paper(paper["id"])["annotations"] == [updated]
    assert store.get_paper(paper["id"])["notes"] == []
    assert client.get("/api/translation/settings").json()["spent_cny"] == 0
    assert client.delete(f"{url}/{item['id']}").status_code == 204
    assert client.get(url).json() == []
    assert client.delete(f"{url}/{item['id']}").status_code == 404


@pytest.mark.parametrize("changes", [
    {"page": 0}, {"page": 6}, {"page": True}, {"quote": " "}, {"content": "\n "},
    {"quote": "a" * 10_001}, {"content": "a" * 20_001}, {"rects": []},
    {"rects": [{"x": .9, "y": .1, "width": .2, "height": .1}]},
    {"rects": [{"x": .1, "y": -.1, "width": .2, "height": .1}]},
    {"rects": [{"x": .1, "y": .1, "width": 0, "height": .1}]},
    {"rects": [annotation()["rects"][0]] * 513},
])
def test_invalid_annotations_never_write_partial_records(client, changes):
    paper = upload(client)
    url = f"/api/papers/{paper['id']}/annotations"
    assert client.post(url, json=annotation(**changes)).status_code == 422
    assert client.get(url).json() == []


def test_edit_does_not_allow_anchor_changes_or_null_content(client):
    paper = upload(client)
    item = add(client, paper)
    url = f"/api/papers/{paper['id']}/annotations/{item['id']}"
    for value in ({"quote": "Changed", "content": "a"}, {"content": None}, {"content": " "}):
        assert client.patch(url, json=value).status_code == 422
    assert client.get(f"/api/papers/{paper['id']}/annotations").json() == [item]
    with pytest.raises(ValueError):
        AnnotationCreate.model_validate(annotation(rects=[{"x": float("nan"), "y": .1, "width": .1, "height": .1}]))


def test_trashed_paper_hides_and_preserves_annotations_then_purge_cascades(client):
    paper = upload(client)
    item = add(client, paper)
    url = f"/api/papers/{paper['id']}/annotations"
    assert client.delete(f"/api/papers/{paper['id']}").status_code == 204
    assert client.get(url).status_code == 404
    assert client.post(url, json=annotation()).status_code == 404
    assert client.patch(f"{url}/{item['id']}", json={"content": "Changed"}).status_code == 404
    assert client.delete(f"{url}/{item['id']}").status_code == 404
    assert client.post(f"/api/library/trash/paper/{paper['id']}/restore").status_code == 200
    assert client.get(url).json() == [item]
    client.delete(f"/api/papers/{paper['id']}")
    preview = client.post("/api/library/trash/empty/preview").json()
    assert client.post("/api/library/trash/empty", json={"preview_id": preview["preview_id"], "confirm": True}).status_code == 200
    with client.app.state.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 0


def edited_backup(client, change):
    data = client.get("/api/library/backup").content
    output = io.BytesIO()
    with ZipFile(io.BytesIO(data)) as source, ZipFile(output, "w") as target:
        for name in source.namelist():
            body = source.read(name)
            if name == "manifest.json":
                value = json.loads(body)
                change(value)
                body = json.dumps(value).encode()
            target.writestr(name, body)
    return output.getvalue()


def test_backup_restore_reassigns_annotation_ids_without_changing_anchors(client):
    paper = upload(client)
    item = add(client, paper)
    data = client.get("/api/library/backup").content
    preview = client.post("/api/library/restore/preview", files={"file": ("backup.zip", data)}).json()
    assert preview["annotations_count"] == 1
    result = client.post("/api/library/restore", json={"preview_id": preview["preview_id"], "confirm": True}).json()
    restored = client.get(f"/api/papers/{result['paper_ids'][0]}/annotations").json()[0]
    assert restored["id"] != item["id"]
    assert {key: restored[key] for key in annotation()} == annotation()
    assert client.get(f"/api/papers/{paper['id']}/annotations").json() == [item]


def test_restore_old_backup_without_annotations_is_compatible(client):
    paper = upload(client)
    add(client, paper)
    data = edited_backup(client, lambda value: value["papers"][0].pop("annotations"))
    response = client.post("/api/library/restore/preview", files={"file": ("old.zip", data)})
    assert response.status_code == 200, response.text
    assert response.json()["annotations_count"] == 0


def test_restore_rejects_invalid_annotation_before_mutating_library(client):
    paper = upload(client)
    item = add(client, paper)
    data = edited_backup(client, lambda value: value["papers"][0]["annotations"][0].update(page=999))
    assert client.post("/api/library/restore/preview", files={"file": ("bad.zip", data)}).status_code == 422
    assert len(client.get("/api/papers").json()) == 1
    assert client.get(f"/api/papers/{paper['id']}/annotations").json() == [item]
