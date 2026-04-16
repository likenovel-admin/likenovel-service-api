from sqlalchemy import text, bindparam
from sqlalchemy.ext.asyncio import AsyncSession


async def blind_list(
    page: int,
    count_per_page: int,
    blind_yn: str | None,
    search_target: str | None,
    search_word: str | None,
    db: AsyncSession,
):
    where_clauses = ["1=1"]
    params: dict = {}

    if blind_yn and blind_yn in ("Y", "N"):
        where_clauses.append("a.blind_yn = :blind_yn")
        params["blind_yn"] = blind_yn

    if search_target and search_word:
        word = search_word.strip()
        if word:
            if search_target == "product-title":
                where_clauses.append("a.title LIKE :sw")
                params["sw"] = f"%{word}%"
            elif search_target == "author-name":
                where_clauses.append("a.author_name LIKE :sw")
                params["sw"] = f"%{word}%"
            elif search_target == "product-id":
                try:
                    params["pid"] = int(word)
                    where_clauses.append("a.product_id = :pid")
                except ValueError:
                    where_clauses.append("1=0")
            elif search_target == "user-id":
                try:
                    params["uid"] = int(word)
                    where_clauses.append("a.user_id = :uid")
                except ValueError:
                    where_clauses.append("1=0")

    where_sql = " AND ".join(where_clauses)

    count_query = text(f"""
        SELECT COUNT(*) AS cnt
          FROM tb_product a
         WHERE {where_sql}
    """)
    count_result = await db.execute(count_query, params)
    total_count = count_result.scalar() or 0

    offset = (page - 1) * count_per_page
    limit_params = {**params, "limit": count_per_page, "offset": offset}

    query = text(f"""
        SELECT a.product_id
             , a.title
             , a.user_id
             , a.author_name
             , COALESCE(u.email, '') AS author_email
             , COALESCE(g.keyword_name, '') AS primary_genre
             , a.blind_yn
             , a.created_date
             , (SELECT COUNT(*)
                  FROM tb_product_episode e
                 WHERE e.product_id = a.product_id
                   AND e.use_yn = 'Y') AS episode_count
          FROM tb_product a
          LEFT JOIN tb_user u
            ON u.user_id = a.author_id
          LEFT JOIN tb_standard_keyword g
            ON g.keyword_id = a.primary_genre_id
         WHERE {where_sql}
         ORDER BY a.product_id DESC
         LIMIT :limit OFFSET :offset
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "results": [dict(row) for row in rows],
    }


async def batch_blind(
    product_ids: list[int],
    blind_yn: str,
    db: AsyncSession,
):
    if not product_ids:
        return {"result": True, "updated_count": 0}

    blind_val = blind_yn.upper()
    if blind_val not in ("Y", "N"):
        blind_val = "N"

    if blind_val == "Y":
        query = text("""
            UPDATE tb_product
               SET blind_yn = 'Y'
                 , open_yn = 'N'
                 , updated_date = NOW()
             WHERE product_id IN :ids
        """).bindparams(bindparam("ids", expanding=True))
    else:
        query = text("""
            UPDATE tb_product
               SET blind_yn = 'N'
                 , updated_date = NOW()
             WHERE product_id IN :ids
        """).bindparams(bindparam("ids", expanding=True))

    result = await db.execute(query, {"ids": product_ids})

    return {"result": True, "updated_count": result.rowcount}
