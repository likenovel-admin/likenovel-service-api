from datetime import datetime

from app.services.product import rising_pick_service as service


INTERNAL_METRIC_TERMS = ("연독률", "재유입", "전환율")


def _row(product_id, *, age_days=40, hours_since_episode=10, rank_gain=5, hits=20):
    return {
        "productId": product_id,
        "title": f"작품{product_id}",
        "authorName": f"작가{product_id}",
        "coverImagePath": f"cover/{product_id}.webp",
        "productAgeDays": age_days,
        "hoursSinceEpisode": hours_since_episode,
        "rankGain": rank_gain,
        "recentHits": hits,
    }


def test_query_excludes_top_ranks_and_requires_rise_signal():
    query, params = service.build_rising_pick_query("N")

    assert "cur.rank_no > :exclude_top_rank" in query
    assert "cur.recent_24h_count_hit >= :min_recent_hits" in query
    assert "(prev.rank_no - cur.rank_no) >= :min_rank_gain" in query
    assert "OR prev.product_id IS NULL" in query
    assert "p.price_type = 'free'" in query
    assert "p.status_code = 'ongoing'" in query
    assert "p.ratings_code = 'all'" in query
    assert params["exclude_top_rank"] == 10
    assert params["min_recent_hits"] == 5
    assert params["min_rank_gain"] == 3


def test_query_includes_adult_products_when_adult_yn_is_yes():
    query, _ = service.build_rising_pick_query("Y")

    assert "p.ratings_code = 'all'" not in query


def test_classify_new_work_takes_priority_over_recent_episode():
    assert service.classify_rising_type(product_age_days=3, hours_since_episode=2) == "new_work"


def test_classify_comeback_requires_old_work_without_recent_episode():
    assert service.classify_rising_type(product_age_days=60, hours_since_episode=200) == "comeback"
    assert service.classify_rising_type(product_age_days=60, hours_since_episode=10) == "fresh_episode"


def test_classify_falls_back_to_rising_when_episode_time_is_unknown_and_work_is_young():
    assert service.classify_rising_type(product_age_days=20, hours_since_episode=None) == "rising"


def test_slot_is_hidden_when_candidate_pool_is_smaller_than_display_count():
    rows = [_row(1), _row(2)]

    assert service.select_rising_picks(rows, datetime(2026, 8, 28, 13, 30)) == []


def test_selection_is_stable_within_the_same_three_hour_bucket():
    rows = [_row(index) for index in range(1, 9)]

    first = service.select_rising_picks(rows, datetime(2026, 8, 28, 12, 30))
    second = service.select_rising_picks(rows, datetime(2026, 8, 28, 14, 30))

    assert [item["productId"] for item in first] == [item["productId"] for item in second]
    assert len(first) == service.RISING_PICK_DISPLAY_COUNT


def test_selection_changes_when_the_bucket_advances():
    rows = [_row(index) for index in range(1, 9)]

    current = service.select_rising_picks(rows, datetime(2026, 8, 28, 13, 30))
    following = service.select_rising_picks(rows, datetime(2026, 8, 28, 16, 30))

    assert [item["productId"] for item in current] != [
        item["productId"] for item in following
    ]


def test_response_exposes_comment_without_rise_numbers():
    rows = [_row(index) for index in range(1, 6)]

    response = service.build_rising_pick_response(rows, now=datetime(2026, 8, 28, 13, 30))

    assert response["items"]
    for item in response["items"]:
        assert item["comment"] == service._COMMENT_TEMPLATES[item["risingType"]]
        assert "rankGain" not in item
        assert "recentHits" not in item
        assert str(_row(1)["recentHits"]) not in item["comment"]
        for term in INTERNAL_METRIC_TERMS:
            assert term not in item["comment"]


def test_comment_templates_fit_mobile_single_card_width():
    for comment in service._COMMENT_TEMPLATES.values():
        assert len(comment) <= 22
