import unittest
from datetime import datetime, timezone

from app.routers.common import statistics_command
from app.schemas.statistics import PostSitePageDwellReqBody, PostSitePageViewReqBody
from app.services.common import statistics_service
from app.utils.auth import analysis_logger


class FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row

    def first(self):
        return self._row

    def all(self):
        if self._row is None:
            return []
        if isinstance(self._row, list):
            return self._row
        return [self._row]


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


class FakeDbSequence:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    async def execute(self, query, params=None):
        self.calls.append((str(query), params))
        return FakeResult(self.rows.pop(0))


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

    async def test_page_view_preserves_marketing_attribution(self):
        db = FakeDb()

        await statistics_service.insert_site_page_view_event(
            db=db,
            kc_user_id=None,
            event_id="1ab1ef4f-a433-4777-a4a9-0d1ab2983b1a",
            occurred_at=datetime(2026, 5, 27, 18, 0, 0, tzinfo=timezone.utc),
            visitor_id="pv_marketing",
            session_id="pvs_marketing",
            route_group="product_detail",
            route_name="product_detail",
            path_template="/product/[id]",
            path="/product/1109",
            query_hash=None,
            referrer_path=None,
            source="service-web",
            taxonomy_version=1,
            utm_source="Instagram",
            utm_medium="social",
            utm_campaign="p1109_card",
            utm_content="card01",
            external_referrer_host="l.instagram.com",
            external_referrer_group="instagram",
        )

        insert_call = db.calls[-1]
        self.assertIn("utm_source", insert_call[0])
        self.assertEqual(insert_call[1]["utm_source"], "instagram")
        self.assertEqual(insert_call[1]["utm_medium"], "social")
        self.assertEqual(insert_call[1]["utm_campaign"], "p1109_card")
        self.assertEqual(insert_call[1]["utm_content"], "card01")
        self.assertEqual(insert_call[1]["external_referrer_host"], "instagram.com")
        self.assertEqual(insert_call[1]["external_referrer_group"], "instagram")

    async def test_page_view_normalizes_x_marketing_attribution(self):
        db = FakeDb()

        await statistics_service.insert_site_page_view_event(
            db=db,
            kc_user_id=None,
            event_id="eb26e25b-b08d-4a56-bcd8-c7447b1b2b3f",
            occurred_at=datetime(2026, 5, 27, 22, 10, 0, tzinfo=timezone.utc),
            visitor_id="pv_x",
            session_id="pvs_x",
            route_group="product_detail",
            route_name="product_detail",
            path_template="/product/[id]",
            path="/product/1126",
            query_hash=None,
            referrer_path=None,
            source="service-web",
            taxonomy_version=1,
            utm_source="Twitter",
            utm_medium="social",
            utm_campaign="p1126_card",
            utm_content="card01",
            external_referrer_host="t.co",
            external_referrer_group="twitter",
        )

        insert_call = db.calls[-1]
        self.assertEqual(insert_call[1]["utm_source"], "x")
        self.assertEqual(insert_call[1]["external_referrer_host"], "t.co")
        self.assertEqual(insert_call[1]["external_referrer_group"], "x")

    async def test_page_view_preserves_product_entry_attribution(self):
        db = FakeDb()

        await statistics_service.insert_site_page_view_event(
            db=db,
            kc_user_id=None,
            event_id="0554070f-0866-46e6-86b9-44c6d2cf443a",
            occurred_at=datetime(2026, 5, 27, 18, 0, 0, tzinfo=timezone.utc),
            visitor_id="pv_product",
            session_id="pvs_product",
            route_group="product_detail",
            route_name="product_detail",
            path_template="/product/[id]",
            path="/product/1117",
            query_hash=None,
            referrer_path=None,
            source="service-web",
            taxonomy_version=1,
            product_id=1117,
            entry_source="Instagram",
            entry_source_group="social",
        )

        insert_call = db.calls[-1]
        self.assertIn("product_id", insert_call[0])
        self.assertIn("entry_source", insert_call[0])
        self.assertIn("entry_source_group", insert_call[0])
        self.assertEqual(insert_call[1]["product_id"], 1117)
        self.assertEqual(insert_call[1]["entry_source"], "instagram")
        self.assertEqual(insert_call[1]["entry_source_group"], "social")

    def test_page_view_schema_accepts_product_entry_attribution(self):
        payload = PostSitePageViewReqBody(
            eventId="0554070f-0866-46e6-86b9-44c6d2cf443a",
            occurredAt=datetime(2026, 5, 27, 18, 0, 0, tzinfo=timezone.utc),
            visitorId="pv_product",
            sessionId="pvs_product",
            routeGroup="product_detail",
            routeName="product_detail",
            pathTemplate="/product/[id]",
            path="/product/1117",
            productId=1117,
            entrySource="Instagram",
            entrySourceGroup="social",
        )

        self.assertEqual(payload.product_id, 1117)
        self.assertEqual(payload.entry_source, "instagram")
        self.assertEqual(payload.entry_source_group, "social")

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

    def test_marketing_attribution_schema_truncates_instead_of_rejecting(self):
        req = PostSitePageViewReqBody(
            eventId="9e6c64d6-9222-4546-a7ef-8699f89e2d26",
            occurredAt="2026-05-21T12:34:56.789+09:00",
            visitorId="pv_visitor",
            sessionId="pvs_session",
            routeGroup="product_detail",
            routeName="product_detail",
            pathTemplate="/product/[id]",
            path="/product/1109",
            queryHash=None,
            referrerPath="/",
            utmSource="X" * 300,
            utmMedium="social",
            utmCampaign="P1109 Card",
            utmContent="Card 01",
            externalReferrerHost="L.Instagram.Com",
            externalReferrerGroup="Instagram",
            source="service-web",
            taxonomyVersion=1,
        )

        self.assertEqual(len(req.utm_source), 120)
        self.assertEqual(req.utm_medium, "social")
        self.assertEqual(req.utm_campaign, "p1109_card")
        self.assertEqual(req.utm_content, "card_01")
        self.assertEqual(req.external_referrer_host, "l.instagram.com")
        self.assertEqual(req.external_referrer_group, "instagram")

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

    async def test_site_page_referrer_statistics_groups_marketing_fields(self):
        db = FakeDbSequence(
            [
                {
                    "page_view_count": 3,
                    "visitor_count": 2,
                    "session_count": 2,
                },
                {"total_count": 1},
                [
                    {
                        "referrer_group": "instagram",
                        "external_referrer_host": "instagram.com",
                        "utm_source": "instagram",
                        "utm_medium": "social",
                        "utm_campaign": "p1109_card",
                        "utm_content": "card01",
                        "route_group": "product_detail",
                        "route_name": "product_detail",
                        "path_template": "/product/[id]",
                        "landing_path": "/product/1109",
                        "page_view_count": 3,
                        "visitor_count": 2,
                        "session_count": 2,
                    }
                ],
            ]
        )

        result = await statistics_service.site_page_referrer_statistics(
            start_date="2026-05-27",
            end_date="2026-05-27",
            referrer_group="instagram",
            route_group="product_detail",
            page=1,
            count_per_page=20,
            db=db,
        )

        self.assertEqual(result["summary"]["page_view_count"], 3)
        self.assertEqual(result["total_count"], 1)
        self.assertEqual(result["results"][0]["utm_campaign"], "p1109_card")
        self.assertEqual(result["results"][0]["utm_content"], "card01")
        detail_sql, detail_params = db.calls[-1]
        self.assertIn("COALESCE(NULLIF(utm_source, ''), NULLIF(external_referrer_group, ''), 'unknown')", detail_sql)
        self.assertEqual(detail_params["referrer_group"], "instagram")
        self.assertEqual(detail_params["route_group"], "product_detail")

    async def test_site_page_referrer_statistics_all_filter_does_not_become_other(self):
        db = FakeDbSequence(
            [
                {
                    "page_view_count": 5,
                    "visitor_count": 3,
                    "session_count": 4,
                },
                {"total_count": 2},
                [],
            ]
        )

        await statistics_service.site_page_referrer_statistics(
            start_date="2026-05-27",
            end_date="2026-05-27",
            referrer_group="all",
            route_group="all",
            page=1,
            count_per_page=20,
            db=db,
        )

        for _sql, params in db.calls:
            self.assertNotIn("referrer_group", params)
            self.assertNotIn("route_group", params)

    async def test_guest_page_dwell_inserts_null_user_id_and_capped_active_ms(self):
        db = FakeDb()

        await statistics_service.insert_site_page_dwell_event(
            db=db,
            kc_user_id=None,
            event_id="c4b7b9c2-8cc4-4b2e-9bf5-4f2e2f037001",
            occurred_at=datetime(2026, 5, 23, 12, 34, 56, tzinfo=timezone.utc),
            visitor_id="pv_guest",
            session_id="pvs_guest",
            route_group="viewer",
            route_name="viewer_episode",
            path_template="/viewer/[id]",
            active_ms=31 * 60 * 1000,
            source="service-web",
            taxonomy_version=1,
        )

        insert_call = db.calls[-1]
        self.assertIn("INSERT INTO tb_site_page_dwell_event", insert_call[0])
        self.assertIsNone(insert_call[1]["user_id"])
        self.assertEqual(insert_call[1]["active_ms"], 30 * 60 * 1000)
        self.assertEqual(db.commits, 1)

    def test_page_dwell_schema_rejects_subsecond_active_ms(self):
        with self.assertRaises(ValueError):
            PostSitePageDwellReqBody(
                eventId="c4b7b9c2-8cc4-4b2e-9bf5-4f2e2f037001",
                occurredAt="2026-05-23T12:34:56.789+09:00",
                visitorId="pv_visitor",
                sessionId="pvs_session",
                routeGroup="viewer",
                routeName="viewer_episode",
                pathTemplate="/viewer/[id]",
                activeMs=999,
                source="service-web",
                taxonomyVersion=1,
            )

    def test_page_dwell_router_does_not_attach_raw_analysis_logger(self):
        page_dwell_route = next(
            route
            for route in statistics_command.router.routes
            if getattr(route, "path", "").endswith("/page-dwell")
        )

        dependency_calls = [
            dependency.call for dependency in page_dwell_route.dependant.dependencies
        ]

        self.assertNotIn(analysis_logger, dependency_calls)

    async def test_site_page_route_statistics_reads_daily_mart_only(self):
        db = FakeDb()

        async def execute(query, params=None):
            sql = str(query)
            db.calls.append((sql, params))
            if "COUNT(*) AS total_count" in sql:
                return FakeResult({"total_count": 1})
            if "route_group," in sql and "GROUP BY route_group" in sql:
                return FakeResult(
                    [
                        {
                            "route_group": "viewer",
                            "route_name": "viewer_episode",
                            "path_template": "/viewer/[id]",
                            "page_view_count": 10,
                            "visitor_count": 7,
                            "session_count": 8,
                            "dwell_event_count": 6,
                            "active_dwell_total_ms": 120000,
                            "active_dwell_avg_ms": 20000,
                            "short_dwell_count": 1,
                        }
                    ]
                )
            return FakeResult(
                {
                    "page_view_count": 10,
                    "visitor_count": 7,
                    "session_count": 8,
                    "dwell_event_count": 6,
                    "active_dwell_total_ms": 120000,
                    "active_dwell_avg_ms": 20000,
                    "short_dwell_count": 1,
                }
            )

        db.execute = execute

        result = await statistics_service.site_page_route_statistics(
            start_date="2026-05-20",
            end_date="2026-05-23",
            route_group="viewer",
            page=1,
            count_per_page=20,
            db=db,
        )

        combined_sql = "\n".join(call[0] for call in db.calls)
        self.assertIn("FROM tb_site_page_route_daily", combined_sql)
        self.assertNotIn("tb_site_page_view_event", combined_sql)
        self.assertNotIn("tb_site_page_dwell_event", combined_sql)
        self.assertEqual(result["total_count"], 1)
        self.assertEqual(result["results"][0]["route_group"], "viewer")
        self.assertEqual(db.calls[0][1]["route_group"], "viewer")
