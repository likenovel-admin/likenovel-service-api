"""AI 취향 추천 서비스 — 작품 DNA 매칭, 프로파일 관리, LLM 호출."""

from fastapi import status
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

import asyncio
import json
import logging
import math
from collections import Counter
from datetime import datetime
import hashlib
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import httpx

from app.const import settings, LOGGER_TYPE, ErrorMessages
from app.exceptions import CustomResponseException
from app.config.log_config import service_error_logger
from app.schemas.ai_recommendation import MAX_EVENT_PAYLOAD_LENGTH

error_logger = service_error_logger(LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_ERROR)
logger = logging.getLogger(__name__)
MIN_SIGNAL_COUNT_FOR_DYNAMIC_SLOTS = 3
AXIS_CONFIDENCE_THRESHOLD = 0.55
AXIS_WEIGHT = {
    "type": 18.0,
    "job": 10.0,
    "goal": 12.0,
    "material": 25.0,
    "worldview": 14.0,
    "romance": 6.0,
    "style": 15.0,
}
AXIS_SHORT_LABEL = {
    "type": "타",
    "job": "직",
    "goal": "목",
    "material": "능",
    "worldview": "세",
    "romance": "연",
    "style": "작",
}
AXIS_DISPLAY_LABEL = {
    "type": "주인공 유형",
    "job": "주인공 직업",
    "goal": "주인공 목표",
    "material": "능력/소재",
    "worldview": "세계관",
    "romance": "관계/로맨스",
    "style": "작풍",
}
GOAL_LABEL_KEYS = {
    "복수",
    "탑등반",
    "생존",
    "육아",
    "여행",
    "차원이동",
    "퇴마",
    "범죄",
    "게임개발",
    "농사",
    "레이드",
    "투자",
    "던전운영",
    "스트리밍",
    "국가경영",
    "날먹",
}
ONBOARDING_TAG_TAB_CONFIG = (
    ("hero", "주인공", 30),
    ("worldTone", "세계관/분위기", 30),
    ("relation", "관계/기타", 24),
)
ONBOARDING_TAG_TAB_LABELS = {
    key: label for key, label, _ in ONBOARDING_TAG_TAB_CONFIG
}
ONBOARDING_TAG_TAB_KEYS = {key for key, _, _ in ONBOARDING_TAG_TAB_CONFIG}
AXIS_CODEBOOK_KEY = {
    "type": "타",
    "job": "직",
    "goal": "목",
    "material": "능",
    "worldview": "세",
    "romance": "연",
    "style": "작",
}
_ALLOWED_AXIS_LABELS_CACHE: dict[str, set[str]] | None = None
_ALLOWED_AXIS_LABELS_WARNED = False
SIGNAL_FACTOR_ALLOWED_AXES: dict[str, tuple[str, ...]] = {
    "protagonist": ("type", "goal"),
    "job": ("job",),
    "goal": ("goal",),
    "material": ("material",),
    "worldview": ("worldview",),
    "theme": ("worldview",),
    "romance": ("romance",),
    "style": ("style",),
    "mood": ("style",),
}
AI_SLOT_FEEDBACK_SIGNAL_EVENTS = {
    "taste_slot_click",
    "episode_view",
    "latest_episode_reached",
    "next_episode_click",
}
AI_SLOT_FEEDBACK_WINDOW_DAYS = 30
AI_SLOT_FEEDBACK_MIN_EPISODES = 3
ENGAGEMENT_SAMPLE_TARGET = 20
MAX_SIGNAL_FACTOR_LABELS_PER_AXIS = 3
DERIVED_REVISIT_24H_FACTOR_MULTIPLIER = 0.7
SIGNAL_FACTOR_METADATA_CACHE_TTL_SECONDS = 60.0
SIGNAL_FACTOR_METADATA_CACHE_MAX_ITEMS = 2048
_SIGNAL_FACTOR_METADATA_CACHE: dict[int, tuple[float, dict]] = {}
_SIGNAL_FACTOR_METADATA_CACHE_LOCKS: dict[int, asyncio.Lock] = {}
_SIGNAL_FACTOR_METADATA_CACHE_LOCKS_GUARD = asyncio.Lock()
LATEST_ENGAGEMENT_JOIN_SQL = """
LEFT JOIN (
    SELECT em.product_id,
           em.binge_rate,
           em.total_next_clicks,
           em.total_readers,
           em.dropoff_7d,
           em.reengage_rate,
           em.avg_speed_cpm
    FROM tb_product_engagement_metrics em
    INNER JOIN (
        SELECT product_id, MAX(computed_date) AS max_computed_date
        FROM tb_product_engagement_metrics
        GROUP BY product_id
    ) latest
      ON latest.product_id = em.product_id
     AND latest.max_computed_date = em.computed_date
) pem ON pem.product_id = p.product_id
"""
LATEST_ENGAGEMENT_SELECT_SQL = """
            COALESCE(pem.binge_rate, 0) AS binge_rate,
            COALESCE(pem.total_next_clicks, 0) AS total_next_clicks,
            COALESCE(pem.total_readers, 0) AS total_readers,
            COALESCE(pem.dropoff_7d, 0) AS dropoff_7d,
            COALESCE(pem.reengage_rate, 0) AS reengage_rate,
            pem.avg_speed_cpm AS avg_speed_cpm
"""
PRESET_RANDOM_POOL_SIZE = 6
PRESET_CANDIDATE_FETCH_LIMIT = 80
COHORT_SIMILAR_USER_LIMIT = 40
COHORT_SIGNAL_LOOKBACK_DAYS = 90
COHORT_SIGNAL_EVENT_WEIGHTS = {
    "episode_view": 0.25,
    "episode_end": 1.0,
    "next_episode_click": 1.6,
    "latest_episode_reached": 1.9,
    "revisit_24h": 0.7,
}


def _allowed_axis_labels_candidates() -> list[Path]:
    resolved = Path(__file__).resolve()
    parents = resolved.parents
    app_root = parents[3] if len(parents) > 3 else Path(settings.ROOT_PATH)

    candidates: list[Path] = [
        Path(settings.ROOT_PATH) / "dist" / "ai" / "allowed-labels-by-axis.json",
        app_root / "dist" / "ai" / "allowed-labels-by-axis.json",
    ]
    for parent in parents:
        candidates.append(parent / "docs" / "ai-codebook" / "allowed-labels-by-axis.json")

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        deduped.append(path)
        seen.add(path)
    return deduped


def _load_allowed_axis_labels() -> dict[str, set[str]]:
    global _ALLOWED_AXIS_LABELS_CACHE, _ALLOWED_AXIS_LABELS_WARNED
    if _ALLOWED_AXIS_LABELS_CACHE is not None:
        return _ALLOWED_AXIS_LABELS_CACHE

    for path in _allowed_axis_labels_candidates():
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8-sig") as fp:
                raw = json.load(fp)
        except Exception as exc:
            logger.warning("failed to load allowed-labels-by-axis.json: %s (%s)", path, exc)
            continue

        if not isinstance(raw, dict):
            logger.warning("invalid allowed-labels-by-axis.json format: %s", path)
            continue

        loaded: dict[str, set[str]] = {}
        is_valid = True
        for axis, codebook_key in AXIS_CODEBOOK_KEY.items():
            values = raw.get(codebook_key)
            if not isinstance(values, list):
                is_valid = False
                break
            normalized = {
                _normalize_factor_key(str(value))
                for value in values
                if isinstance(value, str) and _normalize_factor_key(str(value))
            }
            if not normalized:
                is_valid = False
                break
            loaded[axis] = normalized

        if not is_valid:
            logger.warning("invalid axis entries in allowed-labels-by-axis.json: %s", path)
            continue

        _ALLOWED_AXIS_LABELS_CACHE = loaded
        return loaded

    if not _ALLOWED_AXIS_LABELS_WARNED:
        logger.warning("allowed-labels-by-axis.json not found; axis label filtering is disabled.")
        _ALLOWED_AXIS_LABELS_WARNED = True
    _ALLOWED_AXIS_LABELS_CACHE = {}
    return _ALLOWED_AXIS_LABELS_CACHE


def _filter_axis_label_scores(axis: str, scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}

    normalized_scores: dict[str, float] = {}
    for label, score in scores.items():
        normalized_label = _normalize_factor_key(label)
        normalized_score = _safe_float(score, 0.0)
        if not normalized_label or normalized_score <= 0:
            continue
        normalized_scores[normalized_label] = max(
            normalized_scores.get(normalized_label, 0.0), normalized_score
        )

    if not normalized_scores:
        return {}

    allowed_by_axis = _load_allowed_axis_labels()
    allowed = allowed_by_axis.get(axis)
    if not allowed:
        return normalized_scores

    return {
        label: score
        for label, score in normalized_scores.items()
        if label in allowed
    }


def _allowed_signal_labels_for_factor_type(factor_type: str) -> set[str]:
    normalized_factor_type = _normalize_factor_key(factor_type)
    if not normalized_factor_type:
        return set()
    axes = SIGNAL_FACTOR_ALLOWED_AXES.get(normalized_factor_type)
    if not axes:
        return set()
    allowed_by_axis = _load_allowed_axis_labels()
    allowed: set[str] = set()
    for axis in axes:
        allowed.update(allowed_by_axis.get(axis, set()))
    return allowed


def _normalize_signal_factor(
    factor_type: str | None,
    factor_key: str | None,
) -> tuple[str | None, str | None]:
    normalized_factor_type = _normalize_factor_key(factor_type)
    normalized_factor_key = _normalize_factor_key(factor_key)
    if not normalized_factor_type or not normalized_factor_key:
        return None, None

    allowed_labels = _allowed_signal_labels_for_factor_type(normalized_factor_type)
    if not allowed_labels:
        return None, None
    if normalized_factor_key not in allowed_labels:
        return None, None

    return normalized_factor_type, normalized_factor_key


def _normalize_allowed_axis_label(axis: str, value: str | None) -> str:
    normalized = _normalize_factor_key(value)
    if not normalized:
        return ""
    allowed = _load_allowed_axis_labels().get(axis)
    if allowed and normalized not in allowed:
        return ""
    return normalized

# ──────────────────────────────────────────────────────────
#  LLM 호출 헬퍼
# ──────────────────────────────────────────────────────────

async def _call_claude(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = 1024,
    fail_on_max_tokens: bool = False,
) -> str:
    """Anthropic Messages API 호출. httpx로 직접 호출 (추가 패키지 불필요)."""
    if not settings.ANTHROPIC_API_KEY:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message="AI 추천 서비스가 설정되지 않았습니다.",
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.ANTHROPIC_MODEL,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        if resp.status_code != 200:
            error_logger.error(f"Claude API error: {resp.status_code} {resp.text}")
            raise CustomResponseException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                message="AI 서비스 호출에 실패했습니다.",
            )
        data = resp.json()
        if fail_on_max_tokens and data.get("stop_reason") == "max_tokens":
            raise CustomResponseException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                message=f"AI 응답이 토큰 한도(max_tokens={max_tokens})에 도달해 중단되었습니다.",
            )
        return data["content"][0]["text"]


def _parse_json_from_llm(raw: str) -> dict:
    """LLM 응답에서 JSON 파싱. 마크다운 코드블럭 처리."""
    text_content = raw.strip()
    if text_content.startswith("```"):
        lines = text_content.split("\n")
        lines = lines[1:]  # remove ```json
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text_content = "\n".join(lines)
    return json.loads(text_content)


# ──────────────────────────────────────────────────────────
#  작품 AI DNA
# ──────────────────────────────────────────────────────────

async def get_product_ai_metadata(product_id: int, db: AsyncSession) -> dict | None:
    query = text("""
        SELECT
            m.product_id,
            m.protagonist_type,
            m.protagonist_goal_primary,
            m.goal_confidence,
            m.mood,
            m.taste_tags,
            m.protagonist_material_tags,
            m.worldview_tags,
            m.protagonist_type_tags,
            m.protagonist_job_tags,
            m.axis_style_tags,
            m.axis_romance_tags,
            m.romance_chemistry_weight
        FROM tb_product_ai_metadata m
        INNER JOIN tb_product p ON p.product_id = m.product_id
        WHERE m.product_id = :product_id
          AND p.open_yn = 'Y'
          AND m.analysis_status = 'success'
          AND COALESCE(m.exclude_from_recommend_yn, 'N') = 'N'
    """)
    result = await db.execute(query, {"product_id": product_id})
    row = result.mappings().one_or_none()
    if not row:
        return None
    return _metadata_row_to_dict(row)


async def get_all_product_ai_metadata(db: AsyncSession, adult_yn: str = "N") -> list[dict]:
    adult_filter = "AND p.ratings_code = 'all'" if adult_yn == "N" else ""
    query = text(f"""
        SELECT m.*, p.title, p.status_code, p.count_hit, p.ratings_code,
               {LATEST_ENGAGEMENT_SELECT_SQL}
        FROM tb_product_ai_metadata m
        JOIN tb_product p ON p.product_id = m.product_id
        {LATEST_ENGAGEMENT_JOIN_SQL}
        WHERE p.open_yn = 'Y'
          AND m.analysis_status = 'success'
          AND COALESCE(m.exclude_from_recommend_yn, 'N') = 'N'
        {adult_filter}
    """)
    result = await db.execute(query)
    rows = result.mappings().all()
    return [_metadata_row_to_dict(r) for r in rows]


