import unittest
from datetime import datetime, timezone

from app.routers.common import statistics_command
from app.schemas.statistics import PostSitePageViewReqBody
from app.services.common import statistics_service
from app.utils.auth import analysis_logger


class FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row


class FakeDb:
    def __init__(self, user_row=None):
        self.user_row = user_row
        self.calls = []
        self.commits = 0

    async def execute(self, query, params=None):
        sql = str(query)
        self.calls.append((sql, params))
        if "FROM tb_user" in sql:
            return FakeResult(self.user_row)
        return FakeResult(None)

    async def commit(self):
        self.commits += 1


class SitePageViewStatisticsServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_guest_page_view_inserts_null_user_id(self):
        db = FakeDb()

        await statistics_service.insert_site_page_view_event(
            db=db,
            kc_user_id=None,
            event_id="9e6c64d6-9222-4546-a7ef-8699f89e2d26",
            occurred_at=datetime(2026, 5, 21, 12, 34, 56, tzinfo=timezone.utc),
            visitor_id="pv_guest",
            session_id="pvs_guest",
            route_group="home",
            route_name="home",
            path_template="/",
            path="/",
            query_hash=None,
            referrer_path=None,
            source="service-web",
            taxonomy_version=1,
        )

        insert_call = db.calls[-1]
        self.assertIn("INSERT INTO tb_site_page_view_event", insert_call[0])
        self.assertIsNone(insert_call[1]["user_id"])
        self.assertEqual(db.commits, 1)

    async def test_logged_in_page_view_resolves_user_id(self):
        db = FakeDb(user_row={"user_id": 123})

        await statistics_service.insert_site_page_view_event(
            db=db,
            kc_user_id="kc-123",
            event_id="2f7a05c2-e3fa-4264-ad49-e7613b4795b3",
            occurred_at=datetime(2026, 5, 21, 12, 34, 56, tzinfo=timezone.utc),
            visitor_id="pv_user",
            session_id="pvs_user",
            route_group="viewer",
            route_name="viewer_episode",
            path_template="/viewer/[id]",
            path="/viewer/22051",
            query_hash=None,
            referrer_path="/product/1129",
            source="service-web",
            taxonomy_version=1,
        )

        insert_call = db.calls[-1]
        self.assertEqual(insert_call[1]["user_id"], 123)
        self.assertEqual(db.commits, 1)

    async def test_unknown_kc_user_falls_back_to_guest(self):
        db = FakeDb(user_row=None)

        await statistics_service.insert_site_page_view_event(
            db=db,
            kc_user_id="missing-kc-user",
            event_id="2feb4efb-a0a8-4a21-bba9-a26c8a7d14d4",
            occurred_at=datetime(2026, 5, 21, 12, 34, 56, tzinfo=timezone.utc),
            visitor_id="pv_unknown",
            session_id="pvs_unknown",
            route_group="unknown",
            route_name="unknown",
            path_template="/new-feature",
            path="/new-feature",
            query_hash=None,
            referrer_path="/",
            source="service-web",
            taxonomy_version=1,
        )

        insert_call = db.calls[-1]
        self.assertIsNone(insert_call[1]["user_id"])
        self.assertEqual(db.commits, 1)

    async def test_source_is_normalized_to_service_web(self):
        db = FakeDb()

        await statistics_service.insert_site_page_view_event(
            db=db,
            kc_user_id=None,
            event_id="5f6f9810-42f3-400b-b68a-6f4c28a5bb58",
            occurred_at=datetime(2026, 5, 21, 12, 34, 56, tzinfo=timezone.utc),
            visitor_id="pv_guest",
            session_id="pvs_guest",
            route_group="home",
            route_name="home",
            path_template="/",
            path="/",
            query_hash=None,
            referrer_path=None,
            source="bad-source",
            taxonomy_version=1,
        )

        insert_call = db.calls[-1]
        self.assertEqual(insert_call[1]["source"], "service-web")

    async def test_invalid_query_hash_is_dropped_by_service(self):
        db = FakeDb()

        await statistics_service.insert_site_page_view_event(
            db=db,
            kc_user_id=None,
            event_id="aa1be3ab-f5cd-4ccb-b47b-35432857a489",
            occurred_at=datetime(2026, 5, 21, 12, 34, 56, tzinfo=timezone.utc),
            visitor_id="pv_guest",
            session_id="pvs_guest",
            route_group="home",
            route_name="home",
            path_template="/",
            path="/",
            query_hash="token=secret",
            referrer_path=None,
            source="service-web",
            taxonomy_version=1,
        )

        insert_call = db.calls[-1]
        self.assertIsNone(insert_call[1]["query_hash"])

    def test_sanitize_path_drops_query_and_hash(self):
        self.assertEqual(
            statistics_service._sanitize_page_view_path(
                "/product/1?token=secret#section"
            ),
            "/product/1",
        )

    def test_route_group_validation_allows_unknown_but_rejects_free_text(self):
        self.assertEqual(
            statistics_service._normalize_site_page_view_route_group("home"), "home"
        )
        self.assertEqual(
            statistics_service._normalize_site_page_view_route_group("unknown"),
            "unknown",
        )
        self.assertEqual(
            statistics_service._normalize_site_page_view_route_group("bad group"),
            "unknown",
        )

    def test_occurred_at_is_normalized_to_kst_naive_for_daily_batch(self):
        normalized = statistics_service._normalize_page_view_occurred_at(
            datetime(2026, 5, 21, 15, 30, 0, tzinfo=timezone.utc)
        )

        self.assertEqual(normalized, datetime(2026, 5, 22, 0, 30, 0))
        self.assertIsNone(normalized.tzinfo)

    def test_invalid_query_hash_is_dropped_by_schema(self):
        req = PostSitePageViewReqBody(
            eventId="9e6c64d6-9222-4546-a7ef-8699f89e2d26",
            occurredAt="2026-05-21T12:34:56.789+09:00",
            visitorId="pv_visitor",
            sessionId="pvs_session",
            routeGroup="home",
            routeName="home",
            pathTemplate="/",
            path="/",
            queryHash="token=secret",
            referrerPath="/",
            source="service-web",
            taxonomyVersion=1,
        )

        self.assertIsNone(req.query_hash)

    def test_valid_query_hash_is_preserved_by_schema(self):
        query_hash = "a" * 64

        req = PostSitePageViewReqBody(
            eventId="9e6c64d6-9222-4546-a7ef-8699f89e2d26",
            occurredAt="2026-05-21T12:34:56.789+09:00",
            visitorId="pv_visitor",
            sessionId="pvs_session",
            routeGroup="home",
            routeName="home",
            pathTemplate="/",
            path="/",
            queryHash=query_hash,
            referrerPath="/",
            source="service-web",
            taxonomyVersion=1,
        )

        self.assertEqual(req.query_hash, query_hash)

    def test_page_view_router_does_not_attach_raw_analysis_logger(self):
        page_view_route = next(
            route
            for route in statistics_command.router.routes
            if getattr(route, "path", "").endswith("/page-view")
        )

        dependency_calls = [
            dependency.call for dependency in page_view_route.dependant.dependencies
        ]

        self.assertNotIn(analysis_logger, dependency_calls)
