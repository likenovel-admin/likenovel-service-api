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
):
    return {
        "scopeKey": scope_key,
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


def test_main_character_slot_roster_accepts_chat_eligible_main_and_major_characters():
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
            _row("character:false", public_chat_eligible=False),
            _row("character:string", public_chat_eligible="true"),
            _row("character:missing", public_chat_eligible=None),
            _row("character:fail", safety_status="fail"),
            _row("character:review", safety_status="review"),
        ]
    )

    assert roster == [
        {
            "scopeKey": "character:adelite",
            "displayName": "아델리트",
            "aliases": ["아델리트", "공녀"],
        },
        {
            "scopeKey": "character:follower",
            "displayName": "추종자",
            "aliases": ["추종자"],
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


def test_chat_quality_is_normal_when_a_selectable_character_has_few_scenes():
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
        1170: "normal"
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


def test_public_main_character_slot_query_filters_current_cards_and_stably_orders_all():
    from app.services.product.main_character_slot_service import (
        build_public_main_character_slots_query,
    )

    query = build_public_main_character_slots_query()

    assert "mcs.use_yn = 'Y'" in query
    assert "mcs.deleted_yn = 'N'" in query
    assert "mcs.publish_start_date <= NOW()" in query
    assert "(mcs.publish_end_date IS NULL OR mcs.publish_end_date > NOW())" in query
    assert "p.open_yn = 'Y'" in query
    assert "COALESCE(p.blind_yn, 'N') = 'N'" in query
    assert "COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'" in query
    assert ">= 15" in query
    assert "(:adult_yn = 'Y' OR p.ratings_code != 'adult')" in query
    assert "SELECT COUNT(*)" in query
    assert "FROM tb_product_episode pe" in query
    assert "q.group_type = 'character'" in query
    assert "ORDER BY mcs.card_order ASC, mcs.main_character_slot_id ASC" in query
    assert "ROW_NUMBER()" not in query


def test_main_character_slot_request_schema_enforces_optional_period_contract():
    from app.schemas.admin import (
        PostMainCharacterSlotReqBody,
        PutMainCharacterSlotReqBody,
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
        assert ">= 15" in query
        assert "summary_type = 'character_rp_profile'" in query
        assert "summary_type = 'character_rp_examples'" in query
        assert "JSON_LENGTH" in query
        assert "character_inventory'" not in query
        assert "relation_inventory" not in query
        assert response == {"data": []}

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
        assert "episode_stats.open_episode_count >= :minimum_open_episode_count" in query
        assert "summary_type = 'character_inventory_v3'" in query
        assert "$.public_chat_eligible" in query
        assert "$.display_safety.status" in query
        assert params["minimum_open_episode_count"] == 15
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
            assert "summary_type = 'character_inventory_v3'" in query
            assert "$.public_chat_eligible" in query
            assert "$.display_safety.status" in query
            assert "summary_type = 'character_rp_profile'" in query
            assert "summary_type = 'character_rp_examples'" in query
            assert "JSON_LENGTH" in query
            assert ">= :minimum_open_episode_count" in query
        assert "p.author_name LIKE :search_word" in list_query
        assert params["search_word"] == "%테스트%"
        assert params["minimum_open_episode_count"] == 15
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
    assert "/admins/main-character-slots" in {route.path for route in admin_query.router.routes}
    assert "/admins/main-character-slots/products" in {
        route.path for route in admin_query.router.routes
    }
    assert "/admins/main-character-slots/products/{product_id}/characters" in {
        route.path for route in admin_query.router.routes
    }
    assert "/admins/main-character-slots" in {route.path for route in admin_command.router.routes}
