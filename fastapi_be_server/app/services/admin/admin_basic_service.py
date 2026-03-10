import logging
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import portone_server_sdk as portone

from app.const import ErrorMessages, settings
from app.exceptions import CustomResponseException
import app.schemas.admin as admin_schema
from app.services.common import comm_service
from app.utils.query import build_update_query, get_file_path_sub_query
from app.utils.response import check_exists_or_404

logger = logging.getLogger("admin_app")
portone_client = portone.PortOneClient(secret=settings.PORTONE_SECRET_KEY)

"""
관리자 기본 서비스 함수 모음
"""


async def get_latest_updated_date(table_name: str, db: AsyncSession):
    """
    테이블의 최신 업데이트 날짜 조회

    Args:
        table_name: 조회할 테이블명
        db: 데이터베이스 세션

    Returns:
        최신 업데이트 날짜 (created_date 또는 updated_date 중 최신값)
    """
    query = text(f"""
                 SELECT MAX(IF(updated_date IS NULL, created_date, updated_date)) AS latest_updated_date FROM {table_name}
                 """)
    result = await db.execute(query, {})
    row = result.mappings().one()
    return dict(row).get("latest_updated_date")


async def admin_detail_by_user_id(user_id, db: AsyncSession):
    """
    관리자(admin) 상세 조회

    Args:
        user_id: 조회할 관리자 ID
        db: 데이터베이스 세션

    Returns:
        관리자 상세 정보
    """
    query = text("""
                    SELECT * FROM tb_user WHERE user_id = :user_id AND role_type = "admin"
                    """)
    result = await db.execute(query, {"user_id": user_id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_MEMBER)

    return dict(rows[0])


async def admin_profiles_of_admin(user_id, db: AsyncSession):
    """
    관리자(admin) 프로필 조회

    Args:
        user_id: 조회할 관리자 ID
        db: 데이터베이스 세션

    Returns:
        관리자 프로필 리스트
    """
    await admin_detail_by_user_id(user_id, db)

    query = text(f"""
                 SELECT
                    *,
                    {get_file_path_sub_query("up.profile_image_id", "profile_image_path")}
                 FROM tb_user_profile up WHERE user_id = :user_id
                 """)
    result = await db.execute(query, {"user_id": user_id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_MEMBER)

    return [dict(row) for row in rows]


async def put_user(
    user_id: int, req_body: admin_schema.PutUserReqBody, db: AsyncSession
):
    """
    사용자 정보 수정

    Args:
        user_id: 수정할 사용자 ID
        req_body: 수정할 사용자 정보 (역할 타입 등)
        db: 데이터베이스 세션

    Returns:
        수정 결과 정보
    """

    if req_body is not None:
        logger.info(f"put_user: {req_body}")

    query = text("""
                    SELECT * FROM tb_user WHERE user_id = :user_id
                    """)
    result = await db.execute(query, {"user_id": user_id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_MEMBER)

    set_clause, params = build_update_query(req_body, allowed_fields=["role_type"])
    params["user_id"] = user_id

    query = text(f"UPDATE tb_user SET {set_clause} WHERE user_id = :user_id")

    await db.execute(query, params)

    return {"result": req_body}


async def get_product_simple_list(db: AsyncSession):
    """
    상품 간단 목록 조회

    Args:
        db: 데이터베이스 세션

    Returns:
        상품 ID와 제목이 포함된 간단 리스트
    """
    query = text("""
        SELECT
            product_id, title
        FROM tb_product
        ORDER BY created_date DESC
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    return [dict(row) for row in rows]


async def get_common_rate_data(db: AsyncSession):
    """
    비율 조정 데이터 조회

    Args:
        db: 데이터베이스 세션

    Returns:
        비율 조정 데이터
    """

    query = text("""
        SELECT
            *
        FROM tb_common_code
        WHERE code_group = 'common_rate'
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    default_settlement_rate = 0
    donation_settlement_rate = 0
    payment_fee_rate = 0
    tax_amount_rate = 0
    for row in rows:
        data = dict(row)
        if data["code_key"] == "default_settlement_rate":
            default_settlement_rate = float(data["code_value"])
        if data["code_key"] == "donation_settlement_rate":
            donation_settlement_rate = float(data["code_value"])
        if data["code_key"] == "payment_fee_rate":
            payment_fee_rate = float(data["code_value"])
        if data["code_key"] == "tax_amount_rate":
            tax_amount_rate = float(data["code_value"])

    return {
        "default_settlement_rate": default_settlement_rate,
        "donation_settlement_rate": donation_settlement_rate,
        "payment_fee_rate": payment_fee_rate,
        "tax_amount_rate": tax_amount_rate,
    }


async def save_common_rate_data(
    req_body: admin_schema.PostCommonRateReqBody, db: AsyncSession
):
    """
    비율 조정 데이터 조회

    Args:
        req_body: 저장할 비율 조정 데이터
        db: 데이터베이스 세션

    Returns:
        저장된 비율 조정 데이터
    """

    query = text("""
        SELECT
            *
        FROM tb_common_code
        WHERE code_group = 'common_rate'
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    default_settlement_rate_id = 0
    donation_settlement_rate_id = 0
    payment_fee_rate_id = 0
    tax_amount_rate_id = 0
    for row in rows:
        data = dict(row)
        if data["code_key"] == "default_settlement_rate":
            default_settlement_rate_id = int(data["id"])
        if data["code_key"] == "donation_settlement_rate":
            donation_settlement_rate_id = int(data["id"])
        if data["code_key"] == "payment_fee_rate":
            payment_fee_rate_id = int(data["id"])
        if data["code_key"] == "tax_amount_rate":
            tax_amount_rate_id = int(data["id"])

    if default_settlement_rate_id == 0:
        # 없으면 insert
        query = text("""
                     INSERT INTO tb_common_code (id, code_group, code_key, code_value, code_desc, created_id, created_date)
                     VALUES (DEFAULT, 'common_rate', 'default_settlement_rate', :value, '기본 정산율 - 작가 기준', -1, CURRENT_TIMESTAMP)
                     """)
        await db.execute(query, {"value": req_body.default_settlement_rate})
    else:
        # 있으면 update
        query = text("""
                     UPDATE tb_common_code SET code_value = :value WHERE id = :id
                     """)
        await db.execute(
            query,
            {
                "value": req_body.default_settlement_rate,
                "id": default_settlement_rate_id,
            },
        )

    if donation_settlement_rate_id == 0:
        # 없으면 insert
        query = text("""
                     INSERT INTO tb_common_code (id, code_group, code_key, code_value, code_desc, created_id, created_date)
                     VALUES (DEFAULT, 'common_rate', 'donation_settlement_rate', :value, '후원 정산율 - 작가 기준', -1, CURRENT_TIMESTAMP)
                     """)
        await db.execute(query, {"value": req_body.donation_settlement_rate})
    else:
        # 있으면 update
        query = text("""
                     UPDATE tb_common_code SET code_value = :value WHERE id = :id
                     """)
        await db.execute(
            query,
            {
                "value": req_body.donation_settlement_rate,
                "id": donation_settlement_rate_id,
            },
        )

    if payment_fee_rate_id == 0:
        # 없으면 insert
        query = text("""
                     INSERT INTO tb_common_code (id, code_group, code_key, code_value, code_desc, created_id, created_date)
                     VALUES (DEFAULT, 'common_rate', 'payment_fee_rate', :value, '결제 수수료', -1, CURRENT_TIMESTAMP)
                     """)
        await db.execute(query, {"value": req_body.payment_fee_rate})
    else:
        # 있으면 update
        query = text("""
                     UPDATE tb_common_code SET code_value = :value WHERE id = :id
                     """)
        await db.execute(
            query, {"value": req_body.payment_fee_rate, "id": payment_fee_rate_id}
        )

    if tax_amount_rate_id == 0:
        # 없으면 insert
        query = text("""
                     INSERT INTO tb_common_code (id, code_group, code_key, code_value, code_desc, created_id, created_date)
                     VALUES (DEFAULT, 'common_rate', 'tax_amount_rate', :value, '세액', -1, CURRENT_TIMESTAMP)
                     """)
        await db.execute(query, {"value": req_body.tax_amount_rate})
    else:
        # 있으면 update
        query = text("""
                     UPDATE tb_common_code SET code_value = :value WHERE id = :id
                     """)
        await db.execute(
            query, {"value": req_body.tax_amount_rate, "id": tax_amount_rate_id}
        )

    return {
        "default_settlement_rate": req_body.default_settlement_rate,
        "donation_settlement_rate": req_body.donation_settlement_rate,
        "payment_fee_rate": req_body.payment_fee_rate,
        "tax_amount_rate": req_body.tax_amount_rate,
    }


async def post_cancel_cash_charge_order(
    order_id: int,
    req_body: admin_schema.PostCancelCashChargeOrderReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    Admin-only: cancel a cash charge payment when the user has never spent cash.
    """
    admin_user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if admin_user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    reason = (
        req_body.reason.strip()
        if req_body and req_body.reason and req_body.reason.strip()
        else "Admin canceled unused cash charge"
    )

    async with db.begin():
        order_query = text(
            """
            SELECT
                so.order_id,
                so.order_no,
                so.user_id,
                so.cancel_yn,
                so.total_price,
                soi.id AS order_item_id,
                sp.id AS payment_info_id,
                sp.pg_payment_id
            FROM tb_store_order so
            LEFT JOIN tb_store_order_item soi ON soi.order_id = so.order_id
            LEFT JOIN tb_store_payment sp ON sp.order_id = so.order_id
            WHERE so.order_id = :order_id
            ORDER BY soi.id ASC
            LIMIT 1
            FOR UPDATE
            """
        )
        order_result = await db.execute(order_query, {"order_id": order_id})
        order_row = order_result.mappings().one_or_none()
        if not order_row:
            raise CustomResponseException(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Order not found.",
            )

        order_data = dict(order_row)
        if order_data.get("cancel_yn") == "Y":
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Order is already canceled.",
            )

        order_no = str(order_data.get("order_no") or "")
        if not order_no.startswith("OC"):
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Only cash charge orders can be canceled by this API.",
            )

        if not order_data.get("pg_payment_id") or not order_data.get("payment_info_id"):
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Payment information is missing for this order.",
            )

        if not order_data.get("order_item_id"):
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Order item is missing for this order.",
            )

        refund_exists_query = text(
            """
            SELECT id
            FROM tb_store_refund
            WHERE order_id = :order_id
            LIMIT 1
            """
        )
        refund_exists_result = await db.execute(refund_exists_query, {"order_id": order_id})
        if refund_exists_result.mappings().one_or_none():
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Refund already exists for this order.",
            )

        cash_used_query = text(
            """
            SELECT 1
            FROM tb_user_cashbook_transaction t
            WHERE t.from_user_id = :user_id
              AND t.use_yn = 'Y'
              AND t.to_user_id <> t.from_user_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM tb_user u
                  WHERE u.user_id = t.created_id
                    AND u.role_type = 'admin'
              )
            LIMIT 1
            """
        )
        cash_used_result = await db.execute(
            cash_used_query, {"user_id": int(order_data["user_id"])}
        )
        if cash_used_result.mappings().one_or_none():
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="User has already spent cash and is not eligible for cancel.",
            )

        charge_cash_amount = (int(order_data["total_price"]) * 11) // 10
        if charge_cash_amount <= 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Invalid charge amount.",
            )

        balance_query = text(
            """
            SELECT COALESCE(SUM(balance), 0) AS balance
            FROM tb_user_cashbook
            WHERE user_id = :user_id
            """
        )
        balance_result = await db.execute(
            balance_query, {"user_id": int(order_data["user_id"])}
        )
        balance_row = balance_result.mappings().one_or_none()
        current_balance = int((balance_row or {}).get("balance", 0))
        if current_balance < charge_cash_amount:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.INSUFFICIENT_CASH_BALANCE,
            )

        try:
            portone_client.payment.cancel_payment(
                payment_id=order_data["pg_payment_id"],
                reason=reason,
            )
        except Exception as e:
            logger.error(
                "cash charge cancel failed in payment gateway - order_id=%s, error=%s",
                order_id,
                str(e),
            )
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.PAYMENT_SERVICE_ERROR,
            )

        refund_insert_query = text(
            """
            INSERT INTO tb_store_refund
            (refund_type, order_item_id, payment_info_id, order_id, refund_price, created_id, updated_id)
            VALUES
            ('cancel', :order_item_id, :payment_info_id, :order_id, :refund_price, :created_id, :updated_id)
            """
        )
        await db.execute(
            refund_insert_query,
            {
                "order_item_id": int(order_data["order_item_id"]),
                "payment_info_id": int(order_data["payment_info_id"]),
                "order_id": int(order_data["order_id"]),
                "refund_price": int(order_data["total_price"]),
                "created_id": admin_user_id,
                "updated_id": admin_user_id,
            },
        )

        cancel_order_query = text(
            """
            UPDATE tb_store_order
            SET cancel_yn = 'Y', updated_id = :updated_id, updated_date = NOW()
            WHERE order_id = :order_id
            """
        )
        await db.execute(
            cancel_order_query,
            {"order_id": int(order_data["order_id"]), "updated_id": admin_user_id},
        )

        cancel_order_item_query = text(
            """
            UPDATE tb_store_order_item
            SET cancel_yn = 'Y', updated_id = :updated_id, updated_date = NOW()
            WHERE order_id = :order_id
            """
        )
        await db.execute(
            cancel_order_item_query,
            {"order_id": int(order_data["order_id"]), "updated_id": admin_user_id},
        )

        cashbook_insert_query = text(
            """
            INSERT INTO tb_user_cashbook (user_id, balance, created_id, updated_id)
            VALUES (:user_id, :balance, :created_id, :updated_id)
            """
        )
        await db.execute(
            cashbook_insert_query,
            {
                "user_id": int(order_data["user_id"]),
                "balance": -charge_cash_amount,
                "created_id": admin_user_id,
                "updated_id": admin_user_id,
            },
        )

        cash_tx_insert_query = text(
            """
            INSERT INTO tb_user_cashbook_transaction
            (from_user_id, to_user_id, amount, created_id, created_date, updated_id)
            VALUES (:from_user_id, -1, :amount, :created_id, NOW(), :updated_id)
            """
        )
        await db.execute(
            cash_tx_insert_query,
            {
                "from_user_id": int(order_data["user_id"]),
                "amount": charge_cash_amount,
                "created_id": admin_user_id,
                "updated_id": admin_user_id,
            },
        )

    return {
        "result": True,
        "data": {
            "order_id": int(order_data["order_id"]),
            "user_id": int(order_data["user_id"]),
            "refund_price": int(order_data["total_price"]),
            "reversed_cash_amount": int(charge_cash_amount),
            "pg_payment_id": order_data["pg_payment_id"],
        },
    }
