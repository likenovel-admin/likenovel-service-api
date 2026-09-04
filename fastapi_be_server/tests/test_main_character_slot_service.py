import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _row(
    scope_key="character:adelite",
    *,
    display_name="아델리트",
    aliases=None,
    public_chat_eligible=True,
    public_slot_eligible=True,
    safety_status="pass",
    work_role="main_protagonist",
    distinct_episode_count=10,
    voice_evidence_count=10,
    example_count=5,
    scene_count=5,
):
    return {
        "scopeKey": scope_key,
        "exampleCount": example_count,
        "sceneCount": scene_count,
        "summaryText": json.dumps(
            {
                "canonical_character_key": scope_key,
                "display_name": display_name,
                "aliases": aliases or [display_name],
                "public_chat_eligible": public_chat_eligible,
                "public_slot_eligible": public_slot_eligible,
                "display_safety": {"status": safety_status},
                "work_role": work_role,
                "distinct_episode_count": distinct_episode_count,
                "voice_evidence_count": voice_evidence_count,
            },
            ensure_ascii=False,
        ),
    }


def test_main_character_slot_roster_accepts_only_chat_and_slot_eligible_characters():
    from app.services.product.main_character_slot_service import (
        extract_eligible_main_character_roster,
    )

    roster = extract_eligible_main_character_roster(
        [
            _row(aliases=["아델리트", "공녀", "공녀"]),
            _row(
                "character:follower",
                display_name="추종자",
                work_role="major_character",
                public_slot_eligible=False,
            ),
            _row(
                "character:ally",
                display_name="동료",
                work_role="major_character",
                public_chat_eligible=False,
                public_slot_eligible=True,
            ),
            _row("character:false", public_slot_eligible=False),
            _row("character:string", public_slot_eligible="true"),
            _row("character:missing", public_slot_eligible=None),
            _row("character:fail", safety_status="fail"),
            _row("character:review", safety_status="review"),
        ]
    )

    assert roster == [
        {
            "scopeKey": "character:adelite",
            "displayName": "아델리트",
            "aliases": ["아델리트", "공녀"],
            "distinctEpisodeCount": 10,
            "exampleCount": 5,
            "sceneCount": 5,
            "chatQuality": "good",
            "qualityReason": "회차·RP 예시·장면 데이터 충분",
        },
    ]


def test_main_character_slot_roster_missing_v3_is_empty_and_duplicate_scope_is_removed():
    from app.services.product.main_character_slot_service import (
        extract_eligible_main_character_roster,
    )

    assert extract_eligible_main_character_roster([]) == []
    assert extract_eligible_main_character_roster([_row(), _row(display_name="중복")]) == [
        {
            "scopeKey": "character:adelite",
            "displayName": "아델리트",
            "aliases": ["아델리트"],
            "distinctEpisodeCount": 10,
            "exampleCount": 5,
            "sceneCount": 5,
            "chatQuality": "good",
            "qualityReason": "회차·RP 예시·장면 데이터 충분",
        }
    ]


def test_main_character_slot_roster_keeps_only_top_two_characters():
    from app.services.product.main_character_slot_service import (
        extract_eligible_main_character_roster,
    )

    roster = extract_eligible_main_character_roster(
        [
            _row(
                "character:minor",
                display_name="조연",
                work_role="major_character",
                distinct_episode_count=4,
                voice_evidence_count=3,
            ),
            _row(
                "character:lead",
                display_name="주인공",
                work_role="main_protagonist",
                distinct_episode_count=15,
                voice_evidence_count=8,
            ),
            _row(
                "character:major",
                display_name="주요 인물",
                work_role="major_character",
                distinct_episode_count=12,
                voice_evidence_count=7,
            ),
        ]
    )

    assert [item["scopeKey"] for item in roster] == [
        "character:lead",
        "character:major",
    ]


def test_chat_quality_is_good_when_both_selectable_characters_have_rich_assets():
    from app.services.product.main_character_slot_service import (
        build_main_character_chat_quality_by_product,
    )

    candidates = [
        {
            **_row(
                "character:lead",
                display_name="주인공",
                distinct_episode_count=20,
            ),
            "productId": 1192,
            "exampleCount": 5,
            "sceneCount": 5,
        },
        {
            **_row(
                "character:major",
                display_name="주요 인물",
                work_role="major_character",
                distinct_episode_count=12,
            ),
            "productId": 1192,
            "exampleCount": 4,
            "sceneCount": 5,
        },
        {
            **_row(
                "character:third",
                display_name="세 번째 인물",
                work_role="major_character",
                distinct_episode_count=2,
            ),
            "productId": 1192,
            "exampleCount": 1,
            "sceneCount": 0,
        },
    ]

    assert build_main_character_chat_quality_by_product(candidates) == {
        1192: "good"
    }


def test_chat_quality_is_insufficient_when_a_character_has_fewer_than_five_scenes():
    from app.services.product.main_character_slot_service import (
        build_main_character_chat_quality_by_product,
    )

    candidates = [
        {
            **_row(distinct_episode_count=20),
            "productId": 1170,
            "exampleCount": 5,
            "sceneCount": 4,
        }
    ]

    assert build_main_character_chat_quality_by_product(candidates) == {
        1170: "insufficient"
    }


def test_chat_quality_is_insufficient_without_a_usable_character_scene():
    from app.services.product.main_character_slot_service import (
        build_main_character_chat_quality_by_product,
    )

    candidates = [
        {
            **_row("character:ann", display_name="안", distinct_episode_count=20),
            "productId": 1122,
            "exampleCount": 5,
            "sceneCount": 0,
        }
    ]

    assert build_main_character_chat_quality_by_product(candidates) == {
        1122: "insufficient"
    }


def test_chat_quality_ignores_inventory_without_a_selectable_display_name():
    from app.services.product.main_character_slot_service import (
        build_main_character_chat_quality_by_product,
    )

    candidates = [
        {
            **_row(distinct_episode_count=20),
            "productId": 1122,
            "exampleCount": 5,
            "sceneCount": 5,
        },
        {
            **_row("character:broken", display_name=""),
            "productId": 1122,
            "exampleCount": 0,
            "sceneCount": 0,
        },
    ]

    assert build_main_character_chat_quality_by_product(candidates) == {
        1122: "good"
    }


def test_main_character_slot_migration_and_model_follow_project_conventions():
    migration = (ROOT / "dist/init/106-create-main-character-slot.sql").read_text(
        encoding="utf-8"
    )

    assert "CREATE TABLE IF NOT EXISTS tb_main_character_slot" in migration
    for column in (
        "product_id",
        "character_scope_key",
        "character_name",
        "character_image_file_id",
        "card_order",
        "publish_start_date",
        "publish_end_date",
        "use_yn",
        "deleted_yn",
        "created_id",
        "created_date",
        "updated_id",
        "updated_date",
    ):
        assert column in migration
    assert "idx_main_character_slot_public" in migration
    assert "idx_main_character_slot_product" in migration

    from app.models.product import MainCharacterSlot

    assert MainCharacterSlot.__tablename__ == "tb_main_character_slot"


