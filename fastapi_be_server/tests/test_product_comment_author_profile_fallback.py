import sys
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError


SERVICE_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "app/services/product/product_comment_service.py"
)
APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from app.const import settings
from app.schemas.product import GetProductsProductIdCommentsToCamel
from app.services.product.product_comment_service import _author_profile_image_path_sub_query


def test_comment_list_author_profile_join_has_fallback_profile():
    source = SERVICE_SOURCE.read_text()

    assert (
        "inner join tb_user_profile y on z.author_id = y.user_id"
        not in source
    )
    assert source.count("left join tb_user_profile y on z.author_id = y.user_id") == 8
    assert source.count("y_fallback.profile_id = (") == 8
    assert (
        source.count("{_author_profile_image_path_sub_query()}")
        == 8
    )
    assert "settings.R2_PROFILE_DEFAULT_IMAGE" in source

    author_image_sql = _author_profile_image_path_sub_query()

    assert (
        f"coalesce(y.profile_image_id, y_fallback.profile_image_id, {settings.R2_PROFILE_DEFAULT_IMAGE})"
        in author_image_sql
    )
    assert "AS author_profile_image_path" in author_image_sql


def test_comment_schema_keeps_author_profile_image_path_string_contract():
    row = {
        "comment_id": 1,
        "user_id": 2,
        "user_nickname": "관리자",
        "user_profile_image_path": "https://cdn.likenovel.net/user/default.webp",
        "user_interest_level_badge_image_path": "https://cdn.likenovel.net/badge/interest.webp",
        "user_event_level_badge_image_path": "https://cdn.likenovel.net/badge/event.webp",
        "content": "잘 보고 갑니다",
        "publish_date": datetime(2026, 7, 5, 1, 0, 0),
        "author_pinned_top_yn": "N",
        "author_recommend_yn": "N",
        "recommend_count": 0,
        "not_recommend_count": 0,
        "recommend_yn": "N",
        "not_recommend_yn": "N",
        "user_role": "admin",
        "comment_episode": "댓글 회차 : 1화. 테스트",
        "author_nickname": "작가",
        "author_profile_image_path": "https://cdn.likenovel.net/user/default.webp",
    }

    comment = GetProductsProductIdCommentsToCamel(**row)

    assert comment.author_profile_image_path == row["author_profile_image_path"]


def test_comment_schema_rejects_null_author_profile_image_path():
    row = {
        "comment_id": 1,
        "user_id": 2,
        "user_nickname": "관리자",
        "user_profile_image_path": "https://cdn.likenovel.net/user/default.webp",
        "user_interest_level_badge_image_path": "https://cdn.likenovel.net/badge/interest.webp",
        "user_event_level_badge_image_path": "https://cdn.likenovel.net/badge/event.webp",
        "content": "잘 보고 갑니다",
        "publish_date": datetime(2026, 7, 5, 1, 0, 0),
        "author_pinned_top_yn": "N",
        "author_recommend_yn": "N",
        "recommend_count": 0,
        "not_recommend_count": 0,
        "recommend_yn": "N",
        "not_recommend_yn": "N",
        "user_role": "admin",
        "comment_episode": "댓글 회차 : 1화. 테스트",
        "author_nickname": "작가",
        "author_profile_image_path": None,
    }

    try:
        GetProductsProductIdCommentsToCamel(**row)
    except ValidationError:
        return

    raise AssertionError("author_profile_image_path must stay non-null")
