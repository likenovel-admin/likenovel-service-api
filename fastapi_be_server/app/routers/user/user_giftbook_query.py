from typing import Any, Dict
from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.user.user_giftbook_service as user_giftbook_service

router = APIRouter(prefix="/user-giftbook")


@router.get(
    "",
    tags=["선물함"],
    responses={
        200: {
            "description": "",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "범용 대여권",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "user_id": 1,
                                        "product_id": None,
                                        "episode_id": None,
                                        "ticket_type": "comped",
                                        "own_type": "rental",
                                        "acquisition_type": "event",
                                        "acquisition_id": 100,
                                        "read_yn": "N",
                                        "received_yn": "N",
                                        "received_date": None,
                                        "reason": "이벤트 보상",
                                        "amount": 1,
                                        "created_id": -1,
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_id": -1,
                                        "updated_date": "2024-08-01T16:00:00",
                                        "expiration_date": "2024-08-08T16:00:00",
                                        "product": None,
                                        "episode": None,
                                        "event": {
                                            "id": 100,
                                            "title": "신규 가입 이벤트",
                                            "start_date": "2024-08-01T00:00:00",
                                            "end_date": "2024-08-31T23:59:59",
                                            "type": "add-comment",
                                            "reward_type": "ticket",
                                            "reward_amount": 1,
                                        },
                                        "quest": None,
                                        "promotion": None,
                                    }
                                ]
                            },
                        },
                        "success_2": {
                            "summary": "특정 작품 대여권",
                            "value": {
                                "data": [
                                    {
                                        "id": 2,
                                        "user_id": 1,
                                        "product_id": 123,
                                        "episode_id": None,
                                        "ticket_type": "comped",
                                        "own_type": "rental",
                                        "acquisition_type": "quest",
                                        "acquisition_id": 5,
                                        "read_yn": "N",
                                        "received_yn": "N",
                                        "received_date": None,
                                        "reason": "퀘스트 보상",
                                        "amount": 1,
                                        "created_id": -1,
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_id": -1,
                                        "updated_date": "2024-08-01T16:00:00",
                                        "expiration_date": "2024-08-08T16:00:00",
                                        "product": {
                                            "product_id": 123,
                                            "title": "환생한 마법사",
                                            "author_name": "홍길동",
                                            "thumbnail_url": "/files/covers/product_123.jpg",
                                            "product_type": "web_novel",
                                            "status_code": "ongoing",
                                        },
                                        "episode": None,
                                        "event": None,
                                        "quest": {
                                            "quest_id": 5,
                                            "title": "첫 작품 읽기",
                                            "reward_id": 100,
                                            "end_date": None,
                                            "goal_stage": 1,
                                            "use_yn": "Y",
                                        },
                                        "applied_promotion": None,
                                        "direct_promotion": None,
                                    }
                                ]
                            },
                        },
                        "success_3": {
                            "summary": "특정 에피소드 대여권",
                            "value": {
                                "data": [
                                    {
                                        "id": 3,
                                        "user_id": 1,
                                        "product_id": None,
                                        "episode_id": 456,
                                        "ticket_type": "comped",
                                        "own_type": "rental",
                                        "acquisition_type": "admin_direct",
                                        "acquisition_id": None,
                                        "read_yn": "N",
                                        "received_yn": "N",
                                        "received_date": None,
                                        "reason": "관리자 지급",
                                        "amount": 1,
                                        "created_id": -1,
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_id": -1,
                                        "updated_date": "2024-08-01T16:00:00",
                                        "expiration_date": "2024-08-08T16:00:00",
                                        "product": {
                                            "product_id": 123,
                                            "title": "환생한 마법사",
                                            "author_name": "홍길동",
                                            "thumbnail_url": "/files/covers/product_123.jpg",
                                            "product_type": "web_novel",
                                            "status_code": "ongoing",
                                        },
                                        "episode": {
                                            "episode_id": 456,
                                            "product_id": 123,
                                            "episode_no": 10,
                                            "episode_title": "각성",
                                            "price_type": "paid",
                                            "open_yn": "Y",
                                        },
                                        "event": None,
                                        "quest": None,
                                        "promotion": None,
                                    }
                                ]
                            },
                        },
                        "success_4": {
                            "summary": "신청 프로모션 보상",
                            "value": {
                                "data": [
                                    {
                                        "id": 4,
                                        "user_id": 1,
                                        "product_id": None,
                                        "episode_id": None,
                                        "ticket_type": "comped",
                                        "own_type": "rental",
                                        "acquisition_type": "applied_promotion",
                                        "acquisition_id": 50,
                                        "read_yn": "N",
                                        "received_yn": "N",
                                        "received_date": None,
                                        "reason": "신청 프로모션 보상",
                                        "amount": 1,
                                        "created_id": -1,
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_id": -1,
                                        "updated_date": "2024-08-01T16:00:00",
                                        "expiration_date": "2024-08-08T16:00:00",
                                        "product": None,
                                        "episode": None,
                                        "event": None,
                                        "quest": None,
                                        "promotion": {
                                            "id": 50,
                                            "product_id": 123,
                                            "type": "waiting-for-free",
                                            "status": "ing",
                                            "start_date": "2024-08-01T00:00:00",
                                            "end_date": "2024-08-31T23:59:59",
                                            "num_of_ticket_per_person": 1,
                                            "promotion_category": "applied_promotion",
                                        },
                                    }
                                ]
                            },
                        },
                        "success_5": {
                            "summary": "직접 프로모션 보상",
                            "value": {
                                "data": [
                                    {
                                        "id": 5,
                                        "user_id": 1,
                                        "product_id": None,
                                        "episode_id": None,
                                        "ticket_type": "comped",
                                        "own_type": "rental",
                                        "acquisition_type": "direct_promotion",
                                        "acquisition_id": 60,
                                        "read_yn": "N",
                                        "received_yn": "N",
                                        "received_date": None,
                                        "reason": "직접 프로모션 보상",
                                        "amount": 1,
                                        "created_id": -1,
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_id": -1,
                                        "updated_date": "2024-08-01T16:00:00",
                                        "expiration_date": "2024-08-08T16:00:00",
                                        "product": None,
                                        "episode": None,
                                        "event": None,
                                        "quest": None,
                                        "promotion": {
                                            "id": 60,
                                            "product_id": 123,
                                            "type": "free-for-first",
                                            "status": "ing",
                                            "start_date": "2024-08-01T00:00:00",
                                            "num_of_ticket_per_person": 2,
                                            "promotion_category": "direct_promotion",
                                        },
                                    }
                                ]
                            },
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
async def user_giftbook_list(
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    선물함 목록
    - 작품/에피소드 정보 포함
    - 유효기간 만료일 포함 (선물함 생성일 + 7일)
    - 획득 정보 포함 (이벤트, 퀘스트, 신청 프로모션, 직접 프로모션 등)
    """

    return await user_giftbook_service.user_giftbook_list(
        kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/{id}",
    tags=["선물함"],
    responses={
        200: {
            "description": "",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "범용 대여권",
                            "value": {
                                "data": {
                                    "id": 1,
                                    "user_id": 1,
                                    "product_id": None,
                                    "episode_id": None,
                                    "ticket_type": "comped",
                                    "own_type": "rental",
                                    "acquisition_type": "event",
                                    "acquisition_id": 100,
                                    "read_yn": "N",
                                    "received_yn": "N",
                                    "received_date": None,
                                    "reason": "이벤트 보상",
                                    "amount": 1,
                                    "created_id": -1,
                                    "created_date": "2024-08-01T16:00:00",
                                    "updated_id": -1,
                                    "updated_date": "2024-08-01T16:00:00",
                                    "expiration_date": "2024-08-08T16:00:00",
                                    "product": None,
                                    "episode": None,
                                    "event": {
                                        "id": 100,
                                        "title": "신규 가입 이벤트",
                                        "start_date": "2024-08-01T00:00:00",
                                        "end_date": "2024-08-31T23:59:59",
                                        "type": "add-comment",
                                        "reward_type": "ticket",
                                        "reward_amount": 1,
                                    },
                                    "quest": None,
                                    "applied_promotion": None,
                                    "direct_promotion": None,
                                }
                            },
                        },
                        "success_2": {
                            "summary": "특정 에피소드 대여권 (product 자동 조회)",
                            "value": {
                                "data": {
                                    "id": 3,
                                    "user_id": 1,
                                    "product_id": None,
                                    "episode_id": 456,
                                    "ticket_type": "comped",
                                    "own_type": "rental",
                                    "acquisition_type": "admin_direct",
                                    "acquisition_id": None,
                                    "read_yn": "N",
                                    "received_yn": "N",
                                    "received_date": None,
                                    "reason": "관리자 지급",
                                    "amount": 1,
                                    "created_id": -1,
                                    "created_date": "2024-08-01T16:00:00",
                                    "updated_id": -1,
                                    "updated_date": "2024-08-01T16:00:00",
                                    "expiration_date": "2024-08-08T16:00:00",
                                    "product": {
                                        "product_id": 123,
                                        "title": "환생한 마법사",
                                        "author_name": "홍길동",
                                        "thumbnail_url": "/files/covers/product_123.jpg",
                                        "product_type": "web_novel",
                                        "status_code": "ongoing",
                                    },
                                    "episode": {
                                        "episode_id": 456,
                                        "product_id": 123,
                                        "episode_no": 10,
                                        "episode_title": "각성",
                                        "price_type": "paid",
                                        "open_yn": "Y",
                                    },
                                    "event": None,
                                    "quest": None,
                                    "promotion": None,
                                }
                            },
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
async def user_giftbook_detail_by_id(
    id: int = Path(..., description="선물함 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    선물함 상세
    - 작품/에피소드 정보 포함
    - 유효기간 만료일 포함 (선물함 생성일 + 7일)
    - 획득 정보 포함 (이벤트, 퀘스트, 신청 프로모션, 직접 프로모션 등)
    """

    return await user_giftbook_service.user_giftbook_detail_by_id(id=id, db=db)


@router.get(
    "/history/{type}",
    tags=["선물함"],
    responses={
        200: {
            "description": "",
            "content": {
                "application/json": {
                    "examples": {
                        "success_received_1": {
                            "summary": "받은 내역 - 이벤트 보상",
                            "value": {
                                "data": [
                                    {
                                        "id": 1,
                                        "type": "received",
                                        "user_id": 1,
                                        "giftbook_id": 1,
                                        "amount": 1,
                                        "reason": "이벤트 지급",
                                        "created_id": -1,
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_id": -1,
                                        "updated_date": "2024-08-01T16:00:00",
                                        "product_id": None,
                                        "episode_id": None,
                                        "ticket_type": "comped",
                                        "own_type": "rental",
                                        "acquisition_type": "event",
                                        "acquisition_id": 10,
                                        "expiration_date": "2024-08-08T16:00:00",
                                        "product": None,
                                        "episode": None,
                                        "event": {
                                            "id": 10,
                                            "title": "신규 가입 이벤트",
                                            "start_date": "2024-08-01T00:00:00",
                                            "end_date": "2024-08-31T23:59:59",
                                            "type": "add-comment",
                                            "reward_type": "ticket",
                                            "reward_amount": 1,
                                        },
                                        "quest": None,
                                        "promotion": None,
                                    }
                                ]
                            },
                        },
                        "success_received_2": {
                            "summary": "받은 내역 - 퀘스트 보상",
                            "value": {
                                "data": [
                                    {
                                        "id": 2,
                                        "type": "received",
                                        "user_id": 1,
                                        "giftbook_id": 2,
                                        "amount": 1,
                                        "reason": "퀘스트 보상",
                                        "created_id": -1,
                                        "created_date": "2024-08-01T16:00:00",
                                        "updated_id": -1,
                                        "updated_date": "2024-08-01T16:00:00",
                                        "product_id": 123,
                                        "episode_id": None,
                                        "ticket_type": "comped",
                                        "own_type": "rental",
                                        "acquisition_type": "quest",
                                        "acquisition_id": 5,
                                        "expiration_date": "2024-08-08T16:00:00",
                                        "product": {
                                            "product_id": 123,
                                            "title": "환생한 마법사",
                                            "author_name": "홍길동",
                                            "thumbnail_url": "/files/covers/product_123.jpg",
                                            "product_type": "web_novel",
                                            "status_code": "ongoing",
                                        },
                                        "episode": None,
                                        "event": None,
                                        "quest": {
                                            "quest_id": 5,
                                            "title": "첫 작품 읽기",
                                            "reward_id": 100,
                                            "end_date": None,
                                            "goal_stage": 1,
                                            "use_yn": "Y",
                                        },
                                        "applied_promotion": None,
                                        "direct_promotion": None,
                                    }
                                ]
                            },
                        },
                        "success_used": {
                            "summary": "사용 내역 (대여권을 사용한 작품/에피소드 정보 + 남은 대여 시간)",
                            "value": {
                                "data": [
                                    {
                                        "id": 123,
                                        "user_id": 1,
                                        "product_id": 100,
                                        "episode_id": 500,
                                        "ticket_type": "comped",
                                        "own_type": "rental",
                                        "giftbook_id": 1,
                                        "rental_expired_date": "2024-08-08T16:00:00",
                                        "use_yn": "Y",
                                        "use_date": "2024-08-02T16:00:00",
                                        "created_date": "2024-08-01T16:00:00",
                                        "rental_remaining": 259200,
                                        "acquisition_type": "event",
                                        "acquisition_id": 10,
                                        "product": {
                                            "product_id": 100,
                                            "title": "작품 제목",
                                            "price_type": "paid",
                                            "author_name": "작가명",
                                            "thumbnail_url": "https://cdn.example.com/cover.jpg",
                                        },
                                        "episode": {
                                            "episode_id": 500,
                                            "product_id": 100,
                                            "episode_no": 10,
                                            "episode_title": "10화. 에피소드 제목",
                                            "price_type": "paid",
                                        },
                                        "event": {
                                            "id": 10,
                                            "title": "신규 가입 이벤트",
                                            "start_date": "2024-08-01T00:00:00",
                                            "end_date": "2024-08-31T23:59:59",
                                            "type": "add-comment",
                                            "reward_type": "ticket",
                                            "reward_amount": 1,
                                        },
                                        "quest": None,
                                        "promotion": None,
                                    }
                                ]
                            },
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
async def user_gift_transaction_list(
    type: str = Path(..., description="타입, received: 받은 내역, used: 사용 내역"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    선물함 히스토리 목록
    - type=received: 선물을 받은(지급받은) 내역
    - type=used: 선물을 사용한(대여권으로 전환한) 내역
    - 작품/에피소드 정보 포함
    - 유효기간 만료일 포함 (선물함 생성일 + 7일)
    - 획득 정보 포함 (이벤트, 퀘스트, 신청 프로모션, 직접 프로모션 등)
    """

    return await user_giftbook_service.user_gift_transaction_list(
        kc_user_id=user.get("sub"), type=type, db=db
    )
