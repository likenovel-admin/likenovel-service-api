from __future__ import annotations

from typing import Any, Literal, TypedDict

StoryAgentRoute = Literal["game", "rp", "qa"]
StoryAgentAnswerMode = Literal["direct", "guide", "concierge"]
StoryAgentTone = Literal["playful", "analytical"]
StoryAgentModel = Literal["gemini", "haiku"]
StoryAgentGameReplyRoute = Literal["guide", "ideal_worldcup", "vs_disabled"]
StoryAgentScopeState = Literal["unknown", "none", "known"]


class StoryAgentResolvedScope(TypedDict):
    read_episode_to: int
    latest_episode_no: int


class StoryAgentEvidenceBundle(TypedDict):
    resolved_scope: StoryAgentResolvedScope
    product_row: dict[str, Any]
    scope_context: dict[str, Any] | None


class StoryAgentResponsePlan(TypedDict):
    route: StoryAgentRoute
    answer_mode: StoryAgentAnswerMode
    tone: StoryAgentTone
    route_mode: str
    preferred_model: StoryAgentModel
    intent: str


class StoryAgentGameDispatchPlan(TypedDict):
    route: StoryAgentGameReplyRoute
    model_used: str
    route_mode: str
    intent: str


class StoryAgentQaExecutionResult(TypedDict):
    reply: str
    model_used: str
    fallback_used: bool
    route_mode: str
    intent: str


class StoryAgentPromptReadScopeDecision(TypedDict):
    read_episode_to: int | None
    scope_state: StoryAgentScopeState
    is_scope_only: bool


class StoryAgentReasonCard(TypedDict):
    title: str
    description: str


class StoryAgentStarterAction(TypedDict):
    label: str
    prompt: str


class StoryAgentCtaCard(TypedDict):
    type: Literal["product_detail"]
    label: str
    product_id: int
