import json
import unittest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from fastapi import status

from app.exceptions import CustomResponseException
from app.schemas.websochat import (
    PatchWebsochatSessionReadScopeReqBody,
    PostWebsochatSessionReqBody,
)
from app.services.websochat import websochat_service
from app.services.websochat.websochat_context_loader import (
    _build_websochat_character_entry_context_v2,
    _is_websochat_character_entry_context_v2,
    load_websochat_character_entry_context_v2,
)
from app.services.websochat.websochat_game_memory import _normalize_websochat_session_memory
from app.services.websochat.websochat_service import (
    _assert_websochat_character_chat_read_scope_not_decreased,
    _ensure_websochat_character_chat_entry_context,
    _filter_websochat_character_chat_examples_by_read_scope,
)
from app.services.websochat.websochat_rp_renderer import (
    _build_character_chat_adjacent_opening_prompt,
    _build_character_chat_entry_context_lines,
    _build_character_chat_safe_scene_material,
    _normalize_character_chat_adjacent_opening_payload,
    _select_rp_examples,
    build_websochat_rp_system_prompt,
    generate_character_chat_adjacent_opening_with_gemini,
)


def _scene_row(episode_no: int, scenes: list[dict]) -> dict:
    return {
        "episodeFrom": episode_no,
        "episodeTo": episode_no,
        "summaryText": json.dumps(
            {
                "schema_version": "episode_scene_extraction_v1",
                "status": "ok",
                "episode_no": episode_no,
                "scenes": scenes,
            },
            ensure_ascii=False,
        ),
    }


def _plot_row(episode_no: int, summary: str) -> dict:
    return {
        "episode_from": episode_no,
        "episode_to": episode_no,
        "summary_text": summary,
    }


def _character_scene(name: str, *, scene_index: int = 1, gist: str = "") -> dict:
    scope_key = f"character:{name}"
    return {
        "scene_index": scene_index,
        "scene_gist": gist or f"{name}이 현재 상황을 정리한다.",
        "current_action": f"{name}이 다음 행동을 준비한다.",
        "immediate_pressure": "직전 회차의 선택 결과가 남아 있다.",
        "pressure_clock": "세 턴 안에 추적자가 도착한다.",
        "beat_ladder": ["흔적 확인", "경로 선택", "작은 결과"],
        "turn_continuation_contract": {
            "stall_breaker": "닫힌 문 너머에서 새 소리가 난다.",
            "scene_exit_condition": "다음 경로를 정한다.",
            "canon_safe_new_event_types": ["정비 순서 변경"],
        },
        "opening_grounding": {
            "place_anchor": "완료된 이전 장소",
            "sensory_anchors": ["기름 냄새"],
            "prop_anchors": ["정비용 톱니"],
            "forbidden_opening_inventions": ["갑작스러운 폭발"],
        },
        "scene_identity_boundary": {
            "allowed_address_names": [name],
            "must_not_address_as": ["숨겨진 정체"],
            "surface_role_for_user": "황제의 측근",
            "identity_spoiler_risk": "high",
        },
        "progression_seed": "해결된 일을 반복하지 않고 다음 결과로 이어간다.",
        "participants": [{"scope_key": scope_key, "mention_label": name}],
        "action_ownership": [{"actor_scope_key": scope_key, "action": "다음 행동을 준비한다."}],
    }


def _entry_context(
    read_episode_to: int,
    *,
    product_id: int = 1182,
    character_scope_key: str = "character:아델리트",
) -> dict:
    recent_episode_from = max(1, read_episode_to - 1)
    return {
        "schema_version": "character_chat_entry_context_v2",
        "product_id": product_id,
        "character_scope_key": character_scope_key,
        "read_episode_to": read_episode_to,
        "recent_episode_from": recent_episode_from,
        "recent_episode_to": read_episode_to,
        "recent_plot_rows": [
            {
                "episode_no": episode_no,
                "summary_text": f"{episode_no}화의 현재 상태",
            }
            for episode_no in range(recent_episode_from, read_episode_to + 1)
        ],
        "character_anchor_episode_no": read_episode_to,
        "character_scene": {"scene_gist": "선택 캐릭터의 마지막 실제 장면"},
    }


