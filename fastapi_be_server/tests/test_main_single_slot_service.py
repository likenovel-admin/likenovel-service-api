from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_main_single_slot_migration_creates_schedulable_slot_table():
    migration = _read(ROOT / "dist/init/103-create-main-single-slot.sql")

    assert "CREATE TABLE IF NOT EXISTS tb_main_single_slot" in migration
    assert "slot_key" in migration
    assert "slot_order" in migration
    assert "product_id" in migration
    assert "summary_text" in migration
    assert "publish_start_at" in migration
    assert "publish_end_at" in migration
    assert "cancelled_at" in migration
    assert "idx_main_single_slot_active" in migration


def test_public_main_single_slot_query_uses_latest_active_entry_per_slot():
    from app.services.product import main_single_slot_service

    query = main_single_slot_service.build_active_main_single_slots_query()

    assert "ROW_NUMBER() OVER" in query
    assert "PARTITION BY mss.slot_key" in query
    assert "ORDER BY mss.publish_start_at DESC, mss.single_slot_id DESC" in query
    assert "active_slots.rn = 1" in query
    assert "mss.cancelled_at IS NULL" in query
    assert "mss.publish_start_at <= NOW()" in query
    assert "(mss.publish_end_at IS NULL OR mss.publish_end_at > NOW())" in query


def test_public_main_single_slot_query_filters_only_visible_products_with_open_episode():
    from app.services.product import main_single_slot_service

    query = main_single_slot_service.build_active_main_single_slots_query()

    assert "p.open_yn = 'Y'" in query
    assert "COALESCE(p.blind_yn, 'N') = 'N'" in query
    assert "COALESCE(episode_stats.open_episode_count, 0) > 0" in query
    assert "(:adult_yn = 'Y' OR p.ratings_code != 'adult')" in query


def test_main_single_slot_product_payload_preserves_home_card_shape_and_slot_metadata():
    from app.services.product import main_single_slot_service

    converted = main_single_slot_service.convert_main_single_slot_row(
        {
            "singleSlotId": 10,
            "slotKey": "before_paid_top",
            "slotName": "유료 Top 이전",
            "slotOrder": 1,
            "summaryText": "배신당해 죽었는데,\n눈 떠 보니 IMF 한복판.",
            "productId": 1,
            "adultYn": "N",
            "title": "재벌3세의 AI가 너무 유능함",
            "synopsis": "작품 소개",
            "authorNickname": "작가",
            "priceType": "paid",
            "paidEpisodeNo": 25,
            "singleRegularPrice": 0,
            "singleRentalPrice": 0,
            "seriesRegularPrice": 100,
            "illustratorNickname": "",
            "productType": "normal",
            "createdDate": "2026-06-02T00:00:00",
            "updatedDate": "2026-06-02T00:00:00",
            "authorId": 7,
            "keywords": "키워드1|키워드2",
            "primary_genre": "판타지",
            "sub_genre": "현대판타지",
            "current_rank": None,
            "rank_indicator": None,
            "coverImagePath": "https://cdn.example/cover.webp",
            "count_hit": 1,
            "count_cp_hit": 0,
            "count_recommend": 0,
            "count_bookmark": 0,
            "hasEpisodeCount": 12,
            "totalOpenEpisodeCount": 12,
            "waitingForFreeStatus": None,
            "sixNinePathStatus": None,
            "newReleaseYn": "N",
            "freeEpisodeTicketCount": 0,
            "authorEventLevelBadgeImagePath": None,
            "authorInterestLevelBadgeImagePath": None,
            "interestEndDate": None,
            "interestStatus": "no_interest",
            "readThroughRate": 0,
            "readThroughIndicator": 0,
            "cpHitIndicator": 0,
            "totalInterestCount": 0,
            "totalInterestIndicator": 0,
            "interestSustainCount": 0,
            "interestSustainIndicator": 0,
            "interestLossCount": 0,
            "interestLossIndicator": 0,
            "hitIndicator": 0,
            "recommendIndicator": 0,
            "bookmarkIndicator": 0,
            "averageWeeklyEpisodes": 0,
            "primaryReaderGroup": None,
            "readedEpisodeCount": 0,
            "advancePayment": 0,
            "totalSales": 0,
            "publish_days": "mon,tue",
            "last_episode_date": "2026-06-02T00:00:00",
            "bookmarkYn": "N",
            "monopoly_yn": "N",
            "contract_yn": "N",
            "status_code": "ongoing",
            "publish_regular_yn": "Y",
            "offerCount": 0,
            "offerId": None,
            "offerDate": None,
            "offerAdvancePayment": 0,
            "settlementRatioSnippet": None,
            "offerDecisionState": "review",
            "convertToPaidState": "not_applied",
            "canApplyForPaid": "Y",
            "remainingNotificationCount": 5,
            "latestEpisodeNo": 12,
            "latestEpisodeId": 120,
            "firstEpisodeId": 101,
            "recentReadEpisodeId": None,
            "recentReadEpisodeNo": None,
        }
    )

    assert converted["slotKey"] == "before_paid_top"
    assert converted["slotName"] == "유료 Top 이전"
    assert converted["slotOrder"] == 1
    assert converted["summaryText"].startswith("배신당해")
    assert converted["product"]["productId"] == 1
    assert converted["product"]["title"] == "재벌3세의 AI가 너무 유능함"
    assert converted["product"]["image"]["coverImagePath"] == "https://cdn.example/cover.webp"
    assert converted["product"]["trendindex"]["hasEpisodeCount"] == 12


