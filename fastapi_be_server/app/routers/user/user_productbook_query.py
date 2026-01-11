from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.user.user_productbook_service as user_productbook_service

router = APIRouter(prefix="/user-productbook")


@router.get(
    "",
    tags=["사용자 대여권"],
    responses={
        200: {
            "description": "",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "ticket_type": "type",
                                        "own_type": "own",
                                        "user_id": 1,
                                        "profile_id": 1,
                                        "product_id": 1,
                                        "episode_id": 1,
                                        "rental_expired_date": "2024-08-01T16:00:00",
                                        "createdDate": "2024-08-01T16:00:00",
                                        "updatedDate": "2024-08-01T16:00:00",
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
async def user_productbook_list(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    사용자 대여권 목록
    """

    return await user_productbook_service.user_productbook_list(
        kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/available-tickets",
    tags=["사용자 대여권"],
    responses={
        200: {
            "description": "",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "사용 가능한 대여권 목록",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "ticket_type": "rental",
                                        "own_type": "rental",
                                        "user_id": 1,
                                        "profile_id": 1,
                                        "product_id": 1,
                                        "episode_id": 10,
                                        "rental_expired_date": "2024-12-31T23:59:59",
                                        "use_yn": "N",
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_date": "2024-08-01T16:00:00",
                                    },
                                    {
                                        "id": 2,
                                        "ticket_type": "rental",
                                        "own_type": "rental",
                                        "user_id": 1,
                                        "profile_id": 1,
                                        "product_id": 1,
                                        "episode_id": 11,
                                        "rental_expired_date": "2024-12-31T23:59:59",
                                        "use_yn": "N",
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_date": "2024-08-01T16:00:00",
                                    },
                                ]
                            },
                        }
                    }
                }
            },
        },
        400: {
            "description": "Bad Request",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_params": {
                            "summary": "필수 파라미터 누락",
                            "value": {
                                "message": "episode_id 또는 product_id 중 하나는 필수입니다."
                            },
                        }
                    }
                }
            },
        },
        401: {
            "description": "Unauthorized",
            "content": {
                "application/json": {
                    "examples": {
                        "expired_token": {
                            "summary": "인증 실패",
                            "value": {"message": "액세스 토큰이 만료되었습니다."},
                        }
                    }
                }
            },
        },
        404: {
            "description": "Not Found",
            "content": {
                "application/json": {
                    "examples": {
                        "episode_not_found": {
                            "summary": "에피소드를 찾을 수 없음",
                            "value": {"message": "존재하지 않는 에피소드입니다."},
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
async def get_available_rental_tickets(
    episode_id: Optional[int] = Query(None, description="에피소드 ID"),
    product_id: Optional[int] = Query(None, description="작품 ID"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    특정 에피소드 또는 작품에서 사용 가능한 대여권 목록 조회

    - **episode_id**: 에피소드 ID (선택)
    - **product_id**: 작품 ID (선택)
    - **둘 중 하나는 필수**
    """

    return await user_productbook_service.get_available_rental_tickets(
        kc_user_id=user.get("sub"),
        db=db,
        episode_id=episode_id,
        product_id=product_id,
    )


@router.get(
    "/{id}",
    tags=["사용자 대여권"],
    responses={
        200: {
            "description": "",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "id": 1,
                                    "ticket_type": "type",
                                    "own_type": "own",
                                    "user_id": 1,
                                    "profile_id": 1,
                                    "product_id": 1,
                                    "episode_id": 1,
                                    "rental_expired_date": "2024-08-01T16:00:00",
                                    "createdDate": "2024-08-01T16:00:00",
                                    "updatedDate": "2024-08-01T16:00:00",
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
async def user_productbook_detail_by_id(
    id: int = Path(..., description="사용자 대여권 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    사용자 대여권 상세
    """

    return await user_productbook_service.user_productbook_detail_by_id(id=id, db=db)
