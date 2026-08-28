"""홈 급상승 구좌(AI 사서 코멘트형) 후보 조회.

무료연재 Top 랭킹에서 상위 10위 밖 작품 중 최근 상승 신호가 있는 작품을 고른다.
상승 수치는 공개하지 않고 유형별 코멘트 문구로만 표현한다.
"""

from copy import deepcopy
from datetime import datetime
from time import time
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


RISING_PICK_AREA_CODE = "freeSerialTop"
RISING_PICK_EXCLUDE_TOP_RANK = 10
RISING_PICK_MIN_RECENT_HITS = 5
RISING_PICK_MIN_RANK_GAIN = 3
RISING_PICK_DISPLAY_COUNT = 3
RISING_PICK_CANDIDATE_LIMIT = 12
RISING_PICK_ROTATE_HOURS = 3
RISING_PICK_CACHE_TTL_SECONDS = 300
RISING_PICK_REFRESH_AFTER_SECONDS = 300

_KST = ZoneInfo("Asia/Seoul")
_RISING_PICK_CACHE: dict[str, dict[str, Any]] = {}

NEW_WORK_MAX_AGE_DAYS = 7
COMEBACK_MIN_AGE_DAYS = 30
COMEBACK_MIN_QUIET_HOURS = 72

_COMMENT_TEMPLATES = {
    "new_work": "막 올라왔는데 눈에 띄기 시작했어요",
    "comeback": "요즘 다시 찾는 분들이 늘고 있어요",
    "fresh_episode": "새 회차 뒤로 반응이 이어지고 있어요",
    "rising": "요즘 조용히 오르고 있는 작품이에요",
}


def _normalize_adult_yn(adult_yn: str | None) -> str:
    return "Y" if (adult_yn or "").upper() == "Y" else "N"


def _visibility_filter(adult_yn: str | None) -> str:
    clauses = [
        "p.open_yn = 'Y'",
        "COALESCE(p.blind_yn, 'N') = 'N'",
        "p.price_type = 'free'",
        "p.status_code = 'ongoing'",
    ]
    if _normalize_adult_yn(adult_yn) != "Y":
        clauses.append("p.ratings_code = 'all'")
    return "\n          AND ".join(clauses)


def build_rising_pick_query(adult_yn: str | None) -> tuple[str, dict[str, Any]]:
    """상위 10위 밖에서 24시간 전 대비 상승했거나 새로 진입한 작품을 조회한다."""
    query = f"""
        SELECT
            cur.product_id AS productId,
            p.title,
            p.author_name AS authorName,
            cover.file_path AS coverImagePath,
            DATEDIFF(cur.basis_at, p.created_date) AS productAgeDays,
            TIMESTAMPDIFF(HOUR, latest_episode.latest_open_at, cur.basis_at) AS hoursSinceEpisode,
            (prev.rank_no - cur.rank_no) AS rankGain,
            cur.recent_24h_count_hit AS recentHits
        FROM tb_product_rank_snapshot_hourly cur
        INNER JOIN tb_product p ON p.product_id = cur.product_id
        LEFT JOIN tb_product_rank_snapshot_hourly prev
               ON prev.area_code = cur.area_code
              AND prev.product_id = cur.product_id
              AND prev.basis_at = DATE_SUB(cur.basis_at, INTERVAL 24 HOUR)
        LEFT JOIN (
            SELECT file_group_id, MIN(file_path) AS file_path
            FROM tb_common_file_item
            WHERE use_yn = 'Y'
            GROUP BY file_group_id
        ) cover ON cover.file_group_id = p.thumbnail_file_id
        LEFT JOIN (
            SELECT product_id,
                   MAX(COALESCE(publish_reserve_date, open_changed_date, created_date)) AS latest_open_at
            FROM tb_product_episode
            WHERE open_yn = 'Y' AND use_yn = 'Y'
            GROUP BY product_id
        ) latest_episode ON latest_episode.product_id = cur.product_id
        WHERE cur.area_code = :area_code
          AND cur.basis_at = (
              SELECT MAX(basis_at)
              FROM tb_product_rank_snapshot_hourly
              WHERE area_code = :area_code
          )
          AND cur.rank_no > :exclude_top_rank
          AND cur.recent_24h_count_hit >= :min_recent_hits
          AND (
              (prev.rank_no - cur.rank_no) >= :min_rank_gain
              OR prev.product_id IS NULL
          )
          AND {_visibility_filter(adult_yn)}
        ORDER BY (prev.rank_no - cur.rank_no) DESC, cur.recent_24h_count_hit DESC, cur.product_id DESC
        LIMIT :candidate_limit
    """
    return query, {
        "area_code": RISING_PICK_AREA_CODE,
        "exclude_top_rank": RISING_PICK_EXCLUDE_TOP_RANK,
        "min_recent_hits": RISING_PICK_MIN_RECENT_HITS,
        "min_rank_gain": RISING_PICK_MIN_RANK_GAIN,
        "candidate_limit": RISING_PICK_CANDIDATE_LIMIT,
    }


