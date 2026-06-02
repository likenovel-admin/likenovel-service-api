from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import ErrorMessages
from app.exceptions import CustomResponseException
import app.schemas.admin as admin_schema
import app.services.product.product_service as product_service
from app.utils.query import get_pagination_params
from app.utils.response import build_paginated_response


def build_active_main_single_slots_query(user_id: int | None = None) -> str:
    query_parts = product_service.get_select_fields_and_joins_for_home_card_product(
        user_id=user_id
    )
    return f"""
        SELECT
            active_slots.single_slot_id as singleSlotId,
            active_slots.slot_key as slotKey,
            active_slots.slot_name as slotName,
            active_slots.slot_order as slotOrder,
            active_slots.summary_text as summaryText,
            {query_parts["select_fields"]}
        FROM (
            SELECT
                mss.*,
                ROW_NUMBER() OVER (
                    PARTITION BY mss.slot_key
                    ORDER BY mss.publish_start_at DESC, mss.single_slot_id DESC
                ) AS rn
            FROM tb_main_single_slot mss
            WHERE mss.cancelled_at IS NULL
              AND mss.publish_start_at <= NOW()
              AND (mss.publish_end_at IS NULL OR mss.publish_end_at > NOW())
        ) active_slots
        INNER JOIN tb_product p ON p.product_id = active_slots.product_id
        {query_parts["joins"]}
        WHERE active_slots.rn = 1
          AND p.open_yn = 'Y'
          AND COALESCE(p.blind_yn, 'N') = 'N'
          AND COALESCE(episode_stats.open_episode_count, 0) > 0
          AND (:adult_yn = 'Y' OR p.ratings_code != 'adult')
        ORDER BY active_slots.slot_order ASC, active_slots.slot_key ASC
    """


def build_publish_now_close_query() -> str:
    return """
        UPDATE tb_main_single_slot
        SET publish_end_at = NOW(), updated_id = :updated_id
        WHERE slot_key = :slot_key
          AND cancelled_at IS NULL
          AND publish_start_at <= NOW()
          AND (publish_end_at IS NULL OR publish_end_at > NOW())
    """


def build_update_main_single_slot_query() -> str:
    return """
        UPDATE tb_main_single_slot
        SET
            slot_key = :slot_key,
            slot_name = :slot_name,
            slot_order = :slot_order,
            product_id = :product_id,
            summary_text = :summary_text,
            publish_start_at = COALESCE(:publish_start_at, publish_start_at),
            publish_end_at = :publish_end_at,
            updated_id = :updated_id
        WHERE single_slot_id = :single_slot_id
          AND cancelled_at IS NULL
    """


def convert_main_single_slot_row(row):
    data = dict(row)
    slot = {
        "singleSlotId": data.pop("singleSlotId"),
        "slotKey": data.pop("slotKey"),
        "slotName": data.pop("slotName"),
        "slotOrder": data.pop("slotOrder"),
        "summaryText": data.pop("summaryText"),
        "product": product_service.convert_home_card_product_data(data),
    }
    return slot


async def get_public_main_single_slots(
    kc_user_id: str | None,
    adult_yn: str,
    db: AsyncSession,
):
    user_id = await product_service.get_user_id(kc_user_id, db) if kc_user_id else None
    query = text(build_active_main_single_slots_query(user_id=user_id))
    result = await db.execute(query, {"adult_yn": adult_yn})
    rows = result.mappings().all()
    return {"data": [convert_main_single_slot_row(row) for row in rows]}


def _normalize_optional_datetime(value):
    if value in (None, ""):
        return None
    return value


def _main_single_slot_params(req_body, admin_user_id: int | None = None) -> dict:
    return {
        "slot_key": req_body.slot_key,
        "slot_name": req_body.slot_name,
        "slot_order": req_body.slot_order,
        "product_id": req_body.product_id,
        "summary_text": req_body.summary_text,
        "publish_start_at": getattr(req_body, "publish_start_at", None),
        "publish_end_at": _normalize_optional_datetime(
            getattr(req_body, "publish_end_at", None)
        ),
        "created_id": admin_user_id,
        "updated_id": admin_user_id,
    }


async def _ensure_product_eligible(product_id: int, db: AsyncSession):
    query = text("""
        SELECT p.product_id
        FROM tb_product p
        INNER JOIN (
            SELECT product_id, COUNT(*) AS open_episode_count
            FROM tb_product_episode
            WHERE use_yn = 'Y' AND open_yn = 'Y'
            GROUP BY product_id
        ) episode_stats ON episode_stats.product_id = p.product_id
        WHERE p.product_id = :product_id
          AND p.open_yn = 'Y'
          AND COALESCE(p.blind_yn, 'N') = 'N'
          AND COALESCE(episode_stats.open_episode_count, 0) > 0
    """)
    result = await db.execute(query, {"product_id": product_id})
    if result.mappings().one_or_none() is None:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_PRODUCT_INFO,
        )


