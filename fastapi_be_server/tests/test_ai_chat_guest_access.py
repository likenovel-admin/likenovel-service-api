import unittest
from unittest.mock import AsyncMock, patch

from fastapi import status
from fastapi.security import HTTPAuthorizationCredentials

from app.exceptions import CustomResponseException
from app.routers.ai import ai_command
from app.schemas.ai_recommendation import PostAiChatReqBody
from app.services.ai import ai_chat_service
from app.utils import auth as auth_utils


class _FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _FakeMappings(self._rows)


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

    async def test_handle_chat_attaches_focus_product_card_on_no_match(self):
        focus_product = {
            "productId": 2020,
            "title": "이종족 일꾼 테이밍",
        }
        empty_taste_match = {"protagonist": 0, "mood": 0, "pacing": 0}

        with (
            patch.object(
                ai_chat_service,
                "_build_page_context",
                new_callable=AsyncMock,
            ) as build_page_context,
            patch.object(
                ai_chat_service,
                "_build_product_and_taste",
                new_callable=AsyncMock,
            ) as build_product_and_taste,
            patch.object(
                ai_chat_service,
                "_call_claude_messages",
                new_callable=AsyncMock,
            ) as call_claude_messages,
        ):
            build_page_context.return_value = {
                "page_type": "product",
                "pathname": "/product/free/normal",
                "current_product_id": 2020,
                "current_episode_id": None,
                "current_product_title": "이종족 일꾼 테이밍",
                "focus_product_card": True,
            }
            build_product_and_taste.side_effect = [
                (None, empty_taste_match),
                (focus_product, empty_taste_match),
            ]
            call_claude_messages.return_value = {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "final-1",
                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                        "input": {
                            "mode": "no_match",
                            "product_id": None,
                            "reply": "현재 보고 계신 작품은 이종족 일꾼을 모아 성장하는 작품입니다.",
                        },
                    }
                ]
            }

            result = await ai_chat_service.handle_chat(
                kc_user_id=None,
                messages=[{"role": "user", "content": "조건에 맞는 작품 찾아줘"}],
                context={
                    "trigger": "manual",
                    "page_type": "product",
                    "pathname": "/product/free/normal",
                    "current_product_id": 2020,
                    "focus_product_card": True,
                },
                preset=None,
                exclude_ids=[],
                adult_yn="N",
                db=AsyncMock(),
            )

        self.assertEqual(result["product"], focus_product)
        self.assertEqual(
            build_product_and_taste.await_args_list[-1].kwargs["selected_product_id"],
            2020,
        )

    async def test_handle_chat_replaces_no_match_reply_when_focus_product_card_attached(self):
        with (
            patch.object(
                ai_chat_service,
                "_build_page_context",
                new_callable=AsyncMock,
            ) as build_page_context,
            patch.object(
                ai_chat_service,
                "_dispatch_tool",
                new_callable=AsyncMock,
            ) as dispatch_tool,
            patch.object(
                ai_chat_service,
                "_call_claude_messages",
                new_callable=AsyncMock,
            ) as call_claude_messages,
        ):
            build_page_context.return_value = {
                "page_type": "product",
                "pathname": "/product/free/normal",
                "current_product_id": 2020,
                "current_episode_id": None,
                "current_product_title": "잿빛 길을 걷다",
                "focus_product_card": True,
            }
            dispatch_tool.return_value = {
                "product_id": 2020,
                "title": "잿빛 길을 걷다",
                "author_name": "Avalanche",
                "episode_total": 333,
                "writing_count_per_week": 7.0,
                "status_code": "scheduled_serial",
                "synopsis_text": "멸망한 도시를 걷는 생존자들이 긴장감 있는 여정을 이어가는 포스트 아포칼립스 작품입니다.",
                "taste_tags": ["강한 주인공", "서사적", "긴장감"],
            }
            call_claude_messages.side_effect = [
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "final-1",
                            "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                            "input": {
                                "mode": "no_match",
                                "product_id": None,
                                "reply": "현재 확인한 정보는 '잿빛 길을 걷다' 작품 자체에 대한 것뿐이며, 유사 작품을 추천하기 위한 비교 데이터가 없습니다.",
                            },
                        }
                    ]
                },
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "detail-1",
                            "name": "get_product_info",
                            "input": {"product_id": 2020},
                        }
                    ]
                },
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "final-2",
                            "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                            "input": {
                                "mode": "no_match",
                                "product_id": 2020,
                                "reply": "'잿빛 길을 걷다'는 멸망한 도시를 걷는 생존자들의 포스트 아포칼립스 생존 서사입니다. 현재 조회 가능한 데이터 범위 내에서 유사한 다른 작품을 찾기 어려워 비교 후보를 제시하기 어렵습니다.",
                            },
                        }
                    ]
                },
            ]

            result = await ai_chat_service.handle_chat(
                kc_user_id=None,
                messages=[{"role": "user", "content": "잿빛 길을 걷다 이 작품 어떤 작품인지 알려줘"}],
                context={
                    "trigger": "manual",
                    "page_type": "product",
                    "pathname": "/product/free/normal",
                    "current_product_id": 2020,
                    "focus_product_card": True,
                },
                preset=None,
                exclude_ids=[],
                adult_yn="N",
                db=AsyncMock(),
            )

        self.assertEqual(result["product"]["productId"], 2020)
        self.assertEqual(dispatch_tool.await_args.kwargs["tool_name"], "get_product_info")
        self.assertEqual(
            dispatch_tool.await_args.kwargs["tool_input"]["product_id"],
            2020,
        )
        self.assertIn("잿빛 길을 걷다", result["reply"])
        self.assertIn("포스트 아포칼립스", result["reply"])
        self.assertEqual(call_claude_messages.await_count, 3)
        self.assertEqual(result["finalMode"], "weak_recommend")
        self.assertNotIn("비교 데이터", result["reply"])
        self.assertNotIn("유사한 다른 작품", result["reply"])
        self.assertNotIn("비교 후보", result["reply"])
        self.assertNotIn("추천하기 위한", result["reply"])

    async def test_get_product_info_tool_accepts_optional_public_episode_previews(self):
        db = AsyncMock()
        with patch.object(
            ai_chat_service,
            "get_product_info",
            new_callable=AsyncMock,
        ) as get_product_info:
            get_product_info.return_value = {"product_id": 2020, "episode_previews": []}

            result = await ai_chat_service._dispatch_tool(
                db=db,
                tool_name="get_product_info",
                tool_input={
                    "product_id": 2020,
                    "include_episode_previews": True,
                    "episode_numbers": [1, 2],
                },
                exclude_ids=[],
                adult_yn="N",
            )

        self.assertEqual(result["product_id"], 2020)
        get_product_info.assert_awaited_once_with(
            db,
            product_id=2020,
            adult_yn="N",
            include_episode_previews=True,
            episode_numbers=[1, 2],
        )

    async def test_public_episode_previews_strip_html_and_limit_requested_episodes(self):
        db = AsyncMock()
        db.execute.return_value = _FakeResult(
            [
                {
                    "episode_no": 1,
                    "episode_title": "1화",
                    "episode_content": "<p>첫 장면<br>테이밍을 시작한다.</p>",
                },
                {
                    "episode_no": 2,
                    "episode_title": "2화",
                    "episode_content": "<p>두 번째 장면&nbsp;기지를 만든다.</p>",
                },
            ]
        )

        previews = await ai_chat_service._get_public_episode_previews(
            db,
            product_id=2020,
            episode_numbers=[1, 2],
            adult_yn="N",
        )

        self.assertEqual(
            previews,
            [
                {"episode_no": 1, "title": "1화", "preview_text": "첫 장면 테이밍을 시작한다."},
                {"episode_no": 2, "title": "2화", "preview_text": "두 번째 장면 기지를 만든다."},
            ],
        )

    def test_current_product_episode_questions_are_guided_to_optional_previews(self):
        product_info_tool = next(
            tool for tool in ai_chat_service.DATA_AGENT_TOOLS if tool["name"] == "get_product_info"
        )
        self.assertIn("include_episode_previews", product_info_tool["input_schema"]["properties"])
        self.assertIn("episode_numbers", product_info_tool["input_schema"]["properties"])

        prompt = ai_chat_service._build_data_agent_system_prompt(
            adult_yn="N",
            preset=None,
            reader_context={
                "taste_summary": None,
                "top_factors": [],
                "recent_reads": [],
                "read_product_ids": [],
                "factor_scores": {},
            },
            session_state={"recommended_product_ids": [], "exclude_product_ids": []},
            page_context={
                "current_product_id": 2020,
                "current_product_title": "이종족 일꾼 테이밍",
                "pathname": "/product/free/normal",
                "focus_product_card": True,
            },
        )

        self.assertIn("include_episode_previews=true", prompt)
        self.assertIn("episode_numbers", prompt)

    async def test_handle_chat_reasks_current_product_episode_question_with_public_previews(self):
        empty_taste_match = {"protagonist": 0, "mood": 0, "pacing": 0}

        with (
            patch.object(
                ai_chat_service,
                "_build_page_context",
                new_callable=AsyncMock,
            ) as build_page_context,
            patch.object(
                ai_chat_service,
                "_dispatch_tool",
                new_callable=AsyncMock,
            ) as dispatch_tool,
            patch.object(
                ai_chat_service,
                "_build_product_and_taste",
                new_callable=AsyncMock,
            ) as build_product_and_taste,
            patch.object(
                ai_chat_service,
                "_call_claude_messages",
                new_callable=AsyncMock,
            ) as call_claude_messages,
        ):
            build_page_context.return_value = {
                "page_type": "product",
                "pathname": "/product/free/normal",
                "current_product_id": 2020,
                "current_episode_id": None,
                "current_product_title": "이종족 일꾼 테이밍",
                "focus_product_card": True,
            }
            call_claude_messages.side_effect = [
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "final-1",
                            "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                            "input": {
                                "mode": "no_match",
                                "product_id": None,
                                "reply": "1화, 2화 내용은 확인할 수 없습니다.",
                            },
                        }
                    ]
                },
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "detail-1",
                            "name": "get_product_info",
                            "input": {
                                "product_id": 2020,
                                "include_episode_previews": True,
                                "episode_numbers": [1, 2],
                            },
                        }
                    ]
                },
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "final-2",
                            "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                            "input": {
                                "mode": "weak_recommend",
                                "product_id": 2020,
                                "reply": "1화는 짐꾼 김만덕이 게이트에서 수집 활동을 하며 시작하고, 2화는 이종족 일꾼 운용으로 확장됩니다.",
                            },
                        }
                    ]
                },
            ]
            dispatch_tool.return_value = {
                "product_id": 2020,
                "episode_previews": [
                    {"episode_no": 1, "title": "1화", "preview_text": "김만덕이 게이트에서 수집한다."},
                    {"episode_no": 2, "title": "2화", "preview_text": "이종족 일꾼 운용이 시작된다."},
                ],
            }
            build_product_and_taste.return_value = (
                {"productId": 2020, "title": "이종족 일꾼 테이밍"},
                empty_taste_match,
            )

            result = await ai_chat_service.handle_chat(
                kc_user_id=None,
                messages=[{"role": "user", "content": "대충 1화랑 2화 내용뭔데"}],
                context={
                    "trigger": "manual",
                    "page_type": "product",
                    "pathname": "/product/free/normal",
                    "current_product_id": 2020,
                    "focus_product_card": True,
                },
                preset=None,
                exclude_ids=[],
                adult_yn="N",
                db=AsyncMock(),
            )

        self.assertEqual(result["product"]["productId"], 2020)
        self.assertIn("1화는", result["reply"])
        self.assertEqual(call_claude_messages.await_count, 3)
        self.assertIn("include_episode_previews=true", call_claude_messages.await_args_list[1].kwargs["messages"][-1]["content"])
        self.assertEqual(dispatch_tool.await_args.kwargs["tool_input"]["episode_numbers"], [1, 2])

    async def test_handle_chat_reasks_episode_question_from_previous_product_card(self):
        empty_taste_match = {
            "overallScore": 0,
            "matchedFactors": [],
            "reason": "",
            "insights": [],
        }

        with (
            patch.object(
                ai_chat_service,
                "_build_page_context",
                new_callable=AsyncMock,
            ) as build_page_context,
            patch.object(
                ai_chat_service,
                "_dispatch_tool",
                new_callable=AsyncMock,
            ) as dispatch_tool,
            patch.object(
                ai_chat_service,
                "_build_product_and_taste",
                new_callable=AsyncMock,
            ) as build_product_and_taste,
            patch.object(
                ai_chat_service,
                "_call_claude_messages",
                new_callable=AsyncMock,
            ) as call_claude_messages,
        ):
            build_page_context.return_value = {
                "page_type": "product",
                "pathname": "/product/free/normal",
                "current_product_id": None,
                "current_episode_id": None,
                "current_product_title": None,
                "focus_product_card": False,
            }
            call_claude_messages.side_effect = [
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "final-1",
                            "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                            "input": {
                                "mode": "no_match",
                                "product_id": None,
                                "reply": "1화, 2화 내용은 확인할 수 없습니다.",
                            },
                        }
                    ]
                },
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "detail-1",
                            "name": "get_product_info",
                            "input": {
                                "product_id": 2020,
                                "include_episode_previews": True,
                                "episode_numbers": [1, 2],
                            },
                        }
                    ]
                },
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "final-2",
                            "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                            "input": {
                                "mode": "weak_recommend",
                                "product_id": 2020,
                                "reply": "1화는 게이트 수집 장면으로 시작하고, 2화는 이종족 일꾼 운용으로 확장됩니다.",
                            },
                        }
                    ]
                },
            ]
            dispatch_tool.return_value = {
                "product_id": 2020,
                "episode_previews": [
                    {"episode_no": 1, "title": "1화", "preview_text": "김만덕이 게이트에서 수집한다."},
                    {"episode_no": 2, "title": "2화", "preview_text": "이종족 일꾼 운용이 시작된다."},
                ],
            }
            build_product_and_taste.return_value = (
                {"productId": 2020, "title": "이종족 일꾼 테이밍"},
                empty_taste_match,
            )

            result = await ai_chat_service.handle_chat(
                kc_user_id=None,
                messages=[
                    {
                        "role": "assistant",
                        "content": "현재 보고 계신 작품은 이종족 일꾼 테이밍입니다.",
                        "product_id": 2020,
                    },
                    {"role": "user", "content": "대충 1화랑 2화 내용뭔데"},
                ],
                context={
                    "trigger": "manual",
                    "page_type": "product",
                    "pathname": "/product/free/normal",
                },
                preset=None,
                exclude_ids=[],
                adult_yn="N",
                db=AsyncMock(),
            )

        self.assertEqual(result["product"]["productId"], 2020)
        self.assertIn("1화는", result["reply"])
        self.assertEqual(call_claude_messages.await_count, 3)
        self.assertIn("작품 ID 2020", call_claude_messages.await_args_list[1].kwargs["messages"][-1]["content"])
