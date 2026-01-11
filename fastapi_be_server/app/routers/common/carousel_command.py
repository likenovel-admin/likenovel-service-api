from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.carousel as carousel_schema
import app.services.common.carousel_service as carousel_service

router = APIRouter(prefix="/carousels")


@router.post("", tags=["캐러셀 배너"], dependencies=[Depends(analysis_logger)])
async def post_carousel(
    req_body: carousel_schema.PostCarouselBannerReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    캐러셀 배너 등록
    """

    return await carousel_service.post_carousel(
        req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put("/{id}", tags=["캐러셀 배너"], dependencies=[Depends(analysis_logger)])
async def put_carousel(
    req_body: carousel_schema.PutCarouselBannerReqBody,
    id: int = Path(..., description="캐러셀 배너 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    캐러셀 배너 수정
    """

    return await carousel_service.put_carousel(
        id, req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put("/{id}", tags=["캐러셀 배너"], dependencies=[Depends(analysis_logger)])
async def delete_carousel(
    id: int = Path(..., description="캐러셀 배너 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    캐러셀 배너 삭제
    """

    return await carousel_service.delete_carousel(id, kc_user_id=user.get("sub"), db=db)
