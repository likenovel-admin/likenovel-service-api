"""Bounded billing-route selection for one already pinned model configuration.

Only a confirmed credit rejection advances to another prepaid account. Transport
errors, malformed responses, and errors after a stream starts never trigger a
second inference request. Credentials remain outside model configuration and DB.
"""
from __future__ import annotations

import copy
import asyncio
import logging
import json as json_module
import os
import re
import stat
from collections.abc import Callable
from contextlib import asynccontextmanager, contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

import httpx

from app.services.common.openrouter_background_credit_guard import (
    _background_credit_lock,
    assert_openrouter_background_credit_available,
    openrouter_background_credit_reservation_async,
)
from app.services.common.ai_provider_usage import (
    AiProviderUsageOperation,
    AiProviderUsageAttempt,
    build_ai_provider_usage_record,
    persist_ai_provider_usage_async,
)

logger = logging.getLogger(__name__)


_PREPAID_BASE_URLS = {
    "hive": "https://api-cdn.thehive.ai/api/v3",
    "river": "https://api.river.ai/v1",
}
# These aliases are published by the respective providers. Unknown IDs must be
# resolved/added explicitly, rather than guessing from case or organization.
_PROVIDER_MODEL_IDS = {
    "hive": {
        "deepseek/deepseek-v4.1-flash-1017": "deepseek-ai/deepseek-v4.1-flash-1017",
    },
    "river": {
        "deepseek/deepseek-v4.1-flash-1017": "deepseek-ai/DeepSeek-V4.1-Flash-1017",
    },
}
_CREDIT_ERROR_CODES = frozenset({
    "insufficient_credit", "insufficient_credits", "insufficient_balance",
    "credit_balance_exhausted", "credits_exhausted", "balance_exhausted",
})
_ACCOUNT_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
_SAFE_HEADER_NAMES = frozenset({"content-type", "accept", "http-referer", "x-title"})


class AiModelGatewayConfigurationError(RuntimeError):
    """The chosen route cannot be used; this is not a credit exhaustion signal."""


class AiModelGatewayTransportError(httpx.RequestError):
    """Sanitized transport failure with no automatic cross-account resubmission."""


@dataclass(frozen=True)
class ProviderAccount:
    id: str
    api_key: str = field(repr=False)


@dataclass(frozen=True)
class _Target:
    provider: str
    account_alias: str
    base_url: str
    api_key: str = field(repr=False)
    model_id: str


@dataclass(frozen=True)
class _RequestPlan:
    model_id: str
    revision: int
    targets: tuple[_Target, ...]


def load_provider_accounts(provider: str) -> tuple[ProviderAccount, ...]:
    """Load a server-owned pool. Never report key values or parser input in errors."""
    if provider not in _PREPAID_BASE_URLS:
        raise AiModelGatewayConfigurationError("unsupported prepaid provider")
    path_value = os.getenv("AI_PROVIDER_ACCOUNTS_FILE", "").strip()
    if not path_value:
        raise AiModelGatewayConfigurationError("AI_PROVIDER_ACCOUNTS_FILE is not configured")
    try:
        # Reject symlink substitutions and readable-by-others credential files.
        descriptor = os.open(Path(path_value), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "r", encoding="utf-8") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                raise ValueError("unsafe credential file permissions")
            payload = json_module.load(source)
    except (OSError, ValueError, TypeError, UnicodeError):
        raise AiModelGatewayConfigurationError("provider credential file is unavailable or invalid") from None
    rows = payload.get(provider) if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise AiModelGatewayConfigurationError(f"{provider} account pool is not configured")
    accounts: list[ProviderAccount] = []
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise AiModelGatewayConfigurationError(f"{provider} account pool is invalid")
        alias, key = row.get("id"), row.get("api_key")
        if (
            not isinstance(alias, str) or not _ACCOUNT_ID.fullmatch(alias)
            or not isinstance(key, str) or not key.strip() or "\n" in key or "\r" in key
            or alias in seen_ids or key.strip() in seen_keys or key.strip() in alias
        ):
            raise AiModelGatewayConfigurationError(f"{provider} account pool is invalid")
        seen_ids.add(alias)
        seen_keys.add(key.strip())
        accounts.append(ProviderAccount(alias, key.strip()))
    return tuple(accounts)


def provider_model_id(provider: str, canonical_model_id: str) -> str:
    if provider == "openrouter":
        return canonical_model_id
    mapped = _PROVIDER_MODEL_IDS.get(provider, {}).get(canonical_model_id)
    if not mapped:
        raise AiModelGatewayConfigurationError("selected model has no verified provider mapping")
    return mapped


def provider_capabilities(provider: str, canonical_model_id: str) -> frozenset[str]:
    """Confirmed capabilities only; an empty set means unverified, not impossible.

    Hive Flash: 2026-10-26 bounded live smoke accepted JSON object, strict schema,
    and nested schema despite conflicting prompt text. Forced tool use failed;
    this small smoke is not a guarantee of all schema/semantic correctness.
    River Flash: documented structured output and tools, not a live smoke here.
    OpenRouter capabilities belong to its current per-model metadata validator.
    """
    if canonical_model_id not in _PROVIDER_MODEL_IDS.get(provider, {}):
        return frozenset()
    if provider == "hive":
        return frozenset({"text", "json_object", "json_schema"})
    if provider == "river":
        return frozenset({"text", "json_object", "json_schema", "tools"})
    return frozenset()


def _once_before_submit(callback: Callable[[], None] | None) -> Callable[[], None]:
    submitted = False

    def notify() -> None:
        nonlocal submitted
        if submitted:
            return
        if callback is not None:
            callback()
        submitted = True

    return notify


def _request_plan(feature_key: str, payload: dict[str, Any], base_url: str, api_key: str) -> _RequestPlan:
    # The configuration owner pins this context for the whole job. Read it once,
    # so a setting change cannot alter the fallback model during this call.
    from app.services.common.ai_model_config import get_model_binding

    binding = get_model_binding(feature_key, default_model=payload.get("model"), default_route="openrouter")
    model_id = str(binding.model_id).strip()
    route = str(binding.billing_route)
    if not model_id or route not in {"openrouter", "hive", "river"}:
        raise AiModelGatewayConfigurationError("invalid model billing route")
    targets: list[_Target] = []
    if route != "openrouter":
        native_model = provider_model_id(route, model_id)
        targets.extend(
            _Target(route, account.id, _PREPAID_BASE_URLS[route], account.api_key, native_model)
            for account in load_provider_accounts(route)
        )
    targets.append(_Target("openrouter", "openrouter", base_url.rstrip("/"), api_key, model_id))
    return _RequestPlan(model_id, int(binding.revision), tuple(targets))


def _payload_for_target(payload: dict[str, Any], target: _Target, *, stream: bool) -> dict[str, Any]:
    body = copy.deepcopy(payload)
    body["model"] = target.model_id
    body["stream"] = stream
    if (
        target.model_id in {
            "deepseek/deepseek-v4.1-flash-1017",
            "deepseek-ai/deepseek-v4.1-flash-1017",
            "deepseek-ai/DeepSeek-V4.1-Flash-1017",
        }
        and "reasoning" not in body and "reasoning_effort" not in body
    ):
        # Hive Flash defaults to high; unstated thinking must not consume a
        # JSON/health caller's bounded output budget. Explicit choices survive.
        body["reasoning"] = {"effort": "none", "exclude": True}
    if target.provider == "openrouter":
        if body.get("response_format") or body.get("tools"):
            body["provider"] = {**body.get("provider", {}), "require_parameters": True}
        return body
    body.pop("provider", None)
    reasoning = body.pop("reasoning", None)
    if reasoning is not None:
        if not isinstance(reasoning, dict) or reasoning.get("effort") not in {"none", "low", "high", "max"}:
            raise AiModelGatewayConfigurationError("reasoning configuration is unsupported on selected provider")
        body["reasoning_effort"] = reasoning["effort"]
    if body.get("reasoning_effort") not in {None, "none", "low", "high", "max"}:
        raise AiModelGatewayConfigurationError("reasoning effort is unsupported on selected provider")
    if target.provider == "hive" and "max_tokens" in body:
        body["max_completion_tokens"] = body.pop("max_tokens")
    # response_format and its strict schema are deliberately never weakened.
    return body


def _headers_for_target(headers: dict[str, str], target: _Target) -> dict[str, str]:
    if not target.api_key.strip():
        raise AiModelGatewayConfigurationError(f"{target.provider} credentials are not configured")
    result = {key: value for key, value in headers.items() if key.lower() in _SAFE_HEADER_NAMES}
    result["Authorization"] = f"Bearer {target.api_key}"
    return result


def _credit_exhausted(response: httpx.Response) -> bool:
    if response.status_code == 402:
        return True
    if response.status_code < 400:
        return False
    try:
        payload = response.json()
    except (ValueError, UnicodeError):
        return False
    if not isinstance(payload, dict):
        return False
    error = payload.get("error")
    candidates = [payload.get("code"), payload.get("type")]
    if isinstance(error, dict):
        candidates.extend([error.get("code"), error.get("type")])
    return any(isinstance(code, str) and code.lower() in _CREDIT_ERROR_CODES for code in candidates)


def _annotate_response(response: httpx.Response, target: _Target, plan: _RequestPlan) -> httpx.Response:
    if response.status_code >= 400:
        content = response.content
        for candidate in plan.targets:
            if candidate.api_key:
                content = content.replace(candidate.api_key.encode(), b"[redacted]")
        if content != response.content:
            headers = {
                key: value for key, value in response.headers.items()
                if key.lower() not in {"content-length", "content-encoding"}
            }
            response = httpx.Response(
                response.status_code, headers=headers, content=content,
                request=response.request, extensions=dict(response.extensions),
            )
    response.extensions["ai_route"] = {
        "provider": target.provider,
        "account_alias": target.account_alias,
        "requested_model": plan.model_id,
        "resolved_model": target.model_id,
        "config_revision": plan.revision,
    }
    return response


def post_model_chat_completion(
    client: Any, *, feature_key: str, base_url: str, api_key: str,
    headers: dict[str, str], json: dict[str, Any],
    priority_headroom_usd: Any | None = None, background: bool = True,
    before_submit: Callable[[], None] | None = None,
    **request_kwargs: Any,
) -> httpx.Response:
    plan = _request_plan(feature_key, json, base_url, api_key)
    notify = _once_before_submit(before_submit)
    for target in plan.targets:
        body = _payload_for_target(json, target, stream=False)
        target_headers = _headers_for_target(headers, target)
        try:
            guarded = target.provider == "openrouter" and background
            with _background_credit_lock() if guarded else nullcontext():
                if guarded:
                    assert_openrouter_background_credit_available(
                        client, base_url=target.base_url, api_key=target.api_key,
                        priority_headroom_usd=priority_headroom_usd,
                    )
                notify()
                response = client.post(
                    f"{target.base_url}/chat/completions", headers=target_headers,
                    json=body, **request_kwargs,
                )
        except httpx.RequestError:
            raise AiModelGatewayTransportError(f"{target.provider} transport outcome is unknown; request was not resubmitted") from None
        if target.provider != "openrouter" and _credit_exhausted(response):
            response.close()
            continue
        return _annotate_response(response, target, plan)
    raise AssertionError("OpenRouter terminal target was not processed")


async def post_model_chat_completion_async(
    client: Any, *, feature_key: str, base_url: str, api_key: str,
    headers: dict[str, str], json: dict[str, Any],
    priority_headroom_usd: Any | None = None, background: bool = True,
    before_submit: Callable[[], None] | None = None,
    usage_operation: AiProviderUsageOperation | None = None,
    **request_kwargs: Any,
) -> httpx.Response:
    plan = _request_plan(feature_key, json, base_url, api_key)
    notify = _once_before_submit(before_submit)
    for target in plan.targets:
        body = _payload_for_target(json, target, stream=False)
        target_headers = _headers_for_target(headers, target)
        attempt = None
        response = None
        attempt_status = "transport_error"
        try:
            reservation = (
                openrouter_background_credit_reservation_async(
                    client, base_url=target.base_url, api_key=target.api_key,
                    priority_headroom_usd=priority_headroom_usd,
                ) if target.provider == "openrouter" and background else nullcontext()
            )
            async with reservation:
                notify()
                if usage_operation is not None:
                    attempt = usage_operation.start_attempt(
                        provider=target.provider, requested_model=plan.model_id,
                        request_mode="nonstream",
                    )
                response = await client.post(
                    f"{target.base_url}/chat/completions", headers=target_headers,
                    json=body, **request_kwargs,
                )
                attempt_status = "success" if 200 <= response.status_code < 300 else "http_error"
        except asyncio.CancelledError:
            attempt_status = "cancelled"
            raise
        except httpx.RequestError:
            raise AiModelGatewayTransportError(f"{target.provider} transport outcome is unknown; request was not resubmitted") from None
        finally:
            if attempt is not None:
                await _record_gateway_usage(attempt, target, response, attempt_status)
        if target.provider != "openrouter" and _credit_exhausted(response):
            await response.aclose()
            continue
        return _annotate_response(response, target, plan)
    raise AssertionError("OpenRouter terminal target was not processed")


