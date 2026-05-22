import unittest
from datetime import datetime, timedelta

from app.services.partner import partner_statistics_service as service


class ProductRecent24hStatisticsServiceTest(unittest.TestCase):
    def test_hit_delta_clamps_negative_values(self):
        self.assertEqual(service._recent_24h_hit_delta(10, 15), 0)
        self.assertEqual(service._recent_24h_hit_delta(15, 10), 5)

    def test_episode_rows_are_camel_case_and_use_product_total_for_share(self):
        rows = service._build_recent_24h_episode_rows(
            current_rows=[
                {"episode_id": 1, "episode_no": 1, "episode_title": "1화", "count_hit": 150},
                {"episode_id": 2, "episode_no": 2, "episode_title": "2화", "count_hit": 60},
            ],
            previous_rows=[
                {"episode_id": 1, "count_hit": 100},
                {"episode_id": 2, "count_hit": 50},
            ],
            product_recent_24h_count_hit=100,
        )

        self.assertEqual(rows[0]["episodeId"], 1)
        self.assertEqual(rows[0]["episodeTitle"], "1화")
        self.assertEqual(rows[0]["recent24hCountHit"], 50)
        self.assertEqual(rows[0]["shareRate"], 0.5)
        self.assertEqual(rows[1]["recent24hCountHit"], 10)
        self.assertEqual(rows[1]["shareRate"], 0.1)

    def test_episode_snapshots_are_not_ready_without_current_rows(self):
        self.assertFalse(
            service._recent_24h_episode_snapshots_ready(
                current_rows=[],
                previous_rows=[{"episode_id": 1, "count_hit": 100}],
                total_episode_count=1,
            )
        )
        self.assertTrue(
            service._recent_24h_episode_snapshots_ready(
                current_rows=[
                    {"episode_id": 1, "episode_no": 1, "count_hit": 150}
                ],
                previous_rows=[],
                total_episode_count=1,
            )
        )
        self.assertFalse(
            service._recent_24h_episode_snapshots_ready(
                current_rows=[],
                previous_rows=[],
                total_episode_count=0,
            )
        )
        self.assertTrue(
            service._recent_24h_episode_snapshots_ready(
                current_rows=[
                    {"episode_id": 1, "episode_no": 1, "count_hit": 150}
                ],
                previous_rows=[{"episode_id": 1, "count_hit": 100}],
                total_episode_count=1,
            )
        )

    def test_episode_snapshots_do_not_compare_live_episode_count(self):
        self.assertTrue(
            service._recent_24h_episode_snapshots_ready(
                current_rows=[
                    {"episode_id": 1, "episode_no": 1, "count_hit": 150}
                ],
                previous_rows=[{"episode_id": 1, "count_hit": 100}],
                total_episode_count=2,
            )
        )

    def test_episode_snapshots_do_not_require_previous_episode_ids_to_match(self):
        self.assertTrue(
            service._recent_24h_episode_snapshots_ready(
                current_rows=[
                    {"episode_id": 1, "episode_no": 1, "count_hit": 150},
                    {"episode_id": 2, "episode_no": 2, "count_hit": 80},
                ],
                previous_rows=[
                    {"episode_id": 1, "count_hit": 100},
                    {"episode_id": 3, "count_hit": 70},
                ],
                total_episode_count=2,
            )
        )

    def test_episode_snapshots_are_ready_when_episode_sets_are_complete(self):
        self.assertTrue(
            service._recent_24h_episode_snapshots_ready(
                current_rows=[
                    {"episode_id": 2, "episode_no": 2, "count_hit": 80},
                    {"episode_id": 1, "episode_no": 1, "count_hit": 150},
                ],
                previous_rows=[
                    {"episode_id": 1, "count_hit": 100},
                    {"episode_id": 2, "count_hit": 70},
                ],
                total_episode_count=2,
            )
        )

    def test_not_ready_response_does_not_fake_zero_views(self):
        basis_at = datetime(2026, 5, 21, 13, 30, 0)
        response = service._build_recent_24h_not_ready_response(
            product_id=1129,
            basis_at=basis_at,
            cumulative_count_hit=1234,
            total_episode_count=35,
        )

        self.assertEqual(response["productId"], 1129)
        self.assertEqual(response["basisAt"], basis_at.isoformat())
        self.assertIsNone(response["fromAt"])
        self.assertEqual(response["summary"]["rankStatus"], "not_ready")
        self.assertEqual(response["summary"]["cumulativeCountHit"], 1234)
        self.assertIsNone(response["summary"]["recent24hCountHit"])
        self.assertIsNone(response["summary"]["previous24hCountHit"])
        self.assertEqual(response["hourly"], [])
        self.assertEqual(response["episodes"], [])

    def test_ready_response_keeps_rank_pending_until_top50_switch(self):
        basis_at = datetime(2026, 5, 21, 13, 30, 0)
        response = service._build_recent_24h_response(
            product_id=1129,
            current_basis=basis_at,
            previous_basis=basis_at - timedelta(hours=24),
            total_episode_count=35,
            recent_24h_count_hit=100,
            previous_24h_count_hit=80,
            cumulative_count_hit=1234,
            hourly_rows=[],
            episode_rows=[],
        )

        self.assertEqual(response["summary"]["rankStatus"], "pending")

    def test_hourly_rows_require_pairwise_snapshot_delta(self):
        basis = datetime(2026, 5, 21, 13, 30, 0)
        snapshots = [
            {"basis_at": basis - timedelta(hours=2), "count_hit": 100},
            {"basis_at": basis - timedelta(hours=1), "count_hit": 130},
            {"basis_at": basis, "count_hit": 145},
        ]

        rows = service._build_recent_24h_hourly_rows(snapshots)

        self.assertEqual(rows, [
            {"hourLabel": "12:30", "countHit": 30},
            {"hourLabel": "13:30", "countHit": 15},
        ])


class ProductRecent24hStatisticsQueryTest(unittest.IsolatedAsyncioTestCase):
    class _FakeMappings:
        def __init__(self, first_row):
            self._first_row = first_row

        def first(self):
            return self._first_row

        def all(self):
            return []

    class _FakeResult:
        def __init__(self, first_row):
            self._first_row = first_row

        def mappings(self):
            return ProductRecent24hStatisticsQueryTest._FakeMappings(
                self._first_row
            )

    class _FakeDb:
        def __init__(self):
            self.queries = []
            self._results = [
                ProductRecent24hStatisticsQueryTest._FakeResult(
                    {"product_id": 2026, "count_hit": 123}
                ),
                ProductRecent24hStatisticsQueryTest._FakeResult(
                    {"total_episode_count": 1}
                ),
                ProductRecent24hStatisticsQueryTest._FakeResult(
                    {"basis_at": None}
                ),
            ]

        async def execute(self, query, params=None):
            self.queries.append(str(query))
            return self._results.pop(0)

    async def test_product_lookup_uses_real_tb_product_columns(self):
        db = self._FakeDb()

        await service.product_recent_24h_statistics(
            product_id=2026,
            db=db,
            user_data={"user_id": 1063},
        )

        self.assertIn("p.author_id = :user_id", db.queries[0])
        self.assertNotIn("p.use_yn", db.queries[0])