def _metadata_row_to_dict(row) -> dict:
    d = dict(row)
    for key in (
        "themes",
        "similar_famous",
        "taste_tags",
        "raw_analysis",
        "protagonist_material_tags",
        "worldview_tags",
        "protagonist_type_tags",
        "protagonist_job_tags",
        "axis_style_tags",
        "axis_romance_tags",
    ):
        if isinstance(d.get(key), str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def score_engagement_for_recommendation(item: dict) -> float:
    total_readers = max(
        int(_safe_float(item.get("total_readers"), 0.0)),
        int(_safe_float(item.get("total_next_clicks"), 0.0)),
    )
    sample_scale = _clamp(
        total_readers / ENGAGEMENT_SAMPLE_TARGET,
        0.0,
        1.0,
    )
    binge_rate = _clamp(_safe_float(item.get("binge_rate"), 0.0), 0.0, 1.0)
    reengage_rate = _clamp(_safe_float(item.get("reengage_rate"), 0.0), 0.0, 1.0)
    if total_readers > 0:
        dropoff_rate = _clamp(
            int(_safe_float(item.get("dropoff_7d"), 0.0)) / max(total_readers, 1),
            0.0,
            1.0,
        )
    else:
        dropoff_rate = 0.0

    avg_speed_cpm = _safe_float(item.get("avg_speed_cpm"), 0.0)
    speed_quality = 0.0
    if avg_speed_cpm > 0:
        speed_quality = 1.0 - _clamp(abs(avg_speed_cpm - 900.0) / 700.0, 0.0, 1.0)

    raw_score = (
        (binge_rate * 0.70)
        + (reengage_rate * 0.45)
        + (speed_quality * 0.15)
        - (dropoff_rate * 0.55)
    ) * sample_scale
    return round(_clamp(raw_score, -0.35, 1.0), 4)


# ──────────────────────────────────────────────────────────
#  유저 취향 프로파일
# ──────────────────────────────────────────────────────────

async def get_user_taste_profile(user_id: int, db: AsyncSession) -> dict | None:
    query = text("""
        SELECT * FROM tb_user_taste_profile WHERE user_id = :user_id
    """)
    result = await db.execute(query, {"user_id": user_id})
    row = result.mappings().one_or_none()
    if not row:
        return None
    return _profile_row_to_dict(row)


def _profile_row_to_dict(row) -> dict:
    d = dict(row)
    json_fields = (
        "onboarding_picks", "onboarding_moods", "preferred_protagonist",
        "preferred_mood", "preferred_themes", "taste_tags",
        "recommendation_sections", "read_product_ids",
    )
    for key in json_fields:
        if isinstance(d.get(key), str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


async def _get_user_id_by_kc(kc_user_id: str, db: AsyncSession) -> int | None:
    query = text("SELECT user_id FROM tb_user WHERE kc_user_id = :kc AND use_yn = 'Y' LIMIT 1")
    result = await db.execute(query, {"kc": kc_user_id})
    row = result.mappings().one_or_none()
    return row["user_id"] if row else None


async def _is_ai_onboarding_dismissed(user_id: int, db: AsyncSession) -> bool:
    query = text(
        """
        SELECT COALESCE(ai_onboarding_dismissed_yn, 'N') AS dismissed_yn
        FROM tb_user
        WHERE user_id = :user_id
        LIMIT 1
        """
    )
    result = await db.execute(query, {"user_id": user_id})
    row = result.mappings().one_or_none()
    return (row or {}).get("dismissed_yn") == "Y"


def _unique_nonempty_labels(values: list) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = str(value or "").strip()
        if len(label) > 120:
            label = label[:120]
        if not label or label in seen:
            continue
        seen.add(label)
        result.append(label)
    return result


def _sanitize_onboarding_tags(values: list[str], *, max_items: int = 20) -> list[str]:
    return _unique_nonempty_labels([str(value or "").strip() for value in (values or [])])[:max_items]


def _increment_label_counter(counter: dict[str, int], labels: list[str], *, weight: int = 1) -> None:
    for label in labels:
        counter[label] = counter.get(label, 0) + weight


async def _get_signal_factor_metadata(product_id: int, db: AsyncSession) -> dict | None:
    now = time.monotonic()
    cached_entry = _SIGNAL_FACTOR_METADATA_CACHE.get(product_id)
    if cached_entry and (now - cached_entry[0]) < SIGNAL_FACTOR_METADATA_CACHE_TTL_SECONDS:
        return _clone_signal_factor_metadata(cached_entry[1])

    async with await _get_signal_factor_metadata_lock(product_id):
        now = time.monotonic()
        cached_entry = _SIGNAL_FACTOR_METADATA_CACHE.get(product_id)
        if cached_entry and (now - cached_entry[0]) < SIGNAL_FACTOR_METADATA_CACHE_TTL_SECONDS:
            return _clone_signal_factor_metadata(cached_entry[1])

        _prune_signal_factor_metadata_cache(now)

        query = text(
            """
            SELECT
                m.protagonist_type,
                m.protagonist_goal_primary,
                m.goal_confidence,
                m.mood,
                m.protagonist_material_tags,
                m.worldview_tags,
                m.protagonist_type_tags,
                m.protagonist_job_tags,
                m.axis_style_tags,
                m.axis_romance_tags,
                m.romance_chemistry_weight
            FROM tb_product_ai_metadata m
            WHERE m.product_id = :product_id
              AND m.analysis_status = 'success'
              AND COALESCE(m.exclude_from_recommend_yn, 'N') = 'N'
            LIMIT 1
            """
        )
        result = await db.execute(query, {"product_id": product_id})
        row = result.mappings().one_or_none()
        if not row:
            return None

        metadata = _metadata_row_to_dict(row)
        _SIGNAL_FACTOR_METADATA_CACHE[product_id] = (time.monotonic(), metadata)
        _prune_signal_factor_metadata_cache(time.monotonic())
        return _clone_signal_factor_metadata(metadata)


async def _get_signal_factor_metadata_lock(product_id: int) -> asyncio.Lock:
    async with _SIGNAL_FACTOR_METADATA_CACHE_LOCKS_GUARD:
        lock = _SIGNAL_FACTOR_METADATA_CACHE_LOCKS.get(product_id)
        if lock is None:
            lock = asyncio.Lock()
            _SIGNAL_FACTOR_METADATA_CACHE_LOCKS[product_id] = lock
        return lock


def _clone_signal_factor_metadata(metadata: dict | None) -> dict | None:
    if metadata is None:
        return None
    cloned: dict = {}
    for key, value in metadata.items():
        if isinstance(value, list):
            cloned[key] = list(value)
        elif isinstance(value, dict):
            cloned[key] = dict(value)
        else:
            cloned[key] = value
    return cloned


def _prune_signal_factor_metadata_cache(now: float) -> None:
    expired_product_ids = [
        product_id
        for product_id, (cached_at, _) in _SIGNAL_FACTOR_METADATA_CACHE.items()
        if (now - cached_at) >= SIGNAL_FACTOR_METADATA_CACHE_TTL_SECONDS
    ]
    for product_id in expired_product_ids:
        _SIGNAL_FACTOR_METADATA_CACHE.pop(product_id, None)

    if len(_SIGNAL_FACTOR_METADATA_CACHE) <= SIGNAL_FACTOR_METADATA_CACHE_MAX_ITEMS:
        return

    overflow = len(_SIGNAL_FACTOR_METADATA_CACHE) - SIGNAL_FACTOR_METADATA_CACHE_MAX_ITEMS
    oldest_product_ids = sorted(
        _SIGNAL_FACTOR_METADATA_CACHE.items(),
        key=lambda item: item[1][0],
    )[:overflow]
    for product_id, _ in oldest_product_ids:
        _SIGNAL_FACTOR_METADATA_CACHE.pop(product_id, None)


def _collect_signal_factor_labels(metadata: dict) -> dict[str, list[str]]:
    protagonist_labels = _unique_nonempty_labels(
        _as_list(metadata.get("protagonist_type_tags")) + [metadata.get("protagonist_type")]
    )[:MAX_SIGNAL_FACTOR_LABELS_PER_AXIS]
    material_labels = _unique_nonempty_labels(
        _as_list(metadata.get("protagonist_material_tags"))
    )[:MAX_SIGNAL_FACTOR_LABELS_PER_AXIS]
    job_labels = _unique_nonempty_labels(
        _as_list(metadata.get("protagonist_job_tags"))
    )[:MAX_SIGNAL_FACTOR_LABELS_PER_AXIS]
    worldview_labels = _unique_nonempty_labels(
        _as_list(metadata.get("worldview_tags"))
    )[:MAX_SIGNAL_FACTOR_LABELS_PER_AXIS]
    romance_labels = _unique_nonempty_labels(
        _as_list(metadata.get("axis_romance_tags")) + [metadata.get("romance_chemistry_weight")]
    )[:MAX_SIGNAL_FACTOR_LABELS_PER_AXIS]
    style_labels = _unique_nonempty_labels(
        _as_list(metadata.get("axis_style_tags")) + [metadata.get("mood")]
    )[:MAX_SIGNAL_FACTOR_LABELS_PER_AXIS]

    goal_labels: list[str] = []
    goal_label = str(metadata.get("protagonist_goal_primary") or "").strip()
    goal_confidence = _safe_float(metadata.get("goal_confidence"), 0.0)
    if goal_label and not (goal_label == "생존" and goal_confidence < 0.6):
        goal_labels.append(goal_label)

    return {
        "protagonist": protagonist_labels,
        "material": material_labels,
        "job": job_labels,
        "goal": goal_labels[:MAX_SIGNAL_FACTOR_LABELS_PER_AXIS],
        "worldview": worldview_labels,
        "romance": romance_labels,
        "style": style_labels,
    }


def _signal_factor_score_plan(
    event_type: str,
    *,
    base_event_type: str | None = None,
    score_multiplier: float = 1.0,
) -> list[tuple[str, float]]:
    normalized_event_type = str(event_type or "").strip().lower()
    if normalized_event_type == "revisit_24h":
        source_event_type = str(base_event_type or "").strip().lower()
        if source_event_type not in {"episode_view", "latest_episode_reached"}:
            source_event_type = "episode_view"
        return _signal_factor_score_plan(
            source_event_type,
            score_multiplier=score_multiplier * DERIVED_REVISIT_24H_FACTOR_MULTIPLIER,
        )

    if normalized_event_type == "next_episode_click":
        plan = [
            ("protagonist", 3.0),
            ("material", 2.6),
            ("job", 2.4),
            ("goal", 2.2),
            ("worldview", 1.9),
            ("style", 1.7),
            ("romance", 1.5),
        ]
    elif normalized_event_type == "episode_end":
        plan = [
            ("protagonist", 2.4),
            ("material", 2.1),
            ("worldview", 1.9),
            ("style", 1.7),
            ("job", 1.6),
            ("goal", 1.5),
            ("romance", 1.4),
        ]
    elif normalized_event_type == "latest_episode_reached":
        plan = [
            ("goal", 2.8),
            ("worldview", 2.5),
            ("romance", 2.3),
            ("style", 2.1),
            ("protagonist", 1.8),
            ("material", 1.7),
            ("job", 1.6),
        ]
    elif normalized_event_type == "taste_slot_click":
        plan = [
            ("style", 1.8),
            ("worldview", 1.6),
            ("material", 1.5),
            ("protagonist", 1.4),
            ("job", 1.3),
            ("goal", 1.2),
            ("romance", 1.1),
        ]
    else:
        plan = [
            ("style", 1.4),
            ("worldview", 1.2),
            ("romance", 1.1),
            ("material", 1.0),
            ("job", 0.95),
            ("protagonist", 0.9),
            ("goal", 0.85),
        ]

    return [(factor_type, round(score * score_multiplier, 6)) for factor_type, score in plan]


def _build_signal_factor_entries_from_metadata(
    event_type: str,
    metadata: dict,
    *,
    base_event_type: str | None = None,
    score_multiplier: float = 1.0,
) -> list[dict[str, float | str]]:
    labels_by_type = _collect_signal_factor_labels(metadata)
    plan = _signal_factor_score_plan(
        event_type,
        base_event_type=base_event_type,
        score_multiplier=score_multiplier,
    )

    entries: list[dict[str, float | str]] = []
    seen: set[tuple[str, str]] = set()
    for factor_type, signal_score in plan:
        if signal_score <= 0:
            continue
        for label in labels_by_type.get(factor_type, []):
            normalized_factor_type, normalized_factor_key = _normalize_signal_factor(
                factor_type, label
            )
            if not normalized_factor_type or not normalized_factor_key:
                continue
            dedupe_key = (normalized_factor_type, normalized_factor_key)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            entries.append(
                {
                    "factor_type": normalized_factor_type,
                    "factor_key": normalized_factor_key,
                    "signal_score": signal_score,
                }
            )
    return entries


def _scale_signal_factor_entries(
    entries: list[dict[str, float | str]],
    multiplier: float,
) -> list[dict[str, float | str]]:
    if multiplier == 1:
        return entries
    return [
        {
            "factor_type": entry["factor_type"],
            "factor_key": entry["factor_key"],
            "signal_score": round(_safe_float(entry["signal_score"], 0.0) * multiplier, 6),
        }
        for entry in entries
        if _safe_float(entry["signal_score"], 0.0) > 0
    ]


async def _resolve_signal_factor_entries(
    product_id: int,
    event_type: str,
    db: AsyncSession,
    *,
    base_event_type: str | None = None,
    score_multiplier: float = 1.0,
) -> list[dict[str, float | str]]:
    metadata = await _get_signal_factor_metadata(product_id, db)
    if not metadata:
        return []
    return _build_signal_factor_entries_from_metadata(
        event_type,
        metadata,
        base_event_type=base_event_type,
        score_multiplier=score_multiplier,
    )


async def _insert_ai_signal_event_factors(
    *,
    event_id: int,
    user_id: int,
    product_id: int,
    episode_id: int | None,
    event_type: str,
    factor_entries: list[dict[str, float | str]],
    db: AsyncSession,
) -> None:
    if not factor_entries:
        return

    query = text(
        """
        INSERT INTO tb_user_ai_signal_event_factor (
            event_id,
            user_id,
            product_id,
            episode_id,
            event_type,
            factor_type,
            factor_key,
            signal_score
        ) VALUES (
            :event_id,
            :user_id,
            :product_id,
            :episode_id,
            :event_type,
            :factor_type,
            :factor_key,
            :signal_score
        )
        """
    )
    rows = [
        {
            "event_id": event_id,
            "user_id": user_id,
            "product_id": product_id,
            "episode_id": episode_id,
            "event_type": event_type,
            "factor_type": entry["factor_type"],
            "factor_key": entry["factor_key"],
            "signal_score": entry["signal_score"],
        }
        for entry in factor_entries
    ]
    await db.execute(query, rows)


def _should_skip_signal_factor_generation(event_type: str, payload: dict) -> bool:
    normalized_event_type = str(event_type or "").strip().lower()
    if normalized_event_type == "episode_view" and str(payload.get("trigger") or "").strip().lower() == "exit":
        return True
    return False


# ──────────────────────────────────────────────────────────
#  AI 신호 이벤트 적재
# ──────────────────────────────────────────────────────────

async def post_signal_event(kc_user_id: str, req_body: dict, db: AsyncSession) -> dict:
    user_id = await _get_user_id_by_kc(kc_user_id, db)
    if not user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    product_id = req_body["product_id"]
    episode_id = req_body.get("episode_id")
    event_type = req_body["event_type"]

    if event_type in {"episode_view", "episode_end", "latest_episode_reached"} and episode_id is None:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=f"{event_type}에는 episode_id가 필요합니다.",
        )

    product_match_query = text(
        """
        SELECT 1
        FROM tb_product p
        WHERE p.product_id = :product_id
          AND p.open_yn = 'Y'
        LIMIT 1
        """
    )
    product_match_result = await db.execute(product_match_query, {"product_id": product_id})
    if product_match_result.scalar_one_or_none() is None:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="공개된 작품만 AI 신호 이벤트를 저장할 수 있습니다.",
        )

    if episode_id is not None:
        episode_match_query = text(
            """
            SELECT 1
            FROM tb_product_episode e
            WHERE e.episode_id = :episode_id
              AND e.product_id = :product_id
              AND e.use_yn = 'Y'
              AND (
                  e.open_yn = 'Y'
                  OR EXISTS (
                      SELECT 1
                      FROM tb_user_productbook pb
                      WHERE (
                          pb.episode_id = e.episode_id
                          OR (pb.episode_id IS NULL
                              AND (pb.product_id = e.product_id
                                   OR pb.product_id IS NULL))
                      )
                        AND pb.user_id = :user_id
                        AND pb.use_yn = 'Y'
                        AND (pb.rental_expired_date IS NULL OR pb.rental_expired_date > NOW())
                  )
              )
            LIMIT 1
            """
        )
        episode_match_result = await db.execute(
            episode_match_query,
            {"episode_id": episode_id, "product_id": product_id, "user_id": user_id},
        )
        if episode_match_result.scalar_one_or_none() is None:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="열람 권한이 있는 회차만 AI 신호 이벤트를 저장할 수 있습니다.",
            )

    payload = dict(req_body.get("event_payload") or {})
    # 축/점수는 top-level 검증값만 사용한다.
    payload.pop("factor_type", None)
    payload.pop("factor_key", None)
    payload.pop("signal_score", None)

    if event_type == "next_episode_click":
        if episode_id is None:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="next_episode_click에는 episode_id가 필요합니다.",
            )
        redirect_to_episode_id_raw = payload.get("redirect_to_episode_id")
        try:
            redirect_to_episode_id = int(redirect_to_episode_id_raw)
        except (TypeError, ValueError):
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="next_episode_click에는 유효한 redirect_to_episode_id가 필요합니다.",
            )

        next_episode_query = text(
            """
            WITH visible_episodes AS (
                SELECT
                    q.episode_id,
                    LEAD(q.episode_id, 1) OVER (PARTITION BY q.product_id ORDER BY q.episode_no) AS next_episode_id
                FROM tb_product_episode q
                WHERE q.product_id = :product_id
                  AND q.use_yn = 'Y'
                  AND (
                      q.open_yn = 'Y'
                      OR q.episode_id = :episode_id
                      OR EXISTS (
                          SELECT 1
                          FROM tb_user_productbook pb
                          WHERE (
                              pb.episode_id = q.episode_id
                              OR (pb.episode_id IS NULL
                                  AND (pb.product_id = q.product_id
                                       OR pb.product_id IS NULL))
                          )
                            AND pb.user_id = :user_id
                            AND pb.use_yn = 'Y'
                            AND (pb.rental_expired_date IS NULL OR pb.rental_expired_date > NOW())
                      )
                  )
            )
            SELECT next_episode_id
            FROM visible_episodes
            WHERE episode_id = :episode_id
            LIMIT 1
            """
        )
        next_episode_result = await db.execute(
            next_episode_query,
            {
                "product_id": product_id,
                "episode_id": episode_id,
                "user_id": user_id,
            },
        )
        expected_next_episode_id = next_episode_result.scalar_one_or_none()
        if (
            expected_next_episode_id is None
            or int(expected_next_episode_id) != redirect_to_episode_id
        ):
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="next_episode_click 리다이렉트 정보가 유효하지 않습니다.",
            )

    if not _should_skip_signal_factor_generation(event_type, payload):
        signal_factor_entries = await _resolve_signal_factor_entries(
            product_id,
            event_type,
            db,
        )
    else:
        signal_factor_entries = []

    if payload:
        serialized_payload = json.dumps(payload, ensure_ascii=False)
        if len(serialized_payload) > MAX_EVENT_PAYLOAD_LENGTH:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="event_payload 크기가 허용 범위를 초과했습니다.",
            )
    else:
        serialized_payload = None

    should_insert_revisit_24h = False
    if (
        event_type in {"episode_view", "latest_episode_reached"}
        and not _should_skip_signal_factor_generation(event_type, payload)
    ):
        revisit_check_query = text(
            """
            SELECT 1
            FROM tb_user_ai_signal_event e
            WHERE e.user_id = :user_id
              AND e.product_id = :product_id
              AND e.event_type IN ('episode_view', 'latest_episode_reached')
              AND e.created_date >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
              AND (
                    :session_id IS NULL
                    OR e.session_id IS NULL
                    OR e.session_id <> :session_id
              )
            LIMIT 1
            """
        )
        revisit_check_result = await db.execute(
            revisit_check_query,
            {
                "user_id": user_id,
                "product_id": product_id,
                "session_id": req_body.get("session_id"),
            },
        )
        should_insert_revisit_24h = revisit_check_result.scalar_one_or_none() is not None

    query = text(
        """
        INSERT INTO tb_user_ai_signal_event (
            user_id,
            product_id,
            episode_id,
            event_type,
            session_id,
            active_seconds,
            scroll_depth,
            progress_ratio,
            next_available_yn,
            latest_episode_reached_yn,
            event_payload
        ) VALUES (
            :user_id,
            :product_id,
            :episode_id,
            :event_type,
            :session_id,
            :active_seconds,
            :scroll_depth,
            :progress_ratio,
            :next_available_yn,
            :latest_episode_reached_yn,
            :event_payload
        )
        """
    )

    insert_result = await db.execute(
        query,
        {
            "user_id": user_id,
            "product_id": product_id,
            "episode_id": episode_id,
            "event_type": event_type,
            "session_id": req_body.get("session_id"),
            "active_seconds": req_body.get("active_seconds", 0),
            "scroll_depth": req_body.get("scroll_depth", 0),
            "progress_ratio": req_body.get("progress_ratio", 0),
            "next_available_yn": req_body.get("next_available_yn", "N"),
            "latest_episode_reached_yn": req_body.get("latest_episode_reached_yn", "N"),
            "event_payload": serialized_payload,
        },
    )
    event_id = insert_result.lastrowid
    if event_id and signal_factor_entries:
        await _insert_ai_signal_event_factors(
            event_id=int(event_id),
            user_id=user_id,
            product_id=product_id,
            episode_id=episode_id,
            event_type=event_type,
            factor_entries=signal_factor_entries,
            db=db,
        )

    if should_insert_revisit_24h:
        revisit_payload = json.dumps(
            {
                "source": "derived",
                "base_event_type": event_type,
            },
            ensure_ascii=False,
        )
        revisit_insert_result = await db.execute(
            query,
            {
                "user_id": user_id,
                "product_id": product_id,
                "episode_id": episode_id,
                "event_type": "revisit_24h",
                "session_id": req_body.get("session_id"),
                "active_seconds": 0,
                "scroll_depth": 0,
                "progress_ratio": 0,
                "next_available_yn": req_body.get("next_available_yn", "N"),
                "latest_episode_reached_yn": req_body.get("latest_episode_reached_yn", "N"),
                "event_payload": revisit_payload,
            },
        )
        revisit_event_id = revisit_insert_result.lastrowid
        revisit_factor_entries = _scale_signal_factor_entries(
            signal_factor_entries,
            DERIVED_REVISIT_24H_FACTOR_MULTIPLIER,
        )
        if not revisit_factor_entries:
            revisit_factor_entries = await _resolve_signal_factor_entries(
                product_id,
                "revisit_24h",
                db,
                base_event_type=event_type,
            )
        if revisit_event_id and revisit_factor_entries:
            await _insert_ai_signal_event_factors(
                event_id=int(revisit_event_id),
                user_id=user_id,
                product_id=product_id,
                episode_id=episode_id,
                event_type="revisit_24h",
                factor_entries=revisit_factor_entries,
                db=db,
            )

    # 추천 구좌 피드백 루프 반영 (클릭/3화 연독)
    try:
        await _update_ai_slot_feedback_flags(
            user_id=user_id,
            product_id=product_id,
            event_type=event_type,
            db=db,
        )
    except Exception as e:
        error_logger.error(
            "AI slot feedback update failed: user_id=%s product_id=%s event_type=%s error=%s",
            user_id,
            product_id,
            event_type,
            e,
        )

    await db.commit()
    return {"message": "AI 신호 이벤트가 저장되었습니다."}


