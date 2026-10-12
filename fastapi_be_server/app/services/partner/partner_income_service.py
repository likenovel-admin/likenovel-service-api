import logging
from datetime import datetime
from html import escape
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import CustomResponseException
from app.utils.query import get_pagination_params
from app.utils.response import build_paginated_response
from app.utils.email import send_email
from app.const import CommonConstants
from app.const import ErrorMessages
from app.const import settings

logger = logging.getLogger("partner_app")  # 커스텀 로거 생성

"""
partner 파트너 수익/후원 관련 서비스 함수 모음
"""


def _cp_owned_product_ids_subquery(user_id: int) -> str:
    return f"""
        SELECT product_id
        FROM tb_product
        WHERE cp_user_id = {user_id}
           OR user_id = {user_id}
    """


def _cp_owned_author_ids_subquery(user_id: int) -> str:
    return f"""
        SELECT DISTINCT author_id
        FROM tb_product
        WHERE cp_user_id = {user_id}
           OR user_id = {user_id}
    """


async def sponsorship_recodes_list(
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
    후원 내역을 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        search_target: 검색 대상 (product-title, product-id, author-name, sponsor-name)
        search_word: 검색어
        search_start_date: 검색 시작 날짜 (YYYY-MM-DD)
        search_end_date: 검색 종료 날짜 (YYYY-MM-DD)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 후원 내역 목록 (정산 상태 포함)
    """

    where = """"""

    if user_data["role"] == "author":
        where += f"""
            AND (
                sr.product_id IN (select product_id from tb_product where author_id = {user_data["user_id"]})
                OR sr.author_id = {user_data["user_id"]}
            )
        """
    elif user_data["role"] == "CP":
        where += f"""
            AND (
                sr.product_id IN (
                    {_cp_owned_product_ids_subquery(user_data["user_id"])}
                )
                OR sr.author_id IN (
                    {_cp_owned_author_ids_subquery(user_data["user_id"])}
                )
            )
        """

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where += f"""
                          AND sr.product_id IN (SELECT product_id FROM tb_product WHERE title LIKE '%{search_word}%')
                          """
        elif search_target == CommonConstants.SEARCH_PRODUCT_ID:
            if not search_word.isdigit():
                # 숫자가 아닌 경우 에러 처리
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.SEARCH_WORD_MUST_BE_NUMBER,
                )
            where += f"""
                          AND sr.product_id = {search_word}
                          """
        elif search_target == CommonConstants.SEARCH_AUTHOR_NAME:
            where += f"""
                          AND sr.author_nickname LIKE '%{search_word}%'
                          """
        elif search_target == "sponsor-name":
            where += f"""
                          AND sr.user_name LIKE '%{search_word}%'
                          """

    if search_start_date != "":
        where += f"""
                      AND DATE(sr.created_date) >= '{search_start_date}'
                      """

    if search_end_date != "":
        where += f"""
                      AND DATE(sr.created_date) <= '{search_end_date}'
                      """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        select count(*) as total_count
        from tb_ptn_sponsorship_recodes sr
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회
    # 정산 상태는 후원 건별로 판정한다. 후원일 다음 날 임시 집계에 들어가고,
    # 그 집계일이 속한 달의 다음 달 1일 월 배치가 정산 행을 만든다.
    query = text(f"""
        select *,
            case
                when sr.product_id = 0 then 'not-in-settlement'
                when exists (
                    select 1
                    from tb_ptn_income_settlement s
                    where s.product_id = sr.product_id
                      and s.item_type = 'sponsorship'
                      and s.created_date >= date_add(last_day(date_add(date(sr.created_date), interval 1 day)), interval 1 day)
                ) then 'completed-settlement'
                else 'uncompleted-settlement'
            end as settlement_status
        from tb_ptn_sponsorship_recodes sr
        WHERE 1=1 {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def settlement_sponsorship_recodes(product_id: int, db: AsyncSession):
    """
    특정 작품의 후원 내역에 대한 정산 처리를 수행
    not_in_settlement 상태에서 호출 시 tb_ptn_sponsorship_recodes에서 직접 후원 데이터를 가져와 정산

    Args:
        product_id: 작품 ID
        db: 데이터베이스 세션

    Returns:
        dict: 정산 처리 결과

    정산 계산 로직:
        - 결제 및 서비스 수수료: 10%
        - 세금: 3.3%
    """

    FEE_RATE = 10  # 결제 및 서비스 수수료 10%
    TAX_RATE = 3.3  # 원천징수세율 3.3%

    # 1. 이미 정산 완료 상태인지 확인
    query = text("""
        SELECT * FROM tb_ptn_income_settlement
        WHERE product_id = :product_id AND item_type = 'sponsorship'
    """)
    result = await db.execute(query, {"product_id": product_id})
    rows = result.mappings().all()
    if len(rows) > 0:
        # 이미 정산 완료 상태
        return {"results": True}

    # 2. 정산 미완료(temp) 상태인지 확인
    query = text("""
        SELECT * FROM tb_ptn_income_settlement_temp_summary
        WHERE product_id = :product_id AND item_type = 'sponsorship'
    """)
    result = await db.execute(query, {"product_id": product_id})
    temp_rows = result.mappings().all()

    # 3. not_in_settlement 상태 (temp에도 없음) - tb_ptn_sponsorship_recodes에서 직접 조회
    if len(temp_rows) == 0:
        # 작품의 author_id 조회
        query = text("""
            SELECT author_id FROM tb_product WHERE product_id = :product_id
        """)
        result = await db.execute(query, {"product_id": product_id})
        product_row = result.mappings().first()
        author_id = product_row["author_id"] if product_row else None

        # 해당 작품의 후원 금액 합계 조회 (작품 후원 + 작가 후원 포함)
        query = text("""
            SELECT COALESCE(SUM(donation_price), 0) as total_donation
            FROM tb_ptn_sponsorship_recodes
            WHERE product_id = :product_id
               OR (author_id = :author_id AND :author_id IS NOT NULL)
        """)
        result = await db.execute(
            query, {"product_id": product_id, "author_id": author_id}
        )
        row = result.mappings().first()
        total_donation = row["total_donation"] if row else 0

        if total_donation == 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.NO_SPONSORSHIP_TO_SETTLE,
            )

        # tb_ptn_income_settlement_temp_summary에 삽입 (웹 후원이므로 device_type='web')
        query = text("""
            INSERT INTO tb_ptn_income_settlement_temp_summary
            (product_id, item_type, device_type, sum_income_price, created_id, updated_id)
            VALUES (:product_id, 'sponsorship', 'web', :sum_income_price, 0, 0)
        """)
        await db.execute(
            query, {"product_id": product_id, "sum_income_price": total_donation}
        )

    # 4. tb_ptn_income_settlement_temp_summary에서 데이터 조회
    query = text("""
        SELECT * FROM tb_ptn_income_settlement_temp_summary
        WHERE product_id = :product_id AND item_type = 'sponsorship'
    """)
    result = await db.execute(query, {"product_id": product_id})
    temp_rows = result.mappings().all()

    if len(temp_rows) == 0:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.SETTLEMENT_DATA_CREATION_FAILED,
        )

    # 5. tb_ptn_income_settlement에 정산 완료 데이터 삽입
    for temp_row in temp_rows:
        sum_income_price = temp_row["sum_income_price"]
        device_type = temp_row["device_type"]

        # 정산 계산
        sum_income_price_exclude_fee = round(
            sum_income_price * (100 - FEE_RATE) / 100, 1
        )
        sum_income_price_final = round(
            sum_income_price_exclude_fee * (100 - TAX_RATE) / 100, 1
        )

        query = text("""
            INSERT INTO tb_ptn_income_settlement
            (product_id, item_type, device_type, sum_income_price, total_fee_rate,
             sum_income_price_exclude_fee, withholding_tax_rate, sum_income_price_final,
             created_id, updated_id)
            VALUES (:product_id, 'sponsorship', :device_type, :sum_income_price, :total_fee_rate,
                    :sum_income_price_exclude_fee, :withholding_tax_rate, :sum_income_price_final,
                    0, 0)
        """)
        await db.execute(
            query,
            {
                "product_id": product_id,
                "device_type": device_type,
                "sum_income_price": sum_income_price,
                "total_fee_rate": FEE_RATE,
                "sum_income_price_exclude_fee": sum_income_price_exclude_fee,
                "withholding_tax_rate": TAX_RATE,
                "sum_income_price_final": sum_income_price_final,
            },
        )

    # 6. 정산 완료 확인
    query = text("""
        SELECT * FROM tb_ptn_income_settlement
        WHERE product_id = :product_id AND item_type = 'sponsorship'
    """)
    result = await db.execute(query, {"product_id": product_id})
    rows = result.mappings().all()
    if len(rows) == 0:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.SETTLEMENT_DATA_CREATION_FAILED,
        )

    # 7. temp 데이터 삭제 (정산 완료 후)
    query = text("""
        DELETE FROM tb_ptn_income_settlement_temp_summary
        WHERE product_id = :product_id AND item_type = 'sponsorship'
    """)
    await db.execute(query, {"product_id": product_id})

    return {"results": True}


def _format_won(value) -> str:
    return f"{int(round(float(value or 0))):,}원"


async def request_sponsorship_settlement(req_body, db: AsyncSession, user_data: dict):
    """
    작가의 후원금 정산신청을 운영 메일(settings.SUPPORT_EMAIL)로 전달한다.
    CP 계약 작품을 포함해 후원금은 작가에게만 정산하므로 CP 계정은 신청할 수 없다.
    운영자가 메일을 확인한 뒤 신청 계좌로 직접 입금한다.
    계좌 정보는 메일 본문에만 담고 DB나 로그에는 남기지 않는다.
    """
    if user_data["role"] != "author":
        raise CustomResponseException(
            status_code=status.HTTP_403_FORBIDDEN,
            message=ErrorMessages.SPONSORSHIP_SETTLEMENT_REQUEST_FORBIDDEN,
        )
    user_id = int(user_data["user_id"])

    result = await db.execute(
        text("SELECT u.email FROM tb_user u WHERE u.user_id = :user_id"),
        {"user_id": user_id},
    )
    user_row = result.mappings().first()
    account_email = (user_row or {}).get("email") or ""

    result = await db.execute(
        text("""
            SELECT p.product_id
                 , p.title
                 , p.author_name
                 , COALESCE(d.donation_count, 0) AS donation_count
                 , COALESCE(d.total_donation, 0) AS total_donation
                 , COALESCE(s.confirmed_gross, 0) AS confirmed_gross
                 , COALESCE(s.confirmed_final, 0) AS confirmed_final
              FROM tb_product p
              LEFT JOIN (
                    SELECT product_id
                         , COUNT(*) AS donation_count
                         , SUM(donation_price) AS total_donation
                      FROM tb_ptn_sponsorship_recodes
                     GROUP BY product_id
              ) d ON d.product_id = p.product_id
              LEFT JOIN (
                    SELECT product_id
                         , SUM(sum_income_price) AS confirmed_gross
                         , SUM(sum_income_price_final) AS confirmed_final
                      FROM tb_ptn_income_settlement
                     WHERE item_type = 'sponsorship'
                     GROUP BY product_id
              ) s ON s.product_id = p.product_id
             WHERE p.author_id = :user_id
               AND (d.total_donation > 0 OR s.confirmed_final > 0)
             ORDER BY p.product_id
        """),
        {"user_id": user_id},
    )
    products = result.mappings().all()

    total_donation = sum(int(row["total_donation"] or 0) for row in products)
    if total_donation <= 0:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.NO_SPONSORSHIP_TO_SETTLE,
        )
    confirmed_gross = sum(int(row["confirmed_gross"] or 0) for row in products)
    confirmed_final = sum(int(round(float(row["confirmed_final"] or 0))) for row in products)
    pending_gross = max(total_donation - confirmed_gross, 0)

    author_names = sorted({row["author_name"] for row in products if row["author_name"]})
    requester_label = ", ".join(author_names) or f"user_id {user_id}"
    requested_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    product_rows_html = "".join(
        "<tr>"
        f"<td>{int(row['product_id'])}</td>"
        f"<td>{escape(str(row['title'] or ''))}</td>"
        f"<td>{int(row['donation_count'] or 0)}건</td>"
        f"<td>{_format_won(row['total_donation'])}</td>"
        f"<td>{_format_won(row['confirmed_final'])}</td>"
        "</tr>"
        for row in products
    )
    html_body = (
        "<h2>후원금 정산신청</h2>"
        f"<p><strong>신청자:</strong> {escape(requester_label)} (작가, user_id {user_id})</p>"
        f"<p><strong>계정 이메일:</strong> {escape(account_email)}</p>"
        f"<p><strong>신청 시각:</strong> {requested_at}</p>"
        "<h3>입금 계좌</h3>"
        f"<p><strong>예금주:</strong> {escape(req_body.account_holder)}</p>"
        f"<p><strong>은행:</strong> {escape(req_body.bank_name)}</p>"
        f"<p><strong>계좌번호:</strong> {escape(req_body.account_number)}</p>"
        "<h3>후원 정산 현황</h3>"
        "<table border='1' cellpadding='6' cellspacing='0'>"
        "<tr><th>작품ID</th><th>작품명</th><th>후원 건수</th><th>후원 총액</th>"
        "<th>확정 정산액</th></tr>"
        f"{product_rows_html}"
        "</table>"
        f"<p><strong>후원 총액:</strong> {_format_won(total_donation)}</p>"
        f"<p><strong>확정 정산액 누적:</strong> {_format_won(confirmed_final)}"
        " (수수료 10%, 원천징수 3.3% 공제 후)</p>"
        f"<p><strong>아직 확정 전 후원액:</strong> {_format_won(pending_gross)}"
        " (다음 달 1일 월 배치에서 확정)</p>"
        "<p>확정 정산액은 누적 금액입니다. 이전 입금분을 확인한 뒤 차액을 입금해 주세요.</p>"
    )
    subject = " ".join(
        f"[라이크노벨 후원금 정산신청] {requester_label} (user_id {user_id})".splitlines()
    )

    try:
        await send_email(settings.SUPPORT_EMAIL, subject, html_body)
    except Exception as exc:
        logger.error(
            f"sponsorshipSettlementRequestMail: user_id={user_id} error={type(exc).__name__}"
        )
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message=ErrorMessages.SPONSORSHIP_SETTLEMENT_REQUEST_MAIL_FAILED,
        )

    return {
        "data": {
            "requested": True,
            "total_donation": total_donation,
            "confirmed_final": confirmed_final,
        }
    }


