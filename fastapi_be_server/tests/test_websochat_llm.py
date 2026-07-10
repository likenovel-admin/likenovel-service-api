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

    def __init__(self, *, timeout: float):
        self.__class__.timeouts.append(timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *args, **kwargs):
        self.__class__.urls.append(url)
        return _FakeGeminiResponse()


class WebsochatLlmTimeoutTest(unittest.IsolatedAsyncioTestCase):
    async def test_call_websochat_gemini_uses_requested_timeout(self):
        _FakeGeminiAsyncClient.timeouts = []
        _FakeGeminiAsyncClient.urls = []

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
            )

        self.assertEqual(reply, "응답")
        self.assertEqual(_FakeGeminiAsyncClient.timeouts, [180.0])
        self.assertIn("/models/test-model:generateContent", _FakeGeminiAsyncClient.urls[0])

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


if __name__ == "__main__":
    unittest.main()
