"""Operator-written single copy grounded in owner-bound, freshly read episodes.

Preparing a plan records a proposal, never publishes CMS content. Existing daily
jobs (including failed/uncertain ones) are immutable to this preparation path.
"""

import asyncio
import json
import time
from datetime import datetime, timedelta

from app.services.ai import mcp_policy as policy, mcp_store as store


def normalize_proposals(proposals):
    if not isinstance(proposals, list) or len(proposals) != 3:
        raise ValueError("Exactly three proposals are required")
    fields = {"slot_key", "product_id", "summary_text", "evidence_id", "quotes", "reason"}
    normalized = []
    for item in proposals:
        if not isinstance(item, dict) or set(item) != fields:
            raise ValueError("Supply slot, product, two-line copy, evidence ID, quotes and reason only")
        if item["slot_key"] not in policy.SINGLE_KEYS or type(item["product_id"]) is not int or item["product_id"] <= 0:
            raise ValueError("Invalid slot or product ID")
        if not isinstance(item["summary_text"], str):
            raise ValueError("Copy must be text")
        lines = [line.strip() for line in item["summary_text"].strip().splitlines()]
        if len(lines) != 2 or any(not line for line in lines):
            raise ValueError("Exactly two nonempty lines are required")
        if not isinstance(item["evidence_id"], str) or not item["evidence_id"]:
            raise ValueError("Read episode evidence first")
        quotes = item["quotes"]
        if not isinstance(quotes, list) or not 1 <= len(quotes) <= 3 or any(
            not isinstance(quote, str) or not 2 <= len(quote.strip()) <= 300 for quote in quotes
        ):
            raise ValueError("Supply one to three short exact body quotations")
        if not isinstance(item["reason"], str) or not 10 <= len(item["reason"].strip()) <= 1500:
            raise ValueError("A concrete editorial comparison is required")
        normalized.append({**item, "summary_text": "\n".join(lines),
                           "quotes": [quote.strip() for quote in quotes], "reason": item["reason"].strip()})
    if {item["slot_key"] for item in normalized} != set(policy.SINGLE_KEYS):
        raise ValueError("Each authorized slot must occur exactly once")
    if len({item["product_id"] for item in normalized}) != 3:
        raise ValueError("Three distinct works are required")
    return normalized


def validate_body_grounding(core, proposal, candidate, evidence):
    valid, reason, _ = core.validate_summary(proposal["summary_text"], candidate["title"])
    if not valid:
        raise ValueError("Copy validation failed: " + str(reason))
    bodies = [episode["text"] for episode in evidence]
    if not bodies or any(not any(quote in body for body in bodies) for quote in proposal["quotes"]):
        raise ValueError("Quotations must occur in the retrieved episode body, not its title or synopsis")
    if not core.summary_is_grounded(proposal["summary_text"], proposal["quotes"]):
        raise ValueError("Each copy line must be grounded in the cited episode body")


def check_cooldown(owner, candidates, current_direct, cycle_date, *, same_plan=None):
    from app.services.ai import mcp_operations as ops, mcp_single_copy as core

    # Includes recent direct additions still on display: they are not new opportunities.
    direct = ops._direct_cooldown(owner, current_direct, cycle_date)
    excluded = {row["product_id"] for row in direct["recently_added"]}
    rotation = store.get("rotation", owner) or {}
    proposed = dict(rotation.get("last_proposed_at", {}))
    if same_plan is not None:
        # Preparing and applying the exact same plan is not a second recommendation.
        for item in same_plan["candidates"]:
            key = str(item["product_id"])
            if proposed.get(key) == same_plan["generated_at"]:
                proposed.pop(key)
    now = datetime.now(policy.KST)
    eligible = {item["product_id"] for item in core.rank_candidates(
        candidates, {"last_proposed_at": proposed}, now=now,
    )}
    if any(item["product_id"] in excluded or item["product_id"] not in eligible for item in candidates):
        raise ValueError("A work was recently proposed or newly placed; keep the seven-day exclusion")


def _insert_ready(owner, job_id, payload):
    # Unique daily receipt and rotation history move together across API workers.
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute("SELECT owner FROM receipts WHERE job_id=?", (job_id,)).fetchone()
        if existing:
            if existing[0] != owner:
                raise ValueError("Receipt belongs to another identity")
            return False
        rotation = db.execute("SELECT owner,payload FROM receipts WHERE job_id='rotation'").fetchone()
        if rotation and rotation[0] != owner:
            raise ValueError("Rotation belongs to another identity")
        state = json.loads(rotation[1]) if rotation else {"last_proposed_at": {}}
        for item in payload["candidates"]:
            previous = state["last_proposed_at"].get(str(item["product_id"]))
            if previous:
                seen = datetime.fromisoformat(previous)
                if seen.tzinfo is None:
                    seen = seen.replace(tzinfo=policy.KST)
                if seen > datetime.now(policy.KST) - timedelta(days=7):
                    raise ValueError("Concurrent recent proposal detected; nothing was prepared")
            state["last_proposed_at"][str(item["product_id"])] = payload["generated_at"]
        now = time.time()
        db.execute("INSERT INTO receipts VALUES (?,?,?,?,?)", (
            job_id, owner, "ready", json.dumps(payload, ensure_ascii=False), now,
        ))
        db.execute("INSERT OR REPLACE INTO receipts VALUES (?,?,?,?,?)", (
            "rotation", owner, "state", json.dumps(state, ensure_ascii=False), now,
        ))
        db.commit()
        return True


