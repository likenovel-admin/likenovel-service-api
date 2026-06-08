from copy import deepcopy
from datetime import datetime, timedelta
from time import time
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


HOME_TICKER_REFRESH_AFTER_SECONDS = 60
HOME_TICKER_ROTATE_EVERY_MS = 5000
HOME_TICKER_LIMIT = 10
HOME_TICKER_CACHE_TTL_SECONDS = 60

_KST = ZoneInfo("Asia/Seoul")
_PUBLIC_COPY_BLOCK_TERMS = ("연독률", "재유입", "전환율")
_FALLBACK_MESSAGE = "오늘도 새로운 이야기가 라이크노벨에서 독자를 만나고 있습니다."
_HOME_TICKER_CACHE: dict[str, dict[str, Any]] = {}
_DEFAULT_FRESHNESS = "metric_snapshot"


def _normalize_adult_yn(adult_yn: str | None) -> str:
    return "Y" if (adult_yn or "").upper() == "Y" else "N"


def _visibility_filter(adult_yn: str | None) -> str:
    clauses = [
        "p.open_yn = 'Y'",
        "COALESCE(p.blind_yn, 'N') = 'N'",
        "p.status_code IN ('ongoing', 'end')",
    ]
    if _normalize_adult_yn(adult_yn) != "Y":
        clauses.append("p.ratings_code = 'all'")
    return "\n          AND ".join(clauses)


def _contains_internal_metric_term(message: str) -> bool:
    return any(term in message for term in _PUBLIC_COPY_BLOCK_TERMS)


def build_ticker_item(
    item_type: str,
    message: str,
    priority: int,
    product_id: int | None = None,
    freshness: str = _DEFAULT_FRESHNESS,
) -> dict[str, Any] | None:
    if not message or _contains_internal_metric_term(message):
        return None
    return {
        "type": item_type,
        "message": message,
        "productId": int(product_id) if product_id is not None else None,
        "priority": int(priority),
        "freshness": freshness,
    }


