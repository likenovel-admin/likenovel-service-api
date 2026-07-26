import logging
import logging.handlers
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import Response, status

with patch.object(
    logging.handlers,
    "TimedRotatingFileHandler",
    return_value=logging.NullHandler(),
):
    from app.exceptions import CustomResponseException
    from app.routers.product import episode_query
    from app.services.product import episode_service


class _FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def one_or_none(self):
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


def _viewer_row(**overrides):
    row = {
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
        "open_yn": "Y",
        "product_open_yn": "Y",
        "publish_reserve_yn": "N",
        "product_author_id": 9001,
        "product_user_id": 9001,
        "cp_user_id": None,
        "own_type": None,
        "usage_id": None,
    }
    row.update(overrides)
    return row


class _ViewerDb:
    def __init__(self, *, episode_row, actor_row=None):
        self.episode_row = episode_row
        self.actor_row = actor_row or {
            "user_id": 7001,
            "role_type": "user",
            "is_cp": 0,
        }
        self.queries = []

    async def execute(self, query, _params=None):
        sql = str(query)
        self.queries.append(sql)
        if "u.role_type" in sql and "from tb_user u" in sql:
            return _FakeResult([self.actor_row])
        if "with tmp_get_episodes_episode_id_1" in sql:
            return _FakeResult([self.episode_row])
        return _FakeResult([])


def _info_row(**overrides):
    row = {
        "episode_id": 27362,
        "episode_use_yn": "Y",
        "title": "3화",
        "content": "<p>본문</p>",
        "author_comment": "작가의 말",
        "evaluation_open_yn": "Y",
        "comment_open_yn": "Y",
        "episode_open_yn": "Y",
        "product_open_yn": "Y",
        "publish_reserve_yn": "N",
        "reserve_yn": "N",
        "publish_reserve_date": None,
        "price_type": "paid",
        "count_like": 0,
        "product_user_id": 9001,
        "product_author_id": 9001,
        "cp_user_id": None,
    }
    row.update(overrides)
    return row


