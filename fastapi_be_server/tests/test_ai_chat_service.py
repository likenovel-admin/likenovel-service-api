import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import SQLAlchemyError

from app.exceptions import CustomResponseException
from app.services.ai import ai_chat_service


class AiChatServiceUnitTest(unittest.TestCase):
    def test_to_json_safe_converts_decimal(self):
        payload = {
            "score": Decimal("3.5"),
            "nested": [Decimal("1.25"), {"value": Decimal("2.75")}],
        }

        safe = ai_chat_service._to_json_safe(payload)

        self.assertEqual(safe["score"], 3.5)
        self.assertEqual(safe["nested"][0], 1.25)
        self.assertEqual(safe["nested"][1]["value"], 2.75)

    def test_normalize_adult_yn_accepts_y_n(self):
        self.assertEqual(ai_chat_service._normalize_adult_yn("Y"), "Y")
        self.assertEqual(ai_chat_service._normalize_adult_yn("n"), "N")
        self.assertEqual(ai_chat_service._normalize_adult_yn(None), "N")

    def test_normalize_adult_yn_rejects_invalid_value(self):
        with self.assertRaises(Exception) as exc:
            ai_chat_service._normalize_adult_yn("X")
        self.assertEqual(getattr(exc.exception, "status_code", None), 400)

    def test_parse_final_payload_from_json_text(self):
        reply, product_id, mode = ai_chat_service._parse_final_payload(
            '{"reply":"이 작품이 잘 맞아요.","mode":"recommend","product_id":123}'
        )
        self.assertEqual(reply, "이 작품이 잘 맞아요.")
        self.assertEqual(product_id, 123)
        self.assertEqual(mode, "recommend")

    def test_parse_final_payload_from_plain_text(self):
        reply, product_id, mode = ai_chat_service._parse_final_payload("그냥 텍스트 응답")
        self.assertEqual(reply, "그냥 텍스트 응답")
        self.assertIsNone(product_id)
        self.assertEqual(mode, "no_match")

    def test_normalize_messages_defaults_for_browsing_trigger(self):
        normalized = ai_chat_service._normalize_messages([], {"trigger": "browsing"})
        self.assertEqual(
            normalized,
            [{"role": "user", "content": "최근에 본 작품과 비슷한 작품 추천해줘"}],
        )

    def test_normalize_messages_drops_invalid_and_limits_12(self):
        source = [{"role": "system", "content": "x"}] + [
            {"role": "user", "content": f"q{i}"} for i in range(15)
        ]
        normalized = ai_chat_service._normalize_messages(source, {})
        self.assertEqual(len(normalized), 12)
        self.assertEqual(normalized[0]["content"], "q3")
        self.assertEqual(normalized[-1]["content"], "q14")

    def test_build_session_state_collects_recent_recommendations(self):
        session_state = ai_chat_service._build_session_state(
            [
                {"role": "assistant", "content": "첫 추천", "product_id": 111},
                {"role": "assistant", "content": "둘째 추천", "product_id": 222},
                {"role": "user", "content": "비슷한 거 보여줘"},
                {"role": "assistant", "content": "셋째 추천", "product_id": 333},
            ],
            {"trigger": "browsing"},
            [111, 222, 444],
        )
        self.assertEqual(session_state["trigger"], "browsing")
        self.assertEqual(session_state["last_user_query"], "비슷한 거 보여줘")
        self.assertEqual(session_state["recommended_product_ids"], [111, 222, 333])
        self.assertEqual(session_state["exclude_product_ids"], [111, 222, 444])

    def test_handle_chat_includes_current_product_context_in_data_agent_prompt(self):
        async def run():
            with (
                patch.object(
                    ai_chat_service.recommendation_service,
                    "_get_user_id_by_kc",
                    AsyncMock(return_value=1),
                ),
                patch.object(
                    ai_chat_service.recommendation_service,
                    "get_user_taste_profile",
                    AsyncMock(return_value=None),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_page_context",
                    AsyncMock(
                        return_value={
                            "page_type": "product",
                            "pathname": "/product/326",
                            "current_product_id": 326,
                            "current_product_title": "퍼펙트 메이지",
                        }
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_reader_context",
                    AsyncMock(return_value={"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": []}),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_claude_messages",
                    AsyncMock(
                        return_value={
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "tool-final-1",
                                    "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                    "input": {"reply": "비슷한 결로 다시 골랐어요.", "product_id": 521},
                                }
                            ]
                        }
                    ),
                ) as mocked_call_claude,
                patch.object(
                    ai_chat_service,
                    "_build_product_and_taste",
                    AsyncMock(
                        return_value=(
                            {
                                "productId": 521,
                                "title": "먼치킨인데 왜 아카데미에 가야하냐고",
                                "coverUrl": None,
                                "authorNickname": "작가A",
                                "episodeCount": 123,
                                "matchReason": "",
                                "tasteTags": [],
                                "serialCycle": None,
                                "priceType": "free",
                                "ongoingState": "serial",
                                "monopolyYn": "N",
                                "lastEpisodeDate": None,
                                "newReleaseYn": "N",
                                "cpContractYn": "N",
                                "waitingForFreeYn": "N",
                                "sixNinePathYn": "N",
                            },
                            {"protagonist": 0.5, "mood": 0.25, "pacing": 0.5},
                        )
                    ),
                ),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "이거랑 비슷한 작품 추천해줘"}],
                    context={
                        "trigger": "manual",
                        "current_product_id": 326,
                        "browsed_product_ids": [],
                    },
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

                system_prompt = mocked_call_claude.await_args.kwargs["system_prompt"]
                self.assertIn("현재 페이지 작품 ID: 326", system_prompt)
                self.assertIn("현재 보고 있던 작품: 퍼펙트 메이지", system_prompt)
                self.assertEqual(payload["product"]["productId"], 521)

        import asyncio

        asyncio.run(run())

    def test_extract_final_tool_input(self):
        tool_uses = [
            {"type": "tool_use", "name": "get_fact_catalog", "input": {}},
            {
                "type": "tool_use",
                "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                "input": {"reply": "추천", "product_id": 12},
            },
        ]
        result = ai_chat_service._extract_final_tool_input(tool_uses)
        self.assertEqual(result, {"reply": "추천", "product_id": 12})

    def test_build_fact_catalog_guides_episode_count_derivation(self):
        catalog = ai_chat_service._build_fact_catalog()
        guidance = catalog["rules"]["guidance"]
        self.assertTrue(
            any("tb_product_episode에서 COUNT(*)" in item for item in guidance)
        )
        self.assertTrue(
            any("premise, hook, episode_summary_text" in item for item in guidance)
        )
        self.assertTrue(
            any("evaluation_score 는 tb_cms_product_evaluation" in item for item in guidance)
        )
        self.assertTrue(
            any("tb_product에는 premise, hook, reading_rate, evaluation_score, episode_total 컬럼이 없다" in item for item in guidance)
        )
        self.assertTrue(
            any(table["table"] == "tb_cms_product_evaluation" for table in catalog["tables"])
        )

    def test_build_data_agent_system_prompt_forbids_generic_reply_and_requires_context_comparison(self):
        prompt = ai_chat_service._build_data_agent_system_prompt(
            adult_yn="N",
            preset=None,
            reader_context={
                "taste_summary": "성장형과 미스터리를 좋아함",
                "top_factors": [{"label": "성장형", "factor_type": "protagonist", "score": 6.0}],
                "recent_reads": [{"title": "퍼펙트 메이지", "read_episode_count": 12}],
                "read_product_ids": [326],
            },
            session_state={
                "recommended_product_ids": [326],
                "exclude_product_ids": [326, 482],
            },
            page_context={
                "current_product_id": 326,
                "current_product_title": "퍼펙트 메이지",
                "pathname": "/product/326",
            },
        )
        self.assertIn("빈 답변 금지", prompt)
        self.assertIn("공통점 2개와 차이점 1개", prompt)
        self.assertIn("get_fact_catalog에 나온 컬럼명만 사용", prompt)
        self.assertIn("tb_product_episode에서 COUNT(*)", prompt)
        self.assertIn("tb_product에는 premise, hook, reading_rate, evaluation_score, episode_total 컬럼이 없다", prompt)
        self.assertIn("submit_final_recommendation.mode 규칙", prompt)
        self.assertIn("조회 결과에 추천 가능한 후보가 1개라도 있으면 no_match보다 weak_recommend를 우선한다", prompt)
        self.assertIn("질문에 없는 숫자 임계치", prompt)
        self.assertIn("strict AND로 0건을 만들지 않는다", prompt)
        self.assertIn("2/3 이상 맞는 후보를 우선 비교해 weak_recommend", prompt)
        self.assertIn("DB 결과 내부의 상대 비교", prompt)

    def test_build_axis_taste_context_uses_factor_scores_and_7_axes(self):
        dna = {
            "protagonist_type_tags": ["성장형"],
            "protagonist_job_tags": ["작가"],
            "worldview_tags": ["현대"],
            "axis_style_tags": ["미스터리"],
            "overall_confidence": 0.95,
        }
        factor_scores = {
            "protagonist": {"성장형": 6.0},
            "job": {"작가": 6.0},
            "worldview": {"현대": 6.0},
            "style": {"미스터리": 6.0},
        }
        legacy, axis_scores, taste_summary = ai_chat_service._build_axis_taste_context(
            dna,
            profile={},
            factor_scores=factor_scores,
        )
        self.assertGreater(axis_scores["type"], 0)
        self.assertGreater(axis_scores["job"], 0)
        self.assertGreater(axis_scores["worldview"], 0)
        self.assertGreater(axis_scores["style"], 0)
        self.assertGreater(legacy["protagonist"], 0)
        self.assertGreater(legacy["mood"], 0)
        self.assertIn("성장형", taste_summary)
        self.assertIn("현대", taste_summary)

    def test_is_similar_request(self):
        self.assertTrue(ai_chat_service._is_similar_request("이거랑 비슷한 작품 추천해줘"))
        self.assertTrue(ai_chat_service._is_similar_request("유사작 알려줘"))
        self.assertFalse(ai_chat_service._is_similar_request("요즘 뜨는 작품 추천해줘"))

    def test_extract_anchor_product_id(self):
        messages = [
            {"role": "assistant", "content": "추천", "product_id": 123},
            {"role": "user", "content": "비슷한 거", "product_id": ""},
        ]
        self.assertEqual(ai_chat_service._extract_anchor_product_id(messages), 123)

    def test_handle_chat_freeform_query_uses_tool_loop_instead_of_preset_shortcut(self):
        async def run():
            with (
                patch.object(
                    ai_chat_service.recommendation_service,
                    "_get_user_id_by_kc",
                    AsyncMock(return_value=1),
                ),
                patch.object(
                    ai_chat_service.recommendation_service,
                    "get_user_taste_profile",
                    AsyncMock(return_value=None),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_reader_context",
                    AsyncMock(return_value={"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": []}),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_page_context",
                    AsyncMock(return_value={"page_type": "home", "pathname": "/"}),
                ),
                patch.object(
                    ai_chat_service.recommendation_service,
                    "ai_chat",
                    AsyncMock(),
                ) as mocked_recommend_chat,
                patch.object(
                    ai_chat_service,
                    "_call_claude_messages",
                    AsyncMock(
                        side_effect=[
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-catalog-1",
                                        "name": "get_fact_catalog",
                                        "input": {},
                                    }
                                ]
                            },
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-query-1",
                                        "name": "run_readonly_query",
                                        "input": {
                                            "sql": "SELECT product_id, title FROM tb_product WHERE status_code = 'end' LIMIT 5",
                                        },
                                    }
                                ]
                            },
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-final-1",
                                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                        "input": {
                                            "reply": "대체 추천작을 먼저 보세요.",
                                            "product_id": 888,
                                        },
                                    }
                                ]
                            },
                        ]
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_dispatch_tool",
                    AsyncMock(
                        side_effect=[
                            {"tables": ["tb_product", "tb_product_ai_metadata"]},
                            {
                                "sql": "SELECT product_id, title FROM tb_product WHERE status_code = 'end' LIMIT 5",
                                "row_count": 1,
                                "rows": [
                                    {
                                        "product_id": 888,
                                        "title": "대체 추천작",
                                        "author_name": "작가A",
                                        "episode_count": 120,
                                        "status_code": "end",
                                        "last_episode_date": datetime(2026, 3, 6, 12, 0, 0),
                                        "dna": {},
                                    }
                                ],
                            },
                        ]
                    ),
                ) as mocked_dispatch_tool,
                patch.object(
                    ai_chat_service,
                    "_build_product_and_taste",
                    AsyncMock(
                        return_value=(
                            {
                                "productId": 888,
                                "title": "대체 추천작",
                                "coverUrl": None,
                                "authorNickname": "작가A",
                                "episodeCount": 120,
                                "matchReason": "",
                                "tasteTags": [],
                                "serialCycle": None,
                                "priceType": "free",
                                "ongoingState": "end",
                                "monopolyYn": "N",
                                "lastEpisodeDate": None,
                                "newReleaseYn": "N",
                                "cpContractYn": "N",
                                "waitingForFreeYn": "N",
                                "sixNinePathYn": "N",
                            },
                            {"protagonist": 0.2, "mood": 0.1, "pacing": 0.0},
                        )
                    ),
                ),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "완결작 중 내 취향에 맞는 작품 추천해줘"}],
                    context={"page_type": "home"},
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

                mocked_recommend_chat.assert_not_awaited()
                self.assertEqual(mocked_dispatch_tool.await_count, 2)
                self.assertEqual(
                    mocked_dispatch_tool.await_args_list[0].kwargs["tool_name"],
                    "get_fact_catalog",
                )
                self.assertEqual(
                    mocked_dispatch_tool.await_args_list[1].kwargs["tool_name"],
                    "run_readonly_query",
                )
                self.assertEqual(
                    ai_chat_service._call_claude_messages.await_args_list[0].kwargs["tool_choice"],
                    {"type": "any"},
                )
                self.assertEqual(
                    ai_chat_service._call_claude_messages.await_args_list[1].kwargs["tool_choice"],
                    {"type": "any"},
                )
                self.assertEqual(payload["product"]["productId"], 888)
                self.assertEqual(payload["reply"], "대체 추천작을 먼저 보세요.")
                self.assertEqual(payload["product"]["matchReason"], "대체 추천작을 먼저 보세요.")

        import asyncio

        asyncio.run(run())

    def test_handle_chat_respects_null_product_id_in_final_tool(self):
        async def run():
            build_product_and_taste = AsyncMock(
                return_value=(
                    None,
                    {"protagonist": 0.2, "mood": 0.1, "pacing": 0.0},
                )
            )
            with (
                patch.object(
                    ai_chat_service.recommendation_service,
                    "_get_user_id_by_kc",
                    AsyncMock(return_value=1),
                ),
                patch.object(
                    ai_chat_service.recommendation_service,
                    "get_user_taste_profile",
                    AsyncMock(return_value=None),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_reader_context",
                    AsyncMock(return_value={"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": [], "factor_scores": {}}),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_page_context",
                    AsyncMock(return_value={"page_type": "home", "pathname": "/"}),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_claude_messages",
                    AsyncMock(
                        side_effect=[
                            {
                                "content": [
                                    {"type": "tool_use", "id": "tool-catalog-1", "name": "get_fact_catalog", "input": {}}
                                ]
                            },
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-query-1",
                                        "name": "run_readonly_query",
                                        "input": {"sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5"},
                                    }
                                ]
                            },
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-final-1",
                                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                        "input": {"reply": "후보를 찾았습니다.", "product_id": None},
                                    }
                                ]
                            },
                        ]
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_dispatch_tool",
                    AsyncMock(
                        side_effect=[
                            {"tables": ["tb_product", "tb_product_ai_metadata"]},
                            {
                                "sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5",
                                "row_count": 0,
                                "rows": [],
                            },
                        ]
                    ),
                ),
                patch.object(ai_chat_service, "_build_product_and_taste", build_product_and_taste),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "현대 미스터리 작품 추천해줘"}],
                    context={"page_type": "home"},
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

                self.assertIsNone(payload["product"])
                self.assertIsNone(build_product_and_taste.await_args.kwargs["selected_product_id"])
                self.assertEqual(payload["reply"], "후보를 찾았습니다.")

        import asyncio

        asyncio.run(run())

    def test_handle_chat_reasks_finalize_with_detail_when_query_candidates_exist(self):
        async def run():
            with (
                patch.object(
                    ai_chat_service.recommendation_service,
                    "_get_user_id_by_kc",
                    AsyncMock(return_value=1),
                ),
                patch.object(
                    ai_chat_service.recommendation_service,
                    "get_user_taste_profile",
                    AsyncMock(return_value=None),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_reader_context",
                    AsyncMock(return_value={"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": [], "factor_scores": {}}),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_page_context",
                    AsyncMock(return_value={"page_type": "home", "pathname": "/"}),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_claude_messages",
                    AsyncMock(
                        side_effect=[
                            {"content": [{"type": "tool_use", "id": "tool-query-1", "name": "run_readonly_query", "input": {"sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5"}}]},
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-final-1",
                                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                        "input": {"reply": "후보작을 추천합니다.", "product_id": None},
                                    }
                                ]
                            },
                            {"content": [{"type": "tool_use", "id": "tool-detail-1", "name": "get_product_info", "input": {"product_id": 777}}]},
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-final-2",
                                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                        "input": {"reply": "후보작을 추천합니다.", "product_id": 777},
                                    }
                                ]
                            },
                        ]
                    ),
                ) as mocked_call_claude,
                patch.object(
                    ai_chat_service,
                    "_dispatch_tool",
                    AsyncMock(
                        side_effect=[
                            {
                                "sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5",
                                "row_count": 1,
                                "rows": [{"product_id": 777, "title": "후보작"}],
                            },
                            {"product_id": 777, "title": "후보작", "status_code": "ongoing"},
                        ]
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_product_and_taste",
                    AsyncMock(
                        return_value=(
                            {"productId": 777, "title": "후보작"},
                            {"protagonist": 0.2, "mood": 0.1, "pacing": 0.0},
                        )
                    ),
                ),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "현대 미스터리 작품 추천해줘"}],
                    context={"page_type": "home"},
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

                self.assertEqual(payload["product"]["productId"], 777)
                self.assertEqual(payload["reply"], "후보작을 추천합니다.")
                self.assertEqual(mocked_call_claude.await_count, 4)
                self.assertEqual(mocked_call_claude.await_args_list[2].kwargs["tool_choice"], {"type": "any"})
                self.assertEqual(
                    sorted(tool["name"] for tool in mocked_call_claude.await_args_list[2].kwargs["tools"]),
                    ["get_product_info", ai_chat_service.FINAL_RESPONSE_TOOL_NAME],
                )
                self.assertIn(
                    "후보 작품 ID [777] 중 가장 가까운 작품을 확인하려면 get_product_info(product_id=...)를 먼저 호출한 뒤 recommend 또는 weak_recommend로 submit_final_recommendation을 제출하세요.",
                    mocked_call_claude.await_args_list[2].kwargs["messages"][-1]["content"],
                )

        import asyncio

        asyncio.run(run())

    def test_handle_chat_reasks_when_final_mode_requires_product_id(self):
        async def run():
            with (
                patch.object(
                    ai_chat_service.recommendation_service,
                    "_get_user_id_by_kc",
                    AsyncMock(return_value=1),
                ),
                patch.object(
                    ai_chat_service.recommendation_service,
                    "get_user_taste_profile",
                    AsyncMock(return_value=None),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_reader_context",
                    AsyncMock(return_value={"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": [], "factor_scores": {}}),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_page_context",
                    AsyncMock(return_value={"page_type": "home", "pathname": "/"}),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_claude_messages",
                    AsyncMock(
                        side_effect=[
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-final-1",
                                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                        "input": {"reply": "후보작을 추천합니다.", "mode": "recommend", "product_id": None},
                                    }
                                ]
                            },
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-final-2",
                                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                        "input": {"reply": "후보작을 추천합니다.", "mode": "weak_recommend", "product_id": 555},
                                    }
                                ]
                            },
                        ]
                    ),
                ) as mocked_call_claude,
                patch.object(
                    ai_chat_service,
                    "_build_product_and_taste",
                    AsyncMock(
                        return_value=(
                            {"productId": 555, "title": "후보작"},
                            {"protagonist": 0.1, "mood": 0.0, "pacing": 0.0},
                        )
                    ),
                ),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "현대 미스터리 작품 추천해줘"}],
                    context={"page_type": "home"},
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

                self.assertEqual(payload["product"]["productId"], 555)
                self.assertEqual(payload["finalMode"], "weak_recommend")
                self.assertEqual(mocked_call_claude.await_count, 2)
                self.assertEqual(
                    mocked_call_claude.await_args_list[1].kwargs["tool_choice"],
                    {"type": "any"},
                )
                self.assertEqual(
                    [tool["name"] for tool in mocked_call_claude.await_args_list[1].kwargs["tools"]],
                    [ai_chat_service.FINAL_RESPONSE_TOOL_NAME],
                )
                self.assertEqual(
                    mocked_call_claude.await_args_list[1].kwargs["messages"][-1]["content"],
                    "추가 조회는 허용되지 않습니다. submit_final_recommendation 계약이 잘못됐습니다. recommend/weak_recommend면 product_id를 반드시 넣고, no_match면 product_id를 null로 제출하세요. 지금까지 확보한 조회 결과만 근거로 반드시 submit_final_recommendation을 호출하세요.",
                )

        import asyncio

        asyncio.run(run())

    def test_handle_chat_reasks_finalize_when_product_id_missing_after_detail_lookup(self):
        async def run():
            with (
                patch.object(
                    ai_chat_service.recommendation_service,
                    "_get_user_id_by_kc",
                    AsyncMock(return_value=1),
                ),
                patch.object(
                    ai_chat_service.recommendation_service,
                    "get_user_taste_profile",
                    AsyncMock(return_value=None),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_reader_context",
                    AsyncMock(return_value={"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": [], "factor_scores": {}}),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_page_context",
                    AsyncMock(return_value={"page_type": "home", "pathname": "/"}),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_claude_messages",
                    AsyncMock(
                        side_effect=[
                            {"content": [{"type": "tool_use", "id": "tool-query-1", "name": "run_readonly_query", "input": {"sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5"}}]},
                            {"content": [{"type": "tool_use", "id": "tool-detail-1", "name": "get_product_info", "input": {"product_id": 321}}]},
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-final-1",
                                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                        "input": {"reply": "후보작을 추천합니다.", "product_id": None},
                                    }
                                ]
                            },
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-final-2",
                                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                        "input": {"reply": "후보작을 추천합니다.", "product_id": 321},
                                    }
                                ]
                            },
                        ]
                    ),
                ) as mocked_call_claude,
                patch.object(
                    ai_chat_service,
                    "_dispatch_tool",
                    AsyncMock(
                        side_effect=[
                            {
                                "sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5",
                                "row_count": 1,
                                "rows": [{"product_id": 321, "title": "후보작"}],
                            },
                            {"product_id": 321, "title": "후보작", "status_code": "end"},
                        ]
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_product_and_taste",
                    AsyncMock(
                        return_value=(
                            {"productId": 321, "title": "후보작"},
                            {"protagonist": 0.2, "mood": 0.1, "pacing": 0.0},
                        )
                    ),
                ),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "현대 미스터리 작품 추천해줘"}],
                    context={"page_type": "home"},
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

                self.assertEqual(payload["product"]["productId"], 321)
                self.assertEqual(payload["reply"], "후보작을 추천합니다.")
                self.assertEqual(mocked_call_claude.await_count, 4)
                self.assertEqual(
                    mocked_call_claude.await_args_list[-1].kwargs["tool_choice"],
                    {"type": "tool", "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME},
                )

        import asyncio

        asyncio.run(run())

    def test_handle_chat_converts_tool_query_error_into_tool_result(self):
        async def run():
            with (
                patch.object(
                    ai_chat_service.recommendation_service,
                    "_get_user_id_by_kc",
                    AsyncMock(return_value=1),
                ),
                patch.object(
                    ai_chat_service.recommendation_service,
                    "get_user_taste_profile",
                    AsyncMock(return_value=None),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_reader_context",
                    AsyncMock(return_value={"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": [], "factor_scores": {}}),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_page_context",
                    AsyncMock(return_value={"page_type": "home", "pathname": "/"}),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_claude_messages",
                    AsyncMock(
                        side_effect=[
                            {
                                "content": [
                                    {"type": "tool_use", "id": "tool-catalog-1", "name": "get_fact_catalog", "input": {}}
                                ]
                            },
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-query-1",
                                        "name": "run_readonly_query",
                                        "input": {"sql": "SELECT bad_column FROM tb_product WHERE ratings_code = 'all' LIMIT 5"},
                                    }
                                ]
                            },
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-final-1",
                                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                        "input": {"reply": "조건을 조금만 더 좁혀주시면 다시 찾아드릴게요.", "product_id": None},
                                    }
                                ]
                            },
                        ]
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_dispatch_tool",
                    AsyncMock(
                        side_effect=[
                            {"tables": ["tb_product", "tb_product_ai_metadata"]},
                            CustomResponseException(status_code=400, message="허용 스키마와 맞지 않습니다."),
                        ]
                    ),
                ),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "현대 미스터리 작품 추천해줘"}],
                    context={"page_type": "home"},
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

                self.assertIsNone(payload["product"])
                self.assertIn("조건을 조금만 더 좁혀주시면", payload["reply"])

        import asyncio

        asyncio.run(run())

    def test_handle_chat_allows_query_without_catalog(self):
        async def run():
            with (
                patch.object(
                    ai_chat_service.recommendation_service,
                    "_get_user_id_by_kc",
                    AsyncMock(return_value=1),
                ),
                patch.object(
                    ai_chat_service.recommendation_service,
                    "get_user_taste_profile",
                    AsyncMock(return_value=None),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_reader_context",
                    AsyncMock(return_value={"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": [], "factor_scores": {}}),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_page_context",
                    AsyncMock(return_value={"page_type": "home", "pathname": "/"}),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_claude_messages",
                    AsyncMock(
                        side_effect=[
                            {"content": [{"type": "tool_use", "id": "tool-query-1", "name": "run_readonly_query", "input": {"sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5"}}]},
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-final-1",
                                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                        "input": {"reply": "후보를 찾았습니다.", "product_id": 909},
                                    }
                                ]
                            },
                        ]
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_dispatch_tool",
                    AsyncMock(
                        side_effect=[
                            {"rows": [{"product_id": 909, "title": "루프 종결작"}]},
                        ]
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_product_and_taste",
                    AsyncMock(
                        return_value=(
                            {
                                "productId": 909,
                                "title": "루프 종결작",
                                "coverUrl": None,
                                "authorNickname": "작가C",
                                "episodeCount": 64,
                                "matchReason": "",
                                "tasteTags": [],
                                "serialCycle": None,
                                "priceType": "free",
                                "ongoingState": "serial",
                                "monopolyYn": "N",
                                "lastEpisodeDate": None,
                                "newReleaseYn": "N",
                                "cpContractYn": "N",
                                "waitingForFreeYn": "N",
                                "sixNinePathYn": "N",
                            },
                            {"protagonist": 0.3, "mood": 0.2, "pacing": 0.0},
                        )
                    ),
                ) as mocked_build_product_and_taste,
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "현대 미스터리 작품 추천해줘"}],
                    context={"page_type": "home"},
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

                self.assertEqual(payload["product"]["productId"], 909)
                self.assertEqual(mocked_build_product_and_taste.await_args.kwargs["selected_product_id"], 909)
                self.assertEqual(payload["reply"], "후보를 찾았습니다.")
                self.assertEqual(payload["product"]["matchReason"], "후보를 찾았습니다.")

        import asyncio

        asyncio.run(run())

    def test_handle_chat_forces_finalize_after_query_limit(self):
        async def run():
            build_product_and_taste = AsyncMock(
                return_value=(
                    {
                        "productId": 909,
                        "title": "루프 종결작",
                        "coverUrl": None,
                        "authorNickname": "작가C",
                        "episodeCount": 64,
                        "matchReason": "",
                        "tasteTags": [],
                        "serialCycle": None,
                        "priceType": "free",
                        "ongoingState": "serial",
                        "monopolyYn": "N",
                        "lastEpisodeDate": None,
                        "newReleaseYn": "N",
                        "cpContractYn": "N",
                        "waitingForFreeYn": "N",
                        "sixNinePathYn": "N",
                    },
                    {"protagonist": 0.3, "mood": 0.2, "pacing": 0.0},
                )
            )
            with (
                patch.object(
                    ai_chat_service.recommendation_service,
                    "_get_user_id_by_kc",
                    AsyncMock(return_value=1),
                ),
                patch.object(
                    ai_chat_service.recommendation_service,
                    "get_user_taste_profile",
                    AsyncMock(return_value=None),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_reader_context",
                    AsyncMock(return_value={"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": [], "factor_scores": {}}),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_page_context",
                    AsyncMock(return_value={"page_type": "home", "pathname": "/"}),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_claude_messages",
                    AsyncMock(
                        side_effect=[
                            {"content": [{"type": "tool_use", "id": "tool-query-1", "name": "run_readonly_query", "input": {"sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5"}}]},
                            {"content": [{"type": "tool_use", "id": "tool-query-2", "name": "run_readonly_query", "input": {"sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5"}}]},
                            {"content": [{"type": "tool_use", "id": "tool-query-3", "name": "run_readonly_query", "input": {"sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5"}}]},
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-final-1",
                                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                        "input": {"reply": "지금까지 조회 결과 기준으로는 루프 종결작이 가장 가깝습니다.", "product_id": 909},
                                    }
                                ]
                            },
                        ]
                    ),
                ) as mocked_call_claude,
                patch.object(
                    ai_chat_service,
                    "_dispatch_tool",
                    AsyncMock(
                        side_effect=[
                            {"rows": [{"product_id": 909, "title": "루프 종결작"}]},
                            {"rows": [{"product_id": 909, "title": "루프 종결작"}]},
                        ]
                    ),
                ) as mocked_dispatch_tool,
                patch.object(ai_chat_service, "_build_product_and_taste", build_product_and_taste),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "현대 미스터리 작품 추천해줘"}],
                    context={"page_type": "home"},
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

                self.assertEqual(mocked_dispatch_tool.await_count, 2)
                self.assertEqual(payload["product"]["productId"], 909)
                self.assertIn("루프 종결작", payload["reply"])
                self.assertEqual(
                    mocked_call_claude.await_args_list[-1].kwargs["tool_choice"],
                    {"type": "tool", "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME},
                )

        import asyncio

        asyncio.run(run())

    def test_handle_chat_reuses_prefetched_product_info_on_finalize(self):
        async def run():
            with (
                patch.object(
                    ai_chat_service.recommendation_service,
                    "_get_user_id_by_kc",
                    AsyncMock(return_value=1),
                ),
                patch.object(
                    ai_chat_service.recommendation_service,
                    "get_user_taste_profile",
                    AsyncMock(return_value=None),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_reader_context",
                    AsyncMock(return_value={"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": [], "factor_scores": {}}),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_page_context",
                    AsyncMock(return_value={"page_type": "home", "pathname": "/"}),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_claude_messages",
                    AsyncMock(
                        side_effect=[
                            {"content": [{"type": "tool_use", "id": "tool-query-1", "name": "run_readonly_query", "input": {"sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5"}}]},
                            {"content": [{"type": "tool_use", "id": "tool-detail-1", "name": "get_product_info", "input": {"product_id": 321}}]},
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-final-1",
                                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                        "input": {"reply": "이 작품을 추천합니다.", "product_id": 321},
                                    }
                                ]
                            },
                        ]
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_dispatch_tool",
                    AsyncMock(
                        side_effect=[
                            {"rows": [{"product_id": 321, "title": "후보작"}]},
                            {"product_id": 321, "title": "후보작", "status_code": "serial"},
                        ]
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_product_and_taste",
                    AsyncMock(return_value=(None, {"protagonist": 0.0, "mood": 0.0, "pacing": 0.0})),
                ) as mocked_build_product_and_taste,
            ):
                await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "현대 미스터리 작품 추천해줘"}],
                    context={"page_type": "home"},
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

                self.assertEqual(
                    mocked_build_product_and_taste.await_args.kwargs["prefetched_product_info"],
                    {"product_id": 321, "title": "후보작", "status_code": "serial"},
                )

        import asyncio

        asyncio.run(run())

    def test_sanitize_readonly_sql_allows_order_by_desc(self):
        sql = "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' ORDER BY product_id DESC LIMIT 10"
        normalized = ai_chat_service._sanitize_readonly_sql(sql, adult_yn="N")
        self.assertEqual(normalized, sql)

    def test_sanitize_readonly_sql_normalizes_nulls_last_for_mysql(self):
        sql = (
            "SELECT product_id, title FROM tb_product "
            "WHERE ratings_code = 'all' ORDER BY count_hit DESC NULLS LAST LIMIT 10"
        )
        normalized = ai_chat_service._sanitize_readonly_sql(sql, adult_yn="N")
        self.assertEqual(
            normalized,
            "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' ORDER BY count_hit DESC LIMIT 10",
        )

    def test_sanitize_readonly_sql_blocks_server_variables_and_file_functions(self):
        with self.assertRaises(CustomResponseException):
            ai_chat_service._sanitize_readonly_sql("SELECT @@version LIMIT 1", adult_yn="N")
        with self.assertRaises(CustomResponseException):
            ai_chat_service._sanitize_readonly_sql("SELECT LOAD_FILE('/etc/passwd') LIMIT 1", adult_yn="N")

    def test_sanitize_readonly_sql_requires_adult_filter_for_tb_product(self):
        with self.assertRaises(CustomResponseException):
            ai_chat_service._sanitize_readonly_sql(
                "SELECT product_id, title FROM tb_product ORDER BY product_id DESC LIMIT 5",
                adult_yn="N",
            )

    def test_sanitize_readonly_sql_normalizes_status_code_alias_eq(self):
        sql = (
            "SELECT product_id, title FROM tb_product "
            "WHERE ratings_code = 'all' AND status_code = 'completed' LIMIT 5"
        )
        normalized = ai_chat_service._sanitize_readonly_sql(sql, adult_yn="N")
        self.assertIn("status_code = 'end'", normalized)

    def test_sanitize_readonly_sql_normalizes_status_code_alias_in(self):
        sql = (
            "SELECT product_id, title FROM tb_product "
            "WHERE ratings_code = 'all' AND status_code IN ('serial', 'paused', 'end') LIMIT 5"
        )
        normalized = ai_chat_service._sanitize_readonly_sql(sql, adult_yn="N")
        self.assertIn("status_code IN ('ongoing', 'rest', 'end')", normalized)

    def test_sanitize_readonly_sql_rejects_unknown_status_code(self):
        sql = (
            "SELECT product_id, title FROM tb_product "
            "WHERE ratings_code = 'all' AND status_code = 'archived' LIMIT 5"
        )
        with self.assertRaises(CustomResponseException) as exc:
            ai_chat_service._sanitize_readonly_sql(sql, adult_yn="N")
        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("tb_product.status_code", exc.exception.message)

    def test_sanitize_readonly_sql_allows_valid_alias_columns(self):
        sql = (
            "SELECT p.product_id, p.title, pam.premise "
            "FROM tb_product p "
            "JOIN tb_product_ai_metadata pam ON pam.product_id = p.product_id "
            "WHERE p.ratings_code = 'all' LIMIT 5"
        )
        normalized = ai_chat_service._sanitize_readonly_sql(sql, adult_yn="N")
        self.assertIn("pam.premise", normalized)

    def test_sanitize_readonly_sql_rejects_wrong_table_column_reference(self):
        sql = (
            "SELECT p.premise "
            "FROM tb_product p "
            "WHERE p.ratings_code = 'all' LIMIT 5"
        )
        with self.assertRaises(CustomResponseException) as exc:
            ai_chat_service._sanitize_readonly_sql(sql, adult_yn="N")
        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("p.premise", exc.exception.message)

    def test_sanitize_readonly_sql_rejects_wrong_metric_column_reference(self):
        sql = (
            "SELECT p.episode_total "
            "FROM tb_product p "
            "WHERE p.ratings_code = 'all' LIMIT 5"
        )
        with self.assertRaises(CustomResponseException) as exc:
            ai_chat_service._sanitize_readonly_sql(sql, adult_yn="N")
        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("p.episode_total", exc.exception.message)

    def test_compute_similarity_score_reflects_engagement_bonus(self):
        base = {
            "worldview_tags": ["현대"],
            "protagonist_type_tags": ["성장형"],
            "protagonist_job_tags": ["학생"],
            "protagonist_material_tags": ["회귀"],
            "axis_romance_tags": [],
            "axis_style_tags": ["가벼움"],
            "protagonist_goal_primary": "복수",
            "mood": "긴장감",
            "pacing": "fast",
            "premise": "회귀 후 복수",
            "hook": "첫 회부터 반격",
        }
        weak = {
            **base,
            "binge_rate": 0.10,
            "total_next_clicks": 18,
            "total_readers": 24,
            "dropoff_7d": 15,
            "reengage_rate": 0.01,
            "avg_speed_cpm": 1450,
            "reading_rate": 0.5,
            "count_hit": 8000,
        }
        strong = {
            **base,
            "binge_rate": 0.69,
            "total_next_clicks": 18,
            "total_readers": 24,
            "dropoff_7d": 2,
            "reengage_rate": 0.22,
            "avg_speed_cpm": 910,
            "reading_rate": 0.5,
            "count_hit": 8000,
        }

        weak_score, _ = ai_chat_service._compute_similarity_score(base, weak)
        strong_score, _ = ai_chat_service._compute_similarity_score(base, strong)
        self.assertGreater(strong_score, weak_score)

    def test_score_similar_candidate_prioritizes_taste_layer_when_profile_exists(self):
        base = {
            "worldview_tags": ["현대"],
            "protagonist_type_tags": ["성장형"],
            "protagonist_job_tags": ["학생"],
            "protagonist_material_tags": ["회귀"],
            "axis_romance_tags": [],
            "axis_style_tags": ["가벼움"],
            "protagonist_goal_primary": "복수",
            "mood": "긴장감",
            "pacing": "fast",
            "premise": "회귀 후 복수",
            "hook": "첫 회부터 반격",
        }
        profile = {
            "taste_tags": ["정치", "회귀"],
            "preferred_protagonist": {"전략가": 4},
            "preferred_mood": {"긴장감": 4},
            "preferred_pacing": "fast",
        }
        taste_fit = {
            **base,
            "protagonist_type": "전략가",
            "taste_tags": ["정치", "회귀"],
            "binge_rate": 0.2,
            "total_next_clicks": 12,
            "total_readers": 16,
            "dropoff_7d": 4,
            "reengage_rate": 0.08,
            "avg_speed_cpm": 960,
            "reading_rate": 0.45,
            "count_hit": 3000,
        }
        metric_fit = {
            **base,
            "protagonist_type": "먼치킨",
            "taste_tags": ["학원"],
            "binge_rate": 0.75,
            "total_next_clicks": 30,
            "total_readers": 35,
            "dropoff_7d": 1,
            "reengage_rate": 0.24,
            "avg_speed_cpm": 910,
            "reading_rate": 0.75,
            "count_hit": 40000,
        }

        taste_total, _, _, taste_match = ai_chat_service._score_similar_candidate(base, taste_fit, profile)
        metric_total, _, _, _ = ai_chat_service._score_similar_candidate(base, metric_fit, profile)

        self.assertGreater(taste_total, metric_total)
        self.assertGreater(taste_match["protagonist"], 0)

    def test_run_readonly_query_wraps_sqlalchemy_error(self):
        async def run():
            db = AsyncMock()
            db.execute.side_effect = SQLAlchemyError("bad column")
            with self.assertRaises(CustomResponseException) as exc:
                await ai_chat_service._run_readonly_query(
                    db,
                    "SELECT product_id FROM tb_product WHERE ratings_code = 'all' LIMIT 5",
                    adult_yn="N",
                )
            self.assertEqual(exc.exception.status_code, 400)

        import asyncio

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
