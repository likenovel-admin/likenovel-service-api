from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.content.support_service as support_service

router = APIRouter(prefix="/support")


@router.post("/qnas", tags=["고객지원"], dependencies=[Depends(analysis_logger)])
async def post_support_qnas(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 구현 후 수정 및 최종 테스트 필**\n
    1:1 문의하기 버튼
    """

    return await support_service.post_support_qnas(kc_user_id=user.get("sub"), db=db)
