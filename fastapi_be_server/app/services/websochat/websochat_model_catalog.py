from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from app.const import settings


WebsochatModelKey = Literal["speed", "balance", "deep"]
WebsochatThinkingLevel = Literal["minimal", "medium", "high"]
WebsochatModelProvider = Literal["gemini", "openrouter"]

WEBSOCHAT_BALANCE_OPENROUTER_MODEL = "google/gemma-4-31b-it"


@dataclass(frozen=True)
class WebsochatModelSpec:
    model_key: WebsochatModelKey
    display_name: str
    provider: WebsochatModelProvider
    provider_model: str
    cash_cost: int
    character_chat_daily_free_limit: int
    thinking_level: WebsochatThinkingLevel | None


WEBSOCHAT_DEFAULT_MODEL_KEY: WebsochatModelKey = "speed"
WEBSOCHAT_MODEL_CATALOG: tuple[WebsochatModelSpec, ...] = (
    WebsochatModelSpec(
        "speed",
        "스피드",
        "gemini",
        settings.WEBSOCHAT_GEMINI_MODEL,
        20,
        10,
        "minimal",
    ),
    WebsochatModelSpec(
        "balance",
        "밸런스",
        "openrouter",
        WEBSOCHAT_BALANCE_OPENROUTER_MODEL,
        25,
        5,
        None,
    ),
    WebsochatModelSpec(
        "deep",
        "딥",
        "gemini",
        settings.WEBSOCHAT_GEMINI_MODEL,
        35,
        1,
        "high",
    ),
)
WEBSOCHAT_MODEL_CATALOG_BY_KEY = {
    spec.model_key: spec for spec in WEBSOCHAT_MODEL_CATALOG
}


def normalize_websochat_model_key(value: object) -> WebsochatModelKey:
    normalized = str(value or "").strip().lower()
    if normalized in WEBSOCHAT_MODEL_CATALOG_BY_KEY:
        return cast(WebsochatModelKey, normalized)
    return WEBSOCHAT_DEFAULT_MODEL_KEY


def get_websochat_model_spec(model_key: object) -> WebsochatModelSpec:
    return WEBSOCHAT_MODEL_CATALOG_BY_KEY[normalize_websochat_model_key(model_key)]


def build_websochat_model_used(model_key: object) -> str:
    spec = get_websochat_model_spec(model_key)
    return f"{spec.provider}:{spec.model_key}"
