from pathlib import Path
import unittest


def test_parse_statements_keeps_semicolon_inside_sql_string_literal():
    from app.utils.auto_migrate import _parse_statements

    statements = _parse_statements(
        """
        CREATE TABLE sample (
            id INT PRIMARY KEY,
            note VARCHAR(100) COMMENT 'queued/running; terminal state'
        );
        SELECT 'also; literal';
        """
    )

    assert len(statements) == 2
    assert "queued/running; terminal state" in statements[0]
    assert "also; literal" in statements[1]


def test_ai_reader_phase1_migration_parses_all_create_table_statements():
    from app.utils.auto_migrate import _parse_statements

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "dist"
        / "init"
        / "87-create-ai-reader-agent-phase1-tables.sql"
    )

    statements = _parse_statements(migration_path.read_text(encoding="utf-8"))

    assert len(statements) == 6
    assert all(statement.startswith("CREATE TABLE IF NOT EXISTS") for statement in statements)


class ProductHitSnapshotMigrationTest(unittest.TestCase):
    def test_product_hit_snapshot_migration_parses_all_create_table_statements(self):
        from app.utils.auto_migrate import _parse_statements

        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist"
            / "init"
            / "96-create-product-hit-snapshot-hourly.sql"
        )

        statements = _parse_statements(migration_path.read_text(encoding="utf-8"))

        self.assertEqual(len(statements), 2)
        self.assertTrue(
            all(
                statement.startswith("CREATE TABLE IF NOT EXISTS")
                for statement in statements
            )
        )


class SitePageViewMigrationTest(unittest.TestCase):
    def test_site_page_view_migration_parses_create_table_statement(self):
        from app.utils.auto_migrate import _parse_statements

        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist"
            / "init"
            / "97-create-site-page-view-event.sql"
        )

        statements = _parse_statements(migration_path.read_text(encoding="utf-8"))

        self.assertEqual(len(statements), 1)
        self.assertTrue(statements[0].startswith("CREATE TABLE IF NOT EXISTS"))
        self.assertIn("tb_site_page_view_event", statements[0])

    def test_site_page_view_migration_keeps_write_indexes_minimal(self):
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist"
            / "init"
            / "97-create-site-page-view-event.sql"
        )

        sql = migration_path.read_text(encoding="utf-8")

        self.assertIn("uq_site_page_view_event_event_id", sql)
        self.assertIn("idx_site_page_view_event_source_occurred", sql)
        self.assertNotIn("idx_site_page_view_event_route_occurred", sql)
        self.assertNotIn("idx_site_page_view_event_user_occurred", sql)
        self.assertNotIn("idx_site_page_view_event_session_occurred", sql)

    def test_site_page_view_marketing_attribution_migration_runs_after_base_table(
        self,
    ):
        init_dir = Path(__file__).resolve().parents[1] / "dist" / "init"
        files = sorted(path.name for path in init_dir.glob("*.sql"))

        self.assertLess(
            files.index("99-alter-site-page-route-daily-primary-key.sql"),
            files.index("99a-add-site-page-view-marketing-attribution.sql"),
        )

    def test_site_page_view_marketing_attribution_migration_adds_raw_fields(self):
        from app.utils.auto_migrate import _parse_statements

        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist"
            / "init"
            / "99a-add-site-page-view-marketing-attribution.sql"
        )

        sql = migration_path.read_text(encoding="utf-8").lower()
        statements = _parse_statements(sql)

        self.assertGreaterEqual(len(statements), 20)
        self.assertIn("add column utm_source", sql)
        self.assertIn("add column utm_medium", sql)
        self.assertIn("add column utm_campaign", sql)
        self.assertIn("add column utm_content", sql)
        self.assertIn("add column external_referrer_host", sql)
        self.assertIn("add column external_referrer_group", sql)
        self.assertIn("idx_site_page_view_event_utm_occurred", sql)
        self.assertIn("idx_site_page_view_event_referrer_occurred", sql)

    def test_site_page_view_model_has_marketing_attribution_columns(self):
        from app.models.statistics import SitePageViewEvent

        columns = set(SitePageViewEvent.__table__.columns.keys())

        self.assertIn("utm_source", columns)
        self.assertIn("utm_medium", columns)
        self.assertIn("utm_campaign", columns)
        self.assertIn("utm_content", columns)
        self.assertIn("external_referrer_host", columns)
        self.assertIn("external_referrer_group", columns)

    def test_site_statistics_batch_uses_kst_target_range_for_page_view(self):
        batch_path = (
            Path(__file__).resolve().parents[1]
            / "dist"
            / "batch"
            / "statistics_aggregation_daily_batch.sql"
        )

        sql = batch_path.read_text(encoding="utf-8")

        self.assertIn("SET time_zone = '+09:00'", sql)
        self.assertIn("@site_stats_target_start", sql)
        self.assertIn("@site_stats_target_end", sql)
        self.assertIn("pv.occurred_at >= @site_stats_target_start", sql)
        self.assertIn("pv.occurred_at < @site_stats_target_end", sql)
        self.assertNotIn("DATE(occurred_at)", sql)

    def test_site_statistics_batch_counts_dau_from_logged_in_page_views(self):
        batch_path = (
            Path(__file__).resolve().parents[1]
            / "dist"
            / "batch"
            / "statistics_aggregation_daily_batch.sql"
        )

        sql = batch_path.read_text(encoding="utf-8")

        self.assertIn(
            "COUNT(DISTINCT CASE WHEN pv.user_id IS NOT NULL THEN pv.user_id END)",
            sql,
        )
        self.assertIn("pv.user_id IS NOT NULL", sql)
        self.assertIn("pv.source = 'service-web'", sql)
        self.assertIn("pv.occurred_at >= @site_stats_target_start", sql)
        self.assertIn("pv.occurred_at < @site_stats_target_end", sql)
        self.assertIn("page_stats.dau_count as dau", sql)
        self.assertNotIn(
            "COUNT(DISTINCT CASE WHEN type = 'active' THEN user_id END) as dau",
            sql,
        )

    def test_site_statistics_batch_aggregates_page_view_and_dau_in_one_raw_scan(
        self,
    ):
        batch_path = (
            Path(__file__).resolve().parents[1]
            / "dist"
            / "batch"
            / "statistics_aggregation_daily_batch.sql"
        )

        sql = batch_path.read_text(encoding="utf-8")

        self.assertEqual(sql.count("FROM tb_site_page_view_event pv"), 1)
        self.assertIn("page_stats.page_view_count as page_view", sql)
        self.assertIn("page_stats.dau_count as dau", sql)

    def test_statistics_aggregation_shell_uses_advisory_lock(self):
        script_path = (
            Path(__file__).resolve().parents[1]
            / "dist"
            / "batch"
            / "statistics_aggregation_daily_batch.sh"
        )

        script = script_path.read_text(encoding="utf-8")

        self.assertIn('source "${SCRIPT_DIR}/batch_advisory_lock.sh"', script)
        self.assertIn(
            'run_sql_with_advisory_lock "lk_statistics_aggregation_daily_batch"',
            script,
        )
        self.assertIn("statistics_aggregation_daily_batch.sql", script)


