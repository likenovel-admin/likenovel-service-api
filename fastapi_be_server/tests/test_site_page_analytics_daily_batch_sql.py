from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _batch_sql() -> str:
    return (
        ROOT / "dist" / "batch" / "site_page_analytics_daily_batch.sql"
    ).read_text(encoding="utf-8")


def _batch_sh() -> str:
    return (
        ROOT / "dist" / "batch" / "site_page_analytics_daily_batch.sh"
    ).read_text(encoding="utf-8")


def _advisory_lock_sh() -> str:
    return (
        ROOT / "dist" / "batch" / "batch_advisory_lock.sh"
    ).read_text(encoding="utf-8")


class SitePageAnalyticsDailyBatchSqlTest(unittest.TestCase):
    def test_site_page_analytics_batch_is_independent_from_hot_product_tables(self):
        sql = _batch_sql().lower()

        self.assertIn("tb_site_page_view_event", sql)
        self.assertIn("tb_site_page_dwell_event", sql)
        self.assertIn("tb_site_page_route_daily", sql)
        self.assertNotIn("tb_product", sql)
        self.assertNotIn("tb_product_episode", sql)
        self.assertNotIn("tb_user_product_usage", sql)
        self.assertNotIn("tb_product_order", sql)

    def test_site_page_analytics_batch_is_idempotent_for_target_date(self):
        sql = _batch_sql().lower()

        self.assertIn("set time_zone = '+09:00'", sql)
        self.assertIn("@site_page_analytics_target_date", sql)
        self.assertIn("delete from tb_site_page_route_daily", sql)
        self.assertIn("stat_date = @site_page_analytics_target_date", sql)
        self.assertIn("insert into tb_site_page_route_daily", sql)

    def test_site_page_analytics_shell_uses_advisory_lock_and_manual_date(self):
        script = _batch_sh()

        self.assertIn("run_sql_with_advisory_lock", script)
        self.assertIn("lk_site_page_analytics_daily_batch", script)
        self.assertIn("BATCH_DATE", script)
        self.assertIn('source "${SCRIPT_DIR}/cron_env.sh"', script)
        self.assertIn("site_page_analytics_daily_batch.sql", script)

    def test_site_page_analytics_advisory_lock_does_not_use_coproc_session(self):
        script = _advisory_lock_sh()

        self.assertNotIn("coproc", script)
        self.assertIn("IS_USED_LOCK", script)
        self.assertIn("GET_LOCK", script)
        self.assertIn("RELEASE_LOCK", script)
        self.assertIn("mktemp /tmp/likenovel_batch_advisory_lock", script)
