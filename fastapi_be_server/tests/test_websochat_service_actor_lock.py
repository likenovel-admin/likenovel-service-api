import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import status

from app.exceptions import CustomResponseException
from app.schemas.websochat import PostWebsochatMessageReqBody
from app.services.websochat import websochat_service


class _FakeDb:
    def __init__(self, authorized_episode_to=5):
        self.next_lastrowid = 100
        self.committed = False
        self.rolled_back = False
        self.executions = []
        self.authorized_episode_tos = (
            list(authorized_episode_to)
            if isinstance(authorized_episode_to, (list, tuple))
            else [authorized_episode_to]
        )
        self.authorization_query_count = 0

    async def execute(self, *args, **kwargs):
        self.next_lastrowid += 1
        self.executions.append((args, kwargs))
        statement = str(args[0]) if args else ""
        if "FROM tb_product_episode pe" in statement and "authorizedYn" in statement:
            authorized_episode_to = self.authorized_episode_tos[
                min(
                    self.authorization_query_count,
                    len(self.authorized_episode_tos) - 1,
                )
            ]
            self.authorization_query_count += 1

            class _Mappings:
                def all(self):
                    return [
                        {"episodeNo": episode_no, "authorizedYn": 1}
                        for episode_no in range(1, authorized_episode_to + 1)
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
    async def test_post_message_acquires_actor_lock_for_billing_window(self):
        req_body = PostWebsochatMessageReqBody(
            client_message_id="client-actor-lock-1",
            content="50화 인물과 대화할래",
            starter_mode_key="rp",
            rp_mode="free",
            active_character="모르는 인물",
        )
        db = _FakeDb(authorized_episode_to=50)
        session_lock = object()
        pre_lock_memory = {
            "read_episode_to": 50,
            "read_scope_state": "known",
            "read_scope_source": "account",
        }
        locked_memory = {
            "read_episode_to": 49,
            "read_scope_state": "known",
            "read_scope_source": "account",
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
            get_session_row.side_effect = [
                {
                    "product_id": 987,
                    "session_memory_json": pre_lock_memory,
                    "title": websochat_service.WEBSOCHAT_DEFAULT_TITLE,
                },
                {
                    "product_id": 987,
                    "session_memory_json": locked_memory,
                    "title": websochat_service.WEBSOCHAT_DEFAULT_TITLE,
                },
            ]
            resolve_character.return_value = {}
            resolve_adult.return_value = "Y"
            get_product.return_value = {
                "productId": 987,
                "title": "테스트 작품",
                "contextStatus": "ready",
                "latestEpisodeNo": 50,
                "syncedLatestEpisodeNo": 50,
            }
            resolve_prompt_scope.return_value = 50
            acquire_session_lock.return_value = session_lock
            acquire_actor_lock_on_connection.return_value = True
            latest_visible_episode_no.return_value = 50
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
        update_params = [
            (args[1] if len(args) > 1 else kwargs)
            for args, kwargs in db.executions
            if (args[1] if len(args) > 1 else kwargs).get("session_memory_json")
        ]
        self.assertTrue(update_params)
        stored_memory = json.loads(update_params[-1]["session_memory_json"])
        self.assertEqual(stored_memory["read_episode_to"], 49)
        self.assertTrue(db.committed)
        self.assertTrue(db.rolled_back)

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
        self.assertTrue(db.rolled_back)

    async def test_post_message_saves_successful_rp_turn_as_recent_fact(self):
        req_body = PostWebsochatMessageReqBody(
            client_message_id="client-rp-memory",
            content="49화 기준으로 대화해줘",
            rp_mode="free",
            account_read_episode_to=50,
            model_key="deep",
        )
        db = _FakeDb(authorized_episode_to=[50, 30])
        session_lock = object()
        existing_memory = {
            "session_kind": "character_chat",
            "entry_source": "character_catalog",
            "locked_character_scope_key": "named:test",
            "allowed_modes": ["rp"],
            "active_mode": "rp",
            "read_episode_to": 50,
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
                "_ensure_websochat_character_chat_entry_context",
                new_callable=AsyncMock,
                side_effect=lambda *, session_memory, **_kwargs: session_memory,
            ),
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
            resolve_character.return_value = {
                "scopeKey": "named:test",
                "displayName": "테스트",
                "resolutionSource": "locked_scope_key",
                "candidateCount": 1,
            }
            resolve_adult.return_value = "Y"
            get_product.return_value = {
                "productId": 987,
                "title": "테스트 작품",
                "contextStatus": "ready",
                "latestEpisodeNo": 50,
                "syncedLatestEpisodeNo": 50,
                "characterChatEligible": True,
            }
            resolve_prompt_scope.return_value = 49
            acquire_session_lock.return_value = session_lock
            acquire_actor_lock_on_connection.return_value = True
            latest_visible_episode_no.return_value = 50
            get_existing_turn_messages.return_value = None
            resolve_charge_required.return_value = False
            def build_generated_reply(**kwargs):
                route_memory = dict(kwargs["session_memory"])
                route_memory[websochat_service.WEBSOCHAT_QA_EPISODE_REF_MEMORY_KEY] = [29, 31]
                return (
                    "31화 얘기는 하지 않을게.",
                    "gemini",
                    "qa:factual",
                    False,
                    "playful",
                    route_memory,
                )

            generate_reply.side_effect = build_generated_reply

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
        self.assertEqual(stored_memory["read_episode_to"], 30)
        self.assertEqual(stored_memory["read_scope_source"], "account")
        self.assertEqual(stored_memory["selected_model_key"], "deep")
        self.assertIn("유저: 49화 기준으로 대화해줘", stored_memory["recent_rp_facts"])
        self.assertIn("캐릭터: 31화 얘기는 하지 않을게.", stored_memory["recent_rp_facts"])
        self.assertEqual(
            resolve_charge_required.await_args.kwargs["model_key"],
            "deep",
        )
        self.assertEqual(generate_reply.await_args.kwargs["model_key"], "deep")
        self.assertEqual(
            generate_reply.await_args.kwargs["session_memory"]["read_episode_to"],
            49,
        )
        self.assertEqual(
            result["data"]["messages"][-1]["referencedEpisodeNos"],
            [29],
        )
        authorization_queries = [
            args
            for args, _kwargs in db.executions
            if args and "FROM tb_product_episode pe" in str(args[0]) and "authorizedYn" in str(args[0])
        ]
        self.assertEqual(len(authorization_queries), 2)
        release_actor_lock_on_connection.assert_awaited_once_with(
            user_id=321,
            guest_key=None,
            conn=session_lock,
        )
        release_session_lock.assert_awaited_once_with(session_id=123, conn=session_lock)
        self.assertTrue(db.committed)
        self.assertTrue(db.rolled_back)


if __name__ == "__main__":
    unittest.main()
