import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import status

from app.exceptions import CustomResponseException
from app.services.websochat import websochat_llm


class WebsochatLlmUnitTest(unittest.TestCase):
    def test_extract_websochat_text_sanitizes_visible_model_noise(self):
        response_json = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": "문장이다.다음 문장\u200b\n\n\"좋아.\"다시 움직인다.ⵈ"
                            }
                        ]
                    }
                }
            ]
        }

        text = websochat_llm.extract_websochat_gemini_text(response_json)

        self.assertEqual(text, "문장이다. 다음 문장\n\n\"좋아.\" 다시 움직인다.")
        self.assertNotIn("ⵈ", text)
        self.assertNotIn("\u200b", text)

    def test_provider_quota_error_uses_internal_code_without_raw_provider_message(self):
        with self.assertRaises(CustomResponseException) as exc:
            websochat_llm._raise_websochat_provider_error(
                429,
                '{"error":{"status":"RESOURCE_EXHAUSTED","message":"quota exceeded"}}',
                operation="generateContent",
            )

        self.assertEqual(exc.exception.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(exc.exception.code, "AI_PROVIDER_LIMITED")
        self.assertEqual(
            exc.exception.message,
            "지금은 AI 생성 요청이 많아 답변을 완성하지 못했어요. 잠시 후 다시 시도해 주세요.",
        )
        self.assertNotIn("quota", str(exc.exception).lower())

    def test_provider_auth_error_uses_internal_code_without_status_code_in_message(self):
        with self.assertRaises(CustomResponseException) as exc:
            websochat_llm._raise_websochat_provider_error(
                403,
                '{"error":{"message":"API key invalid"}}',
                operation="generateContent",
            )

        self.assertEqual(exc.exception.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(exc.exception.code, "AI_PROVIDER_AUTH_FAILED")
        self.assertEqual(
            exc.exception.message,
            "AI 생성 설정을 확인하는 중이에요. 잠시 후 다시 시도해 주세요.",
        )
        self.assertNotIn("403", str(exc.exception))


class _FakeGeminiResponse:
    status_code = 200
    text = ""

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": "응답"}]}}]}


class _FakeGeminiAsyncClient:
    timeouts: list[float] = []
    urls: list[str] = []
    payloads: list[dict] = []

    def __init__(self, *, timeout: float):
        self.__class__.timeouts.append(timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *args, **kwargs):
        self.__class__.urls.append(url)
        self.__class__.payloads.append(kwargs["json"])
        return _FakeGeminiResponse()


class WebsochatLlmTimeoutTest(unittest.IsolatedAsyncioTestCase):
    async def test_call_websochat_gemini_uses_requested_timeout(self):
        _FakeGeminiAsyncClient.timeouts = []
        _FakeGeminiAsyncClient.urls = []
        _FakeGeminiAsyncClient.payloads = []

        with (
            patch.object(websochat_llm.settings, "GEMINI_API_KEY", "test-key"),
            patch.object(websochat_llm.settings, "WEBSOCHAT_GEMINI_MODEL", "test-model"),
            patch.object(websochat_llm, "is_websochat_stream_enabled", return_value=False),
            patch.object(websochat_llm.httpx, "AsyncClient", _FakeGeminiAsyncClient),
        ):
            reply = await websochat_llm.call_websochat_gemini(
                system_prompt="system",
                messages=[{"role": "user", "parts": [{"text": "질문"}]}],
                timeout_seconds=180.0,
                thinking_level="medium",
            )

        self.assertEqual(reply, "응답")
        self.assertEqual(_FakeGeminiAsyncClient.timeouts, [180.0])
        self.assertIn("/models/test-model:generateContent", _FakeGeminiAsyncClient.urls[0])
        self.assertEqual(
            _FakeGeminiAsyncClient.payloads[0]["generationConfig"]["thinkingConfig"],
            {"thinkingLevel": "medium"},
        )

    async def test_call_websochat_gemini_can_disable_inherited_stream(self):
        _FakeGeminiAsyncClient.urls = []

        with (
            patch.object(websochat_llm.settings, "GEMINI_API_KEY", "test-key"),
            patch.object(websochat_llm.settings, "WEBSOCHAT_GEMINI_MODEL", "default-model"),
            patch.object(websochat_llm, "is_websochat_stream_enabled", return_value=True),
            patch.object(
                websochat_llm,
                "_call_websochat_gemini_stream",
                new_callable=AsyncMock,
            ) as call_stream,
            patch.object(websochat_llm.httpx, "AsyncClient", _FakeGeminiAsyncClient),
        ):
            reply = await websochat_llm.call_websochat_gemini(
                system_prompt="system",
                messages=[{"role": "user", "parts": [{"text": "질문"}]}],
                stream=False,
            )

        self.assertEqual(reply, "응답")
        call_stream.assert_not_awaited()
        self.assertIn("/models/default-model:generateContent", _FakeGeminiAsyncClient.urls[0])


class _FakeOpenRouterResponse:
    def __init__(self, *, status_code=200, payload=None, lines=None):
        self.status_code = status_code
        self._payload = payload or {}
        self._lines = list(lines or [])
        self.text = json.dumps(self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aread(self):
        return self.text.encode()

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    def json(self):
        return self._payload


class _FakeOpenRouterAsyncClient:
    stream_response = _FakeOpenRouterResponse()
    post_response = _FakeOpenRouterResponse()
    calls: list[dict] = []

    def __init__(self, *, timeout: float):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, **kwargs):
        self.__class__.calls.append(
            {"kind": "stream", "method": method, "url": url, **kwargs}
        )
        return self.__class__.stream_response

    async def post(self, url, **kwargs):
        self.__class__.calls.append({"kind": "post", "url": url, **kwargs})
        return self.__class__.post_response


class WebsochatOpenRouterTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _FakeOpenRouterAsyncClient.calls = []
        _FakeOpenRouterAsyncClient.stream_response = _FakeOpenRouterResponse()
        _FakeOpenRouterAsyncClient.post_response = _FakeOpenRouterResponse()

    async def test_openrouter_dispatches_paid_model_without_reasoning_payload(self):
        _FakeOpenRouterAsyncClient.post_response = _FakeOpenRouterResponse(
            payload={
                "choices": [{"message": {"content": "밸런스 응답"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "total_tokens": 14,
                },
            }
        )
        with (
            patch.object(websochat_llm.settings, "OPENROUTER_API_KEY", "or-key"),
            patch.object(
                websochat_llm.settings,
                "OPENROUTER_BASE_URL",
                "https://openrouter.test/api/v1",
            ),
            patch.object(websochat_llm.httpx, "AsyncClient", _FakeOpenRouterAsyncClient),
        ):
            reply = await websochat_llm.call_websochat_openrouter(
                model="google/gemma-4-31b-it",
                system_prompt="system",
                messages=[
                    {"role": "user", "content": "질문"},
                    {"role": "assistant", "content": "이전 답"},
                ],
                stream=False,
            )

        self.assertEqual(reply, "밸런스 응답")
        call = _FakeOpenRouterAsyncClient.calls[0]
        self.assertEqual(call["url"], "https://openrouter.test/api/v1/chat/completions")
        self.assertEqual(call["headers"]["X-Title"], "LikeNovel Websochat")
        self.assertEqual(call["json"]["model"], "google/gemma-4-31b-it")
        self.assertNotIn("reasoning", call["json"])
        self.assertNotIn("thinking", call["json"])
        self.assertEqual(
            call["json"]["messages"],
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "질문"},
                {"role": "assistant", "content": "이전 답"},
            ],
        )

    async def test_usage_persistence_failure_does_not_fail_provider_reply(self):
        _FakeOpenRouterAsyncClient.post_response = _FakeOpenRouterResponse(
            payload={
                "choices": [{"message": {"content": "정상 응답"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.001},
            }
        )
        with (
            patch.object(websochat_llm.settings, "OPENROUTER_API_KEY", "or-key"),
            patch.object(websochat_llm.httpx, "AsyncClient", _FakeOpenRouterAsyncClient),
            patch.object(
                websochat_llm,
                "persist_ai_provider_usage_async",
                new_callable=AsyncMock,
                side_effect=RuntimeError("telemetry unavailable"),
            ),
        ):
            reply = await websochat_llm.call_websochat_openrouter(
                model="google/gemma-4-31b-it",
                system_prompt="system",
                messages=[{"role": "user", "content": "질문"}],
                stream=False,
                usage_operation=websochat_llm.AiProviderUsageOperation(
                    feature_key="websochat",
                    stage_key="qa_reply",
                ),
            )

        self.assertEqual(reply, "정상 응답")

    async def test_caller_validation_failure_is_recorded_without_changing_reply(self):
        _FakeOpenRouterAsyncClient.post_response = _FakeOpenRouterResponse(
            payload={
                "choices": [{"message": {"content": "형식 불일치 응답"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.001},
            }
        )
        with (
            patch.object(websochat_llm.settings, "OPENROUTER_API_KEY", "or-key"),
            patch.object(websochat_llm.httpx, "AsyncClient", _FakeOpenRouterAsyncClient),
            patch.object(
                websochat_llm,
                "persist_ai_provider_usage_async",
                new_callable=AsyncMock,
                return_value=True,
            ) as persist_usage,
        ):
            reply = await websochat_llm.call_websochat_openrouter(
                model="google/gemma-4-31b-it",
                system_prompt="system",
                messages=[{"role": "user", "content": "질문"}],
                stream=False,
                usage_operation=websochat_llm.AiProviderUsageOperation(
                    feature_key="websochat",
                    stage_key="character_chat_choices",
                ),
                usage_result_validator=lambda _value: False,
            )

        self.assertEqual(reply, "형식 불일치 응답")
        self.assertEqual(
            persist_usage.await_args.args[0].attempt_status,
            "validation_error",
        )

    async def test_openrouter_stream_parses_delta_and_done(self):
        _FakeOpenRouterAsyncClient.stream_response = _FakeOpenRouterResponse(
            lines=[
                'data: {"choices":[{"delta":{"content":"안녕"}}]}',
                'data: {"choices":[{"delta":{"content":" 하세요"}}]}',
                'data: {"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":2,"total_tokens":4}}',
                "data: [DONE]",
            ]
        )
        with (
            patch.object(websochat_llm.settings, "OPENROUTER_API_KEY", "or-key"),
            patch.object(websochat_llm.httpx, "AsyncClient", _FakeOpenRouterAsyncClient),
        ):
            reply = await websochat_llm.call_websochat_openrouter(
                model="google/gemma-4-31b-it",
                system_prompt="system",
                messages=[{"role": "user", "content": "질문"}],
                stream=True,
            )

        self.assertEqual(reply, "안녕 하세요")
        self.assertEqual(
            _FakeOpenRouterAsyncClient.calls[0]["json"]["stream_options"],
            {"include_usage": True},
        )

    async def test_openrouter_partial_stream_error_does_not_retry(self):
        _FakeOpenRouterAsyncClient.stream_response = _FakeOpenRouterResponse(
            lines=[
                'data: {"choices":[{"delta":{"content":"일부"}}]}',
                'data: {"error":{"code":429,"message":"rate limited"}}',
            ]
        )
        with (
            patch.object(websochat_llm.settings, "OPENROUTER_API_KEY", "or-key"),
            patch.object(websochat_llm.httpx, "AsyncClient", _FakeOpenRouterAsyncClient),
        ):
            with self.assertRaises(CustomResponseException) as exc:
                await websochat_llm.call_websochat_openrouter(
                    model="google/gemma-4-31b-it",
                    system_prompt="system",
                    messages=[{"role": "user", "content": "질문"}],
                    stream=True,
                )

        self.assertEqual(exc.exception.code, "AI_PROVIDER_LIMITED")
        self.assertEqual(
            [call["kind"] for call in _FakeOpenRouterAsyncClient.calls],
            ["stream"],
        )

    async def test_openrouter_empty_stream_retries_same_provider_nonstream(self):
        _FakeOpenRouterAsyncClient.stream_response = _FakeOpenRouterResponse(
            lines=["data: [DONE]"]
        )
        _FakeOpenRouterAsyncClient.post_response = _FakeOpenRouterResponse(
            payload={"choices": [{"message": {"content": "재시도 응답"}}]}
        )
        with (
            patch.object(websochat_llm.settings, "OPENROUTER_API_KEY", "or-key"),
            patch.object(websochat_llm.httpx, "AsyncClient", _FakeOpenRouterAsyncClient),
            patch.object(
                websochat_llm,
                "persist_ai_provider_usage_async",
                new_callable=AsyncMock,
                return_value=True,
            ) as persist_usage,
        ):
            reply = await websochat_llm.call_websochat_openrouter(
                model="google/gemma-4-31b-it",
                system_prompt="system",
                messages=[{"role": "user", "content": "질문"}],
                stream=True,
                usage_operation=websochat_llm.AiProviderUsageOperation(
                    feature_key="websochat",
                    stage_key="qa_reply",
                    product_id=123,
                ),
            )

        self.assertEqual(reply, "재시도 응답")
        self.assertEqual(
            [call["kind"] for call in _FakeOpenRouterAsyncClient.calls],
            ["stream", "post"],
        )
        records = [call.args[0] for call in persist_usage.await_args_list]
        self.assertEqual([record.attempt_no for record in records], [1, 2])
        self.assertEqual(
            [record.attempt_status for record in records],
            ["empty_response", "success"],
        )
        self.assertEqual(records[0].operation_id, records[1].operation_id)

    async def test_openrouter_local_config_rejection_creates_no_physical_call_row(self):
        with (
            patch.object(websochat_llm.settings, "OPENROUTER_API_KEY", ""),
            patch.object(
                websochat_llm,
                "persist_ai_provider_usage_async",
                new_callable=AsyncMock,
            ) as persist_usage,
        ):
            with self.assertRaises(CustomResponseException):
                await websochat_llm.call_websochat_openrouter(
                    model="google/gemma-4-31b-it",
                    system_prompt="system",
                    messages=[{"role": "user", "content": "질문"}],
                    stream=False,
                    usage_operation=websochat_llm.AiProviderUsageOperation(
                        feature_key="websochat",
                        stage_key="qa_reply",
                    ),
                )

        persist_usage.assert_not_awaited()

    async def test_openrouter_without_key_does_not_fallback_to_gemini(self):
        with (
            patch.object(websochat_llm.settings, "OPENROUTER_API_KEY", ""),
            patch.object(
                websochat_llm,
                "call_websochat_gemini",
                new_callable=AsyncMock,
            ) as gemini,
        ):
            with self.assertRaises(CustomResponseException) as exc:
                await websochat_llm.call_websochat_openrouter(
                    model="google/gemma-4-31b-it",
                    system_prompt="system",
                    messages=[{"role": "user", "content": "질문"}],
                    stream=False,
                )

        self.assertEqual(exc.exception.code, "AI_PROVIDER_NOT_CONFIGURED")
        gemini.assert_not_awaited()

    async def test_speed_balance_and_deep_use_gemini_catalog_thinking(self):
        with (
            patch.object(
                websochat_llm,
                "call_websochat_gemini",
                new_callable=AsyncMock,
                return_value="응답",
            ) as gemini,
            patch.object(
                websochat_llm,
                "call_websochat_openrouter",
                new_callable=AsyncMock,
            ) as openrouter,
        ):
            await websochat_llm.call_websochat_model(
                model_key="speed",
                system_prompt="system",
                messages=[{"role": "user", "content": "질문"}],
            )
            await websochat_llm.call_websochat_model(
                model_key="balance",
                system_prompt="system",
                messages=[{"role": "user", "content": "질문"}],
            )
            await websochat_llm.call_websochat_model(
                model_key="deep",
                system_prompt="system",
                messages=[{"role": "user", "content": "질문"}],
            )

        self.assertEqual(
            [call.kwargs["thinking_level"] for call in gemini.await_args_list],
            ["minimal", "medium", "high"],
        )
        openrouter.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
