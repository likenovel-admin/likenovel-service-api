import importlib.util
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_story_agent_context.py"
CLI_PATH = Path(__file__).resolve().parents[1] / "scripts" / "apply_story_agent_identity_review.py"


def load_module():
    module_name = "build_story_agent_context_identity_review_test"
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


def load_cli(story_agent_module):
    module_name = "apply_story_agent_identity_review_test"
    spec = importlib.util.spec_from_file_location(module_name, CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    old_story_agent = sys.modules.get("build_story_agent_context")
    sys.modules["build_story_agent_context"] = story_agent_module
    try:
        spec.loader.exec_module(module)
    finally:
        if old_story_agent is None:
            sys.modules.pop("build_story_agent_context", None)
        else:
            sys.modules["build_story_agent_context"] = old_story_agent
    return module


def signal_character(
    character_key: str,
    display_name: str,
    *,
    aliases=None,
    protagonist=False,
    first_person=False,
    voice_mode="dialogue",
):
    return {
        "character_key": character_key,
        "display_name": display_name,
        "aliases": list(aliases or [display_name]),
        "entity_kind": "person",
        "is_protagonist": protagonist,
        "is_work_protagonist": protagonist,
        "is_episode_focal": protagonist,
        "is_first_person": first_person,
        "narration_names": [],
        "social_call_names": [],
        "persona_names": [],
        "real_names": [],
        "scene_weight": "high" if protagonist else "medium",
        "role_in_episode": "lead" if protagonist else "support",
        "voice_mode": voice_mode,
        "action_tags": [],
        "affect_tags": [],
        "relation_edges": [],
        "identity_claims": [],
    }


def signal_row(summary_id: int, episode_no: int, characters: list[dict]):
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


def review_document(module, product_id: int, operations: list[dict]):
    return module.normalize_character_identity_review_document(
        {
            "schema_version": "character_identity_review_v1",
            "product_id": product_id,
            "review_origin": "operator_cli",
            "reviewer_id": "codex.ops",
            "operations": operations,
        }
    )


class CharacterIdentityReviewTest(TestCase):
    def test_request_rejects_source_key_and_display_name_authority(self):
        module = load_module()
        request = {
            "schema_version": "character_identity_review_request_v1",
            "product_id": 1105,
            "operations": [
                {
                    "operation_id": "unsafe",
                    "kind": "confirm_protagonist",
                    "scope_key": "character:마왕성천제",
                    "source_character_keys": ["protagonist:first_person"],
                    "display_name": "추종자",
                    "reason": "must be rejected",
                }
            ],
        }
        with patch.object(
            module,
            "fetch_active_character_inventory_map",
            return_value={},
        ), patch.object(
            module,
            "fetch_active_summary_rows",
            return_value=[],
        ), self.assertRaisesRegex(ValueError, "unknown identity review request"):
            module.materialize_character_identity_review_document(
                object(),
                product_id=1105,
                request=request,
                reviewer_id="codex.ops",
            )

    def test_materializer_pins_current_observation_refs_and_hashes(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character("named:에릭", "에릭"),
                    signal_character("named:에릭애시퍼드", "에릭 애시퍼드"),
                ],
            )
        ]
        inventory_map = {
            "character:에릭": {
                "source_observation_refs": ["summary:1:0"],
                "public_chat_eligible": True,
            },
            "character:에릭애시퍼드": {
                "source_observation_refs": ["summary:1:1"],
                "public_chat_eligible": False,
            },
        }
        request = {
            "schema_version": "character_identity_review_request_v1",
            "product_id": 1149,
            "operations": [
                {
                    "operation_id": "merge-eric",
                    "kind": "merge_active_scopes",
                    "member_scope_keys": [
                        "character:에릭",
                        "character:에릭애시퍼드",
                    ],
                    "target_scope_key": "character:에릭",
                    "force_main_protagonist": True,
                    "reason": "same narrator",
                }
            ],
        }
        with patch.object(
            module,
            "fetch_active_character_inventory_map",
            return_value=inventory_map,
        ), patch.object(
            module,
            "fetch_active_summary_rows",
            return_value=rows,
        ):
            document = module.materialize_character_identity_review_document(
                object(),
                product_id=1149,
                request=request,
                reviewer_id="codex.ops",
            )
        operation = document["operations"][0]
        self.assertEqual(
            operation["authorized_observation_refs"],
            ["summary:1:0", "summary:1:1"],
        )
        self.assertEqual(
            operation["signal_anchors"],
            [{"summary_id": 1, "source_hash": "signal-1"}],
        )
        self.assertTrue(document["review_digest"])

    def test_materializer_accepts_source_backed_display_and_existing_blocked_aliases(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    {
                        **signal_character(
                            "protagonist:named:라파엘",
                            "라파엘",
                            protagonist=True,
                        ),
                        "persona_names": ["안드레이 카르마조프"],
                    }
                ],
            )
        ]
        inventory_map = {
            "character:라파엘더리퍼": {
                "display_name": "라파엘",
                "source_character_keys": ["protagonist:named:라파엘"],
                "source_observation_refs": ["summary:1:0"],
                "aliases": ["라파엘", "안드레이 카르마조프"],
                "persona_names": ["안드레이 카르마조프"],
                "public_chat_eligible": True,
            }
        }
        request = {
            "schema_version": "character_identity_review_request_v1",
            "product_id": 1176,
            "operations": [
                {
                    "operation_id": "confirm-raphael-surface",
                    "kind": "confirm_protagonist",
                    "scope_key": "character:라파엘더리퍼",
                    "canonical_display_name": "라파엘",
                    "blocked_aliases": ["안드레이 카르마조프"],
                    "reason": "reviewed protagonist identity surface",
                }
            ],
        }
        with patch.object(
            module,
            "fetch_active_character_inventory_map",
            return_value=inventory_map,
        ), patch.object(
            module,
            "fetch_active_summary_rows",
            return_value=rows,
        ):
            document = module.materialize_character_identity_review_document(
                object(),
                product_id=1176,
                request=request,
                reviewer_id="codex.ops",
            )

        operation = document["operations"][0]
        self.assertEqual(operation["canonical_display_name"], "라파엘")
        self.assertEqual(operation["blocked_aliases"], ["안드레이 카르마조프"])

    def test_materializer_rejects_unbacked_display_and_missing_blocked_alias(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [signal_character("protagonist:named:한도윤", "한도윤", protagonist=True)],
            )
        ]
        inventory_map = {
            "character:한도윤": {
                "display_name": "실패한 왕",
                "source_character_keys": ["protagonist:named:한도윤"],
                "source_observation_refs": ["summary:1:0"],
                "aliases": ["실패한 왕", "한도윤"],
                "public_chat_eligible": True,
            }
        }
        base_operation = {
            "operation_id": "confirm-han-doyun",
            "kind": "confirm_protagonist",
            "scope_key": "character:한도윤",
            "reason": "reviewed protagonist identity surface",
        }
        with patch.object(
            module,
            "fetch_active_character_inventory_map",
            return_value=inventory_map,
        ), patch.object(
            module,
            "fetch_active_summary_rows",
            return_value=rows,
        ):
            with self.assertRaisesRegex(ValueError, "source-backed display"):
                module.materialize_character_identity_review_document(
                    object(),
                    product_id=1148,
                    request={
                        "schema_version": "character_identity_review_request_v1",
                        "product_id": 1148,
                        "operations": [
                            {**base_operation, "canonical_display_name": "전혀 다른 이름"}
                        ],
                    },
                    reviewer_id="codex.ops",
                )
            with self.assertRaisesRegex(ValueError, "active identity alias"):
                module.materialize_character_identity_review_document(
                    object(),
                    product_id=1148,
                    request={
                        "schema_version": "character_identity_review_request_v1",
                        "product_id": 1148,
                        "operations": [
                            {**base_operation, "blocked_aliases": ["없는 별칭"]}
                        ],
                    },
                    reviewer_id="codex.ops",
                )

    def test_stale_signal_hash_fails_closed(self):
        module = load_module()
        rows = [signal_row(1, 1, [signal_character("named:에릭", "에릭")])]
        document = review_document(
            module,
            1149,
            [
                {
                    "operation_id": "confirm-eric",
                    "kind": "confirm_protagonist",
                    "member_scope_keys": ["character:에릭"],
                    "target_scope_key": "character:에릭",
                    "authorized_observation_refs": ["summary:1:0"],
                    "signal_anchors": [
                        {"summary_id": 1, "source_hash": "old-hash"}
                    ],
                    "force_main_protagonist": True,
                    "anonymous_protagonist": False,
                    "reason": "reviewed protagonist",
                }
            ],
        )
        with self.assertRaisesRegex(
            module.CharacterIdentityReviewStaleError,
            "stale character identity review signal",
        ):
            module.normalize_character_identity_review_document(
                document,
                signal_rows=rows,
            )

    def test_missing_review_observation_is_typed_review_required(self):
        module = load_module()
        document = review_document(
            module,
            1149,
            [
                {
                    "operation_id": "confirm-eric",
                    "kind": "confirm_protagonist",
                    "member_scope_keys": ["character:에릭"],
                    "target_scope_key": "character:에릭",
                    "authorized_observation_refs": ["summary:1:0"],
                    "signal_anchors": [
                        {"summary_id": 1, "source_hash": "signal-1"}
                    ],
                    "force_main_protagonist": True,
                    "anonymous_protagonist": False,
                    "reason": "reviewed protagonist",
                }
            ],
        )
        replacement_rows = [
            signal_row(2, 1, [signal_character("named:에릭", "에릭")])
        ]

        with self.assertRaises(module.CharacterIdentityReviewStaleError) as caught:
            module.normalize_character_identity_review_document(
                document,
                signal_rows=replacement_rows,
            )

        self.assertEqual(caught.exception.product_id, 1149)
        self.assertEqual(caught.exception.operation_ids, ("confirm-eric",))
        self.assertEqual(
            caught.exception.reason_codes,
            ("missing_observations",),
        )

    def test_malformed_review_remains_hard_failure(self):
        module = load_module()
        malformed = {
            "schema_version": "character_identity_review_v1",
            "product_id": 1149,
            "review_origin": "operator_cli",
            "reviewer_id": "codex.ops",
            "operations": [],
        }

        with self.assertRaises(ValueError) as caught:
            module.normalize_character_identity_review_document(malformed)

        self.assertNotIsInstance(
            caught.exception,
            module.CharacterIdentityReviewStaleError,
        )

    def test_retirement_pins_both_retired_and_replacement_scopes(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character("named:남우진", "우진"),
                    signal_character("named:우진", "우진"),
                ],
            )
        ]
        inventory_map = {
            "character:남우진": {
                "source_observation_refs": ["summary:1:0"],
                "public_chat_eligible": True,
            },
            "character:우진": {
                "source_observation_refs": ["summary:1:1"],
                "public_chat_eligible": False,
            },
        }
        request = {
            "schema_version": "character_identity_review_request_v1",
            "product_id": 1161,
            "operations": [
                {
                    "operation_id": "confirm-woojin",
                    "kind": "confirm_protagonist",
                    "scope_key": "character:남우진",
                    "reason": "reviewed protagonist",
                },
                {
                    "operation_id": "retire-duplicate-woojin",
                    "kind": "retire_active_scope",
                    "scope_key": "character:우진",
                    "replacement_scope_key": "character:남우진",
                    "reason": "duplicate protagonist scope",
                }
            ],
        }
        with patch.object(
            module,
            "fetch_active_character_inventory_map",
            return_value=inventory_map,
        ), patch.object(
            module,
            "fetch_active_summary_rows",
            return_value=rows,
        ):
            document = module.materialize_character_identity_review_document(
                object(),
                product_id=1161,
                request=request,
                reviewer_id="codex.ops",
            )
        self.assertEqual(
            document["operations"][1]["authorized_observation_refs"],
            ["summary:1:0", "summary:1:1"],
        )

    def test_exact_review_merge_does_not_authorize_future_generic_source(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        "protagonist:first_person",
                        "추종자",
                        protagonist=True,
                        first_person=True,
                    ),
                    signal_character("named:마왕성천제", "마왕성천제"),
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        "protagonist:first_person",
                        "신미아",
                        protagonist=True,
                        first_person=True,
                    )
                ],
            ),
        ]
        document = review_document(
            module,
            1105,
            [
                {
                    "operation_id": "merge-main-observations",
                    "kind": "merge_active_scopes",
                    "member_scope_keys": [
                        "character:마왕성천제",
                        "character:추종자",
                    ],
                    "target_scope_key": "character:마왕성천제",
                    "authorized_observation_refs": [
                        "summary:1:0",
                        "summary:1:1",
                    ],
                    "signal_anchors": [
                        {"summary_id": 1, "source_hash": "signal-1"}
                    ],
                    "force_main_protagonist": True,
                    "anonymous_protagonist": False,
                    "reason": "same protagonist in reviewed episode",
                }
            ],
        )
        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            character_identity_review=document,
        )
        target = next(
            row
            for row in inventory
            if row["canonical_character_key"] == "character:마왕성천제"
        )
        future = next(
            row for row in inventory if row["display_name"] == "신미아"
        )
        self.assertEqual(
            set(target["source_observation_refs"]),
            {"summary:1:0", "summary:1:1"},
        )
        self.assertNotEqual(
            future["canonical_character_key"],
            target["canonical_character_key"],
        )

    def test_anonymous_review_changes_role_but_not_public_identity(self):
        module = load_module()
        rows = [
            signal_row(
                episode_no,
                episode_no,
                [
                    signal_character(
                        "protagonist:first_person",
                        "나",
                        protagonist=True,
                        first_person=True,
                        voice_mode="monologue",
                    )
                ],
            )
            for episode_no in range(1, 4)
        ]
        document = review_document(
            module,
            1109,
            [
                {
                    "operation_id": "confirm-anonymous-main",
                    "kind": "confirm_protagonist",
                    "member_scope_keys": ["character:나"],
                    "target_scope_key": "character:나",
                    "authorized_observation_refs": ["summary:1:0"],
                    "signal_anchors": [
                        {"summary_id": 1, "source_hash": "signal-1"}
                    ],
                    "force_main_protagonist": True,
                    "anonymous_protagonist": True,
                    "reason": "unnamed first-person narrator",
                }
            ],
        )
        inventory = module.aggregate_character_inventory_v3_rows(
            rows,
            character_identity_review=document,
        )
        protagonist = next(
            row
            for row in inventory
            if row["canonical_character_key"] == "character:나"
        )
        self.assertEqual(protagonist["work_role"], "main_protagonist")
        self.assertEqual(protagonist["display_name"], "나")
        self.assertEqual(protagonist["identity_status"], "UNRESOLVED")
        self.assertFalse(protagonist["public_chat_eligible"])
        self.assertFalse(protagonist["public_slot_eligible"])

    def test_materializer_allows_exact_anonymous_scope_merge(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        "protagonist:first_person",
                        "나",
                        protagonist=True,
                        first_person=True,
                        voice_mode="monologue",
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        "protagonist:first_person",
                        "나",
                        protagonist=True,
                        first_person=True,
                        voice_mode="monologue",
                    )
                ],
            ),
        ]
        inventory_map = {
            "character:anonymous-a": {
                "source_observation_refs": ["summary:1:0"],
                "public_chat_eligible": False,
            },
            "character:anonymous-b": {
                "source_observation_refs": ["summary:2:0"],
                "public_chat_eligible": False,
            },
        }
        request = {
            "schema_version": "character_identity_review_request_v1",
            "product_id": 1109,
            "operations": [
                {
                    "operation_id": "merge-anonymous-main",
                    "kind": "merge_active_scopes",
                    "member_scope_keys": [
                        "character:anonymous-a",
                        "character:anonymous-b",
                    ],
                    "target_scope_key": "character:anonymous-a",
                    "force_main_protagonist": True,
                    "anonymous_protagonist": True,
                    "reason": "same unnamed first-person narrator",
                }
            ],
        }
        with patch.object(
            module,
            "fetch_active_character_inventory_map",
            return_value=inventory_map,
        ), patch.object(
            module,
            "fetch_active_summary_rows",
            return_value=rows,
        ):
            document = module.materialize_character_identity_review_document(
                object(),
                product_id=1109,
                request=request,
                reviewer_id="codex.ops",
            )
        operation = document["operations"][0]
        self.assertTrue(operation["force_main_protagonist"])
        self.assertTrue(operation["anonymous_protagonist"])
        self.assertEqual(
            operation["authorized_observation_refs"],
            ["summary:1:0", "summary:2:0"],
        )

    def test_reviewed_anonymous_main_demotes_old_serving_protagonist_lock(self):
        module = load_module()
        anonymous_scope_key = "character:anonymous-main"
        old_main_scope_key = "character:wrong-main"
        anonymous_row = {
            "canonical_character_key": anonymous_scope_key,
            "display_name": "나",
            "work_role": "main_protagonist",
            "public_chat_eligible": False,
            "public_slot_eligible": False,
            "chat_readiness_v1": {"character_chat_allowed": False},
            "operator_reviewed_anonymous_protagonist": True,
            "character_identity_review": {
                "force_main_protagonist": True,
                "anonymous_protagonist": True,
            },
            "superseded_protagonist_scope_keys": [old_main_scope_key],
        }
        generated_old_main = {
            "canonical_character_key": old_main_scope_key,
            "display_name": "당예린",
            "work_role": "major_character",
            "distinct_episode_count": 8,
            "public_chat_eligible": False,
            "public_slot_eligible": False,
            "chat_readiness_v1": {"character_chat_allowed": False},
        }
        old_inventory_map = {
            anonymous_scope_key: dict(anonymous_row),
            old_main_scope_key: {
                **generated_old_main,
                "work_role": "main_protagonist",
                "public_chat_eligible": True,
                "public_slot_eligible": True,
                "chat_readiness_v1": {"character_chat_allowed": True},
            },
        }
        upserted = []
        with patch.object(
            module,
            "fetch_active_character_inventory_map",
            return_value=old_inventory_map,
        ), patch.object(
            module,
            "aggregate_character_inventory_v3_rows",
            return_value=[anonymous_row, generated_old_main],
        ), patch.object(
            module,
            "reconcile_character_inventory_v3_scope_keys",
            side_effect=lambda rows, **_kwargs: rows,
        ), patch.object(
            module,
            "_refresh_character_inventory_v3_serving_fields",
        ), patch.object(
            module,
            "upsert_character_inventory_v3_item",
            side_effect=lambda _cur, *, product_id, item: upserted.append(dict(item)) or True,
        ), patch.object(
            module,
            "deactivate_missing_active_scopes",
        ):
            module.build_character_inventory_v3_summaries_from_signal_rows(
                object(),
                product_id=1109,
                signal_rows=[{"summary_text": "{}"}],
                character_identity_review={"operations": []},
            )

        by_scope = {
            row["canonical_character_key"]: row for row in upserted
        }
        self.assertEqual(
            by_scope[old_main_scope_key]["work_role"],
            "major_character",
        )
        self.assertFalse(by_scope[old_main_scope_key]["public_slot_eligible"])

    def test_review_applies_display_and_blocked_aliases_to_identity_surface(self):
        module = load_module()
        row = {
            "canonical_character_key": "character:차태흠",
            "display_name": "차태흠 정령",
            "display_name_source": "persona_names",
            "aliases": ["차태흠 정령", "차태흠", "대령"],
            "narration_names": ["차태흠 정령", "차태흠"],
            "social_call_names": ["대령"],
            "persona_names": ["차태흠 정령"],
            "real_names": ["차태흠"],
            "work_role": "major_character",
            "character_identity_review": {
                "operation_id": "confirm-cha-taeheum-surface",
                "kind": "confirm_protagonist",
                "force_main_protagonist": True,
                "canonical_display_name": "차태흠",
                "blocked_aliases": ["차태흠 정령"],
                "reason": "reviewed protagonist identity surface",
            },
        }

        module._apply_character_identity_review_rows([row])

        self.assertEqual(row["display_name"], "차태흠")
        self.assertEqual(row["display_name_source"], "operator_review")
        for field_name in (
            "aliases",
            "narration_names",
            "social_call_names",
            "persona_names",
            "real_names",
        ):
            self.assertNotIn("차태흠 정령", row[field_name])
        self.assertIn("차태흠", row["aliases"])
        self.assertEqual(row["work_role"], "main_protagonist")
        self.assertEqual(
            row["identity_surface_review_v1"]["canonical_display_name"],
            "차태흠",
        )

    def test_aggregate_preserves_reviewed_display_and_blocked_aliases(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    {
                        **signal_character(
                            "protagonist:named:차태흠",
                            "차태흠 정령",
                            aliases=["차태흠 정령", "차태흠"],
                            protagonist=True,
                        ),
                        "narration_names": ["차태흠"],
                        "persona_names": ["차태흠 정령"],
                    }
                ],
            )
        ]
        review = review_document(
            module,
            1165,
            [
                {
                    "operation_id": "confirm-cha-taeheum-surface",
                    "kind": "confirm_protagonist",
                    "member_scope_keys": ["character:차태흠"],
                    "target_scope_key": "character:차태흠",
                    "authorized_observation_refs": ["summary:1:0"],
                    "signal_anchors": [
                        {"summary_id": 1, "source_hash": "signal-1"}
                    ],
                    "force_main_protagonist": True,
                    "anonymous_protagonist": False,
                    "canonical_display_name": "차태흠",
                    "blocked_aliases": ["차태흠 정령"],
                    "reason": "reviewed protagonist identity surface",
                }
            ],
        )

        inventory_rows = module.aggregate_character_inventory_v3_rows(
            rows,
            character_identity_review=review,
        )
        target = next(
            row
            for row in inventory_rows
            if row["canonical_character_key"] == "character:차태흠"
        )

        self.assertEqual(target["display_name"], "차태흠")
        self.assertNotIn("차태흠 정령", target["aliases"])
        self.assertNotIn("차태흠 정령", target["persona_names"])
        self.assertEqual(
            target["identity_surface_review_v1"]["canonical_display_name"],
            "차태흠",
        )

    def test_reviewed_first_person_role_identity_is_publicly_resolved(self):
        module = load_module()
        rows = [
            signal_row(
                1,
                1,
                [
                    signal_character(
                        "protagonist:named:주인공",
                        "주인공",
                        aliases=["주인공"],
                        protagonist=True,
                        voice_mode="narration_only",
                    )
                ],
            ),
            signal_row(
                2,
                2,
                [
                    signal_character(
                        "protagonist:first_person",
                        "나",
                        protagonist=True,
                        first_person=True,
                        voice_mode="narration_only",
                    )
                ],
            ),
            signal_row(
                3,
                3,
                [
                    signal_character(
                        "protagonist:first_person",
                        "나",
                        protagonist=True,
                        first_person=True,
                        voice_mode="narration_only",
                    )
                ],
            ),
        ]
        review = review_document(
            module,
            1109,
            [
                {
                    "operation_id": "merge-squint-saint",
                    "kind": "merge_active_scopes",
                    "member_scope_keys": [
                        "character:4ca88c0896bf",
                        "character:generic-a",
                        "character:generic-b",
                    ],
                    "target_scope_key": "character:4ca88c0896bf",
                    "authorized_observation_refs": [
                        "summary:1:0",
                        "summary:2:0",
                        "summary:3:0",
                    ],
                    "signal_anchors": [
                        {"summary_id": 1, "source_hash": "signal-1"},
                        {"summary_id": 2, "source_hash": "signal-2"},
                        {"summary_id": 3, "source_hash": "signal-3"},
                    ],
                    "force_main_protagonist": True,
                    "anonymous_protagonist": False,
                    "canonical_display_name": "실눈 성자",
                    "blocked_aliases": ["주인공"],
                    "reason": "reviewed source-backed first-person role identity",
                }
            ],
        )

        inventory_rows = module.aggregate_character_inventory_v3_rows(
            rows,
            character_identity_review=review,
        )
        target = next(
            row
            for row in inventory_rows
            if row["canonical_character_key"] == "character:4ca88c0896bf"
        )

        self.assertEqual(target["display_name"], "실눈 성자")
        self.assertEqual(target["identity_status"], "RESOLVED_NAMED")
        self.assertNotIn(
            "unresolved_generic_first_person",
            target["identity_conflict_reasons"],
        )
        self.assertEqual(target["work_role"], "main_protagonist")
        self.assertTrue(target["public_chat_eligible"])

    def test_display_and_competing_alias_cleanup_are_character_local(self):
        module = load_module()
        rows = [
            {
                "canonical_character_key": "character:한도윤",
                "display_name": "실패한 왕",
                "display_name_source": "identity_label",
                "source_character_keys": ["named:한도윤"],
                "aliases": ["실패한 왕", "한도윤"],
                "narration_names": ["한도윤"],
                "social_call_names": [],
                "persona_names": [],
                "real_names": [],
            },
            {
                "canonical_character_key": "character:라파엘더리퍼",
                "display_name": "라파엘",
                "source_character_keys": ["named:라파엘"],
                "aliases": ["라파엘", "안드레이 카르마조프"],
                "narration_names": ["라파엘"],
                "social_call_names": [],
                "persona_names": ["안드레이 카르마조프"],
                "real_names": [],
            },
            {
                "canonical_character_key": "character:안드레이카르마조프",
                "display_name": "안드레이 카르마조프",
                "source_character_keys": ["named:안드레이카르마조프"],
                "aliases": ["안드레이 카르마조프"],
                "narration_names": [],
                "social_call_names": [],
                "persona_names": [],
                "real_names": [],
            },
            {
                "canonical_character_key": "character:레이븐:dup:a",
                "display_name": "레이븐",
                "source_character_keys": ["named:레이븐"],
                "aliases": ["레이븐"],
                "narration_names": [],
                "social_call_names": [],
                "persona_names": [],
                "real_names": [],
            },
            {
                "canonical_character_key": "character:레이븐:dup:b",
                "display_name": "레이븐",
                "source_character_keys": ["named:레이븐"],
                "aliases": ["레이븐"],
                "narration_names": [],
                "social_call_names": [],
                "persona_names": [],
                "real_names": [],
            },
        ]
        module._prefer_source_backed_canonical_display_names(rows)
        module._remove_competing_character_aliases(rows)
        self.assertEqual(rows[0]["display_name"], "한도윤")
        self.assertNotIn("안드레이 카르마조프", rows[1]["aliases"])
        self.assertNotIn("안드레이 카르마조프", rows[1]["persona_names"])
        self.assertEqual(rows[3]["aliases"], ["레이븐"])
        self.assertEqual(rows[4]["aliases"], ["레이븐"])

    def test_review_digest_is_inventory_hash_material(self):
        module = load_module()
        item = {
            "canonical_character_key": "character:에릭",
            "display_name": "에릭",
            "character_identity_review": {"review_digest": "digest-a"},
        }
        other = {
            **item,
            "character_identity_review": {"review_digest": "digest-b"},
        }
        self.assertNotEqual(
            module.build_character_inventory_v3_source_hash(item),
            module.build_character_inventory_v3_source_hash(other),
        )

    def test_reviewed_merge_retires_old_inventory_only_after_target_is_serving(self):
        module = load_module()
        target_scope_key = "character:에릭"
        retired_scope_key = "character:에릭애시퍼드"
        target = {
            "canonical_character_key": target_scope_key,
            "display_name": "에릭",
            "work_role": "main_protagonist",
            "identity_status": "RESOLVED_NAMED",
            "identity_conflict_reasons": [],
            "distinct_episode_count": 3,
            "evidence_episode_nos": [1, 2, 3],
            "rp_signal_quality": {
                "status": "summary_ready",
                "needs_review": False,
            },
            "voice_mode_counts": {"dialogue": 3, "monologue": 0},
            "public_chat_eligible": True,
            "public_slot_eligible": True,
            "chat_readiness_v1": {"character_chat_allowed": True},
        }
        retired = {
            "canonical_character_key": retired_scope_key,
            "display_name": "에릭 애시퍼드",
            "work_role": "major_character",
            "public_chat_eligible": True,
            "public_slot_eligible": True,
            "chat_readiness_v1": {
                "character_chat_allowed": True,
                "public_slot_allowed": True,
            },
        }
        document = {
            "operations": [
                {
                    "operation_id": "merge-eric",
                    "kind": "merge_active_scopes",
                    "member_scope_keys": [target_scope_key, retired_scope_key],
                    "target_scope_key": target_scope_key,
                    "reason": "same protagonist",
                }
            ]
        }
        upserted = []
        cur = object()
        with patch.object(
            module,
            "fetch_active_character_inventory_map",
            return_value={target_scope_key: target, retired_scope_key: retired},
        ), patch.object(
            module,
            "aggregate_character_inventory_v3_rows",
            return_value=[dict(target)],
        ), patch.object(
            module,
            "reconcile_character_inventory_v3_scope_keys",
            side_effect=lambda rows, **_kwargs: rows,
        ), patch.object(
            module,
            "upsert_character_inventory_v3_item",
            side_effect=lambda _cur, *, product_id, item: upserted.append(dict(item)) or True,
        ), patch.object(
            module,
            "deactivate_missing_active_scopes",
        ) as deactivate:
            module.build_character_inventory_v3_summaries_from_signal_rows(
                cur,
                product_id=1149,
                signal_rows=[{"summary_text": "{}"}],
                character_identity_review=document,
            )
        by_scope = {
            row["canonical_character_key"]: row for row in upserted
        }
        self.assertTrue(by_scope[target_scope_key]["public_chat_eligible"])
        self.assertFalse(by_scope[retired_scope_key]["public_chat_eligible"])
        self.assertFalse(by_scope[retired_scope_key]["public_slot_eligible"])
        self.assertEqual(
            by_scope[retired_scope_key]["identity_retirement_v1"][
                "replacement_scope_key"
            ],
            target_scope_key,
        )
        deactivate.assert_called_once_with(
            cur,
            1149,
            "character_inventory_v3",
            {target_scope_key, retired_scope_key},
        )

    def test_display_cleanup_runs_after_durable_scope_reconciliation(self):
        module = load_module()
        old_row = {
            "canonical_character_key": "character:한도윤",
            "display_name": "한도윤",
            "display_name_source": "identity_label",
            "source_character_keys": ["named:한도윤"],
            "aliases": ["한도윤"],
            "work_role": "main_protagonist",
            "identity_status": "RESOLVED_NAMED",
            "identity_conflict_reasons": [],
            "distinct_episode_count": 3,
            "evidence_episode_nos": [1, 2, 3],
            "rp_signal_quality": {
                "status": "summary_ready",
                "needs_review": False,
            },
            "voice_mode_counts": {"dialogue": 3, "monologue": 0},
            "public_chat_eligible": True,
            "public_slot_eligible": True,
            "chat_readiness_v1": {"character_chat_allowed": True},
        }
        generated_row = {
            **old_row,
            "canonical_character_key": "character:실패한왕",
            "display_name": "실패한 왕",
            "aliases": ["실패한 왕", "한도윤"],
        }
        upserted = []
        with patch.object(
            module,
            "fetch_active_character_inventory_map",
            return_value={"character:한도윤": old_row},
        ), patch.object(
            module,
            "aggregate_character_inventory_v3_rows",
            return_value=[generated_row],
        ), patch.object(
            module,
            "upsert_character_inventory_v3_item",
            side_effect=lambda _cur, *, product_id, item: upserted.append(dict(item)) or True,
        ), patch.object(module, "deactivate_missing_active_scopes"):
            module.build_character_inventory_v3_summaries_from_signal_rows(
                object(),
                product_id=1148,
                signal_rows=[{"summary_text": "{}"}],
            )
        self.assertEqual(len(upserted), 1)
        self.assertEqual(
            upserted[0]["canonical_character_key"], "character:한도윤"
        )
        self.assertEqual(upserted[0]["display_name"], "한도윤")
        self.assertEqual(
            upserted[0]["display_name_source"], "canonical_named_source"
        )

    def test_operator_cli_rolls_back_apply_failure(self):
        story_agent = load_module()
        cli = load_cli(story_agent)

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

        fake_connection = FakeConnection()

        @contextmanager
        def fake_lock(_product_id):
            yield object()

        @contextmanager
        def fake_cursor(_conn):
            yield object()

        document = {
            "review_digest": "digest",
            "operations": [
                {
                    "operation_id": "confirm-eric",
                    "kind": "confirm_protagonist",
                    "target_scope_key": "character:에릭",
                    "member_scope_keys": ["character:에릭"],
                    "force_main_protagonist": True,
                }
            ],
        }
        preview = [
            {
                "canonical_character_key": "character:에릭",
                "work_role": "main_protagonist",
                "character_identity_review": document["operations"][0],
            }
        ]
        with patch.object(
            story_agent,
            "product_lock_connection",
            side_effect=fake_lock,
        ), patch.object(
            story_agent,
            "db_connect",
            return_value=fake_connection,
        ), patch.object(
            story_agent,
            "work_cursor",
            side_effect=fake_cursor,
        ), patch.object(
            story_agent,
            "materialize_character_identity_review_document",
            return_value=document,
        ), patch.object(
            story_agent,
            "fetch_active_summary_rows",
            return_value=[],
        ), patch.object(
            cli,
            "_build_preview_rows",
            return_value=preview,
        ), patch.object(
            story_agent,
            "upsert_character_identity_review",
            side_effect=RuntimeError("write failed"),
        ), self.assertRaisesRegex(RuntimeError, "write failed"):
            cli.run_identity_review(
                product_id=1149,
                request={},
                reviewer_id="codex.ops",
                apply=True,
            )
        self.assertEqual(fake_connection.commit_count, 0)
        self.assertEqual(fake_connection.rollback_count, 1)
        self.assertEqual(fake_connection.close_count, 1)


