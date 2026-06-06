import unittest

from app.services.admin import admin_ai_metadata_service


class AdminAiMetadataPromptTest(unittest.TestCase):
    def test_prompt_separates_ai_librarian_public_tone_from_internal_summary_style(self):
        prompt = admin_ai_metadata_service.DNA_SYSTEM_PROMPT

        self.assertIn("summary.premise", prompt)
        self.assertIn("summary.hook", prompt)
        self.assertIn("AI 사서 공개 소개", prompt)
        self.assertIn("해요체", prompt)
        self.assertIn('"다", "합니다", "입니다" 종결을 쓰지 않는다', prompt)
        self.assertIn("summary.protagonist_desc와 summary.episode_summary_text", prompt)
        self.assertIn("존댓말 없이 간결한 서술체", prompt)
