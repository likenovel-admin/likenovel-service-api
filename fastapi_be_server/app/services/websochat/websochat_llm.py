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
WEBSOCHAT_QA_TEMPERATURE = 0.3
WEBSOCHAT_RP_TEMPERATURE = 0.5
WEBSOCHAT_CREATIVE_TEMPERATURE = 0.7


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


async def _call_websochat_gemini_stream(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
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
    async with httpx.AsyncClient(timeout=WEBSOCHAT_GEMINI_TIMEOUT_SECONDS) as client:
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
                logger.error("Gemini streamGenerateContent API error: %s %s", response.status_code, error_text)
                raise CustomResponseException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    message="AI 서비스 호출에 실패했습니다.",
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
) -> str:
    if not settings.GEMINI_API_KEY:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message="Gemini AI 서비스가 설정되지 않았습니다.",
        )

    if is_websochat_stream_enabled():
        try:
            return await _call_websochat_gemini_stream(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
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

    async with httpx.AsyncClient(timeout=WEBSOCHAT_GEMINI_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.WEBSOCHAT_GEMINI_MODEL}:generateContent",
            headers={
                "content-type": "application/json",
                "x-goog-api-key": settings.GEMINI_API_KEY,
            },
            json=payload,
        )

    if response.status_code != 200:
        logger.error("Gemini generateContent API error: %s %s", response.status_code, response.text)
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message="AI 서비스 호출에 실패했습니다.",
        )

    reply = extract_websochat_gemini_text(response.json())
    if not reply:
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message="AI 서비스 호출에 실패했습니다.",
        )
    return reply
