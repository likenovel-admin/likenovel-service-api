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
MAX_QUERY_CANDIDATE_DETAILS = 3
MAX_QUERY_CANDIDATE_SCAN = 10
MAX_REPLY_SENTENCES = 2
MAX_REPLY_CHARS = 220
MAX_RECOMMENDATION_REPLY_CHARS = 140
MAX_MATCH_TAGS = 5
MAX_CONVERSATION_MEMORY_MESSAGES = 10
MAX_CONVERSATION_MEMORY_LINE_CHARS = 140
MIN_SUGGESTED_ACTIONS = 3
MAX_SUGGESTED_ACTIONS = 4
MAX_EPISODE_PREVIEW_COUNT = 3
MAX_EPISODE_PREVIEW_CHARS = 1200
MAX_STORY_CONTEXT_SAFE_EPISODE_TO = 20
MAX_STORY_CONTEXT_PLOT_POINTS = 2
MAX_STORY_CONTEXT_EPISODE_SUMMARIES = 3
MAX_STORY_CONTEXT_EPISODE_SUMMARY_CHARS = 260
MAX_STORY_CONTEXT_SIGNAL_ROWS = 4
MAX_STORY_CONTEXT_CHARACTERS = 5
MAX_STORY_CONTEXT_RELATIONS = 4
MAX_STORY_CONTEXT_HOOKS = 2
FINAL_RESPONSE_TOOL_NAME = "submit_final_recommendation"
FINAL_RESPONSE_MODES = {"recommend", "weak_recommend", "no_match"}
SUGGESTED_ACTION_SNAPSHOT_KEY = "__suggestedActions"
SUGGESTED_ACTION_INTENTS = {
    "explain_match",
    "explain_entry",
    "explain_attribute",
    "recommend_similar",
}
CURRENT_PRODUCT_EXPLANATION_ACTION_INTENTS = {
    "explain_match",
    "explain_entry",
    "explain_attribute",
}
SUGGESTED_ACTION_DEFAULT_PRIORITIES = {
    "explain_match": 10,
    "explain_entry": 20,
    "explain_attribute": 30,
    "recommend_similar": 40,
}

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
BROAD_METADATA_KEYWORD_COLUMNS = (
    "p.title",
    "p.synopsis_text",
    "pg.keyword_name",
    "sg.keyword_name",
    "uk.keyword_name",
    "m.premise",
    "m.hook",
    "m.episode_summary_text",
    "m.protagonist_desc",
    "m.protagonist_goal_primary",
    "m.taste_tags",
    "m.worldview_tags",
    "m.protagonist_type_tags",
    "m.protagonist_job_tags",
    "m.protagonist_material_tags",
    "m.axis_romance_tags",
    "m.axis_style_tags",
)
BROAD_METADATA_RELEVANCE_COLUMNS = (
    ("p.title", 6),
    ("m.protagonist_job_tags", 6),
    ("m.protagonist_material_tags", 5),
    ("uk.keyword_name", 4),
    ("pg.keyword_name", 3),
    ("sg.keyword_name", 3),
    ("m.taste_tags", 3),
    ("m.worldview_tags", 3),
    ("m.premise", 2),
    ("m.hook", 2),
    ("m.episode_summary_text", 1),
)
BROAD_RECOMMENDATION_KEYWORD_HINTS = (
    "현대판타지",
    "다크 판타지",
    "판타지",
    "무협",
    "로맨스판타지",
    "로판",
    "로맨스",
    "미스터리",
    "공포",
    "아카데미",
    "헌터",
    "아이돌",
    "게임",
    "마법",
    "먼치킨",
    "성장",
    "회귀",
    "빙의",
)
AI_LIBRARIAN_SERVICE_CONTEXT_LINES = (
    "라이크노벨은 회차 단위로 연재되고 유료/무료 회차가 나뉘는 웹소설·웹소챗 서비스다.",
    "답변과 후속질문은 출판 분류어보다 작품/회차/완결/연재중/무료/유료 같은 서비스 언어로 쓴다.",
    "사용자가 초단편/단편/짧은 작품을 말하면 별도 숫자가 없는 한 5화 이하 작품을 우선 의미한다고 해석한다.",
    "사용자가 장편/긴 작품을 말하면 별도 숫자가 없는 한 100화 이상 작품을 의미한다고 해석한다.",
    "후속질문 label/user_message에서는 단편소설/초단편/장편소설 같은 표현을 먼저 만들지 말고 5화 이하 작품, 100화 이상 작품처럼 회차 기준으로 풀어쓴다.",
)
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
                "suggested_actions": {
                    "type": "array",
                    "description": "답변 아래에 보여줄 후속질문. recommend/weak_recommend/no_match 모두 3개 또는 4개를 제출한다. no_match일 때는 실패한 조건을 좁히거나 넓히는 다음 질문으로 만든다. 질문은 답변 근거에 맞춰 짧은 한국어로 쓰되, 단편소설/초단편/장편소설보다 5화 이하 작품/100화 이상 작품 같은 회차 기준 표현을 쓴다.",
                    "minItems": MIN_SUGGESTED_ACTIONS,
                    "maxItems": MAX_SUGGESTED_ACTIONS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "action_id": {"type": "string"},
                            "priority": {
                                "type": "integer",
                                "description": "낮을수록 먼저 노출된다. 기본 순서: 취향 근거 10, 초반 포인트 20, 태그 포인트 30, 유사작 40.",
                            },
                            "label": {"type": "string"},
                            "user_message": {"type": "string"},
                            "intent": {
                                "type": "string",
                                "enum": sorted(SUGGESTED_ACTION_INTENTS),
                            },
                            "topic": {"type": "string"},
                        },
                        "required": ["label", "user_message", "intent"],
                    },
                },
            },
            "required": ["reply", "mode", "product_id", "suggested_actions"],
        },
    },
]
DATA_AGENT_RUNTIME_TOOLS = [
    tool for tool in DATA_AGENT_TOOLS
    if tool["name"] != "get_fact_catalog"
]
NO_MATCH_SUGGESTED_ACTION_TOOL_NAME = "submit_no_match_suggested_actions"
NO_MATCH_SUGGESTED_ACTION_TOOL = {
    "name": NO_MATCH_SUGGESTED_ACTION_TOOL_NAME,
    "description": "추천 카드가 없는 no_match 답변 뒤에 붙일 후속질문만 제출한다. 고정 문구를 쓰지 말고 사용자 질문과 실패 조건을 바탕으로 3개 또는 4개를 만든다. 라이크노벨의 작품은 회차 기반이므로 단편소설/초단편/장편소설 같은 출판 분류어보다 5화 이하 작품/100화 이상 작품 같은 회차 기준 표현을 쓴다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "suggested_actions": {
                "type": "array",
                "description": "사용자가 바로 누를 수 있는 한국어 후속질문. 조건을 넓히거나 좁히는 다음 검색 질문으로 만든다. 새 추천 탐색이면 intent는 recommend_similar를 우선 사용한다. 분량은 단편/장편이 아니라 5화 이하/100화 이상처럼 회차 조건으로 쓴다.",
                "minItems": MIN_SUGGESTED_ACTIONS,
                "maxItems": MAX_SUGGESTED_ACTIONS,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "action_id": {"type": "string"},
                        "priority": {"type": "integer"},
                        "label": {"type": "string"},
                        "user_message": {"type": "string"},
                        "intent": {
                            "type": "string",
                            "enum": sorted(SUGGESTED_ACTION_INTENTS),
                        },
                        "topic": {"type": "string"},
                    },
                    "required": ["label", "user_message", "intent"],
                },
            },
        },
        "required": ["suggested_actions"],
    },
}


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
                "작품 추천 후보는 공개 작품 카드로 보여줄 수 있어야 하므로 tb_product 조회에는 p.open_yn = 'Y', p.author_name IS NOT NULL, TRIM(p.author_name) <> '' 조건을 포함한다.",
                "adult_yn=N이면 tb_product를 조회할 때 반드시 p.ratings_code = 'all' 조건을 포함한다.",
                "tb_product_ai_metadata를 추천 후보 검색에 쓰면 m.analysis_status = 'success' 와 COALESCE(m.exclude_from_recommend_yn, 'N') = 'N' 조건을 포함한다.",
                "premise, hook, episode_summary_text, protagonist_*_tags, worldview_tags, axis_*_tags 는 tb_product_ai_metadata 컬럼이다.",
                "키워드/소재 추천은 title, 장르 키워드, tb_product_user_keyword.keyword_name, premise, hook, episode_summary_text, protagonist_desc, protagonist_goal_primary, taste_tags, worldview_tags, protagonist_type_tags, protagonist_job_tags, protagonist_material_tags, axis_romance_tags, axis_style_tags를 넓게 OR 탐색한다.",
                "reading_rate, writing_count_per_week 는 tb_product_trend_index 컬럼이고 tb_product 컬럼이 아니다.",
                "binge_rate, dropoff_7d, reengage_rate, avg_speed_cpm 은 tb_product_engagement_metrics 컬럼이다.",
                "evaluation_score 는 tb_cms_product_evaluation 컬럼이다.",
                "원본 수치(count_hit/count_bookmark/count_recommend)는 tb_product에 있고, tb_product_count_variance에는 *_indicator만 있다.",
                "회차 수가 필요하면 존재하지 않는 컬럼을 추정하지 말고 tb_product_episode에서 COUNT(*)로 계산한다.",
                "tb_product에는 premise, hook, reading_rate, evaluation_score, episode_total 컬럼이 없다.",
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


def _build_fact_catalog_prompt() -> str:
    return json.dumps(_build_fact_catalog(), ensure_ascii=False, separators=(",", ":"))


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


