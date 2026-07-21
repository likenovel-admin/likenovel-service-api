from __future__ import annotations

import json
import logging
import re
from time import monotonic
from typing import Any

import httpx
from fastapi import status

from app.const import settings
from app.exceptions import CustomResponseException
from app.services.websochat.websochat_stream import emit_websochat_stream_delta, is_websochat_stream_enabled
from app.services.websochat.websochat_model_catalog import (
    WEBSOCHAT_DEFAULT_MODEL_KEY,
    WebsochatThinkingLevel,
    get_websochat_model_spec,
)

logger = logging.getLogger(__name__)

WEBSOCHAT_REPLY_MAX_TOKENS = 3072
WEBSOCHAT_GEMINI_TIMEOUT_SECONDS = 35.0
WEBSOCHAT_LONG_GENERATION_TIMEOUT_SECONDS = 180.0
WEBSOCHAT_QA_TEMPERATURE = 0.3
WEBSOCHAT_RP_TEMPERATURE = 0.5
WEBSOCHAT_CREATIVE_TEMPERATURE = 0.7
WEBSOCHAT_AI_PROVIDER_UNAVAILABLE_MESSAGE = "AI 답변을 불러오지 못했어요. 잠시 후 다시 시도해 주세요."
WEBSOCHAT_AI_PROVIDER_LIMITED_MESSAGE = "지금은 AI 생성 요청이 많아 답변을 완성하지 못했어요. 잠시 후 다시 시도해 주세요."
WEBSOCHAT_AI_PROVIDER_AUTH_MESSAGE = "AI 생성 설정을 확인하는 중이에요. 잠시 후 다시 시도해 주세요."
WEBSOCHAT_AI_PROVIDER_TIMEOUT_MESSAGE = "생성 시간이 길어져 답변을 마치지 못했어요. 조금 뒤 다시 시도해 주세요."


def to_websochat_gemini_contents(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    for message in messages:
        text_value = str(message.get("content") or "").strip()
        if not text_value:
            continue
        role = "model" if str(message.get("role") or "").strip().lower() == "assistant" else "user"
        contents.append(
            {
                "role": role,
                "parts": [{"text": text_value}],
            }
        )
    return contents


def to_websochat_openrouter_messages(
    system_prompt: str,
    messages: list[dict[str, Any]],
) -> list[dict[str, str]]:
    converted: list[dict[str, str]] = []
    if str(system_prompt or "").strip():
        converted.append({"role": "system", "content": str(system_prompt).strip()})
    for message in messages:
        role_value = str(message.get("role") or "").strip().lower()
        role = "assistant" if role_value in {"assistant", "model"} else "user"
        content = str(message.get("content") or "").strip()
        if not content:
            content = "\n".join(
                str(part.get("text") or "").strip()
                for part in list(message.get("parts") or [])
                if isinstance(part, dict) and str(part.get("text") or "").strip()
            ).strip()
        if content:
            converted.append({"role": role, "content": content})
    return converted


def _to_websochat_generic_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, str]]:
    converted = to_websochat_openrouter_messages("", messages)
    return [message for message in converted if message["role"] != "system"]


def sanitize_websochat_model_text(text: str) -> str:
    text_value = str(text or "")
    if not text_value:
        return text_value
    text_value = text_value.replace("\r\n", "\n").replace("\r", "\n")
    text_value = re.sub(r"[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]", "", text_value)
    text_value = re.sub(r"[\u200B-\u200D\uFEFF\uFFFD\u2D30-\u2D7F]", "", text_value)
    text_value = re.sub(r"([.!?。！？])([가-힣A-Za-z0-9])", r"\1 \2", text_value)
    text_value = re.sub(r"(?<=[.!?。！？])([\"”’])([가-힣A-Za-z0-9])", r"\1 \2", text_value)
    lines = [re.sub(r"[ \t]{2,}", " ", line).rstrip() for line in text_value.split("\n")]
    return "\n".join(lines).strip()


def extract_websochat_gemini_text(response_json: dict[str, Any]) -> str:
    texts: list[str] = []
    for candidate in response_json.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text_value = sanitize_websochat_model_text(str(part.get("text") or ""))
            if text_value:
                texts.append(text_value)
    return sanitize_websochat_model_text("\n".join(texts))


def _compute_websochat_stream_delta(accumulated: str, current_text: str) -> str:
    if not current_text:
        return ""
    if not accumulated:
        return current_text
    if current_text.startswith(accumulated):
        return current_text[len(accumulated) :]
    if accumulated.endswith(current_text):
        return ""
    return current_text


