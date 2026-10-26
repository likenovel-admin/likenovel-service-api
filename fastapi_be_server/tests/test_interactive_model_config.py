import asyncio
import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.exceptions import CustomResponseException
from app.services.ai import ai_chat_service, recommendation_service
from app.services.common.ai_model_config import AiModelBinding, use_ai_model_snapshot
from app.services.websochat import websochat_llm
from app.services.websochat.websochat_model_catalog import get_websochat_model_spec


FLASH = "deepseek/deepseek-v4.1-flash-1017"
_AsyncClient = httpx.AsyncClient


@contextmanager
def _transport(handler):
    transport = httpx.MockTransport(handler)
    with patch.object(httpx, "AsyncClient", side_effect=lambda **kwargs: _AsyncClient(transport=transport, **kwargs)):
        yield


def _binding(key, model=FLASH, route="openrouter", revision=3):
    return AiModelBinding(key, model, route, revision)


def test_catalog_keeps_billing_tier_and_pins_models_per_job():
    before = get_websochat_model_spec("balance")
    with use_ai_model_snapshot({"websochat.balance": _binding("websochat.balance", revision=1)}):
        old_job = get_websochat_model_spec("balance")
        with use_ai_model_snapshot({"websochat.balance": _binding("websochat.balance", model="other/model", revision=2)}):
            assert get_websochat_model_spec("balance").provider_model == "other/model"
        assert get_websochat_model_spec("balance").provider_model == FLASH
    assert get_websochat_model_spec("balance") == before
    assert old_job.cash_cost == before.cash_cost
    assert old_job.character_chat_daily_free_limit == before.character_chat_daily_free_limit


def test_librarian_tool_history_and_tool_choice_survive_openrouter_override():
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
            "content": None, "tool_calls": [{"id": "final-call", "type": "function", "function": {
                "name": "submit_final_recommendation", "arguments": '{"product_id":42,"reason":"추천"}',
            }}],
        }}]})

    history = [
        {"role": "user", "content": "추천해 주세요"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "lookup-1", "name": "lookup", "input": {"product_id": 42}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "lookup-1", "content": [{"type": "text", "text": '{"title":"작품"}'}]}]},
    ]
    with use_ai_model_snapshot({"ai_chat.tools": _binding("ai_chat.tools")}), _transport(respond), patch.object(ai_chat_service.settings, "OPENROUTER_API_KEY", "test-key"):
        result = asyncio.run(ai_chat_service._call_claude_messages(
            system_prompt="도구 결과를 근거로 추천", messages=history,
            tools=[{"name": "submit_final_recommendation", "description": "최종 추천", "input_schema": {"type": "object", "properties": {"product_id": {"type": "integer"}}}}],
            tool_choice={"type": "tool", "name": "submit_final_recommendation"},
        ))
    assert len(requests) == 1
    payload = requests[0]
    assert payload["model"] == FLASH
    assert payload["messages"][2]["tool_calls"][0]["id"] == "lookup-1"
    assert json.loads(payload["messages"][2]["tool_calls"][0]["function"]["arguments"]) == {"product_id": 42}
    assert payload["messages"][3] == {"role": "tool", "tool_call_id": "lookup-1", "content": '{"title":"작품"}'}
    assert payload["tool_choice"] == {"type": "function", "function": {"name": "submit_final_recommendation"}}
    assert payload["provider"]["require_parameters"] is True
    assert result["content"] == [{"type": "tool_use", "id": "final-call", "name": "submit_final_recommendation", "input": {"product_id": 42, "reason": "추천"}}]


@pytest.mark.parametrize("finish_reason,arguments", [("length", '{"product_id":42}'), ("tool_calls", '{"product_id":'), ("tool_calls", '[]')])
def test_librarian_rejects_incomplete_or_invalid_tool_json_without_retry(finish_reason, arguments):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"finish_reason": finish_reason, "message": {"tool_calls": [{"id": "call", "function": {"name": "lookup", "arguments": arguments}}]}}]})

    with use_ai_model_snapshot({"ai_chat.tools": _binding("ai_chat.tools")}), _transport(respond), patch.object(ai_chat_service.settings, "OPENROUTER_API_KEY", "test-key"):
        with pytest.raises(CustomResponseException):
            asyncio.run(ai_chat_service._call_claude_messages(system_prompt="JSON", messages=[]))
    assert len(calls) == 1


def test_native_anthropic_path_is_retained_for_unchanged_configuration():
    requests = []

    def respond(request):
        requests.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json={"content": [{"type": "text", "text": "native"}]})

    with use_ai_model_snapshot({"ai_chat.tools": _binding("ai_chat.tools", model="claude-test", route="anthropic")}), _transport(respond), patch.object(ai_chat_service.settings, "ANTHROPIC_API_KEY", "test-key"):
        result = asyncio.run(ai_chat_service._call_claude_messages(system_prompt="test", messages=[]))
    assert requests[0][0] == "https://api.anthropic.com/v1/messages"
    assert requests[0][1]["model"] == "claude-test"
    assert result["content"][0]["text"] == "native"


def test_librarian_tool_errors_remain_marked_as_errors():
    converted = ai_chat_service._anthropic_messages_to_chat_messages("system", [
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "failed-query", "is_error": True, "content": "query denied"}]},
    ])
    assert converted[1]["tool_call_id"] == "failed-query"
    assert json.loads(converted[1]["content"]) == {"is_error": True, "content": "query denied"}


@pytest.mark.parametrize("hive_status,actual_provider", [(200, "hive"), (402, "openrouter")])
def test_websochat_usage_records_actual_billing_route(tmp_path, hive_status, actual_provider):
    accounts = tmp_path / "accounts.json"
    accounts.write_text(json.dumps({"hive": [{"id": "hive-one", "api_key": "test-hive-key"}]}))
    accounts.chmod(0o600)

    def respond(request):
        payload = json.loads(request.content)
        if "thehive.ai" in request.url.host and hive_status == 402:
            return httpx.Response(402, json={"error": {"code": "insufficient_credits"}})
        return httpx.Response(200, json={"model": payload["model"], "choices": [{"finish_reason": "stop", "message": {"content": "완성된 답변"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

    with use_ai_model_snapshot({"websochat.speed": _binding("websochat.speed", route="hive")}), _transport(respond), patch.dict("os.environ", {"AI_PROVIDER_ACCOUNTS_FILE": str(accounts)}), patch.object(websochat_llm.settings, "OPENROUTER_API_KEY", "test-or-key"), patch.object(websochat_llm, "persist_ai_provider_usage_async", AsyncMock(return_value=True)) as persist:
        reply = asyncio.run(websochat_llm.call_websochat_model(system_prompt="답변", messages=[], stream=False))
    assert reply == "완성된 답변"
    record = persist.await_args.args[0]
    assert record.provider == actual_provider
    assert record.requested_model == FLASH
    assert record.input_tokens == 10


def test_structured_websochat_is_not_routed_to_plain_hive_choice():
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"model": FLASH, "choices": [{"finish_reason": "stop", "message": {"content": '{"intent":"factual"}'}}]})

    snapshot = {"websochat.speed": _binding("websochat.speed", route="hive"), "websochat.structured": _binding("websochat.structured")}
    with use_ai_model_snapshot(snapshot), _transport(respond), patch.object(websochat_llm.settings, "OPENROUTER_API_KEY", "test-key"), patch.object(websochat_llm, "_persist_websochat_attempt", AsyncMock()):
        reply = asyncio.run(websochat_llm.call_websochat_model(system_prompt="JSON", messages=[], usage_stage_key="intent_routing", stream=True))
    assert json.loads(reply) == {"intent": "factual"}
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["stream"] is False


@pytest.mark.parametrize("finish_reason,content", [("length", "{}"), ("stop", '{"broken":'), ("stop", "[]")])
def test_structured_websochat_rejects_incomplete_or_malformed_json(finish_reason, content):
    def respond(request):
        return httpx.Response(200, json={"choices": [{"finish_reason": finish_reason, "message": {"content": content}}]})

    snapshot = {"websochat.speed": _binding("websochat.speed"), "websochat.structured": _binding("websochat.structured")}
    with use_ai_model_snapshot(snapshot), _transport(respond), patch.object(websochat_llm.settings, "OPENROUTER_API_KEY", "test-key"), patch.object(websochat_llm, "_persist_websochat_attempt", AsyncMock()):
        with pytest.raises(CustomResponseException):
            asyncio.run(websochat_llm.call_websochat_model(system_prompt="JSON", messages=[], usage_stage_key="intent_routing", stream=False))


def test_websochat_stream_timeout_does_not_send_nonstream_retry():
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout("provider outcome unknown", request=request)

    with use_ai_model_snapshot({"websochat.speed": _binding("websochat.speed")}), _transport(respond), patch.object(websochat_llm.settings, "OPENROUTER_API_KEY", "test-key"), patch.object(websochat_llm, "_persist_websochat_attempt", AsyncMock()):
        with pytest.raises(CustomResponseException):
            asyncio.run(websochat_llm.call_websochat_model(system_prompt="대답", messages=[], stream=True))
    assert len(calls) == 1


def test_recommendation_json_and_plain_reason_use_separate_bindings():
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        content = '{"product_id":42}' if payload.get("response_format") else "이 작품을 추천합니다."
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]})

    snapshot = {"recommendation": _binding("recommendation", model="json/model"), "recommendation.answer": _binding("recommendation.answer", model="text/model")}
    with use_ai_model_snapshot(snapshot), _transport(respond), patch.object(recommendation_service.settings, "OPENROUTER_API_KEY", "test-key"):
        result = asyncio.run(recommendation_service._call_claude("JSON", "추천"))
        reason = asyncio.run(recommendation_service._call_claude("순수 텍스트", "추천", routing_feature_key="recommendation.answer"))
    assert json.loads(result) == {"product_id": 42}
    assert reason == "이 작품을 추천합니다."
    assert requests[0]["model"] == "json/model"
    assert requests[1]["model"] == "text/model"
    assert "response_format" not in requests[1]
