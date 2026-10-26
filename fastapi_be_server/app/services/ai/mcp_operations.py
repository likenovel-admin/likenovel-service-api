"""CMS operations with fresh eligibility, optimistic guards and durable receipts."""

import asyncio
import copy
import json
import logging
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import text, bindparam
from httpx import AsyncClient

from app.rdb import likenovel_db_session
from app.services.common.ai_model_config import (
    get_model_binding, load_ai_model_snapshot, use_ai_model_snapshot,
    serialize_model_snapshot, deserialize_model_snapshot,
)
from app.schemas.admin import PutDirectRecommendReqBody, PostMainSingleSlotPublishNowReqBody
from app.services.ai import direct_curator_service as curator
from app.services.ai import mcp_policy as policy, mcp_store as store
from app.services.ai.mcp_config import load as load_config

logger = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()
DIRECT_COOLDOWN_DAYS = 7

SINGLE_QUERY = """
    SELECT single_slot_id, slot_key, slot_name, slot_order, product_id,
           summary_text, publish_start_at, publish_end_at
    FROM tb_main_single_slot
    WHERE cancelled_at IS NULL
      AND (publish_end_at IS NULL OR publish_end_at > NOW())
      AND slot_key IN :slot_keys
    ORDER BY slot_key, single_slot_id
"""


