from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _batch_sql() -> str:
    return (
        ROOT / "dist" / "batch" / "service_reset_hourly_batch.sql"
    ).read_text(encoding="utf-8")


class ServiceResetHourlyBatchSqlTest(unittest.TestCase):
    def test_recent_24h_snapshot_uses_real_product_columns(self):
        sql = _batch_sql()

        self.assertIn("INSERT INTO tb_product_hit_snapshot_hourly", sql)
        self.assertIn("INSERT INTO tb_product_episode_hit_snapshot_hourly", sql)
        self.assertIn("e.use_yn = 'Y'", sql)
        self.assertNotIn("p.use_yn", sql)
