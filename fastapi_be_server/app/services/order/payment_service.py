import logging

# from venv import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.schemas import payment as payment_schema

logger = logging.getLogger("payment_app")  # 커스텀 로거 생성

"""
payments 도메인 개별 서비스 함수 모음
"""


async def payment_verify_virtual_account(
    req_body: payment_schema.VirtualAccountReqBody, user_id: str, db: AsyncSession
):
    if req_body is not None:
        logger.info(f"payment_verify_virtual_account: {req_body}")

    if req_body.cover_image_file_id is None or req_body.cover_image_file_id == 0:
        query = text("""
                        update tb_store_order a
                        set a.order_status = :order_status                            
                            , a.updated_id = :updated_id
                            , a.updated_date = :updated_date
                        where a.order_no = :order_no 
                            and a.order_status = :before_order_status                             
                        """)

        await db.execute(
            query,
            {
                "order_no": req_body.order_no,
                "before_order_status": 10,
                "order_status": 20,
                "updated_id": -1,
                "updated_date": datetime.now(),
            },
        )

    return {"result": req_body}