async def _record_gateway_usage(
    attempt: AiProviderUsageAttempt, target: _Target,
    response: httpx.Response | None, attempt_status: str,
) -> None:
    """Account every submitted request, including rejections before fallback.

    HTTP success means a response arrived, not that its decision JSON is valid.
    Persistence failure must never cause a second billable inference request.
    """
    try:
        payload = response.json() if response is not None else {}
    except ValueError:
        payload = {}
        if attempt_status == "success":
            attempt_status = "invalid_response"
    if not isinstance(payload, dict):
        payload = {}
        if attempt_status == "success":
            attempt_status = "invalid_response"
    record = build_ai_provider_usage_record(
        attempt, status=attempt_status,
        response_json={**payload, "model": payload.get("model") or target.model_id},
        response_headers=response.headers if response is not None else None,
        http_status=response.status_code if response is not None else None,
    )
    logger.info(
        "ai_provider_attempt call_id=%s operation_id=%s provider=%s account_alias=%s status=%s",
        attempt.call_id, attempt.operation_id, target.provider, target.account_alias, attempt_status,
    )
    try:
        persisted = await asyncio.wait_for(persist_ai_provider_usage_async(record), timeout=2.0)
        if not persisted:
            logger.error("ai_provider_usage not_persisted call_id=%s", attempt.call_id)
    except Exception as exc:
        logger.error("ai_provider_usage persist_failed call_id=%s error_class=%s",
                     attempt.call_id, type(exc).__name__)


@contextmanager
def stream_model_chat_completion(
    client: Any, *, feature_key: str, base_url: str, api_key: str,
    headers: dict[str, str], json: dict[str, Any],
    priority_headroom_usd: Any | None = None, background: bool = True,
    **request_kwargs: Any,
) -> Iterator[httpx.Response]:
    """Synchronous streaming preserves the caller's first-byte/total deadline."""
    plan = _request_plan(feature_key, json, base_url, api_key)
    for target in plan.targets:
        body = _payload_for_target(json, target, stream=True)
        target_headers = _headers_for_target(headers, target)
        try:
            with _stream_target_sync(
                client, target, body, target_headers, background,
                priority_headroom_usd, request_kwargs,
            ) as response:
                if response.status_code >= 400:
                    response.read()
                if target.provider != "openrouter" and _credit_exhausted(response):
                    continue
                yield _annotate_response(response, target, plan)
                return
        except httpx.RequestError:
            raise AiModelGatewayTransportError(f"{target.provider} transport outcome is unknown; stream was not resubmitted") from None
    raise AssertionError("OpenRouter terminal target was not processed")


@contextmanager
def _stream_target_sync(
    client: Any, target: _Target, body: dict[str, Any], headers: dict[str, str],
    background: bool, priority_headroom_usd: Any, request_kwargs: dict[str, Any],
) -> Iterator[httpx.Response]:
    if target.provider == "openrouter" and background:
        # Match the existing synchronous guard's lock -> credits -> submit order;
        # client.post would buffer the SSE and defeat the caller's total deadline.
        with _background_credit_lock():
            assert_openrouter_background_credit_available(
                client, base_url=target.base_url, api_key=target.api_key,
                priority_headroom_usd=priority_headroom_usd,
            )
            with client.stream("POST", f"{target.base_url}/chat/completions", headers=headers, json=body, **request_kwargs) as response:
                yield response
        return
    with client.stream("POST", f"{target.base_url}/chat/completions", headers=headers, json=body, **request_kwargs) as response:
        yield response


@asynccontextmanager
async def stream_model_chat_completion_async(
    client: Any, *, feature_key: str, base_url: str, api_key: str,
    headers: dict[str, str], json: dict[str, Any],
    priority_headroom_usd: Any | None = None, background: bool = True,
    **request_kwargs: Any,
) -> AsyncIterator[httpx.Response]:
    plan = _request_plan(feature_key, json, base_url, api_key)
    for target in plan.targets:
        body = _payload_for_target(json, target, stream=True)
        target_headers = _headers_for_target(headers, target)
        try:
            async with _stream_target(
                client, target, body, target_headers, background,
                priority_headroom_usd, request_kwargs,
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                if target.provider != "openrouter" and _credit_exhausted(response):
                    continue
                # Nothing after this yield can advance the account/provider loop.
                yield _annotate_response(response, target, plan)
                return
        except httpx.RequestError:
            raise AiModelGatewayTransportError(f"{target.provider} transport outcome is unknown; stream was not resubmitted") from None
    raise AssertionError("OpenRouter terminal target was not processed")


@asynccontextmanager
async def _stream_target(
    client: Any, target: _Target, body: dict[str, Any], headers: dict[str, str],
    background: bool, priority_headroom_usd: Any, request_kwargs: dict[str, Any],
) -> AsyncIterator[httpx.Response]:
    if target.provider == "openrouter" and background:
        async with openrouter_background_credit_reservation_async(
            client, base_url=target.base_url, api_key=target.api_key,
            priority_headroom_usd=priority_headroom_usd,
        ):
            async with client.stream("POST", f"{target.base_url}/chat/completions", headers=headers, json=body, **request_kwargs) as response:
                yield response
        return
    async with client.stream("POST", f"{target.base_url}/chat/completions", headers=headers, json=body, **request_kwargs) as response:
        yield response
