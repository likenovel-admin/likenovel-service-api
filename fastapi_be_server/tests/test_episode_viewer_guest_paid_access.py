import unittest
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
    def __init__(self):
        self.execute_count = 0

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
                    "episode_no": 3,
                    "title": "유료 테스트",
                    "cover_image_path": None,
                    "episode_title": "3화",
                    "epub_file_name": "paid.epub",
                    "count_comment": 0,
                    "author_comment": "",
                    "next_episode": 4,
                    "count_like": 0,
                    "comment_open_yn": "Y",
                    "evaluation_open_yn": "Y",
                    "prev_episode_id": 27361,
                    "next_episode_id": 27676,
                    "price_type": "paid",
                    "product_price_type": "paid",
                    "websochat_context_status": "pending",
                    "websochat_published_latest_episode_no": 5,
                    "websochat_synced_latest_episode_no": 0,
                    "prev_price_type": "free",
                    "next_price_type": "paid",
                }
            ]
        )


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
