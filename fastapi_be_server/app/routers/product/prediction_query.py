from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.product.prediction_service as prediction_service

router = APIRouter(prefix="/predictions")


@router.get(
    "/author-episode/accuracy",
    tags=["작품 - 예측"],
    dependencies=[Depends(analysis_logger)],
)
async def get_author_episode_prediction_accuracy(
    days: int = Query(30, description="조회 기간(일)"),
    product_id: Optional[int] = Query(None, description="작품 ID"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await prediction_service.get_author_episode_prediction_accuracy(
        days=days,
        product_id=product_id,
        kc_user_id=user.get("sub"),
        db=db,
    )
