from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _batch_sql() -> str:
    return (
        ROOT / "dist" / "batch" / "main_rule_slot_snapshot_batch.sql"
    ).read_text(encoding="utf-8")


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