def test_main_character_slot_config_migration_defaults_to_auto_mode():
    migration = (
        ROOT / "dist/init/108-create-main-character-slot-config.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS tb_main_character_slot_config" in migration
    assert "display_mode VARCHAR(10) NOT NULL DEFAULT 'auto'" in migration
    assert "INSERT INTO tb_main_character_slot_config" in migration
    assert "SELECT 1, 'auto'" in migration


def test_practical_rp_assets_require_nonempty_examples_without_episode_window():
    from app.services.product.main_character_slot_service import (
        _chat_ready_rp_assets_predicate,
    )

    query = _chat_ready_rp_assets_predicate("inventory")

    assert "summary_type = 'character_rp_profile'" in query
    assert "summary_type = 'character_rp_examples'" in query
    assert "$.personality_core" in query
    assert "$.speech_style.tone" in query
    assert "$.speech_style.formality" in query
    assert "$.speech_style.sentence_length" in query
    assert "JSON_LENGTH(JSON_EXTRACT(" in query
    assert ")) >= 1" in query
    assert "eligible_rp_example.episode_no BETWEEN 0 AND 1" not in query
    assert "FROM JSON_TABLE" not in query


def test_public_character_role_normalization_is_strict_and_fail_closed():
    from app.services.product.main_character_slot_service import (
        _extract_public_character_role,
    )

    assert (
        _extract_public_character_role('{"work_role":"main_protagonist"}')
        == "main_protagonist"
    )
    assert (
        _extract_public_character_role('{"work_role":"major_character"}')
        == "major_character"
    )
    assert (
        _extract_public_character_role(
            '{"work_role":"unknown","is_protagonist":true}'
        )
        == "main_protagonist"
    )
    assert _extract_public_character_role('{"work_role":"unknown"}') is None
    assert _extract_public_character_role('{"work_role":"supporting"}') is None
    assert _extract_public_character_role("{}") is None


def test_public_main_character_slot_query_filters_current_cards_and_stably_orders_all():
    from app.services.product.main_character_slot_service import (
        build_public_main_character_slots_query,
    )

    query = build_public_main_character_slots_query()
    normalized_query = " ".join(query.split())

    assert "mcs.use_yn = 'Y'" in query
    assert "mcs.deleted_yn = 'N'" in query
    assert "mcs.publish_start_date <= NOW()" in query
    assert "(mcs.publish_end_date IS NULL OR mcs.publish_end_date > NOW())" in query
    assert "p.open_yn = 'Y'" in query
    assert "COALESCE(p.blind_yn, 'N') = 'N'" in query
    assert "COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'" in query
    assert "p.status_code = 'ongoing'" in query
    assert ">= 15" in normalized_query
    assert "MIN(COALESCE(" in query
    assert "pe.open_changed_date" in query
    assert ">= '2026-03-01 00:00:00'" in query
    assert "(:adult_yn = 'Y' OR p.ratings_code != 'adult')" in query
    assert "HAVING COUNT(*)" in query
    assert "FROM tb_product_episode pe" in query
    assert "FROM tb_story_agent_context_summary inventory" in query
    assert "LEFT JOIN tb_story_agent_context_product sacp" in query
    assert "COALESCE(sacp.ready_episode_count, 0)" in query
    assert "AS syncedLatestEpisodeNo" in query
    assert "SELECT MAX(public_episode.episode_no)" in query
    assert "inventory.scope_key = mcs.character_scope_key" in query
    assert "inventory.summary_type = 'character_inventory_v3'" in query
    assert "'$.distinct_episode_count'" in query
    assert "AS UNSIGNED) >= 5" in normalized_query
    assert "$.work_role" in query
    assert "'main_protagonist', 'major_character'" in query
    assert "$.is_protagonist" in query
    assert query.index("$.work_role") < query.index("LIMIT 12")
    assert "latest_inventory.summary_text" in query
    assert "AS _inventorySummaryText" in query
    assert "ORDER BY latest_inventory.summary_id DESC" in query
    assert "profile.scope_key" in query
    assert "examples.scope_key" in query
    assert "eligible_rp_example.episode_no BETWEEN 0 AND 1" not in query
    assert "summary_type = 'episode_scene_extraction'" not in query
    assert "eligible_scene.episode_to = 1" not in query
    assert "eligible_episode_summary.episode_to = 1" not in query
    assert "FROM tb_product_episode eligible_episode" not in query
    assert "tb_story_agent_context_doc eligible_doc" not in query
    assert "tb_story_agent_context_chunk eligible_chunk" not in query
    assert "eligible_episode_summary.scope_key" not in query
    assert "episode_title" not in query
    assert "AS fullReady" not in query
    assert "AS readinessCoverageRatio" not in query
    assert "q.group_type = 'character'" in query
    assert "ORDER BY mcs.card_order ASC, mcs.main_character_slot_id ASC" in query
    assert query.rstrip().endswith("LIMIT 12")
    assert "ROW_NUMBER()" not in query


def test_public_character_catalog_product_query_only_applies_product_gate():
    from app.services.product.main_character_slot_service import (
        build_public_character_catalog_query,
    )

    query = build_public_character_catalog_query()
    normalized_query = " ".join(query.split())

    assert "FROM tb_product p" in query
    assert "COUNT(DISTINCT public_episode.episode_id)" in query
    assert ">= 15" in normalized_query
    assert "status_code = 'ongoing'" not in query
    assert "2026-03-01" not in query
    assert "AS _chatTotalEpisodeCount" in query
    assert "tb_story_agent_context_summary" not in query
    assert "tb_main_character_slot" not in query
    bounded_query = build_public_character_catalog_query(
        restrict_to_product_ids=True
    )
    assert "p.product_id IN :product_ids" in bounded_query


def test_public_character_catalog_readiness_query_is_product_bounded():
    from app.services.product.main_character_slot_service import (
        build_public_character_catalog_readiness_query,
    )

    query = build_public_character_catalog_readiness_query()

    assert "public_episode.product_id IN :product_ids" in query
    assert "AS _chatReadyEpisodeCount" in query
    assert "AS _contextReadyEpisodeCount" in query
    assert "AS _continuousReadyEpisodeNo" in query
    assert "readiness_summary.summary_type = 'episode_summary'" in query
    assert "readiness_summary.episode_to = public_episode.episode_no" in query
    assert "ready_episode.episode_no >= 1" in query
    normalized_query = " ".join(query.split())
    assert (
        "SELECT DISTINCT ready_episode.product_id, ready_episode.episode_no"
        " FROM ready_episode"
        in normalized_query
    )
    assert "public_episode_no AS" in query
    assert "numbered_public_episode AS" in query
    assert "FROM public_episode_no" in query
    assert "ROW_NUMBER() OVER" in query
    assert (
        "LEFT JOIN ready_episode_no ON ready_episode_no.product_id ="
        " numbered_public_episode.product_id"
        in normalized_query
    )
    assert "ready_episode_no.episode_no IS NULL" in normalized_query
    assert (
        "readiness_sequence.public_ordinal <"
        " readiness_sequence.first_missing_ordinal"
        in normalized_query
    )
    assert "episode_no != ready_ordinal" not in normalized_query
    assert "GROUP BY public_episode.product_id" in query


def test_catalog_merge_uses_only_contiguous_ready_episode_upper_bound():
    from app.services.product.main_character_slot_service import (
        merge_public_character_catalog_candidates,
    )

    product_rows = [
        {
            "productId": product_id,
            "_latestPublicEpisodeNo": latest_episode_no,
            "_chatTotalEpisodeCount": total_episode_count,
        }
        for product_id, latest_episode_no, total_episode_count in [
            (1137, 64, 64),
            (2000, 1, 2),
            (3000, 5, 6),
        ]
    ]
    readiness_rows = [
        {
            "productId": 1137,
            "_chatReadyEpisodeCount": 63,
            "_contextReadyEpisodeCount": 64,
            "_continuousReadyEpisodeNo": 26,
        },
        {
            "productId": 2000,
            "_chatReadyEpisodeCount": 2,
            "_contextReadyEpisodeCount": 2,
            "_continuousReadyEpisodeNo": 1,
        },
        {
            "productId": 3000,
            "_chatReadyEpisodeCount": 5,
            "_contextReadyEpisodeCount": 5,
            "_continuousReadyEpisodeNo": 0,
        },
    ]
    asset_rows = [
        {
            "characterSlotId": product_id,
            "productId": product_id,
            "characterScopeKey": f"character:{product_id}",
            "_inventorySummaryText": '{"work_role":"main_protagonist"}',
        }
        for product_id in [1137, 2000, 3000]
    ]

    result = merge_public_character_catalog_candidates(
        product_rows,
        readiness_rows,
        asset_rows,
    )

    assert [
        (item["productId"], item["syncedLatestEpisodeNo"])
        for item in result
    ] == [
        (1137, 26),
        (2000, 1),
    ]


def test_public_character_catalog_assets_query_filters_before_returning_payload():
    from app.services.product.main_character_slot_service import (
        build_public_character_catalog_assets_query,
    )

    query = build_public_character_catalog_assets_query()
    normalized_query = " ".join(query.split())

    assert "inventory.product_id IN :product_ids" in query
    assert "inventory.summary_type = 'character_inventory_v3'" in query
    assert "inventory.is_active = 'Y'" in query
    assert "$.public_chat_eligible" in query
    assert "$.public_slot_eligible" not in query
    assert "$.display_safety.status" not in query
    assert "summary_type = 'character_rp_profile'" in query
    assert "summary_type = 'character_rp_examples'" in query
    assert "$.personality_core" in query
    assert "$.speech_style.tone" in query
    assert "$.speech_style.formality" in query
    assert "$.speech_style.sentence_length" in query
    assert "profile.scope_key = inventory.scope_key" in normalized_query
    assert "examples.scope_key = inventory.scope_key" in normalized_query
    assert "inventory.source_doc_count AS _distinctEpisodeCount" in query
    assert "examples.source_doc_count AS _exampleCount" in query
    assert "eligible_rp_example.episode_no BETWEEN 0 AND 1" not in query
    assert "ROW_NUMBER() OVER" not in query
    assert "JSON_CONTAINS(" not in query
    assert "$.protagonist_identity_scope_keys" not in query
    assert "$.source_character_keys" not in query
    assert "inventory.updated_date" not in query
    assert "inventory.created_date AS updatedDate" in query
    assert "_inventorySummaryText" in query


def test_catalog_assets_checks_rp_assets_only_after_latest_public_inventory():
    from app.services.product.main_character_slot_service import (
        build_public_character_catalog_assets_query,
    )

    query = build_public_character_catalog_assets_query()
    normalized_query = " ".join(query.split())

    assert "WITH inventory_assets AS (" in normalized_query
    assert "latest_inventory AS (" not in normalized_query
    assert "inventory_ranked AS (" not in normalized_query
    assert (
        "FROM tb_story_agent_context_summary inventory"
        in normalized_query
    )
    assert (
        "INNER JOIN tb_story_agent_context_summary profile"
        in normalized_query
    )
    assert (
        "INNER JOIN tb_story_agent_context_summary examples"
        in normalized_query
    )
    assert "inventory.scope_key AS characterScopeKey" in normalized_query
    assert query.count("examples.summary_type = 'character_rp_examples'") == 1
    assert "profile.is_active = 'Y'" in normalized_query
    assert "examples.is_active = 'Y'" in normalized_query
    assert "profile.scope_key = inventory.scope_key" in normalized_query
    assert "examples.scope_key = inventory.scope_key" in normalized_query


def test_catalog_assets_latest_false_does_not_fall_back_to_older_true():
    from app.services.product.main_character_slot_service import (
        build_public_character_catalog_assets_query,
    )

    inventory_versions = [
        {"summaryId": 1, "publicChatEligible": True},
        {"summaryId": 2, "publicChatEligible": False},
    ]
    latest_inventory = max(
        inventory_versions,
        key=lambda item: item["summaryId"],
    )
    query = build_public_character_catalog_assets_query()
    normalized_query = " ".join(query.split())

    assert latest_inventory["publicChatEligible"] is False
    assert "inventory.is_active = 'Y'" in normalized_query
    assert "ROW_NUMBER() OVER" not in normalized_query
    assert "$.public_chat_eligible" in normalized_query


def test_catalog_alias_fallback_query_preserves_compatible_scope_contract():
    from app.services.product.main_character_slot_service import (
        build_public_character_catalog_alias_fallback_query,
    )

    query = build_public_character_catalog_alias_fallback_query()
    normalized_query = " ".join(query.split())

    assert "inventory.product_id IN :product_ids" in query
    assert "ROW_NUMBER() OVER" in query
    assert "WHERE ranked.inventoryVersionRank = 1" in normalized_query
    assert "JSON_CONTAINS(" in query
    assert "$.protagonist_identity_scope_keys" in query
    assert "$.source_character_keys" in query
    assert "JSON_QUOTE(profile.scope_key)" in query
    assert "JSON_QUOTE(examples.scope_key)" in query
    assert "$.public_chat_eligible" in query
    assert "$.personality_core" in query
    assert "$.speech_style.tone" in query
    assert "$.speech_style.formality" in query
    assert "$.speech_style.sentence_length" in query


def test_catalog_alias_fallback_targets_only_incomplete_or_weak_exact_products():
    from app.services.product.main_character_slot_service import (
        MAIN_CHARACTER_CHAT_GOOD_MIN_EXAMPLES,
        select_public_character_catalog_alias_fallback_product_ids,
    )

    threshold = MAIN_CHARACTER_CHAT_GOOD_MIN_EXAMPLES
    product_rows = [{"productId": product_id} for product_id in [1, 2, 3, 4]]
    readiness_rows = [
        {
            "productId": product_id,
            "_chatReadyEpisodeCount": 1,
            "_continuousReadyEpisodeNo": 1,
        }
        for product_id in [1, 2, 3, 4]
    ]
    exact_candidate_items = [
        {"productId": 1, "_exampleCount": threshold + 1},
        {"productId": 1, "_exampleCount": threshold + 2},
        {"productId": 2, "_exampleCount": threshold},
        {"productId": 3, "_exampleCount": threshold},
        {"productId": 3, "_exampleCount": threshold},
    ]

    assert select_public_character_catalog_alias_fallback_product_ids(
        product_rows,
        readiness_rows,
        exact_candidate_items,
    ) == [2, 3, 4]


def test_catalog_alias_fallback_excludes_unready_or_missing_products():
    from app.services.product.main_character_slot_service import (
        select_public_character_catalog_alias_fallback_product_ids,
    )

    product_rows = [{"productId": product_id} for product_id in [1, 2, 3, 4]]
    readiness_rows = [
        {
            "productId": 1,
            "_chatReadyEpisodeCount": 1,
            "_continuousReadyEpisodeNo": 1,
        },
        {
            "productId": 2,
            "_chatReadyEpisodeCount": 0,
            "_continuousReadyEpisodeNo": 1,
        },
        {
            "productId": 4,
            "_chatReadyEpisodeCount": 1,
            "_continuousReadyEpisodeNo": 0,
        },
    ]

    assert select_public_character_catalog_alias_fallback_product_ids(
        product_rows,
        readiness_rows,
        exact_candidate_items=[],
    ) == [1]


def test_catalog_alias_fallback_is_authoritative_for_target_products():
    from app.services.product.main_character_slot_service import (
        merge_public_character_catalog_asset_candidates,
    )

    exact_candidate_items = [
        {"characterSlotId": 10, "productId": 1, "_exampleCount": 5},
        {"characterSlotId": 20, "productId": 2, "_exampleCount": 1},
        {"characterSlotId": 30, "productId": 3, "_exampleCount": 5},
    ]
    fallback_candidate_items = [
        {"characterSlotId": 20, "productId": 2, "_exampleCount": 9},
        {"characterSlotId": 21, "productId": 2, "_exampleCount": 7},
        {"characterSlotId": 90, "productId": 9, "_exampleCount": 8},
    ]

    result = merge_public_character_catalog_asset_candidates(
        exact_candidate_items,
        fallback_candidate_items,
        fallback_product_ids=[2, 3],
    )

    assert [
        (item["characterSlotId"], item["productId"], item["_exampleCount"])
        for item in result
    ] == [
        (10, 1, 5),
        (20, 2, 9),
        (21, 2, 7),
    ]


def test_public_character_catalog_scene_query_is_one_bulk_product_query():
    from app.services.product.main_character_slot_service import (
        build_public_character_catalog_scene_query,
    )

    query = build_public_character_catalog_scene_query()
    compact_query = "".join(query.split())

    assert "WITH candidate_product AS (" in query
    assert "candidate_scope AS (" in query
    assert "scene_scope AS (" in query
    assert ":candidate_json" in query
    assert "SELECT DISTINCT c.product_id" in query
    assert "character_slot_id BIGINT" in query
    assert "NESTED PATH '$.compatibleScopeKeys[*]'" in query
    assert "SELECTDISTINCTscene.summary_id" in compact_query
    assert "summary_type = 'episode_scene_extraction'" in query
    assert "scene_episode.episode_no >= 1" in query
    assert "scene_episode.use_yn = 'Y'" in query
    assert "scene_episode.open_yn = 'Y'" in query
    assert "COALESCE(scene_episode.price_type, 'free') = 'free'" in query
    assert "COUNT(DISTINCT scene_scope.summary_id) AS sceneCount" in query
    assert "MIN(scene_scope.episode_no) AS entryEpisodeNo" in query
    assert query.count("'$.scenes[*]'") == 1
    assert "JSON_CONTAINS(" not in query
    assert (
        "scene_scope.product_id=candidate_scope.product_id"
        in compact_query
    )
    assert compact_query.count("COLLATEutf8mb4_0900_bin") == 5
    assert "utf8mb4_bin" not in query
    assert "opening_scene" not in query
    assert "episode_to BETWEEN 0 AND 1" not in query
    assert "GROUP BY candidate_scope.character_slot_id" in query


def test_catalog_scene_query_binds_nonempty_gist_and_scope_to_same_scene():
    from app.services.product.main_character_slot_service import (
        build_public_character_catalog_scene_query,
    )

    query = build_public_character_catalog_scene_query()
    compact_query = "".join(query.split())

    assert "CROSS JOIN JSON_TABLE(" in query
    assert "participantsJSONPATH'$.participants'" in compact_query
    assert "action_ownershipJSONPATH'$.action_ownership'" in compact_query
    assert "NESTEDPATH'$.participants[*]'" in compact_query
    assert "NESTEDPATH'$.action_ownership[*]'" in compact_query
    assert "participant_scope_keyVARCHAR(80)" in compact_query
    assert "action_scope_keyVARCHAR(80)" in compact_query
    assert "COALESCE(IF(JSON_TYPE(flat.participants)='ARRAY'" in compact_query
    assert "IF(JSON_TYPE(flat.action_ownership)='ARRAY'" in compact_query
    assert "TRIM(COALESCE(flat.scene_gist,''))<>''" in compact_query
    assert query.count("'$.scenes[*]'") == 1
    assert "$.scenes[*].scene_gist" not in query


@pytest.mark.parametrize(
    ("scene_rows", "expected_entry_episode_no"),
    [
        ({"characterSlotId": 1, "sceneCount": 5, "entryEpisodeNo": 1}, 1),
        ({"characterSlotId": 1, "sceneCount": 5, "entryEpisodeNo": 2}, 2),
        ({"characterSlotId": 1, "sceneCount": 5, "entryEpisodeNo": 3}, 3),
        ({"characterSlotId": 1, "sceneCount": 5, "entryEpisodeNo": 4}, 4),
    ],
)
def test_catalog_uses_first_character_scene_as_entry_episode(
    scene_rows, expected_entry_episode_no,
):
    from app.services.product.main_character_slot_service import (
        filter_public_character_catalog_candidates,
    )

    candidates = [
        {
            "characterSlotId": 1,
            "productId": 1154,
            "characterScopeKey": "character:later-scene",
            "_inventorySummaryText": '{"work_role":"main_protagonist"}',
            "_distinctEpisodeCount": 5,
            "_exampleCount": 1,
            "syncedLatestEpisodeNo": 4,
        }
    ]

    result = filter_public_character_catalog_candidates(candidates, [scene_rows])

    assert result[0]["entryEpisodeNo"] == expected_entry_episode_no


@pytest.mark.parametrize(
    "scene_rows",
    [
        [],
        [{"characterSlotId": 1, "sceneCount": 1, "entryEpisodeNo": 0}],
        [{"characterSlotId": 1, "sceneCount": 1, "entryEpisodeNo": None}],
        [{"characterSlotId": 1, "sceneCount": 1, "entryEpisodeNo": 5}],
    ],
)
def test_catalog_rejects_missing_or_unsynced_entry_episode(scene_rows):
    from app.services.product.main_character_slot_service import (
        filter_public_character_catalog_candidates,
    )

    candidates = [
        {
            "characterSlotId": 1,
            "productId": 1154,
            "characterScopeKey": "character:later-scene",
            "_inventorySummaryText": '{"work_role":"main_protagonist"}',
            "syncedLatestEpisodeNo": 4,
        }
    ]

    assert filter_public_character_catalog_candidates(candidates, scene_rows) == []


def test_catalog_scene_candidates_include_runtime_compatible_inventory_aliases():
    from app.services.product.main_character_slot_service import (
        build_public_character_catalog_scene_candidates,
    )

    candidates = build_public_character_catalog_scene_candidates(
        [
            {
                "characterSlotId": 1,
                "productId": 1154,
                "characterScopeKey": "character:canonical",
                "_inventorySummaryText": json.dumps(
                    {
                        "canonical_character_key": "character:canonical",
                        "protagonist_identity_scope_keys": [
                            "character:identity",
                            "character:canonical",
                        ],
                        "source_character_keys": [
                            "protagonist:named:source",
                            "",
                        ],
                    }
                ),
            }
        ]
    )

    assert candidates == [
        {
            "characterSlotId": 1,
            "productId": 1154,
            "compatibleScopeKeys": [
                "character:canonical",
                "character:identity",
                "protagonist:named:source",
            ],
        }
    ]


def test_public_character_catalog_image_query_uses_selected_cards_only():
    from app.services.product.main_character_slot_service import (
        build_public_character_catalog_image_query,
    )

    query = build_public_character_catalog_image_query()

    assert ":selected_json" in query
    assert "active_slot.character_scope_key" in query
    assert "selected.character_scope_key" in query
    assert "slot_group.group_type = 'character'" in query
    assert "cover_group.group_type = 'cover'" in query
    assert "COALESCE(" in query
    assert "AS hasCharacterImage" not in query
    assert "GROUP BY selected.character_slot_id" in query


def test_catalog_candidate_filter_keeps_supported_roles_and_valid_scenes():
    from app.services.product.main_character_slot_service import (
        filter_public_character_catalog_candidates,
    )

    candidates = [
        {
            "characterSlotId": 1,
            "productId": 10,
            "characterScopeKey": "character:protagonist",
            "characterName": "주인공",
            "_isProtagonist": 1,
            "_distinctEpisodeCount": 5,
            "_exampleCount": 3,
            "_inventorySummaryText": '{"work_role":"main_protagonist"}',
            "syncedLatestEpisodeNo": 10,
        },
        {
            "characterSlotId": 2,
            "productId": 10,
            "characterScopeKey": "character:major",
            "characterName": "주요 인물",
            "_isProtagonist": 0,
            "_distinctEpisodeCount": 20,
            "_exampleCount": 10,
            "_inventorySummaryText": '{"work_role":"major_character"}',
            "syncedLatestEpisodeNo": 10,
        },
        {
            "characterSlotId": 3,
            "productId": 10,
            "characterScopeKey": "character:minor",
            "characterName": "조연",
            "_isProtagonist": 0,
            "_distinctEpisodeCount": 5,
            "_exampleCount": 2,
            "_inventorySummaryText": '{"work_role":"supporting"}',
            "syncedLatestEpisodeNo": 10,
        },
    ]
    scenes = [
        {"characterSlotId": 1, "sceneCount": 5, "entryEpisodeNo": 1},
        {"characterSlotId": 2, "sceneCount": 5, "entryEpisodeNo": 2},
        {"characterSlotId": 3, "sceneCount": 2, "entryEpisodeNo": 3},
    ]

    result = filter_public_character_catalog_candidates(candidates, scenes)

    assert {item["characterSlotId"] for item in result} == {1, 2}
    assert {
        item["characterRole"] for item in result
    } == {"main_protagonist", "major_character"}
    assert all("_inventorySummaryText" not in item for item in result)
    assert all("_isProtagonist" not in item for item in result)


@pytest.mark.parametrize(
    ("distinct_episode_count", "example_count", "scene_count", "expected"),
    [
        (4, 1, 5, "insufficient"),
        (5, 0, 5, "insufficient"),
        (5, 1, 4, "insufficient"),
        (5, 1, 5, "normal"),
        (5, 2, 5, "normal"),
        (10, 4, 5, "good"),
    ],
)
def test_character_chat_quality_enforces_minimum_public_asset_bundle(
    distinct_episode_count, example_count, scene_count, expected,
):
    from app.services.product.main_character_slot_service import (
        classify_main_character_chat_quality,
    )

    quality, _ = classify_main_character_chat_quality(
        distinct_episode_count=distinct_episode_count,
        example_count=example_count,
        scene_count=scene_count,
    )

    assert quality == expected


def test_catalog_hides_character_below_minimum_public_asset_bundle():
    from app.services.product.main_character_slot_service import (
        filter_public_character_catalog_candidates,
    )

    candidates = [
        {
            "characterSlotId": slot_id,
            "productId": slot_id,
            "characterScopeKey": f"character:{slot_id}",
            "characterName": f"인물 {slot_id}",
            "_distinctEpisodeCount": episode_count,
            "_exampleCount": example_count,
            "_inventorySummaryText": '{"work_role":"main_protagonist"}',
            "syncedLatestEpisodeNo": 10,
        }
        for slot_id, episode_count, example_count in [
            (1, 4, 1),
            (2, 5, 0),
            (3, 5, 1),
            (4, 5, 1),
        ]
    ]
    scenes = [
        {"characterSlotId": 1, "sceneCount": 5, "entryEpisodeNo": 1},
        {"characterSlotId": 2, "sceneCount": 5, "entryEpisodeNo": 1},
        {"characterSlotId": 3, "sceneCount": 4, "entryEpisodeNo": 1},
        {"characterSlotId": 4, "sceneCount": 5, "entryEpisodeNo": 1},
    ]

    result = filter_public_character_catalog_candidates(candidates, scenes)

    assert [item["characterSlotId"] for item in result] == [4]


def test_catalog_recommendation_prioritizes_character_image_assets_and_protagonists():
    from app.services.product.main_character_slot_service import (
        rank_public_character_catalog_items,
    )

    items = [
        {
            "characterSlotId": 4,
            "productId": 4,
            "cardOrder": 0,
            "characterImagePath": "/images/default-cover.png",
            "fullReady": True,
            "chatQuality": "good",
            "characterRole": "main_protagonist",
            "readinessCoverageRatio": 1.0,
            "distinctEpisodeCount": 20,
            "exampleCount": 8,
            "sceneCount": 8,
        },
        {
            "characterSlotId": 3,
            "productId": 3,
            "cardOrder": 0,
            "characterImagePath": "/covers/3.webp",
            "fullReady": True,
            "chatQuality": "good",
            "characterRole": "major_character",
            "readinessCoverageRatio": 1.0,
            "distinctEpisodeCount": 20,
            "exampleCount": 8,
            "sceneCount": 8,
        },
        {
            "characterSlotId": 2,
            "productId": 2,
            "cardOrder": 0,
            "characterImagePath": "/characters/2.webp",
            "fullReady": True,
            "chatQuality": "good",
            "characterRole": "main_protagonist",
            "readinessCoverageRatio": 0.8,
            "distinctEpisodeCount": 10,
            "exampleCount": 4,
            "sceneCount": 5,
        },
        {
            "characterSlotId": 1,
            "productId": 1,
            "cardOrder": 0,
            "characterImagePath": "/covers/1.webp",
            "fullReady": False,
            "chatQuality": "good",
            "characterRole": "main_protagonist",
            "readinessCoverageRatio": 0.9,
            "distinctEpisodeCount": 30,
            "exampleCount": 10,
            "sceneCount": 10,
        },
    ]

    ranked = rank_public_character_catalog_items(items)

    assert [item["characterSlotId"] for item in ranked] == [2, 3, 1, 4]
    assert [item["cardOrder"] for item in ranked] == [1, 2, 3, 4]
    assert [item["hasCharacterImage"] for item in ranked] == [True, True, True, False]


def test_catalog_applies_recommendation_priority_before_per_product_limit():
    from app.services.product.main_character_slot_service import (
        finalize_public_character_catalog_items,
    )

    shared = {
        "productId": 10,
        "cardOrder": 0,
        "fullReady": True,
        "chatQuality": "good",
        "readinessCoverageRatio": 1.0,
        "exampleCount": 8,
        "sceneCount": 8,
    }
    items = [
        {
            **shared,
            "characterSlotId": 1,
            "characterImagePath": "/images/default-cover.png",
            "characterRole": "main_protagonist",
            "distinctEpisodeCount": 10,
        },
        {
            **shared,
            "characterSlotId": 2,
            "characterImagePath": "ESokN0lzSgG0um4rn4tBeg/cover.webp",
            "characterRole": "major_character",
            "distinctEpisodeCount": 20,
        },
        {
            **shared,
            "characterSlotId": 3,
            "characterImagePath": "/covers/real.webp",
            "characterRole": "major_character",
            "distinctEpisodeCount": 5,
        },
    ]

    result = finalize_public_character_catalog_items(items)

    assert [item["characterSlotId"] for item in result] == [3, 1]
    assert [item["cardOrder"] for item in result] == [1, 2]
    assert [item["hasCharacterImage"] for item in result] == [True, False]


def test_public_home_auto_mode_does_not_build_the_full_catalog_in_request():
    from app.services.product import main_character_slot_service

    catalog_items = [
        {
            "characterSlotId": 7,
            "cardOrder": 1,
            "hasCharacterImage": True,
        }
    ]
    db = AsyncMock()
    with (
        patch.object(
            main_character_slot_service,
            "get_main_character_slot_display_mode",
            new_callable=AsyncMock,
            return_value="auto",
        ),
        patch.object(
            main_character_slot_service,
            "read_public_character_catalog_snapshot",
            new_callable=AsyncMock,
            return_value=catalog_items,
        ) as read_snapshot,
        patch.object(
            main_character_slot_service,
            "get_public_character_catalog",
            new_callable=AsyncMock,
        ) as get_catalog,
    ):
        response = asyncio.run(
            main_character_slot_service.get_public_main_character_slots(
                adult_yn="N",
                db=db,
            )
        )

    get_catalog.assert_not_awaited()
    read_snapshot.assert_awaited_once_with(
        adult_yn="N",
        db=db,
        limit=12,
    )
    assert response == {"data": catalog_items}
    db.execute.assert_not_awaited()


def test_main_character_slot_request_schema_enforces_optional_period_contract():
    from app.schemas.admin import (
        PostMainCharacterSlotReqBody,
        PutMainCharacterSlotReqBody,
        PutMainCharacterSlotConfigReqBody,
    )

    req = PostMainCharacterSlotReqBody(
        product_id=1182,
        character_scope_key=" character:adelite ",
        character_image_file_id=10,
        card_order=1,
        publish_start_at="2026-07-11T12:00:00+09:00",
        publish_end_at="",
    )

    assert req.character_scope_key == "character:adelite"
    assert not hasattr(req, "character_name")
    assert not hasattr(req, "use_yn")
    assert req.publish_end_at is None

    immediate_req = PostMainCharacterSlotReqBody(
        product_id=1182,
        character_scope_key="character:adelite",
        character_image_file_id=10,
        card_order=1,
    )
    assert immediate_req.publish_start_at is None
    assert immediate_req.publish_end_at is None

    update_req = PutMainCharacterSlotReqBody(
        product_id=1182,
        character_scope_key="character:adelite",
        card_order=2,
        publish_start_at="2026-07-11T12:00:00+09:00",
    )
    assert update_req.character_image_file_id is None
    assert (
        PutMainCharacterSlotConfigReqBody(display_mode="auto").display_mode
        == "auto"
    )

    with pytest.raises(ValueError):
        PutMainCharacterSlotConfigReqBody(display_mode="random")

    with pytest.raises(ValueError):
        PostMainCharacterSlotReqBody(
            product_id=1182,
            character_scope_key="character:adelite",
            character_image_file_id=10,
            card_order=1,
            publish_start_at="2026-07-12T12:00:00+09:00",
            publish_end_at="2026-07-11T12:00:00+09:00",
        )


def test_storage_upload_accepts_character_group_type_through_existing_validator():
    from app.schemas.storage import UploadReqBody, available_group_types

    assert "character" in available_group_types
    assert UploadReqBody(group_type="character", file_name="hero.webp").group_type == "character"


class MainCharacterSlotServiceAsyncTest(unittest.IsolatedAsyncioTestCase):
    async def test_display_mode_defaults_to_auto_and_preserves_manual(self):
        from app.services.product import main_character_slot_service

        result = MagicMock()
        result.mappings.return_value.one_or_none.side_effect = [
            None,
            {"displayMode": "manual"},
        ]
        db = AsyncMock()
        db.execute.return_value = result

        assert (
            await main_character_slot_service.get_main_character_slot_display_mode(
                db=db
            )
            == "auto"
        )
        assert (
            await main_character_slot_service.get_main_character_slot_display_mode(
                db=db
            )
            == "manual"
        )

    async def test_admin_can_persist_the_main_character_slot_display_mode(self):
        from app.schemas.admin import PutMainCharacterSlotConfigReqBody
        from app.services.product import main_character_slot_service

        db = AsyncMock()
        response = (
            await main_character_slot_service.update_admin_main_character_slot_config(
                req_body=PutMainCharacterSlotConfigReqBody(display_mode="manual"),
                admin_user_id=7,
                db=db,
            )
        )

        executed_sql = str(db.execute.await_args.args[0])
        assert "INSERT INTO tb_main_character_slot_config" in executed_sql
        assert "ON DUPLICATE KEY UPDATE" in executed_sql
        assert db.execute.await_args.args[1] == {
            "display_mode": "manual",
            "admin_user_id": 7,
        }
        assert response == {"data": {"displayMode": "manual"}}

    @staticmethod
    def _catalog_base_db():
        product_result = MagicMock()
        product_result.mappings.return_value.all.return_value = [
            {
                "productId": 1182,
                "productTitle": "테스트 작품",
                "authorNickname": "테스트 작가",
                "_chatTotalEpisodeCount": 4,
                "_latestPublicEpisodeNo": 4,
            }
        ]
        readiness_result = MagicMock()
        readiness_result.mappings.return_value.all.return_value = [
            {
                "productId": 1182,
                "_chatReadyEpisodeCount": 3,
                "_contextReadyEpisodeCount": 3,
                "_continuousReadyEpisodeNo": 3,
            }
        ]
        catalog_result = MagicMock()
        catalog_result.mappings.return_value.all.return_value = [
            {
                "characterSlotId": 1,
                "productId": 1182,
                "characterScopeKey": "character:adelite",
                "_distinctEpisodeCount": 12,
                "_exampleCount": 5,
                "_sceneCount": 0,
                "_inventorySummaryText": '{"work_role":"main_protagonist"}',
                "_isProtagonist": 1,
            },
            {
                "characterSlotId": 99,
                "productId": 1182,
                "characterScopeKey": "character:support",
                "_distinctEpisodeCount": 12,
                "_exampleCount": 5,
                "_sceneCount": 0,
                "_inventorySummaryText": '{"work_role":"major_character"}',
                "_isProtagonist": 0,
            },
        ]
        scene_result = MagicMock()
        scene_result.mappings.return_value.all.return_value = [
            {
                "characterSlotId": 1,
                "sceneCount": 5,
                "entryEpisodeNo": 2,
            }
        ]
        image_result = MagicMock()
        image_result.mappings.return_value.all.return_value = [
            {
                "characterSlotId": 1,
                "characterImagePath": "/cover.webp",
            }
        ]
        db = AsyncMock()
        db.execute.side_effect = [
            product_result,
            readiness_result,
            catalog_result,
            scene_result,
            image_result,
        ]
        return db

    async def test_catalog_load_queries_fallback_only_for_target_products(self):
        from app.services.product import main_character_slot_service

        threshold = (
            main_character_slot_service.MAIN_CHARACTER_CHAT_GOOD_MIN_EXAMPLES
        )

        def result(rows):
            query_result = MagicMock()
            query_result.mappings.return_value.all.return_value = rows
            return query_result

        product_result = result(
            [
                {
                    "productId": product_id,
                    "productTitle": f"작품 {product_id}",
                    "authorNickname": "작가",
                    "_chatTotalEpisodeCount": 10,
                    "_latestPublicEpisodeNo": 10,
                }
                for product_id in [1, 2]
            ]
        )
        readiness_result = result(
            [
                {
                    "productId": product_id,
                    "_chatReadyEpisodeCount": 10,
                    "_contextReadyEpisodeCount": 10,
                    "_continuousReadyEpisodeNo": 10,
                }
                for product_id in [1, 2]
            ]
        )
        exact_assets_result = result(
            [
                {
                    "characterSlotId": slot_id,
                    "productId": product_id,
                    "characterScopeKey": f"character:{slot_id}",
                    "_distinctEpisodeCount": distinct_episode_count,
                    "_exampleCount": example_count,
                    "_inventorySummaryText": (
                        '{"work_role":"main_protagonist"}'
                    ),
                    "_isProtagonist": 1,
                }
                for slot_id, product_id, distinct_episode_count, example_count in [
                    (11, 1, 10, threshold + 1),
                    (12, 1, 10, threshold + 1),
                    (13, 1, 9, threshold + 1),
                    (21, 2, 10, threshold - 1),
                ]
            ]
        )
        fallback_assets_result = result(
            [
                {
                    "characterSlotId": slot_id,
                    "productId": 2,
                    "characterScopeKey": f"character:{slot_id}",
                    "_distinctEpisodeCount": distinct_count,
                    "_exampleCount": example_count,
                    "_inventorySummaryText": (
                        '{"work_role":"main_protagonist"}'
                    ),
                    "_isProtagonist": 1,
                }
                for slot_id, distinct_count, example_count in [
                    (21, 91, 9),
                    (22, 70, 7),
                ]
            ]
        )
        scene_result = result(
            [
                {
                    "characterSlotId": slot_id,
                    "sceneCount": 5,
                    "entryEpisodeNo": 1,
                }
                for slot_id in [11, 12, 13, 21, 22]
            ]
        )
        image_result = result(
            [
                {
                    "characterSlotId": slot_id,
                    "characterImagePath": (
                        f"/{slot_id}.webp"
                        if slot_id in {13, 21, 22}
                        else "/images/default-cover.png"
                    ),
                }
                for slot_id in [11, 12, 13, 21, 22]
            ]
        )
        db = AsyncMock()
        db.execute.side_effect = [
            product_result,
            readiness_result,
            exact_assets_result,
            fallback_assets_result,
            scene_result,
            image_result,
        ]

        catalog_items = (
            await main_character_slot_service._load_public_character_catalog_base(
                adult_yn="N",
                db=db,
            )
        )

        assert db.execute.await_count == 6
        assert db.execute.await_args_list[3].args[1]["product_ids"] == [2]
        assert {
            item["characterSlotId"]
            for item in json.loads(
                db.execute.await_args_list[5].args[1]["selected_json"]
            )
        } == {11, 12, 13, 21, 22}
        assert {
            (item["characterSlotId"], item["productId"], item["exampleCount"])
            for item in catalog_items
        } == {
            (11, 1, threshold + 1),
            (13, 1, threshold + 1),
            (21, 2, 9),
            (22, 2, 7),
        }

    async def test_character_catalog_reads_snapshot_for_each_request_and_normalizes_scope(self):
        from app.services.product import main_character_slot_service

        db = AsyncMock()
        with patch.object(
            main_character_slot_service,
            "read_public_character_catalog_snapshot",
            new_callable=AsyncMock,
            side_effect=[
                [{"productId": 1182, "productTitle": "일반"}],
                [{"productId": 1182, "productTitle": "일반 재조회"}],
                [{"productId": 1192, "productTitle": "성인"}],
            ],
        ) as read_snapshot:
            invalid_response = await main_character_slot_service.get_public_character_catalog(
                adult_yn="invalid", kc_user_id=None, db=db
            )
            normal_response = await main_character_slot_service.get_public_character_catalog(
                adult_yn="N", kc_user_id=None, db=db
            )
            adult_response = await main_character_slot_service.get_public_character_catalog(
                adult_yn="Y", kc_user_id=None, db=db
            )

        assert [call.kwargs["adult_yn"] for call in read_snapshot.await_args_list] == [
            "N",
            "N",
            "Y",
        ]
        assert all(call.kwargs["db"] is db for call in read_snapshot.await_args_list)
        assert db.execute.await_count == 0
        assert invalid_response["data"][0]["productTitle"] == "일반"
        assert normal_response["data"][0]["productTitle"] == "일반 재조회"
        assert adult_response["data"][0]["productTitle"] == "성인"

    async def test_character_catalog_keeps_authenticated_progress_fresh_and_private(self):
        from app.services.product import main_character_slot_service

        first_progress_result = MagicMock()
        first_progress_result.mappings.return_value.all.return_value = [
            {
                "productId": 1182,
                "lastViewedEpisodeNo": 17,
                "lastViewedAt": "2026-07-22 12:34:56",
            }
        ]
        first_db = AsyncMock()
        first_db.execute.return_value = first_progress_result

        second_progress_result = MagicMock()
        second_progress_result.mappings.return_value.all.return_value = [
            {
                "productId": 1182,
                "lastViewedEpisodeNo": 3,
                "lastViewedAt": "2026-07-24 09:00:00",
            }
        ]
        second_db = AsyncMock()
        second_db.execute.return_value = second_progress_result
        snapshot_item = {
            "productId": 1182,
            "lastViewedEpisodeNo": None,
            "lastViewedAt": None,
        }
        with patch.object(
            main_character_slot_service,
            "read_public_character_catalog_snapshot",
            new_callable=AsyncMock,
            side_effect=[[dict(snapshot_item)], [dict(snapshot_item)]],
        ):
            first_response = await main_character_slot_service.get_public_character_catalog(
                adult_yn="N", kc_user_id="kc-user-1", db=first_db
            )
            second_response = await main_character_slot_service.get_public_character_catalog(
                adult_yn="N", kc_user_id="kc-user-2", db=second_db
            )

        assert first_db.execute.await_count == 1
        assert second_db.execute.await_count == 1
        assert second_db.execute.await_args.args[1]["kc_user_id"] == "kc-user-2"
        assert (
            first_response["data"][0]["lastViewedEpisodeNo"],
            first_response["data"][0]["lastViewedAt"],
        ) == (17, "2026-07-22 12:34:56")
        assert (
            second_response["data"][0]["lastViewedEpisodeNo"],
            second_response["data"][0]["lastViewedAt"],
        ) == (3, "2026-07-24 09:00:00")

    async def test_public_home_slots_survive_entry_episode_query_failure(self):
        from sqlalchemy.exc import SQLAlchemyError

        from app.services.product import main_character_slot_service

        slot_result = MagicMock()
        slot_result.mappings.return_value.all.return_value = [
            {
                "characterSlotId": 1,
                "productId": 1101,
                "characterScopeKey": "character:1",
                "syncedLatestEpisodeNo": 4,
                "_inventorySummaryText": '{"work_role":"main_protagonist"}',
            }
        ]
        db = AsyncMock()
        db.execute.side_effect = [
            slot_result,
            SQLAlchemyError("entry episode lookup failed"),
        ]

        with (
            patch.object(
                main_character_slot_service,
                "get_main_character_slot_display_mode",
                new_callable=AsyncMock,
                return_value="manual",
            ),
            self.assertLogs(
                main_character_slot_service.logger.name,
                level="ERROR",
            ),
        ):
            response = await main_character_slot_service.get_public_main_character_slots(
                adult_yn="N",
                db=db,
            )

        assert response == {
            "data": [
                {
                    "characterSlotId": 1,
                    "productId": 1101,
                    "characterScopeKey": "character:1",
                    "characterRole": "main_protagonist",
                    "syncedLatestEpisodeNo": 4,
                    "entryEpisodeNo": 1,
                }
            ]
        }

    async def test_public_home_slots_hide_characters_below_scene_minimum(self):
        from app.services.product import main_character_slot_service

        slot_result = MagicMock()
        slot_result.mappings.return_value.all.return_value = [
            {
                "characterSlotId": slot_id,
                "productId": 1100 + slot_id,
                "characterScopeKey": f"character:{slot_id}",
                "syncedLatestEpisodeNo": synced_episode_no,
                "_inventorySummaryText": '{"work_role":"main_protagonist"}',
            }
            for slot_id, synced_episode_no in [
                (1, 4),
                (2, 4),
                (3, 4),
                (4, 4),
                (5, 2),
            ]
        ]
        scene_result = MagicMock()
        scene_result.mappings.return_value.all.return_value = [
            {"characterSlotId": 1, "sceneCount": 5, "entryEpisodeNo": 2},
            {"characterSlotId": 2, "sceneCount": 5, "entryEpisodeNo": 3},
            {"characterSlotId": 3, "sceneCount": 4, "entryEpisodeNo": 4},
            {"characterSlotId": 5, "sceneCount": 5, "entryEpisodeNo": 3},
        ]
        db = AsyncMock()
        db.execute.side_effect = [slot_result, scene_result]

        with patch.object(
            main_character_slot_service,
            "get_main_character_slot_display_mode",
            new_callable=AsyncMock,
            return_value="manual",
        ):
            response = await main_character_slot_service.get_public_main_character_slots(
                adult_yn="N",
                db=db,
            )

        assert db.execute.await_count == 2
        assert json.loads(db.execute.await_args_list[1].args[1]["candidate_json"]) == [
            {
                "characterSlotId": slot_id,
                "productId": 1100 + slot_id,
                "compatibleScopeKeys": [f"character:{slot_id}"],
            }
            for slot_id in range(1, 6)
        ]
        assert [item["characterSlotId"] for item in response["data"]] == [1, 2]
        assert [item["entryEpisodeNo"] for item in response["data"]] == [2, 3]
        assert all(
            "_inventorySummaryText" not in item for item in response["data"]
        )

    async def test_character_catalog_guest_bulk_loads_scenes_with_two_queries(self):
        from app.services.product import main_character_slot_service

        product_result = MagicMock()
        product_result.mappings.return_value.all.return_value = [
            {
                "productId": 1182,
                "productTitle": "테스트 작품",
                "authorNickname": "테스트 작가",
                "_chatTotalEpisodeCount": 4,
                "_latestPublicEpisodeNo": 4,
            }
        ]
        readiness_result = MagicMock()
        readiness_result.mappings.return_value.all.return_value = [
            {
                "productId": 1182,
                "_chatReadyEpisodeCount": 3,
                "_contextReadyEpisodeCount": 3,
                "_continuousReadyEpisodeNo": 3,
            }
        ]
        catalog_result = MagicMock()
        catalog_result.mappings.return_value.all.return_value = [
            {
                "characterSlotId": 1,
                "productId": 1182,
                "characterScopeKey": "character:adelite",
                "_distinctEpisodeCount": 12,
                "_exampleCount": 5,
                "_sceneCount": 0,
                "_inventorySummaryText": '{"work_role":"main_protagonist"}',
                "_isProtagonist": 1,
            },
            {
                "characterSlotId": 99,
                "productId": 1182,
                "characterScopeKey": "character:support",
                "_distinctEpisodeCount": 12,
                "_exampleCount": 5,
                "_sceneCount": 0,
                "_inventorySummaryText": '{"work_role":"major_character"}',
                "_isProtagonist": 0,
            },
        ]
        scene_result = MagicMock()
        scene_result.mappings.return_value.all.return_value = [
            {
                "characterSlotId": 1,
                "sceneCount": 5,
                "entryEpisodeNo": 2,
            }
        ]
        image_result = MagicMock()
        image_result.mappings.return_value.all.return_value = [
            {"characterSlotId": 1, "characterImagePath": "/cover.webp"}
        ]
        db = AsyncMock()
        db.execute.side_effect = [
            product_result,
            readiness_result,
            catalog_result,
            scene_result,
            image_result,
        ]

        catalog_items = await main_character_slot_service._load_public_character_catalog_base(
            adult_yn="N",
            db=db,
        )

        assert db.execute.await_count == 5
        assert db.execute.await_args_list[1].args[0]._bindparams[
            "product_ids"
        ].expanding
        assert db.execute.await_args_list[2].args[0]._bindparams[
            "product_ids"
        ].expanding
        scene_params = db.execute.await_args_list[3].args[1]
        assert json.loads(scene_params["candidate_json"]) == [
            {
                "characterSlotId": 1,
                "productId": 1182,
                "compatibleScopeKeys": ["character:adelite"],
            },
            {
                "characterSlotId": 99,
                "productId": 1182,
                "compatibleScopeKeys": ["character:support"],
            },
        ]
        assert catalog_items == [
            {
                "characterSlotId": 1,
                "productId": 1182,
                "characterScopeKey": "character:adelite",
                "characterRole": "main_protagonist",
                "productTitle": "테스트 작품",
                "authorNickname": "테스트 작가",
                "syncedLatestEpisodeNo": 3,
                "entryEpisodeNo": 2,
                "publishStartAt": None,
                "publishEndAt": None,
                "cardOrder": 1,
                "characterImagePath": "/cover.webp",
                "hasCharacterImage": True,
                "fullReady": False,
                "readinessCoverageRatio": 0.75,
                "distinctEpisodeCount": 12,
                "exampleCount": 5,
                "sceneCount": 5,
                "chatQuality": "good",
                "lastViewedEpisodeNo": None,
                "lastViewedAt": None,
            }
        ]

    async def test_character_catalog_auth_bulk_loads_and_merges_progress(self):
        from app.services.product import main_character_slot_service

        product_result = MagicMock()
        product_result.mappings.return_value.all.return_value = [
            {
                "productId": 1182,
                "_chatTotalEpisodeCount": 12,
                "_latestPublicEpisodeNo": 12,
            },
            {
                "productId": 1192,
                "_chatTotalEpisodeCount": 12,
                "_latestPublicEpisodeNo": 12,
            },
        ]
        readiness_result = MagicMock()
        readiness_result.mappings.return_value.all.return_value = [
            {
                "productId": 1182,
                "_chatReadyEpisodeCount": 12,
                "_contextReadyEpisodeCount": 12,
                "_continuousReadyEpisodeNo": 12,
            },
            {
                "productId": 1192,
                "_chatReadyEpisodeCount": 6,
                "_contextReadyEpisodeCount": 6,
                "_continuousReadyEpisodeNo": 6,
            },
        ]
        catalog_result = MagicMock()
        catalog_result.mappings.return_value.all.return_value = [
            {
                "characterSlotId": 1,
                "productId": 1182,
                "characterScopeKey": "character:adelite",
                "_distinctEpisodeCount": 8,
                "_exampleCount": 2,
                "_sceneCount": 0,
                "_inventorySummaryText": '{"work_role":"main_protagonist"}',
                "_isProtagonist": 1,
            },
            {
                "characterSlotId": 2,
                "productId": 1192,
                "characterScopeKey": "character:other",
                "_distinctEpisodeCount": 10,
                "_exampleCount": 4,
                "_sceneCount": 0,
                "_inventorySummaryText": '{"work_role":"main_protagonist"}',
                "_isProtagonist": 1,
            },
        ]
        scene_result = MagicMock()
        scene_result.mappings.return_value.all.return_value = [
            {"characterSlotId": 1, "sceneCount": 5, "entryEpisodeNo": 2},
            {"characterSlotId": 2, "sceneCount": 5, "entryEpisodeNo": 3},
        ]
        image_result = MagicMock()
        image_result.mappings.return_value.all.return_value = [
            {
                "characterSlotId": 1,
                "characterImagePath": "/one.webp",
                "hasCharacterImage": 1,
            },
            {
                "characterSlotId": 2,
                "characterImagePath": "/two.webp",
                "hasCharacterImage": 1,
            },
        ]
        progress_result = MagicMock()
        progress_result.mappings.return_value.all.return_value = [
            {
                "productId": 1182,
                "lastViewedEpisodeNo": 17,
                "lastViewedAt": "2026-07-22 12:34:56",
            }
        ]
        db = AsyncMock()
        db.execute.side_effect = [
            product_result,
            readiness_result,
            catalog_result,
            catalog_result,
            scene_result,
            image_result,
            progress_result,
        ]

        catalog_items = await main_character_slot_service._load_public_character_catalog_base(
            adult_yn="N", db=db
        )
        with patch.object(
            main_character_slot_service,
            "read_public_character_catalog_snapshot",
            new_callable=AsyncMock,
            return_value=catalog_items,
        ):
            response = await main_character_slot_service.get_public_character_catalog(
                adult_yn="N", kc_user_id="kc-user-1", db=db
            )

        assert db.execute.await_count == 7
        progress_query = db.execute.await_args_list[6].args[0]
        progress_sql = str(progress_query)
        progress_params = db.execute.await_args_list[6].args[1]
        assert "FROM tb_user_product_usage" in progress_sql
        assert "INNER JOIN tb_product_episode" in progress_sql
        assert "INNER JOIN tb_user" in progress_sql
        assert "u.kc_user_id = :kc_user_id" in progress_sql
        assert "u.use_yn = 'Y'" in progress_sql
        assert "usage_row.use_yn = 'Y'" in progress_sql
        assert "pe.use_yn = 'Y'" in progress_sql
        assert "pe.open_yn = 'Y'" in progress_sql
        assert "usage_row.product_id IN" in progress_sql
        assert "MAX(pe.episode_no) AS lastViewedEpisodeNo" in progress_sql
        assert "MAX(usage_row.updated_date) AS lastViewedAt" in progress_sql
        assert progress_query._bindparams["product_ids"].expanding is True
        assert progress_params == {
            "kc_user_id": "kc-user-1",
            "product_ids": [1182, 1192],
        }
        assert response == {
            "data": [
                {
                    "characterSlotId": 1,
                    "productId": 1182,
                    "characterScopeKey": "character:adelite",
                    "characterRole": "main_protagonist",
                    "productTitle": None,
                    "authorNickname": None,
                    "syncedLatestEpisodeNo": 12,
                    "entryEpisodeNo": 2,
                    "publishStartAt": None,
                    "publishEndAt": None,
                    "cardOrder": 1,
                    "characterImagePath": "/one.webp",
                    "hasCharacterImage": True,
                    "fullReady": True,
                    "readinessCoverageRatio": 1.0,
                    "distinctEpisodeCount": 8,
                    "exampleCount": 2,
                    "sceneCount": 5,
                    "chatQuality": "normal",
                    "lastViewedEpisodeNo": 17,
                    "lastViewedAt": "2026-07-22 12:34:56",
                },
                {
                    "characterSlotId": 2,
                    "productId": 1192,
                    "characterScopeKey": "character:other",
                    "characterRole": "main_protagonist",
                    "productTitle": None,
                    "authorNickname": None,
                    "syncedLatestEpisodeNo": 6,
                    "entryEpisodeNo": 3,
                    "publishStartAt": None,
                    "publishEndAt": None,
                    "cardOrder": 2,
                    "characterImagePath": "/two.webp",
                    "hasCharacterImage": True,
                    "fullReady": False,
                    "readinessCoverageRatio": 0.5,
                    "distinctEpisodeCount": 10,
                    "exampleCount": 4,
                    "sceneCount": 5,
                    "chatQuality": "good",
                    "lastViewedEpisodeNo": None,
                    "lastViewedAt": None,
                },
            ]
        }

    async def test_character_catalog_enriches_duplicate_characters_for_same_product(self):
        from app.services.product import main_character_slot_service

        product_result = MagicMock()
        product_result.mappings.return_value.all.return_value = [
            {
                "productId": 1182,
                "_chatTotalEpisodeCount": 15,
                "_latestPublicEpisodeNo": 15,
            }
        ]
        readiness_result = MagicMock()
        readiness_result.mappings.return_value.all.return_value = [
            {
                "productId": 1182,
                "_chatReadyEpisodeCount": 1,
                "_contextReadyEpisodeCount": 1,
                "_continuousReadyEpisodeNo": 1,
            }
        ]
        catalog_result = MagicMock()
        catalog_result.mappings.return_value.all.return_value = [
            {
                "characterSlotId": 1,
                "productId": 1182,
                "characterScopeKey": "character:a",
                "_distinctEpisodeCount": 5,
                "_exampleCount": 5,
                "_inventorySummaryText": '{"work_role":"main_protagonist"}',
            },
            {
                "characterSlotId": 2,
                "productId": 1182,
                "characterScopeKey": "character:b",
                "_distinctEpisodeCount": 5,
                "_exampleCount": 5,
                "_inventorySummaryText": '{"work_role":"major_character"}',
            },
        ]
        scene_result = MagicMock()
        scene_result.mappings.return_value.all.return_value = [
            {"characterSlotId": 1, "sceneCount": 5, "entryEpisodeNo": 1},
            {"characterSlotId": 2, "sceneCount": 5, "entryEpisodeNo": 1},
        ]
        image_result = MagicMock()
        image_result.mappings.return_value.all.return_value = [
            {"characterSlotId": 1, "characterImagePath": None},
            {"characterSlotId": 2, "characterImagePath": None},
        ]
        progress_result = MagicMock()
        progress_result.mappings.return_value.all.return_value = [
            {
                "productId": 1182,
                "lastViewedEpisodeNo": 17,
                "lastViewedAt": "2026-07-22 12:34:56",
            }
        ]
        db = AsyncMock()
        db.execute.side_effect = [
            product_result,
            readiness_result,
            catalog_result,
            scene_result,
            image_result,
            progress_result,
        ]

        catalog_items = await main_character_slot_service._load_public_character_catalog_base(
            adult_yn="Y", db=db
        )
        with patch.object(
            main_character_slot_service,
            "read_public_character_catalog_snapshot",
            new_callable=AsyncMock,
            return_value=catalog_items,
        ):
            response = await main_character_slot_service.get_public_character_catalog(
                adult_yn="Y", kc_user_id="kc-user-1", db=db
            )

        assert db.execute.await_count == 6
        assert db.execute.await_args_list[5].args[1]["product_ids"] == [1182]
        assert [
            (item["lastViewedEpisodeNo"], item["lastViewedAt"])
            for item in response["data"]
        ] == [
            (17, "2026-07-22 12:34:56"),
            (17, "2026-07-22 12:34:56"),
        ]

    async def test_character_catalog_empty_result_skips_auth_progress_query(self):
        from app.services.product import main_character_slot_service

        catalog_result = MagicMock()
        catalog_result.mappings.return_value.all.return_value = []
        db = AsyncMock()
        db.execute.return_value = catalog_result

        response = await main_character_slot_service.get_public_character_catalog(
            adult_yn="N",
            kc_user_id="kc-user-1",
            db=db,
        )

        assert db.execute.await_count == 1
        assert response == {"data": []}

    async def test_character_catalog_router_passes_optional_authenticated_user(self):
        from app.routers.common import main_query
        from app.services.product import main_character_slot_service
        from app.utils.auth import chk_optional_cur_user_strict

        route = next(
            route
            for route in main_query.router.routes
            if route.path == "/products/character-chat-catalog"
        )
        assert chk_optional_cur_user_strict in [
            dependency.call for dependency in route.dependant.dependencies
        ]

        db = object()
        with patch.object(
            main_character_slot_service,
            "get_public_character_catalog",
            new_callable=AsyncMock,
            return_value={"data": []},
        ) as get_catalog:
            response = await main_query.get_character_chat_catalog(
                adult_yn="N",
                user={"sub": "kc-user-1"},
                db=db,
            )

        get_catalog.assert_awaited_once_with(
            adult_yn="N",
            kc_user_id="kc-user-1",
            db=db,
        )
        assert response == {"data": []}

    async def test_character_preview_profile_uses_automatic_catalog_asset_gate(self):
        from app.exceptions import CustomResponseException
        from app.services.product import main_character_slot_service

        profile_result = MagicMock()
        profile_result.mappings.return_value.one_or_none.return_value = None
        db = AsyncMock()
        db.execute.return_value = profile_result

        with self.assertRaises(CustomResponseException):
            await main_character_slot_service.get_public_character_chat_preview(
                product_id=1182,
                character_scope_key="character:adelite",
                episode_no=1,
                db=db,
            )

        query = str(db.execute.await_args.args[0])
        normalized_query = " ".join(query.split())
        assert "FROM tb_main_character_slot" not in query
        assert "FROM tb_story_agent_context_summary inventory" in query
        assert "p.open_yn = 'Y'" in query
        assert "COALESCE(p.blind_yn, 'N') = 'N'" in query
        assert "COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'" in query
        assert "p.status_code = 'ongoing'" not in query
        assert "2026-03-01" not in query
        assert "COUNT(DISTINCT public_episode.episode_id)" in query
        assert ">= 15" in query
        assert "$.public_slot_eligible" not in query
        assert "$.public_chat_eligible" in query
        assert "$.display_safety.status" not in query
        assert "summary_type = 'character_rp_profile'" in query
        assert "summary_type = 'character_rp_examples'" in query
        profile_join = query.split(
            "INNER JOIN tb_story_agent_context_summary profile", 1
        )[1].split("WHERE", 1)[0]
        assert "profile.scope_key = COALESCE(" in profile_join
        assert "inventory.summary_text, '$.canonical_character_key'" in profile_join
        assert "$.protagonist_identity_scope_keys" in profile_join
        assert "$.source_character_keys" in profile_join
        assert "JSON_CONTAINS(" in profile_join
        assert "eligible_scene" not in query
        assert "eligible_episode_summary.summary_type = 'episode_summary'" in query
        assert "eligible_rp_example.episode_no BETWEEN 0 AND 1" not in query
        assert (
            "TRIM(COALESCE( eligible_episode_summary.summary_text, '' )) <> ''"
            in normalized_query
        )
        assert "examples.scope_key = COALESCE(" in query
        assert (
            "JSON_UNQUOTE(JSON_EXTRACT(examples.summary_text, '$.character_key'))"
            in query
        )

    async def test_character_preview_looks_up_episode_summary_by_episode_number(self):
        from app.exceptions import CustomResponseException
        from app.services.product import main_character_slot_service

        profile_result = MagicMock()
        profile_result.mappings.return_value.one_or_none.return_value = {
            "inventorySummaryText": "{}",
            "profileSummaryText": "{}",
        }
        scene_result = MagicMock()
        scene_result.mappings.return_value.all.return_value = []
        db = AsyncMock()
        db.execute.side_effect = [profile_result, scene_result]

        with self.assertRaises(CustomResponseException):
            await main_character_slot_service.get_public_character_chat_preview(
                product_id=1182,
                character_scope_key="character:adelite",
                episode_no=5,
                db=db,
            )

        query = str(db.execute.await_args_list[1].args[0])
        assert "episode_summary.episode_to = pe.episode_no" in query
        assert "CONCAT('episode:', pe.episode_id)" in query
        assert "episode_summary.scope_key = CONCAT('episode:', pe.episode_no)" not in query

    async def test_character_preview_defers_scene_eligibility_to_scene_query(self):
        from app.exceptions import CustomResponseException
        from app.services.product import main_character_slot_service

        profile_result = MagicMock()
        profile_result.mappings.return_value.one_or_none.return_value = {
            "inventorySummaryText": "{}",
            "profileSummaryText": "{}",
        }
        scene_result = MagicMock()
        scene_result.mappings.return_value.all.return_value = []
        db = AsyncMock()
        db.execute.side_effect = [profile_result, scene_result]

        with self.assertRaises(CustomResponseException):
            await main_character_slot_service.get_public_character_chat_preview(
                product_id=1182,
                character_scope_key="character:adelite",
                episode_no=5,
                db=db,
            )

        profile_query = "".join(str(db.execute.await_args_list[0].args[0]).split())
        scene_query = "".join(str(db.execute.await_args_list[1].args[0]).split())
        assert "eligible_scene" not in profile_query
        assert "eligible_episode_summary" in profile_query
        assert (
            "WITHmatched_sceneAS(" in scene_query
        )
        assert (
            "CROSSJOINJSON_TABLE(IF(JSON_VALID(scene.summary_text),"
            "scene.summary_text,JSON_OBJECT()),'$.scenes[*]'"
            in scene_query
        )
        assert "scene_gistVARCHAR(4096)PATH'$.scene_gist'" in scene_query
        assert (
            "LOWER(TRIM(JSON_UNQUOTE(JSON_EXTRACT("
            "scene.summary_text,'$.status'))))IN('ok','partial')"
            in scene_query
        )
        assert (
            "TRIM(COALESCE(preview_scene_row.scene_gist,''))<>''"
            in scene_query
        )
        assert "MIN(pe.episode_id)ASepisodeId" in scene_query
        assert (
            "GROUPBYscene.summary_id,scene.product_id,scene.episode_to"
            in scene_query
        )
        assert (
            scene_query.index(
                "GROUPBYscene.summary_id,scene.product_id,scene.episode_to"
            )
            < scene_query.index(
                "ORDERBYscene.episode_toDESC,scene.summary_idDESCLIMIT5"
            )
            < scene_query.index("FROMmatched_scene")
        )
        assert (
            "ANDEXISTS(SELECT1FROMJSON_TABLE("
            "IF(JSON_VALID(scene.summary_text),"
            not in scene_query
        )
        assert "scene.episode_to<=:episode_no" in scene_query
        assert "pe.use_yn='Y'" in scene_query
        assert "pe.open_yn='Y'" in scene_query
        assert "COALESCE(pe.price_type,'free')='free'" in scene_query
        assert (
            "preview_participant.participant_scope_key"
            "IN(__[POSTCOMPILE_character_scope_keys])"
            in scene_query
        )
        assert (
            "preview_action_owner.action_scope_key"
            "IN(__[POSTCOMPILE_character_scope_keys])"
            in scene_query
        )
        assert "SELECTDISTINCTscene.summary_text" not in scene_query

    async def test_roster_query_reads_only_active_character_inventory_v3(self):
        from app.services.product import main_character_slot_service

        db = AsyncMock()
        result = MagicMock()
        result.mappings.return_value.all.return_value = []
        db.execute.return_value = result

        response = await main_character_slot_service.get_admin_main_character_roster(
            product_id=1182,
            db=db,
        )

        query = str(db.execute.await_args.args[0])
        assert "summary_type = 'character_inventory_v3'" in query
        assert "is_active = 'Y'" in query
        assert "JSON_VALID(sacs.summary_text)" in query
        assert "COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'" in query
        assert "p.status_code = 'ongoing'" in query
        assert ">= 15" in query
        assert "MIN(COALESCE(" in query
        assert "pe.open_changed_date" in query
        assert ">= '2026-03-01 00:00:00'" in query
        assert "summary_type = 'character_rp_profile'" in query
        assert "summary_type = 'character_rp_examples'" in query
        assert "$.public_chat_eligible" in query
        assert "eligible_episode_summary.episode_to = 1" not in query
        assert "eligible_rp_example.episode_no BETWEEN 0 AND 1" not in query
        assert "JSON_LENGTH" in query
        assert "AS exampleCount" in query
        assert "AS sceneCount" in query
        assert "JSON_QUOTE" in query
        assert "character_inventory'" not in query
        assert "relation_inventory" not in query
        assert response == {"data": []}

    async def test_admin_rows_expose_the_same_public_quality_gate(self):
        from app.services.product import main_character_slot_service

        count_result = MagicMock()
        count_result.mappings.return_value.first.return_value = {"total_count": 0}
        list_result = MagicMock()
        list_result.mappings.return_value.all.return_value = []
        db = AsyncMock()
        db.execute.side_effect = [count_result, list_result]

        response = await main_character_slot_service.get_admin_main_character_slots(
            page=1,
            count_per_page=200,
            db=db,
        )

        query = str(db.execute.await_args_list[1].args[0])
        assert "AS publicEligible" in query
        assert "summary_type = 'episode_scene_extraction'" not in query
        assert "$.public_chat_eligible" in query
        assert "eligible_episode_summary.episode_to = 1" not in query
        assert "eligible_rp_example.episode_no BETWEEN 0 AND 1" not in query
        assert response["results"] == []

    async def test_product_search_only_returns_consented_products_with_fifteen_public_episodes(self):
        from app.services.product import main_character_slot_service

        db = AsyncMock()
        result = MagicMock()
        result.mappings.return_value.all.return_value = []
        db.execute.return_value = result

        response = await main_character_slot_service.search_admin_main_character_slot_products(
            search_word="테스트",
            limit=100,
            db=db,
        )

        query = str(db.execute.await_args.args[0])
        params = db.execute.await_args.args[1]
        assert "COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'" in query
        assert "p.status_code = 'ongoing'" in query
        assert "episode_stats.open_episode_count >= :minimum_open_episode_count" in query
        assert "episode_stats.first_public_episode_at >= :first_public_episode_at" in query
        assert "summary_type = 'character_inventory_v3'" in query
        assert "$.public_slot_eligible" in query
        assert "$.public_chat_eligible" in query
        assert "$.display_safety.status" in query
        assert "summary_type = 'character_rp_profile'" in query
        assert "summary_type = 'character_rp_examples'" in query
        assert "eligible_episode_summary.episode_to = 1" not in query
        assert "eligible_rp_example.episode_no BETWEEN 0 AND 1" not in query
        assert "{_chat_ready_rp_assets_predicate" not in query
        assert params["minimum_open_episode_count"] == 15
        assert params["first_public_episode_at"] == "2026-03-01 00:00:00"
        assert response == {"data": []}

    async def test_product_picker_lists_only_chat_ready_products_with_search_and_pagination(self):
        from app.services.product import main_character_slot_service

        count_result = MagicMock()
        count_result.mappings.return_value.first.return_value = {"total_count": 1}
        list_result = MagicMock()
        list_result.mappings.return_value.all.return_value = [
            {
                "productId": 1192,
                "title": "테스트 작품",
                "authorNickname": "테스트 작가",
                "coverImagePath": None,
                "openEpisodeCount": 15,
            }
        ]
        candidate_result = MagicMock()
        candidate_result.mappings.return_value.all.return_value = [
            {
                **_row(distinct_episode_count=15),
                "productId": 1192,
            }
        ]
        asset_result = MagicMock()
        asset_result.mappings.return_value.all.return_value = [
            {
                "productId": 1192,
                "scopeKey": "character:adelite",
                "summaryType": "character_rp_profile",
                "summaryText": json.dumps(
                    {
                        "character_key": "character:adelite",
                        "personality_core": ["신중함"],
                        "speech_style": {
                            "tone": ["차분함"],
                            "formality": "존댓말",
                            "sentence_length": "보통",
                        },
                    },
                    ensure_ascii=False,
                ),
                "exampleCount": 0,
            },
            {
                "productId": 1192,
                "scopeKey": "character:adelite",
                "summaryType": "character_rp_examples",
                "exampleCount": 5,
            },
        ]
        scene_result = MagicMock()
        scene_result.mappings.return_value.all.return_value = [
            {
                "productId": 1192,
                "summaryText": json.dumps(
                    {"characters": ["character:adelite"]}, ensure_ascii=False
                ),
            }
            for _ in range(5)
        ]
        db = AsyncMock()
        db.execute.side_effect = [
            count_result,
            list_result,
            candidate_result,
            asset_result,
            scene_result,
        ]

        response = await main_character_slot_service.get_admin_main_character_slot_products(
            page=2,
            count_per_page=20,
            search_word=" 테스트 ",
            db=db,
        )

        count_query = str(db.execute.await_args_list[0].args[0])
        list_query = str(db.execute.await_args_list[1].args[0])
        params = db.execute.await_args_list[1].args[1]
        for query in (count_query, list_query):
            assert "COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'" in query
            assert "p.status_code = 'ongoing'" in query
            assert "summary_type = 'character_inventory_v3'" in query
            assert "$.public_slot_eligible" in query
            assert "$.public_chat_eligible" in query
            assert "$.display_safety.status" in query
            assert "summary_type = 'character_rp_profile'" in query
            assert "summary_type = 'character_rp_examples'" in query
            assert "eligible_episode_summary.episode_to = 1" not in query
            assert "eligible_rp_example.episode_no BETWEEN 0 AND 1" not in query
            assert "JSON_LENGTH" in query
            assert ">= :minimum_open_episode_count" in query
            assert ">= :first_public_episode_at" in query
        assert "p.author_name LIKE :search_word" in list_query
        assert params["search_word"] == "%테스트%"
        assert params["minimum_open_episode_count"] == 15
        assert params["first_public_episode_at"] == "2026-03-01 00:00:00"
        assert params["limit_count"] == 20
        assert params["offset_count"] == 20
        candidate_query = str(db.execute.await_args_list[2].args[0])
        asset_query = str(db.execute.await_args_list[3].args[0])
        scene_query = str(db.execute.await_args_list[4].args[0])
        assert "INSTR" not in candidate_query
        assert "character_rp_profile" in asset_query
        assert "character_rp_examples" in asset_query
        assert "summary_type = 'episode_scene_extraction'" in scene_query
        assert response["total_count"] == 1
        assert response["results"][0]["productId"] == 1192
        assert response["results"][0]["chatQuality"] == "good"

    async def test_selection_validation_rejects_scope_missing_from_strict_roster(self):
        from app.exceptions import CustomResponseException
        from app.services.product import main_character_slot_service

        with patch.object(
            main_character_slot_service,
            "_load_eligible_main_character_roster",
            new_callable=AsyncMock,
            return_value=[],
        ):
            with self.assertRaises(CustomResponseException):
                await main_character_slot_service._ensure_character_slot_selection_eligible(
                    product_id=1182,
                    character_scope_key="character:ineligible",
                    db=object(),
                )

    async def test_selection_validation_rejects_character_without_scene_evidence(self):
        from app.exceptions import CustomResponseException
        from app.services.product import main_character_slot_service

        with patch.object(
            main_character_slot_service,
            "_load_eligible_main_character_roster",
            new_callable=AsyncMock,
            return_value=[
                {
                    "scopeKey": "character:broken",
                    "displayName": "분리된 인물",
                    "aliases": [],
                    "distinctEpisodeCount": 20,
                    "exampleCount": 5,
                    "sceneCount": 0,
                    "chatQuality": "insufficient",
                    "qualityReason": "캐릭터 장면 데이터 없음",
                }
            ],
        ):
            with self.assertRaises(CustomResponseException) as raised:
                await main_character_slot_service._ensure_character_slot_selection_eligible(
                    product_id=1149,
                    character_scope_key="character:broken",
                    db=object(),
                )

        self.assertIn("품질 미달", raised.exception.message)

    async def test_publish_now_adds_server_roster_name_without_closing_existing_cards(self):
        from app.schemas.admin import PostMainCharacterSlotPublishNowReqBody
        from app.services.product import main_character_slot_service

        req = PostMainCharacterSlotPublishNowReqBody(
            product_id=1182,
            character_scope_key="character:adelite",
            character_image_file_id=10,
            card_order=2,
        )
        db = AsyncMock()
        db.execute.return_value.lastrowid = 91

        with (
            patch.object(
                main_character_slot_service,
                "_ensure_character_slot_selection_eligible",
                new_callable=AsyncMock,
                return_value="아델리트",
            ) as ensure_selection,
            patch.object(
                main_character_slot_service,
                "_ensure_character_image_file",
                new_callable=AsyncMock,
            ) as ensure_image,
        ):
            result = await main_character_slot_service.publish_admin_main_character_slot_now(
                req_body=req,
                admin_user_id=7,
                db=db,
            )

        ensure_selection.assert_awaited_once_with(
            product_id=1182,
            character_scope_key="character:adelite",
            db=db,
        )
        ensure_image.assert_awaited_once_with(character_image_file_id=10, db=db)
        executed_sql = "\n".join(str(call.args[0]) for call in db.execute.await_args_list)
        assert "INSERT INTO tb_main_character_slot" in executed_sql
        assert "UPDATE tb_main_character_slot" not in executed_sql
        assert db.execute.await_args.kwargs == {}
        assert db.execute.await_args.args[1]["character_name"] == "아델리트"
        assert result == {"result": {"characterSlotId": 91}}

    async def test_update_keeps_existing_image_when_cms_does_not_upload_replacement(self):
        from app.schemas.admin import PutMainCharacterSlotReqBody
        from app.services.product import main_character_slot_service

        req = PutMainCharacterSlotReqBody(
            product_id=1182,
            character_scope_key="character:adelite",
            card_order=3,
            publish_start_at="2026-07-11T12:00:00+09:00",
        )
        db = AsyncMock()
        db.execute.return_value.rowcount = 1

        with (
            patch.object(
                main_character_slot_service,
                "_ensure_character_slot_selection_eligible",
                new_callable=AsyncMock,
                return_value="아델리트",
            ),
            patch.object(
                main_character_slot_service,
                "_ensure_character_image_file",
                new_callable=AsyncMock,
            ) as ensure_image,
        ):
            result = await main_character_slot_service.update_admin_main_character_slot(
                character_slot_id=91,
                req_body=req,
                admin_user_id=7,
                db=db,
            )

        ensure_image.assert_not_awaited()
        executed_sql = str(db.execute.await_args.args[0])
        assert "character_image_file_id = COALESCE" in executed_sql
        assert db.execute.await_args.args[1]["character_image_file_id"] is None
        assert result == {"result": {"characterSlotId": 91}}


def test_main_character_slot_router_service_model_schema_imports_and_routes():
    from app.models.product import MainCharacterSlot
    from app.routers.admin import admin_command, admin_query
    from app.routers.common import main_query
    from app.schemas.admin import PostMainCharacterSlotReqBody
    from app.services.product import main_character_slot_service

    assert MainCharacterSlot
    assert PostMainCharacterSlotReqBody
    assert main_character_slot_service
    assert "/products/main-character-slots" in {route.path for route in main_query.router.routes}
    assert "/products/character-chat-catalog" in {
        route.path for route in main_query.router.routes
    }
    assert "/products/{product_id}/character-chat-preview" in {
        route.path for route in main_query.router.routes
    }
    assert "/admins/main-character-slots" in {route.path for route in admin_query.router.routes}
    assert "/admins/main-character-slots/config" in {
        route.path for route in admin_query.router.routes
    }
    assert "/admins/main-character-slots/products" in {
        route.path for route in admin_query.router.routes
    }
    assert "/admins/main-character-slots/products/{product_id}/characters" in {
        route.path for route in admin_query.router.routes
    }
    assert "/admins/main-character-slots" in {route.path for route in admin_command.router.routes}
    assert "/admins/main-character-slots/config" in {
        route.path for route in admin_command.router.routes
    }


def test_build_character_chat_preview_uses_matching_scene_and_source_chunk():
    from app.services.product.main_character_slot_service import (
        build_character_chat_preview_payload,
    )

    source_text = "윤서하는 문 앞에 섰다.\n그녀는 은빛 열쇠를 들었다.\n밖에서 발소리가 가까워졌다."
    scene_text = json.dumps(
        {
            "episode_no": 5,
            "status": "ok",
            "scenes": [
                {
                    "scene_index": 1,
                    "scene_gist": "윤서하가 열쇠를 들고 동행자의 선택을 기다린다.",
                    "char_start": 0,
                    "char_end": len(source_text),
                    "participants": [
                        {"scope_key": "character:윤서하", "mention_label": "윤서하"}
                    ],
                }
            ],
        },
        ensure_ascii=False,
    )
    inventory_text = json.dumps(
        {
            "canonical_character_key": "character:윤서하",
            "display_name": "윤서하",
            "aliases": ["서하 황녀", "마지막 황녀"],
        },
        ensure_ascii=False,
    )
    profile_text = json.dumps(
        {
            "character_key": "character:윤서하",
            "role_label": "몰락한 왕가의 마지막 황녀",
            "personality_core": ["신중함", "책임감이 강함"],
            "speech_style": {
                "tone": ["차분한", "단정한"],
                "formality": "상황에 따라",
                "sentence_length": "보통",
            },
        },
        ensure_ascii=False,
    )

    payload = build_character_chat_preview_payload(
        character_scope_key="character:윤서하",
        profile_row={
            "inventorySummaryText": inventory_text,
            "profileSummaryText": profile_text,
        },
        scene_row={
            "episodeId": 30552,
            "episodeNo": 5,
            "episodeTitle": "왕관 없는 선택",
            "episodeSummaryText": "윤서하가 도시의 사람들을 먼저 구하기로 한다.",
            "sceneSummaryText": scene_text,
        },
        chunk_rows=[
            {
                "charStart": 0,
                "charEnd": len(source_text),
                "text": source_text,
            }
        ],
    )

    assert payload == {
        "episodeNo": 5,
        "episodeTitle": "왕관 없는 선택",
        "episodeSummary": "윤서하가 도시의 사람들을 먼저 구하기로 한다.",
        "roleLabel": "몰락한 왕가의 마지막 황녀",
        "aliases": ["서하 황녀", "마지막 황녀"],
        "personalityCore": ["신중함", "책임감이 강함"],
        "speechStyle": {
            "tone": ["차분한", "단정한"],
            "formality": "상황에 따라",
            "sentenceLength": "보통",
        },
        "sceneSummary": "윤서하가 열쇠를 들고 동행자의 선택을 기다린다.",
        "sceneExcerpt": source_text,
    }


def test_build_character_chat_preview_matches_action_owner_inventory_alias():
    from app.services.product.main_character_slot_service import (
        build_character_chat_preview_payload,
    )

    source_text = "방호영은 검을 뽑아 문 앞을 막았다."
    payload = build_character_chat_preview_payload(
        character_scope_key="character:조렌테이머",
        profile_row={
            "inventorySummaryText": json.dumps(
                {
                    "canonical_character_key": "character:조렌테이머",
                    "display_name": "조렌테이머",
                    "protagonist_identity_scope_keys": ["character:방호영"],
                    "source_character_keys": ["protagonist:named:방호영"],
                },
                ensure_ascii=False,
            ),
            "profileSummaryText": json.dumps(
                {
                    "character_key": "character:방호영",
                    "personality_core": ["단호함"],
                    "speech_style": {
                        "tone": ["낮고 단정함"],
                        "formality": "반말",
                        "sentence_length": "짧음",
                    },
                },
                ensure_ascii=False,
            ),
        },
        scene_row={
            "episodeId": 1,
            "episodeNo": 1,
            "episodeTitle": "문 앞에서",
            "episodeSummaryText": "방호영이 문을 지킨다.",
            "sceneSummaryText": json.dumps(
                {
                    "scenes": [
                        {
                            "scene_index": 1,
                            "scene_gist": "방호영이 검을 뽑아 적을 막는다.",
                            "char_start": 0,
                            "char_end": len(source_text),
                            "participants": [],
                            "action_ownership": [
                                {
                                    "actor_scope_key": "character:방호영",
                                    "action": "검을 뽑는다.",
                                }
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        },
        chunk_rows=[
            {
                "charStart": 0,
                "charEnd": len(source_text),
                "text": source_text,
            }
        ],
    )

    assert payload is not None
    assert payload["sceneSummary"] == "방호영이 검을 뽑아 적을 막는다."
    assert payload["sceneExcerpt"] == source_text


@pytest.mark.parametrize(
    ("field_name", "malformed_value"),
    [
        ("scene_index", "not-a-number"),
        ("char_start", "not-a-number"),
        ("char_end", "not-a-number"),
    ],
)
def test_build_character_chat_preview_rejects_malformed_scene_coordinates(
    field_name,
    malformed_value,
):
    from app.services.product.main_character_slot_service import (
        build_character_chat_preview_payload,
    )

    source_text = "장면 원문"
    scene = {
        "scene_index": 1,
        "scene_gist": "장면 요약",
        "char_start": 0,
        "char_end": len(source_text),
        "participants": [{"scope_key": "character:lead"}],
    }
    scene[field_name] = malformed_value

    payload = build_character_chat_preview_payload(
        character_scope_key="character:lead",
        profile_row={
            "inventorySummaryText": json.dumps(
                {"canonical_character_key": "character:lead"}
            ),
            "profileSummaryText": json.dumps(
                {
                    "character_key": "character:lead",
                    "personality_core": ["신중함"],
                    "speech_style": {
                        "tone": ["차분함"],
                        "formality": "반말",
                        "sentence_length": "짧음",
                    },
                }
            ),
        },
        scene_row={
            "episodeNo": 1,
            "sceneSummaryText": json.dumps({"scenes": [scene]}),
        },
        chunk_rows=[
            {
                "charStart": 0,
                "charEnd": len(source_text),
                "text": source_text,
            }
        ],
    )

    assert payload is None


def test_build_character_chat_preview_rejects_incomplete_profile_contract():
    from app.services.product.main_character_slot_service import (
        build_character_chat_preview_payload,
    )

    payload = build_character_chat_preview_payload(
        character_scope_key="character:lead",
        profile_row={
            "inventorySummaryText": json.dumps(
                {"canonical_character_key": "character:lead"}
            ),
            "profileSummaryText": json.dumps(
                {
                    "character_key": "character:lead",
                    "personality_core": [],
                    "speech_style": {
                        "tone": [],
                        "formality": "",
                        "sentence_length": "",
                    },
                }
            ),
        },
        scene_row={
            "episodeNo": 1,
            "sceneSummaryText": json.dumps(
                {
                    "scenes": [
                        {
                            "scene_index": 1,
                            "scene_gist": "장면 요약",
                            "char_start": 0,
                            "char_end": 4,
                            "participants": [{"scope_key": "character:lead"}],
                        }
                    ]
                }
            ),
        },
        chunk_rows=[{"charStart": 0, "charEnd": 4, "text": "장면 원문"}],
    )

    assert payload is None
