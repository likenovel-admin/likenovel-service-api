import unittest

from app.services.partner import partner_statistics_service as service


class _FakeMappings:
    def __init__(self, first_row=None, rows=None):
        self._first_row = first_row
        self._rows = rows or []

    def first(self):
        return self._first_row

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, first_row=None, rows=None):
        self._mappings = _FakeMappings(first_row=first_row, rows=rows)

    def mappings(self):
        return self._mappings


class _RecordingDb:
    def __init__(self):
        self.queries = []
        self._results = [
            _FakeResult(first_row={"total_count": 0}),
            _FakeResult(rows=[]),
        ]

    async def execute(self, query, params=None):
        self.queries.append(" ".join(str(query).split()))
        return self._results.pop(0)


class PartnerEpisodeStatisticsPermissionTest(unittest.IsolatedAsyncioTestCase):
    async def _queries_for(self, user_data):
        db = _RecordingDb()

        result = await service.product_episode_statistics_list(
            search_target="",
            search_word="",
            search_start_date="",
            search_end_date="",
            page=1,
            count_per_page=15,
            db=db,
            user_data=user_data,
        )

        self.assertEqual(result["total_count"], 0)
        self.assertEqual(len(db.queries), 2)
        return db.queries

    async def test_cp_scope_uses_statistics_alias_in_both_queries(self):
        queries = await self._queries_for({"role": "CP", "user_id": 1079})

        for query in queries:
            self.assertIn("s.product_id IN", query)
            self.assertNotIn("p.product_id IN", query)
        self.assertIn("WHERE cp_user_id = 1079", queries[0])
        self.assertIn("OR user_id = 1079", queries[0])

    async def test_author_scope_filters_statistics_by_owned_product_ids(self):
        queries = await self._queries_for({"role": "author", "user_id": 77})

        for query in queries:
            self.assertIn("s.product_id IN", query)
            self.assertIn("WHERE author_id = 77", query)
            self.assertNotIn("p.author_id", query)


if __name__ == "__main__":
    unittest.main()
