from fastapi import APIRouter, Depends, Path, Body
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.content.message_service as message_service
import app.schemas.message as message_schema

router = APIRouter(prefix="/messages")


@router.post(
    "/chat-rooms",
    tags=["채팅"],
    responses={
        200: {
            "description": "대화방 생성",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "대화방 ID",
                            "value": {"data": {"roomId": 1}},
                        }
                    }
                }
            },
        }
    },
    dependencies=[Depends(analysis_logger)],
)
async def post_chat_room(
    req_body: message_schema.PostChatRoomReqBody = Body(...),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    대화방 생성
    - 항상 새로운 대화방 생성
    - default_message가 제공되면 첫 메시지 자동 전송
    """
    room_id = await message_service.get_or_create_chat_room(
        kc_user_id=user.get("sub"),
        target_user_id=req_body.target_user_id,
        db=db,
        default_message=req_body.default_message,
    )
    return {"data": {"roomId": room_id}}


@router.post(
    "/chat-rooms/{room_id}/messages",
    tags=["채팅"],
    responses={
        200: {
            "description": "메시지 전송",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "전송된 메시지",
                            "value": {
                                "data": {
                                    "messageId": 1,
                                    "roomId": 1,
                                    "senderUserId": 123,
                                    "content": "안녕하세요!",
                                    "isRead": "Y",
                                    "createdDate": "2025-10-14T10:00:00",
                                }
                            },
                        }
                    }
                }
            },
        }
    },
    dependencies=[Depends(analysis_logger)],
)
async def post_chat_message(
    room_id: int = Path(..., description="대화방 ID"),
    req_body: message_schema.PostChatMessageReqBody = Body(...),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    메시지 전송
    - 여러 줄로 메시지 전송 가능
    """
    message = await message_service.send_chat_message(
        kc_user_id=user.get("sub"),
        room_id=room_id,
        content=req_body.content,
        db=db,
    )
    return {"data": message}


@router.delete(
    "/chat-rooms/{room_id}",
    tags=["채팅"],
    responses={
        200: {
            "description": "채팅방 나가기",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "성공",
                            "value": {"data": {"success": True}},
                        }
                    }
                }
            },
        }
    },
    dependencies=[Depends(analysis_logger)],
)
async def delete_chat_room(
    room_id: int = Path(..., description="대화방 ID"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    채팅방 나가기
    - 나간 사용자는 더 이상 메시지를 볼 수 없음
    - 상대방이 메시지를 보내면 다시 대화방이 활성화됨
    """
    result = await message_service.leave_chat_room(
        kc_user_id=user.get("sub"),
        room_id=room_id,
        db=db,
    )
    return {"data": result}


@router.post(
    "/chat-rooms/{room_id}/report",
    tags=["채팅"],
    responses={
        200: {
            "description": "대화방 신고",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "성공",
                            "value": {"data": {"success": True}},
                        }
                    }
                }
            },
        }
    },
    dependencies=[Depends(analysis_logger)],
)
async def post_chat_room_report(
    room_id: int = Path(..., description="대화방 ID"),
    req_body: message_schema.PostChatMessageReportReqBody = Body(...),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    대화방 신고
    - 부적절한 대화방을 신고할 수 있음
    - 신고 사유 타입: threat_extortion(협박/갈취), fraud_impersonation(사기/사칭),
      spam_off_platform(반복적 메시지/플랫폼 외 협의), privacy_copyright(개인정보/저작권 침해),
      illegal_content(범죄/불법정보), spam_advertisement(스팸홍보/도배)
    """
    result = await message_service.report_chat_room(
        kc_user_id=user.get("sub"),
        room_id=room_id,
        req_body=req_body,
        db=db,
    )
    return {"data": result}
