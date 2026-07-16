from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from app.schemas.support import PostSupportQnaReqBody
from app.services.content import support_service


class FakeDb:
    def __init__(self, qna_id: int = 37):
        self.execute = AsyncMock(return_value=SimpleNamespace(lastrowid=qna_id))

    @asynccontextmanager
    async def begin(self):
        yield


class SupportQnaServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_post_support_qna_persists_and_notifies(self):
        db = FakeDb()
        send_email = AsyncMock()

        with (
            patch.object(
                support_service.comm_service,
                "get_user_from_kc",
                AsyncMock(return_value=91),
            ),
            patch.object(support_service, "send_email", send_email),
        ):
            result = await support_service.post_support_qnas(
                req_body=PostSupportQnaReqBody(
                    category="서비스문의",
                    subject="작품 관리 문의",
                    content="공지 수정 위치를 찾기 어렵습니다.",
                    email="author@example.com",
                ),
                kc_user_id="kc-user",
                db=db,
            )

        self.assertEqual(result, {"data": {"qnaId": 37}})
        params = db.execute.await_args.args[1]
        self.assertEqual(
            params,
            {
                "category": "서비스문의",
                "subject": "작품 관리 문의",
                "content": "공지 수정 위치를 찾기 어렵습니다.",
                "email": "author@example.com",
                "user_id": 91,
            },
        )
        send_email.assert_awaited_once()

    def test_post_support_qna_rejects_invalid_email(self):
        with self.assertRaises(ValidationError):
            PostSupportQnaReqBody(
                category="서비스문의",
                subject="문의",
                content="내용",
                email="invalid-email",
            )

    def test_post_support_qna_rejects_unknown_category(self):
        with self.assertRaises(ValidationError):
            PostSupportQnaReqBody(
                category="알수없는문의",
                subject="문의",
                content="내용",
                email="author@example.com",
            )


if __name__ == "__main__":
    unittest.main()
