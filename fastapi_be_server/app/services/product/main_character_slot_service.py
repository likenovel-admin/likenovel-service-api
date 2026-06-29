from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import ErrorMessages
from app.exceptions import CustomResponseException
import app.schemas.admin as admin_schema
import app.services.product.main_single_slot_service as main_single_slot_service
from app.utils.query import get_pagination_params
from app.utils.response import build_paginated_response


# 캐릭터 이미지(file_group_id)를 CDN 경로로 풀어주는 공용 조인.
CHARACTER_IMAGE_JOIN = """
    LEFT JOIN (
        SELECT cf.file_group_id, cfi.file_path
        FROM tb_common_file cf
        JOIN tb_common_file_item cfi ON cf.file_group_id = cfi.file_group_id
        WHERE cf.use_yn = 'Y'
          AND cfi.use_yn = 'Y'
          AND cf.group_type = 'character'
    ) char_img ON char_img.file_group_id = mcs.character_image_file_id
"""


def build_active_main_character_slots_query() -> str:
    return f"""
        SELECT
            mcs.character_slot_id AS characterSlotId,
            mcs.product_id AS productId,
            mcs.character_scope_key AS characterScopeKey,
            mcs.character_name AS characterName,
            char_img.file_path AS characterImagePath,
            mcs.card_order AS cardOrder,
            p.title AS productTitle,
            p.author_name AS authorNickname
        FROM tb_main_character_slot mcs
        INNER JOIN tb_product p ON p.product_id = mcs.product_id
        INNER JOIN (
            SELECT product_id, COUNT(*) AS open_episode_count
            FROM tb_product_episode
            WHERE use_yn = 'Y' AND open_yn = 'Y'
            GROUP BY product_id
        ) episode_stats ON episode_stats.product_id = mcs.product_id
        {CHARACTER_IMAGE_JOIN}
        WHERE mcs.cancelled_at IS NULL
          AND mcs.publish_start_at <= NOW()
          AND (mcs.publish_end_at IS NULL OR mcs.publish_end_at > NOW())
          AND p.open_yn = 'Y'
          AND COALESCE(p.blind_yn, 'N') = 'N'
          AND COALESCE(episode_stats.open_episode_count, 0) > 0
          AND (:adult_yn = 'Y' OR p.ratings_code != 'adult')
        ORDER BY mcs.card_order ASC, mcs.character_slot_id ASC
    """


def convert_main_character_slot_row(row):
    data = dict(row)
    return {
        "characterSlotId": data.get("characterSlotId"),
        "productId": data.get("productId"),
        "characterScopeKey": data.get("characterScopeKey"),
        "characterName": data.get("characterName"),
        "characterImagePath": data.get("characterImagePath"),
        "cardOrder": data.get("cardOrder"),
        "productTitle": data.get("productTitle"),
        "authorNickname": data.get("authorNickname"),
    }


async def get_public_main_character_slots(adult_yn: str, db: AsyncSession):
    query = text(build_active_main_character_slots_query())
    result = await db.execute(query, {"adult_yn": adult_yn})
    rows = result.mappings().all()
    return {"data": [convert_main_character_slot_row(row) for row in rows]}


# 메인 캐릭터 구좌는 채팅보다 엄격한 공개 게이트를 쓴다. v3 인벤토리 summary_type.
SLOT_CHARACTER_INVENTORY_SUMMARY_TYPE = "character_inventory_v3"


def _is_slot_eligible_payload(payload) -> bool:
    """공개 메인 구좌 노출 게이트: display_safety pass + public_slot_eligible + 주인공.

    채팅용 _is_websochat_inventory_rp_eligible(public_chat_eligible 중심)보다 엄격하다.
    """
    if not isinstance(payload, dict) or not payload:
        return False
    display_safety = payload.get("display_safety")
    if not isinstance(display_safety, dict):
        return False
    if str(display_safety.get("status") or "").strip().lower() != "pass":
        return False
    if payload.get("public_slot_eligible") is not True:
        return False
    if str(payload.get("work_role") or "").strip().lower() != "main_protagonist":
        return False
    return True


