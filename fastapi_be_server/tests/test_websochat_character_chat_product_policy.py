import json
import unittest
from unittest.mock import AsyncMock, patch

from app.exceptions import CustomResponseException
from app.schemas.websochat import PostWebsochatMessageReqBody, PostWebsochatSessionReqBody
from app.services.websochat import websochat_service


class _Mappings:
    def __init__(self, row):
        self._row = row

    def one_or_none(self):
        return self._row


class _Result:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return _Mappings(self._row)


class _Db:
    def __init__(self, row):
        self.row = row
        self.statements = []

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return _Result(self.row)


def _product_row(*, character_chat_eligible: int) -> dict:
    return {
        "productId": 1182,
        "title": "테스트 작품",
        "authorNickname": "작가",
        "statusCode": "ongoing",
        "priceType": "free",
        "contextStatus": "ready",
        "latestEpisodeNo": 15,
        "syncedLatestEpisodeNo": 15,
        "characterChatEligible": character_chat_eligible,
    }


class CharacterChatProductPolicyTest(unittest.IsolatedAsyncioTestCase):
    async def test_product_lookup_computes_policy_without_filtering_general_websochat(self):
        db = _Db(_product_row(character_chat_eligible=0))

        product = await websochat_service._get_websochat_product(1182, "N", db)

        self.assertIsNotNone(product)
        self.assertFalse(product["characterChatEligible"])
        query = db.statements[0]
        self.assertIn("p.status_code = 'ongoing'", query)
        self.assertIn("COUNT(e.episode_id) >= 15", query)
        self.assertIn("MIN(COALESCE(", query)
        self.assertIn("e.open_changed_date", query)
        self.assertIn(">= '2026-03-01 00:00:00'", query)

    def test_only_character_chat_uses_product_policy_for_send_permission(self):
        product = {"canSendMessage": True, "characterChatEligible": 0}

        self.assertTrue(
            websochat_service._resolve_websochat_session_can_send_message(
                product_state=product,
                session_memory={"session_kind": "websochat"},
                max_authorized_episode_to=15,
            )
        )
        self.assertFalse(
            websochat_service._resolve_websochat_session_can_send_message(
                product_state=product,
                session_memory={"session_kind": "character_chat"},
                max_authorized_episode_to=15,
            )
        )

    async def test_character_chat_creation_rejects_out_of_cohort_product(self):
        req_body = PostWebsochatSessionReqBody(
            product_id=1182,
            guest_key="guest-1",
            session_kind="character_chat",
            locked_character_scope_key="character:adelite",
        )
        with (
            patch.object(
                websochat_service,
                "_resolve_actor",
                new_callable=AsyncMock,
                return_value=(None, "guest-1"),
            ),
            patch.object(
                websochat_service,
                "_resolve_effective_adult_yn",
                new_callable=AsyncMock,
                return_value="N",
            ),
            patch.object(
                websochat_service,
                "_get_websochat_product",
                new_callable=AsyncMock,
                return_value=_product_row(character_chat_eligible=0),
            ),
            patch.object(
                websochat_service,
                "_get_websochat_authorized_read_scope",
                new_callable=AsyncMock,
                return_value={"maxAuthorizedEpisodeTo": 15},
            ),
        ):
            with self.assertRaises(CustomResponseException) as raised:
                await websochat_service.create_session(
                    req_body=req_body,
                    kc_user_id=None,
                    adult_yn="N",
                    db=AsyncMock(),
                )

        self.assertEqual(raised.exception.code, "CHARACTER_CHAT_PRODUCT_INELIGIBLE")

    async def test_existing_character_chat_is_read_only_outside_cohort(self):
        req_body = PostWebsochatMessageReqBody(
            guest_key="guest-1",
            client_message_id="message-1",
            content="계속 이야기하자.",
        )
        session_row = {
            "product_id": 1182,
            "session_memory_json": json.dumps(
                {
                    "session_kind": "character_chat",
                    "locked_character_scope_key": "character:adelite",
                    "allowed_modes": ["rp"],
                    "active_mode": "rp",
                }
            ),
        }
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
                return_value=session_row,
            ),
            patch.object(
                websochat_service,
                "_resolve_effective_adult_yn",
                new_callable=AsyncMock,
                return_value="N",
            ),
            patch.object(
                websochat_service,
                "_get_websochat_product",
                new_callable=AsyncMock,
                return_value=_product_row(character_chat_eligible=0),
            ),
        ):
            with self.assertRaises(CustomResponseException) as raised:
                await websochat_service.post_message(
                    session_id=77,
                    req_body=req_body,
                    kc_user_id=None,
                    db=AsyncMock(),
                )

        self.assertEqual(raised.exception.code, "CHARACTER_CHAT_PRODUCT_INELIGIBLE")
