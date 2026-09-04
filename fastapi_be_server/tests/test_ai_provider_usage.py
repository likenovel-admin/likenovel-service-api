import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pymysql

from app.services.common.ai_provider_usage import (
    AiProviderUsageOperation,
    build_ai_provider_usage_record,
    estimate_provider_cost,
    persist_ai_provider_usage_pymysql,
)


class AiProviderUsageTest(unittest.TestCase):
    def test_migration_keeps_physical_calls_append_only_and_context_optional(self):
        root = Path(__file__).resolve().parents[1]
        migration = (
            root / "dist/init/109-create-ai-provider-usage-call.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("AUTO_INCREMENT", migration)
        self.assertIn("UNIQUE KEY uq_ai_provider_usage_call_id (call_id)", migration)
        self.assertIn(
            "UNIQUE KEY uq_ai_provider_usage_operation_attempt (operation_id, attempt_no)",
            migration,
        )
        self.assertIn("KEY ix_ai_provider_usage_started (attempt_started_at)", migration)
        self.assertIn(
            "KEY ix_ai_provider_usage_feature_stage_started (feature_key, stage_key, attempt_started_at)",
            migration,
        )
        self.assertNotIn("FOREIGN KEY", migration)

    def test_operation_assigns_stable_id_and_monotonic_attempt_numbers(self):
        operation = AiProviderUsageOperation(
            feature_key="websochat",
            stage_key="qa_reply",
            product_id=123,
        )

        first = operation.start_attempt(
            provider="openrouter",
            requested_model="google/gemma-4-31b-it",
            request_mode="stream",
        )
        second = operation.start_attempt(
            provider="openrouter",
            requested_model="google/gemma-4-31b-it",
            request_mode="nonstream",
        )

        self.assertEqual(first.operation_id, second.operation_id)
        self.assertEqual((first.attempt_no, second.attempt_no), (1, 2))
        self.assertNotEqual(first.call_id, second.call_id)

    def test_discarded_preflight_attempt_does_not_create_retry_gap(self):
        operation = AiProviderUsageOperation(
            feature_key="storyctx",
            stage_key="episode_summary",
        )
        preflight_blocked = operation.start_attempt(
            provider="openrouter",
            requested_model="deepseek/deepseek-v3.2",
            request_mode="nonstream",
        )

        operation.discard_attempt(preflight_blocked)
        first_physical_call = operation.start_attempt(
            provider="openrouter",
            requested_model="deepseek/deepseek-v3.2",
            request_mode="nonstream",
        )

        self.assertEqual(first_physical_call.attempt_no, 1)

    def test_openrouter_provider_cost_is_exact_and_zero_remains_known(self):
        record = build_ai_provider_usage_record(
            AiProviderUsageOperation(
                feature_key="storyctx",
                stage_key="episode_summary",
            ).start_attempt(
                provider="openrouter",
                requested_model="deepseek/deepseek-v3.2",
                request_mode="nonstream",
            ),
            status="success",
            response_json={
                "id": "generation-1",
                "model": "deepseek/deepseek-v3.2",
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "cost": 0,
                },
            },
        )

        self.assertEqual(record.cost_usd, Decimal("0"))
        self.assertEqual(record.cost_source, "provider_reported")
        self.assertEqual(record.provider_request_id, "generation-1")

    def test_missing_openrouter_cost_stays_unavailable(self):
        record = build_ai_provider_usage_record(
            AiProviderUsageOperation(
                feature_key="storyctx",
                stage_key="episode_summary",
            ).start_attempt(
                provider="openrouter",
                requested_model="unknown/model",
                request_mode="nonstream",
            ),
            status="success",
            response_json={"usage": {"prompt_tokens": 10, "completion_tokens": 2}},
        )

        self.assertIsNone(record.cost_usd)
        self.assertEqual(record.cost_source, "unavailable")

    def test_gemini_flash_lite_rate_card_separates_cached_and_reasoning_tokens(self):
        cost, source, version = estimate_provider_cost(
            provider="gemini",
            model="gemini-3.1-flash-lite",
            input_tokens=1_000_000,
            cached_input_tokens=200_000,
            output_tokens=100_000,
            reasoning_tokens=50_000,
        )

        self.assertEqual(cost, Decimal("0.430000000"))
        self.assertEqual(source, "rate_card")
        self.assertEqual(version, "google-gemini-2026-09-04")

    def test_unknown_rate_card_does_not_guess(self):
        cost, source, version = estimate_provider_cost(
            provider="gemini",
            model="future-gemini-model",
            input_tokens=1,
            cached_input_tokens=0,
            output_tokens=1,
            reasoning_tokens=0,
        )

        self.assertIsNone(cost)
        self.assertEqual(source, "unavailable")
        self.assertIsNone(version)

    def test_missing_gemini_usage_is_unavailable_not_zero(self):
        record = build_ai_provider_usage_record(
            AiProviderUsageOperation(
                feature_key="websochat",
                stage_key="qa_reply",
            ).start_attempt(
                provider="gemini",
                requested_model="gemini-3.1-flash-lite",
                request_mode="nonstream",
            ),
            status="provider_error",
            response_json={},
        )

        self.assertIsNone(record.cost_usd)
        self.assertEqual(record.cost_source, "unavailable")

    def test_record_contains_no_prompt_response_or_user_identity(self):
        record = build_ai_provider_usage_record(
            AiProviderUsageOperation(
                feature_key="websochat",
                stage_key="rp_reply",
                product_id=123,
                session_id="session-1",
                scope_key="character:7",
            ).start_attempt(
                provider="gemini",
                requested_model="gemini-3.1-flash-lite",
                request_mode="nonstream",
                started_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
            ),
            status="success",
            response_json={
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 2,
                    "thoughtsTokenCount": 1,
                    "totalTokenCount": 13,
                }
            },
        )

        fields = set(record.as_db_params())
        self.assertFalse(
            fields
            & {
                "prompt",
                "response",
                "raw_error",
                "user_id",
                "guest_key",
                "client_message_id",
            }
        )
        self.assertEqual(record.input_tokens, 10)
        self.assertEqual(record.output_tokens, 2)
        self.assertEqual(record.reasoning_tokens, 1)

    def test_duplicate_insert_is_idempotent_only_for_same_record_hash(self):
        record = build_ai_provider_usage_record(
            AiProviderUsageOperation(
                feature_key="websochat",
                stage_key="qa_reply",
            ).start_attempt(
                provider="openrouter",
                requested_model="google/gemma-4-31b-it",
                request_mode="nonstream",
            ),
            status="success",
            response_json={"usage": {"cost": 0}},
        )

        class FakeCursor:
            def __init__(self, *, matching: bool):
                self.matching = matching
                self.params = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params):
                self.params = params
                if sql.lstrip().startswith("INSERT"):
                    raise pymysql.err.IntegrityError(1062, "duplicate")

            def fetchone(self):
                return {
                    "record_hash": self.params["record_hash"] if self.matching else "different"
                }

        class FakeConnection:
            def __init__(self, *, matching: bool):
                self.matching = matching

            def ping(self, *, reconnect):
                return None

            def cursor(self):
                return FakeCursor(matching=self.matching)

        self.assertTrue(
            persist_ai_provider_usage_pymysql(FakeConnection(matching=True), record)
        )
        with patch("app.services.common.ai_provider_usage.logger.error") as error_log:
            self.assertFalse(
                persist_ai_provider_usage_pymysql(
                    FakeConnection(matching=False),
                    record,
                )
            )
        error_log.assert_called_once()


if __name__ == "__main__":
    unittest.main()
