from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _batch_sh() -> str:
    return (
        ROOT / "dist" / "batch" / "build_story_agent_context_batch.sh"
    ).read_text(encoding="utf-8")


class StoryAgentContextBatchSqlTest(unittest.TestCase):
    def test_candidate_selection_uses_missing_open_episode_summaries_not_episode_no_max(self):
        script = _batch_sh()

        self.assertIn("pe.use_yn = 'Y'", script)
        self.assertIn("pe.open_yn = 'Y'", script)
        self.assertIn("p.blind_yn = 'N'", script)
        self.assertIn("tb_story_agent_context_summary", script)
        self.assertIn("sacs.summary_type = 'episode_summary'", script)
        self.assertIn("sacs.is_active = 'Y'", script)
        self.assertIn("sacs.scope_key = CONCAT('episode:', pe.episode_id)", script)
        self.assertIn("missing_open_episode_count", script)
        self.assertNotIn("MAX(pe.episode_no)", script)
