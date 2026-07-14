from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import app.schemas.admin as admin_schema
from app.exceptions import CustomResponseException
from app.services.websochat.websochat_utils import _extract_websochat_json_object
from app.utils.query import get_file_path_sub_query, get_pagination_params
from app.utils.response import build_paginated_response


def _normalize_aliases(raw_aliases) -> list[str]:
    aliases: list[str] = []
    if not isinstance(raw_aliases, list):
        return aliases
    for raw_alias in raw_aliases:
        alias = str(raw_alias or "").strip()
        if alias and alias not in aliases:
            aliases.append(alias)
    return aliases


def extract_eligible_main_character_roster(rows) -> list[dict]:
    roster: list[dict] = []
    seen_scope_keys: set[str] = set()
    for row in rows:
        row_data = dict(row)
        payload = _extract_websochat_json_object(
            str(row_data.get("summaryText") or row_data.get("summary_text") or "")
        )
        if not payload:
            continue
        display_safety = payload.get("display_safety")
        if not isinstance(display_safety, dict):
            continue
        if str(display_safety.get("status") or "").strip().lower() != "pass":
            continue
        if payload.get("public_slot_eligible") is not True:
            continue
        if str(payload.get("work_role") or "").strip() != "main_protagonist":
            continue

        scope_key = str(payload.get("canonical_character_key") or "").strip()
        display_name = str(payload.get("display_name") or "").strip()
        if not scope_key or not display_name or scope_key in seen_scope_keys:
            continue
        seen_scope_keys.add(scope_key)
        roster.append(
            {
                "scopeKey": scope_key,
                "displayName": display_name,
                "aliases": _normalize_aliases(payload.get("aliases")),
            }
        )
    return roster


async def _load_eligible_main_character_roster(
    product_id: int, db: AsyncSession
) -> list[dict]:
    result = await db.execute(
        text("""
            SELECT scope_key AS scopeKey, summary_text AS summaryText
            FROM tb_story_agent_context_summary
            WHERE product_id = :product_id
              AND summary_type = 'character_inventory_v3'
              AND is_active = 'Y'
            ORDER BY summary_id DESC
        """),
        {"product_id": product_id},
    )
    return extract_eligible_main_character_roster(result.mappings().all())


async def get_admin_main_character_roster(product_id: int, db: AsyncSession):
    return {"data": await _load_eligible_main_character_roster(product_id, db)}


async def _ensure_character_slot_selection_eligible(
    *,
    product_id: int,
    character_scope_key: str,
    db: AsyncSession,
) -> str:
    roster = await _load_eligible_main_character_roster(product_id, db)
    selected = next(
        (item for item in roster if item["scopeKey"] == character_scope_key),
        None,
    )
    if selected is None:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="메인 주인공 카드에 사용할 수 없는 캐릭터입니다.",
        )
    return selected["displayName"]


async def _ensure_character_image_file(
    *, character_image_file_id: int, db: AsyncSession
) -> None:
    result = await db.execute(
        text("""
            SELECT cf.file_group_id
            FROM tb_common_file cf
            INNER JOIN tb_common_file_item cfi
                ON cfi.file_group_id = cf.file_group_id
               AND cfi.use_yn = 'Y'
            WHERE cf.file_group_id = :character_image_file_id
              AND cf.group_type = 'character'
              AND cf.use_yn = 'Y'
            LIMIT 1
        """),
        {"character_image_file_id": character_image_file_id},
    )
    if result.mappings().one_or_none() is None:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="유효하지 않은 캐릭터 이미지 파일입니다.",
        )


