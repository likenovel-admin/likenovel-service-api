import logging
from fastapi import status
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta

from app.const import CommonConstants, settings
from app.exceptions import CustomResponseException
from app.utils.query import get_nickname_sub_query
from app.utils.response import build_paginated_response

logger = logging.getLogger("statistics_app")  # 커스텀 로거 생성

"""
통계 개별 서비스 함수 모음
"""

AI_READER_MONITOR_TABLES = (
    "tb_ai_reader_agent",
    "tb_ai_reader_daily_schedule",
    "tb_ai_reader_llm_decision",
    "tb_ai_reader_action_queue",
    "tb_ai_reader_public_metric_daily",
)

AI_READER_ENGAGEMENT_SUMMARY_KEYS = (
    "total_agent_count",
    "active_agent_count",
    "paused_agent_count",
    "available_paused_agent_count",
    "scheduled_active_agent_count",
    "idle_active_agent_count",
    "available_idle_active_agent_count",
    "created_agent_count",
    "today_schedule_count",
    "open_schedule_count",
    "failed_schedule_count",
    "decision_count",
    "success_decision_count",
    "failed_decision_count",
    "pending_decision_count",
    "queued_action_count",
    "running_action_count",
    "failed_action_count",
    "skipped_action_count",
    "applied_action_count",
    "ai_view_count",
    "ai_bookmark_count",
    "ai_unbookmark_count",
    "ai_recommend_count",
    "ai_unrecommend_count",
    "ai_evaluation_count",
    "drop_count",
)


def _allowed_ai_reader_account_domains() -> list[str]:
    return [
        domain.strip().lower()
        for domain in settings.AI_READER_ACCOUNT_ALLOWED_DOMAINS.split(",")
        if domain.strip()
    ]


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


async def insert_site_statistics_logs(
    db: AsyncSession,
    types: list[str],
    user_id: int | str | None,
    date: datetime | None = None,
):
    """
    여러 사이트 통계 로그를 한 번의 executemany + commit으로 저장합니다.
    read API에서 visit/page_view를 연속 기록할 때 commit 왕복을 줄이기 위한 helper입니다.
    """
    if user_id is None or not types:
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
    await db.execute(
        query,
        [{"date": date, "type": type, "user_id": user_id} for type in types],
    )
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


