"""Task-boundary configuration tests without real DB or provider calls."""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.common.ai_model_config import (
    AiModelBinding, FEATURE_CATALOG, default_model_binding, get_model_binding,
    serialize_model_snapshot, use_ai_model_snapshot,
)
from app.services.ai import reader_agent_decision_service as reader
from app.services.ai import reader_agent_session_service as reader_session
from app.services.ai import mcp_operations, mcp_single_copy
from app.services.admin import admin_ai_metadata_service as admin_dna


def snapshot(feature, model, revision=1, route="openrouter"):
    result = {key: default_model_binding(key) for key in FEATURE_CATALOG}
    result[feature] = AiModelBinding(feature, model, route, revision)
    return result


def dna_module():
    path = Path(__file__).parents[1] / "dist/batch/extract_product_dna.py"
    spec = importlib.util.spec_from_file_location("batch_model_config_dna", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def response(content="{}", *, finish="stop", route=None):
    result = httpx.Response(200, request=httpx.Request("POST", "https://provider.invalid/chat/completions"), json={
        "model": "native-model", "choices": [{"finish_reason": finish, "message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "cost": 0.01},
    })
    result.extensions["ai_route"] = route or {"provider": "river", "account_alias": "river-2", "requested_model": "test/model-a", "resolved_model": "native-model", "config_revision": 1}
    return result


def test_dna_uses_pinned_model_and_preserves_actual_billing_route():
    module = dna_module()
    captured = []
    def post(_client, **kwargs):
        captured.append(kwargs)
        return response()
    with use_ai_model_snapshot(snapshot("dna.analysis", "test/model-a", route="river")), \
         patch.object(module, "OPENROUTER_API_KEY", "not-a-real-key"), \
         patch.object(module, "post_model_chat_completion", side_effect=post), \
         patch.object(module, "_build_openrouter_response_format", return_value={"type": "json_schema"}):
        raw, metadata = module._call_llm("system", "source", {})
        assert raw == "{}"
        assert metadata["provider"] == "river"
        assert metadata["model_route"]["account_alias"] == "river-2"
        assert metadata["model"] == "test/model-a"
        assert captured[0]["feature_key"] == "dna.analysis"
        assert captured[0]["json"]["model"] == "test/model-a"
        assert captured[0]["json"]["provider"]["require_parameters"] is True
        assert "model-a" in module._current_analysis_version()


@pytest.mark.parametrize("finish", ["length", None, "content_filter"])
def test_dna_rejects_incomplete_json_even_if_content_is_parseable(finish):
    module = dna_module()
    with patch.object(module, "OPENROUTER_API_KEY", "not-a-real-key"), \
         patch.object(module, "post_model_chat_completion", return_value=response(finish=finish)), \
         patch.object(module, "_build_openrouter_response_format", return_value={"type": "json_object"}):
        with pytest.raises(module.OpenRouterResponseValidationError):
            module.call_openrouter("system", "source", {})


def test_cms_dna_next_job_changes_model_but_active_job_stays_pinned():
    seen = []
    first = snapshot("dna.analysis", "test/model-a", 1)
    second = snapshot("dna.analysis", "test/model-b", 2)
    async def inner(_product, _db):
        seen.append(get_model_binding("dna.analysis").model_id)
        await asyncio.sleep(0)
        seen.append(get_model_binding("dna.analysis").model_id)
        return {"ok": True}
    async def run():
        with patch.object(admin_dna, "load_ai_model_snapshot", AsyncMock(side_effect=[first, second])), \
             patch.object(admin_dna, "_reanalyze_ai_product_metadata", side_effect=inner):
            await admin_dna.reanalyze_ai_product_metadata(1, object())
            await admin_dna.reanalyze_ai_product_metadata(2, object())
    asyncio.run(run())
    assert seen == ["test/model-a", "test/model-a", "test/model-b", "test/model-b"]


def test_reader_payload_and_report_use_same_pinned_model():
    captured = []
    async def post(_client, **kwargs):
        captured.append(kwargs)
        return response()
    async def run():
        with use_ai_model_snapshot(snapshot("ai_reader.decision", "test/model-a", route="river")), \
             patch.object(reader.settings, "OPENROUTER_API_KEY", "not-a-real-key"), \
             patch.object(reader, "post_model_chat_completion_async", side_effect=post):
            assert reader.reader_llm_model_name() == "test/model-a"
            result = await reader._call_openrouter_chat_completion(system_prompt="s", user_prompt="u", max_tokens=100)
            assert result.model_route["provider"] == "river"
    asyncio.run(run())
    assert len(captured) == 1
    assert captured[0]["json"]["model"] == "test/model-a"
    assert captured[0]["json"]["provider"]["require_parameters"] is True


def test_reader_transport_timeout_is_not_retried():
    async def run():
        with patch.object(reader.settings, "OPENROUTER_API_KEY", "not-a-real-key"), \
             patch.object(reader, "_post_openrouter_chat_completion", AsyncMock(side_effect=httpx.ReadTimeout("unknown"))) as post:
            with pytest.raises(httpx.ReadTimeout):
                await reader._call_openrouter_chat_completion(system_prompt="s", user_prompt="u", max_tokens=100)
            assert post.await_count == 1
    asyncio.run(run())


def test_existing_pending_reader_keeps_recorded_model_revision():
    original = AiModelBinding("ai_reader.decision", "test/old", "river", 4)
    stored = {"ai_model_binding": {"feature_key": original.feature_key, "model_id": original.model_id, "billing_route": original.billing_route, "revision": original.revision}, "episode": {"episode_id": 1}}
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = {"input_snapshot_json": json.dumps(stored), "model_name": "test/old"}
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    async def run():
        with patch.object(reader_session, "load_ai_model_snapshot", AsyncMock(return_value=snapshot("ai_reader.decision", "test/new", 9))), \
             patch.object(reader_session, "_reader_session_id", return_value="session-1"):
            pinned, original_input = await reader_session._reader_model_snapshot(SimpleNamespace(ai_reader_agent_id=1, user_id=2), db)
            assert pinned["ai_reader.decision"] == original
            assert original_input == stored
            assert reader_session._reader_llm_request_hash(original_input) == reader_session._reader_llm_request_hash(stored)
    asyncio.run(run())


def test_mcp_sse_gateway_preserves_json_validation_and_route():
    body = {"items": []}
    events = [
        {"choices": [{"index": 0, "delta": {"content": json.dumps(body)}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    wire = "".join("data: " + json.dumps(item) + "\n\n" for item in events) + "data: [DONE]\n\n"
    reply = httpx.Response(200, content=wire.encode())
    reply.extensions["ai_route"] = {"provider": "river", "account_alias": "river-1"}
    captured = []
    @contextmanager
    def stream(_client, **kwargs):
        captured.append(kwargs)
        yield reply
    with use_ai_model_snapshot(snapshot("mcp.single_copy", "test/model-a", route="river")), \
         patch.object(mcp_single_copy, "stream_model_chat_completion", side_effect=stream):
        result = mcp_single_copy.run_openrouter("not-a-real-key", "generate")
    assert result["items"] == []
    assert result["_model_route"]["account_alias"] == "river-1"
    assert captured[0]["json"]["model"] == "test/model-a"


def test_mcp_reuses_durable_snapshot_across_thread_boundary():
    pinned = snapshot("mcp.single_copy", "test/original", 3)
    seen = []
    async def inner(_job, _owner):
        seen.append(await asyncio.to_thread(lambda: get_model_binding("mcp.single_copy").model_id))
    async def run():
        with patch.object(mcp_operations.store, "get", return_value={"model_snapshot": serialize_model_snapshot(pinned)}), \
             patch.object(mcp_operations, "load_ai_model_snapshot", AsyncMock()) as load, \
             patch.object(mcp_operations, "_generate_single_pinned", side_effect=inner), \
             patch.object(mcp_operations.store, "save"):
            await mcp_operations._generate_single_inner("job", "owner")
            load.assert_not_awaited()
    asyncio.run(run())
    assert seen == ["test/original"]


def test_reader_audit_preserves_route_when_provider_does_not_report_cost():
    decision = reader.ReaderLlmDecision(True, 1, False, "none", "none", False, None, {"positive": [], "negative": []}, "continue")
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)))
    route = {"provider": "hive", "account_alias": "hive-1", "config_revision": 2}
    asyncio.run(reader_session.mark_reader_llm_decision_succeeded(db, llm_decision_id=9, decision=decision, usage=None, model_routes=(route,)))
    params = db.execute.await_args.args[1]
    assert json.loads(params["decision_json"])["_ai_model_routes"] == [route]
    assert params["estimated_cost_usd"] is None


def test_mcp_claim_pins_snapshot_before_background_execution():
    pinned = snapshot("mcp.single_copy", "test/model-at-claim", 4)
    claimed = []
    @asynccontextmanager
    async def database():
        yield object()
    def claim(job, owner, payload):
        claimed.append(payload)
        return False
    async def run():
        with patch.object(mcp_operations.store, "get", side_effect=[None, {"status": "generating"}]), \
             patch.object(mcp_operations.store, "claim", side_effect=claim), \
             patch.object(mcp_operations, "likenovel_db_session", database), \
             patch.object(mcp_operations, "load_ai_model_snapshot", AsyncMock(return_value=pinned)):
            return await mcp_operations.start_single("owner")
    assert asyncio.run(run())["status"] == "generating"
    assert claimed[0]["model_snapshot"]["mcp.single_copy"]["model_id"] == "test/model-at-claim"


def test_reader_reclaim_pending_does_not_submit_with_new_model():
    persisted = {"product": {"product_id": 1}, "episode": {"episode_id": 2}, "ai_model_binding": {"feature_key": "ai_reader.decision", "model_id": "test/old", "billing_route": "openrouter", "revision": 1}}
    row = {"input_snapshot_json": json.dumps(persisted), "model_name": "test/old"}
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = row
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    llm = AsyncMock()
    async def run():
        with patch.object(reader_session, "load_ai_model_snapshot", AsyncMock(return_value=snapshot("ai_reader.decision", "test/new", 2))), \
             patch.object(reader_session, "_reader_session_id", return_value="same-job"):
            with pytest.raises(reader_session.ReaderLlmDecisionAlreadyReservedError, match="recovery_required:reader_pending_decision"):
                await reader_session.process_reader_session_decision(SimpleNamespace(ai_reader_agent_id=1, user_id=2), db, llm_call=llm)
    asyncio.run(run())
    llm.assert_not_awaited()


def test_cms_dna_unknown_submission_blocks_before_any_provider_call():
    from app.exceptions import CustomResponseException
    from app.services.common.ai_model_config import MODEL_SUBMISSION_UNKNOWN_PREFIX
    row = MagicMock()
    row.mappings.return_value.one_or_none.return_value = {"analysis_attempt_count": 1, "analysis_error_message": MODEL_SUBMISSION_UNKNOWN_PREFIX + "ReadTimeout"}
    db = SimpleNamespace(execute=AsyncMock(return_value=row))
    async def run():
        with patch.object(admin_dna, "load_ai_model_snapshot", AsyncMock(return_value=snapshot("dna.analysis", "test/new", 2))), \
             patch.object(admin_dna, "_get_product_for_analysis", AsyncMock(return_value={"product_id": 1})), \
             patch.object(admin_dna, "post_model_chat_completion_async", AsyncMock()) as post:
            with pytest.raises(CustomResponseException) as raised:
                await admin_dna.reanalyze_ai_product_metadata(1, db)
            assert raised.value.status_code == 409
            assert raised.value.code == "recovery_required"
            post.assert_not_awaited()
    asyncio.run(run())


def test_dna_unknown_marker_preserves_last_good_fields_and_creates_missing_row():
    """SQLite SQL-dialect proxy; production MySQL readback remains a separate gate."""
    import re
    import sqlite3
    from app.services.common.ai_model_config import MODEL_SUBMISSION_UNKNOWN_PREFIX
    database = sqlite3.connect(":memory:")
    database.row_factory = sqlite3.Row
    database.execute("""CREATE TABLE tb_product_ai_metadata (
        product_id INTEGER PRIMARY KEY, analysis_status TEXT, analysis_attempt_count INTEGER,
        analysis_error_message TEXT, model_version TEXT, updated_date TEXT,
        premise TEXT, raw_analysis TEXT)""")
    database.execute("INSERT INTO tb_product_ai_metadata VALUES (1,'success',3,NULL,'old-version','old-date','original premise','{\"original\":true}')")
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def execute(self, sql, params):
            sql = sql.replace("%s", "?").replace("ON DUPLICATE KEY UPDATE", "ON CONFLICT(product_id) DO UPDATE SET")
            sql = re.sub(r"VALUES\((\w+)\)", r"excluded.\1", sql).replace("IF(", "IIF(").replace("NOW()", "CURRENT_TIMESTAMP")
            database.execute(sql, params)
    conn = SimpleNamespace(cursor=Cursor)
    module = dna_module()
    module.mark_submission_unknown(conn, 1, 4, "ReadTimeout")
    module.mark_submission_unknown(conn, 2, 1, "ReadTimeout")
    rows = [dict(row) for row in database.execute("SELECT * FROM tb_product_ai_metadata ORDER BY product_id")]
    assert rows[0]["analysis_status"] == "success"
    assert rows[0]["analysis_attempt_count"] == 3
    assert rows[0]["model_version"] == "old-version"
    assert rows[0]["premise"] == "original premise"
    assert rows[0]["raw_analysis"] == '{"original":true}'
    assert rows[0]["analysis_error_message"] == MODEL_SUBMISSION_UNKNOWN_PREFIX + "ReadTimeout"
    assert rows[1]["analysis_status"] == "failed"
    assert rows[1]["analysis_error_message"] == MODEL_SUBMISSION_UNKNOWN_PREFIX + "ReadTimeout"
    database.close()


def test_dna_force_selection_still_excludes_unknown_submission_exact_prefix():
    from app.services.common.ai_model_config import MODEL_SUBMISSION_UNKNOWN_PREFIX
    module = dna_module()
    captured = {}
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def execute(self, sql, params): captured.update(sql=sql, params=params)
        def fetchall(self): return []
    module.get_products(SimpleNamespace(cursor=Cursor), product_id=9, force=True)
    # The predicate is on the actual force query and uses exact prefix equality,
    # not LIKE where underscores would become wildcard matches.
    assert "LEFT(COALESCE(m.analysis_error_message, ''), CHAR_LENGTH(%s)) <> %s" in captured["sql"]
    assert captured["params"][:2] == [MODEL_SUBMISSION_UNKNOWN_PREFIX] * 2
    assert captured["params"][2] == 9
