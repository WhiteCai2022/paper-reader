import hashlib
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.tests.test_api import upload
from backend.translation import ProviderError, TranslationService


@pytest.fixture
def translation_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-translation-test-only")
    app = create_app(data_dir=tmp_path / "data", frontend_dist=tmp_path / "dist")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        translator = app.state.translator

        def source(paper_id, page):
            paper = translator.paper(paper_id)
            if not 1 <= page <= paper["page_count"]:
                from fastapi import HTTPException
                raise HTTPException(422, "Invalid page")
            text = f"Page {page}. We study adaptive partitioning for efficient collaborative neural network inference."
            return text, hashlib.sha256(text.encode()).hexdigest()

        monkeypatch.setattr(translator, "source_page", source)
        yield client, translator


def response(content="这是完整的中文译文。", finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {"content": content}}],
            "usage": {"prompt_tokens": 200, "prompt_cache_hit_tokens": 50, "completion_tokens": 300}}


def estimate(client, paper, pages=None):
    result = client.post(f"/api/papers/{paper['id']}/translations/estimate", json={"pages": pages or [1]})
    assert result.status_code == 200, result.text
    return result.json()


def start(client, paper, quote, limit=0.5):
    return client.post(f"/api/papers/{paper['id']}/translations", json={"quote_id": quote["quote_id"], "max_cost_cny": limit})


def wait(client, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"/api/translation/jobs/{job_id}").json()
        if job["status"] not in {"queued", "running", "cancelling"}:
            return job
        time.sleep(0.01)
    pytest.fail("Translation job did not finish")


def test_estimate_is_free_and_cache_is_idempotent(translation_client):
    client, translator = translation_client
    paper = upload(client)
    calls = []
    translator.call_provider = lambda *args: calls.append(args) or response()
    quote = estimate(client, paper, [1, 1])
    assert quote["total_pages"] == 1
    assert quote["upper_bound_cny"] > quote["estimated_cny"] > 0
    assert calls == []
    assert client.get("/api/translation/settings").json()["spent_cny"] == 0
    result = start(client, paper, quote)
    assert result.status_code == 202
    job = wait(client, result.json()["id"])
    assert job["status"] == "completed"
    assert job["completed_pages"] == 1
    assert job["cost_cny"] == pytest.approx(0.002702)
    assert len(calls) == 1
    assert start(client, paper, quote).json()["id"] == job["id"]
    cached = client.get(f"/api/papers/{paper['id']}/translations/pages/1").json()
    assert cached["translation"]["content"] == "这是完整的中文译文。"
    assert cached["source_text"].startswith("Page 1")
    second = estimate(client, paper)
    assert second["upper_bound_cny"] == second["estimated_cny"] == 0
    assert wait(client, start(client, paper, second, limit=0).json()["id"])["status"] == "completed"
    assert len(calls) == 1
    exported = client.get(f"/api/papers/{paper['id']}/translations/export").text
    assert "### 原文" in exported and "### 译文" in exported
    settings = client.get("/api/translation/settings").json()
    assert settings["reserved_cny"] == 0
    assert "sk-translation-test-only" not in json.dumps(settings)
    client.delete(f"/api/papers/{paper['id']}")
    assert translator.cached(paper["id"], 1) is None
    assert client.get("/api/translation/settings").json()["spent_cny"] == settings["spent_cny"]


def test_single_and_total_budget_prevent_provider_calls(translation_client):
    client, translator = translation_client
    paper = upload(client)
    translator.call_provider = lambda *args: pytest.fail("Budget rejection must not call provider")
    quote = estimate(client, paper)
    assert start(client, paper, quote, limit=0).status_code == 422
    assert client.patch("/api/translation/settings", json={"total_budget_cny": 0}).status_code == 200
    assert start(client, paper, quote).status_code == 422
    assert translator.summary(paper["id"])["job"] is None


@pytest.mark.parametrize("pages", [[], [0], [1.2], [True], [6], list(range(1, 502))])
def test_invalid_page_selections(translation_client, pages):
    client, _ = translation_client
    paper = upload(client)
    assert client.post(f"/api/papers/{paper['id']}/translations/estimate", json={"pages": pages}).status_code == 422


@pytest.mark.parametrize("uncertain", [False, True])
def test_errors_are_not_automatically_retried(translation_client, uncertain):
    client, translator = translation_client
    paper = upload(client)
    calls = []

    def failure(*args):
        calls.append(args)
        raise ProviderError("Test provider error", uncertain=uncertain)

    translator.call_provider = failure
    quote = estimate(client, paper, [1, 2])
    job = wait(client, start(client, paper, quote).json()["id"])
    assert job["status"] == "failed"
    assert len(calls) == 1
    assert translator.summary(paper["id"])["pages"] == []
    settings = translator.settings()
    assert settings["reserved_cny"] == 0
    assert settings["spent_cny"] == (quote["pages"][0]["upper_bound_cny"] if uncertain else 0)
    assert settings["uncertain_cny"] == settings["spent_cny"]


def test_truncated_output_records_cost_without_caching(translation_client):
    client, translator = translation_client
    paper = upload(client)
    translator.call_provider = lambda *args: response("不完整", finish="length")
    job = wait(client, start(client, paper, estimate(client, paper)).json()["id"])
    assert job["status"] == "failed"
    assert translator.settings()["spent_cny"] > 0
    assert translator.cached(paper["id"], 1) is None


def test_cancel_stops_next_page_and_keeps_finished_page(translation_client):
    client, translator = translation_client
    paper = upload(client)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def blocking(*args):
        calls.append(args)
        entered.set()
        assert release.wait(5)
        return response()

    translator.call_provider = blocking
    try:
        job = start(client, paper, estimate(client, paper, [1, 2])).json()
        assert entered.wait(3)
        assert translator.settings()["reserved_cny"] > 0
        assert client.patch("/api/translation/settings", json={"total_budget_cny": 0}).status_code == 422
        assert client.post(f"/api/translation/jobs/{job['id']}/cancel").json()["status"] == "cancelling"
    finally:
        release.set()
    finished = wait(client, job["id"])
    assert finished["status"] == "cancelled"
    assert finished["completed_pages"] == 1
    assert len(calls) == 1
    assert translator.cached(paper["id"], 1)
    assert not translator.cached(paper["id"], 2)


def test_global_reservation_prevents_concurrent_overspending(translation_client):
    client, translator = translation_client
    first, second = upload(client), upload(client)
    entered, release = threading.Event(), threading.Event()
    quote = estimate(client, first)
    client.patch("/api/translation/settings", json={"total_budget_cny": quote["upper_bound_cny"] * 1.5})

    def blocking(*args):
        entered.set()
        assert release.wait(5)
        return response()

    translator.call_provider = blocking
    try:
        job = start(client, first, quote).json()
        assert entered.wait(3)
        assert start(client, second, estimate(client, second)).status_code == 422
    finally:
        release.set()
    assert wait(client, job["id"])["status"] == "completed"


def test_stale_and_expired_estimates_are_rejected(translation_client, monkeypatch):
    client, translator = translation_client
    paper = upload(client)
    quote = estimate(client, paper)
    source = translator.source_page
    monkeypatch.setattr(translator, "source_page", lambda *args: ("changed", "new-hash"))
    assert start(client, paper, quote).status_code == 409
    monkeypatch.setattr(translator, "source_page", source)
    with translator.store.connection() as connection:
        connection.execute("UPDATE translation_quotes SET expires=0")
    assert start(client, paper, quote).status_code == 409


def test_restart_keeps_uncertain_usage_and_releases_future_pages(translation_client):
    client, translator = translation_client
    paper = upload(client)
    with translator.store.connection() as connection:
        connection.execute("INSERT INTO translation_jobs(id,paper_id,status,pages,total_pages,reserved_cny) VALUES ('restart',?,'running','[1,2]',2,0.2)", (paper["id"],))
        connection.execute("INSERT INTO translation_receipts(id,job_id,page,status,cost_cny) VALUES ('receipt','restart',1,'pending',0.1)")
    restarted = TranslationService(translator.store)
    try:
        assert restarted.job("restart")["status"] == "interrupted"
        assert restarted.settings()["reserved_cny"] == 0
        assert restarted.settings()["spent_cny"] == restarted.settings()["uncertain_cny"] == 0.1
    finally:
        restarted.close()


