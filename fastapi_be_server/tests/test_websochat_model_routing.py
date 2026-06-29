import json
import unittest
from unittest.mock import AsyncMock, patch

from app.exceptions import CustomResponseException
from app.services.websochat import (
    websochat_game_memory,
    websochat_qa_executor,
    websochat_rp_renderer,
    websochat_service,
)
from app.services.websochat.websochat_planner import _build_websochat_qa_plan


class _FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _FakeMappings(self._rows)


class _FakeRpContextDb:
    def __init__(self, *, canonical_profile_ready=True):
        self.exact_summary_requests = []
        self.canonical_profile_ready = canonical_profile_ready

    async def execute(self, statement, params=None):
        query = str(statement)
        params = params or {}
        if "summary_type = 'character_inventory_v3'" in query:
            return _FakeResult(
                [
                    {
                        "scopeKey": "character:아델리트",
                        "summaryText": json.dumps(
                            {
                                "canonical_character_key": "character:아델리트",
                                "source_character_keys": ["protagonist:named:아델리트", "named:아델리트"],
                                "display_name": "아델리트",
                                "aliases": ["아델리트"],
                                "is_protagonist": True,
                                "distinct_episode_count": 4,
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
            )
        if "summary_type = 'relation_inventory'" in query:
            return _FakeResult([])
        summary_type = params.get("summary_type")
        scope_key = params.get("scope_key")
        self.exact_summary_requests.append((summary_type, scope_key))
        profile_scope_key = "character:아델리트" if self.canonical_profile_ready else "protagonist:named:아델리트"
        examples_scope_key = "character:아델리트" if self.canonical_profile_ready else "protagonist:named:아델리트"
        if summary_type == "character_rp_profile" and scope_key == profile_scope_key:
            return _FakeResult(
                [
                    {
                        "summaryId": 10,
                        "summaryText": json.dumps(
                            {
                                "display_name": "아델리트",
                                "speech_style": {"tone": ["차분"]},
                                "personality_core": ["상처를 숨김"],
                                "baseline_attitude": "경계",
                            },
                            ensure_ascii=False,
                        ),
                        "episodeFrom": None,
                        "episodeTo": None,
                    }
                ]
            )
        if summary_type == "character_rp_examples" and scope_key == examples_scope_key:
            return _FakeResult(
                [
                    {
                        "summaryId": 11,
                        "summaryText": json.dumps(
                            {
                                "examples": [
                                    {
                                        "episode_no": 1,
                                        "source_kind": "dialogue",
                                        "text": "나는 아직 여기서 끝낼 생각 없어.",
                                        "confidence": 0.9,
                                    }
                                ]
                            },
                            ensure_ascii=False,
                        ),
                        "episodeFrom": None,
                        "episodeTo": None,
                    }
                ]
            )
        return _FakeResult([])


class _FakeInventoryOnlyRpContextDb:
    async def execute(self, statement, params=None):
        query = str(statement)
        params = params or {}
        if "summary_type = 'character_inventory_v3'" in query:
            return _FakeResult([])
        if "summary_type = 'relation_inventory'" in query:
            return _FakeResult(
                [
                    {
                        "scopeKey": "protagonist:named:아델리트->named:제일황자",
                        "summaryText": json.dumps(
                            {
                                "source_key": "protagonist:named:아델리트",
                                "target_key": "named:제일황자",
                                "source_display_name": "아델리트",
                                "target_display_name": "제일황자",
                                "dominant_relation_tags": ["간호", "경계"],
                                "distinct_episode_count": 5,
                                "edge_count": 7,
                                "latest_seen_episode_no": 12,
                            },
                            ensure_ascii=False,
                        ),
                    },
                    {
                        "scopeKey": "named:율리아나->protagonist:named:아델리트",
                        "summaryText": json.dumps(
                            {
                                "source_key": "named:율리아나",
                                "target_key": "protagonist:named:아델리트",
                                "source_display_name": "율리아나",
                                "target_display_name": "아델리트",
                                "dominant_relation_tags": ["견제"],
                                "distinct_episode_count": 2,
                                "edge_count": 2,
                                "latest_seen_episode_no": 8,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ]
            )

        summary_type = params.get("summary_type")
        scope_key = params.get("scope_key")
        if summary_type == "character_inventory" and scope_key == "protagonist:named:아델리트":
            return _FakeResult(
                [
                    {
                        "summaryId": 21,
                        "summaryText": json.dumps(
                            {
                                "display_name": "아델리트",
                                "aliases": ["아델리트"],
                                "is_protagonist": True,
                                "first_seen_episode_no": 1,
                                "latest_seen_episode_no": 12,
                                "distinct_episode_count": 11,
                                "relation_presence": "high",
                                "action_presence": "high",
                                "dominant_affect_tags": ["냉정", "경계"],
                                "dominant_action_tags": ["명령", "돌봄"],
                            },
                            ensure_ascii=False,
                        ),
                        "episodeFrom": None,
                        "episodeTo": None,
                    }
                ]
            )
        return _FakeResult([])


class _FakeUnsafeInventorySeedDb:
    async def execute(self, statement, params=None):
        query = str(statement)
        if "summary_type = 'character_inventory_v3'" in query:
            return _FakeResult(
                [
                    {
                        "scopeKey": "character:산군",
                        "summaryText": json.dumps(
                            {
                                "canonical_character_key": "character:산군",
                                "source_character_keys": ["protagonist:named:산군"],
                                "display_name": "대전사",
                                "aliases": ["대전사", "산군"],
                                "is_protagonist": True,
                                "distinct_episode_count": 20,
                                "display_safety": {"status": "review", "reason": "stable_role_identity"},
                                "public_chat_eligible": False,
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
            )
        if "summary_type = 'character_inventory'" in query:
            return _FakeResult(
                [
                    {
                        "scopeKey": "protagonist:named:산군",
                        "summaryText": json.dumps(
                            {
                                "display_name": "산군",
                                "aliases": ["산군", "대전사"],
                                "is_protagonist": True,
                                "distinct_episode_count": 20,
                                "voice_evidence_count": 8,
                                "summary_mention_count": 20,
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
            )
        if "summary_type = 'relation_inventory'" in query:
            return _FakeResult([])
        return _FakeResult([])


class _FakeUnsafeInventoryV3WithLegacyRpDb:
    async def execute(self, statement, params=None):
        query = str(statement)
        params = params or {}
        if "summary_type = 'character_inventory_v3'" in query:
            return _FakeResult(
                [
                    {
                        "scopeKey": "character:산군",
                        "summaryText": json.dumps(
                            {
                                "canonical_character_key": "character:산군",
                                "source_character_keys": ["protagonist:named:산군"],
                                "display_name": "대전사",
                                "aliases": ["대전사", "산군"],
                                "is_protagonist": True,
                                "distinct_episode_count": 20,
                                "display_safety": {"status": "review", "reason": "stable_role_identity"},
                                "public_chat_eligible": False,
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
            )
        if "summary_type = 'character_inventory'" in query:
            return _FakeResult(
                [
                    {
                        "scopeKey": "protagonist:named:산군",
                        "summaryText": json.dumps(
                            {
                                "display_name": "산군",
                                "aliases": ["산군", "대전사"],
                                "is_protagonist": True,
                                "distinct_episode_count": 20,
                                "voice_evidence_count": 8,
                                "summary_mention_count": 20,
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
            )
        if "summary_type = 'relation_inventory'" in query:
            return _FakeResult([])

        summary_type = params.get("summary_type")
        scope_key = params.get("scope_key")
        if summary_type == "character_rp_profile" and scope_key == "protagonist:named:산군":
            return _FakeResult(
                [
                    {
                        "summaryId": 31,
                        "summaryText": json.dumps(
                            {
                                "display_name": "산군",
                                "speech_style": {"tone": ["거칠고 단호함"]},
                                "personality_core": ["생존 본능이 강함"],
                                "baseline_attitude": "경계",
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
            )
        if summary_type == "character_rp_examples" and scope_key == "protagonist:named:산군":
            return _FakeResult(
                [
                    {
                        "summaryId": 32,
                        "summaryText": json.dumps(
                            {
                                "examples": [
                                    {
                                        "episode_no": 3,
                                        "source_kind": "dialogue",
                                        "text": "나는 물러서지 않는다.",
                                        "confidence": 0.8,
                                    }
                                ]
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
            )
        return _FakeResult([])


class WebsochatModelRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_inventory_rp_eligibility_respects_public_chat_gate_without_breaking_legacy_payload(self):
        self.assertFalse(
            websochat_service._is_websochat_inventory_rp_eligible(
                {
                    "display_name": "대전사",
                    "entity_kind": "person",
                    "distinct_episode_count": 20,
                    "voice_evidence_count": 8,
                    "summary_mention_count": 20,
                    "display_safety": {"status": "review", "reason": "stable_role_identity"},
                    "public_chat_eligible": False,
                }
            )
        )
        self.assertTrue(
            websochat_service._is_websochat_inventory_rp_eligible(
                {
                    "display_name": "백이현",
                    "entity_kind": "person",
                    "distinct_episode_count": 3,
                    "voice_evidence_count": 2,
                    "summary_mention_count": 3,
                }
            )
        )

    async def test_legacy_rp_scope_loads_canonical_inventory_v3_profile_first(self):
        db = _FakeRpContextDb()

        with patch.object(
            websochat_service,
            "_build_websochat_rp_trajectory_context",
            new_callable=AsyncMock,
        ) as build_trajectory:
            build_trajectory.return_value = None
            context = await websochat_service._load_websochat_rp_context(
                product_row={"productId": 1182, "title": "테스트", "latestEpisodeNo": 5},
                session_memory={
                    "active_mode": "rp",
                    "active_character": "protagonist:named:아델리트",
                    "active_character_label": "아델리트",
                    "rp_mode": "free",
                },
                db=db,
            )

        self.assertIsNotNone(context)
        self.assertEqual(context["active_character"], "character:아델리트")
        self.assertEqual(context["display_name"], "아델리트")
        self.assertEqual(context["examples"][0]["text"], "나는 아직 여기서 끝낼 생각 없어.")
        self.assertIn(("character_rp_profile", "character:아델리트"), db.exact_summary_requests)
        self.assertEqual(db.exact_summary_requests[0], ("character_rp_profile", "character:아델리트"))

    async def test_legacy_rp_scope_keeps_legacy_profile_when_canonical_profile_is_missing(self):
        db = _FakeRpContextDb(canonical_profile_ready=False)

        with patch.object(
            websochat_service,
            "_build_websochat_rp_trajectory_context",
            new_callable=AsyncMock,
        ) as build_trajectory:
            build_trajectory.return_value = None
            context = await websochat_service._load_websochat_rp_context(
                product_row={"productId": 1182, "title": "테스트", "latestEpisodeNo": 5},
                session_memory={
                    "active_mode": "rp",
                    "active_character": "protagonist:named:아델리트",
                    "active_character_label": "아델리트",
                    "rp_mode": "free",
                },
                db=db,
            )

        self.assertIsNotNone(context)
        self.assertEqual(context["active_character"], "character:아델리트")
        self.assertEqual(context["display_name"], "아델리트")
        self.assertIn(("character_rp_profile", "character:아델리트"), db.exact_summary_requests)
        self.assertIn(("character_rp_profile", "protagonist:named:아델리트"), db.exact_summary_requests)

    async def test_inventory_only_rp_context_keeps_character_grounding(self):
        db = _FakeInventoryOnlyRpContextDb()

        with patch.object(
            websochat_service,
            "_build_websochat_rp_trajectory_context",
            new_callable=AsyncMock,
        ) as build_trajectory:
            build_trajectory.return_value = {
                "anchor_episode_no": 12,
                "anchor_summary_text": "아델리트는 제일황자의 처소에서 경계를 늦추지 않는다.",
                "trajectory_history": [
                    {
                        "episode_no": 8,
                        "summary_text": "아델리트는 율리아나의 견제를 받으면서도 침착하게 대응한다.",
                    }
                ],
            }
            context = await websochat_service._load_websochat_rp_context(
                product_row={"productId": 1182, "title": "테스트", "latestEpisodeNo": 12},
                session_memory={
                    "active_mode": "rp",
                    "active_character": "protagonist:named:아델리트",
                    "active_character_label": "아델리트",
                    "rp_mode": "free",
                    "read_episode_to": 12,
                },
                db=db,
            )

        self.assertIsNotNone(context)
        self.assertEqual(context["display_name"], "아델리트")
        self.assertTrue(context["speech_style"].get("tone"))
        self.assertIn("냉정", context["personality_core"])
        self.assertIn("제일황자", "\n".join(context["character_relation_lines"]))
        self.assertIn("아델리트 -> 제일황자", "\n".join(context["character_relation_lines"]))
        self.assertIn("율리아나 -> 아델리트", "\n".join(context["character_relation_lines"]))
        self.assertEqual(context["anchor_episode_no"], 12)

        prompt = websochat_rp_renderer.build_websochat_rp_system_prompt(
            product_row={"productId": 1182, "title": "테스트", "latestEpisodeNo": 12},
            rp_context=context,
            recent_messages=[],
        )
        self.assertIn("[관계 맥락]", prompt)
        self.assertIn("제일황자", prompt)

    async def test_scene_rp_context_does_not_load_future_episode_over_read_scope(self):
        db = _FakeRpContextDb()

        with (
            patch.object(
                websochat_service,
                "_build_websochat_rp_trajectory_context",
                new_callable=AsyncMock,
            ) as build_trajectory,
            patch.object(
                websochat_service,
                "_get_websochat_summary_candidates",
                new_callable=AsyncMock,
            ) as get_summary_candidates,
            patch.object(
                websochat_service,
                "_get_websochat_episode_contents",
                new_callable=AsyncMock,
            ) as get_episode_contents,
        ):
            build_trajectory.return_value = None
            get_summary_candidates.return_value = [
                {"summaryText": "5화의 미래 장면이 들어오면 안 된다."}
            ]
            get_episode_contents.return_value = [
                {"episodeNo": 5, "content": "미래 회차 원문"}
            ]
            context = await websochat_service._load_websochat_rp_context(
                product_row={"productId": 1182, "title": "테스트", "latestEpisodeNo": 10},
                session_memory={
                    "active_mode": "rp",
                    "active_character": "protagonist:named:아델리트",
                    "active_character_label": "아델리트",
                    "rp_mode": "scene",
                    "scene_episode_no": 5,
                    "read_episode_to": 3,
                },
                db=db,
            )

        self.assertIsNotNone(context)
        self.assertNotIn("scene_episode_no", context)
        self.assertNotIn("scene_summary_text", context)
        self.assertNotIn("scene_source_text", context)
        get_summary_candidates.assert_not_awaited()
        get_episode_contents.assert_not_awaited()

    async def test_unsafe_inventory_v3_does_not_seed_new_rp_context_without_profile(self):
        db = _FakeUnsafeInventorySeedDb()

        with patch.object(
            websochat_service,
            "_build_websochat_rp_trajectory_context",
            new_callable=AsyncMock,
        ) as build_trajectory:
            build_trajectory.return_value = None
            context = await websochat_service._load_websochat_rp_context(
                product_row={"productId": 1108, "title": "산군이 되었다", "latestEpisodeNo": 20},
                session_memory={
                    "active_mode": "rp",
                    "active_character": "protagonist:named:산군",
                    "active_character_label": "산군",
                    "rp_mode": "free",
                    "read_episode_to": 20,
                },
                db=db,
            )

        self.assertIsNone(context)

    async def test_unsafe_inventory_v3_blocks_legacy_profile_examples_bypass(self):
        db = _FakeUnsafeInventoryV3WithLegacyRpDb()

        with patch.object(
            websochat_service,
            "_build_websochat_rp_trajectory_context",
            new_callable=AsyncMock,
        ) as build_trajectory:
            build_trajectory.return_value = None
            context = await websochat_service._load_websochat_rp_context(
                product_row={"productId": 1108, "title": "산군이 되었다", "latestEpisodeNo": 20},
                session_memory={
                    "active_mode": "rp",
                    "active_character": "protagonist:named:산군",
                    "active_character_label": "산군",
                    "rp_mode": "free",
                    "read_episode_to": 20,
                },
                db=db,
            )

        self.assertIsNone(context)

    async def test_unsafe_inventory_v3_blocks_plain_name_legacy_resolution_bypass(self):
        db = _FakeUnsafeInventoryV3WithLegacyRpDb()

        with patch.object(
            websochat_service,
            "_build_websochat_rp_trajectory_context",
            new_callable=AsyncMock,
        ) as build_trajectory:
            build_trajectory.return_value = None
            context = await websochat_service._load_websochat_rp_context(
                product_row={"productId": 1108, "title": "산군이 되었다", "latestEpisodeNo": 20},
                session_memory={
                    "active_mode": "rp",
                    "active_character": "산군",
                    "active_character_label": "산군",
                    "rp_mode": "free",
                    "read_episode_to": 20,
                },
                db=db,
            )

        self.assertIsNone(context)

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

    async def test_forced_rp_without_context_does_not_fallback_to_qa(self):
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
            "reply": "QA로 새면 안 됩니다.",
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
            load_rp_context.return_value = None
            get_recent_messages.return_value = []
            resolve_intent.return_value = ("factual", False, "general")
            resolve_corrections.return_value = []
            assemble_context.return_value = evidence_bundle
            execute_qa.return_value = qa_result

            reply, model_used, route_mode, fallback_used, intent, next_memory = await websochat_service._generate_websochat_reply(
                session_id=123,
                session_memory={
                    "read_scope_state": "known",
                    "read_episode_to": 1,
                    "active_mode": "rp",
                    "active_character": "named:test",
                    "active_character_label": "테스트",
                    "rp_mode": "free",
                },
                product_row=product_row,
                user_prompt="안녕",
                user_id=1,
                db=AsyncMock(),
                forced_route="rp",
            )

        self.assertIn("테스트", reply)
        self.assertEqual(model_used, "system")
        self.assertEqual(route_mode, "rp:unavailable")
        self.assertFalse(fallback_used)
        self.assertEqual(intent, "rp_unavailable")
        self.assertIsNone(next_memory)
        get_recent_messages.assert_not_awaited()
        execute_qa.assert_not_awaited()

    async def test_active_rp_session_without_context_does_not_fallback_to_qa(self):
        product_row = {"productId": 1, "title": "테스트", "latestEpisodeNo": 5}
        qa_result = {
            "reply": "기존 RP 세션도 QA로 새면 안 됩니다.",
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
                "execute_websochat_qa",
                new_callable=AsyncMock,
            ) as execute_qa,
        ):
            load_rp_context.return_value = None
            get_recent_messages.return_value = []
            execute_qa.return_value = qa_result

            reply, model_used, route_mode, fallback_used, intent, next_memory = await websochat_service._generate_websochat_reply(
                session_id=123,
                session_memory={
                    "read_scope_state": "known",
                    "read_episode_to": 1,
                    "active_mode": "rp",
                    "active_character": "named:test",
                    "active_character_label": "테스트",
                    "rp_mode": "free",
                },
                product_row=product_row,
                user_prompt="아직 있어?",
                user_id=1,
                db=AsyncMock(),
            )

        self.assertIn("테스트", reply)
        self.assertEqual(model_used, "system")
        self.assertEqual(route_mode, "rp:unavailable")
        self.assertFalse(fallback_used)
        self.assertEqual(intent, "rp_unavailable")
        self.assertIsNone(next_memory)
        get_recent_messages.assert_not_awaited()
        execute_qa.assert_not_awaited()

    async def test_active_rp_session_without_rp_mode_does_not_fallback_to_qa(self):
        product_row = {"productId": 1, "title": "테스트", "latestEpisodeNo": 5}
        qa_result = {
            "reply": "rp_mode 누락 세션도 QA로 새면 안 됩니다.",
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
                "execute_websochat_qa",
                new_callable=AsyncMock,
            ) as execute_qa,
        ):
            load_rp_context.return_value = None
            get_recent_messages.return_value = []
            execute_qa.return_value = qa_result

            reply, model_used, route_mode, fallback_used, intent, next_memory = await websochat_service._generate_websochat_reply(
                session_id=123,
                session_memory={
                    "read_scope_state": "known",
                    "read_episode_to": 1,
                    "active_mode": "rp",
                    "active_character": "named:test",
                    "active_character_label": "테스트",
                },
                product_row=product_row,
                user_prompt="아직 있어?",
                user_id=1,
                db=AsyncMock(),
            )

        self.assertIn("테스트", reply)
        self.assertEqual(model_used, "system")
        self.assertEqual(route_mode, "rp:unavailable")
        self.assertFalse(fallback_used)
        self.assertEqual(intent, "rp_unavailable")
        self.assertIsNone(next_memory)
        get_recent_messages.assert_not_awaited()
        execute_qa.assert_not_awaited()

    async def test_exact_recall_uses_grouped_episode_content_field(self):
        with (
            patch.object(
                websochat_service,
                "_resolve_websochat_rp_recall_need",
                new_callable=AsyncMock,
            ) as resolve_recall_need,
            patch.object(
                websochat_service,
                "_get_websochat_summary_candidates",
                new_callable=AsyncMock,
            ) as get_summary_candidates,
            patch.object(
                websochat_service,
                "_get_websochat_episode_contents",
                new_callable=AsyncMock,
            ) as get_episode_contents,
            patch.object(
                websochat_service,
                "_search_websochat_episode_contents",
                new_callable=AsyncMock,
            ) as search_episode_contents,
        ):
            resolve_recall_need.return_value = (True, "검")
            get_summary_candidates.return_value = []
            get_episode_contents.return_value = [
                {"episodeNo": 2, "content": "테스트가 검을 들었다."}
            ]
            search_episode_contents.return_value = []

            context = await websochat_service._build_websochat_rp_exact_recall_context(
                product_row={"productId": 1, "title": "테스트", "latestEpisodeNo": 5},
                user_prompt="그때 뭘 들었지?",
                recent_messages=[],
                rp_context={
                    "display_name": "테스트",
                    "anchor_episode_no": 2,
                    "trajectory_history": [],
                    "session_memory": {"read_episode_to": 3},
                },
                db=AsyncMock(),
            )

        self.assertIn("raw_recall_context", context)
        self.assertIn("검을 들었다", context["raw_recall_context"])
        search_episode_contents.assert_not_awaited()

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
