import copy
import json

import pytest

from backend.reading_api import ReadingValidationError, validate_stage_notes
from backend.reading_sources import WORKFLOW, passage_lookup, source_catalog
from backend.tests.test_api import upload
from backend.tests.test_reading_api import estimate, failed_after_first_stage, legacy_reading_client, provider, reading_client, start, wait


def test_catalog_is_verbatim_complete_deterministic_and_page_scoped():
    text = ("A source sentence about stable queues and delays.\n" * 91) + "Final tail."
    pages = [{"page": 1, "text": text}, {"page": 2, "text": text}]
    catalog = source_catalog(pages)
    assert catalog == source_catalog(pages)
    ids = set()
    for page in catalog:
        assert "".join(item["text"] for item in page["passages"]) == text
        for item in page["passages"]:
            assert item["text"] == text[item["start"]:item["end"]]
            assert 10 <= len(item["text"].strip()) <= 2000
            assert item["source_id"] not in ids
            ids.add(item["source_id"])
    assert len(passage_lookup(catalog, pages)) == len(ids)
    altered = copy.deepcopy(catalog)
    altered[0]["passages"][0]["text"] += "changed"
    with pytest.raises(ValueError):
        passage_lookup(altered, pages)


@pytest.mark.parametrize("pages_count", [1, 5, 12, 80])
def test_every_thematic_stage_has_the_entire_paper_and_frozen_evidence(reading_client, pages_count):
    client, reader = reading_client
    paper = upload(client, pages=pages_count)
    reader.call_provider = lambda *_: pytest.fail("Estimating must remain free")
    quote = estimate(client, paper)
    assert quote["workflow"] == WORKFLOW
    assert [stage["kind"] for stage in quote["stages"]] == ["index", "concept", "method", "experiment", "review"]
    with reader.store.connection() as connection:
        frozen = json.loads(connection.execute("SELECT data FROM translation_quotes WHERE id=?", (quote["quote_id"],)).fetchone()[0])
    for stage in frozen["stages"]:
        assert stage["workflow"] == WORKFLOW and "detail" != stage["kind"]
        assert stage["first"] == 1 and stage["last"] == pages_count
        assert [page["page"] for page in stage["base"]["paper_source_data"]] == list(range(1, pages_count + 1))
        assert len(stage["source_pages"]) == pages_count
        assert len(passage_lookup(stage["base"]["paper_source_data"], stage["source_pages"])) >= pages_count
    assert all(stage["base"]["paper_source_data"] == frozen["stages"][0]["base"]["paper_source_data"] for stage in frozen["stages"])


def stage_fixture(reader):
    from backend.reading_api import ReadingSelection
    snapshot = {"title": "Source fixture", "standard": "test", "pages": [
        {"page": 1, "text": "The first page defines assumptions and model entities."},
        {"page": 2, "text": "The second page connects the algorithm to the experiment."},
    ]}
    return reader.plan(snapshot, ReadingSelection())[2]


def result_document(stage, **changes):
    reference = stage["base"]["paper_source_data"][1]["passages"][0]["source_id"]
    note = {"title": "Complete method", "page_start": 1, "page_end": 1, "kind": "method",
            "content": "[p. 2] Method explanation and evidence boundaries. " * 12,
            "evidence": [{"source_id": reference, "label": "原文片段"}], **changes}
    return json.dumps({"schema_version": 1, "notes": [note]})


def test_id_evidence_backfills_exact_quote_page_and_expands_note_range(reading_client):
    _, reader = reading_client
    stage = stage_fixture(reader)
    normalizations = []
    notes = validate_stage_notes(result_document(stage, verification_status="verified", completed=True), stage, normalizations)
    assert notes[0]["page_start"] == 1 and notes[0]["page_end"] == 2
    assert notes[0]["evidence"] == [{"page": 2, "quote": stage["source_pages"][1]["text"], "label": "原文片段"}]
    assert "evidence_range_expanded" in normalizations
    assert "按已选原文片段定位" in notes[0]["content"]
    assert notes[0]["verification_status"] == "unverified" and notes[0]["completed"] is False


