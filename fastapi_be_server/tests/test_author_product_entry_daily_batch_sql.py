from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _batch_sql() -> str:
    return (
        ROOT / "dist" / "batch" / "author_product_entry_daily_batch.sql"
    ).read_text(encoding="utf-8")


def _batch_sh() -> str:
    return (
        ROOT / "dist" / "batch" / "author_product_entry_daily_batch.sh"
    ).read_text(encoding="utf-8")


def _migration_sql() -> str:
    return (
        ROOT / "dist" / "init" / "101-create-author-product-entry-daily.sql"
    ).read_text(encoding="utf-8")


def _cron_job() -> str:
    return (ROOT / "dist" / "batch" / "cron_job.sh").read_text(encoding="utf-8")


class AuthorProductEntryDailyBatchSqlTest(unittest.TestCase):
    def test_author_product_entry_batch_reads_raw_pv_and_writes_own_mart_only(self):
        sql = _batch_sql().lower()

        self.assertIn("tb_site_page_view_event", sql)
        self.assertIn("tb_author_product_entry_daily", sql)
        self.assertNotIn("tb_product_hit_snapshot_hourly", sql)
        self.assertNotIn("tb_product_episode_hit_snapshot_hourly", sql)
        self.assertNotIn("tb_product_order", sql)

    def test_author_product_entry_batch_is_idempotent_for_target_date(self):
        sql = _batch_sql().lower()

        self.assertIn("set time_zone = '+09:00'", sql)
        self.assertIn("@author_product_entry_target_date", sql)
        self.assertIn("delete from tb_author_product_entry_daily", sql)
        self.assertIn("stat_date = @author_product_entry_target_date", sql)
        self.assertEqual(sql.count("insert into tb_author_product_entry_daily"), 1)

    def test_author_product_entry_batch_rebuild_is_transactional(self):
        sql = _batch_sql().lower()

        self.assertIn("start transaction", sql)
        self.assertIn("commit", sql)
        self.assertLess(sql.index("start transaction"), sql.index(" for update"))
        self.assertLess(sql.index("start transaction"), sql.index("set a.completed_yn = 'n'"))
        self.assertLess(sql.index("start transaction"), sql.index("delete from tb_author_product_entry_daily"))
        self.assertLess(sql.index("insert into tb_author_product_entry_daily"), sql.index("commit"))

    def test_author_product_entry_batch_groups_public_sources(self):
        sql = _batch_sql().lower()

        self.assertIn("route_group = 'product_detail'", sql)
        self.assertIn("coalesce(pv.entry_source_group, 'other')", sql)
        self.assertIn("count(distinct pv.session_id)", sql)
        self.assertIn("count(distinct pv.visitor_id)", sql)

    def test_author_product_entry_shell_uses_advisory_lock_and_manual_date(self):
        script = _batch_sh()

        self.assertIn("run_sql_with_advisory_lock", script)
        self.assertIn("lk_author_product_entry_daily_batch", script)
        self.assertIn("BATCH_DATE", script)
        self.assertIn("author_product_entry_daily_batch.sql", script)

    def test_author_product_entry_migration_creates_mart(self):
        sql = _migration_sql().lower()

        self.assertIn("create table if not exists tb_author_product_entry_daily", sql)
        self.assertIn("stat_date", sql)
        self.assertIn("product_id", sql)
        self.assertIn("entry_source_group", sql)
        self.assertIn("detail_session_count", sql)
        self.assertIn("detail_visitor_count", sql)
        self.assertIn("unique key uk_author_product_entry_daily", sql)

    def test_author_product_entry_batch_is_registered_after_dropoff_batch(self):
        cron = _cron_job()

        dropoff_line = "ai_product_episode_dropoff_daily_batch.sh"
        author_entry_line = "author_product_entry_daily_batch.sh"

        self.assertIn(author_entry_line, cron)
        self.assertLess(cron.index(dropoff_line), cron.index(author_entry_line))
