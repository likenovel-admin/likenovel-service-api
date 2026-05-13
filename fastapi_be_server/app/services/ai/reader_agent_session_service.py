import hashlib
import inspect
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import settings
from app.services.ai import reader_agent_action_service as action_service
from app.services.ai import reader_agent_decision_service as decision_service


logger = logging.getLogger(__name__)

BAYESIAN_LOOSE_STOP_EVIDENCE_WEIGHT = 0.1


class InvalidReaderSessionError(ValueError):
    pass


class ReaderLlmDecisionAlreadyReservedError(InvalidReaderSessionError):
    pass


@dataclass(frozen=True)
class ReaderClaimedSession:
    ai_reader_schedule_id: int
    ai_reader_agent_id: int
    user_id: int
    age_group: str
    gender: str
    persona_json: str
    taste_memory_json: str | None
    activity_pattern_json: str
    claimed_session_no: int = 1


@dataclass(frozen=True)
class ReaderSessionDecisionResult:
    llm_decision_id: int
    actions: list[decision_service.ReaderActionIntent]

    @property
    def enqueued_action_count(self) -> int:
        return len(self.actions)


@dataclass(frozen=True)
class ReaderPreparedSessionDecision:
    snapshot: dict[str, Any]
    decision: decision_service.ReaderLlmDecision
    actions: list[decision_service.ReaderActionIntent]


@dataclass(frozen=True)
class ReaderDailyScheduleWindow:
    ai_reader_agent_id: int
    schedule_date: date
    active_start_at: datetime
    active_end_at: datetime
    session_budget: int


DecisionFunc = Callable[
    [ReaderClaimedSession, AsyncSession],
    Awaitable[ReaderSessionDecisionResult],
]
SessionSuccessFunc = Callable[..., Awaitable[None]]
SessionFailedFunc = Callable[..., Awaitable[None]]
PostSuccessFunc = Callable[[AsyncSession], Awaitable[None]]

BAYESIAN_BOOKMARK_SUGGEST_THRESHOLD = 0.62
BAYESIAN_RECOMMEND_SUGGEST_THRESHOLD = 0.55
BAYESIAN_EVALUATE_SUGGEST_THRESHOLD = 0.55


def _allowed_ai_reader_account_domains() -> list[str]:
    return [
        domain.strip().lower()
        for domain in settings.AI_READER_ACCOUNT_ALLOWED_DOMAINS.split(",")
        if domain.strip()
    ]


def build_reader_daily_schedule_windows(
    *,
    ai_reader_agent_id: int,
    schedule_date: date,
    activity_pattern: str | dict[str, Any],
) -> list[ReaderDailyScheduleWindow]:
    if ai_reader_agent_id <= 0:
        raise InvalidReaderSessionError("ai_reader_agent_id must be positive")
    pattern = _parse_json_field(activity_pattern)
    if not isinstance(pattern, dict):
        raise InvalidReaderSessionError("activity_pattern must be an object")

    active_hours = _normalize_active_hours(pattern.get("active_hours"))
    segments = _active_hour_segments(active_hours)
    if not segments:
        raise InvalidReaderSessionError("active_hours is required")

    daily_session_target = _clamp_int(pattern.get("daily_session_target"), 1, 8, 1)
    selected_segments = _select_schedule_segments(
        segments,
        daily_session_target=daily_session_target,
    )
    session_budgets = _distribute_session_budget(
        selected_segments,
        daily_session_target=daily_session_target,
    )

    windows: list[ReaderDailyScheduleWindow] = []
    for segment, session_budget in zip(selected_segments, session_budgets, strict=True):
        start_hour, end_hour, duration_hours = segment
        jitter_minutes = _schedule_jitter_minutes(
            ai_reader_agent_id=ai_reader_agent_id,
            schedule_date=schedule_date,
            start_hour=start_hour,
        )
        start_at = datetime.combine(schedule_date, time(start_hour, 0)) + timedelta(
            minutes=jitter_minutes
        )
        end_date = schedule_date
        if duration_hours == 24 or end_hour <= start_hour:
            end_date = schedule_date + timedelta(days=1)
        end_at = datetime.combine(end_date, time(end_hour, 0)) + timedelta(
            minutes=jitter_minutes
        )
        windows.append(
            ReaderDailyScheduleWindow(
                ai_reader_agent_id=ai_reader_agent_id,
                schedule_date=schedule_date,
                active_start_at=start_at,
                active_end_at=end_at,
                session_budget=session_budget,
            )
        )
    return sorted(windows, key=lambda window: window.active_start_at)


