import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
MODULE_PATH = SCRIPT_DIR / "summarize_character_chat_opening_labels.py"


def load_module():
    module_name = "summarize_character_chat_opening_labels_under_test"
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def ready_label(*, user_role_type: str = "동행자"):
    return {
        "readiness": {"status": "ready", "confidence": 0.9, "block_reasons": []},
        "work_opening": {
            "premise": "주인공은 첫 사건 현장에서 결정을 내려야 한다.",
            "opening_hook_type": "위기",
            "spoiler_boundary": "1~3화의 첫 사건만 사용",
        },
        "chat_target": {
            "display_name": "테스트 주인공",
            "aliases": [],
            "role": "주인공",
            "protagonist_likelihood": 0.9,
            "chat_target_likelihood": 0.9,
            "evidence": ["주인공 시점"],
        },
        "identity_resolution": {
            "identity_mode": "ordinary",
            "current_display_name": "테스트 주인공",
            "pre_transfer_name": None,
            "host_or_avatar_name": None,
            "public_opening_name": "테스트 주인공",
            "identity_spoiler_risk": "low",
            "name_use_rule": "테스트 주인공이라고 불러도 된다.",
        },
        "opening_scene": {
            "time": "초반",
            "place": "현장",
            "situation": "주인공이 첫 사건을 마주한다.",
            "immediate_conflict": "사건을 방치하면 피해가 커진다.",
            "props_or_anchors": ["현장"],
            "nearby_characters": [],
        },
        "user_role": {
            "role_type": user_role_type,
            "relationship_to_character": "현장에 같이 있는 사람",
            "scene_entry_reason": "유저는 첫 사건 현장에 같이 있었다.",
            "first_turn_affordance": "유저는 단서를 가리키거나 위험을 알릴 수 있다.",
            "user_knows": ["첫 사건이 벌어졌다."],
            "user_must_not_know": ["이후 반전"],
            "allowed_assumptions": ["유저는 현장에 있다."],
            "forbidden_assumptions": ["유저는 원작 인물이다."],
        },
        "character_drive": {"immediate_objective": "첫 사건을 해결한다."},
        "agency_contract": {
            "character_moves_first": True,
            "move_style": "정보 요구",
            "non_user_dependent_action": "유저가 망설여도 주인공이 먼저 현장의 단서를 확인한다.",
            "decision_character_must_make": "위험을 감수하고 현장 안쪽으로 들어갈지 결정한다.",
            "user_influence_boundary": "유저는 단서와 위험을 알려줄 수 있지만 사건 해결을 대신하지 않는다.",
        },
        "progression_engine": {
            "short_term_goal": "첫 사건 현장에서 단서를 확인한다.",
            "mid_term_escalation": "새 위험이 나타나 현장을 벗어나기 어려워진다.",
            "long_term_complication": "처음 본 단서가 더 큰 사건으로 이어진다.",
            "scene_exit_condition": "핵심 단서를 확인하고 다음 장소로 이동한다.",
            "event_injection_rules": [
                {
                    "when": "유저가 침묵한다",
                    "inject": "주인공이 먼저 바닥의 단서를 집어 든다.",
                    "must_not_repeat": "같은 질문 반복",
                },
                {
                    "when": "유저가 지켜보기만 한다",
                    "inject": "현장 밖에서 새 소리가 들린다.",
                    "must_not_repeat": "경계만 반복",
                },
            ],
        },
        "user_affordance_contract": {
            "primary_affordances": ["관찰", "판단", "정보 제공"],
            "forbidden_agency_load": ["유저가 사건을 단독 해결함", "유저가 전투를 주도함"],
            "safe_response_examples": ["단서 위치를 알린다", "다가오는 위험을 말한다"],
            "bad_response_pressure_to_avoid": ["네가 직접 싸워", "네가 혼자 해결해"],
        },
        "canon_safe_expansion": {
            "safe_new_event_pattern": "첫 사건 현장의 위험을 변주한 소규모 돌발 상황",
            "allowed_inventions": ["새 소리", "작은 단서"],
            "forbidden_inventions": ["미래 반전", "미등장 세력명"],
            "must_preserve_facts": ["주인공은 첫 사건을 해결하려 한다"],
        },
        "voice_style": {"speech_level": "반말"},
        "relationship_stance": {
            "initial_trust": "중간",
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
            "opening_greeting_intent": "유저를 사건에 끌어들인다.",
            "next_beats": [
                {"beat": "단서 확인", "trigger": "유저 협조", "avoid_repeating": "같은 질문 반복"},
                {"beat": "위험 접근", "trigger": "유저 지연", "avoid_repeating": "경계만 반복"},
            ],
        },
    }


