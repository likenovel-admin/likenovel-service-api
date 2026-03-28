from typing import Any, Dict

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.story_agent.story_agent_service as story_agent_service

router = APIRouter(prefix="/story-agent")


@router.get(
    "/products",
    tags=["스토리 에이전트"],
    dependencies=[Depends(analysis_logger)],
)
async def get_story_agent_products(
    keyword: str = Query(..., description="작품명/작가명 검색어"),
    adult_yn: str = Query("N", description="성인 작품 포함 여부"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await story_agent_service.search_products(
        keyword=keyword,
        kc_user_id=user.get("sub"),
        adult_yn=adult_yn,
        db=db,
    )


@router.get(
    "/sessions",
    tags=["스토리 에이전트"],
    dependencies=[Depends(analysis_logger)],
)
async def get_story_agent_sessions(
    product_id: int | None = Query(default=None),
    guest_key: str | None = Header(default=None, alias="X-Story-Agent-Guest-Key"),
    adult_yn: str = Query("N"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await story_agent_service.get_sessions(
        kc_user_id=user.get("sub"),
        guest_key=guest_key,
        product_id=product_id,
        adult_yn=adult_yn,
        db=db,
    )


@router.get(
    "/sessions/{session_id}/messages",
    tags=["스토리 에이전트"],
    dependencies=[Depends(analysis_logger)],
)
async def get_story_agent_messages(
    session_id: int,
    guest_key: str | None = Header(default=None, alias="X-Story-Agent-Guest-Key"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await story_agent_service.get_messages(
        session_id=session_id,
        kc_user_id=user.get("sub"),
        guest_key=guest_key,
        db=db,
    )
