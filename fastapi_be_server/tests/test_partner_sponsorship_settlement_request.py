from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from app.const import settings
from app.exceptions import CustomResponseException
from app.routers.partner import partner_command
from app.schemas.partner import PostSponsorshipSettlementRequestReqBody
from app.services.partner import partner_income_service


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return SimpleNamespace(all=lambda: self._rows, first=lambda: self._rows[0] if self._rows else None)


class FakeDb:
    def __init__(self, product_rows, email="author@example.com"):
        self.product_rows = product_rows
        self.email = email
        self.calls = []

    async def execute(self, query, params=None):
        sql = str(query)
        self.calls.append((sql, params))
        if "from tb_user u" in sql.lower():
            return _Result([{"email": self.email}])
        return _Result(self.product_rows)


def _body(**overrides):
    values = {"account_holder": "홍길동", "bank_name": "국민은행", "account_number": "123-456-7890"}
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


class SponsorshipSettlementRequestTest(unittest.IsolatedAsyncioTestCase):
    def test_router_registers_post_route(self):
        route = next(
            route
            for route in partner_command.router.routes
            if getattr(route, "path", None) == "/partners/sponsorship-settlement-requests"
        )
        self.assertIn("POST", route.methods)

    async def test_sends_escaped_request_mail_to_support_address(self):
        db = FakeDb(PRODUCT_ROWS)
        send_email = AsyncMock()

        with patch.object(partner_income_service, "send_email", send_email):
            result = await partner_income_service.request_sponsorship_settlement(
                _body(account_holder="홍<길동>"), db, {"user_id": 2269, "role": "author"}
            )

        send_email.assert_awaited_once()
        to_email, subject, html_body = send_email.await_args.args
        self.assertEqual(to_email, settings.SUPPORT_EMAIL)
        self.assertIn("후원금 정산신청", subject)
        self.assertIn("반고", subject)
        self.assertIn("홍&lt;길동&gt;", html_body)
        self.assertNotIn("홍<길동>", html_body)
        self.assertIn("국민은행", html_body)
        self.assertIn("123-456-7890", html_body)
        self.assertIn("무언마존&lt;無言魔尊&gt;", html_body)
        self.assertIn("author@example.com", html_body)
        self.assertIn("52,218", html_body)
        self.assertEqual(
            result,
            {"data": {"requested": True, "total_donation": 60000, "confirmed_final": 52218}},
        )
        product_sql, product_params = db.calls[-1]
        self.assertIn("p.author_id = :user_id", product_sql)
        self.assertEqual(product_params, {"user_id": 2269})

    async def test_rejects_request_without_sponsorship(self):
        db = FakeDb([])
        send_email = AsyncMock()

        with patch.object(partner_income_service, "send_email", send_email):
            with self.assertRaises(CustomResponseException) as ctx:
                await partner_income_service.request_sponsorship_settlement(
                    _body(), db, {"user_id": 2269, "role": "author"}
                )

        self.assertEqual(ctx.exception.status_code, 400)
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
            self.assertEqual(db.calls, [], role)
            send_email.assert_not_awaited()

    async def test_mail_failure_is_reported_to_requester(self):
        db = FakeDb(PRODUCT_ROWS)
        send_email = AsyncMock(side_effect=OSError("smtp down"))

        with patch.object(partner_income_service, "send_email", send_email):
            with self.assertRaises(CustomResponseException) as ctx:
                await partner_income_service.request_sponsorship_settlement(
                    _body(), db, {"user_id": 2269, "role": "author"}
                )

        self.assertEqual(ctx.exception.status_code, 502)

    def test_schema_strips_and_validates_account_fields(self):
        body = _body(account_holder="  홍길동 ", account_number=" 110-123-456789 ")
        self.assertEqual(body.account_holder, "홍길동")
        self.assertEqual(body.account_number, "110-123-456789")

        for bad in ({"account_number": "12a-456"}, {"account_holder": "  "}, {"bank_name": ""}):
            with self.assertRaises(ValidationError):
                _body(**bad)


if __name__ == "__main__":
    unittest.main()
