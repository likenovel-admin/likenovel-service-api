from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
from app.services.admin import (
    admin_basic_service,
    admin_content_service,
    admin_event_service,
    admin_faq_service,
    admin_notification_service,
    admin_promotion_service,
    admin_quest_service,
    admin_recommend_service,
    admin_system_service,
    admin_user_service,
)
from app.utils.common import check_user

router = APIRouter(prefix="/admins")


@router.get(
    "/detail/{user_id}",
    tags=["CMS - 관리자"],
    responses={
        200: {
            "description": "관리자 상세",
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
async def admin_detail_by_uuid(
    user_id: int = Path(..., description="관리자의 회원 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    관리자 상세
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_basic_service.admin_detail_by_user_id(user_id, db)


@router.get(
    "/detail/{user_id}/profiles",
    tags=["CMS - 관리자"],
    responses={
        200: {
            "description": "관리자 상세",
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
async def admin_profiles_of_admin(
    user_id: int = Path(..., description="관리자의 회원 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    관리자 프로필 리스트
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_basic_service.admin_profiles_of_admin(user_id, db)


@router.get(
    "/users",
    tags=["CMS - 회원"],
    responses={
        200: {
            "description": "회원 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "user_id": 1,
                                        "name": "이름",
                                        "nickname": "닉네임",
                                        "email": "email@admin.com",
                                        "phone": "010-1234-1234",
                                        "created_date": "2025-07-30T01:48:59",
                                        "latest_signed_date": "2025-07-30T01:48:59",
                                        "signoff_date": "2025-07-30T01:48:59",
                                        "agree_terms_yn": "Y",
                                        "noti_yn": "Y",
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
async def user_list(
    status: str = Query("all", description="상태(all | normal | admin | signout)"),
    search_target: str = Query(
        "", description="검색 타겟(nickname | name | contact | email)"
    ),
    search_word: str = Query("", description="검색어"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    회원 목록
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_user_service.user_list(
        status, search_target, search_word, page, count_per_page, db
    )


@router.get(
    "/users/all",
    tags=["CMS - 회원"],
    responses={
        200: {
            "description": "회원 목록 엑셀 다운로드",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "user_id": 1,
                                        "name": "이름",
                                        "nickname": "닉네임",
                                        "email": "email@admin.com",
                                        "phone": "010-1234-1234",
                                        "created_date": "2025-07-30T01:48:59",
                                        "latest_signed_date": "2025-07-30T01:48:59",
                                        "signoff_date": "2025-07-30T01:48:59",
                                        "agree_terms_yn": "Y",
                                        "noti_yn": "Y",
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
async def user_list_for_download(
    status: str = Query("all", description="상태(all | normal | admin | signout)"),
    search_target: str = Query(
        "", description="검색 타겟(nickname | name | contact | email)"
    ),
    search_word: str = Query("", description="검색어"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    회원 목록
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_user_service.user_list(
        status, search_target, search_word, -1, -1, db
    )


@router.get(
    "/users/{user_id}",
    tags=["CMS - 회원"],
    responses={
        200: {
            "description": "회원 상세",
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
                                    "profile": [
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
async def user_detail_by_user_id(
    user_id: int = Path(..., description="회원 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    회원 상세
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_user_service.user_detail_by_user_id(user_id, db)


@router.get(
    "/apply-role",
    tags=["CMS - 자격 신청"],
    responses={
        200: {
            "description": "자격 신청 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "user_id": 1,
                                        "nickname": "닉네임",
                                        "apply_type": "권한 타입",
                                        "company_name": "회사이름",
                                        "email": "account@email.com",
                                        "contact_email": "account@email.com",
                                        "attach_file_path_1st": "파일 경로",
                                        "attach_file_name_1st": "파일명",
                                        "attach_file_path_2nd": "파일 경로",
                                        "attach_file_name_2nd": "파일명",
                                        "approval_code": "승인코드",
                                        "approval_message": "승인 메세지",
                                        "approval_date": "2024-08-02",
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
async def apply_role(
    status: str = Query(
        "all", description="탭(all | waiting | completed | editor | cp)"
    ),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    자격 신청 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_user_service.apply_role(status, page, count_per_page, db)


@router.get(
    "/apply-role/all",
    tags=["CMS - 자격 신청"],
    responses={
        200: {
            "description": "자격 신청 목록 엑셀 다운로드",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "user_id": 1,
                                        "nickname": "닉네임",
                                        "apply_type": "권한 타입",
                                        "company_name": "회사이름",
                                        "email": "account@email.com",
                                        "attach_file_path_1st": "파일 경로",
                                        "attach_file_path_2nd": "파일 경로",
                                        "approval_code": "승인코드",
                                        "approval_message": "승인 메세지",
                                        "approval_date": "2024-08-02",
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
async def apply_role_for_download(
    status: str = Query(
        "all", description="탭(all | waiting | completed | editor | cp)"
    ),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    자격 신청 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_user_service.apply_role(status, -1, -1, db)


@router.get(
    "/badge",
    tags=["CMS - 뱃지"],
    responses={
        200: {
            "description": "뱃지 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "badge_name": "뱃지",
                                        "promotion_conditions": 10,
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
async def badge(
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    뱃지 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_user_service.badge(db)


@router.get(
    "/apply-rank-up",
    tags=["CMS - 승급 신청"],
    responses={
        200: {
            "description": "승급 신청 목록",
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
                                        "price_type": "paid",
                                        "product_type": "normal",
                                        "status_code": "ongoing",
                                        "ratings_code": "all",
                                        "synopsis_text": "1이날이야말로 동소문 안에서 인력거꾼 노릇을 하는 김첨지에게는 오래간만에도 닥친 운수 좋은 날이였다. 문안에(거기도 문밖은 아니지만) 들어간답시는 앞집.",
                                        "user_id": 1,
                                        "author_id": 1,
                                        "author_name": "작가 이름",
                                        "illustrator_id": 1,
                                        "illustrator_name": "그림작가 이름",
                                        "publish_regular_yn": "N",
                                        "publish_days": '{"MON":"Y","TUE":"Y","WED":"Y","THU":"Y","FRI":"Y","SAT":"Y","SUN":"Y"}',
                                        "thumbnail_file_id": 1,
                                        "primary_genre_id": 1,
                                        "sub_genre_id": 2,
                                        "count_hit": 100,
                                        "count_cp_hit": 100,
                                        "count_recommend": 100,
                                        "count_bookmark": 100,
                                        "count_unbookmark": 0,
                                        "open_yn": "N",
                                        "approval_yn": "N",
                                        "monopoly_yn": "N",
                                        "contract_yn": "N",
                                        "paid_open_date": "2024-08-01",
                                        "paid_episode_no": 3,
                                        "last_episode_date": "2024-08-01",
                                        "isbn": "isbn 코드",
                                        "uci": "uci 코드",
                                        "single_regular_price": 10000,
                                        "series_regular_price": 1000,
                                        "sale_price": 10000,
                                        "apply_date": "2024-08-01",
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_date": "2024-08-01T16:00:00",
                                        "status": "review",
                                        "type": "paid",
                                        "count_episode": 10,
                                        "apply_id": 1,
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
async def apply_rank_up(
    status: str = Query("all", description="탭(all | rank-up | paid)"),
    search_target: str = Query(
        "", description="검색 타겟(product-title | writer-name)"
    ),
    search_word: str = Query("", description="검색어"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    승급 신청 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_user_service.apply_rank_up(
        status, search_target, search_word, page, count_per_page, db
    )


@router.get(
    "/apply-rank-up/all",
    tags=["CMS - 승급 신청"],
    responses={
        200: {
            "description": "승급 신청 목록 엑셀 다운로드",
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
                                        "price_type": "paid",
                                        "product_type": "normal",
                                        "status_code": "ongoing",
                                        "ratings_code": "all",
                                        "synopsis_text": "1이날이야말로 동소문 안에서 인력거꾼 노릇을 하는 김첨지에게는 오래간만에도 닥친 운수 좋은 날이였다. 문안에(거기도 문밖은 아니지만) 들어간답시는 앞집.",
                                        "user_id": 1,
                                        "author_id": 1,
                                        "author_name": "작가 이름",
                                        "illustrator_id": 1,
                                        "illustrator_name": "그림작가 이름",
                                        "publish_regular_yn": "N",
                                        "publish_days": '{"MON":"Y","TUE":"Y","WED":"Y","THU":"Y","FRI":"Y","SAT":"Y","SUN":"Y"}',
                                        "thumbnail_file_id": 1,
                                        "primary_genre_id": 1,
                                        "sub_genre_id": 2,
                                        "count_hit": 100,
                                        "count_cp_hit": 100,
                                        "count_recommend": 100,
                                        "count_bookmark": 100,
                                        "count_unbookmark": 0,
                                        "open_yn": "N",
                                        "approval_yn": "N",
                                        "monopoly_yn": "N",
                                        "contract_yn": "N",
                                        "paid_open_date": "2024-08-01",
                                        "paid_episode_no": 3,
                                        "last_episode_date": "2024-08-01",
                                        "isbn": "isbn 코드",
                                        "uci": "uci 코드",
                                        "single_regular_price": 10000,
                                        "series_regular_price": 1000,
                                        "sale_price": 10000,
                                        "apply_date": "2024-08-01",
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_date": "2024-08-01T16:00:00",
                                        "status": "review",
                                        "type": "paid",
                                        "count_episode": 10,
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
async def apply_rank_up_for_download(
    status: str = Query("all", description="탭(all | rank-up | paid)"),
    search_target: str = Query(
        "", description="검색 타겟(product-title | writer-name)"
    ),
    search_word: str = Query("", description="검색어"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    승급 신청 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_user_service.apply_rank_up(
        status, search_target, search_word, -1, -1, db
    )


@router.get(
    "/reviews-comments-notices",
    tags=["CMS - 리뷰/댓글/공지"],
    responses={
        200: {
            "description": "리뷰/댓글/공지 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "type": "notice",
                                        "id": 1,
                                        "product_id": 349,
                                        "user_id": 943,
                                        "use_yn": "Y",
                                        "open_yn": "Y",
                                        "created_date": "2025-08-05T05:55:09",
                                        "user_name": "제로콜라",
                                        "product_title": "카오스 ☆ 카오스",
                                        "contents": "공지 제목",
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
async def reviews_comments_notices(
    type: str = Query("all", description="탭(all | reviews | comments | notices)"),
    search_target: str = Query(
        "", description="검색 타겟(product-title | writer-name)"
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
    리뷰/댓글/공지 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    if type == "reviews":
        return await admin_content_service.reviews_list(
            search_target,
            search_word,
            search_start_date,
            search_end_date,
            page,
            count_per_page,
            db,
        )
    if type == "comments":
        return await admin_content_service.comments_list(
            search_target,
            search_word,
            search_start_date,
            search_end_date,
            page,
            count_per_page,
            db,
        )
    if type == "notices":
        return await admin_content_service.notices_list(
            search_target,
            search_word,
            search_start_date,
            search_end_date,
            page,
            count_per_page,
            db,
        )
    return await admin_content_service.reviews_comments_notices(
        search_target,
        search_word,
        search_start_date,
        search_end_date,
        page,
        count_per_page,
        db,
    )


@router.get(
    "/reviews-comments-notices/all",
    tags=["CMS - 리뷰/댓글/공지"],
    responses={
        200: {
            "description": "리뷰/댓글/공지 목록 엑셀 다운로드",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "type": "review",
                                        "id": 1,
                                        "product_id": 1,
                                        "user_id": 1,
                                        "user_name": "작성자",
                                        "product_title": "대상 작품명",
                                        "use_yn": "Y",
                                        "open_yn": "Y",
                                        "created_date": "2024-08-01T16:00:00",
                                    },
                                    {
                                        "type": "comment",
                                        "id": 1,
                                        "product_id": 1,
                                        "user_id": 1,
                                        "user_name": "작성자",
                                        "product_title": "대상 작품명",
                                        "use_yn": "Y",
                                        "open_yn": "Y",
                                        "created_date": "2024-08-01T16:00:00",
                                    },
                                    {
                                        "type": "notice",
                                        "id": 1,
                                        "product_id": 1,
                                        "user_id": 1,
                                        "user_name": "작성자",
                                        "product_title": "대상 작품명",
                                        "use_yn": "Y",
                                        "open_yn": "Y",
                                        "created_date": "2024-08-01T16:00:00",
                                    },
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
async def reviews_comments_notices_for_download(
    type: str = Query("all", description="탭(all | reviews | comments | notices)"),
    search_target: str = Query(
        "", description="검색 타겟(product-title | writer-name)"
    ),
    search_word: str = Query("", description="검색어"),
    search_start_date: str = Query("", description="기간 검색 시작일"),
    search_end_date: str = Query("", description="기간 검색 종료일"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    리뷰/댓글/공지 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    if type == "reviews":
        return await admin_content_service.reviews_list(
            search_target, search_word, search_start_date, search_end_date, -1, -1, db
        )
    if type == "comments":
        return await admin_content_service.comments_list(
            search_target, search_word, search_start_date, search_end_date, -1, -1, db
        )
    if type == "notices":
        return await admin_content_service.notices_list(
            search_target, search_word, search_start_date, search_end_date, -1, -1, db
        )
    return await admin_content_service.reviews_comments_notices(
        search_target, search_word, search_start_date, search_end_date, -1, -1, db
    )


@router.get(
    "/reviews/{id}",
    tags=["CMS - 리뷰"],
    responses={
        200: {
            "description": "리뷰 상세",
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
                                    "nickname": "작성자 닉네임",
                                    "user_name": "작성자 이름",
                                    "email": "작성자 이메일",
                                    "product_title": "대상 작품명",
                                    "user_id": 1,
                                    "review_text": "리뷰",
                                    "open_yn": "Y",
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
async def review_detail_by_id(
    id: int = Path(..., description="리뷰 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    리뷰 상세
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_content_service.review_detail_by_id(id, db)


@router.get(
    "/comments/{id}",
    tags=["CMS - 댓글"],
    responses={
        200: {
            "description": "댓글 상세",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "comment_id": 1,
                                    "product_id": 1,
                                    "episode_id": 1,
                                    "user_id": 1,
                                    "profile_id": 1,
                                    "nickname": "작성자 닉네임",
                                    "email": "작성자 이메일",
                                    "user_name": "작성자 이름",
                                    "product_title": "대상 작품명",
                                    "author_recommend_yn": "N",
                                    "content": "댓글",
                                    "count_recommend": 0,
                                    "count_not_recommend": 0,
                                    "use_yn": "Y",
                                    "open_yn": "Y",
                                    "display_top_yn": "N",
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
async def comment_detail_by_id(
    id: int = Path(..., description="댓글 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    댓글 상세
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_content_service.comment_detail_by_id(id, db)


@router.get(
    "/notices/{id}",
    tags=["CMS - 공지"],
    responses={
        200: {
            "description": "공지 상세",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "id": 1,
                                    "product_id": 349,
                                    "user_id": 943,
                                    "subject": "공지 제목 u",
                                    "content": "공지 내용 u",
                                    "open_yn": "Y",
                                    "use_yn": "Y",
                                    "created_id": 0,
                                    "created_date": "2024-11-27T07:45:39",
                                    "updated_id": 0,
                                    "updated_date": "2024-12-06T10:19:24",
                                    "title": "카오스 ☆ 카오스",
                                    "price_type": "free",
                                    "status_code": "ongoing",
                                    "ratings_code": "all",
                                    "synopsis_text": "이곳은 K국의 S시.\r\n거대 운석이 낙하하다 허공에서 멈춘 기묘한 도시.\r\n이것은 S시에 사는 사람들의 혼돈과, 혼돈의 이야기다.",
                                    "author_id": 286,
                                    "author_name": "녹차백만잔",
                                    "publish_regular_yn": "N",
                                    "publish_days": '{"MON":"Y"}',
                                    "thumbnail_file_id": 349,
                                    "primary_genre_id": 1,
                                    "count_hit": 3967,
                                    "count_cp_hit": 58,
                                    "count_recommend": 0,
                                    "count_bookmark": 2,
                                    "count_unbookmark": 2,
                                    "approval_yn": "N",
                                    "monopoly_yn": "N",
                                    "contract_yn": "N",
                                    "last_episode_date": "2021-10-18T11:03:21",
                                    "single_regular_price": 0,
                                    "series_regular_price": 0,
                                    "sale_price": 0,
                                    "kc_user_id": "4aeaee9d-d8c8-4063-acdb-d09edaedc985",
                                    "email": "wgb1212@naver.com",
                                    "gender": "F",
                                    "birthdate": "1996-12-12",
                                    "identity_yn": "Y",
                                    "agree_terms_yn": "Y",
                                    "agree_privacy_yn": "Y",
                                    "agree_age_limit_yn": "Y",
                                    "stay_signed_yn": "N",
                                    "latest_signed_date": "2024-12-06T10:19:24",
                                    "latest_signed_type": "likenovel",
                                    "role_type": "normal",
                                    "nickname": "제로콜라",
                                    "product_title": "카오스 ☆ 카오스",
                                    "notice_open_yn": "N",
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
async def notice_detail_by_id(
    id: int = Path(..., description="리뷰 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    공지 상세
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_content_service.notice_detail_by_id(id, db)


@router.get(
    "/keywords/categories",
    tags=["CMS - 테마 키워드"],
    responses={
        200: {
            "description": "테마 키워드 카테고리 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "category_id": 1,
                                        "category_code": "sample_category",
                                        "category_name": "카테고리",
                                        "use_yn": "Y",
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
async def keywords_category_list(
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    테마 키워드 관리 - 테마 키워드 카테고리 목록
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_system_service.keywords_category_list(db)


@router.get(
    "/keywords",
    tags=["CMS - 테마 키워드"],
    responses={
        200: {
            "description": "테마 키워드 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "keyword_id": 1,
                                        "keyword_name": "키워드",
                                        "major_genre_yn": "N",
                                        "filter_yn": "N",
                                        "category_id": 1,
                                        "use_yn": "Y",
                                        "category_code": "genre",
                                        "use_count": 10,
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
async def keywords_list(
    status: str = Query("all", description="탭(all | genre | subject | hero)"),
    search_target: str = Query("tag-name", description="검색 타겟(tag-name)"),
    search_word: str = Query("", description="검색어"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    테마 키워드 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_system_service.keywords_list(
        status, search_target, search_word, page, count_per_page, db
    )


@router.get(
    "/publisher-promotion",
    tags=["CMS - 출판사 프로모션"],
    responses={
        200: {
            "description": "출판사 프로모션 구좌 관리 테이블 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "product_id": 1057,
                                        "show_order": 1234,
                                        "created_id": 0,
                                        "created_date": "2024-12-09T00:40:46",
                                        "updated_id": 0,
                                        "updated_date": "2024-12-09T00:40:46",
                                        "title": "vghfgh",
                                        "price_type": "free",
                                        "status_code": "ongoing",
                                        "ratings_code": "adult",
                                        "synopsis_text": "123123",
                                        "user_id": 942,
                                        "author_id": 943,
                                        "author_name": "제로콜라",
                                        "publish_regular_yn": "N",
                                        "publish_days": '{"MON": "Y", "FRI": "Y"}',
                                        "thumbnail_file_id": 14498,
                                        "primary_genre_id": 1,
                                        "sub_genre_id": 37,
                                        "count_hit": 0,
                                        "count_cp_hit": 0,
                                        "count_recommend": 0,
                                        "count_bookmark": 0,
                                        "count_unbookmark": 0,
                                        "open_yn": "N",
                                        "approval_yn": "N",
                                        "monopoly_yn": "N",
                                        "contract_yn": "N",
                                        "single_regular_price": 0,
                                        "series_regular_price": 0,
                                        "sale_price": 0,
                                        "cp_company_name": "cp",
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
async def publisher_promotion_list(
    search_target: str = Query(
        "", description="검색 타겟(product-title | author-name)"
    ),
    search_word: str = Query("", description="검색어"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    출판사 프로모션 구좌 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_system_service.publisher_promotion_list(
        search_target, search_word, page, count_per_page, db
    )


@router.get(
    "/publisher-promotion/{id}",
    tags=["CMS - 출판사 프로모션"],
    responses={
        200: {
            "description": "직접 추천구좌 상세",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "id": 1,
                                    "name": "추천구좌",
                                    "order": 1,
                                    "product_ids": "[1,2,3]",
                                    "exposure_start_date": "2024-08-01",
                                    "exposure_end_date": "2024-08-15",
                                    "exposure_start_time_weekday": "10:00",
                                    "exposure_end_time_weekday": "15:00",
                                    "exposure_start_time_weekend": "08:00",
                                    "exposure_end_time_weekend": "19:00",
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
async def publisher_promotion_detail_by_id(
    id: int = Path(..., description="출판사 프로모션 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    출판사 프로모션 구좌 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_system_service.publisher_promotion_detail_by_id(id, db)


@router.get(
    "/algorithm-recommend/users",
    tags=["CMS - 알고리즘 추천구좌"],
    responses={
        200: {
            "description": "알고리즘 추천구좌 유저 테이블 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "user_id": 1,
                                        "feature_basic": "male1",
                                        "feature_1": "feature_1",
                                        "feature_2": "feature_2",
                                        "feature_3": "feature_3",
                                        "feature_4": "feature_4",
                                        "feature_5": "feature_5",
                                        "feature_6": "feature_6",
                                        "feature_7": "feature_7",
                                        "feature_8": "feature_8",
                                        "feature_9": "feature_9",
                                        "feature_10": "feature_10",
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_date": "2024-08-01T16:00:00",
                                        "email": "admin@admin.com",
                                        "role_type": "admin",
                                        "gender": "M",
                                        "age": 25,
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
async def algorithm_recommend_user_list(
    search_target: str = Query("email", description="검색 타겟(email)"),
    search_word: str = Query("", description="검색어"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    알고리즘 추천구좌 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_recommend_service.algorithm_recommend_user_list(
        search_target, search_word, page, count_per_page, db
    )


@router.get(
    "/algorithm-recommend/users/format",
    tags=["CMS - 알고리즘 추천구좌"],
    responses={
        200: {
            "description": "알고리즘 추천구좌 유저 테이블 csv 다운로드",
            "content": {"text/csv": {"examples": {}}},
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
async def algorithm_recommend_user_csv_format_download(
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    알고리즘 추천구좌 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_recommend_service.algorithm_recommend_user_csv_format_download(
        db
    )


@router.get(
    "/algorithm-recommend/set-topic",
    tags=["CMS - 알고리즘 추천구좌"],
    responses={
        200: {
            "description": "알고리즘 추천구좌 주제 설정 테이블 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "feature": "feature",
                                        "target": "male1",
                                        "title": "타이틀",
                                        "novel_list": "[1,2,3]",
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
async def algorithm_recommend_set_topic_list(
    search_target: str = Query("product_id", description="검색 타겟(product_id)"),
    search_word: str = Query("", description="검색어"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    알고리즘 추천구좌 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_recommend_service.algorithm_recommend_set_topic_list(
        search_target, search_word, page, count_per_page, db
    )


@router.get(
    "/algorithm-recommend/set-topic/format",
    tags=["CMS - 알고리즘 추천구좌"],
    responses={
        200: {
            "description": "알고리즘 추천구좌 주제 설정 테이블 csv 다운로드",
            "content": {"text/csv": {"examples": {}}},
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
async def algorithm_recommend_set_topic_csv_format_download(
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    알고리즘 추천구좌 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return (
        await admin_recommend_service.algorithm_recommend_set_topic_csv_format_download(
            db
        )
    )


@router.get(
    "/algorithm-recommend/sections",
    tags=["CMS - 알고리즘 추천구좌"],
    responses={
        200: {
            "description": "알고리즘 추천구좌 추천 섹션 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "position": "main",
                                        "feature": "feature",
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
async def algorithm_recommend_section_list(
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    알고리즘 추천구좌 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_recommend_service.algorithm_recommend_section_list(
        page, count_per_page, db
    )


@router.get(
    "/algorithm-recommend/similar/{type}",
    tags=["CMS - 알고리즘 추천구좌"],
    responses={
        200: {
            "description": "알고리즘 추천구좌 추천1 내용비슷, 추천2 장르비슷, 추천3 장바구니 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "type": "content",
                                        "product_id": 1,
                                        "similar_subject_ids": "[1,2,3]",
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
async def algorithm_recommend_similar_list(
    type: str = Path(
        ..., description="타입, 내용비슷: content | 장르비슷: genre | 장바구니: cart"
    ),
    search_target: str = Query("", description="검색 타겟(product-id)"),
    search_word: str = Query("", description="검색어"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    알고리즘 추천구좌 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_recommend_service.algorithm_recommend_similar_list(
        type, search_target, search_word, page, count_per_page, db
    )


@router.get(
    "/algorithm-recommend/similar/{type}/format",
    tags=["CMS - 알고리즘 추천구좌"],
    responses={
        200: {
            "description": "알고리즘 추천구좌 추천1 내용비슷, 추천2 장르비슷, 추천3 장바구니 csv 다운로드",
            "content": {"text/csv": {"examples": {}}},
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
async def algorithm_recommend_similar_csv_format_download(
    type: str = Path(
        ..., description="타입, 내용비슷: content | 장르비슷: genre | 장바구니: cart"
    ),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    알고리즘 추천구좌 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return (
        await admin_recommend_service.algorithm_recommend_similar_csv_format_download(
            type, db
        )
    )


@router.get(
    "/direct-recommend",
    tags=["CMS - 직접 추천구좌"],
    responses={
        200: {
            "description": "직접 추천구좌 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "name": "추천구좌",
                                        "order": 1,
                                        "product_ids": "[1,2,3]",
                                        "exposure_start_date": "2024-08-01",
                                        "exposure_end_date": "2024-08-15",
                                        "exposure_start_time_weekday": "10:00",
                                        "exposure_end_time_weekday": "15:00",
                                        "exposure_start_time_weekend": "08:00",
                                        "exposure_end_time_weekend": "19:00",
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
async def direct_recommend_list(
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    직접 추천구좌 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_recommend_service.direct_recommend_list(page, count_per_page, db)


@router.get(
    "/direct-recommend/{id}",
    tags=["CMS - 직접 추천구좌"],
    responses={
        200: {
            "description": "직접 추천구좌 상세",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "id": 1,
                                    "name": "추천구좌",
                                    "order": 1,
                                    "product_ids": "[1,2,3]",
                                    "exposure_start_date": "2024-08-01",
                                    "exposure_end_date": "2024-08-15",
                                    "exposure_start_time_weekday": "10:00",
                                    "exposure_end_time_weekday": "15:00",
                                    "exposure_start_time_weekend": "08:00",
                                    "exposure_end_time_weekend": "19:00",
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
async def direct_recommend_detail_by_id(
    id: int = Path(..., description="직접 추천구좌 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    직접 추천구좌 상세
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_recommend_service.direct_recommend_detail_by_id(id, db)


@router.get(
    "/direct-promotion",
    tags=["CMS - 직접 프로모션"],
    responses={
        200: {
            "description": "직접 프로모션 목록",
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
                                        "type": "waiting-for-free",
                                        "status": "stop",
                                        "start_date": "2024-08-01",
                                        "end_date": "2024-08-15",
                                        "num_of_ticket_per_person": 1,
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_date": "2024-08-01T16:00:00",
                                        "title": "작품명",
                                        "author_name": "작가명",
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
async def direct_promotion_list(
    status: str = Query(
        "", description="상태, 전체 (all) | 진행중 (ing) | 중지 (stop)"
    ),
    search_target: str = Query(
        "", description="검색 타겟, 작품명 (product-title) | 작가명 (author-name)"
    ),
    search_word: str = Query("", description="검색어"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    직접 프로모션 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_promotion_service.direct_promotion_list(
        status, search_target, search_word, page, count_per_page, db
    )


@router.get(
    "/applied-promotion",
    tags=["CMS - 신청 프로모션"],
    responses={
        200: {
            "description": "신청 프로모션 목록",
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
                                        "type": "waiting-for-free",
                                        "status": "end",
                                        "start_date": "2024-08-01",
                                        "end_date": "2024-08-15",
                                        "num_of_ticket_per_person": 1,
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_date": "2024-08-01T16:00:00",
                                        "title": "작품명",
                                        "author_name": "작가명",
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
async def applied_promotion_list(
    status: str = Query(
        "", description="상태, 전체 (all) | 진행중 (ing) | 신청 (apply) | 철회 (cancel)"
    ),
    search_target: str = Query(
        "", description="검색 타겟, 작품명 (product-title) | 작가명 (author-name)"
    ),
    search_word: str = Query("", description="검색어"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    신청 프로모션 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_promotion_service.applied_promotion_list(
        status, search_target, search_word, page, count_per_page, db
    )


@router.get(
    "/user-giftbook",
    tags=["CMS - 선물함"],
    responses={
        200: {
            "description": "선물함 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "user_id": 1,
                                        "email": "admin@admin.com",
                                        "gift_count": 1,
                                        "recent_gift_date": "2024-08-01T16:00:00",
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
async def user_giftbook_list(
    search_target: str = Query("", description="검색 타겟, 이메일 (email)"),
    search_word: str = Query("", description="검색어"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    선물함
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_promotion_service.user_giftbook_list(
        search_target, search_word, page, count_per_page, db
    )


@router.get(
    "/user-giftbook/{user_id}",
    tags=["CMS - 선물함"],
    responses={
        200: {
            "description": "선물함 엑셀 다운로드",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "received_history": [
                                            {
                                                "reason": "대여권 지급 사유",
                                                "created_date": "2024-08-01T16:00:00",
                                                "expiration_date": "2024-08-08T16:00:00",
                                                "received_date": "2024-08-01T16:00:00",
                                                "target_product_title": "작품 제목",
                                                "target_product_author_name": "작가명",
                                            }
                                        ],
                                        "usage_history": [
                                            {
                                                "title": "사용한 작품 제목",
                                                "author_name": "작가명",
                                                "ticket_type": "comped",
                                                "use_date": "2024-08-01T16:00:00",
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
async def user_giftbook_list_for_download(
    user_id: int = Path(..., description="유저 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    선물함
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_promotion_service.user_giftbook_list_by_user_id(user_id, db)


@router.get(
    "/messages",
    tags=["CMS - 메시지"],
    responses={
        200: {
            "description": "메시지 내역",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "key": "key-conversation-sample",
                                        "sender": 1,
                                        "receiver": 2,
                                        "content": "대화 내용",
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_date": "2024-08-01T16:00:00",
                                        "sender_name": "용감한사자2251",
                                        "receiver_name": "jake2",
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
async def messages_between_users_list(
    search_target: str = Query("", description="검색 타겟(key | sender | receiver)"),
    search_word: str = Query("", description="검색어"),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    메시지 내역
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_notification_service.messages_between_users_list(
        search_target, search_word, page, count_per_page, db
    )


@router.get(
    "/messages/all",
    tags=["CMS - 메시지"],
    responses={
        200: {
            "description": "메시지 내역 엑셀 다운로드",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "key": "key-conversation-sample",
                                        "sender": 1,
                                        "receiver": 2,
                                        "content": "대화 내용",
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_date": "2024-08-01T16:00:00",
                                        "sender_name": "용감한사자2251",
                                        "receiver_name": "jake2",
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
async def messages_between_users_list_for_download(
    search_target: str = Query("", description="검색 타겟(key | sender | receiver)"),
    search_word: str = Query("", description="검색어"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    메시지 내역
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_notification_service.messages_between_users_list(
        search_target, search_word, -1, -1, db
    )


@router.get(
    "/push/templates",
    tags=["CMS - 푸시 메시지"],
    responses={
        200: {
            "description": "푸시 메시지 템플릿 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "use_yn": "Y",
                                        "name": "푸시 템플릿",
                                        "condition": "회원가입",
                                        "landing_page": "/landing_page_sample",
                                        "image_id": 1,
                                        "contents": "푸시 내용",
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
async def push_message_templates_list(
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    푸시 메시지 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_notification_service.push_message_templates_list(db)


@router.get(
    "/push/templates/{id}",
    tags=["CMS - 푸시 메시지"],
    responses={
        200: {
            "description": "푸시 메시지 템플릿 상세",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "id": 1,
                                    "use_yn": "Y",
                                    "name": "푸시 템플릿",
                                    "condition": "회원가입",
                                    "landing_page": "/landing_page_sample",
                                    "image_id": 1,
                                    "contents": "푸시 내용",
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
async def push_message_templates_detail_by_id(
    id: int = Path(..., description="푸시 메시지 템플릿 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    푸시 메시지 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_notification_service.push_message_templates_detail_by_id(id, db)


@router.get(
    "/quests",
    tags=["CMS - 퀘스트"],
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
                                        "questId": 4,
                                        "title": "본인인증하기 / 대여권 1장",
                                        "rewardId": 1,
                                        "useYn": "Y",
                                        "endDate": "2024-12-01T16:00:00",
                                        "createdDate": "2024-08-01T16:00:00",
                                        "updatedDate": "2024-08-01T16:00:00",
                                        "maximumTickets": 3,
                                    },
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
async def quest_all(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    퀘스트 목록
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_quest_service.quest_all(db=db)


@router.get(
    "/quests/{id}",
    tags=["CMS - 퀘스트"],
    responses={
        200: {
            "description": "퀘스트 상세",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "quest_id": 1,
                                    "title": "퀘스트",
                                    "reward_id": 1,
                                    "end_date": "2024-08-10",
                                    "goal_stage": 5,
                                    "use_yn": "Y",
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
async def quest_detail_by_id(
    id: int = Path(..., description="퀘스트 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    퀘스트 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_quest_service.quest_detail_by_id(id, db)


@router.get(
    "/events",
    tags=["CMS - 이벤트"],
    responses={
        200: {
            "description": "이벤트 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "title": "이벤트",
                                        "start_date": "2024-08-01",
                                        "end_date": "2024-08-15",
                                        "type": "etc",
                                        "target_product_ids": "[1,2,3]",
                                        "reward_type": None,
                                        "reward_amount": None,
                                        "reward_max_people": None,
                                        "show_yn_thumbnail_img": "Y",
                                        "show_yn_detail_img": "Y",
                                        "show_yn_product": "Y",
                                        "show_yn_information": "Y",
                                        "thumbnail_image_id": 1,
                                        "detail_image_id": 2,
                                        "account_name": "구좌",
                                        "product_ids": "[1,2,3]",
                                        "information": "샘플입니다",
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_date": "2024-08-01T16:00:00",
                                        "link": "",
                                        "product_title": "새로운 작품 생성",
                                        "status": "ing",
                                        "show": "N",
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
async def events_list(
    type: str = Query(
        "all", description="탭(all | view-3-times | add-comment | add-product | etc)"
    ),
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    이벤트 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.events_list(type, page, count_per_page, db)


@router.get(
    "/events/all",
    tags=["CMS - 이벤트"],
    responses={
        200: {
            "description": "이벤트 목록 엑셀 다운로드",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "title": "이벤트",
                                        "start_date": "2024-08-01",
                                        "end_date": "2024-08-15",
                                        "type": "etc",
                                        "target_product_ids": "[1,2,3]",
                                        "reward_type": None,
                                        "reward_amount": None,
                                        "reward_max_people": None,
                                        "show_yn_thumbnail_img": "Y",
                                        "show_yn_detail_img": "Y",
                                        "show_yn_product": "Y",
                                        "show_yn_information": "Y",
                                        "thumbnail_image_id": 1,
                                        "detail_image_id": 2,
                                        "account_name": "구좌",
                                        "product_ids": "[1,2,3]",
                                        "information": "샘플입니다",
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_date": "2024-08-01T16:00:00",
                                        "link": "",
                                        "product_title": "새로운 작품 생성",
                                        "status": "ing",
                                        "show": "N",
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
async def events_list_for_download(
    type: str = Query(
        "all", description="탭(all | view-3-times | add-comment | add-product | etc)"
    ),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    이벤트 관리
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.events_list(type, -1, -1, db)


@router.get(
    "/events/{id}",
    tags=["CMS - 이벤트"],
    responses={
        200: {
            "description": "이벤트 상세",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "id": 1,
                                    "title": "이벤트",
                                    "start_date": "2024-08-01",
                                    "end_date": "2024-08-15",
                                    "type": "etc",
                                    "target_product_ids": "[1,2,3]",
                                    "reward_type": None,
                                    "reward_amount": None,
                                    "reward_max_people": None,
                                    "show_yn_thumbnail_img": "Y",
                                    "show_yn_detail_img": "Y",
                                    "show_yn_product": "Y",
                                    "show_yn_information": "Y",
                                    "thumbnail_image_id": 1,
                                    "detail_image_id": 2,
                                    "account_name": "구좌",
                                    "product_ids": "[1,2,3]",
                                    "information": "샘플입니다",
                                    "created_date": "2024-08-01T16:00:00",
                                    "updated_date": "2024-08-01T16:00:00",
                                    "link": "",
                                    "product_title": "새로운 작품 생성",
                                    "status": "ing",
                                    "show": "N",
                                    "thumbnail_image_path": "https://cdn.likenovel.net/cover/bA4OeUz41cr72b1mMWJQAaklaa1EEgnqoLn0rWIO.webp",
                                    "detail_image_path": "https://cdn.likenovel.net/cover/bA4OeUz41cr72b1mMWJQAaklaa1EEgnqoLn0rWIO.webp",
                                    "thumbnail_image_filename": "sample_1.webp",
                                    "detail_image_filename": "sample_1.webp",
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
async def event_detail_by_id(
    id: int = Path(..., description="이벤트 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    이벤트 상세
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.event_detail_by_id(id, db)


@router.get(
    "/events/{id}/recipients",
    tags=["CMS - 이벤트"],
    responses={
        200: {
            "description": "이벤트 수령인 목록 csv 다운로드",
            "content": {"text/csv": {"examples": {}}},
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
async def event_download_recipient_by_id(
    id: int = Path(..., description="이벤트 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    이벤트 상세
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.event_download_recipient_by_id(id, db)


@router.get(
    "/banners",
    tags=["CMS - 배너"],
    responses={
        200: {
            "description": "배너 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "position": "main",
                                        "division": "top",
                                        "title": "배너",
                                        "show_start_date": "2024-08-01",
                                        "show_end_date": "2024-08-15",
                                        "show_order": 1,
                                        "url": "https://google.com",
                                        "image_id": 1,
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_date": "2024-08-01T16:00:00",
                                        "show": "N",
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
async def banners_list(
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    배너 및 팝업 관리 - 배너
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.banners_list(page, count_per_page, db)


@router.get(
    "/banners/{id}",
    tags=["CMS - 배너"],
    responses={
        200: {
            "description": "배너 상세",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "id": 1,
                                    "position": "main",
                                    "division": "top",
                                    "title": "배너",
                                    "show_start_date": "2024-08-01",
                                    "show_end_date": "2024-08-15",
                                    "show_order": 1,
                                    "url": "https://google.com",
                                    "image_id": 1,
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
async def banner_detail_by_id(
    id: int = Path(..., description="배너 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    배너 및 팝업 관리 - 배너
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.banner_detail_by_id(id, db)


@router.get(
    "/popup",
    tags=["CMS - 팝업"],
    responses={
        200: {
            "description": "팝업 데이터",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "id": 1,
                                    "title": "팝업",
                                    "content": "샘플입니다",
                                    "image_id": 1,
                                    "start_date": "2024-08-01",
                                    "end_date": "2024-08-15",
                                    "use_yn": "Y",
                                    "created_date": "2024-08-01T16:00:00",
                                    "updated_date": "2024-08-01T16:00:00",
                                    "image_path": "",
                                    "file_name": "",
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
async def get_current_popup_data(
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    배너 및 팝업 관리 - 팝업
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.get_current_popup_data(db)


@router.get(
    "/faq",
    tags=["CMS - FAQ"],
    responses={
        200: {
            "description": "FAQ 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "faq_type": "회원문의",
                                        "subject": "FAQ",
                                        "content": "샘플입니다",
                                        "primary_yn": "N",
                                        "use_yn": "Y",
                                        "view_count": 0,
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
async def faq_list(
    page: int = Query(1, description="페이지"),
    count_per_page: int = Query(8, description="한 페이지 내 갯수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    공지 / FAQ - FAQ
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_faq_service.faq_list(page, count_per_page, db)


@router.get(
    "/faq/{id}",
    tags=["CMS - FAQ"],
    responses={
        200: {
            "description": "FAQ 상세",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "id": 1,
                                    "faq_type": "회원문의",
                                    "subject": "FAQ",
                                    "content": "샘플입니다",
                                    "primary_yn": "N",
                                    "use_yn": "Y",
                                    "view_count": 0,
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
async def faq_detail_by_id(
    id: int = Path(..., description="FAQ 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    공지 / FAQ - FAQ
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_faq_service.faq_detail_by_id(id, db)


@router.get(
    "/common-rate",
    tags=["CMS - 비율 조정"],
    responses={
        200: {
            "description": "비율 조정 데이터 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {
                                "data": {
                                    "default_settlement_rate": 0,
                                    "donation_settlement_rate": 0,
                                    "payment_fee_rate": 0,
                                    "tax_amount_rate": 0,
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
async def get_common_rate_data(
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    비율 조정 데이터 조회
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_basic_service.get_common_rate_data(db)


@router.get(
    "/products/simple",
    tags=["CMS - 작품"],
    responses={
        200: {
            "description": "작품 리스트 조회 (작품 ID, 제목만 포함)",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "",
                            "value": {"data": [{"product_id": 1, "title": "제목"}]},
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
async def get_product_simple_list(
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    작품 리스트 조회 (작품 ID, 제목만 포함)
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_basic_service.get_product_simple_list(db)


@router.get(
    "/general-notices",
    tags=["CMS - 공지사항(사이트 공지)"],
    responses={
        200: {
            "description": "공지사항(notice) 목록 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "공지사항(notice) 목록 조회",
                            "value": {
                                "data": [
                                    {
                                        "noticeId": 7,
                                        "type": "NRML",
                                        "subject": "7-CP회원 2024년 08월 정산 안내(플랫폼별 안내)",
                                        "primaryYn": "Y",
                                        "createdDate": "2024-08-01T16:00:00",
                                        "updatedDate": "2024-08-01T16:00:00",
                                    },
                                    {
                                        "noticeId": 4,
                                        "type": "NRML",
                                        "subject": "4-CP회원 2024년 08월 정산 안내(플랫폼별 안내)",
                                        "primaryYn": "N",
                                        "createdDate": "2024-08-01T12:00:00",
                                        "updatedDate": "2024-08-01T12:00:00",
                                    },
                                    {
                                        "noticeId": 3,
                                        "type": "NRML",
                                        "subject": "3-CP회원 2024년 08월 정산 안내(플랫폼별 안내)",
                                        "primaryYn": "Y",
                                        "createdDate": "2024-08-01T11:00:00",
                                        "updatedDate": "2024-08-01T11:00:00",
                                    },
                                    {
                                        "noticeId": 1,
                                        "type": "NRML",
                                        "subject": "1-CP회원 2024년 08월 정산 안내(플랫폼별 안내)",
                                        "primaryYn": "Y",
                                        "createdDate": "2024-08-01T10:00:00",
                                        "updatedDate": "2024-08-01T10:00:00",
                                    },
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
async def notices_all(
    page: int = Query(1, description="조회 시작 위치"),
    limit: int = Query(10, description="한페이지 조회 개수"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    공지사항(notice) 목록 조회
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e
    return await admin_system_service.notices_all(page, limit, db=db)


@router.get(
    "/general-notices/{notice_id}",
    tags=["CMS - 공지사항(사이트 공지)"],
    responses={
        200: {
            "description": "공지사항(notice) 상세 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "공지사항(notice) 상세 조회",
                            "value": {
                                "data": [
                                    {
                                        "noticeId": 7,
                                        "type": "NRML",
                                        "subject": "7-CP회원 2024년 08월 정산 안내(플랫폼별 안내)",
                                        "content": "7-2024년 08월 정산 안내_CP 회원<br/>안녕하세요, 라이크노벨 입니다.<br/>라이크노벨을 믿고 좋은 작품을 제공해 주셔서 진심으로 감사드리며, 2024년 08월 정산 및 (세금)계산서 발행 관련하여 안내 드립니다.",
                                        "primaryYn": "Y",
                                        "createdDate": "2024-08-01T16:00:00",
                                        "updatedDate": "2024-08-01T16:00:00",
                                    },
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
async def notice_detail_by_notice_id(
    notice_id: int = Path(..., description="공지사항 아이디"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    공지사항(notice) 상세 조회
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e
    return await admin_system_service.notice_detail_by_notice_id(notice_id, db=db)
