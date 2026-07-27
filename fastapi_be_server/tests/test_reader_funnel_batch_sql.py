from pathlib import Path
import unittest

from app.models.product import ProductDetailFunnelDaily, ProductEpisodeDropoffDaily
from app.models.statistics import AuthorProductEntryDaily
from app.utils.auto_migrate import _parse_statements


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8").lower()


class ReaderFunnelBatchSqlTest(unittest.TestCase):
    def test_audience_migration_has_all_additive_mart_columns(self):
        sql = _read("dist/init/106-add-author-funnel-audience-columns.sql")

        expected_columns = {
            "metric_version",
            "guest_detail_view_count",
            "guest_detail_session_count",
            "guest_detail_visitor_count",
            "guest_detail_view_session_count",
            "guest_detail_to_view_session_count",
            "guest_detail_exit_session_count",
            "guest_episode_exit_event_count",
            "guest_read_start_count",
            "guest_episode_dropoff_count",
            "guest_near_complete_count",
        }
        for column in expected_columns:
            self.assertIn(column, sql)
        self.assertGreaterEqual(sql.count("information_schema.columns"), 11)
        self.assertNotIn("add unique", sql)
        self.assertGreater(
            len(_parse_statements(sql)),
            20,
            "guarded ALTER migration must remain parseable statement-by-statement",
        )

    def test_audience_mart_models_match_additive_columns(self):
        model_columns = {
            *AuthorProductEntryDaily.__table__.columns.keys(),
            *ProductDetailFunnelDaily.__table__.columns.keys(),
            *ProductEpisodeDropoffDaily.__table__.columns.keys(),
        }
        expected_columns = {
            "metric_version",
            "guest_detail_view_count",
            "guest_detail_session_count",
            "guest_detail_visitor_count",
            "guest_detail_view_session_count",
            "guest_detail_to_view_session_count",
            "guest_detail_exit_session_count",
            "guest_episode_exit_event_count",
            "guest_read_start_count",
            "guest_episode_dropoff_count",
            "guest_near_complete_count",
        }

        self.assertTrue(expected_columns <= model_columns)

    def test_guest_lane_uses_guest_raw_and_kst_cutover(self):
        for relative_path in (
            "dist/batch/ai_product_detail_funnel_daily_batch.sql",
            "dist/batch/ai_product_episode_dropoff_daily_batch.sql",
        ):
            sql = _read(relative_path)
            self.assertIn("set time_zone = '+09:00'", sql)
            self.assertIn("tb_site_reader_funnel_event", sql)
            self.assertIn("audience_type_at_start = 'guest'", sql)
            self.assertIn("event_type = 'episode_start'", sql)
            self.assertIn("tb_site_reader_funnel_config", sql)
            self.assertIn("c.config_key = 'author_guest_funnel_v2'", sql)
            self.assertNotIn("date(min(e.created_date))", sql)
            self.assertIn("@metric_version", sql)

    def test_guest_episode_sessions_dedupe_start_exit_and_complete(self):
        for relative_path in (
            "dist/batch/ai_product_detail_funnel_daily_batch.sql",
            "dist/batch/ai_product_episode_dropoff_daily_batch.sql",
        ):
            sql = _read(relative_path)
            self.assertIn(
                "min(case when e.event_type = 'episode_start' then e.occurred_at end)",
                sql,
            )
            self.assertIn(
                "max(case when e.event_type = 'episode_exit' then e.active_ms end)",
                sql,
            )
            self.assertIn(
                "max(case when e.event_type = 'episode_exit' then e.progress_ratio end)",
                sql,
            )
            self.assertIn(
                "max(case when e.event_type = 'episode_complete' then 1 else 0 end)",
                sql,
            )
            self.assertIn("e.viewer_session_id", sql)
            self.assertIn(
                "start_event.viewer_session_id = e.viewer_session_id",
                sql,
            )
            self.assertIn(
                "start_event.audience_type_at_start = 'guest'",
                sql,
            )

    def test_guest_detail_events_require_prior_matching_pv_within_sixty_minutes(self):
        sql = _read("dist/batch/ai_product_detail_funnel_daily_batch.sql")

        self.assertIn("tb_site_page_view_event", sql)
        self.assertIn("pv.visitor_id = s.visitor_id", sql)
        self.assertIn("pv.browser_session_id = s.browser_session_id", sql)
        self.assertIn("pv.product_id = s.product_id", sql)
        self.assertIn("s.started_at <= date_add(pv.event_at, interval 60 minute)", sql)
        self.assertIn("e.event_type = 'product_detail_exit'", sql)
        self.assertIn("e.destination_group = 'other_product'", sql)
        self.assertNotIn("e.destination_group = 'other_product_detail'", sql)
        self.assertIn("group by\n        date(pv.event_at),", sql)
        self.assertIn("pv.browser_session_id", sql)
        self.assertIn("count(*) as detail_view_raw_count", sql)

    def test_guest_dropoff_requires_explicit_qualified_exit(self):
        sql = _read("dist/batch/ai_product_episode_dropoff_daily_batch.sql")

        self.assertIn("s.exit_active_ms >= 3000", sql)
        self.assertIn("s.exit_progress_ratio < 0.95", sql)
        self.assertIn("s.completed_yn = 0", sql)
        self.assertIn(
            "s.completed_yn = 1 or s.exit_progress_ratio >= 0.95",
            sql,
        )
        self.assertNotIn("lead(", sql)

    def test_marts_stage_then_delete_and_insert_target_date(self):
        contracts = (
            (
                "dist/batch/ai_product_detail_funnel_daily_batch.sql",
                "create temporary table tmp_product_detail_funnel_daily",
                "delete from tb_product_detail_funnel_daily",
                "insert into tb_product_detail_funnel_daily",
            ),
            (
                "dist/batch/ai_product_episode_dropoff_daily_batch.sql",
                "create temporary table tmp_product_episode_dropoff_daily",
                "delete from tb_product_episode_dropoff_daily",
                "insert into tb_product_episode_dropoff_daily",
            ),
        )
        for relative_path, stage, delete, insert in contracts:
            sql = _read(relative_path)
            self.assertLess(sql.index(stage), sql.index(delete))
            self.assertLess(sql.index(delete), sql.index(insert))
            self.assertNotIn("on duplicate key update", sql)
