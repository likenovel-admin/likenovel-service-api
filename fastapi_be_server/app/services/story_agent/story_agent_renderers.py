from __future__ import annotations

from typing import Any

from app.const import settings
from app.services.ai.ai_chat_service import _call_claude_messages, _extract_text
from app.services.story_agent.story_agent_game_memory import (
    STORY_AGENT_ALLOWED_GAME_MODES,
    _normalize_story_agent_session_memory,
)
from app.services.story_agent.story_agent_llm import call_story_agent_gemini, to_story_agent_gemini_contents


async def call_story_agent_game_host_model(
    *,
    system_prompt: str,
    user_prompt: str,
) -> str:
    if settings.GEMINI_API_KEY:
        return await call_story_agent_gemini(
            system_prompt=system_prompt,
            messages=to_story_agent_gemini_contents([{"role": "user", "content": user_prompt}]),
            max_tokens=640,
        )
    response = await _call_claude_messages(
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=640,
    )
    return _extract_text(response.get("content") or "").strip()


async def generate_story_agent_vs_comparison(
    *,
    product_row: dict[str, Any],
    category: str,
    match_pair: list[dict[str, Any]],
) -> str:
    left = match_pair[0]
    right = match_pair[1]
    category_label_map = {
        "romance": "연애형",
        "date": "데이트형",
        "narrative": "서사적으로 꽂히는 힘",
        "power": "파워",
        "intelligence": "지능",
        "charm": "매력",
        "mental": "멘탈",
        "survival": "생존력",
        "personality": "성격",
    }
    system_prompt = (
        "너는 스토리 에이전트의 VS게임 진행자다. "
        "캐릭터 RP를 하지 말고, 진행자 톤으로 비교하라. "
        "승패를 한쪽으로 정하더라도 근거를 2~3개 들고, 마지막엔 다음 매치 또는 다른 기준을 제안하라."
    )
    user_prompt = (
        f"작품: {str(product_row.get('title') or '').strip()}\n"
        f"기준: {category_label_map.get(category, category)}\n\n"
        f"[후보 A]\n이름: {left['display_name']}\n"
        f"성격: {' / '.join(left['personality_core']) or '-'}\n"
        f"태도: {left['baseline_attitude'] or '-'}\n"
        f"예시 대사: {' / '.join(left['examples']) or '-'}\n\n"
        f"[후보 B]\n이름: {right['display_name']}\n"
        f"성격: {' / '.join(right['personality_core']) or '-'}\n"
        f"태도: {right['baseline_attitude'] or '-'}\n"
        f"예시 대사: {' / '.join(right['examples']) or '-'}\n\n"
        "형식:\n"
        "1. 누가 우세한지 한 줄\n"
        "2. 근거 2~3줄\n"
        "3. 마지막에 다음 VS를 이어갈지 짧게 묻기"
    )
    return await call_story_agent_game_host_model(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )


def build_story_agent_game_guide_reply(
    *,
    session_memory: dict[str, Any],
    product_row: dict[str, Any],
    read_scope_label: str | None = None,
) -> str | None:
    normalized = _normalize_story_agent_session_memory(session_memory)
    if normalized.get("active_mode") not in STORY_AGENT_ALLOWED_GAME_MODES:
        return None

    game_context = normalized.get("game_context") or {}
    game_mode = str(game_context.get("mode") or "").strip().lower()
    if game_mode not in STORY_AGENT_ALLOWED_GAME_MODES:
        return None

    title = str(product_row.get("title") or "").strip()
    gender_scope = str(game_context.get("gender_scope") or "").strip().lower()
    gender_label = {
        "male": "남성 버전",
        "female": "여성 버전",
        "mixed": "섞어서",
    }.get(gender_scope, "")
    category = str(game_context.get("category") or "").strip().lower()
    category_label_map = {
        "romance": "연애/호감",
        "date": "데이트 상대로 끌리는 기준",
        "narrative": "서사적으로 제일 꽂히는 기준",
        "power": "파워",
        "intelligence": "지능",
        "charm": "매력",
        "mental": "멘탈",
        "survival": "생존력",
        "personality": "성격",
    }
    read_episode_to = max(int(normalized.get("read_episode_to") or 0), 0)
    resolved_read_scope_label = str(read_scope_label or "").strip()
    if not resolved_read_scope_label and read_episode_to > 0:
        resolved_read_scope_label = f"{read_episode_to}화"
    read_scope_prefix = (
        f"읽은 범위는 {resolved_read_scope_label}까지로 잡아둘게.\n\n"
        if resolved_read_scope_label
        else ""
    )

    if game_mode == "ideal_worldcup":
        if not gender_scope:
            return (
                f"좋아. {title} 이상형월드컵으로 갈게.\n\n"
                f"{read_scope_prefix}"
                "1. 남성 버전\n"
                "2. 여성 버전\n"
                "3. 섞어서\n\n"
                "어느 쪽으로 할래?"
            )
        if not category:
            return (
                f"좋아. {title} {gender_label} 이상형월드컵으로 갈게.\n\n"
                f"{read_scope_prefix}"
                "1. 연애/호감 기준\n"
                "2. 데이트 상대로 끌리는 기준\n"
                "3. 서사적으로 제일 꽂히는 기준\n\n"
                "어떤 기준으로 할래?"
            )
        return (
            f"좋아. {title} {gender_label} / {category_label_map.get(category, category)} 기준으로 갈게.\n"
            f"{read_scope_prefix}"
            "다음 단계에서 후보를 정리해서 4강 또는 8강 브래킷으로 바로 붙일 수 있게 준비할게."
        )

    match_mode = str(game_context.get("match_mode") or "").strip().lower()
    if not gender_scope:
        return (
            f"좋아. {title} VS게임으로 갈게.\n\n"
            "1. 남성 버전\n"
            "2. 여성 버전\n"
            "3. 섞어서\n\n"
            "어느 쪽으로 할래?"
        )
    if not match_mode:
        return (
            f"좋아. {title} {gender_label} VS게임으로 갈게.\n\n"
            "1. 누구와 누구를 직접 붙여볼래\n"
            "2. 파워/지능/매력 같은 기준부터 고를래\n\n"
            "어느 방식으로 갈래?"
        )
    if match_mode == "direct_match":
        return (
            f"좋아. {title} {gender_label} 직접 매치업으로 갈게.\n"
            "붙여볼 두 캐릭터를 말해줘. 예: 엔데온트라 vs 펜데"
        )
    if not category:
        return (
            f"좋아. {title} {gender_label} 기준 매치업으로 갈게.\n\n"
            "1. 파워\n"
            "2. 지능\n"
            "3. 매력\n"
            "4. 멘탈\n"
            "5. 생존력\n"
            "6. 연애형\n"
            "7. 데이트형\n"
            "8. 성격형\n\n"
            "어떤 기준으로 붙여볼까?"
        )
    return (
        f"좋아. {title} {gender_label} / {category_label_map.get(category, category)} 기준 VS로 갈게.\n"
        "다음 단계에서 매치업 후보를 고르고 바로 붙일 수 있게 준비할게."
    )


def build_story_agent_vs_disabled_reply() -> str:
    return (
        "VS게임은 지금 보류했어.\n"
        "작품마다 비교축이 달라서 고정 규칙으로 내면 품질이 틀어져.\n"
        "지금은 이상형월드컵이나 캐릭터 채팅으로 이어가자."
    )