def _classify_websochat_provider_error(status_code: int, error_text: Any) -> tuple[str, str]:
    normalized = str(error_text or "").lower()
    is_limited = (
        status_code in {402, 429}
        or "quota" in normalized
        or "rate limit" in normalized
        or "rate_limit" in normalized
        or "resource_exhausted" in normalized
        or "credit" in normalized
        or "billing" in normalized
    )
    if is_limited:
        return "AI_PROVIDER_LIMITED", WEBSOCHAT_AI_PROVIDER_LIMITED_MESSAGE
    if status_code in {401, 403}:
        return "AI_PROVIDER_AUTH_FAILED", WEBSOCHAT_AI_PROVIDER_AUTH_MESSAGE
    return "AI_PROVIDER_UNAVAILABLE", WEBSOCHAT_AI_PROVIDER_UNAVAILABLE_MESSAGE


def _raise_websochat_provider_error(
    status_code: int,
    error_text: Any,
    *,
    operation: str,
    provider: str = "Gemini",
) -> None:
    code, message = _classify_websochat_provider_error(status_code, error_text)
    logger.error(
        "%s %s API error: status=%s code=%s body=%s",
        provider,
        operation,
        status_code,
        code,
        error_text,
    )
    raise CustomResponseException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        code=code,
        message=message,
    )


def _raise_websochat_provider_timeout(
    *,
    operation: str,
    provider: str = "Gemini",
) -> None:
    logger.exception("%s %s API timeout", provider, operation)
    raise CustomResponseException(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        code="AI_PROVIDER_TIMEOUT",
        message=WEBSOCHAT_AI_PROVIDER_TIMEOUT_MESSAGE,
    )


def _log_websochat_gemini_usage(
    *,
    operation: str,
    response_json: dict[str, Any],
    elapsed_seconds: float,
    thinking_level: WebsochatThinkingLevel,
) -> None:
    usage = response_json.get("usageMetadata")
    if not isinstance(usage, dict):
        return
    logger.info(
        "websochat gemini_usage operation=%s thinking_level=%s elapsed_ms=%s prompt_tokens=%s candidate_tokens=%s thoughts_tokens=%s total_tokens=%s",
        operation,
        thinking_level,
        max(int(elapsed_seconds * 1000), 0),
        int(usage.get("promptTokenCount") or 0),
        int(usage.get("candidatesTokenCount") or 0),
        int(usage.get("thoughtsTokenCount") or 0),
        int(usage.get("totalTokenCount") or 0),
    )


def _extract_websochat_openrouter_text(response_json: dict[str, Any]) -> str:
    choices = response_json.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        content = "\n".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict)
        )
    return sanitize_websochat_model_text(str(content or ""))


def _log_websochat_openrouter_usage(
    *,
    operation: str,
    response_json: dict[str, Any],
    elapsed_seconds: float,
    model: str,
) -> None:
    usage = response_json.get("usage")
    if not isinstance(usage, dict):
        return
    logger.info(
        "websochat openrouter_usage operation=%s model=%s elapsed_ms=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
        operation,
        model,
        max(int(elapsed_seconds * 1000), 0),
        int(usage.get("prompt_tokens") or 0),
        int(usage.get("completion_tokens") or 0),
        int(usage.get("total_tokens") or 0),
    )


def _raise_websochat_openrouter_event_error(error: Any, *, operation: str) -> None:
    payload = error if isinstance(error, dict) else {"message": str(error or "")}
    try:
        status_code = int(payload.get("code") or 502)
    except (TypeError, ValueError):
        status_code = 502
    _raise_websochat_provider_error(
        status_code,
        payload,
        operation=operation,
        provider="OpenRouter",
    )


async def _call_websochat_openrouter_stream(
    *,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    timeout_seconds: float,
    stream_state: dict[str, bool],
) -> str:
    payload = {
        "model": model,
        "messages": to_websochat_openrouter_messages(system_prompt, messages),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    accumulated = ""
    latest_usage_event: dict[str, Any] = {}
    started_at = monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            async with client.stream(
                "POST",
                f"{settings.OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "X-Title": "LikeNovel Websochat",
                },
                json=payload,
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    _raise_websochat_provider_error(
                        response.status_code,
                        error_text,
                        operation="chat/completions stream",
                        provider="OpenRouter",
                    )
                async for raw_line in response.aiter_lines():
                    line = str(raw_line or "").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload_text = line[5:].strip()
                    if not payload_text or payload_text == "[DONE]":
                        continue
                    try:
                        event_json = json.loads(payload_text)
                    except json.JSONDecodeError:
                        continue
                    if event_json.get("error"):
                        _raise_websochat_openrouter_event_error(
                            event_json["error"],
                            operation="chat/completions stream",
                        )
                    if isinstance(event_json.get("usage"), dict):
                        latest_usage_event = event_json
                    choices = event_json.get("choices") or []
                    if not choices or not isinstance(choices[0], dict):
                        continue
                    delta = choices[0].get("delta") or {}
                    chunk = str(delta.get("content") or "")
                    if chunk:
                        stream_state["emitted"] = True
                        await emit_websochat_stream_delta(chunk)
                        accumulated += chunk
    except CustomResponseException:
        raise
    except httpx.TimeoutException:
        _raise_websochat_provider_timeout(
            operation="chat/completions stream",
            provider="OpenRouter",
        )
    except httpx.HTTPError:
        logger.exception("OpenRouter chat/completions stream HTTP error")
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="AI_PROVIDER_UNAVAILABLE",
            message=WEBSOCHAT_AI_PROVIDER_UNAVAILABLE_MESSAGE,
        )
    _log_websochat_openrouter_usage(
        operation="chat/completions stream",
        response_json=latest_usage_event,
        elapsed_seconds=monotonic() - started_at,
        model=model,
    )
    reply = sanitize_websochat_model_text(accumulated)
    if not reply:
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="AI_PROVIDER_EMPTY_RESPONSE",
            message=WEBSOCHAT_AI_PROVIDER_UNAVAILABLE_MESSAGE,
        )
    return reply