async def _update_ai_slot_feedback_flags(
    *,
    user_id: int,
    product_id: int,
    event_type: str,
    db: AsyncSession,
) -> None:
    if user_id <= 0 or product_id <= 0:
        return

    normalized_event_type = str(event_type or "").strip().lower()
    if normalized_event_type not in AI_SLOT_FEEDBACK_SIGNAL_EVENTS:
        return

    params = {
        "user_id": user_id,
        "product_id": product_id,
    }

    if normalized_event_type == "taste_slot_click":
        click_query = text(
            f"""
            UPDATE tb_ai_slot_serving_log target
            JOIN (
                SELECT s.id
                FROM tb_ai_slot_serving_log s
                WHERE s.user_id = :user_id
                  AND s.product_id = :product_id
                  AND s.clicked_yn = 'N'
                  AND s.served_at >= DATE_SUB(NOW(), INTERVAL {AI_SLOT_FEEDBACK_WINDOW_DAYS} DAY)
                  AND s.served_at > COALESCE(
                        (
                            SELECT MAX(c.served_at)
                            FROM tb_ai_slot_serving_log c
                            WHERE c.user_id = :user_id
                              AND c.product_id = :product_id
                              AND c.clicked_yn = 'Y'
                              AND c.served_at >= DATE_SUB(NOW(), INTERVAL {AI_SLOT_FEEDBACK_WINDOW_DAYS} DAY)
                        ),
                        TIMESTAMP('1970-01-01 00:00:00')
                    )
                ORDER BY s.served_at DESC, s.id DESC
                LIMIT 1
            ) picked ON picked.id = target.id
            SET target.clicked_yn = 'Y'
            """
        )
        await db.execute(click_query, params)
        return

    continued_query = text(
        f"""
        UPDATE tb_ai_slot_serving_log target
        JOIN (
            SELECT s.id
            FROM tb_ai_slot_serving_log s
            WHERE s.user_id = :user_id
              AND s.product_id = :product_id
              AND s.clicked_yn = 'Y'
              AND s.continued_3ep_yn = 'N'
              AND s.served_at >= DATE_SUB(NOW(), INTERVAL {AI_SLOT_FEEDBACK_WINDOW_DAYS} DAY)
              AND (
                    SELECT COUNT(DISTINCT e.episode_id)
                    FROM tb_user_ai_signal_event e
                    WHERE e.user_id = s.user_id
                      AND e.product_id = s.product_id
                      AND e.episode_id IS NOT NULL
                      AND e.event_type IN ('episode_view', 'latest_episode_reached', 'next_episode_click')
                      AND e.created_date >= s.served_at
                ) >= {AI_SLOT_FEEDBACK_MIN_EPISODES}
            ORDER BY s.served_at DESC, s.id DESC
            LIMIT 1
        ) scored ON scored.id = target.id
        SET target.continued_3ep_yn = 'Y'
        """
    )
    await db.execute(continued_query, params)


# ──────────────────────────────────────────────────────────
#  온보딩
# ──────────────────────────────────────────────────────────

async def process_onboarding(
    kc_user_id: str,
    product_ids: list[int],
    moods: list[str],
    hero_tags: list[str],
    world_tone_tags: list[str],
    relation_tags: list[str],
    adult_yn: str,
    db: AsyncSession,
) -> dict:
    user_id = await _get_user_id_by_kc(kc_user_id, db)
    if not user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )
    adult_yn = (adult_yn or "N").upper()
    if adult_yn not in {"Y", "N"}:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="adult_yn은 Y/N 값만 허용됩니다.",
        )
    adult_filter = "AND p.ratings_code = 'all'" if adult_yn == "N" else ""

    sanitized_moods = _sanitize_onboarding_tags(moods)
    sanitized_hero_tags = _sanitize_onboarding_tags(hero_tags)
    sanitized_world_tone_tags = _sanitize_onboarding_tags(world_tone_tags)
    sanitized_relation_tags = _sanitize_onboarding_tags(relation_tags)

    # 공개/활성 작품만 온보딩 선택 허용
    unique_product_ids = list(dict.fromkeys(int(pid) for pid in product_ids))
    if not unique_product_ids and not (
        sanitized_moods
        or sanitized_hero_tags
        or sanitized_world_tone_tags
        or sanitized_relation_tags
    ):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="온보딩 작품 또는 태그 선택값이 비어 있습니다.",
        )

    valid_product_ids: list[int] = []
    dna_rows: list[dict] = []
    if unique_product_ids:
        placeholders = ",".join(f":pid_{i}" for i in range(len(unique_product_ids)))
        valid_product_query = text(
            f"""
            SELECT p.product_id
            FROM tb_product p
            WHERE p.product_id IN ({placeholders})
              AND p.open_yn = 'Y'
              {adult_filter}
            """
        )
        valid_params = {f"pid_{i}": pid for i, pid in enumerate(unique_product_ids)}
        valid_result = await db.execute(valid_product_query, valid_params)
        valid_product_ids = [int(r["product_id"]) for r in valid_result.mappings().all()]

        if len(valid_product_ids) != len(unique_product_ids):
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="비공개 또는 비활성 작품은 온보딩에 사용할 수 없습니다.",
            )

        # 선택한 작품들의 DNA 조회
        placeholders = ",".join(f":pid_{i}" for i in range(len(valid_product_ids)))
        query = text(f"""
            SELECT m.*
            FROM tb_product_ai_metadata m
            INNER JOIN tb_product p ON p.product_id = m.product_id
            WHERE m.product_id IN ({placeholders})
              AND p.open_yn = 'Y'
              {adult_filter}
        """)
        params = {f"pid_{i}": pid for i, pid in enumerate(valid_product_ids)}
        result = await db.execute(query, params)
        dna_rows = [_metadata_row_to_dict(r) for r in result.mappings().all()]

    # DNA 집계 → 취향 프로파일 구성
    protagonist_counts = {}
    mood_counts = {}
    theme_counts = {}
    pacing_counts = {}
    heroine_weight_counts = {}
    all_taste_tags = []

    for dna in dna_rows:
        if dna.get("protagonist_type"):
            pt = dna["protagonist_type"]
            protagonist_counts[pt] = protagonist_counts.get(pt, 0) + 1
        if dna.get("mood"):
            m = dna["mood"]
            mood_counts[m] = mood_counts.get(m, 0) + 1
        if dna.get("pacing"):
            p = dna["pacing"]
            pacing_counts[p] = pacing_counts.get(p, 0) + 1
        if dna.get("heroine_weight"):
            hw = dna["heroine_weight"]
            heroine_weight_counts[hw] = heroine_weight_counts.get(hw, 0) + 1
        for theme in (dna.get("themes") or []):
            theme_counts[theme] = theme_counts.get(theme, 0) + 1
        all_taste_tags.extend(dna.get("taste_tags") or [])

    # 태그 직접 선택 가중치 반영
    _increment_label_counter(mood_counts, sanitized_moods, weight=2)
    _increment_label_counter(protagonist_counts, sanitized_hero_tags, weight=2)
    _increment_label_counter(mood_counts, sanitized_world_tone_tags, weight=1)
    _increment_label_counter(theme_counts, sanitized_world_tone_tags, weight=1)
    _increment_label_counter(theme_counts, sanitized_relation_tags, weight=1)

    preferred_pacing = max(pacing_counts, key=pacing_counts.get) if pacing_counts else None
    preferred_heroine_weight = (
        max(heroine_weight_counts, key=heroine_weight_counts.get)
        if heroine_weight_counts
        else None
    )
    dominant_type = max(protagonist_counts, key=protagonist_counts.get) if protagonist_counts else None
    if not dominant_type and sanitized_hero_tags:
        dominant_type = sanitized_hero_tags[0]

    selected_tags = _unique_nonempty_labels(
        sanitized_moods + sanitized_hero_tags + sanitized_world_tone_tags + sanitized_relation_tags
    )
    taste_tags = _unique_nonempty_labels(all_taste_tags + selected_tags)[:20]

    # LLM으로 추천 섹션 타이틀 + 취향 요약 생성
    sections, taste_summary = await _generate_profile_content(
        protagonist_counts, mood_counts, theme_counts, taste_tags
    )

    # DB 저장 (UPSERT)
    upsert_query = text("""
        INSERT INTO tb_user_taste_profile (
            user_id, onboarding_picks, onboarding_moods,
            preferred_protagonist, preferred_mood, preferred_themes,
            preferred_heroine_weight, preferred_pacing, taste_summary, taste_tags,
            recommendation_sections, read_product_ids, last_computed_at
        ) VALUES (
            :user_id, :onboarding_picks, :onboarding_moods,
            :preferred_protagonist, :preferred_mood, :preferred_themes,
            :preferred_heroine_weight,
            :preferred_pacing, :taste_summary, :taste_tags,
            :recommendation_sections, :read_product_ids, NOW()
        )
        ON DUPLICATE KEY UPDATE
            onboarding_picks = VALUES(onboarding_picks),
            onboarding_moods = VALUES(onboarding_moods),
            preferred_protagonist = VALUES(preferred_protagonist),
            preferred_mood = VALUES(preferred_mood),
            preferred_themes = VALUES(preferred_themes),
            preferred_heroine_weight = VALUES(preferred_heroine_weight),
            preferred_pacing = VALUES(preferred_pacing),
            taste_summary = VALUES(taste_summary),
            taste_tags = VALUES(taste_tags),
            recommendation_sections = VALUES(recommendation_sections),
            read_product_ids = VALUES(read_product_ids),
            last_computed_at = NOW()
    """)
    await db.execute(upsert_query, {
        "user_id": user_id,
        "onboarding_picks": json.dumps(valid_product_ids),
        "onboarding_moods": json.dumps(selected_tags, ensure_ascii=False),
        "preferred_protagonist": json.dumps(protagonist_counts, ensure_ascii=False),
        "preferred_mood": json.dumps(mood_counts, ensure_ascii=False),
        "preferred_themes": json.dumps(theme_counts, ensure_ascii=False),
        "preferred_heroine_weight": preferred_heroine_weight,
        "preferred_pacing": preferred_pacing,
        "taste_summary": taste_summary,
        "taste_tags": json.dumps(taste_tags, ensure_ascii=False),
        "recommendation_sections": json.dumps(sections, ensure_ascii=False),
        "read_product_ids": json.dumps(valid_product_ids),
    })
    await db.execute(
        text(
            """
            UPDATE tb_user
            SET ai_onboarding_dismissed_yn = 'Y',
                updated_date = NOW()
            WHERE user_id = :user_id
            """
        ),
        {"user_id": user_id},
    )

    return {
        "message": "취향 프로파일이 생성되었습니다.",
        "taste_summary": taste_summary,
        "dominant_type": dominant_type,
    }


async def dismiss_onboarding(kc_user_id: str, db: AsyncSession) -> dict:
    user_id = await _get_user_id_by_kc(kc_user_id, db)
    if not user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    await db.execute(
        text(
            """
            UPDATE tb_user
            SET ai_onboarding_dismissed_yn = 'Y',
                updated_date = NOW()
            WHERE user_id = :user_id
            """
        ),
        {"user_id": user_id},
    )
    return {"message": "온보딩 모달 숨김 상태가 저장되었습니다."}


async def _generate_profile_content(
    protagonist_counts: dict,
    mood_counts: dict,
    theme_counts: dict,
    taste_tags: list[str],
) -> tuple[list[dict], str]:
    """LLM으로 추천 섹션 타이틀 3개 + 취향 요약문 생성."""
    system_prompt = (
        "당신은 웹소설 추천 전문가입니다. "
        "독자의 취향 데이터를 분석하여 추천 섹션을 구성합니다. "
        "반드시 JSON으로만 응답하세요."
    )
    user_prompt = f"""아래 독자 취향 데이터를 분석하여 JSON으로 응답하세요.

선호 주인공 유형: {json.dumps(protagonist_counts, ensure_ascii=False)}
선호 분위기: {json.dumps(mood_counts, ensure_ascii=False)}
선호 테마: {json.dumps(theme_counts, ensure_ascii=False)}
취향 태그: {taste_tags}

다음 형식으로 응답하세요:
{{
  "sections": [
    {{
      "dimension": "protagonist",
      "title": "이 독자에게 어울리는 주인공 관련 구좌 타이틀 (15자 이내, 토스증권 스타일로 자신감 있게)",
      "reason": "왜 이 차원으로 추천하는지 한줄"
    }},
    {{
      "dimension": "mood",
      "title": "분위기 관련 구좌 타이틀",
      "reason": "한줄 설명"
    }},
    {{
      "dimension": "theme",
      "title": "테마 관련 구좌 타이틀",
      "reason": "한줄 설명"
    }}
  ],
  "taste_summary": "이 독자의 취향을 한줄로 요약 (예: 냉철한 전략가가 어두운 세계에서 두뇌전을 펼치는 작품을 즐기시네요)"
}}"""

    try:
        raw = await _call_claude(system_prompt, user_prompt)
        parsed = _parse_json_from_llm(raw)
        return parsed.get("sections", []), parsed.get("taste_summary", "")
    except Exception as e:
        error_logger.error(f"Profile content generation failed: {e}")
        # 폴백: 데이터 기반 기본 섹션
        top_protagonist = max(protagonist_counts, key=protagonist_counts.get) if protagonist_counts else "매력적인"
        top_mood = max(mood_counts, key=mood_counts.get) if mood_counts else "몰입감 있는"
        top_theme = max(theme_counts, key=theme_counts.get) if theme_counts else "흥미로운"
        return [
            {"dimension": "protagonist", "title": f"{top_protagonist} 주인공이 활약하는 작품", "reason": "선호 주인공 유형 기반"},
            {"dimension": "mood", "title": f"{top_mood} 분위기의 작품", "reason": "선호 분위기 기반"},
            {"dimension": "theme", "title": f"{top_theme} 테마의 작품", "reason": "선호 테마 기반"},
        ], f"{top_protagonist} 주인공이 {top_mood} 분위기에서 활약하는 작품을 즐기시네요"


# ──────────────────────────────────────────────────────────
#  취향 기반 추천 (메인 구좌용)
# ──────────────────────────────────────────────────────────

async def get_taste_recommendations(kc_user_id: str, adult_yn: str, db: AsyncSession) -> dict:
    adult_yn = (adult_yn or "N").upper()
    if adult_yn not in {"Y", "N"}:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="adult_yn은 Y/N 값만 허용됩니다.",
        )
    user_id = await _get_user_id_by_kc(kc_user_id, db)
    if not user_id:
        return {"sections": [], "needs_onboarding": False}

    dismissed_onboarding = await _is_ai_onboarding_dismissed(user_id, db)
    profile = await get_user_taste_profile(user_id, db)
    recent_read_ids = await _get_recent_read_product_ids(user_id, db)
    has_recent_reads = bool(recent_read_ids)
    needs_onboarding = False
    if not profile:
        profile = await _build_profile_from_recent_reads(user_id, adult_yn, db)
        if not profile:
            weak_section = None
            if has_recent_reads:
                weak_section = await _build_weak_recent_read_section(
                    user_id=user_id,
                    adult_yn=adult_yn,
                    recent_read_ids=recent_read_ids,
                    db=db,
                )
            if weak_section:
                try:
                    async with db.begin_nested():
                        await _save_ai_slot_serving_logs(user_id, [weak_section], db)
                except Exception as e:
                    error_logger.error(
                        f"AI weak slot serving log insert failed: user_id={user_id}, error={e}"
                    )
                return {
                    "sections": [weak_section],
                    "needs_onboarding": not dismissed_onboarding,
                }
            return {"sections": [], "needs_onboarding": not dismissed_onboarding}
    has_onboarding_selection = _has_onboarding_selection(profile)
    if not has_recent_reads and not has_onboarding_selection:
        return {"sections": [], "needs_onboarding": not dismissed_onboarding}

    all_dna = await get_all_product_ai_metadata(db, adult_yn=adult_yn)
    if not all_dna:
        return {"sections": [], "needs_onboarding": needs_onboarding}

    factor_scores = await _get_user_factor_scores(user_id, db)
    total_signal_count = await _get_user_total_signal_count(user_id, db)
    use_dynamic_slots = (
        total_signal_count >= MIN_SIGNAL_COUNT_FOR_DYNAMIC_SLOTS
        and _has_positive_factor_signal(factor_scores)
    )
    sections = (
        _build_dynamic_slot_sections(user_id, profile, factor_scores)
        if use_dynamic_slots
        else _resolve_recommendation_sections(profile, factor_scores)
    )
    if not sections:
        sections = _resolve_recommendation_sections(profile, factor_scores)
    original_sections = list(sections)
    axis_strengths = {
        axis: _axis_signal_strength(axis, factor_scores, profile)
        for axis in AXIS_KEYS
    }
    sections = [
        section
        for section in sections
        if _section_has_collected_category(section, axis_strengths)
    ]
    if not sections:
        if has_recent_reads and not has_onboarding_selection and original_sections:
            # 온보딩을 건너뛴 유저라도 열람 신호가 있으면 최소 1개 구좌는 노출한다.
            sections = original_sections[:1]
        else:
            return {"sections": [], "needs_onboarding": needs_onboarding}

    read_ids = _to_int_set(profile.get("read_product_ids") or []) | recent_read_ids
    taste_tags = set(profile.get("taste_tags") or [])
    result_sections: list[dict] = []
    section_candidates = sections
    for attempt in range(2):
        served_product_ids: set[int] = set()
        result_sections = []
        for section in section_candidates:
            dimension = section.get("dimension", "")
            excluded_ids = read_ids | served_product_ids
            slot_axes = section.get("axes") if isinstance(section.get("axes"), list) else []
            if slot_axes:
                matched = _match_products_by_axes(
                    all_dna,
                    slot_axes,
                    profile,
                    excluded_ids,
                    factor_scores,
                    limit=6,
                )
                if not matched:
                    primary_dimension = _axis_to_legacy_dimension(slot_axes[0])
                    matched = _match_products_by_dimension(
                        all_dna,
                        primary_dimension,
                        profile,
                        excluded_ids,
                        taste_tags,
                        factor_scores,
                        limit=6,
                    )
            else:
                matched = _match_products_by_dimension(
                    all_dna,
                    dimension,
                    profile,
                    excluded_ids,
                    taste_tags,
                    factor_scores,
                    limit=6,
                )
                if not matched and dimension in {"material", "worldview"}:
                    matched = _match_products_by_dimension(
                        all_dna,
                        "theme",
                        profile,
                        excluded_ids,
                        taste_tags,
                        factor_scores,
                        limit=6,
                    )
                if not matched and dimension == "romance":
                    matched = _match_products_by_dimension(
                        all_dna,
                        "mood",
                        profile,
                        excluded_ids,
                        taste_tags,
                        factor_scores,
                        limit=6,
                    )

            products = []
            matched_product_ids: list[int] = []
            for m in matched:
                try:
                    matched_product_ids.append(int(m["product_id"]))
                except (TypeError, ValueError, KeyError):
                    continue
            brief_map = await _get_product_briefs(matched_product_ids, db)

            for m in matched:
                pid = m.get("product_id")
                try:
                    product_info = brief_map.get(int(pid))
                except (TypeError, ValueError):
                    product_info = None
                if product_info:
                    products.append({
                        "productId": product_info["product_id"],
                        "title": product_info["title"],
                        "coverUrl": product_info.get("cover_url"),
                        "authorNickname": product_info.get("author_nickname"),
                        "episodeCount": product_info.get("episode_count", 0),
                        "matchReason": m.get("reason", ""),
                    })
                    served_product_ids.add(int(product_info["product_id"]))

            if products:
                section_axes = slot_axes or _dimension_to_axes(dimension)
                result_sections.append({
                    "title": _build_user_facing_slot_title(section_axes, factor_scores, profile),
                    "dimension": dimension,
                    "reason": section.get("reason", ""),
                    "products": products,
                })

        if result_sections or not use_dynamic_slots or attempt == 1:
            break
        logger.info(
            "AI dynamic slot fallback to legacy sections (user_id=%s, total_signal_count=%s)",
            user_id,
            total_signal_count,
        )
        section_candidates = _resolve_recommendation_sections(profile, factor_scores)

    if result_sections:
        try:
            async with db.begin_nested():
                await _save_ai_slot_serving_logs(user_id, result_sections, db)
        except Exception as e:
            error_logger.error(
                f"AI slot serving log insert failed: user_id={user_id}, section_count={len(result_sections)}, error={e}"
            )
    return {"sections": result_sections, "needs_onboarding": needs_onboarding}


