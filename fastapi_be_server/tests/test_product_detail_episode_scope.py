from fastapi import status

from app.exceptions import CustomResponseException
from app.services.product import product_service


def test_guest_detail_episode_predicate_excludes_closed_unowned_episodes():
    predicate = product_service._build_product_detail_episode_visibility_predicate(
        can_read_owner_episodes=False
    )

    assert "e.open_yn = 'Y'" in predicate
    assert "tb_user_productbook pb" in predicate
    assert "pb.user_id = :user_id" in predicate
    assert "1=1" not in predicate


def test_owner_detail_episode_predicate_allows_all_used_episodes():
    predicate = product_service._build_product_detail_episode_visibility_predicate(
        can_read_owner_episodes=True
    )

    assert predicate == "1=1"


def test_product_detail_owner_episode_scope_is_server_authoritative():
    assert product_service._can_read_owner_product_detail_episodes(
        user_id=10,
        current_user_role="author",
        product_owner_user_id=10,
        product_author_id=99,
    )
    assert product_service._can_read_owner_product_detail_episodes(
        user_id=10,
        current_user_role="author",
        product_owner_user_id=99,
        product_author_id=10,
    )
    assert product_service._can_read_owner_product_detail_episodes(
        user_id=10,
        current_user_role="admin",
        product_owner_user_id=99,
        product_author_id=99,
    )
    assert product_service._can_read_owner_product_detail_episodes(
        user_id=10,
        current_user_role="CP",
        product_owner_user_id=99,
        product_author_id=99,
    )
    assert product_service._can_read_owner_product_detail_episodes(
        user_id=10,
        current_user_role="editor",
        product_owner_user_id=99,
        product_author_id=99,
    )
    assert not product_service._can_read_owner_product_detail_episodes(
        user_id=None,
        current_user_role="author",
        product_owner_user_id=10,
        product_author_id=10,
    )
    assert not product_service._can_read_owner_product_detail_episodes(
        user_id=11,
        current_user_role="author",
        product_owner_user_id=10,
        product_author_id=10,
    )


def test_episode_list_query_options_reject_sql_injection_ordering():
    for kwargs in [
        {"order_by": "episodeNo;select sleep(5)", "order_dir": "desc"},
        {"order_by": "episodeNo", "order_dir": "desc;select sleep(5)"},
    ]:
        try:
            product_service._normalize_episode_list_query_options(
                page=1,
                limit=10,
                **kwargs,
            )
        except CustomResponseException as exc:
            assert exc.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        else:
            raise AssertionError("invalid ordering must raise CustomResponseException")


def test_episode_list_query_options_allow_known_ordering_only():
    options = product_service._normalize_episode_list_query_options(
        page=None,
        limit=None,
        order_by="episodeNo",
        order_dir="desc",
    )

    assert options == {
        "page": 1,
        "limit": 10,
        "order_by": "episodeNo",
        "order_dir": "desc",
    }
