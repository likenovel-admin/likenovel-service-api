from __future__ import annotations

import json
import re
from typing import Any

from fastapi import status

from app.exceptions import CustomResponseException
from app.services.ai.ai_chat_service import _call_claude_messages, _extract_text
from app.services.websochat.websochat_context_loader import (
    _is_websochat_character_entry_context_v2,
)
from app.services.websochat.websochat_game_memory import _normalize_websochat_session_memory
from app.services.websochat.websochat_llm import (
    WEBSOCHAT_RP_TEMPERATURE,
    call_websochat_gemini,
    to_websochat_gemini_contents,
)
from app.services.websochat.websochat_utils import _extract_websochat_json_object

WEBSOCHAT_RP_REPLY_MAX_TOKENS = 4096
WEBSOCHAT_CHARACTER_OPENING_MAX_TOKENS = 2048
WEBSOCHAT_CHARACTER_OPENING_MAX_BYTES = 12000


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
        "runtime_formula_seed",
        "user_affordance_contract",
        "canon_safe_expansion",
        "progression",
    ):
        value = payload.get(key)
        if value not in (None, "", [], {}):
            compact[key] = value
    return compact


def _build_character_chat_safe_scene_material(entry_context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(entry_context, dict):
        return {}
    character_scope_key = str(entry_context.get("character_scope_key") or "").strip()
    scene = entry_context.get("character_scene")
    if not character_scope_key or not isinstance(scene, dict):
        return {}

    safe_scene: dict[str, Any] = {}
    for key in (
        "scene_gist",
        "current_action",
        "immediate_pressure",
        "character_initiative_reason",
        "pressure_clock",
        "conversation_fuel_tags",
        "identity_safety",
        "knowledge_boundary",
        "creative_grounding",
    ):
        value = scene.get(key)
        if value not in (None, "", [], {}):
            safe_scene[key] = value

    selected_character_actions = []
    for item in scene.get("action_ownership") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("actor_scope_key") or "").strip() != character_scope_key:
            continue
        action = str(item.get("action") or "").strip()
        if action:
            selected_character_actions.append(action[:500])
    if selected_character_actions:
        safe_scene["selected_character_actions"] = selected_character_actions[:4]

    read_episode_to = int(entry_context.get("read_episode_to") or 0)
    recent_episode_from = int(entry_context.get("recent_episode_from") or 0)
    anchor_episode_no = int(entry_context.get("character_anchor_episode_no") or 0)
    scene_is_recent = bool(
        read_episode_to > 0
        and recent_episode_from > 0
        and recent_episode_from <= anchor_episode_no <= read_episode_to
    )
    if not scene_is_recent:
        safe_scene.pop("creative_grounding", None)

    return {
        "product_id": int(entry_context.get("product_id") or 0),
        "character_scope_key": character_scope_key,
        "read_episode_to": read_episode_to,
        "entry_strategy": (
            "recent_scene_branch" if scene_is_recent else "current_boundary_reentry"
        ),
        "recent_episode_state": [
            {
                "episode_no": int(row.get("episode_no") or 0),
                "summary_text": str(row.get("summary_text") or "").strip(),
            }
            for row in (entry_context.get("recent_plot_rows") or [])
            if isinstance(row, dict)
            and int(row.get("episode_no") or 0) > 0
            and str(row.get("summary_text") or "").strip()
        ],
        "character_anchor_episode_no": anchor_episode_no,
        "selected_character_last_completed_scene": safe_scene,
    }


