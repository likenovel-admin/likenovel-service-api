"""Chat-only event cash (이벤트 캐시).

Event cash is granted by operators (for example outage compensation) and can
only pay for websochat/character-chat messages. It is spent before paid cash.
Balance changes use a single conditional UPDATE so concurrent messages cannot
drive the balance negative, and every change is recorded in the ledger.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import settings

EVENT_CASH_REASON_GRANT = "grant"
EVENT_CASH_REASON_WEBSOCHAT_MESSAGE = "websochat_message"


async def get_user_event_cash_balance(user_id: int, db: AsyncSession) -> int:
    result = await db.execute(
        text(
            """
            SELECT balance
            FROM tb_user_event_cashbook
            WHERE user_id = :user_id
            """
        ),
        {"user_id": user_id},
    )
    row = result.mappings().one_or_none()
    return int((row or {}).get("balance") or 0)


async def try_spend_event_cash(
    *,
    user_id: int,
    amount: int,
    product_id: int | None,
    session_id: int | None,
    db: AsyncSession,
) -> bool:
    """Spend event cash only when the full amount is available."""
    if amount <= 0:
        return False
    result = await db.execute(
        text(
            """
            UPDATE tb_user_event_cashbook
            SET balance = balance - :amount,
                updated_id = :updated_id
            WHERE user_id = :user_id
              AND balance >= :amount
            """
        ),
        {
            "user_id": user_id,
            "amount": amount,
            "updated_id": settings.DB_DML_DEFAULT_ID,
        },
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        return False
    await db.execute(
        text(
            """
            INSERT INTO tb_user_event_cash_transaction
            (user_id, amount, reason_code, product_id, story_agent_session_id, created_id)
            VALUES (:user_id, :amount, :reason_code, :product_id, :session_id, :created_id)
            """
        ),
        {
            "user_id": user_id,
            "amount": -amount,
            "reason_code": EVENT_CASH_REASON_WEBSOCHAT_MESSAGE,
            "product_id": product_id,
            "session_id": session_id,
            "created_id": settings.DB_DML_DEFAULT_ID,
        },
    )
    return True


async def grant_event_cash(
    *,
    user_id: int,
    amount: int,
    grant_key: str,
    memo: str,
    db: AsyncSession,
) -> bool:
    """Grant event cash once per (user_id, grant_key). Returns False on repeat."""
    if amount <= 0:
        raise ValueError("event cash grant amount must be positive")
    normalized_key = grant_key.strip()
    if not normalized_key:
        raise ValueError("event cash grant_key is required")
    ledger = await db.execute(
        text(
            """
            INSERT IGNORE INTO tb_user_event_cash_transaction
            (user_id, amount, reason_code, grant_key, memo, created_id)
            VALUES (:user_id, :amount, :reason_code, :grant_key, :memo, :created_id)
            """
        ),
        {
            "user_id": user_id,
            "amount": amount,
            "reason_code": EVENT_CASH_REASON_GRANT,
            "grant_key": normalized_key,
            "memo": memo,
            "created_id": settings.DB_DML_DEFAULT_ID,
        },
    )
    if int(getattr(ledger, "rowcount", 0) or 0) != 1:
        return False
    await db.execute(
        text(
            """
            INSERT INTO tb_user_event_cashbook
            (user_id, balance, created_id, updated_id)
            VALUES (:user_id, :amount, :created_id, :created_id)
            ON DUPLICATE KEY UPDATE
                balance = balance + VALUES(balance),
                updated_id = VALUES(updated_id)
            """
        ),
        {
            "user_id": user_id,
            "amount": amount,
            "created_id": settings.DB_DML_DEFAULT_ID,
        },
    )
    return True
