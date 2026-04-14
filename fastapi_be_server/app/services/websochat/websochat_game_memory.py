from __future__ import annotations

import json
import logging
import re
from typing import Any

WEBSOCHAT_ALLOWED_RP_MODES = {"free", "scene"}
WEBSOCHAT_ALLOWED_GAME_MODES = {"ideal_worldcup", "vs_game"}
WEBSOCHAT_ALLOWED_GAME_GENDER_SCOPES = {"male", "female", "mixed"}
WEBSOCHAT_ALLOWED_GAME_CATEGORIES = {
    "romance",
    "date",
    "narrative",
    "power",
    "intelligence",
    "charm",
    "mental",
    "survival",
    "personality",
}
WEBSOCHAT_PENDING_GAME_CATEGORY = "__pending__"
WEBSOCHAT_ALLOWED_VS_GAME_MATCH_MODES = {"direct_match", "criteria_match"}
WEBSOCHAT_ALLOWED_READ_SCOPE_STATES = {"unknown", "none", "known"}
WEBSOCHAT_ALLOWED_READ_SCOPE_SOURCES = {"unknown", "account", "prompt"}
WEBSOCHAT_ALLOWED_RP_STAGES = {"idle", "awaiting_character", "chatting"}
WEBSOCHAT_ALLOWED_PENDING_MODE_ENTRY_GUIDES = {"qa_ready", "rp_select"}
WEBSOCHAT_RP_RECENT_FACT_LIMIT = 6
WEBSOCHAT_QA_RECENT_NOTE_LIMIT = 10
WEBSOCHAT_QA_CORRECTION_LIMIT = 6

logger = logging.getLogger(__name__)


def _normalize_websochat_string_list(raw_value: Any, *, limit: int = 20) -> list[str]:
    items: list[str] = []
    for item in raw_value or []:
        normalized = str(item or "").strip()
        if not normalized or normalized in items:
            continue
        items.append(normalized)
        if len(items) >= limit:
            break
    return items


def _normalize_websochat_qa_corrections(raw_value: Any) -> list[dict[str, str]]:
    normalized_items: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for item in raw_value or []:
        if not isinstance(item, dict):
            continue
        subject = re.sub(r"\s+", " ", str(item.get("subject") or "")).strip()[:80]
        correct_value = re.sub(r"\s+", " ", str(item.get("correct_value") or "")).strip()[:80]
        incorrect_value = re.sub(r"\s+", " ", str(item.get("incorrect_value") or "")).strip()[:80]
        if not subject or not correct_value:
            continue
        key = (subject, correct_value, incorrect_value)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        normalized_items.append(
            {
                "subject": subject,
                "correct_value": correct_value,
                "incorrect_value": incorrect_value,
            }
        )
        if len(normalized_items) >= WEBSOCHAT_QA_CORRECTION_LIMIT:
            break
    return normalized_items


def _normalize_websochat_game_state(game_mode: str, raw_state: Any) -> dict[str, Any]:
    parsed = raw_state if isinstance(raw_state, dict) else {}
    if game_mode == "ideal_worldcup":
        current_bracket: list[list[str]] = []
        for pair in parsed.get("current_bracket") or []:
            if not isinstance(pair, (list, tuple)):
                continue
            normalized_pair = _normalize_websochat_string_list(pair, limit=2)
            if len(normalized_pair) == 2:
                current_bracket.append(normalized_pair)
        current_round = str(parsed.get("current_round") or "").strip() or None
        try:
            current_match_index = max(int(parsed.get("current_match_index") or 0), 0)
        except Exception:
            current_match_index = 0
        try:
            read_episode_to = max(int(parsed.get("read_episode_to") or 0), 0) or None
        except Exception:
            read_episode_to = None
        try:
            requested_bracket_size = int(parsed.get("requested_bracket_size") or 0) or None
        except Exception:
            requested_bracket_size = None
        if requested_bracket_size not in {2, 4, 8}:
            requested_bracket_size = None
        return {
            "current_candidates": _normalize_websochat_string_list(parsed.get("current_candidates"), limit=16),
            "current_bracket": current_bracket,
            "current_round": current_round,
            "current_match_index": current_match_index,
            "picks": _normalize_websochat_string_list(parsed.get("picks"), limit=32),
            "used_pair_keys": _normalize_websochat_string_list(parsed.get("used_pair_keys"), limit=128),
            "last_winner": str(parsed.get("last_winner") or "").strip() or None,
            "read_episode_to": read_episode_to,
            "requested_bracket_size": requested_bracket_size,
        }

    mode = str(parsed.get("mode") or "").strip().lower()
    if mode not in WEBSOCHAT_ALLOWED_VS_GAME_MATCH_MODES:
        mode = None
    try:
        question_index = max(int(parsed.get("question_index") or 0), 0)
    except Exception:
        question_index = 0
    current_match = _normalize_websochat_string_list(parsed.get("current_match"), limit=2)
    return {
        "mode": mode,
        "question_index": question_index,
        "answers": _normalize_websochat_string_list(parsed.get("answers"), limit=64),
        "used_match_keys": _normalize_websochat_string_list(parsed.get("used_match_keys"), limit=128),
        "used_question_keys": _normalize_websochat_string_list(parsed.get("used_question_keys"), limit=128),
        "current_match": current_match,
        "criterion": str(parsed.get("criterion") or "").strip().lower() or None,
        "last_result_summary": str(parsed.get("last_result_summary") or "").strip() or None,
    }


