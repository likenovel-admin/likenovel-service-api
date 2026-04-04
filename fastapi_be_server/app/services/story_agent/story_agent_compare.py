from __future__ import annotations

import re
from itertools import combinations
from typing import Any

from app.services.story_agent.story_agent_game_memory import _normalize_story_agent_string_list


def _build_story_agent_pair_key(name_a: str, name_b: str) -> str:
    return "::".join(sorted([str(name_a).strip(), str(name_b).strip()]))


def _is_story_agent_valid_game_candidate(candidate: dict[str, Any]) -> bool:
    scope_key = str(candidate.get("scope_key") or "").strip()
    if scope_key.startswith("protagonist:"):
        return True
    entity_kind = str(candidate.get("entity_kind") or "").strip().lower()
    if entity_kind and entity_kind not in {"person", "stable_role"}:
        return False
    distinct_episode_count = int(candidate.get("distinct_episode_count") or 0)
    summary_mention_count = int(candidate.get("summary_mention_count") or 0)
    voice_evidence_count = int(candidate.get("voice_evidence_count") or 0)
    if distinct_episode_count > 0 or summary_mention_count > 0 or voice_evidence_count > 0:
        return (
            distinct_episode_count >= 3
            or summary_mention_count >= 3
            or voice_evidence_count >= 2
        )
    has_voice_evidence = bool(candidate.get("examples")) or bool(candidate.get("personality_core"))
    if not has_voice_evidence:
        return False
    return int(candidate.get("evidence_count") or 0) >= 3


def _resolve_story_agent_pair_choice(user_prompt: str, pair: list[str]) -> str | None:
    if len(pair) != 2:
        return None
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip()
    if not normalized:
        return None
    left, right = pair[0], pair[1]
    if left and left in normalized:
        return left
    if right and right in normalized:
        return right
    lowered = normalized.lower()
    if lowered in {"1", "1번", "왼쪽", "앞", "첫번째", "첫 번째"}:
        return left
    if lowered in {"2", "2번", "오른쪽", "뒤", "두번째", "두 번째"}:
        return right
    return None


def _extract_story_agent_episode_no_from_episode_summary_text(summary_text: str) -> int | None:
    normalized = str(summary_text or "").strip()
    if not normalized:
        return None
    match = re.match(r"^\[(\d+)화\]", normalized)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except Exception:
        return None
    return value if value >= 0 else None


def _filter_story_agent_worldcup_candidates_by_read_scope(
    candidates: list[dict[str, Any]],
    *,
    read_episode_to: int,
) -> list[dict[str, Any]]:
    visible_candidates: list[dict[str, Any]] = []
    for item in candidates:
        scope_key = str(item.get("scope_key") or "").strip()
        example_items = list(item.get("example_items") or [])
        in_scope_items = []
        for example in example_items:
            try:
                episode_no = int(example.get("episode_no") or 0)
            except Exception:
                episode_no = 0
            if episode_no and episode_no <= read_episode_to:
                in_scope_items.append(example)
        first_seen_episode_no = max(int(item.get("first_seen_episode_no") or 0), 0) or None
        in_scope_by_first_seen = bool(first_seen_episode_no and first_seen_episode_no <= read_episode_to)
        if scope_key.startswith("protagonist:") or in_scope_items or in_scope_by_first_seen:
            visible = dict(item)
            if in_scope_items:
                visible["examples"] = [
                    str(example.get("text") or "").strip()
                    for example in in_scope_items
                    if str(example.get("text") or "").strip()
                ][:3]
                visible["example_items"] = in_scope_items[:5]
            else:
                visible["examples"] = []
                visible["example_items"] = []
            visible["in_scope_evidence_count"] = len(in_scope_items)
            visible_candidates.append(visible)
    return sorted(
        visible_candidates,
        key=lambda item: (
            0 if str(item.get("scope_key") or "").startswith("protagonist:") else 1,
            -int(item.get("in_scope_evidence_count") or 0),
            -int(item.get("evidence_count") or 0),
            str(item.get("display_name") or ""),
        ),
    )


def _resolve_story_agent_worldcup_bracket_size(
    *,
    read_episode_to: int,
    requested_size: int | None,
    stable_candidate_count: int,
) -> tuple[int, str | None]:
    if stable_candidate_count < 2:
        return 0, "후보부족"
    if read_episode_to <= 5:
        max_by_scope = 2
    elif read_episode_to <= 24:
        max_by_scope = 4
    else:
        max_by_scope = 8
    max_supported = min(
        max_by_scope,
        8 if stable_candidate_count >= 8 else 4 if stable_candidate_count >= 4 else 2,
    )
    if max_supported < 2:
        return 0, "후보부족"
    if requested_size in {2, 4, 8}:
        if requested_size <= max_supported:
            return requested_size, None
        if requested_size == 8 and max_supported == 4:
            return 4, "8강불가"
        if requested_size in {4, 8} and max_supported == 2:
            return 2, "4강불가"
        return max_supported, "축소"
    if max_supported == 2:
        return 2, "2인비교권장"
    if max_supported >= 8 and read_episode_to >= 25:
        return 8, None
    return 4, None


