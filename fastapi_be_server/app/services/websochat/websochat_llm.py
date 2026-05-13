from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from fastapi import status

from app.const import settings
from app.exceptions import CustomResponseException
from app.services.websochat.websochat_stream import emit_websochat_stream_delta, is_websochat_stream_enabled

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


def extract_websochat_gemini_text(response_json: dict[str, Any]) -> str:
    texts: list[str] = []
    for candidate in response_json.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text_value = str(part.get("text") or "").strip()
            if text_value:
                texts.append(text_value)
    return "\n".join(texts).strip()


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
) -> None:
    code, message = _classify_websochat_provider_error(status_code, error_text)
    logger.error(
        "Gemini %s API error: status=%s code=%s body=%s",
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


def _raise_websochat_provider_timeout(*, operation: str) -> None:
    logger.exception("Gemini %s API timeout", operation)
    raise CustomResponseException(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        code="AI_PROVIDER_TIMEOUT",
        message=WEBSOCHAT_AI_PROVIDER_TIMEOUT_MESSAGE,
    )


async def _call_websochat_gemini_stream(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
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
        },
    }
    accumulated = ""
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
                current_text = extract_websochat_gemini_text(event_json)
                delta = _compute_websochat_stream_delta(accumulated, current_text)
                if delta:
                    await emit_websochat_stream_delta(delta)
                    accumulated += delta
    return accumulated.strip()


async def call_websochat_gemini(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    max_tokens: int = WEBSOCHAT_REPLY_MAX_TOKENS,
    temperature: float = WEBSOCHAT_QA_TEMPERATURE,
    timeout_seconds: float = WEBSOCHAT_GEMINI_TIMEOUT_SECONDS,
) -> str:
    if not settings.GEMINI_API_KEY:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="AI_PROVIDER_NOT_CONFIGURED",
            message=WEBSOCHAT_AI_PROVIDER_AUTH_MESSAGE,
        )

    if is_websochat_stream_enabled():
        try:
            return await _call_websochat_gemini_stream(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
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
        },
    }

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

    reply = extract_websochat_gemini_text(response.json())
    if not reply:
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="AI_PROVIDER_EMPTY_RESPONSE",
            message=WEBSOCHAT_AI_PROVIDER_UNAVAILABLE_MESSAGE,
        )
    return reply
