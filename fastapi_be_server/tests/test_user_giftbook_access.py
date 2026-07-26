import inspect
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from fastapi import status

from app.exceptions import CustomResponseException
from app.routers.user import user_giftbook_command, user_giftbook_query
from app.schemas.user_giftbook import PostUserGiftbookReqBody
from app.services.user import user_giftbook_service
from app.utils.auth import login_required


class _Mappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def one_or_none(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows=(), *, rowcount=1, lastrowid=1):
        self._rows = list(rows)
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def mappings(self):
        return _Mappings(self._rows)


class _NestedTransaction:
    def __init__(self, db):
        self.db = db
        self.start_index = 0

    async def __aenter__(self):
        self.start_index = len(self.db.writes)
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        savepoint_writes = self.db.writes[self.start_index :]
        if exc_type is None:
            self.db.committed_savepoints.append(list(savepoint_writes))
        else:
            self.db.rolled_back_savepoints.append(list(savepoint_writes))
            del self.db.writes[self.start_index :]
        return False


class _QueueDb:
    def __init__(self, results):
        self._results = list(results)
        self.calls = []
        self.writes = []
        self.committed_savepoints = []
        self.rolled_back_savepoints = []

    def begin_nested(self):
        return _NestedTransaction(self)

    async def execute(self, statement, params=None):
        query = str(statement)
        self.calls.append((query, params or {}))
        result = self._results.pop(0)
        if isinstance(result, BaseException):
            raise result
        if query.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            self.writes.append(query)
        return result


def _giftbook_body(user_id=42, amount=1):
    return PostUserGiftbookReqBody(
        user_id=user_id,
        ticket_type="comped",
        own_type="rental",
        reason="test",
        amount=amount,
    )


def _giftbook_row(user_id=42, amount=1):
    return {
        "id": 7,
        "user_id": user_id,
        "episode_id": 99,
        "episode_product_id": 10,
        "episode_price_type": "paid",
        "episode_no": 3,
        "episode_title": "제3화",
        "episode_text_count": 1234,
        "episode_content": "본문이 응답에 포함되면 안 됩니다",
        "amount": amount,
    }


