import json
import logging
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta

from app.exceptions import CustomResponseException
from app.utils.query import (
    get_pagination_params,
    build_role_where_clause,
)
from app.utils.response import build_paginated_response, check_exists_or_404
from app.utils.common import handle_exceptions
from app.const import CommonConstants
from app.const import ErrorMessages

logger = logging.getLogger("partner_app")  # 커스텀 로거 생성

"""
partner 파트너 통계 분석 관련 서비스 함수 모음
"""


async def product_statistics_list(
    search_target: str,
    search_word: str,
    search_start_date: str,
    search_end_date: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
    user_data: dict,
):
    """
    작품별 통계 리스트 조회

    Args:
        search_target: 검색 대상 (product-title: 작품명, product-id: 작품ID, author-name: 작가명)
        search_word: 검색어
        search_start_date: 검색 시작일
        search_end_date: 검색 종료일
        page: 페이지 번호
        count_per_page: 페이지당 개수
        db: 데이터베이스 세션

    Returns:
        작품별 통계 리스트 및 페이징 정보
    """

    where = build_role_where_clause(user_data)

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where += f"""
                          AND s.title LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_PRODUCT_ID:
            if not search_word.isdigit():
                # 숫자가 아닌 경우 에러 처리
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.SEARCH_WORD_MUST_BE_NUMBER,
                )
            where += f"""
                          AND s.product_id = {search_word}
                          """
        elif search_target == CommonConstants.SEARCH_AUTHOR_NAME:
            where += f"""
                          AND s.author_nickname LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_CP_NAME:
            where += f"""
                          AND s.product_id IN (
                                select z.product_id
                                from tb_product_contract_offer z
                                inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
                                and y.apply_type = 'cp'
                                and y.approval_date is not null
                                where z.use_yn = 'Y'
                                and z.author_accept_yn = 'Y'
                                and y.company_name LIKE '%{search_word}%'
                          )
                          """

    if search_start_date != "":
        where += f"""
                      AND DATE(s.created_date) >= '{search_start_date}'
                      """

    if search_end_date != "":
        where += f"""
                      AND DATE(s.created_date) <= '{search_end_date}'
                      """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        select count(*) as total_count
        from tb_ptn_product_statistics s
        inner join tb_product p on p.product_id = s.product_id
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 1단계: 통계 데이터 조회 (cp_company_name 제외)
    query = text(f"""
        select p.*, s.*
        from tb_ptn_product_statistics s
        inner join tb_product p on p.product_id = s.product_id
        WHERE 1=1 {where}
        ORDER BY s.created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()
    results = [dict(row) for row in rows]

    # 2단계: product_id 목록 추출 후 cp_company_name 일괄 조회
    product_ids = list({row["product_id"] for row in results})
    cp_map = {}
    if product_ids:
        cp_query = text("""
            SELECT t.product_id, t.company_name as cp_company_name
            FROM (
                SELECT z.product_id, y.company_name,
                    ROW_NUMBER() OVER (PARTITION BY z.product_id ORDER BY z.updated_date DESC) as rn
                FROM tb_product_contract_offer z
                INNER JOIN tb_user_profile_apply y ON z.offer_user_id = y.user_id
                    AND y.apply_type = 'cp'
                    AND y.approval_date is not null
                WHERE z.product_id IN :product_ids
                    AND z.use_yn = 'Y'
                    AND z.author_accept_yn = 'Y'
            ) t
            WHERE t.rn = 1
        """)
        cp_result = await db.execute(cp_query, {"product_ids": tuple(product_ids)})
        cp_map = {
            row["product_id"]: row["cp_company_name"]
            for row in cp_result.mappings().all()
        }

    # 3단계: 결과에 cp_company_name 매핑
    for row in results:
        row["cp_company_name"] = cp_map.get(row["product_id"])

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "results": results,
    }


@handle_exceptions
async def product_episode_statistics_list(
    search_target: str,
    search_word: str,
    search_start_date: str,
    search_end_date: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
    user_data: dict,
):
    """
    회차별 통계 리스트 조회

    Args:
        search_target: 검색 대상 (product-title: 작품명, product-id: 작품ID, author-name: 작가명)
        search_word: 검색어
        search_start_date: 검색 시작일
        search_end_date: 검색 종료일
        page: 페이지 번호
        count_per_page: 페이지당 개수
        db: 데이터베이스 세션
        user_data: 사용자 정보

    Returns:
        회차별 통계 리스트 및 페이징 정보
    """

    where = build_role_where_clause(user_data)

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where += f"""
                          AND s.title LIKE '%{search_word}%'
                          """
        if (
            search_target == CommonConstants.SEARCH_PRODUCT_ID
            and user_data["role"] == "admin"
        ):
            if not search_word.isdigit():
                # 숫자가 아닌 경우 에러 처리
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.SEARCH_WORD_MUST_BE_NUMBER,
                )
            where += f"""
                          AND s.product_id = {search_word}
                          """
        if (
            search_target == CommonConstants.SEARCH_AUTHOR_NAME
            and user_data["role"] == "admin"
        ):
            where += f"""
                          AND s.author_nickname LIKE '%{search_word}%'
                          """
        if (
            search_target == CommonConstants.SEARCH_CP_NAME
            and user_data["role"] == "admin"
        ):
            where += f"""
                          AND s.product_id IN (
                                select z.product_id
                                from tb_product_contract_offer z
                                inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
                                and y.apply_type = 'cp'
                                and y.approval_date is not null
                                where z.use_yn = 'Y'
                                and z.author_accept_yn = 'Y'
                                and y.company_name LIKE '%{search_word}%'
                          )
                          """

    if search_start_date != "":
        where += f"""
                      AND DATE(s.created_date) >= '{search_start_date}'
                      """

    if search_end_date != "":
        where += f"""
                      AND DATE(s.created_date) <= '{search_end_date}'
                      """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 조회(/all)인 경우 count 쿼리 스킵
    is_full_query = page == -1 or count_per_page == -1

    total_count = 0
    if not is_full_query:
        # 전체 개수 구하기 (페이징 시에만)
        count_query = text(f"""
            select count(*) as total_count
            from tb_ptn_product_episode_statistics s
            inner join tb_product p on p.product_id = s.product_id
            WHERE 1=1 {where}
        """)
        count_result = await db.execute(count_query, {})
        total_count = count_result.mappings().first()["total_count"]

    # 1단계: 통계 데이터 조회 (cp_company_name 제외)
    query = text(f"""
        select p.*, s.*
            , date(s.created_date) as `date`
            , e.episode_title
        from tb_ptn_product_episode_statistics s
        inner join tb_product p on p.product_id = s.product_id
        left join tb_product_episode e on e.product_id = p.product_id and e.episode_no = s.episode_no and e.use_yn = 'Y'
        WHERE 1=1 {where}
        ORDER BY s.created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()
    results = [dict(row) for row in rows]

    # 전체 조회 시 결과 개수를 total_count로 사용
    if is_full_query:
        total_count = len(results)

    # 2단계: product_id 목록 추출 후 cp_company_name 일괄 조회
    product_ids = list({row["product_id"] for row in results})
    cp_map = {}
    if product_ids:
        cp_query = text("""
            SELECT t.product_id, t.company_name as cp_company_name
            FROM (
                SELECT z.product_id, y.company_name,
                    ROW_NUMBER() OVER (PARTITION BY z.product_id ORDER BY z.updated_date DESC) as rn
                FROM tb_product_contract_offer z
                INNER JOIN tb_user_profile_apply y ON z.offer_user_id = y.user_id
                    AND y.apply_type = 'cp'
                    AND y.approval_date is not null
                WHERE z.product_id IN :product_ids
                    AND z.use_yn = 'Y'
                    AND z.author_accept_yn = 'Y'
            ) t
            WHERE t.rn = 1
        """)
        cp_result = await db.execute(cp_query, {"product_ids": tuple(product_ids)})
        cp_map = {
            row["product_id"]: row["cp_company_name"]
            for row in cp_result.mappings().all()
        }

    # 3단계: 결과에 cp_company_name 매핑
    for row in results:
        row["cp_company_name"] = cp_map.get(row["product_id"])

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "results": results,
    }


