from contextlib import asynccontextmanager
from dataclasses import dataclass
import hashlib
import inspect
import json
import logging
from typing import AsyncContextManager, Awaitable, Callable

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import settings
from app.services.ai.reader_agent_decision_service import EVALUATION_CODES


YN_VALUES = {"Y", "N"}
DEFAULT_ACTION_LEASE_TIMEOUT_SECONDS = 300
DEFAULT_ACTION_MAX_ATTEMPT_COUNT = 5
DEFAULT_STALE_ACTION_CLEANUP_LIMIT = 100
DEFAULT_STALE_ACTION_TERMINAL_GRACE_SECONDS = 300
MAX_FOLLOWUP_READS_PER_DECISION = 1
MIN_EVALUATION_READ_EPISODE_COUNT = 3
READ_POOL_GUARD_RETRY_DELAY_SECONDS = 30
READ_POOL_GUARD_RETRY_REASONS = frozenset(
    {
        "product_not_read",
        "episode_not_read",
        "insufficient_read_pool",
    }
)
logger = logging.getLogger(__name__)


class InvalidReaderActionError(ValueError):
    pass


class ReaderActionLockBusyError(InvalidReaderActionError):
    pass


class UnsupportedReaderActionError(ValueError):
    pass


@dataclass(frozen=True)
class ReaderQueuedAction:
    ai_reader_action_id: int
    ai_reader_agent_id: int
    user_id: int
    product_id: int
    episode_id: int | None
    action_type: str
    target_value: str | None
    llm_decision_id: int | None = None


@dataclass(frozen=True)
class ReaderActionApplyResult:
    ai_reader_action_id: int
    action_type: str
    applied: bool
    reason: str


ApplyFunc = Callable[
    [ReaderQueuedAction, AsyncSession],
    Awaitable[ReaderActionApplyResult],
]
SuccessFunc = Callable[..., Awaitable[None]]
FailedFunc = Callable[..., Awaitable[None]]
PinnedSessionFactory = Callable[[AsyncSession], AsyncContextManager[AsyncSession]]


async def process_claimed_action(
    action: ReaderQueuedAction,
    db: AsyncSession,
    *,
    worker_id: str,
    apply_func: ApplyFunc | None = None,
    success_func: SuccessFunc | None = None,
    failed_func: FailedFunc | None = None,
    pinned_session_factory: PinnedSessionFactory | None = None,
) -> ReaderActionApplyResult:
    async with _action_processing_session(
        db,
        pinned_session_factory=pinned_session_factory,
    ) as action_db:
        return await _process_claimed_action_in_session(
            action,
            action_db,
            worker_id=worker_id,
            apply_func=apply_func,
            success_func=success_func,
            failed_func=failed_func,
        )


async def _process_claimed_action_in_session(
    action: ReaderQueuedAction,
    db: AsyncSession,
    *,
    worker_id: str,
    apply_func: ApplyFunc | None = None,
    success_func: SuccessFunc | None = None,
    failed_func: FailedFunc | None = None,
) -> ReaderActionApplyResult:
    apply_action = apply_func or apply_reader_action

    async def mark_success(
        tx_db: AsyncSession,
        *,
        action_id: int,
        worker_id: str,
    ) -> None:
        await mark_action_succeeded(
            tx_db,
            action_id=action_id,
            worker_id=worker_id,
        )

    async def mark_failed(
        tx_db: AsyncSession,
        *,
        action_id: int,
        worker_id: str,
        error_message: str,
    ) -> None:
        await mark_action_failed(
            tx_db,
            action_id=action_id,
            worker_id=worker_id,
            error_message=error_message,
        )

    mark_succeeded = success_func or mark_success
    mark_failed_action = failed_func or mark_failed
    lock_key: str | None = None
    try:
        async with db.begin():
            lock_key = await _acquire_action_target_lock(action, db)
            if not await _is_action_agent_active(action, db):
                result = _result(action, applied=False, reason="agent_paused")
                await mark_failed_action(
                    db,
                    action_id=action.ai_reader_action_id,
                    worker_id=worker_id,
                    error_message=result.reason,
                )
                return result
            result = await apply_action(action, db)
            if await _should_retry_after_pending_read_pool_action(action, result, db):
                await mark_action_retry_later(
                    db,
                    action_id=action.ai_reader_action_id,
                    worker_id=worker_id,
                    retry_delay_seconds=READ_POOL_GUARD_RETRY_DELAY_SECONDS,
                    error_message=result.reason,
                )
            else:
                await mark_succeeded(
                    db,
                    action_id=action.ai_reader_action_id,
                    worker_id=worker_id,
                )
            return result
    except ReaderActionLockBusyError:
        async with db.begin():
            await mark_action_retry_later(
                db,
                action_id=action.ai_reader_action_id,
                worker_id=worker_id,
                retry_delay_seconds=_lock_busy_retry_delay_seconds(action),
                error_message="action target lock busy",
            )
        return _result(action, applied=False, reason="lock_busy")
    except Exception as exc:
        try:
            async with db.begin():
                await mark_failed_action(
                    db,
                    action_id=action.ai_reader_action_id,
                    worker_id=worker_id,
                    error_message=str(exc) or exc.__class__.__name__,
            )
        except Exception:
            logger.exception(
                "failed to mark ai reader action as failed",
                extra={
                    "ai_reader_action_id": action.ai_reader_action_id,
                    "worker_id": worker_id,
                },
            )
        raise
    finally:
        if lock_key is not None:
            try:
                await _release_action_target_lock(lock_key, db)
                await _commit_active_transaction(db)
            except Exception:
                logger.exception(
                    "failed to release ai reader action target lock",
                    extra={
                        "ai_reader_action_id": action.ai_reader_action_id,
                        "worker_id": worker_id,
                    },
                )


@asynccontextmanager
async def _action_processing_session(
    db: AsyncSession,
    *,
    pinned_session_factory: PinnedSessionFactory | None,
):
    if pinned_session_factory is not None:
        async with pinned_session_factory(db) as pinned_db:
            yield pinned_db
        return

    if not isinstance(db, AsyncSession):
        yield db
        return

    bind = getattr(db, "bind", None)
    if bind is None or not hasattr(bind, "connect"):
        yield db
        return

    async with bind.connect() as connection:
        pinned_db = AsyncSession(bind=connection, autoflush=False)
        try:
            yield pinned_db
        finally:
            await _rollback_active_transaction(pinned_db)
            await pinned_db.close()


async def claim_due_actions(
    db: AsyncSession,
    *,
    worker_id: str,
    limit: int,
    lease_timeout_seconds: int = DEFAULT_ACTION_LEASE_TIMEOUT_SECONDS,
    max_attempt_count: int = DEFAULT_ACTION_MAX_ATTEMPT_COUNT,
) -> list[ReaderQueuedAction]:
    async with _transaction_scope(db):
        actions = await _claim_due_actions(
            db,
            worker_id=worker_id,
            limit=limit,
            lease_timeout_seconds=lease_timeout_seconds,
            max_attempt_count=max_attempt_count,
        )
    await _commit_active_transaction(db)
    return actions


