from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pymysql
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.const import settings
from app.exceptions import CustomResponseException
from app.routers.partner import partner_command
from app.schemas.partner import PostSponsorshipSettlementRequestReqBody
from app.services.partner import partner_income_service

ROOT = Path(__file__).resolve().parents[1]


class _Result:
    def __init__(self, rows=None, lastrowid=None):
        self._rows = rows or []
        self.lastrowid = lastrowid

    def mappings(self):
        return SimpleNamespace(all=lambda: self._rows, first=lambda: self._rows[0] if self._rows else None)


class FakeDb:
    def __init__(self, product_rows, *, duplicate=False):
        self.product_rows = product_rows
        self.duplicate = duplicate
        self.events = []

    def sql_calls(self, keyword):
        return [(sql, params) for kind, sql, params in self.events if kind == "execute" and keyword in sql.lower()]

    async def execute(self, query, params=None):
        sql = str(query)
        self.events.append(("execute", sql, params))
        lowered = sql.lower()
        if "insert into tb_ptn_sponsorship_settlement_request" in lowered:
            if self.duplicate:
                raise IntegrityError(sql, params, pymysql.err.IntegrityError(1062, "Duplicate entry"))
            return _Result(lastrowid=41)
        if "delete from tb_ptn_sponsorship_settlement_request" in lowered:
            return _Result()
        if "from tb_user u" in lowered:
            return _Result([{"email": "author@example.com"}])
        return _Result(self.product_rows)

    async def commit(self):
        self.events.append(("commit", None, None))

    async def rollback(self):
        self.events.append(("rollback", None, None))


def _body(**overrides):
    values = {
        "account_holder": "홍길동",
        "bank_name": "국민은행",
        "account_number": "123-456-7890",
        "resident_registration_number": "900101-1234567",
    }
    values.update(overrides)
    return PostSponsorshipSettlementRequestReqBody(**values)


PRODUCT_ROWS = [
    {
        "product_id": 1234,
        "title": "무언마존<無言魔尊>",
        "author_name": "반고",
        "donation_count": 3,
        "total_donation": 60000,
        "confirmed_gross": 60000,
        "confirmed_final": 52218,
    }
]
AUTHOR = {"user_id": 2269, "role": "author"}