def _infer_story_agent_game_category_from_prompt(user_prompt: str) -> str | None:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip().lower()
    if not normalized:
        return None
    category_aliases = [
        ("power", ["파워", "힘", "전투력", "강함", "누가 더 셈", "누가 더 세", "누가 더 강"]),
        ("intelligence", ["지능", "두뇌", "머리", "누가 더 똑똑", "지략", "계략"]),
        ("charm", ["매력", "끌림", "이상형", "호감", "누가 더 끌", "더 끌리는"]),
        ("mental", ["멘탈", "정신력", "버티기", "마음가짐", "누가 더 안 무너져"]),
        ("survival", ["생존", "생존력", "누가 더 오래 살아", "누가 더 오래 버텨", "살아남"]),
        ("romance", ["연애", "연애형", "썸", "사귀", "애인"]),
        ("date", ["데이트", "데이트형", "같이 놀", "같이 나가", "데이트 상대로"]),
        ("personality", ["성격", "성향", "인성", "성격형"]),
        ("narrative", ["서사", "서사성", "서사적으로", "캐릭터성", "서사 기준"]),
    ]
    for category, aliases in category_aliases:
        if any(alias in normalized for alias in aliases):
            return category
    return None


def _extract_story_agent_direct_match_scope_keys(
    *,
    user_prompt: str,
    candidates: list[dict[str, Any]],
) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip()
    if not normalized:
        return []
    matched: list[str] = []
    for candidate in candidates:
        names = [candidate["display_name"], *candidate.get("aliases", [])]
        for name in names:
            if name and name in normalized:
                scope_key = str(candidate["scope_key"]).strip()
                if scope_key not in matched:
                    matched.append(scope_key)
                break
        if len(matched) >= 2:
            break
    return matched[:2]


def _pick_story_agent_unused_pair(
    candidates: list[dict[str, Any]],
    used_match_keys: list[str],
) -> list[dict[str, Any]]:
    used_set = set(_normalize_story_agent_string_list(used_match_keys, limit=128))
    for left, right in combinations(candidates, 2):
        pair_key = _build_story_agent_pair_key(left["display_name"], right["display_name"])
        if pair_key in used_set:
            continue
        return [left, right]
    return candidates[:2]


def _build_story_agent_worldcup_round(
    candidate_names: list[str],
    used_pair_keys: list[str],
) -> tuple[list[list[str]], str] | tuple[None, None]:
    unique_candidates = _normalize_story_agent_string_list(candidate_names, limit=8)
    if len(unique_candidates) < 2:
        return None, None
    used_set = set(_normalize_story_agent_string_list(used_pair_keys, limit=128))
    if len(unique_candidates) == 2:
        pair_key = _build_story_agent_pair_key(unique_candidates[0], unique_candidates[1])
        if pair_key in used_set:
            return None, None
        return [unique_candidates], "결승"
    if len(unique_candidates) >= 8:
        names = unique_candidates[:8]
        remaining = list(names)
        pairs: list[list[str]] = []
        while len(remaining) >= 2 and len(pairs) < 4:
            left = remaining.pop(0)
            partner_index = None
            for idx, right in enumerate(remaining):
                pair_key = _build_story_agent_pair_key(left, right)
                if pair_key not in used_set:
                    partner_index = idx
                    break
            if partner_index is None:
                return None, None
            right = remaining.pop(partner_index)
            pairs.append([left, right])
        if len(pairs) == 4:
            return pairs, "8강"
        return None, None

    target_candidates = unique_candidates[:4]
    if len(target_candidates) == 3:
        possible_pairs = list(combinations(target_candidates, 2))
        for pair in possible_pairs:
            pair_key = _build_story_agent_pair_key(pair[0], pair[1])
            if pair_key not in used_set:
                return [[pair[0], pair[1]]], "결승"
        return None, None

    names = target_candidates[:4]
    for pair in combinations(names, 2):
        pair_key = _build_story_agent_pair_key(pair[0], pair[1])
        if pair_key in used_set:
            continue
        remaining = [name for name in names if name not in pair]
        remaining_key = _build_story_agent_pair_key(remaining[0], remaining[1])
        if remaining_key in used_set:
            continue
        return [[pair[0], pair[1]], [remaining[0], remaining[1]]], "4강"
    return None, None