async def _claim_due_actions(
    db: AsyncSession,
    *,
    worker_id: str,
    limit: int,
    lease_timeout_seconds: int,
    max_attempt_count: int,
) -> list[ReaderQueuedAction]:
    if not worker_id.strip():
        raise InvalidReaderActionError("worker_id is required")
    if limit < 1 or limit > 100:
        raise InvalidReaderActionError("limit must be between 1 and 100")
    if lease_timeout_seconds < 1 or lease_timeout_seconds > 86400:
        raise InvalidReaderActionError("lease_timeout_seconds must be between 1 and 86400")
    if max_attempt_count < 1 or max_attempt_count > 20:
        raise InvalidReaderActionError("max_attempt_count must be between 1 and 20")

    await cleanup_stale_max_attempt_actions(
        db,
        lease_timeout_seconds=lease_timeout_seconds,
        max_attempt_count=max_attempt_count,
    )

    result = await db.execute(
        text("""
            select q.ai_reader_action_id
                 , q.ai_reader_agent_id
                 , q.user_id
                 , q.product_id
                 , q.episode_id
                 , q.action_type
                 , q.target_value
                 , q.llm_decision_id
              from tb_ai_reader_action_queue q
              join tb_ai_reader_agent a
                on a.ai_reader_agent_id = q.ai_reader_agent_id
               and a.status = 'active'
             where (
                    (
                        q.status = 'queued'
                        and q.available_at <= current_timestamp
                    )
                    or (
                        q.status = 'running'
                        and q.locked_at is not null
                        and q.locked_at <= timestampadd(second, -:lease_timeout_seconds, current_timestamp)
                        and q.attempt_count < :max_attempt_count
                    )
               )
             order by q.available_at, q.ai_reader_action_id
             limit :limit
             for update skip locked
        """),
        {
            "limit": limit,
            "lease_timeout_seconds": lease_timeout_seconds,
            "max_attempt_count": max_attempt_count,
        },
    )
    rows = result.mappings().all()
    if not rows:
        return []

    action_ids = [row.get("ai_reader_action_id") for row in rows]
    result = await db.execute(
        text("""
            update tb_ai_reader_action_queue q
              join tb_ai_reader_agent a
                on a.ai_reader_agent_id = q.ai_reader_agent_id
               and a.status = 'active'
               set q.status = 'running'
                 , q.locked_by = :worker_id
                 , q.locked_at = current_timestamp
                 , q.attempt_count = q.attempt_count + 1
             where q.ai_reader_action_id in :action_ids
               and q.status in ('queued', 'running')
        """).bindparams(bindparam("action_ids", expanding=True)),
        {"worker_id": worker_id[:100], "action_ids": action_ids},
    )
    _ensure_rows_changed(result, "claim_due_actions", expected_count=len(action_ids))
    return [
        ReaderQueuedAction(
            ai_reader_action_id=row.get("ai_reader_action_id"),
            ai_reader_agent_id=row.get("ai_reader_agent_id"),
            user_id=row.get("user_id"),
            product_id=row.get("product_id"),
            episode_id=row.get("episode_id"),
            action_type=row.get("action_type"),
            target_value=row.get("target_value"),
            llm_decision_id=row.get("llm_decision_id"),
        )
        for row in rows
    ]


