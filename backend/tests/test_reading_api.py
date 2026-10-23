import io
import json
import threading
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.reading_api import ReadingService, ReadingValidationError, call_reading, validate_notes
from backend.tests.test_api import add_note, upload
from backend.translation import ProviderError, SettingsPatch


@pytest.fixture
def reading_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-reading-test-only")
    app = create_app(data_dir=tmp_path / "data", frontend_dist=tmp_path / "dist")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        reader = app.state.reader

        def snapshot(paper_id):
            paper = reader.ai.paper(paper_id)
            return {"title": paper["title"], "pages": [{"page": page, "text": f"PDF page {page}. " + "Source evidence about neural inference, constraints, and evaluation. " * 12} for page in range(1, paper["page_count"] + 1)], "standard": "test"}

        monkeypatch.setattr(reader, "snapshot", snapshot)
        yield client, reader


def estimate(client, paper, **options):
    response = client.post(f"/api/papers/{paper['id']}/reading/estimate", json={"focus": "推导条件与实验设置", **options})
    assert response.status_code == 200, response.text
    return response.json()


def start(client, paper, quote, limit=5):
    return client.post(f"/api/papers/{paper['id']}/reading/jobs", json={"quote_id": quote["quote_id"], "max_cost_cny": limit})


def wait(client, job_id):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        response = client.get(f"/api/reading/jobs/{job_id}")
        assert response.status_code == 200, response.text
        value = response.json()
        if value["status"] not in {"queued", "running", "cancelling"}:
            return value
        time.sleep(.01)
    pytest.fail("Reading job did not finish")


def provider(*args):
    user = json.loads(args[2])
    first, last = user["valid_pdf_pages"]
    document = {"schema_version": 1, "notes": [{"title": "模型条件与证据", "page_start": first, "page_end": last,
        "kind": "method", "content": f"[p. {first}] 论文原文结论：\n\n" + "解释模型假设、变量单位、条件约束、推导步骤及证据边界，不虚构实验数据。" * 12,
        "sort_order": 0, "completed": True}]}
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(document, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 300, "prompt_cache_hit_tokens": 50}}


def test_free_estimate_stages_frozen_selection_and_no_key_or_files_in_quote(reading_client):
    client, reader = reading_client
    paper = upload(client)
    reader.call_provider = lambda *args: pytest.fail("Preparing/estimating must be free")
    quote = estimate(client, paper, model="deepseek-v4-pro", reasoning_effort="low")
    assert [stage["kind"] for stage in quote["stages"]] == ["index", "detail", "detail", "review"]
    assert [(stage["first"], stage["last"]) for stage in quote["stages"] if stage["kind"] == "detail"] == [(1, 3), (4, 5)]
    assert quote["upper_bound_cny"] > quote["estimated_cny"] > 0
    assert quote["model"] == "deepseek-v4-pro" and quote["reasoning_effort"] == "low"
    assert "sk-reading-test-only" not in json.dumps(quote)
    assert "pdf_path" not in json.dumps(quote)
    assert client.get(f"/api/papers/{paper['id']}/reading/jobs").json()["jobs"] == []
    assert reader.ai.settings()["spent_cny"] == 0