def build_public_main_character_slots_query() -> str:
    return f"""
        SELECT
            mcs.main_character_slot_id AS characterSlotId,
            mcs.product_id AS productId,
            mcs.character_scope_key AS characterScopeKey,
            mcs.character_name AS characterName,
            {get_file_path_sub_query("mcs.character_image_file_id", "characterImagePath", "character")},
            mcs.card_order AS cardOrder,
            p.title AS productTitle,
            p.author_name AS authorNickname,
            mcs.publish_start_date AS publishStartAt,
            mcs.publish_end_date AS publishEndAt,
            mcs.created_date AS createdDate,
            mcs.updated_date AS updatedDate
        FROM tb_main_character_slot mcs
        INNER JOIN tb_product p ON p.product_id = mcs.product_id
        WHERE mcs.use_yn = 'Y'
          AND mcs.deleted_yn = 'N'
          AND mcs.publish_start_date <= NOW()
          AND (mcs.publish_end_date IS NULL OR mcs.publish_end_date > NOW())
          AND p.open_yn = 'Y'
          AND COALESCE(p.blind_yn, 'N') = 'N'
          AND (:adult_yn = 'Y' OR p.ratings_code != 'adult')
          AND EXISTS (
              SELECT 1
              FROM tb_product_episode pe
              WHERE pe.product_id = p.product_id
                AND pe.use_yn = 'Y'
                AND pe.open_yn = 'Y'
          )
        ORDER BY mcs.card_order ASC, mcs.main_character_slot_id ASC
    """


async def get_public_main_character_slots(*, adult_yn: str, db: AsyncSession):
    result = await db.execute(
        text(build_public_main_character_slots_query()),
        {"adult_yn": adult_yn},
    )
    return {"data": [dict(row) for row in result.mappings().all()]}


async def get_admin_main_character_slots(
    *, page: int, count_per_page: int, db: AsyncSession
):
    count_result = await db.execute(
        text("""
            SELECT COUNT(*) AS total_count
            FROM tb_main_character_slot
            WHERE deleted_yn = 'N'
        """),
        {},
    )
    count_row = count_result.mappings().first()
    total_count = int(dict(count_row or {}).get("total_count") or 0)
    limit_clause, limit_params = get_pagination_params(page, count_per_page)
    result = await db.execute(
        text(f"""
            SELECT
                mcs.main_character_slot_id AS characterSlotId,
                mcs.product_id AS productId,
                mcs.character_scope_key AS characterScopeKey,
                mcs.character_name AS characterName,
                {get_file_path_sub_query("mcs.character_image_file_id", "characterImagePath", "character")},
                mcs.card_order AS cardOrder,
                p.title AS productTitle,
                p.author_name AS authorNickname,
                mcs.publish_start_date AS publishStartAt,
                mcs.publish_end_date AS publishEndAt,
                mcs.created_date AS createdDate,
                mcs.updated_date AS updatedDate
            FROM tb_main_character_slot mcs
            INNER JOIN tb_product p ON p.product_id = mcs.product_id
            WHERE mcs.deleted_yn = 'N'
            ORDER BY mcs.card_order ASC, mcs.main_character_slot_id ASC
            {limit_clause}
        """),
        limit_params,
    )
    return build_paginated_response(
        result.mappings().all(), total_count, page, count_per_page
    )


async def search_admin_main_character_slot_products(
    *, search_word: str | None, limit: int, db: AsyncSession
):
    normalized_search_word = (search_word or "").strip()
    result = await db.execute(
        text("""
            SELECT
                p.product_id AS productId,
                p.title,
                p.author_name AS authorNickname,
                cf.file_path AS coverImagePath,
                episode_stats.open_episode_count AS openEpisodeCount
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
                INNER JOIN tb_common_file_item cfi
                    ON cfi.file_group_id = cf.file_group_id
                   AND cfi.use_yn = 'Y'
                WHERE cf.use_yn = 'Y' AND cf.group_type = 'cover'
            ) cf ON cf.file_group_id = p.thumbnail_file_id
            WHERE p.open_yn = 'Y'
              AND COALESCE(p.blind_yn, 'N') = 'N'
              AND (:search_word = '%%' OR p.title LIKE :search_word)
            ORDER BY p.updated_date DESC, p.product_id DESC
            LIMIT :limit_count
        """),
        {
            "search_word": f"%{normalized_search_word}%",
            "limit_count": limit,
        },
    )
    return {"data": [dict(row) for row in result.mappings().all()]}