def _to_int_set(values: list) -> set[int]:
    result: set[int] = set()
    for value in values:
        try:
            result.add(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _normalize_factor_key(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _normalize_factor_score(value: float, cap: float = 6.0) -> float:
    """누적 점수를 완만하게 감쇠하고 상/하한을 둔다."""
    if value == 0:
        return 0.0
    normalized = math.copysign(math.log1p(abs(value)), value)
    if normalized > cap:
        return cap
    if normalized < -cap:
        return -cap
    return normalized


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _as_int_list(values) -> list[int]:
    result: list[int] = []
    for value in values or []:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return result


def _has_onboarding_selection(profile: dict | None) -> bool:
    if not isinstance(profile, dict):
        return False
    return bool(_as_list(profile.get("onboarding_picks")) or _as_list(profile.get("onboarding_moods")))


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _daily_seed_for_user(user_id: int) -> int:
    today_kst = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    base = f"{user_id}:{today_kst}"
    return int(hashlib.sha256(base.encode("utf-8")).hexdigest()[:8], 16)


async def _get_recent_read_product_ids(user_id: int, db: AsyncSession, limit: int = 120) -> set[int]:
    safe_limit = max(1, min(int(limit), 500))
    query = text(
        f"""
        SELECT z.product_id
        FROM tb_user_product_usage z
        WHERE z.user_id = :user_id
          AND z.use_yn = 'Y'
        GROUP BY z.product_id
        ORDER BY MAX(z.updated_date) DESC
        LIMIT {safe_limit}
        """
    )
    result = await db.execute(query, {"user_id": user_id})
    return {int(r["product_id"]) for r in result.mappings().all() if r.get("product_id") is not None}


async def _get_recent_read_product_ids_ordered(
    user_id: int,
    db: AsyncSession,
    limit: int = 10,
) -> list[int]:
    safe_limit = max(1, min(int(limit), 50))
    query = text(
        f"""
        SELECT z.product_id
        FROM tb_user_product_usage z
        WHERE z.user_id = :user_id
          AND z.use_yn = 'Y'
        GROUP BY z.product_id
        ORDER BY MAX(z.updated_date) DESC
        LIMIT {safe_limit}
        """
    )
    result = await db.execute(query, {"user_id": user_id})
    ordered_ids: list[int] = []
    for row in result.mappings().all():
        product_id = row.get("product_id")
        if product_id is None:
            continue
        try:
            ordered_ids.append(int(product_id))
        except (TypeError, ValueError):
            continue
    return ordered_ids


async def _build_weak_recent_read_section(
    user_id: int,
    adult_yn: str,
    recent_read_ids: set[int],
    db: AsyncSession,
) -> dict | None:
    ordered_recent_ids = await _get_recent_read_product_ids_ordered(user_id, db, limit=10)
    if not ordered_recent_ids:
        return None

    all_dna = await get_all_product_ai_metadata(db, adult_yn=adult_yn)
    if not all_dna:
        return None

    dna_by_id: dict[int, dict] = {}
    for dna in all_dna:
        try:
            dna_by_id[int(dna.get("product_id"))] = dna
        except (TypeError, ValueError):
            continue

    for product_id in ordered_recent_ids:
        anchor = dna_by_id.get(product_id)
        if not anchor:
            continue

        profile = _build_context_profile(anchor)
        if not profile:
            continue

        read_ids = set(recent_read_ids)
        read_ids.add(product_id)
        taste_tags = set(profile.get("taste_tags") or [])
        sections = _resolve_recommendation_sections(profile, {})

        for section in sections:
            dimension = str(section.get("dimension") or "").strip() or "protagonist"
            matched = _match_products_by_dimension(
                all_dna,
                dimension,
                profile,
                read_ids,
                taste_tags,
                {},
                limit=6,
            )
            if not matched:
                continue

            matched_product_ids: list[int] = []
            for item in matched:
                try:
                    matched_product_ids.append(int(item["product_id"]))
                except (TypeError, ValueError, KeyError):
                    continue

            brief_map = await _get_product_briefs(matched_product_ids, db)
            products: list[dict] = []
            for item in matched:
                pid = item.get("product_id")
                try:
                    product_info = brief_map.get(int(pid))
                except (TypeError, ValueError):
                    product_info = None
                if not product_info:
                    continue
                products.append(
                    {
                        "productId": product_info["product_id"],
                        "title": product_info["title"],
                        "coverUrl": product_info.get("cover_url"),
                        "authorNickname": product_info.get("author_nickname"),
                        "episodeCount": product_info.get("episode_count", 0),
                        "matchReason": item.get("reason", ""),
                    }
                )

            if not products:
                continue

            anchor_title = str(anchor.get("title") or "").strip()
            return {
                "title": (
                    f"최근 본 '{anchor_title}'와 결이 비슷한 작품이에요"
                    if anchor_title
                    else "최근 읽은 작품과 비슷한 추천이에요"
                ),
                "dimension": dimension,
                "reason": "최근 읽은 작품 1개 기준의 약한 추천",
                "products": products,
            }

    return None


async def _build_profile_from_recent_reads(user_id: int, adult_yn: str, db: AsyncSession) -> dict | None:
    """
    콜드스타트 대체 규칙:
    - 최근 열람 작품 pool 5개 이상
    - 각 3회차 이상 읽은 작품이 2개 이상
    """
    query = text(
        """
        SELECT
            z.product_id,
            COUNT(DISTINCT z.episode_id) AS read_episode_count,
            MAX(z.updated_date) AS last_read_date
        FROM tb_user_product_usage z
        WHERE z.user_id = :user_id
          AND z.use_yn = 'Y'
        GROUP BY z.product_id
        ORDER BY last_read_date DESC
        LIMIT 20
        """
    )
    result = await db.execute(query, {"user_id": user_id})
    read_rows = result.mappings().all()
    if len(read_rows) < 5:
        return None

    qualified_rows = [r for r in read_rows if (r.get("read_episode_count") or 0) >= 3]
    if len(qualified_rows) < 2:
        return None

    seed_product_ids = [int(qualified_rows[0]["product_id"]), int(qualified_rows[1]["product_id"])]
    if len(seed_product_ids) < 2:
        return None

    placeholders = ",".join(f":pid_{i}" for i in range(len(seed_product_ids)))
    adult_filter = "AND p.ratings_code = 'all'" if adult_yn == "N" else ""
    dna_query = text(
        f"""
        SELECT m.*
        FROM tb_product_ai_metadata m
        INNER JOIN tb_product p ON p.product_id = m.product_id
        WHERE m.product_id IN ({placeholders})
          AND m.analysis_status = 'success'
          AND COALESCE(m.exclude_from_recommend_yn, 'N') = 'N'
          AND p.open_yn = 'Y'
          {adult_filter}
        """
    )
    params = {f"pid_{i}": pid for i, pid in enumerate(seed_product_ids)}
    dna_result = await db.execute(dna_query, params)
    dna_rows = [_metadata_row_to_dict(r) for r in dna_result.mappings().all()]
    if not dna_rows:
        return None

    protagonist_counts: dict[str, int] = {}
    mood_counts: dict[str, int] = {}
    theme_counts: dict[str, int] = {}
    taste_tags: list[str] = []
    for dna in dna_rows:
        protagonist_labels = _as_list(dna.get("protagonist_type_tags"))
        for label in protagonist_labels:
            normalized = _normalize_allowed_axis_label("type", label)
            if normalized:
                protagonist_counts[normalized] = protagonist_counts.get(normalized, 0) + 1

        style_labels = _as_list(dna.get("axis_style_tags"))
        for label in style_labels:
            normalized = _normalize_allowed_axis_label("style", label)
            if normalized:
                mood_counts[normalized] = mood_counts.get(normalized, 0) + 1

        worldview_labels = _as_list(dna.get("worldview_tags"))
        for label in worldview_labels:
            normalized = _normalize_allowed_axis_label("worldview", label)
            if normalized:
                theme_counts[normalized] = theme_counts.get(normalized, 0) + 1

        for raw_tag in _as_list(dna.get("taste_tags")):
            tag = str(raw_tag or "").strip()
            if tag:
                taste_tags.append(tag)

    top_protagonist = max(protagonist_counts, key=protagonist_counts.get) if protagonist_counts else ""
    top_mood = max(mood_counts, key=mood_counts.get) if mood_counts else ""
    taste_summary = ""
    if top_protagonist and top_mood:
        taste_summary = f"{top_protagonist} 주인공과 {top_mood} 작풍을 선호하는 독자 취향"
    return {
        "preferred_protagonist": protagonist_counts,
        "preferred_mood": mood_counts,
        "preferred_themes": theme_counts,
        "taste_tags": list(dict.fromkeys(taste_tags))[:15],
        "read_product_ids": [int(r["product_id"]) for r in read_rows if r.get("product_id") is not None],
        "taste_summary": taste_summary,
        "recommendation_sections": [
            {"dimension": "protagonist", "title": "당신 취향의 주인공", "reason": ""},
            {"dimension": "material", "title": "당신이 좋아할 설정", "reason": ""},
            {"dimension": "worldview", "title": "당신이 몰입할 세계관", "reason": ""},
        ],
    }


async def _get_user_factor_scores(user_id: int, db: AsyncSession) -> dict[str, dict[str, float]]:
    query = text(
        """
        SELECT factor_type, factor_key, score
        FROM tb_user_taste_factor_score
        WHERE user_id = :user_id
          AND score <> 0
        ORDER BY score DESC
        """
    )
    result = await db.execute(query, {"user_id": user_id})
    by_type: dict[str, dict[str, float]] = {}
    for row in result.mappings().all():
        factor_type = _normalize_factor_key(row.get("factor_type"))
        factor_key = _normalize_factor_key(row.get("factor_key"))
        if not factor_type or not factor_key:
            continue
        score = float(row.get("score") or 0)
        if score == 0:
            continue
        by_type.setdefault(factor_type, {})
        by_type[factor_type][factor_key] = by_type[factor_type].get(factor_key, 0.0) + score

    # raw 누적값을 그대로 쓰지 않고 감쇠/클램프한 값으로 추천 가중치에 반영
    for score_map in by_type.values():
        for key, raw_score in list(score_map.items()):
            score_map[key] = _normalize_factor_score(float(raw_score))

    return by_type


async def _get_user_total_signal_count(user_id: int, db: AsyncSession) -> int:
    query = text(
        """
        SELECT COALESCE(SUM(signal_count), 0) AS total_signal_count
        FROM tb_user_taste_factor_score
        WHERE user_id = :user_id
          AND signal_count > 0
        """
    )
    result = await db.execute(query, {"user_id": user_id})
    row = result.mappings().one_or_none()
    if not row:
        return 0
    return int(row.get("total_signal_count") or 0)


def _has_positive_factor_signal(factor_scores: dict[str, dict[str, float]]) -> bool:
    for entries in factor_scores.values():
        for score in entries.values():
            if _safe_float(score, 0.0) > 0:
                return True
    return False


AXIS_KEYS: tuple[str, ...] = ("type", "job", "goal", "material", "worldview", "romance", "style")


def _normalize_axis_key(value: str | None) -> str:
    normalized = _normalize_factor_key(value)
    if normalized in AXIS_KEYS:
        return normalized
    return ""


def _dimension_to_axes(dimension: str) -> list[str]:
    normalized = _normalize_factor_key(dimension)
    if not normalized:
        return []

    if "_" in normalized:
        axes = [_normalize_axis_key(axis) for axis in normalized.split("_")]
        axes = [axis for axis in axes if axis]
        if axes:
            return list(dict.fromkeys(axes))

    mapping: dict[str, list[str]] = {
        "protagonist": ["type", "job", "goal"],
        "type": ["type"],
        "job": ["job"],
        "goal": ["goal"],
        "material": ["material"],
        "worldview": ["worldview"],
        "theme": ["worldview"],
        "romance": ["romance"],
        "mood": ["style"],
        "style": ["style"],
    }
    return mapping.get(normalized, [])


def _section_has_collected_category(section: dict, axis_strengths: dict[str, float]) -> bool:
    raw_axes = section.get("axes")
    parsed_axes: list[str] = []
    if isinstance(raw_axes, list):
        for axis in raw_axes:
            normalized = _normalize_axis_key(str(axis))
            if normalized and normalized not in parsed_axes:
                parsed_axes.append(normalized)
    if parsed_axes:
        positive_count = sum(1 for axis in parsed_axes if axis_strengths.get(axis, 0.0) > 0)
        required_count = math.ceil(len(parsed_axes) / 2)
        return positive_count >= required_count

    mapped_axes = _dimension_to_axes(str(section.get("dimension") or ""))
    if not mapped_axes:
        return False
    return any(axis_strengths.get(axis, 0.0) > 0 for axis in mapped_axes)


def _top_axis_label(axis: str, factor_scores: dict[str, dict[str, float]], profile: dict) -> str:
    top_entries, _ = _build_axis_top3_entries(axis, factor_scores, profile, top_n=1)
    if not top_entries:
        return ""
    return str(top_entries[0].get("label") or "").strip()


def _build_user_facing_slot_title(
    axes: list[str],
    factor_scores: dict[str, dict[str, float]],
    profile: dict,
) -> str:
    normalized_axes: list[str] = []
    for axis in axes:
        normalized = _normalize_axis_key(axis)
        if normalized and normalized not in normalized_axes:
            normalized_axes.append(normalized)

    if not normalized_axes:
        return "최근 읽은 작품 기반 추천"

    first_axis = normalized_axes[0]
    first_label = _top_axis_label(first_axis, factor_scores, profile)
    first_axis_label = AXIS_DISPLAY_LABEL.get(first_axis, first_axis)

    if len(normalized_axes) >= 2:
        second_axis = normalized_axes[1]
        second_label = _top_axis_label(second_axis, factor_scores, profile)
        second_axis_label = AXIS_DISPLAY_LABEL.get(second_axis, second_axis)

        if first_label and second_label:
            return (
                f"요즘 '{first_label}' {first_axis_label}과 "
                f"'{second_label}' {second_axis_label} 조합을 좋아하시나봐요"
            )
        if first_label:
            return f"요즘 '{first_label}' {first_axis_label}을 특히 좋아하시나봐요"
        if second_label:
            return f"요즘 '{second_label}' {second_axis_label}을 특히 좋아하시나봐요"
        return "최근 읽은 작품 기반 추천"

    if first_label:
        return f"요즘 '{first_label}' {first_axis_label} 작품을 특히 좋아하시나봐요"
    return f"요즘 {first_axis_label} 취향 작품을 추천해드려요"


def _axis_to_legacy_dimension(axis: str) -> str:
    mapping = {
        "type": "protagonist",
        "material": "material",
        "job": "protagonist",
        "goal": "protagonist",
        "worldview": "worldview",
        "romance": "romance",
        "style": "mood",
    }
    return mapping.get(axis, "protagonist")


def _build_dynamic_slot_sections(
    user_id: int,
    profile: dict,
    factor_scores: dict[str, dict[str, float]],
) -> list[dict]:
    seed = _daily_seed_for_user(user_id)

    axis_a2 = "material" if (seed & 1) == 0 else "job"
    axis_b = "goal" if ((seed >> 1) & 1) == 0 else "romance"
    axis_c = "worldview" if ((seed >> 2) & 1) == 0 else "style"

    material_strength = _axis_signal_strength("material", factor_scores, profile)
    job_strength = _axis_signal_strength("job", factor_scores, profile)
    if axis_a2 == "material" and material_strength <= 0 and job_strength > 0:
        axis_a2 = "job"
    elif axis_a2 == "job" and job_strength <= 0 and material_strength > 0:
        axis_a2 = "material"

    romance_strength = _axis_signal_strength("romance", factor_scores, profile)
    goal_strength = _axis_signal_strength("goal", factor_scores, profile)
    if axis_b == "romance" and romance_strength <= 0 and goal_strength > 0:
        axis_b = "goal"
    elif axis_b == "goal" and goal_strength <= 0 and romance_strength > 0:
        axis_b = "romance"

    worldview_strength = _axis_signal_strength("worldview", factor_scores, profile)
    style_strength = _axis_signal_strength("style", factor_scores, profile)
    if axis_c == "worldview" and worldview_strength <= 0 and style_strength > 0:
        axis_c = "style"
    elif axis_c == "style" and style_strength <= 0 and worldview_strength > 0:
        axis_c = "worldview"

    slot_axes = [
        ["type", axis_a2],
        [axis_b],
        [axis_c],
    ]
    sections = []
    for axes in slot_axes:
        short_labels = [AXIS_SHORT_LABEL.get(axis, axis) for axis in axes]
        if len(short_labels) == 2:
            title = f"AI 추천 : {short_labels[0]}+{short_labels[1]}인 작품"
            reason = f"{short_labels[0]}+{short_labels[1]} 축 행동 신호 기반"
            dimension = f"{axes[0]}_{axes[1]}"
        else:
            title = f"AI 추천 : {short_labels[0]}인 작품"
            reason = f"{short_labels[0]} 축 행동 신호 기반"
            dimension = axes[0]
        sections.append(
            {
                "title": title,
                "reason": reason,
                "dimension": dimension,
                "axes": axes,
            }
        )
    return sections


def _axis_signal_strength(axis: str, factor_scores: dict[str, dict[str, float]], profile: dict) -> float:
    label_scores = _build_user_axis_label_scores(axis, factor_scores, profile)
    return float(sum(label_scores.values()))


def _axis_factor_types(axis: str) -> tuple[str, ...]:
    mapping = {
        "type": ("protagonist",),
        "job": ("job",),
        "goal": ("goal", "protagonist"),
        "material": ("material",),
        "worldview": ("worldview", "theme"),
        "romance": ("romance",),
        "style": ("style", "mood"),
    }
    return mapping.get(axis, tuple())


def _profile_count_map_to_scores(value) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    raw: dict[str, float] = {}
    max_value = 0.0
    for key, score in value.items():
        normalized_key = _normalize_factor_key(key)
        if not normalized_key:
            continue
        score_value = _safe_float(score, 0.0)
        if score_value <= 0:
            continue
        raw[normalized_key] = max(raw.get(normalized_key, 0.0), score_value)
        max_value = max(max_value, score_value)
    if max_value <= 0:
        return {}
    return {
        key: _clamp(score / max_value, 0.0, 1.0)
        for key, score in raw.items()
    }


def _build_user_axis_label_scores(
    axis: str,
    factor_scores: dict[str, dict[str, float]],
    profile: dict,
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for factor_type in _axis_factor_types(axis):
        entries = factor_scores.get(_normalize_factor_key(factor_type), {})
        for key, raw in entries.items():
            normalized_key = _normalize_factor_key(key)
            if not normalized_key:
                continue
            raw_score = float(raw or 0.0)
            if raw_score <= 0:
                continue
            if axis == "goal" and factor_type == "protagonist" and normalized_key not in GOAL_LABEL_KEYS:
                continue
            normalized_score = _clamp(raw_score / 6.0, 0.0, 1.0)
            if normalized_score <= 0:
                continue
            scores[normalized_key] = max(scores.get(normalized_key, 0.0), normalized_score)

    if scores:
        filtered = _filter_axis_label_scores(axis, scores)
        if filtered:
            return filtered
        scores = {}

    if axis == "type":
        scores.update(_profile_count_map_to_scores(profile.get("preferred_protagonist") or {}))
    elif axis == "worldview":
        scores.update(_profile_count_map_to_scores(profile.get("preferred_themes") or {}))
    elif axis == "style":
        scores.update(_profile_count_map_to_scores(profile.get("preferred_mood") or {}))
    elif axis == "romance":
        heroine_weight = _normalize_factor_key(profile.get("preferred_heroine_weight"))
        if heroine_weight:
            scores[heroine_weight] = 0.7
    elif axis == "goal":
        taste_tags = _as_list(profile.get("taste_tags"))
        for tag in taste_tags:
            normalized_key = _normalize_factor_key(tag)
            if normalized_key in GOAL_LABEL_KEYS:
                scores[normalized_key] = max(scores.get(normalized_key, 0.0), 0.5)

    return _filter_axis_label_scores(axis, scores)


def _build_axis_top3_entries(
    axis: str,
    factor_scores: dict[str, dict[str, float]],
    profile: dict,
    top_n: int = 3,
) -> tuple[list[dict], float]:
    label_scores = _build_user_axis_label_scores(axis, factor_scores, profile)
    if not label_scores:
        return [], 0.0

    sorted_labels = [
        (label, float(score))
        for label, score in sorted(label_scores.items(), key=lambda item: item[1], reverse=True)
        if label and _safe_float(score, 0.0) > 0
    ][:top_n]
    if not sorted_labels:
        return [], 0.0

    total_score = sum(score for _, score in sorted_labels)
    if total_score <= 0:
        return [], 0.0

    percents = [int(round((score / total_score) * 100)) for _, score in sorted_labels]
    if percents:
        diff = 100 - sum(percents)
        percents[0] = max(0, percents[0] + diff)

    entries: list[dict] = []
    for (label, score), percent in zip(sorted_labels, percents):
        entries.append(
            {
                "label": label,
                "percent": int(percent),
                "score": round(float(score), 4),
            }
        )

    return entries, float(sorted_labels[0][1])


def _build_axis_insight(axis: str, top_entries: list[dict]) -> str:
    if not top_entries:
        return ""
    top_label = str(top_entries[0].get("label") or "").strip()
    if not top_label:
        return ""

    templates = {
        "type": "나는 주인공이 '{label}'인 작품을 좋아해요.",
        "job": "나는 주인공 직업이 '{label}'인 작품을 좋아해요.",
        "goal": "나는 주인공 목표가 '{label}'인 작품을 좋아해요.",
        "material": "나는 능력/소재가 '{label}'인 작품을 좋아해요.",
        "worldview": "나는 세계관이 '{label}'인 작품을 좋아해요.",
        "romance": "나는 관계/로맨스가 '{label}'인 작품을 좋아해요.",
        "style": "나는 작풍이 '{label}'인 작품을 좋아해요.",
    }
    template = templates.get(axis, "나는 '{label}' 성향의 작품을 좋아해요.")
    return template.format(label=top_label)


def _build_compact_taste_summary(axis_top3: dict[str, list[dict]]) -> str:
    def _top_label(axis: str) -> str:
        entries = axis_top3.get(axis) or []
        if not entries:
            return ""
        return str(entries[0].get("label") or "").strip()

    job_label = _top_label("job")
    type_label = _top_label("type")
    material_label = _top_label("material")
    goal_label = _top_label("goal")
    worldview_label = _top_label("worldview")
    romance_label = _top_label("romance")
    style_label = _top_label("style")

    if all([job_label, type_label, material_label, goal_label, worldview_label, romance_label, style_label]):
        return (
            f"주인공이 '{job_label}'이고, '{type_label}'과 '{material_label}'을 보유하고 있고, "
            f"'{goal_label}' 지향적이며, 세계관이 '{worldview_label}'이고, "
            f"관계/로맨스가 '{romance_label}', 작풍이 '{style_label}'인 작품을 좋아하시는 것 같아요."
        )

    clauses: list[str] = []
    if job_label:
        clauses.append(f"주인공 직업이 '{job_label}'")
    if type_label:
        clauses.append(f"주인공 유형이 '{type_label}'")
    if material_label:
        clauses.append(f"능력/소재가 '{material_label}'")
    if goal_label:
        clauses.append(f"주인공 목표가 '{goal_label}'")
    if worldview_label:
        clauses.append(f"세계관이 '{worldview_label}'")
    if romance_label:
        clauses.append(f"관계/로맨스가 '{romance_label}'")
    if style_label:
        clauses.append(f"작풍이 '{style_label}'")

    if not clauses:
        return ""
    if len(clauses) == 1:
        return f"{clauses[0]} 작품을 좋아하시는 것 같아요."
    return f"{', '.join(clauses[:-1])}이고, {clauses[-1]}인 작품을 좋아하시는 것 같아요."


def _collect_product_axis_labels(dna: dict, axis: str) -> dict[str, float]:
    if axis == "goal":
        goal = _normalize_factor_key(dna.get("protagonist_goal_primary"))
        goal_confidence = _safe_float(dna.get("goal_confidence"), 0.0)
        if not goal:
            return {}
        if goal == "생존" and goal_confidence < 0.6:
            return {}
        if goal_confidence < AXIS_CONFIDENCE_THRESHOLD:
            return {}
        return {goal: _clamp(goal_confidence, AXIS_CONFIDENCE_THRESHOLD, 1.0)}

    overall_confidence = _safe_float(dna.get("overall_confidence"), 1.0)
    if overall_confidence < AXIS_CONFIDENCE_THRESHOLD:
        return {}
    label_score = _clamp(overall_confidence, AXIS_CONFIDENCE_THRESHOLD, 1.0)

    raw_values: list[str] = []
    if axis == "type":
        raw_values.extend(_as_list(dna.get("protagonist_type_tags")))
        if not raw_values and dna.get("protagonist_type"):
            raw_values.append(str(dna.get("protagonist_type")))
    elif axis == "job":
        raw_values.extend(_as_list(dna.get("protagonist_job_tags")))
    elif axis == "material":
        raw_values.extend(_as_list(dna.get("protagonist_material_tags")))
    elif axis == "worldview":
        raw_values.extend(_as_list(dna.get("worldview_tags")))
    elif axis == "romance":
        raw_values.extend(_as_list(dna.get("axis_romance_tags")))
        romance_weight = dna.get("romance_chemistry_weight")
        if romance_weight:
            raw_values.append(str(romance_weight))
    elif axis == "style":
        raw_values.extend(_as_list(dna.get("axis_style_tags")))

    labels: dict[str, float] = {}
    for raw in raw_values:
        normalized = _normalize_factor_key(raw)
        if not normalized:
            continue
        labels[normalized] = max(labels.get(normalized, 0.0), label_score)
    return labels


def _calculate_axis_match(
    dna: dict,
    axis: str,
    user_axis_label_scores: dict[str, float],
) -> tuple[float, bool]:
    product_label_scores = _collect_product_axis_labels(dna, axis)
    if not product_label_scores:
        return 0.0, False

    denominator = float(sum(product_label_scores.values()))
    if denominator <= 0:
        return 0.0, True

    numerator = 0.0
    for label, product_score in product_label_scores.items():
        numerator += min(user_axis_label_scores.get(label, 0.0), product_score)

    return _clamp(numerator / denominator, 0.0, 1.0), True


def _match_products_by_axes(
    all_dna: list[dict],
    axes: list[str],
    profile: dict,
    excluded_ids: set[int],
    factor_scores: dict[str, dict[str, float]],
    limit: int = 6,
) -> list[dict]:
    if not axes:
        return []

    unique_axes = []
    for axis in axes:
        if axis not in unique_axes:
            unique_axes.append(axis)

    user_axis_scores = {
        axis: _build_user_axis_label_scores(axis, factor_scores, profile)
        for axis in unique_axes
    }

    positive_scored: list[dict] = []
    zero_scored: list[dict] = []
    for dna in all_dna:
        pid = dna.get("product_id")
        if pid is None or pid in excluded_ids:
            continue

        slot_score = 0.0
        has_any_axis_label = False
        axis_matches: dict[str, float] = {}
        for axis in unique_axes:
            axis_match, has_axis_label = _calculate_axis_match(
                dna,
                axis,
                user_axis_scores.get(axis, {}),
            )
            axis_matches[axis] = axis_match
            has_any_axis_label = has_any_axis_label or has_axis_label
            slot_score += AXIS_WEIGHT.get(axis, 0.0) * axis_match

        if not has_any_axis_label:
            continue

        popularity = math.log10((dna.get("count_hit") or 0) + 1)
        engagement_score = score_engagement_for_recommendation(dna)
        reason = dna.get("protagonist_desc") or dna.get("premise") or ""
        row = {
            "product_id": pid,
            "score": slot_score,
            "engagement_score": engagement_score,
            "popularity": popularity,
            "reason": reason,
        }
        if slot_score > 0:
            positive_scored.append(row)
        else:
            zero_scored.append(row)

    if positive_scored:
        positive_scored.sort(
            key=lambda x: (x["score"], x["engagement_score"], x["popularity"]),
            reverse=True,
        )
        return positive_scored[:limit]

    zero_scored.sort(
        key=lambda x: (x["engagement_score"], x["popularity"]),
        reverse=True,
    )
    return zero_scored[:limit]


def _resolve_recommendation_sections(profile: dict, factor_scores: dict[str, dict[str, float]]) -> list[dict]:
    has_new_factors = any(
        factor_scores.get(k) for k in ("protagonist", "material", "worldview", "romance")
    )
    if has_new_factors:
        worldview_total = sum((factor_scores.get("worldview") or {}).values())
        romance_total = sum((factor_scores.get("romance") or {}).values())
        third_dimension = "worldview" if worldview_total >= romance_total else "romance"
        third_title = "당신이 몰입할 세계관" if third_dimension == "worldview" else "당신 취향의 연애 케미"
        return [
            {"dimension": "protagonist", "title": "당신 취향의 주인공", "reason": ""},
            {"dimension": "material", "title": "당신이 좋아할 설정", "reason": ""},
            {"dimension": third_dimension, "title": third_title, "reason": ""},
        ]

    sections = profile.get("recommendation_sections") or []
    if sections:
        return sections[:3]
    return [
        {"dimension": "protagonist", "title": "당신 취향의 주인공", "reason": ""},
        {"dimension": "mood", "title": "당신에게 맞는 분위기", "reason": ""},
        {"dimension": "theme", "title": "당신이 좋아할 테마", "reason": ""},
    ]


def _match_products_by_dimension(
    all_dna: list[dict],
    dimension: str,
    profile: dict,
    read_ids: set,
    taste_tags: set,
    factor_scores: dict[str, dict[str, float]],
    limit: int = 6,
) -> list[dict]:
    """차원별 작품 매칭. taste_tags 유사도 기반 정렬."""
    scored = []
    for dna in all_dna:
        pid = dna.get("product_id")
        if pid in read_ids:
            continue

        product_tags = set(dna.get("taste_tags") or [])
        overlap = len(taste_tags & product_tags)

        # 차원별 가중치
        bonus = 0.0
        dimension_key = _normalize_factor_key(dimension)
        normalized_factor_scores = factor_scores.get(dimension_key, {})

        if dimension_key == "protagonist":
            protagonist = _normalize_factor_key(dna.get("protagonist_type"))
            if protagonist:
                bonus += normalized_factor_scores.get(protagonist, 0.0)
            goal_primary = _normalize_factor_key(dna.get("protagonist_goal_primary"))
            goal_confidence = float(dna.get("goal_confidence") or 0)
            if goal_primary and not (goal_primary == "생존" and goal_confidence < 0.6):
                bonus += normalized_factor_scores.get(goal_primary, 0.0)
        elif dimension_key == "material":
            for tag in _as_list(dna.get("protagonist_material_tags")):
                bonus += normalized_factor_scores.get(_normalize_factor_key(tag), 0.0)
        elif dimension_key == "worldview":
            for tag in _as_list(dna.get("worldview_tags")):
                bonus += normalized_factor_scores.get(_normalize_factor_key(tag), 0.0)
        elif dimension_key == "romance":
            romance_weight = _normalize_factor_key(dna.get("romance_chemistry_weight"))
            if romance_weight:
                bonus += normalized_factor_scores.get(romance_weight, 0.0)

        if dimension == "protagonist":
            pref = profile.get("preferred_protagonist") or {}
            if dna.get("protagonist_type") in pref:
                bonus += _safe_float(pref.get(dna["protagonist_type"]), 0.0)
        elif dimension == "mood":
            pref = profile.get("preferred_mood") or {}
            if dna.get("mood") in pref:
                bonus += _safe_float(pref.get(dna["mood"]), 0.0)
        elif dimension == "theme":
            pref = profile.get("preferred_themes") or {}
            for theme in _as_list(dna.get("themes")):
                bonus += _safe_float(pref.get(theme), 0.0)

        popularity_bonus = math.log10((dna.get("count_hit") or 0) + 1)
        engagement_bonus = score_engagement_for_recommendation(dna)
        score = (overlap * 0.7) + bonus + (popularity_bonus * 0.3) + (engagement_bonus * 0.8)
        if score <= 0:
            continue
        reason = dna.get("protagonist_desc") or dna.get("premise") or ""
        scored.append({
            "product_id": pid,
            "score": score,
            "engagement_score": engagement_bonus,
            "reason": reason,
        })

    scored.sort(key=lambda x: (x["score"], x["engagement_score"]), reverse=True)
    return scored[:limit]


def _format_serial_cycle(writing_per_week: float, status_code: str = "") -> str | None:
    if status_code in ("complete", "completed"):
        return "완결"
    if writing_per_week >= 5:
        return "매일 연재"
    if writing_per_week >= 1:
        return f"주 {round(writing_per_week)}회"
    if writing_per_week > 0:
        return "비정기 연재"
    return None


async def _get_product_brief(product_id: int, db: AsyncSession) -> dict | None:
    query = text("""
        SELECT
            p.product_id, p.title, p.status_code,
            p.price_type, p.monopoly_yn, p.contract_yn, p.last_episode_date,
            IF(p.last_episode_date >= DATE_SUB(NOW(), INTERVAL 24 HOUR), 'Y', 'N') AS new_release_yn,
            p.author_name AS author_nickname,
            (SELECT COUNT(*) FROM tb_product_episode e
             WHERE e.product_id = p.product_id AND e.use_yn = 'Y') AS episode_count,
            COALESCE(pti.writing_count_per_week, 0) AS writing_count_per_week,
            IF(wff.product_id IS NOT NULL, 'Y', 'N') AS waiting_for_free_yn,
            IF(p69.product_id IS NOT NULL, 'Y', 'N') AS six_nine_path_yn,
            IF(p.thumbnail_file_id IS NULL, NULL,
               (SELECT CASE
                         WHEN w.file_path IS NULL OR w.file_path = '' THEN NULL
                         WHEN w.file_path LIKE 'http://%' OR w.file_path LIKE 'https://%' THEN w.file_path
                         ELSE CONCAT(:cdn, '/', w.file_path)
                       END
                FROM tb_common_file q, tb_common_file_item w
                WHERE q.file_group_id = w.file_group_id
                  AND q.use_yn = 'Y' AND w.use_yn = 'Y'
                  AND q.group_type = 'cover'
                  AND q.file_group_id = p.thumbnail_file_id)) AS cover_url
        FROM tb_product p
        LEFT JOIN tb_product_trend_index pti ON pti.product_id = p.product_id
        LEFT JOIN tb_applied_promotion wff ON wff.product_id = p.product_id AND wff.type = 'waiting-for-free' AND wff.status = 'ing' AND DATE(wff.start_date) <= CURDATE() AND (wff.end_date IS NULL OR DATE(wff.end_date) >= CURDATE())
        LEFT JOIN tb_applied_promotion p69 ON p69.product_id = p.product_id AND p69.type = '6-9-path' AND p69.status = 'ing' AND DATE(p69.start_date) <= CURDATE() AND (p69.end_date IS NULL OR DATE(p69.end_date) >= CURDATE())
        WHERE p.product_id = :pid
          AND p.open_yn = 'Y'
    """)
    result = await db.execute(query, {"pid": product_id, "cdn": settings.R2_SC_CDN_URL})
    row = result.mappings().one_or_none()
    return dict(row) if row else None


async def _get_product_briefs(product_ids: list[int], db: AsyncSession) -> dict[int, dict]:
    unique_ids: list[int] = []
    seen: set[int] = set()
    for pid in product_ids:
        try:
            normalized = int(pid)
        except (TypeError, ValueError):
            continue
        if normalized <= 0 or normalized in seen:
            continue
        unique_ids.append(normalized)
        seen.add(normalized)

    if not unique_ids:
        return {}

    placeholders = ",".join(f":pid_{idx}" for idx in range(len(unique_ids)))
    query = text(
        f"""
        SELECT
            p.product_id, p.title, p.status_code,
            p.author_name AS author_nickname,
            (SELECT COUNT(*) FROM tb_product_episode e
             WHERE e.product_id = p.product_id AND e.use_yn = 'Y') AS episode_count,
            IF(p.thumbnail_file_id IS NULL, NULL,
               (SELECT CASE
                         WHEN w.file_path IS NULL OR w.file_path = '' THEN NULL
                         WHEN w.file_path LIKE 'http://%' OR w.file_path LIKE 'https://%' THEN w.file_path
                         ELSE CONCAT(:cdn, '/', w.file_path)
                       END
                FROM tb_common_file q, tb_common_file_item w
                WHERE q.file_group_id = w.file_group_id
                  AND q.use_yn = 'Y' AND w.use_yn = 'Y'
                  AND q.group_type = 'cover'
                  AND q.file_group_id = p.thumbnail_file_id)) AS cover_url
        FROM tb_product p
        WHERE p.product_id IN ({placeholders})
          AND p.open_yn = 'Y'
        """
    )
    params = {"cdn": settings.R2_SC_CDN_URL}
    params.update({f"pid_{idx}": pid for idx, pid in enumerate(unique_ids)})
    result = await db.execute(query, params)
    return {
        int(row["product_id"]): dict(row)
        for row in result.mappings().all()
        if row.get("product_id") is not None
    }


async def _save_ai_slot_serving_logs(user_id: int, sections: list[dict], db: AsyncSession) -> None:
    if user_id <= 0 or not sections:
        return

    rows: list[dict] = []
    for section in sections:
        slot_type = str(section.get("dimension") or "").strip()[:50]
        if not slot_type:
            continue
        slot_key_raw = str(section.get("title") or "").strip()
        slot_key = slot_key_raw[:100] if slot_key_raw else None
        for product in section.get("products") or []:
            try:
                product_id = int(product.get("productId"))
            except (TypeError, ValueError, AttributeError):
                continue
            if product_id <= 0:
                continue
            rows.append(
                {
                    "user_id": user_id,
                    "slot_type": slot_type,
                    "slot_key": slot_key,
                    "product_id": product_id,
                }
            )

    if not rows:
        return

    query = text(
        """
        INSERT INTO tb_ai_slot_serving_log (
            user_id,
            slot_type,
            slot_key,
            product_id,
            clicked_yn,
            continued_3ep_yn
        ) VALUES (
            :user_id,
            :slot_type,
            :slot_key,
            :product_id,
            'N',
            'N'
        )
        """
    )
    await db.execute(query, rows)


# ──────────────────────────────────────────────────────────
#  AI 챗 추천
# ──────────────────────────────────────────────────────────

PRESET_FILTERS = {
    "stacked-chapters": "(SELECT COUNT(*) FROM tb_product_episode e WHERE e.product_id = p.product_id AND e.use_yn = 'Y') >= 50",
    "good-schedule": "pti.writing_count_per_week >= 3",
    "completed": "1=1",
    "trending": "1=1",  # count_hit 기준 정렬로 처리
}
PRESET_STATUS_FILTERS = {
    "completed": "end",
}

PRESET_LABELS = {
    "stacked-chapters": "회차 쌓인 작품",
    "good-schedule": "연재주기 좋은 작품",
    "completed": "완결작",
    "trending": "요즘 뜨는 작품",
}
PRESET_QUERY_ORDER_CLAUSES = {
    "stacked-chapters": "episode_count DESC, COALESCE(pti.reading_rate, 0) DESC, COALESCE(pem.binge_rate, 0) DESC, p.count_hit DESC",
    "good-schedule": "COALESCE(pti.writing_count_per_week, 0) DESC, COALESCE(pti.reading_rate, 0) DESC, COALESCE(pem.binge_rate, 0) DESC, p.count_hit DESC",
    "completed": "COALESCE(pti.reading_rate, 0) DESC, COALESCE(pem.binge_rate, 0) DESC, COALESCE(ev.evaluation_score, 0) DESC, p.count_hit DESC",
    "trending": "p.count_hit DESC, COALESCE(pti.reading_rate, 0) DESC, COALESCE(pem.binge_rate, 0) DESC",
}
PRESET_RELAXED_FALLBACKS = {
    "completed": ["stacked-chapters", "trending", "good-schedule"],
    "stacked-chapters": ["trending", "good-schedule"],
    "good-schedule": ["trending", "stacked-chapters"],
    "trending": ["stacked-chapters", "good-schedule"],
}


async def ai_recommend(
    kc_user_id: str,
    query_text: str | None,
    preset: str | None,
    exclude_ids: list[int],
    adult_yn: str,
    db: AsyncSession,
    context: dict | None = None,
) -> dict:
    normalized_query_text = (query_text or "").strip()
    query_text = normalized_query_text or None
    adult_yn = (adult_yn or "N").upper()
    if adult_yn not in {"Y", "N"}:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="adult_yn은 Y/N 값만 허용됩니다.",
        )
    if preset is not None:
        preset = preset.strip() or None
    if preset and not query_text and preset not in PRESET_FILTERS:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="preset 값이 유효하지 않습니다.",
        )
    user_id = await _get_user_id_by_kc(kc_user_id, db)
    profile = await get_user_taste_profile(user_id, db) if user_id else None
    factor_scores = await _get_user_factor_scores(user_id, db) if user_id else {}

    if preset and not query_text:
        try:
            return await _preset_recommend(
                user_id,
                profile,
                factor_scores,
                preset,
                exclude_ids,
                adult_yn,
                db,
                context=context,
            )
        except CustomResponseException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            fallback_result = await _build_relaxed_preset_fallback_result(
                user_id=user_id,
                profile=profile,
                factor_scores=factor_scores,
                requested_preset=preset,
                exclude_ids=exclude_ids or [],
                adult_yn=adult_yn,
                db=db,
                context=context,
            )
            if fallback_result:
                return fallback_result
            raise
    else:
        return await _freeform_recommend(
            profile,
            query_text or "재미있는 작품 추천해줘",
            exclude_ids,
            adult_yn,
            db,
        )


async def ai_chat(
    kc_user_id: str,
    messages: list[dict] | None,
    context: dict | None,
    preset: str | None,
    exclude_ids: list[int],
    adult_yn: str,
    db: AsyncSession,
) -> dict:
    """AI 챗 최소 구현: 프리셋은 프리셋 필터, 자유질문은 히스토리 맥락 반영."""
    normalized_preset = (preset or "").strip() or None

    if normalized_preset:
        try:
            recommend_result = await ai_recommend(
                kc_user_id=kc_user_id,
                query_text=None,
                preset=normalized_preset,
                exclude_ids=exclude_ids or [],
                adult_yn=adult_yn,
                db=db,
                context=context,
            )
        except CustomResponseException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            user_id = await _get_user_id_by_kc(kc_user_id, db)
            profile = await get_user_taste_profile(user_id, db) if user_id else None
            factor_scores = await _get_user_factor_scores(user_id, db) if user_id else {}
            fallback_result = await _build_relaxed_preset_fallback_result(
                user_id=user_id,
                profile=profile,
                factor_scores=factor_scores,
                requested_preset=normalized_preset,
                exclude_ids=exclude_ids or [],
                adult_yn=adult_yn,
                db=db,
                context=context,
            )
            if fallback_result:
                taste_match = fallback_result.get("taste_match") or fallback_result.get("tasteMatch") or {
                    "protagonist": 0,
                    "mood": 0,
                    "pacing": 0,
                }
                return {
                    "reply": fallback_result.get("reason") or "",
                    "product": fallback_result.get("product"),
                    "taste_match": taste_match,
                    "tasteMatch": taste_match,
                }
            return await _build_relaxed_preset_chat_fallback(
                kc_user_id=kc_user_id,
                requested_preset=normalized_preset,
                exclude_ids=exclude_ids or [],
                adult_yn=adult_yn,
                db=db,
                context=context,
            )
    else:
        user_messages: list[str] = []
        for message in messages or []:
            if str(message.get("role") or "").lower() != "user":
                continue
            content = str(message.get("content") or "").strip()
            if content:
                user_messages.append(content)

        query_text = "재미있는 작품 추천해줘"
        if user_messages:
            current_query = user_messages[-1]
            prev_queries = user_messages[-4:-1]
            if prev_queries:
                prev_context = " / ".join(prev_queries)
                query_text = f"이전 대화 맥락: {prev_context}\n현재 요청: {current_query}"
            else:
                query_text = current_query
        else:
            trigger = str((context or {}).get("trigger") or "").lower()
            if trigger == "browsing":
                query_text = "최근에 본 작품이랑 비슷한 작품 추천해줘"

        recommend_result = await ai_recommend(
            kc_user_id=kc_user_id,
            query_text=query_text,
            preset=None,
            exclude_ids=exclude_ids or [],
            adult_yn=adult_yn,
            db=db,
        )

    taste_match = recommend_result.get("taste_match") or recommend_result.get("tasteMatch") or {
        "protagonist": 0,
        "mood": 0,
        "pacing": 0,
    }

    return {
        "reply": recommend_result.get("reason") or "",
        "product": recommend_result.get("product"),
        "taste_match": taste_match,
        "tasteMatch": taste_match,
    }


def has_profile_preference_signal(profile: dict | None) -> bool:
    if not isinstance(profile, dict):
        return False
    return bool(
        _as_list(profile.get("taste_tags"))
        or profile.get("preferred_protagonist")
        or profile.get("preferred_mood")
        or profile.get("preferred_themes")
        or profile.get("preferred_pacing")
        or _has_onboarding_selection(profile)
    )


def _has_recommendation_taste_signal(
    profile: dict | None,
    factor_scores: dict[str, dict[str, float]] | None = None,
) -> bool:
    if factor_scores and _has_positive_factor_signal(factor_scores):
        return True
    return has_profile_preference_signal(profile)


def _score_taste_for_candidate_legacy(candidate: dict, profile: dict | None) -> float:
    if not has_profile_preference_signal(profile):
        return 0.0

    taste_tags = set(profile.get("taste_tags") or [])
    tags = candidate.get("taste_tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            tags = []

    tag_overlap = len(taste_tags & set(tags))
    taste_match = _compute_taste_match(candidate, profile)
    return round(
        (_safe_float(taste_match.get("protagonist"), 0.0) * 3.0)
        + (_safe_float(taste_match.get("mood"), 0.0) * 3.0)
        + (_safe_float(taste_match.get("pacing"), 0.0) * 1.8)
        + (min(tag_overlap, 4) * 0.6),
        4,
    )


def _score_taste_for_candidate_by_axes(
    candidate: dict,
    profile: dict | None,
    factor_scores: dict[str, dict[str, float]] | None = None,
) -> float:
    if not _has_recommendation_taste_signal(profile, factor_scores):
        return 0.0

    effective_profile = profile if isinstance(profile, dict) else {}
    normalized_factor_scores = factor_scores or {}
    weighted_score = 0.0
    active_weight = 0.0

    for axis in AXIS_KEYS:
        user_axis_scores = _build_user_axis_label_scores(axis, normalized_factor_scores, effective_profile)
        if not user_axis_scores:
            continue
        axis_match, has_axis_label = _calculate_axis_match(candidate, axis, user_axis_scores)
        axis_weight = AXIS_WEIGHT.get(axis, 0.0)
        active_weight += axis_weight
        if not has_axis_label:
            continue
        weighted_score += axis_weight * axis_match

    if active_weight <= 0:
        return 0.0

    return round((weighted_score / active_weight) * 10.0, 4)


def score_taste_for_candidate(
    candidate: dict,
    profile: dict | None,
    factor_scores: dict[str, dict[str, float]] | None = None,
) -> float:
    legacy_score = _score_taste_for_candidate_legacy(candidate, profile)
    axis_score = _score_taste_for_candidate_by_axes(candidate, profile, factor_scores)
    if axis_score > 0:
        return round(axis_score + (min(legacy_score, 1.5) * 0.2), 4)
    return legacy_score


def _compute_rising_score(candidate: dict) -> float:
    hit_indicator = max(_safe_int(candidate.get("count_hit_indicator"), 0), 0)
    bookmark_indicator = max(_safe_int(candidate.get("count_bookmark_indicator"), 0), 0)
    reading_rate_indicator = max(_safe_float(candidate.get("reading_rate_indicator"), 0.0), 0.0)
    rank_indicator = max(_safe_int(candidate.get("rank_indicator"), 0), 0)

    hit_score = _clamp(math.log10(hit_indicator + 1) / 3.0, 0.0, 1.0)
    bookmark_score = _clamp(math.log10(bookmark_indicator + 1) / 2.5, 0.0, 1.0)
    reading_score = _clamp(reading_rate_indicator / 0.12, 0.0, 1.0)
    rank_score = _clamp(rank_indicator / 20.0, 0.0, 1.0)

    return round(
        (hit_score * 0.35)
        + (bookmark_score * 0.25)
        + (reading_score * 0.25)
        + (rank_score * 0.15),
        4,
    )


def _compute_rank_exposure_penalty(candidate: dict) -> float:
    current_rank = _safe_int(candidate.get("current_rank"), 0)
    if current_rank <= 0:
        return 0.0
    if current_rank <= 10:
        return 0.9
    if current_rank <= 30:
        return 0.45
    if current_rank <= 100:
        return 0.15
    return 0.0


def _extract_context_anchor_product_id(context: dict | None) -> int | None:
    raw = context or {}
    current_product_id = _safe_int(raw.get("current_product_id"), 0)
    if current_product_id > 0:
        return current_product_id
    browsed_ids = _as_int_list(raw.get("browsed_product_ids"))
    return browsed_ids[-1] if browsed_ids else None


async def _get_preset_context_anchor(product_id: int, db: AsyncSession) -> dict | None:
    query = text(
        """
        SELECT
            p.product_id,
            p.title,
            m.protagonist_type,
            m.mood,
            m.pacing,
            m.taste_tags
        FROM tb_product p
        INNER JOIN tb_product_ai_metadata m ON m.product_id = p.product_id
        WHERE p.product_id = :product_id
          AND p.open_yn = 'Y'
          AND m.analysis_status = 'success'
          AND COALESCE(m.exclude_from_recommend_yn, 'N') = 'N'
        LIMIT 1
        """
    )
    result = await db.execute(query, {"product_id": product_id})
    row = result.mappings().first()
    return dict(row) if row else None


def _build_context_profile(anchor: dict | None) -> dict | None:
    if not anchor:
        return None

    profile: dict[str, Any] = {
        "preferred_protagonist": {},
        "preferred_mood": {},
        "preferred_themes": {},
        "taste_tags": _as_list(anchor.get("taste_tags")),
        "read_product_ids": [],
    }
    protagonist_type = str(anchor.get("protagonist_type") or "").strip()
    mood = str(anchor.get("mood") or "").strip()
    pacing = str(anchor.get("pacing") or "").strip()
    if protagonist_type:
        profile["preferred_protagonist"] = {protagonist_type: 1.0}
    if mood:
        profile["preferred_mood"] = {mood: 1.0}
    if pacing:
        profile["preferred_pacing"] = pacing

    return profile if has_profile_preference_signal(profile) else None


def _build_preset_reason_context(
    preset: str,
    profile: dict | None,
    anchor_title: str | None,
    selected: dict | None = None,
) -> str:
    base = PRESET_LABELS.get(preset, "")
    has_selected_taste_alignment = (
        _safe_float((selected or {}).get("_taste_score"), 0.0) > 0.0
        or _safe_float((selected or {}).get("_context_score"), 0.0) > 0.0
    )
    if has_profile_preference_signal(profile) and has_selected_taste_alignment:
        base = f"내 취향에 맞는 {base}"
    if anchor_title:
        return f"현재 보고 있던 '{anchor_title}'와 결이 이어지는 {base}".strip()
    return base


def _build_condition_first_factor_summary(candidates: list[dict]) -> str:
    if not candidates:
        return ""

    type_counter: Counter[str] = Counter()
    worldview_counter: Counter[str] = Counter()
    style_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()

    top_pool = sorted(
        candidates,
        key=lambda item: (
            _safe_float(item.get("_cohort_score"), 0.0),
            _safe_float(item.get("_preset_signal"), 0.0),
            _safe_float(item.get("_engagement_score"), 0.0),
            _safe_float(item.get("_rising_score"), 0.0),
            _safe_float(item.get("count_hit"), 0.0),
        ),
        reverse=True,
    )[:6]

    for candidate in top_pool:
        weight = (
            1.0
            + (_safe_float(candidate.get("_cohort_score"), 0.0) * 1.1)
            + _safe_float(candidate.get("_preset_signal"), 0.0)
            + (_safe_float(candidate.get("_engagement_score"), 0.0) * 0.8)
            + (_safe_float(candidate.get("_rising_score"), 0.0) * 0.5)
        )
        for label in _as_list(candidate.get("protagonist_type_tags"))[:3]:
            normalized = str(label or "").strip()
            if normalized:
                type_counter[normalized] += weight
        for label in _as_list(candidate.get("worldview_tags"))[:3]:
            normalized = str(label or "").strip()
            if normalized:
                worldview_counter[normalized] += weight
        for label in _as_list(candidate.get("axis_style_tags"))[:3]:
            normalized = str(label or "").strip()
            if normalized:
                style_counter[normalized] += weight
        for raw_tag in _as_list(candidate.get("taste_tags"))[:3]:
            tag = str(raw_tag or "").strip()
            if tag:
                tag_counter[tag] += weight * 0.75

    summary_parts: list[str] = []
    if type_counter:
        summary_parts.append(f"'{type_counter.most_common(1)[0][0]}' 주인공")
    if worldview_counter:
        summary_parts.append(f"'{worldview_counter.most_common(1)[0][0]}' 세계관")
    if style_counter:
        summary_parts.append(f"'{style_counter.most_common(1)[0][0]}' 작풍")
    if tag_counter:
        summary_parts.append(f"'{tag_counter.most_common(1)[0][0]}' 요소")
    return ", ".join(summary_parts[:3])


def _build_cohort_seed_labels(
    factor_scores: dict[str, dict[str, float]],
    profile: dict | None,
    *,
    limit: int = 8,
) -> dict[str, float]:
    if limit <= 0:
        return {}

    profile_map = profile if isinstance(profile, dict) else {}
    aggregated: dict[str, float] = {}
    for axis in AXIS_KEYS:
        axis_scores = _build_user_axis_label_scores(axis, factor_scores, profile_map)
        for label, score in axis_scores.items():
            normalized_label = _normalize_factor_key(label)
            normalized_score = _safe_float(score, 0.0)
            if not normalized_label or normalized_score <= 0:
                continue
            aggregated[normalized_label] = max(aggregated.get(normalized_label, 0.0), normalized_score)

    ranked_labels = sorted(aggregated.items(), key=lambda item: item[1], reverse=True)
    return dict(ranked_labels[:limit])


async def _get_condition_first_cohort_scores(
    *,
    user_id: int | None,
    factor_scores: dict[str, dict[str, float]],
    profile: dict | None,
    candidates: list[dict],
    db: AsyncSession,
) -> dict[int, float]:
    if not user_id or not candidates:
        return {}

    seed_labels = _build_cohort_seed_labels(factor_scores, profile)
    if not seed_labels:
        return {}

    similar_users_query = text(
        """
        SELECT user_id, LOWER(TRIM(factor_key)) AS factor_key, score
        FROM tb_user_taste_factor_score
        WHERE user_id <> :user_id
          AND score > 0
          AND LOWER(TRIM(factor_key)) IN :factor_keys
        """
    ).bindparams(bindparam("factor_keys", expanding=True))

    similar_rows = await db.execute(
        similar_users_query,
        {
            "user_id": user_id,
            "factor_keys": list(seed_labels.keys()),
        },
    )

    user_weights: dict[int, float] = {}
    for row in similar_rows.mappings().all():
        similar_user_id = int(row.get("user_id") or 0)
        factor_key = _normalize_factor_key(row.get("factor_key"))
        if similar_user_id <= 0 or not factor_key:
            continue
        base_weight = seed_labels.get(factor_key, 0.0)
        if base_weight <= 0:
            continue
        signal_weight = _clamp(_normalize_factor_score(_safe_float(row.get("score"), 0.0)) / 6.0, 0.0, 1.0)
        if signal_weight <= 0:
            continue
        user_weights[similar_user_id] = user_weights.get(similar_user_id, 0.0) + (base_weight * signal_weight)

    ranked_users = sorted(user_weights.items(), key=lambda item: item[1], reverse=True)[:COHORT_SIMILAR_USER_LIMIT]
    if not ranked_users:
        return {}

    similar_user_weights = {user_id: weight for user_id, weight in ranked_users if weight > 0}
    if not similar_user_weights:
        return {}

    candidate_product_ids = [
        int(candidate.get("product_id") or 0)
        for candidate in candidates
        if int(candidate.get("product_id") or 0) > 0
    ]
    if not candidate_product_ids:
        return {}

    signal_query = text(
        f"""
        SELECT product_id, user_id, event_type, COUNT(*) AS event_count
        FROM tb_user_ai_signal_event
        WHERE user_id IN :user_ids
          AND product_id IN :product_ids
          AND created_date >= DATE_SUB(NOW(), INTERVAL {COHORT_SIGNAL_LOOKBACK_DAYS} DAY)
          AND event_type IN :event_types
        GROUP BY product_id, user_id, event_type
        """
    ).bindparams(
        bindparam("user_ids", expanding=True),
        bindparam("product_ids", expanding=True),
        bindparam("event_types", expanding=True),
    )

    signal_rows = await db.execute(
        signal_query,
        {
            "user_ids": list(similar_user_weights.keys()),
            "product_ids": candidate_product_ids,
            "event_types": list(COHORT_SIGNAL_EVENT_WEIGHTS.keys()),
        },
    )

    total_user_weight = sum(similar_user_weights.values())
    if total_user_weight <= 0:
        return {}

    score_map: dict[int, float] = {}
    coverage_map: dict[int, float] = {}
    for row in signal_rows.mappings().all():
        product_id = int(row.get("product_id") or 0)
        similar_user_id = int(row.get("user_id") or 0)
        event_type = str(row.get("event_type") or "").strip().lower()
        event_count = max(int(row.get("event_count") or 0), 0)
        user_weight = similar_user_weights.get(similar_user_id, 0.0)
        event_weight = COHORT_SIGNAL_EVENT_WEIGHTS.get(event_type, 0.0)
        if product_id <= 0 or user_weight <= 0 or event_weight <= 0 or event_count <= 0:
            continue
        score_map[product_id] = score_map.get(product_id, 0.0) + (
            user_weight * event_weight * math.log1p(event_count)
        )
        coverage_map[product_id] = coverage_map.get(product_id, 0.0) + user_weight

    cohort_scores: dict[int, float] = {}
    for product_id, raw_score in score_map.items():
        normalized_score = raw_score / total_user_weight
        coverage_ratio = _clamp(coverage_map.get(product_id, 0.0) / total_user_weight, 0.0, 1.0)
        cohort_scores[product_id] = round((normalized_score * 0.8) + (coverage_ratio * 1.2), 4)

    return cohort_scores


def _build_condition_first_fallback_reason(
    preset: str,
    selected: dict,
    candidates: list[dict],
) -> str:
    preset_label = PRESET_LABELS.get(preset, "요청하신 조건")
    factor_summary = _build_condition_first_factor_summary(candidates)
    if factor_summary:
        return (
            f"{preset_label} 안에서 지금 취향과 정확히 겹치는 작품은 많지 않았어요. "
            f"대신 비슷한 독자들은 {factor_summary} 결의 작품에 더 반응하는 편이라, "
            f"'{selected.get('title', '')}'를 먼저 추천해요."
        )
    return (
        f"{preset_label} 안에서 지금 취향과 정확히 겹치는 작품은 많지 않았어요. "
        f"대신 비슷한 독자 반응과 연독 지표가 안정적인 '{selected.get('title', '')}'를 먼저 추천해요."
    )


def _build_relaxed_preset_reply(
    requested_preset: str,
    applied_preset: str,
    base_reason: str,
) -> str:
    requested_label = PRESET_LABELS.get(requested_preset, "요청하신 조건")
    applied_label = PRESET_LABELS.get(applied_preset, applied_preset)
    normalized_reason = str(base_reason or "").strip()
    prefix = (
        f"{requested_label} 조건으로 바로 맞는 작품이 적어서, "
        f"비슷한 독자들이 많이 반응하는 {applied_label} 방향으로 한 단계 넓혀 골랐어요."
    )
    if normalized_reason:
        return f"{prefix} {normalized_reason}"
    return prefix


async def _build_relaxed_preset_fallback_result(
    *,
    user_id: int | None,
    profile: dict | None,
    factor_scores: dict[str, dict[str, float]],
    requested_preset: str,
    exclude_ids: list[int],
    adult_yn: str,
    db: AsyncSession,
    context: dict | None,
) -> dict | None:
    for fallback_preset in PRESET_RELAXED_FALLBACKS.get(requested_preset, []):
        try:
            fallback_result = await _preset_recommend(
                user_id=user_id,
                profile=profile,
                factor_scores=factor_scores,
                preset=fallback_preset,
                exclude_ids=exclude_ids,
                adult_yn=adult_yn,
                db=db,
                context=context,
            )
        except CustomResponseException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                continue
            raise

        taste_match = fallback_result.get("taste_match") or fallback_result.get("tasteMatch") or {
            "protagonist": 0,
            "mood": 0,
            "pacing": 0,
        }
        reason = _build_relaxed_preset_reply(
            requested_preset=requested_preset,
            applied_preset=fallback_preset,
            base_reason=str(fallback_result.get("reason") or fallback_result.get("reply") or ""),
        )
        product = fallback_result.get("product")
        if isinstance(product, dict):
            product["matchReason"] = reason
        return {
            "reason": reason,
            "reply": reason,
            "product": product,
            "taste_match": taste_match,
            "tasteMatch": taste_match,
        }

    return None


async def _build_relaxed_preset_chat_fallback(
    *,
    kc_user_id: str,
    requested_preset: str,
    exclude_ids: list[int],
    adult_yn: str,
    db: AsyncSession,
    context: dict | None,
) -> dict:
    zero_taste = {"protagonist": 0, "mood": 0, "pacing": 0}
    user_id = await _get_user_id_by_kc(kc_user_id, db)
    profile = await get_user_taste_profile(user_id, db) if user_id else None
    factor_scores = await _get_user_factor_scores(user_id, db) if user_id else {}
    fallback_result = await _build_relaxed_preset_fallback_result(
        user_id=user_id,
        profile=profile,
        factor_scores=factor_scores,
        requested_preset=requested_preset,
        exclude_ids=exclude_ids,
        adult_yn=adult_yn,
        db=db,
        context=context,
    )
    if fallback_result:
        return {
            "reply": fallback_result.get("reply") or "",
            "product": fallback_result.get("product"),
            "taste_match": fallback_result.get("taste_match") or zero_taste,
            "tasteMatch": fallback_result.get("tasteMatch") or zero_taste,
        }

    requested_label = PRESET_LABELS.get(requested_preset, "요청하신 조건")
    suggestion_labels = [PRESET_LABELS.get(key, key) for key in PRESET_RELAXED_FALLBACKS.get(requested_preset, [])[:2]]
    suggestion_text = ", ".join(suggestion_labels) if suggestion_labels else "다른 추천 방향"
    reply = (
        f"{requested_label} 조건에서 바로 추천할 작품이 충분하지 않았어요. "
        f"대신 {suggestion_text} 쪽으로 넓히면 훨씬 자연스럽게 찾을 수 있어요."
    )
    return {
        "reply": reply,
        "product": None,
        "taste_match": zero_taste,
        "tasteMatch": zero_taste,
    }


def _build_preset_candidate_scores(
    candidate: dict,
    preset: str,
    profile: dict | None,
    factor_scores: dict[str, dict[str, float]] | None = None,
    context_profile: dict | None = None,
) -> dict[str, float]:
    engagement_score = score_engagement_for_recommendation(candidate)
    taste_score = score_taste_for_candidate(candidate, profile, factor_scores)
    context_score = score_taste_for_candidate(candidate, context_profile)
    rising_score = _compute_rising_score(candidate)
    exposure_penalty = _compute_rank_exposure_penalty(candidate)
    reading_rate = _clamp(_safe_float(candidate.get("reading_rate"), 0.0), 0.0, 1.0)
    schedule_score = _clamp(_safe_float(candidate.get("writing_count_per_week"), 0.0) / 4.0, 0.0, 1.0)
    popularity_score = _clamp(
        math.log10(int(_safe_float(candidate.get("count_hit"), 0.0)) + 1) / 6.0,
        0.0,
        1.0,
    )
    episode_score = _clamp(int(_safe_float(candidate.get("episode_count"), 0.0)) / 120.0, 0.0, 1.0)
    evaluation_score = _clamp(_safe_float(candidate.get("evaluation_score"), 0.0) / 10.0, 0.0, 1.0)

    if preset == "trending":
        preset_signal = (
            (reading_rate * 0.8)
            + (engagement_score * 0.7)
            + (rising_score * 1.2)
            + (popularity_score * 0.25)
        )
    elif preset == "good-schedule":
        preset_signal = (
            (schedule_score * 1.1)
            + (reading_rate * 0.4)
            + (engagement_score * 0.45)
            + (rising_score * 0.25)
        )
    elif preset == "completed":
        preset_signal = (
            (engagement_score * 0.85)
            + (reading_rate * 0.55)
            + (evaluation_score * 0.35)
            + (rising_score * 0.1)
            + (popularity_score * 0.15)
        )
    elif preset == "stacked-chapters":
        preset_signal = (
            (episode_score * 1.0)
            + (reading_rate * 0.45)
            + (engagement_score * 0.45)
            + (rising_score * 0.2)
        )
    else:
        preset_signal = popularity_score + (reading_rate * 0.5) + (engagement_score * 0.7)

    if _has_recommendation_taste_signal(profile, factor_scores):
        total_score = (
            (taste_score * 3.2)
            + (context_score * 0.85)
            + (preset_signal * 1.2)
            + (rising_score * 0.9)
            - exposure_penalty
        )
    elif has_profile_preference_signal(context_profile):
        total_score = (
            (context_score * 2.1)
            + (preset_signal * 1.45)
            + (rising_score * 1.0)
            + (popularity_score * 0.15)
            - exposure_penalty
        )
    else:
        total_score = (preset_signal * 1.7) + (rising_score * 1.1) + (popularity_score * 0.2) - exposure_penalty

    return {
        "total_score": round(total_score, 4),
        "engagement_score": engagement_score,
        "taste_score": taste_score,
        "context_score": context_score,
        "preset_signal": round(preset_signal, 4),
        "rising_score": rising_score,
        "pick_weight": round(
            max(total_score, 0.05) * (1.0 + (rising_score * 0.35) + (min(context_score, 4.0) * 0.08)),
            4,
        ),
    }


def _preset_selection_seed(user_id: int | None, preset: str, exclude_ids: list[int]) -> int:
    hour_kst = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d-%H")
    exclude_key = ",".join(str(pid) for pid in sorted(set(_as_int_list(exclude_ids))))
    base = f"{user_id or 0}:{preset}:{hour_kst}:{exclude_key}"
    return int(hashlib.sha256(base.encode("utf-8")).hexdigest()[:8], 16)


def _pick_weighted_candidate(
    candidates: list[dict],
    *,
    pool_size: int = PRESET_RANDOM_POOL_SIZE,
    seed: int | None = None,
) -> dict:
    if not candidates:
        raise ValueError("candidates must not be empty")

    pool = candidates[: max(1, min(pool_size, len(candidates)))]
    if len(pool) == 1:
        return pool[0]

    weights = [max(_safe_float(item.get("_pick_weight"), 0.0), 0.05) for item in pool]
    total_weight = sum(weights)
    if total_weight <= 0:
        return pool[0]

    normalized_seed = seed if seed is not None else int(datetime.now().timestamp())
    point = ((normalized_seed % 1_000_000) / 1_000_000.0) * total_weight
    cumulative = 0.0
    for item, weight in zip(pool, weights):
        cumulative += weight
        if point <= cumulative:
            return item
    return pool[-1]


async def _preset_recommend(
    user_id: int | None,
    profile: dict | None,
    factor_scores: dict[str, dict[str, float]],
    preset: str,
    exclude_ids: list[int],
    adult_yn: str,
    db: AsyncSession,
    context: dict | None = None,
) -> dict:
    """프리셋 추천: DB 필터 → 취향 매칭 → LLM 사유 생성."""
    anchor_product = None
    anchor_profile = None
    anchor_product_id = _extract_context_anchor_product_id(context)
    if anchor_product_id:
        anchor_product = await _get_preset_context_anchor(anchor_product_id, db)
        anchor_profile = _build_context_profile(anchor_product)

    # 작품 후보 조회
    filter_clause = PRESET_FILTERS.get(preset, "1=1")
    status_code_filter = PRESET_STATUS_FILTERS.get(preset)
    order_clause = PRESET_QUERY_ORDER_CLAUSES.get(preset, "p.count_hit DESC")

    adult_filter = "AND p.ratings_code = 'all'" if adult_yn == "N" else ""
    status_filter_sql = "AND p.status_code = :status_code_filter" if status_code_filter else ""
    query = text(f"""
        SELECT
            p.product_id, p.title, p.status_code, p.price_type,
            p.monopoly_yn, p.contract_yn, p.last_episode_date, p.count_hit,
            IF(p.last_episode_date >= DATE_SUB(NOW(), INTERVAL 24 HOUR), 'Y', 'N') AS new_release_yn,
            p.author_name AS author_nickname,
            (SELECT COUNT(*) FROM tb_product_episode e
             WHERE e.product_id = p.product_id AND e.use_yn = 'Y') AS episode_count,
            IF(p.thumbnail_file_id IS NULL, NULL,
               (SELECT CASE
                         WHEN w.file_path IS NULL OR w.file_path = '' THEN NULL
                         WHEN w.file_path LIKE 'http://%' OR w.file_path LIKE 'https://%' THEN w.file_path
                         ELSE CONCAT(:cdn, '/', w.file_path)
                       END
                FROM tb_common_file q, tb_common_file_item w
                WHERE q.file_group_id = w.file_group_id
                  AND q.use_yn = 'Y' AND w.use_yn = 'Y'
                  AND q.group_type = 'cover'
                  AND q.file_group_id = p.thumbnail_file_id)) AS cover_url,
            m.protagonist_type, m.protagonist_desc, m.mood, m.pacing,
            m.premise, m.hook, m.themes, m.taste_tags,
            m.overall_confidence,
            m.protagonist_goal_primary, m.goal_confidence,
            m.protagonist_type_tags, m.protagonist_job_tags,
            m.protagonist_material_tags, m.worldview_tags,
            m.axis_style_tags, m.axis_romance_tags,
            m.romance_chemistry_weight,
            COALESCE(pti.reading_rate, 0) AS reading_rate,
            COALESCE(pti.writing_count_per_week, 0) AS writing_count_per_week,
            COALESCE(pem.binge_rate, 0) AS binge_rate,
            COALESCE(pem.total_next_clicks, 0) AS total_next_clicks,
            COALESCE(pem.total_readers, 0) AS total_readers,
            COALESCE(pem.dropoff_7d, 0) AS dropoff_7d,
            COALESCE(pem.reengage_rate, 0) AS reengage_rate,
            pem.avg_speed_cpm AS avg_speed_cpm,
            ev.evaluation_score,
            COALESCE(pcv.count_hit_indicator, 0) AS count_hit_indicator,
            COALESCE(pcv.count_bookmark_indicator, 0) AS count_bookmark_indicator,
            COALESCE(pcv.reading_rate_indicator, 0) AS reading_rate_indicator,
            pr.current_rank,
            CASE
                WHEN pr.current_rank IS NOT NULL AND pr.privious_rank IS NOT NULL
                THEN (pr.privious_rank - pr.current_rank)
                ELSE 0
            END AS rank_indicator,
            IF(wff.product_id IS NOT NULL, 'Y', 'N') AS waiting_for_free_yn,
            IF(p69.product_id IS NOT NULL, 'Y', 'N') AS six_nine_path_yn
        FROM tb_product p
        JOIN tb_product_ai_metadata m ON m.product_id = p.product_id
        LEFT JOIN tb_product_trend_index pti ON pti.product_id = p.product_id
        {LATEST_ENGAGEMENT_JOIN_SQL}
        LEFT JOIN tb_cms_product_evaluation ev ON ev.product_id = p.product_id
        LEFT JOIN tb_product_count_variance pcv ON pcv.product_id = p.product_id
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
        WHERE p.open_yn = 'Y'
          AND m.analysis_status = 'success'
          AND COALESCE(m.exclude_from_recommend_yn, 'N') = 'N'
          {adult_filter}
          AND {filter_clause}
          {status_filter_sql}
        ORDER BY {order_clause}
        LIMIT {PRESET_CANDIDATE_FETCH_LIMIT}
    """)
    query_params: dict[str, Any] = {"cdn": settings.R2_SC_CDN_URL}
    if status_code_filter:
        query_params["status_code_filter"] = status_code_filter
    result = await db.execute(query, query_params)
    candidates = [_metadata_row_to_dict(r) for r in result.mappings().all()]

    if not candidates:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="조건에 맞는 작품을 찾지 못했습니다.",
        )

    # 읽은 작품 + 제외 목록 필터
    exclude_set = set(exclude_ids)
    if anchor_product_id:
        exclude_set.add(anchor_product_id)
    if profile:
        exclude_set.update(profile.get("read_product_ids") or [])
    candidates = [c for c in candidates if c["product_id"] not in exclude_set]

    if not candidates:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="추천할 새로운 작품이 없습니다.",
        )

    for candidate in candidates:
        score_info = _build_preset_candidate_scores(
            candidate,
            preset,
            profile,
            factor_scores=factor_scores,
            context_profile=anchor_profile,
        )
        candidate["_score"] = score_info["total_score"]
        candidate["_engagement_score"] = score_info["engagement_score"]
        candidate["_taste_score"] = score_info["taste_score"]
        candidate["_context_score"] = score_info["context_score"]
        candidate["_preset_signal"] = score_info["preset_signal"]
        candidate["_rising_score"] = score_info["rising_score"]
        candidate["_cohort_score"] = 0.0
        candidate["_pick_weight"] = score_info["pick_weight"]
    candidates.sort(
        key=lambda x: (
            x.get("_score", 0),
            x.get("_taste_score", 0),
            x.get("_context_score", 0),
            x.get("_rising_score", 0),
            x.get("_engagement_score", 0),
            int(_safe_float(x.get("count_hit"), 0.0)),
        ),
        reverse=True,
    )

    use_condition_first_fallback = False
    if _has_recommendation_taste_signal(profile, factor_scores):
        has_preference_aligned_candidate = any(
            (_safe_float(candidate.get("_taste_score"), 0.0) > 0.0)
            or (_safe_float(candidate.get("_context_score"), 0.0) > 0.0)
            for candidate in candidates
        )
        use_condition_first_fallback = not has_preference_aligned_candidate

    if use_condition_first_fallback:
        cohort_scores = await _get_condition_first_cohort_scores(
            user_id=user_id,
            factor_scores=factor_scores,
            profile=profile,
            candidates=candidates,
            db=db,
        )
        for candidate in candidates:
            candidate["_cohort_score"] = _safe_float(
                cohort_scores.get(int(candidate.get("product_id") or 0), 0.0),
                0.0,
            )
        candidates.sort(
            key=lambda x: (
                x.get("_cohort_score", 0),
                x.get("_preset_signal", 0),
                x.get("_engagement_score", 0),
                x.get("_rising_score", 0),
                _safe_float(x.get("count_hit"), 0.0),
            ),
            reverse=True,
        )
        for candidate in candidates:
            candidate["_pick_weight"] = round(
                max(
                    (
                        (_safe_float(candidate.get("_cohort_score"), 0.0) * 1.6)
                        + (_safe_float(candidate.get("_preset_signal"), 0.0) * 1.0)
                        + (_safe_float(candidate.get("_engagement_score"), 0.0) * 0.7)
                        + (_safe_float(candidate.get("_rising_score"), 0.0) * 0.3)
                    ),
                    0.05,
                ),
                4,
            )

    selected = _pick_weighted_candidate(
        candidates,
        seed=_preset_selection_seed(user_id, preset, exclude_ids),
    )

    if use_condition_first_fallback:
        reason = _build_condition_first_fallback_reason(preset, selected, candidates)
    else:
        # LLM으로 추천 사유 생성
        reason_context = _build_preset_reason_context(
            preset,
            profile,
            str((anchor_product or {}).get("title") or "").strip() or None,
            selected,
        )
        reason = await _generate_reason(selected, profile, reason_context)

    taste_match = _compute_taste_match(selected, profile)

    taste_tags_raw = selected.get("taste_tags")
    if isinstance(taste_tags_raw, str):
        try:
            taste_tags_list = json.loads(taste_tags_raw)
            taste_tags_list = taste_tags_list if isinstance(taste_tags_list, list) else []
        except (json.JSONDecodeError, TypeError):
            taste_tags_list = []
    elif isinstance(taste_tags_raw, list):
        taste_tags_list = taste_tags_raw
    else:
        taste_tags_list = []

    return {
        "product": {
            "productId": selected["product_id"],
            "title": selected["title"],
            "coverUrl": selected.get("cover_url"),
            "authorNickname": selected.get("author_nickname"),
            "episodeCount": selected.get("episode_count", 0),
            "matchReason": reason,
            "tasteTags": [str(t) for t in taste_tags_list[:5] if t],
            "serialCycle": _format_serial_cycle(
                _safe_float(selected.get("writing_count_per_week"), 0.0),
                str(selected.get("status_code") or ""),
            ),
            "priceType": selected.get("price_type"),
            "ongoingState": selected.get("status_code"),
            "monopolyYn": selected.get("monopoly_yn"),
            "lastEpisodeDate": str(selected["last_episode_date"]) if selected.get("last_episode_date") else None,
            "newReleaseYn": selected.get("new_release_yn", "N"),
            "cpContractYn": selected.get("contract_yn", "N"),
            "waitingForFreeYn": selected.get("waiting_for_free_yn", "N"),
            "sixNinePathYn": selected.get("six_nine_path_yn", "N"),
        },
        "reason": reason,
        "tasteMatch": taste_match,
        "taste_match": taste_match,
    }


