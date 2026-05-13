import hashlib
import hmac
import json
from datetime import datetime, date
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import status
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

import app.schemas.admin as admin_schema
from app.const import settings
from app.exceptions import CustomResponseException
from app.services.ai import reader_agent_persona_service
from app.services.ai import reader_agent_session_service


def _parse_schedule_date(value: str | None) -> date:
    if not value:
        return datetime.now(ZoneInfo(settings.KOREA_TIMEZONE)).date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="schedule_date must be YYYY-MM-DD.",
        ) from exc


def _parse_json_field(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def _schedule_window_payload(
    windows: list[reader_agent_session_service.ReaderDailyScheduleWindow],
) -> list[dict[str, Any]]:
    return [
        {
            "active_start_at": window.active_start_at.isoformat(sep=" "),
            "active_end_at": window.active_end_at.isoformat(sep=" "),
            "session_budget": window.session_budget,
        }
        for window in windows
    ]


def _sleep_hours(active_hours: list[int]) -> list[int]:
    active_set = set(active_hours)
    return [hour for hour in range(24) if hour not in active_set]


def _allowed_ai_reader_account_domains() -> list[str]:
    return [
        domain.strip().lower()
        for domain in settings.AI_READER_ACCOUNT_ALLOWED_DOMAINS.split(",")
        if domain.strip()
    ]


def build_ai_reader_bootstrap_dry_run_token(
    *,
    email_prefix: str,
    agent_count: int,
    schedule_date: str,
    allow_partial: bool,
    agent_index_offset: int,
    daily_llm_budget: int,
    active_hours: list[int] | None = None,
    daily_session_target: int | None = None,
    age_group_ratios: dict[str, int] | None = None,
    gender_ratios: dict[str, int] | None = None,
    user_fingerprints: list[dict[str, Any]] | None = None,
) -> str:
    normalized_active_hours = active_hours or list(admin_schema.DEFAULT_AI_READER_ACTIVE_HOURS)
    normalized_age_group_ratios = age_group_ratios or dict(
        admin_schema.DEFAULT_AI_READER_AGE_GROUP_RATIOS
    )
    normalized_gender_ratios = gender_ratios or dict(
        admin_schema.DEFAULT_AI_READER_GENDER_RATIOS
    )
    payload = {
        "v": 1,
        "email_prefix": email_prefix,
        "agent_count": agent_count,
        "schedule_date": schedule_date,
        "allow_partial": allow_partial,
        "agent_index_offset": agent_index_offset,
        "daily_llm_budget": daily_llm_budget,
        "active_hours": sorted(normalized_active_hours),
        "daily_session_target": daily_session_target or 2,
        "age_group_ratios": normalized_age_group_ratios,
        "gender_ratios": normalized_gender_ratios,
        "user_fingerprints": sorted(
            user_fingerprints or [],
            key=lambda item: (str(item.get("agent_key")), int(item.get("user_id") or 0)),
        ),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    secret = (
        settings.KC_CLIENT_SECRET
        or settings.DB_USER_PW
        or "likenovel-ai-reader-bootstrap-dry-run"
    )
    return hmac.new(
        secret.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _expected_bootstrap_dry_run_token(
    req_body: admin_schema.PostAiReaderBootstrapReqBody,
    *,
    schedule_date: date,
    user_fingerprints: list[dict[str, Any]] | None = None,
) -> str:
    return build_ai_reader_bootstrap_dry_run_token(
        email_prefix=req_body.email_prefix,
        agent_count=req_body.agent_count,
        schedule_date=schedule_date.isoformat(),
        allow_partial=req_body.allow_partial,
        agent_index_offset=req_body.agent_index_offset,
        daily_llm_budget=req_body.daily_llm_budget,
        active_hours=req_body.active_hours,
        daily_session_target=req_body.daily_session_target,
        age_group_ratios=req_body.age_group_ratios,
        gender_ratios=req_body.gender_ratios,
        user_fingerprints=user_fingerprints,
    )


def _assert_matching_bootstrap_dry_run_token(
    req_body: admin_schema.PostAiReaderBootstrapReqBody,
    *,
    schedule_date: date,
    user_fingerprints: list[dict[str, Any]] | None = None,
) -> None:
    expected_token = _expected_bootstrap_dry_run_token(
        req_body,
        schedule_date=schedule_date,
        user_fingerprints=user_fingerprints,
    )
    if not req_body.dry_run_token or not hmac.compare_digest(
        req_body.dry_run_token,
        expected_token,
    ):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="matching dry-run token is required before AI reader bootstrap apply.",
        )


def build_ai_reader_resume_paused_dry_run_token(
    *,
    agent_count: int,
    schedule_date: str,
    agent_fingerprints: list[dict[str, Any]] | None = None,
) -> str:
    payload = {
        "v": 1,
        "agent_count": agent_count,
        "schedule_date": schedule_date,
        "agent_fingerprints": sorted(
            agent_fingerprints or [],
            key=lambda item: int(item.get("ai_reader_agent_id") or 0),
        ),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    secret = (
        settings.KC_CLIENT_SECRET
        or settings.DB_USER_PW
        or "likenovel-ai-reader-resume-paused-dry-run"
    )
    return hmac.new(
        secret.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _expected_resume_paused_dry_run_token(
    req_body: admin_schema.PostAiReaderResumePausedReqBody,
    *,
    schedule_date: date,
    agent_fingerprints: list[dict[str, Any]] | None = None,
) -> str:
    return build_ai_reader_resume_paused_dry_run_token(
        agent_count=req_body.agent_count,
        schedule_date=schedule_date.isoformat(),
        agent_fingerprints=agent_fingerprints,
    )


def _assert_matching_resume_paused_dry_run_token(
    req_body: admin_schema.PostAiReaderResumePausedReqBody,
    *,
    schedule_date: date,
    agent_fingerprints: list[dict[str, Any]] | None = None,
) -> None:
    expected_token = _expected_resume_paused_dry_run_token(
        req_body,
        schedule_date=schedule_date,
        agent_fingerprints=agent_fingerprints,
    )
    if not req_body.dry_run_token or not hmac.compare_digest(
        req_body.dry_run_token,
        expected_token,
    ):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="matching dry-run token is required before paused AI reader resume apply.",
        )


def _resume_paused_agent_fingerprints(
    agents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "ai_reader_agent_id": int(agent["ai_reader_agent_id"]),
            "agent_key": str(agent["agent_key"]),
            "user_id": int(agent["user_id"]),
        }
        for agent in agents
    ]


def _resume_paused_agent_preview(
    agents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "ai_reader_agent_id": int(agent["ai_reader_agent_id"]),
            "agent_key": agent["agent_key"],
            "user_id": int(agent["user_id"]),
            "age_group": agent["age_group"],
            "gender": agent["gender"],
            "daily_llm_budget": int(agent["daily_llm_budget"]),
            "activity_pattern": _parse_json_field(agent["activity_pattern_json"], {}),
        }
        for agent in agents
    ]


async def replace_reader_daily_schedule_windows(
    db: AsyncSession,
    *,
    ai_reader_agent_id: int,
    schedule_date: date,
    windows: list[reader_agent_session_service.ReaderDailyScheduleWindow],
    replace_running: bool = False,
) -> dict[str, int]:
    if replace_running:
        await db.execute(
            text("""
                update tb_ai_reader_daily_schedule
                   set status = 'done',
                       locked_by = null,
                       locked_at = null,
                       error_message = 'replaced by admin schedule adjustment',
                       updated_date = current_timestamp
                 where ai_reader_agent_id = :ai_reader_agent_id
                   and schedule_date = :schedule_date
                   and status = 'running'
            """),
            {
                "ai_reader_agent_id": ai_reader_agent_id,
                "schedule_date": schedule_date,
            },
        )

    retire_result = await db.execute(
        text("""
            update tb_ai_reader_daily_schedule
               set status = 'done',
                   locked_by = null,
                   locked_at = null,
                   error_message = 'retired by admin schedule adjustment',
                   updated_date = current_timestamp
             where ai_reader_agent_id = :ai_reader_agent_id
               and schedule_date = :schedule_date
               and status = 'ready'
               and used_session_count > 0
        """),
        {
            "ai_reader_agent_id": ai_reader_agent_id,
            "schedule_date": schedule_date,
        },
    )

    delete_result = await db.execute(
        text("""
            delete from tb_ai_reader_daily_schedule
             where ai_reader_agent_id = :ai_reader_agent_id
               and schedule_date = :schedule_date
               and status = 'ready'
               and used_session_count = 0
        """),
        {
            "ai_reader_agent_id": ai_reader_agent_id,
            "schedule_date": schedule_date,
        },
    )
    upserted_count = await reader_agent_session_service.upsert_reader_daily_schedule_windows(
        db,
        windows,
    )
    return {
        "retired_count": int(getattr(retire_result, "rowcount", 0) or 0),
        "deleted_count": int(getattr(delete_result, "rowcount", 0) or 0),
        "upserted_count": upserted_count,
    }


async def replace_reader_daily_schedule_windows_bulk(
    db: AsyncSession,
    *,
    ai_reader_agent_ids: list[int],
    schedule_date: date,
    windows: list[reader_agent_session_service.ReaderDailyScheduleWindow],
) -> dict[str, int]:
    if not ai_reader_agent_ids:
        return {"retired_count": 0, "deleted_count": 0, "upserted_count": 0}

    retire_stmt = (
        text("""
            update tb_ai_reader_daily_schedule
               set status = 'done',
                   locked_by = null,
                   locked_at = null,
                   error_message = 'retired by admin schedule adjustment',
                   updated_date = current_timestamp
             where ai_reader_agent_id in :ai_reader_agent_ids
               and schedule_date = :schedule_date
               and status = 'ready'
               and used_session_count > 0
        """)
        .bindparams(bindparam("ai_reader_agent_ids", expanding=True))
    )
    retire_result = await db.execute(
        retire_stmt,
        {
            "ai_reader_agent_ids": ai_reader_agent_ids,
            "schedule_date": schedule_date,
        },
    )

    delete_stmt = (
        text("""
            delete from tb_ai_reader_daily_schedule
             where ai_reader_agent_id in :ai_reader_agent_ids
               and schedule_date = :schedule_date
               and status = 'ready'
               and used_session_count = 0
        """)
        .bindparams(bindparam("ai_reader_agent_ids", expanding=True))
    )
    delete_result = await db.execute(
        delete_stmt,
        {
            "ai_reader_agent_ids": ai_reader_agent_ids,
            "schedule_date": schedule_date,
        },
    )
    upserted_count = await reader_agent_session_service.upsert_reader_daily_schedule_windows(
        db,
        windows,
    )
    return {
        "retired_count": int(getattr(retire_result, "rowcount", 0) or 0),
        "deleted_count": int(getattr(delete_result, "rowcount", 0) or 0),
        "upserted_count": upserted_count,
    }


async def pause_all_ai_reader_agents(
    *,
    db: AsyncSession,
) -> dict[str, int]:
    active_result = await db.execute(
        text("""
            select ai_reader_agent_id
              from tb_ai_reader_agent
             where status = 'active'
             order by ai_reader_agent_id asc
             for update
        """)
    )
    ai_reader_agent_ids = [
        int(row["ai_reader_agent_id"])
        for row in active_result.mappings().all()
    ]
    if not ai_reader_agent_ids:
        await db.commit()
        return {
            "paused_agent_count": 0,
            "retired_schedule_count": 0,
            "cancelled_action_count": 0,
        }

    update_agent_stmt = (
        text("""
            update tb_ai_reader_agent
               set status = 'paused',
                   updated_date = current_timestamp
             where ai_reader_agent_id in :ai_reader_agent_ids
               and status = 'active'
        """)
        .bindparams(bindparam("ai_reader_agent_ids", expanding=True))
    )
    update_agent_result = await db.execute(
        update_agent_stmt,
        {"ai_reader_agent_ids": ai_reader_agent_ids},
    )

    retire_schedule_stmt = (
        text("""
            update tb_ai_reader_daily_schedule
               set status = 'done',
                   locked_by = null,
                   locked_at = null,
                   error_message = 'paused by admin bulk pause',
                   updated_date = current_timestamp
             where ai_reader_agent_id in :ai_reader_agent_ids
               and status in ('ready', 'running')
        """)
        .bindparams(bindparam("ai_reader_agent_ids", expanding=True))
    )
    retire_schedule_result = await db.execute(
        retire_schedule_stmt,
        {"ai_reader_agent_ids": ai_reader_agent_ids},
    )

    cancel_action_stmt = (
        text("""
            update tb_ai_reader_action_queue
               set status = 'failed',
                   active_scope_key = null,
                   locked_by = null,
                   locked_at = null,
                   error_message = 'cancelled by admin bulk pause',
                   updated_date = current_timestamp
             where ai_reader_agent_id in :ai_reader_agent_ids
               and status in ('queued', 'running')
        """)
        .bindparams(bindparam("ai_reader_agent_ids", expanding=True))
    )
    cancel_action_result = await db.execute(
        cancel_action_stmt,
        {"ai_reader_agent_ids": ai_reader_agent_ids},
    )

    await db.commit()
    return {
        "paused_agent_count": int(getattr(update_agent_result, "rowcount", 0) or 0),
        "retired_schedule_count": int(getattr(retire_schedule_result, "rowcount", 0) or 0),
        "cancelled_action_count": int(getattr(cancel_action_result, "rowcount", 0) or 0),
    }


async def resume_paused_ai_reader_agents(
    *,
    req_body: admin_schema.PostAiReaderResumePausedReqBody,
    db: AsyncSession,
) -> dict[str, Any]:
    target_date = _parse_schedule_date(req_body.schedule_date)
    allowed_domains = _allowed_ai_reader_account_domains()
    if not allowed_domains:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="AI reader account allowed domains are not configured.",
        )
    count_result = await db.execute(
        text("""
            select count(*) as available_agent_count
              from tb_ai_reader_agent a
              join tb_user u on u.user_id = a.user_id
             where a.status = 'paused'
               and u.use_yn = 'Y'
               and lower(substring_index(u.email, '@', -1)) in :allowed_domains
               and not exists (
                       select 1
                         from tb_user_social us
                        where us.user_id = u.user_id
                   )
        """).bindparams(bindparam("allowed_domains", expanding=True)),
        {"allowed_domains": allowed_domains},
    )
    available_agent_count = int(count_result.scalar() or 0)

    select_sql = """
        select
            a.ai_reader_agent_id,
            a.agent_key,
            a.user_id,
            a.age_group,
            a.gender,
            a.activity_pattern_json,
            a.daily_llm_budget
          from tb_ai_reader_agent a
          join tb_user u on u.user_id = a.user_id
         where a.status = 'paused'
           and u.use_yn = 'Y'
           and lower(substring_index(u.email, '@', -1)) in :allowed_domains
           and not exists (
                   select 1
                     from tb_user_social us
                    where us.user_id = u.user_id
               )
         order by a.updated_date desc, a.ai_reader_agent_id asc
         limit :limit
    """
    if req_body.apply:
        select_sql += " for update"
    paused_result = await db.execute(
        text(select_sql).bindparams(bindparam("allowed_domains", expanding=True)),
        {"allowed_domains": allowed_domains, "limit": req_body.agent_count},
    )
    agents = [dict(row) for row in paused_result.mappings().all()]
    agent_fingerprints = _resume_paused_agent_fingerprints(agents)
    dry_run_token = _expected_resume_paused_dry_run_token(
        req_body,
        schedule_date=target_date,
        agent_fingerprints=agent_fingerprints,
    )
    preview = _resume_paused_agent_preview(agents)

    if not req_body.apply:
        return {
            "applied": False,
            "schedule_date": target_date.isoformat(),
            "requested_count": req_body.agent_count,
            "available_agent_count": available_agent_count,
            "missing_agent_count": max(0, req_body.agent_count - available_agent_count),
            "dry_run_token": dry_run_token,
            "preview": preview,
        }

    if len(agents) < req_body.agent_count:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=(
                "paused AI reader resume requires "
                f"{req_body.agent_count} paused agents, found {len(agents)}."
            ),
        )
    _assert_matching_resume_paused_dry_run_token(
        req_body,
        schedule_date=target_date,
        agent_fingerprints=agent_fingerprints,
    )

    ai_reader_agent_ids = [int(agent["ai_reader_agent_id"]) for agent in agents]
    update_agent_stmt = (
        text("""
            update tb_ai_reader_agent
               set status = 'active',
                   updated_date = current_timestamp
             where ai_reader_agent_id in :ai_reader_agent_ids
               and status = 'paused'
        """)
        .bindparams(bindparam("ai_reader_agent_ids", expanding=True))
    )
    update_agent_result = await db.execute(
        update_agent_stmt,
        {"ai_reader_agent_ids": ai_reader_agent_ids},
    )

    all_windows: list[reader_agent_session_service.ReaderDailyScheduleWindow] = []
    for agent in agents:
        all_windows.extend(
            reader_agent_session_service.build_reader_daily_schedule_windows(
                ai_reader_agent_id=int(agent["ai_reader_agent_id"]),
                schedule_date=target_date,
                activity_pattern=agent["activity_pattern_json"],
            )
        )
    replace_result = await replace_reader_daily_schedule_windows_bulk(
        db,
        ai_reader_agent_ids=ai_reader_agent_ids,
        schedule_date=target_date,
        windows=all_windows,
    )

    await db.commit()
    return {
        "applied": True,
        "schedule_date": target_date.isoformat(),
        "requested_count": req_body.agent_count,
        "available_agent_count": available_agent_count,
        "reactivated_agent_count": int(getattr(update_agent_result, "rowcount", 0) or 0),
        "retired_schedule_count": replace_result["retired_count"],
        "deleted_schedule_count": replace_result["deleted_count"],
        "schedule_count": replace_result["upserted_count"],
        "preview": preview,
    }


