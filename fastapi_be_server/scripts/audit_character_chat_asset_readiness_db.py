#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def load_env_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    loaded: list[str] = []
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            continue
        os.environ[key] = value.strip().strip('"').strip("'")
        loaded.append(key)
    return loaded


def load_story_agent_module():
    previous_cwd = Path.cwd()
    import_cwd = Path(os.getenv("LIKENOVEL_AUDIT_LOG_CWD", "/tmp/likenovel-character-chat-audit"))
    Path(import_cwd, "logs", "data").mkdir(parents=True, exist_ok=True)
    Path(import_cwd, "logs", "error").mkdir(parents=True, exist_ok=True)
    os.chdir(import_cwd)
    try:
        return importlib.import_module("build_story_agent_context")
    finally:
        os.chdir(previous_cwd)


def build_product_query(*, product_ids: list[int], limit: int, open_only: bool) -> tuple[str, list[Any]]:
    where = ["1 = 1"]
    params: list[Any] = []
    if open_only:
        where.extend(
            [
                "p.price_type IN ('free', 'paid')",
                "p.status_code = 'ongoing'",
                "p.open_yn = 'Y'",
            ]
        )
    if product_ids:
        placeholders = ", ".join(["%s"] * len(product_ids))
        where.append(f"p.product_id IN ({placeholders})")
        params.extend(product_ids)
    limit_sql = " LIMIT %s" if limit > 0 else ""
    if limit > 0:
        params.append(int(limit))
    return (
        f"""
        SELECT
            p.product_id,
            p.title,
            p.price_type,
            p.status_code,
            COALESCE(cp.context_status, '') AS context_status,
            COALESCE(cp.total_episode_count, 0) AS total_episode_count,
            COALESCE(cp.ready_episode_count, 0) AS ready_episode_count
        FROM tb_product p
        LEFT JOIN tb_story_agent_context_product cp
          ON cp.product_id = p.product_id
        WHERE {" AND ".join(where)}
        ORDER BY p.product_id ASC
        {limit_sql}
        """,
        params,
    )


def fetch_product_rows(cur, *, product_ids: list[int], limit: int, open_only: bool) -> list[dict[str, Any]]:
    query, params = build_product_query(product_ids=product_ids, limit=limit, open_only=open_only)
    cur.execute(query, params)
    return [dict(row) for row in cur.fetchall()]


def summarize_verifications(rows: list[dict[str, Any]]) -> dict[str, Any]:
    context_status_counts: Counter[str] = Counter()
    character_chat_status_counts: Counter[str] = Counter()
    block_reason_counts: Counter[str] = Counter()
    action_plan_counts: Counter[str] = Counter()
    product_ids_by_action: dict[str, list[int]] = {}
    ready_product_ids: list[int] = []
    hold_product_ids: list[int] = []
    public_candidate_total = 0
    ready_public_candidate_total = 0
    public_slot_ready_total = 0

    for row in rows:
        context_status_counts[str(row.get("context_status") or "missing")] += 1
        readiness = dict(row.get("character_chat_asset_readiness") or {})
        action_plan = build_asset_action_plan(row)
        row["assetActionPlan"] = action_plan
        for action in action_plan:
            action_plan_counts[str(action)] += 1
            product_id = int(row.get("product_id") or 0)
            if product_id > 0:
                product_ids_by_action.setdefault(str(action), []).append(product_id)
        character_chat_status = str(readiness.get("character_chat_status") or "missing")
        character_chat_status_counts[character_chat_status] += 1
        product_id = int(row.get("product_id") or 0)
        if character_chat_status == "ready":
            ready_product_ids.append(product_id)
        elif character_chat_status == "hold":
            hold_product_ids.append(product_id)
        for reason, count in dict(readiness.get("block_reason_counts") or {}).items():
            block_reason_counts[str(reason)] += int(count or 0)
        public_candidate_total += int(readiness.get("public_candidate_count") or 0)
        ready_public_candidate_total += int(readiness.get("ready_public_candidate_count") or 0)
        public_slot_ready_total += int(readiness.get("public_slot_ready_count") or 0)

    return {
        "productCount": len(rows),
        "contextStatusCounts": dict(sorted(context_status_counts.items())),
        "characterChatStatusCounts": dict(sorted(character_chat_status_counts.items())),
        "blockReasonCounts": dict(sorted(block_reason_counts.items())),
        "actionPlanCounts": dict(sorted(action_plan_counts.items())),
        "candidateProductIdsByAction": {
            action: sorted(set(product_ids))[:10]
            for action, product_ids in sorted(product_ids_by_action.items())
        },
        "publicCandidateTotal": public_candidate_total,
        "readyPublicCandidateTotal": ready_public_candidate_total,
        "publicSlotReadyTotal": public_slot_ready_total,
        "readyProductIds": sorted(pid for pid in ready_product_ids if pid > 0),
        "holdProductIdsSample": sorted(pid for pid in hold_product_ids if pid > 0)[:20],
    }


