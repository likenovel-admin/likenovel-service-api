from fastapi import APIRouter, Depends, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.product as product_schema
import app.services.product.product_service as product_service
import app.services.product.product_comment_service as product_comment_service
import app.services.product.product_bookmark_service as product_bookmark_service
import app.services.product.product_notice_service as product_notice_service
import app.services.order.purchase_service as purchase_service
import app.services.gift.author_service as author_service
import app.services.gift.sponsor_service as sponsor_service

router = APIRouter(prefix="/products")

# TODO: 작품 신고 (app/models/product.py에 작품 신고 테이블 신규 설계 후, '작품 댓글 차단/차단해제 버튼' 구현 부분 참고하여 개발)
# TODO: 작품 리뷰 (작품 리뷰 쓰기, 작품 리뷰 추천/비추천 버튼, 작품 리뷰 신고 버튼, 작품 리뷰 차단 버튼, 작품 리뷰 댓글 신고 버튼, 작품 리뷰 댓글 차단 버튼 등)


@router.post(
    "",
    tags=["작품 - 작품 관리"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
                        },
                    }
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "작품 등록/수정 값 validation 에러(유효하지 않은 정보 값)",
                            "value": {"code": "E4225"},
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
async def post_products(
    req_body: product_schema.PostProductsReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 등록 버튼
    (글쓰기 작품 만들기)
    """

    return await product_service.post_products(
        req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/{product_id}",
    tags=["작품 - 작품 관리"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
                        },
                    }
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "작품 등록/수정 값 validation 에러(유효하지 않은 정보 값)",
                            "value": {"code": "E4225"},
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
async def put_products_product_id(
    req_body: product_schema.PutProductsProductIdReqBody,
    product_id: str = Path(..., description="작품 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 정보수정 버튼
    (글쓰기 작품 만들기 회차관리)
    """

    return await product_service.put_products_product_id(
        product_id=product_id, req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/{product_id}/conversion",
    tags=["작품 - 작품 관리"],
    responses={
        200: {
            "description": "작품 일반승급신청/유료전환신청(쿼리스트링 값에 따라 구분)",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "일반승급신청",
                            "value": {
                                "data": {"productId": 1, "productType": "normal"}
                            },
                        },
                        "success_2": {
                            "summary": "유료전환신청",
                            "value": {
                                "data": {"productId": 1, "convertToPaidState": "review"}
                            },
                        },
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def put_products_product_id_conversion(
    product_id: str = Path(..., description="작품 id"),
    category: str = Query(
        None, description="일반승급신청(rank-up), 유료전환신청(paid)"
    ),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 일반승급신청/유료전환신청 버튼
    (작가홈)

    [쿼리스트링 값]
    1. ?category=rank-up: 일반승급신청
    2. ?category=paid: 유료전환신청
    """

    return await product_service.put_products_product_id_conversion(
        category=category, product_id=product_id, kc_user_id=user.get("sub"), db=db
    )


@router.delete(
    "/bookmark",
    tags=["작품 - 북마크"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def delete_products_bookmark(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 북마크 전체삭제 버튼
    (선호작)
    """

    return await product_bookmark_service.delete_products_bookmark(
        kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/{product_id}/bookmark",
    tags=["작품 - 북마크"],
    responses={
        200: {
            "description": "북마크(선작) 설정 및 해제",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 북마크 상태에 따른 반전된 값 및 북마크 수를 전달",
                            "value": {
                                "data": {
                                    "productId": 1,
                                    "bookmarkCount": 30,
                                    "bookmarkYn": "Y",
                                }
                            },
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def put_products_product_id_bookmark(
    product_id: str = Path(..., description="작품 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 북마크/북마크해제 버튼
    (TOP50, 무료/유료, 선호작, 작품 상세, 뷰어, 마이페이지 내 댓글, 통합검색 결과)
    """

    return await product_bookmark_service.put_products_product_id_bookmark(
        product_id=product_id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/comments/episodes/{episode_id}",
    tags=["작품 - 댓글"],
    responses={
        200: {
            "description": "작품 댓글 등록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "생성된 댓글 id 및 갱신된 댓글 수를 전달",
                            "value": {"data": {"commentId": 1, "commentCount": 30}},
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def post_products_comments_episodes_episode_id(
    req_body: product_schema.PostProductsCommentsEpisodesEpisodeIdReqBody,
    episode_id: str = Path(..., description="회차 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 댓글 등록 버튼
    (뷰어)
    """

    return await product_comment_service.post_products_comments_episodes_episode_id(
        episode_id=episode_id, req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/comments/{comment_id}",
    tags=["작품 - 댓글"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def put_products_comments_comment_id(
    req_body: product_schema.PutProductsCommentsCommentIdReqBody,
    comment_id: str = Path(..., description="댓글 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 댓글 수정 버튼
    (작품 상세, 뷰어)
    """

    return await product_comment_service.put_products_comments_comment_id(
        comment_id=comment_id, req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.delete(
    "/comments/{comment_id}",
    tags=["작품 - 댓글"],
    responses={
        200: {
            "description": "작품 댓글 삭제",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "삭제된 댓글 id 및 갱신된 댓글 수를 전달",
                            "value": {"data": {"commentId": 1, "commentCount": 30}},
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def delete_products_comments_comment_id(
    comment_id: str = Path(..., description="댓글 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 댓글 삭제 버튼
    (작품 상세, 뷰어, 마이페이지 내 댓글)
    """

    return await product_comment_service.delete_products_comments_comment_id(
        comment_id=comment_id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/comments/{comment_id}/report",
    tags=["작품 - 댓글"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def post_products_comments_comment_id_report(
    req_body: product_schema.PostProductsCommentsCommentIdReportReqBody,
    comment_id: str = Path(..., description="댓글 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 댓글 신고 버튼
    (작품 상세, 뷰어)
    """

    return await product_comment_service.post_products_comments_comment_id_report(
        comment_id=comment_id, req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{product_id}/report",
    tags=["작품 - 신고"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def post_product_report(
    req_body: product_schema.PostProductReportReqBody,
    product_id: str = Path(..., description="작품 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 신고 버튼
    (작품 상세)
    """

    return await product_service.post_product_report(
        product_id=product_id, req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/comments/{comment_id}/block",
    tags=["작품 - 댓글"],
    responses={
        200: {
            "description": "차단 설정 및 해제",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 차단 상태에 따른 반전된 값 전달",
                            "value": {"data": {"commentId": 1, "blockYn": "N"}},
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def put_products_comments_comment_id_block(
    comment_id: str = Path(..., description="댓글 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 댓글 차단/차단해제 버튼
    (마이페이지 내 댓글, 작품 상세, 뷰어)
    """

    return await product_comment_service.put_products_comments_comment_id_block(
        comment_id=comment_id, kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/comments/{comment_id}/pin",
    tags=["작품 - 댓글"],
    responses={
        200: {
            "description": "상단고정 설정 및 해제",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 상단고정 상태에 따른 반전된 값 전달",
                            "value": {
                                "data": {"commentId": 1, "authorPinnedTopYn": "Y"}
                            },
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def put_products_comments_comment_id_pin(
    comment_id: str = Path(..., description="댓글 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 댓글 상단고정/해제 버튼
    (작가홈)
    """

    return await product_comment_service.put_products_comments_comment_id_pin(
        comment_id=comment_id, kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/comments/{comment_id}/reaction/recommend",
    tags=["작품 - 댓글"],
    responses={
        200: {
            "description": "공감 설정 및 해제",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 공감 여부에 따른 반전된 값 전달",
                            "value": {
                                "data": {
                                    "commentId": 1,
                                    "recommendCount": 10,
                                    "recommendYn": "Y",
                                    "notRecommendCount": 5,
                                    "notRecommendYn": "N",
                                }
                            },
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def put_products_comments_comment_id_reaction_recommend(
    comment_id: str = Path(..., description="댓글 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 댓글 공감 버튼
    (마이페이지 내 댓글, 작품 상세, 뷰어, 작가홈)
    """

    return await product_comment_service.put_products_comments_comment_id_reaction_recommend(
        comment_id=comment_id, kc_user_id=user.get("sub"), db=db
    )


@router.put(
    "/comments/{comment_id}/reaction/not-recommend",
    tags=["작품 - 댓글"],
    responses={
        200: {
            "description": "비공감 설정 및 해제",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 비공감 여부에 따른 반전된 값 전달",
                            "value": {
                                "data": {
                                    "commentId": 1,
                                    "recommendCount": 10,
                                    "recommendYn": "N",
                                    "notRecommendCount": 5,
                                    "notRecommendYn": "N",
                                }
                            },
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def put_products_comments_comment_id_reaction_not_recommend(
    comment_id: str = Path(..., description="댓글 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 댓글 비공감 버튼
    (마이페이지 내 댓글, 작품 상세, 뷰어, 작가홈)
    """

    return await product_comment_service.put_products_comments_comment_id_reaction_not_recommend(
        comment_id=comment_id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{product_id}/notices",
    tags=["작품 - 작품 공지"],
    responses={
        200: {
            "description": "작품 공지 저장/등록",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "새롭게 생성된 작품 공지 id를 전달",
                            "value": {"data": {"productNoticeId": 1}},
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
                        },
                    }
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "작품 공지 저장/등록/수정 값 validation 에러(유효하지 않은 정보 값)",
                            "value": {"code": "E4227"},
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
async def post_products_product_id_notices(
    req_body: product_schema.PostProductsProductIdNoticesReqBody,
    product_id: str = Path(..., description="작품 id"),
    save: Optional[str] = Query(None, description="저장(Y), 등록(N)"),
    product_notice_id: Optional[str] = Query(None, description="생성된 작품 공지 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 공지 저장/등록 버튼
    (글쓰기 작품 만들기 회차관리 회차등록)

    [쿼리스트링 값]
    1. ?save=Y: 저장
    2. ?save=N: 등록
    3. ?product_notice_id: 새로 생성된 작품 공지 id(저장 버튼 클릭 후, 다음에 일어날 저장 혹은 등록 액션에 활용 - 동일한 pk 값으로 업데이트 하기 위함)
    """

    return await product_notice_service.post_products_product_id_notices(
        save=save,
        product_notice_id=product_notice_id,
        product_id=product_id,
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.put(
    "/notices/{product_notice_id}",
    tags=["작품 - 작품 공지"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
                        },
                    }
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "작품 공지 저장/등록/수정 값 validation 에러(유효하지 않은 정보 값)",
                            "value": {"code": "E4227"},
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
async def put_products_notices_product_notice_id(
    req_body: product_schema.PutProductsNoticesProductNoticeIdReqBody,
    product_notice_id: str = Path(..., description="작품 공지 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 공지 수정 버튼
    (글쓰기 작품 만들기 회차관리 회차등록, 글쓰기 작품 만들기 회차관리 공지)
    """

    return await product_notice_service.put_products_notices_product_notice_id(
        product_notice_id=product_notice_id,
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.put(
    "/notices/{product_notice_id}/open",
    tags=["작품 - 작품 공지"],
    responses={
        200: {
            "description": "작품 공지 공개 설정 및 해제",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "현재 공개 상태에 따른 반전된 값 전달",
                            "value": {"data": {"productNoticeId": 1, "openYn": "N"}},
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
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
async def put_products_notices_product_notice_id_open(
    product_notice_id: str = Path(..., description="작품 공지 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    작품 공지 공개/비공개 버튼 버튼
    (글쓰기 작품 만들기 회차관리 공지)
    """

    return await product_notice_service.put_products_notices_product_notice_id_open(
        product_notice_id=product_notice_id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{product_id}/contract-offer",
    tags=["작품 - 계약 제안"],
    responses={
        200: {
            "description": "계약 제안 생성",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "계약 제안이 성공적으로 생성됨",
                            "value": {
                                "data": {
                                    "productId": 1,
                                    "message": "계약 제안이 성공적으로 생성되었습니다.",
                                }
                            },
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
                        },
                    }
                }
            },
        },
        404: {
            "description": "작품을 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "존재하지 않는 작품",
                            "value": {"code": "E4044"},
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
async def post_products_product_id_contract_offer(
    req_body: product_schema.PostProductsProductIdContractOfferReqBody,
    product_id: str = Path(..., description="작품 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 완료**\n
    계약 제안 생성 버튼
    (작품 상세)

    - 제시자가 특정 작품에 대해 계약 제안을 생성합니다.
    - 선인세 범위: ~50, 50~100, 100~200, 200~300, 300~400, 500~
    - CP와 작가간의 정산비율을 퍼센트로 입력합니다. (예: 30, 70)
    - 제안 메시지를 작성할 수 있습니다.
    """

    return await author_service.post_products_product_id_contract_offer(
        product_id=product_id, req_body=req_body, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{product_id}/purchase-all-episodes",
    tags=["작품 - 구매"],
    responses={
        200: {
            "description": "작품 전체 에피소드 구매 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "구매 성공",
                            "value": {
                                "result": True,
                                "data": {
                                    "purchasedCount": 10,
                                    "totalCashUsed": 1000,
                                    "skippedFreeCount": 5,
                                    "skippedOwnedCount": 3,
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
                        "retryPossible_1": {
                            "summary": "캐시 잔액 부족",
                            "value": {"code": "E4002"},
                        },
                        "retryPossible_2": {
                            "summary": "구매 가능한 에피소드가 없음",
                            "value": {"code": "E4003"},
                        },
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
            "description": "작품을 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "존재하지 않는 작품",
                            "value": {"code": "E4044"},
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
async def purchase_all_episodes_with_cash(
    req_body: product_schema.PurchaseAllEpisodesWithCashReqBody,
    product_id: str = Path(..., description="작품 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    캐시로 작품의 전체 에피소드 구매 (소장)

    작품의 모든 유료 에피소드를 일괄 구매합니다.
    - 이미 소장한 에피소드는 건너뜁니다.
    - 무료 에피소드는 건너뜁니다.
    - 에피소드당 100 캐시를 소모합니다.
    """

    return await purchase_service.purchase_all_episodes_with_cash(
        product_id=int(product_id),
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.put(
    "/{product_id}/interest/revive",
    tags=["작품 - 관심"],
    responses={
        200: {
            "description": "관심 되살리기 성공",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "관심이 되살아남",
                            "value": {
                                "data": {
                                    "productId": 1,
                                    "interestStatus": "interest_active",
                                    "interestEndDate": "2025-10-25T12:00:00",
                                    "message": "관심이 성공적으로 되살아났습니다.",
                                }
                            },
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
                        },
                        "retryPossible_2": {
                            "summary": "본인인증 페이지로 이동(본인인증이 안 된 경우에 api 요청을 할 때 발생)",
                            "value": {"code": "E4012"},
                        },
                    }
                }
            },
        },
        404: {
            "description": "작품을 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "존재하지 않는 작품",
                            "value": {"code": "E4044"},
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
                            "summary": "유효하지 않은 작품 ID",
                            "value": {"code": "E4220"},
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
async def put_products_product_id_interest_revive(
    product_id: str = Path(..., description="작품 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **관심 되살리기 API**\n
    관심끊기기 임박 상태를 관심 유지중 상태로 변경합니다.

    - tb_user_product_usage의 updated_date를 현재 시간으로 업데이트합니다.
    - 관심 종료일이 현재 시간 + 3일로 연장됩니다.
    """

    return await product_service.revive_product_interest(
        product_id=product_id, kc_user_id=user.get("sub"), db=db
    )


@router.post(
    "/{product_id}/sponsor",
    tags=["작품 - 후원"],
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
                        "retryPossible_1": {
                            "summary": "캐시 잔액 부족",
                            "value": {"code": "E4002"},
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
            "description": "작품을 찾을 수 없음",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "존재하지 않는 작품",
                            "value": {"code": "E4044"},
                        },
                        "retryPossible_2": {
                            "summary": "존재하지 않는 프로필",
                            "value": {"code": "E4045"},
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
async def post_products_product_id_sponsor(
    req_body: product_schema.SponsorProductReqBody,
    product_id: int = Path(..., description="작품 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **작품 후원**\n
    사용자가 특정 작품에 캐시로 후원합니다.

    - product_id: 후원 대상 작품 ID
    - profile_id: 후원자(현재 사용자)의 프로필 ID
    - donation_price: 후원 금액 (자유 금액)
    - message: 전달 메시지 (선택)
    """

    return await sponsor_service.sponsor_product(
        product_id=product_id,
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )
