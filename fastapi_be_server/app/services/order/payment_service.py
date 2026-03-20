import json
import logging
import os
import random
import string
from datetime import datetime
from typing import Any

import portone_server_sdk as portone
from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import ErrorMessages, settings
from app.exceptions import CustomResponseException
from app.schemas import payment as payment_schema
from app.services.common import comm_service
import app.services.common.statistics_service as statistics_service

logger = logging.getLogger("payment_app")

portone_client = portone.PortOneClient(secret=settings.PORTONE_SECRET_KEY)
PORTONE_WEBHOOK_SECRET = os.getenv("PORTONE_WEBHOOK_SECRET", "").strip()
PAYMENT_LOCK_TIMEOUT_SECONDS = 10


def _parse_virtual_account_custom_data(payment: Any) -> tuple[dict[str, Any], int]:
    if payment.custom_data is None:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_PAYMENT_STATUS,
        )

    try:
        custom_data = json.loads(payment.custom_data)
    except (TypeError, ValueError) as exc:
        logger.warning("invalid virtual account custom_data: %s", exc)
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_PAYMENT_STATUS,
        ) from exc

    item = custom_data.get("item")
    user_id = custom_data.get("user_id")
    if (
        not isinstance(item, dict)
        or not isinstance(item.get("name"), str)
        or not isinstance(item.get("price"), (int, float))
        or not isinstance(user_id, int)
    ):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_PAYMENT_STATUS,
        )

    return item, user_id


def _verify_virtual_account_payment(payment: Any, expected_user_id: int | None = None):
    item, user_id = _parse_virtual_account_custom_data(payment)

    if expected_user_id is not None and user_id != expected_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_PAYMENT_STATUS,
        )

    if payment.order_name != item["name"] or payment.amount.total != int(item["price"]):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_PAYMENT_STATUS,
        )

    return item, user_id


def _get_virtual_account_info(payment: Any) -> dict[str, Any] | None:
    method = getattr(payment, "method", None)
    virtual_account = getattr(method, "virtual_account", None) if method else None
    if virtual_account is None and hasattr(method, "account_number"):
        virtual_account = method

    if virtual_account is None or not getattr(virtual_account, "account_number", None):
        return None

    bank = getattr(virtual_account, "bank", None)
    return {
        "bank": str(bank) if bank is not None else None,
        "account_number": virtual_account.account_number,
        "remittee_name": getattr(virtual_account, "remittee_name", None),
        "expired_at": getattr(virtual_account, "expired_at", None),
        "issued_at": getattr(virtual_account, "issued_at", None),
    }


def _extract_virtual_account_info(payment: Any) -> dict[str, Any]:
    virtual_account = _get_virtual_account_info(payment)
    if virtual_account is None:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_PAYMENT_STATUS,
        )
    return virtual_account


async def _upsert_virtual_account_binding(
    payment: Any,
    *,
    user_id: int,
    item: dict[str, Any],
    db: AsyncSession,
) -> None:
    virtual_account = _extract_virtual_account_info(payment)
    await db.execute(
        text(
            """
            INSERT INTO tb_portone_virtual_account_pending (
                payment_id, user_id, item_name, item_price,
                pg_tx_id, issued_at, expired_at, created_id, updated_id
            ) VALUES (
                :payment_id, :user_id, :item_name, :item_price,
                :pg_tx_id, :issued_at, :expired_at, :created_id, :updated_id
            )
            ON DUPLICATE KEY UPDATE
                user_id = VALUES(user_id),
                item_name = VALUES(item_name),
                item_price = VALUES(item_price),
                pg_tx_id = VALUES(pg_tx_id),
                issued_at = VALUES(issued_at),
                expired_at = VALUES(expired_at),
                updated_id = VALUES(updated_id)
            """
        ),
        {
            "payment_id": payment.id,
            "user_id": user_id,
            "item_name": item["name"],
            "item_price": int(item["price"]),
            "pg_tx_id": payment.transaction_id,
            "issued_at": virtual_account.get("issued_at"),
            "expired_at": virtual_account.get("expired_at"),
            "created_id": user_id or settings.DB_DML_PORTONE_ID,
            "updated_id": user_id or settings.DB_DML_PORTONE_ID,
        },
    )


async def _find_virtual_account_binding(
    payment_id: str, db: AsyncSession
) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT
                pending_id,
                payment_id,
                user_id,
                item_name,
                item_price,
                paid_synced_at
            FROM tb_portone_virtual_account_pending
            WHERE payment_id = :payment_id
            LIMIT 1
            """
        ),
        {"payment_id": payment_id},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else None


async def _find_active_virtual_account_binding_by_user(
    user_id: int, db: AsyncSession
) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT
                pending_id,
                payment_id,
                user_id,
                item_name,
                item_price,
                paid_synced_at,
                expired_at
            FROM tb_portone_virtual_account_pending
            WHERE user_id = :user_id
              AND paid_synced_at IS NULL
              AND expired_at IS NOT NULL
              AND expired_at > NOW()
            ORDER BY expired_at DESC, pending_id DESC
            LIMIT 1
            """
        ),
        {"user_id": user_id},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else None


