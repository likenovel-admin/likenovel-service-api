"""Storyctx model snapshots and durable HTTP boundaries; no paid calls or DB writes."""
import json
import asyncio
from functools import wraps
from dataclasses import replace
from unittest.mock import patch

import httpx
import pytest

from app.services.common.ai_model_config import (
    FEATURE_CATALOG, FLASH_1017_MODEL, default_model_binding,
    get_model_binding, has_ai_model_snapshot, use_ai_model_snapshot,
)
from scripts.character_asset_attempt import CharacterAssetAttemptBlocked, attempt_key
from tests.test_character_asset_attempt import ReceiptConnection
from tests.test_story_agent_context_cost_guard import load_module


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


def snapshot(route="hive", revision=1):
    rows = {key: default_model_binding(key) for key in FEATURE_CATALOG}
    for key in ("storyctx.summary", "storyctx.signals", "storyctx.scenes", "storyctx.protagonist", "storyctx.rp"):
        rows[key] = replace(rows[key], model_id=FLASH_1017_MODEL, billing_route=route, revision=revision)
    return rows


@pytest.fixture
def prepaid_file(tmp_path, monkeypatch):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"hive": [{"id": "hive-1", "api_key": "synthetic-hive-key"}]}))
    path.chmod(0o600)
    monkeypatch.setenv("AI_PROVIDER_ACCOUNTS_FILE", str(path))


