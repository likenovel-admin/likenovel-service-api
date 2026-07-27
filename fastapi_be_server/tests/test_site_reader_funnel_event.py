from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

from fastapi import status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

from app.exceptions import CustomResponseException
from app.const import settings
from app.models.statistics import SiteReaderFunnelConfig, SiteReaderFunnelEvent
from app.routers.common import statistics_command
from app.schemas.statistics import PostSiteReaderFunnelEventReqBody
from app.services.common import statistics_service
from app.utils.auth import chk_optional_cur_user_strict
from app.utils.auto_migrate import _parse_statements


ROOT = Path(__file__).resolve().parents[1]


class FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row


class FakeDb:
    def __init__(
        self,
        *,
        user_row=None,
        product_row=None,
        episode_rows=None,
        next_episode_row=None,
        start_row=None,
        cutover_row=None,
    ):
        self.user_row = user_row
        self.product_row = product_row or {"product_id": 100}
        self.episode_rows = episode_rows or {}
        self.next_episode_row = next_episode_row
        self.start_row = start_row
        self.cutover_row = cutover_row
        self.calls = []
        self.commits = 0

    async def execute(self, query, params=None):
        sql = str(query)
        self.calls.append((sql, params))
        if "FROM tb_user" in sql:
            return FakeResult(self.user_row)
        if "FROM tb_product p" in sql:
            return FakeResult(self.product_row)
        if "FROM tb_site_reader_funnel_event" in sql:
            return FakeResult(self.start_row)
        if "FROM tb_site_reader_funnel_config" in sql:
            return FakeResult(self.cutover_row)
        if "JOIN tb_product_episode n" in sql:
            return FakeResult(self.next_episode_row)
        if "FROM tb_product_episode e" in sql:
            return FakeResult(self.episode_rows.get(params["episode_id"]))
        return FakeResult(None)

    async def commit(self):
        self.commits += 1


def _event_kwargs(**overrides):
    values = {
        "kc_user_id": None,
        "event_id": "2f7a05c2-e3fa-4264-ad49-e7613b4795b3",
        "occurred_at": datetime.now(timezone.utc),
        "event_type": "episode_start",
        "visitor_id": "visitor-1",
        "browser_session_id": "browser-session-1",
        "viewer_session_id": "viewer-session-1",
        "product_id": 100,
        "episode_id": 250,
        "next_episode_id": None,
        "destination_group": "unknown",
        "active_ms": 0,
        "progress_ratio": 0.0,
    }
    values.update(overrides)
    return values