async def websochat_usage_statistics(
    start_date: str | None,
    end_date: str | None,
    search_target: str,
    search_word: str,
    product_id: int | None,
    model_used: str,
    route_mode: str,
    fallback_used: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """웹소챗 사용량/비용 운영 대시보드."""
    params: dict[str, object] = {}
    where_conditions: list[str] = []

    if start_date:
        where_conditions.append("DATE(l.created_date) >= :start_date")
        params["start_date"] = start_date
    if end_date:
        where_conditions.append("DATE(l.created_date) <= :end_date")
        params["end_date"] = end_date
    if product_id is not None:
        where_conditions.append("l.product_id = :product_id")
        params["product_id"] = product_id
    if model_used:
        where_conditions.append("l.model_used = :model_used")
        params["model_used"] = model_used
    if route_mode:
        where_conditions.append("l.route_mode = :route_mode")
        params["route_mode"] = route_mode
    if fallback_used in {"Y", "N"}:
        where_conditions.append("l.fallback_used = :fallback_used")
        params["fallback_used"] = fallback_used

    normalized_search_word = str(search_word or "").strip()
    if normalized_search_word:
        params["search_word"] = f"%{normalized_search_word}%"
        if search_target == "email":
            where_conditions.append("u.email LIKE :search_word")
        elif search_target == "nickname":
            where_conditions.append(
                """
                EXISTS (
                    SELECT 1
                    FROM tb_user_profile up
                    WHERE up.user_id = l.user_id
                      AND up.nickname LIKE :search_word
                )
                """
            )
        elif search_target == "product_title":
            where_conditions.append("p.title LIKE :search_word")
        elif search_target == "session_title":
            where_conditions.append("s.title LIKE :search_word")
        else:
            where_conditions.append(
                """
                (
                    u.email LIKE :search_word
                    OR p.title LIKE :search_word
                    OR s.title LIKE :search_word
                    OR EXISTS (
                        SELECT 1
                        FROM tb_user_profile up
                        WHERE up.user_id = l.user_id
                          AND up.nickname LIKE :search_word
                    )
                )
                """
            )

    where_sql = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
    base_from_sql = f"""
        FROM tb_story_agent_usage_log l
        INNER JOIN tb_story_agent_session s ON s.session_id = l.session_id
        LEFT JOIN tb_product p ON p.product_id = l.product_id
        LEFT JOIN tb_user u ON u.user_id = l.user_id
        {where_sql}
    """

    summary_query = text(
        f"""
        SELECT
            COUNT(*) AS total_turn_count,
            COUNT(DISTINCT l.session_id) AS session_count,
            COUNT(DISTINCT l.product_id) AS product_count,
            COUNT(DISTINCT l.user_id) AS user_count,
            COALESCE(SUM(CASE WHEN l.charged_cash > 0 THEN 1 ELSE 0 END), 0) AS charged_turn_count,
            COALESCE(SUM(l.charged_cash), 0) AS charged_cash,
            COALESCE(SUM(CASE WHEN l.fallback_used = 'Y' THEN 1 ELSE 0 END), 0) AS fallback_count
        {base_from_sql}
        """
    )
    summary_result = await db.execute(summary_query, params)
    summary = dict(summary_result.mappings().first() or {})

    model_query = text(
        f"""
        SELECT
            l.model_used,
            COUNT(*) AS turn_count,
            COALESCE(SUM(l.charged_cash), 0) AS charged_cash,
            COALESCE(SUM(CASE WHEN l.fallback_used = 'Y' THEN 1 ELSE 0 END), 0) AS fallback_count
        {base_from_sql}
        GROUP BY l.model_used
        ORDER BY turn_count DESC, charged_cash DESC
        """
    )
    model_result = await db.execute(model_query, params)
    model_summary = [dict(row) for row in model_result.mappings().all()]

    route_query = text(
        f"""
        SELECT
            l.route_mode,
            COUNT(*) AS turn_count,
            COALESCE(SUM(l.charged_cash), 0) AS charged_cash
        {base_from_sql}
        GROUP BY l.route_mode
        ORDER BY turn_count DESC, charged_cash DESC
        LIMIT 20
        """
    )
    route_result = await db.execute(route_query, params)
    route_summary = [dict(row) for row in route_result.mappings().all()]

    product_query = text(
        f"""
        SELECT
            l.product_id,
            COALESCE(p.title, CONCAT('작품 ', l.product_id)) AS product_title,
            COUNT(*) AS turn_count,
            COUNT(DISTINCT l.session_id) AS session_count,
            COALESCE(SUM(l.charged_cash), 0) AS charged_cash
        {base_from_sql}
        GROUP BY l.product_id, p.title
        ORDER BY turn_count DESC, charged_cash DESC
        LIMIT 10
        """
    )
    product_result = await db.execute(product_query, params)
    product_summary = [dict(row) for row in product_result.mappings().all()]

    count_query = text(f"SELECT COUNT(*) AS total_count {base_from_sql}")
    count_result = await db.execute(count_query, params)
    total_count = int(dict(count_result.mappings().first() or {}).get("total_count") or 0)

    detail_query_sql = f"""
        SELECT
            l.usage_log_id,
            l.session_id,
            l.product_id,
            COALESCE(p.title, CONCAT('작품 ', l.product_id)) AS product_title,
            s.title AS session_title,
            l.user_id,
            u.email,
            {get_nickname_sub_query('l.user_id')},
            l.guest_key,
            l.model_used,
            l.route_mode,
            l.intent,
            l.fallback_used,
            l.charged_cash,
            l.created_date
        {base_from_sql}
        ORDER BY l.created_date DESC, l.usage_log_id DESC
    """
    if page != -1 and count_per_page != -1:
        offset = max(page - 1, 0) * count_per_page
        detail_query_sql += " LIMIT :limit OFFSET :offset"
        detail_params = {**params, "limit": count_per_page, "offset": offset}
    else:
        detail_params = params

    detail_result = await db.execute(text(detail_query_sql), detail_params)
    results = [dict(row) for row in detail_result.mappings().all()]

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "summary": summary,
        "model_summary": model_summary,
        "route_summary": route_summary,
        "product_summary": product_summary,
        "results": results,
    }


def _normalize_ai_reader_date_range(
    start_date: str | None,
    end_date: str | None,
) -> tuple[str, str]:
    today = datetime.now().date()
    normalized_start = start_date or today.isoformat()
    normalized_end = end_date or today.isoformat()

    try:
        parsed_start = datetime.strptime(normalized_start, "%Y-%m-%d").date()
        parsed_end = datetime.strptime(normalized_end, "%Y-%m-%d").date()
    except ValueError:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="날짜 형식이 올바르지 않습니다.",
        )

    if parsed_start > parsed_end:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="start_date는 end_date보다 늦을 수 없습니다.",
        )

    if (parsed_end - parsed_start).days > 30:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="AI 유저 인게이지먼트 조회 기간은 최대 31일까지 선택할 수 있습니다.",
        )

    return parsed_start.isoformat(), parsed_end.isoformat()


def _empty_ai_reader_engagement_response(page: int, count_per_page: int) -> dict:
    return {
        "total_count": 0,
        "page": page,
        "count_per_page": count_per_page,
        "summary": {key: 0 for key in AI_READER_ENGAGEMENT_SUMMARY_KEYS},
        "hourly_summary": [],
        "cohort_summary": [],
        "recent_errors": [],
        "recent_actions": [],
        "results": [],
    }


