from __future__ import annotations

from typing import Any

from app.services.websochat.websochat_contracts import (
    WebsochatModel,
    WebsochatResponsePlan,
    WebsochatRoute,
    WebsochatScopeState,
    WebsochatTone,
)
from app.services.websochat.websochat_game_memory import WEBSOCHAT_ALLOWED_GAME_MODES


def _resolve_websochat_response_route(
    *,
    normalized_memory: dict[str, Any],
    rp_context: dict[str, Any] | None,
) -> WebsochatRoute:
    active_mode = str(normalized_memory.get("active_mode") or "").strip().lower()
    if active_mode in WEBSOCHAT_ALLOWED_GAME_MODES:
        return "game"
    if rp_context:
        return "rp"
    return "qa"


def _build_websochat_rp_plan(
    *,
    rp_context: dict[str, Any],
    gemini_enabled: bool,
) -> WebsochatResponsePlan:
    rp_mode = str(rp_context.get("rp_mode") or "").strip().lower() or "free"
    return {
        "route": "rp",
        "answer_mode": "direct",
        "tone": "playful",
        "route_mode": f"rp:{rp_mode}",
        "preferred_model": "gemini" if gemini_enabled else "haiku",
        "intent": "playful",
    }


def _build_websochat_qa_plan(
    *,
    intent: str,
    needs_creative: bool,
    resolved_mode: str,
    gemini_enabled: bool,
    scope_state: WebsochatScopeState = "known",
) -> WebsochatResponsePlan:
    tone: WebsochatTone = "playful" if intent in {"playful", "self_insert", "simulation"} else "analytical"
    preferred_model: WebsochatModel = "gemini" if gemini_enabled and needs_creative else "haiku"
    return {
        "route": "qa",
        "answer_mode": "concierge" if scope_state == "none" else "direct",
        "tone": tone,
        "route_mode": "qa:concierge" if scope_state == "none" else resolved_mode,
        "preferred_model": preferred_model,
        "intent": "concierge" if scope_state == "none" else intent,
    }
