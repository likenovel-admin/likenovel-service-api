from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.content.message_service as message_service

router = APIRouter(prefix="/messages")


@router.get(
    "/chat-rooms",
    tags=["채팅"],
    responses={
        200: {
            "description": "대화방 리스트 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "대화방 리스트",
                            "value": {
                                "total_count": 10,
                                "page": 1,
                                "count_per_page": 20,
                                "results": [
                                    {
                                        "room_id": 1,
                                        "other_user_id": 100,
                                        "other_user_profile_id": 123,
                                        "other_user_nickname": "작가123",
                                        "other_user_profile_image_path": "https://cdn.likenovel.dev/user/profile.webp",
                                        "other_user_interest_level_badge_image_path": "https://cdn.likenovel.dev/badge/interest/1.webp",
                                        "other_user_event_level_badge_image_path": None,
                                        "last_message_content": "안녕하세요!",
                                        "last_message_date": "2025-10-14T10:00:00",
                                        "unread_message_count": 3,
                                        "is_active": "Y",
                                    }
                                ],
                            },
                        }
                    }
                }
            },
        }
    },
    dependencies=[Depends(analysis_logger)],
)
async def get_chat_rooms(
    filter_type: Optional[str] = Query(None, description="필터 (all/unread)"),
    search_nickname: Optional[str] = Query(None, description="닉네임 검색"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    count_per_page: int = Query(20, ge=1, le=100, description="페이지당 개수"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    대화방 리스트 조회
    - 전체/안읽음 필터 가능
    - 닉네임으로 검색 가능
    - 대화방 정보와 상대방 프로필 조회
    - 안읽은 메시지 개수 표시
    """
    return await message_service.get_chat_room_list(
        kc_user_id=user.get("sub"),
        filter_type=filter_type,
        search_nickname=search_nickname,
        page=page,
        count_per_page=count_per_page,
        db=db,
    )


@router.get(
    "/chat-rooms/{room_id}/messages",
    tags=["채팅"],
    responses={
        200: {
            "description": "특정 대화방의 메시지 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "메시지 리스트",
                            "value": {
                                "total_count": 50,
                                "page": 1,
                                "count_per_page": 30,
                                "results": [
                                    {
                                        "message_id": 1,
                                        "room_id": 1,
                                        "sender_user_id": 123,
                                        "content": "안녕하세요!",
                                        "is_read": "Y",
                                        "created_date": "2025-10-14T10:00:00",
                                    }
                                ],
                            },
                        }
                    }
                }
            },
        }
    },
    dependencies=[Depends(analysis_logger)],
)
async def get_chat_messages(
    room_id: int = Path(..., description="대화방 ID"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    count_per_page: int = Query(30, ge=1, le=100, description="페이지당 개수"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    특정 대화방의 메시지 조회
    - 시간 순으로 정렬
    - 조회 시 자동으로 읽음 처리
    """
    return await message_service.get_chat_messages(
        kc_user_id=user.get("sub"),
        room_id=room_id,
        page=page,
        count_per_page=count_per_page,
        db=db,
    )


@router.get(
    "/unread-count",
    tags=["채팅"],
    responses={
        200: {
            "description": "읽지 않은 채팅 개수 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "읽지 않은 채팅 개수",
                            "value": {"unreadCount": 5},
                        }
                    }
                }
            },
        }
    },
    dependencies=[Depends(analysis_logger)],
)
async def get_unread_chat_count(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    읽지 않은 채팅 개수 조회
    - 읽지 않은 메시지가 있는 대화방의 개수를 반환
    - 페이지네이션 없이 단순 카운트만 반환
    """
    return await message_service.get_unread_chat_count(
        kc_user_id=user.get("sub"),
        db=db,
    )
