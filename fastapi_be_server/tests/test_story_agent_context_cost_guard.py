import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest import TestCase
from unittest.mock import ANY, AsyncMock, patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_story_agent_context.py"


def load_module():
    module_name = "build_story_agent_context_under_test"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class FakeConnection:
    def __init__(self):
        self.commit_count = 0

    def commit(self):
        self.commit_count += 1


@contextmanager
def fake_work_cursor(_conn):
    yield object()


class StoryAgentContextCostGuardTest(IsolatedAsyncioTestCase):
    async def test_existing_episode_character_signal_reuses_without_llm_call(self):
        module = load_module()
        conn = FakeConnection()
        row = {
            "summary_id": 777,
            "scope_key": "episode:1001",
            "episode_from": 1,
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


class StoryAgentContextDeltaValidationTest(TestCase):
    def test_delta_rp_refresh_is_opt_in_cli_flag(self):
        module = load_module()

        with patch.object(sys, "argv", ["build_story_agent_context.py", "--build-mode", "delta", "--product-id", "687"]):
            args = module.parse_args()
        self.assertFalse(args.refresh_rp)
        self.assertFalse(module.should_refresh_delta_rp(args))

        with patch.object(
            sys,
            "argv",
            ["build_story_agent_context.py", "--build-mode", "delta", "--product-id", "687", "--refresh-rp"],
        ):
            args = module.parse_args()
        self.assertTrue(args.refresh_rp)
        self.assertTrue(module.should_refresh_delta_rp(args))

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

    def test_delta_candidate_filter_limits_rows_per_product_by_episode_no(self):
        module = load_module()
        rows = [
            {"product_id": 687, "episode_id": 103, "episode_no": 3},
            {"product_id": 687, "episode_id": 101, "episode_no": 1},
            {"product_id": 687, "episode_id": 102, "episode_no": 2},
            {"product_id": 687, "episode_id": 104, "episode_no": 4},
        ]

        with patch.object(module, "build_open_add_episode_id_set", return_value={101, 102, 103, 104}), \
             patch.object(module, "build_sync_repair_episode_id_set", return_value=set()):
            filtered = module.filter_delta_candidate_rows(object(), rows, max_delta_episodes=2)

        self.assertEqual([row["episode_no"] for row in filtered], [1, 2])
        self.assertEqual([row["_delta_reason"] for row in filtered], ["open_add", "open_add"])

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
