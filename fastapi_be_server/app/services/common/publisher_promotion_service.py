import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

import app.schemas.publisher_promotion as publisher_promotion_schema
import app.services.common.statistics_service as statistics_service
from app.utils.response import build_list_response, build_detail_response

logger = logging.getLogger("publisher_promotion_app")  # 커스텀 로거 생성

"""
publisher_promotion 출판사 프로모션 개별 서비스 함수 모음
"""


async def publisher_promotion_list(db: AsyncSession):
    query = text("""
                 SELECT * FROM tb_publisher_promotion ORDER BY updated_date DESC
                 """)
    result = await db.execute(query, {})
    rows = result.mappings().all()
    return build_list_response(rows)


async def publisher_promotion_detail_by_id(id, db: AsyncSession):
    """
    출판사 프로모션(publisher_promotion) 상세 조회
    """
    query = text("""
                 SELECT * FROM tb_publisher_promotion WHERE id = :id
                 """)
    result = await db.execute(query, {})
    row = result.mappings().one_or_none()
    return build_detail_response(row)


async def post_publisher_promotion(
    req_body: publisher_promotion_schema.PostPublisherPromotionReqBody,
    user_id: str,
    db: AsyncSession,
):
    if req_body is not None:
        logger.info(f"post_publisher_promotion: {req_body}")

    await statistics_service.insert_site_statistics_log(
        db=db, type="active", user_id=user_id
    )

    query = text("""
                        insert into tb_publisher_promotion (id, created_id, created_date)
                        values (default, :created_id, :created_date)
                    """)

    await db.execute(query, {"created_id": -1, "created_date": datetime.now()})

    return {"result": req_body}


async def put_publisher_promotion(
    id: int,
    req_body: publisher_promotion_schema.PutPublisherPromotionReqBody,
    user_id: str,
    db: AsyncSession,
):
    if req_body is not None:
        logger.info(f"put_publisher_promotion: {req_body}")

    query = text("""
                        update set tb_publisher_promotion
                        updated_id = :updated_id,
                        updated_date = :updated_date
                        where id = :id
                    """)

    await db.execute(
        query, {"updated_id": -1, "updated_date": datetime.now(), "id": id}
    )

    return {"result": req_body}


async def delete_publisher_promotion(id: int, user_id: str, db: AsyncSession):
    query = text("""
                        delete from tb_publisher_promotion where id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}
