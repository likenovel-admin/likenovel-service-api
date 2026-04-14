#!/usr/bin/env python3
"""OpenRouter 모델별 story-agent episode summary 비교 스크립트.

목적
- 같은 회차 원문에 대해 여러 모델의 episode_summary 품질을 비교한다.
- 기존 배치/런타임 로직은 건드리지 않고, 로컬에서만 샘플 검증한다.

출력
- 에피소드별 모델 응답 원문
- 파싱된 JSON summary
- schema_pass / latency / usage
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pymysql
from bs4 import BeautifulSoup
from pymysql.constants import CLIENT
from pymysql.cursors import DictCursor

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
DEFAULT_MODELS = [
    item.strip()
    for item in os.getenv(
        "OPENROUTER_COMPARE_MODELS",
        "qwen/qwen3.5-flash-02-23,deepseek/deepseek-chat,z-ai/glm-4.5-air,minimax/minimax-m2.7",
    ).split(",")
    if item.strip()
]
REQUEST_TIMEOUT_SECONDS = 120.0
MAX_OUTPUT_TOKENS = 1200
MAX_EPISODE_CHARS = 9000
DB_HOST = os.getenv("BATCH_DB_HOST", os.getenv("DB_IP", "127.0.0.1"))
DB_PORT = int(os.getenv("BATCH_DB_PORT", os.getenv("DB_PORT", "13306")))
DB_USER = os.getenv("BATCH_DB_USER", os.getenv("DB_USER_ID", "ln-admin"))
DB_PASSWORD = os.getenv("BATCH_DB_PASSWORD", os.getenv("DB_USER_PW", ""))
DB_NAME = os.getenv("BATCH_DB_NAME", "likenovel")

SYSTEM_PROMPT = """당신은 웹소설 회차를 검색용 요약 JSON으로 변환하는 전처리기다.
반드시 유효한 JSON만 반환하라. 설명 문장, 코드블록, 머리말을 붙이지 마라.

핵심 목표
- 이 요약만 보고도 해당 회차를 다시 찾을 수 있어야 한다.
- 요약이 예쁜 문장일 필요는 없고, 검색 가치가 높은 사실이 우선이다.

규칙
1. 사실만 쓴다. 감상, 평가, 추측, 분위기 설명 금지.
2. 원문에 없는 인물, 사건, 수치, 설정을 만들지 마라.
3. 고유명사, 능력명, 장비명, 세력명, 수치, 제약, 선택을 원문 표현에 가깝게 최대한 보존하라.
4. key_events는 반드시 "누가 무엇을 했고 어떤 결과가 났는지"가 보이는 구체 사건 3개를 쓴다.
5. 추상 표현을 피하라. "갈등 심화", "긴장 고조", "위기", "변화", "성장", "결심" 같은 표현 단독 사용 금지.
6. characters에는 이 화에서 중요한 인물만 넣고, 불필요한 외형 수식어는 빼라.
7. settings에는 장소, 능력, 장비, 세력, 규칙만 넣고 장면 소품이나 배경 장식은 넣지 마라.
8. choices에는 서사적으로 의미 있는 결정만 넣고, 없으면 빈 배열로 둔다.
9. keywords는 5~8개를 목표로 하고, 추상어보다 고유명사/능력명/사건 앵커를 우선하라.
10. 정보가 부족하다고 느껴져도 비워 두지 말고, 원문에서 검색 가치가 높은 구체 사실을 더 추출하라.