async def call_websochat_openrouter(
    *,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    max_tokens: int = WEBSOCHAT_REPLY_MAX_TOKENS,
    temperature: float = WEBSOCHAT_QA_TEMPERATURE,
    stream: bool | None = None,
    timeout_seconds: float = WEBSOCHAT_GEMINI_TIMEOUT_SECONDS,
) -> str:
    if not settings.OPENROUTER_API_KEY:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AI_PROVIDER_NOT_CONFIGURED",
            message=WEBSOCHAT_AI_PROVIDER_AUTH_MESSAGE,
        )
    if ":free" in str(model or "").lower():
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AI_PROVIDER_NOT_CONFIGURED",
            message=WEBSOCHAT_AI_PROVIDER_AUTH_MESSAGE,
        )

    stream_enabled = is_websochat_stream_enabled() if stream is None else stream
    if stream_enabled:
        stream_state = {"emitted": False}
        try:
            return await _call_websochat_openrouter_stream(
                model=model,
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
                stream_state=stream_state,
            )
        except CustomResponseException as exc:
            if stream_state["emitted"] or exc.code != "AI_PROVIDER_EMPTY_RESPONSE":
                raise
            logger.warning(
                "OpenRouter stream returned no content; retrying same provider nonstream"
            )
        except Exception:
            if stream_state["emitted"]:
                logger.exception("OpenRouter stream failed after content delta")
                raise CustomResponseException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    code="AI_PROVIDER_UNAVAILABLE",
                    message=WEBSOCHAT_AI_PROVIDER_UNAVAILABLE_MESSAGE,
                )
            logger.exception(
                "OpenRouter stream failed before content; retrying same provider nonstream"
            )

    payload = {
        "model": model,
        "messages": to_websochat_openrouter_messages(system_prompt, messages),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    started_at = monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"{settings.OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "X-Title": "LikeNovel Websochat",
                },
                json=payload,
            )
    except httpx.TimeoutException:
        _raise_websochat_provider_timeout(
            operation="chat/completions",
            provider="OpenRouter",
        )
    except httpx.HTTPError:
        logger.exception("OpenRouter chat/completions HTTP error")
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="AI_PROVIDER_UNAVAILABLE",
            message=WEBSOCHAT_AI_PROVIDER_UNAVAILABLE_MESSAGE,
        )
    if response.status_code != 200:
        _raise_websochat_provider_error(
            response.status_code,
            response.text,
            operation="chat/completions",
            provider="OpenRouter",
        )
    response_json = response.json()
    if response_json.get("error"):
        _raise_websochat_openrouter_event_error(
            response_json["error"],
            operation="chat/completions",
        )
    _log_websochat_openrouter_usage(
        operation="chat/completions",
        response_json=response_json,
        elapsed_seconds=monotonic() - started_at,
        model=model,
    )
    reply = _extract_websochat_openrouter_text(response_json)
    if not reply:
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="AI_PROVIDER_EMPTY_RESPONSE",
            message=WEBSOCHAT_AI_PROVIDER_UNAVAILABLE_MESSAGE,
        )
    return reply


