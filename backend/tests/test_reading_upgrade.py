import json

import pytest

from backend.models import ImportDocument, NoteCreate
from backend.store import Store
from scripts.upgrade_reading_notes import GUIDE_PREFIX, upgrade


@pytest.mark.parametrize("edited_guide", [False, True])
def test_upgrade_backs_up_removes_exercises_and_preserves_other_content(tmp_path, edited_guide):
    data_dir = tmp_path / "data"
    database = Store(data_dir)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"original PDF bytes are never changed")
    guide = {"title": "Guide", "content": "Original guide", "kind": "guide", "page_start": 1, "page_end": 1}
    notes = [
        {**guide, "content": "User-edited guide" if edited_guide else guide["content"]},
        {"title": "Exercise", "content": "Questions", "kind": "exercise", "page_start": 2, "page_end": 2},
        {"title": "User method", "content": "Keep this intact", "kind": "method", "page_start": 1, "page_end": 2, "completed": True},
    ]
    paper = database.create_paper({"title": "Paper", "tags": []}, pdf, 2, "paper.pdf", False, "test", notes=[NoteCreate.model_validate(note).model_dump() for note in notes])
    database.patch_progress("test", {"active_note_id": paper["notes"][1]["id"], "page": 2})
    (data_dir / "seed.json").write_text(json.dumps([{"id": "test", "notes": [{**guide, "content": GUIDE_PREFIX + guide["content"]}]}]), encoding="utf-8")
    original = database.get_paper("test")
    preview = upgrade(data_dir)
    assert preview["applied"] is False
    assert preview["exercises"] == 1
    assert preview["guides"] == (0 if edited_guide else 1)
    assert preview["backup_dir"] is None
    assert database.get_paper("test") == original
    assert not (data_dir / "backups").exists()

    result = upgrade(data_dir, apply=True)
    backups = list((data_dir / "backups").glob("*/*.json"))
    assert len(backups) == 1
    restored = ImportDocument.model_validate_json(backups[0].read_text(encoding="utf-8"))
    assert restored.paper.title == "Paper"
    assert [note.model_dump() for note in restored.notes] == original["notes"]
    actual = database.get_paper("test")
    assert len(actual["notes"]) == 2
    assert actual["progress"]["active_note_id"] is None
    assert actual["progress"]["page"] == 2
    assert actual["notes"][0]["content"] == ("User-edited guide" if edited_guide else GUIDE_PREFIX + "Original guide")
    assert actual["notes"][1] == paper["notes"][2]
    assert pdf.read_bytes() == b"original PDF bytes are never changed"
    assert result["backup_dir"] is not None
    again = upgrade(data_dir, apply=True)
    assert again["exercises"] == again["guides"] == 0
    assert again["backup_dir"] is None