@pytest.mark.parametrize("change,code", [
    ({"evidence": [{"source_id": "invented-or-from-another-document"}]}, "evidence_source_id"),
    ({"evidence": [{"page": 2, "quote": "A fabricated quote"}]}, "evidence_quote"),
    ({"evidence": [{"source_id": None}]}, "evidence_source_schema"),
    ({"evidence": "invalid"}, "evidence_source_schema"),
    ({"kind": "experiment"}, "stage_kind"),
])
def test_reference_or_category_issues_preserve_body_and_require_review_instead_of_losing_stage(reading_client, change, code):
    _, reader = reading_client
    stage = stage_fixture(reader)
    warnings = []
    raw = result_document(stage, **change)
    note = validate_stage_notes(raw, stage, [], warnings)[0]
    assert warnings[0]["code"] == code and warnings[0]["note_index"] == 1
    assert note["verification_status"] == "needs_review" and not note["completed"]
    assert note["content"].endswith(json.loads(raw)["notes"][0]["content"].strip())
    assert "自动检查提示（待复核）" in note["content"]
    if code != "stage_kind":
        assert note["evidence"] == []
    else:
        assert note["kind"] == "experiment" and note["evidence"]


@pytest.mark.parametrize("change,code", [({"page_end": 3}, "page_range"), ({"kind": "invented_kind"}, "note_schema"),
                                         ({"kind": "exercise"}, "exercise"), ({"content": "Too short"}, "content_length")])
def test_structural_and_quality_failures_are_still_blocked(reading_client, change, code):
    _, reader = reading_client
    stage = stage_fixture(reader)
    with pytest.raises(ReadingValidationError) as failure:
        validate_stage_notes(result_document(stage, **change), stage, [])
    assert failure.value.detail["code"] == code


def test_frozen_catalog_corruption_never_becomes_source_evidence(reading_client):
    _, reader = reading_client
    stage = stage_fixture(reader)
    content = result_document(stage)
    stage["base"]["paper_source_data"][1]["passages"][0]["text"] = "A changed passage in a frozen plan."
    with pytest.raises(ReadingValidationError) as failure:
        validate_stage_notes(content, stage, [])
    assert failure.value.detail["code"] == "source_catalog"


def test_real_worker_uses_all_prior_categories_and_imports_only_resolved_evidence(reading_client):
    client, reader = reading_client
    paper = upload(client)
    calls = []
    reader.call_provider = lambda *args: calls.append(args) or provider(*args)
    job = wait(client, start(client, paper, estimate(client, paper)).json()["id"])
    assert job["status"] == "completed" and job["workflow"] == WORKFLOW
    assert len(calls) == 5
    for call in calls:
        user = json.loads(call[2])
        assert [page["page"] for page in user["paper_source_data"]] == [1, 2, 3, 4, 5]
    contexts = [json.loads(call[2])["prior_draft_context"] for call in calls]
    assert contexts[0] == ""
    assert "|concept|" in contexts[2] and "|method|" in contexts[3] and "|experiment|" in contexts[4]
    assert all("source_id" not in evidence and evidence["quote"] for note in job["notes"] for evidence in note["evidence"])
    exported = client.get(f"/api/reading/jobs/{job['id']}/export").json()
    assert all("source_id" not in evidence for note in exported["notes"] for evidence in note["evidence"])
    assert client.post(f"/api/reading/jobs/{job['id']}/import").status_code == 200


def test_invalid_id_is_omitted_with_warning_and_all_five_stages_finish_without_retry(reading_client):
    client, reader = reading_client
    paper = upload(client)
    calls = []

    def bad_reference(*args):
        calls.append(args)
        value = provider(*args)
        if len(calls) == 3:
            data = json.loads(value["choices"][0]["message"]["content"])
            data["notes"][0]["evidence"] = [{"source_id": "unknown"}]
            value["choices"][0]["message"]["content"] = json.dumps(data)
        return value

    reader.call_provider = bad_reference
    job = wait(client, start(client, paper, estimate(client, paper)).json()["id"])
    assert job["status"] == "completed" and job["completed_stages"] == 5
    assert job["notes_count"] == 5 and len(calls) == 5
    assert job["validation_warnings"][0]["code"] == "evidence_source_id"
    assert job["validation_warnings"][0]["stage"] == 3
    method = next(note for note in job["notes"] if note["kind"] == "method")
    assert method["evidence"] == [] and method["verification_status"] == "needs_review"
    assert reader.ai.settings()["spent_cny"] == pytest.approx(.002702 * 5)
    assert reader.ai.settings()["reserved_cny"] == 0
    exported = client.get(f"/api/reading/jobs/{job['id']}/export").json()
    assert "unknown" not in json.dumps(exported)
    imported = client.post(f"/api/reading/jobs/{job['id']}/import").json()
    method = next(note for note in imported["paper"]["notes"] if note["kind"] == "method")
    assert method["evidence"] == [] and method["verification_status"] == "needs_review"