def _is_new_recommendation_request(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    recommendation_keywords = [
        "추천",
        "찾아줘",
        "골라줘",
        "보여줘",
    ]
    condition_keywords = [
        "완결",
        "판타지",
        "무협",
        "로맨스",
        "현대",
        "초반 진입",
        "조건",
        "회차",
        "연재",
    ]
    return any(keyword in normalized for keyword in recommendation_keywords) and any(
        keyword in normalized for keyword in condition_keywords
    )


def _normalize_status_code_value(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return PRODUCT_STATUS_CODE_ALIASES.get(normalized, normalized)


def _extract_required_status_codes(text: str) -> set[str]:
    normalized = str(text or "").strip().lower()
    required: set[str] = set()
    if "완결" in normalized:
        required.add("end")
    if re.search(r"연재\s*중", normalized):
        required.add("ongoing")
    if "휴재" in normalized:
        required.add("rest")
    return required


def _extract_episode_total_constraint(text: str) -> dict[str, Any] | None:
    raw_text = str(text or "")
    if re.search(r"초\s*단편|단편|짧은\s*(작품|소설|웹소설)", raw_text):
        return {"op": "<=", "value": 5, "source": "short_work_alias"}
    if re.search(r"장편|긴\s*(작품|소설|웹소설)", raw_text):
        return {"op": ">=", "value": 100, "source": "long_work_alias"}

    normalized = _rewrite_episode_length_terms_for_service(text)
    if not normalized:
        return None

    for match in re.finditer(r"(\d{1,4})\s*화\s*(이하|까지|이내|미만|이상|넘게|넘는|초과)", normalized):
        episode_count = _safe_int(match.group(1), 0)
        if episode_count <= 0:
            continue
        operator_word = match.group(2)
        if operator_word in {"이상", "넘게", "넘는", "초과"}:
            return {"op": ">=", "value": episode_count, "source": "explicit"}
        return {"op": "<=", "value": episode_count, "source": "explicit"}

    if any(keyword in normalized for keyword in ["5화 이하 작품", "짧은 작품", "짧은 웹소설"]):
        return {"op": "<=", "value": 5, "source": "short_work_alias"}
    if any(keyword in normalized for keyword in ["100화 이상 작품", "긴 작품", "긴 웹소설"]):
        return {"op": ">=", "value": 100, "source": "long_work_alias"}
    return None


def _extract_price_type_constraints(text: str) -> list[str]:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return []
    if re.search(r"무료\s*(만|작품만|로만|위주|작품)", normalized):
        return ["free"]
    if re.search(r"유료\s*(만|작품만|로만|위주|작품)", normalized) and "유료도" not in normalized:
        return ["paid"]
    return []


def _build_exploration_state(messages: list[dict] | None, context: dict | None = None) -> dict[str, Any]:
    state: dict[str, Any] = {
        "hard": {},
        "soft": {"keywords": []},
        "weak": {},
        "negative": {},
    }
    soft_keywords: list[str] = []

    for message in messages or []:
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        raw_text = str(message.get("content") or "").strip()
        if not raw_text:
            continue
        normalized_text = _rewrite_episode_length_terms_for_service(raw_text)

        if any(keyword in raw_text for keyword in ["회차수는 풀어", "회차 수는 풀어", "분량은 풀어", "몇 화인지는 상관"]):
            state["hard"].pop("episode_total", None)
        episode_constraint = _extract_episode_total_constraint(raw_text)
        if episode_constraint:
            state["hard"]["episode_total"] = episode_constraint

        if any(keyword in raw_text for keyword in ["상태는 상관", "연재작도", "연재중도 포함", "완결 아니어도"]):
            state["hard"].pop("status_codes", None)
            state["negative"].pop("status_codes", None)
        status_codes = _extract_required_status_codes(raw_text)
        if status_codes:
            state["hard"]["status_codes"] = sorted(status_codes)
        if any(keyword in raw_text for keyword in ["비완결 싫", "연재중 싫", "완결만"]):
            state["negative"]["status_codes"] = ["ongoing"]
            state["hard"]["status_codes"] = ["end"]

        price_types = _extract_price_type_constraints(raw_text)
        if price_types:
            state["hard"]["price_types"] = price_types

        if any(keyword in raw_text for keyword in ["초반 진입", "진입 쉬", "시작하기 쉬"]):
            state["weak"]["entry_easy"] = True
        if any(keyword in raw_text for keyword in ["가볍게", "가벼운", "부담없이", "부담 없이"]):
            state["weak"]["light_read"] = True
        if "몰입" in raw_text:
            state["weak"]["immersive"] = True

        for keyword in _extract_broad_recommendation_keywords(normalized_text):
            if keyword not in soft_keywords:
                soft_keywords.append(keyword)

    if soft_keywords:
        state["soft"]["keywords"] = soft_keywords[:8]
    else:
        state.pop("soft", None)
    if not state.get("hard"):
        state.pop("hard", None)
    if not state.get("weak"):
        state.pop("weak", None)
    if not state.get("negative"):
        state.pop("negative", None)

    last_action = {
        "source_action_id": _compact_text((context or {}).get("source_action_id") or (context or {}).get("sourceActionId"), 80),
        "source_action_intent": _compact_text((context or {}).get("source_action_intent") or (context or {}).get("sourceActionIntent"), 40),
    }
    if last_action["source_action_id"] or last_action["source_action_intent"]:
        state["last_action"] = {
            key: value for key, value in last_action.items() if value
        }
    return state


def _status_constraint_label(status_codes: set[str]) -> str:
    labels = {"end": "완결", "ongoing": "연재중", "rest": "휴재"}
    return "/".join(labels.get(code, code) for code in sorted(status_codes)) or "상태"


def _candidate_status_code(candidate: dict[str, Any] | None) -> str:
    if not isinstance(candidate, dict):
        return ""
    return _normalize_status_code_value(candidate.get("ongoingState") or candidate.get("status_code"))


def _candidate_matches_required_status(candidate: dict[str, Any] | None, required_status_codes: set[str]) -> bool:
    if not required_status_codes:
        return True
    return _candidate_status_code(candidate) in required_status_codes


def _candidate_episode_count(candidate: dict[str, Any] | None) -> int:
    if not isinstance(candidate, dict):
        return 0
    return _safe_int(
        candidate.get("episodeCount")
        or candidate.get("episode_count")
        or candidate.get("episode_total"),
        0,
    )


def _candidate_price_type(candidate: dict[str, Any] | None) -> str:
    if not isinstance(candidate, dict):
        return ""
    return str(candidate.get("priceType") or candidate.get("price_type") or "").strip().lower()


def _candidate_matches_episode_constraint(candidate: dict[str, Any] | None, episode_rule: dict[str, Any] | None) -> bool:
    if not episode_rule:
        return True
    episode_count = _candidate_episode_count(candidate)
    if episode_count <= 0:
        return False
    value = _safe_int(episode_rule.get("value"), 0)
    if value <= 0:
        return True
    op = str(episode_rule.get("op") or "").strip()
    if op == ">=":
        return episode_count >= value
    return episode_count <= value


def _product_hard_constraint_violations(product: dict[str, Any] | None, exploration_state: dict | None) -> list[str]:
    if not isinstance(product, dict):
        return []
    hard = (exploration_state or {}).get("hard") or {}
    violations: list[str] = []
    status_codes = set(str(value) for value in hard.get("status_codes") or [] if str(value or "").strip())
    if status_codes and not _candidate_matches_required_status(product, status_codes):
        violations.append("status")
    episode_rule = hard.get("episode_total") if isinstance(hard.get("episode_total"), dict) else None
    if episode_rule and not _candidate_matches_episode_constraint(product, episode_rule):
        violations.append("episode_total")
    price_types = set(str(value).strip().lower() for value in hard.get("price_types") or [] if str(value or "").strip())
    if price_types and _candidate_price_type(product) not in price_types:
        violations.append("price_type")
    return violations


def _candidate_matches_hard_constraints(candidate: dict[str, Any] | None, exploration_state: dict | None) -> bool:
    return not _product_hard_constraint_violations(candidate, exploration_state)


def _filter_candidate_rows_by_hard_constraints(
    rows: list[dict[str, Any]],
    exploration_state: dict | None,
) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if isinstance(row, dict) and _candidate_matches_hard_constraints(row, exploration_state)
    ]


def _hard_constraint_violation_label(violations: list[str]) -> str:
    labels = {
        "status": "작품 상태",
        "episode_total": "회차 수",
        "price_type": "무료/유료",
    }
    return ", ".join(labels.get(value, value) for value in violations) or "조건"


def _has_non_status_hard_constraints(exploration_state: dict | None) -> bool:
    hard = (exploration_state or {}).get("hard") or {}
    return bool(hard.get("episode_total") or hard.get("price_types"))


def _filter_candidate_rows_by_required_status(
    rows: list[dict[str, Any]],
    required_status_codes: set[str],
) -> list[dict[str, Any]]:
    if not required_status_codes:
        return rows
    return [
        row for row in rows
        if isinstance(row, dict) and _candidate_matches_required_status(row, required_status_codes)
    ]


def _merge_candidate_rows(
    existing_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = list(existing_rows)
    seen_ids = {
        _safe_int(row.get("product_id"), 0)
        for row in merged
        if isinstance(row, dict) and _safe_int(row.get("product_id"), 0) > 0
    }
    for row in new_rows:
        if not isinstance(row, dict):
            continue
        product_id = _safe_int(row.get("product_id"), 0)
        if product_id <= 0 or product_id in seen_ids:
            continue
        merged.append(row)
        seen_ids.add(product_id)
    return merged


def _extract_broad_recommendation_keywords(text: str, query_terms: list[str] | None = None) -> list[str]:
    normalized = str(text or "").strip()
    keywords: list[str] = []
    for keyword in BROAD_RECOMMENDATION_KEYWORD_HINTS:
        if keyword in normalized and keyword not in keywords:
            keywords.append(keyword)
    for term in query_terms or []:
        compact_term = _compact_text(term, 30)
        if not compact_term or compact_term in keywords:
            continue
        if compact_term in {"완결", "연재중", "휴재", "추천", "작품"}:
            continue
        keywords.append(compact_term)
        if len(keywords) >= 5:
            break
    return keywords[:5]


def _resolve_conversation_product_id(page_context: dict, session_state: dict) -> int:
    active_focus_product_id = _safe_int(page_context.get("active_focus_product_id"), 0)
    if active_focus_product_id > 0:
        return active_focus_product_id
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
    if current_product_id <= 0:
        return False
    latest_query = _latest_user_query(messages)
    if not latest_query or _is_similar_request(latest_query) or _is_new_recommendation_request(latest_query):
        return False
    current_title = str(page_context.get("current_product_title") or "").strip()
    source_action_intent = str(page_context.get("source_action_intent") or "").strip()
    is_current_product_explanation_action = source_action_intent in CURRENT_PRODUCT_EXPLANATION_ACTION_INTENTS
    has_recent_current_product_reply = any(
        str(message.get("role") or "").strip().lower() == "assistant"
        and _safe_int(message.get("product_id"), 0) == current_product_id
        for message in messages or []
    )
    is_contextual_current_product_followup = has_recent_current_product_reply and any(
        keyword in latest_query
        for keyword in [
            "그럼",
            "그러면",
            "주인공",
            "인물",
            "관계",
            "초반",
            "포인트",
            "분위기",
            "세계관",
            "전개",
            "로맨스",
            "히로인",
            "설정",
            "매력",
            "읽을",
            "판단",
            "3줄",
            "한줄",
            "한 줄",
            "장단점",
            "표로",
            "짧게",
        ]
    )
    has_focus_or_context = bool(page_context.get("focus_product_card")) or is_contextual_current_product_followup
    if not has_focus_or_context:
        return False
    has_current_anchor = any(
        keyword in latest_query
        for keyword in ["이 작품", "이거", "현재 작품", "보고 있는 작품"]
    ) or bool(current_title and current_title in latest_query) or is_current_product_explanation_action or is_contextual_current_product_followup
    has_overview_intent = any(
        keyword in latest_query
        for keyword in [
            "어떤 작품",
            "무슨 작품",
            "알려줘",
            "소개",
            "설명",
            "줄거리",
            "내용",
            "키워드",
            "장르",
            "읽을",
            "판단",
            "3줄",
            "한줄",
            "한 줄",
            "장단점",
            "표로",
            "짧게",
        ]
    ) or is_current_product_explanation_action or is_contextual_current_product_followup
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


def _build_conversation_memory(messages: list[dict] | None) -> list[str]:
    memory_lines: list[str] = []
    for message in messages or []:
        role = str(message.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = _compact_text(message.get("content"), MAX_CONVERSATION_MEMORY_LINE_CHARS)
        if not content:
            continue
        role_label = "사용자" if role == "user" else "AI사서"
        product_id = _safe_int(message.get("product_id"), 0)
        product_suffix = f"[작품 ID {product_id}]" if role == "assistant" and product_id > 0 else ""
        memory_lines.append(f"{role_label}{product_suffix}: {content}")
    return memory_lines[-MAX_CONVERSATION_MEMORY_MESSAGES:]


def _build_named_in_clause(prefix: str, values: list[int]) -> tuple[str, dict[str, int]]:
    params: dict[str, int] = {}
    placeholders: list[str] = []
    for index, value in enumerate(values):
        param_name = f"{prefix}_{index}"
        placeholders.append(f":{param_name}")
        params[param_name] = int(value)
    return ", ".join(placeholders), params


def _compact_story_context(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    compact: dict[str, Any] = {}
    if value.get("availability"):
        compact["availability"] = _compact_text(value.get("availability"), 20)
    if value.get("scope_episode_to") is not None:
        compact["scope_episode_to"] = _safe_int(value.get("scope_episode_to"), 0)

    plot_points = [
        _compact_text(item, MAX_STORY_CONTEXT_EPISODE_SUMMARY_CHARS)
        for item in value.get("plot_points") or []
        if _compact_text(item, MAX_STORY_CONTEXT_EPISODE_SUMMARY_CHARS)
    ][:MAX_STORY_CONTEXT_PLOT_POINTS]
    if plot_points:
        compact["plot_points"] = plot_points

    episode_summaries: list[dict[str, Any]] = []
    for item in value.get("episode_summaries") or []:
        if not isinstance(item, dict):
            continue
        summary = _compact_text(item.get("summary"), MAX_STORY_CONTEXT_EPISODE_SUMMARY_CHARS)
        if not summary:
            continue
        episode_summaries.append(
            {
                "episode_from": _safe_int(item.get("episode_from"), 0),
                "episode_to": _safe_int(item.get("episode_to"), 0),
                "summary": summary,
            }
        )
        if len(episode_summaries) >= MAX_STORY_CONTEXT_EPISODE_SUMMARIES:
            break
    if episode_summaries:
        compact["episode_summaries"] = episode_summaries

    characters: list[dict[str, Any]] = []
    for item in value.get("characters") or []:
        if not isinstance(item, dict):
            continue
        display_name = _compact_text(item.get("display_name"), 40)
        if not display_name:
            continue
        characters.append(
            {
                "display_name": display_name,
                "is_protagonist": bool(item.get("is_protagonist")),
                "entity_kind": _compact_text(item.get("entity_kind"), 20),
                "action_tags": _load_json_list(item.get("action_tags"))[:3],
                "affect_tags": _load_json_list(item.get("affect_tags"))[:3],
            }
        )
        if len(characters) >= MAX_STORY_CONTEXT_CHARACTERS:
            break
    if characters:
        compact["characters"] = characters

    relations: list[dict[str, Any]] = []
    for item in value.get("relations") or []:
        if not isinstance(item, dict):
            continue
        source_name = _compact_text(item.get("source_display_name"), 40)
        target_name = _compact_text(item.get("target_display_name"), 40)
        if not source_name or not target_name:
            continue
        relations.append(
            {
                "source": source_name,
                "target": target_name,
                "tags": _load_json_list(item.get("tags"))[:3],
            }
        )
        if len(relations) >= MAX_STORY_CONTEXT_RELATIONS:
            break
    if relations:
        compact["relations"] = relations

    hooks = [
        _compact_text(hook, 90)
        for hook in value.get("opening_hooks") or []
        if _compact_text(hook, 90)
    ][:MAX_STORY_CONTEXT_HOOKS]
    if hooks:
        compact["opening_hooks"] = hooks

    if value.get("ready_episode_count") is not None:
        compact["ready_episode_count"] = _safe_int(value.get("ready_episode_count"), 0)
    if value.get("total_episode_count") is not None:
        compact["total_episode_count"] = _safe_int(value.get("total_episode_count"), 0)

    return compact or None


def _extract_story_context_json_object(text_value: str) -> dict[str, Any] | None:
    raw_text = str(text_value or "").strip()
    if not raw_text:
        return None
    try:
        parsed = json.loads(raw_text)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        pass

    match = re.search(r"\{[\s\S]*\}", raw_text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _add_count(counter: dict[str, int], value: Any) -> None:
    text_value = _compact_text(value, 40)
    if not text_value:
        return
    counter[text_value] = int(counter.get(text_value) or 0) + 1


def _top_counted(counter: dict[str, int], limit: int) -> list[str]:
    return [
        key
        for key, _ in sorted(
            counter.items(),
            key=lambda item: (-int(item[1] or 0), item[0]),
        )[:limit]
    ]


def _aggregate_ai_librarian_signal_rows(signal_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    character_map: dict[str, dict[str, Any]] = {}
    relation_map: dict[str, dict[str, Any]] = {}
    hooks: list[str] = []
    seen_hooks: set[str] = set()

    for row in signal_rows:
        payload = _extract_story_context_json_object(str(row.get("summaryText") or "")) or {}
        for hook in payload.get("cliffhanger_hooks") or []:
            hook_text = _compact_text(hook, 90)
            if not hook_text or hook_text in seen_hooks:
                continue
            seen_hooks.add(hook_text)
            hooks.append(hook_text)
            if len(hooks) >= MAX_STORY_CONTEXT_HOOKS:
                break

        for item in payload.get("mentioned_characters") or []:
            if not isinstance(item, dict):
                continue
            display_name = _compact_text(item.get("display_name"), 40)
            if not display_name:
                continue
            character = character_map.setdefault(
                display_name,
                {
                    "display_name": display_name,
                    "is_protagonist": False,
                    "entity_kind": _compact_text(item.get("entity_kind") or "person", 20),
                    "scene_rank": 0,
                    "mention_count": 0,
                    "action_tag_counts": {},
                    "affect_tag_counts": {},
                },
            )
            character["is_protagonist"] = bool(character.get("is_protagonist")) or bool(item.get("is_protagonist"))
            character["mention_count"] = int(character.get("mention_count") or 0) + 1
            scene_weight = str(item.get("scene_weight") or "").strip().lower()
            scene_rank = 3 if scene_weight == "high" else 2 if scene_weight == "medium" else 1
            character["scene_rank"] = max(int(character.get("scene_rank") or 0), scene_rank)
            for tag in item.get("action_tags") or []:
                _add_count(character["action_tag_counts"], tag)
            for tag in item.get("affect_tags") or []:
                _add_count(character["affect_tag_counts"], tag)

            for edge in item.get("relation_edges") or []:
                if not isinstance(edge, dict):
                    continue
                target_name = _compact_text(edge.get("target_label"), 40)
                relation_tag = _compact_text(edge.get("relation_tag"), 30)
                direction = str(edge.get("direction") or "to_target").strip().lower()
                if not target_name or not relation_tag or target_name == display_name:
                    continue
                if direction == "from_target":
                    source_name, dest_name = target_name, display_name
                else:
                    source_name, dest_name = display_name, target_name
                relation_key = f"{source_name}=>{dest_name}"
                relation = relation_map.setdefault(
                    relation_key,
                    {
                        "source_display_name": source_name,
                        "target_display_name": dest_name,
                        "mention_count": 0,
                        "tag_counts": {},
                    },
                )
                relation["mention_count"] = int(relation.get("mention_count") or 0) + 1
                _add_count(relation["tag_counts"], relation_tag)

    characters = [
        {
            "display_name": str(item.get("display_name") or ""),
            "is_protagonist": bool(item.get("is_protagonist")),
            "entity_kind": str(item.get("entity_kind") or "person"),
            "action_tags": _top_counted(item.get("action_tag_counts") or {}, 3),
            "affect_tags": _top_counted(item.get("affect_tag_counts") or {}, 3),
            "scene_rank": int(item.get("scene_rank") or 0),
            "mention_count": int(item.get("mention_count") or 0),
        }
        for item in character_map.values()
    ]
    characters.sort(
        key=lambda item: (
            -int(bool(item.get("is_protagonist"))),
            -int(item.get("scene_rank") or 0),
            -int(item.get("mention_count") or 0),
            str(item.get("display_name") or ""),
        )
    )

    relations = [
        {
            "source_display_name": str(item.get("source_display_name") or ""),
            "target_display_name": str(item.get("target_display_name") or ""),
            "tags": _top_counted(item.get("tag_counts") or {}, 3),
            "mention_count": int(item.get("mention_count") or 0),
        }
        for item in relation_map.values()
    ]
    relations.sort(
        key=lambda item: (
            -int(item.get("mention_count") or 0),
            str(item.get("source_display_name") or ""),
            str(item.get("target_display_name") or ""),
        )
    )
    return characters[:MAX_STORY_CONTEXT_CHARACTERS], relations[:MAX_STORY_CONTEXT_RELATIONS], hooks


def _build_story_context_from_rows(
    *,
    status_row: dict[str, Any] | None,
    summary_rows: list[dict[str, Any]],
    safe_episode_to: int,
) -> dict[str, Any] | None:
    range_summaries: list[str] = []
    episode_summaries: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []

    for row in summary_rows:
        summary_type = str(row.get("summaryType") or row.get("summary_type") or "").strip()
        summary_text = str(row.get("summaryText") or row.get("summary_text") or "").strip()
        if not summary_text:
            continue
        if summary_type == "range_summary" and len(range_summaries) < MAX_STORY_CONTEXT_PLOT_POINTS:
            range_summaries.append(summary_text)
            continue
        if summary_type == "episode_summary" and len(episode_summaries) < MAX_STORY_CONTEXT_EPISODE_SUMMARIES:
            episode_summaries.append(
                {
                    "episode_from": _safe_int(row.get("episodeFrom") or row.get("episode_from"), 0),
                    "episode_to": _safe_int(row.get("episodeTo") or row.get("episode_to"), 0),
                    "summary": summary_text,
                }
            )
            continue
        if summary_type == "episode_character_signals" and len(signal_rows) < MAX_STORY_CONTEXT_SIGNAL_ROWS:
            signal_rows.append(
                {
                    "episodeFrom": _safe_int(row.get("episodeFrom") or row.get("episode_from"), 0),
                    "summaryText": summary_text,
                }
            )

    plot_points = range_summaries[:MAX_STORY_CONTEXT_PLOT_POINTS]
    if not plot_points:
        plot_points = [item["summary"] for item in episode_summaries[:MAX_STORY_CONTEXT_PLOT_POINTS]]

    characters, relations, hooks = _aggregate_ai_librarian_signal_rows(signal_rows)
    if not plot_points and not episode_summaries and not characters and not relations and not hooks:
        return None

    raw_context: dict[str, Any] = {
        "availability": "ready",
        "scope_episode_to": safe_episode_to,
        "plot_points": plot_points,
        "episode_summaries": episode_summaries,
        "characters": characters,
        "relations": relations,
        "opening_hooks": hooks,
    }
    if status_row:
        raw_context["ready_episode_count"] = _safe_int(
            status_row.get("readyEpisodeCount") or status_row.get("ready_episode_count"),
            0,
        )
        raw_context["total_episode_count"] = _safe_int(
            status_row.get("totalEpisodeCount") or status_row.get("total_episode_count"),
            0,
        )
    return _compact_story_context(raw_context)


async def _load_story_context_summaries(
    db: AsyncSession,
    *,
    product_ids: list[int],
) -> dict[int, dict[str, Any]]:
    normalized_ids: list[int] = []
    for value in product_ids:
        product_id = _safe_int(value, 0)
        if product_id <= 0 or product_id in normalized_ids:
            continue
        normalized_ids.append(product_id)
    if not normalized_ids:
        return {}

    placeholders, params = _build_named_in_clause("product_id", normalized_ids)
    try:
        status_result = await db.execute(
            text(
                f"""
                SELECT
                    product_id AS productId,
                    context_status AS contextStatus,
                    ready_episode_count AS readyEpisodeCount,
                    total_episode_count AS totalEpisodeCount
                FROM tb_story_agent_context_product
                WHERE product_id IN ({placeholders})
                  AND context_status = 'ready'
                """
            ),
            params,
        )
        status_rows = [dict(row) for row in await _result_mappings_all(status_result)]
        ready_status_by_id = {
            _safe_int(row.get("productId"), 0): row
            for row in status_rows
            if _safe_int(row.get("productId"), 0) > 0
        }
        ready_ids = [product_id for product_id in normalized_ids if product_id in ready_status_by_id]
        if not ready_ids:
            return {}

        ready_placeholders, ready_params = _build_named_in_clause("ready_product_id", ready_ids)
        episode_result = await db.execute(
            text(
                f"""
                SELECT
                    product_id AS productId,
                    episode_no AS episodeNo
                FROM tb_product_episode
                WHERE product_id IN ({ready_placeholders})
                  AND use_yn = 'Y'
                  AND open_yn = 'Y'
                  AND price_type = 'free'
                ORDER BY product_id ASC, episode_no ASC
                """
            ),
            ready_params,
        )
        free_episode_numbers_by_id: dict[int, list[int]] = {product_id: [] for product_id in ready_ids}
        for row in await _result_mappings_all(episode_result):
            row_dict = dict(row)
            product_id = _safe_int(row_dict.get("productId"), 0)
            episode_no = _safe_int(row_dict.get("episodeNo"), 0)
            if product_id in free_episode_numbers_by_id and episode_no > 0:
                free_episode_numbers_by_id[product_id].append(episode_no)

        safe_episode_to_by_id: dict[int, int] = {}
        for product_id, episode_numbers in free_episode_numbers_by_id.items():
            expected_episode_no = 1
            safe_episode_to = 0
            for episode_no in sorted(set(episode_numbers)):
                if episode_no == expected_episode_no:
                    safe_episode_to = episode_no
                    expected_episode_no += 1
                    continue
                if episode_no > expected_episode_no:
                    break
            safe_episode_to = min(safe_episode_to, MAX_STORY_CONTEXT_SAFE_EPISODE_TO)
            if safe_episode_to > 0:
                safe_episode_to_by_id[product_id] = safe_episode_to
        if not safe_episode_to_by_id:
            return {}

        scope_parts: list[str] = []
        scope_params: dict[str, int] = {}
        for index, (product_id, safe_episode_to) in enumerate(safe_episode_to_by_id.items()):
            product_param = f"scope_product_id_{index}"
            episode_param = f"scope_episode_to_{index}"
            scope_parts.append(f"SELECT :{product_param} AS product_id, :{episode_param} AS safe_episode_to")
            scope_params[product_param] = product_id
            scope_params[episode_param] = safe_episode_to
        safe_scope_sql = "\nUNION ALL\n".join(scope_parts)
        summary_result = await db.execute(
            text(
                f"""
                WITH safe_scope AS (
                    {safe_scope_sql}
                )
                SELECT *
                FROM (
                    SELECT
                        s.product_id AS productId,
                        s.summary_type AS summaryType,
                        s.episode_from AS episodeFrom,
                        s.episode_to AS episodeTo,
                        s.summary_text AS summaryText,
                        ROW_NUMBER() OVER (
                            PARTITION BY s.product_id, s.summary_type
                            ORDER BY COALESCE(s.episode_to, 0) DESC, s.summary_id DESC
                        ) AS typeRank,
                        ss.safe_episode_to AS safeEpisodeTo
                    FROM tb_story_agent_context_summary s
                    INNER JOIN safe_scope ss
                      ON ss.product_id = s.product_id
                    WHERE s.is_active = 'Y'
                      AND COALESCE(s.episode_to, 0) > 0
                      AND s.episode_to <= ss.safe_episode_to
                      AND summary_type IN (
                          'range_summary',
                          'episode_summary',
                          'episode_character_signals'
                      )
                ) ranked
                WHERE
                    (summaryType = 'range_summary' AND typeRank <= :range_summary_limit)
                    OR (summaryType = 'episode_summary' AND typeRank <= :episode_summary_limit)
                    OR (summaryType = 'episode_character_signals' AND typeRank <= :signal_row_limit)
                ORDER BY
                    productId ASC,
                    CASE summaryType
                        WHEN 'range_summary' THEN 1
                        WHEN 'episode_summary' THEN 2
                        WHEN 'episode_character_signals' THEN 3
                        ELSE 4
                    END ASC,
                    COALESCE(episodeTo, 0) DESC
                """
            ),
            {
                **scope_params,
                "range_summary_limit": MAX_STORY_CONTEXT_PLOT_POINTS,
                "episode_summary_limit": MAX_STORY_CONTEXT_EPISODE_SUMMARIES,
                "signal_row_limit": MAX_STORY_CONTEXT_SIGNAL_ROWS,
            },
        )
        grouped_rows: dict[int, list[dict[str, Any]]] = {product_id: [] for product_id in ready_ids}
        for row in await _result_mappings_all(summary_result):
            row_dict = dict(row)
            product_id = _safe_int(row_dict.get("productId"), 0)
            if product_id in grouped_rows:
                grouped_rows[product_id].append(row_dict)

        contexts: dict[int, dict[str, Any]] = {}
        for product_id in ready_ids:
            context = _build_story_context_from_rows(
                status_row=ready_status_by_id.get(product_id),
                summary_rows=grouped_rows.get(product_id) or [],
                safe_episode_to=safe_episode_to_by_id.get(product_id, 0),
            )
            if context:
                contexts[product_id] = context
        return contexts
    except SQLAlchemyError as exc:
        logger.warning("[ai_chat] story context lookup failed product_ids=%s: %s", normalized_ids, exc)
        return {}


async def _load_story_context_summary(
    db: AsyncSession,
    *,
    product_id: int,
) -> dict[str, Any] | None:
    contexts = await _load_story_context_summaries(db, product_ids=[product_id])
    return contexts.get(_safe_int(product_id, 0))


def _normalize_visible_tag(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _append_unique_tag(tags: list[str], seen: set[str], value: Any) -> None:
    tag = _normalize_visible_tag(value)
    if not tag or tag in seen:
        return
    seen.add(tag)
    tags.append(tag)


def _extract_recommendation_query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for raw_term in re.findall(r"[0-9A-Za-z가-힣]{2,}", str(query or "")):
        term = raw_term.strip()
        candidates = [term]
        if len(term) > 2 and term.endswith("물"):
            candidates.append(term[:-1])
        for candidate in candidates:
            if candidate and candidate not in terms:
                terms.append(candidate)
        if len(terms) >= 8:
            break
    return terms


def _tag_matches_query_terms(tag: str, query_terms: list[str]) -> bool:
    if not query_terms:
        return False
    normalized_tag = _normalize_visible_tag(tag)
    if not normalized_tag:
        return False
    return any(term in normalized_tag or normalized_tag in term for term in query_terms)


def _build_match_tags(product_info: dict[str, Any], query_terms: list[str] | None = None) -> list[str]:
    query_term_list = query_terms or []
    source_groups = [
        _load_json_list(product_info.get("protagonist_job_tags")),
        _load_json_list(product_info.get("protagonist_material_tags")),
        _load_json_list(product_info.get("protagonist_type_tags")),
        _load_json_list(product_info.get("worldview_tags")),
        _load_json_list(product_info.get("taste_tags")),
        _load_json_list(product_info.get("axis_style_tags")),
        _load_json_list(product_info.get("axis_romance_tags")),
        [product_info.get("primary_genre"), product_info.get("sub_genre")],
    ]
    tags: list[str] = []
    seen: set[str] = set()

    for group in source_groups:
        for tag in group:
            if _tag_matches_query_terms(tag, query_term_list):
                _append_unique_tag(tags, seen, tag)
                if len(tags) >= MAX_MATCH_TAGS:
                    return tags

    for group in source_groups:
        for tag in group:
            _append_unique_tag(tags, seen, tag)
            if len(tags) >= MAX_MATCH_TAGS:
                return tags
    return tags


def _product_visible_tags(product: dict | None) -> list[str]:
    if not isinstance(product, dict):
        return []
    source_groups = [
        product.get("matchTags") or [],
        product.get("protagonistJobTags") or [],
        product.get("protagonistMaterialTags") or [],
        product.get("protagonistTypeTags") or [],
        product.get("worldviewTags") or [],
        product.get("tasteTags") or [],
        product.get("axisStyleTags") or [],
        product.get("axisRomanceTags") or [],
        [product.get("primaryGenre"), product.get("subGenre")],
    ]
    tags: list[str] = []
    seen: set[str] = set()
    for group in source_groups:
        for tag in group:
            _append_unique_tag(tags, seen, tag)
    return tags


def _fallback_suggested_actions(product: dict) -> list[dict[str, Any]]:
    tags = _product_visible_tags(product)
    topic = tags[0] if tags else ""
    topic_label = f"#{topic} 포인트는?" if topic else "추천 근거가 뭐예요?"
    return [
        {
            "id": "explain_match",
            "actionId": "explain_match",
            "label": "왜 제 취향에 맞나요?",
            "userMessage": "왜 제 취향에 맞나요?",
            "intent": "explain_match",
            "priority": SUGGESTED_ACTION_DEFAULT_PRIORITIES["explain_match"],
        },
        {
            "id": "explain_entry",
            "actionId": "explain_entry",
            "label": "초반 진입 포인트는?",
            "userMessage": "초반 진입 포인트는?",
            "intent": "explain_entry",
            "priority": SUGGESTED_ACTION_DEFAULT_PRIORITIES["explain_entry"],
        },
        {
            "id": "explain_attribute",
            "actionId": "explain_attribute",
            "label": topic_label,
            "userMessage": topic_label,
            "intent": "explain_attribute",
            "priority": SUGGESTED_ACTION_DEFAULT_PRIORITIES["explain_attribute"],
            **({"topic": topic} if topic else {}),
        },
        {
            "id": "recommend_similar",
            "actionId": "recommend_similar",
            "label": "비슷한 작품도 볼래요",
            "userMessage": "비슷한 작품도 볼래요",
            "intent": "recommend_similar",
            "priority": SUGGESTED_ACTION_DEFAULT_PRIORITIES["recommend_similar"],
        },
    ]


def _infer_suggested_action_intent_from_query(query: str) -> str | None:
    text = str(query or "").strip()
    if not text:
        return None
    if _is_similar_request(text):
        return "recommend_similar"
    if any(keyword in text for keyword in ["초반", "진입", "전개", "시작"]):
        return "explain_entry"
    if any(keyword in text for keyword in ["취향", "맞나", "맞나요", "근거", "왜"]):
        return "explain_match"
    if "포인트" in text or "#" in text:
        return "explain_attribute"
    return None


def _blocked_suggested_action_intents(page_context: dict | None, latest_query: str) -> set[str]:
    blocked: set[str] = set()
    source_action_intent = str((page_context or {}).get("source_action_intent") or "").strip()
    if source_action_intent in SUGGESTED_ACTION_INTENTS:
        blocked.add(source_action_intent)
    query_intent = _infer_suggested_action_intent_from_query(latest_query)
    if query_intent:
        blocked.add(query_intent)
    return blocked


def _build_current_product_suggested_actions(
    *,
    product: dict | None,
    latest_query: str,
) -> list[dict[str, Any]]:
    if not isinstance(product, dict):
        return []

    query = str(latest_query or "")
    tags = _product_visible_tags(product)
    primary_tag = tags[0] if tags else ""
    secondary_tag = tags[1] if len(tags) > 1 else ""

    def action(
        intent: str,
        label: str,
        user_message: str | None = None,
        topic: str = "",
    ) -> dict[str, Any]:
        label_key = re.sub(r"[^0-9A-Za-z가-힣]+", "_", label).strip("_")[:24] or intent
        action_id = f"current_product_{intent}_{label_key}"
        payload = {
            "id": action_id,
            "actionId": action_id,
            "label": label,
            "userMessage": user_message or label,
            "intent": intent,
            "priority": SUGGESTED_ACTION_DEFAULT_PRIORITIES[intent],
        }
        if topic:
            payload["topic"] = topic
        return payload

    actions: list[dict[str, Any]] = []

    if any(keyword in query for keyword in ["주인공", "인물", "캐릭터"]):
        actions.extend(
            [
                action("explain_match", "주인공이 취향에 맞는 이유는?", "주인공이 왜 제 취향에 맞는지 더 알려줘"),
                action("explain_entry", "초반에 주인공은 어때요?", "초반에 주인공이 어떻게 움직이는지 알려줘"),
                action("explain_attribute", "주인공 매력은?", "주인공의 매력을 더 알려줘"),
                action("recommend_similar", "비슷한 주인공 작품도 볼래요", "비슷한 주인공이 나오는 작품도 보여줘"),
            ]
        )
    elif any(keyword in query for keyword in ["세계관", "설정", "배경"]):
        actions.extend(
            [
                action("explain_match", "세계관이 취향에 맞는 이유는?", "세계관이 왜 제 취향에 맞는지 알려줘"),
                action("explain_entry", "초반 세계관 진입은 쉬워요?", "초반에 세계관을 따라가기 쉬운지 알려줘"),
                action("explain_attribute", "설정 포인트는?", "설정 포인트를 더 알려줘", primary_tag),
                action("recommend_similar", "비슷한 세계관도 볼래요", "비슷한 세계관의 작품도 보여줘"),
            ]
        )
    elif any(keyword in query for keyword in ["초반", "진입", "전개", "시작"]):
        actions.extend(
            [
                action("explain_match", "초반부가 취향에 맞는 이유는?", "초반부가 왜 제 취향에 맞는지 알려줘"),
                action("explain_entry", "전개 속도는 어때요?", "전개 속도가 어떤지 알려줘"),
                action("explain_attribute", "초반 관전 포인트는?", "초반 관전 포인트를 더 알려줘", primary_tag),
                action("recommend_similar", "진입 쉬운 작품도 볼래요", "초반 진입이 쉬운 비슷한 작품도 보여줘"),
            ]
        )
    else:
        actions.extend(
            [
                action("explain_match", "왜 이어볼 만해요?", "왜 이 작품을 이어볼 만한지 알려줘"),
                action("explain_entry", "초반 전개는 어떤가요?", "초반 전개가 어떤지 알려줘"),
                action(
                    "explain_attribute",
                    f"#{primary_tag} 포인트는?" if primary_tag else "작품 매력은?",
                    f"{primary_tag} 포인트를 알려줘" if primary_tag else "작품 매력을 알려줘",
                    primary_tag,
                ),
                action("recommend_similar", "비슷한 작품도 볼래요", "비슷한 작품도 보여줘"),
            ]
        )

    if secondary_tag and all(item.get("topic") != secondary_tag for item in actions):
        actions.append(
            action(
                "explain_attribute",
                f"#{secondary_tag} 포인트는?",
                f"{secondary_tag} 포인트를 알려줘",
                secondary_tag,
            )
        )

    return actions


def _normalize_suggested_actions(
    product: dict | None,
    raw_actions: Any,
    *,
    blocked_intents: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(product, dict):
        return []

    blocked_intents = blocked_intents or set()
    valid_topics = set(_product_visible_tags(product))
    normalized = _normalize_llm_suggested_actions(
        raw_actions,
        blocked_intents=blocked_intents,
        valid_topics=valid_topics,
    )

    for fallback_action in _fallback_suggested_actions(product):
        appendable = _normalize_llm_suggested_actions(
            [fallback_action],
            blocked_intents=blocked_intents,
            valid_topics=valid_topics,
            existing_actions=normalized,
            require_min=False,
        )
        if appendable:
            normalized.extend(appendable)
        if len(normalized) >= MAX_SUGGESTED_ACTIONS:
            break

    if len(normalized) < MIN_SUGGESTED_ACTIONS:
        return []
    return sorted(
        normalized[:MAX_SUGGESTED_ACTIONS],
        key=lambda action: (action["priority"], len(action["label"])),
    )


def _normalize_no_match_suggested_actions(
    raw_actions: Any,
    *,
    blocked_intents: set[str] | None = None,
) -> list[dict[str, Any]]:
    del blocked_intents
    normalized = _normalize_llm_suggested_actions(
        raw_actions,
        blocked_intents=set(),
        valid_topics=None,
        dedupe_by_intent=False,
    )
    sanitized: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for action in normalized:
        label = _compact_text(_rewrite_episode_length_terms_for_service(action.get("label")), 34)
        user_message = _compact_text(_rewrite_episode_length_terms_for_service(action.get("userMessage")), 80)
        if not label or not user_message or label in seen_labels:
            continue
        action = {**action, "label": label, "userMessage": user_message}
        sanitized.append(action)
        seen_labels.add(label)
    if len(sanitized) < MIN_SUGGESTED_ACTIONS:
        return []
    return sanitized[:MAX_SUGGESTED_ACTIONS]


def _rewrite_episode_length_terms_for_service(value: Any) -> str:
    text_value = str(value or "")
    if not text_value:
        return ""
    replacements: tuple[tuple[str, str], ...] = (
        (r"초\s*단편\s*소설", "5화 이하 작품"),
        (r"초\s*단편", "5화 이하 작품"),
        (r"단편\s*소설", "5화 이하 작품"),
        (r"단편", "5화 이하 작품"),
        (r"짧은\s*소설", "5화 이하 작품"),
        (r"장편\s*소설", "100화 이상 작품"),
        (r"장편", "100화 이상 작품"),
        (r"긴\s*소설", "100화 이상 작품"),
        (r"(?<!웹)소설", "작품"),
    )
    for pattern, replacement in replacements:
        text_value = re.sub(pattern, replacement, text_value)
    text_value = re.sub(r"(5화 이하 작품|100화 이상 작품)\s*작품", r"\1", text_value)
    text_value = re.sub(r"\s{2,}", " ", text_value).strip()
    return text_value


def _normalize_llm_suggested_actions(
    raw_actions: Any,
    *,
    blocked_intents: set[str],
    valid_topics: set[str] | None,
    existing_actions: list[dict[str, Any]] | None = None,
    require_min: bool = True,
    dedupe_by_intent: bool = True,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = {
        (
            str(action.get("intent") or ""),
            str(action.get("topic") or "")
            if str(action.get("intent") or "") == "explain_attribute"
            else ("" if dedupe_by_intent else str(action.get("label") or "")),
        )
        for action in existing_actions or []
    }

    def append_action(raw_action: Any) -> None:
        if len(normalized) >= MAX_SUGGESTED_ACTIONS or not isinstance(raw_action, dict):
            return
        intent = str(raw_action.get("intent") or "").strip()
        if intent not in SUGGESTED_ACTION_INTENTS:
            return
        if intent in blocked_intents:
            return
        label = _compact_text(raw_action.get("label"), 34)
        user_message = _compact_text(
            raw_action.get("userMessage") or raw_action.get("user_message") or label,
            80,
        )
        if not label or not user_message:
            return
        topic = _normalize_visible_tag(raw_action.get("topic"))
        if topic and valid_topics is not None and topic not in valid_topics:
            topic = ""
        key = (intent, topic if intent == "explain_attribute" else ("" if dedupe_by_intent else label))
        if key in seen_keys:
            return
        seen_keys.add(key)
        default_priority = SUGGESTED_ACTION_DEFAULT_PRIORITIES.get(intent, 99)
        action_priority = default_priority
        raw_action_id = (
            raw_action.get("actionId")
            or raw_action.get("action_id")
            or raw_action.get("id")
            or intent
        )
        action_id = _compact_text(raw_action_id, 40) or intent
        action = {
            "id": action_id,
            "actionId": action_id,
            "label": label,
            "userMessage": user_message,
            "intent": intent,
            "priority": action_priority,
        }
        if topic:
            action["topic"] = topic
        normalized.append(action)

    if isinstance(raw_actions, list):
        for raw_action in raw_actions:
            append_action(raw_action)

    if require_min and len(normalized) < MIN_SUGGESTED_ACTIONS:
        return []
    return sorted(
        normalized[:MAX_SUGGESTED_ACTIONS],
        key=lambda action: (action["priority"], len(action["label"])),
    )


def _log_suggested_actions(
    *,
    product_id: int | None,
    final_mode: str,
    page_context: dict | None,
    suggested_actions: list[dict[str, Any]],
) -> None:
    source_action_id = (page_context or {}).get("source_action_id")
    logger.info(
        "[ai_chat] suggested_actions product_id=%s final_mode=%s source_action_id=%s actions=%s",
        product_id,
        final_mode,
        source_action_id,
        [
            {
                "id": action.get("actionId") or action.get("id"),
                "intent": action.get("intent"),
                "priority": action.get("priority"),
            }
            for action in suggested_actions
        ],
    )


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


def _extract_gemini_text(response_json: dict[str, Any]) -> str:
    texts: list[str] = []
    for candidate in response_json.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text_value = str(part.get("text") or "").strip()
            if text_value:
                texts.append(text_value)
    return "\n".join(texts).strip()


async def _call_gemini_text(
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2048,
    temperature: float = 1.0,
    timeout_seconds: float = 45.0,
) -> str:
    if not settings.GEMINI_API_KEY:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message="AI 추천 서비스가 설정되지 않았습니다.",
        )

    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {
                "thinkingLevel": "low",
            },
        },
    }
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.AI_CHAT_GEMINI_MODEL}:generateContent",
            headers={
                "content-type": "application/json",
                "x-goog-api-key": settings.GEMINI_API_KEY,
            },
            json=payload,
        )

    if response.status_code != 200:
        error_logger.error("Gemini generateContent API error: %s %s", response.status_code, response.text)
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message="AI 서비스 호출에 실패했습니다.",
        )

    reply = _extract_gemini_text(response.json())
    if not reply:
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message="AI 서비스 응답이 비어 있습니다.",
        )
    return reply


def _to_gemini_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema

    if "oneOf" in schema:
        variants = [item for item in schema.get("oneOf") or [] if isinstance(item, dict)]
        non_null = [item for item in variants if item.get("type") != "null"]
        has_null = len(non_null) != len(variants)
        if len(non_null) == 1:
            converted = _to_gemini_schema(non_null[0])
            if isinstance(converted, dict) and has_null:
                converted["nullable"] = True
            return converted

    converted: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "oneOf":
            continue
        if key == "properties" and isinstance(value, dict):
            converted[key] = {
                str(prop_key): _to_gemini_schema(prop_value)
                for prop_key, prop_value in value.items()
            }
        elif key == "items":
            converted[key] = _to_gemini_schema(value)
        else:
            converted[key] = value
    return converted


def _to_gemini_function_declarations(tools: list[dict] | None) -> list[dict]:
    declarations: list[dict] = []
    for tool in tools or []:
        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        declarations.append(
            {
                "name": name,
                "description": str(tool.get("description") or ""),
                "parameters": _to_gemini_schema(tool.get("input_schema") or {"type": "object", "properties": {}}),
            }
        )
    return declarations


def _parse_tool_result_content(raw_content: Any) -> Any:
    if isinstance(raw_content, str):
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            return {"text": raw_content}
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    if isinstance(raw_content, dict):
        return raw_content
    return {"result": _to_json_safe(raw_content)}


def _internal_assistant_blocks_to_gemini_parts(content: Any) -> list[dict]:
    if isinstance(content, str):
        text_value = content.strip()
        return [{"text": text_value}] if text_value else []

    parts: list[dict] = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text_value = str(block.get("text") or "").strip()
            if text_value:
                parts.append({"text": text_value})
        elif block.get("type") == "tool_use":
            function_call = {
                "name": str(block.get("name") or ""),
                "args": _to_json_safe(block.get("input") or {}),
            }
            if block.get("id"):
                function_call["id"] = str(block.get("id"))
            part = {"functionCall": function_call}
            if block.get("thoughtSignature"):
                part["thoughtSignature"] = str(block.get("thoughtSignature"))
            parts.append(part)
    return parts


def _internal_user_content_to_gemini_parts(content: Any) -> list[dict]:
    if isinstance(content, str):
        text_value = content.strip()
        return [{"text": text_value}] if text_value else []

    parts: list[dict] = []
    for item in content or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "tool_result":
            continue
        function_response = {
            "name": str(item.get("name") or ""),
            "response": _parse_tool_result_content(item.get("content")),
        }
        if item.get("tool_use_id"):
            function_response["id"] = str(item.get("tool_use_id"))
        parts.append({"functionResponse": function_response})
    return parts


def _to_gemini_contents(messages: list[dict]) -> list[dict]:
    contents: list[dict] = []
    for message in messages or []:
        role = str(message.get("role") or "user").strip().lower()
        content = message.get("content")
        if role == "assistant":
            parts = _internal_assistant_blocks_to_gemini_parts(content)
            gemini_role = "model"
        else:
            parts = _internal_user_content_to_gemini_parts(content)
            gemini_role = "user"
        if parts:
            contents.append({"role": gemini_role, "parts": parts})
    return contents


def _gemini_response_to_internal(response_json: dict[str, Any]) -> dict:
    content_blocks: list[dict] = []
    tool_index = 0
    for candidate in response_json.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text_value = str(part.get("text") or "").strip()
            if text_value:
                content_blocks.append({"type": "text", "text": text_value})
            function_call = part.get("functionCall")
            if isinstance(function_call, dict):
                tool_index += 1
                tool_block = {
                    "type": "tool_use",
                    "id": str(function_call.get("id") or f"gemini-tool-{tool_index}"),
                    "name": str(function_call.get("name") or ""),
                    "input": function_call.get("args") or {},
                }
                if part.get("thoughtSignature"):
                    tool_block["thoughtSignature"] = str(part.get("thoughtSignature"))
                content_blocks.append(tool_block)
        if content_blocks:
            break
    return {"content": content_blocks}


def _allowed_gemini_tool_names(tools: list[dict] | None, tool_choice: dict[str, Any] | None) -> list[str]:
    tool_names = [str(tool.get("name") or "") for tool in tools or [] if str(tool.get("name") or "")]
    if not tool_choice:
        return tool_names
    if tool_choice.get("type") == "tool":
        name = str(tool_choice.get("name") or "")
        return [name] if name else tool_names
    return tool_names


async def _call_gemini_messages(
    *,
    system_prompt: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: dict[str, Any] | None = None,
    max_tokens: int = 1024,
    timeout_seconds: float = 45.0,
) -> dict:
    if not settings.GEMINI_API_KEY:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message="AI 추천 서비스가 설정되지 않았습니다.",
        )

    payload: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": _to_gemini_contents(messages),
        "generationConfig": {
            "temperature": 0.35,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"thinkingLevel": "low"},
        },
    }
    function_declarations = _to_gemini_function_declarations(tools)
    if function_declarations:
        allowed_names = _allowed_gemini_tool_names(tools, tool_choice)
        payload["tools"] = [{"functionDeclarations": function_declarations}]
        payload["toolConfig"] = {
            "functionCallingConfig": {
                "mode": "ANY",
                "allowedFunctionNames": allowed_names,
            }
        }

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.AI_CHAT_GEMINI_MODEL}:generateContent",
            headers={
                "content-type": "application/json",
                "x-goog-api-key": settings.GEMINI_API_KEY,
            },
            json=payload,
        )

    if response.status_code != 200:
        error_logger.error("Gemini generateContent API error: %s %s", response.status_code, response.text)
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message="AI 서비스 호출에 실패했습니다.",
        )

    return _gemini_response_to_internal(response.json())