async def _freeform_recommend(
    profile: dict | None,
    query_text: str,
    exclude_ids: list[int],
    adult_yn: str,
    db: AsyncSession,
) -> dict:
    """자유 입력 추천: 전체 작품 DNA + 취향 → LLM 판단."""
    all_dna = await get_all_product_ai_metadata(db, adult_yn=adult_yn)
    if not all_dna:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="작품 데이터가 없습니다.",
        )

    exclude_set = set(exclude_ids)
    if profile:
        exclude_set.update(profile.get("read_product_ids") or [])

    # LLM에 전달할 작품 목록 축약
    products_for_llm = []
    candidate_dna_by_id: dict[int, dict] = {}
    for dna in all_dna:
        if dna["product_id"] in exclude_set:
            continue
        candidate_dna_by_id[dna["product_id"]] = dna
        products_for_llm.append({
            "id": dna["product_id"],
            "title": dna.get("title", ""),
            "protagonist": dna.get("protagonist_type", ""),
            "mood": dna.get("mood", ""),
            "premise": dna.get("premise", ""),
            "themes": dna.get("themes", []),
            "taste_tags": dna.get("taste_tags", []),
        })
    if not products_for_llm:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="추천 가능한 작품이 없습니다.",
        )

    profile_summary = ""
    if profile:
        profile_summary = f"""선호 주인공: {json.dumps(profile.get('preferred_protagonist', {}), ensure_ascii=False)}
선호 분위기: {json.dumps(profile.get('preferred_mood', {}), ensure_ascii=False)}
선호 테마: {json.dumps(profile.get('preferred_themes', {}), ensure_ascii=False)}
취향 요약: {profile.get('taste_summary', '')}"""

    system_prompt = """당신은 웹소설 추천 전문가입니다.
규칙:
- 반드시 작품 목록 중에서만 1개 선택
- 독자의 취향과 질문 조건을 모두 만족하는 작품
- 응답 형식: {"product_id": N, "reason": "2~3문장 추천 사유"}
- 추천 사유는 자신감 있게, 짧게, 독자가 기대하게 작성"""

    user_prompt = f"""[독자 취향]
{profile_summary if profile_summary else '(비로그인 독자)'}

[작품 목록]
{json.dumps(products_for_llm, ensure_ascii=False)}

[질문]
"{query_text}"
"""

    try:
        raw = await _call_claude(system_prompt, user_prompt)
        parsed = _parse_json_from_llm(raw)
        selected_id_raw = parsed.get("product_id")
        reason = parsed.get("reason", "")
        if not isinstance(reason, str):
            reason = str(reason)
        reason = reason.strip()
        try:
            selected_id = int(selected_id_raw)
        except (TypeError, ValueError):
            selected_id = None
    except Exception as e:
        error_logger.error(f"Freeform recommend LLM failed: {e}")
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message="AI 추천 생성에 실패했습니다.",
        )

    if selected_id is None or selected_id not in candidate_dna_by_id:
        logger.warning(
            "[FREEFORM_INVALID_PRODUCT] selected_id=%s candidate_count=%s",
            selected_id_raw,
            len(candidate_dna_by_id),
        )
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="추천할 작품을 찾지 못했습니다.",
        )

    product_info = await _get_product_brief(selected_id, db)
    if not product_info:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="작품 정보를 찾을 수 없습니다.",
        )

    # 해당 작품의 DNA 찾기
    selected_dna = candidate_dna_by_id.get(selected_id, {})
    taste_match = _compute_taste_match(selected_dna, profile)

    return {
        "product": {
            "productId": product_info["product_id"],
            "title": product_info["title"],
            "coverUrl": product_info.get("cover_url"),
            "authorNickname": product_info.get("author_nickname"),
            "episodeCount": product_info.get("episode_count", 0),
            "matchReason": reason,
        },
        "reason": reason,
        "tasteMatch": taste_match,
        "taste_match": taste_match,
    }


