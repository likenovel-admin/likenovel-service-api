from contextlib import asynccontextmanager
import unittest
from unittest.mock import MagicMock, patch

from app.const import ErrorMessages
from app.exceptions import CustomResponseException
from app.schemas.admin import PostCancelCashChargeOrderReqBody
from app.services.admin import admin_basic_service


def cancel_response(cancellation_type, total_amount=10_000):
    cancellation = MagicMock(spec=cancellation_type)
    cancellation.total_amount = total_amount
    return MagicMock(cancellation=cancellation)


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row

    def all(self):
        return [self.row] if self.row else []


class FakeDb:
    def __init__(self, *, balance=10_000, refund_exists=False):
        self.balance = balance
        self.refund_exists = refund_exists
        self.begin_calls = 0
        self.begin_nested_calls = 0
        self.executed = []

    @asynccontextmanager
    async def begin(self):
        self.begin_calls += 1
        yield

    @asynccontextmanager
    async def begin_nested(self):
        self.begin_nested_calls += 1
        yield

    async def execute(self, statement, params=None):
        query = str(statement)
        params = params or {}
        self.executed.append((query, params))

        if "from tb_user" in query and "kc_user_id" in query:
            return FakeResult({"user_id": 900})
        if "FROM tb_store_order so" in query:
            return FakeResult(
                {
                    "order_id": 101,
                    "order_no": "OC-101",
                    "user_id": 202,
                    "cancel_yn": "N",
                    "total_price": 10_000,
                    "order_item_id": 303,
                    "payment_info_id": 404,
                    "pg_payment_id": "payment-101",
                }
            )
        if "FROM tb_store_refund" in query:
            return FakeResult({"id": 505} if self.refund_exists else None)
        if "FROM tb_user_cashbook_transaction t" in query:
            return FakeResult()
        if "SELECT COALESCE(SUM(balance), 0) AS balance" in query:
            return FakeResult({"balance": self.balance})
        return FakeResult()

    def params_for(self, query_fragment):
        return next(params for query, params in self.executed if query_fragment in query)


class AdminCashChargeCancelServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_refunds_and_reverses_exact_payment_amount(self):
        db = FakeDb(balance=10_000)
        cancel_payment = MagicMock(
            return_value=cancel_response(
                admin_basic_service.portone.payment.SucceededPaymentCancellation
            )
        )

        with (
            patch.object(
                admin_basic_service.portone_client.payment,
                "cancel_payment",
                cancel_payment,
            ),
        ):
            result = await admin_basic_service.post_cancel_cash_charge_order(
                order_id=101,
                req_body=PostCancelCashChargeOrderReqBody(reason="unused charge"),
                kc_user_id="kc-admin",
                db=db,
            )

        cancel_payment.assert_called_once_with(
            payment_id="payment-101",
            amount=10_000,
            current_cancellable_amount=10_000,
            reason="unused charge",
        )
        self.assertEqual(
            db.params_for("INSERT INTO tb_store_refund")["refund_price"],
            10_000,
        )
        self.assertEqual(
            db.params_for("INSERT INTO tb_user_cashbook (")["balance"],
            -10_000,
        )
        self.assertEqual(
            db.params_for("INSERT INTO tb_user_cashbook_transaction")["amount"],
            10_000,
        )
        self.assertEqual(result["data"]["refund_price"], 10_000)
        self.assertEqual(result["data"]["reversed_cash_amount"], 10_000)

    async def test_cancel_uses_request_scoped_session_transaction(self):
        db = FakeDb(balance=11_000)

        with (
            patch.object(
                admin_basic_service.portone_client.payment,
                "cancel_payment",
                MagicMock(
                    return_value=cancel_response(
                        admin_basic_service.portone.payment.SucceededPaymentCancellation
                    )
                ),
            ),
        ):
            await admin_basic_service.post_cancel_cash_charge_order(
                order_id=101,
                req_body=PostCancelCashChargeOrderReqBody(),
                kc_user_id="kc-admin",
                db=db,
            )

        self.assertEqual(db.begin_calls, 0)
        self.assertEqual(db.begin_nested_calls, 1)

    async def test_cancel_requires_succeeded_gateway_response_for_exact_amount(self):
        cases = (
            (admin_basic_service.portone.payment.RequestedPaymentCancellation, 10_000),
            (admin_basic_service.portone.payment.SucceededPaymentCancellation, 9_999),
        )

        for cancellation_type, total_amount in cases:
            with self.subTest(
                cancellation_type=cancellation_type.__name__,
                total_amount=total_amount,
            ):
                db = FakeDb(balance=10_000)
                with patch.object(
                    admin_basic_service.portone_client.payment,
                    "cancel_payment",
                    MagicMock(
                        return_value=cancel_response(cancellation_type, total_amount)
                    ),
                ):
                    with self.assertRaises(CustomResponseException) as raised:
                        await admin_basic_service.post_cancel_cash_charge_order(
                            order_id=101,
                            req_body=PostCancelCashChargeOrderReqBody(),
                            kc_user_id="kc-admin",
                            db=db,
                        )

                self.assertEqual(raised.exception.status_code, 500)
                self.assertEqual(
                    raised.exception.message,
                    ErrorMessages.PAYMENT_SERVICE_ERROR,
                )
                self.assertFalse(
                    any(
                        query.lstrip().startswith(("INSERT", "UPDATE", "DELETE"))
                        for query, _ in db.executed
                    )
                )

    async def test_cancel_does_not_call_gateway_when_balance_is_insufficient(self):
        db = FakeDb(balance=9_999)
        cancel_payment = MagicMock()

        with (
            patch.object(
                admin_basic_service.portone_client.payment,
                "cancel_payment",
                cancel_payment,
            ),
        ):
            with self.assertRaises(CustomResponseException) as raised:
                await admin_basic_service.post_cancel_cash_charge_order(
                    order_id=101,
                    req_body=PostCancelCashChargeOrderReqBody(),
                    kc_user_id="kc-admin",
                    db=db,
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(
            raised.exception.message,
            ErrorMessages.INSUFFICIENT_CASH_BALANCE,
        )
        cancel_payment.assert_not_called()


if __name__ == "__main__":
    unittest.main()
