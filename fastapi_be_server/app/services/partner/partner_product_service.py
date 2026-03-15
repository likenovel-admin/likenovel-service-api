import logging
from typing import Optional
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.exceptions import CustomResponseException
import app.schemas.partner as partner_schema
from app.utils.query import (
    build_update_query,
    get_file_path_sub_query,
    get_pagination_params,
)
from app.utils.response import build_paginated_response, check_exists_or_404
from app.const import CommonConstants
from app.const import ErrorMessages

logger = logging.getLogger("partner_app")  # 커스텀 로거 생성

"""
partner 작품 관리 서비스 함수 모음
"""


async def product_list(
    contract_type: str,
    status_code: str,
    has_episode_apply_yn: str,
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
    user_data: dict,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    from_episode_sales_page: Optional[bool] = None,
):
    """
    작품 관리 / 작품 리스트

    Args:
        contract_type: 계약 유형 (normal: 일반, type: cp)
        status_code: 연재 상태 (ongoing: 연재중, rest: 휴재, end: 완결, stop: 연재중지, '': 전체)
        search_target: 검색 대상 (product-title: 작품명, product-id: 작품ID, author-name: 작가명, cp-name: CP사명)
        search_word: 검색어
        page: 페이지 번호 (1부터 시작)
        count_per_page: 페이지당 개수
        db: 데이터베이스 세션
        user_data: 사용자 정보 딕셔너리
        start_date: 회차별 매출 시작 날짜 (YYYY-MM-DD)
        end_date: 회차별 매출 종료 날짜 (YYYY-MM-DD)
        from_episode_sales_page: 회차별 매출 페이지에서 호출 여부 (True일 때 매출 데이터가 있는 작품만 조회)

    Returns:
        작품 리스트 및 페이징 정보 딕셔너리
    """

    # 날짜 포맷 검증
    start_date_obj = None
    end_date_obj = None

    if start_date:
        try:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.INVALID_START_DATE_FORMAT,
            )

    if end_date:
        try:
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.INVALID_END_DATE_FORMAT,
            )

    # 날짜 범위 검증
    if start_date_obj and end_date_obj and start_date_obj > end_date_obj:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_DATE_RANGE,
        )

    where = """"""
    if user_data["role"] == "author":
        where += f"""
            AND a.author_id = {user_data["user_id"]}
        """
    elif user_data["role"] == "CP":
        where += f"""
            AND (a.user_id = {user_data["user_id"]}
                 OR a.product_id IN (
                    select z.product_id
                    from tb_product_contract_offer z
                    inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
                    and y.apply_type = 'cp'
                    and y.approval_date is not null
                    where z.use_yn = 'Y'
                    and z.author_accept_yn = 'Y'
                    and y.user_id = {user_data["user_id"]}
                ))
        """

    if contract_type == CommonConstants.CONTRACT_NORMAL:
        where += f"""
                     AND d.cp_company_name = '{CommonConstants.COMPANY_LIKENOVEL}'
                     """
    elif contract_type == CommonConstants.CONTRACT_TYPE:
        where += f"""
                     AND d.cp_company_name IS NOT NULL AND d.cp_company_name != '{CommonConstants.COMPANY_LIKENOVEL}'
                     """

    if status_code != "":
        where += f"""
                     AND a.status_code = '{status_code}'
                     """

    if has_episode_apply_yn == "Y":
        where += """
                     AND EXISTS (
                         SELECT 1
                           FROM tb_product_episode pe
                           INNER JOIN tb_product_episode_apply pea
                              ON pea.episode_id = pe.episode_id
                             AND pea.use_yn = 'Y'
                             AND pea.status_code = 'review'
                          WHERE pe.product_id = a.product_id
                            AND pe.use_yn = 'Y'
                     )
                 """

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where += f"""
                          AND a.title LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_PRODUCT_ID:
            if not search_word.isdigit():
                # 숫자가 아닌 경우 에러 처리
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.SEARCH_WORD_MUST_BE_NUMBER,
                )
            where += f"""
                          AND a.product_id = {search_word}
                          """
        elif search_target == CommonConstants.SEARCH_AUTHOR_NAME:
            where += f"""
                          AND a.author_name LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_CP_NAME:
            where += f"""
                          AND a.product_id IN (
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

    sales_summary_cte = ""
    sales_summary_join = ""

    # 회차별 매출 페이지에서 호출 시 매출 데이터 필터링
    if from_episode_sales_page:
        sales_date_condition = ""
        if start_date:
            sales_date_condition += (
                f" AND sales.created_date >= '{start_date} 00:00:00'"
            )
        if end_date:
            sales_date_condition += (
                f" AND sales.created_date < DATE_ADD('{end_date}', INTERVAL 1 DAY)"
            )

        sales_summary_cte = f"""
        ,
        tmp_episode_sales_product_summary as (
            select distinct sales.product_id
            from tb_ptn_product_episode_sales sales
            where 1=1
            {sales_date_condition}
        )
        """
        sales_summary_join = """
        inner join tmp_episode_sales_product_summary eps on eps.product_id = a.product_id
        """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
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
        {sales_summary_cte}
        select count(a.product_id) as total_count
        from tb_product a
        {sales_summary_join}
        left join tmp_contract_offer_summary d on a.product_id = d.product_id
        WHERE 1=1 {where}
        ;
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        with tmp_product_episode_summary as (
            select product_id
                , count(1) as count_episode
            from tb_product_episode
            where use_yn = 'Y'
            group by product_id
        ),
        tmp_contract_offer_summary as (
            select z.product_id
                , MAX(y.company_name) as cp_company_name
            from tb_product_contract_offer z
            inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
            and y.apply_type = 'cp'
            and y.approval_date is not null
            where z.use_yn = 'Y'
            and z.author_accept_yn = 'Y'
            GROUP BY z.product_id
        )
        {sales_summary_cte}
        ,
        filtered_products as (
            select a.product_id
                , a.created_date
            from tb_product a
            {sales_summary_join}
            left join tmp_contract_offer_summary d on a.product_id = d.product_id
            WHERE 1=1 {where}
            ORDER BY a.created_date DESC
            {limit_clause}
        )
        select a.product_id
            , a.title
            , a.author_name as author_nickname
            , a.synopsis_text as synopsis
            , coalesce(b.count_episode, 0) as count_episode
            , case when d.cp_company_name is null then null
                    when d.cp_company_name = '라이크노벨' then '일반'
                    else 'cp'
            end as contract_type
            , d.cp_company_name
            , a.created_date
            , a.paid_open_date
            , a.isbn
            , a.uci
            , a.status_code
            , a.ratings_code
            , a.price_type
            , (select z.keyword_name from tb_standard_keyword z
                where z.use_yn = 'Y'
                and z.major_genre_yn = 'Y'
                and a.primary_genre_id = z.keyword_id) as primary_genre
            , a.primary_genre_id
            , (select z.keyword_name from tb_standard_keyword z
                where z.use_yn = 'Y'
                and z.major_genre_yn = 'Y'
                and a.sub_genre_id = z.keyword_id) as sub_genre
            , a.sub_genre_id
            , a.single_regular_price
            , a.single_rental_price
            , a.series_regular_price
            , a.monopoly_yn
            , {get_file_path_sub_query("a.thumbnail_file_id", "cover_image_path", "cover")}
        from filtered_products fp
        inner join tb_product a on a.product_id = fp.product_id
        left join tmp_product_episode_summary b on a.product_id = b.product_id
        left join tmp_contract_offer_summary d on a.product_id = d.product_id
        ORDER BY fp.created_date DESC
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def product_detail_by_id(id: int, db: AsyncSession, user_data: dict):
    """
    작품 관리 / 작품 리스트

    Args:
        id: 작품 ID
        db: 데이터베이스 세션
        user_data: 사용자 정보 딕셔너리 (user_id, role)

    Returns:
        작품 상세 정보 딕셔너리
    """

    query = text(f"""
        with tmp_product_episode_summary as (
            select product_id
                , count(1) as count_episode
            from tb_product_episode
            where use_yn = 'Y'
            group by product_id
        ),
        tmp_contract_offer_summary as (
            select z.product_id
                , MAX(y.company_name) as cp_company_name
                , MAX(z.author_profit) as cp_author_profit
                , MAX(z.offer_price) as cp_offer_price
            from tb_product_contract_offer z
            inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
            and y.apply_type = 'cp'
            and y.approval_date is not null
            where z.use_yn = 'Y'
            and z.author_accept_yn = 'Y'
            GROUP BY z.product_id
        )
        select a.product_id
            , a.title
            , a.synopsis_text as synopsis
            , a.author_name as author_nickname
            , coalesce(b.count_episode, 0) as count_episode
            , case when d.cp_company_name is null then null
                    when d.cp_company_name = '라이크노벨' then '일반'
                    else 'cp'
            end as contract_type
            , d.cp_company_name
            , a.created_date
            , a.paid_open_date
            , a.isbn
            , a.uci
            , a.status_code
            , a.ratings_code
            , a.price_type
            , (select z.keyword_name from tb_standard_keyword z
                where z.use_yn = 'Y'
                and z.major_genre_yn = 'Y'
                and a.primary_genre_id = z.keyword_id) as primary_genre
            , a.primary_genre_id
            , (select z.keyword_name from tb_standard_keyword z
                where z.use_yn = 'Y'
                and z.major_genre_yn = 'Y'
                and a.sub_genre_id = z.keyword_id) as sub_genre
            , a.sub_genre_id
            , a.single_regular_price
            , a.single_rental_price
            , a.series_regular_price
            , a.paid_episode_no
            , (select min(e.episode_no)
                 from tb_product_episode e
                where e.product_id = a.product_id
                  and e.use_yn = 'Y'
                  and e.price_type = 'free') as free_episode_start_no
            , (select max(e.episode_no)
                 from tb_product_episode e
                where e.product_id = a.product_id
                  and e.use_yn = 'Y'
                  and e.price_type = 'free') as free_episode_end_no
            , a.monopoly_yn
            , a.blind_yn
            , {get_file_path_sub_query("a.thumbnail_file_id", "cover_image_path", "cover")}
            {
        ''', case when d.cp_author_profit is null then null else d.cp_author_profit / 100 end as cp_author_profit
            , d.cp_offer_price as cp_contract_price'''
        if user_data["role"] == "admin"
        else ""
    }
        from tb_product a
        left join tmp_product_episode_summary b on a.product_id = b.product_id
        left join tmp_contract_offer_summary d on a.product_id = d.product_id
        WHERE a.product_id = :product_id
        ORDER BY created_date DESC LIMIT 1
    """)
    result = await db.execute(query, {"product_id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_PRODUCT)

    return dict(rows[0])


async def put_product(
    req_body: partner_schema.PutProductReqBody, product_id: int, db: AsyncSession,
    user_data: dict = None,
):
    """
    작품 수정

    Args:
        req_body: 작품 수정 요청 데이터
        product_id: 작품 ID
        db: 데이터베이스 세션
        user_data: 사용자 정보 (user_id, role)

    Returns:
        수정된 작품 정보 딕셔너리
    """

    # 권한 체크: 작가는 자기 작품만, CP는 계약작품+자기작품만, admin은 전체
    if user_data:
        user_id = user_data["user_id"]
        role = user_data["role"]
        if role == "author":
            check_query = text("""
                SELECT 1 FROM tb_product
                WHERE product_id = :product_id AND author_id = :user_id
            """)
            result = await db.execute(check_query, {"product_id": product_id, "user_id": user_id})
            if result.scalar() is None:
                raise CustomResponseException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message="본인 작품만 수정할 수 있습니다.",
                )
        elif role == "CP":
            check_query = text("""
                SELECT 1 FROM tb_product p
                WHERE p.product_id = :product_id
                  AND (p.author_id = :user_id
                       OR p.user_id = :user_id
                       OR EXISTS (
                           SELECT 1 FROM tb_product_contract_offer co
                           INNER JOIN tb_user_profile_apply upa ON co.offer_user_id = upa.user_id
                             AND upa.apply_type = 'cp' AND upa.approval_date IS NOT NULL
                           WHERE co.product_id = p.product_id
                             AND co.use_yn = 'Y' AND co.author_accept_yn = 'Y'
                             AND co.offer_user_id = :user_id
                       ))
            """)
            result = await db.execute(check_query, {"product_id": product_id, "user_id": user_id})
            if result.scalar() is None:
                raise CustomResponseException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message="본인 작품 또는 계약 작품만 수정할 수 있습니다.",
                )
        # admin은 제한 없음

    if req_body.ratings_code is not None and req_body.ratings_code not in [
        "all",
        "15",
        "adult",
    ]:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=f"허용되지 않은 연령등급입니다. ({req_body.ratings_code})",
        )

    if req_body.status_code not in ["ongoing", "rest", "end", "stop"]:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=f"허용되지 않은 연재 상태입니다. ({req_body.status_code})",
        )

    if req_body.primary_genre_id is not None:
        query = text("""
                    select z.keyword_name from tb_standard_keyword z
                        where z.use_yn = 'Y'
                        and z.major_genre_yn = 'Y'
                        and :primary_genre_id = z.keyword_id
                    """)
        result = await db.execute(
            query, {"primary_genre_id": req_body.primary_genre_id}
        )
        rows = result.mappings().all()
        if len(rows) == 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=f"유효하지 않은 1차 장르입니다. ({req_body.primary_genre_id})",
            )

    if req_body.sub_genre_id is not None:
        query = text("""
                    select z.keyword_name from tb_standard_keyword z
                        where z.use_yn = 'Y'
                        and z.major_genre_yn = 'N'
                        and :sub_genre_id = z.keyword_id
                    """)
        result = await db.execute(query, {"sub_genre_id": req_body.sub_genre_id})
        rows = result.mappings().all()
        if len(rows) == 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=f"유효하지 않은 2차 장르입니다. ({req_body.sub_genre_id})",
            )

    if req_body.primary_genre_id == req_body.sub_genre_id:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.PRIMARY_SECONDARY_GENRE_SAME,
        )

    query = text("""
                SELECT uci, isbn, series_regular_price, single_regular_price, single_rental_price,
                       blind_yn, open_yn
                  FROM tb_product
                 WHERE product_id = :product_id
                 LIMIT 1
                """)
    result = await db.execute(query, {"product_id": product_id})
    product_row = result.mappings().one_or_none()
    if product_row is None:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_PRODUCT,
        )

    incoming_uci = req_body.uci.strip() if isinstance(req_body.uci, str) else None
    incoming_isbn = req_body.isbn.strip() if isinstance(req_body.isbn, str) else None
    current_uci = (product_row.get("uci") or "").strip()
    current_isbn = (product_row.get("isbn") or "").strip()

    next_uci = incoming_uci if req_body.uci is not None else current_uci
    next_isbn = incoming_isbn if req_body.isbn is not None else current_isbn

    current_series_regular_price = int(product_row.get("series_regular_price") or 0)
    current_single_regular_price = int(product_row.get("single_regular_price") or 0)
    current_single_rental_price = int(product_row.get("single_rental_price") or 0)
    current_blind_yn = (product_row.get("blind_yn") or "N").upper()
    current_open_yn = (product_row.get("open_yn") or "N").upper()

    next_series_regular_price = (
        int(req_body.series_regular_price)
        if req_body.series_regular_price is not None
        else current_series_regular_price
    )
    next_single_regular_price = (
        int(req_body.single_regular_price)
        if req_body.single_regular_price is not None
        else current_single_regular_price
    )
    next_single_rental_price = (
        int(req_body.single_rental_price)
        if req_body.single_rental_price is not None
        else current_single_rental_price
    )

    next_price_type = (
        "paid"
        if next_series_regular_price > 0 or next_single_regular_price > 0
        else "free"
    )

    if next_price_type == "paid" and not next_uci and not next_isbn:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.UCI_OR_ISBN_REQUIRED,
        )

    for field_name, value in [
        ("연재 가격", next_series_regular_price),
        ("단행본 소장가격", next_single_regular_price),
        ("단행본 대여가격", next_single_rental_price),
    ]:
        if value < 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=f"{field_name}은(는) 0 이상이어야 합니다.",
            )

    is_next_serial_product = next_series_regular_price > 0
    is_next_volume_product = (
        next_series_regular_price == 0 and next_single_regular_price > 0
    )

    if is_next_serial_product:
        if next_series_regular_price != 100:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="연재 가격은 100원으로 고정됩니다.",
            )
        if next_single_regular_price > 0 or next_single_rental_price > 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="연재 작품에는 단행본 소장/대여 가격을 함께 저장할 수 없습니다.",
            )
    elif is_next_volume_product:
        if next_single_rental_price <= 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="단행본에는 대여가격을 함께 입력해주세요.",
            )
    elif next_single_rental_price > 0:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="단행본 소장가격 없이 대여가격만 저장할 수 없습니다.",
        )

    free_episode_start_no = req_body.free_episode_start_no
    free_episode_end_no = req_body.free_episode_end_no
    fields_set = getattr(req_body, "model_fields_set", set()) or set()
    blind_yn_in_request = "blind_yn" in fields_set
    open_yn_in_request = "open_yn" in fields_set

    if user_data and user_data["role"] != "admin":
        if blind_yn_in_request and req_body.blind_yn != current_blind_yn:
            raise CustomResponseException(
                status_code=status.HTTP_403_FORBIDDEN,
                message="관리자 블라인드는 관리자만 변경할 수 있습니다.",
            )
        if current_blind_yn == "Y" and open_yn_in_request and req_body.open_yn != current_open_yn:
            raise CustomResponseException(
                status_code=status.HTTP_403_FORBIDDEN,
                message="관리자 블라인드된 작품은 공개 상태를 변경할 수 없습니다.",
            )
    has_free_episode_range_input = (
        "free_episode_start_no" in fields_set or "free_episode_end_no" in fields_set
    )
    has_free_episode_range = (
        free_episode_start_no is not None and free_episode_end_no is not None
    )
    clear_free_episode_range = (
        has_free_episode_range_input
        and free_episode_start_no is None
        and free_episode_end_no is None
    )

    if has_free_episode_range_input and not has_free_episode_range and not clear_free_episode_range:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="무료회차 시작/종료 회차를 모두 입력해주세요.",
        )

    if has_free_episode_range:
        if free_episode_start_no is None or free_episode_end_no is None:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="무료회차 시작/종료 회차를 모두 입력해주세요.",
            )
        if (
            free_episode_start_no <= 0
            or free_episode_end_no <= 0
            or free_episode_start_no > 999
            or free_episode_end_no > 999
        ):
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="무료회차 범위는 1~999 사이 숫자만 입력 가능합니다.",
            )
        if free_episode_start_no > free_episode_end_no:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="무료회차 시작 번호는 종료 번호보다 클 수 없습니다.",
            )
        query = text("""
                     select max(episode_no) as max_episode_no
                       from tb_product_episode
                      where product_id = :product_id
                        and use_yn = 'Y'
                     """)
        result = await db.execute(query, {"product_id": product_id})
        row = result.mappings().one_or_none()
        max_episode_no = row.get("max_episode_no") if row else None
        if (
            max_episode_no is not None
            and max_episode_no > 0
            and free_episode_end_no > int(max_episode_no)
        ):
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="무료회차 종료 번호는 현재 등록된 마지막 회차를 초과할 수 없습니다.",
            )

    if req_body.cp_company_name is not None:
        if req_body.cp_offered_price is not None and req_body.cp_offered_price < 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.CP_PROPOSE_AMOUNT_POSITIVE,
            )
        if req_body.cp_settlement_rate is not None and req_body.cp_settlement_rate < 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.CP_WRITER_SETTLEMENT_POSITIVE,
            )
        if (
            req_body.cp_settlement_rate is not None
            and req_body.cp_settlement_rate > 100
        ):
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.CP_WRITER_SETTLEMENT_MAX100,
            )
        query = text("""
                    select id
                        from tb_user_profile_apply
                        where apply_type = 'cp' and company_name = :cp_company_name
                    """)
        result = await db.execute(query, {"cp_company_name": req_body.cp_company_name})
        rows = result.mappings().all()
        if len(rows) == 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=f"유효하지 않은 cp사명입니다. ({req_body.cp_company_name})",
            )

    set_clause, params = build_update_query(
        req_body,
        allowed_fields=[
            "author_nickname",
            "cover_image_file_id",
            "title",
            "synopsis",
            "ratings_code",
            "primary_genre_id",
            "sub_genre_id",
            "status_code",
            "uci",
            "isbn",
            "series_regular_price",
            "single_regular_price",
            "single_rental_price",
            "monopoly_yn",
            "open_yn",
            *([] if not blind_yn_in_request else ["blind_yn"]),
        ],
        field_mapping={
            "author_nickname": "author_name",
            "cover_image_file_id": "thumbnail_file_id",
            "synopsis": "synopsis_text",
        },
    )

    next_blind_yn = (req_body.blind_yn or "").upper() if blind_yn_in_request else current_blind_yn
    if next_blind_yn == "Y":
        if "open_yn" in params:
            params["open_yn"] = "N"
        else:
            set_clause = f"{set_clause}, open_yn = 'N'"

    set_clause = f"{set_clause}, price_type = :price_type"
    params["price_type"] = next_price_type
    if has_free_episode_range or clear_free_episode_range:
        set_clause = f"{set_clause}, paid_episode_no = :paid_episode_no"
        if next_price_type == "paid":
            params["paid_episode_no"] = (
                free_episode_end_no + 1 if has_free_episode_range else 1
            )
        else:
            params["paid_episode_no"] = None
    params["product_id"] = product_id

    query = text(f"UPDATE tb_product SET {set_clause} WHERE product_id = :product_id")

    await db.execute(query, params)

    if req_body.cp_company_name is not None:
        # cp사 선택한 상태
        query = text("""
                         select * from tb_product_contract_offer where product_id = :product_id
                         """)
        result = await db.execute(query, {"product_id": product_id})
        rows = result.mappings().all()
        if len(rows) == 0:
            # 기존 데이터가 없음 -> insert
            query = text("""
                             insert into tb_product_contract_offer (
                                 product_id,
                                 profit_type, author_profit, offer_profit,
                                 use_yn,
                                 author_user_id,
                                 author_accept_yn,
                                 offer_user_id,
                                 offer_type, offer_code, offer_price, offer_date,
                                 created_date
                             ) values (
                                 :product_id,
                                 'percent', :cp_settlement_rate, 100 - :cp_settlement_rate,
                                 'Y',
                                 (select author_id from tb_product where product_id = :product_id),
                                 NULL,
                                 (select user_id from tb_user_profile_apply where apply_type = 'cp' and company_name = :cp_company_name),
                                 'input', '', :cp_offered_price, now(),
                                 now()
                             )
                             """)
        else:
            # 기존 데이터가 있음 -> use_yn을 Y로 바꿔줌
            query = text("""
                             update tb_product_contract_offer set
                             use_yn = 'Y',
                             profit_type = 'percent', author_profit = :cp_settlement_rate, offer_profit = 100 - :cp_settlement_rate,
                             offer_user_id = (select user_id from tb_user_profile_apply where apply_type = 'cp' and company_name = :cp_company_name),
                             offer_type = 'input', offer_code = '', offer_price = :cp_offered_price, offer_date = now(),
                             updated_date = now()
                             where product_id = :product_id
                             """)
        await db.execute(
            query,
            {
                "cp_settlement_rate": req_body.cp_settlement_rate,
                "cp_offered_price": req_body.cp_offered_price,
                "product_id": product_id,
                "cp_company_name": req_body.cp_company_name,
            },
        )
    else:
        # 설정 안함 선택한 상태
        query = text("""
                         update tb_product_contract_offer set use_yn = 'N' where product_id = :product_id
                         """)
        await db.execute(query, {"product_id": product_id})

    if has_free_episode_range or clear_free_episode_range:
        if has_free_episode_range:
            query = text("""
                         UPDATE tb_product_episode
                            SET price_type = CASE
                                WHEN episode_no BETWEEN :free_episode_start_no AND :free_episode_end_no THEN 'free'
                                ELSE 'paid'
                            END,
                                updated_id = :updated_id
                          WHERE product_id = :product_id
                            AND use_yn = 'Y'
                         """)
            await db.execute(
                query,
                {
                    "product_id": product_id,
                    "free_episode_start_no": free_episode_start_no,
                    "free_episode_end_no": free_episode_end_no,
                    "updated_id": -1,
                },
            )
        else:
            query = text("""
                         UPDATE tb_product_episode
                            SET price_type = 'paid',
                                updated_id = :updated_id
                          WHERE product_id = :product_id
                            AND use_yn = 'Y'
                         """)
            await db.execute(query, {"product_id": product_id, "updated_id": -1})

    return {"result": req_body}


async def delete_product(product_id: int, db: AsyncSession):
    """
    작품 삭제

    Args:
        product_id: 작품 ID
        db: 데이터베이스 세션

    Returns:
        삭제 결과 딕셔너리
    """

    query = text("""
                        delete from tb_product
                        where product_id = :product_id
                    """)

    await db.execute(query, {"product_id": product_id})

    return {"result": True}
