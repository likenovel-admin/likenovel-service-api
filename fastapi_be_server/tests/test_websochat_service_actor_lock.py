import unittest
from unittest.mock import AsyncMock, patch

from fastapi import status

from app.exceptions import CustomResponseException
from app.schemas.websochat import PostWebsochatMessageReqBody
from app.services.websochat import websochat_service


class _FakeDb:
    def __init__(self):
        self.next_lastrowid = 100
        self.committed = False
        self.rolled_back = False

    async def execute(self, *args, **kwargs):
        self.next_lastrowid += 1

        class _Result:
            lastrowid = self.next_lastrowid

        return _Result()

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class WebsochatActorLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_message_acquires_actor_lock_for_billing_window(self):
        req_body = PostWebsochatMessageReqBody(
            client_message_id="client-actor-lock-1",
            content="작품 대화 시작",
            starter_mode_key="qa",
        )
        db = _FakeDb()
        session_lock = object()

        with (
            patch.object(websochat_service, "_resolve_actor", new_callable=AsyncMock) as resolve_actor,
            patch.object(websochat_service, "_get_session_row", new_callable=AsyncMock) as get_session_row,
            patch.object(
                websochat_service,
                "_resolve_websochat_active_character_resolution",
                new_callable=AsyncMock,
            ) as resolve_character,
            patch.object(
                websochat_service,
                "_resolve_effective_adult_yn",
                new_callable=AsyncMock,
            ) as resolve_adult,
            patch.object(websochat_service, "_get_websochat_product", new_callable=AsyncMock) as get_product,
            patch.object(
                websochat_service,
                "_resolve_websochat_prompt_read_episode_to",
                new_callable=AsyncMock,
            ) as resolve_prompt_scope,
            patch.object(
                websochat_service,
                "_acquire_websochat_session_lock",
                new_callable=AsyncMock,
            ) as acquire_session_lock,
            patch.object(
                websochat_service,
                "_release_websochat_session_lock",
                new_callable=AsyncMock,
            ) as release_session_lock,
            patch.object(
                websochat_service,
                "_acquire_websochat_actor_lock",
                new_callable=AsyncMock,
            ) as acquire_actor_lock,
            patch.object(
                websochat_service,
                "_release_websochat_actor_lock",
                new_callable=AsyncMock,
            ) as release_actor_lock,
            patch.object(
                websochat_service,
                "_acquire_websochat_actor_lock_on_connection",
                new_callable=AsyncMock,
                create=True,
            ) as acquire_actor_lock_on_connection,
            patch.object(
                websochat_service,
                "_release_websochat_actor_lock_on_connection",
                new_callable=AsyncMock,
                create=True,
            ) as release_actor_lock_on_connection,
            patch.object(
                websochat_service,
                "_get_websochat_latest_visible_episode_no",
                new_callable=AsyncMock,
            ) as latest_visible_episode_no,
            patch.object(
                websochat_service,
                "_get_existing_turn_messages",
                new_callable=AsyncMock,
            ) as get_existing_turn_messages,
            patch.object(
                websochat_service,
                "_resolve_websochat_message_charge_required",
                new_callable=AsyncMock,
            ) as resolve_charge_required,
            patch.object(
                websochat_service,
                "emit_websochat_stream_text_if_needed",
                new_callable=AsyncMock,
            ),
        ):
            resolve_actor.return_value = (321, None)
            get_session_row.return_value = {
                "product_id": 987,
                "session_memory_json": None,
                "title": websochat_service.WEBSOCHAT_DEFAULT_TITLE,
            }
            resolve_character.return_value = {}
            resolve_adult.return_value = "Y"
            get_product.return_value = {
                "productId": 987,
                "title": "테스트 작품",
                "contextStatus": "ready",
                "latestEpisodeNo": 3,
                "syncedLatestEpisodeNo": 3,
            }
            resolve_prompt_scope.return_value = None
            acquire_session_lock.return_value = session_lock
            acquire_actor_lock_on_connection.return_value = True
            latest_visible_episode_no.return_value = 3
            get_existing_turn_messages.return_value = None
            resolve_charge_required.return_value = False

            result = await websochat_service.post_message(
                session_id=123,
                req_body=req_body,
                kc_user_id="kc-user-id",
                db=db,
            )

        self.assertEqual(result["data"]["sessionId"], 123)
        acquire_actor_lock.assert_not_awaited()
        release_actor_lock.assert_not_awaited()
        acquire_actor_lock_on_connection.assert_awaited_once_with(
            user_id=321,
            guest_key=None,
            conn=session_lock,
        )
        release_actor_lock_on_connection.assert_awaited_once_with(
            user_id=321,
            guest_key=None,
            conn=session_lock,
        )
        release_session_lock.assert_awaited_once_with(session_id=123, conn=session_lock)
        self.assertTrue(db.committed)
        self.assertFalse(db.rolled_back)

    async def test_post_message_rejects_when_actor_lock_is_busy(self):
        req_body = PostWebsochatMessageReqBody(
            client_message_id="client-actor-lock-2",
            content="작품 대화 시작",
            starter_mode_key="qa",
        )
        db = _FakeDb()
        session_lock = object()

        with (
            patch.object(websochat_service, "_resolve_actor", new_callable=AsyncMock) as resolve_actor,
            patch.object(websochat_service, "_get_session_row", new_callable=AsyncMock) as get_session_row,
            patch.object(
                websochat_service,
                "_resolve_websochat_active_character_resolution",
                new_callable=AsyncMock,
            ) as resolve_character,
            patch.object(
                websochat_service,
                "_resolve_effective_adult_yn",
                new_callable=AsyncMock,
            ) as resolve_adult,
            patch.object(websochat_service, "_get_websochat_product", new_callable=AsyncMock) as get_product,
            patch.object(
                websochat_service,
                "_resolve_websochat_prompt_read_episode_to",
                new_callable=AsyncMock,
            ) as resolve_prompt_scope,
            patch.object(
                websochat_service,
                "_acquire_websochat_session_lock",
                new_callable=AsyncMock,
            ) as acquire_session_lock,
            patch.object(
                websochat_service,
                "_release_websochat_session_lock",
                new_callable=AsyncMock,
            ) as release_session_lock,
            patch.object(
                websochat_service,
                "_acquire_websochat_actor_lock",
                new_callable=AsyncMock,
            ) as acquire_actor_lock,
            patch.object(
                websochat_service,
                "_release_websochat_actor_lock",
                new_callable=AsyncMock,
            ) as release_actor_lock,
            patch.object(
                websochat_service,
                "_acquire_websochat_actor_lock_on_connection",
                new_callable=AsyncMock,
                create=True,
            ) as acquire_actor_lock_on_connection,
            patch.object(
                websochat_service,
                "_release_websochat_actor_lock_on_connection",
                new_callable=AsyncMock,
                create=True,
            ) as release_actor_lock_on_connection,
            patch.object(
                websochat_service,
                "_get_websochat_latest_visible_episode_no",
                new_callable=AsyncMock,
            ) as latest_visible_episode_no,
            patch.object(
                websochat_service,
                "_get_existing_turn_messages",
                new_callable=AsyncMock,
            ) as get_existing_turn_messages,
            patch.object(
                websochat_service,
                "_resolve_websochat_message_charge_required",
                new_callable=AsyncMock,
            ) as resolve_charge_required,
        ):
            resolve_actor.return_value = (321, None)
            get_session_row.return_value = {
                "product_id": 987,
                "session_memory_json": None,
                "title": websochat_service.WEBSOCHAT_DEFAULT_TITLE,
            }
            resolve_character.return_value = {}
            resolve_adult.return_value = "Y"
            get_product.return_value = {
                "productId": 987,
                "title": "테스트 작품",
                "contextStatus": "ready",
                "latestEpisodeNo": 3,
                "syncedLatestEpisodeNo": 3,
            }
            resolve_prompt_scope.return_value = None
            acquire_session_lock.return_value = session_lock
            acquire_actor_lock_on_connection.return_value = False
            latest_visible_episode_no.return_value = 3
            get_existing_turn_messages.return_value = None

            with self.assertRaises(CustomResponseException) as exc:
                await websochat_service.post_message(
                    session_id=123,
                    req_body=req_body,
                    kc_user_id="kc-user-id",
                    db=db,
                )

        self.assertEqual(exc.exception.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("다른 메시지를 처리 중", exc.exception.message)
        resolve_charge_required.assert_not_awaited()
        acquire_actor_lock.assert_not_awaited()
        release_actor_lock.assert_not_awaited()
        acquire_actor_lock_on_connection.assert_awaited_once_with(
            user_id=321,
            guest_key=None,
            conn=session_lock,
        )
        release_actor_lock_on_connection.assert_not_awaited()
        release_session_lock.assert_awaited_once_with(session_id=123, conn=session_lock)
        self.assertFalse(db.committed)
        self.assertTrue(db.rolled_back)


if __name__ == "__main__":
    unittest.main()
