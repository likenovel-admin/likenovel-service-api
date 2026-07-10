import unittest
from unittest.mock import AsyncMock, patch

from app.const import ErrorMessages
from app.exceptions import CustomResponseException
from app.routers.partner import partner_query
from app.services.partner import partner_product_service
from app.services.partner import partner_sales_service


class _FakeResult:
    def __init__(self, *, scalar_value=None, first_row=None, rows=None, one_row=None):
        self._scalar_value = scalar_value
        self._first_row = first_row
        self._rows = rows or []
        self._one_row = one_row

    def scalar(self):
        return self._scalar_value

    def mappings(self):
        return self

    def first(self):
        return self._first_row

    def all(self):
        return self._rows

    def one_or_none(self):
        return self._one_row


class _FakeDb:
    def __init__(self, results):
        self._results = list(results)
        self.queries = []
        self.params = []

    async def execute(self, query, params=None):
        self.queries.append(str(query))
        self.params.append(params or {})
        return self._results.pop(0)


class PartnerEpisodeSalesAuthorizationTest(unittest.IsolatedAsyncioTestCase):
    async def _call_detail(self, db, user_data, *, page=1, count_per_page=8):
        return await partner_sales_service.sales_by_episode_list_by_product_id(
            91,
            "",
            "",
            "",
            "",
            page,
            count_per_page,
            db,
            user_data,
        )

    async def test_episode_sales_detail_denies_unowned_author_before_sales_query(self):
        db = _FakeDb([_FakeResult(scalar_value=None)])

        with self.assertRaises(CustomResponseException) as raised:
            await self._call_detail(db, {"user_id": 17, "role": "author"})

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.message, ErrorMessages.FORBIDDEN)
        self.assertEqual(len(db.queries), 1)
        self.assertIn("p.author_id = :user_id", db.queries[0])
        self.assertNotIn("tb_ptn_product_episode_sales", db.queries[0])

    async def test_episode_sales_detail_denies_uncontracted_cp_without_owner_fallback(self):
        db = _FakeDb([_FakeResult(scalar_value=None)])

        with self.assertRaises(CustomResponseException) as raised:
            await self._call_detail(db, {"user_id": 23, "role": "CP"})

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.message, ErrorMessages.FORBIDDEN)
        self.assertEqual(len(db.queries), 1)
        self.assertIn("p.cp_user_id = :user_id", db.queries[0])
        self.assertNotIn("p.user_id = :user_id", db.queries[0])

    async def test_episode_sales_detail_allows_each_documented_role_scope(self):
        cases = [
            ({"user_id": 1, "role": "admin"}, None),
            ({"user_id": 17, "role": "author"}, "p.author_id = :user_id"),
            ({"user_id": 23, "role": "CP"}, "p.cp_user_id = :user_id"),
        ]

        for user_data, expected_condition in cases:
            with self.subTest(role=user_data["role"]):
                results = [_FakeResult(rows=[])]
                if user_data["role"] != "admin":
                    results.insert(0, _FakeResult(scalar_value=1))
                db = _FakeDb(results)

                response = await self._call_detail(
                    db, user_data, page=-1, count_per_page=-1
                )

                self.assertEqual(response["results"], [])
                if expected_condition:
                    self.assertEqual(len(db.queries), 2)
                    self.assertIn(expected_condition, db.queries[0])
                else:
                    self.assertEqual(len(db.queries), 1)
                    self.assertIn("tb_ptn_product_episode_sales", db.queries[0])

    async def test_episode_sales_detail_fails_closed_for_unknown_role(self):
        db = _FakeDb([])

        with self.assertRaises(CustomResponseException) as raised:
            await self._call_detail(db, {"user_id": 99, "role": "unknown"})

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.message, ErrorMessages.FORBIDDEN)
        self.assertEqual(db.queries, [])

    async def test_episode_sales_aggregate_cp_scope_uses_contract_link_only(self):
        db = _FakeDb([_FakeResult(rows=[])])

        await partner_sales_service.sales_by_episode_list(
            "", "", "", "", -1, -1, db, {"user_id": 23, "role": "CP"}
        )

        self.assertEqual(len(db.queries), 1)
        self.assertIn("cp_user_id = 23", db.queries[0])
        self.assertNotIn("OR user_id = 23", db.queries[0])

    async def test_monthly_sales_detail_denial_is_forbidden_not_internal_error(self):
        db = _FakeDb([_FakeResult(scalar_value=None)])

        with self.assertRaises(CustomResponseException) as raised:
            await partner_sales_service.monthly_sales_by_product_detail_by_product_id(
                91, db, {"user_id": 23, "role": "CP"}
            )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.message, ErrorMessages.FORBIDDEN)
        self.assertEqual(len(db.queries), 1)
        self.assertIn("p.cp_user_id = :user_id", db.queries[0])
        self.assertNotIn("p.user_id = :user_id", db.queries[0])

    async def test_monthly_sales_list_cp_scope_uses_contract_link_only(self):
        db = _FakeDb(
            [
                _FakeResult(first_row={"total_count": 0}),
                _FakeResult(rows=[]),
                _FakeResult(one_row=None),
                _FakeResult(rows=[]),
            ]
        )

        await partner_sales_service.monthly_sales_by_product_list(
            "", "", "", "", 1, 8, db, {"user_id": 23, "role": "CP"}
        )

        self.assertIn("p.cp_user_id = 23", db.queries[0])
        self.assertNotIn("p.user_id = 23", db.queries[0])
        self.assertIn("p.cp_user_id = 23", db.queries[1])
        self.assertNotIn("p.user_id = 23", db.queries[1])

    async def test_other_financial_lists_use_cp_contract_link_only(self):
        cases = [
            (
                partner_sales_service.daily_ticket_list,
                [
                    _FakeResult(first_row={"total_count": 0}),
                    _FakeResult(rows=[]),
                ],
            ),
            (
                partner_sales_service.monthly_settlement_list,
                [
                    _FakeResult(first_row={"total_count": 0}),
                    _FakeResult(rows=[]),
                    _FakeResult(one_row=None),
                    _FakeResult(rows=[]),
                ],
            ),
            (
                partner_sales_service.product_contract_offer_deduction_list,
                [
                    _FakeResult(first_row={"total_count": 0}),
                    _FakeResult(rows=[]),
                ],
            ),
        ]

        for list_function, results in cases:
            with self.subTest(function=list_function.__name__):
                db = _FakeDb(results)

                await list_function(
                    "", "", "", "", 1, 8, db, {"user_id": 23, "role": "CP"}
                )

                self.assertIn("cp_user_id = 23", db.queries[0])
                self.assertNotIn("OR user_id = 23", db.queries[0])
                self.assertIn("cp_user_id = 23", db.queries[1])
                self.assertNotIn("OR user_id = 23", db.queries[1])

    async def test_financial_lists_fail_closed_for_unknown_role(self):
        list_functions = [
            partner_sales_service.monthly_sales_by_product_list,
            partner_sales_service.sales_by_episode_list,
            partner_sales_service.daily_ticket_list,
            partner_sales_service.monthly_settlement_list,
            partner_sales_service.product_contract_offer_deduction_list,
        ]

        for list_function in list_functions:
            with self.subTest(function=list_function.__name__):
                db = _FakeDb([])

                with self.assertRaises(CustomResponseException) as raised:
                    await list_function(
                        "",
                        "",
                        "",
                        "",
                        1,
                        8,
                        db,
                        {"user_id": 99, "role": "unknown"},
                    )

                self.assertEqual(raised.exception.status_code, 403)
                self.assertEqual(raised.exception.message, ErrorMessages.FORBIDDEN)
                self.assertEqual(db.queries, [])


