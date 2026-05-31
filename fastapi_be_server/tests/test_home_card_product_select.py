import app.services.product.product_service as product_service


def test_home_card_product_select_omits_heavy_detail_joins():
    assert hasattr(product_service, "get_select_fields_and_joins_for_home_card_product")
    query_parts = product_service.get_select_fields_and_joins_for_home_card_product()

    select_fields = query_parts["select_fields"]
    joins = query_parts["joins"]

    assert "p.product_id as productId" in select_fields
    assert "p.title" in select_fields
    assert "cf.file_path as coverImagePath" in select_fields
    assert "episode_stats.latest_episode_id as latestEpisodeId" in select_fields
    assert "episode_stats.first_episode_id as firstEpisodeId" in select_fields

    assert "tb_product_contract_offer" not in joins
    assert "tb_product_order" not in joins
    assert "tb_product_paid_apply" not in joins
    assert "tb_batch_daily_product_count_summary" not in joins
    assert "tb_user_product_usage" not in joins


def test_convert_home_card_product_data_preserves_frontend_shape_defaults():
    assert hasattr(product_service, "convert_home_card_product_data")
    converted = product_service.convert_home_card_product_data(
        {
            "productId": 1,
            "adultYn": "N",
            "title": "테스트 작품",
            "synopsis": "소개",
            "authorNickname": "작가",
            "priceType": "free",
            "paidEpisodeNo": None,
            "singleRegularPrice": 0,
            "singleRentalPrice": 0,
            "seriesRegularPrice": 0,
            "illustratorNickname": "",
            "productType": "free",
            "createdDate": "2026-05-31T00:00:00",
            "updatedDate": "2026-05-31T00:00:00",
            "authorId": 10,
            "keywords": "키워드1|키워드2",
            "primary_genre": "판타지",
            "sub_genre": "현대판타지",
            "current_rank": 3,
            "rank_indicator": 1,
            "coverImagePath": "https://cdn.example/cover.webp",
            "count_hit": 100,
            "count_cp_hit": 2,
            "count_recommend": 4,
            "count_bookmark": 5,
            "hasEpisodeCount": 12,
            "totalOpenEpisodeCount": 11,
            "waitingForFreeStatus": "ing",
            "sixNinePathStatus": None,
            "newReleaseYn": "Y",
            "freeEpisodeTicketCount": 0,
            "authorEventLevelBadgeImagePath": None,
            "authorInterestLevelBadgeImagePath": None,
            "interestEndDate": None,
            "interestStatus": "no_interest",
            "averageWeeklyEpisodes": None,
            "primaryReaderGroup": None,
            "publish_days": None,
            "last_episode_date": "2026-05-31T00:00:00",
            "bookmarkYn": "N",
            "monopoly_yn": "N",
            "contract_yn": "N",
            "status_code": "ongoing",
            "publish_regular_yn": "Y",
            "remainingNotificationCount": 5,
            "latestEpisodeNo": 12,
            "latestEpisodeId": 120,
            "firstEpisodeId": 101,
            "recentReadEpisodeId": None,
            "recentReadEpisodeNo": None,
        }
    )

    assert converted["productId"] == 1
    assert converted["genre"] == ["판타지", "현대판타지"]
    assert converted["keywords"] == ["키워드1", "키워드2"]
    assert converted["rank"] == {"currentRank": 3, "rankIndicator": 1}
    assert converted["image"]["coverImagePath"] == "https://cdn.example/cover.webp"
    assert converted["badge"]["newReleaseYn"] == "Y"
    assert converted["badge"]["waitingForFreeYn"] == "Y"
    assert converted["trendindex"]["hasEpisodeCount"] == 12
    assert converted["trendindex"]["cpHitCount"] == 2
    assert converted["properties"]["latestEpisodeDate"] == "2026-05-31T00:00:00"
    assert converted["contract"]["advancePayment"] == 0
    assert converted["state"]["ongoingState"] == "ongoing"
    assert converted["remainingNotificationCount"] == 5
    assert converted["latestEpisodeId"] == 120
    assert converted["firstEpisodeId"] == 101
