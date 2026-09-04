import hashlib
import json
import logging
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.websochat.character_chat_product_policy import (
    CHARACTER_CHAT_MINIMUM_OPEN_EPISODE_COUNT,
)


logger = logging.getLogger(__name__)

PUBLIC_CHARACTER_CATALOG_SCOPES = ("N", "Y")
PUBLIC_CHARACTER_CATALOG_SNAPSHOT_LOCK_NAME = (
    "lk_public_character_catalog_snapshot_refresh"
)


def _normalize_adult_yn(adult_yn: str | None) -> str:
    return "Y" if adult_yn == "Y" else "N"


def _decode_item_payload(raw_payload) -> dict:
    if isinstance(raw_payload, dict):
        payload = raw_payload
    elif isinstance(raw_payload, bytes):
        payload = json.loads(raw_payload.decode("utf-8"))
    else:
        payload = json.loads(str(raw_payload))
    if not isinstance(payload, dict):
        raise ValueError("character catalog snapshot payload must be an object")
    return payload


async def read_public_character_catalog_snapshot(
    *,
    adult_yn: str,
    db: AsyncSession,
    limit: int | None = None,
) -> list[dict]:
    normalized_adult_yn = _normalize_adult_yn(adult_yn)
    limit_sql = "LIMIT :limit" if limit is not None else ""
    params: dict[str, object] = {"adult_yn": normalized_adult_yn}
    if limit is not None:
        if limit < 1:
            return []
        params["limit"] = int(limit)

    result = await db.execute(
        text(f"""
            SELECT snapshot_item.payload_json AS payloadJson
            FROM tb_public_character_catalog_generation snapshot_generation
            INNER JOIN tb_public_character_catalog_snapshot snapshot_item
                ON snapshot_item.generation_id =
                    snapshot_generation.generation_id
               AND snapshot_item.adult_yn = snapshot_generation.adult_yn
            INNER JOIN tb_product product
                ON product.product_id = snapshot_item.product_id
            WHERE snapshot_generation.active_scope = :adult_yn
              AND product.open_yn = 'Y'
              AND COALESCE(product.blind_yn, 'N') = 'N'
              AND COALESCE(product.ai_content_service_enabled_yn, 'N') = 'Y'
              AND (:adult_yn = 'Y' OR product.ratings_code != 'adult')
              AND (
                    SELECT COUNT(DISTINCT public_episode.episode_id)
                    FROM tb_product_episode public_episode
                    WHERE public_episode.product_id = snapshot_item.product_id
                      AND public_episode.use_yn = 'Y'
                      AND public_episode.open_yn = 'Y'
                  ) >= {CHARACTER_CHAT_MINIMUM_OPEN_EPISODE_COUNT}
            ORDER BY snapshot_item.display_order ASC
            {limit_sql}
        """),
        params,
    )
    return [
        _decode_item_payload(row["payloadJson"])
        for row in result.mappings().all()
    ]


def _prepare_snapshot_rows(
    *,
    catalogs: dict[str, list[dict]],
    generation_id: str,
) -> tuple[list[dict], list[dict]]:
    generation_rows: list[dict] = []
    item_rows: list[dict] = []

    for adult_yn in PUBLIC_CHARACTER_CATALOG_SCOPES:
        catalog = jsonable_encoder(list(catalogs.get(adult_yn) or []))
        if not catalog:
            raise ValueError(
                f"refusing to publish empty character catalog scope={adult_yn}"
            )

        normalized_items: list[dict] = []
        for display_order, raw_item in enumerate(catalog, start=1):
            if not isinstance(raw_item, dict):
                raise ValueError("character catalog item must be an object")
            item = dict(raw_item)
            item["cardOrder"] = display_order
            if item.get("lastViewedEpisodeNo") is not None or item.get(
                "lastViewedAt"
            ) is not None:
                raise ValueError(
                    "user progress must not be stored in character catalog snapshot"
                )
            product_id = int(item.get("productId") or 0)
            character_slot_id = int(item.get("characterSlotId") or 0)
            character_scope_key = str(item.get("characterScopeKey") or "").strip()
            if product_id < 1 or character_slot_id < 1 or not character_scope_key:
                raise ValueError("character catalog item identity is incomplete")
            normalized_items.append(item)
            item_rows.append(
                {
                    "generation_id": generation_id,
                    "adult_yn": adult_yn,
                    "display_order": display_order,
                    "product_id": product_id,
                    "character_slot_id": character_slot_id,
                    "character_scope_key": character_scope_key,
                    "payload_json": json.dumps(item, ensure_ascii=False),
                }
            )

        canonical_payload = json.dumps(
            normalized_items,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        generation_rows.append(
            {
                "generation_id": generation_id,
                "adult_yn": adult_yn,
                "item_count": len(normalized_items),
                "content_sha256": hashlib.sha256(canonical_payload).hexdigest(),
            }
        )

    return generation_rows, item_rows


async def publish_public_character_catalog_snapshot(
    *,
    catalogs: dict[str, list[dict]],
    db: AsyncSession,
    generation_id: str | None = None,
) -> dict[str, object]:
    published_generation_id = generation_id or str(uuid4())
    generation_rows, item_rows = _prepare_snapshot_rows(
        catalogs=catalogs,
        generation_id=published_generation_id,
    )

    try:
        await db.execute(
            text("""
                INSERT INTO tb_public_character_catalog_generation (
                    generation_id,
                    adult_yn,
                    active_scope,
                    item_count,
                    content_sha256,
                    created_date,
                    published_date
                ) VALUES (
                    :generation_id,
                    :adult_yn,
                    NULL,
                    :item_count,
                    :content_sha256,
                    NOW(6),
                    NULL
                )
            """),
            generation_rows,
        )
        await db.execute(
            text("""
                INSERT INTO tb_public_character_catalog_snapshot (
                    generation_id,
                    adult_yn,
                    display_order,
                    product_id,
                    character_slot_id,
                    character_scope_key,
                    payload_json,
                    created_date
                ) VALUES (
                    :generation_id,
                    :adult_yn,
                    :display_order,
                    :product_id,
                    :character_slot_id,
                    :character_scope_key,
                    :payload_json,
                    NOW(6)
                )
            """),
            item_rows,
        )
        await db.execute(
            text("""
                UPDATE tb_public_character_catalog_generation
                SET active_scope = NULL
                WHERE active_scope IN ('N', 'Y')
            """)
        )
        activation_result = await db.execute(
            text("""
                UPDATE tb_public_character_catalog_generation
                SET active_scope = adult_yn,
                    published_date = NOW(6)
                WHERE generation_id = :generation_id
                  AND adult_yn IN ('N', 'Y')
            """),
            {"generation_id": published_generation_id},
        )
        if activation_result.rowcount != len(PUBLIC_CHARACTER_CATALOG_SCOPES):
            raise RuntimeError("both adult scopes must activate together")
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {
        "generationId": published_generation_id,
        "itemCounts": {
            row["adult_yn"]: row["item_count"] for row in generation_rows
        },
        "contentHashes": {
            row["adult_yn"]: row["content_sha256"] for row in generation_rows
        },
    }


async def cleanup_old_public_character_catalog_snapshots(
    *,
    db: AsyncSession,
) -> None:
    try:
        await db.execute(
            text("""
                DELETE FROM tb_public_character_catalog_generation
                WHERE active_scope IS NULL
                  AND created_date < DATE_SUB(NOW(), INTERVAL 7 DAY)
            """)
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception("public character catalog snapshot cleanup failed")