async def _assert_ai_reader_identity_available(
    db: AsyncSession,
    *,
    expected_pairs: list[dict[str, Any]],
) -> None:
    if not expected_pairs:
        return

    expected_user_by_key = {
        str(pair["agent_key"]): int(pair["user_id"]) for pair in expected_pairs
    }
    expected_key_by_user = {
        int(pair["user_id"]): str(pair["agent_key"]) for pair in expected_pairs
    }
    stmt = (
        text("""
            select
                agent_key,
                user_id
              from tb_ai_reader_agent
             where agent_key in :agent_keys
                or user_id in :user_ids
        """)
        .bindparams(
            bindparam("agent_keys", expanding=True),
            bindparam("user_ids", expanding=True),
        )
    )
    result = await db.execute(
        stmt,
        {
            "agent_keys": list(expected_user_by_key.keys()),
            "user_ids": list(expected_key_by_user.keys()),
        },
    )
    conflicts: list[str] = []
    for row in result.mappings().all():
        agent_key = str(row.get("agent_key") or "")
        user_id = int(row.get("user_id") or 0)
        if expected_user_by_key.get(agent_key, user_id) != user_id:
            conflicts.append(f"{agent_key}:{user_id}")
            continue
        if expected_key_by_user.get(user_id, agent_key) != agent_key:
            conflicts.append(f"{agent_key}:{user_id}")

    if conflicts:
        raise CustomResponseException(
            status_code=status.HTTP_409_CONFLICT,
            message=(
                "AI reader agent identity conflict: "
                + ", ".join(sorted(conflicts)[:5])
            ),
        )


