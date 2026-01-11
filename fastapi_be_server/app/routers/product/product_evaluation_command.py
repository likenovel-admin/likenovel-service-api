from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.product_evaluation as product_evaluation_schema
import app.services.product.product_evaluation_service as product_evaluation_service

router = APIRouter(prefix="/product-evaluation")


@router.post("", tags=["작품 평가"], dependencies=[Depends(analysis_logger)])
async def post_product_evaluation(
    req_body: product_evaluation_schema.PostProductEvaluationReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 평가 등록
    """

    return await product_evaluation_service.post_product_evaluation(
        req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put("/{id}", tags=["작품 평가"], dependencies=[Depends(analysis_logger)])
async def put_product_evaluation(
    req_body: product_evaluation_schema.PutProductEvaluationReqBody,
    id: int = Path(..., description="작품 평가 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 평가 수정
    """

    return await product_evaluation_service.put_product_evaluation(
        id, req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put("/{id}", tags=["작품 평가"], dependencies=[Depends(analysis_logger)])
async def delete_product_evaluation(
    id: int = Path(..., description="작품 평가 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 평가 삭제
    """

    return await product_evaluation_service.delete_product_evaluation(
        id, kc_user_id=user.get("sub"), db=db
    )
