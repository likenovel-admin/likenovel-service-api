from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.order as order_schema
import app.services.order.order_service as order_service

router = APIRouter(prefix="/orders")


@router.post("/complete", tags=["주문"], dependencies=[Depends(analysis_logger)])
async def order_cash_payment_complete_with_payment_id(
    req_body: order_schema.OrderCashReqBody,
    # , payment_id: Annotated[str, Body(embed=True, alias="paymentId")]
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    캐시 결제 완료 처리
    """

    return await order_service.order_cash_payment_complete_with_payment_id(
        req_body=req_body, kc_user_id=user.get("sub"), db=db
    )
