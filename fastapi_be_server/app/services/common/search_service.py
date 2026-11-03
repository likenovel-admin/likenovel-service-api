from app.services.product.product_service import (
    convert_product_data,
    get_select_fields_and_joins_for_product,
    get_user_id,
)
from app.utils.query import get_file_path_sub_query
from app.utils.time import get_full_age
from app.services.common.content_search import search_catalog
from fastapi import status
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.exceptions import CustomResponseException
from app.const import ErrorMessages
# from sklearn.metrics.pairwise import cosine_similarity

import logging

logger = logging.getLogger("search_service")


"""
통합검색(search) 도메인 개별 서비스 함수 모음
"""


# Counts, facets and candidate IDs share this eligibility boundary.
SEARCH_ELIGIBILITY = """
    p.open_yn = 'Y' AND COALESCE(p.blind_yn, 'N') = 'N'
    AND (:include_adult = 1 OR p.ratings_code = 'all')
    AND EXISTS (SELECT 1 FROM tb_product_episode e
        WHERE e.product_id = p.product_id AND e.use_yn = 'Y' AND e.open_yn = 'Y')
"""


async def products_of_searched(
    kc_user_id: str, db: AsyncSession, keyword: str = "", adult_yn: str = "N",
    page: int = 1, limit: int = 10, orderby: str = "relevance",
    tags: list[str] | None = None,
):
    keyword = (keyword or "").strip()
    if page < 1 or not 1 <= limit <= 30 or len(keyword) > 100 or len(tags or []) > 12 or any(len(t) > 120 for t in tags or []):
        raise CustomResponseException(status_code=422, message=ErrorMessages.SEARCH_SERVICE_ERROR)
    try:
        user_id = await get_user_id(kc_user_id, db) if kc_user_id else None
        include_adult = False
        if adult_yn == "Y" and user_id:
            adult_result = await db.execute(text("""
                SELECT DATE_FORMAT(birthdate, '%Y-%m-%d') AS birthdate
                FROM tb_user WHERE user_id = :user_id AND use_yn = 'Y'
            """), {"user_id": user_id})
            birthdate = adult_result.scalar_one_or_none()
            include_adult = bool(birthdate and get_full_age(date=birthdate) >= 19)
        params = {"include_adult": int(include_adult)}
        catalogue = await db.execute(text(f"""
            SELECT p.product_id, p.title, p.author_name, p.synopsis_text,
                   p.last_episode_date, p.count_hit,
                   (SELECT JSON_ARRAYAGG(JSON_OBJECT('id', k.keyword_id, 'label', k.keyword_name))
                    FROM tb_mapped_product_keyword mk JOIN tb_standard_keyword k ON k.keyword_id = mk.keyword_id
                    WHERE mk.product_id = p.product_id AND k.use_yn = 'Y') AS standard_keywords,
                   m.analysis_status, m.exclude_from_recommend_yn, m.overall_confidence,
                   m.goal_confidence, m.axis_label_scores, m.protagonist_goal_primary,
                   m.protagonist_type, m.protagonist_type_tags, m.protagonist_job_tags,
                   m.protagonist_material_tags, m.worldview_tags, m.axis_style_tags,
                   m.axis_romance_tags, m.romance_chemistry_weight
            FROM tb_product p
            LEFT JOIN tb_product_ai_metadata m ON m.product_id = p.product_id
                AND m.analysis_status = 'success'
                AND COALESCE(m.exclude_from_recommend_yn, 'N') = 'N'
            WHERE {SEARCH_ELIGIBILITY}
        """), params)
        found = search_catalog([dict(row) for row in catalogue.mappings().all()], keyword, tags, orderby or "relevance")
        selected = found["matches"][(page - 1) * limit:page * limit]
        products = []
        if selected:
            parts = get_select_fields_and_joins_for_product(user_id=user_id, join_rank=False)
            details = await db.execute(text(f"""
                SELECT {parts['select_fields']} FROM tb_product p {parts['joins']}
                WHERE p.product_id IN :product_ids AND {SEARCH_ELIGIBILITY}
            """).bindparams(bindparam("product_ids", expanding=True)), {
                **params, "product_ids": [row["product_id"] for row in selected],
            })
            by_id = {row["productId"]: convert_product_data(row) for row in details.mappings().all()}
            for item in selected:
                product = by_id.get(item["product_id"])
                if product is not None:
                    product["searchMatchReasons"] = item["searchMatchReasons"]
                    products.append(product)
        events, quests = [], []
        # Preserve keyword-only event/quest callers; selected product tags never apply to events.
        if keyword and not tags:
            event_result = await db.execute(text(f"""
                SELECT e.*, {get_file_path_sub_query('e.thumbnail_image_id', 'thumbnail_image_path')},
                       {get_file_path_sub_query('e.detail_image_id', 'detail_image_path')}
                FROM tb_event_v2 e WHERE title LIKE :keyword
                  AND CURRENT_TIMESTAMP BETWEEN start_date AND end_date
            """), {"keyword": f"%{keyword}%"})
            events = [dict(row) for row in event_result.mappings().all()]
            quest_result = await db.execute(text("""
                SELECT quest_id AS questId, title AS questTitle, '' AS questContent
                FROM tb_quest WHERE title LIKE :keyword
            """), {"keyword": f"%{keyword}%"})
            quests = [dict(row) for row in quest_result.mappings().all()]
        return {"data": {"products": products, "events": events, "quests": quests,
                         "facets": found["facets"], "totalCount": found["totalCount"],
                         "selectedTags": found["selectedTags"],
                         "page": page, "pageSize": limit}}
    except CustomResponseException:
        raise
    except Exception:
        logger.exception("Content search failed")
        raise CustomResponseException(status_code=500, message=ErrorMessages.SEARCH_SERVICE_ERROR)


