from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from fastapi import status
import httpx
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
STORY_AGENT_GEMINI_TIMEOUT_SECONDS = 35.0
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
STORY_AGENT_EXACT_EPISODE_RE = re.compile(r"(\d{1,4})\s*화")
STORY_AGENT_ORDINAL_EPISODE_RE = re.compile(r"(\d{1,4})\s*번째(?:\s*화|\s*회차)?")
STORY_AGENT_KOREAN_ORDINAL_MAP = {
    "첫": 1,
    "두": 2,
    "세": 3,
    "네": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
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
        "사용자가 '저/그/이 선택', '저/그/이 장면', '그때', '그거'처럼 지시대명사로 모호하게 물으면 최근 대화와 이번 질문 관련 요약을 기준으로 가장 가능성 높은 장면이나 선택을 먼저 해석하라. "
        "가능한 해석이 있으면 답변 첫 줄에 어떤 장면/선택으로 이해했는지 짧게 밝힌 뒤 설명하고, 마지막에 혹시 다른 장면이면 알려달라고 덧붙여라. "
        "단서가 약해도 무작정 '어떤 선택인지 말해 달라'고만 하지 말고, 유력한 후보가 1~2개면 그 후보를 짧게 제시하며 어느 쪽인지 물어라. "
        "도구를 1~2번 조회한 뒤에도 근거가 부족하면, 공개 범위에서 확인되는 부분만 짧게 답하고 더 이상의 tool 호출은 멈춰라. "
        "답변은 한국어로, 불필요한 군더더기 없이 바로 답하라. 관련 회차 번호가 있으면 자연스럽게 포함하라."
    )


def _is_story_agent_ambiguous_reference_query(query_text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(query_text or "")).strip()
    if not normalized:
        return False
    return any(pattern in normalized for pattern in STORY_AGENT_AMBIGUOUS_REFERENCE_PATTERNS)


def _build_story_agent_recent_context_message(
    recent_messages: list[dict[str, str]],
) -> str:
    if not recent_messages:
        return ""

    lines: list[str] = []
    for message in recent_messages[-4:]:
        role = "사용자" if str(message.get("role") or "").strip() == "user" else "이전 답변"
        content = re.sub(r"\s+", " ", str(message.get("content") or "")).strip()
        if not content:
            continue
        lines.append(f"- {role}: {content[:220]}")

    if not lines:
        return ""

    return (
        "아래는 이번 질문 직전까지의 최근 대화 핵심이다. "
        "지시대명사 질문이면 가장 최근에 언급된 장면·선택·인물을 우선 참조하라.\n"
        + "\n".join(lines)
    )


