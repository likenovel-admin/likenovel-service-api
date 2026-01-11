from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.user.user_ticketbook_service as user_ticketbook_service

router = APIRouter(prefix="/user-ticketbook")


@router.get(
    "",
    tags=["사용자 이용권"],
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
                                        "user_id": 1,
                                        "product_id": 1,
                                        "use_expired_date": "2024-08-01T16:00:00",
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
async def user_ticketbook_list(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    사용자 이용권 목록
    """

    return await user_ticketbook_service.user_ticketbook_list(
        kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/{id}",
    tags=["사용자 이용권"],
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
                                    "user_id": 1,
                                    "product_id": 1,
                                    "use_expired_date": "2024-08-01T16:00:00",
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
async def user_ticketbook_detail_by_id(
    id: int = Path(..., description="사용자 이용권 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    사용자 이용권 상세
    """

    return await user_ticketbook_service.user_ticketbook_detail_by_id(id=id, db=db)
