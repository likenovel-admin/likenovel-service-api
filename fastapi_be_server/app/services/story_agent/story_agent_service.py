from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.const import ErrorMessages, settings
from app.exceptions import CustomResponseException
from app.rdb import likenovel_db_engine
from app.schemas.story_agent import (
    PostStoryAgentMessageReqBody,
    PostStoryAgentSessionReqBody,
    PatchStoryAgentSessionReqBody,
)
from app.services.story_agent.story_agent_compare import (
    _build_story_agent_pair_key,
    _build_story_agent_worldcup_round,
    _extract_story_agent_direct_match_scope_keys,
    _filter_story_agent_worldcup_candidates_by_read_scope,
    _infer_story_agent_game_category_from_prompt,
    _pick_story_agent_unused_pair,
    _resolve_story_agent_pair_choice,
    _resolve_story_agent_worldcup_bracket_size,
)
from app.services.story_agent.story_agent_compare_runtime import (
    get_story_agent_game_candidate_profiles,
    select_story_agent_game_candidates,
)
from app.services.story_agent.story_agent_concierge import (
    build_story_agent_concierge_payload,
)
from app.services.story_agent.story_agent_context_assembler import assemble_story_agent_scope_context
from app.services.story_agent.story_agent_contracts import (
    StoryAgentCtaCard,
    StoryAgentEvidenceBundle,
    StoryAgentPromptReadScopeDecision,
    StoryAgentQaExecutionResult,
    StoryAgentReasonCard,
    StoryAgentScopeState,
    StoryAgentStarterAction,
)
from app.services.story_agent.story_agent_game_adapter import (
    apply_story_agent_implicit_game_inputs,
    build_story_agent_game_dispatch_plan,
    has_story_agent_worldcup_followup_signal,
    resolve_story_agent_worldcup_followup,
)
from app.services.story_agent.story_agent_game_memory import (
    STORY_AGENT_ALLOWED_GAME_CATEGORIES,
    STORY_AGENT_ALLOWED_GAME_GENDER_SCOPES,
    STORY_AGENT_ALLOWED_GAME_MODES,
    STORY_AGENT_ALLOWED_READ_SCOPE_STATES,
    STORY_AGENT_ALLOWED_RP_MODES,
    STORY_AGENT_ALLOWED_VS_GAME_MATCH_MODES,
    STORY_AGENT_PENDING_GAME_CATEGORY,
    STORY_AGENT_RP_RECENT_FACT_LIMIT,
    _build_story_agent_game_context,
    _clear_story_agent_game_context,
    _merge_story_agent_session_memory,
    _normalize_story_agent_game_state,
    _normalize_story_agent_games_memory,
    _normalize_story_agent_session_memory,
    _normalize_story_agent_string_list,
    _serialize_story_agent_session_memory,
    _update_story_agent_session_memory_after_reply,
)
from app.services.story_agent.story_agent_context_loader import (
    build_story_agent_scope_context_message,
)
from app.services.story_agent.story_agent_planner import (
    _build_story_agent_qa_plan,
    _build_story_agent_rp_plan,
    _resolve_story_agent_response_route,
)
from app.services.story_agent.story_agent_qa_executor import (
    StoryAgentQaExecutionHooks,
    execute_story_agent_qa,
)
from app.services.story_agent.story_agent_qa_renderer import build_story_agent_recent_context_message
from app.services.story_agent.story_agent_rp_renderer import (
    generate_story_agent_rp_reply_with_claude,
    generate_story_agent_rp_reply_with_gemini,
)
from app.services.story_agent.story_agent_renderers import generate_story_agent_vs_comparison
from app.services.story_agent.story_agent_renderers import (
    build_story_agent_game_guide_reply,
    build_story_agent_vs_disabled_reply,
)
from app.services.story_agent.story_agent_scope_resolver import (
    STORY_AGENT_EXACT_EPISODE_RE,
    STORY_AGENT_KOREAN_ORDINAL_MAP,
    STORY_AGENT_ORDINAL_EPISODE_RE,
    _infer_story_agent_read_episode_to_from_prompt,
    _is_story_agent_unread_scope_prompt,
    _resolve_story_agent_prompt_read_scope_decision,
    _resolve_story_agent_scope_read_episode_to,
)
from app.services.story_agent.story_agent_utils import _extract_story_agent_json_object
from app.services.ai.ai_chat_service import _call_claude_messages, _extract_text, _extract_tool_use_blocks, _to_json_safe
from app.services.common.comm_service import get_user_from_kc
from app.utils.common import handle_exceptions
from app.utils.query import get_file_path_sub_query
from app.utils.time import get_full_age

