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
        self.assertEqual(len(result["source_groups"]), 2)
        self.assertEqual(result["source_groups"][0]["entry_source_group"], "social")
        self.assertEqual(result["source_groups"][0]["read_conversion_rate"], 0.3)
        self.assertEqual(result["source_groups"][0]["detail_exit_rate"], 0.7)
        self.assertEqual(result["episode_dropoffs"][0]["episode_id"], 4249010)

        combined_sql = "\n".join(call[0] for call in db.calls)
        self.assertIn("tb_author_product_entry_daily", combined_sql)
        self.assertIn("tb_product_detail_funnel_daily", combined_sql)
        self.assertIn("tb_product_episode_dropoff_daily", combined_sql)
        self.assertIn("author_id = :author_id", combined_sql)
        self.assertIn("product_id = :product_id", combined_sql)
        self.assertEqual(db.calls[0][1]["author_id"], 999)
        self.assertEqual(db.calls[0][1]["product_id"], 1117)

    def test_partner_router_exposes_author_product_inflow_dropoff_endpoint(self):
        paths = {getattr(route, "path", "") for route in partner_query.router.routes}

        self.assertIn("/partners/product-inflow-dropoff-statistics", paths)