async def income_recodes_list(
    search_target: str,
    search_word: str,
    search_start_date: str,
    search_end_date: str,
    item_type: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
    user_data: dict,
):
    """
    기타 수익 내역을 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        search_target: 검색 대상 (product-title, product-id, author-name, sponsor-name)
        search_word: 검색어
        search_start_date: 검색 시작 날짜 (YYYY-MM-DD)
        search_end_date: 검색 종료 날짜 (YYYY-MM-DD)
        item_type: 수익 항목 타입
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 기타 수익 내역 목록
    """

    where = """"""
    if user_data["role"] == "author":
        where += f"""
            AND product_id IN (select product_id from tb_product where author_id = {user_data["user_id"]})
        """
    elif user_data["role"] == "CP":
        where += f"""
            AND product_id IN (
                {_cp_owned_product_ids_subquery(user_data["user_id"])}
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
        elif search_target == "sponsor-name":
            where += """"""  # 여기서는 후원자가 누군지 알 수 없음 - 테이블에 후원자를 저장하지 않음

    if search_start_date != "":
        where += f"""
                      AND DATE(created_date) >= '{search_start_date}'
                      """

    if search_end_date != "":
        where += f"""
                      AND DATE(created_date) <= '{search_end_date}'
                      """

    if item_type != "":
        where += f"""
                      AND item_type = '{item_type}'
                      """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        select count(*) as total_count
        from tb_ptn_income_recodes
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        select *,
            (SELECT author_id FROM tb_product WHERE product_id = pir.product_id) as author_id
        from tb_ptn_income_recodes pir
        WHERE 1=1 {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def income_settlement_list(
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
    후원 및 기타 수익에 대한 정산 목록을 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        search_target: 검색 대상 (author-name)
        search_word: 검색어
        search_start_date: 검색 시작 날짜 (YYYY-MM-DD)
        search_end_date: 검색 종료 날짜 (YYYY-MM-DD)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 후원 및 기타 정산 목록
    """

    where = """"""
    sponsorship_where = """"""
    if user_data["role"] == "author":
        where += f"""
            AND product_id IN (select product_id from tb_product where author_id = {user_data["user_id"]})
        """
        sponsorship_where = f"""
            AND (
                product_id = pis.product_id
                OR (sponsor_type = 'author' AND author_nickname IN (select author_name from tb_product where author_id = {user_data["user_id"]} LIMIT 1))
            )
        """
    elif user_data["role"] == "CP":
        where += f"""
            AND product_id IN (
                {_cp_owned_product_ids_subquery(user_data["user_id"])}
            )
        """
        sponsorship_where = f"""
            AND (
                product_id = pis.product_id
                OR (sponsor_type = 'author' AND author_nickname IN (
                    SELECT DISTINCT author_name
                    FROM tb_product
                    WHERE cp_user_id = {user_data["user_id"]}
                       OR user_id = {user_data["user_id"]}
                ))
            )
        """

    if search_word != "":
        if search_target == "author-name":
            where += f"""
                          AND product_id IN (SELECT product_id FROM tb_product WHERE author_name LIKE '%{search_word}%')
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
        from tb_ptn_income_settlement
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        select *,
            (SELECT author_name FROM tb_product WHERE product_id = pis.product_id) as author_name,
            (select sum(donation_price) from tb_ptn_sponsorship_recodes WHERE 1=1 {sponsorship_where}) as sum_donation_price,
            (select sum(sum_income_price) from tb_ptn_income_recodes WHERE product_id = pis.product_id) as sum_etc_income_price,
            0 as enable_settlement,
            0 as settled_price
        from tb_ptn_income_settlement pis
        WHERE 1=1 {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def income_settlement_summary(
    search_month: str, db: AsyncSession, user_data: dict
):
    """
    지정된 월에 대한 후원 및 기타 수익 정산 요약 정보를 조회

    Args:
        search_month: 조회할 월 (YYYY-MM), 빈 값이면 현재 월로 설정
        db: 데이터베이스 세션
        user_data: 사용자 데이터

    Returns:
        dict: 현재 월과 누적 정산 요약 정보 (후원, 광고 수익 등)

    정산 계산 로직:
        - 결제 및 서비스 수수료: 총 후원 금액의 10%
        - 제외 후 금액: 총 금액 - 수수료
        - 세금: 3.3%
        - 최종 정산액: 제외 후 금액 * (1 - 0.033)
    """

    # search_month가 빈 값이면 현재 월로 설정
    if not search_month:
        search_month = datetime.now().strftime("%Y-%m")

    FEE_RATE = 10  # 결제 및 서비스 수수료 10%
    TAX_RATE = 3.3  # 원천징수세율 3.3%

    current_data = {
        "sponsorship": {
            "web": {
                "sum_income_price": 0,
                "total_fee": 0,  # 결제 및 서비스 수수료 실제 금액 (총 후원 금액 x 0.1)
                "sum_income_price_exclude_fee": 0,
                "withholding_tax": 0,  # 세금 실제 금액 (제외 후 금액 x 0.033)
                "sum_income_price_final": 0,
            },
            "ios": {
                "sum_income_price": 0,
                "total_fee": 0,
                "sum_income_price_exclude_fee": 0,
                "withholding_tax": 0,
                "sum_income_price_final": 0,
            },
            "playstore": {
                "sum_income_price": 0,
                "total_fee": 0,
                "sum_income_price_exclude_fee": 0,
                "withholding_tax": 0,
                "sum_income_price_final": 0,
            },
            "onestore": {
                "sum_income_price": 0,
                "total_fee": 0,
                "sum_income_price_exclude_fee": 0,
                "withholding_tax": 0,
                "sum_income_price_final": 0,
            },
        },
        "ad": {
            "sum_income_price": 0,
            "total_fee": 0,
            "sum_income_price_exclude_fee": 0,
            "withholding_tax": 0,
            "sum_income_price_final": 0,
        },
    }

    accumulated_data = {
        "income_sponsorship": 0,
        "income_etc": 0,
        "enable_settlement_price": 0,
        "completed_settlement_price": 0,
    }

    # 후원 조회 조건 (작가/파트너별)
    sponsorship_where = ""
    if user_data["role"] == "author":
        sponsorship_where = """
            AND (
                product_id IN (select product_id from tb_product where author_id = :user_id)
                OR author_id = :user_id
            )
        """
    elif user_data["role"] == "CP":
        sponsorship_where = """
            AND (
                product_id IN (
                    SELECT product_id
                    FROM tb_product
                    WHERE cp_user_id = :user_id
                       OR user_id = :user_id
                )
                OR author_id IN (
                    SELECT DISTINCT author_id
                    FROM tb_product
                    WHERE cp_user_id = :user_id
                       OR user_id = :user_id
                )
            )
        """

    # 해당 월의 후원 금액 조회 (tb_ptn_sponsorship_recodes에서 직접 조회)
    # 웹 후원이므로 모두 일반 후원(web)으로 처리
    query = text(f"""
        SELECT COALESCE(SUM(donation_price), 0) as total_donation
        FROM tb_ptn_sponsorship_recodes
        WHERE DATE_FORMAT(created_date, '%Y-%m') = :search_month
        {sponsorship_where}
    """)
    result = await db.execute(
        query, {"search_month": search_month, "user_id": user_data["user_id"]}
    )
    row = result.mappings().first()
    monthly_sponsorship = float(row["total_donation"]) if row else 0

    # 월별 후원 정산 계산
    if monthly_sponsorship > 0:
        sum_income_price = monthly_sponsorship
        # 결제 및 서비스 수수료 실제 금액 (총 후원 금액 x 0.1)
        total_fee = round(sum_income_price * FEE_RATE / 100, 1)
        sum_income_price_exclude_fee = round(
            sum_income_price * (100 - FEE_RATE) / 100, 1
        )
        # 세금 실제 금액 (제외 후 금액 x 0.033)
        withholding_tax = round(sum_income_price_exclude_fee * TAX_RATE / 100, 1)
        sum_income_price_final = round(
            sum_income_price_exclude_fee * (100 - TAX_RATE) / 100, 1
        )

        current_data["sponsorship"]["web"]["sum_income_price"] = sum_income_price
        current_data["sponsorship"]["web"]["total_fee"] = total_fee
        current_data["sponsorship"]["web"]["sum_income_price_exclude_fee"] = (
            sum_income_price_exclude_fee
        )
        current_data["sponsorship"]["web"]["withholding_tax"] = withholding_tax
        current_data["sponsorship"]["web"]["sum_income_price_final"] = (
            sum_income_price_final
        )

    # 전체 누적 후원 금액 조회 (정산 완료 여부와 관계없이 전체)
    query = text(f"""
        SELECT COALESCE(SUM(donation_price), 0) as total_donation
        FROM tb_ptn_sponsorship_recodes
        WHERE 1=1
        {sponsorship_where}
    """)
    result = await db.execute(query, {"user_id": user_data["user_id"]})
    row = result.mappings().first()
    total_sponsorship = float(row["total_donation"]) if row else 0

    # 누적 후원 수익 계산 (최종 정산액 기준)
    if total_sponsorship > 0:
        total_exclude_fee = round(total_sponsorship * (100 - FEE_RATE) / 100, 1)
        total_final = round(total_exclude_fee * (100 - TAX_RATE) / 100, 1)
        accumulated_data["income_sponsorship"] = total_final

    # 정산 완료된 후원 금액 조회 (tb_ptn_income_settlement에서)
    # tb_ptn_income_settlement 테이블에는 author_id 컬럼이 없으므로 product_id 기준으로만 조회
    settlement_where = ""
    if user_data["role"] == "author":
        settlement_where = """
            AND product_id IN (select product_id from tb_product where author_id = :user_id)
        """
    elif user_data["role"] == "CP":
        settlement_where = """
            AND product_id IN (
                SELECT product_id
                FROM tb_product
                WHERE cp_user_id = :user_id
                   OR user_id = :user_id
            )
        """

    query = text(f"""
        SELECT COALESCE(SUM(sum_income_price_final), 0) as completed_amount
        FROM tb_ptn_income_settlement
        WHERE item_type = 'sponsorship'
        {settlement_where}
    """)
    result = await db.execute(query, {"user_id": user_data["user_id"]})
    row = result.mappings().first()
    completed_settlement = float(row["completed_amount"]) if row else 0
    accumulated_data["completed_settlement_price"] = completed_settlement

    # 정산 가능액 = 누적 후원 수익 - 정산 완료액
    accumulated_data["enable_settlement_price"] = (
        accumulated_data["income_sponsorship"]
        - accumulated_data["completed_settlement_price"]
    )

    # 기타 수익(광고 등) - tb_ptn_income_settlement 테이블에는 author_id 컬럼이 없으므로 product_id 기준으로만 조회
    addictive_where = ""
    if user_data["role"] == "author":
        addictive_where = """
            AND product_id IN (select product_id from tb_product where author_id = :user_id)
        """
    elif user_data["role"] == "CP":
        addictive_where = """
            AND product_id IN (
                SELECT product_id
                FROM tb_product
                WHERE cp_user_id = :user_id
                   OR user_id = :user_id
            )
        """

    # 기타 수익 (광고 등) 조회
    query = text(f"""
        SELECT *
        FROM tb_ptn_income_settlement
        WHERE DATE_FORMAT(created_date, '%Y-%m') = :search_month
        AND item_type = 'ad'
        {addictive_where}
        ORDER BY created_date DESC
    """)
    result = await db.execute(
        query, {"search_month": search_month, "user_id": user_data["user_id"]}
    )
    rows = result.mappings().all()

    for row in rows:
        d = dict(row)
        current_data["ad"]["sum_income_price"] += d["sum_income_price"]
        current_data["ad"]["total_fee_rate"] = d["total_fee_rate"]
        current_data["ad"]["sum_income_price_exclude_fee"] += d[
            "sum_income_price_exclude_fee"
        ]
        current_data["ad"]["withholding_tax_rate"] = d["withholding_tax_rate"]
        current_data["ad"]["sum_income_price_final"] += d["sum_income_price_final"]
        accumulated_data["income_etc"] += d["sum_income_price_final"]

    return {
        "current": current_data,
        "accumulated": accumulated_data,
    }
