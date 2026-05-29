import unittest
from unittest.mock import AsyncMock, patch

from fastapi import status
from fastapi.security import HTTPAuthorizationCredentials

from app.exceptions import CustomResponseException
from app.routers.ai import ai_command
from app.schemas.ai_recommendation import PostAiChatReqBody
from app.services.ai import ai_chat_service
from app.utils import auth as auth_utils


class AiChatGuestAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_optional_ai_chat_auth_allows_missing_credentials(self):
        self.assertTrue(hasattr(auth_utils, "chk_optional_cur_user_strict"))
        result = await auth_utils.chk_optional_cur_user_strict(credentials=None)

        self.assertEqual(result, {})

    async def test_optional_ai_chat_auth_rejects_invalid_credentials(self):
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="invalid-token",
        )

        self.assertTrue(hasattr(auth_utils, "chk_optional_cur_user_strict"))
        with self.assertRaises(CustomResponseException) as exc:
            await auth_utils.chk_optional_cur_user_strict(credentials=credentials)

        self.assertEqual(exc.exception.status_code, status.HTTP_401_UNAUTHORIZED)

    async def test_post_ai_chat_allows_guest_and_skips_history_save(self):
        req_body = PostAiChatReqBody(
            messages=[{"role": "user", "content": "요즘 뜨는 작품 추천해줘"}],
            context={"trigger": "manual", "page_type": "home", "pathname": "/"},
            exclude_product_ids=[],
            adult_yn="N",
        )

        with (
            patch.object(
                ai_command.ai_chat_service,
                "handle_chat",
                new_callable=AsyncMock,
            ) as handle_chat,
            patch.object(
                ai_command.ai_chat_service,
                "save_chat_messages",
                new_callable=AsyncMock,
            ) as save_chat_messages,
        ):
            handle_chat.return_value = {
                "reply": "추천 후보를 찾았습니다.",
                "product": None,
                "taste_match": {"protagonist": 0, "mood": 0, "pacing": 0},
                "tasteMatch": {"protagonist": 0, "mood": 0, "pacing": 0},
            }

            result = await ai_command.post_ai_chat(
                req_body=req_body,
                user={},
                db=AsyncMock(),
            )

        self.assertEqual(result["data"]["reply"], "추천 후보를 찾았습니다.")
        handle_chat.assert_awaited_once()
        self.assertIsNone(handle_chat.await_args.kwargs["kc_user_id"])
        save_chat_messages.assert_not_awaited()

    async def test_handle_chat_guest_does_not_resolve_user_profile(self):
        with (
            patch.object(
                ai_chat_service.recommendation_service,
                "_get_user_id_by_kc",
                new_callable=AsyncMock,
            ) as get_user_id_by_kc,
            patch.object(
                ai_chat_service,
                "_call_claude_messages",
                new_callable=AsyncMock,
            ) as call_claude_messages,
        ):
            get_user_id_by_kc.side_effect = AssertionError(
                "guest chat must not resolve a user profile"
            )
            call_claude_messages.return_value = {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "final-1",
                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                        "input": {
                            "mode": "no_match",
                            "product_id": None,
                            "reply": "조건을 조금 더 알려주시면 작품을 찾아볼게요.",
                        },
                    }
                ]
            }

            result = await ai_chat_service.handle_chat(
                kc_user_id=None,
                messages=[{"role": "user", "content": "요즘 뜨는 작품 추천해줘"}],
                context={"trigger": "manual", "page_type": "home", "pathname": "/"},
                preset=None,
                exclude_ids=[],
                adult_yn="N",
                db=AsyncMock(),
            )

        self.assertEqual(result["reply"], "조건을 조금 더 알려주시면 작품을 찾아볼게요.")
        get_user_id_by_kc.assert_not_awaited()
