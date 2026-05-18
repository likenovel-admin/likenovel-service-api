import unittest
from unittest.mock import AsyncMock, patch

from app.exceptions import CustomResponseException
from app.services.websochat import (
    websochat_game_memory,
    websochat_qa_executor,
    websochat_service,
)
from app.services.websochat.websochat_planner import _build_websochat_qa_plan


class WebsochatModelRoutingTests(unittest.IsolatedAsyncioTestCase):
    def test_qa_plan_uses_gemini_for_noncreative_answers_when_enabled(self):
        plan = _build_websochat_qa_plan(
            intent="factual",
            needs_creative=False,
            resolved_mode="general",
            gemini_enabled=True,
        )

        self.assertEqual(plan["preferred_model"], "gemini")

    async def test_qa_does_not_fallback_to_claude_after_gemini_failure(self):
        qa_plan = {
            "route": "qa",
            "answer_mode": "direct",
            "tone": "analytical",
            "route_mode": "general",
            "preferred_model": "gemini",
            "intent": "factual",
        }

        with (
            patch.object(
                websochat_qa_executor,
                "_generate_websochat_reply_with_gemini",
                new_callable=AsyncMock,
            ) as generate_gemini,
            patch.object(
                websochat_qa_executor,
                "_generate_websochat_reply_with_claude",
                new_callable=AsyncMock,
            ) as generate_claude,
        ):
            generate_gemini.side_effect = RuntimeError("gemini unavailable")
            generate_claude.return_value = ("claude reply", [])

            with self.assertRaises(RuntimeError):
                await websochat_qa_executor.execute_websochat_qa(
                    product_row={"productId": 1, "title": "테스트"},
                    user_prompt="주인공 능력이 뭐야?",
                    qa_plan=qa_plan,
                    evidence_bundle={
                        "context_text": "",
                        "summary_rows": [],
                        "chunk_rows": [],
                        "exact_episode_rows": [],
                        "tool_context_message": None,
                    },
                    recent_messages=[],
                    qa_recent_notes=[],
                    qa_corrections=[],
                    current_qa_corrections=[],
                    db=AsyncMock(),
                    hooks={},
                    max_tool_rounds=0,
                    gemini_context_episode_limit=0,
                    prefetch_context_chars=0,
                    tools=[],
                )

        generate_claude.assert_not_awaited()

    async def test_rp_does_not_fallback_to_claude_after_gemini_failure(self):
        rp_context = {
            "active_character": "named:test",
            "rp_mode": "free",
            "display_name": "테스트",
        }

        with (
            patch.object(
                websochat_service,
                "_load_websochat_rp_context",
                new_callable=AsyncMock,
            ) as load_rp_context,
            patch.object(
                websochat_service,
                "_get_websochat_recent_messages",
                new_callable=AsyncMock,
            ) as get_recent_messages,
            patch.object(
                websochat_service,
                "_build_websochat_rp_exact_recall_context",
                new_callable=AsyncMock,
            ) as build_exact_recall,
            patch.object(
                websochat_service,
                "generate_websochat_rp_reply_with_gemini",
                new_callable=AsyncMock,
            ) as generate_gemini,
        ):
            load_rp_context.return_value = rp_context
            get_recent_messages.return_value = []
            build_exact_recall.return_value = None
            generate_gemini.side_effect = RuntimeError("gemini unavailable")

            with self.assertRaises(RuntimeError):
                await websochat_service._generate_websochat_reply(
                    session_id=123,
                    session_memory={
                        "read_scope_state": "known",
                        "read_episode_to": 1,
                        "active_mode": "rp",
                        "active_character": "named:test",
                        "rp_mode": "free",
                    },
                    product_row={"productId": 1, "title": "테스트"},
                    user_prompt="안녕",
                    user_id=1,
                    db=AsyncMock(),
                    forced_route="rp",
                )

        self.assertFalse(hasattr(websochat_service, "generate_websochat_rp_reply_with_claude"))

    async def test_read_scope_guard_marks_session_after_first_unknown_prompt(self):
        reply, model_used, route_mode, _, intent, next_memory = await websochat_service._generate_websochat_reply(
            session_id=123,
            session_memory={},
            product_row={"productId": 1, "title": "테스트", "latestEpisodeNo": 5},
            user_prompt="주요 갈등이 뭐야?",
            user_id=None,
            db=AsyncMock(),
        )

        self.assertIn("아직 어디까지 읽었는지 모르겠어요", reply)
        self.assertEqual(model_used, "guard")
        self.assertEqual(route_mode, "guard:read_scope_required")
        self.assertEqual(intent, "read_scope_required")
        self.assertTrue(next_memory["read_scope_prompted"])

    async def test_read_scope_guard_second_unknown_prompt_falls_back_to_episode_one(self):
        product_row = {"productId": 1, "title": "테스트", "latestEpisodeNo": 5}
        evidence_bundle = {
            "product_row": product_row,
            "resolved_scope": {"read_episode_to": 1},
            "context_text": "",
            "summary_rows": [],
            "chunk_rows": [],
            "exact_episode_rows": [],
            "tool_context_message": None,
        }
        qa_result = {
            "reply": "1화 기준 답변입니다.",
            "model_used": "gemini",
            "route_mode": "qa",
            "fallback_used": False,
            "intent": "factual",
            "referenced_episode_nos": [],
        }

        with (
            patch.object(websochat_service.settings, "GEMINI_API_KEY", "test-key"),
            patch.object(
                websochat_service,
                "_get_websochat_recent_messages",
                new_callable=AsyncMock,
            ) as get_recent_messages,
            patch.object(
                websochat_service,
                "_resolve_websochat_intent",
                new_callable=AsyncMock,
            ) as resolve_intent,
            patch.object(
                websochat_service,
                "_resolve_websochat_qa_corrections",
                new_callable=AsyncMock,
            ) as resolve_corrections,
            patch.object(
                websochat_service,
                "assemble_websochat_scope_context",
                new_callable=AsyncMock,
            ) as assemble_context,
            patch.object(
                websochat_service,
                "execute_websochat_qa",
                new_callable=AsyncMock,
            ) as execute_qa,
        ):
            get_recent_messages.return_value = []
            resolve_intent.return_value = ("factual", False, "general")
            resolve_corrections.return_value = []
            assemble_context.return_value = evidence_bundle
            execute_qa.return_value = qa_result

            reply, model_used, route_mode, _, intent, next_memory = await websochat_service._generate_websochat_reply(
                session_id=123,
                session_memory={"read_scope_prompted": True},
                product_row=product_row,
                user_prompt="주요 인물 관계는?",
                user_id=None,
                db=AsyncMock(),
            )

        self.assertIn("1화 기준으로 시작할게요", reply)
        self.assertIn("1화 기준 답변입니다.", reply)
        self.assertEqual(model_used, "gemini")
        self.assertEqual(route_mode, "qa")
        self.assertEqual(intent, "factual")
        self.assertEqual(next_memory["read_episode_to"], 1)
        self.assertEqual(next_memory["read_scope_state"], "known")
        assemble_context.assert_awaited_once()
        context_memory = assemble_context.await_args.kwargs["session_memory"]
        self.assertEqual(context_memory["read_episode_to"], 1)

    async def test_read_scope_episode_one_fallback_survives_gemini_routing_failure(self):
        product_row = {"productId": 1, "title": "테스트", "latestEpisodeNo": 5}
        evidence_bundle = {
            "product_row": product_row,
            "resolved_scope": {"read_episode_to": 1},
            "context_text": "",
            "summary_rows": [],
            "chunk_rows": [],
            "exact_episode_rows": [],
            "tool_context_message": None,
        }
        qa_result = {
            "reply": "기본 QA 답변입니다.",
            "model_used": "gemini",
            "route_mode": "qa",
            "fallback_used": False,
            "intent": "factual",
            "referenced_episode_nos": [],
        }

        with (
            patch.object(websochat_service.settings, "GEMINI_API_KEY", "test-key"),
            patch.object(
                websochat_service,
                "_get_websochat_recent_messages",
                new_callable=AsyncMock,
            ) as get_recent_messages,
            patch.object(
                websochat_service,
                "_resolve_websochat_intent",
                new_callable=AsyncMock,
            ) as resolve_intent,
            patch.object(
                websochat_service,
                "_resolve_websochat_qa_corrections",
                new_callable=AsyncMock,
            ) as resolve_corrections,
            patch.object(
                websochat_service,
                "assemble_websochat_scope_context",
                new_callable=AsyncMock,
            ) as assemble_context,
            patch.object(
                websochat_service,
                "execute_websochat_qa",
                new_callable=AsyncMock,
            ) as execute_qa,
        ):
            get_recent_messages.return_value = []
            resolve_intent.side_effect = RuntimeError("gemini json unavailable")
            resolve_corrections.return_value = []
            assemble_context.return_value = evidence_bundle
            execute_qa.return_value = qa_result

            reply, model_used, route_mode, _, intent, next_memory = await websochat_service._generate_websochat_reply(
                session_id=123,
                session_memory={"read_scope_prompted": True},
                product_row=product_row,
                user_prompt="주요 인물 관계는?",
                user_id=None,
                db=AsyncMock(),
            )

        self.assertIn("1화 기준으로 시작할게요", reply)
        self.assertIn("기본 QA 답변입니다.", reply)
        self.assertEqual(model_used, "gemini")
        self.assertEqual(route_mode, "qa")
        self.assertEqual(intent, "factual")
        self.assertEqual(next_memory["read_episode_to"], 1)
        execute_qa.assert_awaited_once()

    def test_pending_qa_action_survives_general_qa_until_consumed(self):
        self.assertEqual(
            websochat_service._resolve_websochat_next_pending_qa_action_key(
                route_mode="qa",
                requested_qa_action_key=None,
                effective_qa_action_key=None,
                current_pending_qa_action_key="predict",
            ),
            "predict",
        )
        self.assertIsNone(
            websochat_service._resolve_websochat_next_pending_qa_action_key(
                route_mode="qa",
                requested_qa_action_key=None,
                effective_qa_action_key="predict",
                current_pending_qa_action_key="predict",
            )
        )

    def test_context_ready_with_zero_synced_episode_is_unavailable(self):
        with self.assertRaises(CustomResponseException) as captured:
            websochat_service._assert_websochat_product_context_available(
                {
                    "contextStatus": "ready",
                    "latestEpisodeNo": 5,
                    "syncedLatestEpisodeNo": 0,
                }
            )

        self.assertEqual(captured.exception.message, websochat_service.WEBSOCHAT_CONTEXT_PENDING_MESSAGE)

    def test_game_memory_boolean_strings_are_normalized_strictly(self):
        normalized = websochat_game_memory._normalize_websochat_session_memory(
            {"read_scope_prompted": "false"}
        )

        self.assertFalse(normalized["read_scope_prompted"])


if __name__ == "__main__":
    unittest.main()
