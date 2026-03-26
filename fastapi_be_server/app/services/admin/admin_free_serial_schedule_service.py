"""무료연재 예약 스케줄 업로드 서비스.

xlsx 시트 기준으로 이미 생성된 무료 일반연재 작품의 미래 회차 예약일시를
미리보기/적용한다.
"""

from __future__ import annotations

import io
import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import settings
from app.models.product import Product, ProductEpisode

logger = logging.getLogger(__name__)

EXPECTED_COLS = [
    "product_id",
    "작품제목",
    "시작회차",
    "예약공개시작일",
    "예약공개시각",
    "공개간격일수",
    "덮어쓰기",
    "제외회차",
]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
OVERWRITE_VALUES = {"Y", "N"}
MAX_ROWS = 500
MAX_TOTAL_TARGET_EPISODES = 100000
MIN_RESERVE_LEAD_MINUTES = 5

SKIP_ALREADY_OPEN = "already_open"
SKIP_EXCLUDED = "excluded_episode"
SKIP_PAST_RESERVED = "past_reserved_at"
SKIP_KEEP_FUTURE_RESERVED = "keep_existing_future_reserved"

SKIP_REASON_LABELS = {
    SKIP_ALREADY_OPEN: "이미 공개됨",
    SKIP_EXCLUDED: "제외회차",
    SKIP_PAST_RESERVED: "예약시각이 이미 지남",
    SKIP_KEEP_FUTURE_RESERVED: "기존 미래 예약 유지",
}


@asynccontextmanager
async def _apply_transaction(db: AsyncSession):
    if db.in_transaction():
        async with db.begin_nested():
            yield
        return

    async with db.begin():
        yield


@dataclass
class ScheduleConfig:
    row_no: int
    product_id: int | None
    sheet_title: str
    start_episode_no: int | None
    start_date: str
    start_time: str
    interval_days: int | None
    overwrite_future_reserved: str
    excluded_episode_nos: list[int]
    errors: list[str]


@dataclass
class EpisodeSnapshot:
    episode_id: int
    episode_no: int
    open_yn: str
    publish_reserve_date: datetime | None


def _now_kst_naive() -> datetime:
    return datetime.now(ZoneInfo(settings.KOREA_TIMEZONE)).replace(tzinfo=None)