def _json(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def _clean(value):
    return json.loads(json.dumps(value, default=_json, ensure_ascii=False))


def _enabled():
    if load_config().get("writes_enabled") is not True:
        raise ValueError("Automatic writes are disabled")


def _snapshot(snapshot_id: str, owner: str) -> dict:
    snapshot = store.get("snapshot:" + snapshot_id, owner)
    if not snapshot or time.time() - snapshot["updated_at"] > 1800:
        raise ValueError("Snapshot is missing or expired; read a fresh snapshot")
    return snapshot


async def single_rows(db, lock=False):
    query = text(SINGLE_QUERY + (" FOR UPDATE" if lock else "")).bindparams(
        bindparam("slot_keys", expanding=True),
    )
    result = await db.execute(query, {"slot_keys": policy.SINGLE_KEYS})
    return _clean([dict(row) for row in result.mappings().all()])


def _direct_cooldown(owner: str, current: list[dict], cycle_date: date) -> dict:
    # A work becomes eligible again on added_date + 7 KST calendar days.
    first_date = cycle_date - timedelta(days=DIRECT_COOLDOWN_DAYS - 1)
    with store.connection() as db:
        rows = db.execute(
            """SELECT job_id,payload FROM receipts
               WHERE owner=? AND status='completed' AND job_id>=? AND job_id<=?
               ORDER BY job_id LIMIT 8""",
            (owner, f"direct:{first_date.isoformat()}", f"direct:{cycle_date.isoformat()}"),
        ).fetchall()
    if len(rows) > DIRECT_COOLDOWN_DAYS:
        raise ValueError("Direct cooldown history is inconsistent; nothing was written")
    added_at = {}
    for job_id, raw in rows:
        try:
            added_date = date.fromisoformat(job_id.removeprefix("direct:"))
            payload = json.loads(raw)
            if job_id != f"direct:{added_date.isoformat()}" or payload["kind"] != "direct":
                raise ValueError("Invalid direct receipt")
            before, after = payload["before"], payload["after"]
            if not isinstance(before, list) or not isinstance(after, list) or not before:
                raise ValueError("Invalid direct receipt slots")
            before_by_id = {row["slot_id"]: row for row in before}
            after_by_id = {row["slot_id"]: row for row in after}
            if (
                len(before_by_id) != len(before) or len(after_by_id) != len(after)
                or before_by_id.keys() != after_by_id.keys()
            ):
                raise ValueError("Invalid direct receipt slot IDs")
            for slot_id, old in before_by_id.items():
                new = after_by_id[slot_id]
                if (
                    type(slot_id) is not int or slot_id <= 0
                    or {k: v for k, v in old.items() if k != "product_ids"}
                    != {k: v for k, v in new.items() if k != "product_ids"}
                ):
                    raise ValueError("Invalid direct receipt metadata")
                if not isinstance(old["product_ids"], list) or not isinstance(new["product_ids"], list):
                    raise ValueError("Invalid direct receipt product IDs")
                old_ids = policy.validate_ids(old["product_ids"]) if old["product_ids"] else []
                new_ids = policy.validate_ids(new["product_ids"]) if new["product_ids"] else []
                for product_id in set(new_ids) - set(old_ids):
                    added_at[product_id] = added_date
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Direct cooldown history is invalid; nothing was written") from exc
    current_ids = {product_id for row in current for product_id in row["product_ids"]}
    return {
        "cooldown_days": DIRECT_COOLDOWN_DAYS,
        "date_basis": "Asia/Seoul calendar date; eligible on added_date + 7 days",
        "history_source": "This admin's completed MCP direct receipts",
        "legacy_local_proposal_history": "unknown; not imported",
        "recently_added": [
            {
                "product_id": product_id, "last_added_date": added_date.isoformat(),
                "eligible_again_on": (added_date + timedelta(days=DIRECT_COOLDOWN_DAYS)).isoformat(),
            }
            for product_id, added_date in sorted(added_at.items())
        ],
        "avoid_reproposal_product_ids": sorted(set(added_at) - current_ids),
    }


async def direct_snapshot(owner: str) -> dict:
    async with likenovel_db_session() as db:
        result = await curator.build_scheduled_snapshot(db)
        # Full candidate records are required for authoritative write eligibility.
        candidates = await curator._load_candidates(db)
    if not result["slot_snapshot_stable"] or result["objective_checks_error"]:
        raise ValueError("Direct slot snapshot is unstable")
    snapshot_id = uuid.uuid4().hex
    store.save("snapshot:" + snapshot_id, owner, "snapshot", {
        "kind": "direct", "slots": result["slots"], "candidates": candidates,
    })
    result.update(
        mode="automatic_authorized",
        snapshot_id=snapshot_id,
        standing_authorization=True,
        writes_enabled=load_config().get("writes_enabled", False),
        cadence="Daily 10:00 Asia/Seoul; change only with evidence",
        rotation_policy=_direct_cooldown(owner, result["slots"], datetime.now(policy.KST).date()),
    )
    return result


async def apply_direct(owner: str, snapshot_id: str, updates: list[dict]) -> dict:
    from app.services.admin import admin_recommend_service

    _enabled()
    job_id = policy.cycle_key("direct")
    snapshot = _snapshot(snapshot_id, owner)
    if snapshot["kind"] != "direct":
        raise ValueError("Wrong snapshot kind")
    async with likenovel_db_session() as db:
        async with db.begin():
            await db.execute(text("SELECT id FROM tb_direct_recommend ORDER BY id FOR UPDATE"))
            current = await curator._load_slots(db)
            receipt = store.get(job_id, owner)
            if receipt:
                if receipt["status"] == "completed":
                    return receipt
                if receipt["status"] == "applying" and current == receipt["after"]:
                    store.save(job_id, owner, "completed", {
                        **receipt["result"], "recovered_after_commit": True,
                    })
                    return store.get(job_id, owner)
                raise ValueError("An unresolved receipt exists; do not retry the write")
            if current != snapshot["slots"]:
                raise ValueError("CMS state changed since snapshot; nothing was written")
            candidates = await curator._load_candidates(db)
            policy.validate_direct_updates(updates, current, candidates)
            after = copy.deepcopy(current)
            by_slot = {row["slot_id"]: row for row in after}
            for update in updates:
                by_slot[update["slot_id"]]["product_ids"] = update["product_ids"]
            cooldown = _direct_cooldown(owner, current, date.fromisoformat(job_id.split(":")[1]))
            added_ids = {
                product_id for row in after for product_id in row["product_ids"]
            } - {product_id for row in current for product_id in row["product_ids"]}
            if added_ids.intersection(cooldown["avoid_reproposal_product_ids"]):
                raise ValueError("A newly added work is still in its 7-day cooldown; nothing was written")
            result = {"kind": "direct", "before": current, "after": after, "changes": updates}
            # Intent is fsynced before any CMS mutation. A lost response is reconciled by state.
            store.save(job_id, owner, "applying", {"after": after, "result": result})
            for update in updates:
                await admin_recommend_service.put_direct_recommend(
                    update["slot_id"],
                    PutDirectRecommendReqBody(product_ids=update["product_ids"]), db=db,
                )
            if await curator._load_slots(db) != after:
                raise ValueError("Internal direct slot readback failed; transaction rolled back")
        store.save(job_id, owner, "completed", result)
    return store.get(job_id, owner)


async def _generate_single_pinned(job_id: str, owner: str):
    from app.services.ai import mcp_single_copy as core

    try:
        async with likenovel_db_session() as db:
            candidates = core.rows_to_candidates(
                (await db.execute(text(core.CANDIDATE_SQL))).all()
            )
            before = await single_rows(db)
        state = core.empty_state()
        rotation = store.get("rotation", owner)
        if rotation:
            state["last_proposed_at"] = rotation.get("last_proposed_at", {})
        else:
            migration_path = load_config().get("rotation_state_file")
            if migration_path:
                legacy = json.loads(Path(migration_path).read_text())
                state["last_proposed_at"] = legacy["last_proposed_at"]
                store.save("rotation", owner, "state", {
                    "last_proposed_at": state["last_proposed_at"],
                })
        ranked = core.rank_candidates(candidates, state)
        selected, rejected = await asyncio.to_thread(core.select_cover_valid_candidates, ranked)
        if len(selected) != 3:
            store.save(job_id, owner, "insufficient_paid_candidates", {
                "candidate_count": len(candidates), "rejected_covers": rejected[:20],
            })
            return
        ids = [item["product_id"] for item in selected]
        async with likenovel_db_session() as db:
            rows = (await db.execute(text(core._episode_sql(ids)))).all()
        evidence = {product_id: [] for product_id in ids}
        for row in rows:
            evidence[int(row[0])].append(
                f"{int(row[1])}화 {core._decode_hex(row[2], 'episode_title', allow_empty=True)}".strip()
            )
        if any(not values for values in evidence.values()):
            raise ValueError("Missing public episode evidence")
        prompt = core.build_gemini_prompt(selected, evidence)
        proposals = None
        # The existing provider validates streaming completion, evidence and two-line copy.
        for attempt in (1, 2):
            payload = await asyncio.to_thread(
                core.run_openrouter,
                core.DEFAULT_OPENROUTER_API_KEY_FILE,
                prompt if attempt == 1 else prompt + "\n각 줄에 원문 evidence 핵심어를 사용하고 형식 기준을 지키세요.",
            )
            try:
                proposals = core.choose_proposals(selected, payload, evidence)
                break
            except core.CopyValidationError:
                if attempt == 2:
                    raise
        generated_at = datetime.now(policy.KST).isoformat()
        for item in proposals:
            state["last_proposed_at"][str(item["product_id"])] = generated_at
        store.save("rotation", owner, "state", {
            "last_proposed_at": state["last_proposed_at"],
        })
        store.save(job_id, owner, "ready", {
            "kind": "single", "before": before, "candidates": proposals,
            "generated_at": generated_at,
            "provider": (payload.get("_model_route") or {}).get("provider", get_model_binding("mcp.single_copy").billing_route),
            "model": get_model_binding("mcp.single_copy", default_model=core.OPENROUTER_MODEL).model_id,
            "model_route": payload.get("_model_route") or {},
            "attempts": attempt, "rejected_covers": rejected[:20],
        })
    except Exception as exc:
        logger.exception("MCP single-slot generation failed for %s", job_id)
        store.save(job_id, owner, "failed", {"error_type": type(exc).__name__})


async def _generate_single_inner(job_id: str, owner: str):
    try:
        receipt = store.get(job_id, owner) or {}
        if receipt.get("model_snapshot") is not None:
            snapshot = deserialize_model_snapshot(receipt["model_snapshot"])
        else:
            async with likenovel_db_session() as db:
                snapshot = await load_ai_model_snapshot(db)
            store.save(job_id, owner, "generating", {
                "kind": "single", "model_snapshot": serialize_model_snapshot(snapshot),
            })
        with use_ai_model_snapshot(snapshot):
            await _generate_single_pinned(job_id, owner)
    except Exception as exc:
        logger.exception("MCP model configuration failed for %s", job_id)
        store.save(job_id, owner, "failed", {"error_type": type(exc).__name__})


async def _generate_single(job_id: str, owner: str):
    try:
        async with asyncio.timeout(1320):
            await _generate_single_inner(job_id, owner)
    except TimeoutError:
        store.save(job_id, owner, "failed", {"error_type": "GenerationDeadlineExceeded"})


async def start_single(owner: str) -> dict:
    job_id = policy.cycle_key("single")
    receipt = store.get(job_id, owner)
    if receipt:
        return receipt
    async with likenovel_db_session() as db:
        model_snapshot = await load_ai_model_snapshot(db)
    if store.claim(job_id, owner, {
        "kind": "single", "model_snapshot": serialize_model_snapshot(model_snapshot),
    }):
        task = asyncio.create_task(_generate_single(job_id, owner))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    return store.get(job_id, owner)


async def verify_public(owner: str, job_id: str) -> dict:
    receipt = store.get(job_id, owner)
    if not receipt or receipt["status"] != "completed":
        raise ValueError("Only a committed job can be verified")
    base = load_config()["resource"].removesuffix("/mcp")
    route = "main-single-slots" if receipt["kind"] == "single" else "direct-recommend"
    async with AsyncClient(timeout=20, follow_redirects=False) as client:
        response = await client.get(
            base + "/v1/query/products/" + route,
            params={"adult_yn": "Y", "_mcp_readback": uuid.uuid4().hex},
            headers={"Cache-Control": "no-cache"},
        )
        response.raise_for_status()
        public = response.json()["data"]
        if receipt["kind"] == "single":
            expected = {
                row["slot_key"]: [row["product_id"], row["summary_text"]]
                for row in receipt["after"]
            }
            actual = {
                row["slotKey"]: [row["product"]["productId"], row["summaryText"]]
                for row in public if row["slotKey"] in policy.SINGLE_KEYS
            }
        else:
            expected = {row["slot_id"]: row["product_ids"] for row in receipt["after"]}
            actual = {
                row["recommendId"]: [product["productId"] for product in row["productList"]]
                for row in public
            }
        verified = all(actual.get(key) == value for key, value in expected.items())
    proof = {
        "public_verified": verified,
        "verified_at": datetime.now(policy.KST).isoformat(),
        "expected": expected, "actual": actual,
        "public_url": base + "/v1/query/products/" + route,
    }
    # Public verification is a read-only tool; do not mutate receipt state here.
    return proof


async def apply_single(owner: str, admin_user_id: int, job_id: str) -> dict:
    from app.services.ai import mcp_single_copy as core
    from app.services.product import main_single_slot_service

    _enabled()
    if job_id != policy.cycle_key("single"):
        raise ValueError("Only today's scheduled single-slot job can be applied")
    async with likenovel_db_session() as db:
        async with db.begin():
            # Lock all affected rows, including any future reservations.
            current = await single_rows(db, lock=True)
            receipt = store.get(job_id, owner)
            if receipt is None:
                raise ValueError("Generate validated copy first")
            if receipt["status"] == "completed":
                return receipt
            if receipt["status"] == "applying":
                expected = receipt["expected"]
                actual = {
                    row["slot_key"]: (row["product_id"], row["summary_text"])
                    for row in current
                }
                if actual == {key: tuple(value) for key, value in expected.items()}:
                    store.save(job_id, owner, "completed", {
                        **receipt["result"], "after": current, "recovered_after_commit": True,
                    })
                    return store.get(job_id, owner)
                raise ValueError("Uncertain single-slot receipt; automatic retry is blocked")
            if receipt["status"] != "ready" or current != receipt["before"]:
                raise ValueError("CMS changed or generation is not ready; nothing was written")
            by_key = {row["slot_key"]: row for row in current}
            if len(current) != 3 or set(by_key) != set(policy.SINGLE_KEYS):
                raise ValueError("Exactly three current slots and no future reservations are required")
            if any(
                row["publish_end_at"] is not None
                or datetime.fromisoformat(row["publish_start_at"]).replace(tzinfo=policy.KST)
                > datetime.now(policy.KST)
                for row in current
            ):
                raise ValueError("Reserved exposure dates require review; automatic write blocked")
            eligible = core.rows_to_candidates(
                (await db.execute(text(core.CANDIDATE_SQL))).all()
            )
            eligible_ids = {item["product_id"] for item in eligible}
            proposals = receipt["candidates"]
            if len(proposals) != 3 or len({item["product_id"] for item in proposals}) != 3:
                raise ValueError("Expected three distinct paid products")
            for item in proposals:
                if item["product_id"] not in eligible_ids:
                    raise ValueError("Product is no longer eligible")
                valid, _, _ = core.validate_summary(item["summary_text"], item["title"])
                if not valid:
                    raise ValueError("Copy validation failed")
            expected = {item["slot_key"]: [item["product_id"], item["summary_text"]] for item in proposals}
            result = {
                "kind": "single", "before": current, "candidates": proposals,
                "model": receipt["model"], "generated_at": receipt["generated_at"],
            }
            store.save(job_id, owner, "applying", {"expected": expected, "result": result})
            for item in proposals:
                old = by_key[item["slot_key"]]
                await main_single_slot_service.publish_admin_main_single_slot_now(
                    PostMainSingleSlotPublishNowReqBody(
                        slot_key=old["slot_key"], slot_name=old["slot_name"],
                        slot_order=old["slot_order"], product_id=item["product_id"],
                        summary_text=item["summary_text"],
                    ), admin_user_id=admin_user_id, db=db,
                )
            after = await single_rows(db)
            actual = {row["slot_key"]: [row["product_id"], row["summary_text"]] for row in after}
            if len(after) != 3 or actual != expected:
                raise ValueError("Single-slot readback failed; all changes rolled back")
            result["after"] = after
        store.save(job_id, owner, "completed", result)
        rotation = store.get("rotation", owner) or {"last_proposed_at": {}}
        proposed_at = rotation["last_proposed_at"]
        for item in proposals:
            proposed_at[str(item["product_id"])] = result["generated_at"]
        store.save("rotation", owner, "state", {"last_proposed_at": proposed_at})
    return store.get(job_id, owner)
