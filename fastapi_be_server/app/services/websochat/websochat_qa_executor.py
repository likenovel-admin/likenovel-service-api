from __future__ import annotations

from difflib import SequenceMatcher
import json
import logging
import re
from typing import Any, Awaitable, Callable, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.ai_chat_service import _call_claude_messages, _extract_text, _extract_tool_use_blocks, _to_json_safe
from app.services.websochat.websochat_contracts import (
    WebsochatEvidenceBundle,
    WebsochatQaExecutionResult,
    WebsochatResponsePlan,
)
from app.services.websochat.websochat_context_loader import build_websochat_scope_context_message_for_subtype
from app.services.websochat.websochat_llm import (
    WEBSOCHAT_CREATIVE_TEMPERATURE,
    WEBSOCHAT_QA_TEMPERATURE,
    WEBSOCHAT_REPLY_MAX_TOKENS,
    call_websochat_gemini,
    to_websochat_gemini_contents,
)
from app.services.websochat.websochat_qa_renderer import (
    build_websochat_gemini_context_block,
    build_websochat_recent_context_message,
)

WEBSOCHAT_NEXT_EPISODE_WRITE_MAX_TOKENS = 4096
WEBSOCHAT_NEXT_EPISODE_WRITE_MIN_CHARS = 4800
logger = logging.getLogger(__name__)


WEBSOCHAT_PREDICT_DIRECT_PHRASES = (
    "다음 전개",
    "전개 예상",
    "예상해줘",
    "예상해 봐",
    "앞으로 어떻게",
    "이후 어떻게",
    "어떻게 될까",
    "결말 예상",
)

WEBSOCHAT_NEXT_EPISODE_WRITE_DIRECT_PHRASES = (
    "다음회차 써줘",
    "다음 회차 써줘",
    "다음화 써줘",
    "다음 화 써줘",
    "다음편 써줘",
    "다음 편 써줘",
    "이어 써줘",
    "이어서 써줘",
    "후속편 써줘",
)

WEBSOCHAT_WORLD_SETTING_KEYWORDS = (
    "세계관",
    "설정",
    "규칙",
    "룰",
    "능력",
    "체계",
    "세력",
    "가문",
    "종족",
    "직업",
    "마법",
    "스킬",
    "경지",
    "등급",
    "시스템",
)

WEBSOCHAT_CHARACTER_AXIS_KEYWORDS = (
    "성격",
    "캐해",
    "캐릭터성",
    "말투",
    "매력",
    "성향",
    "혐성",
    "인성",
    "왜 이래",
    "왜 저래",
)

WEBSOCHAT_RELATIONSHIP_KEYWORDS = (
    "관계",
    "관계성",
    "케미",
    "이어지",
    "럽라",
    "로맨스",
    "커플",
    "혐관",
    "라이벌",
    "누구랑",
    "서사선",
)

WEBSOCHAT_PLOT_CLARIFICATION_KEYWORDS = (
    "악역",
    "흑막",
    "떡밥",
    "정체",
    "범인",
    "진실",
    "반전",
    "무슨 일",
    "빌런",
)

WEBSOCHAT_NAME_MEMORY_KEYWORDS = (
    "이름",
    "등장인물",
    "인물 정리",
    "누가 누구",
    "헷갈",
    "뭐하는 애",
    "어떤 애",
    "누구였",
)

WEBSOCHAT_CAN_IT_WORK_LOGIC_KEYWORDS = (
    "가능",
    "말됨",
    "말이 돼",
    "개연성",
    "설정 오류",
    "오류",
    "모순",
    "성립",
    "불가능",
)


