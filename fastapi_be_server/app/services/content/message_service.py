"""
messages 도메인 개별 서비스 함수 모음 - 채팅 기능
"""

import logging
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.exceptions import CustomResponseException
from app.const import ErrorMessages
from app.utils.query import get_pagination_params, get_file_path_sub_query
from app.services.common import comm_service
import app.schemas.message as message_schema

logger = logging.getLogger("app")


def query_UTC2KST(utc_column: str, return_column: str) -> str:
    return f"DATE_ADD({utc_column}, INTERVAL 9 HOUR) AS {return_column}"


async def get_or_create_chat_room(
    kc_user_id: str,
    target_user_id: int,
    db: AsyncSession,
    default_message: Optional[str] = None,
) -> int:
    """
    대화방 생성 (항상 새 대화방 생성)

    NOTE: 비즈니스 요구사항으로 인해 기존 대화방 조회 로직이 제거되었습니다.
    동일한 사용자 간에도 계약 협상 등 여러 건의 대화방이 필요할 수 있어,
    매번 새로운 대화방을 생성합니다.

    Args:
        kc_user_id: 현재 사용자 keycloak ID
        target_user_id: 상대방 사용자 ID
        db: 데이터베이스 세션
        default_message: 첫 메시지 (선택사항). 제공되면 자동으로 첫 메시지 전송

    Returns:
        생성된 대화방 ID
    """

    # 현재 사용자 ID 조회
    current_user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if current_user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_USER,
        )

    # 상대방 사용자 존재 확인
    check_user_query = text("""
        SELECT user_id FROM tb_user WHERE user_id = :target_user_id AND use_yn = 'Y'
    """)
    result = await db.execute(check_user_query, {"target_user_id": target_user_id})
    if not result.scalar():
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_USER,
        )

    # 항상 새 대화방 생성 (기존 대화방이 있어도 새로 생성)
    # NOTE: 비즈니스 요구사항 - 동일한 사용자 간에도 계약 협상 등 여러 건의 대화방이 필요할 수 있음
    # 기존 대화방을 찾지 않고 매번 새 대화방을 생성하는 것이 의도된 동작입니다.
    create_room_query = text("""
        INSERT INTO tb_chat_rooms (created_date, updated_date)
        VALUES (NOW(), NOW())
    """)
    result = await db.execute(create_room_query)
    room_id = result.lastrowid

    # 멤버 추가
    add_members_query = text("""
        INSERT INTO tb_chat_room_members (room_id, user_id, is_active, created_date, updated_date)
        VALUES
            (:room_id, :user_id1, 'Y', NOW(), NOW()),
            (:room_id, :user_id2, 'Y', NOW(), NOW())
    """)
    await db.execute(
        add_members_query,
        {
            "room_id": room_id,
            "user_id1": current_user_id,
            "user_id2": target_user_id,
        },
    )

    # default_message가 있으면 첫 메시지 생성
    if default_message:
        # 메시지 생성 (sender_user_id는 target_user_id로 설정)
        # NOTE: default_message는 상대방(target_user)이 보낸 것처럼 표시됨... 뭔가 이상한데 프론트 개발자 요청사항이라 이렇게 함...
        create_message_query = text("""
            INSERT INTO tb_chat_messages (room_id, sender_user_id, content, created_date, updated_date)
            VALUES (:room_id, :sender_user_id, :content, NOW(), NOW())
        """)
        await db.execute(
            create_message_query,
            {
                "room_id": room_id,
                "sender_user_id": target_user_id,
                "content": default_message,
            },
        )

    return room_id


