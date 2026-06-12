import importlib.util
from pathlib import Path
from unittest import TestCase


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "eval_golden_set.py"


def load_module():
    spec = importlib.util.spec_from_file_location("eval_golden_set", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


GOLDEN_WORK = {
    "product_id": 1129,
    "title": "다크엘프에게 버프를 받고 괴물사냥꾼이 됨",
    "expected": {"직": ["헌터"], "능": ["버프"]},
    "expected_any": {"세": [["이종족", "엘프"]]},
    "forbidden": {"능": ["상태창"], "직": ["기사"]},
    "optional": {"타": ["성장형"]},
    "strict_axes": ["타"],
    "unmapped_expected": ["짐꾼"],
}


def prediction(axis_labels, unmapped=None):
    labels = {axis: axis_labels.get(axis, []) for axis in ("세", "직", "능", "연", "작", "타", "목")}
    return {"axis_labels": labels, "unmapped_concepts": unmapped or []}


class EvalGoldenSetScorerTest(TestCase):
    def test_perfect_prediction_passes_all_checks(self):
        module = load_module()
        result = module.score_work(
            GOLDEN_WORK,
            prediction({"직": ["헌터"], "능": ["버프"], "세": ["엘프"], "타": ["성장형"]}, ["S급 짐꾼"]),
        )

        self.assertEqual(result["expected_misses"], [])
        self.assertEqual(result["forbidden_violations"], [])
        self.assertEqual(result["strict_violations"], [])
        self.assertEqual(result["expected_found"], result["expected_total"])
        self.assertEqual(result["unmapped_hits"], ["짐꾼"])

    def test_forbidden_and_expected_miss_are_reported(self):
        module = load_module()
        result = module.score_work(
            GOLDEN_WORK,
            prediction({"직": ["기사"], "능": ["상태창"], "세": []}),
        )

        self.assertIn("[직] 헌터", result["expected_misses"])
        self.assertIn("[능] 버프", result["expected_misses"])
        self.assertIn("[세] 이종족|엘프", result["expected_misses"])
        self.assertIn("[직] 기사", result["forbidden_violations"])
        self.assertIn("[능] 상태창", result["forbidden_violations"])
        self.assertEqual(result["unmapped_misses"], ["짐꾼"])

    def test_strict_axis_flags_unlisted_label_but_allows_optional(self):
        module = load_module()
        result = module.score_work(
            GOLDEN_WORK,
            prediction({"직": ["헌터"], "능": ["버프"], "세": ["이종족"], "타": ["성장형", "낭인"]}),
        )

        self.assertEqual(result["strict_violations"], ["[타] 낭인"])
