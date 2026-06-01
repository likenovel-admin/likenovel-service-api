"""AI 챗 v2 서비스 (tool-use 기반 최소 구현)."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from html import unescape
from typing import Any

import httpx
from fastapi import status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.log_config import service_error_logger
from app.const import LOGGER_TYPE, settings
from app.exceptions import CustomResponseException
from app.utils.query import get_file_path_sub_query
import app.services.ai.recommendation_service as recommendation_service

error_logger = service_error_logger(LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_ERROR)
logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6
MAX_QUERY_TOOL_CALLS = 2
MAX_DETAIL_TOOL_CALLS = 1
MAX_EPISODE_PREVIEW_COUNT = 3
MAX_EPISODE_PREVIEW_CHARS = 1200
FINAL_RESPONSE_TOOL_NAME = "submit_final_recommendation"
FINAL_RESPONSE_MODES = {"recommend", "weak_recommend", "no_match"}

DATA_AGENT_SQL_MAX_LENGTH = 5000
DATA_AGENT_SQL_RESULT_LIMIT = 30
DATA_AGENT_SQL_TIMEOUT_SECONDS = 8.0
PRODUCT_STATUS_CODE_VALUES = {"end", "ongoing", "rest"}
PRODUCT_STATUS_CODE_ALIASES = {
    "end": "end",
    "complete": "end",
    "completed": "end",
    "finished": "end",
    "ongoing": "ongoing",
    "serial": "ongoing",
    "serializing": "ongoing",
    "publishing": "ongoing",
    "active": "ongoing",
    "rest": "rest",
    "pause": "rest",
    "paused": "rest",
    "hiatus": "rest",
    "break": "rest",
    "stop": "rest",
    "stopped": "rest",
    "suspended": "rest",
}
READONLY_SQL_ALLOWED_TABLES: dict[str, dict[str, Any]] = {
    "tb_product": {
        "description": "작품 기본 정보",
        "columns": [
            "product_id", "title", "author_name", "status_code", "price_type", "paid_episode_no",
            "publish_days", "last_episode_date", "count_hit", "count_bookmark", "count_recommend",
            "ratings_code", "open_yn", "primary_genre_id", "sub_genre_id",
        ],
    },
    "tb_product_episode": {
        "description": "회차 수/무료 유료/글자 수/회차별 반응",
        "columns": ["product_id", "episode_id", "episode_no", "price_type", "episode_text_count", "count_hit", "count_comment", "use_yn"],
    },
    "tb_product_ai_metadata": {
        "description": "작품 메타데이터 7축/요약/훅",
        "columns": [
            "product_id", "analysis_status", "premise", "hook", "episode_summary_text", "protagonist_type",
            "protagonist_desc", "protagonist_goal_primary", "mood", "pacing", "regression_type", "taste_tags",
            "worldview_tags", "protagonist_type_tags", "protagonist_job_tags", "protagonist_material_tags",
            "axis_romance_tags", "axis_style_tags", "similar_famous", "exclude_from_recommend_yn",
        ],
    },
    "tb_product_trend_index": {
        "description": "연독률/연재주기/독자층",
        "columns": ["product_id", "reading_rate", "writing_count_per_week", "primary_reader_group"],
    },
    "tb_product_count_variance": {
        "description": "상승세/이탈 등 증감 지표",
        "columns": [
            "product_id", "count_hit_indicator", "count_bookmark_indicator", "count_interest_indicator",
            "count_interest_loss_indicator", "count_interest_sustain_indicator", "reading_rate_indicator", "count_recommend_indicator",
        ],
    },
    "tb_product_rank": {
        "description": "작품 순위 스냅샷",
        "columns": ["product_id", "current_rank", "privious_rank", "created_date"],
    },
    "tb_product_engagement_metrics": {
        "description": "빈지율/이탈/재방문/읽기속도 등 작품 행동 지표",
        "columns": [
            "product_id", "computed_date", "binge_rate", "binge_count", "total_next_clicks", "total_readers",
            "dropoff_3d", "dropoff_7d", "dropoff_30d", "avg_dropoff_ep", "reengage_count", "strong_reengage",
            "reengage_rate", "avg_speed_cpm",
        ],
    },
    "tb_hourly_inflow": {
        "description": "작품 단위 성별/연령/결제 집계",
        "columns": ["product_id", "male_view_count", "female_view_count", "total_payment_count"],
    },
    "tb_product_hit_log": {
        "description": "일별 조회수 추이",
        "columns": ["product_id", "hit_date", "hit_count"],
    },
    "tb_product_review": {
        "description": "공개 리뷰 본문",
        "columns": ["product_id", "review_text", "open_yn", "created_date"],
    },
    "tb_cms_product_evaluation": {
        "description": "CMS 작품 평가 점수",
        "columns": ["product_id", "evaluation_score", "evaluation_yn", "created_date", "updated_date"],
    },
    "tb_standard_keyword": {
        "description": "장르/표준 키워드 라벨",
        "columns": ["keyword_id", "keyword_name", "major_genre_yn", "use_yn"],
    },
    "tb_product_user_keyword": {
        "description": "독자 태그",
        "columns": ["product_id", "keyword_name"],
    },
    "tb_applied_promotion": {
        "description": "작품 프로모션 상태",
        "columns": ["product_id", "type", "status", "start_date", "end_date"],
    },
}
DATA_AGENT_FORBIDDEN_SQL_PATTERN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|replace|merge|call|execute|show|use|describe|explain|set|into|outfile|dumpfile|load_file|sleep|benchmark|handler|lock|unlock)\b",
    re.IGNORECASE,
)
DATA_AGENT_SYSTEM_SCHEMA_PATTERN = re.compile(r"\b(information_schema|mysql|performance_schema|sys)\b", re.IGNORECASE)
DATA_AGENT_COMMENT_PATTERN = re.compile(r"(--|/\*|\*/|#)")
DATA_AGENT_FORBIDDEN_TOKEN_PATTERN = re.compile(r"@@|@`|@\w", re.IGNORECASE)
QUALIFIED_COLUMN_PATTERN = re.compile(r"\b(?P<alias>[A-Za-z_][\w]*)\.(?P<column>[A-Za-z_][\w]*)\b")
NULLS_ORDERING_PATTERN = re.compile(r"\s+NULLS\s+(?:FIRST|LAST)\b", re.IGNORECASE)
STATUS_EQ_PATTERN = re.compile(
    r"(?P<lhs>\b(?:[A-Za-z_][\w]*\.)?status_code\s*(?:=|!=|<>))\s*(?P<quote>['\"])(?P<value>[^'\"]+)(?P=quote)",
    re.IGNORECASE,
)
STATUS_IN_PATTERN = re.compile(
    r"(?P<lhs>\b(?:[A-Za-z_][\w]*\.)?status_code\s+(?:NOT\s+)?IN\s*)\((?P<body>[^)]*)\)",
    re.IGNORECASE,
)
TABLE_ALIAS_PATTERN = re.compile(
    r"\b(?:from|join)\s+`?(?P<table>[A-Za-z_][\w]*)`?(?:\s+(?:as\s+)?(?P<alias>[A-Za-z_][\w]*))?",
    re.IGNORECASE,
)
SQL_ALIAS_STOP_WORDS = {
    "where", "join", "left", "right", "inner", "outer", "cross", "group", "order", "limit", "having", "union", "on",
}
DATA_AGENT_TOOLS = [
    {
        "name": "get_fact_catalog",
        "description": "허용된 작품/집계 테이블 카탈로그와 조회 규칙을 반환한다.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_readonly_query",
        "description": "허용된 작품/집계 테이블에 대해 read-only SQL(SELECT 또는 WITH) 한 문장을 실행한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SELECT 또는 WITH로 시작하는 단일 SQL"},
            },
            "required": ["sql"],
        },
    },
    {
        "name": "get_product_info",
        "description": "최종 후보 작품 1개의 카드/상세 메타를 조회한다. 현재 작품의 특정 회차 줄거리를 물으면 include_episode_previews=true와 episode_numbers를 함께 사용해 공개 무료 회차 미리보기를 확인한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "integer"},
                "include_episode_previews": {
                    "type": "boolean",
                    "description": "현재 작품의 회차별 내용 질문에만 true. 공개 무료 회차의 제한된 미리보기만 반환한다.",
                },
                "episode_numbers": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "확인할 회차 번호. 최대 3개.",
                },
            },
            "required": ["product_id"],
        },
    },
    {
        "name": FINAL_RESPONSE_TOOL_NAME,
        "description": "최종 추천 결과를 제출한다. mode는 recommend/weak_recommend/no_match 중 하나다. recommend와 weak_recommend는 product_id가 필수이고, no_match는 product_id를 null로 제출해야 한다. reply는 빈 문장이나 일반론으로 끝내지 말고 유지한 조건/부족한 이유/다음 제안까지 포함한다. 작품을 추천할 때는 SQL/get_product_info 근거를 최소 2개 이상 녹인다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reply": {"type": "string"},
                "mode": {"type": "string", "enum": sorted(FINAL_RESPONSE_MODES)},
                "product_id": {"oneOf": [{"type": "integer"}, {"type": "null"}]},
            },
            "required": ["reply", "mode", "product_id"],
        },
    },
]


def _build_fact_catalog() -> dict:
    return {
        "rules": {
            "sql": "SELECT/WITH only",
            "limit": f"LIMIT {DATA_AGENT_SQL_RESULT_LIMIT} 이하 필수",
            "forbidden": ["INSERT", "UPDATE", "DELETE", "DDL", "system schema", "comments"],
        "guidance": [
                "다른 유저 개별 row는 조회하지 말고 작품/작품집계 테이블만 사용한다.",
                "JSON 태그 컬럼은 LIKE '%라벨%' 방식으로 탐색할 수 있다.",
                "tb_product를 기준으로 product_id로 조인하는 쿼리를 우선 사용한다.",
                "premise, hook, episode_summary_text, protagonist_*_tags, worldview_tags, axis_*_tags 는 tb_product_ai_metadata 컬럼이다.",
                "reading_rate, writing_count_per_week 는 tb_product_trend_index 컬럼이고 tb_product 컬럼이 아니다.",
                "binge_rate, dropoff_7d, reengage_rate, avg_speed_cpm 은 tb_product_engagement_metrics 컬럼이다.",
                "evaluation_score 는 tb_cms_product_evaluation 컬럼이다.",
                "원본 수치(count_hit/count_bookmark/count_recommend)는 tb_product에 있고, tb_product_count_variance에는 *_indicator만 있다.",
                "회차 수가 필요하면 존재하지 않는 컬럼을 추정하지 말고 tb_product_episode에서 COUNT(*)로 계산한다.",
                "tb_product에는 premise, hook, reading_rate, evaluation_score, episode_total 컬럼이 없다.",
                "adult_yn=N이면 tb_product를 조회할 때 반드시 ratings_code = 'all' 조건을 포함한다.",
                "tb_product.status_code 실제 값은 end(완결), ongoing(연재중), rest(휴재)만 사용한다. completed/serial/paused 같은 별칭은 쓰지 말고, 서버가 발견하면 end/ongoing/rest로 정규화한다.",
            ],
        },
        "tables": [
            {"table": table, "description": meta["description"], "columns": meta["columns"]}
            for table, meta in READONLY_SQL_ALLOWED_TABLES.items()
        ],
        "join_hints": [
            "tb_product.product_id = tb_product_ai_metadata.product_id",
            "tb_product.product_id = tb_product_trend_index.product_id",
            "tb_product.product_id = tb_product_engagement_metrics.product_id",
            "tb_product.product_id = tb_product_count_variance.product_id",
            "tb_product.product_id = tb_product_hit_log.product_id",
            "tb_product.primary_genre_id = tb_standard_keyword.keyword_id",
            "tb_product.sub_genre_id = tb_standard_keyword.keyword_id",
        ],
        "example_patterns": [
            "취향/태그 추천: tb_product + tb_product_ai_metadata + tb_product_trend_index",
            "연재주기/연참: tb_product + tb_product_trend_index",
            "명작/수작: tb_product + tb_product_trend_index + tb_product_engagement_metrics + tb_product_count_variance",
            "독자층/인구통계: tb_product + tb_hourly_inflow",
        ],
    }


def _normalize_adult_yn(adult_yn: str | None) -> str:
    value = (adult_yn or "N").upper().strip()
    if value not in {"Y", "N"}:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="adult_yn은 Y/N 값만 허용됩니다.",
        )
    return value


def _as_int_list(values: Any) -> list[int]:
    result: list[int] = []
    for value in values or []:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _compact_text(value: Any, max_length: int = 120) -> str:
    text_value = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text_value:
        return ""
    return text_value[:max_length]


def _plain_text_from_episode_html(value: Any, max_length: int = MAX_EPISODE_PREVIEW_CHARS) -> str:
    text_value = str(value or "")
    if not text_value:
        return ""
    text_value = re.sub(r"(?i)<br\s*/?>", "\n", text_value)
    text_value = re.sub(r"(?i)</p\s*>", "\n", text_value)
    text_value = re.sub(r"<[^>]+>", " ", text_value)
    text_value = unescape(text_value).replace("\xa0", " ")
    text_value = re.sub(r"\s+", " ", text_value).strip()
    return text_value[:max_length]


def _normalize_episode_numbers(values: Any) -> list[int]:
    episode_numbers: list[int] = []
    for value in values or []:
        episode_no = _safe_int(value, 0)
        if episode_no <= 0 or episode_no in episode_numbers:
            continue
        episode_numbers.append(episode_no)
        if len(episode_numbers) >= MAX_EPISODE_PREVIEW_COUNT:
            break
    return episode_numbers or [1, 2, 3]


def _extract_episode_numbers_from_query(text_value: str) -> list[int]:
    matches = re.findall(r"(\d{1,4})\s*화", str(text_value or ""))
    return _normalize_episode_numbers(matches)


def _resolve_conversation_product_id(page_context: dict, session_state: dict) -> int:
    current_product_id = _safe_int(page_context.get("current_product_id"), 0)
    if current_product_id > 0:
        return current_product_id

    for value in reversed(session_state.get("recommended_product_ids") or []):
        product_id = _safe_int(value, 0)
        if product_id > 0:
            return product_id
    return 0


def _is_current_product_episode_detail_request(
    messages: list[dict] | None,
    conversation_product_id: int,
) -> bool:
    if _safe_int(conversation_product_id, 0) <= 0:
        return False
    latest_query = _latest_user_query(messages)
    if not latest_query:
        return False
    has_episode_hint = bool(re.search(r"\d{1,4}\s*화", latest_query)) or "회차" in latest_query
    has_detail_hint = any(
        keyword in latest_query
        for keyword in ["내용", "줄거리", "뭔데", "무슨 얘기", "무슨 내용", "요약"]
    )
    return has_episode_hint and has_detail_hint


def _is_current_product_overview_request(
    messages: list[dict] | None,
    page_context: dict,
) -> bool:
    current_product_id = _safe_int(page_context.get("current_product_id"), 0)
    if current_product_id <= 0 or not page_context.get("focus_product_card"):
        return False
    latest_query = _latest_user_query(messages)
    if not latest_query or _is_similar_request(latest_query):
        return False
    current_title = str(page_context.get("current_product_title") or "").strip()
    has_current_anchor = any(
        keyword in latest_query
        for keyword in ["이 작품", "이거", "현재 작품", "보고 있는 작품"]
    ) or bool(current_title and current_title in latest_query)
    has_overview_intent = any(
        keyword in latest_query
        for keyword in ["어떤 작품", "무슨 작품", "알려줘", "소개", "설명", "줄거리", "내용", "키워드", "장르"]
    )
    return has_current_anchor and has_overview_intent


def _has_comparison_failure_text(reply: str) -> bool:
    text_value = str(reply or "")
    return any(
        keyword in text_value
        for keyword in ["비교 데이터", "유사한 다른 작품", "비교 후보", "추천하기 위한"]
    )


def _is_similar_request(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    keywords = [
        "비슷",
        "유사",
        "같은 느낌",
        "같은 스타일",
        "비슷한 작품",
        "유사작",
    ]
    return any(keyword in normalized for keyword in keywords)


def _extract_anchor_product_id(messages: list[dict] | None) -> int | None:
    for message in reversed(messages or []):
        value = message.get("product_id")
        try:
            product_id = int(value)
        except (TypeError, ValueError):
            continue
        if product_id > 0:
            return product_id
    return None


def _latest_user_query(messages: list[dict] | None) -> str:
    for message in reversed(messages or []):
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        content = str(message.get("content") or "").strip()
        if content:
            return content
    return ""


def _load_json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v or "").strip()]
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return []
        try:
            parsed = json.loads(text_value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed if str(v or "").strip()]
        except (json.JSONDecodeError, TypeError):
            pass
        return [text_value]
    return []


def _to_cover_url(path: str | None) -> str | None:
    if not path:
        return None
    raw = str(path).strip()
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    base = (settings.R2_SC_CDN_URL or "").rstrip("/")
    if not base:
        return raw
    return f"{base}/{raw.lstrip('/')}"


def _extract_text(content_blocks: Any) -> str:
    texts: list[str] = []
    for block in content_blocks or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text_value = str(block.get("text") or "").strip()
            if text_value:
                texts.append(text_value)
    return "\n".join(texts).strip()


def _extract_tool_use_blocks(content_blocks: Any) -> list[dict]:
    uses: list[dict] = []
    for block in content_blocks or []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            uses.append(block)
    return uses


def _extract_final_tool_input(tool_uses: list[dict]) -> dict | None:
    for block in tool_uses:
        if str(block.get("name") or "") == FINAL_RESPONSE_TOOL_NAME:
            tool_input = block.get("input")
            if isinstance(tool_input, dict):
                return tool_input
            return {}
    return None


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _to_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_to_json_safe(item) for item in value]
    return value


def _append_assistant_text_message(messages: list[dict], text: str) -> None:
    compact = str(text or "").strip()
    if compact:
        messages.append({"role": "assistant", "content": compact})


async def _result_mappings_all(result: Any) -> list[Any]:
    mappings = result.mappings()
    if inspect.isawaitable(mappings):
        mappings = await mappings
    rows = mappings.all()
    if inspect.isawaitable(rows):
        rows = await rows
    return list(rows or [])


async def _result_mappings_first(result: Any) -> Any:
    mappings = result.mappings()
    if inspect.isawaitable(mappings):
        mappings = await mappings
    row = mappings.first()
    if inspect.isawaitable(row):
        row = await row
    return row


async def _call_claude_messages(
    *,
    system_prompt: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: dict[str, Any] | None = None,
    max_tokens: int = 1024,
    timeout_seconds: float = 35.0,
) -> dict:
    if not settings.ANTHROPIC_API_KEY:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message="AI 추천 서비스가 설정되지 않았습니다.",
        )

    payload: dict[str, Any] = {
        "model": settings.ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )

    if response.status_code != 200:
        error_logger.error("Claude messages API error: %s %s", response.status_code, response.text)
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message="AI 서비스 호출에 실패했습니다.",
        )

    return response.json()


def _build_session_state(messages: list[dict] | None, context: dict | None, exclude_ids: list[int]) -> dict:
    recommended_product_ids: list[int] = []
    for message in messages or []:
        if str(message.get("role") or "").strip().lower() != "assistant":
            continue
        product_id = _safe_int(message.get("product_id"), 0)
        if product_id > 0 and product_id not in recommended_product_ids:
            recommended_product_ids.append(product_id)

    return {
        "trigger": str((context or {}).get("trigger") or "manual"),
        "last_user_query": _compact_text(_latest_user_query(messages), 160),
        "recommended_product_ids": recommended_product_ids[-3:],
        "exclude_product_ids": _as_int_list(exclude_ids)[-10:],
    }


async def _get_recent_read_samples(user_id: int, db: AsyncSession, limit: int = 3) -> list[dict]:
    safe_limit = max(1, min(int(limit), 5))
    query = text(
        f"""
        SELECT
            z.product_id,
            p.title,
            COUNT(DISTINCT z.episode_id) AS read_episode_count,
            MAX(z.updated_date) AS last_read_date
        FROM tb_user_product_usage z
        INNER JOIN tb_product p ON p.product_id = z.product_id
        WHERE z.user_id = :user_id
          AND z.use_yn = 'Y'
          AND p.open_yn = 'Y'
        GROUP BY z.product_id, p.title
        ORDER BY last_read_date DESC
        LIMIT {safe_limit}
        """
    )
    result = await db.execute(query, {"user_id": user_id})
    rows = []
    for row in await _result_mappings_all(result):
        product_id = _safe_int(row.get("product_id"), 0)
        title = _compact_text(row.get("title"), 60)
        if product_id <= 0 or not title:
            continue
        rows.append(
            {
                "product_id": product_id,
                "title": title,
                "read_episode_count": max(_safe_int(row.get("read_episode_count"), 0), 0),
            }
        )
    return rows


async def _build_behavior_summary(user_id: int | None, profile: dict | None, db: AsyncSession) -> dict:
    if not user_id:
        return {}

    recent_read_ids = await recommendation_service._get_recent_read_product_ids(user_id, db, limit=30)
    recent_read_samples = await _get_recent_read_samples(user_id, db, limit=3) if recent_read_ids else []

    return {
        "has_profile": bool(profile),
        "recent_read_count": len(recent_read_ids),
        "recent_reads": recent_read_samples,
    }


async def _build_page_context(context: dict | None, db: AsyncSession) -> dict:
    raw = context or {}
    page_type = str(raw.get("page_type") or "other").strip().lower()
    if page_type not in {"home", "product", "mypage", "other"}:
        page_type = "other"

    pathname = _compact_text(raw.get("pathname"), 120) or None
    current_product_id = _safe_int(raw.get("current_product_id"), 0) or None
    current_episode_id = _safe_int(raw.get("current_episode_id"), 0) or None
    focus_product_card = bool(raw.get("focus_product_card")) and bool(current_product_id)
    current_product_title = None

    if current_product_id:
        query = text(
            """
            SELECT p.title
            FROM tb_product p
            WHERE p.product_id = :product_id
            LIMIT 1
            """
        )
        result = await db.execute(query, {"product_id": current_product_id})
        row = await _result_mappings_first(result)
        current_product_title = _compact_text((row or {}).get("title"), 60) or None

    return {
        "page_type": page_type,
        "pathname": pathname,
        "current_product_id": current_product_id,
        "current_episode_id": current_episode_id,
        "current_product_title": current_product_title,
        "focus_product_card": focus_product_card,
    }


async def _build_reader_context(user_id: int | None, profile: dict | None, db: AsyncSession) -> dict:
    if not user_id:
        return {"taste_summary": None, "top_factors": [], "recent_reads": [], "read_product_ids": [], "factor_scores": {}}

    factor_scores = await recommendation_service._get_user_factor_scores(user_id, db)
    top_factors: list[dict[str, Any]] = []
    for factor_type, score_map in factor_scores.items():
        for label, score in score_map.items():
            if score <= 0:
                continue
            top_factors.append(
                {
                    "factor_type": factor_type,
                    "label": label,
                    "score": round(float(score), 4),
                }
            )
    top_factors.sort(key=lambda item: item["score"], reverse=True)

    recent_reads = await _get_recent_read_samples(user_id, db, limit=5)
    read_product_ids = sorted(_as_int_list((profile or {}).get("read_product_ids")))[:20]

    return {
        "taste_summary": _compact_text((profile or {}).get("taste_summary"), 180) or None,
        "top_factors": top_factors[:8],
        "recent_reads": recent_reads,
        "read_product_ids": read_product_ids,
        "factor_scores": factor_scores,
    }


def _build_data_agent_system_prompt(
    *,
    adult_yn: str,
    preset: str | None,
    reader_context: dict,
    session_state: dict,
    page_context: dict,
) -> str:
    lines = [
        "너는 라이크노벨 자유질문 데이터 에이전트다.",
        "추천기 preset 규칙에 맞추려 하지 말고, 허용된 데이터 카탈로그와 read-only SQL 조회 결과를 근거로 답한다.",
        "스키마나 상태값이 헷갈리면 get_fact_catalog를 먼저 호출해 허용 테이블/컬럼과 도메인 값을 확인한다.",
        "다른 유저 개별 row는 조회하지 말고, 작품/작품집계 테이블과 현재 독자 취향 요약만 사용한다.",
        "질문이 구체적이면 바로 조회한다. 질문이 너무 넓고 조건도 취향도 약하면 한 번만 좁혀 묻거나 버튼 프리셋 사용을 제안한다.",
        "추천할 때는 취향, 상태, 분량, 연재주기, 상승세, 품질, 독자반응 중 필요한 축을 스스로 판단해 조회한다.",
        "run_readonly_query는 최대 2회, get_product_info는 최대 1회만 쓸 수 있다. 충분한 후보가 있으면 더 찾지 말고 submit_final_recommendation으로 종료한다.",
        "run_readonly_query는 SELECT/WITH 단일 문장만 허용된다. LIMIT를 포함해라.",
        "존재하지 않는 컬럼을 추정하지 말고 get_fact_catalog에 나온 컬럼명만 사용한다. 회차 수는 필요하면 tb_product_episode에서 COUNT(*)로 계산한다.",
        "tb_product에는 premise, hook, reading_rate, evaluation_score, episode_total 컬럼이 없다. 이 값들은 각각 메타/트렌드/평가/회차 집계 테이블에서 가져와야 한다.",
        "작품 추천이면 SQL 결과에서 직접 product_id를 고르고, 근거 2개 이상을 reply에 녹여라.",
        "작품을 추천할 때는 submit_final_recommendation 전에 get_product_info를 한 번 호출해 premise, hook, synopsis_text, episode_summary_text, 7축 태그, 장르, 연독/연재주기 지표를 확인한다.",
        "현재 작품의 회차 내용 질문(예: 1화/2화 줄거리)이면 현재 페이지 작품 ID로 get_product_info(product_id=..., include_episode_previews=true, episode_numbers=[...])를 호출해 episode_previews를 근거로 답한다.",
        "episode_previews는 공개 무료 회차의 제한된 미리보기다. 원문 전문을 길게 옮기지 말고 회차당 1~2문장으로 요약한다. 미리보기가 없으면 확인 가능한 공개 회차 미리보기가 없다고 말한다.",
        "submit_final_recommendation.mode 규칙: recommend/weak_recommend면 product_id가 필수이고, no_match면 product_id는 null이어야 한다.",
        "조회 결과에 추천 가능한 후보가 1개라도 있으면 no_match보다 weak_recommend를 우선한다. no_match는 SQL 결과가 0건이거나, 모든 후보가 핵심 조건을 명백히 위반할 때만 사용한다.",
        "질문에 없는 숫자 임계치(예: 조회수 50,000 이상, 연독률 12% 이상)를 임의로 만들지 않는다. 작품 비교는 반드시 지금 조회한 DB 결과 내부의 상대 비교와 상위 후보 비교로 설명한다.",
        "질문에 여러 조건이 있어도 사용자가 '모두', '반드시', '정확히'를 명시하지 않았다면 strict AND로 0건을 만들지 않는다. 3개 조건이면 2개만 강하게 맞아도 weak_recommend 후보로 고려하고, OR/가중치 비교로 가장 가까운 작품을 고른다.",
        "예: '현대 배경 + 성장형 + 미스터리'는 세 조건 동시 만족 작품이 없더라도, 조회 결과 안에서 2/3 이상 맞는 후보를 우선 비교해 weak_recommend로 제시할 수 있다.",
        "최종 reply는 고정 템플릿을 복붙하지 말고 질문 맥락에 맞게 작성하되, 추천이면 독자 취향/조건과 추천 근거를 자연스럽게 연결한다.",
        "유저에게는 내부 기술 용어를 쓰지 마라. 금지어: 데이터베이스/DB/쿼리/SQL/카탈로그/조회 결과/반환값/스키마/테이블/컬럼/NULL.",
        "mode/internal 상태값(recommend/weak_recommend/no_match)을 답변 문장에 쓰지 마라.",
        "기술적 실패를 그대로 말하지 말고, 자연어로 안내한다. 예: '조건을 조금만 넓혀서 다시 찾아볼게요.'",
        "빈 답변 금지: '추천할 작품을 찾아봤어요', '조건에 맞는 작품을 골랐어요'처럼 근거 없는 일반 문장만 제출하지 않는다.",
        "정확한 후보가 약하거나 없으면 product_id를 null로 제출해도 되지만, 어떤 조건을 유지했는지와 왜 약한지 설명하고 다음 선택지 1개를 제안한다.",
        "현재 보고 있던 작품과 비슷한 작품을 추천할 때는 조회 결과를 근거로 공통점 2개와 차이점 1개를 설명한다.",
        "reply에는 가능하면 premise, hook, episode_summary_text, 7축 태그, reading_rate, writing_count_per_week, binge_rate, evaluation_score 같은 구체 근거를 2개 이상 포함한다.",
        "reply는 2~4문장으로 작성하고, JSON/코드블럭을 출력하지 않는다.",
        f"현재 독자 adult_yn={adult_yn}",
    ]
    if preset:
        lines.append(f"버튼 프리셋 힌트: {preset}")
    if reader_context.get("taste_summary"):
        lines.append(f"현재 독자 취향 요약: {reader_context['taste_summary']}")
    if reader_context.get("top_factors"):
        top_factor_line = ", ".join(
            f"{item['label']}({item['factor_type']}:{item['score']})"
            for item in reader_context["top_factors"][:8]
        )
        lines.append(f"상위 취향 팩터: {top_factor_line}")
    if reader_context.get("recent_reads"):
        recent_read_line = ", ".join(
            f"{item.get('title')}({max(_safe_int(item.get('read_episode_count'), 0), 1)}화)"
            for item in reader_context["recent_reads"]
            if item.get("title")
        )
        if recent_read_line:
            lines.append(f"최근 읽은 작품 흐름: {recent_read_line}")
    if reader_context.get("read_product_ids"):
        lines.append(f"이미 읽은 작품 ID: {reader_context['read_product_ids']}")
    if session_state.get("recommended_product_ids"):
        lines.append(f"이번 세션 이미 추천한 작품 ID: {session_state['recommended_product_ids']}")
        if not page_context.get("current_product_id"):
            lines.append(f"현재 대화 대상 작품 ID: {session_state['recommended_product_ids'][-1]}")
    if session_state.get("exclude_product_ids"):
        lines.append(f"이번 세션 제외 작품 ID: {session_state['exclude_product_ids']}")
    if page_context.get("current_product_id"):
        lines.append(f"현재 페이지 작품 ID: {page_context['current_product_id']}")
    if page_context.get("current_product_title"):
        lines.append(f"현재 보고 있던 작품: {page_context['current_product_title']}")
    if page_context.get("pathname"):
        lines.append(f"현재 경로: {page_context['pathname']}")
    lines.append(f"최종 응답은 반드시 {FINAL_RESPONSE_TOOL_NAME} tool로 제출한다.")
    return "\n".join(lines)


def _normalize_product_status_value(raw_value: str) -> str:
    normalized = PRODUCT_STATUS_CODE_ALIASES.get(str(raw_value or "").strip().lower())
    if normalized not in PRODUCT_STATUS_CODE_VALUES:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="tb_product.status_code는 end/ongoing/rest 값만 허용됩니다.",
        )
    return normalized


def _normalize_status_code_literals(sql: str) -> str:
    def replace_eq(match: re.Match[str]) -> str:
        lhs = match.group("lhs")
        value = _normalize_product_status_value(match.group("value"))
        return f"{lhs} '{value}'"

    def replace_in(match: re.Match[str]) -> str:
        lhs = match.group("lhs")
        body = match.group("body")
        values = re.findall(r"""['"]([^'"]+)['"]""", body)
        if not values:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="status_code IN 절에는 문자열 리터럴만 사용할 수 있습니다.",
            )
        normalized_values = ", ".join(f"'{_normalize_product_status_value(value)}'" for value in values)
        return f"{lhs}({normalized_values})"

    normalized = STATUS_EQ_PATTERN.sub(replace_eq, sql)
    normalized = STATUS_IN_PATTERN.sub(replace_in, normalized)
    return normalized


def _normalize_mysql_ordering(sql: str) -> str:
    return NULLS_ORDERING_PATTERN.sub("", sql)


def _extract_allowed_table_aliases(sql: str) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for match in TABLE_ALIAS_PATTERN.finditer(sql):
        table = match.group("table").lower()
        if table not in READONLY_SQL_ALLOWED_TABLES:
            continue
        alias_map[table] = table
        alias = (match.group("alias") or "").lower()
        if alias and alias not in SQL_ALIAS_STOP_WORDS:
            alias_map[alias] = table
    return alias_map


def _validate_qualified_columns(sql: str, alias_map: dict[str, str]) -> None:
    for match in QUALIFIED_COLUMN_PATTERN.finditer(sql):
        alias = match.group("alias").lower()
        column = match.group("column").lower()
        table = alias_map.get(alias)
        if not table:
            continue
        allowed_columns = {
            allowed_column.lower()
            for allowed_column in READONLY_SQL_ALLOWED_TABLES.get(table, {}).get("columns", [])
        }
        if column not in allowed_columns:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=f"허용 스키마와 맞지 않는 컬럼 참조입니다: {match.group('alias')}.{match.group('column')}",
            )


def _sanitize_readonly_sql(sql: str, adult_yn: str = "N") -> str:
    normalized = str(sql or "").strip().rstrip(";").strip()
    if not normalized:
        raise CustomResponseException(status_code=status.HTTP_400_BAD_REQUEST, message="SQL이 비어 있습니다.")
    if len(normalized) > DATA_AGENT_SQL_MAX_LENGTH:
        raise CustomResponseException(status_code=status.HTTP_400_BAD_REQUEST, message="SQL 길이가 너무 깁니다.")
    if DATA_AGENT_COMMENT_PATTERN.search(normalized):
        raise CustomResponseException(status_code=status.HTTP_400_BAD_REQUEST, message="SQL 주석은 허용되지 않습니다.")
    if ";" in normalized:
        raise CustomResponseException(status_code=status.HTTP_400_BAD_REQUEST, message="SQL은 한 문장만 허용됩니다.")
    if not re.match(r"^(select|with)\b", normalized, re.IGNORECASE):
        raise CustomResponseException(status_code=status.HTTP_400_BAD_REQUEST, message="SELECT/WITH 조회만 허용됩니다.")
    if DATA_AGENT_FORBIDDEN_SQL_PATTERN.search(normalized):
        raise CustomResponseException(status_code=status.HTTP_400_BAD_REQUEST, message="허용되지 않은 SQL 키워드가 포함되어 있습니다.")
    if DATA_AGENT_FORBIDDEN_TOKEN_PATTERN.search(normalized):
        raise CustomResponseException(status_code=status.HTTP_400_BAD_REQUEST, message="허용되지 않은 SQL 토큰이 포함되어 있습니다.")
    if DATA_AGENT_SYSTEM_SCHEMA_PATTERN.search(normalized):
        raise CustomResponseException(status_code=status.HTTP_400_BAD_REQUEST, message="시스템 스키마 조회는 허용되지 않습니다.")
    normalized = _normalize_status_code_literals(normalized)
    normalized = _normalize_mysql_ordering(normalized)

    table_refs = [
        ref.lower()
        for ref in re.findall(r"\b(?:from|join)\s+`?([a-zA-Z0-9_]+)`?", normalized, flags=re.IGNORECASE)
    ]
    disallowed = sorted({ref for ref in table_refs if ref not in READONLY_SQL_ALLOWED_TABLES})
    if disallowed:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=f"허용되지 않은 테이블이 포함되어 있습니다: {', '.join(disallowed)}",
        )
    _validate_qualified_columns(normalized, _extract_allowed_table_aliases(normalized))
    if _normalize_adult_yn(adult_yn) == "N" and "tb_product" in table_refs:
        lower_sql = normalized.lower().replace(" ", "")
        if "ratings_code='all'" not in lower_sql and 'ratings_code="all"' not in lower_sql:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="adult_yn=N 조회는 p.ratings_code = 'all' 조건이 필요합니다.",
            )

    limit_match = re.search(r"\blimit\s+(\d+)\b", normalized, re.IGNORECASE)
    if limit_match:
        if int(limit_match.group(1)) > DATA_AGENT_SQL_RESULT_LIMIT:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=f"LIMIT는 {DATA_AGENT_SQL_RESULT_LIMIT} 이하여야 합니다.",
            )
        return normalized
    return f"{normalized}\nLIMIT {DATA_AGENT_SQL_RESULT_LIMIT}"


async def _run_readonly_query(db: AsyncSession, sql: str, adult_yn: str = "N") -> dict:
    safe_sql = _sanitize_readonly_sql(sql, adult_yn=adult_yn)
    try:
        result = await asyncio.wait_for(db.execute(text(safe_sql)), timeout=DATA_AGENT_SQL_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise CustomResponseException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            message="쿼리 실행 시간이 너무 깁니다. 조건을 더 좁혀주세요.",
        ) from exc
    except SQLAlchemyError as exc:
        logger.warning("[ai_chat] readonly query failed: %s", exc)
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="조회 SQL이 허용 스키마와 맞지 않습니다. get_fact_catalog를 다시 참고해서 테이블/컬럼을 확인해주세요.",
        ) from exc

    rows = [_to_json_safe(dict(row)) for row in await _result_mappings_all(result)]
    return {
        "sql": safe_sql,
        "row_count": len(rows),
        "rows": rows,
    }

def _normalize_messages(messages: list[dict] | None, context: dict | None) -> list[dict]:
    normalized: list[dict] = []
    for message in messages or []:
        role = str(message.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        normalized.append({"role": role, "content": content})

    if normalized:
        return normalized[-12:]

    trigger = str((context or {}).get("trigger") or "").lower()
    if trigger == "browsing":
        return [{"role": "user", "content": "최근에 본 작품과 비슷한 작품 추천해줘"}]
    return [{"role": "user", "content": "재미있는 작품 추천해줘"}]


def _normalize_final_mode(raw_mode: Any, product_id: int | None) -> str:
    mode = str(raw_mode or "").strip().lower()
    if mode in FINAL_RESPONSE_MODES:
        return mode
    return "recommend" if product_id is not None else "no_match"


def _is_invalid_final_contract(mode: str, product_id: int | None) -> bool:
    if mode == "no_match":
        return product_id is not None
    return product_id is None


def _parse_final_payload(raw_text: str) -> tuple[str, int | None, str]:
    fallback = raw_text.strip()
    product_id: int | None = None
    try:
        parsed = recommendation_service._parse_json_from_llm(raw_text)
        reply = str(parsed.get("reply") or "").strip() or fallback
        raw_product_id = parsed.get("product_id")
        if raw_product_id is not None:
            try:
                product_id = int(raw_product_id)
            except (TypeError, ValueError):
                product_id = None
        return reply, product_id, _normalize_final_mode(parsed.get("mode"), product_id)
    except Exception:
        return fallback, None, _normalize_final_mode(None, None)


def _should_reask_final_with_product_id(
    *,
    final_tool_input: dict,
    detail_cache: dict[int, dict[str, Any]],
) -> bool:
    if final_tool_input.get("product_id") is not None:
        return False
    return bool(detail_cache)


async def _force_finalize_response(
    *,
    system_prompt: str,
    anthropic_messages: list[dict],
    reason: str,
    allowed_tool_names: list[str] | None = None,
) -> dict:
    forced_messages = list(anthropic_messages)
    forced_messages.append(
        {
            "role": "user",
            "content": (
                "추가 조회는 허용되지 않습니다. "
                f"{reason} "
                "지금까지 확보한 조회 결과만 근거로 반드시 submit_final_recommendation을 호출하세요."
            ),
        }
    )
    allowed_tools = (
        [tool for tool in DATA_AGENT_TOOLS if tool["name"] in set(allowed_tool_names)]
        if allowed_tool_names
        else [tool for tool in DATA_AGENT_TOOLS if tool["name"] == FINAL_RESPONSE_TOOL_NAME]
    )
    return await _call_claude_messages(
        system_prompt=system_prompt,
        messages=forced_messages,
        tools=allowed_tools,
        tool_choice={"type": "any"} if allowed_tool_names else {"type": "tool", "name": FINAL_RESPONSE_TOOL_NAME},
        max_tokens=900,
    )


def _should_reask_final_with_detail_lookup(
    *,
    final_tool_input: dict,
    last_query_rows: list[dict[str, Any]],
    detail_cache: dict[int, dict[str, Any]],
    detail_calls: int,
) -> bool:
    if final_tool_input.get("product_id") is not None:
        return False
    if detail_cache:
        return False
    if detail_calls >= MAX_DETAIL_TOOL_CALLS:
        return False
    return bool(last_query_rows)


def _text_tokens(value: str, *, max_count: int = 30) -> set[str]:
    text_value = str(value or "")
    if not text_value:
        return set()
    tokens = re.findall(r"[가-힣A-Za-z0-9]{2,}", text_value.lower())
    if not tokens:
        return set()
    return set(tokens[:max_count])


def _match_ratio(base_values: set[str], candidate_values: set[str]) -> float:
    if not base_values:
        return 0.0
    if not candidate_values:
        return 0.0
    return len(base_values & candidate_values) / len(base_values)


def _compute_similarity_score(base: dict, candidate: dict) -> tuple[float, list[str]]:
    matched_signals: list[str] = []
    score = 0.0

    axis_rules = [
        ("세계관", "worldview_tags", 0.12),
        ("주인공 타입", "protagonist_type_tags", 0.12),
        ("주인공 직업", "protagonist_job_tags", 0.10),
        ("능력/소재", "protagonist_material_tags", 0.10),
        ("관계/로맨스", "axis_romance_tags", 0.09),
        ("작풍", "axis_style_tags", 0.09),
    ]
    for label, key, weight in axis_rules:
        base_set = set(base.get(key) or [])
        candidate_set = set(candidate.get(key) or [])
        ratio = _match_ratio(base_set, candidate_set)
        if ratio > 0:
            score += weight * ratio
            matched_signals.append(label)

    base_goal = str(base.get("protagonist_goal_primary") or "").strip()
    candidate_goal = str(candidate.get("protagonist_goal_primary") or "").strip()
    if base_goal and candidate_goal and base_goal == candidate_goal:
        score += 0.08
        matched_signals.append("목표")

    base_mood = str(base.get("mood") or "").strip()
    candidate_mood = str(candidate.get("mood") or "").strip()
    if base_mood and candidate_mood and base_mood == candidate_mood:
        score += 0.07
        matched_signals.append("분위기")

    base_pacing = str(base.get("pacing") or "").strip()
    candidate_pacing = str(candidate.get("pacing") or "").strip()
    if base_pacing and candidate_pacing and base_pacing == candidate_pacing:
        score += 0.07
        matched_signals.append("전개속도")

    base_text_tokens = _text_tokens(
        f"{base.get('premise') or ''} {base.get('hook') or ''}",
        max_count=40,
    )
    candidate_text_tokens = _text_tokens(
        f"{candidate.get('premise') or ''} {candidate.get('hook') or ''}",
        max_count=40,
    )
    text_overlap = _match_ratio(base_text_tokens, candidate_text_tokens)
    if text_overlap > 0:
        score += 0.10 * text_overlap
        matched_signals.append("설정/훅")

    reading_rate = _safe_float(candidate.get("reading_rate"), 0.0)
    count_hit = _safe_int(candidate.get("count_hit"), 0)
    popularity_score = min(reading_rate, 1.0) * 0.6 + min(count_hit / 100000.0, 1.0) * 0.4
    score += 0.06 * popularity_score

    engagement_score = recommendation_service.score_engagement_for_recommendation(candidate)
    if engagement_score != 0:
        score += 0.08 * engagement_score
        matched_signals.append("독자반응")

    return score, matched_signals


def _score_similar_candidate(
    base: dict,
    candidate: dict,
    profile: dict | None = None,
) -> tuple[float, float, list[str], dict[str, float]]:
    similarity_score, matched_signals = _compute_similarity_score(base, candidate)
    taste_match = recommendation_service._compute_taste_match(candidate, profile)
    if similarity_score <= 0:
        return 0.0, 0.0, matched_signals, taste_match

    engagement_score = recommendation_service.score_engagement_for_recommendation(candidate)
    taste_score = recommendation_service.score_taste_for_candidate(candidate, profile)

    if recommendation_service.has_profile_preference_signal(profile):
        total_score = (taste_score * 2.4) + (similarity_score * 1.6) + (engagement_score * 0.35)
    else:
        total_score = (similarity_score * 2.1) + (engagement_score * 0.4)

    return round(total_score, 4), round(similarity_score, 4), matched_signals, taste_match


async def get_similar_products(
    db: AsyncSession,
    *,
    base_product_id: int,
    exclude_product_ids: list[int] | None = None,
    adult_yn: str = "N",
    limit: int = 3,
    profile: dict | None = None,
) -> tuple[dict | None, list[dict]]:
    normalized_adult = _normalize_adult_yn(adult_yn)
    normalized_limit = max(1, min(int(limit or 3), 5))
    exclude_ids = sorted(set(_as_int_list(exclude_product_ids)))

    base_query = text(
        f"""
        SELECT
            p.product_id,
            p.title,
            p.author_name,
            p.count_hit,
            {get_file_path_sub_query("p.thumbnail_file_id", "cover_path", "cover")},
            COALESCE(pti.reading_rate, 0) AS reading_rate,
            {recommendation_service.LATEST_ENGAGEMENT_SELECT_SQL},
            m.protagonist_type,
            m.protagonist_goal_primary,
            m.mood,
            m.pacing,
            m.premise,
            m.hook,
            m.taste_tags,
            m.worldview_tags,
            m.protagonist_type_tags,
            m.protagonist_job_tags,
            m.protagonist_material_tags,
            m.axis_romance_tags,
            m.axis_style_tags
        FROM tb_product p
        INNER JOIN tb_product_ai_metadata m ON m.product_id = p.product_id
        LEFT JOIN tb_product_trend_index pti ON pti.product_id = p.product_id
        {recommendation_service.LATEST_ENGAGEMENT_JOIN_SQL}
        WHERE p.product_id = :base_product_id
          AND p.open_yn = 'Y'
          AND m.analysis_status = 'success'
          AND COALESCE(m.exclude_from_recommend_yn, 'N') = 'N'
          AND p.author_name IS NOT NULL
          AND TRIM(p.author_name) <> ''
          {"AND p.ratings_code = 'all'" if normalized_adult == "N" else ""}
        LIMIT 1
        """
    )
    base_result = await db.execute(base_query, {"base_product_id": base_product_id})
    base_row = base_result.mappings().one_or_none()
    if not base_row:
        return None, []

    base = dict(base_row)
    base["worldview_tags"] = _load_json_list(base.get("worldview_tags"))
    base["protagonist_type_tags"] = _load_json_list(base.get("protagonist_type_tags"))
    base["protagonist_job_tags"] = _load_json_list(base.get("protagonist_job_tags"))
    base["protagonist_material_tags"] = _load_json_list(base.get("protagonist_material_tags"))
    base["axis_romance_tags"] = _load_json_list(base.get("axis_romance_tags"))
    base["axis_style_tags"] = _load_json_list(base.get("axis_style_tags"))
    base["cover_url"] = _to_cover_url(base.get("cover_path"))
    base["taste_tags"] = _load_json_list(base.get("taste_tags"))

    candidate_params: dict[str, Any] = {"base_product_id": base_product_id}
    exclude_clause = ""
    if exclude_ids:
        placeholders: list[str] = []
        for idx, product_id in enumerate(exclude_ids):
            key = f"exclude_{idx}"
            placeholders.append(f":{key}")
            candidate_params[key] = product_id
        exclude_clause = f" AND p.product_id NOT IN ({', '.join(placeholders)})"

    candidate_query = text(
        f"""
        SELECT
            p.product_id,
            p.title,
            p.author_name,
            p.status_code,
            p.price_type,
            p.monopoly_yn,
            p.contract_yn,
            p.last_episode_date,
            IF(p.last_episode_date >= DATE_SUB(NOW(), INTERVAL 24 HOUR), 'Y', 'N') AS new_release_yn,
            p.count_hit,
            {get_file_path_sub_query("p.thumbnail_file_id", "cover_path", "cover")},
            {recommendation_service.PUBLIC_OPEN_EPISODE_COUNT_SQL} AS episode_count,
            COALESCE(pti.reading_rate, 0) AS reading_rate,
            COALESCE(pti.writing_count_per_week, 0) AS writing_count_per_week,
            {recommendation_service.LATEST_ENGAGEMENT_SELECT_SQL},
            m.protagonist_type,
            m.protagonist_goal_primary,
            m.mood,
            m.pacing,
            m.premise,
            m.hook,
            m.taste_tags,
            m.worldview_tags,
            m.protagonist_type_tags,
            m.protagonist_job_tags,
            m.protagonist_material_tags,
            m.axis_romance_tags,
            m.axis_style_tags,
            IF(wff.product_id IS NOT NULL, 'Y', 'N') AS waiting_for_free_yn,
            IF(p69.product_id IS NOT NULL, 'Y', 'N') AS six_nine_path_yn
        FROM tb_product p
        INNER JOIN tb_product_ai_metadata m ON m.product_id = p.product_id
        LEFT JOIN tb_product_trend_index pti ON pti.product_id = p.product_id
        {recommendation_service.LATEST_ENGAGEMENT_JOIN_SQL}
        LEFT JOIN tb_applied_promotion wff ON wff.product_id = p.product_id AND wff.type = 'waiting-for-free' AND wff.status = 'ing' AND DATE(wff.start_date) <= CURDATE() AND (wff.end_date IS NULL OR DATE(wff.end_date) >= CURDATE())
        LEFT JOIN tb_applied_promotion p69 ON p69.product_id = p.product_id AND p69.type = '6-9-path' AND p69.status = 'ing' AND DATE(p69.start_date) <= CURDATE() AND (p69.end_date IS NULL OR DATE(p69.end_date) >= CURDATE())
        WHERE p.product_id <> :base_product_id
          AND p.open_yn = 'Y'
          AND m.analysis_status = 'success'
          AND COALESCE(m.exclude_from_recommend_yn, 'N') = 'N'
          AND p.author_name IS NOT NULL
          AND TRIM(p.author_name) <> ''
          {"AND p.ratings_code = 'all'" if normalized_adult == "N" else ""}
          {exclude_clause}
        ORDER BY COALESCE(pti.reading_rate, 0) DESC, p.count_hit DESC
        LIMIT 120
        """
    )
    candidate_result = await db.execute(candidate_query, candidate_params)
    candidate_rows = await _result_mappings_all(candidate_result)

    scored: list[dict] = []
    for row in candidate_rows:
        candidate = dict(row)
        candidate["worldview_tags"] = _load_json_list(candidate.get("worldview_tags"))
        candidate["protagonist_type_tags"] = _load_json_list(candidate.get("protagonist_type_tags"))
        candidate["protagonist_job_tags"] = _load_json_list(candidate.get("protagonist_job_tags"))
        candidate["protagonist_material_tags"] = _load_json_list(candidate.get("protagonist_material_tags"))
        candidate["axis_romance_tags"] = _load_json_list(candidate.get("axis_romance_tags"))
        candidate["axis_style_tags"] = _load_json_list(candidate.get("axis_style_tags"))
        candidate["taste_tags"] = _load_json_list(candidate.get("taste_tags"))
        total_score, similarity_score, matched_signals, taste_match = _score_similar_candidate(
            base,
            candidate,
            profile,
        )
        if total_score <= 0:
            continue
        scored.append(
            {
                "product_id": candidate.get("product_id"),
                "title": candidate.get("title"),
                "author_name": candidate.get("author_name"),
                "status_code": candidate.get("status_code"),
                "price_type": candidate.get("price_type"),
                "monopoly_yn": candidate.get("monopoly_yn"),
                "contract_yn": candidate.get("contract_yn", "N"),
                "last_episode_date": candidate.get("last_episode_date"),
                "new_release_yn": candidate.get("new_release_yn", "N"),
                "episode_count": _safe_int(candidate.get("episode_count"), 0),
                "cover_url": _to_cover_url(candidate.get("cover_path")),
                "writing_count_per_week": _safe_float(candidate.get("writing_count_per_week"), 0.0),
                "taste_tags": candidate.get("taste_tags") or [],
                "waiting_for_free_yn": candidate.get("waiting_for_free_yn", "N"),
                "six_nine_path_yn": candidate.get("six_nine_path_yn", "N"),
                "similarity_score": similarity_score,
                "total_score": total_score,
                "matched_signals": matched_signals[:3],
                "taste_match": taste_match,
            }
        )

    scored.sort(
        key=lambda item: (
            item.get("total_score", 0.0),
            item.get("similarity_score", 0.0),
        ),
        reverse=True,
    )
    return base, scored[:normalized_limit]


def _sanitize_reply_text(reply: str) -> str:
    text_value = str(reply or "").strip()
    if not text_value:
        return ""

    if text_value.startswith("```"):
        lines = text_value.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text_value = "\n".join(lines).strip()
        if text_value.lower().startswith("json"):
            text_value = text_value[4:].strip()

    if text_value.startswith("{") and '"reply"' in text_value:
        try:
            parsed = recommendation_service._parse_json_from_llm(text_value)
            parsed_reply = str(parsed.get("reply") or "").strip()
            if parsed_reply:
                text_value = parsed_reply
        except Exception:
            pass

    # 유저 노출 문구에서 내부 기술 용어를 치환한다.
    replacements: list[tuple[str, str]] = [
        (r"(데이터베이스|DB|db)", "작품 정보"),
        (r"(쿼리|SQL|sql)", "탐색"),
        (r"(카탈로그)", "작품 목록"),
        (r"(조회 결과|조회값)", "찾아본 결과"),
        (r"(반환값|반환)", "결과"),
        (r"(스키마|테이블|컬럼|NULL|null)", "정보"),
        (r"(빈지율)", "연달아 보는 비율"),
        (r"(연독률)", "다음 화로 이어서 보는 비율"),
        (r"(쿼리 오류|sql 오류|query error)", "일시적인 탐색 문제"),
        (r"\bweak_recommend\b", "추천 후보"),
        (r"\brecommend\b", "추천"),
        (r"\bno_match\b", "조건에 맞는 작품 없음"),
    ]
    for pattern, replace_to in replacements:
        text_value = re.sub(pattern, replace_to, text_value, flags=re.IGNORECASE)
    text_value = re.sub(r"\s{2,}", " ", text_value).strip()

    return text_value


def _build_focus_product_intro_reply(product: dict) -> str:
    title = str(product.get("title") or "현재 작품").strip()
    synopsis = _compact_text(
        product.get("synopsisText")
        or product.get("premise")
        or product.get("hook")
        or product.get("episodeSummaryText")
        or "",
        180,
    )
    taste_tags = [
        str(tag).strip()
        for tag in (product.get("tasteTags") or [])
        if str(tag).strip()
    ][:3]
    meta_parts: list[str] = []
    author = str(product.get("authorNickname") or "").strip()
    if author:
        meta_parts.append(f"{author} 작가")
    episode_count = _safe_int(product.get("episodeCount"), 0)
    if episode_count > 0:
        meta_parts.append(f"총 {episode_count}화")
    serial_cycle = str(product.get("serialCycle") or "").strip()
    if serial_cycle:
        meta_parts.append(serial_cycle)

    if synopsis:
        reply = f"현재 보고 계신 '{title}' 작품은 {synopsis}"
    else:
        reply = f"현재 보고 계신 '{title}' 작품 정보를 카드로 정리해드렸습니다."

    if taste_tags:
        reply = f"{reply} 키워드는 {', '.join(taste_tags)} 쪽으로 잡혀 있습니다."
    if meta_parts:
        reply = f"{reply} ({' · '.join(meta_parts)})"
    return reply


def _build_axis_taste_context(
    dna: dict,
    profile: dict | None,
    factor_scores: dict[str, dict[str, float]] | None = None,
) -> tuple[dict[str, float], dict[str, float], str]:
    safe_profile = profile or {}
    safe_factor_scores = factor_scores or {}
    axis_order = ("worldview", "job", "material", "romance", "style", "type", "goal")
    axis_scores: dict[str, float] = {}
    axis_top3: dict[str, list[dict]] = {}
    matched_axis_labels: dict[str, str] = {}

    for axis in axis_order:
        user_axis_scores = recommendation_service._build_user_axis_label_scores(axis, safe_factor_scores, safe_profile)
        match_score, _ = recommendation_service._calculate_axis_match(dna, axis, user_axis_scores)
        axis_scores[axis] = round(float(match_score), 4)
        top_entries, _ = recommendation_service._build_axis_top3_entries(axis, safe_factor_scores, safe_profile, top_n=3)
        axis_top3[axis] = top_entries
        if match_score > 0 and top_entries:
            matched_axis_labels[axis] = str(top_entries[0].get("label") or "").strip()

    def _average_nonzero(keys: tuple[str, ...]) -> float:
        values = [axis_scores.get(key, 0.0) for key in keys if axis_scores.get(key, 0.0) > 0]
        if not values:
            return 0.0
        return round(sum(values) / len(values), 2)

    legacy_match = {
        "protagonist": _average_nonzero(("type", "job", "goal")),
        "mood": _average_nonzero(("worldview", "material", "romance", "style")),
        "pacing": round(
            float(recommendation_service._compute_taste_match(dna, safe_profile).get("pacing") or 0.0),
            2,
        ),
    }
    matched_clauses: list[str] = []
    if matched_axis_labels.get("job"):
        matched_clauses.append(f"주인공 직업이 '{matched_axis_labels['job']}'")
    if matched_axis_labels.get("type"):
        matched_clauses.append(f"주인공 유형이 '{matched_axis_labels['type']}'")
    if matched_axis_labels.get("material"):
        matched_clauses.append(f"능력/소재가 '{matched_axis_labels['material']}'")
    if matched_axis_labels.get("goal"):
        matched_clauses.append(f"주인공 목표가 '{matched_axis_labels['goal']}'")
    if matched_axis_labels.get("worldview"):
        matched_clauses.append(f"세계관이 '{matched_axis_labels['worldview']}'")
    if matched_axis_labels.get("romance"):
        matched_clauses.append(f"관계/로맨스가 '{matched_axis_labels['romance']}'")
    if matched_axis_labels.get("style"):
        matched_clauses.append(f"작풍이 '{matched_axis_labels['style']}'")

    if matched_clauses:
        if len(matched_clauses) == 1:
            taste_summary = f"{matched_clauses[0]} 작품을 좋아하시는 것 같아요."
        else:
            taste_summary = f"{', '.join(matched_clauses[:-1])}이고, {matched_clauses[-1]} 작품을 좋아하시는 것 같아요."
    else:
        taste_summary = recommendation_service._build_compact_taste_summary(axis_top3)
    return legacy_match, axis_scores, taste_summary


async def _build_product_and_taste(
    *,
    selected_product_id: int | None,
    last_search_candidates: list[dict],
    profile: dict | None,
    db: AsyncSession,
    factor_scores: dict[str, dict[str, float]] | None = None,
    adult_yn: str = "N",
    fallback_to_search: bool = True,
    prefetched_product_info: dict | None = None,
) -> tuple[dict | None, dict]:
    taste_match = {"protagonist": 0, "mood": 0, "pacing": 0}
    product = None

    if selected_product_id:
        product_info = prefetched_product_info if _safe_int((prefetched_product_info or {}).get("product_id"), 0) == selected_product_id else None
        if product_info is None:
            try:
                product_info = await get_product_info(db, product_id=selected_product_id, adult_yn=adult_yn)
            except CustomResponseException:
                product_info = None
        if product_info:
            selected_dna = {
                "protagonist_type": product_info.get("protagonist_type"),
                "protagonist_desc": product_info.get("protagonist_desc"),
                "protagonist_goal_primary": product_info.get("protagonist_goal_primary"),
                "goal_confidence": product_info.get("goal_confidence"),
                "mood": product_info.get("mood"),
                "pacing": product_info.get("pacing"),
                "premise": product_info.get("premise"),
                "hook": product_info.get("hook"),
                "themes": product_info.get("themes"),
                "taste_tags": product_info.get("taste_tags"),
                "worldview_tags": product_info.get("worldview_tags"),
                "protagonist_type_tags": product_info.get("protagonist_type_tags"),
                "protagonist_job_tags": product_info.get("protagonist_job_tags"),
                "protagonist_material_tags": product_info.get("protagonist_material_tags"),
                "axis_romance_tags": product_info.get("axis_romance_tags"),
                "axis_style_tags": product_info.get("axis_style_tags"),
                "romance_chemistry_weight": product_info.get("romance_chemistry_weight"),
                "overall_confidence": product_info.get("overall_confidence"),
            }
            taste_match, axis_scores, taste_summary = _build_axis_taste_context(selected_dna, profile, factor_scores)
            product = {
                "productId": product_info["product_id"],
                "title": product_info["title"],
                "coverUrl": _to_cover_url(product_info.get("cover_url")),
                "authorNickname": product_info.get("author_name"),
                "episodeCount": _safe_int(product_info.get("episode_total"), 0),
                "matchReason": "",
                "tasteTags": [str(t) for t in (product_info.get("taste_tags") or [])[:5] if t],
                "serialCycle": recommendation_service._format_serial_cycle(
                    _safe_float(product_info.get("writing_count_per_week"), 0.0),
                    str(product_info.get("status_code") or ""),
                ),
                "priceType": product_info.get("price_type"),
                "ongoingState": product_info.get("status_code"),
                "monopolyYn": product_info.get("monopoly_yn"),
                "lastEpisodeDate": str(product_info["last_episode_date"]) if product_info.get("last_episode_date") else None,
                "newReleaseYn": product_info.get("new_release_yn", "N"),
                "cpContractYn": product_info.get("contract_yn", "N"),
                "waitingForFreeYn": product_info.get("waiting_for_free_yn", "N"),
                "sixNinePathYn": product_info.get("six_nine_path_yn", "N"),
                "tasteAxisScores": axis_scores,
                "tasteSummary": taste_summary,
                "synopsisText": product_info.get("synopsis_text"),
                "premise": product_info.get("premise"),
                "hook": product_info.get("hook"),
                "episodeSummaryText": product_info.get("episode_summary_text"),
                "similarFamous": product_info.get("similar_famous"),
                "themes": product_info.get("themes"),
                "worldviewTags": product_info.get("worldview_tags"),
                "protagonistTypeTags": product_info.get("protagonist_type_tags"),
                "protagonistJobTags": product_info.get("protagonist_job_tags"),
                "protagonistMaterialTags": product_info.get("protagonist_material_tags"),
                "axisRomanceTags": product_info.get("axis_romance_tags"),
                "axisStyleTags": product_info.get("axis_style_tags"),
                "primaryGenre": product_info.get("primary_genre"),
                "subGenre": product_info.get("sub_genre"),
            }

    if product is None and fallback_to_search and last_search_candidates:
        fallback_candidate = last_search_candidates[0]
        fallback_id = _safe_int(fallback_candidate.get("product_id"), 0)
        if fallback_id > 0:
            fallback_dna = fallback_candidate.get("dna") or {}
            taste_match, axis_scores, taste_summary = _build_axis_taste_context(fallback_dna, profile, factor_scores)
            fallback_taste_tags = fallback_dna.get("taste_tags") or []
            if isinstance(fallback_taste_tags, str):
                fallback_taste_tags = _load_json_list(fallback_taste_tags)
            product = {
                "productId": fallback_id,
                "title": str(fallback_candidate.get("title") or ""),
                "coverUrl": _to_cover_url(fallback_candidate.get("cover_url")),
                "authorNickname": fallback_candidate.get("author_name"),
                "episodeCount": _safe_int(fallback_candidate.get("episode_count"), 0),
                "matchReason": "",
                "tasteTags": [str(t) for t in fallback_taste_tags[:5] if t],
                "serialCycle": recommendation_service._format_serial_cycle(
                    _safe_float(fallback_candidate.get("writing_count_per_week"), 0.0),
                    str(fallback_candidate.get("status_code") or ""),
                ),
                "priceType": fallback_candidate.get("price_type"),
                "ongoingState": fallback_candidate.get("status_code"),
                "monopolyYn": fallback_candidate.get("monopoly_yn"),
                "lastEpisodeDate": str(fallback_candidate["last_episode_date"]) if fallback_candidate.get("last_episode_date") else None,
                "newReleaseYn": fallback_candidate.get("new_release_yn", "N"),
                "cpContractYn": fallback_candidate.get("contract_yn", "N"),
                "waitingForFreeYn": fallback_candidate.get("waiting_for_free_yn", "N"),
                "sixNinePathYn": fallback_candidate.get("six_nine_path_yn", "N"),
                "tasteAxisScores": axis_scores,
                "tasteSummary": taste_summary,
                "premise": fallback_dna.get("premise"),
                "hook": fallback_dna.get("hook"),
                "themes": _load_json_list(fallback_dna.get("themes")),
                "worldviewTags": _load_json_list(fallback_dna.get("worldview_tags")),
                "protagonistTypeTags": _load_json_list(fallback_dna.get("protagonist_type_tags")),
                "protagonistJobTags": _load_json_list(fallback_dna.get("protagonist_job_tags")),
                "protagonistMaterialTags": _load_json_list(fallback_dna.get("protagonist_material_tags")),
                "axisRomanceTags": _load_json_list(fallback_dna.get("axis_romance_tags")),
                "axisStyleTags": _load_json_list(fallback_dna.get("axis_style_tags")),
            }

    return product, taste_match


async def _attach_focus_product_card_if_needed(
    *,
    product: dict | None,
    taste_match: dict,
    page_context: dict,
    profile: dict | None,
    db: AsyncSession,
    factor_scores: dict | None,
    adult_yn: str,
) -> tuple[dict | None, dict]:
    if product is not None or not page_context.get("focus_product_card"):
        return product, taste_match

    current_product_id = _safe_int(page_context.get("current_product_id"), 0)
    if current_product_id <= 0:
        return product, taste_match

    return await _build_product_and_taste(
        selected_product_id=current_product_id,
        last_search_candidates=[],
        profile=profile,
        db=db,
        factor_scores=factor_scores,
        adult_yn=adult_yn,
        fallback_to_search=False,
    )


async def _get_public_episode_previews(
    db: AsyncSession,
    *,
    product_id: int,
    episode_numbers: list[int] | None,
    adult_yn: str = "N",
) -> list[dict[str, Any]]:
    normalized_adult = _normalize_adult_yn(adult_yn)
    normalized_episode_numbers = _normalize_episode_numbers(episode_numbers)
    placeholders = ", ".join(
        f":episode_no_{index}" for index, _ in enumerate(normalized_episode_numbers)
    )
    query_sql = text(
        f"""
        SELECT
            e.episode_no,
            e.episode_title,
            e.episode_content
        FROM tb_product_episode e
        INNER JOIN tb_product p ON p.product_id = e.product_id
        WHERE e.product_id = :product_id
          AND p.open_yn = 'Y'
          AND COALESCE(p.blind_yn, 'N') = 'N'
          {"AND p.ratings_code = 'all'" if normalized_adult == "N" else ""}
          AND e.use_yn = 'Y'
          AND e.open_yn = 'Y'
          AND (e.publish_reserve_date IS NULL OR e.publish_reserve_date <= CURRENT_TIMESTAMP)
          AND COALESCE(e.price_type, 'free') = 'free'
          AND e.episode_no IN ({placeholders})
        ORDER BY e.episode_no
        LIMIT {MAX_EPISODE_PREVIEW_COUNT}
        """
    )
    params = {"product_id": product_id}
    params.update(
        {f"episode_no_{index}": episode_no for index, episode_no in enumerate(normalized_episode_numbers)}
    )
    result = await db.execute(query_sql, params)
    rows = await _result_mappings_all(result)

    previews: list[dict[str, Any]] = []
    for row in rows:
        row_dict = dict(row)
        preview_text = _plain_text_from_episode_html(row_dict.get("episode_content"))
        if not preview_text:
            continue
        previews.append(
            {
                "episode_no": _safe_int(row_dict.get("episode_no"), 0),
                "title": row_dict.get("episode_title") or "",
                "preview_text": preview_text,
            }
        )
    return previews


async def get_product_info(
    db: AsyncSession,
    *,
    product_id: int,
    adult_yn: str = "N",
    include_episode_previews: bool = False,
    episode_numbers: list[int] | None = None,
) -> dict:
    normalized_adult = _normalize_adult_yn(adult_yn)
    query_sql = text(
        f"""
        SELECT
            p.product_id,
            p.title,
            p.author_name,
            p.status_code,
            p.price_type,
            p.monopoly_yn,
            p.contract_yn,
            p.paid_episode_no,
            p.publish_days,
            p.last_episode_date,
            p.synopsis_text,
            pg.keyword_name AS primary_genre_name,
            sg.keyword_name AS sub_genre_name,
            IF(p.last_episode_date >= DATE_SUB(NOW(), INTERVAL 24 HOUR), 'Y', 'N') AS new_release_yn,
            p.count_hit,
            p.count_bookmark,
            p.count_recommend,
            p.ratings_code,
            {get_file_path_sub_query("p.thumbnail_file_id", "cover_path", "cover")},
            {recommendation_service.PUBLIC_OPEN_EPISODE_COUNT_SQL} AS episode_total,
            (SELECT COUNT(*)
             FROM tb_product_episode e
             WHERE e.product_id = p.product_id
               AND e.use_yn = 'Y'
               AND e.open_yn = 'Y'
               AND e.price_type = 'free') AS free_episode_count,
            (SELECT COUNT(*)
             FROM tb_product_episode e
             WHERE e.product_id = p.product_id
               AND e.use_yn = 'Y'
               AND e.open_yn = 'Y'
               AND e.price_type = 'paid') AS paid_episode_count,
            COALESCE(pti.reading_rate, 0) AS reading_rate,
            COALESCE(pti.writing_count_per_week, 0) AS writing_count_per_week,
            {recommendation_service.LATEST_ENGAGEMENT_SELECT_SQL},
            pti.primary_reader_group,
            pr.current_rank,
            pr.privious_rank,
            m.protagonist_type,
            m.protagonist_desc,
            m.protagonist_goal_primary,
            m.goal_confidence,
            m.mood,
            m.pacing,
            m.regression_type,
            m.premise,
            m.hook,
            m.themes,
            m.similar_famous,
            m.heroine_type,
            m.heroine_weight,
            m.romance_chemistry_weight,
            m.episode_summary_text,
            m.overall_confidence,
            m.taste_tags,
            m.worldview_tags,
            m.protagonist_type_tags,
            m.protagonist_job_tags,
            m.protagonist_material_tags,
            m.axis_romance_tags,
            m.axis_style_tags,
            IF(wff.product_id IS NOT NULL, 'Y', 'N') AS waiting_for_free_yn,
            IF(p69.product_id IS NOT NULL, 'Y', 'N') AS six_nine_path_yn
        FROM tb_product p
        LEFT JOIN tb_product_ai_metadata m
          ON m.product_id = p.product_id
         AND m.analysis_status = 'success'
         AND COALESCE(m.exclude_from_recommend_yn, 'N') = 'N'
        LEFT JOIN tb_product_trend_index pti ON pti.product_id = p.product_id
        {recommendation_service.LATEST_ENGAGEMENT_JOIN_SQL}
        LEFT JOIN tb_standard_keyword pg
          ON pg.keyword_id = p.primary_genre_id
         AND pg.use_yn = 'Y'
        LEFT JOIN tb_standard_keyword sg
          ON sg.keyword_id = p.sub_genre_id
         AND sg.use_yn = 'Y'
        LEFT JOIN (
            SELECT r1.product_id, r1.current_rank, r1.privious_rank
            FROM tb_product_rank r1
            INNER JOIN (
                SELECT product_id, MAX(created_date) AS max_created_date
                FROM tb_product_rank
                GROUP BY product_id
            ) r2
              ON r1.product_id = r2.product_id
             AND r1.created_date = r2.max_created_date
        ) pr ON pr.product_id = p.product_id
        LEFT JOIN tb_applied_promotion wff ON wff.product_id = p.product_id AND wff.type = 'waiting-for-free' AND wff.status = 'ing' AND DATE(wff.start_date) <= CURDATE() AND (wff.end_date IS NULL OR DATE(wff.end_date) >= CURDATE())
        LEFT JOIN tb_applied_promotion p69 ON p69.product_id = p.product_id AND p69.type = '6-9-path' AND p69.status = 'ing' AND DATE(p69.start_date) <= CURDATE() AND (p69.end_date IS NULL OR DATE(p69.end_date) >= CURDATE())
        WHERE p.product_id = :product_id
          AND p.open_yn = 'Y'
          {"AND p.ratings_code = 'all'" if normalized_adult == "N" else ""}
          AND p.author_name IS NOT NULL
          AND TRIM(p.author_name) <> ''
        LIMIT 1
        """
    )
    result = await db.execute(query_sql, {"product_id": product_id})
    row = result.mappings().one_or_none()
    if not row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="작품 정보를 찾을 수 없습니다.",
        )

    row_dict = dict(row)
    summary_line = (
        f"{row_dict.get('title') or ''} | "
        f"{row_dict.get('author_name') or ''} | "
        f"{_safe_int(row_dict.get('episode_total'), 0)}화 | "
        f"연독률 {_safe_float(row_dict.get('reading_rate'), 0.0):.2f}"
    ).strip(" |")

    product_info = {
        "product_id": row_dict.get("product_id"),
        "title": row_dict.get("title"),
        "author_name": row_dict.get("author_name"),
        "status_code": row_dict.get("status_code"),
        "price_type": row_dict.get("price_type"),
        "paid_episode_no": _safe_int(row_dict.get("paid_episode_no"), 0),
        "publish_days": row_dict.get("publish_days"),
        "last_episode_date": str(row_dict.get("last_episode_date") or ""),
        "count_hit": _safe_int(row_dict.get("count_hit"), 0),
        "count_bookmark": _safe_int(row_dict.get("count_bookmark"), 0),
        "count_recommend": _safe_int(row_dict.get("count_recommend"), 0),
        "ratings_code": row_dict.get("ratings_code"),
        "cover_url": _to_cover_url(row_dict.get("cover_path")),
        "episode_total": _safe_int(row_dict.get("episode_total"), 0),
        "free_episode_count": _safe_int(row_dict.get("free_episode_count"), 0),
        "paid_episode_count": _safe_int(row_dict.get("paid_episode_count"), 0),
        "reading_rate": round(_safe_float(row_dict.get("reading_rate"), 0.0), 4),
        "writing_count_per_week": round(_safe_float(row_dict.get("writing_count_per_week"), 0.0), 2),
        "binge_rate": round(_safe_float(row_dict.get("binge_rate"), 0.0), 4),
        "total_next_clicks": _safe_int(row_dict.get("total_next_clicks"), 0),
        "total_readers": _safe_int(row_dict.get("total_readers"), 0),
        "dropoff_7d": _safe_int(row_dict.get("dropoff_7d"), 0),
        "reengage_rate": round(_safe_float(row_dict.get("reengage_rate"), 0.0), 4),
        "avg_speed_cpm": round(_safe_float(row_dict.get("avg_speed_cpm"), 0.0), 1),
        "primary_reader_group": row_dict.get("primary_reader_group"),
        "current_rank": _safe_int(row_dict.get("current_rank"), 0),
        "previous_rank": _safe_int(row_dict.get("privious_rank"), 0),
        "synopsis_text": _compact_text(row_dict.get("synopsis_text"), 1200),
        "primary_genre": row_dict.get("primary_genre_name"),
        "sub_genre": row_dict.get("sub_genre_name"),
        "premise": row_dict.get("premise"),
        "hook": row_dict.get("hook"),
        "themes": _load_json_list(row_dict.get("themes")),
        "similar_famous": _compact_text(row_dict.get("similar_famous"), 500),
        "heroine_type": row_dict.get("heroine_type"),
        "heroine_weight": row_dict.get("heroine_weight"),
        "romance_chemistry_weight": row_dict.get("romance_chemistry_weight"),
        "episode_summary_text": _compact_text(row_dict.get("episode_summary_text"), 1600),
        "overall_confidence": round(_safe_float(row_dict.get("overall_confidence"), 0.0), 4),
        "mood": row_dict.get("mood"),
        "pacing": row_dict.get("pacing"),
        "regression_type": row_dict.get("regression_type"),
        "protagonist_type": row_dict.get("protagonist_type"),
        "protagonist_desc": row_dict.get("protagonist_desc"),
        "protagonist_goal_primary": row_dict.get("protagonist_goal_primary"),
        "goal_confidence": round(_safe_float(row_dict.get("goal_confidence"), 0.0), 4),
        "taste_tags": _load_json_list(row_dict.get("taste_tags")),
        "worldview_tags": _load_json_list(row_dict.get("worldview_tags")),
        "protagonist_type_tags": _load_json_list(row_dict.get("protagonist_type_tags")),
        "protagonist_job_tags": _load_json_list(row_dict.get("protagonist_job_tags")),
        "protagonist_material_tags": _load_json_list(row_dict.get("protagonist_material_tags")),
        "axis_romance_tags": _load_json_list(row_dict.get("axis_romance_tags")),
        "axis_style_tags": _load_json_list(row_dict.get("axis_style_tags")),
        "summary_line": summary_line,
    }
    if include_episode_previews:
        product_info["episode_previews"] = await _get_public_episode_previews(
            db,
            product_id=product_id,
            episode_numbers=episode_numbers,
            adult_yn=adult_yn,
        )
    return product_info


async def _dispatch_tool(
    *,
    db: AsyncSession,
    tool_name: str,
    tool_input: dict,
    exclude_ids: list[int],
    adult_yn: str,
) -> Any:
    if tool_name == "get_fact_catalog":
        return _build_fact_catalog()

    if tool_name == "run_readonly_query":
        sql = str(tool_input.get("sql") or "").strip()
        logger.info("[ai_chat] tool=run_readonly_query sql=%s", sql)
        return await _run_readonly_query(db, sql, adult_yn=adult_yn)

    if tool_name == "get_product_info":
        product_id = _safe_int(tool_input.get("product_id"))
        if product_id <= 0:
            return {"error": "product_id가 유효하지 않습니다."}
        raw_episode_numbers = tool_input.get("episode_numbers")
        episode_numbers = raw_episode_numbers if isinstance(raw_episode_numbers, list) else None
        return await get_product_info(
            db,
            product_id=product_id,
            adult_yn=adult_yn,
            include_episode_previews=bool(tool_input.get("include_episode_previews")),
            episode_numbers=episode_numbers,
        )

    return {"error": f"지원하지 않는 도구입니다: {tool_name}"}


async def handle_chat(
    *,
    kc_user_id: str | None,
    messages: list[dict] | None,
    context: dict | None,
    preset: str | None,
    exclude_ids: list[int],
    adult_yn: str,
    db: AsyncSession,
) -> dict:
    normalized_adult = _normalize_adult_yn(adult_yn)
    normalized_preset = str(preset or "").strip() or None

    user_id = await recommendation_service._get_user_id_by_kc(kc_user_id, db) if kc_user_id else None
    profile = await recommendation_service.get_user_taste_profile(user_id, db) if user_id else None

    exclude_set = set(_as_int_list(exclude_ids))
    if profile:
        exclude_set.update(_as_int_list(profile.get("read_product_ids")))
    combined_exclude = sorted(exclude_set)

    normalized_messages = _normalize_messages(messages, context)
    if normalized_preset and not _latest_user_query(normalized_messages):
        normalized_messages = [{"role": "user", "content": "조건에 맞는 작품 추천해줘"}]

    session_state = _build_session_state(messages, context, combined_exclude)
    page_context = await _build_page_context(context, db)
    reader_context = await _build_reader_context(user_id, profile, db)
    system_prompt = _build_data_agent_system_prompt(
        adult_yn=normalized_adult,
        preset=normalized_preset,
        reader_context=reader_context,
        session_state=session_state,
        page_context=page_context,
    )

    anthropic_messages = list(normalized_messages)
    last_text = ""
    last_query_rows: list[dict[str, Any]] = []
    detail_cache: dict[int, dict[str, Any]] = {}
    query_calls = 0
    detail_calls = 0
    force_finalize_reason: str | None = None
    force_finalize_allowed_tool_names: list[str] | None = None
    forced_finalize_attempted = False

    for _ in range(MAX_TOOL_ROUNDS):
        if force_finalize_reason:
            forced_finalize_attempted = True
            response = await _force_finalize_response(
                system_prompt=system_prompt,
                anthropic_messages=anthropic_messages,
                reason=force_finalize_reason,
                allowed_tool_names=force_finalize_allowed_tool_names,
            )
            force_finalize_reason = None
            force_finalize_allowed_tool_names = None
        else:
            response = await _call_claude_messages(
                system_prompt=system_prompt,
                messages=anthropic_messages,
                tools=DATA_AGENT_TOOLS,
                tool_choice={"type": "any"},
                max_tokens=1400,
            )
        content = response.get("content") or []
        last_text = _extract_text(content)
        tool_uses = _extract_tool_use_blocks(content)
        final_tool_input = _extract_final_tool_input(tool_uses)

        if final_tool_input is not None:
            parsed_product_id: int | None = None
            if final_tool_input.get("product_id") is not None:
                candidate_product_id = _safe_int(final_tool_input.get("product_id"), 0)
                if candidate_product_id > 0:
                    parsed_product_id = candidate_product_id
            final_mode = _normalize_final_mode(final_tool_input.get("mode"), parsed_product_id)
            if _is_invalid_final_contract(final_mode, parsed_product_id) and not forced_finalize_attempted:
                logger.warning(
                    "[ai_chat] final tool contract mismatch mode=%s product_id=%s",
                    final_mode,
                    parsed_product_id,
                )
                _append_assistant_text_message(anthropic_messages, last_text)
                force_finalize_reason = (
                    "submit_final_recommendation 계약이 잘못됐습니다. "
                    "recommend/weak_recommend면 product_id를 반드시 넣고, no_match면 product_id를 null로 제출하세요."
                )
                force_finalize_allowed_tool_names = [FINAL_RESPONSE_TOOL_NAME]
                continue
            current_product_id = _resolve_conversation_product_id(page_context, session_state)
            if (
                _is_current_product_episode_detail_request(normalized_messages, current_product_id)
                and current_product_id > 0
                and current_product_id not in detail_cache
                and detail_calls < MAX_DETAIL_TOOL_CALLS
                and not forced_finalize_attempted
            ):
                logger.warning("[ai_chat] final tool skipped current product episode previews; requiring detail lookup")
                _append_assistant_text_message(anthropic_messages, last_text)
                episode_numbers = _extract_episode_numbers_from_query(_latest_user_query(normalized_messages))
                force_finalize_reason = (
                    f"현재 페이지 작품 ID {current_product_id}의 {episode_numbers}화 내용을 묻는 질문입니다. "
                    f"get_product_info(product_id={current_product_id}, include_episode_previews=true, episode_numbers={episode_numbers})를 먼저 호출한 뒤 "
                    "episode_previews를 근거로 회차당 1~2문장으로 요약해 답하세요. "
                    "원문 전문을 길게 인용하지 말고, episode_previews가 비어 있을 때만 확인 가능한 공개 회차 미리보기가 없다고 말하세요."
                )
                force_finalize_allowed_tool_names = ["get_product_info", FINAL_RESPONSE_TOOL_NAME]
                continue
            if (
                _is_current_product_overview_request(normalized_messages, page_context)
                and current_product_id > 0
                and current_product_id not in detail_cache
                and detail_calls < MAX_DETAIL_TOOL_CALLS
                and not forced_finalize_attempted
            ):
                logger.warning("[ai_chat] final tool skipped current product info; requiring detail lookup")
                _append_assistant_text_message(anthropic_messages, last_text)
                force_finalize_reason = (
                    f"현재 페이지 작품 ID {current_product_id}에 대한 질문입니다. "
                    f"get_product_info(product_id={current_product_id})를 먼저 호출한 뒤 "
                    "작품의 synopsis_text, premise, hook, episode_summary_text, 장르/키워드, 회차 수/연재주기를 근거로 답하세요. "
                    "현재 작품 자체를 묻는 질문이므로 유사 작품 비교 데이터가 없다는 이유로 no_match를 제출하지 마세요."
                )
                force_finalize_allowed_tool_names = ["get_product_info", FINAL_RESPONSE_TOOL_NAME]
                continue
            if _should_reask_final_with_product_id(
                final_tool_input=final_tool_input,
                detail_cache=detail_cache,
            ) and not forced_finalize_attempted:
                logger.warning("[ai_chat] final tool missing product_id after detail lookup; reasking finalize")
                _append_assistant_text_message(anthropic_messages, last_text)
                inspected_ids = sorted(detail_cache.keys())
                force_finalize_reason = (
                    "이미 get_product_info로 확인한 작품이 있습니다. "
                    f"확인한 작품 ID {inspected_ids} 중 가장 가까운 작품 하나를 고르고 weak_recommend 또는 recommend로 제출하세요. "
                    "정말 SQL 결과가 0건이거나 모든 후보가 핵심 조건을 명백히 위반한 경우에만 no_match를 사용하세요. "
                    "product_id=null로 제출할 때는 특정 작품명을 reply에 쓰지 마세요."
                )
                continue
            if _should_reask_final_with_detail_lookup(
                final_tool_input=final_tool_input,
                last_query_rows=last_query_rows,
                detail_cache=detail_cache,
                detail_calls=detail_calls,
            ) and not forced_finalize_attempted:
                logger.warning("[ai_chat] final tool missing product_id while query candidates exist; requiring detail lookup")
                _append_assistant_text_message(anthropic_messages, last_text)
                candidate_ids = [
                    _safe_int(row.get("product_id"), 0)
                    for row in last_query_rows[:5]
                    if isinstance(row, dict) and _safe_int(row.get("product_id"), 0) > 0
                ]
                force_finalize_reason = (
                    "직전 SQL 조회에서 추천 가능한 후보가 이미 있습니다. "
                    f"후보 작품 ID {candidate_ids} 중 가장 가까운 작품을 확인하려면 get_product_info(product_id=...)를 먼저 호출한 뒤 "
                    "recommend 또는 weak_recommend로 submit_final_recommendation을 제출하세요. "
                    "정말 SQL 결과가 0건이거나 모든 후보가 핵심 조건을 명백히 위반한 경우에만 no_match를 사용하세요. "
                    "product_id=null로 제출할 때는 특정 작품명을 reply에 쓰지 마세요."
                )
                force_finalize_allowed_tool_names = ["get_product_info", FINAL_RESPONSE_TOOL_NAME]
                continue
            current_overview_request = _is_current_product_overview_request(normalized_messages, page_context)
            current_overview_product_id = _safe_int(page_context.get("current_product_id"), 0)
            selected_product_id: int | None = None
            if parsed_product_id is not None:
                selected_product_id = parsed_product_id
            selected_from_current_product_context = False
            if (
                selected_product_id is None
                and final_mode == "no_match"
                and current_overview_request
            ):
                if current_overview_product_id > 0:
                    selected_product_id = current_overview_product_id
                    selected_from_current_product_context = True
            if (
                current_overview_request
                and selected_product_id == current_overview_product_id
                and current_overview_product_id > 0
                and final_mode == "no_match"
            ):
                final_mode = "weak_recommend"
                selected_from_current_product_context = True
            product, taste_match = await _build_product_and_taste(
                selected_product_id=selected_product_id,
                last_search_candidates=[],
                profile=profile,
                db=db,
                factor_scores=reader_context.get("factor_scores"),
                adult_yn=normalized_adult,
                fallback_to_search=False,
                prefetched_product_info=detail_cache.get(selected_product_id) if selected_product_id else None,
            )
            if not selected_from_current_product_context:
                product, taste_match = await _attach_focus_product_card_if_needed(
                    product=product,
                    taste_match=taste_match,
                    page_context=page_context,
                    profile=profile,
                    db=db,
                    factor_scores=reader_context.get("factor_scores"),
                    adult_yn=normalized_adult,
            )
            raw_reply = str(final_tool_input.get("reply") or last_text or "").strip()
            if product:
                if final_mode == "no_match" and selected_product_id is not None:
                    final_mode = "weak_recommend"
                if selected_from_current_product_context or (
                    current_overview_request
                    and selected_product_id == current_overview_product_id
                    and _has_comparison_failure_text(raw_reply)
                ):
                    reply = _build_focus_product_intro_reply(product)
                else:
                    reply = _sanitize_reply_text(raw_reply)
                if not reply:
                    logger.warning("[ai_chat] final tool reply empty with product_id=%s", selected_product_id)
                    reply = f"지금까지 조회 결과 기준으로는 '{product['title']}'이 가장 가깝습니다."
                product["matchReason"] = reply
            else:
                reply = _sanitize_reply_text(raw_reply)
                if not reply:
                    logger.warning("[ai_chat] final tool reply empty without product selection")
                    reply = "지금까지 조회 결과만으로는 작품을 확정하지 못했습니다. 조건 하나만 더 알려주시면 다시 찾겠습니다."

            if (
                product
                and current_overview_request
                and selected_product_id == current_overview_product_id
                and final_mode == "no_match"
            ):
                final_mode = "weak_recommend"

            return {
                "reply": reply,
                "product": product,
                "taste_match": taste_match,
                "tasteMatch": taste_match,
                "finalMode": final_mode,
            }

        if not tool_uses:
            if forced_finalize_attempted:
                reply, selected_product_id, final_mode = _parse_final_payload(last_text)
                product, taste_match = await _build_product_and_taste(
                    selected_product_id=selected_product_id,
                    last_search_candidates=[],
                    profile=profile,
                    db=db,
                    factor_scores=reader_context.get("factor_scores"),
                    adult_yn=normalized_adult,
                    fallback_to_search=False,
                    prefetched_product_info=detail_cache.get(selected_product_id) if selected_product_id else None,
                )
                reply = _sanitize_reply_text(reply) or "지금까지 조회 결과만으로는 작품을 확정하지 못했습니다. 조건 하나만 더 알려주시면 다시 찾겠습니다."
                if product:
                    product["matchReason"] = reply
                return {
                    "reply": reply,
                    "product": product,
                    "taste_match": taste_match,
                    "tasteMatch": taste_match,
                    "finalMode": final_mode,
                }

            logger.warning("[ai_chat] finalize_missing_tool last_text=%s", last_text[:300])
            anthropic_messages.append({"role": "assistant", "content": content})
            force_finalize_reason = "일반 텍스트 응답이 왔지만 submit_final_recommendation이 제출되지 않았습니다."
            continue

        anthropic_messages.append({"role": "assistant", "content": content})
        tool_results: list[dict] = []
        for block in tool_uses:
            tool_name = str(block.get("name") or "")
            if tool_name == FINAL_RESPONSE_TOOL_NAME:
                continue
            tool_input = block.get("input") or {}
            if tool_name == "run_readonly_query":
                query_calls += 1
                if query_calls > MAX_QUERY_TOOL_CALLS:
                    force_finalize_reason = f"run_readonly_query 한도 {MAX_QUERY_TOOL_CALLS}회를 초과했습니다."
                    tool_result = {
                        "error": force_finalize_reason,
                        "must_finalize": True,
                        "query_calls": query_calls - 1,
                    }
                else:
                    try:
                        tool_result = await _dispatch_tool(
                            db=db,
                            tool_name=tool_name,
                            tool_input=tool_input,
                            exclude_ids=combined_exclude,
                            adult_yn=normalized_adult,
                        )
                    except CustomResponseException as exc:
                        tool_result = {
                            "error": str(exc.message or "도구 실행에 실패했습니다."),
                            "status_code": exc.status_code,
                        }
            elif tool_name == "get_product_info":
                detail_calls += 1
                if detail_calls > MAX_DETAIL_TOOL_CALLS:
                    force_finalize_reason = f"get_product_info 한도 {MAX_DETAIL_TOOL_CALLS}회를 초과했습니다."
                    tool_result = {
                        "error": force_finalize_reason,
                        "must_finalize": True,
                        "detail_calls": detail_calls - 1,
                    }
                else:
                    try:
                        tool_result = await _dispatch_tool(
                            db=db,
                            tool_name=tool_name,
                            tool_input=tool_input,
                            exclude_ids=combined_exclude,
                            adult_yn=normalized_adult,
                        )
                    except CustomResponseException as exc:
                        tool_result = {
                            "error": str(exc.message or "도구 실행에 실패했습니다."),
                            "status_code": exc.status_code,
                        }
            else:
                try:
                    tool_result = await _dispatch_tool(
                        db=db,
                        tool_name=tool_name,
                        tool_input=tool_input,
                        exclude_ids=combined_exclude,
                        adult_yn=normalized_adult,
                    )
                except CustomResponseException as exc:
                    tool_result = {
                        "error": str(exc.message or "도구 실행에 실패했습니다."),
                        "status_code": exc.status_code,
                    }
            if tool_name == "run_readonly_query" and isinstance(tool_result, dict):
                rows = tool_result.get("rows") or []
                last_query_rows = [
                    row for row in rows
                    if isinstance(row, dict) and _safe_int(row.get("product_id"), 0) > 0
                ]
            if tool_name == "get_product_info" and isinstance(tool_result, dict):
                product_id = _safe_int(tool_result.get("product_id"), 0)
                if product_id > 0:
                    detail_cache[product_id] = tool_result
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.get("id"),
                    "content": json.dumps(_to_json_safe(tool_result), ensure_ascii=False),
                }
            )

        anthropic_messages.append({"role": "user", "content": tool_results})

    logger.warning(
        "[ai_chat] finalize_missing query_calls=%s detail_calls=%s forced_finalize_attempted=%s last_query_rows=%s",
        query_calls,
        detail_calls,
        forced_finalize_attempted,
        len(last_query_rows),
    )
    forced_response = await _force_finalize_response(
        system_prompt=system_prompt,
        anthropic_messages=anthropic_messages,
        reason="도구 호출 한도에 도달했거나 최종 제출 없이 루프가 종료되었습니다.",
    )
    forced_content = forced_response.get("content") or []
    forced_text = _extract_text(forced_content)
    forced_tool_input = _extract_final_tool_input(_extract_tool_use_blocks(forced_content))
    if forced_tool_input is not None:
        reply_text = str(forced_tool_input.get("reply") or forced_text or "").strip()
        selected_product_id = _safe_int(forced_tool_input.get("product_id"), 0) or None
        final_mode = _normalize_final_mode(forced_tool_input.get("mode"), selected_product_id)
        product, taste_match = await _build_product_and_taste(
            selected_product_id=selected_product_id,
            last_search_candidates=[],
            profile=profile,
            db=db,
            factor_scores=reader_context.get("factor_scores"),
            adult_yn=normalized_adult,
            fallback_to_search=False,
            prefetched_product_info=detail_cache.get(selected_product_id) if selected_product_id else None,
        )
        reply = _sanitize_reply_text(reply_text)
        if not reply:
            if product:
                reply = f"지금까지 조회 결과 기준으로는 '{product['title']}'이 가장 가깝습니다."
            else:
                reply = "지금까지 조회 결과만으로는 작품을 확정하지 못했습니다. 조건 하나만 더 알려주시면 다시 찾겠습니다."
        if product:
            product["matchReason"] = reply
        return {
            "reply": reply,
            "product": product,
            "taste_match": taste_match,
            "tasteMatch": taste_match,
            "finalMode": final_mode,
        }

    final_reply, _, final_mode = _parse_final_payload(forced_text or last_text)
    sanitized_last_text = _sanitize_reply_text(forced_text or last_text)
    final_reply = sanitized_last_text or _sanitize_reply_text(final_reply) or "지금까지 조회 결과만으로는 작품을 확정하지 못했습니다. 조건 하나만 더 알려주시면 다시 찾겠습니다."
    fallback_product_id = _safe_int(last_query_rows[0].get("product_id"), 0) if last_query_rows else 0
    if fallback_product_id > 0:
        product, taste_match = await _build_product_and_taste(
            selected_product_id=fallback_product_id,
            last_search_candidates=[],
            profile=profile,
            db=db,
            factor_scores=reader_context.get("factor_scores"),
            adult_yn=normalized_adult,
            fallback_to_search=False,
        )
        if product:
            reply = sanitized_last_text or f"지금까지 조회 결과 기준으로는 '{product['title']}'이 가장 가깝습니다."
            product["matchReason"] = reply
            return {
                "reply": reply,
                "product": product,
                "taste_match": taste_match,
                "tasteMatch": taste_match,
                "finalMode": "weak_recommend",
            }
    return {
        "reply": final_reply,
        "product": None,
        "taste_match": {"protagonist": 0, "mood": 0, "pacing": 0},
        "tasteMatch": {"protagonist": 0, "mood": 0, "pacing": 0},
        "finalMode": final_mode,
    }


# ── 채팅 히스토리 저장/조회 ───────────────────────────


async def save_chat_messages(
    *,
    kc_user_id: str,
    user_content: str | None,
    assistant_result: dict,
    db: AsyncSession,
) -> None:
    """유저 메시지 + 어시스턴트 응답을 DB에 저장."""
    user_id = await recommendation_service._get_user_id_by_kc(kc_user_id, db)
    if not user_id:
        return

    if user_content:
        await db.execute(
            text("""
                INSERT INTO tb_user_ai_chat_message
                    (user_id, role, content)
                VALUES (:user_id, 'user', :content)
            """),
            {"user_id": user_id, "content": user_content},
        )

    reply = assistant_result.get("reply") or ""
    product = assistant_result.get("product")
    taste_match = assistant_result.get("taste_match") or assistant_result.get("tasteMatch")

    product_id = None
    product_snapshot = None
    if isinstance(product, dict) and product.get("productId"):
        product_id = product["productId"]
        product_snapshot = json.dumps(product, ensure_ascii=False)

    taste_match_json = None
    if isinstance(taste_match, dict) and any(v for v in taste_match.values()):
        taste_match_json = json.dumps(taste_match, ensure_ascii=False)

    await db.execute(
        text("""
            INSERT INTO tb_user_ai_chat_message
                (user_id, role, content, product_id, product_snapshot, taste_match)
            VALUES (:user_id, 'assistant', :content, :product_id, :product_snapshot, :taste_match)
        """),
        {
            "user_id": user_id,
            "content": reply,
            "product_id": product_id,
            "product_snapshot": product_snapshot,
            "taste_match": taste_match_json,
        },
    )

    await db.commit()


async def get_chat_history(
    *,
    kc_user_id: str,
    limit: int = 50,
    db: AsyncSession,
) -> list[dict]:
    """유저의 최근 채팅 히스토리 조회."""
    user_id = await recommendation_service._get_user_id_by_kc(kc_user_id, db)
    if not user_id:
        return []

    result = await db.execute(
        text("""
            SELECT id, role, content, product_id, product_snapshot, taste_match, created_date
            FROM tb_user_ai_chat_message
            WHERE user_id = :user_id
            ORDER BY created_date DESC
            LIMIT :limit
        """),
        {"user_id": user_id, "limit": limit},
    )
    rows = await _result_mappings_all(result)

    messages = []
    for row in reversed(rows):
        msg: dict[str, Any] = {
            "id": str(row["id"]),
            "role": row["role"],
            "content": row["content"],
        }
        if row["product_snapshot"]:
            snapshot = row["product_snapshot"]
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)
            msg["product"] = snapshot
        if row["taste_match"]:
            tm = row["taste_match"]
            if isinstance(tm, str):
                tm = json.loads(tm)
            msg["tasteMatch"] = tm
        messages.append(msg)

    return messages


async def clear_chat_history(
    *,
    kc_user_id: str,
    db: AsyncSession,
) -> None:
    """유저의 채팅 히스토리 전체 삭제."""
    user_id = await recommendation_service._get_user_id_by_kc(kc_user_id, db)
    if not user_id:
        return
    await db.execute(
        text("DELETE FROM tb_user_ai_chat_message WHERE user_id = :user_id"),
        {"user_id": user_id},
    )
    await db.commit()
