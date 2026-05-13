import unittest
from unittest.mock import AsyncMock, patch

from fastapi import status

from app.const import ErrorMessages
from app.exceptions import CustomResponseException
from app.services.websochat import websochat_service


class _RecordingDb:
    def __init__(self):
        self.execute_count = 0

    async def execute(self, *args, **kwargs):
        self.execute_count += 1


class WebsochatBillingTests(unittest.IsolatedAsyncioTestCase):
    async def test_charge_websochat_cash_rechecks_balance_before_insert(self):
        db = _RecordingDb()

        with patch.object(
            websochat_service,
            "_get_user_cash_balance_for_websochat",
            new_callable=AsyncMock,
        ) as get_balance:
            get_balance.return_value = 10

            with self.assertRaises(CustomResponseException) as exc:
                await websochat_service._charge_websochat_cash(
                    user_id=321,
                    session_id=123,
                    product_id=987,
                    db=db,
                    cash_cost=30,
                )

        self.assertEqual(exc.exception.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(exc.exception.message, ErrorMessages.INSUFFICIENT_CASH_BALANCE)
        self.assertEqual(db.execute_count, 0)


if __name__ == "__main__":
    unittest.main()