def test_complete_draft_is_not_auto_imported_append_preserves_old_notes_and_is_idempotent(reading_client):
    client, reader = reading_client
    paper = upload(client)
    original = add_note(client, paper["id"], title="人工解析", content="原有人工内容，不能覆盖", completed=True)
    calls = []
    reader.call_provider = lambda *args: calls.append(args) or provider(*args)
    quote = estimate(client, paper)
    result = start(client, paper, quote)
    assert result.status_code == 202, result.text
    job = wait(client, result.json()["id"])
    assert job["status"] == "completed", job
    assert job["completed_stages"] == job["total_stages"] == 4
    assert job["notes_count"] == len(calls) == 4
    assert all(note["completed"] is False and note["content"].startswith("> API 精读草稿") for note in job["notes"])
    assert [note["sort_order"] for note in job["notes"]] == list(range(4))
    assert len(client.get(f"/api/papers/{paper['id']}").json()["notes"]) == 1
    assert start(client, paper, quote).json()["id"] == job["id"]
    assert len(calls) == 4
    assert "prior_draft_context" in json.loads(calls[1][2])
    assert json.loads(calls[1][2])["prior_draft_context"]
    assert "UNTRUSTED" in calls[0][1]
    assert "sk-reading-test-only" not in json.dumps(job)
    exported = client.get(f"/api/reading/jobs/{job['id']}/export").json()
    assert set(exported) == {"schema_version", "notes"}
    assert len(exported["notes"]) == 4
    assert "[p." in client.get(f"/api/reading/jobs/{job['id']}/export?format=markdown").text
    for _ in range(2):
        appended = client.post(f"/api/reading/jobs/{job['id']}/import")
        assert appended.status_code == 200, appended.text
        assert len(appended.json()["paper"]["notes"]) == 5
        assert appended.json()["job"]["imported_at"]
    saved = client.get(f"/api/papers/{paper['id']}").json()["notes"]
    assert next(note for note in saved if note["id"] == original["id"])["content"] == original["content"]
    assert reader.ai.settings()["reserved_cny"] == 0
    assert reader.ai.settings()["spent_cny"] == pytest.approx(4 * .002702)
    assert client.get(f"/api/papers/{paper['id']}/translations").json()["job"] is None


@pytest.mark.parametrize("limit", [0, .01])
def test_budget_rejection_never_dispatches(reading_client, limit):
    client, reader = reading_client
    paper = upload(client)
    reader.call_provider = lambda *args: pytest.fail("No budget, no provider call")
    quote = estimate(client, paper)
    assert start(client, paper, quote, limit=limit).status_code == 422
    assert reader.ai.settings()["spent_cny"] == reader.ai.settings()["reserved_cny"] == 0


def test_cumulative_budget_shared_with_translation_and_key_cannot_change_while_active(reading_client):
    client, reader = reading_client
    paper = upload(client)
    other = upload(client, name="other.pdf")
    quote = estimate(client, paper)
    client.patch("/api/translation/settings", json={"total_budget_cny": quote["upper_bound_cny"] + .000001})
    entered, release = threading.Event(), threading.Event()

    def blocked(*args):
        entered.set(); assert release.wait(5)
        return provider(*args)

    reader.call_provider = blocked
    job = start(client, paper, quote).json()
    try:
        assert entered.wait(3)
        assert reader.ai.settings()["reserved_cny"] > 0
        estimate_translation = client.post(f"/api/papers/{other['id']}/translations/estimate", json={"pages": [1]})
        # The blank test PDF is scanned-like; use a synthetic translation source only for the cost check.
        reader.ai.source_page = lambda *args: ("source text for translation with sufficient characters", "test-digest")
        translation = client.post(f"/api/papers/{other['id']}/translations/estimate", json={"pages": [1]}).json()
        assert client.post(f"/api/papers/{other['id']}/translations", json={"quote_id": translation["quote_id"], "max_cost_cny": 5}).status_code == 422
        assert client.patch("/api/translation/settings", json={"api_key": "sk-replacement-test-only"}).status_code == 409
        assert client.patch("/api/translation/settings", json={"total_budget_cny": 0}).status_code == 422
        client.post(f"/api/reading/jobs/{job['id']}/cancel")
    finally:
        release.set()
    result = wait(client, job["id"])
    assert result["status"] == "cancelled" and result["notes_count"] == 1
    assert reader.ai.settings()["reserved_cny"] == 0