def _normalize_string(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_positive_int(raw: str, field_name: str, errors: list[str]) -> int | None:
    if not raw:
        errors.append(f"{field_name} 필수")
        return None
    if not raw.isdigit():
        errors.append(f"{field_name} 숫자만 입력")
        return None

    value = int(raw)
    if value <= 0:
        errors.append(f"{field_name} 1 이상")
        return None
    return value


def _parse_overwrite(raw: str, errors: list[str]) -> str:
    value = (raw or "Y").strip().upper() or "Y"
    if value not in OVERWRITE_VALUES:
        errors.append("덮어쓰기 값은 Y 또는 N")
        return "Y"
    return value


def _parse_excluded_episode_nos(raw: str, start_episode_no: int | None, errors: list[str]) -> list[int]:
    value = raw.strip()
    if not value:
        return []

    tokens = [token.strip() for token in value.split(",")]
    if any(not token for token in tokens):
        errors.append("제외회차 형식 오류")
        return []
    if any(not token.isdigit() for token in tokens):
        errors.append("제외회차는 숫자와 쉼표만 허용")
        return []

    numbers = [int(token) for token in tokens]
    if any(number <= 0 for number in numbers):
        errors.append("제외회차는 1 이상")
        return []
    if len(numbers) != len(set(numbers)):
        errors.append("제외회차 중복 불가")
        return []
    if start_episode_no is not None and any(number < start_episode_no for number in numbers):
        errors.append("제외회차는 시작회차 이상만 허용")
        return []
    return sorted(numbers)


def _parse_start_at(date_raw: str, time_raw: str, errors: list[str]) -> datetime | None:
    date_value = date_raw.strip()
    time_value = time_raw.strip()

    if not date_value:
        errors.append("예약공개시작일 필수")
    elif not DATE_RE.match(date_value):
        errors.append("예약공개시작일 형식은 YYYY-MM-DD")

    if not time_value:
        errors.append("예약공개시각 필수")
    elif not TIME_RE.match(time_value):
        errors.append("예약공개시각 형식은 HH:MM")

    if errors:
        return None

    try:
        parsed = datetime.strptime(f"{date_value} {time_value}", "%Y-%m-%d %H:%M")
    except ValueError:
        errors.append("예약공개 시작일시 파싱 실패")
        return None

    min_allowed_at = _minimum_reserve_at_kst_naive()
    if parsed < min_allowed_at:
        errors.append(
            f"예약공개 시작일시는 현재 시각 기준 {MIN_RESERVE_LEAD_MINUTES}분 이후만 허용"
        )
        return None

    return parsed


def _minimum_reserve_at_kst_naive() -> datetime:
    now = _now_kst_naive()
    if now.second or now.microsecond:
        now = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return now + timedelta(minutes=MIN_RESERVE_LEAD_MINUTES)


def _read_configs_from_excel(excel_bytes: bytes) -> tuple[list[ScheduleConfig], str | None]:
    try:
        df = pd.read_excel(io.BytesIO(excel_bytes), engine="openpyxl", dtype=str)
    except Exception as exc:
        return [], f"엑셀 파싱 실패: {type(exc).__name__}: {exc}"

    df = df.fillna("")

    missing_cols = [col for col in EXPECTED_COLS if col not in df.columns]
    if missing_cols:
        return [], f"누락 컬럼: {', '.join(missing_cols)}"

    if len(df) == 0:
        return [], "처리할 데이터가 없습니다."
    if len(df) > MAX_ROWS:
        return [], f"최대 {MAX_ROWS}행까지만 업로드할 수 있습니다."

    duplicate_product_ids: set[int] = set()
    seen_product_ids: set[int] = set()
    for _, row in df.iterrows():
        raw_product_id = _normalize_string(row.get("product_id"))
        if raw_product_id.isdigit():
            product_id = int(raw_product_id)
            if product_id in seen_product_ids:
                duplicate_product_ids.add(product_id)
            seen_product_ids.add(product_id)

    configs: list[ScheduleConfig] = []
    for index, row in df.iterrows():
        row_no = index + 2
        errors: list[str] = []

        product_id_raw = _normalize_string(row.get("product_id"))
        product_id = _parse_positive_int(product_id_raw, "product_id", errors)
        if product_id is not None and product_id in duplicate_product_ids:
            errors.append("같은 product_id가 시트에 중복됨")

        start_episode_no = _parse_positive_int(
            _normalize_string(row.get("시작회차")), "시작회차", errors
        )
        interval_days = _parse_positive_int(
            _normalize_string(row.get("공개간격일수")) or "1", "공개간격일수", errors
        )
        overwrite_future_reserved = _parse_overwrite(
            _normalize_string(row.get("덮어쓰기")), errors
        )
        excluded_episode_nos = _parse_excluded_episode_nos(
            _normalize_string(row.get("제외회차")), start_episode_no, errors
        )

        _parse_start_at(
            _normalize_string(row.get("예약공개시작일")),
            _normalize_string(row.get("예약공개시각")),
            errors,
        )

        configs.append(
            ScheduleConfig(
                row_no=row_no,
                product_id=product_id,
                sheet_title=_normalize_string(row.get("작품제목")),
                start_episode_no=start_episode_no,
                start_date=_normalize_string(row.get("예약공개시작일")),
                start_time=_normalize_string(row.get("예약공개시각")),
                interval_days=interval_days,
                overwrite_future_reserved=overwrite_future_reserved,
                excluded_episode_nos=excluded_episode_nos,
                errors=errors,
            )
        )

    return configs, None


async def _load_products_map(
    product_ids: list[int],
    db: AsyncSession,
) -> dict[int, dict[str, Any]]:
    if not product_ids:
        return {}

    result = await db.execute(
        select(
            Product.product_id,
            Product.title,
            Product.price_type,
            Product.product_type,
            Product.open_yn,
        ).where(Product.product_id.in_(product_ids))
    )
    return {
        row.product_id: {
            "product_id": row.product_id,
            "title": row.title,
            "price_type": row.price_type,
            "product_type": row.product_type,
            "open_yn": row.open_yn,
        }
        for row in result.all()
    }


async def _load_episodes_map(
    product_ids: list[int],
    db: AsyncSession,
    for_update: bool = False,
) -> dict[int, list[EpisodeSnapshot]]:
    if not product_ids:
        return {}

    stmt = (
        select(
            ProductEpisode.episode_id,
            ProductEpisode.product_id,
            ProductEpisode.episode_no,
            ProductEpisode.open_yn,
            ProductEpisode.publish_reserve_date,
        )
        .where(
            ProductEpisode.product_id.in_(product_ids),
            ProductEpisode.use_yn == "Y",
        )
        .order_by(ProductEpisode.product_id, ProductEpisode.episode_no)
    )
    if for_update:
        stmt = stmt.with_for_update()

    result = await db.execute(stmt)
    episodes_map: dict[int, list[EpisodeSnapshot]] = {}
    for row in result.all():
        episodes_map.setdefault(row.product_id, []).append(
            EpisodeSnapshot(
                episode_id=row.episode_id,
                episode_no=row.episode_no,
                open_yn=row.open_yn or "N",
                publish_reserve_date=row.publish_reserve_date,
            )
        )
    return episodes_map


def _validate_product_scope(
    product: dict[str, Any] | None,
    config: ScheduleConfig,
    row_errors: list[str],
) -> None:
    if config.product_id is None:
        return

    if product is None:
        row_errors.append("대상 작품 없음")
        return

    if product["price_type"] != "free":
        row_errors.append("무료연재 작품만 가능")
    if product["product_type"] != "normal":
        row_errors.append("일반연재 작품만 가능")
    if config.sheet_title and product["title"] != config.sheet_title:
        row_errors.append("작품제목이 시트와 불일치")


def _skip_reason_label(reason: str) -> str:
    return SKIP_REASON_LABELS.get(reason, reason)


def _build_row_result(
    config: ScheduleConfig,
    product: dict[str, Any] | None,
    episodes: list[EpisodeSnapshot],
) -> dict[str, Any]:
    row_errors = list(config.errors)
    _validate_product_scope(product, config, row_errors)

    row_result: dict[str, Any] = {
        "row": config.row_no,
        "product_id": config.product_id,
        "sheet_title": config.sheet_title,
        "title": product["title"] if product else config.sheet_title,
        "start_episode_no": config.start_episode_no,
        "schedule_start_date": config.start_date,
        "schedule_time": config.start_time,
        "interval_days": config.interval_days,
        "overwrite_future_reserved": config.overwrite_future_reserved,
        "excluded_episode_nos": config.excluded_episode_nos,
        "total_episode_count": len(episodes),
        "matched_episode_count": 0,
        "apply_target_count": 0,
        "new_reservation_count": 0,
        "overwrite_reservation_count": 0,
        "skipped_count": 0,
        "skip_reason_counts": {},
        "first_schedule_at": None,
        "last_schedule_at": None,
        "errors": row_errors,
        "_planned_updates": [],
    }

    if row_errors or config.start_episode_no is None or config.interval_days is None:
        return row_result

    start_at = _parse_start_at(config.start_date, config.start_time, row_errors)
    if row_errors:
        row_result["errors"] = row_errors
        return row_result

    target_episodes = [ep for ep in episodes if ep.episode_no >= config.start_episode_no]
    if not target_episodes:
        row_result["errors"] = row_errors + ["시작회차 이후 회차가 없음"]
        return row_result

    excluded_set = set(config.excluded_episode_nos)
    now_kst = _now_kst_naive()
    schedule_index = 0
    skip_reason_counts: dict[str, int] = {}
    planned_updates: list[dict[str, Any]] = []
    matched_episode_count = 0

    for episode in target_episodes:
        if episode.episode_no in excluded_set:
            skip_reason_counts[SKIP_EXCLUDED] = skip_reason_counts.get(SKIP_EXCLUDED, 0) + 1
            continue

        matched_episode_count += 1

        if episode.open_yn == "Y":
            skip_reason_counts[SKIP_ALREADY_OPEN] = skip_reason_counts.get(SKIP_ALREADY_OPEN, 0) + 1
            continue

        reserve_at = episode.publish_reserve_date
        if reserve_at is not None and reserve_at <= now_kst:
            skip_reason_counts[SKIP_PAST_RESERVED] = skip_reason_counts.get(SKIP_PAST_RESERVED, 0) + 1
            continue

        if (
            reserve_at is not None
            and reserve_at > now_kst
            and config.overwrite_future_reserved == "N"
        ):
            skip_reason_counts[SKIP_KEEP_FUTURE_RESERVED] = (
                skip_reason_counts.get(SKIP_KEEP_FUTURE_RESERVED, 0) + 1
            )
            continue

        scheduled_at = start_at + timedelta(days=schedule_index * config.interval_days)
        update_type = "overwrite" if reserve_at is not None and reserve_at > now_kst else "new"
        planned_updates.append(
            {
                "episode_id": episode.episode_id,
                "episode_no": episode.episode_no,
                "publish_reserve_date": scheduled_at,
                "update_type": update_type,
            }
        )
        schedule_index += 1

    if matched_episode_count == 0:
        row_result["errors"] = row_errors + ["시작회차 이후 적용 대상 회차가 없음"]
        return row_result

    row_result["matched_episode_count"] = matched_episode_count
    row_result["apply_target_count"] = len(planned_updates)
    row_result["new_reservation_count"] = sum(
        1 for item in planned_updates if item["update_type"] == "new"
    )
    row_result["overwrite_reservation_count"] = sum(
        1 for item in planned_updates if item["update_type"] == "overwrite"
    )
    row_result["skipped_count"] = sum(skip_reason_counts.values())
    row_result["skip_reason_counts"] = {
        _skip_reason_label(reason): count for reason, count in skip_reason_counts.items()
    }
    if planned_updates:
        row_result["first_schedule_at"] = planned_updates[0]["publish_reserve_date"].strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        row_result["last_schedule_at"] = planned_updates[-1]["publish_reserve_date"].strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    row_result["_planned_updates"] = planned_updates
    return row_result


async def _build_plan(
    excel_bytes: bytes,
    db: AsyncSession,
    for_update: bool = False,
) -> tuple[list[dict[str, Any]], str | None]:
    configs, read_error = _read_configs_from_excel(excel_bytes)
    if read_error:
        return [], read_error

    product_ids = sorted(
        {config.product_id for config in configs if config.product_id is not None}
    )
    products_map = await _load_products_map(product_ids, db)
    episodes_map = await _load_episodes_map(product_ids, db, for_update=for_update)

    total_target_episodes = 0
    results: list[dict[str, Any]] = []
    for config in configs:
        row_result = _build_row_result(
            config=config,
            product=products_map.get(config.product_id) if config.product_id else None,
            episodes=episodes_map.get(config.product_id, []) if config.product_id else [],
        )
        total_target_episodes += row_result["matched_episode_count"]
        results.append(row_result)

    if total_target_episodes > MAX_TOTAL_TARGET_EPISODES:
        return [], f"한 번에 처리 가능한 회차 수({MAX_TOTAL_TARGET_EPISODES})를 초과했습니다."

    return results, None


def _build_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "row_count": len(results),
        "error_row_count": sum(1 for row in results if row["errors"]),
        "matched_episode_count": sum(row["matched_episode_count"] for row in results),
        "apply_target_count": sum(row["apply_target_count"] for row in results),
        "new_reservation_count": sum(row["new_reservation_count"] for row in results),
        "overwrite_reservation_count": sum(
            row["overwrite_reservation_count"] for row in results
        ),
        "skipped_count": sum(row["skipped_count"] for row in results),
    }


