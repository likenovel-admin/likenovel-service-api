import sqlite3
import unittest

from app.exceptions import CustomResponseException
from app.services.common.search_service import SEARCH_ELIGIBILITY, products_of_searched, products_of_search_by_story, get_trending_keywords


class Result:
    def __init__(self, rows=(), scalar=None):
        self.rows, self.scalar = rows, scalar

    def mappings(self): return self
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None
    def scalar_one_or_none(self): return self.scalar


class Database:
    def __init__(self, results):
        self.results, self.calls = list(results), []

    async def execute(self, query, params=None):
        self.calls.append((str(query), params or {}))
        if not self.results:
            raise AssertionError("Unexpected database query")
        result = self.results.pop(0)
        if isinstance(result, Exception): raise result
        return result


def detail(pid):
    # A database row at the canonical product converter boundary.
    row = dict.fromkeys([
        "keywords", "primary_genre", "sub_genre", "current_rank", "coverImagePath",
        "newReleaseYn", "freeEpisodeTicketCount", "authorEventLevelBadgeImagePath",
        "authorInterestLevelBadgeImagePath", "interestEndDate", "count_cp_hit",
        "totalInterestCount", "count_hit", "count_recommend", "count_bookmark",
        "publish_days", "last_episode_date", "bookmarkYn", "monopoly_yn", "contract_yn",
        "offerAdvancePayment", "status_code", "canApplyForNormal", "canApplyForPaid",
    ])
    return {**row, "productId": pid, "title": f"작품 {pid}", "hasEpisodeCount": 1}


class SearchServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_retired_search_endpoints_do_not_return_fixtures_or_call_providers(self):
        self.assertEqual(await get_trending_keywords(), [])
        with self.assertRaises(CustomResponseException) as error:
            await products_of_search_by_story("공포")
        self.assertEqual(error.exception.status_code, 410)

    async def test_pagination_details_match_reasons_and_same_eligibility(self):
        rows = [{"product_id": i, "title": f"작품 {i}", "standard_keywords": [{"id": 2, "label": "공포"}]} for i in range(1, 5)]
        db = Database([Result(rows), Result([detail(3), detail(4)])])
        result = (await products_of_searched(None, db, page=2, limit=2, tags=["keyword:2"]))["data"]
        self.assertEqual(result["totalCount"], 4)
        self.assertEqual([p["productId"] for p in result["products"]], [3, 4])
        self.assertEqual(result["products"][0]["searchMatchReasons"], ["작품 태그: 공포"])
        self.assertEqual(result["facets"][0]["count"], 4)
        self.assertEqual(db.calls[1][1]["product_ids"], [3, 4])
        for sql, params in db.calls:
            self.assertIn(SEARCH_ELIGIBILITY, sql)
            self.assertEqual(params["include_adult"], 0)

    async def test_guest_cannot_enable_adult_by_query(self):
        db = Database([Result()])
        await products_of_searched(None, db, adult_yn="Y")
        self.assertEqual(len(db.calls), 1)
        self.assertEqual(db.calls[0][1]["include_adult"], 0)

    async def test_server_age_gate(self):
        for birthdate, expected in [(None, 0), ("2020-01-01", 0), ("1990-01-01", 1)]:
            db = Database([Result([{"user_id": 1}]), Result(scalar=birthdate), Result()])
            await products_of_searched("session-sub", db, adult_yn="Y")
            self.assertEqual(db.calls[-1][1]["include_adult"], expected)

    async def test_out_of_range_page_retains_counts_and_selected_tag(self):
        db = Database([Result([{"product_id": 1, "title": "작품", "standard_keywords": [{"id": 2, "label": "공포"}]}])])
        result = (await products_of_searched(None, db, page=100, tags=["keyword:2"]))["data"]
        self.assertEqual(result["products"], [])
        self.assertEqual(result["totalCount"], 1)
        self.assertEqual(result["selectedTags"][0]["label"], "공포")

    async def test_invalid_requests_fail_before_db_and_errors_are_not_empty_success(self):
        for params in [{"page": 0}, {"limit": 31}, {"keyword": "a" * 101}, {"tags": ["x"] * 13}, {"tags": ["x" * 121]}]:
            with self.assertRaises(CustomResponseException) as error:
                await products_of_searched(None, Database([]), **params)
            self.assertEqual(error.exception.status_code, 422)
        with self.assertLogs("search_service", level="ERROR"):
            with self.assertRaises(CustomResponseException) as error:
                await products_of_searched(None, Database([RuntimeError("database unavailable")]))
        self.assertEqual(error.exception.status_code, 500)

    async def test_keyword_only_preserves_events_and_quests(self):
        db = Database([Result(), Result([{"id": 3, "title": "이벤트"}]), Result([{"questId": 4}])])
        result = (await products_of_searched(None, db, keyword="이벤트"))["data"]
        self.assertEqual(result["events"][0]["id"], 3)
        self.assertEqual(result["quests"][0]["questId"], 4)


class EligibilityTest(unittest.TestCase):
    def test_private_blind_adult_and_no_active_public_episode_are_excluded(self):
        # Execute the actual predicate instead of inspecting SQL strings only.
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE tb_product(product_id INT, open_yn TEXT, blind_yn TEXT, ratings_code TEXT)")
        db.execute("CREATE TABLE tb_product_episode(product_id INT, use_yn TEXT, open_yn TEXT)")
        db.executemany("INSERT INTO tb_product VALUES (?, ?, ?, ?)", [
            (1, "Y", "N", "all"), (2, "N", "N", "all"), (3, "Y", "Y", "all"),
            (4, "Y", "N", "adult"), (5, "Y", "N", "all"), (6, "Y", "N", "all"), (7, "Y", "N", "all"),
        ])
        db.executemany("INSERT INTO tb_product_episode VALUES (?, ?, ?)", [
            (1, "Y", "Y"), (2, "Y", "Y"), (3, "Y", "Y"), (4, "Y", "Y"), (6, "N", "Y"), (7, "Y", "N"),
        ])
        query = "SELECT product_id FROM tb_product p WHERE " + SEARCH_ELIGIBILITY
        self.assertEqual(db.execute(query, {"include_adult": 0}).fetchall(), [(1,)])
        self.assertEqual(db.execute(query, {"include_adult": 1}).fetchall(), [(1,), (4,)])


class SearchRouteTest(unittest.TestCase):
    def test_query_contract_limits_and_retired_route(self):
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient
        from app.routers.common import search_query

        app = FastAPI()
        app.include_router(search_query.router)
        app.dependency_overrides[search_query.chk_cur_user] = lambda: {}
        app.dependency_overrides[search_query.get_likenovel_db] = lambda: Database([Result()])
        app.dependency_overrides[search_query.analysis_logger] = lambda: None

        @app.exception_handler(CustomResponseException)
        async def handle_error(request, error):
            return JSONResponse({"message": error.message}, status_code=error.status_code)

        with TestClient(app) as client:
            response = client.get("/search")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["data"]["facets"], [])
            self.assertEqual(response.json()["data"]["totalCount"], 0)
            response = client.get("/search", params=[("tag", "dna:goal:퇴마"), ("tag", "keyword:2")])
            self.assertEqual(response.status_code, 200)
            for params in [{"page": 0}, {"limit": 31}, {"orderby": "unsafe"}, {"keyword": "a" * 101}, {"tag": ["x"] * 13}, {"tag": "x" * 121}]:
                self.assertEqual(client.get("/search", params=params).status_code, 422)
            self.assertEqual(client.post("/search/story", params={"story": "공포"}).status_code, 410)
