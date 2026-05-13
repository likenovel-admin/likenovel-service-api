import argparse
import asyncio
import json
import os
import unittest
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import InvalidRequestError


class AiReaderAgentPhase1Test(unittest.TestCase):
    def test_parse_llm_decision_accepts_json_fenced_response(self):
        from app.services.ai import reader_agent_decision_service as service

        raw = """```json
        {
          "continue_reading": true,
          "next_episode_count": 1,
          "drop_product": false,
          "bookmark_action": "add",
          "recommend_action": "press",
          "evaluation": {"should_evaluate": true, "eval_code": "verypositive"},
          "bayesian_update": {
            "continue_next_episode": {"prior": 0.61, "posterior": 0.74},
            "recommend": {"prior": 0.42, "posterior": 0.58},
            "evaluate": {"prior": 0.30, "posterior": 0.51}
          },
          "taste_delta": {"positive": ["빠른 전개", "성장형"], "negative": []},
          "reason": "다음 갈등이 궁금하고 주인공 성장이 취향과 맞음"
        }
        ```"""

        decision = service.parse_llm_decision(raw)

        self.assertTrue(decision.continue_reading)
        self.assertEqual(decision.next_episode_count, 1)
        self.assertEqual(decision.bookmark_action, "add")
        self.assertEqual(decision.recommend_action, "press")
        self.assertEqual(decision.eval_code, "verypositive")
        self.assertEqual(
            decision.bayesian_update["continue_next_episode"]["prior"],
            0.61,
        )
        self.assertEqual(
            decision.bayesian_update["continue_next_episode"]["posterior"],
            0.74,
        )
        self.assertIn("빠른 전개", decision.taste_delta["positive"])

    def test_parse_llm_decision_clamps_out_of_range_bayesian_probability(self):
        from app.services.ai import reader_agent_decision_service as service

        decision = service.parse_llm_decision(
            {
                "continue_reading": True,
                "next_episode_count": 1,
                "drop_product": False,
                "bookmark_action": "none",
                "recommend_action": "press",
                "evaluation": {"should_evaluate": False, "eval_code": None},
                "bayesian_update": {
                    "recommend": {"prior": 1.2, "posterior": -0.1},
                },
                "taste_delta": {"positive": [], "negative": []},
                "reason": "추천 확률 숫자가 범위를 벗어났지만 행동 판단은 유효함",
            }
        )

        self.assertEqual(decision.bayesian_update["recommend"]["prior"], 1.0)
        self.assertEqual(decision.bayesian_update["recommend"]["posterior"], 0.0)

    def test_parse_llm_decision_rejects_multi_episode_followup(self):
        from app.services.ai import reader_agent_decision_service as service

        with self.assertRaises(service.InvalidReaderDecisionError):
            service.parse_llm_decision(
                {
                    "continue_reading": True,
                    "next_episode_count": 2,
                    "drop_product": False,
                    "bookmark_action": "none",
                    "recommend_action": "none",
                    "evaluation": {"should_evaluate": False, "eval_code": None},
                    "taste_delta": {"positive": [], "negative": []},
                    "reason": "두 화 더 읽고 싶음",
                }
            )

    def test_invalid_llm_decision_raises_without_creating_actions(self):
        from app.services.ai import reader_agent_decision_service as service

        with self.assertRaises(service.InvalidReaderDecisionError):
            service.parse_llm_decision('{"bookmark_action": "toggle"}')

    def test_inconsistent_llm_decision_raises_before_action_generation(self):
        from app.services.ai import reader_agent_decision_service as service

        with self.assertRaises(service.InvalidReaderDecisionError):
            service.parse_llm_decision(
                {
                    "continue_reading": True,
                    "next_episode_count": 1,
                    "drop_product": True,
                    "bookmark_action": "none",
                    "recommend_action": "none",
                    "evaluation": {"should_evaluate": False, "eval_code": None},
                    "taste_delta": {"positive": [], "negative": []},
                    "reason": "drop and continue conflict",
                }
            )

        with self.assertRaises(service.InvalidReaderDecisionError):
            service.parse_llm_decision(
                {
                    "continue_reading": False,
                    "next_episode_count": 1,
                    "drop_product": False,
                    "bookmark_action": "none",
                    "recommend_action": "none",
                    "evaluation": {"should_evaluate": False, "eval_code": None},
                    "taste_delta": {"positive": [], "negative": []},
                    "reason": "next episode without continue",
                }
            )

    def test_build_reader_decision_prompt_requires_human_like_json_decision(self):
        from app.services.ai import reader_agent_decision_service as service

        system_prompt, user_prompt = service.build_reader_decision_prompt(
            {
                "agent": {"age_group": "30s", "gender": "M", "persona": {"patience": 0.4}},
                "product": {
                    "product_id": 200,
                    "title": "테스트 작품",
                    "early_episode_summary_text": "초반 전투",
                },
                "episode": {"episode_id": 300, "episode_no": 1},
                "state": {"read_episode_count": 1, "bookmarked_yn": "N"},
            }
        )

        self.assertIn("사람 독자처럼 판단", system_prompt)
        self.assertIn("JSON", system_prompt)
        self.assertIn("continue_reading", system_prompt)
        self.assertIn("bookmark_action", system_prompt)
        self.assertIn("recommend_action", system_prompt)
        self.assertIn("evaluation", system_prompt)
        self.assertIn("action_affordances", system_prompt)
        self.assertIn("bayesian_update", system_prompt)
        self.assertIn("사전확률", system_prompt)
        self.assertIn("사후확률", system_prompt)
        self.assertIn("조건부확률", system_prompt)
        self.assertIn("0.1", system_prompt)
        self.assertIn("suggested=true", system_prompt)
        self.assertIn("suggested=false는 금지가 아니다", system_prompt)
        self.assertIn("Bayesian 사후확률", system_prompt)
        self.assertIn("추천은 선호작보다 가벼운 긍정 신호", system_prompt)
        self.assertIn("0 또는 1", system_prompt)
        self.assertIn("1~10화 초반 요약", system_prompt)
        self.assertIn("테스트 작품", user_prompt)

    def test_request_reader_decision_calls_llm_and_parses_json(self):
        from app.services.ai import reader_agent_decision_service as service

        async def fake_llm(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
            self.assertIn("continue_reading", system_prompt)
            self.assertIn("작품/회차/독자 스냅샷", user_prompt)
            self.assertEqual(max_tokens, service.READER_DECISION_MAX_TOKENS)
            return """
            {
              "continue_reading": false,
              "next_episode_count": 0,
              "drop_product": true,
              "bookmark_action": "remove",
              "recommend_action": "none",
              "evaluation": {"should_evaluate": true, "eval_code": "neutral"},
              "taste_delta": {"positive": [], "negative": ["느린 전개"]},
              "reason": "취향보다 전개가 느려서 여기서 멈춤"
            }
            """

        decision = asyncio.run(
            service.request_reader_decision(
                {"agent": {"age_group": "20s"}, "product": {"product_id": 200}},
                llm_call=fake_llm,
            )
        )

        self.assertTrue(decision.drop_product)
        self.assertEqual(decision.bookmark_action, "remove")
        self.assertEqual(decision.eval_code, "neutral")

    def test_request_reader_decision_retries_invalid_json_once(self):
        from app.services.ai import reader_agent_decision_service as service

        calls = {"count": 0}

        async def fake_llm(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
            calls["count"] += 1
            if calls["count"] == 1:
                return '{"continue_reading": true, "reason": "끊긴 응답'
            return """
            {
              "continue_reading": true,
              "next_episode_count": 1,
              "drop_product": false,
              "bookmark_action": "none",
              "recommend_action": "press",
              "evaluation": {"should_evaluate": false, "eval_code": null},
              "taste_delta": {"positive": ["초반 훅"], "negative": []},
              "reason": "초반 훅이 살아 있어 다음 회차를 본다"
            }
            """

        decision = asyncio.run(
            service.request_reader_decision(
                {"agent": {"age_group": "30s"}, "product": {"product_id": 200}},
                llm_call=fake_llm,
            )
        )

        self.assertEqual(calls["count"], 2)
        self.assertTrue(decision.continue_reading)
        self.assertEqual(decision.recommend_action, "press")

    def test_default_reader_llm_call_uses_openrouter_chat_completions(self):
        from app.services.ai import reader_agent_decision_service as service

        captured = {}
        raw_decision = """
        {
          "continue_reading": true,
          "next_episode_count": 1,
          "drop_product": false,
          "bookmark_action": "none",
          "recommend_action": "none",
          "evaluation": {"should_evaluate": false, "eval_code": null},
          "taste_delta": {"positive": ["테이밍"], "negative": []},
          "reason": "다음 회차가 궁금함"
        }
        """

        class FakeResponse:
            status_code = 200

            def json(self):
                return {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": raw_decision},
                        }
                    ]
                }

        class FakeAsyncClient:
            def __init__(self, *, timeout):
                captured["timeout"] = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, *, headers, json):
                captured["url"] = url
                captured["headers"] = headers
                captured["payload"] = json
                return FakeResponse()

        with patch.object(service.settings, "OPENROUTER_API_KEY", "openrouter-key"):
            with patch.object(service.settings, "OPENROUTER_BASE_URL", "https://openrouter.test/api/v1"):
                with patch.object(service.settings, "AI_READER_OPENROUTER_MODEL", "deepseek/deepseek-v3.2"):
                    with patch.object(service.settings, "AI_READER_OPENROUTER_PROVIDER_ONLY", ""):
                        with patch.object(service.settings, "AI_READER_OPENROUTER_TEMPERATURE", 0.4):
                            with patch.object(service.settings, "AI_READER_OPENROUTER_TIMEOUT_SECONDS", 12.0):
                                with patch.object(service.httpx, "AsyncClient", FakeAsyncClient):
                                    raw = asyncio.run(
                                        service._default_llm_call(
                                            "system prompt",
                                            "user prompt",
                                            123,
                                        )
                                    )

        self.assertEqual(raw, raw_decision.strip())
        self.assertEqual(captured["timeout"], 12.0)
        self.assertEqual(captured["url"], "https://openrouter.test/api/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer openrouter-key")
        self.assertEqual(captured["headers"]["Content-Type"], "application/json")
        self.assertEqual(captured["headers"]["X-Title"], "LikeNovel AI Reader Agent")
        self.assertEqual(captured["payload"]["model"], "deepseek/deepseek-v3.2")
        self.assertEqual(captured["payload"]["temperature"], 0.4)
        self.assertEqual(captured["payload"]["max_tokens"], 123)
        self.assertEqual(
            captured["payload"]["messages"],
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "user prompt"},
            ],
        )
        self.assertNotIn("anthropic", json.dumps(captured["payload"]).lower())

    def test_default_reader_llm_call_retries_empty_openrouter_choices_once(self):
        from app.services.ai import reader_agent_decision_service as service

        calls = {"count": 0}
        raw_decision = """
        {
          "continue_reading": true,
          "next_episode_count": 1,
          "drop_product": false,
          "bookmark_action": "none",
          "recommend_action": "none",
          "evaluation": {"should_evaluate": false, "eval_code": null},
          "taste_delta": {"positive": ["초반 훅"], "negative": []},
          "reason": "다음 회차가 궁금함"
        }
        """

        class FakeResponse:
            status_code = 200

            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

        class FakeAsyncClient:
            def __init__(self, *, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, *, headers, json):
                calls["count"] += 1
                if calls["count"] == 1:
                    return FakeResponse({"choices": []})
                return FakeResponse(
                    {
                        "choices": [
                            {
                                "finish_reason": "stop",
                                "message": {"content": raw_decision},
                            }
                        ]
                    }
                )

        with patch.object(service.settings, "OPENROUTER_API_KEY", "openrouter-key"):
            with patch.object(service.settings, "OPENROUTER_BASE_URL", "https://openrouter.test/api/v1"):
                with patch.object(service.settings, "AI_READER_OPENROUTER_MODEL", "deepseek/deepseek-v3.2"):
                    with patch.object(service.settings, "AI_READER_OPENROUTER_PROVIDER_ONLY", ""):
                        with patch.object(service.httpx, "AsyncClient", FakeAsyncClient):
                            raw = asyncio.run(
                                service._default_llm_call(
                                    "system prompt",
                                    "user prompt",
                                    123,
                                )
                            )

        self.assertEqual(calls["count"], 2)
        self.assertEqual(raw, raw_decision.strip())

    def test_build_action_intents_generates_stable_idempotency_keys(self):
        from app.services.ai import reader_agent_decision_service as service

        decision = service.ReaderLlmDecision(
            continue_reading=True,
            next_episode_count=1,
            drop_product=False,
            bookmark_action="add",
            recommend_action="press",
            should_evaluate=True,
            eval_code="verypositive",
            taste_delta={"positive": [], "negative": []},
            reason="liked",
        )
        context = service.ReaderActionContext(
            agent_id=7,
            user_id=100,
            session_id="ai-session-1",
            product_id=200,
            episode_id=300,
        )

        actions = service.build_action_intents(decision, context)
        repeated = service.build_action_intents(decision, context)

        self.assertEqual(
            [(a.action_type, a.target_value) for a in actions],
            [
                ("read", ""),
                ("next_episode", "1"),
                ("bookmark", "Y"),
                ("recommend", "Y"),
                ("evaluate", "verypositive"),
            ],
        )
        self.assertEqual(
            [a.idempotency_key for a in actions],
            [a.idempotency_key for a in repeated],
        )
        self.assertEqual(len({a.idempotency_key for a in actions}), len(actions))

    def test_active_action_scope_dedupes_only_current_pending_intent(self):
        from app.services.ai import reader_agent_decision_service as service

        first_session_read = service.build_active_action_scope_key(
            agent_id=7,
            user_id=100,
            product_id=200,
            episode_id=300,
            action_type="read",
            target_value="",
        )
        second_session_same_read = service.build_active_action_scope_key(
            agent_id=7,
            user_id=100,
            product_id=200,
            episode_id=300,
            action_type="read",
            target_value="",
        )
        next_episode_read = service.build_active_action_scope_key(
            agent_id=7,
            user_id=100,
            product_id=200,
            episode_id=301,
            action_type="read",
            target_value="",
        )
        bookmark_from_episode_one = service.build_active_action_scope_key(
            agent_id=7,
            user_id=100,
            product_id=200,
            episode_id=300,
            action_type="bookmark",
            target_value="Y",
        )
        bookmark_from_episode_two = service.build_active_action_scope_key(
            agent_id=7,
            user_id=100,
            product_id=200,
            episode_id=301,
            action_type="bookmark",
            target_value="Y",
        )
        positive_evaluation = service.build_active_action_scope_key(
            agent_id=7,
            user_id=100,
            product_id=200,
            episode_id=300,
            action_type="evaluate",
            target_value="positive",
        )
        verypositive_evaluation = service.build_active_action_scope_key(
            agent_id=7,
            user_id=100,
            product_id=200,
            episode_id=300,
            action_type="evaluate",
            target_value="verypositive",
        )

        self.assertEqual(first_session_read, second_session_same_read)
        self.assertNotEqual(first_session_read, next_episode_read)
        self.assertEqual(bookmark_from_episode_one, bookmark_from_episode_two)
        self.assertEqual(positive_evaluation, verypositive_evaluation)

    def test_build_action_intents_reads_current_episode_before_drop(self):
        from app.services.ai import reader_agent_decision_service as service

        decision = service.ReaderLlmDecision(
            continue_reading=False,
            next_episode_count=0,
            drop_product=True,
            bookmark_action="remove",
            recommend_action="none",
            should_evaluate=False,
            eval_code=None,
            taste_delta={"positive": [], "negative": ["느린전개"]},
            reason="drop",
        )
        context = service.ReaderActionContext(
            agent_id=7,
            user_id=100,
            session_id="ai-session-1",
            product_id=200,
            episode_id=300,
        )

        actions = service.build_action_intents(decision, context)

        self.assertEqual(
            [(a.action_type, a.target_value) for a in actions],
            [("read", ""), ("drop", "Y"), ("bookmark", "N")],
        )

    def test_phase1_migration_declares_agent_and_action_queue_tables(self):
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist/init/87-create-ai-reader-agent-phase1-tables.sql"
        )

        ddl = migration_path.read_text()

        self.assertIn("CREATE TABLE IF NOT EXISTS tb_ai_reader_agent", ddl)
        self.assertIn("CREATE TABLE IF NOT EXISTS tb_ai_reader_action_queue", ddl)
        self.assertIn("UNIQUE KEY uk_ai_reader_agent_user", ddl)
        self.assertIn("UNIQUE KEY uk_ai_reader_action_idempotency", ddl)
        self.assertIn("active_scope_key CHAR(64) NULL", ddl)
        self.assertIn("UNIQUE KEY uk_ai_reader_action_active_scope", ddl)
        self.assertIn("UNIQUE KEY uk_ai_reader_llm_decision_session", ddl)
        self.assertIn("KEY idx_ai_reader_llm_decision_request", ddl)
        self.assertNotIn("UNIQUE KEY uk_ai_reader_llm_decision_request", ddl)
        self.assertIn("ai_unrecommend_count INT NOT NULL DEFAULT 0", ddl)
        self.assertIn("KEY idx_ai_reader_action_queue_stale", ddl)
        self.assertIn("(status, locked_at, attempt_count, ai_reader_action_id)", ddl)
        self.assertIn("KEY idx_ai_reader_daily_schedule_stale", ddl)
        self.assertIn(
            "status, locked_at, active_start_at, active_end_at, ai_reader_schedule_id",
            " ".join(ddl.split()),
        )
        self.assertIn("locked_by VARCHAR(100) NULL", ddl)
        self.assertIn("locked_at TIMESTAMP NULL", ddl)
        self.assertIn("error_message VARCHAR(1000) NULL", ddl)

    def test_active_scope_incremental_migration_updates_existing_action_queue(self):
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist/init/88-add-ai-reader-action-active-scope.sql"
        )

        ddl = migration_path.read_text()

        self.assertIn("ALTER TABLE tb_ai_reader_action_queue", ddl)
        self.assertIn("ADD COLUMN active_scope_key CHAR(64) NULL", ddl)
        self.assertIn("ADD UNIQUE KEY uk_ai_reader_action_active_scope", ddl)
        self.assertIn("active_scope_key", ddl)

    def test_llm_decision_incremental_migration_uses_session_audit_unique(self):
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist/init/89-adjust-ai-reader-llm-decision-audit-indexes.sql"
        )

        ddl = migration_path.read_text()

        duplicate_preflight_pos = ddl.index("@has_ai_reader_llm_session_duplicates")
        add_session_pos = ddl.index("ADD UNIQUE KEY uk_ai_reader_llm_decision_session")
        drop_request_pos = ddl.index("DROP INDEX uk_ai_reader_llm_decision_request")
        self.assertLess(duplicate_preflight_pos, add_session_pos)
        self.assertLess(add_session_pos, drop_request_pos)
        self.assertIn("tmp_ai_reader_llm_decision_duplicate_guard", ddl)
        self.assertIn("CHECK (must_be_zero = 0)", ddl)
        self.assertNotIn("uk_ai_reader_llm_decision_session_duplicate_blocker", ddl)
        self.assertIn("DROP INDEX uk_ai_reader_llm_decision_request", ddl)
        self.assertIn("ADD UNIQUE KEY uk_ai_reader_llm_decision_session", ddl)
        self.assertIn("ADD KEY idx_ai_reader_llm_decision_request", ddl)
        self.assertIn("information_schema.statistics", ddl)

    def test_unrecommend_metric_incremental_migration_adds_column(self):
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist/init/90-add-ai-reader-unrecommend-metric.sql"
        )

        ddl = migration_path.read_text()

        self.assertIn("ALTER TABLE tb_ai_reader_public_metric_daily", ddl)
        self.assertIn("ADD COLUMN ai_unrecommend_count INT NOT NULL DEFAULT 0", ddl)
        self.assertIn("SIGNAL SQLSTATE ''45000''", ddl)
        self.assertIn("tb_ai_reader_public_metric_daily is required", ddl)
        self.assertIn("information_schema.columns", ddl)

    def test_stale_action_index_incremental_migration_adds_index(self):
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist/init/91-add-ai-reader-action-stale-index.sql"
        )

        ddl = migration_path.read_text()

        self.assertIn("ALTER TABLE tb_ai_reader_action_queue", ddl)
        self.assertIn("ADD KEY idx_ai_reader_action_queue_stale", ddl)
        self.assertIn("(status, locked_at, attempt_count, ai_reader_action_id)", ddl)
        self.assertIn("information_schema.statistics", ddl)
        self.assertIn("SIGNAL SQLSTATE ''45000''", ddl)

    def test_schedule_lease_incremental_migration_adds_missing_columns(self):
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist/init/92-add-ai-reader-schedule-lease-columns.sql"
        )

        ddl = migration_path.read_text()

        self.assertIn("tb_ai_reader_daily_schedule", ddl)
        self.assertIn("ADD COLUMN locked_by VARCHAR(100) NULL", ddl)
        self.assertIn("ADD COLUMN locked_at TIMESTAMP NULL", ddl)
        self.assertIn("ADD COLUMN error_message VARCHAR(1000) NULL", ddl)
        self.assertIn("information_schema.columns", ddl)
        self.assertIn("SIGNAL SQLSTATE ''45000''", ddl)

    def test_schedule_stale_index_incremental_migration_adds_index(self):
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist/init/93-add-ai-reader-schedule-stale-index.sql"
        )

        ddl = migration_path.read_text()

        self.assertIn("ALTER TABLE tb_ai_reader_daily_schedule", ddl)
        self.assertIn("ADD KEY idx_ai_reader_daily_schedule_stale", ddl)
        self.assertIn(
            "(status, locked_at, active_start_at, active_end_at, ai_reader_schedule_id)",
            ddl,
        )
        self.assertIn("@ai_reader_schedule_stale_index_columns", ddl)
        self.assertIn("@ai_reader_schedule_stale_index_non_unique", ddl)
        self.assertIn("idx_ai_reader_daily_schedule_stale drift", ddl)
        self.assertIn("locked_at", ddl)
        self.assertIn("active_start_at", ddl)
        self.assertIn("active_end_at", ddl)
        self.assertIn("information_schema.statistics", ddl)
        self.assertIn("information_schema.columns", ddl)
        self.assertIn("SIGNAL SQLSTATE ''45000''", ddl)

    def test_monitor_index_incremental_migration_adds_action_and_decision_indexes(self):
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist/init/94-add-ai-reader-monitor-indexes.sql"
        )

        ddl = migration_path.read_text()

        self.assertIn("tb_ai_reader_action_queue", ddl)
        self.assertIn("ADD KEY idx_ai_reader_action_queue_status_applied_product", ddl)
        self.assertIn("(status, applied_at, product_id, action_type)", ddl)
        self.assertIn("ADD KEY idx_ai_reader_action_queue_failed_updated_product", ddl)
        self.assertIn("(status, updated_date, product_id)", ddl)
        self.assertIn("tb_ai_reader_llm_decision", ddl)
        self.assertIn("ADD KEY idx_ai_reader_llm_decision_status_created_product", ddl)
        self.assertIn("(decision_status, created_date, product_id)", ddl)
        self.assertIn("information_schema.statistics", ddl)
        self.assertIn("SIGNAL SQLSTATE ''45000''", ddl)

    def test_product_models_include_ai_reader_phase1_tables(self):
        from sqlalchemy import JSON, Numeric
        from app.models import product

        self.assertTrue(hasattr(product, "AiReaderAgent"))
        self.assertTrue(hasattr(product, "AiReaderDailySchedule"))
        self.assertTrue(hasattr(product, "AiReaderLlmDecision"))
        self.assertTrue(hasattr(product, "AiReaderActionQueue"))
        self.assertTrue(hasattr(product.AiReaderPublicMetricDaily, "ai_unrecommend_count"))
        self.assertIn(
            "idx_ai_reader_action_queue_stale",
            {index.name for index in product.AiReaderActionQueue.__table__.indexes},
        )
        self.assertIn(
            "idx_ai_reader_action_queue_status_applied_product",
            {index.name for index in product.AiReaderActionQueue.__table__.indexes},
        )
        self.assertIn(
            "idx_ai_reader_action_queue_failed_updated_product",
            {index.name for index in product.AiReaderActionQueue.__table__.indexes},
        )
        self.assertIn(
            "idx_ai_reader_llm_decision_status_created_product",
            {index.name for index in product.AiReaderLlmDecision.__table__.indexes},
        )
        self.assertIn(
            "idx_ai_reader_daily_schedule_stale",
            {index.name for index in product.AiReaderDailySchedule.__table__.indexes},
        )
        self.assertIsInstance(product.AiReaderAgent.__table__.c.persona_json.type, JSON)
        self.assertIsInstance(
            product.AiReaderAgent.__table__.c.taste_memory_json.type,
            JSON,
        )
        self.assertIsInstance(
            product.AiReaderAgent.__table__.c.activity_pattern_json.type,
            JSON,
        )
        self.assertIsInstance(
            product.AiReaderLlmDecision.__table__.c.input_snapshot_json.type,
            JSON,
        )
        self.assertIsInstance(
            product.AiReaderLlmDecision.__table__.c.decision_json.type,
            JSON,
        )
        self.assertIsInstance(
            product.AiReaderActionQueue.__table__.c.decision_json.type,
            JSON,
        )
        estimated_cost_type = (
            product.AiReaderLlmDecision.__table__.c.estimated_cost_usd.type
        )
        self.assertIsInstance(estimated_cost_type, Numeric)
        self.assertEqual(estimated_cost_type.precision, 12)
        self.assertEqual(estimated_cost_type.scale, 6)