class WebsochatCharacterEntryContextTests(unittest.TestCase):
    def test_prologue_rp_example_is_usable_at_first_read_scope(self):
        examples = [
            {"episode_no": 0, "text": "프롤로그 대사"},
            {"episode_no": 1, "text": "첫 등록 회차 대사"},
            {"episode_no": -1, "text": "잘못된 대사"},
            {"text": "회차 근거 없는 대사"},
            {"episode_no": 2, "text": "아직 읽지 않은 대사"},
        ]

        bounded = _filter_websochat_character_chat_examples_by_read_scope(
            examples,
            read_episode_to=1,
        )
        self.assertEqual(
            [item["episode_no"] for item in bounded],
            [0, 1],
        )
        self.assertEqual(
            _select_rp_examples(
                examples_payload=bounded,
                anchor_episode_no=1,
                recent_messages=[],
                scene_summary_text="",
                relationship_stage="",
                read_episode_to=1,
            ),
            ["- 첫 등록 회차 대사", "- 프롤로그 대사"],
        )

    def test_character_catalog_is_an_allowed_character_chat_entry_source(self):
        req = PostWebsochatSessionReqBody(
            product_id=1182,
            session_kind="character_chat",
            entry_source="character_catalog",
            locked_character_scope_key="character:아델리트",
            rp_mode="free",
        )

        self.assertEqual(req.entry_source, "character_catalog")
        self.assertEqual(
            _normalize_websochat_session_memory(
                {
                    "session_kind": "character_chat",
                    "entry_source": req.entry_source,
                    "locked_character_scope_key": req.locked_character_scope_key,
                }
            )["entry_source"],
            "character_catalog",
        )

    def test_adjacent_opening_material_excludes_canon_user_role_and_replay_engine(self):
        entry_context = _entry_context(14)
        entry_context["character_scene"] = {
            "scene_gist": "아델리트가 협상을 마치고 대가를 확인한다.",
            "current_action": "아델리트가 다음 약속을 정리한다.",
            "immediate_pressure": "해가 지기 전에 결정을 내려야 한다.",
            "action_ownership": [
                {
                    "actor_scope_key": "character:아델리트",
                    "action": "봉인 상태를 직접 확인한다.",
                }
            ],
            "user_entry_role": "원작 인물인 황제의 측근",
            "user_hook": "황제가 건넨 밀서를 이미 들고 있다.",
            "user_can_do": ["밀서를 펼친다"],
            "opening_grounding": {
                "place_anchor": "황제의 집무실",
                "sensory_anchors": ["기름 냄새", "낡은 톱니가 긁히는 소리"],
                "prop_anchors": ["정비용 톱니"],
                "forbidden_opening_inventions": ["갑작스러운 폭발"],
            },
            "beat_ladder": ["황제가 명령한다", "밀서를 연다"],
            "turn_continuation_contract": {
                "next": "원작 장면을 재연한다",
                "canon_safe_new_event_types": ["정비 순서 변경"],
            },
            "creative_grounding": {
                "previous_place_anchor": "황제의 집무실",
                "sensory_anchors": ["기름 냄새", "낡은 톱니가 긁히는 소리"],
                "prop_anchors": ["정비용 톱니"],
                "forbidden_inventions": ["갑작스러운 폭발"],
                "canon_safe_new_event_types": ["정비 순서 변경"],
            },
            "progression_seed": "원작 사건을 그대로 진행한다.",
        }

        material = _build_character_chat_safe_scene_material(entry_context)
        serialized = json.dumps(material, ensure_ascii=False)

        self.assertIn("봉인 상태를 직접 확인한다", serialized)
        self.assertIn("14화의 현재 상태", serialized)
        self.assertIn("기름 냄새", serialized)
        self.assertIn("정비용 톱니", serialized)
        self.assertIn("갑작스러운 폭발", serialized)
        self.assertIn("정비 순서 변경", serialized)
        self.assertEqual(material["entry_strategy"], "recent_scene_branch")
        self.assertNotIn("황제의 측근", serialized)
        self.assertNotIn("밀서를 이미 들고", serialized)
        self.assertNotIn("원작 장면을 재연", serialized)

    def test_stale_character_scene_drops_old_place_and_uses_current_boundary(self):
        entry_context = _entry_context(14)
        entry_context["character_anchor_episode_no"] = 9
        entry_context["character_scene"] = {
            "scene_gist": "9화의 오래된 풍차 장면",
            "current_action": "풍차를 수리한다.",
            "creative_grounding": {
                "previous_place_anchor": "9화 풍차 앞",
                "sensory_anchors": ["풍차 날개 소리"],
                "prop_anchors": ["부러진 날개"],
            },
        }

        material = _build_character_chat_safe_scene_material(entry_context)
        serialized = json.dumps(material, ensure_ascii=False)

        self.assertEqual(material["entry_strategy"], "current_boundary_reentry")
        self.assertNotIn("9화 풍차 앞", serialized)
        self.assertNotIn("풍차 날개 소리", serialized)
        self.assertIn("14화의 현재 상태", serialized)

    def test_adjacent_opening_prompt_uses_boundary_voice_and_decision_affordance(self):
        prompt = _build_character_chat_adjacent_opening_prompt(
            product_row={"productId": 1182, "title": "테스트 작품"},
            rp_context={
                "active_character": "character:아델리트",
                "display_name": "아델리트",
                "speech_style": {"tone": ["건조함"], "formality": "반말"},
                "examples": [
                    {"episode_no": 13, "text": "확인했으면 움직여.", "confidence": 0.9},
                    {"episode_no": 15, "text": "미래 회차 말투", "confidence": 1.0},
                ],
                "character_chat_entry_context": _entry_context(14),
            },
        )

        self.assertIn("테스트 작품", prompt)
        self.assertIn("14화 종료 상태", prompt)
        self.assertIn("확인했으면 움직여", prompt)
        self.assertNotIn("미래 회차 말투", prompt)
        self.assertIn("판단에 따라 직접 움직인다", prompt)
        self.assertIn("3인칭 관찰 지문", prompt)
        self.assertIn("recent_scene_branch", prompt)
        self.assertIn("current_boundary_reentry", prompt)
        self.assertIn("설명, 마크다운, JSON 없이", prompt)
        self.assertNotIn('"scene_plan"', prompt)

    def test_adjacent_opening_payload_requires_exact_identity_boundary_and_rich_text(self):
        valid = {
            "schema_version": "character_chat_adjacent_opening_v1",
            "product_id": 1182,
            "character_scope_key": "character:아델리트",
            "read_episode_to": 14,
            "scene_plan": {
                "setting": "협상이 끝난 저녁의 외곽 회랑",
                "continuity_from_boundary": "14화 협상 종료 뒤 남은 일정 압박",
                "freshness_from_completed_scene": "협상 상대와 밀서 없이 별도 봉인 점검을 시작한다.",
                "event_shape": "일상 작업 중 발생한 우선순위 충돌",
                "inciting_event": "봉인 장치가 평소와 다른 간격으로 울린다.",
                "character_first_move": "아델리트가 장치의 진동을 멈추고 원인을 가늠한다.",
                "stakes": "잘못 건드리면 흔적이 사라진다.",
                "beats": ["이상 확인", "판단 선택", "작은 결과"],
                "decision_branch": {
                    "axis": "priority",
                    "user_decision": "흔적 보존과 즉시 확인 중 무엇을 우선할지 판단한다.",
                    "branch_a": {
                        "actor_scope_key": "character:아델리트",
                        "character_next_action": "아델리트가 장치를 봉인하고 흔적을 기록한다.",
                        "immediate_effect": "원인은 늦게 확인하지만 현재 흔적이 보존된다.",
                    },
                    "branch_b": {
                        "actor_scope_key": "character:아델리트",
                        "character_next_action": "아델리트가 덮개를 열고 소리의 근원을 확인한다.",
                        "immediate_effect": "흔적 일부를 잃을 수 있지만 원인을 즉시 좁힌다.",
                    },
                },
            },
            "opening_text": (
                "협상이 끝난 회랑에는 늦은 빛만 길게 남아 있었다. 아델리트는 벽면의 봉인 장치에서 "
                "일정하지 않은 떨림이 번지는 것을 발견하자 손끝으로 가장자리만 눌러 진동을 멈췄다. "
                "안쪽에서 얇은 금속음이 한 번 더 울렸고, 그는 섣불리 덮개를 열지 않은 채 표시의 간격을 살폈다. "
                "오래된 먼지는 그대로인데 한쪽 나사만 미세하게 돌아가 있었다. 아델리트는 흔적을 지우지 않도록 "
                "손을 거두고, 서로 다른 두 소리가 겹치는 주기를 조용히 세었다.\n\n"
                '"평소 고장과는 달라. 먼저 흔적을 보존할지, 지금 소리를 따라 안쪽을 확인할지 정해야 해. '
                '네 판단을 듣고 내가 순서를 바꾸지."'
            ),
        }
        normalized = _normalize_character_chat_adjacent_opening_payload(
            valid,
            expected_product_id=1182,
            expected_character_scope_key="character:아델리트",
            expected_read_episode_to=14,
        )
        wrong_character = dict(valid, character_scope_key="character:다른인물")
        future_episode = dict(
            valid,
            opening_text=valid["opening_text"][:-1] + " 15화에서 밝혀질 일이다.\"",
        )
        trailing_unquoted_dialogue = dict(valid, opening_text=valid["opening_text"] + "\n\n결정해.")
        prior_npc_addressee = dict(
            valid,
            opening_text=valid["opening_text"].replace('"평소', '"폐하, 평소'),
        )
        prior_npc_reference = dict(
            valid,
            opening_text=valid["opening_text"].replace('"평소', '"폐하께서 말한 평소'),
        )
        split_dialogue = dict(
            valid,
            opening_text=valid["opening_text"].replace(
                " 정해야 해. 네 판단을",
                ' 정해야 해."\n\n"네 판단을',
            ),
        )
        wrong_branch_actor = json.loads(json.dumps(valid, ensure_ascii=False))
        wrong_branch_actor["scene_plan"]["decision_branch"]["branch_a"][
            "actor_scope_key"
        ] = "character:다른인물"
        duplicate_branch = json.loads(json.dumps(valid, ensure_ascii=False))
        duplicate_branch["scene_plan"]["decision_branch"]["branch_b"][
            "character_next_action"
        ] = duplicate_branch["scene_plan"]["decision_branch"]["branch_a"][
            "character_next_action"
        ]
        self.assertEqual(normalized["scene_plan"]["beats"], ["이상 확인", "판단 선택", "작은 결과"])
        self.assertEqual(normalized["scene_plan"]["decision_branch"]["axis"], "priority")
        normalized_split_dialogue = _normalize_character_chat_adjacent_opening_payload(
            split_dialogue,
            expected_product_id=1182,
            expected_character_scope_key="character:아델리트",
            expected_read_episode_to=14,
        )
        self.assertIn('정해야 해. 네 판단을', normalized_split_dialogue["opening_text"])
        self.assertNotIn('정해야 해."\n\n"네 판단을', normalized_split_dialogue["opening_text"])
        self.assertEqual(
            _normalize_character_chat_adjacent_opening_payload(
                wrong_character,
                expected_product_id=1182,
                expected_character_scope_key="character:아델리트",
                expected_read_episode_to=14,
            ),
            {},
        )
        self.assertEqual(
            _normalize_character_chat_adjacent_opening_payload(
                prior_npc_addressee,
                expected_product_id=1182,
                expected_character_scope_key="character:아델리트",
                expected_read_episode_to=14,
                forbidden_dialogue_addressees=["폐하"],
            ),
            {},
        )
        self.assertEqual(
            _normalize_character_chat_adjacent_opening_payload(
                trailing_unquoted_dialogue,
                expected_product_id=1182,
                expected_character_scope_key="character:아델리트",
                expected_read_episode_to=14,
            ),
            {},
        )
        self.assertTrue(
            _normalize_character_chat_adjacent_opening_payload(
                prior_npc_reference,
                expected_product_id=1182,
                expected_character_scope_key="character:아델리트",
                expected_read_episode_to=14,
                forbidden_dialogue_addressees=["폐하"],
            )
        )
        self.assertTrue(
            _normalize_character_chat_adjacent_opening_payload(
                future_episode,
                expected_product_id=1182,
                expected_character_scope_key="character:아델리트",
                expected_read_episode_to=14,
            )
        )
        self.assertEqual(
            _normalize_character_chat_adjacent_opening_payload(
                wrong_branch_actor,
                expected_product_id=1182,
                expected_character_scope_key="character:아델리트",
                expected_read_episode_to=14,
            ),
            {},
        )
        self.assertEqual(
            _normalize_character_chat_adjacent_opening_payload(
                duplicate_branch,
                expected_product_id=1182,
                expected_character_scope_key="character:아델리트",
                expected_read_episode_to=14,
            ),
            {},
        )

    def test_session_memory_keeps_only_entry_context_for_the_same_read_boundary(self):
        matching = _normalize_websochat_session_memory(
            {
                "session_kind": "character_chat",
                "locked_character_scope_key": "character:아델리트",
                "read_episode_to": 14,
                "character_chat_entry_context": _entry_context(14),
            }
        )
        stale = _normalize_websochat_session_memory(
            {
                "session_kind": "character_chat",
                "locked_character_scope_key": "character:아델리트",
                "read_episode_to": 15,
                "character_chat_entry_context": _entry_context(14),
            }
        )

        self.assertEqual(
            matching["character_chat_entry_context"]["character_anchor_episode_no"],
            14,
        )
        self.assertEqual(stale["character_chat_entry_context"], {})

    def test_entry_context_validator_rejects_incomplete_or_future_material(self):
        incomplete = _entry_context(14)
        incomplete["recent_plot_rows"] = incomplete["recent_plot_rows"][:1]
        future = _entry_context(14)
        future["character_anchor_episode_no"] = 15
        invalid_source = _entry_context(14)
        invalid_source["character_scene_source"] = "unknown"

        self.assertFalse(_is_websochat_character_entry_context_v2(incomplete))
        self.assertFalse(_is_websochat_character_entry_context_v2(future))
        self.assertFalse(_is_websochat_character_entry_context_v2(invalid_source))
        self.assertFalse(
            _is_websochat_character_entry_context_v2(
                _entry_context(14),
                expected_product_id=1183,
            )
        )
        self.assertFalse(
            _is_websochat_character_entry_context_v2(
                _entry_context(14),
                expected_character_scope_key="character:다른인물",
            )
        )

    def test_character_chat_read_scope_cannot_decrease_in_same_session(self):
        with self.assertRaises(CustomResponseException) as captured:
            _assert_websochat_character_chat_read_scope_not_decreased(
                current_read_episode_to=20,
                next_read_episode_to=14,
            )

        self.assertEqual(captured.exception.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            captured.exception.code,
            "CHARACTER_CHAT_READ_SCOPE_DECREASE_REQUIRES_NEW_SESSION",
        )
        _assert_websochat_character_chat_read_scope_not_decreased(
            current_read_episode_to=14,
            next_read_episode_to=20,
        )

    def test_read_boundary_14_uses_only_13_and_14_and_excludes_15(self):
        current_scene = _character_scene("아델리트", gist="14화 현재 장면")
        current_scene["participants"].append(
            {
                "scope_key": "character:황제",
                "mention_label": "황제",
                "display_name": "황제",
            }
        )
        current_scene["scene_identity_boundary"]["allowed_address_names"] = [
            "아델리트",
            "폐하",
        ]
        context = _build_websochat_character_entry_context_v2(
            product_id=1182,
            read_episode_to=14,
            character_scope_keys=["character:아델리트"],
            plot_rows=[
                _plot_row(15, "15화 미래 사건"),
                _plot_row(14, "14화에서 아델리트가 협상을 끝낸다."),
                _plot_row(13, "13화에서 협상이 시작된다."),
                _plot_row(12, "12화 이전 사건"),
            ],
            scene_rows=[
                _scene_row(15, [_character_scene("아델리트", gist="15화 미래 장면")]),
                _scene_row(14, [current_scene]),
                _scene_row(13, [_character_scene("아델리트", gist="13화 직전 장면")]),
            ],
        )

        self.assertEqual(context["read_episode_to"], 14)
        self.assertEqual(context["recent_episode_from"], 13)
        self.assertEqual(context["recent_episode_to"], 14)
        self.assertEqual(
            [row["episode_no"] for row in context["recent_plot_rows"]],
            [13, 14],
        )
        self.assertEqual(context["character_anchor_episode_no"], 14)
        self.assertEqual(context["character_scene_source"], "matched_character")
        self.assertEqual(context["character_scene"]["scene_gist"], "14화 현재 장면")
        self.assertEqual(
            context["character_scene"]["turn_continuation_contract"]["scene_exit_condition"],
            "다음 경로를 정한다.",
        )
        self.assertEqual(
            context["character_scene"]["creative_grounding"]["sensory_anchors"],
            ["기름 냄새"],
        )
        self.assertEqual(
            context["character_scene"]["identity_safety"]["prior_scene_addressees"],
            ["폐하"],
        )
        serialized_context = json.dumps(context, ensure_ascii=False)
        self.assertNotIn("surface_role_for_user", serialized_context)
        self.assertNotIn("황제의 측근", serialized_context)
        self.assertNotIn("15화", json.dumps(context, ensure_ascii=False))

    def test_uses_latest_character_scene_when_character_is_absent_from_recent_boundary(self):
        context = _build_websochat_character_entry_context_v2(
            product_id=1182,
            read_episode_to=14,
            character_scope_keys=["character:아델리트"],
            plot_rows=[
                _plot_row(14, "14화의 작품 현재 상태"),
                _plot_row(13, "13화의 작품 현재 상태"),
            ],
            scene_rows=[
                _scene_row(14, [_character_scene("경비병")]),
                _scene_row(13, [_character_scene("경비병")]),
                _scene_row(9, [_character_scene("아델리트", gist="아델리트의 마지막 등장")]),
            ],
        )

        self.assertEqual(context["character_anchor_episode_no"], 9)
        self.assertEqual(context["character_scene_source"], "matched_character")
        self.assertEqual(context["character_scene"]["scene_gist"], "아델리트의 마지막 등장")
        self.assertEqual(
            [row["episode_no"] for row in context["recent_plot_rows"]],
            [13, 14],
        )

    def test_missing_exact_read_boundary_is_not_ready(self):
        context = _build_websochat_character_entry_context_v2(
            product_id=1182,
            read_episode_to=14,
            character_scope_keys=["character:아델리트"],
            plot_rows=[_plot_row(13, "13화까지만 준비됨")],
            scene_rows=[_scene_row(13, [_character_scene("아델리트")])],
        )

        self.assertEqual(context, {})

    def test_missing_character_scene_uses_latest_read_scope_scene(self):
        context = _build_websochat_character_entry_context_v2(
            product_id=1182,
            read_episode_to=14,
            character_scope_keys=["character:아델리트"],
            plot_rows=[_plot_row(14, "14화"), _plot_row(13, "13화")],
            scene_rows=[
                _scene_row(15, [_character_scene("상인", gist="15화 미래 장면")]),
                _scene_row(14, [_character_scene("경비병", gist="14화 작품 장면")]),
                _scene_row(13, [_character_scene("상인", gist="13화 작품 장면")]),
            ],
        )

        self.assertEqual(context["character_scene_source"], "read_scope_fallback")
        self.assertEqual(context["character_anchor_episode_no"], 14)
        self.assertEqual(context["character_scene"]["scene_gist"], "14화 작품 장면")
        self.assertNotIn("15화 미래 장면", json.dumps(context, ensure_ascii=False))

    def test_fallback_renderer_marks_work_scene_and_requires_if_character_join(self):
        context = _build_websochat_character_entry_context_v2(
            product_id=1182,
            read_episode_to=14,
            character_scope_keys=["character:아델리트"],
            plot_rows=[_plot_row(14, "14화"), _plot_row(13, "13화")],
            scene_rows=[_scene_row(14, [_character_scene("경비병", gist="경비병의 순찰 장면")])],
        )

        lines = _build_character_chat_entry_context_lines(context)
        rendered = "\n".join(lines)
        material = _build_character_chat_safe_scene_material(context)
        opening_prompt = _build_character_chat_adjacent_opening_prompt(
            product_row={"productId": 1182, "title": "테스트 작품"},
            rp_context={
                "active_character": "character:아델리트",
                "display_name": "아델리트",
                "speech_style": {},
                "examples": [],
                "character_chat_entry_context": context,
            },
        )

        self.assertIn("읽은 범위의 작품 장면 근거: 14화", rendered)
        self.assertIn("IF 곁가지로 새롭게 합류", rendered)
        self.assertIn("원래 있었다고 만들지 마라", rendered)
        self.assertNotIn("선택 캐릭터의 마지막 장면 근거", rendered)
        self.assertEqual(material["entry_strategy"], "read_scope_fallback_if_entry")
        self.assertIn("read_scope_fallback_scene", material)
        self.assertNotIn("selected_character_last_completed_scene", material)
        self.assertIn("선택 캐릭터가 원래 참여했다고 만들지 않는다", opening_prompt)
        self.assertIn("선택 캐릭터가 새로 합류하는 후보", opening_prompt)

    def test_entry_context_compacts_long_material_before_session_storage(self):
        long_scene = _character_scene("아델리트", gist="장" * 10000)
        context = _build_websochat_character_entry_context_v2(
            product_id=1182,
            read_episode_to=14,
            character_scope_keys=["character:아델리트"],
            plot_rows=[
                _plot_row(14, "요" * 10000),
                _plot_row(13, "약" * 10000),
            ],
            scene_rows=[_scene_row(14, [long_scene])],
        )

        self.assertTrue(context)
        self.assertLessEqual(len(context["recent_plot_rows"][0]["summary_text"]), 1600)
        self.assertLessEqual(len(context["character_scene"]["scene_gist"]), 800)
        self.assertLessEqual(
            len(json.dumps(context, ensure_ascii=False).encode("utf-8")),
            32000,
        )

    def test_prompt_prefers_read_boundary_context_over_static_opening_asset(self):
        prompt = build_websochat_rp_system_prompt(
            product_row={"title": "테스트 작품", "latestEpisodeNo": 30},
            rp_context={
                "display_name": "아델리트",
                "active_character": "character:아델리트",
                "rp_mode": "free",
                "speech_style": {},
                "personality_core": [],
                "examples": [
                    {
                        "episode_no": 13,
                        "text": "13화까지 확인된 말투 예시",
                        "confidence": 0.8,
                    },
                    {
                        "episode_no": 15,
                        "text": "15화 미래 말투 예시",
                        "confidence": 1.0,
                    },
                ],
                "internal_prompt": "아델리트의 말투를 유지한다.",
                "session_memory": {
                    "session_kind": "character_chat",
                    "locked_character_scope_key": "character:아델리트",
                    "allowed_modes": ["rp"],
                    "read_episode_to": 14,
                },
                "character_chat_opening": {
                    "opening_message": {"opening_text": "1화 도입부를 반복한다."},
                    "runtime_formula_seed": {"formula_type": "FORMULA_RESOURCE_BOOTSTRAP"},
                },
                "character_chat_entry_context": {
                    "schema_version": "character_chat_entry_context_v2",
                    "product_id": 1182,
                    "character_scope_key": "character:아델리트",
                    "read_episode_to": 14,
                    "recent_episode_from": 13,
                    "recent_episode_to": 14,
                    "recent_plot_rows": [
                        {"episode_no": 13, "summary_text": "협상이 시작된다."},
                        {"episode_no": 14, "summary_text": "협상이 끝나고 대가가 남는다."},
                    ],
                    "character_anchor_episode_no": 14,
                    "character_scene": {
                        "scene_gist": "아델리트가 협상의 결과를 확인한다.",
                        "current_action": "다음 약속을 정리한다.",
                    },
                },
            },
            recent_messages=[],
        )

        self.assertIn("[읽은 범위 진입점]", prompt)
        self.assertIn("13~14화", prompt)
        self.assertIn("14화가 끝난 상태", prompt)
        self.assertIn("선택 캐릭터의 마지막 장면 근거: 14화", prompt)
        self.assertNotIn("[캐릭터챗 오프닝 자산]", prompt)
        self.assertNotIn("FORMULA_RESOURCE_BOOTSTRAP", prompt)
        self.assertNotIn("1화 도입부를 반복한다", prompt)
        self.assertIn("13화까지 확인된 말투 예시", prompt)
        self.assertNotIn("15화 미래 말투 예시", prompt)
        self.assertIn("[첫 턴 최종 출력 계약]", prompt)
        self.assertIn("선택 캐릭터만 큰따옴표 대사를 말한다", prompt)
        self.assertIn("사용자를 원작의 기존 네임드 인물로 해석하지 마라", prompt)
        self.assertIn("직접 근거 장면을 이어 쓰거나 재연하지 마라", prompt)
        self.assertIn("새 곁가지 사건", prompt)

    def test_character_chat_never_falls_back_to_static_opening_asset(self):
        prompt = build_websochat_rp_system_prompt(
            product_row={"title": "테스트 작품", "latestEpisodeNo": 30},
            rp_context={
                "display_name": "아델리트",
                "internal_prompt": "아델리트의 말투를 유지한다.",
                "character_chat_opening": {
                    "opening_message": {"opening_text": "폐기된 1화 정적 오프닝"},
                },
                "character_chat_entry_context": {},
                "session_memory": {
                    "session_kind": "character_chat",
                    "locked_character_scope_key": "character:아델리트",
                    "read_episode_to": 14,
                },
            },
            recent_messages=[],
        )

        self.assertNotIn("[캐릭터챗 오프닝 자산]", prompt)
        self.assertNotIn("폐기된 1화 정적 오프닝", prompt)


class WebsochatCharacterEntryContextRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_loader_skips_fallback_query_when_exact_scene_is_ready(self):
        def result_for(rows: list[dict]) -> MagicMock:
            result = MagicMock()
            result.mappings.return_value.all.return_value = rows
            return result

        db = AsyncMock()
        db.execute.side_effect = [
            result_for([_plot_row(14, "14화"), _plot_row(13, "13화")]),
            result_for(
                [_scene_row(9, [_character_scene("아델리트", gist="정확 매칭 장면")])]
            ),
        ]

        context = await load_websochat_character_entry_context_v2(
            product_id=1182,
            read_episode_to=14,
            latest_episode_no=20,
            character_scope_keys=["character:아델리트"],
            db=db,
        )

        self.assertEqual(db.execute.await_count, 2)
        self.assertEqual(context["character_scene_source"], "matched_character")
        self.assertEqual(context["character_scene"]["scene_gist"], "정확 매칭 장면")

    async def test_loader_fetches_bounded_read_scope_scene_for_fallback(self):
        def result_for(rows: list[dict]) -> MagicMock:
            result = MagicMock()
            result.mappings.return_value.all.return_value = rows
            return result

        db = AsyncMock()
        db.execute.side_effect = [
            result_for([_plot_row(14, "14화"), _plot_row(13, "13화")]),
            result_for([]),
            result_for([_scene_row(14, [_character_scene("경비병", gist="14화 작품 장면")])]),
        ]

        context = await load_websochat_character_entry_context_v2(
            product_id=1182,
            read_episode_to=14,
            latest_episode_no=20,
            character_scope_keys=["character:아델리트"],
            db=db,
        )

        self.assertEqual(db.execute.await_count, 3)
        fallback_sql = str(db.execute.await_args_list[2].args[0])
        fallback_params = db.execute.await_args_list[2].args[1]
        self.assertIn("episode_to <= :read_episode_to", fallback_sql)
        self.assertIn("LIMIT :limit", fallback_sql)
        self.assertNotIn("INSTR(summary_text", fallback_sql)
        self.assertEqual(fallback_params["read_episode_to"], 14)
        self.assertEqual(context["character_scene_source"], "read_scope_fallback")
        self.assertEqual(context["character_scene"]["scene_gist"], "14화 작품 장면")

    async def test_adjacent_opening_generator_accepts_plain_text_response(self):
        entry_context = _entry_context(14)
        payload = {
            "schema_version": "character_chat_adjacent_opening_v1",
            "product_id": 1182,
            "character_scope_key": "character:아델리트",
            "read_episode_to": 14,
            "scene_plan": {
                "setting": "해 질 무렵 회랑",
                "continuity_from_boundary": "14화에서 협상이 끝난 뒤 남은 점검 일정",
                "freshness_from_completed_scene": "협상 상대 없이 외곽 장치를 점검한다.",
                "event_shape": "작업 절차의 우선순위 충돌",
                "inciting_event": "봉인 장치가 불규칙하게 울린다.",
                "character_first_move": "아델리트가 장치의 진동을 멈춘다.",
                "stakes": "잘못 열면 흔적이 지워진다.",
                "beats": ["이상 확인", "순서 결정", "작은 결과"],
                "decision_branch": {
                    "axis": "priority",
                    "user_decision": "흔적 보존과 즉시 확인 중 무엇을 우선할지 판단한다.",
                    "branch_a": {
                        "actor_scope_key": "character:아델리트",
                        "character_next_action": "아델리트가 장치를 봉인하고 흔적을 기록한다.",
                        "immediate_effect": "원인은 늦게 확인하지만 현재 흔적이 보존된다.",
                    },
                    "branch_b": {
                        "actor_scope_key": "character:아델리트",
                        "character_next_action": "아델리트가 덮개를 열고 소리의 근원을 확인한다.",
                        "immediate_effect": "흔적 일부를 잃을 수 있지만 원인을 즉시 좁힌다.",
                    },
                },
            },
            "opening_text": (
                "해 질 무렵의 회랑은 사람 소리가 끊겨 유난히 넓게 느껴졌다. 아델리트는 벽의 봉인 장치가 "
                "불규칙하게 떨리는 것을 발견하고 덮개 대신 바깥 고정쇠를 눌렀다. 금속음은 잦아들었지만 "
                "안쪽에서 가느다란 마찰음이 남았다. 그는 흔적이 지워지지 않도록 손을 떼고 표시를 비교했다. "
                "먼지는 고르게 쌓여 있었지만 고정쇠 하나만 미세하게 따뜻했다. 아델리트는 두 소리의 간격을 "
                "세다가, 어느 쪽부터 확인하느냐에 따라 남는 흔적이 달라진다는 듯 눈을 가늘게 떴다.\n\n"
                '"열기 전에 순서를 정해야 해. 흔적부터 남길지, 소리가 난 방향부터 확인할지 네 판단을 듣지."'
            ),
        }
        with patch(
            "app.services.websochat.websochat_rp_renderer.call_websochat_model",
            new_callable=AsyncMock,
            return_value=payload["opening_text"],
        ) as call_model:
            result = await generate_character_chat_adjacent_opening_with_gemini(
                product_row={"productId": 1182, "title": "테스트 작품"},
                rp_context={
                    "active_character": "character:아델리트",
                    "display_name": "아델리트",
                    "speech_style": {"tone": ["건조함"]},
                    "examples": [{"episode_no": 13, "text": "확인하고 움직여."}],
                    "character_chat_entry_context": entry_context,
                },
            )

        self.assertEqual(result["read_episode_to"], 14)
        self.assertIn("네 판단", result["opening_text"])
        self.assertFalse(call_model.await_args.kwargs["stream"])
        self.assertEqual(call_model.await_args.kwargs["messages"][0]["role"], "user")

    async def test_adjacent_opening_generator_retries_one_invalid_model_response(self):
        entry_context = _entry_context(14)
        payload = {
            "schema_version": "character_chat_adjacent_opening_v1",
            "product_id": 1182,
            "character_scope_key": "character:아델리트",
            "read_episode_to": 14,
            "scene_plan": {
                "setting": "해 질 무렵 회랑",
                "continuity_from_boundary": "협상이 끝난 직후",
                "freshness_from_completed_scene": "새 점검을 시작한다.",
                "event_shape": "우선순위",
                "inciting_event": "봉인 장치가 울린다.",
                "character_first_move": "아델리트가 장치를 살핀다.",
                "stakes": "확인 순서를 정해야 한다.",
                "beats": ["이상 확인", "순서 판단", "다음 행동"],
                "decision_branch": {
                    "axis": "priority",
                    "user_decision": "기록과 확인 중 무엇을 먼저 할지 판단한다.",
                    "branch_a": {
                        "actor_scope_key": "character:아델리트",
                        "character_next_action": "아델리트가 흔적을 기록한다.",
                        "immediate_effect": "현재 흔적이 남는다.",
                    },
                    "branch_b": {
                        "actor_scope_key": "character:아델리트",
                        "character_next_action": "아델리트가 덮개를 연다.",
                        "immediate_effect": "소리의 원인을 바로 확인한다.",
                    },
                },
            },
            "opening_text": (
                "해 질 무렵 회랑에는 긴 그림자가 드리워졌다. 아델리트는 벽면의 봉인 장치가 평소와 다른 "
                "간격으로 떨리는 것을 발견하고 고정쇠를 눌렀다. 금속음은 잠시 잦아들었지만 안쪽에서 더 가느다란 "
                "마찰음이 이어졌다. 그는 덮개를 바로 열지 않고 주변의 먼지와 표시를 차례로 비교했다. 손끝에 "
                "닿은 고정쇠 하나만 미세하게 따뜻했다. 아델리트는 흔적이 지워지지 않도록 손을 거둔 뒤, 소리가 "
                "반복되는 간격을 세며 다음 행동을 고를 준비를 마쳤다.\n\n"
                '"먼저 기록을 남길지, 지금 바로 안을 확인할지 정해. 판단을 들으면 내가 움직이지."'
            ),
        }
        with patch(
            "app.services.websochat.websochat_rp_renderer.call_websochat_model",
            new_callable=AsyncMock,
            side_effect=["not-json", json.dumps(payload, ensure_ascii=False)],
        ) as call_model:
            result = await generate_character_chat_adjacent_opening_with_gemini(
                product_row={"productId": 1182, "title": "테스트 작품"},
                rp_context={
                    "active_character": "character:아델리트",
                    "display_name": "아델리트",
                    "character_chat_entry_context": entry_context,
                },
            )

        self.assertEqual(result["opening_text"], payload["opening_text"])
        self.assertEqual(call_model.await_count, 2)

    async def test_character_chat_session_creation_preserves_requested_read_boundary_and_falls_back_when_missing(
        self,
    ):
        req_body = PostWebsochatSessionReqBody(
            product_id=1182,
            session_kind="character_chat",
            entry_source="home_character_slot",
            locked_character_scope_key="character:아델리트",
            account_read_episode_to=14,
            model_key="deep",
        )
        product_row = {
            "productId": 1182,
            "title": "테스트 작품",
            "latestEpisodeNo": 14,
            "publishedLatestEpisodeNo": 14,
            "syncedLatestEpisodeNo": 14,
            "contextStatus": "ready",
            "characterChatEligible": True,
        }
        session_memory = {
            "session_kind": "character_chat",
            "entry_source": "home_character_slot",
            "locked_character_scope_key": "character:아델리트",
            "allowed_modes": ["rp"],
            "active_mode": "rp",
            "active_character": "character:아델리트",
            "rp_mode": "free",
            "read_episode_to": 7,
            "read_scope_state": "known",
            "character_chat_entry_context": _entry_context(7),
            "selected_model_key": "deep",
        }
        opening = {"opening_text": "아델리트가 먼저 움직였다.\n\n\"이제 시작하지.\""}
        db = AsyncMock()
        db.execute.return_value.lastrowid = 77

        with (
            patch.object(websochat_service, "_resolve_actor", new_callable=AsyncMock) as resolve_actor,
            patch.object(
                websochat_service,
                "_resolve_effective_adult_yn",
                new_callable=AsyncMock,
            ) as resolve_adult,
            patch.object(
                websochat_service,
                "_get_websochat_product",
                new_callable=AsyncMock,
            ) as get_product,
            patch.object(websochat_service, "_assert_websochat_product_context_available"),
            patch.object(
                websochat_service,
                "_get_websochat_authorized_read_scope",
                new_callable=AsyncMock,
            ) as get_authorized_scope,
            patch.object(
                websochat_service,
                "_get_websochat_latest_read_episode_no",
                new_callable=AsyncMock,
            ) as get_latest_read_episode_no,
            patch.object(
                websochat_service,
                "_resolve_websochat_active_character_resolution",
                new_callable=AsyncMock,
            ) as resolve_character,
            patch.object(
                websochat_service,
                "_apply_websochat_account_read_scope",
                new_callable=AsyncMock,
            ) as apply_read_scope,
            patch.object(
                websochat_service,
                "_ensure_websochat_character_chat_entry_context",
                new_callable=AsyncMock,
            ) as ensure_entry_context,
            patch.object(
                websochat_service,
                "_load_websochat_rp_context",
                new_callable=AsyncMock,
            ) as load_rp_context,
            patch.object(
                websochat_service,
                "generate_character_chat_adjacent_opening_with_gemini",
                new_callable=AsyncMock,
            ) as generate_opening,
            patch.object(
                websochat_service,
                "_insert_websochat_assistant_message",
                new_callable=AsyncMock,
            ) as insert_opening,
        ):
            resolve_actor.return_value = (200, None)
            resolve_adult.return_value = "N"
            get_product.return_value = product_row
            get_authorized_scope.return_value = {
                "maxAuthorizedEpisodeTo": 14,
                "authorizedReadEpisodeTo": 14,
            }
            get_latest_read_episode_no.return_value = 7
            resolve_character.return_value = {
                "scopeKey": "character:아델리트",
                "displayName": "아델리트",
            }
            apply_read_scope.return_value = session_memory
            ensure_entry_context.return_value = session_memory
            load_rp_context.return_value = {
                "active_character": "character:아델리트",
                "character_chat_entry_context": _entry_context(7),
            }
            generate_opening.return_value = opening

            result = await websochat_service.create_session(
                req_body=req_body,
                kc_user_id="kc-user",
                adult_yn="N",
                db=db,
            )

            apply_read_scope.assert_awaited_once_with(
                ANY,
                14,
                product_id=1182,
                user_id=200,
                synced_latest_episode_no=14,
                db=db,
            )
            get_latest_read_episode_no.assert_not_awaited()

            apply_read_scope.reset_mock()
            get_latest_read_episode_no.reset_mock()
            generate_opening.reset_mock()
            insert_opening.reset_mock()
            await websochat_service.create_session(
                req_body=req_body.model_copy(
                    update={"account_read_episode_to": None},
                ),
                kc_user_id="kc-user",
                adult_yn="N",
                db=db,
            )

        self.assertEqual(result["data"]["sessionId"], 77)
        self.assertEqual(result["data"]["selectedModelKey"], "deep")
        create_params = db.execute.await_args_list[0].args[1]
        self.assertEqual(
            json.loads(create_params["session_memory_json"])["selected_model_key"],
            "deep",
        )
        apply_read_scope.assert_awaited_once_with(
            ANY,
            7,
            product_id=1182,
            user_id=200,
            synced_latest_episode_no=14,
            db=db,
        )
        get_latest_read_episode_no.assert_awaited_once_with(
            product_id=1182,
            user_id=200,
            db=db,
        )
        generate_opening.assert_awaited_once_with(
            product_row=product_row,
            rp_context=load_rp_context.return_value,
            model_key="speed",
        )
        insert_opening.assert_awaited_once_with(
            session_id=77,
            content=opening["opening_text"],
            db=db,
        )

    def test_character_chat_missing_boundary_uses_episode_one_without_affecting_websochat(self):
        resolver = websochat_service._resolve_websochat_initial_account_read_episode_to

        assert resolver(
            session_kind="character_chat",
            requested_episode_to=None,
        ) == 1
        assert resolver(
            session_kind="character_chat",
            requested_episode_to=None,
        ) == 1
        assert resolver(
            session_kind="character_chat",
            requested_episode_to=5,
        ) == 5
        assert resolver(
            session_kind="websochat",
            requested_episode_to=None,
        ) is None
        assert resolver(
            session_kind="websochat",
            requested_episode_to=5,
        ) == 5
        assert resolver(
            session_kind="character_chat",
            requested_episode_to=5,
        ) == 5

    async def test_character_chat_patch_rejects_requested_lower_read_boundary(self):
        req_body = PatchWebsochatSessionReadScopeReqBody(read_episode_to=14)

        with (
            patch.object(websochat_service, "_resolve_actor", new_callable=AsyncMock) as resolve_actor,
            patch.object(websochat_service, "_get_session_row", new_callable=AsyncMock) as get_session_row,
            patch.object(
                websochat_service,
                "_resolve_effective_adult_yn",
                new_callable=AsyncMock,
            ) as resolve_adult,
            patch.object(
                websochat_service,
                "_get_websochat_product_session_state",
                new_callable=AsyncMock,
            ) as get_product_state,
            patch.object(
                websochat_service,
                "_get_websochat_authorized_read_scope",
                new_callable=AsyncMock,
            ) as get_authorized_scope,
            patch.object(
                websochat_service,
                "_get_websochat_visible_episode_title",
                new_callable=AsyncMock,
                return_value="20화",
            ),
        ):
            resolve_actor.return_value = (200, None)
            get_session_row.return_value = {
                "product_id": 1182,
                "session_memory_json": {
                    "session_kind": "character_chat",
                    "locked_character_scope_key": "character:아델리트",
                    "allowed_modes": ["rp"],
                    "read_episode_to": 20,
                    "read_scope_state": "known",
                    "read_scope_source": "viewer",
                    "character_chat_entry_context": _entry_context(20),
                },
            }
            resolve_adult.return_value = "Y"
            get_product_state.return_value = {
                "canSendMessage": True,
                "latestEpisodeNo": 30,
                "syncedLatestEpisodeNo": 30,
            }
            get_authorized_scope.side_effect = [
                {
                    "authorizedReadEpisodeTo": 20,
                    "maxAuthorizedEpisodeTo": 30,
                },
                {
                    "authorizedReadEpisodeTo": 14,
                    "maxAuthorizedEpisodeTo": 30,
                },
            ]

            with self.assertRaises(CustomResponseException) as captured:
                await websochat_service.patch_session_read_scope(
                    session_id=10,
                    req_body=req_body,
                    kc_user_id="kc-user",
                    db=object(),
                )

        self.assertEqual(captured.exception.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            captured.exception.code,
            "CHARACTER_CHAT_READ_SCOPE_DECREASE_REQUIRES_NEW_SESSION",
        )

    async def test_matching_boundary_reuses_existing_entry_without_query(self):
        with patch(
            "app.services.websochat.websochat_service.load_websochat_character_entry_context_v2",
            new_callable=AsyncMock,
        ) as load_entry:
            memory = await _ensure_websochat_character_chat_entry_context(
                session_memory={
                    "session_kind": "character_chat",
                    "locked_character_scope_key": "character:아델리트",
                    "active_character": "character:아델리트",
                    "read_episode_to": 14,
                    "character_chat_entry_context": _entry_context(14),
                },
                product_id=1182,
                latest_episode_no=30,
                resolved_active_character="character:아델리트",
                resolution={"scopeKey": "character:아델리트"},
                db=object(),
            )

        load_entry.assert_not_awaited()
        self.assertEqual(memory["character_chat_entry_context"]["read_episode_to"], 14)

    async def test_changed_boundary_rebuilds_entry_context(self):
        rebuilt = _entry_context(15)
        with patch(
            "app.services.websochat.websochat_service.load_websochat_character_entry_context_v2",
            new_callable=AsyncMock,
            return_value=rebuilt,
        ) as load_entry:
            memory = await _ensure_websochat_character_chat_entry_context(
                session_memory={
                    "session_kind": "character_chat",
                    "locked_character_scope_key": "character:아델리트",
                    "active_character": "character:아델리트",
                    "read_episode_to": 15,
                    "character_chat_entry_context": _entry_context(14),
                },
                product_id=1182,
                latest_episode_no=30,
                resolved_active_character="character:아델리트",
                resolution={"scopeKey": "character:아델리트"},
                db=object(),
            )

        load_entry.assert_awaited_once()
        self.assertEqual(memory["character_chat_entry_context"], rebuilt)

    async def test_same_boundary_rebuilds_context_for_different_character(self):
        rebuilt = _entry_context(
            14,
            character_scope_key="character:다른인물",
        )
        with patch(
            "app.services.websochat.websochat_service.load_websochat_character_entry_context_v2",
            new_callable=AsyncMock,
            return_value=rebuilt,
        ) as load_entry:
            memory = await _ensure_websochat_character_chat_entry_context(
                session_memory={
                    "session_kind": "character_chat",
                    "locked_character_scope_key": "character:다른인물",
                    "active_character": "character:다른인물",
                    "read_episode_to": 14,
                    "character_chat_entry_context": _entry_context(14),
                },
                product_id=1182,
                latest_episode_no=30,
                resolved_active_character="character:다른인물",
                resolution={"scopeKey": "character:다른인물"},
                db=object(),
            )

        load_entry.assert_awaited_once()
        self.assertEqual(memory["character_chat_entry_context"], rebuilt)

    async def test_canonical_identity_change_updates_locked_character(self):
        rebuilt = _entry_context(
            14,
            character_scope_key="character:아델리트",
        )
        with patch(
            "app.services.websochat.websochat_service.load_websochat_character_entry_context_v2",
            new_callable=AsyncMock,
            return_value=rebuilt,
        ) as load_entry:
            memory = await _ensure_websochat_character_chat_entry_context(
                session_memory={
                    "session_kind": "character_chat",
                    "locked_character_scope_key": "protagonist:named:아델리트",
                    "active_character": "protagonist:named:아델리트",
                    "read_episode_to": 14,
                    "character_chat_entry_context": _entry_context(
                        14,
                        character_scope_key="protagonist:named:아델리트",
                    ),
                },
                product_id=1182,
                latest_episode_no=30,
                resolved_active_character="character:아델리트",
                resolution={"scopeKey": "character:아델리트"},
                db=object(),
            )

        load_entry.assert_awaited_once()
        self.assertEqual(memory["locked_character_scope_key"], "character:아델리트")
        self.assertEqual(memory["active_character"], "character:아델리트")
        self.assertEqual(memory["character_chat_entry_context"], rebuilt)

    async def test_changed_boundary_blocks_when_entry_cannot_be_rebuilt(self):
        with patch(
            "app.services.websochat.websochat_service.load_websochat_character_entry_context_v2",
            new_callable=AsyncMock,
            return_value={},
        ):
            with self.assertRaises(CustomResponseException) as captured:
                await _ensure_websochat_character_chat_entry_context(
                    session_memory={
                        "session_kind": "character_chat",
                        "locked_character_scope_key": "character:아델리트",
                        "active_character": "character:아델리트",
                        "read_episode_to": 15,
                        "character_chat_entry_context": _entry_context(14),
                    },
                    product_id=1182,
                    latest_episode_no=30,
                    resolved_active_character="character:아델리트",
                    resolution={"scopeKey": "character:아델리트"},
                    db=object(),
                )

        self.assertEqual(captured.exception.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(captured.exception.code, "CHARACTER_CHAT_ENTRY_NOT_READY")


if __name__ == "__main__":
    unittest.main()
