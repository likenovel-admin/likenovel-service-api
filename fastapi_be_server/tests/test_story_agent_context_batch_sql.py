from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _batch_sh() -> str:
    return (
        ROOT / "dist" / "batch" / "build_story_agent_context_batch.sh"
    ).read_text(encoding="utf-8")


class StoryAgentContextBatchSqlTest(unittest.TestCase):
    def test_candidate_selection_uses_missing_open_foundation_rows_not_episode_no_max(self):
        script = _batch_sh()

        self.assertIn("pe.use_yn = 'Y'", script)
        self.assertIn("pe.open_yn = 'Y'", script)
        self.assertIn("p.price_type IN ('free', 'paid')", script)
        self.assertIn("p.status_code = 'ongoing'", script)
        self.assertIn("p.blind_yn = 'N'", script)
        self.assertIn("tb_story_agent_context_summary", script)
        self.assertIn("sacs.summary_type = 'episode_summary'", script)
        self.assertIn("sacs.is_active = 'Y'", script)
        self.assertIn("sacs.scope_key = CONCAT('episode:', pe.episode_id)", script)
        self.assertIn("sacs_signal.summary_type = 'episode_character_signals'", script)
        self.assertIn("sacs_signal.scope_key = CONCAT('episode:', pe.episode_id)", script)
        self.assertIn("missing_open_episode_count", script)
        self.assertIn("missing_open_character_signal_count", script)
        self.assertIn("missing_foundation_episode_count", script)
        self.assertIn("active_character_inventory_count", script)
        self.assertIn("active_character_inventory_v3_count", script)
        self.assertNotIn("MAX(pe.episode_no)", script)
        self.assertNotIn("p.price_type = 'free'", script)

    def test_batch_defaults_to_delta_and_requires_explicit_full_opt_in(self):
        script = _batch_sh()

        self.assertIn('BUILD_MODE="${STORYCTX_BUILD_MODE:-delta}"', script)
        self.assertIn('MAX_DELTA_EPISODES="${STORYCTX_MAX_DELTA_EPISODES:-${STORYCTX_MAX_MISSING_EPISODES:-5}}"', script)
        self.assertIn('BACKLOG_PRIORITY_THRESHOLD="${STORYCTX_BACKLOG_PRIORITY_THRESHOLD:-20}"', script)
        self.assertIn('STORYCTX_ALLOW_FULL', script)
        self.assertIn('--build-mode "${BUILD_MODE}"', script)
        self.assertIn('--max-delta-episodes "${MAX_DELTA_EPISODES}"', script)
        self.assertIn("backlog_priority_threshold=${BACKLOG_PRIORITY_THRESHOLD}", script)
        self.assertIn('missing_foundation_episode_count > 0', script)
        self.assertIn("context_status = 'failed'", script)
        self.assertIn("missing_foundation_episode_count = 0", script)
        self.assertIn("active_character_inventory_count > 0", script)
        self.assertIn("active_character_inventory_v3_count > 0", script)
        failed_priority = "WHEN candidates.context_status = 'failed' THEN 0"
        large_backlog_priority = "WHEN candidates.missing_foundation_episode_count >= ${BACKLOG_PRIORITY_THRESHOLD} THEN 1"
        small_delta_priority = "WHEN candidates.missing_foundation_episode_count < ${BACKLOG_PRIORITY_THRESHOLD} THEN 2"
        processing_tiebreaker = "WHEN 'processing' THEN 0"

        self.assertIn(failed_priority, script)
        self.assertIn(large_backlog_priority, script)
        self.assertIn(small_delta_priority, script)
        self.assertIn(processing_tiebreaker, script)
        self.assertLess(script.index(failed_priority), script.index(large_backlog_priority))
        self.assertLess(script.index(large_backlog_priority), script.index(small_delta_priority))
        self.assertIn(
            "candidates.missing_foundation_episode_count DESC",
            script,
        )
        self.assertIn(
            "candidates.missing_open_character_signal_count DESC",
            script,
        )
        self.assertNotIn(
            "CASE WHEN candidates.missing_open_episode_count <= ${MAX_DELTA_EPISODES} THEN 0 ELSE 1 END ASC",
            script,
        )
        self.assertNotIn("missing_open_episode_count > ${MAX_DELTA_EPISODES} THEN 1", script)
        self.assertNotIn('missing_open_episode_count BETWEEN 1 AND ${MAX_MISSING_EPISODES}', script)
        self.assertNotIn("--build-mode full", script)
