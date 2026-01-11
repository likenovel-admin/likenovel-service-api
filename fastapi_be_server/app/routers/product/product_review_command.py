from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.product_review as product_review_schema
import app.services.product.product_review_service as product_review_service

router = APIRouter(prefix="/product-review")


@router.post("", tags=["작품 리뷰"], dependencies=[Depends(analysis_logger)])
async def post_product_review(
    req_body: product_review_schema.PostProductReviewReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 리뷰 등록
    """

    return await product_review_service.post_product_review(
        req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put("/{id}", tags=["작품 리뷰"], dependencies=[Depends(analysis_logger)])
async def put_product_review(
    req_body: product_review_schema.PutProductReviewReqBody,
    id: int = Path(..., description="작품 리뷰 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 리뷰 수정
    """

    return await product_review_service.put_product_review(
        id, req_body, kc_user_id=user.get("sub"), db=db
    )


@router.delete("/{id}", tags=["작품 리뷰"], dependencies=[Depends(analysis_logger)])
async def delete_product_review(
    id: int = Path(..., description="작품 리뷰 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 리뷰 삭제
    """

    return await product_review_service.delete_product_review(
        id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{review_id}/like",
    tags=["작품 리뷰 - 좋아요"],
    dependencies=[Depends(analysis_logger)],
)
async def add_like_product_review(
    review_id: int = Path(..., description="작품 리뷰 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 리뷰 좋아요 추가
    """

    return await product_review_service.add_like_product_review(
        review_id=review_id, kc_user_id=user.get("sub"), db=db
    )


@router.delete(
    "/{review_id}/like",
    tags=["작품 리뷰 - 좋아요"],
    dependencies=[Depends(analysis_logger)],
)
async def remove_like_product_review(
    review_id: int = Path(..., description="작품 리뷰 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 리뷰 좋아요 삭제
    """

    return await product_review_service.remove_like_product_review(
        review_id=review_id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{review_id}/comment",
    tags=["작품 리뷰 - 댓글"],
    dependencies=[Depends(analysis_logger)],
)
async def post_product_review_comment(
    req_body: product_review_schema.PostProductReviewCommentReqBody,
    review_id: int = Path(..., description="작품 리뷰 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 리뷰 댓글 작성
    """

    return await product_review_service.post_product_review_comment(
        review_id=review_id, req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/comment/{comment_id}",
    tags=["작품 리뷰 - 댓글"],
    dependencies=[Depends(analysis_logger)],
)
async def put_product_review_comment(
    req_body: product_review_schema.PutProductReviewCommentReqBody,
    comment_id: int = Path(..., description="댓글 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 리뷰 댓글 수정
    """

    return await product_review_service.put_product_review_comment(
        comment_id=comment_id, req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.delete(
    "/comment/{comment_id}",
    tags=["작품 리뷰 - 댓글"],
    dependencies=[Depends(analysis_logger)],
)
async def delete_product_review_comment(
    comment_id: int = Path(..., description="댓글 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 리뷰 댓글 삭제
    """

    return await product_review_service.delete_product_review_comment(
        comment_id=comment_id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{review_id}/report",
    tags=["작품 리뷰 - 신고"],
    dependencies=[Depends(analysis_logger)],
)
async def post_product_review_report(
    req_body: product_review_schema.PostProductReviewReportReqBody,
    review_id: int = Path(..., description="작품 리뷰 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 리뷰 신고
    """

    return await product_review_service.post_product_review_report(
        review_id=review_id, req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/comment/{comment_id}/report",
    tags=["작품 리뷰 댓글 - 신고"],
    dependencies=[Depends(analysis_logger)],
)
async def post_product_review_comment_report(
    req_body: product_review_schema.PostProductReviewCommentReportReqBody,
    comment_id: int = Path(..., description="작품 리뷰 댓글 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 리뷰 댓글 신고
    """

    return await product_review_service.post_product_review_comment_report(
        comment_id=comment_id, req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/{review_id}/block",
    tags=["작품 리뷰 - 차단"],
    dependencies=[Depends(analysis_logger)],
)
async def put_product_review_block(
    review_id: int = Path(..., description="작품 리뷰 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 리뷰 작성자 차단/차단해제
    """

    return await product_review_service.put_product_review_block(
        review_id=review_id, kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/comment/{comment_id}/block",
    tags=["작품 리뷰 댓글 - 차단"],
    dependencies=[Depends(analysis_logger)],
)
async def put_product_review_comment_block(
    comment_id: int = Path(..., description="작품 리뷰 댓글 번호"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    작품 리뷰 댓글 작성자 차단/차단해제
    """

    return await product_review_service.put_product_review_comment_block(
        comment_id=comment_id, kc_user_id=user.get("sub"), db=db
    )
