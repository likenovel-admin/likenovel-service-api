from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger
import app.services.common.banner_service as banner_service
from app.exceptions import CustomResponseException
from app.const import ErrorMessages

router = APIRouter(prefix="/banners")


@router.get(
    "/{division}",
    tags=["배너 - 조회"],
    responses={
        200: {
            "description": "영역별 배너 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "메인(main)영역 배너 조회",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "division": "main",
                                        "area": "primaryPanel",
                                        "pcImgPath": "https://cdn.likenovel.dev/panel/prim/pc/1/main_img01.webp",
                                        "mobileImgPath": "https://cdn.likenovel.dev/panel/prim/mobile/1/m_main_img01.webp",
                                        "textType": "char",
                                        "topText": "Event",
                                        "middleText": "퀸의 대각선 세트\\n단독 특별판!",
                                        "bottomText": "퀸의 대각선 1-2세트(전2권)\\n라이크노벨 단독 특별판",
                                        "textImgPath": "",
                                        "mobileTextImgPath": "",
                                        "textPosition": "leftTop",
                                        "overlayYn": "N",
                                        "overlayType": "",
                                        "overlayImgPath": "",
                                        "mobileOverlayImgPath": "",
                                        "linkPath": "https://www.likenovel.dev/",
                                    },
                                    {
                                        "id": 2,
                                        "division": "main",
                                        "area": "primaryPanel",
                                        "pcImgPath": "https://cdn.likenovel.dev/panel/prim/pc/2/샘플(900_400)2.webp",
                                        "mobileImgPath": "https://cdn.likenovel.dev/panel/prim/mobile/2/샘플(900_400)2.webp",
                                        "textType": "img",
                                        "topText": "",
                                        "middleText": "",
                                        "bottomText": "",
                                        "textImgPath": "https://cdn.likenovel.dev/panel/prim/pc/2/text/logoSample.webp",
                                        "mobileTextImgPath": "https://cdn.likenovel.dev/panel/prim/mobile/2/text/logoSample.webp",
                                        "textPosition": "leftTop",
                                        "overlayYn": "Y",
                                        "overlayType": "gradation",
                                        "overlayImgPath": "https://cdn.likenovel.dev/panel/prim/pc/2/overlay/redGradation.webp",
                                        "mobileOverlayImgPath": "https://cdn.likenovel.dev/panel/prim/mobile/2/overlay/redGradation.webp",
                                        "linkPath": "https://www.likenovel.dev/",
                                    },
                                    {
                                        "id": 3,
                                        "division": "main",
                                        "area": "primaryPanel",
                                        "pcImgPath": "https://cdn.likenovel.dev/panel/prim/pc/3/샘플1.webp",
                                        "mobileImgPath": "https://cdn.likenovel.dev/panel/prim/mobile/3/샘플1.webp",
                                        "textType": "img",
                                        "topText": "",
                                        "middleText": "",
                                        "bottomText": "",
                                        "textImgPath": "https://cdn.likenovel.dev/panel/prim/pc/3/text/샘플3.webp",
                                        "mobileTextImgPath": "https://cdn.likenovel.dev/panel/prim/mobile/3/text/샘플3.webp",
                                        "textPosition": "leftTop",
                                        "overlayYn": "Y",
                                        "overlayType": "img",
                                        "overlayImgPath": "https://cdn.likenovel.dev/panel/prim/pc/3/overlay/샘플2.webp",
                                        "mobileOverlayImgPath": "https://cdn.likenovel.dev/panel/prim/mobile/3/overlay/샘플2.webp",
                                        "linkPath": "https://www.likenovel.dev/",
                                    },
                                    {
                                        "id": 4,
                                        "division": "main",
                                        "area": "secondaryPanel",
                                        "pcImgPath": "https://cdn.likenovel.dev/panel/scnd/pc/4/pc_banner.webp",
                                        "mobileImgPath": "https://cdn.likenovel.dev/panel/scnd/mobile/4/pc_banner.webp",
                                        "textType": "",
                                        "topText": "",
                                        "middleText": "",
                                        "bottomText": "",
                                        "textImgPath": "",
                                        "mobileTextImgPath": "",
                                        "textPosition": "",
                                        "overlayYn": "",
                                        "overlayType": "",
                                        "overlayImgPath": "",
                                        "mobileOverlayImgPath": "",
                                        "linkPath": "https://www.likenovel.dev/",
                                    },
                                    {
                                        "id": 5,
                                        "division": "main",
                                        "area": "thirdPanel",
                                        "pcImgPath": "https://cdn.likenovel.dev/panel/thrd/pc/5/pc_hanner02_1.webp",
                                        "mobileImgPath": "https://cdn.likenovel.dev/panel/thrd/mobile/5/pc_hanner02_1.webp",
                                        "textType": "",
                                        "topText": "",
                                        "middleText": "",
                                        "bottomText": "",
                                        "textImgPath": "",
                                        "mobileTextImgPath": "",
                                        "textPosition": "",
                                        "overlayYn": "",
                                        "overlayType": "",
                                        "overlayImgPath": "",
                                        "mobileOverlayImgPath": "",
                                        "linkPath": "https://www.likenovel.dev/",
                                    },
                                ]
                            },
                        }
                    }
                }
            },
        },
        422: {
            "description": "Validation Error",
            "content": {
                "application/json": {
                    "examples": {
                        "unprocessable_entity": {
                            "summary": "UNPROCESSABLE_ENTITY",
                            "value": {},
                        }
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "examples": {
                        "internal_server_error": {
                            "summary": "INTERNAL_SERVER_ERROR",
                            "value": {},
                        }
                    }
                }
            },
        },
    },
    dependencies=[Depends(analysis_logger)],
)
async def banners_by_division(
    division: str = Path(
        ..., description="배너 영역 구분값(main, paid, promotion, search)"
    ),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    영역별 배너 조회
    """
    try:
        return await banner_service.banners_by_division(division=division, db=db)
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )
