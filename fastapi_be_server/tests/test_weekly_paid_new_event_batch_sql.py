from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
BATCH_DIR = ROOT / "dist" / "batch"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class WeeklyPaidNewEventBatchSqlTest(unittest.TestCase):
    def test_event_title_pattern_matches_home_ticker_pattern(self):
        sql = _read(BATCH_DIR / "weekly_paid_new_event_batch.sql")
        ticker = _read(ROOT / "app" / "services" / "product" / "home_ticker_service.py")

        ticker_pattern = re.search(
            r'WEEKLY_PAID_NEW_EVENT_TITLE_PATTERN = \(\s*r"([^"]+)"\s*\)', ticker
        ).group(1)
        sql_pattern = re.search(r"SET @event_title_pattern = '([^']+)';", sql).group(1)

        self.assertEqual(sql_pattern, ticker_pattern)

    def test_update_only_when_single_event_and_this_week_conversions_exist(self):
        sql = _read(BATCH_DIR / "weekly_paid_new_event_batch.sql")

        self.assertIn("AND @event_match_count = 1", sql)
        self.assertIn("AND @product_ids IS NOT NULL", sql)
        self.assertIn("p.paid_open_date >= @week_start", sql)
        self.assertIn("p.paid_open_date < @week_end", sql)
        self.assertIn("p.paid_open_date <= @batch_now", sql)
        self.assertIn("p.price_type = 'paid'", sql)
        self.assertIn("p.open_yn = 'Y'", sql)
        self.assertIn("p.blind_yn = 'N'", sql)

    def test_week_number_uses_thursday_month(self):
        sql = _read(BATCH_DIR / "weekly_paid_new_event_batch.sql")

        self.assertIn("SET @week_thursday = DATE_ADD(@week_start, INTERVAL 3 DAY);", sql)
        self.assertIn("MONTH(@week_thursday), '월 '", sql)
        self.assertIn("FLOOR((DAY(@week_thursday) - 1) / 7) + 1, '주차 유료화 신작'", sql)

    def test_wrapper_fails_when_event_match_is_not_single(self):
        script = _read(BATCH_DIR / "weekly_paid_new_event_batch.sh")

        self.assertIn('if [ "$event_match_count" != "1" ]; then', script)
        self.assertIn("exit 1", script)

    def test_cron_runs_in_prod_template_and_stays_disabled_in_dev(self):
        prod_cron = _read(BATCH_DIR / "cron_job.sh")
        dev_cron = _read(BATCH_DIR / "cron_job.dev.sh")

        self.assertIn(
            "*/10 * * * *  bash /app/dist/batch/weekly_paid_new_event_batch.sh",
            prod_cron,
        )
        self.assertIn(
            "# */10 * * * *  ln-admin bash /home/ln-admin/likenovel/batch-dev/weekly_paid_new_event_batch.sh",
            dev_cron,
        )


if __name__ == "__main__":
    unittest.main()
