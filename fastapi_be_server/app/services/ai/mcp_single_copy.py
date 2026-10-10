"""Paid-slot copy core migrated from the existing operator, with no CLI or CMS writes."""

from __future__ import annotations

import hashlib

import json

import re

import random

import time

from datetime import datetime, timedelta

from http.client import HTTPException

from pathlib import Path

from typing import Any, Callable, Iterable, Iterator

from urllib import error as urlerror

from urllib import request

from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

OPENROUTER_MODEL = "google/gemini-3.8-flash"

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

OPENROUTER_MAX_TOKENS = 24_000

OPENROUTER_IDLE_TIMEOUT = 60

OPENROUTER_TOTAL_TIMEOUT = 600

DEFAULT_OPENROUTER_API_KEY_FILE = (
    Path.home() / ".config" / "likenovel" / "openrouter-api-key"
)

EFFORT = "high"

REQUIRED_COUNT = 3

from app.services.ai.mcp_policy import SINGLE_KEYS as SLOT_KEYS

FORBIDDEN_PERSON_TERMS = (
    "주인공",
    "청년",
    "소녀",
    "남자",
    "여자",
    "사장",
    "재무관",
    "검도선수",
    "그녀",
    "이자",
    "인물",
)

FORBIDDEN_MARKS = ("#", "…", "→", "←", "?", "\"", "“", "”")

STIFF_GENRE_TERMS = ("권력", "나락", "기연", "응징", "처절", "위선자")

KNOWN_DEFAULT_COVER_SHA256 = {
    "8516d5cc2964170ba03b8e423df1ad75ceca354bdfaf105e11092f6b90c99415",
}

PERSON_PRONOUN_RE = re.compile(
    r"(?<![가-힣A-Za-z0-9])그(?:들)?(?:에게서|한테서|로부터|에게|한테|로서|하고|가|은|는|의|를|도|만|와|과|랑|로|조차|마저)?(?:은|는|도|만)?(?=$|[\s,.!])"
)

GROUNDING_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")

GROUNDING_SUFFIXES = (
    "으로부터",
    "에게서",
    "한테서",
    "으로",
    "로부터",
    "에서",
    "까지",
    "부터",
    "처럼",
    "보다",
    "에게",
    "한테",
    "로서",
    "을",
    "를",
    "이",
    "가",
    "은",
    "는",
    "의",
    "도",
    "만",
    "와",
    "과",
    "에",
    "로",
)

GROUNDING_STOPWORDS = {"모든", "다시", "시작", "이제", "것이", "있다", "없다"}

AGY_DIAGNOSTIC_OMIT_KEYS = {"status", "prompt", "input", "messages"}

DIAGNOSTIC_AUTH_RE = re.compile(
    r"(?im)(\bauthorization\s*:\s*)[^\r\n]+"
)

DIAGNOSTIC_COOKIE_RE = re.compile(
    r"(?im)(\b(?:cookie|set-cookie)\s*:\s*)[^\r\n]+"
)

DIAGNOSTIC_SECRET_RE = re.compile(
    r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|auth|password|passwd|"
    r"credential|private[_-]?key|client[_-]?secret|session(?:[_-]?(?:id|token|key))?|"
    r"cookie|secret)\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)

DIAGNOSTIC_SECRET_KEY_RE = re.compile(
    r"(?i)(authorization|api[_-]?key|(?:access|refresh|id|auth|bearer)[_-]?token|token|auth|"
    r"password|passwd|credentials?|private[_-]?key|client[_-]?secret|"
    r"session(?:[_-]?(?:id|token|key|cookie))?|cookies?|secret)"
)

CANDIDATE_SQL = """
SELECT
  p.product_id,
  HEX(p.title) AS title_hex,
  HEX(COALESCE(p.synopsis_text, '')) AS synopsis_hex,
  p.price_type,
  p.product_type,
  p.status_code,
  p.open_yn,
  COALESCE(p.blind_yn, 'N') AS blind_yn,
  p.ratings_code,
  COALESCE(p.paid_open_date, p.created_date) AS paid_open_at,
  HEX(COALESCE(cf.cover_image_path, '')) AS cover_image_path_hex,
  ep.open_episode_count,
  ep.latest_episode_no,
  COALESCE(p.count_hit, 0) AS count_hit,
  COALESCE(p.count_bookmark, 0) AS count_bookmark,
  COALESCE(hist.history_count, 0) AS history_count,
  hist.last_single_slot_at
FROM tb_product p
INNER JOIN (
  SELECT
    product_id,
    COUNT(*) AS open_episode_count,
    MAX(episode_no) AS latest_episode_no
  FROM tb_product_episode
  WHERE use_yn = 'Y'
    AND open_yn = 'Y'
    AND (publish_reserve_date IS NULL OR publish_reserve_date <= NOW())
  GROUP BY product_id
) ep ON ep.product_id = p.product_id
LEFT JOIN (
  SELECT cf.file_group_id, MAX(cfi.file_path) AS cover_image_path
  FROM tb_common_file cf
  JOIN tb_common_file_item cfi ON cfi.file_group_id = cf.file_group_id
  WHERE cf.use_yn = 'Y'
    AND cfi.use_yn = 'Y'
    AND cf.group_type = 'cover'
  GROUP BY cf.file_group_id
) cf ON cf.file_group_id = p.thumbnail_file_id
LEFT JOIN (
  SELECT
    product_id,
    COUNT(*) AS history_count,
    MAX(publish_start_at) AS last_single_slot_at
  FROM tb_main_single_slot
  GROUP BY product_id
) hist ON hist.product_id = p.product_id
WHERE p.price_type = 'paid'
  AND p.product_type = 'normal'
  AND p.status_code = 'ongoing'
  AND p.open_yn = 'Y'
  AND COALESCE(p.blind_yn, 'N') = 'N'
  AND p.ratings_code = 'all'
  AND COALESCE(ep.open_episode_count, 0) > 0
  AND COALESCE(cf.cover_image_path, '') != ''
  AND COALESCE(p.synopsis_text, '') != ''
  AND NOT EXISTS (
    SELECT 1
    FROM tb_main_single_slot active
    WHERE active.product_id = p.product_id
      AND active.cancelled_at IS NULL
      AND active.publish_start_at <= NOW()
      AND (active.publish_end_at IS NULL OR active.publish_end_at > NOW())
  )
ORDER BY
  CASE WHEN COALESCE(hist.history_count, 0) = 0 THEN 0 ELSE 1 END,
  COALESCE(p.paid_open_date, p.created_date) DESC,
  p.count_bookmark DESC,
  p.count_hit DESC,
  p.product_id DESC
""".strip()

class ProposalError(RuntimeError):
    pass

class CopyValidationError(ProposalError):
    pass

def _redact_diagnostic_string(value: str) -> str:
    redacted = DIAGNOSTIC_COOKIE_RE.sub(r"\1[REDACTED]", value)
    redacted = DIAGNOSTIC_AUTH_RE.sub(r"\1[REDACTED]", redacted)
    return DIAGNOSTIC_SECRET_RE.sub(r"\1[REDACTED]", redacted)

def _redact_diagnostic_value(value: Any, key: str | None = None) -> Any:
    if key and key.casefold() in AGY_DIAGNOSTIC_OMIT_KEYS:
        return "[OMITTED]"
    if key and DIAGNOSTIC_SECRET_KEY_RE.fullmatch(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(child_key): _redact_diagnostic_value(child_value, str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_diagnostic_value(item) for item in value]
    if isinstance(value, str):
        return _redact_diagnostic_string(value)
    return value

def _safe_diagnostic_text(
    value: Any,
    limit: int = 1200,
    *,
    key: str | None = None,
) -> str:
    value = _redact_diagnostic_value(value, key)
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            text = _redact_diagnostic_string(repr(value))
    return text.strip()[:limit]

def _decode_hex(value: Any, name: str, *, allow_empty: bool = False) -> str:
    try:
        decoded = bytes.fromhex(str(value or "")).decode("utf-8")
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ProposalError(f"{name} is not valid UTF-8 hex") from exc
    normalized = decoded.strip()
    if not normalized and not allow_empty:
        raise ProposalError(f"{name} is empty")
    return normalized

def _parse_datetime(value: Any, name: str) -> datetime | None:
    if value in (None, "", "NULL"):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("T", " "))
    except ValueError as exc:
        raise ProposalError(f"{name} is not a valid datetime") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)