async def get_chat_room_list(
    kc_user_id: str,
    filter_type: Optional[str],
    search_nickname: Optional[str],
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    대화방 리스트 조회

    Args:
        kc_user_id: 현재 사용자 keycloak ID
        filter_type: 필터 타입 (all/unread)
        search_nickname: 검색할 닉네임
        page: 페이지 번호
        count_per_page: 페이지당 개수
        db: 데이터베이스 세션

    Returns:
        대화방 리스트
    """

    # 현재 사용자 ID 조회
    current_user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if current_user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_USER,
        )

    where_conditions = ["crm.user_id = :current_user_id", "crm.is_active = 'Y'"]
    query_params = {"current_user_id": current_user_id}

    # 안읽음 필터
    if filter_type == "unread":
        where_conditions.append("""
            (SELECT COUNT(*) FROM tb_chat_messages cm2
             WHERE cm2.room_id = crm.room_id
               AND cm2.sender_user_id != :current_user_id
               AND (crm.last_read_message_id IS NULL OR cm2.id > crm.last_read_message_id)
               AND cm2.is_deleted = 'N') > 0
        """)

    # 닉네임 검색
    if search_nickname:
        where_conditions.append("other_user_profile.nickname LIKE :search_nickname")
        query_params["search_nickname"] = f"%{search_nickname}%"

    where_clause = " AND ".join(where_conditions)

    # 전체 개수
    count_query = text(f"""
        SELECT COUNT(DISTINCT crm.room_id) AS total_count
        FROM tb_chat_room_members crm
        INNER JOIN tb_chat_room_members other_user_member ON crm.room_id = other_user_member.room_id
        INNER JOIN tb_user_profile other_user_profile ON other_user_member.user_id = other_user_profile.user_id AND other_user_profile.default_yn = 'Y'
        WHERE other_user_member.user_id != :current_user_id
          AND {where_clause}
    """)
    result = await db.execute(count_query, query_params)
    total_count = result.scalar() or 0

    # 페이지네이션
    limit_clause, limit_params = get_pagination_params(page, count_per_page)
    query_params.update(limit_params)

    # 대화방 리스트 조회
    list_query = text(f"""
        SELECT
            crm.room_id,
            other_user_member.user_id AS other_user_id,
            other_user_profile.profile_id AS other_user_profile_id,
            other_user_profile.nickname AS other_user_nickname,
            {get_file_path_sub_query("other_user_profile.profile_image_id", "other_user_profile_image_path")},
            (SELECT y.file_path
             FROM tb_common_file z, tb_common_file_item y, tb_user_badge x
             WHERE z.file_group_id = y.file_group_id
               AND z.use_yn = 'Y'
               AND y.use_yn = 'Y'
               AND z.group_type = 'badge'
               AND x.badge_image_id = z.file_group_id
               AND x.badge_type = 'interest'
               AND x.use_yn = 'Y'
               AND x.display_yn = 'Y'
               AND x.user_id = other_user_profile.user_id
               AND x.profile_id = other_user_profile.profile_id
             LIMIT 1) as other_user_interest_level_badge_image_path,
            (SELECT y.file_path
             FROM tb_common_file z, tb_common_file_item y, tb_user_badge x
             WHERE z.file_group_id = y.file_group_id
               AND z.use_yn = 'Y'
               AND y.use_yn = 'Y'
               AND z.group_type = 'badge'
               AND x.badge_image_id = z.file_group_id
               AND x.badge_type = 'event'
               AND x.use_yn = 'Y'
               AND x.display_yn = 'Y'
               AND x.user_id = other_user_profile.user_id
               AND x.profile_id = other_user_profile.profile_id
             LIMIT 1) as other_user_event_level_badge_image_path,
            last_msg.content AS last_message_content,
            {query_UTC2KST("last_msg.created_date", "last_message_date")},
            (SELECT COUNT(*)
             FROM tb_chat_messages cm2
             WHERE cm2.room_id = crm.room_id
               AND cm2.sender_user_id != :current_user_id
               AND (crm.last_read_message_id IS NULL OR cm2.id > crm.last_read_message_id)
               AND cm2.is_deleted = 'N') AS unread_message_count,
            crm.is_active
        FROM tb_chat_room_members crm
        INNER JOIN tb_chat_room_members other_user_member ON crm.room_id = other_user_member.room_id
        INNER JOIN tb_user_profile other_user_profile ON other_user_member.user_id = other_user_profile.user_id AND other_user_profile.default_yn = 'Y'
        LEFT JOIN (
            SELECT room_id, content, created_date
            FROM tb_chat_messages cm1
            WHERE cm1.id = (
                SELECT MAX(id)
                FROM tb_chat_messages cm2
                WHERE cm2.room_id = cm1.room_id AND cm2.is_deleted = 'N'
            )
        ) last_msg ON crm.room_id = last_msg.room_id
        WHERE other_user_member.user_id != :current_user_id
          AND {where_clause}
        ORDER BY COALESCE(last_msg.created_date, crm.created_date) DESC
        {limit_clause}
    """)

    result = await db.execute(list_query, query_params)
    rooms = [dict(row) for row in result.mappings().all()]

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "results": rooms,
    }


async def get_chat_messages(
    kc_user_id: str,
    room_id: int,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    특정 대화방의 메시지 조회

    Args:
        kc_user_id: 현재 사용자 keycloak ID
        room_id: 대화방 ID
        page: 페이지 번호
        count_per_page: 페이지당 개수
        db: 데이터베이스 세션

    Returns:
        메시지 리스트
    """

    # 현재 사용자 ID 조회
    current_user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if current_user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_USER,
        )

    # 대화방 멤버 확인
    check_member_query = text("""
        SELECT id FROM tb_chat_room_members
        WHERE room_id = :room_id AND user_id = :user_id AND is_active = 'Y'
    """)
    result = await db.execute(
        check_member_query, {"room_id": room_id, "user_id": current_user_id}
    )
    if not result.scalar():
        raise CustomResponseException(
            status_code=status.HTTP_403_FORBIDDEN,
            message=ErrorMessages.FORBIDDEN_ACCESS_CHAT_ROOM,
        )

    # 전체 메시지 수
    count_query = text("""
        SELECT COUNT(*) AS total_count
        FROM tb_chat_messages
        WHERE room_id = :room_id AND is_deleted = 'N'
    """)
    result = await db.execute(count_query, {"room_id": room_id})
    total_count = result.scalar() or 0

    # 페이지네이션
    limit_clause, limit_params = get_pagination_params(page, count_per_page)
    query_params = {"room_id": room_id, **limit_params}

    # 메시지 조회 (최신순)
    messages_query = text(f"""
        SELECT
            cm.id AS message_id,
            cm.room_id,
            cm.sender_user_id,
            cm.content,
            CASE
                WHEN cm.sender_user_id = :current_user_id THEN 'Y'
                ELSE (CASE WHEN crm.last_read_message_id >= cm.id THEN 'Y' ELSE 'N' END)
            END AS is_read,
            {query_UTC2KST("cm.created_date", "created_date")}
        FROM tb_chat_messages cm
        LEFT JOIN tb_chat_room_members crm ON cm.room_id = crm.room_id
            AND crm.user_id != cm.sender_user_id
        WHERE cm.room_id = :room_id AND cm.is_deleted = 'N'
        ORDER BY cm.created_date DESC
        {limit_clause}
    """)
    query_params["current_user_id"] = current_user_id

    result = await db.execute(messages_query, query_params)
    messages = [dict(row) for row in result.mappings().all()]

    # 읽음 상태 업데이트 (마지막 메시지까지 읽음 처리)
    if messages:
        latest_message_id = max(msg["message_id"] for msg in messages)
        update_read_query = text("""
            UPDATE tb_chat_room_members
            SET last_read_message_id = :message_id
            WHERE room_id = :room_id AND user_id = :user_id
              AND (last_read_message_id IS NULL OR last_read_message_id < :message_id)
        """)
        await db.execute(
            update_read_query,
            {
                "room_id": room_id,
                "user_id": current_user_id,
                "message_id": latest_message_id,
            },
        )

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "results": list(reversed(messages)),  # 오래된 순서로 반환
    }


