import json

import pytest

from backend import reading_api
from backend.reading import LEARNING_STYLE, STANDARD_VERSION
from backend.tests.test_api import upload
from backend.tests.test_reading_api import estimate, failed_after_first_stage, provider, reading_client, start, wait


@pytest.mark.parametrize("kind,requirements", [
    ("index", ("concrete scenario", "LEARNING order", "No critique notes")),
    ("concept", ("prerequisite order", "fully worked miniature example", "教学构造，非论文实验")),
    ("method", ("Lagrangian", "derivatives", "normalize", "algorithm trace", "complete update")),
    ("experiment", ("HOW the evaluation relates", "axes", "do NOT turn unread", "absolute values")),
    ("review", ("整篇学习总结", "at most ONE concise critique", "a list of what was not proved")),
])
def test_each_stage_has_specific_learning_instructions_and_safe_source_contract(kind, requirements):
    prompt = reading_api.system_prompt(kind)
    for requirement in requirements:
        assert requirement in prompt
    assert "learning tutor, NOT a peer reviewer" in prompt
    assert "Missing from extracted text or unread" in prompt
    assert "does NOT mean absent from the paper" in prompt
    assert "Do not silently correct numbers" in prompt
    assert "NO self-tests" in prompt and "UNTRUSTED DATA" in prompt
    assert "FINAL API OUTPUT CONTRACT" in prompt and "exact ID from paper_source_data" in prompt
    # Never present a dummy source_id in the schema for the model to copy.
    assert '"evidence":[]' in prompt and '"source_id":"EXACT' not in prompt


def test_learning_estimate_freezes_style_prompts_and_full_source_without_creating_a_job(reading_client):
    client, reader = reading_client
    paper = upload(client)
    reader.call_provider = lambda *_: pytest.fail("Estimation cannot call a model")
    quote = estimate(client, paper)
    assert quote["reading_style"] == LEARNING_STYLE
    assert quote["workflow"] == "whole-paper-topics-v1"
    assert [stage["label"] for stage in quote["stages"]] == [
        "全文初读与学习路线", "前置知识与概念算例 · 全文", "逐步推导与算法演示 · 全文",
        "实验设计与结果解读 · 全文", "整篇学习总结与补充评析"]
    with reader.store.connection() as db:
        frozen = json.loads(db.execute("SELECT data FROM translation_quotes WHERE id=?", (quote["quote_id"],)).fetchone()[0])
        assert db.execute("SELECT COUNT(*) FROM translation_jobs").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM translation_receipts").fetchone()[0] == 0
    for stage in frozen["stages"]:
        assert stage["reading_style"] == LEARNING_STYLE
        assert stage["system"] == reading_api.system_prompt(stage["kind"])
        assert [page["page"] for page in stage["base"]["paper_source_data"]] == list(range(1, 6))
    assert reader.ai.settings()["spent_cny"] == 0


def test_tutor_style_is_visible_on_started_completed_and_listed_jobs(reading_client):
    client, reader = reading_client
    paper = upload(client)
    calls = []
    reader.call_provider = lambda *args: calls.append(args) or provider(*args)
    response = start(client, paper, estimate(client, paper))
    assert response.status_code == 202 and response.json()["reading_style"] == LEARNING_STYLE
    job = wait(client, response.json()["id"])
    assert job["reading_style"] == LEARNING_STYLE and job["completed_stages"] == 5
    assert all("learning tutor, NOT a peer reviewer" in call[1] for call in calls)
    assert client.get(f"/api/papers/{paper['id']}/reading/jobs").json()["jobs"][0]["reading_style"] == LEARNING_STYLE
    assert client.get(f"/api/papers/{paper['id']}").json()["notes_count"] == 0


def test_original_thematic_job_keeps_its_style_and_prompts_when_resumed(reading_client):
    client, reader = reading_client
    paper = upload(client)
    job, _, calls = failed_after_first_stage(client, reader, paper)
    with reader.store.connection() as db:
        plan = json.loads(db.execute("SELECT plan FROM reading_runs WHERE id=?", (job["id"],)).fetchone()[0])
        for stage in plan:
            stage.pop("reading_style")
            stage["system"] = f"Frozen original full-paper protocol for {stage['kind']}"
        frozen = json.dumps(plan)
        db.execute("UPDATE reading_runs SET plan=? WHERE id=?", (frozen, job["id"]))
    assert client.get(f"/api/reading/jobs/{job['id']}").json()["reading_style"] == "original"
    quote = client.post(f"/api/reading/jobs/{job['id']}/resume/estimate").json()
    assert quote["reading_style"] == "original" and quote["workflow"] == "whole-paper-topics-v1"
    response = client.post(f"/api/reading/jobs/{job['id']}/resume", json={"quote_id":quote["quote_id"],"max_cost_cny":5})
    assert response.status_code == 202
    complete = wait(client, job["id"])
    assert complete["reading_style"] == "original" and complete["status"] == "completed"
    assert [call[1] for call in calls[2:]] == [stage["system"] for stage in plan[1:]]
    with reader.store.connection() as db:
        assert db.execute("SELECT plan FROM reading_runs WHERE id=?", (job["id"],)).fetchone()[0] == frozen
    assert any(note["content"] == job["notes"][0]["content"] for note in complete["notes"])
    assert estimate(client, paper)["reading_style"] == LEARNING_STYLE


def test_policy_change_requires_a_new_explicit_fee_estimate_before_dispatch(reading_client, monkeypatch):
    client, reader = reading_client
    paper = upload(client)
    quote = estimate(client, paper)
    reader.call_provider = lambda *_: pytest.fail("A stale quote cannot call a model")
    monkeypatch.setattr(reading_api, "LEARNING_STYLE", "future-learning-style")
    assert start(client, paper, quote).status_code == 409
    assert reader.ai.settings()["spent_cny"] == 0


def test_worked_teaching_examples_are_not_rejected_as_self_tests(reading_client):
    client, reader = reading_client
    paper = upload(client)

    def teach(*args):
        response = provider(*args)
        document = json.loads(response["choices"][0]["message"]["content"])
        if json.loads(args[2])["stage_kind"] == "concept":
            note = document["notes"][0]
            note["title"] = "服务率与排队：完整演算的教学例子"
            note["content"] += "\n\n教学构造，非论文实验：令到达率为 8、服务率为 10，利用率为 0.8。服务时间为 0.1 秒，等待时间为 0.2 秒，总时延为 0.3 秒。这些数值是帮助理解公式的构造值，不是作者实测数据。"
        response["choices"][0]["message"]["content"] = json.dumps(document)
        return response

    reader.call_provider = teach
    job = wait(client, start(client, paper, estimate(client, paper)).json()["id"])
    assert job["status"] == "completed" and job["reading_style"] == LEARNING_STYLE
    assert any("教学构造，非论文实验" in note["content"] for note in job["notes"])
    assert STANDARD_VERSION == "2026-10-24.2"
