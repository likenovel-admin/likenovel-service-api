from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.ai.recommendation_service as recommendation_service
import app.services.ai.ai_chat_service as ai_chat_service
import app.schemas.ai_recommendation as ai_schema
from app.const import LOGGER_TYPE, ErrorMessages
from app.config.log_config import service_error_logger
from app.exceptions import CustomResponseException
from fastapi import status

router = APIRouter(prefix="/ai")

error_logger = service_error_logger(LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_ERROR)


@router.post(
    "/taste-profile/onboarding",
    tags=["AI 추천"],
    responses={200: {"description": "온보딩 선택 저장 + 프로파일 생성"}},
    dependencies=[Depends(analysis_logger)],
)
async def post_onboarding(
    req_body: ai_schema.PostOnboardingReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    kc_user_id = user.get("sub")
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )
    result = await recommendation_service.process_onboarding(
        kc_user_id,
        req_body.product_ids,
        req_body.moods,
        req_body.hero_tags,
        req_body.world_tone_tags,
        req_body.relation_tags,
        req_body.adult_yn,
        db,
    )
    return {"data": result}


@router.post(
    "/taste-profile/onboarding-dismiss",
    tags=["AI 추천"],
    responses={200: {"description": "온보딩 모달 숨김 처리(계정 기준)"}},
    dependencies=[Depends(analysis_logger)],
)
async def post_onboarding_dismiss(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    kc_user_id = user.get("sub")
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )
    result = await recommendation_service.dismiss_onboarding(kc_user_id, db)
    return {"data": result}


@router.post(
    "/signal-events",
    tags=["AI 추천"],
    responses={200: {"description": "AI 추천용 행동 신호 이벤트 적재"}},
    dependencies=[Depends(analysis_logger)],
)
async def post_ai_signal_events(
    req_body: ai_schema.PostAiSignalEventReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    kc_user_id = user.get("sub")
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )
    result = await recommendation_service.post_signal_event(
        kc_user_id,
        req_body.model_dump(),
        db,
    )
    return {"data": result}


@router.post(
    "/recommend",
    tags=["AI 추천"],
    responses={200: {"description": "AI 챗 추천 (프리셋/자유입력)"}},
    dependencies=[Depends(analysis_logger)],
)
async def post_ai_recommend(
    req_body: ai_schema.PostAiRecommendReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    kc_user_id = user.get("sub")
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    result = await recommendation_service.ai_recommend(
        kc_user_id,
        req_body.query,
        req_body.preset,
        req_body.exclude_product_ids,
        req_body.adult_yn,
        db,
    )
    return {"data": result}


@router.post(
    "/chat",
    tags=["AI 추천"],
    responses={200: {"description": "AI 챗 멀티턴 추천(최소 구현)"}},
    dependencies=[Depends(analysis_logger)],
)
async def post_ai_chat(
    req_body: ai_schema.PostAiChatReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    kc_user_id = user.get("sub")
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    result = await ai_chat_service.handle_chat(
        kc_user_id=kc_user_id,
        messages=[message.model_dump() for message in req_body.messages],
        context=req_body.context.model_dump(),
        preset=req_body.preset,
        exclude_ids=req_body.exclude_product_ids,
        adult_yn=req_body.adult_yn,
        db=db,
    )

    # 채팅 히스토리 저장 (브라우징 트리거 자동 메시지는 유저 메시지로 저장하지 않음)
    last_user_content = None
    is_browsing = req_body.context.trigger == "browsing"
    if req_body.messages and not is_browsing:
        last_msg = req_body.messages[-1]
        if last_msg.role == "user":
            last_user_content = last_msg.content
    try:
        await ai_chat_service.save_chat_messages(
            kc_user_id=kc_user_id,
            user_content=last_user_content,
            assistant_result=result,
            db=db,
        )
    except Exception as e:
        error_logger.error(f"Failed to save chat history: {e}")

    return {"data": result}


@router.delete(
    "/chat/history",
    tags=["AI 추천"],
    responses={200: {"description": "AI 챗 히스토리 전체 삭제"}},
    dependencies=[Depends(analysis_logger)],
)
async def delete_ai_chat_history(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    kc_user_id = user.get("sub")
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )
    await ai_chat_service.clear_chat_history(kc_user_id=kc_user_id, db=db)
    return {"data": {"message": "ok"}}
