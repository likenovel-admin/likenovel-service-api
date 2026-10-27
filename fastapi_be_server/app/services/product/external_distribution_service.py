"""외부 유통(카카오페이지/리디) 연재본 매핑.

수집기는 외부 플랫폼에서 관측한 연재본(외부 ID, 제목, 작가명)만 보낸다.
라이크노벨 유료연재 작품과의 매칭, 저장, 노출 조건은 이 모듈이 소유한다.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any, Iterable

from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import ErrorMessages
from app.exceptions import CustomResponseException
import app.services.product.product_service as product_service
from app.utils.query import get_pagination_params
from app.utils.response import build_paginated_response

PLATFORM_KAKAOPAGE = "kakaopage"
PLATFORM_RIDI = "ridi"

PLATFORMS: dict[str, dict[str, Any]] = {
    PLATFORM_KAKAOPAGE: {"label": "카카오페이지", "min_open_episodes": 50},
    PLATFORM_RIDI: {"label": "리디", "min_open_episodes": 100},
}

EDITION_SERIAL = "serial"
STATUS_ACTIVE = "active"
STATUS_HIDDEN = "hidden"
MATCH_EXACT = "exact"
MATCH_AUTHOR_SIMILAR = "author_similar"
MATCH_MANUAL = "manual"

# 연속으로 이 횟수만큼 관측되지 않은 자동 매칭은 공개 노출에서 제외한다.
MISS_LIMIT = 3
# 같은 작가 작품 중 제목 유사도 1위가 이 값 이상이고 2위와 MARGIN 이상 차이 날 때만 자동 매칭한다.
TITLE_SIMILARITY_MIN = 0.6
TITLE_SIMILARITY_MARGIN = 0.3
HOME_SLOT_PRODUCT_LIMIT = 20
PUBLIC_PAGE_LIMIT_MAX = 60

_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def require_platform(platform: str | None) -> str:
    if platform not in PLATFORMS:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_REQUEST_DATA,
        )
    return platform


def normalize_text(value: str | None) -> str:
    """띄어쓰기·문장부호·기호 차이를 지운 비교용 문자열."""
    return _NON_WORD.sub("", unicodedata.normalize("NFKC", value or "")).lower()


def title_similarity(left: str | None, right: str | None) -> float:
    a, b = normalize_text(left), normalize_text(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _preferred_candidate(candidates: list[dict]) -> dict:
    # 같은 작품이 중복 공개된 경우: 공개 회차가 많은 쪽, 같으면 먼저 등록된 쪽
    return sorted(
        candidates,
        key=lambda c: (-int(c.get("open_episode_count") or 0), int(c["product_id"])),
    )[0]


def match_observations(
    observations: Iterable[dict], candidates: Iterable[dict]
) -> dict[str, list[dict]]:
    """외부 연재본 관측값을 유료연재 후보 작품에 매칭한다.

    observations: {external_id, title, author, edition}
    candidates: {product_id, title, author_name, open_episode_count}
    """
    by_author: dict[str, list[dict]] = {}
    for candidate in candidates:
        key = normalize_text(candidate.get("author_name"))
        if key:
            by_author.setdefault(key, []).append(candidate)

    best_by_product: dict[int, dict] = {}
    unmatched: list[dict] = []
    for observation in observations:
        external_id = str(observation.get("external_id") or "").strip()
        if not external_id or (observation.get("edition") or EDITION_SERIAL) != EDITION_SERIAL:
            continue
        author_candidates = by_author.get(normalize_text(observation.get("author")), [])
        if not author_candidates:
            unmatched.append({**observation, "reason": "author_not_found"})
            continue

        observed_title = normalize_text(observation.get("title"))
        exact = [
            c for c in author_candidates if normalize_text(c.get("title")) == observed_title
        ]
        if exact:
            picked, method, score = _preferred_candidate(exact), MATCH_EXACT, 1.0
        else:
            scored = sorted(
                (
                    (title_similarity(observation.get("title"), c.get("title")), c)
                    for c in author_candidates
                ),
                key=lambda item: (-item[0], int(item[1]["product_id"])),
            )
            score, picked = scored[0]
            runner_up = scored[1][0] if len(scored) > 1 else 0.0
            if score < TITLE_SIMILARITY_MIN or score - runner_up < TITLE_SIMILARITY_MARGIN:
                unmatched.append({**observation, "reason": "title_ambiguous"})
                continue
            method = MATCH_AUTHOR_SIMILAR

        product_id = int(picked["product_id"])
        match = {
            "product_id": product_id,
            "external_id": external_id,
            "external_title": observation.get("title"),
            "external_author": observation.get("author"),
            "match_method": method,
            "score": score,
        }
        previous = best_by_product.get(product_id)
        if previous is None or score > previous["score"]:
            best_by_product[product_id] = match

    return {"matched": list(best_by_product.values()), "unmatched": unmatched}


SYNC_CANDIDATES_QUERY = """
    SELECT
        p.product_id,
        p.title,
        p.author_name,
        COALESCE(episode_stats.open_episode_count, 0) AS open_episode_count
    FROM tb_product p
    LEFT JOIN (
        SELECT product_id, COUNT(*) AS open_episode_count
        FROM tb_product_episode
        WHERE use_yn = 'Y' AND open_yn = 'Y'
        GROUP BY product_id
    ) episode_stats ON episode_stats.product_id = p.product_id
    WHERE p.price_type = 'paid'
      AND p.open_yn = 'Y'
      AND COALESCE(p.blind_yn, 'N') = 'N'
    ORDER BY p.product_id ASC