class SponsorshipSettlementRequestTest(unittest.IsolatedAsyncioTestCase):
    def test_router_registers_post_route(self):
        route = next(
            route
            for route in partner_command.router.routes
            if getattr(route, "path", None) == "/partners/sponsorship-settlement-requests"
        )
        self.assertIn("POST", route.methods)

    async def test_reserves_month_then_sends_escaped_mail_to_support_address(self):
        db = FakeDb(PRODUCT_ROWS)
        send_email = AsyncMock(side_effect=lambda *args: db.events.append(("send", None, None)))

        with patch.object(partner_income_service, "send_email", send_email):
            result = await partner_income_service.request_sponsorship_settlement(
                _body(account_holder="홍<길동>"), db, AUTHOR
            )

        send_email.assert_awaited_once()
        to_email, subject, html_body = send_email.await_args.args
        self.assertEqual(to_email, settings.SUPPORT_EMAIL)
        self.assertIn("후원금 정산신청", subject)
        self.assertIn("반고", subject)
        self.assertNotIn("1234567", subject)
        self.assertIn("홍&lt;길동&gt;", html_body)
        self.assertNotIn("홍<길동>", html_body)
        self.assertIn("123-456-7890", html_body)
        self.assertIn("900101-1234567", html_body)
        self.assertIn("무언마존&lt;無言魔尊&gt;", html_body)
        self.assertIn("52,218", html_body)

        (insert_sql, insert_params), = db.sql_calls("insert into tb_ptn_sponsorship_settlement_request")
        self.assertEqual(insert_params["user_id"], 2269)
        self.assertRegex(insert_params["request_month"], r"^\d{4}-\d{2}$")
        self.assertEqual(insert_params["total_donation"], 60000)
        self.assertEqual(insert_params["confirmed_final"], 52218)
        stored = " ".join(str(value) for value in insert_params.values())
        self.assertNotIn("1234567", stored)
        self.assertNotIn("123-456-7890", stored)

        kinds = [kind for kind, _, _ in db.events]
        self.assertLess(kinds.index("commit"), kinds.index("send"))
        self.assertEqual(db.sql_calls("delete from tb_ptn_sponsorship_settlement_request"), [])
        self.assertEqual(result["data"]["requested"], True)
        self.assertEqual(result["data"]["confirmed_final"], 52218)

    async def test_rejects_second_request_in_same_month(self):
        db = FakeDb(PRODUCT_ROWS, duplicate=True)
        send_email = AsyncMock()

        with patch.object(partner_income_service, "send_email", send_email):
            with self.assertRaises(CustomResponseException) as ctx:
                await partner_income_service.request_sponsorship_settlement(_body(), db, AUTHOR)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("rollback", [kind for kind, _, _ in db.events])
        send_email.assert_not_awaited()

    async def test_mail_failure_releases_monthly_slot(self):
        db = FakeDb(PRODUCT_ROWS)
        send_email = AsyncMock(side_effect=OSError("smtp down"))

        with patch.object(partner_income_service, "send_email", send_email):
            with self.assertRaises(CustomResponseException) as ctx:
                await partner_income_service.request_sponsorship_settlement(_body(), db, AUTHOR)

        self.assertEqual(ctx.exception.status_code, 502)
        (delete_sql, delete_params), = db.sql_calls("delete from tb_ptn_sponsorship_settlement_request")
        self.assertEqual(delete_params, {"id": 41})
        self.assertEqual([kind for kind, _, _ in db.events][-1], "commit")

    async def test_rejects_request_without_sponsorship(self):
        db = FakeDb([])
        send_email = AsyncMock()

        with patch.object(partner_income_service, "send_email", send_email):
            with self.assertRaises(CustomResponseException) as ctx:
                await partner_income_service.request_sponsorship_settlement(_body(), db, AUTHOR)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(db.sql_calls("insert into"), [])
        send_email.assert_not_awaited()

    async def test_rejects_non_author_accounts_including_cp(self):
        for role in ("CP", "admin"):
            db = FakeDb(PRODUCT_ROWS)
            send_email = AsyncMock()

            with patch.object(partner_income_service, "send_email", send_email):
                with self.assertRaises(CustomResponseException) as ctx:
                    await partner_income_service.request_sponsorship_settlement(
                        _body(), db, {"user_id": 77, "role": role}
                    )

            self.assertEqual(ctx.exception.status_code, 403, role)
            self.assertEqual(db.events, [], role)
            send_email.assert_not_awaited()

    def test_schema_normalizes_and_validates_fields(self):
        body = _body(
            account_holder="  홍길동 ",
            account_number=" 110-123-456789 ",
            resident_registration_number=" 9001011234567 ",
        )
        self.assertEqual(body.account_holder, "홍길동")
        self.assertEqual(body.account_number, "110-123-456789")
        self.assertEqual(body.resident_registration_number, "900101-1234567")

        for bad in (
            {"account_number": "12a-456"},
            {"account_holder": "  "},
            {"bank_name": ""},
            {"resident_registration_number": "900101-123456"},
            {"resident_registration_number": "9001O1-1234567"},
        ):
            with self.assertRaises(ValidationError):
                _body(**bad)

    def test_request_history_table_has_monthly_unique_key_without_sensitive_columns(self):
        sql = (
            ROOT / "dist" / "init" / "116-create-ptn-sponsorship-settlement-request.sql"
        ).read_text(encoding="utf-8").lower()

        self.assertIn("create table if not exists tb_ptn_sponsorship_settlement_request", sql)
        self.assertRegex(sql, r"unique key \w+ \(user_id, request_month\)")
        for column in ("account", "resident", "bank"):
            self.assertNotIn(column, sql)


if __name__ == "__main__":
    unittest.main()