def completion(*, finish_reason="stop", model="deepseek-ai/deepseek-v4.1-flash-1017"):
    return {"model": model, "choices": [{"finish_reason": finish_reason, "message": {"content": '{"valid":true}'}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


async def request_asset(module, client, *, scope="episode:1"):
    return await module._request_character_asset_json(
        client, stage="signals", scope=scope, contract="test-v1",
        request_payload={"model": "old/default", "messages": [{"role": "user", "content": "synthetic"}], "response_format": {"type": "json_object"}, "max_tokens": 64},
        validate=lambda payload: payload, title="synthetic test", product_id=10,
    )


@async_test
async def test_snapshot_model_is_used_in_payload_and_receipt_before_gateway(prepaid_file):
    module = load_module()
    seen = []
    original = snapshot()
    def handler(req):
        seen.append(json.loads(req.content))
        original["storyctx.signals"] = replace(original["storyctx.signals"], model_id="changed/after-submit", revision=2)
        return httpx.Response(200, json=completion())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with use_ai_model_snapshot(original):
            assert await request_asset(module, client) == {"valid": True}
            assert get_model_binding("storyctx.signals").model_id == FLASH_1017_MODEL
            assert await request_asset(module, client) == {"valid": True}
    assert len(seen) == 1
    assert seen[0]["model"] == "deepseek-ai/deepseek-v4.1-flash-1017"
    assert not has_ai_model_snapshot()
    assert all(row["status"] == "accepted" for row in module._character_asset_attempt_store.connection.rows.values())


@async_test
async def test_billing_route_change_reuses_the_same_accepted_logical_request(prepaid_file):
    module = load_module()
    seen = []
    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200, json=completion())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with use_ai_model_snapshot(snapshot("hive", 1)):
            await request_asset(module, client)
        with use_ai_model_snapshot(snapshot("openrouter", 2)):
            await request_asset(module, client)
    assert len(seen) == 1
    assert len(module._character_asset_attempt_store.connection.rows) == 1


@async_test
async def test_new_model_cannot_submit_past_an_unresolved_scope(prepaid_file):
    module = load_module()
    store = module._character_asset_attempt_store
    old = attempt_key(10, "signals", "episode:1", "test-v1", {"model": "previous"})
    store.claim(old)
    seen = []
    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=completion())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with use_ai_model_snapshot(snapshot()), pytest.raises(CharacterAssetAttemptBlocked, match="duplicate_claim"):
            await request_asset(module, client)
    assert not seen
    assert list(store.connection.rows) == [old]


@async_test
@pytest.mark.parametrize("finish_reason", ["length", "content_filter", None])
async def test_parseable_but_incomplete_json_is_not_accepted(prepaid_file, finish_reason):
    module = load_module()
    posts = []
    def handler(req):
        posts.append(req)
        return httpx.Response(200, json=completion(finish_reason=finish_reason))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with use_ai_model_snapshot(snapshot()):
            for _ in range(2):
                with pytest.raises(CharacterAssetAttemptBlocked, match="terminal_invalid"):
                    await request_asset(module, client)
    assert len(posts) == 1
    assert [r["status"] for r in module._character_asset_attempt_store.connection.rows.values()] == ["terminal_invalid"]


@async_test
async def test_prepaid_credit_fallback_claims_once_and_records_actual_provider(prepaid_file):
    module = load_module()
    module.OPENROUTER_API_KEY = "synthetic-or-key"
    seen = []
    records = []
    def handler(req):
        seen.append((req.method, req.url.host))
        if req.url.host == "api-cdn.thehive.ai":
            return httpx.Response(402, json={"error": {"code": "insufficient_credits"}})
        if req.method == "GET":
            return httpx.Response(200, json={"data": {"total_credits": 100, "total_usage": 0}})
        return httpx.Response(200, json=completion(model=FLASH_1017_MODEL))
    store = module._character_asset_attempt_store
    with patch.object(store, "claim", wraps=store.claim) as claim, patch.object(module, "_storyctx_usage_connection", object()), patch.object(module, "persist_ai_provider_usage_pymysql", side_effect=lambda conn, record: records.append(record)):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with use_ai_model_snapshot(snapshot()):
                await request_asset(module, client)
    claim.assert_called_once()
    assert seen == [("POST", "api-cdn.thehive.ai"), ("GET", "openrouter.ai"), ("POST", "openrouter.ai")]
    assert records[-1].provider == "openrouter"
    assert records[-1].requested_model == FLASH_1017_MODEL


@async_test
async def test_hive_usage_is_not_attributed_to_openrouter(prepaid_file):
    module = load_module()
    records = []
    def handler(req):
        assert req.method == "POST"
        assert req.url.host == "api-cdn.thehive.ai"
        return httpx.Response(200, json=completion())
    with patch.object(module, "_storyctx_usage_connection", object()), patch.object(module, "persist_ai_provider_usage_pymysql", side_effect=lambda conn, record: records.append(record)):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with use_ai_model_snapshot(snapshot()):
                await request_asset(module, client)
    assert records[0].provider == "hive"
    assert records[0].cost_source == "unavailable"
    assert records[0].cost_usd is None
    assert records[0].input_tokens == 10


@async_test
async def test_mixed_prepaid_job_does_not_fail_openrouter_preflight(prepaid_file):
    module = load_module()
    def handler(req):
        raise AssertionError("No credit check should precede a prepaid-only operation")
    with patch.object(module, "OPENROUTER_API_KEY", "synthetic"):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with use_ai_model_snapshot(snapshot()):
                await module.assert_storyctx_openrouter_apply_ready(client)



@async_test
async def test_cli_pins_one_snapshot_for_the_job_and_reloads_for_the_next():
    import io
    import sys
    from contextlib import redirect_stdout
    module = load_module()
    revision = [1]
    reads = []
    active_revisions = []

    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=()):
            self.sql = sql
            if "FROM tb_ai_model_config" in sql:
                reads.append(revision[0])
        def fetchall(self):
            if "FROM tb_ai_model_config" in self.sql:
                return [{"feature_key": "storyctx.signals", "model_id": FLASH_1017_MODEL, "billing_route": "hive", "revision": revision[0]}]
            return []
        def fetchone(self):
            return {"non_unique": 0} if "information_schema.statistics" in self.sql else None

    class Connection:
        def cursor(self): return Cursor()
        def close(self):
            if has_ai_model_snapshot():
                active_revisions.append(get_model_binding("storyctx.signals").revision)
        def commit(self): pass
        def rollback(self): pass

    with patch.object(module.pymysql, "connect", side_effect=lambda **kwargs: Connection()), patch.object(module, "DB_USER", "test"), patch.object(module, "DB_PASSWORD", "test"), patch.object(module, "OPENROUTER_API_KEY", ""), patch.object(module.settings, "ANTHROPIC_API_KEY", ""), patch.object(sys, "argv", [str(module.__file__), "--build-mode", "full", "--apply", "--product-id", "10"]), redirect_stdout(io.StringIO()):
        assert await module.main() == 0
        first = list(active_revisions)
        assert first and set(first) == {1}
        assert not has_ai_model_snapshot()
        revision[0] = 2
        active_revisions.clear()
        assert await module.main() == 0
    assert set(active_revisions) == {2}
    assert reads == [1, 2]
    assert not has_ai_model_snapshot()


def test_opening_label_uses_pinned_route_and_rejects_truncated_json(prepaid_file):
    from scripts import run_character_chat_opening_labeler as labeler
    choices = snapshot()
    choices["character.opening_label"] = replace(choices["character.opening_label"], model_id=FLASH_1017_MODEL, billing_route="hive", revision=3)
    seen = []
    finish = ["stop"]
    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json=completion(finish_reason=finish[0]))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client, use_ai_model_snapshot(choices):
        parsed, usage = labeler.request_openrouter_label(client, model="old/default", row={})
        assert parsed == {"valid": True}
        assert usage["ai_route"]["provider"] == "hive"
        assert seen[0]["model"] == "deepseek-ai/deepseek-v4.1-flash-1017"
        finish[0] = "length"
        with pytest.raises(labeler.LabelParseError, match="incomplete"):
            labeler.request_openrouter_label(client, model="old/default", row={})