async def cart_analysis_list(
    search_target: str,
    search_word: str,
    type: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
    user_data: dict,
):
    """
    장바구니 분석 리스트 조회

    Args:
        search_target: 검색 대상 (product-title: 작품명, product-id: 작품ID, author-name: 작가명)
        search_word: 검색어
        type: 분석 타입
        page: 페이지 번호
        count_per_page: 페이지당 개수
        db: 데이터베이스 세션

    Returns:
        장바구니 분석 리스트 및 페이징 정보
    """

    where = build_role_where_clause(
        user_data, author_id_column="author_id", product_id_column="product_id"
    )

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where += f"""
                          AND title LIKE '%{search_word}%'
                          """
        if search_target == "product-id":
            if not search_word.isdigit():
                # 숫자가 아닌 경우 에러 처리
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.SEARCH_WORD_MUST_BE_NUMBER,
                )
            where += f"""
                          AND product_id = {search_word}
                          """
        if search_target == "author-name":
            where += f"""
                          AND author_name LIKE '%{search_word}%'
                          """
        if search_target == "cp-name":
            where += f"""
                          AND product_id IN (
                                select z.product_id
                                from tb_product_contract_offer z
                                inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
                                and y.apply_type = 'cp'
                                and y.approval_date is not null
                                where z.use_yn = 'Y'
                                and z.author_accept_yn = 'Y'
                                and y.company_name LIKE '%{search_word}%'
                          )
                          """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        select count(*) as total_count
        from tb_product
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        select
            product_id, title
        from tb_product
        WHERE 1=1 {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    # bookmark | tag | similar-user -> cart | genre | content, default: bookmark
    if type == "tag":
        type_value = "genre"
    elif type == "similar-user":
        type_value = "content"
    else:
        type_value = "cart"

    # N+1 쿼리 최적화: 모든 product_id들을 한번에 조회
    product_ids = [row["product_id"] for row in rows]

    # 작품이 없으면 빈 결과 반환
    if not product_ids:
        return {
            "total_count": total_count,
            "page": page,
            "count_per_page": count_per_page,
            "results": [],
        }

    # 모든 알고리즘 추천 데이터를 한번에 조회
    similar_data_query = text("""
        select
            product_id, similar_subject_ids
        from tb_algorithm_recommend_similar
        where product_id in :product_ids and type = :type
    """)
    similar_data_result = await db.execute(
        similar_data_query, {"product_ids": tuple(product_ids), "type": type_value}
    )
    similar_data_rows = similar_data_result.mappings().all()

    # 알고리즘 데이터를 딕셔너리로 변환하여 빠른 조회 가능하도록 함
    similar_data_dict = {}
    all_related_product_ids = set()

    for similar_row in similar_data_rows:
        product_id = similar_row["product_id"]
        related_ids = json.loads(similar_row["similar_subject_ids"])
        similar_data_dict[product_id] = related_ids
        all_related_product_ids.update(related_ids)

    # 모든 관련 상품 정보를 한번에 조회
    products_data_dict = {}
    if all_related_product_ids:
        products_query = text("""
            select
                product_id, title
            from tb_product
            where product_id in :product_ids
            order by count_hit desc
        """)
        products_result = await db.execute(
            products_query, {"product_ids": tuple(all_related_product_ids)}
        )
        products_rows = products_result.mappings().all()

        for product_row in products_rows:
            products_data_dict[product_row["product_id"]] = product_row["title"]

    # 결과 조합
    results = []
    for row in rows:
        data = dict(row)
        product_id = data.get("product_id")

        # 해당 상품의 추천 상품 ID들을 가져옴
        related_ids = similar_data_dict.get(product_id, [])

        # 관련 상품들을 조회수 순으로 정렬하고 최대 10개까지만 표시
        related_products = []
        for rel_id in related_ids[:10]:  # 최대 10개
            if rel_id in products_data_dict:
                related_products.append(
                    {"product_id": rel_id, "title": products_data_dict[rel_id]}
                )

        # 1~10번까지 relative 필드 설정
        for num in range(1, 11):
            if num <= len(related_products):
                data[f"relative_{num}_product_id"] = related_products[num - 1][
                    "product_id"
                ]
                data[f"relative_{num}_product_title"] = related_products[num - 1][
                    "title"
                ]
            else:
                data[f"relative_{num}_product_id"] = None
                data[f"relative_{num}_product_title"] = None

        results.append(data)

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "results": results,
    }


