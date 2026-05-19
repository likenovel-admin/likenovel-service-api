import asyncio
import unittest

from pydantic import ValidationError

from app.exceptions import CustomResponseException
from app.schemas.admin import AdminDelegatedEpisodeOperationReqBody
from app.services.admin.admin_episode_management_service import (
    _is_paid_product_configured,
    _load_existing_episodes,
    build_admin_episode_operation_idempotency_key,
)


class _FakeMappingResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *_args, **_kwargs):
        return _FakeMappingResult(self._rows)


class AdminEpisodeManagementServiceTest(unittest.TestCase):
    def test_operation_schema_rejects_unknown_action(self):
        with self.assertRaises(ValidationError):
            AdminDelegatedEpisodeOperationReqBody(
                action="delete_episode",
                episodes=[
                    {
                        "episode_no": 51,
                        "title": "51화.",
                        "epub_file_id": 901,
                    }
                ],
            )

    def test_operation_schema_rejects_duplicate_episode_no(self):
        with self.assertRaises(ValidationError):
            AdminDelegatedEpisodeOperationReqBody(
                action="append_epub",
                episodes=[
                    {
                        "episode_no": 51,
                        "title": "51화.",
                        "epub_file_id": 901,
                    },
                    {
                        "episode_no": 51,
                        "title": "51화. 중복",
                        "epub_file_id": 902,
                    },
                ],
            )

    def test_operation_schema_rejects_invalid_source_sha256(self):
        with self.assertRaises(ValidationError):
            AdminDelegatedEpisodeOperationReqBody(
                action="append_epub",
                episodes=[
                    {
                        "episode_no": 51,
                        "title": "51화.",
                        "epub_file_id": 901,
                        "source_sha256": "not-a-sha",
                    }
                ],
            )

    def test_replace_operation_rejects_publish_reservation(self):
        with self.assertRaises(ValidationError):
            AdminDelegatedEpisodeOperationReqBody(
                action="replace_epub",
                episodes=[
                    {
                        "episode_no": 51,
                        "title": "51화.",
                        "epub_file_id": 901,
                        "publish_reserve_yn": "Y",
                        "publish_reserve_date": "2026-05-19T16:00:00+09:00",
                    }
                ],
            )

    def test_paid_product_config_detects_paid_schedule_even_before_price_type_flip(self):
        self.assertTrue(
            _is_paid_product_configured(
                {
                    "price_type": "free",
                    "series_regular_price": 100,
                    "single_regular_price": 0,
                }
            )
        )

    def test_load_existing_episodes_rejects_duplicate_active_episode_no(self):
        rows = [
            {"episode_id": 1, "episode_no": 51},
            {"episode_id": 2, "episode_no": 51},
        ]

        with self.assertRaises(CustomResponseException):
            asyncio.run(
                _load_existing_episodes(
                    product_id=1105,
                    db=_FakeDb(rows),
                )
            )

    def test_idempotency_key_is_stable_for_same_episode_set(self):
        first = build_admin_episode_operation_idempotency_key(
            product_id=1105,
            action="append_epub",
            items=[
                {
                    "episode_no": 52,
                    "episode_title": "52화.",
                    "epub_file_id": 902,
                    "source_sha256": "b" * 64,
                    "publish_reserve_date": "2026-05-20T16:00:00+09:00",
                },
                {
                    "episode_no": 51,
                    "episode_title": "51화.",
                    "epub_file_id": 901,
                    "source_sha256": "a" * 64,
                    "publish_reserve_date": "2026-05-19T16:00:00+09:00",
                },
            ],
        )
        second = build_admin_episode_operation_idempotency_key(
            product_id=1105,
            action="append_epub",
            items=[
                {
                    "episode_no": 51,
                    "episode_title": "51화.",
                    "epub_file_id": 901,
                    "source_sha256": "a" * 64,
                    "publish_reserve_date": "2026-05-19T16:00:00+09:00",
                },
                {
                    "episode_no": 52,
                    "episode_title": "52화.",
                    "epub_file_id": 902,
                    "source_sha256": "b" * 64,
                    "publish_reserve_date": "2026-05-20T16:00:00+09:00",
                },
            ],
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_idempotency_key_changes_when_source_file_changes(self):
        base = build_admin_episode_operation_idempotency_key(
            product_id=1105,
            action="append_epub",
            items=[
                {
                    "episode_no": 51,
                    "episode_title": "51화.",
                    "epub_file_id": 901,
                    "source_sha256": "a" * 64,
                    "publish_reserve_date": "2026-05-19T16:00:00+09:00",
                }
            ],
        )
        changed = build_admin_episode_operation_idempotency_key(
            product_id=1105,
            action="append_epub",
            items=[
                {
                    "episode_no": 51,
                    "episode_title": "51화.",
                    "epub_file_id": 901,
                    "source_sha256": "c" * 64,
                    "publish_reserve_date": "2026-05-19T16:00:00+09:00",
                }
            ],
        )

        self.assertNotEqual(base, changed)

    def test_idempotency_key_changes_when_mutation_field_changes(self):
        base = build_admin_episode_operation_idempotency_key(
            product_id=1105,
            action="append_epub",
            items=[
                {
                    "episode_no": 51,
                    "title": "51화.",
                    "epub_file_id": 901,
                    "source_sha256": "a" * 64,
                    "author_comment": "첫 코멘트",
                }
            ],
        )
        changed = build_admin_episode_operation_idempotency_key(
            product_id=1105,
            action="append_epub",
            items=[
                {
                    "episode_no": 51,
                    "title": "51화.",
                    "epub_file_id": 901,
                    "source_sha256": "a" * 64,
                    "author_comment": "수정 코멘트",
                }
            ],
        )

        self.assertNotEqual(base, changed)


if __name__ == "__main__":
    unittest.main()
