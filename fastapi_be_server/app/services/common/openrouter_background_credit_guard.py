from __future__ import annotations

import asyncio
import fcntl
import os
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, AsyncIterator, Iterator

import httpx


DEFAULT_BACKGROUND_RESERVE_USD = Decimal("2.00")
DEFAULT_BACKGROUND_IN_FLIGHT_BUFFER_USD = Decimal("1.00")
DEFAULT_CREDIT_LOOKUP_TIMEOUT_SECONDS = 10.0
DEFAULT_CREDIT_LOCK_PATH = "/tmp/likenovel-openrouter-background-credit.lock"


class OpenRouterBackgroundCreditGuardError(RuntimeError):
    pass


class OpenRouterBackgroundCreditLookupError(OpenRouterBackgroundCreditGuardError):
    pass


class OpenRouterBackgroundCreditReserveError(OpenRouterBackgroundCreditGuardError):
    pass


@dataclass(frozen=True)
class OpenRouterBackgroundCreditStatus:
    remaining_usd: Decimal
    minimum_required_usd: Decimal


def _read_non_negative_decimal_env(name: str, default: Decimal) -> Decimal:
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = Decimal(raw_value)
    except InvalidOperation as exc:
        raise OpenRouterBackgroundCreditLookupError(f"invalid {name}") from exc
    if not value.is_finite() or value < 0:
        raise OpenRouterBackgroundCreditLookupError(f"invalid {name}")
    return value


def _minimum_required_usd() -> Decimal:
    reserve = _read_non_negative_decimal_env(
        "OPENROUTER_BACKGROUND_RESERVE_USD",
        DEFAULT_BACKGROUND_RESERVE_USD,
    )
    in_flight_buffer = _read_non_negative_decimal_env(
        "OPENROUTER_BACKGROUND_IN_FLIGHT_BUFFER_USD",
        DEFAULT_BACKGROUND_IN_FLIGHT_BUFFER_USD,
    )
    return reserve + in_flight_buffer


def _credit_status_from_payload(payload: Any) -> OpenRouterBackgroundCreditStatus:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise OpenRouterBackgroundCreditLookupError("OpenRouter credits response is missing data")
    try:
        total_credits = Decimal(str(data["total_credits"]))
        total_usage = Decimal(str(data["total_usage"]))
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise OpenRouterBackgroundCreditLookupError("OpenRouter credits response is invalid") from exc
    if not total_credits.is_finite() or not total_usage.is_finite():
        raise OpenRouterBackgroundCreditLookupError("OpenRouter credits response is invalid")

    status = OpenRouterBackgroundCreditStatus(
        remaining_usd=total_credits - total_usage,
        minimum_required_usd=_minimum_required_usd(),
    )
    if status.remaining_usd < status.minimum_required_usd:
        raise OpenRouterBackgroundCreditReserveError(
            "OpenRouter background credit reserve blocked: "
            f"remaining=${status.remaining_usd:.6f}, "
            f"required=${status.minimum_required_usd:.2f}"
        )
    return status


def _credit_headers(api_key: str) -> dict[str, str]:
    if not api_key.strip():
        raise OpenRouterBackgroundCreditLookupError("OPENROUTER_API_KEY is not configured")
    return {"Authorization": f"Bearer {api_key.strip()}"}


def assert_openrouter_background_credit_available(
    client: Any,
    *,
    base_url: str,
    api_key: str,
) -> OpenRouterBackgroundCreditStatus:
    try:
        response = client.get(
            f"{base_url.rstrip('/')}/credits",
            headers=_credit_headers(api_key),
            timeout=DEFAULT_CREDIT_LOOKUP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except OpenRouterBackgroundCreditGuardError:
        raise
    except Exception as exc:
        status_code = int(getattr(response, "status_code", 0) or 0) if "response" in locals() else 0
        suffix = f" (status={status_code})" if status_code else ""
        raise OpenRouterBackgroundCreditLookupError(
            f"OpenRouter credits lookup failed{suffix}"
        ) from exc
    return _credit_status_from_payload(payload)


async def assert_openrouter_background_credit_available_async(
    client: Any,
    *,
    base_url: str,
    api_key: str,
) -> OpenRouterBackgroundCreditStatus:
    try:
        response = await client.get(
            f"{base_url.rstrip('/')}/credits",
            headers=_credit_headers(api_key),
            timeout=DEFAULT_CREDIT_LOOKUP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except OpenRouterBackgroundCreditGuardError:
        raise
    except Exception as exc:
        status_code = int(getattr(response, "status_code", 0) or 0) if "response" in locals() else 0
        suffix = f" (status={status_code})" if status_code else ""
        raise OpenRouterBackgroundCreditLookupError(
            f"OpenRouter credits lookup failed{suffix}"
        ) from exc
    return _credit_status_from_payload(payload)


def _credit_lock_path() -> str:
    return os.getenv(
        "OPENROUTER_BACKGROUND_CREDIT_LOCK_PATH",
        DEFAULT_CREDIT_LOCK_PATH,
    ).strip() or DEFAULT_CREDIT_LOCK_PATH


@contextmanager
def _background_credit_lock() -> Iterator[None]:
    lock_fd = os.open(_credit_lock_path(), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


@asynccontextmanager
async def _background_credit_lock_async() -> AsyncIterator[None]:
    lock_fd = os.open(_credit_lock_path(), os.O_CREAT | os.O_RDWR, 0o600)
    lock_acquired = False
    try:
        while not lock_acquired:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_acquired = True
            except BlockingIOError:
                await asyncio.sleep(0.1)
        yield
    finally:
        if lock_acquired:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def post_openrouter_background_chat_completion(
    client: Any,
    *,
    base_url: str,
    api_key: str,
    headers: dict[str, str],
    json: dict[str, Any],
    **request_kwargs: Any,
) -> httpx.Response:
    with _background_credit_lock():
        assert_openrouter_background_credit_available(
            client,
            base_url=base_url,
            api_key=api_key,
        )
        return client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=json,
            **request_kwargs,
        )


async def post_openrouter_background_chat_completion_async(
    client: Any,
    *,
    base_url: str,
    api_key: str,
    headers: dict[str, str],
    json: dict[str, Any],
    **request_kwargs: Any,
) -> httpx.Response:
    async with _background_credit_lock_async():
        await assert_openrouter_background_credit_available_async(
            client,
            base_url=base_url,
            api_key=api_key,
        )
        return await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=json,
            **request_kwargs,
        )