async def _call_websochat_gemini_stream(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    thinking_level: WebsochatThinkingLevel,
    timeout_seconds: float = WEBSOCHAT_GEMINI_TIMEOUT_SECONDS,
) -> str:
    payload: dict[str, Any] = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}],
        },
        "contents": messages,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"thinkingLevel": thinking_level},
        },
    }
    accumulated = ""
    latest_usage_event: dict[str, Any] = {}
    started_at = monotonic()
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        async with client.stream(
            "POST",
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.WEBSOCHAT_GEMINI_MODEL}:streamGenerateContent?alt=sse",
            headers={
                "content-type": "application/json",
                "x-goog-api-key": settings.GEMINI_API_KEY,
            },
            json=payload,
        ) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                _raise_websochat_provider_error(
                    response.status_code,
                    error_text,
                    operation="streamGenerateContent",
                )
            async for raw_line in response.aiter_lines():
                line = str(raw_line or "").strip()
                if not line or not line.startswith("data:"):
                    continue
                payload_text = line[5:].strip()
                if not payload_text:
                    continue
                try:
                    event_json = json.loads(payload_text)
                except json.JSONDecodeError:
                    continue
                if isinstance(event_json.get("usageMetadata"), dict):
                    latest_usage_event = event_json
                current_text = extract_websochat_gemini_text(event_json)
                delta = _compute_websochat_stream_delta(accumulated, current_text)
                if delta:
                    await emit_websochat_stream_delta(delta)
                    accumulated += delta
    _log_websochat_gemini_usage(
        operation="streamGenerateContent",
        response_json=latest_usage_event,
        elapsed_seconds=monotonic() - started_at,
        thinking_level=thinking_level,
    )
    return accumulated.strip()


async def call_websochat_gemini(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    max_tokens: int = WEBSOCHAT_REPLY_MAX_TOKENS,
    temperature: float = WEBSOCHAT_QA_TEMPERATURE,
    stream: bool | None = None,
    timeout_seconds: float = WEBSOCHAT_GEMINI_TIMEOUT_SECONDS,
    thinking_level: WebsochatThinkingLevel = "minimal",
) -> str:
    if not settings.GEMINI_API_KEY:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AI_PROVIDER_NOT_CONFIGURED",
            message=WEBSOCHAT_AI_PROVIDER_AUTH_MESSAGE,
        )

    stream_enabled = is_websochat_stream_enabled() if stream is None else stream
    if stream_enabled:
        try:
            return await _call_websochat_gemini_stream(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                thinking_level=thinking_level,
                timeout_seconds=timeout_seconds,
            )
        except CustomResponseException:
            raise
        except Exception:
            logger.exception("Gemini streamGenerateContent failed; falling back to generateContent")

    payload: dict[str, Any] = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}],
        },
        "contents": messages,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"thinkingLevel": thinking_level},
        },
    }

    started_at = monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{settings.WEBSOCHAT_GEMINI_MODEL}:generateContent",
                headers={
                    "content-type": "application/json",
                    "x-goog-api-key": settings.GEMINI_API_KEY,
                },
                json=payload,
            )
    except httpx.TimeoutException:
        _raise_websochat_provider_timeout(operation="generateContent")
    except httpx.HTTPError:
        logger.exception("Gemini generateContent API HTTP error")
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="AI_PROVIDER_UNAVAILABLE",
            message=WEBSOCHAT_AI_PROVIDER_UNAVAILABLE_MESSAGE,
        )

    if response.status_code != 200:
        _raise_websochat_provider_error(
            response.status_code,
            response.text,
            operation="generateContent",
        )

    response_json = response.json()
    _log_websochat_gemini_usage(
        operation="generateContent",
        response_json=response_json,
        elapsed_seconds=monotonic() - started_at,
        thinking_level=thinking_level,
    )
    reply = extract_websochat_gemini_text(response_json)
    if not reply:
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="AI_PROVIDER_EMPTY_RESPONSE",
            message=WEBSOCHAT_AI_PROVIDER_UNAVAILABLE_MESSAGE,
        )
    return reply


async def call_websochat_model(
    *,
    model_key: object = WEBSOCHAT_DEFAULT_MODEL_KEY,
    system_prompt: str,
    messages: list[dict[str, Any]],
    max_tokens: int = WEBSOCHAT_REPLY_MAX_TOKENS,
    temperature: float = WEBSOCHAT_QA_TEMPERATURE,
    stream: bool | None = None,
    timeout_seconds: float = WEBSOCHAT_GEMINI_TIMEOUT_SECONDS,
) -> str:
    spec = get_websochat_model_spec(model_key)
    generic_messages = _to_websochat_generic_messages(messages)
    if spec.provider == "openrouter":
        return await call_websochat_openrouter(
            model=spec.provider_model,
            system_prompt=system_prompt,
            messages=generic_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=stream,
            timeout_seconds=timeout_seconds,
        )
    return await call_websochat_gemini(
        system_prompt=system_prompt,
        messages=to_websochat_gemini_contents(generic_messages),
        max_tokens=max_tokens,
        temperature=temperature,
        stream=stream,
        timeout_seconds=timeout_seconds,
        thinking_level=spec.thinking_level or "minimal",
    )