def _build_slot_character_roster(rows) -> list[dict]:
    """character_inventory_v3 row에서 슬롯 적격 주인공만 추려 contract(scopeKey/displayName/aliases) 반환."""
    from app.services.websochat.websochat_utils import _extract_websochat_json_object

    seen_scope_keys: set[str] = set()
    characters: list[dict] = []
    for row in rows:
        data = dict(row)
        scope_key = str(data.get("scopeKey") or "").strip()
        if not scope_key or scope_key in seen_scope_keys:
            continue
        payload = _extract_websochat_json_object(str(data.get("summaryText") or "")) or {}
        if not _is_slot_eligible_payload(payload):
            continue
        display_name = str(payload.get("display_name") or "").strip()
        if not display_name:
            continue
        seen_scope_keys.add(scope_key)
        aliases = [
            str(alias).strip()
            for alias in (payload.get("aliases") or [])
            if str(alias).strip()
        ]
        characters.append(
            {"scopeKey": scope_key, "displayName": display_name, "aliases": aliases}
        )
    return characters


async def get_product_character_roster(product_id: int, db: AsyncSession):
    # 메인 캐릭터 구좌 전용 슬롯 로스터: character_inventory_v3의 공개 슬롯 게이트를 통과한 주인공만.
    # v3 데이터가 없으면 빈 배열(월드컵 후보 fallback 없음 — 공개 메인 노출 안전 게이트).
    result = await db.execute(
        text(
            """
            SELECT scope_key AS scopeKey, summary_text AS summaryText
            FROM tb_story_agent_context_summary
            WHERE product_id = :product_id
              AND summary_type = :summary_type
              AND is_active = 'Y'
            ORDER BY summary_id DESC
            """
        ),
        {
            "product_id": product_id,
            "summary_type": SLOT_CHARACTER_INVENTORY_SUMMARY_TYPE,
        },
    )
    return {"data": _build_slot_character_roster(result.mappings().all())}


def _normalize_optional_datetime(value):
    if value in (None, ""):
        return None
    return value


def _main_character_slot_params(req_body, admin_user_id: int | None = None) -> dict:
    return {
        "product_id": req_body.product_id,
        "character_scope_key": req_body.character_scope_key,
        "character_name": req_body.character_name,
        "character_image_file_id": req_body.character_image_file_id,
        "card_order": req_body.card_order,
        "publish_start_at": getattr(req_body, "publish_start_at", None),
        "publish_end_at": _normalize_optional_datetime(
            getattr(req_body, "publish_end_at", None)
        ),
        "created_id": admin_user_id,
        "updated_id": admin_user_id,
    }


async def _ensure_character_in_roster(
    product_id: int, character_scope_key: str, db: AsyncSession
):
    await main_single_slot_service._ensure_product_eligible(product_id, db)
    roster = await get_product_character_roster(product_id, db)
    valid_scope_keys = {item["scopeKey"] for item in roster["data"]}
    if character_scope_key not in valid_scope_keys:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_PRODUCT_INFO,
        )