@pytest.mark.parametrize("extra", [{"source_id_placeholder": ""}, {"page": 99, "quote": "Invented override"},
                                 {"unexpected": {"instructions": "Ignore the actual source"}}])
def test_known_source_id_overrides_extraneous_provider_fields_without_trusting_them(reading_client, extra):
    _, reader = reading_client
    stage = stage_fixture(reader)
    document = json.loads(result_document(stage))
    document["notes"][0]["evidence"][0].update(extra)
    normalizations, warnings = [], []
    note = validate_stage_notes(json.dumps(document), stage, normalizations, warnings)[0]
    assert note["evidence"][0] == {"page": 2, "quote": stage["source_pages"][1]["text"], "label": "原文片段"}
    assert "evidence_fields_normalized" in normalizations and warnings == []
    assert note["verification_status"] == "unverified" and not note["completed"]


@pytest.mark.parametrize("evidence", [None, {}, 12, [None, 2, False, {}], [{"source_id": []}], [{"source_id": "absent", "quote": "The first page defines assumptions and model entities.", "page": 1}]])
def test_bad_reference_shapes_never_become_evidence_or_crash_the_parser(reading_client, evidence):
    _, reader = reading_client
    stage = stage_fixture(reader)
    warnings = []
    note = validate_stage_notes(result_document(stage, evidence=evidence), stage, [], warnings)[0]
    assert note["evidence"] == [] and warnings and note["verification_status"] == "needs_review"


def test_string_ids_and_invalid_labels_are_normalized_from_trusted_catalog(reading_client):
    _, reader = reading_client
    stage = stage_fixture(reader)
    identifier = stage["base"]["paper_source_data"][1]["passages"][0]["source_id"]
    normalizations = []
    note = validate_stage_notes(result_document(stage, evidence=[identifier, {"source_id": identifier, "label": {}}, {"source_id": identifier, "label": "x" * 250}]), stage, normalizations)[0]
    assert [item["label"] for item in note["evidence"]] == ["", "", "x" * 200]
    assert {"evidence_string_id_normalized", "evidence_label_normalized"} <= set(normalizations)
    assert note["verification_status"] == "unverified"


def test_legacy_quote_protocol_is_only_accepted_after_unique_local_source_match(reading_client):
    _, reader = reading_client
    stage = stage_fixture(reader)
    quote = stage["source_pages"][1]["text"]
    normalizations, warnings = [], []
    note = validate_stage_notes(result_document(stage, evidence=[{"page": 1, "quote": quote, "label": "original"}]), stage, normalizations, warnings)[0]
    assert note["evidence"] == [{"page": 2, "quote": quote, "label": "original"}]
    assert "evidence_quote_resolved" in normalizations and warnings == []
    # A missing page cannot disambiguate a phrase repeated on different pages.
    repeated = "A repeated source sentence."
    for page in stage["source_pages"]:
        page["text"] += " " + repeated
    stage["base"]["paper_source_data"] = source_catalog(stage["source_pages"])
    warnings = []
    note = validate_stage_notes(result_document(stage, evidence=[{"quote": repeated}]), stage, [], warnings)[0]
    assert note["evidence"] == [] and warnings[0]["code"] == "evidence_quote"


