import logging
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.exceptions import CustomResponseException
import app.schemas.admin as admin_schema

from app.utils.fcm import PushNotificationPayload, send_push, translate_fcm_error
from app.utils.query import build_update_query, get_pagination_params
from app.utils.response import build_paginated_response, check_exists_or_404
from app.const import ErrorMessages


logger = logging.getLogger("admin_app")  # 커스텀 로거 생성

"""
관리자 메시지/푸시 서비스 함수 모음
"""


async def messages_between_users_list(
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    1:1 메시지 관리 (관리자용)

    Args:
        search_target: 검색 대상 (room_id, sender, receiver)
        search_word: 검색어
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        1:1 메시지 목록과 페이징 정보
    """

    where_conditions = []
    params = {}

    if search_word != "":
        if search_target == "room_id":
            where_conditions.append("cm.room_id = :search_word")
            params["search_word"] = search_word
        elif search_target == "sender":
            where_conditions.append("""
                cm.sender_user_id IN (
                    SELECT user_id FROM tb_user
                    WHERE user_id IN (
                        SELECT user_id FROM tb_user_profile
                        WHERE nickname LIKE :search_pattern
                    )
                )
            """)
            params["search_pattern"] = f"%{search_word}%"
        elif search_target == "receiver":
            where_conditions.append("""
                EXISTS (
                    SELECT 1 FROM tb_chat_room_members crm
                    INNER JOIN tb_user_profile up ON crm.user_id = up.user_id
                    WHERE crm.room_id = cm.room_id
                      AND crm.user_id != cm.sender_user_id
                      AND up.nickname LIKE :search_pattern
                )
            """)
            params["search_pattern"] = f"%{search_word}%"

    where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 파라미터 병합
    all_params = {**params}

    # 전체 개수 구하기
    count_query = text(f"""
        SELECT COUNT(*) AS total_count
        FROM tb_chat_messages cm
        LEFT JOIN tb_user_profile sender_profile ON cm.sender_user_id = sender_profile.user_id
        WHERE cm.is_deleted = 'N' AND {where_clause}
    """)
    count_result = await db.execute(count_query, all_params)
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회 - 파라미터 병합
    query_params = {**all_params, **limit_params}

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            cm.id AS message_id,
            cm.room_id,
            cm.sender_user_id AS sender,
            COALESCE(sender_profile.nickname, 'Unknown') AS sender_name,
            (
                SELECT GROUP_CONCAT(DISTINCT crm.user_id SEPARATOR ',')
                FROM tb_chat_room_members crm
                WHERE crm.room_id = cm.room_id
                  AND crm.user_id != cm.sender_user_id
            ) AS receiver,
            (
                SELECT GROUP_CONCAT(DISTINCT up.nickname SEPARATOR ',')
                FROM tb_chat_room_members crm
                INNER JOIN tb_user_profile up ON crm.user_id = up.user_id
                WHERE crm.room_id = cm.room_id
                  AND crm.user_id != cm.sender_user_id
            ) AS receiver_name,
            cm.content,
            cm.is_deleted,
            cm.created_date,
            cm.updated_date
        FROM tb_chat_messages cm
        LEFT JOIN tb_user_profile sender_profile ON cm.sender_user_id = sender_profile.user_id
        WHERE cm.is_deleted = 'N' AND {where_clause}
        ORDER BY cm.created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, query_params)
    rows = result.mappings().all()
    return build_paginated_response(rows, total_count, page, count_per_page)


async def push_message_templates_list(db: AsyncSession):
    """
    푸시 메시지 관리

    Args:
        db: 데이터베이스 세션

    Returns:
        푸시 메시지 템플릿 목록
    """

    # 실제 데이터 조회
    query = text("""
        SELECT
            *
        FROM tb_push_message_templates
        ORDER BY created_date DESC
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    return {"results": [dict(row) for row in rows]}


async def push_message_templates_detail_by_id(id: int, db: AsyncSession):
    """
    푸시 메시지 관리

    Args:
        id: 조회할 푸시 메시지 템플릿 ID
        db: 데이터베이스 세션

    Returns:
        푸시 메시지 템플릿 상세 정보
    """

    query = text(f"""
        SELECT
            *
        FROM tb_push_message_templates
        WHERE id = {id}
        ORDER BY created_date DESC LIMIT 1
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_PUSH_TEMPLATE)

    return dict(rows[0])


async def on_push_message_templates(id: int, db: AsyncSession):
    """
    푸시 메시지 관리

    Args:
        id: 활성화할 푸시 메시지 템플릿 ID
        db: 데이터베이스 세션

    Returns:
        푸시 메시지 템플릿 활성화 결과
    """

    query = text(f"""
        SELECT
            *
        FROM tb_push_message_templates
        WHERE id = {id}
        ORDER BY created_date DESC LIMIT 1
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_PUSH_TEMPLATE)

    push_message_template = dict(rows[0])

    if push_message_template["use_yn"] == "Y":
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.ALREADY_USING_STATE,
        )

    query = text("""
                        update tb_push_message_templates set
                        use_yn = 'Y', updated_id = :updated_id, updated_date = :updated_date
                        where id = :id
                    """)

    await db.execute(
        query,
        {
            "id": id,
            "updated_id": -1,
            "updated_date": datetime.now(),
        },
    )

    push_message_template["use_yn"] = "Y"
    return {"result": push_message_template}