class PartnerEpisodeSalesRouterAuthorizationTest(unittest.IsolatedAsyncioTestCase):
    async def test_detail_and_download_routes_forward_checked_user_data(self):
        db = object()
        user_data = {"user_id": 23, "role": "CP"}

        with patch.object(
            partner_query, "check_user", AsyncMock(return_value=user_data)
        ), patch.object(
            partner_query.partner_sales_service,
            "sales_by_episode_list_by_product_id",
            AsyncMock(return_value={"results": []}),
        ) as service_mock:
            await partner_query.sales_by_episode_list_by_product_id(
                id=91,
                search_target="",
                search_word="",
                search_start_date="",
                search_end_date="",
                page=2,
                count_per_page=8,
                db=db,
                user={"sub": "kc-user"},
            )
            service_mock.assert_awaited_once_with(
                91, "", "", "", "", 2, 8, db, user_data
            )

            service_mock.reset_mock()
            await partner_query.sales_by_episode_list_by_product_id_for_download(
                id=91,
                search_target="",
                search_word="",
                search_start_date="",
                search_end_date="",
                db=db,
                user={"sub": "kc-user"},
            )
            service_mock.assert_awaited_once_with(
                91, "", "", "", "", -1, -1, db, user_data
            )


class PartnerEpisodeSalesProductListScopeTest(unittest.IsolatedAsyncioTestCase):
    async def _product_list_queries(self, *, from_episode_sales_page):
        db = _FakeDb(
            [
                _FakeResult(first_row={"total_count": 0}),
                _FakeResult(rows=[]),
            ]
        )
        await partner_product_service.product_list(
            "",
            "",
            "",
            "",
            "",
            1,
            8,
            db,
            {"user_id": 23, "role": "CP"},
            from_episode_sales_page=from_episode_sales_page,
        )
        return db.queries

    async def test_episode_sales_product_list_uses_cp_contract_link_only(self):
        queries = await self._product_list_queries(from_episode_sales_page=True)

        for query in queries:
            self.assertIn("a.cp_user_id = 23", query)
            self.assertNotIn("a.user_id = 23", query)

    async def test_general_product_list_keeps_existing_cp_owner_fallback(self):
        for flag in (False, None):
            with self.subTest(from_episode_sales_page=flag):
                queries = await self._product_list_queries(
                    from_episode_sales_page=flag
                )

                for query in queries:
                    self.assertIn("a.cp_user_id = 23", query)
                    self.assertIn("a.user_id = 23", query)

    async def test_episode_sales_product_list_fails_closed_for_unknown_role(self):
        db = _FakeDb([])

        with self.assertRaises(CustomResponseException) as raised:
            await partner_product_service.product_list(
                "",
                "",
                "",
                "",
                "",
                1,
                8,
                db,
                {"user_id": 99, "role": "unknown"},
                from_episode_sales_page=True,
            )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.message, ErrorMessages.FORBIDDEN)
        self.assertEqual(db.queries, [])


if __name__ == "__main__":
    unittest.main()
