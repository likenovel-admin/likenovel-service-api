import unittest
from unittest.mock import AsyncMock, patch

from fastapi import status

from app.exceptions import CustomResponseException
from app.services.websochat import websochat_qa_executor


class WebsochatQaExecutorTimeoutTest(unittest.IsolatedAsyncioTestCase):
    async def test_next_episode_retry_uses_long_gemini_timeout(self):
        with patch.object(
            websochat_qa_executor,
            "call_websochat_gemini",
            new_callable=AsyncMock,
        ) as call_gemini:
            call_gemini.return_value = "다음 회차 초안"

            reply = await websochat_qa_executor._retry_websochat_next_episode_write_with_gemini(
                system_prompt="system",
                messages=[{"role": "user", "content": "다음회차 써줘"}],
            )

        self.assertEqual(reply, "다음 회차 초안")
        self.assertEqual(
            call_gemini.await_args.kwargs["timeout_seconds"],
            websochat_qa_executor.WEBSOCHAT_NEXT_EPISODE_WRITE_TIMEOUT_SECONDS,
        )

    async def test_next_episode_does_not_fallback_after_gemini_provider_error(self):
        provider_error = CustomResponseException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            code="AI_PROVIDER_TIMEOUT",
            message="생성 시간이 길어져 답변을 마치지 못했어요. 조금 뒤 다시 시도해 주세요.",
        )

        with (
            patch.object(
                websochat_qa_executor,
                "_generate_websochat_reply_with_gemini",
                new_callable=AsyncMock,
            ) as generate_with_gemini,
            patch.object(
                websochat_qa_executor,
                "_generate_websochat_reply_with_claude",
                new_callable=AsyncMock,
            ) as generate_with_claude,
        ):
            generate_with_gemini.side_effect = provider_error
            generate_with_claude.return_value = ("fallback reply", [])

            with self.assertRaises(CustomResponseException) as exc:
                await websochat_qa_executor.execute_websochat_qa(
                    product_row={"productId": 1, "latestEpisodeNo": 3},
                    user_prompt="다음회차 써줘",
                    qa_plan={
                        "preferred_model": "gemini",
                        "route_mode": "latest",
                        "intent": "next_episode_write",
                    },
                    evidence_bundle={"resolved_scope": {"read_episode_to": 3}, "scope_context": {}},
                    recent_messages=[],
                    qa_recent_notes=[],
                    qa_corrections=[],
                    current_qa_corrections=[],
                    db=object(),
                    hooks={},
                    max_tool_rounds=1,
                    gemini_context_episode_limit=3,
                    prefetch_context_chars=1000,
                    tools=[],
                )

        self.assertIs(exc.exception, provider_error)
        generate_with_claude.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