@pytest.mark.parametrize("mutation", ["source", "prompt", "limits", "expired", "key"])
def test_stale_quote_is_rejected_before_paying(reading_client, monkeypatch, mutation):
    from backend import reading_api
    client, reader = reading_client
    paper = upload(client)
    quote = estimate(client, paper)
    reader.call_provider = lambda *args: pytest.fail("Stale quote must be rejected")
    if mutation == "source":
        original = reader.snapshot
        monkeypatch.setattr(reader, "snapshot", lambda paper_id: {**original(paper_id), "title": "changed"})
    elif mutation == "prompt":
        original = reading_api.system_prompt
        monkeypatch.setattr(reading_api, "system_prompt", lambda stage: original(stage) + " changed")
    elif mutation == "limits":
        monkeypatch.setitem(reading_api.THINKING_OUTPUT_LIMITS, "high", 98304)
    elif mutation == "expired":
        with reader.store.connection() as connection:
            connection.execute("UPDATE translation_quotes SET expires=0")
    else:
        reader.ai.config.update("sk-changed-test-key", None)
    assert start(client, paper, quote).status_code == 409
    assert reader.ai.settings()["spent_cny"] == 0


def test_estimate_types_cannot_be_confused_between_endpoints(reading_client):
    client, reader = reading_client
    paper = upload(client)
    quote = estimate(client, paper)
    payload = {"quote_id": quote["quote_id"], "max_cost_cny": 5}
    assert client.post(f"/api/papers/{paper['id']}/translations", json=payload).status_code == 422
    reader.ai.source_page = lambda *args: ("source text for translation with sufficient characters", "digest")
    translation = client.post(f"/api/papers/{paper['id']}/translations/estimate", json={"pages": [1]}).json()
    assert start(client, paper, translation).status_code == 422


@pytest.mark.parametrize("bad", ["json", "page", "exercise", "short", "metadata", "truncated"])
def test_invalid_result_charges_usage_but_stops_without_auto_retry_or_import(reading_client, bad):
    client, reader = reading_client
    paper = upload(client)
    calls = []

    def invalid(*args):
        calls.append(args)
        result = provider(*args)
        value = json.loads(result["choices"][0]["message"]["content"])
        if bad == "json":
            result["choices"][0]["message"]["content"] = "not json"
            return result
        if bad == "page": value["notes"][0]["page_end"] = 99
        if bad == "exercise": value["notes"][0]["kind"] = "exercise"
        if bad == "short": value["notes"][0]["content"] = "一句话摘要"
        if bad == "metadata": value["paper"] = {"title": "Must not overwrite"}
        if bad == "truncated": result["choices"][0]["finish_reason"] = "length"
        result["choices"][0]["message"]["content"] = json.dumps(value)
        return result

    reader.call_provider = invalid
    result = wait(client, start(client, paper, estimate(client, paper)).json()["id"])
    assert result["status"] == "failed" and result["notes_count"] == 0
    assert len(calls) == 1
    assert reader.ai.settings()["spent_cny"] == pytest.approx(.002702)
    assert reader.ai.settings()["reserved_cny"] == 0
    assert client.post(f"/api/reading/jobs/{result['id']}/import").status_code == 409
    assert client.get(f"/api/papers/{paper['id']}").json()["notes"] == []
    if bad != "truncated":
        assert result["has_rejected_output"] is True
        assert result["last_attempt"]["validation_error"]["code"]
        assert "第 1 阶段" in result["error"]
        rejected = client.get(f"/api/reading/jobs/{result['id']}/rejected-output")
        assert rejected.status_code == 200 and rejected.headers["content-type"].startswith("text/plain")
        assert "attachment" in rejected.headers["content-disposition"]


def test_uncertain_usage_keeps_conservative_cost_and_partial_draft_can_be_exported(reading_client):
    client, reader = reading_client
    paper = upload(client)
    calls = []

    def failure(*args):
        calls.append(args)
        if len(calls) == 2:
            raise ProviderError("Uncertain request", uncertain=True)
        return provider(*args)

    reader.call_provider = failure
    quote = estimate(client, paper)
    value = wait(client, start(client, paper, quote).json()["id"])
    assert value["status"] == "failed" and value["notes_count"] == 1
    assert len(calls) == 2
    assert reader.ai.settings()["uncertain_cny"] == quote["stages"][1]["upper_bound_cny"]
    assert reader.ai.settings()["reserved_cny"] == 0
    assert len(client.get(f"/api/reading/jobs/{value['id']}/export").json()["notes"]) == 1
    assert client.post(f"/api/reading/jobs/{value['id']}/import").status_code == 409


def test_scans_large_docs_and_unknown_papers_fail_without_paid_calls(reading_client):
    client, reader = reading_client
    paper = upload(client)
    with pytest.raises(HTTPException) as failure:
        ReadingService.snapshot(reader, paper["id"])
    assert failure.value.status_code == 422
    large = upload(client, name="large.pdf", pages=81)
    with pytest.raises(HTTPException) as failure:
        ReadingService.snapshot(reader, large["id"])
    assert failure.value.status_code == 422
    assert client.post("/api/papers/unknown/reading/estimate", json={}).status_code == 404
    assert client.post(f"/api/papers/{paper['id']}/reading/estimate", json={"focus": "x" * 2001}).status_code == 422


def test_delete_paper_removes_drafts_source_plan_but_keeps_usage_ledger(reading_client):
    client, reader = reading_client
    paper = upload(client)
    reader.call_provider = provider
    job = wait(client, start(client, paper, estimate(client, paper)).json()["id"])
    spent = reader.ai.settings()["spent_cny"]
    assert client.delete(f"/api/papers/{paper['id']}").status_code == 204
    assert client.get(f"/api/reading/jobs/{job['id']}").status_code == 404
    with reader.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM reading_runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM translation_quotes").fetchone()[0] == 0
    assert reader.ai.settings()["spent_cny"] == spent


@pytest.mark.parametrize("effort,timeout", [("none", 180), ("low", 300), ("high", 600), ("max", 600)])
def test_provider_uses_json_mode_selected_model_and_fixed_api(monkeypatch, effort, timeout):
    from backend import translation
    sent = []

    class Opener:
        def open(self, request, timeout):
            sent.append((request.full_url, json.loads(request.data), timeout))
            return io.BytesIO(b'{"choices":[],"usage":{}}')

    monkeypatch.setattr(translation, "build_opener", lambda *args: Opener())
    call_reading("sk-not-used", "JSON instructions", "source data", 24000, "deepseek-v4-pro", effort)
    assert sent[0][0] == "https://api.deepseek.com/chat/completions"
    assert sent[0][1]["response_format"] == {"type": "json_object"}
    assert sent[0][1]["model"] == "deepseek-v4-pro"
    assert sent[0][1]["thinking"] == {"type": "disabled" if effort == "none" else "enabled"}
    if effort != "none":
        assert sent[0][1]["reasoning_effort"] == effort
    else:
        assert "reasoning_effort" not in sent[0][1]
    assert sent[0][2] == timeout


@pytest.mark.parametrize("effort,limits", [
    ("none", [8192, 16384, 16384, 12288]),
    ("low", [32768] * 4), ("high", [65536] * 4), ("max", [131072] * 4),
])
def test_reading_limits_reserve_combined_reasoning_and_json_and_are_quoted(reading_client, effort, limits):
    client, reader = reading_client
    paper = upload(client)
    reader.call_provider = lambda *args: pytest.fail("Estimate must not call API")
    quote = estimate(client, paper, reasoning_effort=effort)
    assert [stage["max_tokens"] for stage in quote["stages"]] == limits
    assert quote["upper_bound_cny"] >= sum(limits) * 8 / 1e6
    if effort == "high":
        assert start(client, paper, quote, limit=.5).status_code == 422
    assert reader.ai.settings()["spent_cny"] == 0


