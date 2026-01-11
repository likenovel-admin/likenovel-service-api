from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.episode as episode_schema
import app.services.product.episode_service as episode_service
import app.services.order.purchase_service as purchase_service

router = APIRouter(prefix="/episodes")


@router.post(
    "/products/{product_id}",
    tags=["회차 - 회차 관리"],
    responses={
        200: {
            "description": "회차 저장/등록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "새롭게 생성된 회차 id를 전달",
                            "value": {"data": {"episodeId": 1}},
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
                            "summary": "회차 저장/등록/수정 값 validation 에러(유효하지 않은 정보 값)",
                            "value": {"code": "E4226"},
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
async def post_episodes_products_product_id(
    req_body: episode_schema.PostEpisodesProductsProductIdReqBody,
    product_id: str = Path(..., description="작품 id"),
    save: Optional[str] = Query(None, description="저장(Y), 등록(N)"),
    episode_id: Optional[str] = Query(None, description="회차 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    회차 최초 저장/등록 버튼
    (글쓰기 작품 만들기 회차관리 회차등록)

    [쿼리스트링 값]
    1. ?save=Y: 저장
    2. ?save=N: 등록
    3. ?episode_id: 새로 생성된 회차 id(저장 버튼 클릭 후, 다음에 일어날 저장 혹은 등록 액션에 활용 - 동일한 pk 값으로 업데이트 하기 위함)
    """

    return await episode_service.post_episodes_products_product_id(
        save=save,
        episode_id=episode_id,
        product_id=product_id,
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.put(
    "/{episode_id}",
    tags=["회차 - 회차 관리"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
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
                            "summary": "회차 저장/등록/수정 값 validation 에러(유효하지 않은 정보 값)",
                            "value": {"code": "E4226"},
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
async def put_episodes_episode_id(
    req_body: episode_schema.PutEpisodesEpisodeIdReqBody,
    episode_id: str = Path(..., description="회차 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    회차 수정 버튼
    (글쓰기 작품 만들기 회차관리 회차등록, 글쓰기 작품 만들기 회차관리)
    """

    return await episode_service.put_episodes_episode_id(
        episode_id=episode_id, req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/{episode_id}/open",
    tags=["회차 - 회차 관리"],
    responses={
        200: {
            "description": "회차 공개 설정 및 해제",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 공개 상태에 따른 반전된 값 전달",
                            "value": {"data": {"episodeId": 1, "openYn": "N"}},
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
async def put_episodes_episode_id_open(
    episode_id: str = Path(..., description="회차 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    회차 공개/비공개 버튼
    (글쓰기 작품 만들기 회차관리)
    """

    return await episode_service.put_episodes_episode_id_open(
        episode_id=episode_id, kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/{episode_id}/paid",
    tags=["회차 - 회차 관리"],
    responses={
        200: {
            "description": "회차 유료 설정 및 해제",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 상태에 따른 반전된 값 전달",
                            "value": {"data": {"episodeId": 1, "priceType": "free"}},
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
async def put_episodes_episode_id_paid(
    episode_id: str = Path(..., description="회차 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    회차 유료/무료 버튼
    (글쓰기 작품 만들기 회차관리)
    """

    return await episode_service.put_episodes_episode_id_paid(
        episode_id=episode_id, kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/{episode_id}/reaction",
    tags=["회차 - 뷰어"],
    responses={
        200: {
            "description": "회차 추천 설정 및 해제",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 추천 상태에 따른 반전된 값 전달",
                            "value": {"data": {"episodeId": 1, "recommendYn": "N"}},
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
async def put_episodes_episode_id_reaction(
    episode_id: str = Path(..., description="회차 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    회차 추천/비추천 버튼
    (뷰어)
    """

    return await episode_service.put_episodes_episode_id_reaction(
        episode_id=episode_id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{episode_id}/evaluation",
    tags=["회차 - 뷰어"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
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
async def post_episodes_episode_id_evaluation(
    req_body: episode_schema.PostEpisodesEpisodeIdEvaluationReqBody,
    episode_id: str = Path(..., description="회차 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    회차 평가 버튼
    (뷰어)
    """

    return await episode_service.post_episodes_episode_id_evaluation(
        episode_id=episode_id, req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{episode_id}/like",
    tags=["회차 - 좋아요"],
    responses={
        200: {
            "description": "회차 좋아요 등록",
            "content": {"application/json": {"examples": {"result": True}}},
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
async def add_like_product_episode(
    episode_id: str = Path(..., description="회차 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    좋아요 등록
    """

    return await episode_service.add_like_product_episode(
        episode_id=episode_id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{episode_id}/unlike",
    tags=["회차 - 좋아요"],
    responses={
        200: {
            "description": "회차 좋아요 취소",
            "content": {"application/json": {"examples": {"result": True}}},
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
async def remove_like_product_episode(
    episode_id: str = Path(..., description="회차 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    좋아요 취소
    """

    return await episode_service.remove_like_product_episode(
        episode_id=episode_id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{episode_id}/purchase",
    tags=["회차 - 구매"],
    responses={
        200: {
            "description": "에피소드 구매 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "구매 성공",
                            "value": {"result": True},
                        }
                    }
                }
            },
        },
        400: {
            "description": "잘못된 요청",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "이미 소장한 에피소드",
                            "value": {"code": "E4001"},
                        },
                        "retryPossible_2": {
                            "summary": "캐시 잔액 부족",
                            "value": {"code": "E4002"},
                        },
                        "retryPossible_3": {
                            "summary": "무료 에피소드는 구매 불가",
                            "value": {"code": "E4003"},
                        },
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
        404: {
            "description": "에피소드를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "존재하지 않는 에피소드",
                            "value": {"code": "E4040"},
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
async def purchase_episode_with_cash(
    req_body: episode_schema.PurchaseEpisodeWithCashReqBody,
    episode_id: str = Path(..., description="회차 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    캐시로 에피소드 구매 (소장)

    100 캐시를 소모하여 에피소드를 소장합니다.
    """

    return await purchase_service.purchase_episode_with_cash(
        episode_id=int(episode_id),
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )
