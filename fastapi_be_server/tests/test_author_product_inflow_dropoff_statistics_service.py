import unittest

from app.routers.partner import partner_query
from app.services.partner import partner_statistics_service


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeDb:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    async def execute(self, query, params=None):
        self.calls.append((str(query), params or {}))
        return FakeResult(self.rows.pop(0))


class AuthorProductInflowDropoffStatisticsServiceTest(
    unittest.IsolatedAsyncioTestCase
):
    async def test_author_product_inflow_dropoff_merges_entry_and_funnel_groups(self):
        db = FakeDb(
            [
                [
                    {
                        "guest_cutover_date": "2026-06-01",
                        "max_metric_version": 2,
                    }
                ],
                [
                    {
                        "product_id": 1117,
                        "entry_source_group": "social",
                        "detail_view_count": 20,
                        "detail_session_count": 10,
                        "detail_visitor_count": 9,
                        "login_user_count": 4,
                    },
                    {
                        "product_id": 1117,
                        "entry_source_group": "recommend_slot",
                        "detail_view_count": 15,
                        "detail_session_count": 5,
                        "detail_visitor_count": 5,
                        "login_user_count": 3,
                    },
                ],
                [
                    {
                        "product_id": 1117,
                        "entry_source_group": "social",
                        "reader_session_count": 3,
                        "detail_exit_session_count": 7,
                    },
                    {
                        "product_id": 1117,
                        "entry_source_group": "recommend_slot",
                        "reader_session_count": 4,
                        "detail_exit_session_count": 1,
                    },
                ],
                [
                    {
                        "product_id": 1117,
                        "episode_id": 4249010,
                        "episode_no": 1,
                        "episode_title": "1화",
                        "read_start_count": 8,
                        "episode_dropoff_count": 2,
                        "episode_dropoff_rate": 0.25,
                    }
                ],
            ]
        )

        result = await partner_statistics_service.product_inflow_dropoff_statistics(
            product_id=1117,
            search_start_date="2026-05-27",
            search_end_date="2026-05-27",
            db=db,
            user_data={"user_id": 999},
        )

        self.assertEqual(result["product_id"], 1117)
        self.assertEqual(result["metric_version"], 1)
        self.assertEqual(result["measurement_basis"], "legacy_mixed")
        self.assertEqual(result["requested_start_date"], "2026-05-27")
        self.assertEqual(result["effective_start_date"], "2026-05-27")
        self.assertEqual(len(result["source_groups"]), 2)
        self.assertEqual(result["source_groups"][0]["entry_source_group"], "social")
        self.assertEqual(result["source_groups"][0]["read_conversion_rate"], 0.3)
        self.assertEqual(result["source_groups"][0]["detail_exit_rate"], 0.7)
        self.assertEqual(result["episode_dropoffs"][0]["episode_id"], 4249010)
        self.assertNotIn(
            "guest_detail_session_count",
            result["source_groups"][0],
        )
        self.assertNotIn(
            "member_detail_session_count",
            result["source_groups"][0],
        )
        self.assertNotIn(
            "guest_read_start_count",
            result["episode_dropoffs"][0],
        )
        self.assertNotIn(
            "member_read_start_count",
            result["episode_dropoffs"][0],
        )

        combined_sql = "\n".join(call[0] for call in db.calls)
        self.assertIn("tb_author_product_entry_daily", combined_sql)
        self.assertIn("tb_product_detail_funnel_daily", combined_sql)
        self.assertIn("tb_product_episode_dropoff_daily", combined_sql)
        self.assertIn(
            "WHEN entry_source IN ('social', 'instagram', 'x', 'twitter', 'threads') THEN 'social'",
            combined_sql,
        )
        self.assertIn(
            "WHEN entry_source IS NULL OR entry_source = 'direct' THEN 'direct'",
            combined_sql,
        )
        self.assertIn("WHEN entry_source = 'other' THEN 'other'", combined_sql)
        self.assertIn("author_id = :author_id", combined_sql)
        self.assertIn("product_id = :product_id", combined_sql)
        self.assertIn("tb_site_reader_funnel_config", combined_sql)
        self.assertNotIn("MIN(raw_event.created_date)", combined_sql)
        self.assertNotIn("MAX(entry_mart.metric_version)", combined_sql)
        self.assertEqual(db.calls[0][1]["author_id"], 999)
        self.assertEqual(db.calls[0][1]["product_id"], 1117)

    async def test_author_product_inflow_dropoff_clamps_mixed_period_to_v2(self):
        db = FakeDb(
            [
                [
                    {
                        "guest_cutover_date": "2026-06-01",
                        "max_metric_version": 2,
                    }
                ],
                [
                    {
                        "product_id": 1117,
                        "entry_source_group": "direct",
                        "metric_version": 2,
                        "detail_view_count": 10,
                        "detail_session_count": 8,
                        "detail_visitor_count": 7,
                        "login_user_count": 3,
                        "guest_detail_view_count": 4,
                        "guest_detail_session_count": 3,
                        "guest_detail_visitor_count": 2,
                    }
                ],
                [
                    {
                        "product_id": 1117,
                        "entry_source_group": "direct",
                        "metric_version": 2,
                        "reader_session_count": 5,
                        "detail_exit_session_count": 3,
                        "guest_reader_session_count": 2,
                        "guest_detail_exit_session_count": 1,
                    }
                ],
                [
                    {
                        "product_id": 1117,
                        "episode_id": 4249010,
                        "episode_no": 1,
                        "episode_title": "1화",
                        "metric_version": 2,
                        "read_start_count": 6,
                        "episode_dropoff_count": 2,
                        "episode_dropoff_rate": 1 / 3,
                        "near_complete_count": 2,
                        "guest_read_start_count": 2,
                        "guest_episode_dropoff_count": 1,
                        "guest_near_complete_count": 1,
                    }
                ],
            ]
        )

        result = await partner_statistics_service.product_inflow_dropoff_statistics(
            product_id=1117,
            search_start_date="2026-05-30",
            search_end_date="2026-06-03",
            db=db,
            user_data={"user_id": 999},
        )

        self.assertEqual(result["metric_version"], 2)
        self.assertEqual(result["measurement_basis"], "guest_inclusive")
        self.assertEqual(result["requested_start_date"], "2026-05-30")
        self.assertEqual(result["effective_start_date"], "2026-06-01")
        self.assertEqual(result["start_date"], "2026-06-01")

        source = result["source_groups"][0]
        self.assertEqual(source["guest_detail_session_count"], 3)
        self.assertEqual(source["member_detail_session_count"], 5)
        self.assertEqual(source["guest_reader_session_count"], 2)
        self.assertEqual(source["member_reader_session_count"], 3)
        self.assertEqual(source["guest_detail_exit_session_count"], 1)
        self.assertEqual(source["member_detail_exit_session_count"], 2)

        dropoff = result["episode_dropoffs"][0]
        self.assertEqual(dropoff["guest_read_start_count"], 2)
        self.assertEqual(dropoff["member_read_start_count"], 4)
        self.assertEqual(dropoff["guest_episode_dropoff_count"], 1)
        self.assertEqual(dropoff["member_episode_dropoff_count"], 1)
        self.assertEqual(dropoff["guest_near_complete_count"], 1)
        self.assertEqual(dropoff["member_near_complete_count"], 1)

        for _, params in db.calls[1:]:
            self.assertEqual(params["start_date"], "2026-06-01")
            self.assertEqual(params["metric_version"], 2)

    def test_partner_router_exposes_author_product_inflow_dropoff_endpoint(self):
        paths = {getattr(route, "path", "") for route in partner_query.router.routes}

        self.assertIn("/partners/product-inflow-dropoff-statistics", paths)
