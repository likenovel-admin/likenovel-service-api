import unittest
from unittest.mock import AsyncMock, patch

from app.services.websochat import websochat_service


class _Mappings:
    def __init__(self, *, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def one_or_none(self):
        return self._row

    def all(self):
        return self._rows


class _Result:
    def __init__(self, *, row=None, rows=None):
        self._mappings = _Mappings(row=row, rows=rows)

    def mappings(self):
        return self._mappings


class _Db:
    def __init__(self, results):
        self._results = list(results)
        self.statements = []

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return self._results.pop(0)


def _product_state_row(*, consent="Y"):
    return {
        "productId": 1182,
        "title": "테스트 작품",
        "authorNickname": "작가",
        "coverImagePath": None,
        "statusCode": "serializing",
        "priceType": "free",
        "openYn": "Y",
        "blindYn": "N",
        "aiContentServiceEnabledYn": consent,
        "ratingsCode": "all",
        "contextStatus": "ready",
        "latestEpisodeNo": 14,
        "syncedLatestEpisodeNo": 14,
    }


class WebsochatProductConsentTest(unittest.IsolatedAsyncioTestCase):
    async def test_consent_withdrawal_blocks_new_replies_with_explicit_reason(self):
        db = _Db([_Result(row=_product_state_row(consent="N"))])

        state = await websochat_service._get_websochat_product_session_state(
            product_id=1182,
            adult_yn="N",
            db=db,
        )

        self.assertFalse(state["canSendMessage"])
        self.assertEqual(
            state["unavailableMessage"],
            websochat_service.WEBSOCHAT_CONSENT_DISABLED_MESSAGE,
        )
        self.assertIn("ai_content_service_enabled_yn", db.statements[0])

    async def test_reenabled_consent_allows_existing_session_to_resume(self):
        db = _Db([_Result(row=_product_state_row(consent="Y"))])

        state = await websochat_service._get_websochat_product_session_state(
            product_id=1182,
            adult_yn="N",
            db=db,
        )

        self.assertTrue(state["canSendMessage"])
        self.assertIsNone(state["unavailableMessage"])

    async def test_private_product_remains_read_only_without_deleting_session(self):
        row = _product_state_row(consent="Y")
        row["openYn"] = "N"
        db = _Db([_Result(row=row)])

        state = await websochat_service._get_websochat_product_session_state(
            product_id=1182,
            adult_yn="N",
            db=db,
        )

        self.assertFalse(state["canSendMessage"])
        self.assertEqual(
            state["unavailableMessage"],
            websochat_service.WEBSOCHAT_PRODUCT_UNAVAILABLE_MESSAGE,
        )

    async def test_withdrawn_product_session_remains_visible_as_read_only(self):
        db = _Db(
            [
                _Result(
                    rows=[
                        {
                            "sessionId": 77,
                            "productId": 1182,
                            "title": "루벤과 대화",
                            "createdDate": "2026-07-14 10:00:00",
                            "updatedDate": "2026-07-14 11:00:00",
                            "sessionMemoryJson": None,
                        }
                    ]
                )
            ]
        )
        with (
            patch.object(websochat_service, "_resolve_actor", new_callable=AsyncMock) as resolve_actor,
            patch.object(
                websochat_service,
                "_resolve_effective_adult_yn",
                new_callable=AsyncMock,
                return_value="N",
            ),
            patch.object(
                websochat_service,
                "_get_websochat_product_session_state",
                new_callable=AsyncMock,
                return_value={
                    **_product_state_row(consent="N"),
                    "canSendMessage": False,
                    "unavailableMessage": websochat_service.WEBSOCHAT_CONSENT_DISABLED_MESSAGE,
                },
            ),
            patch.object(
                websochat_service,
                "_get_websochat_authorized_read_scope",
                new_callable=AsyncMock,
                return_value={
                    "authorizedReadEpisodeTo": 14,
                    "maxAuthorizedEpisodeTo": 14,
                },
            ),
            patch.object(
                websochat_service,
                "_get_websochat_visible_episode_title",
                new_callable=AsyncMock,
                return_value="14화",
            ),
        ):
            resolve_actor.return_value = (100, None)
            result = await websochat_service.get_sessions(
                kc_user_id="kc-user",
                guest_key=None,
                product_id=None,
                adult_yn="N",
                db=db,
            )

        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["sessionId"], 77)
        self.assertFalse(result["data"][0]["canSendMessage"])
        self.assertEqual(
            result["data"][0]["unavailableMessage"],
            websochat_service.WEBSOCHAT_CONSENT_DISABLED_MESSAGE,
        )

    async def test_product_lookup_and_search_require_active_consent(self):
        product_db = _Db([_Result(row=None)])
        search_db = _Db([_Result(rows=[])])

        await websochat_service._get_websochat_product(1182, "N", product_db)
        await websochat_service.search_products("테스트", None, "N", search_db)

        expected = "COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'"
        self.assertIn(expected, product_db.statements[0])
        self.assertIn(expected, search_db.statements[0])
