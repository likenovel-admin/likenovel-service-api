from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.user.user_service as user_service
import app.services.user.user_notification_service as user_notification_service
import app.services.gift.author_service as author_service

router = APIRouter(prefix="/user")


@router.get(
    "",
    tags=["유저"],
    responses={
        200: {
            "description": "로그인 후 유저 정보 조회(프론트 단 별도 처리용)",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 유저 정보",
                            "value": {
                                "data": {
                                    "userId": 1,
                                    "birthDate": "2000-01-31",
                                    "gender": "M",
                                    "recentSignInType": "naver",
                                    "adultToggleDisplayYn": "N",
                                    "userRole": "user",
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
async def get_user(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 내 정보 수정, 캐시 모듈 구현 후 수정 및 최종 테스트 필(현재 초안 개발 완료. 추가된 정보(본인인증여부, 이메일, 연동내용, 보유캐시) 활용하여 구현 필)**\n
    로그인 후 유저 정보 조회(프론트 단 별도 처리용)
    """

    return await user_service.get_user(kc_user_id=user.get("sub"), db=db)


@router.get(
    "/info",
    tags=["유저"],
    responses={
        200: {
            "description": "현재 유저 정보 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 유저 정보",
                            "value": {
                                "data": {
                                    "profileId": 1,
                                    "birthDate": "2000-01-31",
                                    "userProfileImagePath": "https://cdn.likenovel.dev/user/26SH8jv6R_ud9lAevfya5Q.webp",
                                    "userNickname": "로스티플",
                                    "userInterestLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/level/interest/1.webp",
                                    "userEventLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/level/event/1.webp",
                                    "userRole": "user",
                                    "identityYn": "N",
                                    "email": "abcd@gamil.com",
                                    "totalCash": 100,
                                    "totalTicket": 10,
                                    "totalInterestSustainCount": 250,
                                    "totalVoteWinCount": 250,
                                    "totalVoteRound": 300,
                                    "totalReadProductCount": 300,
                                    "totalWrittenProductCount": 20,
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
async def get_user_info(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    현재 유저 정보 조회
    (마이페이지 홈, 모바일 햄버거 버튼)
    """

    return await user_service.get_user_info(kc_user_id=user.get("sub"), db=db)


@router.get(
    "/attachment/upload/{file_name}",
    tags=["유저"],
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
                                    "attachmentFileId": 1,
                                    "attachmentUploadPath": "https://a168bba93203dec90f4f7ddda837c772.r2.cloudflarestorage.com/attachment/NIVOD2R3QhShEfuI37qmxA.webp?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=073f266abc091744da51a72250a10c32%2F20241108%2Fapac%2Fs3%2Faws4_request&X-Amz-Date=20241108T110511Z&X-Amz-Expires=10800&X-Amz-SignedHeaders=host&X-Amz-Signature=63b1e666f8a9eb8874053dd214e1c35f8a01dd89ca603447220cda2b3ad4df57",
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
async def get_user_attachment_upload_file_name(
    file_name: str = Path(..., description="원본 파일명(확장자 포함)"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 신청 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    CP/편집자 신청 내 파일 업로드 버튼
    (마이페이지 CP사 입점 편집자 자격 신청)
    """

    return await user_service.get_user_attachment_upload_file_name(
        file_name=file_name, kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/profiles/upload/{file_name}",
    tags=["유저 - 프로필"],
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
                                    "profileImageFileId": 1,
                                    "profileImageUploadPath": "https://a168bba93203dec90f4f7ddda837c772.r2.cloudflarestorage.com/image/profile/NIVOD2R3QhShEfuI37qmxA.webp?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=073f266abc091744da51a72250a10c32%2F20241108%2Fapac%2Fs3%2Faws4_request&X-Amz-Date=20241108T110511Z&X-Amz-Expires=10800&X-Amz-SignedHeaders=host&X-Amz-Signature=63b1e666f8a9eb8874053dd214e1c35f8a01dd89ca603447220cda2b3ad4df57",
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
async def get_user_profiles_upload_file_name(
    file_name: str = Path(..., description="원본 파일명(.webp)"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 프로필 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    프로필 이미지 업로드 버튼
    (마이페이지)
    """

    return await user_service.get_user_profiles_upload_file_name(
        file_name=file_name, kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/profiles",
    tags=["유저 - 프로필"],
    responses={
        200: {
            "description": "프로필 관리 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "프로필 관리",
                            "value": {
                                "data": [
                                    {
                                        "profileId": 1,
                                        "userProfileImagePath": "https://cdn.likenovel.dev/user/26SH8jv6R_ud9lAevfya5Q.webp",
                                        "userNickname": "로스티플",
                                        "userInterestLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/level/interest/1.webp",
                                        "userEventLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/level/event/1.webp",
                                        "userRole": "user",
                                        "defaultYn": "N",
                                        "nicknameChangeableCount": 2,
                                    },
                                    {
                                        "profileId": 2,
                                        "userProfileImagePath": "https://cdn.likenovel.dev/user/26SH8jv6R_ud9lAevfya5Q.webp",
                                        "userNickname": "로스티플",
                                        "userInterestLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/level/interest/1.webp",
                                        "userEventLevelBadgeImagePath": "https://cdn.likenovel.dev/badge/level/event/1.webp",
                                        "userRole": "author",
                                        "defaultYn": "Y",
                                        "nicknameChangeableCount": 1,
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
async def get_user_profiles(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 프로필 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    프로필 관리 조회
    """

    return await user_service.get_user_profiles(kc_user_id=user.get("sub"), db=db)


@router.get(
    "/profiles/{profile_id}/info",
    tags=["유저 - 프로필"],
    responses={
        200: {
            "description": "저장된 프로필 정보 내용 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "저장된 프로필 정보",
                            "value": {
                                "data": {
                                    "profileId": 1,
                                    "userProfileImagePath": "https://cdn.likenovel.dev/user/26SH8jv6R_ud9lAevfya5Q.webp",
                                    "userNickname": "로스티플",
                                    "userRole": "user",
                                    "defaultYn": "N",
                                    "nicknameChangeableCount": 2,
                                    "selectedUserInterestBadgeId": 1,
                                    "userInterestLevelBadgeImagePaths": {
                                        1: "https://cdn.likenovel.dev/badge/level/interest/1.webp",
                                        3: "https://cdn.likenovel.dev/badge/level/interest/1.webp",
                                    },
                                    "selectedUserEventBadgeId": None,
                                    "userEventLevelBadgeImagePaths": {
                                        10: "https://cdn.likenovel.dev/badge/level/event/1.webp"
                                    },
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
async def get_user_profiles_profile_id_info(
    profile_id: str = Path(..., description="프로필 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 프로필 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    저장된 프로필 정보 내용 조회
    """

    return await user_service.get_user_profiles_profile_id_info(
        profile_id=profile_id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{user_id}/indentity-token",
    tags=["유저 - 본인인증"],
    responses={
        200: {
            "description": "본인인증 토큰 발급",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {"summary": "본인인증 토큰 발급", "value": {}}
                    }
                }
            },
        }
    },
)
async def post_userid_identity_token(
    user_id: str = Path(..., description="유저 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    본인인증 토큰 발급
    """

    return await user_service.post_userid_identity_token(
        user_id=user_id, kc_user_id=user.get("sub"), db=db
    )


@router.get("/cash", tags=["유저 - 캐시"], dependencies=[Depends(analysis_logger)])
async def get_user_cash(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 캐시 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    캐시 사용내역 조회
    """

    return await user_service.get_user_cash(kc_user_id=user.get("sub"), db=db)


@router.get(
    "/cash/balance",
    tags=["유저 - 캐시"],
    responses={
        200: {
            "description": "캐시 잔액 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "캐시 잔액",
                            "value": {"data": {"balance": 10000}},
                        }
                    }
                }
            },
        },
        401: {
            "description": "인증 실패",
            "content": {
                "application/json": {
                    "examples": {
                        "login_required": {
                            "summary": "로그인 필요",
                            "value": {"message": "로그인이 필요합니다."},
                        }
                    }
                }
            },
        },
    },
    dependencies=[Depends(analysis_logger)],
)
async def get_user_cash_balance(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    캐시 잔액 조회
    """

    return await user_service.get_user_cash_balance(kc_user_id=user.get("sub"), db=db)


@router.get("/comments", tags=["유저 - 댓글"], dependencies=[Depends(analysis_logger)])
async def get_user_comments(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 댓글 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    내 댓글 조회
    """

    return await user_service.get_user_comments(kc_user_id=user.get("sub"), db=db)


@router.get(
    "/comments/block", tags=["유저 - 댓글"], dependencies=[Depends(analysis_logger)]
)
async def get_user_comments_block(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 댓글 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    차단관리 조회
    """

    return await user_service.get_user_comments_block(kc_user_id=user.get("sub"), db=db)


@router.get("/alarms", tags=["유저 - 알림"], dependencies=[Depends(analysis_logger)])
async def get_user_alarms(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 알림 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    알림 목록 조회
    """

    return await user_notification_service.get_user_alarms(
        kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/summary",
    tags=["유저"],
    responses={
        200: {
            "description": "현재 유저 정보 요약 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 유저 정보",
                            "value": {
                                "data": {
                                    "profileId": 1,
                                    "profileImagePath": "https://cdn.likenovel.dev/user/26SH8jv6R_ud9lAevfya5Q.webp",
                                    "nickname": "로스티플",
                                    "badgeImagePath": "https://cdn.likenovel.dev/badge/level/interest/1.webp",
                                    "email": "abcd@gamil.com",
                                    "totalViewCount": 100,
                                    "totalViewCountIndicator": 1,
                                    "totalBookmarkCount": 100,
                                    "totalBookmarkCountIndicator": 1,
                                    "totalRecommendCount": 100,
                                    "totalRecommendCountIndicator": 1,
                                    "totalCPViewCount": 100,
                                    "totalCPViewCountIndicator": 1,
                                    "interestTotalCount": 100,
                                    "interestTotalCountIndicator": 1,
                                    "interestSustainCount": 100,
                                    "interestSustainCountIndicator": 1,
                                    "interestLossCount": 100,
                                    "interestLossCountIndicator": 1,
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
async def get_user_summary_info(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    현재 유저 요약 정보 조회
    """

    return await user_service.get_user_summary_info(kc_user_id=user.get("sub"), db=db)


@router.get(
    "/evaluation",
    tags=["유저"],
    responses={
        200: {
            "description": "현재 유저 평가 정보 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 유저 평가 정보",
                            "value": {"data": {"highlypositive": 2}},
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
async def get_user_evaluation_info(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    현재 유저 평가 정보 조회
    """

    return await user_service.get_user_evaluation_info(
        kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/products",
    tags=["유저"],
    responses={
        200: {
            "description": "현재 유저의 작품 목록 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 유저의 작품 목록",
                            "value": {
                                "data": {
                                    "products": [
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
async def get_products(
    sort_by: Optional[str] = Query(
        "recent_update",
        description="정렬 기준: recent_update(최근 업데이트 순), title(가나다 순)",
    ),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작가의 작품 목록
    """

    return await author_service.get_products(
        kc_user_id=user.get("sub"), sort_by=sort_by, db=db
    )


@router.get(
    "/products-with-promotions",
    tags=["유저"],
    responses={
        200: {
            "description": "현재 유저의 작품별 프로모션 목록 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 유저의 작품별 프로모션 목록",
                            "value": {
                                "data": {
                                    "products": [
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
                                            "directPromotions": [
                                                {
                                                    "id": 1,
                                                    "product_id": 1057,
                                                    "start_date": "2025-09-19 06:55:04",
                                                    "type": "free-for-first",
                                                    "status": "ing",
                                                    "num_of_ticket_per_person": 1,
                                                    "created_id": -1,
                                                    "created_date": "2025-09-19 06:55:04",
                                                    "updated_id": -1,
                                                    "updated_date": "2025-09-22 04:14:04",
                                                }
                                            ],
                                            "appliedPromotions": [
                                                {
                                                    "id": 1,
                                                    "product_id": 1057,
                                                    "type": "waiting-for-free",
                                                    "status": "ing",
                                                    "start_date": "2025-09-19 06:55:04",
                                                    "end_date": "2025-12-19 06:55:04",
                                                    "num_of_ticket_per_person": 1,
                                                    "created_id": -1,
                                                    "created_date": "2025-09-19 06:55:04",
                                                    "updated_id": -1,
                                                    "updated_date": "2025-09-22 04:14:04",
                                                }
                                            ],
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
async def get_products_promotions(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작가의 작품별 프로모션 목록
    """

    return await author_service.get_products_promotions(
        kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/products/contract-offers",
    tags=["유저"],
    responses={
        200: {
            "description": "현재 유저의 작품 계약 제안 목록 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 유저의 작품 계약 제안 목록",
                            "value": {
                                "data": [
                                    {
                                        "offer_id": 1,
                                        "product_id": 1057,
                                        "profit_type": "percent",
                                        "author_profit": 90,
                                        "offer_profit": 10,
                                        "use_yn": "Y",
                                        "author_user_id": 943,
                                        "author_accept_yn": "Y",
                                        "offer_user_id": 1063,
                                        "offer_type": "input",
                                        "offer_code": "",
                                        "offer_price": 0.7,
                                        "offer_date": "2025-09-19 06:55:04",
                                        "created_id": -1,
                                        "created_date": "2025-08-26 01:53:59",
                                        "updated_id": -1,
                                        "updated_date": "2025-09-22 04:14:04",
                                    }
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
async def get_contract_offers(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작가의 작품 계약 제안 목록
    """

    return await author_service.get_contract_offers(kc_user_id=user.get("sub"), db=db)


@router.get(
    "/products/contract-offered",
    tags=["유저"],
    responses={
        200: {
            "description": "현재 유저가 보낸 작품 계약 제안 목록 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 유저가 보낸 작품 계약 제안 목록",
                            "value": {
                                "data": [
                                    {
                                        "offer_id": 1,
                                        "product_id": 1057,
                                        "cover_image_path": "https://cdn.likenovel.dev/cover/1/image.webp",
                                        "title": "세계전복급 악역으로 오해받고 있습니다",
                                        "author_name": "마로니스",
                                        "illustrator_name": "SENDY",
                                        "created_date": "2024-03-05",
                                        "waiting_for_free_yn": "Y",
                                        "six_nine_path_yn": "N",
                                        "offer_price": 0.7,
                                        "offer_profit": 10,
                                        "author_profit": 90,
                                        "author_accept_yn": "Y",
                                        "use_yn": "Y",
                                        "author_user_id": 943,
                                        "primary_genre": "무협",
                                        "sub_genre": "판타지",
                                        "keywords": ["키워드1", "키워드2", "키워드3"],
                                    }
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
async def get_contract_offered(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    보낸 작품 계약 제안 목록
    """

    return await author_service.get_contract_offered(kc_user_id=user.get("sub"), db=db)


@router.get(
    "/notification-settings",
    tags=["유저"],
    responses={
        200: {
            "description": "현재 유저의 알림 설정 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 유저의 알림 설정 조회",
                            "value": {
                                "data": {
                                    "benefit": "Y",
                                    "comment": "Y",
                                    "system": "Y",
                                    "event": "Y",
                                    "marketing": "Y",
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
async def get_notification_settings(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    현재 유저의 알림 설정 조회
    """

    return await user_notification_service.get_notification_settings(
        kc_user_id=user.get("sub"), db=db
    )


@router.get("/recent-products", tags=["유저"], dependencies=[Depends(analysis_logger)])
async def get_user_recent_products(
    limit: Optional[int] = None,
    adult_yn: str = Query("N", description="성인 작품 포함 여부 (Y | N)"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    최근 본 작품 목록 조회

    Args:
        limit: 조회할 작품 수 (None이면 전체 조회)
        adult_yn: 성인 작품 포함 여부 (Y | N)

    Returns:
        최근 본 작품 목록 (최신순)
    """
    return await user_service.get_user_recent_products(
        kc_user_id=user.get("sub"), limit=limit, adult_yn=adult_yn, db=db
    )
