from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.user_productbook as user_productbook_schema
import app.services.user.user_productbook_service as user_productbook_service

router = APIRouter(prefix="/user-productbook")


@router.post(
    "/{id}/use", tags=["사용자 대여권"], dependencies=[Depends(analysis_logger)]
)
async def use_user_productbook(
    req_body: user_productbook_schema.UseUserProductbookReqBody,
    id: int = Path(..., description="사용자 대여권 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    사용자 대여권 사용

    Args:
        id: 대여권 ID
        req_body: episode_id를 포함한 요청 본문
    """

    return await user_productbook_service.use_user_productbook(
        id, req_body.episode_id, kc_user_id=user.get("sub"), db=db
    )