async def send_chat_message(
    kc_user_id: str,
    room_id: int,
    content: str,
    db: AsyncSession,
):
    """
    메시지 전송

    Args:
        kc_user_id: 현재 사용자 keycloak ID
        room_id: 대화방 ID
        content: 메시지 내용
        db: 데이터베이스 세션

    Returns:
        전송된 메시지 정보
    """

    # 현재 사용자 ID 조회
    current_user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if current_user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_USER,
        )

    # 대화방 멤버 확인
    check_member_query = text("""
        SELECT id FROM tb_chat_room_members
        WHERE room_id = :room_id AND user_id = :user_id AND is_active = 'Y'
    """)
    result = await db.execute(
        check_member_query, {"room_id": room_id, "user_id": current_user_id}
    )
    if not result.scalar():
        raise CustomResponseException(
            status_code=status.HTTP_403_FORBIDDEN,
            message=ErrorMessages.FORBIDDEN_ACCESS_CHAT_ROOM,
        )

    # 메시지 생성
    insert_message_query = text("""
        INSERT INTO tb_chat_messages (room_id, sender_user_id, content, is_deleted, created_date, updated_date)
        VALUES (:room_id, :sender_user_id, :content, 'N', NOW(), NOW())
    """)
    result = await db.execute(
        insert_message_query,
        {
            "room_id": room_id,
            "sender_user_id": current_user_id,
            "content": content,
        },
    )
    message_id = result.lastrowid

    # 생성된 메시지 조회
    get_message_query = text(f"""
        SELECT
            id AS message_id,
            room_id,
            sender_user_id,
            content,
            'Y' AS is_read,
            {query_UTC2KST("created_date", "created_date")}
        FROM tb_chat_messages
        WHERE id = :message_id
    """)
    result = await db.execute(get_message_query, {"message_id": message_id})
    message = dict(result.mappings().first())

    return message


