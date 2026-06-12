#!/usr/bin/env python3
"""
작품 AI 메타 추출 배치 스크립트.

정책:
- 1~10화 본문 기반 분석 (최대 60,000자)
- 3화 미만 작품은 fail-closed (추천풀 제외)
- 허용 라벨(SSOT JSON) 외 값 저장 금지
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx
import pymysql
from pymysql.constants import CLIENT

# DB 접속 (컨테이너: mysql:3306 / 로컬: SSH 터널 127.0.0.1:13306)
DB_HOST = os.getenv("BATCH_DB_HOST", "mysql")
DB_PORT = int(os.getenv("BATCH_DB_PORT", "3306"))
DB_USER = os.getenv("BATCH_DB_USER", "")
DB_PASSWORD = os.getenv("BATCH_DB_PASSWORD", "")
DB_NAME = os.getenv("BATCH_DB_NAME", "likenovel")

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# DNA LLM provider switch.
# Default stays Anthropic so an env rollback restores the previous behavior.
AI_DNA_PROVIDER = os.getenv("AI_DNA_PROVIDER", "anthropic").strip().lower()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
AI_DNA_OPENROUTER_MODEL = os.getenv("AI_DNA_OPENROUTER_MODEL", "deepseek/deepseek-v3.2").strip()
AI_DNA_OPENROUTER_PROVIDER_ONLY = os.getenv("AI_DNA_OPENROUTER_PROVIDER_ONLY", "friendli").strip()
# OpenRouter reasoning(thinking) 제어. 비어있으면 미전송(기존 동작 유지).
# "low"/"medium"/"high" → {"effort": ...}, "enabled"/"on"/"true"/"1" → {"enabled": true}
AI_DNA_OPENROUTER_REASONING = os.getenv("AI_DNA_OPENROUTER_REASONING", "").strip().lower()
AI_DNA_RESPONSE_FORMAT = os.getenv("AI_DNA_RESPONSE_FORMAT", "json_schema").strip().lower()
AI_DNA_TIMEOUT_SECONDS = float(os.getenv("AI_DNA_TIMEOUT_SECONDS", "120.0"))
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
AI_DNA_DEEPSEEK_FALLBACK_MODEL = os.getenv("AI_DNA_DEEPSEEK_FALLBACK_MODEL", "deepseek-v4-flash").strip()

MAX_RETRY_COUNT = 2  # 초기 1회 + 재시도 2회
MAX_ANALYZE_EPISODES = 10
MAX_ANALYZE_CHARS = 60000
MAX_LLM_OUTPUT_TOKENS = int(os.getenv("AI_METADATA_MAX_TOKENS", "4096"))
MIN_REQUIRED_EPISODES = 3
MIN_FIRST_EPISODE_TEXT_COUNT = 1000
FAILED_RETRY_COOLDOWN_DAYS = int(os.getenv("AI_METADATA_FAILED_RETRY_COOLDOWN_DAYS", "3"))
INCOMPLETE_RETRY_COOLDOWN_DAYS = int(os.getenv("AI_METADATA_INCOMPLETE_RETRY_COOLDOWN_DAYS", "3"))
ANALYSIS_PIPELINE_VERSION = os.getenv("AI_METADATA_PIPELINE_VERSION", "dna-v20260611-r2")
UNSUPPORTED_LABEL_ERROR_PREFIX = "unsupported_label:"

AXIS_ORDER = ("세", "직", "능", "연", "작", "타", "목")
# min은 전 축 0 — 부합 라벨이 없으면 빈 배열이 정답(근접 라벨 강제 매핑 금지)
AXIS_LIMITS: dict[str, tuple[int, int]] = {
    "세": (0, 3),
    "직": (0, 2),
    "능": (0, 4),
    "연": (0, 2),
    "작": (0, 3),
    "타": (0, 3),
    "목": (0, 1),
}
ALLOWED_HEROINE_WEIGHT = {"high", "mid", "low", "none"}
ALLOWED_PACING = {"fast", "medium", "slow"}
OPENROUTER_ALLOWED_FINISH_REASONS = {"stop"}

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
LABELS_JSON_CANDIDATES = [
    SCRIPT_DIR / "allowed-labels-by-axis.json",  # 서버 배치 디렉토리
    ROOT_DIR / "ai" / "allowed-labels-by-axis.json",  # 컨테이너: /app/dist/ai/
    ROOT_DIR / "docs" / "ai-codebook" / "allowed-labels-by-axis.json",  # 로컬 프로젝트 루트
    ROOT_DIR
    / "likenovel-service-api"
    / "likenovel-service-api"
    / "fastapi_be_server"
    / "dist"
    / "ai"
    / "allowed-labels-by-axis.json",
]
LABEL_DEFS_JSON_CANDIDATES = [
    SCRIPT_DIR / "label-definitions-by-axis.json",  # 서버 배치 디렉토리
    ROOT_DIR / "ai" / "label-definitions-by-axis.json",  # 컨테이너: /app/dist/ai/
    ROOT_DIR / "docs" / "ai-codebook" / "label-definitions-by-axis.json",
    ROOT_DIR
    / "likenovel-service-api"
    / "likenovel-service-api"
    / "fastapi_be_server"
    / "dist"
    / "ai"
    / "label-definitions-by-axis.json",
]

DNA_SYSTEM_PROMPT = """너는 라이크노벨 내부 메타 추출기 LN_AXIS_EXTRACTOR_V1이다.
입력된 정보(작품정보 + 도입부 회차 본문)를 읽고 작품 신호와 설명 메타를 추출한다.
출력은 반드시 JSON 단일 객체만 허용한다. 설명문, 마크다운, 코드블록 금지.