def test_publish_now_query_closes_current_active_slot_before_insert():
    from app.services.product import main_single_slot_service

    query = main_single_slot_service.build_publish_now_close_query()

    assert "UPDATE tb_main_single_slot" in query
    assert "SET publish_end_at = NOW()" in query
    assert "slot_key = :slot_key" in query
    assert "cancelled_at IS NULL" in query
    assert "publish_start_at <= NOW()" in query
    assert "(publish_end_at IS NULL OR publish_end_at > NOW())" in query


def test_update_main_single_slot_query_updates_existing_uncancelled_queue_only():
    from app.services.product import main_single_slot_service

    query = main_single_slot_service.build_update_main_single_slot_query()

    assert "UPDATE tb_main_single_slot" in query
    assert "slot_key = :slot_key" in query
    assert "slot_name = :slot_name" in query
    assert "slot_order = :slot_order" in query
    assert "product_id = :product_id" in query
    assert "summary_text = :summary_text" in query
    assert "publish_start_at = COALESCE(:publish_start_at, publish_start_at)" in query
    assert "publish_end_at = :publish_end_at" in query
    assert "single_slot_id = :single_slot_id" in query
    assert "cancelled_at IS NULL" in query


def test_main_single_slot_request_schemas_require_product_and_summary():
    from app.schemas.admin import PostMainSingleSlotReqBody

    req = PostMainSingleSlotReqBody(
        slot_key="before_paid_top",
        slot_name="유료 Top 이전",
        slot_order=1,
        product_id=1117,
        summary_text="돌아온 지구는 많은 것이 달라져 있었다.",
        publish_start_at="2026-06-02T12:00:00+09:00",
        publish_end_at="",
    )

    assert req.publish_end_at is None
    assert req.slot_order == 1

    with pytest.raises(ValueError):
        PostMainSingleSlotReqBody(
            slot_key="before_paid_top",
            slot_name="유료 Top 이전",
            slot_order=1,
            product_id=0,
            summary_text="",
            publish_start_at="2026-06-02T12:00:00+09:00",
        )


def test_main_single_slot_update_request_schema_allows_preserving_start_date():
    from app.schemas.admin import PutMainSingleSlotReqBody

    req = PutMainSingleSlotReqBody(
        slot_key="before_paid_top",
        slot_name="유료 Top 이전",
        slot_order=1,
        product_id=1117,
        summary_text="오타만 수정합니다.",
        publish_start_at=None,
        publish_end_at="",
    )

    assert req.publish_start_at is None
    assert req.publish_end_at is None

    req_with_end = PutMainSingleSlotReqBody(
        slot_key="before_paid_top",
        slot_name="유료 Top 이전",
        slot_order=1,
        product_id=1117,
        summary_text="오타만 수정합니다.",
        publish_start_at=None,
        publish_end_at="2026-06-03T12:00:00+09:00",
    )

    assert req_with_end.publish_start_at is None
    assert req_with_end.publish_end_at is not None


def test_main_single_slot_request_schema_compares_mixed_timezone_datetimes():
    from app.schemas.admin import PostMainSingleSlotReqBody

    req = PostMainSingleSlotReqBody(
        slot_key="before_paid_top",
        slot_name="유료 Top 이전",
        slot_order=1,
        product_id=1117,
        summary_text="돌아온 지구는 많은 것이 달라져 있었다.",
        publish_start_at="2026-06-02T12:00:00+09:00",
        publish_end_at="2026-06-03T12:00:00",
    )

    assert req.publish_end_at is not None

    with pytest.raises(ValueError):
        PostMainSingleSlotReqBody(
            slot_key="before_paid_top",
            slot_name="유료 Top 이전",
            slot_order=1,
            product_id=1117,
            summary_text="돌아온 지구는 많은 것이 달라져 있었다.",
            publish_start_at="2026-06-02T12:00:00+09:00",
            publish_end_at="2026-06-02T12:00:00",
        )