def test_valid_references_survive_next_to_bad_references_and_overflow_is_explicit(reading_client):
    _, reader = reading_client
    stage = stage_fixture(reader)
    identifier = stage["base"]["paper_source_data"][1]["passages"][0]["source_id"]
    warnings = []
    note = validate_stage_notes(result_document(stage, evidence=[{"source_id": "wrong"}, {"source_id": identifier}] * 20), stage, [], warnings)[0]
    assert len(note["evidence"]) == 16
    assert all(item["page"] == 2 for item in note["evidence"])
    assert warnings[0]["code"] == "evidence_count" and note["verification_status"] == "needs_review"


def test_all_stages_finish_with_provider_format_drift_and_keep_real_categories(reading_client):
    client, reader = reading_client
    paper = upload(client)
    calls = []

    def drift(*args):
        calls.append(args)
        response = provider(*args)
        document = json.loads(response["choices"][0]["message"]["content"])
        note = document["notes"][0]
        note["evidence"][0]["source_id_placeholder"] = ""
        if len(calls) == 3:
            document["notes"].append({**copy.deepcopy(note), "title": "Method limitations", "kind": "critique"})
        response["choices"][0]["message"]["content"] = json.dumps(document)
        return response

    reader.call_provider = drift
    job = wait(client, start(client, paper, estimate(client, paper)).json()["id"])
    assert job["status"] == "completed" and job["completed_stages"] == len(calls) == 5
    assert job["notes_count"] == 6
    assert len(job["validation_warnings"]) == 1 and job["validation_warnings"][0]["code"] == "stage_kind"
    critique = next(note for note in job["notes"] if note["kind"] == "critique")
    assert critique["title"] == "Method limitations" and critique["verification_status"] == "needs_review"
    assert all(note["evidence"] and "source_id" not in note["evidence"][0] for note in job["notes"])
    with reader.store.connection() as connection:
        diagnostics = json.loads(connection.execute("SELECT diagnostics FROM reading_runs WHERE id=?", (job["id"],)).fetchone()[0])
        assert all("evidence_fields_normalized" in attempt["normalizations"] for attempt in diagnostics)
        assert connection.execute("SELECT COUNT(*) FROM translation_receipts").fetchone()[0] == 5


@pytest.mark.parametrize("error", ["evidence_source_schema", "stage_kind", "evidence_source_id"])
def test_saved_thematic_response_is_recovered_for_free_without_losing_original_or_ledger(reading_client, error):
    client, reader = reading_client
    paper = upload(client)
    reader.call_provider = provider
    job = wait(client, start(client, paper, estimate(client, paper)).json()["id"])
    previous = job["notes"][:2]
    with reader.store.connection() as connection:
        plan = json.loads(connection.execute("SELECT plan FROM reading_runs WHERE id=?", (job["id"],)).fetchone()[0])
        response = provider("unused", "", json.dumps(plan[2]["base"]))
        raw = json.loads(response["choices"][0]["message"]["content"])
        raw["notes"][0]["evidence"][0]["source_id_placeholder"] = ""
        if error == "stage_kind":
            raw["notes"][0]["kind"] = "critique"
        if error == "evidence_source_id":
            raw["notes"][0]["evidence"][0]["source_id"] = "not-in-the-PDF"
        saved = json.dumps(raw)
        connection.execute("UPDATE reading_runs SET notes=?,rejected_output=?,diagnostics=? WHERE id=?", (json.dumps(previous), saved, json.dumps([{"stage":3,"finish_reason":"stop","validation_error":{"code":error}}]), job["id"]))
        connection.execute("UPDATE translation_jobs SET status='failed',completed_pages=2 WHERE id=?", (job["id"],))
        receipts = [tuple(row) for row in connection.execute("SELECT * FROM translation_receipts ORDER BY id")]
    reader.call_provider = lambda *_: pytest.fail("Recovery cannot call provider")
    reader.ai.executor.submit = lambda *_: pytest.fail("Recovery cannot run later stages")
    assert client.get(f"/api/reading/jobs/{job['id']}").json()["can_revalidate"]
    response = client.post(f"/api/reading/jobs/{job['id']}/revalidate")
    assert response.status_code == 200, response.text
    recovered = response.json()
    assert recovered["completed_stages"] == 3 and recovered["remaining_stages"] == 2
    assert recovered["notes"][:2] == previous and recovered["notes_count"] == 3
    assert recovered["cost_cny"] == job["cost_cny"]
    if error != "evidence_source_schema":
        assert recovered["validation_warnings"] and recovered["notes"][-1]["verification_status"] == "needs_review"
    assert client.post(f"/api/reading/jobs/{job['id']}/revalidate").json()["notes_count"] == 3
    with reader.store.connection() as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM translation_receipts ORDER BY id")] == receipts
        assert connection.execute("SELECT rejected_output FROM reading_runs WHERE id=?", (job["id"],)).fetchone()[0] == saved


