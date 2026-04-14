from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

WEBSOCHAT_SCOPE_SUMMARY_LIMIT = 6
WEBSOCHAT_SCOPE_CHARACTER_LIMIT = 12
WEBSOCHAT_SCOPE_RELATION_LIMIT = 16
WEBSOCHAT_SCOPE_HOOK_LIMIT = 8
logger = logging.getLogger(__name__)


def _extract_json_object(text_value: str) -> dict[str, Any] | None:
    raw_text = str(text_value or "").strip()
    if not raw_text:
        return None
    try:
        parsed = json.loads(raw_text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", raw_text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _normalize_string_list(raw_value: Any, *, limit: int = 20) -> list[str]:
    items: list[str] = []
    for item in raw_value or []:
        normalized = str(item or "").strip()
        if not normalized or normalized in items:
            continue
        items.append(normalized)
        if len(items) >= limit:
            break
    return items


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _presence_rank(value: Any) -> int:
    normalized = str(value or "").strip().lower()
    if normalized == "high":
        return 3
    if normalized == "medium":
        return 2
    if normalized == "low":
        return 1
    return 0


def _normalize_scope_summary_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "episode_from": _coerce_int(row.get("episodeFrom")),
        "episode_to": _coerce_int(row.get("episodeTo")),
        "summary_text": str(row.get("summaryText") or "").strip(),
    }