def _admin_main_character_slot_product_where_clause() -> str:
    return """
        WHERE p.open_yn = 'Y'
          AND COALESCE(p.blind_yn, 'N') = 'N'
          AND EXISTS (
              SELECT 1
              FROM tb_product_episode pe
              WHERE pe.product_id = p.product_id
                AND pe.use_yn = 'Y'
                AND pe.open_yn = 'Y'
          )
          AND (
              :search_word = '%%'
              OR p.title LIKE :search_word
              OR p.author_name LIKE :search_word
          )
          AND EXISTS (
              SELECT 1
              FROM tb_story_agent_context_summary sacs
              WHERE sacs.product_id = p.product_id
                AND sacs.summary_type = 'character_inventory_v3'
                AND sacs.is_active = 'Y'
                AND JSON_VALID(sacs.summary_text)
                AND LOWER(TRIM(JSON_UNQUOTE(
                    JSON_EXTRACT(sacs.summary_text, '$.display_safety.status')
                ))) = 'pass'
                AND JSON_TYPE(
                    JSON_EXTRACT(sacs.summary_text, '$.public_slot_eligible')
                ) = 'BOOLEAN'
                AND JSON_UNQUOTE(
                    JSON_EXTRACT(sacs.summary_text, '$.public_slot_eligible')
                ) = 'true'
                AND TRIM(JSON_UNQUOTE(
                    JSON_EXTRACT(sacs.summary_text, '$.work_role')
                )) = 'main_protagonist'
                AND TRIM(COALESCE(JSON_UNQUOTE(
                    JSON_EXTRACT(sacs.summary_text, '$.canonical_character_key')
                ), '')) != ''
                AND TRIM(COALESCE(JSON_UNQUOTE(
                    JSON_EXTRACT(sacs.summary_text, '$.display_name')
                ), '')) != ''
          )
    """


async def get_admin_main_character_slot_products(
    *,
    page: int,
    count_per_page: int,
    search_word: str | None,
    db: AsyncSession,
):
    normalized_search_word = (search_word or "").strip()
    search_params = {"search_word": f"%{normalized_search_word}%"}
    where_clause = _admin_main_character_slot_product_where_clause()

    count_result = await db.execute(
        text(f"SELECT COUNT(*) AS total_count FROM tb_product p {where_clause}"),
        search_params,
    )
    count_row = count_result.mappings().first()
    total_count = int(dict(count_row or {}).get("total_count") or 0)

    limit_clause, limit_params = get_pagination_params(page, count_per_page)
    result = await db.execute(
        text(f"""
            SELECT
                p.product_id AS productId,
                p.title,
                p.author_name AS authorNickname,
                cf.file_path AS coverImagePath,
                episode_stats.open_episode_count AS openEpisodeCount
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
                INNER JOIN tb_common_file_item cfi
                    ON cfi.file_group_id = cf.file_group_id
                   AND cfi.use_yn = 'Y'
                WHERE cf.use_yn = 'Y' AND cf.group_type = 'cover'
            ) cf ON cf.file_group_id = p.thumbnail_file_id
            {where_clause}
            ORDER BY p.updated_date DESC, p.product_id DESC
            {limit_clause}
        """),
        {**search_params, **limit_params},
    )
    return build_paginated_response(
        result.mappings().all(), total_count, page, count_per_page
    )


def _main_character_slot_params(
    req_body,
    *,
    character_name: str,
    admin_user_id: int | None,
) -> dict:
    return {
        "product_id": req_body.product_id,
        "character_scope_key": req_body.character_scope_key,
        "character_name": character_name,
        "character_image_file_id": req_body.character_image_file_id,
        "card_order": req_body.card_order,
        "publish_start_at": getattr(req_body, "publish_start_at", None),
        "publish_end_at": getattr(req_body, "publish_end_at", None),
        "created_id": admin_user_id,
        "updated_id": admin_user_id,
    }


