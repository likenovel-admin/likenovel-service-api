import logging
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.const import CommonConstants
from app.exceptions import CustomResponseException
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


async def product_detail_funnel_statistics(
    start_date: str | None,
    end_date: str | None,
    product_id: int | None,
    entry_source: str | None,
    page: int,
    count_per_page: int,
    db: AsyncSession,
    extra_conditions: list[str] | None = None,
    extra_params: dict | None = None,
):
    """
    작품 상세 퍼널 일별 mart 조회
    detail_entry_date - 상세페이지 진입 일시 기준 집계일
    """

    params = dict(extra_params or {})
    where_conditions: list[str] = list(extra_conditions or [])

    if bool(start_date) != bool(end_date):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="start_date와 end_date는 함께 전달해야 합니다.",
        )

    if start_date is not None and end_date is not None:
        try:
            normalized_start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            normalized_end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="날짜 형식이 올바르지 않습니다.",
            )

        if normalized_start_date > normalized_end_date:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="start_date는 end_date보다 늦을 수 없습니다.",
            )

        if (normalized_end_date - normalized_start_date).days > 89:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="조회 기간은 최대 90일까지 선택할 수 있습니다.",
            )

        where_conditions.append("computed_date BETWEEN :start_date AND :end_date")
        params["start_date"] = normalized_start_date.isoformat()
        params["end_date"] = normalized_end_date.isoformat()

    if product_id is not None:
        where_conditions.append("product_id = :product_id")
        params["product_id"] = product_id

    normalized_entry_source = (entry_source or "").strip()
    if normalized_entry_source:
        if normalized_entry_source == "__null__":
            where_conditions.append("entry_source IS NULL")
        else:
            where_conditions.append("entry_source = :entry_source")
            params["entry_source"] = normalized_entry_source

    where_sql = f"WHERE {' AND '.join(where_conditions)}" if where_conditions else ""

    select_sql = f"""
        SELECT
            computed_date AS detail_entry_date,
            product_id,
            entry_source,
            detail_view_raw_count,
            detail_view_session_count,
            detail_view_user_count,
            detail_to_view_session_count,
            detail_to_view_user_count,
            detail_exit_session_count,
            exit_home_session_count,
            exit_search_session_count,
            exit_other_product_detail_session_count,
            exit_other_route_session_count,
            episode_exit_event_count,
            avg_episode_exit_progress_ratio,
            created_date,
            updated_date
        FROM tb_product_detail_funnel_daily
        {where_sql}
        ORDER BY computed_date DESC, product_id ASC, entry_source_norm ASC
    """

    if page == -1 or count_per_page == -1:
        result = await db.execute(text(select_sql), params)
        rows = result.mappings().all()
        return rows

    offset = (page - 1) * count_per_page
    count_query = text(
        f"""
        SELECT COUNT(*) AS total_count
        FROM tb_product_detail_funnel_daily
        {where_sql}
    """
    )
    count_result = await db.execute(count_query, params)
    total_count = dict(count_result.mappings().first())["total_count"]

    paged_query = text(
        select_sql
        + """
        LIMIT :limit OFFSET :offset
    """
    )
    page_params = {**params, "limit": count_per_page, "offset": offset}
    result = await db.execute(paged_query, page_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def product_episode_dropoff_statistics(
    start_date: str | None,
    end_date: str | None,
    product_id: int | None,
    page: int,
    count_per_page: int,
    db: AsyncSession,
    extra_conditions: list[str] | None = None,
    extra_params: dict | None = None,
):
    """
    작품 회차별 읽다 나감 통계 조회
    computed_date는 회차 읽기 시작일 기준으로 집계된 mart를 기간 합산하여 반환한다.
    """

    params = dict(extra_params or {})
    where_conditions: list[str] = list(extra_conditions or [])

    if bool(start_date) != bool(end_date):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="start_date와 end_date는 함께 전달해야 합니다.",
        )

    if start_date is not None and end_date is not None:
        try:
            normalized_start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            normalized_end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="날짜 형식이 올바르지 않습니다.",
            )

        if normalized_start_date > normalized_end_date:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="start_date는 end_date보다 늦을 수 없습니다.",
            )

        if (normalized_end_date - normalized_start_date).days > 89:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="조회 기간은 최대 90일까지 선택할 수 있습니다.",
            )

        where_conditions.append("computed_date BETWEEN :start_date AND :end_date")
        params["start_date"] = normalized_start_date.isoformat()
        params["end_date"] = normalized_end_date.isoformat()

    if product_id is None:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="product_id는 필수입니다.",
        )

    where_conditions.append("product_id = :product_id")
    params["product_id"] = product_id

    where_sql = f"WHERE {' AND '.join(where_conditions)}" if where_conditions else ""

    select_sql = f"""
        SELECT
            product_id,
            episode_id,
            MAX(episode_no) AS episode_no,
            MAX(episode_title) AS episode_title,
            SUM(read_start_count) AS read_start_count,
            SUM(episode_dropoff_count) AS episode_dropoff_count,
            CASE
                WHEN SUM(read_start_count) = 0 THEN 0
                ELSE SUM(episode_dropoff_count) / SUM(read_start_count)
            END AS episode_dropoff_rate,
            CASE
                WHEN SUM(episode_dropoff_count) = 0 THEN NULL
                ELSE SUM(COALESCE(avg_dropoff_progress_ratio, 0) * episode_dropoff_count) / SUM(episode_dropoff_count)
            END AS avg_dropoff_progress_ratio,
            SUM(near_complete_count) AS near_complete_count,
            SUM(dropoff_0_10_count) AS dropoff_0_10_count,
            SUM(dropoff_10_30_count) AS dropoff_10_30_count,
            SUM(dropoff_30_60_count) AS dropoff_30_60_count,
            SUM(dropoff_60_90_count) AS dropoff_60_90_count,
            SUM(dropoff_90_plus_count) AS dropoff_90_plus_count
        FROM tb_product_episode_dropoff_daily
        {where_sql}
        GROUP BY product_id, episode_id
        ORDER BY MAX(episode_no) ASC, episode_id ASC
    """

    if page == -1 or count_per_page == -1:
        result = await db.execute(text(select_sql), params)
        rows = result.mappings().all()
        return rows

    offset = (page - 1) * count_per_page
    count_query = text(
        f"""
        SELECT COUNT(*) AS total_count
        FROM (
            SELECT episode_id
            FROM tb_product_episode_dropoff_daily
            {where_sql}
            GROUP BY product_id, episode_id
        ) t
    """
    )
    count_result = await db.execute(count_query, params)
    total_count = dict(count_result.mappings().first())["total_count"]

    paged_query = text(
        select_sql
        + """
        LIMIT :limit OFFSET :offset
    """
    )
    page_params = {**params, "limit": count_per_page, "offset": offset}
    result = await db.execute(paged_query, page_params)
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

    params = {}
    where_conditions = [
        "so.cancel_yn = 'N'",
        "CAST(so.order_no AS CHAR) LIKE 'OC%'",
    ]

    if search_word != "":
        params["search_word"] = f"%{search_word}%"
        if search_target == "nickname":
            where_conditions.append(
                """
                EXISTS (
                    SELECT 1
                    FROM tb_user_profile up
                    WHERE up.user_id = so.user_id
                      AND up.nickname LIKE :search_word
                )
                """
            )
        elif search_target == CommonConstants.SEARCH_EMAIL:
            where_conditions.append(
                """
                EXISTS (
                    SELECT 1
                    FROM tb_user su
                    WHERE su.user_id = so.user_id
                      AND su.email LIKE :search_word
                )
                """
            )

    if start_date is not None and end_date is not None:
        where_conditions.append("DATE(so.order_date) BETWEEN :start_date AND :end_date")
        params["start_date"] = start_date
        params["end_date"] = end_date

    where_sql = "WHERE " + " AND ".join(where_conditions)

    select_query = f"""
        SELECT
            so.order_date AS `date`,
            so.order_date AS order_datetime,
            CAST(so.order_no AS CHAR) AS order_no,
            so.user_id,
            u.email AS email,
            {get_nickname_sub_query("so.user_id")},
            so.order_id AS cash_order_id,
            1 AS cash_order_count,
            1 AS pay_count,
            so.total_price AS pay_coin,
            so.total_price AS pay_amount,
            0 AS use_coin_count,
            0 AS use_coin,
            0 AS donation_count,
            0 AS donation_coin,
            0 AS ad_revenue
        FROM tb_store_order so
        LEFT JOIN tb_user u ON u.user_id = so.user_id
        {where_sql}
        ORDER BY so.order_date DESC, so.order_id DESC
    """

    if page == -1 or count_per_page == -1:
        query = text(select_query)
        result = await db.execute(query, params)
        rows = result.mappings().all()
        return [dict(row) for row in rows]

    offset = (page - 1) * count_per_page

    count_query = text(
        f"""
        SELECT COUNT(*) as total_count
        FROM tb_store_order so
        {where_sql}
        """
    )
    count_result = await db.execute(count_query, params)
    total_count = dict(count_result.mappings().first())["total_count"]

    query = text(
        select_query
        + """
        LIMIT :limit OFFSET :offset
    """
    )
    page_params = {**params, "limit": count_per_page, "offset": offset}
    result = await db.execute(query, page_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)