class AiReaderActionApplierTest(unittest.IsolatedAsyncioTestCase):
    class _FakeMappingsResult:
        def __init__(self, rows, rowcount=1, lastrowid=None, scalar_value=None):
            self._rows = rows
            self.rowcount = rowcount
            self.lastrowid = lastrowid
            self._scalar_value = scalar_value

        def mappings(self):
            return self

        def all(self):
            return self._rows

        def one_or_none(self):
            return self._rows[0] if self._rows else None

        def scalar(self):
            if not self._rows:
                return None
            first_row = self._rows[0]
            if isinstance(first_row, dict):
                return next(iter(first_row.values()), None)
            return first_row

        def scalar_one(self):
            return self._scalar_value

        def scalar(self):
            if self._scalar_value is not None:
                return self._scalar_value
            if not self._rows:
                return None
            first_row = self._rows[0]
            if isinstance(first_row, dict):
                return next(iter(first_row.values()), None)
            return first_row

        def first(self):
            return self._rows[0] if self._rows else None

    async def test_ai_reader_engagement_statistics_reads_operational_and_product_metrics(self):
        from app.services.common import statistics_service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"table_count": 5}]),
            self._FakeMappingsResult(
                [
                    {
                        "total_agent_count": 100,
                        "active_agent_count": 100,
                        "created_agent_count": 100,
                    }
                ]
            ),
            self._FakeMappingsResult(
                [
                    {
                        "today_schedule_count": 100,
                        "open_schedule_count": 0,
                        "failed_schedule_count": 0,
                    }
                ]
            ),
            self._FakeMappingsResult(
                [
                    {
                        "decision_count": 500,
                        "success_decision_count": 499,
                        "failed_decision_count": 1,
                    }
                ]
            ),
            self._FakeMappingsResult(
                [
                    {
                        "queued_action_count": 0,
                        "running_action_count": 0,
                        "failed_action_count": 0,
                        "applied_action_count": 978,
                    }
                ]
            ),
            self._FakeMappingsResult(
                [
                    {
                        "ai_view_count": 978,
                        "ai_bookmark_count": 42,
                        "ai_unbookmark_count": 1,
                        "ai_recommend_count": 88,
                        "ai_unrecommend_count": 10,
                        "ai_evaluation_count": 56,
                    }
                ]
            ),
            self._FakeMappingsResult([{"drop_count": 21}]),
            self._FakeMappingsResult([{"total_count": 1}]),
            self._FakeMappingsResult(
                [
                    {
                        "product_id": 473,
                        "product_title": "악녀관두려니까 이제는 성녀?",
                        "ai_view_count": 98,
                        "ai_bookmark_count": 5,
                        "ai_recommend_count": 10,
                        "ai_evaluation_count": 6,
                        "drop_count": 0,
                        "public_view_count": 120,
                        "public_bookmark_count": 9,
                        "public_recommend_count": 11,
                        "public_evaluation_count": 7,
                    }
                ]
            ),
            self._FakeMappingsResult([{"hour": 21, "read_count": 12}]),
            self._FakeMappingsResult([{"age_group": "30s", "gender": "M", "read_count": 7}]),
            self._FakeMappingsResult([{"event_time": "2026-05-12 21:00:00", "error_message": "bad json"}]),
            self._FakeMappingsResult([{"ai_reader_action_id": 1001, "action_type": "read"}]),
        ]

        response = await statistics_service.ai_reader_engagement_statistics(
            start_date="2026-05-12",
            end_date="2026-05-12",
            product_id=None,
            page=1,
            count_per_page=20,
            db=db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertEqual(response["summary"]["total_agent_count"], 100)
        self.assertEqual(response["summary"]["success_decision_count"], 499)
        self.assertEqual(response["summary"]["ai_view_count"], 978)
        self.assertEqual(response["summary"]["drop_count"], 21)
        self.assertEqual(response["total_count"], 1)
        self.assertEqual(response["results"][0]["product_title"], "악녀관두려니까 이제는 성녀?")
        self.assertEqual(response["results"][0]["ai_recommend_count"], 10)
        self.assertIn("tb_ai_reader_public_metric_daily", executed_sql)
        self.assertIn("tb_ai_reader_action_queue", executed_sql)
        self.assertIn("tb_ai_reader_llm_decision", executed_sql)
        self.assertIn("tb_ai_reader_daily_schedule", executed_sql)
        self.assertIn("tb_product", executed_sql)
        self.assertIn("tb_product_evaluation", executed_sql)
        self.assertNotIn("p.count_evaluation", executed_sql)
        self.assertIn("created_date >= :start_at", executed_sql)
        self.assertIn("created_date < :end_exclusive", executed_sql)
        self.assertIn("status IN ('queued', 'running', 'failed')", executed_sql)
        self.assertIn("status = 'applied' AND applied_at >= :start_at", executed_sql)
        self.assertNotIn("DATE(", executed_sql)
        self.assertNotIn("COALESCE(applied_at", executed_sql)
        self.assertNotIn("COALESCE(q.applied_at", executed_sql)

    async def test_ai_reader_engagement_statistics_rejects_long_date_range(self):
        from app.exceptions import CustomResponseException
        from app.services.common import statistics_service

        db = AsyncMock()

        with self.assertRaises(CustomResponseException):
            await statistics_service.ai_reader_engagement_statistics(
                start_date="2026-01-01",
                end_date="2026-03-01",
                product_id=None,
                page=1,
                count_per_page=20,
                db=db,
            )

        db.execute.assert_not_called()

    async def test_ai_reader_engagement_statistics_returns_empty_when_tables_are_absent(self):
        from app.services.common import statistics_service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult([{"table_count": 0}])

        response = await statistics_service.ai_reader_engagement_statistics(
            start_date="2026-05-12",
            end_date="2026-05-12",
            product_id=None,
            page=1,
            count_per_page=20,
            db=db,
        )

        self.assertEqual(response["total_count"], 0)
        self.assertEqual(response["summary"]["total_agent_count"], 0)
        self.assertEqual(response["summary"]["ai_view_count"], 0)
        self.assertEqual(response["results"], [])
        self.assertEqual(response["recent_errors"], [])
        db.execute.assert_awaited_once()

    async def test_ai_reader_engagement_statistics_applies_product_filter_without_alias_corruption(self):
        from app.services.common import statistics_service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"table_count": 5}]),
            self._FakeMappingsResult([{"total_agent_count": 100, "active_agent_count": 100, "created_agent_count": 0}]),
            self._FakeMappingsResult([{"today_schedule_count": 0, "open_schedule_count": 0, "failed_schedule_count": 0}]),
            self._FakeMappingsResult([{"decision_count": 2, "success_decision_count": 2, "failed_decision_count": 0, "pending_decision_count": 0}]),
            self._FakeMappingsResult([{"queued_action_count": 0, "running_action_count": 0, "failed_action_count": 0, "applied_action_count": 4}]),
            self._FakeMappingsResult([{"ai_view_count": 4, "ai_bookmark_count": 1, "ai_unbookmark_count": 0, "ai_recommend_count": 1, "ai_unrecommend_count": 0, "ai_evaluation_count": 1}]),
            self._FakeMappingsResult([{"drop_count": 0}]),
            self._FakeMappingsResult([{"total_count": 1}]),
            self._FakeMappingsResult([{"product_id": 473, "product_title": "테스트", "ai_view_count": 4}]),
            self._FakeMappingsResult([{"hour": 20, "read_count": 4}]),
            self._FakeMappingsResult([{"age_group": "30s", "gender": "M", "read_count": 4}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
        ]

        await statistics_service.ai_reader_engagement_statistics(
            start_date="2026-05-12",
            end_date="2026-05-12",
            product_id=473,
            page=1,
            count_per_page=20,
            db=db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertIn("q.product_id = :product_id", executed_sql)
        self.assertIn("m.product_id = :product_id", executed_sql)
        self.assertIn("AND product_id = :product_id", executed_sql)
        self.assertIn("product_id = :product_id", executed_sql)
        self.assertNotIn(":q.product_id", executed_sql)
        self.assertNotIn(":m.product_id", executed_sql)
        self.assertNotIn(":d.product_id", executed_sql)
        self.assertIn("tb_ai_reader_llm_decision", executed_sql)
        self.assertIn("product_id", executed_sql)
        self.assertIn(
            "FROM tb_product_evaluation\n                WHERE product_id = :product_id",
            executed_sql,
        )

    async def test_ai_reader_agent_actions_history_includes_full_end_date(self):
        from app.services.common import statistics_service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"table_count": 1}], scalar_value=1),
            self._FakeMappingsResult([], scalar_value=1),
            self._FakeMappingsResult(
                [
                    {
                        "ai_reader_action_id": 9001,
                        "ai_reader_agent_id": 7,
                        "product_id": 473,
                        "episode_id": None,
                        "action_type": "read",
                        "target_value": None,
                        "status": "applied",
                        "applied_at": "2026-05-14 21:00:00",
                        "created_date": "2026-05-14 20:59:00",
                        "updated_date": "2026-05-14 21:00:01",
                        "error_message": None,
                    }
                ]
            ),
        ]

        response = await statistics_service.ai_reader_agent_actions_history(
            agent_id=7,
            start_date="2026-05-14",
            end_date="2026-05-14",
            page=1,
            count_per_page=50,
            db=db,
        )

        action_params = [
            call.args[1]
            for call in db.execute.await_args_list
            if len(call.args) > 1
            and isinstance(call.args[1], dict)
            and call.args[1].get("agent_id") == 7
        ]
        self.assertTrue(action_params)
        self.assertTrue(
            all(
                params["start_at"] == "2026-05-14 00:00:00"
                and params["end_exclusive"] == "2026-05-15 00:00:00"
                for params in action_params
            )
        )
        self.assertEqual(response["total_count"], 1)
        self.assertEqual(response["items"][0]["ai_reader_action_id"], 9001)

    async def test_ai_reader_agent_actions_history_returns_empty_when_action_table_absent(self):
        from app.services.common import statistics_service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult([{"table_count": 0}], scalar_value=0)

        response = await statistics_service.ai_reader_agent_actions_history(
            agent_id=7,
            start_date="2026-05-14",
            end_date="2026-05-14",
            page=1,
            count_per_page=50,
            db=db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)
        self.assertIn("information_schema.tables", executed_sql)
        self.assertIn("tb_ai_reader_action_queue", executed_sql)
        self.assertEqual(response["total_count"], 0)
        self.assertEqual(response["items"], [])
        db.execute.assert_awaited_once()

    async def test_bookmark_add_sets_final_state_without_toggle_endpoint(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"read_count": 1}]),
            self._FakeMappingsResult([{"id": 1, "use_yn": "N"}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=10,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=None,
                action_type="bookmark",
                target_value="Y",
                llm_decision_id=91,
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertTrue(result.applied)
        self.assertIn("update tb_user_bookmark", executed_sql)
        self.assertIn("set use_yn = :target_use_yn", executed_sql)
        self.assertNotIn("case when use_yn = 'Y' then 'N' else 'Y' end", executed_sql)
        self.assertIn("update tb_product a", executed_sql)
        self.assertIn("tb_ai_reader_public_metric_daily", executed_sql)
        self.assertIn("last_decision_id", executed_sql)

    async def test_bookmark_add_requires_product_read_pool(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"read_count": 0}]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=10,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=None,
                action_type="bookmark",
                target_value="Y",
                llm_decision_id=91,
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "product_not_read")
        self.assertIn("from tb_user_product_usage", executed_sql)
        self.assertNotIn("insert into tb_user_bookmark", executed_sql)
        self.assertNotIn("update tb_product a", executed_sql)

    async def test_read_action_updates_usage_public_hit_count_and_ai_metric(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult(
                [
                    {
                        "protagonist_type": "성장형",
                        "protagonist_goal_primary": "생존",
                        "goal_confidence": 0.8,
                        "mood": "빠른전개",
                        "protagonist_material_tags": '["상태창"]',
                        "worldview_tags": '["현대"]',
                        "protagonist_type_tags": '["성장형"]',
                        "protagonist_job_tags": '["헌터"]',
                        "axis_style_tags": '["빠른전개"]',
                        "axis_romance_tags": "[]",
                        "romance_chemistry_weight": "none",
                    }
                ],
            ),
            self._FakeMappingsResult([], lastrowid=51),
            self._FakeMappingsResult([], rowcount=2),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=9,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="read",
                target_value=None,
                llm_decision_id=91,
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertTrue(result.applied)
        self.assertIn("insert into tb_user_product_usage", executed_sql)
        self.assertIn("e.open_yn = 'Y'", executed_sql)
        self.assertIn("p.open_yn = 'Y'", executed_sql)
        self.assertIn("e.publish_reserve_date is null", executed_sql)
        self.assertIn("e.price_type", executed_sql)
        self.assertIn("p.paid_episode_no", executed_sql)
        self.assertIn("update tb_product_episode", executed_sql)
        self.assertIn("set count_hit = count_hit + 1", executed_sql)
        self.assertIn("update tb_product", executed_sql)
        self.assertIn("ai_view_count", executed_sql)
        self.assertIn("last_decision_id", executed_sql)
        self.assertIn("tb_user_ai_signal_event", executed_sql)
        self.assertIn("tb_user_ai_signal_event_factor", executed_sql)
        self.assertNotIn("event_reward", executed_sql.lower())

    async def test_evaluate_action_is_idempotent_when_evaluation_exists(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([{"id": 3}]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=11,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="evaluate",
                target_value="verypositive",
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertFalse(result.applied)
        self.assertNotIn("insert into tb_product_evaluation", executed_sql)
        self.assertNotIn("count_evaluation = count_evaluation + 1", executed_sql)

    async def test_evaluate_rejects_episode_product_mismatch(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult([{"product_id": 201}])

        with self.assertRaises(service.InvalidReaderActionError):
            await service.apply_reader_action(
                service.ReaderQueuedAction(
                    ai_reader_action_id=11,
                    ai_reader_agent_id=7,
                    user_id=100,
                    product_id=200,
                    episode_id=300,
                    action_type="evaluate",
                    target_value="verypositive",
                ),
                db,
            )

    async def test_drop_and_next_episode_actions_update_ai_product_state(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([{"active_scope_key": "scope-a"}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
        ]

        drop_result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=20,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="drop",
                target_value="Y",
            ),
            db,
        )
        next_result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=21,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="next_episode",
                target_value="2",
                llm_decision_id=91,
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertTrue(drop_result.applied)
        self.assertTrue(next_result.applied)
        self.assertIn("insert into tb_ai_reader_product_state", executed_sql)
        self.assertIn("state = 'dropped'", executed_sql)
        self.assertIn("insert into tb_ai_reader_action_queue", executed_sql)
        self.assertIn("active_scope_key", executed_sql)
        self.assertIn("ai-reader-active", executed_sql)
        self.assertIn("action_type", executed_sql)
        self.assertIn("target_value", executed_sql)
        self.assertIn("'read', null", executed_sql)
        self.assertIn("llm_decision_id", executed_sql)
        self.assertIn(":llm_decision_id", executed_sql)
        self.assertIn("last_decision_id", executed_sql)
        self.assertIn("z.open_yn = 'Y'", executed_sql)
        self.assertIn("z.publish_reserve_date is null", executed_sql)
        self.assertIn("z.price_type", executed_sql)
        self.assertIn("p.paid_episode_no", executed_sql)

    async def test_read_action_does_not_revive_dropped_product_state(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([{"id": 1, "state": "dropped"}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult(
                [
                    {
                        "protagonist_type": "성장형",
                        "protagonist_goal_primary": "생존",
                        "goal_confidence": 0.8,
                        "mood": "빠른전개",
                        "protagonist_material_tags": '["상태창"]',
                        "worldview_tags": '["현대"]',
                        "protagonist_type_tags": '["성장형"]',
                        "protagonist_job_tags": '["헌터"]',
                        "axis_style_tags": '["빠른전개"]',
                        "axis_romance_tags": "[]",
                        "romance_chemistry_weight": "none",
                    }
                ],
            ),
            self._FakeMappingsResult([], lastrowid=51),
            self._FakeMappingsResult([], rowcount=2),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=22,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="read",
                target_value=None,
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "product_dropped")
        self.assertNotIn("insert into tb_user_product_usage", executed_sql)
        self.assertNotIn("set count_hit = count_hit + 1", executed_sql)
        self.assertNotIn("state = 'reading'", executed_sql)

    async def test_next_episode_action_does_not_queue_after_drop(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([{"state": "dropped"}]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=23,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="next_episode",
                target_value="2",
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "product_dropped")
        self.assertNotIn("insert into tb_ai_reader_action_queue", executed_sql)

    async def test_next_episode_action_requires_active_current_episode_in_product(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult([{"product_id": 999}])

        with self.assertRaises(service.InvalidReaderActionError):
            await service.apply_reader_action(
                service.ReaderQueuedAction(
                    ai_reader_action_id=24,
                    ai_reader_agent_id=7,
                    user_id=100,
                    product_id=200,
                    episode_id=300,
                    action_type="next_episode",
                    target_value="2",
                ),
                db,
            )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)
        self.assertIn("from tb_product_episode e", executed_sql)
        self.assertNotIn("insert into tb_ai_reader_action_queue", executed_sql)
        self.assertNotIn("insert into tb_ai_reader_product_state", executed_sql)

    async def test_next_episode_action_carries_llm_decision_to_followup_reads(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([{"active_scope_key": "scope-a"}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([], rowcount=2),
            self._FakeMappingsResult([]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=24,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="next_episode",
                target_value="2",
                llm_decision_id=91,
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertTrue(result.applied)
        self.assertIn("llm_decision_id", executed_sql)
        self.assertIn(":llm_decision_id", executed_sql)
        self.assertIn("active_scope_key", executed_sql)
        self.assertIn("ai-reader-active", executed_sql)
        self.assertIn("available_at", executed_sql)
        self.assertIn("timestampadd(", executed_sql.lower())
        self.assertIn("second,", executed_sql.lower())
        self.assertIn(":next_read_base_delay_seconds", executed_sql)
        self.assertIn(":next_read_step_delay_seconds", executed_sql)
        self.assertIn("active_scope_key in", executed_sql)
        self.assertLess(
            executed_sql.lower().index("active_scope_key in"),
            executed_sql.lower().index("insert into tb_ai_reader_action_queue"),
        )
        self.assertIn("last_decision_id", executed_sql)

    async def test_next_episode_action_caps_followup_read_to_one_episode(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([{"active_scope_key": "scope-a"}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult([]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=25,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="next_episode",
                target_value="20",
                llm_decision_id=91,
            ),
            db,
        )

        limit_params = [
            call.args[1]
            for call in db.execute.await_args_list
            if len(call.args) > 1
            and isinstance(call.args[1], dict)
            and "next_episode_count" in call.args[1]
        ]

        self.assertTrue(result.applied)
        self.assertTrue(limit_params)
        self.assertTrue(
            all(params["next_episode_count"] == 1 for params in limit_params)
        )

    async def test_next_episode_action_does_not_apply_when_no_followup_episode_exists(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([], rowcount=0),
            self._FakeMappingsResult([]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=26,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="next_episode",
                target_value="1",
                llm_decision_id=91,
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "no_next_episode")
        self.assertNotIn("insert into tb_ai_reader_action_queue", executed_sql)
        self.assertNotIn("insert into tb_ai_reader_product_state", executed_sql)

    def test_action_target_lock_key_is_agent_product_scoped(self):
        from app.services.ai import reader_agent_action_service as service

        read_lock_key = service._build_action_target_lock_key(
            service.ReaderQueuedAction(
                ai_reader_action_id=30,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="read",
                target_value=None,
            )
        )
        drop_lock_key = service._build_action_target_lock_key(
            service.ReaderQueuedAction(
                ai_reader_action_id=31,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=301,
                action_type="drop",
                target_value="Y",
            )
        )
        recommend_lock_key = service._build_action_target_lock_key(
            service.ReaderQueuedAction(
                ai_reader_action_id=32,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="recommend",
                target_value="Y",
            )
        )

        self.assertEqual(read_lock_key, drop_lock_key)
        self.assertEqual(read_lock_key, recommend_lock_key)

    async def test_drop_action_rejects_non_drop_target_value(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()

        with self.assertRaises(service.InvalidReaderActionError):
            await service.apply_reader_action(
                service.ReaderQueuedAction(
                    ai_reader_action_id=20,
                    ai_reader_agent_id=7,
                    user_id=100,
                    product_id=200,
                    episode_id=300,
                    action_type="drop",
                    target_value="N",
                ),
                db,
            )

        db.execute.assert_not_awaited()

    def test_eval_code_contract_matches_existing_nine_step_schema(self):
        from app.services.ai import reader_agent_decision_service as service

        self.assertIn("somewhatpositive", service.EVALUATION_CODES)
        self.assertIn("somewhatnegative", service.EVALUATION_CODES)
        self.assertIn("verynegative", service.EVALUATION_CODES)
        self.assertIn("highlynegative", service.EVALUATION_CODES)

    async def test_recommend_press_uses_episode_like_as_public_count_ssot(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([{"read_count": 1}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=12,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="recommend",
                target_value="Y",
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertTrue(result.applied)
        self.assertIn("insert into tb_product_episode_like", executed_sql)
        self.assertIn("set count_recommend = (", executed_sql)
        self.assertIn("from tb_product_episode_like", executed_sql)
        self.assertIn("ai_recommend_count", executed_sql)
        self.assertIn("tb_user_product_usage", executed_sql)

    async def test_recommend_press_requires_episode_read_pool(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([{"read_count": 0}]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=12,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="recommend",
                target_value="Y",
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "episode_not_read")
        self.assertIn("tb_user_product_usage", executed_sql)
        self.assertNotIn("insert into tb_product_episode_like", executed_sql)

    async def test_recommend_remove_tracks_ai_unrecommend_metric(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([{"id": 91}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=13,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="recommend",
                target_value="N",
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertTrue(result.applied)
        self.assertIn("delete from tb_product_episode_like", executed_sql)
        self.assertIn("set count_recommend = (", executed_sql)
        self.assertIn("recommended_yn", executed_sql)
        self.assertIn("ai_unrecommend_count", executed_sql)
        self.assertNotIn("ai_recommend_count", executed_sql)

    async def test_recommend_remove_deletes_duplicate_like_rows_for_ai_user(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([{"id": 91}, {"id": 92}]),
            self._FakeMappingsResult([], rowcount=2),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=14,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="recommend",
                target_value="N",
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertTrue(result.applied)
        self.assertIn("delete from tb_product_episode_like", executed_sql)
        self.assertIn("where id in", executed_sql)
        self.assertIn("like_ids", executed_sql)
        self.assertIn("set count_recommend = (", executed_sql)

    async def test_recommend_press_deduplicates_existing_like_rows_without_double_metric(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([{"id": 91}, {"id": 92}]),
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=15,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="recommend",
                target_value="Y",
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "already_in_target_state")
        self.assertIn("delete from tb_product_episode_like", executed_sql)
        self.assertIn("where id in", executed_sql)
        self.assertIn("set count_recommend = (", executed_sql)
        self.assertNotIn("ai_recommend_count", executed_sql)

    async def test_evaluate_existing_duplicates_are_deduplicated_and_count_refreshed(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([{"id": 91}, {"id": 92}]),
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult([]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=16,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="evaluate",
                target_value="positive",
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "already_applied")
        self.assertIn("delete from tb_product_evaluation", executed_sql)
        self.assertIn("where id in", executed_sql)
        self.assertIn("set count_evaluation = (", executed_sql)
        self.assertNotIn("ai_evaluation_count", executed_sql)

    async def test_evaluate_requires_current_episode_read_pool(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([{"read_count": 0}]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=16,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="evaluate",
                target_value="positive",
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "episode_not_read")
        self.assertIn("tb_user_product_usage", executed_sql)
        self.assertNotIn("insert into tb_product_evaluation", executed_sql)

    async def test_evaluate_requires_minimum_read_pool(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([{"read_count": 1}]),
            self._FakeMappingsResult([{"read_count": 2}]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=16,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="evaluate",
                target_value="positive",
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "insufficient_read_pool")
        self.assertIn("tb_user_product_usage", executed_sql)
        self.assertNotIn("insert into tb_product_evaluation", executed_sql)

    async def test_evaluate_applies_after_episode_and_minimum_product_reads(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"product_id": 200}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([{"read_count": 1}]),
            self._FakeMappingsResult([{"read_count": 3}]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=16,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="evaluate",
                target_value="positive",
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertTrue(result.applied)
        self.assertIn("insert into tb_product_evaluation", executed_sql)
        self.assertIn("set count_evaluation = (", executed_sql)
        self.assertIn("ai_evaluation_count", executed_sql)

    async def test_bookmark_remove_deduplicates_rows_and_counts_one_ai_unbookmark(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult(
                [{"id": 91, "use_yn": "Y"}, {"id": 92, "use_yn": "Y"}]
            ),
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([]),
        ]

        result = await service.apply_reader_action(
            service.ReaderQueuedAction(
                ai_reader_action_id=17,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=None,
                action_type="bookmark",
                target_value="N",
            ),
            db,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertTrue(result.applied)
        self.assertIn("select id", executed_sql)
        self.assertIn("order by id", executed_sql)
        self.assertIn("update tb_user_bookmark", executed_sql)
        self.assertIn("delete from tb_user_bookmark", executed_sql)
        self.assertIn("bookmark_ids", executed_sql)
        self.assertIn("set a.count_bookmark = t.count_bookmark", executed_sql)
        self.assertIn("ai_unbookmark_count", executed_sql)

    async def test_claim_due_actions_uses_skip_locked_and_marks_running(self):
        from app.services.ai import reader_agent_action_service as service

        events = []
        db = AsyncMock()
        db.in_transaction = lambda: False

        @asynccontextmanager
        async def fake_begin():
            events.append("begin")
            try:
                yield
            finally:
                events.append("end")

        db.begin = fake_begin
        db.execute.side_effect = [
            self._FakeMappingsResult([], rowcount=0),
            self._FakeMappingsResult(
                [
                    {
                        "ai_reader_action_id": 12,
                        "ai_reader_agent_id": 7,
                        "user_id": 100,
                        "product_id": 200,
                        "episode_id": 300,
                        "action_type": "recommend",
                        "target_value": "Y",
                        "llm_decision_id": 91,
                    },
                    {
                        "ai_reader_action_id": 13,
                        "ai_reader_agent_id": 8,
                        "user_id": 101,
                        "product_id": 201,
                        "episode_id": 301,
                        "action_type": "read",
                        "target_value": None,
                        "llm_decision_id": 92,
                    }
                ]
            ),
            self._FakeMappingsResult([], rowcount=2),
        ]

        claimed = await service.claim_due_actions(db, worker_id="worker-a", limit=10)
        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertEqual(len(claimed), 2)
        self.assertEqual(claimed[0].ai_reader_action_id, 12)
        self.assertEqual(claimed[1].ai_reader_action_id, 13)
        self.assertEqual(claimed[0].llm_decision_id, 91)
        self.assertEqual(claimed[1].llm_decision_id, 92)
        self.assertEqual(events, ["begin", "end"])
        self.assertIn("llm_decision_id", executed_sql)
        self.assertIn("join tb_ai_reader_agent", executed_sql.lower())
        self.assertIn("a.status = 'active'", executed_sql.lower())
        self.assertIn("join tb_user", executed_sql.lower())
        self.assertIn("substring_index(u.email, '@', -1)", executed_sql.lower())
        self.assertIn("tb_user_social", executed_sql.lower())
        self.assertGreaterEqual(executed_sql.lower().count("join tb_ai_reader_agent"), 2)
        self.assertIn("for update skip locked", executed_sql.lower())
        self.assertIn("status = 'running'", executed_sql)
        self.assertIn("locked_by = :worker_id", executed_sql)
        self.assertIn("status = 'running'", executed_sql)
        self.assertIn(
            "locked_at <= timestampadd(second, -:lease_timeout_seconds, current_timestamp)",
            executed_sql.lower(),
        )
        self.assertIn("attempt_count < :max_attempt_count", executed_sql)
        self.assertIn("lease_timeout_seconds", str(db.execute.await_args_list[0].args[1]))

    async def test_process_claimed_action_fails_without_apply_when_agent_paused_after_claim(self):
        from app.services.ai import reader_agent_action_service as service

        action = service.ReaderQueuedAction(
            ai_reader_action_id=12,
            ai_reader_agent_id=7,
            user_id=100,
            product_id=200,
            episode_id=300,
            action_type="recommend",
            target_value="Y",
            llm_decision_id=91,
        )
        events = []
        failed = []
        db = AsyncMock()
        db.in_transaction = lambda: False

        @asynccontextmanager
        async def fake_begin():
            events.append("begin")
            try:
                yield
            finally:
                events.append("end")

        async def apply_func(_action, _db):
            events.append("apply")
            raise AssertionError("paused agent action must not be applied")

        async def failed_func(_db, *, action_id: int, worker_id: str, error_message: str):
            failed.append((action_id, worker_id, error_message))

        db.begin = fake_begin
        db.execute.side_effect = [
            self._FakeMappingsResult([], scalar_value=1),
            self._FakeMappingsResult([{"status": "paused"}]),
            self._FakeMappingsResult([], scalar_value=1),
        ]

        result = await service.process_claimed_action(
            action,
            db,
            worker_id="worker-a",
            apply_func=apply_func,
            failed_func=failed_func,
        )
        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "agent_paused")
        self.assertNotIn("apply", events)
        self.assertEqual(failed, [(12, "worker-a", "agent_paused")])
        self.assertIn("from tb_ai_reader_agent", executed_sql.lower())
        self.assertIn("for update", executed_sql.lower())

    async def test_claim_due_actions_commits_claim_before_caller_processes_actions(self):
        from app.services.ai import reader_agent_action_service as service

        events = []
        db = AsyncMock()
        db.in_transaction = lambda: True

        async def fake_commit():
            events.append("commit")

        db.commit.side_effect = fake_commit
        db.execute.side_effect = [
            self._FakeMappingsResult([], rowcount=0),
            self._FakeMappingsResult(
                [
                    {
                        "ai_reader_action_id": 12,
                        "ai_reader_agent_id": 7,
                        "user_id": 100,
                        "product_id": 200,
                        "episode_id": 300,
                        "action_type": "recommend",
                        "target_value": "Y",
                        "llm_decision_id": 91,
                    },
                ]
            ),
            self._FakeMappingsResult([], rowcount=1),
        ]

        claimed = await service.claim_due_actions(db, worker_id="worker-a", limit=10)

        self.assertEqual(len(claimed), 1)
        self.assertEqual(events, ["commit"])

    async def test_claim_due_actions_marks_stale_max_attempt_running_failed_before_claiming(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.in_transaction = lambda: False

        @asynccontextmanager
        async def fake_begin():
            yield

        db.begin = fake_begin
        db.execute.side_effect = [
            self._FakeMappingsResult(
                [
                    {"ai_reader_action_id": 30},
                    {"ai_reader_action_id": 31},
                ]
            ),
            self._FakeMappingsResult([], rowcount=2),
            self._FakeMappingsResult([]),
        ]

        claimed = await service.claim_due_actions(
            db,
            worker_id="worker-a",
            limit=10,
            lease_timeout_seconds=300,
            max_attempt_count=5,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertEqual(claimed, [])
        self.assertIn("for update skip locked", executed_sql.lower())
        self.assertIn("limit :cleanup_limit", executed_sql)
        self.assertIn("set status = 'failed'", executed_sql)
        self.assertIn("max attempts exceeded", executed_sql)
        self.assertIn("active_scope_key = null", executed_sql.lower())
        self.assertIn("locked_by = null", executed_sql.lower())
        self.assertIn("locked_at = null", executed_sql.lower())
        self.assertIn("where ai_reader_action_id in", executed_sql)
        self.assertIn("action_ids", executed_sql)
        self.assertIn("attempt_count >= :max_attempt_count", executed_sql)

    async def test_cleanup_stale_max_attempt_actions_can_target_active_scope_keys(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"ai_reader_action_id": 30}]),
            self._FakeMappingsResult([], rowcount=1),
        ]

        cleaned = await service.cleanup_stale_max_attempt_actions(
            db,
            active_scope_keys=["scope-a"],
            limit=10,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertEqual(cleaned, 1)
        self.assertIn("force index (idx_ai_reader_action_queue_stale)", executed_sql.lower())
        self.assertIn("active_scope_key in", executed_sql)
        self.assertIn("active_scope_keys", executed_sql)
        self.assertIn(":terminal_grace_seconds", executed_sql)
        self.assertIn("-(:lease_timeout_seconds + :terminal_grace_seconds)", executed_sql.lower())
        self.assertIn("for update skip locked", executed_sql.lower())
        self.assertIn("where ai_reader_action_id in", executed_sql)
        self.assertIn("action_ids", executed_sql)

    async def test_mark_action_succeeded_and_failed_require_running_worker_owner(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult([], rowcount=1)

        await service.mark_action_succeeded(db, action_id=12, worker_id="worker-a")
        await service.mark_action_failed(
            db,
            action_id=13,
            worker_id="worker-a",
            error_message="bad decision",
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertIn("set status = 'applied'", executed_sql)
        self.assertIn("applied_at = current_timestamp", executed_sql)
        self.assertIn("active_scope_key = null", executed_sql.lower())
        self.assertIn("locked_by = null", executed_sql.lower())
        self.assertIn("locked_at = null", executed_sql.lower())
        self.assertIn("set status = 'failed'", executed_sql)
        self.assertIn("error_message = :error_message", executed_sql)
        self.assertIn("where ai_reader_action_id = :action_id", executed_sql)
        self.assertIn("and status = 'running'", executed_sql)
        self.assertIn("and locked_by = :worker_id", executed_sql)

    async def test_mark_action_raises_when_running_worker_owner_does_not_match(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult([], rowcount=0)

        with self.assertRaises(service.InvalidReaderActionError):
            await service.mark_action_succeeded(db, action_id=12, worker_id="worker-a")

        with self.assertRaises(service.InvalidReaderActionError):
            await service.mark_action_failed(
                db,
                action_id=13,
                worker_id="worker-a",
                error_message="bad decision",
            )

    async def test_process_claimed_action_default_success_mark_path_runs(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()

        @asynccontextmanager
        async def fake_begin():
            yield

        db.begin = fake_begin
        db.execute.side_effect = [
            self._FakeMappingsResult([], scalar_value=1),
            self._FakeMappingsResult([{"status": "active"}]),
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult([], scalar_value=1),
        ]

        async def fake_apply(action, tx_db):
            return service.ReaderActionApplyResult(
                ai_reader_action_id=action.ai_reader_action_id,
                action_type=action.action_type,
                applied=True,
                reason="applied",
            )

        action = service.ReaderQueuedAction(
            ai_reader_action_id=30,
            ai_reader_agent_id=7,
            user_id=100,
            product_id=200,
            episode_id=300,
            action_type="read",
            target_value=None,
        )

        result = await service.process_claimed_action(
            action,
            db,
            worker_id="worker-a",
            apply_func=fake_apply,
        )
        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertTrue(result.applied)
        self.assertIn("set status = 'applied'", executed_sql)

    async def test_process_claimed_action_wraps_apply_and_success_mark_in_transaction(self):
        from app.services.ai import reader_agent_action_service as service

        events = []
        db = AsyncMock()

        @asynccontextmanager
        async def fake_begin():
            events.append("begin")
            try:
                yield
            finally:
                events.append("end")

        async def fake_execute(statement, *args, **kwargs):
            sql = str(statement).lower()
            if "get_lock" in sql:
                events.append("lock")
                return self._FakeMappingsResult([], scalar_value=1)
            if "from tb_ai_reader_agent" in sql:
                events.append("active")
                return self._FakeMappingsResult([{"status": "active"}])
            if "release_lock" in sql:
                events.append("release")
                return self._FakeMappingsResult([], scalar_value=1)
            raise AssertionError(f"unexpected sql: {statement}")

        db.begin = fake_begin
        db.execute.side_effect = fake_execute

        async def fake_apply(action, tx_db):
            events.append(f"apply:{action.action_type}")
            self.assertIs(tx_db, db)
            return service.ReaderActionApplyResult(
                ai_reader_action_id=action.ai_reader_action_id,
                action_type=action.action_type,
                applied=True,
                reason="applied",
            )

        async def fake_mark(tx_db, *, action_id, worker_id):
            events.append(f"mark:{action_id}:{worker_id}")
            self.assertIs(tx_db, db)

        action = service.ReaderQueuedAction(
            ai_reader_action_id=30,
            ai_reader_agent_id=7,
            user_id=100,
            product_id=200,
            episode_id=300,
            action_type="read",
            target_value=None,
        )

        result = await service.process_claimed_action(
            action,
            db,
            worker_id="worker-a",
            apply_func=fake_apply,
            success_func=fake_mark,
        )
        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertTrue(result.applied)
        self.assertEqual(
            events,
            ["begin", "lock", "active", "apply:read", "mark:30:worker-a", "end", "release"],
        )
        self.assertIn("get_lock", executed_sql.lower())
        self.assertIn("release_lock", executed_sql.lower())
        self.assertLess(
            executed_sql.lower().index("get_lock"),
            executed_sql.lower().index("release_lock"),
        )

    async def test_process_claimed_action_uses_pinned_session_until_lock_release(self):
        from app.services.ai import reader_agent_action_service as service

        events = []
        outer_db = AsyncMock()
        pinned_db = AsyncMock()
        pinned_db.in_transaction = lambda: True

        @asynccontextmanager
        async def fake_pinned_session_factory(source_db):
            events.append("pin")
            self.assertIs(source_db, outer_db)
            try:
                yield pinned_db
            finally:
                events.append("unpin")

        @asynccontextmanager
        async def fake_begin():
            events.append("begin")
            try:
                yield
            finally:
                events.append("end")

        async def fake_execute(statement, *args, **kwargs):
            sql = str(statement).lower()
            if "get_lock" in sql:
                events.append("lock")
                return self._FakeMappingsResult([], scalar_value=1)
            if "from tb_ai_reader_agent" in sql:
                events.append("active")
                return self._FakeMappingsResult([{"status": "active"}])
            if "release_lock" in sql:
                events.append("release")
                return self._FakeMappingsResult([], scalar_value=1)
            raise AssertionError(f"unexpected sql: {statement}")

        async def fake_commit():
            events.append("commit-release")

        pinned_db.begin = fake_begin
        pinned_db.execute.side_effect = fake_execute
        pinned_db.commit.side_effect = fake_commit

        async def fake_apply(action, tx_db):
            events.append("apply")
            self.assertIs(tx_db, pinned_db)
            return service.ReaderActionApplyResult(
                ai_reader_action_id=action.ai_reader_action_id,
                action_type=action.action_type,
                applied=True,
                reason="applied",
            )

        async def fake_mark(tx_db, *, action_id, worker_id):
            events.append("mark")
            self.assertIs(tx_db, pinned_db)

        action = service.ReaderQueuedAction(
            ai_reader_action_id=30,
            ai_reader_agent_id=7,
            user_id=100,
            product_id=200,
            episode_id=300,
            action_type="read",
            target_value=None,
        )

        result = await service.process_claimed_action(
            action,
            outer_db,
            worker_id="worker-a",
            apply_func=fake_apply,
            success_func=fake_mark,
            pinned_session_factory=fake_pinned_session_factory,
        )

        self.assertTrue(result.applied)
        self.assertEqual(
            events,
            [
                "pin",
                "begin",
                "lock",
                "active",
                "apply",
                "mark",
                "end",
                "release",
                "commit-release",
                "unpin",
            ],
        )
        outer_db.execute.assert_not_awaited()

    async def test_process_claimed_action_requeues_when_target_lock_is_busy(self):
        from app.services.ai import reader_agent_action_service as service

        events = []
        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([], scalar_value=0),
            self._FakeMappingsResult([], rowcount=1),
        ]

        @asynccontextmanager
        async def fake_begin():
            events.append("begin")
            try:
                yield
            finally:
                events.append("end")

        db.begin = fake_begin

        async def fake_apply(action, tx_db):
            raise AssertionError("apply must not run without target lock")

        action = service.ReaderQueuedAction(
            ai_reader_action_id=30,
            ai_reader_agent_id=7,
            user_id=100,
            product_id=200,
            episode_id=300,
            action_type="read",
            target_value=None,
        )

        result = await service.process_claimed_action(
            action,
            db,
            worker_id="worker-a",
            apply_func=fake_apply,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)
        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "lock_busy")
        self.assertEqual(events, ["begin", "end", "begin", "end"])
        self.assertIn("get_lock", executed_sql.lower())
        self.assertNotIn("release_lock", executed_sql.lower())
        self.assertIn("set status = 'queued'", executed_sql)
        self.assertIn("locked_by = null", executed_sql)
        self.assertIn("locked_at = null", executed_sql)
        self.assertIn("timestampadd(second, :retry_delay_seconds, current_timestamp)", executed_sql.lower())
        self.assertNotIn("set status = 'failed'", executed_sql)
        self.assertNotIn("active_scope_key = null", executed_sql.lower())

    async def test_process_claimed_action_requeues_read_pool_guard_when_read_is_pending(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([], scalar_value=1),
            self._FakeMappingsResult([{"status": "active"}]),
            self._FakeMappingsResult([{"ai_reader_action_id": 29}]),
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult([], scalar_value=1),
        ]

        @asynccontextmanager
        async def fake_begin():
            yield

        db.begin = fake_begin

        async def fake_apply(action, tx_db):
            return service.ReaderActionApplyResult(
                ai_reader_action_id=action.ai_reader_action_id,
                action_type=action.action_type,
                applied=False,
                reason="episode_not_read",
            )

        action = service.ReaderQueuedAction(
            ai_reader_action_id=30,
            ai_reader_agent_id=7,
            user_id=100,
            product_id=200,
            episode_id=300,
            action_type="recommend",
            target_value="Y",
            llm_decision_id=91,
        )

        result = await service.process_claimed_action(
            action,
            db,
            worker_id="worker-a",
            apply_func=fake_apply,
        )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)
        self.assertFalse(result.applied)
        self.assertEqual(result.reason, "episode_not_read")
        self.assertIn("action_type = 'read'", executed_sql)
        self.assertIn("status in ('queued', 'running')", executed_sql)
        self.assertIn("llm_decision_id = :llm_decision_id", executed_sql)
        self.assertIn("set status = 'queued'", executed_sql)
        self.assertIn("timestampadd(second, :retry_delay_seconds, current_timestamp)", executed_sql.lower())
        self.assertNotIn("set status = 'applied'", executed_sql)
        self.assertNotIn("active_scope_key = null", executed_sql.lower())

    async def test_process_claimed_action_marks_failed_when_target_lock_returns_null(self):
        from app.services.ai import reader_agent_action_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([], scalar_value=None),
            self._FakeMappingsResult([], rowcount=1),
        ]

        @asynccontextmanager
        async def fake_begin():
            yield

        db.begin = fake_begin

        async def fake_apply(action, tx_db):
            raise AssertionError("apply must not run when target lock returns null")

        action = service.ReaderQueuedAction(
            ai_reader_action_id=30,
            ai_reader_agent_id=7,
            user_id=100,
            product_id=200,
            episode_id=300,
            action_type="read",
            target_value=None,
        )

        with self.assertRaises(service.InvalidReaderActionError):
            await service.process_claimed_action(
                action,
                db,
                worker_id="worker-a",
                apply_func=fake_apply,
            )

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)
        self.assertIn("get_lock", executed_sql.lower())
        self.assertIn("set status = 'failed'", executed_sql)
        self.assertIn("active_scope_key = null", executed_sql.lower())

    async def test_process_claimed_action_marks_failed_after_apply_error(self):
        from app.services.ai import reader_agent_action_service as service

        events = []
        db = AsyncMock()

        @asynccontextmanager
        async def fake_begin():
            events.append("begin")
            try:
                yield
            finally:
                events.append("end")

        db.begin = fake_begin
        db.execute.side_effect = [
            self._FakeMappingsResult([], scalar_value=1),
            self._FakeMappingsResult([{"status": "active"}]),
            self._FakeMappingsResult([], scalar_value=1),
        ]

        async def fake_apply(action, tx_db):
            events.append(f"apply:{action.action_type}")
            raise RuntimeError("boom")

        async def fake_fail(tx_db, *, action_id, worker_id, error_message):
            events.append(f"fail:{action_id}:{worker_id}:{error_message}")
            self.assertIs(tx_db, db)

        action = service.ReaderQueuedAction(
            ai_reader_action_id=30,
            ai_reader_agent_id=7,
            user_id=100,
            product_id=200,
            episode_id=300,
            action_type="read",
            target_value=None,
        )

        with self.assertRaises(RuntimeError):
            await service.process_claimed_action(
                action,
                db,
                worker_id="worker-a",
                apply_func=fake_apply,
                failed_func=fake_fail,
            )

        self.assertEqual(
            events,
            ["begin", "apply:read", "end", "begin", "fail:30:worker-a:boom", "end"],
        )


class AiReaderAdminScheduleOpsTest(unittest.IsolatedAsyncioTestCase):
    class _FakeMappingsResult:
        def __init__(self, rows, rowcount=1):
            self._rows = rows
            self.rowcount = rowcount

        def mappings(self):
            return self

        def all(self):
            return self._rows

        def one_or_none(self):
            return self._rows[0] if self._rows else None

        def scalar(self):
            if not self._rows:
                return None
            first_row = self._rows[0]
            if isinstance(first_row, dict):
                return next(iter(first_row.values()), None)
            return first_row

    async def test_update_ai_reader_schedule_replaces_non_running_windows_immediately(self):
        from app.schemas.admin import PutAiReaderScheduleReqBody
        from app.services.admin import admin_ai_reader_service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult(
                [
                    {
                        "ai_reader_agent_id": 7,
                        "agent_key": "ai-reader-0007",
                        "user_id": 107,
                        "age_group": "30s",
                        "gender": "M",
                        "activity_pattern_json": json.dumps(
                            {
                                "active_hours": [7, 8, 12, 20, 21, 22],
                                "sleep_hours": [1, 2, 3, 4, 5],
                                "daily_session_target": 3,
                            }
                        ),
                        "daily_llm_budget": 8,
                        "status": "active",
                    }
                ]
            ),
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult([], rowcount=3),
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult([], rowcount=2),
        ]

        result = await admin_ai_reader_service.update_ai_reader_agent_schedule(
            ai_reader_agent_id=7,
            req_body=PutAiReaderScheduleReqBody(
                schedule_date="2026-05-13",
                active_hours=[6, 7, 20, 21],
                daily_session_target=2,
                daily_llm_budget=6,
            ),
            db=db,
        )

        executed_sql = "\n".join(str(call.args[0]).lower() for call in db.execute.call_args_list)
        self.assertIn("update tb_ai_reader_agent", executed_sql)
        self.assertIn("delete from tb_ai_reader_daily_schedule", executed_sql)
        self.assertIn("used_session_count > 0", executed_sql)
        self.assertIn("status = 'done'", executed_sql)
        self.assertIn("status = 'ready'", executed_sql)
        self.assertIn("used_session_count = 0", executed_sql)
        self.assertIn("insert into tb_ai_reader_daily_schedule", executed_sql)
        self.assertEqual(result["schedule_date"], "2026-05-13")
        self.assertEqual(result["agent"]["active_hours"], [6, 7, 20, 21])
        self.assertEqual(result["agent"]["daily_session_target"], 2)
        self.assertEqual(result["agent"]["daily_llm_budget"], 6)
        self.assertEqual(result["schedule_count"], 2)

    async def test_update_ai_reader_schedule_rejects_replace_running(self):
        from app.schemas.admin import PutAiReaderScheduleReqBody
        from app.services.admin import admin_ai_reader_service

        db = AsyncMock()

        with self.assertRaises(Exception) as raised:
            await admin_ai_reader_service.update_ai_reader_agent_schedule(
                ai_reader_agent_id=7,
                req_body=PutAiReaderScheduleReqBody(
                    schedule_date="2026-05-13",
                    active_hours=[6, 7, 20, 21],
                    daily_session_target=2,
                    replace_running=True,
                ),
                db=db,
            )

        self.assertIn("replace_running is not allowed", str(raised.exception))

    async def test_pause_all_ai_reader_agents_pauses_active_agents_and_pending_work(self):
        from app.services.admin import admin_ai_reader_service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult(
                [
                    {"ai_reader_agent_id": 11},
                    {"ai_reader_agent_id": 12},
                ]
            ),
            self._FakeMappingsResult([], rowcount=2),
            self._FakeMappingsResult([], rowcount=4),
            self._FakeMappingsResult([], rowcount=3),
        ]

        result = await admin_ai_reader_service.pause_all_ai_reader_agents(
            db=db,
        )

        executed_sql = "\n".join(str(call.args[0]).lower() for call in db.execute.call_args_list)
        self.assertIn("select ai_reader_agent_id", executed_sql)
        self.assertIn("from tb_ai_reader_agent", executed_sql)
        self.assertIn("for update", executed_sql)
        self.assertIn("status = 'paused'", executed_sql)
        self.assertIn("tb_ai_reader_daily_schedule", executed_sql)
        self.assertNotIn("schedule_date >=", executed_sql)
        self.assertIn("status in ('ready', 'running')", executed_sql)
        self.assertIn("tb_ai_reader_action_queue", executed_sql)
        self.assertIn("status in ('queued', 'running')", executed_sql)
        self.assertIn("active_scope_key = null", executed_sql)
        self.assertEqual(result["paused_agent_count"], 2)
        self.assertEqual(result["retired_schedule_count"], 4)
        self.assertEqual(result["cancelled_action_count"], 3)
        db.commit.assert_awaited_once()

    async def test_pause_all_ai_reader_agents_noops_when_no_active_agents(self):
        from app.services.admin import admin_ai_reader_service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult([])

        result = await admin_ai_reader_service.pause_all_ai_reader_agents(
            db=db,
        )

        self.assertEqual(result["paused_agent_count"], 0)
        self.assertEqual(result["retired_schedule_count"], 0)
        self.assertEqual(result["cancelled_action_count"], 0)
        self.assertEqual(db.execute.await_count, 1)
        db.commit.assert_awaited_once()

    async def test_resume_paused_ai_reader_agents_dry_run_reports_available_agents(self):
        from app.schemas.admin import PostAiReaderResumePausedReqBody
        from app.services.admin import admin_ai_reader_service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"available_agent_count": 3}]),
            self._FakeMappingsResult(
                [
                    {
                        "ai_reader_agent_id": 11,
                        "agent_key": "ai-reader-0011",
                        "user_id": 111,
                        "age_group": "20s",
                        "gender": "F",
                        "activity_pattern_json": json.dumps(
                            {"active_hours": [7, 20], "daily_session_target": 2}
                        ),
                        "daily_llm_budget": 8,
                    },
                    {
                        "ai_reader_agent_id": 12,
                        "agent_key": "ai-reader-0012",
                        "user_id": 112,
                        "age_group": "30s",
                        "gender": "M",
                        "activity_pattern_json": json.dumps(
                            {"active_hours": [8, 21], "daily_session_target": 2}
                        ),
                        "daily_llm_budget": 8,
                    },
                ]
            ),
        ]

        result = await admin_ai_reader_service.resume_paused_ai_reader_agents(
            req_body=PostAiReaderResumePausedReqBody(
                agent_count=2,
                schedule_date="2026-05-14",
                apply=False,
            ),
            db=db,
        )

        executed_sql = "\n".join(str(call.args[0]).lower() for call in db.execute.call_args_list)
        self.assertIn("status = 'paused'", executed_sql)
        self.assertIn("join tb_user", executed_sql)
        self.assertIn("substring_index(u.email, '@', -1)", executed_sql)
        self.assertIn("tb_user_social", executed_sql)
        self.assertNotIn("email like", executed_sql)
        params = db.execute.call_args_list[0].args[1]
        self.assertEqual(
            params["allowed_domains"],
            ["ai-reader.likenovel.dev", "ai-reader.likenovel.net"],
        )
        self.assertFalse(result["applied"])
        self.assertEqual(result["available_agent_count"], 3)
        self.assertEqual(result["missing_agent_count"], 0)
        self.assertEqual(len(result["preview"]), 2)
        self.assertTrue(result["dry_run_token"])
        db.commit.assert_not_awaited()

    async def test_resume_paused_ai_reader_agents_apply_reactivates_and_schedules(self):
        from app.schemas.admin import PostAiReaderResumePausedReqBody
        from app.services.admin import admin_ai_reader_service

        paused_agents = [
            {
                "ai_reader_agent_id": 11,
                "agent_key": "ai-reader-0011",
                "user_id": 111,
                "age_group": "20s",
                "gender": "F",
                "activity_pattern_json": json.dumps(
                    {"active_hours": [7, 20], "daily_session_target": 2}
                ),
                "daily_llm_budget": 8,
            },
            {
                "ai_reader_agent_id": 12,
                "agent_key": "ai-reader-0012",
                "user_id": 112,
                "age_group": "30s",
                "gender": "M",
                "activity_pattern_json": json.dumps(
                    {"active_hours": [8, 21], "daily_session_target": 2}
                ),
                "daily_llm_budget": 8,
            },
        ]
        dry_run_token = admin_ai_reader_service.build_ai_reader_resume_paused_dry_run_token(
            agent_count=2,
            schedule_date="2026-05-14",
            agent_fingerprints=[
                {
                    "ai_reader_agent_id": row["ai_reader_agent_id"],
                    "agent_key": row["agent_key"],
                    "user_id": row["user_id"],
                }
                for row in paused_agents
            ],
        )
        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([{"available_agent_count": 2}]),
            self._FakeMappingsResult(paused_agents),
            self._FakeMappingsResult([], rowcount=2),
            self._FakeMappingsResult([], rowcount=0),
            self._FakeMappingsResult([], rowcount=0),
            self._FakeMappingsResult([], rowcount=4),
        ]

        result = await admin_ai_reader_service.resume_paused_ai_reader_agents(
            req_body=PostAiReaderResumePausedReqBody(
                agent_count=2,
                schedule_date="2026-05-14",
                apply=True,
                dry_run_token=dry_run_token,
            ),
            db=db,
        )

        executed_sql = "\n".join(str(call.args[0]).lower() for call in db.execute.call_args_list)
        self.assertIn("for update", executed_sql)
        self.assertIn("status = 'active'", executed_sql)
        self.assertIn("where ai_reader_agent_id in", executed_sql)
        self.assertIn("delete from tb_ai_reader_daily_schedule", executed_sql)
        self.assertIn("insert into tb_ai_reader_daily_schedule", executed_sql)
        self.assertEqual(result["reactivated_agent_count"], 2)
        self.assertEqual(result["schedule_count"], 4)
        db.commit.assert_awaited_once()

    async def test_bootstrap_ai_reader_agents_requires_existing_prod_users_before_apply(self):
        from app.schemas.admin import PostAiReaderBootstrapReqBody
        from app.services.admin import admin_ai_reader_service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult(
            [
                {"user_id": 101, "email": "prod-ai-reader-0001@likenovel.internal"},
            ]
        )

        with self.assertRaises(Exception) as raised:
            await admin_ai_reader_service.bootstrap_ai_reader_agents(
                req_body=PostAiReaderBootstrapReqBody(
                    email_prefix="prod-ai-reader-",
                    agent_count=2,
                    schedule_date="2026-05-13",
                    apply=True,
                ),
                db=db,
            )

        self.assertIn("AI reader bootstrap requires", str(raised.exception))

    async def test_bootstrap_ai_reader_agents_rejects_like_wildcard_prefix(self):
        from app.schemas.admin import PostAiReaderBootstrapReqBody

        with self.assertRaises(ValueError):
            PostAiReaderBootstrapReqBody(
                email_prefix="prod-ai-reader-%",
                agent_count=100,
            )

    async def test_bootstrap_ai_reader_agents_dry_run_reports_missing_users(self):
        from app.schemas.admin import PostAiReaderBootstrapReqBody
        from app.services.admin import admin_ai_reader_service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult([])

        result = await admin_ai_reader_service.bootstrap_ai_reader_agents(
            req_body=PostAiReaderBootstrapReqBody(
                email_prefix="prod-ai-reader-",
                agent_count=100,
                schedule_date="2026-05-13",
                apply=False,
            ),
            db=db,
        )

        self.assertFalse(result["applied"])
        self.assertEqual(result["available_user_count"], 0)
        self.assertEqual(result["missing_user_count"], 100)
        self.assertIsNotNone(result["dry_run_token"])

    async def test_bootstrap_ai_reader_agents_only_uses_dedicated_ai_reader_accounts(self):
        from app.schemas.admin import PostAiReaderBootstrapReqBody
        from app.services.admin import admin_ai_reader_service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult(
            [
                {
                    "user_id": 201,
                    "email": "codex-age100c-20260512-clean-001@ai-reader.likenovel.dev",
                }
            ]
        )

        result = await admin_ai_reader_service.bootstrap_ai_reader_agents(
            req_body=PostAiReaderBootstrapReqBody(
                email_prefix="codex-age100c-20260512-clean-",
                agent_count=1,
                schedule_date="2026-05-14",
                apply=False,
            ),
            db=db,
        )

        executed_sql = "\n".join(str(call.args[0]).lower() for call in db.execute.call_args_list)
        self.assertIn("substring_index(email, '@', -1)", executed_sql)
        self.assertIn("not exists", executed_sql)
        self.assertIn("tb_user_social", executed_sql)
        self.assertIn("tb_ai_reader_agent", executed_sql)
        params = db.execute.call_args_list[0].args[1]
        self.assertEqual(
            params["allowed_domains"],
            ["ai-reader.likenovel.dev", "ai-reader.likenovel.net"],
        )
        self.assertEqual(result["available_user_count"], 1)

    def test_bootstrap_ai_reader_agents_caps_agent_count_at_100(self):
        from app.schemas.admin import PostAiReaderBootstrapReqBody

        with self.assertRaises(ValueError):
            PostAiReaderBootstrapReqBody(
                email_prefix="prod-ai-reader-",
                agent_count=101,
            )

    async def test_bootstrap_ai_reader_agents_dry_run_applies_activity_preset(self):
        from app.schemas.admin import PostAiReaderBootstrapReqBody
        from app.services.admin import admin_ai_reader_service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult(
            [
                {
                    "user_id": 100 + index,
                    "email": f"prod-ai-reader-{index:04d}@likenovel.internal",
                }
                for index in range(10)
            ]
        )

        result = await admin_ai_reader_service.bootstrap_ai_reader_agents(
            req_body=PostAiReaderBootstrapReqBody(
                email_prefix="prod-ai-reader-",
                agent_count=10,
                schedule_date="2026-05-13",
                apply=False,
                active_hours=[9, 20],
                daily_session_target=3,
                age_group_ratios={"20s": 60, "30s": 40},
                gender_ratios={"M": 70, "F": 30},
            ),
            db=db,
        )

        preview = result["preview"]
        self.assertEqual(len(preview), 10)
        self.assertEqual(
            {item["age_group"] for item in preview},
            {"20s", "30s"},
        )
        self.assertEqual(
            sum(1 for item in preview if item["age_group"] == "20s"),
            6,
        )
        self.assertEqual(
            sum(1 for item in preview if item["age_group"] == "30s"),
            4,
        )
        self.assertEqual(sum(1 for item in preview if item["gender"] == "M"), 7)
        self.assertEqual(sum(1 for item in preview if item["gender"] == "F"), 3)
        for item in preview:
            self.assertEqual(item["activity_pattern"]["active_hours"], [9, 20])
            self.assertEqual(item["activity_pattern"]["daily_session_target"], 3)

    async def test_bootstrap_ai_reader_agents_apply_requires_matching_dry_run_token(self):
        from app.schemas.admin import PostAiReaderBootstrapReqBody
        from app.services.admin import admin_ai_reader_service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult(
            [
                {"user_id": 101, "email": "prod-ai-reader-0001@likenovel.internal"},
            ]
        )

        with self.assertRaises(Exception) as raised:
            await admin_ai_reader_service.bootstrap_ai_reader_agents(
                req_body=PostAiReaderBootstrapReqBody(
                    email_prefix="prod-ai-reader-",
                    agent_count=1,
                    schedule_date="2026-05-13",
                    apply=True,
                    dry_run_token=admin_ai_reader_service.build_ai_reader_bootstrap_dry_run_token(
                        email_prefix="prod-ai-reader-",
                        agent_count=1,
                        schedule_date="2026-05-13",
                        allow_partial=False,
                        agent_index_offset=0,
                        daily_llm_budget=8,
                        user_fingerprints=[
                            {
                                "user_id": 999,
                                "email": "prod-ai-reader-0001@likenovel.internal",
                                "agent_key": "ai-reader-0000",
                            }
                        ],
                    ),
                ),
                db=db,
            )

        self.assertIn("matching dry-run token is required", str(raised.exception))

    async def test_bootstrap_ai_reader_agents_rejects_agent_key_user_mismatch(self):
        from app.schemas.admin import PostAiReaderBootstrapReqBody
        from app.services.admin import admin_ai_reader_service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult(
                [
                    {"user_id": 101, "email": "prod-ai-reader-0001@likenovel.internal"},
                ]
            ),
            self._FakeMappingsResult(
                [
                    {
                        "agent_key": "ai-reader-0000",
                        "user_id": 999,
                    }
                ]
            ),
        ]

        dry_run_token = admin_ai_reader_service.build_ai_reader_bootstrap_dry_run_token(
            email_prefix="prod-ai-reader-",
            agent_count=1,
            schedule_date="2026-05-13",
            allow_partial=False,
            agent_index_offset=0,
            daily_llm_budget=8,
            user_fingerprints=[
                {
                    "user_id": 101,
                    "email": "prod-ai-reader-0001@likenovel.internal",
                    "agent_key": "ai-reader-0000",
                }
            ],
        )

        with self.assertRaises(Exception) as raised:
            await admin_ai_reader_service.bootstrap_ai_reader_agents(
                req_body=PostAiReaderBootstrapReqBody(
                    email_prefix="prod-ai-reader-",
                    agent_count=1,
                    schedule_date="2026-05-13",
                    apply=True,
                    dry_run_token=dry_run_token,
                ),
                db=db,
            )

        self.assertIn("AI reader agent identity conflict", str(raised.exception))

    async def test_bootstrap_ai_reader_agents_rechecks_agent_rows_after_upsert(self):
        from app.schemas.admin import PostAiReaderBootstrapReqBody
        from app.services.admin import admin_ai_reader_service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult(
                [
                    {"user_id": 101, "email": "prod-ai-reader-0001@likenovel.internal"},
                ]
            ),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult(
                [
                    {
                        "ai_reader_agent_id": 11,
                        "agent_key": "ai-reader-0000",
                        "user_id": 999,
                        "activity_pattern_json": json.dumps(
                            {"active_hours": [6, 7], "daily_session_target": 1}
                        ),
                    },
                ]
            ),
        ]
        dry_run_token = admin_ai_reader_service.build_ai_reader_bootstrap_dry_run_token(
            email_prefix="prod-ai-reader-",
            agent_count=1,
            schedule_date="2026-05-13",
            allow_partial=False,
            agent_index_offset=0,
            daily_llm_budget=8,
            user_fingerprints=[
                {
                    "user_id": 101,
                    "email": "prod-ai-reader-0001@likenovel.internal",
                    "agent_key": "ai-reader-0000",
                }
            ],
        )

        with self.assertRaises(Exception) as raised:
            await admin_ai_reader_service.bootstrap_ai_reader_agents(
                req_body=PostAiReaderBootstrapReqBody(
                    email_prefix="prod-ai-reader-",
                    agent_count=1,
                    schedule_date="2026-05-13",
                    apply=True,
                    dry_run_token=dry_run_token,
                ),
                db=db,
            )

        self.assertIn("AI reader agent post-write mismatch", str(raised.exception))

    async def test_bootstrap_ai_reader_agents_replaces_schedules_in_bulk_for_scale(self):
        from app.schemas.admin import PostAiReaderBootstrapReqBody
        from app.services.admin import admin_ai_reader_service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult(
                [
                    {"user_id": 101, "email": "prod-ai-reader-0001@likenovel.internal"},
                    {"user_id": 102, "email": "prod-ai-reader-0002@likenovel.internal"},
                ]
            ),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([], rowcount=2),
            self._FakeMappingsResult(
                [
                    {
                        "ai_reader_agent_id": 11,
                        "agent_key": "ai-reader-0000",
                        "user_id": 101,
                        "activity_pattern_json": json.dumps(
                            {"active_hours": [6, 7], "daily_session_target": 1}
                        ),
                    },
                    {
                        "ai_reader_agent_id": 12,
                        "agent_key": "ai-reader-0001",
                        "user_id": 102,
                        "activity_pattern_json": json.dumps(
                            {"active_hours": [20, 21], "daily_session_target": 1}
                        ),
                    },
                ]
            ),
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult([], rowcount=4),
            self._FakeMappingsResult([], rowcount=2),
        ]
        dry_run_token = admin_ai_reader_service.build_ai_reader_bootstrap_dry_run_token(
            email_prefix="prod-ai-reader-",
            agent_count=2,
            schedule_date="2026-05-13",
            allow_partial=False,
            agent_index_offset=0,
            daily_llm_budget=8,
            user_fingerprints=[
                {
                    "user_id": 101,
                    "email": "prod-ai-reader-0001@likenovel.internal",
                    "agent_key": "ai-reader-0000",
                },
                {
                    "user_id": 102,
                    "email": "prod-ai-reader-0002@likenovel.internal",
                    "agent_key": "ai-reader-0001",
                },
            ],
        )

        result = await admin_ai_reader_service.bootstrap_ai_reader_agents(
            req_body=PostAiReaderBootstrapReqBody(
                email_prefix="prod-ai-reader-",
                agent_count=2,
                schedule_date="2026-05-13",
                apply=True,
                dry_run_token=dry_run_token,
            ),
            db=db,
        )

        executed_sql = "\n".join(str(call.args[0]).lower() for call in db.execute.call_args_list)
        self.assertEqual(executed_sql.count("delete from tb_ai_reader_daily_schedule"), 1)
        self.assertIn("ai_reader_agent_id in", executed_sql)
        self.assertIn("used_session_count > 0", executed_sql)
        self.assertIn("status = 'done'", executed_sql)
        self.assertIn("status = 'ready'", executed_sql)
        self.assertIn("used_session_count = 0", executed_sql)
        self.assertEqual(executed_sql.count("insert into tb_ai_reader_daily_schedule"), 1)
        self.assertEqual(result["applied_count"], 2)
        self.assertEqual(result["schedule_count"], 2)


class AiReaderSessionPlannerTest(unittest.IsolatedAsyncioTestCase):
    class _FakeMappingsResult:
        def __init__(self, rows, rowcount=1, inserted_primary_key=None, lastrowid=None):
            self._rows = rows
            self.rowcount = rowcount
            self.inserted_primary_key = inserted_primary_key
            self.lastrowid = lastrowid

        def mappings(self):
            return self

        def all(self):
            return self._rows

        def one_or_none(self):
            return self._rows[0] if self._rows else None

    class _TextInsertResult:
        def __init__(self, *, rowcount=1, lastrowid=None):
            self.rowcount = rowcount
            self.lastrowid = lastrowid

        @property
        def inserted_primary_key(self):
            raise InvalidRequestError("Statement is not an insert() expression construct.")

    async def test_claim_due_reader_sessions_uses_window_budget_and_skip_locked(self):
        from app.services.ai import reader_agent_session_service as service

        events = []
        db = AsyncMock()
        db.in_transaction = lambda: False

        @asynccontextmanager
        async def fake_begin():
            events.append("begin")
            try:
                yield
            finally:
                events.append("end")

        db.begin = fake_begin
        db.execute.side_effect = [
            self._FakeMappingsResult([], rowcount=0),
            self._FakeMappingsResult([], rowcount=0),
            self._FakeMappingsResult([], rowcount=0),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult(
                [
                    {
                        "ai_reader_schedule_id": 1,
                        "ai_reader_agent_id": 7,
                        "user_id": 100,
                        "age_group": "30s",
                        "gender": "M",
                        "persona_json": "{}",
                        "taste_memory_json": "{}",
                        "activity_pattern_json": "{}",
                        "claimed_session_no": 2,
                    }
                ]
            ),
            self._FakeMappingsResult([], rowcount=1),
        ]

        sessions = await service.claim_due_reader_sessions(
            db,
            worker_id="session-worker-a",
            limit=10,
        )
        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)
        claim_update_sql = str(db.execute.await_args_list[-1].args[0]).lower()

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].ai_reader_schedule_id, 1)
        self.assertEqual(sessions[0].claimed_session_no, 2)
        self.assertEqual(events, ["begin", "end"])
        self.assertIn("tb_ai_reader_daily_schedule", executed_sql)
        self.assertIn("s.used_session_count < s.session_budget", executed_sql)
        self.assertIn("force index (idx_ai_reader_daily_schedule_stale)", executed_sql.lower())
        self.assertIn("force index (idx_ai_reader_daily_schedule_due)", executed_sql.lower())
        self.assertIn("straight_join tb_ai_reader_agent", executed_sql.lower())
        self.assertIn("join tb_user", executed_sql.lower())
        self.assertIn("substring_index(u.email, '@', -1)", executed_sql.lower())
        self.assertIn("tb_user_social", executed_sql.lower())
        self.assertIn("active_start_at <= current_timestamp", executed_sql)
        self.assertIn("active_end_at > current_timestamp", executed_sql)
        self.assertIn("tb_ai_reader_llm_decision", executed_sql)
        self.assertIn("a.daily_llm_budget", executed_sql)
        self.assertIn("d.created_date >= current_date()", executed_sql)
        self.assertIn("d.created_date < current_date() + interval 1 day", executed_sql)
        self.assertIn("d.decision_status in", executed_sql.lower())
        self.assertIn("for update skip locked", executed_sql.lower())
        self.assertIn("status = 'running'", claim_update_sql)
        self.assertIn("locked_by = :worker_id", executed_sql)
        self.assertLess(
            claim_update_sql.index("used_session_count = used_session_count + case"),
            claim_update_sql.index("status = 'running'"),
        )
        self.assertIn(
            "s.locked_at <= timestampadd(second, -:lease_timeout_seconds, current_timestamp)",
            executed_sql.lower(),
        )
        self.assertNotIn("timestampdiff(second, s.locked_at, current_timestamp)", executed_sql.lower())
        self.assertIn("used_session_count = used_session_count + case", executed_sql.lower())
        self.assertIn("as claimed_session_no", executed_sql.lower())
        self.assertIn("lease_timeout_seconds", str(db.execute.await_args_list[0].args[1]))

    async def test_ensure_reader_daily_schedules_creates_missing_dates_without_cleaning_history(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult(
                [
                    {
                        "ai_reader_agent_id": 7,
                        "activity_pattern_json": json.dumps(
                            {"active_hours": [6, 7], "daily_session_target": 1}
                        ),
                    }
                ]
            ),
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult(
                [
                    {
                        "ai_reader_agent_id": 8,
                        "activity_pattern_json": json.dumps(
                            {"active_hours": [20, 21], "daily_session_target": 1}
                        ),
                    }
                ]
            ),
            self._FakeMappingsResult([], rowcount=1),
        ]

        result = await service.ensure_reader_daily_schedules(
            db,
            schedule_dates=[date(2026, 5, 13), date(2026, 5, 14)],
            limit=1000,
        )

        executed_sql = "\n".join(str(call.args[0]).lower() for call in db.execute.call_args_list)
        self.assertIn("not exists", executed_sql)
        self.assertIn("join tb_user u", executed_sql)
        self.assertIn("substring_index(u.email, '@', -1)", executed_sql)
        self.assertIn("tb_user_social", executed_sql)
        self.assertNotIn("delete from tb_ai_reader_daily_schedule", executed_sql)
        self.assertEqual(result["date_count"], 2)
        self.assertEqual(result["missing_agent_count"], 2)
        self.assertEqual(result["created_schedule_count"], 2)

    async def test_upsert_reader_daily_schedule_windows_preserves_used_session_count(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult([], rowcount=1)

        await service.upsert_reader_daily_schedule_windows(
            db,
            [
                service.ReaderDailyScheduleWindow(
                    ai_reader_agent_id=7,
                    schedule_date=date(2026, 5, 13),
                    active_start_at=__import__("datetime").datetime(2026, 5, 13, 20, 0),
                    active_end_at=__import__("datetime").datetime(2026, 5, 13, 22, 0),
                    session_budget=1,
                )
            ],
        )

        executed_sql = str(db.execute.await_args.args[0]).lower()
        self.assertIn("when status = 'running' then used_session_count", executed_sql)
        self.assertIn("when used_session_count > 0 then used_session_count", executed_sql)
        self.assertIn("when status = 'done' then status", executed_sql)
        self.assertLess(
            executed_sql.index("when status = 'done' then status"),
            executed_sql.index("when used_session_count >= values(session_budget) then 'done'"),
        )

    async def test_cleanup_expired_stale_reader_sessions_marks_schedule_and_pending_audit_failed(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult([], rowcount=2),
        ]

        affected = await service.cleanup_expired_stale_reader_sessions(
            db,
            lease_timeout_seconds=900,
        )
        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertEqual(affected, 2)
        self.assertIn("update tb_ai_reader_llm_decision d", executed_sql.lower())
        self.assertIn("d.session_id like concat(s.ai_reader_schedule_id, ':%')", executed_sql.lower())
        self.assertNotIn("d.ai_reader_schedule_id", executed_sql.lower())
        self.assertIn("decision_status = 'failed'", executed_sql.lower())
        self.assertIn("update tb_ai_reader_daily_schedule", executed_sql.lower())
        self.assertIn("active_end_at <= current_timestamp", executed_sql.lower())
        self.assertIn("locked_at <= timestampadd(second, -:lease_timeout_seconds, current_timestamp)", executed_sql.lower())
        self.assertIn("set status = 'failed'", executed_sql.lower())

    async def test_cleanup_budget_exhausted_ready_reader_sessions_closes_due_ready_windows(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult([], rowcount=3)

        affected = await service.cleanup_budget_exhausted_ready_reader_sessions(db)
        executed_sql = str(db.execute.await_args.args[0]).lower()

        self.assertEqual(affected, 3)
        self.assertIn("update tb_ai_reader_daily_schedule s", executed_sql)
        self.assertIn("join tb_ai_reader_agent a", executed_sql)
        self.assertIn("join tb_user u", executed_sql)
        self.assertIn("substring_index(u.email, '@', -1)", executed_sql)
        self.assertIn("tb_user_social", executed_sql)
        self.assertIn("set s.status = 'done'", executed_sql)
        self.assertIn("daily llm budget exhausted", executed_sql)
        self.assertIn("s.status = 'ready'", executed_sql)
        self.assertIn("s.used_session_count < s.session_budget", executed_sql)
        self.assertIn("s.active_start_at <= current_timestamp", executed_sql)
        self.assertIn("s.active_end_at > current_timestamp", executed_sql)
        self.assertIn("a.status = 'active'", executed_sql)
        self.assertIn(">= a.daily_llm_budget", executed_sql)
        self.assertIn("tb_ai_reader_llm_decision", executed_sql)
        self.assertIn("d.decision_status in ('pending', 'success', 'failed')", executed_sql)

    async def test_claim_due_reader_sessions_prefers_stale_running_before_ready(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.in_transaction = lambda: False

        @asynccontextmanager
        async def fake_begin():
            yield

        db.begin = fake_begin
        db.execute.side_effect = [
            self._FakeMappingsResult([], rowcount=0),
            self._FakeMappingsResult([], rowcount=0),
            self._FakeMappingsResult([], rowcount=0),
            self._FakeMappingsResult(
                [
                    {
                        "ai_reader_schedule_id": 9,
                        "ai_reader_agent_id": 7,
                        "user_id": 100,
                        "age_group": "30s",
                        "gender": "M",
                        "persona_json": "{}",
                        "taste_memory_json": "{}",
                        "activity_pattern_json": "{}",
                        "claimed_session_no": 1,
                    }
                ]
            ),
            self._FakeMappingsResult([], rowcount=1),
        ]

        sessions = await service.claim_due_reader_sessions(
            db,
            worker_id="session-worker-a",
            limit=1,
        )
        executed_sql = [str(call.args[0]).lower() for call in db.execute.await_args_list]
        executed_sql_joined = "\n".join(executed_sql)

        self.assertEqual([session.ai_reader_schedule_id for session in sessions], [9])
        self.assertIn("force index (idx_ai_reader_daily_schedule_stale)", executed_sql_joined)
        self.assertNotIn("force index (idx_ai_reader_daily_schedule_due)", executed_sql_joined)
        self.assertIn("used_session_count = used_session_count + case", executed_sql[-1])

    async def test_claim_due_reader_sessions_allows_stale_pending_decision_when_daily_budget_is_full(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.in_transaction = lambda: False

        @asynccontextmanager
        async def fake_begin():
            yield

        db.begin = fake_begin
        db.execute.side_effect = [
            self._FakeMappingsResult([], rowcount=0),
            self._FakeMappingsResult([], rowcount=0),
            self._FakeMappingsResult([], rowcount=0),
            self._FakeMappingsResult(
                [
                    {
                        "ai_reader_schedule_id": 9,
                        "ai_reader_agent_id": 7,
                        "user_id": 100,
                        "age_group": "30s",
                        "gender": "M",
                        "persona_json": "{}",
                        "taste_memory_json": "{}",
                        "activity_pattern_json": "{}",
                        "claimed_session_no": 2,
                    }
                ]
            ),
            self._FakeMappingsResult([], rowcount=1),
        ]

        sessions = await service.claim_due_reader_sessions(
            db,
            worker_id="session-worker-a",
            limit=1,
        )
        executed_sql = "\n".join(str(call.args[0]).lower() for call in db.execute.await_args_list)
        compact_sql = " ".join(executed_sql.split())
        stale_params = db.execute.await_args_list[3].args[1]

        self.assertEqual([session.claimed_session_no for session in sessions], [2])
        self.assertIn("count(*)", executed_sql)
        self.assertIn("< a.daily_llm_budget", executed_sql)
        self.assertIn("or (", executed_sql)
        self.assertIn("and exists", executed_sql)
        self.assertIn("d_existing.decision_status = 'pending'", executed_sql)
        self.assertIn("d_existing.session_id = concat(", compact_sql)
        self.assertIn("s.ai_reader_schedule_id", compact_sql)
        self.assertIn("greatest(s.used_session_count, 1)", compact_sql)
        self.assertIn("prompt_version", stale_params)

    def test_build_reader_daily_schedule_windows_uses_activity_pattern_budget(self):
        from app.services.ai import reader_agent_session_service as service

        windows = service.build_reader_daily_schedule_windows(
            ai_reader_agent_id=7,
            schedule_date=date(2026, 5, 7),
            activity_pattern={
                "active_hours": [7, 8, 12, 20, 21, 22],
                "daily_session_target": 3,
            },
        )

        self.assertEqual(len(windows), 3)
        self.assertEqual(sum(window.session_budget for window in windows), 3)
        self.assertEqual(
            [window.active_start_at.hour for window in windows],
            [7, 12, 20],
        )
        self.assertEqual(
            [window.active_end_at.hour for window in windows],
            [9, 13, 23],
        )
        self.assertEqual({window.schedule_date for window in windows}, {date(2026, 5, 7)})

    def test_build_reader_daily_schedule_windows_keeps_midnight_window_contiguous(self):
        from app.services.ai import reader_agent_session_service as service

        windows = service.build_reader_daily_schedule_windows(
            ai_reader_agent_id=7,
            schedule_date=date(2026, 5, 7),
            activity_pattern={
                "active_hours": [22, 23, 0],
                "daily_session_target": 1,
            },
        )

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].active_start_at.date(), date(2026, 5, 7))
        self.assertEqual(windows[0].active_start_at.hour, 22)
        self.assertEqual(windows[0].active_end_at.date(), date(2026, 5, 8))
        self.assertEqual(windows[0].active_end_at.hour, 1)
        self.assertEqual(windows[0].session_budget, 1)

    async def test_upsert_reader_daily_schedule_windows_preserves_running_schedule(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult([], rowcount=2)
        windows = service.build_reader_daily_schedule_windows(
            ai_reader_agent_id=7,
            schedule_date=date(2026, 5, 7),
            activity_pattern={
                "active_hours": [20, 21],
                "daily_session_target": 2,
            },
        )

        affected = await service.upsert_reader_daily_schedule_windows(db, windows)
        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertEqual(affected, 2)
        self.assertIn("insert into tb_ai_reader_daily_schedule", executed_sql)
        self.assertIn("on duplicate key update", executed_sql.lower())
        self.assertIn("when status = 'running' then status", executed_sql.lower())
        self.assertIn("when status = 'running' then used_session_count", executed_sql.lower())
        self.assertIn("when used_session_count > 0 then used_session_count", executed_sql.lower())

    def test_reader_engagement_context_suggests_actions_after_strong_match(self):
        from app.services.ai import reader_agent_session_service as service

        target = {
            "worldview_tags": '["현대", "게이트"]',
            "protagonist_job_tags": '["헌터"]',
            "protagonist_material_tags": '["테이밍", "시스템"]',
            "axis_style_tags": '["모험", "유쾌"]',
            "axis_romance_tags": "[]",
            "protagonist_type_tags": '["성장형"]',
            "protagonist_goal_primary": "던전운영",
        }
        persona = {
            "initial_axis_bias": {
                "세": {"현대": 0.8, "게이트": 0.8},
                "직": {"헌터": 0.8},
                "능": {"테이밍": 0.8, "시스템": 0.5},
                "작": {"모험": 0.6, "유쾌": 0.4},
            },
            "bookmark_threshold": 0.55,
            "recommend_threshold": 0.7,
            "rating_severity": 0.3,
        }
        state = {
            "read_episode_count": 4,
            "bookmarked_yn": "N",
            "recommended_yn": "N",
            "evaluated_yn": "N",
        }

        context = service._build_reader_engagement_context(
            target,
            persona=persona,
            state=state,
            taste_factors=[],
        )

        self.assertGreaterEqual(context["engagement_score_hint"], 0.7)
        self.assertTrue(context["action_affordances"]["bookmark"]["suggested"])
        self.assertTrue(context["action_affordances"]["recommend"]["suggested"])
        self.assertTrue(context["action_affordances"]["evaluate"]["suggested"])
        self.assertIn("테이밍", context["matched_persona_labels"])
        bayesian = context["bayesian_action_model"]
        self.assertEqual(bayesian["loose_stop_evidence_weight"], 0.1)
        self.assertIn("continue_next_episode", bayesian["probabilities"])
        self.assertIn("recommend", bayesian["probabilities"])
        self.assertIn("evaluate", bayesian["probabilities"])
        self.assertGreaterEqual(
            bayesian["probabilities"]["continue_next_episode"]["posterior_hint"],
            bayesian["probabilities"]["continue_next_episode"]["prior"],
        )
        self.assertEqual(
            bayesian["probabilities"]["continue_next_episode"]["target_episode_no"],
            1,
        )

    def test_reader_engagement_context_uses_bayesian_posterior_for_recommend_hint(self):
        from app.services.ai import reader_agent_session_service as service

        target = {
            "worldview_tags": '["던전"]',
            "protagonist_job_tags": '["기사"]',
            "protagonist_material_tags": "[]",
            "axis_style_tags": '["전략"]',
            "axis_romance_tags": "[]",
            "protagonist_type_tags": "[]",
            "protagonist_goal_primary": "",
            "episode_no": 7,
        }
        persona = {
            "initial_axis_bias": {
                "세": {"던전": 0.8},
                "직": {"기사": 0.8},
                "작": {"전략": 0.8},
            },
            "recommend_threshold": 0.78,
            "loose_stop_weight": 0.1,
        }
        state = {
            "read_episode_count": 6,
            "bookmarked_yn": "N",
            "recommended_yn": "N",
            "evaluated_yn": "N",
        }

        context = service._build_reader_engagement_context(
            target,
            persona=persona,
            state=state,
            taste_factors=[],
        )

        recommend = context["action_affordances"]["recommend"]
        self.assertLess(recommend["score"], recommend["threshold"])
        self.assertGreaterEqual(
            recommend["posterior_hint"],
            recommend["posterior_threshold"],
        )
        self.assertTrue(recommend["suggested"])

    async def test_process_reader_session_persists_decision_and_enqueues_actions(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.in_transaction = lambda: False

        @asynccontextmanager
        async def fake_begin():
            yield

        db.begin = fake_begin
        db.execute.side_effect = [
            self._FakeMappingsResult(
                [
                    {"factor_type": "worldview", "factor_key": "현대", "score": 0.8},
                    {"factor_type": "style", "factor_key": "빠른전개", "score": 0.7},
                ]
            ),
            self._FakeMappingsResult(
                [
                    {
                        "product_id": 200,
                        "title": "테스트 작품",
                        "status_code": "ongoing",
                        "count_hit": 10,
                        "count_bookmark": 2,
                        "count_recommend": 1,
                        "episode_id": 300,
                        "episode_no": 1,
                        "episode_title": "첫 회",
                        "episode_summary_text": "각성자가 탑에 오른다.",
                        "protagonist_type_tags": '["성장형"]',
                        "protagonist_job_tags": '["헌터"]',
                        "protagonist_material_tags": '["상태창"]',
                        "worldview_tags": '["현대"]',
                        "axis_style_tags": '["빠른전개"]',
                        "axis_romance_tags": "[]",
                        "ai_reader_product_state_id": None,
                    }
                ]
            ),
            self._FakeMappingsResult(
                [
                    {
                        "state": "reading",
                        "read_episode_count": 1,
                        "bookmarked_yn": "N",
                        "recommended_yn": "N",
                        "evaluated_yn": "N",
                    }
                ]
            ),
            self._FakeMappingsResult(
                [{"daily_llm_budget": 1, "used_llm_count": 0}]
            ),
            self._FakeMappingsResult([], rowcount=1, inserted_primary_key=[91]),
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([], rowcount=6),
        ]

        async def fake_llm(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
            self.assertIn("테스트 작품", user_prompt)
            self.assertIn("30s", user_prompt)
            self.assertIn("early_episode_summary_text", user_prompt)
            self.assertNotIn('"summary": "각성자가 탑에 오른다."', user_prompt)
            return """
            {
              "continue_reading": true,
              "next_episode_count": 1,
              "drop_product": false,
              "bookmark_action": "add",
              "recommend_action": "press",
              "evaluation": {"should_evaluate": false, "eval_code": null},
              "taste_delta": {"positive": ["성장형"], "negative": []},
              "reason": "취향과 맞아 다음 화를 본다"
            }
            """

        session = service.ReaderClaimedSession(
            ai_reader_schedule_id=1,
            ai_reader_agent_id=7,
            user_id=100,
            age_group="30s",
            gender="M",
            persona_json='{"patience": 0.6}',
            taste_memory_json="{}",
            activity_pattern_json='{"active_hours": [20, 21]}',
        )

        result = await service.process_reader_session_decision(
            session,
            db,
            llm_call=fake_llm,
        )
        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertEqual(result.llm_decision_id, 91)
        self.assertEqual(result.enqueued_action_count, 4)
        self.assertEqual(
            [(a.action_type, a.target_value) for a in result.actions],
            [("read", ""), ("next_episode", "1"), ("bookmark", "Y"), ("recommend", "Y")],
        )
        self.assertIn("tb_product_ai_metadata", executed_sql)
        self.assertIn("tb_user_taste_factor_score", executed_sql)
        self.assertIn("insert into tb_ai_reader_llm_decision", executed_sql)
        self.assertIn("insert into tb_ai_reader_action_queue", executed_sql)
        self.assertLess(
            executed_sql.lower().index("from tb_ai_reader_action_queue"),
            executed_sql.lower().index("insert into tb_ai_reader_action_queue"),
        )
        self.assertIn("active_scope_key", executed_sql)
        self.assertIn("on duplicate key update", executed_sql)
        enqueue_call = next(
            call
            for call in db.execute.await_args_list
            if "insert into tb_ai_reader_action_queue" in str(call.args[0])
        )
        enqueue_sql = str(enqueue_call.args[0])
        self.assertIn("active_scope_key = active_scope_key", enqueue_sql)
        self.assertNotIn("llm_decision_id = values(llm_decision_id)", enqueue_sql)
        self.assertNotIn("decision_json = values(decision_json)", enqueue_sql)
        enqueued_params = enqueue_call.args[1]
        self.assertTrue(all(row["active_scope_key"] for row in enqueued_params))
        self.assertTrue(all(len(row["active_scope_key"]) == 64 for row in enqueued_params))

    async def test_process_reader_session_reserves_pending_before_llm_call(self):
        from app.services.ai import reader_agent_session_service as service

        events = []
        db = AsyncMock()
        db.in_transaction = lambda: False

        @asynccontextmanager
        async def fake_begin():
            events.append("begin")
            try:
                yield
            finally:
                events.append("end")

        async def fake_execute(statement, *args, **kwargs):
            sql = str(statement).lower()
            if "from tb_user_taste_factor_score" in sql:
                return self._FakeMappingsResult([])
            if "from tb_product p" in sql:
                return self._FakeMappingsResult(
                    [
                        {
                            "product_id": 200,
                            "title": "테스트 작품",
                            "status_code": "ongoing",
                            "count_hit": 10,
                            "count_bookmark": 2,
                            "count_recommend": 1,
                            "episode_id": 300,
                            "episode_no": 1,
                            "episode_title": "첫 회",
                            "episode_summary_text": "각성자가 탑에 오른다.",
                            "protagonist_goal_primary": "탑등반",
                            "protagonist_type_tags": '["성장형"]',
                            "protagonist_job_tags": '["헌터"]',
                            "protagonist_material_tags": '["상태창"]',
                            "worldview_tags": '["현대"]',
                            "axis_style_tags": '["빠른전개"]',
                            "axis_romance_tags": "[]",
                            "ai_reader_product_state_id": None,
                        }
                    ]
                )
            if "from tb_ai_reader_product_state" in sql:
                return self._FakeMappingsResult([])
            if "select a.daily_llm_budget" in sql:
                events.append("budget")
                return self._FakeMappingsResult(
                    [{"daily_llm_budget": 1, "used_llm_count": 0}]
                )
            if "insert into tb_ai_reader_llm_decision" in sql:
                events.append("reserve")
                self.assertIn("'pending'", sql)
                return self._FakeMappingsResult([], rowcount=1, inserted_primary_key=[91])
            if "update tb_ai_reader_llm_decision" in sql:
                events.append("success")
                self.assertIn("decision_status = 'success'", sql)
                return self._FakeMappingsResult([], rowcount=1)
            if "from tb_ai_reader_action_queue" in sql:
                events.append("cleanup")
                self.assertIn("active_scope_key in", sql)
                return self._FakeMappingsResult([])
            if "insert into tb_ai_reader_action_queue" in sql:
                events.append("enqueue")
                return self._FakeMappingsResult([], rowcount=2)
            raise AssertionError(f"unexpected sql: {statement}")

        async def fake_llm(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
            self.assertIn("reserve", events)
            events.append("llm")
            return """
            {
              "continue_reading": true,
              "next_episode_count": 1,
              "drop_product": false,
              "bookmark_action": "none",
              "recommend_action": "none",
              "evaluation": {"should_evaluate": false, "eval_code": null},
              "taste_delta": {"positive": [], "negative": []},
              "reason": "다음 화를 본다"
            }
            """

        db.begin = fake_begin
        db.execute.side_effect = fake_execute
        session = service.ReaderClaimedSession(
            ai_reader_schedule_id=1,
            ai_reader_agent_id=7,
            user_id=100,
            age_group="30s",
            gender="M",
            persona_json="{}",
            taste_memory_json="{}",
            activity_pattern_json="{}",
        )

        result = await service.process_reader_session_decision(
            session,
            db,
            llm_call=fake_llm,
        )

        self.assertEqual(result.llm_decision_id, 91)
        self.assertEqual(
            events,
            [
                "begin",
                "budget",
                "reserve",
                "end",
                "llm",
                "begin",
                "success",
                "cleanup",
                "enqueue",
                "end",
            ],
        )

    async def test_process_reader_session_does_not_call_llm_when_daily_budget_exhausted(self):
        from app.services.ai import reader_agent_session_service as service

        events = []
        db = AsyncMock()
        db.in_transaction = lambda: False

        @asynccontextmanager
        async def fake_begin():
            yield

        db.begin = fake_begin
        db.execute.side_effect = [
            self._FakeMappingsResult([]),
            self._FakeMappingsResult(
                [
                    {
                        "product_id": 200,
                        "title": "테스트 작품",
                        "status_code": "ongoing",
                        "count_hit": 10,
                        "count_bookmark": 2,
                        "count_recommend": 1,
                        "episode_id": 300,
                        "episode_no": 1,
                        "episode_title": "첫 회",
                        "episode_summary_text": "각성자가 탑에 오른다.",
                        "protagonist_goal_primary": "탑등반",
                        "protagonist_type_tags": "[]",
                        "protagonist_job_tags": "[]",
                        "protagonist_material_tags": "[]",
                        "worldview_tags": "[]",
                        "axis_style_tags": "[]",
                        "axis_romance_tags": "[]",
                        "ai_reader_product_state_id": None,
                    }
                ]
            ),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult(
                [{"daily_llm_budget": 1, "used_llm_count": 1}]
            ),
            self._FakeMappingsResult([]),
        ]

        async def fake_llm(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
            events.append("llm")
            return "{}"

        session = service.ReaderClaimedSession(
            ai_reader_schedule_id=1,
            ai_reader_agent_id=7,
            user_id=100,
            age_group="30s",
            gender="M",
            persona_json="{}",
            taste_memory_json="{}",
            activity_pattern_json="{}",
        )

        with self.assertRaises(service.InvalidReaderSessionError):
            await service.process_reader_session_decision(session, db, llm_call=fake_llm)

        self.assertEqual(events, [])

    async def test_reserve_reader_llm_decision_does_not_overwrite_existing_session_audit(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult(
                [{"daily_llm_budget": 2, "used_llm_count": 1}]
            ),
            self._FakeMappingsResult([], rowcount=2, inserted_primary_key=[], lastrowid=91),
            self._FakeMappingsResult(
                [{"ai_reader_llm_decision_id": 91, "decision_status": "success"}]
            ),
        ]
        session = service.ReaderClaimedSession(
            ai_reader_schedule_id=1,
            ai_reader_agent_id=7,
            user_id=100,
            age_group="30s",
            gender="M",
            persona_json="{}",
            taste_memory_json="{}",
            activity_pattern_json="{}",
        )

        with self.assertRaises(service.ReaderLlmDecisionAlreadyReservedError):
            await service.reserve_reader_llm_decision(
                session=session,
                snapshot={
                    "product": {"product_id": 200},
                    "episode": {"episode_id": 300},
                },
                db=db,
            )

        reserve_call = db.execute.await_args_list[1]
        reserve_sql = str(reserve_call.args[0])
        self.assertIn("last_insert_id(ai_reader_llm_decision_id)", reserve_sql.lower())
        self.assertNotIn("decision_status = 'pending'", reserve_sql)
        self.assertNotIn("decision_json = null", reserve_sql)
        self.assertNotIn("error_message = null", reserve_sql)

    async def test_reserve_reader_llm_decision_uses_lastrowid_for_text_insert(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult(
                [{"daily_llm_budget": 2, "used_llm_count": 1}]
            ),
            self._TextInsertResult(rowcount=1, lastrowid=91),
        ]
        session = service.ReaderClaimedSession(
            ai_reader_schedule_id=1,
            ai_reader_agent_id=7,
            user_id=100,
            age_group="30s",
            gender="M",
            persona_json="{}",
            taste_memory_json="{}",
            activity_pattern_json="{}",
        )

        llm_decision_id = await service.reserve_reader_llm_decision(
            session=session,
            snapshot={
                "product": {"product_id": 200},
                "episode": {"episode_id": 300},
            },
            db=db,
        )

        self.assertEqual(llm_decision_id, 91)
        reserve_params = db.execute.await_args_list[1].args[1]
        self.assertEqual(reserve_params["model_name"], "deepseek/deepseek-v3.2")

    async def test_reserve_reader_llm_decision_reuses_existing_pending_session_audit_when_budget_is_exhausted(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        snapshot = {
            "product": {"product_id": 200},
            "episode": {"episode_id": 300},
        }
        request_hash = service._reader_llm_request_hash(snapshot)
        db.execute.side_effect = [
            self._FakeMappingsResult(
                [{"daily_llm_budget": 1, "used_llm_count": 1}]
            ),
            self._FakeMappingsResult(
                [{"ai_reader_llm_decision_id": 91, "decision_status": "pending"}]
            ),
        ]
        session = service.ReaderClaimedSession(
            ai_reader_schedule_id=1,
            ai_reader_agent_id=7,
            user_id=100,
            age_group="30s",
            gender="M",
            persona_json="{}",
            taste_memory_json="{}",
            activity_pattern_json="{}",
            claimed_session_no=2,
        )

        llm_decision_id = await service.reserve_reader_llm_decision(
            session=session,
            snapshot=snapshot,
            db=db,
        )
        executed_sql = "\n".join(str(call.args[0]).lower() for call in db.execute.await_args_list)

        self.assertEqual(llm_decision_id, 91)
        self.assertIn("session_id = :session_id", executed_sql)
        self.assertIn("request_hash = :request_hash", executed_sql)
        self.assertIn("decision_status = 'pending'", executed_sql)
        self.assertEqual(db.execute.await_args_list[1].args[1]["request_hash"], request_hash)
        self.assertNotIn("insert into tb_ai_reader_llm_decision", executed_sql)

    async def test_reserve_reader_llm_decision_does_not_reuse_pending_session_audit_with_different_request_hash(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult(
                [{"daily_llm_budget": 1, "used_llm_count": 1}]
            ),
            self._FakeMappingsResult([]),
        ]
        session = service.ReaderClaimedSession(
            ai_reader_schedule_id=1,
            ai_reader_agent_id=7,
            user_id=100,
            age_group="30s",
            gender="M",
            persona_json="{}",
            taste_memory_json="{}",
            activity_pattern_json="{}",
        )

        with self.assertRaises(service.InvalidReaderSessionError):
            await service.reserve_reader_llm_decision(
                session=session,
                snapshot={
                    "product": {"product_id": 200},
                    "episode": {"episode_id": 300},
                },
                db=db,
            )

        existing_call = db.execute.await_args_list[1]
        existing_sql = str(existing_call.args[0]).lower()
        self.assertIn("request_hash = :request_hash", existing_sql)
        self.assertNotIn(
            "insert into tb_ai_reader_llm_decision",
            "\n".join(str(call.args[0]).lower() for call in db.execute.await_args_list),
        )

    async def test_reader_llm_session_id_includes_claimed_session_sequence(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult(
                [{"daily_llm_budget": 3, "used_llm_count": 1}]
            ),
            self._FakeMappingsResult([], rowcount=1, inserted_primary_key=[91]),
        ]
        session = service.ReaderClaimedSession(
            ai_reader_schedule_id=1,
            ai_reader_agent_id=7,
            user_id=100,
            age_group="30s",
            gender="M",
            persona_json="{}",
            taste_memory_json="{}",
            activity_pattern_json="{}",
            claimed_session_no=2,
        )

        await service.reserve_reader_llm_decision(
            session=session,
            snapshot={
                "product": {"product_id": 200},
                "episode": {"episode_id": 300},
            },
            db=db,
        )

        reserve_params = db.execute.await_args_list[1].args[1]
        self.assertEqual(reserve_params["session_id"], "1:2")

    async def test_process_reader_session_marks_reserved_decision_failed_when_llm_fails(self):
        from app.services.ai import reader_agent_session_service as service

        events = []
        db = AsyncMock()
        db.in_transaction = lambda: False

        @asynccontextmanager
        async def fake_begin():
            events.append("begin")
            try:
                yield
            finally:
                events.append("end")

        async def fake_execute(statement, *args, **kwargs):
            sql = str(statement).lower()
            if "from tb_user_taste_factor_score" in sql:
                return self._FakeMappingsResult([])
            if "from tb_product p" in sql:
                return self._FakeMappingsResult(
                    [
                        {
                            "product_id": 200,
                            "title": "테스트 작품",
                            "status_code": "ongoing",
                            "count_hit": 10,
                            "count_bookmark": 2,
                            "count_recommend": 1,
                            "episode_id": 300,
                            "episode_no": 1,
                            "episode_title": "첫 회",
                            "episode_summary_text": "각성자가 탑에 오른다.",
                            "protagonist_goal_primary": "탑등반",
                            "protagonist_type_tags": "[]",
                            "protagonist_job_tags": "[]",
                            "protagonist_material_tags": "[]",
                            "worldview_tags": "[]",
                            "axis_style_tags": "[]",
                            "axis_romance_tags": "[]",
                            "ai_reader_product_state_id": None,
                        }
                    ]
                )
            if "from tb_ai_reader_product_state" in sql:
                return self._FakeMappingsResult([])
            if "select a.daily_llm_budget" in sql:
                events.append("budget")
                return self._FakeMappingsResult(
                    [{"daily_llm_budget": 1, "used_llm_count": 0}]
                )
            if "insert into tb_ai_reader_llm_decision" in sql:
                events.append("reserve")
                return self._FakeMappingsResult([], rowcount=1, inserted_primary_key=[91])
            if "update tb_ai_reader_llm_decision" in sql:
                events.append("failed")
                self.assertIn("decision_status = 'failed'", sql)
                return self._FakeMappingsResult([], rowcount=1)
            raise AssertionError(f"unexpected sql: {statement}")

        async def fake_llm(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
            events.append("llm")
            raise RuntimeError("llm down")

        db.begin = fake_begin
        db.execute.side_effect = fake_execute
        session = service.ReaderClaimedSession(
            ai_reader_schedule_id=1,
            ai_reader_agent_id=7,
            user_id=100,
            age_group="30s",
            gender="M",
            persona_json="{}",
            taste_memory_json="{}",
            activity_pattern_json="{}",
        )

        with self.assertRaises(RuntimeError):
            await service.process_reader_session_decision(session, db, llm_call=fake_llm)

        self.assertEqual(
            events,
            ["begin", "budget", "reserve", "end", "llm", "begin", "failed", "end"],
        )

    async def test_process_claimed_reader_session_persists_actions_and_success_in_one_transaction(self):
        from app.services.ai import reader_agent_session_service as service

        events = []
        db = AsyncMock()
        db.in_transaction = lambda: False
        results = [
            self._FakeMappingsResult(
                [{"factor_type": "worldview", "factor_key": "현대", "score": 0.8}]
            ),
            self._FakeMappingsResult(
                [
                    {
                        "product_id": 200,
                        "title": "테스트 작품",
                        "status_code": "ongoing",
                        "count_hit": 10,
                        "count_bookmark": 2,
                        "count_recommend": 1,
                        "episode_id": 300,
                        "episode_no": 1,
                        "episode_title": "첫 회",
                        "episode_summary_text": "각성자가 탑에 오른다.",
                        "protagonist_type_tags": '["성장형"]',
                        "protagonist_job_tags": '["헌터"]',
                        "protagonist_material_tags": '["상태창"]',
                        "worldview_tags": '["현대"]',
                        "axis_style_tags": '["빠른전개"]',
                        "axis_romance_tags": "[]",
                        "ai_reader_product_state_id": None,
                    }
                ]
            ),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult(
                [{"daily_llm_budget": 1, "used_llm_count": 0}]
            ),
            self._FakeMappingsResult([], rowcount=1, inserted_primary_key=[91]),
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([], rowcount=4),
            self._FakeMappingsResult([], rowcount=1),
        ]

        @asynccontextmanager
        async def fake_begin():
            events.append("begin")
            try:
                yield
            finally:
                events.append("end")

        async def fake_execute(statement, *args, **kwargs):
            sql = str(statement).lower()
            if "select a.daily_llm_budget" in sql:
                events.append("budget")
            elif "insert into tb_ai_reader_llm_decision" in sql:
                events.append("reserve")
            elif "update tb_ai_reader_llm_decision" in sql:
                events.append("llm_success")
            elif "from tb_ai_reader_action_queue" in sql:
                events.append("cleanup")
            elif "insert into tb_ai_reader_action_queue" in sql:
                events.append("enqueue")
            elif "update tb_ai_reader_daily_schedule" in sql:
                events.append("success")
            return results.pop(0)

        db.begin = fake_begin
        db.execute.side_effect = fake_execute

        async def fake_llm(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
            return """
            {
              "continue_reading": true,
              "next_episode_count": 1,
              "drop_product": false,
              "bookmark_action": "add",
              "recommend_action": "press",
              "evaluation": {"should_evaluate": false, "eval_code": null},
              "taste_delta": {"positive": ["성장형"], "negative": []},
              "reason": "취향과 맞아 다음 화를 본다"
            }
            """

        session = service.ReaderClaimedSession(
            ai_reader_schedule_id=1,
            ai_reader_agent_id=7,
            user_id=100,
            age_group="30s",
            gender="M",
            persona_json='{"patience": 0.6}',
            taste_memory_json="{}",
            activity_pattern_json='{"active_hours": [20, 21]}',
        )

        result = await service.process_claimed_reader_session(
            session,
            db,
            worker_id="session-worker-a",
            llm_call=fake_llm,
        )

        self.assertEqual(result.llm_decision_id, 91)
        self.assertEqual(
            events,
            [
                "begin",
                "budget",
                "reserve",
                "end",
                "begin",
                "llm_success",
                "cleanup",
                "enqueue",
                "success",
                "end",
            ],
        )

    async def test_process_reader_session_prefers_persona_matching_candidate(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.in_transaction = lambda: False

        @asynccontextmanager
        async def fake_begin():
            yield

        db.begin = fake_begin
        db.execute.side_effect = [
            self._FakeMappingsResult(
                [
                    {"factor_type": "worldview", "factor_key": "현대", "score": 0.8},
                    {"factor_type": "style", "factor_key": "빠른전개", "score": 0.7},
                ]
            ),
            self._FakeMappingsResult(
                [
                    {
                        "product_id": 201,
                        "title": "조회수 높은 비취향작",
                        "status_code": "ongoing",
                        "count_hit": 99999,
                        "count_bookmark": 100,
                        "count_recommend": 50,
                        "episode_id": 301,
                        "episode_no": 1,
                        "episode_title": "첫 회",
                        "episode_summary_text": "느린 일상.",
                        "protagonist_type_tags": '["구원자"]',
                        "protagonist_job_tags": '["요리"]',
                        "protagonist_material_tags": '["마법"]',
                        "worldview_tags": '["중세"]',
                        "axis_style_tags": '["일상"]',
                        "axis_romance_tags": "[]",
                        "ai_reader_product_state_id": None,
                    },
                    {
                        "product_id": 200,
                        "title": "취향 맞는 성장 헌터물",
                        "status_code": "ongoing",
                        "count_hit": 10,
                        "count_bookmark": 2,
                        "count_recommend": 1,
                        "episode_id": 300,
                        "episode_no": 1,
                        "episode_title": "첫 회",
                        "episode_summary_text": "각성자가 탑에 오른다.",
                        "protagonist_type_tags": '["성장형"]',
                        "protagonist_job_tags": '["헌터"]',
                        "protagonist_material_tags": '["상태창"]',
                        "worldview_tags": '["현대"]',
                        "axis_style_tags": '["빠른전개"]',
                        "axis_romance_tags": "[]",
                        "ai_reader_product_state_id": None,
                    },
                ]
            ),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult(
                [{"daily_llm_budget": 1, "used_llm_count": 0}]
            ),
            self._FakeMappingsResult([], rowcount=1, inserted_primary_key=[91]),
            self._FakeMappingsResult([], rowcount=1),
            self._FakeMappingsResult([]),
            self._FakeMappingsResult([], rowcount=3),
        ]

        async def fake_llm(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
            self.assertIn("취향 맞는 성장 헌터물", user_prompt)
            self.assertNotIn("조회수 높은 비취향작", user_prompt)
            return """
            {
              "continue_reading": true,
              "next_episode_count": 1,
              "drop_product": false,
              "bookmark_action": "none",
              "recommend_action": "press",
              "evaluation": {"should_evaluate": false, "eval_code": null},
              "taste_delta": {"positive": ["성장형"], "negative": []},
              "reason": "취향 축과 맞아 다음 화를 본다"
            }
            """

        session = service.ReaderClaimedSession(
            ai_reader_schedule_id=1,
            ai_reader_agent_id=7,
            user_id=100,
            age_group="30s",
            gender="M",
            persona_json=json.dumps(
                {
                    "initial_axis_bias": {
                        "세": {"현대": 0.9},
                        "직": {"헌터": 0.9},
                        "능": {"상태창": 0.8},
                        "연": {},
                        "작": {"빠른전개": 0.8},
                        "타": {"성장형": 0.9},
                        "목": {},
                    }
                },
                ensure_ascii=False,
            ),
            taste_memory_json="{}",
            activity_pattern_json="{}",
        )

        result = await service.process_reader_session_decision(
            session,
            db,
            llm_call=fake_llm,
        )

        self.assertEqual(result.enqueued_action_count, 3)

    async def test_reader_target_query_limits_candidate_to_one_next_episode_per_product(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([]),
            self._FakeMappingsResult(
                [
                    {
                        "product_id": 200,
                        "title": "테스트 작품",
                        "status_code": "ongoing",
                        "count_hit": 10,
                        "count_bookmark": 2,
                        "count_recommend": 1,
                        "episode_id": 300,
                        "episode_no": 1,
                        "episode_title": "첫 회",
                        "episode_summary_text": "각성자가 탑에 오른다.",
                        "protagonist_type_tags": '["성장형"]',
                        "protagonist_job_tags": '["헌터"]',
                        "protagonist_material_tags": '["상태창"]',
                        "worldview_tags": '["현대"]',
                        "axis_style_tags": '["빠른전개"]',
                        "axis_romance_tags": "[]",
                        "ai_reader_product_state_id": None,
                    }
                ]
            ),
            self._FakeMappingsResult([]),
        ]

        await service.build_reader_decision_snapshot(
            service.ReaderClaimedSession(
                ai_reader_schedule_id=1,
                ai_reader_agent_id=7,
                user_id=100,
                age_group="30s",
                gender="M",
                persona_json="{}",
                taste_memory_json="{}",
                activity_pattern_json="{}",
            ),
            db,
        )

        target_sql = next(
            str(call.args[0]).lower()
            for call in db.execute.await_args_list
            if "from tb_product p" in str(call.args[0]).lower()
        )

        self.assertIn("e.episode_id = (", target_sql)
        self.assertIn("select e_next.episode_id", target_sql)
        self.assertIn("e.price_type", target_sql)
        self.assertIn("e_next.price_type", target_sql)
        self.assertIn("p.paid_episode_no", target_sql)
        self.assertIn("order by e_next.episode_no, e_next.episode_id", target_sql)
        self.assertIn("limit 1", target_sql)

    async def test_reader_target_query_does_not_prelimit_new_products_by_hit_count(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.execute.side_effect = [
            self._FakeMappingsResult([]),
            self._FakeMappingsResult(
                [
                    {
                        "product_id": 200,
                        "title": "테스트 작품",
                        "status_code": "ongoing",
                        "count_hit": 10,
                        "count_bookmark": 2,
                        "count_recommend": 1,
                        "episode_id": 300,
                        "episode_no": 1,
                        "episode_title": "첫 회",
                        "episode_summary_text": "각성자가 탑에 오른다.",
                        "protagonist_type_tags": '["성장형"]',
                        "protagonist_job_tags": '["헌터"]',
                        "protagonist_material_tags": '["상태창"]',
                        "worldview_tags": '["현대"]',
                        "axis_style_tags": '["빠른전개"]',
                        "axis_romance_tags": "[]",
                        "ai_reader_product_state_id": None,
                    }
                ]
            ),
            self._FakeMappingsResult([]),
        ]

        await service.build_reader_decision_snapshot(
            service.ReaderClaimedSession(
                ai_reader_schedule_id=11,
                ai_reader_agent_id=7,
                user_id=100,
                age_group="30s",
                gender="M",
                persona_json="{}",
                taste_memory_json="{}",
                activity_pattern_json="{}",
            ),
            db,
        )

        target_sql = next(
            str(call.args[0]).lower()
            for call in db.execute.await_args_list
            if "from tb_product p" in str(call.args[0]).lower()
        )

        self.assertIn("crc32(", target_sql)
        self.assertIn("concat(", target_sql)
        self.assertNotIn("p.count_hit desc", target_sql)

    def test_reader_candidate_choice_diversifies_close_new_products(self):
        from app.services.ai import reader_agent_session_service as service

        rows = [
            {
                "product_id": product_id,
                "title": f"비슷한 후보 {product_id}",
                "count_hit": 100,
                "protagonist_type_tags": '["성장형"]',
                "protagonist_job_tags": '["헌터"]',
                "protagonist_material_tags": '["상태창"]',
                "worldview_tags": '["현대"]',
                "axis_style_tags": '["빠른전개"]',
                "axis_romance_tags": "[]",
                "protagonist_goal_primary": "탑등반",
                "ai_reader_product_state_id": None,
            }
            for product_id in range(200, 220)
        ]
        persona = {
            "initial_axis_bias": {
                "세": {"현대": 0.7},
                "직": {"헌터": 0.7},
                "능": {"상태창": 0.7},
                "연": {},
                "작": {"빠른전개": 0.7},
                "타": {"성장형": 0.7},
                "목": {"탑등반": 0.7},
            }
        }

        selected_product_ids = {
            service._choose_reader_candidate(
                rows,
                persona=persona,
                taste_factors=[],
                session=service.ReaderClaimedSession(
                    ai_reader_schedule_id=agent_id,
                    ai_reader_agent_id=agent_id,
                    user_id=1000 + agent_id,
                    age_group="30s",
                    gender="M",
                    persona_json="{}",
                    taste_memory_json="{}",
                    activity_pattern_json="{}",
                ),
            )["product_id"]
            for agent_id in range(1, 21)
        }

        self.assertGreaterEqual(len(selected_product_ids), 5)

    def test_reader_candidate_choice_uses_high_novelty_to_sample_weaker_new_matches(self):
        from app.services.ai import reader_agent_session_service as service

        strong_match = {
            "product_id": 100,
            "title": "완전 취향 후보",
            "count_hit": 100,
            "protagonist_type_tags": '["성장형"]',
            "protagonist_job_tags": '["헌터"]',
            "protagonist_material_tags": '["상태창"]',
            "worldview_tags": '["현대"]',
            "axis_style_tags": '["빠른전개"]',
            "axis_romance_tags": "[]",
            "protagonist_goal_primary": "탑등반",
            "ai_reader_product_state_id": None,
        }
        weaker_matches = [
            {
                "product_id": product_id,
                "title": f"약한 매칭 후보 {product_id}",
                "count_hit": 100,
                "protagonist_type_tags": '["구원자"]',
                "protagonist_job_tags": '["요리"]',
                "protagonist_material_tags": '["마법"]',
                "worldview_tags": '["중세"]',
                "axis_style_tags": '["일상"]',
                "axis_romance_tags": "[]",
                "protagonist_goal_primary": "생존",
                "ai_reader_product_state_id": None,
            }
            for product_id in range(200, 214)
        ]
        persona = {
            "novelty_seeking": 0.75,
            "initial_axis_bias": {
                "세": {"현대": 0.9},
                "직": {"헌터": 0.9},
                "능": {"상태창": 0.9},
                "연": {},
                "작": {"빠른전개": 0.9},
                "타": {"성장형": 0.9},
                "목": {"탑등반": 0.9},
            },
        }

        selected_product_ids = {
            service._choose_reader_candidate(
                [strong_match, *weaker_matches],
                persona=persona,
                taste_factors=[],
                session=service.ReaderClaimedSession(
                    ai_reader_schedule_id=agent_id,
                    ai_reader_agent_id=agent_id,
                    user_id=2000 + agent_id,
                    age_group="20s",
                    gender="X",
                    persona_json="{}",
                    taste_memory_json="{}",
                    activity_pattern_json="{}",
                ),
            )["product_id"]
            for agent_id in range(1, 21)
        }

        self.assertTrue(selected_product_ids - {100})

    def test_reader_candidate_choice_keeps_reading_state_even_for_high_novelty_agent(self):
        from app.services.ai import reader_agent_session_service as service

        continuing_row = {
            "product_id": 100,
            "title": "이미 읽던 작품",
            "count_hit": 10,
            "protagonist_type_tags": '["구원자"]',
            "protagonist_job_tags": '["요리"]',
            "protagonist_material_tags": '["마법"]',
            "worldview_tags": '["중세"]',
            "axis_style_tags": '["일상"]',
            "axis_romance_tags": "[]",
            "protagonist_goal_primary": "생존",
            "ai_reader_product_state_id": 1,
        }
        new_strong_row = {
            "product_id": 200,
            "title": "새로운 완전 취향 후보",
            "count_hit": 10,
            "protagonist_type_tags": '["성장형"]',
            "protagonist_job_tags": '["헌터"]',
            "protagonist_material_tags": '["상태창"]',
            "worldview_tags": '["현대"]',
            "axis_style_tags": '["빠른전개"]',
            "axis_romance_tags": "[]",
            "protagonist_goal_primary": "탑등반",
            "ai_reader_product_state_id": None,
        }
        persona = {
            "novelty_seeking": 0.75,
            "initial_axis_bias": {
                "세": {"현대": 0.9},
                "직": {"헌터": 0.9},
                "능": {"상태창": 0.9},
                "연": {},
                "작": {"빠른전개": 0.9},
                "타": {"성장형": 0.9},
                "목": {"탑등반": 0.9},
            },
        }

        selected = service._choose_reader_candidate(
            [continuing_row, new_strong_row],
            persona=persona,
            taste_factors=[],
            session=service.ReaderClaimedSession(
                ai_reader_schedule_id=1,
                ai_reader_agent_id=1,
                user_id=1,
                age_group="20s",
                gender="X",
                persona_json="{}",
                taste_memory_json="{}",
                activity_pattern_json="{}",
            ),
        )

        self.assertEqual(selected["product_id"], 100)

    async def test_mark_reader_session_success_and_failure_require_running_worker_owner(self):
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult([], rowcount=1)

        await service.mark_reader_session_succeeded(
            db,
            schedule_id=1,
            worker_id="session-worker-a",
        )
        await service.mark_reader_session_failed(
            db,
            schedule_id=2,
            worker_id="session-worker-a",
            error_message="bad llm",
        )
        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertIn(
            "set status = if(greatest(used_session_count, 1) >= session_budget",
            executed_sql,
        )
        self.assertIn("used_session_count = greatest(used_session_count, 1)", executed_sql)
        self.assertIn("locked_by = null", executed_sql)
        self.assertIn("locked_at = null", executed_sql)
        self.assertIn("set status = 'failed'", executed_sql)
        self.assertIn("error_message = :error_message", executed_sql)
        self.assertIn("and status = 'running'", executed_sql)
        self.assertIn("and locked_by = :worker_id", executed_sql)

    async def test_process_claimed_reader_session_marks_success_and_failure(self):
        from app.services.ai import reader_agent_session_service as service

        events = []
        db = AsyncMock()
        db.in_transaction = lambda: False

        @asynccontextmanager
        async def fake_begin():
            events.append("begin")
            try:
                yield
            finally:
                events.append("end")

        db.begin = fake_begin

        async def fake_decision(session, tx_db):
            events.append(f"decision:{session.ai_reader_schedule_id}")
            return service.ReaderSessionDecisionResult(llm_decision_id=91, actions=[])

        async def fake_success(tx_db, *, schedule_id, worker_id):
            events.append(f"success:{schedule_id}:{worker_id}")

        session = service.ReaderClaimedSession(
            ai_reader_schedule_id=1,
            ai_reader_agent_id=7,
            user_id=100,
            age_group="30s",
            gender="M",
            persona_json="{}",
            taste_memory_json="{}",
            activity_pattern_json="{}",
        )

        result = await service.process_claimed_reader_session(
            session,
            db,
            worker_id="session-worker-a",
            decision_func=fake_decision,
            success_func=fake_success,
        )

        self.assertEqual(result.llm_decision_id, 91)
        self.assertEqual(events, ["decision:1", "begin", "success:1:session-worker-a", "end"])

        events.clear()

        async def failing_decision(session, tx_db):
            events.append(f"decision:{session.ai_reader_schedule_id}")
            raise RuntimeError("boom")

        async def fake_failed(tx_db, *, schedule_id, worker_id, error_message):
            events.append(f"failed:{schedule_id}:{worker_id}:{error_message}")

        with self.assertRaises(RuntimeError):
            await service.process_claimed_reader_session(
                session,
                db,
                worker_id="session-worker-a",
                decision_func=failing_decision,
                failed_func=fake_failed,
            )

        self.assertEqual(
            events,
            ["decision:1", "begin", "failed:1:session-worker-a:boom", "end"],
        )

    async def test_process_claimed_reader_session_wraps_persistence_and_success_in_transaction(self):
        from app.services.ai import reader_agent_session_service as service

        events = []
        db = AsyncMock()
        db.in_transaction = lambda: False

        @asynccontextmanager
        async def fake_begin():
            events.append("begin")
            try:
                yield
            finally:
                events.append("end")

        db.begin = fake_begin

        async def fake_decision(session, tx_db):
            events.append("decision")
            return service.ReaderSessionDecisionResult(llm_decision_id=91, actions=[])

        async def fake_success(tx_db, *, schedule_id, worker_id):
            events.append("success")
            self.assertIs(tx_db, db)

        session = service.ReaderClaimedSession(
            ai_reader_schedule_id=1,
            ai_reader_agent_id=7,
            user_id=100,
            age_group="30s",
            gender="M",
            persona_json="{}",
            taste_memory_json="{}",
            activity_pattern_json="{}",
        )

        result = await service.process_claimed_reader_session(
            session,
            db,
            worker_id="session-worker-a",
            decision_func=fake_decision,
            success_func=fake_success,
        )

        self.assertEqual(result.llm_decision_id, 91)
        self.assertEqual(events, ["decision", "begin", "success", "end"])

    async def test_save_reader_llm_decision_reuses_session_primary_key(self):
        from app.services.ai import reader_agent_decision_service as decision_service
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.execute.return_value = self._FakeMappingsResult(
            [],
            rowcount=2,
            inserted_primary_key=[],
            lastrowid=91,
        )
        session = service.ReaderClaimedSession(
            ai_reader_schedule_id=1,
            ai_reader_agent_id=7,
            user_id=100,
            age_group="30s",
            gender="M",
            persona_json="{}",
            taste_memory_json="{}",
            activity_pattern_json="{}",
        )
        decision = decision_service.ReaderLlmDecision(
            continue_reading=True,
            next_episode_count=1,
            drop_product=False,
            bookmark_action="none",
            recommend_action="none",
            should_evaluate=False,
            eval_code=None,
            taste_delta={"positive": [], "negative": []},
            reason="liked",
        )

        llm_decision_id = await service._save_reader_llm_decision(
            session=session,
            snapshot={
                "product": {"product_id": 200},
                "episode": {"episode_id": 300},
            },
            decision=decision,
            db=db,
        )
        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)

        self.assertEqual(llm_decision_id, 91)
        self.assertIn("last_insert_id(ai_reader_llm_decision_id)", executed_sql.lower())

    async def test_save_reader_llm_decision_uses_lastrowid_for_text_insert(self):
        from app.services.ai import reader_agent_decision_service as decision_service
        from app.services.ai import reader_agent_session_service as service

        db = AsyncMock()
        db.execute.return_value = self._TextInsertResult(rowcount=1, lastrowid=91)
        session = service.ReaderClaimedSession(
            ai_reader_schedule_id=1,
            ai_reader_agent_id=7,
            user_id=100,
            age_group="30s",
            gender="M",
            persona_json="{}",
            taste_memory_json="{}",
            activity_pattern_json="{}",
        )
        decision = decision_service.ReaderLlmDecision(
            continue_reading=True,
            next_episode_count=1,
            drop_product=False,
            bookmark_action="none",
            recommend_action="none",
            should_evaluate=False,
            eval_code=None,
            taste_delta={"positive": [], "negative": []},
            reason="liked",
        )

        llm_decision_id = await service._save_reader_llm_decision(
            session=session,
            snapshot={
                "product": {"product_id": 200},
                "episode": {"episode_id": 300},
            },
            decision=decision,
            db=db,
        )

        self.assertEqual(llm_decision_id, 91)


class AiReaderWorkerCycleTest(unittest.IsolatedAsyncioTestCase):
    class _FakeMappingsResult:
        def __init__(self, rows):
            self._rows = rows

        def mappings(self):
            return self

        def all(self):
            return self._rows

    def _required_index_rows(self, worker_service, *, uppercase=False):
        rows = []
        for table_name, indexes in worker_service.REQUIRED_READER_WORKER_INDEXES.items():
            for index_name, index_contract in indexes.items():
                row = {
                    "table_name": table_name,
                    "index_name": index_name,
                    "column_names": ",".join(index_contract["columns"]),
                    "non_unique": 0 if index_contract["unique"] else 1,
                }
                if uppercase:
                    row = {key.upper(): value for key, value in row.items()}
                rows.append(row)
        return rows

    def test_reader_worker_schema_contract_includes_worker_query_columns(self):
        from app.services.ai import reader_agent_worker_service as worker_service

        expected_columns = {
            "tb_ai_reader_agent": {
                "ai_reader_agent_id",
                "user_id",
                "age_group",
                "gender",
                "persona_json",
                "taste_memory_json",
                "activity_pattern_json",
                "status",
                "daily_llm_budget",
            },
            "tb_ai_reader_daily_schedule": {
                "ai_reader_schedule_id",
                "ai_reader_agent_id",
                "schedule_date",
                "active_start_at",
                "active_end_at",
                "session_budget",
                "used_session_count",
                "status",
                "locked_by",
                "locked_at",
                "error_message",
            },
            "tb_ai_reader_product_state": {
                "ai_reader_product_state_id",
                "ai_reader_agent_id",
                "product_id",
                "current_episode_id",
                "state",
                "read_episode_count",
                "bookmarked_yn",
                "recommended_yn",
                "evaluated_yn",
                "last_decision_id",
            },
            "tb_ai_reader_llm_decision": {
                "ai_reader_llm_decision_id",
                "ai_reader_agent_id",
                "user_id",
                "session_id",
                "product_id",
                "episode_id",
                "prompt_version",
                "model_name",
                "request_hash",
                "input_snapshot_json",
                "decision_json",
                "decision_status",
                "created_date",
            },
            "tb_ai_reader_action_queue": {
                "ai_reader_action_id",
                "idempotency_key",
                "active_scope_key",
                "ai_reader_agent_id",
                "user_id",
                "product_id",
                "episode_id",
                "action_type",
                "target_value",
                "llm_decision_id",
                "status",
                "attempt_count",
                "locked_by",
                "locked_at",
                "available_at",
                "applied_at",
                "error_message",
            },
            "tb_ai_reader_public_metric_daily": {
                "ai_reader_public_metric_daily_id",
                "stat_date",
                "product_id",
                "episode_id",
                "ai_view_count",
                "ai_bookmark_count",
                "ai_unbookmark_count",
                "ai_recommend_count",
                "ai_unrecommend_count",
                "ai_evaluation_count",
            },
        }

        for table_name, column_names in expected_columns.items():
            self.assertTrue(
                column_names.issubset(
                    set(worker_service.REQUIRED_READER_WORKER_COLUMNS[table_name])
                ),
                table_name,
            )

    def test_reader_worker_schema_contract_includes_schedule_stale_index(self):
        from app.services.ai import reader_agent_worker_service as worker_service

        self.assertEqual(
            worker_service.REQUIRED_READER_WORKER_INDEXES[
                "tb_ai_reader_daily_schedule"
            ]["idx_ai_reader_daily_schedule_stale"],
            {
                "columns": (
                    "status",
                    "locked_at",
                    "active_start_at",
                    "active_end_at",
                    "ai_reader_schedule_id",
                ),
                "unique": False,
            },
        )

    async def test_assert_reader_worker_schema_ready_accepts_required_objects(self):
        from app.services.ai import reader_agent_worker_service as worker_service

        db = AsyncMock()

        async def fake_execute(statement, *args, **kwargs):
            sql = str(statement).lower()
            if "information_schema.tables" in sql:
                return self._FakeMappingsResult(
                    [
                        {"table_name": table_name}
                        for table_name in worker_service.REQUIRED_READER_WORKER_TABLES
                    ]
                )
            if "information_schema.columns" in sql:
                return self._FakeMappingsResult(
                    [
                        {"table_name": table_name, "column_name": column_name}
                        for table_name, column_names in (
                            worker_service.REQUIRED_READER_WORKER_COLUMNS.items()
                        )
                        for column_name in column_names
                    ]
                )
            if "information_schema.statistics" in sql:
                return self._FakeMappingsResult(self._required_index_rows(worker_service))
            raise AssertionError(f"unexpected schema readback query: {statement}")

        db.execute.side_effect = fake_execute

        await worker_service.assert_reader_worker_schema_ready(db)

        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)
        self.assertIn("information_schema.tables", executed_sql.lower())
        self.assertIn("information_schema.columns", executed_sql.lower())
        self.assertIn("information_schema.statistics", executed_sql.lower())

    async def test_assert_reader_worker_schema_ready_accepts_information_schema_key_case(self):
        from app.services.ai import reader_agent_worker_service as worker_service

        db = AsyncMock()

        async def fake_execute(statement, *args, **kwargs):
            sql = str(statement).lower()
            if "information_schema.tables" in sql:
                return self._FakeMappingsResult(
                    [
                        {"TABLE_NAME": table_name}
                        for table_name in worker_service.REQUIRED_READER_WORKER_TABLES
                    ]
                )
            if "information_schema.columns" in sql:
                return self._FakeMappingsResult(
                    [
                        {"TABLE_NAME": table_name, "COLUMN_NAME": column_name}
                        for table_name, column_names in (
                            worker_service.REQUIRED_READER_WORKER_COLUMNS.items()
                        )
                        for column_name in column_names
                    ]
                )
            if "information_schema.statistics" in sql:
                return self._FakeMappingsResult(
                    self._required_index_rows(worker_service, uppercase=True)
                )
            raise AssertionError(f"unexpected schema readback query: {statement}")

        db.execute.side_effect = fake_execute

        await worker_service.assert_reader_worker_schema_ready(db)

    async def test_assert_reader_worker_schema_ready_fails_before_worker_can_run(self):
        from app.services.ai import reader_agent_worker_service as worker_service

        db = AsyncMock()

        async def fake_execute(statement, *args, **kwargs):
            sql = str(statement).lower()
            if "information_schema.tables" in sql:
                return self._FakeMappingsResult(
                    [
                        {"table_name": table_name}
                        for table_name in worker_service.REQUIRED_READER_WORKER_TABLES
                    ]
                )
            if "information_schema.columns" in sql:
                return self._FakeMappingsResult(
                    [
                        {"table_name": table_name, "column_name": column_name}
                        for table_name, column_names in (
                            worker_service.REQUIRED_READER_WORKER_COLUMNS.items()
                        )
                        for column_name in column_names
                        if column_name != "ai_unrecommend_count"
                    ]
                )
            if "information_schema.statistics" in sql:
                return self._FakeMappingsResult(self._required_index_rows(worker_service))
            raise AssertionError(f"unexpected schema readback query: {statement}")

        db.execute.side_effect = fake_execute

        with self.assertRaises(worker_service.ReaderWorkerSchemaNotReadyError) as ctx:
            await worker_service.assert_reader_worker_schema_ready(db)

        self.assertIn(
            "missing column tb_ai_reader_public_metric_daily.ai_unrecommend_count",
            str(ctx.exception),
        )

    async def test_assert_reader_worker_schema_ready_rejects_retired_unique_index(self):
        from app.services.ai import reader_agent_worker_service as worker_service

        db = AsyncMock()

        async def fake_execute(statement, *args, **kwargs):
            sql = str(statement).lower()
            if "information_schema.tables" in sql:
                return self._FakeMappingsResult(
                    [
                        {"table_name": table_name}
                        for table_name in worker_service.REQUIRED_READER_WORKER_TABLES
                    ]
                )
            if "information_schema.columns" in sql:
                return self._FakeMappingsResult(
                    [
                        {"table_name": table_name, "column_name": column_name}
                        for table_name, column_names in (
                            worker_service.REQUIRED_READER_WORKER_COLUMNS.items()
                        )
                        for column_name in column_names
                    ]
                )
            if "information_schema.statistics" in sql:
                rows = self._required_index_rows(worker_service)
                rows.append(
                    {
                        "table_name": "tb_ai_reader_llm_decision",
                        "index_name": "uk_ai_reader_llm_decision_request",
                        "column_names": "request_hash",
                        "non_unique": 0,
                    }
                )
                return self._FakeMappingsResult(rows)
            raise AssertionError(f"unexpected schema readback query: {statement}")

        db.execute.side_effect = fake_execute

        with self.assertRaises(worker_service.ReaderWorkerSchemaNotReadyError) as ctx:
            await worker_service.assert_reader_worker_schema_ready(db)

        self.assertIn(
            "retired index still exists tb_ai_reader_llm_decision.uk_ai_reader_llm_decision_request",
            str(ctx.exception),
        )

    async def test_assert_reader_worker_schema_ready_rejects_non_unique_required_unique_index(self):
        from app.services.ai import reader_agent_worker_service as worker_service

        db = AsyncMock()

        async def fake_execute(statement, *args, **kwargs):
            sql = str(statement).lower()
            if "information_schema.tables" in sql:
                return self._FakeMappingsResult(
                    [
                        {"table_name": table_name}
                        for table_name in worker_service.REQUIRED_READER_WORKER_TABLES
                    ]
                )
            if "information_schema.columns" in sql:
                return self._FakeMappingsResult(
                    [
                        {"table_name": table_name, "column_name": column_name}
                        for table_name, column_names in (
                            worker_service.REQUIRED_READER_WORKER_COLUMNS.items()
                        )
                        for column_name in column_names
                    ]
                )
            if "information_schema.statistics" in sql:
                rows = self._required_index_rows(worker_service)
                for row in rows:
                    if row["index_name"] == "uk_ai_reader_action_idempotency":
                        row["non_unique"] = 1
                return self._FakeMappingsResult(rows)
            raise AssertionError(f"unexpected schema readback query: {statement}")

        db.execute.side_effect = fake_execute

        with self.assertRaises(worker_service.ReaderWorkerSchemaNotReadyError) as ctx:
            await worker_service.assert_reader_worker_schema_ready(db)

        self.assertIn(
            "non-unique required index tb_ai_reader_action_queue.uk_ai_reader_action_idempotency",
            str(ctx.exception),
        )

    async def test_assert_reader_worker_schema_ready_rejects_unique_drift_for_non_unique_index(self):
        from app.services.ai import reader_agent_worker_service as worker_service

        db = AsyncMock()

        async def fake_execute(statement, *args, **kwargs):
            sql = str(statement).lower()
            if "information_schema.tables" in sql:
                return self._FakeMappingsResult(
                    [
                        {"table_name": table_name}
                        for table_name in worker_service.REQUIRED_READER_WORKER_TABLES
                    ]
                )
            if "information_schema.columns" in sql:
                return self._FakeMappingsResult(
                    [
                        {"table_name": table_name, "column_name": column_name}
                        for table_name, column_names in (
                            worker_service.REQUIRED_READER_WORKER_COLUMNS.items()
                        )
                        for column_name in column_names
                    ]
                )
            if "information_schema.statistics" in sql:
                rows = self._required_index_rows(worker_service)
                for row in rows:
                    if row["index_name"] == "idx_ai_reader_daily_schedule_stale":
                        row["non_unique"] = 0
                return self._FakeMappingsResult(rows)
            raise AssertionError(f"unexpected schema readback query: {statement}")

        db.execute.side_effect = fake_execute

        with self.assertRaises(worker_service.ReaderWorkerSchemaNotReadyError) as ctx:
            await worker_service.assert_reader_worker_schema_ready(db)

        self.assertIn(
            "unique drift for non-unique index tb_ai_reader_daily_schedule.idx_ai_reader_daily_schedule_stale",
            str(ctx.exception),
        )

    async def test_worker_script_runs_schema_readback_before_first_cycle(self):
        from app.services.ai import reader_agent_worker_service as worker_service
        from scripts import run_ai_reader_worker

        events = []

        class FakeDb:
            def __init__(self, name):
                self.name = name

            async def commit(self):
                events.append(f"commit:{self.name}")

        @asynccontextmanager
        async def fake_session_factory():
            db = FakeDb(f"db-{len(events)}")
            events.append(f"open:{db.name}")
            yield db
            events.append(f"close:{db.name}")

        async def fake_schema_checker(db):
            events.append(f"schema:{db.name}")

        async def fake_timezone_setter(db):
            events.append(f"timezone:{db.name}")

        async def fake_schedule_ensurer(db):
            events.append(f"ensure_schedule:{db.name}")
            return {"created_schedule_count": 0}

        async def fake_cycle(db, *, worker_id, session_limit, action_limit):
            events.append(
                f"cycle:{db.name}:{worker_id}:{session_limit}:{action_limit}"
            )
            return worker_service.ReaderWorkerCycleResult(
                claimed_session_count=0,
                processed_session_count=0,
                failed_session_count=0,
                claimed_action_count=0,
                processed_action_count=0,
                failed_action_count=0,
            )

        class FakeEngine:
            async def dispose(self):
                events.append("dispose")

        args = argparse.Namespace(
            worker_id="reader-worker-a",
            session_limit=3,
            action_limit=5,
            interval_seconds=5.0,
            schedule_ensure_interval_seconds=300.0,
            once=True,
        )

        with patch.dict(os.environ, {"AI_READER_WORKER_ENABLED": "Y"}):
            with patch.object(
                run_ai_reader_worker,
                "likenovel_db_session",
                fake_session_factory,
            ):
                    with patch.object(
                        run_ai_reader_worker,
                        "ensure_reader_worker_schema_ready_once",
                        fake_schema_checker,
                    ):
                        with patch.object(
                            run_ai_reader_worker,
                            "likenovel_db_engine",
                            FakeEngine(),
                            create=True,
                        ):
                            with patch.object(
                                run_ai_reader_worker,
                                "run_reader_worker_cycle",
                                fake_cycle,
                            ):
                                with patch.object(
                                    run_ai_reader_worker,
                                    "set_ai_reader_worker_db_timezone",
                                    fake_timezone_setter,
                                ):
                                    with patch.object(
                                        run_ai_reader_worker,
                                        "ensure_reader_daily_schedules_for_worker",
                                        fake_schedule_ensurer,
                                    ):
                                        await run_ai_reader_worker.run(args)

        self.assertEqual(
            events,
            [
                "open:db-0",
                "timezone:db-0",
                "schema:db-0",
                "commit:db-0",
                "close:db-0",
                "open:db-5",
                "timezone:db-5",
                "ensure_schedule:db-5",
                "cycle:db-5:reader-worker-a:3:5",
                "commit:db-5",
                "close:db-5",
                "dispose",
            ],
        )

    def test_worker_schedule_ensure_throttle_runs_first_then_after_interval(self):
        from scripts import run_ai_reader_worker

        self.assertTrue(
            run_ai_reader_worker.should_ensure_reader_daily_schedules(
                last_ensured_at=None,
                now_monotonic=100.0,
                interval_seconds=300.0,
            )
        )
        self.assertFalse(
            run_ai_reader_worker.should_ensure_reader_daily_schedules(
                last_ensured_at=100.0,
                now_monotonic=399.9,
                interval_seconds=300.0,
            )
        )
        self.assertTrue(
            run_ai_reader_worker.should_ensure_reader_daily_schedules(
                last_ensured_at=100.0,
                now_monotonic=400.0,
                interval_seconds=300.0,
            )
        )

    async def test_run_reader_worker_cycle_noops_when_env_disabled(self):
        from app.services.ai import reader_agent_worker_service as worker_service

        db = AsyncMock()
        session_claimer = AsyncMock(return_value=[])
        action_claimer = AsyncMock(return_value=[])

        with patch.dict(os.environ, {}, clear=True):
            result = await worker_service.run_reader_worker_cycle(
                db,
                worker_id="reader-worker-a",
                session_claimer=session_claimer,
                action_claimer=action_claimer,
            )

        session_claimer.assert_not_awaited()
        action_claimer.assert_not_awaited()
        self.assertEqual(result.claimed_session_count, 0)
        self.assertEqual(result.processed_session_count, 0)
        self.assertEqual(result.failed_session_count, 0)
        self.assertEqual(result.claimed_action_count, 0)
        self.assertEqual(result.processed_action_count, 0)
        self.assertEqual(result.failed_action_count, 0)

    async def test_run_reader_worker_cycle_checks_schema_before_claimers(self):
        from app.services.ai import reader_agent_worker_service as worker_service

        events = []
        db = AsyncMock()
        session_claimer = AsyncMock(return_value=[])
        action_claimer = AsyncMock(return_value=[])

        async def fake_schema_guard(tx_db):
            events.append("schema")
            self.assertIs(tx_db, db)

        with patch.dict(os.environ, {"AI_READER_WORKER_ENABLED": "Y"}):
            await worker_service.run_reader_worker_cycle(
                db,
                worker_id="reader-worker-a",
                session_claimer=session_claimer,
                action_claimer=action_claimer,
                schema_guard=fake_schema_guard,
            )

        self.assertEqual(events, ["schema"])
        session_claimer.assert_awaited_once()
        action_claimer.assert_awaited_once()

    async def test_run_reader_worker_cycle_stops_when_schema_gate_fails(self):
        from app.services.ai import reader_agent_worker_service as worker_service

        db = AsyncMock()
        session_claimer = AsyncMock(return_value=[])
        action_claimer = AsyncMock(return_value=[])

        async def failing_schema_guard(tx_db):
            raise worker_service.ReaderWorkerSchemaNotReadyError("schema missing")

        with patch.dict(os.environ, {"AI_READER_WORKER_ENABLED": "Y"}):
            with self.assertRaises(worker_service.ReaderWorkerSchemaNotReadyError):
                await worker_service.run_reader_worker_cycle(
                    db,
                    worker_id="reader-worker-a",
                    session_claimer=session_claimer,
                    action_claimer=action_claimer,
                    schema_guard=failing_schema_guard,
                )

        session_claimer.assert_not_awaited()
        action_claimer.assert_not_awaited()

    async def test_run_reader_worker_cycle_processes_sessions_then_actions(self):
        from app.services.ai import reader_agent_action_service as action_service
        from app.services.ai import reader_agent_session_service as session_service
        from app.services.ai import reader_agent_worker_service as worker_service

        events = []
        db = AsyncMock()
        claimed_sessions = [
            session_service.ReaderClaimedSession(
                ai_reader_schedule_id=1,
                ai_reader_agent_id=7,
                user_id=100,
                age_group="30s",
                gender="M",
                persona_json="{}",
                taste_memory_json="{}",
                activity_pattern_json="{}",
            )
        ]
        claimed_actions = [
            action_service.ReaderQueuedAction(
                ai_reader_action_id=10,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="read",
                target_value=None,
            )
        ]

        async def fake_session_claimer(tx_db, *, worker_id, limit):
            events.append(f"claim_sessions:{worker_id}:{limit}")
            self.assertIs(tx_db, db)
            return claimed_sessions

        async def fake_session_processor(session, tx_db, *, worker_id):
            events.append(f"process_session:{session.ai_reader_schedule_id}:{worker_id}")
            self.assertIs(tx_db, db)
            return session_service.ReaderSessionDecisionResult(
                llm_decision_id=91,
                actions=[],
            )

        async def fake_action_claimer(tx_db, *, worker_id, limit):
            events.append(f"claim_actions:{worker_id}:{limit}")
            self.assertIs(tx_db, db)
            return claimed_actions

        async def fake_action_processor(action, tx_db, *, worker_id):
            events.append(f"process_action:{action.ai_reader_action_id}:{worker_id}")
            self.assertIs(tx_db, db)
            return action_service.ReaderActionApplyResult(
                ai_reader_action_id=action.ai_reader_action_id,
                action_type=action.action_type,
                applied=True,
                reason="applied",
            )

        async def fake_schema_guard(tx_db):
            events.append("schema")
            self.assertIs(tx_db, db)

        with patch.dict(os.environ, {"AI_READER_WORKER_ENABLED": "Y"}):
            result = await worker_service.run_reader_worker_cycle(
                db,
                worker_id="reader-worker-a",
                session_limit=3,
                action_limit=5,
                session_claimer=fake_session_claimer,
                session_processor=fake_session_processor,
                action_claimer=fake_action_claimer,
                action_processor=fake_action_processor,
                schema_guard=fake_schema_guard,
            )

        self.assertEqual(
            events,
            [
                "schema",
                "claim_sessions:reader-worker-a:3",
                "process_session:1:reader-worker-a",
                "claim_actions:reader-worker-a:5",
                "process_action:10:reader-worker-a",
            ],
        )
        self.assertEqual(result.claimed_session_count, 1)
        self.assertEqual(result.processed_session_count, 1)
        self.assertEqual(result.failed_session_count, 0)
        self.assertEqual(result.claimed_action_count, 1)
        self.assertEqual(result.processed_action_count, 1)
        self.assertEqual(result.failed_action_count, 0)

    async def test_run_reader_worker_cycle_commits_action_claim_before_processing(self):
        from app.services.ai import reader_agent_action_service as action_service
        from app.services.ai import reader_agent_worker_service as worker_service

        events = []
        db = AsyncMock()
        db.in_transaction = lambda: True

        async def fake_commit():
            events.append("commit")

        db.commit.side_effect = fake_commit
        claimed_actions = [
            action_service.ReaderQueuedAction(
                ai_reader_action_id=10,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="read",
                target_value=None,
            )
        ]

        async def fake_session_claimer(tx_db, *, worker_id, limit):
            events.append("claim_sessions")
            return []

        async def fake_action_claimer(tx_db, *, worker_id, limit):
            events.append("claim_actions")
            return claimed_actions

        async def fake_action_processor(action, tx_db, *, worker_id):
            events.append("process_action")
            return action_service.ReaderActionApplyResult(
                ai_reader_action_id=action.ai_reader_action_id,
                action_type=action.action_type,
                applied=True,
                reason="applied",
            )

        async def fake_schema_guard(tx_db):
            events.append("schema")

        with patch.dict(os.environ, {"AI_READER_WORKER_ENABLED": "Y"}):
            await worker_service.run_reader_worker_cycle(
                db,
                worker_id="reader-worker-a",
                session_claimer=fake_session_claimer,
                action_claimer=fake_action_claimer,
                action_processor=fake_action_processor,
                schema_guard=fake_schema_guard,
            )

        self.assertEqual(
            events,
            [
                "schema",
                "claim_sessions",
                "claim_actions",
                "commit",
                "process_action",
            ],
        )

    async def test_run_reader_worker_cycle_continues_after_one_failure(self):
        from app.services.ai import reader_agent_action_service as action_service
        from app.services.ai import reader_agent_session_service as session_service
        from app.services.ai import reader_agent_worker_service as worker_service

        events = []
        db = AsyncMock()
        claimed_sessions = [
            session_service.ReaderClaimedSession(
                ai_reader_schedule_id=1,
                ai_reader_agent_id=7,
                user_id=100,
                age_group="30s",
                gender="M",
                persona_json="{}",
                taste_memory_json="{}",
                activity_pattern_json="{}",
            ),
            session_service.ReaderClaimedSession(
                ai_reader_schedule_id=2,
                ai_reader_agent_id=8,
                user_id=101,
                age_group="20s",
                gender="F",
                persona_json="{}",
                taste_memory_json="{}",
                activity_pattern_json="{}",
            ),
        ]
        claimed_actions = [
            action_service.ReaderQueuedAction(
                ai_reader_action_id=10,
                ai_reader_agent_id=7,
                user_id=100,
                product_id=200,
                episode_id=300,
                action_type="read",
                target_value=None,
            )
        ]

        async def fake_session_claimer(tx_db, *, worker_id, limit):
            return claimed_sessions

        async def fake_session_processor(session, tx_db, *, worker_id):
            events.append(f"session:{session.ai_reader_schedule_id}")
            if session.ai_reader_schedule_id == 1:
                raise RuntimeError("bad session")
            return session_service.ReaderSessionDecisionResult(
                llm_decision_id=92,
                actions=[],
            )

        async def fake_action_claimer(tx_db, *, worker_id, limit):
            return claimed_actions

        async def fake_action_processor(action, tx_db, *, worker_id):
            events.append(f"action:{action.ai_reader_action_id}")
            raise RuntimeError("bad action")

        async def fake_schema_guard(tx_db):
            return None

        with self.assertLogs(
            "app.services.ai.reader_agent_worker_service",
            level="ERROR",
        ) as captured_logs:
            with patch.dict(os.environ, {"AI_READER_WORKER_ENABLED": "Y"}):
                result = await worker_service.run_reader_worker_cycle(
                    db,
                    worker_id="reader-worker-a",
                    session_claimer=fake_session_claimer,
                    session_processor=fake_session_processor,
                    action_claimer=fake_action_claimer,
                    action_processor=fake_action_processor,
                    schema_guard=fake_schema_guard,
                )

        self.assertEqual(events, ["session:1", "session:2", "action:10"])
        self.assertEqual(len(captured_logs.output), 2)
        self.assertEqual(result.claimed_session_count, 2)
        self.assertEqual(result.processed_session_count, 1)
        self.assertEqual(result.failed_session_count, 1)
        self.assertEqual(result.claimed_action_count, 1)
        self.assertEqual(result.processed_action_count, 0)
        self.assertEqual(result.failed_action_count, 1)


class AiReaderPersonaFactoryTest(unittest.TestCase):
    def test_generate_reader_agent_seed_uses_likenovel_axis_labels(self):
        from app.services.ai import reader_agent_persona_service as service

        seed = service.generate_reader_agent_seed(42)
        repeated = service.generate_reader_agent_seed(42)

        self.assertEqual(seed, repeated)
        self.assertIn(seed.age_group, {"10s", "20s", "30s", "40s", "50s"})
        self.assertIn(seed.gender, {"M", "F", "X"})

        persona = json.loads(seed.persona_json)
        taste_memory = json.loads(seed.taste_memory_json)
        activity_pattern = json.loads(seed.activity_pattern_json)

        self.assertIn("initial_axis_bias", persona)
        self.assertEqual(
            set(persona["initial_axis_bias"].keys()),
            {"세", "직", "능", "연", "작", "타", "목"},
        )
        self.assertIn("active_hours", activity_pattern)
        self.assertIn("sleep_hours", activity_pattern)
        self.assertNotEqual(set(activity_pattern["active_hours"]), set(range(24)))
        self.assertEqual(taste_memory["source"], "initial_persona")
        self.assertEqual(persona["loose_stop_weight"], 0.1)

    def test_reader_agent_age_group_weights_prioritize_thirties_and_forties(self):
        from app.services.ai import reader_agent_persona_service as service

        weights = dict(service.AGE_GROUP_WEIGHTS)

        self.assertGreater(
            weights["30s"] + weights["40s"],
            weights["20s"] + weights["10s"] + weights["50s"],
        )
        self.assertGreater(weights["30s"], weights["20s"])
        self.assertGreater(weights["40s"], weights["20s"])
        self.assertGreater(weights["20s"], weights["10s"])

    def test_reader_agent_seed_uses_lightweight_recommend_threshold_range(self):
        from app.services.ai import reader_agent_persona_service as service

        thresholds = [
            json.loads(service.generate_reader_agent_seed(index).persona_json)[
                "recommend_threshold"
            ]
            for index in range(60)
        ]

        self.assertGreaterEqual(min(thresholds), 0.52)
        self.assertLessEqual(max(thresholds), 0.82)

    def test_age_group_changes_activity_window_shape(self):
        from app.services.ai import reader_agent_persona_service as service

        teen = service.build_activity_pattern(age_group="10s", gender="X", seed=1)
        thirties = service.build_activity_pattern(age_group="30s", gender="X", seed=1)

        self.assertNotEqual(teen["active_hours"], thirties["active_hours"])
        self.assertTrue(any(hour >= 22 for hour in teen["active_hours"]))
        self.assertTrue(any(hour in thirties["active_hours"] for hour in (7, 8, 12, 20, 21)))
