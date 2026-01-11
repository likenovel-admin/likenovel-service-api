from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, List, Optional

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.product.product_service as product_service
import app.services.product.product_comment_service as product_comment_service
import app.services.product.product_bookmark_service as product_bookmark_service
import app.services.product.product_notice_service as product_notice_service
from app.const import LOGGER_TYPE
from app.config.log_config import service_error_logger

router = APIRouter(prefix="/products")

error_logger = service_error_logger(LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_ERROR)

# TODO: 작품 리뷰 (작품 리뷰 공지 조회, 작품 리뷰 공지 상세, 작품 리뷰 목록 조회, 작품 리뷰 댓글 조회, 리뷰할 작품 검색 등)


@router.get(
    "/managed",
    tags=["작품"],
    responses={
        200: {
            "description": "관리작품(메인, Tops) 목록 전체 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "관리작품(메인, Tops) 목록 전체 조회",
                            "value": {
                                "data": [
                                    {
                                        "productId": 15,
                                        "division": "main",
                                        "area": "freeTop",
                                        "title": "세계전복급 악역으로 오해받고 있습니다",
                                        "rank": 1,
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
async def products_of_managed(
    division: str = Query(None, description="작품 노출 영역 : 메인(main)"),
    area: str = Query(
        None, description="작품 종류: 유료 Top50(paidTop), 무료 Top50(freeTop))"
    ),
    limit: int = Query(None, description="출력 개수"),
    adult_yn: str = Query("N", description="성인등급 작품 포함 여부 (Y/N)"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 목록 전체 조회(메인, 유료, 무료)
    """
    return await product_service.products_of_managed(
        division=division,
        area=area,
        limit=limit,
        adult_yn=adult_yn,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.get(
    "/all",
    tags=["작품"],
    responses={
        200: {
            "description": "전체 작품(유,무료) 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "작품 목록 전체 조회",
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
async def products_all(
    price_type: str = Query(None),
    product_type: str = Query(None),
    product_state: str = Query(None),
    page: int = Query(1),
    limit: int = Query(30),
    genres: List[str] = Query(None),
    adult_yn: str = Query("N", description="성인 작품 포함 여부 (Y: 포함, N: 제외)"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await product_service.products_all(
        price_type=price_type,
        product_type=product_type,
        product_state=product_state,
        page=page,
        limit=limit,
        kc_user_id=user.get("sub"),
        db=db,
        genres=genres,
        adult_yn=adult_yn,
    )


@router.get(
    "/{product_id}/episodes",
    tags=["작품 - 에피소드"],
    responses={
        200: {
            "description": "작품 회차 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "작품 회차 목록 조회.",
                            "value": {
                                "data": {
                                    "latestEpisodeNo": 13,
                                    "latestEpisodeId": 405,
                                    "pagination": {
                                        "totalCount": 76,
                                        "page": 1,
                                        "limit": 10,
                                    },
                                    "episodes": [
                                        {
                                            "episodeId": 405,
                                            "productId": 39,
                                            "episodeNo": 13,
                                            "episodeTitle": "11. 던전상회, 영업합니다Ⅰ",
                                            "episodeTextCount": 13176,
                                            "commentOpenYn": "Y",
                                            "countEvaluation": 0,
                                            "countComment": 0,
                                            "priceType": "free",
                                            "evaluationOpenYn": "Y",
                                            "publishReserveDate": "",
                                            "countHit": 34,
                                            "countRecommend": 0,
                                            "episodeOpenYn": "N",
                                            "usage": {
                                                "readYn": "Y",
                                                "recommendYn": "Y",
                                            },
                                        },
                                        {
                                            "episodeId": 437,
                                            "productId": 39,
                                            "episodeNo": 14,
                                            "episodeTitle": "12. 던전상회, 영업합니다Ⅱ",
                                            "episodeTextCount": 14217,
                                            "commentOpenYn": "Y",
                                            "countEvaluation": 0,
                                            "countComment": 0,
                                            "priceType": "free",
                                            "evaluationOpenYn": "Y",
                                            "publishReserveDate": "",
                                            "countHit": 38,
                                            "countRecommend": 0,
                                            "episodeOpenYn": "N",
                                        },
                                        {
                                            "episodeId": 465,
                                            "productId": 39,
                                            "episodeNo": 15,
                                            "episodeTitle": "13.  평화로운 사자미궁",
                                            "episodeTextCount": 13054,
                                            "commentOpenYn": "Y",
                                            "countEvaluation": 0,
                                            "countComment": 0,
                                            "priceType": "free",
                                            "evaluationOpenYn": "Y",
                                            "publishReserveDate": "",
                                            "countHit": 38,
                                            "countRecommend": 0,
                                            "episodeOpenYn": "N",
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
async def episodes_by_product_id(
    product_id: str = Path(..., description="작품 아이디"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    page: Optional[int] = Query(None, description="조회 시작 위치"),
    limit: Optional[int] = Query(None, description="한페이지 조회 개수"),
    order_by: Optional[str] = Query(None, description="정렬 항목(episodeNo)"),
    order_dir: Optional[str] = Query(None, description="정렬 방향(asc, desc)"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품ID별 회차(에피소드) 목록
    """

    return await product_service.episodes_by_product_id(
        product_id=product_id,
        kc_user_id=user.get("sub"),
        page=page,
        limit=limit,
        order_by=order_by,
        order_dir=order_dir,
        db=db,
    )


@router.get(
    "/{product_id}/details-group",
    tags=["작품"],
    responses={
        200: {
            "description": "작품 회차 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "작품 상세 조회.",
                            "value": {
                                "data": {
                                    "product": {
                                        "productId": 1,
                                        "productType": "normal",
                                        "priceType": "paid",
                                        "title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "synopsis": "1이날이야말로 동소문 안에서 인력거꾼 노릇을 하는 김첨지에게는 오래간만에도 닥친 운수 좋은 날이였다. 문안에(거기도 문밖은 아니지만) 들어간답시는 앞집.",
                                        "authorNickname": "로스티플",
                                        "illustratorNickname": "",
                                        "adultYn": "N",
                                        "genre": ["무협", "판타지"],
                                        "keywords": ["키워드3", "키워드3"],
                                        "image": {
                                            "coverImagePath": "https://cdn.likenovel.dev/cover/1/image.webp",
                                            "adultDefaultcoverImagePath": "https://cdn.likenovel.dev/cover/adult_default.webp",
                                        },
                                        "badge": {
                                            "waitForFreeYn": "Y",
                                            "episodeUploadYn": "Y",
                                            "timepassFromTo": "6-1",
                                            "newReleaseYn": "Y",
                                            "freeEpisodeTicketCount": 3,
                                            "authorEventLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/level/1.webp",
                                            "authorInterestLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/interest/off.webp",
                                        },
                                        "contract": {
                                            "monopolyYn": "N",
                                            "cpContractYn": "N",
                                            "advancePayment": 1000000,
                                            "totalSales": 300000,
                                            "offerCount": 10,
                                            "offerId": "cpUserId",
                                            "offerUserRole": "cp",
                                            "offerDate": "2024-11-01T10:57:00",
                                            "offerAdvancePayment": "",
                                            "settlementRatioSnippet": "정산비 CP 3 : 작가 7",
                                            "offerDecisionState": "review",
                                        },
                                        "properties": {
                                            "updateFrequency": "{'MON':'Y','FRI':'Y'}",
                                            "averageWeeklyEpisodes": 2,
                                            "remarkContentSnippet": "내가 본 OO 작품과 비슷",
                                            "latestEpisodeDate": "2024-09-01T10:57:00",
                                        },
                                        "state": {
                                            "ongoingState": "ongoing",
                                            "convertToPaidState": "approval",
                                        },
                                        "trendindex": {
                                            "readThroughRate": 30,
                                            "readThroughIndicator": 12,
                                            "cpHitCount": 0,
                                            "cpHitIndicator": 1,
                                            "totalInterestCount": 12,
                                            "totalInterestIndicator": 11,
                                            "interestSustainCount": 1,
                                            "interestSustainIndicator": 1,
                                            "interestLossCount": 3,
                                            "interestLossIndicator": 3,
                                            "hitCount": 0,
                                            "hitIndicator": 2,
                                            "recommendCount": 0,
                                            "recommendIndicator": -2,
                                            "notRecommendCount": 0,
                                            "bookmarkCount": 0,
                                            "bookmarkIndicator": 8,
                                            "hasEpisodeCount": 1,
                                            "readedEpisodeCount": 20,
                                            "primaryReaderGroup": "",
                                        },
                                    },
                                    "episodes": [
                                        {
                                            "episodeId": 1,
                                            "productId": 1,
                                            "episodeNo": 1,
                                            "episodeTitle": "라이크노벨 1회차",
                                            "episodeTextCount": 11,
                                            "episodeContent": "가나다라마바사아자차카",
                                            "authorComment": "가나다라마바사",
                                            "commentOpenYn": "Y",
                                            "countEvaluation": 1,
                                            "createdId": "mig",
                                            "createdDate": "2024-11-20T07:15:47",
                                            "updatedId": "mig",
                                            "updatedDate": "2024-11-20T07:15:47",
                                            "countComment": 1,
                                            "priceType": "free",
                                            "evaluationOpenYn": "Y",
                                            "publishReserveDate": "2024-11-19T07:15:47",
                                            "openYn": "Y",
                                            "useYn": "Y",
                                            "countHit": 1,
                                            "countRecommend": 1,
                                            "countLike": 1,
                                            "countView": 3,
                                            "epubFileId": 0,
                                            "epubFilePath": "https://cdn.likenovel.dev",
                                        }
                                    ],
                                    "evaluations": {"highlypositive": 2},
                                    "notices": [
                                        {
                                            "episodeId": 1,
                                            "productId": 1,
                                            "episodeNo": 1,
                                            "noticeId": 1,
                                            "type": "normal",
                                            "subject": "가나다라마바사아자차카",
                                            "content": "가나다라마바사",
                                            "primaryYn": "Y",
                                            "openYn": "Y",
                                            "useYn": "Y",
                                            "countHit": 1,
                                            "createdId": "mig",
                                            "createdDate": "2024-11-20T07:15:47",
                                            "updatedId": "mig",
                                            "updatedDate": "2024-11-20T07:15:47",
                                        }
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
async def product_details_group_by_product_id(
    product_id: str,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 상세 그룹 - 작품 상세, 작품 평가, 작품 공지, 에피소드 목록을 묶어서 응답
    """

    return await product_service.product_details_group_by_product_id(
        product_id=product_id, kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/{product_id}/evaluation",
    tags=["작품"],
    responses={
        200: {
            "description": "작품 평가 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "작품 평가 조회.",
                            "value": {"data": {"highlypositive": 2}},
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
async def product_evaluations_by_product_id(
    db: AsyncSession = Depends(get_likenovel_db),
    product_id: str = Path(..., description="작품 아이디"),
    episode_id: Optional[str] = Query(
        None, description="회차별 평가 조회(회차 아이디)"
    ),
):
    """
    작가의 작품 평가 조회
    """

    return await product_service.product_evaluations_by_id(
        db=db, product_id=product_id, episode_id=episode_id, author_id=None
    )


@router.get(
    "/evaluation/{author_id}",
    tags=["작품"],
    responses={
        200: {
            "description": "작가의 작품 평가 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "작가의 작품 평가 조회.",
                            "value": {"data": {"highlypositive": 2}},
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
async def product_evaluations_by_author_id(
    db: AsyncSession = Depends(get_likenovel_db),
    author_id: str = Path(..., description="작가 사용자 아이디"),
    product_id: Optional[str] = Query(None, description="작품별 평가 조회"),
    episode_id: Optional[str] = Query(
        None, description="회차별 평가 조회(회차 아이디)"
    ),
):
    """
    작가의 작품 평가 조회
    """

    return await product_service.product_evaluations_by_id(
        db=db, product_id=product_id, episode_id=episode_id, author_id=author_id
    )


@router.get(
    "/suggest/{product_id}",
    tags=["작품"],
    responses={
        200: {
            "description": "추천작품 조회(작품 상세 페이지 추천작품 - productId)",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "추천작품 조회",
                            "value": {
                                "data": {
                                    "products": [
                                        {
                                            "productId": 1,
                                            "productType": "normal",
                                            "priceType": "paid",
                                            "title": "1세계전복급 악역으로 오해 받고 있습니다",
                                            "synopsis": "1이날이야말로 동소문 안에서 인력거꾼 노릇을 하는 김첨지에게는 오래간만에도 닥친 운수 좋은 날이였다. 문안에(거기도 문밖은 아니지만) 들어간답시는 앞집.",
                                            "authorNickname": "로스티플",
                                            "illustratorNickname": "",
                                            "adultYn": "N",
                                            "genre": ["무협", "판타지"],
                                            "keywords": ["키워드3", "키워드3"],
                                            "image": {
                                                "coverImagePath": "https://cdn.likenovel.dev/cover/1/image.webp",
                                                "adultDefaultcoverImagePath": "https://cdn.likenovel.dev/cover/adult_default.webp",
                                            },
                                            "badge": {
                                                "waitForFreeYn": "Y",
                                                "episodeUploadYn": "Y",
                                                "timepassFromTo": "6-1",
                                                "newReleaseYn": "Y",
                                                "freeEpisodeTicketCount": 3,
                                                "authorEventLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/level/1.webp",
                                                "authorInterestLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/interest/off.webp",
                                            },
                                            "contract": {
                                                "monopolyYn": "N",
                                                "cpContractYn": "N",
                                                "advancePayment": 1000000,
                                                "totalSales": 300000,
                                                "offerCount": 10,
                                                "offerId": "cpUserId",
                                                "offerUserRole": "cp",
                                                "offerDate": "2024-11-01T10:57:00",
                                                "offerAdvancePayment": "",
                                                "settlementRatioSnippet": "정산비 CP 3 : 작가 7",
                                                "offerDecisionState": "review",
                                            },
                                            "properties": {
                                                "updateFrequency": "{'MON':'Y','FRI':'Y'}",
                                                "averageWeeklyEpisodes": 2,
                                                "remarkContentSnippet": "내가 본 OO 작품과 비슷",
                                                "latestEpisodeDate": "2024-09-01T10:57:00",
                                            },
                                            "state": {
                                                "ongoingState": "ongoing",
                                                "convertToPaidState": "approval",
                                            },
                                            "trendindex": {
                                                "readThroughRate": 30,
                                                "readThroughIndicator": 12,
                                                "cpHitCount": 0,
                                                "cpHitIndicator": 1,
                                                "totalInterestCount": 12,
                                                "totalInterestIndicator": 11,
                                                "interestSustainCount": 1,
                                                "interestSustainIndicator": 1,
                                                "interestLossCount": 3,
                                                "interestLossIndicator": 3,
                                                "hitCount": 0,
                                                "hitIndicator": 2,
                                                "recommendCount": 0,
                                                "recommendIndicator": -2,
                                                "notRecommendCount": 0,
                                                "bookmarkCount": 0,
                                                "bookmarkIndicator": 8,
                                                "hasEpisodeCount": 1,
                                                "readedEpisodeCount": 20,
                                                "primaryReaderGroup": "",
                                            },
                                        }
                                    ]
                                }
                            },
                        }
                    }
                }
            },
        },
        401: {
            "description": "토큰 재발급 요청 필요",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "만료된 access 토큰 상태",
                            "value": {"code": "E4010"},
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
                        "retryPossible_1": {
                            "summary": "UNPROCESSABLE_ENTITY",
                            "value": None,
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
async def suggest_products_by_product_id(
    product_id: str = Path(..., description="작품 아이디"),
    nearby: str = Query(None, description="추천 기준(content,genre,cart)"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 상세 - 추천작품 조회
    """
    return await product_service.suggest_products_by_product_id(
        product_id=product_id, nearby=nearby, kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/suggest-by-recent-viewed/{recent_viewed_product_id}",
    tags=["작품"],
    responses={
        200: {
            "description": "본 작품 기반 추천 작품 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "추천 작품 조회",
                            "value": {
                                "data": {
                                    "products": [
                                        {
                                            "productId": 1,
                                            "productType": "normal",
                                            "priceType": "paid",
                                            "title": "1세계전복급 악역으로 오해 받고 있습니다",
                                            "synopsis": "1이날이야말로 동소문 안에서 인력거꾼 노릇을 하는 김첨지에게는 오래간만에도 닥친 운수 좋은 날이였다. 문안에(거기도 문밖은 아니지만) 들어간답시는 앞집.",
                                            "authorNickname": "로스티플",
                                            "illustratorNickname": "",
                                            "adultYn": "N",
                                            "genre": ["무협", "판타지"],
                                            "keywords": ["키워드3", "키워드3"],
                                            "image": {
                                                "coverImagePath": "https://cdn.likenovel.dev/cover/1/image.webp",
                                                "adultDefaultcoverImagePath": "https://cdn.likenovel.dev/cover/adult_default.webp",
                                            },
                                            "badge": {
                                                "waitForFreeYn": "Y",
                                                "episodeUploadYn": "Y",
                                                "timepassFromTo": "6-1",
                                                "newReleaseYn": "Y",
                                                "freeEpisodeTicketCount": 3,
                                                "authorEventLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/level/1.webp",
                                                "authorInterestLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/interest/off.webp",
                                            },
                                            "contract": {
                                                "monopolyYn": "N",
                                                "cpContractYn": "N",
                                                "advancePayment": 1000000,
                                                "totalSales": 300000,
                                                "offerCount": 10,
                                                "offerId": "cpUserId",
                                                "offerUserRole": "cp",
                                                "offerDate": "2024-11-01T10:57:00",
                                                "offerAdvancePayment": "",
                                                "settlementRatioSnippet": "정산비 CP 3 : 작가 7",
                                                "offerDecisionState": "review",
                                            },
                                            "properties": {
                                                "updateFrequency": "{'MON':'Y','FRI':'Y'}",
                                                "averageWeeklyEpisodes": 2,
                                                "remarkContentSnippet": "내가 본 OO 작품과 비슷",
                                                "latestEpisodeDate": "2024-09-01T10:57:00",
                                            },
                                            "state": {
                                                "ongoingState": "ongoing",
                                                "convertToPaidState": "approval",
                                            },
                                            "trendindex": {
                                                "readThroughRate": 30,
                                                "readThroughIndicator": 12,
                                                "cpHitCount": 0,
                                                "cpHitIndicator": 1,
                                                "totalInterestCount": 12,
                                                "totalInterestIndicator": 11,
                                                "interestSustainCount": 1,
                                                "interestSustainIndicator": 1,
                                                "interestLossCount": 3,
                                                "interestLossIndicator": 3,
                                                "hitCount": 0,
                                                "hitIndicator": 2,
                                                "recommendCount": 0,
                                                "recommendIndicator": -2,
                                                "notRecommendCount": 0,
                                                "bookmarkCount": 0,
                                                "bookmarkIndicator": 8,
                                                "hasEpisodeCount": 1,
                                                "readedEpisodeCount": 20,
                                                "primaryReaderGroup": "",
                                            },
                                        }
                                    ]
                                }
                            },
                        }
                    }
                }
            },
        },
        401: {
            "description": "토큰 재발급 요청 필요",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "만료된 access 토큰 상태",
                            "value": {"code": "E4010"},
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
                        "retryPossible_1": {
                            "summary": "UNPROCESSABLE_ENTITY",
                            "value": None,
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
async def suggest_products_by_recent_viewed_product_id(
    recent_viewed_product_id: str = Path(..., description="최근 본 작품 아이디"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    본 작품 기반 추천 작품 조회
    """
    return await product_service.suggest_products_by_product_id(
        product_id=recent_viewed_product_id,
        nearby="genre",
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.get(
    "/suggest-by-recent-viewed",
    tags=["작품"],
    responses={
        200: {
            "description": "최근 본 작품 기반 추천",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "추천 작품 조회",
                            "value": {
                                "data": [
                                    {
                                        "productId": 15,
                                        "title": "세계전복급 악역으로 오해받고 있습니다",
                                        "genre": ["무협", "판타지"],
                                        "keywords": ["키워드1, 키워드2, 키워드3"],
                                    }
                                ]
                            },
                        }
                    }
                }
            },
        },
        401: {
            "description": "로그인 필요",
            "content": {
                "application/json": {
                    "examples": {
                        "login_required": {
                            "summary": "로그인이 필요합니다",
                            "value": {"code": "E4010"},
                        }
                    }
                }
            },
        },
    },
    dependencies=[Depends(analysis_logger)],
)
async def suggest_products_by_recent_viewed(
    adult_yn: str = Query("N", description="성인 작품 포함 여부 (Y | N)"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    최근 본 작품 기반 추천 작품 조회

    사용자가 가장 최근에 본 작품을 기반으로 유사한 작품들을 추천합니다.
    """
    return await product_service.suggest_products_by_recent_viewed(
        kc_user_id=user.get("sub"), adult_yn=adult_yn, db=db
    )


@router.get(
    "/suggest-managed",
    tags=["작품"],
    responses={
        200: {
            "description": "추천작품 노출관리",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "추천작품 관리",
                            "value": {
                                "data": {
                                    "products": [
                                        {
                                            "productId": 1,
                                            "productType": "normal",
                                            "priceType": "paid",
                                            "title": "1세계전복급 악역으로 오해 받고 있습니다",
                                            "synopsis": "1이날이야말로 동소문 안에서 인력거꾼 노릇을 하는 김첨지에게는 오래간만에도 닥친 운수 좋은 날이였다. 문안에(거기도 문밖은 아니지만) 들어간답시는 앞집.",
                                            "authorNickname": "로스티플",
                                            "illustratorNickname": "",
                                            "adultYn": "N",
                                            "genre": ["무협", "판타지"],
                                            "keywords": ["키워드3", "키워드3"],
                                            "image": {
                                                "coverImagePath": "https://cdn.likenovel.dev/cover/1/image.webp",
                                                "adultDefaultcoverImagePath": "https://cdn.likenovel.dev/cover/adult_default.webp",
                                            },
                                            "badge": {
                                                "waitForFreeYn": "Y",
                                                "episodeUploadYn": "Y",
                                                "timepassFromTo": "6-1",
                                                "newReleaseYn": "Y",
                                                "freeEpisodeTicketCount": 3,
                                                "authorEventLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/level/1.webp",
                                                "authorInterestLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/interest/off.webp",
                                            },
                                            "contract": {
                                                "monopolyYn": "N",
                                                "cpContractYn": "N",
                                                "advancePayment": 1000000,
                                                "totalSales": 300000,
                                                "offerCount": 10,
                                                "offerId": "cpUserId",
                                                "offerUserRole": "cp",
                                                "offerDate": "2024-11-01T10:57:00",
                                                "offerAdvancePayment": "",
                                                "settlementRatioSnippet": "정산비 CP 3 : 작가 7",
                                                "offerDecisionState": "review",
                                            },
                                            "properties": {
                                                "updateFrequency": "{'MON':'Y','FRI':'Y'}",
                                                "averageWeeklyEpisodes": 2,
                                                "remarkContentSnippet": "내가 본 OO 작품과 비슷",
                                                "latestEpisodeDate": "2024-09-01T10:57:00",
                                            },
                                            "state": {
                                                "ongoingState": "ongoing",
                                                "convertToPaidState": "approval",
                                            },
                                            "trendindex": {
                                                "readThroughRate": 30,
                                                "readThroughIndicator": 12,
                                                "cpHitCount": 0,
                                                "cpHitIndicator": 1,
                                                "totalInterestCount": 12,
                                                "totalInterestIndicator": 11,
                                                "interestSustainCount": 1,
                                                "interestSustainIndicator": 1,
                                                "interestLossCount": 3,
                                                "interestLossIndicator": 3,
                                                "hitCount": 0,
                                                "hitIndicator": 2,
                                                "recommendCount": 0,
                                                "recommendIndicator": -2,
                                                "notRecommendCount": 0,
                                                "bookmarkCount": 0,
                                                "bookmarkIndicator": 8,
                                                "hasEpisodeCount": 1,
                                                "readedEpisodeCount": 20,
                                                "primaryReaderGroup": "",
                                            },
                                        }
                                    ]
                                }
                            },
                        }
                    }
                }
            },
        },
        401: {
            "description": "토큰 재발급 요청 필요",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "만료된 access 토큰 상태",
                            "value": {"code": "E4010"},
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
                        "retryPossible_1": {
                            "summary": "UNPROCESSABLE_ENTITY",
                            "value": None,
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
async def suggest_managed_products(
    adult_yn: str = Query("N", description="성인등급 작품 포함 여부 (Y/N)"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    작품 - 추천작품 노출관리
    """
    return await product_service.suggest_managed_products(
        db=db, kc_user_id=user.get("sub"), adult_yn=adult_yn
    )


@router.get(
    "/direct-recommend",
    tags=["작품"],
    responses={
        200: {
            "description": "직접 추천 구좌 작품 목록 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "직접 추천 구좌 작품 목록",
                            "value": {
                                "data": [
                                    {
                                        "recommendId": 1,
                                        "recommendName": "작품 추천 카테고리1",
                                        "order": 1,
                                        "products": [
                                            {
                                                "productId": 15,
                                                "title": "세계전복급 악역으로 오해받고 있습니다",
                                                "genre": ["무협", "판타지"],
                                                "keywords": [
                                                    "키워드1, 키워드2, 키워드3"
                                                ],
                                            }
                                        ],
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
    },
    dependencies=[Depends(analysis_logger)],
)
async def get_direct_recommend_products(
    adult_yn: str = Query("N", description="성인등급 작품 포함 여부 (Y/N)"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    직접 추천 구좌 작품 목록 조회

    관리자가 설정한 직접 추천 구좌의 작품들을 조회합니다.
    노출 기간과 시간대(평일/주말)를 고려하여 현재 활성화된 추천 구좌만 반환합니다.
    """
    return await product_service.get_direct_recommend_products(
        kc_user_id=user.get("sub"), db=db, adult_yn=adult_yn
    )


@router.get(
    "/author/others",
    tags=["작품"],
    responses={
        200: {
            "description": "작품 회차 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "작품 회차 목록 조회.",
                            "value": {
                                "data": {
                                    "latestEpisodeNo": 13,
                                    "latestEpisodeId": 405,
                                    "pagination": {
                                        "totalCount": 76,
                                        "page": 1,
                                        "limit": 10,
                                    },
                                    "episodes": [
                                        {
                                            "episodeId": 405,
                                            "productId": 39,
                                            "episodeNo": 13,
                                            "episodeTitle": "11. 던전상회, 영업합니다Ⅰ",
                                            "episodeTextCount": 13176,
                                            "commentOpenYn": "Y",
                                            "countEvaluation": 0,
                                            "countComment": 0,
                                            "priceType": "free",
                                            "evaluationOpenYn": "Y",
                                            "publishReserveDate": "",
                                            "countHit": 34,
                                            "countRecommend": 0,
                                            "episodeOpenYn": "N",
                                            "usage": {
                                                "readYn": "Y",
                                                "recommendYn": "Y",
                                            },
                                        },
                                        {
                                            "episodeId": 437,
                                            "productId": 39,
                                            "episodeNo": 14,
                                            "episodeTitle": "12. 던전상회, 영업합니다Ⅱ",
                                            "episodeTextCount": 14217,
                                            "commentOpenYn": "Y",
                                            "countEvaluation": 0,
                                            "countComment": 0,
                                            "priceType": "free",
                                            "evaluationOpenYn": "Y",
                                            "publishReserveDate": "",
                                            "countHit": 38,
                                            "countRecommend": 0,
                                            "episodeOpenYn": "N",
                                        },
                                        {
                                            "episodeId": 465,
                                            "productId": 39,
                                            "episodeNo": 15,
                                            "episodeTitle": "13.  평화로운 사자미궁",
                                            "episodeTextCount": 13054,
                                            "commentOpenYn": "Y",
                                            "countEvaluation": 0,
                                            "countComment": 0,
                                            "priceType": "free",
                                            "evaluationOpenYn": "Y",
                                            "publishReserveDate": "",
                                            "countHit": 38,
                                            "countRecommend": 0,
                                            "episodeOpenYn": "N",
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
async def other_products_of_author(
    author_id: int = Query(None, description="작가 아이디"),
    author_nickname: Optional[str] = Query(None, description="작가 닉네임"),
    price_type: Optional[str] = Query(
        None, description="기본:전체, 유료:paid, 무료:free"
    ),
    adult_yn: Optional[str] = Query(None, description="일반:N, 성인:Y"),
    exclude_product_id: Optional[str] = Query(None, description="제외할 작품 아이디"),
    page: Optional[int] = Query(None, description="조회 시작 위치"),
    limit: Optional[int] = Query(None, description="한페이지 조회 개수"),
    order_by: Optional[str] = Query(None, description="정렬 항목(episodeNo)"),
    order_dir: Optional[str] = Query(None, description="정렬 방향(asc, desc)"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작가의 다른 작품 목록
    """

    return await product_service.other_products_of_author(
        kc_user_id=user.get("sub"),
        author_id=author_id,
        author_nickname=author_nickname,
        price_type=price_type,
        adult_yn=adult_yn,
        exclude_product_id=exclude_product_id,
        page=page,
        limit=limit,
        order_by=order_by,
        order_dir=order_dir,
        db=db,
    )


@router.get(
    "/{product_id}/comments",
    tags=["작품 - 댓글"],
    responses={
        200: {
            "description": "작품 전체 댓글(episode_id 쿼리스트링 값이 없으면 전체, 있으면 회차단위) 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "작품 전체 혹은 회차단위로 데이터 리턴",
                            "value": {
                                "data": {
                                    "commentTotalCount": 2,
                                    "comments": [
                                        {
                                            "commentId": 1,
                                            "userId": 1,
                                            "userNickname": "로스티플1",
                                            "userProfileImagePath": "https://cdn.likenovel.dev/user/default_profile.webp",
                                            "userInterestLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/level/interest/1.webp",
                                            "userEventLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/level/event/1.webp",
                                            "content": "댓글내용1",
                                            "publishDate": "2024-03-05T12:35:00",
                                            "authorPinnedTopYn": "N",
                                            "authorRecommendedYn": "Y",
                                            "recommendCount": 100,
                                            "notRecommendCount": 10,
                                            "recommendYn": "Y",
                                            "notRecommendYn": "N",
                                            "userRole": "author",
                                            "commentEpisode": "댓글 회차 : 24화. 선택받은 마녀 미라벨",
                                            "authorNickname": "제로콜라",
                                            "authorProfileImagePath": "https://cdn.likenovel.dev/user/default_profile.webp",
                                        },
                                        {
                                            "commentId": 2,
                                            "userId": 1,
                                            "userNickname": "로스티플2",
                                            "userProfileImagePath": "https://cdn.likenovel.dev/user/default_profile.webp",
                                            "userInterestLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/level/interest/1.webp",
                                            "userEventLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/level/event/1.webp",
                                            "content": "댓글내용2",
                                            "publishDate": "2024-03-15T12:35:00",
                                            "authorPinnedTopYn": "N",
                                            "authorRecommendedYn": "N",
                                            "recommendCount": 50,
                                            "notRecommendCount": 5,
                                            "recommendYn": "N",
                                            "notRecommendYn": "N",
                                            "userRole": "cp",
                                            "commentEpisode": "댓글 회차 : 24화. 선택받은 마녀 미라벨",
                                            "authorNickname": "제로콜라",
                                            "authorProfileImagePath": "https://cdn.likenovel.dev/user/default_profile.webp",
                                        },
                                    ],
                                }
                            },
                        }
                    }
                }
            },
        },
        401: {
            "description": "토큰 재발급 요청 필요",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "만료된 access 토큰 상태",
                            "value": {"code": "E4010"},
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
                        "retryPossible_1": {
                            "summary": "UNPROCESSABLE_ENTITY",
                            "value": None,
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
async def get_products_product_id_comments(
    product_id: str = Path(..., description="작품 id"),
    episode_id: Optional[str] = Query(None, description="회차별 댓글 조회(회차 id)"),
    page: str = Query(None, description="페이지 넘버"),
    limit: str = Query(None, description="페이지당 최대 출력 수"),
    order: str = Query(None, description="정렬 순서(recommend, recent))"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 전체 댓글 조회

    [쿼리스트링 값]
    1. ?episode_id={number}: 회차별 댓글 조회
    2. ?page={number}&limit={number}: 페이징 처리(더보기). number는 1이상의 값, limit은 30 전달 필요
    3. ?order=recommend: 공감많은순 정렬
    4. ?order=recent: 최신순 정렬
    """

    return await product_comment_service.get_products_product_id_comments(
        episode_id=episode_id,
        product_id=product_id,
        page=page,
        limit=limit,
        order=order,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.get(
    "/cover/upload/{file_name}",
    tags=["작품 - 작품 관리"],
    responses={
        200: {
            "description": "파일 업로드가 가능한 URL 생성",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "파일 업로드 권한이 있는 presigned URL을 생성한 후 전달",
                            "value": {
                                "data": {
                                    "coverImageFileId": 1,
                                    "coverImageUploadPath": "https://a168bba93203dec90f4f7ddda837c772.r2.cloudflarestorage.com/image/cover/NIVOD2R3QhShEfuI37qmxA.webp?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=073f266abc091744da51a72250a10c32%2F20241108%2Fapac%2Fs3%2Faws4_request&X-Amz-Date=20241108T110511Z&X-Amz-Expires=10800&X-Amz-SignedHeaders=host&X-Amz-Signature=63b1e666f8a9eb8874053dd214e1c35f8a01dd89ca603447220cda2b3ad4df57",
                                }
                            },
                        }
                    }
                }
            },
        },
        401: {
            "description": "토큰 재발급 요청 필요",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "만료된 access 토큰 상태",
                            "value": {"code": "E4010"},
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
                        },
                    }
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "file_name 값 validation 에러(유효하지 않은 file_name 값)",
                            "value": {"code": "E4224"},
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
async def get_products_cover_upload_file_name(
    file_name: str = Path(..., description="원본 파일명(.webp)"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 표지 이미지 업로드 버튼
    (글쓰기 작품 만들기)
    """

    return await product_service.get_products_cover_upload_file_name(
        file_name=file_name, kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/{product_id}/conversion",
    tags=["작품 - 작품 관리"],
    responses={
        200: {
            "description": "작품 일반승급신청(쿼리스트링 값에 따라 구분. 현재 일반승급신청만 유효함) 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "일반승급신청",
                            "value": {
                                "data": {
                                    "productId": 1,
                                    "contentTextCountFulfillYn": "Y",
                                    "episodeCountFulfillYn": "Y",
                                }
                            },
                        }
                    }
                }
            },
        },
        401: {
            "description": "토큰 재발급 요청 필요",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "만료된 access 토큰 상태",
                            "value": {"code": "E4010"},
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def get_products_product_id_conversion(
    product_id: str = Path(..., description="작품 id"),
    category: str = Query(None, description="일반승급신청(rank-up)"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 일반승급신청/유료전환신청 조건 여부 조회

    [쿼리스트링 값]
    1. ?category=rank-up: 일반승급신청
    """

    return await product_service.get_products_product_id_conversion(
        category=category, product_id=product_id, kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/genres",
    tags=["작품"],
    responses={
        200: {
            "description": "작품 장르 목록 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "작품 장르 목록",
                            "value": {
                                "data": [
                                    {"genreId": 1, "genre": "판타지"},
                                    {"genreId": 5, "genre": "로맨스"},
                                ]
                            },
                        }
                    }
                }
            },
        },
        401: {
            "description": "토큰 재발급 요청 필요",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "만료된 access 토큰 상태",
                            "value": {"code": "E4010"},
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def get_products_genres(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 장르 목록 (필터) 조회
    """

    return await product_service.get_products_genres(kc_user_id=user.get("sub"), db=db)


@router.get(
    "/keywords",
    tags=["작품"],
    responses={
        200: {
            "description": "작품 키워드 목록 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "작품 키워드 목록",
                            "value": {
                                "data": [
                                    {
                                        "categoryId": 1,
                                        "category": "장르",
                                        "categoryCount": 2,
                                        "keywords": ["판타지", "스포츠"],
                                    },
                                    {
                                        "categoryId": 2,
                                        "category": "소재",
                                        "categoryCount": 2,
                                        "keywords": ["판타지", "스포츠"],
                                    },
                                ]
                            },
                        }
                    }
                }
            },
        },
        401: {
            "description": "토큰 재발급 요청 필요",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "만료된 access 토큰 상태",
                            "value": {"code": "E4010"},
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def get_products_keywords(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 키워드 목록 (필터) 조회
    """

    return await product_service.get_products_keywords(
        kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/{product_id}/episodes/count",
    tags=["작품 - 에피소드"],
    responses={
        200: {
            "description": "작품 전체 회차 수 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "작품 전체 회차 수",
                            "value": {"data": {"hasEpisodeCount": 5}},
                        }
                    }
                }
            },
        },
        401: {
            "description": "토큰 재발급 요청 필요",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "만료된 access 토큰 상태",
                            "value": {"code": "E4010"},
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def get_products_product_id_episodes_count(
    product_id: str = Path(..., description="작품 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 전체 회차 수 조회
    """

    return await product_service.get_products_product_id_episodes_count(
        product_id=product_id, kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/{product_id}/info",
    tags=["작품"],
    responses={
        200: {
            "description": "저장된 작품 정보 내용 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "저장된 작품 정보",
                            "value": {
                                "data": {
                                    "productId": 1,
                                    "coverImagePath": "https://cdn.likenovel.dev/cover/26SH8jv6R_ud9lAevfya5Q.webp",
                                    "ongoingState": "end",
                                    "title": "제목",
                                    "authorNickname": "로스티플",
                                    "illustratorNickname": "가나다라",
                                    "updateFrequency": ["mon", "tue"],
                                    "publishRegularYn": "Y",
                                    "primaryGenre": "판타지",
                                    "subGenre": "로맨스",
                                    "keywords": ["판타지", "로맨스"],
                                    "customKeywords": [],
                                    "synopsis": "시놉시스",
                                    "adultYn": "N",
                                    "openYn": "Y",
                                    "monopolyYn": "N",
                                    "cpContractYn": "N",
                                    "paidSettingDate": None,
                                    "paidEpisodeNo": None,
                                    "priceType": "free",
                                }
                            },
                        }
                    }
                }
            },
        },
        401: {
            "description": "토큰 재발급 요청 필요",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "만료된 access 토큰 상태",
                            "value": {"code": "E4010"},
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def get_products_product_id_info(
    product_id: str = Path(..., description="작품 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    저장된 작품 정보 내용 조회
    """

    return await product_service.get_products_product_id_info(
        product_id=product_id, kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/notices/{product_notice_id}/info",
    tags=["작품 - 작품 공지"],
    responses={
        200: {
            "description": "저장된 작품 공지 정보 내용 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "저장된 작품 공지 정보",
                            "value": {
                                "data": {
                                    "productNoticeId": 1,
                                    "title": "제목",
                                    "content": "내용",
                                    "openYn": "N",
                                    "publishReserveYn": "N",
                                    "publishReserveDate": "2024-12-31T23:59:59",
                                }
                            },
                        }
                    }
                }
            },
        },
        401: {
            "description": "토큰 재발급 요청 필요",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "만료된 access 토큰 상태",
                            "value": {"code": "E4010"},
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def get_products_notices_product_notice_id_info(
    product_notice_id: str = Path(..., description="작품 공지 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    저장된 작품 공지 정보 내용 조회
    """

    return await product_notice_service.get_products_notices_product_notice_id_info(
        product_notice_id=product_notice_id, kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/bookmark",
    tags=["작품 - 북마크"],
    responses={
        200: {
            "description": "작품 북마크 목록 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "작품 북마크 목록",
                            "value": {
                                "data": [
                                    {
                                        "productId": 1,
                                        "title": "작품 제목",
                                        "priceType": "paid",
                                        "productType": "normal",
                                        "statusCode": "ongoing",
                                        "ratingsCode": "all",
                                        "synopsisText": "작품 소개",
                                        "userId": 1,
                                        "authorId": 1,
                                        "authorName": "작가명",
                                        "illustratorId": None,
                                        "illustratorName": None,
                                        "publishRegularYn": "Y",
                                        "publishDays": "월,수,금",
                                        "thumbnailFileId": 1,
                                        "thumbnailFilePath": "https://cdn.likenovel.dev/thumbnail.jpg",
                                        "primaryGenreId": 1,
                                        "primaryGenreName": "로맨스",
                                        "subGenreId": 2,
                                        "subGenreName": "판타지",
                                        "countHit": 1000,
                                        "countCpHit": 500,
                                        "countRecommend": 100,
                                        "countBookmark": 50,
                                        "countUnbookmark": 5,
                                        "openYn": "Y",
                                        "approvalYn": "Y",
                                        "monopolyYn": "N",
                                        "contractYn": "N",
                                        "paidOpenDate": "2024-11-01T10:00:00",
                                        "paidEpisodeNo": 3,
                                        "lastEpisodeDate": "2024-11-10T15:00:00",
                                        "isbn": None,
                                        "uci": None,
                                        "singleRegularPrice": 0,
                                        "seriesRegularPrice": 100,
                                        "salePrice": 100,
                                        "applyDate": "2024-10-01T10:00:00",
                                        "createdDate": "2024-09-01T09:00:00",
                                        "updatedDate": "2024-11-10T16:00:00",
                                        "bookmarkYn": "Y",
                                        "bookmarkCreatedDate": "2024-11-11T10:30:00",
                                    }
                                ]
                            },
                        }
                    }
                }
            },
        }
    },
)
async def products_bookmark_by_user_id(
    sort_by: Optional[str] = Query(
        "recent_update",
        description="정렬 기준: recent_update(최근 업데이트 순), title(가나다 순), bookmark_date(선호작 등록 순)",
    ),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 북마크 목록 조회
    """

    return await product_bookmark_service.products_bookmark_by_user_id(
        kc_user_id=user.get("sub"), sort_by=sort_by, db=db
    )


@router.get(
    "/interest-drop-products", tags=["작품"], dependencies=[Depends(analysis_logger)]
)
async def get_user_interest_drop_products(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    관심 끊기기 목록 조회
    """

    return await product_service.get_user_interest_drop_products(
        kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/interest-drop-products-soon",
    tags=["작품"],
    dependencies=[Depends(analysis_logger)],
)
async def get_user_interest_drop_products_soon(
    adult_yn: str = Query("N", description="성인등급 작품 포함 여부 (Y/N)"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    관심 끊기기 임박 목록 조회
    """

    return await product_service.get_user_interest_drop_products_soon(
        kc_user_id=user.get("sub"), db=db, adult_yn=adult_yn
    )


@router.get(
    "/rank",
    tags=["작품"],
    responses={
        200: {
            "description": "유/무료 top 50 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "유/무료 top 50 조회",
                            "value": {
                                "data": [
                                    {
                                        "productId": 15,
                                        "division": "main",
                                        "area": "freeTop",
                                        "title": "세계전복급 악역으로 오해 받고 있습니다",
                                        "rank": 1,
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
async def get_product_rank(db: AsyncSession = Depends(get_likenovel_db)):
    """
    작품 목록 전체 조회(메인, 유료, 무료)
    """

    return await product_service.get_product_rank(db=db)


@router.get(
    "/publisher-promotion",
    tags=["작품"],
    responses={
        200: {
            "description": "출판사 프로모션 작품 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "출판사 프로모션 작품 조회",
                            "value": {
                                "data": [
                                    {
                                        "productId": 15,
                                        "title": "세계전복급 악역으로 오해받고 있습니다",
                                        "rank": 1,
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
async def products_in_publisher_promotion(
    adult_yn: str = Query("N", description="성인등급 작품 포함 여부 (Y/N)"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    출판사 프로모션 작품 리스트 조회
    """
    return await product_service.products_in_publisher_promotion(
        kc_user_id=user.get("sub"), db=db, adult_yn=adult_yn
    )


@router.get(
    "/latest-update",
    tags=["작품"],
    responses={
        200: {
            "description": "최신 업데이트 작품 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "최신 업데이트 작품 조회",
                            "value": {
                                "data": [
                                    {
                                        "productId": 15,
                                        "title": "세계전복급 악역으로 오해받고 있습니다",
                                        "rank": 1,
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
async def products_in_latest_update(
    adult_yn: str = Query("N", description="성인등급 작품 포함 여부 (Y/N)"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    최신 업데이트 작품 리스트 조회
    """
    return await product_service.products_in_latest_update(
        kc_user_id=user.get("sub"), db=db, adult_yn=adult_yn
    )


@router.get(
    "/wait-for-free",
    tags=["작품"],
    responses={
        200: {
            "description": "출판사 프로모션 작품 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "출판사 프로모션 작품 조회",
                            "value": {
                                "data": {
                                    "2025-09-07": [
                                        {
                                            "productId": 15,
                                            "title": "세계전복급 악역으로 오해받고 있습니다",
                                            "rank": 1,
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
async def products_in_applied_promotion_wait_for_free(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    기다리면 무료 프로모션 작품 리스트 조회
    """
    return await product_service.products_in_applied_promotion(
        type="waiting-for-free", kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/6-9-pass",
    tags=["작품"],
    responses={
        200: {
            "description": "출판사 프로모션 작품 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "출판사 프로모션 작품 조회",
                            "value": {
                                "data": [
                                    {
                                        "productId": 15,
                                        "title": "세계전복급 악역으로 오해받고 있습니다",
                                        "rank": 1,
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
async def products_in_applied_promotion_6_9_pass(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    69패스 프로모션 작품 리스트 조회
    """
    return await product_service.products_in_applied_promotion(
        type="6-9-path", kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/{product_id}",
    tags=["작품"],
    responses={
        200: {
            "description": "작품 정보",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "작품 정보 조회.",
                            "value": {
                                "data": {
                                    "productId": 15,
                                    "division": "main",
                                    "area": "freeTop",
                                    "title": "세계전복급 악역으로 오해받고 있습니다",
                                    "rank": 1,
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
async def product_by_product_id(
    product_id: str = Path(..., description="작품 아이디"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 정보 조회
    """

    return await product_service.product_by_product_id(
        product_id=product_id,
        kc_user_id=user.get("sub"),
        db=db,
    )
