import logging
import os
import inspect
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai import reader_agent_action_service as action_service
from app.services.ai import reader_agent_session_service as session_service


logger = logging.getLogger(__name__)
AI_READER_WORKER_ENABLED_ENV = "AI_READER_WORKER_ENABLED"
REQUIRED_READER_WORKER_TABLES = (
    "tb_ai_reader_agent",
    "tb_ai_reader_daily_schedule",
    "tb_ai_reader_product_state",
    "tb_ai_reader_llm_decision",
    "tb_ai_reader_action_queue",
    "tb_ai_reader_public_metric_daily",
)
REQUIRED_READER_WORKER_COLUMNS = {
    "tb_ai_reader_agent": (
        "ai_reader_agent_id",
        "user_id",
        "agent_key",
        "age_group",
        "gender",
        "persona_json",
        "taste_memory_json",
        "activity_pattern_json",
        "status",
        "daily_llm_budget",
    ),
    "tb_ai_reader_daily_schedule": (
        "ai_reader_schedule_id",
        "ai_reader_agent_id",
        "schedule_date",
        "active_start_at",
        "active_end_at",
        "session_budget",
        "used_session_count",
        "status",
        "locked_by",
        "locked_at",
        "error_message",
    ),
    "tb_ai_reader_product_state": (
        "ai_reader_product_state_id",
        "ai_reader_agent_id",
        "product_id",
        "current_episode_id",
        "state",
        "read_episode_count",
        "bookmarked_yn",
        "recommended_yn",
        "evaluated_yn",
        "last_decision_id",
    ),
    "tb_ai_reader_llm_decision": (
        "ai_reader_llm_decision_id",
        "ai_reader_agent_id",
        "user_id",
        "session_id",
        "product_id",
        "episode_id",
        "prompt_version",
        "model_name",
        "request_hash",
        "decision_status",
        "input_snapshot_json",
        "decision_json",
        "created_date",
    ),
    "tb_ai_reader_action_queue": (
        "ai_reader_action_id",
        "idempotency_key",
        "active_scope_key",
        "ai_reader_agent_id",
        "user_id",
        "product_id",
        "episode_id",
        "action_type",
        "target_value",
        "llm_decision_id",
        "attempt_count",
        "status",
        "locked_by",
        "locked_at",
        "available_at",
        "applied_at",
        "error_message",
    ),
    "tb_ai_reader_public_metric_daily": (
        "ai_reader_public_metric_daily_id",
        "stat_date",
        "product_id",
        "episode_id",
        "ai_view_count",
        "ai_bookmark_count",
        "ai_unbookmark_count",
        "ai_recommend_count",
        "ai_unrecommend_count",
        "ai_evaluation_count",
    ),
}
REQUIRED_READER_WORKER_INDEXES = {
    "tb_ai_reader_agent": {
        "uk_ai_reader_agent_user": {"columns": ("user_id",), "unique": True},
        "uk_ai_reader_agent_key": {"columns": ("agent_key",), "unique": True},
    },
    "tb_ai_reader_daily_schedule": {
        "uk_ai_reader_daily_schedule_agent_window": {
            "columns": (
                "ai_reader_agent_id",
                "schedule_date",
                "active_start_at",
            ),
            "unique": True,
        },
        "idx_ai_reader_daily_schedule_due": {
            "columns": (
                "status",
                "active_start_at",
                "active_end_at",
            ),
            "unique": False,
        },
        "idx_ai_reader_daily_schedule_stale": {
            "columns": (
                "status",
                "locked_at",
                "active_start_at",
                "active_end_at",
                "ai_reader_schedule_id",
            ),
            "unique": False,
        },
    },
    "tb_ai_reader_product_state": {
        "uk_ai_reader_product_state_agent_product": {
            "columns": (
                "ai_reader_agent_id",
                "product_id",
            ),
            "unique": True,
        },
    },
    "tb_ai_reader_action_queue": {
        "uk_ai_reader_action_idempotency": {
            "columns": ("idempotency_key",),
            "unique": True,
        },
        "uk_ai_reader_action_active_scope": {
            "columns": ("active_scope_key",),
            "unique": True,
        },
        "idx_ai_reader_action_queue_due": {
            "columns": (
                "status",
                "available_at",
                "ai_reader_action_id",
            ),
            "unique": False,
        },
        "idx_ai_reader_action_queue_stale": {
            "columns": (
                "status",
                "locked_at",
                "attempt_count",
                "ai_reader_action_id",
            ),
            "unique": False,
        },
    },
    "tb_ai_reader_llm_decision": {
        "uk_ai_reader_llm_decision_session": {
            "columns": (
                "ai_reader_agent_id",
                "session_id",
                "prompt_version",
            ),
            "unique": True,
        },
        "idx_ai_reader_llm_decision_request": {
            "columns": ("request_hash",),
            "unique": False,
        },
    },
    "tb_ai_reader_public_metric_daily": {
        "uk_ai_reader_public_metric_daily_target": {
            "columns": (
                "stat_date",
                "product_id",
                "episode_id",
            ),
            "unique": True,
        },
    },
}
FORBIDDEN_READER_WORKER_INDEXES = {
    "tb_ai_reader_llm_decision": ("uk_ai_reader_llm_decision_request",),
}


class ReaderWorkerSchemaNotReadyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReaderWorkerCycleResult:
    claimed_session_count: int
    processed_session_count: int
    failed_session_count: int
    claimed_action_count: int
    processed_action_count: int
    failed_action_count: int


SessionClaimer = Callable[..., Awaitable[list[session_service.ReaderClaimedSession]]]
SessionProcessor = Callable[
    ...,
    Awaitable[session_service.ReaderSessionDecisionResult],
]
ActionClaimer = Callable[..., Awaitable[list[action_service.ReaderQueuedAction]]]
ActionProcessor = Callable[..., Awaitable[action_service.ReaderActionApplyResult]]
SchemaGuard = Callable[[AsyncSession], Awaitable[None]]
_reader_worker_schema_ready_checked = False


def is_reader_worker_enabled() -> bool:
    return os.getenv(AI_READER_WORKER_ENABLED_ENV, "").upper() == "Y"


async def ensure_reader_worker_schema_ready_once(db: AsyncSession) -> None:
    global _reader_worker_schema_ready_checked
    if _reader_worker_schema_ready_checked:
        return
    await assert_reader_worker_schema_ready(db)
    _reader_worker_schema_ready_checked = True


def reset_reader_worker_schema_ready_cache_for_tests() -> None:
    global _reader_worker_schema_ready_checked
    _reader_worker_schema_ready_checked = False


async def assert_reader_worker_schema_ready(db: AsyncSession) -> None:
    missing = []

    existing_tables = await _read_existing_reader_worker_tables(db)
    for table_name in REQUIRED_READER_WORKER_TABLES:
        if table_name not in existing_tables:
            missing.append(f"missing table {table_name}")

    existing_columns = await _read_existing_reader_worker_columns(db)
    for table_name, column_names in REQUIRED_READER_WORKER_COLUMNS.items():
        table_columns = existing_columns.get(table_name, set())
        for column_name in column_names:
            if column_name not in table_columns:
                missing.append(f"missing column {table_name}.{column_name}")

    existing_indexes = await _read_existing_reader_worker_indexes(db)
    for table_name, indexes in REQUIRED_READER_WORKER_INDEXES.items():
        table_indexes = existing_indexes.get(table_name, {})
        for index_name, index_contract in indexes.items():
            actual_index = table_indexes.get(index_name)
            if actual_index is None:
                missing.append(f"missing index {table_name}.{index_name}")
                continue

            column_names = index_contract["columns"]
            actual_column_names = actual_index["columns"]
            if actual_column_names != column_names:
                missing.append(
                    "invalid index "
                    f"{table_name}.{index_name} expected {','.join(column_names)} "
                    f"got {','.join(actual_column_names)}"
                )
            if index_contract["unique"] is True and actual_index["non_unique"] != 0:
                missing.append(f"non-unique required index {table_name}.{index_name}")
            if index_contract["unique"] is False and actual_index["non_unique"] != 1:
                missing.append(f"unique drift for non-unique index {table_name}.{index_name}")

    for table_name, index_names in FORBIDDEN_READER_WORKER_INDEXES.items():
        table_indexes = existing_indexes.get(table_name, {})
        for index_name in index_names:
            if index_name in table_indexes:
                missing.append(f"retired index still exists {table_name}.{index_name}")

    if missing:
        raise ReaderWorkerSchemaNotReadyError(
            "AI reader worker schema is not ready: " + "; ".join(missing)
        )


async def _read_existing_reader_worker_tables(db: AsyncSession) -> set[str]:
    result = await db.execute(
        text("""
            select table_name as table_name
              from information_schema.tables
             where table_schema = database()
               and table_name in :table_names
        """).bindparams(bindparam("table_names", expanding=True)),
        {"table_names": REQUIRED_READER_WORKER_TABLES},
    )
    return {_row_value(row, "table_name") for row in result.mappings().all()}


async def _read_existing_reader_worker_columns(
    db: AsyncSession,
) -> dict[str, set[str]]:
    result = await db.execute(
        text("""
            select table_name as table_name
                 , column_name as column_name
              from information_schema.columns
             where table_schema = database()
               and table_name in :table_names
        """).bindparams(bindparam("table_names", expanding=True)),
        {"table_names": REQUIRED_READER_WORKER_TABLES},
    )
    columns: dict[str, set[str]] = {}
    for row in result.mappings().all():
        columns.setdefault(_row_value(row, "table_name"), set()).add(
            _row_value(row, "column_name")
        )
    return columns