def _normalize_websochat_games_memory(raw_value: Any) -> dict[str, Any]:
    parsed = raw_value if isinstance(raw_value, dict) else {}
    normalized_games: dict[str, Any] = {}
    for game_mode, raw_scopes in parsed.items():
        if game_mode not in WEBSOCHAT_ALLOWED_GAME_MODES or not isinstance(raw_scopes, dict):
            continue
        scope_map: dict[str, Any] = {}
        for gender_scope, raw_categories in raw_scopes.items():
            if gender_scope not in WEBSOCHAT_ALLOWED_GAME_GENDER_SCOPES or not isinstance(raw_categories, dict):
                continue
            category_map: dict[str, Any] = {}
            for category, raw_state in raw_categories.items():
                normalized_category = str(category or "").strip().lower()
                if normalized_category not in (WEBSOCHAT_ALLOWED_GAME_CATEGORIES | {WEBSOCHAT_PENDING_GAME_CATEGORY}):
                    continue
                category_map[normalized_category] = _normalize_websochat_game_state(game_mode, raw_state)
            if category_map:
                scope_map[gender_scope] = category_map
        if scope_map:
            normalized_games[game_mode] = scope_map
    return normalized_games


def _build_websochat_game_context(
    *,
    game_mode: str | None,
    game_gender_scope: str | None,
    game_category: str | None,
    game_match_mode: str | None,
) -> dict[str, Any]:
    return {
        "mode": game_mode if game_mode in WEBSOCHAT_ALLOWED_GAME_MODES else None,
        "gender_scope": game_gender_scope if game_gender_scope in WEBSOCHAT_ALLOWED_GAME_GENDER_SCOPES else None,
        "category": game_category if game_category in WEBSOCHAT_ALLOWED_GAME_CATEGORIES else None,
        "match_mode": game_match_mode if game_match_mode in WEBSOCHAT_ALLOWED_VS_GAME_MATCH_MODES else None,
    }


