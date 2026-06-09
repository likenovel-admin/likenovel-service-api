import asyncio
import json
import logging

from app.rdb import likenovel_db_engine, likenovel_db_session
from app.services.common.ai_provider_health_service import run_ai_provider_health_checks


logger = logging.getLogger(__name__)


async def run() -> dict:
    try:
        async with likenovel_db_session() as db:
            return await run_ai_provider_health_checks(db)
    finally:
        await likenovel_db_engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(run())
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
