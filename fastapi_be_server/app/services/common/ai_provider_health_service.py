from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import settings

logger = logging.getLogger(__name__)

PROVIDER_ORDER = ("gemini", "claude", "openrouter", "deepseek")
SUCCESS_STATUS = "ok"
NOT_CONFIGURED_STATUS = "not_configured"
NOT_CHECKED_STATUS = "not_checked"
ERROR_MESSAGE_MAX_LENGTH = 500


@dataclass(frozen=True)
class ProviderSpec:
    provider: str
    model: str
    api_key: str
    base_url: str
    affected_features: str
    api_kind: str


def _provider_specs() -> list[ProviderSpec]:
    return [
        ProviderSpec(
            provider="gemini",
            model=settings.WEBSOCHAT_GEMINI_MODEL,
            api_key=settings.GEMINI_API_KEY,
            base_url="https://generativelanguage.googleapis.com/v1beta",
            affected_features="websochat",
            api_kind="gemini",
        ),
        ProviderSpec(
            provider="claude",
            model=settings.ANTHROPIC_MODEL,
            api_key=settings.ANTHROPIC_API_KEY,
            base_url="https://api.anthropic.com/v1",
            affected_features="ai_metadata,websochat_fallback",
            api_kind="anthropic",
        ),
        ProviderSpec(
            provider="openrouter",
            model=settings.AI_READER_OPENROUTER_MODEL,
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL,
            affected_features="ai_reader,story_context",
            api_kind="openai_compatible",
        ),
        ProviderSpec(
            provider="deepseek",
            model=settings.AI_PROVIDER_HEALTH_DEEPSEEK_MODEL,
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            affected_features="story_context,dna_fallback",
            api_kind="deepseek",
        ),
    ]


def classify_provider_error(*, http_status: int | None, error_text: str | None) -> dict[str, str | None]:
    normalized_text = (error_text or "").lower()
    error_code = _extract_provider_error_code(error_text)

    if http_status == 429 and re.search(r"credit|prepayment|depleted|insufficient", normalized_text):
        return {
            "status": "credit_depleted",
            "error_code": error_code or "credit_depleted",
            "error_message": _summarize_error_message(error_text),
        }
    if http_status == 429:
        return {
            "status": "rate_limited",
            "error_code": error_code or "rate_limited",
            "error_message": _summarize_error_message(error_text),
        }
    if http_status in {401, 403}:
        return {
            "status": "auth_failed",
            "error_code": error_code or "auth_failed",
            "error_message": _summarize_error_message(error_text),
        }
    if http_status and http_status >= 500:
        return {
            "status": "provider_error",
            "error_code": error_code or "provider_error",
            "error_message": _summarize_error_message(error_text),
        }
    return {
        "status": "unknown_error",
        "error_code": error_code or "unknown_error",
        "error_message": _summarize_error_message(error_text),
    }


def classify_provider_exception(exc: Exception) -> dict[str, str | None]:
    if isinstance(exc, httpx.TimeoutException):
        return {
            "status": "timeout",
            "error_code": "timeout",
            "error_message": "provider request timed out",
        }
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return classify_provider_error(
            http_status=exc.response.status_code,
            error_text=exc.response.text,
        )
    return {
        "status": "provider_error",
        "error_code": exc.__class__.__name__,
        "error_message": _summarize_error_message(str(exc)),
    }


