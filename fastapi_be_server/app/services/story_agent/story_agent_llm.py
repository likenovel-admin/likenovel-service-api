from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import status

from app.const import settings
from app.exceptions import CustomResponseException

logger = logging.getLogger(__name__)

STORY_AGENT_REPLY_MAX_TOKENS = 3072
STORY_AGENT_GEMINI_TIMEOUT_SECONDS = 35.0


def to_story_agent_gemini_contents(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
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


def extract_story_agent_gemini_text(response_json: dict[str, Any]) -> str:
    texts: list[str] = []
    for candidate in response_json.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text_value = str(part.get("text") or "").strip()
            if text_value:
                texts.append(text_value)
    return "\n".join(texts).strip()


async def call_story_agent_gemini(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    max_tokens: int = STORY_AGENT_REPLY_MAX_TOKENS,
) -> str:
    if not settings.GEMINI_API_KEY:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message="Gemini AI 서비스가 설정되지 않았습니다.",
        )

    payload: dict[str, Any] = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}],
        },
        "contents": messages,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": max_tokens,
        },
    }

    async with httpx.AsyncClient(timeout=STORY_AGENT_GEMINI_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.STORY_AGENT_GEMINI_MODEL}:generateContent",
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

    reply = extract_story_agent_gemini_text(response.json())
    if not reply:
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message="AI 서비스 호출에 실패했습니다.",
        )
    return reply
