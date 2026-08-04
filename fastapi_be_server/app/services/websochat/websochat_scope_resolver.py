from __future__ import annotations

import re

from app.services.websochat.websochat_contracts import WebsochatPromptReadScopeDecision

WEBSOCHAT_EXACT_EPISODE_RE = re.compile(r"(\d{1,4})\s*화")
WEBSOCHAT_ORDINAL_EPISODE_RE = re.compile(r"(\d{1,4})\s*번째(?:\s*화|\s*회차)?")
WEBSOCHAT_UNREAD_SCOPE_PATTERNS = (
    re.compile(r"하나도\s+안\s*(?:읽|봤)"),
    re.compile(r"아직\s+안\s*(?:읽|봤)"),
    re.compile(r"아직\s+못\s*(?:읽|봤)"),
    re.compile(r"안\s*읽었"),
    re.compile(r"안\s*봤"),
    re.compile(r"못\s*읽었"),
    re.compile(r"못\s*봤"),
    re.compile(r"안\s*(?:읽은|본)"),
    re.compile(r"못\s*(?:읽은|본)"),
    re.compile(r"(?:읽|보)(?:지|지는|진)\s*(?:못했|않았)"),
)
WEBSOCHAT_SCOPED_UNREAD_SCOPE_RE = re.compile(
    r"(?:"
    r"(?P<episode>\d{1,4})\s*화\s*"
    r"(?:는|은|까지(?:는|도|만)?|이후(?:는)?|뒤(?:는)?)?|"
    r"(?:그\s*뒤|(?:그\s*)?이후)\s*(?:는|부터는|로는)?"
    r")\s*"
    r"(?:(?:아직|하나도|한\s*번도)\s+)*"
    r"(?:"
    r"안\s*(?:읽|봤|본)|"
    r"못\s*(?:읽|봤|본)|"
    r"(?:읽|보)(?:지|지는|진)\s*(?:못했|않았)"
    r")"
)
WEBSOCHAT_POSITIVE_READ_SCOPE_RE = re.compile(
    r"(?P<episode>\d{1,4})\s*화\s*"
    r"(?:(?:까지(?:는|만)?|까진|은|는)\s*)?"
    r"(?:다\s*)?"
    r"(?:"
    r"읽었(?:어(?:요)?|음|다|고|지|지만|는데)?|"
    r"봤(?:어(?:요)?|음|다|고|지|지만|는데)?|"
    r"읽고(?!\s*싶)|보고(?!\s*싶)|"
    r"읽는\s*중(?:이야|이에요|입니다|이고|인데)?|"
    r"보는\s*중(?:이야|이에요|입니다|이고|인데)?"
    r")(?=$|[\s,.!;:])"
)
WEBSOCHAT_EXPLICIT_BASIS_SCOPE_RE = re.compile(
    r"(?P<episode>\d{1,4})\s*화\s*"
    r"기준(?:으로(?:는|만)?|으론)?(?=$|[\s,.!?;:])"
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


def _find_websochat_positive_read_scope_matches(
    user_prompt: str,
) -> list[tuple[int, int, int]]:
    return [
        (int(match.group("episode")), match.start(), match.end())
        for match in WEBSOCHAT_POSITIVE_READ_SCOPE_RE.finditer(user_prompt)
        if int(match.group("episode")) > 0
    ]


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

    positive_scope_values = [
        value
        for value, _, _ in _find_websochat_positive_read_scope_matches(normalized)
    ]
    if positive_scope_values:
        return min(
            max(positive_scope_values),
            max(int(latest_episode_no or 0), 1),
        )

    explicit_basis_values = [
        int(match.group("episode"))
        for match in WEBSOCHAT_EXPLICIT_BASIS_SCOPE_RE.finditer(normalized)
        if int(match.group("episode")) > 0
    ]
    if explicit_basis_values:
        return min(
            max(explicit_basis_values),
            max(int(latest_episode_no or 0), 1),
        )

    values = [
        int(match.group(1))
        for match in WEBSOCHAT_EXACT_EPISODE_RE.finditer(normalized)
        if int(match.group(1)) > 0
    ]
    if values:
        return min(max(values), max(int(latest_episode_no or 0), 1))
    return None


def _is_websochat_unread_scope_prompt(user_prompt: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip().lower()
    if not normalized:
        return False
    has_unread_scope = any(
        pattern.search(normalized) for pattern in WEBSOCHAT_UNREAD_SCOPE_PATTERNS
    )
    if not has_unread_scope:
        return False
    positive_scope_matches = _find_websochat_positive_read_scope_matches(normalized)
    if not positive_scope_matches:
        return True

    positive_scope_ceiling = max(value for value, _, _ in positive_scope_matches)

    def remove_resolved_scoped_unread(match: re.Match[str]) -> str:
        unread_episode = match.group("episode")
        if unread_episode is None:
            return " "

        unread_episode_no = int(unread_episode)
        if unread_episode_no > positive_scope_ceiling:
            return " "
        if any(
            value >= unread_episode_no and start > match.end()
            for value, start, _ in positive_scope_matches
        ):
            return " "
        return match.group(0)

    unscoped_prompt = WEBSOCHAT_SCOPED_UNREAD_SCOPE_RE.sub(
        remove_resolved_scoped_unread,
        normalized,
    )
    return any(
        pattern.search(unscoped_prompt)
        for pattern in WEBSOCHAT_UNREAD_SCOPE_PATTERNS
    )


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
