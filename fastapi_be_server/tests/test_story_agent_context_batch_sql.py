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

    def test_batch_defaults_to_delta_and_requires_explicit_full_opt_in(self):
        script = _batch_sh()

        self.assertIn('BUILD_MODE="${STORYCTX_BUILD_MODE:-delta}"', script)
        self.assertIn('MAX_DELTA_EPISODES="${STORYCTX_MAX_DELTA_EPISODES:-${STORYCTX_MAX_MISSING_EPISODES:-5}}"', script)
        self.assertIn('STORYCTX_ALLOW_FULL', script)
        self.assertIn('--build-mode "${BUILD_MODE}"', script)
        self.assertIn('--max-delta-episodes "${MAX_DELTA_EPISODES}"', script)
        self.assertIn('missing_open_episode_count > 0', script)
        self.assertIn(
            'CASE WHEN candidates.missing_open_episode_count <= ${MAX_DELTA_EPISODES} THEN 0 ELSE 1 END ASC',
            script,
        )
        self.assertNotIn('missing_open_episode_count BETWEEN 1 AND ${MAX_MISSING_EPISODES}', script)
        self.assertNotIn("--build-mode full", script)
