import argparse
import asyncio
import json
import logging

from app.rdb import likenovel_db_engine, likenovel_db_session
import app.schemas.admin as admin_schema
from app.services.admin import admin_ai_reader_service


logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare existing prod/dev users as LikeNovel AI reader agents"
    )
    parser.add_argument("--email-prefix", required=True, help="Existing user email prefix")
    parser.add_argument("--count", type=int, default=100, help="AI reader count")
    parser.add_argument("--schedule-date", default=None, help="YYYY-MM-DD, default=today")
    parser.add_argument("--agent-index-offset", type=int, default=0)
    parser.add_argument("--daily-llm-budget", type=int, default=8)
    parser.add_argument("--dry-run-token", default=None, help="Token from a matching dry-run response")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply DB changes. Without this flag the script only prints a dry-run preview.",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    req_body = admin_schema.PostAiReaderBootstrapReqBody(
        email_prefix=args.email_prefix,
        agent_count=args.count,
        schedule_date=args.schedule_date,
        apply=args.apply,
        allow_partial=args.allow_partial,
        agent_index_offset=args.agent_index_offset,
        daily_llm_budget=args.daily_llm_budget,
        dry_run_token=args.dry_run_token,
    )
    try:
        async with likenovel_db_session() as db:
            result = await admin_ai_reader_service.bootstrap_ai_reader_agents(
                req_body=req_body,
                db=db,
            )
            if not args.apply:
                await db.rollback()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        await likenovel_db_engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
