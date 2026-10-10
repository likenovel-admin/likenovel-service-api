"""OAuth code/PKCE facade authenticated by the existing CMS administrator login.

ChatGPT receives only opaque, resource-bound MCP tokens. The existing Keycloak
offline grant is encrypted at rest and never returned to an MCP tool or client.
"""

import hashlib
import html
import logging
import secrets
import time
from urllib.parse import urlencode, parse_qs

from cryptography.fernet import Fernet
from httpx import AsyncClient
from mcp.server.auth.provider import (
    AccessToken, AuthorizationCode, AuthorizationParams, AuthorizeError,
    OAuthClientInformationFull, OAuthToken, RefreshToken, TokenError,
)
from starlette.responses import HTMLResponse, RedirectResponse, JSONResponse

from app.const import settings
from app.rdb import likenovel_db_session
from app.utils.auth import chk_jwt_token
from app.utils.common import check_user
from app.services.ai import mcp_store as store, mcp_policy as policy
from app.services.ai.mcp_config import load as load_config

logger = logging.getLogger(__name__)
SCOPES = [policy.READ_SCOPE, policy.WRITE_SCOPE, "offline_access"]


def _key(kind: str, value: str) -> str:
    return "oauth:" + kind + ":" + hashlib.sha256(value.encode()).hexdigest()


def _owner() -> str:
    return load_config()["allowed_subject"]


def _cipher() -> Fernet:
    return Fernet(load_config()["token_encryption_key"].encode())


def _encrypt(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _cipher().decrypt(value.encode()).decode()


def _valid(record: dict | None, status: str) -> bool:
    return bool(record and record["status"] == status and record["expires_at"] > time.time())


class AdminAccessToken(AccessToken):
    subject: str
    admin_user_id: int
    grant_id: str


class AdminRefreshToken(RefreshToken):
    grant_id: str


class AdminAuthorizationCode(AuthorizationCode):
    grant_id: str


async def _verify_admin(access_token: str) -> tuple[str, int]:
    claims = await chk_jwt_token(access_token)
    if claims["sub"] != _owner():
        raise ValueError("Only the configured CMS administrator may connect")
    async with likenovel_db_session() as db:
        user = await check_user(claims["sub"], db, role="admin")
    return claims["sub"], user["user_id"]


async def _keycloak(data: dict) -> dict:
    # Use the established keep-sign-in CMS client without expanding realm rights.
    client_id = settings.KC_CLIENT_KEEP_SIGNIN_ID
    secret = settings.KC_CLIENT_KEEP_SIGNIN_SECRET
    async with AsyncClient(timeout=20) as client:
        result = await client.post(
            settings.KC_OIDC_BASE_URL + "/token",
            data={**data, "client_id": client_id},
            auth=(client_id, secret),
        )
        result.raise_for_status()
        return result.json()


class AdminOAuthProvider:
    async def get_client(self, client_id: str):
        if client_id != policy.CLIENT_ID:
            return None
        config = load_config()
        return OAuthClientInformationFull(
            client_id=policy.CLIENT_ID,
            client_name="ChatGPT LikeNovel slot operator",
            redirect_uris=[config["oauth_callback"]],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"], scope=" ".join(SCOPES),
        )

    async def register_client(self, client_info):
        raise NotImplementedError("Dynamic registration is disabled")

    async def authorize(self, client, params: AuthorizationParams) -> str:
        config = load_config()
        if params.resource not in (None, config["resource"]):
            raise AuthorizeError("invalid_request", "Wrong MCP resource")
        if str(params.redirect_uri) != config["oauth_callback"]:
            raise AuthorizeError("invalid_request", "Unregistered callback")
        scopes = params.scopes or SCOPES
        if set(scopes) - set(SCOPES) or not {policy.READ_SCOPE, policy.WRITE_SCOPE}.issubset(scopes):
            raise AuthorizeError("invalid_scope", "Both narrow slot scopes are required")
        if len(params.code_challenge) != 43:
            raise AuthorizeError("invalid_request", "S256 PKCE is required")
        bucket = "oauth:authorize-attempts:" + str(int(time.time()) // 3600)
        if store.increment_counter(bucket, _owner()) > 200:
            raise AuthorizeError("temporarily_unavailable", "Please retry later")
        flow = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        store.save(_key("flow", flow), _owner(), "pending", {
            "params": params.model_dump(mode="json"),
            "csrf": csrf, "expires_at": time.time() + 600,
        })
        return config["resource"].removesuffix("/mcp") + "/oauth/login?flow=" + flow

    async def load_authorization_code(self, client, authorization_code):
        record = store.get(_key("code", authorization_code), _owner())
        if not _valid(record, "ready") or record["client_id"] != client.client_id:
            return None
        return AdminAuthorizationCode(
            code=authorization_code,
            **{key: record[key] for key in (
                "scopes", "expires_at", "client_id", "code_challenge", "redirect_uri",
                "redirect_uri_provided_explicitly", "resource", "subject", "grant_id",
            )},
        )

    def _issue(self, grant_id: str, scopes: list[str]) -> OAuthToken:
        record = store.get(grant_id, _owner())
        if record is None or record["status"] != "active":
            raise TokenError("invalid_grant", "Grant is inactive")
        access, refresh = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
        expiry = min(int(time.time()) + 300, int(record["kc_expires_at"]) - 15)
        if expiry <= time.time():
            raise TokenError("invalid_grant", "Identity grant expired")
        common = {
            "grant_id": grant_id, "client_id": policy.CLIENT_ID,
            "scopes": scopes, "resource": load_config()["resource"],
            "subject": _owner(), "generation": record["generation"],
        }
        store.save(_key("access", access), _owner(), "active", {**common, "expires_at": expiry})
        store.save(_key("refresh", refresh), _owner(), "active", {
            **common, "expires_at": int(time.time()) + 30 * 24 * 3600,
        })
        return OAuthToken(
            access_token=access, refresh_token=refresh,
            expires_in=max(1, expiry - int(time.time())), scope=" ".join(scopes),
        )

    async def exchange_authorization_code(self, client, authorization_code):
        if not store.consume(_key("code", authorization_code.code), _owner(), "ready"):
            raise TokenError("invalid_grant", "Authorization code was already used")
        return self._issue(authorization_code.grant_id, authorization_code.scopes)

    async def load_refresh_token(self, client, refresh_token):
        record = store.get(_key("refresh", refresh_token), _owner())
        if not _valid(record, "active") or record["client_id"] != client.client_id:
            return None
        grant = store.get(record["grant_id"], _owner())
        if not grant or grant["status"] != "active" or grant["generation"] != record["generation"]:
            return None
        return AdminRefreshToken(
            token=refresh_token,
            **{key: record[key] for key in (
                "client_id", "scopes", "expires_at", "resource", "subject", "grant_id",
            )},
        )

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        record = store.get(refresh_token.grant_id, _owner())
        if not record or record["status"] != "active":
            raise TokenError("invalid_grant", "Grant is inactive")
        if not store.consume(_key("refresh", refresh_token.token), _owner(), "active"):
            raise TokenError("invalid_grant", "Refresh token was already used")
        try:
            kc = await _keycloak({
                "grant_type": "refresh_token",
                "refresh_token": _decrypt(record["kc_refresh"]),
            })
            subject, user_id = await _verify_admin(kc["access_token"])
            store.save(refresh_token.grant_id, subject, "active", {
                "kc_access": _encrypt(kc["access_token"]),
                "kc_refresh": _encrypt(kc["refresh_token"]),
                "kc_expires_at": time.time() + kc["expires_in"],
                "generation": record["generation"] + 1,
                "admin_user_id": user_id,
            })
            return self._issue(refresh_token.grant_id, scopes)
        except Exception as exc:
            logger.warning("MCP OAuth refresh failed: %s", type(exc).__name__)
            raise TokenError("invalid_grant", "Administrator authorization must be renewed") from None

    async def load_access_token(self, token):
        record = store.get(_key("access", token), _owner())
        if not _valid(record, "active") or record["resource"] != load_config()["resource"] \
                or record["subject"] != _owner() or record["client_id"] != policy.CLIENT_ID:
            return None
        grant = store.get(record["grant_id"], _owner())
        if not grant or grant["status"] != "active" or grant["generation"] != record["generation"]:
            return None
        try:
            subject, user_id = await _verify_admin(_decrypt(grant["kc_access"]))
            return AdminAccessToken(
                token=token, client_id=policy.CLIENT_ID, scopes=record["scopes"],
                expires_at=record["expires_at"], resource=record["resource"],
                subject=subject, admin_user_id=user_id, grant_id=record["grant_id"],
            )
        except Exception as exc:
            logger.warning("MCP OAuth identity check rejected: %s", type(exc).__name__)
            return None

    async def revoke_token(self, token):
        grant = store.get(token.grant_id, _owner())
        if not grant or grant["status"] != "active":
            return
        # Deny MCP access and erase stored identity tokens before network cleanup.
        store.save(token.grant_id, _owner(), "revoked", {"generation": grant["generation"]})
        try:
            client_id = settings.KC_CLIENT_KEEP_SIGNIN_ID
            async with AsyncClient(timeout=10) as client:
                result = await client.post(
                    settings.KC_OIDC_BASE_URL + "/logout",
                    data={"client_id": client_id, "refresh_token": _decrypt(grant["kc_refresh"])},
                    auth=(client_id, settings.KC_CLIENT_KEEP_SIGNIN_SECRET),
                )
                result.raise_for_status()
        except Exception as exc:
            logger.warning("MCP revoked; upstream session cleanup failed: %s", type(exc).__name__)


HEADERS = {
    "Cache-Control": "no-store", "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
}


async def _read_form(request) -> dict:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 8192:
            raise ValueError("Form exceeds 8 KiB")
    fields = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=8)
    if any(len(values) != 1 for values in fields.values()):
        raise ValueError("Duplicate form field")
    return {key: values[0] for key, values in fields.items()}


async def revoke_public(request):
    # SDK's legacy revocation form requires client_secret even for public
    # clients. Enforce the public-client contract without requiring a fake secret.
    headers = {"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"}
    if request.method == "OPTIONS":
        return JSONResponse({}, headers={**headers, "Access-Control-Allow-Methods": "POST, OPTIONS"})
    try:
        form = await _read_form(request)
    except (UnicodeError, ValueError):
        return JSONResponse({"error": "invalid_request"}, status_code=400, headers=headers)
    if form.get("client_id") != policy.CLIENT_ID:
        return JSONResponse({"error": "invalid_client"}, status_code=400, headers=headers)
    raw_token = form.get("token", "")
    record = store.get(_key("refresh", raw_token), _owner()) or store.get(_key("access", raw_token), _owner())
    if record and record["client_id"] == policy.CLIENT_ID and record["resource"] == load_config()["resource"]:
        grant = store.get(record["grant_id"], _owner())
        if grant and grant["status"] == "active" and grant["generation"] == record["generation"]:
            await AdminOAuthProvider().revoke_token(AdminRefreshToken(
                token=raw_token, client_id=policy.CLIENT_ID, scopes=record["scopes"],
                grant_id=record["grant_id"], resource=record["resource"], subject=_owner(),
            ))
    return JSONResponse({}, headers=headers)


async def login_page(request):
    flow = request.query_params.get("flow", "")
    record = store.get(_key("flow", flow), _owner())
    if not _valid(record, "pending"):
        return HTMLResponse("연결 요청이 만료되었습니다. 닷의 연결 화면에서 다시 시작하세요.", status_code=400, headers=HEADERS)
    body = f"""<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>라이크노벨 닷 연결</title>
<style>body{{font-family:system-ui;max-width:540px;margin:60px auto;padding:20px}}
label,input,button{{display:block;width:100%;box-sizing:border-box;margin:14px 0;padding:12px}}
button{{background:#182638;color:white;border:0;border-radius:8px}}</style>
<h1>라이크노벨 구좌 운영 연결</h1>
<p>기존 CMS 관리자 계정으로 로그인하면 닷에 다음 운영 권한을 연결합니다.</p>
<ul><li>일반 구좌 5개: 매일 오전 10시 검토 후 필요한 변경</li>
<li>유료 단일구좌 3개와 문구: 월·목 오전 10시 5분 교체</li>
<li>한국시간 기준, 매번 승인 없이 운영하며 결과는 닷으로 보고</li></ul>
<p>CMS 비밀번호는 라이크노벨에서 확인하며 닷에 전달하지 않습니다.</p>
<form method="post" action="/oauth/login">
<input type="hidden" name="flow" value="{html.escape(flow, quote=True)}">
<input type="hidden" name="csrf" value="{html.escape(record['csrf'], quote=True)}">
<label for="username">CMS 관리자 이메일</label><input id="username" name="username" type="email" required autocomplete="username">
<label for="password">CMS 관리자 비밀번호</label><input id="password" name="password" type="password" required autocomplete="current-password">
<button type="submit">로그인하고 닷에 구좌 운영 연결</button></form></html>"""
    response = HTMLResponse(body, headers=HEADERS)
    response.set_cookie("ln_mcp_csrf", record["csrf"], max_age=600, secure=True,
                        httponly=True, samesite="lax", path="/oauth")
    return response


async def login_submit(request):
    config = load_config()
    origin = config["resource"].removesuffix("/mcp")
    if request.headers.get("origin") != origin:
        return HTMLResponse("허용되지 않은 로그인 요청입니다.", status_code=403, headers=HEADERS)
    try:
        form = await _read_form(request)
    except (UnicodeError, ValueError):
        return HTMLResponse("올바르지 않은 로그인 요청입니다.", status_code=400, headers=HEADERS)
    flow = str(form.get("flow", ""))
    record = store.get(_key("flow", flow), _owner())
    csrf = str(form.get("csrf", ""))
    if not _valid(record, "pending") or not secrets.compare_digest(csrf, record["csrf"]) \
            or not secrets.compare_digest(request.cookies.get("ln_mcp_csrf", ""), csrf):
        return HTMLResponse("로그인 요청이 만료되었습니다.", status_code=403, headers=HEADERS)
    # One configured administrator: cap failed/attempted logins across all flows.
    bucket = "oauth:login-attempts:" + str(int(time.time()) // 3600)
    if store.increment_counter(bucket, _owner()) > 20:
        return HTMLResponse("로그인 시도가 많습니다. 잠시 뒤 다시 연결하세요.", status_code=429, headers=HEADERS)
    try:
        kc = await _keycloak({
            "grant_type": "password", "username": str(form.get("username", "")),
            "password": str(form.get("password", "")), "scope": "openid offline_access",
        })
        subject, user_id = await _verify_admin(kc["access_token"])
        if not kc.get("refresh_token") or kc.get("refresh_expires_in") != 0:
            raise ValueError("An offline identity grant is required for cloud execution")
        if not store.consume(_key("flow", flow), subject, "pending"):
            raise ValueError("Login flow already consumed")
        grant_id = "oauth:grant:" + secrets.token_urlsafe(32)
        store.save(grant_id, subject, "active", {
            "kc_access": _encrypt(kc["access_token"]),
            "kc_refresh": _encrypt(kc["refresh_token"]),
            "kc_expires_at": time.time() + kc["expires_in"],
            "generation": 1, "admin_user_id": user_id,
        })
        code = secrets.token_urlsafe(32)
        params = record["params"]
        store.save(_key("code", code), subject, "ready", {
            "scopes": params["scopes"] or SCOPES, "expires_at": time.time() + 60,
            "client_id": policy.CLIENT_ID, "code_challenge": params["code_challenge"],
            "redirect_uri": params["redirect_uri"],
            "redirect_uri_provided_explicitly": params["redirect_uri_provided_explicitly"],
            "resource": config["resource"], "subject": subject, "grant_id": grant_id,
        })
        query = {"code": code}
        if params["state"] is not None:
            query["state"] = params["state"]
        response = RedirectResponse(config["oauth_callback"] + "?" + urlencode(query), status_code=303, headers=HEADERS)
        response.delete_cookie("ln_mcp_csrf", path="/oauth", secure=True, httponly=True, samesite="lax")
        return response
    except Exception as exc:
        logger.warning("MCP OAuth login rejected: %s", type(exc).__name__)
        return HTMLResponse(
            "관리자 계정 확인에 실패했습니다. 기존 CMS 계정으로 연결을 다시 시작하세요.",
            status_code=401, headers=HEADERS,
        )
