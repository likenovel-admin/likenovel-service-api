from typing import Any, Dict

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.websochat.websochat_service as websochat_service

router = APIRouter(prefix="/websochat")


def get_websochat_guest_key(
    guest_key: str | None = Header(default=None, alias="X-Websochat-Guest-Key"),
    legacy_guest_key: str | None = Header(default=None, alias="X-Story-Agent-Guest-Key"),
) -> str | None:
    return guest_key or legacy_guest_key


@router.get(
    "/products",
    tags=["웹소챗"],
    dependencies=[Depends(analysis_logger)],
)
async def get_websochat_products(
    keyword: str = Query(..., description="작품명/작가명 검색어"),
    adult_yn: str = Query("N", description="성인 작품 포함 여부"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await websochat_service.search_products(
        keyword=keyword,
        kc_user_id=user.get("sub"),
        adult_yn=adult_yn,
        db=db,
    )


@router.get(
    "/sessions",
    tags=["웹소챗"],
    dependencies=[Depends(analysis_logger)],
)
async def get_websochat_sessions(
    product_id: int | None = Query(default=None),
    guest_key: str | None = Depends(get_websochat_guest_key),
    adult_yn: str = Query("N"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await websochat_service.get_sessions(
        kc_user_id=user.get("sub"),
        guest_key=guest_key,
        product_id=product_id,
        adult_yn=adult_yn,
        db=db,
    )


@router.get(
    "/billing-status",
    tags=["웹소챗"],
    dependencies=[Depends(analysis_logger)],
)
async def get_websochat_billing_status(
    qa_action_key: str | None = Query(default=None),
    guest_key: str | None = Depends(get_websochat_guest_key),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await websochat_service.get_billing_status(
        kc_user_id=user.get("sub"),
        guest_key=guest_key,
        qa_action_key=qa_action_key,
        db=db,
    )


@router.get(
    "/sessions/{session_id}/messages",
    tags=["웹소챗"],
    dependencies=[Depends(analysis_logger)],
)
async def get_websochat_messages(
    session_id: int,
    guest_key: str | None = Depends(get_websochat_guest_key),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await websochat_service.get_messages(
        session_id=session_id,
        kc_user_id=user.get("sub"),
        guest_key=guest_key,
        db=db,
    )
