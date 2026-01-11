from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.publisher_promotion as publisher_promotion_schema
import app.services.common.publisher_promotion_service as publisher_promotion_service

router = APIRouter(prefix="/publisher-promotions")


@router.post("", tags=["출판사 프로모션"], dependencies=[Depends(analysis_logger)])
async def post_publisher_promotion(
    req_body: publisher_promotion_schema.PostPublisherPromotionReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    출판사 프로모션 등록
    """

    return await publisher_promotion_service.post_publisher_promotion(
        req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put("/{id}", tags=["출판사 프로모션"], dependencies=[Depends(analysis_logger)])
async def put_publisher_promotion(
    req_body: publisher_promotion_schema.PutPublisherPromotionReqBody,
    id: int = Path(..., description="출판사 프로모션 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    출판사 프로모션 수정
    """

    return await publisher_promotion_service.put_publisher_promotion(
        id, req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put("/{id}", tags=["출판사 프로모션"], dependencies=[Depends(analysis_logger)])
async def delete_publisher_promotion(
    id: int = Path(..., description="출판사 프로모션 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    출판사 프로모션 삭제
    """

    return await publisher_promotion_service.delete_publisher_promotion(
        id, kc_user_id=user.get("sub"), db=db
    )
