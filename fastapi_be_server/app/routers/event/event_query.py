from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger
import app.services.event.event_service as event_service

router = APIRouter(prefix="/events")


@router.get(
    "",
    tags=["이벤트"],
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
                                        "eventId": 4,
                                        "eventType": "VOTE",
                                        "roundNo": 1,
                                        "bannerImage": "https://cdn.likenovel.dev/panel/prim/pc/1/main_img01.webp",
                                        "subject": "(마감임박) 신작챌린지 2024",
                                        "content": "작품에 투표하세요",
                                        "closeYn": "N",
                                        "beginDate": "2024-08-01T16:00:00",
                                        "endDate": "2024-08-01T16:00:00",
                                        "createdDate": "2024-08-01T16:00:00",
                                        "updatedDate": "2024-08-01T16:00:00",
                                    },
                                    {
                                        "eventId": 2,
                                        "eventType": "IRREGULAR",
                                        "roundNo": 0,
                                        "bannerImage": "https://cdn.likenovel.dev/panel/prim/pc/1/main_img01.webp",
                                        "subject": "백만의 선택",
                                        "content": "백만의 선택, 작품에 투표하세요",
                                        "closeYn": "N",
                                        "beginDate": "2024-08-01T16:00:00",
                                        "endDate": "2024-08-01T16:00:00",
                                        "createdDate": "2024-08-01T16:00:00",
                                        "updatedDate": "2024-08-01T16:00:00",
                                    },
                                    {
                                        "eventId": 1,
                                        "eventType": "REGULAR",
                                        "roundNo": 0,
                                        "bannerImage": "https://cdn.likenovel.dev/panel/prim/pc/1/main_img01.webp",
                                        "subject": "(종료) 신작챌린지 2023",
                                        "content": "작품에 투표하세요",
                                        "closeYn": "Y",
                                        "beginDate": "2024-08-01T16:00:00",
                                        "endDate": "2024-08-01T16:00:00",
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
async def events_all_whether_close_or_not(
    close_yn: str = Query(None, description="이벤트 오픈 여부(기본설정:N)"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    이벤트 목록
    """

    return await event_service.events_all_whether_close_or_not(close_yn=close_yn, db=db)


@router.get(
    "/{event_id}",
    tags=["이벤트"],
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
                                    "eventId": 1,
                                    "eventType": "VOTE",
                                    "roundNo": 1,
                                    "bannerImage": "https://cdn.likenovel.dev/panel/prim/pc/1/main_img01.webp",
                                    "subject": "(종료) 신작챌린지 2023",
                                    "content": "작품에 투표하세요",
                                    "closeYn": "Y",
                                    "beginDate": "2024-08-01T16:00:00",
                                    "endDate": "2024-08-01T16:00:00",
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
async def event_detail_by_eventid(
    event_id: int = Path(..., description="이벤트 번호"),
    round_no: int = Query(default=0, description="투표 라운드 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    이벤트 상세
    """

    return await event_service.event_detail_by_eventid(
        event_id=event_id, db=db, round_no=round_no
    )
