import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.const import CommonConstants
from app.utils.query import get_nickname_sub_query
from app.utils.response import build_paginated_response

logger = logging.getLogger("statistics_app")  # 커스텀 로거 생성

"""
통계 개별 서비스 함수 모음
"""


async def site_statistics(
    start_date: str | None,
    end_date: str | None,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    site 통계
    start_date ~ end_date 사이의 데이터 조회 (페이징 처리)
    date - 날짜
    visitors - 방문자수
    pageView - 페이지뷰 수
    loginCount - 로그인 수
    signinCount - 회원가입 수
    signoffCount - 회원탈퇴 수
    DAU - 하루동안 서비스에 접속한 순수 유저 수
    MAU - 한달동안 서비스에 한번이라도 접속한 순수 유저 수
    """

    if start_date is None or end_date is None:
        where = """"""
    else:
        where = f"""WHERE DATE(`date`) BETWEEN '{start_date}' AND '{end_date}'"""

    if page == -1 or count_per_page == -1:
        query = text(f"""
            SELECT
                `date`,
                visitors,
                page_view,
                login_count,
                (SELECT COUNT(*) FROM tb_user WHERE DATE(created_date) = DATE(tss.`date`)) as signin_count,
                (SELECT COUNT(*) FROM tb_user WHERE DATE(updated_date) = DATE(tss.`date`) AND use_yn = 'N') as signoff_count,
                DAU,
                MAU
            FROM tb_site_statistics tss
            {where}
            ORDER BY `date` DESC
        """)
        result = await db.execute(query, {})
        rows = result.mappings().all()
        return [dict(row) for row in rows]
    offset = (page - 1) * count_per_page

    # 전체 개수 구하기
    count_query = text(f"""
        SELECT COUNT(*) as total_count
        FROM tb_site_statistics
        {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회 (회원가입/탈퇴 수는 서브쿼리)
    query = text(f"""
        SELECT
            `date`,
            visitors,
            page_view,
            login_count,
            (SELECT COUNT(*) FROM tb_user WHERE date(created_date) = tss.`date`) as signin_count,
            (SELECT COUNT(*) FROM tb_user WHERE date(updated_date) = tss.`date` AND use_yn = 'N') as signoff_count,
            DAU,
            MAU
        FROM tb_site_statistics tss
        {where}
        ORDER BY `date` DESC
        LIMIT :limit OFFSET :offset
    """)
    result = await db.execute(query, {"limit": count_per_page, "offset": offset})
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def insert_site_statistics_log(
    db: AsyncSession, type: str, user_id: int | str | None, date: datetime | None = None
):
    """
    사이트 통계 로그를 tb_site_statistics_log에 저장하는 함수
    :param db: AsyncSession
    :param type: 로그 타입(visit, page_view, login, active)
    :param user_id: 유저 아이디
    :param date: 로그 일시(기본값: 현재 시각)
    """
    if user_id is None:
        return
    if isinstance(user_id, str):
        kc_user_id = user_id
        query = text("""
                         SELECT user_id FROM tb_user WHERE kc_user_id = :kc_user_id
                         """)
        result = await db.execute(query, {"kc_user_id": kc_user_id})
        row = result.mappings().one_or_none()
        if row is None:
            return
        user_id = row.get("user_id")
    if date is None:
        date = datetime.now()
    query = text("""
        INSERT INTO tb_site_statistics_log (date, type, user_id, created_date)
        VALUES (:date, :type, :user_id, NOW())
    """)
    await db.execute(query, {"date": date, "type": type, "user_id": user_id})
    await db.commit()


async def payment_statistics(
    start_date: str | None,
    end_date: str | None,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    결제 통계
    start_date ~ end_date 사이의 데이터 조회 (페이징 처리)
    date - 날짜
    pay_count - 결제 횟수
    pay_coin - 결제 코인 수
    pay_amount - 결제 금액
    use_coin_count - 코인 사용 횟수
    use_coin - 코인 사용량
    donation_count - 후원 횟수
    donation_coin - 후원 코인 수
    ad_revenue - 광고 수익
    """

    if start_date is None or end_date is None:
        where = """"""
    else:
        where = f"""WHERE DATE(`date`) BETWEEN '{start_date}' AND '{end_date}'"""

    if page == -1 or count_per_page == -1:
        query = text(f"""
            SELECT
                `date`,
                pay_count,
                pay_coin,
                pay_amount,
                use_coin_count,
                use_coin,
                donation_count,
                donation_coin,
                ad_revenue
            FROM tb_payment_statistics
            {where}
            ORDER BY `date` DESC
        """)
        result = await db.execute(query, {})
        rows = result.mappings().all()
        return [dict(row) for row in rows]
    offset = (page - 1) * count_per_page

    count_query = text(f"""
        SELECT COUNT(*) as total_count
        FROM tb_payment_statistics
        {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    query = text(f"""
        SELECT
            `date`,
            pay_count,
            pay_coin,
            pay_amount,
            use_coin_count,
            use_coin,
            donation_count,
            donation_coin,
            ad_revenue
        FROM tb_payment_statistics
        {where}
        ORDER BY date DESC
        LIMIT :limit OFFSET :offset
    """)
    result = await db.execute(query, {"limit": count_per_page, "offset": offset})
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def insert_payment_statistics_log(
    db: AsyncSession, type: str, user_id: int, amount: int
):
    """
    결제 통계 로그를 tb_payment_statistics_log에 저장하는 함수
    :param db: AsyncSession
    :param type: 로그 타입(pay, use_coin, donation, ad)
    :param user_id: 유저 아이디
    :param amount: 금액 또는 코인 수
    :param date: 로그 일시(기본값: 현재 시각)
    """
    query = text("""
        INSERT INTO tb_payment_statistics_log (date, type, user_id, amount, created_date)
        VALUES (NOW(), :type, :user_id, :amount, NOW())
    """)
    await db.execute(query, {"type": type, "user_id": user_id, "amount": amount})


async def payment_statistics_by_user(
    start_date: str | None,
    end_date: str | None,
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    회원별 결제 통계
    start_date ~ end_date 사이의 데이터 조회 (페이징 처리)
    tb_payment_statistics_log에서 직접 집계
    """

    where = "WHERE 1=1"

    if search_word != "":
        if search_target == "nickname":
            where += f"""
                AND user_id IN (SELECT user_id FROM tb_user_profile WHERE nickname LIKE '%{search_word}%')
            """
        elif search_target == CommonConstants.SEARCH_EMAIL:
            where += f"""
                AND user_id IN (SELECT user_id FROM tb_user WHERE email LIKE '%{search_word}%')
            """

    if start_date is not None and end_date is not None:
        where += f"""
            AND DATE(`date`) BETWEEN '{start_date}' AND '{end_date}'
        """

    if page == -1 or count_per_page == -1:
        query = text(f"""
            SELECT
                DATE(log.date) as `date`,
                log.user_id,
                (SELECT email FROM tb_user WHERE user_id = log.user_id) AS email,
                {get_nickname_sub_query("log.user_id")},
                SUM(CASE WHEN log.type = 'pay' THEN 1 ELSE 0 END) as pay_count,
                SUM(CASE WHEN log.type = 'pay' THEN log.amount ELSE 0 END) as pay_coin,
                SUM(CASE WHEN log.type = 'pay' THEN log.amount ELSE 0 END) as pay_amount,
                SUM(CASE WHEN log.type = 'use_coin' THEN 1 ELSE 0 END) as use_coin_count,
                SUM(CASE WHEN log.type = 'use_coin' THEN log.amount ELSE 0 END) as use_coin,
                SUM(CASE WHEN log.type = 'donation' THEN 1 ELSE 0 END) as donation_count,
                SUM(CASE WHEN log.type = 'donation' THEN log.amount ELSE 0 END) as donation_coin,
                SUM(CASE WHEN log.type = 'ad' THEN log.amount ELSE 0 END) as ad_revenue
            FROM tb_payment_statistics_log log
            {where}
            GROUP BY DATE(log.date), log.user_id
            ORDER BY DATE(log.date) DESC, log.user_id
        """)
        result = await db.execute(query, {})
        rows = result.mappings().all()
        return [dict(row) for row in rows]

    offset = (page - 1) * count_per_page

    count_query = text(f"""
        SELECT COUNT(DISTINCT DATE(date), user_id) as total_count
        FROM tb_payment_statistics_log
        {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    query = text(f"""
        SELECT
            DATE(log.date) as `date`,
            log.user_id,
            (SELECT email FROM tb_user WHERE user_id = log.user_id) AS email,
            {get_nickname_sub_query("log.user_id")},
            SUM(CASE WHEN log.type = 'pay' THEN 1 ELSE 0 END) as pay_count,
            SUM(CASE WHEN log.type = 'pay' THEN log.amount ELSE 0 END) as pay_coin,
            SUM(CASE WHEN log.type = 'pay' THEN log.amount ELSE 0 END) as pay_amount,
            SUM(CASE WHEN log.type = 'use_coin' THEN 1 ELSE 0 END) as use_coin_count,
            SUM(CASE WHEN log.type = 'use_coin' THEN log.amount ELSE 0 END) as use_coin,
            SUM(CASE WHEN log.type = 'donation' THEN 1 ELSE 0 END) as donation_count,
            SUM(CASE WHEN log.type = 'donation' THEN log.amount ELSE 0 END) as donation_coin,
            SUM(CASE WHEN log.type = 'ad' THEN log.amount ELSE 0 END) as ad_revenue
        FROM tb_payment_statistics_log log
        {where}
        GROUP BY DATE(log.date), log.user_id
        ORDER BY DATE(log.date) DESC, log.user_id
        LIMIT :limit OFFSET :offset
    """)
    result = await db.execute(query, {"limit": count_per_page, "offset": offset})
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)
