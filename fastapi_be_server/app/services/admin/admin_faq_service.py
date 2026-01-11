import logging
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import CustomResponseException
import app.schemas.admin as admin_schema

from app.utils.query import (
    build_insert_query,
    build_update_query,
    get_pagination_params,
)
from app.utils.response import build_paginated_response, check_exists_or_404
from app.const import ErrorMessages


logger = logging.getLogger("admin_app")  # 커스텀 로거 생성

"""
관리자 FAQ 관리 서비스 함수 모음
"""


async def faq_list(page: int, count_per_page: int, db: AsyncSession):
    """
    공지 / FAQ - FAQ 목록 조회

    Args:
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        FAQ 목록과 페이징 정보
    """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text("""
        SELECT COUNT(*) AS total_count FROM tb_faq
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            *
        FROM tb_faq
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()
    return build_paginated_response(rows, total_count, page, count_per_page)


async def faq_detail_by_id(id: int, db: AsyncSession):
    """
    공지 / FAQ - FAQ 상세 조회

    Args:
        id: 조회할 FAQ ID
        db: 데이터베이스 세션

    Returns:
        FAQ 상세 정보
    """

    query = text(f"""
        SELECT
            *
        FROM tb_faq
        WHERE id = {id}
        ORDER BY created_date DESC LIMIT 1
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()
    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_FAQ)
    return dict(rows[0])


async def post_faq(req_body: admin_schema.PostFAQReqBody, db: AsyncSession):
    """
    새로운 FAQ 등록

    Args:
        req_body: 등록할 FAQ 정보 (제목, 내용)
        db: 데이터베이스 세션

    Returns:
        FAQ 등록 결과
    """

    if req_body is not None:
        logger.info(f"post_faq: {req_body}")

    if len(req_body.subject) == 0:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.FAQ_TITLE_REQUIRED,
        )

    if len(req_body.content) == 0:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.FAQ_CONTENT_REQUIRED,
        )

    columns, values, params = build_insert_query(
        req_body, required_fields=["subject", "content"]
    )

    query = text(
        f"INSERT INTO tb_faq (id, faq_type, {columns}, created_id, created_date) VALUES (default, 'common', {values}, :created_id, :created_date)"
    )

    await db.execute(query, params)

    return {"result": req_body}


async def put_faq(req_body: admin_schema.PutFAQReqBody, id: int, db: AsyncSession):
    """
    FAQ 수정

    Args:
        req_body: 수정할 FAQ 정보 (제목, 내용)
        id: 수정할 FAQ ID
        db: 데이터베이스 세션

    Returns:
        FAQ 수정 결과
    """

    query = text("""
                    SELECT * FROM tb_faq WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_FAQ)

    if len(req_body.subject) == 0:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.FAQ_TITLE_REQUIRED,
        )

    if len(req_body.content) == 0:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.FAQ_CONTENT_REQUIRED,
        )

    set_clause, params = build_update_query(
        req_body, allowed_fields=["subject", "content"]
    )
    params["id"] = id

    query = text(f"UPDATE tb_faq SET {set_clause} WHERE id = :id")

    await db.execute(query, params)

    return {"result": req_body}


async def delete_faq(id: int, db: AsyncSession):
    """
    FAQ 삭제

    Args:
        id: 삭제할 FAQ ID
        db: 데이터베이스 세션

    Returns:
        FAQ 삭제 결과
    """

    query = text("""
                    SELECT * FROM tb_faq WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()
    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_FAQ)

    query = text("""
                    delete from tb_faq where id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}