def _build_current_product_overview_gemini_prompt(
    *,
    product_info: dict[str, Any],
    messages: list[dict],
    user_query: str,
) -> tuple[str, str]:
    title = str(product_info.get("title") or "이 작품").strip() or "이 작품"
    fields = {
        "title": title,
        "author": product_info.get("author_name"),
        "episodeTotal": product_info.get("episode_total"),
        "primaryGenre": product_info.get("primary_genre"),
        "subGenre": product_info.get("sub_genre"),
        "synopsis": product_info.get("synopsis_text"),
        "premise": product_info.get("premise"),
        "hook": product_info.get("hook"),
        "episodeSummary": product_info.get("episode_summary_text"),
        "mood": product_info.get("mood"),
        "pacing": product_info.get("pacing"),
        "tasteTags": product_info.get("taste_tags"),
        "worldviewTags": product_info.get("worldview_tags"),
        "protagonistTypeTags": product_info.get("protagonist_type_tags"),
        "protagonistJobTags": product_info.get("protagonist_job_tags"),
        "protagonistMaterialTags": product_info.get("protagonist_material_tags"),
        "styleTags": product_info.get("axis_style_tags"),
        "romanceTags": product_info.get("axis_romance_tags"),
        "storyContext": _compact_story_context(product_info.get("story_context")),
    }
    compact_fields = {
        key: value
        for key, value in fields.items()
        if value not in (None, "", [], {})
    }
    system_prompt = (
        "너는 라이크노벨의 AI사서다. 사용자가 현재 작품 상세페이지에서 묻는 질문에 답한다. "
        "제공된 작품 정보 안에서만 말하고, 없는 정보는 단정하지 않는다. "
        "추천봇처럼 다른 작품을 억지로 권하지 말고 현재 작품의 매력을 독자에게 자연스럽게 설명한다. "
        "한국어 해요체로 2~4문장만 답한다."
    )
    conversation_memory = _build_conversation_memory(messages)
    prompt_parts = [f"사용자 질문: {user_query}"]
    if conversation_memory:
        prompt_parts.append("최근 대화 맥락:\n" + "\n".join(conversation_memory))
    prompt_parts.append(f"현재 작품 정보:\n{json.dumps(_to_json_safe(compact_fields), ensure_ascii=False)}")
    user_prompt = "\n\n".join(prompt_parts)
    return system_prompt, user_prompt