def test_high_reasoning_avoids_old_index_cap_without_weakening_later_analysis(reading_client):
    client, reader = reading_client
    paper = upload(client, pages=12)
    calls = []

    def needs_space(*args):
        calls.append(args)
        result = provider(*args)
        if args[3] <= 12288:
            result["choices"][0]["finish_reason"] = "length"
            result["choices"][0]["message"]["content"] = ""
        return result

    reader.call_provider = needs_space
    quote = estimate(client, paper, reasoning_effort="high")
    value = wait(client, start(client, paper, quote).json()["id"])
    assert value["status"] == "completed", value
    assert len(calls) == value["completed_stages"] == 6
    assert all(args[3] == 65536 and args[5] == "high" for args in calls)
    assert "ONLY the navigation/index stage" in calls[0][1]
    assert "exactly TWO guide notes" in calls[0][1]
    assert "in depth" in calls[1][1]
    assert "cross-check" in calls[-1][1]
    assert client.get(f"/api/papers/{paper['id']}").json()["notes_count"] == 0


@pytest.mark.parametrize("reasoning", [12000, None, -1, 999999, "12000", True])
def test_truncation_records_safe_diagnostics_and_keeps_prior_valid_draft(reading_client, reasoning):
    client, reader = reading_client
    paper = upload(client)
    calls = []

    def truncated(*args):
        calls.append(args)
        result = provider(*args)
        if len(calls) == 2:
            result["choices"][0] = {"finish_reason": "length", "message": {
                "content": '{"schema_version":1,"notes":[', "reasoning_content": "PRIVATE REASONING MUST NOT BE SAVED"}}
            result["usage"]["completion_tokens"] = args[3]
            result["usage"]["completion_tokens_details"] = {"reasoning_tokens": reasoning}
        return result

    reader.call_provider = truncated
    quote = estimate(client, paper)
    value = wait(client, start(client, paper, quote).json()["id"])
    assert value["status"] == "failed" and value["completed_stages"] == value["notes_count"] == 1
    assert len(calls) == 2
    assert "第 2 阶段" in value["error"] and "16,384/16,384" in value["error"]
    assert "未自动重试" in value["error"]
    attempt = value["last_attempt"]
    assert attempt["stage"] == 2 and attempt["label"] == quote["stages"][1]["label"]
    assert attempt["finish_reason"] == "length"
    assert attempt["max_tokens"] == attempt["output_tokens"] == 16384
    assert attempt["reasoning_tokens"] == (12000 if type(reasoning) is int and reasoning == 12000 else None)
    assert attempt["content_characters"] > 0
    assert value["cost_cny"] > .1 and reader.ai.settings()["reserved_cny"] == 0
    assert len(client.get(f"/api/reading/jobs/{value['id']}/export").json()["notes"]) == 1
    assert client.post(f"/api/reading/jobs/{value['id']}/import").status_code == 409
    with reader.store.connection() as connection:
        saved = connection.execute("SELECT diagnostics FROM reading_runs WHERE id=?", (value["id"],)).fetchone()[0]
    assert len(json.loads(saved)) == 2
    assert "PRIVATE REASONING" not in saved and "reasoning_content" not in saved
    assert "PRIVATE REASONING" not in json.dumps(value)


def test_other_finish_reasons_are_not_misreported_as_truncation(reading_client):
    client, reader = reading_client
    paper = upload(client)

    def filtered(*args):
        result = provider(*args)
        result["choices"][0]["finish_reason"] = "content_filter"
        return result

    reader.call_provider = filtered
    value = wait(client, start(client, paper, estimate(client, paper)).json()["id"])
    assert value["status"] == "failed" and value["notes_count"] == 0
    assert "content_filter" in value["error"] and "输出上限" not in value["error"]
    assert value["last_attempt"]["finish_reason"] == "content_filter"


