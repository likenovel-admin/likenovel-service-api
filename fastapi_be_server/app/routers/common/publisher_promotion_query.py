from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger
import app.services.common.publisher_promotion_service as publisher_promotion_service

router = APIRouter(prefix="/publisher-promotions")


@router.get(
    "",
    tags=["출판사 프로모션"],
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
                                        "id": 4,
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
async def publisher_promotion_list(db: AsyncSession = Depends(get_likenovel_db)):
    """
    출판사 프로모션 목록
    """

    return await publisher_promotion_service.publisher_promotion_list(db=db)


@router.get(
    "/{id}",
    tags=["출판사 프로모션"],
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
async def publisher_promotion_detail_by_id(
    id: int = Path(..., description="출판사 프로모션 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    출판사 프로모션 상세
    """

    return await publisher_promotion_service.publisher_promotion_detail_by_id(
        id=id, db=db
    )
