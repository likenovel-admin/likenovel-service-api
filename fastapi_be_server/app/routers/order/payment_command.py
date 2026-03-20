from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.payment as payment_schema
import app.services.order.payment_service as payment_service

router = APIRouter(prefix="/payments")


@router.post(
    "/virtual-account/issued",
    tags=["결제 - 가상계좌 발급"],
    dependencies=[Depends(analysis_logger)],
)
async def payment_virtual_account_issued(
    req_body: payment_schema.VirtualAccountIssuedReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await payment_service.payment_virtual_account_issued(
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.post("/webhook", tags=["결제 - 포트원 웹훅"])
async def payment_receive_webhook(
    request: Request,
    body: bytes = Depends(payment_service.get_raw_body),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await payment_service.payment_receive_webhook(
        request=request,
        body=body,
        db=db,
    )


@router.post(
    "/verify-virtual-account",
    tags=["결제 - 가상계좌 입금확인"],
    dependencies=[Depends(analysis_logger)],
)
async def payment_verify_virtual_account(
    req_body: payment_schema.VirtualAccountReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    가상계좌 입금 확인 처리
    """

    return await payment_service.payment_verify_virtual_account(
        req_body=req_body, user_id=user.get("sub"), db=db
    )
