import unittest
from unittest.mock import AsyncMock, patch

from fastapi import status

from app.exceptions import CustomResponseException
from app.schemas.websochat import (
    PatchWebsochatSessionReadScopeReqBody,
    PostWebsochatMessageReqBody,
)
from app.services.websochat import websochat_service
from app.services.websochat.websochat_game_memory import _normalize_websochat_session_memory


class _FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _FakeMappings(self._rows)


class _FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.params = None

    async def execute(self, statement, params=None):
        self.params = params or {}
        return _FakeResult(self.rows)


class _CountingDb:
    def __init__(self):
        self.execute_count = 0

    async def execute(self, *_args, **_kwargs):
        self.execute_count += 1
        return _FakeResult([])


class WebsochatPaidAuthorizationTest(unittest.IsolatedAsyncioTestCase):
    def test_legacy_server_authorized_prompt_source_normalizes_to_prompt(self):
        memory = _normalize_websochat_session_memory(
            {
                "read_episode_to": 5,
                "read_scope_state": "known",
                "read_scope_source": "server_authorized_prompt",
            }
        )

        self.assertEqual(memory["read_episode_to"], 5)
        self.assertEqual(memory["read_scope_state"], "known")
        self.assertEqual(memory["read_scope_source"], "prompt")

    async def test_service_prompt_scope_accepts_exact_episode_command(self):
        resolved = await websochat_service._resolve_websochat_prompt_read_episode_to(
            product_id=100,
            latest_episode_no=50,
            user_prompt="49화",
            db=_CountingDb(),
        )

        self.assertEqual(resolved, 49)

    def test_unknown_prompt_scope_is_clamped_by_cached_authorization(self):
        persistent_memory, turn_memory = (
            websochat_service._resolve_websochat_request_read_scope_memories(
                base_memory={},
                account_read_episode_to=None,
                prompt_decision={
                    "read_episode_to": 50,
                    "scope_state": "known",
                    "is_scope_only": False,
                },
                authorized_scope={"maxAuthorizedEpisodeTo": 3},
            )
        )

        self.assertEqual(persistent_memory["read_episode_to"], 3)
        self.assertEqual(persistent_memory["read_scope_source"], "prompt")
        self.assertEqual(turn_memory["read_episode_to"], 3)

    async def test_authorized_scope_uses_contiguous_paid_access_prefix(self):
        db = _FakeDb(
            [
                {"episodeNo": 1, "authorizedYn": 1},
                {"episodeNo": 2, "authorizedYn": 1},
                {"episodeNo": 3, "authorizedYn": 1},
                {"episodeNo": 4, "authorizedYn": 0},
                {"episodeNo": 5, "authorizedYn": 1},
            ]
        )

        scope = await websochat_service._get_websochat_authorized_read_scope(
            product_id=100,
            user_id=200,
            requested_episode_to=50,
            synced_latest_episode_no=50,
            db=db,
        )

        self.assertEqual(scope["contiguousAuthorizedEpisodeTo"], 3)
        self.assertEqual(scope["maxAuthorizedEpisodeTo"], 3)
        self.assertEqual(scope["authorizedReadEpisodeTo"], 3)
        self.assertEqual(db.params["user_id"], 200)

    async def test_authorized_scope_stops_before_non_contiguous_paid_gap(self):
        db = _FakeDb(
            [
                {"episodeNo": 1, "authorizedYn": 1},
                {"episodeNo": 2, "authorizedYn": 0},
                {"episodeNo": 3, "authorizedYn": 1},
            ]
        )

        scope = await websochat_service._get_websochat_authorized_read_scope(
            product_id=100,
            user_id=200,
            requested_episode_to=3,
            synced_latest_episode_no=3,
            db=db,
        )

        self.assertEqual(scope["contiguousAuthorizedEpisodeTo"], 1)
        self.assertEqual(scope["maxAuthorizedEpisodeTo"], 1)
        self.assertEqual(scope["authorizedReadEpisodeTo"], 1)

    async def test_authorized_scope_clamps_to_story_context_sync(self):
        db = _FakeDb(
            [
                {"episodeNo": 1, "authorizedYn": 1},
                {"episodeNo": 2, "authorizedYn": 1},
                {"episodeNo": 3, "authorizedYn": 1},
                {"episodeNo": 4, "authorizedYn": 1},
                {"episodeNo": 5, "authorizedYn": 1},
            ]
        )

        scope = await websochat_service._get_websochat_authorized_read_scope(
            product_id=100,
            user_id=200,
            requested_episode_to=5,
            synced_latest_episode_no=3,
            db=db,
        )

        self.assertEqual(scope["contiguousAuthorizedEpisodeTo"], 5)
        self.assertEqual(scope["maxAuthorizedEpisodeTo"], 3)
        self.assertEqual(scope["authorizedReadEpisodeTo"], 3)

    async def test_account_read_scope_is_server_clamped(self):
        db = _FakeDb(
            [
                {"episodeNo": 1, "authorizedYn": 1},
                {"episodeNo": 2, "authorizedYn": 1},
                {"episodeNo": 3, "authorizedYn": 1},
            ]
        )

        memory = await websochat_service._apply_websochat_account_read_scope(
            {},
            50,
            product_id=100,
            user_id=200,
            synced_latest_episode_no=10,
            db=db,
        )

        self.assertEqual(memory["read_episode_to"], 3)
        self.assertEqual(memory["read_scope_state"], "known")
        self.assertEqual(memory["read_scope_source"], "account")

    async def test_fresh_account_read_scope_supersedes_legacy_prompt_scope(self):
        db = _FakeDb(
            [
                {"episodeNo": episode_no, "authorizedYn": 1}
                for episode_no in range(1, 51)
            ]
        )

        memory = await websochat_service._apply_websochat_account_read_scope(
            {
                "read_episode_to": 49,
                "read_scope_state": "known",
                "read_scope_source": "server_authorized_prompt",
            },
            50,
            product_id=100,
            user_id=200,
            synced_latest_episode_no=50,
            db=db,
        )

        self.assertEqual(memory["read_episode_to"], 50)
        self.assertEqual(memory["read_scope_state"], "known")
        self.assertEqual(memory["read_scope_source"], "account")

    async def test_clamp_preserves_prompt_source_after_authorization(self):
        db = _FakeDb(
            [
                {"episodeNo": episode_no, "authorizedYn": 1}
                for episode_no in range(1, 11)
            ]
        )

        memory, scope = await websochat_service._clamp_websochat_session_read_scope_to_authorized(
            session_memory={
                "read_episode_to": 5,
                "read_scope_state": "known",
                "read_scope_source": "prompt",
            },
            product_id=100,
            user_id=200,
            synced_latest_episode_no=10,
            db=db,
        )

        self.assertEqual(memory["read_episode_to"], 5)
        self.assertEqual(memory["read_scope_state"], "known")
        self.assertEqual(memory["read_scope_source"], "prompt")
        self.assertEqual(scope["authorizedReadEpisodeTo"], 5)

    async def test_session_read_scope_is_cleared_when_no_authorized_episode_exists(self):
        db = _FakeDb([{"episodeNo": 1, "authorizedYn": 0}])

        memory, scope = await websochat_service._clamp_websochat_session_read_scope_to_authorized(
            session_memory={
                "read_episode_to": 10,
                "read_scope_state": "known",
                "read_scope_source": "prompt",
            },
            product_id=100,
            user_id=200,
            synced_latest_episode_no=10,
            db=db,
        )

        self.assertIsNone(memory["read_episode_to"])
        self.assertEqual(memory["read_scope_state"], "unknown")
        self.assertEqual(memory["read_scope_source"], "unknown")
        self.assertEqual(scope["maxAuthorizedEpisodeTo"], 0)

    async def test_viewer_read_scope_patch_does_not_expand_prompt_scope(self):
        req_body = PatchWebsochatSessionReadScopeReqBody(read_episode_to=27)
        db = _CountingDb()

        with (
            patch.object(websochat_service, "_resolve_actor", new_callable=AsyncMock) as resolve_actor,
            patch.object(websochat_service, "_get_session_row", new_callable=AsyncMock) as get_session_row,
            patch.object(websochat_service, "_resolve_effective_adult_yn", new_callable=AsyncMock) as resolve_adult,
            patch.object(
                websochat_service,
                "_get_websochat_product_session_state",
                new_callable=AsyncMock,
            ) as get_product_state,
            patch.object(
                websochat_service,
                "_get_websochat_authorized_read_scope",
                new_callable=AsyncMock,
            ) as get_authorized_scope,
            patch.object(
                websochat_service,
                "_get_websochat_visible_episode_title",
                new_callable=AsyncMock,
            ) as get_visible_episode_title,
        ):
            resolve_actor.return_value = (200, None)
            get_session_row.return_value = {
                "product_id": 100,
                "session_memory_json": {
                    "read_episode_to": 5,
                    "read_scope_state": "known",
                    "read_scope_source": "prompt",
                },
            }
            resolve_adult.return_value = "Y"
            get_product_state.return_value = {
                "canSendMessage": True,
                "latestEpisodeNo": 27,
                "syncedLatestEpisodeNo": 27,
            }
            get_authorized_scope.side_effect = [
                {
                    "requestedEpisodeTo": 5,
                    "authorizedReadEpisodeTo": 5,
                    "maxAuthorizedEpisodeTo": 27,
                    "contiguousAuthorizedEpisodeTo": 27,
                    "syncedLatestEpisodeNo": 27,
                },
                {
                    "requestedEpisodeTo": 27,
                    "authorizedReadEpisodeTo": 27,
                    "maxAuthorizedEpisodeTo": 27,
                    "contiguousAuthorizedEpisodeTo": 27,
                    "syncedLatestEpisodeNo": 27,
                },
            ]
            get_visible_episode_title.return_value = "5화"

            response = await websochat_service.patch_session_read_scope(
                session_id=10,
                req_body=req_body,
                kc_user_id="kc-user",
                db=db,
            )

        self.assertEqual(response["data"]["readEpisodeNo"], 5)
        self.assertEqual(response["data"]["readEpisodeTitle"], "5화")
        self.assertEqual(db.execute_count, 0)

    async def test_post_message_checks_access_before_character_resolution(self):
        req_body = PostWebsochatMessageReqBody(
            client_message_id="paid-auth-before-character",
            content="마법사랑 대화할래",
            starter_mode_key="rp",
            active_character="마법사",
        )

        with (
            patch.object(websochat_service, "_resolve_actor", new_callable=AsyncMock) as resolve_actor,
            patch.object(websochat_service, "_get_session_row", new_callable=AsyncMock) as get_session_row,
            patch.object(websochat_service, "_resolve_effective_adult_yn", new_callable=AsyncMock) as resolve_adult,
            patch.object(websochat_service, "_get_websochat_product", new_callable=AsyncMock) as get_product,
            patch.object(
                websochat_service,
                "_get_websochat_authorized_read_scope",
                new_callable=AsyncMock,
            ) as get_authorized_scope,
            patch.object(
                websochat_service,
                "_resolve_websochat_active_character_resolution",
                new_callable=AsyncMock,
            ) as resolve_character,
        ):
            resolve_actor.return_value = (200, None)
            get_session_row.return_value = {
                "product_id": 100,
                "session_memory_json": None,
                "title": websochat_service.WEBSOCHAT_DEFAULT_TITLE,
            }
            resolve_adult.return_value = "Y"
            get_product.return_value = {
                "productId": 100,
                "title": "유료 테스트 작품",
                "contextStatus": "ready",
                "latestEpisodeNo": 50,
                "syncedLatestEpisodeNo": 50,
            }
            get_authorized_scope.return_value = {
                "requestedEpisodeTo": None,
                "authorizedReadEpisodeTo": None,
                "maxAuthorizedEpisodeTo": 0,
                "contiguousAuthorizedEpisodeTo": 0,
                "syncedLatestEpisodeNo": 50,
            }

            with self.assertRaises(CustomResponseException) as captured:
                await websochat_service.post_message(
                    session_id=10,
                    req_body=req_body,
                    kc_user_id="kc-user",
                    db=_FakeDb([]),
                )

            self.assertEqual(captured.exception.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(captured.exception.message, websochat_service.WEBSOCHAT_ACCESS_REQUIRED_MESSAGE)
            resolve_character.assert_not_called()
