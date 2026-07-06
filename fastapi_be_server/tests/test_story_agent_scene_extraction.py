import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_story_agent_context.py"


class FakeConnection:
    def __init__(self):
        self.commit_count = 0

    def commit(self):
        self.commit_count += 1


@contextmanager
def fake_work_cursor(_conn):
    yield object()


def load_module():
    module_name = "build_story_agent_scene_extraction_under_test"
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


class StoryAgentSceneExtractionTest(unittest.TestCase):
    def test_line_index_and_anchor_resolution_support_whitespace_normalized_match(self):
        module = load_module()
        text = "문이 열렸다.\n아델리트는  낮게 말했다.\n\"움직이지 마.\"\n"

        indexed_text, line_rows = module.build_line_indexed_episode_text(text)
        exact = module.resolve_episode_scene_anchor(text, "문이 열렸다.")
        normalized = module.resolve_episode_scene_anchor(text, "아델리트는 낮게 말했다.")

        self.assertIn("L0002|", indexed_text)
        self.assertEqual(line_rows[1]["line_no"], 2)
        self.assertEqual(exact["match_type"], "exact")
        self.assertEqual(normalized["match_type"], "whitespace_normalized")
        self.assertEqual(normalized["matched_text"], "아델리트는  낮게 말했다.")

    def test_normalize_scene_payload_partitions_source_by_resolved_anchors(self):
        module = load_module()
        text = (
            "아델리트는 문틈으로 새어 들어온 빛을 보았다.\n"
            "그녀는 오래된 열쇠를 손바닥 위에서 굴렸다.\n"
            "밖에서 경비병의 발소리가 가까워졌다.\n"
            "아델리트는 숨을 낮추고 문고리를 붙잡았다.\n"
        )
        canonical_packet = {
            "characters": [
                {"scope_key": "character:아델리트", "display_name": "아델리트", "aliases": ["아델리트"]}
            ]
        }
        payload = {
            "schema_version": "episode_scene_extraction_v1",
            "status": "ok",
            "scenes": [
                {
                    "scene_index": 1,
                    "boundary_anchor_start": "아델리트는 문틈으로 새어 들어온 빛을 보았다.",
                    "scene_kind": "exposition",
                    "scene_gist": "아델리트가 열쇠와 문틈의 빛으로 상황을 살핀다.",
                    "current_action": "열쇠를 굴리며 문밖을 살핀다.",
                    "immediate_pressure": "경비병이 오기 전에 문을 열지 말지 결정해야 한다.",
                    "character_initiative_reason": "발소리가 가까워져 조용한 협력이 필요하다.",
                    "user_entry_role": "임시 동행자",
                    "user_hook": "소리를 내지 않고 잠금 장치를 확인할지 선택하게 한다.",
                    "user_can_do": ["소리를 듣는다", "잠금 장치를 살핀다"],
                    "opening_grounding": {
                        "place_anchor": "문틈 앞",
                        "sensory_anchors": ["새어 들어온 빛", "경비병의 발소리"],
                        "prop_anchors": ["오래된 열쇠"],
                        "spatial_constraints": ["문 안쪽"],
                        "character_visible_motion": "열쇠를 손바닥 위에서 굴린다.",
                        "forbidden_opening_inventions": ["비", "달빛"],
                    },
                    "scene_identity_boundary": {
                        "allowed_address_names": ["아델리트", "공녀"],
                        "must_not_address_as": ["열쇠의 주인"],
                        "surface_role_for_user": "문 앞의 임시 동행자",
                        "identity_spoiler_risk": "medium",
                    },
                    "pressure_clock": "발소리가 세 걸음 안으로 좁혀진다.",
                    "conversation_fuel_tags": ["잠입", "선택"],
                    "beat_ladder": [
                        {"trigger": "협력 의사를 보임", "advance": "문을 열지 말지 작은 선택을 준다"}
                    ],
                    "turn_continuation_contract": {
                        "state_variables": ["발소리 거리", "잠금 상태"],
                        "user_response_branches": {
                            "accepts_hook": "잠금 장치 확인으로 문 앞 긴장이 오른다.",
                            "asks_question": "아델리트가 낮게 답하고 소리의 방향을 짚는다.",
                            "refuses_or_delays": "아델리트가 다른 선택지를 짧게 제시한다.",
                            "short_or_ambiguous": "아델리트가 시간을 끊으며 선택을 좁힌다.",
                            "hostile_or_suspicious": "의심은 접고 문밖 압력으로 되돌린다.",
                        },
                        "stall_breaker": "문틈의 빛이 한 번 흔들린다.",
                        "scene_exit_condition": "잠금 장치를 확인하면 다음 행동으로 넘어간다.",
                        "canon_safe_new_event_types": ["주변 소음", "새 단서"],
                    },
                    "knowledge_boundary": {
                        "can_hint": ["열쇠가 평범하지 않다"],
                        "must_not_reveal": ["열쇠의 제작자"],
                    },
                    "progression_seed": "발소리가 가까워지며 문틈의 빛이 흔들린다.",
                    "participants": [
                        {
                            "mention_label": "아델리트",
                            "scope_key": "character:아델리트",
                            "evidence": "아델리트는 문틈으로",
                        }
                    ],
                    "action_ownership": [
                        {"actor_scope_key": "character:아델리트", "action": "열쇠를 확인한다"}
                    ],
                },
                {
                    "scene_index": 2,
                    "boundary_anchor_start": "밖에서 경비병의 발소리가 가까워졌다.",
                    "scene_kind": "conflict",
                    "scene_gist": "경비병의 접근으로 문 앞 긴장이 올라간다.",
                    "participants": [{"mention_label": "경비병", "scope_key": None}],
                    "action_ownership": [],
                },
            ],
        }

        normalized = module.normalize_episode_scene_extraction_payload(
            payload,
            normalized_text=text,
            canonical_character_packet=canonical_packet,
            episode_no=7,
        )

        self.assertEqual(normalized["status"], "ok")
        self.assertEqual(normalized["scene_count"], 2)
        self.assertEqual(normalized["episode_no"], 7)
        self.assertEqual(normalized["scenes"][0]["start_line"], 1)
        self.assertEqual(normalized["scenes"][0]["end_line"], 2)
        self.assertEqual(normalized["scenes"][1]["start_line"], 3)
        self.assertEqual(normalized["scenes"][1]["end_line"], 4)
        self.assertEqual(normalized["scenes"][0]["current_action"], "열쇠를 굴리며 문밖을 살핀다.")
        self.assertEqual(normalized["scenes"][0]["immediate_pressure"], "경비병이 오기 전에 문을 열지 말지 결정해야 한다.")
        self.assertEqual(normalized["scenes"][0]["character_initiative_reason"], "발소리가 가까워져 조용한 협력이 필요하다.")
        self.assertEqual(normalized["scenes"][0]["user_entry_role"], "임시 동행자")
        self.assertEqual(normalized["scenes"][0]["user_hook"], "소리를 내지 않고 잠금 장치를 확인할지 선택하게 한다.")
        self.assertEqual(normalized["scenes"][0]["user_can_do"], ["소리를 듣는다", "잠금 장치를 살핀다"])
        self.assertEqual(normalized["scenes"][0]["opening_grounding"]["place_anchor"], "문틈 앞")
        self.assertEqual(normalized["scenes"][0]["opening_grounding"]["prop_anchors"], ["오래된 열쇠"])
        self.assertEqual(normalized["scenes"][0]["opening_grounding"]["forbidden_opening_inventions"], ["비", "달빛"])
        self.assertEqual(normalized["scenes"][0]["scene_identity_boundary"]["allowed_address_names"], ["아델리트", "공녀"])
        self.assertEqual(normalized["scenes"][0]["scene_identity_boundary"]["must_not_address_as"], ["열쇠의 주인"])
        self.assertEqual(normalized["scenes"][0]["scene_identity_boundary"]["identity_spoiler_risk"], "medium")
        self.assertEqual(normalized["scenes"][0]["pressure_clock"], "발소리가 세 걸음 안으로 좁혀진다.")
        self.assertEqual(normalized["scenes"][0]["conversation_fuel_tags"], ["잠입", "선택"])
        self.assertEqual(normalized["scenes"][0]["beat_ladder"], ["협력 의사를 보임 -> 문을 열지 말지 작은 선택을 준다"])
        self.assertEqual(normalized["scenes"][0]["turn_continuation_contract"]["state_variables"], ["발소리 거리", "잠금 상태"])
        self.assertEqual(
            normalized["scenes"][0]["turn_continuation_contract"]["user_response_branches"]["short_or_ambiguous"],
            "아델리트가 시간을 끊으며 선택을 좁힌다.",
        )
        self.assertEqual(normalized["scenes"][0]["turn_continuation_contract"]["stall_breaker"], "문틈의 빛이 한 번 흔들린다.")
        self.assertEqual(normalized["scenes"][0]["knowledge_boundary"]["must_not_reveal"], ["열쇠의 제작자"])
        self.assertEqual(normalized["scenes"][0]["progression_seed"], "발소리가 가까워지며 문틈의 빛이 흔들린다.")
        self.assertEqual(normalized["scenes"][1]["current_action"], "")
        self.assertEqual(normalized["scenes"][1]["user_can_do"], [])
        self.assertEqual(normalized["scenes"][1]["opening_grounding"]["place_anchor"], "")
        self.assertEqual(normalized["scenes"][1]["scene_identity_boundary"]["identity_spoiler_risk"], "unknown")
        self.assertEqual(normalized["scenes"][1]["turn_continuation_contract"]["state_variables"], [])
        self.assertEqual(normalized["scenes"][1]["knowledge_boundary"], {"can_hint": [], "must_not_reveal": []})
        self.assertEqual(normalized["scenes"][0]["participants"][0]["scope_key"], "character:아델리트")

    def test_normalize_scene_payload_drops_missing_anchor_scene(self):
        module = load_module()
        payload = {
            "status": "ok",
            "scenes": [
                {
                    "boundary_anchor_start": "원문에 없는 문장",
                    "scene_kind": "dialogue",
                    "scene_gist": "없는 장면",
                }
            ],
        }

        normalized = module.normalize_episode_scene_extraction_payload(payload, normalized_text="실제 원문만 있다.")

        self.assertEqual(normalized["status"], "failed")
        self.assertEqual(normalized["scene_count"], 0)
        self.assertEqual(normalized["dropped_scene_count"], 1)
        self.assertIn("scene_1_anchor_not_found", normalized["validation_issues"])

    def test_normalize_scene_payload_removes_invented_scope_key(self):
        module = load_module()
        text = "아델리트는 고개를 들었다.\n"
        payload = {
            "status": "ok",
            "scenes": [
                {
                    "boundary_anchor_start": "아델리트는 고개를 들었다.",
                    "scene_kind": "action",
                    "scene_gist": "아델리트가 반응한다.",
                    "participants": [{"mention_label": "아델리트", "scope_key": "character:invented"}],
                    "action_ownership": [{"actor_scope_key": "character:invented", "action": "반응한다"}],
                }
            ],
        }

        normalized = module.normalize_episode_scene_extraction_payload(
            payload,
            normalized_text=text,
            canonical_character_packet={"characters": [{"scope_key": "character:아델리트", "display_name": "아델리트"}]},
        )

        self.assertEqual(normalized["status"], "partial")
        self.assertIsNone(normalized["scenes"][0]["participants"][0]["scope_key"])
        self.assertIsNone(normalized["scenes"][0]["action_ownership"][0]["actor_scope_key"])
        self.assertIn("scene_1_participant_1_unknown_scope:character:invented", normalized["validation_issues"])
        self.assertIn("scene_1_action_1_unknown_scope:character:invented", normalized["validation_issues"])

    def test_scene_extraction_prompt_forbids_greeting_or_rp_generation(self):
        module = load_module()

        self.assertIn("첫인사, RP 대사, 새 사건, 감상평을 만들지 마라", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("canonical scope_key가 확실하지 않으면", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("장면당 participants 최대 3명", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("evidence에는 L0001 같은 라인 prefix를 넣지 말고", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("현장에 등장해 직접 판단, 행동, 대화, 관계 반응", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("현장에 등장하는 장면을 최소 4개", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("가능하면 모든 scene의 participants에 주인공/대상 캐릭터", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("user_entry_role", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("character_initiative_reason", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("conversation_fuel_tags", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("opening_grounding", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("scene_identity_boundary", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("turn_continuation_contract", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("knowledge_boundary", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("progression_seed", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("3~5턴 안에", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("boundary_anchor_start는 반드시 원문 일부를 그대로", module.build_episode_scene_extraction_user_prompt(
            product_title="테스트 작품",
            episode_no=1,
            episode_title="시작",
            normalized_text="아델리트는 문을 열었다.",
            canonical_character_packet={"characters": [{"scope_key": "character:아델리트", "display_name": "아델리트"}]},
        ))

    def test_character_chat_prompt_accepts_scene_frame_context(self):
        module = load_module()

        prompt = module.build_character_chat_internal_prompt_user_prompt(
            target={"display_name": "아델리트", "aliases": ["아델리트"], "is_protagonist": True},
            profile_payload={"speech_style": {"tone": ["낮게 말함"]}},
            example_payload={"examples": [{"episode_no": 1, "text": "문은 내가 연다."}]},
            dialogue_items=[{"episode_no": 1, "kind": "dialogue", "context": "문 앞", "text": "문은 내가 연다."}],
            summary_context_lines=["[1화] 아델리트가 문 앞에서 선택을 앞둔다."],
            relation_context_lines=["아델리트 -> 경비병: 경계"],
            scene_context_lines=[
                "[1화] 압력=경비병 접근 | 유저역할=임시 동행자 | hook=소리 없이 잠금 장치를 확인"
            ],
        )

        self.assertIn("[장면 프레임 근거]", prompt)
        self.assertIn("유저역할=임시 동행자", prompt)
        self.assertIn("hook=소리 없이 잠금 장치를 확인", prompt)

    def test_character_chat_prompt_includes_identity_reveal_boundary(self):
        module = load_module()

        prompt = module.build_character_chat_internal_prompt_user_prompt(
            target={"display_name": "조렌 테이머", "aliases": ["조렌 테이머"], "is_protagonist": True},
            profile_payload={"speech_style": {"tone": ["낮고 계산적으로 말함"], "formality": "반말", "sentence_length": "짧게 끊는", "address": "전하"}},
            example_payload={"examples": [{"episode_no": 2, "text": "지금은 조렌 테이머로 불린다."}]},
            dialogue_items=[{"episode_no": 2, "kind": "dialogue", "context": "성문 앞", "text": "그 이름은 여기서 쓰지 마."}],
            summary_context_lines=["[2화] 호영은 조렌 테이머라는 이름으로 움직인다."],
            relation_context_lines=[],
            inventory_item={
                "display_name": "조렌 테이머",
                "work_role": "main_protagonist",
                "identity_surface": {
                    "chat_display_name": "조렌 테이머",
                    "addressable_names": ["조렌 테이머"],
                    "private_identity_names": ["방호영"],
                    "forbidden_until_revealed": ["방호영"],
                    "reveal_state": "known_to_self",
                },
                "reveal_boundary": {
                    "allowed_address_names": ["조렌 테이머"],
                    "must_not_address_as": ["방호영"],
                    "identity_spoiler_risk": "high",
                },
                "read_range_state_snapshot": {
                    "as_of_episode_no": 2,
                    "current_identity": {
                        "display_name": "조렌 테이머",
                        "private_true_name": "방호영",
                        "identity_variant": "alternate_public_identity",
                    },
                    "forbidden_identity_terms": ["방호영"],
                },
                "interaction_affordance_v1": {
                    "preferred_user_role_key": "scene_clue_holder",
                    "user_role_options": [{"role_label_ko": "장면에 단서를 들고 엮인 임시 조력자"}],
                },
                "adjacent_event_seed_v1": {
                    "new_incident_is_adjacent_not_canon": True,
                    "conflict_vector": "hidden_clue",
                    "protagonist_first_move": "현재 압력이나 단서를 먼저 짚는다.",
                },
                "pov_and_protagonist_centrality_v1": {
                    "protagonist_presence": "late_entry_after_prologue",
                    "hold_before_episode_no": 2,
                    "expose_policy": "hold_until_presence_episode",
                },
                "voice_contract_v1": {
                    "speech_register": "honorific_surface_present",
                    "address_terms": ["전하"],
                    "forbidden_speech_patterns": ["무엇을 도와드릴까요"],
                },
            },
        )

        self.assertIn("identity_surface", prompt)
        self.assertIn("forbidden_until_revealed", prompt)
        self.assertIn("reveal_boundary", prompt)
        self.assertIn("must_not_address_as", prompt)
        self.assertIn("read_range_state_snapshot", prompt)
        self.assertIn("interaction_affordance_v1", prompt)
        self.assertIn("adjacent_event_seed_v1", prompt)
        self.assertIn("pov_and_protagonist_centrality_v1", prompt)
        self.assertIn("late_entry_after_prologue", prompt)
        self.assertIn("[보이스 계약]", prompt)
        self.assertIn("profile_voice_contract", prompt)
        self.assertIn("inventory_voice_contract", prompt)
        self.assertIn("honorific_surface_present", prompt)
        self.assertIn("casual", prompt)
        self.assertIn("scene_clue_holder", prompt)
        self.assertIn("hidden_clue", prompt)
        self.assertIn("방호영", prompt)

    def test_character_chat_internal_prompt_hash_changes_with_scene_context(self):
        module = load_module()
        base_kwargs = {
            "character_key": "character:아델리트",
            "inventory_item": {"display_name": "아델리트"},
            "profile_payload": {"speech_style": {"tone": ["낮게 말함"]}},
            "example_payload": {"examples": [{"text": "문은 내가 연다."}]},
            "dialogue_items": [{"episode_no": 1, "text": "문은 내가 연다."}],
            "summary_context_lines": ["[1화] 문 앞 장면"],
            "relation_context_lines": ["아델리트 -> 경비병: 경계"],
        }

        without_scene = module.build_character_chat_internal_prompt_source_hash(**base_kwargs)
        with_scene = module.build_character_chat_internal_prompt_source_hash(
            **base_kwargs,
            scene_context_lines=["[1화] 압력=경비병 접근 | hook=잠금 장치 확인"],
        )

        self.assertNotEqual(without_scene, with_scene)

    def test_character_chat_internal_prompt_hash_changes_with_identity_boundary(self):
        module = load_module()
        base_kwargs = {
            "character_key": "character:조렌테이머",
            "profile_payload": {"speech_style": {"tone": ["낮게 말함"]}},
            "example_payload": {"examples": [{"text": "성문을 닫아라."}]},
            "dialogue_items": [{"episode_no": 2, "text": "성문을 닫아라."}],
            "summary_context_lines": ["[2화] 성문 앞 장면"],
            "relation_context_lines": [],
            "scene_context_lines": ["[2화] 압력=병사 접근 | hook=성문 봉쇄"],
        }

        public_identity = module.build_character_chat_internal_prompt_source_hash(
            **base_kwargs,
            inventory_item={
                "display_name": "조렌 테이머",
                "identity_surface": {
                    "chat_display_name": "조렌 테이머",
                    "addressable_names": ["조렌 테이머", "방호영"],
                    "forbidden_until_revealed": [],
                    "reveal_state": "public",
                },
                "reveal_boundary": {
                    "allowed_address_names": ["조렌 테이머", "방호영"],
                    "must_not_address_as": [],
                    "identity_spoiler_risk": "low",
                },
            },
        )
        hidden_identity = module.build_character_chat_internal_prompt_source_hash(
            **base_kwargs,
            inventory_item={
                "display_name": "조렌 테이머",
                "identity_surface": {
                    "chat_display_name": "조렌 테이머",
                    "addressable_names": ["조렌 테이머"],
                    "private_identity_names": ["방호영"],
                    "forbidden_until_revealed": ["방호영"],
                    "reveal_state": "known_to_self",
                },
                "reveal_boundary": {
                    "allowed_address_names": ["조렌 테이머"],
                    "must_not_address_as": ["방호영"],
                    "identity_spoiler_risk": "high",
                },
            },
        )

        self.assertNotEqual(public_identity, hidden_identity)

    def test_character_chat_internal_prompt_hash_changes_with_runtime_contracts(self):
        module = load_module()
        base_kwargs = {
            "character_key": "character:조렌테이머",
            "profile_payload": {"speech_style": {"tone": ["낮게 말함"]}},
            "example_payload": {"examples": [{"text": "성문을 닫아라."}]},
            "dialogue_items": [{"episode_no": 2, "text": "성문을 닫아라."}],
            "summary_context_lines": ["[2화] 성문 앞 장면"],
            "relation_context_lines": [],
            "scene_context_lines": ["[2화] 압력=병사 접근 | hook=성문 봉쇄"],
        }

        helper_contract = module.build_character_chat_internal_prompt_source_hash(
            **base_kwargs,
            inventory_item={
                "display_name": "조렌 테이머",
                "read_range_state_snapshot": {"as_of_episode_no": 2},
                "interaction_affordance_v1": {"preferred_user_role_key": "temporary_helper_at_scene"},
                "adjacent_event_seed_v1": {"conflict_vector": "unexpected_visitor"},
                "pov_and_protagonist_centrality_v1": {"protagonist_presence": "active_from_start"},
                "voice_contract_v1": {"speech_register": "dialogue_evidence_present"},
            },
        )
        clue_contract = module.build_character_chat_internal_prompt_source_hash(
            **base_kwargs,
            inventory_item={
                "display_name": "조렌 테이머",
                "read_range_state_snapshot": {"as_of_episode_no": 2},
                "interaction_affordance_v1": {"preferred_user_role_key": "scene_clue_holder"},
                "adjacent_event_seed_v1": {"conflict_vector": "hidden_clue"},
                "pov_and_protagonist_centrality_v1": {"protagonist_presence": "late_entry_after_prologue"},
                "voice_contract_v1": {"speech_register": "honorific_surface_present"},
            },
        )

        self.assertNotEqual(helper_contract, clue_contract)

    def test_character_chat_opening_source_hash_includes_runtime_formula_contract(self):
        module = load_module()
        kwargs = {
            "character_key": "character:아델리트",
            "inventory_item": {
                "display_name": "아델리트",
                "read_range_state_snapshot": {"as_of_episode_no": 3},
            },
            "profile_row": {"source_hash": "profile-hash"},
            "examples_row": {"source_hash": "examples-hash"},
            "internal_prompt_row": {"source_hash": "internal-hash"},
            "summary_context_lines": ["3화: 문 앞 압박"],
            "relation_context_lines": ["아델리트 -> 문지기: 경계"],
            "scene_context_lines": ["[3화] 압력=발소리 접근 | hook=문틈 확인"],
        }

        first_hash = module.build_character_chat_opening_source_hash(**kwargs)
        module.CHARACTER_CHAT_OPENING_RUNTIME_FORMULA_CONTRACT_VERSION = "runtime_formula_seed_v2"
        second_hash = module.build_character_chat_opening_source_hash(**kwargs)

        self.assertNotEqual(first_hash, second_hash)

    def test_character_chat_opening_payload_requires_narration_dialogue_and_objective(self):
        module = load_module()
        base_payload = {
            "readiness": {"status": "ready", "confidence": 0.9, "block_reasons": []},
            "chat_target": {"scope_key": "character:아델리트", "display_name": "아델리트"},
            "opening_scene": {"situation": "아델리트가 문 앞의 발소리를 듣는다."},
            "opening_message": {
                "narration": "문틈 아래로 새어 나온 빛이 낡은 바닥의 흠집을 길게 비춘다. 아델리트는 열쇠를 쥔 손을 천천히 내리고, 복도 끝에서 멎은 발소리를 가늠한다. 습기 밴 벽지 사이로 낮은 마찰음이 번지고, 문고리의 금속은 금방이라도 식은 숨을 토할 듯 흔들린다. 아델리트는 먼저 등불의 심지를 낮추고 바닥의 긁힌 자국을 따라 시선을 옮긴다. 지금 문을 열면 안쪽의 누군가가 움직이고, 그림자를 확인하면 발소리의 주인을 놓칠 수 있다. 잠긴 공기 속에서 선택을 미룰 여유가 없다.",
                "dialogue": "\"발소리가 멎었어. 지금 열쇠를 돌릴지, 아니면 저쪽 그림자부터 확인할지 골라.\"",
                "opening_text": "문틈 아래로 새어 나온 빛이 낡은 바닥의 흠집을 길게 비춘다. 아델리트는 열쇠를 쥔 손을 천천히 내리고, 복도 끝에서 멎은 발소리를 가늠한다. 습기 밴 벽지 사이로 낮은 마찰음이 번지고, 문고리의 금속은 금방이라도 식은 숨을 토할 듯 흔들린다. 아델리트는 먼저 등불의 심지를 낮추고 바닥의 긁힌 자국을 따라 시선을 옮긴다. 지금 문을 열면 안쪽의 누군가가 움직이고, 그림자를 확인하면 발소리의 주인을 놓칠 수 있다. 잠긴 공기 속에서 선택을 미룰 여유가 없다.\n\n\"발소리가 멎었어. 지금 열쇠를 돌릴지, 아니면 저쪽 그림자부터 확인할지 골라.\"",
                "user_objective": "열쇠를 돌릴지 그림자를 확인할지 선택한다.",
            },
            "user_role": {"role_type": "임시 동행자"},
            "character_drive": {"immediate_objective": "문 앞의 위험을 넘긴다."},
            "agency_contract": {
                "character_moves_first": True,
                "non_user_dependent_action": "아델리트가 먼저 발소리의 위치를 확인한다.",
            },
            "progression_engine": {"scene_exit_condition": "문 앞 단서를 확인하면 다음 방으로 이동한다."},
            "runtime_formula_seed": {
                "formula_type": "FORMULA_PUBLIC_TEST_FLIP",
                "p_to_user_request": "열쇠와 그림자 중 먼저 확인할 대상을 고르게 한다.",
                "user_task_type": "UT_INSPECT_CLUE",
                "user_task_success_condition": "유저가 열쇠 또는 그림자 중 하나를 선택한다.",
                "protagonist_state_delta": "아델리트가 선택된 단서를 기준으로 문 앞 대응을 바꾼다.",
                "open_loop": "문 안쪽의 움직임이 다음 압박으로 남는다.",
                "mutation_policy": "MP_SAME_PRESSURE_NEW_ROUTE",
            },
        }

        normalized = module.normalize_character_chat_opening_payload(
            base_payload,
            scope_key="character:아델리트",
            display_name="아델리트",
        )

        self.assertIsNotNone(normalized)
        self.assertIn("문틈 아래로", normalized["opening_message"]["opening_text"])
        self.assertIn("\n\n", normalized["opening_message"]["opening_text"])
        self.assertIn("\"발소리가 멎었어.", normalized["opening_message"]["opening_text"])
        self.assertEqual(normalized["opening_message"]["user_objective"], "열쇠를 돌릴지 그림자를 확인할지 선택한다.")
        self.assertEqual(normalized["runtime_formula_seed"]["user_task_type"], "UT_INSPECT_CLUE")

        missing_formula_seed = dict(base_payload)
        missing_formula_seed.pop("runtime_formula_seed")
        self.assertIsNone(
            module.normalize_character_chat_opening_payload(
                missing_formula_seed,
                scope_key="character:아델리트",
                display_name="아델리트",
            )
        )

        dialogue_only = dict(base_payload)
        dialogue_only["opening_message"] = {
            "dialogue": "\"열쇠를 돌릴지 골라.\"",
            "opening_text": "\"열쇠를 돌릴지 골라.\"",
            "user_objective": "열쇠를 돌린다.",
        }
        self.assertIsNone(
            module.normalize_character_chat_opening_payload(
                dialogue_only,
                scope_key="character:아델리트",
                display_name="아델리트",
            )
        )

        narration_only = dict(base_payload)
        narration_only["opening_message"] = {
            "narration": "문틈 아래로 새어 나온 빛이 낡은 바닥의 흠집을 비춘다.",
            "opening_text": "문틈 아래로 새어 나온 빛이 낡은 바닥의 흠집을 비춘다.",
            "user_objective": "흠집을 확인한다.",
        }
        self.assertIsNone(
            module.normalize_character_chat_opening_payload(
                narration_only,
                scope_key="character:아델리트",
                display_name="아델리트",
            )
        )

        agency_bad = dict(base_payload)
        agency_bad["opening_message"] = dict(base_payload["opening_message"])
        agency_bad["opening_message"]["dialogue"] = "\"거기, 멍하니 서 있지 말고 저 그림자부터 확인해.\""
        agency_bad["opening_message"]["opening_text"] = (
            agency_bad["opening_message"]["narration"]
            + "\n\n"
            + agency_bad["opening_message"]["dialogue"]
        )
        self.assertIsNone(
            module.normalize_character_chat_opening_payload(
                agency_bad,
                scope_key="character:아델리트",
                display_name="아델리트",
            )
        )

        vague_address = dict(base_payload)
        vague_address["opening_message"] = dict(base_payload["opening_message"])
        vague_address["opening_message"]["dialogue"] = "\"거기, 저쪽 그림자와 문틈 아래 흔적 중 하나를 먼저 확인해.\""
        vague_address["opening_message"]["opening_text"] = (
            vague_address["opening_message"]["narration"]
            + "\n\n"
            + vague_address["opening_message"]["dialogue"]
        )
        self.assertIsNone(
            module.normalize_character_chat_opening_payload(
                vague_address,
                scope_key="character:아델리트",
                display_name="아델리트",
            )
        )

    def test_build_scene_context_lines_groups_by_scope_key(self):
        module = load_module()
        scene_payload = {
            "episode_no": 3,
            "scenes": [
                {
                    "scene_index": 2,
                    "scene_gist": "아델리트가 문 앞의 압박을 버틴다.",
                    "current_action": "문고리를 붙잡고 경비병의 발소리를 듣는다.",
                    "immediate_pressure": "경비병이 문 앞까지 접근한다.",
                    "character_initiative_reason": "문밖 인기척 때문에 즉시 선택을 요구해야 한다.",
                    "user_entry_role": "임시 동행자",
                    "user_hook": "소리를 내지 않고 열쇠를 확인할지 고르게 한다.",
                    "user_can_do": ["잠금 장치를 확인한다", "발소리를 센다"],
                    "opening_grounding": {
                        "place_anchor": "문 앞",
                        "sensory_anchors": ["발소리", "문틈의 빛"],
                        "prop_anchors": ["열쇠"],
                        "spatial_constraints": ["문 안쪽"],
                        "character_visible_motion": "문고리를 붙잡는다.",
                        "forbidden_opening_inventions": ["비"],
                    },
                    "scene_identity_boundary": {
                        "allowed_address_names": ["아델리트", "경비병"],
                        "must_not_address_as": ["열쇠의 주인"],
                        "surface_role_for_user": "임시 동행자",
                        "identity_spoiler_risk": "medium",
                    },
                    "pressure_clock": "문밖의 발소리가 멎으면 곧 문이 열린다.",
                    "conversation_fuel_tags": ["잠입", "협력"],
                    "beat_ladder": ["선택을 묻는다", "문밖 방해자가 끼어든다"],
                    "turn_continuation_contract": {
                        "state_variables": ["발소리 거리", "문 잠금"],
                        "user_response_branches": {
                            "short_or_ambiguous": "아델리트가 선택지를 하나로 좁힌다.",
                            "refuses_or_delays": "문밖 압력을 들어 다른 선택을 제시한다.",
                            "asks_question": "짧게 답하고 잠금 확인으로 돌린다.",
                        },
                        "stall_breaker": "문틈의 빛이 흔들린다.",
                        "scene_exit_condition": "열쇠 확인이 끝나면 다음 방으로 이동한다.",
                        "canon_safe_new_event_types": ["주변 소음", "새 단서"],
                    },
                    "knowledge_boundary": {"can_hint": ["열쇠가 이상하다"], "must_not_reveal": ["비밀 통로"]},
                    "progression_seed": "발소리가 멎고 다른 목소리가 끼어든다.",
                    "participants": [
                        {"mention_label": "아델리트", "scope_key": "character:아델리트"},
                        {"mention_label": "경비병", "scope_key": "character:경비병"},
                    ],
                    "action_ownership": [
                        {"actor_scope_key": "character:아델리트", "action": "문고리를 붙잡는다"}
                    ],
                }
            ],
        }

        lines_by_scope = module.build_character_chat_scene_context_lines_by_scope(
            [{"summary_text": json.dumps(scene_payload, ensure_ascii=False)}]
        )

        lines = lines_by_scope["character:아델리트"]
        self.assertEqual(len(lines), 1)
        self.assertIn("3화 장면2", lines[0])
        self.assertIn("압력=경비병이 문 앞까지 접근한다.", lines[0])
        self.assertIn("선제이유=문밖 인기척 때문에 즉시 선택을 요구해야 한다.", lines[0])
        self.assertIn("유저역할=임시 동행자", lines[0])
        self.assertIn("선택=잠금 장치를 확인한다; 발소리를 센다", lines[0])
        self.assertIn("장소=문 앞", lines[0])
        self.assertIn("감각=발소리; 문틈의 빛", lines[0])
        self.assertIn("소품=열쇠", lines[0])
        self.assertIn("금지장식=비", lines[0])
        self.assertIn("허용호칭=아델리트", lines[0])
        self.assertIn("금지호칭=열쇠의 주인", lines[0])
        self.assertIn("정체위험=medium", lines[0])
        self.assertIn("연료=잠입, 협력", lines[0])
        self.assertIn("상태변수=발소리 거리; 문 잠금", lines[0])
        self.assertIn("분기=아델리트가 선택지를 하나로 좁힌다.; 문밖 압력을 들어 다른 선택을 제시한다.", lines[0])
        self.assertIn("정체해소=문틈의 빛이 흔들린다.", lines[0])
        self.assertIn("퇴장조건=열쇠 확인이 끝나면 다음 방으로 이동한다.", lines[0])
        self.assertIn("금지공개=비밀 통로", lines[0])
        self.assertIn("진행=발소리가 멎고 다른 목소리가 끼어든다.", lines[0])
        guard_lines = lines_by_scope["character:경비병"]
        self.assertIn("허용호칭=경비병", guard_lines[0])
        self.assertNotIn("허용호칭=아델리트", guard_lines[0])

    def test_build_scene_canonical_character_packet_prefers_protagonist_people(self):
        module = load_module()

        packet = module.build_episode_scene_canonical_character_packet(
            {
                "character:조연": {
                    "canonical_character_key": "character:조연",
                    "display_name": "조연",
                    "aliases": ["조연"],
                    "entity_kind": "person",
                    "distinct_episode_count": 8,
                    "first_seen_episode_no": 1,
                },
                "location:성": {
                    "canonical_character_key": "location:성",
                    "display_name": "성",
                    "entity_kind": "place",
                },
                "character:아델리트": {
                    "canonical_character_key": "character:아델리트",
                    "display_name": "아델리트",
                    "aliases": ["아델리트", "공녀"],
                    "entity_kind": "person",
                    "work_role": "main_protagonist",
                    "distinct_episode_count": 3,
                    "first_seen_episode_no": 2,
                },
            }
        )

        self.assertEqual(packet["characters"][0]["scope_key"], "character:아델리트")
        self.assertEqual(packet["characters"][0]["aliases"], ["아델리트", "공녀"])
        self.assertEqual([item["scope_key"] for item in packet["characters"]], ["character:아델리트", "character:조연"])

    def test_scene_extraction_source_hash_changes_with_canonical_packet(self):
        module = load_module()
        row = {"summary_id": 11, "source_hash": "episode-source"}

        first_hash = module.build_episode_scene_extraction_source_hash(
            row,
            {"characters": [{"scope_key": "character:아델리트", "display_name": "아델리트"}]},
        )
        second_hash = module.build_episode_scene_extraction_source_hash(
            row,
            {"characters": [{"scope_key": "character:조연", "display_name": "조연"}]},
        )

        self.assertNotEqual(first_hash, second_hash)

    def test_scene_extraction_keeps_old_when_payload_has_no_valid_scenes(self):
        module = load_module()
        conn = FakeConnection()
        request_mock = AsyncMock(
            return_value={
                "schema_version": "episode_scene_extraction_v1",
                "status": "failed",
                "scene_count": 0,
                "validation_issues": ["payload_not_object"],
                "scenes": [],
            }
        )

        async def run():
            with patch.object(module, "work_cursor", fake_work_cursor), \
                 patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
                 patch.object(module, "fetch_existing_summary", return_value=None), \
                 patch.object(module, "request_episode_scene_extraction_payload", request_mock), \
                 patch.object(module, "upsert_summary") as upsert_summary:
                inserted, reused = await module.build_episode_scene_extraction_summaries(
                    conn,
                    product_id=687,
                    product_title="테스트 작품",
                    episode_rows=[
                        {
                            "summary_id": 11,
                            "scope_key": "episode:1",
                            "episode_from": 1,
                            "source_hash": "summary-hash",
                            "summary_text": "[1화] 시작",
                        }
                    ],
                    episode_texts_by_no={1: "아델리트는 문을 열었다."},
                    summary_client=object(),
                    canonical_character_packet={
                        "characters": [{"scope_key": "character:아델리트", "display_name": "아델리트"}]
                    },
                    cleanup_missing_scopes=False,
                    verbose=True,
                )
            return inserted, reused, upsert_summary

        inserted, reused, upsert_summary = asyncio.run(run())

        self.assertEqual((inserted, reused), (0, 0))
        request_mock.assert_awaited_once()
        upsert_summary.assert_not_called()
        self.assertEqual(conn.commit_count, 0)

    def test_scene_extraction_exception_keeps_old_scope(self):
        module = load_module()
        conn = FakeConnection()
        request_mock = AsyncMock(side_effect=module.RequestError("upstream timeout"))

        async def run():
            with patch.object(module, "work_cursor", fake_work_cursor), \
                 patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
                 patch.object(module, "fetch_existing_summary", return_value=None), \
                 patch.object(module, "request_episode_scene_extraction_payload", request_mock), \
                 patch.object(module, "deactivate_active_scope") as deactivate_scope, \
                 patch.object(module, "upsert_summary") as upsert_summary:
                inserted, reused = await module.build_episode_scene_extraction_summaries(
                    conn,
                    product_id=687,
                    product_title="테스트 작품",
                    episode_rows=[
                        {
                            "summary_id": 11,
                            "scope_key": "episode:1",
                            "episode_from": 1,
                            "source_hash": "summary-hash",
                            "summary_text": "[1화] 시작",
                        }
                    ],
                    episode_texts_by_no={1: "아델리트는 문을 열었다."},
                    summary_client=object(),
                    canonical_character_packet={
                        "characters": [{"scope_key": "character:아델리트", "display_name": "아델리트"}]
                    },
                    cleanup_missing_scopes=False,
                    verbose=True,
                )
            return inserted, reused, deactivate_scope, upsert_summary

        inserted, reused, deactivate_scope, upsert_summary = asyncio.run(run())

        self.assertEqual((inserted, reused), (0, 0))
        request_mock.assert_awaited_once()
        deactivate_scope.assert_not_called()
        upsert_summary.assert_not_called()
        self.assertEqual(conn.commit_count, 0)

    def test_scene_extraction_does_not_reuse_existing_failed_payload(self):
        module = load_module()
        conn = FakeConnection()
        request_mock = AsyncMock(
            return_value={
                "schema_version": "episode_scene_extraction_v1",
                "status": "ok",
                "scene_count": 1,
                "validation_issues": [],
                "scenes": [
                    {
                        "scene_index": 1,
                        "scene_gist": "아델리트가 문을 연다.",
                        "participants": [],
                    }
                ],
            }
        )

        async def run():
            with patch.object(module, "work_cursor", fake_work_cursor), \
                 patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
                 patch.object(
                     module,
                     "fetch_existing_summary",
                     return_value={
                         "summary_id": 99,
                         "summary_text": json.dumps(
                             {"status": "failed", "scene_count": 0, "scenes": []},
                             ensure_ascii=False,
                         ),
                     },
                 ), \
                 patch.object(module, "activate_existing_summary") as activate_existing, \
                 patch.object(module, "request_episode_scene_extraction_payload", request_mock), \
                 patch.object(module, "upsert_summary") as upsert_summary, \
                 patch.object(module, "update_existing_summary_payload") as update_existing:
                inserted, reused = await module.build_episode_scene_extraction_summaries(
                    conn,
                    product_id=687,
                    product_title="테스트 작품",
                    episode_rows=[
                        {
                            "summary_id": 11,
                            "scope_key": "episode:1",
                            "episode_from": 1,
                            "source_hash": "summary-hash",
                            "summary_text": "[1화] 시작",
                        }
                    ],
                    episode_texts_by_no={1: "아델리트는 문을 열었다."},
                    summary_client=object(),
                    canonical_character_packet={
                        "characters": [{"scope_key": "character:아델리트", "display_name": "아델리트"}]
                    },
                    cleanup_missing_scopes=False,
                )
            return inserted, reused, activate_existing, upsert_summary, update_existing

        inserted, reused, activate_existing, upsert_summary, update_existing = asyncio.run(run())

        self.assertEqual((inserted, reused), (1, 0))
        activate_existing.assert_not_called()
        request_mock.assert_awaited_once()
        upsert_summary.assert_not_called()
        update_existing.assert_called_once()
        self.assertEqual(conn.commit_count, 1)

    def test_scene_extraction_request_retries_incomplete_json_once(self):
        module = load_module()
        request_mock = AsyncMock(
            side_effect=[
                None,
                {
                    "schema_version": "episode_scene_extraction_v1",
                    "status": "ok",
                    "scenes": [
                        {
                            "scene_index": 1,
                            "boundary_anchor_start": "아델리트는 문을 열었다.",
                            "scene_kind": "action",
                            "scene_gist": "아델리트가 문을 연다.",
                            "participants": [
                                {"mention_label": "아델리트", "scope_key": "character:아델리트"}
                            ],
                            "action_ownership": [
                                {"actor_scope_key": "character:아델리트", "action": "문을 연다"}
                            ],
                        }
                    ],
                },
            ]
        )

        async def run():
            with patch.object(module, "request_episode_scene_extraction_openrouter_json_payload", request_mock):
                return await module.request_episode_scene_extraction_payload(
                    object(),
                    product_title="테스트 작품",
                    episode_no=1,
                    episode_title="시작",
                    normalized_text="아델리트는 문을 열었다.",
                    canonical_character_packet={
                        "characters": [{"scope_key": "character:아델리트", "display_name": "아델리트"}]
                    },
                )

        payload = asyncio.run(run())

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["scene_count"], 1)
        self.assertEqual(request_mock.await_count, 2)
        self.assertIn("이전 응답은 완전한 JSON object가 아니었다", request_mock.await_args_list[1].kwargs["user_prompt"])


if __name__ == "__main__":
    unittest.main()
