import asyncio
import os
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

import httpx

from app.services.common.openrouter_background_credit_guard import (
    OpenRouterBackgroundCreditLookupError,
    OpenRouterBackgroundCreditReserveError,
    assert_openrouter_background_credit_available,
    assert_openrouter_background_credit_available_async,
    post_openrouter_background_chat_completion,
    post_openrouter_background_chat_completion_async,
)


def build_response(status_code: int, payload: dict, *, method: str = "GET") -> httpx.Response:
    request = httpx.Request(method, "https://openrouter.test/api/v1/credits")
    return httpx.Response(status_code, json=payload, request=request)


class FakeSyncClient:
    def __init__(self, credit_response: httpx.Response, completion_response: httpx.Response | None = None):
        self.credit_response = credit_response
        self.completion_response = completion_response
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        return self.credit_response

    def post(self, url, **kwargs):
        self.post_calls.append({"url": url, **kwargs})
        return self.completion_response


class FakeAsyncClient(FakeSyncClient):
    async def get(self, url, **kwargs):
        return super().get(url, **kwargs)

    async def post(self, url, **kwargs):
        return super().post(url, **kwargs)


class OpenRouterBackgroundCreditGuardTest(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "OPENROUTER_BACKGROUND_RESERVE_USD": "2.00",
                "OPENROUTER_BACKGROUND_IN_FLIGHT_BUFFER_USD": "1.00",
                "OPENROUTER_BACKGROUND_CREDIT_LOCK_PATH": f"{self.temp_dir.name}/credit.lock",
            },
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def test_exact_reserve_plus_buffer_is_allowed(self):
        client = FakeSyncClient(
            build_response(
                200,
                {"data": {"total_credits": 20.0, "total_usage": 17.0}},
            )
        )

        status = assert_openrouter_background_credit_available(
            client,
            base_url="https://openrouter.test/api/v1",
            api_key="secret-key",
        )

        self.assertEqual(str(status.remaining_usd), "3.0")
        self.assertEqual(str(status.minimum_required_usd), "3.00")

    def test_below_reserve_plus_buffer_is_blocked(self):
        client = FakeSyncClient(
            build_response(
                200,
                {"data": {"total_credits": 20.0, "total_usage": 17.01}},
            )
        )

        with self.assertRaises(OpenRouterBackgroundCreditReserveError) as ctx:
            assert_openrouter_background_credit_available(
                client,
                base_url="https://openrouter.test/api/v1",
                api_key="secret-key",
            )

        self.assertNotIn("secret-key", str(ctx.exception))

    def test_lower_priority_work_must_leave_priority_headroom(self):
        client = FakeSyncClient(
            build_response(
                200,
                {"data": {"total_credits": 20.0, "total_usage": 16.5}},
            )
        )

        with self.assertRaises(OpenRouterBackgroundCreditReserveError) as ctx:
            assert_openrouter_background_credit_available(
                client,
                base_url="https://openrouter.test/api/v1",
                api_key="secret-key",
                priority_headroom_usd="1.00",
            )

        self.assertIn("required=$4.00", str(ctx.exception))

    def test_lookup_failure_is_fail_closed(self):
        client = FakeSyncClient(build_response(503, {"error": "unavailable"}))

        with self.assertRaises(OpenRouterBackgroundCreditLookupError):
            assert_openrouter_background_credit_available(
                client,
                base_url="https://openrouter.test/api/v1",
                api_key="secret-key",
            )

    def test_completion_is_not_sent_when_reserve_is_blocked(self):
        client = FakeSyncClient(
            build_response(
                200,
                {"data": {"total_credits": 20.0, "total_usage": 19.0}},
            ),
            build_response(200, {"choices": []}, method="POST"),
        )

        with self.assertRaises(OpenRouterBackgroundCreditReserveError):
            post_openrouter_background_chat_completion(
                client,
                base_url="https://openrouter.test/api/v1",
                api_key="secret-key",
                headers={"Authorization": "Bearer secret-key"},
                json={"model": "test"},
            )

        self.assertEqual(client.post_calls, [])

    def test_batch_environment_forwards_credit_guard_settings(self):
        root = Path(__file__).resolve().parents[1]
        cron_env = (root / "dist" / "batch" / "cron_env.sh").read_text(encoding="utf-8")
        ai_dna_batch = (root / "dist" / "batch" / "ai_dna_extract_daily_batch.sh").read_text(
            encoding="utf-8"
        )

        for variable_name in (
            "OPENROUTER_BACKGROUND_RESERVE_USD",
            "OPENROUTER_BACKGROUND_IN_FLIGHT_BUFFER_USD",
        ):
            self.assertIn(variable_name, cron_env)
            self.assertIn(variable_name, ai_dna_batch)

    def test_story_context_passes_its_lower_priority_headroom_to_every_request(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "build_story_agent_context.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('"STORYCTX_OPENROUTER_PRIORITY_HEADROOM_USD"', source)
        self.assertIn('Decimal("1.00")', source)
        self.assertEqual(
            source.count(
                "priority_headroom_usd=STORYCTX_OPENROUTER_PRIORITY_HEADROOM_USD"
            ),
            6,
        )


class OpenRouterBackgroundCreditGuardAsyncTest(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "OPENROUTER_BACKGROUND_RESERVE_USD": "2.00",
                "OPENROUTER_BACKGROUND_IN_FLIGHT_BUFFER_USD": "1.00",
                "OPENROUTER_BACKGROUND_CREDIT_LOCK_PATH": f"{self.temp_dir.name}/credit.lock",
            },
        )
        self.env.start()

    async def asyncTearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    async def test_async_guard_allows_and_posts_only_above_threshold(self):
        completion = build_response(200, {"choices": []}, method="POST")
        client = FakeAsyncClient(
            build_response(
                200,
                {"data": {"total_credits": "20.00", "total_usage": "16.50"}},
            ),
            completion,
        )

        status = await assert_openrouter_background_credit_available_async(
            client,
            base_url="https://openrouter.test/api/v1",
            api_key="secret-key",
        )
        response = await post_openrouter_background_chat_completion_async(
            client,
            base_url="https://openrouter.test/api/v1",
            api_key="secret-key",
            headers={"Authorization": "Bearer secret-key"},
            json={"model": "test"},
        )

        self.assertEqual(str(status.remaining_usd), "3.50")
        self.assertIs(response, completion)
        self.assertEqual(len(client.post_calls), 1)

    async def test_async_background_completions_are_serialized(self):
        state = {"active": 0, "max_active": 0}

        class SerializedClient(FakeAsyncClient):
            async def post(self, url, **kwargs):
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
                await asyncio.sleep(0.02)
                state["active"] -= 1
                return build_response(200, {"choices": []}, method="POST")

        client = SerializedClient(
            build_response(
                200,
                {"data": {"total_credits": 20.0, "total_usage": 10.0}},
            )
        )

        await asyncio.gather(
            *(
                post_openrouter_background_chat_completion_async(
                    client,
                    base_url="https://openrouter.test/api/v1",
                    api_key="secret-key",
                    headers={"Authorization": "Bearer secret-key"},
                    json={"model": "test"},
                )
                for _ in range(2)
            )
        )

        self.assertEqual(state["max_active"], 1)