async def _generate_reason(product: dict, profile: dict | None, context: str) -> str:
    """선택된 작품 + 유저 취향 → 추천 사유 한줄 생성."""
    system_prompt = (
        "당신은 웹소설 추천 전문가입니다. "
        "추천 사유를 토스증권 스타일로 자신감 있게 2~3문장으로 작성하세요. "
        "JSON 없이 순수 텍스트로만 응답하세요."
    )
    taste_info = ""
    if profile:
        taste_info = f"독자 취향: {profile.get('taste_summary', '')}"

    user_prompt = f"""작품: {product.get('title', '')}
주인공: {product.get('protagonist_type', '')} - {product.get('protagonist_desc', '')}
분위기: {product.get('mood', '')}
소재: {product.get('premise', '')}
연재 상태: {product.get('status_code', '')} / {product.get('episode_count', 0)}화
추천 맥락: {context}
{taste_info}

위 정보로 독자에게 이 작품을 추천하는 사유를 작성하세요."""

    try:
        return await _call_claude(system_prompt, user_prompt)
    except Exception:
        return product.get("premise") or product.get("protagonist_desc") or "추천 작품입니다."


def _compute_taste_match(product_dna: dict, profile: dict | None) -> dict:
    """취향 매칭도 계산 (0~1)."""
    if not profile:
        return {"protagonist": 0, "mood": 0, "pacing": 0}

    # 주인공 매칭
    prot_score = 0.0
    pref_prot = _profile_count_map_to_scores(profile.get("preferred_protagonist") or {})
    if product_dna.get("protagonist_type") and product_dna["protagonist_type"] in pref_prot:
        prot_score = round(_safe_float(pref_prot.get(product_dna["protagonist_type"]), 0.0), 2)

    # 분위기 매칭
    mood_score = 0.0
    pref_mood = _profile_count_map_to_scores(profile.get("preferred_mood") or {})
    if product_dna.get("mood") and product_dna["mood"] in pref_mood:
        mood_score = round(_safe_float(pref_mood.get(product_dna["mood"]), 0.0), 2)

    # 페이싱 매칭
    pacing_score = 0.0
    if product_dna.get("pacing") and product_dna["pacing"] == profile.get("preferred_pacing"):
        pacing_score = 1.0

    return {"protagonist": prot_score, "mood": mood_score, "pacing": pacing_score}


