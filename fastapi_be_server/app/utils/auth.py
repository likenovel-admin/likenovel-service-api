from fastapi import Request, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from httpx import AsyncClient, HTTPStatusError
from typing import Annotated

import asyncio
import json
import jwt
from jwt.algorithms import RSAAlgorithm
import logging
from logging.handlers import RotatingFileHandler
import bcrypt
from datetime import datetime, timedelta
import time

from app.const import settings, ErrorMessages
from app.exceptions import CustomResponseException
from app.utils.time import datatime_formatted_by_timezone

"""
인증/인가 관련 유틸 함수 모음
"""

# Authorization 헤더(swagger ui 수기 검증 가능)
auth_req_header = HTTPBearer(auto_error=False)

_KC_JWKS_CACHE = None
_KC_JWKS_CACHE_AT = 0.0
_KC_JWKS_CACHE_TTL_SECONDS = 60 * 5
_KC_JWKS_LOCK = asyncio.Lock()


async def _get_kc_jwks():
    """
    Keycloak JWKS를 가져옵니다(Defensive)
    - Keycloak은 키를 롤링할 수 있으므로(서명 키 교체), 하드코딩된 public key만으로는
      새로 발급된 토큰 검증이 실패(InvalidSignatureError)할 수 있습니다.
    - /certs(JWKS)에서 kid에 맞는 공개키를 조회하도록 하여 키 롤링에 안전하게 대응합니다.
    - 네트워크/Keycloak 장애로 /certs 조회가 실패할 수 있어, TTL 캐시로 요청을 줄입니다.
    """
    global _KC_JWKS_CACHE, _KC_JWKS_CACHE_AT

    now = time.time()
    if _KC_JWKS_CACHE and (now - _KC_JWKS_CACHE_AT) < _KC_JWKS_CACHE_TTL_SECONDS:
        return _KC_JWKS_CACHE

    async with _KC_JWKS_LOCK:
        now = time.time()
        if _KC_JWKS_CACHE and (now - _KC_JWKS_CACHE_AT) < _KC_JWKS_CACHE_TTL_SECONDS:
            return _KC_JWKS_CACHE

        url = f"{settings.KC_OIDC_BASE_URL}/certs"
        try:
            async with AsyncClient() as ac:
                res = await ac.get(url=url, timeout=5.0)
                res.raise_for_status()
                _KC_JWKS_CACHE = res.json()
                _KC_JWKS_CACHE_AT = time.time()
                return _KC_JWKS_CACHE
        except Exception as e:
            logging.getLogger(__name__).warning(
                f"[auth] Failed to fetch Keycloak JWKS from {url}: {e}"
            )
            # 캐시가 있으면 마지막 캐시를 반환(Defensive)
            if _KC_JWKS_CACHE:
                return _KC_JWKS_CACHE
            raise


async def get_kc_signing_key(token: str):
    """
    토큰의 kid 헤더에 맞는 Keycloak 공개키를 반환합니다.
    - 성공 시 RSA public key 객체 반환
    - 실패 시 None 반환(호출부에서 settings.KC_PUBLIC_KEY로 fallback 가능)
    """
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            return None

        jwks = await _get_kc_jwks()
        for jwk in jwks.get("keys", []):
            if jwk.get("kid") == kid:
                return RSAAlgorithm.from_jwk(json.dumps(jwk))
    except Exception as e:
        logging.getLogger(__name__).warning(
            f"[auth] Failed to resolve signing key from JWKS: {e}"
        )
        return None

    return None