def _merge_websochat_priority_summary_rows(
    primary_rows: list[dict[str, Any]],
    secondary_rows: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_keys: set[tuple[int, int, str]] = set()
    for row in [*primary_rows, *secondary_rows]:
        episode_from = int(row.get("episodeFrom") or row.get("episode_from") or 0)
        episode_to = int(row.get("episodeTo") or row.get("episode_to") or 0)
        summary_text = str(row.get("summaryText") or row.get("summary_text") or "").strip()
        dedupe_key = (episode_from, episode_to, summary_text[:120])
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        merged.append(row)
        if len(merged) >= limit:
            break
    return merged

WEBSOCHAT_QA_SUBTYPE_PRIORITY = (
    "can_it_work_logic",
    "plot_clarification",
    "relationship",
    "name_memory",
    "character_axis",
    "world_setting",
    "opinion_general",
)

WEBSOCHAT_RETRIEVAL_ESCALATION_SUBTYPES = {
    "plot_clarification",
    "name_memory",
    "can_it_work_logic",
}
WEBSOCHAT_RETRIEVAL_QUERY_TERM_LIMIT = 6
WEBSOCHAT_RETRIEVAL_EPISODE_LIMIT = 2
WEBSOCHAT_RETRIEVAL_SEARCH_LIMIT = 4
WEBSOCHAT_RETRIEVAL_EPISODE_CHARS = 700
WEBSOCHAT_RETRIEVAL_SEARCH_CHARS = 700
WEBSOCHAT_CLARIFY_RETRY_LIMIT = 2
WEBSOCHAT_ANSWER_FIRST_SUBTYPES = {
    "world_setting",
    "can_it_work_logic",
    "plot_clarification",
}
WEBSOCHAT_FRIEND_TONE_TAIL_TRIM_SUBTYPES = WEBSOCHAT_ANSWER_FIRST_SUBTYPES | {
    "name_memory",
    "relationship",
    "character_axis",
    "opinion_general",
}
WEBSOCHAT_ENTITY_GROUNDING_RETRY_LIMIT = 1


def _is_websochat_predict_query(query_text: str) -> bool:
    normalized = " ".join(str(query_text or "").split())
    if not normalized:
        return False
    if any(phrase in normalized for phrase in WEBSOCHAT_PREDICT_DIRECT_PHRASES):
        return True
    future_cue = any(token in normalized for token in ("앞으로", "이후", "다음", "다음 화", "다음화"))
    predict_cue = any(token in normalized for token in ("예상", "전개", "흐름", "될까", "가설", "가능성"))
    return future_cue and predict_cue


def _is_websochat_next_episode_write_query(query_text: str) -> bool:
    normalized = " ".join(str(query_text or "").split())
    if not normalized:
        return False
    return any(phrase in normalized for phrase in WEBSOCHAT_NEXT_EPISODE_WRITE_DIRECT_PHRASES)


def resolve_websochat_qa_subtype(query_text: str) -> str:
    normalized = " ".join(str(query_text or "").split())
    if not normalized:
        return "opinion_general"

    scores = {
        "world_setting": 0,
        "character_axis": 0,
        "relationship": 0,
        "plot_clarification": 0,
        "name_memory": 0,
        "can_it_work_logic": 0,
        "opinion_general": 0,
    }

    def add_scores(subtype: str, keywords: tuple[str, ...], *, weight: int = 1) -> None:
        for keyword in keywords:
            if keyword in normalized:
                scores[subtype] += weight

    add_scores("world_setting", WEBSOCHAT_WORLD_SETTING_KEYWORDS)
    add_scores("character_axis", WEBSOCHAT_CHARACTER_AXIS_KEYWORDS)
    add_scores("relationship", WEBSOCHAT_RELATIONSHIP_KEYWORDS)
    add_scores("plot_clarification", WEBSOCHAT_PLOT_CLARIFICATION_KEYWORDS)
    add_scores("name_memory", WEBSOCHAT_NAME_MEMORY_KEYWORDS)
    add_scores("can_it_work_logic", WEBSOCHAT_CAN_IT_WORK_LOGIC_KEYWORDS, weight=2)

    if re.search(r"(악역|흑막|빌런).*(누구|뭐|정체)", normalized):
        scores["plot_clarification"] += 4
    if re.search(r"(주인공|캐릭터|인물).*(성격|매력|말투|성향)", normalized):
        scores["character_axis"] += 3
    if re.search(r"(누가 누구|등장인물|이름).*(헷갈|정리|뭐였)", normalized):
        scores["name_memory"] += 4
    if re.search(r"(관계|케미|럽라|혐관|라이벌|이어).*(뭐|어떻|왜)", normalized):
        scores["relationship"] += 3
    if re.search(r"(설정|세계관|규칙|체계|세력).*(뭐|설명|핵심|어떻)", normalized):
        scores["world_setting"] += 3
    if re.search(r"(가능|개연성|모순|오류|말됨|말이 돼)", normalized):
        scores["can_it_work_logic"] += 3


    best_score = max(scores.values())
    if best_score <= 0:
        return "opinion_general"
    for subtype in WEBSOCHAT_QA_SUBTYPE_PRIORITY:
        if scores[subtype] == best_score:
            return subtype
    return "opinion_general"


def _build_websochat_qa_subtype_instruction(qa_subtype: str) -> str:
    if qa_subtype == "world_setting":
        return " 이번 질문은 설정/세계관 설명형이다. 작품 고유명사를 먼저 쓰고, 핵심 규칙을 2~4개 축으로 정리해라. 질문이 넓어도 되묻기 전에 지금 공개 범위에서 설명 가능한 시스템, 규칙, 세력 구조부터 바로 요약해라. 어떤 범위를 말하는지 다시 묻는 서두는 금지하고, 먼저 설명한 뒤 부족한 축만 덧붙여라. 인사, 안내, 질문 유도 문장으로 시작하지 말고 첫 문장부터 바로 설명해라. 마지막도 질문형이 아니라 평서형으로 끝내라."
    if qa_subtype == "character_axis":
        return " 이번 질문은 인물 성격/캐릭터 축 설명형이다. 성격을 한 줄로 먼저 잡고, 그렇게 보이는 행동이나 관계 근거를 붙여라. 질문이 넓어도 현재 공개 범위에서 보이는 성격 축부터 먼저 답해라. 마지막은 친구처럼 평서형으로 마무리하고, 다시 질문으로 넘기지 마라."
    if qa_subtype == "relationship":
        return " 이번 질문은 인물 관계 설명형이다. 관계를 먼저 한 문장으로 정리하고, 왜 그렇게 보이는지 감정선이나 장면 근거를 붙여라. 질문이 넓어도 현재 공개 범위 기준 핵심 관계 1~2개부터 먼저 말해라. 마지막도 다시 질문하지 말고 평서형으로 닫아라."
    if qa_subtype == "plot_clarification":
        return " 이번 질문은 떡밥/정체/악역 확인형이다. 공개 범위 기준으로 가장 유력한 축부터 답하고, 확정이 아니면 선을 분명히 그어라. 질문이 넓어도 되묻기 전에 가장 수상한 축 하나는 먼저 짚어라. 마지막은 질문형 꼬리 없이 평서형으로 끝내라."
    if qa_subtype == "name_memory":
        return " 이번 질문은 이름/등장인물 기억 보조형이다. 헷갈리는 인물을 먼저 구분해서 짧게 정리하고, 호칭 혼선이 있으면 같이 풀어라. 질문이 막연해도 되묻기 전에 현재 공개 범위 기준 주요 인물 3~5명을 먼저 정리해라. 마지막은 다시 물어보지 말고 정리된 평서형으로 끝내라."
    if qa_subtype == "can_it_work_logic":
        return " 이번 질문은 설정 개연성/가능 여부 판단형이다. 공개 범위 기준으로 가능, 불가능, 아직 불명확 중 어디인지 먼저 말하고 근거를 붙여라. 질문이 넓어도 지금 판단 가능한 축부터 먼저 답해라. 질문이 '이 설정', '이거', '이 세계관'처럼 지시대명사형이어도 다시 묻지 말고, 현재 공개 범위에서 가장 중심적인 설정 하나를 네가 골라 그 기준으로 먼저 판단해라. 마지막도 질문형이 아니라 평서형으로 끝내라."
    return " 이번 질문은 자유 감상형 작품대화다. 위키처럼 딱딱하게 정리하지 말고 작품을 아는 사람처럼 같이 떠드는 톤을 유지해라. 질문이 넓어도 되묻기 전에 지금 말할 수 있는 감상부터 먼저 답해라. 마지막은 다시 묻지 말고 네 감상이나 정리로 평서형 마무리를 해라."


def _build_websochat_qa_fallback_reply(qa_subtype: str) -> str:
    if qa_subtype == "world_setting":
        return "지금 공개 범위에서 바로 꺼낼 수 있는 설정 조각은 있는데, 어느 축을 더 보고 싶은지 하나만 집어주면 더 정확하게 풀 수 있습니다. 예를 들면 능력 규칙, 세력 구조, 세계 룰 같은 쪽입니다."
    if qa_subtype == "relationship":
        return "관계 축은 공개 범위 안에서도 바로 풀 수 있는데, 누구와 누구 관계를 보는지 한 번만 더 집어주면 더 정확하게 이어서 답할 수 있습니다."
    if qa_subtype == "character_axis":
        return "인물 축은 바로 풀 수 있는데, 어떤 인물의 성격이나 매력을 보는지 한 명만 집어주면 더 정확하게 답할 수 있습니다."
    if qa_subtype == "name_memory":
        return "이름 축은 정리해 줄 수 있는데, 헷갈리는 인물 이름이나 장면을 한 번만 더 집어주면 바로 정리해 드릴 수 있습니다."
    if qa_subtype == "can_it_work_logic":
        return "이 설정이 말이 되는지는 공개 범위 안에서 따져볼 수 있는데, 어떤 규칙이나 장면을 기준으로 보는지 한 번만 더 짚어주면 더 정확하게 답할 수 있습니다."
    return "지금 공개 범위에서 바로 짚을 수 있는 핵심은 아직 제한적입니다. 그래도 어떤 축이 궁금한지 한 번만 더 집어주면 바로 이어서 답할 수 있습니다."


def _looks_like_websochat_clarifying_reply(text: str, *, qa_subtype: str) -> bool:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return False
    if qa_subtype not in {"world_setting", "can_it_work_logic"}:
        return False
    clarification_patterns = (
        "먼저 확인",
        "어느 범위를",
        "어떤 범위의 설정",
        "말하는 건지",
        "질문을 좀 더 구체적",
        "질문을 구체적",
        "구체적으로 짚어",
        "구체적으로 말씀",
        "구체적으로 지칭",
        "구체적으로 해주",
        "\"이 설정\"이",
        "정확히 무엇을",
        "무엇을 판단",
        "어떤 설정을 판단",
        "어떤 부분의 설정",
        "어느 축의",
        "특정할 수 없",
        "원하는 건가요",
        "궁금한 거라면",
        "알려주면 더 정확",
        "특정 부분",
        "확인이 필요합니다",
        "명확하지 않아서",
        "질문이 있으신가요",
        "편하게 물어봐",
        "궁금하신 부분이 있으면",
    )
    if any(pattern in normalized for pattern in clarification_patterns):
        return True
    if qa_subtype == "can_it_work_logic":
        has_verdict = any(token in normalized for token in ("가능", "불가능", "불명확"))
        looks_like_deferral = any(
            token in normalized
            for token in (
                "죄송",
                "질문",
                "구체",
                "특정",
                "지칭",
                "어떤 설정",
                "판단해야 할지",
                "말씀하는 건지",
            )
        )
        if looks_like_deferral and not has_verdict:
            return True
    return False


def _build_websochat_clarify_retry_message(qa_subtype: str) -> str:
    if qa_subtype == "world_setting":
        return (
            "다시 묻지 말고 바로 설명해라. 현재 공개 범위 안에서 확인되는 설정 핵심 2~4개를 먼저 요약하고, "
            "각 축마다 작품 고유명사를 1개 이상 포함해라. 부족한 부분이 있어도 먼저 설명부터 시작해라. "
            "인사, 안내, 질문 유도 문장은 금지다."
        )
    if qa_subtype == "can_it_work_logic":
        return (
            "다시 묻지 말고 바로 판단해라. 질문이 모호해도 현재 공개 범위에서 가장 중심적인 설정이나 규칙을 기준으로 "
            "가능, 불가능, 아직 불명확 중 어디인지 먼저 말하고, 바로 장면 근거나 작품 고유명사를 붙여라. "
            "최소 2개 이상의 구체적 근거를 써라. '어떤 설정을 말하는지' 다시 묻는 문장과 질문형 마무리는 금지다."
        )
    return ""


def _looks_like_websochat_question_tail(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return False
    lowered = normalized.lower()
    tail_patterns = (
        "?",
        "어떤 축",
        "어느 축",
        "어떤 설정",
        "어느 범위",
        "더 구체적",
        "구체적으로",
        "말해 줄래",
        "말해줄래",
        "집어주",
        "궁금한 거",
        "알고 싶은 부분",
        "어떤 부분",
        "원하는 건가",
        "보고 싶은지",
        "짚어주면",
        "말씀해 주",
        "알아야 합니다",
        "확인이 필요",
        "판단을 위해",
    )
    if any(pattern in lowered for pattern in tail_patterns):
        return True
    return normalized.endswith(("인가요.", "일까요.", "걸까요.", "할까요.", "있어요."))


def _extract_websochat_query_terms(query_text: str) -> list[str]:
    normalized = " ".join(str(query_text or "").split()).strip().lower()
    if not normalized:
        return []
    raw_tokens = re.findall(r"[0-9a-zA-Z가-힣]{2,}", normalized)
    stopwords = {
        "누가", "누구", "뭐", "무엇", "무슨", "왜", "어떻게", "언제", "어디서",
        "설명", "설명했", "말했", "했어", "했대", "했지", "지원", "의심", "등장",
        "까지", "이야기", "정확히", "그때", "지금", "자기", "능력",
        "뭐라고", "무어라고", "어떻게든", "설명됐어", "설명되어", "설명되었", "설명되는",
    }
    boundary_tokens = {
        "누가", "누구", "뭐", "무엇", "무슨", "뭐라고", "무어라고",
        "왜", "어떻게", "언제", "어디서", "설명", "설명했", "설명됐어",
        "말했", "했어", "했대", "했지",
    }
    terms: list[str] = []
    seen: set[str] = set()
    leading_tokens: list[str] = []
    boundary_reached = False

    def _push(value: str) -> None:
        candidate = str(value or "").strip()
        if len(candidate) < 2 or candidate in stopwords or candidate in seen:
            return
        seen.add(candidate)
        terms.append(candidate)

    def _strip_korean_suffixes(token: str) -> list[str]:
        variants: list[str] = []
        stripped = re.sub(
            r"(에게서|에게는|에게|에서|으로는|으로|로는|로|은요|는요|이요|가요|을요|를요|은|는|이|가|을|를|에|도|만|과|와)$",
            "",
            token,
        )
        if stripped and stripped != token:
            variants.append(stripped)
        quoted = re.sub(r"(이라고|라고|냐고|다고|자고|고)$", "", token)
        if quoted and quoted != token:
            variants.append(quoted)
        return variants

    for token in raw_tokens:
        variants = _strip_korean_suffixes(token)
        has_case_particle_suffix = bool(
            re.search(
                r"(에게서|에게는|에게|에서|으로는|으로|로는|로|은요|는요|이요|가요|을요|를요|은|는|이|가|을|를|에|도|만|과|와)$",
                token,
            )
        )
        has_quoted_suffix = bool(re.search(r"(이라고|라고|냐고|다고|자고|고)$", token))
        preferred_terms = list(variants)
        if has_quoted_suffix or not variants or not has_case_particle_suffix:
            preferred_terms.append(token)
        for preferred_term in preferred_terms:
            _push(preferred_term)
        if not boundary_reached:
            token_variants = [token, *variants]
            if any(candidate in boundary_tokens for candidate in token_variants):
                boundary_reached = True
            else:
                preferred = next((candidate for candidate in variants if candidate not in stopwords), token)
                if preferred not in stopwords and len(preferred) >= 2:
                    leading_tokens.append(preferred)
        if len(terms) >= 6:
            break

    if 2 <= len(leading_tokens) <= 4:
        compact_leading = "".join(leading_tokens)
        _push(compact_leading)
    return terms[:6]


def _build_websochat_entity_grounding_text(
    *,
    scope_context: dict[str, Any] | None,
    episode_rows: list[dict[str, Any]],
    search_rows: list[dict[str, Any]],
) -> str:
    parts: list[str] = []
    for row in list((scope_context or {}).get("plot_rows") or [])[:2]:
        parts.append(str(row.get("summary_text") or row.get("summaryText") or ""))
    for row in episode_rows:
        parts.append(str(row.get("content") or row.get("chunkText") or row.get("chunk_text") or ""))
    for row in search_rows[:4]:
        parts.append(str(row.get("chunkText") or row.get("chunk_text") or ""))
    return re.sub(r"\s+", "", "\n".join(part for part in parts if part)).lower()


def _looks_like_websochat_entity_clarify_or_denial_reply(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return False
    patterns = (
        "확인이 필요",
        "정확히 뭘 말하는지",
        "누구인지",
        "등장했나요",
        "등장했나",
        "확인이 안 돼",
        "명확하게 나온 게 없어",
        "명확하게 나오지 않",
        "공개 범위에서 확인이 안",
        "정확히 짚어야 할 것 같아",
    )
    if any(pattern in normalized for pattern in patterns):
        return True
    if "?" in normalized or "？" in normalized:
        return True
    return False


def _should_retry_websochat_entity_grounding(
    *,
    reply: str,
    user_prompt: str,
    scope_context: dict[str, Any] | None,
    episode_rows: list[dict[str, Any]],
    search_rows: list[dict[str, Any]],
) -> bool:
    if not _looks_like_websochat_entity_clarify_or_denial_reply(reply):
        return False
    evidence_text = _build_websochat_entity_grounding_text(
        scope_context=scope_context,
        episode_rows=episode_rows,
        search_rows=search_rows,
    )
    if not evidence_text:
        return False
    query_terms = _extract_websochat_query_terms(user_prompt)
    return any(term and term in evidence_text for term in query_terms)


def _has_websochat_entity_grounding_evidence(
    *,
    user_prompt: str,
    scope_context: dict[str, Any] | None,
    episode_rows: list[dict[str, Any]],
    search_rows: list[dict[str, Any]],
) -> bool:
    evidence_text = _build_websochat_entity_grounding_text(
        scope_context=scope_context,
        episode_rows=episode_rows,
        search_rows=search_rows,
    )
    if not evidence_text:
        return False
    query_terms = _extract_websochat_query_terms(user_prompt)
    return any(term and term in evidence_text for term in query_terms)


def _build_websochat_entity_grounding_retry_message(user_prompt: str) -> str:
    return (
        "공개 컨텍스트와 원문 근거 안에 질문에 등장한 이름 또는 직접 연결된 대상이 이미 보인다. "
        "질문 속 이름이 실제로 등장하는지는 확정된 상태로 보고, 존재 여부를 다시 묻거나 '없다'고 답하지 말고 현재 공개 범위에서 확인되는 사실만 바로 설명해라. "
        "이유가 직접 확정되지 않았으면 누가 의심했고 어떤 맥락에서 언급됐는지까지 말한 뒤, 확정 근거가 아직 없다는 선만 짧게 그어라. "
        f"질문: {user_prompt}"
    )


def _build_websochat_entity_grounding_snippet_message(
    *,
    user_prompt: str,
    episode_rows: list[dict[str, Any]],
    search_rows: list[dict[str, Any]],
) -> str:
    query_terms = _extract_websochat_query_terms(user_prompt)
    if not query_terms:
        return ""

    particle_suffix_re = re.compile(
        r"(에게서|에게는|에게|에서|으로는|으로|로는|로|은요|는요|이요|가요|을요|를요|은|는|이|가|을|를|에|도|만|과|와)$"
    )

    def _compact(value: str) -> str:
        return re.sub(r"\s+", "", str(value or "").lower())

    episode_excerpt_blocks: list[tuple[int, str]] = []
    for row in episode_rows:
        episode_no = int(row.get("episodeNo") or 0)
        content = str(row.get("content") or row.get("chunkText") or row.get("chunk_text") or "").strip()
        compact_content = _compact(content)
        if not content or not any((_compact(term) and _compact(term) in compact_content) for term in query_terms):
            continue
        episode_excerpt_blocks.append((episode_no, content[:2200].strip()))
        if len(episode_excerpt_blocks) >= 2:
            break

    def _term_score(term: str, text: str) -> float:
        compact_term = _compact(term)
        compact_text = _compact(text)
        if not compact_term or not compact_text:
            return 0.0
        if compact_term in compact_text:
            return 100.0 + len(compact_term)
        # Case-particle terms already contribute via stripped exact forms.
        # Suppress fuzzy matching here so names do not dominate action evidence.
        if particle_suffix_re.search(term):
            return 0.0
        token_scores = [
            SequenceMatcher(None, compact_term, _compact(token)).ratio()
            for token in re.findall(r"[0-9a-zA-Z가-힣]{2,}", str(text or ""))
        ]
        best_ratio = max(token_scores, default=0.0)
        if best_ratio >= 0.8:
            return best_ratio * 10.0
        return 0.0

    def _segment_windows(text: str) -> list[str]:
        parts = [part.strip() for part in re.split(r"(?:\n+|(?<=[.!?…])\s+)", str(text or "")) if part.strip()]
        windows: list[str] = []
        for idx, part in enumerate(parts):
            windows.append(part)
            if idx + 1 < len(parts):
                windows.append(f"{part} {parts[idx + 1]}".strip())
            if idx + 2 < len(parts):
                windows.append(f"{part} {parts[idx + 1]} {parts[idx + 2]}".strip())
        return windows

    episode_candidates: list[tuple[float, int, str, set[str]]] = []
    search_candidates: list[tuple[float, int, str, set[str]]] = []
    seen_windows: set[tuple[str, int, str]] = set()

    def _collect_candidates(
        *,
        source: str,
        episode_no: int,
        text: str,
    ) -> None:
        original = str(text or "").strip()
        if not original:
            return
        for window in _segment_windows(original):
            key = (source, episode_no, window)
            if key in seen_windows:
                continue
            seen_windows.add(key)
            matched_terms = {
                term
                for term in query_terms
                if _term_score(term, window) > 0
            }
            if not matched_terms:
                continue
            score = sum(_term_score(term, window) for term in matched_terms)
            target = episode_candidates if source == "episode" else search_candidates
            target.append((score, episode_no, window, matched_terms))

    for row in episode_rows:
        _collect_candidates(
            source="episode",
            episode_no=int(row.get("episodeNo") or 0),
            text=str(row.get("content") or row.get("chunkText") or row.get("chunk_text") or ""),
        )
    for row in search_rows:
        _collect_candidates(
            source="search",
            episode_no=int(row.get("episodeNo") or 0),
            text=str(row.get("chunkText") or row.get("chunk_text") or ""),
        )

    if not episode_candidates and not search_candidates:
        return ""

    def _rank_candidates(
        raw_candidates: list[tuple[float, int, str, set[str]]],
    ) -> list[tuple[int, int, int, float, int, float, int, tuple[str, ...], str]]:
        term_frequency: dict[str, int] = {}
        for _, _, _, matched_terms in raw_candidates:
            for term in matched_terms:
                term_frequency[term] = term_frequency.get(term, 0) + 1

        ranked_candidates: list[tuple[int, int, int, float, int, float, int, tuple[str, ...], str]] = []
        for score, episode_no, window, matched_terms in raw_candidates:
            compact_window = _compact(window)
            exact_terms = [
                term for term in matched_terms
                if (compact_term := _compact(term)) and compact_term in compact_window
            ]
            longest_exact_term_len = max((len(_compact(term)) for term in exact_terms), default=0)
            exact_term_count = len(exact_terms)
            dialogue_bonus = 1 if any(marker in window for marker in ('"', "“", "”", "'")) else 0
            rarity_score = sum(1.0 / max(term_frequency.get(term, 1), 1) for term in matched_terms)
            ranked_candidates.append(
                (
                    longest_exact_term_len,
                    exact_term_count,
                    len(matched_terms),
                    score,
                    dialogue_bonus,
                    rarity_score,
                    episode_no,
                    tuple(sorted(matched_terms)),
                    window,
                )
            )
        ranked_candidates.sort(key=lambda item: (-item[0], -item[1], -item[2], -item[3], -item[4], -item[5], item[6]))
        return ranked_candidates

    ranked_episode_candidates = _rank_candidates(episode_candidates)
    ranked_search_candidates = _rank_candidates(search_candidates)
    snippets: list[tuple[int, str]] = []
    used_snippets: set[tuple[int, str]] = set()
    used_signatures: set[tuple[str, ...]] = set()

    def _append_snippet(episode_no: int, snippet: str) -> bool:
        key = (episode_no, snippet)
        if key in used_snippets:
            return False
        compact_snippet = _compact(snippet)
        for existing_episode_no, existing_snippet in snippets:
            if existing_episode_no != episode_no:
                continue
            compact_existing = _compact(existing_snippet)
            if not compact_existing or not compact_snippet:
                continue
            if compact_snippet in compact_existing or compact_existing in compact_snippet:
                return False
            if SequenceMatcher(None, compact_snippet, compact_existing).ratio() >= 0.82:
                return False
        used_snippets.add(key)
        snippets.append((episode_no, snippet))
        return True

    def _consume_ranked_candidates(
        ranked_candidates: list[tuple[int, int, int, float, int, float, int, tuple[str, ...], str]],
    ) -> None:
        for _, _, _, _, _, _, episode_no, matched_signature, snippet in ranked_candidates:
            if matched_signature in used_signatures:
                continue
            if _append_snippet(episode_no, snippet):
                used_signatures.add(matched_signature)
            if len(snippets) >= 3:
                break
        if len(snippets) < 3:
            for _, _, _, _, _, _, episode_no, _, snippet in ranked_candidates:
                if _append_snippet(episode_no, snippet) and len(snippets) >= 3:
                    break

    _consume_ranked_candidates(ranked_episode_candidates)
    if len(snippets) < 3:
        _consume_ranked_candidates(ranked_search_candidates)

    blocks = [
        "아래는 질문 속 이름이나 직접 연결된 대상을 포함한 원문 발췌다. 이 발췌를 우선 근거로 사용하고, 존재 여부를 부정하지 마라."
    ]
    for episode_no, excerpt in episode_excerpt_blocks:
        blocks.append(f"[{episode_no}화 원문 발췌]\n{excerpt}")
    for episode_no, snippet in snippets:
        blocks.append(f"[{episode_no}화 발췌]\n{snippet}")
    return "\n\n".join(blocks)


def _build_websochat_direct_evidence_instruction() -> str:
    return (
        " 현재 화수에 직접 답이 없더라도 공개 범위 이전 회차 원문에 질문의 직접 답이 있으면, "
        "그 이전 회차 사실을 먼저 단정형으로 답하고 그 다음 현재 화수 맥락을 보강해라."
        " 원문 발췌 안에 직접 진술이나 대사가 있으면 '가능성', '정황', '일 수도'처럼 흐리지 말고 그 진술 자체를 우선 사실로 답해라."
    )


def _finalize_websochat_answer(text: str, *, qa_subtype: str) -> str:
    normalized = str(text or "").strip()
    if not normalized or qa_subtype not in WEBSOCHAT_FRIEND_TONE_TAIL_TRIM_SUBTYPES:
        return normalized

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", normalized) if paragraph.strip()]
    if len(paragraphs) >= 2 and _looks_like_websochat_question_tail(paragraphs[-1]):
        return "\n\n".join(paragraphs[:-1]).strip()

    sentence_splitter = re.compile(r"(?<=[.!?…])\s+")
    sentences = [sentence.strip() for sentence in sentence_splitter.split(normalized) if sentence.strip()]
    if len(sentences) >= 2 and _looks_like_websochat_question_tail(sentences[-1]):
        return " ".join(sentences[:-1]).strip()

    return normalized


def _collect_websochat_logic_fallback_clues(
    *,
    summary_rows: list[dict[str, Any]],
    scope_context: dict[str, Any] | None,
) -> tuple[list[str], list[str]]:
    headings: list[str] = []
    clues: list[str] = []
    seen_headings: set[str] = set()
    seen_clues: set[str] = set()
    raw_texts: list[str] = []

    for row in summary_rows[:3]:
        raw_texts.append(str(row.get("summaryText") or ""))
    for row in list((scope_context or {}).get("plot_rows") or [])[:2]:
        raw_texts.append(str(row.get("summary_text") or row.get("summaryText") or ""))
    for hook in list((scope_context or {}).get("hooks") or [])[:2]:
        if isinstance(hook, dict):
            raw_texts.append(str(hook.get("hook_text") or hook.get("hookText") or hook.get("summary_text") or ""))
        else:
            raw_texts.append(str(hook or ""))

    for raw_text in raw_texts:
        if not raw_text.strip():
            continue
        for heading in re.findall(r"\*\*([^*]{2,40})\*\*", raw_text):
            normalized_heading = " ".join(str(heading or "").split()).strip(" .,:;")
            if not normalized_heading or normalized_heading in seen_headings:
                continue
            seen_headings.add(normalized_heading)
            headings.append(normalized_heading)
            if len(headings) >= 3:
                break

        cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", raw_text)
        cleaned = re.sub(r"[`*_>#-]+", " ", cleaned)
        cleaned = " ".join(cleaned.split())
        for part in re.split(r"(?:\n+|(?<=[.!?])\s+|(?<=다)\s+|(?<=요)\s+|(?<=음)\s+)", cleaned):
            normalized_part = " ".join(str(part or "").split()).strip(" .,:;")
            if len(normalized_part) < 18 or normalized_part in seen_clues:
                continue
            if any(token in normalized_part for token in ("질문", "궁금", "물어봐", "알려줘")):
                continue
            seen_clues.add(normalized_part)
            clues.append(normalized_part)
            if len(clues) >= 3:
                break
        if len(clues) >= 3:
            break

    return headings[:3], clues[:3]


def _build_websochat_can_it_work_logic_fallback(
    *,
    summary_rows: list[dict[str, Any]],
    scope_context: dict[str, Any] | None,
) -> str:
    headings, clues = _collect_websochat_logic_fallback_clues(
        summary_rows=summary_rows,
        scope_context=scope_context,
    )
    if not headings and not clues:
        return (
            "공개 범위 기준으론 아직 불명확해.\n\n"
            "그래도 지금 드러난 정보만 보면 설정 자체가 바로 모순이라고 단정할 정도는 아니고, "
            "작동 원리나 한계가 더 공개돼야 판단이 선다."
        )

    lines: list[str] = ["공개 범위 기준으론 아직 불명확해."]
    if headings:
        lines.append("")
        lines.append(f"그래도 지금 중심 설정 축은 {', '.join(headings)} 쪽이야.")
    if clues:
        lines.append("")
        for clue in clues[:2]:
            lines.append(f"- {clue}")
    lines.append("")
    lines.append("즉 설정 자체가 바로 모순이라고 단정할 정도는 아니지만, 작동 원리나 한계는 더 공개돼야 판단이 선다.")
    return "\n".join(lines).strip()


def _looks_like_websochat_logic_deferral_reply(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return False
    patterns = (
        "질문이",
        "\"이 설정\"",
        "'이 설정'",
        "지시되어",
        "지칭하는지",
        "정확히 뭘 가리키는지",
        "무엇을 가리키는지",
        "무엇을 지칭하는지",
        "어떤 설정의 가능성",
        "어떤 설정을",
        "확인이 필요",
        "명확하지 않",
    )
    return any(pattern in normalized for pattern in patterns)


def _extend_websochat_distinct_terms(
    target: list[str],
    terms: list[str],
    *,
    limit: int = WEBSOCHAT_RETRIEVAL_QUERY_TERM_LIMIT,
) -> None:
    for term in terms:
        normalized = re.sub(r"\s+", " ", str(term or "").strip())
        if not normalized:
            continue
        if normalized in target:
            continue
        target.append(normalized)
        if len(target) >= limit:
            return


def _should_websochat_escalate_retrieval(
    *,
    user_prompt: str,
    qa_subtype: str,
    resolved_mode: str,
    is_predict_query: bool,
    is_next_episode_write_query: bool,
) -> bool:
    if is_predict_query or is_next_episode_write_query:
        return False
    if qa_subtype not in WEBSOCHAT_RETRIEVAL_ESCALATION_SUBTYPES and qa_subtype != "opinion_general":
        return False
    if resolved_mode == "exact":
        return True

    normalized = " ".join(str(user_prompt or "").split())
    if qa_subtype in {"plot_clarification", "name_memory"}:
        return True
    if qa_subtype == "can_it_work_logic":
        return any(token in normalized for token in WEBSOCHAT_CAN_IT_WORK_LOGIC_KEYWORDS + ("왜", "근거"))
    return False


def _build_websochat_retrieval_query(
    *,
    user_prompt: str,
    qa_subtype: str,
    scope_context: dict[str, Any] | None,
) -> str:
    terms: list[str] = []
    _extend_websochat_distinct_terms(terms, [user_prompt], limit=WEBSOCHAT_RETRIEVAL_QUERY_TERM_LIMIT)

    characters = list((scope_context or {}).get("characters") or [])
    hooks = list((scope_context or {}).get("hooks") or [])

    if qa_subtype == "name_memory":
        _extend_websochat_distinct_terms(
            terms,
            [str(item.get("display_name") or "").strip() for item in characters[:4]],
            limit=WEBSOCHAT_RETRIEVAL_QUERY_TERM_LIMIT,
        )
    elif qa_subtype == "plot_clarification":
        _extend_websochat_distinct_terms(terms, [str(item).strip() for item in hooks[:2]], limit=WEBSOCHAT_RETRIEVAL_QUERY_TERM_LIMIT)
        _extend_websochat_distinct_terms(
            terms,
            [str(item.get("display_name") or "").strip() for item in characters[:2]],
            limit=WEBSOCHAT_RETRIEVAL_QUERY_TERM_LIMIT,
        )
    elif qa_subtype == "can_it_work_logic":
        _extend_websochat_distinct_terms(
            terms,
            [str(item.get("display_name") or "").strip() for item in characters[:2]],
            limit=WEBSOCHAT_RETRIEVAL_QUERY_TERM_LIMIT,
        )
        _extend_websochat_distinct_terms(terms, [str(item).strip() for item in hooks[:1]], limit=WEBSOCHAT_RETRIEVAL_QUERY_TERM_LIMIT)

    return " ".join(terms)[:160]


async def _load_websochat_escalated_evidence(
    *,
    product_id: int,
    latest_episode_no: int,
    user_prompt: str,
    qa_subtype: str,
    resolved_mode: str,
    resolved_episode_no: int | None,
    summary_rows: list[dict[str, Any]],
    scope_context: dict[str, Any] | None,
    hooks: WebsochatQaExecutionHooks,
    db: AsyncSession,
) -> dict[str, Any]:
    should_escalate = _should_websochat_escalate_retrieval(
        user_prompt=user_prompt,
        qa_subtype=qa_subtype,
        resolved_mode=resolved_mode,
        is_predict_query=False,
        is_next_episode_write_query=False,
    )

    if not should_escalate and not resolved_episode_no:
        return {
            "retrieval_escalated": False,
            "retrieval_stage": "none",
            "retrieval_query": "",
            "episode_rows": [],
            "search_rows": [],
        }

    candidate_episode_nos: list[int] = []
    for episode_no in [resolved_episode_no, *[int(row.get("episodeTo") or row.get("episodeFrom") or 0) for row in summary_rows[:WEBSOCHAT_RETRIEVAL_EPISODE_LIMIT]]]:
        if episode_no is None:
            continue
        safe_episode_no = int(episode_no or 0)
        if safe_episode_no <= 0 or safe_episode_no > latest_episode_no:
            continue
        if safe_episode_no in candidate_episode_nos:
            continue
        candidate_episode_nos.append(safe_episode_no)

    if resolved_episode_no and resolved_episode_no > 1:
        previous_episode_no = int(resolved_episode_no) - 1
        if previous_episode_no not in candidate_episode_nos:
            candidate_episode_nos.append(previous_episode_no)

    episode_rows: list[dict[str, Any]] = []
    for episode_no in candidate_episode_nos[:WEBSOCHAT_RETRIEVAL_EPISODE_LIMIT]:
        episode_rows.extend(
            await hooks["get_episode_contents"](
                product_id=product_id,
                episode_from=episode_no,
                episode_to=episode_no,
                latest_episode_no=latest_episode_no,
                db=db,
            )
        )

    retrieval_stage = "episode_fetch" if episode_rows else "none"
    retrieval_query = _build_websochat_retrieval_query(
        user_prompt=user_prompt,
        qa_subtype=qa_subtype,
        scope_context=scope_context,
    )

    search_rows: list[dict[str, Any]] = []
    query_terms = _extract_websochat_query_terms(user_prompt)
    should_search_chunks = (
        bool(retrieval_query)
        and (
            qa_subtype in {"plot_clarification", "name_memory"}
            or (resolved_mode == "general" and bool(candidate_episode_nos) and bool(query_terms))
        )
    )
    if should_search_chunks:
        search_rows = (
            await hooks["search_episode_contents"](
                product_id=product_id,
                query_text=retrieval_query,
                latest_episode_no=latest_episode_no,
                db=db,
            )
        )[:WEBSOCHAT_RETRIEVAL_SEARCH_LIMIT]
        if candidate_episode_nos and search_rows:
            candidate_episode_set = set(candidate_episode_nos)
            candidate_only_rows = [
                row for row in search_rows if int(row.get("episodeNo") or 0) in candidate_episode_set
            ]
            if candidate_only_rows:
                top_candidate_score = max(float(row.get("matchScore") or 0.0) for row in candidate_only_rows)
                top_overall_score = max(float(row.get("matchScore") or 0.0) for row in search_rows)
                if top_overall_score <= top_candidate_score:
                    search_rows = candidate_only_rows
        if search_rows:
            top_search_episode_no = int(search_rows[0].get("episodeNo") or 0)
            top_search_score = float(search_rows[0].get("matchScore") or 0.0)
            top_episode_score = 0.0
            search_episode_scores: dict[int, float] = {}
            for row in search_rows:
                episode_no = int(row.get("episodeNo") or 0)
                if episode_no in candidate_episode_nos:
                    top_episode_score = max(top_episode_score, float(row.get("matchScore") or 0.0))
                if episode_no > 0:
                    search_episode_scores[episode_no] = max(
                        search_episode_scores.get(episode_no, 0.0),
                        float(row.get("matchScore") or 0.0),
                    )
            if (
                top_search_episode_no > 0
                and top_search_episode_no not in candidate_episode_nos
                and top_search_score > top_episode_score
                and top_search_episode_no <= latest_episode_no
            ):
                promoted_rows = await hooks["get_episode_contents"](
                    product_id=product_id,
                    episode_from=top_search_episode_no,
                    episode_to=top_search_episode_no,
                    latest_episode_no=latest_episode_no,
                    db=db,
                )
                if promoted_rows:
                    existing_episode_nos = {
                        int(row.get("episodeNo") or 0)
                        for row in episode_rows
                        if int(row.get("episodeNo") or 0) > 0
                    }
                    if top_search_episode_no not in existing_episode_nos:
                        episode_rows = [*promoted_rows, *episode_rows]
            if episode_rows and search_episode_scores:
                episode_rows = sorted(
                    episode_rows,
                    key=lambda row: (
                        -search_episode_scores.get(int(row.get("episodeNo") or 0), 0.0),
                        -int(row.get("episodeNo") or 0),
                    ),
                )
        if search_rows:
            retrieval_stage = "chunk_search"

    logger.info(
        "websochat qa_retrieval_escalation qa_subtype=%s escalated=%s stage=%s evidence_count=%s candidate_episode_nos=%s episode_row_episodes=%s search_row_episodes=%s query=%r prompt_preview=%r",
        qa_subtype,
        should_escalate,
        retrieval_stage,
        len(episode_rows) + len(search_rows),
        candidate_episode_nos,
        sorted({int(row.get('episodeNo') or 0) for row in episode_rows if int(row.get('episodeNo') or 0) > 0}),
        sorted({int(row.get('episodeNo') or 0) for row in search_rows if int(row.get('episodeNo') or 0) > 0}),
        retrieval_query,
        " ".join(str(user_prompt or "").split())[:120],
    )
    return {
        "retrieval_escalated": should_escalate,
        "retrieval_stage": retrieval_stage,
        "retrieval_query": retrieval_query,
        "episode_rows": episode_rows,
        "search_rows": search_rows,
    }


def _build_websochat_retrieval_context_message(
    *,
    qa_subtype: str,
    episode_rows: list[dict[str, Any]],
    search_rows: list[dict[str, Any]],
) -> str:
    if not episode_rows and not search_rows:
        return ""

    intro = "아래는 이번 질문에 더 직접 닿는 공개 근거다. 먼저 사실을 정리하고, 그 다음 해석이나 의견을 얹어라."
    if qa_subtype == "name_memory":
        intro = "아래는 등장인물 식별에 직접 도움이 되는 공개 근거다. 누가 누구인지 먼저 짧게 정리하고, 필요한 경우만 보충 설명해라."
    elif qa_subtype == "plot_clarification":
        intro = "아래는 떡밥/정체 판단에 직접 닿는 공개 근거다. 가장 유력한 축을 먼저 말하고, 확정이 아니면 선을 그어라."
    elif qa_subtype == "can_it_work_logic":
        intro = "아래는 설정 가능 여부를 판단할 때 직접 참고할 공개 근거다. 가능/불가능/불명확을 먼저 말하고, 장면 근거를 붙여라."

    blocks: list[str] = [intro]
    for row in episode_rows[:WEBSOCHAT_RETRIEVAL_EPISODE_LIMIT]:
        content = str(row.get("content") or row.get("chunkText") or row.get("chunk_text") or "").strip()
        if not content:
            continue
        blocks.append(f"[{int(row.get('episodeNo') or 0)}화 원문 일부]\n{content[:WEBSOCHAT_RETRIEVAL_EPISODE_CHARS]}")
    for row in search_rows[:WEBSOCHAT_RETRIEVAL_SEARCH_LIMIT]:
        chunk_text = str(row.get("chunkText") or "").strip()
        if not chunk_text:
            continue
        blocks.append(f"[{int(row.get('episodeNo') or 0)}화 단서]\n{chunk_text[:WEBSOCHAT_RETRIEVAL_SEARCH_CHARS]}")
    return "\n\n".join(blocks)


def _collect_websochat_evidence_episode_nos(
    *,
    summary_rows: list[dict[str, Any]],
    episode_rows: list[dict[str, Any]],
    search_rows: list[dict[str, Any]],
    scope_context: dict[str, Any] | None,
    latest_episode_no: int,
) -> list[int]:
    def _row_episode_no(row: dict[str, Any]) -> int:
        return int(
            row.get("episodeNo")
            or row.get("episode_no")
            or row.get("episodeTo")
            or row.get("episode_to")
            or row.get("episodeFrom")
            or row.get("episode_from")
            or 0
        )

    def _collect(rows: list[dict[str, Any]]) -> list[int]:
        collected: list[int] = []
        seen: set[int] = set()
        for row in rows:
            episode_no = _row_episode_no(row)
            if episode_no <= 0 or episode_no > latest_episode_no or episode_no in seen:
                continue
            seen.add(episode_no)
            collected.append(episode_no)
        return collected

    for rows in (
        search_rows,
        episode_rows,
        summary_rows,
        list((scope_context or {}).get("plot_rows") or []),
    ):
        episode_nos = _collect(rows)
        if episode_nos:
            return sorted(episode_nos)[:3]
    return []


def _should_websochat_skip_tools(
    *,
    user_prompt: str,
    qa_plan: WebsochatResponsePlan,
) -> bool:
    return False


def _build_websochat_recent_title_pattern_message(
    episode_rows: list[dict[str, Any]],
) -> str:
    titled_rows = [row for row in episode_rows if str(row.get("episodeTitle") or "").strip()]
    if not titled_rows:
        return ""
    lines: list[str] = []
    for row in titled_rows[-3:]:
        title = str(row.get("episodeTitle") or "").strip()
        if not title:
            continue
        lines.append(f"- {title}")
    if not lines:
        return ""
    return (
        "아래는 최근 공개 회차 제목 원문이다. 데이터상 제목 앞 숫자 표기는 실제 회차 번호와 다를 수 있으니, "
        "숫자는 절대 따라 쓰지 말고 제목의 결, 마침표 유무, 부제 리듬만 참고하라.\n"
        + "\n".join(lines)
    )


async def _retry_websochat_next_episode_write_with_gemini(
    *,
    system_prompt: str,
    messages: list[dict[str, str]],
) -> str:
    retry_messages = list(messages)
    retry_messages.append(
        {
            "role": "user",
            "content": (
                "방금 초안은 너무 짧았다. 제목 한 줄과 본문 형식은 유지하되, 이번에는 4800자 이상 5200자 이하를 목표로 "
                "장면을 더 충분히 전개해서 처음부터 다시 써라. 요약하지 말고 갈등, 대사, 감정 변화를 더 쌓아라."
            ),
        }
    )
    return await call_websochat_gemini(
        system_prompt=system_prompt,
        messages=to_websochat_gemini_contents(retry_messages),
        max_tokens=WEBSOCHAT_NEXT_EPISODE_WRITE_MAX_TOKENS,
        temperature=WEBSOCHAT_CREATIVE_TEMPERATURE,
    )


class WebsochatQaExecutionHooks(TypedDict):
    resolve_summary_mode: Callable[..., tuple[str, int | None, Any, Any]]
    resolve_exact_episode_no: Callable[..., Awaitable[int | None]]
    extract_keywords: Callable[[str], list[str]]
    get_summary_candidates: Callable[..., Awaitable[list[dict[str, Any]]]]
    get_broad_summary_context_rows: Callable[..., Awaitable[list[dict[str, Any]]]]
    resolve_reference: Callable[..., Awaitable[dict[str, Any]]]
    build_reference_resolution_message: Callable[[dict[str, Any]], str]
    get_episode_contents: Callable[..., Awaitable[list[dict[str, Any]]]]
    search_episode_contents: Callable[..., Awaitable[list[dict[str, Any]]]]
    get_public_episode_refs: Callable[..., Awaitable[list[dict[str, Any]]]]
    build_system_prompt: Callable[[dict[str, Any]], str]
    build_summary_context_message: Callable[..., str]
    is_ambiguous_reference_query: Callable[[str], bool]
    dispatch_tool: Callable[..., Awaitable[dict[str, Any]]]


async def _generate_websochat_reply_with_gemini(
    *,
    product_row: dict[str, Any],
    user_prompt: str,
    resolved_mode: str,
    evidence_bundle: WebsochatEvidenceBundle,
    recent_messages: list[dict[str, str]],
    qa_plan: WebsochatResponsePlan,
    qa_recent_notes: list[str],
    qa_corrections: list[dict[str, str]],
    current_qa_corrections: list[dict[str, str]],
    db: AsyncSession,
    hooks: WebsochatQaExecutionHooks,
    gemini_context_episode_limit: int,
    prefetch_context_chars: int,
) -> tuple[str, list[int]]:
    scope_read_episode_to = evidence_bundle["resolved_scope"]["read_episode_to"]
    scope_context = evidence_bundle["scope_context"]
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    effective_latest_episode_no = min(max(int(scope_read_episode_to or 0), 1), max(latest_episode_no, 1))
    qa_subtype = str(qa_plan.get("qa_subtype") or resolve_websochat_qa_subtype(user_prompt)).strip().lower() or "opinion_general"
    is_predict_query = _is_websochat_predict_query(user_prompt)
    is_next_episode_write_query = _is_websochat_next_episode_write_query(user_prompt)
    has_scope_context = bool(
        scope_context
        and (
            scope_context.get("plot_rows")
            or scope_context.get("characters")
            or scope_context.get("relations")
            or scope_context.get("hooks")
        )
    )
    resolved_mode, exact_episode_no, _, _ = hooks["resolve_summary_mode"](
        query_text=user_prompt,
        latest_episode_no=effective_latest_episode_no,
        mode=resolved_mode,
    )
    if (is_predict_query or is_next_episode_write_query) and resolved_mode == "general":
        resolved_mode = "latest"
    resolved_episode_no = None
    if resolved_mode == "exact":
        resolved_episode_no = await hooks["resolve_exact_episode_no"](
            product_id=int(product_row.get("productId") or 0),
            latest_episode_no=effective_latest_episode_no,
            query_text=user_prompt,
            fallback_episode_no=exact_episode_no,
            db=db,
        )

    keywords = hooks["extract_keywords"](user_prompt)
    if resolved_mode == "exact":
        summary_rows = await hooks["get_summary_candidates"](
            product_id=int(product_row.get("productId") or 0),
            keywords=keywords,
            query_text=user_prompt,
            latest_episode_no=effective_latest_episode_no,
            mode=resolved_mode,
            episode_no=resolved_episode_no,
            db=db,
        )
    else:
        summary_rows = await hooks["get_broad_summary_context_rows"](
            product_id=int(product_row.get("productId") or 0),
            query_text=user_prompt,
            latest_episode_no=effective_latest_episode_no,
            resolved_mode=resolved_mode,
            qa_subtype=qa_subtype,
            qa_corrections=qa_corrections,
            db=db,
        )
    if resolved_mode == "general":
        current_scope_rows = list((scope_context or {}).get("plot_rows") or [])
        if current_scope_rows:
            summary_rows = _merge_websochat_priority_summary_rows(
                current_scope_rows[:1],
                summary_rows,
                limit=max(4, gemini_context_episode_limit),
            )
            logger.info(
                "websochat qa_current_scope_priority applied=true scope_ranges=%s merged_ranges=%s prompt_preview=%r",
                [
                    (
                        int(row.get("episode_from") or row.get("episodeFrom") or 0),
                        int(row.get("episode_to") or row.get("episodeTo") or 0),
                    )
                    for row in current_scope_rows[:1]
                ],
                [
                    (
                        int(row.get("episodeFrom") or row.get("episode_from") or 0),
                        int(row.get("episodeTo") or row.get("episode_to") or 0),
                    )
                    for row in summary_rows[:5]
                ],
                " ".join(str(user_prompt or "").split())[:120],
            )

    reference_resolution = await hooks["resolve_reference"](
        product_row=product_row,
        user_prompt=user_prompt,
        recent_messages=recent_messages,
        summary_rows=summary_rows,
    )
    logger.info(
        "websochat qa_reference_resolution ambiguous_query=%s resolved=%s status=%s confidence=%s summary_ranges=%s prompt_preview=%r",
        hooks["is_ambiguous_reference_query"](user_prompt),
        bool(reference_resolution),
        str((reference_resolution or {}).get("reference_status") or "").strip(),
        (reference_resolution or {}).get("confidence"),
        [
            (
                int(row.get("episodeFrom") or 0),
                int(row.get("episodeTo") or 0),
            )
            for row in summary_rows[:5]
        ],
        " ".join(str(user_prompt or "").split())[:120],
    )

    retrieval_bundle = await _load_websochat_escalated_evidence(
        product_id=int(product_row.get("productId") or 0),
        latest_episode_no=effective_latest_episode_no,
        user_prompt=user_prompt,
        qa_subtype=qa_subtype,
        resolved_mode=resolved_mode,
        resolved_episode_no=resolved_episode_no,
        summary_rows=summary_rows,
        scope_context=scope_context,
        hooks=hooks,
        db=db,
    )
    episode_rows: list[dict[str, Any]] = list(retrieval_bundle.get("episode_rows") or [])
    search_rows: list[dict[str, Any]] = list(retrieval_bundle.get("search_rows") or [])
    if not episode_rows and not resolved_episode_no:
        target_episode_nos: list[int] = []
        for row in summary_rows[:gemini_context_episode_limit]:
            episode_no = int(row.get("episodeTo") or row.get("episodeFrom") or 0)
            if episode_no > 0 and episode_no not in target_episode_nos:
                target_episode_nos.append(episode_no)
        for episode_no in target_episode_nos[:gemini_context_episode_limit]:
            episode_rows.extend(
                await hooks["get_episode_contents"](
                    product_id=int(product_row.get("productId") or 0),
                    episode_from=episode_no,
                    episode_to=episode_no,
                    latest_episode_no=effective_latest_episode_no,
                    db=db,
                )
            )
    referenced_episode_nos = _collect_websochat_evidence_episode_nos(
        summary_rows=summary_rows,
        episode_rows=episode_rows,
        search_rows=search_rows,
        scope_context=scope_context,
        latest_episode_no=effective_latest_episode_no,
    )

    system_prompt = (
        hooks["build_system_prompt"](product_row)
        + " 이번 응답은 확장형 질문용 응답이다. 제공된 공개 컨텍스트만으로 잘 놀아주되, 근거 없는 설정을 단정하지 마라."
        + " 비교/시뮬레이션 답변이라도 근거가 되는 회차나 장면을 1개 이상 자연스럽게 인용하라."
        + " 원문에 없는 추론은 '작품 내 직접 묘사는 없지만'처럼 추론임을 분명히 밝혀라."
        + _build_websochat_direct_evidence_instruction()
        + " 능력, 범위, 지속시간, 거리, 숫자 같은 수치 정보가 공개 범위에 있으면 가능한 한 포함하라."
        + " 작품 고유명사(인물명, 세력명, 사건명, 능력명)를 가능하면 2개 이상 자연스럽게 포함하고, 장르 일반론으로만 때우지 마라."
        + " 사용자가 특정 인물·세력·사건 이름을 물었고 현재 스코프 요약/컨텍스트에 그 이름이나 직접 연결된 관계가 보이면, 곧바로 '없다'거나 '확인이 안 된다'고 답하지 말고 현재 스코프 기준으로 가장 가까운 근거부터 설명하라."
        + _build_websochat_qa_subtype_instruction(qa_subtype)
    )
    if is_predict_query:
        system_prompt += (
            " 이번 질문은 다음 전개 예상이다. 읽은 범위 안 최신 갈등, 관계 변화, 떡밥을 우선 근거로 삼아라."
            " 답은 먼저 가장 가능성 높게 보는 흐름을 한 줄로 베팅하고, 이어서 가능성 있는 가설을 2~3개로 나눠 풀어라."
            " 각 가설에는 왜 그렇게 보는지 근거가 되는 공개 회차, 장면, 감정선, 미해결 변수를 자연스럽게 붙여라."
            " 스포일러처럼 확정하지는 말되, 지나치게 소심하게 흐리지 말고 흥미롭게 풀어라."
            " 마지막에는 이야기를 더 궁금하게 만드는 변수나 갈림길을 한 가지 남겨라."
        )
    if is_next_episode_write_query:
        next_episode_no = effective_latest_episode_no + 1
        system_prompt += (
            " 이번 질문은 다음 회차 창작이다. 읽은 범위 안 공개된 사건, 관계, 감정선, 떡밥만 재료로 써라."
            " 출력은 제목 한 줄 다음에 바로 본문만 써라. 목록, 불릿, 번호 매기기, 메타 설명은 금지다."
            f" 제목 첫 줄의 회차 번호는 반드시 {next_episode_no}화로 시작하라. 이 숫자는 절대 바꾸지 마라."
            " 최근 회차 제목 패턴은 숫자가 아니라 제목 결만 참고하고, 제목 앞 번호 표기를 베끼지 마라."
            " 본문은 실제 다음 화처럼 장면과 대사 중심으로 이어가라."
            " 공식 연재를 아는 척하거나 비공개 정보를 끌어오지 말고, 읽은 범위에서 자연스럽게 이어질 법한 가상 다음화로 써라."
            " 길이는 6000자 이내로 유지하되, 본문은 가능하면 4800자 이상 5200자 이하를 목표로 해서 너무 짧게 끝내지 말고 읽는 맛이 있게 써라."
            " 장면은 최소 3개 이상 전개하고, 중간에 바로 끝내지 말고 갈등과 감정의 파동을 충분히 쌓아라."
        )
    context_block = build_websochat_gemini_context_block(
        product_row=product_row,
        summary_rows=summary_rows,
        episode_rows=episode_rows,
        search_rows=search_rows,
        episode_limit=gemini_context_episode_limit,
        preview_chars=prefetch_context_chars,
    )
    messages = list(recent_messages)
    recent_context_message = build_websochat_recent_context_message(
        recent_messages,
        qa_recent_notes=qa_recent_notes,
        qa_corrections=qa_corrections,
        current_qa_corrections=current_qa_corrections,
    )
    if recent_context_message:
        messages.append({"role": "user", "content": recent_context_message})
    scope_context_message = build_websochat_scope_context_message_for_subtype(
        scope_context or {},
        qa_subtype,
        query_text=user_prompt,
    )
    if scope_context_message:
        messages.append(
            {
                "role": "user",
                "content": (
                    "아래는 현재 공개 범위 기준으로 미리 정리된 작품 컨텍스트다. "
                    "질문 유형에 맞춰 필요한 축부터 우선 참고하라.\n\n"
                    f"{scope_context_message}"
                ),
            }
        )
    if is_next_episode_write_query:
        title_rows = await hooks["get_public_episode_refs"](
            product_id=int(product_row.get("productId") or 0),
            latest_episode_no=effective_latest_episode_no,
            db=db,
        )
        title_pattern_message = _build_websochat_recent_title_pattern_message(title_rows)
        if title_pattern_message:
            messages.append({"role": "user", "content": title_pattern_message})
    if hooks["is_ambiguous_reference_query"](user_prompt):
        reference_message = hooks["build_reference_resolution_message"](reference_resolution or {})
        if reference_message:
            messages.append({"role": "user", "content": reference_message})
    retrieval_context_message = _build_websochat_retrieval_context_message(
        qa_subtype=qa_subtype,
        episode_rows=episode_rows,
        search_rows=search_rows,
    )
    if retrieval_context_message:
        messages.append({"role": "user", "content": retrieval_context_message})
    if _has_websochat_entity_grounding_evidence(
        user_prompt=user_prompt,
        scope_context=scope_context,
        episode_rows=episode_rows,
        search_rows=search_rows,
    ):
        logger.info(
            "websochat qa_entity_grounding_hint applied=true qa_subtype=%s prompt_preview=%r",
            qa_subtype,
            " ".join(str(user_prompt or "").split())[:120],
        )
        messages.append(
            {
                "role": "user",
                "content": _build_websochat_entity_grounding_retry_message(user_prompt),
            }
        )
        snippet_message = _build_websochat_entity_grounding_snippet_message(
            user_prompt=user_prompt,
            episode_rows=episode_rows,
            search_rows=search_rows,
        )
        if snippet_message:
            messages.append({"role": "user", "content": snippet_message})
    messages.append(
        {
            "role": "user",
            "content": (
                "아래 공개 컨텍스트를 우선 참고해 답하라.\n\n"
                f"{context_block}\n\n"
                f"질문: {user_prompt}"
            ),
        }
    )
    # `next_episode_write` keeps the model busy for a long time. Release the
    # read-only transaction before the provider call so the session does not
    # hold a DB connection across the whole generation window.
    if is_next_episode_write_query:
        await db.rollback()

    reply = await call_websochat_gemini(
        system_prompt=system_prompt,
        messages=to_websochat_gemini_contents(messages),
        max_tokens=WEBSOCHAT_NEXT_EPISODE_WRITE_MAX_TOKENS if is_next_episode_write_query else WEBSOCHAT_REPLY_MAX_TOKENS,
        temperature=WEBSOCHAT_CREATIVE_TEMPERATURE if (is_predict_query or is_next_episode_write_query) else WEBSOCHAT_QA_TEMPERATURE,
    )
    clarify_retry_count = 0
    entity_grounding_retry_count = 0
    while (
        qa_subtype in {"world_setting", "can_it_work_logic"}
        and not is_predict_query
        and not is_next_episode_write_query
        and clarify_retry_count < WEBSOCHAT_CLARIFY_RETRY_LIMIT
        and (summary_rows or has_scope_context or episode_rows or search_rows)
        and _looks_like_websochat_clarifying_reply(reply, qa_subtype=qa_subtype)
    ):
        messages.append({"role": "assistant", "content": reply})
        messages.append(
            {
                "role": "user",
                "content": _build_websochat_clarify_retry_message(qa_subtype),
            }
        )
        clarify_retry_count += 1
        reply = await call_websochat_gemini(
            system_prompt=system_prompt,
            messages=to_websochat_gemini_contents(messages),
            max_tokens=WEBSOCHAT_REPLY_MAX_TOKENS,
            temperature=WEBSOCHAT_QA_TEMPERATURE,
        )
    while (
        not is_predict_query
        and not is_next_episode_write_query
        and entity_grounding_retry_count < WEBSOCHAT_ENTITY_GROUNDING_RETRY_LIMIT
        and _should_retry_websochat_entity_grounding(
            reply=reply,
            user_prompt=user_prompt,
            scope_context=scope_context,
            episode_rows=episode_rows,
            search_rows=search_rows,
        )
    ):
        messages.append({"role": "assistant", "content": reply})
        messages.append(
            {
                "role": "user",
                "content": _build_websochat_entity_grounding_retry_message(user_prompt),
            }
        )
        entity_grounding_retry_count += 1
        logger.info(
            "websochat qa_entity_grounding_retry applied=true retry_count=%s qa_subtype=%s prompt_preview=%r",
            entity_grounding_retry_count,
            qa_subtype,
            " ".join(str(user_prompt or "").split())[:120],
        )
        reply = await call_websochat_gemini(
            system_prompt=system_prompt,
            messages=to_websochat_gemini_contents(messages),
            max_tokens=WEBSOCHAT_REPLY_MAX_TOKENS,
            temperature=WEBSOCHAT_QA_TEMPERATURE,
        )
    if (
        qa_subtype == "can_it_work_logic"
        and (
            _looks_like_websochat_clarifying_reply(reply, qa_subtype=qa_subtype)
            or _looks_like_websochat_logic_deferral_reply(reply)
        )
    ):
        fallback_reply = _build_websochat_can_it_work_logic_fallback(
            summary_rows=summary_rows,
            scope_context=scope_context,
        )
        if fallback_reply:
            return fallback_reply, referenced_episode_nos
    if is_next_episode_write_query and len(reply) < WEBSOCHAT_NEXT_EPISODE_WRITE_MIN_CHARS:
        await db.rollback()
        retry_reply = await _retry_websochat_next_episode_write_with_gemini(
            system_prompt=system_prompt,
            messages=messages,
        )
        if len(retry_reply) >= len(reply):
            return retry_reply, referenced_episode_nos
    return _finalize_websochat_answer(reply, qa_subtype=qa_subtype), referenced_episode_nos


async def _generate_websochat_reply_with_claude(
    *,
    product_row: dict[str, Any],
    user_prompt: str,
    resolved_mode: str,
    evidence_bundle: WebsochatEvidenceBundle,
    recent_messages: list[dict[str, str]],
    qa_plan: WebsochatResponsePlan,
    qa_recent_notes: list[str],
    qa_corrections: list[dict[str, str]],
    current_qa_corrections: list[dict[str, str]],
    db: AsyncSession,
    hooks: WebsochatQaExecutionHooks,
    max_tool_rounds: int,
    tools: list[dict[str, Any]],
    prefetch_context_chars: int,
) -> tuple[str, list[int]]:
    scope_read_episode_to = evidence_bundle["resolved_scope"]["read_episode_to"]
    scope_context = evidence_bundle["scope_context"]
    system_prompt = hooks["build_system_prompt"](product_row)
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    effective_latest_episode_no = min(max(int(scope_read_episode_to or 0), 1), max(latest_episode_no, 1))
    qa_subtype = str(qa_plan.get("qa_subtype") or resolve_websochat_qa_subtype(user_prompt)).strip().lower() or "opinion_general"
    is_predict_query = _is_websochat_predict_query(user_prompt)
    is_next_episode_write_query = _is_websochat_next_episode_write_query(user_prompt)
    has_scope_context = bool(
        scope_context
        and (
            scope_context.get("plot_rows")
            or scope_context.get("characters")
            or scope_context.get("relations")
            or scope_context.get("hooks")
        )
    )
    messages = list(recent_messages)
    clarify_retry_count = 0
    recent_context_message = build_websochat_recent_context_message(
        recent_messages,
        qa_recent_notes=qa_recent_notes,
        qa_corrections=qa_corrections,
        current_qa_corrections=current_qa_corrections,
    )
    if recent_context_message:
        messages.append({"role": "user", "content": recent_context_message})
    scope_context_message = build_websochat_scope_context_message_for_subtype(
        scope_context or {},
        qa_subtype,
        query_text=user_prompt,
    )
    if scope_context_message:
        messages.append(
            {
                "role": "user",
                "content": (
                    "아래는 현재 공개 범위 기준으로 미리 정리된 작품 컨텍스트다. "
                    "질문 유형에 맞춰 필요한 축부터 우선 참고하라.\n\n"
                    f"{scope_context_message}"
                ),
            }
        )
    if is_next_episode_write_query:
        title_rows = await hooks["get_public_episode_refs"](
            product_id=int(product_row.get("productId") or 0),
            latest_episode_no=effective_latest_episode_no,
            db=db,
        )
        title_pattern_message = _build_websochat_recent_title_pattern_message(title_rows)
        if title_pattern_message:
            messages.append({"role": "user", "content": title_pattern_message})
    resolved_mode, exact_episode_no, _, _ = hooks["resolve_summary_mode"](
        query_text=user_prompt,
        latest_episode_no=effective_latest_episode_no,
        mode=resolved_mode,
    )
    if (is_predict_query or is_next_episode_write_query) and resolved_mode == "general":
        resolved_mode = "latest"
    if resolved_mode == "exact":
        resolved_episode_no = await hooks["resolve_exact_episode_no"](
            product_id=int(product_row.get("productId") or 0),
            latest_episode_no=effective_latest_episode_no,
            query_text=user_prompt,
            fallback_episode_no=exact_episode_no,
            db=db,
        )
    else:
        resolved_episode_no = None

    prefetched_summary_rows: list[dict[str, Any]] = []
    if resolved_mode != "exact":
        prefetched_summary_rows = await hooks["get_broad_summary_context_rows"](
            product_id=int(product_row.get("productId") or 0),
            query_text=user_prompt,
            latest_episode_no=effective_latest_episode_no,
            resolved_mode=resolved_mode,
            qa_subtype=qa_subtype,
            qa_corrections=qa_corrections,
            db=db,
        )
        if resolved_mode == "general":
            current_scope_rows = list((scope_context or {}).get("plot_rows") or [])
            if current_scope_rows:
                prefetched_summary_rows = _merge_websochat_priority_summary_rows(
                    current_scope_rows[:1],
                    prefetched_summary_rows,
                    limit=5,
                )
                logger.info(
                    "websochat qa_current_scope_priority applied=true scope_ranges=%s merged_ranges=%s prompt_preview=%r",
                    [
                        (
                            int(row.get("episode_from") or row.get("episodeFrom") or 0),
                            int(row.get("episode_to") or row.get("episodeTo") or 0),
                        )
                        for row in current_scope_rows[:1]
                    ],
                    [
                        (
                            int(row.get("episodeFrom") or row.get("episode_from") or 0),
                            int(row.get("episodeTo") or row.get("episode_to") or 0),
                        )
                        for row in prefetched_summary_rows[:5]
                    ],
                    " ".join(str(user_prompt or "").split())[:120],
                )
        summary_context_message = hooks["build_summary_context_message"](prefetched_summary_rows, qa_subtype=qa_subtype)
        if summary_context_message:
            messages.append({"role": "user", "content": summary_context_message})

    reference_resolution = await hooks["resolve_reference"](
        product_row=product_row,
        user_prompt=user_prompt,
        recent_messages=recent_messages,
        summary_rows=prefetched_summary_rows,
    )
    if hooks["is_ambiguous_reference_query"](user_prompt):
        reference_message = hooks["build_reference_resolution_message"](reference_resolution or {})
        if reference_message:
            messages.append({"role": "user", "content": reference_message})
    retrieval_bundle = await _load_websochat_escalated_evidence(
        product_id=int(product_row.get("productId") or 0),
        latest_episode_no=effective_latest_episode_no,
        user_prompt=user_prompt,
        qa_subtype=qa_subtype,
        resolved_mode=resolved_mode,
        resolved_episode_no=resolved_episode_no,
        summary_rows=prefetched_summary_rows,
        scope_context=scope_context,
        hooks=hooks,
        db=db,
    )
    retrieval_context_message = _build_websochat_retrieval_context_message(
        qa_subtype=qa_subtype,
        episode_rows=list(retrieval_bundle.get("episode_rows") or []),
        search_rows=list(retrieval_bundle.get("search_rows") or []),
    )
    fallback_episode_rows: list[dict[str, Any]] = []
    if not retrieval_context_message and not resolved_episode_no:
        target_episode_nos: list[int] = []
        for episode_no in (effective_latest_episode_no, max(1, effective_latest_episode_no - 1)):
            safe_episode_no = int(episode_no or 0)
            if safe_episode_no > 0 and safe_episode_no not in target_episode_nos:
                target_episode_nos.append(safe_episode_no)
        for row in prefetched_summary_rows[:WEBSOCHAT_RETRIEVAL_EPISODE_LIMIT]:
            episode_no = int(row.get("episodeTo") or row.get("episodeFrom") or row.get("episode_to") or row.get("episode_from") or 0)
            if episode_no > 0 and episode_no not in target_episode_nos:
                target_episode_nos.append(episode_no)
        for episode_no in target_episode_nos[:WEBSOCHAT_RETRIEVAL_EPISODE_LIMIT]:
            fallback_episode_rows.extend(
                await hooks["get_episode_contents"](
                    product_id=int(product_row.get("productId") or 0),
                    episode_from=episode_no,
                    episode_to=episode_no,
                    latest_episode_no=effective_latest_episode_no,
                    db=db,
                )
            )
        if fallback_episode_rows:
            logger.info(
                "websochat qa_episode_prefetch_fallback applied=true episodes=%s prompt_preview=%r",
                sorted({int(row.get('episodeNo') or 0) for row in fallback_episode_rows if int(row.get('episodeNo') or 0) > 0}),
                " ".join(str(user_prompt or "").split())[:120],
            )
            retrieval_context_message = _build_websochat_retrieval_context_message(
                qa_subtype=qa_subtype,
                episode_rows=fallback_episode_rows,
                search_rows=[],
            )
    referenced_episode_nos = _collect_websochat_evidence_episode_nos(
        summary_rows=prefetched_summary_rows,
        episode_rows=list(retrieval_bundle.get("episode_rows") or []) or fallback_episode_rows,
        search_rows=list(retrieval_bundle.get("search_rows") or []),
        scope_context=scope_context,
        latest_episode_no=effective_latest_episode_no,
    )
    if retrieval_context_message:
        messages.append({"role": "user", "content": retrieval_context_message})
    entity_grounding_rows = list(retrieval_bundle.get("episode_rows") or []) or fallback_episode_rows
    if _has_websochat_entity_grounding_evidence(
        user_prompt=user_prompt,
        scope_context=scope_context,
        episode_rows=entity_grounding_rows,
        search_rows=list(retrieval_bundle.get("search_rows") or []),
    ):
        logger.info(
            "websochat qa_entity_grounding_hint applied=true qa_subtype=%s prompt_preview=%r",
            qa_subtype,
            " ".join(str(user_prompt or "").split())[:120],
        )
        messages.append(
            {
                "role": "user",
                "content": _build_websochat_entity_grounding_retry_message(user_prompt),
            }
        )
        snippet_message = _build_websochat_entity_grounding_snippet_message(
            user_prompt=user_prompt,
            episode_rows=entity_grounding_rows,
            search_rows=list(retrieval_bundle.get("search_rows") or []),
        )
        if snippet_message:
            messages.append({"role": "user", "content": snippet_message})
    messages.append({"role": "user", "content": user_prompt})
    if is_predict_query:
        system_prompt += (
            " 이번 질문은 다음 전개 예상이다. 읽은 범위 안 최신 갈등, 관계 변화, 떡밥을 우선 근거로 삼아라."
            " 답은 먼저 가장 가능성 높게 보는 흐름을 한 줄로 베팅하고, 이어서 가능성 있는 가설을 2~3개로 나눠 풀어라."
            " 각 가설에는 왜 그렇게 보는지 근거가 되는 공개 회차, 장면, 감정선, 미해결 변수를 자연스럽게 붙여라."
            " 스포일러처럼 확정하지는 말되, 지나치게 소심하게 흐리지 말고 흥미롭게 풀어라."
            " 마지막에는 이야기를 더 궁금하게 만드는 변수나 갈림길을 한 가지 남겨라."
        )
    if is_next_episode_write_query:
        next_episode_no = effective_latest_episode_no + 1
        system_prompt += (
            " 이번 질문은 다음 회차 창작이다. 읽은 범위 안 공개된 사건, 관계, 감정선, 떡밥만 재료로 써라."
            " 출력은 제목 한 줄 다음에 바로 본문만 써라. 목록, 불릿, 번호 매기기, 메타 설명은 금지다."
            f" 제목 첫 줄의 회차 번호는 반드시 {next_episode_no}화로 시작하라. 이 숫자는 절대 바꾸지 마라."
            " 최근 회차 제목 패턴은 숫자가 아니라 제목 결만 참고하고, 제목 앞 번호 표기를 베끼지 마라."
            " 본문은 실제 다음 화처럼 장면과 대사 중심으로 이어가라."
            " 공식 연재를 아는 척하거나 비공개 정보를 끌어오지 말고, 읽은 범위에서 자연스럽게 이어질 법한 가상 다음화로 써라."
            " 길이는 6000자 이내로 유지하되, 본문은 가능하면 4800자 이상 5200자 이하를 목표로 해서 너무 짧게 끝내지 말고 읽는 맛이 있게 써라."
            " 장면은 최소 3개 이상 전개하고, 중간에 바로 끝내지 말고 갈등과 감정의 파동을 충분히 쌓아라."
        )
    else:
        system_prompt += (
            " 작품 고유명사(인물명, 세력명, 사건명, 능력명)를 가능하면 2개 이상 자연스럽게 포함하고, 장르 일반론으로만 때우지 마라."
            + _build_websochat_direct_evidence_instruction()
            + _build_websochat_qa_subtype_instruction(qa_subtype)
        )

    retried_for_length = False
    retried_for_empty = False
    entity_grounding_retry_count = 0
    for _ in range(max_tool_rounds):
        if is_next_episode_write_query:
            await db.rollback()
        response = await _call_claude_messages(
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            max_tokens=WEBSOCHAT_NEXT_EPISODE_WRITE_MAX_TOKENS if is_next_episode_write_query else WEBSOCHAT_REPLY_MAX_TOKENS,
        )
        content = response.get("content") or []
        text_reply = _extract_text(content)
        tool_uses = _extract_tool_use_blocks(content)
        if not tool_uses:
            stripped_reply = text_reply.strip()
            if (
                is_next_episode_write_query
                and not retried_for_length
                and len(stripped_reply) < WEBSOCHAT_NEXT_EPISODE_WRITE_MIN_CHARS
            ):
                retried_for_length = True
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "방금 초안은 너무 짧았다. 제목 한 줄과 본문 형식은 유지하되, 이번에는 4800자 이상 5200자 이하를 목표로 "
                            "장면을 더 충분히 전개해서 처음부터 다시 써라. 요약하지 말고 갈등, 대사, 감정 변화를 더 쌓아라."
                        ),
                    }
                )
                continue
            if (
                qa_subtype in {"world_setting", "can_it_work_logic"}
                and stripped_reply
                and (prefetched_summary_rows or has_scope_context or retrieval_context_message)
                and clarify_retry_count < WEBSOCHAT_CLARIFY_RETRY_LIMIT
                and _looks_like_websochat_clarifying_reply(stripped_reply, qa_subtype=qa_subtype)
            ):
                clarify_retry_count += 1
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": _build_websochat_clarify_retry_message(qa_subtype),
                    }
                )
                continue
            if (
                stripped_reply
                and not is_predict_query
                and not is_next_episode_write_query
                and entity_grounding_retry_count < WEBSOCHAT_ENTITY_GROUNDING_RETRY_LIMIT
                and _should_retry_websochat_entity_grounding(
                    reply=stripped_reply,
                    user_prompt=user_prompt,
                    scope_context=scope_context,
                    episode_rows=list(retrieval_bundle.get("episode_rows") or []) or fallback_episode_rows,
                    search_rows=list(retrieval_bundle.get("search_rows") or []),
                )
            ):
                entity_grounding_retry_count += 1
                logger.info(
                    "websochat qa_entity_grounding_retry applied=true retry_count=%s qa_subtype=%s prompt_preview=%r",
                    entity_grounding_retry_count,
                    qa_subtype,
                    " ".join(str(user_prompt or "").split())[:120],
                )
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": _build_websochat_entity_grounding_retry_message(user_prompt),
                    }
                )
                continue
            if qa_subtype == "can_it_work_logic" and (
                _looks_like_websochat_clarifying_reply(stripped_reply, qa_subtype=qa_subtype)
                or _looks_like_websochat_logic_deferral_reply(stripped_reply)
            ):
                fallback_reply = _build_websochat_can_it_work_logic_fallback(
                    summary_rows=prefetched_summary_rows,
                    scope_context=scope_context,
                )
                if fallback_reply:
                    return fallback_reply, referenced_episode_nos
            if stripped_reply:
                return _finalize_websochat_answer(stripped_reply, qa_subtype=qa_subtype), referenced_episode_nos
            has_scope_context = bool(
                scope_context
                and (
                    scope_context.get("plot_rows")
                    or scope_context.get("characters")
                    or scope_context.get("relations")
                    or scope_context.get("hooks")
                )
            )
            if (prefetched_summary_rows or has_scope_context) and not retried_for_empty and not is_next_episode_write_query:
                retried_for_empty = True
                messages.append({"role": "assistant", "content": content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "이미 공개 컨텍스트가 충분하다. 되묻지 말고 바로 답해라. "
                            "작품 고유명사를 2개 이상 넣고, 공개 범위에서 근거가 되는 축을 1개 이상 자연스럽게 붙여라."
                        ),
                    }
                )
                continue
            return _build_websochat_qa_fallback_reply(qa_subtype), referenced_episode_nos

        messages.append({"role": "assistant", "content": content})
        tool_results: list[dict[str, Any]] = []
        for block in tool_uses:
            tool_name = str(block.get("name") or "")
            tool_input = block.get("input") or {}
            try:
                tool_result = await hooks["dispatch_tool"](
                    tool_name=tool_name,
                    tool_input=tool_input if isinstance(tool_input, dict) else {},
                    product_id=int(product_row.get("productId") or 0),
                    product_row=product_row,
                    db=db,
                )
            except Exception as exc:
                tool_result = {"error": str(exc)}
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.get("id"),
                    "content": json.dumps(_to_json_safe(tool_result), ensure_ascii=False),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    return _build_websochat_qa_fallback_reply(qa_subtype), referenced_episode_nos


