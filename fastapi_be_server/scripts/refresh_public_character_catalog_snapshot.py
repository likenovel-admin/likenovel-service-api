#!/usr/bin/env python3
"""Build and atomically publish the public character catalog ranking."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import text


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.rdb import likenovel_db_engine, likenovel_db_session  # noqa: E402
from app.services.product.main_character_slot_service import (  # noqa: E402
    _load_public_character_catalog_base,
)
from app.services.product.public_character_catalog_snapshot_service import (  # noqa: E402
    PUBLIC_CHARACTER_CATALOG_SCOPES,
    PUBLIC_CHARACTER_CATALOG_SNAPSHOT_LOCK_NAME,
    cleanup_old_public_character_catalog_snapshots,
    publish_public_character_catalog_snapshot,
)


async def _build_catalogs() -> dict[str, list[dict]]:
    async with likenovel_db_engine.connect() as read_connection:
        read_connection = await read_connection.execution_options(
            isolation_level="REPEATABLE READ"
        )
        async with read_connection.begin():
            catalogs = {}
            for adult_yn in PUBLIC_CHARACTER_CATALOG_SCOPES:
                catalogs[adult_yn] = await _load_public_character_catalog_base(
                    adult_yn=adult_yn,
                    db=read_connection,
                )
            return catalogs


def _is_snapshot_lock_acquired(lock_value) -> bool:
    if lock_value is None:
        raise RuntimeError("GET_LOCK returned NULL")
    try:
        normalized_value = int(lock_value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"unexpected GET_LOCK result: {lock_value!r}"
        ) from exc
    if normalized_value == 0:
        return False
    if normalized_value == 1:
        return True
    raise RuntimeError(f"unexpected GET_LOCK result: {lock_value!r}")


async def refresh_public_character_catalog_snapshot() -> dict[str, object]:
    async with likenovel_db_engine.connect() as lock_connection:
        lock_result = await lock_connection.execute(
            text("SELECT GET_LOCK(:lock_name, 0) AS locked"),
            {"lock_name": PUBLIC_CHARACTER_CATALOG_SNAPSHOT_LOCK_NAME},
        )
        lock_acquired = _is_snapshot_lock_acquired(lock_result.scalar())
        await lock_connection.commit()
        if not lock_acquired:
            return {"status": "skipped", "reason": "lock_busy"}

        try:
            catalogs = await _build_catalogs()
            async with likenovel_db_session() as db:
                published = await publish_public_character_catalog_snapshot(
                    catalogs=catalogs,
                    db=db,
                )
                await cleanup_old_public_character_catalog_snapshots(db=db)
            return {"status": "published", **published}
        finally:
            await lock_connection.execute(
                text("SELECT RELEASE_LOCK(:lock_name)"),
                {"lock_name": PUBLIC_CHARACTER_CATALOG_SNAPSHOT_LOCK_NAME},
            )
            await lock_connection.commit()


async def main() -> int:
    try:
        result = await refresh_public_character_catalog_snapshot()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "errorType": type(exc).__name__,
                    "error": str(exc)[:500],
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
