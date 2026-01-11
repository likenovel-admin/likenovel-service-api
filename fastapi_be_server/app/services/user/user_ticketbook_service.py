import logging
from app.services.common import comm_service
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.exceptions import CustomResponseException
from app.const import ErrorMessages
from app.utils.query import build_insert_query, build_update_query
from app.utils.response import build_list_response, build_detail_response
import app.schemas.user_ticketbook as user_ticketbook_schema
import app.services.common.statistics_service as statistics_service

logger = logging.getLogger("user_ticketbook_app")  # 커스텀 로거 생성

"""
user_ticketbook 사용자 이용권 개별 서비스 함수 모음
"""


async def user_ticketbook_list(kc_user_id: str, db: AsyncSession):
    # kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # 해당 user_id의 이용권만 조회
    query = text("""
                 SELECT * FROM tb_user_ticketbook
                 WHERE user_id = :user_id
                 ORDER BY updated_date DESC
                 """)
    result = await db.execute(query, {"user_id": user_id})
    rows = result.mappings().all()
    return build_list_response(rows)


async def user_ticketbook_detail_by_id(id, db: AsyncSession):
    """
    사용자 이용권(user_ticketbook) 상세 조회
    """
    query = text("""
                 SELECT * FROM tb_user_ticketbook WHERE id = :id
                 """)
    result = await db.execute(query, {})
    row = result.mappings().one_or_none()
    return build_detail_response(row)


async def post_user_ticketbook(
    req_body: user_ticketbook_schema.PostUserTicketbookReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    if req_body is not None:
        logger.info(f"post_user_ticketbook: {req_body}")

    # kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    columns, values, params = build_insert_query(
        req_body,
        required_fields=["ticket_type", "user_id", "product_id"],
        optional_fields=["use_expired_date", "use_yn"],
        field_defaults={"use_yn": "N"},
    )

    query = text(
        f"INSERT INTO tb_user_ticketbook (id, {columns}, created_id, created_date) VALUES (default, {values}, :created_id, :created_date)"
    )

    await db.execute(query, params)

    await statistics_service.insert_site_statistics_log(
        db=db, type="active", user_id=user_id
    )

    # 무료이용권 지급 알림 전송
    try:
        # 사용자의 혜택정보 알림 설정 확인
        query = text("""
            select noti_yn
              from tb_user_notification
             where user_id = :user_id
               and noti_type = 'benefit'
        """)
        result = await db.execute(query, {"user_id": req_body.user_id})
        noti_setting = result.mappings().first()

        # 알림 설정이 ON이거나 설정이 없는 경우 (기본값 ON)
        if not noti_setting or noti_setting.get("noti_yn") == "Y":
            # 작품 정보 조회 (1. 선작독자 무료이용권 알림)
            product_title = None
            if req_body.product_id:
                query = text("""
                    select title
                      from tb_product
                     where product_id = :product_id
                """)
                result = await db.execute(query, {"product_id": req_body.product_id})
                product_info = result.mappings().first()
                if product_info:
                    product_title = product_info.get("title")

            # 알림 저장
            if product_title:
                noti_title = f"[{product_title}]의 선작독자 무료이용권이 도착"
                noti_content = ""
            else:
                noti_title = "선작독자 무료이용권이 도착"
                noti_content = ""

            query = text("""
                insert into tb_user_notification_item
                (user_id, noti_type, title, content, read_yn, created_id, created_date)
                values (:user_id, 'benefit', :title, :content, 'N', -1, NOW())
            """)
            await db.execute(
                query,
                {
                    "user_id": req_body.user_id,
                    "title": noti_title,
                    "content": noti_content,
                },
            )

            # TODO: FCM 푸시 전송 (FCM 토큰 테이블 구현 필요)
    except Exception as e:
        # 알림 전송 실패해도 이용권 지급은 성공으로 처리
        logger.error(f"Failed to send ticket notification: {e}")

    return {"result": req_body}


async def put_user_ticketbook(
    id: int,
    req_body: user_ticketbook_schema.PutUserTicketbookReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    if req_body is not None:
        logger.info(f"put_user_ticketbook: {req_body}")

    # kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    set_clause, params = build_update_query(
        req_body,
        allowed_fields=[
            "ticket_type",
            "user_id",
            "product_id",
            "use_expired_date",
            "use_yn",
        ],
    )
    params["id"] = id

    query = text(f"UPDATE tb_user_ticketbook SET {set_clause} WHERE id = :id")

    await db.execute(query, params)

    return {"result": req_body}


async def delete_user_ticketbook(id: int, kc_user_id: str, db: AsyncSession):
    # kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    query = text("""
                        delete from tb_user_ticketbook where id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}


async def use_user_ticketbook(id: int, kc_user_id: str, db: AsyncSession):
    """
    사용자 이용권(user_ticketbook) 사용
    """

    # kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # 이용권 조회 및 소유자 검증
    ticketbook_query = text("""
                              SELECT user_id, use_yn
                              FROM tb_user_ticketbook
                              WHERE id = :id
                              """)
    ticketbook_result = await db.execute(ticketbook_query, {"id": id})
    ticketbook_row = ticketbook_result.mappings().one_or_none()

    if not ticketbook_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_TICKETBOOK,
        )

    # 이용권 소유자와 현재 사용자 일치 여부 확인
    if ticketbook_row["user_id"] != user_id:
        raise CustomResponseException(
            status_code=status.HTTP_403_FORBIDDEN,
            message=ErrorMessages.FORBIDDEN_NOT_OWNER_OF_TICKETBOOK,
        )

    if ticketbook_row["use_yn"] == "Y":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_USED_TICKETBOOK,
        )

    update_filed_query_list = [
        "updated_id = :updated_id",
        "updated_date = :updated_date",
    ]

    db_execute_params = {"updated_id": -1, "updated_date": datetime.now(), "id": id}

    update_filed_query_list.append("use_yn = 'Y'")

    update_filed_query = ",".join(update_filed_query_list)

    query = text(f"""
                        update set tb_user_ticketbook
                        {update_filed_query}
                        where id = :id
                    """)

    await db.execute(query, db_execute_params)

    return {"result": True}
