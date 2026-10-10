"""Prepared AI-reader operations. MCP registration/authentication is separate."""

import hashlib
import json
import re
import time
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import settings
from app.rdb import likenovel_db_engine, likenovel_db_session
from app.schemas import admin as schema
from app.services.admin import admin_ai_reader_service as cms
from app.services.ai import mcp_store as store
from app.services.ai.mcp_config import load as load_config


READ_AI = "likenovel.mcp.ai-reader.read"
WRITE_AI = "likenovel.mcp.ai-reader.write"
PLAN_TTL_SECONDS = 1800
MODES = {
    "bootstrap": (schema.PostAiReaderBootstrapReqBody, "bootstrap_ai_reader_agents"),
    "resume": (schema.PostAiReaderResumePausedReqBody, "resume_paused_ai_reader_agents"),
    "restart": (schema.PostAiReaderRestartReqBody, "restart_ai_reader_agents"),
}
STATE_QUERY = """
    SELECT a.ai_reader_agent_id, a.agent_key, a.user_id, a.status,
           a.activity_pattern_json, a.daily_llm_budget,
           u.use_yn, u.email
    FROM tb_ai_reader_agent a LEFT JOIN tb_user u ON u.user_id=a.user_id
    ORDER BY a.ai_reader_agent_id
"""


def _json(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def _clean(value):
    return json.loads(json.dumps(value, default=_json, ensure_ascii=False))


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json).encode()
    ).hexdigest()


def _today():
    return datetime.now(ZoneInfo(settings.KOREA_TIMEZONE)).date()


def _request(count, starts_on, duration_days, mode, email_prefix):
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError("mode must be bootstrap, resume or restart")
    if type(count) is not int or type(duration_days) is not int:
        raise ValueError("count and duration_days must be integers")
    if not isinstance(starts_on, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", starts_on):
        raise ValueError("starts_on must be YYYY-MM-DD")
    start = date.fromisoformat(starts_on)
    if start < _today():
        raise ValueError("starts_on cannot be in the past (Asia/Seoul)")
    values = {
        "agent_count": count, "schedule_date": starts_on,
        "schedule_duration_days": duration_days, "apply": False,
        "start_immediately": False,
    }
    if mode == "bootstrap":
        if not isinstance(email_prefix, str) or not email_prefix.strip():
            raise ValueError("bootstrap requires the dedicated AI account email_prefix")
        values.update(
            email_prefix=email_prefix, allow_partial=False,
            auto_provision_missing_users=False,
        )
    elif email_prefix is not None:
        raise ValueError("email_prefix is only supported for bootstrap")
    return MODES[mode][0](**values)


async def _state(db, lock=False):
    result = await db.execute(text(STATE_QUERY + (" FOR UPDATE" if lock else "")))
    return _clean([dict(row) for row in result.mappings().all()])


async def status(starts_on: str | None = None, page: int = 1) -> dict:
    """Read current CMS state; no user email or account credentials returned."""
    if type(page) is not int or page < 1:
        raise ValueError("page must be a positive integer")
    if starts_on is not None:
        if not isinstance(starts_on, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", starts_on):
            raise ValueError("starts_on must be YYYY-MM-DD")
        date.fromisoformat(starts_on)
    async with likenovel_db_session() as db:
        result = await cms.list_ai_reader_agents(
            schedule_date=starts_on, status_filter="all",
            page=page, count_per_page=100, db=db,
        )
    for item in result["items"]:
        item.pop("email", None)
    return _clean(result)


def _public_plan(record):
    preview = record["preview"]
    return {
        "plan_id": record["job_id"], "plan_hash": record["plan_hash"],
        "status": record["status"], "mode": record["mode"],
        "count": record["request"]["agent_count"],
        "starts_on": record["request"]["schedule_date"],
        "duration_days": record["request"]["schedule_duration_days"],
        "ends_on": preview["schedule_end_date"],
        "exact_count_available": record["exact_count_available"],
        "selected": [
            {key: item[key] for key in (
                "ai_reader_agent_id", "agent_key", "activity_pattern", "daily_llm_budget"
            ) if key in item}
            for item in preview["preview"]
        ],
        "restart_affects_all_existing_agents": record["mode"] == "restart",
        "existing_agent_count": record["existing_agent_count"],
        "account_provisioning": False,
        "timezone": settings.KOREA_TIMEZONE,
    }


async def plan(owner: str, count: int, starts_on: str, duration_days: int,
               mode: str = "resume", email_prefix: str | None = None) -> dict:
    """Freeze a read-only CMS dry run, owned by the authenticated administrator."""
    req = _request(count, starts_on, duration_days, mode, email_prefix)
    async with likenovel_db_session() as db:
        before = await _state(db)
        preview = _clean(await getattr(cms, MODES[mode][1])(req_body=req, db=db))
        if before != await _state(db):
            raise ValueError("AI-reader configuration changed during planning; retry")
    selected = preview.get("preview", [])
    exact = len(selected) == count
    if preview.get("applied") is not False or not preview.get("dry_run_token"):
        raise ValueError("CMS did not return a complete dry-run contract")
    ends_on = (date.fromisoformat(starts_on) + timedelta(days=duration_days - 1)).isoformat()
    if (
        preview.get("schedule_date") != starts_on
        or preview.get("schedule_duration_days") != duration_days
        or preview.get("schedule_end_date") != ends_on
        or preview.get("requested_count") != count
    ):
        raise ValueError("CMS dry-run count/period does not match the request")
    for item in selected:
        item["activity_pattern"]["auto_start_schedule_start_date"] = starts_on
    payload = {
        "kind": "ai-reader", "mode": mode, "request": req.model_dump(mode="json"),
        "preview": preview, "state_hash": _digest(before),
        "existing_agent_count": len(before), "exact_count_available": exact,
        "created_at": time.time(),
    }
    payload["plan_hash"] = _digest(payload)
    plan_id = "ai-reader-plan:" + uuid.uuid4().hex
    store.save(plan_id, owner, "planned", payload)
    return _public_plan(store.get(plan_id, owner))


def _read_plan(owner, plan_id):
    if not isinstance(plan_id, str) or not re.fullmatch(r"ai-reader-plan:[a-f0-9]{32}", plan_id):
        raise ValueError("Invalid AI-reader plan_id")
    record = store.get(plan_id, owner)
    if not record or record.get("kind") != "ai-reader":
        raise ValueError("AI-reader plan does not belong to this administrator")
    payload = {key: value for key, value in record.items()
               if key not in ("job_id", "status", "updated_at", "plan_hash")}
    if _digest(payload) != record["plan_hash"]:
        raise ValueError("Stored AI-reader plan payload changed")
    return record


async def _verify_applied(db, record):
    selected = record["preview"]["preview"]
    keys = [item["agent_key"] for item in selected]
    result = await db.execute(text("""
        SELECT agent_key, status, activity_pattern_json, daily_llm_budget
        FROM tb_ai_reader_agent WHERE agent_key IN :keys
    """).bindparams(bindparam("keys", expanding=True)), {"keys": keys})
    rows = [dict(row) for row in result.mappings().all()]
    if len(rows) != record["request"]["agent_count"]:
        raise ValueError("Applied AI-reader count does not match the plan")
    expected = {item["agent_key"]: item["activity_pattern"] for item in selected}
    budgets = {
        item["agent_key"]: item.get("daily_llm_budget", record["request"].get("daily_llm_budget"))
        for item in selected
    }
    for row in rows:
        pattern = row["activity_pattern_json"]
        if isinstance(pattern, str):
            pattern = json.loads(pattern)
        if row["status"] != "active" or pattern != expected[row["agent_key"]]:
            raise ValueError("AI-reader status/period readback does not match the plan")
        if budgets[row["agent_key"]] is not None and (
            row["daily_llm_budget"] is None or Decimal(str(row["daily_llm_budget"]))
            != Decimal(str(budgets[row["agent_key"]]))
        ):
            raise ValueError("AI-reader LLM budget readback does not match the plan")
    result = await db.execute(text("""
        SELECT a.agent_key, COUNT(DISTINCT s.schedule_date) AS scheduled_days,
               MIN(s.schedule_date) AS starts_on, MAX(s.schedule_date) AS ends_on
        FROM tb_ai_reader_agent a
        JOIN tb_ai_reader_daily_schedule s ON s.ai_reader_agent_id=a.ai_reader_agent_id
        WHERE a.agent_key IN :keys AND s.schedule_date BETWEEN :start AND :end
          AND s.status IN ('ready','running')
        GROUP BY a.agent_key
    """).bindparams(bindparam("keys", expanding=True)), {
        "keys": keys, "start": record["request"]["schedule_date"],
        "end": record["preview"]["schedule_end_date"],
    })
    schedules = _clean([dict(row) for row in result.mappings().all()])
    if len(schedules) != len(keys) or any(
        row["scheduled_days"] != record["request"]["schedule_duration_days"]
        or row["starts_on"] != record["request"]["schedule_date"]
        or row["ends_on"] != record["preview"]["schedule_end_date"]
        for row in schedules
    ):
        raise ValueError("AI-reader scheduled dates do not match the requested period")
    return {"active_count": len(rows), "schedules": schedules}


async def _apply_start_boundary(db, record):
    await db.execute(text("""
        UPDATE tb_ai_reader_agent
        SET activity_pattern_json=:pattern, updated_date=current_timestamp
        WHERE agent_key=:agent_key AND status='active'
    """), [
        {"agent_key": item["agent_key"], "pattern": json.dumps(item["activity_pattern"], ensure_ascii=False)}
        for item in record["preview"]["preview"]
    ])


async def apply(owner: str, plan_id: str, *, authorized_plan_hash: str | None = None) -> dict:
    """The OAuth wrapper must supply a hash authorized by a direct user command.

    This parameter must never be populated from autonomous model tool arguments.
    """
    record = _read_plan(owner, plan_id)
    if not authorized_plan_hash or authorized_plan_hash != record["plan_hash"]:
        raise PermissionError("A direct user instruction or approved exact plan is required")
    if load_config().get("ai_reader_writes_enabled") is not True:
        raise PermissionError("AI-reader writes are disabled independently of slot writes")
    operation_id = "ai-reader-apply:" + plan_id.split(":")[1]
    receipt = store.get(operation_id, owner)
    if receipt:
        return receipt
    if record["status"] != "planned" or time.time() - record["created_at"] > PLAN_TTL_SECONDS:
        raise ValueError("AI-reader plan expired or was consumed; create a fresh plan")
    if date.fromisoformat(record["request"]["schedule_date"]) < _today():
        raise ValueError("The requested start date has passed; create a fresh plan")
    if not record["exact_count_available"]:
        raise ValueError("The exact requested AI-reader count is unavailable")
    # The outer connection transaction keeps locks across CMS service commits,
    # which release only this session's savepoint.
    async with likenovel_db_engine.connect() as connection:
        async with connection.begin():
            async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint") as db:
                if _digest(await _state(db, lock=True)) != record["state_hash"]:
                    raise ValueError("AI-reader configuration changed; create a fresh plan")
                if not store.consume(plan_id, owner, "planned"):
                    raise ValueError("AI-reader plan was already consumed")
                intent = {"kind": "ai-reader", "plan_id": plan_id, "plan_hash": record["plan_hash"]}
                store.save(operation_id, owner, "applying", intent)
                req = MODES[record["mode"]][0](**{
                    **record["request"], "apply": True,
                    "dry_run_token": record["preview"]["dry_run_token"],
                })
                # A durable intent remains on exceptions. Retrying never repeats
                # effects after an uncertain commit/response or process crash.
                result = _clean(await getattr(cms, MODES[record["mode"]][1])(req_body=req, db=db))
                if result.get("applied") is not True:
                    raise ValueError("CMS did not confirm the AI-reader apply contract")
                await _apply_start_boundary(db, record)
                verification = await _verify_applied(db, record)
                # Persist the boundary update in the session's savepoint.
                await db.commit()
    store.save(operation_id, owner, "completed", {
        **intent, "result": result, "readback": verification,
    })
    return store.get(operation_id, owner)
