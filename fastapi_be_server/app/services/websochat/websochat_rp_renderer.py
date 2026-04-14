from __future__ import annotations

from typing import Any

from app.services.ai.ai_chat_service import _call_claude_messages, _extract_text
from app.services.websochat.websochat_game_memory import _normalize_websochat_session_memory
from app.services.websochat.websochat_llm import (
    WEBSOCHAT_RP_TEMPERATURE,
    call_websochat_gemini,
    to_websochat_gemini_contents,
)

WEBSOCHAT_RP_REPLY_MAX_TOKENS = 4096


def _append_prompt_block(blocks: list[str], title: str, lines: list[str]) -> None:
    cleaned = [str(line).strip() for line in lines if str(line).strip()]
    if not cleaned:
        return
    blocks.append(f"[{title}]\n" + "\n".join(cleaned))


def _collect_prompt_terms(*sources: str) -> set[str]:
    terms: set[str] = set()
    for source in sources:
        for token in str(source or "").replace("\n", " ").split():
            normalized = token.strip(" ,.!?\"'()[]{}<>:;")
            if len(normalized) >= 2:
                terms.add(normalized)
    return terms


def _select_rp_examples(
    *,
    examples_payload: list[dict[str, Any]],
    anchor_episode_no: int,
    recent_messages: list[dict[str, str]],
    scene_summary_text: str,
    relationship_stage: str,
) -> list[str]:
    recent_user_text = " ".join(
        str(item.get("content") or "").strip()
        for item in recent_messages[-4:]
        if str(item.get("role") or "") == "user"
    )
    prompt_terms = _collect_prompt_terms(recent_user_text, scene_summary_text, relationship_stage)

    ranked: list[tuple[tuple[int, float, int], str]] = []
    seen_texts: set[str] = set()
    for item in examples_payload:
        example_text = str(item.get("text") or "").strip()
        if not example_text or example_text in seen_texts:
            continue
        seen_texts.add(example_text)
        episode_no = int(item.get("episode_no") or 0)
        confidence = float(item.get("confidence") or 0)
        overlap = 0
        if prompt_terms:
            overlap = sum(1 for term in prompt_terms if term in example_text)
        episode_distance = abs(anchor_episode_no - episode_no) if anchor_episode_no > 0 and episode_no > 0 else 9999
        ranked.append(((-overlap, -confidence, episode_distance), example_text))

    ranked.sort(key=lambda item: item[0])
    return [f"- {text}" for _, text in ranked[:2]]


def _build_recent_repetition_lines(
    *,
    recent_messages: list[dict[str, str]],
    recent_rp_facts: list[str],
) -> list[str]:
    lines = [
        "- 직전 2턴에서 쓴 시작 문장, 같은 필러, 같은 동작 묘사를 그대로 반복하지 마라.",
        "- 특히 같은 숨 고르기, 시선 처리, 미간/한숨/관자놀이 같은 습관 묘사를 연속 사용하지 마라.",
    ]
    recent_assistant_starts: list[str] = []
    for item in reversed(recent_messages):
        if str(item.get("role") or "") != "assistant":
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        first_line = content.splitlines()[0].strip()
        if first_line:
            recent_assistant_starts.append(first_line[:80])
        if len(recent_assistant_starts) >= 2:
            break
    if recent_assistant_starts:
        lines.append("- 최근 assistant 시작 표현:")
        lines.extend(f"  - {line}" for line in recent_assistant_starts)
    if recent_rp_facts:
        lines.append("- 최근 RP 사실은 이어받되, 같은 표현 방식으로 재진술하지 마라.")
    return lines