# ──────────────────────────────────────────────────────────
#  온보딩 유명작 목록
# ──────────────────────────────────────────────────────────

async def get_onboarding_tag_tabs(
    db: AsyncSession,
    adult_yn: str | None = "N",
    onboarding_only: bool = False,
) -> list[dict]:
    adult_condition = ""
    if adult_yn is not None:
        normalized_adult = (adult_yn or "N").upper()
        if normalized_adult not in {"Y", "N"}:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="adult_yn은 Y/N 값만 허용됩니다.",
            )
        adult_condition = "p.ratings_code = 'all'" if normalized_adult == "N" else ""

    onboarding_join = (
        "INNER JOIN tb_ai_onboarding_product o ON o.product_id = m.product_id AND o.use_yn = 'Y'"
        if onboarding_only
        else ""
    )

    where_clauses = ["m.analysis_status = 'success'"]
    if onboarding_only:
        where_clauses.append("p.open_yn = 'Y'")
        where_clauses.append("COALESCE(m.exclude_from_recommend_yn, 'N') = 'N'")
    if adult_condition:
        where_clauses.append(adult_condition)
    where_clause_sql = " AND ".join(where_clauses)

    query = text(
        f"""
        SELECT
            m.product_id,
            m.protagonist_goal_primary,
            m.protagonist_type_tags,
            m.protagonist_job_tags,
            m.protagonist_material_tags,
            m.worldview_tags,
            m.axis_style_tags,
            m.axis_romance_tags
        FROM tb_product_ai_metadata m
        INNER JOIN tb_product p ON p.product_id = m.product_id
        {onboarding_join}
        WHERE {where_clause_sql}
        """
    )
    result = await db.execute(query)
    rows = [_metadata_row_to_dict(row) for row in result.mappings().all()]

    hero_counter: Counter[str] = Counter()
    world_tone_counter: Counter[str] = Counter()
    relation_counter: Counter[str] = Counter()

    for row in rows:
        hero_tags = _unique_nonempty_labels(
            [
                normalized
                for normalized in (
                    _normalize_allowed_axis_label("type", tag)
                    for tag in _as_list(row.get("protagonist_type_tags"))
                )
                if normalized
            ]
            + [
                normalized
                for normalized in (
                    _normalize_allowed_axis_label("job", tag)
                    for tag in _as_list(row.get("protagonist_job_tags"))
                )
                if normalized
            ]
            + [
                normalized
                for normalized in (
                    _normalize_allowed_axis_label("material", tag)
                    for tag in _as_list(row.get("protagonist_material_tags"))
                )
                if normalized
            ]
            + [
                normalized
                for normalized in (
                    _normalize_allowed_axis_label("goal", tag)
                    for tag in [row.get("protagonist_goal_primary")]
                )
                if normalized
            ]
        )
        world_tone_tags = _unique_nonempty_labels(
            [
                normalized
                for normalized in (
                    _normalize_allowed_axis_label("worldview", tag)
                    for tag in _as_list(row.get("worldview_tags"))
                )
                if normalized
            ]
            + [
                normalized
                for normalized in (
                    _normalize_allowed_axis_label("style", tag)
                    for tag in _as_list(row.get("axis_style_tags"))
                )
                if normalized
            ]
        )
        relation_tags = _unique_nonempty_labels(
            [
                normalized
                for normalized in (
                    _normalize_allowed_axis_label("romance", tag)
                    for tag in _as_list(row.get("axis_romance_tags"))
                )
                if normalized
            ]
        )

        hero_counter.update(hero_tags)
        world_tone_counter.update(world_tone_tags)
        relation_counter.update(relation_tags)

    def _to_sorted_tag_items(counter: Counter[str], limit: int) -> list[dict]:
        return [
            {"tag": tag, "count": int(count)}
            for tag, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]
        ]

    return [
        {"key": "hero", "label": ONBOARDING_TAG_TAB_LABELS["hero"], "tags": _to_sorted_tag_items(hero_counter, 30)},
        {
            "key": "worldTone",
            "label": ONBOARDING_TAG_TAB_LABELS["worldTone"],
            "tags": _to_sorted_tag_items(world_tone_counter, 30),
        },
        {
            "key": "relation",
            "label": ONBOARDING_TAG_TAB_LABELS["relation"],
            "tags": _to_sorted_tag_items(relation_counter, 24),
        },
    ]


