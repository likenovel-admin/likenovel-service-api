from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger
import app.services.content.notice_service as notices_service
from app.exceptions import CustomResponseException
from app.const import ErrorMessages

router = APIRouter(prefix="/notices")


@router.get(
    "/rolling-broadcast",
    tags=["공지사항"],
    responses={
        200: {
            "description": "공지사항(notice) 최상위 메시지 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "공지사항(notice) 최상위 메시지 조회",
                            "value": {
                                "data": [
                                    {
                                        "id": 3,  # id
                                        "actionType": "1,000 조회수 달성",  # 행동 종류(무엇을 했는지)
                                        "actionTime": "20:45",  # 행동 시간. 행동의 종류에 따라 값이 없을 수도 있음
                                        "nickname": "",  # 닉네임. 행동의 종류에 따라 값이 없을 수도 있음
                                        "productTitle": "팬텀윈드",  # 작품명
                                    },
                                    {
                                        "id": 2,
                                        "actionType": "댓글",
                                        "actionTime": "18:00",
                                        "nickname": "김기리",
                                        "productTitle": "판타지 세계의 무당이 되었다",
                                    },
                                    {
                                        "id": 1,
                                        "actionType": "무료 1위 달성",
                                        "actionTime": "12:30",
                                        "nickname": "",
                                        "productTitle": "세계전복급 악역으로 오해받고 있습니다",
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
async def rolling_broadcast_notices():
    """
    최상위 메시지 롤링 공지사항 조회
    """
    try:
        return await notices_service.rolling_broadcast_notices()
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )


@router.get(
    "/rolling-notices",
    tags=["공지사항"],
    responses={
        200: {
            "description": "공지사항(notice) 하단 중요 공지사항 목록 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "공지사항(notice) 하단 중요 공지사항 목록 조회",
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
async def rolling_primary_notices(db: AsyncSession = Depends(get_likenovel_db)):
    """
    공지사항(notice) 하단 중요 공지사항 목록 조회
    """
    try:
        return await notices_service.rolling_primary_notices(db=db)
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )


@router.get(
    "",
    tags=["공지사항"],
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
):
    """
    공지사항(notice) 목록 조회
    """
    try:
        return await notices_service.notices_all(page, limit, db=db)
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )


@router.get(
    "/{notice_id}",
    tags=["공지사항"],
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
):
    """
    공지사항(notice) 상세 조회
    """
    try:
        return await notices_service.notice_detail_by_notice_id(notice_id, db=db)
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )
