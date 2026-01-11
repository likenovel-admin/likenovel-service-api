from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger
import app.services.content.support_service as support_service

router = APIRouter(prefix="/support")


@router.get("/faqs", tags=["고객지원"], dependencies=[Depends(analysis_logger)])
async def get_support_faqs(
    category: str = Query(None, description="카테고리"),
    page: int = Query(1, description="페이지 번호"),
    count_per_page: int = Query(10, description="페이지당 항목 수"),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    FAQ 목록 출력 (페이지네이션 포함)
    """

    return await support_service.get_support_faqs(
        category=category, page=page, count_per_page=count_per_page, db=db
    )


@router.get(
    "/faqs/{faq_id}", tags=["고객지원"], dependencies=[Depends(analysis_logger)]
)
async def get_support_faqs_faq_id(
    faq_id: str, db: AsyncSession = Depends(get_likenovel_db)
):
    """
    **TODO: 구현 후 수정 및 최종 테스트 필**\n
    특정 FAQ 내용 상세 출력
    """

    return await support_service.get_support_faqs_faq_id(faq_id=faq_id, db=db)
