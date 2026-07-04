import unittest
from unittest.mock import AsyncMock, patch

from fastapi import status

from app.exceptions import CustomResponseException
from app.services.product import episode_service


class _FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _FakeMappings(self._rows)


class _GuestPaidEpisodeDb:
    def __init__(
        self,
        *,
        episode_no=3,
        price_type="paid",
        product_price_type="paid",
        websochat_context_status="pending",
        websochat_synced_latest_episode_no=0,
    ):
        self.execute_count = 0
        self.episode_no = episode_no
        self.price_type = price_type
        self.product_price_type = product_price_type
        self.websochat_context_status = websochat_context_status
        self.websochat_synced_latest_episode_no = websochat_synced_latest_episode_no

    async def execute(self, *_args, **_kwargs):
        self.execute_count += 1
        if self.execute_count == 1:
            return _FakeResult(
                [
                    {
                        "episode_open_yn": "Y",
                        "product_open_yn": "Y",
                        "product_id": 2011,
                        "title": "유료 테스트",
                        "episode_title": "3화",
                    }
                ]
            )

        return _FakeResult(
            [
                {
                    "product_id": 2011,
                    "episode_no": self.episode_no,
                    "title": "유료 테스트",
                    "cover_image_path": None,
                    "episode_title": f"{self.episode_no}화",
                    "epub_file_name": "episode.epub",
                    "count_comment": 0,
                    "author_comment": "",
                    "next_episode": 4,
                    "count_like": 0,
                    "comment_open_yn": "Y",
                    "evaluation_open_yn": "Y",
                    "prev_episode_id": 27361,
                    "next_episode_id": 27676,
                    "price_type": self.price_type,
                    "product_price_type": self.product_price_type,
                    "websochat_context_status": self.websochat_context_status,
                    "websochat_published_latest_episode_no": 5,
                    "websochat_synced_latest_episode_no": self.websochat_synced_latest_episode_no,
                    "prev_price_type": "free",
                    "next_price_type": "paid",
                }
            ]
        )


class _LoggedInNullableFreeEpisodeDb:
    def __init__(self):
        self.execute_count = 0

    async def execute(self, *_args, **_kwargs):
        self.execute_count += 1
        rows_by_call = {
            1: [{"cnt": 0}],
            2: [{"user_id": 200}],
            3: [
                {
                    "product_id": 2011,
                    "episode_no": 3,
                    "title": "무료 테스트",
                    "cover_image_path": None,
                    "episode_title": "3화",
                    "epub_file_name": "episode.epub",
                    "count_comment": 0,
                    "usage_id": None,
                    "recommend_yn": "N",
                    "bookmark_yn": "N",
                    "author_comment": "",
                    "evaluation_yn": "N",
                    "next_episode": 4,
                    "comment_open_yn": "Y",
                    "evaluation_open_yn": "Y",
                    "count_like": 0,
                    "prev_episode_id": 27361,
                    "next_episode_id": 27676,
                    "price_type": None,
                    "product_price_type": None,
                    "websochat_context_status": "ready",
                    "websochat_published_latest_episode_no": 5,
                    "websochat_synced_latest_episode_no": 3,
                    "open_yn": "Y",
                    "product_open_yn": "Y",
                    "product_author_id": None,
                    "product_user_id": None,
                    "own_type": None,
                    "prev_own_type": None,
                    "next_own_type": None,
                    "prev_price_type": None,
                    "next_price_type": None,
                    "prev_rental_remaining": None,
                    "next_rental_remaining": None,
                }
            ],
            5: [],
        }
        return _FakeResult(rows_by_call.get(self.execute_count, []))


class EpisodeViewerGuestPaidAccessTest(unittest.IsolatedAsyncioTestCase):
    async def test_guest_viewer_blocks_paid_episode_before_epub_url_generation(self):
        original_make_r2_presigned_url = episode_service.comm_service.make_r2_presigned_url

        def fail_if_epub_url_is_generated(**_kwargs):
            raise AssertionError("guest paid episode must not generate an EPUB URL")

        episode_service.comm_service.make_r2_presigned_url = fail_if_epub_url_is_generated
        try:
            with self.assertRaises(CustomResponseException) as exc:
                await episode_service.get_episodes_episode_id(
                    episode_id="27362",
                    kc_user_id="",
                    db=_GuestPaidEpisodeDb(),
                )
        finally:
            episode_service.comm_service.make_r2_presigned_url = (
                original_make_r2_presigned_url
            )

        self.assertEqual(
            exc.exception.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    async def test_guest_viewer_treats_null_price_type_as_free_for_websochat_eligibility(self):
        with (
            patch.object(
                episode_service.comm_service,
                "make_r2_presigned_url",
                return_value="signed-episode.epub",
            ),
            patch.object(
                episode_service.statistics_service,
                "insert_site_statistics_log",
                new_callable=AsyncMock,
            ),
        ):
            response = await episode_service.get_episodes_episode_id(
                episode_id="27362",
                kc_user_id="",
                db=_GuestPaidEpisodeDb(
                    price_type=None,
                    product_price_type=None,
                    websochat_context_status="ready",
                    websochat_synced_latest_episode_no=3,
                ),
            )

        self.assertIsNone(response["data"]["priceType"])
        self.assertTrue(response["data"]["websochatEligible"])

    async def test_logged_in_viewer_treats_null_price_type_as_free_for_websochat_eligibility(self):
        with (
            patch.object(
                episode_service.comm_service,
                "make_r2_presigned_url",
                return_value="signed-episode.epub",
            ),
            patch.object(
                episode_service.product_service,
                "save_product_hit_log",
                new_callable=AsyncMock,
            ),
            patch.object(
                episode_service.event_reward_service,
                "check_and_grant_event_reward",
                new_callable=AsyncMock,
            ),
            patch.object(
                episode_service.statistics_service,
                "insert_site_statistics_log",
                new_callable=AsyncMock,
            ),
        ):
            response = await episode_service.get_episodes_episode_id(
                episode_id="27362",
                kc_user_id="kc-user",
                db=_LoggedInNullableFreeEpisodeDb(),
            )

        self.assertIsNone(response["data"]["priceType"])
        self.assertTrue(response["data"]["websochatEligible"])