def classify_rising_type(
    product_age_days: int | None,
    hours_since_episode: int | None,
) -> str:
    """작품 나이와 최근 회차 업로드 시점으로 코멘트 유형을 정한다."""
    if product_age_days is not None and product_age_days <= NEW_WORK_MAX_AGE_DAYS:
        return "new_work"
    if (
        product_age_days is not None
        and product_age_days > COMEBACK_MIN_AGE_DAYS
        and (hours_since_episode is None or hours_since_episode >= COMEBACK_MIN_QUIET_HOURS)
    ):
        return "comeback"
    if hours_since_episode is not None and hours_since_episode < 24:
        return "fresh_episode"
    return "rising"


def get_rotation_bucket(now: datetime) -> int:
    """KST 기준 3시간 단위 회전 버킷. 같은 버킷 안에서는 순서가 고정된다."""
    day_ordinal = now.toordinal()
    return day_ordinal * (24 // RISING_PICK_ROTATE_HOURS) + (now.hour // RISING_PICK_ROTATE_HOURS)


def _shuffle_seed(bucket: int, product_id: int) -> int:
    return (bucket * 2654435761 + product_id * 40503) % 1000003


def select_rising_picks(
    rows: list[Mapping[str, Any]], now: datetime
) -> list[dict[str, Any]]:
    """후보를 버킷 기준으로 섞어 노출 개수만큼 고른다. 부족하면 빈 목록을 준다."""
    if len(rows) < RISING_PICK_DISPLAY_COUNT:
        return []

    bucket = get_rotation_bucket(now)
    ordered = sorted(
        rows,
        key=lambda row: _shuffle_seed(bucket, int(row["productId"])),
    )

    picks: list[dict[str, Any]] = []
    for row in ordered[:RISING_PICK_DISPLAY_COUNT]:
        rising_type = classify_rising_type(
            product_age_days=row.get("productAgeDays"),
            hours_since_episode=row.get("hoursSinceEpisode"),
        )
        picks.append(
            {
                "productId": int(row["productId"]),
                "title": row.get("title"),
                "authorName": row.get("authorName"),
                "coverImagePath": row.get("coverImagePath"),
                "risingType": rising_type,
                "comment": _COMMENT_TEMPLATES[rising_type],
            }
        )
    return picks


def build_rising_pick_response(
    rows: list[Mapping[str, Any]], now: datetime | None = None
) -> dict[str, Any]:
    basis = now or datetime.now(_KST).replace(tzinfo=None)
    picks = select_rising_picks(rows, basis)
    return {
        "asOf": basis.isoformat(),
        "refreshAfterSeconds": RISING_PICK_REFRESH_AFTER_SECONDS,
        "items": picks,
    }


def build_cache_key(adult_yn: str | None) -> str:
    return f"rising_pick:{_normalize_adult_yn(adult_yn)}"


def get_cached_rising_pick(adult_yn: str | None) -> dict[str, Any] | None:
    entry = _RISING_PICK_CACHE.get(build_cache_key(adult_yn))
    if entry is None or entry["expires_at"] <= time():
        return None
    return deepcopy(entry["response"])


def set_rising_pick_cache_for_tests(
    adult_yn: str | None, response: dict[str, Any], expires_at: float | None = None
) -> None:
    _RISING_PICK_CACHE[build_cache_key(adult_yn)] = {
        "expires_at": expires_at if expires_at is not None else time() + RISING_PICK_CACHE_TTL_SECONDS,
        "response": deepcopy(response),
    }


def reset_rising_pick_cache_for_tests() -> None:
    _RISING_PICK_CACHE.clear()


async def get_rising_picks(adult_yn: str, db: AsyncSession) -> dict[str, Any]:
    cached = get_cached_rising_pick(adult_yn)
    if cached is not None:
        return cached

    query, params = build_rising_pick_query(adult_yn)
    result = await db.execute(text(query), params)
    rows = result.mappings().all()

    now = datetime.now(_KST).replace(tzinfo=None)
    response = build_rising_pick_response(rows, now=now)
    set_rising_pick_cache_for_tests(adult_yn, response)
    return deepcopy(response)
