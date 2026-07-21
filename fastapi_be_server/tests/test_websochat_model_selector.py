import json
import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from app.exceptions import CustomResponseException
from app.schemas.websochat import (
    PatchWebsochatSessionModelReqBody,
    PostWebsochatMessageReqBody,
    PostWebsochatSessionReqBody,
)
from app.services.websochat import websochat_service
from app.services.websochat.websochat_game_memory import (
    _normalize_websochat_session_memory,
    _serialize_websochat_session_memory,
)
from app.services.websochat.websochat_model_catalog import (
    WEBSOCHAT_MODEL_CATALOG,
    build_websochat_model_used,
)
from app.services.websochat import websochat_renderers
from app.services.websochat.websochat_stream import (
    defer_websochat_stream_output,
    emit_websochat_stream_delta,
    flush_deferred_websochat_stream_output,
    replace_deferred_websochat_stream_output,
    reset_websochat_stream_emitter,
    reset_websochat_stream_output,
    set_websochat_stream_emitter,
)


class WebsochatModelCatalogTests(unittest.TestCase):
    def test_model_catalog_is_the_single_business_contract(self):
        self.assertEqual(
            [
                (
                    spec.model_key,
                    spec.display_name,
                    spec.provider,
                    spec.provider_model,
                    spec.cash_cost,
                    spec.character_chat_daily_free_limit,
                    spec.thinking_level,
                )
                for spec in WEBSOCHAT_MODEL_CATALOG
            ],
            [
                (
                    "speed",
                    "스피드",
                    "gemini",
                    websochat_service.settings.WEBSOCHAT_GEMINI_MODEL,
                    20,
                    10,
                    "minimal",
                ),
                (
                    "balance",
                    "밸런스",
                    "gemini",
                    websochat_service.settings.WEBSOCHAT_GEMINI_MODEL,
                    25,
                    5,
                    "medium",
                ),
                (
                    "deep",
                    "딥",
                    "gemini",
                    websochat_service.settings.WEBSOCHAT_GEMINI_MODEL,
                    35,
                    1,
                    "high",
                ),
            ],
        )

    def test_api_accepts_only_stable_model_keys(self):
        request = PostWebsochatMessageReqBody(
            client_message_id="model-key-1",
            content="계속 이야기해줘",
            model_key="balance",
        )
        self.assertEqual(request.model_key, "balance")
        self.assertEqual(
            PostWebsochatSessionReqBody(
                product_id=1,
                model_key="deep",
            ).model_key,
            "deep",
        )
        self.assertEqual(
            PatchWebsochatSessionModelReqBody(model_key="deep").model_key,
            "deep",
        )

        with self.assertRaises(ValidationError):
            PostWebsochatMessageReqBody(
                client_message_id="model-key-2",
                content="계속 이야기해줘",
                model_key="gemini-3.1-flash-lite",
            )

    def test_legacy_and_invalid_memory_default_to_speed(self):
        self.assertEqual(
            _normalize_websochat_session_memory({})["selected_model_key"],
            "speed",
        )
        self.assertEqual(
            _normalize_websochat_session_memory(
                {"selected_model_key": "unknown"}
            )["selected_model_key"],
            "speed",
        )
        serialized = _serialize_websochat_session_memory(
            {"selected_model_key": "deep"}
        )
        self.assertEqual(json.loads(serialized or "{}")["selected_model_key"], "deep")

    def test_usage_log_value_identifies_the_selected_tier(self):
        self.assertEqual(build_websochat_model_used("speed"), "gemini:speed")
        self.assertEqual(build_websochat_model_used("balance"), "gemini:balance")
        self.assertEqual(build_websochat_model_used("deep"), "gemini:deep")

    def test_next_episode_keeps_fixed_default_model_and_price(self):
        effective_key = websochat_service._resolve_websochat_effective_model_key(
            "deep",
            "next_episode_write",
        )
        self.assertEqual(effective_key, "speed")
        self.assertEqual(
            websochat_service._resolve_websochat_message_cash_cost(
                "next_episode_write",
                "deep",
            ),
            30,
        )
        payload = websochat_service._build_websochat_billing_status_payload(
            used_count=3,
            user_id=12,
            cash_balance=100,
            qa_action_key="next_episode_write",
            selected_model_key="deep",
        )
        self.assertEqual(payload["selectedModelKey"], "speed")
        self.assertEqual(
            [option["modelKey"] for option in payload["modelOptions"]],
            ["speed"],
        )
        self.assertEqual(
            websochat_service._build_websochat_session_contract_payload(
                {
                    "session_kind": "websochat",
                    "selected_model_key": "deep",
                }
            )["selectedModelKey"],
            "speed",
        )
        self.assertEqual(payload["cashCostPerMessage"], 30)

    def test_regular_websochat_ignores_tier_selection(self):
        self.assertEqual(
            websochat_service._resolve_websochat_effective_model_key(
                "balance",
                None,
                is_character_chat=False,
            ),
            "speed",
        )
        self.assertEqual(
            websochat_service._resolve_websochat_effective_model_key(
                "balance",
                None,
                is_character_chat=True,
            ),
            "balance",
        )
        payload = websochat_service._build_websochat_billing_status_payload(
            used_count=2,
            user_id=12,
            cash_balance=100,
            is_character_chat=False,
            selected_model_key="balance",
        )
        self.assertEqual(payload["selectedModelKey"], "speed")
        self.assertEqual(payload["dailyFreeMessageLimit"], 3)
        self.assertEqual(payload["cashCostPerMessage"], 20)
        self.assertEqual(
            [option["modelKey"] for option in payload["modelOptions"]],
            ["speed"],
        )

    def test_character_chat_billing_exposes_independent_free_pools(self):
        payload = websochat_service._build_websochat_billing_status_payload(
            used_count=4,
            user_id=12,
            cash_balance=100,
            is_character_chat=True,
            selected_model_key="balance",
            used_counts_by_model={"speed": 4, "balance": 4, "deep": 1},
        )

        self.assertEqual(payload["selectedModelKey"], "balance")
        self.assertEqual(payload["dailyFreeMessageLimit"], 5)
        self.assertEqual(payload["freeRemainingMessages"], 1)
        self.assertEqual(payload["cashCostPerMessage"], 25)
        self.assertEqual(
            [
                (
                    option["modelKey"],
                    option["freeRemainingMessages"],
                )
                for option in payload["modelOptions"]
            ],
            [("speed", 6), ("balance", 1), ("deep", 0)],
        )


class WebsochatSessionModelPatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_patch_model_persists_under_the_session_lock(self):
        db = AsyncMock()
        lock_connection = AsyncMock()
        with (
            patch.object(
                websochat_service,
                "_resolve_actor",
                new_callable=AsyncMock,
                return_value=(42, None),
            ),
            patch.object(
                websochat_service,
                "_get_session_row",
                new_callable=AsyncMock,
                return_value={
                    "session_memory_json": (
                        '{"session_kind":"character_chat",'
                        '"selected_model_key":"speed"}'
                    )
                },
            ),
            patch.object(
                websochat_service,
                "_acquire_websochat_session_lock",
                new_callable=AsyncMock,
                return_value=lock_connection,
            ),
            patch.object(
                websochat_service,
                "_release_websochat_session_lock",
                new_callable=AsyncMock,
            ) as release_lock,
        ):
            result = await websochat_service.patch_session_model(
                session_id=77,
                req_body=PatchWebsochatSessionModelReqBody(model_key="deep"),
                kc_user_id="kc-user",
                db=db,
            )

        self.assertEqual(result["data"]["selectedModelKey"], "deep")
        update_params = db.execute.await_args.args[1]
        self.assertEqual(
            json.loads(update_params["session_memory_json"])["selected_model_key"],
            "deep",
        )
        db.commit.assert_awaited_once()
        db.rollback.assert_awaited_once()
        release_lock.assert_awaited_once_with(session_id=77, conn=lock_connection)

    async def test_patch_model_rejects_regular_websochat_session(self):
        db = AsyncMock()
        lock_connection = AsyncMock()
        with (
            patch.object(
                websochat_service,
                "_resolve_actor",
                new_callable=AsyncMock,
                return_value=(42, None),
            ),
            patch.object(
                websochat_service,
                "_get_session_row",
                new_callable=AsyncMock,
                return_value={"session_memory_json": '{"session_kind":"websochat"}'},
            ),
            patch.object(
                websochat_service,
                "_acquire_websochat_session_lock",
                new_callable=AsyncMock,
                return_value=lock_connection,
            ),
            patch.object(
                websochat_service,
                "_release_websochat_session_lock",
                new_callable=AsyncMock,
            ) as release_lock,
        ):
            with self.assertRaises(CustomResponseException) as raised:
                await websochat_service.patch_session_model(
                    session_id=77,
                    req_body=PatchWebsochatSessionModelReqBody(model_key="deep"),
                    kc_user_id="kc-user",
                    db=db,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("주인공챗", raised.exception.message)
        db.commit.assert_not_awaited()
        release_lock.assert_awaited_once_with(session_id=77, conn=lock_connection)


class WebsochatModelExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_character_chat_balance_preserves_selected_tier(self):
        with (
            patch.object(websochat_service.settings, "GEMINI_API_KEY", "test-key"),
            patch.object(
                websochat_service,
                "_load_websochat_rp_context",
                new_callable=AsyncMock,
                return_value={"display_name": "주인공"},
            ),
            patch.object(
                websochat_service,
                "_get_websochat_recent_messages",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch.object(
                websochat_service,
                "_build_websochat_rp_exact_recall_context",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                websochat_service,
                "generate_websochat_rp_reply_with_gemini",
                new_callable=AsyncMock,
                return_value="주인공의 답변",
            ) as generate_reply,
        ):
            result = await websochat_service._generate_websochat_reply(
                session_id=7,
                session_memory={
                    "session_kind": "character_chat",
                    "read_scope_state": "known",
                    "read_episode_to": 3,
                    "active_mode": "rp",
                    "active_character": "character:주인공",
                    "locked_character_scope_key": "character:주인공",
                    "rp_mode": "free",
                },
                product_row={"productId": 11, "title": "테스트", "latestEpisodeNo": 3},
                user_prompt="계속 이야기해줘",
                user_id=12,
                db=AsyncMock(),
                forced_route="rp",
                model_key="balance",
            )

        self.assertEqual(result[0], "주인공의 답변")
        self.assertEqual(result[1], "gemini:balance")
        self.assertEqual(generate_reply.await_args.kwargs["model_key"], "balance")

    async def test_game_to_qa_recursion_preserves_selected_model(self):
        expected = ("답변", "gemini:deep", "qa", False, "factual", {})
        with (
            patch.object(
                websochat_service,
                "_build_websochat_read_scope_label",
                new_callable=AsyncMock,
                return_value="3화",
            ),
            patch.object(
                websochat_service,
                "_generate_websochat_reply",
                new_callable=AsyncMock,
                return_value=expected,
            ) as generate_reply,
        ):
            result = await websochat_service._generate_websochat_game_reply(
                session_id=7,
                session_memory={
                    "active_mode": "ideal_worldcup",
                    "game_context": {"mode": "ideal_worldcup"},
                    "read_episode_to": 3,
                },
                product_row={"productId": 11, "title": "테스트"},
                user_prompt="작품의 복선을 설명해줘",
                db=AsyncMock(),
                model_key="deep",
            )

        self.assertEqual(result, expected)
        self.assertEqual(generate_reply.await_args.kwargs["model_key"], "deep")

    async def test_game_renderer_passes_selected_model(self):
        with patch.object(
            websochat_renderers,
            "call_websochat_game_host_model",
            new_callable=AsyncMock,
            return_value="비교 결과",
        ) as call_model:
            await websochat_renderers.generate_websochat_vs_comparison(
                product_row={"title": "테스트"},
                category="power",
                match_pair=[
                    {
                        "display_name": "A",
                        "personality_core": [],
                        "baseline_attitude": "",
                        "examples": [],
                    },
                    {
                        "display_name": "B",
                        "personality_core": [],
                        "baseline_attitude": "",
                        "examples": [],
                    },
                ],
                model_key="balance",
            )

        self.assertEqual(call_model.await_args.kwargs["model_key"], "balance")

    async def test_paid_stream_buffer_discards_output_without_flush(self):
        emitted: list[str] = []

        async def emitter(value: str) -> None:
            emitted.append(value)

        emitter_tokens = set_websochat_stream_emitter(emitter)
        deferred_token = defer_websochat_stream_output()
        try:
            await emit_websochat_stream_delta("provider partial")
            replace_deferred_websochat_stream_output("final reply")
            self.assertEqual(emitted, [])
        finally:
            reset_websochat_stream_output(deferred_token)
            reset_websochat_stream_emitter(emitter_tokens)

        self.assertEqual(emitted, [])

    async def test_paid_stream_flushes_final_reply_after_commit_boundary(self):
        emitted: list[str] = []

        async def emitter(value: str) -> None:
            emitted.append(value)

        emitter_tokens = set_websochat_stream_emitter(emitter)
        deferred_token = defer_websochat_stream_output()
        try:
            await emit_websochat_stream_delta("provider partial")
            replace_deferred_websochat_stream_output("sanitized final")
            self.assertEqual(emitted, [])
            await flush_deferred_websochat_stream_output()
            self.assertEqual(emitted, ["sanitized final"])
        finally:
            reset_websochat_stream_output(deferred_token)
            reset_websochat_stream_emitter(emitter_tokens)

    def test_only_provider_generated_replies_are_billable(self):
        for model_used in ("system", "guard", "game-host", "heuristic"):
            with self.subTest(model_used=model_used):
                self.assertFalse(
                    websochat_service._is_websochat_billable_model_used(model_used)
                )
        for model_used in (
            "gemini",
            "gemini:speed",
            "gemini:balance",
            "gemini:deep",
        ):
            with self.subTest(model_used=model_used):
                self.assertTrue(
                    websochat_service._is_websochat_billable_model_used(model_used)
                )


if __name__ == "__main__":
    unittest.main()
