from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger
import app.services.common.ticket_item_service as ticket_item_service

router = APIRouter(prefix="/ticket-items")


@router.get(
    "",
    tags=["이용권/대여권"],
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
                                        "ticket_id": 1,
                                        "ticket_type": "type",
                                        "ticket_name": "name",
                                        "price": 0,
                                        "settlement_yn": "N",
                                        "expired_hour": 0,
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
async def ticket_item_list(db: AsyncSession = Depends(get_likenovel_db)):
    """
    이용권/대여권 목록
    """

    return await ticket_item_service.ticket_item_list(db=db)


@router.get(
    "/{id}",
    tags=["이용권/대여권"],
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
                                    "ticket_id": 1,
                                    "ticket_type": "type",
                                    "ticket_name": "name",
                                    "price": 0,
                                    "settlement_yn": "N",
                                    "expired_hour": 0,
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
async def ticket_item_detail_by_id(
    id: int = Path(..., description="이용권/대여권 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    이용권/대여권 상세
    """

    return await ticket_item_service.ticket_item_detail_by_id(id=id, db=db)