def test_blank_scanned_page_does_not_call_provider(translation_client, monkeypatch):
    client, translator = translation_client
    paper = upload(client)
    monkeypatch.setattr(translator, "source_page", lambda *args: ("", "empty"))
    result = client.post(f"/api/papers/{paper['id']}/translations/estimate", json={"pages": [1]})
    assert result.status_code == 422
    assert "扫描" in result.json()["detail"]


def test_windows_key_storage_is_protected(tmp_path):
    import os
    from backend.translation_config import TranslationConfig
    if os.name != "nt":
        pytest.skip("Windows DPAPI")
    config = TranslationConfig(tmp_path)
    value = "sk-protected-storage-test-only"
    config.update(api_key=value)
    assert value not in config.path.read_text()
    stored = config.read()["protected_api_key"]
    from backend.translation_config import protect_secret
    assert protect_secret(stored, decrypt=True) == value


@pytest.mark.parametrize("model", ["deepseek-flash", "deepseek-v4-pro"])
@pytest.mark.parametrize("effort", ["none", "low", "high", "max"])
def test_provider_sends_selected_model_and_reasoning(monkeypatch, model, effort):
    import io
    from backend import translation
    sent = []

    class Opener:
        def open(self, request, timeout):
            sent.append(json.loads(request.data))
            return io.BytesIO(json.dumps(response()).encode())

    monkeypatch.setattr(translation, "build_opener", lambda *args: Opener())
    translation.call_deepseek("sk-test-not-used", "test source text", 9000, model, effort)
    assert sent[0]["model"] == model
    assert sent[0]["thinking"]["type"] == ("disabled" if effort == "none" else "enabled")
    assert sent[0].get("reasoning_effort") == (None if effort == "none" else effort)
    assert sent[0]["max_tokens"] == 9000


def test_variants_keep_cache_separate_and_use_selected_prices(translation_client):
    client, translator = translation_client
    paper = upload(client)
    calls = []

    def provider(*args):
        calls.append(args)
        value = response(f"译文：{args[3]} / {args[4]}")
        value["usage"]["completion_tokens_details"] = {"reasoning_tokens": 100}
        return value

    translator.call_provider = provider
    for model, effort in [("deepseek-flash", "none"), ("deepseek-v4-pro", "high"), ("deepseek-flash", "high")]:
        result = client.post(f"/api/papers/{paper['id']}/translations/estimate", json={"pages": [1], "model": model, "reasoning_effort": effort})
        assert result.status_code == 200
        quote = result.json()
        assert quote["cached_pages"] == 0
        job = wait(client, start(client, paper, quote, limit=2).json()["id"])
        assert (job["model"], job["reasoning_effort"]) == (model, effort)
        assert job["status"] == "completed"
        assert job["cost_cny"] == pytest.approx(0.009465 if model == "deepseek-v4-pro" else 0.002702)
    assert [(args[3], args[4]) for args in calls] == [("deepseek-flash", "none"), ("deepseek-v4-pro", "high"), ("deepseek-flash", "high")]
    assert calls[1][2] > calls[0][2]
    for model, effort in [("deepseek-flash", "none"), ("deepseek-v4-pro", "high"), ("deepseek-flash", "high")]:
        query = f"model={model}&reasoning_effort={effort}"
        page = client.get(f"/api/papers/{paper['id']}/translations/pages/1?{query}").json()
        assert page["translation"]["content"] == f"译文：{model} / {effort}"
        quote = client.post(f"/api/papers/{paper['id']}/translations/estimate", json={"pages": [1], "model": model, "reasoning_effort": effort}).json()
        assert quote["cached_pages"] == 1 and quote["upper_bound_cny"] == 0
        assert client.get(f"/api/papers/{paper['id']}/translations?{query}").json()["pages"][0]["reasoning_effort"] == effort
        exported = client.get(f"/api/papers/{paper['id']}/translations/export?{query}").text
        assert f"译文：{model} / {effort}" in exported
    assert len(calls) == 3
    assert client.get(f"/api/papers/{paper['id']}/translations/pages/1?model=deepseek-v4-pro&reasoning_effort=max").json()["translation"] is None


