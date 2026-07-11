import json
import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


SLOT_PAID_OPENRUN = "최근 유료전환 신작 오픈런!"
SLOT_WAIT_FREE = "24시간 기다리면 무료"
SLOT_FREE_NEW = "방금 들어온 무료신작"
SLOT_PD = "라이크노벨 판무PD 주목작"
SLOT_LOWPOINT = "반드시 저점매수 신작!"

SCHEDULED_CANDIDATE_FIELDS = (
    "product_id",
    "title",
    "price_type",
    "status_code",
    "paid_open_date",
    "first_public_episode_date",
    "latest_public_episode_date",
    "open_episode_count",
    "count_hit",
    "count_bookmark",
    "reading_rate",
    "writing_count_per_week",
    "waiting_for_free_yn",
)

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

SLOT_QUERY = text("""
    SELECT
        id AS slot_id,
        name,
        `order`,
        product_ids,
        exposure_start_date AS exposure_start,
        exposure_end_date AS exposure_end,
        exposure_start_time_weekday,
        exposure_end_time_weekday,
        exposure_start_time_weekend,
        exposure_end_time_weekend
    FROM tb_direct_recommend
    ORDER BY `order` ASC, id ASC
""")

CANDIDATE_QUERY = text("""
    SELECT
        p.product_id,
        p.title,
        p.price_type,
        p.product_type,
        p.status_code,
        p.publish_regular_yn,
        pg.keyword_name AS primary_genre,
        sg.keyword_name AS sub_genre,
        p.paid_open_date,
        ep.first_public_episode_date,
        ep.latest_public_episode_date,
        ep.open_episode_count,
        p.count_hit,
        p.count_bookmark,
        ti.reading_rate,
        ti.writing_count_per_week,
        IF(wff.product_id IS NULL, 'N', 'Y') AS waiting_for_free_yn,
        COALESCE(m.exclude_from_recommend_yn, 'N') AS exclude_from_recommend_yn,
        LEFT(p.synopsis_text, 600) AS synopsis_text,
        CASE WHEN m.analysis_status = 'success' THEN LEFT(m.premise, 500) END AS premise,
        CASE WHEN m.analysis_status = 'success' THEN LEFT(m.hook, 400) END AS hook,
        CASE
            WHEN m.analysis_status = 'success'
            THEN LEFT(m.episode_summary_text, 1000)
        END AS episode_summary_text
    FROM tb_product p
    INNER JOIN (
        SELECT
            product_id,
            COUNT(*) AS open_episode_count,
            MIN(COALESCE(publish_reserve_date, created_date)) AS first_public_episode_date,
            MAX(COALESCE(publish_reserve_date, created_date)) AS latest_public_episode_date
        FROM tb_product_episode
        WHERE open_yn = 'Y'
          AND use_yn = 'Y'
          AND (publish_reserve_date IS NULL OR publish_reserve_date <= NOW())
        GROUP BY product_id
    ) ep ON ep.product_id = p.product_id
    LEFT JOIN tb_product_ai_metadata m
      ON m.id = (
        SELECT MAX(m2.id)
        FROM tb_product_ai_metadata m2
        WHERE m2.product_id = p.product_id
      )
    LEFT JOIN tb_product_trend_index ti
      ON ti.id = (
        SELECT MAX(ti2.id)
        FROM tb_product_trend_index ti2
        WHERE ti2.product_id = p.product_id
      )
    LEFT JOIN tb_standard_keyword pg
      ON pg.keyword_id = p.primary_genre_id AND pg.use_yn = 'Y'
    LEFT JOIN tb_standard_keyword sg
      ON sg.keyword_id = p.sub_genre_id AND sg.use_yn = 'Y'
    LEFT JOIN (
        SELECT product_id
        FROM tb_applied_promotion
        WHERE type = 'waiting-for-free'
          AND status = 'ing'
          AND DATE(start_date) <= CURDATE()
          AND (end_date IS NULL OR DATE(end_date) >= CURDATE())
        GROUP BY product_id
    ) wff ON wff.product_id = p.product_id
    WHERE p.open_yn = 'Y'
      AND COALESCE(p.blind_yn, 'N') = 'N'
      AND (
        p.status_code = 'ongoing'
        OR wff.product_id IS NOT NULL
        OR EXISTS (
            SELECT 1
            FROM tb_direct_recommend dr
            WHERE JSON_CONTAINS(
                CAST(dr.product_ids AS JSON),
                CAST(p.product_id AS JSON),
                '$'
            ) = 1
        )
      )
    ORDER BY ep.latest_public_episode_date DESC, p.product_id DESC
    LIMIT 200
""")