def _build_character_chat_entry_context_lines(payload: dict[str, Any]) -> list[str]:
    if not isinstance(payload, dict) or payload.get("schema_version") != "character_chat_entry_context_v2":
        return []
    read_episode_to = int(payload.get("read_episode_to") or 0)
    recent_episode_from = int(payload.get("recent_episode_from") or 0)
    recent_episode_to = int(payload.get("recent_episode_to") or 0)
    if read_episode_to <= 0 or recent_episode_from <= 0 or recent_episode_to != read_episode_to:
        return []

    lines = [
        f"- 읽은 범위의 마지막 회차: {read_episode_to}화",
        f"- 첫 장면 직접 근거: {recent_episode_from}~{recent_episode_to}화",
        f"- {read_episode_to}화가 끝난 상태에서 시작하라. 앞선 도입부 상태로 되돌아가지 마라.",
        f"- {read_episode_to + 1}화 이후의 사건, 결과, 관계 변화는 사용하거나 암시하지 마라.",
    ]
    for row in payload.get("recent_plot_rows") or []:
        if not isinstance(row, dict):
            continue
        episode_no = int(row.get("episode_no") or 0)
        summary_text = str(row.get("summary_text") or "").strip()
        if episode_no <= 0 or not summary_text:
            continue
        lines.append(f"- {episode_no}화 상태: {summary_text}")

    anchor_episode_no = int(payload.get("character_anchor_episode_no") or 0)
    character_scene = payload.get("character_scene") if isinstance(payload.get("character_scene"), dict) else {}
    if anchor_episode_no > 0 and character_scene:
        lines.append(f"- 선택 캐릭터의 마지막 장면 근거: {anchor_episode_no}화")
        lines.append(
            json.dumps(
                _build_character_chat_safe_scene_material(payload).get(
                    "selected_character_last_completed_scene", {}
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        lines.append(
            "- 이 장면은 이미 끝난 캐릭터 상태의 근거다. 장면의 사용자 역할, 대화 상대, 사건 순서를 이어받지 말고 이 범위에서 파생된 새 곁가지 사건으로 변형하라."
        )
        lines.append(
            "- scene_identity_boundary와 knowledge_boundary는 공개 한계다. must_not_address_as와 must_not_reveal에 든 정보는 직접 말하거나 암시하지 마라."
        )
        progression_seed = str(character_scene.get("progression_seed") or "").strip()
        if progression_seed:
            lines.append(f"- 이후 전개 참고: {progression_seed}")
        if anchor_episode_no < recent_episode_from:
            lines.append(
                "- 선택 캐릭터가 최근 두 회차에 없었다. 그 캐릭터가 최근 회차 현장에 원래부터 있었다고 만들지 말고, 마지막 등장 상태와 현재 작품 상황을 잇는 새 장면으로 시작하라."
            )
    return lines


def _normalize_character_chat_adjacent_opening_payload(
    payload: Any,
    *,
    expected_product_id: int,
    expected_character_scope_key: str,
    expected_read_episode_to: int,
    forbidden_dialogue_addressees: list[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if payload.get("schema_version") != "character_chat_adjacent_opening_v1":
        return {}
    try:
        product_id = int(payload.get("product_id") or 0)
        read_episode_to = int(payload.get("read_episode_to") or 0)
    except (TypeError, ValueError):
        return {}
    character_scope_key = str(payload.get("character_scope_key") or "").strip()
    if (
        product_id != int(expected_product_id or 0)
        or character_scope_key != str(expected_character_scope_key or "").strip()
        or read_episode_to != int(expected_read_episode_to or 0)
    ):
        return {}

    scene_plan = payload.get("scene_plan")
    if not isinstance(scene_plan, dict):
        return {}
    normalized_plan: dict[str, Any] = {}
    for key in (
        "setting",
        "continuity_from_boundary",
        "freshness_from_completed_scene",
        "event_shape",
        "inciting_event",
        "character_first_move",
        "stakes",
    ):
        value = str(scene_plan.get(key) or "").strip()
        if not value or len(value) > 500:
            return {}
        normalized_plan[key] = value
    beats = [
        str(item or "").strip()
        for item in (scene_plan.get("beats") or [])
        if str(item or "").strip()
    ]
    if len(beats) != 3 or any(len(item) > 300 for item in beats):
        return {}
    normalized_plan["beats"] = beats

    decision_branch = scene_plan.get("decision_branch")
    if not isinstance(decision_branch, dict):
        return {}
    decision_axis = str(decision_branch.get("axis") or "").strip().lower()
    if decision_axis not in {"risk", "priority", "approach", "interpretation"}:
        return {}
    user_decision = str(decision_branch.get("user_decision") or "").strip()
    if not user_decision or len(user_decision) > 300:
        return {}

    normalized_branches: list[dict[str, str]] = []
    for branch_key in ("branch_a", "branch_b"):
        branch = decision_branch.get(branch_key)
        if not isinstance(branch, dict):
            return {}
        actor_scope_key = str(branch.get("actor_scope_key") or "").strip()
        character_next_action = str(branch.get("character_next_action") or "").strip()
        immediate_effect = str(branch.get("immediate_effect") or "").strip()
        if (
            actor_scope_key != character_scope_key
            or not character_next_action
            or len(character_next_action) > 500
            or not immediate_effect
            or len(immediate_effect) > 500
        ):
            return {}
        normalized_branches.append(
            {
                "actor_scope_key": actor_scope_key,
                "character_next_action": character_next_action,
                "immediate_effect": immediate_effect,
            }
        )
    if (
        normalized_branches[0]["character_next_action"].casefold()
        == normalized_branches[1]["character_next_action"].casefold()
        or normalized_branches[0]["immediate_effect"].casefold()
        == normalized_branches[1]["immediate_effect"].casefold()
    ):
        return {}
    normalized_plan["decision_branch"] = {
        "axis": decision_axis,
        "user_decision": user_decision,
        "branch_a": normalized_branches[0],
        "branch_b": normalized_branches[1],
    }

    raw_opening_text = str(payload.get("opening_text") or "").strip()
    if not (260 <= len(raw_opening_text) <= 1200):
        return {}
    paragraphs = [part.strip() for part in raw_opening_text.split("\n\n") if part.strip()]
    if len(paragraphs) < 2:
        return {}
    first_dialogue_index = next(
        (
            index
            for index, paragraph in enumerate(paragraphs)
            if paragraph.startswith(('"', "“"))
        ),
        -1,
    )
    narration_paragraphs = paragraphs[:first_dialogue_index]
    dialogue_paragraphs = paragraphs[first_dialogue_index:]
    if (
        first_dialogue_index <= 0
        or not (1 <= len(dialogue_paragraphs) <= 3)
        or any(mark in "\n\n".join(narration_paragraphs) for mark in ('"', "“", "”"))
        or any(
            not paragraph.startswith(('"', "“"))
            or not paragraph.endswith(('"', "”"))
            or not paragraph[1:-1].strip()
            for paragraph in dialogue_paragraphs
        )
    ):
        return {}
    dialogue = '"' + " ".join(paragraph[1:-1].strip() for paragraph in dialogue_paragraphs) + '"'
    opening_text = "\n\n".join([*narration_paragraphs, dialogue])
    if not (260 <= len(opening_text) <= 1200):
        return {}
    dialogue_body = dialogue[1:-1].lstrip()
    for addressee in forbidden_dialogue_addressees or []:
        normalized_addressee = str(addressee or "").strip()
        if normalized_addressee and re.match(
            rf"^{re.escape(normalized_addressee)}\s*[,!?:]",
            dialogue_body,
        ):
            return {}

    normalized = {
        "schema_version": "character_chat_adjacent_opening_v1",
        "product_id": product_id,
        "character_scope_key": character_scope_key,
        "read_episode_to": read_episode_to,
        "scene_plan": normalized_plan,
        "opening_text": opening_text,
    }
    if len(json.dumps(normalized, ensure_ascii=False).encode("utf-8")) > WEBSOCHAT_CHARACTER_OPENING_MAX_BYTES:
        return {}
    return normalized


def _build_character_chat_adjacent_opening_prompt(
    *,
    product_row: dict[str, Any],
    rp_context: dict[str, Any],
) -> str:
    entry_context = (
        rp_context.get("character_chat_entry_context")
        if isinstance(rp_context.get("character_chat_entry_context"), dict)
        else {}
    )
    character_scope_key = str(rp_context.get("active_character") or "").strip()
    read_episode_to = int(entry_context.get("read_episode_to") or 0)
    product_id = int(entry_context.get("product_id") or product_row.get("productId") or 0)
    if not _is_websochat_character_entry_context_v2(
        entry_context,
        expected_read_episode_to=read_episode_to,
        expected_product_id=product_id,
        expected_character_scope_key=character_scope_key,
    ):
        return ""

    examples = []
    for item in rp_context.get("examples") or []:
        if not isinstance(item, dict):
            continue
        episode_no = int(item.get("episode_no") or 0)
        text_value = str(item.get("text") or "").strip()
        if 0 < episode_no <= read_episode_to and text_value:
            examples.append({"episode_no": episode_no, "text": text_value[:600]})
        if len(examples) >= 3:
            break

    source = {
        "work": {
            "product_id": product_id,
            "title": str(product_row.get("title") or "작품").strip(),
        },
        "selected_character": {
            "scope_key": character_scope_key,
            "display_name": str(rp_context.get("display_name") or character_scope_key).strip(),
            "speech_style": {
                key: value
                for key in ("tone", "formality", "sentence_length")
                if (value := (rp_context.get("speech_style") or {}).get(key))
                not in (None, "", [], {})
            },
            "speech_examples": examples,
        },
        "reader_boundary": _build_character_chat_safe_scene_material(entry_context),
    }
    return f"""당신은 원작 웹소설 캐릭터챗의 첫 장면을 설계하는 편집자다.

[목표]
- 독자는 {read_episode_to}화까지 읽었다. 정확히 {read_episode_to}화 종료 상태에서 선택 캐릭터가 먼저 움직이고 말하는 새 곁가지 사건을 연다.
- 원작 세계관과 캐릭터의 동기·말투는 유지하되, 입력의 마지막 장면은 이미 끝난 사건이다. 그 장면의 대화 상대·행동 순서·핵심 사건을 재연하지 않는다.
- reader_boundary.entry_strategy가 recent_scene_branch이면 최근 R-1/R 장면의 장소·감각·소품을 장면 프레임으로 유지하고, 완료된 마지막 행동 바로 다음의 새 갈림점에서 시작한다. 원작 대사와 행동은 반복하지 않는다.
- reader_boundary.entry_strategy가 current_boundary_reentry이면 오래된 캐릭터 장면의 장소와 사건으로 돌아가지 않는다. R-1/R recent_episode_state가 현재 시공간과 문제의 유일한 근거다.
- 새 사건은 원작의 미공개 진실이나 핵심 플롯 증거가 아니라, 같은 세계의 현재 활동에서 생긴 독립적인 마찰이다. 입력에 없는 사물의 정체나 과거를 원작 사실처럼 확정하지 않는다.
- 장르와 현재 목표에 맞춰 일정 충돌, 관계 협상, 자원 배분, 기술 시험, 규칙의 예외, 예상 밖의 작은 결과, 방해받은 일상 중 가장 자연스러운 event_shape을 고른다.
- recent_scene_branch의 creative_grounding은 원문 기반 감각·소품을 유지하기 위한 재료다. 1~2개를 사용해 같은 프레임의 새 갈림점을 만들되 완료된 행동은 반복하지 않는다.
- forbidden_inventions는 만들지 않는다. canon_safe_new_event_types는 현재 R-1/R 상태에도 맞을 때만 추상 방향으로 참고한다.
- decision_branch는 사용자가 한두 턴 안에 답할 수 있는 위험·우선순위·접근법·해석 판단 하나와, 그 판단 뒤 선택 캐릭터가 직접 수행할 서로 다른 다음 행동 두 개를 설계한다.
- 정체불명 물건·액체·소리·익명 단서, 숨은 적의 공작, 독극물, 폭발물, 배신을 범용 훅처럼 쓰지 않는다. 원고 근거가 명시한 경우가 아니면 미스터리나 음모로 시작하지 않는다.
- stakes는 한 장면 안에서 다룰 수 있고 실패해도 되돌릴 수 있는 국지적 문제여야 한다. 생명·도시·가문·전쟁·원작 핵심 임무의 운명을 새로 걸지 않는다.

[사용자 경험]
- 선택 캐릭터만 말한다. 첫 대사는 반드시 이름 없는 사용자에게 향한다. 다른 원작 인물은 대사를 하지 않는다.
- identity_safety.prior_scene_addressees와 prior_scene_other_characters는 완료된 원작 장면의 인물이다. opening_text의 대화 상대나 사용자 역할로 재사용하지 않는다.
- 사용자를 원작 네임드, 특정 직책, 환자, 포로, 침입자 등으로 지정하지 않는다. 사용자의 위치·행동·감정·소지품·과거도 서술하지 않는다.
- 캐릭터가 먼저 관찰하고 행동한다. 사용자는 아직 아무 행동도 하지 않았다.
- 사용자는 물건을 들기·가져오기·지키기 같은 행동을 수행하지 않는다. 위험 평가·우선순위·해석·접근법을 판단하고, 선택 캐릭터가 그 판단에 따라 직접 움직인다.
- decision_branch.branch_a와 branch_b의 actor_scope_key는 반드시 선택 캐릭터의 scope_key다. 두 branch의 character_next_action과 immediate_effect는 실제로 달라야 한다.
- 정체 심문이나 장황한 설정 설명 없이 사건으로 바로 들어간다. UI식 번호 선택지는 쓰지 않는다.

[출력 품질]
- opening_text는 한국어 350~750자 안팎이다.
- 선택 캐릭터를 이름이나 호칭으로 부르는 3인칭 관찰 지문으로 시작한다. 캐릭터의 1인칭 독백처럼 서술하지 않는다.
- 감각이 있는 지문에서 선택 캐릭터의 구체 행동과 새 마찰을 보여준 뒤 빈 줄을 둔다.
- 이어서 선택 캐릭터 말투의 큰따옴표 대사 1~3문장으로 끝낸다. 마지막 말은 사용자의 판단이 다음 행동을 실제로 바꾸게 한다.
- 대사가 끝난 뒤 따옴표 밖에 명령, 질문, 설명을 덧붙이지 않는다. 다른 인물의 대사도 넣지 않는다.
- 장면은 한 번에 해결하지 않는다. beats는 이상 확인, 사용자 판단, 그 판단 뒤 발생할 작은 결과의 3단계다.

[출력 형식]
설명이나 마크다운 없이 아래 키를 모두 채운 JSON 객체 하나만 출력하라.
{{
  "schema_version": "character_chat_adjacent_opening_v1",
  "product_id": {product_id},
  "character_scope_key": {json.dumps(character_scope_key, ensure_ascii=False)},
  "read_episode_to": {read_episode_to},
  "scene_plan": {{
    "setting": "...",
    "continuity_from_boundary": "읽은 범위의 어떤 현재 상태를 이어받았는지",
    "freshness_from_completed_scene": "완료된 마지막 장면과 어떻게 다른지",
    "event_shape": "현재 작품에 맞는 마찰 유형",
    "inciting_event": "...",
    "character_first_move": "...",
    "stakes": "...",
    "beats": ["선택 캐릭터의 선행 행동", "사용자의 판단", "선택 캐릭터가 수행할 다음 행동"],
    "decision_branch": {{
      "axis": "risk | priority | approach | interpretation 중 하나",
      "user_decision": "사용자가 판단할 한 가지 쟁점",
      "branch_a": {{
        "actor_scope_key": {json.dumps(character_scope_key, ensure_ascii=False)},
        "character_next_action": "판단 A 뒤 선택 캐릭터가 직접 할 행동",
        "immediate_effect": "그 행동으로 바로 달라지는 장면 상태"
      }},
      "branch_b": {{
        "actor_scope_key": {json.dumps(character_scope_key, ensure_ascii=False)},
        "character_next_action": "판단 B 뒤 선택 캐릭터가 직접 할 다른 행동",
        "immediate_effect": "그 행동으로 바로 달라지는 다른 장면 상태"
      }}
    }}
  }},
  "opening_text": "지문\\n\\n\\\"대사\\\""
}}

[허용된 원고 근거]
{json.dumps(source, ensure_ascii=False, sort_keys=True)}

[출력 직전 편집]
1. 서로 다른 event_shape 후보를 내부에서 세 개 만든 뒤 출력하지 말고 비교하라.
2. recent_scene_branch이면 원문 감각을 가장 잘 살리면서 완료 행동을 반복하지 않는 후보를, current_boundary_reentry이면 오래된 장소를 버리고 최근 회차 상태에 가장 잘 맞는 후보를 고른다.
3. 새 사건의 원인을 특정 인물·세력의 공작으로 돌리거나 원작 핵심 단서와 연결한 문장이 허용된 원고 근거에 없다면, 현재 업무에서 생긴 평범하지만 의미 있는 마찰로 다시 쓴다.
4. decision_branch 두 갈래에서 선택 캐릭터가 직접 수행할 행동과 즉시 결과가 서로 다른지 확인한다. 사용자가 직접 운반·수리·감시·보관해야 진행되는 설계라면 판단만 맡도록 다시 쓴다.
5. 사용자의 위치나 몸짓을 지문에 넣지 않고, stakes가 국지적이고 되돌릴 수 있는지 실제 scene_plan과 opening_text를 다시 읽어 확인한다.
6. opening_text는 3인칭 지문 문단 뒤 빈 줄 하나, 선택 캐릭터의 큰따옴표 대사 한 문단으로 정확히 끝낸다. 내부 branch의 A/B 표시는 대사에 노출하지 않는다.
7. 검수를 마친 최종 JSON 하나만 출력하라."""


async def generate_character_chat_adjacent_opening_with_gemini(
    *,
    product_row: dict[str, Any],
    rp_context: dict[str, Any],
) -> dict[str, Any]:
    prompt = _build_character_chat_adjacent_opening_prompt(
        product_row=product_row,
        rp_context=rp_context,
    )
    if not prompt:
        raise CustomResponseException(
            status_code=status.HTTP_409_CONFLICT,
            code="CHARACTER_CHAT_ENTRY_NOT_READY",
            message="이 읽은 범위의 캐릭터챗 시작 장면이 아직 준비되지 않았습니다.",
        )
    entry_context = rp_context["character_chat_entry_context"]
    safe_material = _build_character_chat_safe_scene_material(entry_context)
    identity_safety = (
        safe_material.get("selected_character_last_completed_scene", {}).get(
            "identity_safety", {}
        )
        if isinstance(
            safe_material.get("selected_character_last_completed_scene", {}).get(
                "identity_safety"
            ),
            dict,
        )
        else {}
    )
    for attempt in range(2):
        user_instruction = "요구한 JSON 오프닝을 생성해 주세요."
        if attempt:
            user_instruction = (
                "이전 응답은 JSON 형식 검증을 통과하지 못했습니다. "
                "설명 없이 요구한 키를 모두 포함한 JSON 객체 하나만 다시 생성해 주세요."
            )
        raw_reply = await call_websochat_gemini(
            system_prompt=prompt,
            messages=to_websochat_gemini_contents(
                [{"role": "user", "content": user_instruction}]
            ),
            max_tokens=WEBSOCHAT_CHARACTER_OPENING_MAX_TOKENS,
            temperature=0.7,
            stream=False,
        )
        normalized = _normalize_character_chat_adjacent_opening_payload(
            _extract_websochat_json_object(raw_reply),
            expected_product_id=int(entry_context.get("product_id") or 0),
            expected_character_scope_key=str(rp_context.get("active_character") or "").strip(),
            expected_read_episode_to=int(entry_context.get("read_episode_to") or 0),
            forbidden_dialogue_addressees=[
                str(item or "").strip()
                for item in (identity_safety.get("prior_scene_addressees") or [])
                if str(item or "").strip()
            ],
        )
        if normalized:
            return normalized
    raise CustomResponseException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        code="CHARACTER_CHAT_OPENING_INVALID_RESPONSE",
        message="캐릭터챗 시작 장면을 완성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    )


def _compact_character_chat_internal_prompt(text: str) -> str:
    """Drop legacy render-guard sections while preserving later persona sections."""
    lines = str(text or "").strip().splitlines()
    guard_headings = (
        "[금지]",
        "[금지 사항]",
        "금지 사항:",
        "금지사항:",
        "[자체검수 기준]",
        "[자체 검수 가이드]",
        "자체검수 기준:",
        "자체 검수 가이드:",
    )
    kept: list[str] = []
    skipping_guard = False
    for line in lines:
        normalized = re.sub(r"^\d+[.)]\s*", "", line.strip().lstrip("#").strip())
        if normalized.startswith(guard_headings):
            skipping_guard = True
            continue
        starts_next_section = (
            normalized.startswith("[") and "]" in normalized[:50]
        ) or normalized.startswith(("응답 감각:", "응답감각:"))
        if skipping_guard and starts_next_section:
            skipping_guard = False
        if not skipping_guard:
            kept.append(line)
    return "\n".join(kept).strip()


def _select_rp_examples(
    *,
    examples_payload: list[dict[str, Any]],
    anchor_episode_no: int,
    recent_messages: list[dict[str, str]],
    scene_summary_text: str,
    relationship_stage: str,
    read_episode_to: int = 0,
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
        episode_no = int(item.get("episode_no") or 0)
        if read_episode_to > 0 and (episode_no <= 0 or episode_no > read_episode_to):
            continue
        if not example_text or example_text in seen_texts:
            continue
        seen_texts.add(example_text)
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
    if is_character_chat_session:
        latest_episode_no = int(session_memory.get("read_episode_to") or latest_episode_no)
        websochat_setting = ""
        speech_style = {
            key: speech_style[key]
            for key in ("tone", "formality", "sentence_length")
            if isinstance(speech_style, dict)
            and speech_style.get(key) not in (None, "", [], {})
        }
        personality_core = []
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
    if is_character_chat_session:
        internal_prompt = ""
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
    if is_character_chat_session:
        baseline_attitude = ""
        inventory_payload = {}
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
    if is_character_chat_session:
        character_relation_lines = []
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
    character_chat_entry_context = (
        rp_context.get("character_chat_entry_context")
        if isinstance(rp_context.get("character_chat_entry_context"), dict)
        else {}
    )
    character_chat_entry_lines = _build_character_chat_entry_context_lines(
        character_chat_entry_context
    )
    character_chat_opening = (
        {}
        if is_character_chat_session
        else _compact_character_chat_opening_asset(
            rp_context.get("character_chat_opening") or {}
        )
    )
    runtime_formula_seed = (
        character_chat_opening.get("runtime_formula_seed")
        if isinstance(character_chat_opening.get("runtime_formula_seed"), dict)
        else {}
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
        read_episode_to=(
            int(session_memory.get("read_episode_to") or 0)
            if is_character_chat_session
            else 0
        ),
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
    if is_character_chat_session and character_chat_entry_lines:
        _append_prompt_block(
            blocks,
            "읽은 범위 진입점",
            character_chat_entry_lines,
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
    if is_character_chat_session and runtime_formula_seed:
        _append_prompt_block(
            blocks,
            "캐릭터챗 런타임 전개 공식",
            [
                json.dumps(runtime_formula_seed, ensure_ascii=False, sort_keys=True),
                "- 이 블록은 장면을 앞으로 미는 엔진이다. 작품 설정 설명이나 연구용 분류로 노출하지 마라.",
                "- p_to_user_request와 user_task_success_condition을 사용해 유저에게 1~3턴 안에 답할 수 있는 구체 작업을 제시하라.",
                "- 사용자가 응답하면 protagonist_state_delta로 캐릭터의 다음 행동/판단을 전환하고, open_loop로 다음 3~5턴의 새 변수나 압박을 남겨라.",
                "- 원작 장면을 그대로 재연하지 말고 mutation_policy에 맞는 같은 세계의 곁가지 사건으로 변형하라.",
                "- 유저가 짧게 답하거나 망설여도 같은 질문을 반복하지 말고 단서, 반응, 시간 압박, 작은 방해 중 하나를 더해 진행하라.",
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
                "- 캐릭터챗 런타임 전개 공식이 있으면 next_required_move는 그 공식의 user task, protagonist state delta, open loop 중 하나를 전진시키는 방식으로 반영하라.",
                "- stall_count가 2 이상이면 같은 질문을 반복하지 말고 상태 변화, 작은 방해, 새 단서, 관계 반응 중 하나로 장면을 움직여라.",
                "- asks_lore는 작품 해설로 길게 답하지 말고 캐릭터가 알 법한 말만 짧게 답한 뒤 현재 장면 압력으로 복귀하라.",
            ],
        )
        _append_prompt_block(
            blocks,
            "캐릭터챗 하드 렌더링 가드",
            [
                "- 이 블록은 내부 프롬프트와 RP 예시보다 우선한다. 충돌하면 이 블록을 따른다.",
                "- 사용자가 방금 입력에서 직접 밝힌 행동, 말, 상태만 이어받을 수 있다. 그 범위를 넓혀 새 행동이나 상태를 만들지 않는다.",
                "- 캐릭터는 자신의 접근, 시선, 접촉, 판단을 먼저 행동할 수 있다. 다만 사용자의 감정, 반응, 성공, 다음 행동은 확정하지 않는다.",
                "- 입력에 없는 사용자의 신체 상태, 위치 이동, 소지품, 과거, 원작 관계, 행동 결과를 새로 만들지 않는다.",
                "- 협력 요청은 선택 가능하게 남기고, 사용자가 실행한 것으로 처리하는 것은 다음 입력을 기다린다.",
            ],
        )
        if not has_prior_assistant_reply:
            _append_prompt_block(
                blocks,
                "캐릭터챗 첫인사 오프닝",
                [
                    "- 이번 답변은 세션의 첫 assistant 응답이다. 일반 인사나 자기소개가 아니라 사용자가 작품 속 한 장면에 이미 엮인 순간처럼 시작하라.",
                    "- 읽은 범위 진입점이 있으면 그 회차 종료 상태와 캐릭터 장면을 첫 응답의 유일한 사건 근거로 사용하라.",
                    "- 첫 문단은 300~500자 안팎의 서술형 지문으로 작성하라. 장소의 공기, 소리나 빛 같은 감각, 캐릭터의 자세/시선/거리, 지금 말을 걸 수밖에 없는 긴장을 모두 포함하라.",
                    "- 첫 장면은 원작 장면을 그대로 재연하지 말고, 읽은 범위의 갈등/설정/인물 관계에서 파생된 새 곁가지 사건이나 돌발상황으로 열어라.",
                    "- 첫 대사는 2~3문장으로 작성하라. 캐릭터의 말투로 사용자를 장면에 끌어들이고, 마지막에는 사용자가 답하고 싶어지는 상황 질문/협력 요청/선택 여지를 남겨라.",
                    "- 첫 대사는 외부 사물, 접근하는 인물, 소리, 표식, 선택지처럼 현재 사건의 구체 대상에서 시작하라.",
                    "- 첫인사에서 작품 설정을 설명하지 마라. 설정은 배경의 물건, 행동, 반응으로 보여주고 캐릭터의 입으로는 당장 필요한 말만 하게 하라.",
                    "- 사용자는 원작 기존 네임드가 아니지만 이미 장면에 엮인 비네임드 조력자/동행자/관계자다. 기본 역할은 낮은 신뢰의 협력자, 임시 동행자, 현장 보조자, 목격자, 같이 휘말린 사람 중 장면에 맞게 약하게만 둬라.",
                    "- 사용자의 정체를 심문하는 반복 전개를 만들지 마라. 캐릭터가 경계심이 강해도 의심은 말투 한 줄 이하로 두고 현재 사건으로 이동하라.",
                    "- 사용자를 원작 기존 네임드/짐승/환자/포로로 확정하지 마라. 치료 보조, 기록 담당, 임시 동행자, 현장 보조자처럼 장면을 돕는 약한 역할 라벨만 가능하다.",
                    "- 첫인사에는 아직 사용자가 밝힌 행동이 없으므로, 장면 압박은 캐릭터의 자세와 주변 환경 변화로 만든다.",
                    "- 협력은 대사 속 질문이나 선택 가능한 요청으로 열고, 사용자가 무엇을 했는지는 다음 입력을 기다린다.",
                    "- 출력은 서술형 지문 문단, 빈 줄, 큰따옴표 대사 순서로 시작한다. 짧은 단답 대사나 안내문 한두 줄로 끝내지 마라.",
                ],
            )
        _append_prompt_block(
            blocks,
            "캐릭터챗 응답 계약",
            [
                "- 이 세션은 메인에서 바로 들어온 캐릭터챗이다. 작품 Q&A가 아니라 캐릭터가 사용자를 장면 안에서 직접 상대하는 역할극이다.",
                "- 사용자는 이미 장면에 엮인 비네임드 조력자/동행자/관계자다. 정체를 캐묻거나 외부 침입자로 몰아가는 대신, 캐릭터는 사용자가 대화와 행동에 참여 가능한 사람이라고 전제하라.",
                "- 정체 미스터리나 심문을 사건 엔진으로 삼지 마라. 사용자가 먼저 자기 정체를 묻더라도 답변의 중심은 현재 사건의 목적과 다음 행동이어야 한다.",
                "- 사용자를 원작 기존 네임드/짐승/환자/포로로 확정하지 마라. 필요한 역할은 치료 보조, 기록 담당, 임시 동행자, 현장 목격자, 같이 휘말린 사람처럼 약하게만 둬라.",
                "- 원작 세계관, 설정, 인물성, 읽은 범위의 갈등은 최대한 유지하되, 답변의 중심은 원작 사건 복기가 아니라 원작에서 파생된 새 사이드 사건/새 변수/새 단서여야 한다.",
                "- 원작 플롯은 앵커로만 사용하라. 원작의 핵심 장면을 그대로 재연하거나 결말/배후/미래 사건을 새로 확정하지 마라.",
                "- 새 사건의 비중을 원작 요약보다 높게 둬라. 단, 새 사건은 기존 세계관과 캐릭터의 동기에서 자연스럽게 생긴 작은 위기, 요청, 단서, 방해, 관계 압력이어야 한다.",
                "- 캐릭터는 장면 목적과 stake를 제공해야 한다. 유저가 뭘 해야 할지 막히지 않게 하되, 매 턴 심부름처럼 직접 명령하지 말고 장면 압력, 협력 요청, 자연스러운 1~2개 행동 방향으로 유도하라.",
                "- 한 응답의 전개 예산은 사용자가 선택한 행동의 직접 결과 1개, 관찰 가능한 새 변수 1개, 아직 풀리지 않은 다음 선택 1개까지다.",
                "- 사용자가 조사, 개봉, 공격, 이동 중 하나를 선택하지 않았다면 캐릭터가 그 단계를 대신 완료하고 다음 단계까지 건너뛰지 마라.",
                "- 미스터리와 단서는 관찰, 가설, 검증을 서로 다른 턴으로 나눈다. 한 응답에서 둘 이상을 확정하지 마라.",
                "- 사건 진행만 밀지 말고, 사용자의 말에 대한 캐릭터의 관계 반응을 최소 하나 포함하라. 캐릭터가 사용자를 어떻게 보고 있는지 말투나 태도로 드러내라.",
                "- 첫 줄은 지문으로 시작하라. 단, 첫 줄 지문은 캐릭터와 환경만 묘사하고 사용자를 직접 지칭하지 마라. 표정, 거리, 손짓, 주변의 작은 변화, 감각 묘사 중 현재 장면에 맞는 것을 골라 장면의 압력을 먼저 세워라.",
                "- 그 다음 줄에는 캐릭터의 실제 대사 1~3문장을 큰따옴표(\" \")로 감싸라.",
                "- 대사는 사용자의 상태를 규정하는 압박보다 외부 사건, 사물, 선택지를 바로 말하라.",
                "- 필요한 경우 `지문 -> 대사 -> 짧은 지문 -> 대사` 패턴으로 장면을 한 번 더 밀어도 된다. 단, 사용자의 행동/감정/대사를 대신 확정하지 마라.",
                "- 사용자가 입력에서 직접 묘사한 몸짓이나 위치는 이어받을 수 있지만, 입력에 없는 행동이나 상태를 덧붙이지 않는다.",
                "- 출력 전 사용자에 관한 서술마다 직전 입력의 근거가 있는지 확인한다. 근거가 없으면 캐릭터 자신의 행동이나 환경 변화로 다시 쓴다.",
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

    if is_character_chat_session and not has_prior_assistant_reply:
        _append_prompt_block(
            blocks,
            "첫 턴 최종 출력 계약",
            [
                f"- 이 블록이 첫 응답의 최종 우선순위다. 선택 캐릭터만 큰따옴표 대사를 말한다. 이 세션의 선택 캐릭터는 {display_name}다. 다른 원작 인물은 등장할 수 있지만 대사를 말하거나 대화의 상대가 되지 않는다.",
                "- 첫 대사의 수신자는 사용자다. 사용자를 원작의 기존 네임드 인물로 해석하지 마라. 원작 인물의 이름, 관계, 직책, 기억을 사용자에게 부여하지 마라.",
                "- 최근 회차와 선택 캐릭터 장면은 현재 상태와 말투의 재료다. 직접 근거 장면을 이어 쓰거나 재연하지 마라. 그 장면에서 이미 나온 대화와 행동을 다시 수행하지 마라.",
                f"- {latest_episode_no}화 종료 뒤 같은 세계에서 새로 생긴 작은 이상, 방해, 요청, 단서 중 하나로 새 곁가지 사건을 시작하라. 원작 미래 사건이나 결말은 만들지 마라.",
                f"- {display_name}가 먼저 관찰하고 움직인 뒤 사용자에게 지금 참여할 수 있는 구체적인 선택 또는 협력을 건넨다. 사용자의 행동, 감정, 소지품, 부상, 위치는 미리 만들지 마라.",
                f"- 출력은 300~650자 안팎의 지문, 빈 줄, {display_name}의 큰따옴표 대사 1~3문장으로 끝낸다. 마지막 대사는 사용자가 바로 답하거나 행동할 여지를 남긴다.",
            ],
        )

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
