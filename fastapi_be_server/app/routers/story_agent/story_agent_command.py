from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.story_agent as story_agent_schema
import app.services.story_agent.story_agent_service as story_agent_service

router = APIRouter(prefix="/story-agent")


@router.post(
    "/sessions",
    tags=["스토리 에이전트"],
    dependencies=[Depends(analysis_logger)],
)
async def post_story_agent_session(
    req_body: story_agent_schema.PostStoryAgentSessionReqBody,
    adult_yn: str = "N",
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await story_agent_service.create_session(
        req_body=req_body,
        kc_user_id=user.get("sub"),
        adult_yn=adult_yn,
        db=db,
    )


@router.patch(
    "/sessions/{session_id}",
    tags=["스토리 에이전트"],
    dependencies=[Depends(analysis_logger)],
)
async def patch_story_agent_session(
    session_id: int,
    req_body: story_agent_schema.PatchStoryAgentSessionReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await story_agent_service.patch_session(
        session_id=session_id,
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.delete(
    "/sessions/{session_id}",
    tags=["스토리 에이전트"],
    dependencies=[Depends(analysis_logger)],
)
async def delete_story_agent_session(
    session_id: int,
    req_body: story_agent_schema.DeleteStoryAgentSessionReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await story_agent_service.delete_session(
        session_id=session_id,
        guest_key=req_body.guest_key,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.post(
    "/sessions/{session_id}/messages",
    tags=["스토리 에이전트"],
    dependencies=[Depends(analysis_logger)],
)
async def post_story_agent_message(
    session_id: int,
    req_body: story_agent_schema.PostStoryAgentMessageReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await story_agent_service.post_message(
        session_id=session_id,
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )
