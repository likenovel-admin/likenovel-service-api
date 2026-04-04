from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.ai_chat_service import _call_claude_messages, _extract_text
from app.services.story_agent.story_agent_compare import (
    _extract_story_agent_episode_no_from_episode_summary_text,
    _is_story_agent_valid_game_candidate,
)
from app.services.story_agent.story_agent_game_memory import _normalize_story_agent_string_list
from app.services.story_agent.story_agent_utils import _extract_story_agent_json_object


async def get_story_agent_game_candidate_profiles(
    *,
    product_id: int,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT summary_type, scope_key, summary_text, source_doc_count
            FROM tb_story_agent_context_summary
            WHERE product_id = :product_id
              AND summary_type IN ('character_rp_profile', 'character_rp_examples')
              AND is_active = 'Y'
            ORDER BY summary_id DESC
            """
        ),
        {"product_id": product_id},
    )
    profiles: dict[str, dict[str, Any]] = {}
    profile_evidence_counts: dict[str, int] = {}
    examples_map: dict[str, list[dict[str, Any]]] = {}
    for row in result.mappings().all():
        summary_type = str(row.get("summary_type") or "").strip()
        scope_key = str(row.get("scope_key") or "").strip()
        if not scope_key:
            continue
        payload = _extract_story_agent_json_object(str(row.get("summary_text") or "")) or {}
        if summary_type == "character_rp_profile" and scope_key not in profiles:
            profiles[scope_key] = payload
            profile_evidence_counts[scope_key] = int(row.get("source_doc_count") or 0)
        if summary_type == "character_rp_examples" and scope_key not in examples_map:
            examples_map[scope_key] = list(payload.get("examples") or [])

    inventory_result = await db.execute(
        text(
            """
            SELECT scope_key, summary_text
            FROM tb_story_agent_context_summary
            WHERE product_id = :product_id
              AND summary_type = 'character_inventory'
              AND is_active = 'Y'
            ORDER BY summary_id DESC
            """
        ),
        {"product_id": product_id},
    )
    inventory_map: dict[str, dict[str, Any]] = {}
    for row in inventory_result.mappings().all():
        scope_key = str(row.get("scope_key") or "").strip()
        if not scope_key or scope_key in inventory_map:
            continue
        payload = _extract_story_agent_json_object(str(row.get("summary_text") or "")) or {}
        if payload:
            inventory_map[scope_key] = payload

    episode_summary_result = await db.execute(
        text(
            """
            SELECT summary_text
            FROM tb_story_agent_context_summary
            WHERE product_id = :product_id
              AND summary_type = 'episode_summary'
              AND is_active = 'Y'
            ORDER BY summary_id ASC
            """
        ),
        {"product_id": product_id},
    )
    episode_summaries: list[tuple[int, str]] = []
    for row in episode_summary_result.mappings().all():
        summary_text = str(row.get("summary_text") or "")
        episode_no = _extract_story_agent_episode_no_from_episode_summary_text(summary_text)
        if episode_no is None:
            continue
        episode_summaries.append((episode_no, summary_text))

    raw_candidates: list[dict[str, Any]] = []
    for scope_key, profile in profiles.items():
        inventory_payload = inventory_map.get(scope_key) or {}
        display_name = str(
            inventory_payload.get("display_name")
            or profile.get("display_name")
            or scope_key
        ).strip()
        if not display_name:
            continue
        alias_candidates = [
            display_name,
            *[str(item).strip() for item in (inventory_payload.get("aliases") or []) if str(item).strip()],
            *[str(item).strip() for item in (profile.get("aliases") or []) if str(item).strip()],
        ]
        normalized_aliases: list[str] = []
        seen_aliases: set[str] = set()
        for alias in sorted(alias_candidates, key=len, reverse=True):
            normalized_alias = alias.strip()
            if not normalized_alias or normalized_alias in seen_aliases:
                continue
            seen_aliases.add(normalized_alias)
            normalized_aliases.append(normalized_alias)

        first_seen_episode_no: int | None = None
        inventory_first_seen = inventory_payload.get("first_seen_episode_no")
        try:
            if inventory_first_seen is not None:
                normalized_first_seen = int(inventory_first_seen)
                if normalized_first_seen > 0:
                    first_seen_episode_no = normalized_first_seen
        except Exception:
            first_seen_episode_no = None
        for episode_no, summary_text in episode_summaries:
            if any(alias in summary_text for alias in normalized_aliases):
                if first_seen_episode_no is None or episode_no < first_seen_episode_no:
                    first_seen_episode_no = episode_no
                break
        distinct_episode_count = int(inventory_payload.get("distinct_episode_count") or 0)
        summary_mention_count = int(inventory_payload.get("summary_mention_count") or 0)
        voice_evidence_count = int(inventory_payload.get("voice_evidence_count") or 0)
        entity_kind = str(inventory_payload.get("entity_kind") or "").strip().lower() or None
        relation_presence = str(inventory_payload.get("relation_presence") or "").strip().lower() or "low"
        action_presence = str(inventory_payload.get("action_presence") or "").strip().lower() or "low"
        raw_candidates.append(
            {
                "scope_key": scope_key,
                "display_name": display_name,
                "aliases": normalized_aliases[1:],
                "personality_core": [str(item).strip() for item in (profile.get("personality_core") or []) if str(item).strip()][:3],
                "baseline_attitude": str(profile.get("baseline_attitude") or "").strip(),
                "evidence_count": int(profile_evidence_counts.get(scope_key) or 0),
                "distinct_episode_count": distinct_episode_count,
                "summary_mention_count": summary_mention_count,
                "voice_evidence_count": voice_evidence_count,
                "entity_kind": entity_kind,
                "relation_presence": relation_presence,
                "action_presence": action_presence,
                "first_seen_episode_no": first_seen_episode_no,
                "examples": [
                    str(item.get("text") or "").strip()
                    for item in (examples_map.get(scope_key) or [])
                    if str(item.get("text") or "").strip()
                ][:3],
                "example_items": [
                    {
                        "episode_no": int(item.get("episode_no") or 0) if str(item.get("episode_no") or "").strip() else 0,
                        "text": str(item.get("text") or "").strip(),
                    }
                    for item in (examples_map.get(scope_key) or [])
                    if str(item.get("text") or "").strip()
                ][:8],
            }
        )

    def _presence_rank(value: Any) -> int:
        normalized = str(value or "").strip().lower()
        if normalized == "high":
            return 2
        if normalized == "medium":
            return 1
        return 0

    def _sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        return (
            0 if str(item.get("scope_key") or "").startswith("protagonist:") else 1,
            -int(item.get("distinct_episode_count") or 0),
            -int(item.get("summary_mention_count") or 0),
            -_presence_rank(item.get("relation_presence")),
            -_presence_rank(item.get("action_presence")),
            -int(item.get("evidence_count") or 0),
            -len(item.get("examples") or []),
            str(item.get("display_name") or ""),
        )

    filtered_candidates = sorted(
        [item for item in raw_candidates if _is_story_agent_valid_game_candidate(item)],
        key=_sort_key,
    )
    if len(filtered_candidates) >= 2:
        return filtered_candidates
    return sorted(raw_candidates, key=_sort_key)


async def select_story_agent_game_candidates(
    *,
    product_row: dict[str, Any],
    candidates: list[dict[str, Any]],
    game_mode: str,
    gender_scope: str,
    category: str,
    desired_count: int,
) -> list[dict[str, Any]]:
    if not candidates:
        return []

    safe_count = max(2, min(int(desired_count or 4), 8))
    candidate_block = "\n".join(
        f"- scope_key={item['scope_key']}\n"
        f"  display_name={item['display_name']}\n"
        f"  aliases={', '.join(item['aliases']) or '-'}\n"
        f"  personality_core={'; '.join(item['personality_core']) or '-'}\n"
        f"  baseline_attitude={item['baseline_attitude'] or '-'}\n"
        f"  examples={'; '.join(item['examples']) or '-'}"
        for item in candidates
    )
    system_prompt = (
        "너는 스토리 에이전트 게임 후보 선별기다. "
        "주어진 후보 목록 안에서만 고른다. 없는 캐릭터를 만들지 마라. "
        "mixed가 아니면 요청한 성별 범위에 맞는 캐릭터만 고른다. "
        "요청 카테고리에 맞게 매력이 있는 후보를 우선 정렬하되, 확신이 약한 후보는 제외할 수 있다. "
        "반드시 JSON 객체만 반환하라."
    )
    user_prompt = (
        f"작품: {str(product_row.get('title') or '').strip()}\n"
        f"game_mode: {game_mode}\n"
        f"gender_scope: {gender_scope}\n"
        f"category: {category}\n"
        f"desired_count: {safe_count}\n\n"
        "[후보 목록]\n"
        f"{candidate_block}\n\n"
        '출력 형식: {"candidate_scope_keys": ["scope_key1", "scope_key2"]}'
    )
    selected_scope_keys: list[str] = []
    try:
        response = await _call_claude_messages(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=240,
        )
        payload = _extract_story_agent_json_object(_extract_text(response.get("content") or "")) or {}
        selected_scope_keys = _normalize_story_agent_string_list(payload.get("candidate_scope_keys"), limit=safe_count)
    except Exception:
        selected_scope_keys = []

    candidate_map = {item["scope_key"]: item for item in candidates}
    selected_candidates = [candidate_map[key] for key in selected_scope_keys if key in candidate_map]
    if selected_candidates:
        return selected_candidates[:safe_count]
    return candidates[:safe_count]

