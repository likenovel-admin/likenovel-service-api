import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
MODULE_PATH = SCRIPT_DIR / "audit_character_chat_asset_readiness_db.py"
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def load_module():
    module_name = "audit_character_chat_asset_readiness_db_under_test"
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class CharacterChatAssetReadinessDbAuditTest(unittest.TestCase):
    def test_dev_deploy_package_includes_character_chat_asset_audit(self):
        workflow = (
            BACKEND_ROOT / ".github" / "workflows" / "deploy_be_actions_dev.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "cp ../scripts/audit_character_chat_asset_readiness_db.py "
            "./scripts/audit_character_chat_asset_readiness_db.py",
            workflow,
        )

    def test_prod_deploy_package_includes_character_chat_asset_audit(self):
        workflow = (
            BACKEND_ROOT / ".github" / "workflows" / "deploy_be_actions.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "cp ../scripts/audit_character_chat_asset_readiness_db.py "
            "./scripts/audit_character_chat_asset_readiness_db.py",
            workflow,
        )

    def test_dev_and_prod_packages_include_identity_review_cli(self):
        expected_copy = (
            "cp ../scripts/apply_story_agent_identity_review.py "
            "./scripts/apply_story_agent_identity_review.py"
        )
        for workflow_name in (
            "deploy_be_actions_dev.yml",
            "deploy_be_actions.yml",
        ):
            workflow = (
                BACKEND_ROOT / ".github" / "workflows" / workflow_name
            ).read_text(encoding="utf-8")
            self.assertIn(expected_copy, workflow)

    def test_build_product_query_defaults_to_open_ongoing_public_scope(self):
        module = load_module()

        query, params = module.build_product_query(product_ids=[100, 200], limit=10, open_only=True)

        self.assertIn("p.price_type IN ('free', 'paid')", query)
        self.assertIn("p.status_code = 'ongoing'", query)
        self.assertIn("p.open_yn = 'Y'", query)
        self.assertIn("COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'", query)
        self.assertIn("AS characterChatEligible", query)
        self.assertIn("COUNT(*) >= 15", query)
        self.assertIn(">= '2026-03-01 00:00:00'", query)
        self.assertIn("p.product_id IN (%s, %s)", query)
        self.assertIn("LIMIT %s", query)
        self.assertEqual(params, [100, 200, 10])

    def test_build_product_query_can_include_closed_scope_for_shadow_cases(self):
        module = load_module()

        query, params = module.build_product_query(product_ids=[], limit=0, open_only=False)
        outer_where = query.rsplit("WHERE", 1)[-1]

        self.assertNotIn("p.price_type IN", query)
        self.assertNotIn("p.status_code = 'ongoing'", outer_where)
        self.assertNotIn("p.ai_content_service_enabled_yn", query)
        self.assertNotIn("LIMIT %s", query)
        self.assertEqual(params, [])

    def test_summarize_verifications_counts_ready_hold_and_reasons(self):
        module = load_module()
        rows = [
            {
                "product_id": 1,
                "characterChatEligible": 1,
                "context_status": "ready",
                "character_chat_asset_readiness": {
                    "character_chat_status": "ready",
                    "public_candidate_count": 2,
                    "ready_public_candidate_count": 1,
                    "public_slot_ready_count": 1,
                    "block_reason_counts": {},
                },
            },
            {
                "product_id": 2,
                "characterChatEligible": 1,
                "context_status": "ready",
                "character_chat_asset_readiness": {
                    "character_chat_status": "hold",
                    "public_candidate_count": 1,
                    "ready_public_candidate_count": 0,
                    "public_slot_ready_count": 0,
                    "block_reason_counts": {
                        "missing_usable_scene": 1,
                    },
                },
            },
            {
                "product_id": 3,
                "characterChatEligible": 1,
                "context_status": "",
                "character_chat_asset_readiness": {
                    "character_chat_status": "none_eligible",
                    "public_candidate_count": 0,
                },
            },
        ]

        summary = module.summarize_verifications(rows)

        self.assertEqual(summary["productCount"], 3)
        self.assertEqual(summary["contextStatusCounts"], {"missing": 1, "ready": 2})
        self.assertEqual(
            summary["characterChatStatusCounts"],
            {"hold": 1, "none_eligible": 1, "ready": 1},
        )
        self.assertEqual(
            summary["blockReasonCounts"],
            {"missing_usable_scene": 1},
        )
        self.assertEqual(
            summary["actionPlanCounts"],
            {
                "generate_episode_scene_extraction": 1,
                "ready": 1,
                "build_story_context_foundation": 1,
            },
        )
        self.assertEqual(rows[0]["assetActionPlan"], ["ready"])
        self.assertEqual(
            rows[1]["assetActionPlan"],
            ["generate_episode_scene_extraction"],
        )
        self.assertEqual(rows[2]["assetActionPlan"], ["build_story_context_foundation"])
        self.assertEqual(
            summary["candidateProductIdsByAction"],
            {
                "build_story_context_foundation": [3],
                "generate_episode_scene_extraction": [2],
                "ready": [1],
            },
        )
        self.assertEqual(summary["publicCandidateTotal"], 3)
        self.assertEqual(summary["readyPublicCandidateTotal"], 1)
        self.assertEqual(summary["publicSlotReadyTotal"], 1)
        self.assertEqual(summary["readyProductIds"], [1])
        self.assertEqual(summary["readyWithoutMainProtagonistCount"], 1)
        self.assertEqual(summary["readyWithoutMainProtagonistProductIds"], [1])
        self.assertEqual(summary["holdProductIdsSample"], [2])

    def test_out_of_cohort_hold_is_observed_without_actionable_alert(self):
        module = load_module()
        rows = [
            {
                "product_id": 787,
                "characterChatEligible": 0,
                "context_status": "ready",
                "character_chat_asset_readiness": {
                    "character_chat_status": "hold",
                    "public_candidate_count": 1,
                    "ready_public_candidate_count": 0,
                    "public_slot_ready_count": 0,
                    "block_reason_counts": {"missing_usable_scene": 1},
                },
            }
        ]

        summary = module.summarize_verifications(rows)

        self.assertEqual(summary["outOfCohortHoldCount"], 1)
        self.assertEqual(summary["outOfCohortHoldProductIds"], [787])
        self.assertEqual(summary["actionPlanCounts"], {})
        self.assertEqual(rows[0]["assetActionPlan"], ["out_of_cohort_hold"])
        self.assertEqual(
            module.build_audit_exit_code(summary, fail_on_actionable=True),
            0,
        )

    def test_load_env_file_reads_key_values_without_printing_or_sourcing(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "BATCH_DB_HOST='127.0.0.1'",
                        "BAD-NAME=skip",
                        "not a shell command",
                    ]
                ),
                encoding="utf-8",
            )
            old_value = os.environ.pop("BATCH_DB_HOST", None)
            try:
                loaded = module.load_env_file(env_path)
                value = os.environ.get("BATCH_DB_HOST")
            finally:
                os.environ.pop("BATCH_DB_HOST", None)
                if old_value is not None:
                    os.environ["BATCH_DB_HOST"] = old_value

        self.assertEqual(loaded, ["BATCH_DB_HOST"])
        self.assertEqual(value, "127.0.0.1")
        self.assertNotIn("BAD-NAME", os.environ)

    def test_build_asset_action_plan_ignores_legacy_prompt_and_opening_reasons(self):
        module = load_module()

        actions = module.build_asset_action_plan(
            {
                "product_id": 2004,
                "context_status": "ready",
                "character_chat_asset_readiness": {
                    "character_chat_status": "hold",
                    "block_reason_counts": {
                        "legacy_profile_scope_key_mismatch": 2,
                        "legacy_examples_scope_key_mismatch": 2,
                        "missing_internal_prompt": 2,
                        "missing_character_chat_opening": 2,
                    },
                },
            }
        )

        self.assertEqual(
            actions,
            ["rebuild_rp_assets_with_v3_scope"],
        )

    def test_ready_candidate_does_not_hide_legacy_scope_mismatch(self):
        module = load_module()

        actions = module.build_asset_action_plan(
            {
                "product_id": 1103,
                "context_status": "ready",
                "character_chat_asset_readiness": {
                    "character_chat_status": "ready",
                    "ready_public_candidate_count": 1,
                    "legacy_profile_scope_key_mismatch_scope_keys": [
                        "character:레이븐:dup:new"
                    ],
                    "block_reason_counts": {
                        "legacy_profile_scope_key_mismatch": 1,
                    },
                },
            }
        )

        self.assertEqual(actions, ["rebuild_rp_assets_with_v3_scope"])

    def test_ready_co_main_observed_ambiguity_is_not_actionable(self):
        module = load_module()

        actions = module.build_asset_action_plan(
            {
                "product_id": 1127,
                "context_status": "ready",
                "character_chat_asset_readiness": {
                    "character_chat_status": "ready",
                    "ready_main_protagonist_scope_keys": ["character:득구"],
                    "continuity_ambiguous_scope_keys": ["character:설총"],
                    "blocking_continuity_ambiguous_scope_keys": [],
                    "block_reason_counts": {
                        "identity_continuity_ambiguous": 1,
                    },
                },
            }
        )

        self.assertEqual(actions, ["ready"])

    def test_actionable_summary_is_nonzero_only_when_fail_flag_is_enabled(self):
        module = load_module()
        summary = {
            "actionPlanCounts": {
                "ready": 10,
                "no_public_character_candidate": 2,
                "rebuild_rp_assets_with_v3_scope": 1,
            }
        }

        self.assertEqual(
            module.build_audit_exit_code(summary, fail_on_actionable=False),
            0,
        )
        self.assertEqual(
            module.build_audit_exit_code(summary, fail_on_actionable=True),
            1,
        )


if __name__ == "__main__":
    unittest.main()
