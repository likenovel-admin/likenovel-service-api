import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_story_agent_context.py"


def load_module():
    module_name = "build_story_agent_character_chat_readiness_under_test"
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


def row(summary_type, scope_key, payload, *, episode_from=None, summary_id=1):
    return {
        "summary_id": summary_id,
        "summary_type": summary_type,
        "scope_key": scope_key,
        "episode_from": episode_from,
        "episode_to": episode_from,
        "source_hash": f"hash:{summary_type}:{scope_key}",
        "summary_text": json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else str(payload),
    }


def inventory_payload(scope_key="protagonist:named:데시", *, public_chat=True, public_slot=True):
    return {
        "canonical_character_key": scope_key,
        "display_name": "데시",
        "public_chat_eligible": public_chat,
        "public_slot_eligible": public_slot,
        "chat_readiness_v1": {
            "exposure_decision": "eligible" if public_chat else "hold",
            "character_chat_allowed": public_chat,
            "public_slot_allowed": public_slot,
        },
    }


def scene_payload(scope_key="protagonist:named:데시"):
    return {
        "episode_no": 3,
        "status": "ok",
        "scene_count": 1,
        "scenes": [
            {
                "scene_index": 1,
                "scene_gist": "데시가 복도 끝 소리를 확인한다.",
                "current_action": "문 앞의 흔적을 살핀다.",
                "immediate_pressure": "발소리가 가까워진다.",
                "character_initiative_reason": "소리를 줄이고 다음 이동을 정해야 한다.",
                "user_entry_role": "임시 동행자",
                "user_hook": "문틈 아래 흔적을 확인할지 고르게 한다.",
                "participants": [{"mention_label": "데시", "scope_key": scope_key}],
                "action_ownership": [{"actor_scope_key": scope_key, "action": "흔적을 확인한다"}],
            }
        ],
    }


def opening_payload(scope_key="protagonist:named:데시"):
    return {
        "schema_version": "character_chat_opening_v1",
        "readiness": {"status": "ready", "confidence": 0.9, "block_reasons": []},
        "chat_target": {"display_name": "데시", "scope_key": scope_key},
        "opening_scene": {"situation": "데시가 복도 끝 소리를 확인한다."},
        "opening_message": {
            "narration": "복도 끝의 낡은 등이 한 번 깜박이고, 데시는 문고리 위에 얹은 손을 멈춘다. 먼지 낀 바닥에는 방금 생긴 듯한 긁힌 자국이 안쪽으로 이어지고, 문틈 아래로는 차갑게 식은 공기가 가늘게 밀려 나온다. 데시는 먼저 등불의 각도를 낮추고, 손잡이 근처에 묻은 검은 가루를 눈으로만 확인한다. 가까워지던 발소리는 문 하나를 사이에 둔 듯 갑자기 멎고, 안쪽에서는 금속이 벽을 긁는 듯한 소리가 짧게 되풀이된다. 지금 흔적을 확인하지 않으면 다음 방의 움직임을 놓치고, 바로 열면 안쪽의 누군가가 먼저 반응할 수 있다.",
            "dialogue": "\"발소리가 가까워지고 있어. 저 흔적이 안쪽으로 이어지는지 먼저 확인해야 해.\"",
            "opening_text": "복도 끝의 낡은 등이 한 번 깜박이고, 데시는 문고리 위에 얹은 손을 멈춘다. 먼지 낀 바닥에는 방금 생긴 듯한 긁힌 자국이 안쪽으로 이어지고, 문틈 아래로는 차갑게 식은 공기가 가늘게 밀려 나온다. 데시는 먼저 등불의 각도를 낮추고, 손잡이 근처에 묻은 검은 가루를 눈으로만 확인한다. 가까워지던 발소리는 문 하나를 사이에 둔 듯 갑자기 멎고, 안쪽에서는 금속이 벽을 긁는 듯한 소리가 짧게 되풀이된다. 지금 흔적을 확인하지 않으면 다음 방의 움직임을 놓치고, 바로 열면 안쪽의 누군가가 먼저 반응할 수 있다.\n\n\"발소리가 가까워지고 있어. 저 흔적이 안쪽으로 이어지는지 먼저 확인해야 해.\"",
            "user_objective": "문틈 아래 흔적을 확인할지, 발소리의 방향을 먼저 들을지 고른다.",
        },
        "user_role": {"role_type": "임시 조력자"},
        "character_drive": {"immediate_objective": "소리를 피해 다음 이동을 정한다."},
        "agency_contract": {
            "character_moves_first": True,
            "non_user_dependent_action": "데시가 먼저 문고리와 바닥 흔적을 확인한다.",
        },
        "progression_engine": {"scene_exit_condition": "흔적을 확인하고 다음 방으로 이동한다."},
        "progression": {"next_beats": [{"beat": "문틈 확인"}, {"beat": "발소리 접근"}]},
    }


