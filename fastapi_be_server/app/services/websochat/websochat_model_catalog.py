from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from app.const import settings


WebsochatModelKey = Literal["speed", "balance", "deep"]
WebsochatThinkingLevel = Literal["minimal", "medium", "high"]
WebsochatModelProvider = Literal["gemini", "openrouter"]

@dataclass(frozen=True)
class WebsochatModelSpec:
    model_key: WebsochatModelKey
    display_name: str
    provider: WebsochatModelProvider
    provider_model: str
    cash_cost: int
    character_chat_daily_free_limit: int
    thinking_level: WebsochatThinkingLevel | None
    # Usage-log label family. It names the model family, not the transport, so
    # daily free limits, billing, and stats keep counting "gemini:<tier>" rows.
    model_family: str = "gemini"


WEBSOCHAT_DEFAULT_MODEL_KEY: WebsochatModelKey = "speed"
WEBSOCHAT_MODEL_CATALOG: tuple[WebsochatModelSpec, ...] = (
    WebsochatModelSpec(
        "speed",
        "스피드",
        "openrouter",
        settings.WEBSOCHAT_OPENROUTER_MODEL,
        20,
        10,
        "minimal",
    ),
    WebsochatModelSpec(
        "balance",
        "밸런스",
        "openrouter",
        settings.WEBSOCHAT_OPENROUTER_MODEL,
        25,
        5,
        "medium",
    ),
    WebsochatModelSpec(
        "deep",
        "딥",
        "openrouter",
        settings.WEBSOCHAT_OPENROUTER_MODEL,
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
    return f"{spec.model_family}:{spec.model_key}"


def is_websochat_model_provider_configured(model_key: object) -> bool:
    spec = get_websochat_model_spec(model_key)
    if spec.provider == "openrouter":
        return bool(settings.OPENROUTER_API_KEY)
    return bool(settings.GEMINI_API_KEY)