async def off_push_message_templates(id: int, db: AsyncSession):
    """
    푸시 메시지 관리

    Args:
        id: 비활성화할 푸시 메시지 템플릿 ID
        db: 데이터베이스 세션

    Returns:
        푸시 메시지 템플릿 비활성화 결과
    """

    query = text(f"""
        SELECT
            *
        FROM tb_push_message_templates
        WHERE id = {id}
        ORDER BY created_date DESC LIMIT 1
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_PUSH_TEMPLATE)

    push_message_template = dict(rows[0])

    if push_message_template["use_yn"] == "N":
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.ALREADY_STOPPED_STATE,
        )

    query = text("""
                        update tb_push_message_templates set
                        use_yn = 'N', updated_id = :updated_id, updated_date = :updated_date
                        where id = :id
                    """)

    await db.execute(
        query,
        {
            "id": id,
            "updated_id": -1,
            "updated_date": datetime.now(),
        },
    )

    push_message_template["use_yn"] = "N"
    return {"result": push_message_template}


async def put_push_message_templates(
    id: int, req_body: admin_schema.PutPushMessageTemplatesReqBody, db: AsyncSession
):
    """
    푸시 메시지 템플릿 수정

    Args:
        id: 수정할 푸시 메시지 템플릿 ID
        req_body: 수정할 푸시 메시지 템플릿 정보
        db: 데이터베이스 세션

    Returns:
        푸시 메시지 템플릿 수정 결과
    """

    query = text("""
                    SELECT * FROM tb_push_message_templates WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_PUSH_TEMPLATE)

    set_clause, params = build_update_query(
        req_body,
        allowed_fields=[
            "use_yn",
            "name",
            "condition",
            "landing_page",
            "image_id",
            "contents",
        ],
    )
    params["id"] = id

    query = text(f"UPDATE tb_push_message_templates SET {set_clause} WHERE id = :id")

    await db.execute(query, params)

    return {"result": req_body}


async def send_push_message_directly(
    req_body: admin_schema.SendPushMessageDirectlyReqBody, db: AsyncSession
):
    """
    푸시 메시지 직접 발송

    Args:
        req_body: 발송할 푸시 메시지 정보 (타입, 제목, 내용 등)
        db: 데이터베이스 세션

    Returns:
        푸시 메시지 발송 결과
    """

    try:
        # 1. 알림 설정이 ON인 사용자 조회
        query = text("""
            select user_id
              from tb_user_notification
             where noti_type = :noti_type
               and noti_yn = 'Y'
        """)
        result = await db.execute(query, {"noti_type": req_body.noti_type})
        users_with_noti_on = result.mappings().all()

        # 알림 설정이 없는 사용자도 포함 (기본값 ON)
        query = text("""
            select u.user_id
              from tb_user u
             where u.use_yn = 'Y'
               and not exists (
                   select 1 from tb_user_notification n
                    where n.user_id = u.user_id
                      and n.noti_type = :noti_type
               )
        """)
        result = await db.execute(query, {"noti_type": req_body.noti_type})
        users_without_setting = result.mappings().all()

        # 알림을 받을 사용자 목록 합치기
        target_users = list(users_with_noti_on) + list(users_without_setting)

        # 2. 각 사용자에게 알림 아이템 저장
        if target_users:
            # bulk insert를 위한 values 생성
            for user in target_users:
                query = text("""
                    insert into tb_user_notification_item
                    (user_id, noti_type, title, content, read_yn, created_id, created_date)
                    values (:user_id, :noti_type, :title, :content, 'N', -1, NOW())
                """)
                await db.execute(
                    query,
                    {
                        "user_id": user.get("user_id"),
                        "noti_type": req_body.noti_type,
                        "title": req_body.title,
                        "content": req_body.content,
                    },
                )

            await db.commit()

        # 3. FCM 푸시 전송 (모든 사용자에게)
        # TODO: 타입별 topic 구독 기능 구현 후 topic="users-{noti_type}"로 변경
        push_response = send_push(
            PushNotificationPayload(
                topic="all-users",
                title=req_body.title,
                body=req_body.content,
                data={"noti_type": req_body.noti_type},
                # image_url="" # TODO 로고 이미지 url
            )
        )

        if "error" in push_response:
            logger.warning(f"Push notification error: {push_response}")
            return {
                "result": False,
                "org_error": push_response["error"],
                "message": translate_fcm_error(
                    push_response["error"].get("message", "")
                ),
            }
        else:
            return {
                "result": True,
                "message": f"푸시 메시지가 성공적으로 발송되었습니다. (발송 대상: {len(target_users)}명)",
                "fcm_id": push_response.get("message_id"),
                "saved_count": len(target_users),
            }

    except Exception as e:
        logger.error(f"Error sending notification: {e}")
        return {"result": False, "message": "알림 발송 중 오류가 발생했습니다."}
