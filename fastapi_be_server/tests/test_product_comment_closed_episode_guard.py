from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from fastapi import status

from app.const import ErrorMessages
from app.exceptions import CustomResponseException
from app.schemas import product as product_schema
from app.services.product import product_comment_service


class _Mappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows=None, scalar=None, rowcount=None):
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

    def mappings(self):
        return _Mappings(self._rows)

    def scalar(self):
        return self._scalar


class _QueueDb:
    """Returns queued results in order and records every executed statement."""

    def __init__(self, results):
        self._results = list(results)
        self.statements: list[str] = []

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))
        if not self._results:
            return _Result()
        return self._results.pop(0)

    @asynccontextmanager
    async def begin(self):
        yield


def _episode_row(comment_open_yn: str):
    return {"product_id": 787, "comment_open_yn": comment_open_yn}


def _user_row():
    return {"user_id": 42, "profile_id": 7}


class ProductCommentClosedEpisodeGuardTest(unittest.IsolatedAsyncioTestCase):
    async def test_closed_episode_rejects_comment_and_skips_insert(self):
        db = _QueueDb([_Result(rows=[_episode_row("N")])])

        with patch.object(
            product_comment_service.comm_service,
            "get_user_from_kc",
            AsyncMock(return_value=42),
        ):
            with self.assertRaises(CustomResponseException) as caught:
                await product_comment_service.post_products_comments_episodes_episode_id(
                    episode_id="8478",
                    req_body=product_schema.PostProductsCommentsEpisodesEpisodeIdReqBody(
                        content="댓글 비허용 회차 우회 시도"
                    ),
                    kc_user_id="kc-user",
                    db=db,
                )

        self.assertEqual(caught.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            caught.exception.message, ErrorMessages.FORBIDDEN_CLOSED_EPISODE_COMMENT
        )
        self.assertTrue(
            all(
                "insert into tb_product_comment" not in statement
                for statement in db.statements
            ),
            "a closed episode must never reach the comment insert",
        )

    async def test_missing_episode_rejects_comment(self):
        db = _QueueDb([_Result(rows=[])])

        with patch.object(
            product_comment_service.comm_service,
            "get_user_from_kc",
            AsyncMock(return_value=42),
        ):
            with self.assertRaises(CustomResponseException) as caught:
                await product_comment_service.post_products_comments_episodes_episode_id(
                    episode_id="999999",
                    req_body=product_schema.PostProductsCommentsEpisodesEpisodeIdReqBody(
                        content="없는 회차"
                    ),
                    kc_user_id="kc-user",
                    db=db,
                )

        self.assertEqual(caught.exception.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            caught.exception.message, ErrorMessages.INVALID_EPISODE_INFO
        )

    async def test_open_episode_still_inserts_comment(self):
        db = _QueueDb(
            [
                _Result(rows=[_episode_row("Y")]),
                _Result(rows=[_user_row()]),
                _Result(rowcount=1),
                _Result(scalar=5150),
                _Result(),
                _Result(rows=[{"product_id": 787}]),
                _Result(rows=[{"count_comment": 16}]),
                _Result(rows=[]),
            ]
        )

        with (
            patch.object(
                product_comment_service.comm_service,
                "get_user_from_kc",
                AsyncMock(return_value=42),
            ),
            patch.object(
                product_comment_service.event_reward_service,
                "check_and_grant_event_reward",
                AsyncMock(return_value=None),
            ),
        ):
            result = await product_comment_service.post_products_comments_episodes_episode_id(
                episode_id="8478",
                req_body=product_schema.PostProductsCommentsEpisodesEpisodeIdReqBody(
                    content="잘 보고 갑니다"
                ),
                kc_user_id="kc-user",
                db=db,
            )

        self.assertEqual(result["data"]["commentId"], 5150)
        self.assertEqual(result["data"]["commentCount"], 16)
        self.assertTrue(
            any(
                "insert into tb_product_comment" in statement
                for statement in db.statements
            ),
            "an open episode must still insert the comment",
        )

    async def test_episode_closed_between_guard_and_insert_rejects_comment(self):
        db = _QueueDb(
            [
                _Result(rows=[_episode_row("Y")]),
                _Result(rows=[_user_row()]),
                _Result(rowcount=0),
            ]
        )

        with patch.object(
            product_comment_service.comm_service,
            "get_user_from_kc",
            AsyncMock(return_value=42),
        ):
            with self.assertRaises(CustomResponseException) as caught:
                await product_comment_service.post_products_comments_episodes_episode_id(
                    episode_id="8478",
                    req_body=product_schema.PostProductsCommentsEpisodesEpisodeIdReqBody(
                        content="등록 직전 비허용 전환"
                    ),
                    kc_user_id="kc-user",
                    db=db,
                )

        self.assertEqual(caught.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            caught.exception.message, ErrorMessages.FORBIDDEN_CLOSED_EPISODE_COMMENT
        )
        insert_statement = next(
            statement
            for statement in db.statements
            if "insert into tb_product_comment" in statement
        )
        self.assertIn("comment_open_yn = 'Y'", insert_statement)
        self.assertTrue(
            all("last_insert_id" not in statement for statement in db.statements),
            "a rejected conditional insert must stop before comment side effects",
        )


if __name__ == "__main__":
    unittest.main()