async def _has_ai_reader_monitor_tables(db: AsyncSession) -> bool:
    result = await db.execute(
        text("""
            SELECT COUNT(*) AS table_count
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name IN :table_names
        """).bindparams(bindparam("table_names", expanding=True)),
        {"table_names": AI_READER_MONITOR_TABLES},
    )
    row = dict(result.mappings().first() or {})
    return int(row.get("table_count") or 0) == len(AI_READER_MONITOR_TABLES)


async def _has_ai_reader_action_queue_table(db: AsyncSession) -> bool:
    result = await db.execute(
        text("""
            SELECT COUNT(*) AS table_count
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name = 'tb_ai_reader_action_queue'
        """),
    )
    row = dict(result.mappings().first() or {})
    return int(row.get("table_count") or 0) > 0


async def ai_reader_engagement_statistics(
    start_date: str | None,
    end_date: str | None,
    product_id: int | None,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """AI reader 운영/작품 반응 관제판."""
    normalized_start, normalized_end = _normalize_ai_reader_date_range(
        start_date,
        end_date,
    )
    if not await _has_ai_reader_monitor_tables(db):
        return _empty_ai_reader_engagement_response(page, count_per_page)

    end_exclusive = (
        datetime.strptime(normalized_end, "%Y-%m-%d").date()
        + timedelta(days=1)
    )
    params: dict[str, object] = {
        "start_date": normalized_start,
        "end_date": normalized_end,
        "start_at": f"{normalized_start} 00:00:00",
        "end_exclusive": f"{end_exclusive.isoformat()} 00:00:00",
    }
    action_product_filter = ""
    metric_product_filter = ""
    decision_product_filter = ""
    product_where_filter = ""
    queued_action_product_filter = ""
    evaluation_product_filter = ""
    schedule_error_filter = ""
    if product_id is not None:
        params["product_id"] = product_id
        action_product_filter = "AND product_id = :product_id"
        metric_product_filter = "AND product_id = :product_id"
        decision_product_filter = "AND product_id = :product_id"
        product_where_filter = "AND m.product_id = :product_id"
        queued_action_product_filter = "AND q.product_id = :product_id"
        evaluation_product_filter = "WHERE product_id = :product_id"
        schedule_error_filter = "AND 1 = 0"

    allowed_domains = _allowed_ai_reader_account_domains() or ["__ai_reader_domain_not_configured__"]
    agent_result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS total_agent_count,
                COALESCE(SUM(CASE WHEN a.status = 'active' THEN 1 ELSE 0 END), 0) AS active_agent_count,
                COALESCE(SUM(CASE WHEN a.status = 'paused' THEN 1 ELSE 0 END), 0) AS paused_agent_count,
                COALESCE(SUM(CASE
                    WHEN a.status = 'active'
                     AND EXISTS (
                         SELECT 1
                           FROM tb_ai_reader_daily_schedule s_active
                          WHERE s_active.ai_reader_agent_id = a.ai_reader_agent_id
                            AND s_active.status IN ('ready', 'running')
                            AND s_active.active_end_at > current_timestamp
                     )
                    THEN 1
                    ELSE 0
                END), 0) AS scheduled_active_agent_count,
                COALESCE(SUM(CASE
                    WHEN a.status = 'active'
                     AND NOT EXISTS (
                         SELECT 1
                           FROM tb_ai_reader_daily_schedule s_idle
                          WHERE s_idle.ai_reader_agent_id = a.ai_reader_agent_id
                            AND s_idle.status IN ('ready', 'running')
                            AND s_idle.active_end_at > current_timestamp
                     )
                    THEN 1
                    ELSE 0
                END), 0) AS idle_active_agent_count,
                COALESCE(SUM(CASE
                    WHEN a.status = 'active'
                     AND u.use_yn = 'Y'
                     AND lower(substring_index(u.email, '@', -1)) in :allowed_domains
                     AND NOT EXISTS (
                         SELECT 1
                           FROM tb_user_social us
                          WHERE us.user_id = u.user_id
                     )
                     AND NOT EXISTS (
                         SELECT 1
                           FROM tb_ai_reader_daily_schedule s_available_idle
                          WHERE s_available_idle.ai_reader_agent_id = a.ai_reader_agent_id
                            AND s_available_idle.status IN ('ready', 'running')
                            AND s_available_idle.active_end_at > current_timestamp
                     )
                    THEN 1
                    ELSE 0
                END), 0) AS available_idle_active_agent_count,
                COALESCE(SUM(CASE
                    WHEN a.status = 'paused'
                     AND u.use_yn = 'Y'
                     AND lower(substring_index(u.email, '@', -1)) in :allowed_domains
                     AND NOT EXISTS (
                         SELECT 1
                           FROM tb_user_social us
                          WHERE us.user_id = u.user_id
                     )
                    THEN 1
                    ELSE 0
                END), 0) AS available_paused_agent_count,
                COALESCE(SUM(CASE WHEN a.created_date >= :start_at AND a.created_date < :end_exclusive THEN 1 ELSE 0 END), 0) AS created_agent_count,
                0 AS today_schedule_count,
                0 AS open_schedule_count,
                0 AS failed_schedule_count
            FROM tb_ai_reader_agent a
            LEFT JOIN tb_user u ON u.user_id = a.user_id
        """).bindparams(bindparam("allowed_domains", expanding=True)),
        {**params, "allowed_domains": allowed_domains},
    )
    agent_summary = dict(agent_result.mappings().first() or {})

    schedule_result = await db.execute(
        text("""
            SELECT
                COUNT(*) AS today_schedule_count,
                COALESCE(SUM(CASE WHEN status IN ('ready', 'running') THEN 1 ELSE 0 END), 0) AS open_schedule_count,
                COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_schedule_count
            FROM tb_ai_reader_daily_schedule
            WHERE active_start_at >= :start_at
              AND active_start_at < :end_exclusive
        """),
        params,
    )
    agent_summary.update(dict(schedule_result.mappings().first() or {}))

    decision_result = await db.execute(
        text(f"""
            SELECT
                COALESCE(SUM(CASE
                    WHEN decision_status IN ('success', 'failed')
                     AND created_date >= :start_at
                     AND created_date < :end_exclusive THEN 1
                    WHEN decision_status = 'pending' THEN 1
                    ELSE 0
                END), 0) AS decision_count,
                COALESCE(SUM(CASE
                    WHEN decision_status = 'success'
                     AND created_date >= :start_at
                     AND created_date < :end_exclusive THEN 1
                    ELSE 0
                END), 0) AS success_decision_count,
                COALESCE(SUM(CASE
                    WHEN decision_status = 'failed'
                     AND created_date >= :start_at
                     AND created_date < :end_exclusive THEN 1
                    ELSE 0
                END), 0) AS failed_decision_count,
                COALESCE(SUM(CASE WHEN decision_status = 'pending' THEN 1 ELSE 0 END), 0) AS pending_decision_count
            FROM tb_ai_reader_llm_decision
            WHERE (
                decision_status = 'pending'
                OR (created_date >= :start_at AND created_date < :end_exclusive)
            )
              {decision_product_filter}
        """),
        params,
    )
    decision_summary = dict(decision_result.mappings().first() or {})

    action_result = await db.execute(
        text(f"""
            SELECT
                COALESCE(SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END), 0) AS queued_action_count,
                COALESCE(SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END), 0) AS running_action_count,
                COALESCE(SUM(CASE
                    WHEN status = 'failed'
                     AND updated_date >= :start_at
                     AND updated_date < :end_exclusive THEN 1
                    ELSE 0
                END), 0) AS failed_action_count,
                COALESCE(SUM(CASE
                    WHEN status = 'skipped'
                     AND updated_date >= :start_at
                     AND updated_date < :end_exclusive THEN 1
                    ELSE 0
                END), 0) AS skipped_action_count,
                COALESCE(SUM(CASE
                    WHEN status = 'applied'
                     AND applied_at >= :start_at
                     AND applied_at < :end_exclusive THEN 1
                    ELSE 0
                END), 0) AS applied_action_count
            FROM tb_ai_reader_action_queue
            WHERE (
                status IN ('queued', 'running')
                OR (status = 'failed' AND updated_date >= :start_at AND updated_date < :end_exclusive)
                OR (status = 'skipped' AND updated_date >= :start_at AND updated_date < :end_exclusive)
                OR (status = 'applied' AND applied_at >= :start_at AND applied_at < :end_exclusive)
            )
              {action_product_filter}
        """),
        params,
    )
    action_summary = dict(action_result.mappings().first() or {})

    metric_result = await db.execute(
        text(f"""
            SELECT
                COALESCE(SUM(ai_view_count), 0) AS ai_view_count,
                COALESCE(SUM(ai_bookmark_count), 0) AS ai_bookmark_count,
                COALESCE(SUM(ai_unbookmark_count), 0) AS ai_unbookmark_count,
                COALESCE(SUM(ai_recommend_count), 0) AS ai_recommend_count,
                COALESCE(SUM(ai_unrecommend_count), 0) AS ai_unrecommend_count,
                COALESCE(SUM(ai_evaluation_count), 0) AS ai_evaluation_count
            FROM tb_ai_reader_public_metric_daily
            WHERE stat_date BETWEEN :start_date AND :end_date
              {metric_product_filter}
        """),
        params,
    )
    metric_summary = dict(metric_result.mappings().first() or {})

    drop_result = await db.execute(
        text(f"""
            SELECT COUNT(*) AS drop_count
            FROM tb_ai_reader_action_queue
            WHERE action_type = 'drop'
              AND status = 'applied'
              AND applied_at >= :start_at
              AND applied_at < :end_exclusive
              {action_product_filter}
        """),
        params,
    )
    drop_summary = dict(drop_result.mappings().first() or {})

    product_base_subquery = f"""
                SELECT m.product_id
                FROM tb_ai_reader_public_metric_daily m
                WHERE m.stat_date BETWEEN :start_date AND :end_date
                  {product_where_filter}
                UNION
                SELECT q.product_id
                FROM tb_ai_reader_action_queue q
                WHERE q.status = 'applied'
                  AND q.applied_at >= :start_at
                  AND q.applied_at < :end_exclusive
                  {queued_action_product_filter}
    """

    count_result = await db.execute(
        text(f"""
            SELECT COUNT(*) AS total_count
            FROM (
{product_base_subquery}
            ) z
        """),
        params,
    )
    total_count = int(dict(count_result.mappings().first() or {}).get("total_count") or 0)

    offset = max(page - 1, 0) * count_per_page
    product_result = await db.execute(
        text(f"""
            SELECT
                b.product_id,
                COALESCE(p.title, CONCAT('작품 ', b.product_id)) AS product_title,
                COALESCE(m.ai_view_count, 0) AS ai_view_count,
                COALESCE(m.ai_bookmark_count, 0) AS ai_bookmark_count,
                COALESCE(m.ai_unbookmark_count, 0) AS ai_unbookmark_count,
                COALESCE(m.ai_recommend_count, 0) AS ai_recommend_count,
                COALESCE(m.ai_unrecommend_count, 0) AS ai_unrecommend_count,
                COALESCE(m.ai_evaluation_count, 0) AS ai_evaluation_count,
                COALESCE(a.ai_view_action_count, 0) AS ai_view_action_count,
                COALESCE(a.ai_bookmark_add_action_count, 0) AS ai_bookmark_add_action_count,
                COALESCE(a.ai_bookmark_remove_action_count, 0) AS ai_bookmark_remove_action_count,
                COALESCE(a.ai_bookmark_net_action_count, 0) AS ai_bookmark_net_action_count,
                COALESCE(a.ai_recommend_add_action_count, 0) AS ai_recommend_add_action_count,
                COALESCE(a.ai_recommend_remove_action_count, 0) AS ai_recommend_remove_action_count,
                COALESCE(a.ai_recommend_net_action_count, 0) AS ai_recommend_net_action_count,
                COALESCE(a.ai_evaluation_action_count, 0) AS ai_evaluation_action_count,
                a.last_ai_action_at,
                COALESCE(d.drop_count, 0) AS drop_count,
                COALESCE(p.count_hit, 0) AS public_view_count,
                COALESCE(p.count_bookmark, 0) AS public_bookmark_count,
                COALESCE(p.count_recommend, 0) AS public_recommend_count,
                COALESCE(e.public_evaluation_count, 0) AS public_evaluation_count,
                (
                    COALESCE(m.ai_view_count, 0)
                    + COALESCE(m.ai_recommend_count, 0) * 5
                    + COALESCE(m.ai_bookmark_count, 0) * 4
                    + COALESCE(m.ai_evaluation_count, 0) * 3
                    - COALESCE(d.drop_count, 0) * 2
                ) AS ai_popularity_score
            FROM (
{product_base_subquery}
            ) b
            LEFT JOIN (
                SELECT
                    m.product_id,
                    COALESCE(SUM(m.ai_view_count), 0) AS ai_view_count,
                    COALESCE(SUM(m.ai_bookmark_count), 0) AS ai_bookmark_count,
                    COALESCE(SUM(m.ai_unbookmark_count), 0) AS ai_unbookmark_count,
                    COALESCE(SUM(m.ai_recommend_count), 0) AS ai_recommend_count,
                    COALESCE(SUM(m.ai_unrecommend_count), 0) AS ai_unrecommend_count,
                    COALESCE(SUM(m.ai_evaluation_count), 0) AS ai_evaluation_count
                FROM tb_ai_reader_public_metric_daily m
                WHERE m.stat_date BETWEEN :start_date AND :end_date
                  {product_where_filter}
                GROUP BY m.product_id
            ) m ON m.product_id = b.product_id
            LEFT JOIN (
                SELECT
                    q.product_id,
                    COALESCE(SUM(CASE WHEN q.action_type = 'read' THEN 1 ELSE 0 END), 0) AS ai_view_action_count,
                    COALESCE(SUM(CASE WHEN q.action_type = 'bookmark' AND q.target_value = 'Y' THEN 1 ELSE 0 END), 0) AS ai_bookmark_add_action_count,
                    COALESCE(SUM(CASE WHEN q.action_type = 'bookmark' AND q.target_value = 'N' THEN 1 ELSE 0 END), 0) AS ai_bookmark_remove_action_count,
                    COALESCE(SUM(CASE
                        WHEN q.action_type = 'bookmark' AND q.target_value = 'Y' THEN 1
                        WHEN q.action_type = 'bookmark' AND q.target_value = 'N' THEN -1
                        ELSE 0
                    END), 0) AS ai_bookmark_net_action_count,
                    COALESCE(SUM(CASE WHEN q.action_type = 'recommend' AND q.target_value = 'Y' THEN 1 ELSE 0 END), 0) AS ai_recommend_add_action_count,
                    COALESCE(SUM(CASE WHEN q.action_type = 'recommend' AND q.target_value = 'N' THEN 1 ELSE 0 END), 0) AS ai_recommend_remove_action_count,
                    COALESCE(SUM(CASE
                        WHEN q.action_type = 'recommend' AND q.target_value = 'Y' THEN 1
                        WHEN q.action_type = 'recommend' AND q.target_value = 'N' THEN -1
                        ELSE 0
                    END), 0) AS ai_recommend_net_action_count,
                    COALESCE(SUM(CASE WHEN q.action_type = 'evaluate' THEN 1 ELSE 0 END), 0) AS ai_evaluation_action_count,
                    MAX(q.applied_at) AS last_ai_action_at
                FROM tb_ai_reader_action_queue q
                WHERE q.status = 'applied'
                  AND q.applied_at >= :start_at
                  AND q.applied_at < :end_exclusive
                  {queued_action_product_filter}
                GROUP BY q.product_id
            ) a ON a.product_id = b.product_id
            LEFT JOIN tb_product p ON p.product_id = b.product_id
            LEFT JOIN (
                SELECT product_id, COUNT(*) AS drop_count
                FROM tb_ai_reader_action_queue
                WHERE action_type = 'drop'
                  AND status = 'applied'
                  AND applied_at >= :start_at
                  AND applied_at < :end_exclusive
                  {action_product_filter}
                GROUP BY product_id
            ) d ON d.product_id = b.product_id
            LEFT JOIN (
                SELECT product_id, COUNT(*) AS public_evaluation_count
                FROM tb_product_evaluation
                {evaluation_product_filter}
                GROUP BY product_id
            ) e ON e.product_id = b.product_id
            ORDER BY a.last_ai_action_at DESC, ai_popularity_score DESC, ai_view_action_count DESC, b.product_id DESC
            LIMIT :limit OFFSET :offset
        """),
        {**params, "limit": count_per_page, "offset": offset},
    )
    products = [dict(row) for row in product_result.mappings().all()]

    hourly_result = await db.execute(
        text(f"""
            SELECT
                HOUR(applied_at) AS hour,
                COALESCE(SUM(CASE WHEN action_type = 'read' THEN 1 ELSE 0 END), 0) AS read_count,
                COALESCE(SUM(CASE WHEN action_type = 'bookmark' AND target_value = 'Y' THEN 1 ELSE 0 END), 0) AS bookmark_count,
                COALESCE(SUM(CASE WHEN action_type = 'bookmark' AND target_value = 'N' THEN 1 ELSE 0 END), 0) AS unbookmark_count,
                COALESCE(SUM(CASE WHEN action_type = 'recommend' AND target_value = 'Y' THEN 1 ELSE 0 END), 0) AS recommend_count,
                COALESCE(SUM(CASE WHEN action_type = 'recommend' AND target_value = 'N' THEN 1 ELSE 0 END), 0) AS unrecommend_count,
                COALESCE(SUM(CASE WHEN action_type = 'evaluate' THEN 1 ELSE 0 END), 0) AS evaluation_count,
                COALESCE(SUM(CASE WHEN action_type = 'drop' THEN 1 ELSE 0 END), 0) AS drop_count
            FROM tb_ai_reader_action_queue
            WHERE status = 'applied' AND applied_at >= :start_at
              AND applied_at < :end_exclusive
              {action_product_filter}
            GROUP BY HOUR(applied_at)
            ORDER BY hour ASC
        """),
        params,
    )
    hourly_summary = [dict(row) for row in hourly_result.mappings().all()]

    cohort_result = await db.execute(
        text(f"""
            SELECT
                COALESCE(a.age_group, 'unknown') AS age_group,
                COALESCE(a.gender, 'unknown') AS gender,
                COALESCE(SUM(CASE WHEN q.action_type = 'read' THEN 1 ELSE 0 END), 0) AS read_count,
                COALESCE(SUM(CASE WHEN q.action_type = 'bookmark' AND q.target_value = 'Y' THEN 1 ELSE 0 END), 0) AS bookmark_count,
                COALESCE(SUM(CASE WHEN q.action_type = 'bookmark' AND q.target_value = 'N' THEN 1 ELSE 0 END), 0) AS unbookmark_count,
                COALESCE(SUM(CASE WHEN q.action_type = 'recommend' AND q.target_value = 'Y' THEN 1 ELSE 0 END), 0) AS recommend_count,
                COALESCE(SUM(CASE WHEN q.action_type = 'recommend' AND q.target_value = 'N' THEN 1 ELSE 0 END), 0) AS unrecommend_count,
                COALESCE(SUM(CASE WHEN q.action_type = 'evaluate' THEN 1 ELSE 0 END), 0) AS evaluation_count,
                COALESCE(SUM(CASE WHEN q.action_type = 'drop' THEN 1 ELSE 0 END), 0) AS drop_count
            FROM tb_ai_reader_action_queue q
            INNER JOIN tb_ai_reader_agent a ON a.ai_reader_agent_id = q.ai_reader_agent_id
            WHERE q.status = 'applied'
              AND q.applied_at >= :start_at
              AND q.applied_at < :end_exclusive
              {queued_action_product_filter}
            GROUP BY a.age_group, a.gender
            ORDER BY read_count DESC, recommend_count DESC
            LIMIT 20
        """),
        params,
    )
    cohort_summary = [dict(row) for row in cohort_result.mappings().all()]

    error_result = await db.execute(
        text(f"""
            SELECT *
            FROM (
                SELECT
                    created_date AS event_time,
                    'llm_decision' AS source,
                    ai_reader_agent_id,
                    product_id,
                    NULL AS action_type,
                    model_name,
                    error_message
                FROM tb_ai_reader_llm_decision
                WHERE decision_status = 'failed'
                  AND created_date >= :start_at
                  AND created_date < :end_exclusive
                  {decision_product_filter}
                UNION ALL
                SELECT
                    updated_date AS event_time,
                    'action_queue' AS source,
                    ai_reader_agent_id,
                    product_id,
                    action_type,
                    NULL AS model_name,
                    error_message
                FROM tb_ai_reader_action_queue
                WHERE status = 'failed'
                  AND updated_date >= :start_at
                  AND updated_date < :end_exclusive
                  {action_product_filter}
                UNION ALL
                SELECT
                    updated_date AS event_time,
                    'daily_schedule' AS source,
                    ai_reader_agent_id,
                    NULL AS product_id,
                    NULL AS action_type,
                    NULL AS model_name,
                    error_message
                FROM tb_ai_reader_daily_schedule
                WHERE status = 'failed'
                  AND active_start_at >= :start_at
                  AND active_start_at < :end_exclusive
                  {schedule_error_filter}
            ) errors
            ORDER BY event_time DESC
            LIMIT 20
        """),
        params,
    )
    recent_errors = [dict(row) for row in error_result.mappings().all()]

    recent_actions_result = await db.execute(
        text(f"""
            SELECT
                q.ai_reader_action_id,
                q.ai_reader_agent_id,
                a.agent_key,
                a.age_group,
                a.gender,
                q.product_id,
                p.title AS product_title,
                q.episode_id,
                q.action_type,
                q.target_value,
                q.status,
                q.applied_at,
                q.created_date
            FROM tb_ai_reader_action_queue q
            INNER JOIN tb_ai_reader_agent a ON a.ai_reader_agent_id = q.ai_reader_agent_id
            LEFT JOIN tb_product p ON p.product_id = q.product_id
            WHERE q.status = 'applied'
              AND q.applied_at >= :start_at
              AND q.applied_at < :end_exclusive
              {queued_action_product_filter}
            ORDER BY q.applied_at DESC, q.ai_reader_action_id DESC
            LIMIT 30
        """),
        params,
    )
    recent_actions = [dict(row) for row in recent_actions_result.mappings().all()]

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "summary": {
            **agent_summary,
            **decision_summary,
            **action_summary,
            **metric_summary,
            **drop_summary,
        },
        "hourly_summary": hourly_summary,
        "cohort_summary": cohort_summary,
        "recent_errors": recent_errors,
        "recent_actions": recent_actions,
        "results": products,
    }


async def ai_reader_agent_actions_history(
    agent_id: int,
    start_date: str | None,
    end_date: str | None,
    page: int,
    count_per_page: int,
    db: AsyncSession,
) -> dict:
    normalized_start, normalized_end = _normalize_ai_reader_date_range(start_date, end_date)
    safe_page = max(1, int(page or 1))
    safe_count_per_page = max(1, min(int(count_per_page or 50), 200))
    offset = (safe_page - 1) * safe_count_per_page

    if not await _has_ai_reader_action_queue_table(db):
        return {
            "total_count": 0,
            "page": safe_page,
            "count_per_page": safe_count_per_page,
            "items": [],
        }

    end_exclusive = (
        datetime.strptime(normalized_end, "%Y-%m-%d").date()
        + timedelta(days=1)
    )
    params = {
        "agent_id": int(agent_id),
        "start_at": f"{normalized_start} 00:00:00",
        "end_exclusive": f"{end_exclusive.isoformat()} 00:00:00",
    }

    count_result = await db.execute(
        text(
            """
            SELECT COUNT(*) AS total_count
            FROM tb_ai_reader_action_queue
            WHERE ai_reader_agent_id = :agent_id
              AND created_date >= :start_at
              AND created_date < :end_exclusive
            """
        ),
        params,
    )
    total_count = int(count_result.scalar() or 0)

    if total_count == 0:
        return {
            "total_count": 0,
            "page": safe_page,
            "count_per_page": safe_count_per_page,
            "items": [],
        }

    items_result = await db.execute(
        text(
            """
            SELECT
                ai_reader_action_id,
                ai_reader_agent_id,
                product_id,
                episode_id,
                action_type,
                target_value,
                status,
                applied_at,
                created_date,
                updated_date,
                error_message
            FROM tb_ai_reader_action_queue
            WHERE ai_reader_agent_id = :agent_id
              AND created_date >= :start_at
              AND created_date < :end_exclusive
            ORDER BY created_date DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {**params, "limit": safe_count_per_page, "offset": offset},
    )
    items = [dict(row) for row in items_result.mappings().all()]

    return {
        "total_count": total_count,
        "page": safe_page,
        "count_per_page": safe_count_per_page,
        "items": items,
    }


