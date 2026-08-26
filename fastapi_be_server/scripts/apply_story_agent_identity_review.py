#!/usr/bin/env python3
"""Operator-authored character identity review, materialized from current DB state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import build_story_agent_context as story_agent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="현재 active 신호에 고정된 캐릭터 identity review 적용"
    )
    parser.add_argument("--product-id", type=int, required=True)
    parser.add_argument(
        "--request-json",
        default="-",
        help="review request JSON 경로. 기본값 '-'는 stdin",
    )
    parser.add_argument("--reviewer", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="지정하지 않으면 transaction을 rollback하는 dry-run",
    )
    return parser.parse_args()


def load_request(path: str) -> dict[str, object]:
    raw_text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw_text)
    if not isinstance(payload, dict):
        raise ValueError("identity review request JSON must be an object")
    return payload


def _build_preview_rows(
    cur,
    *,
    product_id: int,
    signal_rows: list[dict],
    review_document: dict[str, object],
) -> list[dict[str, object]]:
    old_inventory_map = story_agent.fetch_active_character_inventory_map(
        cur=cur,
        product_id=product_id,
        summary_type="character_inventory_v3",
    )
    locked_protagonist_rows = [
        {
            **dict(payload or {}),
            "canonical_character_key": str(
                dict(payload or {}).get("canonical_character_key") or scope_key
            ),
        }
        for scope_key, payload in old_inventory_map.items()
        if str(dict(payload or {}).get("work_role") or "") == "main_protagonist"
    ]
    rows = story_agent.aggregate_character_inventory_v3_rows(
        signal_rows,
        locked_protagonist_rows=locked_protagonist_rows,
        character_identity_review=review_document,
    )
    return story_agent.reconcile_character_inventory_v3_scope_keys(
        rows,
        old_inventory_map=old_inventory_map,
    )


def _validate_review_result(
    *,
    review_document: dict[str, object],
    inventory_map: dict[str, dict[str, object]],
    validate_retirements: bool = True,
) -> None:
    for operation in list(review_document.get("operations") or []):
        target_scope_key = str(operation.get("target_scope_key") or "").strip()
        target = dict(inventory_map.get(target_scope_key) or {})
        if not target:
            raise ValueError(
                f"review target missing after reaggregation: {target_scope_key}"
            )
        if operation.get("force_main_protagonist") is True and str(
            target.get("work_role") or ""
        ) != "main_protagonist":
            raise ValueError(
                f"reviewed protagonist role missing: {target_scope_key}"
            )
        if operation.get("anonymous_protagonist") is True and (
            bool(target.get("public_chat_eligible"))
            or bool(target.get("public_slot_eligible"))
        ):
            raise ValueError(
                f"anonymous protagonist became publicly eligible: {target_scope_key}"
            )
        if not validate_retirements or str(operation.get("kind") or "") not in {
            "merge_active_scopes",
            "retire_active_scope",
        }:
            continue
        for retired_scope_key in set(
            str(value or "").strip()
            for value in list(operation.get("member_scope_keys") or [])
        ) - {target_scope_key, ""}:
            retired = dict(inventory_map.get(retired_scope_key) or {})
            if not retired or bool(retired.get("public_chat_eligible")) or bool(
                retired.get("public_slot_eligible")
            ):
                raise ValueError(
                    f"reviewed retired scope remains eligible: {retired_scope_key}"
                )


def run_identity_review(
    *,
    product_id: int,
    request: dict[str, object],
    reviewer_id: str,
    apply: bool,
) -> dict[str, Any]:
    with story_agent.product_lock_connection(product_id) as lock_connection:
        if lock_connection is None:
            raise RuntimeError(f"story-agent product lock busy: {product_id}")
        conn = story_agent.db_connect()
        try:
            with story_agent.work_cursor(conn) as cur:
                signal_rows = story_agent.fetch_active_character_asset_summary_rows(
                    cur=cur,
                    product_id=product_id,
                    summary_type="episode_character_signals",
                )
                review_document = story_agent.materialize_character_identity_review_document(
                    cur,
                    product_id=product_id,
                    request=request,
                    reviewer_id=reviewer_id,
                    signal_rows=signal_rows,
                )
                preview_rows = _build_preview_rows(
                    cur,
                    product_id=product_id,
                    signal_rows=signal_rows,
                    review_document=review_document,
                )
                preview_map = {
                    str(row.get("canonical_character_key") or "").strip(): row
                    for row in preview_rows
                    if str(row.get("canonical_character_key") or "").strip()
                }
                _validate_review_result(
                    review_document=review_document,
                    inventory_map=preview_map,
                    validate_retirements=False,
                )
                review_summary_id = None
                inserted_count = 0
                reused_count = 0
                if apply:
                    review_summary_id, _, review_document = (
                        story_agent.upsert_character_identity_review(
                            cur,
                            product_id=product_id,
                            request=request,
                            reviewer_id=reviewer_id,
                            signal_rows=signal_rows,
                        )
                    )
                    inserted_count, reused_count = (
                        story_agent.build_character_inventory_v3_summaries_from_signal_rows(
                            cur,
                            product_id=product_id,
                            signal_rows=signal_rows,
                            character_identity_review=review_document,
                        )
                    )
                    story_agent.assert_story_agent_foundation_invariants(
                        cur,
                        product_id=product_id,
                        require_signal_coverage=False,
                    )
                    persisted_inventory_map = (
                        story_agent.fetch_active_character_inventory_map(
                            cur=cur,
                            product_id=product_id,
                            summary_type="character_inventory_v3",
                        )
                    )
                    _validate_review_result(
                        review_document=review_document,
                        inventory_map=persisted_inventory_map,
                    )
                    conn.commit()
                else:
                    conn.rollback()
                reviewed_scope_keys = {
                    str(value or "").strip()
                    for operation in list(
                        review_document.get("operations") or []
                    )
                    for value in [
                        operation.get("target_scope_key"),
                        *list(operation.get("member_scope_keys") or []),
                    ]
                    if str(value or "").strip()
                }
                return {
                    "mode": "apply" if apply else "dry-run",
                    "productId": product_id,
                    "reviewSummaryId": review_summary_id,
                    "reviewDigest": str(
                        review_document.get("review_digest") or ""
                    ),
                    "operationIds": [
                        str(operation.get("operation_id") or "")
                        for operation in list(
                            review_document.get("operations") or []
                        )
                    ],
                    "preview": [
                        {
                            "scopeKey": str(
                                row.get("canonical_character_key") or ""
                            ),
                            "displayName": str(row.get("display_name") or ""),
                            "workRole": str(row.get("work_role") or ""),
                            "publicChatEligible": bool(
                                row.get("public_chat_eligible")
                            ),
                            "continuityStatus": str(
                                row.get("continuity_status") or ""
                            ),
                        }
                        for row in preview_rows
                        if str(row.get("canonical_character_key") or "").strip()
                        in reviewed_scope_keys
                    ],
                    "insertedInventoryRows": inserted_count,
                    "reusedInventoryRows": reused_count,
                }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def main() -> None:
    args = parse_args()
    result = run_identity_review(
        product_id=args.product_id,
        request=load_request(args.request_json),
        reviewer_id=args.reviewer,
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
