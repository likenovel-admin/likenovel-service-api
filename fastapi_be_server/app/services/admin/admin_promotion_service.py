import logging
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.exceptions import CustomResponseException
import app.schemas.admin as admin_schema

from app.utils.query import get_pagination_params
from app.utils.response import build_paginated_response, check_exists_or_404
from app.const import CommonConstants
from app.const import ErrorMessages


logger = logging.getLogger("admin_app")  # 커스텀 로거 생성

"""
관리자 프로모션/이벤트 관리 서비스 함수 모음
"""


async def direct_promotion_list(
    status: str,
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    직접 프로모션 리스트 조회

    Args:
        status: 프로모션 상태 ('ing', 'stop', 'all')
        search_target: 검색 대상 (제목, 작가명)
        search_word: 검색어
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        직접 프로모션 리스트와 페이징 정보
    """

    if status == "ing":
        where = """
                     AND status = 'ing'
                     """
    elif status == "stop":
        where = """
                     AND status = 'stop'
                     """
    else:
        where = """"""

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where += f"""
                          AND p.title LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_AUTHOR_NAME:
            where += f"""
                          AND p.author_name LIKE '%{search_word}%'
                          """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        SELECT COUNT(*) AS total_count FROM tb_direct_promotion dp INNER JOIN tb_product p ON p.product_id = dp.product_id WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            dp.*,
            p.title,
            p.author_name
        FROM tb_direct_promotion dp
        INNER JOIN tb_product p ON p.product_id = dp.product_id
        WHERE 1=1 {where}
        ORDER BY dp.created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    # 선작 독자 프로모션은 발급 후 항상 중지 상태로 표시
    results = []
    for row in rows:
        row_dict = dict(row)
        if row_dict.get("type") == "reader-of-prev":
            row_dict["status"] = "stop"
        results.append(row_dict)

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "results": results,
    }


async def applied_promotion_list(
    status: str,
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    신청 프로모션 리스트 조회

    Args:
        status: 프로모션 상태 ('ing', 'apply', 'cancel', 'all')
        search_target: 검색 대상 (제목, 작가명)
        search_word: 검색어
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        신청 프로모션 리스트와 페이징 정보
    """

    if status == "ing":
        where = """
                     AND status = 'ing'
                     """
    elif status == "apply":
        where = """
                     AND status = 'apply'
                     """
    elif status == "cancel":
        where = """
                     AND status = 'cancel'
                     """
    else:
        where = """"""

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where += f"""
                          AND p.title LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_AUTHOR_NAME:
            where += f"""
                          AND p.author_name LIKE '%{search_word}%'
                          """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        SELECT COUNT(*) AS total_count FROM tb_applied_promotion ap INNER JOIN tb_product p ON p.product_id = ap.product_id WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            ap.*,
            p.title,
            p.author_name
        FROM tb_applied_promotion ap
        INNER JOIN tb_product p ON p.product_id = ap.product_id
        WHERE 1=1 {where}
        ORDER BY ap.created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def post_applied_promotion(
    req_body: admin_schema.PostAppliedPromotionReqBody, db: AsyncSession
):
    """
    새로운 신청 프로모션 등록

    Args:
        req_body: 등록할 신청 프로모션 정보 (상품 ID, 타입, 시작/종료 날짜)
        db: 데이터베이스 세션

    Returns:
        신청 프로모션 등록 결과
    """

    if req_body is not None:
        logger.info(f"direct_recommend: {req_body}")

    start_date = datetime.strptime(req_body.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(req_body.end_date, "%Y-%m-%d")
    if start_date > end_date:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_RECOMMEND_EXPOSE_START_DATE,
        )

    column_list = []
    value_list = []

    db_execute_params = {"created_id": -1, "created_date": datetime.now()}

    column_list.append("product_id")
    value_list.append(":product_id")
    db_execute_params["product_id"] = req_body.product_id

    column_list.append("type")
    value_list.append(":type")
    db_execute_params["type"] = req_body.type

    column_list.append("status")
    value_list.append(":status")
    db_execute_params["status"] = "apply"

    column_list.append("start_date")
    value_list.append(":start_date")
    db_execute_params["start_date"] = req_body.start_date

    column_list.append("end_date")
    value_list.append(":end_date")
    db_execute_params["end_date"] = req_body.end_date

    column_list.append("num_of_ticket_per_person")
    value_list.append(":num_of_ticket_per_person")
    db_execute_params["num_of_ticket_per_person"] = 1

    columns = ",".join(column_list)
    values = ",".join(value_list)

    query = text(f"""
                        insert into tb_applied_promotion (id, {columns}, created_id, created_date)
                        values (default, {values}, :created_id, :created_date)
                    """)

    await db.execute(query, db_execute_params)

    return {"result": req_body}


async def accept_applied_promotion_accept(
    id: int, req_body: admin_schema.PostAcceptAppliedPromotionReqBody, db: AsyncSession
):
    """
    신청 프로모션 승인 처리

    Args:
        id: 승인할 신청 프로모션 ID
        req_body: 승인 정보 (종료 날짜 등)
        db: 데이터베이스 세션

    Returns:
        신청 프로모션 승인 결과
    """

    query = text("""
                     SELECT * FROM tb_applied_promotion WHERE id = :id
                     """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_REVIEW)

    applied_promotion = dict(rows[0])

    if applied_promotion["status"] == "ing":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_APPROVED_IN_PROGRESS_APPLIED_PROMOTION,
        )

    if applied_promotion["status"] == "cancel":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.WITHDRAWN_APPLIED_PROMOTION,
        )

    if applied_promotion["status"] == "end":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_ENDED_APPLIED_PROMOTION,
        )

    query = text("""
                        update tb_applied_promotion set
                        status = 'ing',
                        end_date = :end_date
                        where id = :id
                    """)

    await db.execute(query, {"id": id, "end_date": req_body.end_date})

    applied_promotion["status"] = "ing"
    return {"result": applied_promotion}


