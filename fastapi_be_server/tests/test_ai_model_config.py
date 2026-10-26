import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.exceptions import CustomResponseException
from app.schemas.ai_model import PutAiModelRequest, ValidateAiModelRequest
from app.services.common import ai_model_config as config
from app.services.admin import admin_ai_model_service as service


class Result:
    def __init__(self, rows=(), rowcount=1):
        self.rows, self.rowcount = list(rows), rowcount
    def mappings(self): return self
    def all(self): return self.rows
    def one_or_none(self): return self.rows[0] if self.rows else None


class Database:
    def __init__(self, current=None, update_count=1, history_error=None, insert_error=None):
        self.current, self.update_count = current, update_count
        self.history_error, self.insert_error = history_error, insert_error
        self.statements = []
        self.commit, self.rollback = AsyncMock(), AsyncMock()
    async def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, dict(params or {})))
        if sql.startswith("SELECT"):
            return Result([self.current] if self.current else [])
        if "INSERT INTO tb_ai_model_config_history" in sql and self.history_error:
            raise self.history_error
        if "INSERT INTO tb_ai_model_config\n" in sql and self.insert_error:
            raise self.insert_error
        return Result(rowcount=self.update_count)


def row(revision=1, model_id=config.FLASH_1017_MODEL, route="openrouter"):
    return {"feature_key": "storyctx.signals", "model_id": model_id, "billing_route": route, "revision": revision}


@pytest.mark.parametrize("feature_key", [
    "websochat.speed", "websochat.balance", "websochat.deep", "websochat.structured",
    "storyctx.signals", "storyctx.scenes", "storyctx.protagonist", "storyctx.rp",
])
def test_runtime_paid_model_restriction_is_checked_before_saving(feature_key):
    async def run():
        client = AsyncMock()
        with pytest.raises(CustomResponseException) as error:
            await service.validate_admin_ai_model(
                feature_key=feature_key, model_id="test/model:free",
                billing_route="openrouter", client=client,
            )
        assert error.value.status_code == 422
        assert ":free" in str(error.value)
        client.get.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize("old", sorted(config.LEGACY_V4_PRO_MODELS))
def test_legacy_environment_model_migrates_without_mutating_environment(monkeypatch, old):
    monkeypatch.setenv("STORY_AGENT_CHARACTER_SIGNALS_OPENROUTER_MODEL", old)
    assert config.default_model_binding("storyctx.signals").model_id == config.FLASH_1017_MODEL
    import os
    assert os.environ["STORY_AGENT_CHARACTER_SIGNALS_OPENROUTER_MODEL"] == old


def test_explicit_cms_model_is_not_rewritten():
    snapshot = asyncio.run(config.load_ai_model_snapshot(Database(row(model_id="deepseek/deepseek-v4-pro-0813"))))
    with config.use_ai_model_snapshot(snapshot):
        assert config.get_model_binding("storyctx.signals").model_id == "deepseek/deepseek-v4-pro-0813"