class StoryAgentCharacterChatReadinessTest(unittest.TestCase):
    def test_story_context_ready_does_not_make_character_chat_ready_without_assets(self):
        module = load_module()

        verification = module.build_character_chat_asset_readiness_verification(
            product_id=100,
            story_context_status="ready",
            total_episode_count=3,
            summary_rows_by_type={
                "episode_summary": [row("episode_summary", "episode:1", "1화")],
                "episode_character_signals": [row("episode_character_signals", "episode:1", {})],
                "character_inventory_v3": [
                    row("character_inventory_v3", "protagonist:named:데시", inventory_payload())
                ],
            },
        )

        self.assertEqual(verification["character_chat_status"], "hold")
        self.assertEqual(verification["story_context_status"], "ready")
        self.assertEqual(verification["public_candidate_count"], 1)
        self.assertEqual(verification["ready_public_candidate_count"], 0)
        self.assertEqual(verification["missing_profile_scope_keys"], ["protagonist:named:데시"])
        self.assertEqual(verification["missing_examples_scope_keys"], ["protagonist:named:데시"])
        self.assertEqual(verification["missing_internal_prompt_scope_keys"], ["protagonist:named:데시"])
        self.assertEqual(verification["missing_opening_scope_keys"], ["protagonist:named:데시"])
        self.assertEqual(verification["missing_usable_scene_scope_keys"], ["protagonist:named:데시"])
        self.assertEqual(verification["block_reason_counts"]["missing_profile"], 1)
        self.assertEqual(verification["block_reason_counts"]["missing_character_chat_opening"], 1)
        self.assertEqual(verification["block_reason_counts"]["missing_usable_scene"], 1)

    def test_character_chat_holds_without_opening_asset_even_if_other_assets_exist(self):
        module = load_module()
        scope_key = "protagonist:named:데시"

        verification = module.build_character_chat_asset_readiness_verification(
            product_id=101,
            story_context_status="ready",
            total_episode_count=3,
            summary_rows_by_type={
                "character_inventory_v3": [row("character_inventory_v3", scope_key, inventory_payload(scope_key))],
                "character_rp_profile": [row("character_rp_profile", scope_key, {"display_name": "데시"})],
                "character_rp_examples": [row("character_rp_examples", scope_key, {"examples": [{"text": "움직여."}]})],
                "character_chat_internal_prompt": [
                    row("character_chat_internal_prompt", scope_key, {"internal_prompt": "[핵심] 데시는 먼저 움직인다."})
                ],
                "episode_scene_extraction": [row("episode_scene_extraction", "episode:3", scene_payload(scope_key), episode_from=3)],
            },
        )

        self.assertEqual(verification["character_chat_status"], "hold")
        self.assertEqual(verification["ready_public_candidate_count"], 0)
        self.assertEqual(verification["missing_opening_scope_keys"], [scope_key])
        self.assertEqual(verification["block_reason_counts"]["missing_character_chat_opening"], 1)

    def test_character_chat_holds_when_opening_asset_scope_mismatches(self):
        module = load_module()
        scope_key = "protagonist:named:데시"
        invalid_opening = opening_payload("protagonist:named:다른인물")

        verification = module.build_character_chat_asset_readiness_verification(
            product_id=106,
            story_context_status="ready",
            total_episode_count=3,
            summary_rows_by_type={
                "character_inventory_v3": [row("character_inventory_v3", scope_key, inventory_payload(scope_key))],
                "character_rp_profile": [row("character_rp_profile", scope_key, {"display_name": "데시"})],
                "character_rp_examples": [row("character_rp_examples", scope_key, {"examples": [{"text": "움직여."}]})],
                "character_chat_internal_prompt": [
                    row("character_chat_internal_prompt", scope_key, {"internal_prompt": "[핵심] 데시는 먼저 움직인다."})
                ],
                "character_chat_opening_v1": [row("character_chat_opening_v1", scope_key, invalid_opening)],
                "episode_scene_extraction": [row("episode_scene_extraction", "episode:3", scene_payload(scope_key), episode_from=3)],
            },
        )

        self.assertEqual(verification["character_chat_status"], "hold")
        self.assertEqual(verification["ready_public_candidate_count"], 0)
        self.assertEqual(verification["invalid_opening_scope_keys"], [scope_key])
        self.assertEqual(verification["block_reason_counts"]["invalid_character_chat_opening"], 1)

    def test_legacy_rp_scope_key_mismatch_is_reported_without_becoming_ready(self):
        module = load_module()
        scope_key = "character:데시"
        legacy_scope_key = "protagonist:named:데시"
        payload = inventory_payload(scope_key)
        payload["source_character_keys"] = [legacy_scope_key]

        verification = module.build_character_chat_asset_readiness_verification(
            product_id=105,
            story_context_status="ready",
            total_episode_count=3,
            summary_rows_by_type={
                "character_inventory_v3": [row("character_inventory_v3", scope_key, payload)],
                "character_rp_profile": [row("character_rp_profile", legacy_scope_key, {"display_name": "데시"})],
                "character_rp_examples": [
                    row("character_rp_examples", legacy_scope_key, {"examples": [{"text": "움직여."}]})
                ],
                "character_chat_internal_prompt": [
                    row("character_chat_internal_prompt", scope_key, {"internal_prompt": "[핵심] 데시는 먼저 움직인다."})
                ],
                "character_chat_opening_v1": [row("character_chat_opening_v1", scope_key, opening_payload(scope_key))],
                "episode_scene_extraction": [row("episode_scene_extraction", "episode:3", scene_payload(scope_key), episode_from=3)],
            },
        )

        self.assertEqual(verification["character_chat_status"], "hold")
        self.assertEqual(verification["ready_public_candidate_count"], 0)
        self.assertEqual(verification["missing_profile_scope_keys"], [scope_key])
        self.assertEqual(verification["missing_examples_scope_keys"], [scope_key])
        self.assertEqual(verification["legacy_profile_scope_key_mismatch_scope_keys"], [scope_key])
        self.assertEqual(verification["legacy_examples_scope_key_mismatch_scope_keys"], [scope_key])
        self.assertEqual(verification["block_reason_counts"]["legacy_profile_scope_key_mismatch"], 1)
        self.assertEqual(verification["block_reason_counts"]["legacy_examples_scope_key_mismatch"], 1)
        self.assertNotIn("missing_profile", verification["block_reason_counts"])
        self.assertNotIn("missing_examples", verification["block_reason_counts"])

    def test_character_chat_ready_requires_exact_scope_profile_examples_prompt_scene_and_opening(self):
        module = load_module()
        scope_key = "protagonist:named:데시"

        verification = module.build_character_chat_asset_readiness_verification(
            product_id=104,
            story_context_status="ready",
            total_episode_count=3,
            summary_rows_by_type={
                "character_inventory_v3": [row("character_inventory_v3", scope_key, inventory_payload(scope_key))],
                "character_rp_profile": [row("character_rp_profile", scope_key, {"display_name": "데시"})],
                "character_rp_examples": [row("character_rp_examples", scope_key, {"examples": [{"text": "움직여."}]})],
                "character_chat_internal_prompt": [
                    row("character_chat_internal_prompt", scope_key, {"internal_prompt": "[핵심] 데시는 먼저 움직인다."})
                ],
                "character_chat_opening_v1": [row("character_chat_opening_v1", scope_key, opening_payload(scope_key))],
                "episode_scene_extraction": [row("episode_scene_extraction", "episode:3", scene_payload(scope_key), episode_from=3)],
            },
        )

        self.assertEqual(verification["character_chat_status"], "ready")
        self.assertEqual(verification["ready_public_candidate_count"], 1)
        self.assertEqual(verification["public_slot_ready_count"], 1)
        self.assertEqual(verification["ready_scope_keys"], [scope_key])
        self.assertEqual(verification["missing_profile_scope_keys"], [])
        self.assertEqual(verification["missing_opening_scope_keys"], [])
        self.assertEqual(verification["missing_usable_scene_scope_keys"], [])

    def test_no_public_candidate_is_none_eligible_not_ready(self):
        module = load_module()

        verification = module.build_character_chat_asset_readiness_verification(
            product_id=102,
            story_context_status="ready",
            summary_rows_by_type={
                "character_inventory_v3": [
                    row(
                        "character_inventory_v3",
                        "supporting:named:오리온",
                        inventory_payload("supporting:named:오리온", public_chat=False, public_slot=False),
                    )
                ],
            },
        )

        self.assertEqual(verification["character_chat_status"], "none_eligible")
        self.assertEqual(verification["public_candidate_count"], 0)
        self.assertEqual(verification["ready_public_candidate_count"], 0)

    def test_status_row_is_enriched_with_character_chat_asset_readiness(self):
        module = load_module()
        readiness = {
            "schema_version": "character_chat_asset_readiness_v1",
            "character_chat_status": "hold",
        }
        fake_cursor = object()

        with patch.object(module, "fetch_character_chat_asset_readiness_verification", return_value=readiness) as fetch:
            enriched = module.attach_character_chat_asset_readiness_to_status_row(
                fake_cursor,
                {
                    "product_id": 103,
                    "context_status": "ready",
                    "total_episode_count": 12,
                    "ready_episode_count": 12,
                },
            )

        fetch.assert_called_once_with(
            fake_cursor,
            product_id=103,
            story_context_status="ready",
            total_episode_count=12,
        )
        self.assertEqual(enriched["context_status"], "ready")
        self.assertEqual(enriched["character_chat_asset_readiness"], readiness)


if __name__ == "__main__":
    unittest.main()