async def hourly_inflow_product_list(
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
    user_data: dict,
):
    """
    시간대별 작품별 유입 리스트 조회

    Args:
        search_target: 검색 대상 (product-title: 작품명, product-id: 작품ID, author-name: 작가명)
        search_word: 검색어
        page: 페이지 번호
        count_per_page: 페이지당 개수
        db: 데이터베이스 세션

    Returns:
        시간대별 작품별 유입 리스트 및 페이징 정보
    """

    where = build_role_where_clause(
        user_data, author_id_column="author_id", product_id_column="product_id"
    )

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where += f"""
                          AND title LIKE '%{search_word}%'
                          """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        select count(*) as total_count
        from tb_product
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        select *
        from tb_product
        WHERE 1=1 {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def hourly_inflow_detail_by_product_id(
    id: int,
    search_date: str,
    search_target: str,
    search_word: str,
    db: AsyncSession,
    user_data: dict,
):
    """
    작품별 시간대별 유입 상세 조회

    Args:
        id: 작품 ID
        search_date: 검색 날짜
        search_target: 검색 대상
        search_word: 검색어
        db: 데이터베이스 세션
        user_data: 사용자 정보

    Returns:
        시간대별 유입 상세 정보
    """

    # 작품 존재 여부 확인
    product_query = text(
        "SELECT COUNT(*) as count FROM tb_product WHERE product_id = :product_id"
    )
    product_result = await db.execute(product_query, {"product_id": id})
    if product_result.mappings().first()["count"] == 0:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_PRODUCT,
        )

    where = build_role_where_clause(user_data)
    product_title_join = ""

    if user_data["role"] in ["author", "partner"]:
        product_title_join = """
            INNER JOIN tb_product p ON hi.product_id = p.product_id
        """

    if search_date != "":
        where += f"""
                     AND DATE(created_date) = '{search_date}'
                     """

    if search_word != "" and search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
        if product_title_join == "":
            product_title_join = """
                INNER JOIN tb_product p ON hi.product_id = p.product_id
            """
        where += f"""
                          AND p.title LIKE '%{search_word}%'
                          """

    query = text(f"""
        SELECT
            HOUR(hi.created_date) + 1 AS `hour`,
            SUM(hi.total_view_count) AS total_view_count,
            SUM(hi.total_payment_count) AS total_payment_count,
            SUM(hi.male_view_count) AS male_view_count,
            SUM(hi.female_view_count) AS female_view_count,
            SUM(hi.male_payment_count) AS male_payment_count,
            SUM(hi.female_payment_count) AS female_payment_count,
            SUM(hi.male_20_under_payment_count) AS male_20_under_payment_count,
            SUM(hi.male_30_payment_count) AS male_30_payment_count,
            SUM(hi.male_40_payment_count) AS male_40_payment_count,
            SUM(hi.male_50_payment_count) AS male_50_payment_count,
            SUM(hi.male_60_over_payment_count) AS male_60_over_payment_count,
            SUM(hi.female_20_under_payment_count) AS female_20_under_payment_count,
            SUM(hi.female_30_payment_count) AS female_30_payment_count,
            SUM(hi.female_40_payment_count) AS female_40_payment_count,
            SUM(hi.female_50_payment_count) AS female_50_payment_count,
            SUM(hi.female_60_over_payment_count) AS female_60_over_payment_count,
            SUM(hi.male_20_under_view_count) AS male_20_under_view_count,
            SUM(hi.male_30_view_count) AS male_30_view_count,
            SUM(hi.male_40_view_count) AS male_40_view_count,
            SUM(hi.male_50_view_count) AS male_50_view_count,
            SUM(hi.male_60_over_view_count) AS male_60_over_view_count,
            SUM(hi.female_20_under_view_count) AS female_20_under_view_count,
            SUM(hi.female_30_view_count) AS female_30_view_count,
            SUM(hi.female_40_view_count) AS female_40_view_count,
            SUM(hi.female_50_view_count) AS female_50_view_count,
            SUM(hi.female_60_over_view_count) AS female_60_over_view_count
        FROM tb_hourly_inflow hi
        {product_title_join}
        WHERE hi.product_id = :product_id {where}
        GROUP BY `hour`
        ORDER BY `hour` ASC
    """)
    result = await db.execute(query, {"product_id": id})
    rows = result.mappings().all()

    data = []
    for hour in list(range(24)):
        data.append(
            {
                "hour": hour + 1,
                "total_view_count": 0,
                "total_payment_count": 0,
                "male_view_count": 0,
                "female_view_count": 0,
                "male_payment_count": 0,
                "female_payment_count": 0,
                "male_20_under_payment_count": 0,
                "male_30_payment_count": 0,
                "male_40_payment_count": 0,
                "male_50_payment_count": 0,
                "male_60_over_payment_count": 0,
                "female_20_under_payment_count": 0,
                "female_30_payment_count": 0,
                "female_40_payment_count": 0,
                "female_50_payment_count": 0,
                "female_60_over_payment_count": 0,
                "male_20_under_view_count": 0,
                "male_30_view_count": 0,
                "male_40_view_count": 0,
                "male_50_view_count": 0,
                "male_60_over_view_count": 0,
                "female_20_under_view_count": 0,
                "female_30_view_count": 0,
                "female_40_view_count": 0,
                "female_50_view_count": 0,
                "female_60_over_view_count": 0,
            }
        )

    if len(rows) > 0:
        for row in rows:
            row_dict = dict(row)
            data[int(row_dict.get("hour")) - 1] = row_dict

    return data