def _slice_default_onboarding_tag_tabs(tag_tabs: list[dict], default_top_n: int = 10) -> list[dict]:
    default_tabs: list[dict] = []
    for key, label, _ in ONBOARDING_TAG_TAB_CONFIG:
        tab = next((item for item in tag_tabs if item.get("key") == key), None)
        all_tags = tab.get("tags", []) if tab else []
        default_tabs.append(
            {
                "key": key,
                "label": label,
                "tags": all_tags[:default_top_n],
            }
        )
    return default_tabs


async def get_curated_onboarding_tag_tabs(
    db: AsyncSession,
    adult_yn: str | None = "N",
    default_top_n: int = 10,
) -> list[dict]:
    all_tabs = await get_onboarding_tag_tabs(db, adult_yn=adult_yn, onboarding_only=False)
    all_tab_map = {tab["key"]: tab for tab in all_tabs}
    tag_count_map_by_tab = {
        tab["key"]: {item["tag"]: int(item.get("count", 0)) for item in tab.get("tags", [])}
        for tab in all_tabs
    }

    selected_rows = await db.execute(
        text(
            """
            SELECT tab_key, tag_name, sort_order
            FROM tb_ai_onboarding_tag
            WHERE use_yn = 'Y'
            ORDER BY tab_key ASC, sort_order ASC, id ASC
            """
        )
    )
    selected_map: dict[str, list[str]] = {key: [] for key, _, _ in ONBOARDING_TAG_TAB_CONFIG}
    selected_seen: dict[str, set[str]] = {key: set() for key, _, _ in ONBOARDING_TAG_TAB_CONFIG}
    for row in selected_rows.mappings().all():
        tab_key = str(row.get("tab_key") or "").strip()
        tag_name = str(row.get("tag_name") or "").strip()
        if tab_key not in ONBOARDING_TAG_TAB_KEYS or not tag_name:
            continue
        if tag_name in selected_seen[tab_key]:
            continue
        selected_seen[tab_key].add(tag_name)
        selected_map[tab_key].append(tag_name)

    has_any_selected = any(len(tags) > 0 for tags in selected_map.values())
    if not has_any_selected:
        return _slice_default_onboarding_tag_tabs(all_tabs, default_top_n=default_top_n)

    curated_tabs: list[dict] = []
    for key, default_label, _ in ONBOARDING_TAG_TAB_CONFIG:
        label = all_tab_map.get(key, {}).get("label", default_label)
        selected_tags = selected_map.get(key, [])
        if not selected_tags:
            curated_tabs.append(
                {
                    "key": key,
                    "label": label,
                    "tags": [],
                }
            )
            continue

        count_map = tag_count_map_by_tab.get(key, {})
        curated_tabs.append(
            {
                "key": key,
                "label": label,
                "tags": [{"tag": tag, "count": int(count_map.get(tag, 0))} for tag in selected_tags],
            }
        )

    return curated_tabs


async def get_onboarding_products(db: AsyncSession, adult_yn: str = "N") -> list[dict]:
    """온보딩에 표시할 작품 목록. CMS 수동 설정 순서로 노출."""
    adult_yn = (adult_yn or "N").upper()
    if adult_yn not in {"Y", "N"}:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="adult_yn은 Y/N 값만 허용됩니다.",
        )
    adult_filter = "AND p.ratings_code = 'all'" if adult_yn == "N" else ""

    query = text("""
        SELECT
            p.product_id, p.title, p.author_name, p.count_hit,
            IF(p.thumbnail_file_id IS NULL, NULL,
               (SELECT CASE
                         WHEN w.file_path IS NULL OR w.file_path = '' THEN NULL
                         WHEN w.file_path LIKE 'http://%' OR w.file_path LIKE 'https://%' THEN w.file_path
                         ELSE CONCAT(:cdn, '/', w.file_path)
                       END
                FROM tb_common_file q, tb_common_file_item w
                WHERE q.file_group_id = w.file_group_id
                  AND q.use_yn = 'Y' AND w.use_yn = 'Y'
                  AND q.group_type = 'cover'
                  AND q.file_group_id = p.thumbnail_file_id)) AS cover_url,
            m.protagonist_type,
            m.protagonist_type_tags,
            m.protagonist_job_tags,
            m.protagonist_material_tags,
            m.protagonist_goal_primary,
            m.mood,
            m.worldview_tags,
            m.axis_style_tags,
            m.axis_romance_tags,
            m.taste_tags
        FROM tb_ai_onboarding_product o
        INNER JOIN tb_product p ON p.product_id = o.product_id
        LEFT JOIN tb_product_ai_metadata m ON m.product_id = p.product_id
        WHERE o.use_yn = 'Y'
          AND p.open_yn = 'Y'
          {adult_filter}
        ORDER BY o.sort_order ASC, o.id ASC
        LIMIT 15
    """.format(adult_filter=adult_filter))
    result = await db.execute(query, {"cdn": settings.R2_SC_CDN_URL})
    return [dict(r) for r in result.mappings().all()]


# ──────────────────────────────────────────────────────────
#  마이페이지 취향 대시보드
# ──────────────────────────────────────────────────────────

async def get_taste_dashboard(kc_user_id: str, db: AsyncSession) -> dict:
    user_id = await _get_user_id_by_kc(kc_user_id, db)
    if not user_id:
        return {"has_profile": False}

    profile = await get_user_taste_profile(user_id, db)
    factor_scores = await _get_user_factor_scores(user_id, db)
    has_positive_signal = _has_positive_factor_signal(factor_scores)
    profile_source = "onboarding"

    if not profile:
        profile = await _build_profile_from_recent_reads(user_id, "N", db)
        if profile:
            profile_source = "recent_reads"

    if not profile and not has_positive_signal:
        return {"has_profile": False}

    if not profile:
        profile = {
            "preferred_protagonist": {},
            "preferred_mood": {},
            "preferred_themes": {},
            "taste_tags": [],
            "read_product_ids": [],
            "recommendation_sections": [],
            "taste_summary": "",
        }
        profile_source = "signal_only"

    axis_order = ("worldview", "job", "material", "romance", "style", "type", "goal")
    axis_tags: dict[str, list[str]] = {}
    axis_top3: dict[str, list[dict]] = {}
    axis_insights: dict[str, str] = {}
    axis_strengths: list[tuple[str, float]] = []
    for axis in axis_order:
        top_entries, strength = _build_axis_top3_entries(axis, factor_scores, profile, top_n=3)
        top_labels = [str(entry.get("label") or "").strip() for entry in top_entries if entry.get("label")]
        axis_tags[axis] = top_labels
        axis_top3[axis] = top_entries
        axis_insights[axis] = _build_axis_insight(axis, top_entries)
        axis_strengths.append((axis, strength))

    # 선호 주인공 TOP 3
    prot_raw = profile.get("preferred_protagonist") or {}
    prot_items: list[tuple[str, float]] = []
    if isinstance(prot_raw, dict):
        for key, value in prot_raw.items():
            normalized_key = _normalize_factor_key(key)
            if not normalized_key:
                continue
            prot_items.append((str(key), _safe_float(value, 0.0)))
    top_protagonists = sorted(prot_items, key=lambda x: x[1], reverse=True)[:3]

    taste_summary = _build_compact_taste_summary(axis_top3)
    if not taste_summary:
        strongest_axes = [
            axis for axis, score in sorted(axis_strengths, key=lambda item: item[1], reverse=True) if score > 0
        ][:2]
        insight_lines = [axis_insights.get(axis, "") for axis in strongest_axes if axis_insights.get(axis)]
        if insight_lines:
            taste_summary = " ".join(insight_lines)

    return {
        "has_profile": True,
        "profile_source": profile_source,
        "taste_summary": taste_summary,
        "top_protagonists": [{"type": k, "count": v} for k, v in top_protagonists],
        "preferred_mood": profile.get("preferred_mood", {}),
        "preferred_themes": profile.get("preferred_themes", {}),
        "preferred_pacing": profile.get("preferred_pacing"),
        "taste_tags": profile.get("taste_tags", []),
        "axis_tags": axis_tags,
        "axis_top3": axis_top3,
        "axis_insights": axis_insights,
        "axis_labels": {axis: AXIS_DISPLAY_LABEL.get(axis, axis) for axis in axis_order},
    }