async def get_admin_main_single_slots(
    slot_key: str | None,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    where = "WHERE (:slot_key IS NULL OR mss.slot_key = :slot_key)"
    params = {"slot_key": slot_key}
    count_query = text(f"""
        SELECT COUNT(*) AS total_count
        FROM tb_main_single_slot mss
        {where}
    """)
    count_result = await db.execute(count_query, params)
    total_count = dict(count_result.mappings().first()).get("total_count", 0)

    limit_clause, limit_params = get_pagination_params(page, count_per_page)
    params.update(limit_params)
    query = text(f"""
        SELECT
            mss.single_slot_id as singleSlotId,
            mss.slot_key as slotKey,
            mss.slot_name as slotName,
            mss.slot_order as slotOrder,
            mss.product_id as productId,
            p.title as productTitle,
            p.author_name as authorNickname,
            mss.summary_text as summaryText,
            mss.publish_start_at as publishStartAt,
            mss.publish_end_at as publishEndAt,
            mss.cancelled_at as cancelledAt,
            mss.created_date as createdDate,
            mss.updated_date as updatedDate
        FROM tb_main_single_slot mss
        INNER JOIN tb_product p ON p.product_id = mss.product_id
        {where}
        ORDER BY mss.slot_order ASC, mss.publish_start_at DESC, mss.single_slot_id DESC
        {limit_clause}
    """)
    result = await db.execute(query, params)
    return build_paginated_response(
        result.mappings().all(), total_count, page, count_per_page
    )


async def search_admin_main_single_slot_products(
    search_word: str | None,
    limit: int,
    db: AsyncSession,
):
    normalized_search_word = (search_word or "").strip()
    params = {
        "search_word": f"%{normalized_search_word}%",
        "limit_count": limit,
    }
    query = text("""
        SELECT
            p.product_id as productId,
            p.title,
            p.author_name as authorNickname,
            cf.file_path as coverImagePath,
            episode_stats.open_episode_count as openEpisodeCount
        FROM tb_product p
        INNER JOIN (
            SELECT product_id, COUNT(*) AS open_episode_count
            FROM tb_product_episode
            WHERE use_yn = 'Y' AND open_yn = 'Y'
            GROUP BY product_id
        ) episode_stats ON episode_stats.product_id = p.product_id
        LEFT JOIN (
            SELECT cf.file_group_id, cfi.file_path
            FROM tb_common_file cf
            JOIN tb_common_file_item cfi ON cf.file_group_id = cfi.file_group_id
            WHERE cf.use_yn = 'Y'
              AND cfi.use_yn = 'Y'
              AND cf.group_type = 'cover'
        ) cf ON cf.file_group_id = p.thumbnail_file_id
        WHERE p.open_yn = 'Y'
          AND COALESCE(p.blind_yn, 'N') = 'N'
          AND (:search_word = '%%' OR p.title LIKE :search_word)
        ORDER BY p.updated_date DESC, p.product_id DESC
        LIMIT :limit_count
    """)
    result = await db.execute(query, params)
    return {"data": [dict(row) for row in result.mappings().all()]}


async def post_admin_main_single_slot(
    req_body: admin_schema.PostMainSingleSlotReqBody,
    admin_user_id: int | None,
    db: AsyncSession,
):
    await _ensure_product_eligible(req_body.product_id, db)
    params = _main_single_slot_params(req_body, admin_user_id=admin_user_id)
    query = text("""
        INSERT INTO tb_main_single_slot (
            slot_key,
            slot_name,
            slot_order,
            product_id,
            summary_text,
            publish_start_at,
            publish_end_at,
            created_id,
            updated_id
        ) VALUES (
            :slot_key,
            :slot_name,
            :slot_order,
            :product_id,
            :summary_text,
            :publish_start_at,
            :publish_end_at,
            :created_id,
            :updated_id
        )
    """)
    await db.execute(query, params)
    return {"result": req_body}


async def publish_admin_main_single_slot_now(
    req_body: admin_schema.PostMainSingleSlotPublishNowReqBody,
    admin_user_id: int | None,
    db: AsyncSession,
):
    await _ensure_product_eligible(req_body.product_id, db)
    close_query = text(build_publish_now_close_query())
    await db.execute(
        close_query,
        {"slot_key": req_body.slot_key, "updated_id": admin_user_id},
    )
    insert_query = text("""
        INSERT INTO tb_main_single_slot (
            slot_key,
            slot_name,
            slot_order,
            product_id,
            summary_text,
            publish_start_at,
            publish_end_at,
            created_id,
            updated_id
        ) VALUES (
            :slot_key,
            :slot_name,
            :slot_order,
            :product_id,
            :summary_text,
            NOW(),
            NULL,
            :created_id,
            :updated_id
        )
    """)
    await db.execute(
        insert_query,
        _main_single_slot_params(req_body, admin_user_id=admin_user_id),
    )
    return {"result": req_body}


async def cancel_admin_main_single_slot(
    single_slot_id: int,
    admin_user_id: int | None,
    db: AsyncSession,
):
    query = text("""
        UPDATE tb_main_single_slot
        SET cancelled_at = NOW(), updated_id = :updated_id
        WHERE single_slot_id = :single_slot_id
          AND cancelled_at IS NULL
    """)
    result = await db.execute(
        query,
        {"single_slot_id": single_slot_id, "updated_id": admin_user_id},
    )
    if result.rowcount == 0:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_RECOMMEND_SLOT,
        )
    return {"result": {"singleSlotId": single_slot_id}}


async def update_admin_main_single_slot(
    single_slot_id: int,
    req_body: admin_schema.PutMainSingleSlotReqBody,
    admin_user_id: int | None,
    db: AsyncSession,
):
    await _ensure_product_eligible(req_body.product_id, db)
    params = _main_single_slot_params(req_body, admin_user_id=admin_user_id)
    params["single_slot_id"] = single_slot_id
    result = await db.execute(text(build_update_main_single_slot_query()), params)
    if result.rowcount == 0:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_RECOMMEND_SLOT,
        )
    return {"result": {"singleSlotId": single_slot_id}}
