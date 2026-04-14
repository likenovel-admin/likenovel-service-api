from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Any

from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.const import ErrorMessages, settings
from app.exceptions import CustomResponseException
from app.rdb import likenovel_db_engine
from app.schemas.websochat import (
    PostWebsochatMessageReqBody,
    PostWebsochatSessionReqBody,
    PatchWebsochatSessionModeReqBody,
    PatchWebsochatSessionReadScopeReqBody,
    PatchWebsochatSessionReqBody,
)
from app.services.websochat.websochat_compare import (
    _build_websochat_pair_key,
    _build_websochat_worldcup_round,
    _extract_websochat_direct_match_scope_keys,
    _filter_websochat_worldcup_candidates_by_read_scope,
    _infer_websochat_game_category_from_prompt,
    _pick_websochat_unused_pair,
    _resolve_websochat_pair_choice,
    _resolve_websochat_worldcup_bracket_size,
)
from app.services.websochat.websochat_compare_runtime import (
    get_websochat_game_candidate_profiles,
    select_websochat_game_candidates,
)
from app.services.websochat.websochat_concierge import (
    build_websochat_concierge_payload,
)
from app.services.websochat.websochat_context_assembler import assemble_websochat_scope_context
from app.services.websochat.websochat_contracts import (
    WebsochatCtaCard,
    WebsochatEvidenceBundle,
    WebsochatPromptReadScopeDecision,
    WebsochatQaExecutionResult,
    WebsochatReasonCard,
    WebsochatScopeState,
    WebsochatStarterAction,
)
from app.services.websochat.websochat_game_adapter import (
    apply_websochat_implicit_game_inputs,
    build_websochat_game_dispatch_plan,
    has_websochat_worldcup_followup_signal,
    resolve_websochat_worldcup_followup,
)
from app.services.websochat.websochat_game_memory import (
    WEBSOCHAT_ALLOWED_GAME_CATEGORIES,
    WEBSOCHAT_ALLOWED_GAME_GENDER_SCOPES,
    WEBSOCHAT_ALLOWED_GAME_MODES,
    WEBSOCHAT_ALLOWED_READ_SCOPE_STATES,
    WEBSOCHAT_ALLOWED_RP_MODES,
    WEBSOCHAT_ALLOWED_RP_STAGES,
    WEBSOCHAT_ALLOWED_VS_GAME_MATCH_MODES,
    WEBSOCHAT_PENDING_GAME_CATEGORY,
    WEBSOCHAT_RP_RECENT_FACT_LIMIT,
    _build_websochat_game_context,
    _clear_websochat_game_context,
    _clear_websochat_rp_context,
    _merge_websochat_qa_corrections,
    _merge_websochat_session_memory,
    _normalize_websochat_qa_corrections,
    _normalize_websochat_game_state,
    _normalize_websochat_games_memory,
    _normalize_websochat_session_memory,
    _normalize_websochat_string_list,
    _resolve_websochat_active_character_label,
    _resolve_websochat_rp_stage,
    _serialize_websochat_session_memory,
    _update_websochat_session_memory_after_reply,
)
from app.services.websochat.websochat_planner import (
    _build_websochat_qa_plan,
    _build_websochat_rp_plan,
    _resolve_websochat_response_route,
)
from app.services.websochat.websochat_qa_executor import (
    _is_websochat_next_episode_write_query,
    WebsochatQaExecutionHooks,
    execute_websochat_qa,
    resolve_websochat_qa_subtype,
)
from app.services.websochat.websochat_qa_renderer import build_websochat_recent_context_message
from app.services.websochat.websochat_rp_renderer import (
    generate_websochat_rp_reply_with_claude,
    generate_websochat_rp_reply_with_gemini,
)
from app.services.websochat.websochat_renderers import generate_websochat_vs_comparison
from app.services.websochat.websochat_renderers import (
    build_websochat_game_guide_reply,
    build_websochat_vs_disabled_reply,
)
from app.services.websochat.websochat_scope_resolver import (
    WEBSOCHAT_EXACT_EPISODE_RE,
    WEBSOCHAT_KOREAN_ORDINAL_MAP,
    WEBSOCHAT_ORDINAL_EPISODE_RE,
    _infer_websochat_read_episode_to_from_prompt,
    _is_websochat_unread_scope_prompt,
    _resolve_websochat_prompt_read_scope_decision,
    _resolve_websochat_scope_read_episode_to,
)
from app.services.websochat.websochat_stream import emit_websochat_stream_text_if_needed
from app.services.websochat.websochat_utils import _extract_websochat_json_object
from app.services.ai.ai_chat_service import _call_claude_messages, _extract_text, _extract_tool_use_blocks, _to_json_safe
from app.services.common.comm_service import get_user_from_kc
from app.utils.common import handle_exceptions
from app.utils.query import get_file_path_sub_query
from app.utils.time import get_full_age

WEBSOCHAT_DEFAULT_TITLE = "새 대화"
WEBSOCHAT_SESSION_LOCK_TIMEOUT_SECONDS = 0
WEBSOCHAT_SESSION_TTL_DAYS = 30
WEBSOCHAT_DAILY_FREE_MESSAGE_LIMIT = 2
WEBSOCHAT_NONCANONICAL_NEXT_EPISODE_MARKER = "[[websochat:noncanonical:next_episode_write]]\n"
WEBSOCHAT_MESSAGE_CASH_COST = 20
WEBSOCHAT_NEXT_EPISODE_WRITE_CASH_COST = 30


def _resolve_websochat_message_cash_cost(
    qa_action_key: str | None,
) -> int:
    if str(qa_action_key or "").strip().lower() == "next_episode_write":
        return WEBSOCHAT_NEXT_EPISODE_WRITE_CASH_COST
    return WEBSOCHAT_MESSAGE_CASH_COST


def _build_websochat_billing_status_payload(
    *,
    used_count: int,
    user_id: int | None,
    cash_balance: int | None,
    qa_action_key: str | None = None,
) -> dict[str, Any]:
    free_remaining = max(WEBSOCHAT_DAILY_FREE_MESSAGE_LIMIT - int(used_count), 0)
    requires_cash = free_remaining <= 0
    cash_cost = _resolve_websochat_message_cash_cost(qa_action_key)
    return {
        "freeRemainingMessages": free_remaining,
        "dailyFreeMessageLimit": WEBSOCHAT_DAILY_FREE_MESSAGE_LIMIT,
        "cashCostPerMessage": cash_cost,
        "requiresCashForNextMessage": requires_cash,
        "requiresLoginForNextMessage": bool(requires_cash and user_id is None),
        "cashBalance": int(cash_balance or 0) if user_id is not None else None,
    }


WEBSOCHAT_PRODUCT_UNAVAILABLE_MESSAGE = "비공개된 작품과는 더이상 이야기하실 수 없습니다."
WEBSOCHAT_CONTEXT_PENDING_MESSAGE = "이 작품은 아직 대화 준비 중입니다."
WEBSOCHAT_PLACEHOLDER_TEMPLATE = (
    "[{title}] 기준으로 관련 회차와 원문 일부를 먼저 찾았습니다.\n"
    "{context_block}\n\n"
    "질문: {user_prompt}\n"
    "다음 단계에서 이 컨텍스트를 바탕으로 실제 T2T/T2I 응답을 붙입니다."
)
WEBSOCHAT_MAX_TOOL_ROUNDS = 4
WEBSOCHAT_MAX_HISTORY_MESSAGES = 40
WEBSOCHAT_MAX_EPISODE_CONTENT_CHARS = 6000
WEBSOCHAT_PREFETCH_CONTEXT_CHARS = 3000
WEBSOCHAT_BROAD_SUMMARY_CONTEXT_LIMIT = 6
WEBSOCHAT_GEMINI_CONTEXT_EPISODE_LIMIT = 2
WEBSOCHAT_REFERENCE_RESOLUTION_MAX_TOKENS = 220
WEBSOCHAT_INTENT_MAX_TOKENS = 120
WEBSOCHAT_QA_CORRECTION_MAX_TOKENS = 180
WEBSOCHAT_RP_RECALL_DECISION_MAX_TOKENS = 120
WEBSOCHAT_RP_RECALL_CONTEXT_CHAR_LIMIT = 1800
WEBSOCHAT_ALLOWED_INTENTS = {
    "factual",
    "comparative",
    "playful",
    "self_insert",
    "simulation",
}
WEBSOCHAT_EPISODE_RANGE_RE = re.compile(r"(\d{1,4})\s*(?:~|-|–|—)\s*(\d{1,4})\s*화")
WEBSOCHAT_EPISODE_SINGLE_RE = re.compile(r"(\d{1,4})\s*화")
WEBSOCHAT_ALLOWED_SUMMARY_MODES = {"exact", "early", "latest", "general"}


def _resolve_websochat_synced_latest_episode_no(product_row: dict[str, Any] | None) -> int:
    if not product_row:
        return 0
    latest_episode_no = max(int(product_row.get("latestEpisodeNo") or 0), 0)
    synced_latest_episode_no = max(int(product_row.get("syncedLatestEpisodeNo") or 0), 0)
    if latest_episode_no <= 0:
        return 0
    return min(synced_latest_episode_no, latest_episode_no)


def _build_websochat_next_episode_write_pending_message(
    synced_latest_episode_no: int | None,
) -> str:
    resolved_synced_latest_episode_no = max(int(synced_latest_episode_no or 0), 0)
    if resolved_synced_latest_episode_no > 0:
        return (
            "최신 공개 회차 준비가 끝나면 다음회차 생성도 다시 열릴게. "
            f"지금은 {resolved_synced_latest_episode_no}화까지 기준 대화만 가능해."
        )
    return "최신 공개 회차 준비가 끝나면 다음회차 생성도 다시 열릴게. 지금은 대화만 가능해."


def _build_websochat_sync_pending_read_scope_message(
    requested_read_episode_to: int | None,
    synced_latest_episode_no: int | None,
) -> str:
    resolved_requested_read_episode_to = max(int(requested_read_episode_to or 0), 0)
    resolved_synced_latest_episode_no = max(int(synced_latest_episode_no or 0), 0)
    if resolved_requested_read_episode_to > 0 and resolved_synced_latest_episode_no > 0:
        return (
            f"{resolved_requested_read_episode_to}화는 아직 준비 중이라 "
            f"{resolved_synced_latest_episode_no}화까지 내용을 토대로 이야기할게."
        )
    if resolved_synced_latest_episode_no > 0:
        return (
            "최신 공개 회차는 아직 준비 중이라 "
            f"{resolved_synced_latest_episode_no}화까지 내용을 토대로 이야기할게."
        )
    return "최신 공개 회차는 아직 준비 중이라 준비된 범위 안에서만 이야기할게."
WEBSOCHAT_TOOLS = [
    {
        "name": "get_product_context",
        "description": "현재 작품의 제목, 작가, 최신 공개 회차만 조회한다. 총 화수 계획이나 비공개 정보는 제공하지 않는다.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_episode_summaries",
        "description": "질문과 관련된 회차 요약을 찾는다. mode는 exact, early, latest, general 중 하나다. '1화', '12화'처럼 정확한 회차면 exact와 episode_no를 쓰고, '초반', '처음', '첫 등장', '첫 발현' 같은 질문이면 early, '최신', '최근', '지금' 같은 질문이면 latest를 우선 사용한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["exact", "early", "latest", "general"],
                },
                "episode_no": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_episode_contents",
        "description": "원문 청크에서 질문과 관련된 부분을 직접 찾는다. 사실 확인이 필요하면 사용한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_episode_contents",
        "description": "특정 회차 범위의 원문을 직접 가져온다. episode_from과 episode_to는 최신 공개 회차 범위 안에서만 사용한다. 주인공 소개, 인물 역할극, 초반 사건 질문이면 1~3화 같은 초반 회차를 먼저 보고, 최신 갈등/변화 질문이면 최신 공개 회차 근처를 먼저 조회하라.",
        "input_schema": {
            "type": "object",
            "properties": {
                "episode_from": {"type": "integer"},
                "episode_to": {"type": "integer"},
            },
            "required": ["episode_from", "episode_to"],
        },
    },
]
WEBSOCHAT_KEYWORD_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
WEBSOCHAT_KEYWORD_STOPWORDS = {
    "그리고", "하지만", "그러나", "이번", "저번", "그녀", "그는", "그것", "이것", "저것",
    "에게", "에서", "한다", "했다", "했다는", "있다", "있는", "없다", "없고", "정도", "처럼",
    "위해", "통해", "이후", "이전", "장면", "회차", "작품", "내용", "상태", "주인공", "분석",
    "누가", "누구", "뭐", "무엇", "무슨", "왜", "어떻게", "언제", "어디서",
}
WEBSOCHAT_EARLY_QUESTION_KEYWORDS = (
    "초반", "처음", "첫 ", "첫등장", "첫 등장", "첫발현", "첫 발현", "첫 각성", "처음 각성",
)
WEBSOCHAT_BROAD_QUESTION_KEYWORDS = (
    "최신", "현재", "지금", "최근", "갈등", "관계", "떡밥", "미해결", "변화",
)
WEBSOCHAT_AMBIGUOUS_REFERENCE_PATTERNS = (
    "저 선택",
    "그 선택",
    "이 선택",
    "저 장면",
    "그 장면",
    "이 장면",
    "그때",
    "그거",
    "저거",
    "이거",
)
logger = logging.getLogger(__name__)
WEBSOCHAT_QA_EPISODE_REF_MEMORY_KEY = "_qa_referenced_episode_nos"


def _is_websochat_noncanonical_action(qa_action_key: str | None) -> bool:
    return str(qa_action_key or "").strip().lower() == "next_episode_write"


def _mark_websochat_noncanonical_message(content: str, *, qa_action_key: str | None) -> str:
    normalized = str(content or "")
    if not normalized.strip():
        return normalized
    if not _is_websochat_noncanonical_action(qa_action_key):
        return normalized
    if normalized.startswith(WEBSOCHAT_NONCANONICAL_NEXT_EPISODE_MARKER):
        return normalized
    return f"{WEBSOCHAT_NONCANONICAL_NEXT_EPISODE_MARKER}{normalized}"


def _is_websochat_noncanonical_message(content: str) -> bool:
    return str(content or "").startswith(WEBSOCHAT_NONCANONICAL_NEXT_EPISODE_MARKER)


def _strip_websochat_noncanonical_message_marker(content: str) -> str:
    normalized = str(content or "")
    if not normalized.startswith(WEBSOCHAT_NONCANONICAL_NEXT_EPISODE_MARKER):
        return normalized
    return normalized[len(WEBSOCHAT_NONCANONICAL_NEXT_EPISODE_MARKER):]

_STORY_AGENT_SUMMARY_OVERRIDE_CACHE: dict[str, Any] = {
    "path": None,
    "mtime": None,
    "rows": None,
}


def _resolve_websochat_read_scope_state(
    session_memory: dict[str, Any],
) -> WebsochatScopeState:
    normalized_state = str(session_memory.get("read_scope_state") or "").strip().lower()
    if normalized_state in WEBSOCHAT_ALLOWED_READ_SCOPE_STATES:
        return normalized_state  # type: ignore[return-value]
    if int(session_memory.get("read_episode_to") or 0) > 0:
        return "known"
    return "unknown"


def _apply_websochat_account_read_scope(
    session_memory: dict[str, Any],
    account_read_episode_to: int | None,
) -> dict[str, Any]:
    normalized = _normalize_websochat_session_memory(session_memory)
    resolved_account_read_episode_to = max(int(account_read_episode_to or 0), 0) or None
    if not resolved_account_read_episode_to:
        return normalized
    if str(normalized.get("read_scope_source") or "").strip().lower() == "prompt":
        return normalized
    normalized["read_episode_to"] = resolved_account_read_episode_to
    normalized["read_scope_state"] = "known"
    normalized["read_scope_source"] = "account"
    return normalized