class SnapshotBuildError(RuntimeError):
    pass


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def _redact_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return EMAIL_PATTERN.sub("[redacted-email]", str(value))


def _clip_text(value: Any, limit: int) -> str | None:
    redacted = _redact_text(value)
    if redacted is None:
        return None
    compact = " ".join(redacted.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3].rstrip()}..."


def _parse_product_ids(value: Any) -> list[int]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SnapshotBuildError("direct slot product_ids is invalid JSON") from exc
    if not isinstance(value, list):
        raise SnapshotBuildError("direct slot product_ids must be a JSON list")
    try:
        return [int(product_id) for product_id in value]
    except (TypeError, ValueError) as exc:
        raise SnapshotBuildError("direct slot product_ids contains a non-integer") from exc


async def _load_slots(db: AsyncSession) -> list[dict[str, Any]]:
    result = await db.execute(SLOT_QUERY)
    slots = []
    for row in result.mappings().all():
        slots.append(
            {
                "slot_id": int(row["slot_id"]),
                "name": row["name"],
                "order": int(row["order"]),
                "product_ids": _parse_product_ids(row["product_ids"]),
                "exposure_start": _json_value(row["exposure_start"]),
                "exposure_end": _json_value(row["exposure_end"]),
                "weekday": [
                    _json_value(row["exposure_start_time_weekday"]),
                    _json_value(row["exposure_end_time_weekday"]),
                ],
                "weekend": [
                    _json_value(row["exposure_start_time_weekend"]),
                    _json_value(row["exposure_end_time_weekend"]),
                ],
            }
        )
    return slots


def _sanitize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    sanitized = {key: _json_value(value) for key, value in candidate.items()}
    for field in ("synopsis_text", "premise", "hook", "episode_summary_text"):
        sanitized[field] = _redact_text(sanitized.get(field))
    for field in ("product_id", "open_episode_count", "count_hit", "count_bookmark"):
        if sanitized.get(field) is not None:
            sanitized[field] = int(sanitized[field])
    for field in ("reading_rate", "writing_count_per_week"):
        if sanitized.get(field) is not None:
            sanitized[field] = float(sanitized[field])
    return sanitized


async def _load_candidates(db: AsyncSession) -> list[dict[str, Any]]:
    result = await db.execute(CANDIDATE_QUERY)
    return [_sanitize_candidate(dict(row)) for row in result.mappings().all()]


def _slot_fingerprint(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: slot.get(key)
            for key in (
                "slot_id",
                "name",
                "order",
                "product_ids",
                "exposure_start",
                "exposure_end",
                "weekday",
                "weekend",
            )
        }
        for slot in slots
    ]


def _brief(candidate: dict[str, Any]) -> dict[str, Any]:
    return {"product_id": candidate["product_id"], "title": candidate["title"]}