def test_legacy_truncation_uses_receipt_without_inventing_reasoning_counts(reading_client):
    client, reader = reading_client
    paper = upload(client)

    def truncated(*args):
        result = provider(*args)
        result["choices"][0]["finish_reason"] = "length"
        return result

    reader.call_provider = truncated
    value = wait(client, start(client, paper, estimate(client, paper)).json()["id"])
    with reader.store.connection() as connection:
        connection.execute("UPDATE reading_runs SET diagnostics='[]' WHERE id=?", (value["id"],))
        connection.execute("UPDATE translation_jobs SET error=? WHERE id=?", ("本阶段输出被截断，已记录用量并保留此前草稿，未自动重试。", value["id"]))
    restored = client.get(f"/api/reading/jobs/{value['id']}").json()
    assert restored["last_attempt"]["legacy"] is True
    assert restored["last_attempt"]["stage"] == 1
    assert restored["last_attempt"]["output_tokens"] == 300
    assert restored["last_attempt"]["reasoning_tokens"] is None
    assert restored["last_attempt"]["content_characters"] is None
    assert restored["notes_count"] == 0 and restored["cost_cny"] == value["cost_cny"]


def test_diagnostics_migration_preserves_existing_drafts_and_ledger(reading_client):
    client, reader = reading_client
    paper = upload(client)
    original = add_note(client, paper["id"], title="人工解析")
    reader.call_provider = provider
    value = wait(client, start(client, paper, estimate(client, paper)).json()["id"])
    with reader.store.connection() as connection:
        connection.execute("ALTER TABLE reading_runs DROP COLUMN diagnostics")
        connection.execute("ALTER TABLE reading_runs DROP COLUMN rejected_output")
    migrated = ReadingService(reader.ai).get(value["id"])
    assert migrated["notes"] == value["notes"]
    assert migrated["cost_cny"] == value["cost_cny"]
    assert migrated["last_attempt"] is None
    assert migrated["has_rejected_output"] is False
    assert client.get(f"/api/papers/{paper['id']}").json()["notes"][0]["id"] == original["id"]


def document_for_validation():
    return {"schema_version": 1, "notes": [{"title": "公式与模型", "page_start": 4, "page_end": 6,
        "kind": "method", "content": "[p. 4] " + "解释假设、符号、推导及证据范围。" * 20 + "\n\n" + r"$\alpha+\frac{a}{b}$" + "\n\t" + r"\begin{aligned} a&=b \end{aligned}",
        "sort_order": 0, "completed": False}]}


def test_literal_json_string_whitespace_preserves_markdown_and_latex_exactly():
    document = document_for_validation()
    content = json.dumps(document, ensure_ascii=False).replace(r"\n", "\n").replace(r"\t", "\t")
    with pytest.raises(json.JSONDecodeError):
        json.loads(content)
    normalizations = []
    notes = validate_notes(content, 4, 6, normalizations)
    assert normalizations == ["json_string_whitespace"]
    assert notes[0]["content"].split("\n\n", 1)[1] == document["notes"][0]["content"]
    assert notes[0]["page_start"] == 4 and notes[0]["page_end"] == 6
    assert notes[0]["completed"] is False


@pytest.mark.parametrize("literal", [False, True])
@pytest.mark.parametrize("control", ["\x00", "\b", "\f", "\x1b"])
def test_unexpected_controls_are_rejected_instead_of_rewriting_math(control, literal):
    document = document_for_validation()
    document["notes"][0]["content"] += control
    content = json.dumps(document)
    if literal:
        prefix, _, suffix = content.rpartition(json.dumps(control)[1:-1])
        content = prefix + control + suffix
    with pytest.raises(ReadingValidationError) as failure:
        validate_notes(content, 4, 6)
    assert failure.value.detail["code"] == "control_character"
    assert failure.value.detail["note_index"] == 1
    assert failure.value.detail["field"] == "content"


