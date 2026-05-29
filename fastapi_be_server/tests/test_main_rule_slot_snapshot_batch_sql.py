from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _batch_sql() -> str:
    return (
        ROOT / "dist" / "batch" / "main_rule_slot_snapshot_batch.sql"
    ).read_text(encoding="utf-8")


def _batch_file(path: str) -> str:
    return (ROOT / "dist" / "batch" / path).read_text(encoding="utf-8")


def _dist_file(path: str) -> str:
    return (ROOT / "dist" / path).read_text(encoding="utf-8")


class MainRuleSlotSnapshotBatchSqlTest(unittest.TestCase):
    def test_snapshot_window_is_daily(self):
        sql = _batch_sql()

        self.assertIn("SET @snapshot_ref_at = CURDATE();", sql)
        self.assertIn("SET @snapshot_start_date = @snapshot_ref_at;", sql)
        self.assertIn("SET @snapshot_end_date = @snapshot_ref_at;", sql)
        self.assertNotIn("MOD(DATEDIFF(@snapshot_ref_at, @anchor_date), 3)", sql)
        self.assertNotIn("INTERVAL 2 DAY", sql)

    def test_rule_slot_candidate_thresholds_are_preserved(self):
        sql = _batch_sql()

        self.assertIn("s.slot_key = 'free-new-3up'", sql)
        self.assertIn("s.slot_key = 'free-binge-10up'", sql)
        self.assertIn("COALESCE(ep_count.open_episode_count, 0) >= 3", sql)
        self.assertIn("p.created_date >= DATE_SUB(@snapshot_ref_at, INTERVAL 3 DAY)", sql)
        self.assertIn("COALESCE(ep_count.open_episode_count, 0) >= 10", sql)
        self.assertIn("p.last_episode_date >= DATE_SUB(@snapshot_ref_at, INTERVAL 7 DAY)", sql)

    def test_snapshot_rebuilds_after_refresh_window(self):
        sql = _batch_sql()

        self.assertIn("SET @snapshot_refresh_after_minutes = 330;", sql)
        self.assertIn("MAX(updated_date)", sql)
        self.assertIn("INTO @current_snapshot_last_updated_at", sql)
        self.assertIn(
            "TIMESTAMPDIFF(MINUTE, @current_snapshot_last_updated_at, NOW()) < @snapshot_refresh_after_minutes",
            sql,
        )

    def test_main_rule_slot_cron_runs_four_times_daily(self):
        prod_cron = _batch_file("cron_job.sh")
        dev_cron = _batch_file("cron_job.dev.sh")

        self.assertIn("45 1,7,13,19 * * *  bash /app/dist/batch/main_rule_slot_snapshot_batch.sh", prod_cron)
        self.assertIn(
            "45 1,7,13,19 * * * ln-admin bash /home/ln-admin/likenovel/batch-dev/main_rule_slot_snapshot_batch.sh",
            dev_cron,
        )

    def test_prod_deploy_ensures_main_rule_slot_cron_line(self):
        run_be = _dist_file("run_be.sh")

        self.assertIn(
            "MAIN_RULE_SLOT_CRON_LINE='45 1,7,13,19 * * * bash /home/ln-admin/likenovel/batch/main_rule_slot_snapshot_batch.sh",
            run_be,
        )
        self.assertIn(
            'grep -Fv "/home/ln-admin/likenovel/batch/main_rule_slot_snapshot_batch.sh" || true',
            run_be,
        )
