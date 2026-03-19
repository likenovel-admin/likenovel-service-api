#!/usr/bin/env python3
"""
factor row 없는 raw AI signal을 현재 metadata 기준으로 backfill한다.

사용법 (컨테이너 내부):
  python3 /app/dist/batch/backfill_ai_signal_event_factors.py --dry-run
  python3 /app/dist/batch/backfill_ai_signal_event_factors.py --product-id 673
  python3 /app/dist/batch/backfill_ai_signal_event_factors.py --event-id-from 900 --event-id-to 1200
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import bindparam, text

APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.rdb import likenovel_db_engine, likenovel_db_session  # noqa: E402
from app.services.ai import recommendation_service  # noqa: E402

SUPPORTED_EVENT_TYPES = (
    "episode_view",
    "episode_end",
    "latest_episode_reached",
    "next_episode_click",
    "revisit_24h",
    "taste_slot_click",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill missing AI signal factor rows")
    parser.add_argument("--event-id-from", type=int, help="시작 event_id")
    parser.add_argument("--event-id-to", type=int, help="종료 event_id")
    parser.add_argument("--product-id", type=int, help="특정 작품만")
    parser.add_argument("--user-id", type=int, help="특정 유저만")
    parser.add_argument("--limit", type=int, default=500, help="최대 처리 건수")
    parser.add_argument("--dry-run", action="store_true", help="대상/예상 factor만 출력")
    return parser.parse_args()


def build_where_clause(args: argparse.Namespace) -> tuple[str, dict]:
    clauses = [
        "e.event_type IN :supported_event_types",
    ]
    params: dict[str, object] = {
        "supported_event_types": SUPPORTED_EVENT_TYPES,
        "limit": int(args.limit or 500),
    }

    if args.event_id_from is not None:
        clauses.append("e.id >= :event_id_from")
        params["event_id_from"] = int(args.event_id_from)

    if args.event_id_to is not None:
        clauses.append("e.id <= :event_id_to")
        params["event_id_to"] = int(args.event_id_to)

    if args.product_id is not None:
        clauses.append("e.product_id = :product_id")
        params["product_id"] = int(args.product_id)

    if args.user_id is not None:
        clauses.append("e.user_id = :user_id")
        params["user_id"] = int(args.user_id)

    return " AND ".join(clauses), params

async def resolve_entries(row: dict, db) -> list[dict]:
    payload_raw = row.get("event_payload")
    payload = {}
    if payload_raw:
        try:
            payload = json.loads(payload_raw)
        except Exception:
            payload = {}

    event_type = str(row.get("event_type") or "").strip().lower()
    progress_ratio = recommendation_service._safe_float(row.get("progress_ratio"), 0.0)
    active_seconds = recommendation_service._safe_float(row.get("active_seconds"), 0.0)
    multiplier = recommendation_service._compute_signal_factor_score_multiplier(
        event_type,
        payload,
        progress_ratio=progress_ratio,
        active_seconds=active_seconds,
    )

    if multiplier <= 0:
        return []

    base_event_type = None
    if event_type == "revisit_24h":
        base_event_type = str(payload.get("base_event_type") or "").strip().lower() or None

    return await recommendation_service._resolve_signal_factor_entries(
        int(row["product_id"]),
        event_type,
        db,
        base_event_type=base_event_type,
        score_multiplier=multiplier,
    )


async def fetch_existing_factor_keys(event_ids: list[int], db) -> dict[int, set[tuple[str, str]]]:
    if not event_ids:
        return {}

    query = text(
        """
        SELECT event_id, factor_type, factor_key
        FROM tb_user_ai_signal_event_factor
        WHERE event_id IN :event_ids
        """
    ).bindparams(bindparam("event_ids", expanding=True))

    result = await db.execute(query, {"event_ids": event_ids})
    mapping: dict[int, set[tuple[str, str]]] = {}
    for row in result.mappings().all():
        mapping.setdefault(int(row["event_id"]), set()).add(
            (str(row["factor_type"]), str(row["factor_key"]))
        )
    return mapping


async def run(args: argparse.Namespace) -> int:
    where_sql, params = build_where_clause(args)
    query = text(
        f"""
        SELECT
            e.id,
            e.user_id,
            e.product_id,
            e.episode_id,
            e.event_type,
            e.active_seconds,
            e.progress_ratio,
            e.event_payload,
            e.created_date
        FROM tb_user_ai_signal_event e
        WHERE {where_sql}
        ORDER BY e.id
        LIMIT :limit
        """
    )

    try:
        async with likenovel_db_session() as db:
            result = await db.execute(
                query.bindparams(bindparam("supported_event_types", expanding=True)),
                params,
            )
            rows = [dict(row) for row in result.mappings().all()]

            if not rows:
                print("[INFO] 대상 raw signal이 없습니다.")
                return 0

            print(f"[INFO] 대상 이벤트 수: {len(rows)}")
            existing_factor_keys_by_event = await fetch_existing_factor_keys(
                [int(row["id"]) for row in rows],
                db,
            )

            inserted_events = 0
            inserted_factor_rows = 0
            skipped_events = 0

            for row in rows:
                entries = await resolve_entries(row, db)
                existing_keys = existing_factor_keys_by_event.get(int(row["id"]), set())
                missing_entries = [
                    entry
                    for entry in entries
                    if (str(entry["factor_type"]), str(entry["factor_key"])) not in existing_keys
                ]
                if args.dry_run:
                    print(
                        f"[DRY] event_id={row['id']} type={row['event_type']} "
                        f"product_id={row['product_id']} episode_id={row['episode_id']} "
                        f"existing_factor_rows={len(existing_keys)} "
                        f"missing_factor_rows={len(missing_entries)}"
                    )
                    if missing_entries:
                        inserted_events += 1
                        inserted_factor_rows += len(missing_entries)
                    else:
                        skipped_events += 1
                    continue

                if not missing_entries:
                    skipped_events += 1
                    continue

                await recommendation_service._insert_ai_signal_event_factors(
                    event_id=int(row["id"]),
                    user_id=int(row["user_id"]),
                    product_id=int(row["product_id"]),
                    episode_id=int(row["episode_id"]) if row.get("episode_id") is not None else None,
                    event_type=str(row["event_type"]),
                    factor_entries=missing_entries,
                    db=db,
                )
                inserted_events += 1
                inserted_factor_rows += len(missing_entries)

            if args.dry_run:
                print(
                    f"[DONE] dry-run target={len(rows)} insertable_events={inserted_events} "
                    f"insertable_factor_rows={inserted_factor_rows} skipped={skipped_events}"
                )
                return 0

            await db.commit()
            print(
                f"[DONE] target={len(rows)} inserted_events={inserted_events} "
                f"inserted_factor_rows={inserted_factor_rows} skipped={skipped_events}"
            )
            return 0
    finally:
        await likenovel_db_engine.dispose()


def main() -> int:
    args = parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
