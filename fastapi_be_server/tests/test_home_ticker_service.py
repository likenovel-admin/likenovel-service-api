from datetime import datetime, timedelta
import asyncio

from app.services.product import home_ticker_service as service


FRESHNESS_ENUM = {
    "weekly",
    "near_real_time",
    "ranking_snapshot",
    "metric_snapshot",
    "trend_snapshot",
    "fallback",
}
INTERNAL_METRIC_TERMS = ("연독률", "재유입", "전환율")


def _assert_public_copy_has_no_internal_metric_terms(copy: str):
    for term in INTERNAL_METRIC_TERMS:
        assert term not in copy


def test_paid_conversion_copy_uses_weekly_author_count():
    item = service.build_paid_conversion_summary_item(3)

    assert item["message"] == "이번 주 유료전환 작가님 3명 축하드립니다."
    assert item["productId"] is None
    assert item["freshness"] == "weekly"


def test_paid_conversion_copy_is_hidden_when_weekly_author_count_is_zero():
    assert service.build_paid_conversion_summary_item(0) is None


def test_paid_conversion_query_uses_weekly_paid_new_event_product_authors():
    week_start, week_end = service.get_week_window_kst(datetime(2026, 6, 10, 12, 30))
    query, params = service.build_paid_conversion_summary_query(week_start, week_end, "N")

    assert week_start == datetime(2026, 6, 8)
    assert week_end == datetime(2026, 6, 15)
    assert "tb_event_v2" in query
    assert "e.product_ids" in query
    assert "JSON_TABLE" in query
    assert "e.show_yn_product = 'Y'" in query
    assert "e.start_date >= :week_start" in query
    assert "e.start_date < :week_end" in query
    assert "e.end_date > NOW()" in query
    assert "e.title REGEXP :event_title_pattern" in query
    assert "COUNT(DISTINCT p.author_id)" in query
    assert "p.paid_open_date" not in query
    assert "CONCAT('이번 주 유료전환 작가님 ', COUNT(DISTINCT p.author_id), '명 축하드립니다.')" in query
    assert "HAVING COUNT(DISTINCT p.author_id) > 0" in query
    assert "p.ratings_code = 'all'" in query
    assert params == {
        "week_start": week_start,
        "week_end": week_end,
        "event_title_pattern": service.WEEKLY_PAID_NEW_EVENT_TITLE_PATTERN,
    }


def test_internal_metric_terms_are_blocked():
    assert (
        service.build_ticker_item(
            item_type="reader_momentum",
            message="연독률이 오른 작품입니다.",
            priority=10,
        )
        is None
    )
    assert (
        service.build_ticker_item(
            item_type="reader_momentum",
            message="재유입 흐름이 있는 작품입니다.",
            priority=10,
        )
        is None
    )
    assert (
        service.build_ticker_item(
            item_type="reader_momentum",
            message="전환율이 오른 작품입니다.",
            priority=10,
        )
        is None
    )


def test_reader_facing_term_is_accepted():
    item = service.build_ticker_item(
        item_type="reader_momentum",
        message="독자 반응이 이어지고 있습니다.",
        priority=10,
        product_id=123,
    )

    assert item == {
        "type": "reader_momentum",
        "message": "독자 반응이 이어지고 있습니다.",
        "productId": 123,
        "targetType": "product",
        "targetId": 123,
        "priority": 10,
        "freshness": "metric_snapshot",
    }


def test_recent_episode_query_contract():
    query, params = service.build_recent_episode_query("Y")

    assert "tb_product_episode e" in query
    assert "ELSE CONCAT(p.author_name, ' 작가님이 <" in query
    assert ">의 신규 회차를 업로드했습니다." in query
    assert "THEN CONCAT('작가님이 <" in query
    assert "e.open_yn = 'Y'" in query
    assert "e.use_yn = 'Y'" in query
    assert "e.publish_reserve_date <= NOW()" in query
    assert "DATE_SUB(NOW(), INTERVAL 2 HOUR)" in query
    assert "'near_real_time' AS freshness" in query
    assert "LIMIT 5" in query
    assert "p.ratings_code = 'all'" not in query
    _assert_public_copy_has_no_internal_metric_terms(query)
    assert params == {}