def test_reasoning_and_pro_costs_require_larger_reservations(translation_client):
    client, _ = translation_client
    paper = upload(client)
    amounts = []
    for effort in ["none", "low", "high", "max"]:
        value = client.post(f"/api/papers/{paper['id']}/translations/estimate", json={"pages": [1], "model": "deepseek-flash", "reasoning_effort": effort}).json()
        amounts.append(value["upper_bound_cny"])
    assert all(right > left for left, right in zip(amounts, amounts[1:]))
    pro = client.post(f"/api/papers/{paper['id']}/translations/estimate", json={"pages": [1], "model": "deepseek-v4-pro", "reasoning_effort": "max"}).json()
    assert pro["upper_bound_cny"] > amounts[-1]
    assert start(client, paper, pro, limit=amounts[0]).status_code == 422


@pytest.mark.parametrize("options", [{"model": "unknown"}, {"reasoning_effort": "medium"}, {"reasoning_effort": "invalid"}])
def test_invalid_model_and_effort_rejected(translation_client, options):
    client, _ = translation_client
    paper = upload(client)
    assert client.post(f"/api/papers/{paper['id']}/translations/estimate", json={"pages": [1], **options}).status_code == 422
    assert client.get(f"/api/papers/{paper['id']}/translations/pages/1", params=options).status_code == 422


def test_migration_preserves_existing_paid_translation(translation_client):
    client, translator = translation_client
    paper = upload(client)
    text, digest = translator.source_page(paper["id"], 1)
    with translator.store.connection() as connection:
        connection.execute("DROP TABLE translation_pages")
        connection.execute("""CREATE TABLE translation_pages (
            paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE, page INTEGER NOT NULL,
            source_hash TEXT NOT NULL, source_text TEXT NOT NULL, content TEXT NOT NULL, model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, cost_cny REAL NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(paper_id,page))""")
        connection.execute("INSERT INTO translation_pages(paper_id,page,source_hash,source_text,content,model,input_tokens,output_tokens,cost_cny) VALUES (?,1,?,?,'旧译文','deepseek-flash',100,100,0.001)", (paper["id"], digest, text))
    for _ in range(2):
        migrated = TranslationService(translator.store)
        try:
            cached = migrated.cached(paper["id"], 1, digest)
            assert cached["content"] == "旧译文"
            assert cached["reasoning_effort"] == "none"
            assert cached["cost_cny"] == 0.001
            assert migrated.cached(paper["id"], 1, digest, "deepseek-v4-pro", "high") is None
        finally:
            migrated.close()


def balance_response(amount="12.3456", currency="CNY", available=True):
    return {"is_available": available, "balance_infos": [{"currency": currency, "total_balance": amount,
            "granted_balance": "0.50", "topped_up_balance": "11.8456"}]}


def test_official_balance_get_request_has_no_model_call(monkeypatch):
    import io
    from backend import translation
    sent = []

    class Opener:
        def open(self, request, timeout):
            sent.append(request)
            return io.BytesIO(json.dumps(balance_response()).encode())

    monkeypatch.setattr(translation, "build_opener", lambda *args: Opener())
    value = translation.fetch_deepseek_balance("sk-balance-test-only")
    assert value["balance_infos"][0]["total_balance"] == "12.3456"
    assert sent[0].full_url == "https://api.deepseek.com/user/balance"
    assert sent[0].get_method() == "GET"
    assert sent[0].data is None
    assert sent[0].get_header("Authorization") == "Bearer sk-balance-test-only"


def test_balance_is_cached_refreshable_and_preserves_currency(translation_client):
    client, translator = translation_client
    calls = []
    translator.balance_provider = lambda key: calls.append(key) or balance_response(currency="USD")
    first = client.get("/api/translation/balance").json()
    assert first["status"] == "ok"
    assert first["balance_infos"][0]["currency"] == "USD"
    assert first["balance_infos"][0]["total_balance"] == "12.3456"
    assert first["checked_at"]
    assert len(calls) == 1
    assert client.get("/api/translation/balance").json() == first
    assert len(calls) == 1
    assert client.get("/api/translation/balance?refresh=true").json()["status"] == "ok"
    assert len(calls) == 2
    assert "sk-translation-test-only" not in json.dumps(first)
    settings = client.get("/api/translation/settings").json()
    assert settings["key_hint"] == "••••only"
    assert first["key_id"] == settings["key_id"]
    assert settings["key_source"] == "environment"


@pytest.mark.parametrize("invalid", [{"is_available": True, "balance_infos": []}, balance_response(amount="NaN"), balance_response(currency="EUR"), {"is_available": "true", "balance_infos": balance_response()["balance_infos"]}])
def test_invalid_balance_is_not_reported_as_zero(translation_client, invalid):
    client, translator = translation_client
    translator.balance_provider = lambda key: invalid
    value = client.get("/api/translation/balance").json()
    assert value["status"] == "error"
    assert value["balance_infos"] == []
    assert value["is_available"] is None
    assert value["error"]


def test_bind_validates_before_replacing_key_and_invalidates_quotes(translation_client):
    client, translator = translation_client
    paper = upload(client)
    quote = estimate(client, paper)
    new_key = "sk-bound-account-test-only"
    calls = []

    def balances(key):
        calls.append(key)
        if key == "sk-invalid-account-test":
            raise ProviderError("API Key 无效，请检查后重新绑定。")
        return balance_response(amount="8.10" if key == new_key else "12.3456")

    translator.balance_provider = balances
    old_settings = translator.settings()
    assert client.get("/api/translation/balance").json()["balance_infos"][0]["total_balance"] == "12.3456"
    failed = client.patch("/api/translation/settings", json={"api_key": "sk-invalid-account-test", "total_budget_cny": 10})
    assert failed.status_code == 422
    assert translator.settings()["key_id"] == old_settings["key_id"]
    assert translator.settings()["total_budget_cny"] == old_settings["total_budget_cny"]
    assert translator.config.api_key() == "sk-translation-test-only"
    bound = client.patch("/api/translation/settings", json={"api_key": new_key})
    assert bound.status_code == 200
    assert bound.json()["configured"] is True
    assert bound.json()["key_source"] == "local"
    assert bound.json()["key_id"] != old_settings["key_id"]
    assert new_key not in bound.text
    assert new_key not in translator.config.path.read_text()
    assert translator.config.api_key() == new_key
    count = len(calls)
    balance = client.get("/api/translation/balance").json()
    assert balance["balance_infos"][0]["total_balance"] == "8.10"
    assert balance["key_id"] == bound.json()["key_id"]
    assert len(calls) == count
    assert start(client, paper, quote).status_code == 409


def test_unbind_does_not_fall_back_to_environment_or_call_provider(translation_client):
    client, translator = translation_client
    translator.balance_provider = lambda key: pytest.fail("Unbinding must not query the old account")
    assert client.patch("/api/translation/settings", json={"api_key": ""}).json()["configured"] is False
    assert translator.config.api_key() == ""
    value = client.get("/api/translation/balance").json()
    assert value["status"] == "unconfigured" and value["key_id"] is None
    assert value["balance_infos"] == []


def test_zero_or_negative_official_balance_is_preserved(translation_client):
    client, translator = translation_client
    translator.balance_provider = lambda key: balance_response(amount="-0.01", available=False)
    value = client.get("/api/translation/balance").json()
    assert value["status"] == "ok"
    assert value["is_available"] is False
    assert value["balance_infos"][0]["total_balance"] == "-0.01"


def test_network_error_never_returns_a_different_keys_cached_balance(translation_client):
    client, translator = translation_client
    def balances(key):
        if key == "sk-translation-test-only":
            return balance_response()
        raise ProviderError("余额接口暂不可用")
    translator.balance_provider = balances
    original = client.get("/api/translation/balance").json()
    result = translator.read_balance("sk-different-account", refresh=True)
    assert result["status"] == "error" and result["balance_infos"] == []
    assert result["key_id"] != original["key_id"]
    assert client.get("/api/translation/balance").json()["balance_infos"] == original["balance_infos"]


def test_key_cannot_change_while_a_translation_is_running(translation_client):
    client, translator = translation_client
    paper = upload(client)
    entered, release = threading.Event(), threading.Event()
    def blocking(*args):
        entered.set()
        assert release.wait(5)
        assert args[0] == "sk-translation-test-only"
        return response()
    translator.call_provider = blocking
    translator.balance_provider = lambda key: pytest.fail("Must reject key change before verification")
    try:
        job = start(client, paper, estimate(client, paper)).json()
        assert entered.wait(3)
        assert client.patch("/api/translation/settings", json={"api_key": "sk-new-during-job"}).status_code == 409
    finally:
        release.set()
    assert wait(client, job["id"])["status"] == "completed"
