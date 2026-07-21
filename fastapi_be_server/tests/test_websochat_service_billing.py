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


class _Mappings:
    def __init__(self, row):
        self._row = row

    def one(self):
        return self._row


class _Result:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return _Mappings(self._row)


class _ScopedCountDb:
    def __init__(self):
        self.params = []
        self.statements = []

    async def execute(self, statement, params=None):
        self.params.append(params)
        self.statements.append(str(statement))
        count = 8 if params["is_character_chat"] == 1 else 2
        return _Result({"cnt": count})


class WebsochatBillingTests(unittest.IsolatedAsyncioTestCase):
    def test_character_chat_has_separate_daily_free_limit(self):
        regular = websochat_service._build_websochat_billing_status_payload(
            used_count=3,
            user_id=None,
            cash_balance=None,
            is_character_chat=False,
        )
        character_chat = websochat_service._build_websochat_billing_status_payload(
            used_count=3,
            user_id=None,
            cash_balance=None,
            is_character_chat=True,
        )

        self.assertEqual(regular["dailyFreeMessageLimit"], 3)
        self.assertEqual(regular["freeRemainingMessages"], 0)
        self.assertEqual(character_chat["dailyFreeMessageLimit"], 10)
        self.assertEqual(character_chat["freeRemainingMessages"], 7)

    async def test_daily_message_count_uses_separate_session_pools(self):
        db = _ScopedCountDb()

        character_count = await websochat_service._get_websochat_daily_user_message_count(
            user_id=None,
            guest_key="guest-1",
            db=db,
            is_character_chat=True,
        )
        regular_count = await websochat_service._get_websochat_daily_user_message_count(
            user_id=None,
            guest_key="guest-1",
            db=db,
            is_character_chat=False,
        )

        self.assertEqual(character_count, 8)
        self.assertEqual(regular_count, 2)
        self.assertEqual(db.params[0]["is_character_chat"], 1)
        self.assertEqual(db.params[1]["is_character_chat"], 0)
        self.assertIn("tb_story_agent_usage_log", db.statements[0])
        self.assertIn("l.model_used", db.statements[0])
        self.assertNotIn("m.role = 'user'", db.statements[0])

    async def test_billing_status_resolves_character_chat_from_owned_session(self):
        db = AsyncMock()
        with (
            patch.object(
                websochat_service,
                "_resolve_actor",
                new_callable=AsyncMock,
                return_value=(None, "guest-1"),
            ),
            patch.object(
                websochat_service,
                "_get_session_row",
                new_callable=AsyncMock,
                return_value={
                    "session_memory_json": '{"session_kind":"character_chat"}',
                },
            ),
            patch.object(
                websochat_service,
                "_get_websochat_character_chat_daily_counts_by_model",
                new_callable=AsyncMock,
                return_value={"speed": 4, "balance": 0, "deep": 0},
            ) as get_used_counts,
        ):
            result = await websochat_service.get_billing_status(
                kc_user_id=None,
                guest_key="guest-1",
                qa_action_key=None,
                session_id=77,
                db=db,
            )

        self.assertEqual(result["data"]["dailyFreeMessageLimit"], 10)
        self.assertEqual(result["data"]["freeRemainingMessages"], 6)
        get_used_counts.assert_awaited_once()

    async def test_character_chat_fourth_message_stays_free_but_regular_chat_requires_login(self):
        db = AsyncMock()
        with patch.object(
            websochat_service,
            "_get_websochat_daily_user_message_count",
            new_callable=AsyncMock,
            return_value=3,
        ) as get_used_count:
            character_charge_required = (
                await websochat_service._resolve_websochat_message_charge_required(
                    user_id=None,
                    guest_key="guest-1",
                    db=db,
                    is_character_chat=True,
                )
            )
            with self.assertRaises(CustomResponseException) as regular_exc:
                await websochat_service._resolve_websochat_message_charge_required(
                    user_id=None,
                    guest_key="guest-1",
                    db=db,
                    is_character_chat=False,
                )

        self.assertFalse(character_charge_required)
        self.assertEqual(regular_exc.exception.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            get_used_count.await_args_list[0].kwargs["is_character_chat"],
            True,
        )
        self.assertEqual(
            get_used_count.await_args_list[1].kwargs["is_character_chat"],
            False,
        )

    async def test_character_chat_charges_only_after_tenth_free_message(self):
        db = AsyncMock()
        with (
            patch.object(
                websochat_service,
                "_get_websochat_daily_user_message_count",
                new_callable=AsyncMock,
                side_effect=[9, 10],
            ),
            patch.object(
                websochat_service,
                "_get_user_cash_balance_for_websochat",
                new_callable=AsyncMock,
                return_value=100,
            ),
        ):
            tenth_message_charge_required = (
                await websochat_service._resolve_websochat_message_charge_required(
                    user_id=321,
                    guest_key=None,
                    db=db,
                    is_character_chat=True,
                )
            )
            eleventh_message_charge_required = (
                await websochat_service._resolve_websochat_message_charge_required(
                    user_id=321,
                    guest_key=None,
                    db=db,
                    is_character_chat=True,
                )
            )

        self.assertFalse(tenth_message_charge_required)
        self.assertTrue(eleventh_message_charge_required)

    async def test_deep_character_chat_charges_after_its_one_free_message(self):
        db = AsyncMock()
        with (
            patch.object(
                websochat_service,
                "_get_websochat_daily_user_message_count",
                new_callable=AsyncMock,
                side_effect=[0, 1],
            ) as get_used_count,
            patch.object(
                websochat_service,
                "_get_user_cash_balance_for_websochat",
                new_callable=AsyncMock,
                return_value=100,
            ),
        ):
            first_message_charge_required = (
                await websochat_service._resolve_websochat_message_charge_required(
                    user_id=321,
                    guest_key=None,
                    db=db,
                    is_character_chat=True,
                    model_key="deep",
                )
            )
            second_message_charge_required = (
                await websochat_service._resolve_websochat_message_charge_required(
                    user_id=321,
                    guest_key=None,
                    db=db,
                    is_character_chat=True,
                    model_key="deep",
                )
            )

        self.assertFalse(first_message_charge_required)
        self.assertTrue(second_message_charge_required)
        self.assertEqual(
            [call.kwargs["model_key"] for call in get_used_count.await_args_list],
            ["deep", "deep"],
        )

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
