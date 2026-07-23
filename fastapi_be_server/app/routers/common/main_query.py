from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_optional_cur_user_strict
import app.services.common.main_service as main_service
import app.services.product.main_character_slot_service as main_character_slot_service

router = APIRouter()


@router.get(
    "/products/main-character-slots",
    tags=["홈"],
    responses={200: {"description": "현재 노출 중인 메인 주인공 카드 목록"}},
    dependencies=[Depends(analysis_logger)],
)
async def get_main_character_slots(
    adult_yn: str = Query("N", description="성인등급 작품 포함 여부 (Y/N)"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await main_character_slot_service.get_public_main_character_slots(
        adult_yn=adult_yn,
        db=db,
    )


@router.get(
    "/products/character-chat-catalog",
    tags=["캐릭터챗"],
    responses={200: {"description": "현재 공개 가능한 캐릭터챗 전체 목록"}},
    dependencies=[Depends(analysis_logger)],
)
async def get_character_chat_catalog(
    adult_yn: str = Query("N", description="성인등급 작품 포함 여부 (Y/N)"),
    user: dict = Depends(chk_optional_cur_user_strict),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await main_character_slot_service.get_public_character_catalog(
        adult_yn=adult_yn,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.get(
    "/products/{product_id}/character-chat-preview",
    tags=["캐릭터챗"],
    responses={200: {"description": "선택 회차 기준 캐릭터 및 장면 미리보기"}},
    dependencies=[Depends(analysis_logger)],
)
async def get_character_chat_preview(
    product_id: int,
    character_scope_key: str = Query(..., min_length=1, max_length=80),
    episode_no: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await main_character_slot_service.get_public_character_chat_preview(
        product_id=product_id,
        character_scope_key=character_scope_key,
        episode_no=episode_no,
        db=db,
    )


@router.get(
    "/popup",
    tags=["홈"],
    responses={
        200: {
            "description": "현재 노출 중인 팝업 데이터 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_with_data": {
                            "summary": "현재 노출 중인 팝업이 있는 경우",
                            "value": {
                                "data": {
                                    "id": 1,
                                    "url": "https://www.likenovel.net/event/1",
                                    "imagePath": "https://cdn.likenovel.net/popup/image.webp",
                                }
                            },
                        },
                        "success_no_data": {
                            "summary": "현재 노출 중인 팝업이 없는 경우",
                            "value": {"data": None},
                        },
                    }
                }
            },
        },
        422: {
            "description": "Validation Error",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "UNPROCESSABLE_ENTITY",
                            "value": None,
                        }
                    }
                }
            },
        },
    },
    dependencies=[Depends(analysis_logger)],
)
async def get_popup(db: AsyncSession = Depends(get_likenovel_db)):
    """
    [팝업 조회 - 인증 불필요]
    현재 노출 중인 팝업 데이터를 조회합니다.

    - use_yn = 'Y'인 팝업만 조회
    """

    return await main_service.get_popup(db=db)
