"""Separate, first-party CP connection; never impersonate the CMS administrator."""

import hashlib
import html
import logging
import secrets
import time

from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route

from app.rdb import likenovel_db_session
from app.services.ai import mcp_oauth as oauth, mcp_store as store
from app.services.ai.mcp_config import load as load_config
from app.services.partner.partner_product_service import get_approved_cp_company_name_by_user_id
from app.utils.auth import chk_jwt_token
from app.utils.common import check_user

logger = logging.getLogger(__name__)
GRANT_KEY = "cp:grant"
COOKIE = "ln_mcp_cp_csrf"
LOGIN_PATH = "/oauth/cp/login"
HEADERS = {**oauth.HEADERS, "Referrer-Policy": "same-origin"}


def _config(owner: str) -> dict:
    config = load_config()
    if owner != config.get("allowed_subject") or not owner:
        raise ValueError("Only the configured administrator may connect a CP account")
    company = config.get("cp_company_name")
    if not isinstance(company, str) or not company.strip():
        raise ValueError("The approved CP company must be configured")
    return config


def _flow_key(flow: str) -> str:
    return "cp:flow:" + hashlib.sha256(flow.encode()).hexdigest()


def begin_connection(owner: str) -> dict:
    config = _config(owner)
    bucket = "cp:begin-attempts:" + str(int(time.time()) // 3600)
    if store.increment_counter(bucket, owner) > 20:
        raise ValueError("Too many CP connection requests; retry later")
    flow = secrets.token_urlsafe(32)
    store.save(_flow_key(flow), owner, "pending", {
        "csrf": secrets.token_urlsafe(32), "expires_at": time.time() + 600,
        "company_name": config["cp_company_name"],
    })
    return {
        "connection_required": True,
        "login_url": config["resource"].removesuffix("/mcp") + LOGIN_PATH + "?flow=" + flow,
        "expires_in": 600,
        "instruction": "라이크노벨 로그인 화면에서 CP 계정으로 직접 연결하세요. 비밀번호를 닷에 보내지 마세요.",
    }


async def _verify_cp(access_token: str, config: dict) -> tuple[str, dict]:
    claims = await chk_jwt_token(access_token)
    subject = claims["sub"]
    if not isinstance(subject, str) or not subject:
        raise ValueError("CP subject is missing")
    async with likenovel_db_session() as db:
        actor = await check_user(subject, db, role="partner")
        # check_user(role="partner") itself also permits admins and authors.
        if actor.get("role") != "CP" or type(actor.get("user_id")) is not int:
            raise ValueError("A real CP account is required")
        company = await get_approved_cp_company_name_by_user_id(actor["user_id"], db)
    if company != config["cp_company_name"]:
        raise ValueError("This CP does not belong to the configured company")
    return subject, {"user_id": actor["user_id"], "role": "CP", "company_name": company}


def _grant_payload(kc: dict, subject: str, actor: dict) -> dict:
    if (
        not isinstance(kc.get("refresh_token"), str) or not kc["refresh_token"]
        or type(kc.get("expires_in")) is not int or kc["expires_in"] <= 30
    ):
        raise ValueError("A renewable CP identity grant is required")
    return {
        "cp_subject": subject, "actor": actor,
        "kc_access": oauth._encrypt(kc["access_token"]),
        "kc_refresh": oauth._encrypt(kc["refresh_token"]),
        "kc_expires_at": time.time() + kc["expires_in"],
    }


async def _authenticate_credentials(owner: str, username: str, password: str) -> dict:
    config = _config(owner)
    if (
        not isinstance(username, str) or not 1 <= len(username) <= 320
        or not isinstance(password, str) or not 1 <= len(password) <= 4096
    ):
        raise ValueError("CP credentials are missing or too long")
    kc = await oauth._keycloak({
        "grant_type": "password", "username": username, "password": password,
        "scope": "openid offline_access",
    })
    subject, actor = await _verify_cp(kc["access_token"], config)
    if kc.get("refresh_expires_in") != 0:
        raise ValueError("An offline CP grant is required")
    return _grant_payload(kc, subject, actor)


async def connect_credentials(owner: str, username: str, password: str) -> dict:
    """Trusted server setup only. Do not expose credential arguments as an MCP tool."""
    payload = await _authenticate_credentials(owner, username, password)
    store.save(GRANT_KEY, owner, "active", payload)
    return payload["actor"]


async def get_actor(owner: str) -> dict:
    """Return only a freshly verified CP actor, never password or identity tokens."""
    config = _config(owner)
    record = store.get(GRANT_KEY, owner)
    if not record or record["status"] != "active":
        raise ValueError("Connect the LikeNovel CP account first")
    if record["kc_expires_at"] <= time.time() + 30:
        # A durable state transition prevents two API workers rotating this grant.
        if not store.consume(GRANT_KEY, owner, "active"):
            raise ValueError("CP refresh is in progress; retry the read")
        try:
            kc = await oauth._keycloak({
                "grant_type": "refresh_token",
                "refresh_token": oauth._decrypt(record["kc_refresh"]),
            })
            subject, actor = await _verify_cp(kc["access_token"], config)
            if subject != record["cp_subject"]:
                raise ValueError("CP identity changed during refresh")
            payload = _grant_payload(kc, subject, actor)
            store.save(GRANT_KEY, owner, "active", payload)
            return actor
        except Exception as exc:
            store.save(GRANT_KEY, owner, "revoked", {})
            logger.warning("MCP CP refresh rejected: %s", type(exc).__name__)
            raise ValueError("CP authorization must be renewed") from None
    subject, actor = await _verify_cp(oauth._decrypt(record["kc_access"]), config)
    if subject != record["cp_subject"]:
        raise ValueError("CP identity changed")
    return actor


async def connection_status(owner: str) -> dict:
    config = _config(owner)
    record = store.get(GRANT_KEY, owner)
    if not record or record["status"] != "active":
        return {"connected": False, "company_name": config["cp_company_name"],
                "authorization_required": True}
    try:
        actor = await get_actor(owner)
    except Exception as exc:
        logger.warning("MCP CP connection check rejected: %s", type(exc).__name__)
        return {"connected": False, "company_name": config["cp_company_name"],
                "authorization_required": True}
    return {"connected": True, **actor, "authorization_required": False}


def _pending(request):
    config = load_config()
    owner = config.get("allowed_subject", "")
    _config(owner)
    flow = request.query_params.get("flow", "")
    return config, owner, flow, store.get(_flow_key(flow), owner)


async def login_page(request):
    try:
        config, owner, flow, record = _pending(request)
    except ValueError:
        return HTMLResponse("CP 연결 설정이 준비되지 않았습니다.", status_code=400, headers=HEADERS)
    if not oauth._valid(record, "pending") or record["company_name"] != config["cp_company_name"]:
        return HTMLResponse("연결 요청이 만료되었습니다. 닷에서 다시 시작하세요.", status_code=400, headers=HEADERS)
    body = f"""<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>라이크노벨 CP 계정 연결</title>
<style>body{{font-family:system-ui;max-width:540px;margin:60px auto;padding:20px}}
label,input,button{{display:block;width:100%;box-sizing:border-box;margin:14px 0;padding:12px}}</style>
<h1>라이크노벨 CP 계정 연결</h1>
<p>승인된 CP 회사: {html.escape(config['cp_company_name'])}</p>
<p>파트너 사이트에 사용하는 CP 계정으로 직접 로그인하세요. 관리자 계정은 연결할 수 없습니다.</p>
<p>비밀번호는 닷에 전달하지 않습니다. 연결 후에도 프로모션 실행에는 별도 지시나 승인이 필요합니다.</p>
<form method="post" action="{LOGIN_PATH}">
<input type="hidden" name="flow" value="{html.escape(flow, quote=True)}">
<input type="hidden" name="csrf" value="{html.escape(record['csrf'], quote=True)}">
<label for="username">CP 계정 이메일</label><input id="username" name="username" type="email" required autocomplete="username">
<label for="password">CP 계정 비밀번호</label><input id="password" name="password" type="password" required autocomplete="current-password">
<button type="submit">CP 계정 연결</button></form></html>"""
    response = HTMLResponse(body, headers=HEADERS)
    response.set_cookie(COOKIE, record["csrf"], max_age=600, secure=True,
                        httponly=True, samesite="lax", path="/oauth/cp")
    return response


async def login_submit(request):
    config = load_config()
    owner = config.get("allowed_subject", "")
    try:
        _config(owner)
    except ValueError:
        return HTMLResponse("CP 연결 설정이 준비되지 않았습니다.", status_code=400, headers=HEADERS)
    if request.headers.get("origin") != config["resource"].removesuffix("/mcp"):
        return HTMLResponse("허용되지 않은 로그인 요청입니다.", status_code=403, headers=HEADERS)
    try:
        form = await oauth._read_form(request)
    except (UnicodeError, ValueError):
        return HTMLResponse("올바르지 않은 로그인 요청입니다.", status_code=400, headers=HEADERS)
    flow, csrf = form.get("flow", ""), form.get("csrf", "")
    record = store.get(_flow_key(flow), owner)
    if (
        not oauth._valid(record, "pending")
        or record["company_name"] != config["cp_company_name"]
        or not secrets.compare_digest(csrf, record["csrf"])
        or not secrets.compare_digest(request.cookies.get(COOKIE, ""), csrf)
    ):
        return HTMLResponse("로그인 요청이 만료되었습니다.", status_code=403, headers=HEADERS)
    bucket = "cp:login-attempts:" + str(int(time.time()) // 3600)
    if store.increment_counter(bucket, owner) > 20:
        return HTMLResponse("로그인 시도가 많습니다. 잠시 뒤 다시 연결하세요.", status_code=429, headers=HEADERS)
    try:
        payload = await _authenticate_credentials(
            owner, form.get("username", ""), form.get("password", ""),
        )
        if not store.consume(_flow_key(flow), owner, "pending"):
            raise ValueError("CP login flow was already consumed")
        store.save(GRANT_KEY, owner, "active", payload)
        response = RedirectResponse("/oauth/cp/connected", status_code=303, headers=HEADERS)
        response.delete_cookie(COOKIE, path="/oauth/cp", secure=True, httponly=True, samesite="lax")
        return response
    except Exception as exc:
        logger.warning("MCP CP login rejected: %s", type(exc).__name__)
        return HTMLResponse("승인된 라이크노벨 CP 계정 확인에 실패했습니다. 닷에서 다시 연결하세요.",
                            status_code=401, headers=HEADERS)


async def connection_result(request):
    return HTMLResponse("CP 계정 인증을 저장했습니다. 닷에서 연결 상태를 확인하세요.",
                        headers=HEADERS)


CP_AUTH_ROUTES = [
    Route(LOGIN_PATH, login_page, methods=["GET"]),
    Route(LOGIN_PATH, login_submit, methods=["POST"]),
    Route("/oauth/cp/connected", connection_result, methods=["GET"]),
]