def build_websochat_rp_system_prompt(
    *,
    product_row: dict[str, Any],
    rp_context: dict[str, Any],
    recent_messages: list[dict[str, str]],
) -> str:
    title = str(product_row.get("title") or "작품").strip()
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    websochat_setting = str(product_row.get("websochatSetting") or "").strip()
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
    session_memory = _normalize_websochat_session_memory(rp_context.get("session_memory") or {})
    relationship_stage = str(session_memory.get("relationship_stage") or "").strip()
    recent_rp_facts = [
        str(item).strip()
        for item in (session_memory.get("recent_rp_facts") or [])
        if str(item).strip()
    ]

    speech_lines = []
    tones = ", ".join(str(item).strip() for item in (speech_style.get("tone") or []) if str(item).strip())
    if tones:
        speech_lines.append(f"- tone: {tones}")
    formality = str(speech_style.get("formality") or "").strip()
    if formality:
        speech_lines.append(f"- formality: {formality}")
    sentence_length = str(speech_style.get("sentence_length") or "").strip()
    if sentence_length:
        speech_lines.append(f"- sentence_length: {sentence_length}")
    habits = ", ".join(str(item).strip() for item in (speech_style.get("habit") or []) if str(item).strip())
    if habits:
        speech_lines.append(f"- habit: {habits}")
    address = str(speech_style.get("address") or "").strip()
    if address:
        speech_lines.append(f"- address: {address}")

    baseline_attitude = str(rp_context.get("baseline_attitude") or "").strip()
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
    anchor_episode_no = int(rp_context.get("anchor_episode_no") or 0)
    anchor_summary_text = str(rp_context.get("anchor_summary_text") or "").strip()
    trajectory_history = [
        item
        for item in (rp_context.get("trajectory_history") or [])
        if isinstance(item, dict)
    ]
    trajectory_lines: list[str] = []
    for item in trajectory_history[:2]:
        episode_no = int(item.get("episode_no") or 0)
        summary_text = str(item.get("summary_text") or "").strip()
        if episode_no <= 0 or not summary_text:
            continue
        trajectory_lines.append(f"- {episode_no}화: {summary_text}")
    raw_recall_context = str(rp_context.get("raw_recall_context") or "").strip()
    scene_lines: list[str] = []
    if str(rp_context.get("rp_mode") or "") == "scene":
        scene_summary = str(rp_context.get("scene_summary_text") or "").strip()
        scene_source = str(rp_context.get("scene_source_text") or "").strip()
        scene_state = str(rp_context.get("scene_state") or "").strip()
        if scene_summary:
            scene_lines.append(f"- 현재 상황: {scene_summary}")
        if scene_state:
            scene_lines.append(f"- 이 시점에서 {display_name}은 {scene_state}")
        if scene_source:
            scene_lines.append(f"- 참고 원문:\n{scene_source}")

    examples = _select_rp_examples(
        examples_payload=examples_payload,
        anchor_episode_no=anchor_episode_no,
        recent_messages=recent_messages,
        scene_summary_text=str(rp_context.get("scene_summary_text") or "").strip(),
        relationship_stage=relationship_stage,
    )

    blocks: list[str] = [f"너는 {display_name}이다."]
    _append_prompt_block(
        blocks,
        "역할 고정",
        [
            f"- 항상 {display_name}로만 반응하라. 말투와 감정선, 기본 태도는 끝까지 {display_name}답게 유지하라.",
            "- 작품 해설, 상황 요약, 분석 답변, 독자 코멘트처럼 말하지 마라. 설명보다 반응과 장면을 우선하라.",
            "- 말투/예시는 목소리와 호흡을 잡는 참고 자료다. 사실 정보의 근거로 쓰지 마라.",
            "- 사실 정보는 세션 메모리, 현재 기준점, 궤적, 원문 참고, 장면 컨텍스트 안에서만 사용하라.",
            "- 공개 범위를 넘는 사실이나 확인되지 않은 속마음, 과거사, 미공개 사건을 만들지 마라.",
            "- 모르면 해설로 빠지지 말고, 현재 장면 안에서 짧게 반응하라.",
            "- 첫 문장을 '이 작품', 'X는', '독자 입장', '정리하면' 같은 해설투로 시작하지 마라.",
        ],
    )
    _append_prompt_block(
        blocks,
        "응답 원칙",
        [
            "- 상대의 방금 말에 바로 반응하는 느낌이 나야 한다.",
            "- 같은 질문, 같은 감정, 같은 버릇말을 되풀이하지 마라.",
            "- 현재 관계 단계에 맞춰 거리감, 호칭, 말의 세기를 조절하라.",
            "- 답은 짧고 선명하게 유지하되, 장면감은 잃지 마라.",
            "- 사용자가 끝내려는 뜻이 아니면 먼저 대화를 닫지 마라.",
        ],
    )
    _append_prompt_block(
        blocks,
        "출력 기본형",
        [
            "- 지문은 필요할 때만 0~1문장 사용하라. 매 턴 반드시 지문으로 시작할 필요는 없다.",
            "- 대사는 1~3문장 중심으로 쓰고, 짧은 질문에는 짧게 받아쳐도 된다.",
            "- 한 응답은 보통 2~5문장 안에서 끝내라.",
            "- 장면이 필요하면 `짧은 지문 -> 대사`로, 즉답이 더 자연스러우면 대사 위주로 답하라.",
        ],
    )
    _append_prompt_block(
        blocks,
        "작품",
        [
            f"- 제목: {title}",
            f"- 최신 공개 회차: {latest_episode_no}화",
        ],
    )
    if websochat_setting:
        _append_prompt_block(
            blocks,
            "작품 톤 가드",
            [
                "- 아래 설정은 작품 톤을 맞추는 보조 가드다. 원문/공개 정보와 충돌하면 원문과 공개 범위를 우선하라.",
                websochat_setting,
            ],
        )
    _append_prompt_block(blocks, "기본 태도", [f"- {baseline_attitude}"] if baseline_attitude else [])
    _append_prompt_block(blocks, "말투", speech_lines)
    _append_prompt_block(blocks, "성격", [f"- {item}" for item in personality_core])
    _append_prompt_block(blocks, "인물 맥락", inventory_lines)

    relation_lines: list[str] = []
    if relationship_stage:
        relation_lines.append(f"- 관계 단계: {relationship_stage}")
    relation_lines.extend(f"- {item}" for item in recent_rp_facts[:4])
    _append_prompt_block(blocks, "최근 흐름", relation_lines)
    _append_prompt_block(
        blocks,
        "최근 반복 억제",
        _build_recent_repetition_lines(
            recent_messages=recent_messages,
            recent_rp_facts=recent_rp_facts,
        ),
    )

    if anchor_episode_no > 0 and anchor_summary_text:
        _append_prompt_block(
            blocks,
            "현재 기준점",
            [
                f"- {anchor_episode_no}화 기준",
                anchor_summary_text,
            ],
        )
    _append_prompt_block(blocks, "캐릭터 궤적 참고", trajectory_lines)
    _append_prompt_block(blocks, "원문 참고", [raw_recall_context] if raw_recall_context else [])
    _append_prompt_block(blocks, "장면 컨텍스트", scene_lines)
    _append_prompt_block(
        blocks,
        "예시 사용 원칙",
        [
            "- 아래 예시는 어휘 결, 호흡, 반응 온도를 참고하기 위한 것이다.",
            "- 문장을 그대로 베끼지 말고, 현재 장면과 관계 단계에 맞는 결만 가져와라.",
            "- 예시보다 현재 장면, 세션 메모리, 원문 참고를 우선하라.",
        ],
    )
    _append_prompt_block(blocks, "선별 예시", examples)

    return "\n\n".join(blocks)


