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

from app.services.websochat.character_chat_product_policy import (  # noqa: E402
    build_correlated_character_chat_product_policy_sql,
    is_character_chat_product_eligible,
)


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


def build_product_query(*, product_ids: list[int], limit: int, open_only: bool, batch_cohort_sql: str | None = None) -> tuple[str, list[Any]]:
    where = ["1 = 1"]
    params: list[Any] = []
    if open_only:
        where.extend(
            [
                "p.price_type IN ('free', 'paid')",
                "p.status_code IN ('ongoing', 'end')" if batch_cohort_sql else "p.status_code = 'ongoing'",
                "p.open_yn = 'Y'",
                "COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'",
            ]
        )
    if product_ids:
        placeholders = ", ".join(["%s"] * len(product_ids))
        where.append(f"p.product_id IN ({placeholders})")
        params.extend(product_ids)
    limit_sql = " LIMIT %s" if limit > 0 else ""
    if limit > 0:
        params.append(int(limit))
    character_chat_policy_sql = build_correlated_character_chat_product_policy_sql(
        product_alias="p",
        episode_alias="cohort_episode",
    )
    if batch_cohort_sql:
        character_chat_policy_sql = f"AND {batch_cohort_sql}"
        where.append("COALESCE(p.blind_yn, 'N') = 'N'")
    return (
        f"""
        SELECT
            p.product_id,
            p.title,
            p.price_type,
            p.status_code,
            COALESCE(cp.context_status, '') AS context_status,
            COALESCE(cp.total_episode_count, 0) AS total_episode_count,
            COALESCE(cp.ready_episode_count, 0) AS ready_episode_count,
            CASE
                WHEN 1 = 1 {character_chat_policy_sql} THEN 1
                ELSE 0
            END AS characterChatEligible
        FROM tb_product p
        LEFT JOIN tb_story_agent_context_product cp
          ON cp.product_id = p.product_id
        WHERE {" AND ".join(where)}
        ORDER BY p.product_id ASC
        {limit_sql}
        """,
        params,
    )


def fetch_product_rows(cur, *, product_ids: list[int], limit: int, open_only: bool, batch_cohort_sql: str | None = None) -> list[dict[str, Any]]:
    query, params = build_product_query(product_ids=product_ids, limit=limit, open_only=open_only, batch_cohort_sql=batch_cohort_sql)
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
    ready_without_main_protagonist_product_ids: list[int] = []
    out_of_cohort_hold_product_ids: list[int] = []
    automatic_scope_counts: Counter[str] = Counter()

    for row in rows:
        if "automatic_policy" in row:
            automatic_scope_counts["products"] += 1
            for field in ("selected_scope_keys", "rp_scope_keys", "scene_scope_keys", "blockers", "residual_rp_scope_keys", "residual_scene_scope_keys"):
                automatic_scope_counts[field] += len(row["automatic_policy"].get(field) or [])
        context_status_counts[str(row.get("context_status") or "missing")] += 1
        readiness = dict(row.get("character_chat_asset_readiness") or {})
        character_chat_status = str(
            readiness.get("character_chat_status") or "missing"
        )
        out_of_cohort_hold = (
            character_chat_status == "hold"
            and not is_character_chat_product_eligible(row)
        )
        action_plan = (
            ["out_of_cohort_hold"]
            if out_of_cohort_hold
            else build_asset_action_plan(row)
        )
        row["assetActionPlan"] = action_plan
        product_id = int(row.get("product_id") or 0)
        if out_of_cohort_hold:
            if product_id > 0:
                out_of_cohort_hold_product_ids.append(product_id)
        else:
            for action in action_plan:
                action_plan_counts[str(action)] += 1
                if product_id > 0:
                    product_ids_by_action.setdefault(str(action), []).append(
                        product_id
                    )
        character_chat_status_counts[character_chat_status] += 1
        if character_chat_status == "ready":
            ready_product_ids.append(product_id)
            if not list(readiness.get("main_protagonist_scope_keys") or []):
                ready_without_main_protagonist_product_ids.append(product_id)
        elif character_chat_status == "hold":
            hold_product_ids.append(product_id)
        for reason, count in dict(readiness.get("block_reason_counts") or {}).items():
            block_reason_counts[str(reason)] += int(count or 0)
        public_candidate_total += int(readiness.get("public_candidate_count") or 0)
        ready_public_candidate_total += int(readiness.get("ready_public_candidate_count") or 0)
        public_slot_ready_total += int(readiness.get("public_slot_ready_count") or 0)

    return {
        "productCount": len(rows),
        "automaticPolicyCounts": dict(automatic_scope_counts),
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
        "readyWithoutMainProtagonistCount": len(
            [pid for pid in ready_without_main_protagonist_product_ids if pid > 0]
        ),
        "readyWithoutMainProtagonistProductIds": sorted(
            pid for pid in ready_without_main_protagonist_product_ids if pid > 0
        )[:20],
        "outOfCohortHoldCount": len(out_of_cohort_hold_product_ids),
        "outOfCohortHoldProductIds": sorted(set(out_of_cohort_hold_product_ids))[
            :20
        ],
        "holdProductIdsSample": sorted(pid for pid in hold_product_ids if pid > 0)[:20],
    }


def build_asset_action_plan(row: dict[str, Any]) -> list[str]:
    readiness = dict(row.get("character_chat_asset_readiness") or {})
    status = str(readiness.get("character_chat_status") or "missing")
    context_status = str(row.get("context_status") or "").strip()
    if "automatic_policy" in row:
        policy = row["automatic_policy"]
        actions = []
        if context_status != "ready":
            actions.append("build_story_context_foundation")
        if policy["blockers"]:
            actions.append("repair_character_inventory")
        else:
            if policy["rp_scope_keys"]:
                actions.append("generate_rp_profile_examples")
            if policy["scene_scope_keys"]:
                actions.append("generate_episode_scene_extraction")
        return actions or (["no_public_character_candidate"] if status == "none_eligible" else ["ready"])
    block_counts = dict(readiness.get("block_reason_counts") or {})
    has_legacy_scope_mismatch = bool(
        readiness.get("legacy_profile_scope_key_mismatch_scope_keys")
        or readiness.get("legacy_examples_scope_key_mismatch_scope_keys")
        or int(block_counts.get("legacy_profile_scope_key_mismatch") or 0) > 0
        or int(block_counts.get("legacy_examples_scope_key_mismatch") or 0) > 0
    )
    has_identity_continuity_ambiguity = (
        bool(readiness.get("blocking_continuity_ambiguous_scope_keys"))
        if "blocking_continuity_ambiguous_scope_keys" in readiness
        else bool(
            readiness.get("continuity_ambiguous_scope_keys")
            or int(block_counts.get("identity_continuity_ambiguous") or 0) > 0
        )
    )
    if status == "ready" and not (
        has_legacy_scope_mismatch or has_identity_continuity_ambiguity
    ):
        return ["ready"]
    actions: list[str] = []
    if context_status != "ready":
        actions.append("build_story_context_foundation")
    if status == "none_eligible":
        if not actions:
            actions.append("no_public_character_candidate")
        return actions
    if (
        status == "failed"
        or readiness.get("malformed_inventory_scope_keys")
        or has_identity_continuity_ambiguity
    ):
        actions.append("repair_character_inventory")

    if has_legacy_scope_mismatch:
        actions.append("rebuild_rp_assets_with_v3_scope")
    if (
        int(block_counts.get("missing_profile") or 0) > 0
        or int(block_counts.get("missing_examples") or 0) > 0
    ):
        actions.append("generate_rp_profile_examples")
    if int(block_counts.get("missing_usable_scene") or 0) > 0:
        actions.append("generate_episode_scene_extraction")
    return list(dict.fromkeys(actions or ["inspect_character_chat_assets"]))


def build_audit_exit_code(
    summary: dict[str, Any],
    *,
    fail_on_actionable: bool,
) -> int:
    if not fail_on_actionable:
        return 0
    non_actionable = {"ready", "no_public_character_candidate"}
    return int(
        any(
            action not in non_actionable and int(count or 0) > 0
            for action, count in dict(summary.get("actionPlanCounts") or {}).items()
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="dev DB character_chat asset readiness read-only audit")
    parser.add_argument("--env-file", default=".env", help="DB env file. Values are loaded but never printed.")
    parser.add_argument("--product-id", action="append", type=int, default=[], help="Specific product_id. Repeatable.")
    parser.add_argument("--limit", type=int, default=0, help="Max products to audit. 0 means no limit.")
    parser.add_argument("--include-closed", action="store_true", help="Include closed/private/non-ongoing products.")
    parser.add_argument("--scheduled", action="store_true", help="Limit automatic repair actions to the generator's current target scopes; retain full readiness diagnostics.")
    parser.add_argument("--scheduled-action-ids", action="store_true", help="Read-only v1|repair-product-ids|blocked-product-ids manifest for the batch SQL.")
    parser.add_argument("--out", default="", help="Optional JSONL detail output path.")
    parser.add_argument("--summary-out", default="", help="Optional JSON summary output path.")
    parser.add_argument(
        "--fail-on-actionable",
        action="store_true",
        help="Exit 1 when the audit finds an actionable character-chat asset gap.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scheduled_policy_mode = bool(args.scheduled or args.scheduled_action_ids)
    load_env_file(Path(args.env_file))
    story_agent = load_story_agent_module()
    rows: list[dict[str, Any]] = []
    repair_ids: list[int] = []
    blocked_ids: list[int] = []
    with story_agent.db_connect(autocommit=True) as conn:
        with conn.cursor() as cur:
            product_rows = fetch_product_rows(
                cur,
                product_ids=[int(value) for value in args.product_id if int(value) > 0],
                limit=max(int(args.limit or 0), 0),
                open_only=not bool(args.include_closed),
                batch_cohort_sql=(story_agent.build_story_agent_collection_cohort_sql(product_alias="p", episode_alias="cohort_episode") if scheduled_policy_mode else None),
            )
            for product in product_rows:
                product_id = int(product.get("product_id") or 0)
                if scheduled_policy_mode and (not is_character_chat_product_eligible(product) or product.get("context_status") == "disabled"):
                    continue
                readiness = story_agent.fetch_character_chat_asset_readiness_verification(
                    cur,
                    product_id=product_id,
                    story_context_status=str(product.get("context_status") or ""),
                    total_episode_count=int(product.get("total_episode_count") or 0),
                )
                row = {**product, "character_chat_asset_readiness": readiness}
                if scheduled_policy_mode:
                    policy = story_agent.build_scheduled_character_asset_policy(
                        inventory_map=story_agent.fetch_active_character_inventory_map(
                            cur=cur, product_id=product_id, summary_type="character_inventory_v3",
                        ),
                        signal_rows=story_agent.fetch_active_character_asset_summary_rows(
                            cur=cur, product_id=product_id, summary_type="episode_character_signals",
                        ),
                        readiness=readiness,
                    )
                    row["automatic_policy"] = policy
                    if product_id <= 0:
                        raise ValueError("scheduled manifest requires a positive product id")
                    if policy["blockers"]:
                        blocked_ids.append(product_id)
                    elif policy["repairable"]:
                        repair_ids.append(product_id)
                rows.append(row)

    if args.scheduled_action_ids:
        print("v1|" + ",".join(map(str, [0, *repair_ids])) + "|" + ",".join(map(str, [0, *blocked_ids])))
        return 0

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
    return build_audit_exit_code(
        summary,
        fail_on_actionable=bool(args.fail_on_actionable),
    )


if __name__ == "__main__":
    raise SystemExit(main())
