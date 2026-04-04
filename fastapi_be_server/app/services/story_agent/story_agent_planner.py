from __future__ import annotations

from typing import Any

from app.services.story_agent.story_agent_contracts import (
    StoryAgentModel,
    StoryAgentResponsePlan,
    StoryAgentRoute,
    StoryAgentScopeState,
    StoryAgentTone,
)
from app.services.story_agent.story_agent_game_memory import STORY_AGENT_ALLOWED_GAME_MODES


def _resolve_story_agent_response_route(
    *,
    normalized_memory: dict[str, Any],
    rp_context: dict[str, Any] | None,
) -> StoryAgentRoute:
    active_mode = str(normalized_memory.get("active_mode") or "").strip().lower()
    if active_mode in STORY_AGENT_ALLOWED_GAME_MODES:
        return "game"
    if rp_context:
        return "rp"
    return "qa"


def _build_story_agent_rp_plan(
    *,
    rp_context: dict[str, Any],
    gemini_enabled: bool,
) -> StoryAgentResponsePlan:
    rp_mode = str(rp_context.get("rp_mode") or "").strip().lower() or "free"
    return {
        "route": "rp",
        "answer_mode": "direct",
        "tone": "playful",
        "route_mode": f"rp:{rp_mode}",
        "preferred_model": "gemini" if gemini_enabled else "haiku",
        "intent": "playful",
    }


def _build_story_agent_qa_plan(
    *,
    intent: str,
    needs_creative: bool,
    resolved_mode: str,
    gemini_enabled: bool,
    scope_state: StoryAgentScopeState = "known",
) -> StoryAgentResponsePlan:
    tone: StoryAgentTone = "playful" if intent in {"playful", "self_insert", "simulation"} else "analytical"
    preferred_model: StoryAgentModel = "gemini" if gemini_enabled and needs_creative else "haiku"
    return {
        "route": "qa",
        "answer_mode": "concierge" if scope_state == "none" else "direct",
        "tone": tone,
        "route_mode": "qa:concierge" if scope_state == "none" else resolved_mode,
        "preferred_model": preferred_model,
        "intent": "concierge" if scope_state == "none" else intent,
    }
