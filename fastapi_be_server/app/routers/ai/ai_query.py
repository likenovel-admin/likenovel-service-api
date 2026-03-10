from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.ai.recommendation_service as recommendation_service
import app.services.ai.ai_chat_service as ai_chat_service
from app.const import LOGGER_TYPE, ErrorMessages
from app.config.log_config import service_error_logger
from app.exceptions import CustomResponseException

router = APIRouter(prefix="/ai")

error_logger = service_error_logger(LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_ERROR)


@router.get(
    "/taste-profile",
    tags=["AI 추천"],
    responses={200: {"description": "내 취향 프로파일 조회"}},
    dependencies=[Depends(analysis_logger)],
)
async def get_taste_profile(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    kc_user_id = user.get("sub")
    if not kc_user_id:
        return {"data": {"has_profile": False}}
    dashboard = await recommendation_service.get_taste_dashboard(kc_user_id, db)
    return {"data": dashboard}


@router.get(
    "/taste-profile/recommendations",
    tags=["AI 추천"],
    responses={200: {"description": "취향 기반 추천 섹션 (메인 페이지용)"}},
    dependencies=[Depends(analysis_logger)],
)
async def get_taste_recommendations(
    adult_yn: str = Query("N", description="성인등급 작품 포함 여부"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    kc_user_id = user.get("sub")
    if not kc_user_id:
        return {"data": {"sections": [], "needs_onboarding": False}}
    result = await recommendation_service.get_taste_recommendations(kc_user_id, adult_yn, db)
    return {"data": result}


@router.get(
    "/onboarding-products",
    tags=["AI 추천"],
    responses={200: {"description": "온보딩 유명작 목록"}},
    dependencies=[Depends(analysis_logger)],
)
async def get_onboarding_products(
    adult_yn: str = Query("N", description="성인등급 작품 포함 여부"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    products = await recommendation_service.get_onboarding_products(db, adult_yn=adult_yn)
    tag_tabs = await recommendation_service.get_curated_onboarding_tag_tabs(
        db,
        adult_yn=adult_yn,
        default_top_n=10,
    )
    return {"data": products, "tag_tabs": tag_tabs}


@router.get(
    "/product-metadata/{product_id}",
    tags=["AI 추천"],
    responses={200: {"description": "작품 AI DNA 메타데이터 조회"}},
    dependencies=[Depends(analysis_logger)],
)
async def get_product_ai_metadata(
    product_id: int,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    kc_user_id = user.get("sub")
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )
    metadata = await recommendation_service.get_product_ai_metadata(product_id, db)
    return {"data": metadata}


@router.get(
    "/chat/history",
    tags=["AI 추천"],
    responses={200: {"description": "AI 챗 히스토리 조회"}},
    dependencies=[Depends(analysis_logger)],
)
async def get_ai_chat_history(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    kc_user_id = user.get("sub")
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )
    messages = await ai_chat_service.get_chat_history(
        kc_user_id=kc_user_id, db=db
    )
    return {"data": messages}