class StoryAgentOpeningLabelSummaryTest(unittest.TestCase):
    def test_merge_uses_latest_result_for_same_file_and_current_schema(self):
        module = load_module()
        input_rows = [
            {"fileName": "a.txt", "llmLabelingBucket": "main", "splitConfidence": "high"},
            {"fileName": "b.txt", "llmLabelingBucket": "main", "splitConfidence": "high"},
        ]
        result_rows = [
            {"fileName": "a.txt", "status": "error", "error": "old"},
            {"fileName": "a.txt", "status": "ok", "label": ready_label()},
            {"fileName": "b.txt", "status": "ok", "label": ready_label(user_role_type="불명")},
        ]

        selected = module.merge_label_rows(input_rows=input_rows, result_rows=result_rows)
        summary = module.summarize_rows(selected)

        self.assertEqual(selected[0]["status"], "ok")
        self.assertTrue(selected[0]["schemaPassCurrent"])
        self.assertEqual(selected[0]["effectiveStatus"], "ready")
        self.assertFalse(selected[1]["schemaPassCurrent"])
        self.assertEqual(selected[1]["schemaIssuesCurrent"], ["ready_user_role_unspecified"])
        self.assertEqual(selected[1]["effectiveStatus"], "not_ready")
        self.assertEqual(selected[1]["effectiveBlockReasons"], ["ready_user_role_unspecified"])
        self.assertEqual(summary["statusCounts"], {"ok": 2})
        self.assertEqual(summary["schemaPassCurrentCounts"], {"fail": 1, "pass": 1})
        self.assertEqual(summary["effectiveStatusCounts"], {"not_ready": 1, "ready": 1})
        self.assertEqual(summary["openingHookTypeCounts"], {"위기": 2})
        self.assertEqual(summary["identityModeCounts"], {"ordinary": 2})
        self.assertEqual(summary["targetRoleCounts"], {"주인공": 2})
        self.assertEqual(summary["targetNameEvidenceCounts"], {"direct_name": 2})
        self.assertEqual(summary["voiceEvidenceCounts"], {"dialogue": 2})
        self.assertEqual(summary["sceneAnchorEvidenceCounts"], {"direct": 2})
        self.assertEqual(summary["nextBeatsCountBuckets"], {"2": 2})
        self.assertEqual(summary["schemaIssueCounts"], {"ready_user_role_unspecified": 1})
        self.assertEqual(summary["gateFailureReasonCounts"], {"ready_user_role_unspecified": 1})
        self.assertEqual(summary["readyAndSchemaPassCount"], 1)
        self.assertEqual(summary["usableCount"], 1)
        self.assertEqual(summary["usableRate"], 0.5)
        self.assertEqual(summary["notUsableCount"], 1)

    def test_summary_normalizes_model_block_reason_counts(self):
        module = load_module()
        label = ready_label()
        label["readiness"] = {
            "status": "needs_review",
            "confidence": 0.4,
            "block_reasons": ["주인공 후보 판단 근거가 길고 작품별로 달라지는 설명"],
        }
        selected = module.merge_label_rows(
            input_rows=[{"fileName": "review.txt", "llmLabelingBucket": "main"}],
            result_rows=[{"fileName": "review.txt", "status": "ok", "label": label}],
        )
        summary = module.summarize_rows(selected)

        self.assertEqual(selected[0]["effectiveStatus"], "needs_review")
        self.assertEqual(summary["gateFailureReasonCounts"], {"model_needs_review": 1})

    def test_summary_classifies_non_ok_failures_separately(self):
        module = load_module()
        input_rows = [
            {"fileName": "pay.txt", "llmLabelingBucket": "main"},
            {"fileName": "slow.txt", "llmLabelingBucket": "main"},
            {"fileName": "bad-json.txt", "llmLabelingBucket": "main"},
            {"fileName": "missing.txt", "llmLabelingBucket": "main"},
        ]
        result_rows = [
            {
                "fileName": "pay.txt",
                "status": "error",
                "error": "Client error '402 Payment Required'",
            },
            {
                "fileName": "slow.txt",
                "status": "error",
                "error": "call exceeded 360.0s",
            },
            {
                "fileName": "bad-json.txt",
                "status": "parse_error",
                "parseError": "Expecting ',' delimiter",
            },
        ]

        selected = module.merge_label_rows(input_rows=input_rows, result_rows=result_rows)
        summary = module.summarize_rows(selected)

        self.assertEqual(
            [row["effectiveBlockReasons"] for row in selected],
            [["api_payment_required"], ["timeout"], ["parse_error"], ["missing"]],
        )
        self.assertEqual(
            summary["statusFailureReasonCounts"],
            {
                "api_payment_required": 1,
                "missing": 1,
                "parse_error": 1,
                "timeout": 1,
            },
        )
        self.assertEqual(
            summary["gateFailureReasonCounts"],
            {
                "api_payment_required": 1,
                "missing": 1,
                "parse_error": 1,
                "timeout": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
