#!/usr/bin/env python3
"""배너 목록 필터/정렬 디버깅 스크립트.

목적
- CMS 배너 목록 API와 동일한 서비스 로직을 로컬에서 바로 검증한다.
- 현재 DB 채널, 위치별 배너 분포, 정렬 결과를 빠르게 확인한다.

사용 예시
- python scripts/debug_banner_listing.py --summary
- python scripts/debug_banner_listing.py --position review --compare-sorts
- docker exec likenovel-api python scripts/debug_banner_listing.py --position main-top --sort-by latest_updated
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.const import settings
from app.rdb import likenovel_db_engine, likenovel_db_session
from app.services.admin import admin_event_service

POSITION_CHOICES = [
    "all",
    "main-top",
    "main-mid",
    "main-bot",
    "paid",
    "review",
    "promotion",
    "search",
    "viewer",
]
SORT_CHOICES = ["show_order_asc", "show_order_desc", "latest_updated"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="배너 목록 디버깅")
    parser.add_argument(
        "--position",
        choices=POSITION_CHOICES,
        default="all",
        help="배너 위치 필터",
    )
    parser.add_argument(
        "--sort-by",
        choices=SORT_CHOICES,
        default="show_order_asc",
        help="정렬 기준",
    )
    parser.add_argument("--page", type=int, default=1, help="페이지 번호")
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="조회 개수",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="위치별 배너 분포 요약 출력",
    )
    parser.add_argument(
        "--compare-sorts",
        action="store_true",
        help="선택한 위치에 대해 모든 정렬 결과를 순서대로 출력",
    )
    return parser.parse_args()


def mask_db_target() -> str:
    return f"{settings.DB_USER_ID}@{settings.DB_IP}:{settings.DB_PORT}/likenovel"


def format_position(position: str | None, division: str | None) -> str:
    if position == "main" and division:
        return f"{position}-{division}"
    return position or "-"


async def print_summary() -> None:
    async with likenovel_db_session() as db:
        result = await db.execute(
            text(
                """
                SELECT
                    position,
                    COALESCE(division, '') AS division,
                    COUNT(*) AS cnt,
                    MIN(show_order) AS min_order,
                    MAX(show_order) AS max_order,
                    MAX(COALESCE(updated_date, created_date)) AS latest_dt
                FROM tb_carousel_banner
                GROUP BY position, division
                ORDER BY position, division
                """
            )
        )
        print("[summary]")
        for row in result.mappings():
            division = row["division"] or "-"
            print(
                f"- {row['position']}/{division}: "
                f"count={row['cnt']} "
                f"show_order={row['min_order']}..{row['max_order']} "
                f"latest={row['latest_dt']}"
            )


async def print_listing(position: str, sort_by: str, page: int, count: int) -> None:
    normalized_position = None if position == "all" else position
    async with likenovel_db_session() as db:
        response = await admin_event_service.banners_list(
            page=page,
            count_per_page=count,
            position=normalized_position,
            sort_by=sort_by,
            db=db,
        )

    print(
        f"[listing] position={position} sort_by={sort_by} "
        f"page={page} count={count} total={response['total_count']}"
    )
    if not response["results"]:
        print("- no rows")
        return

    for item in response["results"]:
        print(
            f"- id={item['id']} "
            f"slot={format_position(item['position'], item['division'])} "
            f"show_order={item['show_order']} "
            f"updated={item['updated_date']} "
            f"title={item['title']}"
        )


async def main() -> None:
    args = parse_args()

    try:
        print(f"[db] {mask_db_target()}")

        if args.summary:
            await print_summary()
            print("")

        if args.compare_sorts:
            for sort_by in SORT_CHOICES:
                await print_listing(args.position, sort_by, args.page, args.count)
                print("")
            return

        await print_listing(args.position, args.sort_by, args.page, args.count)
    finally:
        await likenovel_db_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