class SiteReaderFunnelSchemaTest(unittest.TestCase):
    def test_schema_accepts_frontend_episode_start_defaults(self):
        event = PostSiteReaderFunnelEventReqBody.model_validate(
            {
                "eventId": "2f7a05c2-e3fa-4264-ad49-e7613b4795b3",
                "occurredAt": "2026-07-27T12:00:00Z",
                "eventType": "episode_start",
                "visitorId": "visitor-1",
                "browserSessionId": "browser-session-1",
                "viewerSessionId": "viewer-session-1",
                "productId": 100,
                "episodeId": 250,
                "activeMs": 0,
                "progressRatio": 0,
            }
        )

        self.assertEqual(event.destination_group, "unknown")

    def test_schema_requires_episode_identity_for_episode_events(self):
        with self.assertRaises(ValidationError):
            PostSiteReaderFunnelEventReqBody.model_validate(
                {
                    "eventId": "2f7a05c2-e3fa-4264-ad49-e7613b4795b3",
                    "occurredAt": "2026-07-27T12:00:00Z",
                    "eventType": "episode_exit",
                    "visitorId": "visitor-1",
                    "browserSessionId": "browser-session-1",
                    "productId": 100,
                }
            )

    def test_schema_allows_product_detail_exit_without_viewer_session(self):
        event = PostSiteReaderFunnelEventReqBody.model_validate(
            {
                "eventId": "2f7a05c2-e3fa-4264-ad49-e7613b4795b3",
                "occurredAt": "2026-07-27T12:00:00Z",
                "eventType": "product_detail_exit",
                "visitorId": "visitor-1",
                "browserSessionId": "browser-session-1",
                "productId": 100,
                "destinationGroup": "home",
                "activeMs": 1500,
            }
        )

        self.assertIsNone(event.viewer_session_id)
        self.assertIsNone(event.episode_id)
        self.assertEqual(event.progress_ratio, 0)

    def test_schema_rejects_client_owned_server_fields_and_unknown_entry_source(self):
        base = {
            "eventId": "2f7a05c2-e3fa-4264-ad49-e7613b4795b3",
            "occurredAt": "2026-07-27T12:00:00Z",
            "eventType": "product_detail_exit",
            "visitorId": "visitor-1",
            "browserSessionId": "browser-session-1",
            "productId": 100,
            "destinationGroup": "unknown",
            "activeMs": 0,
            "progressRatio": 0,
        }

        for field, value in (
            ("userId", 99),
            ("audienceTypeAtStart", "member"),
            ("trackingVersion", 999),
            ("source", "spoofed-client"),
            ("entrySource", "ai"),
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                PostSiteReaderFunnelEventReqBody.model_validate(
                    {**base, field: value}
                )

    def test_schema_rejects_unlisted_event_and_destination_types(self):
        base = {
            "eventId": "2f7a05c2-e3fa-4264-ad49-e7613b4795b3",
            "occurredAt": "2026-07-27T12:00:00Z",
            "eventType": "product_detail_exit",
            "visitorId": "visitor-1",
            "browserSessionId": "browser-session-1",
            "productId": 100,
            "destinationGroup": "unknown",
            "activeMs": 0,
            "progressRatio": 0,
        }

        with self.assertRaises(ValidationError):
            PostSiteReaderFunnelEventReqBody.model_validate(
                {**base, "eventType": "episode_view"}
            )
        with self.assertRaises(ValidationError):
            PostSiteReaderFunnelEventReqBody.model_validate(
                {**base, "destinationGroup": "raw_url"}
            )


class SiteReaderFunnelServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_client_timestamp_outside_ingest_window_is_rejected(self):
        for occurred_at in (
            datetime.now(timezone.utc) - timedelta(days=2),
            datetime.now(timezone.utc) + timedelta(minutes=10),
        ):
            with self.subTest(occurred_at=occurred_at):
                db = FakeDb()
                with self.assertRaises(CustomResponseException) as exc:
                    await statistics_service.insert_site_reader_funnel_event(
                        db=db,
                        **_event_kwargs(occurred_at=occurred_at),
                    )

                self.assertEqual(
                    exc.exception.status_code,
                    status.HTTP_400_BAD_REQUEST,
                )
                self.assertEqual(db.calls, [])

    async def test_guest_free_episode_25_is_allowed(self):
        db = FakeDb(
            episode_rows={
                250: {
                    "episode_id": 250,
                    "episode_no": 25,
                    "price_type": "free",
                }
            }
        )

        await statistics_service.insert_site_reader_funnel_event(
            db=db,
            **_event_kwargs(),
        )

        insert_sql, params = db.calls[-1]
        self.assertIn("INSERT INTO tb_site_reader_funnel_event", insert_sql)
        self.assertIn("'service-web'", insert_sql)
        self.assertNotIn("source", params)
        self.assertNotIn("tracking_version", params)
        self.assertEqual(params["audience_type_at_start"], "guest")
        self.assertIsNone(params["user_id"])
        self.assertEqual(db.commits, 1)
        combined_sql = "\n".join(sql for sql, _ in db.calls)
        self.assertIn("p.open_yn = 'Y'", combined_sql)
        self.assertIn("e.product_id = :product_id", combined_sql)
        self.assertIn("e.open_yn = 'Y'", combined_sql)
        self.assertIn("e.use_yn = 'Y'", combined_sql)
        self.assertIn("INSERT INTO tb_site_reader_funnel_config", combined_sql)
        config_sql, config_params = next(
            (sql, call_params)
            for sql, call_params in db.calls
            if "INSERT INTO tb_site_reader_funnel_config" in sql
        )
        self.assertIn(
            "cutover_date = LEAST(cutover_date, VALUES(cutover_date))",
            config_sql,
        )
        self.assertEqual(
            config_params["cutover_date"],
            datetime.now(ZoneInfo(settings.KOREA_TIMEZONE)).date()
            + timedelta(days=1),
        )

    async def test_guest_episode_26_and_paid_episode_are_rejected(self):
        for episode_id, episode_no, price_type in (
            (260, 26, "free"),
            (10, 10, "paid"),
        ):
            with self.subTest(episode_no=episode_no, price_type=price_type):
                db = FakeDb(
                    episode_rows={
                        episode_id: {
                            "episode_id": episode_id,
                            "episode_no": episode_no,
                            "price_type": price_type,
                        }
                    }
                )

                with self.assertRaises(CustomResponseException) as exc:
                    await statistics_service.insert_site_reader_funnel_event(
                        db=db,
                        **_event_kwargs(episode_id=episode_id),
                    )

                self.assertEqual(exc.exception.status_code, status.HTTP_401_UNAUTHORIZED)
                self.assertFalse(
                    any(
                        "INSERT INTO tb_site_reader_funnel_event" in sql
                        for sql, _ in db.calls
                    )
                )

    async def test_existing_cutover_marker_avoids_hot_row_update(self):
        db = FakeDb(
            episode_rows={
                250: {
                    "episode_id": 250,
                    "episode_no": 25,
                    "price_type": "free",
                }
            },
            cutover_row={"cutover_date": "2026-07-28"},
        )

        await statistics_service.insert_site_reader_funnel_event(
            db=db,
            **_event_kwargs(),
        )

        combined_sql = "\n".join(sql for sql, _ in db.calls)
        self.assertIn("FROM tb_site_reader_funnel_config", combined_sql)
        self.assertNotIn("INSERT INTO tb_site_reader_funnel_config", combined_sql)
        self.assertIn("INSERT INTO tb_site_reader_funnel_event", combined_sql)
        self.assertEqual(db.commits, 1)

    async def test_next_episode_click_rejects_forged_non_next_episode(self):
        db = FakeDb(
            episode_rows={
                250: {
                    "episode_id": 250,
                    "episode_no": 25,
                    "price_type": "free",
                }
            },
            next_episode_row={
                "episode_id": 270,
                "episode_no": 27,
                "price_type": "free",
            },
        )

        with self.assertRaises(CustomResponseException) as exc:
            await statistics_service.insert_site_reader_funnel_event(
                db=db,
                **_event_kwargs(
                    event_type="next_episode_click",
                    next_episode_id=260,
                ),
            )

        self.assertEqual(exc.exception.status_code, status.HTTP_400_BAD_REQUEST)
        combined_sql = "\n".join(sql for sql, _ in db.calls)
        self.assertIn("n.product_id = e.product_id", combined_sql)
        self.assertIn("n.open_yn = 'Y'", combined_sql)
        self.assertIn("n.use_yn = 'Y'", combined_sql)

    async def test_guest_episode_25_to_26_click_is_recorded_before_login_gate(self):
        db = FakeDb(
            episode_rows={
                250: {
                    "episode_id": 250,
                    "episode_no": 25,
                    "price_type": "free",
                }
            },
            next_episode_row={
                "episode_id": 260,
                "episode_no": 26,
                "price_type": "free",
            },
        )

        await statistics_service.insert_site_reader_funnel_event(
            db=db,
            **_event_kwargs(
                event_type="next_episode_click",
                next_episode_id=260,
            ),
        )

        insert_sql, params = db.calls[-1]
        self.assertIn("INSERT INTO tb_site_reader_funnel_event", insert_sql)
        self.assertEqual(params["next_episode_id"], 260)
        self.assertEqual(params["audience_type_at_start"], "guest")
        self.assertEqual(db.commits, 1)

    async def test_episode_exit_inherits_guest_start_audience_after_login(self):
        db = FakeDb(
            user_row={"user_id": 77},
            episode_rows={
                250: {
                    "episode_id": 250,
                    "episode_no": 25,
                    "price_type": "free",
                }
            },
            start_row={"audience_type_at_start": "guest"},
        )

        await statistics_service.insert_site_reader_funnel_event(
            db=db,
            **_event_kwargs(
                kc_user_id="kc-member-77",
                event_type="episode_exit",
                active_ms=20000,
                progress_ratio=0.4,
            ),
        )

        insert_sql, params = db.calls[-1]
        self.assertEqual(params["user_id"], 77)
        self.assertEqual(params["audience_type_at_start"], "guest")
        self.assertIn(
            "active_ms = GREATEST(active_ms, VALUES(active_ms))",
            insert_sql,
        )
        self.assertIn(
            "progress_ratio = GREATEST(progress_ratio, VALUES(progress_ratio))",
            insert_sql,
        )
        self.assertIn(
            "occurred_at = GREATEST(occurred_at, VALUES(occurred_at))",
            insert_sql,
        )
        self.assertIn("user_id = COALESCE(user_id, VALUES(user_id))", insert_sql)


class SiteReaderFunnelRouteAndMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_strict_optional_auth_rejects_invalid_bearer(self):
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="invalid-token",
        )

        with self.assertRaises(CustomResponseException) as exc:
            await chk_optional_cur_user_strict(credentials=credentials)

        self.assertEqual(exc.exception.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_route_uses_strict_optional_auth(self):
        route = next(
            route
            for route in statistics_command.router.routes
            if getattr(route, "path", "").endswith("/reader-funnel-event")
        )

        dependency_calls = [
            dependency.call for dependency in route.dependant.dependencies
        ]

        self.assertIn(chk_optional_cur_user_strict, dependency_calls)

    def test_migration_declares_minimal_raw_table_contract(self):
        migration = (
            ROOT / "dist/init/105-create-site-reader-funnel-event.sql"
        ).read_text(encoding="utf-8")
        lowered = migration.lower()
        statements = _parse_statements(migration)

        self.assertEqual(len(statements), 2)
        self.assertIn("create table if not exists tb_site_reader_funnel_event", lowered)
        self.assertIn("create table if not exists tb_site_reader_funnel_config", lowered)
        self.assertIn("unique key uq_site_reader_funnel_event_event_id", lowered)
        self.assertIn(
            "unique key uq_site_reader_funnel_viewer_event_type "
            "(viewer_session_id, event_type)",
            lowered,
        )
        self.assertIn(
            "key idx_site_reader_funnel_audience_event_occurred",
            lowered,
        )
        self.assertIn(
            "key idx_site_reader_funnel_audience_event_created",
            lowered,
        )
        for forbidden in (
            "raw_json",
            "payload",
            "ip_address",
            "user_agent",
            "referrer",
            "foreign key",
        ):
            self.assertNotIn(forbidden, lowered)

        self.assertEqual(
            set(SiteReaderFunnelEvent.__table__.columns.keys()),
            {
                "id",
                "event_id",
                "occurred_at",
                "user_id",
                "audience_type_at_start",
                "visitor_id",
                "browser_session_id",
                "viewer_session_id",
                "event_type",
                "product_id",
                "episode_id",
                "next_episode_id",
                "destination_group",
                "active_ms",
                "progress_ratio",
                "tracking_version",
                "source",
                "created_date",
                "updated_date",
            },
        )
        self.assertEqual(
            set(SiteReaderFunnelConfig.__table__.columns.keys()),
            {"config_key", "cutover_date", "created_date"},
        )