핵심 규칙:
1) 허용 라벨 목록 외 신규 라벨 생성 금지.
1-1) 각 라벨의 의미는 "라벨 정의" 섹션을 참고하여 판단한다. 이름만으로 추측하지 않는다.
1-2) 라벨은 상호배타 장르 분류가 아니라 AI추천구좌와 AI사서에서 작품을 엮는 작품 신호다.
1-2-1) 내부 그룹 키 의미는 다음과 같다. 세=무대, 세계관, 기관, 세력, 반복 배경, 직=직업, 직위, 사회적 역할, 전투 클래스, 능=능력, 시스템 메커니즘, 전투·성장 도구, 연=히로인·관계·애정 구도 신호, 작=작풍·정서·전개감·서사 질감, 타=주인공 상태, 서사 포지션, 핵심 세력과 속성, 목=반복 목표, 메인 루프, 주된 활동.
1-3) 주인공, 핵심 인물, 핵심 세력, 반복 소재, 갈등 축, 주요 배경이 강하게 연결되면 같은 작품에 여러 라벨을 동시에 부여한다.
1-4) 문파, 세력, 공간 라벨은 주인공 소속으로만 한정하지 않는다. 단순 언급이나 스쳐 지나가는 배경만으로는 선택하지 않는다.
1-4-1) 단순 언급, 비유 표현, 지나가는 배경, 1회성 몬스터, 직업, 장소, 농담성 대사만으로는 라벨을 선택하지 않는다.
1-5) 조합 라벨을 새로 만들지 않는다. 예: "아카데미빙의" 대신 "아카데미"와 "빙의"를 각각 선택한다.
1-6) 라벨 배열은 강한 근거 순서로 정렬한다. 제목, 태그, 줄거리, 초반 회차에서 반복되거나 갈등·목표·배경에 직접 연결된 라벨을 앞에 둔다.
1-6-1) 최대 개수를 채우려 하지 않는다. 두 번째 이후 라벨은 제목, 태그, 줄거리, 초반 회차에서 독립 근거가 확인될 때만 선택한다.
1-6-2) 시대 배경 라벨과 기관, 세력, 반복 공간 라벨은 서로 대체하지 않는다. 중세 세계에서 전사 아카데미 입학이 초반 목표라면 중세와 아카데미를 함께 선택한다.
1-7) 근거가 약하면 라벨을 선택하지 않는다. 어떤 그룹이든 부합하는 허용 라벨이 없으면 빈 배열로 둔다. 가장 가까운 라벨로 대체하지 않는다.
1-7-1) 상태창은 스탯, 스킬, 업적을 보여주는 정보 창이고, 시스템은 퀘스트·보상·페널티·상점·레벨업을 집행하는 메커니즘이다. 정보 표시만 있으면 상태창만 선택한다.
1-7-2) 회귀는 과거 특정 시점으로 돌아오는 1회성 또는 제한적 인생 재시작, 무한회귀는 실패 때마다 반복 재시도, 루프는 특정 사건·하루·구간 반복, 빙의는 타인의 몸이나 작품 속 인물 신분, 환생은 새 육체와 생애, 귀환자는 장기 생존 후 원래 세계 복귀, 차원이동은 살아 있는 상태의 세계 이동으로 구분한다.
1-7-3) 아카데미는 특수능력 교육기관, 학원은 현대 학교생활, 청춘, 교우관계, 학교는 물리적 학교 공간 사건이 중심일 때만 선택한다.
1-7-4) 하렘은 복수의 이성 캐릭터가 명확한 애정, 소유욕, 관계 긴장을 보일 때만, 조력자는 단순 도움 제공이 아니라 동등한 파트너십과 반복 동행이 작품 매력일 때만 선택한다.
1-7-5) 직 라벨은 실제 직업, 신분, 역할, 전투 클래스가 직접 확인될 때만 선택한다. 세계를 구하거나 사람을 구하는 목표만으로 소방관, 의사, 경찰 같은 직업을 추정하지 않는다.
1-7-6) 아카데미 입학, 편입, 선발시험, 평가전, 수련, 교사, 교수, 교관 활동이 초반 목표나 반복 사건이면 물리적 캠퍼스 장면이 적어도 아카데미를 선택한다.
2) 목표 라벨 그룹(목)은 최대 1개. 라벨 정의를 참고하여 작품의 핵심 목표에 가장 부합하는 라벨을 선택하고, 부합하는 허용 라벨이 없으면 빈 배열로 두고 unmapped_concepts에 기록한다.
3) 관계와 케미 라벨 그룹(연)은 연애와 케미가 드러날 때만 선택 가능. 없으면 빈 배열 가능.
4) confidence는 0~1 범위 숫자.
5) summary의 모든 필드를 빈 값 없이 채운다. null 금지. themes와 taste_tags도 각각 1개 이상.
6) heroine이 없는 작품은 heroine_type에 주요 여성 캐릭터를 기재하고, heroine_weight는 "none"으로 설정한다.
7) 출력 JSON 스키마를 정확히 지킨다. axis_* 이름은 저장용 내부 키이며 판단 기준은 작품 신호와 작품 연결 라벨이다.
8) axis_label_scores는 작품 연결 라벨별 확신도 목록으로 작성하고 각 score는 0~1 범위 숫자다.
9) evidence는 작품 신호를 선택한 회차 근거 중심으로 짧게 작성한다.
10) summary.premise는 핵심 설정이다. 작품을 움직이는 기본 전제, 규칙, 상황을 구체적으로 쓴다.
11) summary.hook은 초반 진입 포인트다. 광고 카피가 아니라 초반 1~3화에서 독자가 다음 화를 누르게 되는 구체적 사건, 위기, 목표, 반전, 보상 약속을 쓴다.
12) summary.hook에 "흥미진진한", "몰입감 있는", "기대되는" 같은 추상 홍보문구, 장르와 라벨 나열, 본문에 없는 기대감 생성을 쓰지 않는다.
13) 작품의 핵심 반복 개념(주인공 직업, 능력, 소재, 상태)이 허용 라벨에 없으면 근처 라벨로 대체하지 말고 unmapped_concepts 배열에 원문 표현 그대로 기록한다. 최대 5개, 없으면 빈 배열.
"""

DNA_USER_TEMPLATE = """아래 작품 정보를 분석하여 JSON으로 응답하세요.

작품명: {title}
장르: {genres}
태그: {keywords}
줄거리: {synopsis_text}
회차수: {episode_count}화
연재상태: {status_code}
분석요청 회차수: {n_requested}
실제 분석 회차수: {n_received}

허용 작품 연결 라벨(내부 그룹 키 SSOT JSON):
{allowed_labels_json}

라벨 정의(작품 신호 판정 기준):
{label_definitions_text}

분석 회차 본문:
{episodes_text}

반드시 아래 JSON 스키마로만 응답:
{{
  "summary": {{
    "protagonist_type": "string",
    "protagonist_desc": "string",
    "heroine_type": "string",
    "heroine_weight": "high|mid|low|none",
    "mood": "string",
    "pacing": "fast|medium|slow",
    "premise": "string",
    "hook": "string",
    "themes": ["string"],
    "taste_tags": ["string"]
  }},
  "axis_labels": {{
    "세": ["string"],
    "직": ["string"],
    "능": ["string"],
    "연": ["string"],
    "작": ["string"],
    "타": ["string"],
    "목": ["string"]
  }},
  "axis_confidence": {{
    "세": 0.0,
    "직": 0.0,
    "능": 0.0,
    "연": 0.0,
    "작": 0.0,
    "타": 0.0,
    "목": 0.0
  }},
  "axis_label_scores": {{
    "세": [{{"label": "string", "score": 0.0}}],
    "직": [{{"label": "string", "score": 0.0}}],
    "능": [{{"label": "string", "score": 0.0}}],
    "연": [{{"label": "string", "score": 0.0}}],
    "작": [{{"label": "string", "score": 0.0}}],
    "타": [{{"label": "string", "score": 0.0}}],
    "목": [{{"label": "string", "score": 0.0}}]
  }},
  "overall_confidence": 0.0,
  "evidence": {{
    "세": ["string"],
    "직": ["string"],
    "능": ["string"],
    "연": ["string"],
    "작": ["string"],
    "타": ["string"],
    "목": ["string"]
  }},
  "unmapped_concepts": ["string"]
}}"""

DNA_REPAIR_TEMPLATE = """아래는 1차 분석 결과 JSON이다.
이 JSON에는 허용되지 않은 라벨이 포함되어 있어 저장할 수 없다.

작품명: {title}
문제 축: {axis}
문제 라벨: {label}

허용 라벨(축별 SSOT JSON):
{allowed_labels_json}

라벨 정의(분류 기준):
{label_definitions_text}

기존 JSON:
{raw_payload_json}

수정 규칙:
1) 허용 라벨 목록 외 값은 절대 사용하지 않는다.
2) axis_labels의 정상 라벨은 최대한 유지한다.
3) 문제 축과 문제 라벨을 교정한다. 부합하는 허용 라벨이 없으면 해당 축을 빈 배열로 둔다.
4) goal(목) 축은 최대 1개만 남긴다.
5) 전체 출력은 반드시 JSON 단일 객체만 반환한다.
6) 설명문, 코드블록, 주석 금지.
"""


class UnsupportedLabelError(ValueError):
    def __init__(self, axis: str, label: str):
        self.axis = axis
        self.label = label
        super().__init__(f"axis_labels.{axis} contains unsupported label: {label}")


def db_connect():
    if not DB_USER or not DB_PASSWORD:
        raise RuntimeError("BATCH_DB_USER/BATCH_DB_PASSWORD 환경변수를 설정하세요.")
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        autocommit=True,
        client_flag=CLIENT.MULTI_STATEMENTS,
        cursorclass=pymysql.cursors.DictCursor,
    )


def get_products(conn, product_id: int | None = None, force: bool = False):
    """분석 대상 작품 목록 조회."""
    with conn.cursor() as cur:
        params: list[Any] = []
        where = f"""
            p.open_yn = 'Y'
            AND COALESCE(p.blind_yn, 'N') = 'N'
            AND COALESCE(u.role_type, 'normal') != 'admin'
            AND COALESCE(TRIM(p.author_name), '') != ''
            AND EXISTS (
                SELECT 1
                FROM tb_product_episode fe
                WHERE fe.product_id = p.product_id
                  AND fe.episode_no = 1
                  AND fe.use_yn = 'Y'
                  AND fe.open_yn = 'Y'
                  AND fe.episode_text_count >= {MIN_FIRST_EPISODE_TEXT_COUNT}
            )
            AND (
                SELECT COUNT(*)
                FROM tb_product_episode e
                WHERE e.product_id = p.product_id
                  AND e.use_yn = 'Y'
                  AND e.open_yn = 'Y'
            ) >= 3
        """
        if product_id:
            where += " AND p.product_id = %s"
            params.append(product_id)
        if not force:
            where += f"""
            AND (
                m.id IS NULL
                OR (
                    COALESCE(m.analysis_status, 'pending') = 'failed'
                    AND COALESCE(m.analysis_error_message, '') NOT LIKE %s
                    AND COALESCE(m.updated_date, m.created_date, '1970-01-01 00:00:00')
                        < DATE_SUB(NOW(), INTERVAL {FAILED_RETRY_COOLDOWN_DAYS} DAY)
                )
                OR (
                    COALESCE(m.analysis_status, 'pending') != 'failed'
                    AND m.analyzed_at IS NULL
                )
                OR (
                    COALESCE(m.analysis_status, 'pending') = 'success'
                    AND EXISTS (
                        SELECT 1
                        FROM tb_product_episode le
                        WHERE le.product_id = p.product_id
                          AND le.episode_no = {MAX_ANALYZE_EPISODES}
                          AND le.use_yn = 'Y'
                          AND le.open_yn = 'Y'
                          AND le.updated_date > m.analyzed_at
                    )
                )
            )
            """  # 미분석 즉시, 실패는 cooldown 뒤, 10화 공개/수정 시 최종 1회 재분석
            params.append(f"{UNSUPPORTED_LABEL_ERROR_PREFIX}%")

        cur.execute(
            f"""
            SELECT
                p.product_id, p.title, p.status_code, p.count_hit,
                p.price_type, p.author_name AS author_nickname,
                (SELECT CONCAT_WS('/', pg.keyword_name, sg.keyword_name)
                 FROM tb_standard_keyword pg
                 LEFT JOIN tb_standard_keyword sg ON sg.keyword_id = p.sub_genre_id AND sg.use_yn = 'Y'
                 WHERE pg.keyword_id = p.primary_genre_id AND pg.use_yn = 'Y'
                ) AS genres,
                (SELECT GROUP_CONCAT(DISTINCT sk.keyword_name SEPARATOR ', ')
                 FROM tb_mapped_product_keyword mpk
                 LEFT JOIN tb_standard_keyword sk ON sk.keyword_id = mpk.keyword_id
                 WHERE mpk.product_id = p.product_id) AS keywords,
                p.synopsis_text,
                (SELECT COUNT(*)
                 FROM tb_product_episode e
                 WHERE e.product_id = p.product_id
                   AND e.use_yn = 'Y'
                   AND e.open_yn = 'Y') AS episode_count
            FROM tb_product p
            LEFT JOIN tb_user u ON u.user_id = p.user_id
            LEFT JOIN tb_product_ai_metadata m ON m.product_id = p.product_id
            WHERE {where}
            ORDER BY p.count_hit DESC
        """,
            params,
        )
        return cur.fetchall()


def get_episodes(conn, product_id: int) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                episode_no,
                episode_title,
                episode_content
            FROM tb_product_episode
            WHERE product_id = %s
              AND use_yn = 'Y'
              AND open_yn = 'Y'
            ORDER BY episode_no ASC
            LIMIT %s
            """,
            (product_id, MAX_ANALYZE_EPISODES),
        )
        return cur.fetchall()


