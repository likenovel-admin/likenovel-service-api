from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.content.support_service as support_service

router = APIRouter(prefix="/support")


@router.post("/qnas", tags=["고객지원"], dependencies=[Depends(analysis_logger)])
async def post_support_qnas(
    req_body: support_schema.PostSupportQnaReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """로그인 사용자의 1:1 문의를 접수한다."""

    return await support_service.post_support_qnas(
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )
