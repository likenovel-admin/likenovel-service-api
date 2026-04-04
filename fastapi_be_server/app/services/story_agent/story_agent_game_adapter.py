from __future__ import annotations

import re
from typing import Any

from app.services.story_agent.story_agent_contracts import (
    StoryAgentGameDispatchPlan,
    StoryAgentGameReplyRoute,
)
from app.services.story_agent.story_agent_game_memory import (
    STORY_AGENT_ALLOWED_GAME_MODES,
    _merge_story_agent_session_memory,
    _normalize_story_agent_session_memory,
)

STORY_AGENT_EXIT_GAME_TOKENS = (
    "일반 모드로 돌아",
    "일반 모드로 가",
    "게임 말고",
    "월드컵 말고",
    "월드컵 그만",
    "그만할래",
    "그만할게",
    "작품 얘기로 돌아",
    "대화로 돌아",
)
STORY_AGENT_WORLDCUP_META_TOKENS = (
    "왜 이 둘",
    "왜 둘이",
    "왜 나왔",
    "왜 붙",
    "규칙",
    "몇강",
    "몇 명",
    "무슨 기준",
)


def is_story_agent_restart_prompt(user_prompt: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip()
    if not normalized:
        return False
    return any(token in normalized for token in ["다시", "새로", "리셋", "처음부터"])


def is_story_agent_resume_prompt(user_prompt: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip()
    if not normalized:
        return False
    return any(token in normalized for token in ["이어서", "계속", "이어", "다음"])


def is_story_agent_confirm_current_size_prompt(user_prompt: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip().lower()
    if not normalized:
        return False
    return normalized in {"1", "1번"} or any(
        token in normalized
        for token in ["지금 가능한 크기로", "그대로 진행", "2인 비교로", "결승으로", "4강으로", "8강으로"]
    )


def is_story_agent_worldcup_prompt(user_prompt: str) -> bool:
    normalized = re.sub(r"\s+", "", str(user_prompt or "")).strip().lower()
    if not normalized:
        return False
    return any(token in normalized for token in ["이상형월드컵", "이상형월드컵해줘", "월드컵"])


def is_story_agent_exit_game_prompt(user_prompt: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip().lower()
    if not normalized:
        return False
    return any(token in normalized for token in STORY_AGENT_EXIT_GAME_TOKENS)


def is_story_agent_worldcup_meta_prompt(user_prompt: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip().lower()
    if not normalized:
        return False
    return any(token in normalized for token in STORY_AGENT_WORLDCUP_META_TOKENS)


def infer_story_agent_game_gender_scope_from_prompt(user_prompt: str) -> str | None:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip().lower()
    compact = re.sub(r"\s+", "", normalized)
    if not normalized:
        return None
    if any(token in compact for token in ["남성버전", "남캐", "남자버전", "남성"]):
        return "male"
    if any(token in compact for token in ["여성버전", "여캐", "여자버전", "여성"]):
        return "female"
    if any(token in compact for token in ["섞어서", "혼합", "남녀", "믹스", "mixed"]):
        return "mixed"
    if normalized in {"1", "1번"}:
        return "male"
    if normalized in {"2", "2번"}:
        return "female"
    if normalized in {"3", "3번"}:
        return "mixed"
    return None


def infer_story_agent_worldcup_category_from_prompt(user_prompt: str) -> str | None:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip().lower()
    compact = re.sub(r"\s+", "", normalized)
    if not normalized:
        return None
    if any(token in compact for token in ["연애", "호감", "썸", "연애형"]):
        return "romance"
    if any(token in compact for token in ["데이트", "데이트상대", "같이나가", "같이놀"]):
        return "date"
    if any(token in compact for token in ["서사", "서사적", "캐릭터성", "꽂히는"]):
        return "narrative"
    if normalized in {"1", "1번"}:
        return "romance"
    if normalized in {"2", "2번"}:
        return "date"
    if normalized in {"3", "3번"}:
        return "narrative"
    return None


def apply_story_agent_implicit_game_inputs(
    *,
    session_memory: dict[str, Any],
    user_prompt: str,
    game_read_episode_to: int | None,
) -> dict[str, Any]:
    normalized = _normalize_story_agent_session_memory(session_memory)
    game_context = normalized.get("game_context") or {}
    active_mode = str(normalized.get("active_mode") or "").strip().lower()
    game_mode = str(game_context.get("mode") or "").strip().lower()

    if active_mode not in STORY_AGENT_ALLOWED_GAME_MODES and game_mode not in STORY_AGENT_ALLOWED_GAME_MODES:
        if not is_story_agent_worldcup_prompt(user_prompt):
            return normalized
        inferred_gender_scope = infer_story_agent_game_gender_scope_from_prompt(user_prompt)
        inferred_category = infer_story_agent_worldcup_category_from_prompt(user_prompt)
        return _merge_story_agent_session_memory(
            base_memory=normalized,
            rp_mode=None,
            active_character=None,
            scene_episode_no=None,
            game_mode="ideal_worldcup",
            game_gender_scope=inferred_gender_scope,
            game_category=inferred_category,
            game_read_episode_to=game_read_episode_to,
        )

    if game_mode != "ideal_worldcup":
        return normalized

    inferred_gender_scope = None
    inferred_category = None
    if not str(game_context.get("gender_scope") or "").strip().lower():
        inferred_gender_scope = infer_story_agent_game_gender_scope_from_prompt(user_prompt)
    elif not str(game_context.get("category") or "").strip().lower():
        inferred_category = infer_story_agent_worldcup_category_from_prompt(user_prompt)

    if not inferred_gender_scope and not inferred_category and not game_read_episode_to:
        return normalized

    return _merge_story_agent_session_memory(
        base_memory=normalized,
        rp_mode=None,
        active_character=None,
        scene_episode_no=None,
        game_mode="ideal_worldcup",
        game_gender_scope=inferred_gender_scope,
        game_category=inferred_category,
        game_read_episode_to=game_read_episode_to,
    )


def infer_story_agent_worldcup_requested_size_from_prompt(user_prompt: str) -> int | None:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip().lower()
    if not normalized:
        return None
    if "8강" in normalized:
        return 8
    if "4강" in normalized:
        return 4
    if any(token in normalized for token in ["2인 비교", "2인", "결승", "둘만", "둘 중"]):
        return 2
    return None


def resolve_story_agent_worldcup_followup(
    *,
    user_prompt: str,
) -> dict[str, Any]:
    return {
        "exit_requested": is_story_agent_exit_game_prompt(user_prompt),
        "restart_requested": is_story_agent_restart_prompt(user_prompt),
        "resume_requested": is_story_agent_resume_prompt(user_prompt),
        "confirm_requested": is_story_agent_confirm_current_size_prompt(user_prompt),
        "meta_requested": is_story_agent_worldcup_meta_prompt(user_prompt),
        "gender_scope": infer_story_agent_game_gender_scope_from_prompt(user_prompt),
        "category": infer_story_agent_worldcup_category_from_prompt(user_prompt),
        "requested_size": infer_story_agent_worldcup_requested_size_from_prompt(user_prompt),
    }


def has_story_agent_worldcup_followup_signal(
    *,
    user_prompt: str,
    followup: dict[str, Any] | None = None,
) -> bool:
    resolved_followup = followup or resolve_story_agent_worldcup_followup(user_prompt=user_prompt)
    return any(
        [
            is_story_agent_worldcup_prompt(user_prompt),
            bool(resolved_followup.get("exit_requested")),
            bool(resolved_followup.get("restart_requested")),
            bool(resolved_followup.get("resume_requested")),
            bool(resolved_followup.get("confirm_requested")),
            bool(resolved_followup.get("meta_requested")),
            bool(str(resolved_followup.get("gender_scope") or "").strip()),
            bool(str(resolved_followup.get("category") or "").strip()),
            bool(int(resolved_followup.get("requested_size") or 0)),
        ]
    )


def resolve_story_agent_game_reply_route(session_memory: dict[str, Any]) -> StoryAgentGameReplyRoute:
    normalized = _normalize_story_agent_session_memory(session_memory)
    game_mode = str((normalized.get("game_context") or {}).get("mode") or "").strip().lower()
    if game_mode not in STORY_AGENT_ALLOWED_GAME_MODES:
        return "guide"
    if game_mode == "ideal_worldcup":
        return "ideal_worldcup"
    return "vs_disabled"


def build_story_agent_game_dispatch_plan(session_memory: dict[str, Any]) -> StoryAgentGameDispatchPlan:
    route = resolve_story_agent_game_reply_route(session_memory)
    if route == "ideal_worldcup":
        return {
            "route": route,
            "model_used": "game-host",
            "route_mode": "game:ideal_worldcup",
            "intent": "playful",
        }
    if route == "vs_disabled":
        return {
            "route": route,
            "model_used": "system",
            "route_mode": "game:vs_game_disabled",
            "intent": "playful",
        }
    return {
        "route": "guide",
        "model_used": "system",
        "route_mode": "game:guide",
        "intent": "playful",
    }
