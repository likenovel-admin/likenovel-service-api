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

MAX_RETRY_COUNT = 2  # 초기 1회 + 재시도 2회
MAX_ANALYZE_EPISODES = 10
MAX_ANALYZE_CHARS = 60000
MAX_LLM_OUTPUT_TOKENS = int(os.getenv("AI_METADATA_MAX_TOKENS", "4096"))
MIN_REQUIRED_EPISODES = 3
DEFAULT_GOAL_LABEL = "성장"

AXIS_ORDER = ("세", "직", "능", "연", "작", "타", "목")
AXIS_LIMITS: dict[str, tuple[int, int]] = {
    "세": (1, 3),
    "직": (1, 2),
    "능": (1, 4),
    "연": (0, 2),
    "작": (1, 3),
    "타": (1, 3),
    "목": (1, 1),
}
ALLOWED_HEROINE_WEIGHT = {"high", "mid", "low", "none"}
ALLOWED_PACING = {"fast", "medium", "slow"}

ROOT_DIR = Path(__file__).resolve().parent.parent
LABELS_JSON_CANDIDATES = [
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
입력된 정보(작품정보 + 도입부 회차 본문)를 읽고 7축 메타를 추출한다.
출력은 반드시 JSON 단일 객체만 허용한다. 설명문/마크다운/코드블록 금지.

핵심 규칙:
1) 허용 라벨 목록 외 신규 라벨 생성 금지.
1-1) 각 라벨의 의미는 "라벨 정의" 섹션을 참고하여 판단한다. 이름만으로 추측하지 않는다.
2) 목표축(목)은 1개만 선택. 라벨 정의를 참고하여 작품의 핵심 목표에 가장 부합하는 라벨을 선택한다.
3) 연애축(연)은 연애/케미가 드러날 때만 선택 가능. 없으면 빈 배열 가능.
4) confidence는 0~1 범위 숫자.
5) summary의 모든 필드를 빈 값 없이 채운다. null 금지. themes/taste_tags도 각각 1개 이상.
6) heroine이 없는 작품은 heroine_type에 주요 여성 캐릭터를 기재하고, heroine_weight는 "none"으로 설정한다.
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

허용 라벨(축별 SSOT JSON):
{allowed_labels_json}

라벨 정의(분류 기준):
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
  "overall_confidence": 0.0
}}"""


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
        where = """
            p.open_yn = 'Y'
            AND COALESCE(u.role_type, 'normal') != 'admin'
            AND COALESCE(TRIM(p.author_name), '') != ''
            AND EXISTS (
                SELECT 1
                FROM tb_product_episode fe
                WHERE fe.product_id = p.product_id
                  AND fe.episode_no = 1
                  AND fe.use_yn = 'Y'
                  AND fe.open_yn = 'Y'
                  AND fe.episode_text_count >= 5000
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
            where += f" AND p.product_id = {product_id}"
        if not force:
            where += f"""
            AND (
                m.id IS NULL
                OR m.analyzed_at IS NULL
                OR (
                    SELECT COUNT(*)
                    FROM tb_product_episode le
                    WHERE le.product_id = p.product_id
                      AND le.use_yn = 'Y'
                      AND le.open_yn = 'Y'
                ) < {MAX_ANALYZE_EPISODES}
            )
            """  # 미분석 또는 10화 미만(완결 전) 작품은 매 배치 갱신

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
        """
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


def normalize_payload(payload: dict[str, Any], allowed_labels: dict[str, set[str]]) -> dict[str, Any]:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    axis_labels = payload.get("axis_labels")
    if not isinstance(axis_labels, dict):
        axis_labels = {}

    normalized_axis: dict[str, list[str]] = {}
    for axis in AXIS_ORDER:
        min_items, max_items = AXIS_LIMITS[axis]
        labels = _safe_list(axis_labels.get(axis), f"axis_labels.{axis}", max_items=max_items, max_item_length=50)
        for label in labels:
            if label not in allowed_labels[axis]:
                raise ValueError(f"axis_labels.{axis} contains unsupported label: {label}")
        if len(labels) < min_items:
            if axis == "목":
                fallback = DEFAULT_GOAL_LABEL if DEFAULT_GOAL_LABEL in allowed_labels["목"] else sorted(allowed_labels["목"])[0]
                labels = [fallback]
            else:
                raise ValueError(f"axis_labels.{axis} requires at least {min_items} labels")
        normalized_axis[axis] = labels[:max_items]

    axis_confidence = payload.get("axis_confidence")
    if not isinstance(axis_confidence, dict):
        axis_confidence = {}

    protagonist_type = _safe_text(summary.get("protagonist_type"), "summary.protagonist_type", 200)
    if protagonist_type is None:
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
        "protagonist_goal_primary": normalized_axis["목"][0],
        "goal_confidence": _safe_confidence(axis_confidence.get("목"), "axis_confidence.목"),
        "overall_confidence": _safe_confidence(payload.get("overall_confidence"), "overall_confidence"),
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


def parse_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)


def analyze_product(
    product: dict,
    allowed_labels: dict[str, set[str]],
    episodes_text: str,
    used_count: int,
) -> tuple[dict, dict]:
    """작품 1개 분석."""
    user_prompt = DNA_USER_TEMPLATE.format(
        title=product["title"],
        genres=product.get("genres") or "",
        keywords=product.get("keywords") or "",
        synopsis_text=(product.get("synopsis_text") or "")[:1000],
        episode_count=product.get("episode_count", 0),
        status_code=product.get("status_code", ""),
        n_requested=MAX_ANALYZE_EPISODES,
        n_received=used_count,
        allowed_labels_json=json.dumps(
            {axis: sorted(allowed_labels[axis]) for axis in AXIS_ORDER},
            ensure_ascii=False,
        ),
        label_definitions_text=load_label_definitions(),
        episodes_text=episodes_text,
    )
    raw = call_claude(DNA_SYSTEM_PROMPT, user_prompt)
    parsed = parse_json(raw)
    normalized = normalize_payload(parsed, allowed_labels)
    return normalized, parsed


def save_dna(conn, product_id: int, dna: dict, parsed: dict, attempt_count: int):
    """분석 결과 저장 (UPSERT)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tb_product_ai_metadata (
                product_id,
                protagonist_type, protagonist_desc, heroine_type, heroine_weight, romance_chemistry_weight,
                mood, pacing, premise, hook,
                protagonist_goal_primary, goal_confidence, overall_confidence,
                protagonist_material_tags, worldview_tags, protagonist_type_tags, protagonist_job_tags, axis_style_tags, axis_romance_tags,
                themes, similar_famous, taste_tags,
                raw_analysis, analyzed_at, model_version,
                analysis_status, analysis_attempt_count, analysis_error_message
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
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
                json.dumps(dna.get("protagonist_material_tags", []), ensure_ascii=False),
                json.dumps(dna.get("worldview_tags", []), ensure_ascii=False),
                json.dumps(dna.get("protagonist_type_tags", []), ensure_ascii=False),
                json.dumps(dna.get("protagonist_job_tags", []), ensure_ascii=False),
                json.dumps(dna.get("axis_style_tags", []), ensure_ascii=False),
                json.dumps(dna.get("axis_romance_tags", []), ensure_ascii=False),
                json.dumps(dna.get("themes", []), ensure_ascii=False),
                json.dumps(dna.get("similar_famous", []), ensure_ascii=False),
                json.dumps(dna.get("taste_tags", []), ensure_ascii=False),
                json.dumps(parsed, ensure_ascii=False),
                ANTHROPIC_MODEL,
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
                ANTHROPIC_MODEL,
            ),
        )


def main():
    parser = argparse.ArgumentParser(description="작품 AI 메타 추출")
    parser.add_argument("--product-id", type=int, help="특정 작품 ID만 분석")
    parser.add_argument("--all", action="store_true", help="전체 작품 분석")
    parser.add_argument("--force", action="store_true", help="기존 분석 덮어쓰기")
    args = parser.parse_args()

    if not args.product_id and not args.all:
        parser.error("--product-id 또는 --all 중 하나를 지정하세요.")

    allowed_labels = load_allowed_labels()
    conn = db_connect()
    print(f"[OK] DB 연결 성공 ({DB_HOST}:{DB_PORT})")
    print(f"[OK] 라벨 SSOT 로드 완료: {next(path for path in LABELS_JSON_CANDIDATES if path.exists())}")

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
                print(f"OK (attempt={attempt})")
                break
            except Exception as e:
                last_error = str(e)
                if attempt <= MAX_RETRY_COUNT:
                    time.sleep(1.0)

        if not analyzed:
            fail += 1
            save_failed(conn, pid, MAX_RETRY_COUNT + 1, last_error)
            print(f"FAIL: {last_error}")

        time.sleep(1)  # rate limit 방지

    conn.close()
    print(f"\n[DONE] 성공: {success}, 실패: {fail}")


if __name__ == "__main__":
    main()
