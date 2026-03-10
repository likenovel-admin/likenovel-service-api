import logging
from typing import Any

from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import settings
from app.exceptions import CustomResponseException
from app.services.ai import recommendation_service

logger = logging.getLogger("admin_app")

MIN_ONBOARDING_PRODUCT_COUNT = 3
MAX_ONBOARDING_PRODUCT_COUNT = 15
ONBOARDING_SETTINGS_LOCK_NAME = "ai_onboarding_settings_lock"


def _dedupe_product_ids(product_ids: list[int]) -> list[int]:
    deduped: list[int] = []
    seen: set[int] = set()
    for product_id in product_ids:
        if product_id in seen:
            continue
        deduped.append(product_id)
        seen.add(product_id)
    return deduped


def _sanitize_selected_tags(values: list[str] | None) -> list[str]:
    sanitized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        tag = str(value or "").strip()
        if not tag or tag in seen:
            continue
        if len(tag) > 100:
            tag = tag[:100]
        seen.add(tag)
        sanitized.append(tag)
    return sanitized


async def ai_onboarding_product_list(db: AsyncSession) -> dict[str, Any]:
    query = text(
        """
        SELECT
            o.id,
            o.product_id,
            o.sort_order,
            o.use_yn,
            p.title,
            IF(p.thumbnail_file_id IS NULL, NULL,
               (SELECT CONCAT(:cdn, '/', w.file_path)
                FROM tb_common_file q, tb_common_file_item w
                WHERE q.file_group_id = w.file_group_id
                  AND q.use_yn = 'Y' AND w.use_yn = 'Y'
                  AND q.group_type = 'cover'
                  AND q.file_group_id = p.thumbnail_file_id)) AS cover_url,
            p.author_name,
            p.price_type,
            p.status_code,
            'Y' AS product_use_yn,
            p.open_yn AS product_open_yn,
            COALESCE(m.analysis_status, 'missing') AS analysis_status,
            COALESCE(m.exclude_from_recommend_yn, 'N') AS exclude_from_recommend_yn,
            o.created_date,
            o.updated_date
        FROM tb_ai_onboarding_product o
        INNER JOIN tb_product p ON p.product_id = o.product_id
        LEFT JOIN tb_product_ai_metadata m ON m.product_id = o.product_id
        WHERE o.use_yn = 'Y'
        ORDER BY o.sort_order ASC, o.id ASC
        """
    )
    result = await db.execute(query, {"cdn": settings.R2_SC_CDN_URL})
    rows = [dict(row) for row in result.mappings().all()]
    tag_tabs = await recommendation_service.get_onboarding_tag_tabs(
        db,
        adult_yn=None,
        onboarding_only=False,
    )
    selected_tag_tabs = await recommendation_service.get_curated_onboarding_tag_tabs(
        db,
        adult_yn=None,
        default_top_n=10,
    )
    return {"data": rows, "tag_tabs": tag_tabs, "selected_tag_tabs": selected_tag_tabs}


