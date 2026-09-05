import sqlite3
import copy
import unittest
from types import SimpleNamespace

from test_story_agent_context_cost_guard import load_module, signal_row, signal_character


class ScheduledCollectionScopeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_scheduled_query_caps_public_ordinal_but_manual_query_does_not(self):
        args = SimpleNamespace(product_ids=[1], episode_ids=None, episode_nos=None, limit=0, scheduled=True)
        query, _ = self.module.build_target_query(args, False)
        self.assertIn("asset_rank.public_episode_rank <= 30", query.split("WHERE")[-1])
        args.scheduled = False
        query, _ = self.module.build_target_query(args, False)
        self.assertNotIn("asset_rank.public_episode_rank <= 30", query.split("WHERE")[-1])

    def test_actual_collector_sql_uses_public_ordinal_not_episode_number(self):
        with sqlite3.connect(":memory:") as db:
            db.executescript("""
                CREATE TABLE tb_product(product_id,title,price_type,status_code,open_yn,blind_yn,ai_content_service_enabled_yn);
                CREATE TABLE tb_product_episode(product_id,episode_id,episode_no,episode_title,episode_content,episode_text_count,epub_file_id,use_yn,open_yn,open_changed_date,publish_reserve_date,created_date);
                CREATE TABLE tb_story_agent_context_product(product_id,context_status);
                INSERT INTO tb_product VALUES(1,'test','free','ongoing','Y','N','Y');
            """)
            for rank in range(1, 32):
                db.execute("INSERT INTO tb_product_episode VALUES(1,?,?, 'title','body',4,NULL,'Y','Y','2026-09-01',NULL,'2026-09-01')", (rank, rank * 2))
            args = SimpleNamespace(product_ids=[1], episode_ids=None, episode_nos=None, limit=0, scheduled=True)
            query, params = self.module.build_target_query(args, False)
            rows = db.execute(query.replace("%s", "?"), params).fetchall()
            self.assertEqual(len(rows), 30)
            self.assertEqual(rows[-1][3], 60)
            args.scheduled = False
            query, params = self.module.build_target_query(args, False)
            self.assertEqual(len(db.execute(query.replace("%s", "?"), params).fetchall()), 31)

    def test_scheduled_targets_reuse_generator_top_two_after_signal_scope_filter(self):
        names = ["강현", "이준", "김민", "박서윤"]
        inventory = {
            f"character:{name}": {
                "canonical_character_key": f"character:{name}",
                "display_name": name, "aliases": [name],
                "source_character_keys": [f"named:{name}"],
                "is_protagonist": i == 0,
                "distinct_episode_count": 100 - i,
                "voice_evidence_count": 10,
            }
            for i, name in enumerate(names)
        }
        signals = [signal_row(1, 1, [signal_character(character_key=f"named:{name}", display_name=name) for name in names[:3]])]
        selected = self.module.build_scheduled_character_asset_scope_keys(inventory_map=inventory, signal_rows=signals)
        self.assertEqual(selected, {"character:강현", "character:이준"})
        self.assertNotIn("character:박서윤", selected)

    def test_policy_keeps_selected_invalid_payload_actionable_and_residual_observable(self):
        names = ["강현", "이준", "김민"]
        inventory = {
            f"character:{name}": {
                "canonical_character_key": f"character:{name}", "display_name": name,
                "aliases": [name], "source_character_keys": [f"named:{name}"],
                "is_protagonist": i == 0, "distinct_episode_count": 100 - i,
                "voice_evidence_count": 10,
            } for i, name in enumerate(names)
        }
        signals = [signal_row(1, 1, [signal_character(character_key=f"named:{name}", display_name=name) for name in names])]
        readiness = {
            "public_candidate_count": 3, "main_protagonist_scope_keys": ["character:강현"],
            "invalid_profile_scope_keys": ["character:이준"],
            "invalid_examples_scope_keys": ["character:이준"],
            "legacy_profile_scope_key_mismatch_scope_keys": ["character:김민"],
            "missing_usable_scene_scope_keys": ["character:이준", "character:김민"],
        }
        before = copy.deepcopy((inventory, signals, readiness))
        policy = self.module.build_scheduled_character_asset_policy(inventory_map=inventory, signal_rows=signals, readiness=readiness)
        self.assertEqual(policy["rp_scope_keys"], ["character:이준"])
        self.assertEqual(policy["scene_scope_keys"], ["character:이준"])
        self.assertEqual(policy["residual_rp_scope_keys"], ["character:김민"])
        self.assertEqual(policy["residual_scene_scope_keys"], ["character:김민"])
        self.assertTrue(policy["repairable"])
        self.assertEqual((inventory, signals, readiness), before)
        readiness["invalid_profile_scope_keys"] = []
        readiness["invalid_examples_scope_keys"] = []
        readiness["missing_usable_scene_scope_keys"] = ["character:김민"]
        policy = self.module.build_scheduled_character_asset_policy(inventory_map=inventory, signal_rows=signals, readiness=readiness)
        self.assertFalse(policy["repairable"])
        self.assertEqual(policy["residual_rp_scope_keys"], ["character:김민"])

    def test_empty_selection_does_not_hide_identity_or_main_failures(self):
        for readiness, blocker in (
            ({"public_candidate_count": 1}, "missing_main_protagonist"),
            ({"main_protagonist_scope_keys": ["character:강현"]}, "main_protagonist_not_selected"),
            ({"malformed_inventory_scope_keys": ["bad"]}, "malformed_inventory"),
            ({"blocking_continuity_ambiguous_scope_keys": ["character:강현"]}, "character:강현"),
        ):
            with self.subTest(blocker=blocker):
                policy = self.module.build_scheduled_character_asset_policy(inventory_map={}, signal_rows=[], readiness=readiness)
                self.assertIn(blocker, policy["blockers"])
                self.assertFalse(policy["repairable"])


if __name__ == "__main__":
    unittest.main()
