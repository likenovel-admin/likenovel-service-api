import unittest
from unittest.mock import AsyncMock, patch

from app.exceptions import CustomResponseException
from app.routers.websochat import websochat_command
from app.schemas.websochat import PostWebsochatMessageReqBody


class WebsochatCommandRouteTests(unittest.IsolatedAsyncioTestCase):
    def test_stream_error_payload_preserves_custom_safe_message(self):
        exc = CustomResponseException(
            status_code=502,
            code="AI_PROVIDER_LIMITED",
            message="AI 답변 생성이 잠시 지연되고 있어요. 잠시 후 다시 시도해 주세요.",
        )

        payload = websochat_command._build_websochat_stream_error_payload(exc)

        self.assertEqual(
            payload,
            {
                "detail": "AI 답변 생성이 잠시 지연되고 있어요. 잠시 후 다시 시도해 주세요.",
                "code": "AI_PROVIDER_LIMITED",
                "status": 502,
            },
        )

    def test_stream_error_payload_hides_unexpected_exception_detail(self):
        payload = websochat_command._build_websochat_stream_error_payload(
            RuntimeError("provider 402 quota exhausted: sk-secret")
        )

        self.assertEqual(
            payload,
            {
                "detail": "AI 답변을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.",
                "code": "WEBSOCHAT_STREAM_FAILED",
                "status": 502,
            },
        )
        self.assertNotIn("quota", payload["detail"])
        self.assertNotIn("sk-secret", payload["detail"])

    async def test_next_episode_route_forces_next_episode_action(self):
        req_body = PostWebsochatMessageReqBody(
            client_message_id="client-1",
            content="다음회차 써줘",
            starter_mode_key="qa",
            qa_action_key="predict",
        )
        db = object()

        with patch.object(
            websochat_command.websochat_service,
            "post_message",
            new_callable=AsyncMock,
        ) as post_message:
            post_message.return_value = {"data": {"sessionId": 123, "messages": []}}

            result = await websochat_command.post_websochat_next_episode_message(
                session_id=123,
                req_body=req_body,
                user={"sub": "kc-user-id"},
                db=db,
            )

        self.assertEqual(result, {"data": {"sessionId": 123, "messages": []}})
        called_kwargs = post_message.await_args.kwargs
        self.assertEqual(called_kwargs["session_id"], 123)
        self.assertEqual(called_kwargs["kc_user_id"], "kc-user-id")
        self.assertIs(called_kwargs["db"], db)
        self.assertEqual(called_kwargs["req_body"].starter_mode_key, "qa")
        self.assertEqual(called_kwargs["req_body"].qa_action_key, "next_episode_write")
        self.assertEqual(called_kwargs["req_body"].content, "다음회차 써줘")


if __name__ == "__main__":
    unittest.main()
