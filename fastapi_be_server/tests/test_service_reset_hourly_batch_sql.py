from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _batch_sql() -> str:
    return (
        ROOT / "dist" / "batch" / "service_reset_hourly_batch.sql"
    ).read_text(encoding="utf-8")


def _section(sql: str, start_marker: str, end_marker: str) -> str:
    start = sql.index(start_marker)
    end = sql.index(end_marker, start)
    return sql[start:end]


class ServiceResetHourlyBatchSqlTest(unittest.TestCase):
    def test_recent_24h_snapshot_uses_real_product_columns(self):
        sql = _batch_sql()

        self.assertIn("INSERT INTO tb_product_hit_snapshot_hourly", sql)
        self.assertIn("INSERT INTO tb_product_episode_hit_snapshot_hourly", sql)
        self.assertIn("e.use_yn = 'Y'", sql)
        self.assertNotIn("p.use_yn", sql)

    def test_top_rank_basis_uses_public_episode_count_and_reservation_signal(self):
        sql = _batch_sql()

        self.assertIn("CREATE TEMPORARY TABLE tmp_product_rank_basis AS", sql)
        self.assertIn("AS open_episode_count", sql)
        self.assertIn("b.open_yn = 'Y'", sql)
        self.assertIn("b.use_yn = 'Y'", sql)
        self.assertIn("AS latest_open_at", sql)
        self.assertIn("AS next_reserved_at", sql)
        self.assertIn("b.publish_reserve_date > @rank_freshness_basis_at", sql)
        self.assertIn("ep.open_episode_count >= 3", sql)
        self.assertNotIn("b.episode_no >= 5", sql)

    def test_serial_top_areas_require_ongoing_recent_or_reserved_products(self):
        sql = _batch_sql()
        free_serial = _section(sql, "-- 무료연재 Top 랭킹 재계산", "-- 유료연재 Top 랭킹 재계산")
        paid_serial = _section(sql, "-- 유료연재 Top 랭킹 재계산", "-- 연재완결 Top 랭킹 재계산")

        for section in (free_serial, paid_serial):
            self.assertIn("y.status_code = 'ongoing'", section)
            self.assertNotIn("y.status_code in ('ongoing', 'rest')", section)
            self.assertIn("filtered.open_episode_count >= 3", section)
            self.assertIn("filtered.latest_open_at >= DATE_SUB(@rank_freshness_basis_at, INTERVAL 30 DAY)", section)
            self.assertIn("filtered.next_reserved_at IS NOT NULL", section)

    def test_freshness_gate_does_not_mutate_product_status(self):
        sql = _batch_sql().lower()

        self.assertNotIn("set status_code = 'stop'", sql)
        self.assertNotIn('set status_code = "stop"', sql)
        self.assertNotIn("update tb_product set status_code", sql)