async def _handle_current_product_overview_with_gemini(
    *,
    normalized_messages: list[dict],
    page_context: dict,
    profile: dict | None,
    reader_context: dict,
    db: AsyncSession,
    adult_yn: str,
) -> dict:
    current_product_id = _safe_int(page_context.get("current_product_id"), 0)
    if current_product_id <= 0:
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message="AI 서비스 호출에 실패했습니다.",
        )

    product_info = await get_product_info(
        db,
        product_id=current_product_id,
        adult_yn=adult_yn,
        include_episode_previews=False,
        episode_numbers=None,
        include_story_context=True,
    )
    system_prompt, user_prompt = _build_current_product_overview_gemini_prompt(
        product_info=product_info,
        messages=normalized_messages,
        user_query=_latest_user_query(normalized_messages),
    )
    raw_reply = await _call_gemini_text(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    reply = _limit_readable_reply(_sanitize_reply_text(raw_reply)) or f"{product_info.get('title') or '이 작품'}의 핵심 정보를 확인했습니다."
    product, taste_match = await _build_product_and_taste(
        selected_product_id=current_product_id,
        last_search_candidates=[],
        profile=profile,
        db=db,
        factor_scores=reader_context.get("factor_scores"),
        adult_yn=adult_yn,
        fallback_to_search=False,
        prefetched_product_info=product_info,
    )
    if product:
        product["matchReason"] = reply
    latest_query = _latest_user_query(normalized_messages)
    blocked_intents = _blocked_suggested_action_intents(page_context, latest_query)
    suggested_actions = _normalize_suggested_actions(
        product,
        _build_current_product_suggested_actions(
            product=product,
            latest_query=latest_query,
        ),
        blocked_intents=blocked_intents,
    )
    _log_suggested_actions(
        product_id=current_product_id,
        final_mode="weak_recommend",
        page_context=page_context,
        suggested_actions=suggested_actions,
    )
    return {
        "reply": reply,
        "product": product,
        "tasteMatch": taste_match,
        "taste_match": taste_match,
        "suggestedActions": suggested_actions,
        "finalMode": "weak_recommend",
    }


def _build_similar_product_reply(
    *,
    product: dict,
    similar_candidate: dict,
) -> str:
    signals = [
        str(signal).strip()
        for signal in (similar_candidate.get("matched_signals") or [])
        if str(signal).strip()
    ][:2]
    signal_text = ", ".join(signals) if signals else "설정과 분위기"
    visible_tags = [
        _normalize_visible_tag(tag)
        for tag in (product.get("matchTags") or product.get("tasteTags") or [])
        if _normalize_visible_tag(tag)
    ][:2]
    if visible_tags:
        return _limit_readable_reply(
            f"현재 작품과 {signal_text} 결이 가까워요.\n{', '.join(visible_tags)} 요소가 이어져서 다음 카드로 먼저 볼 만합니다."
        )
    return _limit_readable_reply(
        f"현재 작품과 {signal_text} 결이 가까워요.\n비슷한 감각으로 이어서 보기 좋은 후보를 먼저 골랐습니다."
    )


async def _handle_similar_product_request(
    *,
    normalized_messages: list[dict],
    page_context: dict,
    session_state: dict,
    profile: dict | None,
    reader_context: dict,
    db: AsyncSession,
    adult_yn: str,
    exclude_ids: list[int],
    query_terms: list[str],
) -> dict | None:
    latest_query = _latest_user_query(normalized_messages)
    if not _is_similar_request(latest_query):
        return None

    anchor_product_id = _resolve_conversation_product_id(page_context, session_state)
    if anchor_product_id <= 0:
        return None

    _, similar_products = await get_similar_products(
        db,
        base_product_id=anchor_product_id,
        exclude_product_ids=exclude_ids,
        adult_yn=adult_yn,
        limit=3,
        profile=profile,
    )
    if not similar_products:
        return None

    selected_candidate = similar_products[0]
    selected_product_id = _safe_int(selected_candidate.get("product_id"), 0)
    if selected_product_id <= 0:
        return None

    product, taste_match = await _build_product_and_taste(
        selected_product_id=selected_product_id,
        last_search_candidates=[],
        profile=profile,
        db=db,
        factor_scores=reader_context.get("factor_scores"),
        adult_yn=adult_yn,
        fallback_to_search=False,
        query_terms=query_terms,
    )
    if not product:
        return None

    reply = _build_similar_product_reply(
        product=product,
        similar_candidate=selected_candidate,
    )
    product["matchReason"] = reply
    suggested_actions = _normalize_suggested_actions(
        product,
        None,
        blocked_intents=_blocked_suggested_action_intents(page_context, latest_query),
    )
    _log_suggested_actions(
        product_id=selected_product_id,
        final_mode="recommend",
        page_context=page_context,
        suggested_actions=suggested_actions,
    )
    return {
        "reply": reply,
        "product": product,
        "tasteMatch": taste_match,
        "taste_match": taste_match,
        "suggestedActions": suggested_actions,
        "finalMode": "recommend",
    }


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
        "conversation_memory": _build_conversation_memory(messages),
        "exploration_state": _build_exploration_state(messages, context),
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
    active_focus_product_id = _safe_int(raw.get("active_focus_product_id") or raw.get("activeFocusProductId"), 0) or None
    current_episode_id = _safe_int(raw.get("current_episode_id"), 0) or None
    focus_product_card = bool(raw.get("focus_product_card")) and bool(current_product_id)
    source_action_id = _compact_text(raw.get("source_action_id") or raw.get("sourceActionId"), 80) or None
    source_action_intent = _compact_text(raw.get("source_action_intent") or raw.get("sourceActionIntent"), 40) or None
    if source_action_intent not in SUGGESTED_ACTION_INTENTS:
        source_action_intent = None
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
        "active_focus_product_id": active_focus_product_id,
        "current_episode_id": current_episode_id,
        "current_product_title": current_product_title,
        "focus_product_card": focus_product_card,
        "source_action_id": source_action_id,
        "source_action_intent": source_action_intent,
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
        *AI_LIBRARIAN_SERVICE_CONTEXT_LINES,
        "추천기 preset 규칙에 맞추려 하지 말고, 허용된 데이터 카탈로그와 read-only SQL 조회 결과를 근거로 답한다.",
        "스키마나 상태값은 아래 내장 데이터 카탈로그의 허용 테이블/컬럼과 도메인 값만 사용한다.",
        "다른 유저 개별 row는 조회하지 말고, 작품/작품집계 테이블과 현재 독자 취향 요약만 사용한다.",
        "질문이 구체적이면 바로 조회한다. 질문이 너무 넓고 조건도 취향도 약하면 한 번만 좁혀 묻거나 버튼 프리셋 사용을 제안한다.",
        "추천할 때는 취향, 상태, 분량, 연재주기, 상승세, 품질, 독자반응 중 필요한 축을 스스로 판단해 조회한다.",
        "run_readonly_query는 최대 2회, get_product_info는 최대 1회만 쓸 수 있다. 충분한 후보가 있으면 더 찾지 말고 submit_final_recommendation으로 종료한다.",
        "run_readonly_query는 SELECT/WITH 단일 문장만 허용된다. LIMIT를 포함해라.",
        "작품 추천 후보는 공개 작품 카드로 보여줄 수 있는 후보만 조회한다. tb_product에는 p.open_yn = 'Y', p.author_name IS NOT NULL, TRIM(p.author_name) <> '' 조건을 포함한다.",
        "tb_product_ai_metadata를 추천 후보 검색에 쓰면 m.analysis_status = 'success' 와 COALESCE(m.exclude_from_recommend_yn, 'N') = 'N' 조건을 포함한다.",
        "키워드/소재/직업 추천은 한두 태그만 보지 말고 title, 장르 키워드, tb_product_user_keyword.keyword_name, premise, hook, episode_summary_text, protagonist_desc, protagonist_goal_primary, taste_tags, worldview_tags, protagonist_type_tags, protagonist_job_tags, protagonist_material_tags, axis_romance_tags, axis_style_tags를 넓게 비교한다.",
        "존재하지 않는 컬럼을 추정하지 말고 내장 데이터 카탈로그에 나온 컬럼명만 사용한다. 회차 수는 필요하면 tb_product_episode에서 COUNT(*)로 계산한다.",
        "tb_product에는 premise, hook, reading_rate, evaluation_score, episode_total 컬럼이 없다. 이 값들은 각각 메타/트렌드/평가/회차 집계 테이블에서 가져와야 한다.",
        "작품 추천이면 SQL 결과에서 직접 product_id를 고르고, 근거 2개 이상을 reply에 녹여라.",
        "run_readonly_query 결과에 candidate_details가 있으면 그 안의 story_context, synopsis_text, premise, hook, episode_summary_text, 7축 태그, 장르, 연독/연재주기 지표를 근거로 바로 submit_final_recommendation을 제출한다.",
        "candidate_details가 없거나 현재 작품/특정 회차처럼 SQL 후보 비교가 아닌 상세 질문일 때만 get_product_info를 호출한다.",
        "story_context는 공개·무료 초반 범위에서 서버가 압축한 보조 근거다. 저장된 요약문을 그대로 옮기지 말고 설정, 주요 인물, 관계성, 초반 훅을 고수준으로만 활용한다.",
        "story_context가 없거나 기존 synopsis/DNA와 충돌하면 단정하지 말고 기존 작품 정보만으로 답한다. story_context 부재는 no_match나 후보 제외 사유가 아니다.",
        "현재 작품의 회차 내용 질문(예: 1화/2화 줄거리)이면 현재 페이지 작품 ID로 get_product_info(product_id=..., include_episode_previews=true, episode_numbers=[...])를 호출해 episode_previews를 근거로 답한다.",
        "episode_previews는 공개 무료 회차의 제한된 미리보기다. 원문 전문을 길게 옮기지 말고 회차당 1~2문장으로 요약한다. 미리보기가 없으면 확인 가능한 공개 회차 미리보기가 없다고 말한다.",
        "submit_final_recommendation.mode 규칙: recommend/weak_recommend면 product_id가 필수이고, no_match면 product_id는 null이어야 한다.",
        "조회 결과에 추천 가능한 후보가 1개라도 있으면 no_match보다 weak_recommend를 우선한다. no_match는 SQL 결과가 0건이거나, 모든 후보가 핵심 조건을 명백히 위반할 때만 사용한다.",
        "질문에 없는 숫자 임계치(예: 조회수 50,000 이상, 연독률 12% 이상)를 임의로 만들지 않는다. 작품 비교는 반드시 지금 조회한 DB 결과 내부의 상대 비교와 상위 후보 비교로 설명한다.",
        "질문에 여러 조건이 있어도 사용자가 '모두', '반드시', '정확히'를 명시하지 않았다면 strict AND로 0건을 만들지 않는다. 3개 조건이면 2개만 강하게 맞아도 weak_recommend 후보로 고려하고, OR/가중치 비교로 가장 가까운 작품을 고른다.",
        "예: '현대 배경 + 성장형 + 미스터리'는 세 조건 동시 만족 작품이 없더라도, 조회 결과 안에서 2/3 이상 맞는 후보를 우선 비교해 weak_recommend로 제시할 수 있다.",
        "단, 사용자가 완결/연재중/휴재 같은 작품 상태를 직접 말하면 이는 hard constraint다. 모든 run_readonly_query와 최종 product_id에서 p.status_code 조건을 유지하고, 이 상태 조건을 만족하지 않는 작품은 약추천으로도 제출하지 않는다.",
        "최종 reply는 고정 템플릿을 복붙하지 말고 질문 맥락에 맞게 작성하되, 추천이면 독자 취향/조건과 추천 근거를 자연스럽게 연결한다.",
        "유저에게는 내부 기술 용어를 쓰지 마라. 금지어: 데이터베이스/DB/쿼리/SQL/카탈로그/조회 결과/반환값/스키마/테이블/컬럼/NULL.",
        "mode/internal 상태값(recommend/weak_recommend/no_match)을 답변 문장에 쓰지 마라.",
        "기술적 실패를 그대로 말하지 말고, 자연어로 안내한다. 예: '조건을 조금만 넓혀서 다시 찾아볼게요.'",
        "빈 답변 금지: '추천할 작품을 찾아봤어요', '조건에 맞는 작품을 골랐어요'처럼 근거 없는 일반 문장만 제출하지 않는다.",
        "정확한 후보가 약하거나 없으면 product_id를 null로 제출해도 되지만, 어떤 조건을 유지했는지와 왜 약한지 설명하고 다음 선택지 1개를 제안한다.",
        "현재 보고 있던 작품과 비슷한 작품을 추천할 때는 조회 결과를 근거로 공통점 2개와 차이점 1개를 설명한다.",
        "reply에는 가능하면 story_context의 plot_points/characters/relations/opening_hooks, premise, hook, episode_summary_text, 7축 태그, reading_rate, writing_count_per_week, binge_rate, evaluation_score 같은 구체 근거를 2개 이상 포함한다.",
        "추천 카드는 한 작품만 노출된다. reply에서 작품명을 말할 때는 선택한 product_id의 작품명만 언급하고, 카드가 없는 다른 후보 작품명은 쓰지 않는다.",
        "reply는 2문장, 220자 이내로 읽기 좋게 작성하고 JSON/코드블럭을 출력하지 않는다.",
        "모든 최종 응답은 suggested_actions를 반드시 3개 또는 4개만 제출한다. 추천 카드가 없어 no_match를 제출할 때도 현재 실패 조건을 좁히거나 넓히는 후속질문을 만든다. 2개 이하나 5개 이상은 금지다.",
        "suggested_actions는 reply와 선택 작품 근거를 이어받는 짧은 후속질문이다. label/user_message는 한국어 한 줄 질문으로 쓰고, intent는 허용 enum만 사용한다.",
        "suggested_actions에는 action_id와 priority를 가능하면 함께 넣는다. priority는 낮을수록 먼저 보이며 기본 순서는 explain_match=10, explain_entry=20, explain_attribute=30, recommend_similar=40이다.",
        f"현재 독자 adult_yn={adult_yn}",
        f"내장 데이터 카탈로그(JSON): {_build_fact_catalog_prompt()}",
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
    if session_state.get("conversation_memory"):
        lines.append("최근 대화 맥락:\n" + "\n".join(session_state["conversation_memory"]))
        lines.append("짧은 후속질문은 최근 대화 맥락과 현재 페이지 작품/직전 추천 작품을 기준으로 해석한다. 새 조건이 명시되면 새 조건을 우선한다.")
    if session_state.get("exploration_state"):
        lines.append(
            "현재 세션 탐색 조건(JSON): "
            + json.dumps(session_state["exploration_state"], ensure_ascii=False, separators=(",", ":"))
        )
        lines.append("hard/negative 조건은 사용자가 명시적으로 풀기 전까지 유지하고, 최종 추천 카드가 hard 조건을 위반하면 제출하지 않는다.")
        lines.append("soft/weak 조건은 후보를 없애는 필터가 아니라 추천 순위와 설명을 돕는 힌트로만 사용한다.")
    if _is_new_recommendation_request(session_state.get("last_user_query", "")):
        lines.append("이번 질문은 새 작품 추천 요청이다. 현재 페이지 작품은 참고 맥락일 뿐이며, 현재 작품 정보 안에서만 답하지 말고 전체 추천 후보를 탐색한다.")
    if session_state.get("recommended_product_ids"):
        lines.append(f"이번 세션 이미 추천한 작품 ID: {session_state['recommended_product_ids']}")
        if not page_context.get("current_product_id"):
            lines.append(f"현재 대화 대상 작품 ID: {session_state['recommended_product_ids'][-1]}")
    if page_context.get("active_focus_product_id"):
        lines.append(f"현재 대화 초점 작품 ID: {page_context['active_focus_product_id']}")
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


def _has_string_equality_filter(sql: str, column: str, value: str) -> bool:
    pattern = rf"\b(?:[A-Za-z_][\w]*\.)?{re.escape(column)}\s*=\s*(['\"]){re.escape(value)}\1"
    return bool(re.search(pattern, sql, flags=re.IGNORECASE))


def _has_nonempty_author_filter(sql: str) -> bool:
    has_not_null = bool(
        re.search(
            r"\b(?:[A-Za-z_][\w]*\.)?author_name\s+IS\s+NOT\s+NULL\b",
            sql,
            flags=re.IGNORECASE,
        )
    )
    compact_sql = re.sub(r"\s+", "", sql).lower()
    has_trim_not_empty = (
        "trim(" in compact_sql
        and "author_name)" in compact_sql
        and ("<>''" in compact_sql or "!=''" in compact_sql or '<>""' in compact_sql or '!=""' in compact_sql)
    )
    return has_not_null and has_trim_not_empty


def _has_recommendable_metadata_filter(sql: str) -> bool:
    if not _has_string_equality_filter(sql, "analysis_status", "success"):
        return False
    compact_sql = re.sub(r"\s+", "", sql).lower()
    has_direct_exclude_filter = (
        "exclude_from_recommend_yn='n'" in compact_sql
        or 'exclude_from_recommend_yn="n"' in compact_sql
    )
    has_coalesced_exclude_filter = (
        "coalesce(" in compact_sql
        and "exclude_from_recommend_yn" in compact_sql
        and (")='n'" in compact_sql or ')="n"' in compact_sql)
    )
    return has_direct_exclude_filter or has_coalesced_exclude_filter


def _validate_public_recommendation_filters(sql: str, table_refs: list[str]) -> None:
    if "tb_product" in table_refs:
        if not _has_string_equality_filter(sql, "open_yn", "Y"):
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="tb_product 추천 후보 조회에는 p.open_yn = 'Y' 조건이 필요합니다.",
            )
        if not _has_nonempty_author_filter(sql):
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="tb_product 추천 후보 조회에는 p.author_name IS NOT NULL 및 TRIM(p.author_name) <> '' 조건이 필요합니다.",
            )
    if "tb_product_ai_metadata" in table_refs and not _has_recommendable_metadata_filter(sql):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="tb_product_ai_metadata 추천 후보 조회에는 m.analysis_status = 'success' 및 exclude_from_recommend_yn = 'N' 조건이 필요합니다.",
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
    _validate_public_recommendation_filters(normalized, table_refs)

    limit_match = re.search(r"\blimit\s+(\d+)\b", normalized, re.IGNORECASE)
    if limit_match:
        if int(limit_match.group(1)) > DATA_AGENT_SQL_RESULT_LIMIT:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=f"LIMIT는 {DATA_AGENT_SQL_RESULT_LIMIT} 이하여야 합니다.",
            )
        return normalized
    return f"{normalized}\nLIMIT {DATA_AGENT_SQL_RESULT_LIMIT}"


def _extract_like_keywords(sql: str) -> list[str]:
    keywords: list[str] = []
    for match in re.finditer(r"\bLIKE\s+(['\"])(?P<value>.*?)\1", sql, flags=re.IGNORECASE | re.DOTALL):
        value = re.sub(r"[%_]", "", match.group("value")).strip()
        value = re.sub(r"\\+", "", value).strip()
        if not 2 <= len(value) <= 30:
            continue
        if not re.fullmatch(r"[0-9A-Za-z가-힣\s]+", value):
            continue
        if value not in keywords:
            keywords.append(value)
        if len(keywords) >= 5:
            break
    return keywords


def _should_try_broad_metadata_keyword_fallback(sql: str) -> bool:
    table_refs = {
        ref.lower()
        for ref in re.findall(r"\b(?:from|join)\s+`?([a-zA-Z0-9_]+)`?", sql, flags=re.IGNORECASE)
    }
    return "tb_product" in table_refs and "tb_product_ai_metadata" in table_refs and bool(_extract_like_keywords(sql))


async def _run_broad_metadata_keyword_query(
    db: AsyncSession,
    *,
    keywords: list[str],
    adult_yn: str,
    required_status_codes: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not keywords:
        return []

    params: dict[str, Any] = {}
    keyword_clauses: list[str] = []
    relevance_parts: list[str] = []
    for index, keyword in enumerate(keywords[:5]):
        param_name = f"kw_{index}"
        params[param_name] = f"%{keyword}%"
        keyword_clauses.append(
            "("
            + " OR ".join(f"{column} LIKE :{param_name}" for column in BROAD_METADATA_KEYWORD_COLUMNS)
            + ")"
        )
        relevance_parts.extend(
            f"CASE WHEN {column} LIKE :{param_name} THEN {weight} ELSE 0 END"
            for column, weight in BROAD_METADATA_RELEVANCE_COLUMNS
        )

    normalized_adult = _normalize_adult_yn(adult_yn)
    status_values = [
        code for code in sorted(required_status_codes or set())
        if code in PRODUCT_STATUS_CODE_VALUES
    ]
    status_clause = ""
    if status_values:
        placeholders: list[str] = []
        for index, code in enumerate(status_values):
            param_name = f"status_{index}"
            params[param_name] = code
            placeholders.append(f":{param_name}")
        status_clause = f"AND p.status_code IN ({', '.join(placeholders)})"
    query_sql = text(
        f"""
        SELECT DISTINCT
            p.product_id,
            p.title,
            p.author_name,
            p.status_code,
            pg.keyword_name AS primary_genre,
            sg.keyword_name AS sub_genre,
            m.premise,
            m.hook,
            m.episode_summary_text,
            m.protagonist_desc,
            m.protagonist_goal_primary,
            m.taste_tags,
            m.worldview_tags,
            m.protagonist_type_tags,
            m.protagonist_job_tags,
            m.protagonist_material_tags,
            m.axis_romance_tags,
            m.axis_style_tags,
            m.similar_famous,
            COALESCE(t.reading_rate, 0) AS reading_rate,
            ({' + '.join(relevance_parts)}) AS relevance_score
        FROM tb_product p
        INNER JOIN tb_product_ai_metadata m
          ON m.product_id = p.product_id
         AND m.analysis_status = 'success'
         AND COALESCE(m.exclude_from_recommend_yn, 'N') = 'N'
        LEFT JOIN tb_standard_keyword pg
          ON pg.keyword_id = p.primary_genre_id
         AND pg.use_yn = 'Y'
        LEFT JOIN tb_standard_keyword sg
          ON sg.keyword_id = p.sub_genre_id
         AND sg.use_yn = 'Y'
        LEFT JOIN tb_product_user_keyword uk ON uk.product_id = p.product_id
        LEFT JOIN tb_product_trend_index t ON t.product_id = p.product_id
        WHERE p.open_yn = 'Y'
          AND p.author_name IS NOT NULL
          AND TRIM(p.author_name) <> ''
          {"AND p.ratings_code = 'all'" if normalized_adult == "N" else ""}
          {status_clause}
          AND ({' OR '.join(keyword_clauses)})
        ORDER BY relevance_score DESC, COALESCE(t.reading_rate, 0) DESC, p.product_id DESC
        LIMIT {DATA_AGENT_SQL_RESULT_LIMIT}
        """
    )
    result = await asyncio.wait_for(
        db.execute(query_sql, params),
        timeout=DATA_AGENT_SQL_TIMEOUT_SECONDS,
    )
    return [_to_json_safe(dict(row)) for row in await _result_mappings_all(result)]


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
            message="조회 SQL이 허용 스키마와 맞지 않습니다. 내장 데이터 카탈로그의 테이블/컬럼을 다시 확인해주세요.",
        ) from exc

    rows = [_to_json_safe(dict(row)) for row in await _result_mappings_all(result)]
    fallback_terms = _extract_like_keywords(safe_sql)
    fallback_applied = False
    if not rows and _should_try_broad_metadata_keyword_fallback(safe_sql):
        try:
            rows = await _run_broad_metadata_keyword_query(
                db,
                keywords=fallback_terms,
                adult_yn=adult_yn,
            )
            fallback_applied = bool(rows)
        except TimeoutError as exc:
            raise CustomResponseException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                message="확장 메타데이터 조회 실행 시간이 너무 깁니다. 조건을 더 좁혀주세요.",
            ) from exc
        except SQLAlchemyError as exc:
            logger.warning("[ai_chat] broad metadata fallback query failed: %s", exc)
    return {
        "sql": safe_sql,
        "row_count": len(rows),
        "rows": rows,
        "metadata_keyword_fallback": fallback_applied,
        "metadata_keyword_terms": fallback_terms if fallback_applied else [],
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
        normalized_message = {"role": role, "content": content}
        product_id = _safe_int(message.get("product_id"), 0)
        if product_id > 0:
            normalized_message["product_id"] = product_id
        normalized.append(normalized_message)

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
    explicit_mode = str(final_tool_input.get("mode") or "").strip()
    if explicit_mode == "no_match":
        return False
    return bool(detail_cache)


async def _force_finalize_response(
    *,
    system_prompt: str,
    model_messages: list[dict],
    reason: str,
    allowed_tool_names: list[str] | None = None,
) -> dict:
    forced_messages = list(model_messages)
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
        [tool for tool in DATA_AGENT_RUNTIME_TOOLS if tool["name"] in set(allowed_tool_names)]
        if allowed_tool_names
        else [tool for tool in DATA_AGENT_RUNTIME_TOOLS if tool["name"] == FINAL_RESPONSE_TOOL_NAME]
    )
    return await _call_gemini_messages(
        system_prompt=system_prompt,
        messages=forced_messages,
        tools=allowed_tools,
        tool_choice={"type": "any"} if allowed_tool_names else {"type": "tool", "name": FINAL_RESPONSE_TOOL_NAME},
        max_tokens=900,
    )


async def _generate_no_match_suggested_actions(
    *,
    latest_user_query: str,
    reply: str,
    blocked_intents: set[str],
) -> list[dict[str, Any]]:
    response = await _call_gemini_messages(
        system_prompt=(
            "너는 라이크노벨 AI 사서의 후속질문 생성기다. "
            + " ".join(AI_LIBRARIAN_SERVICE_CONTEXT_LINES)
            + " "
            "추천 카드가 없는 no_match 답변 아래에 붙일 버튼 질문만 만든다. "
            "고정 문구를 반복하지 말고 사용자 질문과 실패 조건을 바탕으로 조건을 넓히거나 좁히는 질문을 만든다."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"사용자 질문: {latest_user_query}\n"
                    f"AI 사서 no_match 답변: {reply}\n"
                    "submit_no_match_suggested_actions tool로 suggested_actions 3개 또는 4개만 제출하세요. "
                    "label은 짧은 한국어 질문, user_message는 클릭 즉시 보낼 사용자 프롬프트입니다. "
                    "새 추천을 다시 탐색하는 질문이면 intent는 recommend_similar를 우선 사용하세요."
                ),
            }
        ],
        tools=[NO_MATCH_SUGGESTED_ACTION_TOOL],
        tool_choice={"type": "tool", "name": NO_MATCH_SUGGESTED_ACTION_TOOL_NAME},
        max_tokens=500,
        timeout_seconds=20.0,
    )
    for tool_use in _extract_tool_use_blocks(response.get("content") or []):
        if str(tool_use.get("name") or "") != NO_MATCH_SUGGESTED_ACTION_TOOL_NAME:
            continue
        tool_input = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {}
        return _normalize_no_match_suggested_actions(
            tool_input.get("suggested_actions") or tool_input.get("suggestedActions"),
            blocked_intents=blocked_intents,
        )
    return []


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


def _collect_candidate_product_ids(
    *,
    last_query_rows: list[dict[str, Any]],
    detail_cache: dict[int, dict[str, Any]],
) -> list[int]:
    candidate_ids: list[int] = []
    seen_ids: set[int] = set()
    for row in last_query_rows:
        if not isinstance(row, dict):
            continue
        product_id = _safe_int(row.get("product_id"), 0)
        if product_id <= 0 or product_id in seen_ids:
            continue
        candidate_ids.append(product_id)
        seen_ids.add(product_id)
    for product_id in detail_cache.keys():
        product_id = _safe_int(product_id, 0)
        if product_id <= 0 or product_id in seen_ids:
            continue
        candidate_ids.append(product_id)
        seen_ids.add(product_id)
    return candidate_ids


def _is_allowed_current_product_selection(
    *,
    selected_product_id: int | None,
    current_product_id: int,
    current_overview_request: bool,
) -> bool:
    return (
        selected_product_id is not None
        and current_product_id > 0
        and selected_product_id == current_product_id
        and current_overview_request
    )


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


def _limit_readable_reply(reply: str) -> str:
    text_value = str(reply or "").strip()
    if not text_value:
        return ""
    text_value = re.sub(r"[ \t]{2,}", " ", text_value)
    raw_parts = re.split(r"(?<=[.!?。！？])\s+|\n+", text_value)
    parts = [part.strip() for part in raw_parts if part and part.strip()]
    if parts:
        text_value = "\n".join(parts[:MAX_REPLY_SENTENCES])
    if len(text_value) <= MAX_REPLY_CHARS:
        return text_value
    clipped = text_value[:MAX_REPLY_CHARS].rstrip()
    sentence_end = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"), clipped.rfind("。"), clipped.rfind("！"), clipped.rfind("？"))
    if sentence_end >= 80:
        return clipped[: sentence_end + 1].strip()
    return f"{clipped.rstrip(' .,!?。！？')}..."


def _collect_unselected_candidate_titles(
    *,
    selected_product_id: int | None,
    last_query_rows: list[dict[str, Any]],
    detail_cache: dict[int, dict[str, Any]],
) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    for row in [*last_query_rows, *detail_cache.values()]:
        if not isinstance(row, dict):
            continue
        product_id = _safe_int(row.get("product_id"), 0)
        if selected_product_id is not None and product_id == selected_product_id:
            continue
        title = _compact_text(row.get("title"), 80)
        if not title or title in seen:
            continue
        seen.add(title)
        titles.append(title)
    return titles


def _reply_mentions_any_title(reply: str, titles: list[str]) -> bool:
    return any(title and title in reply for title in titles)


def _build_compact_product_reply(product: dict) -> str:
    raw_title = str(product.get("title") or "").strip()
    subject = f"'{raw_title}'" if raw_title and len(raw_title) <= 16 else "이 작품"
    match_tags = [
        _normalize_visible_tag(tag)
        for tag in (product.get("matchTags") or product.get("tasteTags") or [])
        if _normalize_visible_tag(tag)
    ][:3]
    if match_tags:
        return _limit_readable_reply(
            f"{subject}은 {', '.join(match_tags)} 키워드가 맞는 후보예요.\n요청하신 결과 가장 가까워 먼저 보여드렸습니다."
        )
    return _limit_readable_reply(f"지금 조건에서는 {subject}이 가장 가까운 후보예요.")


def _normalize_product_reply(
    *,
    raw_reply: str,
    product: dict,
    unselected_candidate_titles: list[str] | None = None,
) -> str:
    sanitized_reply = _sanitize_reply_text(raw_reply)
    reply = _limit_readable_reply(sanitized_reply)
    if reply and _reply_mentions_any_title(reply, unselected_candidate_titles or []):
        reply = ""
    if reply and len(sanitized_reply) > MAX_RECOMMENDATION_REPLY_CHARS:
        return _build_compact_product_reply(product)
    if reply:
        return reply
    return _build_compact_product_reply(product)


def _normalize_no_match_reply(reply: str) -> str:
    fallback = "지금 조건만으로는 작품 카드를 확정하지 못했습니다.\n원하는 결을 하나만 더 좁혀주시면 다시 골라드릴게요."
    text_value = _limit_readable_reply(_sanitize_reply_text(reply))
    if not text_value:
        return fallback
    success_pattern = re.compile(r"(추천(?:합니다|드려요|할게요|해요)|골랐(?:어요|습니다)|후보를 찾(?:았습니다|았어요)|작품을 찾(?:았습니다|았어요))")
    quoted_title_pattern = re.compile(r"[「『'“\"]([^」』'”\"]{2,60})[」』'”\"]")
    if success_pattern.search(text_value) or quoted_title_pattern.search(text_value):
        return fallback
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
    query_terms: list[str] | None = None,
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
                "matchTags": _build_match_tags(product_info, query_terms),
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
                "matchTags": _build_match_tags(fallback_dna, query_terms),
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


