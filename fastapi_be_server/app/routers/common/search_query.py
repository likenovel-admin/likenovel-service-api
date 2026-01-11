from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.config.log_config import (
    analysis_logger,
    service_data_logger,
    service_error_logger,
)
from app.const import LOGGER_TYPE
from app.utils.auth import chk_cur_user
from typing import Dict, Any, Optional
from app.exceptions import CustomResponseException
from app.const import ErrorMessages

import app.services.common.search_service as search_service


router = APIRouter(prefix="/search")
error_logger = service_error_logger(LOGGER_TYPE.LOGGER_INSTANCE_NAME_FOR_SERVICE_ERROR)


@router.get(
    "",
    tags=["통합검색 - 일반"],
    responses={
        200: {
            "description": "일반 통합검색",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "일반 통합검색",
                            "value": {
                                "data": {
                                    "products": [
                                        {
                                            "productId": 15,
                                            "title": "세계전복급 악역으로 오해 받고 있습니다",
                                            "genre": ["무협", "판타지"],
                                            "keywords": ["키워드1, 키워드2, 키워드3"],
                                            "image": {
                                                "coverImgPath": "https://cdn.likenovel.dev/cover/1/image.webp",
                                                "adultDefaultcoverImgPath": "https://cdn.likenovel.dev/cover/adult_default.webp",
                                            },
                                            "badge": {
                                                "waitForFreeYn": "Y",
                                                "episodeUploadYn": "Y",
                                                "timepassFromTo": "6-1",
                                                "authorLevelBadgeImgPath": "https://cdn.likenovel.dev/badge/level/1.webp",
                                                "authorInterestBadgeImgPath": "https://cdn.likenovel.dev/badge/interest/off.webp",
                                            },
                                        }
                                    ],
                                    "events": [
                                        {
                                            "eventId": 4,
                                            "eventType": "VOTE",
                                            "roundNo": 1,
                                            "bannerImage": "https://cdn.likenovel.dev/panel/prim/pc/1/main_img01.webp",
                                            "subject": "(마감임박) 신작챌린지 2024",
                                            "content": "작품에 투표하세요",
                                            "closeYn": "N",
                                            "beginDate": "2024-08-01T16:00:00",
                                            "endDate": "2024-08-01T16:00:00",
                                            "createdDate": "2024-08-01T16:00:00",
                                            "updatedDate": "2024-08-01T16:00:00",
                                        },
                                    ],
                                    "quests": [
                                        {
                                            "questId": 4,
                                            "title": "본인인증하기 / 대여권 1장",
                                            "rewardId": 1,
                                            "useYn": "Y",
                                            "endDate": "2024-12-01T16:00:00",
                                            "createdDate": "2024-08-01T16:00:00",
                                            "updatedDate": "2024-08-01T16:00:00",
                                            "maximumTickets": 3,
                                        },
                                    ],
                                }
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
async def products_of_searched(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
    keyword: str = Query(None, description="검색 키워드"),
    adult_yn: str = Query(None, description="통합검색(일반검색-작품, 퀘스트, 이벤트)"),
    orderby: str = Query(None, description="정렬 기준"),
    page: int = Query(1, description="조회 시작 위치"),
    limit: int = Query(10, description="한페이지 조회 개수"),
):
    """
    통합검색(일반검색-작품, 퀘스트, 이벤트)
    """

    return await search_service.products_of_searched(
        kc_user_id=user.get("sub"),
        db=db,
        adult_yn=adult_yn,
        keyword=keyword,
        page=page,
        limit=limit,
        orderby=orderby,
    )


@router.get(
    "/autocomplete",
    tags=["통합검색 - 자동완성 키워드"],
    responses={
        200: {
            "description": "통합검색 - 자동완성 키워드",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "통합검색 - 자동완성 키워드",
                            "value": {},
                        }
                    }
                }
            },
        }
    },
    dependencies=[Depends(analysis_logger)],
)
async def results_of_autocomplete(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
    keyword: str = Query(None, description="검색 키워드"),
    adult_yn: str = Query(None, description="통합검색(일반검색-작품, 퀘스트, 이벤트)"),
):
    """
    일반 통합검색 자동완성 키워드
    """
    return await search_service.results_of_autocomplete(
        kc_user_id=user.get("sub"), db=db, keyword=keyword, adult_yn=adult_yn
    )