def rows_to_candidates(rows: Iterable[list[Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        if len(row) != 17:
            raise ProposalError(
                f"candidate column drift: expected 17 values, got {len(row)}"
            )
        try:
            product_id = int(row[0])
            open_episode_count = int(row[11])
            latest_episode_no = int(row[12])
            count_hit = int(row[13] or 0)
            count_bookmark = int(row[14] or 0)
            history_count = int(row[15] or 0)
        except (TypeError, ValueError) as exc:
            raise ProposalError("candidate row contains an invalid integer") from exc
        if product_id <= 0 or product_id in seen:
            raise ProposalError("candidate row has an invalid or duplicate product_id")
        seen.add(product_id)
        expected = {
            "price_type": "paid",
            "product_type": "normal",
            "status_code": "ongoing",
            "open_yn": "Y",
            "blind_yn": "N",
            "ratings_code": "all",
        }
        actual = {
            "price_type": str(row[3]),
            "product_type": str(row[4]),
            "status_code": str(row[5]),
            "open_yn": str(row[6]),
            "blind_yn": str(row[7]),
            "ratings_code": str(row[8]),
        }
        if actual != expected:
            raise ProposalError(
                f"candidate {product_id} violates paid-only eligibility: {actual}"
            )
        if open_episode_count <= 0 or latest_episode_no <= 0:
            raise ProposalError(f"candidate {product_id} has no public episode")
        candidates.append(
            {
                "product_id": product_id,
                "title": _decode_hex(row[1], "title"),
                "synopsis": _decode_hex(row[2], "synopsis"),
                **actual,
                "paid_open_at": _parse_datetime(row[9], "paid_open_at"),
                "cover_image_path": _decode_hex(row[10], "cover_image_path"),
                "open_episode_count": open_episode_count,
                "latest_episode_no": latest_episode_no,
                "count_hit": count_hit,
                "count_bookmark": count_bookmark,
                "history_count": history_count,
                "last_single_slot_at": _parse_datetime(
                    row[16], "last_single_slot_at"
                ),
            }
        )
    return candidates

def empty_state() -> dict[str, Any]:
    return {
        "version": 1,
        "last_proposed_at": {},
        "last_run_date": None,
        "last_snapshot": None,
    }

def _combined_last_seen(
    candidate: dict[str, Any], proposed_at: dict[str, Any]
) -> datetime | None:
    values = [candidate.get("last_single_slot_at")]
    proposed = proposed_at.get(str(candidate["product_id"]))
    if proposed:
        values.append(_parse_datetime(proposed, "last_proposed_at"))
    present = [value for value in values if isinstance(value, datetime)]
    return max(present) if present else None

def rank_candidates(
    candidates: Iterable[dict[str, Any]], state: dict[str, Any],
    *, now: datetime | None = None,
) -> list[dict[str, Any]]:
    proposed_at = state["last_proposed_at"]
    current = now if now is not None else datetime.now(KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    cutoff = current - timedelta(days=7)
    ranked = []
    for candidate in candidates:
        last_seen = _combined_last_seen(candidate, proposed_at)
        if last_seen is None or last_seen <= cutoff:
            ranked.append(candidate)
    # All cooldown-eligible works have equal opportunity, regardless of age or views.
    random.shuffle(ranked)
    return ranked

def cover_is_eligible(metadata: dict[str, Any]) -> tuple[bool, str | None]:
    sha256 = str(metadata.get("sha256") or "").lower()
    if sha256 in KNOWN_DEFAULT_COVER_SHA256:
        return False, "cover_known_default_fingerprint"
    cover_url = str(metadata.get("url") or "").lower()
    if "default" in cover_url or "placeholder" in cover_url:
        return False, "cover_default_path"
    if metadata["bytes"] < 10_000:
        return False, "cover_under_10kb"
    width, height = metadata["size"]
    if width < 300 or height < 400:
        return False, "cover_dimensions_too_small"
    if metadata["sample_colors"] < 200:
        return False, "cover_low_color_count"
    mean = metadata.get("mean")
    if (
        isinstance(mean, list)
        and len(mean) == 3
        and min(float(value) for value in mean) >= 235
        and metadata["sample_colors"] < 800
    ):
        return False, "cover_pale_placeholder"
    if height <= width:
        return False, "cover_not_portrait"
    return True, None

def inspect_cover(url: str, timeout: int = 25) -> dict[str, Any]:
    try:
        from PIL import Image, ImageStat
        from io import BytesIO
    except ImportError as exc:
        raise ProposalError("Pillow is required for cover validation") from exc
    cover_url = url if url.startswith(("http://", "https://")) else (
        f"https://cdn.likenovel.net/{url.lstrip('/')}"
    )
    from urllib.parse import urlsplit
    parsed = urlsplit(cover_url)
    if parsed.scheme != "https" or parsed.hostname != "cdn.likenovel.net" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ProposalError("Only the LikeNovel HTTPS CDN is allowed")
    req = request.Request(
        cover_url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.likenovel.net/"},
    )
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ProposalError("Cover redirects are not allowed")

    try:
        with request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            if response.geturl().split("/")[2] != "cdn.likenovel.net":
                raise ProposalError("Unexpected cover redirect")
            raw = response.read(20_000_001)
            if len(raw) > 20_000_000:
                raise ProposalError("Cover exceeds size limit")
        image = Image.open(BytesIO(raw))
        if image.width * image.height > 20_000_000:
            raise ProposalError("Cover exceeds pixel limit")
        image = image.convert("RGB")
    except Exception as exc:
        raise ProposalError(f"cover fetch failed: {type(exc).__name__}") from exc
    small = image.resize((64, 64))
    metadata = {
        "url": cover_url,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "size": [image.width, image.height],
        "sample_colors": len(small.getcolors(maxcolors=4096) or []),
        "mean": [round(value, 2) for value in ImageStat.Stat(small).mean],
    }
    eligible, reason = cover_is_eligible(metadata)
    metadata["eligible"] = eligible
    metadata["reason"] = reason
    return metadata

def select_cover_valid_candidates(
    candidates: Iterable[dict[str, Any]], required_count: int = REQUIRED_COUNT
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            evidence = inspect_cover(candidate["cover_image_path"])
        except ProposalError as exc:
            rejected.append(
                {
                    "product_id": candidate["product_id"],
                    "title": candidate["title"],
                    "reason": str(exc),
                }
            )
            continue
        if not evidence["eligible"]:
            rejected.append(
                {
                    "product_id": candidate["product_id"],
                    "title": candidate["title"],
                    "reason": evidence["reason"],
                }
            )
            continue
        item = dict(candidate)
        item["cover_evidence"] = evidence
        selected.append(item)
        if len(selected) == required_count:
            break
    return selected, rejected

def _episode_sql(product_ids: list[int]) -> str:
    if not product_ids or any(product_id <= 0 for product_id in product_ids):
        raise ProposalError("episode evidence requires positive product ids")
    values = ",".join(str(product_id) for product_id in product_ids)
    return f"""
SELECT
  e.product_id,
  e.episode_no,
  HEX(COALESCE(e.episode_title, '')) AS episode_title_hex
FROM tb_product_episode e
JOIN (
  SELECT product_id, MAX(episode_no) AS max_episode_no
  FROM tb_product_episode
  WHERE use_yn = 'Y'
    AND open_yn = 'Y'
    AND (publish_reserve_date IS NULL OR publish_reserve_date <= NOW())
    AND product_id IN ({values})
  GROUP BY product_id
) latest ON latest.product_id = e.product_id
WHERE e.use_yn = 'Y'
  AND e.open_yn = 'Y'
  AND (e.publish_reserve_date IS NULL OR e.publish_reserve_date <= NOW())
  AND e.product_id IN ({values})
  AND (e.episode_no <= 5 OR e.episode_no > latest.max_episode_no - 3)
ORDER BY e.product_id, e.episode_no
""".strip()

def build_gemini_prompt(
    selected: list[dict[str, Any]], episode_evidence: dict[int, list[str]]
) -> str:
    sources = [
        {
            "productId": item["product_id"],
            "title": item["title"],
            "synopsis": item["synopsis"],
            "episodeTitles": episode_evidence[item["product_id"]],
        }
        for item in selected
    ]
    source_json = json.dumps(sources, ensure_ascii=False)
    return f"""라이크노벨 홈 단일구좌에 쓸 한국어 훅 문구를 작성한다.

입력 작품마다 후보 문구 5안과 recommendedIndex를 반환한다.

문체 기준:
- 웹소설 독자에게 말하듯 자연스럽고 장면이 바로 떠올라야 한다.
- 설정 요약문, 보도문, 기획서처럼 쓰지 않는다.
- 추상명사를 연달아 쌓지 않고 두 줄 모두 한다로 끝내지 않는다.
- 권력, 나락, 기연, 응징, 처절, 위선자 같은 딱딱한 장르어는 한 문구에 최대 하나만 쓴다.
- 첫 줄부터 사건·반전·새 규칙에 들어가고 둘째 줄은 읽는 쾌감이나 핵심 작동 방식을 보여준다.
- 인물 소개 없이 작품을 클릭할 이유에 집중한다.

금지 기준:
- 등장인물 고유명사 금지.
- 주인공, 청년, 소녀, 남자, 여자, 사장, 재무관, 검도선수, 그, 그녀, 이자, 인물 같은 인물 지칭 금지.
- 제목 전체 반복, 따옴표, 해시태그, 말줄임표, 화살표, 의문문 금지.
- 입력 근거에 없는 설정·능력·관계·목표 생성 금지.

형식 기준:
- 각 문구는 정확히 두 줄이다.
- 각 줄은 공백과 문장부호를 포함해 8~24자다.
- 글자 수와 근거 일치는 외부 검증기가 검사한다. charCounts는 반환하지 않는다.
- 조건에 맞는 자연스러운 문구 5안을 작성하고, 같은 안을 반복 최적화하지 않는다.
- evidence는 입력 synopsis 또는 episodeTitles에서 글자 하나 바꾸지 않고 그대로 복사한 1~3개의 짧은 문구다.
- summaryText의 첫째 줄과 둘째 줄에는 각각 evidence에 실제로 있는 2자 이상의 핵심어가 최소 하나씩 들어간다.
- 5안 중 최소 2안은 첫째 줄을 `다`로 끝내지 않아야 한다.
- recommendedIndex는 1부터 시작한다.
- 마크다운 없이 JSON 하나만 반환한다.
- results는 입력 productId와 같은 순서와 개수여야 한다.

출력 스키마:
{{"results":[{{"productId":1,"recommendedIndex":1,"variants":[{{"summaryText":"첫줄\\n둘째줄","evidence":["근거"]}}]}}]}}

입력:
{source_json}"""

def _parse_inner_json(value: str) -> dict[str, Any]:
    normalized = value.strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        normalized = "\n".join(lines).strip()
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise CopyValidationError("Gemini response body is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise CopyValidationError("Gemini response root is not an object")
    return payload

def _openrouter_error_detail(payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error", payload)
        if isinstance(error, dict):
            allowed = {
                key: error[key]
                for key in ("code", "message", "type", "provider_name")
                if error.get(key) not in (None, "")
            }
            if allowed:
                return _safe_diagnostic_text(allowed, limit=800)
    return "details=unavailable"

def _openrouter_stream_events(
    response: Any, started_at: float, total_timeout: int
) -> Iterator[str]:
    data_lines: list[str] = []
    while True:
        elapsed = time.monotonic() - started_at
        if elapsed >= total_timeout:
            raise ProposalError(
                f"OpenRouter timeout: stage=stream_deadline; elapsed_s={elapsed:.1f}; "
                f"total_timeout_s={total_timeout}; model={OPENROUTER_MODEL}"
            )
        raw_line = response.readline()
        elapsed = time.monotonic() - started_at
        if elapsed >= total_timeout:
            raise ProposalError(
                f"OpenRouter timeout: stage=stream_deadline; elapsed_s={elapsed:.1f}; "
                f"total_timeout_s={total_timeout}; model={OPENROUTER_MODEL}"
            )
        if not raw_line:
            raise ProposalError("OpenRouter incomplete stream: EOF before [DONE]")
        try:
            line = raw_line.decode("utf-8").rstrip("\r\n")
        except UnicodeDecodeError as exc:
            raise ProposalError("OpenRouter stream contains invalid UTF-8") from exc
        # SSE comments are keepalives, and data may span multiple lines.
        if not line:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines.clear()
        elif not line.startswith(":"):
            field, separator, value = line.partition(":")
            if field == "data":
                data_lines.append(value.removeprefix(" ") if separator else "")

def _read_openrouter_stream(
    response: Any, started_at: float, total_timeout: int
) -> dict[str, Any]:
    fragments: list[str] = []
    finish_reason: str | None = None
    diagnostics: dict[str, Any] = {}
    for event in _openrouter_stream_events(response, started_at, total_timeout):
        if event == "[DONE]":
            if finish_reason == "length":
                diagnostics["content_chars"] = sum(len(part) for part in fragments)
                raise CopyValidationError(
                    "OpenRouter response truncated: finish_reason=length; "
                    f"max_tokens={OPENROUTER_MAX_TOKENS}; "
                    f"{_safe_diagnostic_text(diagnostics)}"
                )
            if finish_reason != "stop":
                raise ProposalError("OpenRouter incomplete stream: missing stop before [DONE]")
            content = "".join(fragments)
            if not content.strip():
                raise CopyValidationError("OpenRouter response text is missing")
            return _parse_inner_json(content)
        try:
            payload = json.loads(event)
        except json.JSONDecodeError as exc:
            raise ProposalError("OpenRouter stream returned invalid event JSON") from exc
        if not isinstance(payload, dict):
            raise ProposalError("OpenRouter stream event root is not an object")
        if payload.get("error"):
            raise ProposalError(
                f"OpenRouter stream failed: {_openrouter_error_detail(payload)}"
            )
        generation_id = payload.get("id")
        if (
            isinstance(generation_id, str)
            and re.fullmatch(r"gen-[A-Za-z0-9_-]{1,150}", generation_id)
        ):
            diagnostics["generation_id"] = generation_id
        usage = payload.get("usage")
        if isinstance(usage, dict):
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(field)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    diagnostics[field] = value
            details = usage.get("completion_tokens_details")
            if isinstance(details, dict):
                value = details.get("reasoning_tokens")
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    diagnostics["reasoning_tokens"] = value
        choices = payload.get("choices")
        if choices == [] and isinstance(payload.get("usage"), dict):
            continue
        if not isinstance(choices, list) or len(choices) != 1:
            raise ProposalError("OpenRouter stream must contain exactly one choice")
        choice = choices[0]
        if not isinstance(choice, dict) or choice.get("index") != 0:
            raise ProposalError("OpenRouter stream choice index must be zero")
        reason = choice.get("finish_reason")
        if reason not in (None, "stop", "length"):
            raise ProposalError(
                f"OpenRouter stream failed: finish_reason={_safe_diagnostic_text(reason)}"
            )
        if finish_reason and reason is not None and reason != finish_reason:
            raise ProposalError("OpenRouter stream finish_reason changed after completion")
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            raise ProposalError("OpenRouter stream delta is not an object")
        content = delta.get("content")
        if content is not None and not isinstance(content, str):
            raise ProposalError("OpenRouter stream content is not text")
        if content:
            if finish_reason is not None:
                raise ProposalError("OpenRouter stream contains content after completion")
            fragments.append(content)
        if reason is not None:
            finish_reason = reason
    raise ProposalError("OpenRouter incomplete stream: missing [DONE]")

def run_openrouter(
    api_key: str, prompt: str, timeout: int = OPENROUTER_IDLE_TIMEOUT
) -> dict[str, Any]:
    body = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "reasoning": {"effort": EFFORT},
        "temperature": 0.2,
        "max_tokens": OPENROUTER_MAX_TOKENS,
        "stream": True,
    }
    http_request = request.Request(
        OPENROUTER_API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "HTTP-Referer": "https://www.likenovel.net/",
            "X-OpenRouter-Title": "LikeNovel single-slot proposal automation",
        },
        method="POST",
    )
    started_at = time.monotonic()
    stage = "connect"

    def timeout_detail() -> str:
        return (
            f"OpenRouter timeout: stage={stage}; "
            f"elapsed_s={time.monotonic() - started_at:.1f}; "
            f"idle_timeout_s={timeout}; total_timeout_s={OPENROUTER_TOTAL_TIMEOUT}; "
            f"model={OPENROUTER_MODEL}"
        )

    try:
        with request.urlopen(http_request, timeout=timeout) as response:
            stage = "stream_read"
            return _read_openrouter_stream(
                response, started_at, OPENROUTER_TOTAL_TIMEOUT
            )
    except TimeoutError as exc:
        raise ProposalError(timeout_detail()) from exc
    except urlerror.HTTPError as exc:
        try:
            raw_error = exc.read(65_536).decode("utf-8", errors="replace")
            error_payload: Any = json.loads(raw_error)
        except (OSError, HTTPException, json.JSONDecodeError):
            error_payload = None
        raise ProposalError(
            f"OpenRouter call failed: status={exc.code}; "
            f"{_openrouter_error_detail(error_payload)}"
        ) from exc
    except urlerror.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise ProposalError(timeout_detail()) from exc
        reason = _safe_diagnostic_text(exc.reason, limit=400)
        raise ProposalError(
            f"OpenRouter transport failed: stage={stage}; {reason}"
        ) from exc
    except (OSError, HTTPException) as exc:
        raise ProposalError(
            f"OpenRouter transport failed: stage={stage}; error_type={type(exc).__name__}"
        ) from exc

def validate_summary(summary: Any, title: str) -> tuple[bool, str | None, list[int]]:
    if not isinstance(summary, str):
        return False, "summary_not_string", []
    lines = summary.strip().splitlines()
    if len(lines) != 2 or any(not line.strip() for line in lines):
        return False, "summary_not_two_lines", [len(line) for line in lines]
    counts = [len(line) for line in lines]
    if any(count > 24 for count in counts):
        return False, "summary_line_too_long", counts
    if any(count < 8 for count in counts):
        return False, "summary_line_too_short", counts
    if title.strip() and title.strip() in summary:
        return False, "summary_repeats_title", counts
    if any(term in summary for term in FORBIDDEN_PERSON_TERMS):
        return False, "summary_has_person_reference", counts
    if PERSON_PRONOUN_RE.search(summary):
        return False, "summary_has_person_reference", counts
    if any(mark in summary for mark in FORBIDDEN_MARKS):
        return False, "summary_has_forbidden_mark", counts
    if sum(term in summary for term in STIFF_GENRE_TERMS) > 1:
        return False, "summary_stacks_stiff_genre_terms", counts
    if all(line.rstrip().endswith("다") for line in lines):
        return False, "summary_repeats_formal_ending", counts
    return True, None, counts

def validate_evidence(
    evidence: Any,
    candidate: dict[str, Any],
    episode_evidence: dict[int, list[str]],
) -> tuple[bool, list[str]]:
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 3:
        return False, []
    normalized = [str(item).strip() for item in evidence if isinstance(item, str)]
    if len(normalized) != len(evidence) or any(len(item) < 2 for item in normalized):
        return False, []
    source_texts = [candidate["synopsis"], *episode_evidence[candidate["product_id"]]]
    if any(not any(item in source for source in source_texts) for item in normalized):
        return False, []
    return True, normalized

def _grounding_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for token in GROUNDING_TOKEN_RE.findall(text):
        normalized = token.lower()
        for suffix in GROUNDING_SUFFIXES:
            if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 2:
                normalized = normalized[: -len(suffix)]
                break
        if len(normalized) >= 2 and normalized not in GROUNDING_STOPWORDS:
            terms.add(normalized)
    return terms

def summary_is_grounded(summary: str, evidence: list[str]) -> bool:
    evidence_terms = _grounding_terms(" ".join(evidence))
    return all(
        bool(_grounding_terms(line) & evidence_terms) for line in summary.splitlines()
    )

def choose_proposals(
    selected: list[dict[str, Any]],
    gemini_payload: dict[str, Any],
    episode_evidence: dict[int, list[str]],
) -> list[dict[str, Any]]:
    results = gemini_payload.get("results")
    if not isinstance(results, list) or len(results) != len(selected):
        raise CopyValidationError(
            "Gemini results count does not match selected products"
        )
    by_product: dict[int, dict[str, Any]] = {}
    for result in results:
        if not isinstance(result, dict):
            raise CopyValidationError("Gemini result is not an object")
        try:
            product_id = int(result.get("productId"))
        except (TypeError, ValueError) as exc:
            raise CopyValidationError("Gemini result has an invalid productId") from exc
        if product_id in by_product:
            raise CopyValidationError("Gemini returned duplicate productId")
        by_product[product_id] = result

    proposals: list[dict[str, Any]] = []
    for slot_key, candidate in zip(SLOT_KEYS, selected, strict=True):
        product_id = candidate["product_id"]
        result = by_product.get(product_id)
        if result is None:
            raise CopyValidationError(f"Gemini omitted product {product_id}")
        variants = result.get("variants")
        if not isinstance(variants, list) or not variants:
            raise CopyValidationError(
                f"Gemini returned no variants for product {product_id}"
            )
        valid: list[tuple[int, str, list[int], list[str]]] = []
        for index, variant in enumerate(variants, 1):
            if not isinstance(variant, dict):
                continue
            summary = variant.get("summaryText")
            ok, _, counts = validate_summary(summary, candidate["title"])
            evidence_ok, evidence = validate_evidence(
                variant.get("evidence"), candidate, episode_evidence
            )
            if ok and evidence_ok and summary_is_grounded(str(summary), evidence):
                valid.append((index, str(summary).strip(), counts, evidence))
        if not valid:
            raise CopyValidationError(
                f"Gemini produced no valid copy for product {product_id}"
            )
        try:
            recommended = int(result.get("recommendedIndex", 0))
        except (TypeError, ValueError):
            recommended = 0
        chosen = next((item for item in valid if item[0] == recommended), valid[0])
        proposals.append(
            {
                "slot_key": slot_key,
                "product_id": product_id,
                "title": candidate["title"],
                "price_type": candidate["price_type"],
                "status_code": candidate["status_code"],
                "open_episode_count": candidate["open_episode_count"],
                "latest_episode_no": candidate["latest_episode_no"],
                "summary_text": chosen[1],
                "char_counts": chosen[2],
                "copy_evidence": chosen[3],
                "cover_evidence": candidate["cover_evidence"],
                "history_count": candidate["history_count"],
                "last_single_slot_at": (
                    candidate["last_single_slot_at"].isoformat(timespec="seconds")
                    if candidate["last_single_slot_at"]
                    else None
                ),
            }
        )
    return proposals
