import asyncio
import copy
import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from app.services.common import ai_model_gateway as gateway


MODEL = "deepseek/deepseek-v4.1-flash-1017"
OPENROUTER = "https://openrouter.ai/api/v1"
SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "result", "strict": True,
        "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}},
                   "required": ["ok"], "additionalProperties": False},
    },
}


@pytest.fixture
def setup_route(monkeypatch, tmp_path):
    binding = SimpleNamespace(feature_key="storyctx.signals", model_id=MODEL, billing_route="hive", revision=7)
    config_reads = []

    def resolve(feature_key, **kwargs):
        config_reads.append((feature_key, kwargs))
        return binding

    # Configuration loading is a separate component; HTTP/credit routing below
    # runs through the actual gateway and actual existing credit guard.
    monkeypatch.setitem(sys.modules, "app.services.common.ai_model_config", SimpleNamespace(get_model_binding=resolve))
    credentials = tmp_path / "accounts.json"
    credentials.write_text(json.dumps({
        "hive": [{"id": "hive-1", "api_key": "hive-secret-one"}, {"id": "hive-2", "api_key": "hive-secret-two"}],
        "river": [{"id": "river-1", "api_key": "river-secret-one"}, {"id": "river-2", "api_key": "river-secret-two"}],
    }))
    credentials.chmod(0o600)
    monkeypatch.setenv("AI_PROVIDER_ACCOUNTS_FILE", str(credentials))
    monkeypatch.setenv("OPENROUTER_BACKGROUND_CREDIT_LOCK_PATH", str(tmp_path / "credit.lock"))
    return binding, config_reads, credentials


def request_kwargs():
    return {
        "feature_key": "storyctx.signals", "base_url": OPENROUTER,
        "api_key": "openrouter-secret", "headers": {
            "Authorization": "Bearer old-openrouter-secret", "Content-Type": "application/json",
            "X-Title": "test", "Cookie": "private-cookie", "X-Api-Key": "private-header-key",
        },
        "json": {"model": "old-model", "messages": [{"role": "user", "content": "Return JSON."}],
                 "response_format": copy.deepcopy(SCHEMA), "reasoning": {"effort": "none", "exclude": True},
                 "max_tokens": 64, "provider": {"only": ["some-openrouter-provider"]}},
    }


def success(request):
    return httpx.Response(200, request=request, json={
        "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
    })


@pytest.mark.parametrize("provider,native", [
    ("hive", "deepseek-ai/deepseek-v4.1-flash-1017"),
    ("river", "deepseek-ai/DeepSeek-V4.1-Flash-1017"),
])
def test_prepaid_route_preserves_json_and_does_not_check_openrouter_credit(setup_route, provider, native):
    binding, reads, _ = setup_route
    binding.billing_route = provider
    requests = []

    def handler(request):
        requests.append(request)
        return success(request)

    kwargs = request_kwargs()
    original = copy.deepcopy(kwargs["json"])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = gateway.post_model_chat_completion(client, **kwargs)
    assert len(requests) == 1
    sent = json.loads(requests[0].content)
    assert sent["model"] == native
    assert sent["response_format"] == SCHEMA
    assert sent["reasoning_effort"] == "none"
    assert "provider" not in sent and "reasoning" not in sent
    assert sent.get("max_completion_tokens" if provider == "hive" else "max_tokens") == 64
    assert requests[0].headers["Authorization"] == f"Bearer {provider}-secret-one"
    assert "cookie" not in requests[0].headers and "x-api-key" not in requests[0].headers
    assert kwargs["json"] == original
    assert len(reads) == 1
    assert response.extensions["ai_route"] == {
        "provider": provider, "account_alias": f"{provider}-1", "requested_model": MODEL,
        "resolved_model": native, "config_revision": 7,
    }
    assert "secret" not in repr(response.extensions)


