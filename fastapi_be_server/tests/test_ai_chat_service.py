import asyncio
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

    def test_sanitize_readonly_sql_requires_public_cardable_product_filters(self):
        with self.assertRaises(CustomResponseException) as exc:
            ai_chat_service._sanitize_readonly_sql(
                "SELECT p.product_id, p.title FROM tb_product p WHERE p.ratings_code = 'all' LIMIT 5",
                adult_yn="N",
            )
        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("open_yn", exc.exception.message)

        sanitized = ai_chat_service._sanitize_readonly_sql(
            """
            SELECT p.product_id, p.title
            FROM tb_product p
            WHERE p.ratings_code = 'all'
              AND p.open_yn = 'Y'
              AND p.author_name IS NOT NULL
              AND TRIM(p.author_name) <> ''
            LIMIT 5
            """,
            adult_yn="N",
        )
        self.assertIn("p.open_yn = 'Y'", sanitized)

    def test_sanitize_readonly_sql_requires_successful_recommendable_metadata(self):
        with self.assertRaises(CustomResponseException) as exc:
            ai_chat_service._sanitize_readonly_sql(
                """
                SELECT p.product_id, p.title
                FROM tb_product p
                JOIN tb_product_ai_metadata m ON m.product_id = p.product_id
                WHERE p.ratings_code = 'all'
                  AND p.open_yn = 'Y'
                  AND p.author_name IS NOT NULL
                  AND TRIM(p.author_name) <> ''
                LIMIT 5
                """,
                adult_yn="N",
            )
        self.assertEqual(exc.exception.status_code, 400)
        self.assertIn("analysis_status", exc.exception.message)

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

    def test_build_match_tags_prioritizes_query_visible_evidence(self):
        tags = ai_chat_service._build_match_tags(
            {
                "protagonist_job_tags": ["선생님", "헌터"],
                "taste_tags": ["아카데미", "전투"],
            },
            ["헌터물", "헌터"],
        )

        self.assertEqual(tags[0], "헌터")
        self.assertIn("아카데미", tags)

    def test_build_exploration_state_keeps_hard_conditions_across_followup(self):
        state = ai_chat_service._build_exploration_state(
            [
                {"role": "user", "content": "완결됐고 5화 이하 판타지 무료만 추천해줘"},
                {"role": "assistant", "content": "조건에 맞는 작품을 찾아볼게요."},
                {"role": "user", "content": "그거 말고 더 가벼운 거"},
            ],
            {"source_action_id": "followup-1", "source_action_intent": "recommend_similar"},
        )

        self.assertEqual(state["hard"]["status_codes"], ["end"])
        self.assertEqual(state["hard"]["episode_total"], {"op": "<=", "value": 5, "source": "explicit"})
        self.assertEqual(state["hard"]["price_types"], ["free"])
        self.assertTrue(state["weak"]["light_read"])
        self.assertIn("판타지", state["soft"]["keywords"])
        self.assertEqual(state["last_action"]["source_action_intent"], "recommend_similar")

    def test_build_exploration_state_maps_short_and_long_service_aliases(self):
        short_state = ai_chat_service._build_exploration_state(
            [{"role": "user", "content": "완결 단편 추천해줘"}],
            None,
        )
        long_state = ai_chat_service._build_exploration_state(
            [{"role": "user", "content": "장편 판타지 추천해줘"}],
            None,
        )

        self.assertEqual(short_state["hard"]["episode_total"], {"op": "<=", "value": 5, "source": "short_work_alias"})
        self.assertEqual(long_state["hard"]["episode_total"], {"op": ">=", "value": 100, "source": "long_work_alias"})

    def test_product_hard_constraint_violations_only_blocks_explicit_hard(self):
        product = {
            "ongoingState": "ongoing",
            "episodeCount": 6,
            "priceType": "paid",
        }
        hard_state = {
            "hard": {
                "status_codes": ["end"],
                "episode_total": {"op": "<=", "value": 5},
                "price_types": ["free"],
            },
            "weak": {"light_read": True},
        }
        weak_only_state = {"weak": {"light_read": True, "entry_easy": True}}

        self.assertEqual(
            ai_chat_service._product_hard_constraint_violations(product, hard_state),
            ["status", "episode_total", "price_type"],
        )
        self.assertEqual(ai_chat_service._product_hard_constraint_violations(product, weak_only_state), [])

    def test_final_response_tool_schema_limits_suggested_actions_to_three_or_four(self):
        final_tool = next(
            tool for tool in ai_chat_service.DATA_AGENT_TOOLS
            if tool["name"] == ai_chat_service.FINAL_RESPONSE_TOOL_NAME
        )
        suggested_actions_schema = final_tool["input_schema"]["properties"]["suggested_actions"]

        self.assertEqual(suggested_actions_schema["minItems"], 3)
        self.assertEqual(suggested_actions_schema["maxItems"], 4)
        self.assertEqual(
            set(suggested_actions_schema["items"]["properties"]["intent"]["enum"]),
            ai_chat_service.SUGGESTED_ACTION_INTENTS,
        )
        self.assertIn("action_id", suggested_actions_schema["items"]["properties"])
        self.assertIn("priority", suggested_actions_schema["items"]["properties"])
        self.assertIn("suggested_actions", final_tool["input_schema"]["required"])

    def test_normalize_suggested_actions_enforces_three_or_four_and_falls_back(self):
        product = {
            "title": "추천작",
            "matchTags": ["헌터", "아카데미"],
            "tasteTags": ["성장"],
        }
        raw_actions = [
            {
                "id": "bad-topic",
                "label": "#없는태그 포인트는?",
                "user_message": "#없는태그 포인트는?",
                "intent": "explain_attribute",
                "topic": "없는태그",
            },
            {
                "id": "duplicate-match",
                "label": "취향 근거는?",
                "user_message": "취향 근거는?",
                "intent": "explain_match",
            },
            {
                "id": "same-intent",
                "label": "왜 맞나요?",
                "user_message": "왜 맞나요?",
                "intent": "explain_match",
            },
            {
                "id": "bad-intent",
                "label": "아무거나",
                "user_message": "아무거나",
                "intent": "open_browser",
            },
            {
                "id": "similar",
                "label": "비슷한 것도?",
                "user_message": "비슷한 것도?",
                "intent": "recommend_similar",
            },
        ]

        actions = ai_chat_service._normalize_suggested_actions(product, raw_actions)

        self.assertIn(len(actions), {3, 4})
        self.assertLess(len(actions), 5)
        self.assertEqual(len({(item["intent"], item.get("topic", "")) for item in actions}), len(actions))
        self.assertNotIn("없는태그", [item.get("topic") for item in actions])
        self.assertEqual(
            [item["intent"] for item in actions],
            ["explain_match", "explain_entry", "explain_attribute", "recommend_similar"],
        )
        self.assertEqual([item["priority"] for item in actions], [10, 20, 30, 40])
        self.assertTrue(all(item["id"] and item["actionId"] for item in actions))

    def test_normalize_no_match_suggested_actions_fills_deterministic_fallback(self):
        raw_actions = [
            {
                "id": "broaden-status",
                "label": "연재중도 포함해볼까요?",
                "user_message": "연재중도 포함해서 판타지 추천해줘",
                "intent": "recommend_similar",
            },
            {
                "id": "broaden-genre",
                "label": "장르를 넓혀볼까요?",
                "user_message": "장르 제한 없이 완결작 추천해줘",
                "intent": "recommend_similar",
            },
            {
                "id": "narrow-entry",
                "label": "초반 쉬운 작품만 볼까요?",
                "user_message": "초반 진입 쉬운 작품 위주로 추천해줘",
                "intent": "recommend_similar",
            },
        ]

        actions = ai_chat_service._normalize_no_match_suggested_actions(raw_actions)

        self.assertCountEqual([item["label"] for item in actions], [item["label"] for item in raw_actions])
        self.assertEqual([item["intent"] for item in actions], ["recommend_similar"] * 3)
        short_actions = ai_chat_service._normalize_no_match_suggested_actions(
            raw_actions[:2],
            latest_user_query="완결 판타지 5화 이하 작품 추천해줘",
        )
        empty_actions = ai_chat_service._normalize_no_match_suggested_actions(
            None,
            latest_user_query="완결 판타지 5화 이하 작품 추천해줘",
        )

        self.assertIn(len(short_actions), {3, 4})
        self.assertIn(len(empty_actions), {3, 4})
        self.assertTrue(all(item["intent"] == "recommend_similar" for item in empty_actions))
        self.assertNotIn("왜 제 취향에 맞나요?", [item["label"] for item in actions])

    def test_normalize_no_match_suggested_actions_drops_repeated_prompt(self):
        raw_actions = [
            {
                "id": "repeat",
                "label": "완결 판타지 5화 이하 작품 추천해줘",
                "user_message": "완결 판타지 5화 이하 작품 추천해줘",
                "intent": "recommend_similar",
            },
            {
                "id": "broaden-status",
                "label": "연재중도 포함해볼까요?",
                "user_message": "연재중도 포함해서 판타지 추천해줘",
                "intent": "recommend_similar",
            },
            {
                "id": "broaden-genre",
                "label": "장르를 넓혀볼까요?",
                "user_message": "장르 제한 없이 완결작 추천해줘",
                "intent": "recommend_similar",
            },
        ]

        actions = ai_chat_service._normalize_no_match_suggested_actions(
            raw_actions,
            latest_user_query="완결 판타지 5화 이하 작품 추천해줘",
        )

        self.assertIn(len(actions), {3, 4})
        self.assertNotIn("완결 판타지 5화 이하 작품 추천해줘", [item["userMessage"] for item in actions])
        self.assertNotIn("완결 판타지 5화 이하 작품 추천해줘", [item["label"] for item in actions])

    def test_normalize_no_match_suggested_actions_forces_recommend_intent(self):
        raw_actions = [
            {
                "id": "bad-intent-1",
                "label": "연재중도 포함해볼까요?",
                "user_message": "연재중도 포함해서 판타지 추천해줘",
                "intent": "explain_attribute",
            },
            {
                "id": "bad-intent-2",
                "label": "장르를 넓혀볼까요?",
                "user_message": "장르 제한 없이 완결작 추천해줘",
                "intent": "explain_entry",
            },
            {
                "id": "ok-intent",
                "label": "초반 쉬운 작품만 볼까요?",
                "user_message": "초반 진입 쉬운 작품 위주로 추천해줘",
                "intent": "recommend_similar",
            },
        ]

        actions = ai_chat_service._normalize_no_match_suggested_actions(raw_actions)

        self.assertEqual([item["intent"] for item in actions], ["recommend_similar"] * 3)

    def test_normalize_no_match_suggested_actions_drops_explain_only_actions(self):
        raw_actions = [
            {
                "id": "detail-settings",
                "label": "작품의 상세 설정 보기",
                "user_message": "작품의 상세 설정을 더 알려줘",
                "intent": "recommend_similar",
            },
            {
                "id": "similar-strategy",
                "label": "비슷한 전략물 추천",
                "user_message": "비슷한 전략물 추천해줘",
                "intent": "recommend_similar",
            },
            {
                "id": "ongoing-fantasy",
                "label": "다른 연재 중인 판타지 보기",
                "user_message": "다른 연재 중인 판타지 작품도 추천해줘",
                "intent": "recommend_similar",
            },
        ]

        actions = ai_chat_service._normalize_no_match_suggested_actions(
            raw_actions,
            latest_user_query="연재 중인 5화 이하 판타지 작품을 추천해줘",
        )

        visible_text = " ".join(item["label"] for item in actions)
        self.assertIn(len(actions), {3, 4})
        self.assertNotIn("작품의 상세 설정 보기", visible_text)
        self.assertTrue(all(item["intent"] == "recommend_similar" for item in actions))

    def test_normalize_no_match_suggested_actions_uses_service_episode_terms(self):
        raw_actions = [
            {
                "id": "short-fantasy",
                "label": "완결 단편소설 추천해줘",
                "user_message": "완결 단편소설 추천해줘",
                "intent": "recommend_similar",
            },
            {
                "id": "very-short",
                "label": "초단편도 볼래요",
                "user_message": "초단편 작품도 추천해줘",
                "intent": "recommend_similar",
            },
            {
                "id": "long-work",
                "label": "장편소설도 볼래요",
                "user_message": "장편소설 100화 이상 작품 추천해줘",
                "intent": "recommend_similar",
            },
            {
                "id": "short-novel",
                "label": "짧은 소설로 다시",
                "user_message": "짧은 소설 위주로 다시 추천해줘",
                "intent": "recommend_similar",
            },
        ]

        actions = ai_chat_service._normalize_no_match_suggested_actions(
            raw_actions,
            blocked_intents={"recommend_similar"},
        )

        visible_text = " ".join(f"{item['label']} {item['userMessage']}" for item in actions)
        self.assertIn(len(actions), {3, 4})
        self.assertIn("5화 이하 작품", visible_text)
        self.assertIn("100화 이상 작품", visible_text)
        self.assertNotRegex(visible_text, r"단편소설|초단편|장편소설|짧은 소설|100화 이상 100화 이상 작품")
        self.assertEqual([item["intent"] for item in actions], ["recommend_similar"] * len(actions))

    def test_normalize_no_match_reply_uses_service_episode_terms(self):
        reply = ai_chat_service._normalize_no_match_reply(
            "완결된 초단편 판타지 작품은 부족합니다. "
            "대신 완결된 판타지 작품 중에서 100화 이상인 100화 이상 작품을 볼 수 있어요."
        )

        self.assertIn("5화 이하 작품", reply)
        self.assertIn("100화 이상인 작품", reply)
        self.assertNotRegex(reply, r"초단편|단편소설|100화 이상인 100화 이상 작품")

    def test_rewrite_episode_length_terms_drops_duplicate_episode_phrases(self):
        self.assertEqual(
            ai_chat_service._rewrite_episode_length_terms_for_service("판타지 장르의 100화 이상 100화 이상 작품 추천"),
            "판타지 장르의 100화 이상 작품 추천",
        )

    def test_generate_no_match_suggested_actions_uses_llm_action_tool(self):
        async def run():
            raw_actions = [
                {
                    "id": "broaden-status",
                    "label": "연재중도 포함해볼까요?",
                    "user_message": "연재중도 포함해서 판타지 추천해줘",
                    "intent": "recommend_similar",
                },
                {
                    "id": "broaden-genre",
                    "label": "장르를 넓혀볼까요?",
                    "user_message": "장르 제한 없이 완결작 추천해줘",
                    "intent": "recommend_similar",
                },
                {
                    "id": "narrow-entry",
                    "label": "초반 쉬운 작품만 볼까요?",
                    "user_message": "초반 진입 쉬운 작품 위주로 추천해줘",
                    "intent": "recommend_similar",
                },
            ]
            with patch.object(
                ai_chat_service,
                "_call_gemini_messages",
                AsyncMock(
                    return_value={
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tool-actions-1",
                                "name": ai_chat_service.NO_MATCH_SUGGESTED_ACTION_TOOL_NAME,
                                "input": {"suggested_actions": raw_actions},
                            }
                        ]
                    }
                ),
            ) as mocked_call:
                actions = await ai_chat_service._generate_no_match_suggested_actions(
                    latest_user_query="너무 좁은 완결 판타지 추천해줘",
                    reply="조건에 맞는 작품을 찾지 못했습니다.",
                    blocked_intents=set(),
                )

            mocked_call.assert_awaited_once()
            self.assertEqual(
                mocked_call.await_args.kwargs["tools"][0]["name"],
                ai_chat_service.NO_MATCH_SUGGESTED_ACTION_TOOL_NAME,
            )
            self.assertEqual(
                mocked_call.await_args.kwargs["tool_choice"],
                {"type": "tool", "name": ai_chat_service.NO_MATCH_SUGGESTED_ACTION_TOOL_NAME},
            )
            self.assertIn("라이크노벨은 회차 단위", mocked_call.await_args.kwargs["system_prompt"])
            self.assertIn("5화 이하 작품", mocked_call.await_args.kwargs["system_prompt"])
            self.assertCountEqual([item["label"] for item in actions], [item["label"] for item in raw_actions])

        import asyncio

        asyncio.run(run())

    def test_generate_no_match_suggested_actions_falls_back_when_llm_fails(self):
        async def run():
            with patch.object(
                ai_chat_service,
                "_call_gemini_messages",
                AsyncMock(side_effect=RuntimeError("provider down")),
            ):
                actions = await ai_chat_service._generate_no_match_suggested_actions(
                    latest_user_query="완결 판타지 5화 이하 작품 추천해줘",
                    reply="조건에 맞는 작품을 찾지 못했습니다.",
                    blocked_intents=set(),
                )

            self.assertIn(len(actions), {3, 4})
            visible_text = " ".join(f"{item['label']} {item['userMessage']}" for item in actions)
            self.assertIn("5화 이하 작품", visible_text)
            self.assertTrue(all(item["intent"] == "recommend_similar" for item in actions))

        import asyncio

        asyncio.run(run())

    def test_current_product_suggested_actions_follow_manual_topic(self):
        product = {
            "title": "퍼펙트 메이지",
            "matchTags": ["마법사", "이세계"],
            "tasteTags": ["성장"],
        }

        actions = ai_chat_service._normalize_suggested_actions(
            product,
            ai_chat_service._build_current_product_suggested_actions(
                product=product,
                latest_query="그럼 주인공은?",
            ),
        )
        labels = [item["label"] for item in actions]
        fallback_labels = [
            item["label"]
            for item in ai_chat_service._normalize_suggested_actions(product, None)
        ]

        self.assertIn(len(actions), {3, 4})
        self.assertLess(len(actions), 5)
        self.assertTrue(any("주인공" in label for label in labels))
        self.assertNotEqual(labels, fallback_labels)

    def test_current_product_suggested_actions_block_source_intent(self):
        product = {
            "title": "퍼펙트 메이지",
            "matchTags": ["마법사", "이세계"],
            "tasteTags": ["성장"],
        }

        actions = ai_chat_service._normalize_suggested_actions(
            product,
            ai_chat_service._build_current_product_suggested_actions(
                product=product,
                latest_query="초반 진입 포인트는?",
            ),
            blocked_intents={"explain_entry"},
        )

        self.assertIn(len(actions), {3, 4})
        self.assertLess(len(actions), 5)
        self.assertNotIn("explain_entry", [item["intent"] for item in actions])
        self.assertNotIn("초반 진입 포인트는?", [item["label"] for item in actions])

    def test_build_page_context_keeps_followup_action_metadata(self):
        context = asyncio.run(
            ai_chat_service._build_page_context(
                {
                    "source_action_id": "followup-match-1",
                    "source_action_intent": "explain_match",
                },
                AsyncMock(),
            )
        )

        self.assertEqual(context["source_action_id"], "followup-match-1")
        self.assertEqual(context["source_action_intent"], "explain_match")

    def test_build_page_context_keeps_active_focus_product_id(self):
        context = asyncio.run(
            ai_chat_service._build_page_context(
                {
                    "active_focus_product_id": 521,
                },
                AsyncMock(),
            )
        )

        self.assertEqual(context["active_focus_product_id"], 521)

    def test_normalize_product_reply_blocks_uncarded_candidate_title_and_limits_readability(self):
        reply = ai_chat_service._normalize_product_reply(
            raw_reply="'추천작'이 좋습니다. 카드가 없는 작품도 좋아요. 세 번째 문장입니다.",
            product={"title": "추천작", "matchTags": ["헌터"]},
            unselected_candidate_titles=["카드가 없는 작품"],
        )

        self.assertIn("추천작", reply)
        self.assertIn("헌터", reply)
        self.assertNotIn("카드가 없는 작품", reply)
        self.assertLessEqual(len(reply), ai_chat_service.MAX_RECOMMENDATION_REPLY_CHARS)

    def test_normalize_product_reply_compacts_overlong_reply_for_panel_readability(self):
        reply = ai_chat_service._normalize_product_reply(
            raw_reply=(
                "헌터 육성학교를 배경으로 한 아주 긴 설명입니다. "
                "이 작품은 다음 화로 이어서 보는 비율과 주인공의 목표와 세계관의 상세한 맥락을 모두 길게 풀어내서 "
                "모바일 말풍선에서 읽기 부담스러운 답변입니다. "
                "여기에 전투 방식, 학원 배경, 조력자 관계까지 다시 한 번 길게 덧붙입니다."
            ),
            product={
                "title": "요정이야기~규격파괴 사제의 임시동맹~",
                "matchTags": ["헌터", "선생님", "마법"],
            },
        )

        self.assertLessEqual(len(reply), ai_chat_service.MAX_REPLY_CHARS)
        self.assertIn("헌터", reply)
        self.assertIn("선생님", reply)
        self.assertNotIn("요정이야기~규격파괴 사제의 임시동맹~", reply)
        self.assertIn("\n", reply)
        self.assertNotIn("읽기 부담스러운", reply)

    def test_normalize_no_match_reply_removes_success_language_without_product(self):
        reply = ai_chat_service._normalize_no_match_reply("'비공개 후보작'을 추천합니다.")

        self.assertNotIn("비공개 후보작", reply)
        self.assertNotIn("추천합니다", reply)
        self.assertIn("작품 카드를 확정하지 못했습니다", reply)

    def test_limit_readable_reply_keeps_two_sentences(self):
        reply = ai_chat_service._limit_readable_reply("첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다.")

        self.assertEqual(reply, "첫 문장입니다.\n둘째 문장입니다.")

    def test_tool_result_to_gemini_preserves_function_response_id(self):
        parts = ai_chat_service._internal_user_content_to_gemini_parts(
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-query-1",
                    "name": "run_readonly_query",
                    "content": '{"rows":[]}',
                }
            ]
        )

        self.assertEqual(parts[0]["functionResponse"]["id"], "tool-query-1")
        self.assertEqual(parts[0]["functionResponse"]["name"], "run_readonly_query")

    def test_should_not_reask_explicit_no_match_after_detail_lookup(self):
        detail_cache = {777: {"product_id": 777, "title": "후보작"}}

        self.assertFalse(
            ai_chat_service._should_reask_final_with_product_id(
                final_tool_input={"mode": "no_match", "product_id": None},
                detail_cache=detail_cache,
            )
        )
        self.assertTrue(
            ai_chat_service._should_reask_final_with_product_id(
                final_tool_input={"product_id": None},
                detail_cache=detail_cache,
            )
        )

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
                    "_call_gemini_messages",
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
                ) as mocked_call_gemini,
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
                    messages=[{"role": "user", "content": "요즘 뜨는 판타지 작품 추천해줘"}],
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

                system_prompt = mocked_call_gemini.await_args.kwargs["system_prompt"]
                self.assertIn("현재 페이지 작품 ID: 326", system_prompt)
                self.assertIn("현재 보고 있던 작품: 퍼펙트 메이지", system_prompt)
                self.assertEqual(payload["product"]["productId"], 521)

        import asyncio

        asyncio.run(run())

    def test_handle_chat_uses_gemini_fast_path_for_current_product_overview(self):
        async def run():
            with (
                patch.object(
                    ai_chat_service,
                    "_build_page_context",
                    AsyncMock(
                        return_value={
                            "page_type": "product",
                            "pathname": "/product/1106",
                            "current_product_id": 1106,
                            "current_product_title": "마법사 인생 2회차는 소드마스터",
                            "focus_product_card": True,
                        }
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_reader_context",
                    AsyncMock(return_value={"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": [], "factor_scores": {}}),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_gemini_messages",
                    AsyncMock(side_effect=AssertionError("current product overview must use Gemini fast path")),
                ) as mocked_call_gemini_messages,
                patch.object(
                    ai_chat_service,
                    "get_product_info",
                    AsyncMock(
                        return_value={
                            "product_id": 1106,
                            "title": "마법사 인생 2회차는 소드마스터",
                            "author_name": "퀀퀀",
                            "episode_total": 77,
                            "synopsis_text": "잘못 살았다. 이번 생엔 반드시 마법사가 아닌, 소드마스터가 돼야 한다.",
                            "premise": "회귀한 마법사가 검의 길을 선택한다.",
                            "hook": "마법사였던 전생을 뒤집는 소드마스터 성장담.",
                            "taste_tags": ["회귀", "성장"],
                            "worldview_tags": ["아카데미"],
                        }
                    ),
                ) as mocked_product_info,
                patch.object(
                    ai_chat_service,
                    "_call_gemini_text",
                    AsyncMock(return_value="회귀한 대마법사가 검으로 다시 길을 여는 성장 판타지예요."),
                ) as mocked_call_gemini_text,
                patch.object(
                    ai_chat_service,
                    "_build_product_and_taste",
                    AsyncMock(
                        return_value=(
                            {
                                "productId": 1106,
                                "title": "마법사 인생 2회차는 소드마스터",
                                "matchReason": "",
                            },
                            {"protagonist": 0.0, "mood": 0.0, "pacing": 0.0},
                        )
                    ),
                ),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id=None,
                    messages=[{"role": "user", "content": "마법사 인생 2회차는 소드마스터 이 작품 어떤 작품인지 알려줘"}],
                    context={
                        "trigger": "manual",
                        "page_type": "product",
                        "pathname": "/product/1106",
                        "current_product_id": 1106,
                        "focus_product_card": True,
                    },
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

                mocked_call_gemini_messages.assert_not_awaited()
                mocked_product_info.assert_awaited_once()
                mocked_call_gemini_text.assert_awaited_once()
                self.assertNotIn("providerFallback", payload)
                self.assertEqual(payload["reply"], "회귀한 대마법사가 검으로 다시 길을 여는 성장 판타지예요.")
                self.assertEqual(payload["product"]["productId"], 1106)
                self.assertEqual(payload["product"]["matchReason"], payload["reply"])

        import asyncio

        asyncio.run(run())

    def test_handle_chat_uses_current_product_overview_for_followup_chip(self):
        async def run():
            with (
                patch.object(
                    ai_chat_service,
                    "_build_page_context",
                    AsyncMock(
                        return_value={
                            "page_type": "product",
                            "pathname": "/product/326",
                            "current_product_id": 326,
                            "current_product_title": "퍼펙트 메이지",
                            "focus_product_card": True,
                            "source_action_intent": "explain_entry",
                        }
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_reader_context",
                    AsyncMock(return_value={"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": [], "factor_scores": {}}),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_gemini_messages",
                    AsyncMock(side_effect=AssertionError("follow-up chip must stay on current product overview path")),
                ) as mocked_call_gemini_messages,
                patch.object(
                    ai_chat_service,
                    "get_product_info",
                    AsyncMock(
                        return_value={
                            "product_id": 326,
                            "title": "퍼펙트 메이지",
                            "author_name": "justme",
                            "episode_total": 225,
                            "synopsis_text": "게임 최강 마법사가 죽음 뒤 다른 세계에서 눈뜬다.",
                            "story_context": {
                                "availability": "ready",
                                "scope_episode_to": 20,
                                "plot_points": ["아이작이 초반 전투와 소환 사건을 겪는다."],
                            },
                        }
                    ),
                ) as mocked_product_info,
                patch.object(
                    ai_chat_service,
                    "_call_gemini_text",
                    AsyncMock(return_value="초반은 아이작이 낯선 세계에서 힘과 정체성을 확인하는 진입부예요."),
                ) as mocked_call_gemini_text,
                patch.object(
                    ai_chat_service,
                    "_build_product_and_taste",
                    AsyncMock(
                        return_value=(
                            {
                                "productId": 326,
                                "title": "퍼펙트 메이지",
                                "matchReason": "",
                            },
                            {"protagonist": 0.0, "mood": 0.0, "pacing": 0.0},
                        )
                    ),
                ),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id=None,
                    messages=[
                        {"role": "user", "content": "퍼펙트 메이지 이 작품 어떤 작품인지 알려줘"},
                        {"role": "assistant", "content": "게임 최강 마법사의 이세계 판타지예요.", "product_id": 326},
                        {"role": "user", "content": "초반 진입 포인트는?"},
                    ],
                    context={
                        "trigger": "manual",
                        "page_type": "product",
                        "pathname": "/product/326",
                        "current_product_id": 326,
                        "focus_product_card": True,
                        "source_action_intent": "explain_entry",
                    },
                    preset=None,
                    exclude_ids=[326],
                    adult_yn="N",
                    db=AsyncMock(),
                )

                mocked_call_gemini_messages.assert_not_awaited()
                mocked_product_info.assert_awaited_once()
                self.assertTrue(mocked_product_info.await_args.kwargs["include_story_context"])
                mocked_call_gemini_text.assert_awaited_once()
                user_prompt = mocked_call_gemini_text.await_args.kwargs["user_prompt"]
                self.assertIn("최근 대화 맥락", user_prompt)
                self.assertIn("AI사서[작품 ID 326]", user_prompt)
                self.assertIn("초반 진입 포인트는?", user_prompt)
                self.assertEqual(payload["reply"], "초반은 아이작이 낯선 세계에서 힘과 정체성을 확인하는 진입부예요.")
                self.assertEqual(payload["product"]["productId"], 326)
                self.assertEqual(payload["product"]["matchReason"], payload["reply"])
                self.assertIn(len(payload["suggestedActions"]), {3, 4})
                self.assertNotIn(
                    "explain_entry",
                    [item["intent"] for item in payload["suggestedActions"]],
                )
                self.assertNotIn(
                    "초반 진입 포인트는?",
                    [item["label"] for item in payload["suggestedActions"]],
                )

        import asyncio

        asyncio.run(run())

    def test_build_data_agent_system_prompt_includes_conversation_memory(self):
        prompt = ai_chat_service._build_data_agent_system_prompt(
            adult_yn="N",
            preset=None,
            reader_context={"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": [], "factor_scores": {}},
            session_state={
                "conversation_memory": [
                    "사용자: 현대 배경에 성장형이면 좋겠어",
                    "AI사서[작품 ID 326]: 퍼펙트 메이지를 먼저 보여드렸어요.",
                    "사용자: 그럼 초반은 어때?",
                ],
                "recommended_product_ids": [326],
                "exclude_product_ids": [326],
            },
            page_context={"page_type": "home", "pathname": "/"},
        )

        self.assertIn("최근 대화 맥락", prompt)
        self.assertIn("현대 배경에 성장형", prompt)
        self.assertIn("AI사서[작품 ID 326]", prompt)
        self.assertIn("짧은 후속질문은 최근 대화 맥락", prompt)

    def test_current_product_overview_request_accepts_manual_contextual_followup(self):
        messages = [
            {"role": "user", "content": "퍼펙트 메이지 이 작품 어떤 작품인지 알려줘"},
            {"role": "assistant", "content": "게임 최강 마법사의 이세계 판타지예요.", "product_id": 326},
            {"role": "user", "content": "그럼 주인공은?"},
        ]

        self.assertTrue(
            ai_chat_service._is_current_product_overview_request(
                messages,
                {
                    "page_type": "product",
                    "current_product_id": 326,
                    "current_product_title": "퍼펙트 메이지",
                    "focus_product_card": False,
                },
            )
        )
        self.assertFalse(
            ai_chat_service._is_current_product_overview_request(
                [*messages[:-1], {"role": "user", "content": "비슷한 작품 추천해줘"}],
                {
                    "page_type": "product",
                    "current_product_id": 326,
                    "current_product_title": "퍼펙트 메이지",
                    "focus_product_card": False,
                },
            )
        )

    def test_current_product_overview_request_uses_active_focus_for_short_format_followup(self):
        messages = [
            {"role": "user", "content": "비슷한 작품도 보여줘"},
            {"role": "assistant", "content": "이 작품을 먼저 보세요.", "product_id": 521},
            {"role": "user", "content": "지금 바로 읽을지 말지 3줄로 판단해줘"},
        ]

        self.assertEqual(
            ai_chat_service._resolve_conversation_product_id(
                {
                    "current_product_id": 326,
                    "active_focus_product_id": 521,
                },
                {"recommended_product_ids": [521]},
            ),
            521,
        )
        self.assertTrue(
            ai_chat_service._is_current_product_overview_request(
                messages,
                {
                    "page_type": "product",
                    "current_product_id": 521,
                    "active_focus_product_id": 521,
                    "current_product_title": "추천작",
                    "focus_product_card": False,
                },
            )
        )

    def test_current_product_overview_request_rejects_new_recommendation_on_product_page(self):
        messages = [
            {"role": "user", "content": "퍼펙트 메이지 이 작품 어떤 작품인지 알려줘"},
            {"role": "assistant", "content": "게임 최강 마법사의 이세계 판타지예요.", "product_id": 326},
            {"role": "user", "content": "완결됐고 초반 진입 쉬운 판타지 추천해줘"},
        ]

        self.assertFalse(
            ai_chat_service._is_current_product_overview_request(
                messages,
                {
                    "page_type": "product",
                    "current_product_id": 326,
                    "current_product_title": "퍼펙트 메이지",
                    "focus_product_card": False,
                },
            )
        )

    def test_build_data_agent_system_prompt_marks_new_recommendation_and_active_focus(self):
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
            session_state={
                "last_user_query": "완결됐고 초반 진입 쉬운 판타지 추천해줘",
                "conversation_memory": [
                    "AI사서[작품 ID 521]: 추천작을 먼저 보여드렸어요.",
                ],
                "recommended_product_ids": [521],
                "exclude_product_ids": [],
            },
            page_context={
                "page_type": "product",
                "current_product_id": 326,
                "active_focus_product_id": 521,
                "current_product_title": "퍼펙트 메이지",
                "pathname": "/product/326",
            },
        )

        self.assertIn("이번 질문은 새 작품 추천 요청이다", prompt)
        self.assertIn("현재 대화 초점 작품 ID: 521", prompt)

    def test_handle_chat_new_recommendation_escapes_current_product_overview_path(self):
        async def run():
            with (
                patch.object(
                    ai_chat_service,
                    "_build_page_context",
                    AsyncMock(
                        return_value={
                            "page_type": "product",
                            "pathname": "/product/326",
                            "current_product_id": 326,
                            "active_focus_product_id": 326,
                            "current_product_title": "퍼펙트 메이지",
                            "focus_product_card": False,
                        }
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_reader_context",
                    AsyncMock(return_value={"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": [], "factor_scores": {}}),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_gemini_text",
                    AsyncMock(side_effect=AssertionError("new recommendation must not use current product overview path")),
                ) as mocked_call_gemini_text,
                patch.object(
                    ai_chat_service,
                    "_call_gemini_messages",
                    AsyncMock(
                        return_value={
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "tool-final-1",
                                    "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                    "input": {
                                        "reply": "완결 판타지로는 후보작을 먼저 보세요.",
                                        "product_id": 888,
                                    },
                                }
                            ]
                        }
                    ),
                ) as mocked_call_gemini_messages,
                patch.object(
                    ai_chat_service,
                    "_build_product_and_taste",
                    AsyncMock(
                        return_value=(
                            {
                                "productId": 888,
                                "title": "완결 판타지 후보작",
                                "matchReason": "",
                                "ongoingState": "end",
                            },
                            {"protagonist": 0.0, "mood": 0.0, "pacing": 0.0},
                        )
                    ),
                ),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id=None,
                    messages=[
                        {"role": "user", "content": "퍼펙트 메이지 이 작품 어떤 작품인지 알려줘"},
                        {"role": "assistant", "content": "게임 최강 마법사의 이세계 판타지예요.", "product_id": 326},
                        {"role": "user", "content": "완결됐고 초반 진입 쉬운 판타지 추천해줘"},
                    ],
                    context={
                        "trigger": "manual",
                        "page_type": "product",
                        "pathname": "/product/326",
                        "current_product_id": 326,
                        "active_focus_product_id": 326,
                    },
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

                mocked_call_gemini_text.assert_not_awaited()
                mocked_call_gemini_messages.assert_awaited_once()
                system_prompt = mocked_call_gemini_messages.await_args.kwargs["system_prompt"]
                self.assertIn("이번 질문은 새 작품 추천 요청이다", system_prompt)
                self.assertEqual(payload["product"]["productId"], 888)

        import asyncio

        asyncio.run(run())

    def test_handle_chat_reasks_when_final_product_violates_requested_status(self):
        async def run():
            async def build_product_and_taste(**kwargs):
                product_id = kwargs.get("selected_product_id")
                ongoing_state = "end" if product_id == 777 else "ongoing"
                return (
                    {
                        "productId": product_id,
                        "title": "완결 후보작" if product_id == 777 else "비완결 후보작",
                        "coverUrl": None,
                        "authorNickname": "작가",
                        "episodeCount": 80,
                        "matchReason": "",
                        "matchTags": ["판타지"],
                        "tasteTags": [],
                        "serialCycle": None,
                        "priceType": "free",
                        "ongoingState": ongoing_state,
                        "monopolyYn": "N",
                        "lastEpisodeDate": None,
                        "newReleaseYn": "N",
                        "cpContractYn": "N",
                        "waitingForFreeYn": "N",
                        "sixNinePathYn": "N",
                    },
                    {"protagonist": 0.0, "mood": 0.0, "pacing": 0.0},
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
                    "_call_gemini_messages",
                    AsyncMock(
                        side_effect=[
                            {"content": [{"type": "tool_use", "id": "tool-query-1", "name": "run_readonly_query", "input": {"sql": "SELECT product_id, title, status_code FROM tb_product WHERE status_code = 'end' AND ratings_code = 'all' AND open_yn = 'Y' AND author_name IS NOT NULL AND TRIM(author_name) <> '' LIMIT 5"}}]},
                            {"content": [{"type": "tool_use", "id": "tool-query-2", "name": "run_readonly_query", "input": {"sql": "SELECT product_id, title, status_code FROM tb_product WHERE ratings_code = 'all' AND open_yn = 'Y' AND author_name IS NOT NULL AND TRIM(author_name) <> '' LIMIT 5"}}]},
                            {"content": [{"type": "tool_use", "id": "tool-final-1", "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME, "input": {"reply": "비완결 후보작을 추천합니다.", "product_id": 35}}]},
                            {"content": [{"type": "tool_use", "id": "tool-final-2", "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME, "input": {"reply": "완결 후보작을 추천합니다.", "product_id": 777}}]},
                        ]
                    ),
                ) as mocked_call_gemini,
                patch.object(
                    ai_chat_service,
                    "_dispatch_tool",
                    AsyncMock(
                        side_effect=[
                            {"rows": [{"product_id": 777, "title": "완결 후보작", "status_code": "end"}]},
                            {"rows": [{"product_id": 35, "title": "비완결 후보작", "status_code": "ongoing"}]},
                        ]
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_product_and_taste",
                    AsyncMock(side_effect=build_product_and_taste),
                ),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "완결됐고 초반 진입 쉬운 판타지 추천해줘"}],
                    context={"page_type": "home"},
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

            self.assertEqual(payload["product"]["productId"], 777)
            self.assertEqual(mocked_call_gemini.await_count, 4)
            force_message = mocked_call_gemini.await_args_list[3].kwargs["messages"][-1]["content"]
            self.assertIn("명시 상태 조건(완결)", force_message)
            self.assertIn("상태 조건을 만족하는 후보 작품 ID [777]", force_message)

        import asyncio

        asyncio.run(run())

    def test_handle_chat_uses_status_keyword_fallback_when_model_returns_no_match(self):
        async def run():
            async def build_product_and_taste(**kwargs):
                if kwargs.get("selected_product_id") != 777:
                    return (None, {"protagonist": 0.0, "mood": 0.0, "pacing": 0.0})
                return (
                    {
                        "productId": 777,
                        "title": "완결 판타지 후보작",
                        "coverUrl": None,
                        "authorNickname": "작가",
                        "episodeCount": 80,
                        "matchReason": "",
                        "matchTags": ["판타지"],
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
                    {"protagonist": 0.0, "mood": 0.0, "pacing": 0.0},
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
                    "_call_gemini_messages",
                    AsyncMock(
                        return_value={
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "tool-final-1",
                                    "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                    "input": {
                                        "reply": "조건에 맞는 작품을 확정하지 못했습니다.",
                                        "mode": "no_match",
                                        "product_id": None,
                                    },
                                }
                            ]
                        }
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_run_broad_metadata_keyword_query",
                    AsyncMock(return_value=[{"product_id": 777, "title": "완결 판타지 후보작", "status_code": "end"}]),
                ) as mocked_broad_query,
                patch.object(
                    ai_chat_service,
                    "_build_product_and_taste",
                    AsyncMock(side_effect=build_product_and_taste),
                ),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "완결됐고 초반 진입 쉬운 판타지 추천해줘"}],
                    context={"page_type": "home"},
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

            self.assertEqual(payload["product"]["productId"], 777)
            self.assertEqual(payload["finalMode"], "weak_recommend")
            self.assertEqual(mocked_broad_query.await_args.kwargs["required_status_codes"], {"end"})
            self.assertIn("판타지", mocked_broad_query.await_args.kwargs["keywords"])

        import asyncio

        asyncio.run(run())

    def test_handle_chat_returns_llm_no_match_suggested_actions_without_product_card(self):
        async def run():
            llm_actions = [
                {
                    "id": "broaden-status",
                    "label": "연재중도 포함해볼까요?",
                    "user_message": "연재중도 포함해서 판타지 추천해줘",
                    "intent": "recommend_similar",
                    "priority": 10,
                },
                {
                    "id": "broaden-genre",
                    "label": "완결작 전체로 넓혀볼까요?",
                    "user_message": "장르 제한 없이 완결작 추천해줘",
                    "intent": "recommend_similar",
                    "priority": 20,
                },
                {
                    "id": "narrow-magic",
                    "label": "마법 중심으로 좁혀볼까요?",
                    "user_message": "완결작 중 마법 중심으로 찾아줘",
                    "intent": "recommend_similar",
                    "priority": 30,
                },
            ]
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
                    "_build_status_keyword_fallback_recommendation",
                    AsyncMock(return_value=None),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_gemini_messages",
                    AsyncMock(
                        return_value={
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "tool-final-1",
                                    "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                    "input": {
                                        "reply": "조건에 맞는 공개 작품을 확정하지 못했습니다.",
                                        "mode": "no_match",
                                        "product_id": None,
                                        "suggested_actions": llm_actions,
                                    },
                                }
                            ]
                        }
                    ),
                ),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "조건이 너무 좁은 완결 판타지 추천해줘"}],
                    context={"page_type": "home"},
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

            self.assertIsNone(payload["product"])
            self.assertEqual(payload["finalMode"], "no_match")
            self.assertEqual([item["label"] for item in payload["suggestedActions"]], [item["label"] for item in llm_actions])
            self.assertNotIn("왜 제 취향에 맞나요?", [item["label"] for item in payload["suggestedActions"]])

        import asyncio

        asyncio.run(run())

    def test_handle_chat_reasks_no_match_finalize_when_suggested_actions_missing(self):
        async def run():
            forced_actions = [
                {
                    "id": "broaden-status",
                    "label": "연재중도 포함해볼까요?",
                    "user_message": "연재중도 포함해서 판타지 추천해줘",
                    "intent": "recommend_similar",
                },
                {
                    "id": "broaden-genre",
                    "label": "완결작 전체로 넓혀볼까요?",
                    "user_message": "장르 제한 없이 완결작 추천해줘",
                    "intent": "recommend_similar",
                },
                {
                    "id": "narrow-magic",
                    "label": "마법 중심으로 좁혀볼까요?",
                    "user_message": "완결작 중 마법 중심으로 찾아줘",
                    "intent": "recommend_similar",
                },
            ]
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
                    "_build_status_keyword_fallback_recommendation",
                    AsyncMock(return_value=None),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_gemini_messages",
                    AsyncMock(
                        return_value={
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "tool-final-1",
                                    "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                    "input": {
                                        "reply": "조건에 맞는 공개 작품을 확정하지 못했습니다.",
                                        "mode": "no_match",
                                        "product_id": None,
                                    },
                                }
                            ]
                        }
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_force_finalize_response",
                    AsyncMock(
                        return_value={
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "tool-final-2",
                                    "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                    "input": {
                                        "reply": "조건에 맞는 공개 작품을 확정하지 못했습니다.",
                                        "mode": "no_match",
                                        "product_id": None,
                                        "suggested_actions": forced_actions,
                                    },
                                }
                            ]
                        }
                    ),
                ) as mocked_force_finalize,
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "조건이 너무 좁은 완결 판타지 추천해줘"}],
                    context={"page_type": "home"},
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

            mocked_force_finalize.assert_awaited_once()
            self.assertIsNone(payload["product"])
            self.assertEqual(payload["finalMode"], "no_match")
            self.assertEqual([item["label"] for item in payload["suggestedActions"]], [item["label"] for item in forced_actions])
            self.assertIn("suggested_actions를 3개 또는 4개", mocked_force_finalize.await_args.kwargs["reason"])

        import asyncio

        asyncio.run(run())

    def test_handle_chat_generates_no_match_actions_when_forced_finalize_omits_them(self):
        async def run():
            generated_actions = [
                {
                    "id": "broaden-status",
                    "label": "연재중도 포함해볼까요?",
                    "user_message": "연재중도 포함해서 판타지 추천해줘",
                    "intent": "recommend_similar",
                },
                {
                    "id": "broaden-genre",
                    "label": "완결작 전체로 넓혀볼까요?",
                    "user_message": "장르 제한 없이 완결작 추천해줘",
                    "intent": "recommend_similar",
                },
                {
                    "id": "narrow-magic",
                    "label": "마법 중심으로 좁혀볼까요?",
                    "user_message": "완결작 중 마법 중심으로 찾아줘",
                    "intent": "recommend_similar",
                },
            ]
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
                    "_build_status_keyword_fallback_recommendation",
                    AsyncMock(return_value=None),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_gemini_messages",
                    AsyncMock(
                        side_effect=[
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-final-1",
                                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                        "input": {
                                            "reply": "조건에 맞는 공개 작품을 확정하지 못했습니다.",
                                            "mode": "no_match",
                                            "product_id": None,
                                        },
                                    }
                                ]
                            },
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-actions-1",
                                        "name": ai_chat_service.NO_MATCH_SUGGESTED_ACTION_TOOL_NAME,
                                        "input": {"suggested_actions": generated_actions},
                                    }
                                ]
                            },
                        ]
                    ),
                ) as mocked_call,
                patch.object(
                    ai_chat_service,
                    "_force_finalize_response",
                    AsyncMock(
                        return_value={
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "tool-final-2",
                                    "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                    "input": {
                                        "reply": "조건에 맞는 공개 작품을 확정하지 못했습니다.",
                                        "mode": "no_match",
                                        "product_id": None,
                                    },
                                }
                            ]
                        }
                    ),
                ),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "조건이 너무 좁은 완결 판타지 추천해줘"}],
                    context={"page_type": "home"},
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

            self.assertEqual(mocked_call.await_count, 2)
            self.assertIsNone(payload["product"])
            self.assertEqual(payload["finalMode"], "no_match")
            self.assertEqual([item["label"] for item in payload["suggestedActions"]], [item["label"] for item in generated_actions])

        import asyncio

        asyncio.run(run())

    def test_handle_chat_similar_request_uses_deterministic_similar_path(self):
        async def run():
            with (
                patch.object(
                    ai_chat_service,
                    "_build_page_context",
                    AsyncMock(
                        return_value={
                            "page_type": "product",
                            "pathname": "/product/326",
                            "current_product_id": 326,
                            "current_product_title": "퍼펙트 메이지",
                            "focus_product_card": False,
                        }
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_reader_context",
                    AsyncMock(return_value={"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": [], "factor_scores": {}}),
                ),
                patch.object(
                    ai_chat_service,
                    "_call_gemini_messages",
                    AsyncMock(side_effect=AssertionError("similar request must use deterministic similar path first")),
                ) as mocked_call_gemini_messages,
                patch.object(
                    ai_chat_service,
                    "get_similar_products",
                    AsyncMock(
                        return_value=(
                            {"product_id": 326, "title": "퍼펙트 메이지"},
                            [
                                {
                                    "product_id": 888,
                                    "title": "비슷한 후보작",
                                    "matched_signals": ["세계관", "능력/소재"],
                                }
                            ],
                        )
                    ),
                ) as mocked_get_similar_products,
                patch.object(
                    ai_chat_service,
                    "_build_product_and_taste",
                    AsyncMock(
                        return_value=(
                            {
                                "productId": 888,
                                "title": "비슷한 후보작",
                                "matchReason": "",
                                "matchTags": ["마법", "먼치킨"],
                                "tasteTags": ["판타지"],
                            },
                            {"protagonist": 0.0, "mood": 0.0, "pacing": 0.0},
                        )
                    ),
                ),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id=None,
                    messages=[{"role": "user", "content": "비슷한 작품도 보여줘"}],
                    context={
                        "trigger": "manual",
                        "page_type": "product",
                        "pathname": "/product/326",
                        "current_product_id": 326,
                    },
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

                mocked_call_gemini_messages.assert_not_awaited()
                mocked_get_similar_products.assert_awaited_once()
                self.assertEqual(mocked_get_similar_products.await_args.kwargs["base_product_id"], 326)
                self.assertEqual(payload["product"]["productId"], 888)
                self.assertIn("세계관", payload["reply"])
                self.assertIn(len(payload["suggestedActions"]), {3, 4})
                self.assertNotIn(
                    "recommend_similar",
                    [item["intent"] for item in payload["suggestedActions"]],
                )
                self.assertNotIn(
                    "비슷한 작품도 볼래요",
                    [item["label"] for item in payload["suggestedActions"]],
                )

        import asyncio

        asyncio.run(run())

    def test_call_gemini_text_uses_low_thinking_and_larger_output_budget(self):
        class FakeGeminiResponse:
            status_code = 200
            text = ""

            def json(self):
                return {"candidates": [{"content": {"parts": [{"text": "완성된 답변"}]}}]}

        class FakeAsyncClient:
            calls = []

            def __init__(self, *, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                self.__class__.calls.append({"args": args, "kwargs": kwargs})
                return FakeGeminiResponse()

        async def run():
            FakeAsyncClient.calls = []
            with (
                patch.object(ai_chat_service.settings, "GEMINI_API_KEY", "test-key"),
                patch.object(ai_chat_service.settings, "WEBSOCHAT_GEMINI_MODEL", "gemini-3.1-flash-lite"),
                patch.object(ai_chat_service.settings, "AI_CHAT_GEMINI_MODEL", "gemini-3.1-pro-preview"),
                patch.object(ai_chat_service.httpx, "AsyncClient", FakeAsyncClient),
            ):
                reply = await ai_chat_service._call_gemini_text(
                    system_prompt="system",
                    user_prompt="user",
                )

            self.assertEqual(reply, "완성된 답변")
            request_url = FakeAsyncClient.calls[0]["args"][0]
            self.assertIn("/models/gemini-3.1-pro-preview:generateContent", request_url)
            request_json = FakeAsyncClient.calls[0]["kwargs"]["json"]
            generation_config = request_json["generationConfig"]
            self.assertEqual(generation_config["maxOutputTokens"], 2048)
            self.assertEqual(generation_config["temperature"], 1.0)
            self.assertEqual(generation_config["thinkingConfig"]["thinkingLevel"], "low")

        import asyncio

        asyncio.run(run())

    def test_gemini_tool_response_preserves_thought_signature(self):
        internal = ai_chat_service._gemini_response_to_internal(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "get_fact_catalog",
                                        "args": {},
                                    },
                                    "thoughtSignature": "sig-a",
                                }
                            ]
                        }
                    }
                ]
            }
        )

        contents = ai_chat_service._to_gemini_contents(
            [{"role": "assistant", "content": internal["content"]}]
        )

        self.assertEqual(contents[0]["parts"][0]["thoughtSignature"], "sig-a")
        self.assertEqual(
            contents[0]["parts"][0]["functionCall"]["name"],
            "get_fact_catalog",
        )

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

    def test_build_fact_catalog_guides_public_metadata_wide_search(self):
        catalog = ai_chat_service._build_fact_catalog()
        guidance_text = "\n".join(catalog["rules"]["guidance"])

        self.assertIn("p.open_yn = 'Y'", guidance_text)
        self.assertIn("m.analysis_status = 'success'", guidance_text)
        self.assertIn("protagonist_job_tags", guidance_text)
        self.assertIn("protagonist_material_tags", guidance_text)
        self.assertIn("episode_summary_text", guidance_text)
        self.assertIn("tb_product_user_keyword.keyword_name", guidance_text)
        self.assertNotIn("similar_famous를 넓게", guidance_text)

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
                "exploration_state": {
                    "hard": {"status_codes": ["end"], "episode_total": {"op": "<=", "value": 5}},
                    "weak": {"entry_easy": True},
                },
            },
            page_context={
                "current_product_id": 326,
                "current_product_title": "퍼펙트 메이지",
                "pathname": "/product/326",
            },
        )
        self.assertIn("빈 답변 금지", prompt)
        self.assertIn("공통점 2개와 차이점 1개", prompt)
        self.assertIn("내장 데이터 카탈로그", prompt)
        self.assertIn('"tb_product_ai_metadata"', prompt)
        self.assertIn("tb_product_episode에서 COUNT(*)", prompt)
        self.assertIn("tb_product에는 premise, hook, reading_rate, evaluation_score, episode_total 컬럼이 없다", prompt)
        self.assertIn("submit_final_recommendation.mode 규칙", prompt)
        self.assertIn("카드가 없는 다른 후보 작품명은 쓰지 않는다", prompt)
        self.assertIn("reply는 2문장, 220자 이내", prompt)
        self.assertIn("suggested_actions를 반드시 3개 또는 4개", prompt)
        self.assertNotIn("similar_famous를 넓게", prompt)
        self.assertIn("조회 결과에 추천 가능한 후보가 1개라도 있으면 no_match보다 weak_recommend를 우선한다", prompt)
        self.assertIn("라이크노벨은 회차 단위", prompt)
        self.assertIn("초단편/단편/짧은 작품", prompt)
        self.assertIn("100화 이상 작품", prompt)
        self.assertIn("soft/weak 조건은 후보를 없애는 필터가 아니라", prompt)
        self.assertIn("질문에 없는 숫자 임계치", prompt)
        self.assertIn("strict AND로 0건을 만들지 않는다", prompt)
        self.assertIn("2/3 이상 맞는 후보를 우선 비교해 weak_recommend", prompt)
        self.assertIn("DB 결과 내부의 상대 비교", prompt)
        self.assertIn("공개 작품 카드로 보여줄 수 있는 후보만", prompt)
        self.assertIn("protagonist_job_tags", prompt)
        self.assertIn("episode_summary_text", prompt)

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
                    "_call_gemini_messages",
                    AsyncMock(
                        side_effect=[
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
                self.assertEqual(mocked_dispatch_tool.await_count, 1)
                self.assertEqual(
                    mocked_dispatch_tool.await_args_list[0].kwargs["tool_name"],
                    "run_readonly_query",
                )
                self.assertNotIn(
                    "get_fact_catalog",
                    [tool["name"] for tool in ai_chat_service._call_gemini_messages.await_args_list[0].kwargs["tools"]],
                )
                self.assertEqual(
                    ai_chat_service._call_gemini_messages.await_args_list[0].kwargs["tool_choice"],
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
                    "_call_gemini_messages",
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
                                        "input": {
                                            "reply": "후보를 찾았습니다.",
                                            "mode": "no_match",
                                            "product_id": None,
                                            "suggested_actions": [
                                                {
                                                    "id": "broaden-status",
                                                    "label": "연재중도 포함해볼까요?",
                                                    "user_message": "연재중도 포함해서 현대 미스터리 추천해줘",
                                                    "intent": "recommend_similar",
                                                },
                                                {
                                                    "id": "broaden-genre",
                                                    "label": "미스터리 조건을 넓혀볼까요?",
                                                    "user_message": "현대 장르에서 미스터리 조건을 넓혀 추천해줘",
                                                    "intent": "recommend_similar",
                                                },
                                                {
                                                    "id": "narrow-keyword",
                                                    "label": "사건 중심으로 좁혀볼까요?",
                                                    "user_message": "사건 중심 현대 미스터리 작품 추천해줘",
                                                    "intent": "recommend_similar",
                                                },
                                            ],
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
                self.assertIn("작품 카드를 확정하지 못했습니다", payload["reply"])
                self.assertNotIn("후보를 찾았습니다", payload["reply"])

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
                    "_call_gemini_messages",
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
                ) as mocked_call_gemini,
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
                self.assertEqual(mocked_call_gemini.await_count, 4)
                self.assertEqual(mocked_call_gemini.await_args_list[2].kwargs["tool_choice"], {"type": "any"})
                self.assertEqual(
                    sorted(tool["name"] for tool in mocked_call_gemini.await_args_list[2].kwargs["tools"]),
                    ["get_product_info", ai_chat_service.FINAL_RESPONSE_TOOL_NAME],
                )
                self.assertIn(
                    "후보 작품 ID [777] 중 가장 가까운 작품을 확인하려면 get_product_info(product_id=...)를 먼저 호출한 뒤 recommend 또는 weak_recommend로 submit_final_recommendation을 제출하세요.",
                    mocked_call_gemini.await_args_list[2].kwargs["messages"][-1]["content"],
                )

        import asyncio

        asyncio.run(run())

    def test_dispatch_readonly_query_attaches_candidate_details_for_model_selection(self):
        async def run():
            with (
                patch.object(
                    ai_chat_service,
                    "_run_readonly_query",
                    AsyncMock(
                        return_value={
                            "sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5",
                            "row_count": 1,
                            "rows": [{"product_id": 777, "title": "후보작"}],
                        }
                    ),
                ) as run_query,
                patch.object(
                    ai_chat_service,
                    "get_product_info",
                    AsyncMock(
                        return_value={
                            "product_id": 777,
                            "title": "후보작",
                            "author_name": "작가A",
                            "status_code": "ongoing",
                            "monopoly_yn": "Y",
                            "contract_yn": "Y",
                            "episode_total": 80,
                            "new_release_yn": "Y",
                            "waiting_for_free_yn": "Y",
                            "six_nine_path_yn": "N",
                            "primary_genre": "현대판타지",
                            "sub_genre": "미스터리",
                            "premise": "사건을 추적하는 성장형 주인공",
                            "hook": "초반 단서 회수가 빠르게 이어진다",
                            "episode_summary_text": "사건의 단서를 따라가며 세계관이 열린다",
                            "taste_tags": ["성장형", "미스터리"],
                            "worldview_tags": ["현대"],
                            "protagonist_type_tags": ["성장형"],
                            "protagonist_job_tags": ["탐정"],
                            "axis_style_tags": ["미스터리"],
                        }
                    ),
                ) as get_product_info,
                patch.object(
                    ai_chat_service,
                    "_load_story_context_summaries",
                    AsyncMock(
                        return_value={
                            777: {
                                "plot_points": ["배치가 만든 후보작 초반 맥락"],
                                "characters": [{"display_name": "서윤"}],
                            }
                        }
                    ),
                ) as load_story_contexts,
            ):
                result = await ai_chat_service._dispatch_tool(
                    db=AsyncMock(),
                    tool_name="run_readonly_query",
                    tool_input={"sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5"},
                    exclude_ids=[],
                    adult_yn="N",
                )

            run_query.assert_awaited_once()
            get_product_info.assert_awaited_once()
            load_story_contexts.assert_awaited_once()
            self.assertEqual(result["candidate_details"][0]["product_id"], 777)
            self.assertEqual(result["candidate_details"][0]["premise"], "사건을 추적하는 성장형 주인공")
            self.assertEqual(result["candidate_details"][0]["story_context"]["plot_points"], ["배치가 만든 후보작 초반 맥락"])
            self.assertEqual(result["candidate_details"][0]["monopoly_yn"], "Y")
            self.assertEqual(result["candidate_details"][0]["new_release_yn"], "Y")
            self.assertEqual(result["candidate_details"][0]["waiting_for_free_yn"], "Y")
            self.assertIn("모델이 선택", result["candidate_detail_policy"])

        import asyncio

        asyncio.run(run())

    def test_current_product_overview_prompt_includes_story_context(self):
        _, user_prompt = ai_chat_service._build_current_product_overview_gemini_prompt(
            product_info={
                "title": "후보작",
                "story_context": {
                    "availability": "ready",
                    "scope_episode_to": 12,
                    "plot_points": ["초반에 도시의 균열을 추적한다."],
                    "characters": [{"display_name": "서윤", "is_protagonist": True, "action_tags": ["추적"]}],
                    "opening_hooks": ["비밀 문양이 다시 열린다."],
                },
            },
            messages=[],
            user_query="이 작품 어떤 작품이야?",
        )

        self.assertIn("storyContext", user_prompt)
        self.assertIn("초반에 도시의 균열", user_prompt)
        self.assertIn("비밀 문양", user_prompt)

    def test_dispatch_readonly_query_filters_uncardable_rows_and_continues(self):
        async def run():
            with (
                patch.object(
                    ai_chat_service,
                    "_run_readonly_query",
                    AsyncMock(
                        return_value={
                            "sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5",
                            "row_count": 3,
                            "rows": [
                                {"product_id": 315, "title": "숨긴 후보"},
                                {"product_id": 777, "title": "공개 후보"},
                                {"product_id": 888, "title": "두번째 공개 후보"},
                            ],
                        }
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "get_product_info",
                    AsyncMock(
                        side_effect=[
                            CustomResponseException(status_code=404, message="작품 정보를 찾을 수 없습니다."),
                            {"product_id": 777, "title": "공개 후보", "author_name": "작가A"},
                            {"product_id": 888, "title": "두번째 공개 후보", "author_name": "작가B"},
                        ]
                    ),
                ) as get_product_info,
            ):
                result = await ai_chat_service._dispatch_tool(
                    db=AsyncMock(),
                    tool_name="run_readonly_query",
                    tool_input={"sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5"},
                    exclude_ids=[],
                    adult_yn="N",
                )

            self.assertEqual(get_product_info.await_count, 3)
            self.assertEqual([row["product_id"] for row in result["rows"]], [777, 888])
            self.assertEqual(result["row_count"], 2)
            self.assertEqual(result["candidate_product_ids"], [777, 888])
            self.assertEqual([item["product_id"] for item in result["candidate_details"]], [777, 888])

        import asyncio

        asyncio.run(run())

    def test_dispatch_readonly_query_returns_empty_candidates_when_all_rows_uncardable(self):
        async def run():
            with (
                patch.object(
                    ai_chat_service,
                    "_run_readonly_query",
                    AsyncMock(
                        return_value={
                            "sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5",
                            "row_count": 1,
                            "rows": [{"product_id": 315, "title": "숨긴 후보"}],
                        }
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "get_product_info",
                    AsyncMock(
                        side_effect=[
                            CustomResponseException(status_code=404, message="작품 정보를 찾을 수 없습니다."),
                        ]
                    ),
                ),
            ):
                result = await ai_chat_service._dispatch_tool(
                    db=AsyncMock(),
                    tool_name="run_readonly_query",
                    tool_input={"sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5"},
                    exclude_ids=[],
                    adult_yn="N",
                )

            self.assertEqual(result["rows"], [])
            self.assertEqual(result["row_count"], 0)
            self.assertEqual(result["candidate_product_ids"], [])
            self.assertEqual(result["candidate_details"], [])

        import asyncio

        asyncio.run(run())

    def test_handle_chat_uses_query_candidate_details_without_extra_detail_roundtrip(self):
        async def run():
            build_product_and_taste = AsyncMock(
                return_value=(
                    {"productId": 777, "title": "후보작"},
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
                    "_call_gemini_messages",
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
                ) as mocked_call_gemini,
                patch.object(
                    ai_chat_service,
                    "_dispatch_tool",
                    AsyncMock(
                        return_value={
                            "sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5",
                            "row_count": 1,
                            "rows": [{"product_id": 777, "title": "후보작"}],
                            "candidate_details": [
                                {
                                    "product_id": 777,
                                    "title": "후보작",
                                    "premise": "사건을 추적하는 성장형 주인공",
                                    "hook": "초반 단서 회수가 빠르게 이어진다",
                                }
                            ],
                        }
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

            self.assertEqual(payload["product"]["productId"], 777)
            self.assertEqual(mocked_call_gemini.await_count, 3)
            self.assertEqual(
                [tool["name"] for tool in mocked_call_gemini.await_args_list[-1].kwargs["tools"]],
                [ai_chat_service.FINAL_RESPONSE_TOOL_NAME],
            )
            self.assertIn(
                "이미 get_product_info로 확인한 작품이 있습니다.",
                mocked_call_gemini.await_args_list[-1].kwargs["messages"][-1]["content"],
            )
            self.assertEqual(
                build_product_and_taste.await_args.kwargs["prefetched_product_info"]["product_id"],
                777,
            )

        import asyncio

        asyncio.run(run())

    def test_handle_chat_reasks_when_final_product_is_outside_candidates(self):
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
                    "_call_gemini_messages",
                    AsyncMock(
                        side_effect=[
                            {"content": [{"type": "tool_use", "id": "tool-query-1", "name": "run_readonly_query", "input": {"sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5"}}]},
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-final-1",
                                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                        "input": {"reply": "후보 밖 작품을 추천합니다.", "product_id": 999},
                                    }
                                ]
                            },
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-final-2",
                                        "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                        "input": {"reply": "후보 안 작품을 추천합니다.", "product_id": 777},
                                    }
                                ]
                            },
                        ]
                    ),
                ) as mocked_call_gemini,
                patch.object(
                    ai_chat_service,
                    "_dispatch_tool",
                    AsyncMock(return_value={"rows": [{"product_id": 777, "title": "후보작"}]}),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_product_and_taste",
                    AsyncMock(
                        return_value=(
                            {
                                "productId": 777,
                                "title": "후보작",
                                "coverUrl": None,
                                "authorNickname": "작가B",
                                "episodeCount": 33,
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

            self.assertEqual(payload["product"]["productId"], 777)
            self.assertEqual(mocked_build_product_and_taste.await_args.kwargs["selected_product_id"], 777)
            self.assertIn(
                "제출한 product_id 999는 확보한 후보 목록 [777]에 없습니다.",
                mocked_call_gemini.await_args_list[2].kwargs["messages"][-1]["content"],
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
                    "_call_gemini_messages",
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
                ) as mocked_call_gemini,
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
                self.assertEqual(mocked_call_gemini.await_count, 2)
                self.assertEqual(
                    mocked_call_gemini.await_args_list[1].kwargs["tool_choice"],
                    {"type": "any"},
                )
                self.assertEqual(
                    [tool["name"] for tool in mocked_call_gemini.await_args_list[1].kwargs["tools"]],
                    [ai_chat_service.FINAL_RESPONSE_TOOL_NAME],
                )
                self.assertEqual(
                    mocked_call_gemini.await_args_list[1].kwargs["messages"][-1]["content"],
                    "추가 조회는 허용되지 않습니다. submit_final_recommendation 계약이 잘못됐습니다. recommend/weak_recommend면 product_id를 반드시 넣고, no_match면 product_id를 null로 제출하세요. 지금까지 확보한 조회 결과만 근거로 반드시 submit_final_recommendation을 호출하세요.",
                )

        import asyncio

        asyncio.run(run())

    def test_handle_chat_does_not_return_recommend_mode_without_product_card(self):
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
                    "_call_gemini_messages",
                    AsyncMock(
                        return_value={
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "tool-final-1",
                                    "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME,
                                    "input": {
                                        "reply": "비공개 후보작을 추천합니다.",
                                        "mode": "recommend",
                                        "product_id": 315,
                                    },
                                }
                            ]
                        }
                    ),
                ),
                patch.object(
                    ai_chat_service,
                    "_build_product_and_taste",
                    AsyncMock(
                        return_value=(
                            None,
                            {"protagonist": 0.0, "mood": 0.0, "pacing": 0.0},
                        )
                    ),
                ),
            ):
                payload = await ai_chat_service.handle_chat(
                    kc_user_id="kc-user",
                    messages=[{"role": "user", "content": "헌터물 추천해줘"}],
                    context={"page_type": "home"},
                    preset=None,
                    exclude_ids=[],
                    adult_yn="N",
                    db=AsyncMock(),
                )

                self.assertIsNone(payload["product"])
                self.assertEqual(payload["finalMode"], "no_match")
                self.assertNotIn("비공개 후보작", payload["reply"])

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
                    "_call_gemini_messages",
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
                ) as mocked_call_gemini,
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
                self.assertEqual(mocked_call_gemini.await_count, 4)
                self.assertEqual(
                    mocked_call_gemini.await_args_list[-1].kwargs["tool_choice"],
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
                    "_call_gemini_messages",
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
                                        "input": {
                                            "reply": "조건을 조금만 더 좁혀주시면 다시 찾아드릴게요.",
                                            "mode": "no_match",
                                            "product_id": None,
                                            "suggested_actions": [
                                                {
                                                    "id": "broaden-status",
                                                    "label": "연재중도 포함해볼까요?",
                                                    "user_message": "연재중도 포함해서 현대 미스터리 추천해줘",
                                                    "intent": "recommend_similar",
                                                },
                                                {
                                                    "id": "broaden-genre",
                                                    "label": "미스터리 조건을 넓혀볼까요?",
                                                    "user_message": "현대 장르에서 미스터리 조건을 넓혀 추천해줘",
                                                    "intent": "recommend_similar",
                                                },
                                                {
                                                    "id": "narrow-keyword",
                                                    "label": "사건 중심으로 좁혀볼까요?",
                                                    "user_message": "사건 중심 현대 미스터리 작품 추천해줘",
                                                    "intent": "recommend_similar",
                                                },
                                            ],
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
                    "_call_gemini_messages",
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
                    "_call_gemini_messages",
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
                ) as mocked_call_gemini,
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
                    mocked_call_gemini.await_args_list[-1].kwargs["tool_choice"],
                    {"type": "tool", "name": ai_chat_service.FINAL_RESPONSE_TOOL_NAME},
                )

        import asyncio

        asyncio.run(run())

    def test_handle_chat_does_not_fallback_to_first_query_row_when_forced_finalize_has_no_tool(self):
        async def run():
            with (
                patch.object(ai_chat_service, "MAX_TOOL_ROUNDS", 1),
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
                    "_call_gemini_messages",
                    AsyncMock(
                        side_effect=[
                            {"content": [{"type": "tool_use", "id": "tool-query-1", "name": "run_readonly_query", "input": {"sql": "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' LIMIT 5"}}]},
                            {"content": [{"type": "text", "text": "후보를 확정하지 못했습니다."}]},
                            {
                                "content": [
                                    {
                                        "type": "tool_use",
                                        "id": "tool-actions-1",
                                        "name": ai_chat_service.NO_MATCH_SUGGESTED_ACTION_TOOL_NAME,
                                        "input": {
                                            "suggested_actions": [
                                                {
                                                    "id": "broaden-status",
                                                    "label": "연재중도 포함해볼까요?",
                                                    "user_message": "연재중도 포함해서 현대 미스터리 추천해줘",
                                                    "intent": "recommend_similar",
                                                },
                                                {
                                                    "id": "broaden-genre",
                                                    "label": "장르를 넓혀볼까요?",
                                                    "user_message": "장르 제한 없이 추천해줘",
                                                    "intent": "recommend_similar",
                                                },
                                                {
                                                    "id": "narrow-keyword",
                                                    "label": "사건 중심으로 좁혀볼까요?",
                                                    "user_message": "사건 중심 현대 미스터리 추천해줘",
                                                    "intent": "recommend_similar",
                                                },
                                            ]
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
                    AsyncMock(return_value={"rows": [{"product_id": 909, "title": "첫 후보"}]}),
                ),
                patch.object(ai_chat_service, "_build_product_and_taste", AsyncMock()) as mocked_build_product_and_taste,
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
            self.assertEqual(len(payload["suggestedActions"]), 3)
            mocked_build_product_and_taste.assert_not_awaited()

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
                    "_call_gemini_messages",
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
                    AsyncMock(
                        return_value=(
                            {"productId": 321, "title": "후보작"},
                            {"protagonist": 0.0, "mood": 0.0, "pacing": 0.0},
                        )
                    ),
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
        sql = (
            "SELECT product_id, title FROM tb_product "
            "WHERE ratings_code = 'all' "
            "AND open_yn = 'Y' "
            "AND author_name IS NOT NULL "
            "AND TRIM(author_name) <> '' "
            "ORDER BY product_id DESC LIMIT 10"
        )
        normalized = ai_chat_service._sanitize_readonly_sql(sql, adult_yn="N")
        self.assertEqual(normalized, sql)

    def test_sanitize_readonly_sql_normalizes_nulls_last_for_mysql(self):
        sql = (
            "SELECT product_id, title FROM tb_product "
            "WHERE ratings_code = 'all' "
            "AND open_yn = 'Y' "
            "AND author_name IS NOT NULL "
            "AND TRIM(author_name) <> '' "
            "ORDER BY count_hit DESC NULLS LAST LIMIT 10"
        )
        normalized = ai_chat_service._sanitize_readonly_sql(sql, adult_yn="N")
        self.assertEqual(
            normalized,
            "SELECT product_id, title FROM tb_product WHERE ratings_code = 'all' AND open_yn = 'Y' AND author_name IS NOT NULL AND TRIM(author_name) <> '' ORDER BY count_hit DESC LIMIT 10",
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
            "WHERE ratings_code = 'all' "
            "AND open_yn = 'Y' "
            "AND author_name IS NOT NULL "
            "AND TRIM(author_name) <> '' "
            "AND status_code = 'completed' LIMIT 5"
        )
        normalized = ai_chat_service._sanitize_readonly_sql(sql, adult_yn="N")
        self.assertIn("status_code = 'end'", normalized)

    def test_sanitize_readonly_sql_normalizes_status_code_alias_in(self):
        sql = (
            "SELECT product_id, title FROM tb_product "
            "WHERE ratings_code = 'all' "
            "AND open_yn = 'Y' "
            "AND author_name IS NOT NULL "
            "AND TRIM(author_name) <> '' "
            "AND status_code IN ('serial', 'paused', 'end') LIMIT 5"
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
            "WHERE p.ratings_code = 'all' "
            "AND p.open_yn = 'Y' "
            "AND p.author_name IS NOT NULL "
            "AND TRIM(p.author_name) <> '' "
            "AND pam.analysis_status = 'success' "
            "AND COALESCE(pam.exclude_from_recommend_yn, 'N') = 'N' "
            "LIMIT 5"
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

    def test_run_readonly_query_broadens_empty_metadata_keyword_search(self):
        class FakeResult:
            def __init__(self, rows):
                self._rows = rows

            def mappings(self):
                return self

            def all(self):
                return self._rows

        async def run():
            db = AsyncMock()
            db.execute.side_effect = [
                FakeResult([]),
                FakeResult(
                    [
                        {
                            "product_id": 2020,
                            "title": "이종족 일꾼 테이밍 dev개행정합성0424",
                            "protagonist_job_tags": '["헌터", "조련사"]',
                            "relevance_score": 6,
                        }
                    ]
                ),
            ]

            result = await ai_chat_service._run_readonly_query(
                db,
                """
                SELECT p.product_id, p.title
                FROM tb_product p
                JOIN tb_product_ai_metadata m ON p.product_id = m.product_id
                WHERE p.open_yn = 'Y'
                  AND p.author_name IS NOT NULL
                  AND TRIM(p.author_name) <> ''
                  AND p.ratings_code = 'all'
                  AND m.analysis_status = 'success'
                  AND COALESCE(m.exclude_from_recommend_yn, 'N') = 'N'
                  AND (p.title LIKE '%헌터%' OR m.taste_tags LIKE '%헌터%' OR m.worldview_tags LIKE '%헌터%')
                ORDER BY p.product_id DESC
                LIMIT 5
                """,
                adult_yn="N",
            )

            self.assertEqual(db.execute.await_count, 2)
            fallback_sql = str(db.execute.await_args_list[1].args[0])
            self.assertIn("m.protagonist_job_tags", fallback_sql)
            self.assertIn("m.protagonist_material_tags", fallback_sql)
            self.assertIn("m.episode_summary_text", fallback_sql)
            self.assertEqual(result["row_count"], 1)
            self.assertTrue(result["metadata_keyword_fallback"])
            self.assertEqual(result["metadata_keyword_terms"], ["헌터"])
            self.assertEqual(result["rows"][0]["product_id"], 2020)

        import asyncio

        asyncio.run(run())

    def test_load_story_context_summaries_compacts_ready_batch_context(self):
        class FakeResult:
            def __init__(self, rows):
                self._rows = rows

            def mappings(self):
                return self

            def all(self):
                return self._rows

        async def run():
            signal_payload = {
                "episode_no": 12,
                "mentioned_characters": [
                    {
                        "character_key": "hero",
                        "display_name": "서윤",
                        "is_protagonist": True,
                        "entity_kind": "person",
                        "scene_weight": "high",
                        "action_tags": ["추적"],
                        "affect_tags": ["긴장"],
                        "relation_edges": [
                            {
                                "target_label": "도현",
                                "relation_tag": "동료",
                                "direction": "to_target",
                            }
                        ],
                    },
                    {
                        "character_key": "mentor",
                        "display_name": "도현",
                        "is_protagonist": False,
                        "entity_kind": "person",
                        "scene_weight": "medium",
                        "action_tags": ["조언"],
                        "affect_tags": ["신뢰"],
                        "relation_edges": [],
                    },
                ],
                "cliffhanger_hooks": ["비밀 문양이 다시 열린다."],
            }
            db = AsyncMock()
            db.execute.side_effect = [
                FakeResult(
                    [
                        {
                            "productId": 777,
                            "contextStatus": "ready",
                            "readyEpisodeCount": 12,
                            "totalEpisodeCount": 20,
                        }
                    ]
                ),
                FakeResult(
                    [
                        {"productId": 777, "episodeNo": 1},
                        {"productId": 777, "episodeNo": 2},
                        {"productId": 777, "episodeNo": 3},
                        {"productId": 777, "episodeNo": 4},
                        {"productId": 777, "episodeNo": 5},
                        {"productId": 777, "episodeNo": 6},
                        {"productId": 777, "episodeNo": 7},
                        {"productId": 777, "episodeNo": 8},
                        {"productId": 777, "episodeNo": 9},
                        {"productId": 777, "episodeNo": 10},
                        {"productId": 777, "episodeNo": 11},
                        {"productId": 777, "episodeNo": 12},
                    ]
                ),
                FakeResult(
                    [
                        {
                            "productId": 777,
                            "summaryType": "range_summary",
                            "episodeFrom": 1,
                            "episodeTo": 12,
                            "summaryText": "도시의 균열을 추적하는 성장형 주인공의 이야기입니다.",
                        },
                        {
                            "productId": 777,
                            "summaryType": "episode_summary",
                            "episodeFrom": 12,
                            "episodeTo": 12,
                            "summaryText": "12화에서 서윤은 단서를 따라 지하 시설에 들어간다.",
                        },
                        {
                            "productId": 777,
                            "summaryType": "episode_character_signals",
                            "episodeFrom": 12,
                            "episodeTo": 12,
                            "summaryText": ai_chat_service.json.dumps(signal_payload, ensure_ascii=False),
                        },
                    ]
                ),
            ]

            contexts = await ai_chat_service._load_story_context_summaries(db, product_ids=[777, 777, 0])

            context = contexts[777]
            self.assertEqual(db.execute.await_count, 3)
            self.assertEqual(context["scope_episode_to"], 12)
            self.assertIn("도시의 균열", context["plot_points"][0])
            self.assertEqual(context["episode_summaries"][0]["episode_to"], 12)
            self.assertEqual(context["characters"][0]["display_name"], "서윤")
            self.assertEqual(context["characters"][0]["action_tags"], ["추적"])
            self.assertEqual(context["relations"][0]["tags"], ["동료"])
            self.assertEqual(context["opening_hooks"], ["비밀 문양이 다시 열린다."])
            self.assertEqual(context["ready_episode_count"], 12)

        import asyncio

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
