from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.gift.gift_service as gift_service

router = APIRouter(prefix="/gifts")


@router.put(
    "/{gift_id}/collection", tags=["선물함"], dependencies=[Depends(analysis_logger)]
)
async def put_gifts_gift_id_collection(
    gift_id: str = Path(..., description="선물 아이디"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 구현 후 수정 및 최종 테스트 필**\n
    선물 받기 버튼
    """

    return await gift_service.put_gifts_gift_id_collection(
        gift_id=gift_id, kc_user_id=user.get("sub"), db=db
    )
