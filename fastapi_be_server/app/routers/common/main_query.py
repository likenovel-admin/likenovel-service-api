from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger
import app.services.common.main_service as main_service

router = APIRouter()


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