async def prepare_single_plan(owner, snapshot_id, proposals):
    from sqlalchemy import text
    from app.rdb import likenovel_db_session
    from app.services.ai import mcp_operations as ops, mcp_single_copy as core
    from app.services.ai.mcp_episode_evidence import validate_evidence, load_evidence

    ops._enabled()
    job_id = policy.cycle_key("single")
    existing = store.get(job_id, owner)
    if existing:
        return existing  # In particular, never turn a failed/applying job into a new plan.
    proposals = normalize_proposals(proposals)
    snapshot = ops._snapshot(snapshot_id, owner)
    if snapshot.get("kind") != "direct" or "single_slots" not in snapshot:
        raise ValueError("Read a fresh snapshot with single-slot state first")
    async with likenovel_db_session() as db:
        before = await ops.single_rows(db)
        direct = await ops.curator._load_slots(db)
        if before != snapshot["single_slots"] or direct != snapshot["slots"]:
            raise ValueError("CMS changed since snapshot; nothing was prepared")
        ops.validate_single_layout(before)
        eligible = core.rows_to_candidates((await db.execute(text(core.CANDIDATE_SQL))).all())
        by_id = {item["product_id"]: item for item in eligible}
        if any(item["product_id"] not in by_id for item in proposals):
            raise ValueError("A selected work is not eligible")
        selected = [by_id[item["product_id"]] for item in proposals]
        check_cooldown(owner, selected, direct, datetime.now(policy.KST).date())
        validated = []
        for proposal in proposals:
            candidate = by_id[proposal["product_id"]]
            manifest = load_evidence(owner, proposal["evidence_id"], candidate["product_id"])
            evidence = await validate_evidence(owner, candidate["product_id"], proposal["evidence_id"], db=db)
            validate_body_grounding(core, proposal, candidate, evidence)
            cover = await asyncio.to_thread(core.inspect_cover, candidate["cover_image_path"])
            if not core.cover_is_eligible(cover)[0]:
                raise ValueError("A selected work has an ineligible cover")
            validated.append({**proposal, "title": candidate["title"], "cover_evidence": cover,
                              "evidence_manifest": manifest,
                              "read_episode_ids": [episode["episode_id"] for episode in evidence]})
    payload = {"kind": "single", "copy_source": "operator_episode_body", "model": "operator",
               "before": before, "candidates": validated, "generated_at": datetime.now(policy.KST).isoformat(),
               "snapshot_id": snapshot_id, "history_limitations": "Legacy proposal records may be incomplete; inspect available shared records before preparing."}
    _insert_ready(owner, job_id, payload)
    return store.get(job_id, owner)


async def validate_manual_apply(owner, receipt, snapshot_id, current, db, eligible):
    from app.services.ai import mcp_operations as ops, mcp_single_copy as core
    from app.services.ai.mcp_episode_evidence import revalidate_evidence, EVIDENCE_KIND

    snapshot = ops._snapshot(snapshot_id, owner)
    if snapshot.get("kind") != "direct" or snapshot.get("single_slots") != current:
        raise ValueError("A fresh matching single-slot snapshot is required")
    if snapshot.get("updated_at", 0) <= receipt.get("updated_at", 0):
        raise ValueError("Read a new snapshot after preparing the plan, immediately before applying")
    direct = await ops.curator._load_slots(db)
    if direct != snapshot["slots"]:
        raise ValueError("Direct CMS state changed; refresh and review before applying")
    by_id = {item["product_id"]: item for item in eligible}
    proposals = receipt["candidates"]
    if any(item["product_id"] not in by_id for item in proposals):
        raise ValueError("A selected work is no longer eligible")
    check_cooldown(owner, [by_id[item["product_id"]] for item in proposals], direct,
                   datetime.now(policy.KST).date(), same_plan=receipt)
    for proposal in proposals:
        candidate = by_id[proposal["product_id"]]
        # This manifest is server-created and bound to the owner-owned ready receipt.
        # Its age may exceed the read receipt TTL, but exact live bodies must still match.
        manifest = proposal.get("evidence_manifest")
        if not manifest or manifest.get("kind") != EVIDENCE_KIND or manifest.get("product_id") != candidate["product_id"]:
            raise ValueError("Prepared manuscript evidence is missing or belongs to another work")
        evidence = await revalidate_evidence(db, manifest)
        validate_body_grounding(core, proposal, candidate, evidence)
        cover = await asyncio.to_thread(core.inspect_cover, candidate["cover_image_path"])
        if not core.cover_is_eligible(cover)[0]:
            raise ValueError("A selected cover changed or is no longer eligible")
