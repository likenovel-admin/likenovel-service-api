import importlib.util
import asyncio
import io
import json
import os
import sys
import tempfile
from contextlib import ExitStack, contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest import TestCase
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import httpx


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_story_agent_context.py"


def load_module():
    module_name = "build_story_agent_context_under_test"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    previous_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as temp_dir:
        Path(temp_dir, "logs", "data").mkdir(parents=True, exist_ok=True)
        Path(temp_dir, "logs", "error").mkdir(parents=True, exist_ok=True)
        os.chdir(temp_dir)
        try:
            spec.loader.exec_module(module)
        finally:
            os.chdir(previous_cwd)
    return module


def signal_row(summary_id: int, episode_no: int, characters: list[dict]) -> dict:
    return {
        "summary_id": summary_id,
        "episode_from": episode_no,
        "source_hash": f"signal-{summary_id}",
        "summary_text": json.dumps(
            {
                "episode_no": episode_no,
                "mentioned_characters": characters,
                "cliffhanger_hooks": [],
            },
            ensure_ascii=False,
        ),
    }


def signal_character(
    *,
    character_key: str,
    display_name: str,
    aliases: list[str] | None = None,
    is_protagonist: bool = False,
    is_work_protagonist: bool | None = None,
    is_episode_focal: bool | None = None,
    is_first_person: bool = False,
    narration_names: list[str] | None = None,
    social_call_names: list[str] | None = None,
    persona_names: list[str] | None = None,
    real_names: list[str] | None = None,
    entity_kind: str = "person",
    role_in_episode: str = "support",
    voice_mode: str = "narration_only",
    scene_weight: str = "low",
    action_tags: list[str] | None = None,
    affect_tags: list[str] | None = None,
    relation_edges: list[dict] | None = None,
    identity_claims: list[dict] | None = None,
) -> dict:
    return {
        "character_key": character_key,
        "display_name": display_name,
        "aliases": aliases or [display_name],
        "is_protagonist": is_protagonist,
        "is_work_protagonist": is_protagonist if is_work_protagonist is None else is_work_protagonist,
        "is_episode_focal": is_protagonist if is_episode_focal is None else is_episode_focal,
        "is_first_person": is_first_person,
        "narration_names": narration_names or [],
        "social_call_names": social_call_names or [],
        "persona_names": persona_names or [],
        "real_names": real_names or [],
        "entity_kind": entity_kind,
        "scene_weight": scene_weight,
        "role_in_episode": role_in_episode,
        "voice_mode": voice_mode,
        "action_tags": action_tags or [],
        "affect_tags": affect_tags or [],
        "relation_edges": relation_edges or [],
        "identity_claims": identity_claims or [],
        "episode_no": 0,
    }


class FakeConnection:
    def __init__(self):
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def close(self):
        self.close_count += 1


class FakeRowsCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = ""
        self.params = None

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


@contextmanager
def fake_work_cursor(_conn):
    yield object()


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeOpenRouterClient:
    def __init__(self, content):
        self.content = content
        self.calls = []
        self.credit_calls = []

    async def get(self, url, **kwargs):
        self.credit_calls.append({"url": url, **kwargs})
        return FakeResponse(
            {"data": {"total_credits": 20.0, "total_usage": 10.0}}
        )

    async def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {"content": json.dumps(self.content, ensure_ascii=False)},
                        "finish_reason": "stop",
                    }
                ]
            }
        )


class FakeHangingOpenRouterClient:
    def __init__(self):
        self.calls = []

    async def get(self, url, **kwargs):
        return FakeResponse(
            {"data": {"total_credits": 20.0, "total_usage": 10.0}}
        )

    async def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        await asyncio.sleep(3600)


class FakeRateLimitedOpenRouterClient:
    def __init__(self, content, *, retry_after: str = "7"):
        self.content = content
        self.retry_after = retry_after
        self.calls = []

    async def get(self, url, **kwargs):
        return FakeResponse(
            {"data": {"total_credits": 20.0, "total_usage": 10.0}}
        )

    async def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if len(self.calls) == 1:
            request = httpx.Request("POST", url)
            return httpx.Response(
                429,
                headers={"Retry-After": self.retry_after},
                request=request,
            )
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {"content": json.dumps(self.content, ensure_ascii=False)},
                        "finish_reason": "stop",
                    }
                ]
            }
        )


class FakeStatusErrorAsyncClient:
    def __init__(self, status_code: int, body: str = ""):
        self.status_code = status_code
        self.body = body
        self.calls = []
        self.closed = False

    async def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        request = httpx.Request("POST", url)
        response = httpx.Response(self.status_code, text=self.body, request=request)
        raise httpx.HTTPStatusError(f"Client error '{self.status_code}'", request=request, response=response)

    async def aclose(self):
        self.closed = True


class FakeCreditAsyncClient:
    def __init__(self, *, total_credits: float, total_usage: float):
        self.total_credits = total_credits
        self.total_usage = total_usage
        self.calls = []
        self.closed = False

    async def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return FakeResponse(
            {
                "data": {
                    "total_credits": self.total_credits,
                    "total_usage": self.total_usage,
                }
            }
        )

    async def aclose(self):
        self.closed = True


class StoryAgentContextCostGuardTest(IsolatedAsyncioTestCase):
    def test_work_cursor_never_reconnects_across_bundle_transaction(self):
        module = load_module()
        conn = MagicMock()

        with module.work_cursor(conn):
            pass

        conn.ping.assert_called_once_with(reconnect=False)

        disconnected = MagicMock()
        disconnected.ping.side_effect = RuntimeError("connection lost")
        with self.assertRaisesRegex(RuntimeError, "connection lost"):
            with module.work_cursor(disconnected):
                self.fail("disconnected cursor must not be yielded")
        disconnected.cursor.assert_not_called()

    def test_partial_full_build_scopes_downstream_rows_without_cleanup(self):
        module = load_module()
        product_rows = [
            {"episode_id": 1000 + episode_no, "episode_no": episode_no}
            for episode_no in range(1, 16)
        ]
        active_rows = [
            {
                "scope_key": f"episode:{1000 + episode_no}",
                "episode_from": episode_no,
            }
            for episode_no in range(1, 24)
        ]

        selected_rows, cleanup_missing_scopes = module.select_full_build_episode_rows(
            product_rows=product_rows,
            episode_summary_rows=active_rows,
            args=SimpleNamespace(
                episode_ids=[],
                episode_nos=list(range(1, 16)),
                limit=0,
            ),
        )

        self.assertEqual(
            [int(row["episode_from"]) for row in selected_rows],
            list(range(1, 16)),
        )
        self.assertFalse(cleanup_missing_scopes)

    def test_unfiltered_full_build_keeps_all_rows_and_cleanup(self):
        module = load_module()
        active_rows = [{"scope_key": "episode:1001", "episode_from": 1}]

        selected_rows, cleanup_missing_scopes = module.select_full_build_episode_rows(
            product_rows=[{"episode_id": 1001, "episode_no": 1}],
            episode_summary_rows=active_rows,
            args=SimpleNamespace(episode_ids=[], episode_nos=[], limit=0),
        )

        self.assertIs(selected_rows, active_rows)
        self.assertTrue(cleanup_missing_scopes)

    async def test_rp_examples_hash_changes_when_provenance_changes(self):
        module = load_module()
        common = {
            "character_key": "character:루벤",
            "inventory_item": None,
            "summary_context_lines": [],
            "relation_context_lines": [],
        }
        first_hash = module.build_rp_examples_source_hash(
            **common,
            example_payload={
                "examples": [
                    {
                        "episode_no": 1,
                        "source_kind": "dialogue",
                        "text": "그만 물러서.",
                        "confidence": 0.9,
                    }
                ]
            },
        )
        corrected_hash = module.build_rp_examples_source_hash(
            **common,
            example_payload={
                "examples": [
                    {
                        "episode_no": 2,
                        "source_kind": "dialogue",
                        "text": "그만 물러서.",
                        "confidence": 0.9,
                    }
                ]
            },
        )
        source_kind_hash = module.build_rp_examples_source_hash(
            **common,
            example_payload={
                "examples": [
                    {
                        "episode_no": 1,
                        "source_kind": "narration",
                        "text": "그만 물러서.",
                        "confidence": 0.9,
                    }
                ]
            },
        )
        confidence_hash = module.build_rp_examples_source_hash(
            **common,
            example_payload={
                "examples": [
                    {
                        "episode_no": 1,
                        "source_kind": "dialogue",
                        "text": "그만 물러서.",
                        "confidence": 0.7,
                    }
                ]
            },
        )
        repeated_hash = module.build_rp_examples_source_hash(
            **common,
            example_payload={
                "examples": [
                    {
                        "episode_no": 1,
                        "source_kind": "dialogue",
                        "text": "그만 물러서.",
                        "confidence": 0.9,
                    }
                ]
            },
        )

        self.assertNotEqual(first_hash, corrected_hash)
        self.assertNotEqual(first_hash, source_kind_hash)
        self.assertNotEqual(first_hash, confidence_hash)
        self.assertEqual(first_hash, repeated_hash)

    def test_rp_hashes_follow_inventory_v3_action_and_affect_changes(self):
        module = load_module()
        base_inventory = {
            "canonical_character_key": "character:루벤",
            "dominant_action_tags": ["추적"],
            "dominant_affect_tags": ["경계"],
        }
        changed_inventory = {
            **base_inventory,
            "dominant_action_tags": ["구출"],
            "dominant_affect_tags": ["결의"],
        }
        profile_common = {
            "character_key": "character:루벤",
            "dialogue_items": [{"episode_no": 1, "text": "내가 확인하겠다."}],
            "summary_context_lines": ["1화 사건"],
            "relation_context_lines": ["동료와 협력"],
        }
        examples_common = {
            "character_key": "character:루벤",
            "example_payload": {
                "examples": [
                    {
                        "episode_no": 1,
                        "source_kind": "dialogue",
                        "text": "내가 확인하겠다.",
                        "confidence": 0.9,
                    }
                ]
            },
            "summary_context_lines": ["1화 사건"],
            "relation_context_lines": ["동료와 협력"],
        }

        self.assertNotEqual(
            module.build_character_inventory_v3_source_hash(base_inventory),
            module.build_character_inventory_v3_source_hash(changed_inventory),
        )
        self.assertNotEqual(
            module.build_rp_profile_source_hash(
                **profile_common,
                inventory_item=base_inventory,
            ),
            module.build_rp_profile_source_hash(
                **profile_common,
                inventory_item=changed_inventory,
            ),
        )
        self.assertNotEqual(
            module.build_rp_examples_source_hash(
                **examples_common,
                inventory_item=base_inventory,
            ),
            module.build_rp_examples_source_hash(
                **examples_common,
                inventory_item=changed_inventory,
            ),
        )

    def test_rp_hashes_follow_inventory_v3_first_person_changes(self):
        module = load_module()
        base_inventory = {
            "canonical_character_key": "character:루벤",
            "is_first_person": False,
            "first_person_evidence": {"episode_count": 0},
        }
        changed_inventory = {
            **base_inventory,
            "is_first_person": True,
            "first_person_evidence": {"episode_count": 3},
        }
        profile_common = {
            "character_key": "character:루벤",
            "dialogue_items": [{"episode_no": 1, "text": "내가 확인하겠다."}],
            "summary_context_lines": ["1화 사건"],
            "relation_context_lines": [],
        }
        examples_common = {
            "character_key": "character:루벤",
            "example_payload": {
                "examples": [{"episode_no": 1, "text": "내가 확인하겠다."}]
            },
            "summary_context_lines": ["1화 사건"],
            "relation_context_lines": [],
        }

        self.assertNotEqual(
            module.build_character_inventory_v3_source_hash(base_inventory),
            module.build_character_inventory_v3_source_hash(changed_inventory),
        )
        self.assertNotEqual(
            module.build_rp_profile_source_hash(
                **profile_common,
                inventory_item=base_inventory,
            ),
            module.build_rp_profile_source_hash(
                **profile_common,
                inventory_item=changed_inventory,
            ),
        )
        self.assertNotEqual(
            module.build_rp_examples_source_hash(
                **examples_common,
                inventory_item=base_inventory,
            ),
            module.build_rp_examples_source_hash(
                **examples_common,
                inventory_item=changed_inventory,
            ),
        )

    async def test_full_apply_preflight_reserve_is_deferred_before_product_lock(self):
        module = load_module()
        client = FakeCreditAsyncClient(total_credits=20.0, total_usage=17.01)
        conn = FakeConnection()
        args = SimpleNamespace(apply=True, verbose=False)

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "EPISODE_SUMMARY_MODEL", "deepseek/deepseek-v3.2"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "AsyncClient", return_value=client), \
             patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "fetch_total_episode_count", return_value=30), \
             patch.object(module, "fetch_product_ready_episode_count", return_value=12), \
             patch.object(module, "fetch_product_context_status", return_value="ready"), \
             patch.object(module, "product_lock_connection") as product_lock:
            results = await module.build_context_rows(
                rows=[{"product_id": 687}],
                args=args,
            )

        self.assertEqual(len(client.calls), 1)
        self.assertTrue(client.calls[0]["url"].endswith("/credits"))
        self.assertTrue(client.closed)
        self.assertEqual(conn.close_count, 1)
        product_lock.assert_not_called()
        self.assertEqual(results["deferred_budget"], 1)
        self.assertEqual(results["products"][0]["context_status"], "deferred_budget")
        self.assertEqual(results["products"][0]["persisted_context_status"], "ready")

    async def test_apply_preflights_anthropic_billing_before_product_lock(self):
        module = load_module()
        client = FakeStatusErrorAsyncClient(
            400,
            '{"error":{"message":"Your credit balance is too low. Please purchase credits."}}',
        )
        conn = FakeConnection()
        args = SimpleNamespace(apply=True, verbose=False)

        with patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module.settings, "ANTHROPIC_API_KEY", "anthropic-key"), \
             patch.object(module, "RP_REASONING_MODEL", "claude-haiku-4-5-20251001"), \
             patch.object(module, "AsyncClient", return_value=client), \
             patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "product_lock_connection") as product_lock:
            with self.assertRaisesRegex(RuntimeError, "Anthropic preflight failed"):
                await module.build_context_rows(
                    rows=[{"product_id": 687}],
                    args=args,
                )

        self.assertEqual(len(client.calls), 1)
        self.assertIn("api.anthropic.com", client.calls[0]["url"])
        self.assertTrue(client.closed)
        self.assertEqual(conn.close_count, 1)
        product_lock.assert_not_called()

    async def test_delta_apply_touches_attempt_before_provider_preflight(self):
        module = load_module()
        conn = FakeConnection()
        preflight = AsyncMock(side_effect=RuntimeError("provider unavailable"))

        with patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module.settings, "ANTHROPIC_API_KEY", ""), \
             patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "touch_product_context_build_attempt") as touch, \
             patch.object(module, "assert_storyctx_apply_providers_ready", preflight), \
             patch.object(module, "product_lock_connection") as product_lock:
            with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                await module.build_context_rows_delta(
                    rows=[{"product_id": 687, "_character_asset_collection_eligible": True}],
                    args=SimpleNamespace(apply=True, verbose=False),
                )

        touch.assert_called_once_with(ANY, product_id=687)
        self.assertEqual(conn.commit_count, 1)
        self.assertEqual(conn.close_count, 1)
        product_lock.assert_not_called()

    async def test_delta_reserve_exhaustion_is_deferred_without_marking_product_failed(self):
        module = load_module()
        conn = FakeConnection()
        preflight = AsyncMock(
            side_effect=module.OpenRouterBackgroundCreditReserveError(
                "background credit reserve blocked"
            )
        )

        with patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "touch_product_context_build_attempt"), \
             patch.object(module, "assert_storyctx_apply_providers_ready", preflight), \
             patch.object(module, "fetch_total_episode_count", return_value=30), \
             patch.object(module, "fetch_product_ready_episode_count", return_value=12), \
             patch.object(module, "fetch_product_context_status", return_value="ready"), \
             patch.object(module, "mark_product_context_failed") as mark_failed, \
             patch.object(module, "product_lock_connection") as product_lock:
            results = await module.build_context_rows_delta(
                rows=[{"product_id": 687, "_character_asset_collection_eligible": True}],
                args=SimpleNamespace(apply=True, verbose=False),
            )

        self.assertEqual(results["deferred_budget"], 1)
        self.assertEqual(
            results["products"],
            [
                {
                    "product_id": 687,
                    "context_status": "deferred_budget",
                    "persisted_context_status": "ready",
                    "total_episode_count": 30,
                    "ready_episode_count": 12,
                }
            ],
        )
        self.assertEqual(
            module.build_delta_exit_code(results, apply=True),
            module.STORYCTX_DEFERRED_BUDGET_EXIT_CODE,
        )
        mark_failed.assert_not_called()
        product_lock.assert_not_called()

    async def test_delta_midrun_reserve_exhaustion_is_deferred_without_marking_failed(self):
        module = load_module()
        conn = FakeConnection()
        reserve_error = module.OpenRouterBackgroundCreditReserveError(
            "background credit reserve blocked"
        )
        mark_failed = MagicMock()
        row = {
            "product_id": 687,
            "title": "테스트 작품",
            "episode_id": 101,
            "episode_no": 16,
            "_character_asset_collection_eligible": True,
        }

        patchers = [
            patch.object(module, "OPENROUTER_API_KEY", ""),
            patch.object(module.settings, "ANTHROPIC_API_KEY", ""),
            patch.object(module, "db_connect", return_value=conn),
            patch.object(module, "work_cursor", fake_work_cursor),
            patch.object(
                module,
                "product_lock_connection",
                return_value=module.nullcontext(object()),
            ),
            patch.object(module, "touch_product_context_build_attempt"),
            patch.object(module, "assert_storyctx_apply_providers_ready", AsyncMock()),
            patch.object(module, "fetch_total_episode_count", return_value=30),
            patch.object(module, "fetch_product_ready_episode_count", return_value=12),
            patch.object(module, "fetch_product_context_status", return_value="ready"),
            patch.object(module, "fetch_active_character_inventory_map", return_value={}),
            patch.object(
                module,
                "fetch_active_relation_inventory_by_relation_key_map",
                return_value={},
            ),
            patch.object(module, "fetch_active_summary_state_map", return_value={}),
            patch.object(
                module,
                "fetch_active_summary_rows_for_episode_nos",
                return_value=[],
            ),
            patch.object(
                module,
                "resolve_source_payload",
                AsyncMock(return_value={"html_content": "본문", "source_type": "db"}),
            ),
            patch.object(module, "normalize_episode_html", return_value="정규화 본문"),
            patch.object(module, "build_chunks", return_value=[{"chunk_text": "본문"}]),
            patch.object(module, "fetch_existing_doc", return_value=None),
            patch.object(module, "insert_doc_and_chunks"),
            patch.object(
                module,
                "insert_episode_summary",
                AsyncMock(side_effect=reserve_error),
            ),
            patch.object(module, "mark_product_context_failed", mark_failed),
        ]

        with ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            results = await module.build_context_rows_delta(
                rows=[row],
                args=SimpleNamespace(
                    apply=True,
                    verbose=False,
                    use_epub_fallback=False,
                    refresh_rp=False,
                ),
            )

        self.assertEqual(results["deferred_budget"], 1)
        self.assertEqual(results["products"][0]["context_status"], "deferred_budget")
        self.assertEqual(results["products"][0]["persisted_context_status"], "ready")
        self.assertEqual(
            module.build_delta_exit_code(results, apply=True),
            module.STORYCTX_DEFERRED_BUDGET_EXIT_CODE,
        )
        mark_failed.assert_not_called()

    async def test_out_of_cohort_ready_delta_builds_foundation_but_skips_character_assets(self):
        module = load_module()
        conn = FakeConnection()
        episode_summary_row = {
            "summary_id": 11,
            "scope_key": "episode:101",
            "episode_from": 16,
            "source_hash": "summary-hash",
            "summary_text": "[16화] 요약",
        }
        row = {
            "product_id": 787,
            "title": "grandfather 작품",
            "episode_id": 101,
            "episode_no": 16,
            "character_asset_episode_eligible": 1,
            "_character_asset_collection_eligible": False,
        }
        summary_builder = AsyncMock(return_value=(11, True, {"used_llm": True}))
        signal_builder = AsyncMock(return_value=(1, 0, True))
        scene_builder = AsyncMock(return_value=(1, 0))
        rp_builder = AsyncMock(return_value={"profile": (1, 0), "examples": (1, 0)})
        compute_rp = MagicMock()
        patchers = [
            patch.object(module, "OPENROUTER_API_KEY", ""),
            patch.object(module.settings, "ANTHROPIC_API_KEY", ""),
            patch.object(module, "db_connect", return_value=conn),
            patch.object(module, "work_cursor", fake_work_cursor),
            patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())),
            patch.object(module, "touch_product_context_build_attempt"),
            patch.object(module, "assert_storyctx_apply_providers_ready", AsyncMock()),
            patch.object(module, "fetch_total_episode_count", return_value=16),
            patch.object(module, "fetch_active_character_inventory_map", return_value={}),
            patch.object(module, "fetch_active_relation_inventory_by_relation_key_map", return_value={}),
            patch.object(module, "fetch_active_summary_state_map", return_value={}),
            patch.object(module, "fetch_active_summary_rows_for_episode_nos", return_value=[episode_summary_row]),
            patch.object(module, "resolve_source_payload", AsyncMock(return_value={"html_content": "본문", "source_type": "db"})),
            patch.object(module, "normalize_episode_html", return_value="정규화 본문"),
            patch.object(module, "build_chunks", return_value=[{"chunk_text": "정규화 본문"}]),
            patch.object(module, "fetch_existing_doc", return_value=None),
            patch.object(module, "insert_doc_and_chunks"),
            patch.object(module, "insert_episode_summary", summary_builder),
            patch.object(module, "build_episode_character_signals_summaries_nonblocking", signal_builder),
            patch.object(module, "fetch_active_summary_rows", return_value=[episode_summary_row]),
            patch.object(module, "fetch_active_character_asset_summary_rows", return_value=[episode_summary_row]),
            patch.object(module, "build_work_protagonist_resolution_for_inventory_v3", AsyncMock(return_value={})),
            patch.object(module, "build_compound_summaries_delta", return_value={"range": (1, 0), "product": (1, 0)}),
            patch.object(module, "build_character_inventory_summaries_delta", return_value={"inserted_count": 1, "reused_count": 0}),
            patch.object(module, "build_character_inventory_v3_summaries", return_value=(1, 0)),
            patch.object(module, "build_relation_inventory_summaries_delta", return_value={"inserted_count": 1, "reused_count": 0}),
            patch.object(module, "cleanup_duplicate_character_inventory_rows", return_value={"canonical_character_key_by_display_name": {}, "touched_scope_keys": set()}),
            patch.object(module, "cleanup_duplicate_relation_inventory_rows"),
            patch.object(module, "fetch_active_relation_inventory_map", return_value={}),
            patch.object(module, "build_canonical_relation_inventory_map", return_value={}),
            patch.object(module, "fetch_active_episode_texts_by_no", return_value={16: "본문"}),
            patch.object(module, "build_episode_scene_extraction_summaries_nonblocking", scene_builder),
            patch.object(module, "compute_rp_affected_scope_keys", compute_rp),
            patch.object(module, "build_rp_summaries_delta", rp_builder),
            patch.object(module, "build_delta_inventory_verification", return_value={"product_id": 787}),
            patch.object(module, "build_rp_delta_verification", return_value={}),
            patch.object(module, "assert_story_agent_foundation_invariants"),
            patch.object(module, "refresh_product_context_status", return_value={"product_id": 787, "context_status": "ready"}),
            patch.object(module, "attach_character_chat_asset_readiness_to_status_row", side_effect=lambda _cur, status: status),
        ]

        with ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            results = await module.build_context_rows_delta(
                rows=[row],
                args=SimpleNamespace(
                    apply=True,
                    verbose=False,
                    use_epub_fallback=False,
                    refresh_rp=False,
                ),
            )

        summary_builder.assert_awaited_once()
        signal_builder.assert_awaited_once()
        scene_builder.assert_not_awaited()
        compute_rp.assert_not_called()
        rp_builder.assert_not_awaited()
        self.assertEqual(results["inserted_summaries"], 1)
        self.assertEqual(results["inserted_episode_character_signals"], 1)
        self.assertEqual(results["products"][0]["context_status"], "ready")

    async def test_delta_public_main_bundle_reuses_ready_scene_and_requires_current_rp(self):
        module = load_module()
        conn = FakeConnection()
        scope_key = "character:new-main"
        episode_summary_row = {
            "summary_id": 11,
            "scope_key": "episode:101",
            "episode_from": 16,
            "source_hash": "summary-hash",
            "summary_text": "[16화] 요약",
        }
        row = {
            "product_id": 787,
            "title": "테스트 작품",
            "episode_id": 101,
            "episode_no": 16,
            "character_asset_episode_eligible": 1,
            "_character_asset_collection_eligible": True,
        }
        old_v3_map = {
            "character:old-main": {
                "work_role": "main_protagonist",
                "public_chat_eligible": True,
            }
        }
        new_v3_map = {
            scope_key: {
                "canonical_character_key": scope_key,
                "display_name": "새 주인공",
                "work_role": "main_protagonist",
                "is_protagonist": True,
                "public_chat_eligible": True,
                "evidence_episode_nos": [1, 2, 3],
            }
        }
        v3_reads = iter([old_v3_map, new_v3_map])
        asset_commit_counts = []

        def fetch_inventory_map(*, summary_type="character_inventory", **_kwargs):
            if summary_type == "character_inventory_v3":
                return next(v3_reads)
            return {}

        async def build_scene(**kwargs):
            asset_commit_counts.append(conn.commit_count)
            return 1, 0

        async def build_rp(**kwargs):
            asset_commit_counts.append(conn.commit_count)
            kwargs["processed_scope_keys"].add(scope_key)
            return {"profile": (1, 0), "examples": (1, 0)}

        scene_builder = AsyncMock(side_effect=build_scene)
        rp_builder = AsyncMock(side_effect=build_rp)
        patchers = [
            patch.object(module, "OPENROUTER_API_KEY", ""),
            patch.object(module.settings, "ANTHROPIC_API_KEY", ""),
            patch.object(module, "db_connect", return_value=conn),
            patch.object(module, "work_cursor", fake_work_cursor),
            patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())),
            patch.object(module, "touch_product_context_build_attempt"),
            patch.object(module, "assert_storyctx_apply_providers_ready", AsyncMock()),
            patch.object(module, "fetch_total_episode_count", return_value=16),
            patch.object(module, "fetch_active_character_inventory_map", side_effect=fetch_inventory_map),
            patch.object(module, "filter_character_inventory_map_to_signal_scope", side_effect=lambda inventory_map, **_kwargs: inventory_map),
            patch.object(module, "fetch_active_relation_inventory_by_relation_key_map", return_value={}),
            patch.object(module, "fetch_active_summary_state_map", return_value={}),
            patch.object(module, "fetch_active_summary_rows_for_episode_nos", return_value=[episode_summary_row]),
            patch.object(module, "resolve_source_payload", AsyncMock(return_value={"html_content": "본문", "source_type": "db"})),
            patch.object(module, "normalize_episode_html", return_value="정규화 본문"),
            patch.object(module, "build_chunks", return_value=[{"chunk_text": "정규화 본문"}]),
            patch.object(module, "fetch_existing_doc", return_value=None),
            patch.object(module, "insert_doc_and_chunks"),
            patch.object(module, "insert_episode_summary", AsyncMock(return_value=(11, True, {"used_llm": True}))),
            patch.object(module, "build_episode_character_signals_summaries_nonblocking", AsyncMock(return_value=(1, 0, True))),
            patch.object(module, "fetch_active_character_asset_summary_rows", return_value=[episode_summary_row]),
            patch.object(module, "build_work_protagonist_resolution_for_inventory_v3", AsyncMock(return_value={})),
            patch.object(module, "build_compound_summaries_delta", return_value={"range": (1, 0), "product": (1, 0)}),
            patch.object(module, "build_character_inventory_summaries_delta", return_value={"inserted_count": 1, "reused_count": 0}),
            patch.object(module, "build_character_inventory_v3_summaries", return_value=(1, 0)),
            patch.object(module, "build_relation_inventory_summaries_delta", return_value={"inserted_count": 1, "reused_count": 0}),
            patch.object(module, "fetch_active_episode_texts_by_no", return_value={16: "본문"}),
            patch.object(module, "build_episode_scene_extraction_summaries_nonblocking", scene_builder),
            patch.object(module, "compute_rp_affected_scope_keys", return_value={scope_key}),
            patch.object(module, "select_delta_rp_scope_keys", return_value={scope_key}),
            patch.object(module, "fetch_rp_ready_character_inventory_history_state_map", return_value={}),
            patch.object(module, "build_rp_summaries_delta", rp_builder),
            patch.object(module, "build_delta_inventory_verification", return_value={"product_id": 787}),
            patch.object(module, "build_rp_delta_verification", return_value={}),
            patch.object(module, "assert_story_agent_foundation_invariants"),
            patch.object(module, "refresh_product_context_status", return_value={"product_id": 787, "context_status": "ready"}),
            patch.object(
                module,
                "attach_character_chat_asset_readiness_to_status_row",
                side_effect=lambda _cur, status: {
                    **status,
                    "character_chat_asset_readiness": {
                        "ready_main_protagonist_scope_keys": [scope_key]
                    },
                },
            ),
        ]

        with ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            results = await module.build_context_rows_delta(
                rows=[row],
                args=SimpleNamespace(
                    apply=True,
                    verbose=False,
                    use_epub_fallback=False,
                    refresh_rp=False,
                ),
            )

        self.assertEqual(asset_commit_counts, [2, 2])
        self.assertEqual(conn.commit_count, 3)
        self.assertFalse(scene_builder.await_args.kwargs["commit_changes"])
        self.assertEqual(results["inserted_character_inventory_v3"], 1)
        self.assertEqual(results["inserted_episode_scene_extractions"], 1)
        self.assertEqual(results["inserted_character_rp_profiles"], 1)
        self.assertEqual(results["inserted_character_rp_examples"], 1)

    async def test_delta_above_character_cap_keeps_episode_summary_but_skips_character_collection(self):
        module = load_module()
        conn = FakeConnection()
        episode_summary_row = {
            "summary_id": 31,
            "scope_key": "episode:131",
            "episode_from": 31,
            "source_hash": "summary-hash-31",
            "summary_text": "[31화] 요약",
        }
        row = {
            "product_id": 787,
            "title": "30화 제한 작품",
            "episode_id": 131,
            "episode_no": 31,
            "character_asset_episode_eligible": 0,
            "_character_asset_collection_eligible": True,
        }
        summary_builder = AsyncMock(return_value=(31, True, {"used_llm": True}))
        signal_builder = AsyncMock()
        scene_builder = AsyncMock()
        rp_builder = AsyncMock()
        patchers = [
            patch.object(module, "OPENROUTER_API_KEY", ""),
            patch.object(module.settings, "ANTHROPIC_API_KEY", ""),
            patch.object(module, "db_connect", return_value=conn),
            patch.object(module, "work_cursor", fake_work_cursor),
            patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())),
            patch.object(module, "touch_product_context_build_attempt"),
            patch.object(module, "assert_storyctx_apply_providers_ready", AsyncMock()),
            patch.object(module, "fetch_total_episode_count", return_value=31),
            patch.object(module, "fetch_active_character_inventory_map", return_value={}),
            patch.object(module, "fetch_active_relation_inventory_by_relation_key_map", return_value={}),
            patch.object(module, "fetch_active_summary_state_map", return_value={}),
            patch.object(module, "fetch_active_summary_rows_for_episode_nos", return_value=[episode_summary_row]),
            patch.object(module, "resolve_source_payload", AsyncMock(return_value={"html_content": "본문", "source_type": "db"})),
            patch.object(module, "normalize_episode_html", return_value="정규화 본문"),
            patch.object(module, "build_chunks", return_value=[{"chunk_text": "정규화 본문"}]),
            patch.object(module, "fetch_existing_doc", return_value=None),
            patch.object(module, "insert_doc_and_chunks"),
            patch.object(module, "insert_episode_summary", summary_builder),
            patch.object(module, "build_episode_character_signals_summaries_nonblocking", signal_builder),
            patch.object(module, "build_episode_scene_extraction_summaries_nonblocking", scene_builder),
            patch.object(module, "build_rp_summaries_delta", rp_builder),
            patch.object(module, "build_compound_summaries_delta", return_value={"range": (1, 0), "product": (1, 0)}),
            patch.object(module, "refresh_product_context_status", return_value={"product_id": 787, "context_status": "ready"}),
            patch.object(module, "attach_character_chat_asset_readiness_to_status_row", side_effect=lambda _cur, status: status),
        ]

        with ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            results = await module.build_context_rows_delta(
                rows=[row],
                args=SimpleNamespace(
                    apply=True,
                    verbose=False,
                    use_epub_fallback=False,
                    refresh_rp=False,
                ),
            )

        summary_builder.assert_awaited_once()
        signal_builder.assert_not_awaited()
        scene_builder.assert_not_awaited()
        rp_builder.assert_not_awaited()
        self.assertEqual(results["inserted_summaries"], 1)
        self.assertEqual(results["inserted_episode_character_signals"], 0)
        self.assertEqual(results["products"][0]["context_status"], "ready")

    async def test_delta_signal_provider_failure_keeps_ready_product_and_lkg(self):
        module = load_module()
        conn = FakeConnection()
        episode_summary_row = {
            "summary_id": 11,
            "scope_key": "episode:101",
            "episode_from": 16,
            "source_hash": "summary-hash",
            "summary_text": "[16화] 요약",
        }
        row = {
            "product_id": 1105,
            "title": "테스트 작품",
            "episode_id": 101,
            "episode_no": 16,
            "_character_asset_collection_eligible": True,
        }
        signal_builder = AsyncMock(return_value=(0, 0, False))
        resolution_builder = AsyncMock()
        inventory_builder = MagicMock()
        rp_builder = AsyncMock()
        invariants = MagicMock()
        mark_failed = MagicMock()
        patchers = [
            patch.object(module, "OPENROUTER_API_KEY", ""),
            patch.object(module.settings, "ANTHROPIC_API_KEY", ""),
            patch.object(module, "db_connect", return_value=conn),
            patch.object(module, "work_cursor", fake_work_cursor),
            patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())),
            patch.object(module, "touch_product_context_build_attempt"),
            patch.object(module, "assert_storyctx_apply_providers_ready", AsyncMock()),
            patch.object(module, "fetch_total_episode_count", return_value=16),
            patch.object(module, "fetch_active_character_inventory_map", return_value={}),
            patch.object(module, "fetch_active_relation_inventory_by_relation_key_map", return_value={}),
            patch.object(module, "fetch_active_summary_state_map", return_value={}),
            patch.object(module, "fetch_active_summary_rows_for_episode_nos", return_value=[episode_summary_row]),
            patch.object(module, "resolve_source_payload", AsyncMock(return_value={"html_content": "본문", "source_type": "db"})),
            patch.object(module, "normalize_episode_html", return_value="정규화 본문"),
            patch.object(module, "build_chunks", return_value=[{"chunk_text": "정규화 본문"}]),
            patch.object(module, "fetch_existing_doc", return_value=None),
            patch.object(module, "insert_doc_and_chunks"),
            patch.object(module, "insert_episode_summary", AsyncMock(return_value=(11, True, {"used_llm": True}))),
            patch.object(module, "build_episode_character_signals_summaries_nonblocking", signal_builder),
            patch.object(module, "build_compound_summaries_delta", return_value={"range": (1, 0), "product": (1, 0)}),
            patch.object(module, "build_work_protagonist_resolution_for_inventory_v3", resolution_builder),
            patch.object(module, "build_character_inventory_v3_summaries", inventory_builder),
            patch.object(module, "build_rp_summaries_delta", rp_builder),
            patch.object(module, "assert_story_agent_foundation_invariants", invariants),
            patch.object(
                module,
                "refresh_product_context_status",
                return_value={
                    "product_id": 1105,
                    "context_status": "ready",
                    "total_episode_count": 16,
                    "ready_episode_count": 15,
                },
            ),
            patch.object(module, "attach_character_chat_asset_readiness_to_status_row", side_effect=lambda _cur, status: status),
            patch.object(module, "mark_product_context_failed", mark_failed),
        ]

        with ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            results = await module.build_context_rows_delta(
                rows=[row],
                args=SimpleNamespace(
                    apply=True,
                    verbose=False,
                    use_epub_fallback=False,
                    refresh_rp=False,
                ),
            )

        signal_builder.assert_awaited_once()
        resolution_builder.assert_not_awaited()
        inventory_builder.assert_not_called()
        rp_builder.assert_not_awaited()
        invariants.assert_not_called()
        mark_failed.assert_not_called()
        self.assertEqual(results["inserted_summaries"], 1)
        self.assertEqual(results["inserted_range_summaries"], 1)
        self.assertEqual(results["products"][0]["context_status"], "ready")

    async def test_delta_stale_identity_review_keeps_foundation_and_lkg(self):
        module = load_module()
        conn = FakeConnection()
        episode_summary_row = {
            "summary_id": 11,
            "scope_key": "episode:101",
            "episode_from": 16,
            "source_hash": "summary-hash",
            "summary_text": "[16화] 요약",
        }
        row = {
            "product_id": 1149,
            "title": "테스트 작품",
            "episode_id": 101,
            "episode_no": 16,
            "_character_asset_collection_eligible": True,
        }
        stale_error = module.CharacterIdentityReviewStaleError(
            "stale character identity review observations: confirm-main count=1",
            product_id=1149,
            operation_id="confirm-main",
            reason_code="missing_observations",
        )
        summary_builder = AsyncMock(return_value=(11, True, {"used_llm": True}))
        signal_builder = AsyncMock(return_value=(1, 0, True))
        scene_builder = AsyncMock()
        rp_builder = AsyncMock()
        mark_failed = MagicMock()
        patchers = [
            patch.object(module, "OPENROUTER_API_KEY", ""),
            patch.object(module.settings, "ANTHROPIC_API_KEY", ""),
            patch.object(module, "db_connect", return_value=conn),
            patch.object(module, "work_cursor", fake_work_cursor),
            patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())),
            patch.object(module, "touch_product_context_build_attempt"),
            patch.object(module, "assert_storyctx_apply_providers_ready", AsyncMock()),
            patch.object(module, "fetch_total_episode_count", return_value=16),
            patch.object(module, "fetch_active_character_inventory_map", return_value={}),
            patch.object(module, "fetch_active_relation_inventory_by_relation_key_map", return_value={}),
            patch.object(module, "fetch_active_summary_state_map", return_value={}),
            patch.object(module, "fetch_active_summary_rows_for_episode_nos", return_value=[episode_summary_row]),
            patch.object(module, "resolve_source_payload", AsyncMock(return_value={"html_content": "본문", "source_type": "db"})),
            patch.object(module, "normalize_episode_html", return_value="정규화 본문"),
            patch.object(module, "build_chunks", return_value=[{"chunk_text": "정규화 본문"}]),
            patch.object(module, "fetch_existing_doc", return_value=None),
            patch.object(module, "insert_doc_and_chunks"),
            patch.object(module, "insert_episode_summary", summary_builder),
            patch.object(module, "build_episode_character_signals_summaries_nonblocking", signal_builder),
            patch.object(module, "fetch_active_summary_rows", return_value=[episode_summary_row]),
            patch.object(module, "fetch_active_character_asset_summary_rows", return_value=[episode_summary_row]),
            patch.object(module, "build_work_protagonist_resolution_for_inventory_v3", AsyncMock(return_value={})),
            patch.object(module, "build_compound_summaries_delta", return_value={"range": (1, 0), "product": (1, 0)}),
            patch.object(module, "build_character_inventory_summaries_delta", return_value={"inserted_count": 1, "reused_count": 0}),
            patch.object(module, "build_character_inventory_v3_summaries", side_effect=stale_error),
            patch.object(module, "build_episode_scene_extraction_summaries_nonblocking", scene_builder),
            patch.object(module, "build_rp_summaries_delta", rp_builder),
            patch.object(
                module,
                "refresh_product_context_status",
                return_value={
                    "product_id": 1149,
                    "context_status": "ready",
                    "total_episode_count": 16,
                    "ready_episode_count": 16,
                },
            ),
            patch.object(module, "attach_character_chat_asset_readiness_to_status_row", side_effect=lambda _cur, status: status),
            patch.object(module, "mark_product_context_failed", mark_failed),
        ]

        with ExitStack() as stack:
            for patcher in patchers:
                stack.enter_context(patcher)
            results = await module.build_context_rows_delta(
                rows=[row],
                args=SimpleNamespace(
                    apply=True,
                    verbose=False,
                    use_epub_fallback=False,
                    refresh_rp=False,
                ),
            )

        summary_builder.assert_awaited_once()
        signal_builder.assert_awaited_once()
        scene_builder.assert_not_awaited()
        rp_builder.assert_not_awaited()
        mark_failed.assert_not_called()
        self.assertEqual(conn.rollback_count, 1)
        self.assertEqual(results["inserted_summaries"], 1)
        self.assertEqual(results["inserted_episode_character_signals"], 0)
        self.assertEqual(results["review_required"], 1)
        self.assertEqual(results["products"][0]["context_status"], "review_required")
        self.assertEqual(results["products"][0]["persisted_context_status"], "ready")
        self.assertEqual(
            results["products"][0]["review_reason_codes"],
            ["missing_observations"],
        )
        self.assertEqual(
            module.build_delta_exit_code(results, apply=True),
            module.STORYCTX_REVIEW_REQUIRED_EXIT_CODE,
        )

    async def test_episode_scene_extraction_skips_when_openrouter_key_missing(self):
        module = load_module()
        conn = FakeConnection()
        request_mock = AsyncMock(return_value={})

        with patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_episode_scene_extraction_payload", request_mock):
            counts = await module.build_episode_scene_extraction_summaries(
                conn,
                product_id=687,
                product_title="테스트 작품",
                episode_rows=[
                    {
                        "summary_id": 1,
                        "scope_key": "episode:1001",
                        "episode_from": 1,
                        "source_hash": "hash",
                        "summary_text": "[1화] 테스트",
                    }
                ],
                episode_texts_by_no={1: "야율천은 문 앞에 섰다."},
                summary_client=object(),
                canonical_character_packet={"characters": [{"display_name": "야율천"}]},
            )

        self.assertEqual(counts, (0, 0))
        request_mock.assert_not_awaited()
        self.assertEqual(conn.commit_count, 0)

    async def test_scene_repair_keeps_old_when_regeneration_drops_existing_character(self):
        module = load_module()
        conn = FakeConnection()
        required_scope_key = "protagonist:named:데시"
        other_scope_key = "supporting:named:오리온"
        existing_payload = {
            "episode_no": 1,
            "status": "ok",
            "scene_count": 1,
            "scenes": [
                {
                    "scene_gist": "오리온이 문을 연다.",
                    "participants": [{"scope_key": other_scope_key}],
                    "action_ownership": [],
                }
            ],
        }
        regenerated_payload = {
            **existing_payload,
            "scenes": [
                {
                    "scene_gist": "데시가 문을 연다.",
                    "participants": [{"scope_key": required_scope_key}],
                    "action_ownership": [],
                }
            ],
        }
        request_mock = AsyncMock(return_value=regenerated_payload)
        upsert_mock = MagicMock()

        with patch.object(module, "OPENROUTER_API_KEY", "test-key"), \
             patch.object(module, "EPISODE_SCENE_EXTRACTION_OPENROUTER_MODEL", "test-model"), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(
                 module,
                 "fetch_existing_summary",
                 return_value=None,
             ), \
             patch.object(
                 module,
                 "fetch_active_summary_by_scope",
                 return_value={
                     "summary_id": 9,
                     "source_hash": "previous-source-hash",
                     "summary_text": json.dumps(existing_payload, ensure_ascii=False),
                 },
             ), \
             patch.object(module, "request_episode_scene_extraction_payload", request_mock), \
             patch.object(module, "upsert_summary", upsert_mock):
            counts = await module.build_episode_scene_extraction_summaries(
                conn,
                product_id=687,
                product_title="테스트 작품",
                episode_rows=[
                    {
                        "summary_id": 1,
                        "scope_key": "episode:1001",
                        "episode_from": 1,
                        "source_hash": "hash",
                        "summary_text": "[1화] 테스트",
                    }
                ],
                episode_texts_by_no={1: "데시와 오리온은 문 앞에 섰다."},
                summary_client=object(),
                canonical_character_packet={
                    "characters": [{"scope_key": required_scope_key, "display_name": "데시"}]
                },
                required_scope_keys_by_episode_no={1: {required_scope_key}},
                cleanup_missing_scopes=False,
            )

        self.assertEqual(counts, (0, 0))
        request_mock.assert_awaited_once()
        upsert_mock.assert_not_called()

    async def test_scene_repair_strict_mode_raises_unexpected_request_error(self):
        module = load_module()
        conn = FakeConnection()

        with patch.object(module, "OPENROUTER_API_KEY", "test-key"), \
             patch.object(module, "EPISODE_SCENE_EXTRACTION_OPENROUTER_MODEL", "test-model"), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "fetch_existing_summary", return_value=None), \
             patch.object(module, "fetch_active_summary_by_scope", return_value=None), \
             patch.object(
                 module,
                 "request_episode_scene_extraction_payload",
                 AsyncMock(side_effect=TypeError("scene normalization bug")),
             ):
            with self.assertRaisesRegex(TypeError, "scene normalization bug"):
                await module.build_episode_scene_extraction_summaries(
                    conn,
                    product_id=687,
                    product_title="테스트 작품",
                    episode_rows=[
                        {
                            "summary_id": 1,
                            "scope_key": "episode:1001",
                            "episode_from": 1,
                            "source_hash": "hash",
                            "summary_text": "[1화] 테스트",
                        }
                    ],
                    episode_texts_by_no={1: "데시가 문을 연다."},
                    summary_client=object(),
                    canonical_character_packet={
                        "characters": [
                            {"scope_key": "character:main", "display_name": "데시"}
                        ]
                    },
                    cleanup_missing_scopes=False,
                    raise_unexpected_errors=True,
                )

    async def test_scene_repair_strict_mode_propagates_unexpected_value_error(self):
        module = load_module()
        conn = FakeConnection()

        with patch.object(module, "OPENROUTER_API_KEY", "test-key"), \
             patch.object(module, "EPISODE_SCENE_EXTRACTION_OPENROUTER_MODEL", "test-model"), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "fetch_existing_summary", return_value=None), \
             patch.object(module, "fetch_active_summary_by_scope", return_value=None), \
             patch.object(
                 module,
                 "request_episode_scene_extraction_openrouter_json_payload",
                 AsyncMock(side_effect=ValueError("unexpected scene invariant failure")),
             ):
            with self.assertRaisesRegex(ValueError, "unexpected scene invariant failure"):
                await module.build_episode_scene_extraction_summaries(
                    conn,
                    product_id=687,
                    product_title="테스트 작품",
                    episode_rows=[
                        {
                            "summary_id": 1,
                            "scope_key": "episode:1001",
                            "episode_from": 1,
                            "source_hash": "hash",
                            "summary_text": "[1화] 테스트",
                        }
                    ],
                    episode_texts_by_no={1: "데시가 문을 연다."},
                    summary_client=object(),
                    canonical_character_packet={
                        "characters": [
                            {"scope_key": "character:main", "display_name": "데시"}
                        ]
                    },
                    cleanup_missing_scopes=False,
                    raise_unexpected_errors=True,
                )

    def test_inventory_v3_does_not_link_previous_first_person_by_episode_order(self):
        module = load_module()
        signal_rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:롤랑지그문트",
                        display_name="롤랑 지그문트",
                        aliases=["롤랑 지그문트"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        scene_weight="high",
                        voice_mode="narration_only",
                    ),
                    signal_character(
                        character_key="named:니드호그",
                        display_name="니드호그",
                        aliases=["니드호그"],
                        role_in_episode="obstacle",
                        scene_weight="high",
                        voice_mode="dialogue",
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="니드호그",
                        aliases=["니드호그"],
                        is_protagonist=True,
                        is_first_person=True,
                        role_in_episode="lead",
                        scene_weight="high",
                        voice_mode="monologue",
                    ),
                ],
            ),
            *[
                signal_row(
                    summary_id,
                    episode_no,
                    [
                        signal_character(
                            character_key="protagonist:named:갤러해드지그문트",
                            display_name="갤러해드 지그문트",
                            aliases=["갤러해드 지그문트", "갤러해드"],
                            is_protagonist=True,
                            role_in_episode="lead",
                            scene_weight="high",
                            voice_mode="dialogue",
                        )
                    ],
                )
                for summary_id, episode_no in [(3, 3), (4, 4), (5, 5)]
            ],
        ]
        resolution = {
            "schema_version": module.WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
            "decision": "RESOLVED",
            "work_protagonist_key": "character:갤러해드지그문트",
            "work_protagonist_keys": ["character:갤러해드지그문트"],
            "confidence": "high",
            "reason_code": "persona_rename_same_person",
            "rationale": "3화 이후 현재 세계 이름이 작품 전체 행동 중심이다.",
            "rejected": [{"key": "character:롤랑지그문트", "reason": "프롤로그 전투 인물"}],
            "safety_flags": {
                "requires_identity_merge": False,
                "selected_candidate_eligible": True,
                "multiple_plausible_main_candidates": False,
            },
        }

        rows = module.aggregate_character_inventory_v3_rows(
            signal_rows,
            protagonist_resolution=resolution,
        )
        rows_by_key = {row["canonical_character_key"]: row for row in rows}
        main = rows_by_key["character:갤러해드지그문트"]
        previous = rows_by_key["character:니드호그"]
        prologue_actor = rows_by_key["character:롤랑지그문트"]

        self.assertEqual(main["work_role"], "main_protagonist")
        self.assertNotEqual(previous["work_role"], "main_protagonist")
        for row in (main, previous, prologue_actor):
            self.assertNotIn("identity_group_key", row)
            self.assertNotIn("identity_linked_to_scope_key", row)
            self.assertNotIn(
                "identity_group_key",
                module.build_character_inventory_v3_hash_payload(row),
            )

    def test_character_chat_internal_prompt_system_prefers_new_side_event(self):
        module = load_module()
        prompt = module.CHARACTER_CHAT_INTERNAL_PROMPT_SYSTEM

        self.assertIn("[원작 기반 새 사건 운용]", prompt)
        self.assertIn("런타임의 하드 렌더링 가드가 이 내부 프롬프트보다 우선한다", prompt)
        self.assertIn("원작 플롯은 앵커로만 쓰고", prompt)
        self.assertIn("원작에서 파생된 새 사이드 사건/새 변수/새 단서", prompt)
        self.assertIn("새 사건의 비중을 원작 요약보다 높게", prompt)
        self.assertIn("원작은 대본이 아니라 제약 조건", prompt)
        self.assertIn("장면 압력, 협력 요청, 자연스러운 1~2개 행동 방향", prompt)
        self.assertIn("관계 반응을 최소 하나 포함", prompt)
        self.assertIn("이미 장면에 엮인 비네임드 조력자/동행자/관계자", prompt)
        self.assertIn("사용자의 정체를 심문하는 반복 전개", prompt)
        self.assertIn("정체 심문을 사건 엔진으로 쓰지 마라", prompt)
        self.assertIn("현재 사건의 목적, 위기, 행동 hook", prompt)
        self.assertIn("원작 기존 네임드/짐승/환자/포로로 확정하지 마라", prompt)
        self.assertIn("[사용자 agency]", prompt)
        self.assertIn("사용자가 직전 입력에서 직접 밝힌 행동/말/상태만 이어받는다", prompt)
        self.assertIn("사용자가 직전 입력에서 직접 묘사한 행동과 상태는 이어받을 수 있지만", prompt)
        self.assertIn("캐릭터 자신의 접근/시선/접촉은 캐릭터 행동으로 쓸 수 있으나", prompt)
        self.assertIn("협력 요청은 대사 안에서 선택 가능하게 남기고", prompt)
        self.assertIn("구체적인 금지 표현 목록을 만들지 마라", prompt)
        self.assertIn("사용자에 관한 서술마다 직전 입력의 근거가 있는지 확인", prompt)
        self.assertNotIn("곁에 선 이", prompt)
        self.assertNotIn("네가 가리킨", prompt)
        self.assertNotIn("잡아채", prompt)
        self.assertNotIn("첫 대사의 압박/질문/명령 hook", prompt)

    async def test_character_chat_internal_prompt_uses_dedicated_timeout(self):
        module = load_module()
        client = FakeOpenRouterClient(
            {"internal_prompt": "[핵심 정체성] 이시혁은 상황을 직접 판단하고 움직인다."}
        )

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"):
            payload = await module.request_character_chat_internal_prompt_payload(
                client,
                target={"character_key": "character:이시혁", "display_name": "이시혁", "aliases": ["이시혁"]},
                profile_payload={"display_name": "이시혁", "speech_style": {}, "personality_core": []},
                example_payload={"examples": []},
                dialogue_items=[],
                summary_context_lines=[],
            )

        self.assertIsNotNone(payload)
        self.assertGreater(
            module.CHARACTER_CHAT_INTERNAL_PROMPT_TIMEOUT_SECONDS,
            module.RP_OPENROUTER_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            client.calls[0]["timeout"],
            module.CHARACTER_CHAT_INTERNAL_PROMPT_TIMEOUT_SECONDS,
        )

        default_client = FakeOpenRouterClient({"ok": True})
        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"):
            await module.request_rp_openrouter_json_payload(
                default_client,
                system_prompt="system",
                user_prompt="user",
                max_tokens=100,
                title="test",
            )
        self.assertEqual(default_client.calls[0]["timeout"], module.RP_OPENROUTER_TIMEOUT_SECONDS)

    async def test_existing_episode_character_signal_reuses_without_llm_call(self):
        module = load_module()
        conn = FakeConnection()
        row = {
            "summary_id": 777,
            "scope_key": "episode:1001",
            "episode_from": 4,
            "source_hash": "episode-summary-hash",
            "summary_text": "[1화] 첫 만남\n주인공이 사건에 휘말린다.\n핵심: 주인공, 사건, 만남, 갈등, 선택, 후킹",
        }
        request_mock = AsyncMock(
            return_value={
                "mentioned_characters": [
                    {
                        "display_name": "주인공",
                        "is_protagonist": True,
                        "is_first_person": False,
                    }
                ],
                "cliffhanger_hooks": ["다음 사건의 단서가 남는다."],
            }
        )

        with patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "fetch_existing_summary", return_value={"summary_id": 123, "version_no": 1, "is_active": "Y"}), \
             patch.object(module, "activate_existing_summary") as activate_existing, \
             patch.object(module, "request_episode_character_signals_payload", request_mock):
            inserted, reused = await module.build_episode_character_signals_summaries(
                conn,
                product_id=687,
                episode_rows=[row],
                summary_client=object(),
                cleanup_missing_scopes=False,
            )

        self.assertEqual(inserted, 0)
        self.assertEqual(reused, 1)
        request_mock.assert_not_awaited()
        activate_existing.assert_called_once_with(ANY, 123, 687, "episode_character_signals", "episode:1001")
        self.assertEqual(conn.commit_count, 1)

    async def test_opening_character_signal_uses_raw_text_and_invalidates_summary_only_cache(self):
        module = load_module()
        conn = FakeConnection()
        row = {
            "summary_id": 777,
            "scope_key": "episode:1001",
            "episode_from": 1,
            "source_hash": "episode-summary-hash",
            "summary_text": "[1화] 요약에서는 인물 이름이 미정으로 축약됐다.",
        }
        opening_text = "이름: 미정(추종자)\n내 이름은 추종자다."
        old_source_hash = module.build_compound_summary_source_hash(
            module.EPISODE_CHARACTER_SIGNALS_FORMAT_VERSION,
            [
                "777:episode-summary-hash",
                module.build_rp_reasoning_signature(),
            ],
        )
        request_mock = AsyncMock(
            return_value={
                "mentioned_characters": [
                    signal_character(
                        character_key="ignored",
                        display_name="추종자",
                        real_names=["추종자"],
                        is_work_protagonist=True,
                    )
                ]
            }
        )

        def fetch_existing(*, source_hash, **kwargs):
            return {"summary_id": 123} if source_hash == old_source_hash else None

        with patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "is_episode_character_signals_provider_available", return_value=True), \
             patch.object(module, "fetch_existing_summary", side_effect=fetch_existing), \
             patch.object(module, "request_episode_character_signals_payload", request_mock), \
             patch.object(module, "upsert_summary", return_value=(456, True)):
            inserted, reused = await module.build_episode_character_signals_summaries(
                conn,
                product_id=687,
                episode_rows=[row],
                episode_texts_by_no={1: opening_text},
                summary_client=object(),
                cleanup_missing_scopes=False,
            )

        self.assertEqual((inserted, reused), (1, 0))
        request_mock.assert_awaited_once()
        self.assertEqual(
            request_mock.await_args.kwargs["opening_text"],
            opening_text,
        )

    def test_possessed_work_protagonist_keeps_distinct_named_persona(self):
        module = load_module()

        payload = module.normalize_episode_character_signals_payload(
            {
                "mentioned_characters": [
                    signal_character(
                        character_key="ignored",
                        display_name="추종자",
                        aliases=["추종자"],
                        persona_names=["추종자"],
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        identity_claims=[
                            {
                                "target_label": "신미아의 동생",
                                "claim_type": "possessed_as",
                                "evidence": "추종자가 신미아의 동생 몸에 빙의했다",
                            }
                        ],
                    )
                ]
            },
            episode_no=1,
        )

        self.assertEqual(len(payload["mentioned_characters"]), 1)
        protagonist = payload["mentioned_characters"][0]
        self.assertEqual(protagonist["character_key"], "protagonist:named:추종자")
        self.assertEqual(protagonist["display_name"], "추종자")
        self.assertEqual(protagonist["entity_kind"], "person")

        inventory = module.aggregate_character_inventory_v3_rows(
            [signal_row(1, 1, payload["mentioned_characters"])]
        )
        inventory_protagonist = next(
            row
            for row in inventory
            if "protagonist:named:추종자"
            in list(row.get("source_character_keys") or [])
        )
        self.assertEqual(inventory_protagonist["display_name"], "추종자")

    async def test_episode_character_signal_can_stage_reuse_without_child_commit(self):
        module = load_module()
        conn = FakeConnection()
        processed_scope_keys = set()
        row = {
            "summary_id": 777,
            "scope_key": "episode:1001",
            "episode_from": 4,
            "source_hash": "episode-summary-hash",
            "summary_text": "[4화] 현재 요약",
        }

        with patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "fetch_existing_summary", return_value={"summary_id": 123}), \
             patch.object(module, "activate_existing_summary"):
            counts = await module.build_episode_character_signals_summaries(
                conn,
                product_id=687,
                episode_rows=[row],
                summary_client=object(),
                cleanup_missing_scopes=False,
                processed_scope_keys=processed_scope_keys,
                commit_changes=False,
            )

        self.assertEqual(counts, (0, 1))
        self.assertEqual(processed_scope_keys, {"episode:1001"})
        self.assertEqual(conn.commit_count, 0)

    async def test_episode_character_signal_failure_preserves_last_good_scope_and_stops_product(self):
        module = load_module()
        conn = FakeConnection()
        rows = [{
            "summary_id": 777,
            "scope_key": "episode:1001",
            "episode_from": 1,
            "source_hash": "episode-summary-hash-new",
            "summary_text": "[1화] 바뀐 회차\n주인공 후보가 바뀐다.\n핵심: 주인공, 후보, 변경",
        }, {
            "summary_id": 778,
            "scope_key": "episode:1002",
            "episode_from": 2,
            "source_hash": "episode-summary-hash-next",
            "summary_text": "[2화] 다음 회차\n주인공이 앞으로 나아간다.",
        }]
        request_mock = AsyncMock(side_effect=module.RequestError("upstream timeout"))

        with patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL", "deepseek/deepseek-v4-pro"), \
             patch.object(module, "RP_REASONING_MODEL", ""), \
             patch.object(module, "fetch_existing_summary", return_value=None), \
             patch.object(module, "request_episode_character_signals_payload", request_mock), \
             patch.object(module, "deactivate_active_scope", return_value=1) as deactivate_scope:
            with self.assertRaises(module.RequestError):
                await module.build_episode_character_signals_summaries(
                    conn,
                    product_id=687,
                    episode_rows=rows,
                    summary_client=object(),
                    cleanup_missing_scopes=False,
                )

        request_mock.assert_awaited_once()
        deactivate_scope.assert_not_called()
        self.assertEqual(conn.commit_count, 0)

    async def test_episode_character_signals_429_honors_retry_after_before_retry(self):
        module = load_module()
        client = FakeRateLimitedOpenRouterClient(
            {
                "episode_no": 1,
                "mentioned_characters": [],
                "cliffhanger_hooks": [],
            },
            retry_after="7",
        )

        with patch.object(module.settings, "ANTHROPIC_API_KEY", ""), \
             patch.object(module, "RP_REASONING_MODEL", ""), \
             patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL", "deepseek/deepseek-v4-pro"), \
             patch.object(module.asyncio, "sleep", AsyncMock()) as sleep_mock:
            payload = await module.request_episode_character_signals_payload(
                client,
                row={"episode_no": 1, "title": "테스트", "episode_title": "1화"},
                summary_text="[1화] 테스트\n주인공이 움직인다.",
            )

        self.assertEqual(payload["episode_no"], 1)
        self.assertEqual(len(client.calls), 2)
        sleep_mock.assert_awaited_once_with(7.0)

    def test_openrouter_retry_delay_is_bounded_and_rate_limit_only(self):
        module = load_module()
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")

        def status_error(status_code: int, retry_after: str | None):
            headers = {"Retry-After": retry_after} if retry_after is not None else {}
            response = httpx.Response(status_code, headers=headers, request=request)
            return httpx.HTTPStatusError("provider error", request=request, response=response)

        self.assertEqual(module.get_openrouter_retry_delay_seconds(status_error(429, "bad")), 10.0)
        self.assertEqual(module.get_openrouter_retry_delay_seconds(status_error(429, "120")), 60.0)
        self.assertEqual(module.get_openrouter_retry_delay_seconds(status_error(503, "0")), 1.0)
        self.assertIsNone(module.get_openrouter_retry_delay_seconds(status_error(400, "10")))

    async def test_episode_character_signals_keep_old_when_provider_unavailable(self):
        module = load_module()
        conn = FakeConnection()
        row = {
            "summary_id": 777,
            "scope_key": "episode:1001",
            "episode_from": 1,
            "source_hash": "episode-summary-hash-new",
            "summary_text": "[1화] 바뀐 회차\n주인공 후보가 바뀐다.",
        }
        request_mock = AsyncMock(return_value={"mentioned_characters": []})

        with patch.object(module.settings, "ANTHROPIC_API_KEY", ""), \
             patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module, "EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL", ""), \
             patch.object(module, "RP_REASONING_MODEL", ""), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "fetch_existing_summary", return_value=None), \
             patch.object(module, "request_episode_character_signals_payload", request_mock), \
             patch.object(module, "deactivate_active_scope") as deactivate_scope:
            inserted, reused = await module.build_episode_character_signals_summaries(
                conn,
                product_id=687,
                episode_rows=[row],
                summary_client=object(),
                cleanup_missing_scopes=False,
            )

        self.assertEqual((inserted, reused), (0, 0))
        request_mock.assert_not_awaited()
        deactivate_scope.assert_not_called()
        self.assertEqual(conn.commit_count, 0)

    async def test_character_signal_expected_provider_error_is_deferred_without_product_failure(self):
        module = load_module()
        conn = MagicMock()
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        expected_error = httpx.HTTPStatusError(
            "payment required",
            request=request,
            response=httpx.Response(402, request=request),
        )

        with patch.object(
            module,
            "build_episode_character_signals_summaries",
            AsyncMock(side_effect=expected_error),
        ):
            inserted, reused, complete = await module.build_episode_character_signals_summaries_nonblocking(
                conn=conn,
                product_id=687,
                episode_rows=[{"episode_from": 1}],
                summary_client=object(),
                cleanup_missing_scopes=False,
            )

        self.assertEqual((inserted, reused, complete), (0, 0, False))
        conn.rollback.assert_called_once_with()

    async def test_character_signal_unexpected_error_still_fails_loudly(self):
        module = load_module()

        with patch.object(
            module,
            "build_episode_character_signals_summaries",
            AsyncMock(side_effect=RuntimeError("db write failed")),
        ):
            with self.assertRaisesRegex(RuntimeError, "db write failed"):
                await module.build_episode_character_signals_summaries_nonblocking(
                    conn=MagicMock(),
                    product_id=687,
                    episode_rows=[{"episode_from": 1}],
                    summary_client=object(),
                    cleanup_missing_scopes=False,
                )

    async def test_character_signal_auth_error_still_fails_loudly(self):
        module = load_module()
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        auth_error = httpx.HTTPStatusError(
            "unauthorized",
            request=request,
            response=httpx.Response(401, request=request),
        )

        with patch.object(
            module,
            "build_episode_character_signals_summaries",
            AsyncMock(side_effect=auth_error),
        ):
            with self.assertRaises(httpx.HTTPStatusError):
                await module.build_episode_character_signals_summaries_nonblocking(
                    conn=MagicMock(),
                    product_id=687,
                    episode_rows=[{"episode_from": 1}],
                    summary_client=object(),
                    cleanup_missing_scopes=False,
                )

    def test_rp_target_excludes_alias_owned_by_another_character(self):
        module = load_module()
        raphael_scope_key = "character:라파엘"
        andrei_scope_key = "character:안드레이카르마조프"
        inventory_map = {
            raphael_scope_key: {
                "canonical_character_key": raphael_scope_key,
                "display_name": "라파엘",
                "aliases": ["라파엘", "안드레이 카르마조프"],
                "is_protagonist": True,
                "is_first_person": True,
                "work_role": "main_protagonist",
            },
            andrei_scope_key: {
                "canonical_character_key": andrei_scope_key,
                "display_name": "안드레이 카르마조프",
                "aliases": ["안드레이 카르마조프", "안드레이"],
                "work_role": "major_character",
            },
        }

        target = module.build_inventory_rp_target(
            scope_key=raphael_scope_key,
            inventory_item=inventory_map[raphael_scope_key],
        )
        assert target is not None
        target = module.attach_competing_speaker_anchors(
            target,
            current_scope_key=raphael_scope_key,
            inventory_map=inventory_map,
        )

        self.assertNotIn("안드레이 카르마조프", target["aliases"])
        self.assertNotIn(
            "안드레이 카르마조프",
            target["collection_rules"]["speaker_anchors"],
        )
        self.assertIn(
            "안드레이 카르마조프",
            target["collection_rules"]["competing_speaker_anchors"],
        )
        self.assertIn("안드레이 카르마조프", inventory_map[raphael_scope_key]["aliases"])

    async def test_episode_character_signals_defaults_to_deepseek_direct(self):
        module = load_module()
        client = FakeOpenRouterClient(
            {
                "episode_no": 1,
                "mentioned_characters": [
                    {
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "is_first_person": False,
                        "entity_kind": "person",
                        "scene_weight": "high",
                        "role_in_episode": "lead",
                        "voice_mode": "dialogue",
                        "action_tags": ["질문"],
                        "affect_tags": ["경계"],
                        "relation_edges": [],
                        "identity_claims": [],
                    }
                ],
                "cliffhanger_hooks": ["다음 선택이 남는다."],
            }
        )

        with patch.object(module.settings, "ANTHROPIC_API_KEY", ""), \
             patch.object(module, "RP_REASONING_MODEL", ""), \
             patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"), \
             patch.object(module, "EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL", "deepseek/deepseek-v4-pro"):
            payload = await module.request_episode_character_signals_payload(
                client,
                row={"episode_no": 1, "title": "테스트", "episode_title": "1화"},
                summary_text="[1화] 테스트\n백이현이 경계하며 질문한다.\n핵심: 백이현, 경계, 질문, 선택, 사건, 단서",
            )

        self.assertEqual(payload["mentioned_characters"][0]["display_name"], "백이현")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(client.calls[0]["json"]["model"], "deepseek/deepseek-v4-pro")
        self.assertEqual(client.calls[0]["json"]["max_tokens"], module.EPISODE_CHARACTER_SIGNALS_MAX_OUTPUT_TOKENS)
        self.assertEqual(client.calls[0]["json"]["response_format"], {"type": "json_object"})
        call_messages = client.calls[0]["json"]["messages"]
        self.assertIn("JSON schema", call_messages[1]["content"])
        self.assertNotIn("라인 포맷", call_messages[1]["content"])
        self.assertEqual(client.calls[0]["headers"]["X-Title"], "LikeNovel Story Agent Episode Character Signals OpenRouter")

    async def test_episode_character_signals_uses_configured_openrouter_model(self):
        module = load_module()
        client = FakeOpenRouterClient(
            {
                "episode_no": 1,
                "mentioned_characters": [
                    {
                        "display_name": "야율천",
                        "aliases": ["야율천"],
                        "is_protagonist": True,
                        "is_first_person": False,
                        "entity_kind": "person",
                        "scene_weight": "high",
                        "role_in_episode": "lead",
                        "voice_mode": "dialogue",
                        "action_tags": ["판단"],
                        "affect_tags": ["침착"],
                        "relation_edges": [],
                        "identity_claims": [],
                    }
                ],
                "cliffhanger_hooks": ["다음 진료 판단이 남는다."],
            }
        )

        with patch.object(module.settings, "ANTHROPIC_API_KEY", ""), \
             patch.object(module, "RP_REASONING_MODEL", ""), \
             patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "RP_OPENROUTER_PROVIDER_ONLY", "deepinfra,together"), \
             patch.object(module, "DEEPSEEK_OPENROUTER_PROVIDER_ONLY", "together"):
            payload = await module.request_episode_character_signals_payload(
                client,
                row={"episode_no": 1, "title": "테스트", "episode_title": "1화"},
                summary_text="[1화] 테스트\n야율천이 침착하게 판단한다.\n핵심: 야율천, 판단, 진료, 선택, 사건, 단서",
            )

        self.assertEqual(payload["mentioned_characters"][0]["display_name"], "야율천")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(client.calls[0]["json"]["model"], "google/gemma-4-31b-it")
        self.assertEqual(
            client.calls[0]["json"]["provider"],
            {"only": ["together"], "order": ["together"], "allow_fallbacks": False},
        )
        self.assertEqual(client.calls[0]["headers"]["X-Title"], "LikeNovel Story Agent Episode Character Signals OpenRouter")

    async def test_episode_character_signals_openrouter_timeout_does_not_hang(self):
        module = load_module()
        client = FakeHangingOpenRouterClient()

        with patch.object(module.settings, "ANTHROPIC_API_KEY", ""), \
             patch.object(module, "RP_REASONING_MODEL", ""), \
             patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "EPISODE_CHARACTER_SIGNALS_OPENROUTER_TIMEOUT_SECONDS", 0.01):
            with self.assertRaises(module.EpisodeCharacterSignalsParseError):
                await module.request_episode_character_signals_payload(
                    client,
                    row={"episode_no": 1, "title": "테스트", "episode_title": "1화"},
                    summary_text="[1화] 테스트\n야율천이 침착하게 판단한다.",
                )

        self.assertEqual(len(client.calls), 2)

    async def test_episode_scene_extraction_openrouter_timeout_does_not_hang(self):
        module = load_module()
        client = FakeHangingOpenRouterClient()

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "EPISODE_SCENE_EXTRACTION_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "DEEPSEEK_OPENROUTER_PROVIDER_ONLY", "together"), \
             patch.object(module, "EPISODE_SCENE_EXTRACTION_OPENROUTER_TIMEOUT_SECONDS", 0.01):
            payload = await module.request_episode_scene_extraction_payload(
                client,
                product_title="테스트 작품",
                episode_no=1,
                episode_title="1화",
                normalized_text="야율천은 의방 문을 열고 약재 냄새를 확인했다.",
                canonical_character_packet={
                    "characters": [{"scope_key": "character:야율천", "display_name": "야율천"}]
                },
            )

        self.assertEqual(payload, {})
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0]["json"]["model"], "google/gemma-4-31b-it")
        self.assertEqual(
            client.calls[0]["json"]["provider"],
            {"only": ["together"], "order": ["together"], "allow_fallbacks": False},
        )

    async def test_episode_scene_extraction_429_honors_retry_after_before_retry(self):
        module = load_module()
        normalized_text = '루벤은 검을 들었다. "문을 열어."'
        client = FakeRateLimitedOpenRouterClient(
            {
                "episode_no": 1,
                "scenes": [
                    {
                        "scene_id": "scene_1",
                        "summary": "루벤이 문을 연다.",
                        "characters": ["character:루벤"],
                        "opening_anchor": "루벤은 검을 들었다.",
                    }
                ],
            },
            retry_after="5",
        )

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "EPISODE_SCENE_EXTRACTION_OPENROUTER_MODEL", "deepseek/deepseek-v4-pro"), \
             patch.object(module.asyncio, "sleep", AsyncMock()) as sleep_mock:
            await module.request_episode_scene_extraction_payload(
                client,
                product_title="테스트 작품",
                episode_no=1,
                episode_title="1화",
                normalized_text=normalized_text,
                canonical_character_packet={
                    "characters": [{"scope_key": "character:루벤", "display_name": "루벤"}]
                },
            )

        self.assertEqual(len(client.calls), 2)
        sleep_mock.assert_awaited_once_with(5.0)

    def test_episode_scene_extraction_defaults_to_compact_deepseek_request(self):
        with patch.dict(
            os.environ,
            {
                "STORY_AGENT_SCENE_EXTRACTION_OPENROUTER_MODEL": "",
                "STORY_AGENT_SCENE_EXTRACTION_MAX_OUTPUT_TOKENS": "5000",
            },
        ):
            module = load_module()

        self.assertEqual(module.EPISODE_SCENE_EXTRACTION_OPENROUTER_MODEL, "deepseek/deepseek-v4-pro")
        self.assertEqual(module.EPISODE_SCENE_EXTRACTION_MAX_OUTPUT_TOKENS, 5000)
        self.assertEqual(module.EPISODE_SCENE_EXTRACTION_OPENROUTER_TIMEOUT_SECONDS, 120.0)
        self.assertIn("핵심 장면 2~3개", module.EPISODE_SCENE_EXTRACTION_SYSTEM)

    def test_episode_character_signals_source_hash_uses_primary_model(self):
        module = load_module()

        with patch.object(module, "RP_REASONING_MODEL", ""), \
             patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL", "deepseek/deepseek-v4-pro"):
            self.assertEqual(
                module.build_rp_reasoning_signature(),
                "openrouter|deepseek/deepseek-v4-pro|reasoning:none",
            )

        with patch.object(module, "RP_REASONING_MODEL", ""), \
             patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module, "EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL", ""):
            self.assertEqual(module.build_rp_reasoning_signature(), "none")

        with patch.object(module, "RP_REASONING_MODEL", ""), \
             patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "RP_OPENROUTER_PROVIDER_ONLY", "deepinfra,together"):
            self.assertEqual(
                module.build_rp_reasoning_signature(),
                "openrouter|google/gemma-4-31b-it|reasoning:none",
            )

        with patch.object(module, "RP_REASONING_MODEL", "claude-sonnet-4-6"), \
             patch.object(module, "RP_REASONING_EFFORT", "medium"), \
             patch.object(module, "RP_REASONING_THINKING_DISPLAY", "omitted"):
            self.assertEqual(
                module.build_rp_reasoning_signature(),
                "anthropic|claude-sonnet-4-6|medium|omitted",
            )

    def test_provider_summary_reports_openrouter_deepseek_signal_path(self):
        module = load_module()

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "EPISODE_SUMMARY_MODEL", "deepseek/deepseek-v3.2"), \
             patch.object(module.settings, "ANTHROPIC_API_KEY", ""), \
             patch.object(module, "RP_REASONING_MODEL", ""), \
             patch.object(module, "EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL", "deepseek/deepseek-v4-pro"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "RP_OPENROUTER_PROVIDER_ONLY", "deepinfra,together"):
            line = module.build_storyctx_provider_summary_line()

        self.assertIn("episode_summary_provider=openrouter", line)
        self.assertIn("episode_summary_model=deepseek/deepseek-v3.2", line)
        self.assertIn("episode_character_signals_provider=openrouter", line)
        self.assertIn("episode_character_signals_model=deepseek/deepseek-v4-pro", line)
        self.assertIn("rp_profile_provider=openrouter", line)
        self.assertIn("rp_profile_model=google/gemma-4-31b-it", line)
        self.assertIn("rp_openrouter_provider_only=deepinfra,together", line)

    def test_episode_summary_prompt_uses_episode_summary_input_cap(self):
        module = load_module()
        normalized_text = "가" * (module.EPISODE_SUMMARY_MAX_INPUT_CHARS + 50)

        prompt = module.build_episode_summary_user_prompt(
            {"title": "테스트 작품", "episode_no": 1, "episode_title": "1화 시작"},
            normalized_text,
        )

        source_text = prompt.split("원문:\n", 1)[1]
        self.assertEqual(len(source_text), module.EPISODE_SUMMARY_MAX_INPUT_CHARS)

    def test_episode_character_signal_prompt_requires_explicit_identity_claims(self):
        module = load_module()

        prompt = module.EPISODE_CHARACTER_SIGNALS_PROMPT

        self.assertIn("is_work_protagonist는 작품 전체 주인공일 때만 true", prompt)
        self.assertIn("is_episode_focal은 이 회차의 중심 인물이면 true", prompt)
        self.assertIn("social_call_names에는 다른 인물이 그 인물을 부르는 호칭", prompt)
        self.assertIn("social_call_names는 identity merge 근거가 아니라 말투/거리감 근거", prompt)
        self.assertIn("전하, 폐하, 도련님, 아가씨, 공자, 대장, 팀장", prompt)
        self.assertIn("display_name으로 승격하지 마라", prompt)
        self.assertIn("persona_names에 넣고, 현실/전생/본명은 real_names", prompt)
        self.assertIn('display_name="나"로 두고', prompt)
        self.assertIn("연구 주제/대화 주제/사건명/상태어를 이름처럼 쓰지 마라", prompt)
        self.assertIn("호영이 조렌 테이머의 부활 중 빙의된 수호자", prompt)
        self.assertIn('target_label="조렌 테이머"', prompt)
        self.assertIn('claim_type="possessed_as"', prompt)
        self.assertIn("단순 직책, 소속, 가족/상하관계, 상태 설명, 같은 장면 등장은 identity_claims로 만들지 않는다", prompt)

    def test_print_summary_includes_provider_line_and_product_ids(self):
        module = load_module()
        results = module.build_empty_results()
        results["inserted_docs"] = 2
        results["inserted_episode_character_signals"] = 2
        results["products"] = [
            {
                "product_id": 687,
                "context_status": "processing",
                "ready_episode_count": 12,
                "total_episode_count": 20,
            }
        ]
        stdout = io.StringIO()

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "EPISODE_SUMMARY_MODEL", "deepseek/deepseek-v3.2"), \
             patch.object(module.settings, "ANTHROPIC_API_KEY", ""), \
             patch.object(module, "RP_REASONING_MODEL", ""), \
             patch.object(module, "EPISODE_CHARACTER_SIGNALS_OPENROUTER_MODEL", "deepseek/deepseek-v4-pro"), \
             redirect_stdout(stdout):
            module.print_summary(results=results, apply=True)

        output = stdout.getvalue()
        self.assertIn("storyctx-provider", output)
        self.assertIn("episode_character_signals_provider=openrouter", output)
        self.assertIn("mode=apply product_ids=687 inserted_docs=2", output)
        self.assertIn("inserted_episode_character_signals=2", output)
        self.assertIn("product product_id=687 status=processing ready=12 total=20", output)

    async def test_rp_profile_uses_paid_gemma_openrouter_payload(self):
        module = load_module()
        client = FakeOpenRouterClient(
            {
                "speech_style": {"tone": ["차분한"], "formality": "반말", "sentence_length": "보통", "habit": [], "address": ""},
                "personality_core": ["경계심이 강함"],
                "baseline_attitude": "경계",
                "example_dialogues": ["그게 정말 가능하다고?"],
            }
        )

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "RP_OPENROUTER_PROVIDER_ONLY", "deepinfra,together"):
            payload = await module.request_rp_profile_payload(
                client,
                target={"display_name": "백이현", "aliases": ["백이현"]},
                dialogue_items=[{"kind": "dialogue", "context": "질문", "text": "그게 정말 가능하다고?", "example_score": 8}],
                summary_context_lines=["[1화] 백이현이 상황을 의심한다."],
            )

        self.assertEqual(payload["baseline_attitude"], "경계")
        self.assertEqual(len(client.calls), 1)
        request_json = client.calls[0]["json"]
        self.assertEqual(request_json["model"], "google/gemma-4-31b-it")
        self.assertEqual(
            request_json["provider"],
            {
                "only": ["deepinfra", "together"],
                "order": ["deepinfra", "together"],
                "allow_fallbacks": True,
            },
        )
        self.assertEqual(request_json["reasoning"], {"effort": "none", "exclude": True})
        self.assertEqual(request_json["response_format"], {"type": "json_object"})
        self.assertNotIn(":free", request_json["model"])

    async def test_rp_openrouter_rejects_free_model_variant_before_network_call(self):
        module = load_module()
        client = FakeOpenRouterClient({"characters": []})

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it:free"):
            with self.assertRaisesRegex(RuntimeError, "must not use :free"):
                await module.request_rp_character_plan_payload(
                    client,
                    episode_rows=[],
                    episode_texts_by_no={},
                )

        self.assertEqual(client.calls, [])

    async def test_rp_dialogue_request_uses_openrouter_payload_without_undefined_provider_helper(self):
        module = load_module()
        client = FakeOpenRouterClient(
            {
                "items": [
                    {
                        "episode_no": 1,
                        "kind": "dialogue",
                        "context": "문 앞",
                        "text": "나는 여기서 물러서지 않아.",
                        "speaker_label": "백이현",
                        "confidence": 0.95,
                    }
                ]
            }
        )

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "RP_OPENROUTER_PROVIDER_ONLY", "google"):
            items = await module.request_rp_dialogue_items(
                client,
                target={
                    "display_name": "백이현",
                    "reference_name": "백이현",
                    "aliases": ["백이현"],
                },
                normalized_text='<episode no="1">백이현이 말했다. "나는 여기서 물러서지 않아."</episode>',
            )

        self.assertEqual(
            items,
            [{"episode_no": 1, "kind": "dialogue", "context": "문 앞", "text": "나는 여기서 물러서지 않아.", "confidence": 0.95}],
        )
        self.assertEqual(
            client.calls[0]["json"]["provider"],
            {"only": ["google"], "order": ["google"], "allow_fallbacks": False},
        )

    async def test_rp_build_keeps_old_profiles_when_plan_targets_missing(self):
        module = load_module()
        conn = FakeConnection()

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_rp_character_plan_payload", AsyncMock(return_value={"characters": []})), \
             patch.object(module, "deactivate_missing_active_scopes") as deactivate_missing:
            counts = await module.build_rp_summaries(
                conn,
                product_id=687,
                episode_rows=[],
                episode_texts_by_no={},
                summary_client=object(),
            )

        self.assertEqual(counts, {"profile": (0, 0), "examples": (0, 0)})
        deactivate_missing.assert_not_called()
        self.assertEqual(conn.commit_count, 0)

    async def test_rp_build_does_not_fallback_to_plan_when_v3_inventory_has_no_targets(self):
        module = load_module()
        conn = FakeConnection()
        plan_mock = AsyncMock(
            return_value={
                "characters": [
                    {
                        "character_key": "named:legacy",
                        "display_name": "레거시",
                        "aliases": ["레거시"],
                        "is_protagonist": False,
                    }
                ]
            }
        )

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_rp_character_plan_payload", plan_mock), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "deactivate_missing_active_scopes") as deactivate_missing:
            counts = await module.build_rp_summaries(
                conn,
                product_id=687,
                episode_rows=[],
                episode_texts_by_no={},
                summary_client=object(),
                inventory_map={
                    "character:해설자": {
                        "canonical_character_key": "character:해설자",
                        "display_name": "해설자",
                        "entity_kind": "narrator",
                        "distinct_episode_count": 3,
                    }
                },
            )

        self.assertEqual(counts, {"profile": (0, 0), "examples": (0, 0)})
        plan_mock.assert_not_called()
        deactivate_missing.assert_not_called()
        self.assertEqual(conn.commit_count, 0)

    async def test_rp_build_uses_v3_inventory_targets_without_plan_call(self):
        module = load_module()
        conn = FakeConnection()
        episode_texts_by_no = {
            1: "\n".join(
                [
                    '백이현이 말했다. "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해."',
                    '백이현이 낮게 물었다. "그 말이 사실이라면 지금 당장 증거를 보여 줘."',
                    '백이현은 고개를 저으며 말했다. "아직 끝난 게 아니야, 내가 직접 확인하겠어."',
                ]
            ),
            2: "\n".join(
                [
                    '백이현이 숨을 고르며 답했다. "겁먹을 시간은 없어, 먼저 사람들을 빼내."',
                    '백이현이 검을 세우며 말했다. "네가 막는다면 나도 돌아가지 않겠어."',
                    '백이현이 짧게 웃었다. "좋아, 이번엔 네 방식대로 움직여 보자."',
                ]
            ),
            3: "\n".join(
                [
                    '백이현이 문서를 접으며 말했다. "이 기록은 내가 맡을게, 누구에게도 넘기지 마."',
                    '백이현이 뒤돌아서며 말했다. "따라오지 마, 여기서부터는 내가 정리한다."',
                    '백이현이 조용히 말했다. "약속은 지킬 거야, 대신 너도 물러서지 마."',
                ]
            ),
        }
        profile_payload = {
            "speech_style": {"tone": "단호"},
            "personality_core": ["원칙적"],
            "baseline_attitude": "경계",
            "example_dialogues": [
                "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해.",
                "겁먹을 시간은 없어, 먼저 사람들을 빼내.",
                "이 기록은 내가 맡을게, 누구에게도 넘기지 마.",
            ],
        }
        plan_mock = AsyncMock(return_value={"characters": []})
        profile_mock = AsyncMock(return_value=profile_payload)

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_rp_character_plan_payload", plan_mock), \
             patch.object(module, "request_rp_profile_payload", profile_mock), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=[({"summary_id": 1}, True), ({"summary_id": 2}, True)]), \
             patch.object(module, "deactivate_missing_active_scopes") as deactivate_missing:
            counts = await module.build_rp_summaries(
                conn,
                product_id=687,
                episode_rows=[],
                episode_texts_by_no=episode_texts_by_no,
                summary_client=object(),
                inventory_map={
                    "character:백이현": {
                        "canonical_character_key": "character:백이현",
                        "source_character_keys": ["protagonist:named:백이현", "named:백이현"],
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 3,
                        "voice_evidence_count": 9,
                        "evidence_episode_nos": [1, 2, 3],
                    }
                },
            )

        self.assertEqual(counts, {"profile": (1, 0), "examples": (1, 0)})
        plan_mock.assert_not_called()
        profile_mock.assert_awaited_once()
        expected_scope_keys = {"character:백이현", "protagonist:named:백이현", "named:백이현"}
        deactivate_missing.assert_any_call(ANY, 687, "character_rp_profile", expected_scope_keys)
        deactivate_missing.assert_any_call(ANY, 687, "character_rp_examples", expected_scope_keys)
        self.assertEqual(conn.commit_count, 2)

    async def test_rp_build_reuses_existing_examples_when_new_voice_extraction_is_not_ready(self):
        module = load_module()
        conn = FakeConnection()
        legacy_scope_key = "protagonist:named:승택"
        legacy_examples = {
            "examples": [
                {
                    "episode_no": episode_no,
                    "source_kind": "dialogue",
                    "text": text,
                    "confidence": 0.9,
                }
                for episode_no, text in enumerate(
                    (
                        "내가 직접 확인하겠어.",
                        "지금은 물러서지 않아.",
                        "약속은 반드시 지킨다.",
                        "기록은 내가 맡을게.",
                        "이번에는 네 판단을 믿지.",
                    ),
                    start=1,
                )
            ]
        }
        profile_payload = {
            "speech_style": {"tone": "단호"},
            "personality_core": ["원칙적"],
            "baseline_attitude": "경계",
            "example_dialogues": [],
        }
        internal_prompt_payload = {"internal_prompt": "[핵심 정체성] 전승택은 직접 판단하고 움직인다."}
        upserted_types = []

        def fake_upsert(cur, **kwargs):
            upserted_types.append(kwargs["summary_type"])
            return {"summary_id": len(upserted_types)}, True

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "build_direct_voice_evidence_quality", return_value={"strict_chat_ready": True}), \
             patch.object(module, "collect_rule_based_rp_dialogue_items_by_episode", return_value=[
                 {"episode_no": (index % 5) + 1, "kind": "monologue", "text": f"내면 독백 근거 {index}번을 기록한다."}
                 for index in range(80)
             ]), \
             patch.object(module, "request_rp_profile_payload", AsyncMock(return_value=profile_payload)), \
             patch.object(module, "request_character_chat_internal_prompt_payload", AsyncMock(return_value=internal_prompt_payload)), \
             patch.object(module, "fetch_active_summary_state_map", return_value={
                 legacy_scope_key: {
                     "scope_key": legacy_scope_key,
                     "payload": legacy_examples,
                 }
             }), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=fake_upsert), \
             patch.object(module, "deactivate_missing_active_scopes"):
            counts = await module.build_rp_summaries(
                conn,
                product_id=756,
                episode_rows=[],
                episode_texts_by_no={
                    item["episode_no"]: item["text"]
                    for item in legacy_examples["examples"]
                },
                summary_client=object(),
                inventory_map={
                    "character:전승택": {
                        "canonical_character_key": "character:전승택",
                        "source_character_keys": [legacy_scope_key],
                        "display_name": "전승택",
                        "aliases": ["전승택", "승택"],
                        "is_protagonist": True,
                        "distinct_episode_count": 16,
                        "public_chat_eligible": False,
                        "display_safety": {
                            "status": "pass",
                            "reason": "resolved_named_identity",
                        },
                    }
                },
            )

        self.assertEqual(counts, {"profile": (1, 0), "examples": (1, 0)})
        self.assertEqual(
            upserted_types,
            ["character_rp_profile", "character_rp_examples", "character_chat_internal_prompt"],
        )

    async def test_rp_build_upserts_character_chat_internal_prompt_when_generated(self):
        module = load_module()
        conn = FakeConnection()
        episode_texts_by_no = {
            1: "\n".join(
                [
                    '백이현이 말했다. "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해."',
                    '백이현이 낮게 물었다. "그 말이 사실이라면 지금 당장 증거를 보여 줘."',
                    '백이현은 고개를 저으며 말했다. "아직 끝난 게 아니야, 내가 직접 확인하겠어."',
                ]
            ),
            2: "\n".join(
                [
                    '백이현이 숨을 고르며 답했다. "겁먹을 시간은 없어, 먼저 사람들을 빼내."',
                    '백이현이 검을 세우며 말했다. "네가 막는다면 나도 돌아가지 않겠어."',
                    '백이현이 짧게 웃었다. "좋아, 이번엔 네 방식대로 움직여 보자."',
                ]
            ),
            3: "\n".join(
                [
                    '백이현이 문서를 접으며 말했다. "이 기록은 내가 맡을게, 누구에게도 넘기지 마."',
                    '백이현이 뒤돌아서며 말했다. "따라오지 마, 여기서부터는 내가 정리한다."',
                    '백이현이 조용히 말했다. "약속은 지킬 거야, 대신 너도 물러서지 마."',
                ]
            ),
        }
        profile_payload = {
            "speech_style": {"tone": "단호"},
            "personality_core": ["원칙적"],
            "baseline_attitude": "경계",
            "example_dialogues": [
                "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해.",
                "겁먹을 시간은 없어, 먼저 사람들을 빼내.",
                "이 기록은 내가 맡을게, 누구에게도 넘기지 마.",
            ],
        }
        scene_context_lines = ["[1화] 압력=경비병 접근 | hook=잠금 장치 확인"]
        internal_prompt_mock = AsyncMock(
            return_value={
                "internal_prompt": "[핵심 정체성] 백이현은 물러서지 않는 주인공이다.\n[짧은 입력 처리] 사용자가 짧게 답해도 장면을 전진시킨다."
            }
        )
        upserted_types = []

        def fake_upsert(cur, **kwargs):
            upserted_types.append(kwargs["summary_type"])
            return {"summary_id": len(upserted_types)}, True

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_rp_character_plan_payload", AsyncMock(return_value={"characters": []})), \
             patch.object(module, "request_rp_profile_payload", AsyncMock(return_value=profile_payload)), \
             patch.object(module, "request_character_chat_internal_prompt_payload", internal_prompt_mock), \
             patch.object(module, "load_character_chat_scene_context_lines_by_scope", return_value={"character:백이현": scene_context_lines}), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=fake_upsert), \
             patch.object(module, "deactivate_missing_active_scopes"):
            counts = await module.build_rp_summaries(
                conn,
                product_id=687,
                episode_rows=[],
                episode_texts_by_no=episode_texts_by_no,
                summary_client=object(),
                inventory_map={
                    "character:백이현": {
                        "canonical_character_key": "character:백이현",
                        "source_character_keys": ["protagonist:named:백이현", "named:백이현"],
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 3,
                        "voice_evidence_count": 9,
                        "evidence_episode_nos": [1, 2, 3],
                    }
                },
            )

        self.assertEqual(counts, {"profile": (1, 0), "examples": (1, 0)})
        internal_prompt_mock.assert_awaited_once()
        self.assertEqual(internal_prompt_mock.await_args.kwargs["scene_context_lines"], scene_context_lines)
        self.assertEqual(
            upserted_types,
            ["character_rp_profile", "character_rp_examples", "character_chat_internal_prompt"],
        )

    async def test_delta_rp_build_uses_v3_inventory_without_plan_call(self):
        module = load_module()
        conn = FakeConnection()
        episode_texts_by_no = {
            1: "\n".join(
                [
                    '백이현이 말했다. "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해."',
                    '백이현이 낮게 물었다. "그 말이 사실이라면 지금 당장 증거를 보여 줘."',
                    '백이현은 고개를 저으며 말했다. "아직 끝난 게 아니야, 내가 직접 확인하겠어."',
                ]
            ),
            2: "\n".join(
                [
                    '백이현이 숨을 고르며 답했다. "겁먹을 시간은 없어, 먼저 사람들을 빼내."',
                    '백이현이 검을 세우며 말했다. "네가 막는다면 나도 돌아가지 않겠어."',
                    '백이현이 짧게 웃었다. "좋아, 이번엔 네 방식대로 움직여 보자."',
                ]
            ),
            3: "\n".join(
                [
                    '백이현이 문서를 접으며 말했다. "이 기록은 내가 맡을게, 누구에게도 넘기지 마."',
                    '백이현이 뒤돌아서며 말했다. "따라오지 마, 여기서부터는 내가 정리한다."',
                    '백이현이 조용히 말했다. "약속은 지킬 거야, 대신 너도 물러서지 마."',
                ]
            ),
        }
        profile_payload = {
            "speech_style": {"tone": "단호"},
            "personality_core": ["원칙적"],
            "baseline_attitude": "경계",
            "example_dialogues": [
                "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해.",
                "겁먹을 시간은 없어, 먼저 사람들을 빼내.",
                "이 기록은 내가 맡을게, 누구에게도 넘기지 마.",
            ],
        }
        plan_mock = AsyncMock(return_value={"characters": []})
        profile_mock = AsyncMock(return_value=profile_payload)
        scene_context_lines = ["[2화] 압력=문서 봉인 | hook=기록 확인"]
        internal_prompt_mock = AsyncMock(return_value={"internal_prompt": "[현재 장면] 문서 봉인을 확인한다."})

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_rp_character_plan_payload", plan_mock), \
             patch.object(module, "request_rp_profile_payload", profile_mock), \
             patch.object(module, "request_character_chat_internal_prompt_payload", internal_prompt_mock), \
             patch.object(module, "fetch_active_summary_state_map", return_value={}), \
             patch.object(module, "load_character_chat_scene_context_lines_by_scope", return_value={"character:백이현": scene_context_lines}), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=[({"summary_id": 1}, True), ({"summary_id": 2}, True), ({"summary_id": 3}, True)]), \
             patch.object(module, "deactivate_active_scope", return_value=1) as deactivate_scope:
            counts = await module.build_rp_summaries_delta(
                conn,
                product_id=687,
                affected_scope_keys={"character:백이현", "protagonist:named:백이현"},
                episode_rows=[],
                episode_texts_by_no=episode_texts_by_no,
                summary_client=object(),
                inventory_map={
                    "character:백이현": {
                        "canonical_character_key": "character:백이현",
                        "source_character_keys": ["protagonist:named:백이현", "named:백이현"],
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 3,
                        "voice_evidence_count": 9,
                        "evidence_episode_nos": [1, 2, 3],
                    }
                },
                relation_map={},
            )

        self.assertEqual(counts["profile"], [1, 0])
        self.assertEqual(counts["examples"], [1, 0])
        plan_mock.assert_not_called()
        profile_mock.assert_awaited_once()
        internal_prompt_mock.assert_awaited_once()
        self.assertEqual(internal_prompt_mock.await_args.kwargs["scene_context_lines"], scene_context_lines)
        self.assertEqual(counts["deactivated_profile_count"], 0)
        self.assertEqual(counts["deactivated_examples_count"], 0)
        deactivate_scope.assert_not_called()

    async def test_delta_rp_build_accepts_two_grounded_examples_below_strict_distribution_gate(self):
        module = load_module()
        conn = FakeConnection()
        dialogue_items = [
            {
                "episode_no": 3,
                "kind": "dialogue",
                "text": "아저씨 얼른 저 따라오세요. 여기 위험해요.",
            },
            {
                "episode_no": 3,
                "kind": "dialogue",
                "text": "이번에는 제가 아저씨를 살려드릴게요.",
            },
        ]
        aliases = ["이시혁"]
        self.assertFalse(module.is_strict_dialogue_item_set_ready(dialogue_items, aliases))

        profile_payload = {
            "speech_style": {"tone": "단호"},
            "personality_core": ["책임감"],
            "baseline_attitude": "보호",
            "example_dialogues": [item["text"] for item in dialogue_items],
        }

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "build_direct_voice_evidence_quality", return_value={"strict_chat_ready": False, "status": "insufficient"}), \
             patch.object(module, "collect_rule_based_rp_dialogue_items_by_episode", return_value=[]), \
             patch.object(module, "collect_llm_rp_dialogue_items", AsyncMock(return_value=dialogue_items)), \
             patch.object(module, "request_rp_profile_payload", AsyncMock(return_value=profile_payload)), \
             patch.object(module, "request_character_chat_internal_prompt_payload", AsyncMock(return_value=None)), \
             patch.object(module, "fetch_active_summary_state_map", return_value={}), \
             patch.object(module, "load_character_chat_scene_context_lines_by_scope", return_value={}), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=[({"summary_id": 1}, True), ({"summary_id": 2}, True)]), \
             patch.object(module, "deactivate_active_scope", return_value=0):
            counts = await module.build_rp_summaries_delta(
                conn,
                product_id=1099,
                affected_scope_keys={"character:이시혁"},
                episode_rows=[],
                episode_texts_by_no={3: "원문"},
                summary_client=object(),
                inventory_map={
                    "character:이시혁": {
                        "canonical_character_key": "character:이시혁",
                        "display_name": "이시혁",
                        "aliases": aliases,
                        "is_protagonist": True,
                        "distinct_episode_count": 83,
                    }
                },
                relation_map={},
            )

        self.assertEqual(counts["profile"], [1, 0])
        self.assertEqual(counts["examples"], [1, 0])
        self.assertEqual(counts["keep_old_dialogue_missing_count"], 0)

    async def test_delta_rp_strict_mode_raises_unexpected_dialogue_error(self):
        module = load_module()
        conn = FakeConnection()
        scope_key = "character:데시"

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "build_direct_voice_evidence_quality", return_value={"strict_chat_ready": False}), \
             patch.object(module, "collect_rule_based_rp_dialogue_items_by_episode", return_value=[]), \
             patch.object(module, "collect_llm_rp_dialogue_items", AsyncMock(side_effect=TypeError("dialogue parser bug"))), \
             patch.object(module, "fetch_active_summary_state_map", return_value={}), \
             patch.object(module, "load_character_chat_scene_context_lines_by_scope", return_value={}), \
             patch.object(module, "work_cursor", fake_work_cursor):
            with self.assertRaisesRegex(TypeError, "dialogue parser bug"):
                await module.build_rp_summaries_delta(
                    conn,
                    product_id=687,
                    affected_scope_keys={scope_key},
                    episode_rows=[],
                    episode_texts_by_no={1: "데시가 문을 연다."},
                    summary_client=object(),
                    inventory_map={
                        scope_key: {
                            "canonical_character_key": scope_key,
                            "display_name": "데시",
                            "aliases": ["데시"],
                            "is_protagonist": True,
                            "distinct_episode_count": 3,
                        }
                    },
                    relation_map={},
                    raise_unexpected_errors=True,
                )

    async def test_delta_rp_strict_mode_keeps_provider_402_as_no_progress(self):
        module = load_module()
        conn = FakeConnection()
        scope_key = "character:데시"
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        response = httpx.Response(402, request=request)
        provider_error = httpx.HTTPStatusError(
            "402 Payment Required",
            request=request,
            response=response,
        )

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "build_direct_voice_evidence_quality", return_value={"strict_chat_ready": False, "status": "insufficient"}), \
             patch.object(module, "collect_rule_based_rp_dialogue_items_by_episode", return_value=[]), \
             patch.object(module, "collect_llm_rp_dialogue_items", AsyncMock(side_effect=provider_error)), \
             patch.object(module, "fetch_active_summary_state_map", return_value={}), \
             patch.object(module, "load_character_chat_scene_context_lines_by_scope", return_value={}), \
             patch.object(module, "work_cursor", fake_work_cursor):
            counts = await module.build_rp_summaries_delta(
                conn,
                product_id=687,
                affected_scope_keys={scope_key},
                episode_rows=[],
                episode_texts_by_no={1: "데시가 문을 연다."},
                summary_client=object(),
                inventory_map={
                    scope_key: {
                        "canonical_character_key": scope_key,
                        "display_name": "데시",
                        "aliases": ["데시"],
                        "is_protagonist": True,
                        "distinct_episode_count": 3,
                    }
                },
                relation_map={},
                raise_unexpected_errors=True,
            )

        self.assertEqual(counts["profile"], [0, 0])
        self.assertEqual(counts["examples"], [0, 0])
        self.assertEqual(counts["keep_old_dialogue_missing_count"], 1)

    async def test_delta_rp_build_materializes_legacy_profile_examples_without_provider_dependency(self):
        module = load_module()
        conn = FakeConnection()
        scope_key = "character:백이현"
        legacy_scope_key = "protagonist:named:백이현"
        profile_payload = {
            "character_key": legacy_scope_key,
            "display_name": "백이현",
            "aliases": ["백이현"],
            "speech_style": {"tone": "단호"},
            "personality_core": ["원칙적"],
            "baseline_attitude": "경계",
        }
        example_payload = {
            "character_key": legacy_scope_key,
            "examples": [
                {"episode_no": 1, "source_kind": "dialogue", "text": "나는 여기서 물러서지 않을 거야.", "confidence": 0.9},
                {"episode_no": 2, "source_kind": "dialogue", "text": "겁먹을 시간은 없어, 먼저 사람들을 빼내.", "confidence": 0.9},
                {"episode_no": 3, "source_kind": "dialogue", "text": "이 기록은 내가 맡을게, 누구에게도 넘기지 마.", "confidence": 0.9},
            ],
        }
        state_maps = {
            "character_rp_profile": {
                legacy_scope_key: {
                    "summary_id": 11,
                    "scope_key": legacy_scope_key,
                    "source_hash": "legacy-profile-hash",
                    "payload": profile_payload,
                }
            },
            "character_rp_examples": {
                legacy_scope_key: {
                    "summary_id": 12,
                    "scope_key": legacy_scope_key,
                    "source_hash": "legacy-examples-hash",
                    "payload": example_payload,
                }
            },
        }
        internal_prompt_mock = AsyncMock(
            return_value={"internal_prompt": "[핵심] 백이현은 기존 RP 자료를 바탕으로 먼저 움직인다."}
        )
        profile_mock = AsyncMock(return_value={"speech_style": {"tone": "unused"}})
        upserted = []

        def fake_fetch_state_map(*, summary_type, **_kwargs):
            return state_maps.get(summary_type, {})

        def fake_upsert(_cur, **kwargs):
            upserted.append(kwargs)
            return {"summary_id": len(upserted)}, True

        with patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module, "RP_OPENROUTER_MODEL", ""), \
             patch.object(module, "fetch_active_summary_state_map", side_effect=fake_fetch_state_map), \
             patch.object(module, "request_rp_profile_payload", profile_mock), \
             patch.object(module, "request_character_chat_internal_prompt_payload", internal_prompt_mock), \
             patch.object(module, "collect_llm_rp_dialogue_items", AsyncMock(return_value=[])) as dialogue_mock, \
             patch.object(module, "load_character_chat_scene_context_lines_by_scope", return_value={scope_key: ["[1화] 압력=문서 봉인 | hook=흔적 확인"]}), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=fake_upsert), \
             patch.object(module, "deactivate_active_scope", return_value=1) as deactivate_scope:
            counts = await module.build_rp_summaries_delta(
                conn,
                product_id=687,
                affected_scope_keys={scope_key},
                episode_rows=[],
                episode_texts_by_no={},
                summary_client=None,
                inventory_map={
                    scope_key: {
                        "canonical_character_key": scope_key,
                        "source_character_keys": [legacy_scope_key, "named:백이현"],
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 3,
                        "voice_evidence_count": 0,
                    }
                },
                relation_map={},
            )

        self.assertEqual(counts["profile"], [1, 0])
        self.assertEqual(counts["examples"], [1, 0])
        self.assertEqual(counts["keep_old_dialogue_missing_count"], 0)
        dialogue_mock.assert_not_awaited()
        profile_mock.assert_not_awaited()
        internal_prompt_mock.assert_not_awaited()
        self.assertEqual([item["summary_type"] for item in upserted], [
            "character_rp_profile",
            "character_rp_examples",
        ])
        self.assertTrue(all(item["scope_key"] == scope_key for item in upserted))
        deactivate_scope.assert_not_called()

    async def test_delta_rp_build_bridges_reviewed_matching_profile_from_ambiguous_alias(self):
        module = load_module()
        conn = FakeConnection()
        scope_key = "character:4ca88c0896bf"
        other_scope_key = "character:당시우"
        legacy_scope_key = "protagonist:first_person"
        profile_payload = {
            "character_key": legacy_scope_key,
            "display_name": "백의",
            "aliases": ["백의", "실눈 성자"],
            "speech_style": {"tone": "담담"},
            "personality_core": ["신중함"],
            "baseline_attitude": "경계",
        }
        example_payload = {
            "character_key": legacy_scope_key,
            "examples": [
                {"episode_no": 0, "source_kind": "dialogue", "text": "첫 번째 유일 대사", "confidence": 0.9},
                {"episode_no": 0, "source_kind": "dialogue", "text": "두 번째 유일 대사", "confidence": 0.9},
                {"episode_no": 0, "source_kind": "dialogue", "text": "세 번째 유일 대사", "confidence": 0.9},
            ],
        }
        state_maps = {
            "character_rp_profile": {
                legacy_scope_key: {
                    "summary_id": 11,
                    "scope_key": legacy_scope_key,
                    "source_hash": "legacy-profile-hash",
                    "payload": profile_payload,
                }
            },
            "character_rp_examples": {
                legacy_scope_key: {
                    "summary_id": 12,
                    "scope_key": legacy_scope_key,
                    "source_hash": "legacy-examples-hash",
                    "payload": example_payload,
                }
            },
        }
        inventory_map = {
            scope_key: {
                "canonical_character_key": scope_key,
                "source_character_keys": [legacy_scope_key],
                "display_name": "실눈 성자",
                "aliases": ["실눈 성자", "나"],
                "is_protagonist": True,
                "distinct_episode_count": 8,
                "identity_surface_review_v1": {
                    "version": 1,
                    "operation_id": "merge-squint-saint",
                    "review_digest": "review-digest",
                    "canonical_display_name": "실눈 성자",
                },
            },
            other_scope_key: {
                "canonical_character_key": other_scope_key,
                "source_character_keys": [legacy_scope_key, "named:당시우"],
                "display_name": "당시우",
                "aliases": ["당시우"],
                "distinct_episode_count": 2,
            },
        }
        upserted = []

        def fake_fetch_state_map(*, summary_type, **_kwargs):
            return state_maps.get(summary_type, {})

        def fake_upsert(_cur, **kwargs):
            upserted.append(kwargs)
            return {"summary_id": len(upserted)}, True

        with patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module, "RP_OPENROUTER_MODEL", ""), \
             patch.object(module, "fetch_active_summary_state_map", side_effect=fake_fetch_state_map), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=fake_upsert):
            counts = await module.build_rp_summaries_delta(
                conn,
                product_id=1109,
                affected_scope_keys={scope_key},
                episode_rows=[],
                episode_texts_by_no={
                    4: "첫 번째 유일 대사",
                    5: "두 번째 유일 대사와 세 번째 유일 대사",
                },
                summary_client=None,
                inventory_map=inventory_map,
                relation_map={},
            )

        self.assertNotIn(
            legacy_scope_key,
            module.build_inventory_source_scope_key_map(inventory_map),
        )
        self.assertEqual(counts["profile"], [1, 0])
        self.assertEqual(counts["examples"], [1, 0])
        self.assertEqual(
            [item["scope_key"] for item in upserted],
            [scope_key, scope_key],
        )
        saved_examples = json.loads(upserted[1]["summary_text"])
        self.assertEqual(
            [item["episode_no"] for item in saved_examples["examples"]],
            [4, 5, 5],
        )

    async def test_delta_rp_build_recovers_inactive_inventory_scope_by_strong_history_alias(self):
        module = load_module()
        conn = FakeConnection()
        current_scope_key = "character:레이븐:dup:faa369a2"
        legacy_scope_key = "character:레이븐:dup:be810f0c"
        stable_source_key = "protagonist:named:레이븐"
        state_maps = {
            "character_rp_profile": {
                legacy_scope_key: {
                    "scope_key": legacy_scope_key,
                    "source_hash": "legacy-profile-hash",
                    "payload": {
                        "character_key": legacy_scope_key,
                        "display_name": "레이븐",
                        "speech_style": {"tone": "건조"},
                    },
                }
            },
            "character_rp_examples": {
                legacy_scope_key: {
                    "scope_key": legacy_scope_key,
                    "source_hash": "legacy-examples-hash",
                    "payload": {
                        "character_key": legacy_scope_key,
                        "examples": [
                            {
                                "episode_no": 2,
                                "source_kind": "dialogue",
                                "text": "살아남으려면 지금 움직여.",
                            }
                        ],
                    },
                }
            },
        }
        upserted = []

        def fake_fetch_state_map(*, summary_type, **_kwargs):
            return state_maps.get(summary_type, {})

        def fake_upsert(_cur, **kwargs):
            upserted.append(kwargs)
            return {"summary_id": len(upserted)}, True

        with patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module, "RP_OPENROUTER_MODEL", ""), \
             patch.object(module, "fetch_active_summary_state_map", side_effect=fake_fetch_state_map), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=fake_upsert):
            counts = await module.build_rp_summaries_delta(
                conn,
                product_id=1103,
                affected_scope_keys={current_scope_key},
                episode_rows=[],
                episode_texts_by_no={},
                summary_client=None,
                inventory_map={
                    current_scope_key: {
                        "canonical_character_key": current_scope_key,
                        "source_character_keys": [stable_source_key],
                        "display_name": "레이븐",
                        "aliases": ["레이븐"],
                        "is_protagonist": True,
                        "distinct_episode_count": 116,
                    }
                },
                historical_inventory_state_map={
                    legacy_scope_key: {
                        "summary_id": 101,
                        "scope_key": legacy_scope_key,
                        "payload": {
                            "canonical_character_key": legacy_scope_key,
                            "source_character_keys": [stable_source_key],
                            "display_name": "레이븐",
                        },
                    }
                },
                relation_map={},
            )

        self.assertEqual(counts["profile"], [1, 0])
        self.assertEqual(counts["examples"], [1, 0])
        self.assertEqual(
            [item["scope_key"] for item in upserted],
            [current_scope_key, current_scope_key],
        )

    def test_rp_example_episode_evidence_backfill_uses_unique_exact_source_match_only(self):
        module = load_module()
        payload = {
            "character_key": "character:레이븐",
            "examples": [
                {"episode_no": 0, "text": "유일하게 남은 대사"},
                {"episode_no": 0, "text": "두 번 나온 대사"},
                {"episode_no": 7, "text": "이미 근거가 있는 대사"},
            ],
        }

        repaired, recovered_count = module.backfill_rp_example_episode_evidence(
            payload,
            {
                1: "두 번 나온 대사",
                2: "유일하게 남은 대사와 두 번 나온 대사",
                7: "이미 근거가 있는 대사",
            },
        )

        self.assertEqual(recovered_count, 1)
        self.assertEqual(
            [item["episode_no"] for item in repaired["examples"]],
            [2, 0, 7],
        )
        self.assertEqual(
            [item["episode_no"] for item in payload["examples"]],
            [0, 0, 7],
        )

    async def test_delta_rp_build_repairs_exact_key_examples_without_provider(self):
        module = load_module()
        conn = FakeConnection()
        scope_key = "character:레이븐:dup:faa369a2"
        state_maps = {
            "character_rp_profile": {
                scope_key: {
                    "scope_key": scope_key,
                    "source_hash": "profile-hash",
                    "payload": {
                        "character_key": scope_key,
                        "display_name": "레이븐",
                    },
                }
            },
            "character_rp_examples": {
                scope_key: {
                    "scope_key": scope_key,
                    "source_hash": "examples-without-evidence-hash",
                    "payload": {
                        "character_key": scope_key,
                        "examples": [
                            {"episode_no": 0, "text": "유일하게 남은 대사"},
                            {"episode_no": 0, "text": "두 번 나온 대사"},
                        ],
                    },
                }
            },
        }
        upserted = []

        def fake_fetch_state_map(*, summary_type, **_kwargs):
            return state_maps.get(summary_type, {})

        def fake_upsert(_cur, **kwargs):
            upserted.append(kwargs)
            return {"summary_id": 21}, True

        with patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module, "RP_OPENROUTER_MODEL", ""), \
             patch.object(module, "fetch_active_summary_state_map", side_effect=fake_fetch_state_map), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=fake_upsert):
            counts = await module.build_rp_summaries_delta(
                conn,
                product_id=1103,
                affected_scope_keys={scope_key},
                episode_rows=[],
                episode_texts_by_no={
                    1: "두 번 나온 대사",
                    2: "유일하게 남은 대사와 두 번 나온 대사",
                },
                summary_client=None,
                inventory_map={
                    scope_key: {
                        "canonical_character_key": scope_key,
                        "display_name": "레이븐",
                        "aliases": ["레이븐"],
                        "is_protagonist": True,
                        "distinct_episode_count": 117,
                    }
                },
                relation_map={},
            )

        self.assertEqual(counts["profile"], [0, 1])
        self.assertEqual(counts["examples"], [1, 0])
        self.assertEqual(len(upserted), 1)
        self.assertEqual(upserted[0]["summary_type"], "character_rp_examples")
        saved_payload = json.loads(upserted[0]["summary_text"])
        self.assertEqual(
            [item["episode_no"] for item in saved_payload["examples"]],
            [2, 0],
        )

    async def test_delta_rp_build_does_not_recover_history_by_name_only(self):
        module = load_module()
        conn = FakeConnection()
        current_scope_key = "character:레이븐:dup:new"
        legacy_scope_key = "character:레이븐:dup:old"
        state_maps = {
            "character_rp_profile": {
                legacy_scope_key: {
                    "scope_key": legacy_scope_key,
                    "source_hash": "legacy-profile-hash",
                    "payload": {"character_key": legacy_scope_key},
                }
            },
            "character_rp_examples": {
                legacy_scope_key: {
                    "scope_key": legacy_scope_key,
                    "source_hash": "legacy-examples-hash",
                    "payload": {
                        "character_key": legacy_scope_key,
                        "examples": [{"episode_no": 1, "text": "기존 대사"}],
                    },
                }
            },
        }

        def fake_fetch_state_map(*, summary_type, **_kwargs):
            return state_maps.get(summary_type, {})

        with patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module, "RP_OPENROUTER_MODEL", ""), \
             patch.object(module, "fetch_active_summary_state_map", side_effect=fake_fetch_state_map), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary") as upsert_mock:
            counts = await module.build_rp_summaries_delta(
                conn,
                product_id=1103,
                affected_scope_keys={current_scope_key},
                episode_rows=[],
                episode_texts_by_no={},
                summary_client=None,
                inventory_map={
                    current_scope_key: {
                        "canonical_character_key": current_scope_key,
                        "source_character_keys": ["named:레이븐:new"],
                        "display_name": "레이븐",
                        "aliases": ["레이븐"],
                        "is_protagonist": True,
                        "distinct_episode_count": 116,
                    }
                },
                historical_inventory_state_map={
                    legacy_scope_key: {
                        "summary_id": 101,
                        "scope_key": legacy_scope_key,
                        "payload": {
                            "canonical_character_key": legacy_scope_key,
                            "source_character_keys": ["named:레이븐:old"],
                            "display_name": "레이븐",
                        },
                    }
                },
                relation_map={},
            )

        self.assertEqual(counts["profile"], [0, 0])
        self.assertEqual(counts["examples"], [0, 0])
        upsert_mock.assert_not_called()

    def test_rp_ready_inventory_history_reads_latest_scope_with_active_asset_pair(self):
        module = load_module()
        scope_key = "character:레이븐:dup:old"
        cursor = FakeRowsCursor(
            [
                {
                    "summary_id": 12,
                    "scope_key": scope_key,
                    "summary_text": json.dumps(
                        {
                            "canonical_character_key": scope_key,
                            "source_character_keys": ["protagonist:named:레이븐"],
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "summary_id": 11,
                    "scope_key": scope_key,
                    "summary_text": "{}",
                },
            ]
        )

        history = module.fetch_rp_ready_character_inventory_history_state_map(
            cursor,
            product_id=1103,
        )

        self.assertEqual(history[scope_key]["summary_id"], 12)
        self.assertEqual(
            history[scope_key]["payload"]["source_character_keys"],
            ["protagonist:named:레이븐"],
        )
        self.assertIn("profile.is_active = 'Y'", cursor.query)
        self.assertIn("examples.is_active = 'Y'", cursor.query)
        self.assertEqual(cursor.params, (1103,))

    async def test_delta_rp_build_preserves_successful_canonical_rows(self):
        module = load_module()
        conn = FakeConnection()
        scope_key = "character:백이현"
        legacy_scope_key = "named:백이현"
        episode_texts_by_no = {
            1: "\n".join(
                [
                    '백이현이 말했다. "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해."',
                    '백이현이 낮게 물었다. "그 말이 사실이라면 지금 당장 증거를 보여 줘."',
                    '백이현은 고개를 저으며 말했다. "아직 끝난 게 아니야, 내가 직접 확인하겠어."',
                ]
            ),
            2: "\n".join(
                [
                    '백이현이 숨을 고르며 답했다. "겁먹을 시간은 없어, 먼저 사람들을 빼내."',
                    '백이현이 검을 세우며 말했다. "네가 막는다면 나도 돌아가지 않겠어."',
                    '백이현이 짧게 웃었다. "좋아, 이번엔 네 방식대로 움직여 보자."',
                ]
            ),
            3: "\n".join(
                [
                    '백이현이 문서를 접으며 말했다. "이 기록은 내가 맡을게, 누구에게도 넘기지 마."',
                    '백이현이 뒤돌아서며 말했다. "따라오지 마, 여기서부터는 내가 정리한다."',
                    '백이현이 조용히 말했다. "약속은 지킬 거야, 대신 너도 물러서지 마."',
                ]
            ),
        }
        canonical_profile_payload = {"character_key": scope_key, "display_name": "백이현", "speech_style": {"tone": "old"}}
        canonical_example_payload = {
            "character_key": scope_key,
            "examples": [{"episode_no": 1, "text": "낡은 대표 대사"}],
        }
        legacy_profile_payload = {"character_key": legacy_scope_key, "display_name": "백이현", "speech_style": {"tone": "legacy"}}
        legacy_example_payload = {
            "character_key": legacy_scope_key,
            "examples": [{"episode_no": 1, "text": "legacy 대표 대사"}],
        }
        state_maps = {
            "character_rp_profile": {
                scope_key: {"scope_key": scope_key, "source_hash": "canonical-profile-hash", "payload": canonical_profile_payload},
                legacy_scope_key: {"scope_key": legacy_scope_key, "source_hash": "legacy-profile-hash", "payload": legacy_profile_payload},
            },
            "character_rp_examples": {
                scope_key: {"scope_key": scope_key, "source_hash": "canonical-examples-hash", "payload": canonical_example_payload},
                legacy_scope_key: {"scope_key": legacy_scope_key, "source_hash": "legacy-examples-hash", "payload": legacy_example_payload},
            },
        }
        profile_mock = AsyncMock(
            return_value={
                "speech_style": {"tone": "new"},
                "personality_core": ["원칙적"],
                "baseline_attitude": "경계",
                "example_dialogues": [
                    "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해.",
                    "겁먹을 시간은 없어, 먼저 사람들을 빼내.",
                    "이 기록은 내가 맡을게, 누구에게도 넘기지 마.",
                ],
            }
        )
        internal_prompt_mock = AsyncMock(return_value={"internal_prompt": "[핵심] 새 대사 근거로 다시 조립한다."})

        def fake_fetch_state_map(*, summary_type, **_kwargs):
            return state_maps.get(summary_type, {})

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "fetch_active_summary_state_map", side_effect=fake_fetch_state_map), \
             patch.object(module, "request_rp_profile_payload", profile_mock), \
             patch.object(module, "request_character_chat_internal_prompt_payload", internal_prompt_mock), \
             patch.object(module, "load_character_chat_scene_context_lines_by_scope", return_value={scope_key: ["[1화] 압력=문서 봉인 | hook=흔적 확인"]}), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=[({"summary_id": 1}, True), ({"summary_id": 2}, True), ({"summary_id": 3}, True)]) as upsert_mock, \
             patch.object(module, "deactivate_active_scope", return_value=1):
            counts = await module.build_rp_summaries_delta(
                conn,
                product_id=687,
                affected_scope_keys={scope_key},
                episode_rows=[],
                episode_texts_by_no=episode_texts_by_no,
                summary_client=object(),
                inventory_map={
                    scope_key: {
                        "canonical_character_key": scope_key,
                        "source_character_keys": [legacy_scope_key],
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 3,
                        "voice_evidence_count": 9,
                        "evidence_episode_nos": [1, 2, 3],
                    }
                },
                relation_map={},
            )

        self.assertEqual(counts["profile"], [0, 1])
        self.assertEqual(counts["examples"], [0, 1])
        profile_mock.assert_not_awaited()
        internal_prompt_mock.assert_not_awaited()
        upsert_mock.assert_not_called()

    async def test_delta_rp_current_generation_does_not_accept_stale_exact_rows(self):
        module = load_module()
        conn = FakeConnection()
        scope_key = "character:백이현"
        processed_scope_keys = set()
        state_maps = {
            "character_rp_profile": {
                scope_key: {
                    "scope_key": scope_key,
                    "payload": {
                        "character_key": scope_key,
                        "display_name": "백이현",
                    },
                }
            },
            "character_rp_examples": {
                scope_key: {
                    "scope_key": scope_key,
                    "payload": {
                        "character_key": scope_key,
                        "examples": [{"episode_no": 1, "text": "기존 대사"}],
                    },
                }
            },
        }

        with patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module, "fetch_active_summary_state_map", side_effect=lambda *, summary_type, **_kwargs: state_maps.get(summary_type, {})), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary") as upsert_mock:
            counts = await module.build_rp_summaries_delta(
                conn,
                product_id=687,
                affected_scope_keys={scope_key},
                episode_rows=[],
                episode_texts_by_no={1: "백이현이 말했다."},
                summary_client=None,
                inventory_map={
                    scope_key: {
                        "canonical_character_key": scope_key,
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 30,
                        "voice_evidence_count": 3,
                    }
                },
                relation_map={},
                require_current_generation_scope_keys={scope_key},
                processed_scope_keys=processed_scope_keys,
            )

        self.assertEqual(counts["profile"], [0, 0])
        self.assertEqual(counts["examples"], [0, 0])
        self.assertEqual(processed_scope_keys, set())
        upsert_mock.assert_not_called()

    async def test_character_chat_opening_build_upserts_exact_v3_scope_only(self):
        module = load_module()
        conn = FakeConnection()
        scope_key = "character:백이현"
        profile_payload = {
            "character_key": scope_key,
            "display_name": "백이현",
            "aliases": ["백이현"],
            "speech_style": {"tone": "단호"},
        }
        example_payload = {
            "character_key": scope_key,
            "examples": [{"episode_no": 1, "text": "나는 여기서 물러서지 않을 거야."}],
        }
        internal_prompt_payload = {"internal_prompt": "[핵심 정체성] 백이현은 물러서지 않는다."}
        opening_payload = {
            "readiness": {"status": "ready", "confidence": 0.9, "block_reasons": []},
            "chat_target": {"scope_key": scope_key, "display_name": "백이현"},
            "opening_scene": {"situation": "백이현이 봉인된 문서 앞에서 멈춘다."},
            "user_role": {"role_type": "임시 조력자"},
            "character_drive": {"immediate_objective": "문서의 흔적을 확인한다."},
            "agency_contract": {"character_moves_first": True},
            "progression_engine": {"short_term_goal": "봉인 문서를 확인한다."},
            "runtime_formula_seed": {
                "formula_type": "FORMULA_CASE_TO_NETWORK",
                "p_to_user_request": "문서 끈 방향과 문밖 발소리 중 하나를 먼저 확인하게 한다.",
                "user_task_type": "UT_INSPECT_CLUE",
                "user_task_success_condition": "유저가 끈 방향 또는 발소리 중 하나를 선택한다.",
                "protagonist_state_delta": "백이현이 선택된 단서에 따라 문서 또는 문밖을 먼저 확인한다.",
                "open_loop": "봉인 훼손자가 가까이에 있다는 압박이 남는다.",
                "mutation_policy": "MP_SAME_ASSET_NEW_CLUE",
            },
        }
        state_maps = {
            "character_rp_profile": {
                scope_key: {
                    "scope_key": scope_key,
                    "source_hash": "profile-hash",
                    "payload": profile_payload,
                }
            },
            "character_rp_examples": {
                scope_key: {
                    "scope_key": scope_key,
                    "source_hash": "examples-hash",
                    "payload": example_payload,
                }
            },
            "character_chat_internal_prompt": {
                scope_key: {
                    "scope_key": scope_key,
                    "source_hash": "internal-hash",
                    "payload": internal_prompt_payload,
                }
            },
        }
        request_mock = AsyncMock(return_value=opening_payload)
        upserted = []

        def fake_fetch_state_map(*, summary_type, **_kwargs):
            return state_maps.get(summary_type, {})

        def fake_upsert(_cur, **kwargs):
            upserted.append(kwargs)
            return 77, True

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "fetch_active_summary_state_map", side_effect=fake_fetch_state_map), \
             patch.object(module, "fetch_existing_summary", return_value=None), \
             patch.object(module, "request_character_chat_opening_payload", request_mock), \
             patch.object(module, "load_character_chat_scene_context_lines_by_scope", return_value={scope_key: ["- 1화 장면1: 압력=문서 봉인 | hook=흔적 확인"]}), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=fake_upsert), \
             patch.object(module, "deactivate_missing_active_scopes") as deactivate_missing:
            counts = await module.build_character_chat_opening_summaries(
                conn=conn,
                product_id=687,
                episode_rows=[],
                summary_client=object(),
                inventory_map={
                    scope_key: {
                        "canonical_character_key": scope_key,
                        "source_character_keys": ["protagonist:named:백이현"],
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 3,
                        "voice_evidence_count": 6,
                        "public_chat_eligible": True,
                    }
                },
                relation_map={},
            )

        self.assertEqual(counts, (1, 0))
        request_mock.assert_awaited_once()
        self.assertEqual(request_mock.await_args.kwargs["scene_context_lines"], ["- 1화 장면1: 압력=문서 봉인 | hook=흔적 확인"])
        self.assertEqual(len(upserted), 1)
        self.assertEqual(upserted[0]["summary_type"], "character_chat_opening_v1")
        self.assertEqual(upserted[0]["scope_key"], scope_key)
        saved_payload = json.loads(upserted[0]["summary_text"])
        self.assertEqual(saved_payload["chat_target"]["scope_key"], scope_key)
        deactivate_missing.assert_called_once()

    async def test_character_chat_opening_build_uses_legacy_alias_summary_rows(self):
        module = load_module()
        conn = FakeConnection()
        scope_key = "character:백이현"
        legacy_scope_key = "named:백이현"
        profile_payload = {
            "character_key": legacy_scope_key,
            "display_name": "백이현",
            "aliases": ["백이현"],
            "speech_style": {"tone": "단호"},
        }
        example_payload = {
            "character_key": legacy_scope_key,
            "examples": [{"episode_no": 1, "text": "나는 여기서 물러서지 않을 거야."}],
        }
        internal_prompt_payload = {"character_key": legacy_scope_key, "internal_prompt": "[핵심] 백이현은 물러서지 않는다."}
        opening_payload = {
            "readiness": {"status": "ready", "confidence": 0.9, "block_reasons": []},
            "chat_target": {"scope_key": scope_key, "display_name": "백이현"},
            "opening_scene": {"situation": "백이현이 봉인된 문서 앞에서 멈춘다."},
            "user_role": {"role_type": "임시 조력자"},
            "character_drive": {"immediate_objective": "문서의 흔적을 확인한다."},
            "agency_contract": {"character_moves_first": True},
            "progression_engine": {"short_term_goal": "봉인 문서를 확인한다."},
            "runtime_formula_seed": {
                "formula_type": "FORMULA_CASE_TO_NETWORK",
                "p_to_user_request": "문서 끈 방향과 문밖 발소리 중 하나를 먼저 확인하게 한다.",
                "user_task_type": "UT_INSPECT_CLUE",
                "user_task_success_condition": "유저가 끈 방향 또는 발소리 중 하나를 선택한다.",
                "protagonist_state_delta": "백이현이 선택된 단서에 따라 문서 또는 문밖을 먼저 확인한다.",
                "open_loop": "봉인 훼손자가 가까이에 있다는 압박이 남는다.",
                "mutation_policy": "MP_SAME_ASSET_NEW_CLUE",
            },
        }
        state_maps = {
            "character_rp_profile": {
                legacy_scope_key: {
                    "scope_key": legacy_scope_key,
                    "source_hash": "legacy-profile-hash",
                    "payload": profile_payload,
                }
            },
            "character_rp_examples": {
                legacy_scope_key: {
                    "scope_key": legacy_scope_key,
                    "source_hash": "legacy-examples-hash",
                    "payload": example_payload,
                }
            },
            "character_chat_internal_prompt": {
                legacy_scope_key: {
                    "scope_key": legacy_scope_key,
                    "source_hash": "legacy-internal-hash",
                    "payload": internal_prompt_payload,
                }
            },
        }
        request_mock = AsyncMock(return_value=opening_payload)
        upserted = []

        def fake_fetch_state_map(*, summary_type, **_kwargs):
            return state_maps.get(summary_type, {})

        def fake_upsert(_cur, **kwargs):
            upserted.append(kwargs)
            return 88, True

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "fetch_active_summary_state_map", side_effect=fake_fetch_state_map), \
             patch.object(module, "fetch_existing_summary", return_value=None), \
             patch.object(module, "request_character_chat_opening_payload", request_mock), \
             patch.object(module, "load_character_chat_scene_context_lines_by_scope", return_value={scope_key: ["- 1화 장면1: 압력=문서 봉인 | hook=흔적 확인"]}), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=fake_upsert), \
             patch.object(module, "deactivate_missing_active_scopes"):
            counts = await module.build_character_chat_opening_summaries(
                conn=conn,
                product_id=687,
                episode_rows=[],
                summary_client=object(),
                inventory_map={
                    scope_key: {
                        "canonical_character_key": scope_key,
                        "source_character_keys": [legacy_scope_key],
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 3,
                        "voice_evidence_count": 6,
                        "public_chat_eligible": True,
                    }
                },
                relation_map={},
            )

        self.assertEqual(counts, (1, 0))
        request_mock.assert_awaited_once()
        self.assertEqual(request_mock.await_args.kwargs["profile_payload"]["character_key"], scope_key)
        self.assertEqual(request_mock.await_args.kwargs["example_payload"]["character_key"], scope_key)
        self.assertEqual(request_mock.await_args.kwargs["internal_prompt_payload"]["character_key"], scope_key)
        self.assertEqual(request_mock.await_args.kwargs["scene_context_lines"], ["- 1화 장면1: 압력=문서 봉인 | hook=흔적 확인"])
        self.assertEqual(len(upserted), 1)
        self.assertEqual(upserted[0]["summary_type"], "character_chat_opening_v1")
        self.assertEqual(upserted[0]["scope_key"], scope_key)

    def test_opening_payload_normalization_rejects_scope_mismatch(self):
        module = load_module()

        normalized = module.normalize_character_chat_opening_payload(
            {
                "readiness": {"status": "ready"},
                "chat_target": {"scope_key": "character:다른인물", "display_name": "다른 인물"},
                "opening_scene": {"situation": "문 앞에서 멈춘다."},
                "user_role": {"role_type": "임시 조력자"},
                "character_drive": {"immediate_objective": "흔적을 확인한다."},
                "agency_contract": {"character_moves_first": True},
                "progression_engine": {"short_term_goal": "문을 확인한다."},
            },
            scope_key="character:백이현",
            display_name="백이현",
        )

        self.assertIsNone(normalized)

    async def test_character_chat_opening_regenerates_legacy_summary_without_runtime_formula_seed(self):
        module = load_module()
        conn = FakeConnection()
        scope_key = "character:백이현"
        profile_payload = {"character_key": scope_key, "display_name": "백이현"}
        example_payload = {"character_key": scope_key, "examples": [{"episode_no": 1, "text": "물러서지 않아."}]}
        internal_prompt_payload = {"internal_prompt": "[핵심] 백이현은 먼저 판단한다."}
        state_maps = {
            "character_rp_profile": {
                scope_key: {
                    "scope_key": scope_key,
                    "source_hash": "profile-hash",
                    "payload": profile_payload,
                }
            },
            "character_rp_examples": {
                scope_key: {
                    "scope_key": scope_key,
                    "source_hash": "examples-hash",
                    "payload": example_payload,
                }
            },
            "character_chat_internal_prompt": {
                scope_key: {
                    "scope_key": scope_key,
                    "source_hash": "internal-hash",
                    "payload": internal_prompt_payload,
                }
            },
        }
        existing_opening_payload = {
            "readiness": {"status": "ready", "confidence": 0.9, "block_reasons": []},
            "chat_target": {"scope_key": scope_key, "display_name": "백이현"},
            "opening_scene": {"situation": "백이현이 문서 앞에서 멈춘다."},
            "opening_message": {
                "narration": "봉인된 문서가 놓인 탁자 위로 낮은 등잔불이 흔들리고, 백이현은 손끝에 묻은 먹물을 닦지 않은 채 서류의 끊어진 끈을 내려다본다. 창밖에서는 발소리가 한 번 가까워졌다가 멎고, 젖은 종이 냄새와 식은 쇠 냄새가 좁은 방 안에 가라앉는다. 백이현은 먼저 문서 가장자리의 찢어진 방향을 확인하고, 봉인이 깨진 시점을 가늠하듯 숨을 낮춘다. 지금 봉인을 다시 묶으면 안쪽 기록이 사라질 수 있고, 문밖의 기척을 놓치면 누가 이 일을 벌였는지 알 수 없게 된다. 등잔불은 더 짧게 떨리고, 그의 손은 아직 문서에 닿지 않은 채 멈춰 있다.",
                "dialogue": "\"문서의 끈이 끊어진 방향과 문밖 발소리 중 하나를 먼저 확인해야 해. 어느 쪽이 더 급하다고 보지?\"",
                "opening_text": "봉인된 문서가 놓인 탁자 위로 낮은 등잔불이 흔들리고, 백이현은 손끝에 묻은 먹물을 닦지 않은 채 서류의 끊어진 끈을 내려다본다. 창밖에서는 발소리가 한 번 가까워졌다가 멎고, 젖은 종이 냄새와 식은 쇠 냄새가 좁은 방 안에 가라앉는다. 백이현은 먼저 문서 가장자리의 찢어진 방향을 확인하고, 봉인이 깨진 시점을 가늠하듯 숨을 낮춘다. 지금 봉인을 다시 묶으면 안쪽 기록이 사라질 수 있고, 문밖의 기척을 놓치면 누가 이 일을 벌였는지 알 수 없게 된다. 등잔불은 더 짧게 떨리고, 그의 손은 아직 문서에 닿지 않은 채 멈춰 있다.\n\n\"문서의 끈이 끊어진 방향과 문밖 발소리 중 하나를 먼저 확인해야 해. 어느 쪽이 더 급하다고 보지?\"",
                "user_objective": "문서의 끈 방향을 볼지 문밖 발소리를 확인할지 선택한다.",
            },
            "user_role": {"role_type": "임시 조력자"},
            "character_drive": {"immediate_objective": "봉인된 문서가 훼손된 이유를 확인한다."},
            "agency_contract": {"character_moves_first": True},
            "progression_engine": {"short_term_goal": "문서 훼손 단서를 확인한다."},
        }
        regenerated_opening_payload = dict(existing_opening_payload)
        regenerated_opening_payload["runtime_formula_seed"] = {
            "formula_type": "FORMULA_CASE_TO_NETWORK",
            "p_to_user_request": "문서 끈 방향과 문밖 발소리 중 하나를 먼저 확인하게 한다.",
            "user_task_type": "UT_INSPECT_CLUE",
            "user_task_success_condition": "유저가 끈 방향 또는 발소리 중 하나를 선택한다.",
            "protagonist_state_delta": "백이현이 선택된 단서에 따라 문서 또는 문밖을 먼저 확인한다.",
            "open_loop": "봉인 훼손자가 가까이에 있다는 압박이 남는다.",
            "mutation_policy": "MP_SAME_ASSET_NEW_CLUE",
        }
        upserted = []

        def fake_fetch_state_map(*, summary_type, **_kwargs):
            return state_maps.get(summary_type, {})

        def fake_upsert(_cur, **kwargs):
            upserted.append(kwargs)
            return 92, True

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "fetch_active_summary_state_map", side_effect=fake_fetch_state_map), \
             patch.object(
                 module,
                 "fetch_existing_summary",
                 return_value={"summary_id": 91, "summary_text": json.dumps(existing_opening_payload, ensure_ascii=False)},
             ), \
             patch.object(module, "activate_existing_summary") as activate_existing, \
             patch.object(module, "request_character_chat_opening_payload", AsyncMock(return_value=regenerated_opening_payload)) as request_mock, \
             patch.object(module, "load_character_chat_scene_context_lines_by_scope", return_value={scope_key: ["- 1화 장면1: 압력=문서 봉인"]}), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=fake_upsert) as upsert_mock, \
             patch.object(module, "deactivate_missing_active_scopes"):
            counts = await module.build_character_chat_opening_summaries(
                conn=conn,
                product_id=687,
                episode_rows=[],
                summary_client=object(),
                inventory_map={
                    scope_key: {
                        "canonical_character_key": scope_key,
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 3,
                        "voice_evidence_count": 6,
                    }
                },
                relation_map={},
            )

        self.assertEqual(counts, (1, 0))
        request_mock.assert_awaited_once()
        upsert_mock.assert_called_once()
        activate_existing.assert_not_called()
        self.assertEqual(json.loads(upserted[0]["summary_text"])["runtime_formula_seed"]["user_task_type"], "UT_INSPECT_CLUE")

    async def test_rp_build_preserves_keep_old_scope_when_another_v3_target_succeeds(self):
        module = load_module()
        conn = FakeConnection()
        episode_texts_by_no = {
            1: "\n".join(
                [
                    '백이현이 말했다. "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해."',
                    '백이현이 낮게 물었다. "그 말이 사실이라면 지금 당장 증거를 보여 줘."',
                    '백이현은 고개를 저으며 말했다. "아직 끝난 게 아니야, 내가 직접 확인하겠어."',
                ]
            ),
            2: "\n".join(
                [
                    '백이현이 숨을 고르며 답했다. "겁먹을 시간은 없어, 먼저 사람들을 빼내."',
                    '백이현이 검을 세우며 말했다. "네가 막는다면 나도 돌아가지 않겠어."',
                    '백이현이 짧게 웃었다. "좋아, 이번엔 네 방식대로 움직여 보자."',
                ]
            ),
            3: "\n".join(
                [
                    '백이현이 문서를 접으며 말했다. "이 기록은 내가 맡을게, 누구에게도 넘기지 마."',
                    '백이현이 뒤돌아서며 말했다. "따라오지 마, 여기서부터는 내가 정리한다."',
                    '백이현이 조용히 말했다. "약속은 지킬 거야, 대신 너도 물러서지 마."',
                ]
            ),
            4: "김도윤은 말없이 장면 밖에 머물렀다.",
        }
        profile_payload = {
            "speech_style": {"tone": "단호"},
            "personality_core": ["원칙적"],
            "baseline_attitude": "경계",
            "example_dialogues": [
                "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해.",
                "겁먹을 시간은 없어, 먼저 사람들을 빼내.",
                "이 기록은 내가 맡을게, 누구에게도 넘기지 마.",
            ],
        }

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_rp_character_plan_payload", AsyncMock(return_value={"characters": []})), \
             patch.object(module, "collect_llm_rp_dialogue_items", AsyncMock(return_value=[])), \
             patch.object(module, "request_rp_profile_payload", AsyncMock(return_value=profile_payload)), \
             patch.object(module, "fetch_active_summary_state_map", return_value={}), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=[({"summary_id": 1}, True), ({"summary_id": 2}, True)]), \
             patch.object(module, "deactivate_missing_active_scopes") as deactivate_missing:
            counts = await module.build_rp_summaries(
                conn,
                product_id=687,
                episode_rows=[],
                episode_texts_by_no=episode_texts_by_no,
                summary_client=object(),
                inventory_map={
                    "character:백이현": {
                        "canonical_character_key": "character:백이현",
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 3,
                        "voice_evidence_count": 9,
                        "evidence_episode_nos": [1, 2, 3],
                    },
                    "character:김도윤": {
                        "canonical_character_key": "character:김도윤",
                        "display_name": "김도윤",
                        "aliases": ["김도윤"],
                        "entity_kind": "person",
                        "distinct_episode_count": 1,
                        "voice_evidence_count": 1,
                        "evidence_episode_nos": [4],
                    },
                },
            )

        self.assertEqual(counts, {"profile": (1, 0), "examples": (1, 0)})
        expected_scope_keys = {"character:백이현", "character:김도윤"}
        deactivate_missing.assert_any_call(ANY, 687, "character_rp_profile", expected_scope_keys)
        deactivate_missing.assert_any_call(ANY, 687, "character_rp_examples", expected_scope_keys)

    async def test_rp_build_skips_cleanup_when_all_v3_targets_keep_old(self):
        module = load_module()
        conn = FakeConnection()

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_rp_character_plan_payload", AsyncMock(return_value={"characters": []})), \
             patch.object(module, "collect_llm_rp_dialogue_items", AsyncMock(return_value=[])), \
             patch.object(module, "fetch_active_summary_state_map", return_value={}), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "deactivate_missing_active_scopes") as deactivate_missing:
            counts = await module.build_rp_summaries(
                conn,
                product_id=687,
                episode_rows=[],
                episode_texts_by_no={1: "김도윤은 말없이 장면 밖에 머물렀다."},
                summary_client=object(),
                inventory_map={
                    "character:김도윤": {
                        "canonical_character_key": "character:김도윤",
                        "display_name": "김도윤",
                        "aliases": ["김도윤"],
                        "entity_kind": "person",
                        "distinct_episode_count": 1,
                        "voice_evidence_count": 1,
                        "evidence_episode_nos": [1],
                    }
                },
            )

        self.assertEqual(counts, {"profile": (0, 0), "examples": (0, 0)})
        deactivate_missing.assert_not_called()
        self.assertEqual(conn.commit_count, 0)

    async def test_rp_build_uses_gemma_exact_dialogue_when_rule_based_voice_is_not_ready(self):
        module = load_module()
        conn = FakeConnection()
        episode_texts_by_no = {
            1: '그는 고개를 들었다. "나는 여기서 물러서지 않아, 끝까지 확인하고 책임까지 지겠어." 잠시 뒤 다시 말했다. "네가 숨긴 기록부터 내 앞에 내놔, 판단은 그 다음에 하겠다."',
            2: '상대가 물러서자 그가 답했다. "겁먹을 시간은 없어, 먼저 사람들을 빼내고 문을 봉쇄해." 그리고 낮게 덧붙였다. "내가 맡을 테니 너는 문을 막아, 뒤는 돌아보지 마."',
            3: '침묵 끝에 목소리가 떨어졌다. "약속은 지킬 거야, 대신 너도 여기서 물러서지 마." 곧이어 이어졌다. "이 기록은 내가 맡을게, 누구에게도 넘기지 말고 기다려."',
            4: '마지막 문 앞에서 그가 웃었다. "좋아, 이번엔 네 방식대로 움직여 보자, 대신 신호는 내가 낸다." 숨을 고른 뒤 말했다. "따라오지 마, 여기서부터는 내가 정리하고 끝내겠다."',
        }
        llm_items = [
            {"episode_no": 1, "kind": "dialogue", "text": "나는 여기서 물러서지 않아, 끝까지 확인하고 책임까지 지겠어.", "confidence": 0.95},
            {"episode_no": 1, "kind": "dialogue", "text": "네가 숨긴 기록부터 내 앞에 내놔, 판단은 그 다음에 하겠다.", "confidence": 0.95},
            {"episode_no": 2, "kind": "dialogue", "text": "겁먹을 시간은 없어, 먼저 사람들을 빼내고 문을 봉쇄해.", "confidence": 0.95},
            {"episode_no": 2, "kind": "dialogue", "text": "내가 맡을 테니 너는 문을 막아, 뒤는 돌아보지 마.", "confidence": 0.95},
            {"episode_no": 3, "kind": "dialogue", "text": "약속은 지킬 거야, 대신 너도 여기서 물러서지 마.", "confidence": 0.95},
            {"episode_no": 3, "kind": "dialogue", "text": "이 기록은 내가 맡을게, 누구에게도 넘기지 말고 기다려.", "confidence": 0.95},
            {"episode_no": 4, "kind": "dialogue", "text": "좋아, 이번엔 네 방식대로 움직여 보자, 대신 신호는 내가 낸다.", "confidence": 0.95},
            {"episode_no": 4, "kind": "dialogue", "text": "따라오지 마, 여기서부터는 내가 정리하고 끝내겠다.", "confidence": 0.95},
        ]
        profile_payload = {
            "speech_style": {"tone": "단호"},
            "personality_core": ["책임감"],
            "baseline_attitude": "경계",
            "example_dialogues": [
                "나는 여기서 물러서지 않아, 끝까지 확인하고 책임까지 지겠어.",
                "겁먹을 시간은 없어, 먼저 사람들을 빼내고 문을 봉쇄해.",
                "따라오지 마, 여기서부터는 내가 정리하고 끝내겠다.",
            ],
        }
        plan_mock = AsyncMock(return_value={"characters": []})
        dialogue_mock = AsyncMock(return_value=llm_items)
        profile_mock = AsyncMock(return_value=profile_payload)
        self.assertTrue(module.is_strict_dialogue_item_set_ready(llm_items, ["백이현"]))

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "request_rp_character_plan_payload", plan_mock), \
             patch.object(module, "request_rp_dialogue_items", dialogue_mock), \
             patch.object(module, "request_rp_profile_payload", profile_mock), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=[({"summary_id": 1}, True), ({"summary_id": 2}, True)]), \
             patch.object(module, "deactivate_missing_active_scopes"):
            counts = await module.build_rp_summaries(
                conn,
                product_id=687,
                episode_rows=[],
                episode_texts_by_no=episode_texts_by_no,
                summary_client=object(),
                inventory_map={
                    "character:백이현": {
                        "canonical_character_key": "character:백이현",
                        "source_character_keys": ["protagonist:named:백이현"],
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 4,
                        "voice_evidence_count": 4,
                        "evidence_episode_nos": [1, 2, 3, 4],
                    }
                },
            )

        self.assertEqual(counts, {"profile": (1, 0), "examples": (1, 0)})
        plan_mock.assert_not_called()
        dialogue_mock.assert_awaited_once()
        profile_mock.assert_awaited_once()

    async def test_rp_build_keeps_enough_verified_rule_based_examples_below_strict_voice_gate(self):
        module = load_module()
        conn = FakeConnection()
        dialogue_items = [
            {
                "episode_no": episode_no,
                "kind": "dialogue",
                "text": f"검증된 원문 대사 {episode_no}입니다.",
                "is_example_candidate": True,
            }
            for episode_no in range(1, 6)
        ]
        profile_payload = {
            "speech_style": {"tone": "단호"},
            "personality_core": ["책임감"],
            "baseline_attitude": "경계",
            "example_dialogues": [item["text"] for item in dialogue_items[:3]],
        }

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "RP_OPENROUTER_MODEL", "google/gemma-4-31b-it"), \
             patch.object(module, "build_direct_voice_evidence_quality", return_value={"strict_chat_ready": False, "status": "direct_limited"}), \
             patch.object(module, "collect_rule_based_rp_dialogue_items_by_episode", return_value=dialogue_items), \
             patch.object(module, "collect_llm_rp_dialogue_items", AsyncMock(return_value=[])), \
             patch.object(module, "request_rp_profile_payload", AsyncMock(return_value=profile_payload)), \
             patch.object(module, "fetch_active_summary_state_map", return_value={}), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "upsert_summary", side_effect=[({"summary_id": 1}, True), ({"summary_id": 2}, True)]), \
             patch.object(module, "deactivate_missing_active_scopes"):
            counts = await module.build_rp_summaries(
                conn,
                product_id=687,
                episode_rows=[],
                episode_texts_by_no={episode_no: item["text"] for episode_no, item in enumerate(dialogue_items, 1)},
                summary_client=object(),
                inventory_map={
                    "character:백이현": {
                        "canonical_character_key": "character:백이현",
                        "display_name": "백이현",
                        "aliases": ["백이현"],
                        "is_protagonist": True,
                        "distinct_episode_count": 5,
                    }
                },
            )

        self.assertEqual(counts, {"profile": (1, 0), "examples": (1, 0)})

    def test_safe_main_protagonist_remains_public_without_summary_voice_label(self):
        module = load_module()
        protagonist = {
            "canonical_character_key": "character:환진",
            "display_name": "환진",
            "identity_status": "RESOLVED_NAMED",
            "identity_conflict_reasons": [],
            "entity_kind": "person",
            "work_role": "main_protagonist",
            "is_protagonist": True,
            "distinct_episode_count": 14,
            "voice_mode_counts": {"dialogue": 0, "monologue": 0, "narration_only": 14},
            "relation_episode_count": 0,
            "rp_signal_quality": {
                "status": "insufficient",
                "needs_review": False,
            },
            "display_safety": {
                "status": "pass",
                "reason": "resolved_named_identity",
            },
        }

        self.assertTrue(module.is_public_chat_inventory_candidate(protagonist))
        self.assertTrue(module.is_public_slot_inventory_candidate(protagonist))


class StoryAgentContextDeltaValidationTest(IsolatedAsyncioTestCase):
    def test_mark_failure_preserves_last_ready_context_status(self):
        module = load_module()
        cursor = MagicMock()
        cursor.fetchone.return_value = {"ready_episode_count": 7}
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor

        with patch.object(module, "db_connect", return_value=conn):
            ready_episode_count = module.mark_product_context_failed(
                product_id=687,
                total_episode_count=8,
                error_message="refresh failed",
            )

        self.assertEqual(ready_episode_count, 7)
        update_sql = " ".join(cursor.execute.call_args_list[1].args[0].split())
        self.assertIn("context_status = IF(", update_sql)
        self.assertIn(
            "context_status = 'ready' AND VALUES(ready_episode_count) > 0",
            update_sql,
        )
        self.assertIn(
            "last_error_message = IF(context_status = 'disabled', last_error_message, VALUES(last_error_message))",
            update_sql,
        )
        conn.commit.assert_called_once_with()
        conn.close.assert_called_once_with()

    def test_product_progress_uses_contiguous_public_episode_frontier(self):
        module = load_module()
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "ready_episode_count": 7,
            "current_context_status": "processing",
        }

        ready_episode_no, context_status = module.fetch_product_context_progress(
            cursor,
            product_id=687,
        )

        self.assertEqual(ready_episode_no, 7)
        self.assertEqual(context_status, "processing")
        query = " ".join(cursor.execute.call_args.args[0].split())
        self.assertIn("MAX(ready_episode.episode_no)", query)
        self.assertIn("NOT EXISTS", query)
        self.assertIn(
            "prefix_episode.episode_no <= ready_episode.episode_no",
            query,
        )
        self.assertIn("prefix_summary.summary_id IS NULL", query)

    def test_refresh_preserves_ready_status_while_new_episodes_sync(self):
        module = load_module()
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "ready_episode_count": 7,
            "current_context_status": "ready",
        }

        status_row = module.refresh_product_context_status(
            cursor,
            product_id=687,
            total_episode_count=8,
        )

        self.assertEqual(status_row["context_status"], "ready")
        select_sql = " ".join(cursor.execute.call_args_list[0].args[0].split())
        self.assertIn("current_context_status", select_sql)
        insert_params = cursor.execute.call_args_list[1].args[1]
        self.assertEqual(insert_params[1], "ready")

    def test_refresh_keeps_never_ready_context_processing(self):
        module = load_module()
        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "ready_episode_count": 7,
            "current_context_status": "processing",
        }

        status_row = module.refresh_product_context_status(
            cursor,
            product_id=687,
            total_episode_count=8,
        )

        self.assertEqual(status_row["context_status"], "processing")

    def test_fetch_active_character_inventory_map_accepts_v3_summary_type(self):
        module = load_module()
        cur = object()

        with patch.object(
            module,
            "fetch_active_summary_rows",
            return_value=[
                {
                    "scope_key": "character:백이현",
                    "summary_text": '{"display_name":"백이현"}',
                }
            ],
        ) as fetch_rows:
            inventory = module.fetch_active_character_inventory_map(
                cur,
                product_id=687,
                summary_type="character_inventory_v3",
            )

        fetch_rows.assert_called_once_with(cur=cur, product_id=687, summary_type="character_inventory_v3")
        self.assertEqual(inventory, {"character:백이현": {"display_name": "백이현"}})

    def test_foundation_invariant_requires_character_inventory_v3(self):
        module = load_module()
        missing_v3_cursor = FakeRowsCursor(
            [
                {
                    "episode_summary_count": 3,
                    "signal_count": 3,
                    "inventory_count": 1,
                    "inventory_v3_count": 0,
                    "missing_required_signal_count": 0,
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "character_inventory_v3=0"):
            module.assert_story_agent_foundation_invariants(missing_v3_cursor, product_id=687)

        ready_cursor = FakeRowsCursor(
            [
                {
                    "episode_summary_count": 3,
                    "signal_count": 3,
                    "inventory_count": 1,
                    "inventory_v3_count": 1,
                    "missing_required_signal_count": 0,
                }
            ]
        )
        module.assert_story_agent_foundation_invariants(ready_cursor, product_id=687)
        self.assertIn("character_inventory_v3", ready_cursor.query)

    def test_delta_exit_code_is_nonzero_when_apply_product_failed(self):
        module = load_module()
        results = module.build_empty_results()
        results["products"] = [
            {
                "product_id": 687,
                "context_status": "failed",
                "ready_episode_count": 3,
                "total_episode_count": 5,
            }
        ]

        self.assertEqual(module.build_delta_exit_code(results, apply=True), 1)
        self.assertEqual(module.build_delta_exit_code(results, apply=False), 0)

        results["products"][0]["context_status"] = "ready"
        self.assertEqual(module.build_delta_exit_code(results, apply=True), 0)

        results["products"][0]["character_chat_asset_readiness"] = {
            "character_chat_status": "ready",
            "public_candidate_count": 2,
            "ready_public_candidate_count": 1,
            "block_reason_counts": {
                "legacy_profile_scope_key_mismatch": 1,
            },
        }
        self.assertEqual(module.build_delta_exit_code(results, apply=True), 0)

        results["character_asset_repair_failed"] = 1
        self.assertEqual(module.build_delta_exit_code(results, apply=True), 1)

    def test_product_result_merge_does_not_downgrade_failed_or_review_required(self):
        module = load_module()
        failed_products = [
            {
                "product_id": 687,
                "context_status": "failed",
                "total_episode_count": 5,
                "ready_episode_count": 3,
            }
        ]

        module.merge_story_agent_product_result(
            failed_products,
            {
                "product_id": 687,
                "context_status": "ready",
                "total_episode_count": 5,
                "ready_episode_count": 5,
                "character_asset_repair": {"status": "no_progress"},
            },
        )

        self.assertEqual(failed_products[0]["context_status"], "failed")
        self.assertEqual(failed_products[0]["persisted_context_status"], "ready")
        self.assertEqual(
            failed_products[0]["character_asset_repair"],
            {"status": "no_progress"},
        )

        review_required_products = [
            {
                "product_id": 688,
                "context_status": "review_required",
                "persisted_context_status": "ready",
                "total_episode_count": 8,
                "ready_episode_count": 8,
            }
        ]
        module.merge_story_agent_product_result(
            review_required_products,
            {
                "product_id": 688,
                "context_status": "deferred_budget",
                "persisted_context_status": "ready",
                "total_episode_count": 8,
                "ready_episode_count": 8,
            },
        )

        self.assertEqual(
            review_required_products[0]["context_status"],
            "review_required",
        )
        self.assertEqual(
            review_required_products[0]["persisted_context_status"],
            "ready",
        )

    def test_identity_dependent_rows_exclude_only_review_required_products(self):
        module = load_module()
        results = module.build_empty_results()
        results["products"] = [
            {"product_id": 1149, "context_status": "review_required"},
            {"product_id": 1109, "context_status": "ready"},
            {"product_id": 1207, "context_status": "failed"},
        ]
        rows = [
            {"product_id": 1149, "title": "stale review"},
            {"product_id": 1109, "title": "fresh review"},
            {"product_id": 1207, "title": "hard failure"},
        ]

        filtered = module.filter_review_required_product_rows(
            rows,
            results=results,
        )

        self.assertEqual(
            [row["product_id"] for row in filtered],
            [1109, 1207],
        )

    def test_delta_exit_code_reports_budget_deferral_without_failure(self):
        module = load_module()
        results = module.build_empty_results()
        results["deferred_budget"] = 1
        results["products"] = [
            {
                "product_id": 687,
                "context_status": "deferred_budget",
                "ready_episode_count": 12,
                "total_episode_count": 30,
            }
        ]

        self.assertEqual(
            module.build_delta_exit_code(results, apply=True),
            module.STORYCTX_DEFERRED_BUDGET_EXIT_CODE,
        )
        self.assertEqual(module.build_delta_exit_code(results, apply=False), 0)

    def test_character_asset_repair_plan_routes_only_safe_scopes(self):
        module = load_module()
        plan = module.build_character_chat_asset_repair_plan(
            {
                "missing_profile_scope_keys": ["character:main", "character:ambiguous"],
                "missing_examples_scope_keys": ["character:main"],
                "legacy_profile_scope_key_mismatch_scope_keys": ["character:legacy"],
                "missing_usable_scene_scope_keys": ["character:main", "character:ambiguous"],
                "continuity_ambiguous_scope_keys": ["character:ambiguous"],
            }
        )

        self.assertEqual(
            plan["rp_scope_keys"],
            ["character:legacy", "character:main"],
        )
        self.assertEqual(plan["scene_scope_keys"], ["character:main"])
        self.assertEqual(plan["blocked_scope_keys"], ["character:ambiguous"])
        self.assertTrue(plan["repairable"])

    def test_character_asset_repair_plan_can_repair_nonblocking_co_main(self):
        module = load_module()
        plan = module.build_character_chat_asset_repair_plan(
            {
                "missing_profile_scope_keys": ["character:co-main"],
                "missing_examples_scope_keys": ["character:co-main"],
                "continuity_ambiguous_scope_keys": ["character:co-main"],
                "blocking_continuity_ambiguous_scope_keys": [],
            }
        )

        self.assertEqual(plan["blocked_scope_keys"], [])
        self.assertEqual(plan["rp_scope_keys"], ["character:co-main"])
        self.assertTrue(plan["repairable"])

    def test_character_asset_repair_plan_excludes_over_cap_only_character(self):
        module = load_module()
        repair_plan = {
            "rp_scope_keys": ["character:main", "character:late"],
            "scene_scope_keys": ["character:main", "character:late"],
            "blocked_scope_keys": [],
            "repairable": True,
        }
        signal_rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:main",
                        display_name="주인공",
                    )
                ],
            )
        ]
        inventory_map = {
            "character:main": {"source_character_keys": ["named:main"]},
            "character:late": {"source_character_keys": ["named:late"]},
        }

        filtered = module.filter_character_chat_asset_repair_plan_to_signal_scope(
            repair_plan=repair_plan,
            signal_rows=signal_rows,
            inventory_map=inventory_map,
        )

        self.assertEqual(filtered["rp_scope_keys"], ["character:main"])
        self.assertEqual(filtered["scene_scope_keys"], ["character:main"])
        self.assertTrue(filtered["repairable"])

    def test_provider_inventory_map_excludes_over_cap_only_character(self):
        module = load_module()
        signal_rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:main",
                        display_name="주인공",
                    )
                ],
            )
        ]
        inventory_map = {
            "character:main": {"source_character_keys": ["named:main"]},
            "character:late": {"source_character_keys": ["named:late"]},
        }

        filtered = module.filter_character_inventory_map_to_signal_scope(
            inventory_map=inventory_map,
            signal_rows=signal_rows,
        )

        self.assertEqual(filtered, {"character:main": inventory_map["character:main"]})

    def test_character_scene_context_loader_uses_first_thirty_public_episodes(self):
        module = load_module()

        class PingConnection:
            def ping(self, reconnect=False):
                return None

        capped_scene_rows = [
            {
                "scope_key": "episode:130",
                "episode_from": 30,
                "summary_text": '{"episode_no":30,"scenes":[]}',
            }
        ]
        with patch.object(
            module,
            "fetch_active_character_asset_summary_rows",
            return_value=capped_scene_rows,
        ) as capped_fetch, patch.object(
            module,
            "fetch_active_summary_rows",
        ) as uncapped_fetch, patch.object(
            module,
            "work_cursor",
            fake_work_cursor,
        ):
            module.load_character_chat_scene_context_lines_by_scope(
                PingConnection(),
                product_id=687,
            )

        capped_fetch.assert_called_once_with(
            cur=ANY,
            product_id=687,
            summary_type="episode_scene_extraction",
        )
        uncapped_fetch.assert_not_called()

    def test_scene_repair_selection_prioritizes_main_and_caps_rows(self):
        module = load_module()
        rows, required = module.select_character_chat_scene_repair_rows(
            inventory_map={
                "character:main": {
                    "work_role": "main_protagonist",
                    "evidence_episode_nos": [1, 3],
                },
                "character:support": {
                    "work_role": "supporting",
                    "evidence_episode_nos": [2],
                },
            },
            episode_summary_rows=[
                {"episode_from": 1, "scope_key": "episode:101"},
                {"episode_from": 2, "scope_key": "episode:102"},
                {"episode_from": 3, "scope_key": "episode:103"},
            ],
            scene_scope_keys={"character:main", "character:support"},
            limit=1,
        )

        self.assertEqual([row["episode_from"] for row in rows], [3])
        self.assertEqual(required, {3: {"character:main"}})

    async def test_character_asset_repair_only_run_reports_budget_deferral(self):
        module = load_module()
        conn = FakeConnection()
        client = FakeCreditAsyncClient(total_credits=20.0, total_usage=16.5)
        results = module.build_empty_results()

        with patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
             patch.object(module, "AsyncClient", return_value=client), \
             patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "fetch_total_episode_count", return_value=30), \
             patch.object(module, "fetch_product_ready_episode_count", return_value=12), \
             patch.object(module, "fetch_product_context_status", return_value="ready"), \
             patch.object(module, "product_lock_connection") as product_lock:
            await module.repair_character_chat_assets(
                rows=[
                    {
                        "product_id": 687,
                        "title": "테스트 작품",
                        "character_asset_collection_eligible": 1,
                    }
                ],
                args=SimpleNamespace(apply=True, verbose=False),
                results=results,
            )

        self.assertEqual(results["deferred_budget"], 1)
        self.assertEqual(
            results["character_asset_repairs"],
            [{"product_id": 687, "status": "deferred_budget"}],
        )
        self.assertEqual(results["products"][0]["persisted_context_status"], "ready")
        self.assertEqual(
            module.build_delta_exit_code(results, apply=True),
            module.STORYCTX_DEFERRED_BUDGET_EXIT_CODE,
        )
        self.assertTrue(client.closed)
        product_lock.assert_not_called()

    async def test_character_asset_repair_runs_without_foundation_delta_or_provider_preflight(self):
        module = load_module()
        conn = FakeConnection()
        results = module.build_empty_results()
        scope_key = "character:main"
        before_readiness = {
            "character_chat_status": "hold",
            "public_candidate_count": 1,
            "missing_profile_scope_keys": [scope_key],
            "missing_examples_scope_keys": [scope_key],
            "missing_usable_scene_scope_keys": [scope_key],
        }
        after_readiness = {
            "character_chat_status": "ready",
            "public_candidate_count": 1,
            "ready_scope_keys": [scope_key],
        }
        inventory_map = {
            scope_key: {
                "canonical_character_key": scope_key,
                "display_name": "데시",
                "work_role": "main_protagonist",
                "is_protagonist": True,
                "evidence_episode_nos": [1],
            }
        }
        episode_rows = [
            {
                "summary_id": 1,
                "scope_key": "episode:101",
                "episode_from": 1,
                "source_hash": "summary-hash",
                "summary_text": "[1화] 테스트",
            }
        ]
        scene_builder = AsyncMock(return_value=(1, 0))
        rp_builder = AsyncMock(
            return_value={"profile": [1, 0], "examples": [1, 0]}
        )
        preflight = AsyncMock()

        with patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module.settings, "ANTHROPIC_API_KEY", ""), \
             patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())), \
             patch.object(module, "fetch_total_episode_count", return_value=1), \
             patch.object(module, "fetch_product_context_status", return_value="ready"), \
             patch.object(module, "fetch_product_ready_episode_count", return_value=1), \
             patch.object(
                 module,
                 "fetch_character_chat_asset_readiness_verification",
                 side_effect=[before_readiness, after_readiness],
             ), \
             patch.object(module, "fetch_character_identity_review", return_value=None), \
             patch.object(module, "fetch_active_character_inventory_map", return_value=inventory_map), \
             patch.object(
                 module,
                 "fetch_active_character_asset_summary_rows",
                 side_effect=[
                     [signal_row(1, 1, [signal_character(character_key=scope_key, display_name="데시")])],
                     episode_rows,
                 ],
             ), \
             patch.object(module, "fetch_active_episode_texts_by_no", return_value={1: "데시가 문을 연다."}), \
             patch.object(module, "fetch_active_relation_inventory_map", return_value={}), \
             patch.object(module, "fetch_rp_ready_character_inventory_history_state_map", return_value={}), \
             patch.object(module, "build_episode_scene_extraction_summaries", scene_builder), \
             patch.object(module, "build_rp_summaries_delta", rp_builder), \
             patch.object(module, "touch_product_context_build_attempt") as touch, \
             patch.object(module, "assert_storyctx_apply_providers_ready", preflight):
            await module.repair_character_chat_assets(
                rows=[{"product_id": 687, "title": "테스트 작품", "_character_asset_collection_eligible": True}],
                args=SimpleNamespace(
                    apply=True,
                    verbose=False,
                    max_delta_episodes=2,
                ),
                results=results,
            )

        preflight.assert_not_awaited()
        scene_builder.assert_awaited_once()
        rp_builder.assert_awaited_once()
        self.assertTrue(scene_builder.await_args.kwargs["raise_unexpected_errors"])
        self.assertTrue(rp_builder.await_args.kwargs["raise_unexpected_errors"])
        touch.assert_called_once()
        self.assertEqual(results["character_asset_repair_attempted"], 1)
        self.assertEqual(results["character_asset_repair_recovered"], 1)
        self.assertEqual(results["character_asset_repair_failed"], 0)
        self.assertEqual(results["products"][0]["context_status"], "ready")
        self.assertEqual(module.build_delta_exit_code(results, apply=True), 0)

    async def test_character_asset_repair_stale_review_stops_before_identity_writes(self):
        module = load_module()
        conn = FakeConnection()
        results = module.build_empty_results()
        stale_error = module.CharacterIdentityReviewStaleError(
            "stale character identity review signal: confirm-main summary_id=1",
            product_id=1176,
            operation_id="confirm-main",
            reason_code="signal_anchor_changed",
        )
        scene_builder = AsyncMock()
        rp_builder = AsyncMock()

        with patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module.settings, "ANTHROPIC_API_KEY", ""), \
             patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())), \
             patch.object(module, "fetch_total_episode_count", return_value=69), \
             patch.object(module, "fetch_product_context_status", return_value="ready"), \
             patch.object(module, "fetch_product_ready_episode_count", return_value=69), \
             patch.object(module, "fetch_active_character_asset_summary_rows", return_value=[signal_row(1, 1, [])]), \
             patch.object(module, "fetch_character_identity_review", side_effect=stale_error) as review_fetch, \
             patch.object(module, "fetch_character_chat_asset_readiness_verification") as readiness, \
             patch.object(module, "build_episode_scene_extraction_summaries", scene_builder), \
             patch.object(module, "build_rp_summaries_delta", rp_builder), \
             patch.object(module, "touch_product_context_build_attempt") as touch:
            await module.repair_character_chat_assets(
                rows=[
                    {
                        "product_id": 1176,
                        "title": "테스트 작품",
                        "_character_asset_collection_eligible": True,
                    }
                ],
                args=SimpleNamespace(
                    apply=True,
                    verbose=False,
                    max_delta_episodes=2,
                ),
                results=results,
            )

        review_fetch.assert_called_once()
        readiness.assert_not_called()
        scene_builder.assert_not_awaited()
        rp_builder.assert_not_awaited()
        touch.assert_not_called()
        self.assertEqual(conn.rollback_count, 2)
        self.assertEqual(results["character_asset_repair_failed"], 0)
        self.assertEqual(results["review_required"], 1)
        self.assertEqual(
            results["character_asset_repairs"][0]["status"],
            "review_required",
        )
        self.assertEqual(results["products"][0]["context_status"], "review_required")
        self.assertEqual(results["products"][0]["persisted_context_status"], "ready")
        self.assertEqual(
            module.build_delta_exit_code(results, apply=True),
            module.STORYCTX_REVIEW_REQUIRED_EXIT_CODE,
        )

    async def test_character_asset_repair_skips_out_of_cohort_product(self):
        module = load_module()
        conn = FakeConnection()
        results = module.build_empty_results()
        scene_builder = AsyncMock()
        rp_builder = AsyncMock()

        with patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module.settings, "ANTHROPIC_API_KEY", ""), \
             patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "product_lock_connection") as product_lock, \
             patch.object(module, "build_episode_scene_extraction_summaries", scene_builder), \
             patch.object(module, "build_rp_summaries_delta", rp_builder):
            await module.repair_character_chat_assets(
                rows=[{"product_id": 787, "title": "grandfather 작품", "_character_asset_collection_eligible": False}],
                args=SimpleNamespace(apply=True, verbose=False, max_delta_episodes=2),
                results=results,
            )

        product_lock.assert_not_called()
        scene_builder.assert_not_awaited()
        rp_builder.assert_not_awaited()
        self.assertEqual(results["character_asset_repair_attempted"], 0)
        self.assertEqual(
            results["character_asset_repairs"],
            [{"product_id": 787, "status": "skipped_cohort"}],
        )
        self.assertEqual(module.build_delta_exit_code(results, apply=True), 0)

    async def test_character_asset_repair_midrun_reserve_exhaustion_is_deferred(self):
        module = load_module()
        conn = FakeConnection()
        results = module.build_empty_results()
        scope_key = "character:main"
        before_readiness = {
            "character_chat_status": "hold",
            "public_candidate_count": 1,
            "missing_usable_scene_scope_keys": [scope_key],
        }
        reserve_error = module.OpenRouterBackgroundCreditReserveError(
            "background credit reserve blocked"
        )
        touch = MagicMock()

        with patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module.settings, "ANTHROPIC_API_KEY", ""), \
             patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())), \
             patch.object(module, "fetch_total_episode_count", return_value=30), \
             patch.object(module, "fetch_product_context_status", return_value="ready"), \
             patch.object(module, "fetch_product_ready_episode_count", return_value=12), \
             patch.object(module, "fetch_character_chat_asset_readiness_verification", return_value=before_readiness), \
             patch.object(module, "fetch_character_identity_review", return_value=None), \
             patch.object(module, "fetch_active_character_inventory_map", return_value={scope_key: {"canonical_character_key": scope_key, "display_name": "데시", "work_role": "main_protagonist", "is_protagonist": True, "evidence_episode_nos": [1]} }), \
             patch.object(
                 module,
                 "fetch_active_character_asset_summary_rows",
                 side_effect=[
                     [signal_row(1, 1, [signal_character(character_key=scope_key, display_name="데시")])],
                     [{"summary_id": 1, "scope_key": "episode:101", "episode_from": 1, "source_hash": "summary-hash", "summary_text": "[1화] 테스트"}],
                 ],
             ), \
             patch.object(module, "fetch_active_episode_texts_by_no", return_value={1: "데시가 문을 연다."}), \
             patch.object(module, "fetch_active_relation_inventory_map", return_value={}), \
             patch.object(module, "fetch_rp_ready_character_inventory_history_state_map", return_value={}), \
             patch.object(module, "build_episode_scene_extraction_summaries", AsyncMock(side_effect=reserve_error)), \
             patch.object(module, "build_rp_summaries_delta", AsyncMock()) as rp_builder, \
             patch.object(module, "touch_product_context_build_attempt", touch):
            await module.repair_character_chat_assets(
                rows=[{"product_id": 687, "title": "테스트 작품", "_character_asset_collection_eligible": True}],
                args=SimpleNamespace(
                    apply=True,
                    verbose=False,
                    max_delta_episodes=2,
                ),
                results=results,
            )

        rp_builder.assert_not_awaited()
        touch.assert_called_once()
        self.assertEqual(results["character_asset_repair_failed"], 0)
        self.assertEqual(results["deferred_budget"], 1)
        self.assertEqual(results["character_asset_repairs"][0]["status"], "deferred_budget")
        self.assertEqual(results["products"][0]["context_status"], "deferred_budget")
        self.assertEqual(
            module.build_delta_exit_code(results, apply=True),
            module.STORYCTX_DEFERRED_BUDGET_EXIT_CODE,
        )

    async def test_character_asset_repair_storage_failure_sets_failed_exit(self):
        module = load_module()
        conn = FakeConnection()
        results = module.build_empty_results()
        scope_key = "character:main"
        before_readiness = {
            "character_chat_status": "hold",
            "public_candidate_count": 1,
            "missing_usable_scene_scope_keys": [scope_key],
        }

        with patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module.settings, "ANTHROPIC_API_KEY", ""), \
             patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())), \
             patch.object(module, "fetch_total_episode_count", return_value=1), \
             patch.object(module, "fetch_product_context_status", return_value="ready"), \
             patch.object(module, "fetch_product_ready_episode_count", return_value=1), \
             patch.object(module, "fetch_character_chat_asset_readiness_verification", return_value=before_readiness), \
             patch.object(module, "fetch_character_identity_review", return_value=None), \
             patch.object(module, "fetch_active_character_inventory_map", return_value={scope_key: {"canonical_character_key": scope_key, "display_name": "데시", "work_role": "main_protagonist", "is_protagonist": True, "evidence_episode_nos": [1]}}), \
             patch.object(
                 module,
                 "fetch_active_character_asset_summary_rows",
                 side_effect=[
                     [signal_row(1, 1, [signal_character(character_key=scope_key, display_name="데시")])],
                     [{"summary_id": 1, "scope_key": "episode:101", "episode_from": 1, "source_hash": "summary-hash", "summary_text": "[1화] 테스트"}],
                 ],
             ), \
             patch.object(module, "fetch_active_episode_texts_by_no", return_value={1: "데시가 문을 연다."}), \
             patch.object(module, "fetch_active_relation_inventory_map", return_value={}), \
             patch.object(module, "fetch_rp_ready_character_inventory_history_state_map", return_value={}), \
             patch.object(module, "build_episode_scene_extraction_summaries", AsyncMock(side_effect=RuntimeError("scene storage failed"))), \
             patch.object(module, "build_rp_summaries_delta", AsyncMock()) as rp_builder, \
             patch.object(module, "touch_product_context_build_attempt") as touch:
            await module.repair_character_chat_assets(
                rows=[{"product_id": 687, "title": "테스트 작품", "_character_asset_collection_eligible": True}],
                args=SimpleNamespace(
                    apply=True,
                    verbose=False,
                    max_delta_episodes=2,
                ),
                results=results,
            )

        rp_builder.assert_not_awaited()
        touch.assert_called_once()
        self.assertEqual(results["character_asset_repair_failed"], 1)
        self.assertEqual(results["character_asset_repair_no_progress"], 0)
        self.assertEqual(results["character_asset_repairs"][0]["status"], "failed")
        self.assertEqual(module.build_delta_exit_code(results, apply=True), 1)

    def test_failed_delta_status_repair_refreshes_when_foundation_complete(self):
        module = load_module()
        cur = object()
        rows = [
            {"product_id": 687, "episode_id": 101, "episode_no": 1},
            {"product_id": 687, "episode_id": 102, "episode_no": 2},
        ]
        repaired_row = {
            "product_id": 687,
            "context_status": "ready",
            "ready_episode_count": 2,
            "total_episode_count": 2,
        }

        with patch.object(module, "fetch_product_context_status", return_value="failed"), \
             patch.object(module, "build_open_add_episode_id_set", return_value=set()), \
             patch.object(module, "build_signal_repair_episode_id_set", return_value=set()), \
             patch.object(module, "assert_story_agent_foundation_invariants") as assert_foundation, \
             patch.object(module, "fetch_total_episode_count", return_value=2), \
             patch.object(module, "refresh_product_context_status", return_value=repaired_row) as refresh:
            repaired = module.repair_failed_delta_context_statuses(cur, rows)

        assert_foundation.assert_called_once_with(cur, product_id=687)
        refresh.assert_called_once_with(cur, product_id=687, total_episode_count=2)
        self.assertEqual(repaired, [repaired_row])

    def test_failed_delta_status_repair_skips_when_foundation_gap_remains(self):
        module = load_module()
        cur = object()
        rows = [
            {"product_id": 687, "episode_id": 101, "episode_no": 1},
            {"product_id": 687, "episode_id": 102, "episode_no": 2},
        ]

        with patch.object(module, "fetch_product_context_status", return_value="failed"), \
             patch.object(module, "build_open_add_episode_id_set", return_value=set()), \
             patch.object(module, "build_signal_repair_episode_id_set", return_value={102}), \
             patch.object(module, "refresh_product_context_status") as refresh:
            repaired = module.repair_failed_delta_context_statuses(cur, rows)

        refresh.assert_not_called()
        self.assertEqual(repaired, [])

    async def test_work_protagonist_resolution_does_not_call_provider(self):
        module = load_module()
        client = FakeOpenRouterClient({})
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:초반주인공",
                        display_name="초반주인공",
                        real_names=["초반주인공"],
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        payload = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=rows,
            summary_client=client,
        )

        self.assertEqual(payload["decision"], "RESOLVED")
        self.assertEqual(payload["work_protagonist_key"], "character:초반주인공")
        self.assertEqual(client.calls, [])

    async def test_work_protagonist_resolution_is_fixed_by_opening_three_episodes(self):
        module = load_module()
        opening_rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:초반주인공",
                        display_name="초반주인공",
                        real_names=["초반주인공"],
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]
        later_rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:후반시점인물",
                        display_name="후반시점인물",
                        real_names=["후반시점인물"],
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(4, 101)
        ]

        self.assertFalse(hasattr(module, "request_work_protagonist_resolution_payload"))
        opening_resolution = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=opening_rows,
            summary_client=None,
        )
        full_resolution = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=[*opening_rows, *later_rows],
            summary_client=None,
        )

        self.assertEqual(opening_resolution, full_resolution)
        self.assertEqual(opening_resolution["decision"], "RESOLVED")
        self.assertEqual(opening_resolution["work_protagonist_key"], "character:초반주인공")

        inventory = module.aggregate_character_inventory_v3_rows(
            [*opening_rows, *later_rows],
            protagonist_resolution=full_resolution,
        )
        self.assertEqual(
            [row["display_name"] for row in inventory if row["work_role"] == "main_protagonist"],
            ["초반주인공"],
        )

    async def test_work_protagonist_resolution_does_not_substitute_episode_four_for_missing_one(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:후보",
                        display_name="후보",
                        real_names=["후보"],
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                    )
                ],
            )
            for episode_no in (2, 3, 4)
        ]

        resolution = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=rows,
            summary_client=None,
        )

        self.assertEqual(resolution["decision"], "UNRESOLVED")
        self.assertEqual(resolution["reason_code"], "opening_signal_incomplete")

    async def test_later_anonymous_work_evidence_accumulates_on_selected_named_main(self):
        module = load_module()
        opening_rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:차태석",
                        display_name="차태석",
                        real_names=["차태석"],
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        is_first_person=True,
                        role_in_episode="lead",
                        voice_mode="monologue",
                        action_tags=["초반행동"],
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]
        later_rows = []
        for episode_no in (4, 30, 100):
            payload = module.normalize_episode_character_signals_payload(
                {
                    "mentioned_characters": [
                        signal_character(
                            character_key="ignored",
                            display_name="나",
                            aliases=["나"],
                            entity_kind="stable_role",
                            is_work_protagonist=True,
                            is_episode_focal=True,
                            is_first_person=True,
                            role_in_episode="lead",
                            voice_mode="monologue",
                            action_tags=["후반행동"],
                            affect_tags=["후반감정"],
                            relation_edges=[
                                {
                                    "target_key": "named:동료",
                                    "target_label": "동료",
                                    "relation_tag": "협력",
                                }
                            ],
                        )
                    ]
                },
                episode_no=episode_no,
            )
            later_rows.append(
                signal_row(episode_no, episode_no, payload["mentioned_characters"])
            )

        resolution = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=opening_rows,
            summary_client=None,
        )
        inventory = module.aggregate_character_inventory_v3_rows(
            [*opening_rows, *later_rows],
            protagonist_resolution=resolution,
        )
        main = next(row for row in inventory if row["work_role"] == "main_protagonist")
        target = module.build_inventory_rp_target(
            scope_key=main["canonical_character_key"],
            inventory_item=main,
        )

        self.assertEqual(main["canonical_character_key"], "character:차태석")
        self.assertEqual(main["evidence_episode_nos"], [1, 2, 3, 4, 30, 100])
        self.assertEqual(main["work_protagonist_evidence"]["episode_count"], 6)
        self.assertEqual(main["first_person_evidence"]["episode_count"], 6)
        self.assertIn("후반행동", main["dominant_action_tags"])
        self.assertIn("후반감정", main["dominant_affect_tags"])
        self.assertEqual(main["relation_episode_count"], 3)
        self.assertFalse(
            any(row["canonical_character_key"] == "character:나(주인공)" for row in inventory)
        )
        self.assertTrue(target["is_first_person"])
        self.assertTrue(target["collection_rules"]["use_monologue"])

    async def test_later_non_protagonist_name_variant_stays_separate_from_main(self):
        module = load_module()
        opening_rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:윤서진",
                        display_name="윤서진",
                        real_names=["윤서진"],
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]
        later_row = signal_row(
            4,
            4,
            [
                signal_character(
                    character_key="named:윤서",
                    display_name="윤서",
                    real_names=["윤서"],
                    is_work_protagonist=False,
                    is_episode_focal=True,
                    role_in_episode="lead",
                    action_tags=["별도행동"],
                )
            ],
        )

        resolution = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=opening_rows,
            summary_client=None,
        )
        inventory = module.aggregate_character_inventory_v3_rows(
            [*opening_rows, later_row],
            protagonist_resolution=resolution,
        )
        main = next(row for row in inventory if row["work_role"] == "main_protagonist")
        side = next(row for row in inventory if row is not main and "윤서" in row["aliases"])

        self.assertEqual(main["canonical_character_key"], "character:윤서진")
        self.assertEqual(main["evidence_episode_nos"], [1, 2, 3])
        self.assertEqual(side["evidence_episode_nos"], [4])

    async def test_later_work_positive_name_variant_cannot_replace_opening_main(self):
        module = load_module()
        opening_rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:민수",
                        display_name="민수",
                        real_names=["민수"],
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]
        later_row = signal_row(
            4,
            4,
            [
                signal_character(
                    character_key="protagonist:named:김민수",
                    display_name="김민수",
                    real_names=["김민수"],
                    is_work_protagonist=True,
                    is_episode_focal=True,
                    role_in_episode="lead",
                    action_tags=["후반행동"],
                )
            ],
        )

        resolution = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=[*opening_rows, later_row],
            summary_client=None,
        )
        inventory = module.aggregate_character_inventory_v3_rows(
            [*opening_rows, later_row],
            protagonist_resolution=resolution,
        )
        main = next(row for row in inventory if row["work_role"] == "main_protagonist")
        side = next(row for row in inventory if row is not main)

        self.assertEqual(resolution["work_protagonist_key"], "character:민수")
        self.assertEqual(main["canonical_character_key"], "character:민수")
        self.assertEqual(main["evidence_episode_nos"], [1, 2, 3, 4])
        self.assertIn("후반행동", main["dominant_action_tags"])
        self.assertEqual(side["canonical_character_key"], "character:김민수")
        self.assertEqual(side["evidence_episode_nos"], [4])

    async def test_work_protagonist_resolution_uses_internal_role_for_one_anonymous_opening(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="나",
                        aliases=["나"],
                        entity_kind="stable_role",
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        is_first_person=True,
                        role_in_episode="lead",
                        voice_mode="monologue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        resolution = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=rows,
            summary_client=None,
        )

        self.assertEqual(resolution["decision"], "RESOLVED")
        self.assertEqual(resolution["work_protagonist_key"], "character:나(주인공)")

    async def test_work_protagonist_resolution_abstains_for_conflicting_opening_claimants(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key=f"protagonist:named:후보{episode_no}",
                        display_name=f"후보{episode_no}",
                        real_names=[f"후보{episode_no}"],
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        resolution = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=rows,
            summary_client=None,
        )

        self.assertEqual(resolution["decision"], "UNRESOLVED")
        self.assertEqual(resolution["work_protagonist_keys"], [])

    async def test_work_protagonist_resolution_preserves_two_anonymous_claimants_in_one_episode(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 4):
            payload = module.normalize_episode_character_signals_payload(
                {
                    "mentioned_characters": [
                        signal_character(
                            character_key="ignored",
                            display_name="나",
                            aliases=[display_name],
                            entity_kind="stable_role",
                            is_work_protagonist=True,
                            is_episode_focal=True,
                            is_first_person=True,
                            role_in_episode="lead",
                            voice_mode="monologue",
                            scene_weight="high",
                        )
                        for display_name in ("첫 번째 화자", "두 번째 화자")
                    ]
                },
                episode_no=episode_no,
            )
            self.assertEqual(len(payload["mentioned_characters"]), 2)
            rows.append(signal_row(episode_no, episode_no, payload["mentioned_characters"]))

        resolution = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=rows,
            summary_client=None,
        )

        self.assertEqual(resolution["decision"], "UNRESOLVED")
        self.assertEqual(resolution["reason_code"], "conflicting_opening_claimants")

    async def test_possessed_protagonist_keeps_internal_key_and_uses_body_persona_display(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 4):
            payload = module.normalize_episode_character_signals_payload(
                {
                    "mentioned_characters": [
                        signal_character(
                            character_key="ignored",
                            display_name="김태석",
                            aliases=["태석", "김태석"],
                            real_names=["태석", "김태석"],
                            persona_names=["선우", "박선우"],
                            social_call_names=(
                                ["태석 님", "김태석"]
                                if episode_no == 1
                                else ["선우"]
                                if episode_no == 2
                                else ["선우", "박선우"]
                            ),
                            is_work_protagonist=True,
                            is_episode_focal=True,
                            is_first_person=True,
                            role_in_episode="lead",
                            voice_mode="monologue",
                            scene_weight="high",
                            identity_claims=[
                                {
                                    "target_label": "박선우",
                                    "claim_type": "possessed_as",
                                    "evidence": "김태석이 박선우의 몸과 사회적 이름을 사용한다",
                                }
                            ],
                        ),
                        signal_character(
                            character_key="ignored",
                            display_name="박선우",
                            aliases=["선우", "박선우"],
                            real_names=["선우", "박선우"],
                            role_in_episode="support",
                        ),
                    ]
                },
                episode_no=episode_no,
            )
            rows.append(signal_row(episode_no, episode_no, payload["mentioned_characters"]))

        resolution = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=rows,
            summary_client=None,
        )
        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution=resolution,
        )
        main = next(row for row in inventory if row["work_role"] == "main_protagonist")
        body_owner = next(
            row
            for row in inventory
            if row["canonical_character_key"] == "character:박선우"
        )

        self.assertEqual(main["canonical_character_key"], "character:김태석")
        self.assertEqual(main["display_name"], "박선우")
        self.assertTrue(main["public_chat_eligible"])
        self.assertNotEqual(body_owner["work_role"], "main_protagonist")

    async def test_possessed_protagonist_display_matching_body_owner_keeps_two_identities(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 4):
            payload = module.normalize_episode_character_signals_payload(
                {
                    "mentioned_characters": [
                        signal_character(
                            character_key="ignored",
                            display_name="백선우",
                            aliases=["백선우"],
                            real_names=["차태석"],
                            persona_names=["백선우"],
                            is_work_protagonist=True,
                            is_episode_focal=True,
                            is_first_person=True,
                            role_in_episode="lead",
                            voice_mode="monologue",
                            identity_claims=[
                                {
                                    "target_label": "백선우",
                                    "claim_type": "possessed_as",
                                    "evidence": "차태석이 백선우의 몸으로 살아간다",
                                }
                            ],
                        ),
                        signal_character(
                            character_key="ignored",
                            display_name="백선우",
                            aliases=["백선우"],
                            real_names=["백선우"],
                            role_in_episode="support",
                        ),
                    ]
                },
                episode_no=episode_no,
            )
            self.assertEqual(len(payload["mentioned_characters"]), 2)
            rows.append(signal_row(episode_no, episode_no, payload["mentioned_characters"]))

        resolution = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=rows,
            summary_client=None,
        )
        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution=resolution,
        )
        main = next(row for row in inventory if row["work_role"] == "main_protagonist")
        body_owner = next(
            row
            for row in inventory
            if row is not main
            and "named:백선우" in list(row.get("source_character_keys") or [])
        )

        self.assertEqual(main["canonical_character_key"], "character:차태석")
        self.assertEqual(main["display_name"], "백선우")
        self.assertNotEqual(body_owner["work_role"], "main_protagonist")

    async def test_possessed_protagonist_and_same_named_body_owner_remain_separate(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 4):
            payload = module.normalize_episode_character_signals_payload(
                {
                    "mentioned_characters": [
                        signal_character(
                            character_key="ignored",
                            display_name="동명인",
                            aliases=["동명인"],
                            real_names=["동명인"],
                            is_work_protagonist=True,
                            is_episode_focal=True,
                            is_first_person=True,
                            role_in_episode="lead",
                            identity_claims=[
                                {
                                    "target_label": "동명인",
                                    "claim_type": "possessed_as",
                                    "evidence": "동명인의 몸에 빙의했다",
                                }
                            ],
                        ),
                        signal_character(
                            character_key="ignored",
                            display_name="동명인",
                            aliases=["동명인"],
                            real_names=["동명인"],
                            role_in_episode="support",
                        ),
                    ]
                },
                episode_no=episode_no,
            )
            self.assertEqual(len(payload["mentioned_characters"]), 2)
            rows.append(signal_row(episode_no, episode_no, payload["mentioned_characters"]))

        resolution = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=rows,
            summary_client=None,
        )
        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution=resolution,
        )

        consciousness_rows = [
            row
            for row in inventory
            if "protagonist:named:동명인" in list(row.get("source_character_keys") or [])
        ]
        body_owner_rows = [
            row
            for row in inventory
            if "named:동명인" in list(row.get("source_character_keys") or [])
        ]
        mains = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertTrue(consciousness_rows)
        self.assertTrue(body_owner_rows)
        self.assertEqual(len(mains), 1)
        self.assertIn(mains[0], consciousness_rows)
        self.assertTrue(all(row["work_role"] != "main_protagonist" for row in body_owner_rows))

    async def test_resolved_opening_replaces_old_locked_main(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:새주인공",
                        display_name="새주인공",
                        real_names=["새주인공"],
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]
        resolution = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=rows,
            summary_client=None,
        )
        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution=resolution,
            locked_protagonist_rows=[
                {
                    "canonical_character_key": "character:기존주인공",
                    "display_name": "기존주인공",
                    "work_role": "main_protagonist",
                }
            ],
        )
        main = next(row for row in inventory if row["work_role"] == "main_protagonist")

        self.assertEqual(main["canonical_character_key"], "character:새주인공")
        self.assertEqual(
            main["superseded_protagonist_scope_keys"],
            ["character:기존주인공"],
        )

    async def test_resolved_opening_does_not_remap_fresh_identity_to_old_persona_lock(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 4):
            payload = module.normalize_episode_character_signals_payload(
                {
                    "mentioned_characters": [
                        signal_character(
                            character_key="ignored",
                            display_name="차태석",
                            aliases=["차태석", "백선우"],
                            real_names=["차태석"],
                            persona_names=["백선우"],
                            is_work_protagonist=True,
                            is_episode_focal=True,
                            is_first_person=True,
                            role_in_episode="lead",
                            voice_mode="monologue",
                            scene_weight="high",
                            identity_claims=[
                                {
                                    "target_label": "백선우",
                                    "claim_type": "possessed_as",
                                    "evidence": "차태석이 백선우의 몸으로 살아간다",
                                }
                            ],
                        ),
                        signal_character(
                            character_key="ignored",
                            display_name="백선우",
                            aliases=["백선우"],
                            real_names=["백선우"],
                            role_in_episode="support",
                        ),
                    ]
                },
                episode_no=episode_no,
            )
            rows.append(signal_row(episode_no, episode_no, payload["mentioned_characters"]))

        resolution = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=rows,
            summary_client=None,
        )
        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution=resolution,
            locked_protagonist_rows=[
                {
                    "canonical_character_key": "character:백선우",
                    "display_name": "백선우",
                    "source_character_keys": ["named:백선우"],
                    "work_role": "main_protagonist",
                }
            ],
        )
        main = next(row for row in inventory if row["work_role"] == "main_protagonist")

        self.assertEqual(main["canonical_character_key"], "character:차태석")
        self.assertEqual(main["display_name"], "백선우")
        self.assertEqual(
            main["superseded_protagonist_scope_keys"],
            ["character:백선우"],
        )

    async def test_unresolved_opening_preserves_matching_locked_main(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:기존주인공",
                        display_name="기존주인공",
                        real_names=["기존주인공"],
                        role_in_episode="lead",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]
        resolution = await module.build_work_protagonist_resolution_for_inventory_v3(
            product_id=687,
            product_title="테스트 작품",
            signal_rows=rows,
            summary_client=None,
        )
        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution=resolution,
            locked_protagonist_rows=[
                {
                    "canonical_character_key": "character:기존주인공",
                    "display_name": "기존주인공",
                    "source_character_keys": ["named:기존주인공"],
                    "work_role": "main_protagonist",
                }
            ],
        )

        self.assertEqual(resolution["decision"], "UNRESOLVED")
        self.assertEqual(
            [row["canonical_character_key"] for row in inventory if row["work_role"] == "main_protagonist"],
            ["character:기존주인공"],
        )

    async def test_build_character_inventory_v3_resolved_path_applies_work_resolution(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 6):
            rows.append(
                signal_row(
                    episode_no,
                    episode_no,
                    [
                        signal_character(
                            character_key="protagonist:named:존" if episode_no <= 3 else "named:존",
                            display_name="존",
                            is_protagonist=episode_no <= 3,
                            is_work_protagonist=episode_no <= 3,
                            is_episode_focal=episode_no <= 3,
                            role_in_episode="lead",
                            voice_mode="dialogue",
                            scene_weight="high",
                        ),
                        signal_character(
                            character_key="named:설총",
                            display_name="설총",
                            is_work_protagonist=False,
                            is_episode_focal=episode_no >= 2,
                            role_in_episode="lead",
                            voice_mode="dialogue",
                            scene_weight="high",
                        ),
                    ],
                )
            )
        inserted_items = []

        def fake_fetch(*, cur, product_id, summary_type):
            self.assertEqual(product_id, 687)
            if summary_type == "episode_character_signals":
                return rows
            if summary_type == "character_inventory_v3":
                return []
            if summary_type == "character_identity_review_v1":
                return []
            self.fail(f"unexpected summary_type: {summary_type}")

        def fake_upsert(cur, *, product_id, item):
            inserted_items.append(item)
            return True

        with patch.object(module, "fetch_active_character_asset_summary_rows", side_effect=fake_fetch), \
             patch.object(module, "fetch_active_summary_rows", side_effect=fake_fetch), \
             patch.object(module, "upsert_character_inventory_v3_item", side_effect=fake_upsert), \
             patch.object(module, "deactivate_missing_active_scopes") as deactivate_missing:
            counts = await module.build_character_inventory_v3_summaries_resolved(
                object(),
                product_id=687,
                product_title="테스트 작품",
                summary_client=object(),
                episode_summary_rows=[
                    {
                        "episode_from": 1,
                        "summary_text": "1화\n- 존과 설총이 충돌한다.\n- 키워드: 존, 설총",
                    }
                ],
            )

        self.assertEqual(counts, (len(inserted_items), 0))
        main_rows = [item for item in inserted_items if item["work_role"] == "main_protagonist"]
        self.assertEqual([item["display_name"] for item in main_rows], ["존"])
        self.assertEqual(main_rows[0]["work_protagonist_resolution"]["decision"], "RESOLVED")
        deactivate_missing.assert_called_once()

    async def test_build_character_inventory_v3_resolved_path_runs_without_provider(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:존",
                        display_name="존",
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 6)
        ]
        inserted_items = []

        with patch.object(module, "fetch_active_character_asset_summary_rows", return_value=rows), \
             patch.object(module, "fetch_active_summary_rows", return_value=rows), \
             patch.object(module, "fetch_character_identity_review", return_value=None), \
             patch.object(module, "OPENROUTER_API_KEY", ""), \
             patch.object(module, "upsert_character_inventory_v3_item", side_effect=lambda cur, *, product_id, item: inserted_items.append(item) or True), \
             patch.object(module, "deactivate_missing_active_scopes"):
            await module.build_character_inventory_v3_summaries_resolved(
                object(),
                product_id=687,
                product_title="테스트 작품",
                summary_client=object(),
            )

        self.assertEqual(
            [item["display_name"] for item in inserted_items if item["work_role"] == "main_protagonist"],
            ["존"],
        )

    def test_rp_target_quality_guard_rejects_generic_display_name(self):
        module = load_module()

        self.assertEqual(module.get_rp_target_skip_reason({"display_name": "지금"}), "generic_display_name")
        self.assertEqual(module.get_rp_target_skip_reason({"display_name": " 오늘 "}), "generic_display_name")
        self.assertEqual(module.get_rp_target_skip_reason({"display_name": "형"}), "generic_display_name")
        self.assertEqual(module.get_rp_target_skip_reason({"display_name": "왕"}), "generic_display_name")
        self.assertEqual(module.get_rp_target_skip_reason({"display_name": "백이현"}), "")
        self.assertEqual(module.get_rp_target_skip_reason({"display_name": "주인공", "aliases": ["나"]}), "generic_display_name")

    def test_rp_profile_requires_minimum_exact_examples(self):
        module = load_module()

        self.assertFalse(module.has_enough_rp_example_texts(["첫 번째"]))
        self.assertTrue(module.has_enough_rp_example_texts(["첫 번째", "두 번째"]))

    def test_character_chat_context_richness_report_compares_prod_baseline_and_shadow(self):
        module = load_module()
        baseline = {
            "inventory": {
                "display_name": "백이현",
                "aliases": ["백이현"],
                "evidence_episode_nos": [1],
            },
            "profile": {
                "speech_style": {},
                "personality_core": [],
                "baseline_attitude": "",
            },
            "examples": {"examples": []},
        }
        shadow = {
            "inventory": {
                "display_name": "백이현",
                "aliases": ["백이현", "이현", "공자"],
                "narration_names": ["백이현"],
                "social_call_names": ["공자님"],
                "persona_names": ["검은 공자"],
                "real_names": ["백이현"],
                "evidence_episode_nos": [1, 2, 3, 4],
                "relation_episode_count": 3,
            },
            "profile": {
                "speech_style": {"tone": "단호", "formality": "반말"},
                "personality_core": ["원칙적", "경계심"],
                "baseline_attitude": "경계",
            },
            "examples": {
                "examples": [
                    {"episode_no": 1, "text": "물러서지 마."},
                    {"episode_no": 2, "text": "내가 확인하지."},
                    {"episode_no": 3, "text": "지금은 움직여야 해."},
                ]
            },
            "summary_context_lines": ["[1화] 백이현이 결심한다."],
            "relation_context_lines": ["백이현 -> 설총: 경계"],
        }

        report = module.compare_character_chat_context_richness(baseline, shadow)

        self.assertGreater(report["candidate"]["richness_score"], report["baseline"]["richness_score"])
        self.assertGreater(report["deltas"]["example_count"], 0)
        self.assertGreater(report["deltas"]["identity_name_signal_count"], 0)
        self.assertIn("speech_style_field_count", report["improved_metrics"])

    def test_dedupe_rp_dialogue_items_preserves_episode_no(self):
        module = load_module()

        deduped = module.dedupe_rp_dialogue_items(
            [
                {
                    "kind": "dialogue",
                    "context": "백이현",
                    "text": "그게 정말 가능하다고?",
                    "episode_no": 7,
                }
            ]
        )

        self.assertEqual(deduped[0]["episode_no"], 7)

    def test_speaker_anchor_match_requires_precise_name_boundary(self):
        module = load_module()

        self.assertTrue(module.has_speaker_anchor_match('백이현이 말했다. "간다."', ["백이현"]))
        self.assertTrue(module.has_speaker_anchor_match('반 아슬란은 대답했다. "물러서지 않는다."', ["반 아슬란"]))
        self.assertFalse(module.has_speaker_anchor_match('최신 트렌드를 설명했다. "이게 맞다."', ["렌"]))
        self.assertFalse(module.has_speaker_anchor_match('김백이현이 말했다. "간다."', ["백이현"]))
        self.assertTrue(module.has_speaker_anchor_match('렌이 말했다. "간다."', ["렌"], allow_single_char_anchors=True))
        self.assertFalse(module.has_speaker_anchor_match('최신 트렌드를 설명했다. "이게 맞다."', ["렌"], allow_single_char_anchors=True))

    def test_direct_voice_quality_requires_distributed_exact_dialogue(self):
        module = load_module()
        target = {
            "display_name": "백이현",
            "aliases": ["백이현"],
            "collection_rules": {
                "use_dialogue": True,
                "speaker_anchors": ["백이현"],
            },
        }
        episode_texts_by_no = {
            1: "\n".join(
                [
                    '백이현이 말했다. "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해."',
                    '백이현이 낮게 물었다. "그 말이 사실이라면 지금 당장 증거를 보여 줘."',
                    '백이현은 고개를 저으며 말했다. "아직 끝난 게 아니야, 내가 직접 확인하겠어."',
                ]
            ),
            2: "\n".join(
                [
                    '백이현이 숨을 고르며 답했다. "겁먹을 시간은 없어, 먼저 사람들을 빼내."',
                    '백이현이 검을 세우며 말했다. "네가 막는다면 나도 돌아가지 않겠어."',
                    '백이현이 짧게 웃었다. "좋아, 이번엔 네 방식대로 움직여 보자."',
                ]
            ),
            3: "\n".join(
                [
                    '백이현이 문서를 접으며 말했다. "이 기록은 내가 맡을게, 누구에게도 넘기지 마."',
                    '백이현이 뒤돌아서며 말했다. "따라오지 마, 여기서부터는 내가 정리한다."',
                    '백이현이 조용히 말했다. "약속은 지킬 거야, 대신 너도 물러서지 마."',
                ]
            ),
        }

        quality = module.build_direct_voice_evidence_quality(target, episode_texts_by_no)

        self.assertEqual(quality["status"], "strict_dialogue_ready")
        self.assertTrue(quality["strict_chat_ready"])
        self.assertEqual(quality["dialogue"]["item_count"], 9)
        self.assertEqual(quality["dialogue"]["episode_count"], 3)
        self.assertGreaterEqual(quality["dialogue"]["example_count"], 3)
        self.assertLessEqual(quality["dialogue"]["max_episode_share"], 0.60)

    def test_direct_voice_quality_excludes_generic_display_label(self):
        module = load_module()
        target = {
            "display_name": "형",
            "aliases": ["형"],
            "collection_rules": {"speaker_anchors": ["형"]},
        }

        quality = module.build_direct_voice_evidence_quality(
            target,
            {
                1: '형이 말했다. "지금은 움직이면 안 돼."',
                2: '형이 답했다. "내가 먼저 확인하고 올게."',
                3: '형이 물었다. "너는 여기 남을 수 있겠어?"',
            },
        )

        self.assertEqual(quality["status"], "excluded_generic_label")
        self.assertFalse(quality["strict_chat_ready"])

    def test_direct_voice_quality_accepts_strong_role_like_persona_label(self):
        module = load_module()
        target = {
            "display_name": "관리자",
            "aliases": ["관리자"],
            "display_safety": {"status": "pass", "reason": "stable_persona_identity"},
            "collection_rules": {
                "use_dialogue": True,
                "speaker_anchors": ["관리자"],
            },
        }

        quality = module.build_direct_voice_evidence_quality(
            target,
            {
                1: "\n".join(
                    [
                        '관리자가 말했다. "지금부터 기록을 다시 확인한다, 누구도 먼저 움직이지 말고 내가 부를 때까지 대기해."',
                        '관리자가 낮게 답했다. "내 허락 없이 문을 열면 모두 위험해진다, 그러니 통제선 밖으로 물러서."',
                        '관리자는 시선을 돌리며 말했다. "남은 권한은 내가 책임지고 정리하겠다, 너희는 생존자부터 확인해."',
                    ]
                ),
                2: "\n".join(
                    [
                        '관리자가 물었다. "네가 본 장면을 순서대로 말해, 작은 단서라도 빠뜨리면 안 된다."',
                        '관리자가 고개를 끄덕이며 말했다. "좋아, 이번에는 네 판단을 믿고 맡기겠다, 대신 보고는 바로 올려."',
                        '관리자가 짧게 말했다. "문제는 아직 끝나지 않았고, 내가 직접 막는다, 모두 뒤를 맡아라."',
                    ]
                ),
                3: "\n".join(
                    [
                        '관리자가 한숨을 삼키며 답했다. "여기서 물러서면 다음 피해자는 더 늘어난다, 그러니 내가 끝까지 남겠다."',
                        '관리자가 손을 들며 말했다. "경보는 내가 끈다, 너는 사람들을 빼내고 출구를 확보해."',
                        '관리자가 마지막으로 답했다. "책임은 내게 있으니 모두 뒤로 물러서라, 남은 판단은 내가 한다."',
                    ]
                ),
            },
        )

        self.assertEqual(quality["status"], "strict_dialogue_ready")
        self.assertTrue(quality["strict_chat_ready"])
        self.assertEqual(quality["dialogue"]["episode_count"], 3)

    def test_dialogue_attribution_rejects_addressee_as_speaker(self):
        module = load_module()
        text = '철수가 백이현에게 말했다. "지금은 도망쳐야 해."'
        baek_target = {
            "display_name": "백이현",
            "aliases": ["백이현"],
            "collection_rules": {"speaker_anchors": ["백이현"]},
        }
        cheol_target = {
            "display_name": "철수",
            "aliases": ["철수"],
            "collection_rules": {"speaker_anchors": ["철수"]},
        }

        self.assertEqual(module.collect_rule_based_rp_dialogue_items(baek_target, text), [])
        self.assertEqual(len(module.collect_rule_based_rp_dialogue_items(cheol_target, text)), 1)

    def test_dialogue_attribution_does_not_use_next_line_as_speaker(self):
        module = load_module()
        text = "\n".join(
            [
                "철수가 말했다.",
                '"지금은 도망쳐야 해."',
                "백이현이 고개를 끄덕였다.",
            ]
        )
        baek_target = {
            "display_name": "백이현",
            "aliases": ["백이현"],
            "collection_rules": {"speaker_anchors": ["백이현"]},
        }
        cheol_target = {
            "display_name": "철수",
            "aliases": ["철수"],
            "collection_rules": {"speaker_anchors": ["철수"]},
        }

        self.assertEqual(module.collect_rule_based_rp_dialogue_items(baek_target, text), [])
        self.assertEqual(len(module.collect_rule_based_rp_dialogue_items(cheol_target, text)), 1)

    def test_dialogue_attribution_rejects_competing_speaker_match(self):
        module = load_module()
        text = '백이현이 말했다. 영희가 대답했다. "같이 가자."'
        target = {
            "display_name": "백이현",
            "aliases": ["백이현"],
            "collection_rules": {
                "speaker_anchors": ["백이현"],
                "competing_speaker_anchors": ["영희"],
            },
        }

        self.assertEqual(module.collect_rule_based_rp_dialogue_items(target, text), [])

    def test_direct_voice_quality_does_not_count_unanchored_first_person_quotes(self):
        module = load_module()
        target = {
            "display_name": "백이현",
            "aliases": ["백이현"],
            "is_protagonist": True,
            "is_first_person": True,
            "collection_rules": {
                "use_dialogue": True,
                "use_monologue": True,
                "speaker_anchors": ["백이현"],
            },
        }
        episode_texts_by_no = {
            1: "\n".join(
                [
                    '상대가 말했다. "나는 여기서 물러서지 않을 거야, 네 선택을 다시 확인해."',
                    '상대가 낮게 물었다. "그 말이 사실이라면 지금 당장 증거를 보여 줘."',
                    '상대는 고개를 저었다. "아직 끝난 게 아니야, 내가 직접 확인하겠어."',
                ]
            ),
            2: "\n".join(
                [
                    '상대가 숨을 고르며 답했다. "겁먹을 시간은 없어, 먼저 사람들을 빼내."',
                    '상대가 검을 세웠다. "네가 막는다면 나도 돌아가지 않겠어."',
                    '상대가 짧게 웃었다. "좋아, 이번엔 네 방식대로 움직여 보자."',
                ]
            ),
            3: "\n".join(
                [
                    '상대가 문서를 접었다. "이 기록은 내가 맡을게, 누구에게도 넘기지 마."',
                    '상대가 뒤돌아섰다. "따라오지 마, 여기서부터는 내가 정리한다."',
                    '상대가 조용히 말했다. "약속은 지킬 거야, 대신 너도 물러서지 마."',
                ]
            ),
        }

        quality = module.build_direct_voice_evidence_quality(target, episode_texts_by_no)

        self.assertEqual(quality["status"], "insufficient")
        self.assertFalse(quality["strict_chat_ready"])
        self.assertEqual(quality["dialogue"]["item_count"], 0)
        self.assertEqual(quality["monologue"]["item_count"], 0)

    def test_first_person_collection_does_not_collect_all_unattributed_quotes(self):
        module = load_module()
        target = {
            "display_name": "백이현",
            "aliases": ["백이현"],
            "is_protagonist": True,
            "is_first_person": True,
            "collection_rules": {
                "use_dialogue": True,
                "use_monologue": True,
                "speaker_anchors": ["백이현"],
            },
        }
        text = "\n".join(
            [
                '상대가 말했다. "나는 여기서 물러서지 않을 거야."',
                '백이현이 말했다. "나는 직접 확인하겠어."',
            ]
        )

        items = module.collect_rule_based_rp_dialogue_items(target, text)

        self.assertEqual([item["text"] for item in items], ["나는 직접 확인하겠어."])

    def test_inventory_rp_targets_exclude_generic_identity_labels(self):
        module = load_module()
        targets = module.build_inventory_rp_targets(
            {
                "character:형": {
                    "canonical_character_key": "character:형",
                    "display_name": "형",
                    "aliases": ["형"],
                    "is_protagonist": True,
                    "distinct_episode_count": 10,
                    "voice_evidence_count": 10,
                },
                "character:백이현": {
                    "canonical_character_key": "character:백이현",
                    "display_name": "백이현",
                    "aliases": ["백이현"],
                    "is_protagonist": True,
                    "distinct_episode_count": 10,
                    "voice_evidence_count": 10,
                },
            }
        )

        self.assertEqual([target["character_key"] for target in targets], ["character:백이현"])

    def test_inventory_rp_targets_exclude_non_protagonist_duplicate_canonical_rows(self):
        module = load_module()
        targets = module.build_inventory_rp_targets(
            {
                "character:이시혁": {
                    "display_name": "이시혁",
                    "aliases": ["이시혁", "1000번"],
                    "is_protagonist": True,
                    "distinct_episode_count": 83,
                    "review_reasons": ["duplicate_canonical_key"],
                },
                "character:1000번:dup:fed5c7cd": {
                    "display_name": "1000번",
                    "aliases": ["1000번", "주인공"],
                    "is_protagonist": False,
                    "distinct_episode_count": 40,
                    "review_reasons": ["AMBIGUOUS_TOP_CANDIDATES", "duplicate_canonical_key"],
                },
                "character:당화린": {
                    "display_name": "당화린",
                    "aliases": ["당화린"],
                    "is_protagonist": False,
                    "distinct_episode_count": 13,
                },
            }
        )

        self.assertEqual(
            [target["character_key"] for target in targets],
            ["character:이시혁", "character:당화린"],
        )
        self.assertEqual(
            module.build_inventory_rp_retained_scope_keys(
                {
                    "character:이시혁": {
                        "display_name": "이시혁",
                        "aliases": ["이시혁", "1000번"],
                        "is_protagonist": True,
                        "distinct_episode_count": 83,
                        "review_reasons": ["duplicate_canonical_key"],
                    },
                    "character:1000번:dup:fed5c7cd": {
                        "display_name": "1000번",
                        "aliases": ["1000번", "주인공"],
                        "is_protagonist": False,
                        "distinct_episode_count": 40,
                        "review_reasons": ["duplicate_canonical_key"],
                    },
                }
            ),
            {"character:이시혁"},
        )

    def test_inventory_rp_targets_do_not_require_public_chat_voice_gate(self):
        module = load_module()
        targets = module.build_inventory_rp_targets(
            {
                "character:전승택": {
                    "canonical_character_key": "character:전승택",
                    "display_name": "전승택",
                    "aliases": ["전승택", "승택"],
                    "is_protagonist": True,
                    "distinct_episode_count": 16,
                    "public_chat_eligible": False,
                    "display_safety": {
                        "status": "pass",
                        "reason": "resolved_named_identity",
                    },
                }
            }
        )

        self.assertEqual([target["character_key"] for target in targets], ["character:전승택"])

    def test_inventory_rp_targets_default_to_two_and_preserve_other_valid_scopes(self):
        module = load_module()
        inventory = {
            f"character:{name}": {
                "canonical_character_key": f"character:{name}",
                "display_name": name,
                "aliases": [name],
                "is_protagonist": name == "백이현",
                "distinct_episode_count": episode_count,
                "voice_evidence_count": episode_count,
            }
            for name, episode_count in (("백이현", 15), ("동료", 12), ("라이벌", 10))
        }

        targets = module.build_inventory_rp_targets(inventory)
        retained_scope_keys = module.build_inventory_rp_retained_scope_keys(inventory)

        self.assertEqual(
            [target["character_key"] for target in targets],
            ["character:백이현", "character:동료"],
        )
        self.assertEqual(
            retained_scope_keys,
            {"character:백이현", "character:동료", "character:라이벌"},
        )

    def test_direct_voice_quality_accepts_distributed_first_person_monologue(self):
        module = load_module()
        target = {
            "display_name": "백이현",
            "aliases": ["백이현"],
            "is_protagonist": True,
            "is_first_person": True,
            "collection_rules": {
                "use_dialogue": True,
                "use_monologue": True,
                "speaker_anchors": ["백이현"],
            },
        }
        episode_texts_by_no = {
            1: "\n".join(
                [
                    "나는 아직 이 싸움의 끝을 보지 못했다. 물러서면 모두가 같은 함정에 빠질 것이다. 그래서 먼저 발을 옮겼다.",
                    "내가 먼저 움직여야 한다고 판단했다. 누군가를 기다리기에는 시간이 너무 적었다. 망설이면 늦는다.",
                ]
            ),
            2: "\n".join(
                [
                    "난 그들의 침묵이 더 위험하다고 느꼈다. 말하지 않는 쪽이 늘 더 많은 것을 숨겼다. 그래서 더 파고들었다.",
                    "내게 남은 선택지는 많지 않았다. 그래도 여기서 멈추면 아무것도 지킬 수 없었다. 끝까지 확인해야 했다.",
                ]
            ),
            3: "\n".join(
                [
                    "내 마음은 이미 답을 알고 있었다. 겁이 나도 뒤로 물러설 수는 없었다. 그게 내가 택한 길이었다.",
                    "내 판단이 틀렸다면 책임도 내가 져야 한다. 그래서 마지막 문을 직접 열었다. 누구에게도 미룰 수 없었다.",
                ]
            ),
        }

        quality = module.build_direct_voice_evidence_quality(target, episode_texts_by_no)

        self.assertEqual(quality["status"], "strict_monologue_ready")
        self.assertTrue(quality["strict_chat_ready"])
        self.assertEqual(quality["monologue"]["item_count"], 6)
        self.assertEqual(quality["monologue"]["episode_count"], 3)
        self.assertGreaterEqual(quality["monologue"]["total_chars"], 300)

    def test_delta_rp_refresh_is_opt_in_cli_flag(self):
        module = load_module()

        with patch.object(sys, "argv", ["build_story_agent_context.py", "--build-mode", "delta", "--product-id", "687"]):
            args = module.parse_args()
        self.assertFalse(args.refresh_rp)
        self.assertFalse(module.should_refresh_delta_rp(args))

        with patch.object(
            sys,
            "argv",
            [
                "build_story_agent_context.py",
                "--build-mode",
                "delta",
                "--product-id",
                "687",
                "--refresh-rp",
            ],
        ):
            args = module.parse_args()
        self.assertTrue(args.refresh_rp)
        self.assertTrue(module.should_refresh_delta_rp(args))

    def test_delta_rp_scope_selection_repairs_only_missing_canonical_targets(self):
        module = load_module()
        inventory_map = {
            "character:루벤": {
                "display_name": "루벤",
                "aliases": ["루벤"],
                "is_protagonist": True,
                "distinct_episode_count": 15,
                "voice_evidence_count": 12,
            },
            "character:티르": {
                "display_name": "티르",
                "aliases": ["티르"],
                "is_protagonist": False,
                "distinct_episode_count": 12,
                "voice_evidence_count": 8,
            },
            "character:세실": {
                "display_name": "세실",
                "aliases": ["세실"],
                "is_protagonist": False,
                "distinct_episode_count": 8,
                "voice_evidence_count": 6,
            },
        }
        complete_profile = {"payload": {"character_key": "character:티르", "speech_style": {"tone": "차분"}}}
        complete_examples = {
            "payload": {
                "character_key": "character:티르",
                "examples": [{"episode_no": 1, "text": "준비하겠습니다."}],
            }
        }

        selected = module.select_delta_rp_scope_keys(
            refresh_requested=False,
            affected_scope_keys={"character:티르"},
            inventory_map=inventory_map,
            profile_map={"character:티르": complete_profile},
            examples_map={
                "character:티르": complete_examples,
                "protagonist:named:루벤": {
                    "payload": {"examples": [{"episode_no": 1, "text": "legacy only"}]}
                },
            },
        )

        self.assertEqual(selected, {"character:루벤"})

    def test_delta_rp_scope_selection_refresh_uses_affected_scope_keys(self):
        module = load_module()

        selected = module.select_delta_rp_scope_keys(
            refresh_requested=True,
            affected_scope_keys={"character:루벤", "character:티르"},
            inventory_map={},
            profile_map={},
            examples_map={},
        )

        self.assertEqual(selected, {"character:루벤", "character:티르"})

    def test_delta_cli_accepts_max_delta_episode_cap(self):
        module = load_module()

        with patch.object(
            sys,
            "argv",
            [
                "build_story_agent_context.py",
                "--build-mode",
                "delta",
                "--product-id",
                "687",
                "--max-delta-episodes",
                "5",
            ],
        ):
            args = module.parse_args()

        self.assertEqual(args.max_delta_episodes, 5)

    def test_target_queries_include_all_consented_products_but_mark_character_cohort(self):
        module = load_module()

        args = SimpleNamespace(product_ids=[], episode_ids=[], episode_nos=[], limit=0)
        query, params = module.build_target_query(args=args, use_epub_fallback=False)

        self.assertEqual(params, [])
        self.assertIn("p.price_type IN ('free', 'paid')", query)
        self.assertIn("p.status_code IN ('ongoing', 'end')", query)
        self.assertIn("pe.open_yn = 'Y'", query)
        self.assertIn("FROM tb_product_episode cohort_episode", query)
        self.assertIn("cohort_episode.use_yn = 'Y'", query)
        self.assertIn("cohort_episode.open_yn = 'Y'", query)
        self.assertIn("HAVING COUNT(*) >= 15", query)
        self.assertIn("MIN(COALESCE(", query)
        self.assertIn("cohort_episode.open_changed_date", query)
        self.assertIn("cohort_episode.publish_reserve_date", query)
        self.assertIn("cohort_episode.created_date", query)
        self.assertIn(">= '2026-03-01 00:00:00'", query)
        self.assertIn("COALESCE(p.blind_yn, 'N') = 'N'", query)
        self.assertIn("COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'", query)
        self.assertIn("COALESCE(sacp.context_status, 'pending') <> 'disabled'", query)
        self.assertNotIn("OR COALESCE(sacp.context_status, 'pending') = 'ready'", query)
        self.assertIn("AS character_asset_collection_eligible", query)
        self.assertNotIn("p.price_type = 'free'", query)

    def test_total_episode_count_matches_public_serial_or_ended_scope(self):
        module = load_module()

        class FakeCursor:
            def __init__(self):
                self.query = ""
                self.params = None

            def execute(self, query, params):
                self.query = query
                self.params = params

            def fetchone(self):
                return {"total_episode_count": 7}

        cur = FakeCursor()
        count = module.fetch_total_episode_count(cur, product_id=1101)

        self.assertEqual(count, 7)
        self.assertEqual(cur.params, (1101,))
        self.assertIn("p.price_type IN ('free', 'paid')", cur.query)
        self.assertIn("p.status_code IN ('ongoing', 'end')", cur.query)
        self.assertNotIn("'rest'", cur.query)
        self.assertNotIn("'stop'", cur.query)
        self.assertNotIn("p.price_type = 'free'", cur.query)


class StoryAgentCharacterInventoryV3Test(TestCase):
    def test_inventory_v3_merges_named_and_protagonist_prefix_for_same_character(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:란",
                        display_name="란",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:란",
                        display_name="란",
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="protagonist:named:란",
                        display_name="란",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        character = inventory[0]
        self.assertEqual(character["display_name"], "란")
        self.assertEqual(set(character["source_character_keys"]), {"named:란", "protagonist:named:란"})
        self.assertEqual(character["distinct_episode_count"], 3)
        self.assertEqual(character["episode_focal_evidence"]["episode_count"], 2)
        self.assertEqual(character["work_role"], "main_protagonist")
        self.assertTrue(character["is_protagonist"])
        self.assertEqual(character["protagonist_confidence"], "high")
        self.assertEqual(character["classification_status"], "AUTO_RESOLVED")
        self.assertEqual(character["rp_signal_quality"]["status"], "summary_ready")
        self.assertEqual(character["rp_signal_quality"]["evidence_source"], "episode_summary_voice_mode")
        self.assertFalse(character["rp_signal_quality"]["strict_chat_ready"])
        self.assertFalse(character["rp_signal_quality"]["needs_review"])

    def test_episode_character_signal_normalization_preserves_names_and_strict_booleans(self):
        module = load_module()
        payload = {
            "episode_no": 1,
            "mentioned_characters": [
                {
                    "display_name": "성아",
                    "aliases": ["성아", "소야"],
                    "is_protagonist": "false",
                    "is_first_person": "true",
                    "entity_kind": "person",
                    "scene_weight": "high",
                    "role_in_episode": "lead",
                    "voice_mode": "dialogue",
                    "action_tags": [],
                    "affect_tags": [],
                    "relation_edges": [],
                    "identity_claims": [
                        {
                            "target_label": "소야",
                            "claim_type": "alias_of",
                            "evidence": "성아는 소야로도 불린다",
                        }
                    ],
                }
            ],
            "cliffhanger_hooks": [],
        }

        normalized = module.normalize_episode_character_signals_payload(payload, episode_no=1)
        character = normalized["mentioned_characters"][0]

        self.assertEqual(module.normalize_signal_entity_label("성아"), "성아")
        self.assertEqual(module.normalize_signal_entity_label("소야"), "소야")
        self.assertEqual(character["character_key"], "named:성아")
        self.assertFalse(character["is_protagonist"])
        self.assertFalse(character["is_work_protagonist"])
        self.assertFalse(character["is_episode_focal"])
        self.assertFalse(character["is_first_person"])
        self.assertEqual(
            character["identity_claims"],
            [
                {
                    "target_label": "소야",
                    "target_key": "named:성아",
                    "normalized_target_label": "소야",
                    "claim_type": "alias_of",
                    "evidence": "성아는 소야로도 불린다",
                }
            ],
        )

    def test_episode_character_signal_normalize_splits_work_protagonist_from_episode_focal(self):
        module = load_module()
        payload = {
            "episode_no": 2,
            "mentioned_characters": [
                {
                    "display_name": "조연",
                    "aliases": ["조연"],
                    "is_protagonist": False,
                    "is_work_protagonist": False,
                    "is_episode_focal": True,
                    "is_first_person": False,
                    "narration_names": ["조연"],
                    "social_call_names": ["조연님"],
                    "persona_names": [],
                    "real_names": [],
                    "entity_kind": "person",
                    "scene_weight": "high",
                    "role_in_episode": "lead",
                    "voice_mode": "dialogue",
                    "action_tags": [],
                    "affect_tags": [],
                    "relation_edges": [],
                    "identity_claims": [],
                }
            ],
            "cliffhanger_hooks": [],
        }

        normalized = module.normalize_episode_character_signals_payload(payload, episode_no=2)
        character = normalized["mentioned_characters"][0]

        self.assertFalse(character["is_protagonist"])
        self.assertFalse(character["is_work_protagonist"])
        self.assertTrue(character["is_episode_focal"])
        self.assertEqual(character["character_key"], "named:조연")
        self.assertEqual(character["narration_names"], ["조연"])
        self.assertEqual(character["social_call_names"], ["조연님"])

    def test_inventory_v3_does_not_promote_later_dominance_without_opening_resolution(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 51):
            characters = [
                signal_character(
                    character_key="protagonist:named:존" if episode_no <= 12 else "named:존",
                    display_name="존",
                    is_protagonist=episode_no <= 12,
                    role_in_episode="lead" if episode_no <= 30 else "support",
                    voice_mode="dialogue" if episode_no <= 30 else "narration_only",
                    scene_weight="high" if episode_no <= 30 else "medium",
                )
            ]
            if episode_no <= 16:
                characters.append(
                    signal_character(
                        character_key="named:요한",
                        display_name="요한",
                        role_in_episode="support",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                )
            rows.append(signal_row(episode_no, episode_no, characters))

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(inventory[0]["display_name"], "존")
        self.assertTrue(all(row["protagonist_evidence"]["score"] == 0.0 for row in inventory))
        self.assertEqual(
            [row["display_name"] for row in inventory if row["work_role"] == "main_protagonist"],
            ["존"],
        )

    def test_inventory_v3_does_not_use_score_threshold_as_protagonist_authority(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 21):
            characters = []
            if episode_no <= 15:
                characters.append(
                    signal_character(
                        character_key="protagonist:named:존" if episode_no <= 4 else "named:존",
                        display_name="존",
                        is_protagonist=episode_no <= 4,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                )
            if episode_no <= 8:
                characters.append(
                    signal_character(
                        character_key="protagonist:named:요한" if episode_no <= 2 else "named:요한",
                        display_name="요한",
                        is_protagonist=episode_no <= 2,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                )
            rows.append(signal_row(episode_no, episode_no, characters))

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(inventory[0]["display_name"], "존")
        self.assertTrue(all(row["protagonist_evidence"]["score"] == 0.0 for row in inventory))
        self.assertEqual(
            [row for row in inventory if row["work_role"] == "main_protagonist"],
            [],
        )

    def test_inventory_v3_does_not_promote_role_like_name_by_rank(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 21):
            characters = []
            if episode_no <= 13:
                characters.append(
                    signal_character(
                        character_key="protagonist:named:추종자" if episode_no <= 5 else "named:추종자",
                        display_name="추종자",
                        is_protagonist=episode_no <= 5,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                )
            if episode_no <= 12:
                characters.append(
                    signal_character(
                        character_key="protagonist:named:신미아" if episode_no <= 4 else "named:신미아",
                        display_name="신미아",
                        is_protagonist=episode_no <= 4,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                )
            rows.append(signal_row(episode_no, episode_no, characters))

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(inventory[0]["display_name"], "추종자")
        self.assertEqual(
            [row for row in inventory if row["work_role"] == "main_protagonist"],
            [],
        )

    def test_inventory_v3_keeps_close_top_candidates_under_review_below_default_threshold(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 21):
            characters = []
            if episode_no <= 12:
                characters.append(
                    signal_character(
                        character_key="protagonist:named:하린" if episode_no <= 4 else "named:하린",
                        display_name="하린",
                        is_protagonist=episode_no <= 4,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                )
            if episode_no <= 12:
                characters.append(
                    signal_character(
                        character_key="protagonist:named:미아" if episode_no <= 4 else "named:미아",
                        display_name="미아",
                        is_protagonist=episode_no <= 4,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                )
            rows.append(signal_row(episode_no, episode_no, characters))

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual([row for row in inventory if row["work_role"] == "main_protagonist"], [])
        top_rows = [row for row in inventory if row["protagonist_evidence"]["rank"] <= 2]
        self.assertEqual(len(top_rows), 2)
        self.assertTrue(all(row["protagonist_evidence"]["score"] == 0.0 for row in top_rows))

    def test_inventory_v3_work_level_resolution_selects_existing_candidate_only(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 11):
            characters = [
                signal_character(
                    character_key="protagonist:named:득구" if episode_no <= 5 else "named:득구",
                    display_name="득구",
                    is_protagonist=episode_no <= 5,
                    role_in_episode="lead",
                    voice_mode="dialogue",
                    scene_weight="high",
                ),
            ]
            if episode_no in {3, 4}:
                characters.append(
                    signal_character(
                        character_key="named:설총",
                        display_name="설총",
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="medium",
                    )
                )
            rows.append(signal_row(episode_no, episode_no, characters))

        base_inventory = module.aggregate_character_inventory_v3_rows(rows)
        deukgu_key = next(row["canonical_character_key"] for row in base_inventory if row["display_name"] == "득구")
        resolution = {
            "schema_version": module.WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
            "decision": "RESOLVED",
            "work_protagonist_key": deukgu_key,
            "confidence": "medium",
            "reason_code": "single_clear",
            "rationale": "작품 단위 연속성이 득구 쪽에 있다.",
            "safety_flags": {
                "requires_identity_merge": False,
                "selected_candidate_eligible": True,
                "multiple_plausible_main_candidates": False,
            },
        }

        inventory = module.aggregate_character_inventory_v3_rows(rows, protagonist_resolution=resolution)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual([row["display_name"] for row in main_rows], ["득구"])
        self.assertEqual(main_rows[0]["work_protagonist_resolution"]["decision"], "RESOLVED")
        self.assertFalse(any(row["display_name"] == "설총" and row["is_protagonist"] for row in inventory))

    def test_inventory_v3_resolved_opening_replaces_locked_main(self):
        module = load_module()
        initial_rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:란",
                        display_name="란",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]
        locked_main = next(
            row
            for row in module.aggregate_character_inventory_v3_rows(initial_rows)
            if row["work_role"] == "main_protagonist"
        )
        all_rows = [
            *initial_rows,
            *[
                signal_row(
                    episode_no,
                    episode_no,
                    [
                        signal_character(
                            character_key="protagonist:named:카인",
                            display_name="카인",
                            is_protagonist=True,
                            role_in_episode="lead",
                            voice_mode="dialogue",
                            scene_weight="high",
                        )
                    ],
                )
                for episode_no in range(4, 9)
            ],
        ]
        unlocked_inventory = module.aggregate_character_inventory_v3_rows(all_rows)
        kain_key = next(
            row["canonical_character_key"]
            for row in unlocked_inventory
            if row["display_name"] == "카인"
        )
        later_resolution = {
            "schema_version": module.WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
            "decision": "RESOLVED",
            "work_protagonist_key": kain_key,
            "work_protagonist_keys": [kain_key],
            "confidence": "high",
            "reason_code": "single_clear",
            "safety_flags": {
                "requires_identity_merge": False,
                "selected_candidate_eligible": True,
                "multiple_plausible_main_candidates": False,
            },
        }

        inventory = module.aggregate_character_inventory_v3_rows(
            all_rows,
            protagonist_resolution=later_resolution,
            locked_protagonist_rows=[locked_main],
        )

        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]
        self.assertEqual([row["display_name"] for row in main_rows], ["카인"])
        self.assertEqual(
            main_rows[0]["superseded_protagonist_scope_keys"],
            ["character:란"],
        )

    def test_explicit_resolver_rejection_can_replace_a_stale_main_lock(self):
        module = load_module()
        locked_main = {
            "canonical_character_key": "character:당신",
            "display_name": "당신",
            "source_character_keys": ["protagonist:first_person"],
            "distinct_episode_count": 5,
            "work_role": "main_protagonist",
            "identity_conflict_reasons": [],
        }
        current_wrong = {
            **locked_main,
            "work_role": "major_character",
        }
        current_main = {
            "canonical_character_key": "character:추종자",
            "display_name": "추종자",
            "source_character_keys": ["protagonist:named:추종자"],
            "distinct_episode_count": 15,
            "work_role": "main_protagonist",
            "role_confidence": "high",
            "classification_status": "AUTO_RESOLVED",
            "review_reasons": [],
            "identity_conflict_reasons": [],
            "work_protagonist_resolution": {
                "decision": "RESOLVED",
                "work_protagonist_key": "character:추종자",
                "work_protagonist_keys": ["character:추종자"],
                "confidence": "high",
                "rejected": [
                    {"key": "character:당신", "reason": "호칭일 뿐 독립 인물이 아니다."}
                ],
            },
        }

        matched_scope_keys = module._apply_locked_work_protagonist_rows(
            [current_wrong, current_main],
            [locked_main],
        )

        self.assertEqual(matched_scope_keys, set())
        self.assertEqual(current_wrong["work_role"], "major_character")
        self.assertEqual(current_main["work_role"], "main_protagonist")
        self.assertEqual(
            current_main["superseded_protagonist_scope_keys"],
            ["character:당신"],
        )

    def test_locked_main_can_move_to_known_identity_group_surface(self):
        module = load_module()
        locked_main = {
            "canonical_character_key": "character:방호영",
            "display_name": "방호영",
            "source_character_keys": ["named:방호영"],
            "work_role": "main_protagonist",
            "identity_group_key": "character:방호영",
            "protagonist_identity_scope_keys": ["character:방호영", "character:조렌테이머"],
        }
        current_surface = {
            "canonical_character_key": "character:조렌테이머",
            "display_name": "조렌테이머",
            "source_character_keys": ["named:조렌테이머"],
            "distinct_episode_count": 12,
            "work_role": "major_character",
            "role_confidence": "medium",
            "classification_status": "AUTO_RESOLVED",
            "review_reasons": [],
        }

        matched_scope_keys = module._apply_locked_work_protagonist_rows(
            [current_surface],
            [locked_main],
        )

        self.assertEqual(matched_scope_keys, {"character:방호영"})
        self.assertEqual(current_surface["work_role"], "main_protagonist")
        self.assertEqual(current_surface["identity_group_key"], "character:방호영")
        self.assertEqual(
            current_surface["protagonist_identity_scope_keys"],
            ["character:방호영", "character:조렌테이머"],
        )

    def test_locked_identity_group_prefers_current_resolved_surface_over_old_exact_row(self):
        module = load_module()
        locked_main = {
            "canonical_character_key": "character:방호영",
            "display_name": "방호영",
            "source_character_keys": ["named:방호영"],
            "work_role": "main_protagonist",
            "identity_group_key": "character:방호영",
            "protagonist_identity_scope_keys": ["character:방호영", "character:조렌테이머"],
        }
        rows = [
            {
                "canonical_character_key": "character:방호영",
                "display_name": "방호영",
                "source_character_keys": ["named:방호영"],
                "distinct_episode_count": 15,
                "work_role": "major_character",
            },
            {
                "canonical_character_key": "character:조렌테이머",
                "display_name": "조렌테이머",
                "source_character_keys": ["named:조렌테이머"],
                "distinct_episode_count": 14,
                "work_role": "main_protagonist",
            },
        ]

        module._apply_locked_work_protagonist_rows(rows, [locked_main])

        self.assertEqual(
            [row["display_name"] for row in rows if row["work_role"] == "main_protagonist"],
            ["조렌테이머"],
        )

    def test_locked_main_rejects_source_key_only_match_with_identity_conflict(self):
        module = load_module()
        locked_main = {
            "canonical_character_key": "character:민준",
            "display_name": "민준",
            "source_character_keys": ["named:민준"],
            "work_role": "main_protagonist",
        }
        conflicting_candidate = {
            "canonical_character_key": "character:다른민준",
            "display_name": "다른 민준",
            "source_character_keys": ["named:민준"],
            "identity_conflict_reasons": ["cannot_link_name_conflict"],
            "distinct_episode_count": 10,
            "work_role": "main_protagonist",
            "classification_status": "NEEDS_REVIEW",
            "review_reasons": ["cannot_link_name_conflict"],
        }

        matched_scope_keys = module._apply_locked_work_protagonist_rows(
            [conflicting_candidate],
            [locked_main],
        )

        self.assertEqual(matched_scope_keys, set())
        self.assertEqual(conflicting_candidate["work_role"], "major_character")
        self.assertEqual(conflicting_candidate["review_reasons"], ["cannot_link_name_conflict"])

    def test_locked_main_moves_to_current_resolved_surface_with_old_source_provenance(self):
        module = load_module()
        locked_main = {
            "canonical_character_key": "character:방호영",
            "display_name": "방호영",
            "source_character_keys": ["protagonist:named:방호영"],
            "work_role": "main_protagonist",
            "identity_group_key": "character:방호영",
        }
        current_surface = {
            "canonical_character_key": "character:조렌테이머",
            "display_name": "조렌테이머",
            "source_character_keys": [
                "protagonist:named:방호영",
                "protagonist:named:조렌테이머",
            ],
            "distinct_episode_count": 8,
            "work_role": "main_protagonist",
            "role_confidence": "high",
            "classification_status": "AUTO_RESOLVED",
            "review_reasons": [],
            "identity_conflict_reasons": [],
        }

        matched_scope_keys = module._apply_locked_work_protagonist_rows(
            [current_surface],
            [locked_main],
        )

        self.assertEqual(matched_scope_keys, {"character:방호영"})
        self.assertEqual(current_surface["work_role"], "main_protagonist")
        self.assertEqual(current_surface["identity_group_key"], "character:방호영")
        self.assertEqual(
            current_surface["protagonist_identity_scope_keys"],
            ["character:방호영", "character:조렌테이머"],
        )

    def test_locked_main_does_not_move_on_source_overlap_without_current_main_resolution(self):
        module = load_module()
        locked_main = {
            "canonical_character_key": "character:방호영",
            "display_name": "방호영",
            "source_character_keys": ["protagonist:named:방호영"],
            "work_role": "main_protagonist",
        }
        supporting_character = {
            "canonical_character_key": "character:조렌테이머",
            "display_name": "조렌테이머",
            "source_character_keys": ["protagonist:named:방호영"],
            "distinct_episode_count": 8,
            "work_role": "major_character",
            "identity_conflict_reasons": [],
        }

        matched_scope_keys = module._apply_locked_work_protagonist_rows(
            [supporting_character],
            [locked_main],
        )

        self.assertEqual(matched_scope_keys, set())
        self.assertEqual(supporting_character["work_role"], "major_character")

    def test_locked_main_rejects_exact_scope_candidate_with_identity_conflict(self):
        module = load_module()
        locked_main = {
            "canonical_character_key": "character:민준",
            "display_name": "민준",
            "source_character_keys": ["named:민준"],
            "work_role": "main_protagonist",
        }
        conflicting_candidate = {
            "canonical_character_key": "character:민준",
            "display_name": "민준",
            "source_character_keys": ["named:민준"],
            "identity_conflict_reasons": ["cannot_link_name_conflict"],
            "distinct_episode_count": 10,
            "work_role": "main_protagonist",
            "classification_status": "NEEDS_REVIEW",
            "review_reasons": ["cannot_link_name_conflict"],
        }

        matched_scope_keys = module._apply_locked_work_protagonist_rows(
            [conflicting_candidate],
            [locked_main],
        )

        self.assertEqual(matched_scope_keys, set())
        self.assertEqual(conflicting_candidate["work_role"], "major_character")
        self.assertEqual(conflicting_candidate["review_reasons"], ["cannot_link_name_conflict"])

    def test_inventory_v3_preserves_locked_main_scope_when_current_signals_do_not_rebuild_it(self):
        module = load_module()
        cur = object()
        locked_main = {
            "canonical_character_key": "character:란",
            "display_name": "란",
            "work_role": "main_protagonist",
        }

        with patch.object(
            module,
            "fetch_active_character_inventory_map",
            return_value={"character:란": locked_main},
        ), patch.object(
            module,
            "aggregate_character_inventory_v3_rows",
            return_value=[],
        ), patch.object(module, "deactivate_missing_active_scopes") as deactivate_missing:
            counts = module.build_character_inventory_v3_summaries_from_signal_rows(
                cur,
                product_id=687,
                signal_rows=[{"summary_text": "{}"}],
            )

        self.assertEqual(counts, (0, 1))
        deactivate_missing.assert_called_once_with(
            cur,
            687,
            "character_inventory_v3",
            {"character:란"},
        )

    def test_inventory_v3_demotes_superseded_lock_without_deleting_old_character(self):
        module = load_module()
        cur = object()
        old_main = {
            "canonical_character_key": "character:당신",
            "display_name": "당신",
            "work_role": "main_protagonist",
            "identity_status": "RESOLVED_NAMED",
            "identity_conflict_reasons": [],
            "entity_kind": "person",
            "distinct_episode_count": 5,
            "voice_mode_counts": {"dialogue": 2, "monologue": 0},
            "rp_signal_quality": {"status": "summary_ready", "needs_review": False},
            "display_safety": {"status": "pass", "reason": "resolved_named_identity"},
            "public_chat_eligible": True,
            "public_slot_eligible": True,
        }
        new_main = {
            "canonical_character_key": "character:추종자",
            "display_name": "추종자",
            "work_role": "main_protagonist",
            "identity_status": "RESOLVED_NAMED",
            "identity_conflict_reasons": [],
            "entity_kind": "person",
            "distinct_episode_count": 15,
            "voice_mode_counts": {"dialogue": 10, "monologue": 0},
            "rp_signal_quality": {"status": "summary_ready", "needs_review": False},
            "superseded_protagonist_scope_keys": ["character:당신"],
        }
        upserted_items: list[dict] = []

        with patch.object(
            module,
            "fetch_active_character_inventory_map",
            return_value={"character:당신": old_main},
        ), patch.object(
            module,
            "aggregate_character_inventory_v3_rows",
            return_value=[new_main],
        ), patch.object(
            module,
            "reconcile_character_inventory_v3_scope_keys",
            side_effect=lambda rows, **_kwargs: rows,
        ), patch.object(
            module,
            "upsert_character_inventory_v3_item",
            side_effect=lambda _cur, *, product_id, item: upserted_items.append(dict(item)) or True,
        ), patch.object(module, "deactivate_missing_active_scopes") as deactivate_missing:
            module.build_character_inventory_v3_summaries_from_signal_rows(
                cur,
                product_id=1105,
                signal_rows=[{"summary_text": "{}"}],
            )

        by_scope = {
            item["canonical_character_key"]: item
            for item in upserted_items
        }
        self.assertEqual(by_scope["character:추종자"]["work_role"], "main_protagonist")
        self.assertEqual(by_scope["character:당신"]["work_role"], "major_character")
        self.assertFalse(by_scope["character:당신"]["is_protagonist"])
        deactivate_missing.assert_called_once_with(
            cur,
            1105,
            "character_inventory_v3",
            {"character:당신", "character:추종자"},
        )

    def test_inventory_v3_authoritative_main_upgrade_is_not_blocked_by_major_lkg(self):
        module = load_module()
        cur = object()
        old_main = {
            "canonical_character_key": "character:당신",
            "display_name": "당신",
            "work_role": "main_protagonist",
            "distinct_episode_count": 1,
            "public_chat_eligible": False,
            "public_slot_eligible": False,
        }
        old_major = {
            "canonical_character_key": "character:추종자",
            "display_name": "추종자",
            "work_role": "major_character",
            "public_chat_eligible": True,
            "public_slot_eligible": False,
        }
        resolution = {
            "schema_version": module.WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
            "decision": "RESOLVED",
            "work_protagonist_key": "character:추종자",
            "work_protagonist_keys": ["character:추종자"],
            "confidence": "high",
            "reason_code": "opening_role_continuity",
            "rejected": [],
            "safety_flags": {
                "requires_identity_merge": False,
                "selected_candidate_eligible": True,
                "multiple_plausible_main_candidates": False,
            },
        }
        fresh_main = {
            "canonical_character_key": "character:추종자",
            "display_name": "추종자",
            "work_role": "main_protagonist",
            "identity_status": "RESOLVED_NAMED",
            "identity_conflict_reasons": [],
            "distinct_episode_count": 30,
            "public_chat_eligible": False,
            "public_slot_eligible": False,
            "work_protagonist_resolution": resolution,
            "superseded_protagonist_scope_keys": ["character:당신"],
        }
        upserted_items: list[dict] = []

        with patch.object(
            module,
            "fetch_active_character_inventory_map",
            return_value={
                "character:당신": old_main,
                "character:추종자": old_major,
            },
        ), patch.object(
            module,
            "aggregate_character_inventory_v3_rows",
            return_value=[fresh_main],
        ), patch.object(
            module,
            "reconcile_character_inventory_v3_scope_keys",
            side_effect=lambda rows, **_kwargs: rows,
        ), patch.object(
            module,
            "_refresh_character_inventory_v3_serving_fields",
            side_effect=lambda _item: None,
        ), patch.object(
            module,
            "upsert_character_inventory_v3_item",
            side_effect=lambda _cur, *, product_id, item: upserted_items.append(dict(item)) or True,
        ), patch.object(module, "deactivate_missing_active_scopes"):
            module.build_character_inventory_v3_summaries_from_signal_rows(
                cur,
                product_id=1105,
                signal_rows=[{"summary_text": "{}"}],
                protagonist_resolution=resolution,
            )

        by_scope = {
            item["canonical_character_key"]: item
            for item in upserted_items
        }
        self.assertEqual(
            by_scope["character:추종자"]["work_role"],
            "main_protagonist",
        )
        self.assertEqual(
            by_scope["character:당신"]["work_role"],
            "major_character",
        )

    def test_inventory_v3_resolved_result_cannot_persist_without_a_main(self):
        module = load_module()
        resolution = {
            "schema_version": module.WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
            "decision": "RESOLVED",
            "work_protagonist_key": "character:추종자",
            "work_protagonist_keys": ["character:추종자"],
            "confidence": "high",
            "reason_code": "opening_role_continuity",
            "rejected": [],
            "safety_flags": {
                "requires_identity_merge": False,
                "selected_candidate_eligible": True,
                "multiple_plausible_main_candidates": False,
            },
        }
        only_major = {
            "canonical_character_key": "character:추종자",
            "display_name": "추종자",
            "work_role": "major_character",
            "distinct_episode_count": 30,
        }

        with patch.object(
            module,
            "fetch_active_character_inventory_map",
            return_value={},
        ), patch.object(
            module,
            "aggregate_character_inventory_v3_rows",
            return_value=[only_major],
        ), patch.object(
            module,
            "reconcile_character_inventory_v3_scope_keys",
            side_effect=lambda rows, **_kwargs: rows,
        ), patch.object(
            module,
            "upsert_character_inventory_v3_item",
            return_value=True,
        ), patch.object(module, "deactivate_missing_active_scopes"):
            with self.assertRaisesRegex(
                ValueError,
                "resolved protagonist inventory has no persisted main",
            ):
                module.build_character_inventory_v3_summaries_from_signal_rows(
                    object(),
                    product_id=1105,
                    signal_rows=[{"summary_text": "{}"}],
                    protagonist_resolution=resolution,
                )

    def test_inventory_v3_does_not_overwrite_locked_main_with_conflicting_same_scope_row(self):
        module = load_module()
        cur = object()
        locked_main = {
            "canonical_character_key": "character:민준",
            "display_name": "민준",
            "work_role": "main_protagonist",
        }
        conflicting_current_row = {
            "canonical_character_key": "character:민준",
            "display_name": "민준",
            "work_role": "major_character",
            "identity_conflict_reasons": ["cannot_link_name_conflict"],
        }

        with patch.object(
            module,
            "fetch_active_character_inventory_map",
            return_value={"character:민준": locked_main},
        ), patch.object(
            module,
            "aggregate_character_inventory_v3_rows",
            return_value=[conflicting_current_row],
        ), patch.object(
            module,
            "upsert_character_inventory_v3_item",
        ) as upsert_item, patch.object(
            module,
            "deactivate_missing_active_scopes",
        ) as deactivate_missing:
            counts = module.build_character_inventory_v3_summaries_from_signal_rows(
                cur,
                product_id=687,
                signal_rows=[{"summary_text": "{}"}],
            )

        self.assertEqual(counts, (0, 1))
        upsert_item.assert_not_called()
        deactivate_missing.assert_called_once_with(
            cur,
            687,
            "character_inventory_v3",
            {"character:민준"},
        )

    def test_locked_main_still_accumulates_new_episode_and_voice_evidence(self):
        module = load_module()
        initial_rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:란",
                        display_name="란",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]
        locked_main = next(
            row
            for row in module.aggregate_character_inventory_v3_rows(initial_rows)
            if row["work_role"] == "main_protagonist"
        )
        expanded_rows = [
            *initial_rows,
            *[
                signal_row(
                    episode_no,
                    episode_no,
                    [
                        signal_character(
                            character_key="named:란",
                            display_name="란",
                            is_work_protagonist=True,
                            is_episode_focal=True,
                            role_in_episode="lead",
                            voice_mode="dialogue",
                            scene_weight="high",
                        )
                    ],
                )
                for episode_no in range(4, 6)
            ],
        ]

        inventory = module.aggregate_character_inventory_v3_rows(
            expanded_rows,
            locked_protagonist_rows=[locked_main],
        )
        main = next(row for row in inventory if row["work_role"] == "main_protagonist")

        self.assertEqual(main["display_name"], "란")
        self.assertEqual(main["latest_seen_episode_no"], 5)
        self.assertEqual(main["distinct_episode_count"], 5)
        self.assertEqual(main["voice_mode_counts"]["dialogue"], 5)

    def test_locked_co_main_set_is_preserved(self):
        module = load_module()
        locked_rows = [
            {
                "canonical_character_key": f"character:{name}",
                "display_name": name,
                "source_character_keys": [f"named:{name}"],
                "work_role": "main_protagonist",
            }
            for name in ["득구", "한설총"]
        ]
        rows = [
            {
                "canonical_character_key": f"character:{name}",
                "display_name": name,
                "source_character_keys": [f"named:{name}"],
                "distinct_episode_count": 8,
                "work_role": "main_protagonist" if name == "새후보" else "major_character",
            }
            for name in ["득구", "한설총", "새후보"]
        ]

        matched_scope_keys = module._apply_locked_work_protagonist_rows(rows, locked_rows)

        self.assertEqual(matched_scope_keys, {"character:득구", "character:한설총"})
        self.assertEqual(
            {row["display_name"] for row in rows if row["work_role"] == "main_protagonist"},
            {"득구", "한설총"},
        )

    def test_inventory_v3_work_level_resolution_preserves_other_chat_targets(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 8):
            rows.append(
                signal_row(
                    episode_no,
                    episode_no,
                    [
                        signal_character(
                            character_key="protagonist:named:추종자" if episode_no <= 5 else "named:추종자",
                            display_name="추종자",
                            is_protagonist=episode_no <= 5,
                            is_work_protagonist=episode_no <= 5,
                            is_episode_focal=episode_no <= 5,
                            role_in_episode="lead",
                            voice_mode="dialogue",
                            scene_weight="high",
                        ),
                        signal_character(
                            character_key="named:신미아",
                            display_name="신미아",
                            is_episode_focal=episode_no in {2, 4, 6},
                            role_in_episode="lead" if episode_no in {2, 4, 6} else "counterpart",
                            voice_mode="dialogue",
                            scene_weight="high",
                        ),
                    ],
                )
            )

        base_inventory = module.aggregate_character_inventory_v3_rows(rows)
        follower_key = next(row["canonical_character_key"] for row in base_inventory if row["display_name"] == "추종자")
        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution={
                "schema_version": module.WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
                "decision": "RESOLVED",
                "work_protagonist_key": follower_key,
                "confidence": "high",
                "reason_code": "single_clear",
                "rationale": "추종자가 작품 전체 목표와 서술 중심에서 우세하다.",
                "rejected": [{"key": "character:신미아", "reason": "주요 인물이지만 작품 대표 주인공은 아니다."}],
                "safety_flags": {
                    "requires_identity_merge": False,
                    "selected_candidate_eligible": True,
                    "multiple_plausible_main_candidates": False,
                },
            },
        )
        by_name = {row["display_name"]: row for row in inventory}
        rp_target_names = [
            target["display_name"]
            for target in module.build_inventory_rp_targets(
                {row["canonical_character_key"]: row for row in inventory}
            )
        ]

        self.assertEqual(by_name["추종자"]["work_role"], "main_protagonist")
        self.assertTrue(by_name["추종자"]["public_chat_eligible"])
        self.assertEqual(by_name["신미아"]["work_role"], "major_character")
        self.assertFalse(by_name["신미아"]["is_protagonist"])
        self.assertTrue(by_name["신미아"]["public_chat_eligible"])
        self.assertIn("추종자", rp_target_names)
        self.assertIn("신미아", rp_target_names)

    def test_inventory_v3_work_level_resolution_accepts_co_main_protagonists(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 11):
            rows.append(
                signal_row(
                    episode_no,
                    episode_no,
                    [
                        signal_character(
                            character_key="protagonist:named:득구" if episode_no <= 5 else "named:득구",
                            display_name="득구",
                            is_protagonist=episode_no <= 5,
                            is_work_protagonist=episode_no <= 5,
                            is_episode_focal=True,
                            role_in_episode="lead",
                            voice_mode="dialogue",
                            scene_weight="high",
                        ),
                        signal_character(
                            character_key="protagonist:named:한설총" if episode_no > 5 else "named:한설총",
                            display_name="한설총",
                            is_protagonist=episode_no > 5,
                            is_work_protagonist=episode_no > 5,
                            is_episode_focal=True,
                            role_in_episode="lead",
                            voice_mode="dialogue",
                            scene_weight="high",
                        ),
                    ],
                )
            )

        base_inventory = module.aggregate_character_inventory_v3_rows(rows)
        deukgu_key = next(row["canonical_character_key"] for row in base_inventory if row["display_name"] == "득구")
        seolchong_key = next(row["canonical_character_key"] for row in base_inventory if row["display_name"] == "한설총")
        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution={
                "schema_version": module.WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
                "decision": "RESOLVED",
                "work_protagonist_key": deukgu_key,
                "work_protagonist_keys": [deukgu_key, seolchong_key],
                "confidence": "medium",
                "reason_code": "co_main_protagonists",
                "rationale": "득구와 한설총이 작품 전체 행동/서술 중심을 나눠 갖는다.",
                "rejected": [],
                "safety_flags": {
                    "requires_identity_merge": False,
                    "selected_candidate_eligible": True,
                    "multiple_plausible_main_candidates": True,
                },
            },
        )

        by_name = {row["display_name"]: row for row in inventory}
        main_names = [row["display_name"] for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual(main_names, ["득구", "한설총"])
        self.assertTrue(by_name["득구"]["is_protagonist"])
        self.assertTrue(by_name["한설총"]["is_protagonist"])
        self.assertEqual(by_name["득구"]["work_protagonist_resolution"]["work_protagonist_keys"], [deukgu_key, seolchong_key])
        self.assertEqual(by_name["한설총"]["work_protagonist_resolution"]["reason_code"], "co_main_protagonists")

    def test_inventory_v3_work_level_resolution_does_not_expand_near_tie_selection(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 11):
            rows.append(
                signal_row(
                    episode_no,
                    episode_no,
                    [
                        signal_character(
                            character_key="protagonist:named:득구" if episode_no <= 5 else "named:득구",
                            display_name="득구",
                            is_protagonist=episode_no <= 5,
                            is_work_protagonist=episode_no <= 5,
                            is_episode_focal=True,
                            role_in_episode="lead",
                            voice_mode="dialogue",
                            scene_weight="high",
                        ),
                        signal_character(
                            character_key="protagonist:named:한설총" if episode_no > 5 else "named:한설총",
                            display_name="한설총",
                            is_protagonist=episode_no > 5,
                            is_work_protagonist=episode_no > 5,
                            is_episode_focal=True,
                            role_in_episode="lead",
                            voice_mode="dialogue",
                            scene_weight="high",
                        ),
                    ],
                )
            )

        base_inventory = module.aggregate_character_inventory_v3_rows(rows)
        deukgu_key = next(row["canonical_character_key"] for row in base_inventory if row["display_name"] == "득구")
        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution={
                "schema_version": module.WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
                "decision": "RESOLVED",
                "work_protagonist_key": deukgu_key,
                "work_protagonist_keys": [],
                "confidence": "medium",
                "reason_code": "single_clear",
                "rationale": "모델은 득구를 골랐지만 지표상 한설총도 근접 동률이다.",
                "rejected": [],
                "safety_flags": {
                    "requires_identity_merge": False,
                    "selected_candidate_eligible": True,
                    "multiple_plausible_main_candidates": False,
                },
            },
        )

        main_names = [row["display_name"] for row in inventory if row["work_role"] == "main_protagonist"]
        by_name = {row["display_name"]: row for row in inventory}

        self.assertEqual(main_names, ["득구"])
        self.assertEqual(by_name["득구"]["work_protagonist_resolution"]["work_protagonist_keys"], [deukgu_key])
        self.assertEqual(by_name["득구"]["work_protagonist_resolution"]["reason_code"], "single_clear")
        self.assertFalse(by_name["한설총"]["is_protagonist"])

    def test_inventory_v3_work_level_resolution_does_not_expand_rejected_near_tie(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 11):
            rows.append(
                signal_row(
                    episode_no,
                    episode_no,
                    [
                        signal_character(
                            character_key="protagonist:named:득구" if episode_no <= 5 else "named:득구",
                            display_name="득구",
                            is_protagonist=episode_no <= 5,
                            is_work_protagonist=episode_no <= 5,
                            is_episode_focal=True,
                            role_in_episode="lead",
                            voice_mode="dialogue",
                            scene_weight="high",
                        ),
                        signal_character(
                            character_key="protagonist:named:한설총" if episode_no > 5 else "named:한설총",
                            display_name="한설총",
                            is_protagonist=episode_no > 5,
                            is_work_protagonist=episode_no > 5,
                            is_episode_focal=True,
                            role_in_episode="lead",
                            voice_mode="dialogue",
                            scene_weight="high",
                        ),
                    ],
                )
            )

        base_inventory = module.aggregate_character_inventory_v3_rows(rows)
        deukgu_key = next(row["canonical_character_key"] for row in base_inventory if row["display_name"] == "득구")
        seolchong_key = next(row["canonical_character_key"] for row in base_inventory if row["display_name"] == "한설총")
        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution={
                "schema_version": module.WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
                "decision": "RESOLVED",
                "work_protagonist_key": deukgu_key,
                "work_protagonist_keys": [],
                "confidence": "medium",
                "reason_code": "single_clear",
                "rationale": "모델은 득구를 단일 주인공으로 보고 한설총은 명시 제외했다.",
                "rejected": [{"key": seolchong_key, "reason": "중요 조력자지만 작품 대표 주인공은 아니다."}],
                "safety_flags": {
                    "requires_identity_merge": False,
                    "selected_candidate_eligible": True,
                    "multiple_plausible_main_candidates": False,
                },
            },
        )

        main_names = [row["display_name"] for row in inventory if row["work_role"] == "main_protagonist"]
        by_name = {row["display_name"]: row for row in inventory}

        self.assertEqual(main_names, ["득구"])
        self.assertEqual(by_name["득구"]["work_protagonist_resolution"]["work_protagonist_keys"], [deukgu_key])
        self.assertEqual(by_name["득구"]["work_protagonist_resolution"]["reason_code"], "single_clear")
        self.assertFalse(by_name["한설총"]["is_protagonist"])

    def test_inventory_v3_work_level_resolution_keeps_near_tie_unresolved(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 11):
            rows.append(
                signal_row(
                    episode_no,
                    episode_no,
                    [
                        signal_character(
                            character_key="protagonist:named:득구" if episode_no <= 5 else "named:득구",
                            display_name="득구",
                            is_protagonist=episode_no <= 5,
                            is_work_protagonist=episode_no <= 5,
                            is_episode_focal=True,
                            role_in_episode="lead",
                            voice_mode="dialogue",
                            scene_weight="high",
                        ),
                        signal_character(
                            character_key="protagonist:named:한설총" if episode_no > 5 else "named:한설총",
                            display_name="한설총",
                            is_protagonist=episode_no > 5,
                            is_work_protagonist=episode_no > 5,
                            is_episode_focal=True,
                            role_in_episode="lead",
                            voice_mode="dialogue",
                            scene_weight="high",
                        ),
                    ],
                )
            )

        base_inventory = module.aggregate_character_inventory_v3_rows(rows)
        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution={
                "schema_version": module.WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
                "decision": "UNRESOLVED",
                "work_protagonist_key": None,
                "work_protagonist_keys": [],
                "confidence": "low",
                "reason_code": "ambiguous_dual_lead",
                "rationale": "득구와 한설총이 거의 동률이다.",
                "rejected": [],
                "safety_flags": {
                    "requires_identity_merge": False,
                    "selected_candidate_eligible": False,
                    "multiple_plausible_main_candidates": True,
                },
            },
        )

        main_names = [row["display_name"] for row in inventory if row["work_role"] == "main_protagonist"]
        by_name = {row["display_name"]: row for row in inventory}

        self.assertEqual(main_names, [])
        self.assertTrue(all(not row["is_protagonist"] for row in by_name.values()))
        self.assertTrue(
            all(
                row["work_protagonist_resolution"]["decision"] == "UNRESOLVED"
                for row in by_name.values()
            )
        )

    def test_inventory_v3_work_level_resolution_unresolved_has_no_legacy_fallback(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 21):
            rows.append(
                signal_row(
                    episode_no,
                    episode_no,
                    [
                        signal_character(
                            character_key="protagonist:named:존" if episode_no <= 5 else "named:존",
                            display_name="존",
                            is_protagonist=episode_no <= 5,
                            role_in_episode="lead",
                            voice_mode="dialogue",
                            scene_weight="high",
                        )
                    ],
                )
            )

        legacy_inventory = module.aggregate_character_inventory_v3_rows(rows)
        self.assertEqual(legacy_inventory[0]["work_role"], "main_protagonist")

        unresolved_inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution={
                "schema_version": module.WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
                "decision": "UNRESOLVED",
                "confidence": "low",
                "reason_code": "insufficient_evidence",
                "safety_flags": {
                    "requires_identity_merge": False,
                    "selected_candidate_eligible": False,
                    "multiple_plausible_main_candidates": True,
                },
            },
        )

        self.assertEqual([row for row in unresolved_inventory if row["work_role"] == "main_protagonist"], [])
        self.assertIn("WORK_PROTAGONIST_UNRESOLVED", unresolved_inventory[0]["review_reasons"])

    def test_inventory_v3_work_level_resolution_keeps_blocked_title_internal_only(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 5):
            rows.append(
                signal_row(
                    episode_no,
                    episode_no,
                    [
                        signal_character(
                            character_key="protagonist:named:제일황자" if episode_no <= 2 else "named:제일황자",
                            display_name="제 일 황자",
                            aliases=["제 일 황자"],
                            is_protagonist=episode_no <= 2,
                            role_in_episode="lead",
                            voice_mode="dialogue",
                            scene_weight="high",
                        )
                    ],
                )
            )

        base_inventory = module.aggregate_character_inventory_v3_rows(rows)
        blocked_key = base_inventory[0]["canonical_character_key"]
        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution={
                "schema_version": module.WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
                "decision": "RESOLVED",
                "work_protagonist_key": blocked_key,
                "confidence": "high",
                "reason_code": "single_clear",
                "safety_flags": {
                    "requires_identity_merge": False,
                    "selected_candidate_eligible": True,
                    "multiple_plausible_main_candidates": False,
                },
            },
        )

        self.assertEqual(
            [row["canonical_character_key"] for row in inventory if row["work_role"] == "main_protagonist"],
            [blocked_key],
        )
        self.assertFalse(inventory[0]["public_chat_eligible"])
        self.assertFalse(inventory[0]["public_slot_eligible"])

    def test_inventory_v3_does_not_attach_generic_first_person_to_top_named_candidate(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="나",
                        aliases=["나"],
                        is_protagonist=True,
                        is_first_person=True,
                        role_in_episode="lead",
                        voice_mode="monologue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="named:백이현",
                        display_name="백이현",
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:백이현",
                        display_name="백이현",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        by_display_name = {row["display_name"]: row for row in inventory}

        self.assertIn("나", by_display_name)
        self.assertIn("백이현", by_display_name)
        self.assertEqual(by_display_name["나"]["source_character_keys"], ["protagonist:first_person"])
        self.assertEqual(by_display_name["나"]["identity_status"], "UNRESOLVED")
        self.assertIn("unresolved_generic_first_person", by_display_name["나"]["identity_conflict_reasons"])
        self.assertFalse(by_display_name["나"]["is_protagonist"])
        self.assertEqual(by_display_name["나"]["protagonist_confidence"], "low")
        self.assertEqual(by_display_name["백이현"]["source_character_keys"], ["named:백이현"])

    def test_inventory_v3_generic_first_person_source_key_does_not_merge_different_named_speakers(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="남우진",
                        aliases=["남우진"],
                        is_protagonist=True,
                        is_first_person=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="송하늘",
                        aliases=["송하늘"],
                        is_protagonist=True,
                        is_first_person=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="하늘 씨",
                        aliases=["하늘 씨", "하늘"],
                        is_protagonist=True,
                        is_first_person=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        by_name = {row["display_name"]: row for row in inventory}

        self.assertIn("남우진", by_name)
        self.assertIn("송하늘", by_name)
        self.assertNotEqual(by_name["남우진"]["canonical_character_key"], by_name["송하늘"]["canonical_character_key"])
        self.assertEqual(by_name["송하늘"]["distinct_episode_count"], 2)
        self.assertIn("하늘 씨", by_name["송하늘"]["aliases"])

    def test_inventory_v3_rejects_unverified_first_person_topic_as_public_identity(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="주제",
                        aliases=["주제"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        is_first_person=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "주제")
        self.assertEqual(inventory[0]["identity_status"], "UNRESOLVED")
        self.assertIn("first_person_identity_unverified", inventory[0]["identity_conflict_reasons"])
        self.assertEqual(
            inventory[0]["display_safety"],
            {"status": "review", "reason": "first_person_identity_unverified"},
        )
        self.assertTrue(inventory[0]["is_protagonist"])
        self.assertFalse(inventory[0]["public_chat_eligible"])
        self.assertFalse(inventory[0]["public_slot_eligible"])

    def test_inventory_v3_keeps_first_person_identity_with_positive_name_signal(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="송하늘",
                        aliases=["송하늘"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        is_first_person=True,
                        social_call_names=["송하늘"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "송하늘")
        self.assertEqual(inventory[0]["identity_status"], "RESOLVED_NAMED")
        self.assertNotIn("first_person_identity_unverified", inventory[0]["identity_conflict_reasons"])
        self.assertEqual(inventory[0]["display_safety"], {"status": "pass", "reason": "resolved_named_identity"})
        self.assertTrue(inventory[0]["public_chat_eligible"])
        self.assertTrue(inventory[0]["public_slot_eligible"])

    def test_inventory_v3_does_not_merge_one_way_possession_relation_without_alias(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="주인공",
                        aliases=["주인공"],
                        is_protagonist=True,
                        is_first_person=True,
                        role_in_episode="lead",
                        voice_mode="narration_only",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "named:데시",
                                "target_label": "데시",
                                "relation_tag": "빙의",
                                "direction": "to_target",
                            }
                        ],
                    ),
                    signal_character(
                        character_key="named:데시",
                        display_name="데시",
                        aliases=["데시"],
                        role_in_episode="support",
                        voice_mode="narration_only",
                        scene_weight="low",
                    ),
                ],
            )
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"protagonist:first_person"}, source_sets)
        self.assertIn({"named:데시"}, source_sets)
        self.assertNotIn({"protagonist:first_person", "named:데시"}, source_sets)

    def test_inventory_v3_does_not_merge_possession_target_with_independent_voice(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="주인공",
                        aliases=["주인공"],
                        is_protagonist=True,
                        is_first_person=True,
                        role_in_episode="lead",
                        voice_mode="monologue",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "named:데시",
                                "target_label": "데시",
                                "relation_tag": "빙의",
                                "direction": "to_target",
                            }
                        ],
                    ),
                    signal_character(
                        character_key="named:데시",
                        display_name="데시",
                        aliases=["데시"],
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "protagonist:first_person",
                                "target_label": "주인공",
                                "relation_tag": "빙의당함",
                                "direction": "from_target",
                            }
                        ],
                    ),
                ],
            )
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"protagonist:first_person"}, source_sets)
        self.assertIn({"named:데시"}, source_sets)
        self.assertNotIn({"protagonist:first_person", "named:데시"}, source_sets)

    def test_inventory_v3_does_not_merge_recall_memory_relation_as_identity(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:주인공",
                        display_name="주인공",
                        aliases=["주인공"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="narration_only",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "named:사촌누나",
                                "target_label": "사촌 누나",
                                "relation_tag": "회귀 전 기억",
                                "direction": "to_target",
                            }
                        ],
                    ),
                    signal_character(
                        character_key="named:사촌누나",
                        display_name="사촌 누나",
                        aliases=["사촌 누나"],
                        role_in_episode="support",
                        voice_mode="narration_only",
                        scene_weight="medium",
                        relation_edges=[
                            {
                                "target_key": "protagonist:named:주인공",
                                "target_label": "주인공",
                                "relation_tag": "회귀 전 기억",
                                "direction": "from_target",
                            }
                        ],
                    ),
                ],
            )
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"protagonist:named:주인공"}, source_sets)
        self.assertIn({"named:사촌누나"}, source_sets)
        self.assertNotIn({"protagonist:named:주인공", "named:사촌누나"}, source_sets)

    def test_inventory_v3_does_not_merge_named_protagonist_into_possession_target_by_relation_only(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:추종자",
                        display_name="추종자",
                        aliases=["추종자"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "named:신미아",
                                "target_label": "신미아",
                                "relation_tag": "빙의 대상",
                                "direction": "to_target",
                            }
                        ],
                    ),
                    signal_character(
                        character_key="named:신미아",
                        display_name="신미아",
                        aliases=["신미아"],
                        role_in_episode="support",
                        voice_mode="narration_only",
                        scene_weight="medium",
                        relation_edges=[
                            {
                                "target_key": "protagonist:named:추종자",
                                "target_label": "추종자",
                                "relation_tag": "빙의 대상",
                                "direction": "from_target",
                            }
                        ],
                    ),
                ],
            )
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"protagonist:named:추종자"}, source_sets)
        self.assertIn({"named:신미아"}, source_sets)
        self.assertNotIn({"protagonist:named:추종자", "named:신미아"}, source_sets)

    def test_inventory_v3_does_not_merge_blocked_role_source_into_named_identity(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="제 일 황자",
                        aliases=["제 일 황자"],
                        is_protagonist=True,
                        is_first_person=True,
                        role_in_episode="lead",
                        voice_mode="narration_only",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "protagonist:named:아델리트",
                                "target_label": "아델리트",
                                "relation_tag": "빙의",
                                "direction": "to_target",
                            }
                        ],
                    ),
                    signal_character(
                        character_key="protagonist:named:아델리트",
                        display_name="아델리트",
                        aliases=["아델리트"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="narration_only",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "protagonist:first_person",
                                "target_label": "제 일 황자",
                                "relation_tag": "빙의",
                                "direction": "from_target",
                            }
                        ],
                    ),
                ],
            )
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"protagonist:first_person"}, source_sets)
        self.assertIn({"protagonist:named:아델리트"}, source_sets)
        self.assertNotIn({"protagonist:first_person", "protagonist:named:아델리트"}, source_sets)

    def test_inventory_v3_keeps_related_named_characters_split(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:모어",
                        display_name="모어",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "named:란",
                                "target_label": "란",
                                "relation_tag": "대립",
                                "direction": "to_target",
                            }
                        ],
                    ),
                    signal_character(
                        character_key="named:란",
                        display_name="란",
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                ],
            )
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"protagonist:named:모어"}, source_sets)
        self.assertIn({"named:란"}, source_sets)
        self.assertNotIn({"protagonist:named:모어", "named:란"}, source_sets)
        self.assertTrue(all(row["identity_status"] != "CONFLICT" for row in inventory))
        self.assertTrue(all(row["identity_conflict_reasons"] == [] for row in inventory))

    def test_inventory_v3_canonical_key_uses_resolved_display_name_not_short_alias(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:반아슬란",
                        display_name="반 아슬란",
                        aliases=["반 아슬란", "반"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        identity_claims=[
                            {
                                "target_label": "반",
                                "claim_type": "alias_of",
                                "evidence": "반 아슬란은 반으로도 불린다",
                            }
                        ],
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:반",
                        display_name="반",
                        aliases=["반"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="named:반",
                        display_name="반",
                        aliases=["반"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(inventory[0]["display_name"], "반 아슬란")
        self.assertEqual(inventory[0]["canonical_character_key"], "character:반아슬란")

    def test_inventory_v3_merges_opening_full_name_and_short_name_variants(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:남기준",
                        display_name="남기준",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:named:기준",
                        display_name="기준",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="protagonist:named:기준",
                        display_name="기준",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]
        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["display_name"], "남기준")
        self.assertEqual(main_rows[0]["canonical_character_key"], "character:남기준")
        self.assertEqual(
            set(main_rows[0]["source_character_keys"]),
            {"protagonist:named:남기준", "protagonist:named:기준"},
        )
        self.assertEqual(main_rows[0]["episode_focal_evidence"]["episode_count"], 3)

    def test_inventory_v3_cannot_link_parent_index_tracks_component_unions(self):
        module = load_module()
        parents = [0, 1, 2, 3]
        cannot_link_parent_index = module._build_cannot_link_parent_index(
            parents,
            {(0, 2), (1, 3)},
        )

        self.assertTrue(module._would_merge_cannot_link_pair(parents, 0, 2, cannot_link_parent_index))
        self.assertFalse(module._would_merge_cannot_link_pair(parents, 0, 1, cannot_link_parent_index))

        module._union_observations_with_cannot_link_indexes(
            parents,
            0,
            1,
            [cannot_link_parent_index],
        )

        self.assertTrue(module._would_merge_cannot_link_pair(parents, 0, 2, cannot_link_parent_index))
        self.assertTrue(module._would_merge_cannot_link_pair(parents, 1, 3, cannot_link_parent_index))
        self.assertFalse(module._would_merge_cannot_link_pair(parents, 2, 3, cannot_link_parent_index))

        module._union_observations_with_cannot_link_indexes(
            parents,
            2,
            3,
            [cannot_link_parent_index],
        )

        self.assertTrue(module._would_merge_cannot_link_pair(parents, 0, 2, cannot_link_parent_index))

    def test_inventory_v3_does_not_merge_name_variants_when_same_episode_cannot_linked(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:한도윤",
                        display_name="한도윤",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "named:도윤",
                                "target_label": "도윤",
                                "relation_tag": "대립",
                                "direction": "to_target",
                            }
                        ],
                    ),
                    signal_character(
                        character_key="named:도윤",
                        display_name="도윤",
                        is_protagonist=True,
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:named:한도윤",
                        display_name="한도윤",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"protagonist:named:한도윤"}, source_sets)
        self.assertIn({"named:도윤"}, source_sets)
        self.assertNotIn({"protagonist:named:한도윤", "named:도윤"}, source_sets)

    def test_inventory_v3_does_not_hard_merge_avatar_identity_claim(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:조렌테이머",
                        display_name="조렌 테이머",
                        aliases=["조렌 테이머", "조렌"],
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="medium",
                    ),
                    signal_character(
                        character_key="protagonist:named:방호영",
                        display_name="방호영",
                        aliases=["방호영", "호영"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="narration_only",
                        scene_weight="high",
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:named:호영",
                        display_name="호영",
                        aliases=["호영", "조렌 테이머", "수호자"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        action_tags=["탐색", "단서"],
                        identity_claims=[
                            {
                                "target_label": "조렌 테이머",
                                "claim_type": "avatar_name_of",
                                "evidence": "호영이 게임 속에서 조렌 테이머로 불린다",
                            }
                        ],
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="protagonist:named:조렌테이머",
                        display_name="조렌 테이머",
                        aliases=["조렌 테이머", "변방백"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "named:호영",
                                "target_label": "호영",
                                "relation_tag": "동행",
                                "direction": "mutual",
                            }
                        ],
                    ),
                    signal_character(
                        character_key="named:호영",
                        display_name="호영",
                        aliases=["호영"],
                        role_in_episode="support",
                        voice_mode="dialogue",
                        scene_weight="medium",
                    ),
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertTrue(
            any(
                {"protagonist:named:방호영", "protagonist:named:호영", "named:호영"} <= source_set
                for source_set in source_sets
            )
        )
        self.assertTrue(
            any(
                {"named:조렌테이머", "protagonist:named:조렌테이머"} <= source_set
                for source_set in source_sets
            )
        )
        self.assertFalse(
            any(
                {
                    "named:조렌테이머",
                    "named:호영",
                    "protagonist:named:방호영",
                    "protagonist:named:조렌테이머",
                    "protagonist:named:호영",
                } <= source_set
                for source_set in source_sets
            )
        )

    def test_inventory_v3_social_persona_name_wins_chat_display_without_changing_identity_seed(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:호영",
                        display_name="호영",
                        aliases=["방호영", "호영"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        narration_names=["호영"],
                        social_call_names=["조렌 테이머"],
                        persona_names=["조렌 테이머"],
                        real_names=["방호영"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        identity_claims=[
                            {
                                "target_label": "조렌 테이머",
                                "claim_type": "avatar_name_of",
                                "evidence": "호영은 이 세계에서 조렌 테이머로 불린다",
                            }
                        ],
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:named:호영",
                        display_name="호영",
                        aliases=["호영"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        narration_names=["호영"],
                        social_call_names=["조렌 테이머"],
                        persona_names=["조렌 테이머"],
                        real_names=["방호영"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        action_tags=["탐색", "단서"],
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            protagonist_resolution={
                "schema_version": module.WORK_PROTAGONIST_RESOLUTION_FORMAT_VERSION,
                "decision": "RESOLVED",
                "work_protagonist_key": "character:호영",
                "work_protagonist_keys": ["character:호영"],
                "confidence": "high",
                "reason_code": "single_clear",
                "rejected": [],
                "safety_flags": {
                    "requires_identity_merge": False,
                    "selected_candidate_eligible": True,
                    "multiple_plausible_main_candidates": False,
                },
            },
        )
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["display_name"], "조렌 테이머")
        self.assertEqual(main_rows[0]["display_name_source"], "social_call_names")
        self.assertEqual(main_rows[0]["canonical_character_key"], "character:호영")
        self.assertEqual(main_rows[0]["social_call_names"], ["조렌 테이머"])
        self.assertEqual(main_rows[0]["persona_names"], ["조렌 테이머"])
        self.assertEqual(main_rows[0]["real_names"], ["방호영"])
        self.assertIn("호영", main_rows[0]["aliases"])
        identity_surface = main_rows[0]["identity_surface"]
        reveal_boundary = main_rows[0]["reveal_boundary"]
        self.assertEqual(identity_surface["chat_display_name"], "조렌 테이머")
        self.assertEqual(identity_surface["addressable_names"], ["조렌 테이머"])
        self.assertNotIn("호영", identity_surface["addressable_names"])
        self.assertEqual(identity_surface["private_identity_names"], ["방호영"])
        self.assertEqual(identity_surface["forbidden_until_revealed"], ["방호영"])
        self.assertEqual(identity_surface["reveal_state"], "known_to_self")
        self.assertEqual(reveal_boundary["allowed_address_names"], ["조렌 테이머"])
        self.assertEqual(reveal_boundary["must_not_address_as"], ["방호영"])
        self.assertEqual(reveal_boundary["identity_spoiler_risk"], "high")
        hash_payload = module.build_character_inventory_v3_hash_payload(main_rows[0])
        self.assertEqual(hash_payload["identity_surface"]["chat_display_name"], "조렌 테이머")
        self.assertEqual(hash_payload["reveal_boundary"]["must_not_address_as"], ["방호영"])
        state_snapshot = main_rows[0]["read_range_state_snapshot"]
        self.assertEqual(state_snapshot["as_of_episode_no"], 2)
        self.assertEqual(state_snapshot["valid_episode_range"], {"from": 1, "to": 2})
        self.assertEqual(state_snapshot["current_identity"]["display_name"], "조렌 테이머")
        self.assertEqual(state_snapshot["current_identity"]["social_name"], "조렌 테이머")
        self.assertEqual(state_snapshot["current_identity"]["private_true_name"], "방호영")
        self.assertEqual(state_snapshot["current_identity"]["identity_variant"], "alternate_public_identity")
        self.assertEqual(state_snapshot["forbidden_identity_terms"], ["방호영"])
        affordance = main_rows[0]["interaction_affordance_v1"]
        self.assertEqual(affordance["preferred_user_role_key"], "scene_clue_holder")
        self.assertEqual(affordance["user_role_options"][0]["role_label_ko"], "장면에 단서를 들고 엮인 임시 조력자")
        self.assertEqual(affordance["user_role_options"][0]["suspicion_ceiling"], "light")
        self.assertIn("미래를 다 아는 존재", affordance["prohibited_user_roles"])
        event_seed = main_rows[0]["adjacent_event_seed_v1"]
        self.assertTrue(event_seed["new_incident_is_adjacent_not_canon"])
        self.assertEqual(event_seed["conflict_vector"], "hidden_clue")
        self.assertEqual(event_seed["allowed_intensity"], "investigation")
        self.assertIn("원작 결말 확정", event_seed["forbidden_canon_outcomes"])
        pov_centrality = main_rows[0]["pov_and_protagonist_centrality_v1"]
        self.assertEqual(pov_centrality["protagonist_presence"], "active_from_start")
        self.assertIsNone(pov_centrality["hold_before_episode_no"])
        self.assertEqual(pov_centrality["expose_policy"], "allow")
        voice_contract = main_rows[0]["voice_contract_v1"]
        self.assertEqual(voice_contract["stage"], "inventory_signal")
        self.assertEqual(voice_contract["speech_register"], "dialogue_evidence_present")
        self.assertEqual(voice_contract["address_terms"], ["조렌 테이머"])
        addressing_contract = voice_contract["addressing_contract_v1"]
        self.assertEqual(addressing_contract["schema_version"], "addressing_contract_v1")
        self.assertEqual(addressing_contract["user_to_character_allowed_calls"], ["조렌 테이머"])
        self.assertEqual(addressing_contract["user_to_character_forbidden_calls"], ["방호영"])
        self.assertEqual(addressing_contract["character_to_user_default_call"], "호칭 생략")
        self.assertEqual(addressing_contract["confidence"], "high")
        self.assertIn("무엇을 도와드릴까요", voice_contract["forbidden_speech_patterns"])
        self.assertEqual(hash_payload["read_range_state_snapshot"]["current_identity"]["private_true_name"], "방호영")
        self.assertEqual(hash_payload["interaction_affordance_v1"]["preferred_user_role_key"], "scene_clue_holder")
        self.assertEqual(hash_payload["adjacent_event_seed_v1"]["conflict_vector"], "hidden_clue")
        self.assertEqual(hash_payload["pov_and_protagonist_centrality_v1"]["protagonist_presence"], "active_from_start")
        self.assertEqual(hash_payload["voice_contract_v1"]["address_terms"], ["조렌 테이머"])
        self.assertEqual(
            hash_payload["voice_contract_v1"]["addressing_contract_v1"]["user_to_character_forbidden_calls"],
            ["방호영"],
        )
        readiness = main_rows[0]["chat_readiness_v1"]
        self.assertEqual(readiness["stage"], "inventory_signal")
        self.assertEqual(readiness["exposure_decision"], "eligible")
        self.assertTrue(readiness["character_chat_allowed"])
        self.assertFalse(readiness["public_slot_allowed"])
        self.assertEqual(readiness["block_reasons"], [])
        self.assertTrue(readiness["required_passes"]["has_identity_surface"])
        self.assertTrue(readiness["required_passes"]["has_reveal_boundary"])
        self.assertTrue(readiness["required_passes"]["has_read_range_state_snapshot"])
        self.assertTrue(readiness["required_passes"]["has_interaction_affordance"])
        self.assertTrue(readiness["required_passes"]["has_adjacent_event_seed"])
        self.assertTrue(readiness["required_passes"]["has_pov_centrality"])
        self.assertTrue(readiness["required_passes"]["has_voice_contract"])
        self.assertEqual(hash_payload["chat_readiness_v1"]["exposure_decision"], "eligible")

    def test_inventory_voice_contract_marks_honorific_surface(self):
        module = load_module()
        main = {
            "display_name": "이안",
            "identity_surface": {
                "chat_display_name": "이안",
                "addressable_names": ["이안"],
                "public_role_titles": ["전하", "소궁주"],
            },
            "voice_mode_counts": {"dialogue": 2},
        }

        voice_contract = module.build_inventory_voice_contract_v1(main)

        self.assertEqual(voice_contract["speech_register"], "honorific_surface_present")
        self.assertIn("전하", voice_contract["address_terms"])
        self.assertIn("소궁주", voice_contract["address_terms"])
        self.assertIn("전하", voice_contract["addressing_contract_v1"]["user_to_character_allowed_calls"])
        self.assertIn("소궁주", voice_contract["addressing_contract_v1"]["user_to_character_allowed_calls"])
        self.assertEqual(voice_contract["addressing_contract_v1"]["distance_axis"], "user_lower_or_formal_distance")
        self.assertEqual(voice_contract["addressing_contract_v1"]["confidence"], "high")

    def test_inventory_pov_contract_marks_late_protagonist_after_prologue(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:니드호그",
                        display_name="니드호그",
                        aliases=["니드호그"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:named:갤러해드",
                        display_name="갤러해드 지그문트",
                        aliases=["갤러해드 지그문트"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="protagonist:named:갤러해드",
                        display_name="갤러해드 지그문트",
                        aliases=["갤러해드 지그문트"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main = [row for row in inventory if row["work_role"] == "main_protagonist"][0]
        pov_centrality = main["pov_and_protagonist_centrality_v1"]

        self.assertEqual(main["display_name"], "갤러해드 지그문트")
        self.assertEqual(main["first_seen_episode_no"], 2)
        self.assertEqual(pov_centrality["protagonist_presence"], "late_entry_after_prologue")
        self.assertEqual(pov_centrality["hold_before_episode_no"], 2)
        self.assertEqual(pov_centrality["expose_policy"], "hold_until_presence_episode")
        self.assertEqual(pov_centrality["true_main_protagonist_character_key"], main["canonical_character_key"])
        self.assertTrue(main["chat_readiness_v1"]["required_passes"]["has_pov_centrality"])

    def test_inventory_runtime_contract_uses_action_tag_substrings(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:박형훈",
                        display_name="박형훈",
                        aliases=["박형훈"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        action_tags=["정체확인", "잠입", "추리"],
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main = [row for row in inventory if row["work_role"] == "main_protagonist"][0]

        self.assertEqual(main["interaction_affordance_v1"]["preferred_user_role_key"], "scene_clue_holder")
        self.assertEqual(main["adjacent_event_seed_v1"]["conflict_vector"], "hidden_clue")
        self.assertEqual(main["adjacent_event_seed_v1"]["allowed_intensity"], "investigation")

    def test_inventory_runtime_contract_prefers_dominant_action_family(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:전귀",
                        display_name="전귀",
                        aliases=["전귀"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        action_tags=["제압", "정보수집", "검기전개", "방어"],
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main = [row for row in inventory if row["work_role"] == "main_protagonist"][0]

        self.assertEqual(main["interaction_affordance_v1"]["preferred_user_role_key"], "field_support")
        self.assertEqual(main["adjacent_event_seed_v1"]["conflict_vector"], "minor_attack")

    def test_inventory_runtime_contract_does_not_treat_generic_confirm_as_clue(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:원유성",
                        display_name="원유성",
                        aliases=["원유성"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        action_tags=["오디션대기", "합격확인", "무대공연"],
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main = [row for row in inventory if row["work_role"] == "main_protagonist"][0]

        self.assertEqual(main["adjacent_event_seed_v1"]["conflict_vector"], "test_or_trial")

    def test_inventory_v3_recurring_aliases_do_not_override_opening_main_abstention(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:조렌테이머",
                        display_name="조렌 테이머",
                        aliases=["조렌 테이머", "조렌"],
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="medium",
                    ),
                    signal_character(
                        character_key="protagonist:named:방호영",
                        display_name="방호영",
                        aliases=["방호영", "호영"],
                        is_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="narration_only",
                        scene_weight="high",
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:named:호영",
                        display_name="호영",
                        aliases=["호영", "조렌 테이머", "수호자"],
                        is_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="protagonist:named:조렌테이머",
                        display_name="조렌 테이머",
                        aliases=["조렌 테이머", "변방백"],
                        is_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "named:호영",
                                "target_label": "호영",
                                "relation_tag": "동행",
                            }
                        ],
                    ),
                    signal_character(
                        character_key="named:호영",
                        display_name="호영",
                        aliases=["호영"],
                        role_in_episode="support",
                        voice_mode="dialogue",
                        scene_weight="medium",
                    ),
                ],
            ),
            signal_row(
                13,
                13,
                [
                    signal_character(
                        character_key="protagonist:named:호영",
                        display_name="호영",
                        aliases=["호영", "조렌 테이머"],
                        is_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertEqual(main_rows, [])
        self.assertTrue(
            any(
                {
                    "named:조렌테이머",
                    "named:호영",
                    "protagonist:named:방호영",
                    "protagonist:named:조렌테이머",
                    "protagonist:named:호영",
                } <= source_set
                for source_set in source_sets
            )
        )

    def test_inventory_v3_relation_edge_keeps_honorific_alias_split_without_persona_display(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 7):
            characters = []
            if episode_no <= 4:
                characters.append(
                    signal_character(
                        character_key="protagonist:named:남우진",
                        display_name="남우진",
                        aliases=["남우진", "우진"],
                        is_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                )
            characters.append(
                signal_character(
                    character_key="named:하늘",
                    display_name="하늘",
                    aliases=["하늘"],
                    role_in_episode="counterpart",
                    voice_mode="dialogue",
                    scene_weight="medium",
                    relation_edges=[
                        {
                            "target_key": "protagonist:first_person",
                            "target_label": "하늘 씨",
                            "relation_tag": "연인",
                        }
                    ]
                    if episode_no >= 5
                    else [],
                )
            )
            if episode_no >= 5:
                characters.append(
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="하늘 씨",
                        aliases=["하늘 씨", "하늘"],
                        is_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                )
            rows.append(signal_row(episode_no, episode_no, characters))

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]
        haneul_rows = [
            row
            for row in inventory
            if any(alias in {"하늘", "하늘 씨"} for alias in row["aliases"])
        ]

        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["display_name"], "남우진")
        self.assertGreaterEqual(len(haneul_rows), 2)

    def test_inventory_v3_display_name_prefers_frequent_full_name_over_single_typo_variant(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:하늘",
                        display_name="송하늘",
                        aliases=["송하늘", "하늘"],
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]
        rows.extend(
            [
                signal_row(
                    4,
                    4,
                    [
                        signal_character(
                            character_key="named:하늘",
                            display_name="하늘",
                            aliases=["하늘"],
                            role_in_episode="counterpart",
                            voice_mode="dialogue",
                            scene_weight="high",
                        )
                    ],
                ),
                signal_row(
                    5,
                    5,
                    [
                        signal_character(
                            character_key="named:하늘",
                            display_name="솔하늘",
                            aliases=["솔하늘", "하늘"],
                            role_in_episode="counterpart",
                            voice_mode="dialogue",
                            scene_weight="high",
                        )
                    ],
                ),
            ]
        )

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "송하늘")
        self.assertIn("솔하늘", inventory[0]["aliases"])

    def test_inventory_v3_display_name_keeps_single_full_name_without_competing_full_name(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:다이애나",
                        display_name="다이애나",
                        aliases=["다이애나"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 5)
        ]
        rows.append(
            signal_row(
                5,
                5,
                [
                    signal_character(
                        character_key="named:다이애나",
                        display_name="다이애나 체페슈",
                        aliases=["다이애나 체페슈", "다이애나"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
        )

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "다이애나 체페슈")
        self.assertIn("다이애나 체페슈", inventory[0]["aliases"])

    def test_inventory_v3_display_name_prefers_frequent_name_over_contextual_suffix_variant(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:파이크",
                        display_name="파이크",
                        aliases=["파이크"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 5)
        ]
        rows.append(
            signal_row(
                5,
                5,
                [
                    signal_character(
                        character_key="named:파이크",
                        display_name="파이크 단장",
                        aliases=["파이크 단장", "파이크"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
        )

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "파이크")
        self.assertIn("파이크 단장", inventory[0]["aliases"])

    def test_inventory_v3_display_name_prefers_frequent_name_over_single_syllable_typo_suffix(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:깁소필라",
                        display_name="깁소필라",
                        aliases=["깁소필라"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 5)
        ]
        rows.append(
            signal_row(
                5,
                5,
                [
                    signal_character(
                        character_key="named:깁소필라",
                        display_name="깁소 필라니",
                        aliases=["깁소 필라니", "깁소필라"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
        )

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "깁소필라")
        self.assertIn("깁소 필라니", inventory[0]["aliases"])

    def test_inventory_v3_display_name_prefers_full_name_over_contextual_call_variant(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:주연",
                        display_name="나주연",
                        aliases=["나주연", "주연"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
        ]
        rows.extend(
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:주연",
                        display_name="주연이",
                        aliases=["주연이", "주연"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(2, 6)
        )

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "나주연")
        self.assertIn("주연이", inventory[0]["aliases"])

    def test_inventory_v3_contextual_call_variant_does_not_force_cross_cluster_merge(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:남우진",
                        display_name="남우진",
                        aliases=["남우진", "우진"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:우진씨",
                        display_name="우진 씨",
                        aliases=["우진 씨", "우진"],
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 2)
        display_names = {row["display_name"] for row in inventory}
        self.assertIn("남우진", display_names)
        self.assertIn("우진", display_names)
        self.assertNotIn("우진 씨", display_names)

    def test_inventory_v3_contextual_call_suffix_without_base_evidence_is_kept(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:다온이",
                        display_name="다온이",
                        aliases=["다온이"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "다온이")

    def test_inventory_v3_parenthetical_generic_display_uses_inner_persona_name(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:나오레오",
                        display_name="나(오레오)",
                        aliases=["나(오레오)", "오레오", "나"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "오레오")
        self.assertIn("나(오레오)", inventory[0]["aliases"])

    def test_inventory_v3_rejects_generic_parenthetical_protagonist_display(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:서술자주인공",
                        display_name="서술자(주인공)",
                        aliases=["서술자(주인공)", "주인공"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="monologue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 5)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_safety"], {"status": "fail", "reason": "role_or_relation_label"})
        self.assertFalse(inventory[0]["public_chat_eligible"])
        self.assertFalse(inventory[0]["public_slot_eligible"])

    def test_inventory_v3_suppresses_duplicate_public_display_rows(self):
        module = load_module()
        rows = [
            {
                "canonical_character_key": "character:송하늘:dup:keep",
                "display_name": "송하늘",
                "work_role": "main_protagonist",
                "identity_status": "RESOLVED_NAMED",
                "identity_conflict_reasons": [],
                "distinct_episode_count": 8,
                "voice_mode_counts": {"dialogue": 5},
                "public_chat_eligible": True,
                "public_slot_eligible": True,
                "review_reasons": [],
            },
            {
                "canonical_character_key": "character:송하늘:dup:drop",
                "display_name": "송하늘",
                "work_role": "major_character",
                "identity_status": "CONFLICT",
                "identity_conflict_reasons": ["duplicate_canonical_key"],
                "distinct_episode_count": 4,
                "voice_mode_counts": {"dialogue": 3},
                "public_chat_eligible": True,
                "public_slot_eligible": True,
                "review_reasons": [],
            },
        ]

        module._suppress_duplicate_public_display_rows(rows)

        self.assertTrue(rows[0]["public_chat_eligible"])
        self.assertTrue(rows[0]["public_slot_eligible"])
        self.assertFalse(rows[1]["public_chat_eligible"])
        self.assertFalse(rows[1]["public_slot_eligible"])
        self.assertIn("DUPLICATE_PUBLIC_DISPLAY_NAME", rows[1]["review_reasons"])

    def test_inventory_v3_suppresses_main_alias_slot_without_hiding_chat(self):
        module = load_module()
        rows = [
            {
                "canonical_character_key": "character:남우진",
                "display_name": "남우진",
                "aliases": ["남우진", "우진"],
                "work_role": "main_protagonist",
                "public_chat_eligible": True,
                "public_slot_eligible": True,
                "review_reasons": [],
            },
            {
                "canonical_character_key": "character:우진",
                "display_name": "우진",
                "aliases": ["우진", "우진 씨"],
                "work_role": "major_character",
                "public_chat_eligible": True,
                "public_slot_eligible": True,
                "review_reasons": [],
            },
        ]

        module._suppress_main_alias_public_slot_rows(rows)

        self.assertTrue(rows[0]["public_slot_eligible"])
        self.assertTrue(rows[1]["public_chat_eligible"])
        self.assertFalse(rows[1]["public_slot_eligible"])
        self.assertIn("MAIN_ALIAS_PUBLIC_SLOT_DUPLICATE", rows[1]["review_reasons"])

    def test_inventory_v3_social_role_call_does_not_replace_resolved_real_name_display(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:백이현",
                        display_name="백이현",
                        aliases=["백이현"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        narration_names=["백이현", "이현"],
                        social_call_names=["영웅"],
                        persona_names=["백이현", "영웅"],
                        real_names=["백이현"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["canonical_character_key"], "character:백이현")
        self.assertEqual(main_rows[0]["display_name"], "백이현")
        self.assertNotEqual(main_rows[0]["display_name"], "영웅")
        self.assertEqual(main_rows[0]["display_safety"], {"status": "pass", "reason": "resolved_named_identity"})
        self.assertTrue(main_rows[0]["public_chat_eligible"])
        self.assertTrue(main_rows[0]["public_slot_eligible"])

    def test_inventory_v3_social_role_call_does_not_replace_identity_display_without_claim(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:산군",
                        display_name="산군",
                        aliases=["산군"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        narration_names=["산군", "대전사"],
                        social_call_names=["대전사"],
                        persona_names=["산군", "대전사"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["canonical_character_key"], "character:산군")
        self.assertEqual(main_rows[0]["display_name"], "산군")
        self.assertNotEqual(main_rows[0]["display_name"], "대전사")
        self.assertTrue(main_rows[0]["public_chat_eligible"])

    def test_inventory_v3_contextual_social_call_does_not_replace_identity_display_name(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="protagonist:named:전귀",
                        display_name="전귀",
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        narration_names=["전귀"],
                        social_call_names=["재미있는 놈"],
                        persona_names=["전귀"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["display_name"], "전귀")
        self.assertEqual(main_rows[0]["display_name_source"], "persona_names")
        self.assertIn("재미있는 놈", main_rows[0]["social_call_names"])

    def test_inventory_v3_identity_counts_do_not_auto_promote_main(self):
        module = load_module()
        rows = [
            {
                "display_name": "이시혁",
                "identity_status": "CONFLICT",
                "identity_conflict_reasons": ["unresolved_generic_first_person", "duplicate_canonical_key"],
                "is_generic_display_name": False,
                "distinct_episode_count": 8,
                "work_protagonist_evidence": {"episode_count": 8},
                "episode_focal_evidence": {"episode_count": 8},
                "first_person_evidence": {"episode_count": 2},
                "episode_role_counts": {"lead": 8},
                "scene_weight_counts": {"high": 8},
                "voice_mode_counts": {"dialogue": 8},
            },
            {
                "display_name": "조연",
                "identity_status": "RESOLVED_NAMED",
                "identity_conflict_reasons": [],
                "is_generic_display_name": False,
                "distinct_episode_count": 3,
                "work_protagonist_evidence": {"episode_count": 1},
                "episode_focal_evidence": {"episode_count": 1},
                "first_person_evidence": {"episode_count": 0},
                "episode_role_counts": {"lead": 1},
                "scene_weight_counts": {"high": 1},
                "voice_mode_counts": {"dialogue": 1},
            },
        ]

        module._classify_character_inventory_v3_rows(rows, total_signal_episodes=8)

        self.assertEqual(rows[0]["work_role"], "major_character")
        self.assertEqual(rows[0]["classification_status"], "NEEDS_REVIEW")
        self.assertEqual(rows[0]["rp_signal_quality"]["status"], "summary_ready")
        self.assertEqual(rows[0]["display_safety"], {"status": "pass", "reason": "resolved_named_identity"})
        self.assertTrue(rows[0]["public_chat_eligible"])

    def test_inventory_v3_episode_focal_non_protagonist_does_not_beat_work_protagonist(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:회차주역",
                        display_name="회차주역",
                        is_protagonist=False,
                        is_work_protagonist=False,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="protagonist:named:주인공명",
                        display_name="주인공명",
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=False,
                        is_first_person=True,
                        role_in_episode="support",
                        voice_mode="monologue",
                        scene_weight="medium",
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:회차주역",
                        display_name="회차주역",
                        is_protagonist=False,
                        is_work_protagonist=False,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="protagonist:named:주인공명",
                        display_name="주인공명",
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=False,
                        is_first_person=True,
                        role_in_episode="support",
                        voice_mode="monologue",
                        scene_weight="medium",
                    ),
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="named:회차주역",
                        display_name="회차주역",
                        is_protagonist=False,
                        is_work_protagonist=False,
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["display_name"], "주인공명")
        self.assertEqual(main_rows[0]["work_protagonist_evidence"]["episode_count"], 2)
        self.assertNotEqual(main_rows[0]["display_name"], "회차주역")

    def test_inventory_v3_does_not_merge_avatar_alias_without_identity_claim(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:호영",
                        display_name="호영",
                        aliases=["호영", "조렌 테이머"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="named:조렌테이머",
                        display_name="조렌 테이머",
                        aliases=["조렌 테이머"],
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="medium",
                    ),
                ],
            )
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"protagonist:named:호영"}, source_sets)
        self.assertIn({"named:조렌테이머"}, source_sets)
        self.assertNotIn({"protagonist:named:호영", "named:조렌테이머"}, source_sets)

    def test_inventory_v3_does_not_merge_substring_role_like_label_without_identity_claim(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:우미",
                        display_name="우미",
                        aliases=["우미", "도우미"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="named:도우미",
                        display_name="도우미",
                        aliases=["도우미"],
                        role_in_episode="support",
                        voice_mode="dialogue",
                        scene_weight="medium",
                    ),
                ],
            )
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"protagonist:named:우미"}, source_sets)
        self.assertIn({"named:도우미"}, source_sets)
        self.assertNotIn({"protagonist:named:우미", "named:도우미"}, source_sets)

    def test_inventory_v3_title_claim_never_creates_identity_bridge(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:펜데",
                        display_name="펜데",
                        aliases=["펜데"],
                        identity_claims=[
                            {
                                "target_label": "영주권 소지자",
                                "claim_type": "title_of",
                                "evidence": "펜데가 자신은 영주권 소지자라고 말했다",
                            }
                        ],
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:영주권소지자",
                        display_name="영주권 소지자",
                        aliases=["영주권 소지자"],
                    ),
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"named:펜데"}, source_sets)
        self.assertIn({"named:영주권소지자"}, source_sets)
        self.assertNotIn({"named:펜데", "named:영주권소지자"}, source_sets)

    def test_inventory_v3_relation_phrase_claim_never_creates_identity_bridge(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:아셔",
                        display_name="아셔",
                        aliases=["아셔"],
                        identity_claims=[
                            {
                                "target_label": "이안의 아이",
                                "claim_type": "same_person_as",
                                "evidence": "황제가 이 아이는 이안의 아이이다라고 말했다",
                            }
                        ],
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:이안의아이",
                        display_name="이안의 아이",
                        aliases=["이안의 아이"],
                    ),
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"named:아셔"}, source_sets)
        self.assertIn({"named:이안의아이"}, source_sets)
        self.assertNotIn({"named:아셔", "named:이안의아이"}, source_sets)

    def test_inventory_v3_real_name_variant_claim_merges_when_unconflicted(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:현태",
                        display_name="현태",
                        aliases=["현태"],
                        identity_claims=[
                            {
                                "target_label": "서현태",
                                "claim_type": "real_name_of",
                                "evidence": "현태의 풀네임이 서현태로 언급됨",
                            }
                        ],
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:서현태",
                        display_name="서현태",
                        aliases=["서현태"],
                    ),
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"named:현태", "named:서현태"}, source_sets)

    def test_inventory_v3_non_variant_real_name_claim_does_not_merge(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:발리우스",
                        display_name="발리우스",
                        aliases=["발리우스"],
                        identity_claims=[
                            {
                                "target_label": "노이티에",
                                "claim_type": "real_name_of",
                                "evidence": "수신인 노이티에가 자신의 친아버지임을 알았다",
                            }
                        ],
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:노이티에",
                        display_name="노이티에",
                        aliases=["노이티에"],
                    ),
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"named:발리우스"}, source_sets)
        self.assertIn({"named:노이티에"}, source_sets)
        self.assertNotIn({"named:발리우스", "named:노이티에"}, source_sets)

    def test_inventory_v3_name_with_ui_syllable_is_not_treated_as_possessive_phrase(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:백의",
                        display_name="백의",
                        aliases=["백의"],
                        identity_claims=[
                            {
                                "target_label": "백의검",
                                "claim_type": "codename_of",
                                "evidence": "백의가 백의검이라는 별호로도 불린다",
                            }
                        ],
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:백의검",
                        display_name="백의검",
                        aliases=["백의검"],
                    ),
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertIn({"named:백의", "named:백의검"}, source_sets)

    def test_inventory_v3_display_name_prefers_non_generic_alias_identity(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="나",
                        aliases=["유아"],
                        is_protagonist=True,
                        is_first_person=True,
                        role_in_episode="lead",
                        voice_mode="monologue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:유아",
                        display_name="유아",
                        aliases=["유아"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(inventory[0]["display_name"], "유아")
        self.assertEqual(inventory[0]["canonical_character_key"], "character:유아")

    def test_inventory_v3_duplicate_canonical_keys_are_conflicted_and_suffixed(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:설총:a",
                        display_name="설총",
                        aliases=["설총"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                        relation_edges=[
                            {
                                "target_key": "named:설총:b",
                                "target_label": "설총",
                                "relation_tag": "대립",
                                "direction": "to_target",
                            }
                        ],
                    ),
                    signal_character(
                        character_key="named:설총:b",
                        display_name="설총",
                        aliases=["설총"],
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                ],
            )
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        keys = [row["canonical_character_key"] for row in inventory]

        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(key.startswith("character:설총:dup:") for key in keys))
        self.assertTrue(all(row["identity_status"] == "CONFLICT" for row in inventory))
        self.assertTrue(all("duplicate_canonical_key" in row["identity_conflict_reasons"] for row in inventory))

    def test_inventory_v3_reuses_durable_key_when_observation_hash_changes(self):
        module = load_module()
        old_scope_key = "character:레이븐:dup:be810f0c"
        new_scope_key = "character:레이븐:dup:faa369a2"
        rows = [
            {
                "canonical_character_key": new_scope_key,
                "display_name": "레이븐",
                "source_character_keys": ["protagonist:named:레이븐"],
                "public_chat_eligible": True,
                "public_slot_eligible": True,
                "identity_conflict_reasons": ["duplicate_canonical_key"],
                "review_reasons": ["duplicate_canonical_key"],
            }
        ]
        old_inventory_map = {
            old_scope_key: {
                "canonical_character_key": old_scope_key,
                "display_name": "레이븐",
                "source_character_keys": ["protagonist:named:레이븐"],
                "public_chat_eligible": True,
                "public_slot_eligible": True,
            }
        }

        reconciled = module.reconcile_character_inventory_v3_scope_keys(
            rows,
            old_inventory_map=old_inventory_map,
        )

        self.assertEqual(reconciled[0]["canonical_character_key"], old_scope_key)
        self.assertEqual(reconciled[0]["legacy_scope_keys"], [new_scope_key])
        self.assertEqual(reconciled[0]["continuity_status"], "reused")

    def test_inventory_v3_prefers_unique_locked_main_when_reaggregation_absorbs_duplicate(self):
        module = load_module()
        main_scope_key = "character:레이븐:dup:faa369a2"
        duplicate_scope_key = "character:레이븐:dup:d15d08d0"
        generated_scope_key = "character:레이븐"
        rows = [
            {
                "canonical_character_key": generated_scope_key,
                "display_name": "레이븐",
                "work_role": "main_protagonist",
                "source_character_keys": [
                    "named:레이븐",
                    "protagonist:named:레이븐",
                ],
                "public_chat_eligible": True,
                "public_slot_eligible": True,
                "identity_conflict_reasons": [],
                "review_reasons": [],
            }
        ]
        old_inventory_map = {
            main_scope_key: {
                "canonical_character_key": main_scope_key,
                "display_name": "레이븐",
                "work_role": "main_protagonist",
                "source_character_keys": ["protagonist:named:레이븐"],
            },
            duplicate_scope_key: {
                "canonical_character_key": duplicate_scope_key,
                "display_name": "레이븐",
                "work_role": "major_character",
                "source_character_keys": ["named:레이븐"],
            },
        }

        reconciled = module.reconcile_character_inventory_v3_scope_keys(
            rows,
            old_inventory_map=old_inventory_map,
        )

        self.assertEqual(reconciled[0]["canonical_character_key"], main_scope_key)
        self.assertEqual(reconciled[0]["continuity_status"], "reused")
        self.assertNotIn(
            "identity_continuity_ambiguous",
            reconciled[0]["identity_conflict_reasons"],
        )

    def test_inventory_v3_keeps_ambiguity_when_multiple_locked_mains_match(self):
        module = load_module()
        generated_scope_key = "character:레이븐"
        rows = [
            {
                "canonical_character_key": generated_scope_key,
                "display_name": "레이븐",
                "work_role": "main_protagonist",
                "source_character_keys": [
                    "protagonist:named:레이븐:a",
                    "protagonist:named:레이븐:b",
                ],
                "public_chat_eligible": True,
                "public_slot_eligible": True,
                "identity_conflict_reasons": [],
                "review_reasons": [],
            }
        ]
        old_inventory_map = {
            "character:레이븐:dup:a": {
                "display_name": "레이븐",
                "work_role": "main_protagonist",
                "source_character_keys": ["protagonist:named:레이븐:a"],
            },
            "character:레이븐:dup:b": {
                "display_name": "레이븐",
                "work_role": "main_protagonist",
                "source_character_keys": ["protagonist:named:레이븐:b"],
            },
        }

        reconciled = module.reconcile_character_inventory_v3_scope_keys(
            rows,
            old_inventory_map=old_inventory_map,
        )

        self.assertEqual(reconciled[0]["canonical_character_key"], generated_scope_key)
        self.assertEqual(reconciled[0]["continuity_status"], "ambiguous")
        self.assertFalse(reconciled[0]["public_chat_eligible"])

    def test_inventory_v3_name_only_continuity_is_fail_closed(self):
        module = load_module()
        new_scope_key = "character:레이븐:dup:new"
        rows = [
            {
                "canonical_character_key": new_scope_key,
                "display_name": "레이븐",
                "source_character_keys": ["named:레이븐:new"],
                "public_chat_eligible": True,
                "public_slot_eligible": True,
                "identity_conflict_reasons": [],
                "review_reasons": [],
            }
        ]
        old_inventory_map = {
            "character:레이븐:dup:old": {
                "canonical_character_key": "character:레이븐:dup:old",
                "display_name": "레이븐",
                "source_character_keys": ["named:레이븐:old"],
                "public_chat_eligible": True,
                "public_slot_eligible": True,
            }
        }

        reconciled = module.reconcile_character_inventory_v3_scope_keys(
            rows,
            old_inventory_map=old_inventory_map,
        )

        self.assertEqual(reconciled[0]["canonical_character_key"], new_scope_key)
        self.assertEqual(reconciled[0]["continuity_status"], "ambiguous")
        self.assertFalse(reconciled[0]["public_chat_eligible"])
        self.assertFalse(reconciled[0]["public_slot_eligible"])
        self.assertFalse(reconciled[0]["chat_readiness_v1"]["character_chat_allowed"])
        self.assertFalse(reconciled[0]["chat_readiness_v1"]["public_slot_allowed"])
        self.assertEqual(reconciled[0]["chat_readiness_v1"]["exposure_decision"], "hold")
        self.assertIn(
            "identity_continuity_ambiguous",
            reconciled[0]["identity_conflict_reasons"],
        )

    def test_inventory_v3_does_not_bridge_cannot_linked_characters_through_aliases(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:설총",
                        display_name="설총",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="named:득구",
                        display_name="득구",
                        role_in_episode="counterpart",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="named:별칭혼합",
                        display_name="별칭혼합",
                        aliases=["설총", "득구"],
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="protagonist:named:설총",
                        display_name="설총",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        source_sets = [set(row["source_character_keys"]) for row in inventory]

        self.assertNotIn({"protagonist:named:설총", "named:득구", "named:별칭혼합"}, source_sets)
        self.assertTrue(all(not ({"protagonist:named:설총", "named:득구"} <= set(row["source_character_keys"])) for row in inventory))
        self.assertTrue(all("AMBIGUOUS_ALIAS_BRIDGE" not in row["identity_conflict_reasons"] for row in inventory))

    def test_inventory_v3_marks_ambiguous_top_candidates_for_review(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:설총",
                        display_name="설총",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:named:설총",
                        display_name="설총",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="protagonist:named:득구",
                        display_name="득구",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
            signal_row(
                4,
                4,
                [
                    signal_character(
                        character_key="protagonist:named:득구",
                        display_name="득구",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual([row for row in inventory if row["work_role"] == "main_protagonist"], [])
        top_rows = [row for row in inventory if row["protagonist_evidence"]["rank"] <= 2]
        self.assertEqual(len(top_rows), 2)
        self.assertTrue(all(row["protagonist_evidence"]["score"] == 0.0 for row in top_rows))
        self.assertTrue(all(not row["is_protagonist"] for row in top_rows))
        self.assertTrue(all(row["protagonist_confidence"] == "low" for row in top_rows))
        self.assertTrue(all(row["rp_signal_quality"]["needs_review"] for row in top_rows))

    def test_inventory_v3_public_chat_gate_keeps_stable_role_internal_only(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:대전사",
                        display_name="대전사",
                        aliases=["대전사"],
                        entity_kind="stable_role",
                        is_episode_focal=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["identity_status"], "RESOLVED_STABLE_ROLE")
        self.assertEqual(inventory[0]["display_safety"], {"status": "review", "reason": "stable_role_identity"})
        self.assertFalse(inventory[0]["public_chat_eligible"])
        self.assertEqual(
            module.build_inventory_rp_targets({inventory[0]["canonical_character_key"]: inventory[0]}),
            [],
        )

    def test_inventory_v3_public_chat_gate_keeps_unnamed_role_internal(self):
        module = load_module()
        rows = []
        for episode_no in range(1, 7):
            payload = module.normalize_episode_character_signals_payload(
                {
                    "mentioned_characters": [
                    signal_character(
                        character_key="protagonist:named:관리자" if episode_no <= 4 else "named:관리자",
                        display_name="관리자",
                        aliases=["관리자"],
                        entity_kind="stable_role",
                        is_protagonist=episode_no <= 4,
                        is_episode_focal=episode_no <= 6,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                    ]
                },
                episode_no=episode_no,
            )
            rows.append(signal_row(episode_no, episode_no, payload["mentioned_characters"]))

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        main = next(row for row in inventory if row["work_role"] == "main_protagonist")
        self.assertEqual(main["display_name"], "나(주인공)")
        self.assertFalse(main["public_chat_eligible"])
        self.assertFalse(main["public_slot_eligible"])
        self.assertEqual(
            module.build_inventory_rp_targets(
                {main["canonical_character_key"]: main}
            ),
            [],
        )

    def test_inventory_v3_public_chat_gate_rejects_weak_role_like_persona(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:관리자",
                        display_name="관리자",
                        aliases=["관리자"],
                        entity_kind="stable_role",
                        role_in_episode="support",
                        voice_mode="dialogue" if episode_no == 1 else "narration_only",
                        scene_weight="medium",
                    )
                ],
            )
            for episode_no in range(1, 3)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_safety"], {"status": "fail", "reason": "generic_display_name"})
        self.assertFalse(inventory[0]["public_chat_eligible"])
        self.assertFalse(inventory[0]["public_slot_eligible"])
        readiness = inventory[0]["chat_readiness_v1"]
        self.assertEqual(readiness["exposure_decision"], "reject")
        self.assertFalse(readiness["character_chat_allowed"])
        self.assertFalse(readiness["public_slot_allowed"])
        self.assertIn("display_safety_not_pass", readiness["block_reasons"])
        self.assertIn("not_major_character", readiness["block_reasons"])
        self.assertFalse(readiness["required_passes"]["has_public_display_safety"])

    def test_inventory_v3_source_hash_changes_when_public_gate_changes(self):
        module = load_module()
        base_item = {
            "canonical_character_key": "character:산군",
            "display_name": "산군",
            "display_name_source": "persona_names",
            "aliases": ["산군"],
            "source_character_keys": ["protagonist:named:산군"],
            "identity_status": "RESOLVED_NAMED",
            "entity_kind": "person",
            "work_role": "main_protagonist",
            "role_confidence": "high",
            "is_protagonist": True,
            "protagonist_confidence": "high",
            "rp_signal_quality": {"status": "summary_ready"},
            "evidence_episode_nos": [1, 2, 3],
        }
        pass_item = {
            **base_item,
            "display_safety": {"status": "pass", "reason": "resolved_named_identity"},
            "public_chat_eligible": True,
            "public_slot_eligible": True,
        }
        blocked_item = {
            **base_item,
            "display_safety": {"status": "review", "reason": "stable_role_identity"},
            "public_chat_eligible": False,
            "public_slot_eligible": False,
        }

        self.assertNotEqual(
            module.build_character_inventory_v3_source_hash(pass_item),
            module.build_character_inventory_v3_source_hash(blocked_item),
        )

    def test_inventory_v3_public_chat_gate_rejects_ordinal_title_display_name(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:제일황자",
                        display_name="제 일 황자",
                        aliases=["제 일 황자"],
                        persona_names=["제 일 황자"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "제 일 황자")
        self.assertEqual(inventory[0]["display_safety"], {"status": "fail", "reason": "role_or_relation_label"})
        self.assertFalse(inventory[0]["public_chat_eligible"])
        self.assertFalse(inventory[0]["public_slot_eligible"])

    def test_inventory_v3_public_chat_gate_rejects_collective_role_display_name(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:공작부부",
                        display_name="공작부부",
                        aliases=["공작부부"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "공작부부")
        self.assertEqual(inventory[0]["display_safety"], {"status": "fail", "reason": "role_or_relation_label"})
        self.assertFalse(inventory[0]["public_chat_eligible"])
        self.assertFalse(inventory[0]["public_slot_eligible"])

    def test_inventory_v3_public_chat_gate_rejects_possessive_relation_display_name(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:아셔의어머니",
                        display_name="아셔의어머니",
                        aliases=["아셔의 어머니"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_safety"], {"status": "fail", "reason": "role_or_relation_label"})
        self.assertFalse(inventory[0]["public_chat_eligible"])
        self.assertFalse(inventory[0]["public_slot_eligible"])

    def test_inventory_v3_public_chat_gate_rejects_descriptor_display_name(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:키큰남자",
                        display_name="키큰남자",
                        aliases=["키 큰 남자"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_safety"], {"status": "fail", "reason": "role_or_relation_label"})
        self.assertFalse(inventory[0]["public_chat_eligible"])
        self.assertFalse(inventory[0]["public_slot_eligible"])

    def test_inventory_v3_public_chat_gate_rejects_particle_prefixed_honorific_display_name(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:은노야",
                        display_name="은 노야",
                        aliases=["은 노야"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "은 노야")
        self.assertEqual(inventory[0]["display_safety"], {"status": "fail", "reason": "role_or_relation_label"})
        self.assertFalse(inventory[0]["public_chat_eligible"])
        self.assertFalse(inventory[0]["public_slot_eligible"])

    def test_inventory_v3_public_chat_gate_keeps_named_title_display_name(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        character_key="named:아서교수",
                        display_name="아서 교수",
                        aliases=["아서 교수", "아서"],
                        social_call_names=["아서 교수"],
                        persona_names=["아서 교수"],
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["display_name"], "아서 교수")
        self.assertEqual(inventory[0]["display_safety"], {"status": "pass", "reason": "resolved_named_identity"})
        self.assertTrue(inventory[0]["public_chat_eligible"])
        self.assertFalse(inventory[0]["public_slot_eligible"])

    def test_inventory_v3_abstains_from_two_to_one_opening_votes(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:하남재",
                        display_name="하남재",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="named:퍼틴",
                        display_name="퍼틴",
                        role_in_episode="support",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        character_key="protagonist:named:퍼틴",
                        display_name="퍼틴",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="named:하남재",
                        display_name="하남재",
                        role_in_episode="support",
                        voice_mode="dialogue",
                        scene_weight="medium",
                    ),
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        character_key="protagonist:named:하남재",
                        display_name="하남재",
                        is_protagonist=True,
                        role_in_episode="lead",
                        voice_mode="dialogue",
                        scene_weight="high",
                    ),
                    signal_character(
                        character_key="named:퍼틴",
                        display_name="퍼틴",
                        role_in_episode="support",
                        voice_mode="dialogue",
                        scene_weight="medium",
                    ),
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual(main_rows, [])
        self.assertTrue(all(not row["is_protagonist"] for row in inventory))

    def test_inventory_v3_uses_stable_observation_ids_without_summary_id(self):
        module = load_module()
        rows = [
            {
                "episode_id": 101,
                "episode_from": 1,
                "source_hash": "episode-101",
                "summary_text": json.dumps(
                    {
                        "episode_no": 1,
                        "mentioned_characters": [
                            signal_character(character_key="named:클레어", display_name="클레어"),
                            signal_character(
                                character_key="protagonist:named:렌",
                                display_name="렌",
                                is_protagonist=True,
                                role_in_episode="lead",
                                voice_mode="dialogue",
                                scene_weight="high",
                            ),
                        ],
                        "cliffhanger_hooks": [],
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "episode_id": 102,
                "episode_from": 2,
                "source_hash": "episode-102",
                "summary_text": json.dumps(
                    {
                        "episode_no": 2,
                        "mentioned_characters": [
                            signal_character(
                                character_key="protagonist:named:렌",
                                display_name="렌",
                                is_protagonist=True,
                                role_in_episode="lead",
                                voice_mode="dialogue",
                                scene_weight="high",
                            ),
                            signal_character(character_key="named:의사", display_name="의사"),
                        ],
                        "cliffhanger_hooks": [],
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "episode_id": 103,
                "episode_from": 3,
                "source_hash": "episode-103",
                "summary_text": json.dumps(
                    {
                        "episode_no": 3,
                        "mentioned_characters": [
                            signal_character(
                                character_key="protagonist:named:렌",
                                display_name="렌",
                                is_protagonist=True,
                                role_in_episode="lead",
                                voice_mode="dialogue",
                                scene_weight="high",
                            ),
                            signal_character(character_key="named:의사", display_name="의사"),
                        ],
                        "cliffhanger_hooks": [],
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        main_rows = [row for row in inventory if row["work_role"] == "main_protagonist"]

        self.assertEqual(len(main_rows), 1)
        self.assertEqual(main_rows[0]["display_name"], "렌")
        self.assertEqual(main_rows[0]["identity_status"], "RESOLVED_NAMED")
        self.assertNotIn("cannot_link_name_conflict", main_rows[0]["review_reasons"])

    def test_delta_candidate_filter_limits_rows_per_product_by_episode_no(self):
        module = load_module()
        rows = [
            {"product_id": 687, "episode_id": 103, "episode_no": 3, "character_asset_collection_eligible": 1},
            {"product_id": 687, "episode_id": 101, "episode_no": 1, "character_asset_collection_eligible": 1},
            {"product_id": 687, "episode_id": 102, "episode_no": 2, "character_asset_collection_eligible": 1},
            {"product_id": 687, "episode_id": 104, "episode_no": 4, "character_asset_collection_eligible": 1},
        ]

        with patch.object(module, "build_open_add_episode_id_set", return_value={101, 102, 103, 104}), \
             patch.object(module, "build_sync_repair_episode_id_set", return_value=set()), \
             patch.object(module, "build_signal_repair_episode_id_set", return_value=set()), \
             patch.object(module, "build_scene_repair_episode_id_set", return_value=set()):
            filtered = module.filter_delta_candidate_rows(object(), rows, max_delta_episodes=2)

        self.assertEqual([row["episode_no"] for row in filtered], [1, 2])
        self.assertEqual([row["_delta_reason"] for row in filtered], ["open_add", "open_add"])

    def test_delta_candidate_filter_includes_missing_episode_character_signals(self):
        module = load_module()
        rows = [
            {"product_id": 687, "episode_id": 101, "episode_no": 1, "character_asset_collection_eligible": 1},
            {"product_id": 687, "episode_id": 102, "episode_no": 2, "character_asset_collection_eligible": 1},
        ]

        with patch.object(module, "build_open_add_episode_id_set", return_value=set()), \
             patch.object(module, "build_sync_repair_episode_id_set", return_value=set()), \
             patch.object(module, "build_signal_repair_episode_id_set", return_value={102}), \
             patch.object(module, "build_scene_repair_episode_id_set", return_value=set()):
            filtered = module.filter_delta_candidate_rows(object(), rows, max_delta_episodes=0)

        self.assertEqual([row["episode_no"] for row in filtered], [2])
        self.assertEqual([row["_delta_reason"] for row in filtered], ["signal_repair"])

    def test_signal_repair_episode_id_set_uses_episode_character_signal_scope_keys(self):
        module = load_module()
        cur = object()
        rows = [
            {"product_id": 687, "episode_id": 101, "episode_no": 1},
            {"product_id": 687, "episode_id": 102, "episode_no": 2},
        ]

        with patch.object(
            module,
            "fetch_active_summary_rows",
            return_value=[{"scope_key": "episode:101"}],
        ) as fetch_rows:
            repair_ids = module.build_signal_repair_episode_id_set(
                cur,
                product_id=687,
                product_rows=rows,
            )

        fetch_rows.assert_called_once_with(
            cur=cur,
            product_id=687,
            summary_type="episode_character_signals",
        )
        self.assertEqual(repair_ids, {102})

    def test_signal_and_scene_repairs_skip_episode_outside_character_collection_cap(self):
        module = load_module()
        cur = object()
        rows = [
            {
                "product_id": 687,
                "episode_id": 130,
                "episode_no": 30,
                "character_asset_episode_eligible": 1,
            },
            {
                "product_id": 687,
                "episode_id": 131,
                "episode_no": 31,
                "character_asset_episode_eligible": 0,
            },
        ]

        with patch.object(module, "fetch_active_summary_rows", return_value=[]):
            signal_repairs = module.build_signal_repair_episode_id_set(
                cur,
                product_id=687,
                product_rows=rows,
            )
        with patch.object(module, "fetch_active_summary_rows", side_effect=[[], []]):
            scene_repairs = module.build_scene_repair_episode_id_set(
                cur,
                product_id=687,
                product_rows=rows,
            )

        self.assertEqual(signal_repairs, {130})
        self.assertEqual(scene_repairs, {130})

    def test_character_asset_rows_cap_first_public_rank_but_preserve_cleanup_scope(self):
        module = load_module()
        product_rows = [
            {"episode_id": 130, "episode_no": 45, "character_asset_episode_eligible": 1},
            {"episode_id": 131, "episode_no": 46, "character_asset_episode_eligible": 0},
        ]
        summary_rows = [
            {"scope_key": "episode:130", "episode_from": 45},
            {"scope_key": "episode:131", "episode_from": 46},
        ]

        selected, cleanup_missing_scopes = module.select_character_asset_episode_rows(
            product_rows=product_rows,
            episode_summary_rows=summary_rows,
        )

        self.assertEqual(selected, [summary_rows[0]])
        self.assertFalse(cleanup_missing_scopes)

    def test_target_query_marks_character_asset_eligibility_by_first_public_rank(self):
        module = load_module()
        query, _ = module.build_target_query(
            SimpleNamespace(product_ids=[687], episode_ids=[], episode_nos=[], limit=0),
            use_epub_fallback=False,
        )

        self.assertIn("ROW_NUMBER() OVER (", query)
        self.assertIn("AS public_episode_rank", query)
        self.assertIn(
            f"asset_rank.public_episode_rank <= {module.CHARACTER_CHAT_MAX_COLLECTED_PUBLIC_EPISODES}",
            query,
        )
        self.assertIn("asset_rank.public_episode_rank", query)
        self.assertIn("AS character_asset_episode_eligible", query)

    def test_scene_repair_episode_id_set_requires_usable_active_scene(self):
        module = load_module()
        cur = object()
        rows = [
            {"product_id": 687, "episode_id": 101, "episode_no": 1},
            {"product_id": 687, "episode_id": 102, "episode_no": 2},
            {"product_id": 687, "episode_id": 103, "episode_no": 3},
            {"product_id": 687, "episode_id": 104, "episode_no": 4},
            {"product_id": 687, "episode_id": 105, "episode_no": 5},
        ]
        active_scene_rows = [
            {
                "summary_id": 20,
                "scope_key": "episode:101",
                "summary_text": json.dumps(
                    {
                        "status": "ok",
                        "scene_count": 1,
                        "scenes": [{"scene_index": 1, "scene_gist": "렌이 문을 연다."}],
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "summary_id": 20,
                "scope_key": "episode:102",
                "summary_text": json.dumps(
                    {"status": "failed", "scene_count": 1, "scenes": [{"scene_index": 1}]},
                    ensure_ascii=False,
                ),
            },
            {
                "summary_id": 20,
                "scope_key": "episode:104",
                "summary_text": json.dumps(
                    {"status": "ok", "scene_count": "not-a-number", "scenes": [{"scene_index": 1}]},
                    ensure_ascii=False,
                ),
            },
            {
                "summary_id": 20,
                "scope_key": "episode:105",
                "summary_text": json.dumps(
                    {"status": "ok", "scene_count": 1, "scenes": {"scene_index": 1}},
                    ensure_ascii=False,
                ),
            },
        ]

        with patch.object(
            module,
            "fetch_active_summary_rows",
            side_effect=[
                active_scene_rows,
                [
                    {"summary_id": 10, "scope_key": f"episode:{episode_id}"}
                    for episode_id in range(101, 106)
                ],
            ],
        ) as fetch_rows:
            repair_ids = module.build_scene_repair_episode_id_set(
                cur,
                product_id=687,
                product_rows=rows,
            )

        fetch_rows.assert_any_call(
            cur=cur,
            product_id=687,
            summary_type="episode_scene_extraction",
        )
        self.assertEqual(repair_ids, {102, 103, 104, 105})

    def test_scene_repair_marks_scene_stale_when_episode_summary_is_newer(self):
        module = load_module()
        cur = object()
        rows = [{"product_id": 687, "episode_id": 101, "episode_no": 1}]
        active_scene_rows = [
            {
                "summary_id": 10,
                "scope_key": "episode:101",
                "summary_text": json.dumps(
                    {
                        "status": "ok",
                        "scene_count": 1,
                        "scenes": [{"scene_index": 1, "scene_gist": "렌이 문을 연다."}],
                    },
                    ensure_ascii=False,
                ),
            }
        ]
        active_episode_summary_rows = [
            {"summary_id": 20, "scope_key": "episode:101", "summary_text": "새 요약"}
        ]

        with patch.object(
            module,
            "fetch_active_summary_rows",
            side_effect=[active_scene_rows, active_episode_summary_rows],
        ):
            repair_ids = module.build_scene_repair_episode_id_set(
                cur,
                product_id=687,
                product_rows=rows,
            )

        self.assertEqual(repair_ids, {101})

    def test_scene_repair_keeps_scene_when_it_is_newer_than_episode_summary(self):
        module = load_module()
        cur = object()
        rows = [{"product_id": 687, "episode_id": 101, "episode_no": 1}]
        active_scene_rows = [
            {
                "summary_id": 30,
                "scope_key": "episode:101",
                "summary_text": json.dumps(
                    {
                        "status": "partial",
                        "scene_count": 1,
                        "scenes": [{"scene_index": 1, "scene_gist": "렌이 문을 연다."}],
                    },
                    ensure_ascii=False,
                ),
            }
        ]
        active_episode_summary_rows = [
            {"summary_id": 20, "scope_key": "episode:101", "summary_text": "현재 요약"}
        ]

        with patch.object(
            module,
            "fetch_active_summary_rows",
            side_effect=[active_scene_rows, active_episode_summary_rows],
        ):
            repair_ids = module.build_scene_repair_episode_id_set(
                cur,
                product_id=687,
                product_rows=rows,
            )

        self.assertEqual(repair_ids, set())

    def test_delta_keeps_character_bundle_uncommitted_until_readiness(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        delta_start = source.index("async def build_context_rows_delta(")
        delta_inventory_anchor = source.index(
            "new_inventory_v3_map = fetch_active_character_inventory_map(",
            delta_start,
        )
        scene_call = source.index(
            "scene_counts = await build_episode_scene_extraction_summaries_nonblocking(",
            delta_inventory_anchor,
        )
        readiness_check = source.index(
            "public main character asset bundle incomplete:",
            scene_call,
        )
        final_commit = source.index("work_conn.commit()", readiness_check)

        self.assertNotIn(
            "work_conn.commit()",
            source[delta_inventory_anchor:readiness_check],
        )
        self.assertIn("commit_changes=False", source[scene_call:readiness_check])
        self.assertGreater(final_commit, readiness_check)

    def test_atomic_bundle_allows_internal_anonymous_main_without_public_assets(self):
        module = load_module()

        replacement_scope_keys = (
            module.build_public_main_protagonist_bundle_scope_keys(
                old_inventory_map={},
                new_inventory_map={
                    "character:anonymous-main": {
                        "work_role": "main_protagonist",
                        "public_chat_eligible": False,
                        "chat_readiness_v1": {
                            "character_chat_allowed": False,
                        },
                    }
                },
            )
        )

        self.assertEqual(replacement_scope_keys, set())

    def test_delta_candidate_filter_includes_scene_debt_after_foundation_repairs(self):
        module = load_module()
        rows = [
            {"product_id": 687, "episode_id": 101, "episode_no": 1, "character_asset_collection_eligible": 1},
            {"product_id": 687, "episode_id": 102, "episode_no": 2, "character_asset_collection_eligible": 1},
        ]

        with patch.object(module, "build_open_add_episode_id_set", return_value=set()), \
             patch.object(module, "build_sync_repair_episode_id_set", return_value=set()), \
             patch.object(module, "build_signal_repair_episode_id_set", return_value=set()), \
             patch.object(module, "build_scene_repair_episode_id_set", return_value={102}):
            filtered = module.filter_delta_candidate_rows(object(), rows, max_delta_episodes=0)

        self.assertEqual([row["episode_no"] for row in filtered], [2])
        self.assertEqual([row["_delta_reason"] for row in filtered], ["scene_repair"])

    def test_delta_candidate_filter_prioritizes_new_foundation_over_old_scene_debt(self):
        module = load_module()
        rows = [
            *[
                {"product_id": 687, "episode_id": episode_no, "episode_no": episode_no, "character_asset_collection_eligible": 1}
                for episode_no in range(1, 7)
            ],
            {"product_id": 687, "episode_id": 100, "episode_no": 100, "character_asset_collection_eligible": 1},
        ]

        with patch.object(module, "build_open_add_episode_id_set", return_value={100}), \
             patch.object(module, "build_sync_repair_episode_id_set", return_value=set()), \
             patch.object(module, "build_signal_repair_episode_id_set", return_value=set()), \
             patch.object(module, "build_scene_repair_episode_id_set", return_value=set(range(1, 7))):
            filtered = module.filter_delta_candidate_rows(object(), rows, max_delta_episodes=5)

        self.assertEqual(filtered[0]["episode_no"], 100)
        self.assertEqual(filtered[0]["_delta_reason"], "open_add")
        self.assertEqual(len(filtered), 5)

    def test_out_of_cohort_delta_filter_keeps_foundation_and_ignores_scene_debt(self):
        module = load_module()
        rows = [
            {"product_id": 787, "episode_id": 101, "episode_no": 16, "character_asset_collection_eligible": 0},
            {"product_id": 787, "episode_id": 102, "episode_no": 17, "character_asset_collection_eligible": 0},
        ]

        with patch.object(module, "build_open_add_episode_id_set", return_value=set()), \
             patch.object(module, "build_sync_repair_episode_id_set", return_value=set()), \
             patch.object(module, "build_signal_repair_episode_id_set", return_value={102}), \
             patch.object(module, "build_scene_repair_episode_id_set") as scene_repair:
            filtered = module.filter_delta_candidate_rows(object(), rows, max_delta_episodes=0)

        scene_repair.assert_not_called()
        self.assertEqual([row["episode_no"] for row in filtered], [17])
        self.assertEqual([row["_delta_reason"] for row in filtered], ["signal_repair"])
        self.assertFalse(filtered[0]["_character_asset_collection_eligible"])

    def test_inventory_source_scope_map_rejects_ambiguous_source_alias(self):
        module = load_module()
        inventory_map = {
            "character:민준A": {
                "canonical_character_key": "character:민준A",
                "source_character_keys": ["named:민준"],
            },
            "character:민준B": {
                "canonical_character_key": "character:민준B",
                "source_character_keys": ["named:민준", "named:민준B"],
            },
        }

        alias_map = module.build_inventory_source_scope_key_map(inventory_map)

        self.assertNotIn("named:민준", alias_map)
        self.assertEqual(alias_map["character:민준A"], "character:민준A")
        self.assertEqual(alias_map["named:민준B"], "character:민준B")
        legacy_row = module.fetch_legacy_summary_state_for_inventory_alias(
            {"named:민준": {"scope_key": "named:민준"}},
            scope_key="character:민준A",
            inventory_item=inventory_map["character:민준A"],
            allowed_alias_keys={
                alias_key
                for alias_key, owner_scope_key in alias_map.items()
                if owner_scope_key == "character:민준A"
            },
        )
        self.assertEqual(legacy_row, {})

        affected_scope_keys = module.compute_rp_affected_scope_keys(
            old_inventory_map=inventory_map,
            new_inventory_map=inventory_map,
            old_relation_map={},
            new_relation_map={},
            old_touched_signal_rows=[],
            new_touched_signal_rows=[
                signal_row(
                    1,
                    1,
                    [
                        signal_character(
                            character_key="named:민준",
                            display_name="민준",
                        )
                    ],
                )
            ],
            old_profile_map={"named:민준": {"character_key": "named:민준"}},
            old_examples_map={"named:민준": {"character_key": "named:민준"}},
        )
        self.assertNotIn("named:민준", affected_scope_keys)

    def test_delta_mode_allows_product_only_apply_for_internal_changed_row_filtering(self):
        module = load_module()
        args = SimpleNamespace(
            build_mode="delta",
            limit=0,
            product_ids=[687],
            episode_ids=None,
            episode_nos=None,
            max_delta_episodes=0,
        )

        module.validate_delta_args(args)

    def test_unchanged_touched_rp_scope_is_not_rebuilt_when_profile_and_examples_exist(self):
        module = load_module()
        signal_row = {
            "summary_id": 10,
            "source_hash": "signal-hash",
            "summary_text": """
            {
              "episode_no": 1,
              "mentioned_characters": [
                {
                  "character_key": "protagonist:named:hero",
                  "display_name": "주인공",
                  "relation_edges": []
                }
              ]
            }
            """,
        }
        inventory = {
            "protagonist:named:hero": {
                "character_key": "protagonist:named:hero",
                "display_name": "주인공",
                "is_protagonist": True,
                "distinct_episode_count": 3,
            }
        }
        profile_map = {"protagonist:named:hero": {"source_hash": "profile-hash"}}
        examples_map = {"protagonist:named:hero": {"source_hash": "examples-hash"}}

        affected = module.compute_rp_affected_scope_keys(
            old_inventory_map=inventory,
            new_inventory_map=inventory,
            old_relation_map={},
            new_relation_map={},
            old_touched_signal_rows=[signal_row],
            new_touched_signal_rows=[signal_row],
            old_profile_map=profile_map,
            old_examples_map=examples_map,
        )

        self.assertEqual(affected, set())

    def test_missing_rp_outputs_are_rebuilt_even_when_inventory_is_unchanged(self):
        module = load_module()
        signal_row = {
            "summary_id": 10,
            "source_hash": "signal-hash",
            "summary_text": """
            {
              "episode_no": 1,
              "mentioned_characters": [
                {
                  "character_key": "protagonist:named:hero",
                  "display_name": "주인공",
                  "relation_edges": []
                }
              ]
            }
            """,
        }
        inventory = {
            "protagonist:named:hero": {
                "character_key": "protagonist:named:hero",
                "display_name": "주인공",
                "is_protagonist": True,
                "distinct_episode_count": 3,
            }
        }

        affected = module.compute_rp_affected_scope_keys(
            old_inventory_map=inventory,
            new_inventory_map=inventory,
            old_relation_map={},
            new_relation_map={},
            old_touched_signal_rows=[signal_row],
            new_touched_signal_rows=[signal_row],
            old_profile_map={},
            old_examples_map={},
        )

        self.assertEqual(affected, {"protagonist:named:hero"})

    def test_missing_character_chat_internal_prompt_rebuilds_touched_scope(self):
        module = load_module()
        signal_row = {
            "summary_id": 10,
            "source_hash": "signal-hash",
            "summary_text": """
            {
              "episode_no": 1,
              "mentioned_characters": [
                {
                  "character_key": "protagonist:named:hero",
                  "display_name": "주인공",
                  "relation_edges": []
                }
              ]
            }
            """,
        }
        inventory = {
            "protagonist:named:hero": {
                "character_key": "protagonist:named:hero",
                "display_name": "주인공",
                "is_protagonist": True,
                "distinct_episode_count": 3,
            }
        }

        affected = module.compute_rp_affected_scope_keys(
            old_inventory_map=inventory,
            new_inventory_map=inventory,
            old_relation_map={},
            new_relation_map={},
            old_touched_signal_rows=[signal_row],
            new_touched_signal_rows=[signal_row],
            old_profile_map={"protagonist:named:hero": {"source_hash": "profile-hash"}},
            old_examples_map={"protagonist:named:hero": {"source_hash": "examples-hash"}},
            old_internal_prompt_map={},
        )

        self.assertEqual(affected, {"protagonist:named:hero"})

    def test_changed_rp_inventory_is_rebuilt(self):
        module = load_module()
        signal_row = {
            "summary_id": 10,
            "source_hash": "signal-hash",
            "summary_text": """
            {
              "episode_no": 1,
              "mentioned_characters": [
                {
                  "character_key": "protagonist:named:hero",
                  "display_name": "주인공",
                  "relation_edges": []
                }
              ]
            }
            """,
        }
        old_inventory = {
            "protagonist:named:hero": {
                "character_key": "protagonist:named:hero",
                "display_name": "주인공",
                "is_protagonist": True,
                "distinct_episode_count": 3,
            }
        }
        new_inventory = {
            "protagonist:named:hero": {
                "character_key": "protagonist:named:hero",
                "display_name": "주인공",
                "is_protagonist": True,
                "distinct_episode_count": 4,
            }
        }
        profile_map = {"protagonist:named:hero": {"source_hash": "profile-hash"}}
        examples_map = {"protagonist:named:hero": {"source_hash": "examples-hash"}}

        affected = module.compute_rp_affected_scope_keys(
            old_inventory_map=old_inventory,
            new_inventory_map=new_inventory,
            old_relation_map={},
            new_relation_map={},
            old_touched_signal_rows=[signal_row],
            new_touched_signal_rows=[signal_row],
            old_profile_map=profile_map,
            old_examples_map=examples_map,
        )

        self.assertEqual(affected, {"protagonist:named:hero"})

    def test_v3_inventory_source_keys_drive_delta_rp_scope_resolution(self):
        module = load_module()
        signal_row = {
            "summary_id": 10,
            "source_hash": "signal-hash",
            "summary_text": """
            {
              "episode_no": 1,
              "mentioned_characters": [
                {
                  "character_key": "protagonist:named:hero",
                  "display_name": "백이현",
                  "relation_edges": []
                }
              ]
            }
            """,
        }
        inventory = {
            "character:백이현": {
                "canonical_character_key": "character:백이현",
                "source_character_keys": ["protagonist:named:hero"],
                "display_name": "백이현",
                "is_protagonist": True,
                "distinct_episode_count": 3,
            }
        }

        self.assertEqual(
            module.compute_rp_affected_scope_keys(
                old_inventory_map=inventory,
                new_inventory_map=inventory,
                old_relation_map={},
                new_relation_map={},
                old_touched_signal_rows=[signal_row],
                new_touched_signal_rows=[signal_row],
                old_profile_map={"character:백이현": {"source_hash": "profile-hash"}},
                old_examples_map={"character:백이현": {"source_hash": "examples-hash"}},
            ),
            set(),
        )
        self.assertEqual(
            module.compute_rp_affected_scope_keys(
                old_inventory_map=inventory,
                new_inventory_map=inventory,
                old_relation_map={},
                new_relation_map={},
                old_touched_signal_rows=[signal_row],
                new_touched_signal_rows=[signal_row],
                old_profile_map={},
                old_examples_map={},
            ),
            {"character:백이현"},
        )
        self.assertEqual(
            module.compute_rp_affected_scope_keys(
                old_inventory_map=inventory,
                new_inventory_map=inventory,
                old_relation_map={},
                new_relation_map={},
                old_touched_signal_rows=[signal_row],
                new_touched_signal_rows=[signal_row],
                old_profile_map={"protagonist:named:hero": {"source_hash": "legacy-profile-hash"}},
                old_examples_map={"protagonist:named:hero": {"source_hash": "legacy-examples-hash"}},
            ),
            {"character:백이현", "protagonist:named:hero"},
        )

    def test_v3_relation_only_change_marks_canonical_rp_scope_affected(self):
        module = load_module()
        signal_row = {
            "summary_id": 10,
            "source_hash": "signal-hash",
            "summary_text": """
            {
              "episode_no": 1,
              "mentioned_characters": [
                {
                  "character_key": "protagonist:named:hero",
                  "display_name": "백이현",
                  "relation_edges": [
                    {"target_key": "named:rival", "relation_tag": "대립", "direction": "to_target"}
                  ]
                }
              ]
            }
            """,
        }
        inventory = {
            "character:백이현": {
                "canonical_character_key": "character:백이현",
                "source_character_keys": ["protagonist:named:hero"],
                "display_name": "백이현",
                "is_protagonist": True,
                "distinct_episode_count": 3,
            }
        }
        old_relation_map = {
            "protagonist:named:hero=>named:rival": {
                "relation_key": "protagonist:named:hero=>named:rival",
                "source_key": "protagonist:named:hero",
                "target_key": "named:rival",
                "relation_tags": ["경계"],
            }
        }
        new_relation_map = {
            "protagonist:named:hero=>named:rival": {
                "relation_key": "protagonist:named:hero=>named:rival",
                "source_key": "protagonist:named:hero",
                "target_key": "named:rival",
                "relation_tags": ["대립"],
            }
        }

        affected = module.compute_rp_affected_scope_keys(
            old_inventory_map=inventory,
            new_inventory_map=inventory,
            old_relation_map=old_relation_map,
            new_relation_map=new_relation_map,
            old_touched_signal_rows=[signal_row],
            new_touched_signal_rows=[signal_row],
            old_profile_map={"character:백이현": {"source_hash": "profile-hash"}},
            old_examples_map={"character:백이현": {"source_hash": "examples-hash"}},
        )

        self.assertEqual(affected, {"character:백이현"})

    def test_canonical_relation_map_resolves_legacy_source_key_for_v3_rp_context(self):
        module = load_module()
        relation_map = {
            "protagonist:named:hero": [
                {
                    "relation_key": "protagonist:named:hero=>named:rival",
                    "source_key": "protagonist:named:hero",
                    "target_key": "named:rival",
                    "target_display_name": "라이벌",
                    "dominant_relation_tags": ["대립"],
                    "distinct_episode_count": 3,
                    "latest_seen_episode_no": 8,
                }
            ]
        }
        inventory_map = {
            "character:백이현": {
                "canonical_character_key": "character:백이현",
                "source_character_keys": ["protagonist:named:hero"],
                "display_name": "백이현",
            }
        }

        canonical_map = module.build_canonical_relation_inventory_map(
            relation_map=relation_map,
            inventory_map=inventory_map,
        )
        lines = module.build_rp_relation_context_lines(
            character_key="character:백이현",
            relation_map=canonical_map,
        )

        self.assertEqual(list(canonical_map.keys()), ["character:백이현"])
        self.assertEqual(lines, ["- 대상: 라이벌 | 관계 태그: 대립 | 반복 화수: 3 | 최근: 8화"])

    def test_provider_relation_map_excludes_preserved_over_cap_relation(self):
        module = load_module()
        capped_signal_rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="named:main",
                        display_name="주인공",
                    )
                ],
            )
        ]
        inventory_map = {
            "character:main": {
                "source_character_keys": ["named:main"],
                "display_name": "주인공",
            }
        }

        provider_relation_map = module.build_character_asset_relation_inventory_map(
            signal_rows=capped_signal_rows,
            inventory_map=inventory_map,
        )

        self.assertEqual(provider_relation_map, {})
        self.assertEqual(
            module.build_rp_relation_context_lines(
                character_key="character:main",
                relation_map=provider_relation_map,
            ),
            [],
        )

    def test_changed_rp_relation_context_is_rebuilt(self):
        module = load_module()
        signal_row = {
            "summary_id": 10,
            "source_hash": "signal-hash",
            "summary_text": """
            {
              "episode_no": 1,
              "mentioned_characters": [
                {
                  "character_key": "protagonist:named:hero",
                  "display_name": "주인공",
                  "relation_edges": [
                    {
                      "target_key": "named:rival",
                      "relation_tag": "대립",
                      "direction": "to_target"
                    }
                  ]
                },
                {
                  "character_key": "named:rival",
                  "display_name": "라이벌",
                  "relation_edges": []
                }
              ]
            }
            """,
        }
        inventory = {
            "protagonist:named:hero": {
                "character_key": "protagonist:named:hero",
                "display_name": "주인공",
                "is_protagonist": True,
                "distinct_episode_count": 3,
            },
            "named:rival": {
                "character_key": "named:rival",
                "display_name": "라이벌",
                "entity_kind": "person",
                "distinct_episode_count": 3,
            },
        }
        old_relation_map = {
            "protagonist:named:hero=>named:rival": {
                "relation_key": "protagonist:named:hero=>named:rival",
                "source_key": "protagonist:named:hero",
                "target_key": "named:rival",
                "relation_tags": ["경계"],
            }
        }
        new_relation_map = {
            "protagonist:named:hero=>named:rival": {
                "relation_key": "protagonist:named:hero=>named:rival",
                "source_key": "protagonist:named:hero",
                "target_key": "named:rival",
                "relation_tags": ["대립"],
            }
        }
        profile_map = {
            "protagonist:named:hero": {"source_hash": "profile-hash"},
            "named:rival": {"source_hash": "profile-hash"},
        }
        examples_map = {
            "protagonist:named:hero": {"source_hash": "examples-hash"},
            "named:rival": {"source_hash": "examples-hash"},
        }

        affected = module.compute_rp_affected_scope_keys(
            old_inventory_map=inventory,
            new_inventory_map=inventory,
            old_relation_map=old_relation_map,
            new_relation_map=new_relation_map,
            old_touched_signal_rows=[signal_row],
            new_touched_signal_rows=[signal_row],
            old_profile_map=profile_map,
            old_examples_map=examples_map,
        )

        self.assertEqual(affected, {"protagonist:named:hero", "named:rival"})


class FakeRollbackConnection(FakeConnection):
    def __init__(self):
        super().__init__()
        self.rollback_count = 0

    def rollback(self):
        self.rollback_count += 1


class InventoryReaggregationTest(IsolatedAsyncioTestCase):
    def test_generic_first_person_relation_does_not_poison_named_alias_across_episodes(self):
        module = load_module()
        locked_main = {
            "canonical_character_key": "character:레이븐:durable",
            "display_name": "레이븐",
            "work_role": "main_protagonist",
            "source_character_keys": [
                "protagonist:first_person",
                "protagonist:named:레이븐",
            ],
        }
        rows = [
            *[
                signal_row(
                    episode_no,
                    episode_no,
                    [
                        signal_character(
                            character_key="protagonist:named:레이븐",
                            display_name="레이븐",
                            is_protagonist=True,
                            is_work_protagonist=True,
                            is_episode_focal=True,
                            role_in_episode="lead",
                            scene_weight="high",
                        )
                    ],
                )
                for episode_no in range(1, 4)
            ],
            signal_row(
                4,
                4,
                [
                    signal_character(
                        character_key="protagonist:first_person",
                        display_name="소년",
                        aliases=["소년"],
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        is_first_person=True,
                        role_in_episode="lead",
                    ),
                    signal_character(
                        character_key="named:레이븐",
                        display_name="레이븐",
                        aliases=["레이븐"],
                        role_in_episode="support",
                        relation_edges=[
                            {
                                "target_key": "protagonist:first_person",
                                "target_label": "소년",
                                "relation_tag": "협력",
                                "direction": "mutual",
                            }
                        ],
                    ),
                ],
            ),
            signal_row(
                5,
                5,
                [
                    signal_character(
                        character_key="named:레이븐",
                        display_name="레이븐",
                        aliases=["레이븐"],
                        role_in_episode="support",
                    )
                ],
            ),
        ]

        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            locked_protagonist_rows=[locked_main],
        )
        raven_rows = [row for row in inventory if row["display_name"] == "레이븐"]

        self.assertEqual(len(raven_rows), 1)
        self.assertEqual(raven_rows[0]["work_role"], "main_protagonist")
        self.assertEqual(raven_rows[0]["latest_seen_episode_no"], 5)
        self.assertEqual(raven_rows[0]["evidence_episode_nos"], [1, 2, 3, 4, 5])
        self.assertEqual(
            set(raven_rows[0]["source_character_keys"]),
            {
                "named:레이븐",
                "protagonist:named:레이븐",
            },
        )
        self.assertEqual(
            len([row for row in inventory if row["display_name"] == "소년"]),
            1,
        )

    def test_same_episode_same_label_distinct_source_keys_remain_separate(self):
        module = load_module()
        locked_main = {
            "canonical_character_key": "character:레이븐:durable",
            "display_name": "레이븐",
            "work_role": "main_protagonist",
            "source_character_keys": [
                "protagonist:first_person",
                "protagonist:named:레이븐",
            ],
        }
        rows = [
            *[
                signal_row(
                    episode_no,
                    episode_no,
                    [
                        signal_character(
                            character_key="protagonist:named:레이븐",
                            display_name="레이븐",
                            is_protagonist=True,
                            is_work_protagonist=True,
                            is_episode_focal=True,
                            role_in_episode="lead",
                            scene_weight="high",
                        )
                    ],
                )
                for episode_no in range(1, 4)
            ],
            signal_row(
                4,
                4,
                [
                    signal_character(
                        character_key="named:레이븐:a",
                        display_name="레이븐",
                        role_in_episode="lead",
                    ),
                    signal_character(
                        character_key="named:레이븐:b",
                        display_name="레이븐",
                        aliases=["레이븐"],
                        role_in_episode="support",
                    ),
                ],
            )
        ]

        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            locked_protagonist_rows=[locked_main],
        )

        self.assertEqual(
            len([row for row in inventory if row["display_name"] == "레이븐"]),
            2,
        )

    def test_shared_role_label_does_not_merge_distinct_ravens(self):
        module = load_module()
        locked_main = {
            "canonical_character_key": "character:레이븐:durable",
            "display_name": "레이븐",
            "work_role": "main_protagonist",
            "source_character_keys": ["protagonist:named:레이븐"],
        }
        rows = [
            *[
                signal_row(
                    episode_no,
                    episode_no,
                    [
                        signal_character(
                            character_key="protagonist:named:레이븐",
                            display_name="레이븐",
                            aliases=["레이븐"],
                            is_protagonist=True,
                            is_work_protagonist=True,
                            is_episode_focal=True,
                            is_first_person=True,
                            role_in_episode="lead",
                            voice_mode="monologue",
                            scene_weight="high",
                        ),
                        signal_character(
                            character_key="named:수염난레이븐",
                            display_name="수염 난 레이븐",
                            aliases=["수염 난 레이븐", "레이븐"],
                            is_episode_focal=True,
                            role_in_episode="counterpart",
                            voice_mode="dialogue",
                            scene_weight="medium",
                        ),
                    ],
                )
                for episode_no in range(1, 3)
            ],
            *[
                signal_row(
                    episode_no,
                    episode_no,
                    [
                        signal_character(
                            character_key="protagonist:named:레이븐",
                            display_name="레이븐",
                            aliases=["레이븐"],
                            is_protagonist=True,
                            is_work_protagonist=True,
                            is_episode_focal=True,
                            is_first_person=True,
                            role_in_episode="lead",
                            voice_mode="monologue",
                            scene_weight="high",
                        ),
                        signal_character(
                            character_key="named:키큰레이븐",
                            display_name="키 큰 레이븐",
                            aliases=["키 큰 레이븐", "레이븐"],
                            is_episode_focal=True,
                            role_in_episode="counterpart",
                            voice_mode="dialogue",
                            scene_weight="medium",
                        ),
                    ],
                )
                for episode_no in range(3, 5)
            ],
        ]

        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            locked_protagonist_rows=[locked_main],
        )
        source_sets = {
            frozenset(row["source_character_keys"]): row
            for row in inventory
        }

        self.assertIn(frozenset({"protagonist:named:레이븐"}), source_sets)
        self.assertIn(frozenset({"named:수염난레이븐"}), source_sets)
        self.assertIn(frozenset({"named:키큰레이븐"}), source_sets)
        main = source_sets[frozenset({"protagonist:named:레이븐"})]
        self.assertEqual(main["work_role"], "main_protagonist")
        self.assertIn("레이븐", main["non_unique_identity_labels"])

    def test_same_episode_canonical_named_and_protagonist_sources_can_merge(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        character_key="protagonist:named:레이븐",
                        display_name="레이븐",
                        is_protagonist=True,
                        is_work_protagonist=True,
                        is_episode_focal=True,
                        role_in_episode="lead",
                    ),
                    signal_character(
                        character_key="named:레이븐",
                        display_name="레이븐",
                        aliases=["레이븐"],
                        role_in_episode="support",
                    ),
                ],
            )
        ]

        inventory = module.aggregate_character_inventory_v3_rows(rows)
        raven_rows = [row for row in inventory if row["display_name"] == "레이븐"]

        self.assertEqual(len(raven_rows), 1)
        self.assertEqual(
            set(raven_rows[0]["source_character_keys"]),
            {"named:레이븐", "protagonist:named:레이븐"},
        )

    def test_reaggregate_flag_requires_delta_mode(self):
        module = load_module()
        args = SimpleNamespace(
            build_mode="full",
            repair_character_assets=False,
            reaggregate_character_inventory=True,
        )
        with self.assertRaises(ValueError):
            module.validate_delta_args(args)

    def test_reaggregate_flag_requires_apply(self):
        module = load_module()
        args = SimpleNamespace(
            build_mode="delta",
            repair_character_assets=False,
            reaggregate_character_inventory=True,
            limit=0,
            product_ids=[1103],
            max_delta_episodes=2,
            apply=False,
        )
        with self.assertRaises(ValueError):
            module.validate_delta_args(args)

    async def test_inventory_reaggregation_runs_without_provider(self):
        module = load_module()
        conn = FakeRollbackConnection()
        results = module.build_empty_results()
        active_signal_rows = [
            signal_row(
                1,
                116,
                [
                    signal_character(
                        character_key="named:레이븐",
                        display_name="레이븐",
                        is_work_protagonist=True,
                        is_episode_focal=True,
                    )
                ],
            )
        ]
        old_inventory_map = {
            "named:레이븐": {
                "character_key": "named:레이븐",
                "display_name": "레이븐",
                "latest_seen_episode_no": 110,
            }
        }
        old_relation_map = {
            "named:레이븐=>named:소년": {
                "relation_key": "named:레이븐=>named:소년",
                "source_key": "named:레이븐",
                "source_display_name": "레이븐",
                "target_key": "named:소년",
                "target_display_name": "소년",
            }
        }
        inventory_builder = MagicMock(
            return_value={"inserted_count": 1, "reused_count": 2}
        )
        inventory_v3_builder = MagicMock(return_value=(3, 4))
        relation_builder = MagicMock(
            return_value={"inserted_count": 0, "reused_count": 5}
        )
        invariants = MagicMock()

        with patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())), \
             patch.object(module, "fetch_active_character_asset_summary_rows", return_value=active_signal_rows), \
             patch.object(module, "fetch_active_character_inventory_map", return_value=old_inventory_map), \
             patch.object(module, "fetch_active_relation_inventory_by_relation_key_map", return_value=old_relation_map), \
             patch.object(module, "build_character_inventory_summaries_delta", inventory_builder), \
             patch.object(module, "build_character_inventory_v3_summaries", inventory_v3_builder), \
             patch.object(module, "build_relation_inventory_summaries_delta", relation_builder), \
             patch.object(module, "build_character_inventory_summaries") as destructive_inventory_builder, \
             patch.object(module, "build_relation_inventory_summaries") as destructive_relation_builder, \
             patch.object(module, "cleanup_duplicate_character_inventory_rows") as character_cleanup, \
             patch.object(module, "cleanup_duplicate_relation_inventory_rows") as relation_cleanup, \
             patch.object(module, "assert_story_agent_foundation_invariants", invariants), \
             patch.object(module, "touch_product_context_build_attempt") as touch:
            await module.reaggregate_character_inventory_foundations(
                rows=[{"product_id": 1103, "title": "테스트 작품"}],
                args=SimpleNamespace(apply=True, verbose=False),
                results=results,
            )

        inventory_builder.assert_called_once_with(
            ANY,
            product_id=1103,
            old_inventory_map=old_inventory_map,
            old_touched_signal_rows=active_signal_rows,
            new_touched_signal_rows=active_signal_rows,
        )
        inventory_v3_builder.assert_called_once_with(
            cur=ANY,
            product_id=1103,
            protagonist_resolution=None,
            cleanup_missing_scopes=False,
        )
        relation_builder.assert_called_once_with(
            ANY,
            product_id=1103,
            old_relation_map=old_relation_map,
            old_touched_signal_rows=active_signal_rows,
            new_touched_signal_rows=active_signal_rows,
        )
        destructive_inventory_builder.assert_not_called()
        destructive_relation_builder.assert_not_called()
        character_cleanup.assert_not_called()
        relation_cleanup.assert_not_called()
        invariants.assert_called_once_with(
            cur=ANY,
            product_id=1103,
            require_signal_coverage=False,
        )
        touch.assert_called_once()
        self.assertEqual(conn.commit_count, 1)
        self.assertEqual(results["inventory_reaggregation_attempted"], 1)
        self.assertEqual(results["inventory_reaggregation_updated"], 1)
        self.assertEqual(results["inventory_reaggregation_failed"], 0)
        self.assertEqual(results["inventory_reaggregations"][0]["status"], "updated")
        self.assertEqual(module.build_delta_exit_code(results, apply=True), 0)

    async def test_inventory_reaggregation_public_main_replacement_without_assets_rolls_back(self):
        module = load_module()
        conn = FakeRollbackConnection()
        results = module.build_empty_results()
        old_main = {
            "character:old": {
                "canonical_character_key": "character:old",
                "work_role": "main_protagonist",
                "public_chat_eligible": True,
            }
        }
        new_main = {
            "character:new": {
                "canonical_character_key": "character:new",
                "work_role": "main_protagonist",
                "public_chat_eligible": True,
            }
        }
        v3_reads = iter([old_main, new_main])

        def fetch_inventory_map(*, summary_type="character_inventory", **_kwargs):
            if summary_type == "character_inventory_v3":
                return next(v3_reads)
            return {}

        with patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())), \
             patch.object(module, "fetch_active_character_asset_summary_rows", return_value=[signal_row(1, 1, [])]), \
             patch.object(module, "fetch_active_character_inventory_map", side_effect=fetch_inventory_map), \
             patch.object(module, "fetch_active_relation_inventory_by_relation_key_map", return_value={}), \
             patch.object(module, "build_character_inventory_summaries_delta", return_value={"inserted_count": 1, "reused_count": 0}), \
             patch.object(module, "build_character_inventory_v3_summaries", return_value=(1, 0)), \
             patch.object(module, "build_relation_inventory_summaries_delta", return_value={"inserted_count": 0, "reused_count": 0}), \
             patch.object(module, "assert_story_agent_foundation_invariants"), \
             patch.object(module, "touch_product_context_build_attempt"), \
             patch.object(
                 module,
                 "fetch_character_chat_asset_readiness_verification",
                 return_value={"ready_main_protagonist_scope_keys": []},
             ):
            await module.reaggregate_character_inventory_foundations(
                rows=[{"product_id": 1103, "title": "테스트 작품"}],
                args=SimpleNamespace(apply=True, verbose=False),
                results=results,
            )

        self.assertEqual(conn.commit_count, 0)
        self.assertEqual(conn.rollback_count, 1)
        self.assertEqual(results["inventory_reaggregation_failed"], 1)
        self.assertEqual(results["inventory_reaggregations"][0]["status"], "failed")

    async def test_inventory_reaggregation_same_public_main_with_changed_evidence_and_stale_rp_rolls_back(self):
        module = load_module()
        conn = FakeRollbackConnection()
        results = module.build_empty_results()
        scope_key = "character:main"
        old_main = {
            scope_key: {
                "canonical_character_key": scope_key,
                "work_role": "main_protagonist",
                "public_chat_eligible": True,
                "distinct_episode_count": 3,
            }
        }
        new_main = {
            scope_key: {
                **old_main[scope_key],
                "distinct_episode_count": 30,
            }
        }
        v3_reads = iter([old_main, new_main])

        def fetch_inventory_map(*, summary_type="character_inventory", **_kwargs):
            if summary_type == "character_inventory_v3":
                return next(v3_reads)
            return {}

        with patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())), \
             patch.object(module, "fetch_active_character_asset_summary_rows", return_value=[signal_row(1, 1, [])]), \
             patch.object(module, "fetch_active_character_inventory_map", side_effect=fetch_inventory_map), \
             patch.object(module, "fetch_active_relation_inventory_by_relation_key_map", return_value={}), \
             patch.object(module, "build_character_inventory_summaries_delta", return_value={"inserted_count": 1, "reused_count": 0}), \
             patch.object(module, "build_character_inventory_v3_summaries", return_value=(1, 0)), \
             patch.object(module, "build_relation_inventory_summaries_delta", return_value={"inserted_count": 0, "reused_count": 0}), \
             patch.object(module, "assert_story_agent_foundation_invariants"), \
             patch.object(module, "touch_product_context_build_attempt"), \
             patch.object(
                 module,
                 "fetch_character_chat_asset_readiness_verification",
                 return_value={
                     "ready_main_protagonist_scope_keys": [scope_key]
                 },
             ):
            await module.reaggregate_character_inventory_foundations(
                rows=[{"product_id": 1103, "title": "테스트 작품"}],
                args=SimpleNamespace(apply=True, verbose=False),
                results=results,
            )

        self.assertEqual(conn.commit_count, 0)
        self.assertEqual(conn.rollback_count, 1)
        self.assertEqual(results["inventory_reaggregation_failed"], 1)

    async def test_inventory_reaggregation_no_progress_when_nothing_inserted(self):
        module = load_module()
        conn = FakeRollbackConnection()
        results = module.build_empty_results()
        active_signal_rows = [signal_row(1, 1, [])]

        with patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())), \
             patch.object(module, "fetch_active_character_asset_summary_rows", return_value=active_signal_rows), \
             patch.object(module, "fetch_active_character_inventory_map", return_value={}), \
             patch.object(module, "fetch_active_relation_inventory_by_relation_key_map", return_value={}), \
             patch.object(module, "build_character_inventory_summaries_delta", MagicMock(return_value={"inserted_count": 0, "reused_count": 3})), \
             patch.object(module, "build_character_inventory_v3_summaries", MagicMock(return_value=(0, 7))), \
             patch.object(module, "build_relation_inventory_summaries_delta", MagicMock(return_value={"inserted_count": 0, "reused_count": 2})), \
             patch.object(module, "assert_story_agent_foundation_invariants", MagicMock()), \
             patch.object(module, "touch_product_context_build_attempt"):
            await module.reaggregate_character_inventory_foundations(
                rows=[{"product_id": 1103, "title": "테스트 작품"}],
                args=SimpleNamespace(apply=True, verbose=False),
                results=results,
            )

        self.assertEqual(results["inventory_reaggregation_no_progress"], 1)
        self.assertEqual(results["inventory_reaggregation_updated"], 0)
        self.assertEqual(results["inventory_reaggregations"][0]["status"], "no_progress")

    async def test_inventory_reaggregation_without_active_signals_is_non_destructive_no_progress(self):
        module = load_module()
        conn = FakeRollbackConnection()
        results = module.build_empty_results()

        with patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())), \
             patch.object(module, "fetch_active_character_asset_summary_rows", return_value=[]), \
             patch.object(module, "build_character_inventory_summaries_delta") as inventory_builder, \
             patch.object(module, "build_character_inventory_v3_summaries") as inventory_v3_builder, \
             patch.object(module, "build_relation_inventory_summaries_delta") as relation_builder, \
             patch.object(module, "touch_product_context_build_attempt") as touch:
            await module.reaggregate_character_inventory_foundations(
                rows=[{"product_id": 1103, "title": "테스트 작품"}],
                args=SimpleNamespace(apply=True, verbose=False),
                results=results,
            )

        inventory_builder.assert_not_called()
        inventory_v3_builder.assert_not_called()
        relation_builder.assert_not_called()
        touch.assert_not_called()
        self.assertEqual(conn.commit_count, 0)
        self.assertEqual(conn.rollback_count, 0)
        self.assertEqual(results["inventory_reaggregation_no_progress"], 1)
        self.assertEqual(
            results["inventory_reaggregations"][0],
            {
                "product_id": 1103,
                "status": "no_progress",
                "reason": "no_active_character_signals",
            },
        )

    def test_reaggregation_invariant_allows_incomplete_signal_coverage(self):
        module = load_module()
        count_rows = [
            {
                "episode_summary_count": 117,
                "signal_count": 115,
                "inventory_count": 123,
                "inventory_v3_count": 160,
                "missing_required_signal_count": 0,
            }
        ]

        module.assert_story_agent_foundation_invariants(
            FakeRowsCursor(count_rows),
            product_id=1103,
            require_signal_coverage=False,
        )
        module.assert_story_agent_foundation_invariants(
            FakeRowsCursor(count_rows),
            product_id=1103,
        )
        with self.assertRaisesRegex(ValueError, "missing_required_episode_character_signals=1"):
            module.assert_story_agent_foundation_invariants(
                FakeRowsCursor(
                    [
                        {
                            "episode_summary_count": 117,
                            "signal_count": 114,
                            "inventory_count": 123,
                            "inventory_v3_count": 160,
                            "missing_required_signal_count": 1,
                        }
                    ]
                ),
                product_id=1103,
            )

    async def test_inventory_reaggregation_failure_rolls_back_and_sets_failed_exit(self):
        module = load_module()
        conn = FakeRollbackConnection()
        results = module.build_empty_results()
        invariants = MagicMock(side_effect=ValueError("foundation invariant broken"))

        with patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())), \
             patch.object(module, "fetch_active_character_asset_summary_rows", return_value=[signal_row(1, 1, [])]), \
             patch.object(module, "fetch_active_character_inventory_map", return_value={}), \
             patch.object(module, "fetch_active_relation_inventory_by_relation_key_map", return_value={}), \
             patch.object(module, "build_character_inventory_summaries_delta", MagicMock(return_value={"inserted_count": 1, "reused_count": 0})), \
             patch.object(module, "build_character_inventory_v3_summaries", MagicMock(return_value=(1, 0))), \
             patch.object(module, "build_relation_inventory_summaries_delta", MagicMock(return_value={"inserted_count": 1, "reused_count": 0})), \
             patch.object(module, "assert_story_agent_foundation_invariants", invariants), \
             patch.object(module, "touch_product_context_build_attempt"):
            await module.reaggregate_character_inventory_foundations(
                rows=[{"product_id": 1103, "title": "테스트 작품"}],
                args=SimpleNamespace(apply=True, verbose=False),
                results=results,
            )

        self.assertEqual(conn.commit_count, 0)
        self.assertEqual(conn.rollback_count, 1)
        self.assertEqual(results["inventory_reaggregation_failed"], 1)
        self.assertEqual(results["inventory_reaggregations"][0]["status"], "failed")
        self.assertEqual(module.build_delta_exit_code(results, apply=True), 1)

    async def test_inventory_reaggregation_stale_review_is_review_required(self):
        module = load_module()
        conn = FakeRollbackConnection()
        results = module.build_empty_results()
        stale_error = module.CharacterIdentityReviewStaleError(
            "stale character identity review signal: confirm-main summary_id=1",
            product_id=1176,
            operation_id="confirm-main",
            reason_code="signal_anchor_changed",
        )
        relation_builder = MagicMock()

        with patch.object(module, "db_connect", return_value=conn), \
             patch.object(module, "work_cursor", fake_work_cursor), \
             patch.object(module, "product_lock_connection", return_value=module.nullcontext(object())), \
             patch.object(module, "fetch_active_character_asset_summary_rows", return_value=[signal_row(1, 1, [])]), \
             patch.object(module, "fetch_active_character_inventory_map", return_value={}), \
             patch.object(module, "fetch_active_relation_inventory_by_relation_key_map", return_value={}), \
             patch.object(module, "build_character_inventory_summaries_delta", return_value={"inserted_count": 1, "reused_count": 0}), \
             patch.object(module, "build_character_inventory_v3_summaries", side_effect=stale_error), \
             patch.object(module, "build_relation_inventory_summaries_delta", relation_builder), \
             patch.object(module, "fetch_total_episode_count", return_value=69), \
             patch.object(module, "fetch_product_context_status", return_value="ready"), \
             patch.object(module, "fetch_product_ready_episode_count", return_value=69), \
             patch.object(module, "touch_product_context_build_attempt") as touch:
            await module.reaggregate_character_inventory_foundations(
                rows=[{"product_id": 1176, "title": "테스트 작품"}],
                args=SimpleNamespace(apply=True, verbose=False),
                results=results,
            )

        relation_builder.assert_not_called()
        touch.assert_not_called()
        self.assertEqual(conn.commit_count, 0)
        self.assertEqual(conn.rollback_count, 2)
        self.assertEqual(results["inventory_reaggregation_failed"], 0)
        self.assertEqual(results["review_required"], 1)
        self.assertEqual(
            results["inventory_reaggregations"][0]["status"],
            "review_required",
        )
        self.assertEqual(results["products"][0]["context_status"], "review_required")
        self.assertEqual(results["products"][0]["persisted_context_status"], "ready")
        self.assertEqual(
            module.build_delta_exit_code(results, apply=True),
            module.STORYCTX_REVIEW_REQUIRED_EXIT_CODE,
        )
