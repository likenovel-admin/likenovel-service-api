from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.schemas.ai_model import PutAiModelRequest, ValidateAiModelRequest
from app.services.admin import admin_ai_model_service
from app.utils.auth import analysis_logger, chk_cur_user
from app.utils.common import check_user

router = APIRouter(prefix="/admins")


@router.post("/ai-models/validate", tags=["CMS - AI 모델 관리"], dependencies=[Depends(analysis_logger)])
async def validate_ai_model(
    req_body: ValidateAiModelRequest,
    db: AsyncSession = Depends(get_likenovel_db),
    user: dict[str, Any] = Depends(chk_cur_user),
):
    await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    return await admin_ai_model_service.validate_admin_ai_model(**req_body.model_dump())


@router.put("/ai-models/{feature_key}", tags=["CMS - AI 모델 관리"], dependencies=[Depends(analysis_logger)])
async def put_ai_model(
    feature_key: str,
    req_body: PutAiModelRequest,
    db: AsyncSession = Depends(get_likenovel_db),
    user: dict[str, Any] = Depends(chk_cur_user),
):
    admin = await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    return await admin_ai_model_service.put_admin_ai_model(
        feature_key=feature_key,
        **req_body.model_dump(),
        admin_user_id=admin.get("user_id"),
        db=db,
    )
