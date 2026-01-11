import logging
from typing import Optional
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.exceptions import CustomResponseException
import app.schemas.partner as partner_schema
from app.utils.query import build_update_query, get_pagination_params
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
    elif user_data["role"] == "partner":
        where += f"""
            AND a.product_id IN (
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

    # 회차별 매출 페이지에서 호출 시 매출 데이터 필터링
    if from_episode_sales_page:
        sales_date_condition = ""
        if start_date:
            sales_date_condition += f" AND DATE(sales.created_date) >= '{start_date}'"
        if end_date:
            sales_date_condition += f" AND DATE(sales.created_date) <= '{end_date}'"

        where += f"""
                     AND EXISTS (
                         SELECT 1
                         FROM tb_ptn_product_episode_sales sales
                         WHERE sales.product_id = a.product_id
                         {sales_date_condition}
                     )
                     """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        with tmp_product_episode_summary as (
            select product_id
                , count(1) as count_episode
                , sum(current_count_evaluation) as count_evaluation
            from tb_batch_daily_product_episode_count_summary
            group by product_id
        ),
        tmp_contract_offer_summary as (
            select z.product_id
                , y.company_name as cp_company_name
            from tb_product_contract_offer z
            inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
            and y.apply_type = 'cp'
            and y.approval_date is not null
            where z.use_yn = 'Y'
            and z.author_accept_yn = 'Y'
        )
        select count(a.product_id) as total_count
        from tb_product a
        left join tmp_product_episode_summary b on a.product_id = b.product_id
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
                , sum(current_count_evaluation) as count_evaluation
            from tb_batch_daily_product_episode_count_summary
            group by product_id
        ),
        tmp_contract_offer_summary as (
            select z.product_id
                , y.company_name as cp_company_name
            from tb_product_contract_offer z
            inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
            and y.apply_type = 'cp'
            and y.approval_date is not null
            where z.use_yn = 'Y'
            and z.author_accept_yn = 'Y'
        )
        select a.product_id
            , a.title
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
            , a.series_regular_price
            , a.monopoly_yn
        from tb_product a
        left join tmp_product_episode_summary b on a.product_id = b.product_id
        left join tmp_contract_offer_summary d on a.product_id = d.product_id
        WHERE 1=1 {where}
        ORDER BY a.created_date DESC
        {limit_clause}
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
                , sum(current_count_evaluation) as count_evaluation
            from tb_batch_daily_product_episode_count_summary
            group by product_id
        ),
        tmp_contract_offer_summary as (
            select z.product_id
                , y.company_name as cp_company_name
                , z.author_profit as cp_author_profit
                , z.offer_price as cp_offer_price
            from tb_product_contract_offer z
            inner join tb_user_profile_apply y on z.offer_user_id = y.user_id
            and y.apply_type = 'cp'
            and y.approval_date is not null
            where z.use_yn = 'Y'
            and z.author_accept_yn = 'Y'
        )
        select a.product_id
            , a.title
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
            , a.series_regular_price
            , a.monopoly_yn
            , case when a.open_yn = 'Y' then 'N' else 'Y' end as blind_yn
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
    req_body: partner_schema.PutProductReqBody, product_id: int, db: AsyncSession
):
    """
    작품 수정

    Args:
        req_body: 작품 수정 요청 데이터
        product_id: 작품 ID
        db: 데이터베이스 세션

    Returns:
        수정된 작품 정보 딕셔너리
    """

    if req_body.ratings_code is not None and req_body.ratings_code not in [
        "all",
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
                        and z.major_genre_yn = 'Y'
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
            "title",
            "ratings_code",
            "primary_genre_id",
            "sub_genre_id",
            "status_code",
            "uci",
            "isbn",
            "series_regular_price",
            "single_regular_price",
            "monopoly_yn",
            "open_yn",
        ],
    )
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