def _extract_story_agent_json_object(text_value: str) -> dict[str, Any] | None:
    raw = str(text_value or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


async def _resolve_story_agent_reference(
    *,
    product_row: dict[str, Any],
    user_prompt: str,
    recent_messages: list[dict[str, str]],
    summary_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not _is_story_agent_ambiguous_reference_query(user_prompt):
        return None

    recent_context_message = _build_story_agent_recent_context_message(recent_messages)
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
            f"- 질문이 모호하지만 우선 '{primary_target}'을(를) 가리키는 것으로 가정하고 먼저 답하라.\n"
            "- 답변 첫 줄에 어떤 장면/선택으로 이해했는지 짧게 밝힌 뒤, 그 가정 아래에서 이유를 설명하라.\n"
            + (f"{bullet_lines}\n" if bullet_lines else "")
            + "- 마지막에는 혹시 다른 장면이라면 알려달라고 덧붙여라."
            + (" 다른 후보가 있으면 그 후보를 1~2개만 짧게 함께 제시하라." if secondary_targets else "")
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
    recent_context_message = _build_story_agent_recent_context_message(recent_messages)
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
    product_row: dict[str, Any],
    user_prompt: str,
    db: AsyncSession,
) -> tuple[str, str, str, bool, str]:
    recent_messages = await _get_story_agent_recent_messages(session_id=session_id, db=db)
    intent, needs_creative, routed_mode = await _resolve_story_agent_intent(
        user_prompt=user_prompt,
        recent_messages=recent_messages,
    )
    resolved_mode, _, _, _ = _resolve_story_agent_summary_mode(
        query_text=user_prompt,
        latest_episode_no=int(product_row.get("latestEpisodeNo") or 0),
        mode=routed_mode,
    )
    prompt_preview = _build_story_agent_prompt_preview(user_prompt)
    fallback_used = False
    if settings.GEMINI_API_KEY and needs_creative:
        try:
            logger.info(
                "story-agent route_selected model_used=gemini intent=%s needs_creative=true route_mode=%s fallback_used=false product_id=%s session_id=%s latest_episode_no=%s prompt_preview=%r",
                intent,
                resolved_mode,
                product_row.get("productId"),
                session_id,
                int(product_row.get("latestEpisodeNo") or 0),
                prompt_preview,
            )
            reply = await _generate_story_agent_reply_with_gemini(
                session_id=session_id,
                product_row=product_row,
                user_prompt=user_prompt,
                resolved_mode=resolved_mode,
                db=db,
            )
            return reply, "gemini", resolved_mode, False, intent
        except Exception as exc:
            fallback_used = True
            logger.warning(
                "story-agent route_selected model_used=gemini intent=%s needs_creative=true route_mode=%s fallback_used=true product_id=%s session_id=%s latest_episode_no=%s prompt_preview=%r error=%s",
                intent,
                resolved_mode,
                product_row.get("productId"),
                session_id,
                int(product_row.get("latestEpisodeNo") or 0),
                prompt_preview,
                exc,
            )

    logger.info(
        "story-agent route_selected model_used=haiku intent=%s needs_creative=%s route_mode=%s fallback_used=false product_id=%s session_id=%s latest_episode_no=%s prompt_preview=%r",
        intent,
        "true" if needs_creative else "false",
        resolved_mode,
        product_row.get("productId"),
        session_id,
        int(product_row.get("latestEpisodeNo") or 0),
        prompt_preview,
    )
    reply = await _generate_story_agent_reply_with_claude(
        session_id=session_id,
        product_row=product_row,
        user_prompt=user_prompt,
        resolved_mode=resolved_mode,
        db=db,
    )
    return reply, "haiku", resolved_mode, fallback_used, intent


def _to_story_agent_gemini_contents(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    for message in messages:
        text_value = str(message.get("content") or "").strip()
        if not text_value:
            continue
        role = "model" if str(message.get("role") or "").strip().lower() == "assistant" else "user"
        contents.append(
            {
                "role": role,
                "parts": [{"text": text_value}],
            }
        )
    return contents


def _extract_story_agent_gemini_text(response_json: dict[str, Any]) -> str:
    texts: list[str] = []
    for candidate in response_json.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text_value = str(part.get("text") or "").strip()
            if text_value:
                texts.append(text_value)
    return "\n".join(texts).strip()


async def _call_story_agent_gemini(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 1024,
) -> str:
    if not settings.GEMINI_API_KEY:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message="Gemini AI 서비스가 설정되지 않았습니다.",
        )

    payload: dict[str, Any] = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}],
        },
        "contents": messages,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": max_tokens,
        },
    }

    async with httpx.AsyncClient(timeout=STORY_AGENT_GEMINI_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.STORY_AGENT_GEMINI_MODEL}:generateContent",
            headers={
                "content-type": "application/json",
                "x-goog-api-key": settings.GEMINI_API_KEY,
            },
            json=payload,
        )

    if response.status_code != 200:
        logger.error("Gemini generateContent API error: %s %s", response.status_code, response.text)
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message="AI 서비스 호출에 실패했습니다.",
        )

    reply = _extract_story_agent_gemini_text(response.json())
    if not reply:
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message="AI 서비스 호출에 실패했습니다.",
        )
    return reply


def _build_story_agent_gemini_context_block(
    *,
    product_row: dict[str, Any],
    summary_rows: list[dict[str, Any]],
    episode_rows: list[dict[str, Any]],
    search_rows: list[dict[str, Any]],
) -> str:
    lines: list[str] = [
        "[작품 정보]",
        f"- 제목: {str(product_row.get('title') or '').strip()}",
        f"- 작가: {str(product_row.get('authorNickname') or '').strip()}",
        f"- 최신 공개 회차: {int(product_row.get('latestEpisodeNo') or 0)}화",
    ]

    if summary_rows:
        lines.append("[관련 회차 요약]")
        for row in summary_rows[:3]:
            summary_text = str(row.get("summaryText") or "").strip()
            if summary_text:
                lines.append(summary_text)

    if episode_rows:
        lines.append("[관련 공개 원문]")
        for row in episode_rows[:STORY_AGENT_GEMINI_CONTEXT_EPISODE_LIMIT]:
            content = str(row.get("content") or "").strip()
            if not content:
                continue
            lines.append(
                f"{int(row.get('episodeNo') or 0)}화 원문:\n{content[:STORY_AGENT_PREFETCH_CONTEXT_CHARS]}"
            )

    if search_rows:
        lines.append("[추가 원문 단서]")
        for row in search_rows[:4]:
            preview = re.sub(r"\s+", " ", str(row.get("chunkText") or "")).strip()
            if preview:
                lines.append(f"- {int(row.get('episodeNo') or 0)}화 일부: {preview[:220]}")

    return "\n".join(lines)


