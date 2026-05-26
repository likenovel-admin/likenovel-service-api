import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from app.services.common import statistics_service


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class AiApiUsageStatisticsTest(unittest.IsolatedAsyncioTestCase):
    async def test_ai_api_usage_response_groups_existing_sources(self):
        db = AsyncMock()
        db.execute.side_effect = [
            FakeResult([
                {
                    "source_key": "dna_batch",
                    "source_label": "DNA 배치",
                    "request_count": 2,
                    "success_count": 1,
                    "failure_count": 1,
                    "exact_cost_usd": 0.123456,
                    "estimated_cost_usd": 0,
                    "untracked_count": 1,
                    "charged_cash": 0,
                },
                {
                    "source_key": "websochat_chat",
                    "source_label": "웹소챗 채팅",
                    "request_count": 3,
                    "success_count": 3,
                    "failure_count": 0,
                    "exact_cost_usd": 0,
                    "estimated_cost_usd": 0,
                    "untracked_count": 3,
                    "charged_cash": 15,
                },
            ]),
            FakeResult([
                {
                    "provider": "openrouter",
                    "model_name": "deepseek/deepseek-v3.2",
                    "source_key": "dna_batch",
                    "request_count": 2,
                    "exact_cost_usd": 0.123456,
                    "estimated_cost_usd": 0,
                    "untracked_count": 1,
                }
            ]),
        ]

        result = await statistics_service.ai_api_usage_statistics(
            start_date="2026-05-01",
            end_date="2026-05-26",
            db=db,
        )

        self.assertEqual(result["summary"]["request_count"], 5)
        self.assertEqual(result["summary"]["tracked_cost_usd"], 0.123456)
        self.assertEqual(result["summary"]["untracked_count"], 4)
        self.assertEqual(result["results"][0]["source_key"], "dna_batch")
        self.assertEqual(result["results"][1]["source_key"], "websochat_chat")
        self.assertEqual(result["model_summary"][0]["model_name"], "deepseek/deepseek-v3.2")
        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.call_args_list)
        self.assertIn("$._llm_meta.total_cost", executed_sql)
        self.assertIn("$._llm_meta.calls[0].provider", executed_sql)
        self.assertIn("NULLIF", executed_sql)
        self.assertIn("COALESCE(SUM(CASE WHEN d.decision_status = 'success'", executed_sql)
        self.assertIn("COLLATE utf8mb4_general_ci", executed_sql)
        self.assertIn("WHERE request_count > 0", executed_sql)

    async def test_ai_api_usage_defaults_to_recent_seven_days(self):
        db = AsyncMock()
        db.execute.side_effect = [FakeResult([]), FakeResult([])]

        with patch.object(statistics_service, "date") as mock_date:
            mock_date.today.return_value = date(2026, 5, 26)
            result = await statistics_service.ai_api_usage_statistics(
                start_date=None,
                end_date=None,
                db=db,
            )

        self.assertEqual(result["summary"]["request_count"], 0)
        first_params = db.execute.call_args_list[0].args[1]
        self.assertEqual(first_params["start_date"], "2026-05-20")
        self.assertEqual(first_params["end_date_exclusive"], "2026-05-27")

    async def test_ai_api_usage_same_start_end_counts_one_day(self):
        db = AsyncMock()
        db.execute.side_effect = [FakeResult([]), FakeResult([])]

        await statistics_service.ai_api_usage_statistics(
            start_date="2026-05-26",
            end_date="2026-05-26",
            db=db,
        )

        first_params = db.execute.call_args_list[0].args[1]
        self.assertEqual(first_params["start_date"], "2026-05-26")
        self.assertEqual(first_params["end_date_exclusive"], "2026-05-27")


def test_statistics_query_exposes_ai_api_usage_route():
    from app.routers.common import statistics_query

    paths = {
        getattr(route, "path", None)
        for route in statistics_query.router.routes
    }
    assert "/statistics/ai-api-usage" in paths