class _InfoDb:
    def __init__(self, *, info_row, actor_row=None):
        self.info_row = info_row
        self.actor_row = actor_row

    async def execute(self, query, params=None):
        sql = str(query)
        if "u.role_type" in sql and "from tb_user u" in sql:
            return _FakeResult([self.actor_row] if self.actor_row else [])
        if "a.use_yn" in sql and "a.episode_title" not in sql:
            if not self.info_row:
                return _FakeResult([])
            return _FakeResult(
                [
                    {
                        "episode_id": self.info_row["episode_id"],
                        "use_yn": self.info_row["episode_use_yn"],
                    }
                ]
            )
        if "a.episode_content as content" in sql:
            user_id = (params or {}).get("user_id")
            can_manage = bool(
                self.info_row
                and (
                    (params or {}).get("is_admin") == 1
                    or self.info_row.get("product_user_id") == user_id
                    or self.info_row.get("product_author_id") == user_id
                    or (
                        (params or {}).get("is_cp") == 1
                        and self.info_row.get("cp_user_id") == user_id
                    )
                )
            )
            return _FakeResult([self.info_row] if can_manage else [])
        if "a.episode_title as title" in sql:
            is_public = bool(
                self.info_row
                and self.info_row.get("episode_open_yn") == "Y"
                and self.info_row.get("product_open_yn") == "Y"
                and self.info_row.get("publish_reserve_yn") != "Y"
            )
            return _FakeResult([self.info_row] if is_public else [])
        raise AssertionError(f"unexpected query: {sql}")


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

    async def test_authenticated_unowned_paid_episode_is_denied_before_side_effects(self):
        db = _ViewerDb(episode_row=_viewer_row())

        with (
            patch.object(
                episode_service.comm_service,
                "make_r2_presigned_url",
            ) as make_presigned,
            patch.object(
                episode_service,
                "check_like_product_episode",
                new=AsyncMock(return_value=False),
            ) as check_like,
            patch.object(
                episode_service.product_service,
                "save_product_hit_log",
                new=AsyncMock(),
            ) as save_hit_log,
            patch.object(
                episode_service.event_reward_service,
                "check_and_grant_event_reward",
                new=AsyncMock(),
            ) as grant_reward,
            patch.object(
                episode_service.statistics_service,
                "insert_site_statistics_log",
                new=AsyncMock(),
            ) as insert_statistics,
        ):
            with self.assertRaises(CustomResponseException) as exc:
                await episode_service.get_episodes_episode_id(
                    episode_id="27362",
                    kc_user_id="kc-user",
                    db=db,
                )

        self.assertEqual(exc.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(exc.exception.code, "PURCHASE_REQUIRED")
        make_presigned.assert_not_called()
        check_like.assert_not_awaited()
        save_hit_log.assert_not_awaited()
        grant_reward.assert_not_awaited()
        insert_statistics.assert_not_awaited()
        self.assertFalse(
            any(
                marker in sql.lower()
                for sql in db.queries
                for marker in (
                    "insert into tb_user_product_usage",
                    "update tb_user_product_usage",
                    "update tb_product_episode",
                    "update tb_product",
                )
            )
        )

    async def test_paid_episode_allows_effective_entitlement_and_privileged_actors(self):
        cases = (
            ("own", _viewer_row(own_type="own"), None),
            ("rental", _viewer_row(own_type="rental"), None),
            (
                "product-user",
                _viewer_row(product_user_id=7001),
                None,
            ),
            (
                "product-author",
                _viewer_row(product_author_id=7001),
                None,
            ),
            (
                "admin",
                _viewer_row(open_yn="N"),
                {"user_id": 7001, "role_type": "admin", "is_cp": 0},
            ),
            (
                "assigned-cp",
                _viewer_row(cp_user_id=7001, publish_reserve_yn="Y"),
                {"user_id": 7001, "role_type": "user", "is_cp": 1},
            ),
        )

        for label, row, actor_row in cases:
            with self.subTest(label=label):
                db = _ViewerDb(episode_row=row, actor_row=actor_row)
                with (
                    patch.object(
                        episode_service.comm_service,
                        "make_r2_presigned_url",
                        return_value="https://signed.example/episode.epub",
                    ),
                    patch.object(
                        episode_service,
                        "check_like_product_episode",
                        new=AsyncMock(return_value=False),
                    ),
                    patch.object(
                        episode_service.product_service,
                        "save_product_hit_log",
                        new=AsyncMock(),
                    ),
                    patch.object(
                        episode_service.event_reward_service,
                        "check_and_grant_event_reward",
                        new=AsyncMock(),
                    ),
                    patch.object(
                        episode_service.statistics_service,
                        "insert_site_statistics_log",
                        new=AsyncMock(),
                    ),
                ):
                    response = await episode_service.get_episodes_episode_id(
                        episode_id="27362",
                        kc_user_id="kc-user",
                        db=db,
                    )

                self.assertEqual(
                    response["data"]["epubFilePath"],
                    "https://signed.example/episode.epub",
                )

    async def test_paid_episode_rejects_unrelated_cp_unaccepted_cp_and_editor(self):
        actors = (
            {"user_id": 7001, "role_type": "user", "is_cp": 1},
            {"user_id": 7001, "role_type": "user", "is_cp": 0},
            {"user_id": 7001, "role_type": "editor", "is_cp": 0},
        )
        for actor_row in actors:
            with self.subTest(actor=actor_row):
                db = _ViewerDb(
                    episode_row=_viewer_row(cp_user_id=8001),
                    actor_row=actor_row,
                )
                with (
                    patch.object(
                        episode_service,
                        "check_like_product_episode",
                        new=AsyncMock(return_value=False),
                    ),
                    patch.object(
                        episode_service.statistics_service,
                        "insert_site_statistics_log",
                        new=AsyncMock(),
                    ),
                ):
                    with self.assertRaises(CustomResponseException) as exc:
                        await episode_service.get_episodes_episode_id(
                            episode_id="27362",
                            kc_user_id="kc-user",
                            db=db,
                        )
                self.assertEqual(exc.exception.status_code, status.HTTP_403_FORBIDDEN)
                self.assertEqual(exc.exception.code, "PURCHASE_REQUIRED")

    async def test_free_and_null_price_episodes_remain_accessible(self):
        for price_type in ("free", None):
            with self.subTest(price_type=price_type):
                db = _ViewerDb(
                    episode_row=_viewer_row(
                        price_type=price_type,
                        websochat_context_status="ready",
                        websochat_synced_latest_episode_no=3,
                    )
                )
                with (
                    patch.object(
                        episode_service.comm_service,
                        "make_r2_presigned_url",
                        return_value="https://signed.example/episode.epub",
                    ),
                    patch.object(
                        episode_service,
                        "check_like_product_episode",
                        new=AsyncMock(return_value=False),
                    ),
                    patch.object(
                        episode_service.product_service,
                        "save_product_hit_log",
                        new=AsyncMock(),
                    ),
                    patch.object(
                        episode_service.event_reward_service,
                        "check_and_grant_event_reward",
                        new=AsyncMock(),
                    ),
                    patch.object(
                        episode_service.statistics_service,
                        "insert_site_statistics_log",
                        new=AsyncMock(),
                    ),
                ):
                    response = await episode_service.get_episodes_episode_id(
                        episode_id="27362",
                        kc_user_id="kc-user",
                        db=db,
                    )
                self.assertEqual(
                    response["data"]["epubFilePath"],
                    "https://signed.example/episode.epub",
                )
                self.assertEqual(response["data"]["priceType"], price_type)
                self.assertTrue(response["data"]["websochatEligible"])

    async def test_private_or_reserved_episode_never_presigns_for_regular_buyer(self):
        rows = (
            _viewer_row(open_yn="N", own_type="own"),
            _viewer_row(publish_reserve_yn="Y", own_type="own"),
            _viewer_row(product_open_yn="N", own_type="own"),
        )
        for row in rows:
            with self.subTest(row=row):
                db = _ViewerDb(episode_row=row)
                with (
                    patch.object(
                        episode_service.comm_service,
                        "make_r2_presigned_url",
                    ) as make_presigned,
                    patch.object(
                        episode_service,
                        "check_like_product_episode",
                        new=AsyncMock(return_value=False),
                    ),
                    patch.object(
                        episode_service.statistics_service,
                        "insert_site_statistics_log",
                        new=AsyncMock(),
                    ),
                ):
                    response = await episode_service.get_episodes_episode_id(
                        episode_id="27362",
                        kc_user_id="kc-user",
                        db=db,
                    )
                make_presigned.assert_not_called()
                self.assertNotIn("epubFilePath", response["data"])
                self.assertEqual(response["data"]["privateYn"], "Y")


class EpisodeInfoAccessTest(unittest.IsolatedAsyncioTestCase):
    async def test_guest_and_nonprivileged_public_info_is_metadata_only(self):
        cases = (
            ("", None),
            (
                "kc-user",
                {"user_id": 7001, "role_type": "user", "is_cp": 0},
            ),
        )
        for kc_user_id, actor_row in cases:
            with self.subTest(kc_user_id=kc_user_id):
                response = await episode_service.get_episodes_episode_id_info(
                    episode_id="27362",
                    kc_user_id=kc_user_id,
                    db=_InfoDb(info_row=_info_row(), actor_row=actor_row),
                )
                self.assertEqual(
                    response,
                    {"data": {"episodeId": 27362, "title": "3화"}},
                )

    async def test_private_or_reserved_info_is_not_found_for_nonprivileged_user(self):
        rows = (
            _info_row(episode_open_yn="N"),
            _info_row(product_open_yn="N"),
            _info_row(publish_reserve_yn="Y"),
        )
        for row in rows:
            with self.subTest(row=row):
                with self.assertRaises(CustomResponseException) as exc:
                    await episode_service.get_episodes_episode_id_info(
                        episode_id="27362",
                        kc_user_id="",
                        db=_InfoDb(info_row=row),
                    )
                self.assertEqual(exc.exception.status_code, status.HTTP_404_NOT_FOUND)

    async def test_privileged_info_keeps_full_author_fields(self):
        actor_row = {"user_id": 7001, "role_type": "user", "is_cp": 1}
        with patch.object(
            episode_service,
            "check_like_product_episode",
            new=AsyncMock(return_value=True),
        ):
            response = await episode_service.get_episodes_episode_id_info(
                episode_id="27362",
                kc_user_id="kc-cp",
                db=_InfoDb(
                    info_row=_info_row(
                        episode_open_yn="N",
                        publish_reserve_yn="Y",
                        cp_user_id=7001,
                    ),
                    actor_row=actor_row,
                ),
            )

        self.assertEqual(response["data"]["content"], "<p>본문</p>")
        self.assertEqual(response["data"]["authorComment"], "작가의 말")
        self.assertEqual(response["data"]["liked"], "Y")

    async def test_info_route_sets_private_no_store_on_success(self):
        response = Response()
        service_response = {"data": {"episodeId": 27362, "title": "3화"}}
        with patch.object(
            episode_query.episode_service,
            "get_episodes_episode_id_info",
            new=AsyncMock(return_value=service_response),
        ):
            result = await episode_query.get_episodes_episode_id_info(
                response=response,
                episode_id="27362",
                user={"sub": ""},
                db=object(),
            )

        self.assertEqual(result, service_response)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
