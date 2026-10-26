from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.services.admin import admin_ai_model_service
from app.utils.auth import analysis_logger, chk_cur_user
from app.utils.common import check_user

router = APIRouter(prefix="/admins")


@router.get("/ai-models", tags=["CMS - AI 모델 관리"], dependencies=[Depends(analysis_logger)])
async def get_ai_models(
    db: AsyncSession = Depends(get_likenovel_db),
    user: dict[str, Any] = Depends(chk_cur_user),
):
    await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    return await admin_ai_model_service.get_admin_ai_models(db=db)