async def chk_revoked_token(token: str, decoded_token: dict):
    url = f"{settings.KC_OIDC_BASE_URL}/token/introspect"

    data = {"token": token}

    client = decoded_token.get("azp")

    if client == settings.KC_CLIENT_ID:
        auth = (settings.KC_CLIENT_ID, settings.KC_CLIENT_SECRET)
    elif client == settings.KC_CLIENT_KEEP_SIGNIN_ID:
        auth = (
            settings.KC_CLIENT_KEEP_SIGNIN_ID,
            settings.KC_CLIENT_KEEP_SIGNIN_SECRET,
        )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    try:
        async with AsyncClient() as ac:
            res = await ac.post(url=url, data=data, auth=auth)
            res.raise_for_status()

            res_json = res.json()

            logging.getLogger("log_test").info({"res_json": res_json})

            if not res_json.get("active", False):
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
                )

            return res_json
    except HTTPStatusError:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )


async def chk_jwt_token(token: str):
    try:
        if not token or len(token.split(".")) != 3:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
            )

        signing_key = await get_kc_signing_key(token)
        decoded_token = jwt.decode(
            jwt=token,
            # JWKS(kid) 기반 공개키를 우선 사용하고, 실패 시 기존 하드코딩 키로 fallback 합니다.
            key=signing_key or settings.KC_PUBLIC_KEY,
            algorithms=settings.KC_PK_ALGORITHMS,
            issuer=settings.KC_ISSUER_BASE_URL,
            audience=settings.KC_AUDIENCE,
        )

        await chk_revoked_token(token, decoded_token)

        return decoded_token
    except jwt.ExpiredSignatureError:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )
    except jwt.InvalidTokenError:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )


# access_token으로 인가된 사용자 체크. DI로 활용
async def chk_cur_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(auth_req_header)],
):
    if credentials is None:
        decoded_token = dict()
    else:
        try:
            decoded_token = await chk_jwt_token(credentials.credentials)
        except CustomResponseException:
            decoded_token = dict()

    return decoded_token


def hash_password(plain_password: str) -> str:
    """
    bcrypt를 사용하여 비밀번호를 해시합니다.
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    평문 비밀번호와 해시된 비밀번호를 비교합니다.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def create_access_token(data: dict, expires_delta: int = 3600) -> str:
    """
    admin 정보를 받아 JWT access token을 발급합니다.
    - data: 토큰에 담을 정보
    - expires_delta: 만료 시간(초)
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(seconds=expires_delta)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.KC_PUBLIC_KEY,
        algorithm=settings.KC_PK_ALGORITHMS[0],
    )
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """
    JWT access token을 admin 정보(dict)로 변환합니다.
    만료 시간이 지났으면 401 Unauthorized 에러를 발생시킵니다.
    """
    try:
        payload = jwt.decode(
            token,
            settings.KC_PUBLIC_KEY,
            algorithms=settings.KC_PK_ALGORITHMS,
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )
    except jwt.InvalidTokenError:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.INVALID_TOKEN,
        )


def analysis_logger(request: Request):
    try:
        logger = logging.getLogger(settings.LOGGER_NAME)
        logger.setLevel(logging.INFO)

        # 핸들러가 없을 때만 추가 (중복 방지)
        # RotatingFileHandler: 50MB, 최대 3개 백업 파일
        if not logger.handlers:
            handler = RotatingFileHandler(
                "test_analysis.log",
                maxBytes=50*1024*1024,  # 50MB
                backupCount=3
            )
            logger.addHandler(handler)

        """ 서비스 로깅 메세지 설정 """
        logging_message = dict()
        logging_message["timestamp"] = datatime_formatted_by_timezone("y")
        logging_message["trace_id"] = request.state.trace_id
        logging_message["span_id"] = request.state.span_id
        logging_message["client_ip"] = request.scope.get("client")[0]
        logging_message["client_host"] = request.client.host
        logging_message["client_port"] = str(request.client.port)
        logging_message["device"] = request.headers.get("user-agent")
        logging_message["request_path"] = request.scope.get("path")
        logging_message["request_method"] = str(request.method).lower()
        logging_message["route_name"] = request.scope.get("route").name
        logging_message["referer"] = str(request.headers.get("referer")).lower()
        logging_message["analysis_params"] = request.state.analysis_params

        logger.info(logging_message)
    except Exception as e:
        logger.info(e)
        pass

    return
