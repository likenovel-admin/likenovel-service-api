import json
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
        self.executions = []

    async def execute(self, *args, **kwargs):
        self.next_lastrowid += 1
        self.executions.append((args, kwargs))
        statement = str(args[0]) if args else ""
        if "FROM tb_product_episode pe" in statement and "authorizedYn" in statement:
            class _Mappings:
                def all(self):
                    return [
                        {"episodeNo": 1, "authorizedYn": 1},
                        {"episodeNo": 2, "authorizedYn": 1},
                        {"episodeNo": 3, "authorizedYn": 1},
                        {"episodeNo": 4, "authorizedYn": 1},
                        {"episodeNo": 5, "authorizedYn": 1},
                    ]

            class _MappingResult:
                def mappings(self):
                    return _Mappings()

            return _MappingResult()

        class _Result:
            lastrowid = self.next_lastrowid

        return _Result()

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class WebsochatActorLockTests(unittest.IsolatedAsyncioTestCase):
    def test_character_resolution_clarify_reply_hides_internal_scope_keys(self):
        reply = websochat_service._build_websochat_rp_character_resolution_clarify_reply(
            active_character_label="마법사",
            resolution_source="ambiguous",
            protagonist_intent=False,
            candidate_names=["named:이유진", "protagonist:first_person", "이소라"],
        )

        self.assertIn("이유진", reply)
        self.assertIn("주인공", reply)
        self.assertNotIn("named:", reply)
        self.assertNotIn("protagonist:", reply)

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

    async def test_post_message_does_not_save_rp_unavailable_as_character_fact(self):
        req_body = PostWebsochatMessageReqBody(
            client_message_id="client-rp-unavailable",
            content="안녕",
            starter_mode_key="rp",
            rp_mode="free",
            active_character="테스트",
            account_read_episode_to=1,
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
                "_charge_websochat_cash",
                new_callable=AsyncMock,
            ) as charge_cash,
            patch.object(
                websochat_service,
                "_generate_websochat_reply",
                new_callable=AsyncMock,
            ) as generate_reply,
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
            resolve_character.return_value = {
                "scopeKey": "named:test",
                "displayName": "테스트",
                "resolutionSource": "profile_alias",
                "candidateCount": 1,
            }
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
            resolve_charge_required.return_value = True
            generate_reply.return_value = (
                "지금은 테스트와 대화할 캐릭터 데이터가 아직 준비되지 않았어요.",
                "system",
                "rp:unavailable",
                False,
                "rp_unavailable",
                None,
            )

            result = await websochat_service.post_message(
                session_id=123,
                req_body=req_body,
                kc_user_id="kc-user-id",
                db=db,
            )

        self.assertEqual(result["data"]["sessionId"], 123)
        generate_reply.assert_awaited_once()
        update_params = [
            (args[1] if len(args) > 1 else kwargs)
            for args, kwargs in db.executions
            if (
                (args[1] if len(args) > 1 else kwargs).get("session_memory_json")
                and (args[1] if len(args) > 1 else kwargs).get("session_id") == 123
            )
        ]
        self.assertTrue(update_params)
        stored_memory = json.loads(update_params[-1]["session_memory_json"])
        self.assertEqual(stored_memory["active_character"], "named:test")
        self.assertEqual(stored_memory["rp_mode"], "free")
        self.assertEqual(stored_memory["recent_rp_facts"], [])
        usage_log_params = [
            (args[1] if len(args) > 1 else kwargs)
            for args, kwargs in db.executions
            if (args[1] if len(args) > 1 else kwargs).get("route_mode") == "rp:unavailable"
        ]
        self.assertTrue(usage_log_params)
        self.assertEqual(usage_log_params[-1]["charged_cash"], 0)
        charge_cash.assert_not_awaited()
        release_actor_lock_on_connection.assert_awaited_once_with(
            user_id=321,
            guest_key=None,
            conn=session_lock,
        )
        release_session_lock.assert_awaited_once_with(session_id=123, conn=session_lock)
        self.assertTrue(db.committed)
        self.assertFalse(db.rolled_back)

    async def test_post_message_saves_successful_rp_turn_as_recent_fact(self):
        req_body = PostWebsochatMessageReqBody(
            client_message_id="client-rp-memory",
            content="아직 있어?",
            rp_mode="free",
            account_read_episode_to=1,
        )
        db = _FakeDb()
        session_lock = object()
        existing_memory = {
            "active_mode": "rp",
            "read_episode_to": 1,
            "read_scope_state": "known",
            "read_scope_source": "account",
            "active_character": "named:test",
            "active_character_label": "테스트",
            "rp_mode": "free",
        }

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
                "_generate_websochat_reply",
                new_callable=AsyncMock,
            ) as generate_reply,
            patch.object(
                websochat_service,
                "emit_websochat_stream_text_if_needed",
                new_callable=AsyncMock,
            ),
        ):
            resolve_actor.return_value = (321, None)
            get_session_row.return_value = {
                "product_id": 987,
                "session_memory_json": json.dumps(existing_memory, ensure_ascii=False),
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
            generate_reply.return_value = (
                "여기 있어. 네 말은 듣고 있었어.",
                "gemini",
                "rp:free",
                False,
                "playful",
                None,
            )

            result = await websochat_service.post_message(
                session_id=123,
                req_body=req_body,
                kc_user_id="kc-user-id",
                db=db,
            )

        self.assertEqual(result["data"]["sessionId"], 123)
        update_params = [
            (args[1] if len(args) > 1 else kwargs)
            for args, kwargs in db.executions
            if (
                (args[1] if len(args) > 1 else kwargs).get("session_memory_json")
                and (args[1] if len(args) > 1 else kwargs).get("session_id") == 123
            )
        ]
        self.assertTrue(update_params)
        stored_memory = json.loads(update_params[-1]["session_memory_json"])
        self.assertEqual(stored_memory["active_character"], "named:test")
        self.assertEqual(stored_memory["rp_mode"], "free")
        self.assertIn("유저: 아직 있어?", stored_memory["recent_rp_facts"])
        self.assertIn("캐릭터: 여기 있어. 네 말은 듣고 있었어.", stored_memory["recent_rp_facts"])
        release_actor_lock_on_connection.assert_awaited_once_with(
            user_id=321,
            guest_key=None,
            conn=session_lock,
        )
        release_session_lock.assert_awaited_once_with(session_id=123, conn=session_lock)
        self.assertTrue(db.committed)
        self.assertFalse(db.rolled_back)


if __name__ == "__main__":
    unittest.main()
