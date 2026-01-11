from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.user_giftbook as user_giftbook_schema
import app.services.user.user_giftbook_service as user_giftbook_service

router = APIRouter(prefix="/user-giftbook")


@router.post("", tags=["선물함"], dependencies=[Depends(analysis_logger)])
async def post_user_giftbook(
    req_body: user_giftbook_schema.PostUserGiftbookReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    선물함 등록
    """

    return await user_giftbook_service.post_user_giftbook(
        req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put("/{id}", tags=["선물함"], dependencies=[Depends(analysis_logger)])
async def put_user_giftbook(
    req_body: user_giftbook_schema.PutUserGiftbookReqBody,
    id: int = Path(..., description="선물함 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    선물함 수정
    """

    return await user_giftbook_service.put_user_giftbook(id, req_body, db=db)


@router.delete("/{id}", tags=["선물함"], dependencies=[Depends(analysis_logger)])
async def delete_user_giftbook(
    id: int = Path(..., description="선물함 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    선물함 삭제
    """

    return await user_giftbook_service.delete_user_giftbook(id, db=db)


@router.post(
    "/{id}/receive",
    tags=["선물함"],
    responses={
        200: {
            "description": "선물 받기 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "성공",
                            "value": {
                                "result": True,
                                "message": "선물을 받았습니다.",
                            },
                        }
                    }
                }
            },
        },
        400: {
            "description": "Bad Request",
            "content": {
                "application/json": {
                    "examples": {
                        "already_received": {
                            "summary": "이미 받은 선물",
                            "value": {
                                "detail": "이미 받은 선물입니다.",
                            },
                        },
                        "expired": {
                            "summary": "유효기간 만료",
                            "value": {
                                "detail": "선물의 유효기간(7일)이 만료되었습니다.",
                            },
                        },
                    }
                }
            },
        },
        403: {
            "description": "Forbidden",
            "content": {
                "application/json": {
                    "examples": {
                        "forbidden": {
                            "summary": "권한 없음",
                            "value": {
                                "detail": "권한이 없습니다.",
                            },
                        }
                    }
                }
            },
        },
        404: {
            "description": "Not Found",
            "content": {
                "application/json": {
                    "examples": {
                        "not_found": {
                            "summary": "선물함을 찾을 수 없음",
                            "value": {
                                "detail": "존재하지 않습니다.",
                            },
                        }
                    }
                }
            },
        },
    },
    dependencies=[Depends(analysis_logger)],
)
async def receive_user_giftbook(
    id: int = Path(..., description="선물함 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    선물 받기
    - 선물함에서 선물을 받아 대여권으로 전환
    - 유효기간: 선물함 생성일로부터 7일
    """

    return await user_giftbook_service.receive_user_giftbook(
        giftbook_id=id, kc_user_id=user.get("sub"), db=db
    )