async def run_ai_provider_health_checks(db: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    for spec in _provider_specs():
        result = await _check_provider(spec)
        await _insert_health_check(db, result)
        results.append(_serialize_health_row(result))
    await db.commit()
    return {"results": results}


async def get_ai_provider_health_summary(db: AsyncSession) -> list[dict[str, Any]]:
    latest_result = await db.execute(text("""
        SELECT h.provider,
               h.model,
               h.status,
               h.http_status,
               h.error_code,
               h.error_message,
               h.latency_ms,
               h.checked_at,
               h.success_at,
               h.affected_features
          FROM tb_ai_provider_health_check h
          JOIN (
                SELECT provider, MAX(health_check_id) AS health_check_id
                  FROM tb_ai_provider_health_check
                 GROUP BY provider
          ) latest
            ON latest.health_check_id = h.health_check_id
    """))
    latest_by_provider = {
        row["provider"]: dict(row)
        for row in latest_result.mappings().all()
    }

    success_result = await db.execute(text("""
        SELECT provider, MAX(success_at) AS last_success_at
          FROM tb_ai_provider_health_check
         WHERE success_at IS NOT NULL
         GROUP BY provider
    """))
    last_success_by_provider = {
        row["provider"]: row["last_success_at"]
        for row in success_result.mappings().all()
    }

    rows: list[dict[str, Any]] = []
    for spec in _provider_specs():
        latest = latest_by_provider.get(spec.provider)
        if latest:
            row = _serialize_health_row(latest)
            row["last_success_at"] = _format_dt(
                latest.get("success_at") or last_success_by_provider.get(spec.provider)
            )
            rows.append(row)
            continue

        rows.append(_default_health_row(spec))
    return rows


async def _check_provider(spec: ProviderSpec) -> dict[str, Any]:
    checked_at = datetime.now()
    if not spec.api_key:
        return _health_result(
            spec=spec,
            status=NOT_CONFIGURED_STATUS,
            checked_at=checked_at,
            http_status=None,
            error_code="missing_api_key",
            error_message="API key is not configured",
            latency_ms=None,
        )

    started = time.monotonic()
    try:
        response = await _post_health_prompt(spec)
        latency_ms = int((time.monotonic() - started) * 1000)
        if 200 <= response.status_code < 300:
            return _health_result(
                spec=spec,
                status=SUCCESS_STATUS,
                checked_at=checked_at,
                http_status=response.status_code,
                error_code=None,
                error_message=None,
                latency_ms=latency_ms,
            )
        classified = classify_provider_error(
            http_status=response.status_code,
            error_text=response.text,
        )
        return _health_result(
            spec=spec,
            status=str(classified["status"]),
            checked_at=checked_at,
            http_status=response.status_code,
            error_code=classified["error_code"],
            error_message=classified["error_message"],
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        classified = classify_provider_exception(exc)
        logger.warning(
            "AI provider health check failed",
            extra={"provider": spec.provider, "status": classified["status"]},
        )
        return _health_result(
            spec=spec,
            status=str(classified["status"]),
            checked_at=checked_at,
            http_status=None,
            error_code=classified["error_code"],
            error_message=classified["error_message"],
            latency_ms=latency_ms,
        )


async def _post_health_prompt(spec: ProviderSpec) -> httpx.Response:
    timeout_seconds = settings.AI_PROVIDER_HEALTH_TIMEOUT_SECONDS
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        if spec.api_kind == "gemini":
            return await client.post(
                f"{spec.base_url}/models/{spec.model}:generateContent",
                headers={
                    "content-type": "application/json",
                    "x-goog-api-key": spec.api_key,
                },
                json={
                    "contents": [{"role": "user", "parts": [{"text": "Reply exactly OK."}]}],
                    "generationConfig": {"temperature": 0, "maxOutputTokens": 4},
                },
            )
        if spec.api_kind == "anthropic":
            return await client.post(
                f"{spec.base_url}/messages",
                headers={
                    "x-api-key": spec.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": spec.model,
                    "max_tokens": 4,
                    "system": "Health check.",
                    "messages": [{"role": "user", "content": "Reply exactly OK."}],
                },
            )

        payload: dict[str, Any] = {
            "model": spec.model,
            "temperature": 0,
            "max_tokens": 4,
            "messages": [{"role": "user", "content": "Reply exactly OK."}],
        }
        if spec.api_kind == "openai_compatible":
            provider_only = _split_csv(settings.AI_READER_OPENROUTER_PROVIDER_ONLY)
            if provider_only:
                payload["provider"] = {
                    "only": provider_only,
                    "require_parameters": True,
                }

        return await client.post(
            _join_url(spec.base_url, "/chat/completions"),
            headers={
                "Authorization": f"Bearer {spec.api_key}",
                "Content-Type": "application/json",
                "X-Title": "LikeNovel AI Provider Health",
            },
            json=payload,
        )


def _health_result(
    *,
    spec: ProviderSpec,
    status: str,
    checked_at: datetime,
    http_status: int | None,
    error_code: str | None,
    error_message: str | None,
    latency_ms: int | None,
) -> dict[str, Any]:
    return {
        "provider": spec.provider,
        "model": spec.model,
        "status": status,
        "http_status": http_status,
        "error_code": error_code,
        "error_message": _truncate(error_message, ERROR_MESSAGE_MAX_LENGTH),
        "latency_ms": latency_ms,
        "checked_at": checked_at,
        "success_at": checked_at if status == SUCCESS_STATUS else None,
        "affected_features": spec.affected_features,
    }


def _default_health_row(spec: ProviderSpec) -> dict[str, Any]:
    status = NOT_CHECKED_STATUS if spec.api_key else NOT_CONFIGURED_STATUS
    return {
        "provider": spec.provider,
        "model": spec.model,
        "status": status,
        "http_status": None,
        "error_code": "missing_api_key" if status == NOT_CONFIGURED_STATUS else None,
        "error_message": "API key is not configured" if status == NOT_CONFIGURED_STATUS else None,
        "latency_ms": None,
        "checked_at": None,
        "success_at": None,
        "last_success_at": None,
        "affected_features": spec.affected_features,
    }


async def _insert_health_check(db: AsyncSession, result: dict[str, Any]) -> None:
    await db.execute(
        text("""
            INSERT INTO tb_ai_provider_health_check (
                provider,
                model,
                status,
                http_status,
                error_code,
                error_message,
                latency_ms,
                checked_at,
                success_at,
                affected_features
            ) VALUES (
                :provider,
                :model,
                :status,
                :http_status,
                :error_code,
                :error_message,
                :latency_ms,
                :checked_at,
                :success_at,
                :affected_features
            )
        """),
        result,
    )


def _extract_provider_error_code(error_text: str | None) -> str | None:
    if not error_text:
        return None
    try:
        payload = json.loads(error_text)
    except json.JSONDecodeError:
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        code = error.get("status") or error.get("code") or error.get("type")
        return str(code) if code else None
    return None


def _summarize_error_message(error_text: str | None) -> str | None:
    if not error_text:
        return None
    message = error_text
    try:
        payload = json.loads(error_text)
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and error.get("message"):
            message = str(error["message"])
    except json.JSONDecodeError:
        message = error_text
    message = re.sub(r"\s+", " ", message).strip()
    return _truncate(message, ERROR_MESSAGE_MAX_LENGTH)


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _serialize_health_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": row.get("provider"),
        "model": row.get("model"),
        "status": row.get("status"),
        "http_status": row.get("http_status"),
        "error_code": row.get("error_code"),
        "error_message": row.get("error_message"),
        "latency_ms": row.get("latency_ms"),
        "checked_at": _format_dt(row.get("checked_at")),
        "success_at": _format_dt(row.get("success_at")),
        "last_success_at": _format_dt(row.get("last_success_at") or row.get("success_at")),
        "affected_features": row.get("affected_features"),
    }


def _format_dt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)