def _finalize_scoped_characters(character_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for current in character_map.values():
        episode_nos = sorted(int(value) for value in set(current["episode_nos"]))
        distinct_episode_count = len(episode_nos)
        aliases = sorted(
            set(str(alias).strip() for alias in current["aliases"] if str(alias).strip()),
            key=lambda value: (0 if value == str(current["display_name"]) else 1, -len(value), value),
        )
        alias_stability = (
            "high"
            if len(aliases) <= 2 and distinct_episode_count >= 3
            else "medium"
            if distinct_episode_count >= 2
            else "low"
        )
        scene_centrality = (
            "high"
            if int(current["scene_weight_high_count"] or 0) >= max(2, distinct_episode_count // 2)
            else "medium"
            if int(current["scene_weight_high_count"] or 0) + int(current["scene_weight_medium_count"] or 0) >= 2
            else "low"
        )
        action_presence = (
            "high"
            if int(current["summary_mention_count"] or 0) >= 4 and current["action_tag_counts"]
            else "medium"
            if current["action_tag_counts"]
            else "low"
        )
        relation_presence = (
            "high"
            if int(current["relation_episode_count"] or 0) >= 3
            else "medium"
            if int(current["relation_episode_count"] or 0) >= 1
            else "low"
        )
        rows.append(
            {
                "character_key": str(current["character_key"]),
                "display_name": str(current["display_name"]),
                "aliases": aliases[:8],
                "entity_kind": str(current["entity_kind"]),
                "first_seen_episode_no": episode_nos[0] if episode_nos else 0,
                "latest_seen_episode_no": episode_nos[-1] if episode_nos else 0,
                "distinct_episode_count": distinct_episode_count,
                "summary_mention_count": int(current["summary_mention_count"] or 0),
                "voice_evidence_count": int(current["voice_evidence_count"] or 0),
                "alias_stability": alias_stability,
                "scene_centrality": scene_centrality,
                "role_stability": "high" if distinct_episode_count >= 3 else "medium" if distinct_episode_count >= 2 else "low",
                "action_presence": action_presence,
                "relation_presence": relation_presence,
            }
        )
    rows.sort(
        key=lambda item: (
            -_presence_rank(item.get("scene_centrality")),
            -int(item.get("distinct_episode_count") or 0),
            -int(item.get("summary_mention_count") or 0),
            -int(item.get("voice_evidence_count") or 0),
            int(item.get("first_seen_episode_no") or 0) or 999999,
            str(item.get("display_name") or ""),
        )
    )
    return rows[:WEBSOCHAT_SCOPE_CHARACTER_LIMIT]


def _finalize_scoped_relations(relation_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for current in relation_map.values():
        episode_nos = sorted(int(value) for value in set(current["episode_nos"]))
        distinct_episode_count = len(episode_nos)
        rows.append(
            {
                "source_key": str(current["source_key"]),
                "target_key": str(current["target_key"]),
                "source_display_name": str(current["source_display_name"]),
                "target_display_name": str(current["target_display_name"]),
                "first_seen_episode_no": episode_nos[0] if episode_nos else 0,
                "latest_seen_episode_no": episode_nos[-1] if episode_nos else 0,
                "distinct_episode_count": distinct_episode_count,
                "relation_intensity": "high" if distinct_episode_count >= 3 else "medium" if distinct_episode_count >= 2 else "low",
                "dominant_relation_tags": [
                    key
                    for key, _ in sorted(
                        current["relation_tag_counts"].items(),
                        key=lambda item: (-int(item[1] or 0), item[0]),
                    )[:5]
                ],
                "evidence_episode_nos": episode_nos[:12],
            }
        )
    rows.sort(
        key=lambda item: (
            -_presence_rank(item.get("relation_intensity")),
            -int(item.get("distinct_episode_count") or 0),
            int(item.get("first_seen_episode_no") or 0) or 999999,
            str(item.get("source_display_name") or ""),
            str(item.get("target_display_name") or ""),
        )
    )
    return rows[:WEBSOCHAT_SCOPE_RELATION_LIMIT]


def _aggregate_scoped_signal_rows(signal_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    character_map: dict[str, dict[str, Any]] = {}
    relation_map: dict[str, dict[str, Any]] = {}
    hooks: list[str] = []
    seen_hooks: set[str] = set()

    for row in signal_rows:
        payload = _extract_json_object(str(row.get("summaryText") or "")) or {}
        episode_no = _coerce_int(payload.get("episode_no") or row.get("episodeFrom"))
        mentioned_characters = list(payload.get("mentioned_characters") or [])
        display_name_by_key: dict[str, str] = {}

        for hook in payload.get("cliffhanger_hooks") or []:
            normalized_hook = str(hook or "").strip()
            if not normalized_hook or normalized_hook in seen_hooks:
                continue
            seen_hooks.add(normalized_hook)
            hooks.append(normalized_hook)
            if len(hooks) >= WEBSOCHAT_SCOPE_HOOK_LIMIT:
                break

        for item in mentioned_characters:
            if not isinstance(item, dict):
                continue
            character_key = str(item.get("character_key") or "").strip()
            display_name = str(item.get("display_name") or "").strip()
            entity_kind = str(item.get("entity_kind") or "person").strip().lower()
            if entity_kind not in {"person", "stable_role"}:
                continue
            if not character_key or not display_name:
                continue
            display_name_by_key[character_key] = display_name
            current = character_map.setdefault(
                character_key,
                {
                    "character_key": character_key,
                    "display_name": display_name,
                    "entity_kind": entity_kind,
                    "aliases": set(),
                    "episode_nos": set(),
                    "summary_mention_count": 0,
                    "voice_evidence_count": 0,
                    "scene_weight_high_count": 0,
                    "scene_weight_medium_count": 0,
                    "scene_weight_low_count": 0,
                    "action_tag_counts": {},
                    "relation_episode_count": 0,
                },
            )
            current["display_name"] = display_name
            current["entity_kind"] = entity_kind
            for alias in item.get("aliases") or []:
                alias_text = str(alias).strip()
                if alias_text:
                    current["aliases"].add(alias_text)
            if episode_no > 0:
                current["episode_nos"].add(episode_no)
            current["summary_mention_count"] += 1
            if str(item.get("voice_mode") or "").strip().lower() in {"dialogue", "monologue"}:
                current["voice_evidence_count"] += 1
            scene_weight = str(item.get("scene_weight") or "").strip().lower()
            if scene_weight == "high":
                current["scene_weight_high_count"] += 1
            elif scene_weight == "medium":
                current["scene_weight_medium_count"] += 1
            else:
                current["scene_weight_low_count"] += 1
            for tag in item.get("action_tags") or []:
                tag_text = str(tag).strip()
                if not tag_text:
                    continue
                current["action_tag_counts"][tag_text] = int(current["action_tag_counts"].get(tag_text) or 0) + 1
            if list(item.get("relation_edges") or []):
                current["relation_episode_count"] += 1

        for item in mentioned_characters:
            if not isinstance(item, dict):
                continue
            source_key = str(item.get("character_key") or "").strip()
            source_display_name = str(item.get("display_name") or "").strip()
            if not source_key or not source_display_name:
                continue
            for edge in item.get("relation_edges") or []:
                if not isinstance(edge, dict):
                    continue
                target_key = str(edge.get("target_key") or "").strip()
                relation_tag = str(edge.get("relation_tag") or "").strip()
                direction = str(edge.get("direction") or "").strip().lower()
                if not target_key or not relation_tag or target_key == source_key:
                    continue
                target_display_name = display_name_by_key.get(target_key) or str(edge.get("target_label") or target_key).strip()

                edge_specs: list[tuple[str, str, str, str, str]] = []
                if direction == "from_target":
                    edge_specs.append((target_key, target_display_name, source_key, source_display_name, relation_tag))
                elif direction == "mutual":
                    edge_specs.append((source_key, source_display_name, target_key, target_display_name, relation_tag))
                    edge_specs.append((target_key, target_display_name, source_key, source_display_name, relation_tag))
                else:
                    edge_specs.append((source_key, source_display_name, target_key, target_display_name, relation_tag))

                for edge_source_key, edge_source_name, edge_target_key, edge_target_name, edge_tag in edge_specs:
                    relation_key = f"{edge_source_key}=>{edge_target_key}"
                    current_relation = relation_map.setdefault(
                        relation_key,
                        {
                            "source_key": edge_source_key,
                            "source_display_name": edge_source_name,
                            "target_key": edge_target_key,
                            "target_display_name": edge_target_name,
                            "episode_nos": set(),
                            "relation_tag_counts": {},
                        },
                    )
                    if episode_no > 0:
                        current_relation["episode_nos"].add(episode_no)
                    current_relation["relation_tag_counts"][edge_tag] = int(
                        current_relation["relation_tag_counts"].get(edge_tag) or 0
                    ) + 1

    return (
        _finalize_scoped_characters(character_map),
        _finalize_scoped_relations(relation_map),
        hooks[:WEBSOCHAT_SCOPE_HOOK_LIMIT],
    )


async def load_websochat_scope_context(
    *,
    product_id: int,
    read_episode_to: int,
    latest_episode_no: int,
    db: AsyncSession,
) -> dict[str, Any]:
    safe_scope = max(1, min(int(read_episode_to or latest_episode_no or 0), int(latest_episode_no or 0)))

    summary_result = await db.execute(
        text(
            """
            SELECT
                episode_from AS episodeFrom,
                episode_to AS episodeTo,
                summary_text AS summaryText
            FROM tb_story_agent_context_summary
            WHERE product_id = :product_id
              AND summary_type = 'episode_summary'
              AND is_active = 'Y'
              AND episode_to <= :read_episode_to
            ORDER BY episode_to DESC, summary_id DESC
            LIMIT :limit
            """
        ),
        {
            "product_id": product_id,
            "read_episode_to": safe_scope,
            "limit": WEBSOCHAT_SCOPE_SUMMARY_LIMIT,
        },
    )
    summary_rows = [_normalize_scope_summary_row(dict(row)) for row in summary_result.mappings().all()]

    signal_result = await db.execute(
        text(
            """
            SELECT
                episode_from AS episodeFrom,
                summary_text AS summaryText
            FROM tb_story_agent_context_summary
            WHERE product_id = :product_id
              AND summary_type = 'episode_character_signals'
              AND is_active = 'Y'
              AND episode_to <= :read_episode_to
            ORDER BY episode_to DESC, summary_id DESC
            LIMIT :limit
            """
        ),
        {
            "product_id": product_id,
            "read_episode_to": safe_scope,
            "limit": WEBSOCHAT_SCOPE_SUMMARY_LIMIT,
        },
    )
    signal_rows = [dict(row) for row in signal_result.mappings().all()]
    scoped_characters, scoped_relations, hooks = _aggregate_scoped_signal_rows(signal_rows)
    logger.info(
        "websochat scope_character_signal_aggregate product_id=%s read_episode_to=%s signal_count=%s character_count=%s relation_count=%s hooks_count=%s sample_characters=%s",
        product_id,
        safe_scope,
        len(signal_rows),
        len(scoped_characters),
        len(scoped_relations),
        len(hooks),
        [
            {
                "display_name": str(item.get("display_name") or "").strip(),
                "entity_kind": str(item.get("entity_kind") or "").strip(),
                "episodes": list(item.get("episode_nos") or [])[:3],
            }
            for item in scoped_characters[:5]
        ],
    )

    return {
        "canon_scope": {
            "product_id": product_id,
            "read_episode_to": safe_scope,
            "latest_episode_no": int(latest_episode_no or 0),
        },
        "plot_rows": summary_rows,
        "hooks": hooks,
        "characters": scoped_characters,
        "relations": scoped_relations,
    }


def build_websochat_scope_context_message(scope_context: dict[str, Any]) -> str:
    return build_websochat_scope_context_message_for_subtype(scope_context, "opinion_general")


def _normalize_websochat_scope_match_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def _matches_websochat_query_entity(query_text: str, *values: Any) -> bool:
    normalized_query = _normalize_websochat_scope_match_text(query_text)
    if not normalized_query:
        return False
    for value in values:
        if isinstance(value, (list, tuple, set)):
            for item in value:
                normalized_item = _normalize_websochat_scope_match_text(item)
                if normalized_item and normalized_item in normalized_query:
                    return True
            continue
        normalized_value = _normalize_websochat_scope_match_text(value)
        if normalized_value and normalized_value in normalized_query:
            return True
    return False


def _prioritize_websochat_scope_rows_by_query(
    rows: list[dict[str, Any]],
    *,
    query_text: str | None,
    matcher,
) -> list[dict[str, Any]]:
    if not query_text:
        return rows
    matched = [row for row in rows if matcher(row, query_text)]
    if not matched:
        return rows
    seen = {id(row) for row in matched}
    return matched + [row for row in rows if id(row) not in seen]


def build_websochat_scope_context_message_for_subtype(
    scope_context: dict[str, Any],
    qa_subtype: str | None,
    query_text: str | None = None,
) -> str:
    canon_scope = scope_context.get("canon_scope") or {}
    plot_rows = list(scope_context.get("plot_rows") or [])
    characters = list(scope_context.get("characters") or [])
    relations = list(scope_context.get("relations") or [])
    hooks = list(scope_context.get("hooks") or [])
    resolved_subtype = str(qa_subtype or "opinion_general").strip().lower() or "opinion_general"

    blocks: list[str] = [
        "[참고 규칙]",
        "- 아래 인물/관계 정보는 공개 범위 내 회차를 집계한 참고 신호다.",
        "- 줄거리 요약이나 직접 원문 근거와 충돌하면 줄거리/원문 근거를 우선한다.",
        "[스코프 기준]",
        f"- 공개 답변 범위: 1~{int(canon_scope.get('read_episode_to') or 0)}화",
    ]

    prioritized_characters = _prioritize_websochat_scope_rows_by_query(
        characters,
        query_text=query_text,
        matcher=lambda item, query: _matches_websochat_query_entity(
            query,
            item.get("display_name"),
            item.get("aliases") or [],
        ),
    )
    prioritized_relations = _prioritize_websochat_scope_rows_by_query(
        relations,
        query_text=query_text,
        matcher=lambda item, query: _matches_websochat_query_entity(
            query,
            item.get("source_display_name"),
            item.get("target_display_name"),
            item.get("dominant_relation_tags") or [],
        ),
    )
    prioritized_hooks = hooks
    if query_text:
        matched_hooks = [hook for hook in hooks if _matches_websochat_query_entity(query_text, hook)]
        if matched_hooks:
            seen_hooks = set(matched_hooks)
            prioritized_hooks = matched_hooks + [hook for hook in hooks if hook not in seen_hooks]

    plot_block: list[str] = []
    if plot_rows:
        plot_block.append("[핵심 줄거리]")
        for row in plot_rows[:3]:
            summary_text = str(row.get("summary_text") or "").strip()
            if not summary_text:
                continue
            episode_from = int(row.get("episode_from") or 0)
            episode_to = int(row.get("episode_to") or 0)
            label = f"{episode_from}화" if episode_from == episode_to else f"{episode_from}~{episode_to}화"
            plot_block.append(f"- {label}: {summary_text.splitlines()[0][:180]}")

    character_block: list[str] = []
    if prioritized_characters:
        character_block.append("[반복 등장 인물 신호]")
        for item in prioritized_characters[:6]:
            display_name = str(item.get("display_name") or "").strip()
            if not display_name:
                continue
            character_block.append(
                f"- {display_name}: 등장 {int(item.get('distinct_episode_count') or 0)}화, "
                f"언급 {int(item.get('summary_mention_count') or 0)}회, "
                f"관계 {str(item.get('relation_presence') or '정보 적음')}"
            )

    relation_block: list[str] = []
    if prioritized_relations:
        relation_block.append("[반복 관계 신호]")
        for item in prioritized_relations[:6]:
            source_name = str(item.get("source_display_name") or "").strip()
            target_name = str(item.get("target_display_name") or "").strip()
            tags = ", ".join(_normalize_string_list(item.get("dominant_relation_tags"), limit=3)) or "관계 정보"
            if source_name and target_name:
                relation_block.append(f"- {source_name} -> {target_name}: {tags}")

    hook_block: list[str] = []
    if prioritized_hooks:
        hook_block.append("[미해결 훅]")
        for hook in prioritized_hooks[:4]:
            hook_block.append(f"- {hook}")

    if resolved_subtype in {"relationship"}:
        ordered_blocks = [relation_block, character_block, plot_block, hook_block]
    elif resolved_subtype in {"character_axis", "name_memory"}:
        ordered_blocks = [character_block, relation_block, plot_block, hook_block]
    elif resolved_subtype in {"plot_clarification"}:
        ordered_blocks = [hook_block, plot_block, character_block, relation_block]
    else:
        ordered_blocks = [plot_block, relation_block, character_block, hook_block]

    for block in ordered_blocks:
        if block:
            blocks.extend(block)

    return "\n".join(blocks)
