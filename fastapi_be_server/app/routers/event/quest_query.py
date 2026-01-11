from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.event.quest_service as quest_service

router = APIRouter(prefix="/quests")


@router.get(
    "",
    tags=["퀘스트"],
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

    return await quest_service.quest_all(kc_user_id=user.get("sub"), db=db)


@router.get(
    "/rewarded",
    tags=["퀘스트"],
    responses={
        200: {
            "description": "보상을 받은 퀘스트 목록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "보상을 받은 퀘스트 목록",
                            "value": {
                                "data": [
                                    {
                                        "quest_id": 1,
                                        "title": "출석체크 / 대여권 1장",
                                        "reward_id": 1,
                                        "use_yn": "Y",
                                        "end_date": "2024-12-31T23:59:59",
                                        "created_date": "2024-01-01T00:00:00",
                                        "updated_date": "2024-01-01T00:00:00",
                                        "reward": {
                                            "item_id": 1,
                                            "item_name": "대여권",
                                            "item_type": "ticket",
                                        },
                                        "current_stage": 1,
                                        "achieve_yn": "Y",
                                        "reward_own_yn": "Y",
                                        "reward_received_date": "2024-01-15T10:30:00",
                                    },
                                ]
                            },
                        }
                    }
                }
            },
        },
        404: {
            "description": "사용자를 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "not_found": {
                            "summary": "NOT_FOUND_MEMBER",
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
async def quest_rewarded(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    로그인한 유저가 보상을 받은 퀘스트 목록 조회
    """

    return await quest_service.quest_rewarded(kc_user_id=user.get("sub"), db=db)