async def results_of_autocomplete(
    kc_user_id: str, db: AsyncSession, keyword: str, adult_yn: str = "N"
):
    """
    일반 통합검색 자동완성 키워드
    """

    try:
        user_id = await get_user_id(kc_user_id, db)
        query_parts = get_select_fields_and_joins_for_product(
            user_id=user_id, join_rank=False
        )
        # adult_yn='Y': 전체 조회 (성인 포함), adult_yn='N': 성인 제외 (all만)
        ratings_filter = "" if adult_yn == "Y" else "and p.ratings_code = 'all'"

        query = text(f"""
            select {query_parts["select_fields"]}
            from tb_product p
            {query_parts["joins"]}
            where
                (
                    p.title like :keyword
                    or
                    p.author_name like :keyword
                )
                {ratings_filter}
                and p.open_yn = 'Y'
            limit 10 offset 0
        """)
        result = await db.execute(
            query,
            {
                "keyword": f"%{keyword}%",
            },
        )
        rows = result.mappings().all()
        product_all = [convert_product_data(row) for row in rows]

        query = text("""
            select
                id as eventId,
                title as eventTitle,
                information as eventContent
            from tb_event_v2
            where title like :keyword
            limit 3 offset 0
        """)
        result = await db.execute(query, {"keyword": f"%{keyword}%"})
        rows = result.mappings().all()
        events = [dict(row) for row in rows]

        try:
            titles = list(set([product["title"] for product in product_all]))
            authorNicknames = list(
                set([product["authorNickname"] for product in product_all])
            )[:3]
            # keywords = list(set([product['keywords'] for product in product_all]))[:3]

        except Exception as e:
            logger.error(f"Error: {e}")

        titles_data = [
            {"key": "product", "content": title}
            for title in titles
            if title is not None and title != ""
        ]
        authorNicknames_data = [
            {"key": "author", "content": authorNickname}
            for authorNickname in authorNicknames
            if authorNickname is not None and authorNickname != ""
        ]
        # keywords_data = [{'key': 'keyword', 'content': keyword} for keyword in keywords if keyword is not None]
        events_data = [
            {"key": "event", "content": event}
            for event in events
            if event is not None and event != ""
        ]

        # 모든 배열 통합
        combined_results = titles_data + authorNicknames_data + events_data

        res_body = dict()
        res_body["data"] = combined_results
        return res_body

    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.SEARCH_SERVICE_ERROR,
        )


async def products_of_search_by_story(story: str, adult_yn: str = "N"):
    # Retire the unused embedding endpoint without calling an external provider.
    raise CustomResponseException(
        status_code=410, message="스토리 검색이 작품 검색으로 통합되었습니다."
    )


