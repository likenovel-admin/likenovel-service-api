from fastapi import status
from httpx import AsyncClient, HTTPStatusError
from typing import Optional

import os
import uuid
import base64
import random
import jwt
import jwt.algorithms
import json
import boto3
import logging
from botocore.config import Config
from ebooklib import epub
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import settings
from app.exceptions import CustomResponseException
from app.const import ErrorMessages

logger = logging.getLogger(__name__)

"""
재사용하는 공통 서비스 함수 모음
"""


async def get_user_from_kc(
    kc_user_id: str, db: AsyncSession, addUserInfo: list[str] = []
) -> int | tuple[int, dict[str, any] | None]:
    """
    kc_user_id로 user_id 조회

    Args:
        kc_user_id: Keycloak user ID
        db: AsyncSession

    Returns:
        user_id if found, -1 if not found
    """
    query = text(f"""
        select user_id {(", " + ", ".join(addUserInfo)) if len(addUserInfo) > 0 else ""}
        from tb_user
        where kc_user_id = :kc_user_id
          and use_yn = 'Y'
    """)

    result = await db.execute(query, {"kc_user_id": kc_user_id})
    db_rst = result.mappings().all()

    if db_rst:
        if len(addUserInfo) > 0:
            return db_rst[0].get("user_id"), dict(db_rst[0])
        return db_rst[0].get("user_id")

    if len(addUserInfo) > 0:
        return -1, None
    return -1


async def kc_logout_endpoint(method: str, type: str, user_ref_token: str):
    url = f"{settings.KC_OIDC_BASE_URL}/logout"

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    data = dict()
    if method == "POST":
        if type in ["logout_normal", "reissue_normal"]:
            data = {
                "client_id": settings.KC_CLIENT_ID,
                "client_secret": settings.KC_CLIENT_SECRET,
                "refresh_token": user_ref_token,
            }
        elif type in ["logout_keep", "reissue_keep"]:
            data = {
                "client_id": settings.KC_CLIENT_KEEP_SIGNIN_ID,
                "client_secret": settings.KC_CLIENT_KEEP_SIGNIN_SECRET,
                "refresh_token": user_ref_token,
            }

    try:
        async with AsyncClient() as ac:
            if method == "POST":
                res = await ac.post(url=url, headers=headers, data=data)
                res.raise_for_status()
                return
    except HTTPStatusError as e:
        if type in ["reissue_normal", "reissue_keep"]:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.EXPIRED_REFRESH_TOKEN,
            )
        else:
            raise CustomResponseException(
                status_code=e.response.status_code,
                message=ErrorMessages.KEYCLOAK_CONNECTION_ERROR,
            )