async def _read_existing_reader_worker_indexes(
    db: AsyncSession,
) -> dict[str, dict[str, dict]]:
    required_index_names = {
        index_name
        for indexes in REQUIRED_READER_WORKER_INDEXES.values()
        for index_name in indexes.keys()
    }
    forbidden_index_names = {
        index_name
        for index_names in FORBIDDEN_READER_WORKER_INDEXES.values()
        for index_name in index_names
    }
    index_names_to_read = tuple(sorted(required_index_names | forbidden_index_names))
    table_names_to_read = tuple(
        sorted(
            set(REQUIRED_READER_WORKER_INDEXES.keys())
            | set(FORBIDDEN_READER_WORKER_INDEXES.keys())
        )
    )
    result = await db.execute(
        text("""
            select table_name as table_name
                 , index_name as index_name
                 , max(non_unique) as non_unique
                 , group_concat(column_name order by seq_in_index separator ',') as column_names
              from information_schema.statistics
             where table_schema = database()
               and table_name in :table_names
               and index_name in :index_names
             group by table_name, index_name
        """).bindparams(
            bindparam("table_names", expanding=True),
            bindparam("index_names", expanding=True),
        ),
        {
            "table_names": table_names_to_read,
            "index_names": index_names_to_read,
        },
    )
    indexes: dict[str, dict[str, dict]] = {}
    for row in result.mappings().all():
        column_names = str(_row_value(row, "column_names") or "")
        indexes.setdefault(_row_value(row, "table_name"), {})[
            _row_value(row, "index_name")
        ] = {
            "columns": tuple(
                column_name for column_name in column_names.split(",") if column_name
            ),
            "non_unique": int(_row_value(row, "non_unique") or 0),
        }
    return indexes


def _row_value(row, key: str):
    if hasattr(row, "get"):
        return row.get(key) or row.get(key.upper())
    return row[key]


async def _commit_active_transaction(db: AsyncSession) -> None:
    in_transaction = getattr(db, "in_transaction", None)
    if not callable(in_transaction):
        return
    try:
        active = in_transaction()
    except TypeError:
        return
    if inspect.isawaitable(active):
        active = await active
    if active is not True:
        return

    commit = getattr(db, "commit", None)
    if not callable(commit):
        return
    result = commit()
    if inspect.isawaitable(result):
        await result


async def run_reader_worker_cycle(
    db: AsyncSession,
    *,
    worker_id: str,
    session_limit: int = 10,
    action_limit: int = 50,
    session_claimer: SessionClaimer = session_service.claim_due_reader_sessions,
    session_processor: SessionProcessor = session_service.process_claimed_reader_session,
    action_claimer: ActionClaimer = action_service.claim_due_actions,
    action_processor: ActionProcessor = action_service.process_claimed_action,
    schema_guard: SchemaGuard = ensure_reader_worker_schema_ready_once,
) -> ReaderWorkerCycleResult:
    if not worker_id.strip():
        raise ValueError("worker_id is required")
    if not is_reader_worker_enabled():
        logger.warning(
            "ai reader worker disabled",
            extra={"worker_id": worker_id, "env_var": AI_READER_WORKER_ENABLED_ENV},
        )
        return ReaderWorkerCycleResult(
            claimed_session_count=0,
            processed_session_count=0,
            failed_session_count=0,
            claimed_action_count=0,
            processed_action_count=0,
            failed_action_count=0,
        )

    await schema_guard(db)

    sessions = await session_claimer(db, worker_id=worker_id, limit=session_limit)
    processed_session_count = 0
    failed_session_count = 0
    for session in sessions:
        try:
            await session_processor(session, db, worker_id=worker_id)
            processed_session_count += 1
        except Exception:
            failed_session_count += 1
            logger.exception(
                "ai reader session processing failed",
                extra={
                    "worker_id": worker_id,
                    "ai_reader_schedule_id": session.ai_reader_schedule_id,
                    "ai_reader_agent_id": session.ai_reader_agent_id,
                },
            )

    actions = await action_claimer(db, worker_id=worker_id, limit=action_limit)
    await _commit_active_transaction(db)
    processed_action_count = 0
    failed_action_count = 0
    for action in actions:
        try:
            await action_processor(action, db, worker_id=worker_id)
            processed_action_count += 1
        except Exception:
            failed_action_count += 1
            logger.exception(
                "ai reader action processing failed",
                extra={
                    "worker_id": worker_id,
                    "ai_reader_action_id": action.ai_reader_action_id,
                    "ai_reader_agent_id": action.ai_reader_agent_id,
                },
            )

    return ReaderWorkerCycleResult(
        claimed_session_count=len(sessions),
        processed_session_count=processed_session_count,
        failed_session_count=failed_session_count,
        claimed_action_count=len(actions),
        processed_action_count=processed_action_count,
        failed_action_count=failed_action_count,
    )
