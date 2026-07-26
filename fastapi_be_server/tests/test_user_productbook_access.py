import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi import status

from app.const import ErrorMessages
from app.exceptions import CustomResponseException
from app.routers.common import ticket_item_command
from app.routers.user import (
    user_productbook_command,
    user_productbook_query,
    user_ticketbook_command,
    user_ticketbook_query,
)
from app.services.user import user_productbook_service, user_ticketbook_service
from app.utils.auth import login_required


class _Mappings:
    def __init__(self, row):
        self._row = row

    def one_or_none(self):
        return self._row


class _Result:
    def __init__(self, row=None, *, rowcount=1):
        self._row = row
        self.rowcount = rowcount

    def mappings(self):
        return _Mappings(self._row)


class _QueueDb:
    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return self._results.pop(0)


def _episode_row():
    return {
        "product_id": 10,
        "episode_no": 3,
        "product_title": "테스트 작품",
    }


def _productbook_row(*, expiry=None, ticket_type="free", **overrides):
    row = {
        "user_id": 42,
        "product_id": None,
        "episode_id": None,
        "use_yn": "N",
        "own_type": "rental",
        "ticket_type": ticket_type,
        "rental_expired_date": expiry,
        "acquisition_type": None,
        "applied_promotion_type": None,
        "gift_promotion_type": None,
        "applied_wff_active_yn": "N",
        "gift_wff_active_yn": "N",
    }
    row.update(overrides)
    return row


class UserProductbookRouteTest(unittest.TestCase):
    def test_public_mutation_routes_are_removed_but_use_remains(self):
        route_methods = {
            (route.path, method)
            for route in user_productbook_command.router.routes
            for method in route.methods
        }

        self.assertNotIn(("/user-productbook", "POST"), route_methods)
        self.assertNotIn(("/user-productbook/{id}", "PUT"), route_methods)
        self.assertNotIn(("/user-productbook/{id}", "DELETE"), route_methods)
        self.assertIn(("/user-productbook/{id}/use", "POST"), route_methods)

    def test_ticketbook_mutation_routes_are_removed_but_use_remains(self):
        route_methods = {
            (route.path, method)
            for route in user_ticketbook_command.router.routes
            for method in route.methods
        }

        self.assertNotIn(("/user-ticketbook", "POST"), route_methods)
        self.assertNotIn(("/user-ticketbook/{id}", "PUT"), route_methods)
        self.assertNotIn(("/user-ticketbook/{id}", "DELETE"), route_methods)
        self.assertIn(("/user-ticketbook/{id}/use", "POST"), route_methods)

    def test_ticket_item_issuance_routes_are_removed_but_catalog_routes_remain(self):
        route_methods = {
            (route.path, method)
            for route in ticket_item_command.router.routes
            for method in route.methods
        }

        self.assertNotIn(
            ("/ticket-items/{id}/issuance-productbook", "POST"), route_methods
        )
        self.assertNotIn(
            ("/ticket-items/{id}/issuance-ticketbook", "POST"), route_methods
        )
        self.assertIn(("/ticket-items", "POST"), route_methods)
        self.assertIn(("/ticket-items/{id}", "PUT"), route_methods)

    def test_productbook_detail_requires_strict_login(self):
        detail_route = next(
            route
            for route in user_productbook_query.router.routes
            if route.path == "/user-productbook/{id}"
        )
        dependency_calls = {
            dependency.call for dependency in detail_route.dependant.dependencies
        }

        self.assertIn(login_required, dependency_calls)

    def test_ticketbook_detail_requires_strict_login(self):
        detail_route = next(
            route
            for route in user_ticketbook_query.router.routes
            if route.path == "/user-ticketbook/{id}"
        )
        dependency_calls = {
            dependency.call for dependency in detail_route.dependant.dependencies
        }

        self.assertIn(login_required, dependency_calls)