async def _generate_story_agent_reply_with_gemini(
    *,
    session_id: int,
    product_row: dict[str, Any],
    user_prompt: str,
    resolved_mode: str,
    db: AsyncSession,
) -> str:
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    recent_messages = await _get_story_agent_recent_messages(session_id=session_id, db=db)
    resolved_mode, exact_episode_no, _, _ = _resolve_story_agent_summary_mode(
        query_text=user_prompt,
        latest_episode_no=latest_episode_no,
        mode=resolved_mode,
    )
    resolved_episode_no = None
    if resolved_mode == "exact":
        resolved_episode_no = await _resolve_story_agent_exact_episode_no(
            product_id=int(product_row.get("productId") or 0),
            latest_episode_no=latest_episode_no,
            query_text=user_prompt,
            fallback_episode_no=exact_episode_no,
            db=db,
        )

    keywords = _extract_story_agent_keywords(user_prompt)
    if resolved_mode == "exact":
        summary_rows = await _get_story_agent_summary_candidates(
            product_id=int(product_row.get("productId") or 0),
            keywords=keywords,
            query_text=user_prompt,
            latest_episode_no=latest_episode_no,
            mode=resolved_mode,
            episode_no=resolved_episode_no,
            db=db,
        )
    else:
        summary_rows = await _get_story_agent_broad_summary_context_rows(
            product_id=int(product_row.get("productId") or 0),
            query_text=user_prompt,
            latest_episode_no=latest_episode_no,
            resolved_mode=resolved_mode,
            db=db,
        )

    reference_resolution = await _resolve_story_agent_reference(
        product_row=product_row,
        user_prompt=user_prompt,
        recent_messages=recent_messages,
        summary_rows=summary_rows,
    )

    episode_rows: list[dict[str, Any]] = []
    search_rows: list[dict[str, Any]] = []
    if resolved_episode_no:
        episode_rows = await _get_story_agent_episode_contents(
            product_id=int(product_row.get("productId") or 0),
            episode_from=resolved_episode_no,
            episode_to=resolved_episode_no,
            latest_episode_no=latest_episode_no,
            db=db,
        )
    else:
        target_episode_nos: list[int] = []
        for row in summary_rows[:STORY_AGENT_GEMINI_CONTEXT_EPISODE_LIMIT]:
            episode_no = int(row.get("episodeTo") or row.get("episodeFrom") or 0)
            if episode_no > 0 and episode_no not in target_episode_nos:
                target_episode_nos.append(episode_no)
        for episode_no in target_episode_nos[:STORY_AGENT_GEMINI_CONTEXT_EPISODE_LIMIT]:
            episode_rows.extend(
                await _get_story_agent_episode_contents(
                    product_id=int(product_row.get("productId") or 0),
                    episode_from=episode_no,
                    episode_to=episode_no,
                    latest_episode_no=latest_episode_no,
                    db=db,
                )
            )
        search_rows = await _search_story_agent_episode_contents(
            product_id=int(product_row.get("productId") or 0),
            query_text=user_prompt,
            latest_episode_no=latest_episode_no,
            db=db,
        )

    system_prompt = (
        _build_story_agent_system_prompt(product_row)
        + " 이번 응답은 확장형 질문용 응답이다. 제공된 공개 컨텍스트만으로 잘 놀아주되, 근거 없는 설정을 단정하지 마라."
        + " 비교/시뮬레이션 답변이라도 근거가 되는 회차나 장면을 1개 이상 자연스럽게 인용하라."
        + " 원문에 없는 추론은 '작품 내 직접 묘사는 없지만'처럼 추론임을 분명히 밝혀라."
        + " 능력, 범위, 지속시간, 거리, 숫자 같은 수치 정보가 공개 범위에 있으면 가능한 한 포함하라."
    )
    context_block = _build_story_agent_gemini_context_block(
        product_row=product_row,
        summary_rows=summary_rows,
        episode_rows=episode_rows,
        search_rows=search_rows,
    )
    messages = list(recent_messages)
    if _is_story_agent_ambiguous_reference_query(user_prompt):
        recent_context_message = _build_story_agent_recent_context_message(recent_messages)
        if recent_context_message:
            messages.append(
                {
                    "role": "user",
                    "content": recent_context_message,
                }
            )
        reference_message = _build_story_agent_reference_resolution_message(reference_resolution or {})
        if reference_message:
            messages.append(
                {
                    "role": "user",
                    "content": reference_message,
                }
            )
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
    return await _call_story_agent_gemini(
        system_prompt=system_prompt,
        messages=_to_story_agent_gemini_contents(messages),
        max_tokens=1024,
    )


