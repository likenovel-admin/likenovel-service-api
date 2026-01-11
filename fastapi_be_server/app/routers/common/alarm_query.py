from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.common.alarm_service as alarm_service

router = APIRouter(prefix="/alarms")


@router.get("/unread", tags=["알림"], dependencies=[Depends(analysis_logger)])
async def get_alarms_unread(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 구현 후 수정 및 최종 테스트 필**\n
    읽지 않은 알림 목록 출력
    """

    return await alarm_service.get_alarms_unread(kc_user_id=user.get("sub"), db=db)