async def generate_websochat_rp_reply_with_gemini(
    *,
    product_row: dict[str, Any],
    user_prompt: str,
    rp_context: dict[str, Any],
    recent_messages: list[dict[str, str]],
) -> str:
    messages = list(recent_messages)
    messages.append({"role": "user", "content": user_prompt})
    return await call_websochat_gemini(
        system_prompt=build_websochat_rp_system_prompt(
            product_row=product_row,
            rp_context=rp_context,
            recent_messages=recent_messages,
        ),
        messages=to_websochat_gemini_contents(messages),
        max_tokens=WEBSOCHAT_RP_REPLY_MAX_TOKENS,
        temperature=WEBSOCHAT_RP_TEMPERATURE,
    )


async def generate_websochat_rp_reply_with_claude(
    *,
    product_row: dict[str, Any],
    user_prompt: str,
    rp_context: dict[str, Any],
    recent_messages: list[dict[str, str]],
) -> str:
    messages = list(recent_messages)
    messages.append({"role": "user", "content": user_prompt})
    response = await _call_claude_messages(
        system_prompt=build_websochat_rp_system_prompt(
            product_row=product_row,
            rp_context=rp_context,
            recent_messages=recent_messages,
        ),
        messages=messages,
        max_tokens=WEBSOCHAT_RP_REPLY_MAX_TOKENS,
    )
    return _extract_text(response.get("content") or []).strip()