def _public_row_result(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "_planned_updates"}


async def preview_free_serial_schedule_upload(
    excel_bytes: bytes,
    db: AsyncSession,
) -> dict[str, Any]:
    results, error_message = await _build_plan(excel_bytes=excel_bytes, db=db)
    if error_message:
        return {"success": False, "message": error_message, "summary": None, "results": []}

    summary = _build_summary(results)
    message = "미리보기 완료"
    if summary["error_row_count"] > 0:
        message = f"오류 {summary['error_row_count']}건 포함"

    return {
        "success": True,
        "message": message,
        "summary": summary,
        "results": [_public_row_result(row) for row in results],
    }


async def apply_free_serial_schedule_upload(
    excel_bytes: bytes,
    db: AsyncSession,
    admin_user_id: int,
) -> dict[str, Any]:
    async with _apply_transaction(db):
        results, error_message = await _build_plan(
            excel_bytes=excel_bytes,
            db=db,
            for_update=True,
        )
        if error_message:
            return {
                "success": False,
                "message": error_message,
                "summary": None,
                "results": [],
            }

        summary = _build_summary(results)
        if summary["error_row_count"] > 0:
            return {
                "success": False,
                "message": "오류 행이 있어 적용하지 않았습니다.",
                "summary": summary,
                "results": [_public_row_result(row) for row in results],
            }

        updates: list[dict[str, Any]] = []
        updated_at = datetime.now()
        for row in results:
            for item in row["_planned_updates"]:
                updates.append(
                    {
                        "episode_id": item["episode_id"],
                        "publish_reserve_date": item["publish_reserve_date"],
                        "updated_id": admin_user_id,
                        "updated_date": updated_at,
                    }
                )

        for item in updates:
            await db.execute(
                update(ProductEpisode)
                .where(
                    ProductEpisode.episode_id == item["episode_id"],
                    ProductEpisode.use_yn == "Y",
                    ProductEpisode.open_yn == "N",
                )
                .values(
                    publish_reserve_date=item["publish_reserve_date"],
                    open_yn="N",
                    updated_id=item["updated_id"],
                    updated_date=item["updated_date"],
                )
            )

        logger.info(
            "[free-serial-schedule][apply] admin_user_id=%s row_count=%s apply_target_count=%s overwrite_count=%s skipped_count=%s results=%s",
            admin_user_id,
            summary["row_count"],
            summary["apply_target_count"],
            summary["overwrite_reservation_count"],
            summary["skipped_count"],
            [
                {
                    "row": row["row"],
                    "product_id": row["product_id"],
                    "title": row["title"],
                    "start_episode_no": row["start_episode_no"],
                    "interval_days": row["interval_days"],
                    "overwrite_future_reserved": row["overwrite_future_reserved"],
                    "apply_target_count": row["apply_target_count"],
                    "new_reservation_count": row["new_reservation_count"],
                    "overwrite_reservation_count": row["overwrite_reservation_count"],
                    "skipped_count": row["skipped_count"],
                    "skip_reason_counts": row["skip_reason_counts"],
                    "episode_ids": [item["episode_id"] for item in row["_planned_updates"]],
                }
                for row in results
            ],
        )

    return {
        "success": True,
        "message": f"{summary['apply_target_count']}개 회차 예약을 적용했습니다.",
        "summary": summary,
        "results": [_public_row_result(row) for row in results],
    }