"""


async def get_sync_candidates(db: AsyncSession) -> list[dict]:
    result = await db.execute(text(SYNC_CANDIDATES_QUERY))
    return [dict(row) for row in result.mappings().all()]


async def get_admin_sync_candidates(db: AsyncSession) -> dict:
    rows = await get_sync_candidates(db)
    return {
        "data": [
            {
                "productId": row["product_id"],
                "title": row["title"],
                "authorName": row["author_name"],
                "openEpisodeCount": int(row["open_episode_count"] or 0),
            }
            for row in rows
        ],
        "platforms": PLATFORMS,
    }


async def apply_sync(
    platform: str,
    observations: list[dict],
    complete: bool,
    admin_user_id: int | None,
    db: AsyncSession,
) -> dict:
    """관측값을 매칭해 매핑을 갱신한다.

    - 매칭된 작품: 신규 저장 또는 외부 정보 갱신, miss_count 초기화
    - 관리자가 수동 등록한 매핑과 같은 외부 ID는 자동 매칭이 덮어쓰지 않는다.
    - complete=True(수집 완료)일 때만 이번에 관측되지 않은 자동 매핑의 miss_count를 올린다.
    - status(active/hidden)는 관리자 결정이므로 sync가 바꾸지 않는다.
    """
    require_platform(platform)
    candidates = await get_sync_candidates(db)
    result = match_observations(observations, candidates)

    existing_rows = (
        await db.execute(
            text("""
                SELECT id, product_id, external_id, match_method
                FROM tb_product_external_distribution
                WHERE platform = :platform
            """),
            {"platform": platform},
        )
    ).mappings().all()
    existing_by_product = {int(row["product_id"]): dict(row) for row in existing_rows}
    manual_external_owner = {
        str(row["external_id"]): int(row["product_id"])
        for row in existing_rows
        if row["match_method"] == MATCH_MANUAL
    }

    inserted = updated = skipped_manual = 0
    seen_product_ids: set[int] = set()
    for match in result["matched"]:
        product_id = match["product_id"]
        owner = manual_external_owner.get(match["external_id"])
        if owner is not None and owner != product_id:
            skipped_manual += 1
            continue
        params = {
            "product_id": product_id,
            "platform": platform,
            "external_id": match["external_id"],
            "external_title": (match["external_title"] or "")[:500],
            "external_author": (match["external_author"] or "")[:200],
            "match_method": match["match_method"],
            "user_id": admin_user_id,
        }
        existing = existing_by_product.get(product_id)
        if existing is None:
            await db.execute(
                text("""
                    INSERT INTO tb_product_external_distribution (
                        product_id, platform, external_id, external_title, external_author,
                        match_method, status, miss_count, first_seen_at, last_seen_at,
                        created_id, updated_id
                    ) VALUES (
                        :product_id, :platform, :external_id, :external_title, :external_author,
                        :match_method, 'active', 0, NOW(), NOW(), :user_id, :user_id
                    )
                """),
                params,
            )
            inserted += 1
        elif existing["match_method"] == MATCH_MANUAL:
            await db.execute(
                text("""
                    UPDATE tb_product_external_distribution
                    SET miss_count = 0, last_seen_at = NOW(), updated_id = :user_id
                    WHERE product_id = :product_id AND platform = :platform
                """),
                params,
            )
            updated += 1
        else:
            await db.execute(
                text("""
                    UPDATE tb_product_external_distribution
                    SET external_id = :external_id,
                        external_title = :external_title,
                        external_author = :external_author,
                        match_method = :match_method,
                        miss_count = 0,
                        last_seen_at = NOW(),
                        updated_id = :user_id
                    WHERE product_id = :product_id AND platform = :platform
                """),
                params,
            )
            updated += 1
        seen_product_ids.add(product_id)

    missed = 0
    if complete:
        missed_ids = [
            product_id
            for product_id, row in existing_by_product.items()
            if product_id not in seen_product_ids and row["match_method"] != MATCH_MANUAL
        ]
        for product_id in missed_ids:
            await db.execute(
                text("""
                    UPDATE tb_product_external_distribution
                    SET miss_count = miss_count + 1, updated_id = :user_id
                    WHERE product_id = :product_id AND platform = :platform
                """),
                {"product_id": product_id, "platform": platform, "user_id": admin_user_id},
            )
        missed = len(missed_ids)

    return {
        "data": {
            "platform": platform,
            "complete": complete,
            "observedCount": len(observations),
            "matchedCount": len(result["matched"]),
            "insertedCount": inserted,
            "updatedCount": updated,
            "skippedManualCount": skipped_manual,
            "missedCount": missed,
            "unmatched": result["unmatched"][:100],
        }
    }


def build_visible_products_query(user_id: int | None, with_limit: bool = True) -> str:
    query_parts = product_service.get_select_fields_and_joins_for_home_card_product(
        user_id=user_id
    )
    limit_clause = "LIMIT :limit_count OFFSET :offset_count" if with_limit else ""
    return f"""
        SELECT {query_parts["select_fields"]}
        FROM tb_product_external_distribution ped
        INNER JOIN tb_product p ON p.product_id = ped.product_id
        {query_parts["joins"]}
        WHERE {VISIBLE_CONDITION}
        ORDER BY p.last_episode_date DESC, p.product_id DESC
        {limit_clause}
    """


VISIBLE_CONDITION = """
    ped.platform = :platform
    AND ped.status = 'active'
    AND ped.miss_count < :miss_limit
    AND p.price_type = 'paid'
    AND p.open_yn = 'Y'
    AND COALESCE(p.blind_yn, 'N') = 'N'
    AND COALESCE(episode_stats.open_episode_count, 0) >= :min_open_episodes
    AND (:adult_yn = 'Y' OR p.ratings_code != 'adult')
"""


def _visible_params(platform: str, adult_yn: str) -> dict:
    return {
        "platform": platform,
        "miss_limit": MISS_LIMIT,
        "min_open_episodes": PLATFORMS[platform]["min_open_episodes"],
        "adult_yn": "Y" if adult_yn == "Y" else "N",
    }


async def get_visible_products(
    platform: str,
    adult_yn: str,
    user_id: int | None,
    limit: int,
    offset: int,
    db: AsyncSession,
) -> list[dict]:
    params = _visible_params(platform, adult_yn)
    params.update({"limit_count": limit, "offset_count": offset})
    result = await db.execute(text(build_visible_products_query(user_id)), params)
    return [
        product_service.convert_home_card_product_data(row)
        for row in result.mappings().all()
    ]


async def count_visible_products(platform: str, adult_yn: str, db: AsyncSession) -> int:
    query = text(f"""
        SELECT COUNT(*) AS total_count
        FROM tb_product_external_distribution ped
        INNER JOIN tb_product p ON p.product_id = ped.product_id
        LEFT JOIN (
            SELECT product_id, COUNT(*) AS open_episode_count
            FROM tb_product_episode
            WHERE use_yn = 'Y' AND open_yn = 'Y'
            GROUP BY product_id
        ) episode_stats ON episode_stats.product_id = p.product_id
        WHERE {VISIBLE_CONDITION}
    """)
    result = await db.execute(query, _visible_params(platform, adult_yn))
    return int(result.scalar() or 0)


async def get_public_external_distribution_products(
    platform: str,
    page: int,
    limit: int,
    adult_yn: str,
    kc_user_id: str | None,
    db: AsyncSession,
) -> dict:
    require_platform(platform)
    page = max(1, int(page or 1))
    limit = max(1, min(int(limit or 30), PUBLIC_PAGE_LIMIT_MAX))
    user_id = await product_service.get_user_id(kc_user_id, db) if kc_user_id else None
    if user_id == -1:
        user_id = None
    products = await get_visible_products(
        platform, adult_yn, user_id, limit, (page - 1) * limit, db
    )
    total_count = await count_visible_products(platform, adult_yn, db)
    return {
        "data": {
            "platform": platform,
            "platformLabel": PLATFORMS[platform]["label"],
            "minOpenEpisodes": PLATFORMS[platform]["min_open_episodes"],
            "totalCount": total_count,
            "page": page,
            "limit": limit,
            "products": products,
        }
    }


async def get_admin_external_distributions(
    platform: str | None,
    page: int,
    count_per_page: int,
    db: AsyncSession,
) -> dict:
    if platform is not None:
        require_platform(platform)
    params: dict[str, Any] = {"platform": platform, "miss_limit": MISS_LIMIT}
    where = "WHERE (:platform IS NULL OR ped.platform = :platform)"
    count_result = await db.execute(
        text(f"SELECT COUNT(*) FROM tb_product_external_distribution ped {where}"),
        params,
    )
    total_count = int(count_result.scalar() or 0)

    limit_clause, limit_params = get_pagination_params(page, count_per_page)
    params.update(limit_params)
    params.update(
        {
            "kakao_min": PLATFORMS[PLATFORM_KAKAOPAGE]["min_open_episodes"],
            "ridi_min": PLATFORMS[PLATFORM_RIDI]["min_open_episodes"],
        }
    )
    result = await db.execute(
        text(f"""
            SELECT
                ped.id,
                ped.product_id AS productId,
                p.title AS productTitle,
                p.author_name AS authorName,
                ped.platform,
                ped.external_id AS externalId,
                ped.external_title AS externalTitle,
                ped.external_author AS externalAuthor,
                ped.match_method AS matchMethod,
                ped.status,
                ped.miss_count AS missCount,
                ped.first_seen_at AS firstSeenAt,
                ped.last_seen_at AS lastSeenAt,
                COALESCE(episode_stats.open_episode_count, 0) AS openEpisodeCount,
                CASE
                    WHEN ped.status = 'active'
                     AND ped.miss_count < :miss_limit
                     AND p.price_type = 'paid'
                     AND p.open_yn = 'Y'
                     AND COALESCE(p.blind_yn, 'N') = 'N'
                     AND COALESCE(episode_stats.open_episode_count, 0) >= CASE
                         WHEN ped.platform = 'kakaopage' THEN :kakao_min ELSE :ridi_min END
                    THEN 'Y' ELSE 'N'
                END AS visibleYn
            FROM tb_product_external_distribution ped
            INNER JOIN tb_product p ON p.product_id = ped.product_id
            LEFT JOIN (
                SELECT product_id, COUNT(*) AS open_episode_count
                FROM tb_product_episode
                WHERE use_yn = 'Y' AND open_yn = 'Y'
                GROUP BY product_id
            ) episode_stats ON episode_stats.product_id = p.product_id
            {where}
            ORDER BY ped.platform ASC, ped.last_seen_at DESC, ped.id DESC
            {limit_clause}
        """),
        params,
    )
    return build_paginated_response(
        result.mappings().all(), total_count, page, count_per_page
    )


async def post_admin_external_distribution(
    product_id: int,
    platform: str,
    external_id: str,
    admin_user_id: int | None,
    db: AsyncSession,
) -> dict:
    require_platform(platform)
    external_id = str(external_id or "").strip()
    if not external_id:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_REQUEST_DATA,
        )
    candidates = {int(c["product_id"]): c for c in await get_sync_candidates(db)}
    candidate = candidates.get(int(product_id))
    if candidate is None:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_PRODUCT_INFO,
        )
    await db.execute(
        text("""
            INSERT INTO tb_product_external_distribution (
                product_id, platform, external_id, external_title, external_author,
                match_method, status, miss_count, first_seen_at, last_seen_at,
                created_id, updated_id
            ) VALUES (
                :product_id, :platform, :external_id, :external_title, :external_author,
                'manual', 'active', 0, NOW(), NOW(), :user_id, :user_id
            )
            ON DUPLICATE KEY UPDATE
                external_id = VALUES(external_id),
                match_method = 'manual',
                status = 'active',
                miss_count = 0,
                last_seen_at = NOW(),
                updated_id = VALUES(updated_id)
        """),
        {
            "product_id": int(product_id),
            "platform": platform,
            "external_id": external_id,
            "external_title": candidate["title"],
            "external_author": candidate["author_name"],
            "user_id": admin_user_id,
        },
    )
    return {"result": True}


async def _ensure_mapping_exists(mapping_id: int, db: AsyncSession) -> None:
    result = await db.execute(
        text("SELECT id FROM tb_product_external_distribution WHERE id = :id"),
        {"id": mapping_id},
    )
    if result.mappings().one_or_none() is None:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.INVALID_REQUEST_DATA,
        )


async def put_admin_external_distribution_status(
    mapping_id: int, new_status: str, admin_user_id: int | None, db: AsyncSession
) -> dict:
    if new_status not in (STATUS_ACTIVE, STATUS_HIDDEN):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_REQUEST_DATA,
        )
    await _ensure_mapping_exists(mapping_id, db)
    await db.execute(
        text("""
            UPDATE tb_product_external_distribution
            SET status = :status, updated_id = :user_id
            WHERE id = :id
        """),
        {"id": mapping_id, "status": new_status, "user_id": admin_user_id},
    )
    return {"result": True}


async def delete_admin_external_distribution(mapping_id: int, db: AsyncSession) -> dict:
    await _ensure_mapping_exists(mapping_id, db)
    await db.execute(
        text("DELETE FROM tb_product_external_distribution WHERE id = :id"),
        {"id": mapping_id},
    )
    return {"result": True}
