"""Prepared member-mail capability; not registered as an MCP tool yet.

Authorization records must be created by a trusted user-command ingress, never
from model-provided tool arguments. Gmail configuration is deliberately absent
until the existing Workspace DWD credential is securely provisioned on WAS.
"""

import base64
import hashlib
import json
import re
import secrets
import stat
import time
from datetime import datetime
from email import policy as email_policy
from email.message import EmailMessage
from email.utils import getaddresses
from pathlib import Path

import jwt
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import bindparam, text

from app.const import settings
from app.services.ai import mcp_store as store
from app.services.ai.mcp_config import load as load_config

READ_MEMBERS = "likenovel.mcp.members.read"
WRITE_MAIL = "likenovel.mcp.mail.write"
SENDER = "admin@likenovel.net"
MAX_MEMBERS = 500
SNAPSHOT_SECONDS = 900
GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
)
_EMAIL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$")
_ID = re.compile(r"^mail:(preview|campaign):[a-f0-9]{32}$")


def _digest(value: dict | list) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _cipher() -> Fernet:
    return Fernet(load_config()["token_encryption_key"].encode())


def _seal(value: dict) -> str:
    return _cipher().encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()


def _open(record: dict) -> dict:
    return json.loads(_cipher().decrypt(record["sealed"].encode()))


def _record(owner: str, record_id: str, kind: str) -> dict:
    if not isinstance(record_id, str) or not _ID.fullmatch(record_id) \
            or not record_id.startswith(f"mail:{kind}:"):
        raise ValueError("Invalid member-mail receipt ID")
    record = store.get(record_id, owner)
    if record is None:
        raise ValueError("Member-mail receipt not found for this identity")
    return record


def _filters(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) - {"purpose", "user_ids", "joined_from", "joined_before"}:
        raise ValueError("Unknown member filter")
    purpose = value.get("purpose", "marketing")
    if purpose not in {"marketing", "service_notice"}:
        raise ValueError("Purpose must be marketing or service_notice")
    result = {"purpose": purpose}
    if "user_ids" in value:
        ids = value["user_ids"]
        if not isinstance(ids, list) or not ids or len(ids) > MAX_MEMBERS \
                or any(type(item) is not int or item <= 0 for item in ids) \
                or len(set(ids)) != len(ids):
            raise ValueError("user_ids must be distinct positive member IDs")
        result["user_ids"] = sorted(ids)
    for key in ("joined_from", "joined_before"):
        if key in value:
            raw = value[key]
            if not isinstance(raw, str):
                raise ValueError("Joined dates must be ISO local database dates")
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is not None:
                raise ValueError("Joined dates use the existing database local-time convention")
            result[key] = parsed.isoformat()
    if "joined_from" in result and "joined_before" in result \
            and result["joined_from"] >= result["joined_before"]:
        raise ValueError("Joined interval must be increasing and half-open")
    return result


async def _members(db, filters: dict) -> tuple[list[dict], int]:
    """Only parameterized, bounded queries; never execute user-provided SQL."""
    clauses = [
        "u.use_yn = 'Y'", "u.role_type = 'normal'",
        "not exists (select 1 from tb_ai_reader_agent a where a.user_id = u.user_id)",
    ]
    params = {"limit": MAX_MEMBERS + 1}
    if filters["purpose"] == "marketing":
        clauses.append("""coalesce((
            select n.noti_yn from tb_user_notification n
            where n.user_id = u.user_id and n.noti_type = 'marketing'
            order by n.updated_date desc, n.id desc limit 1
        ), 'N') = 'Y'""")
    if "user_ids" in filters:
        clauses.append("u.user_id in :user_ids")
        params["user_ids"] = filters["user_ids"]
    for key, operator in (("joined_from", ">="), ("joined_before", "<")):
        if key in filters:
            clauses.append(f"u.created_date {operator} :{key}")
            params[key] = filters[key]
    query = text(f"""
        select u.user_id, u.email from tb_user u
        where {' and '.join(clauses)} order by u.user_id asc limit :limit
    """)
    if "user_ids" in params:
        query = query.bindparams(bindparam("user_ids", expanding=True))
    rows = (await db.execute(query, params)).mappings().all()
    if len(rows) > MAX_MEMBERS:
        raise ValueError("More than 500 source members; narrow the filter, no partial audience is prepared")
    ai_domains = {
        domain.strip().lower()
        for domain in settings.AI_READER_ACCOUNT_ALLOWED_DOMAINS.split(",")
        if domain.strip()
    }
    recipients = []
    seen = set()
    excluded = 0
    for row in rows:
        raw = row["email"]
        # Do not silently trim malformed newline/withdrawal/multi-address values.
        if not isinstance(raw, str) or raw != raw.strip() or not _EMAIL.fullmatch(raw):
            excluded += 1
            continue
        address = raw.lower()
        if address.split("@", 1)[1] in ai_domains or address in seen or address == SENDER:
            excluded += 1
            continue
        seen.add(address)
        recipients.append({"user_id": int(row["user_id"]), "email": address})
    return recipients, excluded


def _public(record_id: str, record: dict) -> dict:
    result = {
        "receipt_id": record_id, "status": record["status"],
        "sender": SENDER, "recipient_count": record["recipient_count"],
        "content_hash": record["content_hash"],
        "expires_at": record["expires_at"],
    }
    if record["status"] in {"used", "sending", "sent_unverified", "uncertain", "verified"}:
        result["may_have_sent"] = True
        result["sent_verified"] = record["status"] == "verified"
    return result


async def preview_members(owner: str, db, filters: dict) -> dict:
    filters = _filters(filters)
    recipients, excluded = await _members(db, filters)
    record_id = "mail:preview:" + secrets.token_hex(16)
    data = {"filters": filters, "recipients": recipients}
    payload = {
        "sealed": _seal(data), "recipient_count": len(recipients),
        "content_hash": _digest(data), "expires_at": time.time() + SNAPSHOT_SECONDS,
    }
    store.save(record_id, owner, "prepared", payload)
    return {
        **_public(record_id, {"status": "prepared", **payload}),
        "filters": filters, "excluded_invalid_or_duplicate_count": excluded,
        "masked_sample": [
            {"user_id": row["user_id"], "email": "***@" + row["email"].split("@")[1]}
            for row in recipients[:10]
        ],
    }


def prepare_campaign(owner: str, preview_id: str, subject: str, body: str) -> dict:
    preview = _record(owner, preview_id, "preview")
    if preview["status"] != "prepared" or preview["expires_at"] <= time.time():
        raise ValueError("Member preview expired; prepare a fresh audience")
    if not isinstance(subject, str) or not 1 <= len(subject) <= 200 \
            or any(ord(char) < 32 for char in subject):
        raise ValueError("Subject must be 1-200 characters without header controls")
    if not isinstance(body, str) or not body.strip() or len(body.encode()) > 200_000 \
            or "\x00" in body:
        raise ValueError("A nonempty bounded plain-text body is required")
    audience = _open(preview)
    if not audience["recipients"]:
        raise ValueError("No eligible recipients")
    data = {
        **audience, "sender": SENDER, "subject": subject,
        "body": body.replace("\r\n", "\n").replace("\r", "\n"),
    }
    record_id = "mail:campaign:" + secrets.token_hex(16)
    payload = {
        "sealed": _seal(data), "recipient_count": len(data["recipients"]),
        "content_hash": _digest(data), "expires_at": preview["expires_at"],
    }
    store.save(record_id, owner, "prepared", payload)
    return {
        **_public(record_id, {"status": "prepared", **payload}),
        "subject": data["subject"], "body": data["body"],
        "filters": data["filters"], "authorization_required": True,
    }


def record_user_authorization(owner: str, campaign_id: str, content_hash: str, *,
                              source: str, evidence_ref: str) -> dict:
    """Trusted ingress only. MUST NOT be exposed as an MCP tool.

    The caller must verify evidence_ref references the real user's direct
    execution command or concrete-plan approval, including the frozen audience
    and exact subject/body. An autonomous proposal is not user authorization.
    """
    campaign = _record(owner, campaign_id, "campaign")
    if source not in {"direct_user_command", "approved_concrete_plan"} \
            or not isinstance(evidence_ref, str) or not evidence_ref.strip():
        raise ValueError("Verified user instruction evidence is required")
    if not isinstance(content_hash, str) or campaign["status"] != "prepared" or campaign["expires_at"] <= time.time() \
            or not secrets.compare_digest(content_hash, campaign["content_hash"]):
        raise ValueError("Authorization does not match the active exact campaign")
    store.save("mail:authorization:" + campaign_id, owner, "authorized", {
        "campaign_id": campaign_id, "content_hash": content_hash,
        "evidence_ref": evidence_ref, "source": source,
        "expires_at": campaign["expires_at"],
    })
    return {"campaign_id": campaign_id, "authorized": True, "content_hash": content_hash}