async def kc_token_endpoint(method: str, type: str, data_dict: Optional[dict] = None):
    url = f"{settings.KC_OIDC_BASE_URL}/token"

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    data = dict()
    if method == "POST":
        if type == "client_normal":
            data = {
                "client_id": settings.KC_CLIENT_ID,
                "client_secret": settings.KC_CLIENT_SECRET,
                "grant_type": "client_credentials",
            }
        elif type == "client_keep":
            data = {
                "client_id": settings.KC_CLIENT_KEEP_SIGNIN_ID,
                "client_secret": settings.KC_CLIENT_KEEP_SIGNIN_SECRET,
                "grant_type": "client_credentials",
            }
        elif type == "user_normal_signin":
            data = {
                "client_id": settings.KC_CLIENT_ID,
                "client_secret": settings.KC_CLIENT_SECRET,
                "grant_type": "password",
                "scope": "openid",
                "username": data_dict["username"],
                "password": data_dict["password"],
            }
        elif type == "user_keep_signin":
            data = {
                "client_id": settings.KC_CLIENT_KEEP_SIGNIN_ID,
                "client_secret": settings.KC_CLIENT_KEEP_SIGNIN_SECRET,
                "grant_type": "password",
                "scope": "openid",
                "username": data_dict["username"],
                "password": data_dict["password"],
            }
        elif type == "reissue_normal":
            data = {
                "client_id": settings.KC_CLIENT_ID,
                "client_secret": settings.KC_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": data_dict["refresh_token"],
            }
        elif type == "reissue_keep":
            data = {
                "client_id": settings.KC_CLIENT_KEEP_SIGNIN_ID,
                "client_secret": settings.KC_CLIENT_KEEP_SIGNIN_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": data_dict["refresh_token"],
            }
        elif type == "user_normal_signin_code":
            data = {
                "client_id": settings.KC_CLIENT_ID,
                "client_secret": settings.KC_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "scope": "openid impersonation",
                "code": data_dict["code"],
                "redirect_uri": data_dict["redirect_uri"],
            }
        elif type == "user_keep_signin_code":
            data = {
                "client_id": settings.KC_CLIENT_KEEP_SIGNIN_ID,
                "client_secret": settings.KC_CLIENT_KEEP_SIGNIN_SECRET,
                "grant_type": "authorization_code",
                "scope": "openid impersonation",
                "code": data_dict["code"],
                "redirect_uri": data_dict["redirect_uri"],
            }

    try:
        async with AsyncClient() as ac:
            if method == "POST":
                res = await ac.post(url=url, headers=headers, data=data)
                res.raise_for_status()
                return res.json()
    except HTTPStatusError as e:
        error_message = await e.response.aread()
        logger.error(f"Keycloak Error Response: {error_message.decode()}")
        if type in ["reissue_normal", "reissue_keep"]:
            await kc_logout_endpoint(
                method="POST", type=type, user_ref_token=data_dict["refresh_token"]
            )
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.EXPIRED_REFRESH_TOKEN,
            )
        else:
            raise CustomResponseException(
                status_code=e.response.status_code,
                message=ErrorMessages.KEYCLOAK_CONNECTION_ERROR,
            )


async def kc_users_endpoint(
    method: str,
    admin_acc_token: str,
    params_dict: Optional[dict] = None,
    data_dict: Optional[dict] = None,
):
    url = f"{settings.KC_ADMIN_BASE_URL}/users"

    headers = {"Authorization": f"Bearer {admin_acc_token}"}

    data = dict()
    if method == "GET":
        pass
    elif method == "POST":
        data.update(data_dict)

    logger.info(
        f"Keycloak API request: {method} {url}, username: {data_dict.get('username') if data_dict else 'N/A'}"
    )

    try:
        async with AsyncClient() as ac:
            if method == "GET":
                if params_dict:
                    res = await ac.get(url=url, headers=headers, params=params_dict)
                else:
                    res = await ac.get(url=url, headers=headers)

                res.raise_for_status()
                logger.info(
                    f"Keycloak API success: {method} {url}, status: {res.status_code}"
                )
                return res.json()
            elif method == "POST":
                res = await ac.post(url=url, headers=headers, json=data)
                res.raise_for_status()
                new_user_id = res.headers.get("location").rstrip("/").split("/")[-1]
                logger.info(
                    f"Keycloak API success: {method} {url}, status: {res.status_code}, new_user_id: {new_user_id}"
                )
                return new_user_id  # id
    except HTTPStatusError as e:
        logger.error(
            f"Keycloak API error: {method} {url}, "
            f"status_code: {e.response.status_code}, "
            f"response_body: {e.response.text}, "
            f"username: {data_dict.get('username') if data_dict else 'N/A'}"
        )
        raise CustomResponseException(
            status_code=e.response.status_code,
            message=ErrorMessages.KEYCLOAK_OPERATION_ERROR,
        )


async def kc_users_id_endpoint(
    method: str, admin_acc_token: str, id: str, data_dict: Optional[dict] = None
):
    url = f"{settings.KC_ADMIN_BASE_URL}/users/{id}"

    headers = {"Authorization": f"Bearer {admin_acc_token}"}

    data = dict()
    if method == "GET":
        pass
    elif method == "PUT":
        data.update(data_dict)
    elif method == "DELETE":
        pass

    logger.info(f"Keycloak API request: {method} {url}, user_id: {id}")

    try:
        async with AsyncClient() as ac:
            if method == "GET":
                res = await ac.get(url=url, headers=headers)
                res.raise_for_status()
                logger.info(
                    f"Keycloak API success: {method} {url}, status: {res.status_code}"
                )
                return res.json()
            elif method == "PUT":
                res = await ac.put(url=url, headers=headers, json=data)
                res.raise_for_status()
                logger.info(
                    f"Keycloak API success: {method} {url}, status: {res.status_code}"
                )
                return
            elif method == "DELETE":
                res = await ac.delete(url=url, headers=headers)
                res.raise_for_status()
                logger.info(
                    f"Keycloak API success: {method} {url}, status: {res.status_code}"
                )
                return
    except HTTPStatusError as e:
        logger.error(
            f"Keycloak API error: {method} {url}, "
            f"status_code: {e.response.status_code}, "
            f"response_body: {e.response.text}"
        )
        raise CustomResponseException(
            status_code=e.response.status_code,
            message=ErrorMessages.KEYCLOAK_OPERATION_ERROR,
        )


async def kc_users_id_imperson_endpoint(method: str, admin_acc_token: str, id: str):
    url = f"{settings.KC_ADMIN_BASE_URL}/users/{id}/impersonation"

    headers = {"Authorization": f"Bearer {admin_acc_token}"}

    try:
        async with AsyncClient() as ac:
            if method == "POST":
                res = await ac.post(url=url, headers=headers)
                res.raise_for_status()

                return res.json().get("redirect")
    except HTTPStatusError as e:
        raise CustomResponseException(
            status_code=e.response.status_code,
            message=ErrorMessages.KEYCLOAK_OPERATION_ERROR,
        )


async def kc_users_id_imperson_auth_endpoint(method: str, type: str, redirect_uri: str):
    url = f"{settings.KC_OIDC_BASE_URL}/auth"

    params = dict()
    if type == "client_normal":
        params = {
            "response_type": "code",
            "client_id": settings.KC_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "openid",
        }
    elif type == "client_keep":
        params = {
            "response_type": "code",
            "client_id": settings.KC_CLIENT_KEEP_SIGNIN_ID,
            "redirect_uri": redirect_uri,
            "scope": "openid",
        }

    async with AsyncClient() as ac:
        if method == "GET":
            res = await ac.get(url=url, params=params, follow_redirects=False)

            redirect_url = res.headers.get("location")
            parsed_url = urlparse(redirect_url)
            query_params = parse_qs(parsed_url.query)
            return query_params.get("code", [None])[0]  # code

    return None


async def kc_userinfo_endpoint(method: str, user_acc_token: str):
    url = f"{settings.KC_OIDC_BASE_URL}/userinfo"

    headers = {"Authorization": f"Bearer {user_acc_token}"}

    try:
        async with AsyncClient() as ac:
            if method == "GET":
                res = await ac.get(url=url, headers=headers)
                res.raise_for_status()
                return res.json().get("sub")  # id
    except HTTPStatusError as e:
        if e.response.status_code == 401:
            raise CustomResponseException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                message=ErrorMessages.INVALID_LOGIN_INFO,
            )
        else:
            raise CustomResponseException(
                status_code=e.response.status_code,
                message=ErrorMessages.KEYCLOAK_CONNECTION_ERROR,
            )


async def sns_token_endpoint(
    method: str, type: str, code: str, state: str, redirect_uri: Optional[str] = None
):
    if type == "naver":
        url = f"{settings.NAVER_OAUTH2_BASE_URL}/token"
    elif type == "google":
        url = f"{settings.GOOGLE_OAUTH2_BASE_URL}/token"
    elif type == "kakao":
        url = f"{settings.KAKAO_OAUTH2_BASE_URL}/token"
    elif type == "apple":
        url = f"{settings.APPLE_OAUTH2_BASE_URL}/token"

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    data = dict()
    if method == "POST":
        if type == "naver":
            data["client_id"] = settings.NAVER_CLIENT_ID
            data["client_secret"] = settings.NAVER_CLIENT_SECRET
            data["state"] = state  # 네이버는 state 필요
        elif type == "google":
            data["client_id"] = settings.GOOGLE_CLIENT_ID
            data["client_secret"] = settings.GOOGLE_CLIENT_SECRET
            data["redirect_uri"] = redirect_uri
        elif type == "kakao":
            data["client_id"] = settings.KAKAO_CLIENT_ID
            data["client_secret"] = settings.KAKAO_CLIENT_SECRET
            data["redirect_uri"] = redirect_uri
            # 카카오는 토큰 요청 시 state 파라미터 불필요
        elif type == "apple":
            data["client_id"] = settings.APPLE_CLIENT_ID
            data["client_secret"] = settings.APPLE_CLIENT_SECRET
            data["redirect_uri"] = redirect_uri
        data["grant_type"] = "authorization_code"
        data["code"] = code

    try:
        async with AsyncClient() as ac:
            if method == "POST":
                res = await ac.post(url=url, headers=headers, data=data)
                res.raise_for_status()
                return res.json()
    except HTTPStatusError as e:
        logger.error(
            f"SNS Token Endpoint Error - Type: {type}, Status: {e.response.status_code}, "
            f"URL: {url}, Response: {e.response.text}, Data: {data}"
        )
        raise CustomResponseException(
            status_code=e.response.status_code,
            message=ErrorMessages.EXTERNAL_API_ERROR,
        )


async def sns_me_endpoint(method: str, type: str, sns_acc_token: str):
    if type == "naver":
        url = f"{settings.NAVER_API_BASE_URL}/me"
    elif type == "google":
        url = f"{settings.GOOGLE_API_BASE_URL}/userinfo"
    elif type == "kakao":
        url = f"{settings.KAKAO_API_BASE_URL}/me"

    headers = {"Authorization": f"Bearer {sns_acc_token}"}

    try:
        async with AsyncClient() as ac:
            if method == "GET":
                res = await ac.get(url=url, headers=headers)
                res.raise_for_status()
                return res.json()
    except HTTPStatusError as e:
        logger.error(
            f"SNS Me Endpoint Error - Type: {type}, Status: {e.response.status_code}, "
            f"URL: {url}, Response: {e.response.text}"
        )
        raise CustomResponseException(
            status_code=e.response.status_code,
            message=ErrorMessages.EXTERNAL_API_ERROR,
        )


async def decode_apple_token(id_token: str):
    url = settings.APPLE_KEYS_URL

    try:
        async with AsyncClient() as ac:
            res = await ac.get(url=url)
            res.raise_for_status()
            res_json = res.json()
    except HTTPStatusError as e:
        raise CustomResponseException(
            status_code=e.response.status_code,
            message=ErrorMessages.EXTERNAL_API_ERROR,
        )

    header = jwt.get_unverified_header(id_token)
    keys = res_json.get("keys")

    srch_key = ""
    for key in keys:
        if key.get("kid") == header["kid"]:
            srch_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
            break

    try:
        decoded_token = jwt.decode(
            jwt=id_token,
            key=srch_key,
            algorithms=["RS256"],
            issuer=settings.APPLE_ISSUER_BASE_URL,
            audience=settings.APPLE_CLIENT_ID,
        )

        return decoded_token
    except jwt.ExpiredSignatureError:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.INVALID_LOGIN_INFO,
        )
    except jwt.InvalidTokenError:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.INVALID_LOGIN_INFO,
        )


def make_rand_uuid():
    rand_uuid = (
        base64.urlsafe_b64encode(uuid.uuid4().bytes).rstrip(b"=").decode("utf-8")
    )  # 길이 최소화

    return rand_uuid


def make_rand_nickname():
    adjectives = [
        "행복한",
        "당당한",
        "신나는",
        "보고싶은",
        "웃긴",
        "용감한",
        "멋진",
        "귀여운",
    ]
    nouns = ["고양이", "강아지", "사자", "호랑이", "코끼리", "가자미", "거북이", "펭귄"]

    adjective = random.choice(adjectives)
    noun = random.choice(nouns)
    number = random.randint(1000, 9999)
    rand_nickname = f"{adjective}{noun}{number}"

    return rand_nickname


def make_r2_presigned_url(type: str, bucket_name: str, file_id: str):
    s3 = boto3.client(
        service_name="s3",
        endpoint_url=settings.R2_SC_DOMAIN,
        aws_access_key_id=settings.R2_CLIENT_ID,
        aws_secret_access_key=settings.R2_CLIENT_SECRET,
        region_name=settings.R2_REGION,  # Must be one of: wnam, enam, weur, eeur, apac, auto
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )

    expire = 10800

    if type == "upload":  # 클라에서 직접 업로드 필요
        method = "put_object"
    elif type == "download":
        method = "get_object"
        if bucket_name == settings.R2_SC_EPUB_BUCKET:
            # EPUB 다운로드 presigned URL 만료시간(Defensive)
            # - 기존 5초는 네트워크/디바이스 성능에 따라 요청이 지연되면 바로 만료(403)되어
            #   뷰어에서 본문(epub)이 보이지 않는 문제가 발생합니다.
            # - 운영/스테이징 정책이 다를 수 있어 환경변수로 조절합니다.
            #   (기본값은 600초로 설정해 모바일/저속 환경에서도 403(만료) 없이 안정적으로 로드되도록 합니다.)
            try:
                expire = int(os.getenv("R2_EPUB_DOWNLOAD_EXPIRE_SECONDS", "600"))
            except Exception:
                expire = 600

    pre_signed_url = s3.generate_presigned_url(
        method, Params={"Bucket": bucket_name, "Key": file_id}, ExpiresIn=expire
    )

    return pre_signed_url


async def make_epub(
    file_org_name: str, cover_image_path: str, episode_title: str, content_db: str
):
    book = epub.EpubBook()

    # metadata
    book.set_language("ko")

    # 표지 이미지
    cover_chapter = epub.EpubHtml(title="Cover", file_name="cover.xhtml")
    cover_chapter.content = (
        f'<div><img src="{cover_image_path}" alt="{episode_title}"/></div>'
    )
    book.add_item(cover_chapter)

    # 내용
    content_chapter = epub.EpubHtml(title="Content", file_name="content.xhtml")
    content_chapter.content = content_db
    book.add_item(content_chapter)

    book.toc = []
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [cover_chapter, content_chapter]

    # ROOT_PATH에 파일 생성
    file_path = Path(f"{settings.ROOT_PATH}/{file_org_name}")
    epub.write_epub(str(file_path), book, {})

    return


async def upload_epub_to_r2(url: str, file_name: str):
    headers = {"Content-Type": "application/epub+zip"}
    file_path = Path(f"{settings.ROOT_PATH}/{file_name}")

    try:
        with open(file_path, "rb") as f:
            file_content = f.read()

        async with AsyncClient() as ac:
            res = await ac.put(url=url, content=file_content, headers=headers)
            res.raise_for_status()
    except HTTPStatusError as e:
        raise CustomResponseException(
            status_code=e.response.status_code,
            message=ErrorMessages.STORAGE_SERVICE_ERROR,
        )
    finally:
        # 업로드 성공/실패와 관계없이 로컬 파일 삭제
        if file_path.exists():
            file_path.unlink()
