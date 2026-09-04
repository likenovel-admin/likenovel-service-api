from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from time import monotonic
from typing import Any, Literal
from uuid import uuid4

import pymysql
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.rdb import likenovel_db_session

logger = logging.getLogger(__name__)

CostSource = Literal["provider_reported", "rate_card", "unavailable"]
_COST_QUANTUM = Decimal("0.000000001")
_INSERT_SQL = """
INSERT INTO tb_ai_provider_usage_call (
    call_id,
    operation_id,
    attempt_no,
    feature_key,
    stage_key,
    request_mode,
    provider,
    requested_model,
    resolved_model,
    provider_request_id,
    attempt_status,
    http_status,
    error_code,
    input_tokens,
    cached_input_tokens,
    output_tokens,
    reasoning_tokens,
    total_tokens,
    cost_usd,
    cost_source,
    pricing_version,
    latency_ms,
    product_id,
    episode_id,
    session_id,
    batch_run_id,
    scope_key,
    attempt_started_at,
    record_hash
) VALUES (
    :call_id,
    :operation_id,
    :attempt_no,
    :feature_key,
    :stage_key,
    :request_mode,
    :provider,
    :requested_model,
    :resolved_model,
    :provider_request_id,
    :attempt_status,
    :http_status,
    :error_code,
    :input_tokens,
    :cached_input_tokens,
    :output_tokens,
    :reasoning_tokens,
    :total_tokens,
    :cost_usd,
    :cost_source,
    :pricing_version,
    :latency_ms,
    :product_id,
    :episode_id,
    :session_id,
    :batch_run_id,
    :scope_key,
    :attempt_started_at,
    :record_hash
)
"""
_FIND_EXISTING_SQL = """
SELECT call_id, operation_id, attempt_no, record_hash
FROM tb_ai_provider_usage_call
WHERE call_id = :call_id
   OR (operation_id = :operation_id AND attempt_no = :attempt_no)
LIMIT 1
"""
_SQLALCHEMY_BIND_PATTERN = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")
_INSERT_SQL_PYMYSQL = _SQLALCHEMY_BIND_PATTERN.sub(r"%(\1)s", _INSERT_SQL)
_FIND_EXISTING_SQL_PYMYSQL = _SQLALCHEMY_BIND_PATTERN.sub(
    r"%(\1)s",
    _FIND_EXISTING_SQL,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _bounded_text(value: object, limit: int) -> str | None:
    text_value = str(value or "").strip()
    return text_value[:limit] if text_value else None


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return None


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        normalized = Decimal(str(value))
        if not normalized.is_finite() or normalized < 0:
            return None
        return normalized.quantize(
            _COST_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, TypeError, ValueError):
        return None


@dataclass(frozen=True)
class AiProviderUsageAttempt:
    call_id: str
    operation_id: str
    attempt_no: int
    feature_key: str
    stage_key: str
    provider: str
    requested_model: str
    request_mode: str
    product_id: int | None
    episode_id: int | None
    session_id: str | None
    batch_run_id: str | None
    scope_key: str | None
    started_at: datetime
    started_monotonic: float = field(repr=False, compare=False)


@dataclass
class AiProviderUsageOperation:
    feature_key: str
    stage_key: str
    product_id: int | None = None
    episode_id: int | None = None
    session_id: str | None = None
    batch_run_id: str | None = None
    scope_key: str | None = None
    operation_id: str = field(default_factory=lambda: str(uuid4()))
    _attempt_no: int = field(default=0, init=False, repr=False)

    def start_attempt(
        self,
        *,
        provider: str,
        requested_model: str,
        request_mode: str,
        started_at: datetime | None = None,
    ) -> AiProviderUsageAttempt:
        self._attempt_no += 1
        return AiProviderUsageAttempt(
            call_id=str(uuid4()),
            operation_id=self.operation_id,
            attempt_no=self._attempt_no,
            feature_key=self.feature_key,
            stage_key=self.stage_key,
            provider=provider,
            requested_model=requested_model,
            request_mode=request_mode,
            product_id=self.product_id,
            episode_id=self.episode_id,
            session_id=self.session_id,
            batch_run_id=self.batch_run_id,
            scope_key=self.scope_key,
            started_at=started_at or _utc_now(),
            started_monotonic=monotonic(),
        )

    def discard_attempt(self, attempt: AiProviderUsageAttempt) -> bool:
        if (
            attempt.operation_id != self.operation_id
            or attempt.attempt_no != self._attempt_no
        ):
            return False
        self._attempt_no -= 1
        return True


@dataclass(frozen=True)
class AiProviderUsageRecord:
    call_id: str
    operation_id: str
    attempt_no: int
    feature_key: str
    stage_key: str
    request_mode: str
    provider: str
    requested_model: str
    resolved_model: str | None
    provider_request_id: str | None
    attempt_status: str
    http_status: int | None
    error_code: str | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None
    cost_usd: Decimal | None
    cost_source: CostSource
    pricing_version: str | None
    latency_ms: int
    product_id: int | None
    episode_id: int | None
    session_id: str | None
    batch_run_id: str | None
    scope_key: str | None
    attempt_started_at: datetime

    def as_db_params(self) -> dict[str, object]:
        params = asdict(self)
        started_at = self.attempt_started_at
        if started_at.tzinfo is not None:
            started_at = started_at.astimezone(timezone.utc).replace(tzinfo=None)
        params["attempt_started_at"] = started_at
        hash_payload = {
            key: str(value) if isinstance(value, (Decimal, datetime)) else value
            for key, value in params.items()
        }
        params["record_hash"] = hashlib.sha256(
            json.dumps(
                hash_payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return params


def estimate_provider_cost(
    *,
    provider: str,
    model: str,
    input_tokens: int | None,
    cached_input_tokens: int | None,
    output_tokens: int | None,
    reasoning_tokens: int | None,
    cache_creation_input_tokens: int | None = None,
) -> tuple[Decimal | None, CostSource, str | None]:
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip().lower()
    has_token_usage = any(
        value is not None
        for value in (
            input_tokens,
            cached_input_tokens,
            output_tokens,
            reasoning_tokens,
            cache_creation_input_tokens,
        )
    )
    if not has_token_usage:
        return None, "unavailable", None
    if normalized_provider == "gemini" and normalized_model in {
        "gemini-3.1-flash-lite",
        "gemini-3.1-flash-lite-preview",
    }:
        cached = min(
            max(cached_input_tokens or 0, 0),
            max(input_tokens or 0, 0),
        )
        uncached = max((input_tokens or 0) - cached, 0)
        generated = max(output_tokens or 0, 0) + max(reasoning_tokens or 0, 0)
        cost = (
            Decimal(uncached) * Decimal("0.25")
            + Decimal(cached) * Decimal("0.025")
            + Decimal(generated) * Decimal("1.50")
        ) / Decimal(1_000_000)
        return (
            cost.quantize(_COST_QUANTUM, rounding=ROUND_HALF_UP),
            "rate_card",
            "google-gemini-2026-09-04",
        )
    if normalized_provider == "anthropic" and (
        normalized_model == "claude-haiku-4-5"
        or normalized_model.startswith("claude-haiku-4-5-")
    ):
        cost = (
            Decimal(max(input_tokens or 0, 0)) * Decimal("1.00")
            + Decimal(max(cache_creation_input_tokens or 0, 0)) * Decimal("1.25")
            + Decimal(max(cached_input_tokens or 0, 0)) * Decimal("0.10")
            + Decimal(max(output_tokens or 0, 0)) * Decimal("5.00")
        ) / Decimal(1_000_000)
        return (
            cost.quantize(_COST_QUANTUM, rounding=ROUND_HALF_UP),
            "rate_card",
            "anthropic-2026-09-04",
        )
    return None, "unavailable", None


def build_ai_provider_usage_record(
    attempt: AiProviderUsageAttempt,
    *,
    status: str,
    response_json: dict[str, Any] | None = None,
    response_headers: object | None = None,
    http_status: int | None = None,
    error_code: str | None = None,
    latency_ms: int | None = None,
) -> AiProviderUsageRecord:
    payload = response_json if isinstance(response_json, dict) else {}
    usage: dict[str, Any] = {}
    resolved_model = _bounded_text(
        payload.get("model") or payload.get("modelVersion"),
        128,
    )
    provider_request_id = _bounded_text(
        payload.get("id") or payload.get("responseId"),
        128,
    )
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: Decimal | None = None
    cost_source: CostSource = "unavailable"
    pricing_version: str | None = None

    if attempt.provider == "gemini":
        usage = payload.get("usageMetadata") if isinstance(payload.get("usageMetadata"), dict) else {}
        input_tokens = _optional_nonnegative_int(usage.get("promptTokenCount"))
        cached_input_tokens = _optional_nonnegative_int(usage.get("cachedContentTokenCount"))
        output_tokens = _optional_nonnegative_int(usage.get("candidatesTokenCount"))
        reasoning_tokens = _optional_nonnegative_int(usage.get("thoughtsTokenCount"))
        total_tokens = _optional_nonnegative_int(usage.get("totalTokenCount"))
    elif attempt.provider == "anthropic":
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        input_tokens = _optional_nonnegative_int(usage.get("input_tokens"))
        cached_input_tokens = _optional_nonnegative_int(usage.get("cache_read_input_tokens"))
        cache_creation_input_tokens = _optional_nonnegative_int(
            usage.get("cache_creation_input_tokens")
        )
        output_tokens = _optional_nonnegative_int(usage.get("output_tokens"))
        values = [input_tokens, cached_input_tokens, cache_creation_input_tokens, output_tokens]
        total_tokens = sum(value or 0 for value in values) if any(value is not None for value in values) else None
    else:
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        input_tokens = _optional_nonnegative_int(usage.get("prompt_tokens"))
        output_tokens = _optional_nonnegative_int(usage.get("completion_tokens"))
        total_tokens = _optional_nonnegative_int(usage.get("total_tokens"))
        prompt_details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
        completion_details = usage.get("completion_tokens_details") if isinstance(usage.get("completion_tokens_details"), dict) else {}
        cached_input_tokens = _optional_nonnegative_int(prompt_details.get("cached_tokens"))
        reasoning_tokens = _optional_nonnegative_int(completion_details.get("reasoning_tokens"))
        if "cost" in usage:
            cost_usd = _optional_decimal(usage.get("cost"))
            if cost_usd is not None:
                cost_source = "provider_reported"

    if response_headers is not None and not provider_request_id:
        get_header = getattr(response_headers, "get", None)
        if callable(get_header):
            provider_request_id = _bounded_text(
                get_header("request-id")
                or get_header("x-request-id")
                or get_header("anthropic-request-id"),
                128,
            )

    if cost_usd is None:
        cost_usd, cost_source, pricing_version = estimate_provider_cost(
            provider=attempt.provider,
            model=resolved_model or attempt.requested_model,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
        )

    elapsed_ms = max(int((monotonic() - attempt.started_monotonic) * 1000), 0)
    return AiProviderUsageRecord(
        call_id=attempt.call_id,
        operation_id=attempt.operation_id,
        attempt_no=attempt.attempt_no,
        feature_key=str(attempt.feature_key)[:32],
        stage_key=str(attempt.stage_key)[:64],
        request_mode=str(attempt.request_mode)[:16],
        provider=str(attempt.provider)[:32],
        requested_model=str(attempt.requested_model)[:128],
        resolved_model=resolved_model,
        provider_request_id=provider_request_id,
        attempt_status=str(status or "internal_error")[:32],
        http_status=_optional_nonnegative_int(http_status),
        error_code=_bounded_text(error_code, 64),
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        cost_source=cost_source,
        pricing_version=pricing_version,
        latency_ms=max(int(latency_ms), 0) if latency_ms is not None else elapsed_ms,
        product_id=attempt.product_id,
        episode_id=attempt.episode_id,
        session_id=_bounded_text(attempt.session_id, 64),
        batch_run_id=_bounded_text(attempt.batch_run_id, 64),
        scope_key=_bounded_text(attempt.scope_key, 128),
        attempt_started_at=attempt.started_at,
    )


async def _existing_async_record_matches(params: dict[str, object]) -> bool:
    async with likenovel_db_session() as db:
        result = await db.execute(text(_FIND_EXISTING_SQL), params)
        row = result.mappings().first()
    return bool(row and str(row.get("record_hash") or "") == params["record_hash"])


async def persist_ai_provider_usage_async(record: AiProviderUsageRecord) -> bool:
    params = record.as_db_params()
    for attempt_no in range(2):
        try:
            async with likenovel_db_session() as db:
                await db.execute(text(_INSERT_SQL), params)
                await db.commit()
            return True
        except IntegrityError:
            if await _existing_async_record_matches(params):
                return True
            logger.error(
                "ai_provider_usage persistence_invariant_failed feature=%s stage=%s call_id=%s operation_id=%s attempt_no=%s",
                record.feature_key,
                record.stage_key,
                record.call_id,
                record.operation_id,
                record.attempt_no,
            )
            return False
        except Exception as exc:
            if attempt_no == 0:
                continue
            logger.error(
                "ai_provider_usage persist_failed feature=%s stage=%s call_id=%s db_error_class=%s",
                record.feature_key,
                record.stage_key,
                record.call_id,
                type(exc).__name__,
            )
            return False
    return False


def _existing_sync_record_matches(connection: object, params: dict[str, object]) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(_FIND_EXISTING_SQL_PYMYSQL, params)
        row = cursor.fetchone()
    return bool(row and str(row.get("record_hash") or "") == params["record_hash"])


def persist_ai_provider_usage_pymysql(
    connection: object,
    record: AiProviderUsageRecord,
) -> bool:
    params = record.as_db_params()
    for attempt_no in range(2):
        try:
            connection.ping(reconnect=attempt_no > 0)
            with connection.cursor() as cursor:
                cursor.execute(_INSERT_SQL_PYMYSQL, params)
            connection.commit()
            return True
        except pymysql.err.IntegrityError:
            if _existing_sync_record_matches(connection, params):
                return True
            logger.error(
                "ai_provider_usage persistence_invariant_failed feature=%s stage=%s call_id=%s operation_id=%s attempt_no=%s",
                record.feature_key,
                record.stage_key,
                record.call_id,
                record.operation_id,
                record.attempt_no,
            )
            return False
        except Exception as exc:
            try:
                connection.rollback()
            except Exception:
                pass
            if attempt_no == 0:
                continue
            logger.error(
                "ai_provider_usage persist_failed feature=%s stage=%s call_id=%s db_error_class=%s",
                record.feature_key,
                record.stage_key,
                record.call_id,
                type(exc).__name__,
            )
            return False
    return False
