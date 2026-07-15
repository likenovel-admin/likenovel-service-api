import json
from collections import defaultdict

from fastapi import status
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

import app.schemas.admin as admin_schema
from app.exceptions import CustomResponseException
from app.services.websochat.websochat_utils import _extract_websochat_json_object
from app.utils.query import get_file_path_sub_query, get_pagination_params
from app.utils.response import build_paginated_response


MAIN_CHARACTER_SLOT_MINIMUM_OPEN_EPISODE_COUNT = 15
MAIN_CHARACTER_SLOT_MAX_CHARACTERS_PER_PRODUCT = 2
MAIN_CHARACTER_CHAT_GOOD_MIN_DISTINCT_EPISODES = 10
MAIN_CHARACTER_CHAT_GOOD_MIN_EXAMPLES = 4
MAIN_CHARACTER_CHAT_GOOD_MIN_SCENES = 5


def _normalize_aliases(raw_aliases) -> list[str]:
    aliases: list[str] = []
    if not isinstance(raw_aliases, list):
        return aliases
    for raw_alias in raw_aliases:
        alias = str(raw_alias or "").strip()
        if alias and alias not in aliases:
            aliases.append(alias)
    return aliases


def _chat_ready_rp_assets_predicate(inventory_alias: str) -> str:
    canonical_scope_key = f"""COALESCE(
        NULLIF(TRIM(JSON_UNQUOTE(JSON_EXTRACT(
            {inventory_alias}.summary_text, '$.canonical_character_key'
        ))), ''),
        {inventory_alias}.scope_key
    )"""
    return f"""
        AND EXISTS (
            SELECT 1
            FROM tb_story_agent_context_summary profile
            WHERE profile.product_id = {inventory_alias}.product_id
              AND profile.scope_key = {canonical_scope_key}
              AND profile.summary_type = 'character_rp_profile'
              AND profile.is_active = 'Y'
              AND JSON_VALID(profile.summary_text)
        )
        AND EXISTS (
            SELECT 1
            FROM tb_story_agent_context_summary examples
            WHERE examples.product_id = {inventory_alias}.product_id
              AND examples.scope_key = {canonical_scope_key}
              AND examples.summary_type = 'character_rp_examples'
              AND examples.is_active = 'Y'
              AND JSON_VALID(examples.summary_text)
              AND JSON_TYPE(JSON_EXTRACT(
                  examples.summary_text, '$.examples'
              )) = 'ARRAY'
              AND JSON_LENGTH(JSON_EXTRACT(
                  examples.summary_text, '$.examples'
              )) > 0
        )
    """


def _extract_eligible_character_payload(row) -> dict | None:
    row_data = dict(row)
    payload = _extract_websochat_json_object(
        str(row_data.get("summaryText") or row_data.get("summary_text") or "")
    )
    if not payload:
        return None
    display_safety = payload.get("display_safety")
    if not isinstance(display_safety, dict):
        return None
    if str(display_safety.get("status") or "").strip().lower() != "pass":
        return None
    if payload.get("public_chat_eligible") is not True:
        return None
    return payload


def _character_priority(payload: dict) -> tuple[object, ...]:
    return (
        0
        if str(payload.get("work_role") or "").strip().lower()
        == "main_protagonist"
        or payload.get("is_protagonist") is True
        else 1,
        -int(payload.get("distinct_episode_count") or 0),
        -int(payload.get("voice_evidence_count") or 0),
        str(payload.get("display_name") or "").strip(),
    )


def extract_eligible_main_character_roster(rows) -> list[dict]:
    roster: list[tuple[tuple[object, ...], dict]] = []
    seen_scope_keys: set[str] = set()
    for row in rows:
        payload = _extract_eligible_character_payload(row)
        if not payload:
            continue

        scope_key = str(payload.get("canonical_character_key") or "").strip()
        display_name = str(payload.get("display_name") or "").strip()
        if not scope_key or not display_name or scope_key in seen_scope_keys:
            continue
        seen_scope_keys.add(scope_key)
        roster.append(
            (
                _character_priority(payload),
                {
                    "scopeKey": scope_key,
                    "displayName": display_name,
                    "aliases": _normalize_aliases(payload.get("aliases")),
                },
            )
        )
    return [
        item
        for _, item in sorted(roster, key=lambda candidate: candidate[0])[
            :MAIN_CHARACTER_SLOT_MAX_CHARACTERS_PER_PRODUCT
        ]
    ]


