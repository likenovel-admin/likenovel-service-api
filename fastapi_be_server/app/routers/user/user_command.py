from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.user as user_schema
import app.services.user.user_service as user_service
import app.services.user.user_notification_service as user_notification_service
import app.services.gift.author_service as author_service

from app.const import settings

router = APIRouter(prefix="/user")


@router.post(
    "/apply-role",
    tags=["유저 - CP/편집자 신청"],
    responses={
        200: {
            "description": "CP/편집자 신청",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "신청 여부 값 전달",
                            "value": {"data": {"applyRoleYn": "Y"}},
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
        409: {
            "description": "이미 신청이 접수된 상태이고 검토 중일 경우",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "이미 신청이 접수된 상태이고 검토 중입니다.",
                            "value": {"code": "M0001"},
                        }
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
                            "summary": "cp/편집자 신청 값 validation 에러(유효하지 않은 정보 값)",
                            "value": {"code": "E4228"},
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
async def post_user_apply_role(
    req_body: user_schema.PostUserApplyRoleReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 신청 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    CP/편집자 신청 버튼
    (마이페이지 CP사 입점 편집자 자격 신청)
    """

    return await user_service.post_user_apply_role(
        req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/profiles",
    tags=["유저 - 프로필"],
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
                            "summary": "프로필 추가/수정 신청 값 validation 에러(유효하지 않은 정보 값)",
                            "value": {"code": "E4229"},
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
async def post_user_profiles(
    req_body: user_schema.PostUserProfilesReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 프로필 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    프로필 추가 버튼
    (마이페이지 프로필등록)
    """

    return await user_service.post_user_profiles(
        req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/profiles/{profile_id}",
    tags=["유저 - 프로필"],
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
        403: {
            "description": "닉네임 변경 가능 횟수가 0인 상태",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "닉네임 변경 가능 횟수가 0입니다. 충전이 필요합니다.",
                            "value": {"code": "M0002"},
                        }
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
                            "summary": "프로필 추가/수정 신청 값 validation 에러(유효하지 않은 정보 값)",
                            "value": {"code": "E4229"},
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
async def put_user_profiles_profile_id(
    req_body: user_schema.PutUserProfilesProfileIdReqBody,
    profile_id: str = Path(..., description="프로필 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 프로필 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    프로필 수정 버튼
    (마이페이지 프로필수정)
    """

    return await user_service.put_user_profiles_profile_id(
        req_body=req_body, profile_id=profile_id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/profiles/{profile_id}/purchase-nickname-change",
    tags=["유저 - 프로필"],
    response_model=user_schema.PurchaseNicknameChangeResponse,
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "닉네임 변경권 구매 성공",
                            "value": {
                                "success": True,
                                "remainingCash": 1500,
                                "nicknameChangeCount": 0,
                                "paidChangeCount": 1,
                            },
                        }
                    }
                }
            },
        },
        400: {
            "description": "캐시 잔액 부족",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "캐시 잔액이 부족합니다.",
                            "value": {"code": "B4001"},
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
        403: {
            "description": "무료 변경 횟수가 남아있음",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "무료 닉네임 변경 횟수가 남아있습니다.",
                            "value": {"code": "M0003"},
                        }
                    }
                }
            },
        },
        404: {
            "description": "프로필을 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "프로필을 찾을 수 없습니다.",
                            "value": {"code": "N4042"},
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
async def post_user_profiles_purchase_nickname_change(
    profile_id: str = Path(..., description="프로필 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    닉네임 변경권 구매 API

    - 500 캐시로 닉네임 변경권 1개 구매
    - 무료 변경 횟수가 남아있으면 구매 불가
    - 구매 시 paid_change_count가 1 증가
    """

    return await user_service.purchase_nickname_change_ticket(
        profile_id=int(profile_id), kc_user_id=user.get("sub"), db=db
    )


@router.delete(
    "/profiles/{profile_id}",
    tags=["유저 - 프로필"],
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
async def delete_user_profiles_profile_id(
    profile_id: str = Path(..., description="프로필 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 프로필 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    프로필 삭제 버튼
    (마이페이지 프로필관리)
    """

    return await user_service.delete_user_profiles_profile_id(
        profile_id=profile_id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/nickname/duplicate-check",
    tags=["유저 - 프로필"],
    dependencies=[Depends(analysis_logger)],
)
async def post_user_nickname_duplicate_check(
    req_body: user_schema.PostUserNicknameDuplicateCheckReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 프로필 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    닉네임 중복 확인 버튼
    """

    return await user_service.post_user_nickname_duplicate_check(
        req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/alarms/mark-as-read",
    tags=["유저 - 알림"],
    dependencies=[Depends(analysis_logger)],
)
async def put_user_alarms_alarm_id(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 알림 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    알림 읽음
    """

    return await user_notification_service.put_user_alarms_alarm_id(
        kc_user_id=user.get("sub"), db=db
    )


@router.get("/identity/nice/callback", tags=["유저 - 본인인증"])
async def nice_callback(
    request: Request,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **본인인증 콜백 처리**\n
    나이스 본인인증 후 리다이렉트되는 엔드포인트\n
    프론트엔드에서 암호화 키들을 query parameter로 전달받아 처리
    """

    # 본인인증 결과 DB 업데이트
    """
    GET /nice/callback?enc_data=...&token_version_id=...&integrity_value=...&encryption_key=...&encryption_iv=...&hmac_key=...&req_no=...
    """
    await user_service.get_user_authed_data(
        enc_data=request.query_params.get("enc_data"),
        token_version_id=request.query_params.get("token_version_id"),
        integrity_value=request.query_params.get("integrity_value"),
        encryption_key=request.query_params.get("encryption_key"),
        encryption_iv=request.query_params.get("encryption_iv"),
        hmac_key=request.query_params.get("hmac_key"),
        req_no=request.query_params.get("req_no"),
        kc_user_id=user.get("sub"),
        db=db,
    )

    # 리다이렉트 URL로 이동
    return RedirectResponse(
        url=settings.FE_WWW_DOMAIN + "?identityYn=Y", status_code=302
    )


@router.post("/products/contract-offers/{offer_id}/accept", tags=["유저"])
async def accept_contract_offers(
    offer_id: int = Path(..., description="제안 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 계약 제안 수락
    """

    return await author_service.accept_contract_offers(
        offer_id=offer_id, kc_user_id=user.get("sub"), db=db
    )


@router.post("/products/contract-offers/{offer_id}/reject", tags=["유저"])
async def reject_contract_offers(
    offer_id: int = Path(..., description="제안 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 계약 제안 거절
    """

    return await author_service.reject_contract_offers(
        offer_id=offer_id, kc_user_id=user.get("sub"), db=db
    )


@router.post("/direct-promotion/{promotion_id}/stop", tags=["유저"])
async def stop_direct_promotion(
    promotion_id: int = Path(..., description="프로모션 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    직접 프로모션 중지
    """

    return await author_service.stop_direct_promotion(
        promotion_id=promotion_id, kc_user_id=user.get("sub"), db=db
    )


@router.post("/direct-promotion/{promotion_id}/start", tags=["유저"])
async def start_direct_promotion(
    promotion_id: int = Path(..., description="프로모션 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    직접 프로모션 시작
    """

    return await author_service.start_direct_promotion(
        promotion_id=promotion_id, kc_user_id=user.get("sub"), db=db
    )


@router.post("/direct-promotion/{promotion_id}/end", tags=["유저"])
async def end_direct_promotion(
    promotion_id: int = Path(..., description="프로모션 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    직접 프로모션 종료
    """

    return await author_service.end_direct_promotion(
        promotion_id=promotion_id, kc_user_id=user.get("sub"), db=db
    )


@router.post("/direct-promotion/{promotion_id}/issue", tags=["유저"])
async def issue_reader_of_prev_promotion(
    promotion_id: int = Path(..., description="프로모션 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    선작 독자 무료 대여권 발급 (일주일에 한번만 가능)
    """

    return await author_service.issue_reader_of_prev_promotion(
        promotion_id=promotion_id, kc_user_id=user.get("sub"), db=db
    )


@router.get("/direct-promotion/{promotion_id}/issuance-status", tags=["유저"])
async def check_reader_of_prev_issuance_status(
    promotion_id: int = Path(..., description="프로모션 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    선작 독자 무료 대여권 발급 상태 확인
    - 이번 주에 발급했는지 여부
    - 마지막 발급 날짜
    - 다음 발급 가능 날짜 (다음 주 월요일)
    """

    return await author_service.check_reader_of_prev_issuance_status(
        promotion_id=promotion_id, kc_user_id=user.get("sub"), db=db
    )


@router.post("/products/{product_id}/direct-promotion/save", tags=["유저"])
async def save_direct_promotion(
    req_body: user_schema.PostDirectPromotionTicketCountReqBody,
    product_id: int = Path(..., description="작품 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    직접 프로모션 명당 증정 대여권 수 저장
    """

    return await author_service.save_direct_promotion(
        req_body=req_body, product_id=product_id, kc_user_id=user.get("sub"), db=db
    )


@router.post("/products/{product_id}/applied-promotion/apply", tags=["유저"])
async def apply_applied_promotion(
    req_body: user_schema.PostAppliedPromotionReqBody,
    product_id: int = Path(..., description="작품 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    신철 프로모션 신청
    """

    return await author_service.apply_applied_promotion(
        req_body=req_body, product_id=product_id, kc_user_id=user.get("sub"), db=db
    )


@router.post("/applied-promotion/{promotion_id}/cancel", tags=["유저"])
async def cancel_applied_promotion(
    promotion_id: int = Path(..., description="프로모션 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    신청 프로모션 철회
    """

    return await author_service.cancel_applied_promotion(
        promotion_id=promotion_id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/products/{product_id}/send-notification-to-bookmarked-users", tags=["유저"]
)
async def send_notification_to_bookmarked_users(
    req_body: user_schema.PostNotificationToBookmarkedReqBody,
    product_id: int = Path(..., description="작품 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    북마크한 유저에게 알림 전송
    """

    return await user_notification_service.send_notification_to_bookmarked_users(
        product_id=product_id,
        content=req_body.content,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.put(
    "/notification-settings",
    tags=["유저"],
    dependencies=[Depends(analysis_logger)],
)
async def update_notification_settings(
    req_body: user_schema.PutNotificationSettingsReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    알림 설정 변경
    """

    return await user_notification_service.update_notification_settings(
        req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.post("/recent-products", tags=["유저"], dependencies=[Depends(analysis_logger)])
async def save_user_recent_product(
    req_body: user_schema.PostUserRecentProductReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    최근 본 작품 수동 저장

    Args:
        product_id: 저장할 작품 ID

    Returns:
        저장 결과
    """
    return await user_service.save_user_recent_product(
        product_id=req_body.product_id, kc_user_id=user.get("sub"), db=db
    )


@router.delete(
    "/recent-products/{product_id}",
    tags=["유저"],
    dependencies=[Depends(analysis_logger)],
)
async def delete_user_recent_product(
    product_id: int,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    최근 본 작품 개별 삭제

    Args:
        product_id: 삭제할 작품 ID

    Returns:
        삭제 결과
    """
    return await user_service.delete_user_recent_product(
        product_id=product_id, kc_user_id=user.get("sub"), db=db
    )


@router.delete(
    "/recent-products", tags=["유저"], dependencies=[Depends(analysis_logger)]
)
async def delete_all_user_recent_products(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    최근 본 작품 전체 삭제

    Returns:
        삭제 결과
    """
    return await user_service.delete_all_user_recent_products(
        kc_user_id=user.get("sub"), db=db
    )
