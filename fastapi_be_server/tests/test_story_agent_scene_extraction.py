import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch

from tests.test_character_asset_attempt import ReceiptConnection
from tests.test_story_agent_context_cost_guard import FakeOpenRouterClient


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_story_agent_context.py"


class FakeConnection:
    def __init__(self):
        self.commit_count = 0
        self.rollback_count = 0

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


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
    module._character_asset_attempt_store = module.CharacterAssetAttemptStore(ReceiptConnection())
    module._character_asset_product_id.set(687)
    return module


class StoryAgentSceneExtractionTest(unittest.TestCase):
    def test_cached_superseded_scene_replacement_preserves_canonical_actors_and_receipts(self):
        for receipt_version, omit_companion in ((None, False), ("receipt_v2", False), ("receipt_v1", False), (None, True), ("receipt_v2", True), ("receipt_v1", True)):
            with self.subTest(receipt_version=receipt_version, omit_companion=omit_companion):
                module = load_module()
                conn = FakeConnection()
                old, canonical, companion = "character:old", "character:new", "character:companion"
                raw = "민서는 문을 닫았고 도윤은 출구를 지켰다."
                packet = {"characters": [{"scope_key": canonical, "display_name": "민서"}, {"scope_key": companion, "display_name": "도윤"}]}
                row = {"summary_id": 104, "scope_key": "episode:104", "episode_from": 5, "source_hash": "summary104", "summary_text": "[5화] 출구"}
                payload = {"episode_no": 5, "scenes": [{"boundary_anchor_start": raw, "scene_gist": raw, "participants": [{"mention_label": "민서", "scope_key": canonical}], "action_ownership": []}]}
                if not omit_companion:
                    payload["scenes"][0]["participants"].append({"mention_label": "도윤", "scope_key": companion})
                cached_payload = {"episode_no": 5, "status": "ok", "scene_count": 1, "scenes": [{"scene_gist": raw, "participants": [{"scope_key": old}, {"scope_key": companion}]}]}
                cached = {"summary_id": 777, "scope_key": "episode:104", "episode_from": 5, "episode_to": 5, "source_hash": module.build_episode_scene_extraction_source_hash(row, packet, normalized_text=raw), "summary_text": json.dumps(cached_payload)}
                client = FakeOpenRouterClient(payload)
                store = module._character_asset_attempt_store

                async def run():
                    with patch.object(module, "OPENROUTER_API_KEY", "test-key"), patch.object(module, "work_cursor", fake_work_cursor), patch.object(module, "fetch_existing_summary", return_value=cached) as fetch, patch.object(module, "fetch_active_summary_by_scope", return_value=cached), patch.object(module, "activate_existing_summary") as activate, patch.object(module, "update_existing_summary_payload") as update, patch.object(module, "upsert_summary") as insert:
                        before = None
                        if receipt_version:
                            prompt = module.build_episode_scene_extraction_user_prompt(product_title="합성 작품", episode_no=5, episode_title=module.parse_summary_text(row["summary_text"]).get("header") or "", normalized_text=raw, canonical_character_packet=packet)
                            if receipt_version == "receipt_v2":
                                constraints = {"episode_scope_key": "episode:104", "episode_no": 5, "required_scope_keys": sorted([canonical, companion]), "scope_key_replacements": {old: canonical}}
                                prompt += "\n필수 장면 계약: " + json.dumps(constraints, ensure_ascii=False, sort_keys=True) + "\n원문에서 뒷받침되는 필수 인물을 장면에 포함하고, 근거 없는 인물은 만들지 마라."
                            key = module.attempt_key(687, "scenes", "episode:104", module.EPISODE_SCENE_EXTRACTION_FORMAT_VERSION + ":" + receipt_version, {"provider": "openrouter", "body": module.build_episode_scene_extraction_openrouter_payload(user_prompt=prompt)})
                            store.claim(key)
                            store.accept(key, payload)
                            before = deepcopy(store.connection.rows)
                        for _ in range(2):
                            kwargs = dict(product_id=687, product_title="합성 작품", episode_rows=[row], episode_scope_map={"episode:104": 5}, episode_texts_by_scope={"episode:104": raw}, summary_client=client, canonical_character_packet=packet, scope_key_replacements={old: canonical}, required_scope_keys_by_episode_scope={"episode:104": {canonical}}, cleanup_missing_scopes=False, commit_changes=False)
                            if omit_companion:
                                with self.assertRaises(module.CharacterAssetAttemptBlocked):
                                    await module.build_episode_scene_extraction_summaries_nonblocking(conn, **kwargs)
                            else:
                                try:
                                    result = await module.build_episode_scene_extraction_summaries_nonblocking(conn, **kwargs)
                                except module.CharacterAssetAttemptBlocked:
                                    self.assertEqual(next(iter(store.connection.rows.values()))["status"], "accepted")
                                    update.assert_not_called()
                                    raise
                                self.assertEqual(result, (1, 0))
                                replacement = update.call_args.kwargs
                                self.assertEqual(replacement["summary_id"], 777)
                                self.assertEqual(module.extract_episode_scene_character_scope_keys(json.loads(replacement["summary_text"])), {canonical, companion})
                                episode_map = {**{f"episode:{200 + no}": no for no in range(1, 5)}, "episode:104": 5}
                                prepared = [{"scope_key": f"episode:{200 + no}", "episode_from": no, "episode_to": no, "summary_text": json.dumps({"episode_no": no, "status": "ok", "scenes": [{"scene_gist": "민서는 문을 지켰다.", "participants": [{"scope_key": canonical}]}]})} for no in range(1, 5)]
                                self.assertEqual(len(module.build_usable_character_scene_episodes_by_scope(prepared, episode_map)[canonical]), 4)
                                coverage = module.build_usable_character_scene_episodes_by_scope([*prepared, replacement], episode_map)
                                self.assertEqual(set(coverage[canonical]), set(episode_map))
                                self.assertNotIn(old, coverage)
                                conn.rollback()  # The next invocation still sees both original cache rows.
                        self.assertEqual(fetch.call_args.kwargs["source_hash"], cached["source_hash"])
                        activate.assert_not_called()
                        insert.assert_not_called()
                        self.assertEqual(update.call_count, 0 if omit_companion else 2)
                        self.assertEqual(len(client.calls), 0 if receipt_version else 1)
                        self.assertEqual(len(store.connection.rows), 1)
                        if before is not None:
                            self.assertEqual(store.connection.rows, before)
                        else:
                            self.assertEqual(next(iter(store.connection.rows.values()))["status"], "terminal_invalid" if omit_companion else "accepted")
                asyncio.run(run())

    def test_scene_packet_retains_anonymous_first_person_but_not_shared_roles(self):
        module = load_module()
        packet = module.build_episode_scene_canonical_character_packet({
            "character:anonymous": {
                "display_name": "나(주인공)", "entity_kind": "stable_role",
                "is_protagonist": True, "first_person_evidence": {"episode_count": 2},
                "work_role": "main_protagonist",
                "source_character_keys": ["protagonist:generic"],
            },
            "character:role": {
                "display_name": "경비원", "entity_kind": "stable_role",
                "work_role": "major_character",
            },
            "character:민서": {"display_name": "민서", "entity_kind": "person"},
        })
        self.assertEqual({item["scope_key"] for item in packet["characters"]}, {"character:anonymous", "character:민서"})

    def test_usable_scene_payload_requires_known_status_and_scene_gist(self):
        module = load_module()

        self.assertFalse(
            module._is_usable_episode_scene_payload(
                {"scene_count": 1, "scenes": [{}]}
            )
        )
        self.assertFalse(
            module._is_usable_episode_scene_payload(
                {"status": "garbage", "scene_count": 1, "scenes": [{}]}
            )
        )
        self.assertTrue(
            module._is_usable_episode_scene_payload(
                {
                    "status": "partial",
                    "scene_count": 1,
                    "scenes": [{"scene_gist": "주인공이 문을 연다."}],
                }
            )
        )

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
        self.assertIn("핵심 장면 2~3개", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
        self.assertIn("현장에 등장하는 장면을 최대 3개", module.EPISODE_SCENE_EXTRACTION_SYSTEM)
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
            normalized_text="원문",
        )
        second_hash = module.build_episode_scene_extraction_source_hash(
            row,
            {"characters": [{"scope_key": "character:조연", "display_name": "조연"}]},
            normalized_text="원문",
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
                 patch.object(module, "RP_OPENROUTER_MODEL", ""), \
                 patch.object(module, "EPISODE_SCENE_EXTRACTION_OPENROUTER_MODEL", "deepseek/deepseek-v4-pro"), \
                 patch.object(module, "fetch_existing_summary", return_value=None), \
                 patch.object(module, "fetch_active_summary_by_scope", return_value=None), \
                 patch.object(module, "request_episode_scene_extraction_payload", request_mock), \
                 patch.object(module, "upsert_summary") as upsert_summary:
                inserted, reused = await module.build_episode_scene_extraction_summaries(
                    conn,
                    episode_scope_map={"episode:1": 1},
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
                    episode_texts_by_scope={"episode:1": "아델리트는 문을 열었다."},
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

    def test_scene_extraction_provider_failure_does_not_deactivate_existing_scope(self):
        module = load_module()
        conn = FakeConnection()
        request_mock = AsyncMock(side_effect=module.RequestError("upstream timeout"))

        async def run():
            with patch.object(module, "work_cursor", fake_work_cursor), \
                 patch.object(module, "OPENROUTER_API_KEY", "openrouter-key"), \
                 patch.object(module, "EPISODE_SCENE_EXTRACTION_OPENROUTER_MODEL", "deepseek/deepseek-v4-pro"), \
                 patch.object(module, "fetch_existing_summary", return_value=None), \
                 patch.object(module, "fetch_active_summary_by_scope", return_value=None), \
                 patch.object(module, "request_episode_scene_extraction_payload", request_mock), \
                 patch.object(module, "deactivate_active_scope") as deactivate_scope:
                inserted, reused = await module.build_episode_scene_extraction_summaries(
                    conn,
                    episode_scope_map={"episode:1": 1},
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
                    episode_texts_by_scope={"episode:1": "아델리트는 문을 열었다."},
                    summary_client=object(),
                    canonical_character_packet={
                        "characters": [{"scope_key": "character:아델리트", "display_name": "아델리트"}]
                    },
                    cleanup_missing_scopes=False,
                )
            return inserted, reused, deactivate_scope

        inserted, reused, deactivate_scope = asyncio.run(run())

        self.assertEqual((inserted, reused), (0, 0))
        request_mock.assert_awaited_once()
        deactivate_scope.assert_not_called()
        self.assertEqual(conn.commit_count, 0)

    def test_scene_extraction_storage_failure_rolls_back_without_failing_product_build(self):
        module = load_module()
        conn = FakeConnection()
        build_mock = AsyncMock(side_effect=RuntimeError("scene upsert failed"))

        async def run():
            with patch.object(
                module,
                "build_episode_scene_extraction_summaries",
                build_mock,
            ):
                return await module.build_episode_scene_extraction_summaries_nonblocking(
                    conn,
                    product_id=687,
                    product_title="테스트 작품",
                    episode_rows=[],
                    episode_texts_by_scope={},
                    summary_client=object(),
                    canonical_character_packet={"characters": []},
                )

        self.assertEqual(asyncio.run(run()), (0, 0))
        self.assertEqual(conn.rollback_count, 1)

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
                 patch.object(module, "fetch_active_summary_by_scope", return_value=None), \
                 patch.object(module, "activate_existing_summary") as activate_existing, \
                 patch.object(module, "request_episode_scene_extraction_payload", request_mock), \
                 patch.object(module, "upsert_summary") as upsert_summary, \
                 patch.object(module, "update_existing_summary_payload") as update_existing:
                inserted, reused = await module.build_episode_scene_extraction_summaries(
                    conn,
                    episode_scope_map={"episode:1": 1},
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
                    episode_texts_by_scope={"episode:1": "아델리트는 문을 열었다."},
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

    def test_scene_extraction_request_blocks_incomplete_json_without_retry(self):
        module = load_module()
        client = FakeOpenRouterClient(None)

        async def run():
            with patch.object(module, "OPENROUTER_API_KEY", "test-key"):
                for _ in range(2):
                    with self.assertRaisesRegex(module.CharacterAssetAttemptBlocked, "terminal_invalid"):
                        await module.request_episode_scene_extraction_payload(
                            client, product_id=687, product_title="테스트 작품",
                            episode_no=1, episode_title="시작",
                            episode_scope_key="episode:1",
                            normalized_text="아델리트는 문을 열었다.",
                            canonical_character_packet={
                                "characters": [{"scope_key": "character:아델리트", "display_name": "아델리트"}]
                            },
                        )

        asyncio.run(run())
        self.assertEqual(len(client.calls), 1)
        receipt = next(iter(module._character_asset_attempt_store.connection.rows.values()))
        self.assertEqual(receipt["status"], "terminal_invalid")


if __name__ == "__main__":
    unittest.main()
