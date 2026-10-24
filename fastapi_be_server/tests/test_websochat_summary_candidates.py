import unittest
from unittest.mock import AsyncMock, patch

from app.services.websochat import websochat_service


class _FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _FakeMappings(self._rows)


class _CapturingSummaryDb:
    def __init__(self):
        self.queries: list[str] = []
        self.params_list: list[dict] = []

    async def execute(self, statement, params=None):
        self.queries.append(str(statement))
        self.params_list.append(dict(params or {}))
        return _FakeResult([])


class WebsochatSummaryCandidatesSqlTests(unittest.IsolatedAsyncioTestCase):
    async def _capture(self, *, keywords, query_text, mode, episode_no):
        db = _CapturingSummaryDb()
        rows = await websochat_service._get_websochat_summary_candidates(
            product_id=1182,
            keywords=keywords,
            query_text=query_text,
            latest_episode_no=30,
            mode=mode,
            episode_no=episode_no,
            db=db,
        )
        self.assertEqual(rows, [])
        self.assertEqual(len(db.queries), 1)
        return db.queries[0], db.params_list[0]

    async def test_general_mode_without_keywords_omits_score_terms(self):
        sql, params = await self._capture(
            keywords=[], query_text="아델리트", mode="general", episode_no=None
        )

        self.assertIn("ORDER BY", sql)
        self.assertNotIn("(0)", sql)
        self.assertIn("episode_to DESC", sql)
        self.assertIn("summary_id DESC", sql)
        self.assertNotIn("keyword_", sql)
        self.assertNotIn("keyword_", str(params))

    async def test_exact_mode_downgrade_without_keywords_omits_score_terms(self):
        with patch.object(
            websochat_service,
            "_resolve_websochat_exact_episode_no",
            new_callable=AsyncMock,
            return_value=None,
        ):
            sql, _ = await self._capture(
                keywords=[], query_text="3화", mode="exact", episode_no=3
            )

        self.assertIn("ORDER BY", sql)
        self.assertNotIn("(0)", sql)

    async def test_range_modes_without_keywords_omits_score_terms(self):
        for mode in ("early", "latest"):
            with self.subTest(mode=mode):
                sql, _ = await self._capture(
                    keywords=[], query_text="초반 이야기", mode=mode, episode_no=None
                )

                self.assertIn("ORDER BY", sql)
                self.assertNotIn("(0)", sql)

    async def test_general_mode_with_keywords_keeps_score_terms(self):
        sql, params = await self._capture(
            keywords=["아델리트", "레이븐"],
            query_text="아델리트 레이븐",
            mode="general",
            episode_no=None,
        )

        score_expr = (
            "CASE WHEN summary_text LIKE :keyword_1 THEN 1 ELSE 0 END"
            " + CASE WHEN summary_text LIKE :keyword_2 THEN 1 ELSE 0 END"
        )
        self.assertIn(f"CASE WHEN ({score_expr}) > 0 THEN 0 ELSE 1 END", sql)
        self.assertIn(f"({score_expr}) DESC", sql)
        self.assertIn("episode_to DESC", sql)
        self.assertIn("summary_id DESC", sql)
        self.assertEqual(params["keyword_1"], "%아델리트%")
        self.assertEqual(params["keyword_2"], "%레이븐%")

    async def test_exact_mode_with_keywords_keeps_match_prefix_and_abs(self):
        with patch.object(
            websochat_service,
            "_resolve_websochat_exact_episode_no",
            new_callable=AsyncMock,
            return_value=3,
        ):
            sql, params = await self._capture(
                keywords=["아델리트"], query_text="3화", mode="exact", episode_no=3
            )

        score_expr = "CASE WHEN summary_text LIKE :keyword_1 THEN 1 ELSE 0 END"
        self.assertIn(f"CASE WHEN ({score_expr}) > 0 THEN 0 ELSE 1 END", sql)
        self.assertIn("ABS(episode_to - :exact_episode_no) ASC", sql)
        self.assertIn("summary_id DESC", sql)
        self.assertNotIn(") DESC,\n          ABS", sql)
        self.assertEqual(params["exact_episode_no"], 3)

    async def test_early_mode_with_keywords_keeps_score_terms_and_ascending_order(self):
        sql, _ = await self._capture(
            keywords=["아델리트"], query_text="초반 이야기", mode="early", episode_no=None
        )

        score_expr = "CASE WHEN summary_text LIKE :keyword_1 THEN 1 ELSE 0 END"
        self.assertIn(f"CASE WHEN ({score_expr}) > 0 THEN 0 ELSE 1 END", sql)
        self.assertIn(f"({score_expr}) DESC", sql)
        self.assertIn("episode_to ASC", sql)
        self.assertIn("summary_id ASC", sql)
        self.assertIn("episode_to <= :early_upper_bound", sql)


if __name__ == "__main__":
    unittest.main()
