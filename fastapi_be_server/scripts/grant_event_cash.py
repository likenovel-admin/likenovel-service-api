"""Grant chat-only event cash (이벤트 캐시) to exact user IDs.

Dry-run is the default. --apply grants once per (user_id, grant_key) inside one
transaction, so re-running the same command never double-grants.

Run from the backend root (fastapi_be_server) or the deployed api directory
with the app package importable and the DB env loaded, for example:
  PYTHONPATH=. python scripts/grant_event_cash.py --user-ids 971,1127 --amount 300 --grant-key websochat-outage-20260930 --memo "웹소챗 장애 보상"
  (add --apply to write)
"""

from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import bindparam, text

from app.rdb import likenovel_db_engine, likenovel_db_session
from app.services.websochat.websochat_event_cash import (
    get_user_event_cash_balance,
    grant_event_cash,
)


def _parse_user_ids(raw: str) -> list[int]:
    user_ids = sorted({int(part) for part in raw.split(",") if part.strip()})
    if not user_ids:
        raise SystemExit("--user-ids must contain at least one user id")
    return user_ids


async def _load_users(db, user_ids: list[int]) -> dict[int, dict]:
    result = await db.execute(
        text(
            """
            SELECT user_id, email, use_yn
            FROM tb_user
            WHERE user_id IN :user_ids
            """
        ).bindparams(bindparam("user_ids", expanding=True)),
        {"user_ids": user_ids},
    )
    return {int(row["user_id"]): dict(row) for row in result.mappings().all()}


async def _already_granted(db, user_ids: list[int], grant_key: str) -> set[int]:
    result = await db.execute(
        text(
            """
            SELECT user_id
            FROM tb_user_event_cash_transaction
            WHERE grant_key = :grant_key
              AND user_id IN :user_ids
            """
        ).bindparams(bindparam("user_ids", expanding=True)),
        {"grant_key": grant_key, "user_ids": user_ids},
    )
    return {int(row["user_id"]) for row in result.mappings().all()}


async def run(args: argparse.Namespace) -> int:
    user_ids = _parse_user_ids(args.user_ids)
    if args.amount <= 0:
        raise SystemExit("--amount must be positive")
    grant_key = args.grant_key.strip()
    if not grant_key:
        raise SystemExit("--grant-key is required")

    try:
        async with likenovel_db_session() as db:
            users = await _load_users(db, user_ids)
            missing = [user_id for user_id in user_ids if user_id not in users]
            inactive = [
                user_id
                for user_id, row in users.items()
                if str(row.get("use_yn") or "").upper() != "Y"
            ]
            if missing or inactive:
                print(json.dumps({"ok": False, "missing": missing, "inactive": inactive}))
                return 2
            granted_before = await _already_granted(db, user_ids, grant_key)
            plan = [
                {
                    "user_id": user_id,
                    "balance_before": await get_user_event_cash_balance(user_id, db),
                    "already_granted": user_id in granted_before,
                }
                for user_id in user_ids
            ]
            if not args.apply:
                print(json.dumps({"ok": True, "mode": "dry-run", "amount": args.amount, "grant_key": grant_key, "plan": plan}))
                return 0

            granted = []
            for user_id in user_ids:
                if await grant_event_cash(
                    user_id=user_id,
                    amount=args.amount,
                    grant_key=grant_key,
                    memo=args.memo,
                    db=db,
                ):
                    granted.append(user_id)
            await db.commit()

        async with likenovel_db_session() as db:
            after = [
                {
                    "user_id": user_id,
                    "balance_after": await get_user_event_cash_balance(user_id, db),
                }
                for user_id in user_ids
            ]
        print(json.dumps({"ok": True, "mode": "apply", "granted": granted, "skipped_repeat": sorted(set(user_ids) - set(granted)), "after": after}))
        return 0
    finally:
        await likenovel_db_engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-ids", required=True)
    parser.add_argument("--amount", type=int, required=True)
    parser.add_argument("--grant-key", required=True)
    parser.add_argument("--memo", default="")
    parser.add_argument("--apply", action="store_true")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