async def upsert_reader_daily_schedule_windows(
    db: AsyncSession,
    windows: list[ReaderDailyScheduleWindow],
) -> int:
    if not windows:
        return 0

    result = await db.execute(
        text("""
            insert into tb_ai_reader_daily_schedule
                (
                    ai_reader_agent_id,
                    schedule_date,
                    active_start_at,
                    active_end_at,
                    session_budget
                )
            values
                (
                    :ai_reader_agent_id,
                    :schedule_date,
                    :active_start_at,
                    :active_end_at,
                    :session_budget
                )
            on duplicate key update
                active_end_at = values(active_end_at),
                session_budget = values(session_budget),
                status = case
                    when status = 'running' then status
                    when status = 'done' then status
                    when used_session_count >= values(session_budget) then 'done'
                    else 'ready'
                end,
                used_session_count = case
                    when status = 'running' then used_session_count
                    when used_session_count > 0 then used_session_count
                    else 0
                end,
                locked_by = case when status = 'running' then locked_by else null end,
                locked_at = case when status = 'running' then locked_at else null end,
                error_message = null,
                updated_date = current_timestamp
        """),
        [
            {
                "ai_reader_agent_id": window.ai_reader_agent_id,
                "schedule_date": window.schedule_date,
                "active_start_at": window.active_start_at,
                "active_end_at": window.active_end_at,
                "session_budget": window.session_budget,
            }
            for window in windows
        ],
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def ensure_reader_daily_schedules(
    db: AsyncSession,
    *,
    schedule_dates: list[date],
    limit: int = 2000,
) -> dict[str, int]:
    normalized_dates = sorted({schedule_date for schedule_date in schedule_dates})
    if not normalized_dates:
        return {
            "date_count": 0,
            "missing_agent_count": 0,
            "created_schedule_count": 0,
        }
    if limit < 1 or limit > 5000:
        raise InvalidReaderSessionError("limit must be between 1 and 5000")

    missing_agent_count = 0
    created_schedule_count = 0
    for schedule_date in normalized_dates:
        result = await db.execute(
            text("""
                select
                    a.ai_reader_agent_id,
                    a.activity_pattern_json
                  from tb_ai_reader_agent a
                  join tb_user u
                    on u.user_id = a.user_id
                 where a.status = 'active'
                   and u.use_yn = 'Y'
                   and lower(substring_index(u.email, '@', -1)) in :allowed_domains
                   and not exists (
                        select 1
                          from tb_user_social us
                         where us.user_id = u.user_id
                   )
                   and not exists (
                        select 1
                          from tb_ai_reader_daily_schedule s
                         where s.ai_reader_agent_id = a.ai_reader_agent_id
                           and s.schedule_date = :schedule_date
                   )
                 order by a.ai_reader_agent_id asc
                 limit :limit
            """).bindparams(bindparam("allowed_domains", expanding=True)),
            {
                "schedule_date": schedule_date,
                "limit": limit,
                "allowed_domains": _allowed_ai_reader_account_domains(),
            },
        )
        rows = [dict(row) for row in result.mappings().all()]
        missing_agent_count += len(rows)
        windows: list[ReaderDailyScheduleWindow] = []
        for row in rows:
            windows.extend(
                build_reader_daily_schedule_windows(
                    ai_reader_agent_id=int(row["ai_reader_agent_id"]),
                    schedule_date=schedule_date,
                    activity_pattern=row["activity_pattern_json"],
                )
            )
        created_schedule_count += await upsert_reader_daily_schedule_windows(db, windows)

    return {
        "date_count": len(normalized_dates),
        "missing_agent_count": missing_agent_count,
        "created_schedule_count": created_schedule_count,
    }


async def claim_due_reader_sessions(
    db: AsyncSession,
    *,
    worker_id: str,
    limit: int,
    lease_timeout_seconds: int = 900,
) -> list[ReaderClaimedSession]:
    async with _transaction_scope(db):
        return await _claim_due_reader_sessions(
            db,
            worker_id=worker_id,
            limit=limit,
            lease_timeout_seconds=lease_timeout_seconds,
        )


async def cleanup_expired_stale_reader_sessions(
    db: AsyncSession,
    *,
    lease_timeout_seconds: int,
) -> int:
    if lease_timeout_seconds < 1 or lease_timeout_seconds > 86400:
        raise InvalidReaderSessionError("lease_timeout_seconds must be between 1 and 86400")

    await db.execute(
        text("""
            update tb_ai_reader_llm_decision d
              join tb_ai_reader_daily_schedule s
                on s.ai_reader_agent_id = d.ai_reader_agent_id
               and d.session_id like concat(s.ai_reader_schedule_id, ':%')
               set d.decision_status = 'failed'
                 , d.error_message = 'expired stale schedule lease'
                 , d.updated_date = current_timestamp
             where s.status = 'running'
               and s.locked_at is not null
               and s.locked_at <= timestampadd(second, -:lease_timeout_seconds, current_timestamp)
               and s.active_end_at <= current_timestamp
               and d.decision_status = 'pending'
        """),
        {"lease_timeout_seconds": lease_timeout_seconds},
    )
    result = await db.execute(
        text("""
            update tb_ai_reader_daily_schedule
               set status = 'failed'
                 , locked_by = null
                 , locked_at = null
                 , error_message = 'expired stale schedule lease'
                 , updated_date = current_timestamp
             where status = 'running'
               and locked_at is not null
               and locked_at <= timestampadd(second, -:lease_timeout_seconds, current_timestamp)
               and active_end_at <= current_timestamp
        """),
        {"lease_timeout_seconds": lease_timeout_seconds},
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def cleanup_budget_exhausted_ready_reader_sessions(db: AsyncSession) -> int:
    result = await db.execute(
        text("""
            update tb_ai_reader_daily_schedule s
              join tb_ai_reader_agent a
                on a.ai_reader_agent_id = s.ai_reader_agent_id
              join tb_user u
                on u.user_id = a.user_id
               set s.status = 'done'
                 , s.locked_by = null
                 , s.locked_at = null
                 , s.error_message = 'daily llm budget exhausted'
                 , s.updated_date = current_timestamp
             where s.status = 'ready'
               and s.used_session_count < s.session_budget
               and s.active_start_at <= current_timestamp
               and s.active_end_at > current_timestamp
               and a.status = 'active'
               and u.use_yn = 'Y'
               and lower(substring_index(u.email, '@', -1)) in :allowed_domains
               and not exists (
                    select 1
                      from tb_user_social us
                     where us.user_id = u.user_id
               )
               and (
                    select count(*)
                      from tb_ai_reader_llm_decision d
                     where d.ai_reader_agent_id = a.ai_reader_agent_id
                       and d.created_date >= current_date()
                       and d.created_date < current_date() + interval 1 day
                       and d.decision_status in ('pending', 'success', 'failed')
               ) >= a.daily_llm_budget
        """).bindparams(bindparam("allowed_domains", expanding=True)),
        {"allowed_domains": _allowed_ai_reader_account_domains()},
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def _claim_due_reader_sessions(
    db: AsyncSession,
    *,
    worker_id: str,
    limit: int,
    lease_timeout_seconds: int,
) -> list[ReaderClaimedSession]:
    if not worker_id.strip():
        raise InvalidReaderSessionError("worker_id is required")
    if limit < 1 or limit > 100:
        raise InvalidReaderSessionError("limit must be between 1 and 100")
    if lease_timeout_seconds < 1 or lease_timeout_seconds > 86400:
        raise InvalidReaderSessionError("lease_timeout_seconds must be between 1 and 86400")

    await cleanup_expired_stale_reader_sessions(
        db,
        lease_timeout_seconds=lease_timeout_seconds,
    )
    await cleanup_budget_exhausted_ready_reader_sessions(db)

    stale_rows = await _select_claimable_reader_session_rows(
        db,
        index_name="idx_ai_reader_daily_schedule_stale",
        condition_sql="""
            s.status = 'running'
            and s.locked_at is not null
            and s.locked_at <= timestampadd(second, -:lease_timeout_seconds, current_timestamp)
        """,
        limit=limit,
        lease_timeout_seconds=lease_timeout_seconds,
    )
    rows = stale_rows
    remaining_limit = limit - len(rows)
    if remaining_limit > 0:
        rows.extend(
            await _select_claimable_reader_session_rows(
                db,
                index_name="idx_ai_reader_daily_schedule_due",
                condition_sql="""
                    s.status = 'ready'
                    and s.used_session_count < s.session_budget
                """,
                limit=remaining_limit,
                lease_timeout_seconds=lease_timeout_seconds,
            )
        )
    if not rows:
        return []

    schedule_ids = [row.get("ai_reader_schedule_id") for row in rows]
    result = await db.execute(
        text("""
            update tb_ai_reader_daily_schedule
               set used_session_count = used_session_count + case
                    when status = 'ready' then 1
                    else 0
                   end
                 , status = 'running'
                 , locked_by = :worker_id
                 , locked_at = current_timestamp
             where ai_reader_schedule_id in :schedule_ids
               and status in ('ready', 'running')
        """).bindparams(bindparam("schedule_ids", expanding=True)),
        {"worker_id": worker_id[:100], "schedule_ids": schedule_ids},
    )
    _ensure_rows_changed(result, "claim_due_reader_sessions", len(schedule_ids))

    return [
        ReaderClaimedSession(
            ai_reader_schedule_id=row.get("ai_reader_schedule_id"),
            ai_reader_agent_id=row.get("ai_reader_agent_id"),
            user_id=row.get("user_id"),
            age_group=row.get("age_group"),
            gender=row.get("gender"),
            persona_json=row.get("persona_json"),
            taste_memory_json=row.get("taste_memory_json"),
            activity_pattern_json=row.get("activity_pattern_json"),
            claimed_session_no=int(row.get("claimed_session_no") or 1),
        )
        for row in rows
    ]


async def _select_claimable_reader_session_rows(
    db: AsyncSession,
    *,
    index_name: str,
    condition_sql: str,
    limit: int,
    lease_timeout_seconds: int,
):
    result = await db.execute(
        text(f"""
            select s.ai_reader_schedule_id
                 , a.ai_reader_agent_id
                 , a.user_id
                 , a.age_group
                 , a.gender
                 , a.persona_json
                 , a.taste_memory_json
                 , a.activity_pattern_json
                 , s.used_session_count + case
                    when s.status = 'ready' then 1
                    else 0
                   end as claimed_session_no
              from tb_ai_reader_daily_schedule s force index ({index_name})
              straight_join tb_ai_reader_agent a
                on a.ai_reader_agent_id = s.ai_reader_agent_id
              join tb_user u
                on u.user_id = a.user_id
             where {condition_sql}
               and s.active_start_at <= current_timestamp
               and s.active_end_at > current_timestamp
               and a.status = 'active'
               and u.use_yn = 'Y'
               and lower(substring_index(u.email, '@', -1)) in :allowed_domains
               and not exists (
                    select 1
                      from tb_user_social us
                     where us.user_id = u.user_id
               )
               and (
                    (
                        select count(*)
                          from tb_ai_reader_llm_decision d
                         where d.ai_reader_agent_id = a.ai_reader_agent_id
                           and d.created_date >= current_date()
                           and d.created_date < current_date() + interval 1 day
                           and d.decision_status in ('pending', 'success', 'failed')
                    ) < a.daily_llm_budget
                    or (
                        s.status = 'running'
                        and exists (
                            select 1
                              from tb_ai_reader_llm_decision d_existing
                             where d_existing.ai_reader_agent_id = a.ai_reader_agent_id
                               and d_existing.user_id = a.user_id
                               and d_existing.session_id = concat(
                                    s.ai_reader_schedule_id,
                                    ':',
                                    greatest(s.used_session_count, 1)
                               )
                               and d_existing.prompt_version = :prompt_version
                               and d_existing.decision_status = 'pending'
                        )
                    )
               )
             order by s.active_start_at, s.ai_reader_schedule_id
             limit :limit
             for update skip locked
        """).bindparams(bindparam("allowed_domains", expanding=True)),
        {
            "limit": limit,
            "lease_timeout_seconds": lease_timeout_seconds,
            "prompt_version": decision_service.READER_DECISION_PROMPT_VERSION,
            "allowed_domains": _allowed_ai_reader_account_domains(),
        },
    )
    return result.mappings().all()


async def process_claimed_reader_session(
    session: ReaderClaimedSession,
    db: AsyncSession,
    *,
    worker_id: str,
    decision_func: DecisionFunc | None = None,
    success_func: SessionSuccessFunc | None = None,
    failed_func: SessionFailedFunc | None = None,
    llm_call: decision_service.ReaderLlmCall | None = None,
) -> ReaderSessionDecisionResult:
    async def mark_success(
        tx_db: AsyncSession,
        *,
        schedule_id: int,
        worker_id: str,
    ) -> None:
        await mark_reader_session_succeeded(
            tx_db,
            schedule_id=schedule_id,
            worker_id=worker_id,
        )

    async def mark_failed(
        tx_db: AsyncSession,
        *,
        schedule_id: int,
        worker_id: str,
        error_message: str,
    ) -> None:
        await mark_reader_session_failed(
            tx_db,
            schedule_id=schedule_id,
            worker_id=worker_id,
            error_message=error_message,
        )

    mark_succeeded = success_func or mark_success
    mark_failed_func = failed_func or mark_failed
    try:
        if decision_func is not None:
            result = await decision_func(session, db)
            async with _transaction_scope(db):
                await mark_succeeded(
                    db,
                    schedule_id=session.ai_reader_schedule_id,
                    worker_id=worker_id,
                )
        else:
            result = await _process_reader_session_decision(
                session,
                db,
                llm_call=llm_call,
                post_success=lambda tx_db: mark_succeeded(
                    tx_db,
                    schedule_id=session.ai_reader_schedule_id,
                    worker_id=worker_id,
                ),
            )
        return result
    except Exception as exc:
        async with _transaction_scope(db):
            await mark_failed_func(
                db,
                schedule_id=session.ai_reader_schedule_id,
                worker_id=worker_id,
                error_message=str(exc) or exc.__class__.__name__,
            )
        raise


async def mark_reader_session_succeeded(
    db: AsyncSession,
    *,
    schedule_id: int,
    worker_id: str,
) -> None:
    if not worker_id.strip():
        raise InvalidReaderSessionError("worker_id is required")
    result = await db.execute(
        text("""
            update tb_ai_reader_daily_schedule
               set status = if(greatest(used_session_count, 1) >= session_budget, 'done', 'ready')
                 , used_session_count = greatest(used_session_count, 1)
                 , locked_by = null
                 , locked_at = null
                 , error_message = null
             where ai_reader_schedule_id = :schedule_id
               and status = 'running'
               and locked_by = :worker_id
        """),
        {"schedule_id": schedule_id, "worker_id": worker_id[:100]},
    )
    _ensure_rows_changed(result, "mark_reader_session_succeeded", 1)


async def mark_reader_session_failed(
    db: AsyncSession,
    *,
    schedule_id: int,
    worker_id: str,
    error_message: str,
) -> None:
    if not worker_id.strip():
        raise InvalidReaderSessionError("worker_id is required")
    result = await db.execute(
        text("""
            update tb_ai_reader_daily_schedule
               set status = 'failed'
                 , locked_by = null
                 , locked_at = null
                 , error_message = :error_message
             where ai_reader_schedule_id = :schedule_id
               and status = 'running'
               and locked_by = :worker_id
        """),
        {
            "schedule_id": schedule_id,
            "worker_id": worker_id[:100],
            "error_message": error_message[:1000],
        },
    )
    _ensure_rows_changed(result, "mark_reader_session_failed", 1)


async def process_reader_session_decision(
    session: ReaderClaimedSession,
    db: AsyncSession,
    *,
    llm_call: decision_service.ReaderLlmCall | None = None,
) -> ReaderSessionDecisionResult:
    return await _process_reader_session_decision(session, db, llm_call=llm_call)


async def _process_reader_session_decision(
    session: ReaderClaimedSession,
    db: AsyncSession,
    *,
    llm_call: decision_service.ReaderLlmCall | None = None,
    post_success: PostSuccessFunc | None = None,
) -> ReaderSessionDecisionResult:
    snapshot = await build_reader_decision_snapshot(session, db)
    await _commit_active_transaction(db)

    async with _transaction_scope(db):
        llm_decision_id = await reserve_reader_llm_decision(
            session=session,
            snapshot=snapshot,
            db=db,
        )

    try:
        llm_decision = await decision_service.request_reader_decision(
            snapshot,
            llm_call=llm_call,
        )
        context = decision_service.ReaderActionContext(
            agent_id=session.ai_reader_agent_id,
            user_id=session.user_id,
            session_id=_reader_session_id(session),
            product_id=snapshot["product"]["product_id"],
            episode_id=snapshot["episode"]["episode_id"],
        )
        actions = decision_service.build_action_intents(llm_decision, context)
    except Exception as exc:
        async with _transaction_scope(db):
            await mark_reader_llm_decision_failed(
                db,
                llm_decision_id=llm_decision_id,
                error_message=str(exc) or exc.__class__.__name__,
            )
        raise

    prepared = ReaderPreparedSessionDecision(
        snapshot=snapshot,
        decision=llm_decision,
        actions=actions,
    )
    async with _transaction_scope(db):
        await mark_reader_llm_decision_succeeded(
            db,
            llm_decision_id=llm_decision_id,
            decision=llm_decision,
        )
        result = await persist_reader_session_decision(
            session=session,
            prepared=prepared,
            llm_decision_id=llm_decision_id,
            db=db,
        )
        if post_success is not None:
            await post_success(db)
        return result


async def prepare_reader_session_decision(
    session: ReaderClaimedSession,
    db: AsyncSession,
    *,
    llm_call: decision_service.ReaderLlmCall | None = None,
) -> ReaderPreparedSessionDecision:
    snapshot = await build_reader_decision_snapshot(session, db)
    llm_decision = await decision_service.request_reader_decision(
        snapshot,
        llm_call=llm_call,
    )
    context = decision_service.ReaderActionContext(
        agent_id=session.ai_reader_agent_id,
        user_id=session.user_id,
        session_id=_reader_session_id(session),
        product_id=snapshot["product"]["product_id"],
        episode_id=snapshot["episode"]["episode_id"],
    )
    actions = decision_service.build_action_intents(llm_decision, context)
    return ReaderPreparedSessionDecision(
        snapshot=snapshot,
        decision=llm_decision,
        actions=actions,
    )


async def persist_reader_session_decision(
    *,
    session: ReaderClaimedSession,
    prepared: ReaderPreparedSessionDecision,
    llm_decision_id: int | None = None,
    db: AsyncSession,
) -> ReaderSessionDecisionResult:
    if llm_decision_id is None:
        llm_decision_id = await _save_reader_llm_decision(
            session=session,
            snapshot=prepared.snapshot,
            decision=prepared.decision,
            db=db,
        )
    if prepared.actions:
        await _enqueue_reader_actions(
            session=session,
            snapshot=prepared.snapshot,
            llm_decision_id=llm_decision_id,
            decision=prepared.decision,
            actions=prepared.actions,
            db=db,
        )
    return ReaderSessionDecisionResult(
        llm_decision_id=llm_decision_id,
        actions=prepared.actions,
    )


async def build_reader_decision_snapshot(
    session: ReaderClaimedSession,
    db: AsyncSession,
) -> dict[str, Any]:
    persona = _parse_json_field(session.persona_json)
    taste_memory = _parse_json_field(session.taste_memory_json)
    activity_pattern = _parse_json_field(session.activity_pattern_json)
    taste_factors = await _get_reader_taste_factors(session.user_id, db)
    target = await _select_reader_target_episode(
        session,
        db,
        persona=persona,
        taste_factors=taste_factors,
    )
    state = await _get_reader_product_state(session, target["product_id"], db)
    return {
        "agent": {
            "ai_reader_agent_id": session.ai_reader_agent_id,
            "user_id": session.user_id,
            "age_group": session.age_group,
            "gender": session.gender,
            "persona": persona,
            "taste_memory": taste_memory,
            "activity_pattern": activity_pattern,
        },
        "product": {
            "product_id": target["product_id"],
            "title": target.get("title"),
            "status_code": target.get("status_code"),
            "early_episode_summary_text": target.get("episode_summary_text"),
            "public_counts": {
                "hit": target.get("count_hit") or 0,
                "bookmark": target.get("count_bookmark") or 0,
                "recommend": target.get("count_recommend") or 0,
            },
        },
        "episode": {
            "episode_id": target["episode_id"],
            "episode_no": target.get("episode_no"),
            "episode_title": target.get("episode_title"),
        },
        "dna": {
            "protagonist_type_tags": _parse_json_field(target.get("protagonist_type_tags"), []),
            "protagonist_job_tags": _parse_json_field(target.get("protagonist_job_tags"), []),
            "protagonist_material_tags": _parse_json_field(target.get("protagonist_material_tags"), []),
            "worldview_tags": _parse_json_field(target.get("worldview_tags"), []),
            "axis_style_tags": _parse_json_field(target.get("axis_style_tags"), []),
            "axis_romance_tags": _parse_json_field(target.get("axis_romance_tags"), []),
        },
        "state": state,
        "taste_factors": taste_factors,
        "engagement_context": _build_reader_engagement_context(
            target,
            persona=persona,
            state=state,
            taste_factors=taste_factors,
        ),
    }


async def _select_reader_target_episode(
    session: ReaderClaimedSession,
    db: AsyncSession,
    *,
    persona: dict[str, Any],
    taste_factors: list[dict[str, Any]],
) -> dict[str, Any]:
    result = await db.execute(
        text("""
            select p.product_id
                 , p.title
                 , p.status_code
                 , p.count_hit
                 , p.count_bookmark
                 , p.count_recommend
                 , e.episode_id
                 , e.episode_no
                 , e.episode_title
                 , m.episode_summary_text
                 , m.protagonist_goal_primary
                 , m.protagonist_type_tags
                 , m.protagonist_job_tags
                 , m.protagonist_material_tags
                 , m.worldview_tags
                 , m.axis_style_tags
                 , m.axis_romance_tags
                 , ps.ai_reader_product_state_id
              from tb_product p
              join tb_product_ai_metadata m
                on m.product_id = p.product_id
              join tb_product_episode e
                on e.product_id = p.product_id
              left join tb_ai_reader_product_state ps
                on ps.ai_reader_agent_id = :ai_reader_agent_id
               and ps.product_id = p.product_id
             where p.open_yn = 'Y'
               and coalesce(p.blind_yn, 'N') = 'N'
               and e.use_yn = 'Y'
               and e.open_yn = 'Y'
               and (e.publish_reserve_date is null or e.publish_reserve_date <= current_timestamp)
               and (
                    coalesce(e.price_type, 'free') = 'free'
                    or (
                        p.price_type = 'paid'
                        and p.paid_episode_no is not null
                        and p.paid_episode_no > 0
                        and e.episode_no < p.paid_episode_no
                    )
               )
               and m.analysis_status = 'success'
               and coalesce(m.exclude_from_recommend_yn, 'N') = 'N'
               and coalesce(ps.state, 'reading') = 'reading'
               and e.episode_id = (
                    select e_next.episode_id
                      from tb_product_episode e_next
                     where e_next.product_id = p.product_id
                       and e_next.use_yn = 'Y'
                       and e_next.open_yn = 'Y'
                       and (
                            e_next.publish_reserve_date is null
                            or e_next.publish_reserve_date <= current_timestamp
                       )
                       and (
                            coalesce(e_next.price_type, 'free') = 'free'
                            or (
                                p.price_type = 'paid'
                                and p.paid_episode_no is not null
                                and p.paid_episode_no > 0
                                and e_next.episode_no < p.paid_episode_no
                            )
                       )
                       and e_next.episode_no > coalesce((
                            select current_episode.episode_no
                              from tb_product_episode current_episode
                             where current_episode.episode_id = ps.current_episode_id
                             limit 1
                       ), 0)
                     order by e_next.episode_no, e_next.episode_id
                     limit 1
               )
             order by case when ps.ai_reader_product_state_id is null then 1 else 0 end
                    , case
                        when ps.ai_reader_product_state_id is null then crc32(
                            concat(
                                :ai_reader_agent_id,
                                ':',
                                :user_id,
                                ':',
                                :ai_reader_schedule_id,
                                ':',
                                p.product_id
                            )
                        )
                        else 0
                      end
                    , ps.updated_date desc
                    , e.episode_no
             limit 200
        """),
        {
            "ai_reader_agent_id": session.ai_reader_agent_id,
            "user_id": session.user_id,
            "ai_reader_schedule_id": session.ai_reader_schedule_id,
        },
    )
    rows = result.mappings().all()
    if not rows:
        raise InvalidReaderSessionError("no readable target episode")
    return _choose_reader_candidate(
        [dict(row) for row in rows],
        persona=persona,
        taste_factors=taste_factors,
        session=session,
    )


async def _get_reader_product_state(
    session: ReaderClaimedSession,
    product_id: int,
    db: AsyncSession,
) -> dict[str, Any]:
    result = await db.execute(
        text("""
            select state
                 , read_episode_count
                 , bookmarked_yn
                 , recommended_yn
                 , evaluated_yn
              from tb_ai_reader_product_state
             where ai_reader_agent_id = :ai_reader_agent_id
               and product_id = :product_id
             limit 1
        """),
        {"ai_reader_agent_id": session.ai_reader_agent_id, "product_id": product_id},
    )
    row = result.mappings().one_or_none()
    if row:
        return dict(row)
    return {
        "state": "new",
        "read_episode_count": 0,
        "bookmarked_yn": "N",
        "recommended_yn": "N",
        "evaluated_yn": "N",
    }


async def _get_reader_taste_factors(user_id: int, db: AsyncSession) -> list[dict[str, Any]]:
    result = await db.execute(
        text("""
            select factor_type
                 , factor_key
                 , score
              from tb_user_taste_factor_score
             where user_id = :user_id
             order by score desc, updated_date desc
             limit 30
        """),
        {"user_id": user_id},
    )
    return [dict(row) for row in result.mappings().all()]


def _score_reader_candidate(
    row: dict[str, Any],
    *,
    persona: dict[str, Any],
    taste_factors: list[dict[str, Any]],
) -> float:
    state_score = 10.0 if row.get("ai_reader_product_state_id") else 0.0
    persona_score = _score_candidate_by_persona(row, persona)
    taste_score = _score_candidate_by_taste(row, taste_factors)
    popularity_score = min(float(row.get("count_hit") or 0) / 100000.0, 1.0) * 0.05
    return state_score + persona_score + taste_score + popularity_score


def _choose_reader_candidate(
    rows: list[dict[str, Any]],
    *,
    persona: dict[str, Any],
    taste_factors: list[dict[str, Any]],
    session: ReaderClaimedSession,
) -> dict[str, Any]:
    if not rows:
        raise InvalidReaderSessionError("no readable target episode")

    continuing_rows = [row for row in rows if row.get("ai_reader_product_state_id")]

    def ranking(row: dict[str, Any], *, jitter_scale: float) -> float:
        base_score = _score_reader_candidate(
            row,
            persona=persona,
            taste_factors=taste_factors,
        )
        return base_score + _stable_reader_candidate_jitter(session, row) * jitter_scale

    if continuing_rows:
        return max(continuing_rows, key=lambda row: ranking(row, jitter_scale=0.02))

    novelty_seeking = _clamp_probability(
        _safe_float(persona.get("novelty_seeking"), 0.0)
    )
    if novelty_seeking < 0.55:
        return max(rows, key=lambda row: ranking(row, jitter_scale=0.35))

    scored_rows = sorted(
        (
            (
                _score_reader_candidate(
                    row,
                    persona=persona,
                    taste_factors=taste_factors,
                ),
                row,
            )
            for row in rows
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    pool_size = min(
        len(scored_rows),
        3 + int(round((novelty_seeking - 0.55) / 0.45 * 7)),
    )
    exploration_pool = [row for _, row in scored_rows[: max(pool_size, 1)]]
    return max(
        exploration_pool,
        key=lambda row: _stable_reader_candidate_jitter(session, row),
    )


def _stable_reader_candidate_jitter(
    session: ReaderClaimedSession,
    row: dict[str, Any],
) -> float:
    product_id = row.get("product_id") or ""
    episode_id = row.get("episode_id") or ""
    seed = (
        f"{session.ai_reader_schedule_id}:"
        f"{session.ai_reader_agent_id}:"
        f"{session.user_id}:"
        f"{product_id}:"
        f"{episode_id}"
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(0xFFFFFFFFFFFF)


def _score_candidate_by_persona(row: dict[str, Any], persona: dict[str, Any]) -> float:
    axis_bias = persona.get("initial_axis_bias")
    if not isinstance(axis_bias, dict):
        return 0.0

    score = 0.0
    for axis, labels in _candidate_axis_labels(row).items():
        raw_axis_bias = axis_bias.get(axis, {})
        if not isinstance(raw_axis_bias, dict):
            continue
        for label in labels:
            score += _safe_float(raw_axis_bias.get(label), 0.0)
    return score


def _score_candidate_by_taste(
    row: dict[str, Any],
    taste_factors: list[dict[str, Any]],
) -> float:
    labels_by_axis = _candidate_axis_labels(row)
    all_labels = set().union(*labels_by_axis.values()) if labels_by_axis else set()
    score = 0.0
    for factor in taste_factors:
        factor_key = str(factor.get("factor_key") or "").strip()
        if not factor_key or factor_key not in all_labels:
            continue
        score += _safe_float(factor.get("score"), 0.0)
    return score


def _build_reader_engagement_context(
    row: dict[str, Any],
    *,
    persona: dict[str, Any],
    state: dict[str, Any],
    taste_factors: list[dict[str, Any]],
) -> dict[str, Any]:
    persona_raw_score = _score_candidate_by_persona(row, persona)
    taste_raw_score = _score_candidate_by_taste(row, taste_factors)
    read_episode_count = _clamp_int(
        state.get("read_episode_count"),
        0,
        1000,
        0,
    )

    persona_match_score = min(max(persona_raw_score / 4.0, 0.0), 1.0)
    taste_match_score = min(max(taste_raw_score / 5.0, 0.0), 1.0)
    progress_score = min(read_episode_count / 4.0, 1.0)
    engagement_score = min(
        1.0,
        persona_match_score * 0.65
        + taste_match_score * 0.15
        + progress_score * 0.20,
    )

    bookmark_threshold = min(
        max(_safe_float(persona.get("bookmark_threshold"), 0.65), 0.0),
        1.0,
    )
    recommend_threshold = min(
        max(_safe_float(persona.get("recommend_threshold"), 0.78), 0.0),
        1.0,
    )
    rating_threshold = min(
        max(0.55 + _safe_float(persona.get("rating_severity"), 0.4) * 0.1, 0.0),
        1.0,
    )

    already_bookmarked = state.get("bookmarked_yn") == "Y"
    already_recommended = state.get("recommended_yn") == "Y"
    already_evaluated = state.get("evaluated_yn") == "Y"
    bayesian_action_model = _build_bayesian_action_model(
        row,
        persona=persona,
        read_episode_count=read_episode_count,
        engagement_score=engagement_score,
        persona_match_score=persona_match_score,
        taste_match_score=taste_match_score,
        bookmark_threshold=bookmark_threshold,
        recommend_threshold=recommend_threshold,
        rating_threshold=rating_threshold,
        already_bookmarked=already_bookmarked,
        already_recommended=already_recommended,
        already_evaluated=already_evaluated,
    )
    bookmark_posterior_hint = _action_posterior_hint(
        bayesian_action_model,
        "bookmark",
    )
    recommend_posterior_hint = _action_posterior_hint(
        bayesian_action_model,
        "recommend",
    )
    evaluate_posterior_hint = _action_posterior_hint(
        bayesian_action_model,
        "evaluate",
    )
    return {
        "engagement_score_hint": round(engagement_score, 3),
        "persona_match_score": round(persona_match_score, 3),
        "taste_match_score": round(taste_match_score, 3),
        "progress_score": round(progress_score, 3),
        "read_episode_count": read_episode_count,
        "matched_persona_labels": _matched_persona_labels(row, persona),
        "bayesian_action_model": bayesian_action_model,
        "action_affordances": {
            "bookmark": {
                "current": "Y" if already_bookmarked else "N",
                "threshold": round(bookmark_threshold, 3),
                "score": round(engagement_score, 3),
                "posterior_hint": round(bookmark_posterior_hint, 3),
                "posterior_threshold": BAYESIAN_BOOKMARK_SUGGEST_THRESHOLD,
                "suggested": (not already_bookmarked)
                and bookmark_posterior_hint >= BAYESIAN_BOOKMARK_SUGGEST_THRESHOLD,
            },
            "recommend": {
                "current": "Y" if already_recommended else "N",
                "threshold": round(recommend_threshold, 3),
                "score": round(engagement_score, 3),
                "posterior_hint": round(recommend_posterior_hint, 3),
                "posterior_threshold": BAYESIAN_RECOMMEND_SUGGEST_THRESHOLD,
                "suggested": (not already_recommended)
                and recommend_posterior_hint >= BAYESIAN_RECOMMEND_SUGGEST_THRESHOLD,
            },
            "evaluate": {
                "current": "Y" if already_evaluated else "N",
                "threshold": round(rating_threshold, 3),
                "score": round(engagement_score, 3),
                "posterior_hint": round(evaluate_posterior_hint, 3),
                "posterior_threshold": BAYESIAN_EVALUATE_SUGGEST_THRESHOLD,
                "min_read_episode_count": 3,
                "suggested": (not already_evaluated)
                and read_episode_count >= 3
                and evaluate_posterior_hint >= BAYESIAN_EVALUATE_SUGGEST_THRESHOLD,
            },
        },
    }


def _action_posterior_hint(
    bayesian_action_model: dict[str, Any],
    action_key: str,
) -> float:
    probabilities = bayesian_action_model.get("probabilities")
    if not isinstance(probabilities, dict):
        return 0.0
    item = probabilities.get(action_key)
    if not isinstance(item, dict):
        return 0.0
    return _clamp_probability(item.get("posterior_hint"))


def _build_bayesian_action_model(
    row: dict[str, Any],
    *,
    persona: dict[str, Any],
    read_episode_count: int,
    engagement_score: float,
    persona_match_score: float,
    taste_match_score: float,
    bookmark_threshold: float,
    recommend_threshold: float,
    rating_threshold: float,
    already_bookmarked: bool,
    already_recommended: bool,
    already_evaluated: bool,
) -> dict[str, Any]:
    loose_stop_weight = _clamp_probability(
        _safe_float(
            persona.get("loose_stop_weight"),
            BAYESIAN_LOOSE_STOP_EVIDENCE_WEIGHT,
        )
    )
    progress_score = min(read_episode_count / 8.0, 1.0)
    patience = _clamp_probability(_safe_float(persona.get("patience"), 0.55))
    rating_severity = _clamp_probability(
        _safe_float(persona.get("rating_severity"), 0.4)
    )

    continue_prior = _clamp_probability(
        0.18
        + persona_match_score * 0.34
        + taste_match_score * 0.14
        + patience * 0.22
        + progress_score * 0.12
    )
    bookmark_prior = 0.0 if already_bookmarked else _threshold_probability(
        engagement_score,
        bookmark_threshold,
        progress_score=progress_score,
    )
    recommend_prior = 0.0 if already_recommended else _threshold_probability(
        engagement_score,
        recommend_threshold,
        progress_score=progress_score,
        action_lightness_bonus=0.08,
    )
    evaluate_prior = 0.0 if already_evaluated or read_episode_count + 1 < 3 else _threshold_probability(
        engagement_score,
        rating_threshold,
        progress_score=progress_score,
        action_lightness_bonus=-rating_severity * 0.05,
    )

    current_episode_no = _clamp_int(row.get("episode_no"), 0, 1000000, 0)
    return {
        "method": "bayesian_conditional_probability",
        "loose_stop_evidence_weight": loose_stop_weight,
        "current_episode_no": current_episode_no or None,
        "probabilities": {
            "continue_next_episode": _bayesian_probability_item(
                continue_prior,
                engagement_score,
                negative_evidence_weight=loose_stop_weight,
                target_episode_no=current_episode_no + 1,
            ),
            "bookmark": _bayesian_probability_item(
                bookmark_prior,
                engagement_score,
                target_episode_no=current_episode_no,
            ),
            "recommend": _bayesian_probability_item(
                recommend_prior,
                engagement_score,
                target_episode_no=current_episode_no,
            ),
            "evaluate": _bayesian_probability_item(
                evaluate_prior,
                engagement_score,
                target_episode_no=current_episode_no,
            ),
        },
    }


def _threshold_probability(
    engagement_score: float,
    threshold: float,
    *,
    progress_score: float,
    action_lightness_bonus: float = 0.0,
) -> float:
    return _clamp_probability(
        0.18
        + engagement_score * 0.55
        - threshold * 0.22
        + progress_score * 0.12
        + action_lightness_bonus
    )


def _bayesian_probability_item(
    prior: float,
    engagement_score: float,
    *,
    negative_evidence_weight: float = 0.2,
    target_episode_no: int | None = None,
) -> dict[str, Any]:
    posterior_hint = _bayesian_update_probability(
        prior,
        likelihood_if_yes=0.5 + _clamp_probability(engagement_score) * 0.45,
        likelihood_if_no=0.5
        + (1.0 - _clamp_probability(engagement_score)) * negative_evidence_weight,
    )
    item: dict[str, Any] = {
        "prior": round(prior, 3),
        "posterior_hint": round(posterior_hint, 3),
    }
    if target_episode_no is not None:
        item["target_episode_no"] = target_episode_no
    return item


def _bayesian_update_probability(
    prior: float,
    *,
    likelihood_if_yes: float,
    likelihood_if_no: float,
) -> float:
    prior = _clamp_probability(prior)
    likelihood_if_yes = _clamp_probability(likelihood_if_yes)
    likelihood_if_no = _clamp_probability(likelihood_if_no)
    numerator = likelihood_if_yes * prior
    denominator = numerator + likelihood_if_no * (1.0 - prior)
    if denominator <= 0:
        return prior
    return _clamp_probability(numerator / denominator)


def _matched_persona_labels(row: dict[str, Any], persona: dict[str, Any]) -> list[str]:
    axis_bias = persona.get("initial_axis_bias")
    if not isinstance(axis_bias, dict):
        return []

    matched: list[str] = []
    for axis, labels in _candidate_axis_labels(row).items():
        raw_axis_bias = axis_bias.get(axis, {})
        if not isinstance(raw_axis_bias, dict):
            continue
        for label in sorted(labels):
            if _safe_float(raw_axis_bias.get(label), 0.0) > 0:
                matched.append(label)
    return matched[:30]


def _candidate_axis_labels(row: dict[str, Any]) -> dict[str, set[str]]:
    return {
        "세": set(_parse_json_field(row.get("worldview_tags"), [])),
        "직": set(_parse_json_field(row.get("protagonist_job_tags"), [])),
        "능": set(_parse_json_field(row.get("protagonist_material_tags"), [])),
        "연": set(_parse_json_field(row.get("axis_romance_tags"), [])),
        "작": set(_parse_json_field(row.get("axis_style_tags"), [])),
        "타": set(_parse_json_field(row.get("protagonist_type_tags"), [])),
        "목": {str(row.get("protagonist_goal_primary") or "").strip()} - {""},
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp_probability(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, parsed))


def _clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _normalize_active_hours(value: Any) -> set[int]:
    if not isinstance(value, list):
        raise InvalidReaderSessionError("activity_pattern.active_hours must be a list")
    hours: set[int] = set()
    for raw_hour in value:
        if isinstance(raw_hour, bool):
            raise InvalidReaderSessionError("active_hours contains invalid hour")
        try:
            hour = int(raw_hour)
        except (TypeError, ValueError) as exc:
            raise InvalidReaderSessionError("active_hours contains invalid hour") from exc
        if hour < 0 or hour > 23:
            raise InvalidReaderSessionError("active_hours contains invalid hour")
        hours.add(hour)
    return hours


def _active_hour_segments(active_hours: set[int]) -> list[tuple[int, int, int]]:
    if not active_hours:
        return []
    if len(active_hours) == 24:
        return [(0, 0, 24)]

    starts = sorted(
        hour for hour in active_hours if ((hour - 1) % 24) not in active_hours
    )
    segments: list[tuple[int, int, int]] = []
    for start_hour in starts:
        duration = 0
        cursor = start_hour
        while cursor in active_hours:
            duration += 1
            cursor = (cursor + 1) % 24
        segments.append((start_hour, cursor, duration))
    return segments


def _select_schedule_segments(
    segments: list[tuple[int, int, int]],
    *,
    daily_session_target: int,
) -> list[tuple[int, int, int]]:
    if daily_session_target >= len(segments):
        return sorted(segments, key=lambda segment: segment[0])

    selected = sorted(segments, key=lambda segment: (-segment[2], segment[0]))[
        :daily_session_target
    ]
    return sorted(selected, key=lambda segment: segment[0])


def _distribute_session_budget(
    segments: list[tuple[int, int, int]],
    *,
    daily_session_target: int,
) -> list[int]:
    budgets = [1 for _ in segments]
    remaining = max(0, daily_session_target - len(segments))
    if remaining == 0:
        return budgets

    ranked_indexes = sorted(
        range(len(segments)),
        key=lambda index: (-segments[index][2], segments[index][0]),
    )
    for index in range(remaining):
        budgets[ranked_indexes[index % len(ranked_indexes)]] += 1
    return budgets


def _schedule_jitter_minutes(
    *,
    ai_reader_agent_id: int,
    schedule_date: date,
    start_hour: int,
) -> int:
    raw = f"{ai_reader_agent_id}|{schedule_date.isoformat()}|{start_hour}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 60


async def reserve_reader_llm_decision(
    *,
    session: ReaderClaimedSession,
    snapshot: dict[str, Any],
    db: AsyncSession,
) -> int:
    request_hash = _reader_llm_request_hash(snapshot)
    budget_result = await db.execute(
        text("""
            select a.daily_llm_budget
                 , (
                    select count(*)
                      from tb_ai_reader_llm_decision d
                     where d.ai_reader_agent_id = a.ai_reader_agent_id
                       and d.created_date >= current_date()
                       and d.created_date < current_date() + interval 1 day
                       and d.decision_status in ('pending', 'success', 'failed')
                 ) as used_llm_count
              from tb_ai_reader_agent a
             where a.ai_reader_agent_id = :ai_reader_agent_id
               and a.user_id = :user_id
               and a.status = 'active'
             for update
        """),
        {
            "ai_reader_agent_id": session.ai_reader_agent_id,
            "user_id": session.user_id,
        },
    )
    budget_row = budget_result.mappings().one_or_none()
    if budget_row is None:
        raise InvalidReaderSessionError("active ai reader agent not found")
    daily_budget = int(budget_row.get("daily_llm_budget") or 0)
    used_count = int(budget_row.get("used_llm_count") or 0)
    if used_count >= daily_budget:
        existing_pending_id = await _read_existing_pending_reader_llm_decision_id(
            session=session,
            request_hash=request_hash,
            db=db,
        )
        if existing_pending_id is not None:
            return existing_pending_id
        raise InvalidReaderSessionError("daily llm budget exceeded")

    snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    result = await db.execute(
        text("""
            insert into tb_ai_reader_llm_decision
                (
                    ai_reader_agent_id,
                    user_id,
                    session_id,
                    product_id,
                    episode_id,
                    prompt_version,
                    model_name,
                    request_hash,
                    input_snapshot_json,
                    decision_status
                )
            values
                (
                    :ai_reader_agent_id,
                    :user_id,
                    :session_id,
                    :product_id,
                    :episode_id,
                    :prompt_version,
                    :model_name,
                    :request_hash,
                    :input_snapshot_json,
                    'pending'
                )
            on duplicate key update
                ai_reader_llm_decision_id = last_insert_id(ai_reader_llm_decision_id),
                updated_date = updated_date
        """),
        {
            "ai_reader_agent_id": session.ai_reader_agent_id,
            "user_id": session.user_id,
            "session_id": _reader_session_id(session),
            "product_id": snapshot["product"]["product_id"],
            "episode_id": snapshot["episode"]["episode_id"],
            "prompt_version": decision_service.READER_DECISION_PROMPT_VERSION,
            "model_name": decision_service.reader_llm_model_name(),
            "request_hash": request_hash,
            "input_snapshot_json": snapshot_json,
        },
    )
    llm_decision_id = _resolve_inserted_primary_key(
        result,
        "reserve_reader_llm_decision",
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        existing_pending_id = await _read_existing_pending_reader_llm_decision_id(
            session=session,
            request_hash=request_hash,
            db=db,
        )
        if existing_pending_id is not None:
            return existing_pending_id
        raise ReaderLlmDecisionAlreadyReservedError(
            f"llm decision already reserved: {llm_decision_id}"
        )
    return llm_decision_id


async def _read_existing_pending_reader_llm_decision_id(
    *,
    session: ReaderClaimedSession,
    request_hash: str,
    db: AsyncSession,
) -> int | None:
    result = await db.execute(
        text("""
            select ai_reader_llm_decision_id
                 , decision_status
              from tb_ai_reader_llm_decision
             where ai_reader_agent_id = :ai_reader_agent_id
               and user_id = :user_id
               and session_id = :session_id
               and prompt_version = :prompt_version
               and request_hash = :request_hash
               and decision_status = 'pending'
             limit 1
        """),
        {
            "ai_reader_agent_id": session.ai_reader_agent_id,
            "user_id": session.user_id,
            "session_id": _reader_session_id(session),
            "prompt_version": decision_service.READER_DECISION_PROMPT_VERSION,
            "request_hash": request_hash,
        },
    )
    row = result.mappings().one_or_none()
    if row is None or row.get("decision_status") != "pending":
        return None
    return int(row.get("ai_reader_llm_decision_id"))


async def mark_reader_llm_decision_succeeded(
    db: AsyncSession,
    *,
    llm_decision_id: int,
    decision: decision_service.ReaderLlmDecision,
) -> None:
    decision_json = json.dumps(asdict(decision), ensure_ascii=False, sort_keys=True)
    result = await db.execute(
        text("""
            update tb_ai_reader_llm_decision
               set decision_json = :decision_json
                 , decision_status = 'success'
                 , error_message = null
                 , updated_date = current_timestamp
             where ai_reader_llm_decision_id = :llm_decision_id
               and decision_status = 'pending'
        """),
        {
            "llm_decision_id": llm_decision_id,
            "decision_json": decision_json,
        },
    )
    _ensure_rows_changed(result, "mark_reader_llm_decision_succeeded", 1)


async def mark_reader_llm_decision_failed(
    db: AsyncSession,
    *,
    llm_decision_id: int,
    error_message: str,
) -> None:
    result = await db.execute(
        text("""
            update tb_ai_reader_llm_decision
               set decision_status = 'failed'
                 , error_message = :error_message
                 , updated_date = current_timestamp
             where ai_reader_llm_decision_id = :llm_decision_id
               and decision_status = 'pending'
        """),
        {
            "llm_decision_id": llm_decision_id,
            "error_message": error_message[:1000],
        },
    )
    _ensure_rows_changed(result, "mark_reader_llm_decision_failed", 1)


async def _save_reader_llm_decision(
    *,
    session: ReaderClaimedSession,
    snapshot: dict[str, Any],
    decision: decision_service.ReaderLlmDecision,
    db: AsyncSession,
) -> int:
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    decision_json = json.dumps(asdict(decision), ensure_ascii=False, sort_keys=True)
    request_hash = _reader_llm_request_hash(snapshot)
    result = await db.execute(
        text("""
            insert into tb_ai_reader_llm_decision
                (
                    ai_reader_agent_id,
                    user_id,
                    session_id,
                    product_id,
                    episode_id,
                    prompt_version,
                    model_name,
                    request_hash,
                    input_snapshot_json,
                    decision_json,
                    decision_status
                )
            values
                (
                    :ai_reader_agent_id,
                    :user_id,
                    :session_id,
                    :product_id,
                    :episode_id,
                    :prompt_version,
                    :model_name,
                    :request_hash,
                    :input_snapshot_json,
                    :decision_json,
                    'success'
                )
            on duplicate key update
                ai_reader_llm_decision_id = last_insert_id(ai_reader_llm_decision_id),
                decision_json = values(decision_json),
                decision_status = 'success',
                updated_date = current_timestamp
        """),
        {
            "ai_reader_agent_id": session.ai_reader_agent_id,
            "user_id": session.user_id,
            "session_id": _reader_session_id(session),
            "product_id": snapshot["product"]["product_id"],
            "episode_id": snapshot["episode"]["episode_id"],
            "prompt_version": decision_service.READER_DECISION_PROMPT_VERSION,
            "model_name": decision_service.reader_llm_model_name(),
            "request_hash": request_hash,
            "input_snapshot_json": snapshot_json,
            "decision_json": decision_json,
        },
    )
    return _resolve_inserted_primary_key(result, "_save_reader_llm_decision")


def _reader_llm_request_hash(snapshot: dict[str, Any]) -> str:
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(
        (
            decision_service.READER_DECISION_PROMPT_VERSION
            + "|"
            + snapshot_json
        ).encode("utf-8")
    ).hexdigest()


def _resolve_inserted_primary_key(result: Any, operation: str) -> int:
    try:
        inserted_primary_key = getattr(result, "inserted_primary_key", None)
    except Exception:
        inserted_primary_key = None
    if inserted_primary_key:
        return int(inserted_primary_key[0])
    lastrowid = getattr(result, "lastrowid", None)
    if lastrowid:
        return int(lastrowid)
    raise InvalidReaderSessionError(f"failed to resolve primary key for {operation}")


def _reader_session_id(session: ReaderClaimedSession) -> str:
    return f"{session.ai_reader_schedule_id}:{max(int(session.claimed_session_no or 1), 1)}"


async def _enqueue_reader_actions(
    *,
    session: ReaderClaimedSession,
    snapshot: dict[str, Any],
    llm_decision_id: int,
    decision: decision_service.ReaderLlmDecision,
    actions: list[decision_service.ReaderActionIntent],
    db: AsyncSession,
) -> None:
    decision_json = json.dumps(asdict(decision), ensure_ascii=False, sort_keys=True)
    action_rows = [
        {
            "idempotency_key": action.idempotency_key,
            "active_scope_key": decision_service.build_active_action_scope_key(
                agent_id=session.ai_reader_agent_id,
                user_id=session.user_id,
                product_id=snapshot["product"]["product_id"],
                episode_id=snapshot["episode"]["episode_id"],
                action_type=action.action_type,
                target_value=action.target_value,
            ),
            "ai_reader_agent_id": session.ai_reader_agent_id,
            "user_id": session.user_id,
            "product_id": snapshot["product"]["product_id"],
            "episode_id": snapshot["episode"]["episode_id"],
            "action_type": action.action_type,
            "target_value": action.target_value,
            "llm_decision_id": llm_decision_id,
            "decision_json": decision_json,
        }
        for action in actions
    ]
    if not action_rows:
        return
    await action_service.cleanup_stale_max_attempt_actions(
        db,
        active_scope_keys=[row["active_scope_key"] for row in action_rows],
        limit=max(len(action_rows), 1),
    )
    result = await db.execute(
        text("""
            insert into tb_ai_reader_action_queue
                (
                    idempotency_key,
                    active_scope_key,
                    ai_reader_agent_id,
                    user_id,
                    product_id,
                    episode_id,
                    action_type,
                    target_value,
                    llm_decision_id,
                    decision_json
                )
            values
                (
                    :idempotency_key,
                    :active_scope_key,
                    :ai_reader_agent_id,
                    :user_id,
                    :product_id,
                    :episode_id,
                    :action_type,
                    :target_value,
                    :llm_decision_id,
                    :decision_json
                )
            on duplicate key update
                active_scope_key = active_scope_key
        """),
        action_rows,
    )
    affected_count = int(getattr(result, "rowcount", 0) or 0)
    if affected_count < len(actions):
        logger.info(
            "ai reader action enqueue skipped duplicate active/idempotent intents",
            extra={
                "ai_reader_agent_id": session.ai_reader_agent_id,
                "ai_reader_schedule_id": session.ai_reader_schedule_id,
                "requested_action_count": len(actions),
                "affected_action_count": affected_count,
            },
        )


def _parse_json_field(value: Any, default: Any | None = None) -> Any:
    if default is None:
        default = {}
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _ensure_rows_changed(result, operation: str, expected_count: int) -> None:
    if getattr(result, "rowcount", None) != expected_count:
        raise InvalidReaderSessionError(
            f"{operation} did not update expected rows: {expected_count}"
        )


def _ensure_min_rows_changed(result, operation: str, minimum_count: int) -> None:
    if getattr(result, "rowcount", None) < minimum_count:
        raise InvalidReaderSessionError(
            f"{operation} did not update minimum rows: {minimum_count}"
        )


@asynccontextmanager
async def _transaction_scope(db: AsyncSession):
    if _has_active_transaction(db):
        yield
        return

    async with db.begin():
        yield


async def _commit_active_transaction(db: AsyncSession) -> None:
    if _has_active_transaction(db):
        await db.commit()


def _has_active_transaction(db: AsyncSession) -> bool:
    in_transaction = getattr(db, "in_transaction", None)
    if not callable(in_transaction):
        return False
    try:
        result = in_transaction()
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            return False
        return bool(result)
    except TypeError:
        return False
