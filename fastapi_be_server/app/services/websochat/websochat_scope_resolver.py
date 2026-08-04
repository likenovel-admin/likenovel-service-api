from __future__ import annotations

import re

from app.services.websochat.websochat_contracts import WebsochatPromptReadScopeDecision

WEBSOCHAT_EXACT_EPISODE_RE = re.compile(r"(\d{1,4})\s*화")
WEBSOCHAT_ORDINAL_EPISODE_RE = re.compile(r"(\d{1,4})\s*번째(?:\s*화|\s*회차)?")
WEBSOCHAT_KOREAN_ORDINAL_MAP = {
    "첫": 1,
    "두": 2,
    "세": 3,
    "네": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
}
WEBSOCHAT_SCOPE_ONLY_EXACT_EPISODE_RE = re.compile(r"^\d{1,4}\s*화$")


def _infer_websochat_read_episode_to_from_prompt(
    user_prompt: str,
    *,
    latest_episode_no: int,
) -> int | None:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip()
    if not normalized:
        return None

    values = [
        int(match.group(1))
        for match in WEBSOCHAT_EXACT_EPISODE_RE.finditer(normalized)
        if int(match.group(1)) > 0
    ]
    if values:
        return min(max(values), max(int(latest_episode_no or 0), 1))
    return None


def _is_websochat_scope_declaration_prompt(user_prompt: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip()
    return bool(WEBSOCHAT_SCOPE_ONLY_EXACT_EPISODE_RE.fullmatch(normalized))


def _resolve_websochat_prompt_read_scope_decision(
    *,
    user_prompt: str,
    inferred_read_episode_to: int | None,
) -> WebsochatPromptReadScopeDecision:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip()
    if not normalized:
        return {
            "read_episode_to": None,
            "scope_state": "unknown",
            "is_scope_only": False,
        }

    inferred_episode_to = (
        int(inferred_read_episode_to)
        if inferred_read_episode_to is not None and int(inferred_read_episode_to) > 0
        else None
    )
    if inferred_episode_to is not None and _is_websochat_scope_declaration_prompt(normalized):
        return {
            "read_episode_to": inferred_episode_to,
            "scope_state": "known",
            "is_scope_only": True,
        }

    return {
        "read_episode_to": inferred_episode_to,
        "scope_state": "unknown",
        "is_scope_only": False,
    }


def _merge_websochat_prompt_read_scope(
    *,
    session_memory: dict[str, object],
    decision: WebsochatPromptReadScopeDecision,
) -> tuple[dict[str, object], dict[str, object]]:
    persistent_memory = dict(session_memory)
    turn_memory = dict(session_memory)
    current_episode_to = max(int(session_memory.get("read_episode_to") or 0), 0)
    decision_episode_to = max(int(decision.get("read_episode_to") or 0), 0)

    if decision.get("scope_state") == "known" and decision_episode_to > 0:
        turn_episode_to = (
            min(current_episode_to, decision_episode_to)
            if current_episode_to > 0
            else decision_episode_to
        )
        turn_memory["read_episode_to"] = turn_episode_to
        turn_memory["read_scope_state"] = "known"
        if current_episode_to <= 0 or decision_episode_to < current_episode_to:
            persistent_memory["read_episode_to"] = turn_episode_to
            persistent_memory["read_scope_state"] = "known"
            persistent_memory["read_scope_source"] = "prompt"
            turn_memory["read_scope_source"] = "prompt"
        return persistent_memory, turn_memory

    if current_episode_to > 0 and decision_episode_to > 0:
        turn_memory["read_episode_to"] = min(
            current_episode_to,
            decision_episode_to,
        )
        turn_memory["read_scope_state"] = "known"

    return persistent_memory, turn_memory


def _resolve_websochat_scope_read_episode_to(
    *,
    session_memory: dict[str, object],
    user_prompt: str,
    latest_episode_no: int,
) -> int:
    session_scope = max(int(session_memory.get("read_episode_to") or 0), 0)
    bounded_session_scope = min(
        session_scope,
        max(int(latest_episode_no or 0), 1),
    )
    inferred_from_prompt = _infer_websochat_read_episode_to_from_prompt(
        user_prompt,
        latest_episode_no=latest_episode_no,
    )
    if bounded_session_scope > 0:
        if inferred_from_prompt is not None and inferred_from_prompt > 0:
            return min(bounded_session_scope, inferred_from_prompt)
        return bounded_session_scope

    if (
        inferred_from_prompt is not None
        and _is_websochat_scope_declaration_prompt(user_prompt)
    ):
        return inferred_from_prompt

    return 0