@pytest.mark.parametrize("change,code,field", [
    ({"page_start": 3}, "page_range", "page_start/page_end"),
    ({"page_end": 7}, "page_range", "page_start/page_end"),
    ({"page_start": "4"}, "note_schema", "page_start"),
    ({"kind": "theory"}, "note_schema", "kind"),
    ({"content": "过短解析"}, "content_length", "content"),
    ({"kind": "exercise"}, "exercise", "kind"),
    ({"paper": {}}, "note_schema", "paper"),
])
def test_specific_errors_still_enforce_contract_after_whitespace_compatibility(change, code, field):
    document = document_for_validation()
    document["notes"][0].update(change)
    content = json.dumps(document).replace(r"\n", "\n")
    with pytest.raises(ReadingValidationError) as failure:
        validate_notes(content, 4, 6)
    assert failure.value.detail["code"] == code
    assert failure.value.detail["note_index"] == 1 and failure.value.detail["field"] == field


@pytest.mark.parametrize("bad", ['{"schema_version":1,"notes":[', '{"content":"\\unknown"}', '```json\n{}\n```'])
def test_broken_json_is_not_guessed_or_silently_repaired(bad):
    with pytest.raises(ReadingValidationError) as failure:
        validate_notes(bad, 4, 6)
    assert failure.value.detail["code"] == "invalid_json"
    assert failure.value.detail["line"] >= 1 and failure.value.detail["column"] >= 1


def test_provider_markdown_newlines_complete_without_extra_calls(reading_client):
    client, reader = reading_client
    paper = upload(client)
    calls = []

    def multiline(*args):
        calls.append(args)
        result = provider(*args)
        result["choices"][0]["message"]["content"] = result["choices"][0]["message"]["content"].replace(r"\n", "\n")
        return result

    reader.call_provider = multiline
    value = wait(client, start(client, paper, estimate(client, paper)).json()["id"])
    assert value["status"] == "completed" and value["completed_stages"] == len(calls) == 4
    assert value["last_attempt"]["normalizations"] == ["json_string_whitespace"]
    assert value["has_rejected_output"] is False
    assert client.get(f"/api/reading/jobs/{value['id']}/rejected-output").status_code == 404
    assert reader.ai.settings()["spent_cny"] == pytest.approx(4 * .002702)


def test_rejected_final_text_is_retained_without_reasoning_and_deleted_with_paper(reading_client):
    client, reader = reading_client
    paper = upload(client)
    calls = []

    def invalid_page(*args):
        calls.append(args)
        result = provider(*args)
        if len(calls) == 2:
            value = json.loads(result["choices"][0]["message"]["content"])
            value["notes"][0]["page_start"] = 4
            value["notes"][0]["page_end"] = 5
            result["choices"][0]["message"] = {"content": json.dumps(value), "reasoning_content": "DO NOT SAVE PRIVATE REASONING"}
        return result

    reader.call_provider = invalid_page
    value = wait(client, start(client, paper, estimate(client, paper)).json()["id"])
    assert value["status"] == "failed" and value["notes_count"] == 1 and len(calls) == 2
    assert "页码 4–5" in value["error"] and "第 1–3 页" in value["error"]
    assert value["last_attempt"]["validation_error"]["code"] == "page_range"
    raw = client.get(f"/api/reading/jobs/{value['id']}/rejected-output").text
    assert json.loads(raw)["notes"][0]["page_start"] == 4
    assert "DO NOT SAVE" not in raw and "DO NOT SAVE" not in json.dumps(value)
    assert "rejected_output" not in value
    assert client.delete(f"/api/papers/{paper['id']}").status_code == 204
    assert client.get(f"/api/reading/jobs/{value['id']}/rejected-output").status_code == 404


def test_paper_deleted_during_estimation_returns_404_without_orphan_quote(reading_client, monkeypatch):
    client, reader = reading_client
    paper = upload(client)
    original_plan = reader.plan

    def deleted(*args):
        result = original_plan(*args)
        reader.store.delete_paper(paper["id"])
        return result

    monkeypatch.setattr(reader, "plan", deleted)
    reader.call_provider = lambda *args: pytest.fail("Deleted paper must not call API")
    response = client.post(f"/api/papers/{paper['id']}/reading/estimate", json={})
    assert response.status_code == 404, response.text
    with reader.store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM translation_quotes").fetchone()[0] == 0