@router.post(
    "/story",
    tags=["통합검색 - 스토리 검색"],
    responses={
        200: {
            "description": "스토리 검색",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "스토리 검색", "value": {}}}
                }
            },
        }
    },
    dependencies=[Depends(analysis_logger)],
)
async def products_of_search_by_story(
    story: str = Query(None, description="스토리"),
    adult_yn: str = Query(None, description="통합검색 - 스토리 검색"),
):
    """
    스토리 검색
    """
    return await search_service.products_of_search_by_story(
        story=story, adult_yn=adult_yn
    )


@router.get(
    "/trending-keywords",
    tags=["통합검색 - 인기 키워드"],
    responses={
        200: {
            "description": "인기 키워드",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "인기 키워드", "value": {}}}
                }
            },
        }
    },
    dependencies=[Depends(service_data_logger)],
)
async def get_trending_keywords(user: Dict[str, Any] = Depends(chk_cur_user)):
    """
    인기 키워드
    """
    trending_keywords = {}
    try:
        trending_keywords = await search_service.get_trending_keywords()
    except Exception as e:
        error_logger.error(f"user: {user} - {e}")
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.SEARCH_SERVICE_ERROR,
        )

    return trending_keywords


@router.get(
    "/weekly-most-searched",
    tags=["통합검색 - 금주 최다 검색 작품"],
    responses={
        200: {
            "description": "금주 최다 검색 작품",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "금주 최다 검색 작품",
                            "value": {
                                "data": [
                                    {
                                        "productId": 15,
                                        "title": "세계전복급 악역으로 오해 받고 있습니다",
                                        "genre": ["무협", "판타지"],
                                        "keywords": ["키워드1, 키워드2, 키워드3"],
                                        "weeklyHits": 1234,
                                        "image": {
                                            "coverImgPath": "https://cdn.likenovel.dev/cover/1/image.webp",
                                            "adultDefaultcoverImgPath": "https://cdn.likenovel.dev/cover/adult_default.webp",
                                        },
                                        "badge": {
                                            "waitForFreeYn": "Y",
                                            "episodeUploadYn": "Y",
                                            "timepassFromTo": "6-1",
                                            "authorLevelBadgeImgPath": "https://cdn.likenovel.dev/badge/level/1.webp",
                                            "authorInterestBadgeImgPath": "https://cdn.likenovel.dev/badge/interest/off.webp",
                                        },
                                    }
                                ],
                                "totalCount": 100,
                                "pageSize": 10,
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
async def get_weekly_most_viewed_products(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
    adult_yn: str = Query("N", description="성인 작품 포함 여부 (Y/N)"),
    page: int = Query(1, description="조회 페이지"),
    limit: int = Query(10, description="한 페이지당 조회 개수"),
):
    """
    금주의 최다 검색 작품 목록 조회
    최근 7일간 조회수가 가장 많은 작품을 반환
    """
    return await search_service.get_weekly_most_viewed_products(
        kc_user_id=user.get("sub"),
        db=db,
        adult_yn=adult_yn,
        page=page,
        limit=limit,
    )


@router.get(
    "/products-for-review",
    tags=["통합검색 - 리뷰 작성용 작품 검색"],
    responses={
        200: {
            "description": "리뷰 작성용 작품 검색",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "리뷰 작성용 작품 검색",
                            "value": {
                                "data": [
                                    {
                                        "productId": 15,
                                        "title": "세계전복급 악역으로 오해 받고 있습니다",
                                        "genre": ["무협", "판타지"],
                                        "keywords": ["키워드1, 키워드2, 키워드3"],
                                        "image": {
                                            "coverImgPath": "https://cdn.likenovel.dev/cover/1/image.webp",
                                            "adultDefaultcoverImgPath": "https://cdn.likenovel.dev/cover/adult_default.webp",
                                        },
                                        "badge": {
                                            "waitForFreeYn": "Y",
                                            "episodeUploadYn": "Y",
                                            "timepassFromTo": "6-1",
                                            "authorLevelBadgeImgPath": "https://cdn.likenovel.dev/badge/level/1.webp",
                                            "authorInterestBadgeImgPath": "https://cdn.likenovel.dev/badge/interest/off.webp",
                                        },
                                    }
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
async def search_products_for_review(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
    keyword: str = Query(..., description="검색 키워드 (작품명, 작가명)"),
    adult_yn: str = Query("N", description="성인 작품 포함 여부 (Y/N)"),
    limit: Optional[int] = Query(None, description="조회 개수"),
):
    """
    리뷰 작성용 작품 검색
    작품명, 작가명으로 검색하여 작품 목록 반환
    """
    return await search_service.search_products_for_review(
        kc_user_id=user.get("sub"),
        db=db,
        keyword=keyword,
        adult_yn=adult_yn,
        limit=limit,
    )
