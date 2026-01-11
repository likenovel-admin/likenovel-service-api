import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

import app.schemas.carousel as carousel_schema
from app.utils.response import build_list_response, build_detail_response

logger = logging.getLogger("carousel_banner_app")  # 커스텀 로거 생성

"""
carousel_banners 캐러셀 배너 개별 서비스 함수 모음
"""


async def carousel_list(db: AsyncSession):
    query = text("""
                 SELECT * FROM tb_carousel_banners ORDER BY updated_date DESC
                 """)
    result = await db.execute(query, {})
    rows = result.mappings().all()
    return build_list_response(rows)


async def carousel_detail_by_id(id, db: AsyncSession):
    """
    캐러셀 배너(carousel) 상세 조회
    """
    query = text("""
                 SELECT * FROM tb_carousel_banners WHERE id = :id
                 """)
    result = await db.execute(query, {})
    row = result.mappings().one_or_none()
    return build_detail_response(row)


async def post_carousel(
    req_body: carousel_schema.PostCarouselBannerReqBody, user_id: str, db: AsyncSession
):
    if req_body is not None:
        logger.info(f"post_carousel: {req_body}")

    query = text("""
                        insert into tb_carousel_banner (id, created_id, created_date)
                        values (default, :created_id, :created_date)
                    """)

    await db.execute(query, {"created_id": -1, "created_date": datetime.now()})

    return {"result": req_body}


async def put_carousel(
    id: int,
    req_body: carousel_schema.PutCarouselBannerReqBody,
    user_id: str,
    db: AsyncSession,
):
    if req_body is not None:
        logger.info(f"put_carousel: {req_body}")

    query = text("""
                        update set tb_carousel_banner
                        updated_id = :updated_id,
                        updated_date = :updated_date
                        where id = :id
                    """)

    await db.execute(
        query, {"updated_id": -1, "updated_date": datetime.now(), "id": id}
    )

    return {"result": req_body}


async def delete_carousel(id: int, user_id: str, db: AsyncSession):
    query = text("""
                        delete from tb_carousel_banner where id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}