def _enabled_config() -> dict:
    config = load_config()
    if config.get("member_mail_enabled") is not True:
        raise RuntimeError("Member mail is disabled; server Workspace connection is not enabled")
    if not config.get("member_mail_service_account_file"):
        raise RuntimeError("Server Workspace credential path is not configured")
    return config


def capability_status() -> dict:
    config = load_config()
    enabled = config.get("member_mail_enabled") is True
    connected = bool(config.get("member_mail_service_account_file"))
    return {
        "sender": SENDER, "configured": connected, "enabled": enabled and connected,
        "runtime_connection_verified": False,
        "read_scope": READ_MEMBERS, "write_scope": WRITE_MAIL,
        "execution_requires": "matching verified user instruction",
        "mcp_registered": False,
        "blocker": None if enabled and connected else "Server Workspace credential is not connected/enabled",
    }


def _mime(campaign_id: str, data: dict) -> bytes:
    message = EmailMessage(policy=email_policy.SMTP)
    message["From"] = SENDER
    message["To"] = SENDER
    message["Bcc"] = ", ".join(row["email"] for row in data["recipients"])
    message["Subject"] = data["subject"]
    message["Message-ID"] = _message_id(campaign_id)
    message.set_content(data["body"], charset="utf-8")
    return message.as_bytes()


def _message_id(campaign_id: str) -> str:
    return "<likenovel-mail." + campaign_id.rsplit(":", 1)[1] + "@likenovel.net>"


class WorkspaceAdminGmail:
    """Existing DWD JWT pattern, fixed impersonated subject and Google URLs.

    No credentials are copied from Windows, returned, logged, or stored in
    receipts. Private service-account material stays in a WAS-owned file.
    """

    def __init__(self, credential_file: str):
        self.credential_file = credential_file

    async def _token(self, client: AsyncClient) -> str:
        path = Path(self.credential_file)
        if not path.is_absolute() or not path.is_file() \
                or stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise RuntimeError("Workspace credential must be an existing private absolute-path file")
        key = json.loads(path.read_text())
        if key.get("type") != "service_account" \
                or key.get("token_uri", TOKEN_URL) != TOKEN_URL:
            raise RuntimeError("Invalid Google Workspace service-account credential")
        now = int(time.time())
        assertion = jwt.encode({
            "iss": key["client_email"], "sub": SENDER, "scope": " ".join(GMAIL_SCOPES),
            "aud": TOKEN_URL, "iat": now, "exp": now + 3600,
        }, key["private_key"], algorithm="RS256")
        response = await client.post(TOKEN_URL, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion,
        })
        if response.status_code != 200:
            raise RuntimeError(f"Workspace authentication failed ({response.status_code})")
        return response.json()["access_token"]

    async def request(self, path: str, *, raw: bytes | None = None, params: dict | None = None) -> dict:
        # Paths are exclusively generated internally, not MCP input.
        if path not in {"/messages", "/messages/send"} \
                and not re.fullmatch(r"/messages/[A-Za-z0-9_-]+", path):
            raise ValueError("Invalid internal Gmail path")
        async with AsyncClient(timeout=30, follow_redirects=False) as client:
            token = await self._token(client)
            response = await client.request(
                "POST" if raw is not None else "GET", GMAIL_BASE + path,
                headers={"Authorization": "Bearer " + token},
                params=params,
                json={"raw": base64.urlsafe_b64encode(raw).decode()} if raw is not None else None,
            )
            if not response.is_success:
                raise RuntimeError(f"Workspace Gmail request failed ({response.status_code})")
            return response.json()


