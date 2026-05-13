import unittest
from unittest.mock import AsyncMock, patch

from app.services.websochat import websochat_qa_executor, websochat_service
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
            patch.object(
                websochat_service,
                "generate_websochat_rp_reply_with_claude",
                new_callable=AsyncMock,
            ) as generate_claude,
        ):
            load_rp_context.return_value = rp_context
            get_recent_messages.return_value = []
            build_exact_recall.return_value = None
            generate_gemini.side_effect = RuntimeError("gemini unavailable")
            generate_claude.return_value = "claude rp"

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

        generate_claude.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
