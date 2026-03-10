import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("admin_app")

"""
CMS 작품 평가 서비스 함수 모음
"""


async def cms_product_evaluation_list(
    price_type: str,
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    작품 평가 목록 조회 (tb_product LEFT JOIN tb_cms_product_evaluation)

    Args:
        price_type: 가격유형 (free|paid)
        search_target: 검색 타겟 (product-title|author-name)
        search_word: 검색어
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        페이징된 작품 평가 목록
    """
    where_clauses = ["p.open_yn = 'Y'"]
    params = {}

    if price_type:
        where_clauses.append("p.price_type = :price_type")
        params["price_type"] = price_type

    if search_target and search_word:
        if search_target == "product-title":
            where_clauses.append("p.title LIKE :search_word")
            params["search_word"] = f"%{search_word}%"
        elif search_target == "author-name":
            where_clauses.append("p.author_name LIKE :search_word")
            params["search_word"] = f"%{search_word}%"

    where_sql = " AND ".join(where_clauses)
    offset = (page - 1) * count_per_page

    count_query = text(f"""
        SELECT COUNT(*) AS total_count
        FROM tb_product p
        LEFT JOIN tb_cms_product_evaluation cpe ON p.product_id = cpe.product_id
        WHERE {where_sql}
    """)
    count_result = await db.execute(count_query, params)
    total_count = dict(count_result.mappings().one()).get("total_count", 0)

    list_query = text(f"""
        SELECT
            p.product_id,
            p.title,
            p.author_name,
            p.price_type,
            cpe.evaluation_score,
            cpe.evaluation_yn,
            cpe.updated_date
        FROM tb_product p
        LEFT JOIN tb_cms_product_evaluation cpe ON p.product_id = cpe.product_id
        WHERE {where_sql}
        ORDER BY p.product_id DESC
        LIMIT :limit OFFSET :offset
    """)
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


async def upsert_cms_product_evaluation(
    product_id: int,
    evaluation_score: int,
    user_id: str,
    db: AsyncSession,
):
    """
    작품 평가 upsert (INSERT ON DUPLICATE KEY UPDATE)

    Args:
        product_id: 작품 ID
        evaluation_score: 평가 점수 (0~10, DB에는 *10 하여 0~100)
        user_id: Keycloak 사용자 ID
        db: 데이터베이스 세션

    Returns:
        성공 메시지
    """
    db_score = evaluation_score * 10

    query = text("""
        INSERT INTO tb_cms_product_evaluation
            (product_id, evaluation_score, weight_count_hit, weight_evaluation_score,
             score1, score2, score3, evaluation_yn, created_date, updated_date)
        VALUES
            (:product_id, :evaluation_score, 50, 5,
             0, 0, 0, 'Y', NOW(), NOW())
        ON DUPLICATE KEY UPDATE
            evaluation_score = :evaluation_score,
            weight_count_hit = 50,
            weight_evaluation_score = 5,
            evaluation_yn = 'Y',
            updated_date = NOW()
    """)

    await db.execute(query, {
        "product_id": product_id,
        "evaluation_score": db_score,
    })
    await db.commit()

    return {"data": {"message": "작품 평가가 저장되었습니다."}}