def _build_websochat_cta_cards(
    cta_cards: list[WebsochatCtaCard] | None,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for card in cta_cards or []:
        card_type = str(card.get("type") or "").strip()
        label = str(card.get("label") or "").strip()
        product_id = int(card.get("product_id") or 0)
        if not card_type or not label or product_id <= 0:
            continue
        cards.append(
            {
                "type": card_type,
                "label": label,
                "productId": product_id,
            }
        )
    return cards


def _attach_websochat_concierge_cards(
    message: dict[str, Any],
    concierge_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if message.get("role") != "assistant" or not concierge_payload:
        return message
    return {
        **message,
        "reasonCards": list(concierge_payload.get("reasonCards") or []),
        "actionCards": list(concierge_payload.get("actions") or []),
        "ctaCards": _build_websochat_cta_cards(concierge_payload.get("ctaCards") or []),
    }


def _attach_websochat_concierge_to_last_assistant_message(
    messages: list[dict[str, Any]],
    concierge_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not concierge_payload:
        return messages
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") != "assistant":
            continue
        enriched = list(messages)
        enriched[index] = _attach_websochat_concierge_cards(enriched[index], concierge_payload)
        return enriched
    return messages


def _build_websochat_starter(
    *,
    product_title: str,
    scope_state: WebsochatScopeState,
    read_episode_to: int | None,
    read_episode_title: str | None,
    latest_episode_no: int,
    synced_latest_episode_no: int,
    can_send_message: bool,
    concierge_payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not can_send_message:
        return None

    normalized_title = str(product_title or "").strip() or "이 작품"
    resolved_read_episode_to = max(min(int(read_episode_to or 0), max(latest_episode_no, 0)), 0) or None
    prompt_prefix = f"{resolved_read_episode_to}화까지 기준으로 " if resolved_read_episode_to else ""
    default_actions: list[WebsochatStarterAction] = [
        {
            "label": "작품 대화",
            "prompt": f"{prompt_prefix}이 작품에 대해 뭐든 편하게 이야기해줘",
            "modeKey": "qa",
            "qaActionKey": None,
            "cashCost": None,
        },
        {
            "label": "다음 전개 예상",
            "prompt": f"{prompt_prefix}다음 전개 예상해줘",
            "modeKey": "qa",
            "qaActionKey": "predict",
            "cashCost": None,
        },
        {
            "label": "다음회차 생성",
            "prompt": f"{prompt_prefix}다음회차 써줘",
            "modeKey": "qa",
            "qaActionKey": "next_episode_write",
            "cashCost": WEBSOCHAT_NEXT_EPISODE_WRITE_CASH_COST,
        },
        {
            "label": "인물과 대화",
            "prompt": f"{prompt_prefix}누구랑 대화하고 싶어? 인물 이름만 말해주면 바로 그 인물과 대화를 시작할게.",
            "modeKey": "rp",
            "qaActionKey": None,
            "cashCost": None,
        },
        {
            "label": "이상형월드컵",
            "prompt": f"{prompt_prefix}이 작품으로 이상형월드컵을 시작해줘",
            "modeKey": "ideal_worldcup",
            "qaActionKey": None,
            "cashCost": None,
        },
    ]
    starter_actions = (
        list(concierge_payload.get("actions") or [])
        if scope_state == "none" and concierge_payload
        else default_actions
    )

    return {
        "productTitle": normalized_title,
        "scopeState": scope_state,
        "readEpisodeNo": resolved_read_episode_to,
        "readEpisodeTitle": str(read_episode_title or "").strip() or None,
        "latestEpisodeNo": max(latest_episode_no, 0),
        "publishedLatestEpisodeNo": max(latest_episode_no, 0),
        "syncedLatestEpisodeNo": max(min(int(synced_latest_episode_no or 0), max(latest_episode_no, 0)), 0),
        "reasonCards": list(concierge_payload.get("reasonCards") or []) if concierge_payload else [],
        "ctaCards": _build_websochat_cta_cards(concierge_payload.get("ctaCards") or []) if concierge_payload else [],
        "actions": starter_actions,
    }


def _build_websochat_read_scope_required_reply() -> str:
    return (
        "아직 어디까지 읽었는지 모르겠어요.\n"
        "스포일러 안 섞이게 맞춰서 이야기하려면, 어디까지 읽었는지만 먼저 알려주세요.\n"
        "예: 프롤로그까지 읽었어 / 습격까지 읽었어 / 아직 시작 안 했어"
    )


def _build_websochat_qa_mode_entry_reply(
    *,
    product_row: dict[str, Any],
    read_scope_label: str | None = None,
) -> str:
    title = str(product_row.get("title") or "이 작품").strip() or "이 작품"
    if read_scope_label:
        return (
            f"{read_scope_label} 기준으로 {title} 작품대화를 이어갈 수 있어. "
            "캐릭터, 장면, 관계, 설정 중에서 편하게 말해줘."
        )
    return (
        f"{title} 작품대화를 이어갈 수 있어. "
        "캐릭터, 장면, 관계, 설정 중에서 편하게 말해줘."
    )


def _build_websochat_rp_mode_entry_reply(
    *,
    read_scope_label: str | None = None,
) -> str:
    if read_scope_label:
        return (
            f"{read_scope_label} 기준으로 맞춰둘게요. "
            "누구랑 대화하고 싶어? 인물 이름만 말해주면 바로 그 인물과 대화를 시작할게."
        )
    return "누구랑 대화하고 싶어? 인물 이름만 말해주면 바로 그 인물과 대화를 시작할게."


def _build_websochat_rp_character_selection_guide_reply() -> str:
    return "누구랑 대화하고 싶어? 인물 이름만 말해주면 바로 그 인물과 대화를 시작할게."


async def _insert_websochat_assistant_message(
    *,
    session_id: int,
    content: str,
    db: AsyncSession,
) -> None:
    normalized_content = str(content or "").strip()
    if not normalized_content:
        return
    await db.execute(
        text(
            """
            INSERT INTO tb_story_agent_message (
                session_id, role, client_message_id, content, created_id
            )
            VALUES (
                :session_id, 'assistant', NULL, :content, :created_id
            )
            """
        ),
        {
            "session_id": session_id,
            "content": normalized_content,
            "created_id": settings.DB_DML_DEFAULT_ID,
        },
    )


async def _build_websochat_read_scope_confirm_reply(
    *,
    product_id: int,
    read_episode_to: int | None,
    db: AsyncSession,
) -> str:
    read_scope_label = await _build_websochat_read_scope_label(
        product_id=product_id,
        read_episode_to=read_episode_to,
        db=db,
    )
    if not read_scope_label:
        return "좋아요. 읽은 범위를 먼저 잡아둘게요. 그 안에서만 편하게 이야기해볼게요."
    return (
        f"좋아요. 읽은 범위는 {read_scope_label}까지로 맞춰둘게요.\n"
        "이 범위 안에서만 편하게 이야기해볼게요."
    )


async def _resolve_actor(kc_user_id: str | None, guest_key: str | None, db: AsyncSession) -> tuple[int | None, str | None]:
    if kc_user_id:
        user_id = await get_user_from_kc(kc_user_id, db)
        if user_id != -1:
            return int(user_id), None
    normalized_guest_key = (guest_key or "").strip()
    if normalized_guest_key:
        return None, normalized_guest_key
    raise CustomResponseException(
        status_code=status.HTTP_400_BAD_REQUEST,
        message="비로그인 요청은 guest_key가 필요합니다.",
    )


async def _resolve_effective_adult_yn(
    kc_user_id: str | None,
    adult_yn: str,
    db: AsyncSession,
) -> str:
    requested_adult_yn = "Y" if (adult_yn or "").upper() == "Y" else "N"
    if requested_adult_yn != "Y" or not kc_user_id:
        return "N"

    query = text(
        """
        SELECT
            DATE_FORMAT(u.birthdate, '%Y-%m-%d') AS birthdate
        FROM tb_user u
        WHERE u.kc_user_id = :kc_user_id
          AND u.use_yn = 'Y'
        LIMIT 1
        """
    )
    result = await db.execute(query, {"kc_user_id": kc_user_id})
    user_row = result.mappings().one_or_none()
    if not user_row:
        return "N"

    birthdate = user_row.get("birthdate")
    if not birthdate:
        return "N"

    return "Y" if get_full_age(date=birthdate) >= 19 else "N"


async def _get_websochat_product(product_id: int, adult_yn: str, db: AsyncSession) -> dict[str, Any] | None:
    ratings_filter = "" if adult_yn == "Y" else "AND p.ratings_code = 'all'"
    query = text(
        f"""
        SELECT
            p.product_id AS productId,
            p.title,
            p.author_name AS authorNickname,
            p.story_agent_setting_text AS websochatSetting,
            {get_file_path_sub_query('p.thumbnail_file_id', 'coverImagePath')},
            p.status_code AS statusCode,
            COALESCE(sacp.context_status, 'pending') AS contextStatus,
            COALESCE(MAX(e.episode_no), 0) AS latestEpisodeNo,
            LEAST(COALESCE(sacp.ready_episode_count, 0), COALESCE(MAX(e.episode_no), 0)) AS syncedLatestEpisodeNo
        FROM tb_product p
        LEFT JOIN tb_story_agent_context_product sacp
          ON sacp.product_id = p.product_id
        LEFT JOIN tb_product_episode e
          ON e.product_id = p.product_id
         AND e.use_yn = 'Y'
         AND e.open_yn = 'Y'
        WHERE p.product_id = :product_id
          AND p.price_type = 'free'
          AND p.open_yn = 'Y'
          AND p.blind_yn = 'N'
          AND COALESCE(sacp.context_status, 'pending') = 'ready'
          {ratings_filter}
        GROUP BY p.product_id, p.title, p.author_name, p.story_agent_setting_text, p.thumbnail_file_id, p.status_code, sacp.context_status, sacp.ready_episode_count
        HAVING COALESCE(MAX(e.episode_no), 0) > 0
        """
    )
    result = await db.execute(query, {"product_id": product_id})
    row = result.mappings().one_or_none()
    if not row:
        return None
    product = dict(row)
    product["publishedLatestEpisodeNo"] = int(product.get("latestEpisodeNo") or 0)
    return product


async def _get_websochat_product_session_state(
    product_id: int,
    adult_yn: str,
    db: AsyncSession,
) -> dict[str, Any]:
    query = text(
        f"""
        SELECT
            p.product_id AS productId,
            p.title,
            p.author_name AS authorNickname,
            {get_file_path_sub_query('p.thumbnail_file_id', 'coverImagePath')},
            p.status_code AS statusCode,
            p.price_type AS priceType,
            p.open_yn AS openYn,
            p.blind_yn AS blindYn,
            p.ratings_code AS ratingsCode,
            COALESCE(sacp.context_status, 'pending') AS contextStatus,
            COALESCE(MAX(e.episode_no), 0) AS latestEpisodeNo,
            LEAST(COALESCE(sacp.ready_episode_count, 0), COALESCE(MAX(e.episode_no), 0)) AS syncedLatestEpisodeNo
        FROM tb_product p
        LEFT JOIN tb_story_agent_context_product sacp
          ON sacp.product_id = p.product_id
        LEFT JOIN tb_product_episode e
          ON e.product_id = p.product_id
         AND e.use_yn = 'Y'
         AND e.open_yn = 'Y'
        WHERE p.product_id = :product_id
        GROUP BY
            p.product_id,
            p.title,
            p.author_name,
            p.thumbnail_file_id,
            p.status_code,
            p.price_type,
            p.open_yn,
            p.blind_yn,
            p.ratings_code,
            sacp.context_status,
            sacp.ready_episode_count
        """
    )
    result = await db.execute(query, {"product_id": product_id})
    row = result.mappings().one_or_none()
    if not row:
        return {
            "productId": product_id,
            "title": None,
            "authorNickname": None,
            "latestEpisodeNo": 0,
            "publishedLatestEpisodeNo": 0,
            "syncedLatestEpisodeNo": 0,
            "canSendMessage": False,
            "unavailableMessage": WEBSOCHAT_PRODUCT_UNAVAILABLE_MESSAGE,
        }

    product = dict(row)
    can_send_message = (
        product.get("priceType") == "free"
        and product.get("openYn") == "Y"
        and product.get("blindYn") == "N"
        and product.get("contextStatus") == "ready"
        and int(product.get("latestEpisodeNo") or 0) > 0
        and (adult_yn == "Y" or product.get("ratingsCode") == "all")
    )
    unavailable_message = None
    if not can_send_message:
        if (
            product.get("priceType") != "free"
            or product.get("openYn") != "Y"
            or product.get("blindYn") != "N"
            or int(product.get("latestEpisodeNo") or 0) <= 0
        ):
            unavailable_message = WEBSOCHAT_PRODUCT_UNAVAILABLE_MESSAGE
        elif product.get("contextStatus") != "ready":
            unavailable_message = WEBSOCHAT_CONTEXT_PENDING_MESSAGE
        elif adult_yn != "Y" and product.get("ratingsCode") != "all":
            unavailable_message = WEBSOCHAT_PRODUCT_UNAVAILABLE_MESSAGE
        else:
            unavailable_message = WEBSOCHAT_PRODUCT_UNAVAILABLE_MESSAGE
    return {
        **product,
        "publishedLatestEpisodeNo": int(product.get("latestEpisodeNo") or 0),
        "canSendMessage": can_send_message,
        "unavailableMessage": unavailable_message,
    }


async def _get_websochat_latest_visible_episode_no(
    product_id: int,
    db: AsyncSession,
) -> int:
    result = await db.execute(
        text(
            """
            SELECT COALESCE(MAX(episode_no), 0) AS latestEpisodeNo
            FROM tb_product_episode
            WHERE product_id = :product_id
              AND use_yn = 'Y'
              AND open_yn = 'Y'
            """
        ),
        {"product_id": product_id},
    )
    row = result.mappings().one_or_none()
    return int((row or {}).get("latestEpisodeNo") or 0)


def _resolve_websochat_episode_ref_ceiling(
    latest_episode_no: int | None,
    synced_latest_episode_no: int | None,
    read_episode_to: int | None,
) -> int:
    latest_visible = max(0, int(latest_episode_no or 0))
    synced_latest = max(0, int(synced_latest_episode_no or 0))
    read_scope = max(0, int(read_episode_to or 0))
    upper_bound = min(latest_visible, synced_latest) if synced_latest > 0 else latest_visible
    if upper_bound <= 0:
        return 0
    if read_scope <= 0:
        return upper_bound
    return min(upper_bound, read_scope)


def _resolve_websochat_display_read_episode_to(
    *,
    scope_state: WebsochatScopeState | None = None,
    latest_episode_no: int | None,
    synced_latest_episode_no: int | None,
    requested_read_episode_to: int | None,
) -> int | None:
    normalized_scope_state = str(scope_state or "").strip().lower()
    if normalized_scope_state != "known":
        return None
    resolved = _resolve_websochat_episode_ref_ceiling(
        latest_episode_no,
        synced_latest_episode_no,
        requested_read_episode_to,
    )
    return resolved if resolved > 0 else None


async def _get_websochat_visible_episode_title(
    product_id: int,
    episode_no: int | None,
    db: AsyncSession,
) -> str | None:
    if not episode_no or episode_no <= 0:
        return None
    result = await db.execute(
        text(
            """
            SELECT COALESCE(episode_title, '') AS episodeTitle
            FROM tb_product_episode
            WHERE product_id = :product_id
              AND episode_no = :episode_no
              AND use_yn = 'Y'
              AND open_yn = 'Y'
            LIMIT 1
            """
        ),
        {"product_id": product_id, "episode_no": int(episode_no)},
    )
    row = result.mappings().one_or_none()
    title = str((row or {}).get("episodeTitle") or "").strip()
    return title or None


async def _build_websochat_read_scope_label(
    *,
    product_id: int,
    read_episode_to: int | None,
    db: AsyncSession,
) -> str | None:
    resolved_read_episode_to = max(int(read_episode_to or 0), 0)
    if resolved_read_episode_to <= 0:
        return None
    episode_title = await _get_websochat_visible_episode_title(
        product_id=product_id,
        episode_no=resolved_read_episode_to,
        db=db,
    )
    if episode_title:
        return f"{resolved_read_episode_to}화({episode_title})"
    return f"{resolved_read_episode_to}화"


def _normalize_websochat_scope_lookup_text(raw_text: str | None) -> str:
    normalized = re.sub(r"\s+", "", str(raw_text or "").strip().lower())
    return re.sub(r"[^0-9a-z가-힣]", "", normalized)


def _extract_websochat_episode_title_aliases(episode_title: str | None) -> list[str]:
    aliases: list[str] = []

    def append_alias(raw_value: str | None) -> None:
        normalized = _normalize_websochat_scope_lookup_text(raw_value)
        if len(normalized) < 2 or normalized in aliases:
            return
        aliases.append(normalized)

    normalized_title = str(episode_title or "").strip()
    if not normalized_title:
        return aliases

    append_alias(normalized_title)
    prefix_match = re.match(r"^(프롤로그|\d+\s*화)\s*[\.\-:：·\)\]]*\s*(.*)$", normalized_title, re.IGNORECASE)
    if prefix_match:
        append_alias(prefix_match.group(1))
        append_alias(prefix_match.group(2))

    return aliases


def _augment_websochat_episode_title_aliases(
    *,
    episode_no: int,
    episode_title: str | None,
) -> list[str]:
    aliases = _extract_websochat_episode_title_aliases(episode_title)
    if episode_no == 1:
        for alias in ("프롤로그", "prologue"):
            normalized = _normalize_websochat_scope_lookup_text(alias)
            if normalized and normalized not in aliases:
                aliases.append(normalized)
    return aliases


async def _resolve_websochat_prompt_episode_title_scope(
    *,
    product_id: int,
    latest_episode_no: int,
    user_prompt: str,
    db: AsyncSession,
) -> int | None:
    prompt_lookup = _normalize_websochat_scope_lookup_text(user_prompt)
    if not prompt_lookup or latest_episode_no <= 0:
        return None

    episode_rows = await _get_websochat_public_episode_refs(
        product_id=product_id,
        latest_episode_no=latest_episode_no,
        db=db,
    )
    matched_scores: list[tuple[int, int]] = []
    for row in episode_rows:
        episode_no = int(row.get("episodeNo") or 0)
        if episode_no <= 0:
            continue
        matched_length = max(
            (
                len(alias)
                for alias in _augment_websochat_episode_title_aliases(
                    episode_no=episode_no,
                    episode_title=row.get("episodeTitle"),
                )
                if alias in prompt_lookup
            ),
            default=0,
        )
        if matched_length > 0:
            matched_scores.append((episode_no, matched_length))

    if not matched_scores:
        return None

    best_length = max(score for _, score in matched_scores)
    best_episode_nos = sorted({episode_no for episode_no, score in matched_scores if score == best_length})
    if len(best_episode_nos) != 1:
        return None

    return best_episode_nos[0]


async def _resolve_websochat_prompt_read_episode_to(
    *,
    product_id: int,
    latest_episode_no: int,
    user_prompt: str,
    db: AsyncSession,
) -> int | None:
    if _is_websochat_unread_scope_prompt(user_prompt):
        return 0

    inferred_from_number = _infer_websochat_read_episode_to_from_prompt(
        user_prompt,
        latest_episode_no=latest_episode_no,
    )
    if inferred_from_number is not None:
        return inferred_from_number

    resolved_from_title = await _resolve_websochat_prompt_episode_title_scope(
        product_id=product_id,
        latest_episode_no=latest_episode_no,
        user_prompt=user_prompt,
        db=db,
    )
    if resolved_from_title is not None:
        return resolved_from_title

    return None


def _expand_websochat_keyword_variants(token: str) -> list[str]:
    normalized = str(token or "").strip()
    if len(normalized) < 2:
        return []
    variants: list[str] = [normalized]
    stripped_values = [
        re.sub(
            r"(에게서|에게는|에게|에서|으로는|으로|로는|로|은요|는요|이요|가요|을요|를요|은|는|이|가|을|를|에|도|만|과|와)$",
            "",
            normalized,
        ),
        re.sub(r"(이라고|라고|냐고|다고|자고|고)$", "", normalized),
        re.sub(r"(처럼|같이|같은|같아|같은데|보였어|보였지|보였대|보이던|보이는)$", "", normalized),
    ]
    for value in stripped_values:
        candidate = str(value or "").strip()
        if len(candidate) < 2 or candidate == normalized:
            continue
        variants.append(candidate)
    return variants


def _extract_websochat_keywords(content: str) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for token in WEBSOCHAT_KEYWORD_RE.findall(content or ""):
        for candidate in _expand_websochat_keyword_variants(token):
            if len(candidate) < 2 or candidate in WEBSOCHAT_KEYWORD_STOPWORDS:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            keywords.append(candidate)
            if len(keywords) >= 6:
                return keywords
    return keywords


def _resolve_websochat_summary_mode(
    query_text: str,
    latest_episode_no: int,
    mode: str | None = None,
    episode_no: int | None = None,
) -> tuple[str, int | None, int | None, int]:
    normalized_query = (query_text or "").strip()
    normalized_mode = (mode or "").strip().lower()
    exact_episode_no = int(episode_no) if episode_no else None

    if normalized_mode not in {"exact", "early", "latest", "general"}:
        exact_match = WEBSOCHAT_EXACT_EPISODE_RE.search(normalized_query)
        ordinal_match = WEBSOCHAT_ORDINAL_EPISODE_RE.search(normalized_query)
        if exact_match or ordinal_match:
            normalized_mode = "exact"
            exact_episode_no = int((exact_match or ordinal_match).group(1))
        elif any(
            keyword in normalized_query
            for keyword in (
                "첫 번째 화",
                "첫번째 화",
                "두 번째 화",
                "두번째 화",
                "세 번째 화",
                "세번째 화",
                "네 번째 화",
                "네번째 화",
            )
        ):
            normalized_mode = "exact"
        elif any(keyword in normalized_query for keyword in WEBSOCHAT_EARLY_QUESTION_KEYWORDS):
            normalized_mode = "early"
        elif any(keyword in normalized_query for keyword in WEBSOCHAT_BROAD_QUESTION_KEYWORDS):
            normalized_mode = "general"
        else:
            normalized_mode = "general"

    if normalized_mode == "exact":
        label_episode_no, ordinal_index = _extract_websochat_episode_reference(
            query_text=normalized_query,
            fallback_episode_no=exact_episode_no,
        )
        if label_episode_no is not None:
            exact_episode_no = label_episode_no
        if exact_episode_no is None and ordinal_index is None:
            normalized_mode = "general"
        elif exact_episode_no is not None:
            exact_episode_no = max(1, min(int(exact_episode_no), latest_episode_no))

    if normalized_mode == "early":
        early_upper_bound = min(
            latest_episode_no,
            max(8, min(20, (latest_episode_no + 4) // 5)),
        )
        return normalized_mode, exact_episode_no, early_upper_bound, 5

    if normalized_mode == "latest":
        latest_lower_bound = max(1, latest_episode_no - 19)
        return normalized_mode, exact_episode_no, latest_lower_bound, 5

    if normalized_mode == "exact":
        return normalized_mode, exact_episode_no, None, 1

    limit = 5 if any(keyword in normalized_query for keyword in WEBSOCHAT_BROAD_QUESTION_KEYWORDS) else 3
    return normalized_mode, exact_episode_no, None, limit


def _extract_websochat_episode_reference(
    query_text: str,
    fallback_episode_no: int | None = None,
) -> tuple[int | None, int | None]:
    normalized_query = (query_text or "").strip()
    exact_match = WEBSOCHAT_EXACT_EPISODE_RE.search(normalized_query)
    if exact_match:
        return int(exact_match.group(1)), None

    ordinal_match = WEBSOCHAT_ORDINAL_EPISODE_RE.search(normalized_query)
    if ordinal_match:
        return None, int(ordinal_match.group(1))

    for word, value in WEBSOCHAT_KOREAN_ORDINAL_MAP.items():
        if f"{word} 번째 화" in normalized_query or f"{word}번째 화" in normalized_query:
            return None, value

    return fallback_episode_no, None


async def _get_websochat_public_episode_refs(
    product_id: int,
    latest_episode_no: int,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT
                episode_no AS episodeNo,
                COALESCE(episode_title, '') AS episodeTitle
            FROM tb_product_episode
            WHERE product_id = :product_id
              AND use_yn = 'Y'
              AND open_yn = 'Y'
              AND episode_no <= :latest_episode_no
            ORDER BY episode_no ASC
            """
        ),
        {
            "product_id": product_id,
            "latest_episode_no": latest_episode_no,
        },
    )
    return [dict(row) for row in result.mappings().all()]


async def _resolve_websochat_exact_episode_no(
    *,
    product_id: int,
    latest_episode_no: int,
    query_text: str,
    fallback_episode_no: int | None,
    db: AsyncSession,
) -> int | None:
    label_episode_no, ordinal_index = _extract_websochat_episode_reference(
        query_text=query_text,
        fallback_episode_no=fallback_episode_no,
    )
    episode_rows = await _get_websochat_public_episode_refs(
        product_id=product_id,
        latest_episode_no=latest_episode_no,
        db=db,
    )
    if not episode_rows:
        return None

    if label_episode_no is not None:
        label_token = f"{label_episode_no}화"
        for row in episode_rows:
            if label_token in str(row.get("episodeTitle") or ""):
                return int(row.get("episodeNo") or 0) or None

    if ordinal_index is not None and 1 <= ordinal_index <= len(episode_rows):
        return int(episode_rows[ordinal_index - 1].get("episodeNo") or 0) or None

    if label_episode_no is not None:
        for row in episode_rows:
            if int(row.get("episodeNo") or 0) == label_episode_no:
                return label_episode_no

    return None


async def _get_websochat_summary_candidates(
    product_id: int,
    keywords: list[str],
    query_text: str,
    latest_episode_no: int,
    mode: str | None,
    episode_no: int | None,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    override_rows = _load_websochat_summary_override_rows(
        product_id=product_id,
        latest_episode_no=latest_episode_no,
    )
    if override_rows:
        return await _get_websochat_summary_candidates_from_rows(
            rows=override_rows,
            product_id=product_id,
            keywords=keywords,
            query_text=query_text,
            latest_episode_no=latest_episode_no,
            mode=mode,
            episode_no=episode_no,
            db=db,
        )

    params: dict[str, Any] = {"product_id": product_id}
    score_parts: list[str] = []
    for idx, keyword in enumerate(keywords, start=1):
        key = f"keyword_{idx}"
        params[key] = f"%{keyword}%"
        score_parts.append(f"CASE WHEN summary_text LIKE :{key} THEN 1 ELSE 0 END")
    score_sql = " + ".join(score_parts) if score_parts else "0"

    resolved_mode, exact_episode_no, range_anchor, limit = _resolve_websochat_summary_mode(
        query_text=query_text,
        latest_episode_no=latest_episode_no,
        mode=mode,
        episode_no=episode_no,
    )

    where_sql = ""
    order_sql = (
        f"""
          CASE WHEN ({score_sql}) > 0 THEN 0 ELSE 1 END,
          ({score_sql}) DESC,
          episode_to DESC,
          summary_id DESC
        """
    )

    if resolved_mode == "exact":
        resolved_episode_no = await _resolve_websochat_exact_episode_no(
            product_id=product_id,
            latest_episode_no=latest_episode_no,
            query_text=query_text,
            fallback_episode_no=exact_episode_no,
            db=db,
        )
        if resolved_episode_no:
            params["exact_episode_no"] = resolved_episode_no
        else:
            resolved_mode = "general"

    if resolved_mode == "exact" and params.get("exact_episode_no"):
        where_sql = """
          AND episode_from <= :exact_episode_no
          AND episode_to >= :exact_episode_no
        """
        order_sql = f"""
          CASE WHEN ({score_sql}) > 0 THEN 0 ELSE 1 END,
          ABS(episode_to - :exact_episode_no) ASC,
          summary_id DESC
        """
    elif resolved_mode == "early" and range_anchor:
        params["early_upper_bound"] = range_anchor
        where_sql = """
          AND episode_to <= :early_upper_bound
        """
        order_sql = f"""
          CASE WHEN ({score_sql}) > 0 THEN 0 ELSE 1 END,
          ({score_sql}) DESC,
          episode_to ASC,
          summary_id ASC
        """
    elif resolved_mode == "latest" and range_anchor:
        params["latest_lower_bound"] = range_anchor
        where_sql = """
          AND episode_to >= :latest_lower_bound
        """

    query = text(
        f"""
        SELECT
            episode_from AS episodeFrom,
            episode_to AS episodeTo,
            summary_text AS summaryText
        FROM tb_story_agent_context_summary
        WHERE product_id = :product_id
          AND summary_type = 'episode_summary'
          AND is_active = 'Y'
          AND episode_to <= :latest_episode_no
          {where_sql}
        ORDER BY
          {order_sql}
        LIMIT {limit}
        """
    )
    params["latest_episode_no"] = latest_episode_no
    result = await db.execute(query, params)
    return [dict(row) for row in result.mappings().all()]


def _get_websochat_summary_override_path() -> str:
    return str(os.getenv("STORY_AGENT_SUMMARY_OVERRIDE_JSON") or "").strip()


def _normalize_websochat_summary_override_row(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        episode_from = int(item.get("episodeFrom") or item.get("episode_from") or 0)
        episode_to = int(item.get("episodeTo") or item.get("episode_to") or 0)
    except Exception:
        return None
    summary_text = str(item.get("summaryText") or item.get("summary_text") or "").strip()
    if episode_from <= 0 or episode_to <= 0 or not summary_text:
        return None
    scope_key = str(item.get("scopeKey") or item.get("scope_key") or "").strip()
    product_id_raw = item.get("productId") or item.get("product_id")
    product_id = None
    if product_id_raw is not None and str(product_id_raw).strip():
        try:
            product_id = int(product_id_raw)
        except Exception:
            product_id = None
    return {
        "productId": product_id,
        "episodeFrom": episode_from,
        "episodeTo": episode_to,
        "scopeKey": scope_key,
        "summaryText": summary_text,
    }


def _load_websochat_summary_override_payload(path: str) -> list[dict[str, Any]]:
    mtime = os.path.getmtime(path)
    cached_path = _STORY_AGENT_SUMMARY_OVERRIDE_CACHE.get("path")
    cached_mtime = _STORY_AGENT_SUMMARY_OVERRIDE_CACHE.get("mtime")
    if cached_path == path and cached_mtime == mtime and isinstance(_STORY_AGENT_SUMMARY_OVERRIDE_CACHE.get("rows"), list):
        return list(_STORY_AGENT_SUMMARY_OVERRIDE_CACHE["rows"])

    with open(path, "r", encoding="utf-8") as fp:
        payload = json.load(fp)

    raw_rows = payload.get("rows") if isinstance(payload, dict) else payload
    normalized_rows: list[dict[str, Any]] = []
    if isinstance(raw_rows, list):
        payload_product_id = None
        if isinstance(payload, dict):
            try:
                if payload.get("productId") is not None:
                    payload_product_id = int(payload.get("productId"))
            except Exception:
                payload_product_id = None
        for item in raw_rows:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_websochat_summary_override_row(item)
            if not normalized:
                continue
            if normalized.get("productId") is None:
                normalized["productId"] = payload_product_id
            normalized_rows.append(normalized)

    _STORY_AGENT_SUMMARY_OVERRIDE_CACHE["path"] = path
    _STORY_AGENT_SUMMARY_OVERRIDE_CACHE["mtime"] = mtime
    _STORY_AGENT_SUMMARY_OVERRIDE_CACHE["rows"] = normalized_rows
    return list(normalized_rows)


def _load_websochat_summary_override_rows(
    *,
    product_id: int,
    latest_episode_no: int,
) -> list[dict[str, Any]]:
    path = _get_websochat_summary_override_path()
    if not path:
        return []
    try:
        rows = _load_websochat_summary_override_payload(path)
    except Exception as exc:
        logger.warning(
            "websochat summary_override_load_failed path=%r error=%s",
            path,
            str(exc)[:300],
        )
        return []

    filtered_rows = [
        row
        for row in rows
        if (row.get("productId") in {None, product_id})
        and int(row.get("episodeTo") or 0) <= latest_episode_no
    ]
    if filtered_rows:
        logger.info(
            "websochat summary_override_loaded path=%r product_id=%s latest_episode_no=%s row_count=%s",
            path,
            product_id,
            latest_episode_no,
            len(filtered_rows),
        )
    return filtered_rows


def _score_websochat_summary_row(summary_text: str, keywords: list[str]) -> int:
    normalized_text = str(summary_text or "")
    score = 0
    for keyword in keywords:
        normalized_keyword = str(keyword or "").strip()
        if normalized_keyword and normalized_keyword in normalized_text:
            score += 1
    return score


async def _get_websochat_summary_candidates_from_rows(
    *,
    rows: list[dict[str, Any]],
    product_id: int,
    keywords: list[str],
    query_text: str,
    latest_episode_no: int,
    mode: str | None,
    episode_no: int | None,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    resolved_mode, exact_episode_no, range_anchor, limit = _resolve_websochat_summary_mode(
        query_text=query_text,
        latest_episode_no=latest_episode_no,
        mode=mode,
        episode_no=episode_no,
    )

    if resolved_mode == "exact":
        resolved_episode_no = await _resolve_websochat_exact_episode_no(
            product_id=product_id,
            latest_episode_no=latest_episode_no,
            query_text=query_text,
            fallback_episode_no=exact_episode_no,
            db=db,
        )
        if resolved_episode_no:
            exact_episode_no = resolved_episode_no
        else:
            resolved_mode = "general"

    filtered_rows: list[dict[str, Any]] = []
    for row in rows:
        episode_from = int(row.get("episodeFrom") or 0)
        episode_to = int(row.get("episodeTo") or 0)
        if episode_to <= 0 or episode_to > latest_episode_no:
            continue
        if resolved_mode == "exact" and exact_episode_no:
            if not (episode_from <= exact_episode_no <= episode_to):
                continue
        elif resolved_mode == "early" and range_anchor:
            if episode_to > range_anchor:
                continue
        elif resolved_mode == "latest" and range_anchor:
            if episode_to < range_anchor:
                continue
        filtered_rows.append(row)

    scored_rows: list[dict[str, Any]] = []
    for row in filtered_rows:
        scored_rows.append(
            {
                **row,
                "_score": _score_websochat_summary_row(str(row.get("summaryText") or ""), keywords),
            }
        )

    if resolved_mode == "exact" and exact_episode_no:
        scored_rows.sort(
            key=lambda row: (
                0 if int(row.get("_score") or 0) > 0 else 1,
                abs(int(row.get("episodeTo") or 0) - int(exact_episode_no)),
                -int(row.get("episodeTo") or 0),
            )
        )
    elif resolved_mode == "early" and range_anchor:
        scored_rows.sort(
            key=lambda row: (
                0 if int(row.get("_score") or 0) > 0 else 1,
                -int(row.get("_score") or 0),
                int(row.get("episodeTo") or 0),
                int(row.get("episodeFrom") or 0),
            )
        )
    else:
        scored_rows.sort(
            key=lambda row: (
                0 if int(row.get("_score") or 0) > 0 else 1,
                -int(row.get("_score") or 0),
                -int(row.get("episodeTo") or 0),
                -int(row.get("episodeFrom") or 0),
            )
        )

    return [
        {
            "episodeFrom": int(row.get("episodeFrom") or 0),
            "episodeTo": int(row.get("episodeTo") or 0),
            "summaryText": str(row.get("summaryText") or ""),
            "scopeKey": str(row.get("scopeKey") or ""),
        }
        for row in scored_rows[:limit]
    ]


def _merge_websochat_summary_rows(
    *groups: list[dict[str, Any]],
    limit: int = WEBSOCHAT_BROAD_SUMMARY_CONTEXT_LIMIT,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, int, int]] = set()
    for rows in groups:
        for row in rows:
            scope_key = str(row.get("scopeKey") or "").strip()
            episode_from = int(row.get("episodeFrom") or 0)
            episode_to = int(row.get("episodeTo") or 0)
            key = (scope_key, episode_from, episode_to)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged.append(row)
            if len(merged) >= limit:
                return merged
    return merged


async def _get_websochat_active_summary_rows_by_type(
    *,
    product_id: int,
    latest_episode_no: int,
    summary_type: str,
    db: AsyncSession,
    limit: int = 2,
) -> list[dict[str, Any]]:
    query = text(
        f"""
        SELECT
            episode_from AS episodeFrom,
            episode_to AS episodeTo,
            scope_key AS scopeKey,
            summary_text AS summaryText
        FROM tb_story_agent_context_summary
        WHERE product_id = :product_id
          AND summary_type = :summary_type
          AND is_active = 'Y'
          AND COALESCE(episode_to, 0) <= :latest_episode_no
        ORDER BY
          COALESCE(episode_to, 0) DESC,
          COALESCE(episode_from, 0) DESC,
          summary_id DESC
        LIMIT {limit}
        """
    )
    result = await db.execute(
        query,
        {
            "product_id": product_id,
            "summary_type": summary_type,
            "latest_episode_no": latest_episode_no,
        },
    )
    return [dict(row) for row in result.mappings().all()]


def _has_websochat_recency_cue(query_text: str) -> bool:
    normalized = " ".join(str(query_text or "").split())
    if not normalized:
        return False
    return any(token in normalized for token in ("지금", "최근", "요즘", "현재", "최신"))


async def _get_websochat_broad_summary_context_rows(
    *,
    product_id: int,
    query_text: str,
    latest_episode_no: int,
    resolved_mode: str,
    qa_subtype: str | None = None,
    qa_corrections: list[dict[str, str]] | None = None,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    keywords = _extract_websochat_keywords(query_text)
    resolved_subtype = str(qa_subtype or "opinion_general").strip().lower() or "opinion_general"

    if resolved_mode == "exact":
        return []

    if resolved_mode == "early":
        return await _get_websochat_summary_candidates(
            product_id=product_id,
            keywords=keywords,
            query_text=query_text,
            latest_episode_no=latest_episode_no,
            mode="early",
            episode_no=None,
            db=db,
        )

    if resolved_mode == "latest":
        return await _get_websochat_summary_candidates(
            product_id=product_id,
            keywords=keywords,
            query_text=query_text,
            latest_episode_no=latest_episode_no,
            mode="latest",
            episode_no=None,
            db=db,
        )

    general_rows = await _get_websochat_summary_candidates(
        product_id=product_id,
        keywords=keywords,
        query_text=query_text,
        latest_episode_no=latest_episode_no,
        mode="general",
        episode_no=None,
        db=db,
    )
    if general_rows:
        general_rows = _filter_websochat_summary_rows_by_qa_corrections(
            general_rows,
            qa_corrections=qa_corrections or [],
        )
        async def get_latest_rows() -> list[dict[str, Any]]:
            rows = await _get_websochat_summary_candidates(
                product_id=product_id,
                keywords=keywords,
                query_text=query_text,
                latest_episode_no=latest_episode_no,
                mode="latest",
                episode_no=None,
                db=db,
            )
            return _filter_websochat_summary_rows_by_qa_corrections(rows, qa_corrections=qa_corrections or [])

        async def get_early_rows() -> list[dict[str, Any]]:
            rows = await _get_websochat_summary_candidates(
                product_id=product_id,
                keywords=keywords,
                query_text=query_text,
                latest_episode_no=latest_episode_no,
                mode="early",
                episode_no=None,
                db=db,
            )
            return _filter_websochat_summary_rows_by_qa_corrections(rows, qa_corrections=qa_corrections or [])

        selected_rows = general_rows[:2]
        selected_label = "general"
        if resolved_subtype in {"world_setting", "can_it_work_logic"}:
            product_rows = _filter_websochat_summary_rows_by_qa_corrections(
                await _get_websochat_active_summary_rows_by_type(
                    product_id=product_id,
                    latest_episode_no=latest_episode_no,
                    summary_type="product_summary",
                    db=db,
                    limit=1,
                ),
                qa_corrections=qa_corrections or [],
            )
            range_rows = _filter_websochat_summary_rows_by_qa_corrections(
                await _get_websochat_active_summary_rows_by_type(
                    product_id=product_id,
                    latest_episode_no=latest_episode_no,
                    summary_type="range_summary",
                    db=db,
                    limit=1,
                ),
                qa_corrections=qa_corrections or [],
            )
            latest_rows = await get_latest_rows()
            early_rows = await get_early_rows()
            selected_rows = _merge_websochat_summary_rows(
                latest_rows[:1],
                general_rows[:1],
                product_rows[:1],
                range_rows[:1],
                early_rows[:1],
                limit=5,
            )
            if _has_websochat_recency_cue(query_text):
                selected_rows = _merge_websochat_summary_rows(
                    selected_rows,
                    latest_rows[:1],
                    limit=5,
                )
                selected_label = f"{resolved_subtype}_pack_with_latest"
            else:
                selected_label = f"{resolved_subtype}_pack"
        elif resolved_subtype == "opinion_general":
            latest_rows = await get_latest_rows()
            selected_rows = _merge_websochat_summary_rows(
                latest_rows[:2],
                general_rows[:1],
                limit=3,
            )
            selected_label = "opinion_general_pack"
        elif resolved_subtype == "relationship":
            latest_rows = await get_latest_rows()
            selected_rows = _merge_websochat_summary_rows(
                general_rows[:2],
                latest_rows[:1],
                limit=4,
            )
            selected_label = "relationship_pack"
        elif resolved_subtype == "character_axis":
            latest_rows = await get_latest_rows()
            selected_rows = _merge_websochat_summary_rows(
                general_rows[:2],
                latest_rows[:1],
                limit=4,
            )
            selected_label = "character_axis_pack"
        elif resolved_subtype == "plot_clarification":
            latest_rows = await get_latest_rows()
            selected_rows = _merge_websochat_summary_rows(
                latest_rows[:2],
                general_rows[:1],
                limit=4,
            )
            selected_label = "plot_pack"
        elif resolved_subtype == "name_memory":
            latest_rows = await get_latest_rows()
            selected_rows = _merge_websochat_summary_rows(
                general_rows[:1],
                latest_rows[:1],
                limit=3,
            )
            selected_label = "name_memory_pack"
        logger.info(
            "websochat qa_summary_selection mode=general qa_subtype=%s selected=%s "
            "general_count=%s correction_count=%s ranges=%s prompt_preview=%r",
            resolved_subtype,
            selected_label,
            len(selected_rows),
            len(qa_corrections or []),
            [
                (
                    int(row.get("episodeFrom") or 0),
                    int(row.get("episodeTo") or 0),
                )
                for row in selected_rows[:5]
            ],
            query_text[:120],
        )
        return selected_rows

    latest_rows = await _get_websochat_summary_candidates(
        product_id=product_id,
        keywords=keywords,
        query_text=query_text,
        latest_episode_no=latest_episode_no,
        mode="latest",
        episode_no=None,
        db=db,
    )
    if latest_rows:
        latest_rows = _filter_websochat_summary_rows_by_qa_corrections(
            latest_rows,
            qa_corrections=qa_corrections or [],
        )
        logger.info(
            "websochat qa_summary_selection mode=general qa_subtype=%s selected=latest_fallback "
            "general_count=0 latest_count=%s early_count=0 correction_count=%s ranges=%s prompt_preview=%r",
            resolved_subtype,
            len(latest_rows),
            len(qa_corrections or []),
            [
                (
                    int(row.get("episodeFrom") or 0),
                    int(row.get("episodeTo") or 0),
                )
                for row in latest_rows[:3]
            ],
            query_text[:120],
        )
        return latest_rows[:1]

    early_rows = await _get_websochat_summary_candidates(
        product_id=product_id,
        keywords=keywords,
        query_text=query_text,
        latest_episode_no=latest_episode_no,
        mode="early",
        episode_no=None,
        db=db,
    )
    early_rows = _filter_websochat_summary_rows_by_qa_corrections(
        early_rows,
        qa_corrections=qa_corrections or [],
    )
    logger.info(
        "websochat qa_summary_selection mode=general qa_subtype=%s selected=%s "
        "general_count=0 latest_count=0 early_count=%s correction_count=%s ranges=%s prompt_preview=%r",
        resolved_subtype,
        "early_fallback" if early_rows else "empty",
        len(early_rows),
        len(qa_corrections or []),
        [
            (
                int(row.get("episodeFrom") or 0),
                int(row.get("episodeTo") or 0),
            )
            for row in early_rows[:3]
        ],
        query_text[:120],
    )
    return early_rows[:1]


def _normalize_websochat_matching_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _build_websochat_subject_tokens(subject: str) -> list[str]:
    normalized = _normalize_websochat_matching_text(subject)
    tokens = [token for token in re.split(r"[^0-9a-zA-Z가-힣]+", normalized) if len(token) >= 2]
    if normalized and normalized not in tokens:
        tokens.append(normalized)
    return tokens[:4]


def _filter_websochat_summary_rows_by_qa_corrections(
    rows: list[dict[str, Any]],
    *,
    qa_corrections: list[dict[str, str]],
) -> list[dict[str, Any]]:
    if not rows or not qa_corrections:
        return rows

    filtered_rows: list[dict[str, Any]] = []
    dropped_ranges: list[tuple[int, int]] = []
    for row in rows:
        summary_text = _normalize_websochat_matching_text(row.get("summaryText"))
        should_drop = False
        for item in qa_corrections:
            subject_tokens = _build_websochat_subject_tokens(str(item.get("subject") or ""))
            correct_value = _normalize_websochat_matching_text(item.get("correct_value"))
            incorrect_value = _normalize_websochat_matching_text(item.get("incorrect_value"))
            if not incorrect_value or incorrect_value not in summary_text:
                continue
            subject_hit = any(token in summary_text for token in subject_tokens)
            correct_hit = bool(correct_value and correct_value in summary_text)
            if subject_hit:
                should_drop = True
                break
            if not correct_hit:
                should_drop = True
                break
        if should_drop:
            dropped_ranges.append(
                (
                    int(row.get("episodeFrom") or 0),
                    int(row.get("episodeTo") or 0),
                )
            )
            continue
        filtered_rows.append(row)

    if dropped_ranges:
        logger.info(
            "websochat qa_summary_correction_filter before=%s after=%s dropped_ranges=%s corrections=%s",
            len(rows),
            len(filtered_rows),
            dropped_ranges[:4],
            qa_corrections[:4],
        )
    return filtered_rows


def _build_websochat_summary_context_message(
    summary_rows: list[dict[str, Any]],
    *,
    qa_subtype: str | None = None,
) -> str:
    if not summary_rows:
        return ""
    resolved_subtype = str(qa_subtype or "opinion_general").strip().lower() or "opinion_general"

    blocks: list[str] = []
    for row in summary_rows:
        summary_text = str(row.get("summaryText") or "").strip()
        if not summary_text:
            continue
        episode_from = int(row.get("episodeFrom") or 0)
        episode_to = int(row.get("episodeTo") or 0)
        label = f"{episode_from}화" if episode_from == episode_to else f"{episode_from}~{episode_to}화"
        blocks.append(f"[{label} 요약]\n{summary_text}")

    if not blocks:
        return ""

    intro = "아래는 이번 질문과 관련해 먼저 참고할 공개 회차 요약이다. 필요한 부분만 자연스럽게 녹여서 답하고, 답이 되는 상황이면 굳이 다시 정리하거나 되묻지 마라."
    if resolved_subtype in {"world_setting", "can_it_work_logic"}:
        intro = "아래는 이번 질문과 관련해 설정/규칙을 먼저 잡을 때 참고할 공개 회차 요약이다. 세계관 룰, 세력 구조, 능력 체계를 설명할 때 우선 활용하고 장르 일반론으로만 때우지 마라."
    elif resolved_subtype == "relationship":
        intro = "아래는 이번 질문과 관련해 인물 관계와 감정선을 먼저 잡을 때 참고할 공개 회차 요약이다. 관계를 먼저 한 문장으로 정리하고 근거를 자연스럽게 붙여라."
    elif resolved_subtype == "character_axis":
        intro = "아래는 이번 질문과 관련해 인물 성격과 캐릭터 축을 잡을 때 참고할 공개 회차 요약이다. 성격을 먼저 요약하고 그렇게 보이는 행동 근거를 붙여라."
    elif resolved_subtype == "plot_clarification":
        intro = "아래는 이번 질문과 관련해 떡밥, 정체, 갈등 축을 먼저 잡을 때 참고할 공개 회차 요약이다. 공개 범위 기준으로 가장 유력한 축부터 답하라."
    elif resolved_subtype == "name_memory":
        intro = "아래는 이번 질문과 관련해 이름, 호칭, 등장인물 식별을 정리할 때 참고할 공개 회차 요약이다. 헷갈리는 인물부터 먼저 구분해라."

    return (
        intro + "\n\n"
        + "\n\n".join(blocks)
    )


async def _get_websochat_product_context(product_id: int, db: AsyncSession) -> dict[str, Any]:
    result = await db.execute(
        text(
            f"""
            SELECT
                p.product_id AS productId,
                p.title,
                p.author_name AS authorNickname,
                p.story_agent_setting_text AS websochatSetting,
                COALESCE(MAX(e.episode_no), 0) AS latestEpisodeNo
            FROM tb_product p
            LEFT JOIN tb_product_episode e
              ON e.product_id = p.product_id
             AND e.use_yn = 'Y'
             AND e.open_yn = 'Y'
            WHERE p.product_id = :product_id
            GROUP BY p.product_id, p.title, p.author_name, p.story_agent_setting_text
            """
        ),
        {"product_id": product_id},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else {}


def _build_websochat_search_chunk_snippet(
    *,
    text_value: str,
    keywords: list[str],
    query_text: str,
    window_chars: int = 1200,
    prefix_chars: int = 180,
) -> str:
    normalized_text = str(text_value or "").strip()
    if not normalized_text:
        return ""

    candidate_terms = [
        str(term).strip()
        for term in [*list(keywords or []), str(query_text or "").strip()]
        if str(term).strip()
    ]
    lowered_text = normalized_text.lower()
    match_index: int | None = None
    for term in sorted(candidate_terms, key=len, reverse=True):
        idx = lowered_text.find(term.lower())
        if idx < 0:
            continue
        if match_index is None or idx < match_index:
            match_index = idx
    if match_index is None:
        return normalized_text[:window_chars]

    start = max(0, match_index - prefix_chars)
    end = min(len(normalized_text), start + window_chars)
    if end - start < window_chars and start > 0:
        start = max(0, end - window_chars)
    return normalized_text[start:end].strip()


async def _search_websochat_episode_contents(
    product_id: int,
    query_text: str,
    latest_episode_no: int,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    keywords = _extract_websochat_keywords(query_text)
    params: dict[str, Any] = {"product_id": product_id}
    where_parts: list[str] = []
    score_parts: list[str] = []
    for idx, keyword in enumerate(keywords, start=1):
        key = f"keyword_{idx}"
        params[key] = f"%{keyword}%"
        where_parts.append(f"c.text LIKE :{key}")
        score_parts.append(f"(CASE WHEN c.text LIKE :{key} THEN {max(len(keyword), 1)} ELSE 0 END)")
    if not where_parts:
        params["keyword_fallback"] = f"%{(query_text or '').strip()[:40]}%"
        where_parts.append("c.text LIKE :keyword_fallback")
        score_parts.append("(CASE WHEN c.text LIKE :keyword_fallback THEN 1 ELSE 0 END)")

    result = await db.execute(
        text(
            f"""
            SELECT
                c.episode_no AS episodeNo,
                c.text AS rawText,
                ({' + '.join(score_parts)}) AS matchScore
            FROM tb_story_agent_context_chunk c
            JOIN tb_story_agent_context_doc d
              ON d.context_doc_id = c.context_doc_id
             AND d.is_active = 'Y'
            JOIN tb_product_episode pe
              ON pe.episode_id = c.episode_id
             AND pe.use_yn = 'Y'
             AND pe.open_yn = 'Y'
            WHERE c.product_id = :product_id
              AND c.episode_no <= :latest_episode_no
              AND ({' OR '.join(where_parts)})
            ORDER BY matchScore DESC, c.episode_no DESC, c.chunk_no ASC
            LIMIT 6
            """
        ),
        {**params, "latest_episode_no": latest_episode_no},
    )
    rows: list[dict[str, Any]] = []
    for row in result.mappings().all():
        item = dict(row)
        item["chunkText"] = _build_websochat_search_chunk_snippet(
            text_value=str(item.pop("rawText", "") or ""),
            keywords=keywords,
            query_text=query_text,
        )
        rows.append(item)
    return rows


async def _get_websochat_episode_contents(
    product_id: int,
    episode_from: int,
    episode_to: int,
    latest_episode_no: int,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    safe_from = max(1, int(episode_from))
    safe_to = min(max(safe_from, int(episode_to)), latest_episode_no)
    safe_from = min(safe_from, latest_episode_no)
    if safe_to - safe_from > 2:
        safe_to = safe_from + 2
    if safe_from <= 0 or safe_to <= 0 or safe_from > safe_to:
        return []

    result = await db.execute(
        text(
            """
            SELECT
                c.episode_no AS episodeNo,
                c.text AS chunkText
            FROM tb_story_agent_context_chunk c
            JOIN tb_story_agent_context_doc d
              ON d.context_doc_id = c.context_doc_id
             AND d.is_active = 'Y'
            JOIN tb_product_episode pe
              ON pe.episode_id = c.episode_id
             AND pe.use_yn = 'Y'
             AND pe.open_yn = 'Y'
            WHERE c.product_id = :product_id
              AND c.episode_no BETWEEN :episode_from AND :episode_to
            ORDER BY c.episode_no ASC, c.chunk_no ASC
            LIMIT 30
            """
        ),
        {
            "product_id": product_id,
            "episode_from": safe_from,
            "episode_to": safe_to,
        },
    )
    rows = [dict(row) for row in result.mappings().all()]
    grouped: dict[int, dict[str, Any]] = {}
    for row in rows:
        episode_no = int(row.get("episodeNo") or 0)
        current = grouped.setdefault(
            episode_no,
            {
                "episodeNo": episode_no,
                "content": "",
            },
        )
        next_text = f"{current['content']}\n\n{str(row.get('chunkText') or '').strip()}".strip()
        current["content"] = next_text[:WEBSOCHAT_MAX_EPISODE_CONTENT_CHARS]
    return list(grouped.values())


async def _get_websochat_recent_messages(session_id: int, db: AsyncSession) -> list[dict[str, str]]:
    result = await db.execute(
        text(
            """
            SELECT role, content
            FROM tb_story_agent_message
            WHERE session_id = :session_id
            ORDER BY message_id DESC
            LIMIT :limit
            """
        ),
        {
            "session_id": session_id,
            "limit": WEBSOCHAT_MAX_HISTORY_MESSAGES,
        },
    )
    rows = [dict(row) for row in result.mappings().all()]
    rows.reverse()
    return [
        {
            "role": str(row.get("role") or "user"),
            "content": _strip_websochat_noncanonical_message_marker(str(row.get("content") or ""))[:2000],
        }
        for row in rows
        if str(row.get("content") or "").strip()
        and not _is_websochat_noncanonical_message(str(row.get("content") or ""))
    ]


def _build_websochat_system_prompt(product_row: dict[str, Any]) -> str:
    title = str(product_row.get("title") or "작품")
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    websochat_setting = str(product_row.get("websochatSetting") or "").strip()
    setting_block = (
        f" 작품 보조 설정: {websochat_setting} "
        if websochat_setting
        else ""
    )
    return (
        "너는 LikeNovel 스토리 에이전트다. "
        f"현재 작품은 '{title}'이고 최신 공개 회차는 {latest_episode_no}화다. "
        f"{setting_block}"
        "질문에 답할 때는 작품 외부 추천이나 일반론으로 새지 말고, 이 작품 안에서만 답하라. "
        "tool 결과에 없는 사실은 말하지 마라. 총 화수, 연재 계획, 비공개 회차 내용, 작가 의도 같은 메타를 추측해서 쓰지 마라. "
        "사실 확인이 필요한 질문이면 반드시 tool을 사용해 회차 요약이나 원문을 확인한 뒤 답하라. "
        "모호하면 원문을 먼저 더 조회하라. 원문 근거 없이 사실을 단정하지 마라. "
        "작품 보조 설정이 있으면 캐릭터 성향, 세계관 룰, 전력 비교, IF/VS 질문의 보조 근거로만 활용하라. 원문이나 공개 회차 정보와 충돌하면 반드시 원문과 공개 정보를 우선하라. "
        "예상 질문(predict)일 때만 추정을 허용하고, 그 외 질문에서는 현재 공개 범위에서 확인된 사실만 답하라. "
        "사용자가 작품 속 인물처럼 말해 달라고 하면, 공개 범위에서 확인된 성격·상황·관계를 바탕으로 그 인물 시점에서 자연스럽게 답하라. "
        "이때 자신을 에이전트라고 소개하거나 역할극 자체를 거절하지 마라. 확인되지 않은 과거사, 속마음, 외형, 미공개 사건은 만들지 마라. 정보가 일부 부족해도 공개 범위에서 확인된 사실 안에서만 짧게 이어가라. "
        "정확한 회차가 보이면 search_episode_summaries를 mode=exact로 호출하라. 'N화'는 제목 라벨 기준으로, 'N번째 화'는 공개 회차 순서 기준으로 해석한다. 초반/처음/첫 발현/첫 등장 같은 질문이면 mode=early, 최신/최근/지금 같은 질문이면 mode=latest를 우선 사용하라. "
        "도구 내부의 회차 해석 과정이나 episode_no 매핑은 사용자에게 설명하지 마라. 질문에 맞는 회차 원문이 이미 조회되었다면 그 원문을 사용자가 지칭한 회차의 근거로 자연스럽게 답하라. "
        "주인공 소개나 인물 역할극 질문이면 먼저 초반 구간 요약을 찾고, 필요하면 그 회차 원문을 조회해 이름, 목표, 현재 상황을 확인하라. "
        "최신 갈등, 최신 관계, 떡밥 질문이면 최신 공개 회차 쪽 요약과 원문을 먼저 확인하라. "
        "질문이 넓거나 모호하면 거절하거나 '질문을 좁혀 달라'로 끝내지 마라. 공개 범위에서 바로 말해줄 수 있는 쪽부터 자연스럽게 답하고, 정말 필요한 경우에만 마지막에 짧고 편한 말투로 한 번만 되물어라. "
        "대화를 이어갈 때도 운영자처럼 선택지를 나열하기보다, 사용자가 바로 이어서 물어볼 만한 한 지점만 가볍게 열어둬라. "
        "사용자가 '저/그/이 선택', '저/그/이 장면', '그때', '그거'처럼 지시대명사로 모호하게 물으면 섣불리 하나를 확정하지 마라. "
        "최근 대화와 이번 질문 관련 요약을 기준으로 유력한 후보가 1~2개면 짧게 짚어주고, 모호함이 클 때만 한 번 가볍게 확인하라. "
        "회차나 장면 키워드 확인이 필요해도 문진표처럼 길게 묻지 말고, 사용자가 바로 답할 수 있는 짧은 질문 하나로 끝내라. "
        "사용자가 추가 단서를 주기 전에는 특정 장면이나 선택을 사실처럼 단정하지 마라. "
        "도구를 1~2번 조회한 뒤에도 근거가 부족하면, 공개 범위에서 확인되는 부분만 짧게 답하고 더 이상의 tool 호출은 멈춰라. "
        "답변은 한국어로 하되, 상담봇처럼 딱딱하거나 운영자처럼 굴지 말고 ChatGPT처럼 친근하고 자연스럽게 이어가라. 과하게 가볍게 굴 필요는 없지만, 사용자가 편하게 대화하고 있다는 느낌이 들게 답하라. 첫 문장을 '정리하면', '다시 정리하자면', '다시 말해', '우리가', '먼저' 같은 메타 표현으로 시작하지 마라. 설명을 시작하기보다 바로 내용으로 들어가고, 관련 회차 번호가 있으면 자연스럽게 포함하라."
    )


def _is_websochat_ambiguous_reference_query(query_text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(query_text or "")).strip()
    if not normalized:
        return False
    return any(pattern in normalized for pattern in WEBSOCHAT_AMBIGUOUS_REFERENCE_PATTERNS)


def _get_websochat_game_state(
    session_memory: dict[str, Any],
    *,
    game_mode: str,
    gender_scope: str,
    category: str,
) -> dict[str, Any]:
    normalized = _normalize_websochat_session_memory(session_memory)
    return _normalize_websochat_game_state(
        game_mode,
        ((((normalized.get("games") or {}).get(game_mode) or {}).get(gender_scope) or {}).get(category) or {}),
    )


def _set_websochat_game_state(
    session_memory: dict[str, Any],
    *,
    game_mode: str,
    gender_scope: str,
    category: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    normalized = _normalize_websochat_session_memory(session_memory)
    games = dict(normalized.get("games") or {})
    scope_map = dict((games.get(game_mode) or {}))
    category_map = dict((scope_map.get(gender_scope) or {}))
    category_map[category] = _normalize_websochat_game_state(game_mode, state)
    scope_map[gender_scope] = category_map
    games[game_mode] = scope_map
    normalized["games"] = _normalize_websochat_games_memory(games)
    normalized["active_mode"] = game_mode
    normalized["game_context"] = _build_websochat_game_context(
        game_mode=game_mode,
        game_gender_scope=gender_scope,
        game_category=category if category in WEBSOCHAT_ALLOWED_GAME_CATEGORIES else None,
        game_match_mode=(state or {}).get("mode") if game_mode == "vs_game" else None,
    )
    return normalized


def _build_websochat_worldcup_meta_reply(
    *,
    product_row: dict[str, Any],
    gender_scope: str,
    category: str,
    state: dict[str, Any],
    read_scope_label: str | None = None,
    current_pair: list[str] | None = None,
) -> str:
    gender_label = {
        "male": "남성 버전",
        "female": "여성 버전",
        "mixed": "섞어서",
    }.get(gender_scope, gender_scope or "미정")
    category_label = {
        "romance": "연애/호감",
        "date": "데이트 상대로 끌리는 기준",
        "narrative": "서사적으로 제일 꽂히는 기준",
        "power": "파워",
        "intelligence": "지능",
        "charm": "매력",
        "mental": "멘탈",
        "survival": "생존력",
        "personality": "성격",
    }.get(category, category or "미정")
    read_episode_to = max(int(state.get("read_episode_to") or 0), 0)
    resolved_read_scope_label = str(read_scope_label or "").strip()
    if not resolved_read_scope_label and read_episode_to > 0:
        resolved_read_scope_label = f"{read_episode_to}화"
    current_round = str(state.get("current_round") or "").strip() or "현재 라운드"
    candidate_count = len(list(state.get("current_candidates") or []))
    reply_lines = [
        f"{str(product_row.get('title') or '').strip()} 월드컵은 지금 {gender_label} / {category_label} 기준이야.",
    ]
    if resolved_read_scope_label:
        reply_lines.append(f"읽은 범위는 {resolved_read_scope_label}까지로 잡혀 있어.")
    if candidate_count > 0:
        reply_lines.append(f"후보는 현재 {candidate_count}명 기준으로 묶여 있어.")
    if current_pair and len(current_pair) == 2:
        reply_lines.append(f"지금 대진은 {current_round}의 {current_pair[0]} vs {current_pair[1]}야.")
    else:
        reply_lines.append(f"지금 단계는 {current_round} 준비 상태야.")
    reply_lines.append("원하면 그대로 진행하거나, 읽은 범위/성별/기준을 바꿔서 다시 잡을 수 있어.")
    return "\n".join(reply_lines)


def _build_websochat_worldcup_setup_meta_reply(
    *,
    product_row: dict[str, Any],
    gender_scope: str | None,
    category: str | None,
    read_scope_label: str | None = None,
) -> str:
    gender_label = {
        "male": "남성 버전",
        "female": "여성 버전",
        "mixed": "섞어서",
    }.get(str(gender_scope or "").strip().lower(), "미정")
    category_label = {
        "romance": "연애/호감",
        "date": "데이트 상대로 끌리는 기준",
        "narrative": "서사적으로 제일 꽂히는 기준",
        "power": "파워",
        "intelligence": "지능",
        "charm": "매력",
        "mental": "멘탈",
        "survival": "생존력",
        "personality": "성격",
    }.get(str(category or "").strip().lower(), "미정")
    reply_lines = [
        f"{str(product_row.get('title') or '').strip()} 월드컵은 아직 준비 단계야.",
    ]
    if read_scope_label:
        reply_lines.append(f"읽은 범위는 {read_scope_label}까지로 잡혀 있어.")
    reply_lines.append(f"성별 범위는 {gender_label}, 기준은 {category_label} 상태야.")
    reply_lines.append("아직 대진을 짜기 전이라, 먼저 남성/여성/섞어서와 기준을 정하면 바로 후보를 붙일 수 있어.")
    return "\n".join(reply_lines)


async def _generate_websochat_worldcup_reply(
    *,
    session_memory: dict[str, Any],
    product_row: dict[str, Any],
    user_prompt: str,
    db: AsyncSession,
) -> tuple[str, dict[str, Any]]:
    normalized = _normalize_websochat_session_memory(session_memory)
    game_context = normalized.get("game_context") or {}
    gender_scope = str(game_context.get("gender_scope") or "").strip().lower()
    category = str(game_context.get("category") or "").strip().lower()
    product_id = int(product_row.get("productId") or 0)
    if not gender_scope or not category:
        read_scope_label = await _build_websochat_read_scope_label(
            product_id=product_id,
            read_episode_to=normalized.get("read_episode_to"),
            db=db,
        )
        return (
            build_websochat_game_guide_reply(
                session_memory=normalized,
                product_row=product_row,
                read_scope_label=read_scope_label,
            )
            or "",
            normalized,
        )

    state = _get_websochat_game_state(
        normalized,
        game_mode="ideal_worldcup",
        gender_scope=gender_scope,
        category=category,
    )
    followup = resolve_websochat_worldcup_followup(user_prompt=user_prompt)
    if followup["exit_requested"]:
        reply = "좋아요. 월드컵은 여기서 잠깐 쉬고, 다시 작품 얘기로 돌아가볼게요."
        return reply, _clear_websochat_game_context(normalized)
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    inferred_read_episode_to = await _resolve_websochat_prompt_read_episode_to(
        product_id=int(product_row.get("productId") or 0),
        latest_episode_no=latest_episode_no,
        user_prompt=user_prompt,
        db=db,
    )
    inferred_requested_size = int(followup["requested_size"] or 0) or None
    requested_gender_scope = str(followup["gender_scope"] or "").strip().lower() or None
    requested_category = str(followup["category"] or "").strip().lower() or None
    previous_gender_scope = gender_scope
    previous_category = category
    previous_read_episode_to = max(int(state.get("read_episode_to") or 0), 0) or None
    previous_requested_size = int(state.get("requested_bracket_size") or 0) or None

    if requested_gender_scope or requested_category:
        normalized = _merge_websochat_session_memory(
            base_memory=normalized,
            rp_mode=None,
            active_character=None,
            active_character_label=None,
            scene_episode_no=None,
            game_mode="ideal_worldcup",
            game_gender_scope=requested_gender_scope or gender_scope,
            game_category=requested_category or category,
            game_read_episode_to=inferred_read_episode_to or previous_read_episode_to,
        )
        game_context = normalized.get("game_context") or {}
        gender_scope = str(game_context.get("gender_scope") or "").strip().lower()
        category = str(game_context.get("category") or "").strip().lower()
        state = _get_websochat_game_state(
            normalized,
            game_mode="ideal_worldcup",
            gender_scope=gender_scope,
            category=category,
        )

    if inferred_read_episode_to is not None:
        state["read_episode_to"] = inferred_read_episode_to
    if inferred_requested_size:
        state["requested_bracket_size"] = inferred_requested_size

    has_constraint_update = any(
        [
            inferred_read_episode_to is not None and inferred_read_episode_to != previous_read_episode_to,
            bool(inferred_requested_size and inferred_requested_size != previous_requested_size),
            bool(requested_gender_scope and requested_gender_scope != previous_gender_scope),
            bool(requested_category and requested_category != previous_category),
        ]
    )

    if followup["restart_requested"] or has_constraint_update:
        state["current_bracket"] = []
        state["current_round"] = None
        state["current_match_index"] = 0
        state["picks"] = []
        state["last_winner"] = None

    read_scope_label = await _build_websochat_read_scope_label(
        product_id=product_id,
        read_episode_to=state.get("read_episode_to"),
        db=db,
    )

    if not state.get("read_episode_to"):
        reply = (
            "월드컵은 읽은 범위 기준으로만 돌릴게.\n"
            "어디까지 읽었는지 말해줘. 예: 3화까지 읽었어 / 프롤로그까지 읽었어"
        )
        return reply, _set_websochat_game_state(
            normalized,
            game_mode="ideal_worldcup",
            gender_scope=gender_scope,
            category=category,
            state=state,
        )

    current_bracket = [pair for pair in state.get("current_bracket") or [] if len(pair) == 2]
    current_match_index = max(int(state.get("current_match_index") or 0), 0)
    if current_bracket and current_match_index < len(current_bracket):
        current_pair = current_bracket[current_match_index]
        if followup["meta_requested"]:
            reply = _build_websochat_worldcup_meta_reply(
                product_row=product_row,
                gender_scope=gender_scope,
                category=category,
                state=state,
                read_scope_label=read_scope_label,
                current_pair=current_pair,
            )
            return reply, _set_websochat_game_state(
                normalized,
                game_mode="ideal_worldcup",
                gender_scope=gender_scope,
                category=category,
                state=state,
            )
        chosen = _resolve_websochat_pair_choice(user_prompt, current_pair)
        if chosen is None and not followup["resume_requested"]:
            reply = (
                f"지금 매치업은 {current_pair[0]} vs {current_pair[1]}야.\n"
                "둘 중 하나만 골라줘. 이름을 그대로 말하거나 1번/2번으로 골라도 돼."
            )
            return reply, _set_websochat_game_state(
                normalized,
                game_mode="ideal_worldcup",
                gender_scope=gender_scope,
                category=category,
                state=state,
            )
        if chosen is not None:
            pair_key = _build_websochat_pair_key(current_pair[0], current_pair[1])
            state["used_pair_keys"] = _normalize_websochat_string_list(
                [*(state.get("used_pair_keys") or []), pair_key],
                limit=128,
            )
            state["picks"] = _normalize_websochat_string_list([*(state.get("picks") or []), chosen], limit=16)
            state["current_match_index"] = current_match_index + 1
            current_match_index = state["current_match_index"]

        if current_match_index < len(current_bracket):
            next_pair = current_bracket[current_match_index]
            reply = (
                f"{chosen} 선택이네.\n\n"
                f"{state.get('current_round') or '현재 라운드'}\n"
                f"{next_pair[0]} vs {next_pair[1]}\n"
                "둘 중 하나만 골라줘."
            ) if chosen else (
                f"{state.get('current_round') or '현재 라운드'}\n"
                f"{current_pair[0]} vs {current_pair[1]}\n"
                "둘 중 하나만 골라줘."
            )
            return reply, _set_websochat_game_state(
                normalized,
                game_mode="ideal_worldcup",
                gender_scope=gender_scope,
                category=category,
                state=state,
            )

        winners = _normalize_websochat_string_list(state.get("picks"), limit=8)
        if len(winners) == 1 and len(current_bracket) == 1:
            winner = winners[0]
            state["last_winner"] = winner
            state["current_bracket"] = []
            state["current_round"] = None
            state["current_match_index"] = 0
            state["picks"] = []
            reply = (
                f"우승은 {winner}.\n"
                "이번 판 결과를 보면 네 취향 축이 어느 정도 잡혔어.\n"
                "원하면 같은 세션에서 다시 이상형월드컵을 하거나, 바로 VS게임으로 넘어갈 수 있어."
            )
            return reply, _set_websochat_game_state(
                normalized,
                game_mode="ideal_worldcup",
                gender_scope=gender_scope,
                category=category,
                state=state,
            )

        next_round, round_label = _build_websochat_worldcup_round(winners, [])
        if not next_round:
            state["last_winner"] = winners[0] if winners else None
            state["current_bracket"] = []
            state["current_round"] = None
            state["current_match_index"] = 0
            state["picks"] = []
            reply = (
                f"이번 판은 여기까지 정리할게. 현재 가장 앞선 후보는 {state.get('last_winner') or '없음'}이야.\n"
                "원하면 새로 다시 돌리거나 다른 기준으로 갈 수 있어."
            )
            return reply, _set_websochat_game_state(
                normalized,
                game_mode="ideal_worldcup",
                gender_scope=gender_scope,
                category=category,
                state=state,
            )

        state["current_candidates"] = winners
        state["current_bracket"] = next_round
        state["current_round"] = round_label
        state["current_match_index"] = 0
        state["picks"] = []
        final_pair = next_round[0]
        reply = (
            f"{state.get('current_round') or round_label}\n"
            f"{final_pair[0]} vs {final_pair[1]}\n"
            "이제 결승이야. 둘 중 하나만 골라줘."
        )
        return reply, _set_websochat_game_state(
            normalized,
            game_mode="ideal_worldcup",
            gender_scope=gender_scope,
            category=category,
            state=state,
        )

    candidates = await get_websochat_game_candidate_profiles(
        product_id=int(product_row.get("productId") or 0),
        db=db,
    )
    visible_candidates = _filter_websochat_worldcup_candidates_by_read_scope(
        candidates,
        read_episode_to=int(state.get("read_episode_to") or 0),
    )
    bracket_size, bracket_reason = _resolve_websochat_worldcup_bracket_size(
        read_episode_to=int(state.get("read_episode_to") or 0),
        requested_size=int(state.get("requested_bracket_size") or 0) or None,
        stable_candidate_count=len(visible_candidates),
    )
    if bracket_size == 0:
        reply = (
            f"{read_scope_label or f'{int(state.get('read_episode_to') or 0)}화'} 기준으로는 월드컵으로 돌릴 후보가 아직 부족해.\n"
            "더 읽은 범위로 넓혀주면 다시 잡아볼게."
        )
        return reply, _set_websochat_game_state(
            normalized,
            game_mode="ideal_worldcup",
            gender_scope=gender_scope,
            category=category,
            state=state,
        )
    if bracket_reason == "2인비교권장" and not inferred_requested_size:
        if followup["confirm_requested"]:
            state["requested_bracket_size"] = 2
        else:
            reply = (
                f"{read_scope_label or f'{int(state.get('read_episode_to') or 0)}화'} 기준으로는 아직 4강을 돌리기엔 후보 풀이 좁아.\n"
                "지금은\n"
                "1. 2인 비교로 가기\n"
                "2. 더 읽은 범위로 넓히기\n"
                "중에 골라줘."
            )
            return reply, _set_websochat_game_state(
                normalized,
                game_mode="ideal_worldcup",
                gender_scope=gender_scope,
                category=category,
                state=state,
            )
    if bracket_reason in {"4강불가", "8강불가"}:
        if followup["confirm_requested"]:
            state["requested_bracket_size"] = bracket_size
        else:
            requested_label = "8강" if int(state.get("requested_bracket_size") or 0) == 8 else "4강"
            fallback_label = "4강" if bracket_size == 4 else "2인 비교"
            reply = (
                f"{read_scope_label or f'{int(state.get('read_episode_to') or 0)}화'} 기준으로는 {requested_label}을 돌릴 만큼 후보가 아직 부족해.\n"
                f"지금은 {fallback_label}까지가 자연스러워.\n"
                "1. 지금 가능한 크기로 진행하기\n"
                "2. 더 읽은 범위로 넓히기"
            )
            return reply, _set_websochat_game_state(
                normalized,
                game_mode="ideal_worldcup",
                gender_scope=gender_scope,
                category=category,
                state=state,
            )
    selected_candidates = visible_candidates[:bracket_size]
    selected_names = [item["display_name"] for item in selected_candidates]
    next_round, round_label = _build_websochat_worldcup_round(selected_names, state.get("used_pair_keys") or [])
    if not next_round:
        reply = (
            f"{read_scope_label or f'{int(state.get('read_episode_to') or 0)}화'} 기준에선 지금 바로 월드컵으로 돌릴 후보가 부족해.\n"
            "더 읽은 범위로 넓히거나, 지금은 2인 비교로 가는 쪽이 자연스러워."
        )
        return reply, _set_websochat_game_state(
            normalized,
            game_mode="ideal_worldcup",
            gender_scope=gender_scope,
            category=category,
            state=state,
        )

    state["current_candidates"] = selected_names
    state["current_bracket"] = next_round
    state["current_round"] = round_label
    state["current_match_index"] = 0
    state["picks"] = []
    first_pair = next_round[0]
    reply = (
        f"좋아. {str(product_row.get('title') or '').strip()} {gender_scope} / {category} 기준으로 갈게.\n\n"
        f"{f'읽은 범위는 {read_scope_label}까지로 잡아둘게.\\n\\n' if read_scope_label else ''}"
        f"{round_label}\n"
        f"{first_pair[0]} vs {first_pair[1]}\n"
        "둘 중 하나만 골라줘."
    )
    return reply, _set_websochat_game_state(
        normalized,
        game_mode="ideal_worldcup",
        gender_scope=gender_scope,
        category=category,
        state=state,
    )


async def _generate_websochat_vs_reply(
    *,
    session_memory: dict[str, Any],
    product_row: dict[str, Any],
    user_prompt: str,
    db: AsyncSession,
) -> tuple[str, dict[str, Any]]:
    normalized = _normalize_websochat_session_memory(session_memory)
    game_context = normalized.get("game_context") or {}
    gender_scope = str(game_context.get("gender_scope") or "").strip().lower()
    category = str(game_context.get("category") or "").strip().lower()
    match_mode = str(game_context.get("match_mode") or "").strip().lower()
    read_scope_label = await _build_websochat_read_scope_label(
        product_id=int(product_row.get("productId") or 0),
        read_episode_to=normalized.get("read_episode_to"),
        db=db,
    )
    if not gender_scope or not match_mode:
        return (
            build_websochat_game_guide_reply(
                session_memory=normalized,
                product_row=product_row,
                read_scope_label=read_scope_label,
            )
            or "",
            normalized,
        )

    inferred_category = _infer_websochat_game_category_from_prompt(user_prompt)
    effective_category = category or inferred_category or None

    state_category = effective_category or WEBSOCHAT_PENDING_GAME_CATEGORY
    state = _get_websochat_game_state(
        normalized,
        game_mode="vs_game",
        gender_scope=gender_scope,
        category=state_category,
    )
    state["mode"] = match_mode
    candidates = await get_websochat_game_candidate_profiles(
        product_id=int(product_row.get("productId") or 0),
        db=db,
    )

    if match_mode == "direct_match":
        matched_scope_keys = _extract_websochat_direct_match_scope_keys(
            user_prompt=user_prompt,
            candidates=candidates,
        )
        candidate_map = {item["scope_key"]: item for item in candidates}
        if len(matched_scope_keys) == 2:
            state["current_match"] = matched_scope_keys
        if len(state.get("current_match") or []) < 2:
            reply = (
                f"좋아. {str(product_row.get('title') or '').strip()} {gender_scope} 직접 매치업으로 갈게.\n"
                "붙여볼 두 캐릭터를 말해줘. 예: 엔데온트라 vs 펜데"
            )
            return reply, _set_websochat_game_state(
                normalized,
                game_mode="vs_game",
                gender_scope=gender_scope,
                category=state_category,
                state=state,
            )
        if not effective_category:
            reply = (
                "좋아. 이제 기준을 골라줘.\n\n"
                "1. 파워\n"
                "2. 지능\n"
                "3. 매력\n"
                "4. 멘탈\n"
                "5. 생존력\n"
                "6. 연애형\n"
                "7. 데이트형\n"
                "8. 성격형"
            )
            return reply, _set_websochat_game_state(
                normalized,
                game_mode="vs_game",
                gender_scope=gender_scope,
                category=state_category,
                state=state,
            )
        left = candidate_map.get(state["current_match"][0])
        right = candidate_map.get(state["current_match"][1])
        if not left or not right:
            state["current_match"] = []
            reply = "지금 매치업 후보를 다시 잡아야 해. 붙일 두 캐릭터를 다시 말해줘."
            return reply, _set_websochat_game_state(
                normalized,
                game_mode="vs_game",
                gender_scope=gender_scope,
                category=state_category,
                state=state,
            )
        repeated_match_key = _build_websochat_pair_key(left["display_name"], right["display_name"])
        if repeated_match_key in set(_normalize_websochat_string_list(state.get("used_match_keys"), limit=128)):
            state["current_match"] = []
            reply = (
                f"{left['display_name']} vs {right['display_name']}는 이 세션에서 이미 한번 붙였어.\n"
                "다른 두 캐릭터를 붙이거나, 다른 기준으로 가자."
            )
            return reply, _set_websochat_game_state(
                normalized,
                game_mode="vs_game",
                gender_scope=gender_scope,
                category=effective_category or state_category,
                state=state,
            )
        comparison = await generate_websochat_vs_comparison(
            product_row=product_row,
            category=effective_category or state_category,
            match_pair=[left, right],
        )
        match_key = _build_websochat_pair_key(left["display_name"], right["display_name"])
        state["used_match_keys"] = _normalize_websochat_string_list([*(state.get("used_match_keys") or []), match_key], limit=128)
        state["current_match"] = []
        state["last_result_summary"] = comparison[:200]
        return comparison, _set_websochat_game_state(
            normalized,
            game_mode="vs_game",
            gender_scope=gender_scope,
            category=effective_category or state_category,
            state=state,
        )

    if not effective_category:
        return (
            build_websochat_game_guide_reply(
                session_memory=normalized,
                product_row=product_row,
                read_scope_label=read_scope_label,
            )
            or "",
            normalized,
        )

    if effective_category:
        pending_state = _get_websochat_game_state(
            normalized,
            game_mode="vs_game",
            gender_scope=gender_scope,
            category=WEBSOCHAT_PENDING_GAME_CATEGORY,
        )
        if pending_state.get("current_match") and not state.get("current_match"):
            state["current_match"] = list(pending_state.get("current_match") or [])
            pending_state["current_match"] = []
            normalized = _set_websochat_game_state(
                normalized,
                game_mode="vs_game",
                gender_scope=gender_scope,
                category=WEBSOCHAT_PENDING_GAME_CATEGORY,
                state=pending_state,
            )

    selected_candidates = await select_websochat_game_candidates(
        product_row=product_row,
        candidates=candidates,
        game_mode="vs_game",
        gender_scope=gender_scope,
        category=effective_category,
        desired_count=4,
    )
    selected_pair = _pick_websochat_unused_pair(
        selected_candidates,
        state.get("used_match_keys") or [],
    )
    if len(selected_pair) < 2:
        reply = (
            f"{str(product_row.get('title') or '').strip()} {gender_scope} / {category} 기준으로 바로 붙일 후보가 부족해.\n"
            "다른 기준으로 바꾸거나 직접 매치업으로 가면 이어갈 수 있어."
        )
        return reply, _set_websochat_game_state(
            normalized,
            game_mode="vs_game",
            gender_scope=gender_scope,
            category=category,
            state=state,
        )
    comparison = await generate_websochat_vs_comparison(
        product_row=product_row,
        category=effective_category,
        match_pair=selected_pair,
    )
    match_key = _build_websochat_pair_key(
        selected_pair[0]["display_name"],
        selected_pair[1]["display_name"],
    )
    state["used_match_keys"] = _normalize_websochat_string_list([*(state.get("used_match_keys") or []), match_key], limit=128)
    state["current_match"] = [selected_pair[0]["scope_key"], selected_pair[1]["scope_key"]]
    state["last_result_summary"] = comparison[:200]
    return comparison, _set_websochat_game_state(
        normalized,
        game_mode="vs_game",
        gender_scope=gender_scope,
        category=effective_category,
        state=state,
    )


async def _generate_websochat_game_reply(
    *,
    session_id: int,
    session_memory: dict[str, Any],
    product_row: dict[str, Any],
    user_prompt: str,
    db: AsyncSession,
) -> tuple[str, str, str, bool, str, dict[str, Any]]:
    normalized = _normalize_websochat_session_memory(session_memory)
    dispatch_plan = build_websochat_game_dispatch_plan(normalized)
    if dispatch_plan["route"] == "guide":
        game_context = normalized.get("game_context") or {}
        active_game_mode = str(game_context.get("mode") or "").strip().lower()
        read_scope_label = await _build_websochat_read_scope_label(
            product_id=int(product_row.get("productId") or 0),
            read_episode_to=normalized.get("read_episode_to"),
            db=db,
        )
        if active_game_mode == "ideal_worldcup":
            followup = resolve_websochat_worldcup_followup(user_prompt=user_prompt)
            if followup["exit_requested"]:
                reply = "좋아요. 월드컵은 여기서 잠깐 쉬고, 다시 작품 얘기로 돌아가볼게요."
                return (
                    reply,
                    dispatch_plan["model_used"],
                    dispatch_plan["route_mode"],
                    False,
                    dispatch_plan["intent"],
                    _clear_websochat_game_context(normalized),
                )
            if followup["meta_requested"]:
                reply = _build_websochat_worldcup_setup_meta_reply(
                    product_row=product_row,
                    gender_scope=game_context.get("gender_scope"),
                    category=game_context.get("category"),
                    read_scope_label=read_scope_label,
                )
                return (
                    reply,
                    dispatch_plan["model_used"],
                    dispatch_plan["route_mode"],
                    False,
                    dispatch_plan["intent"],
                    normalized,
                )
            if not has_websochat_worldcup_followup_signal(
                user_prompt=user_prompt,
                followup=followup,
            ):
                cleared_memory = _clear_websochat_game_context(normalized)
                return await _generate_websochat_reply(
                    session_id=session_id,
                    session_memory=cleared_memory,
                    product_row=product_row,
                    user_prompt=user_prompt,
                    user_id=None,
                    db=db,
                )
        guide = (
            build_websochat_game_guide_reply(
                session_memory=normalized,
                product_row=product_row,
                read_scope_label=read_scope_label,
            )
            or ""
        )
        return guide, dispatch_plan["model_used"], dispatch_plan["route_mode"], False, dispatch_plan["intent"], normalized
    if dispatch_plan["route"] == "ideal_worldcup":
        game_context = normalized.get("game_context") or {}
        active_gender_scope = str(game_context.get("gender_scope") or "").strip().lower()
        active_category = str(game_context.get("category") or "").strip().lower()
        if not active_gender_scope or not active_category:
            read_scope_label = await _build_websochat_read_scope_label(
                product_id=int(product_row.get("productId") or 0),
                read_episode_to=normalized.get("read_episode_to"),
                db=db,
            )
            followup = resolve_websochat_worldcup_followup(user_prompt=user_prompt)
            if followup["exit_requested"]:
                reply = "좋아요. 월드컵은 여기서 잠깐 쉬고, 다시 작품 얘기로 돌아가볼게요."
                return (
                    reply,
                    dispatch_plan["model_used"],
                    dispatch_plan["route_mode"],
                    False,
                    dispatch_plan["intent"],
                    _clear_websochat_game_context(normalized),
                )
            if followup["meta_requested"]:
                reply = _build_websochat_worldcup_setup_meta_reply(
                    product_row=product_row,
                    gender_scope=active_gender_scope or None,
                    category=active_category or None,
                    read_scope_label=read_scope_label,
                )
                return (
                    reply,
                    dispatch_plan["model_used"],
                    dispatch_plan["route_mode"],
                    False,
                    dispatch_plan["intent"],
                    normalized,
                )
            if not has_websochat_worldcup_followup_signal(
                user_prompt=user_prompt,
                followup=followup,
            ):
                cleared_memory = _clear_websochat_game_context(normalized)
                return await _generate_websochat_reply(
                    session_id=session_id,
                    session_memory=cleared_memory,
                    product_row=product_row,
                    user_prompt=user_prompt,
                    user_id=None,
                    db=db,
                )
        reply, next_memory = await _generate_websochat_worldcup_reply(
            session_memory=normalized,
            product_row=product_row,
            user_prompt=user_prompt,
            db=db,
        )
        return reply, dispatch_plan["model_used"], dispatch_plan["route_mode"], False, dispatch_plan["intent"], next_memory
    reply = build_websochat_vs_disabled_reply()
    return reply, dispatch_plan["model_used"], dispatch_plan["route_mode"], False, dispatch_plan["intent"], _clear_websochat_game_context(normalized)


def _normalize_websochat_character_name(value: str) -> str:
    normalized = re.sub(r"\s+", "", str(value or "")).strip().lower()
    return normalized


def _is_websochat_protagonist_direct_alias(normalized_name: str) -> bool:
    return normalized_name in {"주인공"}


def _is_websochat_first_person_protagonist_alias(normalized_name: str) -> bool:
    return normalized_name in {"나", "내가"}


def _rank_websochat_protagonist_inventory_row(row: dict[str, Any]) -> tuple[int, int, int, int]:
    payload = dict(row.get("payload") or {})
    return (
        1 if bool(payload.get("is_first_person")) else 0,
        int(payload.get("distinct_episode_count") or 0),
        int(payload.get("latest_seen_episode_no") or 0),
        int(payload.get("voice_evidence_count") or 0),
    )


def _pick_websochat_dominant_protagonist_inventory_row(
    protagonist_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not protagonist_rows:
        return None
    ordered_rows = sorted(
        protagonist_rows,
        key=_rank_websochat_protagonist_inventory_row,
        reverse=True,
    )
    top_row = ordered_rows[0]
    top_payload = dict(top_row.get("payload") or {})
    top_distinct_episode_count = int(top_payload.get("distinct_episode_count") or 0)
    top_voice_evidence_count = int(top_payload.get("voice_evidence_count") or 0)
    if top_distinct_episode_count <= 0 or top_voice_evidence_count <= 0:
        return None
    if len(ordered_rows) == 1:
        return top_row if top_distinct_episode_count >= 2 else None
    second_row = ordered_rows[1]
    second_payload = dict(second_row.get("payload") or {})
    second_distinct_episode_count = int(second_payload.get("distinct_episode_count") or 0)
    second_voice_evidence_count = int(second_payload.get("voice_evidence_count") or 0)
    if top_distinct_episode_count < max(3, second_distinct_episode_count * 2):
        return None
    if top_voice_evidence_count < max(1, second_voice_evidence_count):
        return None
    return top_row


def _merge_websochat_ordered_texts(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            merged.append(text)
    return merged


def _websochat_presence_rank(value: str) -> int:
    normalized = str(value or "").strip().lower()
    if normalized == "high":
        return 3
    if normalized == "medium":
        return 2
    if normalized == "low":
        return 1
    return 0


def _extract_websochat_protagonist_candidate_names(
    *,
    scope_key: str,
    payload: dict[str, Any],
) -> set[str]:
    candidate_names: list[str] = []
    display_name = str(payload.get("display_name") or "").strip()
    if display_name:
        candidate_names.append(display_name)
    for alias in payload.get("aliases") or []:
        alias_text = str(alias or "").strip()
        if alias_text:
            candidate_names.append(alias_text)
    if scope_key.startswith("protagonist:named:"):
        scope_tail = scope_key.split(":")[-1].strip()
        if scope_tail:
            candidate_names.append(scope_tail)
    return {
        _normalize_websochat_character_name(name)
        for name in candidate_names
        if str(name or "").strip()
    }


def _build_websochat_protagonist_cluster(
    *,
    seed_scope_key: str,
    protagonist_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows_by_scope = {
        str(row.get("scopeKey") or "").strip(): row
        for row in protagonist_rows
        if str(row.get("scopeKey") or "").strip()
    }
    if seed_scope_key not in rows_by_scope:
        return []
    names_by_scope = {
        scope_key: _extract_websochat_protagonist_candidate_names(
            scope_key=scope_key,
            payload=dict(row.get("payload") or {}),
        )
        for scope_key, row in rows_by_scope.items()
    }
    cluster_scope_keys: set[str] = set()
    pending_scope_keys: list[str] = [seed_scope_key]
    while pending_scope_keys:
        current_scope_key = pending_scope_keys.pop()
        if current_scope_key in cluster_scope_keys:
            continue
        cluster_scope_keys.add(current_scope_key)
        current_names = names_by_scope.get(current_scope_key) or set()
        if not current_names:
            continue
        for candidate_scope_key, candidate_names in names_by_scope.items():
            if candidate_scope_key in cluster_scope_keys:
                continue
            if current_names & candidate_names:
                pending_scope_keys.append(candidate_scope_key)
    ordered_rows = sorted(
        [rows_by_scope[scope_key] for scope_key in cluster_scope_keys],
        key=lambda row: (
            1 if str(row.get("scopeKey") or "").strip() == seed_scope_key else 0,
            *_rank_websochat_protagonist_inventory_row(row),
        ),
        reverse=True,
    )
    return ordered_rows


def _merge_websochat_protagonist_inventory_payload(cluster_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not cluster_rows:
        return {}
    primary_row = max(cluster_rows, key=_rank_websochat_protagonist_inventory_row)
    primary_payload = dict(primary_row.get("payload") or {})
    evidence_episode_nos = sorted(
        {
            int(episode_no or 0)
            for row in cluster_rows
            for episode_no in (dict(row.get("payload") or {}).get("evidence_episode_nos") or [])
            if int(episode_no or 0) > 0
        }
    )
    merged_aliases = _merge_websochat_ordered_texts(
        [str(item).strip() for item in (primary_payload.get("aliases") or []) if str(item).strip()],
        *[
            [str(item).strip() for item in (dict(row.get("payload") or {}).get("aliases") or []) if str(item).strip()]
            for row in cluster_rows
            if row is not primary_row
        ],
    )
    merged_action_tags = _merge_websochat_ordered_texts(
        [str(item).strip() for item in (primary_payload.get("dominant_action_tags") or []) if str(item).strip()],
        *[
            [str(item).strip() for item in (dict(row.get("payload") or {}).get("dominant_action_tags") or []) if str(item).strip()]
            for row in cluster_rows
            if row is not primary_row
        ],
    )
    merged_affect_tags = _merge_websochat_ordered_texts(
        [str(item).strip() for item in (primary_payload.get("dominant_affect_tags") or []) if str(item).strip()],
        *[
            [str(item).strip() for item in (dict(row.get("payload") or {}).get("dominant_affect_tags") or []) if str(item).strip()]
            for row in cluster_rows
            if row is not primary_row
        ],
    )
    return {
        **primary_payload,
        "scope_keys": [str(row.get("scopeKey") or "").strip() for row in cluster_rows if str(row.get("scopeKey") or "").strip()],
        "aliases": merged_aliases,
        "evidence_episode_nos": evidence_episode_nos,
        "distinct_episode_count": max(
            len(evidence_episode_nos),
            max(int(dict(row.get("payload") or {}).get("distinct_episode_count") or 0) for row in cluster_rows),
        ),
        "summary_mention_count": sum(int(dict(row.get("payload") or {}).get("summary_mention_count") or 0) for row in cluster_rows),
        "voice_evidence_count": sum(int(dict(row.get("payload") or {}).get("voice_evidence_count") or 0) for row in cluster_rows),
        "relation_episode_count": max(int(dict(row.get("payload") or {}).get("relation_episode_count") or 0) for row in cluster_rows),
        "first_seen_episode_no": min(
            (
                int(dict(row.get("payload") or {}).get("first_seen_episode_no") or 0)
                for row in cluster_rows
                if int(dict(row.get("payload") or {}).get("first_seen_episode_no") or 0) > 0
            ),
            default=0,
        ),
        "latest_seen_episode_no": max(int(dict(row.get("payload") or {}).get("latest_seen_episode_no") or 0) for row in cluster_rows),
        "dominant_action_tags": merged_action_tags,
        "dominant_affect_tags": merged_affect_tags,
        "is_first_person": any(bool(dict(row.get("payload") or {}).get("is_first_person")) for row in cluster_rows),
        "action_presence": max(
            (
                str(dict(row.get("payload") or {}).get("action_presence") or "").strip()
                for row in cluster_rows
            ),
            key=_websochat_presence_rank,
            default="",
        ),
        "relation_presence": max(
            (
                str(dict(row.get("payload") or {}).get("relation_presence") or "").strip()
                for row in cluster_rows
            ),
            key=_websochat_presence_rank,
            default="",
        ),
    }


def _build_websochat_fallback_protagonist_profile(
    *,
    scope_key: str,
    inventory_payload: dict[str, Any],
) -> dict[str, Any]:
    return _build_websochat_fallback_character_profile(
        scope_key=scope_key,
        inventory_payload=inventory_payload,
    )


def _build_websochat_fallback_character_profile(
    *,
    scope_key: str,
    inventory_payload: dict[str, Any],
) -> dict[str, Any]:
    display_name = str(inventory_payload.get("display_name") or scope_key).strip() or scope_key
    affect_tags = [
        str(item).strip()
        for item in (inventory_payload.get("dominant_affect_tags") or [])
        if str(item).strip()
    ]
    action_tags = [
        str(item).strip()
        for item in (inventory_payload.get("dominant_action_tags") or [])
        if str(item).strip()
    ]
    baseline_parts = affect_tags[:2] or action_tags[:2]
    return {
        "display_name": display_name,
        "aliases": [
            str(item).strip()
            for item in (inventory_payload.get("aliases") or [])
            if str(item).strip()
        ],
        "speech_style": {},
        "personality_core": (affect_tags[:3] + action_tags[:2])[:4],
        "baseline_attitude": ", ".join(baseline_parts),
    }


def _is_websochat_inventory_rp_eligible(
    payload: dict[str, Any] | None,
) -> bool:
    if not isinstance(payload, dict) or not payload:
        return False
    entity_kind = str(payload.get("entity_kind") or "").strip().lower()
    if entity_kind and entity_kind != "person":
        return False
    display_name = str(payload.get("display_name") or "").strip()
    if len(display_name) < 2:
        return False
    distinct_episode_count = int(payload.get("distinct_episode_count") or 0)
    voice_evidence_count = int(payload.get("voice_evidence_count") or 0)
    summary_mention_count = int(payload.get("summary_mention_count") or 0)
    return voice_evidence_count >= 2 or (distinct_episode_count >= 2 and summary_mention_count >= 3)


async def _load_websochat_protagonist_inventory_rows(
    *,
    product_id: int,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            """
            SELECT scope_key AS scopeKey, summary_text AS summaryText
            FROM tb_story_agent_context_summary
            WHERE product_id = :product_id
              AND summary_type = 'character_inventory'
              AND is_active = 'Y'
            ORDER BY summary_id DESC
            """
        ),
        {"product_id": product_id},
    )
    protagonist_rows: list[dict[str, Any]] = []
    for row in result.mappings().all():
        scope_key = str(row.get("scopeKey") or "").strip()
        if not scope_key.startswith("protagonist:"):
            continue
        payload = _extract_websochat_json_object(str(row.get("summaryText") or "")) or {}
        protagonist_rows.append(
            {
                "scopeKey": scope_key,
                "payload": payload,
            }
        )
    return protagonist_rows


async def _resolve_websochat_protagonist_scope_key(
    *,
    product_id: int,
    raw_value: str,
    db: AsyncSession,
) -> dict[str, Any]:
    target_name = _normalize_websochat_character_name(raw_value)
    protagonist_rows = await _load_websochat_protagonist_inventory_rows(product_id=product_id, db=db)
    if not protagonist_rows:
        return {
            "scopeKey": None,
            "protagonistIntent": False,
            "resolutionSource": "none",
            "candidateCount": 0,
        }

    matched_inventory_rows: list[dict[str, Any]] = []
    for row in protagonist_rows:
        payload = dict(row.get("payload") or {})
        is_first_person = bool(payload.get("is_first_person"))
        candidate_names = [row.get("scopeKey")]
        display_name = str(payload.get("display_name") or "").strip()
        if display_name:
            candidate_names.append(display_name)
        for alias in payload.get("aliases") or []:
            alias_text = str(alias or "").strip()
            if alias_text:
                candidate_names.append(alias_text)
        normalized_candidates = {
            _normalize_websochat_character_name(name)
            for name in candidate_names
            if str(name or "").strip()
        }
        protagonist_intent = False
        if _is_websochat_protagonist_direct_alias(target_name):
            protagonist_intent = True
        elif is_first_person and _is_websochat_first_person_protagonist_alias(target_name):
            protagonist_intent = True
        elif target_name in normalized_candidates:
            protagonist_intent = True
        if protagonist_intent:
            matched_inventory_rows.append({
                "scopeKey": str(row.get("scopeKey") or "").strip(),
                "payload": payload,
            })

    if not matched_inventory_rows:
        if _is_websochat_first_person_protagonist_alias(target_name):
            dominant_inventory_row = _pick_websochat_dominant_protagonist_inventory_row(
                protagonist_rows,
            )
            if dominant_inventory_row:
                return {
                    "scopeKey": str(dominant_inventory_row.get("scopeKey") or "").strip() or None,
                    "protagonistIntent": True,
                    "resolutionSource": "protagonist_inventory_dominant",
                    "candidateCount": len(protagonist_rows),
                }
        return {
            "scopeKey": None,
            "protagonistIntent": False,
            "resolutionSource": "none",
            "candidateCount": 0,
        }

    rp_result = await db.execute(
        text(
            """
            SELECT scope_key AS scopeKey, summary_text AS summaryText
            FROM tb_story_agent_context_summary
            WHERE product_id = :product_id
              AND summary_type = 'character_rp_profile'
              AND is_active = 'Y'
            ORDER BY summary_id DESC
            """
        ),
        {"product_id": product_id},
    )
    rp_rows = [dict(row) for row in rp_result.mappings().all()]

    matched_scope_keys: list[str] = []
    inventory_scope_keys = {str(item.get("scopeKey") or "").strip() for item in matched_inventory_rows if str(item.get("scopeKey") or "").strip()}
    for scope_key in inventory_scope_keys:
        if any(str(row.get("scopeKey") or "").strip() == scope_key for row in rp_rows):
            matched_scope_keys.append(scope_key)

    if not matched_scope_keys:
        for inventory_row in matched_inventory_rows:
            payload = dict(inventory_row.get("payload") or {})
            candidate_names = [inventory_row.get("scopeKey")]
            display_name = str(payload.get("display_name") or "").strip()
            if display_name:
                candidate_names.append(display_name)
            for alias in payload.get("aliases") or []:
                alias_text = str(alias or "").strip()
                if alias_text:
                    candidate_names.append(alias_text)
            normalized_candidates = {
                _normalize_websochat_character_name(name)
                for name in candidate_names
                if str(name or "").strip()
            }
            for row in rp_rows:
                scope_key = str(row.get("scopeKey") or "").strip()
                if not scope_key:
                    continue
                payload = _extract_websochat_json_object(str(row.get("summaryText") or "")) or {}
                rp_names = [scope_key]
                display_name = str(payload.get("display_name") or "").strip()
                if display_name:
                    rp_names.append(display_name)
                for alias in payload.get("aliases") or []:
                    alias_text = str(alias or "").strip()
                    if alias_text:
                        rp_names.append(alias_text)
                normalized_rp_names = {
                    _normalize_websochat_character_name(name)
                    for name in rp_names
                    if str(name or "").strip()
                }
                if normalized_candidates & normalized_rp_names:
                    matched_scope_keys.append(scope_key)

    unique_scope_keys = sorted(set(matched_scope_keys))
    if len(unique_scope_keys) == 1:
        return {
            "scopeKey": unique_scope_keys[0],
            "protagonistIntent": True,
            "resolutionSource": "protagonist_profile",
            "candidateCount": len(matched_inventory_rows),
        }
    if len(unique_scope_keys) > 1:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="주인공으로 잡히는 RP 캐릭터가 여러 명이라 누구와 대화할지 더 구체적으로 말해줘.",
        )
    best_inventory_row = max(
        matched_inventory_rows,
        key=_rank_websochat_protagonist_inventory_row,
    )
    best_scope_key = str(best_inventory_row.get("scopeKey") or "").strip()
    return {
        "scopeKey": best_scope_key or None,
        "protagonistIntent": True,
        "resolutionSource": "protagonist_inventory",
        "candidateCount": len(matched_inventory_rows),
    }


async def _get_websochat_exact_summary_row(
    *,
    product_id: int,
    summary_type: str,
    scope_key: str,
    db: AsyncSession,
) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT
                summary_id AS summaryId,
                summary_text AS summaryText,
                episode_from AS episodeFrom,
                episode_to AS episodeTo
            FROM tb_story_agent_context_summary
            WHERE product_id = :product_id
              AND summary_type = :summary_type
              AND scope_key = :scope_key
              AND is_active = 'Y'
            ORDER BY summary_id DESC
            LIMIT 1
            """
        ),
        {
            "product_id": product_id,
            "summary_type": summary_type,
            "scope_key": scope_key,
        },
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else None


async def _get_websochat_first_available_summary_row(
    *,
    product_id: int,
    summary_type: str,
    scope_keys: list[str],
    db: AsyncSession,
) -> dict[str, Any] | None:
    for scope_key in scope_keys:
        normalized_scope_key = str(scope_key or "").strip()
        if not normalized_scope_key:
            continue
        row = await _get_websochat_exact_summary_row(
            product_id=product_id,
            summary_type=summary_type,
            scope_key=normalized_scope_key,
            db=db,
        )
        if row:
            return row
    return None


async def _build_websochat_rp_trajectory_context(
    *,
    product_id: int,
    latest_episode_no: int,
    read_episode_to: int,
    active_character_scope_key: str,
    profile: dict[str, Any],
    examples: list[dict[str, Any]],
    db: AsyncSession,
) -> dict[str, Any]:
    upper_episode_no = min(
        int(read_episode_to or 0) if int(read_episode_to or 0) > 0 else int(latest_episode_no or 0),
        int(latest_episode_no or 0),
    )
    if upper_episode_no <= 0 or not active_character_scope_key:
        return {}

    candidate_names: list[str] = []
    display_name = str(profile.get("display_name") or "").strip()
    if display_name:
        candidate_names.append(display_name)
    for alias in profile.get("aliases") or []:
        alias_text = str(alias or "").strip()
        if alias_text:
            candidate_names.append(alias_text)
    scope_tail = active_character_scope_key.split(":")[-1].strip()
    if scope_tail:
        candidate_names.append(scope_tail)
    normalized_names: list[str] = []
    seen_names: set[str] = set()
    for name in candidate_names:
        if len(name) < 2:
            continue
        normalized_name = _normalize_websochat_character_name(name)
        if normalized_name in seen_names:
            continue
        seen_names.add(normalized_name)
        normalized_names.append(name)

    example_episode_nos = sorted(
        {
            int(item.get("episode_no") or 0)
            for item in examples
            if int(item.get("episode_no") or 0) > 0 and int(item.get("episode_no") or 0) <= upper_episode_no
        },
        reverse=True,
    )

    summary_candidate_rows: list[dict[str, Any]] = []
    if normalized_names:
        query_text = " ".join(normalized_names[:5])
        keywords = _extract_websochat_keywords(query_text)
        latest_rows = await _get_websochat_summary_candidates(
            product_id=product_id,
            keywords=keywords,
            query_text=query_text,
            latest_episode_no=upper_episode_no,
            mode="latest",
            episode_no=None,
            db=db,
        )
        general_rows = await _get_websochat_summary_candidates(
            product_id=product_id,
            keywords=keywords,
            query_text=query_text,
            latest_episode_no=upper_episode_no,
            mode="general",
            episode_no=None,
            db=db,
        )
        summary_candidate_rows = _merge_websochat_summary_rows(
            latest_rows[:4],
            general_rows[:4],
            limit=6,
        )

    summary_rows_by_episode: dict[int, dict[str, Any]] = {}
    for row in summary_candidate_rows:
        episode_no = int(row.get("episodeTo") or row.get("episodeFrom") or 0)
        if episode_no <= 0:
            continue
        summary_rows_by_episode.setdefault(episode_no, row)

    named_summary_rows: list[dict[str, Any]] = []
    if normalized_names:
        for row in summary_candidate_rows:
            summary_text = str(row.get("summaryText") or "").strip()
            if not summary_text:
                continue
            if any(name in summary_text for name in normalized_names):
                named_summary_rows.append(row)

    anchor_row: dict[str, Any] | None = None
    for episode_no in example_episode_nos:
        anchor_row = summary_rows_by_episode.get(episode_no)
        if anchor_row:
            break
        summary_rows = await _get_websochat_summary_candidates(
            product_id=product_id,
            keywords=[],
            query_text=f"{episode_no}화",
            latest_episode_no=upper_episode_no,
            mode="exact",
            episode_no=episode_no,
            db=db,
        )
        if summary_rows:
            anchor_row = summary_rows[0]
            break

    if not anchor_row and named_summary_rows:
        anchor_row = max(
            named_summary_rows,
            key=lambda row: int(row.get("episodeTo") or row.get("episodeFrom") or 0),
        )
    if not anchor_row and summary_candidate_rows:
        anchor_row = summary_candidate_rows[0]
    if not anchor_row:
        return {}

    anchor_episode_no = int(anchor_row.get("episodeTo") or anchor_row.get("episodeFrom") or 0)
    anchor_summary_text = str(anchor_row.get("summaryText") or "").strip()[:600]
    if anchor_episode_no <= 0 or not anchor_summary_text:
        return {}

    trajectory_history: list[dict[str, Any]] = []
    seen_history_episodes: set[int] = {anchor_episode_no}
    for row in named_summary_rows:
        episode_no = int(row.get("episodeTo") or row.get("episodeFrom") or 0)
        if episode_no <= 0 or episode_no in seen_history_episodes:
            continue
        summary_text = str(row.get("summaryText") or "").strip()
        if not summary_text:
            continue
        seen_history_episodes.add(episode_no)
        trajectory_history.append(
            {
                "episode_no": episode_no,
                "summary_text": summary_text[:400],
            }
        )
        if len(trajectory_history) >= 2:
            break

    return {
        "anchor_episode_no": anchor_episode_no,
        "anchor_summary_text": anchor_summary_text,
        "trajectory_history": trajectory_history,
    }


async def _resolve_websochat_active_character_scope_key(
    *,
    product_id: int,
    active_character: str | None,
    db: AsyncSession,
) -> str | None:
    resolution = await _resolve_websochat_active_character_resolution(
        product_id=product_id,
        active_character=active_character,
        db=db,
    )
    return str(resolution.get("scopeKey") or "").strip() or None


async def _resolve_websochat_active_character_resolution(
    *,
    product_id: int,
    active_character: str | None,
    db: AsyncSession,
) -> dict[str, Any]:
    raw_value = str(active_character or "").strip()
    if not raw_value:
        return {
            "scopeKey": None,
            "resolutionSource": "none",
            "protagonistIntent": False,
            "candidateCount": 0,
        }
    if ":" in raw_value:
        return {
            "scopeKey": raw_value,
            "resolutionSource": "explicit_scope",
            "protagonistIntent": False,
            "candidateCount": 1,
        }

    protagonist_resolution = await _resolve_websochat_protagonist_scope_key(
        product_id=product_id,
        raw_value=raw_value,
        db=db,
    )
    protagonist_scope_key = str(protagonist_resolution.get("scopeKey") or "").strip()
    protagonist_intent = bool(protagonist_resolution.get("protagonistIntent"))
    if protagonist_scope_key:
        return protagonist_resolution
    if protagonist_intent:
        return {
            **protagonist_resolution,
            "resolutionSource": "clarify_protagonist",
        }

    inventory_result = await db.execute(
        text(
            """
            SELECT scope_key AS scopeKey, summary_text AS summaryText
            FROM tb_story_agent_context_summary
            WHERE product_id = :product_id
              AND summary_type = 'character_inventory'
              AND is_active = 'Y'
            ORDER BY summary_id DESC
            """
        ),
        {"product_id": product_id},
    )
    target_name = _normalize_websochat_character_name(raw_value)
    matched_inventory_scope_keys: list[str] = []
    for row in inventory_result.mappings().all():
        scope_key = str(row.get("scopeKey") or "").strip()
        if not scope_key:
            continue
        payload = _extract_websochat_json_object(str(row.get("summaryText") or "")) or {}
        if not _is_websochat_inventory_rp_eligible(payload):
            continue
        candidate_names = [scope_key]
        display_name = str(payload.get("display_name") or "").strip()
        if display_name:
            candidate_names.append(display_name)
        for alias in payload.get("aliases") or []:
            alias_text = str(alias or "").strip()
            if alias_text:
                candidate_names.append(alias_text)
        if any(_normalize_websochat_character_name(name) == target_name for name in candidate_names if str(name).strip()):
            matched_inventory_scope_keys.append(scope_key)

    unique_inventory_scope_keys = sorted(set(matched_inventory_scope_keys))
    if len(unique_inventory_scope_keys) == 1:
        return {
            "scopeKey": unique_inventory_scope_keys[0],
            "resolutionSource": "inventory_alias",
            "protagonistIntent": False,
            "candidateCount": len(unique_inventory_scope_keys),
        }
    if len(unique_inventory_scope_keys) > 1:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="같은 이름으로 여러 인물이 잡혀서 누구와 대화할지 정하기 어렵습니다. 캐릭터를 더 구체적으로 지정해주세요.",
        )

    result = await db.execute(
        text(
            """
            SELECT scope_key AS scopeKey, summary_text AS summaryText
            FROM tb_story_agent_context_summary
            WHERE product_id = :product_id
              AND summary_type = 'character_rp_profile'
              AND is_active = 'Y'
            ORDER BY summary_id DESC
            """
        ),
        {"product_id": product_id},
    )
    target_name = _normalize_websochat_character_name(raw_value)
    matched_scope_keys: list[str] = []
    for row in result.mappings().all():
        scope_key = str(row.get("scopeKey") or "").strip()
        if not scope_key:
            continue
        payload = _extract_websochat_json_object(str(row.get("summaryText") or "")) or {}
        candidate_names = [scope_key]
        display_name = str(payload.get("display_name") or "").strip()
        if display_name:
            candidate_names.append(display_name)
        for alias in payload.get("aliases") or []:
            alias_text = str(alias or "").strip()
            if alias_text:
                candidate_names.append(alias_text)
        if any(_normalize_websochat_character_name(name) == target_name for name in candidate_names if str(name).strip()):
            matched_scope_keys.append(scope_key)

    unique_scope_keys = sorted(set(matched_scope_keys))
    if not unique_scope_keys:
        return {
            "scopeKey": None,
            "resolutionSource": "none",
            "protagonistIntent": False,
            "candidateCount": 0,
        }
    if len(unique_scope_keys) > 1:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="같은 이름으로 여러 RP 캐릭터가 잡혀서 누구와 대화할지 정하기 어렵습니다. 캐릭터를 더 구체적으로 지정해주세요.",
        )
    return {
        "scopeKey": unique_scope_keys[0],
        "resolutionSource": "profile_alias",
        "protagonistIntent": False,
        "candidateCount": len(unique_scope_keys),
    }


async def _load_websochat_rp_context(
    *,
    product_row: dict[str, Any],
    session_memory: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any] | None:
    normalized_memory = _normalize_websochat_session_memory(session_memory)
    active_character = str(normalized_memory.get("active_character") or "").strip()
    rp_mode = str(normalized_memory.get("rp_mode") or "").strip().lower()
    if not active_character or rp_mode not in WEBSOCHAT_ALLOWED_RP_MODES:
        return None

    product_id = int(product_row.get("productId") or 0)
    resolution = await _resolve_websochat_active_character_resolution(
        product_id=product_id,
        active_character=active_character,
        db=db,
    )
    resolved_active_character = str(resolution.get("scopeKey") or "").strip()
    if not resolved_active_character:
        return None
    protagonist_cluster_rows: list[dict[str, Any]] = []
    cluster_scope_keys: list[str] = [resolved_active_character]
    if resolved_active_character.startswith("protagonist:"):
        protagonist_rows = await _load_websochat_protagonist_inventory_rows(
            product_id=product_id,
            db=db,
        )
        protagonist_cluster_rows = _build_websochat_protagonist_cluster(
            seed_scope_key=resolved_active_character,
            protagonist_rows=protagonist_rows,
        )
        cluster_scope_keys = [
            str(row.get("scopeKey") or "").strip()
            for row in protagonist_cluster_rows
            if str(row.get("scopeKey") or "").strip()
        ] or [resolved_active_character]
    profile_row = await _get_websochat_first_available_summary_row(
        product_id=product_id,
        summary_type="character_rp_profile",
        scope_keys=cluster_scope_keys,
        db=db,
    )
    examples_row = await _get_websochat_first_available_summary_row(
        product_id=product_id,
        summary_type="character_rp_examples",
        scope_keys=cluster_scope_keys,
        db=db,
    )
    inventory_row = await _get_websochat_first_available_summary_row(
        product_id=product_id,
        summary_type="character_inventory",
        scope_keys=cluster_scope_keys,
        db=db,
    )
    profile = _extract_websochat_json_object(str((profile_row or {}).get("summaryText") or ""))
    examples_payload = _extract_websochat_json_object(str((examples_row or {}).get("summaryText") or ""))
    inventory_payload = _extract_websochat_json_object(str((inventory_row or {}).get("summaryText") or ""))
    if protagonist_cluster_rows:
        merged_inventory_payload = _merge_websochat_protagonist_inventory_payload(protagonist_cluster_rows)
        if merged_inventory_payload:
            inventory_payload = merged_inventory_payload
    inventory_is_protagonist = bool((inventory_payload or {}).get("is_protagonist"))
    inventory_rp_eligible = _is_websochat_inventory_rp_eligible(inventory_payload)
    fallback_used = False
    if inventory_is_protagonist and not profile:
        profile = _build_websochat_fallback_protagonist_profile(
            scope_key=resolved_active_character,
            inventory_payload=inventory_payload or {},
        )
        fallback_used = True
    if inventory_is_protagonist and not examples_payload:
        examples_payload = {"examples": []}
        fallback_used = True
    if not inventory_is_protagonist and inventory_rp_eligible and not profile:
        profile = _build_websochat_fallback_character_profile(
            scope_key=resolved_active_character,
            inventory_payload=inventory_payload or {},
        )
        fallback_used = True
    if not inventory_is_protagonist and inventory_rp_eligible and examples_payload is None:
        examples_payload = {"examples": []}
        fallback_used = True
    if not profile or examples_payload is None:
        return None

    logger.info(
        "websochat rp_resolution product_id=%s raw=%s resolved=%s resolution_source=%s protagonist_intent=%s cluster_size=%s fallback_used=%s",
        product_id,
        active_character,
        resolved_active_character,
        str(resolution.get("resolutionSource") or "none"),
        bool(resolution.get("protagonistIntent")),
        len(cluster_scope_keys),
        fallback_used,
    )

    context: dict[str, Any] = {
        "active_character": resolved_active_character,
        "rp_mode": rp_mode,
        "display_name": str(profile.get("display_name") or resolved_active_character).strip(),
        "speech_style": profile.get("speech_style") or {},
        "personality_core": profile.get("personality_core") or [],
        "baseline_attitude": str(profile.get("baseline_attitude") or "").strip(),
        "examples": list(examples_payload.get("examples") or []),
        "inventory": inventory_payload or {},
        "session_memory": normalized_memory,
    }

    trajectory_context = await _build_websochat_rp_trajectory_context(
        product_id=product_id,
        latest_episode_no=int(product_row.get("latestEpisodeNo") or 0),
        read_episode_to=int(normalized_memory.get("read_episode_to") or 0),
        active_character_scope_key=resolved_active_character,
        profile=profile,
        examples=list(examples_payload.get("examples") or []),
        db=db,
    )
    if trajectory_context:
        context.update(trajectory_context)

    if rp_mode == "scene":
        scene_episode_no = int(normalized_memory.get("scene_episode_no") or 0) or None
        if scene_episode_no:
            summary_rows = await _get_websochat_summary_candidates(
                product_id=product_id,
                keywords=[],
                query_text=f"{scene_episode_no}화",
                latest_episode_no=int(product_row.get("latestEpisodeNo") or 0),
                mode="exact",
                episode_no=scene_episode_no,
                db=db,
            )
            scene_summary_text = str((summary_rows[0] if summary_rows else {}).get("summaryText") or "").strip()
            episode_rows = await _get_websochat_episode_contents(
                product_id=product_id,
                episode_from=scene_episode_no,
                episode_to=scene_episode_no,
                latest_episode_no=int(product_row.get("latestEpisodeNo") or 0),
                db=db,
            )
            scene_source_text = "\n".join(
                str(row.get("content") or "").strip()
                for row in episode_rows[:1]
                if str(row.get("content") or "").strip()
            )[:WEBSOCHAT_PREFETCH_CONTEXT_CHARS]
            context["scene_episode_no"] = scene_episode_no
            context["scene_summary_text"] = scene_summary_text
            context["scene_source_text"] = scene_source_text
            context["scene_state"] = scene_summary_text.split("\n", 1)[0] if scene_summary_text else ""
    return context


async def _build_websochat_rp_session_state(
    *,
    product_row: dict[str, Any],
    session_memory: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    rp_stage = _resolve_websochat_rp_stage(session_memory)
    if rp_stage not in WEBSOCHAT_ALLOWED_RP_STAGES:
        rp_stage = "idle"
    active_character_label = _resolve_websochat_active_character_label(session_memory)
    if rp_stage == "chatting":
        rp_context = await _load_websochat_rp_context(
            product_row=product_row,
            session_memory=session_memory,
            db=db,
        )
        active_character_label = (
            str((rp_context or {}).get("display_name") or "").strip()
            or active_character_label
        )
    return {
        "rpStage": rp_stage,
        "rpActiveCharacterLabel": active_character_label,
    }


async def _resolve_websochat_reference(
    *,
    product_row: dict[str, Any],
    user_prompt: str,
    recent_messages: list[dict[str, str]],
    summary_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not _is_websochat_ambiguous_reference_query(user_prompt):
        return None

    recent_context_message = build_websochat_recent_context_message(recent_messages)
    summary_context_message = _build_websochat_summary_context_message(summary_rows[:3])

    context_parts = [
        "너는 스토리 에이전트 내부 해석기다.",
        "사용자에게 보여줄 답변을 쓰지 말고 JSON만 반환하라.",
        "지시대명사 질문이 최근 대화에서 무엇을 가리키는지 해석하라.",
        "JSON 스키마:",
        '{"reference_status":"resolved|ambiguous","resolved_target":"...", "confidence":0.0, "alternate_targets":["..."]}',
        "resolved_target은 1문장으로 구체적인 장면/선택을 적어라.",
        "alternate_targets는 최대 2개까지만 넣어라.",
        "근거가 충분하면 resolved, 부족하면 ambiguous로 하라.",
    ]
    if recent_context_message:
        context_parts.append(recent_context_message)
    if summary_context_message:
        context_parts.append(summary_context_message)
    context_parts.append(f"현재 질문: {user_prompt}")

    response = await _call_claude_messages(
        system_prompt="\n\n".join(context_parts),
        messages=[{"role": "user", "content": "JSON만 반환해."}],
        max_tokens=WEBSOCHAT_REFERENCE_RESOLUTION_MAX_TOKENS,
    )
    content = response.get("content") or []
    parsed = _extract_websochat_json_object(_extract_text(content))
    if not parsed:
        return None

    reference_status = str(parsed.get("reference_status") or "").strip().lower()
    if reference_status not in {"resolved", "ambiguous"}:
        return None

    resolved_target = str(parsed.get("resolved_target") or "").strip()
    alternate_targets = [
        str(item).strip()
        for item in (parsed.get("alternate_targets") or [])
        if str(item).strip()
    ][:2]
    try:
        confidence = float(parsed.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0

    resolved = {
        "reference_status": reference_status,
        "resolved_target": resolved_target,
        "confidence": max(0.0, min(confidence, 1.0)),
        "alternate_targets": alternate_targets,
    }
    logger.info(
        "websochat reference_resolution status=%s confidence=%s resolved_target=%r alternate_targets=%s prompt_preview=%r",
        resolved["reference_status"],
        resolved["confidence"],
        resolved["resolved_target"],
        resolved["alternate_targets"],
        _build_websochat_prompt_preview(user_prompt),
    )
    return resolved


def _build_websochat_reference_resolution_message(reference_resolution: dict[str, Any]) -> str:
    status = str(reference_resolution.get("reference_status") or "").strip().lower()
    resolved_target = str(reference_resolution.get("resolved_target") or "").strip()
    alternate_targets = [
        str(item).strip()
        for item in (reference_resolution.get("alternate_targets") or [])
        if str(item).strip()
    ][:2]

    if status == "resolved" and resolved_target:
        return (
            "[지시대명사 해석 결과]\n"
            f"- 이 질문은 '{resolved_target}'을 가리키는 것으로 해석했다.\n"
            "- 답변 첫 줄에 이 해석을 한 문장으로 밝힌 뒤 이유를 설명하라.\n"
            "- 마지막에는 다른 장면을 뜻했다면 알려달라고 짧게 덧붙여라."
        )

    if status == "ambiguous" and alternate_targets:
        primary_target = resolved_target or alternate_targets[0]
        secondary_targets = [item for item in alternate_targets if item != primary_target][:2]
        bullet_lines = "\n".join(f"- {item}" for item in secondary_targets)
        return (
            "[지시대명사 해석 결과]\n"
            "- 질문이 아직 모호하니 하나를 확정해서 먼저 답하지 마라.\n"
            f"- 현재 유력한 후보는 '{primary_target}'이다.\n"
            + (f"{bullet_lines}\n" if bullet_lines else "")
            + "- 먼저 한 번의 clarifying question으로 범위를 좁혀라.\n"
            + "- 질문에는 가능한 경우 다음 축을 함께 넣어라: 몇 번째 회차인지, 언제 공개된 회차인지, 초반/중반/최신 중 어디쯤인지, 기억나는 회차명이나 장면 키워드.\n"
            + "- 다른 후보가 있으면 1~2개만 짧게 제시하고, 추가 단서가 오기 전에는 특정 장면을 사실처럼 단정하지 마라."
        )

    return ""


async def _dispatch_websochat_tool(
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    product_id: int,
    product_row: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    if tool_name == "get_product_context":
        return await _get_websochat_product_context(product_id=product_id, db=db)
    if tool_name == "search_episode_summaries":
        return {
            "rows": await _get_websochat_summary_candidates(
                product_id=product_id,
                keywords=_extract_websochat_keywords(str(tool_input.get("query") or "")),
                query_text=str(tool_input.get("query") or ""),
                latest_episode_no=latest_episode_no,
                mode=str(tool_input.get("mode") or ""),
                episode_no=int(tool_input.get("episode_no") or 0) or None,
                db=db,
            )
        }
    if tool_name == "search_episode_contents":
        return {
            "rows": await _search_websochat_episode_contents(
                product_id=product_id,
                query_text=str(tool_input.get("query") or ""),
                latest_episode_no=latest_episode_no,
                db=db,
            )
        }
    if tool_name == "get_episode_contents":
        return {
            "rows": await _get_websochat_episode_contents(
                product_id=product_id,
                episode_from=int(tool_input.get("episode_from") or 1),
                episode_to=int(tool_input.get("episode_to") or tool_input.get("episode_from") or 1),
                latest_episode_no=latest_episode_no,
                db=db,
            )
        }
    return {"error": f"지원하지 않는 tool입니다: {tool_name}"}


def _build_websochat_prompt_preview(user_prompt: str) -> str:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip()
    return normalized[:80]


async def _resolve_websochat_qa_corrections(
    *,
    user_prompt: str,
    recent_messages: list[dict[str, str]],
    qa_recent_notes: list[str],
    qa_corrections: list[dict[str, str]],
) -> list[dict[str, str]]:
    recent_context_message = build_websochat_recent_context_message(
        recent_messages,
        qa_recent_notes=qa_recent_notes,
        qa_corrections=qa_corrections,
    )
    system_prompt_parts = [
        "너는 세션 교정 추출기다.",
        "사용자에게 보여줄 답변을 쓰지 말고 JSON만 반환하라.",
        "현재 사용자 발화가 직전 대화의 작품 사실관계를 명시적으로 정정할 때만 correction을 추출하라.",
        "감상, 반박, 추가 질문, 애매한 불만은 correction으로 만들지 마라.",
        "질문형 확인이나 가정 확인은 correction이 아니다. 예: '주인공이 맞지?', '그 인물 맞지?' 같은 문장은 correction으로 만들지 마라.",
        "사용자가 '아니', '틀렸어', '정정하면', '맞는 건'처럼 바로잡는 의미를 분명히 드러낼 때만 correction을 추출하라.",
        "불명확하면 has_corrections=false로 두어라.",
        "subject는 짧은 항목명으로, correct_value는 사용자가 맞다고 바로잡은 값으로 적어라.",
        "incorrect_value는 이전에 잘못 언급된 값이 현재 문맥에서 분명할 때만 넣어라.",
        "최대 3개까지만 반환하라.",
        'JSON 스키마: {"has_corrections":true|false,"corrections":[{"subject":"...","correct_value":"...","incorrect_value":"..."}]}',
    ]
    if recent_context_message:
        system_prompt_parts.append(recent_context_message)

    response = await _call_claude_messages(
        system_prompt="\n\n".join(system_prompt_parts),
        messages=[
            {
                "role": "user",
                "content": f"현재 사용자 발화: {user_prompt}\n\nJSON만 반환해.",
            }
        ],
        max_tokens=WEBSOCHAT_QA_CORRECTION_MAX_TOKENS,
    )
    parsed = _extract_websochat_json_object(_extract_text(response.get("content") or [])) or {}
    raw_has_corrections = parsed.get("has_corrections")
    if isinstance(raw_has_corrections, bool):
        has_corrections = raw_has_corrections
    else:
        has_corrections = str(raw_has_corrections or "").strip().lower() == "true"
    if not has_corrections:
        return []

    corrections = _normalize_websochat_qa_corrections(parsed.get("corrections"))
    if corrections:
        logger.info(
            "websochat qa_corrections_detected corrections=%s prompt_preview=%r",
            corrections,
            _build_websochat_prompt_preview(user_prompt),
        )
    return corrections


async def _resolve_websochat_intent(
    *,
    user_prompt: str,
    recent_messages: list[dict[str, str]],
) -> tuple[str, bool, str]:
    recent_context_message = build_websochat_recent_context_message(recent_messages)
    system_prompt_parts = [
        "너는 스토리 에이전트 라우팅 전용 분류기다.",
        "사용자에게 보여줄 답변을 쓰지 말고 JSON만 반환하라.",
        "intent는 factual, comparative, playful, self_insert, simulation 중 하나만 고르라.",
        "mode는 exact, early, latest, general 중 하나만 고르라.",
        "exact: 특정 회차, 특정 장면, 특정 선택처럼 정확한 대상이 분명할 때",
        "early: 작품의 초반부나 도입부 전체를 묻는 질문일 때",
        "latest: 최신 공개분, 최근 갈등, 지금 상황을 묻는 질문일 때",
        "general: 작품 전체, 넓은 설정, 특정 구간이 확정되지 않은 질문일 때",
        "질문에 '처음'이 있어도 이야기 도입부가 아니라 '가장 처음 발생한 사건/각성/등장'을 묻는 것일 수 있다. 이런 경우 구간이 특정되지 않으면 early가 아니라 general로 두어라.",
        "needs_creative는 이 질문에 답하려면 작품에 없는 결과, 대화, 상황을 새로 만들어야 하는지 여부다.",
        "작품 내 정보를 정리, 설명, 비교, 해석해서 답할 수 있으면 needs_creative=false다.",
        "작품에 없는 대결 결과, 역할극 대사, 자기투영 시나리오, IF 전개, 창작적 놀이 답변을 새로 만들어야 하면 needs_creative=true다.",
        "factual: 사실 확인, 줄거리, 회차 사건, 설정 설명, 최신 갈등 같은 질문",
        "comparative: 누가 더 강한지, 상성, 비교, 랭킹, 월드컵처럼 비교 판단이 핵심인 질문",
        "playful: 인물 대화, 캐릭터 몰입, 호감형/밈/놀아주는 톤이 핵심인 질문",
        "self_insert: 내가 들어가면, 내가 주인공이면, 내 포지션 같은 자기투영 질문",
        "simulation: 만약, IF, 세계가 어떻게 반응하는지, 누가 대신 움직이는지 같은 가정/전개 시뮬레이션 질문",
        "비교 질문이라도 작품 내 명시된 사실만으로 바로 답할 수 있으면 factual로 분류하라.",
        "작품에 직접 근거가 없고 추론이나 상상이 필요할 때만 comparative로 분류하라.",
        "예시:",
        '- "한스 능력이 존보다 강해?" -> {"intent":"factual","needs_creative":false,"mode":"general"}',
        '- "한스랑 존이 붙으면 누가 이겨?" -> {"intent":"comparative","needs_creative":true,"mode":"general"}',
        '- "주인공 능력이 뭐야?" -> {"intent":"factual","needs_creative":false,"mode":"general"}',
        '- "주인공이랑 악당이 성격이 왜 비슷해?" -> {"intent":"factual","needs_creative":false,"mode":"general"}',
        '- "이 세계관에서 최강자 랭킹 매겨봐" -> {"intent":"comparative","needs_creative":true,"mode":"general"}',
        '- "내가 들어가면 살아남을 수 있어?" -> {"intent":"self_insert","needs_creative":true,"mode":"general"}',
        '- "1화에서 벌어진 가장 중요한 사건 3가지를 꼽아줘" -> {"intent":"factual","needs_creative":false,"mode":"exact"}',
        '- "최신 갈등이 뭐야?" -> {"intent":"factual","needs_creative":false,"mode":"latest"}',
        '- "초반 분위기가 어때?" -> {"intent":"factual","needs_creative":false,"mode":"early"}',
        '- "주인공이 처음 각성한 건 어디야?" -> {"intent":"factual","needs_creative":false,"mode":"general"}',
        'JSON 스키마: {"intent":"factual|comparative|playful|self_insert|simulation","needs_creative":true|false,"mode":"exact|early|latest|general"}',
    ]
    if recent_context_message:
        system_prompt_parts.append(recent_context_message)

    response = await _call_claude_messages(
        system_prompt="\n\n".join(system_prompt_parts),
        messages=[
            {
                "role": "user",
                "content": f"질문: {user_prompt}\n\nJSON만 반환해.",
            }
        ],
        max_tokens=WEBSOCHAT_INTENT_MAX_TOKENS,
    )
    parsed = _extract_websochat_json_object(_extract_text(response.get("content") or [])) or {}
    intent = str(parsed.get("intent") or "").strip().lower()
    if intent not in WEBSOCHAT_ALLOWED_INTENTS:
        intent = "factual"
    mode = str(parsed.get("mode") or "").strip().lower()
    if mode not in WEBSOCHAT_ALLOWED_SUMMARY_MODES:
        mode = "general"
    raw_needs_creative = parsed.get("needs_creative")
    if isinstance(raw_needs_creative, bool):
        needs_creative = raw_needs_creative
    else:
        needs_creative = str(raw_needs_creative or "").strip().lower() == "true"
    return intent, needs_creative, mode


async def _resolve_websochat_rp_recall_need(
    *,
    user_prompt: str,
    recent_messages: list[dict[str, str]],
    rp_context: dict[str, Any],
) -> tuple[bool, str]:
    recent_context_message = build_websochat_recent_context_message(recent_messages)
    anchor_episode_no = int(rp_context.get("anchor_episode_no") or 0)
    anchor_summary_text = str(rp_context.get("anchor_summary_text") or "").strip()
    display_name = str(rp_context.get("display_name") or rp_context.get("active_character") or "캐릭터").strip()
    system_prompt_parts = [
        "너는 RP 원고 회상 보조 분류기다.",
        "사용자에게 보여줄 답변을 쓰지 말고 JSON만 반환하라.",
        "현재 질문이 정확한 대사, 특정 행동 디테일, 과거 장면의 실제 표현을 더 정확히 짚기 위해 원문 청크를 참조해야 하는지 판단하라.",
        "단순한 감정 해석, 태도 해석, 현재 반응, 넓은 과거 회상만으로 충분하면 needs_exact_recall=false다.",
        "정확히 뭐라고 했는지, 그때 어떤 행동을 했는지, 특정 장면의 말/행동 디테일을 복원해야 하면 needs_exact_recall=true다.",
        "search_query는 원문 검색용 짧은 한국어 구문이다. 인물명, 행동, 사건, 관계 키워드를 포함하되 12단어 이내로 줄여라.",
        "모르면 needs_exact_recall=false로 보수적으로 답하라.",
        'JSON 스키마: {"needs_exact_recall":true|false,"search_query":"짧은 검색어"}',
    ]
    if anchor_episode_no > 0 and anchor_summary_text:
        system_prompt_parts.append(
            f"[현재 anchor]\n- {display_name}\n- 기준 회차: {anchor_episode_no}화\n- 요약: {anchor_summary_text[:300]}"
        )
    if recent_context_message:
        system_prompt_parts.append(recent_context_message)

    response = await _call_claude_messages(
        system_prompt="\n\n".join(system_prompt_parts),
        messages=[
            {
                "role": "user",
                "content": f"질문: {user_prompt}\n\nJSON만 반환해.",
            }
        ],
        max_tokens=WEBSOCHAT_RP_RECALL_DECISION_MAX_TOKENS,
    )
    parsed = _extract_websochat_json_object(_extract_text(response.get("content") or [])) or {}
    raw_needs_exact_recall = parsed.get("needs_exact_recall")
    if isinstance(raw_needs_exact_recall, bool):
        needs_exact_recall = raw_needs_exact_recall
    else:
        needs_exact_recall = str(raw_needs_exact_recall or "").strip().lower() == "true"
    search_query = re.sub(r"\s+", " ", str(parsed.get("search_query") or "").strip())[:120]
    if not search_query:
        search_query = _build_websochat_prompt_preview(user_prompt)
    return needs_exact_recall, search_query


async def _build_websochat_rp_exact_recall_context(
    *,
    product_row: dict[str, Any],
    user_prompt: str,
    recent_messages: list[dict[str, str]],
    rp_context: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    needs_exact_recall, search_query = await _resolve_websochat_rp_recall_need(
        user_prompt=user_prompt,
        recent_messages=recent_messages,
        rp_context=rp_context,
    )
    if not needs_exact_recall:
        return {}

    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    read_episode_to = int(((rp_context.get("session_memory") or {}).get("read_episode_to")) or 0)
    latest_public_episode_no = min(
        read_episode_to if read_episode_to > 0 else latest_episode_no,
        latest_episode_no,
    )
    if latest_public_episode_no <= 0:
        return {}

    anchor_episode_no = int(rp_context.get("anchor_episode_no") or 0)
    candidate_episode_order: dict[int, int] = {}
    candidate_episode_nos: list[int] = []
    for episode_no in [anchor_episode_no, *[int(item.get("episode_no") or 0) for item in (rp_context.get("trajectory_history") or []) if isinstance(item, dict)]]:
        if episode_no <= 0 or episode_no > latest_public_episode_no or episode_no in candidate_episode_order:
            continue
        candidate_episode_order[episode_no] = len(candidate_episode_order)
        candidate_episode_nos.append(episode_no)

    keywords = _extract_websochat_keywords(search_query or user_prompt)
    summary_rows = await _get_websochat_summary_candidates(
        product_id=int(product_row.get("productId") or 0),
        keywords=keywords,
        query_text=search_query or user_prompt,
        latest_episode_no=latest_public_episode_no,
        mode="general",
        episode_no=None,
        db=db,
    )
    for row in summary_rows[:3]:
        for episode_no in [
            int(row.get("episodeTo") or 0),
            int(row.get("episodeFrom") or 0),
        ]:
            if (
                episode_no <= 0
                or episode_no > latest_public_episode_no
                or episode_no in candidate_episode_order
            ):
                continue
            candidate_episode_order[episode_no] = len(candidate_episode_order)
            candidate_episode_nos.append(episode_no)

    prioritized_rows: list[dict[str, Any]] = []
    if candidate_episode_nos:
        for episode_no in candidate_episode_nos[:5]:
            episode_rows = await _get_websochat_episode_contents(
                product_id=int(product_row.get("productId") or 0),
                episode_from=episode_no,
                episode_to=episode_no,
                latest_episode_no=latest_public_episode_no,
                db=db,
            )
            for row in episode_rows:
                chunk_text = str(row.get("chunkText") or "").strip()
                if not chunk_text:
                    continue
                score = sum(1 for keyword in keywords if keyword and keyword in chunk_text)
                if keywords and score <= 0:
                    continue
                prioritized_rows.append(
                    {
                        "episodeNo": episode_no,
                        "chunkText": chunk_text,
                        "matchScore": score,
                    }
                )

    if prioritized_rows:
        chunk_rows = sorted(
            prioritized_rows,
            key=lambda row: (
                -int(row.get("matchScore") or 0),
                candidate_episode_order.get(int(row.get("episodeNo") or 0), 999),
            ),
        )
    else:
        chunk_rows = await _search_websochat_episode_contents(
            product_id=int(product_row.get("productId") or 0),
            query_text=search_query,
            latest_episode_no=latest_public_episode_no,
            db=db,
        )
        if not chunk_rows:
            return {}

    def _row_sort_key(row: dict[str, Any]) -> tuple[int, int, int]:
        episode_no = int(row.get("episodeNo") or 0)
        if episode_no in candidate_episode_order:
            return (0, candidate_episode_order[episode_no], episode_no)
        distance = abs(episode_no - anchor_episode_no) if anchor_episode_no > 0 else 9999
        return (1, distance, episode_no)

    selected_rows: list[dict[str, Any]] = []
    seen_episode_nos: set[int] = set()
    total_chars = 0
    for row in sorted(chunk_rows, key=_row_sort_key):
        episode_no = int(row.get("episodeNo") or 0)
        chunk_text = str(row.get("chunkText") or "").strip()
        if episode_no <= 0 or not chunk_text:
            continue
        if episode_no in seen_episode_nos and len(selected_rows) >= 2:
            continue
        if total_chars >= WEBSOCHAT_RP_RECALL_CONTEXT_CHAR_LIMIT:
            break
        seen_episode_nos.add(episode_no)
        clipped = chunk_text[:500]
        selected_rows.append({"episode_no": episode_no, "chunk_text": clipped})
        total_chars += len(clipped)
        if len(selected_rows) >= 4:
            break
    if not selected_rows:
        return {}

    recall_lines = [
        "- 아래는 지금 질문과 가장 가까운 공개 회차 원문 일부다.",
        "- 정확한 대사나 행동은 여기에서 확인되는 범위 안에서만 반영하라.",
        "- 원문에 보이지 않는 문장을 정확한 인용처럼 꾸며내지 마라.",
    ]
    for row in selected_rows:
        recall_lines.append(f"[{int(row['episode_no'])}화 원문 일부]\n{row['chunk_text']}")
    return {
        "raw_recall_context": "\n".join(recall_lines),
    }


async def _generate_websochat_reply(
    *,
    session_id: int,
    session_memory: dict[str, Any],
    product_row: dict[str, Any],
    user_prompt: str,
    user_id: int | None,
    db: AsyncSession,
    forced_route: str | None = None,
) -> tuple[str, str, str, bool, str, dict[str, Any] | None]:
    normalized_memory = _normalize_websochat_session_memory(session_memory)
    gemini_enabled = bool(settings.GEMINI_API_KEY)
    scope_state = _resolve_websochat_read_scope_state(normalized_memory)
    normalized_forced_route = str(forced_route or "").strip().lower() or None

    initial_route = normalized_forced_route or _resolve_websochat_response_route(
        normalized_memory=normalized_memory,
        rp_context=None,
    )
    if initial_route == "game":
        return await _generate_websochat_game_reply(
            session_id=session_id,
            session_memory=normalized_memory,
            product_row=product_row,
            user_prompt=user_prompt,
            db=db,
        )

    if scope_state == "none":
        concierge_payload = await build_websochat_concierge_payload(
            product_row=product_row,
            user_id=user_id,
            db=db,
            user_prompt=user_prompt,
        )
        return (
            str(concierge_payload.get("reply") or "").strip(),
            "system",
            "qa:concierge",
            False,
            "concierge",
            normalized_memory,
        )

    if not int(normalized_memory.get("read_episode_to") or 0):
        return (
            _build_websochat_read_scope_required_reply(),
            "guard",
            "guard:read_scope_required",
            False,
            "read_scope_required",
            None,
        )

    rp_context = None
    active_route = normalized_forced_route or "qa"
    if normalized_forced_route != "qa":
        rp_context = await _load_websochat_rp_context(
            product_row=product_row,
            session_memory=normalized_memory,
            db=db,
        )
        active_route = normalized_forced_route or _resolve_websochat_response_route(
            normalized_memory=normalized_memory,
            rp_context=rp_context,
        )
    recent_messages = await _get_websochat_recent_messages(session_id=session_id, db=db)
    if active_route == "rp" and rp_context:
        exact_recall_context = await _build_websochat_rp_exact_recall_context(
            product_row=product_row,
            user_prompt=user_prompt,
            recent_messages=recent_messages,
            rp_context=rp_context,
            db=db,
        )
        if exact_recall_context:
            rp_context = {
                **rp_context,
                **exact_recall_context,
            }
        rp_plan = _build_websochat_rp_plan(
            rp_context=rp_context,
            gemini_enabled=gemini_enabled,
        )
        if rp_plan["preferred_model"] == "gemini":
            try:
                reply = await generate_websochat_rp_reply_with_gemini(
                    product_row=product_row,
                    user_prompt=user_prompt,
                    rp_context=rp_context,
                    recent_messages=recent_messages,
                )
                return reply, "gemini", rp_plan["route_mode"], False, rp_plan["intent"], None
            except Exception as exc:
                logger.warning(
                    "websochat rp_route_selected model_used=gemini fallback_used=true product_id=%s session_id=%s active_character=%s error=%s",
                    product_row.get("productId"),
                    session_id,
                    rp_context.get("active_character"),
                    exc,
                )
        reply = await generate_websochat_rp_reply_with_claude(
            product_row=product_row,
            user_prompt=user_prompt,
            rp_context=rp_context,
            recent_messages=recent_messages,
        )
        return reply, "haiku", rp_plan["route_mode"], gemini_enabled, rp_plan["intent"], None

    intent_result, detected_qa_corrections = await asyncio.gather(
        _resolve_websochat_intent(
            user_prompt=user_prompt,
            recent_messages=recent_messages,
        ),
        _resolve_websochat_qa_corrections(
            user_prompt=user_prompt,
            recent_messages=recent_messages,
            qa_recent_notes=list(normalized_memory.get("qa_recent_notes") or []),
            qa_corrections=list(normalized_memory.get("qa_corrections") or []),
        ),
    )
    intent, needs_creative, routed_mode = intent_result
    qa_subtype = resolve_websochat_qa_subtype(user_prompt)
    route_session_memory: dict[str, Any] | None = None
    if detected_qa_corrections:
        normalized_memory = _merge_websochat_qa_corrections(
            normalized_memory,
            detected_qa_corrections,
        )
        route_session_memory = normalized_memory
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    evidence_bundle: WebsochatEvidenceBundle = await assemble_websochat_scope_context(
        product_row=product_row,
        session_memory=normalized_memory,
        user_prompt=user_prompt,
        db=db,
    )
    scoped_product_row = evidence_bundle["product_row"]
    resolved_mode, _, _, _ = _resolve_websochat_summary_mode(
        query_text=user_prompt,
        latest_episode_no=latest_episode_no,
        mode=routed_mode,
    )
    qa_plan = _build_websochat_qa_plan(
        intent=intent,
        needs_creative=needs_creative,
        resolved_mode=resolved_mode,
        gemini_enabled=gemini_enabled,
        scope_state=scope_state,
    )
    qa_plan["qa_subtype"] = qa_subtype
    prompt_preview = _build_websochat_prompt_preview(user_prompt)
    qa_hooks: WebsochatQaExecutionHooks = {
        "resolve_summary_mode": _resolve_websochat_summary_mode,
        "resolve_exact_episode_no": _resolve_websochat_exact_episode_no,
        "extract_keywords": _extract_websochat_keywords,
        "get_summary_candidates": _get_websochat_summary_candidates,
        "get_broad_summary_context_rows": _get_websochat_broad_summary_context_rows,
        "resolve_reference": _resolve_websochat_reference,
        "build_reference_resolution_message": _build_websochat_reference_resolution_message,
        "get_episode_contents": _get_websochat_episode_contents,
        "search_episode_contents": _search_websochat_episode_contents,
        "get_public_episode_refs": _get_websochat_public_episode_refs,
        "build_system_prompt": _build_websochat_system_prompt,
        "build_summary_context_message": _build_websochat_summary_context_message,
        "is_ambiguous_reference_query": _is_websochat_ambiguous_reference_query,
        "dispatch_tool": _dispatch_websochat_tool,
    }
    result: WebsochatQaExecutionResult = await execute_websochat_qa(
        product_row=scoped_product_row,
        user_prompt=user_prompt,
        qa_plan=qa_plan,
        evidence_bundle=evidence_bundle,
        recent_messages=recent_messages,
        qa_recent_notes=list(normalized_memory.get("qa_recent_notes") or []),
        qa_corrections=list(normalized_memory.get("qa_corrections") or []),
        current_qa_corrections=detected_qa_corrections,
        db=db,
        hooks=qa_hooks,
        max_tool_rounds=WEBSOCHAT_MAX_TOOL_ROUNDS,
        gemini_context_episode_limit=WEBSOCHAT_GEMINI_CONTEXT_EPISODE_LIMIT,
        prefetch_context_chars=WEBSOCHAT_PREFETCH_CONTEXT_CHARS,
        tools=WEBSOCHAT_TOOLS,
    )
    logger.info(
        "websochat route_selected model_used=%s intent=%s qa_subtype=%s needs_creative=%s route_mode=%s fallback_used=%s product_id=%s session_id=%s latest_episode_no=%s prompt_preview=%r",
        result["model_used"],
        result["intent"],
        qa_subtype,
        "true" if needs_creative else "false",
        result["route_mode"],
        "true" if result["fallback_used"] else "false",
        product_row.get("productId"),
        session_id,
        int(product_row.get("latestEpisodeNo") or 0),
        prompt_preview,
    )
    if result.get("referenced_episode_nos"):
        route_session_memory = dict(route_session_memory or normalized_memory)
        route_session_memory[WEBSOCHAT_QA_EPISODE_REF_MEMORY_KEY] = list(result.get("referenced_episode_nos") or [])
    return result["reply"], result["model_used"], result["route_mode"], result["fallback_used"], result["intent"], route_session_memory




async def _get_websochat_chunk_previews(
    product_id: int,
    episode_nos: list[int],
    keywords: list[str],
    db: AsyncSession,
) -> list[dict[str, Any]]:
    if not episode_nos:
        return []

    params: dict[str, Any] = {"product_id": product_id}
    placeholders: list[str] = []
    for idx, episode_no in enumerate(episode_nos, start=1):
        key = f"episode_no_{idx}"
        params[key] = episode_no
        placeholders.append(f":{key}")

    keyword_where_parts: list[str] = []
    for idx, keyword in enumerate(keywords, start=1):
        key = f"chunk_keyword_{idx}"
        params[key] = f"%{keyword}%"
        keyword_where_parts.append(f"c.text LIKE :{key}")
    keyword_where_sql = f" AND ({' OR '.join(keyword_where_parts)})" if keyword_where_parts else ""

    query = text(
        f"""
        SELECT
            c.episode_no AS episodeNo,
            c.chunk_no AS chunkNo,
            c.text AS chunkText
        FROM tb_story_agent_context_chunk c
        JOIN tb_story_agent_context_doc d
          ON d.context_doc_id = c.context_doc_id
         AND d.is_active = 'Y'
        WHERE c.product_id = :product_id
          AND c.episode_no IN ({', '.join(placeholders)})
          {keyword_where_sql}
        ORDER BY c.episode_no ASC, c.chunk_no ASC
        LIMIT 6
        """
    )
    result = await db.execute(query, params)
    rows = [dict(row) for row in result.mappings().all()]
    if rows or keywords:
        return rows

    fallback_query = text(
        f"""
        SELECT
            c.episode_no AS episodeNo,
            c.chunk_no AS chunkNo,
            c.text AS chunkText
        FROM tb_story_agent_context_chunk c
        JOIN tb_story_agent_context_doc d
          ON d.context_doc_id = c.context_doc_id
         AND d.is_active = 'Y'
        WHERE c.product_id = :product_id
          AND c.episode_no IN ({', '.join(placeholders)})
        ORDER BY c.episode_no ASC, c.chunk_no ASC
        LIMIT 3
        """
    )
    fallback_result = await db.execute(fallback_query, params)
    return [dict(row) for row in fallback_result.mappings().all()]


async def _acquire_named_lock(lock_name: str) -> AsyncConnection | None:
    conn = await likenovel_db_engine.connect()
    result = await conn.execute(
        text("SELECT GET_LOCK(:lock_name, :timeout) AS locked"),
        {"lock_name": lock_name, "timeout": WEBSOCHAT_SESSION_LOCK_TIMEOUT_SECONDS},
    )
    row = result.mappings().one()
    if bool(row.get("locked")):
        return conn
    await conn.close()
    return None


async def _release_named_lock(lock_name: str, conn: AsyncConnection | None) -> None:
    if conn is None:
        return
    try:
        await conn.execute(text("SELECT RELEASE_LOCK(:lock_name)"), {"lock_name": lock_name})
    except Exception as exc:
        logger.warning("failed to release named lock [%s]: %s", lock_name, exc)
    finally:
        await conn.close()


async def _acquire_websochat_session_lock(session_id: int) -> AsyncConnection | None:
    return await _acquire_named_lock(f"websochat-session:{session_id}")


async def _release_websochat_session_lock(session_id: int, conn: AsyncConnection | None) -> None:
    await _release_named_lock(f"websochat-session:{session_id}", conn)


def _get_websochat_actor_lock_name(user_id: int | None, guest_key: str | None) -> str:
    if user_id is not None:
        return f"websochat-actor:user:{user_id}"
    return f"websochat-actor:guest:{guest_key}"


async def _acquire_websochat_actor_lock(
    user_id: int | None,
    guest_key: str | None,
    db: AsyncSession,
) -> AsyncConnection | None:
    del db
    return await _acquire_named_lock(_get_websochat_actor_lock_name(user_id, guest_key))


async def _release_websochat_actor_lock(
    user_id: int | None,
    guest_key: str | None,
    conn: AsyncConnection | None,
) -> None:
    await _release_named_lock(_get_websochat_actor_lock_name(user_id, guest_key), conn)


async def _get_websochat_daily_user_message_count(
    user_id: int | None,
    guest_key: str | None,
    db: AsyncSession,
) -> int:
    owner_where = "s.user_id = :user_id" if user_id is not None else "s.guest_key = :guest_key"
    params: dict[str, Any] = {}
    if user_id is not None:
        params["user_id"] = user_id
    else:
        params["guest_key"] = guest_key

    result = await db.execute(
        text(
            f"""
            SELECT COUNT(*) AS cnt
            FROM tb_story_agent_message m
            JOIN tb_story_agent_session s ON s.session_id = m.session_id
            WHERE m.role = 'user'
              AND {owner_where}
              AND DATE(m.created_date) = CURDATE()
            """
        ),
        params,
    )
    row = result.mappings().one()
    return int(row.get("cnt") or 0)


async def _get_user_cash_balance_for_websochat(user_id: int, db: AsyncSession) -> int:
    result = await db.execute(
        text(
            """
            SELECT COALESCE(SUM(balance), 0) AS balance
            FROM tb_user_cashbook
            WHERE user_id = :user_id
            """
        ),
        {"user_id": user_id},
    )
    row = result.mappings().one_or_none()
    return int((row or {}).get("balance") or 0)


async def _charge_websochat_cash(
    user_id: int,
    session_id: int,
    product_id: int,
    db: AsyncSession,
    cash_cost: int,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO tb_user_cashbook
            (user_id, balance, created_id, created_date, updated_id, updated_date)
            VALUES (:user_id, :amount, :created_id, NOW(), :updated_id, NOW())
            """
        ),
        {
            "user_id": user_id,
            "amount": -cash_cost,
            "created_id": settings.DB_DML_DEFAULT_ID,
            "updated_id": settings.DB_DML_DEFAULT_ID,
        },
    )
    await db.execute(
        text(
            """
            INSERT INTO tb_user_cashbook_transaction
            (
                from_user_id,
                to_user_id,
                amount,
                sponsor_type,
                product_id,
                story_agent_session_id,
                created_id,
                created_date
            )
            VALUES (
                :from_user_id,
                :to_user_id,
                :amount,
                :sponsor_type,
                :product_id,
                :story_agent_session_id,
                :created_id,
                NOW()
            )
            """
        ),
        {
            "from_user_id": user_id,
            "to_user_id": -1,
            "amount": cash_cost,
            "sponsor_type": "story_agent",
            "product_id": product_id,
            "story_agent_session_id": session_id,
            "created_id": settings.DB_DML_DEFAULT_ID,
        },
    )


async def _enforce_websochat_message_usage(
    user_id: int | None,
    guest_key: str | None,
    session_id: int,
    product_id: int,
    db: AsyncSession,
    qa_action_key: str | None = None,
) -> None:
    used_count = await _get_websochat_daily_user_message_count(user_id, guest_key, db)
    if used_count < WEBSOCHAT_DAILY_FREE_MESSAGE_LIMIT:
        return

    if user_id is None:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    cash_cost = _resolve_websochat_message_cash_cost(qa_action_key)
    balance = await _get_user_cash_balance_for_websochat(user_id=user_id, db=db)
    if balance < cash_cost:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INSUFFICIENT_CASH_BALANCE,
        )

    await _charge_websochat_cash(
        user_id=user_id,
        session_id=session_id,
        product_id=product_id,
        db=db,
        cash_cost=cash_cost,
    )


async def _resolve_websochat_message_charge_required(
    user_id: int | None,
    guest_key: str | None,
    db: AsyncSession,
    qa_action_key: str | None = None,
) -> bool:
    used_count = await _get_websochat_daily_user_message_count(user_id, guest_key, db)
    if used_count < WEBSOCHAT_DAILY_FREE_MESSAGE_LIMIT:
        return False

    if user_id is None:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    cash_cost = _resolve_websochat_message_cash_cost(qa_action_key)
    balance = await _get_user_cash_balance_for_websochat(user_id=user_id, db=db)
    if balance < cash_cost:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INSUFFICIENT_CASH_BALANCE,
        )
    return True


async def _get_existing_turn_messages(
    session_id: int,
    client_message_id: str,
    latest_episode_no: int | None,
    synced_latest_episode_no: int | None,
    read_episode_to: int | None,
    concierge_payload: dict[str, Any] | None,
    db: AsyncSession,
) -> list[dict[str, Any]] | None:
    result = await db.execute(
        text(
            """
            SELECT
                message_id AS messageId,
                role,
                content,
                DATE_FORMAT(created_date, '%Y-%m-%d %H:%i:%s') AS createdDate
            FROM tb_story_agent_message
            WHERE session_id = :session_id
              AND client_message_id = :client_message_id
            ORDER BY message_id ASC
            """
        ),
        {
            "session_id": session_id,
            "client_message_id": client_message_id,
        },
    )
    rows = [dict(row) for row in result.mappings().all()]
    rows = [
        {
            **row,
            "content": _strip_websochat_noncanonical_message_marker(str(row.get("content") or "")),
        }
        for row in rows
    ]
    episode_ref_ceiling = _resolve_websochat_episode_ref_ceiling(
        latest_episode_no,
        synced_latest_episode_no,
        read_episode_to,
    )
    rows = [
        (
            {**row, "referencedEpisodeNos": []}
            if concierge_payload and row.get("role") == "assistant"
            else _attach_websochat_message_episode_refs(row, latest_episode_no=episode_ref_ceiling)
        )
        for row in rows
    ]
    rows = _attach_websochat_concierge_to_last_assistant_message(rows, concierge_payload)
    if not rows:
        return None
    if len(rows) != 2:
        raise CustomResponseException(
            status_code=status.HTTP_409_CONFLICT,
            message="이전 메시지가 아직 처리 중입니다. 잠시 후 다시 시도해주세요.",
        )
    return rows


def _extract_websochat_referenced_episode_nos(
    content: str,
    latest_episode_no: int | None = None,
) -> list[int]:
    normalized_content = (content or "").strip()
    if not normalized_content:
        return []

    max_episode_no = max(0, int(latest_episode_no or 0))
    scope_only_match = re.search(r"읽은 범위는\s*(\d{1,4})화", normalized_content)
    if scope_only_match:
        scope_episode_no = int(scope_only_match.group(1) or 0)
        if scope_episode_no > 0 and (max_episode_no <= 0 or scope_episode_no <= max_episode_no):
            return [scope_episode_no]

    episode_nos: set[int] = set()

    for range_match in WEBSOCHAT_EPISODE_RANGE_RE.finditer(normalized_content):
        first = int(range_match.group(1) or 0)
        second = int(range_match.group(2) or 0)
        if not first or not second:
            continue
        start = max(1, min(first, second))
        end = max(first, second)
        if max_episode_no > 0:
            end = min(end, max_episode_no)
        for episode_no in range(start, end + 1):
            episode_nos.add(episode_no)

    for single_match in WEBSOCHAT_EPISODE_SINGLE_RE.finditer(normalized_content):
        episode_no = int(single_match.group(1) or 0)
        if not episode_no:
            continue
        if max_episode_no > 0 and episode_no > max_episode_no:
            continue
        episode_nos.add(episode_no)

    return sorted(episode_nos)


def _attach_websochat_message_episode_refs(
    message: dict[str, Any],
    latest_episode_no: int | None = None,
) -> dict[str, Any]:
    if message.get("role") != "assistant":
        return message
    return {
        **message,
        "referencedEpisodeNos": _extract_websochat_referenced_episode_nos(
            str(message.get("content") or ""),
            latest_episode_no=latest_episode_no,
        ),
    }


async def _get_session_row(
    session_id: int,
    user_id: int | None,
    guest_key: str | None,
    db: AsyncSession,
) -> dict[str, Any]:
    owner_where = "AND user_id = :user_id" if user_id is not None else "AND guest_key = :guest_key"
    params: dict[str, Any] = {"session_id": session_id}
    if user_id is not None:
        params["user_id"] = user_id
    else:
        params["guest_key"] = guest_key

    query = text(
        f"""
        SELECT session_id, product_id, title, session_memory_json, created_date, updated_date
        FROM tb_story_agent_session
        WHERE session_id = :session_id
          AND deleted_yn = 'N'
          AND expires_at > NOW()
          {owner_where}
        LIMIT 1
        """
    )
    result = await db.execute(query, params)
    row = result.mappings().one_or_none()
    if not row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="스토리 에이전트 세션을 찾을 수 없습니다.",
        )
    return dict(row)


@handle_exceptions
async def search_products(
    keyword: str,
    kc_user_id: str | None,
    adult_yn: str,
    db: AsyncSession,
):
    normalized_keyword = (keyword or "").strip()
    if not normalized_keyword:
        return {"data": []}

    effective_adult_yn = await _resolve_effective_adult_yn(
        kc_user_id=kc_user_id,
        adult_yn=adult_yn,
        db=db,
    )
    ratings_filter = "" if effective_adult_yn == "Y" else "AND p.ratings_code = 'all'"
    query = text(
        f"""
        SELECT
            p.product_id AS productId,
            p.title,
            p.author_name AS authorNickname,
            {get_file_path_sub_query('p.thumbnail_file_id', 'coverImagePath')},
            p.status_code AS statusCode,
            COALESCE(sacp.context_status, 'pending') AS contextStatus,
            COALESCE(MAX(e.episode_no), 0) AS latestEpisodeNo,
            LEAST(COALESCE(sacp.ready_episode_count, 0), COALESCE(MAX(e.episode_no), 0)) AS syncedLatestEpisodeNo
        FROM tb_product p
        LEFT JOIN tb_story_agent_context_product sacp
          ON sacp.product_id = p.product_id
        LEFT JOIN tb_product_episode e
          ON e.product_id = p.product_id
         AND e.use_yn = 'Y'
         AND e.open_yn = 'Y'
        WHERE p.price_type = 'free'
          AND p.open_yn = 'Y'
          AND p.blind_yn = 'N'
          {ratings_filter}
          AND (
            p.title LIKE :keyword
            OR p.author_name LIKE :keyword
          )
        GROUP BY p.product_id, p.title, p.author_name, p.thumbnail_file_id, p.status_code, sacp.context_status, sacp.ready_episode_count
        HAVING COALESCE(MAX(e.episode_no), 0) > 0
        ORDER BY
          CASE WHEN COALESCE(sacp.context_status, 'pending') = 'ready' THEN 0 ELSE 1 END,
          CASE WHEN p.title LIKE :prefix_keyword THEN 0 ELSE 1 END,
          p.updated_date DESC,
          p.product_id DESC
        LIMIT 20
        """
    )
    params = {
        "keyword": f"%{normalized_keyword}%",
        "prefix_keyword": f"{normalized_keyword}%",
    }
    result = await db.execute(query, params)
    rows = [dict(row) for row in result.mappings().all()]
    for row in rows:
        row["publishedLatestEpisodeNo"] = int(row.get("latestEpisodeNo") or 0)
    return {"data": rows}


@handle_exceptions
async def get_sessions(
    kc_user_id: str | None,
    guest_key: str | None,
    product_id: int | None,
    adult_yn: str,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, guest_key, db)
    effective_adult_yn = await _resolve_effective_adult_yn(
        kc_user_id=kc_user_id,
        adult_yn=adult_yn,
        db=db,
    )

    where_parts = ["deleted_yn = 'N'", "expires_at > NOW()"]
    params: dict[str, Any] = {}
    if user_id is not None:
        where_parts.append("user_id = :user_id")
        params["user_id"] = user_id
    else:
        where_parts.append("guest_key = :guest_key")
        params["guest_key"] = resolved_guest_key

    if product_id:
        where_parts.append("product_id = :product_id")
        params["product_id"] = product_id

    query = text(
        f"""
        SELECT
            session_id AS sessionId,
            product_id AS productId,
            title,
            DATE_FORMAT(created_date, '%Y-%m-%d %H:%i:%s') AS createdDate,
            DATE_FORMAT(updated_date, '%Y-%m-%d %H:%i:%s') AS updatedDate,
            session_memory_json AS sessionMemoryJson
        FROM tb_story_agent_session
        WHERE {' AND '.join(where_parts)}
        ORDER BY updated_date DESC, session_id DESC
        LIMIT 50
        """
    )
    result = await db.execute(query, params)
    session_rows = [dict(row) for row in result.mappings().all()]
    product_state_cache: dict[int, dict[str, Any]] = {}
    read_scope_title_cache: dict[tuple[int, int], str | None] = {}
    items: list[dict[str, Any]] = []

    for row in session_rows:
        current_product_id = int(row["productId"])
        if current_product_id not in product_state_cache:
            product_state_cache[current_product_id] = await _get_websochat_product_session_state(
                product_id=current_product_id,
                adult_yn=effective_adult_yn,
                db=db,
            )
        product_state = product_state_cache[current_product_id]
        session_memory = _normalize_websochat_session_memory(row.get("sessionMemoryJson"))
        rp_session_state = await _build_websochat_rp_session_state(
            product_row=product_state,
            session_memory=session_memory,
            db=db,
        )
        scope_state = _resolve_websochat_read_scope_state(session_memory)
        requested_read_episode_to = max(int(session_memory.get("read_episode_to") or 0), 0) or None
        read_episode_to = _resolve_websochat_display_read_episode_to(
            scope_state=scope_state,
            latest_episode_no=product_state.get("latestEpisodeNo"),
            synced_latest_episode_no=product_state.get("syncedLatestEpisodeNo"),
            requested_read_episode_to=requested_read_episode_to,
        )
        read_episode_title = None
        if read_episode_to:
            cache_key = (current_product_id, read_episode_to)
            if cache_key not in read_scope_title_cache:
                read_scope_title_cache[cache_key] = await _get_websochat_visible_episode_title(
                    current_product_id,
                    read_episode_to,
                    db,
                )
            read_episode_title = read_scope_title_cache[cache_key]

        items.append(
            {
                "sessionId": row["sessionId"],
                "productId": current_product_id,
                "title": row["title"],
                "createdDate": row["createdDate"],
                "updatedDate": row["updatedDate"],
                "productTitle": product_state.get("title"),
                "productAuthorNickname": product_state.get("authorNickname"),
                "coverImagePath": product_state.get("coverImagePath"),
                "readScopeState": scope_state,
                "readEpisodeNo": read_episode_to,
                "readEpisodeTitle": read_episode_title,
                "latestEpisodeNo": product_state.get("latestEpisodeNo") or 0,
                "publishedLatestEpisodeNo": product_state.get("latestEpisodeNo") or 0,
                "syncedLatestEpisodeNo": product_state.get("syncedLatestEpisodeNo") or 0,
                "contextStatus": product_state.get("contextStatus"),
                "canSendMessage": product_state.get("canSendMessage"),
                "unavailableMessage": product_state.get("unavailableMessage"),
                "rpStage": rp_session_state["rpStage"],
                "rpActiveCharacterLabel": rp_session_state["rpActiveCharacterLabel"],
            }
        )

    return {"data": items}


@handle_exceptions
async def get_messages(
    session_id: int,
    kc_user_id: str | None,
    guest_key: str | None,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, guest_key, db)
    session_row = await _get_session_row(session_id, user_id, resolved_guest_key, db)
    product_state = await _get_websochat_product_session_state(
        product_id=int(session_row["product_id"]),
        adult_yn=await _resolve_effective_adult_yn(
            kc_user_id=kc_user_id,
            adult_yn="Y",
            db=db,
        ),
        db=db,
    )

    query = text(
        """
        SELECT
            message_id AS messageId,
            role,
            content,
            DATE_FORMAT(created_date, '%Y-%m-%d %H:%i:%s') AS createdDate
        FROM tb_story_agent_message
        WHERE session_id = :session_id
        ORDER BY message_id ASC
        """
    )
    result = await db.execute(query, {"session_id": session_id})
    messages = [dict(row) for row in result.mappings().all()]
    messages = [
        {
            **message,
            "content": _strip_websochat_noncanonical_message_marker(str(message.get("content") or "")),
        }
        for message in messages
    ]
    session_memory = _normalize_websochat_session_memory(session_row.get("session_memory_json"))
    rp_session_state = await _build_websochat_rp_session_state(
        product_row=product_state,
        session_memory=session_memory,
        db=db,
    )
    scope_state = _resolve_websochat_read_scope_state(session_memory)
    requested_read_episode_to = max(int(session_memory.get("read_episode_to") or 0), 0) or None
    latest_episode_no = int(product_state.get("latestEpisodeNo") or 0)
    synced_latest_episode_no = _resolve_websochat_synced_latest_episode_no(product_state)
    read_episode_to = _resolve_websochat_display_read_episode_to(
        scope_state=scope_state,
        latest_episode_no=latest_episode_no,
        synced_latest_episode_no=synced_latest_episode_no,
        requested_read_episode_to=requested_read_episode_to,
    )
    read_episode_title = None
    if read_episode_to:
        read_episode_title = await _get_websochat_visible_episode_title(
            int(session_row["product_id"]),
            read_episode_to,
            db,
        )
    concierge_payload = None
    if scope_state == "none":
        concierge_payload = await build_websochat_concierge_payload(
            product_row=product_state,
            user_id=user_id,
            db=db,
        )
    episode_ref_ceiling = _resolve_websochat_episode_ref_ceiling(
        latest_episode_no,
        synced_latest_episode_no,
        requested_read_episode_to,
    )
    messages = [
        (
            {**message, "referencedEpisodeNos": []}
            if concierge_payload and message.get("role") == "assistant"
            else _attach_websochat_message_episode_refs(message, latest_episode_no=episode_ref_ceiling)
        )
        for message in messages
    ]
    messages = _attach_websochat_concierge_to_last_assistant_message(messages, concierge_payload)
    starter = _build_websochat_starter(
        product_title=str(product_state.get("title") or session_row.get("title") or "").strip(),
        scope_state=scope_state,
        read_episode_to=read_episode_to,
        read_episode_title=read_episode_title,
        latest_episode_no=latest_episode_no,
        synced_latest_episode_no=synced_latest_episode_no,
        can_send_message=bool(product_state.get("canSendMessage")),
        concierge_payload=concierge_payload,
    )
    guide_message = None
    pending_mode_entry_guide = str(session_memory.get("pending_mode_entry_guide") or "").strip().lower() or None
    if pending_mode_entry_guide == "rp_select":
        read_scope_label = await _build_websochat_read_scope_label(
            product_id=int(session_row["product_id"]),
            read_episode_to=read_episode_to,
            db=db,
        )
        guide_message = {
            "messageId": 0,
            "role": "assistant",
            "content": _build_websochat_rp_mode_entry_reply(
                read_scope_label=read_scope_label,
            ),
            "createdDate": (
                session_row["updated_date"].strftime("%Y-%m-%d %H:%M:%S")
                if isinstance(session_row["updated_date"], datetime)
                else str(session_row["updated_date"])
            ),
        }
    elif pending_mode_entry_guide == "qa_ready":
        read_scope_label = await _build_websochat_read_scope_label(
            product_id=int(session_row["product_id"]),
            read_episode_to=read_episode_to,
            db=db,
        )
        guide_message = {
            "messageId": 0,
            "role": "assistant",
            "content": _build_websochat_qa_mode_entry_reply(
                product_row=product_state,
                read_scope_label=read_scope_label,
            ),
            "createdDate": (
                session_row["updated_date"].strftime("%Y-%m-%d %H:%M:%S")
                if isinstance(session_row["updated_date"], datetime)
                else str(session_row["updated_date"])
            ),
        }
    logger.info(
        "websochat_debug get_messages session_id=%s message_count=%s starter=%s guide=%s scope_state=%s read_episode_to=%s rp_stage=%s rp_active_character=%s pending_mode_guide=%s",
        session_id,
        len(messages),
        bool(starter),
        bool(guide_message),
        scope_state,
        read_episode_to,
        rp_session_state["rpStage"],
        rp_session_state["rpActiveCharacterLabel"],
        pending_mode_entry_guide or "none",
    )

    return {
        "data": {
            "session": {
                "sessionId": session_row["session_id"],
                "productId": session_row["product_id"],
                "title": session_row["title"],
                "productTitle": product_state.get("title"),
                "productAuthorNickname": product_state.get("authorNickname"),
                "coverImagePath": product_state.get("coverImagePath"),
                "readScopeState": scope_state,
                "latestEpisodeNo": latest_episode_no,
                "publishedLatestEpisodeNo": latest_episode_no,
                "syncedLatestEpisodeNo": synced_latest_episode_no,
                "contextStatus": product_state.get("contextStatus"),
                "canSendMessage": bool(product_state.get("canSendMessage")),
                "unavailableMessage": product_state.get("unavailableMessage"),
                "createdDate": (
                    session_row["created_date"].strftime("%Y-%m-%d %H:%M:%S")
                    if isinstance(session_row["created_date"], datetime)
                    else str(session_row["created_date"])
                ),
                "updatedDate": (
                    session_row["updated_date"].strftime("%Y-%m-%d %H:%M:%S")
                    if isinstance(session_row["updated_date"], datetime)
                    else str(session_row["updated_date"])
                ),
                "readEpisodeNo": read_episode_to,
                "readEpisodeTitle": read_episode_title,
                "rpStage": rp_session_state["rpStage"],
                "rpActiveCharacterLabel": rp_session_state["rpActiveCharacterLabel"],
            },
            "messages": messages,
            "starter": starter,
            "guideMessage": guide_message,
        }
    }


@handle_exceptions
async def get_billing_status(
    kc_user_id: str | None,
    guest_key: str | None,
    qa_action_key: str | None,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, guest_key, db)
    used_count = await _get_websochat_daily_user_message_count(user_id, resolved_guest_key, db)
    cash_balance = None
    if user_id is not None:
        cash_balance = await _get_user_cash_balance_for_websochat(user_id=user_id, db=db)

    return {
        "data": _build_websochat_billing_status_payload(
            used_count=used_count,
            user_id=user_id,
            cash_balance=cash_balance,
            qa_action_key=qa_action_key,
        )
    }


@handle_exceptions
async def create_session(
    req_body: PostWebsochatSessionReqBody,
    kc_user_id: str | None,
    adult_yn: str,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, req_body.guest_key, db)
    effective_adult_yn = await _resolve_effective_adult_yn(
        kc_user_id=kc_user_id,
        adult_yn=adult_yn,
        db=db,
    )
    product_row = await _get_websochat_product(
        product_id=req_body.product_id,
        adult_yn=effective_adult_yn,
        db=db,
    )
    if not product_row:
        product_state = await _get_websochat_product_session_state(
            product_id=req_body.product_id,
            adult_yn=effective_adult_yn,
            db=db,
        )
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=product_state.get("unavailableMessage") or ErrorMessages.NOT_FOUND_PRODUCT,
        )
    if product_row.get("contextStatus") != "ready":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=WEBSOCHAT_CONTEXT_PENDING_MESSAGE,
        )

    title = (req_body.title or WEBSOCHAT_DEFAULT_TITLE).strip()[:120]
    resolution = await _resolve_websochat_active_character_resolution(
        product_id=req_body.product_id,
        active_character=req_body.active_character,
        db=db,
    )
    resolved_active_character = str(resolution.get("scopeKey") or "").strip() or None
    if req_body.active_character and not resolved_active_character:
        logger.info(
            "websochat rp_resolution_clarify product_id=%s raw=%s resolution_source=%s protagonist_intent=%s candidate_count=%s",
            req_body.product_id,
            req_body.active_character,
            str(resolution.get("resolutionSource") or "none"),
            bool(resolution.get("protagonistIntent")),
            int(resolution.get("candidateCount") or 0),
        )
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="누구와 이야기하고 싶은지 이름으로 한 번만 더 말해줘. 주인공이면 이름이나 주인공이라고 적어도 돼요.",
        )
    session_memory = _merge_websochat_session_memory(
        base_memory={},
        rp_mode=req_body.rp_mode,
        active_character=resolved_active_character,
        active_character_label=req_body.active_character,
        scene_episode_no=req_body.scene_episode_no,
        game_mode=req_body.game_mode,
        game_gender_scope=req_body.game_gender_scope,
        game_category=req_body.game_category,
        game_match_mode=req_body.game_match_mode,
        game_read_episode_to=req_body.game_read_episode_to,
    )
    session_memory = _apply_websochat_account_read_scope(
        session_memory,
        req_body.account_read_episode_to,
    )
    session_memory_json = _serialize_websochat_session_memory(session_memory)
    query = text(
        f"""
        INSERT INTO tb_story_agent_session
        (product_id, user_id, guest_key, title, session_memory_json, deleted_yn, expires_at, created_id, updated_id)
        VALUES (
            :product_id,
            :user_id,
            :guest_key,
            :title,
            :session_memory_json,
            'N',
            DATE_ADD(NOW(), INTERVAL {WEBSOCHAT_SESSION_TTL_DAYS} DAY),
            :created_id,
            :updated_id
        )
        """
    )
    created_id = user_id if user_id is not None else settings.DB_DML_DEFAULT_ID
    result = await db.execute(
        query,
        {
            "product_id": req_body.product_id,
            "user_id": user_id,
            "guest_key": resolved_guest_key,
            "title": title,
            "session_memory_json": session_memory_json,
            "created_id": created_id,
            "updated_id": created_id,
        },
    )
    session_id = result.lastrowid

    return {
        "data": {
            "sessionId": int(session_id),
            "productId": req_body.product_id,
            "title": title,
            "product": product_row,
        }
    }


@handle_exceptions
async def patch_session(
    session_id: int,
    req_body: PatchWebsochatSessionReqBody,
    kc_user_id: str | None,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, req_body.guest_key, db)
    await _get_session_row(session_id, user_id, resolved_guest_key, db)

    query = text(
        f"""
        UPDATE tb_story_agent_session
        SET title = :title,
            expires_at = DATE_ADD(NOW(), INTERVAL {WEBSOCHAT_SESSION_TTL_DAYS} DAY),
            updated_id = :updated_id,
            updated_date = NOW()
        WHERE session_id = :session_id
        """
    )
    await db.execute(
        query,
        {
            "title": req_body.title,
            "updated_id": user_id if user_id is not None else settings.DB_DML_DEFAULT_ID,
            "session_id": session_id,
        },
    )

    return {"data": {"sessionId": session_id, "title": req_body.title}}


@handle_exceptions
async def patch_session_mode(
    session_id: int,
    req_body: PatchWebsochatSessionModeReqBody,
    kc_user_id: str | None,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, req_body.guest_key, db)
    session_row = await _get_session_row(session_id, user_id, resolved_guest_key, db)
    session_memory = _normalize_websochat_session_memory(session_row.get("session_memory_json"))
    current_rp_stage = _resolve_websochat_rp_stage(session_memory)
    current_mode_key = "rp" if current_rp_stage in {"awaiting_character", "chatting"} else "qa"
    logger.info(
        "websochat_debug patch_session_mode:start session_id=%s current_mode=%s current_rp_stage=%s pending_rp=%s requested_mode=%s",
        session_id,
        current_mode_key,
        current_rp_stage,
        bool(session_memory.get("pending_rp_character_selection")),
        req_body.mode_key,
    )

    if (
        req_body.mode_key in {"qa", "rp"}
        and req_body.mode_key == current_mode_key
        and not req_body.force_entry_guide
    ):
        logger.info(
            "websochat_debug patch_session_mode:noop session_id=%s mode=%s pending_rp=%s",
            session_id,
            req_body.mode_key,
            bool(session_memory.get("pending_rp_character_selection")),
        )
        return {
            "data": {
                "sessionId": session_id,
                "modeKey": req_body.mode_key,
                "pendingRpCharacterSelection": bool(session_memory.get("pending_rp_character_selection")),
            }
        }

    next_session_memory = _clear_websochat_rp_context(_clear_websochat_game_context(session_memory))
    if req_body.mode_key == "rp":
        next_session_memory["pending_rp_character_selection"] = True
        next_session_memory["pending_mode_entry_guide"] = "rp_select"
    else:
        next_session_memory["pending_rp_character_selection"] = False
        if req_body.mode_key == "qa":
            next_session_memory["pending_mode_entry_guide"] = "qa_ready"

    await db.execute(
        text(
            f"""
            UPDATE tb_story_agent_session
            SET session_memory_json = :session_memory_json,
                expires_at = DATE_ADD(NOW(), INTERVAL {WEBSOCHAT_SESSION_TTL_DAYS} DAY),
                updated_id = :updated_id,
                updated_date = NOW()
            WHERE session_id = :session_id
            """
        ),
        {
            "session_memory_json": _serialize_websochat_session_memory(next_session_memory),
            "updated_id": user_id if user_id is not None else settings.DB_DML_DEFAULT_ID,
            "session_id": session_id,
        },
    )
    await db.commit()
    logger.info(
        "websochat_debug patch_session_mode:done session_id=%s next_mode=%s next_rp_stage=%s pending_rp=%s pending_mode_guide=%s",
        session_id,
        req_body.mode_key,
        _resolve_websochat_rp_stage(next_session_memory),
        bool(next_session_memory.get("pending_rp_character_selection")),
        str(next_session_memory.get("pending_mode_entry_guide") or "none"),
    )

    return {
        "data": {
            "sessionId": session_id,
            "modeKey": req_body.mode_key,
            "pendingRpCharacterSelection": bool(next_session_memory.get("pending_rp_character_selection")),
        }
    }


@handle_exceptions
async def patch_session_read_scope(
    session_id: int,
    req_body: PatchWebsochatSessionReadScopeReqBody,
    kc_user_id: str | None,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, req_body.guest_key, db)
    session_row = await _get_session_row(session_id, user_id, resolved_guest_key, db)
    session_memory = _normalize_websochat_session_memory(session_row.get("session_memory_json"))
    current_read_episode_to = max(int(session_memory.get("read_episode_to") or 0), 0)
    latest_visible_episode_no = await _get_websochat_latest_visible_episode_no(
        int(session_row["product_id"]),
        db=db,
    )
    requested_read_episode_to = min(
        max(int(req_body.read_episode_to or 0), 0),
        max(int(latest_visible_episode_no or 0), 0),
    )
    if requested_read_episode_to <= 0:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.NOT_FOUND_EPISODE,
        )

    resolved_read_episode_to = max(current_read_episode_to, requested_read_episode_to)
    if resolved_read_episode_to > current_read_episode_to:
        session_memory["read_episode_to"] = resolved_read_episode_to
        session_memory["read_scope_state"] = "known"
        session_memory["read_scope_source"] = "viewer"
        await db.execute(
            text(
                f"""
                UPDATE tb_story_agent_session
                SET session_memory_json = :session_memory_json,
                    expires_at = DATE_ADD(NOW(), INTERVAL {WEBSOCHAT_SESSION_TTL_DAYS} DAY),
                    updated_id = :updated_id,
                    updated_date = NOW()
                WHERE session_id = :session_id
                """
            ),
            {
                "session_memory_json": _serialize_websochat_session_memory(session_memory),
                "updated_id": user_id if user_id is not None else settings.DB_DML_DEFAULT_ID,
                "session_id": session_id,
            },
        )

    read_episode_title = await _get_websochat_visible_episode_title(
        int(session_row["product_id"]),
        resolved_read_episode_to,
        db=db,
    )
    return {
        "data": {
            "sessionId": session_id,
            "readScopeState": "known",
            "readEpisodeNo": resolved_read_episode_to,
            "readEpisodeTitle": read_episode_title,
        }
    }


@handle_exceptions
async def delete_session(
    session_id: int,
    guest_key: str | None,
    kc_user_id: str | None,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, guest_key, db)
    await _get_session_row(session_id, user_id, resolved_guest_key, db)

    query = text(
        """
        UPDATE tb_story_agent_session
        SET deleted_yn = 'Y',
            updated_id = :updated_id,
            updated_date = NOW()
        WHERE session_id = :session_id
        """
    )
    await db.execute(
        query,
        {
            "updated_id": user_id if user_id is not None else settings.DB_DML_DEFAULT_ID,
            "session_id": session_id,
        },
    )
    return {"data": {"sessionId": session_id, "deletedYn": "Y"}}


@handle_exceptions
async def post_message(
    session_id: int,
    req_body: PostWebsochatMessageReqBody,
    kc_user_id: str | None,
    db: AsyncSession,
):
    logger.info(
        "websochat_debug post_message:start session_id=%s starter_mode_key=%s qa_action_key=%s rp_mode=%s active_character=%s game_mode=%s client_message_id=%s prompt_preview=%r",
        session_id,
        req_body.starter_mode_key,
        req_body.qa_action_key,
        req_body.rp_mode,
        req_body.active_character,
        req_body.game_mode,
        req_body.client_message_id,
        _build_websochat_prompt_preview(req_body.content),
    )
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, req_body.guest_key, db)
    session_row = await _get_session_row(session_id, user_id, resolved_guest_key, db)
    current_session_memory = _normalize_websochat_session_memory(session_row.get("session_memory_json"))
    starter_mode_key = str(req_body.starter_mode_key or "").strip().lower() or None
    qa_action_key = str(req_body.qa_action_key or "").strip().lower() or None
    if starter_mode_key == "qa":
        current_session_memory = _clear_websochat_rp_context(_clear_websochat_game_context(current_session_memory))
    elif starter_mode_key == "rp":
        current_session_memory = _clear_websochat_rp_context(_clear_websochat_game_context(current_session_memory))
    elif starter_mode_key == "ideal_worldcup":
        current_session_memory = _clear_websochat_rp_context(_clear_websochat_game_context(current_session_memory))
    explicit_game_mode = req_body.game_mode
    if starter_mode_key == "ideal_worldcup" and not explicit_game_mode:
        explicit_game_mode = "ideal_worldcup"
    resolution = await _resolve_websochat_active_character_resolution(
        product_id=int(session_row["product_id"]),
        active_character=req_body.active_character,
        db=db,
    )
    resolved_active_character = str(resolution.get("scopeKey") or "").strip() or None
    if req_body.active_character and not resolved_active_character:
        logger.info(
            "websochat rp_resolution_clarify product_id=%s raw=%s resolution_source=%s protagonist_intent=%s candidate_count=%s",
            int(session_row["product_id"]),
            req_body.active_character,
            str(resolution.get("resolutionSource") or "none"),
            bool(resolution.get("protagonistIntent")),
            int(resolution.get("candidateCount") or 0),
        )
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="누구와 이야기하고 싶은지 이름으로 한 번만 더 말해줘. 주인공이면 이름이나 주인공이라고 적어도 돼요.",
        )
    next_session_memory = _merge_websochat_session_memory(
        base_memory=current_session_memory,
        rp_mode=req_body.rp_mode,
        active_character=resolved_active_character,
        active_character_label=req_body.active_character,
        scene_episode_no=req_body.scene_episode_no,
        game_mode=explicit_game_mode,
        game_gender_scope=req_body.game_gender_scope,
        game_category=req_body.game_category,
        game_match_mode=req_body.game_match_mode,
        game_read_episode_to=req_body.game_read_episode_to,
    )
    next_session_memory = _apply_websochat_account_read_scope(
        next_session_memory,
        req_body.account_read_episode_to,
    )
    logger.info(
        "websochat_debug post_message:memory session_id=%s current_rp_stage=%s next_rp_stage=%s pending_rp=%s resolved_active_character=%s active_character_label=%s",
        session_id,
        _resolve_websochat_rp_stage(current_session_memory),
        _resolve_websochat_rp_stage(next_session_memory),
        bool(next_session_memory.get("pending_rp_character_selection")),
        resolved_active_character,
        _resolve_websochat_active_character_label(next_session_memory),
    )
    if starter_mode_key not in {"qa", "rp"}:
        next_session_memory = apply_websochat_implicit_game_inputs(
            session_memory=next_session_memory,
            user_prompt=req_body.content,
            game_read_episode_to=req_body.game_read_episode_to,
        )
    effective_adult_yn = await _resolve_effective_adult_yn(
        kc_user_id=kc_user_id,
        adult_yn="Y",
        db=db,
    )
    product_row = await _get_websochat_product(
        product_id=int(session_row["product_id"]),
        adult_yn=effective_adult_yn,
        db=db,
    )
    if not product_row:
        product_state = await _get_websochat_product_session_state(
            product_id=int(session_row["product_id"]),
            adult_yn=effective_adult_yn,
            db=db,
        )
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=product_state.get("unavailableMessage") or WEBSOCHAT_PRODUCT_UNAVAILABLE_MESSAGE,
        )
    if product_row.get("contextStatus") != "ready":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=WEBSOCHAT_CONTEXT_PENDING_MESSAGE,
        )
    synced_latest_episode_no = _resolve_websochat_synced_latest_episode_no(product_row)
    latest_episode_no = max(int(product_row.get("latestEpisodeNo") or 0), 0)
    requested_next_episode_write = _is_websochat_noncanonical_action(
        req_body.qa_action_key
    ) or _is_websochat_next_episode_write_query(req_body.content)
    if requested_next_episode_write and latest_episode_no > synced_latest_episode_no:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=_build_websochat_next_episode_write_pending_message(synced_latest_episode_no),
        )
    inferred_prompt_read_episode_to = await _resolve_websochat_prompt_read_episode_to(
        product_id=int(session_row["product_id"]),
        latest_episode_no=latest_episode_no,
        user_prompt=req_body.content,
        db=db,
    )
    read_scope_decision: WebsochatPromptReadScopeDecision = _resolve_websochat_prompt_read_scope_decision(
        user_prompt=req_body.content,
        inferred_read_episode_to=inferred_prompt_read_episode_to,
    )
    if read_scope_decision["scope_state"] == "known" and read_scope_decision["read_episode_to"] is not None:
        next_session_memory["read_episode_to"] = int(read_scope_decision["read_episode_to"])
        next_session_memory["read_scope_state"] = "known"
        next_session_memory["read_scope_source"] = "prompt"
    elif read_scope_decision["scope_state"] == "none":
        next_session_memory["read_episode_to"] = None
        next_session_memory["read_scope_state"] = "none"
        next_session_memory["read_scope_source"] = "prompt"

    display_read_episode_to = _resolve_websochat_display_read_episode_to(
        scope_state=_resolve_websochat_read_scope_state(next_session_memory),
        latest_episode_no=latest_episode_no,
        synced_latest_episode_no=synced_latest_episode_no,
        requested_read_episode_to=next_session_memory.get("read_episode_to"),
    )
    logger.info(
        "websochat scope_resolution product_id=%s session_id=%s inferred_prompt_read_episode_to=%s scope_state=%s read_episode_to=%s is_scope_only=%s display_read_episode_to=%s latest_episode_no=%s synced_latest_episode_no=%s prompt_preview=%r",
        int(session_row["product_id"]),
        session_id,
        inferred_prompt_read_episode_to,
        read_scope_decision.get("scope_state"),
        read_scope_decision.get("read_episode_to"),
        bool(read_scope_decision.get("is_scope_only")),
        display_read_episode_to,
        latest_episode_no,
        synced_latest_episode_no,
        _build_websochat_prompt_preview(req_body.content),
    )

    created_id = user_id if user_id is not None else settings.DB_DML_DEFAULT_ID

    session_lock_conn: AsyncConnection | None = None
    try:
        session_lock_conn = await _acquire_websochat_session_lock(session_id=session_id)
        if session_lock_conn is None:
            raise CustomResponseException(
                status_code=status.HTTP_409_CONFLICT,
                message="같은 세션에서 다른 메시지를 처리 중입니다. 잠시 후 다시 시도해주세요.",
            )

        concierge_payload = None
        if _resolve_websochat_read_scope_state(next_session_memory) == "none":
            concierge_payload = await build_websochat_concierge_payload(
                product_row=product_row,
                user_id=user_id,
                db=db,
                user_prompt=req_body.content,
            )

        existing_messages = await _get_existing_turn_messages(
            session_id=session_id,
            client_message_id=req_body.client_message_id,
            latest_episode_no=await _get_websochat_latest_visible_episode_no(
                int(session_row["product_id"]),
                db=db,
            ),
            synced_latest_episode_no=synced_latest_episode_no,
            read_episode_to=next_session_memory.get("read_episode_to"),
            concierge_payload=concierge_payload,
            db=db,
        )
        if existing_messages:
            return {
                "data": {
                    "sessionId": session_id,
                    "messages": existing_messages,
                }
            }

        should_charge_cash = await _resolve_websochat_message_charge_required(
            user_id=user_id,
            guest_key=resolved_guest_key,
            db=db,
            qa_action_key=qa_action_key,
        )

        if read_scope_decision["is_scope_only"]:
            requested_read_episode_to = int(read_scope_decision["read_episode_to"] or 0) or None
            if (
                requested_read_episode_to is not None
                and synced_latest_episode_no > 0
                and requested_read_episode_to > synced_latest_episode_no
            ):
                assistant_reply = _build_websochat_sync_pending_read_scope_message(
                    requested_read_episode_to=requested_read_episode_to,
                    synced_latest_episode_no=synced_latest_episode_no,
                )
            else:
                assistant_reply = await _build_websochat_read_scope_confirm_reply(
                    product_id=int(session_row["product_id"]),
                    read_episode_to=display_read_episode_to,
                    db=db,
                )
            model_used = "system"
            route_mode = "scope:set"
            fallback_used = False
            intent = "scope"
            route_session_memory = None
        elif starter_mode_key == "qa" and not qa_action_key:
            read_scope_label = await _build_websochat_read_scope_label(
                product_id=int(session_row["product_id"]),
                read_episode_to=display_read_episode_to,
                db=db,
            )
            assistant_reply = _build_websochat_qa_mode_entry_reply(
                product_row=product_row,
                read_scope_label=read_scope_label,
            )
            model_used = "system"
            route_mode = "qa:starter"
            fallback_used = False
            intent = "starter"
            route_session_memory = next_session_memory
        elif starter_mode_key == "rp" and not resolved_active_character:
            read_scope_label = await _build_websochat_read_scope_label(
                product_id=int(session_row["product_id"]),
                read_episode_to=display_read_episode_to,
                db=db,
            )
            assistant_reply = _build_websochat_rp_mode_entry_reply(
                read_scope_label=read_scope_label,
            )
            model_used = "system"
            route_mode = "rp:starter"
            fallback_used = False
            intent = "starter"
            route_session_memory = next_session_memory
        else:
            forced_route = None
            if starter_mode_key == "rp" and resolved_active_character:
                forced_route = "rp"
            elif starter_mode_key == "ideal_worldcup":
                forced_route = "game"
            assistant_reply, model_used, route_mode, fallback_used, intent, route_session_memory = await _generate_websochat_reply(
                session_id=session_id,
                session_memory=next_session_memory,
                product_row=product_row,
                user_prompt=req_body.content,
                user_id=user_id,
                db=db,
                forced_route=forced_route,
            )
        await emit_websochat_stream_text_if_needed(assistant_reply)
        route_referenced_episode_nos: list[int] = []
        if route_session_memory is not None:
            route_referenced_episode_nos = [
                int(episode_no)
                for episode_no in list(route_session_memory.pop(WEBSOCHAT_QA_EPISODE_REF_MEMORY_KEY, []) or [])
                if int(episode_no or 0) > 0
            ]
            next_session_memory = _normalize_websochat_session_memory(route_session_memory)
        if route_mode not in {"qa:starter", "rp:starter"} and not _is_websochat_noncanonical_action(qa_action_key):
            next_session_memory = _update_websochat_session_memory_after_reply(
                next_session_memory,
                user_prompt=req_body.content,
                assistant_reply=assistant_reply,
            )

        insert_query = text(
            """
            INSERT INTO tb_story_agent_message (
                session_id, role, client_message_id, content, created_id
            )
            VALUES (
                :session_id, :role, :client_message_id, :content, :created_id
            )
            """
        )
        user_result = await db.execute(
            insert_query,
            {
                "session_id": session_id,
                "role": "user",
                "client_message_id": req_body.client_message_id,
                "content": _mark_websochat_noncanonical_message(req_body.content, qa_action_key=qa_action_key),
                "created_id": created_id,
            },
        )
        assistant_result = await db.execute(
            insert_query,
            {
                "session_id": session_id,
                "role": "assistant",
                "client_message_id": req_body.client_message_id,
                "content": _mark_websochat_noncanonical_message(assistant_reply, qa_action_key=qa_action_key),
                "created_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        if should_charge_cash:
            await _charge_websochat_cash(
                user_id=int(user_id),
                session_id=session_id,
                product_id=int(session_row["product_id"]),
                db=db,
                cash_cost=_resolve_websochat_message_cash_cost(qa_action_key),
            )

        update_title_query = text(
            f"""
            UPDATE tb_story_agent_session
            SET title = CASE
                    WHEN title = :default_title THEN :next_title
                    ELSE title
                END,
                session_memory_json = :session_memory_json,
                expires_at = DATE_ADD(NOW(), INTERVAL {WEBSOCHAT_SESSION_TTL_DAYS} DAY),
                updated_id = :updated_id,
                updated_date = NOW()
            WHERE session_id = :session_id
            """
        )
        await db.execute(
            update_title_query,
            {
                "default_title": WEBSOCHAT_DEFAULT_TITLE,
                "next_title": req_body.content[:40],
                "session_memory_json": _serialize_websochat_session_memory(next_session_memory),
                "updated_id": created_id,
                "session_id": session_id,
            },
        )

        await db.commit()
        logger.info(
            "websochat reply_completed model_used=%s intent=%s route_mode=%s fallback_used=%s product_id=%s session_id=%s charged_cash=%s prompt_preview=%r",
            model_used,
            intent,
            route_mode,
            "true" if fallback_used else "false",
            int(session_row["product_id"]),
            session_id,
            "true" if should_charge_cash else "false",
            _build_websochat_prompt_preview(req_body.content),
        )

        assistant_message = (
            {
                "messageId": int(assistant_result.lastrowid),
                "role": "assistant",
                "content": assistant_reply,
                "referencedEpisodeNos": [],
            }
            if route_mode == "qa:concierge"
            else _attach_websochat_message_episode_refs(
                {
                    "messageId": int(assistant_result.lastrowid),
                    "role": "assistant",
                    "content": assistant_reply,
                },
                latest_episode_no=_resolve_websochat_episode_ref_ceiling(
                    int(product_row.get("latestEpisodeNo") or 0),
                    _resolve_websochat_synced_latest_episode_no(product_row),
                    next_session_memory.get("read_episode_to"),
                ),
            )
        )
        if (
            not assistant_message.get("referencedEpisodeNos")
            and route_referenced_episode_nos
            and not route_mode.startswith("rp:")
            and route_mode != "qa:starter"
        ):
            assistant_message = {
                **assistant_message,
                "referencedEpisodeNos": sorted(set(route_referenced_episode_nos)),
            }
        logger.info(
            "websochat reply_episode_refs session_id=%s route_mode=%s referenced_episode_nos=%s reply_preview=%r",
            session_id,
            route_mode,
            assistant_message.get("referencedEpisodeNos"),
            str(assistant_reply or "")[:200],
        )

        return {
            "data": {
                "sessionId": session_id,
                "messages": [
                    {
                        "messageId": int(user_result.lastrowid),
                        "role": "user",
                        "content": req_body.content,
                    },
                    _attach_websochat_concierge_cards(
                        assistant_message,
                        concierge_payload if route_mode == "qa:concierge" else None,
                    ),
                ],
            }
        }
    except Exception:
        await db.rollback()
        raise
    finally:
        if session_lock_conn is not None:
            await _release_websochat_session_lock(session_id=session_id, conn=session_lock_conn)
