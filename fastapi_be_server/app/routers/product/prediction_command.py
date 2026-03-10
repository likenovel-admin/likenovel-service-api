from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.prediction as prediction_schema
import app.services.product.prediction_service as prediction_service

router = APIRouter(prefix="/predictions")


@router.post(
    "/author-episode",
    tags=["작품 - 예측"],
    dependencies=[Depends(analysis_logger)],
)
async def post_author_episode_prediction(
    req_body: prediction_schema.PostAuthorEpisodePredictionReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await prediction_service.post_author_episode_prediction(
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )
