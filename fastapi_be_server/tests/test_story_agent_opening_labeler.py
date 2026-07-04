import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import httpx


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
MODULE_PATH = SCRIPT_DIR / "run_character_chat_opening_labeler.py"


def load_module():
    module_name = "run_character_chat_opening_labeler_under_test"
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def ready_payload():
    return {
        "readiness": {"status": "ready", "confidence": 0.82, "block_reasons": []},
        "work_opening": {
            "premise": "아델리트는 폐허 안쪽에서 추격자를 따돌려야 한다.",
            "opening_hook_type": "위기",
            "spoiler_boundary": "1~3화 안에서 드러난 추격과 탈출 상황까지만 사용",
        },
        "chat_target": {
            "display_name": "아델리트",
            "aliases": [],
            "role": "주인공",
            "protagonist_likelihood": 0.91,
            "chat_target_likelihood": 0.89,
            "evidence": ["아델리트 시점과 대사가 반복된다."],
        },
        "identity_resolution": {
            "identity_mode": "ordinary",
            "current_display_name": "아델리트",
            "pre_transfer_name": None,
            "host_or_avatar_name": None,
            "public_opening_name": "아델리트",
            "identity_spoiler_risk": "low",
            "name_use_rule": "첫 장면에서는 아델리트라고 불러도 된다.",
        },
        "opening_scene": {
            "time": "밤",
            "place": "폐허",
            "situation": "아델리트가 추격을 피해 폐허 안쪽으로 들어선다.",
            "immediate_conflict": "추격자가 근처까지 접근했다.",
            "props_or_anchors": ["폐허", "무너진 벽"],
            "nearby_characters": ["추격자"],
        },
        "user_role": {
            "role_type": "임시 조력자",
            "relationship_to_character": "방금 같은 장소에 휘말린 조력자",
            "scene_entry_reason": "유저는 폐허 안쪽 통로에서 아델리트와 마주쳤다.",
            "first_turn_affordance": "숨을 곳을 가리키거나 추격자의 위치를 알려줄 수 있다.",
            "user_knows": ["추격자가 가까이 있다."],
            "user_must_not_know": ["아델리트의 숨겨진 과거"],
            "allowed_assumptions": ["유저는 현장에 있다."],
            "forbidden_assumptions": ["유저는 원작의 절친이다."],
        },
        "character_drive": {"immediate_objective": "추격자를 따돌리고 탈출로를 찾는다."},
        "agency_contract": {
            "character_moves_first": True,
            "move_style": "도주 유도",
            "non_user_dependent_action": "유저가 침묵해도 아델리트가 먼저 무너진 벽 뒤로 이동한다.",
            "decision_character_must_make": "지금 숨을지, 더 깊은 통로로 뛰어들지 결정해야 한다.",
            "user_influence_boundary": "유저는 방향과 단서를 제안할 수 있지만 탈출 결정을 대신하지 않는다.",
        },
        "progression_engine": {
            "short_term_goal": "추격자를 피해 폐허 안쪽 은신처까지 이동한다.",
            "mid_term_escalation": "추격자가 폐허의 다른 입구를 막아 우회로를 찾아야 한다.",
            "long_term_complication": "안전해 보이던 통로가 더 큰 위험과 연결된다.",
            "scene_exit_condition": "추격자의 시야를 벗어나 다음 은신 지점에 도착한다.",
            "event_injection_rules": [
                {
                    "when": "유저가 3턴 이상 망설인다",
                    "inject": "추격자의 발소리가 바로 뒤에서 커진다.",
                    "must_not_repeat": "정체 추궁 반복",
                },
                {
                    "when": "유저가 지켜보기만 한다",
                    "inject": "아델리트가 먼저 손목을 잡고 벽 뒤로 끌어당긴다.",
                    "must_not_repeat": "같은 도주 지시 반복",
                },
            ],
        },
        "user_affordance_contract": {
            "primary_affordances": ["관찰", "판단", "정보 제공"],
            "forbidden_agency_load": ["유저가 단독으로 추격자를 제압함", "유저가 탈출 임무를 주도함"],
            "safe_response_examples": ["오른쪽 통로의 발소리를 알린다", "숨을 수 있는 틈을 가리킨다"],
            "bad_response_pressure_to_avoid": ["네가 직접 싸워", "네가 먼저 나가서 확인해"],
        },
        "canon_safe_expansion": {
            "safe_new_event_pattern": "폐허의 좁은 통로와 추격 압박을 변주한 소규모 도주 사건",
            "allowed_inventions": ["짧은 발소리", "무너진 돌조각", "근처의 어두운 틈"],
            "forbidden_inventions": ["미등장 세력명", "미래 사건 결말", "새 능력 체계"],
            "must_preserve_facts": ["아델리트는 추격을 피해야 한다", "폐허 안쪽이 현재 장면이다"],
        },
        "voice_style": {"speech_level": "반말"},
        "relationship_stance": {
            "initial_trust": "낮음",
            "power_distance": "대등",
            "warmth": "중립",
            "volatility": "중간",
        },
        "evidence_quality": {
            "target_name_evidence": "direct_name",
            "voice_evidence": "dialogue",
            "scene_anchor_evidence": "direct",
            "input_truncated": False,
        },
        "progression": {
            "opening_greeting_intent": "유저에게 조용히 따라오라고 압박한다.",
            "next_beats": [
                {"beat": "탈출로 확인", "trigger": "유저가 협조한다", "avoid_repeating": "같은 경고 반복"},
                {"beat": "추격자 접근", "trigger": "유저가 망설인다", "avoid_repeating": "정체 추궁 반복"},
            ],
        },
    }