class SitePageRouteDailyMigrationTest(unittest.TestCase):
    def test_site_page_analytics_migration_creates_raw_and_daily_tables(self):
        from app.utils.auto_migrate import _parse_statements

        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist"
            / "init"
            / "98-create-site-page-analytics-tables.sql"
        )

        statements = _parse_statements(migration_path.read_text(encoding="utf-8"))

        self.assertEqual(len(statements), 2)
        self.assertIn("tb_site_page_dwell_event", statements[0])
        self.assertIn("tb_site_page_route_daily", statements[1])

    def test_site_page_dwell_raw_table_does_not_store_raw_path(self):
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist"
            / "init"
            / "98-create-site-page-analytics-tables.sql"
        )

        sql = migration_path.read_text(encoding="utf-8").lower()
        raw_table_section = sql.split("create table if not exists tb_site_page_route_daily")[0]

        self.assertIn("active_ms", raw_table_section)
        self.assertIn("path_template", raw_table_section)
        self.assertNotIn(" path ", raw_table_section)
        self.assertNotIn("query_hash", raw_table_section)

    def test_site_page_route_daily_primary_key_includes_route_name(self):
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist"
            / "init"
            / "98-create-site-page-analytics-tables.sql"
        )

        sql = migration_path.read_text(encoding="utf-8").lower()

        self.assertIn(
            "primary key (stat_date, route_group, route_name, path_template)",
            sql,
        )

    def test_site_page_route_daily_model_primary_key_matches_migration(self):
        from app.models.statistics import (
            SitePageDwellEvent,
            SitePageRouteDaily,
            SitePageViewEvent,
        )

        self.assertEqual(
            [column.name for column in SitePageRouteDaily.__table__.primary_key.columns],
            ["stat_date", "route_group", "route_name", "path_template"],
        )
        self.assertEqual(
            [column.name for column in SitePageViewEvent.__table__.primary_key.columns],
            ["id"],
        )
        self.assertEqual(
            [column.name for column in SitePageDwellEvent.__table__.primary_key.columns],
            ["id"],
        )

    def test_site_page_route_daily_pk_forward_migration_is_conditional(self):
        from app.utils.auto_migrate import _parse_statements

        migration_path = (
            Path(__file__).resolve().parents[1]
            / "dist"
            / "init"
            / "99-alter-site-page-route-daily-primary-key.sql"
        )

        sql = migration_path.read_text(encoding="utf-8").lower()
        statements = _parse_statements(sql)

        self.assertGreaterEqual(len(statements), 5)
        self.assertIn("information_schema.key_column_usage", sql)
        self.assertIn("information_schema.tables", sql)
        self.assertIn("coalesce(@site_page_route_daily_pk, '')", sql)
        self.assertIn("drop primary key", sql)
        self.assertIn(
            "add primary key (stat_date, route_group, route_name, path_template)",
            sql,
        )
        self.assertIn("prepare stmt_alter_site_page_route_daily_pk", sql)