def test_thematic_resume_never_rebuilds_a_frozen_catalog_or_changes_prompts(reading_client, monkeypatch):
    from backend import reading_api
    client, reader = reading_client
    paper = upload(client)
    job, _, calls = failed_after_first_stage(client, reader, paper)
    frozen_system, frozen_user = calls[1][1], json.loads(calls[1][2])
    monkeypatch.setattr(reading_api, "source_catalog", lambda *_: pytest.fail("Resume cannot rebuild source IDs"))
    monkeypatch.setattr(reading_api, "system_prompt", lambda *_: "Changed future prompt")
    old_snapshot = reader.snapshot
    monkeypatch.setattr(reader, "snapshot", lambda pid: {**old_snapshot(pid), "standard": "future standard"})
    quote = client.post(f"/api/reading/jobs/{job['id']}/resume/estimate").json()
    assert quote["workflow"] == WORKFLOW and quote["remaining_stages"] == 4
    assert client.post(f"/api/reading/jobs/{job['id']}/resume", json={"quote_id": quote["quote_id"], "max_cost_cny": 5}).status_code == 202
    complete = wait(client, job["id"])
    assert complete["status"] == "completed", complete
    assert calls[2][1] == frozen_system
    assert json.loads(calls[2][2])["paper_source_data"] == frozen_user["paper_source_data"]
    assert any(note["content"] == job["notes"][0]["content"] for note in complete["notes"])


def test_free_legacy_chinese_layout_recovery_preserves_receipts_and_prior_draft(legacy_reading_client, monkeypatch):
    client, reader = legacy_reading_client
    old_snapshot = reader.snapshot

    def snapshot(pid):
        value = old_snapshot(pid)
        value["pages"][0]["text"] = "原文说明动态分配计\n算资源，\n并满足稳定性约束。" * 1
        return value

    monkeypatch.setattr(reader, "snapshot", snapshot)
    paper = upload(client)
    reader.call_provider = provider
    job = wait(client, start(client, paper, estimate(client, paper)).json()["id"])
    previous = job["notes"][:1]
    raw = {"schema_version": 1, "notes": [{"title": "资源分配机制", "kind": "method", "page_start": 1, "page_end": 3,
           "content": "这个本地测试只检查排版等价引文、检查点和账本，不把文字匹配视为结论核验。" * 12,
           "evidence": [{"page": 1, "quote": "动态分配计算资源， 并满足稳定性约束。"}]}]}
    with reader.store.connection() as connection:
        connection.execute("UPDATE reading_runs SET notes=?,rejected_output=?,diagnostics=? WHERE id=?", (json.dumps(previous), json.dumps(raw), json.dumps([{"stage": 2, "finish_reason": "stop", "validation_error": {"code": "evidence_quote"}}]), job["id"]))
        connection.execute("UPDATE translation_jobs SET status='failed',completed_pages=1 WHERE id=?", (job["id"],))
        receipts = [tuple(row) for row in connection.execute("SELECT * FROM translation_receipts ORDER BY id")]
    reader.call_provider = lambda *_: pytest.fail("Local revalidation must never call API")
    reader.ai.executor.submit = lambda *_: pytest.fail("Local revalidation cannot start later stages")
    response = client.post(f"/api/reading/jobs/{job['id']}/revalidate")
    assert response.status_code == 200, response.text
    recovered = response.json()
    assert recovered["workflow"] == "legacy-page-batches" and recovered["completed_stages"] == 2
    assert recovered["notes"][0] == previous[0] and recovered["notes_count"] == 2
    assert recovered["cost_cny"] == job["cost_cny"]
    with reader.store.connection() as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM translation_receipts ORDER BY id")] == receipts