def _verify_virtual_account_payment_against_binding(
    payment: portone.payment.PaidPayment, binding: dict[str, Any]
) -> None:
    if payment.order_name != binding["item_name"] or payment.amount.total != int(
        binding["item_price"]
    ):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_PAYMENT_STATUS,
        )


async def _mark_virtual_account_binding_paid(
    payment_id: str, user_id: int, db: AsyncSession
) -> None:
    await db.execute(
        text(
            """
            UPDATE tb_portone_virtual_account_pending
            SET paid_synced_at = NOW(),
                updated_id = :updated_id
            WHERE payment_id = :payment_id
            """
        ),
        {
            "payment_id": payment_id,
            "updated_id": user_id or settings.DB_DML_PORTONE_ID,
        },
    )


async def _acquire_payment_lock(db: AsyncSession, payment_id: str) -> bool:
    result = await db.execute(
        text("SELECT GET_LOCK(:lock_name, :timeout) AS locked"),
        {
            "lock_name": f"portone_va:{payment_id}",
            "timeout": PAYMENT_LOCK_TIMEOUT_SECONDS,
        },
    )
    row = result.mappings().one()
    return bool(row.get("locked"))


async def _release_payment_lock(db: AsyncSession, payment_id: str) -> None:
    try:
        await db.execute(
            text("SELECT RELEASE_LOCK(:lock_name)"),
            {"lock_name": f"portone_va:{payment_id}"},
        )
    except Exception as exc:
        logger.warning("failed to release virtual account lock: %s", exc)


def _build_order_no() -> str:
    order_date = datetime.now()
    random_str = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"OCC{order_date.strftime('%y%m%d')}{random_str}"


async def _find_existing_payment_row(
    payment_id: str, db: AsyncSession
) -> dict[str, Any] | None:
    result = await db.execute(
        text(
            """
            SELECT
                sp.id AS payment_row_id,
                sp.order_id,
                so.order_no,
                so.order_status
            FROM tb_store_payment sp
            JOIN tb_store_order so ON so.order_id = sp.order_id
            WHERE sp.pg_payment_id = :payment_id
            LIMIT 1
            """
        ),
        {"payment_id": payment_id},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else None


async def _create_cash_charge_order_for_virtual_account_paid(
    payment: portone.payment.PaidPayment, user_id: int, db: AsyncSession
) -> dict[str, Any]:
    existing = await _find_existing_payment_row(payment.id, db)
    if existing:
        return existing

    total_price = payment.amount.total
    charge_cash_amount = total_price * 1.1
    order_no = _build_order_no()
    order_item_name = payment.order_name

    order_result = await db.execute(
        text(
            """
            INSERT INTO tb_store_order (
                order_no, device_type, user_id, order_date,
                order_status, total_price, cancel_yn, created_id, updated_id
            ) VALUES (
                :order_no, :device_type, :user_id, NOW(), :order_status,
                :total_price, 'N', :created_id, :updated_id
            )
            """
        ),
        {
            "order_no": order_no,
            "device_type": "web",
            "user_id": user_id,
            "order_status": 10,
            "total_price": total_price,
            "created_id": user_id or settings.DB_DML_PORTONE_ID,
            "updated_id": user_id or settings.DB_DML_PORTONE_ID,
        },
    )
    order_id = order_result.lastrowid

    await db.execute(
        text(
            """
            INSERT INTO tb_store_order_item (
                order_id, item_id, item_name, item_price,
                cancel_yn, quantity, created_id, updated_id
            ) VALUES (
                :order_id, 'C', :item_name, :item_price,
                'N', 1, :created_id, :updated_id
            )
            """
        ),
        {
            "order_id": order_id,
            "item_name": order_item_name,
            "item_price": total_price,
            "created_id": user_id or settings.DB_DML_PORTONE_ID,
            "updated_id": user_id or settings.DB_DML_PORTONE_ID,
        },
    )

    await db.execute(
        text(
            """
            INSERT INTO tb_store_payment (
                order_id, total_price, pg_name, pg_payment_id,
                pg_tx_id, created_id, updated_id
            ) VALUES (
                :order_id, :total_price, 'PORTONE_INICIS_V2',
                :pg_payment_id, :pg_tx_id, :created_id, :updated_id
            )
            """
        ),
        {
            "order_id": order_id,
            "total_price": total_price,
            "pg_payment_id": payment.id,
            "pg_tx_id": payment.transaction_id,
            "created_id": user_id or settings.DB_DML_PORTONE_ID,
            "updated_id": user_id or settings.DB_DML_PORTONE_ID,
        },
    )

    await db.execute(
        text(
            """
            INSERT INTO tb_user_cashbook (user_id, balance, created_id, updated_id)
            VALUES (:user_id, :cash_amount, :created_id, :updated_id)
            """
        ),
        {
            "user_id": user_id,
            "cash_amount": charge_cash_amount,
            "created_id": user_id or settings.DB_DML_PORTONE_ID,
            "updated_id": user_id or settings.DB_DML_PORTONE_ID,
        },
    )

    await db.execute(
        text(
            """
            INSERT INTO tb_user_cashbook_transaction
            (from_user_id, to_user_id, amount, created_id, created_date, updated_id)
            VALUES (:from_user_id, :to_user_id, :amount, :created_id, NOW(), :updated_id)
            """
        ),
        {
            "from_user_id": user_id,
            "to_user_id": user_id,
            "amount": charge_cash_amount,
            "created_id": user_id or settings.DB_DML_PORTONE_ID,
            "updated_id": user_id or settings.DB_DML_PORTONE_ID,
        },
    )

    try:
        await statistics_service.insert_payment_statistics_log(
            db=db, type="pay", user_id=int(user_id), amount=total_price
        )
    except Exception as stats_error:
        logger.warning(
            "virtual account payment statistics logging failed - payment_id: %s, user_id: %s, amount: %s, error: %s",
            payment.id,
            user_id,
            total_price,
            stats_error,
        )

    return {
        "payment_row_id": None,
        "order_id": order_id,
        "order_no": order_no,
        "order_status": 10,
    }


async def payment_virtual_account_issued(
    req_body: payment_schema.VirtualAccountIssuedReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    try:
        actual_payment = portone_client.payment.get_payment(payment_id=req_body.payment_id)
    except Exception as exc:
        logger.error("virtual account issued lookup failed: %s", exc)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.PAYMENT_SERVICE_ERROR,
        ) from exc

    if not isinstance(actual_payment, portone.payment.VirtualAccountIssuedPayment):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_PAYMENT_STATUS,
        )

    item, _ = _verify_virtual_account_payment(
        actual_payment, expected_user_id=int(user_id)
    )
    await _upsert_virtual_account_binding(
        actual_payment,
        user_id=int(user_id),
        item=item,
        db=db,
    )

    return {
        "payment": {
            "status": "VIRTUAL_ACCOUNT_ISSUED",
            "payment_id": actual_payment.id,
            "tx_id": actual_payment.transaction_id,
        },
        "virtual_account": _extract_virtual_account_info(actual_payment),
    }


