from fastapi import APIRouter, Depends, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Union, Dict, Any
from urllib.parse import quote

from app.const import settings, ErrorMessages, LOGGER_TYPE
from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
from app.exceptions import CustomResponseException
from app.config.log_config import service_error_logger
import app.schemas.auth as auth_schema
import app.services.auth.auth_service as auth_service

router = APIRouter(prefix="/auth")

error_logger = service_error_logger(LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_ERROR)

# TODO: 본인인증, 통합아이디 연동 (tb_user의 identity_yn과 tb_user_social의 integrated_user_id, default_yn 활용)


@router.post(
    "/signup",
    tags=["인증 - 세션"],
    responses={
        200: {
            "description": "회원가입 결과(로그인까지 처리)",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "회원가입한 유저 데이터 생성 후, 로그인(/auth/signin)까지 처리하여 토큰 발급",
                            "value": {
                                "data": {
                                    "auth": {
                                        "accessToken": "eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICJUdElPUi1YQ0ZHVDI0SXlCZnZaQzIxajJlMXcxNWh1MGhlb0IzSWtBbTd3In0.eyJleHAiOjE3MjUyNTE0MDksImlhdCI6MTcyNTI1MTEwOSwianRpIjoiZTc3NGRhMzctMDM5Ny00YzQzLTlkZmYtMzlmYTM0NzNmMTFlIiwiaXNzIjoiaHR0cHM6Ly9hdXRoLmxpa2Vub3ZlbC5kZXYvcmVhbG1zL2xpa2Vub3ZlbCIsImF1ZCI6InJlYWxtLW1hbmFnZW1lbnQiLCJzdWIiOiIxMTY1NTQ4Zi1iNTA0LTQwYmQtYTYxNC0zMDEwMWEyMjU0ZmYiLCJ0eXAiOiJCZWFyZXIiLCJhenAiOiJ0ZXN0QSIsInNpZCI6IjI5M2NkZGVmLThkNTMtNDkzNi05OWFmLTZmYWRhZWE5NGU1NyIsImFjciI6IjEiLCJhbGxvd2VkLW9yaWdpbnMiOlsiIl0sInJlc291cmNlX2FjY2VzcyI6eyJyZWFsbS1tYW5hZ2VtZW50Ijp7InJvbGVzIjpbIm1hbmFnZS11c2VycyIsInZpZXctdXNlcnMiLCJxdWVyeS1ncm91cHMiLCJxdWVyeS11c2VycyJdfX0sInNjb3BlIjoib3BlbmlkIGVtYWlsIHByb2ZpbGUiLCJlbWFpbF92ZXJpZmllZCI6ZmFsc2UsInByZWZlcnJlZF91c2VybmFtZSI6InRlc3RAdGVzdC5jb20iLCJlbWFpbCI6InRlc3RAdGVzdC5jb20ifQ.Hz7PXtO_uGrpLxfTiBKXZEPMASOIAFuN-k0cDDfCJWaYaFsHx5leUDvkKXfMwifWdHfyg-Z7zNQrPsz4UAQdzxgAs0XVxZNgeTkr8OVyzv_4A26fUWFazoUflXAIBNgDEVDjA4RUvMbzJOpXsUr4iRbn4T_WCFLEGgSzUaK2vfiDzIaqEdm9LXJ_mE-aU6W7NyQGRqxS0gSVts5h3gdtAH50Ue1qe_84Vyg4hMvjsXnjDy2hSFu6jmhDBz-FrhvoJuN_fiYHJcVGVF5gx93YJ_xuJPvghI-HeyfujqG9pOGF-wMFZx6o6cksE5cTtIP-3miyxpdqU45-Emav8YT1oA",
                                        "accessTokenExpiresIn": 300,
                                        "refreshToken": "eyJhbGciOiJIUzUxMiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICIyMDNiODBmNS0zYWRkLTQxMTctYjQ4Zi02NDU2NzkwMDYwZGIifQ.eyJleHAiOjE3MjUyNTI5MDksImlhdCI6MTcyNTI1MTEwOSwianRpIjoiZmFjMGQzZTItZGI1Yy00NmMzLTkwYjgtNjEwMDFlNWVmNGY0IiwiaXNzIjoiaHR0cHM6Ly9hdXRoLmxpa2Vub3ZlbC5kZXYvcmVhbG1zL2xpa2Vub3ZlbCIsImF1ZCI6Imh0dHBzOi8vYXV0aC5saWtlbm92ZWwuZGV2L3JlYWxtcy9saWtlbm92ZWwiLCJzdWIiOiIxMTY1NTQ4Zi1iNTA0LTQwYmQtYTYxNC0zMDEwMWEyMjU0ZmYiLCJ0eXAiOiJSZWZyZXNoIiwiYXpwIjoidGVzdEEiLCJzaWQiOiIyOTNjZGRlZi04ZDUzLTQ5MzYtOTlhZi02ZmFkYWVhOTRlNTciLCJzY29wZSI6Im9wZW5pZCBhY3Igcm9sZXMgYmFzaWMgZW1haWwgcHJvZmlsZSB3ZWItb3JpZ2lucyJ9.V9lDnNFw-zo2diQn4pruxsVMUaB78IuCeTOMxEy7poyqvUwbZQa0SWhNx4cPa_7CFHustAIGHj_SJkhf5-fvIA",
                                        "refreshTokenExpiresIn": 1800,
                                        "recentSignInType": "naver",
                                        "userId": 13,
                                        "birthDate": "2000-01-31",
                                        "gender": "M",
                                    }
                                }
                            },
                        }
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
                            "summary": "email 값 validation 에러(유효하지 않은 email 값)",
                            "value": {"code": "E4220"},
                        },
                        "retryPossible_2": {
                            "summary": "password 값 validation 에러(유효하지 않은 password 값)",
                            "value": {"code": "E4221"},
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
async def post_auth_signup(
    req_body: auth_schema.SignupReqBody, db: AsyncSession = Depends(get_likenovel_db)
):
    """
    **인터페이스 구현 최종 완료**\n
    신규 회원정보 insert.
    회원가입 처리 후 로그인(/auth/signin) 처리까지 진행.
    키클록 인증 후, 발급받은 토큰 및 일부 회원정보 리턴
    """

    res_body = await auth_service.post_auth_signup(req_body=req_body, db=db)

    req_body = auth_schema.SigninReqBody(**res_body)

    return await post_auth_signin(req_body=req_body, db=db)


@router.get(
    "/signup/naver/callback",
    tags=["인증 - sns 로그인 연동"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "state 값 validation 에러(유효하지 않은 state 값)",
                            "value": {"code": "E4222"},
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
async def get_auth_signup_naver_callback(
    code: Union[str, None] = None,
    state: Union[str, None] = None,
    error: Union[str, None] = None,
    error_description: Union[str, None] = None,
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    네이버 로그인 콜백(회원가입)
    네이버 인증 후, callback으로 전달 받은 쿼리스트링 값으로 네이버 정보 조회.
    이후 회원가입 및 로그인 처리 후 메인페이지로 redirect.
    https://nid.naver.com/oauth2.0/authorize?client_id=0XC3m3M1KszmRR7vkIIh&redirect_uri=https%3A//api.likenovel.net/v1/command/auth/signup/naver/callback&response_type=code&state=Y-likenovel
    """
    try:
        res_body = await auth_service.get_auth_signup_naver_callback(
            db=db, code=code, state=state, error=error
        )

        if res_body.get("ad_info_agree_yn"):  # 미등록(회원가입 후 로그인)
            req_body = auth_schema.SignupReqBody(**res_body)
            res_body = await post_auth_signup(req_body=req_body, db=db)
        else:  # 기 등록(로그인)
            req_body = auth_schema.SigninReqBody(**res_body)
            res_body = await post_auth_signin(req_body=req_body, db=db)

        url_with_query = f"{settings.FE_REDIRECT_URL}?sns_id={res_body.get('data').get('auth').get('snsId')}&temp_issued_key={res_body.get('data').get('auth').get('tempIssuedKey')}"

        return RedirectResponse(url=url_with_query, status_code=302)
    except Exception as e:
        error_message = str(e) if str(e) else "회원가입 처리 중 오류가 발생했습니다."
        error_logger.error(
            f"Naver signup callback error: {error_message}", exc_info=True
        )
        error_url = f"{settings.FE_DOMAIN}/sign-up?error={quote(error_message)}"
        return RedirectResponse(url=error_url, status_code=302)


@router.get(
    "/signup/google/callback",
    tags=["인증 - sns 로그인 연동"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "state 값 validation 에러(유효하지 않은 state 값)",
                            "value": {"code": "E4222"},
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
async def get_auth_signup_google_callback(
    code: Union[str, None] = None,
    state: Union[str, None] = None,
    error: Union[str, None] = None,
    error_description: Union[str, None] = None,
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    구글 로그인 콜백(회원가입)
    구글 인증 후, callback으로 전달 받은 쿼리스트링 값으로 구글 정보 조회.
    이후 회원가입 및 로그인 처리 후 홈페이지로 redirect.
    https://accounts.google.com/o/oauth2/v2/auth?client_id=1030423380095-6rvpkqp76c5fshtld4s6sebls3vf3048.apps.googleusercontent.com&redirect_uri=https://api.likenovel.net/v1/command/auth/signup/google/callback&response_type=code&state=Y-1900-01-01-M-likenovel&scope=email%20profile
    """
    try:
        res_body = await auth_service.get_auth_signup_google_callback(
            db=db, code=code, state=state, error=error
        )

        if res_body.get("ad_info_agree_yn"):  # 미등록(회원가입 후 로그인)
            req_body = auth_schema.SignupReqBody(**res_body)
            res_body = await post_auth_signup(req_body=req_body, db=db)
        else:  # 기 등록(로그인)
            req_body = auth_schema.SigninReqBody(**res_body)
            res_body = await post_auth_signin(req_body=req_body, db=db)

        url_with_query = f"{settings.FE_REDIRECT_URL}?sns_id={res_body.get('data').get('auth').get('snsId')}&temp_issued_key={res_body.get('data').get('auth').get('tempIssuedKey')}"

        return RedirectResponse(url=url_with_query, status_code=302)
    except Exception as e:
        error_message = str(e) if str(e) else "회원가입 처리 중 오류가 발생했습니다."
        error_logger.error(
            f"Google signup callback error: {error_message}", exc_info=True
        )
        error_url = f"{settings.FE_DOMAIN}/sign-up?error={quote(error_message)}"
        return RedirectResponse(url=error_url, status_code=302)


@router.get(
    "/signup/kakao/callback",
    tags=["인증 - sns 로그인 연동"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "state 값 validation 에러(유효하지 않은 state 값)",
                            "value": {"code": "E4222"},
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
async def get_auth_signup_kakao_callback(
    code: Union[str, None] = None,
    state: Union[str, None] = None,
    error: Union[str, None] = None,
    error_description: Union[str, None] = None,
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    카카오 로그인 콜백(회원가입)
    카카오 인증 후, callback으로 전달 받은 쿼리스트링 값으로 카카오 정보 조회.
    이후 회원가입 및 로그인 처리 후 홈페이지로 redirect.
    https://kauth.kakao.com/oauth/authorize?client_id=8f6f1ee843ffbff8549267db3d2fb3ce&redirect_uri=https://api.likenovel.net/v1/command/auth/signup/kakao/callback&response_type=code&state=Y-likenovel
    """
    try:
        res_body = await auth_service.get_auth_signup_kakao_callback(
            db=db, code=code, state=state, error=error
        )

        if res_body.get("ad_info_agree_yn"):  # 미등록(회원가입 후 로그인)
            req_body = auth_schema.SignupReqBody(**res_body)
            res_body = await post_auth_signup(req_body=req_body, db=db)
        else:  # 기 등록(로그인)
            req_body = auth_schema.SigninReqBody(**res_body)
            res_body = await post_auth_signin(req_body=req_body, db=db)

        url_with_query = f"{settings.FE_REDIRECT_URL}?sns_id={res_body.get('data').get('auth').get('snsId')}&temp_issued_key={res_body.get('data').get('auth').get('tempIssuedKey')}"

        return RedirectResponse(url=url_with_query, status_code=302)
    except Exception as e:
        error_message = str(e) if str(e) else "회원가입 처리 중 오류가 발생했습니다."
        error_logger.error(
            f"Kakao signup callback error: {error_message}", exc_info=True
        )
        error_url = f"{settings.FE_DOMAIN}/sign-up?error={quote(error_message)}"
        return RedirectResponse(url=error_url, status_code=302)


@router.get(
    "/signup/apple/callback",
    tags=["인증 - sns 로그인 연동"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "state 값 validation 에러(유효하지 않은 state 값)",
                            "value": {"code": "E4222"},
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
async def get_auth_signup_apple_callback(
    code: Union[str, None] = None,
    state: Union[str, None] = None,
    error: Union[str, None] = None,
    error_description: Union[str, None] = None,
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    애플 로그인 콜백(회원가입)
    애플 인증 후, callback으로 전달 받은 쿼리스트링 값으로 애플 정보 조회.
    이후 회원가입 및 로그인 처리 후 홈페이지로 redirect.
    https://appleid.apple.com/auth/authorize?client_id=prod.likenovel&redirect_uri=https://api.likenovel.net/v1/command/auth/signup/apple/callback&response_type=code&state=Y-1900-01-01-M-likenovel
    """
    try:
        res_body = await auth_service.get_auth_signup_apple_callback(
            db=db, code=code, state=state, error=error
        )

        if res_body.get("ad_info_agree_yn"):  # 미등록(회원가입 후 로그인)
            req_body = auth_schema.SignupReqBody(**res_body)
            res_body = await post_auth_signup(req_body=req_body, db=db)
        else:  # 기 등록(로그인)
            req_body = auth_schema.SigninReqBody(**res_body)
            res_body = await post_auth_signin(req_body=req_body, db=db)

        url_with_query = f"{settings.FE_REDIRECT_URL}?sns_id={res_body.get('data').get('auth').get('snsId')}&temp_issued_key={res_body.get('data').get('auth').get('tempIssuedKey')}"

        return RedirectResponse(url=url_with_query, status_code=302)
    except Exception as e:
        error_message = str(e) if str(e) else "회원가입 처리 중 오류가 발생했습니다."
        error_logger.error(
            f"Apple signup callback error: {error_message}", exc_info=True
        )
        error_url = f"{settings.FE_DOMAIN}/sign-up?error={quote(error_message)}"
        return RedirectResponse(url=error_url, status_code=302)


@router.post(
    "/email/duplicate-check",
    tags=["인증 - 기타"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
                }
            },
        },
        409: {
            "description": "이메일 중복",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "라이크노벨에 직접 가입한 이메일이 이미 존재합니다.",
                            "value": {"code": "M0000"},
                        }
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
                            "summary": "email 값 validation 에러(유효하지 않은 email 값)",
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
async def post_auth_email_duplicate_check(
    req_body: auth_schema.EmailDuplicateCheckReqBody,
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    이메일 중복 확인.
    DB에 해당 이메일이 있으면 중복 판단.
    """

    return await auth_service.post_auth_email_duplicate_check(req_body=req_body, db=db)


@router.post(
    "/signin",
    tags=["인증 - 세션"],
    responses={
        200: {
            "description": "로그인 결과",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "로그인 처리 후 토큰 발급",
                            "value": {
                                "data": {
                                    "auth": {
                                        "accessToken": "eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICJUdElPUi1YQ0ZHVDI0SXlCZnZaQzIxajJlMXcxNWh1MGhlb0IzSWtBbTd3In0.eyJleHAiOjE3MjUyNTE0MDksImlhdCI6MTcyNTI1MTEwOSwianRpIjoiZTc3NGRhMzctMDM5Ny00YzQzLTlkZmYtMzlmYTM0NzNmMTFlIiwiaXNzIjoiaHR0cHM6Ly9hdXRoLmxpa2Vub3ZlbC5kZXYvcmVhbG1zL2xpa2Vub3ZlbCIsImF1ZCI6InJlYWxtLW1hbmFnZW1lbnQiLCJzdWIiOiIxMTY1NTQ4Zi1iNTA0LTQwYmQtYTYxNC0zMDEwMWEyMjU0ZmYiLCJ0eXAiOiJCZWFyZXIiLCJhenAiOiJ0ZXN0QSIsInNpZCI6IjI5M2NkZGVmLThkNTMtNDkzNi05OWFmLTZmYWRhZWE5NGU1NyIsImFjciI6IjEiLCJhbGxvd2VkLW9yaWdpbnMiOlsiIl0sInJlc291cmNlX2FjY2VzcyI6eyJyZWFsbS1tYW5hZ2VtZW50Ijp7InJvbGVzIjpbIm1hbmFnZS11c2VycyIsInZpZXctdXNlcnMiLCJxdWVyeS1ncm91cHMiLCJxdWVyeS11c2VycyJdfX0sInNjb3BlIjoib3BlbmlkIGVtYWlsIHByb2ZpbGUiLCJlbWFpbF92ZXJpZmllZCI6ZmFsc2UsInByZWZlcnJlZF91c2VybmFtZSI6InRlc3RAdGVzdC5jb20iLCJlbWFpbCI6InRlc3RAdGVzdC5jb20ifQ.Hz7PXtO_uGrpLxfTiBKXZEPMASOIAFuN-k0cDDfCJWaYaFsHx5leUDvkKXfMwifWdHfyg-Z7zNQrPsz4UAQdzxgAs0XVxZNgeTkr8OVyzv_4A26fUWFazoUflXAIBNgDEVDjA4RUvMbzJOpXsUr4iRbn4T_WCFLEGgSzUaK2vfiDzIaqEdm9LXJ_mE-aU6W7NyQGRqxS0gSVts5h3gdtAH50Ue1qe_84Vyg4hMvjsXnjDy2hSFu6jmhDBz-FrhvoJuN_fiYHJcVGVF5gx93YJ_xuJPvghI-HeyfujqG9pOGF-wMFZx6o6cksE5cTtIP-3miyxpdqU45-Emav8YT1oA",
                                        "accessTokenExpiresIn": 300,
                                        "refreshToken": "eyJhbGciOiJIUzUxMiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICIyMDNiODBmNS0zYWRkLTQxMTctYjQ4Zi02NDU2NzkwMDYwZGIifQ.eyJleHAiOjE3MjUyNTI5MDksImlhdCI6MTcyNTI1MTEwOSwianRpIjoiZmFjMGQzZTItZGI1Yy00NmMzLTkwYjgtNjEwMDFlNWVmNGY0IiwiaXNzIjoiaHR0cHM6Ly9hdXRoLmxpa2Vub3ZlbC5kZXYvcmVhbG1zL2xpa2Vub3ZlbCIsImF1ZCI6Imh0dHBzOi8vYXV0aC5saWtlbm92ZWwuZGV2L3JlYWxtcy9saWtlbm92ZWwiLCJzdWIiOiIxMTY1NTQ4Zi1iNTA0LTQwYmQtYTYxNC0zMDEwMWEyMjU0ZmYiLCJ0eXAiOiJSZWZyZXNoIiwiYXpwIjoidGVzdEEiLCJzaWQiOiIyOTNjZGRlZi04ZDUzLTQ5MzYtOTlhZi02ZmFkYWVhOTRlNTciLCJzY29wZSI6Im9wZW5pZCBhY3Igcm9sZXMgYmFzaWMgZW1haWwgcHJvZmlsZSB3ZWItb3JpZ2lucyJ9.V9lDnNFw-zo2diQn4pruxsVMUaB78IuCeTOMxEy7poyqvUwbZQa0SWhNx4cPa_7CFHustAIGHj_SJkhf5-fvIA",
                                        "refreshTokenExpiresIn": 1800,
                                        "recentSignInType": "naver",
                                        "userId": 13,
                                        "birthDate": "2000-01-31",
                                        "gender": "M",
                                    }
                                }
                            },
                        }
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
                            "summary": "email 값 validation 에러(유효하지 않은 email 값)",
                            "value": {"code": "E4220"},
                        },
                        "retryPossible_2": {
                            "summary": "password 값 validation 에러(유효하지 않은 password 값)",
                            "value": {"code": "E4221"},
                        },
                        "retryPossible_3": {
                            "summary": "로그인 값 validation 에러(유효하지 않은 정보 값)",
                            "value": {"code": "E4223"},
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
async def post_auth_signin(
    req_body: auth_schema.SigninReqBody, db: AsyncSession = Depends(get_likenovel_db)
):
    """
    **TODO: 통합아이디 연동 모듈 구현 후 수정 및 최종 테스트 필(현재 개별아이디 개발 완료. 나머지 초안 개발 완료)**\n
    키클록 인증 후, 발급받은 토큰 및 일부 회원정보 리턴
    """

    return await auth_service.post_auth_signin(req_body=req_body, db=db)


@router.get(
    "/signin/naver/callback",
    tags=["인증 - sns 로그인 연동"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "state 값 validation 에러(유효하지 않은 state 값)",
                            "value": {"code": "E4222"},
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
async def get_auth_signin_naver_callback(
    code: Union[str, None] = None,
    state: Union[str, None] = None,
    error: Union[str, None] = None,
    error_description: Union[str, None] = None,
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    네이버 로그인 콜백(로그인)
    네이버 인증 후, callback으로 전달 받은 쿼리스트링 값으로 네이버 정보 조회.
    이후 회원가입 및 로그인 처리 후 홈페이지로 redirect.
    https://nid.naver.com/oauth2.0/authorize?client_id=0XC3m3M1KszmRR7vkIIh&redirect_uri=https%3A//api.likenovel.net/v1/command/auth/signin/naver/callback&response_type=code&state=Y-likenovel
    """
    try:
        res_body = await auth_service.get_auth_signin_naver_callback(
            db=db, code=code, state=state, error=error
        )

        if res_body.get("ad_info_agree_yn"):  # 미등록(회원가입 후 로그인)
            req_body = auth_schema.SignupReqBody(**res_body)
            res_body = await post_auth_signup(req_body=req_body, db=db)
        else:  # 기 등록(로그인)
            req_body = auth_schema.SigninReqBody(**res_body)
            res_body = await post_auth_signin(req_body=req_body, db=db)

        url_with_query = f"{settings.FE_REDIRECT_URL}?sns_id={res_body.get('data').get('auth').get('snsId')}&temp_issued_key={res_body.get('data').get('auth').get('tempIssuedKey')}"

        return RedirectResponse(url=url_with_query, status_code=302)
    except Exception as e:
        error_message = str(e) if str(e) else "로그인 처리 중 오류가 발생했습니다."
        error_logger.error(
            f"Naver signin callback error: {error_message}", exc_info=True
        )
        error_url = f"{settings.FE_DOMAIN}/login?error={quote(error_message)}"
        return RedirectResponse(url=error_url, status_code=302)


@router.get(
    "/signin/google/callback",
    tags=["인증 - sns 로그인 연동"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "state 값 validation 에러(유효하지 않은 state 값)",
                            "value": {"code": "E4222"},
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
async def get_auth_signin_google_callback(
    code: Union[str, None] = None,
    state: Union[str, None] = None,
    error: Union[str, None] = None,
    error_description: Union[str, None] = None,
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    구글 로그인 콜백(로그인)
    구글 인증 후, callback으로 전달 받은 쿼리스트링 값으로 구글 정보 조회.
    이후 회원가입 및 로그인 처리 후 홈페이지로 redirect.
    https://accounts.google.com/o/oauth2/v2/auth?client_id=1030423380095-6rvpkqp76c5fshtld4s6sebls3vf3048.apps.googleusercontent.com&redirect_uri=https://api.likenovel.net/v1/command/auth/signin/google/callback&response_type=code&state=Y-1900-01-01-M-likenovel&scope=email%20profile
    """
    try:
        res_body = await auth_service.get_auth_signin_google_callback(
            db=db, code=code, state=state, error=error
        )

        if res_body.get("ad_info_agree_yn"):  # 미등록(회원가입 후 로그인)
            req_body = auth_schema.SignupReqBody(**res_body)
            res_body = await post_auth_signup(req_body=req_body, db=db)
        else:  # 기 등록(로그인)
            req_body = auth_schema.SigninReqBody(**res_body)
            res_body = await post_auth_signin(req_body=req_body, db=db)

        url_with_query = f"{settings.FE_REDIRECT_URL}?sns_id={res_body.get('data').get('auth').get('snsId')}&temp_issued_key={res_body.get('data').get('auth').get('tempIssuedKey')}"

        return RedirectResponse(url=url_with_query, status_code=302)
    except Exception as e:
        error_message = str(e) if str(e) else "로그인 처리 중 오류가 발생했습니다."
        error_logger.error(
            f"Google signin callback error: {error_message}", exc_info=True
        )
        error_url = f"{settings.FE_DOMAIN}/login?error={quote(error_message)}"
        return RedirectResponse(url=error_url, status_code=302)


@router.get(
    "/signin/kakao/callback",
    tags=["인증 - sns 로그인 연동"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "state 값 validation 에러(유효하지 않은 state 값)",
                            "value": {"code": "E4222"},
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
async def get_auth_signin_kakao_callback(
    code: Union[str, None] = None,
    state: Union[str, None] = None,
    error: Union[str, None] = None,
    error_description: Union[str, None] = None,
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    카카오 로그인 콜백(로그인)
    카카오 인증 후, callback으로 전달 받은 쿼리스트링 값으로 카카오 정보 조회.
    이후 회원가입 및 로그인 처리 후 홈페이지로 redirect.
    https://kauth.kakao.com/oauth/authorize?client_id=8f6f1ee843ffbff8549267db3d2fb3ce&redirect_uri=https://api.likenovel.net/v1/command/auth/signin/kakao/callback&response_type=code&state=Y-likenovel
    """
    try:
        res_body = await auth_service.get_auth_signin_kakao_callback(
            db=db, code=code, state=state, error=error
        )

        if res_body.get("ad_info_agree_yn"):  # 미등록(회원가입 후 로그인)
            req_body = auth_schema.SignupReqBody(**res_body)
            res_body = await post_auth_signup(req_body=req_body, db=db)
        else:  # 기 등록(로그인)
            req_body = auth_schema.SigninReqBody(**res_body)
            res_body = await post_auth_signin(req_body=req_body, db=db)

        # 안전하게 값 추출
        data = res_body.get("data")
        if not data:
            error_logger.error(
                f"Kakao signin callback: 'data' field missing in response. res_body: {res_body}"
            )
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.INTERNAL_SERVER_ERROR,
            )

        auth = data.get("auth")
        if not auth:
            error_logger.error(
                f"Kakao signin callback: 'auth' field missing in response. data: {data}"
            )
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.INTERNAL_SERVER_ERROR,
            )

        sns_id = auth.get("snsId")
        temp_issued_key = auth.get("tempIssuedKey")

        if not sns_id or not temp_issued_key:
            error_logger.error(
                f"Kakao signin callback: Missing snsId or tempIssuedKey. auth: {auth}"
            )
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.INTERNAL_SERVER_ERROR,
            )

        url_with_query = f"{settings.FE_REDIRECT_URL}?sns_id={sns_id}&temp_issued_key={temp_issued_key}"

        return RedirectResponse(url=url_with_query, status_code=302)
    except Exception as e:
        error_message = str(e) if str(e) else "로그인 처리 중 오류가 발생했습니다."
        error_logger.error(
            f"Kakao signin callback error: {error_message}", exc_info=True
        )
        error_url = f"{settings.FE_DOMAIN}/login?error={quote(error_message)}"
        return RedirectResponse(url=error_url, status_code=302)


@router.get(
    "/signin/apple/callback",
    tags=["인증 - sns 로그인 연동"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "state 값 validation 에러(유효하지 않은 state 값)",
                            "value": {"code": "E4222"},
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
async def get_auth_signin_apple_callback(
    code: Union[str, None] = None,
    state: Union[str, None] = None,
    error: Union[str, None] = None,
    error_description: Union[str, None] = None,
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    애플 로그인 콜백(로그인)
    애플 인증 후, callback으로 전달 받은 쿼리스트링 값으로 애플 정보 조회.
    이후 회원가입 및 로그인 처리 후 홈페이지로 redirect.
    https://appleid.apple.com/auth/authorize?client_id=prod.likenovel&redirect_uri=https://api.likenovel.net/v1/command/auth/signin/apple/callback&response_type=code&state=Y-1900-01-01-M-likenovel
    """
    try:
        res_body = await auth_service.get_auth_signin_apple_callback(
            db=db, code=code, state=state, error=error
        )

        if res_body.get("ad_info_agree_yn"):  # 미등록(회원가입 후 로그인)
            req_body = auth_schema.SignupReqBody(**res_body)
            res_body = await post_auth_signup(req_body=req_body, db=db)
        else:  # 기 등록(로그인)
            req_body = auth_schema.SigninReqBody(**res_body)
            res_body = await post_auth_signin(req_body=req_body, db=db)

        url_with_query = f"{settings.FE_REDIRECT_URL}?sns_id={res_body.get('data').get('auth').get('snsId')}&temp_issued_key={res_body.get('data').get('auth').get('tempIssuedKey')}"

        return RedirectResponse(url=url_with_query, status_code=302)
    except Exception as e:
        error_message = str(e) if str(e) else "로그인 처리 중 오류가 발생했습니다."
        error_logger.error(
            f"Apple signin callback error: {error_message}", exc_info=True
        )
        error_url = f"{settings.FE_DOMAIN}/login?error={quote(error_message)}"
        return RedirectResponse(url=error_url, status_code=302)


@router.post(
    "/identity/account/search",
    tags=["인증 - 기타"],
    responses={
        200: {
            "description": "본인인증 후 본인인증 한 아이디 찾기 결과(비밀번호 찾기 시 입력한 이메일 주소 비교에도 활용)",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "본인인증 한 아이디",
                            "value": {
                                "data": {
                                    "signUpType": "naver",
                                    "masked_email": None,
                                    "email": None,
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
async def post_auth_identity_account_search(
    req_body: auth_schema.IdentityAccountSearchReqBody,
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 본인인증 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    아이디 찾기, 비밀번호 찾기
    """

    return await auth_service.post_auth_identity_account_search(
        req_body=req_body, db=db
    )


@router.post(
    "/identity/password/auth",
    tags=["인증 - 기타"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "email 값 validation 에러(유효하지 않은 email 값)",
                            "value": {"code": "E4220"},
                        },
                        "retryPossible_2": {
                            "summary": "password 값 validation 에러(유효하지 않은 password 값)",
                            "value": {"code": "E4221"},
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
async def post_identity_token(
    req_body: auth_schema.IdentityTokenForPasswordReqBody,
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    비밀번호 찾기 - 본인인증 토큰 발급
    """

    return await auth_service.post_identity_token_for_password(req_body=req_body, db=db)


@router.put(
    "/identity/password/reset",
    tags=["인증 - 기타"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "email 값 validation 에러(유효하지 않은 email 값)",
                            "value": {"code": "E4220"},
                        },
                        "retryPossible_2": {
                            "summary": "password 값 validation 에러(유효하지 않은 password 값)",
                            "value": {"code": "E4221"},
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
async def put_auth_identity_password_reset(
    req_body: auth_schema.IdentityPasswordResetReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 본인인증 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    비밀번호 재설정
    """

    return await auth_service.put_auth_identity_password_reset(
        req_body=req_body, kc_user_id=user.get("sub") if user else None, db=db
    )


@router.post(
    "/signout",
    tags=["인증 - 세션"],
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
async def post_auth_signout(
    req_body: auth_schema.SignoutReqBody, user: Dict[str, Any] = Depends(chk_cur_user)
):
    """
    **인터페이스 구현 최종 완료**\n
    refresh_token으로 개별 로그아웃 처리
    """

    return await auth_service.post_auth_signout(
        req_body=req_body, kc_user_id=user.get("sub"), kc_client=user.get("azp")
    )


@router.put(
    "/signoff",
    tags=["인증 - 기타"],
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
async def put_auth_signoff(
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **TODO: 통합아이디 연동 모듈 구현 후 수정 및 최종 테스트 필(현재 개별아이디 개발 완료. 나머지 초안 개발 완료)**\n
    회원탈퇴
    """

    return await auth_service.put_auth_signoff(
        kc_user_id=user.get("sub"), kc_client=user.get("azp"), db=db
    )


@router.put(
    "/token/reissue",
    tags=["인증 - 세션"],
    responses={
        200: {
            "description": "토큰 재발급 결과",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "refresh 토큰으로 access 토큰 재발급",
                            "value": {
                                "data": {
                                    "auth": {
                                        "accessToken": "eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICJUdElPUi1YQ0ZHVDI0SXlCZnZaQzIxajJlMXcxNWh1MGhlb0IzSWtBbTd3In0.eyJleHAiOjE3MjUyNTE0MDksImlhdCI6MTcyNTI1MTEwOSwianRpIjoiZTc3NGRhMzctMDM5Ny00YzQzLTlkZmYtMzlmYTM0NzNmMTFlIiwiaXNzIjoiaHR0cHM6Ly9hdXRoLmxpa2Vub3ZlbC5kZXYvcmVhbG1zL2xpa2Vub3ZlbCIsImF1ZCI6InJlYWxtLW1hbmFnZW1lbnQiLCJzdWIiOiIxMTY1NTQ4Zi1iNTA0LTQwYmQtYTYxNC0zMDEwMWEyMjU0ZmYiLCJ0eXAiOiJCZWFyZXIiLCJhenAiOiJ0ZXN0QSIsInNpZCI6IjI5M2NkZGVmLThkNTMtNDkzNi05OWFmLTZmYWRhZWE5NGU1NyIsImFjciI6IjEiLCJhbGxvd2VkLW9yaWdpbnMiOlsiIl0sInJlc291cmNlX2FjY2VzcyI6eyJyZWFsbS1tYW5hZ2VtZW50Ijp7InJvbGVzIjpbIm1hbmFnZS11c2VycyIsInZpZXctdXNlcnMiLCJxdWVyeS1ncm91cHMiLCJxdWVyeS11c2VycyJdfX0sInNjb3BlIjoib3BlbmlkIGVtYWlsIHByb2ZpbGUiLCJlbWFpbF92ZXJpZmllZCI6ZmFsc2UsInByZWZlcnJlZF91c2VybmFtZSI6InRlc3RAdGVzdC5jb20iLCJlbWFpbCI6InRlc3RAdGVzdC5jb20ifQ.Hz7PXtO_uGrpLxfTiBKXZEPMASOIAFuN-k0cDDfCJWaYaFsHx5leUDvkKXfMwifWdHfyg-Z7zNQrPsz4UAQdzxgAs0XVxZNgeTkr8OVyzv_4A26fUWFazoUflXAIBNgDEVDjA4RUvMbzJOpXsUr4iRbn4T_WCFLEGgSzUaK2vfiDzIaqEdm9LXJ_mE-aU6W7NyQGRqxS0gSVts5h3gdtAH50Ue1qe_84Vyg4hMvjsXnjDy2hSFu6jmhDBz-FrhvoJuN_fiYHJcVGVF5gx93YJ_xuJPvghI-HeyfujqG9pOGF-wMFZx6o6cksE5cTtIP-3miyxpdqU45-Emav8YT1oA",
                                        "accessTokenExpiresIn": 300,
                                    }
                                }
                            },
                        }
                    }
                }
            },
        },
        401: {
            "description": "로그인 페이지로 이동 필요",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "만료된 refresh 토큰 상태",
                            "value": {"code": "E4011"},
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
async def put_auth_token_reissue(req_body: auth_schema.TokenReissueReqBody):
    """
    **인터페이스 구현 최종 완료**\n
    access 토큰 만료 후 진입. access 토큰 재발급
    """

    return await auth_service.put_auth_token_reissue(req_body=req_body)


@router.put(
    "/token/relay/callback",
    tags=["인증 - sns 로그인 연동"],
    responses={
        200: {
            "description": "저장된 임시 정보 리턴 및 초기화",
            "content": {
                "application/json": {
                    "examples": {
                        "success_1": {
                            "summary": "저장된 임시 정보 리턴 및 초기화",
                            "value": {
                                "data": {
                                    "auth": {
                                        "accessToken": "eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICJUdElPUi1YQ0ZHVDI0SXlCZnZaQzIxajJlMXcxNWh1MGhlb0IzSWtBbTd3In0.eyJleHAiOjE3MjUyNTE0MDksImlhdCI6MTcyNTI1MTEwOSwianRpIjoiZTc3NGRhMzctMDM5Ny00YzQzLTlkZmYtMzlmYTM0NzNmMTFlIiwiaXNzIjoiaHR0cHM6Ly9hdXRoLmxpa2Vub3ZlbC5kZXYvcmVhbG1zL2xpa2Vub3ZlbCIsImF1ZCI6InJlYWxtLW1hbmFnZW1lbnQiLCJzdWIiOiIxMTY1NTQ4Zi1iNTA0LTQwYmQtYTYxNC0zMDEwMWEyMjU0ZmYiLCJ0eXAiOiJCZWFyZXIiLCJhenAiOiJ0ZXN0QSIsInNpZCI6IjI5M2NkZGVmLThkNTMtNDkzNi05OWFmLTZmYWRhZWE5NGU1NyIsImFjciI6IjEiLCJhbGxvd2VkLW9yaWdpbnMiOlsiIl0sInJlc291cmNlX2FjY2VzcyI6eyJyZWFsbS1tYW5hZ2VtZW50Ijp7InJvbGVzIjpbIm1hbmFnZS11c2VycyIsInZpZXctdXNlcnMiLCJxdWVyeS1ncm91cHMiLCJxdWVyeS11c2VycyJdfX0sInNjb3BlIjoib3BlbmlkIGVtYWlsIHByb2ZpbGUiLCJlbWFpbF92ZXJpZmllZCI6ZmFsc2UsInByZWZlcnJlZF91c2VybmFtZSI6InRlc3RAdGVzdC5jb20iLCJlbWFpbCI6InRlc3RAdGVzdC5jb20ifQ.Hz7PXtO_uGrpLxfTiBKXZEPMASOIAFuN-k0cDDfCJWaYaFsHx5leUDvkKXfMwifWdHfyg-Z7zNQrPsz4UAQdzxgAs0XVxZNgeTkr8OVyzv_4A26fUWFazoUflXAIBNgDEVDjA4RUvMbzJOpXsUr4iRbn4T_WCFLEGgSzUaK2vfiDzIaqEdm9LXJ_mE-aU6W7NyQGRqxS0gSVts5h3gdtAH50Ue1qe_84Vyg4hMvjsXnjDy2hSFu6jmhDBz-FrhvoJuN_fiYHJcVGVF5gx93YJ_xuJPvghI-HeyfujqG9pOGF-wMFZx6o6cksE5cTtIP-3miyxpdqU45-Emav8YT1oA",
                                        "accessTokenExpiresIn": 300,
                                        "refreshToken": "eyJhbGciOiJIUzUxMiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICIyMDNiODBmNS0zYWRkLTQxMTctYjQ4Zi02NDU2NzkwMDYwZGIifQ.eyJleHAiOjE3MjUyNTI5MDksImlhdCI6MTcyNTI1MTEwOSwianRpIjoiZmFjMGQzZTItZGI1Yy00NmMzLTkwYjgtNjEwMDFlNWVmNGY0IiwiaXNzIjoiaHR0cHM6Ly9hdXRoLmxpa2Vub3ZlbC5kZXYvcmVhbG1zL2xpa2Vub3ZlbCIsImF1ZCI6Imh0dHBzOi8vYXV0aC5saWtlbm92ZWwuZGV2L3JlYWxtcy9saWtlbm92ZWwiLCJzdWIiOiIxMTY1NTQ4Zi1iNTA0LTQwYmQtYTYxNC0zMDEwMWEyMjU0ZmYiLCJ0eXAiOiJSZWZyZXNoIiwiYXpwIjoidGVzdEEiLCJzaWQiOiIyOTNjZGRlZi04ZDUzLTQ5MzYtOTlhZi02ZmFkYWVhOTRlNTciLCJzY29wZSI6Im9wZW5pZCBhY3Igcm9sZXMgYmFzaWMgZW1haWwgcHJvZmlsZSB3ZWItb3JpZ2lucyJ9.V9lDnNFw-zo2diQn4pruxsVMUaB78IuCeTOMxEy7poyqvUwbZQa0SWhNx4cPa_7CFHustAIGHj_SJkhf5-fvIA",
                                        "refreshTokenExpiresIn": 1800,
                                        "recentSignInType": "naver",
                                        "userId": 13,
                                        "birthDate": "2000-01-31",
                                        "gender": "M",
                                    }
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
async def put_auth_token_relay_callback(
    req_body: auth_schema.TokenRelayReqBody,
    db: AsyncSession = Depends(get_likenovel_db),
):
    """
    **인터페이스 구현 최종 완료**\n
    리다이렉트 페이지 콜백
    """

    return await auth_service.put_auth_token_relay_callback(req_body=req_body, db=db)
