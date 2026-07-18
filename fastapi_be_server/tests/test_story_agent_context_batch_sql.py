from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

from app.services.websochat.character_chat_product_policy import (
    CHARACTER_CHAT_FIRST_PUBLIC_EPISODE_AT,
    CHARACTER_CHAT_MINIMUM_OPEN_EPISODE_COUNT,
)


ROOT = Path(__file__).resolve().parents[1]


def _batch_sh() -> str:
    return (
        ROOT / "dist" / "batch" / "build_story_agent_context_batch.sh"
    ).read_text(encoding="utf-8")


class StoryAgentContextBatchSqlTest(unittest.TestCase):
    def test_candidate_query_failure_exits_nonzero(self):
        script = _batch_sh()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            batch_dir = root / "dist" / "batch"
            scripts_dir = root / "scripts"
            bin_dir = root / "bin"
            batch_dir.mkdir(parents=True)
            scripts_dir.mkdir(parents=True)
            bin_dir.mkdir()

            batch_path = batch_dir / "build_story_agent_context_batch.sh"
            batch_path.write_text(script, encoding="utf-8")
            (scripts_dir / "build_story_agent_context.py").write_text("", encoding="utf-8")
            mysql_path = bin_dir / "mysql"
            mysql_path.write_text("#!/bin/sh\nexit 42\n", encoding="utf-8")
            mysql_path.chmod(0o755)

            log_path = root / "batch.log"
            result = subprocess.run(
                ["bash", str(batch_path)],
                env={
                    **os.environ,
                    "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                    "DB_HOST": "example.invalid",
                    "DB_PORT": "3306",
                    "DB_USER": "test-user",
                    "DB_PW": "test-password",
                    "DB_NAME": "likenovel",
                    "OPENROUTER_API_KEY": "test-key",
                    "STORYCTX_LOCK_DIR": str(root / "batch.lock"),
                    "STORYCTX_LOG_FILE": str(log_path),
                },
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("[error] candidate query failed", log_path.read_text(encoding="utf-8"))

    def test_candidate_selection_uses_missing_open_foundation_rows_not_episode_no_max(self):
        script = _batch_sh()

        self.assertIn("pe.use_yn = 'Y'", script)
        self.assertIn("pe.open_yn = 'Y'", script)
        self.assertIn("p.price_type IN ('free', 'paid')", script)
        self.assertIn("p.status_code = 'ongoing'", script)
        self.assertIn("FROM tb_product_episode cohort_episode", script)
        self.assertIn("cohort_episode.use_yn = 'Y'", script)
        self.assertIn("cohort_episode.open_yn = 'Y'", script)
        self.assertIn("HAVING COUNT(*) >= 15", script)
        self.assertIn("cohort_episode.open_changed_date", script)
        self.assertIn("cohort_episode.publish_reserve_date", script)
        self.assertIn("cohort_episode.created_date", script)
        self.assertIn(">= '2026-03-01 00:00:00'", script)
        self.assertIn("p.blind_yn = 'N'", script)
        self.assertIn("COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'", script)
        self.assertIn("COALESCE(sacp.context_status, 'pending') <> 'disabled'", script)
        self.assertIn("collection_cohort.product_id IS NOT NULL", script)
        self.assertIn("OR COALESCE(sacp.context_status, 'pending') = 'ready'", script)
        self.assertIn(
            "CASE WHEN collection_cohort.product_id IS NULL THEN 0 ELSE (\n"
            "      SELECT COUNT(*)\n"
            "      FROM tb_story_agent_context_summary repair_inventory",
            script,
        )
        self.assertIn(
            "FROM tb_story_agent_context_summary ci\n"
            "      WHERE ci.product_id = p.product_id",
            script,
        )
        self.assertIn("tb_story_agent_context_summary", script)
        self.assertIn("sacs.summary_type = 'episode_summary'", script)
        self.assertIn("sacs.is_active = 'Y'", script)
        self.assertIn("sacs.scope_key = CONCAT('episode:', pe.episode_id)", script)
        self.assertIn("sacs_signal.summary_type = 'episode_character_signals'", script)
        self.assertIn("sacs_signal.scope_key = CONCAT('episode:', pe.episode_id)", script)
        self.assertIn("sacs_scene.summary_type = 'episode_scene_extraction'", script)
        self.assertIn("sacs_scene.scope_key = CONCAT('episode:', pe.episode_id)", script)
        self.assertIn("'$.status'", script)
        self.assertIn("'$.scene_count'", script)
        self.assertIn("'$.scenes'", script)
        self.assertIn("'$.scenes[0].scene_gist'", script)
        self.assertIn("JSON_TYPE", script)
        self.assertIn("= 'ARRAY'", script)
        self.assertIn("= 'INTEGER'", script)
        self.assertIn("LOWER(TRIM(", script)
        self.assertIn("AS SIGNED", script)
        self.assertIn("sacs_scene.summary_id > sacs.summary_id", script)
        self.assertIn("IN ('ok', 'partial')", script)
        self.assertNotIn(") <> 'failed'", script)
        self.assertNotIn("AS UNSIGNED", script)
        self.assertIn("missing_open_episode_count", script)
        self.assertIn("missing_open_character_signal_count", script)
        self.assertIn("missing_open_scene_count", script)
        self.assertIn("missing_foundation_episode_count", script)
        self.assertIn("active_character_inventory_count", script)
        self.assertIn("active_character_inventory_v3_count", script)
        self.assertIn("character_asset_repair_needed", script)
        self.assertIn("character_rp_profile", script)
        self.assertIn("character_rp_examples", script)
        self.assertIn("JSON_TABLE", script)
        self.assertIn("repair_scene_participant.character_scope_key = repair_inventory.scope_key", script)
        self.assertIn("repair_scene_actor.character_scope_key = repair_inventory.scope_key", script)
        self.assertIn("repair_example_item.example_text", script)
        self.assertIn("--repair-character-assets", script)
        self.assertNotIn("MAX(pe.episode_no)", script)
        self.assertNotIn("p.price_type = 'free'", script)

    def test_shell_cohort_literals_match_character_chat_policy_ssot(self):
        script = _batch_sh()

        minimum_match = re.search(r"HAVING COUNT\(\*\) >= (\d+)", script)
        cutoff_match = re.search(
            r">= '([^']+)'\s*\n\s*\) collection_cohort",
            script,
        )

        self.assertIsNotNone(minimum_match)
        self.assertIsNotNone(cutoff_match)
        self.assertEqual(
            int(minimum_match.group(1)),
            CHARACTER_CHAT_MINIMUM_OPEN_EPISODE_COUNT,
        )
        self.assertEqual(
            cutoff_match.group(1),
            CHARACTER_CHAT_FIRST_PUBLIC_EPISODE_AT,
        )

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
        self.assertIn("missing_open_scene_count > 0", script)
        self.assertIn("context_status = 'failed'", script)
        self.assertIn("missing_foundation_episode_count = 0", script)
        self.assertIn("active_character_inventory_count > 0", script)
        self.assertIn("active_character_inventory_v3_count > 0", script)
        self.assertIn("character_asset_repair_needed > 0", script)
        self.assertIn("candidates.character_asset_repair_needed ASC", script)
        failed_priority = "WHEN candidates.context_status = 'failed' THEN 0"
        large_backlog_priority = "WHEN candidates.missing_foundation_episode_count >= ${BACKLOG_PRIORITY_THRESHOLD} THEN 1"
        small_delta_priority = "WHEN candidates.missing_foundation_episode_count > 0 OR candidates.missing_open_scene_count > 0 THEN 2"
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
        self.assertIn(
            "candidates.missing_open_scene_count DESC",
            script,
        )
        self.assertLess(
            script.index("COALESCE(candidates.last_built_at, '1970-01-01') ASC"),
            script.index(failed_priority),
        )
        self.assertLess(
            script.index("COALESCE(candidates.last_built_at, '1970-01-01') ASC"),
            script.index("candidates.missing_open_scene_count DESC"),
        )
        self.assertNotIn(
            "CASE WHEN candidates.missing_open_episode_count <= ${MAX_DELTA_EPISODES} THEN 0 ELSE 1 END ASC",
            script,
        )
        self.assertNotIn("missing_open_episode_count > ${MAX_DELTA_EPISODES} THEN 1", script)
        self.assertNotIn('missing_open_episode_count BETWEEN 1 AND ${MAX_MISSING_EPISODES}', script)
        self.assertNotIn("--build-mode full", script)
