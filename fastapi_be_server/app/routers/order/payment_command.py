from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.payment as payment_schema
import app.services.order.payment_service as payment_service

router = APIRouter(prefix="/payments")


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