async def cleanup_stale_max_attempt_actions(
    db: AsyncSession,
    *,
    lease_timeout_seconds: int = DEFAULT_ACTION_LEASE_TIMEOUT_SECONDS,
    max_attempt_count: int = DEFAULT_ACTION_MAX_ATTEMPT_COUNT,
    limit: int = DEFAULT_STALE_ACTION_CLEANUP_LIMIT,
    active_scope_keys: list[str] | None = None,
    terminal_grace_seconds: int = DEFAULT_STALE_ACTION_TERMINAL_GRACE_SECONDS,
) -> int:
    if lease_timeout_seconds < 1 or lease_timeout_seconds > 86400:
        raise InvalidReaderActionError("lease_timeout_seconds must be between 1 and 86400")
    if max_attempt_count < 1 or max_attempt_count > 20:
        raise InvalidReaderActionError("max_attempt_count must be between 1 and 20")
    if limit < 1 or limit > 1000:
        raise InvalidReaderActionError("limit must be between 1 and 1000")
    if terminal_grace_seconds < 0 or terminal_grace_seconds > 86400:
        raise InvalidReaderActionError("terminal_grace_seconds must be between 0 and 86400")

    scope_keys = _normalize_active_scope_keys(active_scope_keys)
    if active_scope_keys is not None and not scope_keys:
        return 0

    params = {
        "lease_timeout_seconds": lease_timeout_seconds,
        "max_attempt_count": max_attempt_count,
        "cleanup_limit": limit,
        "terminal_grace_seconds": terminal_grace_seconds,
    }
    scope_filter = "and active_scope_key in :active_scope_keys" if scope_keys else ""
    statement = text(f"""
        select ai_reader_action_id
          from tb_ai_reader_action_queue force index (idx_ai_reader_action_queue_stale)
         where status = 'running'
           and locked_at is not null
           and locked_at <= timestampadd(
                   second,
                   -(:lease_timeout_seconds + :terminal_grace_seconds),
                   current_timestamp
               )
           and attempt_count >= :max_attempt_count
           {scope_filter}
         order by locked_at, ai_reader_action_id
         limit :cleanup_limit
         for update skip locked
    """)
    if scope_keys:
        params["active_scope_keys"] = scope_keys
        statement = statement.bindparams(bindparam("active_scope_keys", expanding=True))

    result = await db.execute(statement, params)
    rows = result.mappings().all()
    action_ids = [row.get("ai_reader_action_id") for row in rows]
    if not action_ids:
        return 0

    result = await db.execute(
        text("""
            update tb_ai_reader_action_queue
               set status = 'failed'
                 , error_message = 'max attempts exceeded'
                 , active_scope_key = null
                 , locked_by = null
                 , locked_at = null
             where ai_reader_action_id in :action_ids
               and status = 'running'
        """).bindparams(bindparam("action_ids", expanding=True)),
        {"action_ids": action_ids},
    )
    _ensure_rows_changed(
        result,
        "cleanup_stale_max_attempt_actions",
        expected_count=len(action_ids),
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def _acquire_action_target_lock(
    action: ReaderQueuedAction,
    db: AsyncSession,
) -> str:
    lock_key = _build_action_target_lock_key(action)
    result = await db.execute(
        text("select get_lock(:lock_key, :timeout_seconds)"),
        {"lock_key": lock_key, "timeout_seconds": 5},
    )
    lock_result = result.scalar_one()
    if lock_result == 0:
        raise ReaderActionLockBusyError("action target lock busy")
    if lock_result != 1:
        raise InvalidReaderActionError("failed to acquire action target lock")
    return lock_key


async def _release_action_target_lock(lock_key: str, db: AsyncSession) -> None:
    result = await db.execute(
        text("select release_lock(:lock_key)"),
        {"lock_key": lock_key},
    )
    release_result = result.scalar_one()
    if release_result != 1:
        logger.warning(
            "ai reader action target lock release returned unexpected result",
            extra={"lock_key": lock_key, "release_result": release_result},
        )


async def _is_action_agent_active(
    action: ReaderQueuedAction,
    db: AsyncSession,
) -> bool:
    result = await db.execute(
        text("""
            select status
              from tb_ai_reader_agent
             where ai_reader_agent_id = :ai_reader_agent_id
               and user_id = :user_id
             limit 1
             for update
        """),
        {
            "ai_reader_agent_id": action.ai_reader_agent_id,
            "user_id": action.user_id,
        },
    )
    row = result.mappings().one_or_none()
    return bool(row and row.get("status") == "active")


async def _should_retry_after_pending_read_pool_action(
    action: ReaderQueuedAction,
    result: ReaderActionApplyResult,
    db: AsyncSession,
) -> bool:
    if result.applied or result.reason not in READ_POOL_GUARD_RETRY_REASONS:
        return False
    return await _has_pending_read_pool_action(action, db, reason=result.reason)


async def _has_pending_read_pool_action(
    action: ReaderQueuedAction,
    db: AsyncSession,
    *,
    reason: str,
) -> bool:
    if action.llm_decision_id is None:
        return False
    if reason == "episode_not_read" and action.episode_id is None:
        return False

    episode_filter = "and episode_id = :episode_id" if reason == "episode_not_read" else ""
    result = await db.execute(
        text(f"""
            select ai_reader_action_id
              from tb_ai_reader_action_queue
             where ai_reader_action_id <> :ai_reader_action_id
               and ai_reader_agent_id = :ai_reader_agent_id
               and user_id = :user_id
               and product_id = :product_id
               and llm_decision_id = :llm_decision_id
               and action_type = 'read'
               and status in ('queued', 'running')
               {episode_filter}
             limit 1
        """),
        {
            "ai_reader_action_id": action.ai_reader_action_id,
            "ai_reader_agent_id": action.ai_reader_agent_id,
            "user_id": action.user_id,
            "product_id": action.product_id,
            "episode_id": action.episode_id,
            "llm_decision_id": action.llm_decision_id,
        },
    )
    return bool(result.mappings().all())


async def _commit_active_transaction(db: AsyncSession) -> None:
    in_transaction = getattr(db, "in_transaction", None)
    if not callable(in_transaction):
        return
    active = in_transaction()
    if inspect.isawaitable(active):
        active = await active
    if active is True:
        await db.commit()


async def _rollback_active_transaction(db: AsyncSession) -> None:
    in_transaction = getattr(db, "in_transaction", None)
    if not callable(in_transaction):
        return
    active = in_transaction()
    if inspect.isawaitable(active):
        active = await active
    if active is True:
        await db.rollback()


def _build_action_target_lock_key(action: ReaderQueuedAction) -> str:
    raw = f"{action.ai_reader_agent_id}|{action.product_id}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:46]
    return f"ai-reader-action:{digest}"


def _lock_busy_retry_delay_seconds(action: ReaderQueuedAction) -> int:
    raw = (
        f"{action.ai_reader_action_id}|{action.ai_reader_agent_id}|"
        f"{action.product_id}|{action.episode_id or 0}"
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return 30 + (int(digest[:8], 16) % 151)


def _next_read_base_delay_seconds(action: ReaderQueuedAction) -> int:
    raw = (
        f"next-read|{action.ai_reader_action_id}|{action.ai_reader_agent_id}|"
        f"{action.product_id}|{action.episode_id or 0}"
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return 45 + (int(digest[:8], 16) % 196)


def _normalize_active_scope_keys(active_scope_keys: list[str] | None) -> list[str]:
    if active_scope_keys is None:
        return []
    normalized = []
    seen = set()
    for key in active_scope_keys:
        if not key:
            continue
        trimmed = key[:64]
        if trimmed in seen:
            continue
        seen.add(trimmed)
        normalized.append(trimmed)
    return normalized


async def mark_action_succeeded(
    db: AsyncSession,
    *,
    action_id: int,
    worker_id: str,
) -> None:
    if not worker_id.strip():
        raise InvalidReaderActionError("worker_id is required")
    result = await db.execute(
        text("""
            update tb_ai_reader_action_queue
               set status = 'applied'
                 , applied_at = current_timestamp
                 , error_message = null
                 , active_scope_key = null
                 , locked_by = null
                 , locked_at = null
             where ai_reader_action_id = :action_id
               and status = 'running'
               and locked_by = :worker_id
        """),
        {"action_id": action_id, "worker_id": worker_id[:100]},
    )
    _ensure_rows_changed(result, "mark_action_succeeded")


async def mark_action_failed(
    db: AsyncSession,
    *,
    action_id: int,
    worker_id: str,
    error_message: str,
) -> None:
    if not worker_id.strip():
        raise InvalidReaderActionError("worker_id is required")
    result = await db.execute(
        text("""
            update tb_ai_reader_action_queue
               set status = 'failed'
                 , error_message = :error_message
                 , active_scope_key = null
                 , locked_by = null
                 , locked_at = null
             where ai_reader_action_id = :action_id
               and status = 'running'
               and locked_by = :worker_id
        """),
        {
            "action_id": action_id,
            "worker_id": worker_id[:100],
            "error_message": error_message[:1000],
        },
    )
    _ensure_rows_changed(result, "mark_action_failed")


async def mark_action_retry_later(
    db: AsyncSession,
    *,
    action_id: int,
    worker_id: str,
    retry_delay_seconds: int,
    error_message: str,
) -> None:
    if not worker_id.strip():
        raise InvalidReaderActionError("worker_id is required")
    if retry_delay_seconds < 1 or retry_delay_seconds > 3600:
        raise InvalidReaderActionError("retry_delay_seconds must be between 1 and 3600")
    result = await db.execute(
        text("""
            update tb_ai_reader_action_queue
               set status = 'queued'
                 , locked_by = null
                 , locked_at = null
                 , available_at = timestampadd(second, :retry_delay_seconds, current_timestamp)
                 , attempt_count = greatest(attempt_count - 1, 0)
                 , error_message = :error_message
             where ai_reader_action_id = :action_id
               and status = 'running'
               and locked_by = :worker_id
        """),
        {
            "action_id": action_id,
            "worker_id": worker_id[:100],
            "retry_delay_seconds": retry_delay_seconds,
            "error_message": error_message[:1000],
        },
    )
    _ensure_rows_changed(result, "mark_action_retry_later")


async def apply_reader_action(
    action: ReaderQueuedAction,
    db: AsyncSession,
) -> ReaderActionApplyResult:
    if action.action_type == "bookmark":
        return await _apply_bookmark_action(action, db)
    if action.action_type == "evaluate":
        return await _apply_evaluate_action(action, db)
    if action.action_type == "recommend":
        return await _apply_recommend_action(action, db)
    if action.action_type == "drop":
        return await _apply_drop_action(action, db)
    if action.action_type == "next_episode":
        return await _apply_next_episode_action(action, db)
    if action.action_type == "read":
        return await _apply_read_action(action, db)
    raise UnsupportedReaderActionError(f"unsupported action_type: {action.action_type}")


async def _apply_bookmark_action(
    action: ReaderQueuedAction,
    db: AsyncSession,
) -> ReaderActionApplyResult:
    target_use_yn = _require_yn(action.target_value, "bookmark.target_value")
    if target_use_yn == "Y" and not await _has_ai_reader_read_product(action, db):
        return _result(action, applied=False, reason="product_not_read")

    result = await db.execute(
        text("""
            select id
                 , use_yn
              from tb_user_bookmark
             where user_id = :user_id
               and product_id = :product_id
             order by id
        """),
        {"user_id": action.user_id, "product_id": action.product_id},
    )
    rows = result.mappings().all()

    changed = False
    cleaned_duplicates = False
    if rows:
        row = rows[0]
        duplicate_ids = _duplicate_row_ids(rows)
        if duplicate_ids:
            await _delete_user_bookmark_ids(duplicate_ids, db)
            cleaned_duplicates = True
        if row.get("use_yn") != target_use_yn:
            await db.execute(
                text("""
                    update tb_user_bookmark
                       set use_yn = :target_use_yn
                         , updated_id = :user_id
                     where id = :id
                """),
                {
                    "id": row.get("id"),
                    "target_use_yn": target_use_yn,
                    "user_id": action.user_id,
                },
            )
            changed = True
    elif target_use_yn == "Y":
        await db.execute(
            text("""
                insert into tb_user_bookmark
                    (user_id, product_id, use_yn, created_id, updated_id)
                values
                    (:user_id, :product_id, 'Y', :created_id, :updated_id)
            """),
            {
                "user_id": action.user_id,
                "product_id": action.product_id,
                "created_id": settings.DB_DML_DEFAULT_ID,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            },
        )
        changed = True

    if not changed:
        if cleaned_duplicates:
            await _refresh_product_bookmark_count(action.product_id, db)
        return _result(action, applied=False, reason="already_in_target_state")

    await _refresh_product_bookmark_count(action.product_id, db)
    await _mark_ai_product_state_flag(
        action,
        db,
        flag_column="bookmarked_yn",
        flag_value=target_use_yn,
    )
    await _increment_ai_public_metric(
        product_id=action.product_id,
        episode_id=0,
        metric_column=(
            "ai_bookmark_count" if target_use_yn == "Y" else "ai_unbookmark_count"
        ),
        db=db,
    )
    return _result(action, applied=True, reason="applied")


async def _apply_read_action(
    action: ReaderQueuedAction,
    db: AsyncSession,
) -> ReaderActionApplyResult:
    if action.episode_id is None:
        raise InvalidReaderActionError("read action requires episode_id")

    product_id = await _get_active_episode_product_id(action.episode_id, db)
    if product_id != action.product_id:
        raise InvalidReaderActionError("episode does not belong to product")
    if await _is_ai_product_dropped(action, db):
        return _result(action, applied=False, reason="product_dropped")

    result = await db.execute(
        text("""
            select id
              from tb_user_product_usage
             where user_id = :user_id
               and product_id = :product_id
               and episode_id = :episode_id
             limit 1
        """),
        {
            "user_id": action.user_id,
            "product_id": action.product_id,
            "episode_id": action.episode_id,
        },
    )
    rows = result.mappings().all()
    if rows:
        await db.execute(
            text("""
                update tb_user_product_usage
                   set updated_id = :user_id
                 where id = :id
            """),
            {"id": rows[0].get("id"), "user_id": action.user_id},
        )
    else:
        await db.execute(
            text("""
                insert into tb_user_product_usage
                    (user_id, product_id, episode_id, created_id, updated_id)
                values
                    (:user_id, :product_id, :episode_id, :created_id, :updated_id)
            """),
            {
                "user_id": action.user_id,
                "product_id": action.product_id,
                "episode_id": action.episode_id,
                "created_id": settings.DB_DML_DEFAULT_ID,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            },
        )

    await db.execute(
        text("""
            update tb_product_episode
               set count_hit = count_hit + 1
             where episode_id = :episode_id
        """),
        {"episode_id": action.episode_id},
    )
    await db.execute(
        text("""
            update tb_product
               set count_hit = count_hit + 1
             where product_id = :product_id
        """),
        {"product_id": action.product_id},
    )
    await _save_product_hit_log(product_id=action.product_id, db=db)
    await _mark_ai_product_state_read(action, db)
    await _increment_ai_public_metric(
        product_id=action.product_id,
        episode_id=action.episode_id,
        metric_column="ai_view_count",
        db=db,
    )
    await _insert_ai_reader_signal_event(
        action,
        db,
        event_type="episode_view",
    )
    return _result(action, applied=True, reason="applied")


async def _apply_evaluate_action(
    action: ReaderQueuedAction,
    db: AsyncSession,
) -> ReaderActionApplyResult:
    if action.episode_id is None:
        raise InvalidReaderActionError("evaluate action requires episode_id")
    if action.target_value not in EVALUATION_CODES:
        raise InvalidReaderActionError("evaluate.target_value is invalid")

    result = await db.execute(
        text("""
            select e.product_id
              from tb_product_episode e
              join tb_product p
                on p.product_id = e.product_id
             where e.episode_id = :episode_id
               and e.use_yn = 'Y'
               and e.open_yn = 'Y'
               and (e.publish_reserve_date is null or e.publish_reserve_date <= current_timestamp)
               and p.open_yn = 'Y'
               and coalesce(p.blind_yn, 'N') = 'N'
               and (
                    coalesce(e.price_type, 'free') = 'free'
                    or (
                        p.price_type = 'paid'
                        and p.paid_episode_no is not null
                        and p.paid_episode_no > 0
                        and e.episode_no < p.paid_episode_no
                    )
               )
             limit 1
        """),
        {"episode_id": action.episode_id},
    )
    episode_rows = result.mappings().all()
    if not episode_rows:
        raise InvalidReaderActionError("episode does not exist or is not active")

    product_id = episode_rows[0].get("product_id")
    if product_id != action.product_id:
        raise InvalidReaderActionError("episode does not belong to product")

    result = await db.execute(
        text("""
            select id
              from tb_product_evaluation
             where user_id = :user_id
               and product_id = :product_id
               and episode_id = :episode_id
             order by id
        """),
        {
            "user_id": action.user_id,
            "product_id": product_id,
            "episode_id": action.episode_id,
        },
    )
    existing_rows = result.mappings().all()
    if existing_rows:
        duplicate_ids = _duplicate_row_ids(existing_rows)
        if duplicate_ids:
            await _delete_product_evaluation_ids(duplicate_ids, db)
            await _refresh_episode_evaluation_count(action.episode_id, db)
        return _result(action, applied=False, reason="already_applied")

    if not await _has_ai_reader_read_episode(action, db):
        return _result(action, applied=False, reason="episode_not_read")

    read_episode_count = await _count_ai_reader_read_product_episodes(action, db)
    if read_episode_count < MIN_EVALUATION_READ_EPISODE_COUNT:
        return _result(action, applied=False, reason="insufficient_read_pool")

    await db.execute(
        text("""
            insert into tb_product_evaluation
                (product_id, episode_id, user_id, eval_code, created_id, updated_id)
            values
                (:product_id, :episode_id, :user_id, :eval_code, :created_id, :updated_id)
        """),
        {
            "product_id": product_id,
            "episode_id": action.episode_id,
            "user_id": action.user_id,
            "eval_code": action.target_value,
            "created_id": settings.DB_DML_DEFAULT_ID,
            "updated_id": settings.DB_DML_DEFAULT_ID,
        },
    )
    await db.execute(
        text("""
            update tb_product_episode
               set count_evaluation = (
                    select count(*)
                      from tb_product_evaluation
                     where episode_id = :episode_id
               )
             where episode_id = :episode_id
        """),
        {"episode_id": action.episode_id},
    )
    await _mark_ai_product_state_flag(
        action,
        db,
        flag_column="evaluated_yn",
        flag_value="Y",
    )
    await _increment_ai_public_metric(
        product_id=product_id,
        episode_id=action.episode_id,
        metric_column="ai_evaluation_count",
        db=db,
    )
    return _result(action, applied=True, reason="applied")


async def _apply_drop_action(
    action: ReaderQueuedAction,
    db: AsyncSession,
) -> ReaderActionApplyResult:
    target_drop_yn = _require_yn(action.target_value, "drop.target_value")
    if target_drop_yn != "Y":
        raise InvalidReaderActionError("drop.target_value must be Y")
    await db.execute(
        text("""
            insert into tb_ai_reader_product_state
                (ai_reader_agent_id, product_id, current_episode_id, state, last_decision_id)
            values
                (:ai_reader_agent_id, :product_id, :episode_id, 'dropped', :llm_decision_id)
            on duplicate key update
                current_episode_id = values(current_episode_id),
                state = 'dropped',
                last_decision_id = coalesce(values(last_decision_id), last_decision_id),
                updated_date = current_timestamp
        """),
        {
            "ai_reader_agent_id": action.ai_reader_agent_id,
            "product_id": action.product_id,
            "episode_id": action.episode_id,
            "llm_decision_id": action.llm_decision_id,
        },
    )
    return _result(action, applied=True, reason="applied")


async def _apply_next_episode_action(
    action: ReaderQueuedAction,
    db: AsyncSession,
) -> ReaderActionApplyResult:
    requested_next_episode_count = _require_count(
        action.target_value,
        "next_episode.target_value",
    )
    next_episode_count = _cap_followup_read_count(requested_next_episode_count)
    if action.episode_id is None:
        raise InvalidReaderActionError("next_episode action requires episode_id")
    product_id = await _get_active_episode_product_id(action.episode_id, db)
    if product_id != action.product_id:
        raise InvalidReaderActionError("episode does not belong to product")
    if await _is_ai_product_dropped(action, db):
        return _result(action, applied=False, reason="product_dropped")

    active_scope_keys = await _select_next_read_active_scope_keys(
        action,
        next_episode_count=next_episode_count,
        db=db,
    )
    if not active_scope_keys:
        return _result(action, applied=False, reason="no_next_episode")

    await cleanup_stale_max_attempt_actions(
        db,
        active_scope_keys=active_scope_keys,
        limit=max(len(active_scope_keys), 1),
    )
    await db.execute(
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
                    available_at
                )
            select sha2(concat_ws(
                       '|',
                       'ai-reader-next-read',
                       :source_action_id,
                       z.episode_id
                   ), 256) as idempotency_key
                 , sha2(concat_ws(
                       '|',
                       'ai-reader-active',
                       :ai_reader_agent_id,
                       :user_id,
                       z.product_id,
                       z.episode_id,
                       'read',
                       ''
                   ), 256) as active_scope_key
                 , :ai_reader_agent_id
                 , :user_id
                 , z.product_id
                 , z.episode_id
                 , 'read', null
                 , :llm_decision_id
                 , timestampadd(
                       second,
                       :next_read_base_delay_seconds
                       + (
                           :next_read_step_delay_seconds
                           * greatest(z.episode_no - current_episode.episode_no - 1, 0)
                       ),
                       current_timestamp
                   )
             from tb_product_episode z
             join tb_product p
               on p.product_id = z.product_id
             join tb_product_episode current_episode
               on current_episode.episode_id = :episode_id
              and current_episode.product_id = :product_id
             where z.product_id = :product_id
               and z.use_yn = 'Y'
               and z.open_yn = 'Y'
               and (z.publish_reserve_date is null or z.publish_reserve_date <= current_timestamp)
               and (
                    coalesce(z.price_type, 'free') = 'free'
                    or (
                        p.price_type = 'paid'
                        and p.paid_episode_no is not null
                        and p.paid_episode_no > 0
                        and z.episode_no < p.paid_episode_no
                    )
               )
               and z.episode_no > current_episode.episode_no
             order by z.episode_no
             limit :next_episode_count
            on duplicate key update
                available_at = available_at
        """),
        {
            "source_action_id": action.ai_reader_action_id,
            "ai_reader_agent_id": action.ai_reader_agent_id,
            "user_id": action.user_id,
            "product_id": action.product_id,
            "episode_id": action.episode_id,
            "next_episode_count": next_episode_count,
            "llm_decision_id": action.llm_decision_id,
            "next_read_base_delay_seconds": _next_read_base_delay_seconds(action),
            "next_read_step_delay_seconds": 45,
        },
    )
    await db.execute(
        text("""
            insert into tb_ai_reader_product_state
                (ai_reader_agent_id, product_id, current_episode_id, state, last_decision_id)
            values
                (:ai_reader_agent_id, :product_id, :episode_id, 'reading', :llm_decision_id)
            on duplicate key update
                current_episode_id = values(current_episode_id),
                state = 'reading',
                last_decision_id = coalesce(values(last_decision_id), last_decision_id),
                updated_date = current_timestamp
        """),
        {
            "ai_reader_agent_id": action.ai_reader_agent_id,
            "product_id": action.product_id,
            "episode_id": action.episode_id,
            "llm_decision_id": action.llm_decision_id,
        },
    )
    return _result(action, applied=True, reason="applied")


async def _select_next_read_active_scope_keys(
    action: ReaderQueuedAction,
    *,
    next_episode_count: int,
    db: AsyncSession,
) -> list[str]:
    result = await db.execute(
        text("""
            select sha2(concat_ws(
                       '|',
                       'ai-reader-active',
                       :ai_reader_agent_id,
                       :user_id,
                       z.product_id,
                       z.episode_id,
                       'read',
                       ''
                   ), 256) as active_scope_key
              from tb_product_episode z
              join tb_product p
                on p.product_id = z.product_id
              join tb_product_episode current_episode
                on current_episode.episode_id = :episode_id
               and current_episode.product_id = :product_id
             where z.product_id = :product_id
               and z.use_yn = 'Y'
               and z.open_yn = 'Y'
               and (z.publish_reserve_date is null or z.publish_reserve_date <= current_timestamp)
               and (
                    coalesce(z.price_type, 'free') = 'free'
                    or (
                        p.price_type = 'paid'
                        and p.paid_episode_no is not null
                        and p.paid_episode_no > 0
                        and z.episode_no < p.paid_episode_no
                    )
               )
               and z.episode_no > current_episode.episode_no
             order by z.episode_no
             limit :next_episode_count
        """),
        {
            "ai_reader_agent_id": action.ai_reader_agent_id,
            "user_id": action.user_id,
            "product_id": action.product_id,
            "episode_id": action.episode_id,
            "next_episode_count": next_episode_count,
        },
    )
    return [
        row.get("active_scope_key")
        for row in result.mappings().all()
        if row.get("active_scope_key")
    ]


async def _apply_recommend_action(
    action: ReaderQueuedAction,
    db: AsyncSession,
) -> ReaderActionApplyResult:
    target_like_yn = _require_yn(action.target_value, "recommend.target_value")
    if action.episode_id is None:
        raise InvalidReaderActionError("recommend action requires episode_id")

    product_id = await _get_active_episode_product_id(action.episode_id, db)
    if product_id != action.product_id:
        raise InvalidReaderActionError("episode does not belong to product")

    result = await db.execute(
        text("""
            select id
              from tb_product_episode_like
             where user_id = :user_id
               and product_id = :product_id
               and episode_id = :episode_id
             order by id
        """),
        {
            "user_id": action.user_id,
            "product_id": action.product_id,
            "episode_id": action.episode_id,
        },
    )
    rows = result.mappings().all()

    changed = False
    like_ids = _row_ids(rows)
    if rows and target_like_yn == "N":
        await _delete_episode_like_ids(like_ids, db)
        changed = True
    elif not rows and target_like_yn == "Y":
        if not await _has_ai_reader_read_episode(action, db):
            return _result(action, applied=False, reason="episode_not_read")
        await db.execute(
            text("""
                insert into tb_product_episode_like
                    (product_id, episode_id, user_id, created_id)
                values
                    (:product_id, :episode_id, :user_id, :created_id)
            """),
            {
                "product_id": action.product_id,
                "episode_id": action.episode_id,
                "user_id": action.user_id,
                "created_id": settings.DB_DML_DEFAULT_ID,
            },
        )
        changed = True
    elif len(like_ids) > 1:
        await _delete_episode_like_ids(like_ids[1:], db)
        await _refresh_episode_like_recommend_count(
            action.product_id,
            action.episode_id,
            db,
        )

    if not changed:
        return _result(action, applied=False, reason="already_in_target_state")

    await _refresh_episode_like_recommend_count(action.product_id, action.episode_id, db)
    await _mark_ai_product_state_flag(
        action,
        db,
        flag_column="recommended_yn",
        flag_value=target_like_yn,
    )
    await _increment_ai_public_metric(
        product_id=action.product_id,
        episode_id=action.episode_id,
        metric_column=(
            "ai_recommend_count" if target_like_yn == "Y" else "ai_unrecommend_count"
        ),
        db=db,
    )
    return _result(action, applied=True, reason="applied")


async def _refresh_product_bookmark_count(product_id: int, db: AsyncSession) -> None:
    await db.execute(
        text("""
            update tb_product a
             inner join (
                select z.product_id
                     , sum(case when z.use_yn = 'Y' then 1 else 0 end) as count_bookmark
                     , sum(case when z.use_yn = 'N' then 1 else 0 end) as count_unbookmark
                  from tb_user_bookmark z
                 where z.product_id = :product_id
                 group by z.product_id
              ) as t on a.product_id = t.product_id
               set a.count_bookmark = t.count_bookmark
                 , a.count_unbookmark = t.count_unbookmark
             where a.product_id = :product_id
        """),
        {"product_id": product_id},
    )


async def _refresh_episode_evaluation_count(episode_id: int, db: AsyncSession) -> None:
    await db.execute(
        text("""
            update tb_product_episode
               set count_evaluation = (
                    select count(*)
                      from tb_product_evaluation
                     where episode_id = :episode_id
               )
             where episode_id = :episode_id
        """),
        {"episode_id": episode_id},
    )


async def _delete_episode_like_ids(like_ids: list[int], db: AsyncSession) -> None:
    if not like_ids:
        return
    await db.execute(
        text("""
            delete from tb_product_episode_like
             where id in :like_ids
        """).bindparams(bindparam("like_ids", expanding=True)),
        {"like_ids": like_ids},
    )


async def _delete_product_evaluation_ids(
    evaluation_ids: list[int],
    db: AsyncSession,
) -> None:
    if not evaluation_ids:
        return
    await db.execute(
        text("""
            delete from tb_product_evaluation
             where id in :evaluation_ids
        """).bindparams(bindparam("evaluation_ids", expanding=True)),
        {"evaluation_ids": evaluation_ids},
    )


async def _delete_user_bookmark_ids(bookmark_ids: list[int], db: AsyncSession) -> None:
    if not bookmark_ids:
        return
    await db.execute(
        text("""
            delete from tb_user_bookmark
             where id in :bookmark_ids
        """).bindparams(bindparam("bookmark_ids", expanding=True)),
        {"bookmark_ids": bookmark_ids},
    )


def _row_ids(rows: list[dict]) -> list[int]:
    return [int(row.get("id")) for row in rows if row.get("id") is not None]


def _duplicate_row_ids(rows: list[dict]) -> list[int]:
    return _row_ids(rows)[1:]


async def _mark_ai_product_state_read(
    action: ReaderQueuedAction,
    db: AsyncSession,
) -> None:
    await db.execute(
        text("""
            insert into tb_ai_reader_product_state
                (
                    ai_reader_agent_id,
                    product_id,
                    current_episode_id,
                    state,
                    read_episode_count,
                    last_decision_id
                )
            values
                (:ai_reader_agent_id, :product_id, :episode_id, 'reading', 1, :llm_decision_id)
            on duplicate key update
                current_episode_id = values(current_episode_id),
                state = 'reading',
                read_episode_count = read_episode_count + 1,
                last_decision_id = coalesce(values(last_decision_id), last_decision_id),
                updated_date = current_timestamp
        """),
        {
            "ai_reader_agent_id": action.ai_reader_agent_id,
            "product_id": action.product_id,
            "episode_id": action.episode_id,
            "llm_decision_id": action.llm_decision_id,
        },
    )


async def _is_ai_product_dropped(
    action: ReaderQueuedAction,
    db: AsyncSession,
) -> bool:
    result = await db.execute(
        text("""
            select state
              from tb_ai_reader_product_state
             where ai_reader_agent_id = :ai_reader_agent_id
               and product_id = :product_id
             limit 1
        """),
        {
            "ai_reader_agent_id": action.ai_reader_agent_id,
            "product_id": action.product_id,
        },
    )
    row = result.mappings().one_or_none()
    return bool(row and row.get("state") == "dropped")


async def _has_ai_reader_read_product(
    action: ReaderQueuedAction,
    db: AsyncSession,
) -> bool:
    result = await db.execute(
        text("""
            select count(*) as read_count
              from tb_user_product_usage
             where user_id = :user_id
               and product_id = :product_id
        """),
        {"user_id": action.user_id, "product_id": action.product_id},
    )
    return _read_count_from_result(result) > 0


async def _has_ai_reader_read_episode(
    action: ReaderQueuedAction,
    db: AsyncSession,
) -> bool:
    if action.episode_id is None:
        return False
    result = await db.execute(
        text("""
            select count(*) as read_count
              from tb_user_product_usage
             where user_id = :user_id
               and product_id = :product_id
               and episode_id = :episode_id
        """),
        {
            "user_id": action.user_id,
            "product_id": action.product_id,
            "episode_id": action.episode_id,
        },
    )
    return _read_count_from_result(result) > 0


async def _count_ai_reader_read_product_episodes(
    action: ReaderQueuedAction,
    db: AsyncSession,
) -> int:
    result = await db.execute(
        text("""
            select count(distinct episode_id) as read_count
              from tb_user_product_usage
             where user_id = :user_id
               and product_id = :product_id
               and episode_id is not null
        """),
        {"user_id": action.user_id, "product_id": action.product_id},
    )
    return _read_count_from_result(result)


def _read_count_from_result(result) -> int:
    rows = result.mappings().all()
    if not rows:
        return 0
    return int(rows[0].get("read_count") or 0)


async def _mark_ai_product_state_flag(
    action: ReaderQueuedAction,
    db: AsyncSession,
    *,
    flag_column: str,
    flag_value: str,
) -> None:
    if flag_column not in {"bookmarked_yn", "recommended_yn", "evaluated_yn"}:
        raise InvalidReaderActionError("state flag is invalid")

    await db.execute(
        text(f"""
            insert into tb_ai_reader_product_state
                (
                    ai_reader_agent_id,
                    product_id,
                    current_episode_id,
                    {flag_column},
                    last_decision_id
                )
            values
                (:ai_reader_agent_id, :product_id, :episode_id, :flag_value, :llm_decision_id)
            on duplicate key update
                current_episode_id = values(current_episode_id),
                {flag_column} = values({flag_column}),
                last_decision_id = coalesce(values(last_decision_id), last_decision_id),
                updated_date = current_timestamp
        """),
        {
            "ai_reader_agent_id": action.ai_reader_agent_id,
            "product_id": action.product_id,
            "episode_id": action.episode_id,
            "flag_value": flag_value,
            "llm_decision_id": action.llm_decision_id,
        },
    )


async def _refresh_episode_like_recommend_count(
    product_id: int,
    episode_id: int,
    db: AsyncSession,
) -> None:
    await db.execute(
        text("""
            update tb_product_episode
               set count_recommend = (
                    select count(*)
                      from tb_product_episode_like
                     where episode_id = :episode_id
               )
             where episode_id = :episode_id
        """),
        {"episode_id": episode_id},
    )
    await db.execute(
        text("""
            update tb_product
               set count_recommend = (
                    select count(*)
                      from tb_product_episode_like
                     where product_id = :product_id
               )
             where product_id = :product_id
        """),
        {"product_id": product_id},
    )


async def _save_product_hit_log(product_id: int, db: AsyncSession) -> None:
    await db.execute(
        text("""
            insert into tb_product_hit_log (product_id, hit_date, hit_count)
            values (:product_id, current_date(), 1)
            on duplicate key update hit_count = hit_count + 1
        """),
        {"product_id": product_id},
    )


async def _insert_ai_reader_signal_event(
    action: ReaderQueuedAction,
    db: AsyncSession,
    *,
    event_type: str,
) -> None:
    if action.episode_id is None:
        raise InvalidReaderActionError("signal event requires episode_id")

    factor_entries = await _resolve_ai_reader_signal_factor_entries(
        action.product_id,
        db,
    )
    payload = json.dumps(
        {
            "source": "ai_reader_agent",
            "ai_reader_agent_id": action.ai_reader_agent_id,
            "ai_reader_action_id": action.ai_reader_action_id,
        },
        ensure_ascii=False,
    )
    result = await db.execute(
        text("""
            insert into tb_user_ai_signal_event (
                user_id,
                product_id,
                episode_id,
                event_type,
                session_id,
                active_seconds,
                scroll_depth,
                progress_ratio,
                next_available_yn,
                latest_episode_reached_yn,
                event_payload
            ) values (
                :user_id,
                :product_id,
                :episode_id,
                :event_type,
                :session_id,
                :active_seconds,
                :scroll_depth,
                :progress_ratio,
                'N',
                'N',
                :event_payload
            )
        """),
        {
            "user_id": action.user_id,
            "product_id": action.product_id,
            "episode_id": action.episode_id,
            "event_type": event_type,
            "session_id": f"ai-reader-action-{action.ai_reader_action_id}",
            "active_seconds": 180,
            "scroll_depth": 0.85,
            "progress_ratio": 0.85,
            "event_payload": payload,
        },
    )
    event_id = getattr(result, "lastrowid", None)
    if event_id and factor_entries:
        await _insert_ai_signal_event_factors(
            event_id=int(event_id),
            user_id=action.user_id,
            product_id=action.product_id,
            episode_id=action.episode_id,
            event_type=event_type,
            factor_entries=factor_entries,
            db=db,
        )


async def _resolve_ai_reader_signal_factor_entries(
    product_id: int,
    db: AsyncSession,
) -> list[dict[str, float | str]]:
    result = await db.execute(
        text("""
            select protagonist_type
                 , protagonist_goal_primary
                 , protagonist_material_tags
                 , worldview_tags
                 , protagonist_type_tags
                 , protagonist_job_tags
                 , axis_style_tags
                 , axis_romance_tags
              from tb_product_ai_metadata
             where product_id = :product_id
               and analysis_status = 'success'
               and coalesce(exclude_from_recommend_yn, 'N') = 'N'
             limit 1
        """),
        {"product_id": product_id},
    )
    row = result.mappings().one_or_none()
    if not row:
        return []

    labels_by_type = {
        "style": _json_label_list(row.get("axis_style_tags")),
        "worldview": _json_label_list(row.get("worldview_tags")),
        "romance": _json_label_list(row.get("axis_romance_tags")),
        "material": _json_label_list(row.get("protagonist_material_tags")),
        "job": _json_label_list(row.get("protagonist_job_tags")),
        "protagonist": _json_label_list(row.get("protagonist_type_tags"))
        + _nonempty_labels([row.get("protagonist_type")]),
        "goal": _nonempty_labels([row.get("protagonist_goal_primary")]),
    }
    score_plan = [
        ("style", 1.4),
        ("worldview", 1.2),
        ("romance", 1.1),
        ("material", 1.0),
        ("job", 0.95),
        ("protagonist", 0.9),
        ("goal", 0.85),
    ]

    entries: list[dict[str, float | str]] = []
    seen: set[tuple[str, str]] = set()
    for factor_type, signal_score in score_plan:
        for factor_key in labels_by_type.get(factor_type, []):
            dedupe_key = (factor_type, factor_key)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            entries.append(
                {
                    "factor_type": factor_type,
                    "factor_key": factor_key,
                    "signal_score": signal_score,
                }
            )
    return entries


async def _insert_ai_signal_event_factors(
    *,
    event_id: int,
    user_id: int,
    product_id: int,
    episode_id: int,
    event_type: str,
    factor_entries: list[dict[str, float | str]],
    db: AsyncSession,
) -> None:
    await db.execute(
        text("""
            insert into tb_user_ai_signal_event_factor (
                event_id,
                user_id,
                product_id,
                episode_id,
                event_type,
                factor_type,
                factor_key,
                signal_score
            ) values (
                :event_id,
                :user_id,
                :product_id,
                :episode_id,
                :event_type,
                :factor_type,
                :factor_key,
                :signal_score
            )
            on duplicate key update
                signal_score = values(signal_score)
        """),
        [
            {
                "event_id": event_id,
                "user_id": user_id,
                "product_id": product_id,
                "episode_id": episode_id,
                "event_type": event_type,
                "factor_type": entry["factor_type"],
                "factor_key": entry["factor_key"],
                "signal_score": entry["signal_score"],
            }
            for entry in factor_entries
        ],
    )


def _json_label_list(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return _nonempty_labels(parsed)
        return []
    if isinstance(value, list):
        return _nonempty_labels(value)
    return []


def _nonempty_labels(values: list[object]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = str(value or "").strip()[:120]
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels


async def _increment_ai_public_metric(
    *,
    product_id: int,
    episode_id: int,
    metric_column: str,
    db: AsyncSession,
) -> None:
    if metric_column not in {
        "ai_bookmark_count",
        "ai_unbookmark_count",
        "ai_recommend_count",
        "ai_unrecommend_count",
        "ai_evaluation_count",
        "ai_view_count",
    }:
        raise InvalidReaderActionError("metric_column is invalid")

    await db.execute(
        text(f"""
            insert into tb_ai_reader_public_metric_daily
                (stat_date, product_id, episode_id, {metric_column})
            values
                (current_date(), :product_id, :episode_id, 1)
            on duplicate key update
                {metric_column} = {metric_column} + 1
        """),
        {"product_id": product_id, "episode_id": episode_id},
    )


async def _get_active_episode_product_id(episode_id: int, db: AsyncSession) -> int:
    result = await db.execute(
        text("""
            select e.product_id
              from tb_product_episode e
              join tb_product p
                on p.product_id = e.product_id
             where e.episode_id = :episode_id
               and e.use_yn = 'Y'
               and e.open_yn = 'Y'
               and (e.publish_reserve_date is null or e.publish_reserve_date <= current_timestamp)
               and p.open_yn = 'Y'
               and coalesce(p.blind_yn, 'N') = 'N'
               and (
                    coalesce(e.price_type, 'free') = 'free'
                    or (
                        p.price_type = 'paid'
                        and p.paid_episode_no is not null
                        and p.paid_episode_no > 0
                        and e.episode_no < p.paid_episode_no
                    )
               )
             limit 1
        """),
        {"episode_id": episode_id},
    )
    rows = result.mappings().all()
    if not rows:
        raise InvalidReaderActionError("episode does not exist or is not active")
    return rows[0].get("product_id")


def _require_yn(value: str | None, field_name: str) -> str:
    if value not in YN_VALUES:
        raise InvalidReaderActionError(f"{field_name} must be Y or N")
    return value


def _require_count(value: str | None, field_name: str) -> int:
    try:
        count = int(value or "")
    except ValueError as exc:
        raise InvalidReaderActionError(f"{field_name} must be integer") from exc
    if count < 1 or count > 20:
        raise InvalidReaderActionError(f"{field_name} must be between 1 and 20")
    return count


def _cap_followup_read_count(count: int) -> int:
    return min(count, MAX_FOLLOWUP_READS_PER_DECISION)


@asynccontextmanager
async def _transaction_scope(db: AsyncSession):
    if _has_active_transaction(db):
        yield
        return

    async with db.begin():
        yield


def _has_active_transaction(db: AsyncSession) -> bool:
    in_transaction = getattr(db, "in_transaction", None)
    if not callable(in_transaction):
        return False
    try:
        return bool(in_transaction())
    except TypeError:
        return False


def _ensure_rows_changed(result, operation: str, *, expected_count: int = 1) -> None:
    if getattr(result, "rowcount", None) != expected_count:
        raise InvalidReaderActionError(
            f"{operation} did not update expected rows: {expected_count}"
        )


def _result(
    action: ReaderQueuedAction,
    *,
    applied: bool,
    reason: str,
) -> ReaderActionApplyResult:
    return ReaderActionApplyResult(
        ai_reader_action_id=action.ai_reader_action_id,
        action_type=action.action_type,
        applied=applied,
        reason=reason,
    )