def _get_slot(slots: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matches = [slot for slot in slots if slot.get("name") == name]
    if len(matches) != 1:
        raise SnapshotBuildError(
            f"expected one direct slot named {name!r}, found {len(matches)}"
        )
    return matches[0]


def build_objective_checks(
    slots: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> dict[str, Any]:
    by_id = {candidate["product_id"]: candidate for candidate in candidates}
    paid_ids = set(_get_slot(slots, SLOT_PAID_OPENRUN)["product_ids"])
    wait_free_ids = set(_get_slot(slots, SLOT_WAIT_FREE)["product_ids"])
    free_new_slot = _get_slot(slots, SLOT_FREE_NEW)
    free_new_ids = set(free_new_slot["product_ids"])

    paid_eligible = [
        candidate
        for candidate in candidates
        if candidate["price_type"] == "paid"
        and candidate["publish_regular_yn"] == "Y"
        and candidate["status_code"] == "ongoing"
        and candidate["exclude_from_recommend_yn"] != "Y"
    ]
    wait_free_eligible = [
        candidate
        for candidate in candidates
        if candidate["price_type"] == "paid"
        and candidate["waiting_for_free_yn"] == "Y"
        and candidate["exclude_from_recommend_yn"] != "Y"
    ]
    free_new_eligible = [
        candidate
        for candidate in candidates
        if candidate["price_type"] == "free"
        and candidate["product_type"] == "normal"
        and candidate["status_code"] == "ongoing"
        and candidate["exclude_from_recommend_yn"] != "Y"
    ]
    free_new_eligible.sort(
        key=lambda candidate: (
            candidate["first_public_episode_date"] or "",
            candidate["product_id"],
        ),
        reverse=True,
    )
    expected_free_new = free_new_eligible[: len(free_new_slot["product_ids"])]
    expected_free_new_ids = {candidate["product_id"] for candidate in expected_free_new}

    def current_violations(ids: set[int], predicate: Any) -> list[dict[str, Any]]:
        violations = []
        for product_id in sorted(ids):
            candidate = by_id.get(product_id)
            if candidate is None:
                violations.append(
                    {
                        "product_id": product_id,
                        "title": None,
                        "reason": "candidate_missing",
                    }
                )
            elif not predicate(candidate):
                violations.append(_brief(candidate))
        return violations

    duplicates = {
        slot["name"]: sorted(
            {
                product_id
                for product_id in slot["product_ids"]
                if slot["product_ids"].count(product_id) > 1
            }
        )
        for slot in slots
        if len(slot["product_ids"]) != len(set(slot["product_ids"]))
    }
    excluded_current = []
    for slot in slots:
        for product_id in slot["product_ids"]:
            candidate = by_id.get(product_id)
            if candidate and candidate["exclude_from_recommend_yn"] == "Y":
                excluded_current.append({"slot": slot["name"], **_brief(candidate)})

    return {
        "duplicate_product_ids_by_slot": duplicates,
        "metadata_excluded_current_products": excluded_current,
        "paid_openrun_missing": [
            _brief(item) for item in paid_eligible if item["product_id"] not in paid_ids
        ],
        "paid_openrun_ineligible_current": current_violations(
            paid_ids,
            lambda item: item["price_type"] == "paid"
            and item["publish_regular_yn"] == "Y"
            and item["status_code"] == "ongoing"
            and item["exclude_from_recommend_yn"] != "Y",
        ),
        "wait_free_missing": [
            _brief(item)
            for item in wait_free_eligible
            if item["product_id"] not in wait_free_ids
        ],
        "wait_free_ineligible_current": current_violations(
            wait_free_ids,
            lambda item: item["price_type"] == "paid"
            and item["waiting_for_free_yn"] == "Y"
            and item["exclude_from_recommend_yn"] != "Y",
        ),
        "free_new_expected_top": [_brief(item) for item in expected_free_new],
        "free_new_missing_from_expected_top": [
            _brief(item)
            for item in expected_free_new
            if item["product_id"] not in free_new_ids
        ],
        "free_new_extra_vs_expected_top": [
            _brief(by_id[product_id])
            for product_id in sorted(free_new_ids - expected_free_new_ids)
            if product_id in by_id
        ],
        "free_new_ineligible_current": current_violations(
            free_new_ids,
            lambda item: item["price_type"] == "free"
            and item["product_type"] == "normal"
            and item["status_code"] == "ongoing"
            and item["exclude_from_recommend_yn"] != "Y",
        ),
    }


def _select_editorial_detail_ids(
    slots: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    limit: int = 30,
) -> list[int]:
    by_id = {candidate["product_id"]: candidate for candidate in candidates}
    selected: list[int] = []
    selected_set: set[int] = set()

    def add(product_id: int) -> None:
        if product_id in by_id and product_id not in selected_set:
            selected.append(product_id)
            selected_set.add(product_id)

    for slot in slots:
        if slot.get("name") in {SLOT_PD, SLOT_LOWPOINT}:
            for product_id in slot.get("product_ids", []):
                add(product_id)

    eligible = [
        candidate
        for candidate in candidates
        if candidate.get("exclude_from_recommend_yn") != "Y"
    ]
    ranking_fields = (
        "first_public_episode_date",
        "latest_public_episode_date",
        "count_hit",
        "count_bookmark",
        "reading_rate",
    )
    rankings = [
        sorted(
            eligible,
            key=lambda candidate: (
                candidate.get(field) is not None,
                candidate.get(field) if candidate.get(field) is not None else "",
                candidate["product_id"],
            ),
            reverse=True,
        )
        for field in ranking_fields
    ]

    for index in range(max((len(ranking) for ranking in rankings), default=0)):
        for ranking in rankings:
            if index < len(ranking):
                add(ranking[index]["product_id"])
                if len(selected) >= limit:
                    return selected
    return selected


def _build_compact_snapshot(
    slots: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    stable: bool,
) -> dict[str, Any]:
    candidates = [_sanitize_candidate(candidate) for candidate in candidates]
    detail_ids = _select_editorial_detail_ids(slots, candidates)
    by_id = {candidate["product_id"]: candidate for candidate in candidates}
    current_product_ids_by_slot = {
        slot["name"]: [
            product_id
            for product_id in slot.get("product_ids", [])
            if product_id in by_id
        ]
        for slot in slots
        if slot.get("name") in {SLOT_PD, SLOT_LOWPOINT}
    }
    current_editorial_ids = {
        product_id
        for product_ids in current_product_ids_by_slot.values()
        for product_id in product_ids
    }
    editorial_detail_rows = []
    for product_id in detail_ids:
        candidate = by_id[product_id]
        premise = candidate.get("premise")
        synopsis = candidate.get("synopsis_text")
        editorial_detail_rows.append(
            [
                product_id,
                "premise" if premise else "synopsis",
                candidate.get("primary_genre"),
                candidate.get("sub_genre"),
                _clip_text(premise or synopsis, 100),
                _clip_text(candidate.get("hook"), 60),
                _clip_text(candidate.get("episode_summary_text"), 80),
            ]
        )

    return {
        "schema_version": 1,
        "mode": "proposal_only",
        "generated_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(
            timespec="seconds"
        ),
        "source": {
            "provider": "likenovel-service-api",
            "query": "direct_curator_snapshot_v1",
        },
        "slot_snapshot_stable": stable,
        "candidate_count": len(candidates),
        "objective_checks": build_objective_checks(slots, candidates) if stable else None,
        "snapshot_format": "scheduled_compact_v1",
        "slots": slots,
        "candidate_row_fields": list(SCHEDULED_CANDIDATE_FIELDS),
        "candidate_rows": [
            [candidate.get(field) for field in SCHEDULED_CANDIDATE_FIELDS]
            for candidate in candidates
        ],
        "editorial_detail_selection": {
            "limit": 30,
            "always_included_slots": [SLOT_PD, SLOT_LOWPOINT],
            "challenger_signals": [
                "first_public_episode_date",
                "latest_public_episode_date",
                "count_hit",
                "count_bookmark",
                "reading_rate",
            ],
            "note": (
                "Rows contain every candidate; excerpts are a diverse editorial "
                "review set, not a final ranking."
            ),
        },
        "editorial_comparison_sets": {
            "current_product_ids_by_slot": current_product_ids_by_slot,
            "challenger_product_ids": [
                product_id
                for product_id in detail_ids
                if product_id not in current_editorial_ids
            ],
        },
        "editorial_detail_fields": [
            "product_id",
            "content_source",
            "primary_genre",
            "sub_genre",
            "premise_or_synopsis_excerpt",
            "hook_excerpt",
            "episode_summary_excerpt",
        ],
        "editorial_detail_rows": editorial_detail_rows,
    }


async def build_scheduled_snapshot(db: AsyncSession) -> dict[str, Any]:
    before = await _load_slots(db)
    candidates = await _load_candidates(db)

    # End the read transaction so the second slot read can detect concurrent edits.
    await db.rollback()
    after = await _load_slots(db)
    stable = _slot_fingerprint(before) == _slot_fingerprint(after)

    return _build_compact_snapshot(after, candidates, stable)