def build_main_character_chat_quality_by_product(candidate_rows) -> dict[int, str]:
    candidates_by_product: dict[
        int, list[tuple[tuple[object, ...], dict[str, object]]]
    ] = defaultdict(list)
    seen_scope_keys: set[tuple[int, str]] = set()
    for row in candidate_rows:
        row_data = dict(row)
        product_id = int(row_data.get("productId") or 0)
        payload = _extract_eligible_character_payload(row_data)
        if not product_id or not payload:
            continue
        scope_key = str(payload.get("canonical_character_key") or "").strip()
        display_name = str(payload.get("display_name") or "").strip()
        if (
            not scope_key
            or not display_name
            or (product_id, scope_key) in seen_scope_keys
        ):
            continue
        seen_scope_keys.add((product_id, scope_key))
        candidates_by_product[product_id].append(
            (
                _character_priority(payload),
                {
                    "scopeKey": scope_key,
                    "distinctEpisodeCount": int(
                        payload.get("distinct_episode_count") or 0
                    ),
                    "exampleCount": int(row_data.get("exampleCount") or 0),
                    "sceneCount": int(row_data.get("sceneCount") or 0),
                },
            )
        )

    quality_by_product: dict[int, str] = {}
    severity = {"good": 0, "normal": 1, "insufficient": 2}
    for product_id, candidates in candidates_by_product.items():
        candidate_qualities: list[str] = []
        for _, candidate in sorted(candidates, key=lambda item: item[0])[
            :MAIN_CHARACTER_SLOT_MAX_CHARACTERS_PER_PRODUCT
        ]:
            scene_count = candidate["sceneCount"]
            if scene_count == 0:
                candidate_qualities.append("insufficient")
            elif (
                candidate["distinctEpisodeCount"]
                >= MAIN_CHARACTER_CHAT_GOOD_MIN_DISTINCT_EPISODES
                and candidate["exampleCount"] >= MAIN_CHARACTER_CHAT_GOOD_MIN_EXAMPLES
                and scene_count >= MAIN_CHARACTER_CHAT_GOOD_MIN_SCENES
            ):
                candidate_qualities.append("good")
            else:
                candidate_qualities.append("normal")

        if candidate_qualities:
            quality_by_product[product_id] = max(
                candidate_qualities, key=severity.__getitem__
            )
    return quality_by_product


async def _load_eligible_main_character_roster(
    product_id: int, db: AsyncSession
) -> list[dict]:
    result = await db.execute(
        text(f"""
            SELECT sacs.scope_key AS scopeKey, sacs.summary_text AS summaryText
            FROM tb_story_agent_context_summary sacs
            INNER JOIN tb_product p ON p.product_id = sacs.product_id
            WHERE sacs.product_id = :product_id
              AND sacs.summary_type = 'character_inventory_v3'
              AND sacs.is_active = 'Y'
              AND JSON_VALID(sacs.summary_text)
              AND p.open_yn = 'Y'
              AND COALESCE(p.blind_yn, 'N') = 'N'
              AND COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'
              AND (
                  SELECT COUNT(*)
                  FROM tb_product_episode pe
                  WHERE pe.product_id = p.product_id
                    AND pe.use_yn = 'Y'
                    AND pe.open_yn = 'Y'
              ) >= {MAIN_CHARACTER_SLOT_MINIMUM_OPEN_EPISODE_COUNT}
              {_chat_ready_rp_assets_predicate("sacs")}
            ORDER BY sacs.summary_id DESC
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
            message="메인 캐릭터 카드에 사용할 수 없는 인물입니다.",
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
          AND COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'
          AND (:adult_yn = 'Y' OR p.ratings_code != 'adult')
          AND (
              SELECT COUNT(*)
              FROM tb_product_episode pe
              WHERE pe.product_id = p.product_id
                AND pe.use_yn = 'Y'
                AND pe.open_yn = 'Y'
          ) >= {MAIN_CHARACTER_SLOT_MINIMUM_OPEN_EPISODE_COUNT}
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
              AND COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'
              AND episode_stats.open_episode_count >= :minimum_open_episode_count
              AND EXISTS (
                  SELECT 1
                  FROM tb_story_agent_context_summary sacs
                  WHERE sacs.product_id = p.product_id
                    AND sacs.summary_type = 'character_inventory_v3'
                    AND sacs.is_active = 'Y'
                    AND JSON_UNQUOTE(
                        JSON_EXTRACT(sacs.summary_text, '$.public_chat_eligible')
                    ) = 'true'
                    AND JSON_UNQUOTE(
                        JSON_EXTRACT(sacs.summary_text, '$.display_safety.status')
                    ) = 'pass'
              )
              AND (:search_word = '%%' OR p.title LIKE :search_word)
            ORDER BY p.updated_date DESC, p.product_id DESC
            LIMIT :limit_count
        """),
        {
            "search_word": f"%{normalized_search_word}%",
            "limit_count": limit,
            "minimum_open_episode_count": MAIN_CHARACTER_SLOT_MINIMUM_OPEN_EPISODE_COUNT,
        },
    )
    return {"data": [dict(row) for row in result.mappings().all()]}