def build_asset_action_plan(row: dict[str, Any]) -> list[str]:
    readiness = dict(row.get("character_chat_asset_readiness") or {})
    status = str(readiness.get("character_chat_status") or "missing")
    context_status = str(row.get("context_status") or "").strip()
    if status == "ready":
        return ["ready"]
    actions: list[str] = []
    if context_status != "ready":
        actions.append("build_story_context_foundation")
    if status == "none_eligible":
        if not actions:
            actions.append("no_public_character_candidate")
        return actions
    if status == "failed" or readiness.get("malformed_inventory_scope_keys"):
        actions.append("repair_character_inventory")

    block_counts = dict(readiness.get("block_reason_counts") or {})
    if (
        int(block_counts.get("legacy_profile_scope_key_mismatch") or 0) > 0
        or int(block_counts.get("legacy_examples_scope_key_mismatch") or 0) > 0
    ):
        actions.append("rebuild_rp_assets_with_v3_scope")
    if (
        int(block_counts.get("missing_profile") or 0) > 0
        or int(block_counts.get("missing_examples") or 0) > 0
    ):
        actions.append("generate_rp_profile_examples")
    if int(block_counts.get("missing_usable_scene") or 0) > 0:
        actions.append("generate_episode_scene_extraction")
    return list(dict.fromkeys(actions or ["inspect_character_chat_assets"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="dev DB character_chat asset readiness read-only audit")
    parser.add_argument("--env-file", default=".env", help="DB env file. Values are loaded but never printed.")
    parser.add_argument("--product-id", action="append", type=int, default=[], help="Specific product_id. Repeatable.")
    parser.add_argument("--limit", type=int, default=0, help="Max products to audit. 0 means no limit.")
    parser.add_argument("--include-closed", action="store_true", help="Include closed/private/non-ongoing products.")
    parser.add_argument("--out", default="", help="Optional JSONL detail output path.")
    parser.add_argument("--summary-out", default="", help="Optional JSON summary output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))
    story_agent = load_story_agent_module()
    rows: list[dict[str, Any]] = []
    with story_agent.db_connect(autocommit=True) as conn:
        with conn.cursor() as cur:
            product_rows = fetch_product_rows(
                cur,
                product_ids=[int(value) for value in args.product_id if int(value) > 0],
                limit=max(int(args.limit or 0), 0),
                open_only=not bool(args.include_closed),
            )
            for product in product_rows:
                product_id = int(product.get("product_id") or 0)
                readiness = story_agent.fetch_character_chat_asset_readiness_verification(
                    cur,
                    product_id=product_id,
                    story_context_status=str(product.get("context_status") or ""),
                    total_episode_count=int(product.get("total_episode_count") or 0),
                )
                rows.append({**product, "character_chat_asset_readiness": readiness})

    summary = summarize_verifications(rows)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )
        summary["out"] = str(out_path)
    if args.summary_out:
        summary_path = Path(args.summary_out)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["summaryOut"] = str(summary_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