async def get_admin_main_character_slots(
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    count_query = text("""
        SELECT COUNT(*) AS total_count
        FROM tb_main_character_slot mcs
    """)
    count_result = await db.execute(count_query)
    total_count = dict(count_result.mappings().first()).get("total_count", 0)

    limit_clause, limit_params = get_pagination_params(page, count_per_page)
    query = text(f"""
        SELECT
            mcs.character_slot_id AS characterSlotId,
            mcs.product_id AS productId,
            mcs.character_scope_key AS characterScopeKey,
            mcs.character_name AS characterName,
            mcs.character_image_file_id AS characterImageFileId,
            char_img.file_path AS characterImagePath,
            mcs.card_order AS cardOrder,
            p.title AS productTitle,
            p.author_name AS authorNickname,
            mcs.publish_start_at AS publishStartAt,
            mcs.publish_end_at AS publishEndAt,
            mcs.cancelled_at AS cancelledAt,
            mcs.created_date AS createdDate,
            mcs.updated_date AS updatedDate
        FROM tb_main_character_slot mcs
        INNER JOIN tb_product p ON p.product_id = mcs.product_id
        {CHARACTER_IMAGE_JOIN}
        ORDER BY mcs.card_order ASC, mcs.publish_start_at DESC, mcs.character_slot_id DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    return build_paginated_response(
        result.mappings().all(), total_count, page, count_per_page
    )


async def search_admin_main_character_slot_products(
    search_word: str | None,
    limit: int,
    db: AsyncSession,
):
    # 작품 검색 조건은 단일구좌와 동일하다(공개 작품 + 공개 회차 보유).
    return await main_single_slot_service.search_admin_main_single_slot_products(
        search_word, limit, db
    )


async def post_admin_main_character_slot(
    req_body: admin_schema.PostMainCharacterSlotReqBody,
    admin_user_id: int | None,
    db: AsyncSession,
):
    await _ensure_character_in_roster(
        req_body.product_id, req_body.character_scope_key, db
    )
    params = _main_character_slot_params(req_body, admin_user_id=admin_user_id)
    query = text("""
        INSERT INTO tb_main_character_slot (
            product_id,
            character_scope_key,
            character_name,
            character_image_file_id,
            card_order,
            publish_start_at,
            publish_end_at,
            created_id,
            updated_id
        ) VALUES (
            :product_id,
            :character_scope_key,
            :character_name,
            :character_image_file_id,
            :card_order,
            COALESCE(:publish_start_at, NOW()),
            :publish_end_at,
            :created_id,
            :updated_id
        )
    """)
    await db.execute(query, params)
    return {"result": req_body}


async def publish_admin_main_character_slot_now(
    req_body: admin_schema.PostMainCharacterSlotPublishNowReqBody,
    admin_user_id: int | None,
    db: AsyncSession,
):
    # 캐러셀은 카드가 공존하므로 단일구좌처럼 기존 노출을 닫지 않고, 즉시 노출 카드를 추가한다.
    await _ensure_character_in_roster(
        req_body.product_id, req_body.character_scope_key, db
    )
    params = _main_character_slot_params(req_body, admin_user_id=admin_user_id)
    query = text("""
        INSERT INTO tb_main_character_slot (
            product_id,
            character_scope_key,
            character_name,
            character_image_file_id,
            card_order,
            publish_start_at,
            publish_end_at,
            created_id,
            updated_id
        ) VALUES (
            :product_id,
            :character_scope_key,
            :character_name,
            :character_image_file_id,
            :card_order,
            NOW(),
            NULL,
            :created_id,
            :updated_id
        )
    """)
    await db.execute(query, params)
    return {"result": req_body}


async def update_admin_main_character_slot(
    character_slot_id: int,
    req_body: admin_schema.PutMainCharacterSlotReqBody,
    admin_user_id: int | None,
    db: AsyncSession,
):
    await _ensure_character_in_roster(
        req_body.product_id, req_body.character_scope_key, db
    )
    params = _main_character_slot_params(req_body, admin_user_id=admin_user_id)
    params["character_slot_id"] = character_slot_id
    query = text("""
        UPDATE tb_main_character_slot
        SET
            product_id = :product_id,
            character_scope_key = :character_scope_key,
            character_name = :character_name,
            character_image_file_id = :character_image_file_id,
            card_order = :card_order,
            publish_start_at = COALESCE(:publish_start_at, publish_start_at),
            publish_end_at = :publish_end_at,
            updated_id = :updated_id
        WHERE character_slot_id = :character_slot_id
          AND cancelled_at IS NULL
    """)
    result = await db.execute(query, params)
    if result.rowcount == 0:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_RECOMMEND_SLOT,
        )
    return {"result": {"characterSlotId": character_slot_id}}


async def cancel_admin_main_character_slot(
    character_slot_id: int,
    admin_user_id: int | None,
    db: AsyncSession,
):
    query = text("""
        UPDATE tb_main_character_slot
        SET cancelled_at = NOW(), updated_id = :updated_id
        WHERE character_slot_id = :character_slot_id
          AND cancelled_at IS NULL
    """)
    result = await db.execute(
        query,
        {"character_slot_id": character_slot_id, "updated_id": admin_user_id},
    )
    if result.rowcount == 0:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_RECOMMEND_SLOT,
        )
    return {"result": {"characterSlotId": character_slot_id}}
