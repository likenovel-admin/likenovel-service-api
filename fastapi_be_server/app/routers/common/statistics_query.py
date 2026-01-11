from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger
import app.services.common.statistics_service as statistics_service

router = APIRouter(prefix="/statistics")


@router.get(
    "/site",
    tags=["site 통계"],
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
                                    "total_count": 1,
                                    "page": 1,
                                    "count_per_page": 8,
                                    "results": [
                                        {
                                            "date": "2024-08-01",
                                            "visitors": 10,
                                            "page_view": 10,
                                            "login_count": 10,
                                            "signin_count": 10,
                                            "signoff_count": 10,
                                            "DAU": 10,
                                            "MAU": 10,
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
async def site_statistics(
    start_date: str | None = Query(None, description="시작 날짜"),
    end_date: str | None = Query(None, description="종료 날짜"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    site 통계
    """

    return await statistics_service.site_statistics(
        start_date, end_date, page, count_per_page, db
    )


@router.get(
    "/site/all",
    tags=["site 통계"],
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
                                        "date": "2024-08-01",
                                        "visitors": 10,
                                        "page_view": 10,
                                        "login_count": 10,
                                        "signin_count": 10,
                                        "signoff_count": 10,
                                        "DAU": 10,
                                        "MAU": 10,
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
async def site_statistics_for_excel_download(
    start_date: str | None = Query(None, description="시작 날짜"),
    end_date: str | None = Query(None, description="종료 날짜"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    site 통계
    """

    return await statistics_service.site_statistics(start_date, end_date, -1, -1, db)


@router.get(
    "/payment",
    tags=["결제 통계"],
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
                                    "total_count": 1,
                                    "page": 1,
                                    "count_per_page": 8,
                                    "results": [
                                        {
                                            "date": "2024-08-01",
                                            "pay_count": 10,
                                            "pay_coin": 10,
                                            "pay_amount": 10,
                                            "use_coin_count": 10,
                                            "use_coin": 10,
                                            "donation_count": 10,
                                            "donation_coin": 10,
                                            "ad_revenue": 10,
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
async def payment_statistics(
    start_date: str = Query(None, description="시작 날짜"),
    end_date: str = Query(None, description="종료 날짜"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    결제 통계
    """

    return await statistics_service.payment_statistics(
        start_date, end_date, page, count_per_page, db
    )


@router.get(
    "/payment/all",
    tags=["결제 통계"],
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
                                        "date": "2024-08-01",
                                        "pay_count": 10,
                                        "pay_coin": 10,
                                        "pay_amount": 10,
                                        "use_coin_count": 10,
                                        "use_coin": 10,
                                        "donation_count": 10,
                                        "donation_coin": 10,
                                        "ad_revenue": 10,
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
async def payment_statistics_for_excel_download(
    start_date: str = Query(None, description="시작 날짜"),
    end_date: str = Query(None, description="종료 날짜"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    결제 통계
    """

    return await statistics_service.payment_statistics(start_date, end_date, -1, -1, db)


@router.get(
    "/payment-by-user",
    tags=["회원별 결제 통계"],
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
                                    "total_count": 1,
                                    "page": 1,
                                    "count_per_page": 8,
                                    "results": [
                                        {
                                            "date": "2024-08-01",
                                            "email": "test@test.com",
                                            "nickname": "test",
                                            "pay_count": 10,
                                            "pay_coin": 10,
                                            "pay_amount": 10,
                                            "use_coin_count": 10,
                                            "use_coin": 10,
                                            "donation_count": 10,
                                            "donation_coin": 10,
                                            "ad_revenue": 10,
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
async def payment_statistics_by_user(
    start_date: str | None = Query(None, description="시작 날짜"),
    end_date: str | None = Query(None, description="종료 날짜"),
    search_target: str = Query("", description="검색 타겟(email | nickname)"),
    search_word: str = Query("", description="검색어"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    회원별 결제 통계
    """

    return await statistics_service.payment_statistics_by_user(
        start_date, end_date, search_target, search_word, page, count_per_page, db
    )


@router.get(
    "/payment-by-user/all",
    tags=["회원별 결제 통계"],
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
                                        "date": "2024-08-01",
                                        "email": "test@test.com",
                                        "nickname": "test",
                                        "pay_count": 10,
                                        "pay_coin": 10,
                                        "pay_amount": 10,
                                        "use_coin_count": 10,
                                        "use_coin": 10,
                                        "donation_count": 10,
                                        "donation_coin": 10,
                                        "ad_revenue": 10,
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
async def payment_statistics_by_user_for_excel_download(
    start_date: str = Query(None, description="시작 날짜"),
    end_date: str = Query(None, description="종료 날짜"),
    search_target: str = Query("", description="검색 타겟(email | nickname)"),
    search_word: str = Query("", description="검색어"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    회원별 결제 통계
    """

    return await statistics_service.payment_statistics_by_user(
        start_date, end_date, search_target, search_word, -1, -1, db
    )