def _admin_chat_ready_product_where_clause() -> str:
    return f"""
        WHERE p.open_yn = 'Y'
          AND COALESCE(p.blind_yn, 'N') = 'N'
          AND COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'
          AND (
              SELECT COUNT(*)
              FROM tb_product_episode pe
              WHERE pe.product_id = p.product_id
                AND pe.use_yn = 'Y'
                AND pe.open_yn = 'Y'
          ) >= :minimum_open_episode_count
          AND (
              :search_word = '%%'
              OR p.title LIKE :search_word
              OR p.author_name LIKE :search_word
          )
          AND EXISTS (
              SELECT 1
              FROM tb_story_agent_context_summary inventory
              WHERE inventory.product_id = p.product_id
                AND inventory.summary_type = 'character_inventory_v3'
                AND inventory.is_active = 'Y'
                AND JSON_VALID(inventory.summary_text)
                AND JSON_UNQUOTE(JSON_EXTRACT(
                    inventory.summary_text, '$.public_chat_eligible'
                )) = 'true'
                AND LOWER(TRIM(JSON_UNQUOTE(JSON_EXTRACT(
                    inventory.summary_text, '$.display_safety.status'
                )))) = 'pass'
                AND TRIM(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
                    inventory.summary_text, '$.canonical_character_key'
                )), '')) != ''
                AND TRIM(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
                    inventory.summary_text, '$.display_name'
                )), '')) != ''
                {_chat_ready_rp_assets_predicate("inventory")}
          )
    """