def get_week_window_kst(now: datetime | None = None) -> tuple[datetime, datetime]:
    basis = now or datetime.now(_KST)
    if basis.tzinfo is not None:
        basis = basis.astimezone(_KST).replace(tzinfo=None)
    week_start = (basis - timedelta(days=basis.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return week_start, week_start + timedelta(days=7)


def build_paid_conversion_summary_item(author_count: int) -> dict[str, Any] | None:
    if author_count <= 0:
        return None
    return build_ticker_item(
        item_type="paid_conversion_summary",
        message=f"이번 주 유료전환 작가님 {author_count}명 축하드립니다.",
        priority=100,
        freshness="weekly",
    )


def build_paid_conversion_summary_query(
    week_start: datetime,
    week_end: datetime,
    adult_yn: str | None,
) -> tuple[str, dict[str, Any]]:
    query = f"""
        SELECT
            'paid_conversion_summary' AS itemType,
            NULL AS productId,
            CONCAT('이번 주 유료전환 작가님 ', COUNT(DISTINCT p.author_id), '명 축하드립니다.') AS message,
            100 AS priority,
            'weekly' AS freshness
        FROM tb_product p
        WHERE {_visibility_filter(adult_yn)}
          AND p.paid_open_date IS NOT NULL
          AND p.paid_open_date >= :week_start
          AND p.paid_open_date < :week_end
        HAVING COUNT(DISTINCT p.author_id) > 0
    """
    return query, {"week_start": week_start, "week_end": week_end}


def build_recent_episode_query(adult_yn: str | None) -> tuple[str, dict[str, Any]]:
    query = f"""
        SELECT
            'recent_episode' AS itemType,
            p.product_id AS productId,
            CASE
                WHEN p.author_name IS NULL OR p.author_name = ''
                    THEN CONCAT('작가님이 <', p.title, '>의 신규 회차를 업로드했습니다.')
                ELSE CONCAT(p.author_name, ' 작가님이 <', p.title, '>의 신규 회차를 업로드했습니다.')
            END AS message,
            90 AS priority,
            'near_real_time' AS freshness
        FROM tb_product_episode e
        INNER JOIN tb_product p ON p.product_id = e.product_id
        WHERE {_visibility_filter(adult_yn)}
          AND e.open_yn = 'Y'
          AND e.use_yn = 'Y'
          AND e.publish_reserve_date <= NOW()
          AND e.publish_reserve_date >= DATE_SUB(NOW(), INTERVAL 2 HOUR)
        ORDER BY e.publish_reserve_date DESC, e.episode_id DESC
        LIMIT 5
    """
    return query, {}


def build_popular_free_top_query(adult_yn: str | None) -> tuple[str, dict[str, Any]]:
    query = f"""
        SELECT
            'popular_free_top' AS itemType,
            p.product_id AS productId,
            CASE
                WHEN p.author_name IS NULL OR p.author_name = ''
                    THEN CONCAT('작가님의 <', p.title, '>이 인기무료 TOP 1위에 올랐습니다.')
                ELSE CONCAT(p.author_name, ' 작가님의 <', p.title, '>이 인기무료 TOP 1위에 올랐습니다.')
            END AS message,
            80 AS priority,
            'ranking_snapshot' AS freshness
        FROM tb_product_rank_area r
        INNER JOIN (
            SELECT product_id, MAX(created_date) AS created_date
            FROM tb_product_rank_area
            WHERE area_code = 'freeSerialTop'
            GROUP BY product_id
        ) latest ON latest.product_id = r.product_id AND latest.created_date = r.created_date
        INNER JOIN tb_product p ON p.product_id = r.product_id
        WHERE {_visibility_filter(adult_yn)}
          AND r.area_code = 'freeSerialTop'
          AND r.current_rank = 1
          AND p.price_type = 'free'
          AND p.status_code = 'ongoing'
        LIMIT 1
    """
    return query, {}


def build_reader_momentum_query(adult_yn: str | None) -> tuple[str, dict[str, Any]]:
    query = f"""
        SELECT
            'reader_momentum' AS itemType,
            p.product_id AS productId,
            CONCAT('<', p.title, '>을 이어 읽는 독자가 늘고 있습니다.') AS message,
            70 AS priority,
            'metric_snapshot' AS freshness
        FROM tb_product p
        INNER JOIN tb_product_trend_index pti ON pti.product_id = p.product_id
        INNER JOIN tb_product_count_variance pcv ON pcv.product_id = p.product_id
        WHERE {_visibility_filter(adult_yn)}
          AND pcv.reading_rate_indicator >= :min_reading_rate_indicator
          AND p.count_hit >= :min_count_hit
        ORDER BY pcv.reading_rate_indicator DESC, p.count_hit DESC, p.product_id DESC
        LIMIT 5
    """
    return query, {
        "min_reading_rate_indicator": 5,
        "min_count_hit": 100,
    }


def build_new_product_query(adult_yn: str | None) -> tuple[str, dict[str, Any]]:
    query = f"""
        SELECT
            'new_product' AS itemType,
            p.product_id AS productId,
            CASE
                WHEN p.author_name IS NULL OR p.author_name = ''
                    THEN CONCAT('작가님의 신규작 <', p.title, '>이 등록되었습니다.')
                ELSE CONCAT(p.author_name, ' 작가님의 신규작 <', p.title, '>이 등록되었습니다.')
            END AS message,
            60 AS priority,
            'near_real_time' AS freshness
        FROM tb_product p
        WHERE {_visibility_filter(adult_yn)}
          AND p.created_date >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
        ORDER BY p.created_date DESC, p.product_id DESC
        LIMIT 3
    """
    return query, {}


def build_new_notice_query(adult_yn: str | None = None) -> tuple[str, dict[str, Any]]:
    query = """
        SELECT
            'new_notice' AS itemType,
            NULL AS productId,
            '새로운 공지사항이 등록되었습니다' AS message,
            85 AS priority,
            'near_real_time' AS freshness
        FROM tb_notice n
        WHERE n.use_yn = 'Y'
          AND n.created_date >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
        ORDER BY n.created_date DESC, n.id DESC
        LIMIT 1
    """
    return query, {}


def build_material_trend_query(adult_yn: str | None) -> tuple[str, dict[str, Any]]:
    query = f"""
        SELECT
            'material_trend' AS itemType,
            NULL AS productId,
            CONCAT('최근 ', materials.materialTag, ' 소재 작품을 찾는 독자가 늘고 있습니다.') AS message,
            50 AS priority,
            'trend_snapshot' AS freshness
        FROM tb_product p
        INNER JOIN tb_product_ai_metadata m ON m.product_id = p.product_id
        INNER JOIN tb_product_count_variance pcv ON pcv.product_id = p.product_id
        CROSS JOIN JSON_TABLE(
            IF(JSON_VALID(m.protagonist_material_tags), m.protagonist_material_tags, JSON_ARRAY()),
            '$[*]' COLUMNS(materialTag VARCHAR(100) PATH '$')
        ) materials
        WHERE {_visibility_filter(adult_yn)}
          AND JSON_VALID(m.protagonist_material_tags)
          AND p.count_hit >= :min_count_hit
          AND materials.materialTag IS NOT NULL
          AND materials.materialTag != ''
        GROUP BY materials.materialTag
        HAVING COUNT(DISTINCT p.product_id) >= :min_product_count
        ORDER BY COUNT(DISTINCT p.product_id) DESC, MAX(p.count_hit) DESC
        LIMIT :limit_count
    """
    return query, {
        "min_count_hit": 100,
        "min_product_count": 2,
        "limit_count": 3,
    }


def _row_value(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _item_from_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    return build_ticker_item(
        item_type=_row_value(row, "type", "itemType"),
        message=_row_value(row, "message"),
        priority=_row_value(row, "priority") or 0,
        product_id=_row_value(row, "productId", "product_id"),
        freshness=_row_value(row, "freshness") or _DEFAULT_FRESHNESS,
    )


def build_home_ticker_response(
    rows: list[Mapping[str, Any]], now: datetime | None = None
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None]] = set()
    for row in sorted(rows, key=lambda value: int(value.get("priority") or 0), reverse=True):
        item = _item_from_row(row)
        if item is None:
            continue
        key = (item["type"], item.get("productId"))
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
        if len(items) >= HOME_TICKER_LIMIT:
            break

    if not items:
        items = [
            build_ticker_item(
                item_type="fallback",
                message=_FALLBACK_MESSAGE,
                priority=0,
                freshness="fallback",
            )
        ]

    basis = now or datetime.now(_KST)
    as_of = basis.isoformat() if isinstance(basis, datetime) else None
    return {
        "asOf": as_of,
        "refreshAfterSeconds": HOME_TICKER_REFRESH_AFTER_SECONDS,
        "rotateEveryMs": HOME_TICKER_ROTATE_EVERY_MS,
        "items": items,
    }


def build_cache_key(adult_yn: str | None) -> str:
    return f"home_ticker:{_normalize_adult_yn(adult_yn)}"


def get_cached_home_ticker(adult_yn: str | None) -> dict[str, Any] | None:
    cache_entry = _HOME_TICKER_CACHE.get(build_cache_key(adult_yn))
    if cache_entry is None or cache_entry["expires_at"] <= time():
        return None
    return deepcopy(cache_entry["response"])


def set_home_ticker_cache_for_tests(
    adult_yn: str | None, response: dict[str, Any], expires_at: float | None = None
) -> None:
    _HOME_TICKER_CACHE[build_cache_key(adult_yn)] = {
        "expires_at": expires_at if expires_at is not None else time() + HOME_TICKER_CACHE_TTL_SECONDS,
        "response": deepcopy(response),
    }


def reset_home_ticker_cache_for_tests() -> None:
    _HOME_TICKER_CACHE.clear()


async def _fetch_ticker_rows(db: AsyncSession, query: str, params: dict[str, Any]) -> list[Mapping[str, Any]]:
    result = await db.execute(text(query), params)
    return result.mappings().all()


async def get_home_ticker(adult_yn: str, db: AsyncSession) -> dict[str, Any]:
    cached = get_cached_home_ticker(adult_yn)
    if cached is not None:
        return cached

    now = datetime.now(_KST).replace(tzinfo=None)
    rows: list[Mapping[str, Any]] = []

    week_start, week_end = get_week_window_kst(now)
    paid_conversion_query, paid_conversion_params = build_paid_conversion_summary_query(
        week_start, week_end, adult_yn
    )
    rows.extend(await _fetch_ticker_rows(db, paid_conversion_query, paid_conversion_params))
    for query_builder in (
        build_recent_episode_query,
        build_popular_free_top_query,
        build_reader_momentum_query,
        build_new_product_query,
        build_new_notice_query,
        build_material_trend_query,
    ):
        query, params = query_builder(adult_yn)
        rows.extend(await _fetch_ticker_rows(db, query, params))

    response = build_home_ticker_response(rows, now=now)
    set_home_ticker_cache_for_tests(adult_yn, response)
    return deepcopy(response)