def test_signal_legacy_anthropic_default_requires_model_and_key(monkeypatch):
    monkeypatch.setenv("STORY_AGENT_RP_REASONING_MODEL", "anthropic.claude-sonnet-4-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    binding = config.default_model_binding("storyctx.signals")
    assert binding.model_id == "claude-sonnet-4-5"
    assert binding.billing_route == "anthropic"
    assert binding.revision == 0
    assert config.default_model_binding("storyctx.protagonist").billing_route == "openrouter"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert config.default_model_binding("storyctx.signals").billing_route == "openrouter"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("STORY_AGENT_RP_REASONING_MODEL", "")
    assert config.default_model_binding("storyctx.signals").billing_route == "openrouter"


def test_saved_openrouter_revision_overrides_signal_legacy_anthropic(monkeypatch):
    monkeypatch.setenv("STORY_AGENT_RP_REASONING_MODEL", "claude-sonnet-4-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    snapshot = asyncio.run(config.load_ai_model_snapshot(Database(row(revision=9))))
    with config.use_ai_model_snapshot(snapshot):
        binding = config.get_model_binding("storyctx.signals")
        assert binding.model_id == config.FLASH_1017_MODEL
        assert binding.billing_route == "openrouter"
        assert binding.revision == 9


def test_requested_initial_models_ignore_legacy_native_environment(monkeypatch):
    for name in ("ANTHROPIC_MODEL", "AI_CHAT_GEMINI_MODEL", "AI_READER_OPENROUTER_MODEL"):
        monkeypatch.setenv(name, "old-model")
    for key in ("ai_chat.tools", "ai_chat.answer", "ai_reader.decision"):
        assert config.default_model_binding(key).model_id == config.FLASH_1017_MODEL
    assert config.default_model_binding("ai_chat.answer").billing_route == "hive"
    assert config.default_model_binding("ai_reader.decision").billing_route == "hive"
    assert config.default_model_binding("ai_chat.tools").billing_route == "openrouter"
    assert config.get_feature("websochat.speed").required_capabilities == ("text",)
    assert config.get_feature("websochat.structured").required_capabilities == ("json_object",)


def test_active_job_keeps_revision_and_next_job_sees_change():
    async def run():
        db = Database(row())
        old = await config.load_ai_model_snapshot(db)
        assert not config.has_ai_model_snapshot()
        with config.use_ai_model_snapshot(old):
            db.current = row(2, route="river")
            new = await config.load_ai_model_snapshot(db)
            assert config.get_model_binding("storyctx.signals").revision == 1
            with config.use_ai_model_snapshot(new):
                assert config.get_model_binding("storyctx.signals").revision == 2
            assert config.get_model_binding("storyctx.signals").revision == 1
        assert not config.has_ai_model_snapshot()
        with config.use_ai_model_snapshot(new):
            assert config.get_model_binding("storyctx.signals").billing_route == "river"
    asyncio.run(run())


def test_parallel_jobs_have_isolated_model_snapshot():
    async def run():
        first = await config.load_ai_model_snapshot(Database(row()))
        second = dict(first)
        second["storyctx.signals"] = replace(first["storyctx.signals"], revision=2, billing_route="river")
        async def job(snapshot):
            with config.use_ai_model_snapshot(snapshot):
                await asyncio.sleep(0)
                return config.get_model_binding("storyctx.signals").billing_route
        assert await asyncio.gather(job(first), job(second)) == ["openrouter", "river"]
    asyncio.run(run())


def test_snapshot_is_immutable_serializable_and_rejects_mismatched_data():
    snapshot = asyncio.run(config.load_ai_model_snapshot(Database(row(7))))
    with pytest.raises(TypeError): snapshot["storyctx.signals"] = snapshot["storyctx.scenes"]
    with pytest.raises(AttributeError): snapshot["storyctx.signals"].revision = 9
    serialized = config.serialize_model_snapshot(snapshot)
    assert config.deserialize_model_snapshot(serialized) == snapshot
    copied = dict(snapshot)
    with config.use_ai_model_snapshot(copied):
        copied.clear()
        assert config.get_model_binding("storyctx.signals").revision == 7
    serialized["storyctx.signals"]["feature_key"] = "storyctx.scenes"
    with pytest.raises(ValueError, match="mismatch"): config.deserialize_model_snapshot(serialized)
    with pytest.raises(ValueError, match="incomplete"): config.deserialize_model_snapshot({})


def test_sync_and_async_loaders_return_same_snapshot():
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def execute(self, sql): assert sql.startswith("SELECT")
        def fetchall(self): return [row(4)]
    assert config.load_ai_model_snapshot_sync(SimpleNamespace(cursor=lambda: Cursor())) == asyncio.run(config.load_ai_model_snapshot(Database(row(4))))


@pytest.mark.parametrize("extra", [{"expected_revision": -1}, {"expected_revision": True}, {"billing_route": "unknown"}, {"api_key": "private"}])
def test_schema_rejects_unsafe_fields(extra):
    value = {"model_id": "deepseek/model", "billing_route": "openrouter", "expected_revision": 0, **extra}
    with pytest.raises(ValidationError): PutAiModelRequest(**value)


def validation(feature="storyctx.signals", model=config.FLASH_1017_MODEL, route="openrouter", parameters=("response_format", "structured_outputs", "tools", "tool_choice"), status=200):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"data": {"endpoints": [{"supported_parameters": list(parameters)}]}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await service.validate_admin_ai_model(feature_key=feature, model_id=model, billing_route=route, client=client)
    return run, calls


def test_reader_model_over_database_limit_fails_before_metadata_lookup():
    model = "a/" + "m" * 99
    assert len(model) == 101
    run, calls = validation(feature="ai_reader.decision", model=model)
    with pytest.raises(CustomResponseException) as error:
        asyncio.run(run())
    assert error.value.status_code == 400
    assert "100" in error.value.message
    assert not calls


@pytest.mark.parametrize("feature,model", [
    ("ai_reader.decision", config.FLASH_1017_MODEL),
    ("ai_reader.decision", "a/" + "m" * 98),
    ("storyctx.signals", "a/" + "m" * 99),
])
def test_reader_valid_ids_and_other_feature_long_id_keep_working(feature, model):
    run, calls = validation(feature=feature, model=model)
    assert asyncio.run(run())["data"]["valid"] is True
    assert len(calls) == 1


def test_metadata_validation_uses_fixed_host_get_only():
    run, calls = validation()
    result = asyncio.run(run())
    assert result["data"]["validation_level"] == "metadata"
    assert calls[0].method == "GET"
    assert str(calls[0].url) == "https://openrouter.ai/api/v1/models/deepseek/deepseek-v4.1-flash-1017/endpoints"
    assert "authorization" not in calls[0].headers


@pytest.mark.parametrize("feature,parameters", [("storyctx.signals", ["response_format"]), ("ai_chat.tools", ["response_format"]), ("storyctx.scenes", [])])
def test_missing_capability_rejected(feature, parameters):
    run, _ = validation(feature=feature, parameters=parameters)
    with pytest.raises(CustomResponseException) as error: asyncio.run(run())
    assert error.value.status_code == 422


@pytest.mark.parametrize("model", ["https://attacker.invalid/model", "deepseek/../../private", "deepseek/x?key=secret", "deepseek/x\nInjected:header"])
def test_model_cannot_inject_metadata_url(model):
    run, calls = validation(model=model)
    with pytest.raises(CustomResponseException): asyncio.run(run())
    assert not calls


def test_unknown_feature_and_redirect_fail_closed():
    run, calls = validation(feature="not.a.feature")
    with pytest.raises(CustomResponseException): asyncio.run(run())
    assert not calls
    run, calls = validation(status=302)
    with pytest.raises(CustomResponseException) as error: asyncio.run(run())
    assert error.value.status_code == 503
    assert len(calls) == 1


@pytest.mark.parametrize("body", [b"not-json", b"[]"])
def test_malformed_metadata_does_not_pass_validation(body):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))) as client:
            await service.validate_admin_ai_model(feature_key="storyctx.signals", model_id=config.FLASH_1017_MODEL, billing_route="openrouter", client=client)
    with pytest.raises(CustomResponseException) as error:
        asyncio.run(run())
    assert error.value.status_code == 503


