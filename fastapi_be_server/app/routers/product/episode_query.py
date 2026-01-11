from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.services.product.episode_service as episode_service

router = APIRouter(prefix="/episodes")


@router.get(
    "/{episode_id}",
    tags=["회차 - 뷰어"],
    responses={
        200: {
            "description": "회차 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "뷰어 관련 데이터 전달",
                            "value": {
                                "data": {
                                    "product_id": 1,
                                    "title": "작품 제목",
                                    "episodeTitle": "1화. 에피소드 제목",
                                    "epubFilePath": "https://a168bba93203dec90f4f7ddda837c772.r2.cloudflarestorage.com/epub/XHzE2P7XSLOFQCXv0vbC6g.epub?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=073f266abc091744da51a72250a10c32%2F20241119%2Fapac%2Fs3%2Faws4_request&X-Amz-Date=20241119T070922Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=host&X-Amz-Signature=28c6cde4b6c1f1006e03fd52dba94f1ad0c6d2ad3f7e953d8ac2edfd744ef90a",
                                    "bingeWatchYn": "N",
                                    "commentCount": 30,
                                    "likeCount": 30,
                                    "liked": "Y",
                                    "recommendYn": "Y",
                                    "bookmarkYn": "N",
                                    "authorComment": "안녕하세요",
                                    "evaluationYn": "N",
                                    "nextEpisodes": 3,
                                    "commentOpenYn": "Y",
                                    "evaluationOpenYn": "Y",
                                    "previousEpisodeId": 3,
                                    "nextEpisodeId": 7,
                                    "priceType": "free",
                                    "ownType": "own",
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
async def get_episodes_episode_id(
    episode_id: str = Path(..., description="회차 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 이전화/다음화, 정주행 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    회차 보기
    (뷰어)
    """

    return await episode_service.get_episodes_episode_id(
        episode_id=episode_id, kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/episode/upload/{file_name}",
    tags=["회차 - 회차 관리"],
    responses={
        200: {
            "description": "파일 업로드가 가능한 URL 생성",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "파일 업로드 권한이 있는 presigned URL을 생성한 후 전달",
                            "value": {
                                "data": {
                                    "episodeImageFileId": 1,
                                    "episodeImageUploadPath": "https://a168bba93203dec90f4f7ddda837c772.r2.cloudflarestorage.com/image/episode/NIVOD2R3QhShEfuI37qmxA.webp?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=073f266abc091744da51a72250a10c32%2F20241108%2Fapac%2Fs3%2Faws4_request&X-Amz-Date=20241108T110511Z&X-Amz-Expires=10800&X-Amz-SignedHeaders=host&X-Amz-Signature=63b1e666f8a9eb8874053dd214e1c35f8a01dd89ca603447220cda2b3ad4df57",
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
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "file_name 값 validation 에러(유효하지 않은 file_name 값)",
                            "value": {"code": "E4224"},
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
async def get_episodes_episode_upload_file_name(
    file_name: str = Path(..., description="원본 파일명(.webp)"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    회차 내 이미지 업로드 버튼
    (글쓰기 작품 만들기 회차관리 회차등록)
    """

    return await episode_service.get_episodes_episode_upload_file_name(
        file_name=file_name, kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/episode/download/{episode_image_file_id}",
    tags=["회차 - 회차 관리"],
    responses={
        200: {
            "description": "파일 다운로드가 가능한 URL 생성",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "파일 다운로드 권한이 있는 URL을 생성한 후 전달",
                            "value": {
                                "data": {
                                    "episodeImageFileId": 1,
                                    "episodeImageDownloadPath": "https://cdn.likenovel.dev/episode/km1SXT1lQnK3LWntKVOrDA.webp",
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
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "file_name 값 validation 에러(유효하지 않은 file_name 값)",
                            "value": {"code": "E4224"},
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
async def get_episodes_episode_download_episode_image_file_id(
    episode_image_file_id: str = Path(..., description="파일 아이디"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    회차 내 이미지 다운로드
    (글쓰기 작품 만들기 회차관리 회차등록)
    """

    return await episode_service.get_episodes_episode_download_episode_image_file_id(
        episode_image_file_id=episode_image_file_id, kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/{episode_id}/info",
    tags=["회차 - 회차 관리"],
    responses={
        200: {
            "description": "저장된 회차 정보 내용 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "저장된 회차 정보",
                            "value": {
                                "data": {
                                    "episodeId": 1,
                                    "title": "제목",
                                    "content": "내용",
                                    "authorComment": "작가의 말",
                                    "evaluationOpenYn": "Y",
                                    "commentOpenYn": "Y",
                                    "episodeOpenYn": "Y",
                                    "publishReserveYn": "N",
                                    "publishReserveDate": "2024-03-05T12:35:00",
                                    "priceType": "free",
                                    "likeCount": 30,
                                    "liked": "Y",
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
async def get_episodes_episode_id_info(
    episode_id: str = Path(..., description="회차 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    저장된 회차 정보 내용 조회
    """

    return await episode_service.get_episodes_episode_id_info(
        episode_id=episode_id, kc_user_id=user.get("sub"), db=db
    )


@router.get(
    "/products/{product_id}/info",
    tags=["회차 - 회차 관리"],
    responses={
        200: {
            "description": "회차 등록 상단 최근 회차 정보 내용 조회",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "회차 등록 상단 최근 회차 정보(등록한 회차 없으면 episodeTitle null값 전달)",
                            "value": {
                                "data": {
                                    "title": "작품 제목",
                                    "episodeTitle": "1화. 에피소드 제목",
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
async def get_episodes_products_product_id_info(
    product_id: str = Path(..., description="작품 id"),
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    회차 등록 상단 최근 회차 정보 내용 조회
    """

    return await episode_service.get_episodes_products_product_id_info(
        product_id=product_id, kc_user_id=user.get("sub"), db=db
    )