async def _sync_virtual_account_paid_payment(payment_id: str, db: AsyncSession) -> None:
    if not await _acquire_payment_lock(db, payment_id):
        raise CustomResponseException(
            status_code=status.HTTP_409_CONFLICT,
            message=ErrorMessages.PAYMENT_PROCESSING_ERROR,
        )

    try:
        try:
            actual_payment = portone_client.payment.get_payment(payment_id=payment_id)
        except Exception as exc:
            logger.error("virtual account paid lookup failed: %s", exc)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.PAYMENT_SERVICE_ERROR,
            ) from exc

        if not isinstance(actual_payment, portone.payment.PaidPayment):
            logger.info(
                "ignore non-paid virtual account webhook payment_id=%s status=%s",
                payment_id,
                getattr(actual_payment, "status", None),
            )
            return

        if _get_virtual_account_info(actual_payment) is None:
            logger.info(
                "ignore paid webhook without virtual account method payment_id=%s",
                payment_id,
            )
            return

        binding = await _find_virtual_account_binding(payment_id, db)
        if binding is None:
            logger.error(
                "missing virtual account binding for payment_id=%s", payment_id
            )
            raise CustomResponseException(
                status_code=status.HTTP_409_CONFLICT,
                message=ErrorMessages.PAYMENT_PROCESSING_ERROR,
            )

        _verify_virtual_account_payment_against_binding(actual_payment, binding)
        user_id = int(binding["user_id"])

        async with db.begin():
            await _create_cash_charge_order_for_virtual_account_paid(
                payment=actual_payment,
                user_id=user_id,
                db=db,
            )
            await _mark_virtual_account_binding_paid(
                payment_id=payment_id,
                user_id=user_id,
                db=db,
            )
    except SQLAlchemyError as exc:
        logger.error("virtual account paid db error: %s", exc)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_TRANSACTION_ERROR,
        ) from exc
    finally:
        await _release_payment_lock(db, payment_id)


async def get_raw_body(request: Request) -> bytes:
    return await request.body()


async def payment_receive_webhook(request: Request, body: bytes, db: AsyncSession):
    if not PORTONE_WEBHOOK_SECRET:
        logger.error("PORTONE_WEBHOOK_SECRET is missing")
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.PAYMENT_SERVICE_ERROR,
        )

    try:
        webhook = portone.webhook.verify(
            PORTONE_WEBHOOK_SECRET,
            body.decode("utf-8"),
            request.headers,
        )
    except portone.webhook.WebhookVerificationError as exc:
        logger.warning("invalid portone webhook signature: %s", exc)
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_PAYMENT_STATUS,
        ) from exc

    # SDK 타입 매칭 성공
    if isinstance(webhook, portone.webhook.WebhookTransactionPaid):
        await _sync_virtual_account_paid_payment(webhook.data.payment_id, db)
        return {"ok": True}

    # SDK 역직렬화 실패 → raw dict: 포트원 실제 페이로드 형식으로 처리
    # 실제 형식: {"tx_id":"...", "payment_id":"...", "status":"Paid"}
    if isinstance(webhook, dict):
        wh_status = webhook.get("status")
        payment_id = webhook.get("payment_id")
        if wh_status == "Paid" and payment_id:
            await _sync_virtual_account_paid_payment(payment_id, db)

    return {"ok": True}


async def payment_verify_virtual_account(
    req_body: payment_schema.VirtualAccountReqBody, user_id: str, db: AsyncSession
):
    if not req_body.payment_id:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_PAYMENT_STATUS,
        )

    actual_user_id = await comm_service.get_user_from_kc(user_id, db)
    if actual_user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    try:
        actual_payment = portone_client.payment.get_payment(payment_id=req_body.payment_id)
    except Exception as exc:
        logger.error("virtual account verify lookup failed: %s", exc)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.PAYMENT_SERVICE_ERROR,
        ) from exc

    if isinstance(actual_payment, portone.payment.VirtualAccountIssuedPayment):
        item, _ = _verify_virtual_account_payment(
            actual_payment, expected_user_id=int(actual_user_id)
        )
        await _upsert_virtual_account_binding(
            actual_payment,
            user_id=int(actual_user_id),
            item=item,
            db=db,
        )
        return {
            "payment": {
                "status": "VIRTUAL_ACCOUNT_ISSUED",
                "payment_id": actual_payment.id,
                "tx_id": actual_payment.transaction_id,
            },
            "virtual_account": _extract_virtual_account_info(actual_payment),
        }

    if isinstance(actual_payment, portone.payment.PaidPayment):
        _extract_virtual_account_info(actual_payment)
        item, _ = _verify_virtual_account_payment(
            actual_payment, expected_user_id=int(actual_user_id)
        )
        await _upsert_virtual_account_binding(
            actual_payment,
            user_id=int(actual_user_id),
            item=item,
            db=db,
        )
        await _sync_virtual_account_paid_payment(actual_payment.id, db)
        return {
            "payment": {
                "status": "PAID",
                "payment_id": actual_payment.id,
                "tx_id": actual_payment.transaction_id,
            }
        }

    raise CustomResponseException(
        status_code=status.HTTP_400_BAD_REQUEST,
        message=ErrorMessages.INVALID_PAYMENT_STATUS,
    )


async def get_active_virtual_account_pending(kc_user_id: str, db: AsyncSession):
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    binding = await _find_active_virtual_account_binding_by_user(int(user_id), db)
    if binding is None:
        return {"has_pending": False}

    try:
        actual_payment = portone_client.payment.get_payment(
            payment_id=binding["payment_id"]
        )
    except Exception as exc:
        logger.error("active virtual account lookup failed: %s", exc)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.PAYMENT_SERVICE_ERROR,
        ) from exc

    if isinstance(actual_payment, portone.payment.VirtualAccountIssuedPayment):
        item, _ = _verify_virtual_account_payment(
            actual_payment, expected_user_id=int(user_id)
        )
        await _upsert_virtual_account_binding(
            actual_payment,
            user_id=int(user_id),
            item=item,
            db=db,
        )
        return {
            "has_pending": True,
            "payment": {
                "status": "VIRTUAL_ACCOUNT_ISSUED",
                "payment_id": actual_payment.id,
                "tx_id": actual_payment.transaction_id,
            },
            "virtual_account": _extract_virtual_account_info(actual_payment),
        }

    if isinstance(actual_payment, portone.payment.PaidPayment):
        _extract_virtual_account_info(actual_payment)
        item, _ = _verify_virtual_account_payment(
            actual_payment, expected_user_id=int(user_id)
        )
        await _upsert_virtual_account_binding(
            actual_payment,
            user_id=int(user_id),
            item=item,
            db=db,
        )
        await _sync_virtual_account_paid_payment(actual_payment.id, db)
        return {
            "has_pending": False,
            "payment": {
                "status": "PAID",
                "payment_id": actual_payment.id,
                "tx_id": actual_payment.transaction_id,
            },
        }

    return {"has_pending": False}