def test_malformed_endpoint_capabilities_fail_closed():
    run, _ = validation(parameters=[{"unexpected": "object"}])
    with pytest.raises(CustomResponseException) as error:
        asyncio.run(run())
    assert error.value.status_code == 422


def test_metadata_timeout_is_sanitized():
    def handler(request):
        raise httpx.ReadTimeout("private-header-value", request=request)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await service.validate_admin_ai_model(feature_key="storyctx.signals", model_id=config.FLASH_1017_MODEL, billing_route="openrouter", client=client)
    with pytest.raises(CustomResponseException) as error:
        asyncio.run(run())
    assert error.value.status_code == 503
    assert "private-header-value" not in str(error.value)


def test_hive_unverified_tool_calls_are_not_downgraded():
    run, _ = validation(feature="ai_chat.tools", route="hive")
    with pytest.raises(CustomResponseException) as error: asyncio.run(run())
    assert error.value.status_code == 422
    assert "검증되지" in error.value.message


@pytest.mark.parametrize("provider,native_model", [("river", "deepseek-ai/DeepSeek-V4.1-Flash-1017"), ("hive", "deepseek-ai/deepseek-v4.1-flash-1017")])
def test_prepaid_json_requires_exact_model_on_each_account_and_does_not_return_keys(provider, native_model):
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.host == "openrouter.ai":
            return httpx.Response(200, json={"data": {"endpoints": [{"supported_parameters": ["response_format", "structured_outputs"]}]}})
        return httpx.Response(200, json={"data": [{"id": native_model}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await service.validate_admin_ai_model(feature_key="storyctx.signals", model_id=config.FLASH_1017_MODEL, billing_route=provider, client=client)
    with patch.object(service, "_provider_accounts", return_value=(SimpleNamespace(id="a", api_key="private-a"), SimpleNamespace(id="b", api_key="private-b"))):
        result = asyncio.run(run())
    assert len(calls) == 3
    assert calls[1].headers["authorization"] == "Bearer private-a"
    assert calls[2].headers["authorization"] == "Bearer private-b"
    assert "private" not in str(result)


def update(db, expected=1):
    return service.put_admin_ai_model(feature_key="storyctx.signals", model_id=config.FLASH_1017_MODEL, billing_route="river", expected_revision=expected, admin_user_id=21, db=db)


def test_initial_setting_and_history_commit_together():
    db = Database()
    with patch.object(service, "validate_admin_ai_model", new=AsyncMock()): result = asyncio.run(update(db, 0))
    assert result["data"]["revision"] == 1
    assert result["data"]["apply_policy"] == "next_job"
    assert result["data"]["title"]
    assert db.statements[-1][1]["admin_user_id"] == 21
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()


def test_update_uses_cas_and_records_prior_choice():
    db = Database(row())
    with patch.object(service, "validate_admin_ai_model", new=AsyncMock()): result = asyncio.run(update(db))
    assert result["data"]["revision"] == 2
    assert "revision = :expected_revision" in db.statements[1][0]
    assert db.statements[1][1]["expected_revision"] == 1
    assert db.statements[2][1]["previous_model_id"] == config.FLASH_1017_MODEL


@pytest.mark.parametrize("current,count", [(row(2), 1), (row(), 0)])
def test_conflict_does_not_commit_or_append_history(current, count):
    db = Database(current, update_count=count)
    with patch.object(service, "validate_admin_ai_model", new=AsyncMock()):
        with pytest.raises(CustomResponseException) as error: asyncio.run(update(db))
    assert error.value.status_code == 409
    assert not any("INSERT INTO tb_ai_model_config_history" in sql for sql, _ in db.statements)
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()


def test_duplicate_first_insert_is_conflict():
    import pymysql
    db = Database(insert_error=IntegrityError("insert", {}, pymysql.err.IntegrityError(1062, "duplicate")))
    with patch.object(service, "validate_admin_ai_model", new=AsyncMock()):
        with pytest.raises(CustomResponseException) as error: asyncio.run(update(db, 0))
    assert error.value.status_code == 409
    db.commit.assert_not_awaited()


def test_history_failure_rolls_back_setting():
    db = Database(row(), history_error=RuntimeError("history unavailable"))
    with patch.object(service, "validate_admin_ai_model", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="history unavailable"): asyncio.run(update(db))
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()


def test_validation_failure_does_not_access_database():
    db = Database(row())
    with patch.object(service, "validate_admin_ai_model", new=AsyncMock(side_effect=CustomResponseException(status_code=503, message="metadata unavailable"))):
        with pytest.raises(CustomResponseException): asyncio.run(update(db))
    assert not db.statements


def test_admin_endpoints_check_permission_before_service():
    from app.routers.admin import ai_model_command, ai_model_query
    async def run():
        db, user = object(), {"sub": "non-admin"}
        actions = [
            (ai_model_query, lambda: ai_model_query.get_ai_models(db=db, user=user)),
            (ai_model_command, lambda: ai_model_command.validate_ai_model(ValidateAiModelRequest(feature_key="storyctx.signals", model_id=config.FLASH_1017_MODEL, billing_route="openrouter"), db=db, user=user)),
            (ai_model_command, lambda: ai_model_command.put_ai_model("storyctx.signals", PutAiModelRequest(model_id=config.FLASH_1017_MODEL, billing_route="openrouter", expected_revision=0), db=db, user=user)),
        ]
        for module, action in actions:
            with patch.object(module, "check_user", new=AsyncMock(side_effect=CustomResponseException(status_code=403, message="admin required"))) as guard, patch.object(service, "get_admin_ai_models", new=AsyncMock()) as read, patch.object(service, "validate_admin_ai_model", new=AsyncMock()) as validate, patch.object(service, "put_admin_ai_model", new=AsyncMock()) as write:
                with pytest.raises(CustomResponseException) as error: await action()
                assert error.value.status_code == 403
                guard.assert_awaited_once_with(kc_user_id="non-admin", db=db, role="admin")
                read.assert_not_awaited(); validate.assert_not_awaited(); write.assert_not_awaited()
    asyncio.run(run())