STORY_AGENT_DEFAULT_TITLE = "새 대화"
STORY_AGENT_SESSION_LOCK_TIMEOUT_SECONDS = 0
STORY_AGENT_SESSION_TTL_DAYS = 30
STORY_AGENT_DAILY_FREE_MESSAGE_LIMIT = 2
STORY_AGENT_MESSAGE_CASH_COST = 20
STORY_AGENT_PRODUCT_UNAVAILABLE_MESSAGE = "비공개된 작품과는 더이상 이야기하실 수 없습니다."
STORY_AGENT_CONTEXT_PENDING_MESSAGE = "이 작품은 아직 대화 준비 중입니다."
STORY_AGENT_PLACEHOLDER_TEMPLATE = (
    "[{title}] 기준으로 관련 회차와 원문 일부를 먼저 찾았습니다.\n"
    "{context_block}\n\n"
    "질문: {user_prompt}\n"
    "다음 단계에서 이 컨텍스트를 바탕으로 실제 T2T/T2I 응답을 붙입니다."
)
STORY_AGENT_MAX_TOOL_ROUNDS = 4
STORY_AGENT_MAX_HISTORY_MESSAGES = 10
STORY_AGENT_MAX_EPISODE_CONTENT_CHARS = 6000
STORY_AGENT_PREFETCH_CONTEXT_CHARS = 3000
STORY_AGENT_BROAD_SUMMARY_CONTEXT_LIMIT = 6
STORY_AGENT_GEMINI_CONTEXT_EPISODE_LIMIT = 2
STORY_AGENT_REFERENCE_RESOLUTION_MAX_TOKENS = 220
STORY_AGENT_INTENT_MAX_TOKENS = 120
STORY_AGENT_ALLOWED_INTENTS = {
    "factual",
    "comparative",
    "playful",
    "self_insert",
    "simulation",
}
STORY_AGENT_EPISODE_RANGE_RE = re.compile(r"(\d{1,4})\s*(?:~|-|–|—)\s*(\d{1,4})\s*화")
STORY_AGENT_EPISODE_SINGLE_RE = re.compile(r"(\d{1,4})\s*화")
STORY_AGENT_ALLOWED_SUMMARY_MODES = {"exact", "early", "latest", "general"}
STORY_AGENT_TOOLS = [
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
STORY_AGENT_KEYWORD_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
STORY_AGENT_KEYWORD_STOPWORDS = {
    "그리고", "하지만", "그러나", "이번", "저번", "그녀", "그는", "그것", "이것", "저것",
    "에게", "에서", "한다", "했다", "했다는", "있다", "있는", "없다", "없고", "정도", "처럼",
    "위해", "통해", "이후", "이전", "장면", "회차", "작품", "내용", "상태", "주인공", "분석",
}
STORY_AGENT_EARLY_QUESTION_KEYWORDS = (
    "초반", "처음", "첫 ", "첫등장", "첫 등장", "첫발현", "첫 발현", "첫 각성", "처음 각성",
)
STORY_AGENT_BROAD_QUESTION_KEYWORDS = (
    "최신", "현재", "지금", "최근", "갈등", "관계", "떡밥", "미해결", "변화",
)
STORY_AGENT_AMBIGUOUS_REFERENCE_PATTERNS = (
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


def _resolve_story_agent_read_scope_state(
    session_memory: dict[str, Any],
) -> StoryAgentScopeState:
    normalized_state = str(session_memory.get("read_scope_state") or "").strip().lower()
    if normalized_state in STORY_AGENT_ALLOWED_READ_SCOPE_STATES:
        return normalized_state  # type: ignore[return-value]
    if int(session_memory.get("read_episode_to") or 0) > 0:
        return "known"
    return "unknown"


def _build_story_agent_cta_cards(
    cta_cards: list[StoryAgentCtaCard] | None,
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


def _attach_story_agent_concierge_cards(
    message: dict[str, Any],
    concierge_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if message.get("role") != "assistant" or not concierge_payload:
        return message
    return {
        **message,
        "reasonCards": list(concierge_payload.get("reasonCards") or []),
        "actionCards": list(concierge_payload.get("actions") or []),
        "ctaCards": _build_story_agent_cta_cards(concierge_payload.get("ctaCards") or []),
    }


def _attach_story_agent_concierge_to_last_assistant_message(
    messages: list[dict[str, Any]],
    concierge_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not concierge_payload:
        return messages
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") != "assistant":
            continue
        enriched = list(messages)
        enriched[index] = _attach_story_agent_concierge_cards(enriched[index], concierge_payload)
        return enriched
    return messages


def _build_story_agent_starter(
    *,
    product_title: str,
    scope_state: StoryAgentScopeState,
    read_episode_to: int | None,
    read_episode_title: str | None,
    latest_episode_no: int,
    can_send_message: bool,
    concierge_payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not can_send_message:
        return None

    normalized_title = str(product_title or "").strip() or "이 작품"
    resolved_read_episode_to = max(min(int(read_episode_to or 0), max(latest_episode_no, 0)), 0) or None
    prompt_prefix = f"{resolved_read_episode_to}화까지 기준으로 " if resolved_read_episode_to else ""
    default_actions: list[StoryAgentStarterAction] = [
        {
            "label": "작품 얘기",
            "prompt": f"{prompt_prefix}작품 핵심 포인트를 이야기해줘",
        },
        {
            "label": "캐릭터와 대화",
            "prompt": f"{prompt_prefix}인상적인 캐릭터 한 명을 골라 그 말투로 인사해줘",
        },
        {
            "label": "다음 전개 예상",
            "prompt": f"{prompt_prefix}앞으로 전개를 예상해줘",
        },
        {
            "label": "인물 비교",
            "prompt": f"{prompt_prefix}인물 둘을 비교해줘",
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
        "reasonCards": list(concierge_payload.get("reasonCards") or []) if concierge_payload else [],
        "ctaCards": _build_story_agent_cta_cards(concierge_payload.get("ctaCards") or []) if concierge_payload else [],
        "actions": starter_actions,
    }


def _build_story_agent_read_scope_required_reply() -> str:
    return (
        "읽은 회차가 아직 안 잡혔어.\n"
        "스포일러 안 섞이게 어디까지 읽었는지 먼저 알려줘.\n"
        "예: 프롤로그까지 읽었어 / 습격까지 읽었어 / 아직 시작 안 했어"
    )


async def _build_story_agent_read_scope_confirm_reply(
    *,
    product_id: int,
    read_episode_to: int | None,
    db: AsyncSession,
) -> str:
    read_scope_label = await _build_story_agent_read_scope_label(
        product_id=product_id,
        read_episode_to=read_episode_to,
        db=db,
    )
    if not read_scope_label:
        return "좋아. 읽은 범위를 잡아둘게. 이 범위 안에서만 이야기할게."
    return (
        f"좋아. 읽은 범위는 {read_scope_label}까지로 잡아둘게.\n"
        "이 범위 안에서만 이야기할게."
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


async def _get_story_agent_product(product_id: int, adult_yn: str, db: AsyncSession) -> dict[str, Any] | None:
    ratings_filter = "" if adult_yn == "Y" else "AND p.ratings_code = 'all'"
    query = text(
        f"""
        SELECT
            p.product_id AS productId,
            p.title,
            p.author_name AS authorNickname,
            p.story_agent_setting_text AS storyAgentSetting,
            {get_file_path_sub_query('p.thumbnail_file_id', 'coverImagePath')},
            p.status_code AS statusCode,
            COALESCE(sacp.context_status, 'pending') AS contextStatus,
            COALESCE(MAX(e.episode_no), 0) AS latestEpisodeNo
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
        GROUP BY p.product_id, p.title, p.author_name, p.story_agent_setting_text, p.thumbnail_file_id, p.status_code, sacp.context_status
        """
    )
    result = await db.execute(query, {"product_id": product_id})
    row = result.mappings().one_or_none()
    return dict(row) if row else None


async def _get_story_agent_product_session_state(
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
            COALESCE(MAX(e.episode_no), 0) AS latestEpisodeNo
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
            sacp.context_status
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
            "canSendMessage": False,
            "unavailableMessage": STORY_AGENT_PRODUCT_UNAVAILABLE_MESSAGE,
        }

    product = dict(row)
    can_send_message = (
        product.get("priceType") == "free"
        and product.get("openYn") == "Y"
        and product.get("blindYn") == "N"
        and product.get("contextStatus") == "ready"
        and (adult_yn == "Y" or product.get("ratingsCode") == "all")
    )
    unavailable_message = None
    if not can_send_message:
        if product.get("priceType") != "free" or product.get("openYn") != "Y" or product.get("blindYn") != "N":
            unavailable_message = STORY_AGENT_PRODUCT_UNAVAILABLE_MESSAGE
        elif product.get("contextStatus") != "ready":
            unavailable_message = STORY_AGENT_CONTEXT_PENDING_MESSAGE
        elif adult_yn != "Y" and product.get("ratingsCode") != "all":
            unavailable_message = STORY_AGENT_PRODUCT_UNAVAILABLE_MESSAGE
        else:
            unavailable_message = STORY_AGENT_PRODUCT_UNAVAILABLE_MESSAGE
    return {
        **product,
        "canSendMessage": can_send_message,
        "unavailableMessage": unavailable_message,
    }


async def _get_story_agent_latest_visible_episode_no(
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


def _resolve_story_agent_episode_ref_ceiling(
    latest_episode_no: int | None,
    read_episode_to: int | None,
) -> int:
    latest_visible = max(0, int(latest_episode_no or 0))
    read_scope = max(0, int(read_episode_to or 0))
    if latest_visible <= 0:
        return 0
    if read_scope <= 0:
        return latest_visible
    return min(latest_visible, read_scope)


async def _get_story_agent_visible_episode_title(
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


async def _build_story_agent_read_scope_label(
    *,
    product_id: int,
    read_episode_to: int | None,
    db: AsyncSession,
) -> str | None:
    resolved_read_episode_to = max(int(read_episode_to or 0), 0)
    if resolved_read_episode_to <= 0:
        return None
    episode_title = await _get_story_agent_visible_episode_title(
        product_id=product_id,
        episode_no=resolved_read_episode_to,
        db=db,
    )
    if episode_title:
        return f"{resolved_read_episode_to}화({episode_title})"
    return f"{resolved_read_episode_to}화"


def _normalize_story_agent_scope_lookup_text(raw_text: str | None) -> str:
    normalized = re.sub(r"\s+", "", str(raw_text or "").strip().lower())
    return re.sub(r"[^0-9a-z가-힣]", "", normalized)


def _extract_story_agent_episode_title_aliases(episode_title: str | None) -> list[str]:
    aliases: list[str] = []

    def append_alias(raw_value: str | None) -> None:
        normalized = _normalize_story_agent_scope_lookup_text(raw_value)
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


def _augment_story_agent_episode_title_aliases(
    *,
    episode_no: int,
    episode_title: str | None,
) -> list[str]:
    aliases = _extract_story_agent_episode_title_aliases(episode_title)
    if episode_no == 1:
        for alias in ("프롤로그", "prologue"):
            normalized = _normalize_story_agent_scope_lookup_text(alias)
            if normalized and normalized not in aliases:
                aliases.append(normalized)
    return aliases


async def _resolve_story_agent_prompt_episode_title_scope(
    *,
    product_id: int,
    latest_episode_no: int,
    user_prompt: str,
    db: AsyncSession,
) -> int | None:
    prompt_lookup = _normalize_story_agent_scope_lookup_text(user_prompt)
    if not prompt_lookup or latest_episode_no <= 0:
        return None

    episode_rows = await _get_story_agent_public_episode_refs(
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
                for alias in _augment_story_agent_episode_title_aliases(
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


async def _resolve_story_agent_prompt_read_episode_to(
    *,
    product_id: int,
    latest_episode_no: int,
    user_prompt: str,
    db: AsyncSession,
) -> int | None:
    if _is_story_agent_unread_scope_prompt(user_prompt):
        return 0

    resolved_from_title = await _resolve_story_agent_prompt_episode_title_scope(
        product_id=product_id,
        latest_episode_no=latest_episode_no,
        user_prompt=user_prompt,
        db=db,
    )
    if resolved_from_title is not None:
        return resolved_from_title

    return _infer_story_agent_read_episode_to_from_prompt(
        user_prompt,
        latest_episode_no=latest_episode_no,
    )


def _extract_story_agent_keywords(content: str) -> list[str]:
    keywords: list[str] = []
    for token in STORY_AGENT_KEYWORD_RE.findall(content or ""):
        normalized = token.strip()
        if len(normalized) < 2 or normalized in STORY_AGENT_KEYWORD_STOPWORDS:
            continue
        if normalized in keywords:
            continue
        keywords.append(normalized)
        if len(keywords) >= 6:
            break
    return keywords


def _resolve_story_agent_summary_mode(
    query_text: str,
    latest_episode_no: int,
    mode: str | None = None,
    episode_no: int | None = None,
) -> tuple[str, int | None, int | None, int]:
    normalized_query = (query_text or "").strip()
    normalized_mode = (mode or "").strip().lower()
    exact_episode_no = int(episode_no) if episode_no else None

    if normalized_mode not in {"exact", "early", "latest", "general"}:
        exact_match = STORY_AGENT_EXACT_EPISODE_RE.search(normalized_query)
        ordinal_match = STORY_AGENT_ORDINAL_EPISODE_RE.search(normalized_query)
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
        elif any(keyword in normalized_query for keyword in STORY_AGENT_EARLY_QUESTION_KEYWORDS):
            normalized_mode = "early"
        elif any(keyword in normalized_query for keyword in STORY_AGENT_BROAD_QUESTION_KEYWORDS):
            normalized_mode = "latest"
        else:
            normalized_mode = "general"

    if normalized_mode == "exact":
        label_episode_no, ordinal_index = _extract_story_agent_episode_reference(
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

    limit = 5 if any(keyword in normalized_query for keyword in STORY_AGENT_BROAD_QUESTION_KEYWORDS) else 3
    return normalized_mode, exact_episode_no, None, limit


def _extract_story_agent_episode_reference(
    query_text: str,
    fallback_episode_no: int | None = None,
) -> tuple[int | None, int | None]:
    normalized_query = (query_text or "").strip()
    exact_match = STORY_AGENT_EXACT_EPISODE_RE.search(normalized_query)
    if exact_match:
        return int(exact_match.group(1)), None

    ordinal_match = STORY_AGENT_ORDINAL_EPISODE_RE.search(normalized_query)
    if ordinal_match:
        return None, int(ordinal_match.group(1))

    for word, value in STORY_AGENT_KOREAN_ORDINAL_MAP.items():
        if f"{word} 번째 화" in normalized_query or f"{word}번째 화" in normalized_query:
            return None, value

    return fallback_episode_no, None


async def _get_story_agent_public_episode_refs(
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


async def _resolve_story_agent_exact_episode_no(
    *,
    product_id: int,
    latest_episode_no: int,
    query_text: str,
    fallback_episode_no: int | None,
    db: AsyncSession,
) -> int | None:
    label_episode_no, ordinal_index = _extract_story_agent_episode_reference(
        query_text=query_text,
        fallback_episode_no=fallback_episode_no,
    )
    episode_rows = await _get_story_agent_public_episode_refs(
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


async def _get_story_agent_summary_candidates(
    product_id: int,
    keywords: list[str],
    query_text: str,
    latest_episode_no: int,
    mode: str | None,
    episode_no: int | None,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"product_id": product_id}
    score_parts: list[str] = []
    for idx, keyword in enumerate(keywords, start=1):
        key = f"keyword_{idx}"
        params[key] = f"%{keyword}%"
        score_parts.append(f"CASE WHEN summary_text LIKE :{key} THEN 1 ELSE 0 END")
    score_sql = " + ".join(score_parts) if score_parts else "0"

    resolved_mode, exact_episode_no, range_anchor, limit = _resolve_story_agent_summary_mode(
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
        resolved_episode_no = await _resolve_story_agent_exact_episode_no(
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


def _merge_story_agent_summary_rows(
    *groups: list[dict[str, Any]],
    limit: int = STORY_AGENT_BROAD_SUMMARY_CONTEXT_LIMIT,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_keys: set[tuple[int, int]] = set()
    for rows in groups:
        for row in rows:
            episode_from = int(row.get("episodeFrom") or 0)
            episode_to = int(row.get("episodeTo") or 0)
            key = (episode_from, episode_to)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged.append(row)
            if len(merged) >= limit:
                return merged
    return merged


async def _get_story_agent_broad_summary_context_rows(
    *,
    product_id: int,
    query_text: str,
    latest_episode_no: int,
    resolved_mode: str,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    keywords = _extract_story_agent_keywords(query_text)

    if resolved_mode == "exact":
        return []

    if resolved_mode == "early":
        return await _get_story_agent_summary_candidates(
            product_id=product_id,
            keywords=keywords,
            query_text=query_text,
            latest_episode_no=latest_episode_no,
            mode="early",
            episode_no=None,
            db=db,
        )

    if resolved_mode == "latest":
        return await _get_story_agent_summary_candidates(
            product_id=product_id,
            keywords=keywords,
            query_text=query_text,
            latest_episode_no=latest_episode_no,
            mode="latest",
            episode_no=None,
            db=db,
        )

    general_rows = await _get_story_agent_summary_candidates(
        product_id=product_id,
        keywords=keywords,
        query_text=query_text,
        latest_episode_no=latest_episode_no,
        mode="general",
        episode_no=None,
        db=db,
    )
    early_rows = await _get_story_agent_summary_candidates(
        product_id=product_id,
        keywords=keywords,
        query_text=query_text,
        latest_episode_no=latest_episode_no,
        mode="early",
        episode_no=None,
        db=db,
    )
    latest_rows = await _get_story_agent_summary_candidates(
        product_id=product_id,
        keywords=keywords,
        query_text=query_text,
        latest_episode_no=latest_episode_no,
        mode="latest",
        episode_no=None,
        db=db,
    )
    return _merge_story_agent_summary_rows(
        general_rows[:2],
        early_rows[:2],
        latest_rows[:2],
    )


def _build_story_agent_summary_context_message(summary_rows: list[dict[str, Any]]) -> str:
    if not summary_rows:
        return ""

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

    return (
        "아래는 이번 질문과 관련해 먼저 참고할 공개 회차 요약이다. "
        "넓거나 모호한 질문이면 여기서 확인되는 핵심 2~3가지를 먼저 짚고, "
        "마지막에 어떤 축이 더 궁금한지 한 문장으로 좁혀 물어라.\n\n"
        + "\n\n".join(blocks)
    )


async def _get_story_agent_product_context(product_id: int, db: AsyncSession) -> dict[str, Any]:
    result = await db.execute(
        text(
            f"""
            SELECT
                p.product_id AS productId,
                p.title,
                p.author_name AS authorNickname,
                p.story_agent_setting_text AS storyAgentSetting,
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


async def _search_story_agent_episode_contents(
    product_id: int,
    query_text: str,
    latest_episode_no: int,
    db: AsyncSession,
) -> list[dict[str, Any]]:
    keywords = _extract_story_agent_keywords(query_text)
    params: dict[str, Any] = {"product_id": product_id}
    where_parts: list[str] = []
    for idx, keyword in enumerate(keywords, start=1):
        key = f"keyword_{idx}"
        params[key] = f"%{keyword}%"
        where_parts.append(f"c.text LIKE :{key}")
    if not where_parts:
        params["keyword_fallback"] = f"%{(query_text or '').strip()[:40]}%"
        where_parts.append("c.text LIKE :keyword_fallback")

    result = await db.execute(
        text(
            f"""
            SELECT
                c.episode_no AS episodeNo,
                LEFT(c.text, 300) AS chunkText
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
            ORDER BY c.episode_no ASC, c.chunk_no ASC
            LIMIT 6
            """
        ),
        {**params, "latest_episode_no": latest_episode_no},
    )
    return [dict(row) for row in result.mappings().all()]


async def _get_story_agent_episode_contents(
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
        current["content"] = next_text[:STORY_AGENT_MAX_EPISODE_CONTENT_CHARS]
    return list(grouped.values())


async def _get_story_agent_recent_messages(session_id: int, db: AsyncSession) -> list[dict[str, str]]:
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
            "limit": STORY_AGENT_MAX_HISTORY_MESSAGES,
        },
    )
    rows = [dict(row) for row in result.mappings().all()]
    rows.reverse()
    return [
        {
            "role": str(row.get("role") or "user"),
            "content": str(row.get("content") or "")[:2000],
        }
        for row in rows
        if str(row.get("content") or "").strip()
    ]


def _build_story_agent_system_prompt(product_row: dict[str, Any]) -> str:
    title = str(product_row.get("title") or "작품")
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    story_agent_setting = str(product_row.get("storyAgentSetting") or "").strip()
    setting_block = (
        f" 작품 보조 설정: {story_agent_setting} "
        if story_agent_setting
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
        "질문이 넓거나 모호하면 거절하거나 '질문을 좁혀 달라'로 끝내지 마라. 먼저 공개 범위에서 확인되는 핵심 2~3가지를 짧게 답하고, 마지막에 어떤 축으로 더 좁혀서 볼지 한 문장으로 되물어라. "
        "예를 들면 능력 규칙, 세력 질서, 인물 관계, 전투 상성 중 무엇이 궁금한지 되묻는 식으로 대화를 이어가라. "
        "사용자가 '저/그/이 선택', '저/그/이 장면', '그때', '그거'처럼 지시대명사로 모호하게 물으면 섣불리 하나를 확정하지 마라. "
        "최근 대화와 이번 질문 관련 요약을 기준으로 유력한 후보가 1~2개면 짧게 제시하되, 먼저 한 번의 질문으로 범위를 좁혀라. "
        "이때 몇 번째 회차인지, 언제 공개된 회차인지, 초반/중반/최신 중 어디쯤인지, 기억나는 회차명이나 장면 키워드가 있는지를 한 번에 함께 물어라. "
        "사용자가 추가 단서를 주기 전에는 특정 장면이나 선택을 사실처럼 단정하지 마라. "
        "도구를 1~2번 조회한 뒤에도 근거가 부족하면, 공개 범위에서 확인되는 부분만 짧게 답하고 더 이상의 tool 호출은 멈춰라. "
        "답변은 한국어로, 불필요한 군더더기 없이 바로 답하라. 관련 회차 번호가 있으면 자연스럽게 포함하라."
    )


def _is_story_agent_ambiguous_reference_query(query_text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(query_text or "")).strip()
    if not normalized:
        return False
    return any(pattern in normalized for pattern in STORY_AGENT_AMBIGUOUS_REFERENCE_PATTERNS)


def _get_story_agent_game_state(
    session_memory: dict[str, Any],
    *,
    game_mode: str,
    gender_scope: str,
    category: str,
) -> dict[str, Any]:
    normalized = _normalize_story_agent_session_memory(session_memory)
    return _normalize_story_agent_game_state(
        game_mode,
        ((((normalized.get("games") or {}).get(game_mode) or {}).get(gender_scope) or {}).get(category) or {}),
    )


def _set_story_agent_game_state(
    session_memory: dict[str, Any],
    *,
    game_mode: str,
    gender_scope: str,
    category: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    normalized = _normalize_story_agent_session_memory(session_memory)
    games = dict(normalized.get("games") or {})
    scope_map = dict((games.get(game_mode) or {}))
    category_map = dict((scope_map.get(gender_scope) or {}))
    category_map[category] = _normalize_story_agent_game_state(game_mode, state)
    scope_map[gender_scope] = category_map
    games[game_mode] = scope_map
    normalized["games"] = _normalize_story_agent_games_memory(games)
    normalized["active_mode"] = game_mode
    normalized["game_context"] = _build_story_agent_game_context(
        game_mode=game_mode,
        game_gender_scope=gender_scope,
        game_category=category if category in STORY_AGENT_ALLOWED_GAME_CATEGORIES else None,
        game_match_mode=(state or {}).get("mode") if game_mode == "vs_game" else None,
    )
    return normalized


def _build_story_agent_worldcup_meta_reply(
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


def _build_story_agent_worldcup_setup_meta_reply(
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


async def _generate_story_agent_worldcup_reply(
    *,
    session_memory: dict[str, Any],
    product_row: dict[str, Any],
    user_prompt: str,
    db: AsyncSession,
) -> tuple[str, dict[str, Any]]:
    normalized = _normalize_story_agent_session_memory(session_memory)
    game_context = normalized.get("game_context") or {}
    gender_scope = str(game_context.get("gender_scope") or "").strip().lower()
    category = str(game_context.get("category") or "").strip().lower()
    product_id = int(product_row.get("productId") or 0)
    if not gender_scope or not category:
        read_scope_label = await _build_story_agent_read_scope_label(
            product_id=product_id,
            read_episode_to=normalized.get("read_episode_to"),
            db=db,
        )
        return (
            build_story_agent_game_guide_reply(
                session_memory=normalized,
                product_row=product_row,
                read_scope_label=read_scope_label,
            )
            or "",
            normalized,
        )

    state = _get_story_agent_game_state(
        normalized,
        game_mode="ideal_worldcup",
        gender_scope=gender_scope,
        category=category,
    )
    followup = resolve_story_agent_worldcup_followup(user_prompt=user_prompt)
    if followup["exit_requested"]:
        reply = "좋아. 월드컵은 여기서 멈추고 일반 모드로 돌아갈게. 이제 작품 얘기나 분석으로 이어가면 돼."
        return reply, _clear_story_agent_game_context(normalized)
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    inferred_read_episode_to = await _resolve_story_agent_prompt_read_episode_to(
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
        normalized = _merge_story_agent_session_memory(
            base_memory=normalized,
            rp_mode=None,
            active_character=None,
            scene_episode_no=None,
            game_mode="ideal_worldcup",
            game_gender_scope=requested_gender_scope or gender_scope,
            game_category=requested_category or category,
            game_read_episode_to=inferred_read_episode_to or previous_read_episode_to,
        )
        game_context = normalized.get("game_context") or {}
        gender_scope = str(game_context.get("gender_scope") or "").strip().lower()
        category = str(game_context.get("category") or "").strip().lower()
        state = _get_story_agent_game_state(
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

    read_scope_label = await _build_story_agent_read_scope_label(
        product_id=product_id,
        read_episode_to=state.get("read_episode_to"),
        db=db,
    )

    if not state.get("read_episode_to"):
        reply = (
            "월드컵은 읽은 범위 기준으로만 돌릴게.\n"
            "어디까지 읽었는지 말해줘. 예: 3화까지 읽었어 / 프롤로그까지 읽었어"
        )
        return reply, _set_story_agent_game_state(
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
            reply = _build_story_agent_worldcup_meta_reply(
                product_row=product_row,
                gender_scope=gender_scope,
                category=category,
                state=state,
                read_scope_label=read_scope_label,
                current_pair=current_pair,
            )
            return reply, _set_story_agent_game_state(
                normalized,
                game_mode="ideal_worldcup",
                gender_scope=gender_scope,
                category=category,
                state=state,
            )
        chosen = _resolve_story_agent_pair_choice(user_prompt, current_pair)
        if chosen is None and not followup["resume_requested"]:
            reply = (
                f"지금 매치업은 {current_pair[0]} vs {current_pair[1]}야.\n"
                "둘 중 하나만 골라줘. 이름을 그대로 말하거나 1번/2번으로 골라도 돼."
            )
            return reply, _set_story_agent_game_state(
                normalized,
                game_mode="ideal_worldcup",
                gender_scope=gender_scope,
                category=category,
                state=state,
            )
        if chosen is not None:
            pair_key = _build_story_agent_pair_key(current_pair[0], current_pair[1])
            state["used_pair_keys"] = _normalize_story_agent_string_list(
                [*(state.get("used_pair_keys") or []), pair_key],
                limit=128,
            )
            state["picks"] = _normalize_story_agent_string_list([*(state.get("picks") or []), chosen], limit=16)
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
            return reply, _set_story_agent_game_state(
                normalized,
                game_mode="ideal_worldcup",
                gender_scope=gender_scope,
                category=category,
                state=state,
            )

        winners = _normalize_story_agent_string_list(state.get("picks"), limit=8)
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
            return reply, _set_story_agent_game_state(
                normalized,
                game_mode="ideal_worldcup",
                gender_scope=gender_scope,
                category=category,
                state=state,
            )

        next_round, round_label = _build_story_agent_worldcup_round(winners, [])
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
            return reply, _set_story_agent_game_state(
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
        return reply, _set_story_agent_game_state(
            normalized,
            game_mode="ideal_worldcup",
            gender_scope=gender_scope,
            category=category,
            state=state,
        )

    candidates = await get_story_agent_game_candidate_profiles(
        product_id=int(product_row.get("productId") or 0),
        db=db,
    )
    visible_candidates = _filter_story_agent_worldcup_candidates_by_read_scope(
        candidates,
        read_episode_to=int(state.get("read_episode_to") or 0),
    )
    bracket_size, bracket_reason = _resolve_story_agent_worldcup_bracket_size(
        read_episode_to=int(state.get("read_episode_to") or 0),
        requested_size=int(state.get("requested_bracket_size") or 0) or None,
        stable_candidate_count=len(visible_candidates),
    )
    if bracket_size == 0:
        reply = (
            f"{read_scope_label or f'{int(state.get('read_episode_to') or 0)}화'} 기준으로는 월드컵으로 돌릴 후보가 아직 부족해.\n"
            "더 읽은 범위로 넓혀주면 다시 잡아볼게."
        )
        return reply, _set_story_agent_game_state(
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
            return reply, _set_story_agent_game_state(
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
            return reply, _set_story_agent_game_state(
                normalized,
                game_mode="ideal_worldcup",
                gender_scope=gender_scope,
                category=category,
                state=state,
            )
    selected_candidates = visible_candidates[:bracket_size]
    selected_names = [item["display_name"] for item in selected_candidates]
    next_round, round_label = _build_story_agent_worldcup_round(selected_names, state.get("used_pair_keys") or [])
    if not next_round:
        reply = (
            f"{read_scope_label or f'{int(state.get('read_episode_to') or 0)}화'} 기준에선 지금 바로 월드컵으로 돌릴 후보가 부족해.\n"
            "더 읽은 범위로 넓히거나, 지금은 2인 비교로 가는 쪽이 자연스러워."
        )
        return reply, _set_story_agent_game_state(
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
    return reply, _set_story_agent_game_state(
        normalized,
        game_mode="ideal_worldcup",
        gender_scope=gender_scope,
        category=category,
        state=state,
    )


async def _generate_story_agent_vs_reply(
    *,
    session_memory: dict[str, Any],
    product_row: dict[str, Any],
    user_prompt: str,
    db: AsyncSession,
) -> tuple[str, dict[str, Any]]:
    normalized = _normalize_story_agent_session_memory(session_memory)
    game_context = normalized.get("game_context") or {}
    gender_scope = str(game_context.get("gender_scope") or "").strip().lower()
    category = str(game_context.get("category") or "").strip().lower()
    match_mode = str(game_context.get("match_mode") or "").strip().lower()
    read_scope_label = await _build_story_agent_read_scope_label(
        product_id=int(product_row.get("productId") or 0),
        read_episode_to=normalized.get("read_episode_to"),
        db=db,
    )
    if not gender_scope or not match_mode:
        return (
            build_story_agent_game_guide_reply(
                session_memory=normalized,
                product_row=product_row,
                read_scope_label=read_scope_label,
            )
            or "",
            normalized,
        )

    inferred_category = _infer_story_agent_game_category_from_prompt(user_prompt)
    effective_category = category or inferred_category or None

    state_category = effective_category or STORY_AGENT_PENDING_GAME_CATEGORY
    state = _get_story_agent_game_state(
        normalized,
        game_mode="vs_game",
        gender_scope=gender_scope,
        category=state_category,
    )
    state["mode"] = match_mode
    candidates = await get_story_agent_game_candidate_profiles(
        product_id=int(product_row.get("productId") or 0),
        db=db,
    )

    if match_mode == "direct_match":
        matched_scope_keys = _extract_story_agent_direct_match_scope_keys(
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
            return reply, _set_story_agent_game_state(
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
            return reply, _set_story_agent_game_state(
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
            return reply, _set_story_agent_game_state(
                normalized,
                game_mode="vs_game",
                gender_scope=gender_scope,
                category=state_category,
                state=state,
            )
        repeated_match_key = _build_story_agent_pair_key(left["display_name"], right["display_name"])
        if repeated_match_key in set(_normalize_story_agent_string_list(state.get("used_match_keys"), limit=128)):
            state["current_match"] = []
            reply = (
                f"{left['display_name']} vs {right['display_name']}는 이 세션에서 이미 한번 붙였어.\n"
                "다른 두 캐릭터를 붙이거나, 다른 기준으로 가자."
            )
            return reply, _set_story_agent_game_state(
                normalized,
                game_mode="vs_game",
                gender_scope=gender_scope,
                category=effective_category or state_category,
                state=state,
            )
        comparison = await generate_story_agent_vs_comparison(
            product_row=product_row,
            category=effective_category or state_category,
            match_pair=[left, right],
        )
        match_key = _build_story_agent_pair_key(left["display_name"], right["display_name"])
        state["used_match_keys"] = _normalize_story_agent_string_list([*(state.get("used_match_keys") or []), match_key], limit=128)
        state["current_match"] = []
        state["last_result_summary"] = comparison[:200]
        return comparison, _set_story_agent_game_state(
            normalized,
            game_mode="vs_game",
            gender_scope=gender_scope,
            category=effective_category or state_category,
            state=state,
        )

    if not effective_category:
        return (
            build_story_agent_game_guide_reply(
                session_memory=normalized,
                product_row=product_row,
                read_scope_label=read_scope_label,
            )
            or "",
            normalized,
        )

    if effective_category:
        pending_state = _get_story_agent_game_state(
            normalized,
            game_mode="vs_game",
            gender_scope=gender_scope,
            category=STORY_AGENT_PENDING_GAME_CATEGORY,
        )
        if pending_state.get("current_match") and not state.get("current_match"):
            state["current_match"] = list(pending_state.get("current_match") or [])
            pending_state["current_match"] = []
            normalized = _set_story_agent_game_state(
                normalized,
                game_mode="vs_game",
                gender_scope=gender_scope,
                category=STORY_AGENT_PENDING_GAME_CATEGORY,
                state=pending_state,
            )

    selected_candidates = await select_story_agent_game_candidates(
        product_row=product_row,
        candidates=candidates,
        game_mode="vs_game",
        gender_scope=gender_scope,
        category=effective_category,
        desired_count=4,
    )
    selected_pair = _pick_story_agent_unused_pair(
        selected_candidates,
        state.get("used_match_keys") or [],
    )
    if len(selected_pair) < 2:
        reply = (
            f"{str(product_row.get('title') or '').strip()} {gender_scope} / {category} 기준으로 바로 붙일 후보가 부족해.\n"
            "다른 기준으로 바꾸거나 직접 매치업으로 가면 이어갈 수 있어."
        )
        return reply, _set_story_agent_game_state(
            normalized,
            game_mode="vs_game",
            gender_scope=gender_scope,
            category=category,
            state=state,
        )
    comparison = await generate_story_agent_vs_comparison(
        product_row=product_row,
        category=effective_category,
        match_pair=selected_pair,
    )
    match_key = _build_story_agent_pair_key(
        selected_pair[0]["display_name"],
        selected_pair[1]["display_name"],
    )
    state["used_match_keys"] = _normalize_story_agent_string_list([*(state.get("used_match_keys") or []), match_key], limit=128)
    state["current_match"] = [selected_pair[0]["scope_key"], selected_pair[1]["scope_key"]]
    state["last_result_summary"] = comparison[:200]
    return comparison, _set_story_agent_game_state(
        normalized,
        game_mode="vs_game",
        gender_scope=gender_scope,
        category=effective_category,
        state=state,
    )


async def _generate_story_agent_game_reply(
    *,
    session_id: int,
    session_memory: dict[str, Any],
    product_row: dict[str, Any],
    user_prompt: str,
    db: AsyncSession,
) -> tuple[str, str, str, bool, str, dict[str, Any]]:
    normalized = _normalize_story_agent_session_memory(session_memory)
    dispatch_plan = build_story_agent_game_dispatch_plan(normalized)
    if dispatch_plan["route"] == "guide":
        game_context = normalized.get("game_context") or {}
        active_game_mode = str(game_context.get("mode") or "").strip().lower()
        read_scope_label = await _build_story_agent_read_scope_label(
            product_id=int(product_row.get("productId") or 0),
            read_episode_to=normalized.get("read_episode_to"),
            db=db,
        )
        if active_game_mode == "ideal_worldcup":
            followup = resolve_story_agent_worldcup_followup(user_prompt=user_prompt)
            if followup["exit_requested"]:
                reply = "좋아. 월드컵은 여기서 멈추고 일반 모드로 돌아갈게. 이제 작품 얘기나 분석으로 이어가면 돼."
                return (
                    reply,
                    dispatch_plan["model_used"],
                    dispatch_plan["route_mode"],
                    False,
                    dispatch_plan["intent"],
                    _clear_story_agent_game_context(normalized),
                )
            if followup["meta_requested"]:
                reply = _build_story_agent_worldcup_setup_meta_reply(
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
            if not has_story_agent_worldcup_followup_signal(
                user_prompt=user_prompt,
                followup=followup,
            ):
                cleared_memory = _clear_story_agent_game_context(normalized)
                return await _generate_story_agent_reply(
                    session_id=session_id,
                    session_memory=cleared_memory,
                    product_row=product_row,
                    user_prompt=user_prompt,
                    user_id=None,
                    db=db,
                )
        guide = (
            build_story_agent_game_guide_reply(
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
            read_scope_label = await _build_story_agent_read_scope_label(
                product_id=int(product_row.get("productId") or 0),
                read_episode_to=normalized.get("read_episode_to"),
                db=db,
            )
            followup = resolve_story_agent_worldcup_followup(user_prompt=user_prompt)
            if followup["exit_requested"]:
                reply = "좋아. 월드컵은 여기서 멈추고 일반 모드로 돌아갈게. 이제 작품 얘기나 분석으로 이어가면 돼."
                return (
                    reply,
                    dispatch_plan["model_used"],
                    dispatch_plan["route_mode"],
                    False,
                    dispatch_plan["intent"],
                    _clear_story_agent_game_context(normalized),
                )
            if followup["meta_requested"]:
                reply = _build_story_agent_worldcup_setup_meta_reply(
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
            if not has_story_agent_worldcup_followup_signal(
                user_prompt=user_prompt,
                followup=followup,
            ):
                cleared_memory = _clear_story_agent_game_context(normalized)
                return await _generate_story_agent_reply(
                    session_id=session_id,
                    session_memory=cleared_memory,
                    product_row=product_row,
                    user_prompt=user_prompt,
                    user_id=None,
                    db=db,
                )
        reply, next_memory = await _generate_story_agent_worldcup_reply(
            session_memory=normalized,
            product_row=product_row,
            user_prompt=user_prompt,
            db=db,
        )
        return reply, dispatch_plan["model_used"], dispatch_plan["route_mode"], False, dispatch_plan["intent"], next_memory
    reply = build_story_agent_vs_disabled_reply()
    return reply, dispatch_plan["model_used"], dispatch_plan["route_mode"], False, dispatch_plan["intent"], _clear_story_agent_game_context(normalized)


def _normalize_story_agent_character_name(value: str) -> str:
    normalized = re.sub(r"\s+", "", str(value or "")).strip().lower()
    return normalized


async def _get_story_agent_exact_summary_row(
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


async def _resolve_story_agent_active_character_scope_key(
    *,
    product_id: int,
    active_character: str | None,
    db: AsyncSession,
) -> str | None:
    raw_value = str(active_character or "").strip()
    if not raw_value:
        return None
    if ":" in raw_value:
        return raw_value

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
    target_name = _normalize_story_agent_character_name(raw_value)
    matched_scope_keys: list[str] = []
    for row in result.mappings().all():
        scope_key = str(row.get("scopeKey") or "").strip()
        if not scope_key:
            continue
        payload = _extract_story_agent_json_object(str(row.get("summaryText") or "")) or {}
        candidate_names = [scope_key]
        display_name = str(payload.get("display_name") or "").strip()
        if display_name:
            candidate_names.append(display_name)
        for alias in payload.get("aliases") or []:
            alias_text = str(alias or "").strip()
            if alias_text:
                candidate_names.append(alias_text)
        if any(_normalize_story_agent_character_name(name) == target_name for name in candidate_names if str(name).strip()):
            matched_scope_keys.append(scope_key)

    unique_scope_keys = sorted(set(matched_scope_keys))
    if not unique_scope_keys:
        return None
    if len(unique_scope_keys) > 1:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="같은 이름으로 여러 RP 캐릭터가 잡혀서 누구와 대화할지 정하기 어렵습니다. 캐릭터를 더 구체적으로 지정해주세요.",
        )
    return unique_scope_keys[0]


async def _load_story_agent_rp_context(
    *,
    product_row: dict[str, Any],
    session_memory: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any] | None:
    normalized_memory = _normalize_story_agent_session_memory(session_memory)
    active_character = str(normalized_memory.get("active_character") or "").strip()
    rp_mode = str(normalized_memory.get("rp_mode") or "").strip().lower()
    if not active_character or rp_mode not in STORY_AGENT_ALLOWED_RP_MODES:
        return None

    product_id = int(product_row.get("productId") or 0)
    resolved_active_character = await _resolve_story_agent_active_character_scope_key(
        product_id=product_id,
        active_character=active_character,
        db=db,
    )
    if not resolved_active_character:
        return None
    profile_row = await _get_story_agent_exact_summary_row(
        product_id=product_id,
        summary_type="character_rp_profile",
        scope_key=resolved_active_character,
        db=db,
    )
    examples_row = await _get_story_agent_exact_summary_row(
        product_id=product_id,
        summary_type="character_rp_examples",
        scope_key=resolved_active_character,
        db=db,
    )
    inventory_row = await _get_story_agent_exact_summary_row(
        product_id=product_id,
        summary_type="character_inventory",
        scope_key=resolved_active_character,
        db=db,
    )
    profile = _extract_story_agent_json_object(str((profile_row or {}).get("summaryText") or ""))
    examples_payload = _extract_story_agent_json_object(str((examples_row or {}).get("summaryText") or ""))
    inventory_payload = _extract_story_agent_json_object(str((inventory_row or {}).get("summaryText") or ""))
    if not profile or not examples_payload:
        return None

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

    if rp_mode == "scene":
        scene_episode_no = int(normalized_memory.get("scene_episode_no") or 0) or None
        if scene_episode_no:
            summary_rows = await _get_story_agent_summary_candidates(
                product_id=product_id,
                keywords=[],
                query_text=f"{scene_episode_no}화",
                latest_episode_no=int(product_row.get("latestEpisodeNo") or 0),
                mode="exact",
                episode_no=scene_episode_no,
                db=db,
            )
            scene_summary_text = str((summary_rows[0] if summary_rows else {}).get("summaryText") or "").strip()
            episode_rows = await _get_story_agent_episode_contents(
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
            )[:STORY_AGENT_PREFETCH_CONTEXT_CHARS]
            context["scene_episode_no"] = scene_episode_no
            context["scene_summary_text"] = scene_summary_text
            context["scene_source_text"] = scene_source_text
            context["scene_state"] = scene_summary_text.split("\n", 1)[0] if scene_summary_text else ""
    return context


async def _resolve_story_agent_reference(
    *,
    product_row: dict[str, Any],
    user_prompt: str,
    recent_messages: list[dict[str, str]],
    summary_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not _is_story_agent_ambiguous_reference_query(user_prompt):
        return None

    recent_context_message = build_story_agent_recent_context_message(recent_messages)
    summary_context_message = _build_story_agent_summary_context_message(summary_rows[:3])

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
        max_tokens=STORY_AGENT_REFERENCE_RESOLUTION_MAX_TOKENS,
    )
    content = response.get("content") or []
    parsed = _extract_story_agent_json_object(_extract_text(content))
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

    return {
        "reference_status": reference_status,
        "resolved_target": resolved_target,
        "confidence": max(0.0, min(confidence, 1.0)),
        "alternate_targets": alternate_targets,
    }


def _build_story_agent_reference_resolution_message(reference_resolution: dict[str, Any]) -> str:
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


async def _dispatch_story_agent_tool(
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    product_id: int,
    product_row: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    if tool_name == "get_product_context":
        return await _get_story_agent_product_context(product_id=product_id, db=db)
    if tool_name == "search_episode_summaries":
        return {
            "rows": await _get_story_agent_summary_candidates(
                product_id=product_id,
                keywords=_extract_story_agent_keywords(str(tool_input.get("query") or "")),
                query_text=str(tool_input.get("query") or ""),
                latest_episode_no=latest_episode_no,
                mode=str(tool_input.get("mode") or ""),
                episode_no=int(tool_input.get("episode_no") or 0) or None,
                db=db,
            )
        }
    if tool_name == "search_episode_contents":
        return {
            "rows": await _search_story_agent_episode_contents(
                product_id=product_id,
                query_text=str(tool_input.get("query") or ""),
                latest_episode_no=latest_episode_no,
                db=db,
            )
        }
    if tool_name == "get_episode_contents":
        return {
            "rows": await _get_story_agent_episode_contents(
                product_id=product_id,
                episode_from=int(tool_input.get("episode_from") or 1),
                episode_to=int(tool_input.get("episode_to") or tool_input.get("episode_from") or 1),
                latest_episode_no=latest_episode_no,
                db=db,
            )
        }
    return {"error": f"지원하지 않는 tool입니다: {tool_name}"}


def _build_story_agent_prompt_preview(user_prompt: str) -> str:
    normalized = re.sub(r"\s+", " ", str(user_prompt or "")).strip()
    return normalized[:80]


async def _resolve_story_agent_intent(
    *,
    user_prompt: str,
    recent_messages: list[dict[str, str]],
) -> tuple[str, bool, str]:
    recent_context_message = build_story_agent_recent_context_message(recent_messages)
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
        max_tokens=STORY_AGENT_INTENT_MAX_TOKENS,
    )
    parsed = _extract_story_agent_json_object(_extract_text(response.get("content") or [])) or {}
    intent = str(parsed.get("intent") or "").strip().lower()
    if intent not in STORY_AGENT_ALLOWED_INTENTS:
        intent = "factual"
    mode = str(parsed.get("mode") or "").strip().lower()
    if mode not in STORY_AGENT_ALLOWED_SUMMARY_MODES:
        mode = "general"
    raw_needs_creative = parsed.get("needs_creative")
    if isinstance(raw_needs_creative, bool):
        needs_creative = raw_needs_creative
    else:
        needs_creative = str(raw_needs_creative or "").strip().lower() == "true"
    return intent, needs_creative, mode


async def _generate_story_agent_reply(
    *,
    session_id: int,
    session_memory: dict[str, Any],
    product_row: dict[str, Any],
    user_prompt: str,
    user_id: int | None,
    db: AsyncSession,
) -> tuple[str, str, str, bool, str, dict[str, Any] | None]:
    normalized_memory = _normalize_story_agent_session_memory(session_memory)
    gemini_enabled = bool(settings.GEMINI_API_KEY)
    scope_state = _resolve_story_agent_read_scope_state(normalized_memory)

    initial_route = _resolve_story_agent_response_route(
        normalized_memory=normalized_memory,
        rp_context=None,
    )
    if initial_route == "game":
        return await _generate_story_agent_game_reply(
            session_id=session_id,
            session_memory=normalized_memory,
            product_row=product_row,
            user_prompt=user_prompt,
            db=db,
        )

    if scope_state == "none":
        concierge_payload = await build_story_agent_concierge_payload(
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
            _build_story_agent_read_scope_required_reply(),
            "guard",
            "guard:read_scope_required",
            False,
            "read_scope_required",
            None,
        )

    rp_context = await _load_story_agent_rp_context(
        product_row=product_row,
        session_memory=normalized_memory,
        db=db,
    )
    active_route = _resolve_story_agent_response_route(
        normalized_memory=normalized_memory,
        rp_context=rp_context,
    )
    recent_messages = await _get_story_agent_recent_messages(session_id=session_id, db=db)
    if active_route == "rp" and rp_context:
        rp_plan = _build_story_agent_rp_plan(
            rp_context=rp_context,
            gemini_enabled=gemini_enabled,
        )
        if rp_plan["preferred_model"] == "gemini":
            try:
                reply = await _generate_story_agent_rp_reply_with_gemini(
                    product_row=product_row,
                    user_prompt=user_prompt,
                    rp_context=rp_context,
                    recent_messages=recent_messages,
                )
                return reply, "gemini", rp_plan["route_mode"], False, rp_plan["intent"], None
            except Exception as exc:
                logger.warning(
                    "story-agent rp_route_selected model_used=gemini fallback_used=true product_id=%s session_id=%s active_character=%s error=%s",
                    product_row.get("productId"),
                    session_id,
                    rp_context.get("active_character"),
                    exc,
                )
        reply = await _generate_story_agent_rp_reply_with_claude(
            product_row=product_row,
            user_prompt=user_prompt,
            rp_context=rp_context,
            recent_messages=recent_messages,
        )
        return reply, "haiku", rp_plan["route_mode"], gemini_enabled, rp_plan["intent"], None

    intent, needs_creative, routed_mode = await _resolve_story_agent_intent(
        user_prompt=user_prompt,
        recent_messages=recent_messages,
    )
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    evidence_bundle: StoryAgentEvidenceBundle = await assemble_story_agent_scope_context(
        product_row=product_row,
        session_memory=normalized_memory,
        user_prompt=user_prompt,
        db=db,
    )
    scoped_product_row = evidence_bundle["product_row"]
    resolved_mode, _, _, _ = _resolve_story_agent_summary_mode(
        query_text=user_prompt,
        latest_episode_no=latest_episode_no,
        mode=routed_mode,
    )
    qa_plan = _build_story_agent_qa_plan(
        intent=intent,
        needs_creative=needs_creative,
        resolved_mode=resolved_mode,
        gemini_enabled=gemini_enabled,
        scope_state=scope_state,
    )
    prompt_preview = _build_story_agent_prompt_preview(user_prompt)
    qa_hooks: StoryAgentQaExecutionHooks = {
        "resolve_summary_mode": _resolve_story_agent_summary_mode,
        "resolve_exact_episode_no": _resolve_story_agent_exact_episode_no,
        "extract_keywords": _extract_story_agent_keywords,
        "get_summary_candidates": _get_story_agent_summary_candidates,
        "get_broad_summary_context_rows": _get_story_agent_broad_summary_context_rows,
        "resolve_reference": _resolve_story_agent_reference,
        "build_reference_resolution_message": _build_story_agent_reference_resolution_message,
        "get_episode_contents": _get_story_agent_episode_contents,
        "search_episode_contents": _search_story_agent_episode_contents,
        "build_system_prompt": _build_story_agent_system_prompt,
        "build_summary_context_message": _build_story_agent_summary_context_message,
        "is_ambiguous_reference_query": _is_story_agent_ambiguous_reference_query,
        "dispatch_tool": _dispatch_story_agent_tool,
    }
    result: StoryAgentQaExecutionResult = await execute_story_agent_qa(
        product_row=scoped_product_row,
        user_prompt=user_prompt,
        qa_plan=qa_plan,
        evidence_bundle=evidence_bundle,
        recent_messages=recent_messages,
        db=db,
        hooks=qa_hooks,
        max_tool_rounds=STORY_AGENT_MAX_TOOL_ROUNDS,
        gemini_context_episode_limit=STORY_AGENT_GEMINI_CONTEXT_EPISODE_LIMIT,
        prefetch_context_chars=STORY_AGENT_PREFETCH_CONTEXT_CHARS,
        tools=STORY_AGENT_TOOLS,
    )
    logger.info(
        "story-agent route_selected model_used=%s intent=%s needs_creative=%s route_mode=%s fallback_used=%s product_id=%s session_id=%s latest_episode_no=%s prompt_preview=%r",
        result["model_used"],
        result["intent"],
        "true" if needs_creative else "false",
        result["route_mode"],
        "true" if result["fallback_used"] else "false",
        product_row.get("productId"),
        session_id,
        int(product_row.get("latestEpisodeNo") or 0),
        prompt_preview,
    )
    return result["reply"], result["model_used"], result["route_mode"], result["fallback_used"], result["intent"], None




async def _get_story_agent_chunk_previews(
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
        {"lock_name": lock_name, "timeout": STORY_AGENT_SESSION_LOCK_TIMEOUT_SECONDS},
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


async def _acquire_story_agent_session_lock(session_id: int) -> AsyncConnection | None:
    return await _acquire_named_lock(f"story-agent-session:{session_id}")


async def _release_story_agent_session_lock(session_id: int, conn: AsyncConnection | None) -> None:
    await _release_named_lock(f"story-agent-session:{session_id}", conn)


def _get_story_agent_actor_lock_name(user_id: int | None, guest_key: str | None) -> str:
    if user_id is not None:
        return f"story-agent-actor:user:{user_id}"
    return f"story-agent-actor:guest:{guest_key}"


async def _acquire_story_agent_actor_lock(
    user_id: int | None,
    guest_key: str | None,
    db: AsyncSession,
) -> AsyncConnection | None:
    del db
    return await _acquire_named_lock(_get_story_agent_actor_lock_name(user_id, guest_key))


async def _release_story_agent_actor_lock(
    user_id: int | None,
    guest_key: str | None,
    conn: AsyncConnection | None,
) -> None:
    await _release_named_lock(_get_story_agent_actor_lock_name(user_id, guest_key), conn)


async def _get_story_agent_daily_user_message_count(
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


async def _get_user_cash_balance_for_story_agent(user_id: int, db: AsyncSession) -> int:
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


async def _charge_story_agent_cash(
    user_id: int,
    session_id: int,
    product_id: int,
    db: AsyncSession,
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
            "amount": -STORY_AGENT_MESSAGE_CASH_COST,
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
            "amount": STORY_AGENT_MESSAGE_CASH_COST,
            "sponsor_type": "story_agent",
            "product_id": product_id,
            "story_agent_session_id": session_id,
            "created_id": settings.DB_DML_DEFAULT_ID,
        },
    )


async def _enforce_story_agent_message_usage(
    user_id: int | None,
    guest_key: str | None,
    session_id: int,
    product_id: int,
    db: AsyncSession,
) -> None:
    used_count = await _get_story_agent_daily_user_message_count(user_id, guest_key, db)
    if used_count < STORY_AGENT_DAILY_FREE_MESSAGE_LIMIT:
        return

    if user_id is None:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    balance = await _get_user_cash_balance_for_story_agent(user_id=user_id, db=db)
    if balance < STORY_AGENT_MESSAGE_CASH_COST:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INSUFFICIENT_CASH_BALANCE,
        )

    await _charge_story_agent_cash(
        user_id=user_id,
        session_id=session_id,
        product_id=product_id,
        db=db,
    )


async def _resolve_story_agent_message_charge_required(
    user_id: int | None,
    guest_key: str | None,
    db: AsyncSession,
) -> bool:
    used_count = await _get_story_agent_daily_user_message_count(user_id, guest_key, db)
    if used_count < STORY_AGENT_DAILY_FREE_MESSAGE_LIMIT:
        return False

    if user_id is None:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    balance = await _get_user_cash_balance_for_story_agent(user_id=user_id, db=db)
    if balance < STORY_AGENT_MESSAGE_CASH_COST:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INSUFFICIENT_CASH_BALANCE,
        )
    return True


async def _get_existing_turn_messages(
    session_id: int,
    client_message_id: str,
    latest_episode_no: int | None,
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
    episode_ref_ceiling = _resolve_story_agent_episode_ref_ceiling(
        latest_episode_no,
        read_episode_to,
    )
    rows = [
        (
            {**row, "referencedEpisodeNos": []}
            if concierge_payload and row.get("role") == "assistant"
            else _attach_story_agent_message_episode_refs(row, latest_episode_no=episode_ref_ceiling)
        )
        for row in rows
    ]
    rows = _attach_story_agent_concierge_to_last_assistant_message(rows, concierge_payload)
    if not rows:
        return None
    if len(rows) != 2:
        raise CustomResponseException(
            status_code=status.HTTP_409_CONFLICT,
            message="이전 메시지가 아직 처리 중입니다. 잠시 후 다시 시도해주세요.",
        )
    return rows


def _extract_story_agent_referenced_episode_nos(
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

    for range_match in STORY_AGENT_EPISODE_RANGE_RE.finditer(normalized_content):
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

    for single_match in STORY_AGENT_EPISODE_SINGLE_RE.finditer(normalized_content):
        episode_no = int(single_match.group(1) or 0)
        if not episode_no:
            continue
        if max_episode_no > 0 and episode_no > max_episode_no:
            continue
        episode_nos.add(episode_no)

    return sorted(episode_nos)


def _attach_story_agent_message_episode_refs(
    message: dict[str, Any],
    latest_episode_no: int | None = None,
) -> dict[str, Any]:
    if message.get("role") != "assistant":
        return message
    return {
        **message,
        "referencedEpisodeNos": _extract_story_agent_referenced_episode_nos(
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
            COALESCE(MAX(e.episode_no), 0) AS latestEpisodeNo
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
        GROUP BY p.product_id, p.title, p.author_name, p.thumbnail_file_id, p.status_code, sacp.context_status
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
            DATE_FORMAT(updated_date, '%Y-%m-%d %H:%i:%s') AS updatedDate
        FROM tb_story_agent_session
        WHERE {' AND '.join(where_parts)}
        ORDER BY updated_date DESC, session_id DESC
        LIMIT 50
        """
    )
    result = await db.execute(query, params)
    return {"data": [dict(row) for row in result.mappings().all()]}


@handle_exceptions
async def get_messages(
    session_id: int,
    kc_user_id: str | None,
    guest_key: str | None,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, guest_key, db)
    session_row = await _get_session_row(session_id, user_id, resolved_guest_key, db)
    product_state = await _get_story_agent_product_session_state(
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
    session_memory = _normalize_story_agent_session_memory(session_row.get("session_memory_json"))
    scope_state = _resolve_story_agent_read_scope_state(session_memory)
    concierge_payload = None
    if scope_state == "none":
        concierge_payload = await build_story_agent_concierge_payload(
            product_row=product_state,
            user_id=user_id,
            db=db,
        )
    latest_episode_no = int(product_state.get("latestEpisodeNo") or 0)
    episode_ref_ceiling = _resolve_story_agent_episode_ref_ceiling(
        latest_episode_no,
        session_memory.get("read_episode_to"),
    )
    messages = [
        (
            {**message, "referencedEpisodeNos": []}
            if concierge_payload and message.get("role") == "assistant"
            else _attach_story_agent_message_episode_refs(message, latest_episode_no=episode_ref_ceiling)
        )
        for message in messages
    ]
    messages = _attach_story_agent_concierge_to_last_assistant_message(messages, concierge_payload)
    starter = None
    if not messages:
        read_episode_to = session_memory.get("read_episode_to")
        starter = _build_story_agent_starter(
            product_title=str(product_state.get("title") or session_row.get("title") or "").strip(),
            scope_state=scope_state,
            read_episode_to=read_episode_to,
            read_episode_title=await _get_story_agent_visible_episode_title(
                int(session_row["product_id"]),
                int(read_episode_to or 0) if read_episode_to else None,
                db,
            ),
            latest_episode_no=latest_episode_no,
            can_send_message=bool(product_state.get("canSendMessage")),
            concierge_payload=concierge_payload,
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
                "latestEpisodeNo": latest_episode_no,
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
            },
            "messages": messages,
            "starter": starter,
        }
    }


@handle_exceptions
async def create_session(
    req_body: PostStoryAgentSessionReqBody,
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
    product_row = await _get_story_agent_product(
        product_id=req_body.product_id,
        adult_yn=effective_adult_yn,
        db=db,
    )
    if not product_row:
        product_state = await _get_story_agent_product_session_state(
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
            message=STORY_AGENT_CONTEXT_PENDING_MESSAGE,
        )

    title = (req_body.title or STORY_AGENT_DEFAULT_TITLE).strip()[:120]
    resolved_active_character = await _resolve_story_agent_active_character_scope_key(
        product_id=req_body.product_id,
        active_character=req_body.active_character,
        db=db,
    )
    if req_body.active_character and not resolved_active_character:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="RP 캐릭터를 찾지 못했습니다. 표시 이름이나 내부 키를 다시 확인해주세요.",
        )
    session_memory = _merge_story_agent_session_memory(
        base_memory={},
        rp_mode=req_body.rp_mode,
        active_character=resolved_active_character,
        scene_episode_no=req_body.scene_episode_no,
        game_mode=req_body.game_mode,
        game_gender_scope=req_body.game_gender_scope,
        game_category=req_body.game_category,
        game_match_mode=req_body.game_match_mode,
        game_read_episode_to=req_body.game_read_episode_to,
    )
    session_memory_json = _serialize_story_agent_session_memory(session_memory)
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
            DATE_ADD(NOW(), INTERVAL {STORY_AGENT_SESSION_TTL_DAYS} DAY),
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
    req_body: PatchStoryAgentSessionReqBody,
    kc_user_id: str | None,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, req_body.guest_key, db)
    await _get_session_row(session_id, user_id, resolved_guest_key, db)

    query = text(
        f"""
        UPDATE tb_story_agent_session
        SET title = :title,
            expires_at = DATE_ADD(NOW(), INTERVAL {STORY_AGENT_SESSION_TTL_DAYS} DAY),
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
    req_body: PostStoryAgentMessageReqBody,
    kc_user_id: str | None,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, req_body.guest_key, db)
    session_row = await _get_session_row(session_id, user_id, resolved_guest_key, db)
    current_session_memory = _normalize_story_agent_session_memory(session_row.get("session_memory_json"))
    resolved_active_character = await _resolve_story_agent_active_character_scope_key(
        product_id=int(session_row["product_id"]),
        active_character=req_body.active_character,
        db=db,
    )
    if req_body.active_character and not resolved_active_character:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="RP 캐릭터를 찾지 못했습니다. 표시 이름이나 내부 키를 다시 확인해주세요.",
        )
    next_session_memory = _merge_story_agent_session_memory(
        base_memory=current_session_memory,
        rp_mode=req_body.rp_mode,
        active_character=resolved_active_character,
        scene_episode_no=req_body.scene_episode_no,
        game_mode=req_body.game_mode,
        game_gender_scope=req_body.game_gender_scope,
        game_category=req_body.game_category,
        game_match_mode=req_body.game_match_mode,
        game_read_episode_to=req_body.game_read_episode_to,
    )
    next_session_memory = apply_story_agent_implicit_game_inputs(
        session_memory=next_session_memory,
        user_prompt=req_body.content,
        game_read_episode_to=req_body.game_read_episode_to,
    )
    effective_adult_yn = await _resolve_effective_adult_yn(
        kc_user_id=kc_user_id,
        adult_yn="Y",
        db=db,
    )
    product_row = await _get_story_agent_product(
        product_id=int(session_row["product_id"]),
        adult_yn=effective_adult_yn,
        db=db,
    )
    if not product_row:
        product_state = await _get_story_agent_product_session_state(
            product_id=int(session_row["product_id"]),
            adult_yn=effective_adult_yn,
            db=db,
        )
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=product_state.get("unavailableMessage") or STORY_AGENT_PRODUCT_UNAVAILABLE_MESSAGE,
        )
    if product_row.get("contextStatus") != "ready":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=STORY_AGENT_CONTEXT_PENDING_MESSAGE,
        )
    inferred_prompt_read_episode_to = await _resolve_story_agent_prompt_read_episode_to(
        product_id=int(session_row["product_id"]),
        latest_episode_no=int(product_row.get("latestEpisodeNo") or 0),
        user_prompt=req_body.content,
        db=db,
    )
    read_scope_decision: StoryAgentPromptReadScopeDecision = _resolve_story_agent_prompt_read_scope_decision(
        user_prompt=req_body.content,
        inferred_read_episode_to=inferred_prompt_read_episode_to,
    )
    if read_scope_decision["scope_state"] == "known" and read_scope_decision["read_episode_to"] is not None:
        next_session_memory["read_episode_to"] = int(read_scope_decision["read_episode_to"])
        next_session_memory["read_scope_state"] = "known"
    elif read_scope_decision["scope_state"] == "none":
        next_session_memory["read_episode_to"] = None
        next_session_memory["read_scope_state"] = "none"

    created_id = user_id if user_id is not None else settings.DB_DML_DEFAULT_ID

    session_lock_conn: AsyncConnection | None = None
    try:
        session_lock_conn = await _acquire_story_agent_session_lock(session_id=session_id)
        if session_lock_conn is None:
            raise CustomResponseException(
                status_code=status.HTTP_409_CONFLICT,
                message="같은 세션에서 다른 메시지를 처리 중입니다. 잠시 후 다시 시도해주세요.",
            )

        concierge_payload = None
        if _resolve_story_agent_read_scope_state(next_session_memory) == "none":
            concierge_payload = await build_story_agent_concierge_payload(
                product_row=product_row,
                user_id=user_id,
                db=db,
                user_prompt=req_body.content,
            )

        existing_messages = await _get_existing_turn_messages(
            session_id=session_id,
            client_message_id=req_body.client_message_id,
            latest_episode_no=await _get_story_agent_latest_visible_episode_no(
                int(session_row["product_id"]),
                db=db,
            ),
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

        should_charge_cash = await _resolve_story_agent_message_charge_required(
            user_id=user_id,
            guest_key=resolved_guest_key,
            db=db,
        )

        if read_scope_decision["is_scope_only"]:
            assistant_reply = await _build_story_agent_read_scope_confirm_reply(
                product_id=int(session_row["product_id"]),
                read_episode_to=next_session_memory.get("read_episode_to"),
                db=db,
            )
            model_used = "system"
            route_mode = "scope:set"
            fallback_used = False
            intent = "scope"
            route_session_memory = None
        else:
            assistant_reply, model_used, route_mode, fallback_used, intent, route_session_memory = await _generate_story_agent_reply(
                session_id=session_id,
                session_memory=next_session_memory,
                product_row=product_row,
                user_prompt=req_body.content,
                user_id=user_id,
                db=db,
            )
        if route_session_memory is not None:
            next_session_memory = _normalize_story_agent_session_memory(route_session_memory)
        next_session_memory = _update_story_agent_session_memory_after_reply(
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
                "content": req_body.content,
                "created_id": created_id,
            },
        )
        assistant_result = await db.execute(
            insert_query,
            {
                "session_id": session_id,
                "role": "assistant",
                "client_message_id": req_body.client_message_id,
                "content": assistant_reply,
                "created_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        if should_charge_cash:
            await _charge_story_agent_cash(
                user_id=int(user_id),
                session_id=session_id,
                product_id=int(session_row["product_id"]),
                db=db,
            )

        update_title_query = text(
            f"""
            UPDATE tb_story_agent_session
            SET title = CASE
                    WHEN title = :default_title THEN :next_title
                    ELSE title
                END,
                session_memory_json = :session_memory_json,
                expires_at = DATE_ADD(NOW(), INTERVAL {STORY_AGENT_SESSION_TTL_DAYS} DAY),
                updated_id = :updated_id,
                updated_date = NOW()
            WHERE session_id = :session_id
            """
        )
        await db.execute(
            update_title_query,
            {
                "default_title": STORY_AGENT_DEFAULT_TITLE,
                "next_title": req_body.content[:40],
                "session_memory_json": _serialize_story_agent_session_memory(next_session_memory),
                "updated_id": created_id,
                "session_id": session_id,
            },
        )

        await db.commit()
        logger.info(
            "story-agent reply_completed model_used=%s intent=%s route_mode=%s fallback_used=%s product_id=%s session_id=%s charged_cash=%s prompt_preview=%r",
            model_used,
            intent,
            route_mode,
            "true" if fallback_used else "false",
            int(session_row["product_id"]),
            session_id,
            "true" if should_charge_cash else "false",
            _build_story_agent_prompt_preview(req_body.content),
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
                    _attach_story_agent_concierge_cards(
                        (
                            {
                                "messageId": int(assistant_result.lastrowid),
                                "role": "assistant",
                                "content": assistant_reply,
                                "referencedEpisodeNos": [],
                            }
                            if route_mode == "qa:concierge"
                            else _attach_story_agent_message_episode_refs({
                                "messageId": int(assistant_result.lastrowid),
                                "role": "assistant",
                                "content": assistant_reply,
                            }, latest_episode_no=_resolve_story_agent_episode_ref_ceiling(
                                int(product_row.get("latestEpisodeNo") or 0),
                                next_session_memory.get("read_episode_to"),
                            ))
                        ),
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
            await _release_story_agent_session_lock(session_id=session_id, conn=session_lock_conn)