def _clear_websochat_game_context(session_memory: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_websochat_session_memory(session_memory)
    normalized["active_mode"] = "rp" if normalized.get("active_character") and normalized.get("rp_mode") else None
    normalized["game_context"] = _build_websochat_game_context(
        game_mode=None,
        game_gender_scope=None,
        game_category=None,
        game_match_mode=None,
    )
    normalized["pending_mode_entry_guide"] = None
    return normalized


def _clear_websochat_rp_context(session_memory: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_websochat_session_memory(session_memory)
    normalized["active_character"] = None
    normalized["active_character_label"] = None
    normalized["rp_mode"] = None
    normalized["pending_rp_character_selection"] = False
    normalized["scene_episode_no"] = None
    normalized["relationship_stage"] = None
    normalized["recent_rp_facts"] = []
    normalized["pending_mode_entry_guide"] = None
    active_game_mode = str((normalized.get("game_context") or {}).get("mode") or "").strip().lower()
    normalized["active_mode"] = active_game_mode if active_game_mode in WEBSOCHAT_ALLOWED_GAME_MODES else None
    return normalized


def _resolve_websochat_rp_stage(session_memory: dict[str, Any]) -> str:
    normalized = _normalize_websochat_session_memory(session_memory)
    if bool(normalized.get("pending_rp_character_selection")):
        return "awaiting_character"
    if normalized.get("active_character") and normalized.get("rp_mode") in WEBSOCHAT_ALLOWED_RP_MODES:
        return "chatting"
    return "idle"


def _normalize_websochat_session_memory(raw_value: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    if isinstance(raw_value, str) and raw_value.strip():
        try:
            loaded = json.loads(raw_value)
            if isinstance(loaded, dict):
                parsed = loaded
        except Exception:
            parsed = {}
    elif isinstance(raw_value, dict):
        parsed = raw_value

    try:
        read_episode_to = max(int(parsed.get("read_episode_to") or 0), 0) or None
    except Exception:
        read_episode_to = None
    read_scope_state = str(parsed.get("read_scope_state") or "").strip().lower() or None
    if read_scope_state not in WEBSOCHAT_ALLOWED_READ_SCOPE_STATES:
        read_scope_state = "known" if read_episode_to else "unknown"
    read_scope_source = str(parsed.get("read_scope_source") or "").strip().lower() or None
    if read_scope_source not in WEBSOCHAT_ALLOWED_READ_SCOPE_SOURCES:
        read_scope_source = "unknown"

    rp_mode = str(parsed.get("rp_mode") or "").strip().lower()
    if rp_mode not in WEBSOCHAT_ALLOWED_RP_MODES:
        rp_mode = None
    active_character = str(parsed.get("active_character") or "").strip() or None
    active_character_label = str(parsed.get("active_character_label") or "").strip() or None
    pending_rp_character_selection = bool(parsed.get("pending_rp_character_selection"))
    pending_mode_entry_guide = str(parsed.get("pending_mode_entry_guide") or "").strip().lower() or None
    if pending_mode_entry_guide not in WEBSOCHAT_ALLOWED_PENDING_MODE_ENTRY_GUIDES:
        pending_mode_entry_guide = None
    try:
        scene_episode_no = int(parsed.get("scene_episode_no") or 0) or None
    except Exception:
        scene_episode_no = None
    relationship_stage = str(parsed.get("relationship_stage") or "").strip() or "neutral"
    recent_rp_facts = [
        str(item).strip()
        for item in (parsed.get("recent_rp_facts") or [])
        if str(item).strip()
    ][:WEBSOCHAT_RP_RECENT_FACT_LIMIT]
    qa_recent_notes = [
        str(item).strip()
        for item in (parsed.get("qa_recent_notes") or [])
        if str(item).strip()
    ][:WEBSOCHAT_QA_RECENT_NOTE_LIMIT]
    qa_corrections = _normalize_websochat_qa_corrections(parsed.get("qa_corrections"))
    raw_game_context = parsed.get("game_context") if isinstance(parsed.get("game_context"), dict) else {}
    game_context = _build_websochat_game_context(
        game_mode=str(raw_game_context.get("mode") or "").strip().lower() or None,
        game_gender_scope=str(raw_game_context.get("gender_scope") or "").strip().lower() or None,
        game_category=str(raw_game_context.get("category") or "").strip().lower() or None,
        game_match_mode=str(raw_game_context.get("match_mode") or "").strip().lower() or None,
    )
    games = _normalize_websochat_games_memory(parsed.get("games"))
    active_mode = str(parsed.get("active_mode") or "").strip().lower() or None
    if active_mode not in ({"rp"} | WEBSOCHAT_ALLOWED_GAME_MODES):
        active_mode = None
    if active_mode in WEBSOCHAT_ALLOWED_GAME_MODES and game_context.get("mode") != active_mode:
        active_mode = game_context.get("mode")
    if active_mode == "rp" and (not active_character or not rp_mode):
        active_mode = None
    if active_character and pending_rp_character_selection:
        pending_rp_character_selection = False
    if not active_character:
        active_character_label = None
    return {
        "active_mode": active_mode,
        "read_episode_to": read_episode_to,
        "read_scope_state": read_scope_state,
        "read_scope_source": read_scope_source,
        "active_character": active_character,
        "active_character_label": active_character_label,
        "rp_mode": rp_mode,
        "pending_rp_character_selection": pending_rp_character_selection,
        "pending_mode_entry_guide": pending_mode_entry_guide,
        "scene_episode_no": scene_episode_no,
        "relationship_stage": relationship_stage,
        "recent_rp_facts": recent_rp_facts,
        "qa_recent_notes": qa_recent_notes,
        "qa_corrections": qa_corrections,
        "game_context": game_context,
        "games": games,
    }


def _merge_websochat_session_memory(
    *,
    base_memory: dict[str, Any],
    rp_mode: str | None,
    active_character: str | None,
    active_character_label: str | None,
    scene_episode_no: int | None,
    game_mode: str | None = None,
    game_gender_scope: str | None = None,
    game_category: str | None = None,
    game_match_mode: str | None = None,
    game_read_episode_to: int | None = None,
) -> dict[str, Any]:
    next_memory = _normalize_websochat_session_memory(base_memory)
    next_memory["pending_mode_entry_guide"] = None

    normalized_active_character = str(active_character or "").strip() or None
    normalized_active_character_label = str(active_character_label or "").strip() or None
    if normalized_active_character is not None:
        next_memory["active_character"] = normalized_active_character
        next_memory["active_character_label"] = (
            normalized_active_character_label
            or str(next_memory.get("active_character_label") or "").strip()
            or None
        )
        next_memory["pending_rp_character_selection"] = False

    normalized_scene_episode_no = int(scene_episode_no or 0) or None
    requested_mode = str(rp_mode or "").strip().lower()
    if normalized_scene_episode_no:
        next_memory["scene_episode_no"] = normalized_scene_episode_no
        next_memory["rp_mode"] = "scene"
    elif requested_mode in WEBSOCHAT_ALLOWED_RP_MODES:
        next_memory["rp_mode"] = requested_mode
        if requested_mode != "scene":
            next_memory["scene_episode_no"] = None

    if next_memory.get("rp_mode") == "scene" and not next_memory.get("scene_episode_no"):
        next_memory["rp_mode"] = "free"
    if not next_memory.get("active_character"):
        next_memory["active_character_label"] = None
        next_memory["rp_mode"] = None
        next_memory["scene_episode_no"] = None

    normalized_game_mode = str(game_mode or "").strip().lower() or None
    if normalized_game_mode not in WEBSOCHAT_ALLOWED_GAME_MODES:
        normalized_game_mode = None
    normalized_gender_scope = str(game_gender_scope or "").strip().lower() or None
    if normalized_gender_scope not in WEBSOCHAT_ALLOWED_GAME_GENDER_SCOPES:
        normalized_gender_scope = None
    normalized_game_category = str(game_category or "").strip().lower() or None
    if normalized_game_category not in WEBSOCHAT_ALLOWED_GAME_CATEGORIES:
        normalized_game_category = None
    normalized_game_match_mode = str(game_match_mode or "").strip().lower() or None
    if normalized_game_match_mode not in WEBSOCHAT_ALLOWED_VS_GAME_MATCH_MODES:
        normalized_game_match_mode = None
    normalized_game_read_episode_to = max(int(game_read_episode_to or 0), 0) or None
    if normalized_game_read_episode_to and next_memory.get("read_scope_source") != "prompt":
        next_memory["read_episode_to"] = normalized_game_read_episode_to
        next_memory["read_scope_state"] = "known"
        next_memory["read_scope_source"] = "account"

    has_game_inputs = any(
        value is not None and str(value).strip() != ""
        for value in [game_mode, game_gender_scope, game_category, game_match_mode, normalized_game_read_episode_to]
    )
    effective_game_mode = normalized_game_mode or str((next_memory.get("game_context") or {}).get("mode") or "").strip().lower() or None
    if effective_game_mode not in WEBSOCHAT_ALLOWED_GAME_MODES:
        effective_game_mode = None

    if effective_game_mode and has_game_inputs:
        next_memory["active_mode"] = effective_game_mode
        next_memory["game_context"] = _build_websochat_game_context(
            game_mode=effective_game_mode,
            game_gender_scope=normalized_gender_scope or next_memory.get("game_context", {}).get("gender_scope"),
            game_category=normalized_game_category,
            game_match_mode=normalized_game_match_mode if effective_game_mode == "vs_game" else None,
        )
        games = dict(next_memory.get("games") or {})
        scope_map = dict((games.get(effective_game_mode) or {}))
        if next_memory["game_context"].get("gender_scope"):
            category_map = dict((scope_map.get(next_memory["game_context"]["gender_scope"]) or {}))
            if next_memory["game_context"].get("category"):
                existing_state = category_map.get(next_memory["game_context"]["category"]) or {}
                next_state = _normalize_websochat_game_state(effective_game_mode, existing_state)
                if effective_game_mode == "vs_game" and next_memory["game_context"].get("match_mode"):
                    next_state["mode"] = next_memory["game_context"]["match_mode"]
                if effective_game_mode == "ideal_worldcup" and normalized_game_read_episode_to:
                    next_state["read_episode_to"] = normalized_game_read_episode_to
                category_map[next_memory["game_context"]["category"]] = next_state
            scope_map[next_memory["game_context"]["gender_scope"]] = category_map
        games[effective_game_mode] = scope_map
        next_memory["games"] = _normalize_websochat_games_memory(games)

    has_rp_inputs = any(
        value is not None and str(value).strip() != ""
        for value in [rp_mode, active_character, scene_episode_no]
    )
    if has_rp_inputs and next_memory.get("active_character") and next_memory.get("rp_mode"):
        next_memory["active_mode"] = "rp"
        next_memory["pending_rp_character_selection"] = False

    return next_memory
def _resolve_websochat_active_character_label(session_memory: dict[str, Any]) -> str | None:
    normalized = _normalize_websochat_session_memory(session_memory)
    explicit_label = str(normalized.get("active_character_label") or "").strip()
    if explicit_label:
        return explicit_label

    active_character = str(normalized.get("active_character") or "").strip()
    if not active_character:
        return None
    if "named:" in active_character:
        return active_character.split("named:", 1)[1].strip() or None
    return active_character or None


def _update_websochat_session_memory_after_reply(
    session_memory: dict[str, Any],
    *,
    user_prompt: str,
    assistant_reply: str,
) -> dict[str, Any]:
    next_memory = _normalize_websochat_session_memory(session_memory)
    next_memory["pending_mode_entry_guide"] = None
    if next_memory.get("active_character") and next_memory.get("rp_mode"):
        facts = list(next_memory.get("recent_rp_facts") or [])
        prompt_preview = re.sub(r"\s+", " ", str(user_prompt or "")).strip()[:80]
        reply_preview = re.sub(r"\s+", " ", str(assistant_reply or "")).strip()[:80]
        if prompt_preview:
            facts.append(f"유저: {prompt_preview}")
        if reply_preview:
            facts.append(f"캐릭터: {reply_preview}")
        next_memory["recent_rp_facts"] = facts[-WEBSOCHAT_RP_RECENT_FACT_LIMIT:]
        return next_memory

    prompt_preview = re.sub(r"\s+", " ", str(user_prompt or "")).strip()
    prompt_preview = prompt_preview[:120]
    if prompt_preview:
        notes = list(next_memory.get("qa_recent_notes") or [])
        note = f"최근 논의 축: {prompt_preview}"
        if note and (not notes or notes[-1] != note):
            notes.append(note)
        next_memory["qa_recent_notes"] = notes[-WEBSOCHAT_QA_RECENT_NOTE_LIMIT:]
        logger.info(
            "websochat qa_note_saved note=%s total=%s",
            note,
            len(next_memory["qa_recent_notes"]),
        )
    return next_memory


def _merge_websochat_qa_corrections(
    session_memory: dict[str, Any],
    corrections: list[dict[str, str]],
) -> dict[str, Any]:
    next_memory = _normalize_websochat_session_memory(session_memory)
    normalized_updates = _normalize_websochat_qa_corrections(corrections)
    if not normalized_updates:
        return next_memory

    merged_by_subject: dict[str, dict[str, str]] = {}
    for item in next_memory.get("qa_corrections") or []:
        subject = str(item.get("subject") or "").strip()
        if subject:
            merged_by_subject[subject] = dict(item)
    for item in normalized_updates:
        merged_by_subject[item["subject"]] = item

    merged_items = list(merged_by_subject.values())[-WEBSOCHAT_QA_CORRECTION_LIMIT:]
    next_memory["qa_corrections"] = merged_items
    logger.info(
        "websochat qa_corrections_merged total=%s corrections=%s",
        len(merged_items),
        merged_items,
    )
    return next_memory


def _serialize_websochat_session_memory(session_memory: dict[str, Any]) -> str | None:
    normalized = _normalize_websochat_session_memory(session_memory)
    has_rp_state = bool(normalized.get("active_character") and normalized.get("rp_mode"))
    has_pending_rp_state = bool(normalized.get("pending_rp_character_selection"))
    has_game_state = bool(normalized.get("game_context", {}).get("mode"))
    has_scope_state = bool(int(normalized.get("read_episode_to") or 0))
    has_non_read_scope_state = normalized.get("read_scope_state") == "none"
    has_qa_memory = bool(normalized.get("qa_recent_notes"))
    has_qa_corrections = bool(normalized.get("qa_corrections"))
    if not has_rp_state and not has_pending_rp_state and not has_game_state and not has_scope_state and not has_non_read_scope_state and not has_qa_memory and not has_qa_corrections:
        return None
    return json.dumps(normalized, ensure_ascii=False)
