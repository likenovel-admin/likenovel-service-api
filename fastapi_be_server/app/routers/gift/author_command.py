from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.author as author_schema
import app.services.gift.sponsor_service as sponsor_service

router = APIRouter(prefix="/authors")


@router.post(
    "/{author_id}/sponsor",
    tags=["작가 - 후원"],
    responses={
        200: {
            "description": "후원 완료",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "후원 성공",
                            "value": {
                                "result": True,
                                "data": {
                                    "donationPrice": 1000,
                                    "remainingBalance": 9000,
                                },
                            },
                        }
                    }
                }
            },
        },
        400: {
            "description": "잘못된 요청",
            "content": {
                "application/json": {
                    "examples": {
                        "insufficient_balance": {
                            "summary": "캐시 잔액 부족",
                            "value": {"message": "캐시 잔액이 부족합니다."},
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
        404: {
            "description": "리소스를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "not_found_author": {
                            "summary": "작가를 찾을 수 없음",
                            "value": {"message": "존재하지 않는 작가입니다."},
                        },
                        "not_found_profile": {
                            "summary": "프로필을 찾을 수 없음",
                            "value": {"message": "상대방 프로필을 찾을 수 없습니다."},
                        },
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
async def post_authors_author_id_sponsor(
    req_body: author_schema.SponsorAuthorReqBody,
    author_id: int = Path(..., description="작가 user_id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **작가 후원**\n
    사용자가 작가에게 캐시로 후원합니다.

    - author_id: 후원 대상 작가의 user_id
    - profile_id: 후원자(현재 사용자)의 프로필 ID
    - donation_price: 후원 금액 (자유 금액)
    """

    return await sponsor_service.sponsor_author(
        author_id=author_id,
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )
