#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_story_agent_context import db_connect, work_cursor

GENERIC_ROLE_TOKENS = ("주인공", "후배", "아이", "남자", "여자", "오빠", "언니")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DB episode summary와 shadow JSON 비교")
    parser.add_argument("--product-id", type=int, required=True, help="대상 작품 ID")
    parser.add_argument("--shadow-json", type=str, required=True, help="shadow JSON 경로")
    parser.add_argument("--latest-episode-no", type=int, default=0, help="최대 회차 번호")
    return parser.parse_args()


def load_shadow_rows(path: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        try:
            episode_from = int(item.get("episodeFrom") or 0)
            episode_to = int(item.get("episodeTo") or 0)
        except Exception:
            continue
        summary_text = str(item.get("summaryText") or "").strip()
        if episode_from <= 0 or episode_to <= 0 or not summary_text:
            continue
        normalized.append(
            {
                "episodeFrom": episode_from,
                "episodeTo": episode_to,
                "summaryText": summary_text,
            }
        )
    return normalized


def fetch_db_rows(product_id: int, latest_episode_no: int) -> list[dict[str, Any]]:
    conn = db_connect(autocommit=False)
    try:
        where = [
            "product_id = %s",
            "summary_type = 'episode_summary'",
            "is_active = 'Y'",
        ]
        params: list[Any] = [product_id]
        if latest_episode_no > 0:
            where.append("episode_to <= %s")
            params.append(latest_episode_no)
        query = f"""
            SELECT episode_from AS episodeFrom, episode_to AS episodeTo, summary_text AS summaryText
            FROM tb_story_agent_context_summary
            WHERE {" AND ".join(where)}
            ORDER BY episode_to ASC
        """
        with work_cursor(conn) as cur:
            cur.execute(query, tuple(params))
            return list(cur.fetchall())
    finally:
        conn.close()


def count_generic_roles(summary_text: str) -> int:
    text = str(summary_text or "")
    return sum(text.count(token) for token in GENERIC_ROLE_TOKENS)


def main() -> None:
    args = parse_args()
    shadow_rows = load_shadow_rows(args.shadow_json)
    if args.latest_episode_no > 0:
        shadow_rows = [row for row in shadow_rows if int(row.get("episodeTo") or 0) <= args.latest_episode_no]
    db_rows = fetch_db_rows(args.product_id, args.latest_episode_no)

    db_map = {(int(row["episodeFrom"]), int(row["episodeTo"])): row for row in db_rows}
    shadow_map = {(int(row["episodeFrom"]), int(row["episodeTo"])): row for row in shadow_rows}
    all_keys = sorted(set(db_map.keys()) | set(shadow_map.keys()))

    changed_rows: list[dict[str, Any]] = []
    for key in all_keys:
        db_row = db_map.get(key)
        shadow_row = shadow_map.get(key)
        if not db_row or not shadow_row:
            changed_rows.append(
                {
                    "range": key,
                    "changeType": "missing_in_shadow" if db_row and not shadow_row else "missing_in_db",
                }
            )
            continue
        db_text = str(db_row.get("summaryText") or "").strip()
        shadow_text = str(shadow_row.get("summaryText") or "").strip()
        if db_text == shadow_text:
            continue
        changed_rows.append(
            {
                "range": key,
                "changeType": "changed",
                "dbGenericRoleCount": count_generic_roles(db_text),
                "shadowGenericRoleCount": count_generic_roles(shadow_text),
                "dbPreview": db_text[:220],
                "shadowPreview": shadow_text[:220],
            }
        )

    payload = {
        "productId": args.product_id,
        "dbRowCount": len(db_rows),
        "shadowRowCount": len(shadow_rows),
        "changedRowCount": len(changed_rows),
        "dbGenericRoleCount": sum(count_generic_roles(str(row.get("summaryText") or "")) for row in db_rows),
        "shadowGenericRoleCount": sum(count_generic_roles(str(row.get("summaryText") or "")) for row in shadow_rows),
        "sampleChanges": changed_rows[:10],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
