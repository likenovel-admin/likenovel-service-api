import logging
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.exceptions import CustomResponseException
import app.schemas.admin as admin_schema
from app.utils.query import (
    build_insert_query,
    build_update_query,
    get_file_name_sub_query,
    get_file_path_sub_query,
    get_pagination_params,
)
from app.utils.response import (
    build_detail_response,
    build_paginated_response,
    check_exists_or_404,
)
from app.const import CommonConstants
from app.const import ErrorMessages

logger = logging.getLogger("admin_app")

"""
관리자 시스템/키워드 관리 서비스 함수 모음
"""


async def keywords_category_list(db: AsyncSession):
    """
    키워드 카테고리 목록 조회

    Args:
        db: 데이터베이스 세션

    Returns:
        키워드 카테고리 목록
    """

    query = text("""
        SELECT
            *
        FROM tb_standard_keyword_category
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    return [dict(row) for row in rows]


async def keywords_list(
    status: str,
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    키워드 목록 조회

    Args:
        status: 키워드 상태 또는 카테고리 ('all' 또는 카테고리 코드)
        search_target: 검색 대상 ('tag-name')
        search_word: 검색어
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        키워드 목록과 페이징 정보
    """

    if status != "all":
        where = f"""
                 AND kc.category_code = '{status}'
                 """
    else:
        where = """"""

    if search_word != "":
        if search_target == "tag-name":
            where += f"""
                          AND k.keyword_name LIKE '%{search_word}%'
                          """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        SELECT COUNT(*) AS total_count FROM tb_standard_keyword k INNER JOIN tb_standard_keyword_category kc ON kc.category_id = k.category_id WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            k.*,
            kc.category_code,
            (
                (SELECT COUNT(*) FROM tb_mapped_product_keyword WHERE keyword_id = k.keyword_id)
                +
                (SELECT COUNT(*) FROM tb_product_user_keyword WHERE keyword_id = k.keyword_id)
            ) AS use_count
        FROM tb_standard_keyword k
        INNER JOIN tb_standard_keyword_category kc ON kc.category_id = k.category_id
        WHERE 1=1 {where}
        ORDER BY k.created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def post_keywords(req_body: admin_schema.PostKeywordReqBody, db: AsyncSession):
    """
    새로운 키워드 등록

    Args:
        req_body: 등록할 키워드 정보 (키워드명, 카테고리 ID)
        db: 데이터베이스 세션

    Returns:
        키워드 등록 결과
    """

    if req_body is not None:
        logger.info(f"post_keywords: {req_body}")

    query = text("""
                    SELECT * FROM tb_standard_keyword WHERE keyword_name = :keyword_name
                    """)
    result = await db.execute(query, {"keyword_name": req_body.keyword_name})
    rows = result.mappings().all()

    if len(rows) > 0:
        # keyword_name이 중복된게 있음
        raise CustomResponseException(
            status_code=status.HTTP_409_CONFLICT,
            message=ErrorMessages.ALREADY_EXIST_KEYWORD,
        )

    column_list = []
    value_list = []

    db_execute_params = {"created_id": -1, "created_date": datetime.now()}

    column_list.append("keyword_name")
    value_list.append(":keyword_name")
    db_execute_params["keyword_name"] = req_body.keyword_name

    column_list.append("major_genre_yn")
    value_list.append(":major_genre_yn")
    db_execute_params["major_genre_yn"] = CommonConstants.NO

    column_list.append("filter_yn")
    value_list.append(":filter_yn")
    db_execute_params["filter_yn"] = CommonConstants.NO

    column_list.append("category_id")
    value_list.append(":category_id")
    db_execute_params["category_id"] = req_body.category_id

    column_list.append("use_yn")
    value_list.append(":use_yn")
    db_execute_params["use_yn"] = CommonConstants.YES

    columns = ",".join(column_list)
    values = ",".join(value_list)

    query = text(f"""
                        insert into tb_standard_keyword (keyword_id, {columns}, created_id, created_date)
                        values (default, {values}, :created_id, :created_date)
                    """)

    await db.execute(query, db_execute_params)

    return {"result": req_body}


async def put_keywords(
    id: int, req_body: admin_schema.PutKeywordReqBody, db: AsyncSession
):
    """
    키워드 정보 수정

    Args:
        id: 수정할 키워드 ID
        req_body: 수정할 키워드 정보 (키워드명, 카테고리 ID)
        db: 데이터베이스 세션

    Returns:
        키워드 수정 결과
    """
    if req_body is not None:
        logger.info(f"put_keywords: {req_body}")

    query = text("""
                    SELECT * FROM tb_standard_keyword WHERE keyword_id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_KEYWORD)

    set_clause, params = build_update_query(
        req_body, allowed_fields=["keyword_name", "category_id"]
    )
    params["id"] = id

    query = text(f"UPDATE tb_standard_keyword SET {set_clause} WHERE keyword_id = :id")

    await db.execute(query, params)

    return {"result": req_body}


async def delete_keywords(id: int, db: AsyncSession):
    """
    키워드 삭제

    Args:
        id: 삭제할 키워드 ID
        db: 데이터베이스 세션

    Returns:
        키워드 삭제 결과
    """
    query = text("""
                    SELECT * FROM tb_standard_keyword WHERE keyword_id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_KEYWORD)

    query = text("""
                    delete from tb_standard_keyword where keyword_id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}


async def publisher_promotion_list(
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    출판사 프로모션 구좌 목록 조회

    Args:
        search_target: 검색 대상 (제목, 작가명)
        search_word: 검색어
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        출판사 프로모션 구좌 목록과 페이징 정보
    """

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where = text(f"""
                          AND p.title LIKE '%{search_word}%'
                          """)
        elif search_target == CommonConstants.SEARCH_AUTHOR_NAME:
            where = text(f"""
                          AND p.author_name LIKE '%{search_word}%'
                          """)
        else:
            where = text("""""")
    else:
        where = text("""""")

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        SELECT COUNT(*) AS total_count FROM tb_publisher_promotion pp INNER JOIN tb_product p ON p.product_id = pp.product_id WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        with tmp_contract_offer_summary as (
            select z.product_id
                , y.company_name as cp_company_name
            from tb_product_contract_offer z
            inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
            and y.apply_type = 'cp'
            and y.approval_date is not null
            where z.use_yn = 'Y'
            and z.author_accept_yn = 'Y'
        )
        SELECT
            pp.*, p.*
            , d.cp_company_name
        FROM tb_publisher_promotion pp
        INNER JOIN tb_product p ON p.product_id = pp.product_id
        left join tmp_contract_offer_summary d on p.product_id = d.product_id
        WHERE 1=1 {where}
        ORDER BY pp.created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def publisher_promotion_detail_by_id(id: int, db: AsyncSession):
    """
    출판사 프로모션 구좌 상세 정보 조회

    Args:
        id: 조회할 출판사 프로모션 구좌 ID
        db: 데이터베이스 세션

    Returns:
        출판사 프로모션 구좌 상세 정보
    """

    query = text(f"""
        SELECT
            pp.*, p.*
        FROM tb_publisher_promotion pp
        INNER JOIN tb_product p ON p.product_id = pp.product_id
        WHERE pp.id = {id}
        ORDER BY pp.created_date DESC LIMIT 1
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_PROMOTION_SLOT)

    return dict(rows[0])


async def post_publisher_promotion(
    req_body: admin_schema.PostPublisherPromotionReqBody, db: AsyncSession
):
    """
    새로운 출판사 프로모션 구좌 등록

    Args:
        req_body: 등록할 출판사 프로모션 구좌 정보 (상품 ID, 노출 순서)
        db: 데이터베이스 세션

    Returns:
        출판사 프로모션 구좌 등록 결과
    """

    if req_body is not None:
        logger.info(f"post_publisher_promotion: {req_body}")

    query = text("""
                 SELECT * FROM tb_product WHERE product_id = :product_id
                 """)
    result = await db.execute(query, {"product_id": req_body.product_id})
    rows = result.mappings().all()
    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_PRODUCT)

    columns, values, params = build_insert_query(
        req_body, required_fields=["product_id", "show_order"]
    )

    query = text(
        f"INSERT INTO tb_publisher_promotion (id, {columns}, created_id, created_date) VALUES (default, {values}, :created_id, :created_date)"
    )

    await db.execute(query, params)

    return {"result": req_body}


async def put_publisher_promotion(
    id: int, req_body: admin_schema.PutPublisherPromotionReqBody, db: AsyncSession
):
    """
    출판사 프로모션 구좌 정보 수정

    Args:
        id: 수정할 출판사 프로모션 구좌 ID
        req_body: 수정할 출판사 프로모션 구좌 정보 (상품 ID, 노출 순서)
        db: 데이터베이스 세션

    Returns:
        출판사 프로모션 구좌 수정 결과
    """
    if req_body is not None:
        logger.info(f"put_publisher_promotion: {req_body}")

    query = text("""
                    SELECT * FROM tb_publisher_promotion WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_PROMOTION_SLOT)

    if req_body.product_id is not None:
        query = text("""
                     SELECT * FROM tb_product WHERE product_id = :product_id
                     """)
        result = await db.execute(query, {"product_id": req_body.product_id})
        rows = result.mappings().all()
        check_exists_or_404(rows, ErrorMessages.NOT_FOUND_PRODUCT)

    set_clause, params = build_update_query(
        req_body, allowed_fields=["product_id", "show_order"]
    )
    params["id"] = id

    query = text(f"UPDATE tb_publisher_promotion SET {set_clause} WHERE id = :id")

    await db.execute(query, params)

    return {"result": req_body}


async def delete_publisher_promotion(id: int, db: AsyncSession):
    """
    출판사 프로모션 구좌 삭제

    Args:
        id: 삭제할 출판사 프로모션 구좌 ID
        db: 데이터베이스 세션

    Returns:
        출판사 프로모션 구좌 삭제 결과
    """
    query = text("""
                    SELECT * FROM tb_publisher_promotion WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_PROMOTION_SLOT)

    query = text("""
                    delete from tb_publisher_promotion where id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}


async def notices_all(page: int, limit: int, db: AsyncSession):
    """
    공지사항(notice) 목록 조회

    Args:
        page: 페이지 번호
        limit: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        공지사항 목록과 페이징 정보
    """
    query = text(f"""
                 SELECT
                    *
                    , {get_file_path_sub_query("n.file_id", "file_path")}
                    , {get_file_name_sub_query("n.file_id", "file_name")}
                 FROM tb_notice n
                 ORDER BY primary_yn DESC, id DESC
                 LIMIT :limit OFFSET :offset
                 """)
    offset = (page - 1) * limit
    result = await db.execute(query, {"limit": limit, "offset": offset})
    rows = result.mappings().all()

    count_query = text("""
                       SELECT COUNT(*) AS total_count FROM tb_notice
                       """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": limit,
        "data": [dict(row) for row in rows],
    }


async def notice_detail_by_notice_id(notice_id, db: AsyncSession):
    """
    공지사항(notice) 상세 조회

    Args:
        notice_id: 조회할 공지사항 ID
        db: 데이터베이스 세션

    Returns:
        공지사항 상세 정보
    """
    query = text(f"""
                 SELECT
                    *
                    , {get_file_path_sub_query("n.file_id", "file_path")}
                    , {get_file_name_sub_query("n.file_id", "file_name")}
                 FROM tb_notice n WHERE id = :id
                 """)
    result = await db.execute(query, {"id": notice_id})
    row = result.mappings().one_or_none()
    return build_detail_response(row)


async def post_general_notice(
    req_body: admin_schema.PostNoticeReqBody, db: AsyncSession
):
    """
    새로운 일반 공지사항 등록

    Args:
        req_body: 등록할 공지사항 정보 (제목, 내용, 우선순위 여부 등)
        db: 데이터베이스 세션

    Returns:
        공지사항 등록 결과
    """

    if req_body is not None:
        logger.info(f"post_notice: {req_body}")

    column_list = []
    value_list = []

    db_execute_params = {"created_id": -1, "created_date": datetime.now()}

    column_list.append("subject")
    value_list.append(":subject")
    db_execute_params["subject"] = req_body.subject

    column_list.append("content")
    value_list.append(":content")
    db_execute_params["content"] = req_body.content

    column_list.append("primary_yn")
    value_list.append(":primary_yn")
    db_execute_params["primary_yn"] = (
        req_body.primary_yn if req_body.primary_yn is not None else CommonConstants.NO
    )

    if req_body.file_id is not None:
        column_list.append("file_id")
        value_list.append(":file_id")
        db_execute_params["file_id"] = req_body.file_id

    column_list.append("use_yn")
    value_list.append(":use_yn")
    db_execute_params["use_yn"] = CommonConstants.YES

    columns = ",".join(column_list)
    values = ",".join(value_list)

    query = text(f"""
                        insert into tb_notice (id, {columns}, created_id, created_date)
                        values (default, {values}, :created_id, :created_date)
                    """)

    await db.execute(query, db_execute_params)

    return {"result": req_body}


async def put_general_notice(
    id: int, req_body: admin_schema.PutNoticeReqBody, db: AsyncSession
):
    """
    일반 공지사항 수정

    Args:
        id: 수정할 공지사항 ID
        req_body: 수정할 공지사항 정보 (제목, 내용, 우선순위 여부 등)
        db: 데이터베이스 세션

    Returns:
        공지사항 수정 결과
    """

    if req_body is not None:
        logger.info(f"put_product_review: {req_body}")

    set_clause, params = build_update_query(
        req_body, allowed_fields=["subject", "content", "primary_yn", "file_id"]
    )
    params["id"] = id

    query = text(f"UPDATE tb_notice SET {set_clause} WHERE id = :id")

    await db.execute(query, params)

    return {"result": req_body}


async def delete_general_notice(id: int, db: AsyncSession):
    """
    일반 공지사항 삭제

    Args:
        id: 삭제할 공지사항 ID
        db: 데이터베이스 세션

    Returns:
        공지사항 삭제 결과
    """

    query = text("""
                        delete from tb_notice where id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}
