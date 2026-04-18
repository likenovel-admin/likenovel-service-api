from __future__ import annotations

import re

from app.services.websochat.websochat_contracts import WebsochatPromptReadScopeDecision

WEBSOCHAT_EXACT_EPISODE_RE = re.compile(r"(\d{1,4})\s*화")
WEBSOCHAT_ORDINAL_EPISODE_RE = re.compile(r"(\d{1,4})\s*번째(?:\s*화|\s*회차)?")
WEBSOCHAT_UNREAD_SCOPE_PATTERNS = (
    re.compile(r"하나도\s+안\s*(?:읽|봤)"),
    re.compile(r"아직\s+안\s*(?:읽|봤)"),
    re.compile(r"안\s*읽었"),
    re.compile(r"안\s*봤"),
)
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
WEBSOCHAT_SCOPE_DECLARATION_RE = re.compile(
    r"(?:까지|기준)?\s*(?:읽었(?:어|어요|음|다)?|봤(?:어|어요|음|다)?|읽는\s*중(?:이야|이에요|입니다)?|보는\s*중(?:이야|이에요|입니다)?)$"
)
WEBSOCHAT_SCOPE_TERMINAL_RE = re.compile(r"(?:까지|기준)$")
WEBSOCHAT_SCOPE_ONLY_EXACT_EPISODE_RE = re.compile(r"^\d{1,4}\s*화$")
WEBSOCHAT_SCOPE_ONLY_EXACT_ORDINAL_RE = re.compile(r"^\d{1,4}\s*번째(?:\s*화|\s*회차)?$")
WEBSOCHAT_SCOPE_REQUEST_RE = re.compile(
    r"(?:\?|왜|뭐|무엇|무슨|어때|어떤|어디|누가|비교|분석|설명|정리|요약|예상|말해|알려|추천|토론|대화|이야기|해줘)"
)


def _infer_websochat_read_episode_to_from_prompt(
    user_prompt: str,
    *,
    latest_episode_no: int,
) -> int | None:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip()
    if not normalized:
        return None
    if _is_websochat_unread_scope_prompt(normalized):
        return 0
    patterns = [
        r"(\d+)\s*화\s*(?:까지|기준|읽었|읽고)",
        r"(\d+)\s*화",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        try:
            value = int(match.group(1))
        except Exception:
            continue
        if value <= 0:
            continue
        return min(value, max(int(latest_episode_no or 0), 1))
    return None


def _is_websochat_unread_scope_prompt(user_prompt: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip().lower()
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in WEBSOCHAT_UNREAD_SCOPE_PATTERNS)


def _is_websochat_scope_declaration_prompt(user_prompt: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip().lower()
    if not normalized or _is_websochat_unread_scope_prompt(normalized):
        return False
    if (
        WEBSOCHAT_SCOPE_ONLY_EXACT_EPISODE_RE.fullmatch(normalized)
        or WEBSOCHAT_SCOPE_ONLY_EXACT_ORDINAL_RE.fullmatch(normalized)
    ):
        return True
    if WEBSOCHAT_SCOPE_REQUEST_RE.search(normalized):
        return False
    return bool(
        WEBSOCHAT_SCOPE_DECLARATION_RE.search(normalized)
        or WEBSOCHAT_SCOPE_TERMINAL_RE.search(normalized)
    )


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

    if _is_websochat_unread_scope_prompt(normalized):
        return {
            "read_episode_to": 0,
            "scope_state": "none",
            "is_scope_only": not bool(WEBSOCHAT_SCOPE_REQUEST_RE.search(normalized)),
        }

    if inferred_read_episode_to is None or int(inferred_read_episode_to) <= 0:
        return {
            "read_episode_to": None,
            "scope_state": "unknown",
            "is_scope_only": False,
        }

    return {
        "read_episode_to": int(inferred_read_episode_to),
        "scope_state": "known",
        "is_scope_only": _is_websochat_scope_declaration_prompt(normalized),
    }


def _resolve_websochat_scope_read_episode_to(
    *,
    session_memory: dict[str, object],
    user_prompt: str,
    latest_episode_no: int,
) -> int:
    inferred_from_prompt = _infer_websochat_read_episode_to_from_prompt(
        user_prompt,
        latest_episode_no=latest_episode_no,
    )
    if inferred_from_prompt is not None:
        return inferred_from_prompt

    session_scope = max(int(session_memory.get("read_episode_to") or 0), 0)
    if session_scope > 0:
        return min(session_scope, max(int(latest_episode_no or 0), 1))

    return 0