async def deny_applied_promotion_accept(id: int, db: AsyncSession):
    """
    신청 프로모션 반려 처리

    Args:
        id: 반려할 신청 프로모션 ID
        db: 데이터베이스 세션

    Returns:
        신청 프로모션 반려 결과
    """

    query = text("""
                     SELECT * FROM tb_applied_promotion WHERE id = :id
                     """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_REVIEW)

    applied_promotion = dict(rows[0])

    if applied_promotion["status"] == "deny":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_REJECTED_APPLIED_PROMOTION,
        )

    if applied_promotion["status"] == "cancel":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.WITHDRAWN_APPLIED_PROMOTION,
        )

    if applied_promotion["status"] == "end":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_ENDED_APPLIED_PROMOTION,
        )

    query = text("""
                        update tb_applied_promotion set
                        status = 'deny'
                        where id = :id
                    """)

    await db.execute(query, {"id": id})

    applied_promotion["status"] = "deny"
    return {"result": applied_promotion}


async def end_applied_promotion_accept(id: int, db: AsyncSession):
    """
    신청 프로모션 종료 처리

    Args:
        id: 종료할 신청 프로모션 ID
        db: 데이터베이스 세션

    Returns:
        신청 프로모션 종료 결과
    """

    query = text("""
                     SELECT * FROM tb_applied_promotion WHERE id = :id
                     """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_REVIEW)

    applied_promotion = dict(rows[0])

    if applied_promotion["status"] == "deny":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.APPLIED_PROMOTION_REJECTED,
        )

    if applied_promotion["status"] == "cancel":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.WITHDRAWN_APPLIED_PROMOTION,
        )

    if applied_promotion["status"] == "end":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_ENDED_APPLIED_PROMOTION,
        )

    query = text(f"""
                        update tb_applied_promotion set
                        status = 'end'
                        {", end_date = current_timestamp" if applied_promotion["end_date"] is None else ""}
                        where id = :id
                    """)

    await db.execute(query, {"id": id})

    applied_promotion["status"] = "end"
    return {"result": applied_promotion}


async def user_giftbook_list(
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    사용자 선물도서 리스트 조회

    Args:
        search_target: 검색 대상 (이메일)
        search_word: 검색어
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        사용자 선물도서 리스트와 페이징 정보
    """

    if search_word != "":
        if search_target == CommonConstants.SEARCH_EMAIL:
            where = f"""
                          AND u.email LIKE '%{search_word}%'
                          """
        else:
            where = """"""
    else:
        where = """"""

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        SELECT COUNT(u.user_id) AS total_count FROM tb_user u WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            u.user_id,
            u.email,
            (select count(*) from tb_user_giftbook where user_id = u.user_id) AS gift_count,
            (select max(created_date) from tb_user_giftbook where user_id = u.user_id) AS recent_gift_date
        FROM tb_user u
        WHERE 1=1 {where}
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()
    return build_paginated_response(rows, total_count, page, count_per_page)


async def user_giftbook_list_by_user_id(user_id: int, db: AsyncSession):
    """
    사용자 선물도서 내역 조회

    Args:
        user_id: 사용자 ID
        db: 데이터베이스 세션

    Returns:
        사용자 선물도서 내역
    """

    # 받은 내역 조회
    received_history_query = text("""
        select
            ug.reason,
            coalesce(ug.product_id, if(ug.episode_id is not null, (select product_id from tb_product_episode where episode_id = ug.episode_id), null)) as product_id,
            ug.episode_id,
            ug.amount,
            ug.received_date,
            ug.created_date,
            DATE_ADD(ug.created_date, INTERVAL 7 DAY) AS expiration_date,
            p.title as target_product_title,
            p.author_name as target_product_author_name
        from tb_user_giftbook ug
        left join tb_product p on p.product_id = coalesce(ug.product_id, if(ug.episode_id is not null, (select product_id from tb_product_episode where episode_id = ug.episode_id), null))
        where ug.received_yn = 'Y' and ug.user_id = :user_id
        """)
    received_history_result = await db.execute(
        received_history_query, {"user_id": user_id}
    )
    received_history_rows = received_history_result.mappings().all()
    received_history = []
    for received_history_row in received_history_rows:
        received_history_data = dict(received_history_row)

        # product_id가 NULL이면 범용 티켓
        if received_history_data.get("product_id") is None:
            received_history_data["target_product_title"] = "전체 작품"
            received_history_data["target_product_author_name"] = ""

        received_history.append(received_history_data)

    # 사용 내역 조회
    usage_history_query = text("""
        select
            p.title,
            p.author_name,
            up.ticket_type,
            up.use_date
        from tb_user_productbook up
        inner join tb_product p on p.product_id = up.product_id
        where up.use_yn = 'Y' and up.user_id = :user_id
        """)
    usage_history_result = await db.execute(usage_history_query, {"user_id": user_id})
    usage_history_rows = usage_history_result.mappings().all()
    usage_history = [
        dict(usage_history_row) for usage_history_row in usage_history_rows
    ]

    return {"received_history": received_history, "usage_history": usage_history}