async def _validated_character_slot_params(
    req_body,
    *,
    admin_user_id: int | None,
    db: AsyncSession,
) -> dict:
    character_name = await _ensure_character_slot_selection_eligible(
        product_id=req_body.product_id,
        character_scope_key=req_body.character_scope_key,
        db=db,
    )
    if req_body.character_image_file_id is not None:
        await _ensure_character_image_file(
            character_image_file_id=req_body.character_image_file_id,
            db=db,
        )
    return _main_character_slot_params(
        req_body,
        character_name=character_name,
        admin_user_id=admin_user_id,
    )


async def post_admin_main_character_slot(
    *,
    req_body: admin_schema.PostMainCharacterSlotReqBody,
    admin_user_id: int | None,
    db: AsyncSession,
):
    params = await _validated_character_slot_params(
        req_body, admin_user_id=admin_user_id, db=db
    )
    result = await db.execute(
        text("""
            INSERT INTO tb_main_character_slot (
                product_id,
                character_scope_key,
                character_name,
                character_image_file_id,
                card_order,
                publish_start_date,
                publish_end_date,
                use_yn,
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
                'Y',
                :created_id,
                :updated_id
            )
        """),
        params,
    )
    return {"result": {"characterSlotId": result.lastrowid}}


async def publish_admin_main_character_slot_now(
    *,
    req_body: admin_schema.PostMainCharacterSlotPublishNowReqBody,
    admin_user_id: int | None,
    db: AsyncSession,
):
    params = await _validated_character_slot_params(
        req_body, admin_user_id=admin_user_id, db=db
    )
    result = await db.execute(
        text("""
            INSERT INTO tb_main_character_slot (
                product_id,
                character_scope_key,
                character_name,
                character_image_file_id,
                card_order,
                publish_start_date,
                publish_end_date,
                use_yn,
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
                'Y',
                :created_id,
                :updated_id
            )
        """),
        params,
    )
    return {"result": {"characterSlotId": result.lastrowid}}


async def update_admin_main_character_slot(
    *,
    character_slot_id: int,
    req_body: admin_schema.PutMainCharacterSlotReqBody,
    admin_user_id: int | None,
    db: AsyncSession,
):
    params = await _validated_character_slot_params(
        req_body, admin_user_id=admin_user_id, db=db
    )
    params["character_slot_id"] = character_slot_id
    result = await db.execute(
        text("""
            UPDATE tb_main_character_slot
            SET
                product_id = :product_id,
                character_scope_key = :character_scope_key,
                character_name = :character_name,
                character_image_file_id = COALESCE(
                    :character_image_file_id,
                    character_image_file_id
                ),
                card_order = :card_order,
                publish_start_date = COALESCE(:publish_start_at, publish_start_date),
                publish_end_date = :publish_end_at,
                updated_id = :updated_id
            WHERE main_character_slot_id = :character_slot_id
              AND deleted_yn = 'N'
        """),
        params,
    )
    if result.rowcount == 0:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="존재하지 않는 메인 주인공 카드입니다.",
        )
    return {"result": {"characterSlotId": character_slot_id}}


async def delete_admin_main_character_slot(
    *, character_slot_id: int, admin_user_id: int | None, db: AsyncSession
):
    result = await db.execute(
        text("""
            UPDATE tb_main_character_slot
            SET use_yn = 'N', deleted_yn = 'Y', updated_id = :updated_id
            WHERE main_character_slot_id = :character_slot_id
              AND deleted_yn = 'N'
        """),
        {
            "character_slot_id": character_slot_id,
            "updated_id": admin_user_id,
        },
    )
    if result.rowcount == 0:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="존재하지 않는 메인 주인공 카드입니다.",
        )
    return {"result": {"characterSlotId": character_slot_id}}