class UserProductbookUseTest(unittest.IsolatedAsyncioTestCase):
    async def test_expired_unused_productbook_is_rejected_before_update(self):
        db = _QueueDb(
            [
                _Result(_episode_row()),
                _Result(
                    _productbook_row(expiry=datetime.now() - timedelta(seconds=1))
                ),
            ]
        )

        with (
            patch.object(
                user_productbook_service.comm_service,
                "get_user_from_kc",
                new=AsyncMock(return_value=42),
            ),
            patch.object(
                user_productbook_service,
                "create_product_order_with_items",
                new=AsyncMock(),
            ) as create_order,
        ):
            with self.assertRaises(CustomResponseException) as captured:
                await user_productbook_service.use_user_productbook(
                    id=7, episode_id=99, kc_user_id="kc-owner", db=db
                )

        self.assertEqual(captured.exception.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            captured.exception.message, ErrorMessages.EXPIRED_PRODUCTBOOK
        )
        self.assertEqual(len(db.calls), 2)
        create_order.assert_not_awaited()

    async def test_null_and_future_expiry_productbooks_remain_usable(self):
        for expiry in (None, datetime.now() + timedelta(days=1)):
            with self.subTest(expiry=expiry):
                db = _QueueDb(
                    [
                        _Result(_episode_row()),
                        _Result(_productbook_row(expiry=expiry)),
                        _Result(rowcount=1),
                    ]
                )
                with patch.object(
                    user_productbook_service.comm_service,
                    "get_user_from_kc",
                    new=AsyncMock(return_value=42),
                ):
                    response = await user_productbook_service.use_user_productbook(
                        id=7, episode_id=99, kc_user_id="kc-owner", db=db
                    )

                self.assertEqual(response, {"result": True})
                select_query, select_params = db.calls[1]
                self.assertIn("rental_expired_date", select_query)
                self.assertIn("FOR UPDATE", select_query.upper())
                self.assertEqual(select_params, {"id": 7})

                update_query, update_params = db.calls[2]
                normalized_update = " ".join(update_query.split())
                self.assertIn("user_id = :user_id", normalized_update)
                self.assertIn("own_type = 'rental'", normalized_update)
                self.assertIn("use_yn = 'N'", normalized_update)
                self.assertIn(
                    "rental_expired_date IS NULL OR rental_expired_date > NOW()",
                    normalized_update,
                )
                self.assertEqual(update_params["id"], 7)
                self.assertEqual(update_params["user_id"], 42)

    async def test_inactive_waiting_for_free_source_is_rejected(self):
        db = _QueueDb(
            [
                _Result(_episode_row()),
                _Result(
                    _productbook_row(
                        product_id=10,
                        acquisition_type="applied_promotion",
                        applied_promotion_type="waiting-for-free",
                        applied_wff_active_yn="N",
                    )
                ),
            ]
        )

        with (
            patch.object(
                user_productbook_service.comm_service,
                "get_user_from_kc",
                new=AsyncMock(return_value=42),
            ),
            patch.object(
                user_productbook_service,
                "create_product_order_with_items",
                new=AsyncMock(),
            ) as create_order,
        ):
            with self.assertRaises(CustomResponseException) as captured:
                await user_productbook_service.use_user_productbook(
                    id=7, episode_id=99, kc_user_id="kc-owner", db=db
                )

        self.assertEqual(captured.exception.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            captured.exception.message, ErrorMessages.EXPIRED_GIFT_VALIDITY
        )
        self.assertEqual(len(db.calls), 2)
        create_order.assert_not_awaited()

    async def test_active_waiting_for_free_gift_lineage_is_usable(self):
        db = _QueueDb(
            [
                _Result(_episode_row()),
                _Result(
                    _productbook_row(
                        ticket_type="waiting-for-free",
                        product_id=10,
                        acquisition_type="gift",
                        gift_promotion_type="waiting-for-free",
                        gift_wff_active_yn="Y",
                    )
                ),
                _Result(rowcount=1),
            ]
        )

        with (
            patch.object(
                user_productbook_service.comm_service,
                "get_user_from_kc",
                new=AsyncMock(return_value=42),
            ),
            patch.object(
                user_productbook_service,
                "create_product_order_with_items",
                new=AsyncMock(),
            ) as create_order,
        ):
            response = await user_productbook_service.use_user_productbook(
                id=7, episode_id=99, kc_user_id="kc-owner", db=db
            )

        self.assertEqual(response, {"result": True})
        self.assertEqual(len(db.calls), 3)
        create_order.assert_not_awaited()

    async def test_lost_update_fails_without_paid_order_side_effect(self):
        db = _QueueDb(
            [
                _Result(_episode_row()),
                _Result(_productbook_row(ticket_type="paid")),
                _Result(rowcount=0),
            ]
        )

        with (
            patch.object(
                user_productbook_service.comm_service,
                "get_user_from_kc",
                new=AsyncMock(return_value=42),
            ),
            patch.object(
                user_productbook_service,
                "create_product_order_with_items",
                new=AsyncMock(),
            ) as create_order,
        ):
            with self.assertRaises(CustomResponseException) as captured:
                await user_productbook_service.use_user_productbook(
                    id=7, episode_id=99, kc_user_id="kc-owner", db=db
                )

        self.assertEqual(captured.exception.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            captured.exception.message, ErrorMessages.ALREADY_USED_PRODUCTBOOK
        )
        create_order.assert_not_awaited()

    async def test_paid_order_is_created_once_after_successful_update(self):
        events = []

        class _EventDb(_QueueDb):
            async def execute(self, statement, params=None):
                result = await super().execute(statement, params)
                event = (
                    "update"
                    if "update tb_user_productbook" in str(statement)
                    else "query"
                )
                events.append(event)
                return result

        db = _EventDb(
            [
                _Result(_episode_row()),
                _Result(_productbook_row(ticket_type="paid")),
                _Result(rowcount=1),
            ]
        )

        async def record_order(**_kwargs):
            events.append("order")

        with (
            patch.object(
                user_productbook_service.comm_service,
                "get_user_from_kc",
                new=AsyncMock(return_value=42),
            ),
            patch.object(
                user_productbook_service,
                "create_product_order_with_items",
                new=AsyncMock(side_effect=record_order),
            ) as create_order,
        ):
            response = await user_productbook_service.use_user_productbook(
                id=7, episode_id=99, kc_user_id="kc-owner", db=db
            )

        self.assertEqual(response, {"result": True})
        create_order.assert_awaited_once()
        self.assertLess(events.index("update"), events.index("order"))


