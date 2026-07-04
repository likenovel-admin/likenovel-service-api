import json
import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_character_chat_opening_corpus.py"


def load_module():
    module_name = "audit_character_chat_opening_corpus_under_test"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def long_body(label: str, repeat: int = 80) -> str:
    return "\n".join(f"{label} 본문 {index:03d}" for index in range(repeat))


class StoryAgentOpeningCorpusAuditTest(unittest.TestCase):
    def test_extracts_first_three_from_standard_nhwa_headers(self):
        module = load_module()
        text = "\n".join(
            [
                "1화 첫 장면",
                long_body("one"),
                "2화 두 번째 장면",
                long_body("two"),
                "3화 세 번째 장면",
                long_body("three"),
                "4화 네 번째 장면",
                long_body("four"),
            ]
        )

        openings, _headers = module.extract_opening_episodes(text, min_section_chars=100)

        self.assertEqual([item.episode_no for item in openings], [1, 2, 3])
        self.assertEqual([item.header_pattern for item in openings], ["n_hwa", "n_hwa", "n_hwa"])
        self.assertEqual(module.classify_opening_quality(openings), "first3_detected")

    def test_extracts_title_prefixed_parenthesized_episode_headers(self):
        module = load_module()
        text = "\n".join(
            [
                "AI 경찰",
                "Downloaded with novel-dl",
                "AI 경찰 (1)화",
                long_body("one"),
                "AI 경찰 (2)화",
                long_body("two"),
                "AI 경찰 (3)화",
                long_body("three"),
            ]
        )

        openings, _headers = module.extract_opening_episodes(text, min_section_chars=100)

        self.assertEqual([item.episode_no for item in openings], [1, 2, 3])
        self.assertEqual([item.header_pattern for item in openings], ["title_nhwa", "title_nhwa", "title_nhwa"])

    def test_extracts_number_line_headers_with_following_title(self):
        module = load_module()
        text = "\n".join(
            [
                "게임 속 기사로 살아가기",
                "1",
                "야만의 시대",
                long_body("one"),
                "2",
                "용병의 밤",
                long_body("two"),
                "3",
                "검은 성문",
                long_body("three"),
            ]
        )

        openings, _headers = module.extract_opening_episodes(text, min_section_chars=100)

        self.assertEqual([item.episode_no for item in openings], [1, 2, 3])
        self.assertEqual([item.header_pattern for item in openings], ["number_line", "number_line", "number_line"])

    def test_skips_table_of_contents_when_real_sections_are_later(self):
        module = load_module()
        text = "\n".join(
            [
                "작품 소개",
                "목차",
                "1화 각성",
                "2화 탑",
                "3화 파티",
                "프롤로그",
                long_body("intro", repeat=20),
                "1화 각성",
                long_body("one"),
                "2화 탑",
                long_body("two"),
                "3화 파티",
                long_body("three"),
            ]
        )

        openings, _headers = module.extract_opening_episodes(text, min_section_chars=100)

        self.assertEqual([item.episode_no for item in openings], [1, 2, 3])
        self.assertGreater(openings[0].start_offset, text.index("프롤로그"))

    def test_numbered_list_after_first_header_does_not_become_fake_episode_two(self):
        module = load_module()
        text = "\n".join(
            [
                "제 1화",
                "1. 로또 1등 되기.",
                "2. 주식 선점하기.",
                "3. 부동산 사기.",
                long_body("one"),
                "제 2화",
                long_body("two"),
                "제 3화",
                long_body("three"),
            ]
        )

        openings, _headers = module.extract_opening_episodes(text, min_section_chars=100)

        self.assertEqual([item.episode_no for item in openings], [1, 2, 3])
        self.assertEqual([item.header_pattern for item in openings], ["je_nhwa", "je_nhwa", "je_nhwa"])

    def test_multipart_same_episode_headers_do_not_block_opening_sequence(self):
        module = load_module()
        text = "\n".join(
            [
                "1화 기회 (1)",
                long_body("one-a"),
                "1화 기회 (2)",
                long_body("one-b"),
                "1화 기회 (3)",
                long_body("one-c"),
                "2화 낯선 문 (1)",
                long_body("two-a"),
                "2화 낯선 문 (2)",
                long_body("two-b"),
                "3화 첫 선택",
                long_body("three"),
            ]
        )

        openings, _headers = module.extract_opening_episodes(text, min_section_chars=100)

        self.assertEqual([item.episode_no for item in openings], [1, 2, 3])
        self.assertEqual(module.classify_opening_quality(openings), "first3_detected")

    def test_split_diagnostics_marks_clean_first3_as_high_confidence(self):
        module = load_module()
        openings = [
            module.OpeningEpisode(1, "one", 0, 5000, "n_hwa", 5000),
            module.OpeningEpisode(2, "two", 5000, 10000, "je_nhwa", 5000),
            module.OpeningEpisode(3, "three", 10000, 15000, "title_nhwa", 5000),
        ]

        diagnostics = module.build_split_diagnostics(
            openings,
            quality="first3_detected",
            header_count=3,
            analyzed_text_chars=15000,
            file_size=15000,
            read_bytes=2_000_000,
        )

        self.assertEqual(diagnostics["splitConfidence"], "high")
        self.assertEqual(diagnostics["llmLabelingBucket"], "main")
        self.assertTrue(diagnostics["readyForLLMLabeling"])
        self.assertEqual(diagnostics["lengthOutlierFlags"], [])

    def test_split_diagnostics_marks_number_dot_first3_as_review_bucket(self):
        module = load_module()
        openings = [
            module.OpeningEpisode(1, "one", 0, 6000, "number_dot", 6000),
            module.OpeningEpisode(2, "two", 6000, 12000, "number_dot", 6000),
            module.OpeningEpisode(3, "three", 12000, 18000, "number_dot", 6000),
        ]

        diagnostics = module.build_split_diagnostics(
            openings,
            quality="first3_detected",
            header_count=3,
            analyzed_text_chars=18000,
            file_size=18000,
            read_bytes=2_000_000,
        )

        self.assertEqual(diagnostics["splitConfidence"], "medium")
        self.assertEqual(diagnostics["llmLabelingBucket"], "review")
        self.assertTrue(diagnostics["readyForLLMLabeling"])
        self.assertTrue(diagnostics["numberDotOnly"])

    def test_dense_headers_do_not_downgrade_strong_clean_split(self):
        module = load_module()
        openings = [
            module.OpeningEpisode(1, "one", 0, 6000, "n_hwa", 6000),
            module.OpeningEpisode(2, "two", 6000, 12000, "n_hwa", 6000),
            module.OpeningEpisode(3, "three", 12000, 18000, "n_hwa", 6000),
        ]

        diagnostics = module.build_split_diagnostics(
            openings,
            quality="first3_detected",
            header_count=150,
            analyzed_text_chars=800000,
            file_size=800000,
            read_bytes=2_000_000,
        )

        self.assertTrue(diagnostics["denseHeaders"])
        self.assertEqual(diagnostics["splitConfidence"], "high")
        self.assertEqual(diagnostics["llmLabelingBucket"], "main")

    def test_split_diagnostics_blocks_length_outlier_first3(self):
        module = load_module()
        openings = [
            module.OpeningEpisode(1, "one", 0, 714824, "number_dot", 714824),
            module.OpeningEpisode(2, "two", 714824, 769351, "number_dot", 54527),
            module.OpeningEpisode(3, "three", 769351, 769353, "number_dot", 2),
        ]

        diagnostics = module.build_split_diagnostics(
            openings,
            quality="first3_detected",
            header_count=90,
            analyzed_text_chars=800000,
            file_size=800000,
            read_bytes=2_000_000,
        )

        self.assertEqual(diagnostics["splitConfidence"], "suspect")
        self.assertEqual(diagnostics["llmLabelingBucket"], "blocked")
        self.assertFalse(diagnostics["readyForLLMLabeling"])
        self.assertTrue(diagnostics["thirdEpisodeTooShort"])
        self.assertIn("episode_1_too_long", diagnostics["lengthOutlierFlags"])
        self.assertIn("episode_3_too_short", diagnostics["lengthOutlierFlags"])
        self.assertIn("episode_length_variance", diagnostics["lengthOutlierFlags"])

    def test_audit_zip_reports_quality_counts_without_extracting_payload_text(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = Path(temp_dir) / "sample.zip"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr(
                    "standard.txt",
                    "\n".join(
                        [
                            "1화 시작",
                            long_body("one", repeat=120),
                            "2화 다음",
                            long_body("two", repeat=120),
                            "3화 끝",
                            long_body("three", repeat=120),
                        ]
                    ),
                )
                archive.writestr("unknown.txt", "제목만 있고 회차 헤더는 없다.\n본문도 짧다.")

            payload = module.audit_zip(zip_path, min_section_chars=100)

        self.assertEqual(payload["fileCount"], 2)
        self.assertEqual(payload["qualityCounts"]["first3_detected"], 1)
        self.assertEqual(payload["qualityCounts"]["no_headers"], 1)
        self.assertEqual(payload["splitConfidenceCounts"]["high"], 1)
        self.assertEqual(payload["splitConfidenceCounts"]["fail"], 1)
        self.assertEqual(payload["llmLabelingBucketCounts"]["main"], 1)
        self.assertEqual(payload["llmLabelingBucketCounts"]["blocked"], 1)
        self.assertTrue(payload["rows"][0]["readyForLLMLabeling"])
        self.assertIn("headerDensityPer100k", payload["rows"][0])
        self.assertNotIn("text", payload["rows"][0])

        manifest_rows = [json.loads(line) for line in module.build_manifest_lines(payload)]
        self.assertEqual(len(manifest_rows), 2)
        self.assertEqual(manifest_rows[0]["sourceZip"], str(zip_path))
        self.assertEqual(manifest_rows[0]["llmLabelingBucket"], "main")
        self.assertNotIn("text", manifest_rows[0])


if __name__ == "__main__":
    unittest.main()