def _assert_ai_reader_agent_rows_match_expected(
    agents: list[dict[str, Any]],
    *,
    expected_pairs: list[dict[str, Any]],
) -> None:
    expected_user_by_key = {
        str(pair["agent_key"]): int(pair["user_id"]) for pair in expected_pairs
    }
    actual_user_by_key = {
        str(row.get("agent_key") or ""): int(row.get("user_id") or 0)
        for row in agents
    }
    mismatches = [
        f"{agent_key}:{actual_user_by_key.get(agent_key, 'missing')}"
        for agent_key, expected_user_id in expected_user_by_key.items()
        if actual_user_by_key.get(agent_key) != expected_user_id
    ]
    extra_keys = sorted(set(actual_user_by_key) - set(expected_user_by_key))
    if mismatches or extra_keys:
        raise CustomResponseException(
            status_code=status.HTTP_409_CONFLICT,
            message=(
                "AI reader agent post-write mismatch: "
                + ", ".join((mismatches + extra_keys)[:5])
            ),
        )


async def list_ai_reader_agents(
    *,
    schedule_date: str | None,
    status_filter: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
) -> dict[str, Any]:
    target_date = _parse_schedule_date(schedule_date)
    page = max(1, page)
    count_per_page = min(max(1, count_per_page), 200)
    offset = (page - 1) * count_per_page

    where_clauses = ["1 = 1"]
    params: dict[str, Any] = {
        "schedule_date": target_date,
        "limit": count_per_page,
        "offset": offset,
    }
    if status_filter and status_filter != "all":
        where_clauses.append("a.status = :status")
        params["status"] = status_filter
    where_sql = " and ".join(where_clauses)

    count_result = await db.execute(
        text(f"""
            select count(*) as total_count
              from tb_ai_reader_agent a
             where {where_sql}
        """),
        params,
    )
    total_count = int((count_result.mappings().one_or_none() or {}).get("total_count") or 0)

    agent_result = await db.execute(
        text(f"""
            select
                a.ai_reader_agent_id,
                a.agent_key,
                a.user_id,
                u.email,
                a.age_group,
                a.gender,
                a.activity_pattern_json,
                a.daily_llm_budget,
                a.status,
                coalesce(sum(s.session_budget), 0) as schedule_session_budget,
                coalesce(sum(s.used_session_count), 0) as used_session_count,
                count(s.ai_reader_schedule_id) as schedule_window_count,
                min(s.active_start_at) as first_active_start_at,
                max(s.active_end_at) as last_active_end_at
              from tb_ai_reader_agent a
              left join tb_user u
                on u.user_id = a.user_id
              left join tb_ai_reader_daily_schedule s
                on s.ai_reader_agent_id = a.ai_reader_agent_id
               and s.schedule_date = :schedule_date
             where {where_sql}
             group by
                a.ai_reader_agent_id,
                a.agent_key,
                a.user_id,
                u.email,
                a.age_group,
                a.gender,
                a.activity_pattern_json,
                a.daily_llm_budget,
                a.status
             order by a.agent_key asc
             limit :limit offset :offset
        """),
        params,
    )
    rows = [dict(row) for row in agent_result.mappings().all()]
    agent_ids = [row["ai_reader_agent_id"] for row in rows]
    schedule_by_agent: dict[int, list[dict[str, Any]]] = {agent_id: [] for agent_id in agent_ids}
    if agent_ids:
        schedule_stmt = (
            text("""
                select
                    ai_reader_agent_id,
                    active_start_at,
                    active_end_at,
                    session_budget,
                    used_session_count,
                    status
                  from tb_ai_reader_daily_schedule
                 where schedule_date = :schedule_date
                   and ai_reader_agent_id in :agent_ids
                 order by ai_reader_agent_id asc, active_start_at asc
            """)
            .bindparams(bindparam("agent_ids", expanding=True))
        )
        schedule_result = await db.execute(
            schedule_stmt,
            {
                "schedule_date": target_date,
                "agent_ids": agent_ids,
            },
        )
        for schedule_row in schedule_result.mappings().all():
            item = dict(schedule_row)
            agent_id = int(item.pop("ai_reader_agent_id"))
            schedule_by_agent.setdefault(agent_id, []).append(item)

    items = []
    for row in rows:
        activity_pattern = _parse_json_field(row.get("activity_pattern_json"), {})
        active_hours = activity_pattern.get("active_hours") if isinstance(activity_pattern, dict) else []
        daily_session_target = (
            activity_pattern.get("daily_session_target") if isinstance(activity_pattern, dict) else None
        )
        agent_id = int(row["ai_reader_agent_id"])
        items.append(
            {
                **row,
                "activity_pattern": activity_pattern,
                "active_hours": active_hours or [],
                "daily_session_target": daily_session_target,
                "schedules": schedule_by_agent.get(agent_id, []),
            }
        )

    return {
        "schedule_date": target_date.isoformat(),
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "items": items,
    }


