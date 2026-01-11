from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.exceptions import CustomResponseException
import app.schemas.support as support_schema

from app.config.log_config import service_error_logger
from app.const import LOGGER_TYPE, ErrorMessages

error_logger = service_error_logger(LOGGER_TYPE.LOGGER_INSTANCE_NAME_FOR_SERVICE_ERROR)

"""
support 도메인 개별 서비스 함수 모음
"""


async def get_support_faqs(
    category: str, page: int, count_per_page: int, db: AsyncSession
):
    """
    FAQ 목록 조회 (페이지네이션 포함)

    Args:
        category: 카테고리 필터 (None이면 전체)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        FAQ 목록과 페이징 정보
    """
    from app.utils.query import get_pagination_params

    faqs_list = list()
    total_count = 0

    try:
        # 카테고리 필터 조건
        category_filter = ""
        params = {}
        if category and category != "all":
            category_filter = "AND a.faq_type = :category"
            params["category"] = category

        # 전체 개수 조회
        count_query = text(f"""
            SELECT COUNT(*) AS total_count
            FROM tb_faq a
            WHERE a.use_yn = 'Y'
            {category_filter}
        """)
        count_result = await db.execute(count_query, params)
        total_count = dict(count_result.mappings().first())["total_count"]

        # 페이지네이션 파라미터 생성
        limit_clause, limit_params = get_pagination_params(page, count_per_page)
        query_params = {**params, **limit_params}

        # FAQ 목록 조회
        query = text(f"""
            WITH tmp_get_support_faqs AS (
                SELECT ROW_NUMBER() OVER (ORDER BY a.primary_yn DESC, a.updated_date DESC) AS row_num
                    , a.primary_yn
                    , a.id
                    , a.faq_type
                    , a.subject AS question
                    , a.content AS answer
                    , a.updated_date AS posting_date
                FROM tb_faq a
                WHERE a.use_yn = 'Y'
                {category_filter}
            )
            SELECT t.id
                , t.faq_type AS type
                , t.question
                , t.answer
                , t.posting_date
            FROM tmp_get_support_faqs t
            ORDER BY t.row_num
            {limit_clause}
        """)

        result = await db.execute(query, query_params)
        db_rst = result.mappings().all()

        if db_rst:
            faqs_list = [support_schema.GetSupportFaqsToCamel(**row) for row in db_rst]

    except SQLAlchemyError as e:
        error_logger.error(f"faqList: {e}")
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )

    res_body = {
        "data": {
            "totalItems": total_count,
            "page": page,
            "countPerPage": count_per_page,
            "items": faqs_list,
        }
    }

    return res_body


async def get_support_faqs_faq_id(faq_id: str, db: AsyncSession):
    faq_data = dict()

    try:
        async with db.begin():
            query = text("""
                             select a.subject as title
                                  , a.updated_date as posting_date
                                  , a.content
                               from tb_faq a
                              where a.use_yn = 'Y'
                                and a.id = :faq_id
                             """)

            bind_var = dict()
            bind_var["faq_id"] = faq_id

            result = await db.execute(query, bind_var)
            db_rst = result.mappings().all()

            if db_rst:
                faq_data = support_schema.GetSupportFaqsFaqIdToCamel(**db_rst)
    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )

    res_data = dict()
    res_data["faq"] = faq_data

    res_body = dict()
    res_body["data"] = res_data

    return res_body


async def post_support_qnas(kc_user_id: str, db: AsyncSession):
    return
