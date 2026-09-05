from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

from app.services.websochat.character_chat_product_policy import (
    CHARACTER_CHAT_FIRST_PUBLIC_EPISODE_AT,
    CHARACTER_CHAT_MAX_COLLECTED_PUBLIC_EPISODES,
    CHARACTER_CHAT_MINIMUM_OPEN_EPISODE_COUNT,
)


ROOT = Path(__file__).resolve().parents[1]


def _batch_sh() -> str:
    return (
        ROOT / "dist" / "batch" / "build_story_agent_context_batch.sh"
    ).read_text(encoding="utf-8")


def _builder_py() -> str:
    return (ROOT / "scripts" / "build_story_agent_context.py").read_text(
        encoding="utf-8"
    )


def _recommendation_service_py() -> str:
    return (
        ROOT / "app" / "services" / "ai" / "recommendation_service.py"
    ).read_text(encoding="utf-8")


class StoryAgentContextBatchSqlTest(unittest.TestCase):
    def test_action_manifest_validation_fails_closed_before_candidate_selection(self):
        script = _batch_sh()
        manifest_guard = script[script.index('SCHEDULED_REPAIR_IDS_SQL=0'):script.index('if ! CANDIDATE_OUTPUT=')]
        for manifest, provider_rc, expected_rc in (
            ("v1|0|0", 0, 0),
            ("v1|0,1174|0,1196", 0, 0),
            ("v2|0|0", 0, 1),
            ("v1|0,-1|0", 0, 1),
            ("v1|0,1);DROP TABLE x|0", 0, 1),
            ("", 0, 1),
            ("v1|0|0", 42, 1),
        ):
            with self.subTest(manifest=manifest, provider_rc=provider_rc):
                result = subprocess.run(
                    ["bash", "-c", 'set -uo pipefail\nlog() { :; }\nfake_python() { printf "%s\\n" "$MANIFEST"; return "$PROVIDER_RC"; }\nPYTHON_BIN=fake_python\nAPI_ROOT=/nonexistent\n' + manifest_guard + '\nprintf "selected:%s|%s" "$SCHEDULED_REPAIR_IDS_SQL" "$SCHEDULED_BLOCKED_IDS_SQL"'],
                    env={**os.environ, "BUILD_MODE": "delta", "MANIFEST": manifest, "PROVIDER_RC": str(provider_rc)},
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, expected_rc, result.stderr)
                if expected_rc:
                    self.assertNotIn("selected:", result.stdout)
                else:
                    self.assertEqual(result.stdout, "selected:" + manifest.removeprefix("v1|"))

    def test_guarded_full_does_not_invoke_scheduled_manifest(self):
        script = _batch_sh()
        guard = script[script.index('SCHEDULED_REPAIR_IDS_SQL=0'):script.index('if ! CANDIDATE_OUTPUT=')]
        result = subprocess.run(
            ["bash", "-c", 'set -uo pipefail\nfake_python() { echo unexpected-invocation; return 42; }\nlog() { :; }\nPYTHON_BIN=fake_python\nAPI_ROOT=/nonexistent\nBUILD_MODE=full\n' + guard + '\nprintf "%s|%s" "$SCHEDULED_REPAIR_IDS_SQL" "$SCHEDULED_BLOCKED_IDS_SQL"'],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "0|0")
        self.assertIn("ELSE\n    CASE WHEN collection_cohort.product_id IS NULL THEN 0 ELSE (", script)
        full_predicate = script.split("ELSE\n    CASE WHEN collection_cohort.product_id IS NULL", 1)[1].split("END AS character_asset_repair_needed", 1)[0]
        self.assertIn("repair_inventory", full_predicate)
        self.assertNotIn("SCHEDULED_", full_predicate)
        self.assertNotIn("public_episode_rank", full_predicate)

    def test_candidate_query_failure_exits_nonzero(self):
        script = _batch_sh()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            batch_dir = root / "dist" / "batch"
            scripts_dir = root / "scripts"
            bin_dir = root / "bin"
            batch_dir.mkdir(parents=True)
            scripts_dir.mkdir(parents=True)
            (scripts_dir / "audit_character_chat_asset_readiness_db.py").write_text("print('v1|0|0')\n", encoding="utf-8")
            bin_dir.mkdir()

            batch_path = batch_dir / "build_story_agent_context_batch.sh"
            batch_path.write_text(script, encoding="utf-8")
            (scripts_dir / "build_story_agent_context.py").write_text("", encoding="utf-8")
            mysql_path = bin_dir / "mysql"
            mysql_path.write_text(
                "#!/bin/sh\n"
                "query=$(cat)\n"
                "case \"$query\" in\n"
                "  *REVIEW_REQUIRED:*) exit 0 ;;\n"
                "  *) exit 42 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
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

        self.assertIn("public_episode.use_yn = 'Y'", script)
        self.assertIn("public_episode.open_yn = 'Y'", script)
        self.assertIn("ROW_NUMBER() OVER (", script)
        self.assertIn("AS public_episode_rank", script)
        self.assertIn("p.price_type IN ('free', 'paid')", script)
        self.assertIn("p.status_code IN ('ongoing', 'end')", script)
        self.assertNotIn("'rest'", script)
        self.assertNotIn("'stop'", script)
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
        self.assertNotIn(
            "collection_cohort.product_id IS NOT NULL\n"
            "      OR COALESCE(sacp.context_status, 'pending') = 'ready'",
            script,
        )
        self.assertIn(
            "CASE WHEN p.product_id IN (${SCHEDULED_REPAIR_IDS_SQL}) THEN 1 ELSE 0 END",
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
        self.assertIn("active_open_character_signal_count", script)
        self.assertIn("missing_open_scene_count", script)
        self.assertIn("missing_foundation_episode_count", script)
        self.assertIn("active_character_inventory_count", script)
        self.assertIn("active_character_inventory_v3_count", script)
        self.assertIn("inventory_reaggregation_needed", script)
        self.assertIn("character_asset_repair_needed", script)
        self.assertIn("JSON_TABLE", script)
        self.assertIn("--scheduled-action-ids", script)
        self.assertIn("AND ('${BUILD_MODE}' = 'full' OR pe.public_episode_rank <= ${CHAT_ASSET_TARGET_EPISODES})", script)
        self.assertNotIn("FROM tb_story_agent_context_summary capped_signal", script)
        self.assertNotIn("capped_character.character_scope_key = repair_inventory.scope_key", script)
        self.assertIn("CASE WHEN '${BUILD_MODE}' = 'delta' THEN", script)
        self.assertIn("--repair-character-assets", script)
        self.assertIn("--reaggregate-character-inventory", script)
        self.assertNotIn("MAX(pe.episode_no)", script)
        self.assertNotIn("p.price_type = 'free'", script)

    def test_inventory_only_drift_is_selected_for_reaggregation(self):
        script = _batch_sh()

        self.assertRegex(
            script,
            r"active_open_character_signal_count > 0\s+"
            r"AND \(\s+active_character_inventory_count = 0\s+"
            r"OR active_character_inventory_v3_count = 0\s+\)",
        )
        self.assertIn("END AS inventory_reaggregation_needed", script)

    def test_stale_identity_review_only_suppresses_identity_dependent_work(self):
        script = _batch_sh()

        self.assertIn("character_identity_review_required", script)
        self.assertIn("'$.operations[*].signal_anchors[*]'", script)
        self.assertIn("review_anchor.summary_id", script)
        self.assertIn("review_anchor.source_hash", script)
        self.assertIn(
            "WHEN candidates.character_identity_review_required > 0 THEN 0",
            script,
        )

    def test_stale_review_scan_is_index_bounded_before_candidate_query(self):
        script = _batch_sh()

        self.assertIn("REVIEW_REQUIRED_OUTPUT", script)
        self.assertIn("REVIEW_REQUIRED_PRODUCT_IDS_SQL", script)
        self.assertIn(
            "FROM tb_story_agent_context_product review_product\n"
            "STRAIGHT_JOIN tb_story_agent_context_summary identity_review",
            script,
        )
        self.assertIn(
            "FORCE INDEX (idx_story_agent_context_summary_product_type)",
            script,
        )
        self.assertLess(
            script.index("REVIEW_REQUIRED_OUTPUT"),
            script.index("CANDIDATE_OUTPUT"),
        )
        self.assertIn(
            "p.product_id IN (${REVIEW_REQUIRED_PRODUCT_IDS_SQL},${SCHEDULED_BLOCKED_IDS_SQL})",
            script,
        )
        self.assertIn(
            "missing_foundation_episode_count > 0\n"
            "    OR (\n"
            "      character_identity_review_required = 0",
            script,
        )

    def test_suppressed_stale_review_is_still_counted_for_monitoring(self):
        script = _batch_sh()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            batch_dir = root / "dist" / "batch"
            scripts_dir = root / "scripts"
            bin_dir = root / "bin"
            batch_dir.mkdir(parents=True)
            scripts_dir.mkdir(parents=True)
            (scripts_dir / "audit_character_chat_asset_readiness_db.py").write_text("print('v1|0|0')\n", encoding="utf-8")
            bin_dir.mkdir()

            batch_path = batch_dir / "build_story_agent_context_batch.sh"
            batch_path.write_text(script, encoding="utf-8")
            (scripts_dir / "build_story_agent_context.py").write_text(
                "", encoding="utf-8"
            )
            mysql_path = bin_dir / "mysql"
            mysql_path.write_text(
                "#!/bin/sh\n"
                "query=$(cat)\n"
                "case \"$query\" in\n"
                "  *REVIEW_REQUIRED:*) printf 'REVIEW_REQUIRED:1176\\n' ;;\n"
                "  *) exit 0 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
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

            self.assertEqual(result.returncode, 0, result.stderr)
            log = log_path.read_text(encoding="utf-8")
            self.assertIn("[batch-empty] no eligible products", log)
            self.assertIn(
                "ready=0 review_required=1 deferred=0 failed=0",
                log,
            )

    def test_reaggregation_candidate_flag_reaches_delta_cli(self):
        script = _batch_sh()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            batch_dir = root / "dist" / "batch"
            scripts_dir = root / "scripts"
            venv_bin_dir = root / ".venv" / "bin"
            bin_dir = root / "bin"
            batch_dir.mkdir(parents=True)
            scripts_dir.mkdir(parents=True)
            venv_bin_dir.mkdir(parents=True)
            bin_dir.mkdir()

            batch_path = batch_dir / "build_story_agent_context_batch.sh"
            batch_path.write_text(script, encoding="utf-8")
            (scripts_dir / "build_story_agent_context.py").write_text("", encoding="utf-8")

            mysql_path = bin_dir / "mysql"
            mysql_path.write_text(
                "#!/bin/sh\nprintf '1112\\tTest title\\t0\\t1\\n'\n",
                encoding="utf-8",
            )
            mysql_path.chmod(0o755)

            args_path = root / "python-args.txt"
            python_path = venv_bin_dir / "python"
            python_path.write_text(
                "#!/bin/sh\ncase \"$1\" in *audit_character_chat*) echo 'v1|0|0'; exit 0 ;; esac\n"
                "printf '%s\\n' \"$@\" > \"$ARGS_FILE\"\n",
                encoding="utf-8",
            )
            python_path.chmod(0o755)

            log_path = root / "batch.log"
            result = subprocess.run(
                ["bash", str(batch_path)],
                env={
                    **os.environ,
                    "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                    "ARGS_FILE": str(args_path),
                    "DB_HOST": "example.invalid",
                    "DB_PORT": "3306",
                    "DB_USER": "test-user",
                    "DB_PW": "test-password",
                    "DB_NAME": "likenovel",
                    "OPENROUTER_API_KEY": "test-key",
                    "STORYCTX_LOCK_DIR": str(root / "batch.lock"),
                    "STORYCTX_LOG_FILE": str(log_path),
                    "STORYCTX_MAX_PARALLEL": "1",
                },
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            args = args_path.read_text(encoding="utf-8").splitlines()
            self.assertIn("--reaggregate-character-inventory", args)
            self.assertNotIn("--repair-character-assets", args)

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
        self.assertIn("END AS inventory_reaggregation_needed", script)
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

    def test_candidate_priority_caps_character_assets_at_thirty_public_episodes(self):
        script = _batch_sh()

        self.assertIn(
            f'CHAT_ASSET_TARGET_EPISODES="{CHARACTER_CHAT_MAX_COLLECTED_PUBLIC_EPISODES}"',
            script,
        )
        self.assertIn("websochat_asset_request", script)
        self.assertIn("recent_user_demand_at", script)
        self.assertIn("FROM tb_user_ai_signal_event demand_event", script)
        self.assertIn(
            "GROUP BY demand_event.product_id, demand_event.episode_id",
            script,
        )
        self.assertIn("recent_demand.episode_id = pe.episode_id", script)
        self.assertIn(
            "WHEN recent_demand.recent_user_demand_at IS NOT NULL",
            script,
        )
        self.assertIn("AND sacs_signal.summary_id IS NULL", script)
        self.assertIn(
            "collection_cohort.product_id IS NOT NULL\n"
            "           AND sacs_scene.summary_id IS NULL",
            script,
        )
        self.assertIn("chat_asset_ready_episode_count", script)
        self.assertIn("chat_asset_target_episode_count", script)
        self.assertIn(
            "pe.public_episode_rank <= ${CHAT_ASSET_TARGET_EPISODES}",
            script,
        )
        self.assertIn(
            "WHEN pe.public_episode_rank <= ${CHAT_ASSET_TARGET_EPISODES} AND sacs_signal.summary_id IS NULL",
            script,
        )
        self.assertIn(
            "WHEN pe.public_episode_rank <= ${CHAT_ASSET_TARGET_EPISODES}\n"
            "       AND collection_cohort.product_id IS NOT NULL\n"
            "       AND sacs_scene.summary_id IS NULL",
            script,
        )
        self.assertIn(
            "SUM(CASE WHEN sacs.summary_id IS NULL THEN 1 ELSE 0 END) AS missing_open_episode_count",
            script,
        )
        self.assertNotIn(
            "pe.episode_no <= ${CHAT_ASSET_TARGET_EPISODES}",
            script,
        )
        self.assertIn("STORYCTX_OPENROUTER_PRIORITY_HEADROOM_USD", script)
        self.assertIn("deferred=", script)

        demand_priority = "WHEN candidates.recent_user_demand_at IS NOT NULL THEN 0"
        target_priority = (
            "WHEN candidates.chat_asset_ready_episode_count "
            "< candidates.chat_asset_target_episode_count THEN 1"
        )
        ready_count_order = "candidates.chat_asset_ready_episode_count ASC"
        last_built_order = "COALESCE(candidates.last_built_at, '1970-01-01') ASC"

        self.assertIn(demand_priority, script)
        self.assertIn(target_priority, script)
        self.assertIn(ready_count_order, script)
        self.assertLess(script.index(demand_priority), script.index(target_priority))
        self.assertLess(script.index(ready_count_order), script.index(last_built_order))

    def test_websochat_demand_signal_is_server_gated_and_deduplicated(self):
        source = _recommendation_service_py()
        demand_gate_start = source.index('if event_type == "websochat_asset_request":')
        demand_gate_end = source.index("duplicate_request_result", demand_gate_start)
        demand_gate = source[demand_gate_start:demand_gate_end]

        self.assertIn('if event_type == "websochat_asset_request":', source)
        self.assertIn("AS chat_asset_ready", demand_gate)
        self.assertIn("or chat_asset_ready", demand_gate)
        self.assertIn("AND e.open_yn = 'Y'", demand_gate)
        self.assertIn("AND p.price_type IN ('free', 'paid')", demand_gate)
        self.assertIn("AND p.status_code IN ('ongoing', 'end')", demand_gate)
        self.assertIn("COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'", demand_gate)
        self.assertIn("COALESCE(sacp.context_status, 'pending') <> 'disabled'", demand_gate)
        self.assertIn("demand.created_date >= DATE_SUB(NOW(), INTERVAL 7 DAY)", source)
        self.assertIn("SELECT p.product_id", source)
        self.assertIn("FOR UPDATE", source)
        self.assertIn("await db.rollback()", source)
        self.assertIn(
            'payload["episode_no"] = websochat_asset_request_episode_no',
            source,
        )

    def test_midrun_openrouter_reserve_propagates_to_deferred_exit(self):
        source = _builder_py()

        import_start = source.index(
            "from app.services.common.openrouter_background_credit_guard import ("
        )
        import_end = source.index(")", import_start)
        self.assertIn(
            "OpenRouterBackgroundCreditReserveError",
            source[import_start:import_end],
        )
        self.assertIn("except OpenRouterBackgroundCreditReserveError:", source)
        self.assertIn("story_agent_full_budget_deferred product_id=%s", source)
        self.assertIn("story_agent_delta_budget_deferred product_id=%s", source)
        self.assertIn("story_agent_character_asset_repair_budget_deferred", source)
        self.assertIn(
            'if int(results.get("deferred_budget") or 0) > 0:\n'
            "        return STORYCTX_DEFERRED_BUDGET_EXIT_CODE",
            source,
        )

    def test_budget_deferred_child_is_not_counted_as_failure(self):
        script = _batch_sh()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            batch_dir = root / "dist" / "batch"
            scripts_dir = root / "scripts"
            venv_bin_dir = root / ".venv" / "bin"
            bin_dir = root / "bin"
            batch_dir.mkdir(parents=True)
            scripts_dir.mkdir(parents=True)
            venv_bin_dir.mkdir(parents=True)
            bin_dir.mkdir()

            batch_path = batch_dir / "build_story_agent_context_batch.sh"
            batch_path.write_text(script, encoding="utf-8")
            (scripts_dir / "build_story_agent_context.py").write_text("", encoding="utf-8")

            mysql_path = bin_dir / "mysql"
            mysql_path.write_text(
                "#!/bin/sh\nprintf '1182\\tTest title\\t0\\t0\\t1.00\\n'\n",
                encoding="utf-8",
            )
            mysql_path.chmod(0o755)

            python_path = venv_bin_dir / "python"
            python_path.write_text("#!/bin/sh\ncase \"$1\" in *audit_character_chat*) echo 'v1|0|0'; exit 0 ;; esac\nexit 75\n", encoding="utf-8")
            python_path.chmod(0o755)

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
                    "STORYCTX_MAX_PARALLEL": "1",
                },
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            log = log_path.read_text(encoding="utf-8")
            self.assertIn("[deferred-budget] product_id=1182", log)
            self.assertIn(
                "ready=0 review_required=0 deferred=1 failed=0",
                log,
            )

    def test_review_required_child_does_not_downgrade_successful_sibling(self):
        script = _batch_sh()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            batch_dir = root / "dist" / "batch"
            scripts_dir = root / "scripts"
            venv_bin_dir = root / ".venv" / "bin"
            bin_dir = root / "bin"
            batch_dir.mkdir(parents=True)
            scripts_dir.mkdir(parents=True)
            venv_bin_dir.mkdir(parents=True)
            bin_dir.mkdir()

            batch_path = batch_dir / "build_story_agent_context_batch.sh"
            batch_path.write_text(script, encoding="utf-8")
            (scripts_dir / "build_story_agent_context.py").write_text("", encoding="utf-8")

            mysql_path = bin_dir / "mysql"
            mysql_path.write_text(
                "#!/bin/sh\n"
                "printf '1109\\tFresh review\\t0\\t0\\t1.00\\n'\n"
                "printf '1176\\tStale review\\t0\\t0\\t1.00\\n'\n",
                encoding="utf-8",
            )
            mysql_path.chmod(0o755)

            python_path = venv_bin_dir / "python"
            python_path.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in *audit_character_chat*) echo 'v1|0|0'; exit 0 ;; esac\n"
                "product_id=''\n"
                "while [ \"$#\" -gt 0 ]; do\n"
                "  if [ \"$1\" = '--product-id' ]; then product_id=\"$2\"; break; fi\n"
                "  shift\n"
                "done\n"
                "if [ \"$product_id\" = '1176' ]; then exit 76; fi\n"
                "exit 0\n",
                encoding="utf-8",
            )
            python_path.chmod(0o755)

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
                    "STORYCTX_MAX_PARALLEL": "2",
                },
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            log = log_path.read_text(encoding="utf-8")
            self.assertIn("[done] product_id=1109", log)
            self.assertIn("[review-required] product_id=1176", log)
            self.assertIn(
                "ready=1 review_required=1 deferred=0 failed=0",
                log,
            )