async def bootstrap_ai_reader_agents(
    *,
    req_body: admin_schema.PostAiReaderBootstrapReqBody,
    db: AsyncSession,
) -> dict[str, Any]:
    target_date = _parse_schedule_date(req_body.schedule_date)
    allowed_domains = _allowed_ai_reader_account_domains()
    if not allowed_domains:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="AI reader account allowed domains are not configured.",
        )
    user_result = await db.execute(
        text("""
            select
                user_id,
                email
              from tb_user
             where use_yn = 'Y'
               and role_type = 'normal'
               and email like :email_like
               and lower(substring_index(email, '@', -1)) in :allowed_domains
               and not exists (
                       select 1
                         from tb_user_social us
                        where us.user_id = tb_user.user_id
                   )
               and not exists (
                       select 1
                         from tb_ai_reader_agent ar
                        where ar.user_id = tb_user.user_id
                   )
             order by email asc, user_id asc
             limit :limit
        """).bindparams(bindparam("allowed_domains", expanding=True)),
        {
            "email_like": f"{req_body.email_prefix}%",
            "allowed_domains": allowed_domains,
            "limit": req_body.agent_count,
        },
    )
    users = [dict(row) for row in user_result.mappings().all()]
    if req_body.apply and len(users) < req_body.agent_count and not req_body.allow_partial:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=(
                "AI reader bootstrap requires "
                f"{req_body.agent_count} existing users for prefix {req_body.email_prefix}, "
                f"found {len(users)}."
            ),
        )
    target_users = users[: req_body.agent_count]
    seeds = reader_agent_persona_service.generate_reader_agent_seeds(
        count=len(target_users),
        index_offset=req_body.agent_index_offset,
        age_group_ratios=req_body.age_group_ratios,
        gender_ratios=req_body.gender_ratios,
        active_hours=req_body.active_hours,
        daily_session_target=req_body.daily_session_target,
    )
    expected_pairs = [
        {"user_id": user["user_id"], "agent_key": seed.agent_key}
        for user, seed in zip(target_users, seeds, strict=True)
    ]
    user_fingerprints = [
        {
            "user_id": int(user["user_id"]),
            "email": str(user.get("email") or ""),
            "agent_key": seed.agent_key,
        }
        for user, seed in zip(target_users, seeds, strict=True)
    ]
    dry_run_token = _expected_bootstrap_dry_run_token(
        req_body,
        schedule_date=target_date,
        user_fingerprints=user_fingerprints,
    )
    if req_body.apply:
        _assert_matching_bootstrap_dry_run_token(
            req_body,
            schedule_date=target_date,
            user_fingerprints=user_fingerprints,
        )
    if req_body.apply:
        await _assert_ai_reader_identity_available(
            db,
            expected_pairs=expected_pairs,
        )
    preview = [
        {
            "user_id": user["user_id"],
            "email": user["email"],
            "agent_key": seed.agent_key,
            "age_group": seed.age_group,
            "gender": seed.gender,
            "activity_pattern": _parse_json_field(seed.activity_pattern_json, {}),
        }
        for user, seed in zip(target_users, seeds, strict=True)
    ]
    if not req_body.apply:
        return {
            "applied": False,
            "schedule_date": target_date.isoformat(),
            "requested_count": req_body.agent_count,
            "available_user_count": len(users),
            "missing_user_count": max(0, req_body.agent_count - len(users)),
            "dry_run_token": dry_run_token,
            "preview": preview,
        }

    if not target_users:
        return {
            "applied": True,
            "schedule_date": target_date.isoformat(),
            "requested_count": req_body.agent_count,
            "applied_count": 0,
            "schedule_count": 0,
            "preview": [],
        }

    await db.execute(
        text("""
            insert into tb_ai_reader_agent
                (
                    user_id,
                    agent_key,
                    age_group,
                    gender,
                    persona_json,
                    taste_memory_json,
                    activity_pattern_json,
                    status,
                    daily_llm_budget
                )
            values
                (
                    :user_id,
                    :agent_key,
                    :age_group,
                    :gender,
                    :persona_json,
                    :taste_memory_json,
                    :activity_pattern_json,
                    'active',
                    :daily_llm_budget
                )
            on duplicate key update
                age_group = values(age_group),
                gender = values(gender),
                persona_json = values(persona_json),
                taste_memory_json = values(taste_memory_json),
                activity_pattern_json = values(activity_pattern_json),
                status = 'active',
                daily_llm_budget = values(daily_llm_budget),
                updated_date = current_timestamp
        """),
        [
            {
                "user_id": user["user_id"],
                "agent_key": seed.agent_key,
                "age_group": seed.age_group,
                "gender": seed.gender,
                "persona_json": seed.persona_json,
                "taste_memory_json": seed.taste_memory_json,
                "activity_pattern_json": seed.activity_pattern_json,
                "daily_llm_budget": req_body.daily_llm_budget,
            }
            for user, seed in zip(target_users, seeds, strict=True)
        ],
    )

    agent_keys = [seed.agent_key for seed in seeds]
    agent_stmt = (
        text("""
            select
                ai_reader_agent_id,
                agent_key,
                user_id,
                activity_pattern_json
              from tb_ai_reader_agent
             where agent_key in :agent_keys
        """)
        .bindparams(bindparam("agent_keys", expanding=True))
    )
    agent_result = await db.execute(agent_stmt, {"agent_keys": agent_keys})
    agents = [dict(row) for row in agent_result.mappings().all()]
    _assert_ai_reader_agent_rows_match_expected(
        agents,
        expected_pairs=expected_pairs,
    )

    all_windows: list[reader_agent_session_service.ReaderDailyScheduleWindow] = []
    for agent in agents:
        all_windows.extend(
            reader_agent_session_service.build_reader_daily_schedule_windows(
                ai_reader_agent_id=int(agent["ai_reader_agent_id"]),
                schedule_date=target_date,
                activity_pattern=agent["activity_pattern_json"],
            )
        )
    replace_result = await replace_reader_daily_schedule_windows_bulk(
        db,
        ai_reader_agent_ids=[int(agent["ai_reader_agent_id"]) for agent in agents],
        schedule_date=target_date,
        windows=all_windows,
    )

    await db.commit()
    return {
        "applied": True,
        "schedule_date": target_date.isoformat(),
        "requested_count": req_body.agent_count,
        "available_user_count": len(users),
        "applied_count": len(agents),
        "schedule_count": replace_result["upserted_count"],
        "preview": preview,
    }


