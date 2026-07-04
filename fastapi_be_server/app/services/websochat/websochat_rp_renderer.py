from __future__ import annotations

import json
from typing import Any

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


def _compact_character_chat_opening_asset(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        return {}
    compact: dict[str, Any] = {}
    for key in (
        "opening_message",
        "opening_scene",
        "user_role",
        "character_drive",
        "agency_contract",
        "progression_engine",
        "user_affordance_contract",
        "canon_safe_expansion",
        "progression",
    ):
        value = payload.get(key)
        if value not in (None, "", [], {}):
            compact[key] = value
    return compact


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


def _classify_character_chat_user_intent(user_text: str) -> str:
    text = str(user_text or "").strip()
    if not text:
        return "none"
    if any(token in text for token in ("작품", "원작", "앞으로", "스포", "설명", "줄거리", "결말")):
        return "asks_lore"
    if any(token in text for token in ("싫", "안 해", "못 해", "잠깐", "기다", "거절")):
        return "refuses_or_delays"
    if any(token in text for token in ("너 누구", "정체", "수상", "믿을 수", "왜 여기")):
        return "hostile_or_suspicious"
    if text.endswith("?") or text.endswith("？") or "?" in text:
        return "asks_question"
    if len(text) <= 8:
        return "short_or_ambiguous"
    return "responds_to_scene"


def build_character_chat_runtime_turn_state_v1(
    *,
    recent_messages: list[dict[str, str]],
    has_prior_assistant_reply: bool,
    current_user_prompt: str = "",
) -> dict[str, Any]:
    assistant_starts: list[str] = []
    assistant_reply_count = 0
    for item in recent_messages:
        if str(item.get("role") or "").strip().lower() != "assistant":
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        assistant_reply_count += 1
        first_line = content.splitlines()[0].strip()
        if first_line and first_line not in assistant_starts:
            assistant_starts.append(first_line[:80])

    latest_user_text = str(current_user_prompt or "").strip()
    if not latest_user_text:
        for item in reversed(recent_messages):
            if str(item.get("role") or "").strip().lower() == "user":
                latest_user_text = str(item.get("content") or "").strip()
                break
    latest_user_intent = _classify_character_chat_user_intent(latest_user_text)

    stall_count = 1 if latest_user_intent == "short_or_ambiguous" and current_user_prompt else 0
    for item in reversed(recent_messages):
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        if _classify_character_chat_user_intent(str(item.get("content") or "")) == "short_or_ambiguous":
            stall_count += 1
            continue
        break

    if not has_prior_assistant_reply:
        scene_phase = "opening"
        next_required_move = "scene_opening"
    elif stall_count >= 2:
        scene_phase = "complication"
        next_required_move = "state_change"
    elif latest_user_intent == "asks_lore":
        scene_phase = "choice"
        next_required_move = "answer_briefly_then_return_to_pressure"
    elif latest_user_intent == "refuses_or_delays":
        scene_phase = "choice"
        next_required_move = "offer_alternative_without_stalling"
    elif latest_user_intent == "hostile_or_suspicious":
        scene_phase = "choice"
        next_required_move = "one_line_boundary_then_scene_pressure"
    else:
        scene_phase = "choice" if assistant_reply_count <= 2 else "complication"
        next_required_move = "progress_delta"

    return {
        "schema_version": "runtime_turn_state_v1",
        "turn_index_in_scene": assistant_reply_count,
        "scene_phase": scene_phase,
        "latest_user_intent": latest_user_intent,
        "stall_count": stall_count,
        "next_required_move": next_required_move,
        "must_not_repeat": assistant_starts[-2:],
    }


def build_websochat_rp_system_prompt(
    *,
    product_row: dict[str, Any],
    rp_context: dict[str, Any],
    recent_messages: list[dict[str, str]],
    current_user_prompt: str = "",
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
    is_character_chat_session = (
        str(session_memory.get("session_kind") or "").strip().lower()
        == "character_chat"
    )
    has_prior_assistant_reply = any(
        str(item.get("role") or "").strip().lower() == "assistant"
        and str(item.get("content") or "").strip()
        for item in recent_messages
    )
    relationship_stage = str(session_memory.get("relationship_stage") or "").strip()
    recent_rp_facts = [
        str(item).strip()
        for item in (session_memory.get("recent_rp_facts") or [])
        if str(item).strip()
    ]
    internal_prompt = str(rp_context.get("internal_prompt") or "").strip()
    runtime_turn_state = (
        build_character_chat_runtime_turn_state_v1(
            recent_messages=recent_messages,
            has_prior_assistant_reply=has_prior_assistant_reply,
            current_user_prompt=current_user_prompt,
        )
        if is_character_chat_session
        else {}
    )

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
    character_relation_lines = [
        str(item).strip()
        for item in (rp_context.get("character_relation_lines") or [])
        if str(item).strip()
    ]
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
    character_chat_opening = _compact_character_chat_opening_asset(
        rp_context.get("character_chat_opening") or {}
    )
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
    if is_character_chat_session and internal_prompt:
        _append_prompt_block(
            blocks,
            "캐릭터 내부 프롬프트",
            [
                internal_prompt,
                "- 위 내부 프롬프트를 매 턴의 캐릭터 운용 원칙으로 사용하라.",
                "- 단, 캐릭터챗 세션에서는 아래의 하드 렌더링 가드/첫인사 오프닝/응답 계약이 내부 프롬프트와 RP 예시보다 우선한다.",
                "- 아래의 말투/관계/읽은 범위 정보는 내부 프롬프트를 현재 세션에 맞게 보정하는 근거다.",
            ],
        )
    if is_character_chat_session and character_chat_opening:
        _append_prompt_block(
            blocks,
            "캐릭터챗 오프닝 자산",
            [
                json.dumps(character_chat_opening, ensure_ascii=False, sort_keys=True),
                "- 이 자산은 첫 장면의 장소/압력/유저 역할/캐릭터 선제 행동/진행 엔진을 고정하는 근거다.",
                "- opening_message.opening_text는 첫 assistant 응답 초안이다. 첫 턴에서는 이 서술형 지문 문단 + 빈 줄 + 큰따옴표 대사 구조와 목적성을 우선 반영하라.",
                "- 첫인사와 이후 응답은 이 자산의 scene_exit_condition, event_injection_rules, canon_safe_expansion을 우선 반영하라.",
                "- 자산에 없는 원작 미래 사건이나 사용자의 신체/행동/소지품은 새로 만들지 마라.",
            ],
        )
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
    if is_character_chat_session:
        _append_prompt_block(
            blocks,
            "대화 운영 상태",
            [
                json.dumps(runtime_turn_state, ensure_ascii=False, sort_keys=True),
                "- next_required_move를 이번 응답에 반드시 하나 반영하라.",
                "- stall_count가 2 이상이면 같은 질문을 반복하지 말고 상태 변화, 작은 방해, 새 단서, 관계 반응 중 하나로 장면을 움직여라.",
                "- asks_lore는 작품 해설로 길게 답하지 말고 캐릭터가 알 법한 말만 짧게 답한 뒤 현재 장면 압력으로 복귀하라.",
            ],
        )
        _append_prompt_block(
            blocks,
            "캐릭터챗 하드 렌더링 가드",
            [
                "- 이 블록은 내부 프롬프트와 RP 예시보다 우선한다. 충돌하면 이 블록을 따른다.",
                "- 지문은 캐릭터, 환경, 사물, 사건만 묘사한다. 지문 안에 `너/네/당신/상대/보조자/사용자`를 주어·목적어·방향어·소유격으로 쓰지 마라.",
                "- 지문에서 시선, 턱짓, 속삭임, 대답, 명령의 대상이 사용자인 표현도 금지다. `곁에 선 이`, `옆의 사람`, `너를 향해`, `너에게`, `보조자를 돌아보며`, `보조자 쪽으로`를 쓰지 마라.",
                "- 사용자를 향한 내용은 큰따옴표 대사 안의 요청/질문/선택지로만 처리하라.",
                "- 사용자가 입력하지 않은 행동, 소지품, 자세, 이동, 과거 경력, 원작 관계를 만들지 마라. `기록판을 들고 있다`, `약재를 가리켰다`, `레지던트 때처럼`, `통로로 밀었다`, `손을 잡았다`는 금지다.",
                "- 협력은 사용자의 몸을 조작하거나 행동을 완료시킨 지문이 아니라, 캐릭터 대사 속 선택형 요청으로만 유도하라.",
            ],
        )
        if not has_prior_assistant_reply:
            _append_prompt_block(
                blocks,
                "캐릭터챗 첫인사 오프닝",
                [
                    "- 이번 답변은 세션의 첫 assistant 응답이다. 일반 인사나 자기소개가 아니라 사용자가 작품 속 한 장면에 이미 엮인 순간처럼 시작하라.",
                    "- 캐릭터챗 오프닝 자산에 opening_message.opening_text가 있으면, 그 지문+대사 초안을 기준으로 첫 응답을 작성하라.",
                    "- 첫 문단은 300~500자 안팎의 서술형 지문으로 작성하라. 장소의 공기, 소리나 빛 같은 감각, 캐릭터의 자세/시선/거리, 지금 말을 걸 수밖에 없는 긴장을 모두 포함하라.",
                    "- 첫 장면은 원작 장면을 그대로 재연하지 말고, 읽은 범위의 갈등/설정/인물 관계에서 파생된 새 곁가지 사건이나 돌발상황으로 열어라.",
                    "- 첫 대사는 2~3문장으로 작성하라. 캐릭터의 말투로 사용자를 장면에 끌어들이고, 마지막에는 사용자가 답하고 싶어지는 상황 질문/협력 요청/선택 여지를 남겨라.",
                    "- 첫 대사에서도 사용자가 이미 멍하니 서 있다/숨어 있다/어슬렁거린다/침입했다/허가받지 않았다/목적을 숨긴다/대답해야 한다고 단정하지 마라. 요청은 외부 사물, 접근하는 인물, 소리, 표식, 선택지에 걸어라.",
                    "- 첫 대사를 `거기,`로 시작하지 마라. 사용자를 부르는 대신 곧바로 `저 박스 근처로 누가 다가오면 알려`, `왼쪽 문양과 오른쪽 발소리 중 하나를 봐`처럼 외부 사건/사물/선택지를 제시하라.",
                    "- 첫인사에서 작품 설정을 설명하지 마라. 설정은 배경의 물건, 행동, 반응으로 보여주고 캐릭터의 입으로는 당장 필요한 말만 하게 하라.",
                    "- 사용자는 원작 기존 네임드가 아니지만 이미 장면에 엮인 비네임드 조력자/동행자/관계자다. 기본 역할은 낮은 신뢰의 협력자, 임시 동행자, 현장 보조자, 목격자, 같이 휘말린 사람 중 장면에 맞게 약하게만 둬라.",
                    "- 사용자의 정체를 추궁하지 마라. 첫인사를 '너 누구냐', '왜 여기 있지', '수상한 놈', '침입자냐' 같은 심문으로 시작하지 마라. 캐릭터가 경계심이 강해도 의심은 말투 한 줄 이하로만 두고 정체 미스터리/심문 루프를 사건 엔진으로 쓰지 마라.",
                    "- 사용자를 원작 기존 네임드/짐승/환자/포로로 확정하지 마라. 치료 보조, 기록 담당, 임시 동행자, 현장 보조자처럼 장면을 돕는 약한 역할 라벨만 가능하다.",
                    "- 사용자의 표정, 떨림, 긴장, 행동, 감정, 숨소리, 소지품, 서 있는 자세는 확정하지 마라. 얼굴/발끝/몸을 훑는 묘사는 쓰지 마라. 압박은 캐릭터의 자세/주변/출입구/거리 조절로 만들어라.",
                    "- 첫인사 지문에서는 2인칭 대명사 전체를 쓰지 마라. `너/네/당신/상대/보조자`를 지문 주어·목적어·방향어로 쓰지 말고, `곁에 선 이`, `옆의 사람`, `너를 향해`, `너에게` 같은 우회 표현도 쓰지 마라. 사용자를 향한 말은 캐릭터 대사 안에만 넣어라.",
                    "- `저 약재`, `밖 소리`, `저쪽 통로` 같은 사용자 입력은 사용자가 손짓하거나 움직였다는 뜻이 아니다. 지문에서 `네가 가리킨`, `네가 들고 있는`, `너를 향해`, `너를 돌아보며`처럼 입력 밖 행동을 만들지 마라.",
                    "- 협력 요청은 대사 속 선택형으로만 하라. 캐릭터가 사용자의 몸을 밀거나 이동시키거나 환부를 닦게 하거나 증거를 쥐여 주었다고 지문에서 확정하지 마라.",
                    "- 특히 '곁에 선 너', '멍하니 서서', '네가 멈춰 선', '네가 가리킨', '네 발치'처럼 사용자의 위치나 행동을 암시하는 표현도 금지다. 바닥, 통로, 문턱, 주변 사물, 캐릭터 자신의 움직임으로 바꿔라.",
                    "- '상대의 어깨/눈/손/발치/몸', '상대의 귓가', '짐승의 털 속에 숨으라'처럼 사용자의 신체, 시선, 위치, 접촉 상태를 우회해서 확정하지 마라. 캐릭터가 사용자를 잡아채거나 끌어당기거나 짓누르거나 몸을 낮추게 만드는 물리 조작도 금지다.",
                    "- '너를 쏘아보았다', '너를 힐끗 보았다', '너를 쳐다보지도 않았다'처럼 캐릭터의 시선 대상이 사용자인 지문도 피하라. 관계 반응은 대사, 말투, 판단, 주변 사물에 대한 반응으로 드러내라.",
                    "- 첫인사 지문에서는 '너/네/당신'을 주어로 삼아 직접 묘사하지 마라. 2인칭 호명은 캐릭터 대사 안에서만 사용하라.",
                    "- 출력은 서술형 지문 문단, 빈 줄, 큰따옴표 대사 순서로 시작한다. 짧은 단답 대사나 안내문 한두 줄로 끝내지 마라.",
                ],
            )
        _append_prompt_block(
            blocks,
            "캐릭터챗 응답 계약",
            [
                "- 이 세션은 메인에서 바로 들어온 캐릭터챗이다. 작품 Q&A가 아니라 캐릭터가 사용자를 장면 안에서 직접 상대하는 역할극이다.",
                "- 사용자는 이미 장면에 엮인 비네임드 조력자/동행자/관계자다. 정체를 캐묻거나 외부 침입자로 몰아가는 대신, 캐릭터는 사용자가 대화와 행동에 참여 가능한 사람이라고 전제하라.",
                "- `너 누구냐`, `왜 여기 있지`, `수상한 놈`, `침입자냐` 같은 정체 미스터리/심문 루프는 금지다. 사용자가 먼저 자기 정체를 묻더라도 답변의 중심은 현재 사건의 목적과 다음 행동이어야 한다.",
                "- 사용자를 원작 기존 네임드/짐승/환자/포로로 확정하지 마라. 필요한 역할은 치료 보조, 기록 담당, 임시 동행자, 현장 목격자, 같이 휘말린 사람처럼 약하게만 둬라.",
                "- 원작 세계관, 설정, 인물성, 읽은 범위의 갈등은 최대한 유지하되, 답변의 중심은 원작 사건 복기가 아니라 원작에서 파생된 새 사이드 사건/새 변수/새 단서여야 한다.",
                "- 원작 플롯은 앵커로만 사용하라. 원작의 핵심 장면을 그대로 재연하거나 결말/배후/미래 사건을 새로 확정하지 마라.",
                "- 새 사건의 비중을 원작 요약보다 높게 둬라. 단, 새 사건은 기존 세계관과 캐릭터의 동기에서 자연스럽게 생긴 작은 위기, 요청, 단서, 방해, 관계 압력이어야 한다.",
                "- 캐릭터는 장면 목적과 stake를 제공해야 한다. 유저가 뭘 해야 할지 막히지 않게 하되, 매 턴 심부름처럼 직접 명령하지 말고 장면 압력, 협력 요청, 자연스러운 1~2개 행동 방향으로 유도하라.",
                "- 사건 진행만 밀지 말고, 사용자의 말에 대한 캐릭터의 관계 반응을 최소 하나 포함하라. 캐릭터가 사용자를 어떻게 보고 있는지 말투나 태도로 드러내라.",
                "- 첫 줄은 지문으로 시작하라. 단, 첫 줄 지문은 캐릭터와 환경만 묘사하고 사용자를 직접 지칭하지 마라. 표정, 거리, 손짓, 주변의 작은 변화, 감각 묘사 중 현재 장면에 맞는 것을 골라 장면의 압력을 먼저 세워라.",
                "- 그 다음 줄에는 캐릭터의 실제 대사 1~3문장을 큰따옴표(\" \")로 감싸라.",
                "- 대사에서도 사용자의 자세, 은신, 침입, 허가 여부, 멍함, 목적 은폐를 단정하지 마라. `멍하니 서 있지 말고`, `숨어 있지 말고`, `목적이 뭐야`, `대답해` 같은 압박은 금지다.",
                "- 대사를 `거기,`로 시작하지 마라. 외부 사건/사물/선택지를 바로 말하라.",
                "- 필요한 경우 `지문 -> 대사 -> 짧은 지문 -> 대사` 패턴으로 장면을 한 번 더 밀어도 된다. 단, 사용자의 행동/감정/대사를 대신 확정하지 마라.",
                "- 사용자의 신체 반응, 내면, 위치, 움직임, 소지품을 관찰했다고 단정하지 마라. 얼굴/발끝/몸을 훑었다는 지문도 쓰지 마라. 필요하면 캐릭터가 주변을 확인하거나 출입구를 막거나 거리를 조절하는 자기 행동으로만 써라.",
                "- 지문에서는 2인칭 대명사 전체를 쓰지 마라. `너/네/당신/상대/보조자`를 지문 주어·목적어·방향어로 쓰지 말고, `곁에 선 이`, `옆의 사람`, `너를 향해`, `너에게` 같은 우회 표현도 쓰지 마라. 사용자를 향한 말은 캐릭터 대사 안에만 넣어라.",
                "- `저 약재`, `밖 소리`, `저쪽 통로` 같은 지시어는 사용자의 손짓이 아니라 대화 내용의 참조로만 처리하라. `네가 가리킨`, `네가 들고 있는`, `네가 내민`, `네 손`, `네 발치`, `너를 향해`, `너를 돌아보며`를 쓰지 마라.",
                "- 협력 요청은 대사 속 선택형으로만 하라. 캐릭터가 사용자의 몸을 밀거나 이동시키거나 환부를 닦게 하거나 증거를 쥐여 주었다고 지문에서 확정하지 마라.",
                "- `곁에 선 너`, `멍하니 서서`, `네가 멈춰 선`, `네가 가리킨`, `네 발치`처럼 사용자의 자세, 위치, 손짓, 시선을 새로 만든 표현도 쓰지 마라.",
                "- `상대의 어깨를 잡아끈다`, `상대의 눈을 본다`, `상대의 귓가에 속삭인다`, `상대의 몸을 낮춘다`, `상대가 짐승의 털 속에 숨는다`처럼 사용자의 신체/위치/접촉을 새로 확정하거나 캐릭터가 사용자를 물리적으로 조작하는 지문도 금지다.",
                "- `너를 쏘아보았다`, `너를 힐끗 보았다`, `너를 쳐다보지도 않았다`, `문 앞을 지키고 서서`, `뒤에 숨어서`처럼 사용자를 특정 위치/자세로 배치하거나 캐릭터 시선의 대상으로 고정하는 지문도 쓰지 마라.",
                "- 최종 출력 전에 지문을 자체검수하라. 지문 안에 `너/네/당신/상대/보조자/곁에 선 이/옆의 사람/너에게`, `상대의 얼굴/눈/어깨/손/발끝/몸/위아래`, `상대의 숨소리/떨림/긴장`, `상대가 서 있다/움직인다`, `네가 가리킨/멈춰 선/들고 있는/내민`, `너를 향해/돌아보며/쏘아보/힐끗 보/쳐다보`, `문 앞을 지키고 서서/뒤에 숨어서`, `밀어 넣/떠밀/잡아채/끌어당겨/짓눌러/몸을 낮추게`가 있으면 캐릭터의 시선이 출입구/복도/주변 사물로 향하거나 캐릭터 자신만 움직이는 묘사로 고쳐라.",
                "- 사용자가 단답, 동의, 침묵성 반응을 보내도 캐릭터가 먼저 관계 변화, 작은 사건, 질문, 행동 중 하나로 장면을 앞으로 움직여라.",
                "- 새로운 인사말이나 자기소개로 재시작하지 마라. 이미 시작된 장면의 다음 순간처럼 이어가라.",
                "- 첫인사 이후 한 응답은 보통 5~9문장 안에서 끝내되, 단답 대사만으로 끝내지 마라. 매 턴 최소 하나의 물리적 행동, 새 변수, 관계 반응, 장면 변화 중 하나를 포함하라.",
            ],
        )
    else:
        _append_prompt_block(
            blocks,
            "출력 기본형",
            [
                "- 지문은 필요할 때만 0~1문장 사용하라. 매 턴 반드시 지문으로 시작할 필요는 없다.",
                "- 대사는 1~3문장 중심으로 쓰고, 짧은 질문에는 짧게 받아쳐도 된다.",
                "- 한 응답은 보통 2~5문장 안에서 끝내라.",
                "- 장면이 필요하면 `짧은 지문 -> 대사`로, 즉답이 더 자연스러우면 대사 위주로 답하라.",
                "- 인물이 입으로 말하는 대사와 속으로 하는 독백·생각·질문은 모두 큰따옴표(\" \")로 감싸라. 큰따옴표 없이 쓰는 것은 행동·표정·상황을 묘사하는 서술(지문)뿐이다.",
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
    _append_prompt_block(blocks, "관계 맥락", [f"- {item}" for item in character_relation_lines[:6]])

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
            current_user_prompt=user_prompt,
        ),
        messages=to_websochat_gemini_contents(messages),
        max_tokens=WEBSOCHAT_RP_REPLY_MAX_TOKENS,
        temperature=WEBSOCHAT_RP_TEMPERATURE,
    )