def _strip_html(content: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", content or "")
    return re.sub(r"\s+", " ", no_tags).strip()


def _build_episode_context(episodes: list[dict[str, Any]]) -> tuple[str, int]:
    chunks: list[str] = []
    total_chars = 0
    used_count = 0
    for episode in episodes:
        episode_no = int(episode.get("episode_no") or 0)
        episode_title = (episode.get("episode_title") or "").strip()
        episode_text = _strip_html(episode.get("episode_content") or "")
        if not episode_text:
            continue

        marker = f"[EP{episode_no:02d}] {episode_title}".strip()
        room = MAX_ANALYZE_CHARS - total_chars
        if room <= len(marker) + 4:
            break
        truncated = episode_text[: room - len(marker) - 4]
        block = f"{marker}\n{truncated}"
        chunks.append(block)
        total_chars += len(block)
        used_count += 1
    return "\n\n".join(chunks), used_count


def _safe_text(value: Any, field_name: str, max_length: int, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be string")
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"{field_name} is required")
    if not normalized:
        return None
    return normalized[:max_length]


def _safe_enum(value: Any, field_name: str, allowed: set[str], required: bool = False) -> str | None:
    normalized = _safe_text(value, field_name, 50, required=required)
    if normalized is None:
        return None
    if normalized not in allowed:
        raise ValueError(f"{field_name} must be one of {sorted(allowed)}")
    return normalized


def _safe_confidence(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    try:
        casted = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be number")
    if casted < 0 or casted > 1:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return round(casted, 4)


def _safe_list(value: Any, field_name: str, max_items: int = 15, max_item_length: int = 100) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be list")

    normalized_items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} item must be string")
        stripped = item.strip()
        if not stripped:
            continue
        normalized_items.append(stripped[:max_item_length])
        if len(normalized_items) >= max_items:
            break
    return list(dict.fromkeys(normalized_items))


def _flatten_text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.extend(_flatten_text_values(item))
        return parts
    if isinstance(value, dict):
        parts: list[str] = []
        for item in value.values():
            parts.extend(_flatten_text_values(item))
        return parts
    return []


def _payload_evidence_text(payload: dict[str, Any], source_text: str = "") -> str:
    parts = [source_text]
    summary = payload.get("summary")
    if isinstance(summary, dict):
        parts.extend(_flatten_text_values(summary))
    evidence = payload.get("evidence")
    if isinstance(evidence, dict):
        parts.extend(_flatten_text_values(evidence))
    return "\n".join(part for part in parts if part)


def _has_academy_evidence(text: str) -> bool:
    if "아카데미" not in text:
        return False
    return any(
        marker in text
        for marker in (
            "입학",
            "편입",
            "선발시험",
            "평가전",
            "강의",
            "수련",
            "교사",
            "교수",
            "교관",
            "아카데미생",
            "아카데미 학생",
            "아카데미 파티",
            "전사 아카데미",
            "마법 아카데미",
        )
    )


def _has_status_window_evidence(text: str) -> bool:
    negative_markers = ("상태창이나 시스템은 없", "상태창은 없", "상태창 없음")
    if any(marker in text for marker in negative_markers):
        return False
    return any(
        marker in text
        for marker in ("상태창", "스탯", "능력치", "업적", "눈앞 UI", "정보 인터페이스")
    )


def _has_buff_evidence(text: str) -> bool:
    return "버프" in text or ("계약" in text and any(marker in text for marker in ("힘을 얻", "강화", "능력")))


def _has_possession_evidence(text: str) -> bool:
    negative_markers = ("시스템이 빙의", "프로그램이 설치", "빙의한 형태")
    if any(marker in text for marker in negative_markers):
        return False
    return any(
        marker in text
        for marker in (
            "몸에 빙의",
            "몸으로 빙의",
            "몸에 들어",
            "몸으로 들어",
            "빙의해",
            "빙의한",
            "빙의되",
            "빙의한다",
            "소설 속",
            "작품 속",
            "게임 속",
            "타인의 몸",
            "남의 몸",
            "다른 사람의 몸",
        )
    )


def _has_growth_evidence(text: str) -> bool:
    return any(marker in text for marker in ("성장", "데뷔", "훈련", "수련", "레벨업", "퀘스트", "목표"))


def _has_monster_hunter_evidence(text: str) -> bool:
    return any(marker in text for marker in ("괴물사냥꾼", "괴물 사냥", "괴물을 사냥", "몬스터 사냥"))


def _apply_axis_label_evidence_guards(
    axis_labels: dict[str, list[str]],
    allowed_labels: dict[str, set[str]],
    source_text: str = "",
) -> dict[str, list[str]]:
    if not source_text:
        return axis_labels

    guarded = {axis: list(labels) for axis, labels in axis_labels.items()}

    firefighter_markers = ("소방서", "화재", "구급", "119", "구조 출동", "재난 현장", "소방 공무원", "소방대")
    if "소방관" in guarded["직"] and not any(marker in source_text for marker in firefighter_markers):
        guarded["직"] = [label for label in guarded["직"] if label != "소방관"]

    knight_negative_markers = (
        "자신은 기사가 아님",
        "주인공은 기사가 아님",
        "로머 자신은 기사가 아님",
        "주인공의 아버지가 기사",
        "아버지가 기사",
    )
    if "기사" in guarded["직"] and any(marker in source_text for marker in knight_negative_markers):
        guarded["직"] = [label for label in guarded["직"] if label != "기사"]
        if "헌터" in allowed_labels["직"] and "헌터" not in guarded["직"] and _has_monster_hunter_evidence(source_text):
            guarded["직"].append("헌터")

    if "상태창" in guarded["능"] and not _has_status_window_evidence(source_text):
        guarded["능"] = [label for label in guarded["능"] if label != "상태창"]
        if "버프" in allowed_labels["능"] and "버프" not in guarded["능"] and _has_buff_evidence(source_text):
            guarded["능"].append("버프")

    if "빙의" in guarded["타"] and not _has_possession_evidence(source_text):
        guarded["타"] = [label for label in guarded["타"] if label != "빙의"]
        if not guarded["타"] and "성장형" in allowed_labels["타"] and _has_growth_evidence(source_text):
            guarded["타"].append("성장형")

    _, worldview_max_items = AXIS_LIMITS["세"]
    if (
        "아카데미" in allowed_labels["세"]
        and "아카데미" not in guarded["세"]
        and len(guarded["세"]) < worldview_max_items
        and _has_academy_evidence(source_text)
    ):
        guarded["세"].append("아카데미")

    return guarded


def _normalize_axis_label_scores(
    raw_scores: Any,
    axis_labels: dict[str, list[str]],
    axis_confidence: dict[str, float | None],
) -> dict[str, list[dict[str, float]]]:
    if not isinstance(raw_scores, dict):
        raw_scores = {}

    normalized_scores: dict[str, list[dict[str, float]]] = {}
    for axis in AXIS_ORDER:
        labels = axis_labels[axis]
        axis_raw = raw_scores.get(axis)

        parsed: dict[str, float] = {}
        candidates: list[dict[str, Any]] = []
        if isinstance(axis_raw, list):
            candidates = [item for item in axis_raw if isinstance(item, dict)]
        elif isinstance(axis_raw, dict):
            candidates = [{"label": key, "score": value} for key, value in axis_raw.items()]

        for item in candidates:
            label = item.get("label")
            if not isinstance(label, str):
                continue
            key = label.strip()
            if not key or key not in labels:
                continue
            try:
                score = _safe_confidence(item.get("score"), f"axis_label_scores.{axis}.{key}")
            except ValueError:
                continue
            if score is None:
                continue
            parsed[key] = score

        fallback = axis_confidence.get(axis)
        if fallback is None:
            fallback = 0.0
        normalized_scores[axis] = [{"label": label, "score": parsed.get(label, fallback)} for label in labels]

    return normalized_scores


def _format_allowed_labels_json(allowed_labels: dict[str, set[str]]) -> str:
    return json.dumps(
        {axis: sorted(allowed_labels[axis]) for axis in AXIS_ORDER},
        ensure_ascii=False,
    )


def load_allowed_labels() -> dict[str, set[str]]:
    for path in LABELS_JSON_CANDIDATES:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig") as fp:
            raw = json.load(fp)
        if not isinstance(raw, dict):
            raise ValueError("allowed-labels-by-axis.json format is invalid")
        result: dict[str, set[str]] = {}
        for axis in AXIS_ORDER:
            values = raw.get(axis)
            if not isinstance(values, list):
                raise ValueError(f"axis '{axis}' is not list")
            result[axis] = {
                str(v).strip()
                for v in values
                if isinstance(v, str) and str(v).strip()
            }
        return result
    raise ValueError("allowed-labels-by-axis.json 파일을 찾을 수 없습니다.")


def load_label_definitions() -> str:
    """라벨 정의 JSON을 프롬프트용 텍스트로 변환."""
    for path in LABEL_DEFS_JSON_CANDIDATES:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig") as fp:
            raw = json.load(fp)
        lines = []
        for axis, defs in raw.items():
            if isinstance(defs, dict):
                for label, desc in defs.items():
                    lines.append(f"  [{axis}] {label}: {desc}")
        return "\n".join(lines)
    return ""


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _compact_model_slug(model: str) -> str:
    slug = (model or "").split("/")[-1].strip().lower()
    return (
        slug.replace("deepseek-", "ds-")
        .replace("claude-", "cl-")
        .replace("haiku-", "hq-")
        .replace("json_schema", "schema")
    )


def _compact_response_format(value: str) -> str:
    if value == "json_schema":
        return "schema"
    if value == "json_object":
        return "json"
    return (value or "default")[:10]


def _current_analysis_version() -> str:
    if AI_DNA_PROVIDER != "openrouter":
        return ANALYSIS_PIPELINE_VERSION[:50]
    provider = (_split_csv(AI_DNA_OPENROUTER_PROVIDER_ONLY) or ["auto"])[0]
    version = "|".join(
        [
            ANALYSIS_PIPELINE_VERSION,
            "or",
            _compact_model_slug(AI_DNA_OPENROUTER_MODEL),
            provider,
            _compact_response_format(AI_DNA_RESPONSE_FORMAT),
        ]
    )
    return version[:50]


CURRENT_ANALYSIS_VERSION = _current_analysis_version()


def _build_openrouter_response_format(allowed_labels: dict[str, set[str]]) -> dict[str, Any]:
    if AI_DNA_RESPONSE_FORMAT == "json_object":
        return {"type": "json_object"}
    if AI_DNA_RESPONSE_FORMAT != "json_schema":
        raise ValueError(f"unsupported AI_DNA_RESPONSE_FORMAT: {AI_DNA_RESPONSE_FORMAT}")

    axis_properties: dict[str, Any] = {}
    for axis in AXIS_ORDER:
        min_items, max_items = AXIS_LIMITS[axis]
        axis_properties[axis] = {
            "type": "array",
            "items": {"type": "string", "enum": sorted(allowed_labels[axis])},
            "minItems": min_items,
            "maxItems": max_items,
        }
    confidence_properties = {
        axis: {"type": "number", "minimum": 0, "maximum": 1}
        for axis in AXIS_ORDER
    }
    axis_label_score_properties = {
        axis: {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label": {"type": "string", "enum": sorted(allowed_labels[axis])},
                    "score": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["label", "score"],
            },
            "minItems": min_items,
            "maxItems": max_items,
        }
        for axis, (min_items, max_items) in AXIS_LIMITS.items()
    }
    evidence_properties = {
        axis: {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 0,
            "maxItems": max_items,
        }
        for axis, (_, max_items) in AXIS_LIMITS.items()
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "protagonist_type": {"type": "string"},
                    "protagonist_desc": {"type": "string"},
                    "heroine_type": {"type": "string"},
                    "heroine_weight": {
                        "type": "string",
                        "enum": sorted(ALLOWED_HEROINE_WEIGHT),
                    },
                    "mood": {"type": "string"},
                    "pacing": {"type": "string", "enum": sorted(ALLOWED_PACING)},
                    "premise": {"type": "string"},
                    "hook": {"type": "string"},
                    "themes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "taste_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                },
                "required": [
                    "protagonist_type",
                    "protagonist_desc",
                    "heroine_type",
                    "heroine_weight",
                    "mood",
                    "pacing",
                    "premise",
                    "hook",
                    "themes",
                    "taste_tags",
                ],
            },
            "axis_labels": {
                "type": "object",
                "additionalProperties": False,
                "properties": axis_properties,
                "required": list(AXIS_ORDER),
            },
            "axis_confidence": {
                "type": "object",
                "additionalProperties": False,
                "properties": confidence_properties,
                "required": list(AXIS_ORDER),
            },
            "axis_label_scores": {
                "type": "object",
                "additionalProperties": False,
                "properties": axis_label_score_properties,
                "required": list(AXIS_ORDER),
            },
            "overall_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {
                "type": "object",
                "additionalProperties": False,
                "properties": evidence_properties,
                "required": list(AXIS_ORDER),
            },
            "unmapped_concepts": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 0,
                "maxItems": 10,
            },
        },
        "required": [
            "summary",
            "axis_labels",
            "axis_confidence",
            "axis_label_scores",
            "overall_confidence",
            "evidence",
            "unmapped_concepts",
        ],
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "likenovel_dna_axis_extraction",
            "strict": True,
            "schema": schema,
        },
    }