class StoryAgentOpeningLabelerTest(unittest.TestCase):
    def test_validate_ready_payload_requires_chat_runtime_fields(self):
        module = load_module()
        schema_pass, issues = module.validate_label_payload(ready_payload())

        self.assertTrue(schema_pass)
        self.assertEqual(issues, [])

    def test_validate_ready_payload_rejects_thin_ready_label(self):
        module = load_module()
        payload = ready_payload()
        payload["progression"]["next_beats"] = []
        payload["opening_scene"]["situation"] = ""

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_missing_scene", issues)
        self.assertIn("ready_needs_at_least_two_next_beats", issues)

    def test_validate_ready_payload_rejects_unspecified_user_role(self):
        module = load_module()
        payload = ready_payload()
        payload["user_role"]["role_type"] = "불명"

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_user_role_unspecified", issues)

    def test_validate_ready_payload_rejects_invalid_user_role_enum(self):
        module = load_module()
        payload = ready_payload()
        payload["user_role"]["role_type"] = "시청자"

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("invalid_user_role_type", issues)

    def test_validate_ready_payload_rejects_transfer_hook_without_identity(self):
        module = load_module()
        payload = ready_payload()
        payload["work_opening"]["opening_hook_type"] = "빙의"
        payload["identity_resolution"]["identity_mode"] = "unknown"
        payload["identity_resolution"]["name_use_rule"] = ""

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_transfer_identity_unknown", issues)
        self.assertIn("ready_missing_name_use_rule", issues)

    def test_validate_ready_payload_accepts_body_double_identity(self):
        module = load_module()
        payload = ready_payload()
        payload["work_opening"]["opening_hook_type"] = "대역"
        payload["identity_resolution"]["identity_mode"] = "body_double_or_disguise"
        payload["identity_resolution"]["name_use_rule"] = "공개 장면에서는 대역 신분의 이름만 쓴다."

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertTrue(schema_pass)
        self.assertEqual(issues, [])

    def test_validate_ready_payload_rejects_body_double_as_possession(self):
        module = load_module()
        payload = ready_payload()
        payload["work_opening"]["opening_hook_type"] = "대역"
        payload["identity_resolution"]["identity_mode"] = "possession_host_body"

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_body_double_identity_mismatch", issues)

    def test_validate_ready_payload_rejects_target_identity_mismatch(self):
        module = load_module()
        payload = ready_payload()
        payload["chat_target"]["display_name"] = "김하연"
        payload["chat_target"]["aliases"] = ["하연퀸"]
        payload["identity_resolution"]["current_display_name"] = "김검성"
        payload["identity_resolution"]["public_opening_name"] = "김검성"
        payload["identity_resolution"]["host_or_avatar_name"] = None

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_identity_target_name_mismatch", issues)

    def test_validate_ready_payload_rejects_user_role_starting_with_canon_character(self):
        module = load_module()
        payload = ready_payload()
        payload["opening_scene"]["nearby_characters"] = ["채이레", "담당 매니저"]
        payload["user_role"]["scene_entry_reason"] = "채이레가 아델리트와 약속 장소에서 만났거나 새 지인으로 합류했다."

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_user_role_uses_canon_character_subject", issues)

    def test_validate_ready_payload_allows_canon_character_sending_user(self):
        module = load_module()
        payload = ready_payload()
        payload["opening_scene"]["nearby_characters"] = ["감호위", "정석우"]
        payload["user_role"]["scene_entry_reason"] = "감호위가 아델리트의 상태를 확인하라고 유저를 파견했다."

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertTrue(schema_pass)
        self.assertEqual(issues, [])

    def test_validate_ready_payload_rejects_user_as_specific_canon_group_member(self):
        module = load_module()
        payload = ready_payload()
        payload["opening_scene"]["nearby_characters"] = ["토끼 부부"]
        payload["user_role"]["scene_entry_reason"] = "유저는 동굴에 들어온 토끼 부부 중 하나이다."

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_user_role_as_canon_group_member", issues)

    def test_validate_ready_payload_rejects_user_as_original_party_member(self):
        module = load_module()
        payload = ready_payload()
        payload["user_role"]["scene_entry_reason"] = "유저는 원작 파티 멤버 중 하나로 현장에 있었다."

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_user_role_as_canon_group_member", issues)

    def test_validate_ready_payload_allows_generic_group_member_user(self):
        module = load_module()
        payload = ready_payload()
        payload["opening_scene"]["nearby_characters"] = ["학생들"]
        payload["user_role"]["scene_entry_reason"] = "유저는 같은 아카데미 학생 중 하나로 현장에 있었다."

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertTrue(schema_pass)
        self.assertEqual(issues, [])

    def test_validate_ready_payload_rejects_weak_target_role(self):
        module = load_module()
        payload = ready_payload()
        payload["chat_target"]["role"] = "기타"

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_chat_target_role_too_weak", issues)

    def test_validate_ready_payload_rejects_non_direct_target_name_evidence(self):
        module = load_module()
        payload = ready_payload()
        payload["evidence_quality"]["target_name_evidence"] = "role_only"

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_target_name_evidence_not_direct", issues)

    def test_validate_ready_payload_rejects_narration_only_voice_evidence(self):
        module = load_module()
        payload = ready_payload()
        payload["evidence_quality"]["voice_evidence"] = "narration_only"

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_voice_evidence_not_dialogue", issues)

    def test_validate_ready_payload_rejects_role_label_display_name(self):
        module = load_module()
        payload = ready_payload()
        payload["chat_target"]["display_name"] = "주인공"
        payload["identity_resolution"]["current_display_name"] = "주인공"
        payload["identity_resolution"]["public_opening_name"] = "주인공"

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_display_name_is_role_label", issues)

    def test_validate_ready_payload_rejects_role_label_public_opening_name(self):
        module = load_module()
        payload = ready_payload()
        payload["identity_resolution"]["public_opening_name"] = "당신"

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_public_opening_name_is_role_label", issues)

    def test_validate_ready_payload_rejects_hook_identity_mismatch(self):
        module = load_module()
        payload = ready_payload()
        payload["work_opening"]["opening_hook_type"] = "회귀"
        payload["identity_resolution"]["identity_mode"] = "reincarnation_new_body"

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_hook_identity_mismatch", issues)

    def test_validate_ready_payload_allows_broad_otherworld_identity_modes(self):
        module = load_module()
        payload = ready_payload()
        payload["work_opening"]["opening_hook_type"] = "전이/이세계"
        payload["identity_resolution"]["identity_mode"] = "reincarnation_new_body"
        payload["identity_resolution"]["name_use_rule"] = "현재 세계 이름을 쓴다."

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertTrue(schema_pass)
        self.assertEqual(issues, [])

    def test_validate_ready_payload_allows_contract_opening_hook(self):
        module = load_module()
        payload = ready_payload()
        payload["work_opening"]["opening_hook_type"] = "계약"

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertTrue(schema_pass)
        self.assertEqual(issues, [])

    def test_validate_ready_payload_allows_retirement_opening_hook(self):
        module = load_module()
        payload = ready_payload()
        payload["work_opening"]["opening_hook_type"] = "은퇴"

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertTrue(schema_pass)
        self.assertEqual(issues, [])

    def test_derive_effective_readiness_downgrades_schema_failed_ready(self):
        module = load_module()
        payload = ready_payload()
        payload["evidence_quality"]["target_name_evidence"] = "role_only"
        schema_pass, issues = module.validate_label_payload(payload)

        effective_status, effective_reasons = module.derive_effective_readiness(
            payload,
            schema_pass=schema_pass,
            schema_issues=issues,
        )

        self.assertFalse(schema_pass)
        self.assertEqual(effective_status, "not_ready")
        self.assertIn("ready_target_name_evidence_not_direct", effective_reasons)

    def test_derive_effective_readiness_marks_hook_mismatch_for_review(self):
        module = load_module()
        payload = ready_payload()
        payload["work_opening"]["opening_hook_type"] = "회귀"
        payload["identity_resolution"]["identity_mode"] = "ordinary"
        schema_pass, issues = module.validate_label_payload(payload)

        effective_status, effective_reasons = module.derive_effective_readiness(
            payload,
            schema_pass=schema_pass,
            schema_issues=issues,
        )

        self.assertFalse(schema_pass)
        self.assertEqual(effective_status, "needs_review")
        self.assertEqual(effective_reasons, ["ready_hook_identity_mismatch"])

    def test_validate_ready_payload_requires_agency_contract(self):
        module = load_module()
        payload = ready_payload()
        payload["agency_contract"]["non_user_dependent_action"] = ""
        payload["agency_contract"]["user_influence_boundary"] = ""

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_missing_non_user_dependent_action", issues)
        self.assertIn("ready_missing_user_influence_boundary", issues)

    def test_validate_ready_payload_requires_progression_engine(self):
        module = load_module()
        payload = ready_payload()
        payload["progression_engine"]["scene_exit_condition"] = ""
        payload["progression_engine"]["event_injection_rules"] = [
            {"when": "유저가 침묵한다", "inject": "발소리가 가까워진다", "must_not_repeat": "정체 추궁 반복"}
        ]

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_missing_scene_exit_condition", issues)
        self.assertIn("ready_needs_at_least_two_event_injection_rules", issues)

    def test_validate_ready_payload_requires_user_affordance_contract(self):
        module = load_module()
        payload = ready_payload()
        payload["user_affordance_contract"]["forbidden_agency_load"] = []
        payload["user_affordance_contract"]["safe_response_examples"] = ["숨을 곳을 가리킨다"]

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_missing_forbidden_agency_load", issues)
        self.assertIn("ready_needs_at_least_two_safe_response_examples", issues)

    def test_validate_ready_payload_rejects_blank_safe_response_examples(self):
        module = load_module()
        payload = ready_payload()
        payload["user_affordance_contract"]["safe_response_examples"] = ["", "   "]

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_needs_at_least_two_safe_response_examples", issues)

    def test_validate_ready_payload_requires_canon_safe_expansion(self):
        module = load_module()
        payload = ready_payload()
        payload["canon_safe_expansion"]["safe_new_event_pattern"] = ""
        payload["canon_safe_expansion"]["forbidden_inventions"] = []

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_missing_safe_new_event_pattern", issues)
        self.assertIn("ready_missing_forbidden_inventions", issues)

    def test_validate_ready_payload_requires_entry_affordance(self):
        module = load_module()
        payload = ready_payload()
        payload["user_role"]["scene_entry_reason"] = ""
        payload["user_role"]["first_turn_affordance"] = ""

        schema_pass, issues = module.validate_label_payload(payload)

        self.assertFalse(schema_pass)
        self.assertIn("ready_missing_scene_entry_reason", issues)
        self.assertIn("ready_missing_first_turn_affordance", issues)

    def test_validate_not_ready_requires_block_reason(self):
        module = load_module()
        schema_pass, issues = module.validate_label_payload(
            {"readiness": {"status": "not_ready", "block_reasons": []}}
        )

        self.assertFalse(schema_pass)
        self.assertIn("not_ready_missing_block_reasons", issues)

    def test_load_input_rows_and_prompt_for_dry_run_surface(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.jsonl"
            row = {
                "fileName": "sample.txt",
                "splitConfidence": "high",
                "llmLabelingBucket": "main",
                "episodes": [
                    {
                        "episodeNo": 1,
                        "title": "첫 사건",
                        "headerPattern": "n_hwa",
                        "textChars": 1200,
                        "labelTextTruncated": True,
                        "labelText": "1화 첫 사건\n본문",
                    }
                ],
            }
            input_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

            rows = module.load_input_rows(input_path, limit=1)
            prompt = module.build_user_prompt(rows[0])

        self.assertEqual(len(rows), 1)
        self.assertIn("sample.txt", prompt)
        self.assertIn("1화 첫 사건", prompt)
        self.assertIn("split_confidence: high", prompt)
        self.assertIn("label_text_truncated: True", prompt)

    def test_load_input_rows_supports_offset_for_chunked_runs(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.jsonl"
            input_path.write_text(
                "\n".join(
                    json.dumps({"fileName": f"sample-{index}.txt"}, ensure_ascii=False)
                    for index in range(5)
                )
                + "\n",
                encoding="utf-8",
            )

            rows = module.load_input_rows(input_path, limit=2, offset=3)

        self.assertEqual([row["fileName"] for row in rows], ["sample-3.txt", "sample-4.txt"])

    def test_resume_helpers_skip_only_completed_when_retry_failed(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "labels.jsonl"
            output_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {"fileName": "ok.txt", "status": "ok", "schemaPass": True},
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {"fileName": "timeout.txt", "status": "timeout", "error": "call exceeded"},
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {"fileName": "schema.txt", "status": "ok", "schemaPass": False},
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            existing = module.load_existing_results(output_path)

        self.assertEqual(set(existing), {"ok.txt", "timeout.txt", "schema.txt"})
        self.assertTrue(module.should_skip_existing_result(existing["ok.txt"], retry_failed=False))
        self.assertTrue(module.should_skip_existing_result(existing["timeout.txt"], retry_failed=False))
        self.assertTrue(module.should_skip_existing_result(existing["ok.txt"], retry_failed=True))
        self.assertFalse(module.should_skip_existing_result(existing["timeout.txt"], retry_failed=True))
        self.assertFalse(module.should_skip_existing_result(existing["schema.txt"], retry_failed=True))

    def test_openrouter_payment_required_detection_is_402_only(self):
        module = load_module()
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        payment_error = httpx.HTTPStatusError(
            "Client error '402 Payment Required'",
            request=request,
            response=httpx.Response(402, request=request),
        )
        server_error = httpx.HTTPStatusError(
            "Server error '500 Internal Server Error'",
            request=request,
            response=httpx.Response(500, request=request),
        )

        self.assertTrue(module.is_openrouter_payment_required(payment_error))
        self.assertFalse(module.is_openrouter_payment_required(server_error))
        self.assertFalse(module.is_openrouter_payment_required(RuntimeError("boom")))

    def test_load_env_file_reads_key_values_without_shell_execution(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "OPENROUTER_API_KEY='test-key'",
                        "BAD-NAME=should_skip",
                        "ntfm command that would fail if sourced",
                    ]
                ),
                encoding="utf-8",
            )
            old_value = os.environ.pop("OPENROUTER_API_KEY", None)
            try:
                loaded = module.load_env_file(env_path)
                value = os.environ.get("OPENROUTER_API_KEY")
            finally:
                os.environ.pop("OPENROUTER_API_KEY", None)
                if old_value is not None:
                    os.environ["OPENROUTER_API_KEY"] = old_value

        self.assertEqual(loaded, ["OPENROUTER_API_KEY"])
        self.assertEqual(value, "test-key")
        self.assertNotIn("BAD-NAME", os.environ)

    def test_wall_clock_timeout_raises_timeout_error(self):
        module = load_module()

        with self.assertRaises(module.LabelCallTimeoutError):
            with module.wall_clock_timeout(0.01):
                time.sleep(0.05)


if __name__ == "__main__":
    unittest.main()
