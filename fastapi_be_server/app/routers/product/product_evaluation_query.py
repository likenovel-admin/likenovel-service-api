from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger
import app.services.product.product_evaluation_service as product_evaluation_service

router = APIRouter(prefix="/product-evaluation")


@router.get(
    "",
    tags=["작품 평가"],
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
                                        "product_id": 1,
                                        "episode_id": 1,
                                        "user_id": 1,
                                        "eval_code": "eval_code",
                                        "use_yn": "Y",
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
async def product_evaluation_list(db: AsyncSession = Depends(get_likenovel_db)):
    """
    작품 평가 목록
    """

    return await product_evaluation_service.product_evaluation_list(db=db)


@router.get(
    "/{id}",
    tags=["작품 평가"],
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
                                    "product_id": 1,
                                    "episode_id": 1,
                                    "user_id": 1,
                                    "eval_code": "eval_code",
                                    "use_yn": "Y",
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
async def product_evaluation_detail_by_id(
    id: int = Path(..., description="작품 평가 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 평가 상세
    """

    return await product_evaluation_service.product_evaluation_detail_by_id(
        id=id, db=db
    )