반환 JSON 스키마
{
  "episode_title_label": "문자열",
  "key_events": ["문자열", "문자열", "문자열"],
  "characters": ["문자열"],
  "settings": ["문자열"],
  "choices": ["문자열"],
  "keywords": ["문자열"]
}
"""

GLM_PERSON_LIKE_KEYWORDS = (
    "남자",
    "여자",
    "소년",
    "소녀",
    "주인공",
    "요원",
    "경비",
    "기사",
    "간수",
    "수감자",
    "엘프",
    "마법사",
    "병사",
)
GLM_SCENE_NOISE_KEYWORDS = (
    "복도",
    "천장",
    "전등",
    "바닥",
    "벽",
    "창문",
    "문",
    "발소리",
    "눈동자",
    "머리카락",
)
GLM_SETTING_LIKE_KEYWORDS = (
    "능력",
    "마력",
    "마법",
    "초커",
    "억제",
    "감옥",
    "기지",
    "전쟁",
    "저격총",
    "각성",
    "세력",
    "룰",
    "제약",
)


def db_connect():
    if not DB_USER or not DB_PASSWORD:
        raise RuntimeError("DB 접속 정보가 비어 있습니다.")
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        autocommit=False,
        client_flag=CLIENT.MULTI_STATEMENTS,
        cursorclass=DictCursor,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenRouter episode summary 모델 비교")
    parser.add_argument("--product-id", type=int, action="append", dest="product_ids", help="작품 ID. 여러 번 지정 가능")
    parser.add_argument("--episode-id", type=int, action="append", dest="episode_ids", help="회차 ID. 여러 번 지정 가능")
    parser.add_argument("--limit", type=int, default=8, help="최대 회차 수")
    parser.add_argument("--models", type=str, default=",".join(DEFAULT_MODELS), help="쉼표 구분 모델 목록")
    parser.add_argument("--output", type=str, default="/tmp/story_agent_summary_model_compare.json", help="결과 JSON 경로")
    parser.add_argument("--verbose", action="store_true", help="상세 로그 출력")
    return parser.parse_args()


def extract_json_object(text: str) -> dict[str, Any]:
    if isinstance(text, list):
        raw = "\n".join(str(item) for item in text if str(item).strip()).strip()
    else:
        raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty content")

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("json object not found")

    return json.loads(raw[start:end + 1])


def extract_message_content(message: dict[str, Any]) -> str:
    primary = message.get("content")
    if primary:
        return str(primary)

    reasoning = message.get("reasoning")
    if reasoning:
        return str(reasoning)

    reasoning_details = message.get("reasoning_details")
    if isinstance(reasoning_details, list):
        parts: list[str] = []
        for item in reasoning_details:
            text = ""
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
            elif item:
                text = str(item).strip()
            if text:
                parts.append(text)
        if parts:
            return "\n".join(parts)

    return ""


def normalize_string_list(value: Any, *, limit: int, min_items: int = 0) -> list[str]:
    if isinstance(value, list):
        normalized = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str) and value.strip():
        normalized = [item.strip() for item in value.split(",") if item.strip()]
    else:
        normalized = []
    normalized = normalized[:limit]
    if min_items and len(normalized) < min_items:
        normalized.extend([""] * (min_items - len(normalized)))
    return normalized


def validate_summary_payload(payload: dict[str, Any]) -> tuple[bool, dict[str, Any], list[str]]:
    issues: list[str] = []
    normalized = {
        "episode_title_label": str(payload.get("episode_title_label") or "").strip(),
        "key_events": normalize_string_list(payload.get("key_events"), limit=3, min_items=3),
        "characters": normalize_string_list(payload.get("characters"), limit=8),
        "settings": normalize_string_list(payload.get("settings"), limit=8),
        "choices": normalize_string_list(payload.get("choices"), limit=5),
        "keywords": normalize_string_list(payload.get("keywords"), limit=8, min_items=5),
    }
    if not normalized["episode_title_label"]:
        issues.append("missing_episode_title_label")
    if not any(item for item in normalized["key_events"]):
        issues.append("missing_key_events")
    if not any(item for item in normalized["keywords"]):
        issues.append("missing_keywords")
    return len(issues) == 0, normalized, issues


def _postprocess_glm_list_item(item: str) -> str:
    text = str(item or "").strip()
    if not text:
        return ""

    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*\([^)]{1,40}\)\s*$", "", text).strip()

    for sep in (" - ", " — ", " – ", " : ", ": "):
        if sep in text:
            head, tail = text.split(sep, 1)
            head = head.strip()
            tail = tail.strip()
            if head and tail and len(head) <= 32:
                text = head
                break

    text = re.sub(r"\s+", " ", text).strip(" -:;,")
    return text


def apply_model_postprocess(
    *,
    model: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not model.startswith("z-ai/glm-5"):
        return payload

    processed = dict(payload)
    for key in ("characters", "settings", "choices", "keywords"):
        value = processed.get(key)
        if isinstance(value, list):
            items = [_postprocess_glm_list_item(item) for item in value]
            deduped: list[str] = []
            seen: set[str] = set()
            for item in items:
                normalized = item.strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                deduped.append(normalized)
            processed[key] = deduped
        elif isinstance(value, str):
            processed[key] = _postprocess_glm_list_item(value)

    processed["characters"] = _postprocess_glm_characters(processed.get("characters"))
    processed["settings"] = _postprocess_glm_settings(processed.get("settings"))
    processed["keywords"] = _postprocess_glm_keywords(processed.get("keywords"))

    return processed


def _dedupe_strings(items: list[str], *, limit: int) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return deduped


def _postprocess_glm_characters(value: Any) -> list[str]:
    items = normalize_string_list(value, limit=8)
    filtered: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        if " 내 " in text or text.endswith("들"):
            continue
        if any(keyword in text for keyword in GLM_SCENE_NOISE_KEYWORDS):
            continue
        if any(keyword in text for keyword in GLM_PERSON_LIKE_KEYWORDS) or len(text) <= 6:
            filtered.append(text)
    return _dedupe_strings(filtered, limit=6)


def _postprocess_glm_settings(value: Any) -> list[str]:
    items = normalize_string_list(value, limit=8)
    filtered: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        if any(keyword in text for keyword in GLM_SETTING_LIKE_KEYWORDS):
            filtered.append(text)
            continue
        if any(keyword in text for keyword in GLM_SCENE_NOISE_KEYWORDS):
            continue
        if len(text) <= 12:
            filtered.append(text)
    return _dedupe_strings(filtered, limit=6)


def _postprocess_glm_keywords(value: Any) -> list[str]:
    items = normalize_string_list(value, limit=10)
    filtered = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        if len(text) > 18 and not any(keyword in text for keyword in GLM_SETTING_LIKE_KEYWORDS):
            continue
        filtered.append(text)
    return _dedupe_strings(filtered, limit=8)


def build_user_prompt(row: dict[str, Any], normalized_text: str) -> str:
    title = str(row.get("title") or "").strip()
    episode_no = int(row.get("episode_no") or 0)
    episode_title = str(row.get("episode_title") or "").strip()
    return (
        f"작품명: {title}\n"
        f"회차 표기: {episode_no}화\n"
        f"회차 제목: {episode_title}\n"
        f"원문:\n{normalized_text[:MAX_EPISODE_CHARS]}"
    )


def build_target_query(args: argparse.Namespace) -> tuple[str, list[object]]:
    where = [
        "p.price_type = 'free'",
        "pe.use_yn = 'Y'",
        "pe.episode_content IS NOT NULL",
        "TRIM(pe.episode_content) <> ''",
    ]
    params: list[object] = []

    if args.product_ids:
        placeholders = ", ".join(["%s"] * len(args.product_ids))
        where.append(f"p.product_id IN ({placeholders})")
        params.extend(args.product_ids)

    if args.episode_ids:
        placeholders = ", ".join(["%s"] * len(args.episode_ids))
        where.append(f"pe.episode_id IN ({placeholders})")
        params.extend(args.episode_ids)

    limit_sql = f" LIMIT {int(args.limit)}" if args.limit and args.limit > 0 else ""
    query = f"""
        SELECT
            p.product_id,
            p.title,
            pe.episode_id,
            pe.episode_no,
            pe.episode_title,
            pe.episode_content
        FROM tb_product p
        JOIN tb_product_episode pe
          ON pe.product_id = p.product_id
        WHERE {' AND '.join(where)}
        ORDER BY p.product_id ASC, pe.episode_no ASC
        {limit_sql}
    """
    return query, params


def normalize_episode_html(html_content: str) -> str:
    soup = BeautifulSoup(html_content or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text(separator="\n")
    text = text.replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    paragraphs: list[str] = []
    blank_open = False
    for line in lines:
        if not line:
            if paragraphs and not blank_open:
                paragraphs.append("")
                blank_open = True
            continue
        paragraphs.append(line)
        blank_open = False
    normalized = "\n".join(paragraphs).strip()
    return re.sub(r"\n{3,}", "\n\n", normalized)


async def call_openrouter_summary(
    client: httpx.AsyncClient,
    *,
    model: str,
    row: dict[str, Any],
    normalized_text: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    response = await client.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "X-Title": "LikeNovel Story Agent Summary Compare",
        },
        json={
            "model": model,
            "temperature": 0.1,
            "max_completion_tokens": MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(row, normalized_text)},
            ],
        },
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    response.raise_for_status()
    payload = response.json()
    message = payload.get("choices", [{}])[0].get("message", {})
    content = extract_message_content(message)
    parsed = extract_json_object(content)
    parsed = apply_model_postprocess(model=model, payload=parsed)
    schema_pass, normalized_summary, schema_issues = validate_summary_payload(parsed)
    return {
        "model": model,
        "latency_ms": latency_ms,
        "usage": payload.get("usage"),
        "schema_pass": schema_pass,
        "schema_issues": schema_issues,
        "summary_json": normalized_summary,
        "raw_content": content,
    }


def fetch_target_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    conn = db_connect()
    try:
        with conn.cursor() as cur:
            query, params = build_target_query(args)
            cur.execute(query, params)
            return list(cur.fetchall())
    finally:
        conn.close()


def load_existing_rows(output_path: Path, *, models: list[str]) -> list[dict[str, Any]]:
    if not output_path.exists():
        return []
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []

    rows = payload.get("rows")
    if not isinstance(rows, list):
        return []

    requested = set(models)
    restored: list[dict[str, Any]] = []
    for row in rows:
        results = row.get("results")
        if not isinstance(results, list):
            continue
        done = {str(result.get("model") or "") for result in results if result.get("model")}
        if requested.issubset(done):
            restored.append(row)
    return restored


def write_snapshot(*, output_path: Path, models: list[str], rows: list[dict[str, Any]]) -> None:
    output_path.write_text(
        json.dumps(
            {
                "models": models,
                "summary": build_summary(rows),
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def build_comparison_rows(args: argparse.Namespace) -> list[dict[str, Any]]:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY가 비어 있습니다.")

    models = [item.strip() for item in args.models.split(",") if item.strip()]
    output_path = Path(args.output)
    rows = fetch_target_rows(args)
    existing_rows = load_existing_rows(output_path, models=models)
    done_episode_ids = {int(row.get("episode_id") or 0) for row in existing_rows}
    results: list[dict[str, Any]] = list(existing_rows)

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        for row in rows:
            if int(row["episode_id"]) in done_episode_ids:
                if args.verbose:
                    print(
                        f"[compare] product_id={row['product_id']} episode_id={row['episode_id']} "
                        f"episode_no={row['episode_no']} skip=checkpoint"
                    )
                continue
            normalized_text = normalize_episode_html(str(row.get("episode_content") or ""))
            model_results: list[dict[str, Any]] = []
            for model in models:
                try:
                    result = await call_openrouter_summary(
                        client,
                        model=model,
                        row=row,
                        normalized_text=normalized_text,
                    )
                except Exception as exc:  # noqa: BLE001
                    result = {
                        "model": model,
                        "error": str(exc),
                        "schema_pass": False,
                    }
                model_results.append(result)
                if args.verbose:
                    print(
                        f"[compare] product_id={row['product_id']} episode_id={row['episode_id']} "
                        f"episode_no={row['episode_no']} model={model} "
                        f"schema_pass={result.get('schema_pass')} latency_ms={result.get('latency_ms')}"
                    )

            results.append({
                "product_id": int(row["product_id"]),
                "product_title": str(row.get("title") or ""),
                "episode_id": int(row["episode_id"]),
                "episode_no": int(row["episode_no"]),
                "episode_title": str(row.get("episode_title") or ""),
                "source_type": "episode_content",
                "normalized_text_length": len(normalized_text),
                "results": model_results,
            })
            write_snapshot(output_path=output_path, models=models, rows=results)

    return results


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    model_stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        for result in row.get("results", []):
            model = str(result.get("model") or "unknown")
            current = model_stats.setdefault(
                model,
                {
                    "total": 0,
                    "success": 0,
                    "schema_pass": 0,
                    "errors": 0,
                    "avg_latency_ms": 0.0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                },
            )
            current["total"] += 1
            usage = result.get("usage") or {}
            current["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
            current["completion_tokens"] += int(usage.get("completion_tokens") or 0)
            if result.get("error"):
                current["errors"] += 1
                continue
            current["success"] += 1
            if result.get("schema_pass"):
                current["schema_pass"] += 1
            current["avg_latency_ms"] += float(result.get("latency_ms") or 0.0)

    for stats in model_stats.values():
        if stats["success"] > 0:
            stats["avg_latency_ms"] = round(stats["avg_latency_ms"] / stats["success"], 1)
        else:
            stats["avg_latency_ms"] = None
    return model_stats


async def async_main() -> int:
    args = parse_args()
    rows = await build_comparison_rows(args)
    summary = build_summary(rows)
    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(
            {
                "models": [item.strip() for item in args.models.split(",") if item.strip()],
                "summary": summary,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output_path), "summary": summary}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