async def _load_main_character_chat_quality(
    product_ids: list[int], db: AsyncSession
) -> dict[int, str]:
    if not product_ids:
        return {}

    candidate_query = text("""
        SELECT
            inventory.product_id AS productId,
            inventory.summary_text AS summaryText
        FROM tb_story_agent_context_summary inventory
        WHERE inventory.product_id IN :product_ids
          AND inventory.summary_type = 'character_inventory_v3'
          AND inventory.is_active = 'Y'
          AND JSON_VALID(inventory.summary_text)
          AND JSON_UNQUOTE(JSON_EXTRACT(
              inventory.summary_text, '$.public_chat_eligible'
          )) = 'true'
          AND LOWER(TRIM(JSON_UNQUOTE(JSON_EXTRACT(
              inventory.summary_text, '$.display_safety.status'
          )))) = 'pass'
        ORDER BY inventory.product_id ASC, inventory.summary_id DESC
    """).bindparams(bindparam("product_ids", expanding=True))
    candidate_result = await db.execute(
        candidate_query,
        {"product_ids": product_ids},
    )

    asset_query = text("""
        SELECT
            product_id AS productId,
            scope_key AS scopeKey,
            summary_type AS summaryType,
            CASE
                WHEN summary_type = 'character_rp_examples'
                 AND JSON_TYPE(JSON_EXTRACT(summary_text, '$.examples')) = 'ARRAY'
                THEN JSON_LENGTH(JSON_EXTRACT(summary_text, '$.examples'))
                ELSE 0
            END AS exampleCount
        FROM tb_story_agent_context_summary
        WHERE product_id IN :product_ids
          AND summary_type IN ('character_rp_profile', 'character_rp_examples')
          AND is_active = 'Y'
          AND JSON_VALID(summary_text)
    """).bindparams(bindparam("product_ids", expanding=True))
    asset_result = await db.execute(asset_query, {"product_ids": product_ids})

    scene_query = text("""
        SELECT product_id AS productId, summary_text AS summaryText
        FROM tb_story_agent_context_summary
        WHERE product_id IN :product_ids
          AND summary_type = 'episode_scene_extraction'
          AND is_active = 'Y'
    """).bindparams(bindparam("product_ids", expanding=True))
    scene_result = await db.execute(scene_query, {"product_ids": product_ids})

    profile_keys: set[tuple[int, str]] = set()
    example_counts: dict[tuple[int, str], int] = defaultdict(int)
    for row in asset_result.mappings().all():
        row_data = dict(row)
        key = (
            int(row_data.get("productId") or 0),
            str(row_data.get("scopeKey") or "").strip(),
        )
        if not key[0] or not key[1]:
            continue
        if row_data.get("summaryType") == "character_rp_profile":
            profile_keys.add(key)
        elif row_data.get("summaryType") == "character_rp_examples":
            example_counts[key] = max(
                example_counts[key], int(row_data.get("exampleCount") or 0)
            )

    scene_texts: dict[int, list[str]] = defaultdict(list)
    for row in scene_result.mappings().all():
        row_data = dict(row)
        scene_texts[int(row_data.get("productId") or 0)].append(
            str(row_data.get("summaryText") or "")
        )

    enriched_candidates: list[dict] = []
    for row in candidate_result.mappings().all():
        row_data = dict(row)
        payload = _extract_eligible_character_payload(row_data)
        if not payload:
            continue
        product_id = int(row_data.get("productId") or 0)
        scope_key = str(payload.get("canonical_character_key") or "").strip()
        key = (product_id, scope_key)
        example_count = example_counts.get(key, 0)
        if key not in profile_keys or example_count <= 0:
            continue
        scope_token = json.dumps(scope_key, ensure_ascii=False)
        enriched_candidates.append(
            {
                **row_data,
                "exampleCount": example_count,
                "sceneCount": sum(
                    scope_token in scene_text
                    for scene_text in scene_texts.get(product_id, [])
                ),
            }
        )

    return build_main_character_chat_quality_by_product(
        enriched_candidates
    )


async def get_admin_main_character_slot_products(
    *,
    page: int,
    count_per_page: int,
    search_word: str | None,
    db: AsyncSession,
):
    normalized_search_word = (search_word or "").strip()
    params = {
        "search_word": f"%{normalized_search_word}%",
        "minimum_open_episode_count": MAIN_CHARACTER_SLOT_MINIMUM_OPEN_EPISODE_COUNT,
    }
    where_clause = _admin_chat_ready_product_where_clause()

    count_result = await db.execute(
        text(f"SELECT COUNT(*) AS total_count FROM tb_product p {where_clause}"),
        params,
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
                (
                    SELECT COUNT(*)
                    FROM tb_product_episode pe
                    WHERE pe.product_id = p.product_id
                      AND pe.use_yn = 'Y'
                      AND pe.open_yn = 'Y'
                ) AS openEpisodeCount
            FROM tb_product p
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
        {**params, **limit_params},
    )
    products = [dict(row) for row in result.mappings().all()]
    quality_by_product = await _load_main_character_chat_quality(
        [int(product["productId"]) for product in products],
        db,
    )
    for product in products:
        product["chatQuality"] = quality_by_product.get(
            int(product["productId"]), "insufficient"
        )
    return build_paginated_response(products, total_count, page, count_per_page)


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