class CharacterIdentityReviewAsyncTest(IsolatedAsyncioTestCase):
    async def test_reviewed_main_skips_paid_protagonist_resolver(self):
        module = load_module()
        rows = [signal_row(1, 1, [signal_character("named:에릭", "에릭")])]
        document = review_document(
            module,
            1149,
            [
                {
                    "operation_id": "confirm-eric",
                    "kind": "confirm_protagonist",
                    "member_scope_keys": ["character:에릭"],
                    "target_scope_key": "character:에릭",
                    "authorized_observation_refs": ["summary:1:0"],
                    "signal_anchors": [
                        {"summary_id": 1, "source_hash": "signal-1"}
                    ],
                    "force_main_protagonist": True,
                    "anonymous_protagonist": False,
                    "reason": "reviewed protagonist",
                }
            ],
        )
        with patch.object(
            module,
            "fetch_active_summary_rows",
            return_value=rows,
        ), patch.object(
            module,
            "fetch_character_identity_review",
            return_value=document,
        ), patch.object(
            module,
            "build_work_protagonist_resolution_for_inventory_v3",
            AsyncMock(),
        ) as resolver, patch.object(
            module,
            "build_character_inventory_v3_summaries_from_signal_rows",
            return_value=(1, 0),
        ) as builder:
            result = await module.build_character_inventory_v3_summaries_resolved(
                object(),
                product_id=1149,
                summary_client=object(),
            )
        self.assertEqual(result, (1, 0))
        resolver.assert_not_awaited()
        self.assertEqual(
            builder.call_args.kwargs["character_identity_review"],
            document,
        )
