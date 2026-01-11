from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.partner as partner_schema
import app.schemas.auth as auth_schema
import app.services.partner.partner_product_service as partner_product_service
import app.services.partner.partner_sales_service as partner_sales_service
import app.services.partner.partner_income_service as partner_income_service
import app.services.auth.auth_service as auth_service
from app.utils.common import check_user

router = APIRouter(prefix="/partners")


@router.post("/login", tags=["파트너"], dependencies=[Depends(analysis_logger)])
async def login_partner(
    req_body: auth_schema.SigninReqBody, db: AsyncSession = Depends(get_likenovel_db)
):
    """
    파트너 로그인
    """

    return await auth_service.post_auth_signin(
        req_body=req_body, db=db, call_from="partner"
    )


@router.put(
    "/products/{id}", tags=["파트너 - 작품"], dependencies=[Depends(analysis_logger)]
)
async def put_product(
    req_body: partner_schema.PutProductReqBody,
    id: int = Path(..., description="작품 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 작품 관리 / 작품 리스트
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_product_service.put_product(req_body, id, db=db)


@router.delete(
    "/products/{id}", tags=["파트너 - 작품"], dependencies=[Depends(analysis_logger)]
)
async def delete_product(
    id: int = Path(..., description="작품 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 작품 관리 / 작품 리스트
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_product_service.delete_product(id, db=db)


@router.put(
    "/monthly-sales-by-product/{id}",
    tags=["파트너 - 작품별 월매출"],
    dependencies=[Depends(analysis_logger)],
)
async def put_monthly_sales_by_product(
    req_body: partner_schema.PutPtnProductSalesReqBody,
    id: int = Path(..., description="작품 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 작품별 월매출
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_sales_service.put_monthly_sales_by_product(req_body, id, db=db)


@router.post(
    "/sponsorship-recodes/{id}/settlement",
    tags=["파트너 - 후원 내역"],
    dependencies=[Depends(analysis_logger)],
)
async def settlement_sponsorship_recodes(
    id: int = Path(..., description="작품 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 후원 내역 정산
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_income_service.settlement_sponsorship_recodes(id, db=db)