def test_popular_free_top_query_contract():
    query, params = service.build_popular_free_top_query("N")

    assert "tb_product_rank_area r" in query
    assert "area_code = 'freeSerialTop'" in query
    assert "ELSE CONCAT(p.author_name, ' 작가님의 <" in query
    assert ">이 인기무료 TOP 1위에 올랐습니다." in query
    assert "THEN CONCAT('작가님의 <" in query
    assert "r.current_rank = 1" in query
    assert "p.price_type = 'free'" in query
    assert "p.status_code = 'ongoing'" in query
    assert "MAX(created_date)" in query
    assert "basis_at" not in query
    assert "'ranking_snapshot' AS freshness" in query
    assert "p.ratings_code = 'all'" in query
    _assert_public_copy_has_no_internal_metric_terms(query)
    assert params == {}


def test_reader_momentum_query_contract():
    query, params = service.build_reader_momentum_query("N")

    assert "tb_product_trend_index pti" in query
    assert "tb_product_count_variance pcv" not in query
    assert "<', p.title, '>을 독자들이 이어 읽고 있습니다." in query
    assert "pti.reading_rate >= :min_reading_rate" in query
    assert "p.count_hit >= :min_count_hit" in query
    assert "ORDER BY pti.reading_rate DESC, p.count_hit DESC, p.product_id DESC" in query
    assert "'metric_snapshot' AS freshness" in query
    _assert_public_copy_has_no_internal_metric_terms(query)
    assert params == {"min_reading_rate": 50, "min_count_hit": 30}


def test_new_product_query_contract():
    query, params = service.build_new_product_query("N")

    assert "ELSE CONCAT(p.author_name, ' 작가님의 신규작 <" in query
    assert ">이 등록되었습니다." in query
    assert "THEN CONCAT('작가님의 신규작 <" in query
    assert "p.created_date >= DATE_SUB(NOW(), INTERVAL 24 HOUR)" in query
    assert "ORDER BY p.created_date DESC, p.product_id DESC" in query
    assert "'near_real_time' AS freshness" in query
    assert "LIMIT 3" in query
    assert "p.ratings_code = 'all'" in query
    _assert_public_copy_has_no_internal_metric_terms(query)
    assert params == {}


def test_new_notice_query_contract():
    query, params = service.build_new_notice_query()

    assert "tb_notice n" in query
    assert "'new_notice' AS itemType" in query
    assert "NULL AS productId" in query
    assert "'notice' AS targetType" in query
    assert "n.id AS targetId" in query
    assert "'새로운 공지사항이 등록되었습니다' AS message" in query
    assert "n.use_yn = 'Y'" in query
    assert "n.created_date >= DATE_SUB(NOW(), INTERVAL 24 HOUR)" in query
    assert "ORDER BY n.created_date DESC, n.id DESC" in query
    assert "'near_real_time' AS freshness" in query
    assert "LIMIT 1" in query
    _assert_public_copy_has_no_internal_metric_terms(query)
    assert params == {}


def test_material_trend_query_contract():
    query, params = service.build_material_trend_query("N")

    assert "tb_product_ai_metadata m" in query
    assert "m.protagonist_material_tags" in query
    assert "NULL AS productId" in query
    assert "tb_product_count_variance pcv" not in query
    assert "materials.materialTag AS dedupeKey" in query
    assert "최근 ', materials.materialTag, ' 소재 작품이 주목받고 있습니다." in query
    assert "JSON_VALID(m.protagonist_material_tags)" in query
    assert "HAVING COUNT(DISTINCT p.product_id) >= :min_product_count" in query
    assert "'trend_snapshot' AS freshness" in query
    assert "LIMIT :limit_count" in query
    _assert_public_copy_has_no_internal_metric_terms(query)
    assert params == {
        "min_count_hit": 30,
        "min_product_count": 2,
        "limit_count": 3,
    }


def test_response_keeps_multiple_material_trend_messages():
    rows = [
        {
            "itemType": "material_trend",
            "productId": None,
            "dedupeKey": "마법",
            "message": "최근 마법 소재 작품이 주목받고 있습니다.",
            "priority": 50,
            "freshness": "trend_snapshot",
        },
        {
            "itemType": "material_trend",
            "productId": None,
            "dedupeKey": "시스템",
            "message": "최근 시스템 소재 작품이 주목받고 있습니다.",
            "priority": 50,
            "freshness": "trend_snapshot",
        },
    ]

    response = service.build_home_ticker_response(rows, now=datetime(2026, 6, 8))

    assert [item["message"] for item in response["items"]] == [
        "최근 마법 소재 작품이 주목받고 있습니다.",
        "최근 시스템 소재 작품이 주목받고 있습니다.",
    ]
    for item in response["items"]:
        assert set(item.keys()) == {
            "type",
            "message",
            "productId",
            "targetType",
            "targetId",
            "priority",
            "freshness",
        }