async def put_ai_onboarding_products(
    product_ids: list[int],
    db: AsyncSession,
    hero_tags: list[str] | None = None,
    world_tone_tags: list[str] | None = None,
    relation_tags: list[str] | None = None,
) -> dict[str, Any]:
    deduped_ids = _dedupe_product_ids(product_ids)
    sanitized_hero_tags = _sanitize_selected_tags(hero_tags)
    sanitized_world_tone_tags = _sanitize_selected_tags(world_tone_tags)
    sanitized_relation_tags = _sanitize_selected_tags(relation_tags)
    has_tag_payload = (
        hero_tags is not None
        or world_tone_tags is not None
        or relation_tags is not None
    )
    if has_tag_payload and not (
        hero_tags is not None
        and world_tone_tags is not None
        and relation_tags is not None
    ):
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="hero_tags, world_tone_tags, relation_tags는 함께 전달해야 합니다.",
        )
    should_update_tags = has_tag_payload

    if len(deduped_ids) < MIN_ONBOARDING_PRODUCT_COUNT:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="온보딩 작품은 최소 3개 이상 설정해야 합니다.",
        )
    if len(deduped_ids) > MAX_ONBOARDING_PRODUCT_COUNT:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="온보딩 작품은 최대 15개까지 설정할 수 있습니다.",
        )

    placeholders = ", ".join(f":pid_{idx}" for idx in range(len(deduped_ids)))
    params = {f"pid_{idx}": pid for idx, pid in enumerate(deduped_ids)}

    validate_query = text(
        f"""
        SELECT
            p.product_id,
            p.open_yn,
            COALESCE(m.analysis_status, 'missing') AS analysis_status,
            COALESCE(m.exclude_from_recommend_yn, 'N') AS exclude_from_recommend_yn
        FROM tb_product p
        LEFT JOIN tb_product_ai_metadata m ON m.product_id = p.product_id
        WHERE p.product_id IN ({placeholders})
        """
    )
    result = await db.execute(validate_query, params)
    rows = [dict(row) for row in result.mappings().all()]
    row_map = {row["product_id"]: row for row in rows}

    missing_ids = [pid for pid in deduped_ids if pid not in row_map]
    if missing_ids:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=f"존재하지 않는 작품이 포함되어 있습니다: {missing_ids[:10]}",
        )

    invalid_ids: list[int] = []
    for pid in deduped_ids:
        row = row_map[pid]
        if row.get("open_yn") != "Y":
            invalid_ids.append(pid)
            continue
        if row.get("analysis_status") != "success":
            invalid_ids.append(pid)
            continue
        if row.get("exclude_from_recommend_yn") == "Y":
            invalid_ids.append(pid)

    if invalid_ids:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=(
                "온보딩 노출 조건(open_yn=Y, analysis_status=success, "
                f"exclude_from_recommend_yn=N)을 만족하지 않는 작품이 있습니다: {invalid_ids[:10]}"
            ),
        )

    lock_acquired = False
    try:
        lock_result = await db.execute(
            text("SELECT GET_LOCK(:lock_name, 10)"),
            {"lock_name": ONBOARDING_SETTINGS_LOCK_NAME},
        )
        lock_acquired = int(lock_result.scalar() or 0) == 1
        if not lock_acquired:
            raise CustomResponseException(
                status_code=status.HTTP_409_CONFLICT,
                message="온보딩 설정이 동시에 수정 중입니다. 잠시 후 다시 시도해주세요.",
            )

        await db.execute(
            text(
                """
                UPDATE tb_ai_onboarding_product
                SET use_yn = 'N', updated_date = NOW()
                WHERE use_yn = 'Y'
                """
            )
        )

        upsert_query = text(
            """
            INSERT INTO tb_ai_onboarding_product (product_id, sort_order, use_yn)
            VALUES (:product_id, :sort_order, 'Y')
            ON DUPLICATE KEY UPDATE
                sort_order = VALUES(sort_order),
                use_yn = 'Y',
                updated_date = NOW()
            """
        )
        for sort_order, product_id in enumerate(deduped_ids, start=1):
            await db.execute(
                upsert_query,
                {"product_id": product_id, "sort_order": sort_order},
            )

        if should_update_tags:
            await db.execute(
                text(
                    """
                    UPDATE tb_ai_onboarding_tag
                    SET use_yn = 'N', updated_date = NOW()
                    WHERE use_yn = 'Y'
                    """
                )
            )

            upsert_tag_query = text(
                """
                INSERT INTO tb_ai_onboarding_tag (tab_key, tag_name, sort_order, use_yn)
                VALUES (:tab_key, :tag_name, :sort_order, 'Y')
                ON DUPLICATE KEY UPDATE
                    sort_order = VALUES(sort_order),
                    use_yn = 'Y',
                    updated_date = NOW()
                """
            )
            selected_by_tab = {
                "hero": sanitized_hero_tags,
                "worldTone": sanitized_world_tone_tags,
                "relation": sanitized_relation_tags,
            }
            for tab_key, tags in selected_by_tab.items():
                for sort_order, tag_name in enumerate(tags, start=1):
                    await db.execute(
                        upsert_tag_query,
                        {
                            "tab_key": tab_key,
                            "tag_name": tag_name,
                            "sort_order": sort_order,
                        },
                    )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        if lock_acquired:
            try:
                await db.execute(
                    text("SELECT RELEASE_LOCK(:lock_name)"),
                    {"lock_name": ONBOARDING_SETTINGS_LOCK_NAME},
                )
            except Exception:
                logger.warning("failed to release onboarding settings lock")

    return {
        "data": {
            "message": "온보딩 작품 노출 목록이 저장되었습니다.",
            "count": len(deduped_ids),
        }
    }