async def product_discovery_statistics_list(
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
    user_data: dict,
):
    """
    발굴 통계에서 발굴작품 목록을 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        search_target: 검색 대상 (story, keyword-genre)
        search_word: 검색어
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 발굴작품 통계 목록 (커버 이미지 포함)
    """

    where = """"""
    if user_data["role"] == "author":
        where += f"""
            AND product_id IN (SELECT product_id FROM tb_product WHERE author_id = {user_data["user_id"]})
        """
    # elif user_data["role"] == "partner":
    #     where += f"""
    #         AND product_id IN (
    #             select z.product_id
    #             from tb_product_contract_offer z
    #             inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
    #             and y.apply_type = 'cp'
    #             and y.approval_date is not null
    #             where z.use_yn = 'Y'
    #             and z.author_accept_yn = 'Y'
    #             and y.user_id = {user_data["user_id"]}
    #         )
    #     """

    if search_word != "":
        if search_target == "story":
            where += f"""
                          AND product_id IN (SELECT product_id FROM tb_product WHERE title LIKE '%{search_word}%' OR synopsis_text LIKE '%{search_word}%')
                          """
        elif search_target == "keyword-genre":
            where += f"""
                          AND (
                              primary_genre LIKE '%{search_word}%'
                              OR
                              sub_genre LIKE '%{search_word}%'
                          )
                          """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        select count(*) as total_count
        from tb_ptn_product_discovery_statistics
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        select *
            , (select y.file_path from tb_common_file z, tb_common_file_item y
                where z.file_group_id = y.file_group_id
                and z.use_yn = 'Y'
                and y.use_yn = 'Y'
                and z.group_type = 'cover'
                and (select thumbnail_file_id from tb_product where product_id = ppds.product_id) = z.file_group_id) as cover_image_path
        from tb_ptn_product_discovery_statistics ppds
        WHERE 1=1 {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def product_discovery_statistics_detail_by_id(id: int, db: AsyncSession):
    """
    특정 발굴작품의 상세 통계 정보를 조회하고 각종 지표를 계산

    Args:
        id: 발굴 통계 ID
        db: 데이터베이스 세션

    Returns:
        dict: 발굴가치, 활성 독자율, 독자 선호율, 선인세 제안범위, 연재 성실성 등의 상세 통계 정보
    """

    async def _query(query_str: str, params: dict = {}):
        query = text(query_str)
        result = await db.execute(query, params)
        rows = result.mappings().all()
        return [dict(row) for row in rows]

    statistics_data = await _query(
        """
        select
            ppds.*,
            cpe.*
        from tb_ptn_product_discovery_statistics ppds
        inner join tb_cms_product_evaluation cpe on cpe.product_id = ppds.product_id
        WHERE ppds.id = :id
    """,
        {"id": id},
    )

    check_exists_or_404(statistics_data, ErrorMessages.NOT_FOUND_DISCOVERY_STAT)

    data = statistics_data[0]

    # 발굴가치 = score1, score2, score3 평균값으로 범위별로 높음/보통/낮음
    avg_score = (data["score1"] + data["score2"] + data["score3"]) / 3
    if avg_score < 2:
        data["excavation_value"] = "낮음"
    elif avg_score < 3.5:
        data["excavation_value"] = "보통"
    else:
        data["excavation_value"] = "높음"

    # 활성 독자율 = 관심 유지수 / 독자수 * 100, 신규독자 유입율에서 독자수가 없다는데 일단 전체 관심 수를 독자수로 간주해서 계산하겠음
    # 독자 선호율 = 누적 선호작 수 / 독자수 * 100, 신규독자 유입율에서 독자수가 없다는데 일단 전체 관심 수를 독자수로 간주해서 계산하겠음
    interest_summary = await _query(
        """
        select y.product_id
            , count(y.free_keep_interest) as count_free_interest
            , sum(case when y.free_keep_interest = 'sustain' then 1 else 0 end) as count_free_interest_sustain
            , sum(case when y.free_keep_interest = 'loss' then 1 else 0 end) as count_free_interest_loss
        from (
            select z.user_id
                , z.product_id
                , case when floor(timestampdiff(second, curdate(), max(z.updated_date)) / 3600) <= 72
                        then 'loss'
                        else 'sustain'
                end as free_keep_interest
            from tb_user_product_usage z
            where z.use_yn = 'Y'
            and z.updated_date < curdate()
            group by z.user_id, z.product_id
        ) y
        where y.product_id = :product_id
        group by y.product_id
    """,
        {"product_id": data["product_id"]},
    )
    bookmark_count = int(data.get("count_bookmark") or 0)
    if (
        len(interest_summary) > 0
        and int(interest_summary[0].get("count_free_interest") or 0) > 0
    ):
        total_interest = int(interest_summary[0]["count_free_interest"])
        sustain_interest = int(interest_summary[0]["count_free_interest_sustain"])
        data["active_reader_rate"] = (sustain_interest / total_interest) * 100
        data["reader_preference_rate"] = (bookmark_count / total_interest) * 100
    else:
        data["active_reader_rate"] = 0
        data["reader_preference_rate"] = 0

    # 선인세 제안범위 = 제안받은 선인세 최소값 ~ 최대값, 선인세 = 계약금, [최소값, 최대값] 형태로 리턴, 금액 직접 입력인 경우 최소값 == 최대값
    contract_offer = await _query(
        """
        select z.*
        from tb_product_contract_offer z
        inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
        and y.apply_type = 'cp'
        and y.approval_date is not null
        where z.use_yn = 'Y'
        and z.author_accept_yn = 'Y'
        and z.product_id = :product_id
    """,
        {"product_id": data["product_id"]},
    )
    if len(contract_offer) == 0:  # 계약 내용이 조회가 안됨
        data["advance_tax_proposal_scope"] = [0, 0]
    elif contract_offer[0]["offer_type"] == "input":  # 금액 직접 입력
        data["advance_tax_proposal_scope"] = [
            int(contract_offer[0]["offer_price"]),
            int(contract_offer[0]["offer_price"]),
        ]
    else:
        data["advance_tax_proposal_scope"] = [
            int(value) * 10000 for value in "~".split(contract_offer[0]["offer_code"])
        ]  # 만 단위이기 때문에 10000을 곱해서 리턴

    # 연재 성실성 = 주평균 연재횟수
    data["serial_integrity"] = data["writing_count_per_week"]

    # 신규독자 유입율 = (최근일(D-day) 1화 조회수-24시간 1화 조회수)/24시간 1화 조회수*100, 근데 독자수가 없어서 계산 불가능이라는데...?
    # 첫화 기준 신규독자 유입율 계산을 단일 쿼리로 통합
    first_ep_usage = await _query(
        """
        SELECT
            IFNULL(SUM(CASE WHEN FLOOR(TIMESTAMPDIFF(SECOND, CURDATE(), u.created_date) / 3600) <= 24 THEN 1 ELSE 0 END), 0) AS cnt_24h,
            IFNULL(SUM(CASE WHEN DATE(u.created_date) = CURDATE() THEN 1 ELSE 0 END), 0) AS cnt_today
        FROM tb_user_product_usage u
        WHERE u.episode_id = (
            SELECT pe.episode_id
            FROM tb_product_episode pe
            WHERE pe.product_id = :product_id
            ORDER BY pe.episode_no ASC
            LIMIT 1
        )
    """,
        {"product_id": data["product_id"]},
    )
    if len(first_ep_usage) == 0 or first_ep_usage[0]["cnt_24h"] == 0:
        data["new_reader_inflow_rate"] = 0
    else:
        data["new_reader_inflow_rate"] = (
            (first_ep_usage[0]["cnt_today"] - first_ep_usage[0]["cnt_24h"])
            / first_ep_usage[0]["cnt_24h"]
        ) * 100

    # 라이크노벨 평가 = score1(창의력), score2(완성도), score3(대중성), 테이블 join해서 select함

    today = datetime.today().date()
    last_week_dates = [
        (today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)
    ]

    # 기간별 연독률 통계(최근 7일)
    count_trends = await _query(
        """
        select
            date(created_date) as `date`,
            current_reading_rate as reading_rate,
            current_count_interest_sustain as count_interest_sustain,
            current_count_interest_loss as count_interest_loss
        from tb_batch_daily_product_count_summary
        where product_id = :product_id and created_date >= CURDATE() - INTERVAL 7 DAY
        order by created_date asc
    """,
        {"product_id": data["product_id"]},
    )
    data["reading_rate_trends"] = []
    for date in last_week_dates:
        reading_rate = 0
        for info in count_trends:
            if info["date"] == date:
                reading_rate = info["reading_rate"]
                break
        data["reading_rate_trends"].append({"date": date, "reading_rate": reading_rate})

    # 선호작(최근일) = 선호작 추가수 : 선호작 해제수
    # 선호작 추이 = 최근 1주일 기준 선호작 추가수 변화량 & 최근 1주일 기준 선호작 해제수 변화량
    bookmark_trends = await _query(
        """
        select date(created_date) as `date`, count_bookmark, count_unbookmark
        from tb_ptn_product_statistics
        where product_id = :product_id and created_date >= CURDATE() - INTERVAL 7 DAY
    """,
        {"product_id": data["product_id"]},
    )
    data["bookmark_trends"] = []
    for date in last_week_dates:
        count_bookmark = 0
        count_unbookmark = 0
        for info in bookmark_trends:
            if info["date"] == date:
                count_bookmark = info["count_bookmark"]
                count_unbookmark = info["count_unbookmark"]
                break
        data["bookmark_trends"].append(
            {
                "date": date,
                "count_bookmark": count_bookmark,
                "count_unbookmark": count_unbookmark,
            }
        )

    # 관심 유지수(최근일) = 관심 유지수 : 관심 탈락수
    # 관심 유지수 추이 = 최근 1주일 기준 일별 관심 유지수 변화량 & 최근 1주일 기준 일별 관심 탈락수 변화량
    data["interest_trends"] = []
    for date in last_week_dates:
        count_interest_sustain = 0
        count_interest_loss = 0
        for info in count_trends:
            if info["date"] == date:
                count_interest_sustain = info["count_interest_sustain"]
                count_interest_loss = info["count_interest_loss"]
                break
        data["interest_trends"].append(
            {
                "date": date,
                "count_interest_sustain": count_interest_sustain,
                "count_interest_loss": count_interest_loss,
            }
        )

    # 24시간 조회수(초동 조회수) = 첫화 24시간 조회수 : 최신화 24시간 조회수 비교
    # 첫/최신화 24h 조회수를 단일 쿼리로 통합
    first_latest_24h = await _query(
        """
        SELECT
            (
                SELECT b.current_count_hit_in_24h
                FROM tb_batch_daily_product_episode_count_summary b
                WHERE b.product_id = :product_id
                  AND b.episode_no = (SELECT MIN(episode_no) FROM tb_product_episode WHERE product_id = :product_id)
                ORDER BY b.created_date DESC
                LIMIT 1
            ) AS first_count,
            (
                SELECT b.current_count_hit_in_24h
                FROM tb_batch_daily_product_episode_count_summary b
                WHERE b.product_id = :product_id
                  AND b.episode_no = (SELECT MAX(episode_no) FROM tb_product_episode WHERE product_id = :product_id)
                ORDER BY b.created_date DESC
                LIMIT 1
            ) AS latest_count
    """,
        {"product_id": data["product_id"]},
    )
    data["first_episode_count_hit_in_24h"] = (
        first_latest_24h[0]["first_count"]
        if first_latest_24h and first_latest_24h[0]["first_count"] is not None
        else 0
    )
    data["latest_episode_count_hit_in_24h"] = (
        first_latest_24h[0]["latest_count"]
        if first_latest_24h and first_latest_24h[0]["latest_count"] is not None
        else 0
    )

    # 회차별 조회수 = 회차별 통계 > 회차, 조회수
    episode_count_hit_info = await _query(
        """
        select episode_no, episode_title, count_hit
        from tb_product_episode
        where product_id = :product_id
        order by episode_no asc
    """,
        {"product_id": data["product_id"]},
    )
    data["episode_count_hit"] = episode_count_hit_info

    # 타깃독자 분석 = 1순위 독자 & 2순위 독자(%) -> 타깃독자 분석상세에서 첫번째, 두번째
    # 타깃독자 분석상세 = 1순위 ~ 10순위까지 %나열 -> primary_reader_group1, primary_reader_group2 근데 %는 가져올 수가 있나? 이걸 사용하는게 아닌건가? 이거 말고는 뭐가 없는데?
    total_count_reader = await _query(
        """
        select count(*) as total_count from tb_user_product_usage where product_id = :product_id
    """,
        {"product_id": data["product_id"]},
    )
    reader_analysis = await _query(
        """
        select
            case
                when u.gender = 'M' then (
                    case
                        when u.birthdate >= CURDATE() - INTERVAL 10 YEAR then '10대 남성'
                        when u.birthdate >= CURDATE() - INTERVAL 20 YEAR then '20대 남성'
                        when u.birthdate >= CURDATE() - INTERVAL 30 YEAR then '30대 남성'
                        when u.birthdate >= CURDATE() - INTERVAL 40 YEAR then '40대 남성'
                        when u.birthdate >= CURDATE() - INTERVAL 50 YEAR then '50대 남성'
                        else '60대 이상 남성'
                    end
                )
                else (
                    case
                        when u.birthdate >= CURDATE() - INTERVAL 10 YEAR then '10대 여성'
                        when u.birthdate >= CURDATE() - INTERVAL 20 YEAR then '20대 여성'
                        when u.birthdate >= CURDATE() - INTERVAL 30 YEAR then '30대 여성'
                        when u.birthdate >= CURDATE() - INTERVAL 40 YEAR then '40대 여성'
                        when u.birthdate >= CURDATE() - INTERVAL 50 YEAR then '50대 여성'
                        else '60대 이상 여성'
                    end
                )
            end as user_type,
            count(u.user_id) as count_user
        from tb_user_product_usage ups
        inner join tb_user u on u.user_id = ups.user_id
        where ups.product_id = :product_id and u.gender is not null
        group by user_type
        order by count_user desc
    """,
        {"product_id": data["product_id"]},
    )
    total_count = (
        int(total_count_reader[0]["total_count"])
        if total_count_reader[0] and "total_count" in total_count_reader[0]
        else 0
    )
    data["reader_analysis"] = []
    for info in reader_analysis:
        percent = 0
        if total_count > 0:
            percent = (int(info["count_user"]) / total_count) * 100
        data["reader_analysis"].append(
            {"user_type": info["user_type"], "percent": percent}
        )

    # 유사작 추천 = 태그(장르비슷), 비슷한 이용자(내용비슷), 북마크(장바구니)
    similar_info = await _query(
        """
        select type, similar_subject_ids
        from tb_algorithm_recommend_similar
        where product_id = :product_id
    """,
        {"product_id": data["product_id"]},
    )
    # 유사작 추천: 모든 ID를 합쳐 1회 IN 조회 후 타입별 매핑
    all_ids = []
    type_to_ids = {"content": [], "genre": [], "cart": []}
    for info in similar_info:
        try:
            ids = json.loads(info["similar_subject_ids"]) or []
        except Exception:
            ids = []
        type_to_ids.get(info.get("type"), []).extend(ids)
        all_ids.extend(ids)
    id_set = list({int(x) for x in all_ids}) if all_ids else []
    product_map = {}
    if len(id_set) > 0:
        placeholders = ",".join([str(x) for x in id_set])
        products = await _query(f"""
            select product_id, title from tb_product where product_id in ({placeholders})
        """)
        product_map = {
            row["product_id"]: {"product_id": row["product_id"], "title": row["title"]}
            for row in products
        }
    # 타입별 첫 번째만 매핑
    data["similar_product_1"] = None
    data["similar_product_2"] = None
    data["similar_product_3"] = None
    if type_to_ids["content"]:
        for pid in type_to_ids["content"]:
            if pid in product_map:
                data["similar_product_1"] = product_map[pid]
                break
    if type_to_ids["genre"]:
        for pid in type_to_ids["genre"]:
            if pid in product_map:
                data["similar_product_2"] = product_map[pid]
                break
    if type_to_ids["cart"]:
        for pid in type_to_ids["cart"]:
            if pid in product_map:
                data["similar_product_3"] = product_map[pid]
                break

    # 장르 = primary_genre, sub_genre

    return data
