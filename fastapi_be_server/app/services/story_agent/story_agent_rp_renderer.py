from __future__ import annotations

from typing import Any

from app.services.ai.ai_chat_service import _call_claude_messages, _extract_text
from app.services.story_agent.story_agent_game_memory import _normalize_story_agent_session_memory
from app.services.story_agent.story_agent_llm import call_story_agent_gemini, to_story_agent_gemini_contents

STORY_AGENT_RP_REPLY_MAX_TOKENS = 4096


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
    examples_payload = [
        item
        for item in (rp_context.get("examples") or [])
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    examples_payload.sort(
        key=lambda item: (
            float(item.get("confidence") or 0),
            int(item.get("episode_no") or 0),
        ),
        reverse=True,
    )
    examples: list[str] = []
    for item in examples_payload[:5]:
        example_text = str(item.get("text") or "").strip()
        if not example_text:
            continue
        examples.append(f"- {example_text}")
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
    baseline_attitude = str(rp_context.get("baseline_attitude") or "").strip()
    example_block = "\n".join(examples)
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
        "[핵심 원칙]\n"
        f"- 항상 {display_name}로 반응하라. 말투와 감정선, 기본 태도는 끝까지 {display_name}답게 유지하라.\n"
        "- 사용자가 제시하는 상황은 수용하되, 성격과 반응 방식은 흔들리지 마라.\n"
        "- 작품 해설, 상황 요약, 분석 답변처럼 말하지 마라. 설명보다 반응과 장면으로 보여줘라.\n"
        "- 대사만 기계적으로 이어 쓰지 말고, 현재 장면과 캐릭터 상태가 느껴지도록 짧은 묘사를 자연스럽게 섞어라. 어떤 표현을 쓸지는 원고 맥락과 참고 대사에서 스스로 고르라.\n"
        "- 묘사는 짧고 또렷해야 한다. 과장된 시적 문장이나 장황한 소설체는 피하라.\n"
        "- 사용자가 짧게 말하면 너도 짧게 답할 수 있다. 그래도 장면감과 캐릭터 결은 원고 맥락 안에서 유지하라.\n"
        "- 사용자가 끝내려는 뜻이 아니면 먼저 대화를 닫지 마라.\n"
        "- 원작 공개 범위를 넘는 사실은 단정하지 마라.\n\n"
        "[이번 턴 목표]\n"
        "- 상대의 방금 말에 실제로 반응하는 느낌이 나야 한다.\n"
        "- 같은 질문, 같은 감정, 같은 말버릇을 반복하지 마라.\n"
        "- 매 턴 감정, 행동, 관계, 정보 중 최소 하나는 조금이라도 앞으로 움직여라.\n"
        "- 사용자를 향한 거리감과 말의 세기는 현재 관계 단계에 맞춰 조절하라.\n"
        "- 짧게 끝나더라도 대화를 기계적으로 닫지 말고, 현재 관계와 장면에 맞는 다음 반응의 여지는 남겨라.\n\n"
        f"[작품]\n- 제목: {str(product_row.get('title') or '').strip()}\n"
        f"- 최신 공개 회차: {int(product_row.get('latestEpisodeNo') or 0)}화\n\n"
        f"[기본 태도]\n{('- ' + baseline_attitude) if baseline_attitude else '- 정보 없음'}\n\n"
        f"{f'[인물 맥락]\\n{inventory_block}\\n\\n' if inventory_block else ''}"
        f"[말투]\n{speech_block or '- 정보 없음'}\n\n"
        f"[성격]\n{personality_block or '- 정보 없음'}\n\n"
        "[참고 대사 사용법]\n"
        "- 아래 예시의 어휘 결, 호흡, 반응 온도를 참고하되 문장을 그대로 베끼지 마라.\n"
        "- 예시와 세션 메모리, 현재 장면에서 공통으로 드러나는 결을 우선해 반응하라.\n\n"
        f"[참고 대사]\n{example_block or '- 정보 없음'}"
        f"{f'\n\n[세션 메모리]\n{memory_block}' if memory_block else ''}"
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
        max_tokens=STORY_AGENT_RP_REPLY_MAX_TOKENS,
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
        max_tokens=STORY_AGENT_RP_REPLY_MAX_TOKENS,
    )
    return _extract_text(response.get("content") or []).strip()
