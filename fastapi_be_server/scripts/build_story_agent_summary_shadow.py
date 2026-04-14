#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from httpx import AsyncClient

from build_story_agent_context import (
    EPISODE_SUMMARY_TIMEOUT_SECONDS,
    EPISODE_SUMMARY_FORMAT_VERSION,
    db_connect,
    generate_episode_summary_text,
    normalize_episode_html,
    work_cursor,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="스토리 에이전트 shadow episode summary JSON 생성")
    parser.add_argument("--product-id", type=int, required=True, help="대상 작품 ID")
    parser.add_argument("--out", type=str, required=True, help="출력 JSON 경로")
    parser.add_argument("--latest-episode-no", type=int, default=0, help="최대 회차 번호")
    parser.add_argument("--episode-no", type=int, action="append", dest="episode_nos", help="특정 회차만 생성")
    parser.add_argument("--verbose", action="store_true", help="상세 로그 출력")
    return parser.parse_args()


def fetch_target_rows(
    *,
    product_id: int,
    latest_episode_no: int,
    episode_nos: list[int] | None,
) -> list[dict[str, Any]]:
    conn = db_connect(autocommit=False)
    try:
        where = [
            "p.product_id = %s",
            "p.price_type = 'free'",
            "p.open_yn = 'Y'",
            "pe.use_yn = 'Y'",
            "pe.open_yn = 'Y'",
        ]
        params: list[Any] = [product_id]
        if latest_episode_no > 0:
            where.append("pe.episode_no <= %s")
            params.append(latest_episode_no)
        if episode_nos:
            placeholders = ", ".join(["%s"] * len(episode_nos))
            where.append(f"pe.episode_no IN ({placeholders})")
            params.extend(sorted(set(episode_nos)))

        query = f"""
            SELECT
                p.product_id,
                p.title,
                pe.episode_id,
                pe.episode_no,
                pe.episode_title,
                pe.episode_content
            FROM tb_product p
            JOIN tb_product_episode pe
              ON pe.product_id = p.product_id
            WHERE {" AND ".join(where)}
            ORDER BY pe.episode_no ASC
        """
        with work_cursor(conn) as cur:
            cur.execute(query, tuple(params))
            return list(cur.fetchall())
    finally:
        conn.close()


async def build_shadow_rows(
    rows: list[dict[str, Any]],
    *,
    verbose: bool,
) -> list[dict[str, Any]]:
    timeout = EPISODE_SUMMARY_TIMEOUT_SECONDS
    async with AsyncClient(timeout=timeout) as client:
        payload_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized_text = normalize_episode_html(str(row.get("episode_content") or ""))
            if not normalized_text:
                if verbose:
                    print(f"[shadow-skip] episode_id={row.get('episode_id')} reason=empty_normalized_text")
                continue
            summary_text, summary_meta = await generate_episode_summary_text(
                client=client,
                row=row,
                normalized_text=normalized_text,
                verbose=verbose,
            )
            payload_rows.append(
                {
                    "productId": int(row["product_id"]),
                    "episodeId": int(row["episode_id"]),
                    "episodeFrom": int(row["episode_no"]),
                    "episodeTo": int(row["episode_no"]),
                    "scopeKey": f"episode:{int(row['episode_id'])}",
                    "summaryText": summary_text,
                    "meta": summary_meta,
                }
            )
        return payload_rows


async def main() -> None:
    args = parse_args()
    rows = fetch_target_rows(
        product_id=args.product_id,
        latest_episode_no=args.latest_episode_no,
        episode_nos=args.episode_nos,
    )
    shadow_rows = await build_shadow_rows(rows, verbose=args.verbose)
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "productId": args.product_id,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "story_agent_shadow_summary",
        "summaryFormatVersion": EPISODE_SUMMARY_FORMAT_VERSION,
        "rowCount": len(shadow_rows),
        "rows": shadow_rows,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(output_path), "rowCount": len(shadow_rows)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
