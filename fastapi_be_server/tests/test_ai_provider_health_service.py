import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from app.services.common import ai_provider_health_service


ROOT = Path(__file__).resolve().parents[1]


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeHealthResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class FakeAsyncClient:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, **kwargs):
        self.__class__.calls.append({"url": url, **kwargs})
        return FakeHealthResponse()


class AiProviderHealthServiceTest(unittest.IsolatedAsyncioTestCase):
    def test_classify_credit_depleted_429(self):
        result = ai_provider_health_service.classify_provider_error(
            http_status=429,
            error_text="Your prepayment credits are depleted.",
        )

        self.assertEqual(result["status"], "credit_depleted")
        self.assertEqual(result["error_code"], "credit_depleted")

    def test_classify_auth_failed(self):
        result = ai_provider_health_service.classify_provider_error(
            http_status=403,
            error_text='{"error":{"message":"API key invalid"}}',
        )

        self.assertEqual(result["status"], "auth_failed")

    def test_classify_timeout_exception(self):
        result = ai_provider_health_service.classify_provider_exception(
            httpx.TimeoutException("timeout"),
        )

        self.assertEqual(result["status"], "timeout")

    async def test_get_ai_provider_health_summary_returns_all_known_providers(self):
        db = AsyncMock()
        db.execute.side_effect = [
            FakeResult([
                {
                    "provider": "gemini",
                    "model": "gemini-test",
                    "status": "ok",
                    "http_status": 200,
                    "error_code": None,
                    "error_message": None,
                    "latency_ms": 123,
                    "checked_at": "2026-06-09 16:00:00",
                    "success_at": "2026-06-09 16:00:00",
                    "affected_features": "websochat",
                }
            ]),
            FakeResult([
                {
                    "provider": "gemini",
                    "last_success_at": "2026-06-09 16:00:00",
                }
            ]),
        ]

        with (
            patch.object(ai_provider_health_service.settings, "GEMINI_API_KEY", "gemini-key"),
            patch.object(ai_provider_health_service.settings, "WEBSOCHAT_GEMINI_MODEL", "gemini-test"),
            patch.object(ai_provider_health_service.settings, "ANTHROPIC_API_KEY", ""),
            patch.object(ai_provider_health_service.settings, "OPENROUTER_API_KEY", ""),
            patch.object(ai_provider_health_service.settings, "DEEPSEEK_API_KEY", ""),
        ):
            rows = await ai_provider_health_service.get_ai_provider_health_summary(db)

        by_provider = {row["provider"]: row for row in rows}
        self.assertEqual(by_provider["gemini"]["status"], "ok")
        self.assertEqual(by_provider["gemini"]["last_success_at"], "2026-06-09 16:00:00")
        self.assertEqual(by_provider["claude"]["status"], "not_configured")
        self.assertEqual(by_provider["openrouter"]["status"], "not_configured")
        self.assertEqual(by_provider["deepseek"]["status"], "not_configured")

    async def test_run_health_check_records_not_configured_without_http_call(self):
        db = AsyncMock()

        with (
            patch.object(ai_provider_health_service.settings, "GEMINI_API_KEY", ""),
            patch.object(ai_provider_health_service.settings, "ANTHROPIC_API_KEY", ""),
            patch.object(ai_provider_health_service.settings, "OPENROUTER_API_KEY", ""),
            patch.object(ai_provider_health_service.settings, "DEEPSEEK_API_KEY", ""),
            patch.object(ai_provider_health_service, "_post_health_prompt", new=AsyncMock()) as post_prompt,
        ):
            result = await ai_provider_health_service.run_ai_provider_health_checks(db)

        self.assertEqual(len(result["results"]), 4)
        self.assertTrue(all(row["status"] == "not_configured" for row in result["results"]))
        post_prompt.assert_not_called()
        self.assertEqual(db.execute.call_count, 4)
        db.commit.assert_awaited()

    async def test_openrouter_health_payload_includes_reader_provider_only(self):
        FakeAsyncClient.calls = []
        spec = ai_provider_health_service.ProviderSpec(
            provider="openrouter",
            model="deepseek/deepseek-v3.2",
            api_key="openrouter-key",
            base_url="https://openrouter.ai/api/v1",
            affected_features="ai_reader",
            api_kind="openai_compatible",
        )

        with (
            patch.object(
                ai_provider_health_service.settings,
                "AI_READER_OPENROUTER_PROVIDER_ONLY",
                "friendli, deepinfra",
            ),
            patch.object(ai_provider_health_service.httpx, "AsyncClient", FakeAsyncClient),
        ):
            await ai_provider_health_service._post_health_prompt(spec)

        self.assertEqual(FakeAsyncClient.calls[0]["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(
            FakeAsyncClient.calls[0]["json"]["provider"],
            {"only": ["friendli", "deepinfra"], "require_parameters": True},
        )

    async def test_deepseek_health_uses_story_context_chat_completion_path(self):
        FakeAsyncClient.calls = []
        spec = ai_provider_health_service.ProviderSpec(
            provider="deepseek",
            model="deepseek-v4-flash",
            api_key="deepseek-key",
            base_url="https://api.deepseek.com/",
            affected_features="story_context",
            api_kind="deepseek",
        )

        with patch.object(ai_provider_health_service.httpx, "AsyncClient", FakeAsyncClient):
            await ai_provider_health_service._post_health_prompt(spec)

        self.assertEqual(FakeAsyncClient.calls[0]["url"], "https://api.deepseek.com/chat/completions")

    async def test_check_provider_records_non_200_response_status(self):
        spec = ai_provider_health_service.ProviderSpec(
            provider="openrouter",
            model="deepseek/deepseek-v3.2",
            api_key="openrouter-key",
            base_url="https://openrouter.ai/api/v1",
            affected_features="ai_reader",
            api_kind="openai_compatible",
        )

        with patch.object(
            ai_provider_health_service,
            "_post_health_prompt",
            new=AsyncMock(return_value=FakeHealthResponse(429, "prepayment credits are depleted")),
        ):
            result = await ai_provider_health_service._check_provider(spec)

        self.assertEqual(result["status"], "credit_depleted")
        self.assertEqual(result["http_status"], 429)
        self.assertIsNone(result["success_at"])


def test_ai_provider_health_migration_contract():
    migration = (ROOT / "dist/init/100-create-ai-provider-health-check.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS tb_ai_provider_health_check" in migration
    assert "provider VARCHAR(40) NOT NULL" in migration
    assert "status VARCHAR(40) NOT NULL" in migration
    assert "idx_ai_provider_health_provider_checked" in migration


def test_statistics_command_exposes_ai_provider_health_check_route():
    from app.routers.common import statistics_command

    paths = {
        getattr(route, "path", None)
        for route in statistics_command.router.routes
    }
    assert "/statistics/ai-provider-health/check" in paths


def test_statistics_query_exposes_ai_provider_health_route():
    from app.routers.common import statistics_query

    paths = {
        getattr(route, "path", None)
        for route in statistics_query.router.routes
    }
    assert "/statistics/ai-provider-health" in paths
