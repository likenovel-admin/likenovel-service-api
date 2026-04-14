from __future__ import annotations

from typing import Any, Literal, TypedDict

WebsochatRoute = Literal["game", "rp", "qa"]
WebsochatAnswerMode = Literal["direct", "guide", "concierge"]
WebsochatTone = Literal["playful", "analytical"]
WebsochatModel = Literal["gemini", "haiku"]
WebsochatGameReplyRoute = Literal["guide", "ideal_worldcup", "vs_disabled"]
WebsochatScopeState = Literal["unknown", "none", "known"]
WebsochatStarterModeKey = Literal["qa", "rp", "ideal_worldcup"]
WebsochatQaActionKey = Literal["predict", "next_episode_write"]


class WebsochatResolvedScope(TypedDict):
    read_episode_to: int
    latest_episode_no: int


class WebsochatEvidenceBundle(TypedDict):
    resolved_scope: WebsochatResolvedScope
    product_row: dict[str, Any]
    scope_context: dict[str, Any] | None


class WebsochatResponsePlan(TypedDict):
    route: WebsochatRoute
    answer_mode: WebsochatAnswerMode
    tone: WebsochatTone
    route_mode: str
    preferred_model: WebsochatModel
    intent: str


class WebsochatGameDispatchPlan(TypedDict):
    route: WebsochatGameReplyRoute
    model_used: str
    route_mode: str
    intent: str


class WebsochatQaExecutionResult(TypedDict):
    reply: str
    model_used: str
    fallback_used: bool
    route_mode: str
    intent: str
    referenced_episode_nos: list[int]


class WebsochatPromptReadScopeDecision(TypedDict):
    read_episode_to: int | None
    scope_state: WebsochatScopeState
    is_scope_only: bool


class WebsochatReasonCard(TypedDict):
    title: str
    description: str


class WebsochatStarterAction(TypedDict):
    label: str
    prompt: str
    modeKey: WebsochatStarterModeKey | None
    qaActionKey: WebsochatQaActionKey | None
    cashCost: int | None


class WebsochatCtaCard(TypedDict):
    type: Literal["product_detail"]
    label: str
    product_id: int