class UserGiftbookRouteTest(unittest.IsolatedAsyncioTestCase):
    def test_public_mutation_routes_are_removed_but_receive_remains(self):
        route_methods = {
            (route.path, method)
            for route in user_giftbook_command.router.routes
            for method in route.methods
        }

        self.assertNotIn(("/user-giftbook", "POST"), route_methods)
        self.assertNotIn(("/user-giftbook/{id}", "PUT"), route_methods)
        self.assertNotIn(("/user-giftbook/{id}", "DELETE"), route_methods)
        self.assertIn(("/user-giftbook/{id}/receive", "POST"), route_methods)

    async def test_detail_route_requires_strict_login(self):
        detail_route = next(
            route
            for route in user_giftbook_query.router.routes
            if route.path == "/user-giftbook/{id}"
        )
        dependency_calls = {
            dependency.call for dependency in detail_route.dependant.dependencies
        }
        self.assertIn(login_required, dependency_calls)

        with self.assertRaises(CustomResponseException) as captured:
            await login_required({})
        self.assertEqual(captured.exception.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_router_passes_authenticated_subject_to_detail_service(self):
        signature = inspect.signature(
            user_giftbook_query.user_giftbook_detail_by_id
        )
        self.assertIn("kc_user_id", signature.parameters)


class UserGiftbookDetailTest(unittest.IsolatedAsyncioTestCase):
    async def test_owner_gets_metadata_without_episode_body(self):
        db = _QueueDb([_Result([_giftbook_row()])])
        with patch.object(
            user_giftbook_service.comm_service,
            "get_user_from_kc",
            new=AsyncMock(return_value=42),
        ):
            response = await user_giftbook_service.user_giftbook_detail_by_id(
                id=7, kc_user_id="kc-owner", db=db
            )

        query, params = db.calls[0]
        self.assertIn("ug.id = :id", query)
        self.assertIn("ug.user_id = :user_id", query)
        self.assertEqual(params, {"id": 7, "user_id": 42})
        self.assertEqual(response["data"]["episode"]["episode_id"], 99)
        self.assertNotIn("episode_content", response["data"]["episode"])
        self.assertNotIn("episode_content", response["data"])

    async def test_other_or_missing_giftbook_is_not_found(self):
        db = _QueueDb([_Result([])])
        with patch.object(
            user_giftbook_service.comm_service,
            "get_user_from_kc",
            new=AsyncMock(return_value=42),
        ):
            with self.assertRaises(CustomResponseException) as captured:
                await user_giftbook_service.user_giftbook_detail_by_id(
                    id=8, kc_user_id="kc-owner", db=db
                )

        self.assertEqual(captured.exception.status_code, status.HTTP_404_NOT_FOUND)

    async def test_unknown_authenticated_subject_is_unauthorized(self):
        db = _QueueDb([])
        with patch.object(
            user_giftbook_service.comm_service,
            "get_user_from_kc",
            new=AsyncMock(return_value=-1),
        ):
            with self.assertRaises(CustomResponseException) as captured:
                await user_giftbook_service.user_giftbook_detail_by_id(
                    id=7, kc_user_id="unknown", db=db
                )

        self.assertEqual(captured.exception.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(db.calls, [])


class UserGiftbookBodyTest(unittest.IsolatedAsyncioTestCase):
    def test_shared_query_and_transform_exclude_episode_body(self):
        query = user_giftbook_service._build_giftbook_query_with_joins()
        self.assertNotIn("episode_content", query)

        transformed = user_giftbook_service._transform_giftbook_row_to_nested_structure(
            _giftbook_row()
        )
        self.assertNotIn("episode_content", transformed["episode"])
        self.assertNotIn("episode_content", transformed)

    async def test_received_history_excludes_episode_body(self):
        db = _QueueDb([_Result([_giftbook_row()])])
        with patch.object(
            user_giftbook_service.comm_service,
            "get_user_from_kc",
            new=AsyncMock(return_value=42),
        ):
            response = await user_giftbook_service.user_gift_transaction_list(
                kc_user_id="kc-owner", type="received", db=db
            )

        query, _ = db.calls[0]
        self.assertNotIn("episode_content", query)
        self.assertNotIn("episode_content", response["data"][0]["episode"])


class UserGiftbookGrantBindingTest(unittest.IsolatedAsyncioTestCase):
    async def test_trusted_user_id_is_required(self):
        with self.assertRaises(CustomResponseException) as captured:
            await user_giftbook_service.post_user_giftbook(
                req_body=_giftbook_body(), kc_user_id="kc-user", db=_QueueDb([])
            )

        self.assertEqual(captured.exception.status_code, status.HTTP_403_FORBIDDEN)

    async def test_body_user_must_match_trusted_user(self):
        with self.assertRaises(CustomResponseException) as captured:
            await user_giftbook_service.post_user_giftbook(
                req_body=_giftbook_body(user_id=42),
                kc_user_id="",
                db=_QueueDb([]),
                user_id=43,
            )

        self.assertEqual(captured.exception.status_code, status.HTTP_403_FORBIDDEN)

    async def test_matching_trusted_user_keeps_internal_grant_contract(self):
        db = _QueueDb([_Result(lastrowid=77)])
        with patch.object(
            user_giftbook_service.statistics_service,
            "insert_site_statistics_log",
            new=AsyncMock(),
        ):
            response = await user_giftbook_service.post_user_giftbook(
                req_body=_giftbook_body(user_id=42),
                kc_user_id="",
                db=db,
                user_id=42,
            )

        self.assertEqual(response["result"].user_id, 42)
        self.assertIn("insert into tb_user_giftbook", db.calls[0][0].lower())

    async def test_grant_rejects_amount_below_one_before_writes(self):
        db = _QueueDb([])
        with self.assertRaises(CustomResponseException) as captured:
            await user_giftbook_service.post_user_giftbook(
                req_body=_giftbook_body(user_id=42, amount=0),
                kc_user_id="",
                db=db,
                user_id=42,
            )

        self.assertEqual(captured.exception.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(db.calls, [])

    async def test_auto_receive_rolls_back_partial_grant_when_insert_fails(self):
        body = _giftbook_body(user_id=42, amount=2)
        body.promotion_type = "event"
        body.acquisition_type = "event"
        db = _QueueDb(
            [
                _Result(lastrowid=77),
                _Result([{"noti_yn": "N"}]),
                _Result([{"profile_id": 5}]),
                _Result(),
                RuntimeError("second productbook insert failed"),
            ]
        )

        with patch.object(
            user_giftbook_service.statistics_service,
            "insert_site_statistics_log",
            new=AsyncMock(),
        ):
            response = await user_giftbook_service.post_user_giftbook(
                req_body=body,
                kc_user_id="",
                db=db,
                user_id=42,
            )

        self.assertEqual(response["result"].user_id, 42)
        self.assertEqual(len(db.rolled_back_savepoints), 1)
        self.assertTrue(
            any(
                "INSERT INTO tb_user_productbook" in query
                for query in db.rolled_back_savepoints[0]
            )
        )
        self.assertFalse(
            any("tb_user_productbook" in query for query in db.writes)
        )
        self.assertTrue(
            any("tb_user_giftbook" in query for query in db.writes)
        )


class UserGiftbookReceiveTest(unittest.IsolatedAsyncioTestCase):
    async def test_receive_locks_and_conditionally_updates_once_for_full_amount(self):
        giftbook = {
            "user_id": 42,
            "product_id": 10,
            "episode_id": None,
            "ticket_type": "comped",
            "own_type": "rental",
            "amount": 2,
            "received_yn": "N",
            "created_date": datetime.now(),
            "expiration_date": datetime.now() + timedelta(days=1),
            "promotion_type": None,
            "acquisition_type": "event",
            "acquisition_id": 9,
            "ticket_expiration_type": "days",
            "ticket_expiration_value": 7,
        }
        db = _QueueDb(
            [
                _Result([giftbook]),
                _Result([{"profile_id": 5}]),
                _Result(),
                _Result(),
                _Result(rowcount=1),
                _Result(),
            ]
        )

        with (
            patch.object(
                user_giftbook_service.comm_service,
                "get_user_from_kc",
                new=AsyncMock(return_value=42),
            ),
            patch.object(
                user_giftbook_service.statistics_service,
                "insert_site_statistics_log",
                new=AsyncMock(),
            ),
        ):
            response = await user_giftbook_service.receive_user_giftbook(
                giftbook_id=7, kc_user_id="kc-owner", db=db
            )

        self.assertTrue(response["result"])
        self.assertIn("FOR UPDATE", db.calls[0][0].upper())
        productbook_inserts = [
            query
            for query, _ in db.calls
            if "INSERT INTO tb_user_productbook" in query
        ]
        self.assertEqual(len(productbook_inserts), 2)
        self.assertEqual(len(db.committed_savepoints), 1)
        self.assertEqual(db.rolled_back_savepoints, [])
        update_query = next(
            query
            for query, _ in db.calls
            if "UPDATE tb_user_giftbook" in query
        )
        self.assertIn("received_yn = 'N'", update_query)

    async def test_receive_rejects_lost_conditional_update(self):
        giftbook = {
            "user_id": 42,
            "product_id": 10,
            "episode_id": None,
            "ticket_type": "comped",
            "own_type": "rental",
            "amount": 1,
            "received_yn": "N",
            "created_date": datetime.now(),
            "expiration_date": datetime.now() + timedelta(days=1),
            "promotion_type": None,
            "acquisition_type": "event",
            "acquisition_id": 9,
            "ticket_expiration_type": None,
            "ticket_expiration_value": None,
        }
        db = _QueueDb(
            [
                _Result([giftbook]),
                _Result([{"profile_id": 5}]),
                _Result(),
                _Result(rowcount=0),
            ]
        )

        with (
            patch.object(
                user_giftbook_service.comm_service,
                "get_user_from_kc",
                new=AsyncMock(return_value=42),
            ),
            patch.object(
                user_giftbook_service.statistics_service,
                "insert_site_statistics_log",
                new=AsyncMock(),
            ),
        ):
            with self.assertRaises(CustomResponseException) as captured:
                await user_giftbook_service.receive_user_giftbook(
                    giftbook_id=7, kc_user_id="kc-owner", db=db
                )

        self.assertEqual(captured.exception.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(db.rolled_back_savepoints), 1)
        self.assertEqual(db.writes, [])

    async def test_receive_rejects_amount_below_one_before_grant_writes(self):
        giftbook = {
            "user_id": 42,
            "product_id": 10,
            "episode_id": None,
            "ticket_type": "comped",
            "own_type": "rental",
            "amount": 0,
            "received_yn": "N",
            "created_date": datetime.now(),
            "expiration_date": datetime.now() + timedelta(days=1),
            "promotion_type": None,
            "acquisition_type": "event",
            "acquisition_id": 9,
            "ticket_expiration_type": None,
            "ticket_expiration_value": None,
        }
        db = _QueueDb([_Result([giftbook])])

        with patch.object(
            user_giftbook_service.comm_service,
            "get_user_from_kc",
            new=AsyncMock(return_value=42),
        ):
            with self.assertRaises(CustomResponseException) as captured:
                await user_giftbook_service.receive_user_giftbook(
                    giftbook_id=7, kc_user_id="kc-owner", db=db
                )

        self.assertEqual(captured.exception.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(db.calls), 1)
        self.assertEqual(db.writes, [])

    async def test_receive_insert_failure_rolls_back_savepoint(self):
        giftbook = {
            "user_id": 42,
            "product_id": 10,
            "episode_id": None,
            "ticket_type": "comped",
            "own_type": "rental",
            "amount": 2,
            "received_yn": "N",
            "created_date": datetime.now(),
            "expiration_date": datetime.now() + timedelta(days=1),
            "promotion_type": None,
            "acquisition_type": "event",
            "acquisition_id": 9,
            "ticket_expiration_type": None,
            "ticket_expiration_value": None,
        }
        db = _QueueDb(
            [
                _Result([giftbook]),
                _Result([{"profile_id": 5}]),
                _Result(),
                RuntimeError("second insert failed"),
            ]
        )

        with (
            patch.object(
                user_giftbook_service.comm_service,
                "get_user_from_kc",
                new=AsyncMock(return_value=42),
            ),
            patch.object(
                user_giftbook_service.statistics_service,
                "insert_site_statistics_log",
                new=AsyncMock(),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "second insert failed"):
                await user_giftbook_service.receive_user_giftbook(
                    giftbook_id=7, kc_user_id="kc-owner", db=db
                )

        self.assertEqual(len(db.rolled_back_savepoints), 1)
        self.assertEqual(db.writes, [])

    async def test_receive_history_failure_rolls_back_grant_and_update(self):
        giftbook = {
            "user_id": 42,
            "product_id": 10,
            "episode_id": None,
            "ticket_type": "comped",
            "own_type": "rental",
            "amount": 1,
            "received_yn": "N",
            "created_date": datetime.now(),
            "expiration_date": datetime.now() + timedelta(days=1),
            "promotion_type": None,
            "acquisition_type": "event",
            "acquisition_id": 9,
            "ticket_expiration_type": None,
            "ticket_expiration_value": None,
        }
        db = _QueueDb(
            [
                _Result([giftbook]),
                _Result([{"profile_id": 5}]),
                _Result(),
                _Result(rowcount=1),
                RuntimeError("history insert failed"),
            ]
        )

        with (
            patch.object(
                user_giftbook_service.comm_service,
                "get_user_from_kc",
                new=AsyncMock(return_value=42),
            ),
            patch.object(
                user_giftbook_service.statistics_service,
                "insert_site_statistics_log",
                new=AsyncMock(),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "history insert failed"):
                await user_giftbook_service.receive_user_giftbook(
                    giftbook_id=7, kc_user_id="kc-owner", db=db
                )

        self.assertEqual(len(db.rolled_back_savepoints), 1)
        rolled_back = db.rolled_back_savepoints[0]
        self.assertTrue(any("tb_user_productbook" in query for query in rolled_back))
        self.assertTrue(any("UPDATE tb_user_giftbook" in query for query in rolled_back))
        self.assertEqual(db.writes, [])


if __name__ == "__main__":
    unittest.main()