async def ai_reader_actions_timeline(
    start_date: str | None,
    end_date: str | None,
    page: int,
    count_per_page: int,
    db: AsyncSession,
    status_filter: str | None = None,
) -> dict:
    normalized_start, normalized_end = _normalize_ai_reader_date_range(start_date, end_date)
    safe_page = max(1, int(page or 1))
    safe_count_per_page = max(1, min(int(count_per_page or 50), 200))
    offset = (safe_page - 1) * safe_count_per_page
    normalized_status_filter = (status_filter or "applied").strip().lower()
    status_conditions = {
        "applied": "q.status = 'applied'",
        "pending": "q.status IN ('queued', 'running')",
        "skipped": "q.status = 'skipped'",
        "failed": "q.status = 'failed'",
        "all": "1 = 1",
    }
    if normalized_status_filter not in status_conditions:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="status_filter must be one of applied, pending, skipped, failed, all.",
        )
    status_condition = status_conditions[normalized_status_filter]
    event_time_expr = (
        "q.applied_at"
        if normalized_status_filter == "applied"
        else "COALESCE(q.applied_at, q.updated_date, q.created_date)"
    )

    if not await _has_ai_reader_action_queue_table(db):
        return {
            "total_count": 0,
            "page": safe_page,
            "count_per_page": safe_count_per_page,
            "items": [],
        }

    end_exclusive = (
        datetime.strptime(normalized_end, "%Y-%m-%d").date()
        + timedelta(days=1)
    )
    params = {
        "start_at": f"{normalized_start} 00:00:00",
        "end_exclusive": f"{end_exclusive.isoformat()} 00:00:00",
    }

    count_result = await db.execute(
        text(
            f"""
            SELECT COUNT(*) AS total_count
            FROM tb_ai_reader_action_queue q
            WHERE {status_condition}
              AND {event_time_expr} >= :start_at
              AND {event_time_expr} < :end_exclusive
            """,
        ),
        params,
    )
    total_count = int(count_result.scalar() or 0)

    if total_count == 0:
        return {
            "total_count": 0,
            "page": safe_page,
            "count_per_page": safe_count_per_page,
            "items": [],
        }

    items_result = await db.execute(
        text(
            f"""
            SELECT
                q.ai_reader_action_id,
                q.ai_reader_agent_id,
                a.agent_key,
                a.age_group,
                a.gender,
                q.product_id,
                p.title AS product_title,
                q.episode_id,
                q.action_type,
                q.target_value,
                q.status,
                {event_time_expr} AS event_time,
                q.applied_at,
                q.created_date,
                q.updated_date,
                q.error_message
            FROM tb_ai_reader_action_queue q
            INNER JOIN tb_ai_reader_agent a ON a.ai_reader_agent_id = q.ai_reader_agent_id
            LEFT JOIN tb_product p ON p.product_id = q.product_id
            WHERE {status_condition}
              AND {event_time_expr} >= :start_at
              AND {event_time_expr} < :end_exclusive
            ORDER BY event_time DESC, q.ai_reader_action_id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        {**params, "limit": safe_count_per_page, "offset": offset},
    )
    items = [dict(row) for row in items_result.mappings().all()]

    return {
        "total_count": total_count,
        "page": safe_page,
        "count_per_page": safe_count_per_page,
        "items": items,
    }