class UserProductbookDetailTest(unittest.IsolatedAsyncioTestCase):
    async def test_owner_gets_existing_productbook_detail(self):
        row = {"id": 7, "user_id": 42, "ticket_type": "free"}
        db = _QueueDb([_Result(row)])

        with patch.object(
            user_productbook_service.comm_service,
            "get_user_from_kc",
            new=AsyncMock(return_value=42),
        ):
            response = await user_productbook_service.user_productbook_detail_by_id(
                id=7, kc_user_id="kc-owner", db=db
            )

        self.assertEqual(response, {"data": row})
        query, params = db.calls[0]
        self.assertIn("id = :id", query)
        self.assertIn("user_id = :user_id", query)
        self.assertEqual(params, {"id": 7, "user_id": 42})

    async def test_unknown_productbook_subject_is_unauthorized(self):
        db = _QueueDb([])

        with patch.object(
            user_productbook_service.comm_service,
            "get_user_from_kc",
            new=AsyncMock(return_value=-1),
        ):
            with self.assertRaises(CustomResponseException) as captured:
                await user_productbook_service.user_productbook_detail_by_id(
                    id=7, kc_user_id="unknown", db=db
                )

        self.assertEqual(captured.exception.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(db.calls, [])

    async def test_other_or_missing_productbook_is_not_found(self):
        for productbook_id in (7, 999):
            with self.subTest(productbook_id=productbook_id):
                db = _QueueDb([_Result()])

                with patch.object(
                    user_productbook_service.comm_service,
                    "get_user_from_kc",
                    new=AsyncMock(return_value=42),
                ):
                    with self.assertRaises(CustomResponseException) as captured:
                        await user_productbook_service.user_productbook_detail_by_id(
                            id=productbook_id, kc_user_id="kc-owner", db=db
                        )

                self.assertEqual(
                    captured.exception.status_code, status.HTTP_404_NOT_FOUND
                )
                self.assertEqual(
                    captured.exception.message, ErrorMessages.NOT_FOUND_PRODUCTBOOK
                )


class UserTicketbookDetailTest(unittest.IsolatedAsyncioTestCase):
    async def test_owner_gets_existing_ticketbook_detail(self):
        row = {"id": 11, "user_id": 42, "ticket_type": "free"}
        db = _QueueDb([_Result(row)])

        with patch.object(
            user_ticketbook_service.comm_service,
            "get_user_from_kc",
            new=AsyncMock(return_value=42),
        ):
            response = await user_ticketbook_service.user_ticketbook_detail_by_id(
                id=11, kc_user_id="kc-owner", db=db
            )

        self.assertEqual(response, {"data": row})
        query, params = db.calls[0]
        self.assertIn("id = :id", query)
        self.assertIn("user_id = :user_id", query)
        self.assertEqual(params, {"id": 11, "user_id": 42})

    async def test_unknown_ticketbook_subject_is_unauthorized(self):
        db = _QueueDb([])

        with patch.object(
            user_ticketbook_service.comm_service,
            "get_user_from_kc",
            new=AsyncMock(return_value=-1),
        ):
            with self.assertRaises(CustomResponseException) as captured:
                await user_ticketbook_service.user_ticketbook_detail_by_id(
                    id=11, kc_user_id="unknown", db=db
                )

        self.assertEqual(captured.exception.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(db.calls, [])

    async def test_other_or_missing_ticketbook_is_not_found(self):
        for ticketbook_id in (11, 999):
            with self.subTest(ticketbook_id=ticketbook_id):
                db = _QueueDb([_Result()])

                with patch.object(
                    user_ticketbook_service.comm_service,
                    "get_user_from_kc",
                    new=AsyncMock(return_value=42),
                ):
                    with self.assertRaises(CustomResponseException) as captured:
                        await user_ticketbook_service.user_ticketbook_detail_by_id(
                            id=ticketbook_id, kc_user_id="kc-owner", db=db
                        )

                self.assertEqual(
                    captured.exception.status_code, status.HTTP_404_NOT_FOUND
                )
                self.assertEqual(
                    captured.exception.message, ErrorMessages.NOT_FOUND_TICKETBOOK
                )
