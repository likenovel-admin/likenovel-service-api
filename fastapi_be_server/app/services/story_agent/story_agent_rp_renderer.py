from __future__ import annotations

from typing import Any

from app.services.ai.ai_chat_service import _call_claude_messages, _extract_text
from app.services.story_agent.story_agent_game_memory import _normalize_story_agent_session_memory
from app.services.story_agent.story_agent_llm import (
    STORY_AGENT_REPLY_MAX_TOKENS,
    call_story_agent_gemini,
    to_story_agent_gemini_contents,
)


def build_story_agent_rp_system_prompt(
    *,
    product_row: dict[str, Any],
    rp_context: dict[str, Any],
) -> str:
    display_name = str(rp_context.get("display_name") or "캐릭터").strip()
    speech_style = rp_context.get("speech_style") or {}
    personality_core = [
        str(item).strip()
        for item in (rp_context.get("personality_core") or [])
        if str(item).strip()
    ]
    examples = [
        str(item.get("text") or "").strip()
        for item in (rp_context.get("examples") or [])
        if str(item.get("text") or "").strip()
    ][:5]
    session_memory = _normalize_story_agent_session_memory(rp_context.get("session_memory") or {})
    memory_lines: list[str] = []
    if str(session_memory.get("relationship_stage") or "").strip():
        memory_lines.append(f"- 관계 단계: {session_memory['relationship_stage']}")
    for item in session_memory.get("recent_rp_facts") or []:
        memory_lines.append(f"- {item}")

    speech_lines = [
        f"- tone: {', '.join(str(item) for item in (speech_style.get('tone') or []) if str(item).strip())}",
        f"- formality: {str(speech_style.get('formality') or '').strip()}",
        f"- sentence_length: {str(speech_style.get('sentence_length') or '').strip()}",
        f"- habit: {', '.join(str(item) for item in (speech_style.get('habit') or []) if str(item).strip())}",
        f"- address: {str(speech_style.get('address') or '').strip()}",
    ]
    speech_block = "\n".join(line for line in speech_lines if not line.endswith(": "))
    personality_block = "\n".join(f"- {item}" for item in personality_core)
    example_block = "\n".join(f"- {item}" for item in examples)
    memory_block = "\n".join(memory_lines)
    inventory_payload = rp_context.get("inventory") or {}
    inventory_lines: list[str] = []
    if inventory_payload:
        first_seen_episode_no = int(inventory_payload.get("first_seen_episode_no") or 0)
        distinct_episode_count = int(inventory_payload.get("distinct_episode_count") or 0)
        relation_presence = str(inventory_payload.get("relation_presence") or "").strip()
        action_presence = str(inventory_payload.get("action_presence") or "").strip()
        if first_seen_episode_no > 0:
            inventory_lines.append(f"- 최초 등장: {first_seen_episode_no}화")
        if distinct_episode_count > 0:
            inventory_lines.append(f"- 반복 등장도: {distinct_episode_count}화")
        if relation_presence:
            inventory_lines.append(f"- 관계 존재감: {relation_presence}")
        if action_presence:
            inventory_lines.append(f"- 행동 존재감: {action_presence}")
    inventory_block = "\n".join(inventory_lines)

    scene_block = ""
    if str(rp_context.get("rp_mode") or "") == "scene":
        scene_summary = str(rp_context.get("scene_summary_text") or "").strip()
        scene_source = str(rp_context.get("scene_source_text") or "").strip()
        scene_state = str(rp_context.get("scene_state") or "").strip()
        parts = []
        if scene_summary:
            parts.append(f"현재 상황: {scene_summary}")
        if scene_state:
            parts.append(f"이 시점에서 {display_name}은 {scene_state}")
        if scene_source:
            parts.append(f"참고 원문:\n{scene_source}")
        if parts:
            scene_block = "\n\n[장면 컨텍스트]\n" + "\n".join(parts)

    return (
        f"너는 {display_name}이다.\n\n"
        "[절대 규칙]\n"
        f"- 항상 {display_name}으로 말하라. 3인칭 서술, 해설, 메타 설명 금지.\n"
        "- 사용자가 제시하는 상황은 수용하라. 시대나 장소가 원작과 달라도 거부하지 마라.\n"
        "- 대신 말투, 성격, 반응 방식은 유지하라.\n"
        "- 답변 끝에는 행동 또는 감정 묘사 1줄과, 대화를 이어가는 짧은 말 1마디를 붙여라.\n"
        "- 사용자가 끝내려는 뜻이 아니면 먼저 대화를 닫지 마라.\n"
        "- 원작 공개 범위를 넘는 사실은 단정하지 마라.\n\n"
        f"[작품]\n- 제목: {str(product_row.get('title') or '').strip()}\n"
        f"- 최신 공개 회차: {int(product_row.get('latestEpisodeNo') or 0)}화\n\n"
        f"{f'[인물 맥락]\\n{inventory_block}\\n\\n' if inventory_block else ''}"
        f"[말투]\n{speech_block or '- 정보 없음'}\n\n"
        f"[성격]\n{personality_block or '- 정보 없음'}\n\n"
        f"[참고 대사]\n{example_block or '- 정보 없음'}"
        f"{f'\\n\\n[세션 메모리]\\n{memory_block}' if memory_block else ''}"
        f"{scene_block}"
    )


async def generate_story_agent_rp_reply_with_gemini(
    *,
    product_row: dict[str, Any],
    user_prompt: str,
    rp_context: dict[str, Any],
    recent_messages: list[dict[str, str]],
) -> str:
    messages = list(recent_messages)
    messages.append({"role": "user", "content": user_prompt})
    return await call_story_agent_gemini(
        system_prompt=build_story_agent_rp_system_prompt(product_row=product_row, rp_context=rp_context),
        messages=to_story_agent_gemini_contents(messages),
        max_tokens=STORY_AGENT_REPLY_MAX_TOKENS,
    )


async def generate_story_agent_rp_reply_with_claude(
    *,
    product_row: dict[str, Any],
    user_prompt: str,
    rp_context: dict[str, Any],
    recent_messages: list[dict[str, str]],
) -> str:
    messages = list(recent_messages)
    messages.append({"role": "user", "content": user_prompt})
    response = await _call_claude_messages(
        system_prompt=build_story_agent_rp_system_prompt(product_row=product_row, rp_context=rp_context),
        messages=messages,
        max_tokens=STORY_AGENT_REPLY_MAX_TOKENS,
    )
    return _extract_text(response.get("content") or []).strip()
