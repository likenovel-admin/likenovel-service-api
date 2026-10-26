import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.exceptions import CustomResponseException
from app.services.common.ai_model_config import (
    AiModelBinding,
    FEATURE_CATALOG,
    default_model_binding,
    get_model_binding,
    has_ai_model_snapshot,
)
from app.services.websochat import websochat_service


class WebsochatModelSnapshotTest(unittest.IsolatedAsyncioTestCase):
    async def test_each_public_generation_entry_pins_once_and_releases_after_failure(self):
        for entry in ("create_session", "post_character_chat_choices", "post_message"):
            with self.subTest(entry=entry):
                seen = []
                first = {key: default_model_binding(key) for key in FEATURE_CATALOG}
                second = dict(first)
                first["websochat.speed"] = AiModelBinding("websochat.speed", "test/first", "openrouter", 1)
                second["websochat.speed"] = AiModelBinding("websochat.speed", "test/second", "openrouter", 2)

                async def stop_after_reading_pinned_model(*args):
                    seen.append(get_model_binding("websochat.speed"))
                    self.assertTrue(has_ai_model_snapshot())
                    raise CustomResponseException(status_code=403, message="test boundary")

                request = SimpleNamespace(
                    guest_key=None, starter_mode_key=None, qa_action_key=None,
                    rp_mode=None, active_character=None, game_mode=None,
                    client_message_id=None, content="test",
                )
                kwargs = {"req_body": request, "kc_user_id": None, "db": AsyncMock()}
                kwargs.update({"adult_yn": "N"} if entry == "create_session" else {"session_id": 1})
                with (
                    patch.object(websochat_service, "load_ai_model_snapshot", AsyncMock(side_effect=[first, second])) as load,
                    patch.object(websochat_service, "_resolve_actor", side_effect=stop_after_reading_pinned_model),
                ):
                    for _ in range(2):
                        with self.assertRaises(CustomResponseException):
                            await getattr(websochat_service, entry)(**kwargs)
                        self.assertFalse(has_ai_model_snapshot())
                    self.assertEqual(load.await_count, 2)
                self.assertEqual([item.model_id for item in seen], ["test/first", "test/second"])
