import unittest
from unittest.mock import AsyncMock, patch

from fastapi import Response, status

from app.const import settings
from app.exceptions import CustomResponseException
from app.routers.ai import direct_curator_query
from app.services.ai import direct_curator_service


def _slot(name: str, product_ids: list[int]) -> dict:
    return {
        "slot_id": len(name),
        "name": name,
        "order": 1,
        "product_ids": product_ids,
        "exposure_start": "2026-01-01",
        "exposure_end": "2026-12-31",
        "weekday": ["00:00:00", "23:59:59"],
        "weekend": ["00:00:00", "23:59:59"],
    }


def _candidate(product_id: int, title: str, **overrides) -> dict:
    candidate = {
        "product_id": product_id,
        "title": title,
        "price_type": "free",
        "product_type": "normal",
        "status_code": "ongoing",
        "publish_regular_yn": "Y",
        "primary_genre": "판타지",
        "sub_genre": "현대판타지",
        "paid_open_date": None,
        "first_public_episode_date": "2026-07-10T10:00:00",
        "latest_public_episode_date": "2026-07-11T10:00:00",
        "open_episode_count": 12,
        "count_hit": 120,
        "count_bookmark": 7,
        "reading_rate": 63.5,
        "writing_count_per_week": 7.0,
        "waiting_for_free_yn": "N",
        "exclude_from_recommend_yn": "N",
        "synopsis_text": "contact author@example.com for a spoiler-heavy synopsis",
        "premise": None,
        "hook": "reader@example.com should not leak",
        "episode_summary_text": "첫 사건이 시작된다.",
    }
    candidate.update(overrides)
    return candidate


class DirectCuratorAuthTests(unittest.TestCase):
    def test_unconfigured_secret_fails_closed(self):
        with patch.object(settings, "DIRECT_CURATOR_SNAPSHOT_TOKEN", ""):
            with self.assertRaises(CustomResponseException) as exc:
                direct_curator_query.require_curator_key(None)

        self.assertEqual(exc.exception.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_missing_or_wrong_secret_is_rejected(self):
        with patch.object(settings, "DIRECT_CURATOR_SNAPSHOT_TOKEN", "expected"):
            for supplied in (None, "wrong"):
                with self.subTest(supplied=supplied):
                    with self.assertRaises(CustomResponseException) as exc:
                        direct_curator_query.require_curator_key(supplied)
                    self.assertEqual(
                        exc.exception.status_code,
                        status.HTTP_401_UNAUTHORIZED,
                    )

    def test_matching_secret_is_accepted(self):
        with patch.object(settings, "DIRECT_CURATOR_SNAPSHOT_TOKEN", "expected"):
            self.assertIsNone(direct_curator_query.require_curator_key("expected"))


class DirectCuratorRouteTests(unittest.IsolatedAsyncioTestCase):
    def test_router_exposes_get_only(self):
        methods = {
            method
            for route in direct_curator_query.router.routes
            for method in route.methods
        }

        self.assertEqual(methods, {"GET"})

    async def test_route_is_no_store_and_delegates_to_read_only_service(self):
        response = Response()
        db = object()
        snapshot = {"mode": "proposal_only", "candidate_count": 1}

        with patch.object(
            direct_curator_query.direct_curator_service,
            "build_scheduled_snapshot",
            new_callable=AsyncMock,
            return_value=snapshot,
        ) as build_snapshot:
            result = await direct_curator_query.get_direct_curator_snapshot(
                response=response,
                db=db,
                _authorized=None,
            )

        self.assertEqual(result, {"data": snapshot})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        build_snapshot.assert_awaited_once_with(db)


class DirectCuratorSnapshotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.slots = [
            _slot(direct_curator_service.SLOT_PD, [1]),
            _slot(direct_curator_service.SLOT_WAIT_FREE, [2]),
            _slot(direct_curator_service.SLOT_PAID_OPENRUN, [2]),
            _slot(direct_curator_service.SLOT_FREE_NEW, [1]),
            _slot(direct_curator_service.SLOT_LOWPOINT, [1]),
        ]
        self.candidates = [
            _candidate(1, "무료 신작"),
            _candidate(
                2,
                "기다무 신작",
                price_type="paid",
                waiting_for_free_yn="Y",
                paid_open_date="2026-07-10T00:00:00",
                synopsis_text="유료 전환작",
                hook=None,
            ),
        ]

    def test_snapshot_queries_contain_no_dml(self):
        sql = (
            f"{direct_curator_service.SLOT_QUERY}\n"
            f"{direct_curator_service.CANDIDATE_QUERY}"
        ).upper()

        for keyword in ("INSERT ", "UPDATE ", "DELETE ", "REPLACE "):
            with self.subTest(keyword=keyword):
                self.assertNotIn(keyword, sql)

    async def test_snapshot_is_bounded_sanitized_and_proposal_only(self):
        db = AsyncMock()

        with (
            patch.object(
                direct_curator_service,
                "_load_slots",
                new_callable=AsyncMock,
                side_effect=[self.slots, self.slots],
            ),
            patch.object(
                direct_curator_service,
                "_load_candidates",
                new_callable=AsyncMock,
                return_value=self.candidates,
            ),
        ):
            result = await direct_curator_service.build_scheduled_snapshot(db)

        self.assertEqual(result["mode"], "proposal_only")
        self.assertEqual(result["snapshot_format"], "scheduled_compact_v1")
        self.assertTrue(result["slot_snapshot_stable"])
        self.assertEqual(result["candidate_count"], 2)
        self.assertNotIn("author_name", result["candidate_row_fields"])
        self.assertNotIn("@example.com", str(result))
        self.assertIn("[redacted-email]", str(result))
        self.assertIsNotNone(result["objective_checks"])
        db.rollback.assert_awaited_once_with()

    async def test_concurrent_slot_change_disables_objective_checks(self):
        changed_slots = [dict(slot) for slot in self.slots]
        changed_slots[0] = {**changed_slots[0], "product_ids": [2]}
        db = AsyncMock()

        with (
            patch.object(
                direct_curator_service,
                "_load_slots",
                new_callable=AsyncMock,
                side_effect=[self.slots, changed_slots],
            ),
            patch.object(
                direct_curator_service,
                "_load_candidates",
                new_callable=AsyncMock,
                return_value=self.candidates,
            ),
        ):
            result = await direct_curator_service.build_scheduled_snapshot(db)

        self.assertFalse(result["slot_snapshot_stable"])
        self.assertIsNone(result["objective_checks"])


if __name__ == "__main__":
    unittest.main()
