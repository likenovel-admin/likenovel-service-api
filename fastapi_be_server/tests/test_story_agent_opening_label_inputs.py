import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
MODULE_PATH = SCRIPT_DIR / "build_character_chat_opening_label_inputs.py"


def load_module():
    module_name = "build_character_chat_opening_label_inputs_under_test"
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def long_body(label: str, repeat: int = 40) -> str:
    return "\n".join(f"{label} 라벨 입력 본문 {index:03d}" for index in range(repeat))


class StoryAgentOpeningLabelInputsTest(unittest.TestCase):
    def test_builds_label_inputs_from_selected_manifest_bucket(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            zip_path = temp_path / "sample.zip"
            text = "\n".join(
                [
                    "1화 첫 사건",
                    long_body("one"),
                    "2화 두 번째 압박",
                    long_body("two"),
                    "3화 선택지",
                    long_body("three"),
                ]
            )
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("main.txt", text)
                archive.writestr("blocked.txt", text)

            manifest_path = temp_path / "manifest.jsonl"
            manifest_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "fileName": "main.txt",
                                "llmLabelingBucket": "main",
                                "splitConfidence": "high",
                                "openingQuality": "first3_detected",
                                "openingTextChars": [1000, 1000, 1000],
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "fileName": "blocked.txt",
                                "llmLabelingBucket": "blocked",
                                "splitConfidence": "fail",
                                "openingQuality": "no_headers",
                                "openingTextChars": [],
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            manifest_rows = module.load_manifest_rows(manifest_path, buckets={"main"})
            rows, skipped = module.build_label_input_rows(
                zip_path=zip_path,
                manifest_rows=manifest_rows,
                max_items=0,
                max_episode_chars=120,
                min_section_chars=100,
                max_read_bytes=2_000_000,
            )

        self.assertEqual(len(manifest_rows), 1)
        self.assertEqual(skipped, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fileName"], "main.txt")
        self.assertEqual(rows[0]["llmLabelingBucket"], "main")
        self.assertEqual([episode["episodeNo"] for episode in rows[0]["episodes"]], [1, 2, 3])
        self.assertIn("1화 첫 사건", rows[0]["episodes"][0]["labelText"])
        self.assertTrue(rows[0]["episodes"][0]["labelTextTruncated"])

    def test_jsonl_dump_escapes_unicode_line_separators(self):
        module = load_module()
        line = module.dumps_jsonl({"labelText": "첫 줄\u2028둘째 줄\u2029끝"})

        self.assertEqual(len(line.splitlines()), 1)
        self.assertIn("\\u2028", line)
        self.assertIn("\\u2029", line)
        self.assertEqual(json.loads(line)["labelText"], "첫 줄\u2028둘째 줄\u2029끝")


if __name__ == "__main__":
    unittest.main()