async def _build_status_keyword_fallback_recommendation(
    *,
    latest_user_query: str,
    required_status_codes: set[str],
    query_terms: list[str],
    profile: dict | None,
    db: AsyncSession,
    factor_scores: dict[str, dict[str, float]] | None,
    adult_yn: str,
) -> dict[str, Any] | None:
    keywords = _extract_broad_recommendation_keywords(latest_user_query, query_terms)
    if not required_status_codes or not keywords:
        return None
    try:
        rows = await _run_broad_metadata_keyword_query(
            db,
            keywords=keywords,
            adult_yn=adult_yn,
            required_status_codes=required_status_codes,
        )
    except (TimeoutError, SQLAlchemyError) as exc:
        logger.warning("[ai_chat] status keyword fallback failed: %s", exc)
        return None
    matching_rows = _filter_candidate_rows_by_required_status(rows, required_status_codes)
    if not matching_rows:
        return None

    selected_product_id = _safe_int(matching_rows[0].get("product_id"), 0)
    if selected_product_id <= 0:
        return None
    product, taste_match = await _build_product_and_taste(
        selected_product_id=selected_product_id,
        last_search_candidates=[],
        profile=profile,
        db=db,
        factor_scores=factor_scores,
        adult_yn=adult_yn,
        fallback_to_search=False,
        query_terms=query_terms or keywords,
    )
    if not product or not _candidate_matches_required_status(product, required_status_codes):
        return None

    keyword_label = ", ".join(keywords[:2])
    raw_reply = (
        f"{_status_constraint_label(required_status_codes)} 조건은 지키고 "
        f"{keyword_label} 결이 가까운 작품을 먼저 골랐어요. "
        "정확히 맞는 후보가 적어 가장 가까운 카드로 보여드릴게요."
    )
    reply = _normalize_product_reply(
        raw_reply=raw_reply,
        product=product,
        unselected_candidate_titles=[],
    )
    product["matchReason"] = reply
    suggested_actions = _normalize_suggested_actions(product, None)
    _log_suggested_actions(
        product_id=selected_product_id,
        final_mode="weak_recommend",
        page_context={},
        suggested_actions=suggested_actions,
    )
    return {
        "reply": reply,
        "product": product,
        "taste_match": taste_match,
        "tasteMatch": taste_match,
        "suggestedActions": suggested_actions,
        "finalMode": "weak_recommend",
    }


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
    include_story_context: bool = False,
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
        "monopoly_yn": row_dict.get("monopoly_yn"),
        "contract_yn": row_dict.get("contract_yn"),
        "paid_episode_no": _safe_int(row_dict.get("paid_episode_no"), 0),
        "publish_days": row_dict.get("publish_days"),
        "last_episode_date": str(row_dict.get("last_episode_date") or ""),
        "new_release_yn": row_dict.get("new_release_yn"),
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
        "waiting_for_free_yn": row_dict.get("waiting_for_free_yn"),
        "six_nine_path_yn": row_dict.get("six_nine_path_yn"),
        "summary_line": summary_line,
    }
    if include_episode_previews:
        product_info["episode_previews"] = await _get_public_episode_previews(
            db,
            product_id=product_id,
            episode_numbers=episode_numbers,
            adult_yn=adult_yn,
        )
    if include_story_context:
        story_context = await _load_story_context_summary(db, product_id=product_id)
        if story_context:
            product_info["story_context"] = story_context
    return product_info


def _compact_candidate_detail(product_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_id": product_info.get("product_id"),
        "title": product_info.get("title"),
        "author_name": product_info.get("author_name"),
        "status_code": product_info.get("status_code"),
        "price_type": product_info.get("price_type"),
        "monopoly_yn": product_info.get("monopoly_yn"),
        "contract_yn": product_info.get("contract_yn"),
        "cover_url": product_info.get("cover_url"),
        "episode_total": product_info.get("episode_total"),
        "free_episode_count": product_info.get("free_episode_count"),
        "paid_episode_count": product_info.get("paid_episode_count"),
        "reading_rate": product_info.get("reading_rate"),
        "writing_count_per_week": product_info.get("writing_count_per_week"),
        "binge_rate": product_info.get("binge_rate"),
        "dropoff_7d": product_info.get("dropoff_7d"),
        "reengage_rate": product_info.get("reengage_rate"),
        "primary_reader_group": product_info.get("primary_reader_group"),
        "current_rank": product_info.get("current_rank"),
        "previous_rank": product_info.get("previous_rank"),
        "last_episode_date": product_info.get("last_episode_date"),
        "new_release_yn": product_info.get("new_release_yn"),
        "waiting_for_free_yn": product_info.get("waiting_for_free_yn"),
        "six_nine_path_yn": product_info.get("six_nine_path_yn"),
        "primary_genre": product_info.get("primary_genre"),
        "sub_genre": product_info.get("sub_genre"),
        "synopsis_text": _compact_text(product_info.get("synopsis_text"), 500),
        "premise": _compact_text(product_info.get("premise"), 300),
        "hook": _compact_text(product_info.get("hook"), 300),
        "episode_summary_text": _compact_text(product_info.get("episode_summary_text"), 700),
        "protagonist_type": product_info.get("protagonist_type"),
        "protagonist_desc": _compact_text(product_info.get("protagonist_desc"), 400),
        "protagonist_goal_primary": _compact_text(product_info.get("protagonist_goal_primary"), 240),
        "mood": product_info.get("mood"),
        "pacing": product_info.get("pacing"),
        "regression_type": product_info.get("regression_type"),
        "themes": product_info.get("themes") or [],
        "taste_tags": product_info.get("taste_tags") or [],
        "worldview_tags": product_info.get("worldview_tags") or [],
        "protagonist_type_tags": product_info.get("protagonist_type_tags") or [],
        "protagonist_job_tags": product_info.get("protagonist_job_tags") or [],
        "protagonist_material_tags": product_info.get("protagonist_material_tags") or [],
        "axis_romance_tags": product_info.get("axis_romance_tags") or [],
        "axis_style_tags": product_info.get("axis_style_tags") or [],
        "story_context": _compact_story_context(product_info.get("story_context")),
        "summary_line": product_info.get("summary_line"),
    }


async def _attach_query_candidate_details(
    db: AsyncSession,
    query_result: dict,
    *,
    adult_yn: str,
) -> dict:
    rows = query_result.get("rows") or []
    product_ids: list[int] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        product_id = _safe_int(row.get("product_id"), 0)
        if product_id <= 0 or product_id in product_ids:
            continue
        product_ids.append(product_id)
        if len(product_ids) >= MAX_QUERY_CANDIDATE_SCAN:
            break

    if not product_ids:
        return query_result

    candidate_details: list[dict[str, Any]] = []
    certified_product_ids: list[int] = []
    for product_id in product_ids:
        try:
            product_info = await get_product_info(
                db,
                product_id=product_id,
                adult_yn=adult_yn,
                include_story_context=False,
            )
        except CustomResponseException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                logger.info(
                    "[ai_chat] candidate detail skipped product_id=%s status=%s",
                    product_id,
                    exc.status_code,
                )
                continue
            raise
        certified_product_ids.append(product_id)
        candidate_details.append(product_info)
        if len(candidate_details) >= MAX_QUERY_CANDIDATE_DETAILS:
            break

    story_contexts = await _load_story_context_summaries(db, product_ids=certified_product_ids)
    compact_candidate_details: list[dict[str, Any]] = []
    for product_info in candidate_details:
        product_id = _safe_int(product_info.get("product_id"), 0)
        if product_id in story_contexts:
            product_info = {**product_info, "story_context": story_contexts[product_id]}
        compact_candidate_details.append(_compact_candidate_detail(product_info))

    certified_id_set = set(certified_product_ids)
    certified_rows = [
        row
        for row in rows
        if isinstance(row, dict) and _safe_int(row.get("product_id"), 0) in certified_id_set
    ]

    enriched = dict(query_result)
    enriched["rows"] = certified_rows
    enriched["row_count"] = len(certified_rows)
    enriched["candidate_product_ids"] = certified_product_ids
    enriched["candidate_details"] = compact_candidate_details
    enriched["candidate_detail_policy"] = (
        f"rows의 product_id를 최대 {MAX_QUERY_CANDIDATE_SCAN}개까지 확인해 "
        f"공개 작품 카드로 렌더링 가능한 후보 {MAX_QUERY_CANDIDATE_DETAILS}개까지 서버가 상세 보강했다. "
        "이 후보들 중 질문에 가장 가까운 작품을 모델이 선택한다. "
        "candidate_product_ids 밖의 작품은 최종 추천하지 않는다."
    )
    return enriched


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
        query_result = await _run_readonly_query(db, sql, adult_yn=adult_yn)
        return await _attach_query_candidate_details(db, query_result, adult_yn=adult_yn)

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
            include_story_context=True,
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
    query_terms = _extract_recommendation_query_terms(_latest_user_query(normalized_messages))

    session_state = _build_session_state(messages, context, combined_exclude)
    page_context = await _build_page_context(context, db)
    if page_context.get("source_action_id"):
        logger.info(
            "[ai_chat] followup_action_request source_action_id=%s source_action_intent=%s current_product_id=%s",
            page_context.get("source_action_id"),
            page_context.get("source_action_intent"),
            page_context.get("current_product_id"),
        )
    reader_context = await _build_reader_context(user_id, profile, db)
    system_prompt = _build_data_agent_system_prompt(
        adult_yn=normalized_adult,
        preset=normalized_preset,
        reader_context=reader_context,
        session_state=session_state,
        page_context=page_context,
    )

    if _is_current_product_overview_request(normalized_messages, page_context):
        return await _handle_current_product_overview_with_gemini(
            normalized_messages=normalized_messages,
            page_context=page_context,
            profile=profile,
            reader_context=reader_context,
            db=db,
            adult_yn=normalized_adult,
        )

    similar_payload = await _handle_similar_product_request(
        normalized_messages=normalized_messages,
        page_context=page_context,
        session_state=session_state,
        profile=profile,
        reader_context=reader_context,
        db=db,
        adult_yn=normalized_adult,
        exclude_ids=combined_exclude,
        query_terms=query_terms,
    )
    if similar_payload:
        return similar_payload

    model_messages = list(normalized_messages)
    latest_user_query = _latest_user_query(normalized_messages)
    exploration_state = session_state.get("exploration_state") or {}
    hard_constraints = exploration_state.get("hard") or {}
    required_status_codes = set(hard_constraints.get("status_codes") or _extract_required_status_codes(latest_user_query))
    allow_status_keyword_fallback = not _has_non_status_hard_constraints(exploration_state)
    last_text = ""
    last_query_rows: list[dict[str, Any]] = []
    all_query_rows: list[dict[str, Any]] = []
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
                model_messages=model_messages,
                reason=force_finalize_reason,
                allowed_tool_names=force_finalize_allowed_tool_names,
            )
            force_finalize_reason = None
            force_finalize_allowed_tool_names = None
        else:
            response = await _call_gemini_messages(
                system_prompt=system_prompt,
                messages=model_messages,
                tools=DATA_AGENT_RUNTIME_TOOLS,
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
                _append_assistant_text_message(model_messages, last_text)
                force_finalize_reason = (
                    "submit_final_recommendation 계약이 잘못됐습니다. "
                    "recommend/weak_recommend면 product_id를 반드시 넣고, no_match면 product_id를 null로 제출하세요."
                )
                force_finalize_allowed_tool_names = [FINAL_RESPONSE_TOOL_NAME]
                continue
            current_product_id = _resolve_conversation_product_id(page_context, session_state)
            current_overview_request = _is_current_product_overview_request(normalized_messages, page_context)
            if (
                _is_current_product_episode_detail_request(normalized_messages, current_product_id)
                and current_product_id > 0
                and current_product_id not in detail_cache
                and detail_calls < MAX_DETAIL_TOOL_CALLS
                and not forced_finalize_attempted
            ):
                logger.warning("[ai_chat] final tool skipped current product episode previews; requiring detail lookup")
                _append_assistant_text_message(model_messages, last_text)
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
                current_overview_request
                and current_product_id > 0
                and current_product_id not in detail_cache
                and detail_calls < MAX_DETAIL_TOOL_CALLS
                and not forced_finalize_attempted
            ):
                logger.warning("[ai_chat] final tool skipped current product info; requiring detail lookup")
                _append_assistant_text_message(model_messages, last_text)
                force_finalize_reason = (
                    f"현재 페이지 작품 ID {current_product_id}에 대한 질문입니다. "
                    f"get_product_info(product_id={current_product_id})를 먼저 호출한 뒤 "
                    "작품의 synopsis_text, premise, hook, episode_summary_text, 장르/키워드, 회차 수/연재주기를 근거로 답하세요. "
                    "현재 작품 자체를 묻는 질문이므로 유사 작품 비교 데이터가 없다는 이유로 no_match를 제출하지 마세요."
                )
                force_finalize_allowed_tool_names = ["get_product_info", FINAL_RESPONSE_TOOL_NAME]
                continue
            candidate_product_ids = _collect_candidate_product_ids(
                last_query_rows=all_query_rows or last_query_rows,
                detail_cache=detail_cache,
            )
            selected_product_id_invalid = False
            if (
                parsed_product_id is not None
                and candidate_product_ids
                and parsed_product_id not in candidate_product_ids
                and not _is_allowed_current_product_selection(
                    selected_product_id=parsed_product_id,
                    current_product_id=current_product_id,
                    current_overview_request=current_overview_request,
                )
            ):
                logger.warning(
                    "[ai_chat] final tool selected product outside candidates product_id=%s candidates=%s",
                    parsed_product_id,
                    candidate_product_ids,
                )
                if not forced_finalize_attempted:
                    _append_assistant_text_message(model_messages, last_text)
                    force_finalize_reason = (
                        f"제출한 product_id {parsed_product_id}는 확보한 후보 목록 {candidate_product_ids}에 없습니다. "
                        "반드시 이 후보 목록 안에서만 가장 가까운 작품을 고르거나, 모두 부적합하면 no_match로 제출하세요. "
                        "후보 밖 작품명이나 product_id를 새로 만들지 마세요."
                    )
                    force_finalize_allowed_tool_names = [FINAL_RESPONSE_TOOL_NAME]
                    continue
                selected_product_id_invalid = True
                parsed_product_id = None
                final_mode = "no_match"
            if _should_reask_final_with_product_id(
                final_tool_input=final_tool_input,
                detail_cache=detail_cache,
            ) and not forced_finalize_attempted:
                logger.warning("[ai_chat] final tool missing product_id after detail lookup; reasking finalize")
                _append_assistant_text_message(model_messages, last_text)
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
                _append_assistant_text_message(model_messages, last_text)
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
                query_terms=query_terms,
            )
            if not selected_from_current_product_context and selected_product_id is None:
                product, taste_match = await _attach_focus_product_card_if_needed(
                    product=product,
                    taste_match=taste_match,
                    page_context=page_context,
                    profile=profile,
                    db=db,
                    factor_scores=reader_context.get("factor_scores"),
                    adult_yn=normalized_adult,
            )
            if (
                product
                and required_status_codes
                and final_mode in {"recommend", "weak_recommend"}
                and not _candidate_matches_required_status(product, required_status_codes)
            ):
                matching_rows = _filter_candidate_rows_by_required_status(
                    all_query_rows or last_query_rows,
                    required_status_codes,
                )
                matching_candidate_ids = [
                    _safe_int(row.get("product_id"), 0)
                    for row in matching_rows[:5]
                    if isinstance(row, dict) and _safe_int(row.get("product_id"), 0) > 0
                ]
                logger.warning(
                    "[ai_chat] final product violates required status product_id=%s status=%s required=%s candidates=%s",
                    selected_product_id,
                    _candidate_status_code(product),
                    sorted(required_status_codes),
                    matching_candidate_ids,
                )
                if matching_candidate_ids and not forced_finalize_attempted:
                    _append_assistant_text_message(model_messages, last_text)
                    force_finalize_reason = (
                        f"사용자 질문의 명시 상태 조건({_status_constraint_label(required_status_codes)})을 "
                        f"product_id {selected_product_id}가 위반했습니다. "
                        f"상태 조건을 만족하는 후보 작품 ID {matching_candidate_ids} 중에서만 가장 가까운 작품 하나를 고르거나, "
                        "모두 부적합하면 no_match로 제출하세요. 상태 조건을 만족하지 않는 작품은 weak_recommend로도 제출하지 마세요."
                    )
                    force_finalize_allowed_tool_names = [FINAL_RESPONSE_TOOL_NAME]
                    continue
                selected_product_id_invalid = True
                selected_product_id = None
                product = None
                final_mode = "no_match"
            hard_violations = _product_hard_constraint_violations(product, exploration_state)
            if product and hard_violations and selected_product_id is not None:
                candidate_pool = list(detail_cache.values()) + (all_query_rows or last_query_rows)
                matching_rows = _filter_candidate_rows_by_hard_constraints(candidate_pool, exploration_state)
                matching_candidate_ids = [
                    _safe_int(row.get("product_id"), 0)
                    for row in matching_rows[:5]
                    if isinstance(row, dict) and _safe_int(row.get("product_id"), 0) > 0
                ]
                logger.warning(
                    "[ai_chat] final product violates hard constraints product_id=%s violations=%s candidates=%s",
                    selected_product_id,
                    hard_violations,
                    matching_candidate_ids,
                )
                if matching_candidate_ids and not forced_finalize_attempted:
                    _append_assistant_text_message(model_messages, last_text)
                    force_finalize_reason = (
                        f"product_id {selected_product_id}가 사용자 질문의 명시 조건"
                        f"({_hard_constraint_violation_label(hard_violations)})을 위반했습니다. "
                        f"명시 조건을 만족하는 후보 작품 ID {matching_candidate_ids} 중에서만 가장 가까운 작품 하나를 고르거나, "
                        "모두 부적합하면 no_match로 제출하세요. soft/weak 조건은 필터가 아니지만 hard 조건은 위반하지 마세요."
                    )
                    force_finalize_allowed_tool_names = [FINAL_RESPONSE_TOOL_NAME]
                    continue
                selected_product_id_invalid = True
                selected_product_id = None
                product = None
                final_mode = "no_match"
            if (
                selected_product_id is not None
                and final_mode in {"recommend", "weak_recommend"}
                and product is None
            ):
                logger.warning(
                    "[ai_chat] final tool selected product cannot be rendered product_id=%s",
                    selected_product_id,
                )
                if detail_cache and not forced_finalize_attempted:
                    _append_assistant_text_message(model_messages, last_text)
                    inspected_ids = sorted(detail_cache.keys())
                    force_finalize_reason = (
                        f"선택한 product_id {selected_product_id}는 공개 작품 카드로 확인되지 않습니다. "
                        f"이미 확인된 공개 후보 작품 ID {inspected_ids} 중 가장 가까운 작품 하나를 고르고 "
                        "weak_recommend 또는 recommend로 제출하세요. "
                        "공개 후보가 모두 부적합할 때만 no_match를 사용하세요."
                    )
                    force_finalize_allowed_tool_names = [FINAL_RESPONSE_TOOL_NAME]
                    continue
                selected_product_id_invalid = True
                selected_product_id = None
                final_mode = "no_match"
            raw_reply = "" if selected_product_id_invalid else str(final_tool_input.get("reply") or last_text or "").strip()
            if product:
                if final_mode == "no_match":
                    final_mode = "weak_recommend"
                if selected_from_current_product_context or (
                    current_overview_request
                    and selected_product_id == current_overview_product_id
                    and _has_comparison_failure_text(raw_reply)
                ):
                    reply = _limit_readable_reply(_build_focus_product_intro_reply(product))
                else:
                    reply = _normalize_product_reply(
                        raw_reply=raw_reply,
                        product=product,
                        unselected_candidate_titles=_collect_unselected_candidate_titles(
                            selected_product_id=selected_product_id,
                            last_query_rows=last_query_rows,
                            detail_cache=detail_cache,
                        ),
                    )
                product["matchReason"] = reply
            else:
                fallback_payload = (
                    await _build_status_keyword_fallback_recommendation(
                        latest_user_query=latest_user_query,
                        required_status_codes=required_status_codes,
                        query_terms=query_terms,
                        profile=profile,
                        db=db,
                        factor_scores=reader_context.get("factor_scores"),
                        adult_yn=normalized_adult,
                    )
                    if allow_status_keyword_fallback
                    else None
                )
                if fallback_payload:
                    return fallback_payload
                reply = _normalize_no_match_reply(raw_reply)

            if (
                product
                and current_overview_request
                and selected_product_id == current_overview_product_id
                and final_mode == "no_match"
            ):
                final_mode = "weak_recommend"

            raw_suggested_actions = final_tool_input.get("suggested_actions") or final_tool_input.get("suggestedActions")
            blocked_intents = _blocked_suggested_action_intents(page_context, latest_user_query)
            if product:
                suggested_actions = _normalize_suggested_actions(
                    product,
                    raw_suggested_actions,
                    blocked_intents=blocked_intents,
                )
            else:
                suggested_actions = _normalize_no_match_suggested_actions(
                    raw_suggested_actions,
                    blocked_intents=blocked_intents,
                )
                if final_mode == "no_match" and not suggested_actions and not forced_finalize_attempted:
                    _append_assistant_text_message(model_messages, last_text)
                    force_finalize_reason = (
                        "no_match 최종 응답에도 suggested_actions를 3개 또는 4개 포함해야 합니다. "
                        "작품 카드를 억지로 만들지 말고, 사용자가 조건을 좁히거나 넓힐 수 있는 한국어 후속질문만 제출하세요."
                    )
                    force_finalize_allowed_tool_names = [FINAL_RESPONSE_TOOL_NAME]
                    continue
                if final_mode == "no_match" and not suggested_actions:
                    suggested_actions = await _generate_no_match_suggested_actions(
                        latest_user_query=latest_user_query,
                        reply=reply,
                        blocked_intents=blocked_intents,
                    )
            _log_suggested_actions(
                product_id=selected_product_id,
                final_mode=final_mode,
                page_context=page_context,
                suggested_actions=suggested_actions,
            )
            return {
                "reply": reply,
                "product": product,
                "taste_match": taste_match,
                "tasteMatch": taste_match,
                "suggestedActions": suggested_actions,
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
                    query_terms=query_terms,
                )
                hard_violations = _product_hard_constraint_violations(product, exploration_state)
                if product and hard_violations and selected_product_id is not None:
                    logger.warning(
                        "[ai_chat] parsed final product violates hard constraints product_id=%s violations=%s",
                        selected_product_id,
                        hard_violations,
                    )
                    product = None
                    selected_product_id = None
                    final_mode = "no_match"
                    reply = ""
                if product:
                    if final_mode == "no_match":
                        final_mode = "weak_recommend"
                    reply = _normalize_product_reply(
                        raw_reply=reply,
                        product=product,
                        unselected_candidate_titles=_collect_unselected_candidate_titles(
                            selected_product_id=selected_product_id,
                            last_query_rows=last_query_rows,
                            detail_cache=detail_cache,
                        ),
                    )
                    product["matchReason"] = reply
                else:
                    final_mode = "no_match"
                    fallback_payload = (
                        await _build_status_keyword_fallback_recommendation(
                            latest_user_query=latest_user_query,
                            required_status_codes=required_status_codes,
                            query_terms=query_terms,
                            profile=profile,
                            db=db,
                            factor_scores=reader_context.get("factor_scores"),
                            adult_yn=normalized_adult,
                        )
                        if allow_status_keyword_fallback
                        else None
                    )
                    if fallback_payload:
                        return fallback_payload
                    reply = _normalize_no_match_reply(reply)
                if product:
                    suggested_actions = _normalize_suggested_actions(
                        product,
                        None,
                        blocked_intents=_blocked_suggested_action_intents(page_context, latest_user_query),
                    )
                else:
                    suggested_actions = await _generate_no_match_suggested_actions(
                        latest_user_query=latest_user_query,
                        reply=reply,
                        blocked_intents=_blocked_suggested_action_intents(page_context, latest_user_query),
                    )
                _log_suggested_actions(
                    product_id=selected_product_id,
                    final_mode=final_mode,
                    page_context=page_context,
                    suggested_actions=suggested_actions,
                )
                return {
                    "reply": reply,
                    "product": product,
                    "taste_match": taste_match,
                    "tasteMatch": taste_match,
                    "suggestedActions": suggested_actions,
                    "finalMode": final_mode,
                }

            logger.warning("[ai_chat] finalize_missing_tool last_text=%s", last_text[:300])
            model_messages.append({"role": "assistant", "content": content})
            force_finalize_reason = "일반 텍스트 응답이 왔지만 submit_final_recommendation이 제출되지 않았습니다."
            continue

        model_messages.append({"role": "assistant", "content": content})
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
                all_query_rows = _merge_candidate_rows(all_query_rows, last_query_rows)
                for candidate_detail in tool_result.get("candidate_details") or []:
                    if not isinstance(candidate_detail, dict):
                        continue
                    product_id = _safe_int(candidate_detail.get("product_id"), 0)
                    if product_id > 0:
                        detail_cache[product_id] = candidate_detail
            if tool_name == "get_product_info" and isinstance(tool_result, dict):
                product_id = _safe_int(tool_result.get("product_id"), 0)
                if product_id > 0:
                    detail_cache[product_id] = tool_result
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.get("id"),
                    "name": tool_name,
                    "content": json.dumps(_to_json_safe(tool_result), ensure_ascii=False),
                }
            )

        model_messages.append({"role": "user", "content": tool_results})

    logger.warning(
        "[ai_chat] finalize_missing query_calls=%s detail_calls=%s forced_finalize_attempted=%s last_query_rows=%s",
        query_calls,
        detail_calls,
        forced_finalize_attempted,
        len(last_query_rows),
    )
    forced_response = await _force_finalize_response(
        system_prompt=system_prompt,
        model_messages=model_messages,
        reason="도구 호출 한도에 도달했거나 최종 제출 없이 루프가 종료되었습니다.",
    )
    forced_content = forced_response.get("content") or []
    forced_text = _extract_text(forced_content)
    forced_tool_input = _extract_final_tool_input(_extract_tool_use_blocks(forced_content))
    if forced_tool_input is not None:
        reply_text = str(forced_tool_input.get("reply") or forced_text or "").strip()
        selected_product_id = _safe_int(forced_tool_input.get("product_id"), 0) or None
        final_mode = _normalize_final_mode(forced_tool_input.get("mode"), selected_product_id)
        candidate_product_ids = _collect_candidate_product_ids(
            last_query_rows=all_query_rows or last_query_rows,
            detail_cache=detail_cache,
        )
        current_product_id = _resolve_conversation_product_id(page_context, session_state)
        current_overview_request = _is_current_product_overview_request(normalized_messages, page_context)
        if (
            selected_product_id is not None
            and candidate_product_ids
            and selected_product_id not in candidate_product_ids
            and not _is_allowed_current_product_selection(
                selected_product_id=selected_product_id,
                current_product_id=current_product_id,
                current_overview_request=current_overview_request,
            )
        ):
            logger.warning(
                "[ai_chat] forced final selected product outside candidates product_id=%s candidates=%s",
                selected_product_id,
                candidate_product_ids,
            )
            selected_product_id = None
            final_mode = "no_match"
            reply_text = ""
        product, taste_match = await _build_product_and_taste(
            selected_product_id=selected_product_id,
            last_search_candidates=[],
            profile=profile,
            db=db,
            factor_scores=reader_context.get("factor_scores"),
            adult_yn=normalized_adult,
            fallback_to_search=False,
            prefetched_product_info=detail_cache.get(selected_product_id) if selected_product_id else None,
            query_terms=query_terms,
        )
        if (
            selected_product_id is not None
            and final_mode in {"recommend", "weak_recommend"}
            and product is None
        ):
            logger.warning(
                "[ai_chat] forced final selected product cannot be rendered product_id=%s",
                selected_product_id,
            )
            selected_product_id = None
            final_mode = "no_match"
            reply_text = ""
        if (
            product
            and required_status_codes
            and final_mode in {"recommend", "weak_recommend"}
            and not _candidate_matches_required_status(product, required_status_codes)
        ):
            logger.warning(
                "[ai_chat] forced final product violates required status product_id=%s status=%s required=%s",
                selected_product_id,
                _candidate_status_code(product),
                sorted(required_status_codes),
            )
            selected_product_id = None
            product = None
            final_mode = "no_match"
            reply_text = ""
        hard_violations = _product_hard_constraint_violations(product, exploration_state)
        if product and hard_violations and selected_product_id is not None:
            logger.warning(
                "[ai_chat] forced final product violates hard constraints product_id=%s violations=%s",
                selected_product_id,
                hard_violations,
            )
            selected_product_id = None
            product = None
            final_mode = "no_match"
            reply_text = ""
        if product:
            if final_mode == "no_match":
                final_mode = "weak_recommend"
            reply = _normalize_product_reply(
                raw_reply=reply_text,
                product=product,
                unselected_candidate_titles=_collect_unselected_candidate_titles(
                    selected_product_id=selected_product_id,
                    last_query_rows=last_query_rows,
                    detail_cache=detail_cache,
                ),
            )
            product["matchReason"] = reply
        else:
            final_mode = "no_match"
            fallback_payload = (
                await _build_status_keyword_fallback_recommendation(
                    latest_user_query=latest_user_query,
                    required_status_codes=required_status_codes,
                    query_terms=query_terms,
                    profile=profile,
                    db=db,
                    factor_scores=reader_context.get("factor_scores"),
                    adult_yn=normalized_adult,
                )
                if allow_status_keyword_fallback
                else None
            )
            if fallback_payload:
                return fallback_payload
            reply = _normalize_no_match_reply(reply_text)
        raw_suggested_actions = forced_tool_input.get("suggested_actions") or forced_tool_input.get("suggestedActions")
        blocked_intents = _blocked_suggested_action_intents(page_context, latest_user_query)
        if product:
            suggested_actions = _normalize_suggested_actions(
                product,
                raw_suggested_actions,
                blocked_intents=blocked_intents,
            )
        else:
            suggested_actions = _normalize_no_match_suggested_actions(
                raw_suggested_actions,
                blocked_intents=blocked_intents,
            )
            if final_mode == "no_match" and not suggested_actions:
                suggested_actions = await _generate_no_match_suggested_actions(
                    latest_user_query=latest_user_query,
                    reply=reply,
                    blocked_intents=blocked_intents,
                )
        _log_suggested_actions(
            product_id=selected_product_id,
            final_mode=final_mode,
            page_context=page_context,
            suggested_actions=suggested_actions,
        )
        return {
            "reply": reply,
            "product": product,
            "taste_match": taste_match,
            "tasteMatch": taste_match,
            "suggestedActions": suggested_actions,
            "finalMode": final_mode,
        }

    final_reply, _, final_mode = _parse_final_payload(forced_text or last_text)
    final_reply = _normalize_no_match_reply(forced_text or final_reply or last_text)
    suggested_actions = await _generate_no_match_suggested_actions(
        latest_user_query=latest_user_query,
        reply=final_reply,
        blocked_intents=_blocked_suggested_action_intents(page_context, latest_user_query),
    )
    return {
        "reply": final_reply,
        "product": None,
        "taste_match": {"protagonist": 0, "mood": 0, "pacing": 0},
        "tasteMatch": {"protagonist": 0, "mood": 0, "pacing": 0},
        "suggestedActions": suggested_actions,
        "finalMode": "no_match",
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
    suggested_actions = assistant_result.get("suggestedActions")

    product_id = None
    product_snapshot = None
    if isinstance(product, dict) and product.get("productId"):
        product_id = product["productId"]
        product_snapshot_payload = dict(product)
        if (
            isinstance(suggested_actions, list)
            and MIN_SUGGESTED_ACTIONS <= len(suggested_actions) <= MAX_SUGGESTED_ACTIONS
        ):
            product_snapshot_payload[SUGGESTED_ACTION_SNAPSHOT_KEY] = suggested_actions
        product_snapshot = json.dumps(product_snapshot_payload, ensure_ascii=False)

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
            if isinstance(snapshot, dict):
                suggested_actions = snapshot.pop(SUGGESTED_ACTION_SNAPSHOT_KEY, None)
                if (
                    isinstance(suggested_actions, list)
                    and MIN_SUGGESTED_ACTIONS <= len(suggested_actions) <= MAX_SUGGESTED_ACTIONS
                ):
                    msg["suggestedActions"] = suggested_actions
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
