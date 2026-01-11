from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.common.alarm_service as alarm_service

router = APIRouter(prefix="/alarms")


@router.put("/mark-as-read", tags=["알림"], dependencies=[Depends(analysis_logger)])
async def put_alarms_mark_as_read(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 구현 후 수정 및 최종 테스트 필**\n
    모두 읽음 처리 버튼
    """

    return await alarm_service.put_alarms_mark_as_read(
        kc_user_id=user.get("sub"), db=db
    )


# TODO: 알림 관련 도메인 구현 시 아래 내용 포함 필
# @router.post("/{product_id}/reader-alarm", tags=["알림"],
#             dependencies=[Depends(analysis_logger)])
# async def post_products_product_id_reader_alarm(product_id: str = Path(..., description="작품 id"),
#                                                user: Dict[str, Any] = Depends(chk_cur_user), db: AsyncSession = Depends(get_likenovel_db)):
#    """
#    작품 독자알림 버튼
#    (글쓰기 작품 만들기 회차관리)
#    """
#
#    return await product_service.post_products_product_id_reader_alarm(product_id=product_id, kc_user_id=user.get("sub"), db=db)
