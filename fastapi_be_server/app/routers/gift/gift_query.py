from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.gift.gift_service as gift_service

router = APIRouter(prefix="/gifts")


@router.get("", tags=["선물함"], dependencies=[Depends(analysis_logger)])
async def get_gifts(
    category: str = Query(None, description="카테고리"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 구현 후 수정 및 최종 테스트 필**\n
    선물함 목록 출력
    """

    return await gift_service.get_gifts(
        category=category, kc_user_id=user.get("sub"), db=db
    )
