import logging
from decimal import Decimal, ROUND_HALF_UP
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.exceptions import CustomResponseException
import app.schemas.partner as partner_schema
from app.utils.query import (
    get_pagination_params,
    build_search_where_clause,
)
from app.utils.response import build_paginated_response, check_exists_or_404
from app.const import CommonConstants
from app.const import ErrorMessages

logger = logging.getLogger("partner_app")  # 커스텀 로거 생성

"""
partner 파트너 매출/정산 관련 서비스 함수 모음
"""


async def monthly_sales_by_product_list(
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
    작품별 월매출 데이터를 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        search_target: 검색 대상 (product-title, product-id, author-name, cp-name)
        search_word: 검색어
        search_start_date: 검색 시작 날짜 (YYYY-MM-DD)
        search_end_date: 검색 종료 날짜 (YYYY-MM-DD)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 작품별 월매출 데이터 목록
    """

    where = """"""
    # JOIN 최적화를 위한 추가 테이블 조인 설정
    additional_joins = ""

    if user_data["role"] == "author":
        additional_joins += """
            INNER JOIN tb_product p ON pps.product_id = p.product_id
        """
        where += f"""
            AND p.author_id = {user_data["user_id"]}
        """
    elif user_data["role"] == "partner":
        additional_joins += """
            INNER JOIN tb_product p ON pps.product_id = p.product_id
        """
        where += f"""
            AND p.product_id IN (
                select z.product_id
                from tb_product_contract_offer z
                inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
                and y.apply_type = 'cp'
                and y.approval_date is not null
                where z.use_yn = 'Y'
                and z.author_accept_yn = 'Y'
                and y.user_id = {user_data["user_id"]}
            )
        """

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            if additional_joins == "":
                additional_joins += """
                    INNER JOIN tb_product p ON pps.product_id = p.product_id
                """
            where += f"""
                          AND p.title LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_PRODUCT_ID:
            if not search_word.isdigit():
                # 숫자가 아닌 경우 에러 처리
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.SEARCH_WORD_MUST_BE_NUMBER,
                )
            where += f"""
                          AND pps.product_id = {search_word}
                          """
        elif search_target == CommonConstants.SEARCH_AUTHOR_NAME:
            where += f"""
                          AND pps.author_nickname LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_CP_NAME:
            additional_joins += """
                INNER JOIN tb_product_contract_offer z ON pps.product_id = z.product_id
                INNER JOIN tb_user_profile_apply y ON z.offer_user_id = y.user_id
            """
            where += f"""
                          AND y.apply_type = 'cp'
                          AND y.approval_date IS NOT NULL
                          AND z.use_yn = 'Y'
                          AND z.author_accept_yn = 'Y'
                          AND y.company_name LIKE '%{search_word}%'
                          """

    if search_start_date != "":
        where += f"""
                      AND DATE(pps.created_date) >= '{search_start_date}'
                      """

    if search_end_date != "":
        where += f"""
                      AND DATE(pps.created_date) <= '{search_end_date}'
                      """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기 - JOIN 최적화 적용
    count_query = text(f"""
        select count(DISTINCT pps.id) as total_count
        from tb_ptn_product_sales pps
        {additional_joins}
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회 - JOIN 최적화 적용
    query = text(f"""
        select DISTINCT pps.*
        from tb_ptn_product_sales pps
        {additional_joins}
        WHERE 1=1 {where}
        ORDER BY pps.created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def monthly_sales_by_product_detail_by_product_id(id: int, db: AsyncSession):
    """
    특정 작품의 월매출 상세 정보를 조회

    Args:
        id: 작품 ID
        db: 데이터베이스 세션

    Returns:
        dict: 해당 작품의 월매출 상세 데이터
    """

    query = text("""
        SELECT
            *
        FROM tb_ptn_product_sales
        WHERE product_id = :product_id
    """)
    result = await db.execute(query, {"product_id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_PRODUCT)

    data = dict(rows[0])

    # Decimal로 변환하여 정확한 금액 계산
    def to_decimal(value):
        """값을 Decimal로 변환. None이면 0 반환"""
        return Decimal(str(value)) if value is not None else Decimal("0")

    def to_int(decimal_value):
        """Decimal을 반올림하여 정수로 변환"""
        return int(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    # 유상 : (일반구매 + 대여권에서 무상 대여권을 제외한 값의 합 - 취소액 - 각각의 결제 수수료) * 정산율
    # 매출이 없으면 수수료도 0으로 처리
    gross_sales_web = (
        to_decimal(data.get("sum_normal_price_web"))
        + to_decimal(data.get("sum_ticket_price_web"))
        - to_decimal(data.get("sum_refund_price_web"))
    )
    fee_web = to_decimal(data.get("fee_web")) if gross_sales_web > 0 else Decimal("0")
    paid_price_web = max(
        Decimal("0"),
        (gross_sales_web - fee_web)
        * (to_decimal(data.get("settlement_rate_web")) / Decimal("100")),
    )

    gross_sales_playstore = (
        to_decimal(data.get("sum_normal_price_playstore"))
        + to_decimal(data.get("sum_ticket_price_playstore"))
        - to_decimal(data.get("sum_refund_price_playstore"))
    )
    fee_playstore = (
        to_decimal(data.get("fee_playstore"))
        if gross_sales_playstore > 0
        else Decimal("0")
    )
    paid_price_playstore = max(
        Decimal("0"),
        (gross_sales_playstore - fee_playstore)
        * (to_decimal(data.get("settlement_rate_playstore")) / Decimal("100")),
    )

    gross_sales_ios = (
        to_decimal(data.get("sum_normal_price_ios"))
        + to_decimal(data.get("sum_ticket_price_ios"))
        - to_decimal(data.get("sum_refund_price_ios"))
    )
    fee_ios = to_decimal(data.get("fee_ios")) if gross_sales_ios > 0 else Decimal("0")
    paid_price_ios = max(
        Decimal("0"),
        (gross_sales_ios - fee_ios)
        * (to_decimal(data.get("settlement_rate_ios")) / Decimal("100")),
    )

    gross_sales_onestore = (
        to_decimal(data.get("sum_normal_price_onestore"))
        + to_decimal(data.get("sum_ticket_price_onestore"))
        - to_decimal(data.get("sum_refund_price_onestore"))
    )
    fee_onestore = (
        to_decimal(data.get("fee_onestore"))
        if gross_sales_onestore > 0
        else Decimal("0")
    )
    paid_price_onestore = max(
        Decimal("0"),
        (gross_sales_onestore - fee_onestore)
        * (to_decimal(data.get("settlement_rate_onestore")) / Decimal("100")),
    )

    paid_price = (
        paid_price_web + paid_price_playstore + paid_price_ios + paid_price_onestore
    )

    # 무상 : 무상 대여권 - 결제 수수료 - 취소액 - 정산율
    # 매출이 없으면 수수료도 0으로 처리
    gross_comped_ticket = to_decimal(data.get("sum_comped_ticket_price")) - to_decimal(
        data.get("sum_refund_comped_ticket_price")
    )
    fee_comped_ticket = (
        to_decimal(data.get("fee_comped_ticket"))
        if gross_comped_ticket > 0
        else Decimal("0")
    )
    free_price = max(
        Decimal("0"),
        (gross_comped_ticket - fee_comped_ticket)
        * (to_decimal(data.get("settlement_rate_comped_ticket")) / Decimal("100")),
    )

    # 전체 : 유상 + 무상
    sum_price = paid_price + free_price

    # 세액 : 기본 = 전체 * 세율(3.3% 고정)
    # 관리자가 파트너 사이트 세액 부분에서 직접 입력 가능(직접 입력했을 시 자동으로 다른 값으로 편집되지 않음)
    tax_rate = (
        to_decimal(data.get("tax_rate")) if data.get("tax_rate") else Decimal("3.3")
    )
    tax_price = max(Decimal("0"), sum_price * (tax_rate / Decimal("100")))

    # 합계 : 전체 - 세액
    total_price = max(Decimal("0"), sum_price - tax_price)

    return {
        "result": data,
        "summary": {
            "paid_price": to_int(paid_price),
            "free_price": to_int(free_price),
            "sum_price": to_int(sum_price),
            "tax_price": to_int(tax_price),
            "total_price": to_int(total_price),
        },
    }


async def put_monthly_sales_by_product(
    req_body: partner_schema.PutPtnProductSalesReqBody,
    product_id: int,
    db: AsyncSession,
):
    """
    작품별 월매출 정보를 업데이트

    Args:
        req_body: 월매출 수정 요청 데이터 (정산액, 정산율, 수수료, 세액 등)
        product_id: 작품 ID
        db: 데이터베이스 세션

    Returns:
        dict: 업데이트된 요청 데이터
    """

    update_filed_query_list = [
        "updated_id = :updated_id",
        "updated_date = :updated_date",
    ]

    db_execute_params = {
        "updated_id": -1,
        "updated_date": datetime.now(),
        "product_id": product_id,
    }

    if (
        req_body.sum_settlement_price_web is not None
        and req_body.sum_settlement_comped_ticket_price is not None
        and req_body.tax_price is not None
    ):
        if req_body.sum_settlement_price_web < 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.PAID_AMOUNT_NEGATIVE,
            )

        if req_body.sum_settlement_comped_ticket_price < 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.FREE_AMOUNT_NEGATIVE,
            )

        if req_body.tax_price < 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.TAX_AMOUNT_NEGATIVE,
            )

        update_filed_query_list.append(
            "sum_settlement_price_web = :sum_settlement_price_web"
        )
        db_execute_params["sum_settlement_price_web"] = (
            req_body.sum_settlement_price_web
        )

        update_filed_query_list.append(
            "sum_settlement_comped_ticket_price = :sum_settlement_comped_ticket_price"
        )
        db_execute_params["sum_settlement_comped_ticket_price"] = (
            req_body.sum_settlement_comped_ticket_price
        )

        update_filed_query_list.append("tax_price = :tax_price")
        db_execute_params["tax_price"] = req_body.tax_price

        update_filed_query_list.append("total_price = :total_price")
        db_execute_params["total_price"] = (
            req_body.sum_settlement_price_web
            + req_body.sum_settlement_comped_ticket_price
            - req_body.tax_price
        )
    elif (
        req_body.settlement_rate is not None
        and req_body.fee is not None
        and req_body.tax_price is not None
    ):
        if req_body.settlement_rate < 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.SETTLEMENT_RATE_NEGATIVE,
            )

        if req_body.fee < 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.PAYMENT_FEE_NEGATIVE,
            )

        if req_body.tax_price < 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.TAX_AMOUNT_NEGATIVE,
            )

        update_filed_query_list.append("settlement_rate_web = :settlement_rate")
        update_filed_query_list.append("settlement_rate_playstore = :settlement_rate")
        update_filed_query_list.append("settlement_rate_ios = :settlement_rate")
        update_filed_query_list.append("settlement_rate_onestore = :settlement_rate")
        update_filed_query_list.append(
            "settlement_rate_comped_ticket = :settlement_rate"
        )
        db_execute_params["settlement_rate"] = req_body.settlement_rate

        update_filed_query_list.append("fee_web = :fee")
        update_filed_query_list.append("fee_playstore = :fee")
        update_filed_query_list.append("fee_ios = :fee")
        update_filed_query_list.append("fee_onestore = :fee")
        update_filed_query_list.append("fee_comped_ticket = :fee")
        db_execute_params["fee"] = req_body.fee

        update_filed_query_list.append("tax_price = :tax_price")
        db_execute_params["tax_price"] = req_body.tax_price
    else:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.SETTLEMENT_FIELDS_REQUIRED,
        )

    update_filed_query = ",".join(update_filed_query_list)

    query = text(f"""
                        update tb_ptn_product_sales set
                        {update_filed_query}
                        where product_id = :product_id
                    """)

    await db.execute(query, db_execute_params)

    return {"result": req_body}


async def sales_by_episode_list(
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
    회차별 매출 데이터를 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        search_target: 검색 대상 (product-title, product-id, author-name, cp-name)
        search_word: 검색어
        search_start_date: 검색 시작 날짜 (YYYY-MM-DD)
        search_end_date: 검색 종료 날짜 (YYYY-MM-DD)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 회차별 매출 데이터 목록
    """

    where = """"""
    if user_data["role"] == "author":
        where += f"""
            AND product_id IN (SELECT product_id FROM tb_product WHERE author_id = {user_data["user_id"]})
        """
    elif user_data["role"] == "partner":
        where += f"""
            AND product_id IN (
                select z.product_id
                from tb_product_contract_offer z
                inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
                and y.apply_type = 'cp'
                and y.approval_date is not null
                where z.use_yn = 'Y'
                and z.author_accept_yn = 'Y'
                and y.user_id = {user_data["user_id"]}
            )
        """

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where += f"""
                          AND product_id IN (SELECT product_id FROM tb_product WHERE title LIKE '%{search_word}%')
                          """
        elif search_target == CommonConstants.SEARCH_PRODUCT_ID:
            if not search_word.isdigit():
                # 숫자가 아닌 경우 에러 처리
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.SEARCH_WORD_MUST_BE_NUMBER,
                )
            where += f"""
                          AND product_id = {search_word}
                          """
        elif search_target == CommonConstants.SEARCH_AUTHOR_NAME:
            where += f"""
                          AND author_nickname LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_CP_NAME:
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

    if search_start_date != "":
        where += f"""
                      AND DATE(created_date) >= '{search_start_date}'
                      """

    if search_end_date != "":
        where += f"""
                      AND DATE(created_date) <= '{search_end_date}'
                      """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        select count(*) as total_count
        from tb_ptn_product_episode_sales
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        select *,
            (select episode_title from tb_product_episode where episode_id = s.episode_id) as episode_title
        from tb_ptn_product_episode_sales s
        WHERE 1=1 {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def sales_by_episode_list_by_product_id(
    product_id: int,
    search_target: str,
    search_word: str,
    search_start_date: str,
    search_end_date: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    특정 작품의 회차별 매출 데이터를 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        product_id: 작품 ID
        search_target: 검색 대상
        search_word: 검색어
        search_start_date: 검색 시작 날짜 (YYYY-MM-DD)
        search_end_date: 검색 종료 날짜 (YYYY-MM-DD)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 해당 작품의 회차별 매출 데이터 목록
    """

    where = f"""
                 AND product_id = {product_id}
                 """

    where, params = build_search_where_clause(
        search_word,
        search_target,
        search_start_date,
        search_end_date,
        search_type="partner",
    )

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        select count(*) as total_count
        from tb_ptn_product_episode_sales
        WHERE product_id = {product_id} {where}
    """)
    count_result = await db.execute(count_query, params)
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        select *,
            (select episode_title from tb_product_episode where episode_id = s.episode_id) as episode_title
        from tb_ptn_product_episode_sales s
        WHERE product_id = {product_id} {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params | params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def daily_ticket_list(
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
    일별 이용권 상세 데이터를 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        search_target: 검색 대상 (product-title, product-id, author-name, cp-name)
        search_word: 검색어
        search_start_date: 검색 시작 날짜 (YYYY-MM-DD)
        search_end_date: 검색 종료 날짜 (YYYY-MM-DD)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 일별 이용권 상세 데이터 목록
    """

    where = """"""
    if user_data["role"] == "author":
        where += f"""
            AND product_id IN (SELECT product_id FROM tb_product WHERE author_id = {user_data["user_id"]})
        """
    elif user_data["role"] == "partner":
        where += f"""
            AND product_id IN (
                select z.product_id
                from tb_product_contract_offer z
                inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
                and y.apply_type = 'cp'
                and y.approval_date is not null
                where z.use_yn = 'Y'
                and z.author_accept_yn = 'Y'
                and y.user_id = {user_data["user_id"]}
            )
        """

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where += f"""
                          AND product_id IN (SELECT product_id FROM tb_product WHERE title LIKE '%{search_word}%')
                          """
        elif search_target == CommonConstants.SEARCH_PRODUCT_ID:
            if not search_word.isdigit():
                # 숫자가 아닌 경우 에러 처리
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.SEARCH_WORD_MUST_BE_NUMBER,
                )
            where += f"""
                          AND product_id = {search_word}
                          """
        elif search_target == CommonConstants.SEARCH_AUTHOR_NAME:
            where += f"""
                          AND author_nickname LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_CP_NAME:
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

    if search_start_date != "":
        where += f"""
                      AND DATE(created_date) >= '{search_start_date}'
                      """

    if search_end_date != "":
        where += f"""
                      AND DATE(created_date) <= '{search_end_date}'
                      """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        select count(*) as total_count
        from tb_ptn_ticket_usage
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        select *
            , (select publish_regular_yn from tb_product where product_id = ptu.product_id) as publish_regular_yn
        from tb_ptn_ticket_usage ptu
        WHERE 1=1 {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def monthly_settlement_list(
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
    월별 정산 데이터를 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        search_target: 검색 대상 (author-name, cp-name)
        search_word: 검색어
        search_start_date: 검색 시작 날짜 (YYYY-MM-DD)
        search_end_date: 검색 종료 날짜 (YYYY-MM-DD)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 월별 정산 데이터 목록
    """

    where = """"""
    if user_data["role"] == "author":
        where += f"""
            AND product_id IN (SELECT product_id FROM tb_product WHERE author_id = {user_data["user_id"]})
        """
    elif user_data["role"] == "partner":
        where += f"""
            AND product_id IN (
                select z.product_id
                from tb_product_contract_offer z
                inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
                and y.apply_type = 'cp'
                and y.approval_date is not null
                where z.use_yn = 'Y'
                and z.author_accept_yn = 'Y'
                and y.user_id = {user_data["user_id"]}
            )
        """

    if search_word != "":
        if search_target == "author-name":
            where += f"""
                          AND product_id IN (SELECT product_id FROM tb_product WHERE author_name LIKE '%{search_word}%')
                          """
        elif search_target == CommonConstants.SEARCH_CP_NAME:
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

    if search_start_date != "":
        where += f"""
                      AND DATE(created_date) >= '{search_start_date}'
                      """

    if search_end_date != "":
        where += f"""
                      AND DATE(created_date) <= '{search_end_date}'
                      """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        select count(*) as total_count
        from tb_ptn_product_settlement
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        select *,
            (
                select author_name
                from tb_product
                where product_id = pps.product_id
            ) as author_name,
            (
                select y.company_name
                from tb_product_contract_offer z
                inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
                and y.apply_type = 'cp'
                and y.approval_date is not null
                where z.use_yn = 'Y'
                and z.author_accept_yn = 'Y'
                and z.product_id = pps.product_id
            ) as cp_name
        from tb_ptn_product_settlement pps
        WHERE 1=1 {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def product_contract_offer_deduction_list(
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
    선계약금 차감 내역을 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        search_target: 검색 대상 (product-title, product-id, author-name, cp-name)
        search_word: 검색어
        search_start_date: 검색 시작 날짜 (YYYY-MM-DD)
        search_end_date: 검색 종료 날짜 (YYYY-MM-DD)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 선계약금 차감 내역 목록
    """

    where = """"""
    if user_data["role"] == "author":
        where += f"""
            AND product_id IN (SELECT product_id FROM tb_product WHERE author_id = {user_data["user_id"]})
        """
    elif user_data["role"] == "partner":
        where += f"""
            AND product_id IN (
                select z.product_id
                from tb_product_contract_offer z
                inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
                and y.apply_type = 'cp'
                and y.approval_date is not null
                where z.use_yn = 'Y'
                and z.author_accept_yn = 'Y'
                and y.user_id = {user_data["user_id"]}
            )
        """

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where += f"""
                          AND product_id IN (SELECT product_id FROM tb_product WHERE title LIKE '%{search_word}%')
                          """
        elif search_target == CommonConstants.SEARCH_PRODUCT_ID:
            if not search_word.isdigit():
                # 숫자가 아닌 경우 에러 처리
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.SEARCH_WORD_MUST_BE_NUMBER,
                )
            where += f"""
                          AND product_id = {search_word}
                          """
        elif search_target == CommonConstants.SEARCH_AUTHOR_NAME:
            where += f"""
                          AND author_nickname LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_CP_NAME:
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

    if search_start_date != "":
        where += f"""
                      AND DATE(created_date) >= '{search_start_date}'
                      """

    if search_end_date != "":
        where += f"""
                      AND DATE(created_date) <= '{search_end_date}'
                      """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        select count(*) as total_count
        from tb_ptn_product_contract_offer_deduction
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        with tmp_contract_offer_settlement_summary as (
            select z.product_id
                , z.offer_id
            from tb_product_contract_offer z
            where z.use_yn = 'Y'
            and z.author_accept_yn = 'Y'
        )
        select a.*, b.offer_id
        from tb_ptn_product_contract_offer_deduction a
        inner join tmp_contract_offer_settlement_summary b on a.product_id = b.product_id
        WHERE 1=1 {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)