def _validate_runtime_config(allowed_labels: dict[str, set[str]]) -> None:
    if MAX_LLM_OUTPUT_TOKENS <= 0:
        raise RuntimeError("AI_METADATA_MAX_TOKENS must be > 0")
    if AI_DNA_PROVIDER == "anthropic":
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY 환경변수를 설정하세요.")
        return
    if AI_DNA_PROVIDER != "openrouter":
        raise RuntimeError(f"unsupported AI_DNA_PROVIDER: {AI_DNA_PROVIDER}")
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY 환경변수를 설정하세요.")
    if not AI_DNA_OPENROUTER_MODEL:
        raise RuntimeError("AI_DNA_OPENROUTER_MODEL 환경변수를 설정하세요.")
    if AI_DNA_TIMEOUT_SECONDS <= 0:
        raise RuntimeError("AI_DNA_TIMEOUT_SECONDS must be > 0")
    _build_openrouter_response_format(allowed_labels)


def normalize_payload(
    payload: dict[str, Any],
    allowed_labels: dict[str, set[str]],
    source_text: str = "",
) -> dict[str, Any]:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    axis_labels = payload.get("axis_labels")
    if not isinstance(axis_labels, dict):
        axis_labels = {}

    normalized_axis: dict[str, list[str]] = {}
    for axis in AXIS_ORDER:
        _, max_items = AXIS_LIMITS[axis]
        labels = _safe_list(axis_labels.get(axis), f"axis_labels.{axis}", max_items=max_items, max_item_length=50)
        for label in labels:
            if label not in allowed_labels[axis]:
                raise UnsupportedLabelError(axis, label)
        normalized_axis[axis] = labels[:max_items]

    normalized_axis = _apply_axis_label_evidence_guards(
        normalized_axis,
        allowed_labels,
        _payload_evidence_text(payload, source_text),
    )

    axis_confidence = payload.get("axis_confidence")
    if not isinstance(axis_confidence, dict):
        axis_confidence = {}
    normalized_confidence = {
        axis: _safe_confidence(axis_confidence.get(axis), f"axis_confidence.{axis}")
        for axis in AXIS_ORDER
    }
    axis_label_scores = _normalize_axis_label_scores(
        payload.get("axis_label_scores"),
        normalized_axis,
        normalized_confidence,
    )
    unmapped_concepts = _safe_list(
        payload.get("unmapped_concepts"), "unmapped_concepts", max_items=10, max_item_length=50
    )

    protagonist_type = _safe_text(summary.get("protagonist_type"), "summary.protagonist_type", 200)
    if protagonist_type is None:
        if not normalized_axis["타"]:
            raise ValueError("summary.protagonist_type is required when 타 axis is empty")
        protagonist_type = normalized_axis["타"][0]

    mood = _safe_text(summary.get("mood"), "summary.mood", 200, required=True)
    premise = _safe_text(summary.get("premise"), "summary.premise", 500, required=True)

    taste_tags = _safe_list(summary.get("taste_tags"), "summary.taste_tags", max_items=30)
    if not taste_tags:
        merged = (
            normalized_axis["세"]
            + normalized_axis["직"]
            + normalized_axis["능"]
            + normalized_axis["연"]
            + normalized_axis["작"]
            + normalized_axis["타"]
            + normalized_axis["목"]
        )
        taste_tags = list(dict.fromkeys(merged))[:30]

    themes = _safe_list(summary.get("themes"), "summary.themes")
    if not themes:
        raise ValueError("summary.themes requires at least 1 item")
    return {
        "protagonist_type": protagonist_type,
        "protagonist_desc": _safe_text(summary.get("protagonist_desc"), "summary.protagonist_desc", 500, required=True),
        "heroine_type": _safe_text(summary.get("heroine_type"), "summary.heroine_type", 200, required=True),
        "heroine_weight": _safe_enum(summary.get("heroine_weight"), "summary.heroine_weight", ALLOWED_HEROINE_WEIGHT, required=True),
        "romance_chemistry_weight": _safe_enum(
            summary.get("romance_chemistry_weight"),
            "summary.romance_chemistry_weight",
            ALLOWED_HEROINE_WEIGHT,
        )
        or ("mid" if normalized_axis["연"] else "none"),
        "mood": mood,
        "pacing": _safe_enum(summary.get("pacing"), "summary.pacing", ALLOWED_PACING, required=True),
        "premise": premise,
        "hook": _safe_text(summary.get("hook"), "summary.hook", 300, required=True),
        "themes": themes,
        "similar_famous": [],
        "taste_tags": taste_tags,
        "protagonist_goal_primary": normalized_axis["목"][0] if normalized_axis["목"] else None,
        "goal_confidence": normalized_confidence["목"],
        "overall_confidence": _safe_confidence(payload.get("overall_confidence"), "overall_confidence"),
        "axis_label_scores": axis_label_scores,
        "unmapped_concepts": unmapped_concepts,
        "protagonist_material_tags": normalized_axis["능"],
        "worldview_tags": normalized_axis["세"],
        "protagonist_type_tags": normalized_axis["타"],
        "protagonist_job_tags": normalized_axis["직"],
        "axis_style_tags": normalized_axis["작"],
        "axis_romance_tags": normalized_axis["연"],
    }


