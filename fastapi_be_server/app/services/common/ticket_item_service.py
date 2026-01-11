import json
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

import app.schemas.ticket_item as ticket_item_schema
import app.schemas.user_ticketbook as user_ticketbook_schema
import app.schemas.user_productbook as user_productbook_schema
import app.services.user.user_ticketbook_service as user_ticketbook_service
import app.services.user.user_productbook_service as user_productbook_service
from app.const import CommonConstants
from app.utils.response import build_list_response, build_detail_response

logger = logging.getLogger("ticket_item_app")  # 커스텀 로거 생성

"""
ticket_item 이용권/대여권 개별 서비스 함수 모음
"""


async def ticket_item_list(db: AsyncSession):
    query = text("""
                 SELECT * FROM tb_ticket_item ORDER BY updated_date DESC
                 """)
    result = await db.execute(query, {})
    rows = result.mappings().all()
    return build_list_response(rows)


async def ticket_item_detail_by_id(id, db: AsyncSession):
    """
    이용권/대여권(ticket_item) 상세 조회
    """
    query = text("""
                 SELECT * FROM tb_ticket_item WHERE id = :id
                 """)
    result = await db.execute(query, {"id": id})
    row = result.mappings().one_or_none()
    return build_detail_response(row)


async def post_ticket_item(
    req_body: ticket_item_schema.PostTicketItemReqBody, user_id: str, db: AsyncSession
):
    if req_body is not None:
        logger.info(f"post_ticket_item: {req_body}")

    column_list = []
    value_list = []

    db_execute_params = {"created_id": -1, "created_date": datetime.now()}

    column_list.append("ticket_type")
    value_list.append(":ticket_type")
    db_execute_params["ticket_type"] = req_body.ticket_type

    if req_body.ticket_name is not None:
        column_list.append("ticket_name")
        value_list.append(":ticket_name")
        db_execute_params["ticket_name"] = req_body.ticket_name

    column_list.append("price")
    value_list.append(":price")
    db_execute_params["price"] = req_body.price | 0

    column_list.append("settlement_yn")
    value_list.append(":settlement_yn")
    db_execute_params["settlement_yn"] = req_body.settlement_yn | CommonConstants.NO

    column_list.append("expired_hour")
    value_list.append(":expired_hour")
    db_execute_params["expired_hour"] = req_body.expired_hour | 0

    column_list.append("use_yn")
    value_list.append(":use_yn")
    db_execute_params["use_yn"] = req_body.use_yn | CommonConstants.YES

    column_list.append("target_products")
    value_list.append(":target_products")
    db_execute_params["target_products"] = (
        json.dumps(req_body.target_products)
        if req_body.target_products is not None
        else "[]"
    )

    columns = ",".join(column_list)
    values = ",".join(value_list)

    query = text(f"""
                        insert into tb_ticket_item (ticket_id, {columns}, created_id, created_date)
                        values (default, {values}, :created_id, :created_date)
                    """)

    await db.execute(query, db_execute_params)

    return {"result": req_body}


async def put_ticket_item(
    id: int,
    req_body: ticket_item_schema.PutTicketItemReqBody,
    user_id: str,
    db: AsyncSession,
):
    if req_body is not None:
        logger.info(f"put_ticket_item: {req_body}")

    update_filed_query_list = [
        "updated_id = :updated_id",
        "updated_date = :updated_date",
    ]

    db_execute_params = {
        "updated_id": -1,
        "updated_date": datetime.now(),
        "ticket_id": id,
    }

    update_filed_query_list.append("ticket_type = :ticket_type")
    db_execute_params["ticket_type"] = req_body.ticket_type

    if req_body.ticket_name is not None:
        update_filed_query_list.append("ticket_name = :ticket_name")
        db_execute_params["ticket_name"] = req_body.ticket_name

    if req_body.price is not None:
        update_filed_query_list.append("price = :price")
        db_execute_params["price"] = req_body.price

    if req_body.settlement_yn is not None:
        update_filed_query_list.append("settlement_yn = :settlement_yn")
        db_execute_params["settlement_yn"] = req_body.settlement_yn

    if req_body.expired_hour is not None:
        update_filed_query_list.append("expired_hour = :expired_hour")
        db_execute_params["expired_hour"] = req_body.expired_hour

    if req_body.use_yn is not None:
        update_filed_query_list.append("use_yn = :use_yn")
        db_execute_params["use_yn"] = req_body.use_yn

    if req_body.target_products is not None:
        update_filed_query_list.append("target_products = :target_products")
        db_execute_params["target_products"] = json.dumps(req_body.target_products)

    update_filed_query = ",".join(update_filed_query_list)

    query = text(f"""
                        update set tb_ticket_item
                        {update_filed_query}
                        where ticket_id = :ticket_id
                    """)

    await db.execute(query, db_execute_params)

    return {"result": req_body}


async def delete_ticket_item(id: int, user_id: str, db: AsyncSession):
    query = text("""
                        delete from tb_ticket_item where ticket_id = :ticket_id
                    """)

    await db.execute(query, {"ticket_id": id})

    return {"result": True}


async def issuance_ticketbook(
    id: int,
    req_body: user_ticketbook_schema.PostUserTicketbookReqBody,
    user_id: str,
    db: AsyncSession,
):
    """
    이용권(ticket_item) 발급
    """
    ticket_item = ticket_item_detail_by_id(id, db)

    if ticket_item.get("ticket_type") != "ticketbook":
        # 이용권이 아니면 여기서 리턴
        return {"result": False}

    return await user_ticketbook_service.post_user_ticketbook(req_body, user_id, db)


async def issuance_productbook(
    id: int,
    req_body: user_productbook_schema.PostUserProductbookReqBody,
    user_id: str,
    db: AsyncSession,
):
    """
    대여권(ticket_item) 발급
    """
    ticket_item = ticket_item_detail_by_id(id, db)

    if ticket_item.get("ticket_type") != "productbook":
        # 이용권이 아니면 여기서 리턴
        return {"result": False}

    return await user_productbook_service.post_user_productbook(req_body, user_id, db)