def test_exhausted_account_advances_once_then_openrouter_credit_guard(setup_route):
    _, reads, _ = setup_route
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "api-cdn.thehive.ai":
            return httpx.Response(402, request=request, json={"error": {"code": "insufficient_credits"}})
        if request.url.path.endswith("/credits"):
            return httpx.Response(200, request=request, json={"data": {"total_credits": 10, "total_usage": 1}})
        return success(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = gateway.post_model_chat_completion(client, **request_kwargs())
    assert [r.method for r in requests] == ["POST", "POST", "GET", "POST"]
    assert [r.headers["authorization"] for r in requests] == [
        "Bearer hive-secret-one", "Bearer hive-secret-two", "Bearer openrouter-secret", "Bearer openrouter-secret",
    ]
    final_payload = json.loads(requests[-1].content)
    assert final_payload["model"] == MODEL
    assert final_payload["response_format"] == SCHEMA
    assert final_payload["provider"] == {"only": ["some-openrouter-provider"], "require_parameters": True}
    assert response.extensions["ai_route"]["provider"] == "openrouter"
    assert len(reads) == 1


def test_confirmed_credit_error_code_can_advance_without_402(setup_route):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(403, request=request, json={"error": {"type": "insufficient_balance"}})
        return success(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = gateway.post_model_chat_completion(client, **request_kwargs())
    assert len(calls) == 2
    assert response.extensions["ai_route"]["account_alias"] == "hive-2"


@pytest.mark.parametrize("status,body", [
    (401, {"error": {"code": "invalid_api_key"}}),
    (429, {"error": {"code": "rate_limit_exceeded"}}),
    (500, {"error": {"code": "server_error"}}),
    (400, {"error": {"code": "unsupported_response_format"}}),
    (400, {"message": "insufficient credits"}),
    (405, {"error": {"code": "MODEL_PAUSED", "message": "VLM paused: check balance or terms"}}),
    (200, {"error": {"code": "insufficient_credits"}}),
])
def test_other_errors_do_not_retry(setup_route, status, body):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, request=request, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = gateway.post_model_chat_completion(client, **request_kwargs())
    assert len(calls) == 1
    assert response.status_code == status


@pytest.mark.parametrize("status", [200, 400, 500])
def test_malformed_json_never_triggers_a_fallback(setup_route, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, request=request, content=b'{"broken":')

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = gateway.post_model_chat_completion(client, **request_kwargs())
    assert response.content == b'{"broken":'
    assert len(calls) == 1


def test_timeout_is_sanitized_and_not_retried(setup_route):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("reflected hive-secret-one", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(gateway.AiModelGatewayTransportError) as exc:
            gateway.post_model_chat_completion(client, **request_kwargs())
    assert "secret" not in str(exc.value)
    assert exc.value.__suppress_context__
    assert len(calls) == 1


def test_reflected_credential_in_error_response_is_redacted_without_retry(setup_route):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, request=request, json={"error": {"message": "invalid hive-secret-one"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = gateway.post_model_chat_completion(client, **request_kwargs())
    assert response.status_code == 401 and len(calls) == 1
    assert response.json()["error"]["message"] == "invalid [redacted]"
    assert "hive-secret-one" not in response.text


def test_missing_pool_does_not_spend_openrouter_credit(setup_route, monkeypatch):
    monkeypatch.delenv("AI_PROVIDER_ACCOUNTS_FILE")
    calls = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: calls.append(request))) as client:
        with pytest.raises(gateway.AiModelGatewayConfigurationError):
            gateway.post_model_chat_completion(client, **request_kwargs())
    assert calls == []


def test_credential_pool_has_private_permissions_and_safe_aliases(setup_route):
    _, _, path = setup_route
    accounts = gateway.load_provider_accounts("hive")
    assert len(accounts) == 2 and "secret" not in repr(accounts)
    path.chmod(0o644)
    with pytest.raises(gateway.AiModelGatewayConfigurationError):
        gateway.load_provider_accounts("hive")
    path.chmod(0o600)
    path.write_text(json.dumps({"hive": [{"id": "my-secret-key", "api_key": "my-secret-key"}]}))
    with pytest.raises(gateway.AiModelGatewayConfigurationError) as exc:
        gateway.load_provider_accounts("hive")
    assert "my-secret-key" not in str(exc.value)


def test_unknown_model_mapping_and_reasoning_fail_before_submit(setup_route):
    binding, _, _ = setup_route
    with pytest.raises(gateway.AiModelGatewayConfigurationError, match="mapping"):
        gateway.provider_model_id("hive", "some/unknown-model")
    kwargs = request_kwargs()
    kwargs["json"]["reasoning"] = {"effort": "medium"}
    calls = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: calls.append(request))) as client:
        with pytest.raises(gateway.AiModelGatewayConfigurationError, match="reasoning"):
            gateway.post_model_chat_completion(client, **kwargs)
    assert calls == []


def test_async_account_fallback_uses_same_pinned_model(setup_route):
    binding, reads, _ = setup_route
    binding.billing_route = "river"
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            binding.model_id = "changed/during-call"
            binding.revision = 8
            return httpx.Response(402, request=request)
        return success(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await gateway.post_model_chat_completion_async(client, **request_kwargs())

    response = asyncio.run(run())
    assert len(calls) == 2 and len(reads) == 1
    assert response.extensions["ai_route"]["config_revision"] == 7
    assert response.extensions["ai_route"]["requested_model"] == MODEL
    assert json.loads(calls[1].content)["model"] == "deepseek-ai/DeepSeek-V4.1-Flash-1017"


def test_async_openrouter_reserve_failure_does_not_submit(setup_route):
    binding, _, _ = setup_route
    binding.billing_route = "openrouter"
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, request=request, json={"data": {"total_credits": 1, "total_usage": 1}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await gateway.post_model_chat_completion_async(client, **request_kwargs())

    from app.services.common.openrouter_background_credit_guard import OpenRouterBackgroundCreditReserveError
    with pytest.raises(OpenRouterBackgroundCreditReserveError):
        asyncio.run(run())
    assert len(calls) == 1 and calls[0].method == "GET"


def test_stream_credit_rejection_falls_back_before_yield(setup_route):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(402, request=request, json={"error": {"code": "insufficient_credit"}})
        return httpx.Response(200, request=request, content=b'data: {"ok":true}\n\ndata: [DONE]\n\n')

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async with gateway.stream_model_chat_completion_async(client, **request_kwargs()) as response:
                assert response.extensions["ai_route"]["account_alias"] == "hive-2"
                return [line async for line in response.aiter_lines()]

    lines = asyncio.run(run())
    assert "data: [DONE]" in lines
    assert len(calls) == 2
    assert all(json.loads(call.content)["stream"] for call in calls)


def test_partial_stream_timeout_never_switches_account(setup_route):
    calls = []
    received = []

    class PartialStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
            raise httpx.ReadTimeout("reflected hive-secret-one")

    def handler(request):
        calls.append(request)
        return httpx.Response(200, request=request, stream=PartialStream())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async with gateway.stream_model_chat_completion_async(client, **request_kwargs()) as response:
                async for line in response.aiter_lines():
                    received.append(line)

    with pytest.raises(gateway.AiModelGatewayTransportError) as exc:
        asyncio.run(run())
    assert received and "hello" in received[0]
    assert len(calls) == 1 and "secret" not in str(exc.value)


def test_foreground_openrouter_call_preserves_json_requirements_without_credit_lookup(setup_route):
    binding, _, _ = setup_route
    binding.billing_route = "openrouter"
    calls = []

    def handler(request):
        calls.append(request)
        return success(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async with gateway.stream_model_chat_completion_async(client, background=False, **request_kwargs()) as response:
                await response.aread()

    asyncio.run(run())
    assert len(calls) == 1 and calls[0].method == "POST"
    assert json.loads(calls[0].content)["provider"]["require_parameters"] is True


def test_real_configuration_contexts_remain_isolated_between_concurrent_jobs():
    from app.services.common.ai_model_config import AiModelBinding, use_ai_model_snapshot

    calls = []

    async def handler(request):
        await asyncio.sleep(0)
        calls.append(json.loads(request.content)["model"])
        return success(request)

    async def job(client, model, revision):
        binding = AiModelBinding("storyctx.signals", model, "openrouter", revision)
        with use_ai_model_snapshot({"storyctx.signals": binding}):
            await asyncio.sleep(0)
            response = await gateway.post_model_chat_completion_async(
                client, background=False, **request_kwargs(),
            )
            assert response.extensions["ai_route"]["requested_model"] == model
            assert response.extensions["ai_route"]["config_revision"] == revision

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await asyncio.gather(job(client, MODEL, 7), job(client, "another/validated-model", 8))

    asyncio.run(run())
    assert sorted(calls) == sorted([MODEL, "another/validated-model"])


def test_sync_stream_is_not_buffered_and_partial_failure_never_retries(setup_route):
    calls, consumed = [], []

    class PartialStream(httpx.SyncByteStream):
        def __iter__(self):
            consumed.append("first")
            yield b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
            consumed.append("timeout")
            raise httpx.ReadTimeout("reflected hive-secret-one")

    def handler(request):
        calls.append(request)
        return httpx.Response(200, request=request, stream=PartialStream())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(gateway.AiModelGatewayTransportError) as exc:
            with gateway.stream_model_chat_completion(client, **request_kwargs()) as response:
                assert consumed == []
                chunks = response.iter_raw()
                assert b"hello" in next(chunks)
                next(chunks)
    assert consumed == ["first", "timeout"] and len(calls) == 1
    assert "secret" not in str(exc.value)


def test_sync_stream_uses_openrouter_reserve_only_after_pool_exhaustion(setup_route):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "api-cdn.thehive.ai":
            return httpx.Response(402, request=request)
        if request.url.path.endswith("/credits"):
            return httpx.Response(200, request=request, json={"data": {"total_credits": 10, "total_usage": 1}})
        return httpx.Response(200, request=request, content=b'data: [DONE]\n\n')

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with gateway.stream_model_chat_completion(client, **request_kwargs()) as response:
            assert list(response.iter_lines()) == ["data: [DONE]", ""]
            assert response.extensions["ai_route"]["provider"] == "openrouter"
    assert [r.method for r in calls] == ["POST", "POST", "GET", "POST"]


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("route", ["hive", "openrouter"])
def test_claim_runs_once_immediately_before_first_submit(setup_route, async_mode, route):
    binding, _, _ = setup_route
    binding.billing_route = route
    events = []

    def claim():
        events.append("claim")

    def handler(request):
        if request.method == "GET":
            events.append("reserve")
            return httpx.Response(200, request=request, json={"data": {"total_credits": 10, "total_usage": 0}})
        assert events.count("claim") == 1
        events.append("submit")
        if request.url.host == "api-cdn.thehive.ai":
            return httpx.Response(402, request=request)
        return success(request)

    if async_mode:
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await gateway.post_model_chat_completion_async(client, before_submit=claim, **request_kwargs())
        asyncio.run(run())
    else:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            gateway.post_model_chat_completion(client, before_submit=claim, **request_kwargs())
    expected = ["claim", "submit", "submit", "reserve", "submit"] if route == "hive" else ["reserve", "claim", "submit"]
    assert events == expected


@pytest.mark.parametrize("async_mode", [False, True])
def test_openrouter_reserve_rejection_does_not_claim_or_submit(setup_route, async_mode):
    from app.services.common.openrouter_background_credit_guard import OpenRouterBackgroundCreditReserveError

    binding, _, _ = setup_route
    binding.billing_route = "openrouter"
    events = []

    def handler(request):
        events.append(request.method)
        return httpx.Response(200, request=request, json={"data": {"total_credits": 0, "total_usage": 0}})

    def claim():
        events.append("claim")

    with pytest.raises(OpenRouterBackgroundCreditReserveError):
        if async_mode:
            async def run():
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    await gateway.post_model_chat_completion_async(client, before_submit=claim, **request_kwargs())
            asyncio.run(run())
        else:
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                gateway.post_model_chat_completion(client, before_submit=claim, **request_kwargs())
    assert events == ["GET"]


@pytest.mark.parametrize("async_mode", [False, True])
def test_claim_rejection_prevents_all_inference_requests(setup_route, async_mode):
    calls = []

    def claim():
        raise RuntimeError("duplicate_claim")

    def handler(request):
        calls.append(request)
        return success(request)

    with pytest.raises(RuntimeError, match="duplicate_claim"):
        if async_mode:
            async def run():
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    await gateway.post_model_chat_completion_async(client, before_submit=claim, **request_kwargs())
            asyncio.run(run())
        else:
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                gateway.post_model_chat_completion(client, before_submit=claim, **request_kwargs())
    assert calls == []


def test_provider_capabilities_only_include_confirmed_hive_features():
    assert gateway.provider_capabilities("hive", MODEL) == frozenset({"text", "json_object", "json_schema"})
    assert gateway.provider_capabilities("river", MODEL) == frozenset({"text", "json_object", "json_schema", "tools"})
    assert gateway.provider_capabilities("hive", "unverified/model") == frozenset()


@pytest.mark.parametrize("async_mode", [False, True])
def test_claim_is_preserved_when_prepaid_is_exhausted_and_openrouter_reserve_rejects(setup_route, async_mode):
    from app.services.common.openrouter_background_credit_guard import OpenRouterBackgroundCreditReserveError

    events = []

    def claim():
        events.append("claim")

    def handler(request):
        if request.method == "GET":
            events.append("reserve")
            return httpx.Response(200, request=request, json={"data": {"total_credits": 0, "total_usage": 0}})
        events.append("credit_rejected")
        return httpx.Response(402, request=request)

    with pytest.raises(OpenRouterBackgroundCreditReserveError):
        if async_mode:
            async def run():
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    await gateway.post_model_chat_completion_async(client, before_submit=claim, **request_kwargs())
            asyncio.run(run())
        else:
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                gateway.post_model_chat_completion(client, before_submit=claim, **request_kwargs())
    assert events == ["claim", "credit_rejected", "credit_rejected", "reserve"]


@pytest.mark.parametrize("route", ["hive", "river", "openrouter"])
@pytest.mark.parametrize("effort", [None, "low", "high"])
def test_flash_reasoning_default_is_off_and_explicit_effort_is_preserved(setup_route, route, effort):
    binding, _, _ = setup_route
    binding.billing_route = route
    calls = []

    def handler(request):
        calls.append(request)
        return success(request)

    kwargs = request_kwargs()
    kwargs["json"].pop("reasoning")
    if effort is not None:
        kwargs["json"]["reasoning"] = {"effort": effort, "exclude": True}
    original = copy.deepcopy(kwargs["json"])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        gateway.post_model_chat_completion(client, background=False, **kwargs)
    assert len(calls) == 1
    body = json.loads(calls[0].content)
    if route == "openrouter":
        assert body["reasoning"] == {"effort": effort or "none", "exclude": True}
    else:
        assert body["reasoning_effort"] == (effort or "none")
        assert "reasoning" not in body
    assert body["response_format"] == SCHEMA
    assert kwargs["json"] == original


@pytest.mark.parametrize("route", ["hive", "river", "openrouter"])
def test_flash_explicit_native_reasoning_effort_is_not_overridden(setup_route, route):
    binding, _, _ = setup_route
    binding.billing_route = route
    calls = []

    def handler(request):
        calls.append(request)
        return success(request)

    kwargs = request_kwargs()
    kwargs["json"].pop("reasoning")
    kwargs["json"]["reasoning_effort"] = "low"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        gateway.post_model_chat_completion(client, background=False, **kwargs)
    body = json.loads(calls[0].content)
    assert body["reasoning_effort"] == "low"
    assert "reasoning" not in body


@pytest.mark.parametrize("model", ["google/gemini-3.1-flash-lite", "deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4-pro-0813"])
def test_other_models_do_not_receive_a_flash_1017_reasoning_default(setup_route, model):
    binding, _, _ = setup_route
    binding.billing_route = "openrouter"
    binding.model_id = model
    calls = []

    def handler(request):
        calls.append(request)
        return success(request)

    kwargs = request_kwargs()
    kwargs["json"].pop("reasoning")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        gateway.post_model_chat_completion(client, background=False, **kwargs)
    body = json.loads(calls[0].content)
    assert "reasoning" not in body and "reasoning_effort" not in body
