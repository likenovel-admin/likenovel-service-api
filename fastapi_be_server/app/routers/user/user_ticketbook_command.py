from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.user_ticketbook as user_ticketbook_schema
import app.services.user.user_ticketbook_service as user_ticketbook_service

router = APIRouter(prefix="/user-ticketbook")


@router.post("", tags=["사용자 이용권"], dependencies=[Depends(analysis_logger)])
async def post_user_ticketbook(
    req_body: user_ticketbook_schema.PostUserTicketbookReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    사용자 이용권 등록
    """

    return await user_ticketbook_service.post_user_ticketbook(
        req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put("/{id}", tags=["사용자 이용권"], dependencies=[Depends(analysis_logger)])
async def put_user_ticketbook(
    req_body: user_ticketbook_schema.PutUserTicketbookReqBody,
    id: int = Path(..., description="사용자 이용권 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    사용자 이용권 수정
    """

    return await user_ticketbook_service.put_user_ticketbook(
        id, req_body, kc_user_id=user.get("sub"), db=db
    )


@router.delete("/{id}", tags=["사용자 이용권"], dependencies=[Depends(analysis_logger)])
async def delete_user_ticketbook(
    id: int = Path(..., description="사용자 이용권 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    사용자 이용권 삭제
    """

    return await user_ticketbook_service.delete_user_ticketbook(
        id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{id}/use", tags=["사용자 이용권"], dependencies=[Depends(analysis_logger)]
)
async def use_user_ticketbook(
    id: int = Path(..., description="사용자 이용권 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    사용자 이용권 사용
    """

    return await user_ticketbook_service.use_user_ticketbook(
        id, kc_user_id=user.get("sub"), db=db
    )
