import argparse
import asyncio
import logging
import socket
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.const import settings
from app.rdb import likenovel_db_engine, likenovel_db_session
from app.services.ai.reader_agent_session_service import ensure_reader_daily_schedules
from app.services.ai.reader_agent_worker_service import (
    AI_READER_WORKER_ENABLED_ENV,
    ensure_reader_worker_schema_ready_once,
    is_reader_worker_enabled,
    run_reader_worker_cycle,
)


logger = logging.getLogger(__name__)


async def set_ai_reader_worker_db_timezone(db) -> None:
    await db.execute(text("set time_zone = '+09:00'"))


async def ensure_reader_daily_schedules_for_worker(db) -> dict[str, int]:
    today = datetime.now(ZoneInfo(settings.KOREA_TIMEZONE)).date()
    return await ensure_reader_daily_schedules(
        db,
        schedule_dates=[today, today + timedelta(days=1)],
        limit=2000,
    )


def should_ensure_reader_daily_schedules(
    *,
    last_ensured_at: float | None,
    now_monotonic: float,
    interval_seconds: float,
) -> bool:
    if last_ensured_at is None:
        return True
    return now_monotonic - last_ensured_at >= interval_seconds


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LikeNovel AI reader worker")
    parser.add_argument("--worker-id", default=f"ai-reader-{socket.gethostname()}")
    parser.add_argument("--session-limit", type=int, default=10)
    parser.add_argument("--action-limit", type=int, default=50)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    parser.add_argument("--schedule-ensure-interval-seconds", type=float, default=300.0)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    if not is_reader_worker_enabled():
        logger.warning(
            "ai reader worker disabled; set %s=Y to run",
            AI_READER_WORKER_ENABLED_ENV,
        )
        return

    try:
        async with likenovel_db_session() as db:
            await set_ai_reader_worker_db_timezone(db)
            await ensure_reader_worker_schema_ready_once(db)
            await db.commit()

        last_schedule_ensured_at: float | None = None
        while True:
            async with likenovel_db_session() as db:
                await set_ai_reader_worker_db_timezone(db)
                now_monotonic = time.monotonic()
                if should_ensure_reader_daily_schedules(
                    last_ensured_at=last_schedule_ensured_at,
                    now_monotonic=now_monotonic,
                    interval_seconds=args.schedule_ensure_interval_seconds,
                ):
                    await ensure_reader_daily_schedules_for_worker(db)
                    last_schedule_ensured_at = now_monotonic
                result = await run_reader_worker_cycle(
                    db,
                    worker_id=args.worker_id,
                    session_limit=args.session_limit,
                    action_limit=args.action_limit,
                )
                await db.commit()
            logger.info("ai reader worker cycle completed", extra={"result": result})
            if args.once:
                return
            await asyncio.sleep(args.interval_seconds)
    finally:
        await likenovel_db_engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
