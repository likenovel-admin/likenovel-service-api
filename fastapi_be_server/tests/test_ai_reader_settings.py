import os
import subprocess
import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _read_ai_reader_model(**env_overrides: str) -> str:
    env = os.environ.copy()
    env.pop("AI_READER_OPENROUTER_MODEL", None)
    env.update(env_overrides)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.const import settings; print(settings.AI_READER_OPENROUTER_MODEL)",
        ],
        cwd=BACKEND_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


class AiReaderSettingsTest(unittest.TestCase):
    def test_default_is_gemma_independently_of_global_openrouter_model(self):
        self.assertEqual(
            _read_ai_reader_model(OPENROUTER_MODEL="deepseek/deepseek-v3.2"),
            "google/gemma-4-31b-it",
        )

    def test_explicit_model_override_is_preserved(self):
        self.assertEqual(
            _read_ai_reader_model(
                OPENROUTER_MODEL="deepseek/deepseek-v3.2",
                AI_READER_OPENROUTER_MODEL="vendor/reader-override",
            ),
            "vendor/reader-override",
        )