async def leave_chat_room(
    kc_user_id: str,
    room_id: int,
    db: AsyncSession,
):
    """
    채팅방 나가기

    Args:
        kc_user_id: 현재 사용자 keycloak ID
        room_id: 대화방 ID
        db: 데이터베이스 세션
    """

    # 현재 사용자 ID 조회
    current_user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if current_user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_USER,
        )

    # 대화방 멤버 확인
    check_member_query = text("""
        SELECT id FROM tb_chat_room_members
        WHERE room_id = :room_id AND user_id = :user_id AND is_active = 'Y'
    """)
    result = await db.execute(
        check_member_query, {"room_id": room_id, "user_id": current_user_id}
    )
    if not result.scalar():
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_CHAT_ROOM,
        )

    # 채팅방 나가기
    leave_query = text("""
        UPDATE tb_chat_room_members
        SET is_active = 'N', left_date = NOW()
        WHERE room_id = :room_id AND user_id = :user_id
    """)
    await db.execute(leave_query, {"room_id": room_id, "user_id": current_user_id})

    return {"success": True}


async def report_chat_room(
    kc_user_id: str,
    room_id: int,
    req_body: message_schema.PostChatMessageReportReqBody,
    db: AsyncSession,
):
    """
    대화방 신고

    Args:
        kc_user_id: 신고자 keycloak ID
        room_id: 신고할 대화방 ID
        req_body: 신고 정보 (report_reason, report_detail)
        db: 데이터베이스 세션
    """

    # 현재 사용자 ID 조회
    current_user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if current_user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_USER,
        )

    # 대화방 존재 및 멤버 확인
    check_room_query = text("""
        SELECT crm.id, crm.room_id
        FROM tb_chat_room_members crm
        WHERE crm.room_id = :room_id
          AND crm.user_id = :user_id
          AND crm.is_active = 'Y'
    """)
    result = await db.execute(
        check_room_query,
        {"room_id": room_id, "user_id": current_user_id},
    )
    if not result.scalar():
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_CHAT_ROOM,
        )

    # 중복 신고 확인
    check_duplicate_query = text("""
        SELECT id FROM tb_chat_room_reports
        WHERE room_id = :room_id AND reporter_user_id = :reporter_user_id
    """)
    result = await db.execute(
        check_duplicate_query,
        {"room_id": room_id, "reporter_user_id": current_user_id},
    )
    if result.scalar():
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_REPORTED_MESSAGE,
        )

    # 신고 생성
    insert_report_query = text("""
        INSERT INTO tb_chat_room_reports (room_id, reporter_user_id, report_reason, report_detail, status, created_date, updated_date)
        VALUES (:room_id, :reporter_user_id, :report_reason, :report_detail, 'pending', NOW(), NOW())
    """)
    await db.execute(
        insert_report_query,
        {
            "room_id": room_id,
            "reporter_user_id": current_user_id,
            "report_reason": req_body.report_reason,
            "report_detail": req_body.report_detail,
        },
    )

    return {"success": True}


async def get_unread_chat_count(kc_user_id: str, db: AsyncSession):
    """
    읽지 않은 채팅 개수 조회

    Args:
        kc_user_id: 현재 사용자 keycloak ID
        db: 데이터베이스 세션

    Returns:
        읽지 않은 채팅 개수
    """
    # 현재 사용자 ID 조회
    current_user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if current_user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_USER,
        )

    # 읽지 않은 메시지가 있는 대화방 개수 조회
    count_query = text("""
        SELECT COUNT(DISTINCT crm.room_id) as unread_chat_count
        FROM tb_chat_room_members crm
        WHERE crm.user_id = :current_user_id
          AND crm.is_active = 'Y'
          AND EXISTS (
              SELECT 1
              FROM tb_chat_messages cm
              WHERE cm.room_id = crm.room_id
                AND cm.sender_user_id != :current_user_id
                AND (crm.last_read_message_id IS NULL OR cm.id > crm.last_read_message_id)
                AND cm.is_deleted = 'N'
          )
    """)

    result = await db.execute(count_query, {"current_user_id": current_user_id})
    count_row = result.mappings().one_or_none()
    unread_count = count_row["unread_chat_count"] if count_row else 0

    return {"unreadCount": unread_count}