async def get_trending_keywords():
    # Retired: old deployed clients may still call this route during rollout.
    # Remove the endpoint once those clients have migrated to content search.
    return []


async def get_weekly_most_viewed_products(
    kc_user_id: str,
    db: AsyncSession,
    adult_yn: str = "N",
    page: int = 1,
    limit: int = 10,
):
    """
    금주의 최다 조회 작품 목록 조회
    최근 7일간 조회수가 가장 많은 작품을 반환
    """
    try:
        user_id = await get_user_id(kc_user_id, db)

        # 전체 개수 조회
        count_query = text("""
            SELECT COUNT(DISTINCT phl.product_id) as total_count
            FROM tb_product_hit_log phl
            WHERE phl.hit_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
        """)
        count_result = await db.execute(count_query)
        total_count = count_result.scalar() or 0

        # 최근 7일간 조회수 상위 작품 ID 조회
        query = text("""
            SELECT
                phl.product_id,
                SUM(phl.hit_count) as weekly_hits
            FROM tb_product_hit_log phl
            WHERE phl.hit_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
            GROUP BY phl.product_id
            ORDER BY weekly_hits DESC
            LIMIT :limit OFFSET :offset
        """)
        result = await db.execute(query, {"limit": limit, "offset": (page - 1) * limit})
        weekly_hits_rows = result.mappings().all()

        if not weekly_hits_rows:
            return {"data": [], "totalCount": total_count, "pageSize": limit}

        # 작품 ID 목록
        product_ids = [row["product_id"] for row in weekly_hits_rows]

        # 작품 상세 정보 조회
        query_parts = get_select_fields_and_joins_for_product(
            user_id=user_id, join_rank=False
        )
        # adult_yn='Y': 전체 조회 (성인 포함), adult_yn='N': 성인 제외 (all만)
        ratings_filter = "" if adult_yn == "Y" else "AND p.ratings_code = 'all'"

        query = text(f"""
            SELECT {query_parts["select_fields"]}
            FROM tb_product p
            {query_parts["joins"]}
            WHERE p.product_id IN :product_ids
                {ratings_filter}
                AND p.open_yn = 'Y'
        """)
        result = await db.execute(
            query,
            {
                "product_ids": tuple(product_ids),
            },
        )
        rows = result.mappings().all()

        # product_id를 키로 하는 딕셔너리 생성
        products_dict = {row["productId"]: convert_product_data(row) for row in rows}

        # 조회수 순서대로 정렬하여 반환
        products = []
        for hit_row in weekly_hits_rows:
            product_id = hit_row["product_id"]
            if product_id in products_dict:
                product = products_dict[product_id]
                product["weeklyHits"] = hit_row["weekly_hits"]
                products.append(product)

        return {"data": products, "totalCount": total_count, "pageSize": limit}

    except Exception as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.SEARCH_SERVICE_ERROR,
        )


async def search_products_for_review(
    kc_user_id: str,
    db: AsyncSession,
    keyword: str,
    adult_yn: str = "N",
    limit: int | None = None,
):
    """
    리뷰 작성용 작품 검색
    작품명, 작가명으로 검색
    """
    try:
        user_id = await get_user_id(kc_user_id, db)

        query_parts = get_select_fields_and_joins_for_product(
            user_id=user_id, join_rank=False
        )
        # adult_yn='Y': 전체 조회 (성인 포함), adult_yn='N': 성인 제외 (all만)
        ratings_filter = "" if adult_yn == "Y" else "AND p.ratings_code = 'all'"

        query = text(f"""
            SELECT {query_parts["select_fields"]}
            FROM tb_product p
            {query_parts["joins"]}
            WHERE
                (
                    p.title LIKE :keyword
                    OR
                    p.author_name LIKE :keyword
                )
                {ratings_filter}
                AND p.open_yn = 'Y'
            ORDER BY p.last_episode_date DESC
            {f"LIMIT {limit}" if limit is not None else ""}
        """)
        result = await db.execute(
            query,
            {
                "keyword": f"%{keyword}%",
            },
        )
        rows = result.mappings().all()
        products = [convert_product_data(row) for row in rows]

        return {"data": products}

    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.SEARCH_SERVICE_ERROR,
        )