async def update_ai_reader_agent_schedule(
    *,
    ai_reader_agent_id: int,
    req_body: admin_schema.PutAiReaderScheduleReqBody,
    db: AsyncSession,
) -> dict[str, Any]:
    if req_body.replace_running:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="replace_running is not allowed for AI reader schedule updates.",
        )
    target_date = _parse_schedule_date(req_body.schedule_date)
    agent_result = await db.execute(
        text("""
            select
                ai_reader_agent_id,
                agent_key,
                user_id,
                age_group,
                gender,
                activity_pattern_json,
                daily_llm_budget,
                status
              from tb_ai_reader_agent
             where ai_reader_agent_id = :ai_reader_agent_id
             limit 1
        """),
        {"ai_reader_agent_id": ai_reader_agent_id},
    )
    agent = agent_result.mappings().one_or_none()
    if not agent:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="AI reader agent not found.",
        )

    current_pattern = _parse_json_field(agent.get("activity_pattern_json"), {})
    if not isinstance(current_pattern, dict):
        current_pattern = {}
    active_hours = list(req_body.active_hours)
    next_pattern = {
        **current_pattern,
        "active_hours": active_hours,
        "sleep_hours": _sleep_hours(active_hours),
        "daily_session_target": req_body.daily_session_target,
    }
    next_status = req_body.status or agent.get("status") or "active"
    next_daily_llm_budget = req_body.daily_llm_budget or int(agent.get("daily_llm_budget") or 8)

    await db.execute(
        text("""
            update tb_ai_reader_agent
               set activity_pattern_json = :activity_pattern_json,
                   daily_llm_budget = :daily_llm_budget,
                   status = :status,
                   updated_date = current_timestamp
             where ai_reader_agent_id = :ai_reader_agent_id
        """),
        {
            "activity_pattern_json": json.dumps(next_pattern, ensure_ascii=False),
            "daily_llm_budget": next_daily_llm_budget,
            "status": next_status,
            "ai_reader_agent_id": ai_reader_agent_id,
        },
    )

    windows = reader_agent_session_service.build_reader_daily_schedule_windows(
        ai_reader_agent_id=ai_reader_agent_id,
        schedule_date=target_date,
        activity_pattern=next_pattern,
    )
    replace_result = await replace_reader_daily_schedule_windows(
        db,
        ai_reader_agent_id=ai_reader_agent_id,
        schedule_date=target_date,
        windows=windows,
        replace_running=req_body.replace_running,
    )
    await db.commit()
    return {
        "schedule_date": target_date.isoformat(),
        "agent": {
            "ai_reader_agent_id": ai_reader_agent_id,
            "agent_key": agent.get("agent_key"),
            "user_id": agent.get("user_id"),
            "age_group": agent.get("age_group"),
            "gender": agent.get("gender"),
            "active_hours": active_hours,
            "daily_session_target": req_body.daily_session_target,
            "daily_llm_budget": next_daily_llm_budget,
            "status": next_status,
        },
        "schedule_count": len(windows),
        "deleted_schedule_count": replace_result["deleted_count"],
        "upserted_schedule_count": replace_result["upserted_count"],
        "schedules": _schedule_window_payload(windows),
    }
