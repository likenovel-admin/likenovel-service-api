from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.event.quest_service as quest_service

router = APIRouter(prefix="/quests")


@router.put(
    "/{quest_id}/reward", tags=["퀘스트"], dependencies=[Depends(analysis_logger)]
)
async def update_quest_rewards_by_userid(
    quest_id: str = Path(..., description="퀘스트 아이디"),
    reward_id: str = Query(None, description="리워드 아이디"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    사용자별 퀘스트 보상 받기
    ㄴ reward_id : 검증용 리워드 아이디
    """

    return await quest_service.update_quest_rewards_by_userid(
        quest_id=quest_id, reward_id=reward_id, kc_user_id=user.get("sub"), db=db
    )
