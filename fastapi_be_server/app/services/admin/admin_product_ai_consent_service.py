from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def product_ai_consent_list(
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
) -> dict[str, Any]:
    """작품별 AI 활용 동의 현황 조회."""
    page = max(page, 1)
    count_per_page = max(1, min(count_per_page, 100))

    where_clauses = ["1 = 1"]
    params: dict[str, Any] = {}

    normalized_search_word = (search_word or "").strip()
    if search_target and normalized_search_word:
        if search_target == "product-id":
            if normalized_search_word.isdigit():
                where_clauses.append("p.product_id = :product_id")
                params["product_id"] = int(normalized_search_word)
            else:
                where_clauses.append("1 = 0")
        elif search_target == "product-title":
            where_clauses.append("p.title LIKE :search_word")
            params["search_word"] = f"%{normalized_search_word}%"
        elif search_target == "nickname":
            where_clauses.append("p.author_name LIKE :search_word")
            params["search_word"] = f"%{normalized_search_word}%"

    where_sql = " AND ".join(where_clauses)
    offset = (page - 1) * count_per_page

    count_query = text(
        f"""
        SELECT COUNT(*) AS total_count
        FROM tb_product p
        WHERE {where_sql}
        """
    )
    count_result = await db.execute(count_query, params)
    total_count = dict(count_result.mappings().one()).get("total_count", 0)

    list_query = text(
        f"""
        SELECT
            p.product_id,
            p.title,
            p.author_name AS nickname,
            (
                SELECT COUNT(*)
                FROM tb_product_episode e
                WHERE e.product_id = p.product_id
                  AND e.use_yn = 'Y'
            ) AS episode_count,
            CASE WHEN p.open_yn = 'Y' THEN 'Y' ELSE 'N' END AS open_yn,
            CASE
                WHEN p.ai_external_promotion_yn = 'Y' THEN 'Y'
                ELSE 'N'
            END AS ai_promotion_yn,
            CASE
                WHEN COALESCE((
                    SELECT sacp.context_status
                    FROM tb_story_agent_context_product sacp
                    WHERE sacp.product_id = p.product_id
                    LIMIT 1
                ), 'pending') = 'disabled'
                THEN 'N'
                ELSE 'Y'
            END AS websochat_enabled_yn
        FROM tb_product p
        WHERE {where_sql}
        ORDER BY p.product_id DESC
        LIMIT :limit OFFSET :offset
        """
    )
    params["limit"] = count_per_page
    params["offset"] = offset
    result = await db.execute(list_query, params)
    rows = [dict(row) for row in result.mappings().all()]

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "results": rows,
    }