async def execute_websochat_qa(
    *,
    product_row: dict[str, Any],
    user_prompt: str,
    qa_plan: WebsochatResponsePlan,
    evidence_bundle: WebsochatEvidenceBundle,
    recent_messages: list[dict[str, str]],
    qa_recent_notes: list[str],
    qa_corrections: list[dict[str, str]],
    current_qa_corrections: list[dict[str, str]],
    db: AsyncSession,
    hooks: WebsochatQaExecutionHooks,
    max_tool_rounds: int,
    gemini_context_episode_limit: int,
    prefetch_context_chars: int,
    tools: list[dict[str, Any]],
) -> WebsochatQaExecutionResult:
    fallback_used = False
    skip_tools = _should_websochat_skip_tools(
        user_prompt=user_prompt,
        qa_plan=qa_plan,
    )
    if skip_tools:
        logger.info(
            "websochat qa_tool_policy skip_tools=true intent=%s route_mode=%s prompt_preview=%r",
            qa_plan["intent"],
            qa_plan["route_mode"],
            " ".join(str(user_prompt or "").split())[:80],
        )
    if qa_plan["preferred_model"] == "gemini":
        try:
            reply, referenced_episode_nos = await _generate_websochat_reply_with_gemini(
                product_row=product_row,
                user_prompt=user_prompt,
                resolved_mode=qa_plan["route_mode"],
                evidence_bundle=evidence_bundle,
                recent_messages=recent_messages,
                qa_plan=qa_plan,
                qa_recent_notes=qa_recent_notes,
                qa_corrections=qa_corrections,
                current_qa_corrections=current_qa_corrections,
                db=db,
                hooks=hooks,
                gemini_context_episode_limit=gemini_context_episode_limit,
                prefetch_context_chars=prefetch_context_chars,
            )
            return {
                "reply": reply,
                "model_used": "gemini",
                "fallback_used": False,
                "route_mode": qa_plan["route_mode"],
                "intent": qa_plan["intent"],
                "referenced_episode_nos": referenced_episode_nos,
            }
        except Exception:
            fallback_used = True

    reply, referenced_episode_nos = await _generate_websochat_reply_with_claude(
        product_row=product_row,
        user_prompt=user_prompt,
        resolved_mode=qa_plan["route_mode"],
        evidence_bundle=evidence_bundle,
        recent_messages=recent_messages,
        qa_plan=qa_plan,
        qa_recent_notes=qa_recent_notes,
        qa_corrections=qa_corrections,
        current_qa_corrections=current_qa_corrections,
        db=db,
        hooks=hooks,
        max_tool_rounds=1 if skip_tools else max_tool_rounds,
        tools=[] if skip_tools else tools,
        prefetch_context_chars=prefetch_context_chars,
    )
    return {
        "reply": reply,
        "model_used": "haiku",
        "fallback_used": fallback_used,
        "route_mode": qa_plan["route_mode"],
        "intent": qa_plan["intent"],
        "referenced_episode_nos": referenced_episode_nos,
    }
