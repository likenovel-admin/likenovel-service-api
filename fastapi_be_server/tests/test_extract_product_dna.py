import importlib.util
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "dist" / "batch" / "extract_product_dna.py"
FASTAPI_ROOT = MODULE_PATH.parents[2]
CODEBOOK_DIRS = [FASTAPI_ROOT / "dist" / "ai", FASTAPI_ROOT / "dist" / "batch"]


class AiDnaCodebookContractTest(TestCase):
    def test_runtime_codebook_copies_are_complete_and_in_sync(self):
        expected_allowed_bytes = (CODEBOOK_DIRS[0] / "allowed-labels-by-axis.json").read_bytes()
        expected_definitions_bytes = (CODEBOOK_DIRS[0] / "label-definitions-by-axis.json").read_bytes()
        expected_allowed = json.loads(
            expected_allowed_bytes.decode("utf-8")
        )
        expected_definitions = json.loads(
            expected_definitions_bytes.decode("utf-8")
        )

        for codebook_dir in CODEBOOK_DIRS[1:]:
            self.assertEqual(
                (codebook_dir / "allowed-labels-by-axis.json").read_bytes(),
                expected_allowed_bytes,
            )
            self.assertEqual(
                (codebook_dir / "label-definitions-by-axis.json").read_bytes(),
                expected_definitions_bytes,
            )
            self.assertEqual(
                json.loads((codebook_dir / "allowed-labels-by-axis.json").read_text(encoding="utf-8")),
                expected_allowed,
            )
            self.assertEqual(
                json.loads((codebook_dir / "label-definitions-by-axis.json").read_text(encoding="utf-8")),
                expected_definitions,
            )

        missing = {
            axis: [label for label in labels if label not in expected_definitions.get(axis, {})]
            for axis, labels in expected_allowed.items()
        }
        self.assertEqual({axis: labels for axis, labels in missing.items() if labels}, {})
        self.assertEqual(sum(map(len, expected_allowed.values())), 361)

        for label in ("회귀", "빙의", "환생"):
            self.assertIn(label, expected_allowed["타"])
            self.assertIn(label, expected_definitions["타"])
        self.assertIn("무한회귀", expected_allowed["능"])
        self.assertIn("루프", expected_allowed["작"])
        self.assertIn("차원이동", expected_allowed["목"])


def load_module():
    spec = importlib.util.spec_from_file_location("extract_product_dna_batch", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AiDnaDeepseekFallbackTest(TestCase):
    def test_anthropic_failure_falls_back_to_deepseek_v4flash(self):
        module = load_module()
        module.AI_DNA_PROVIDER = "anthropic"
        module.ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
        module.DEEPSEEK_API_KEY = "test-key"
        module.AI_DNA_DEEPSEEK_FALLBACK_MODEL = "deepseek-v4-flash"

        with patch.object(module, "call_claude", side_effect=RuntimeError("Claude API error: 429 credit")), \
             patch.object(module, "call_deepseek", return_value=("{}", {"total_tokens": 123})) as mocked_deepseek:
            raw, meta = module._call_llm("system", "user", {axis: set() for axis in module.AXIS_ORDER})

        self.assertEqual(raw, "{}")
        mocked_deepseek.assert_called_once()
        self.assertEqual(meta["provider"], "deepseek")
        self.assertEqual(meta["fallback_from"], "anthropic")
        self.assertEqual(meta["model"], "deepseek-v4-flash")
        self.assertIn("Claude API error", meta["fallback_reason"])
        self.assertEqual(meta["usage"], {"prompt_tokens": None, "completion_tokens": None, "total_tokens": 123, "cost": None})

    def test_anthropic_failure_without_deepseek_key_raises_original_error(self):
        module = load_module()
        module.AI_DNA_PROVIDER = "anthropic"
        module.DEEPSEEK_API_KEY = ""
        module.AI_DNA_DEEPSEEK_FALLBACK_MODEL = "deepseek-v4-flash"

        with patch.object(module, "call_claude", side_effect=RuntimeError("Claude API error: 429 credit")):
            with self.assertRaisesRegex(RuntimeError, "Claude API error"):
                module._call_llm("system", "user", {axis: set() for axis in module.AXIS_ORDER})


class FakeCursor:
    def __init__(self):
        self.sql = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return []


class FakeConnection:
    def __init__(self):
        self.last_cursor = FakeCursor()

    def cursor(self):
        return self.last_cursor


class AiDnaProductTargetQueryTest(TestCase):
    def test_first_episode_minimum_text_count_is_1000(self):
        module = load_module()
        conn = FakeConnection()

        module.get_products(conn, force=True)

        self.assertIn("fe.episode_text_count >= 1000", conn.last_cursor.sql)
        self.assertNotIn("fe.episode_text_count >= 5000", conn.last_cursor.sql)