async def _generate_story_agent_reply_with_claude(
    *,
    session_id: int,
    product_row: dict[str, Any],
    user_prompt: str,
    resolved_mode: str,
    db: AsyncSession,
) -> str:
    system_prompt = _build_story_agent_system_prompt(product_row)
    recent_messages = await _get_story_agent_recent_messages(session_id=session_id, db=db)
    messages = list(recent_messages)
    resolved_mode, exact_episode_no, _, _ = _resolve_story_agent_summary_mode(
        query_text=user_prompt,
        latest_episode_no=int(product_row.get("latestEpisodeNo") or 0),
        mode=resolved_mode,
    )
    if resolved_mode == "exact":
        resolved_episode_no = await _resolve_story_agent_exact_episode_no(
            product_id=int(product_row.get("productId") or 0),
            latest_episode_no=int(product_row.get("latestEpisodeNo") or 0),
            query_text=user_prompt,
            fallback_episode_no=exact_episode_no,
            db=db,
        )
    else:
        resolved_episode_no = None

    prefetched_summary_rows: list[dict[str, Any]] = []
    if resolved_mode != "exact":
        prefetched_summary_rows = await _get_story_agent_broad_summary_context_rows(
            product_id=int(product_row.get("productId") or 0),
            query_text=user_prompt,
            latest_episode_no=int(product_row.get("latestEpisodeNo") or 0),
            resolved_mode=resolved_mode,
            db=db,
        )
        summary_context_message = _build_story_agent_summary_context_message(prefetched_summary_rows)
        if summary_context_message:
            messages.append(
                {
                    "role": "user",
                    "content": summary_context_message,
                }
            )

    reference_resolution = await _resolve_story_agent_reference(
        product_row=product_row,
        user_prompt=user_prompt,
        recent_messages=recent_messages,
        summary_rows=prefetched_summary_rows,
    )
    if _is_story_agent_ambiguous_reference_query(user_prompt):
        recent_context_message = _build_story_agent_recent_context_message(recent_messages)
        if recent_context_message:
            messages.append(
                {
                    "role": "user",
                    "content": recent_context_message,
                }
            )
        reference_message = _build_story_agent_reference_resolution_message(reference_resolution or {})
        if reference_message:
            messages.append(
                {
                    "role": "user",
                    "content": reference_message,
                }
            )

    if resolved_mode == "exact" and resolved_episode_no:
        prefetched_rows = await _get_story_agent_episode_contents(
            product_id=int(product_row.get("productId") or 0),
            episode_from=resolved_episode_no,
            episode_to=resolved_episode_no,
            latest_episode_no=int(product_row.get("latestEpisodeNo") or 0),
            db=db,
        )
        prefetched_blocks: list[str] = []
        for row in prefetched_rows:
            content = str(row.get("content") or "").strip()
            if not content:
                continue
            prefetched_blocks.append(
                f"[질문 관련 공개 원문]\n{content[:STORY_AGENT_PREFETCH_CONTEXT_CHARS]}"
            )
        if prefetched_blocks:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "아래는 이번 질문과 직접 관련된 공개 원문이다. "
                        "명시된 회차 사실 질문에서는 이 원문을 최우선 근거로 사용하고, 내부 회차 매핑 과정은 설명하지 마라.\n\n"
                        + "\n\n".join(prefetched_blocks)
                    ),
                }
            )
    messages.append({"role": "user", "content": user_prompt})

    for _ in range(STORY_AGENT_MAX_TOOL_ROUNDS):
        response = await _call_claude_messages(
            system_prompt=system_prompt,
            messages=messages,
            tools=STORY_AGENT_TOOLS,
            max_tokens=1024,
        )
        content = response.get("content") or []
        text_reply = _extract_text(content)
        tool_uses = _extract_tool_use_blocks(content)
        if not tool_uses:
            return text_reply.strip() or "지금 공개 범위에서 바로 짚을 수 있는 핵심은 아직 제한적입니다. 우선 어떤 축이 궁금한지 말씀해 주세요. 예를 들면 능력 규칙, 세력 질서, 인물 관계, 전투 상성 중 하나로 좁히면 더 정확하게 이어서 답할 수 있습니다."

        messages.append({"role": "assistant", "content": content})
        tool_results: list[dict[str, Any]] = []
        for block in tool_uses:
            tool_name = str(block.get("name") or "")
            tool_input = block.get("input") or {}
            try:
                tool_result = await _dispatch_story_agent_tool(
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

    return "지금 공개 범위에서 바로 단정할 수 있는 근거는 충분하지 않습니다. 다만 질문을 더 잘게 나누면 바로 이어서 볼 수 있습니다. 능력 규칙, 세력 질서, 인물 관계, 전투 상성 중 어느 쪽이 궁금한지 한 가지로 좁혀 주세요."


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


def _build_story_agent_context_block(
    summary_rows: list[dict[str, Any]],
    chunk_rows: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    if summary_rows:
        lines.append("관련 회차 요약:")
        for row in summary_rows[:3]:
            summary_text = str(row.get("summaryText") or "").strip()
            if not summary_text:
                continue
            lines.append(summary_text)

    if chunk_rows:
        lines.append("원문 미리보기:")
        for row in chunk_rows[:3]:
            preview = re.sub(r"\s+", " ", str(row.get("chunkText") or "")).strip()
            if not preview:
                continue
            preview = preview[:180]
            lines.append(f"- {int(row.get('episodeNo') or 0)}화 일부: {preview}")

    if not lines:
        return "아직 관련 회차 요약이나 원문 미리보기를 찾지 못했습니다."
    return "\n".join(lines)


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
    if not rows:
        return None
    if len(rows) != 2:
        raise CustomResponseException(
            status_code=status.HTTP_409_CONFLICT,
            message="이전 메시지가 아직 처리 중입니다. 잠시 후 다시 시도해주세요.",
        )
    return rows


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
        SELECT session_id, product_id, title, created_date, updated_date
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
    return {
        "data": {
            "session": {
                "sessionId": session_row["session_id"],
                "productId": session_row["product_id"],
                "title": session_row["title"],
                "productTitle": product_state.get("title"),
                "productAuthorNickname": product_state.get("authorNickname"),
                "latestEpisodeNo": int(product_state.get("latestEpisodeNo") or 0),
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
    query = text(
        f"""
        INSERT INTO tb_story_agent_session
        (product_id, user_id, guest_key, title, deleted_yn, expires_at, created_id, updated_id)
        VALUES (
            :product_id,
            :user_id,
            :guest_key,
            :title,
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

    created_id = user_id if user_id is not None else settings.DB_DML_DEFAULT_ID

    session_lock_conn: AsyncConnection | None = None
    try:
        session_lock_conn = await _acquire_story_agent_session_lock(session_id=session_id)
        if session_lock_conn is None:
            raise CustomResponseException(
                status_code=status.HTTP_409_CONFLICT,
                message="같은 세션에서 다른 메시지를 처리 중입니다. 잠시 후 다시 시도해주세요.",
            )

        existing_messages = await _get_existing_turn_messages(
            session_id=session_id,
            client_message_id=req_body.client_message_id,
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

        assistant_reply, model_used, route_mode, fallback_used, intent = await _generate_story_agent_reply(
            session_id=session_id,
            product_row=product_row,
            user_prompt=req_body.content,
            db=db,
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
                    {
                        "messageId": int(assistant_result.lastrowid),
                        "role": "assistant",
                        "content": assistant_reply,
                    },
                ],
            }
        }
    except Exception:
        await db.rollback()
        raise
    finally:
        if session_lock_conn is not None:
            await _release_story_agent_session_lock(session_id=session_id, conn=session_lock_conn)
