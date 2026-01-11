from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.ticket_item as ticket_item_schema
import app.schemas.user_ticketbook as user_ticketbook_schema
import app.schemas.user_productbook as user_productbook_schema
import app.services.common.ticket_item_service as ticket_item_service

router = APIRouter(prefix="/ticket-items")


@router.post("", tags=["이용권/대여권"], dependencies=[Depends(analysis_logger)])
async def post_ticket_item(
    req_body: ticket_item_schema.PostTicketItemReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    이용권/대여권 등록
    """

    return await ticket_item_service.post_ticket_item(
        req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put("/{id}", tags=["이용권/대여권"], dependencies=[Depends(analysis_logger)])
async def put_ticket_item(
    req_body: ticket_item_schema.PutTicketItemReqBody,
    id: int = Path(..., description="이용권/대여권 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    이용권/대여권 수정
    """

    return await ticket_item_service.put_ticket_item(
        id, req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put("/{id}", tags=["이용권/대여권"], dependencies=[Depends(analysis_logger)])
async def delete_ticket_item(
    id: int = Path(..., description="이용권/대여권 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    이용권/대여권 삭제
    """

    return await ticket_item_service.delete_ticket_item(
        id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{id}/issuance-ticketbook",
    tags=["이용권/대여권"],
    dependencies=[Depends(analysis_logger)],
)
async def issuance_ticketbook(
    req_body: user_ticketbook_schema.PostUserTicketbookReqBody,
    id: int = Path(..., description="이용권/대여권 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    이용권 발급
    """

    return await ticket_item_service.issuance_ticketbook(
        id, req_body, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{id}/issuance-productbook",
    tags=["이용권/대여권"],
    dependencies=[Depends(analysis_logger)],
)
async def issuance_productbook(
    req_body: user_productbook_schema.PostUserProductbookReqBody,
    id: int = Path(..., description="이용권/대여권 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    대여권 발급
    """

    return await ticket_item_service.issuance_productbook(
        id, req_body, kc_user_id=user.get("sub"), db=db
    )
