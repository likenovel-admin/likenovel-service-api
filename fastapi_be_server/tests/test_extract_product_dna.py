import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "dist" / "batch" / "extract_product_dna.py"


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
