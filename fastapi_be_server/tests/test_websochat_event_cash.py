import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.const import ErrorMessages
from app.exceptions import CustomResponseException
from app.services.websochat import websochat_event_cash, websochat_service


class _Result:
    def __init__(self, *, rowcount=0, row=None):
        self.rowcount = rowcount
        self._row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row


class _ScriptedDb:
    """Records SQL and returns scripted results in order."""

    def __init__(self, results):
        self._results = list(results)
        self.statements = []
        self.params = []

    async def execute(self, statement, params=None):
        self.statements.append(" ".join(str(statement).split()))
        self.params.append(params or {})
        return self._results.pop(0)


class EventCashLedgerTests(unittest.IsolatedAsyncioTestCase):
    async def test_spend_uses_conditional_update_and_records_ledger(self):
        db = _ScriptedDb([_Result(rowcount=1), _Result(rowcount=1)])

        spent = await websochat_event_cash.try_spend_event_cash(
            user_id=7, amount=20, product_id=11, session_id=99, db=db
        )

        self.assertTrue(spent)
        self.assertIn("AND balance >= :amount", db.statements[0])
        self.assertEqual(db.params[0]["amount"], 20)
        self.assertIn("INSERT INTO tb_user_event_cash_transaction", db.statements[1])
        self.assertEqual(db.params[1]["amount"], -20)
        self.assertEqual(db.params[1]["session_id"], 99)

    async def test_spend_without_enough_balance_writes_nothing_more(self):
        db = _ScriptedDb([_Result(rowcount=0)])

        spent = await websochat_event_cash.try_spend_event_cash(
            user_id=7, amount=35, product_id=11, session_id=99, db=db
        )

        self.assertFalse(spent)
        self.assertEqual(len(db.statements), 1)

    async def test_new_grant_checks_key_then_writes_ledger_and_balance(self):
        db = _ScriptedDb([_Result(row=None), _Result(rowcount=1), _Result(rowcount=1)])

        granted = await websochat_event_cash.grant_event_cash(
            user_id=7, amount=300, grant_key="outage-1", memo="보상", db=db
        )

        self.assertTrue(granted)
        self.assertIn("FOR UPDATE", db.statements[0])
        self.assertTrue(db.statements[1].startswith("INSERT INTO tb_user_event_cash_transaction"))
        self.assertNotIn("IGNORE", db.statements[1])
        self.assertIn("balance = balance + :amount", db.statements[2])
        self.assertNotIn("VALUES(", db.statements[2])
        self.assertEqual(db.params[2]["amount"], 300)

    async def test_repeat_grant_with_same_key_does_not_add_balance(self):
        repeat = _ScriptedDb([_Result(row={"id": 1})])

        granted_again = await websochat_event_cash.grant_event_cash(
            user_id=7, amount=300, grant_key="outage-1", memo="보상", db=repeat
        )

        self.assertFalse(granted_again)
        self.assertEqual(len(repeat.statements), 1)

    async def test_grant_rejects_keys_and_memos_that_the_ledger_would_truncate(self):
        with self.assertRaises(ValueError):
            await websochat_event_cash.grant_event_cash(
                user_id=7, amount=300, grant_key="k" * 101, memo="", db=_ScriptedDb([])
            )
        with self.assertRaises(ValueError):
            await websochat_event_cash.grant_event_cash(
                user_id=7, amount=300, grant_key="k", memo="m" * 256, db=_ScriptedDb([])
            )

    async def test_grant_rejects_non_positive_amount(self):
        with self.assertRaises(ValueError):
            await websochat_event_cash.grant_event_cash(
                user_id=7, amount=0, grant_key="k", memo="", db=_ScriptedDb([])
            )


class EventCashChargeTests(unittest.IsolatedAsyncioTestCase):
    async def _charge_required(self, *, event_balance, cash_balance):
        with (
            patch.object(
                websochat_service,
                "_get_websochat_daily_user_message_count",
                new_callable=AsyncMock,
                return_value=10,
            ),
            patch.object(
                websochat_service,
                "get_user_event_cash_balance",
                new_callable=AsyncMock,
                return_value=event_balance,
            ),
            patch.object(
                websochat_service,
                "_get_user_cash_balance_for_websochat",
                new_callable=AsyncMock,
                return_value=cash_balance,
            ) as cash,
        ):
            required = await websochat_service._resolve_websochat_message_charge_required(
                user_id=321,
                guest_key=None,
                db=AsyncMock(),
                is_character_chat=True,
            )
        return required, cash

    async def test_event_cash_alone_can_pay_for_a_message(self):
        required, cash = await self._charge_required(event_balance=20, cash_balance=0)

        self.assertTrue(required)
        cash.assert_not_awaited()

    async def test_insufficient_event_and_paid_cash_is_rejected(self):
        with self.assertRaises(CustomResponseException) as raised:
            await self._charge_required(event_balance=19, cash_balance=0)

        self.assertEqual(raised.exception.message, ErrorMessages.INSUFFICIENT_CASH_BALANCE)

    async def _charge_message(self, *, event_paid):
        with (
            patch.object(
                websochat_service,
                "try_spend_event_cash",
                new_callable=AsyncMock,
                return_value=event_paid,
            ) as spend_event,
            patch.object(
                websochat_service,
                "_charge_websochat_cash",
                new_callable=AsyncMock,
            ) as charge_paid,
        ):
            paid = await websochat_service._charge_websochat_message_cost(
                user_id=321, session_id=9, product_id=11, cost=25, db=AsyncMock()
            )
        return paid, spend_event, charge_paid

    async def test_message_paid_by_event_cash_charges_no_paid_cash(self):
        paid, spend_event, charge_paid = await self._charge_message(event_paid=True)

        self.assertEqual(paid, 0)
        self.assertEqual(spend_event.await_args.kwargs["amount"], 25)
        charge_paid.assert_not_awaited()

    async def test_message_falls_back_to_paid_cash_when_event_cash_cannot_cover(self):
        paid, _, charge_paid = await self._charge_message(event_paid=False)

        self.assertEqual(paid, 25)
        self.assertEqual(charge_paid.await_args.kwargs["cash_cost"], 25)

    def test_billing_payload_exposes_event_cash_only_for_members(self):
        member = websochat_service._build_websochat_billing_status_payload(
            used_count=0, user_id=5, cash_balance=40, event_cash_balance=300
        )
        guest = websochat_service._build_websochat_billing_status_payload(
            used_count=0, user_id=None, cash_balance=None, event_cash_balance=None
        )

        self.assertEqual((member["cashBalance"], member["eventCashBalance"]), (40, 300))
        self.assertIsNone(guest["eventCashBalance"])


class GrantScriptSmokeTest(unittest.TestCase):
    def test_script_help_runs_from_backend_root(self):
        backend_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, "scripts/grant_event_cash.py", "--help"],
            cwd=backend_root,
            env={**os.environ, "PYTHONPATH": "."},
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[-500:])
        self.assertIn("--grant-key", completed.stdout)


if __name__ == "__main__":
    unittest.main()
