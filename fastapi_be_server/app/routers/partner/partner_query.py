from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.partner.partner_basic_service as partner_basic_service
import app.services.partner.partner_product_service as partner_product_service
import app.services.partner.partner_statistics_service as partner_statistics_service
import app.services.partner.partner_sales_service as partner_sales_service
import app.services.partner.partner_income_service as partner_income_service
from app.utils.common import check_user

router = APIRouter(prefix="/partners")


@router.get(
    "/detail/{user_id}",
    tags=["파트너"],
    responses={
        200: {
            "description": "파트너 상세",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "user_id": 1,
                                    "kc_user_id": "kc_user_id",
                                    "email": "user@email.com",
                                    "gender": "M",
                                    "birthdate": "0000-00-00",
                                    "user_name": "이름",
                                    "identity_yn": "N",
                                    "agree_terms_yn": "Y",
                                    "agree_privacy_yn": "Y",
                                    "agree_age_limit_yn": "Y",
                                    "stay_signed_yn": "N",
                                    "latest_signed_date": "2024-08-01T16:00:00",
                                    "latest_signed_type": "likenovel",
                                    "use_yn": "Y",
                                    "role_type": "admin",
                                    "created_date": "2024-08-01T16:00:00",
                                    "updated_date": "2024-08-01T16:00:00",
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
async def partner_detail_by_user_id(
    user_id: int = Path(..., description="파트너의 회원 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 상세
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_basic_service.partner_detail_by_user_id(user_id, db)


@router.get(
    "/detail/{user_id}/profiles",
    tags=["파트너"],
    responses={
        200: {
            "description": "파트너 상세",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "profile_id": 1,
                                        "user_id": 1,
                                        "nickname": "넥네임",
                                        "default_yn": "N",
                                        "role_type": "user",
                                        "profile_image_path": "파일 경로",
                                        "nickname_change_max_count": 3,
                                        "nickname_change_count": 3,
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_date": "2024-08-01T16:00:00",
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
async def partner_profiles_of_partner(
    user_id: int = Path(..., description="파트너의 회원 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 프로필 리스트
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_basic_service.partner_profiles_of_partner(user_id, db)


@router.get(
    "/products",
    tags=["파트너 - 작품"],
    responses={
        200: {
            "description": "작품 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "product_id": 1,
                                        "title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "author_nickname": "로스티플",
                                        "count_episode": 10,
                                        "contract_type": "일반",
                                        "cp_company_name": "라이크노벨",
                                        "paid_open_date": "2024-08-01T16:00:00",
                                        "status_code": "ongoing",
                                        "ratings_code": "all",
                                        "price_type": "paid",
                                        "primary_genre": "1차 장르",
                                        "primary_genre_id": 1,
                                        "sub_genre": "2차 장르",
                                        "sub_genre_id": 2,
                                        "single_regular_price": 10000,
                                        "series_regular_price": 10000,
                                        "monopoly_yn": "Y",
                                        "created_date": "2024-08-01T16:00:00",
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
async def product_list(
    contract_type: str = Query(
        "",
        description="계약 유형(일반 - normal | cp - cp), 선택안한 상태에서는 값이 없거나 비워두세요",
    ),
    status_code: str = Query(
        "",
        description="연재 상태(연재중 - ongoing | 휴재중 - rest | 완결 - end | 연재중지 - stop), 선택안한 상태에서는 값이 없거나 비워두세요",
    ),
    search_target: str = Query(
        "", description="검색 타겟(product-title | product-id | author-name | cp-name)"
    ),
    search_word: str = Query("", description="검색어"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    start_date: Optional[str] = Query(
        None, description="회차별 매출 시작 날짜 (YYYY-MM-DD)"
    ),
    end_date: Optional[str] = Query(
        None, description="회차별 매출 종료 날짜 (YYYY-MM-DD)"
    ),
    from_episode_sales_page: Optional[bool] = Query(
        None, description="회차별 매출 페이지에서 호출 여부"
    ),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 작품 관리 / 작품 리스트
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_product_service.product_list(
        contract_type,
        status_code,
        search_target,
        search_word,
        page,
        count_per_page,
        db,
        user_data,
        start_date,
        end_date,
        from_episode_sales_page,
    )


@router.get(
    "/products/genre",
    tags=["파트너 - 작품"],
    responses={
        200: {
            "description": "작품 장르 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "keyword_id": 19,
                                        "keyword_name": "현대판타지",
                                        "major_genre_yn": "Y",
                                        "filter_yn": "Y",
                                        "category_id": 1,
                                        "use_yn": "Y",
                                        "created_id": 0,
                                        "created_date": "2024-11-27T08:44:31",
                                        "updated_id": 0,
                                        "updated_date": "2024-11-27T08:44:31",
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
async def product_genre_list(
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 작품 관리 / 작품 리스트 - 장르
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_basic_service.get_genre_list(db)


@router.get(
    "/products/all",
    tags=["파트너 - 작품"],
    responses={
        200: {
            "description": "작품 목록 엑셀 다운로드",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "product_id": 1,
                                        "title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "author_nickname": "로스티플",
                                        "count_episode": 10,
                                        "contract_type": "일반",
                                        "cp_company_name": "라이크노벨",
                                        "paid_open_date": "2024-08-01T16:00:00",
                                        "status_code": "ongoing",
                                        "ratings_code": "all",
                                        "price_type": "paid",
                                        "primary_genre": "1차 장르",
                                        "primary_genre_id": 1,
                                        "sub_genre": "2차 장르",
                                        "sub_genre_id": 2,
                                        "single_regular_price": 10000,
                                        "series_regular_price": 10000,
                                        "monopoly_yn": "Y",
                                        "created_date": "2024-08-01T16:00:00",
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
async def product_list_for_download(
    contract_type: str = Query(
        "",
        description="계약 유형(일반 - normal | cp - cp), 선택안한 상태에서는 값이 없거나 비워두세요",
    ),
    status_code: str = Query(
        "",
        description="연재 상태(연재중 - ongoing | 휴재중 - rest | 완결 - end | 연재중지 - stop), 선택안한 상태에서는 값이 없거나 비워두세요",
    ),
    search_target: str = Query(
        "", description="검색 타겟(product-title | product-id | author-name | cp-name)"
    ),
    search_word: str = Query("", description="검색어"),
    start_date: Optional[str] = Query(
        None, description="회차별 매출 시작 날짜 (YYYY-MM-DD)"
    ),
    end_date: Optional[str] = Query(
        None, description="회차별 매출 종료 날짜 (YYYY-MM-DD)"
    ),
    from_episode_sales_page: Optional[bool] = Query(
        None, description="회차별 매출 페이지에서 호출 여부"
    ),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 작품 관리 / 작품 리스트
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_product_service.product_list(
        contract_type,
        status_code,
        search_target,
        search_word,
        -1,
        -1,
        db,
        user_data,
        start_date,
        end_date,
        from_episode_sales_page,
    )


@router.get(
    "/products/cp-company",
    tags=["파트너 - 작품"],
    responses={
        200: {
            "description": "작품 장르 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {"data": [{"company_name": "라이크노벨"}]},
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
async def get_cp_company_name_list(
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 작품 관리 / 작품 리스트 - cp사명
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_basic_service.get_cp_company_name_list(db)


@router.get(
    "/products/{id}",
    tags=["파트너 - 작품"],
    responses={
        200: {
            "description": "작품 상세",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "product_id": 1,
                                    "title": "1세계전복급 악역으로 오해 받고 있습니다",
                                    "author_nickname": "로스티플",
                                    "count_episode": 10,
                                    "contract_type": "일반",
                                    "cp_company_name": "라이크노벨",
                                    "paid_open_date": "2024-08-01T16:00:00",
                                    "status_code": "ongoing",
                                    "ratings_code": "all",
                                    "price_type": "paid",
                                    "primary_genre": "1차 장르",
                                    "primary_genre_id": 1,
                                    "sub_genre": "2차 장르",
                                    "sub_genre_id": 2,
                                    "single_regular_price": 10000,
                                    "series_regular_price": 10000,
                                    "monopoly_yn": "Y",
                                    "blind_yn": "N",
                                    "cp_author_profit": 0.7,
                                    "cp_contract_price": "",
                                    "created_date": "2024-08-01T16:00:00",
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
async def product_detail_by_id(
    id: int = Path(..., description="작품 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 작품 관리 / 작품 리스트
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_product_service.product_detail_by_id(id, db, user_data)


@router.get(
    "/product-statistics",
    tags=["파트너 - 작품별 통계"],
    responses={
        200: {
            "description": "작품별 통계 목록",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "count_episode": 10,
                                        "paid_yn": "N",
                                        "count_hit": 0,
                                        "count_bookmark": 0,
                                        "count_unbookmark": 0,
                                        "count_recommend": 0,
                                        "count_evaluation": 0,
                                        "count_total_sales": 0,
                                        "sum_total_sales_price": 0,
                                        "sales_price_per_count_hit": 0,
                                        "count_cp_hit": 0,
                                        "reading_rate": 0,
                                        "author_id": 1,
                                        "cp_company_name": "CP사명",
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
async def product_statistics_list(
    search_target: str = Query(
        "", description="검색 타겟(product-title | product-id | author-name | cp-name)"
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 통계 분석 > 작품별 통계
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_statistics_service.product_statistics_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        page,
        count_per_page,
        db,
        user_data,
    )


@router.get(
    "/product-statistics/all",
    tags=["파트너 - 작품별 통계"],
    responses={
        200: {
            "description": "작품별 통계 엑셀 다운로드",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "count_episode": 10,
                                        "paid_yn": "N",
                                        "count_hit": 0,
                                        "count_bookmark": 0,
                                        "count_unbookmark": 0,
                                        "count_recommend": 0,
                                        "count_evaluation": 0,
                                        "count_total_sales": 0,
                                        "sum_total_sales_price": 0,
                                        "sales_price_per_count_hit": 0,
                                        "count_cp_hit": 0,
                                        "reading_rate": 0,
                                        "author_id": 1,
                                        "cp_company_name": "CP사명",
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
async def product_statistics_list_for_download(
    search_target: str = Query(
        "", description="검색 타겟(product-title | product-id | author-name | cp-name)"
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 통계 분석 > 작품별 통계
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_statistics_service.product_statistics_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        -1,
        -1,
        db,
        user_data,
    )


@router.get(
    "/product-episode-statistics",
    tags=["파트너 - 회차별 통계"],
    responses={
        200: {
            "description": "회차별 통계 목록",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "episode_no": 10,
                                        "paid_yn": "N",
                                        "count_hit": 0,
                                        "count_recommend": 0,
                                        "count_evaluation": 0,
                                        "count_total_sales": 0,
                                        "sum_total_sales_price": 0,
                                        "sales_price_per_count_hit": 0,
                                        "count_hit_in_24h": 0,
                                        "date": "2024-08-01",
                                        "episode_title": "에피소드명",
                                        "cp_company_name": "담당CP",
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
async def product_episode_statistics_list(
    search_target: str = Query(
        "", description="검색 타겟(product-title | product-id | author-name | cp-name)"
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 통계 분석 > 회차별 통계
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_statistics_service.product_episode_statistics_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        page,
        count_per_page,
        db,
        user_data,
    )


@router.get(
    "/product-episode-statistics/all",
    tags=["파트너 - 회차별 통계"],
    responses={
        200: {
            "description": "회차별 통계 엑셀 다운로드",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "episode_no": 10,
                                        "paid_yn": "N",
                                        "count_hit": 0,
                                        "count_recommend": 0,
                                        "count_evaluation": 0,
                                        "count_total_sales": 0,
                                        "sum_total_sales_price": 0,
                                        "sales_price_per_count_hit": 0,
                                        "count_hit_in_24h": 0,
                                        "date": "2024-08-01",
                                        "episode_title": "에피소드명",
                                        "cp_company_name": "담당CP",
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
async def product_episode_statistics_list_for_download(
    search_target: str = Query(
        "", description="검색 타겟(product-title | product-id | author-name | cp-name)"
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 통계 분석 > 회차별 통계
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_statistics_service.product_episode_statistics_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        -1,
        -1,
        db,
        user_data,
    )


@router.get(
    "/cart-analysis",
    tags=["파트너 - 장바구니 분석"],
    responses={
        200: {
            "description": "장바구니 분석 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "product_id": 1,
                                        "title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_1_product_id": 1,
                                        "relative_1_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_2_product_id": 1,
                                        "relative_2_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_3_product_id": 1,
                                        "relative_3_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_4_product_id": 1,
                                        "relative_4_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_5_product_id": 1,
                                        "relative_5_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_6_product_id": 1,
                                        "relative_6_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_7_product_id": 1,
                                        "relative_7_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_8_product_id": 1,
                                        "relative_8_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_9_product_id": 1,
                                        "relative_9_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_10_product_id": 1,
                                        "relative_10_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
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
async def cart_analysis_list(
    search_target: str = Query("", description="검색 타겟(product-title)"),
    search_word: str = Query("", description="검색어"),
    type: str = Query("bookmark", description="타입(bookmark | tag | similar-user)"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 장바구니 분석
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_statistics_service.cart_analysis_list(
        search_target, search_word, type, page, count_per_page, db, user_data
    )


@router.get(
    "/cart-analysis/all",
    tags=["파트너 - 장바구니 분석"],
    responses={
        200: {
            "description": "장바구니 분석 엑셀 다운로드",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "product_id": 1,
                                        "title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_1_product_id": 1,
                                        "relative_1_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_2_product_id": 1,
                                        "relative_2_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_3_product_id": 1,
                                        "relative_3_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_4_product_id": 1,
                                        "relative_4_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_5_product_id": 1,
                                        "relative_5_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_6_product_id": 1,
                                        "relative_6_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_7_product_id": 1,
                                        "relative_7_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_8_product_id": 1,
                                        "relative_8_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_9_product_id": 1,
                                        "relative_9_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "relative_10_product_id": 1,
                                        "relative_10_product_title": "1세계전복급 악역으로 오해 받고 있습니다",
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
async def cart_analysis_list_for_download(
    search_target: str = Query("", description="검색 타겟(product-title)"),
    search_word: str = Query("", description="검색어"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 장바구니 분석
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_statistics_service.cart_analysis_list(
        search_target, search_word, -1, -1, db, user_data
    )


@router.get(
    "/hourly-inflow",
    tags=["파트너 - 시간별 유입"],
    responses={
        200: {
            "description": "시간별 유입 분석 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "product_id": 1,
                                        "product_type": "normal",
                                        "price_type": "paid",
                                        "title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "synopsis": "1이날이야말로 동소문 안에서 인력거꾼 노릇을 하는 김첨지에게는 오래간만에도 닥친 운수 좋은 날이였다. 문안에(거기도 문밖은 아니지만) 들어간답시는 앞집.",
                                        "author_nickname": "로스티플",
                                        "illustrator_nickname": "",
                                        "adult_yn": "N",
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
async def hourly_inflow_product_list(
    search_target: str = Query("", description="검색 타겟(product-title)"),
    search_word: str = Query("", description="검색어"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 통계 분석 > 시간별 유입 분석
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_statistics_service.hourly_inflow_product_list(
        search_target, search_word, page, count_per_page, db, user_data
    )


@router.get(
    "/hourly-inflow/all",
    tags=["파트너 - 시간별 유입"],
    responses={
        200: {
            "description": "시간별 유입 분석 엑셀 다운로드",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "productId": 1,
                                        "productType": "normal",
                                        "priceType": "paid",
                                        "title": "1세계전복급 악역으로 오해 받고 있습니다",
                                        "synopsis": "1이날이야말로 동소문 안에서 인력거꾼 노릇을 하는 김첨지에게는 오래간만에도 닥친 운수 좋은 날이였다. 문안에(거기도 문밖은 아니지만) 들어간답시는 앞집.",
                                        "authorNickname": "로스티플",
                                        "illustratorNickname": "",
                                        "adultYn": "N",
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
async def hourly_inflow_product_list_for_download(
    search_target: str = Query("", description="검색 타겟(product-title)"),
    search_word: str = Query("", description="검색어"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 통계 분석 > 시간별 유입 분석
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_statistics_service.hourly_inflow_product_list(
        search_target, search_word, -1, -1, db, user_data
    )


@router.get(
    "/hourly-inflow/{id}",
    tags=["파트너 - 시간별 유입"],
    responses={
        200: {
            "description": "특정 작품의 시간별 유입 분석",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "hour": 1,
                                        "total_view_count": 0,
                                        "total_payment_count": 0,
                                        "male_view_count": 0,
                                        "female_view_count": 0,
                                        "male_payment_count": 0,
                                        "female_payment_count": 0,
                                        "male_20_under_payment_count": 0,
                                        "male_30_payment_count": 0,
                                        "male_40_payment_count": 0,
                                        "male_50_payment_count": 0,
                                        "male_60_over_payment_count": 0,
                                        "female_20_under_payment_count": 0,
                                        "female_30_payment_count": 0,
                                        "female_40_payment_count": 0,
                                        "female_50_payment_count": 0,
                                        "female_60_over_payment_count": 0,
                                        "male_20_under_view_count": 0,
                                        "male_30_view_count": 0,
                                        "male_40_view_count": 0,
                                        "male_50_view_count": 0,
                                        "male_60_over_view_count": 0,
                                        "female_20_under_view_count": 0,
                                        "female_30_view_count": 0,
                                        "female_40_view_count": 0,
                                        "female_50_view_count": 0,
                                        "female_60_over_view_count": 0,
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
async def hourly_inflow_detail_by_product_id(
    id: int = Path(..., description="작품 번호"),
    search_date: str = Query(
        "",
        description="날짜 검색, 이 값이 없으면 전체 날짜를 기준으로 각 시간별 통계값의 합이 리턴됩니다",
    ),
    search_target: str = Query("", description="검색 타겟(product-title)"),
    search_word: str = Query("", description="검색어"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 통계 분석 > 시간별 유입 분석
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_statistics_service.hourly_inflow_detail_by_product_id(
        id, search_date, search_target, search_word, db, user_data
    )


@router.get(
    "/monthly-sales-by-product",
    tags=["파트너 - 작품별 월매출"],
    responses={
        200: {
            "description": "작품별 월매출 목록",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "contract_type": "cp",
                                        "cp_company_name": "cp 회사명",
                                        "paid_open_date": "2024-08-01",
                                        "isbn": "isbn",
                                        "uci": "uci",
                                        "series_regular_price": 100,
                                        "sale_price": 100,
                                        "sum_normal_price_web": 100,
                                        "sum_normal_price_playstore": 100,
                                        "sum_normal_price_ios": 100,
                                        "sum_normal_price_onestore": 100,
                                        "sum_ticket_price_web": 100,
                                        "sum_ticket_price_playstore": 100,
                                        "sum_ticket_price_ios": 100,
                                        "sum_ticket_price_onestore": 100,
                                        "sum_comped_ticket_price": 100,
                                        "fee_web": 100,
                                        "fee_playstore": 100,
                                        "fee_ios": 100,
                                        "fee_onestore": 100,
                                        "fee_comped_ticket": 100,
                                        "sum_refund_price_web": 100,
                                        "sum_refund_price_playstore": 100,
                                        "sum_refund_price_ios": 100,
                                        "sum_refund_price_onestore": 100,
                                        "sum_refund_comped_ticket_price": 100,
                                        "settlement_rate_web": 100,
                                        "settlement_rate_playstore": 100,
                                        "settlement_rate_ios": 100,
                                        "settlement_rate_onestore": 100,
                                        "settlement_rate_comped_ticket": 100,
                                        "sum_settlement_price_web": 100,
                                        "sum_settlement_comped_ticket_price": 100,
                                        "tax_price": 100,
                                        "total_price": 100,
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
async def monthly_sales_by_product_list(
    search_target: str = Query(
        "", description="검색 타겟(product-title | product-id | author-name | cp-name)"
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 작품별 월매출
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_sales_service.monthly_sales_by_product_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        page,
        count_per_page,
        db,
        user_data,
    )


@router.get(
    "/monthly-sales-by-product/all",
    tags=["파트너 - 작품별 월매출"],
    responses={
        200: {
            "description": "작품별 월매출 엑셀 다운로드",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "contract_type": "cp",
                                        "cp_company_name": "cp 회사명",
                                        "paid_open_date": "2024-08-01",
                                        "isbn": "isbn",
                                        "uci": "uci",
                                        "series_regular_price": 100,
                                        "sale_price": 100,
                                        "sum_normal_price_web": 100,
                                        "sum_normal_price_playstore": 100,
                                        "sum_normal_price_ios": 100,
                                        "sum_normal_price_onestore": 100,
                                        "sum_ticket_price_web": 100,
                                        "sum_ticket_price_playstore": 100,
                                        "sum_ticket_price_ios": 100,
                                        "sum_ticket_price_onestore": 100,
                                        "sum_comped_ticket_price": 100,
                                        "fee_web": 100,
                                        "fee_playstore": 100,
                                        "fee_ios": 100,
                                        "fee_onestore": 100,
                                        "fee_comped_ticket": 100,
                                        "sum_refund_price_web": 100,
                                        "sum_refund_price_playstore": 100,
                                        "sum_refund_price_ios": 100,
                                        "sum_refund_price_onestore": 100,
                                        "sum_refund_comped_ticket_price": 100,
                                        "settlement_rate_web": 100,
                                        "settlement_rate_playstore": 100,
                                        "settlement_rate_ios": 100,
                                        "settlement_rate_onestore": 100,
                                        "settlement_rate_comped_ticket": 100,
                                        "sum_settlement_price_web": 100,
                                        "sum_settlement_comped_ticket_price": 100,
                                        "tax_price": 100,
                                        "total_price": 100,
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
async def monthly_sales_by_product_list_for_download(
    search_target: str = Query(
        "", description="검색 타겟(product-title | product-id | author-name | cp-name)"
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 작품별 월매출
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_sales_service.monthly_sales_by_product_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        -1,
        -1,
        db,
        user_data,
    )


@router.get(
    "/monthly-sales-by-product/{id}",
    tags=["파트너 - 작품별 월매출"],
    responses={
        200: {
            "description": "특정 작품의 월매출",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "id": 1,
                                    "product_id": 1,
                                    "title": "작품명",
                                    "author_nickname": "작가명",
                                    "contract_type": "cp",
                                    "cp_company_name": "cp 회사명",
                                    "paid_open_date": "2024-08-01",
                                    "isbn": "isbn",
                                    "uci": "uci",
                                    "series_regular_price": 100,
                                    "sale_price": 100,
                                    "sum_normal_price_web": 100,
                                    "sum_normal_price_playstore": 100,
                                    "sum_normal_price_ios": 100,
                                    "sum_normal_price_onestore": 100,
                                    "sum_ticket_price_web": 100,
                                    "sum_ticket_price_playstore": 100,
                                    "sum_ticket_price_ios": 100,
                                    "sum_ticket_price_onestore": 100,
                                    "sum_comped_ticket_price": 100,
                                    "fee_web": 100,
                                    "fee_playstore": 100,
                                    "fee_ios": 100,
                                    "fee_onestore": 100,
                                    "fee_comped_ticket": 100,
                                    "sum_refund_price_web": 100,
                                    "sum_refund_price_playstore": 100,
                                    "sum_refund_price_ios": 100,
                                    "sum_refund_price_onestore": 100,
                                    "sum_refund_comped_ticket_price": 100,
                                    "settlement_rate_web": 100,
                                    "settlement_rate_playstore": 100,
                                    "settlement_rate_ios": 100,
                                    "settlement_rate_onestore": 100,
                                    "settlement_rate_comped_ticket": 100,
                                    "sum_settlement_price_web": 100,
                                    "sum_settlement_comped_ticket_price": 100,
                                    "tax_price": 100,
                                    "total_price": 100,
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
async def monthly_sales_by_product_detail_by_product_id(
    id: int = Path(..., description="작품 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 작품별 월매출
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_sales_service.monthly_sales_by_product_detail_by_product_id(
        id, db
    )


@router.get(
    "/sales-by-episode",
    tags=["파트너 - 회차별 매출"],
    responses={
        200: {
            "description": "회차별 매출 목록",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "episode_no": 10,
                                        "episode_title": "에피소드명",
                                        "contract_type": "cp",
                                        "cp_company_name": "cp 회사명",
                                        "paid_open_date": "2024-08-01",
                                        "count_total_sales": 10,
                                        "sum_total_sales_price": 1000,
                                        "count_normal_sales": 10,
                                        "sum_normal_price": 1000,
                                        "count_discount_sales": 10,
                                        "sum_discount_price": 1000,
                                        "count_paid_ticket_sales": 10,
                                        "sum_paid_ticket_price": 1000,
                                        "count_comped_ticket_sales": 10,
                                        "sum_comped_ticket_price": 1000,
                                        "count_free_ticket_sales": 10,
                                        "sum_free_ticket_price": 1000,
                                        "count_total_refund": 10,
                                        "sum_total_refund_price": 1000,
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
async def sales_by_episode_list(
    search_target: str = Query(
        "", description="검색 타겟(product-title | product-id | author-name | cp-name)"
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 회차별 매출
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_sales_service.sales_by_episode_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        page,
        count_per_page,
        db,
        user_data,
    )


@router.get(
    "/sales-by-episode/all",
    tags=["파트너 - 회차별 매출"],
    responses={
        200: {
            "description": "회차별 매출 엑셀 다운로드",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "episode_no": 10,
                                        "episode_title": "에피소드명",
                                        "contract_type": "cp",
                                        "cp_company_name": "cp 회사명",
                                        "paid_open_date": "2024-08-01",
                                        "count_total_sales": 10,
                                        "sum_total_sales_price": 1000,
                                        "count_normal_sales": 10,
                                        "sum_normal_price": 1000,
                                        "count_discount_sales": 10,
                                        "sum_discount_price": 1000,
                                        "count_paid_ticket_sales": 10,
                                        "sum_paid_ticket_price": 1000,
                                        "count_comped_ticket_sales": 10,
                                        "sum_comped_ticket_price": 1000,
                                        "count_free_ticket_sales": 10,
                                        "sum_free_ticket_price": 1000,
                                        "count_total_refund": 10,
                                        "sum_total_refund_price": 1000,
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
async def sales_by_episode_list_for_download(
    search_target: str = Query(
        "", description="검색 타겟(product-title | product-id | author-name | cp-name)"
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 회차별 매출
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_sales_service.sales_by_episode_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        -1,
        -1,
        db,
        user_data,
    )


@router.get(
    "/sales-by-episode/{id}",
    tags=["파트너 - 회차별 매출"],
    responses={
        200: {
            "description": "특정 작품의 회차별 매출 목록",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "episode_no": 10,
                                        "episode_title": "에피소드명",
                                        "contract_type": "cp",
                                        "cp_company_name": "cp 회사명",
                                        "paid_open_date": "2024-08-01",
                                        "count_total_sales": 10,
                                        "sum_total_sales_price": 1000,
                                        "count_normal_sales": 10,
                                        "sum_normal_price": 1000,
                                        "count_discount_sales": 10,
                                        "sum_discount_price": 1000,
                                        "count_paid_ticket_sales": 10,
                                        "sum_paid_ticket_price": 1000,
                                        "count_comped_ticket_sales": 10,
                                        "sum_comped_ticket_price": 1000,
                                        "count_free_ticket_sales": 10,
                                        "sum_free_ticket_price": 1000,
                                        "count_total_refund": 10,
                                        "sum_total_refund_price": 1000,
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
async def sales_by_episode_list_by_product_id(
    id: int = Path(..., description="작품 번호"),
    search_target: str = Query("", description="검색 타겟(product-title)"),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 회차별 매출
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_sales_service.sales_by_episode_list_by_product_id(
        id,
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        page,
        count_per_page,
        db,
    )


@router.get(
    "/sales-by-episode/{id}/all",
    tags=["파트너 - 회차별 매출"],
    responses={
        200: {
            "description": "특정 작품의 회차별 매출 엑셀 다운로드",
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
                                        "title": "작품명",
                                        "author_nickname": "작품명",
                                        "episode_no": 10,
                                        "contract_type": "cp",
                                        "cp_company_name": "cp 회사명",
                                        "paid_open_date": "2024-08-01",
                                        "count_total_sales": 10,
                                        "sum_total_sales_price": 1000,
                                        "count_normal_sales": 10,
                                        "sum_normal_price": 1000,
                                        "count_discount_sales": 10,
                                        "sum_discount_price": 1000,
                                        "count_paid_ticket_sales": 10,
                                        "sum_paid_ticket_price": 1000,
                                        "count_comped_ticket_sales": 10,
                                        "sum_comped_ticket_price": 1000,
                                        "count_free_ticket_sales": 10,
                                        "sum_free_ticket_price": 1000,
                                        "count_total_refund": 10,
                                        "sum_total_refund_price": 1000,
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
async def sales_by_episode_list_by_product_id_for_download(
    id: int = Path(..., description="작품 번호"),
    search_target: str = Query("", description="검색 타겟(product-title)"),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 회차별 매출
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_sales_service.sales_by_episode_list_by_product_id(
        id, search_target, search_word, search_start_date, search_end_date, -1, -1, db
    )


@router.get(
    "/daily-ticket",
    tags=["파트너 - 일별 이용권 상세"],
    responses={
        200: {
            "description": "일별 이용권 상세 목록",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "contract_type": "cp",
                                        "cp_company_name": "cp 회사명",
                                        "paid_open_date": "2024-08-01",
                                        "isbn": "isbn",
                                        "uci": "uci",
                                        "episode_no": 10,
                                        "item_name": "상품명",
                                        "count_ticket_usage": 1,
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
async def daily_ticket_list(
    search_target: str = Query(
        "", description="검색 타겟(product-title | product-id | author-name | cp-name)"
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 일별 이용권 상세
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_sales_service.daily_ticket_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        page,
        count_per_page,
        db,
        user_data,
    )


@router.get(
    "/daily-ticket/all",
    tags=["파트너 - 일별 이용권 상세"],
    responses={
        200: {
            "description": "일별 이용권 상세 엑셀 다운로드",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "contract_type": "cp",
                                        "cp_company_name": "cp 회사명",
                                        "paid_open_date": "2024-08-01",
                                        "isbn": "isbn",
                                        "uci": "uci",
                                        "episode_no": 10,
                                        "item_name": "상품명",
                                        "count_ticket_usage": 1,
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
async def daily_ticket_list_for_download(
    search_target: str = Query(
        "", description="검색 타겟(product-title | product-id | author-name | cp-name)"
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 일별 이용권 상세
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_sales_service.daily_ticket_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        -1,
        -1,
        db,
        user_data,
    )


@router.get(
    "/monthly-settlement",
    tags=["파트너 - 월별 정산"],
    responses={
        200: {
            "description": "월별 정산 목록",
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
                                        "item_type": "sponsorship",
                                        "device_type": "web",
                                        "sum_total_sales_price": 1000,
                                        "fee": 0,
                                        "net_sales_price": 1000,
                                        "taxable_price": 1000,
                                        "vat_price": 0,
                                        "settlement_price": 909,
                                        "platform_revenue": 0,
                                        "privious_offer_amount": 500,
                                        "current_offer_amount": 500,
                                        "final_settlement_price": 500,
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
async def monthly_settlement_list(
    search_target: str = Query("", description="검색 타겟(author-name | cp-name)"),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 월별 정산
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_sales_service.monthly_settlement_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        page,
        count_per_page,
        db,
        user_data,
    )


@router.get(
    "/monthly-settlement/all",
    tags=["파트너 - 월별 정산"],
    responses={
        200: {
            "description": "월별 정산 엑셀 다운로드",
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
                                        "item_type": "sponsorship",
                                        "device_type": "web",
                                        "sum_total_sales_price": 1000,
                                        "fee": 0,
                                        "net_sales_price": 1000,
                                        "taxable_price": 1000,
                                        "vat_price": 0,
                                        "settlement_price": 909,
                                        "platform_revenue": 0,
                                        "privious_offer_amount": 500,
                                        "current_offer_amount": 500,
                                        "final_settlement_price": 500,
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
async def monthly_settlement_list_for_download(
    search_target: str = Query("", description="검색 타겟(author-name | cp-name)"),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 월별 정산
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_sales_service.monthly_settlement_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        -1,
        -1,
        db,
        user_data,
    )


@router.get(
    "/product-contract-offer-deduction",
    tags=["파트너 - 선계약금 차감 조회"],
    responses={
        200: {
            "description": "선계약금 차감 조회 목록",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "contract_type": "cp",
                                        "cp_company_name": "cp 회사명",
                                        "offer_amount": 1000,
                                        "privious_offer_amount": 300,
                                        "settlement_price": 300,
                                        "current_offer_amount": 700,
                                        "createdDate": "2024-08-01T16:00:00",
                                        "updatedDate": "2024-08-01T16:00:00",
                                        "offer_id": 1,
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
async def product_contract_offer_deduction_list(
    search_target: str = Query(
        "", description="검색 타겟(product-title | product-id | author-name | cp-name)"
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 선계약금 차감 조회
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_sales_service.product_contract_offer_deduction_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        page,
        count_per_page,
        db,
        user_data,
    )


@router.get(
    "/product-contract-offer-deduction/all",
    tags=["파트너 - 선계약금 차감 조회"],
    responses={
        200: {
            "description": "선계약금 차감 조회 엑셀 다운로드",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "contract_type": "cp",
                                        "cp_company_name": "cp 회사명",
                                        "offer_amount": 1000,
                                        "privious_offer_amount": 300,
                                        "settlement_price": 300,
                                        "current_offer_amount": 700,
                                        "createdDate": "2024-08-01T16:00:00",
                                        "updatedDate": "2024-08-01T16:00:00",
                                        "offer_id": 1,
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
async def product_contract_offer_deduction_list_for_download(
    search_target: str = Query(
        "", description="검색 타겟(product-title | product-id | author-name | cp-name)"
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 선계약금 차감 조회
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_sales_service.product_contract_offer_deduction_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        -1,
        -1,
        db,
        user_data,
    )


@router.get(
    "/sponsorship-recodes",
    tags=["파트너 - 후원 내역"],
    responses={
        200: {
            "description": "후원 내역 목록",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "user_name": "후원자명",
                                        "donation_price": 1000,
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
async def sponsorship_recodes_list(
    search_target: str = Query(
        "",
        description="검색 타겟(product-title | product-id | author-name | sponsor-name)",
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 후원 내역
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_income_service.sponsorship_recodes_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        page,
        count_per_page,
        db,
        user_data,
    )


@router.get(
    "/sponsorship-recodes/all",
    tags=["파트너 - 후원 내역"],
    responses={
        200: {
            "description": "후원 내역 엑셀 다운로드",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "user_name": "후원자명",
                                        "donation_price": 1000,
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
async def sponsorship_recodes_list_for_download(
    search_target: str = Query(
        "",
        description="검색 타겟(product-title | product-id | author-name | sponsor-name)",
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 후원 내역
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_income_service.sponsorship_recodes_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        -1,
        -1,
        db,
        user_data,
    )


@router.get(
    "/income-recodes",
    tags=["파트너 - 기타 수익 내역"],
    responses={
        200: {
            "description": "기타 수익 내역 목록",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "item_type": "sponsorship",
                                        "sum_income_price": 1000,
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
async def income_recodes_list(
    search_target: str = Query(
        "",
        description="검색 타겟(product-title | product-id | author-name | sponsor-name)",
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    item_type: str = Query("", description="수익 내역(후원-sponsorship | 광고-ad)"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 기타 수익 내역
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_income_service.income_recodes_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        item_type,
        page,
        count_per_page,
        db,
        user_data,
    )


@router.get(
    "/income-recodes/all",
    tags=["파트너 - 기타 수익 내역"],
    responses={
        200: {
            "description": "기타 수익 내역 엑셀 다운로드",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "item_type": "sponsorship",
                                        "sum_income_price": 1000,
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
async def income_recodes_list_for_download(
    search_target: str = Query(
        "",
        description="검색 타겟(product-title | product-id | author-name | sponsor-name)",
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    item_type: str = Query("", description="수익 내역(후원-sponsorship | 광고-ad)"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 기타 수익 내역
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_income_service.income_recodes_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        item_type,
        -1,
        -1,
        db,
        user_data,
    )


@router.get(
    "/income-settlement",
    tags=["파트너 - 후원 및 기타 정산"],
    responses={
        200: {
            "description": "후원 및 기타 정산 목록",
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
                                        "item_type": "sponsorship",
                                        "device_type": "web",
                                        "sum_income_price": 1000,
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
async def income_settlement_list(
    search_target: str = Query("", description="검색 타겟(author-name)"),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 후원 및 기타 정산
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_income_service.income_settlement_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        page,
        count_per_page,
        db,
        user_data,
    )


@router.get(
    "/income-settlement/all",
    tags=["파트너 - 후원 및 기타 정산"],
    responses={
        200: {
            "description": "후원 및 기타 정산 엑셀 다운로드",
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
                                        "item_type": "sponsorship",
                                        "device_type": "web",
                                        "sum_income_price": 1000,
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
async def income_settlement_list_for_download(
    search_target: str = Query("", description="검색 타겟(author-name)"),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 후원 및 기타 정산
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_income_service.income_settlement_list(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        -1,
        -1,
        db,
        user_data,
    )


@router.get(
    "/income-settlement/summary",
    tags=["파트너 - 후원 및 기타 정산"],
    responses={
        200: {
            "description": "후원 및 기타 정산 요약 데이터 조회",
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
                                        "item_type": "own",
                                        "device_type": "web",
                                        "sum_income_price": 1000,
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
async def income_settlement_summary(
    search_month: str = Query("", description="조회할 년월 (yyyy-mm)"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 매출 및 정산 > 후원 및 기타 정산
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_income_service.income_settlement_summary(
        search_month, db, user_data
    )


@router.get(
    "/product-discovery-statistics",
    tags=["파트너 - 발굴 통계"],
    responses={
        200: {
            "description": "발굴 통계 발굴작품 목록",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "count_episode": 10,
                                        "count_hit": 100,
                                        "count_hit_per_episode": 10,
                                        "count_read_user": 10,
                                        "count_bookmark": 5,
                                        "count_unbookmark": 3,
                                        "count_recommend": 10,
                                        "count_evaluation": 10,
                                        "count_cp_hit": 1,
                                        "reading_rate": 0,
                                        "writing_count_per_week": 0,
                                        "count_interest_sustain": 0,
                                        "count_interest_loss": 0,
                                        "primary_reader_group1": None,
                                        "primary_reader_group2": None,
                                        "primary_genre": "1차 장르",
                                        "sub_genre": "2차 장르",
                                        "score1": 0,
                                        "score2": 0,
                                        "score3": 0,
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
async def product_discovery_statistics_list(
    search_target: str = Query("", description="검색 타겟(story | keyword-genre)"),
    search_word: str = Query("", description="검색어"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 발굴 통계 발굴작품 조회
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_statistics_service.product_discovery_statistics_list(
        search_target, search_word, page, count_per_page, db, user_data
    )


@router.get(
    "/product-discovery-statistics/all",
    tags=["파트너 - 발굴 통계"],
    responses={
        200: {
            "description": "발굴 통계 발굴작품 엑셀 다운로드",
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
                                        "title": "작품명",
                                        "author_nickname": "작가명",
                                        "count_episode": 10,
                                        "count_hit": 100,
                                        "count_hit_per_episode": 10,
                                        "count_read_user": 10,
                                        "count_bookmark": 5,
                                        "count_unbookmark": 3,
                                        "count_recommend": 10,
                                        "count_evaluation": 10,
                                        "count_cp_hit": 1,
                                        "reading_rate": 0,
                                        "writing_count_per_week": 0,
                                        "count_interest_sustain": 0,
                                        "count_interest_loss": 0,
                                        "primary_reader_group1": None,
                                        "primary_reader_group2": None,
                                        "primary_genre": "1차 장르",
                                        "sub_genre": "2차 장르",
                                        "score1": 0,
                                        "score2": 0,
                                        "score3": 0,
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
async def product_discovery_statistics_list_for_download(
    search_target: str = Query("", description="검색 타겟(story | keyword-genre)"),
    search_word: str = Query("", description="검색어"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 발굴 통계 발굴작품 조회
    """
    try:
        user_data = await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_statistics_service.product_discovery_statistics_list(
        search_target, search_word, -1, -1, db, user_data
    )


@router.get(
    "/product-discovery-statistics/{id}",
    tags=["파트너 - 발굴 통계"],
    responses={
        200: {
            "description": "발굴 통계 발굴작품 상세",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "product_id": 1,
                                    "title": "타이틀",
                                    "author_nickname": "작가명",
                                    "count_episode": 1,
                                    "contract_type": "일반",
                                    "cp_company_name": "cp회사명",
                                    "created_date": "2024-08-01T16:00:00",
                                    "paid_open_date": "2024-08-01T16:00:00",
                                    "isbn": "isbn",
                                    "uci": "uci",
                                    "status_code": "ongoing",
                                    "ratings_code": "all",
                                    "paid_yn": "Y",
                                    "primary_genre": "1차 장르",
                                    "sub_genre": "2차 장르",
                                    "single_regular_price": 1000,
                                    "series_regular_price": 1000,
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
async def product_discovery_statistics_detail_by_id(
    id: int = Path(..., description="발굴작품 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    파트너 - 발굴 통계 발굴작품 조회
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db)
    except Exception as e:
        raise e

    return await partner_statistics_service.product_discovery_statistics_detail_by_id(
        id, db
    )