def test_response_sorts_by_priority_deduplicates_limits_and_falls_back():
    rows = [
        {
            "itemType": "new_product",
            "productId": 1,
            "message": "낮은 우선순위",
            "priority": 1,
            "freshness": "near_real_time",
        },
        {
            "itemType": "new_product",
            "productId": 1,
            "message": "중복",
            "priority": 99,
            "freshness": "near_real_time",
        },
        {
            "itemType": "reader_momentum",
            "productId": 2,
            "message": "높은 우선순위",
            "priority": 10,
            "freshness": "metric_snapshot",
        },
        {
            "itemType": "new_notice",
            "productId": None,
            "targetType": "notice",
            "targetId": 42,
            "message": "새로운 공지사항이 등록되었습니다",
            "priority": 9,
            "freshness": "near_real_time",
        },
    ]

    response = service.build_home_ticker_response(rows, now=datetime(2026, 6, 8))
    items = response["items"]

    assert [item["message"] for item in items] == [
        "중복",
        "높은 우선순위",
        "새로운 공지사항이 등록되었습니다",
    ]
    assert items[2]["targetType"] == "notice"
    assert items[2]["targetId"] == 42
    assert response["asOf"] == "2026-06-08T00:00:00"
    assert response["refreshAfterSeconds"] == service.HOME_TICKER_REFRESH_AFTER_SECONDS
    assert response["rotateEveryMs"] == service.HOME_TICKER_ROTATE_EVERY_MS
    assert set(response.keys()) == {
        "asOf",
        "refreshAfterSeconds",
        "rotateEveryMs",
        "items",
    }
    for item in items:
        assert set(item.keys()) == {
            "type",
            "message",
            "productId",
            "targetType",
            "targetId",
            "priority",
            "freshness",
        }
        assert item["freshness"] in FRESHNESS_ENUM

    fallback = service.build_home_ticker_response([], now=datetime(2026, 6, 8))
    assert fallback["items"] == [
        {
            "type": "fallback",
            "message": "오늘도 새로운 이야기가 라이크노벨에서 독자를 만나고 있습니다.",
            "productId": None,
            "targetType": "none",
            "targetId": None,
            "priority": 0,
            "freshness": "fallback",
        }
    ]


def test_response_limits_to_home_ticker_limit():
    rows = [
        {
            "itemType": "new_product",
            "productId": product_id,
            "message": f"작품 {product_id}",
            "priority": product_id,
            "freshness": "near_real_time",
        }
        for product_id in range(service.HOME_TICKER_LIMIT + 3)
    ]

    response = service.build_home_ticker_response(rows, now=datetime(2026, 6, 8))

    assert len(response["items"]) == service.HOME_TICKER_LIMIT


def test_cache_helpers_return_deep_copy():
    service.reset_home_ticker_cache_for_tests()
    response = {
        "items": [
            {
                "type": "fallback",
                "message": "테스트",
                "productId": None,
                "priority": 0,
                "freshness": "fallback",
            }
        ],
    }

    service.set_home_ticker_cache_for_tests(
        "N", response, expires_at=(datetime.now() + timedelta(days=1)).timestamp()
    )
    cached = service.get_cached_home_ticker("N")
    cached["items"][0]["message"] = "변경"

    assert service.get_cached_home_ticker("N")["items"][0]["message"] == "테스트"


def test_expired_cache_returns_none():
    service.reset_home_ticker_cache_for_tests()
    service.set_home_ticker_cache_for_tests(
        "N",
        {"items": []},
        expires_at=(datetime.now() - timedelta(seconds=1)).timestamp(),
    )

    assert service.get_cached_home_ticker("N") is None


def test_get_home_ticker_uses_cache_without_db_execute():
    service.reset_home_ticker_cache_for_tests()
    expected = {
        "items": [
            {
                "type": "fallback",
                "message": "테스트",
                "productId": None,
                "priority": 0,
                "freshness": "fallback",
            }
        ]
    }
    service.set_home_ticker_cache_for_tests(
        "N", expected, expires_at=(datetime.now() + timedelta(days=1)).timestamp()
    )

    class NoExecuteDb:
        async def execute(self, *args, **kwargs):
            raise AssertionError("cached response should not execute SQL")

    result = asyncio.run(service.get_home_ticker("N", NoExecuteDb()))

    assert result == expected