def call_claude(system_prompt: str, user_prompt: str) -> str:
    """Anthropic Messages API 호출 (동기)."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY 환경변수를 설정하세요.")

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": MAX_LLM_OUTPUT_TOKENS,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Claude API error: {resp.status_code} {resp.text}")
        data = resp.json()
        if data.get("stop_reason") == "max_tokens":
            raise RuntimeError(
                f"Claude output truncated: stop_reason=max_tokens(max_tokens={MAX_LLM_OUTPUT_TOKENS})"
            )
        return data["content"][0]["text"]


def _extract_openrouter_message_text(payload: dict[str, Any]) -> str:
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        content = "\n".join(parts)
    return str(content or "").strip()


def _redact_openrouter_message(text: str) -> str:
    cleaned = re.sub(r'(?i)(user_id["=: ]+)([A-Za-z0-9_-]+)', r"\1***", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:240]


def _sanitize_openrouter_error(resp: httpx.Response) -> str:
    message = ""
    code = ""
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or error.get("type") or "").strip()
            message = str(error.get("message") or "").strip()
        if not code:
            code = str(payload.get("code") or "").strip()
        if not message:
            message = str(payload.get("message") or "").strip()
    detail_parts = [f"status={resp.status_code}"]
    if code:
        detail_parts.append(f"code={code}")
    if message:
        detail_parts.append(f"message={_redact_openrouter_message(message)}")
    return f"OpenRouter API error ({', '.join(detail_parts)})"


def _validate_openrouter_choice(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenRouter invalid response: missing choices")
    choice = choices[0] or {}
    finish_reason = choice.get("finish_reason")
    if finish_reason and finish_reason not in OPENROUTER_ALLOWED_FINISH_REASONS:
        raise RuntimeError(f"OpenRouter incomplete response: finish_reason={finish_reason}")
    return choice


def call_openrouter(
    system_prompt: str,
    user_prompt: str,
    allowed_labels: dict[str, set[str]],
) -> tuple[str, dict[str, Any]]:
    """OpenRouter Chat Completions 호출 (동기)."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY 환경변수를 설정하세요.")
    if not AI_DNA_OPENROUTER_MODEL:
        raise RuntimeError("AI_DNA_OPENROUTER_MODEL 환경변수를 설정하세요.")

    payload: dict[str, Any] = {
        "model": AI_DNA_OPENROUTER_MODEL,
        "temperature": 0.1,
        "max_tokens": MAX_LLM_OUTPUT_TOKENS,
        "response_format": _build_openrouter_response_format(allowed_labels),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if AI_DNA_OPENROUTER_REASONING:
        if AI_DNA_OPENROUTER_REASONING in ("low", "medium", "high"):
            payload["reasoning"] = {"effort": AI_DNA_OPENROUTER_REASONING}
        elif AI_DNA_OPENROUTER_REASONING in ("enabled", "on", "true", "1"):
            payload["reasoning"] = {"enabled": True}
    provider_only = _split_csv(AI_DNA_OPENROUTER_PROVIDER_ONLY)
    if provider_only:
        payload["provider"] = {
            "only": provider_only,
            "require_parameters": True,
        }

    with httpx.Client(timeout=AI_DNA_TIMEOUT_SECONDS) as client:
        resp = client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "X-Title": "LikeNovel AI DNA Metadata Batch",
            },
            json=payload,
        )
    if resp.status_code != 200:
        raise RuntimeError(_sanitize_openrouter_error(resp))

    data = resp.json()
    _validate_openrouter_choice(data)
    raw = _extract_openrouter_message_text(data)
    if not raw:
        finish_reason = ((data.get("choices") or [{}])[0] or {}).get("finish_reason")
        raise RuntimeError(f"OpenRouter empty content (finish_reason={finish_reason or 'unknown'})")
    return raw, data.get("usage") or {}


def _sanitize_deepseek_error(resp: httpx.Response) -> str:
    message = ""
    code = ""
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or error.get("type") or "").strip()
            message = str(error.get("message") or "").strip()
        if not code:
            code = str(payload.get("code") or "").strip()
        if not message:
            message = str(payload.get("message") or "").strip()
    detail_parts = [f"status={resp.status_code}"]
    if code:
        detail_parts.append(f"code={code}")
    if message:
        detail_parts.append(f"message={_redact_openrouter_message(message)}")
    return f"DeepSeek API error ({', '.join(detail_parts)})"


def call_deepseek(system_prompt: str, user_prompt: str) -> tuple[str, dict[str, Any]]:
    """DeepSeek 공식 Chat Completions 호출 (Anthropic fallback용)."""
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY 환경변수를 설정하세요.")
    if not AI_DNA_DEEPSEEK_FALLBACK_MODEL:
        raise RuntimeError("AI_DNA_DEEPSEEK_FALLBACK_MODEL 환경변수를 설정하세요.")

    with httpx.Client(timeout=AI_DNA_TIMEOUT_SECONDS) as client:
        resp = client.post(
            f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": AI_DNA_DEEPSEEK_FALLBACK_MODEL,
                "temperature": 0.2,
                "max_tokens": MAX_LLM_OUTPUT_TOKENS,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
    if resp.status_code != 200:
        raise RuntimeError(_sanitize_deepseek_error(resp))

    data = resp.json()
    _validate_openrouter_choice(data)
    raw = _extract_openrouter_message_text(data)
    if not raw:
        finish_reason = ((data.get("choices") or [{}])[0] or {}).get("finish_reason")
        raise RuntimeError(f"DeepSeek empty content (finish_reason={finish_reason or 'unknown'})")
    return raw, data.get("usage") or {}


def _usage_summary(usage: dict[str, Any] | None) -> dict[str, Any]:
    usage = usage or {}
    return {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "cost": usage.get("cost"),
    }


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    allowed_labels: dict[str, set[str]],
) -> tuple[str, dict[str, Any]]:
    if AI_DNA_PROVIDER == "anthropic":
        try:
            return call_claude(system_prompt, user_prompt), {
                "provider": "anthropic",
                "model": ANTHROPIC_MODEL,
                "response_format": "json_object",
            }
        except Exception as exc:
            if not DEEPSEEK_API_KEY:
                raise
            raw, usage = call_deepseek(system_prompt, user_prompt)
            return raw, {
                "provider": "deepseek",
                "fallback_from": "anthropic",
                "fallback_reason": str(exc)[:240],
                "model": AI_DNA_DEEPSEEK_FALLBACK_MODEL,
                "response_format": "json_object",
                "usage": _usage_summary(usage),
            }
    if AI_DNA_PROVIDER == "openrouter":
        raw, usage = call_openrouter(system_prompt, user_prompt, allowed_labels)
        return raw, {
            "provider": "openrouter",
            "model": AI_DNA_OPENROUTER_MODEL,
            "provider_only": _split_csv(AI_DNA_OPENROUTER_PROVIDER_ONLY),
            "response_format": AI_DNA_RESPONSE_FORMAT,
            "usage": _usage_summary(usage),
        }
    raise RuntimeError(f"unsupported AI_DNA_PROVIDER: {AI_DNA_PROVIDER}")


def _attach_llm_meta(parsed: dict[str, Any], calls: list[dict[str, Any]]) -> dict[str, Any]:
    enriched = dict(parsed)
    total_cost = 0.0
    found_cost = False
    for call in calls:
        usage = call.get("usage") or {}
        if usage.get("cost") is not None:
            total_cost += float(usage["cost"])
            found_cost = True
    enriched["_llm_meta"] = {
        "analysis_version": CURRENT_ANALYSIS_VERSION,
        "calls": calls,
        "total_cost": round(total_cost, 8) if found_cost else None,
    }
    return enriched


def parse_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)


def _build_analysis_prompt(
    product: dict,
    allowed_labels: dict[str, set[str]],
    episodes_text: str,
    used_count: int,
) -> str:
    return DNA_USER_TEMPLATE.format(
        title=product["title"],
        genres=product.get("genres") or "",
        keywords=product.get("keywords") or "",
        synopsis_text=(product.get("synopsis_text") or "")[:1000],
        episode_count=product.get("episode_count", 0),
        status_code=product.get("status_code", ""),
        n_requested=MAX_ANALYZE_EPISODES,
        n_received=used_count,
        allowed_labels_json=_format_allowed_labels_json(allowed_labels),
        label_definitions_text=load_label_definitions(),
        episodes_text=episodes_text,
    )


def _build_repair_prompt(
    product: dict,
    allowed_labels: dict[str, set[str]],
    parsed_payload: dict[str, Any],
    error: UnsupportedLabelError,
) -> str:
    return DNA_REPAIR_TEMPLATE.format(
        title=product["title"],
        axis=error.axis,
        label=error.label,
        allowed_labels_json=_format_allowed_labels_json(allowed_labels),
        label_definitions_text=load_label_definitions(),
        raw_payload_json=json.dumps(parsed_payload, ensure_ascii=False),
    )


def analyze_product(
    product: dict,
    allowed_labels: dict[str, set[str]],
    episodes_text: str,
    used_count: int,
) -> tuple[dict, dict]:
    """작품 1개 분석."""
    source_text = "\n".join(
        [
            str(product.get("title") or ""),
            str(product.get("genres") or ""),
            str(product.get("keywords") or ""),
            str(product.get("synopsis_text") or ""),
            episodes_text,
        ]
    )
    user_prompt = _build_analysis_prompt(product, allowed_labels, episodes_text, used_count)
    raw, call_meta = _call_llm(DNA_SYSTEM_PROMPT, user_prompt, allowed_labels)
    llm_calls = [{"stage": "analysis", **call_meta}]
    parsed = parse_json(raw)
    try:
        normalized = normalize_payload(parsed, allowed_labels, source_text=source_text)
    except UnsupportedLabelError as repair_error:
        repair_prompt = _build_repair_prompt(product, allowed_labels, parsed, repair_error)
        repaired_raw, repair_call_meta = _call_llm(DNA_SYSTEM_PROMPT, repair_prompt, allowed_labels)
        llm_calls.append(
            {
                "stage": "repair",
                "repair_axis": repair_error.axis,
                "repair_label": repair_error.label,
                **repair_call_meta,
            }
        )
        repaired_parsed = parse_json(repaired_raw)
        normalized = normalize_payload(repaired_parsed, allowed_labels, source_text=source_text)
        parsed = repaired_parsed
    parsed = _attach_llm_meta(parsed, llm_calls)
    return normalized, parsed


def save_dna(conn, product_id: int, dna: dict, parsed: dict, attempt_count: int):
    """분석 결과 저장 (UPSERT)."""
    raw_analysis = dict(parsed) if isinstance(parsed, dict) else parsed
    if isinstance(raw_analysis, dict):
        raw_analysis["unmapped_concepts"] = dna.get("unmapped_concepts", [])

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tb_product_ai_metadata (
                product_id,
                protagonist_type, protagonist_desc, heroine_type, heroine_weight, romance_chemistry_weight,
                mood, pacing, premise, hook,
                protagonist_goal_primary, goal_confidence, overall_confidence, axis_label_scores,
                protagonist_material_tags, worldview_tags, protagonist_type_tags, protagonist_job_tags, axis_style_tags, axis_romance_tags,
                themes, similar_famous, taste_tags,
                raw_analysis, analyzed_at, model_version,
                analysis_status, analysis_attempt_count, analysis_error_message
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, NOW(), %s,
                'success', %s, NULL
            )
            ON DUPLICATE KEY UPDATE
                protagonist_type = VALUES(protagonist_type),
                protagonist_desc = VALUES(protagonist_desc),
                heroine_type = VALUES(heroine_type),
                heroine_weight = VALUES(heroine_weight),
                romance_chemistry_weight = VALUES(romance_chemistry_weight),
                mood = VALUES(mood),
                pacing = VALUES(pacing),
                premise = VALUES(premise),
                hook = VALUES(hook),
                protagonist_goal_primary = VALUES(protagonist_goal_primary),
                goal_confidence = VALUES(goal_confidence),
                overall_confidence = VALUES(overall_confidence),
                axis_label_scores = VALUES(axis_label_scores),
                protagonist_material_tags = VALUES(protagonist_material_tags),
                worldview_tags = VALUES(worldview_tags),
                protagonist_type_tags = VALUES(protagonist_type_tags),
                protagonist_job_tags = VALUES(protagonist_job_tags),
                axis_style_tags = VALUES(axis_style_tags),
                axis_romance_tags = VALUES(axis_romance_tags),
                themes = VALUES(themes),
                similar_famous = VALUES(similar_famous),
                taste_tags = VALUES(taste_tags),
                raw_analysis = VALUES(raw_analysis),
                analyzed_at = NOW(),
                model_version = VALUES(model_version),
                analysis_status = 'success',
                analysis_attempt_count = VALUES(analysis_attempt_count),
                analysis_error_message = NULL
        """,
            (
                product_id,
                dna.get("protagonist_type"),
                dna.get("protagonist_desc"),
                dna.get("heroine_type"),
                dna.get("heroine_weight"),
                dna.get("romance_chemistry_weight"),
                dna.get("mood"),
                dna.get("pacing"),
                dna.get("premise"),
                dna.get("hook"),
                dna.get("protagonist_goal_primary"),
                dna.get("goal_confidence"),
                dna.get("overall_confidence"),
                json.dumps(dna.get("axis_label_scores", {}), ensure_ascii=False),
                json.dumps(dna.get("protagonist_material_tags", []), ensure_ascii=False),
                json.dumps(dna.get("worldview_tags", []), ensure_ascii=False),
                json.dumps(dna.get("protagonist_type_tags", []), ensure_ascii=False),
                json.dumps(dna.get("protagonist_job_tags", []), ensure_ascii=False),
                json.dumps(dna.get("axis_style_tags", []), ensure_ascii=False),
                json.dumps(dna.get("axis_romance_tags", []), ensure_ascii=False),
                json.dumps(dna.get("themes", []), ensure_ascii=False),
                json.dumps(dna.get("similar_famous", []), ensure_ascii=False),
                json.dumps(dna.get("taste_tags", []), ensure_ascii=False),
                json.dumps(raw_analysis, ensure_ascii=False),
                CURRENT_ANALYSIS_VERSION,
                attempt_count,
            ),
        )


def save_failed(conn, product_id: int, attempt_count: int, error_message: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tb_product_ai_metadata (
                product_id, analysis_status, analysis_attempt_count, analysis_error_message, model_version
            ) VALUES (
                %s, 'failed', %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                analysis_status = 'failed',
                analysis_attempt_count = VALUES(analysis_attempt_count),
                analysis_error_message = VALUES(analysis_error_message),
                model_version = VALUES(model_version)
            """,
            (
                product_id,
                attempt_count,
                (error_message or "unknown error")[:1000],
                CURRENT_ANALYSIS_VERSION,
            ),
        )


def _format_failure_message(error: Exception) -> str:
    if isinstance(error, UnsupportedLabelError):
        return f"{UNSUPPORTED_LABEL_ERROR_PREFIX}{error.axis}:{error.label}"
    return (str(error) or "unknown error")[:1000]


def _format_cost_from_parsed(parsed: dict[str, Any]) -> str:
    meta = parsed.get("_llm_meta") if isinstance(parsed, dict) else None
    if not isinstance(meta, dict) or meta.get("total_cost") is None:
        return ""
    return f", cost=${float(meta['total_cost']):.6f}"


def main():
    parser = argparse.ArgumentParser(description="작품 AI 메타 추출")
    parser.add_argument("--product-id", type=int, help="특정 작품 ID만 분석")
    parser.add_argument("--all", action="store_true", help="전체 작품 분석")
    parser.add_argument("--force", action="store_true", help="기존 분석 덮어쓰기")
    args = parser.parse_args()

    if not args.product_id and not args.all:
        parser.error("--product-id 또는 --all 중 하나를 지정하세요.")

    allowed_labels = load_allowed_labels()
    _validate_runtime_config(allowed_labels)
    conn = db_connect()
    print(f"[OK] DB 연결 성공 ({DB_HOST}:{DB_PORT})")
    print(f"[OK] 라벨 SSOT 로드 완료: {next(path for path in LABELS_JSON_CANDIDATES if path.exists())}")
    print(f"[INFO] provider={AI_DNA_PROVIDER}, version={CURRENT_ANALYSIS_VERSION}")

    products = get_products(conn, args.product_id, args.force)
    print(f"[INFO] 분석 대상: {len(products)}개 작품")

    success = 0
    fail = 0
    for i, product in enumerate(products, 1):
        pid = product["product_id"]
        title = product["title"]
        print(f"[{i}/{len(products)}] {pid}: {title} ... ", end="", flush=True)

        episodes = get_episodes(conn, pid)
        episode_context, used_count = _build_episode_context(episodes)
        if used_count < MIN_REQUIRED_EPISODES:
            fail += 1
            save_failed(conn, pid, 1, f"insufficient_episodes(<{MIN_REQUIRED_EPISODES})")
            print(f"SKIP: insufficient episodes ({used_count})")
            continue

        last_error = "unknown error"
        analyzed = False
        for retry_idx in range(MAX_RETRY_COUNT + 1):
            attempt = retry_idx + 1
            try:
                dna, parsed = analyze_product(product, allowed_labels, episode_context, used_count)
                save_dna(conn, pid, dna, parsed, attempt)
                success += 1
                analyzed = True
                print(f"OK (attempt={attempt}{_format_cost_from_parsed(parsed)})")
                break
            except UnsupportedLabelError as e:
                last_error = _format_failure_message(e)
                break
            except Exception as e:
                last_error = _format_failure_message(e)
                if attempt <= MAX_RETRY_COUNT:
                    time.sleep(1.0)

        if not analyzed:
            fail += 1
            save_failed(conn, pid, MAX_RETRY_COUNT + 1, last_error)
            print(f"FAIL: {last_error}")

        time.sleep(1)  # rate limit 방지

    conn.close()
    print(f"\n[DONE] 성공: {success}, 실패: {fail}")
    if fail > 0 and success == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
