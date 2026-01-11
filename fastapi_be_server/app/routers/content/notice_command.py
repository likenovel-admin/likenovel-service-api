from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.notice as notice_schema
import app.services.content.notice_service as notice_service

router = APIRouter(prefix="/notices")


@router.post("", tags=["공지사항"], dependencies=[Depends(analysis_logger)])
async def post_notice(
    req_body: notice_schema.PostNoticeReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    공지사항 등록
    """

    return await notice_service.post_notice(req_body, kc_user_id=user.get("sub"), db=db)


@router.put("/{id}", tags=["공지사항"], dependencies=[Depends(analysis_logger)])
async def put_notice(
    req_body: notice_schema.PutNoticeReqBody,
    id: int = Path(..., description="공지사항 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    공지사항 수정
    """

    return await notice_service.put_notice(
        id, req_body, kc_user_id=user.get("sub"), db=db
    )


@router.delete("/{id}", tags=["공지사항"], dependencies=[Depends(analysis_logger)])
async def delete_notice(
    id: int = Path(..., description="공지사항 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    공지사항 삭제
    """

    return await notice_service.delete_notice(id, kc_user_id=user.get("sub"), db=db)