async def send_campaign(owner: str, campaign_id: str, db) -> dict:
    config = _enabled_config()
    campaign = _record(owner, campaign_id, "campaign")
    if campaign["status"] != "prepared":
        # Ambiguous/lost responses are never retried; use verify_sent instead.
        return _public(campaign_id, campaign)
    authorization = store.get("mail:authorization:" + campaign_id, owner)
    if not authorization or authorization["status"] != "authorized" \
            or authorization["expires_at"] <= time.time() \
            or authorization["content_hash"] != campaign["content_hash"]:
        raise ValueError("No matching verified user authorization")
    if campaign["expires_at"] <= time.time():
        raise ValueError("Campaign expired; prepare and authorize a fresh campaign")
    data = _open(campaign)
    if _digest(data) != campaign["content_hash"] or data["sender"] != SENDER:
        raise ValueError("Campaign integrity mismatch")
    current, _ = await _members(db, data["filters"])
    if current != data["recipients"]:
        raise ValueError("Member audience changed; prepare a new preview and campaign")
    raw = _mime(campaign_id, data)
    if not store.consume(campaign_id, owner, "prepared"):
        return _public(campaign_id, _record(owner, campaign_id, "campaign"))
    payload = {key: campaign[key] for key in ("sealed", "recipient_count", "content_hash", "expires_at")}
    store.save(campaign_id, owner, "sending", payload)
    gmail = WorkspaceAdminGmail(config["member_mail_service_account_file"])
    try:
        sent = await gmail.request("/messages/send", raw=raw)
        message_id = sent.get("id")
        if not isinstance(message_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", message_id):
            raise ValueError("Gmail send receipt is incomplete")
        payload["gmail_message_id"] = message_id
        store.save(campaign_id, owner, "sent_unverified", payload)
    except Exception:
        store.save(campaign_id, owner, "uncertain", payload)
        raise RuntimeError("Send outcome is uncertain; inspect Sent before any further action") from None
    return await verify_sent(owner, campaign_id)


def _sent_matches(message: dict, campaign_id: str, data: dict) -> bool:
    if "SENT" not in message.get("labelIds", []):
        return False
    payload = message.get("payload", {})
    headers = {}
    for item in payload.get("headers", []):
        headers.setdefault(item["name"].lower(), []).append(item["value"])

    def addresses(name: str) -> list[str]:
        return sorted(address.lower() for _, address in getaddresses(headers.get(name, [])))

    if addresses("from") != [SENDER] or addresses("to") != [SENDER] or addresses("cc") \
            or addresses("bcc") != sorted(row["email"] for row in data["recipients"]) \
            or headers.get("subject") != [data["subject"]] \
            or headers.get("message-id") != [_message_id(campaign_id)]:
        return False
    if payload.get("mimeType") != "text/plain" or payload.get("parts"):
        return False
    encoded = payload.get("body", {}).get("data", "")
    try:
        body = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    expected = data["body"] if data["body"].endswith("\n") else data["body"] + "\n"
    return body.replace("\r\n", "\n") == expected


async def verify_sent(owner: str, campaign_id: str) -> dict:
    config = _enabled_config()
    campaign = _record(owner, campaign_id, "campaign")
    if campaign["status"] == "verified":
        return _public(campaign_id, campaign)
    if campaign["status"] not in {"used", "sending", "sent_unverified", "uncertain"}:
        raise ValueError("Campaign has not entered the send path")
    data = _open(campaign)
    gmail = WorkspaceAdminGmail(config["member_mail_service_account_file"])
    message_id = campaign.get("gmail_message_id")
    if not message_id:
        found = await gmail.request("/messages", params={
            "q": "in:sent rfc822msgid:" + _message_id(campaign_id), "maxResults": 2,
        })
        matches = found.get("messages", [])
        if len(matches) != 1 or found.get("nextPageToken"):
            return {**_public(campaign_id, campaign), "sent_verified": False,
                    "action_required": "Sent result is unresolved; never resend automatically"}
        message_id = matches[0]["id"]
    message = await gmail.request("/messages/" + message_id, params={"format": "full"})
    if not _sent_matches(message, campaign_id, data):
        return {**_public(campaign_id, campaign), "sent_verified": False,
                "action_required": "Sent headers/body do not match the exact campaign"}
    payload = {key: campaign[key] for key in ("sealed", "recipient_count", "content_hash", "expires_at")}
    payload["gmail_message_id"] = message_id
    store.save(campaign_id, owner, "verified", payload)
    return _public(campaign_id, {"status": "verified", **payload})
