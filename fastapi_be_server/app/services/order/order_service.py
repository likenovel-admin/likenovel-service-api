from app.services.common import comm_service
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
from dataclasses import dataclass

from app.exceptions import CustomResponseException
from app.const import settings, ErrorMessages

import json
import portone_server_sdk as portone

import logging
import app.schemas.order as order_schema

import random
import string
import app.services.common.statistics_service as statistics_service

"""
orders 도메인 개별 서비스 함수 모음
"""


@dataclass
class Item:
    id: str
    name: str
    price: int
    currency: portone.common.Currency


@dataclass
class Payment:
    status: str


items = {
    item.id: item
    for item in [
        Item("1", "cash", 1000, "KRW"),
        Item("1", "cash", 5000, "KRW"),
        Item("1", "cash", 10000, "KRW"),
        Item("1", "cash", 30000, "KRW"),
        Item("1", "cash", 50000, "KRW"),
        Item("1", "cash", 100000, "KRW"),
    ]
}
portone_client = portone.PortOneClient(secret=settings.PORTONE_SECRET_KEY)

payment_store = {}

# 로그 설정
logging.basicConfig(
    level=logging.INFO,  # 로그 수준: DEBUG, INFO, WARNING, ERROR, CRITICAL
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger("order_app")  # 커스텀 로거 생성


async def order_cash_payment_complete_with_payment_id(
    req_body: order_schema.OrderCashReqBody, kc_user_id: str, db: AsyncSession
):
    """
    캐시 결제 완료 처리
    """
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    payment_id = req_body.payment_id

    if payment_id not in payment_store:
        payment_store[payment_id] = Payment("PENDING")

    payment = payment_store[payment_id]

    # 실제 결제 정보 조회
    try:
        actual_payment = portone_client.payment.get_payment(payment_id=payment_id)
    except Exception as e:
        logger.error(f"오류 발생: {str(e)}")
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.PAYMENT_SERVICE_ERROR,
        )

    # 결제 완료 상태인 경우만 처리
    if not isinstance(actual_payment, portone.payment.PaidPayment):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_PAYMENT_STATUS,
        )

    if payment.status == "PAID":
        return payment

    payment.status = "PAID"

    # 주문번호 생성
    order_date = datetime.now()
    pay_method = "C"
    random_str = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    order_no = f"OC{pay_method}{order_date.strftime('%y%m%d')}{random_str}"

    device_type = "web"
    total_price = actual_payment.amount.total
    order_item_name = actual_payment.order_name

    # 결제 수단별 상태 설정
    method = actual_payment.method
    if getattr(method, "card", None) is not None:
        order_status = 20  # 카드 결제
    elif getattr(method, "easy_pay", None) is not None or hasattr(method, "provider"):
        order_status = 15  # 간편결제
    else:
        order_status = 10  # 기타 결제수단

    # 데이터베이스 작업 수행 (get_likenovel_db가 자동으로 commit 처리)
    try:
        if user_id is None:
            user_id = settings.DB_DML_DEFAULT_ID

        # 주문 생성
        order_query = text("""
            INSERT INTO tb_store_order (
                order_no, device_type, user_id, order_date,
                order_status, total_price, cancel_yn, created_id, updated_id
            ) VALUES (
                :order_no, :device_type, :user_id, NOW(), :order_status,
                :total_price, 'N', :created_id, :updated_id
            )
        """)
        result = await db.execute(
            order_query,
            {
                "order_no": order_no,
                "device_type": device_type,
                "user_id": user_id,
                "order_status": order_status,
                "total_price": total_price,
                "created_id": user_id or settings.DB_DML_PORTONE_ID,
                "updated_id": user_id or settings.DB_DML_PORTONE_ID,
            },
        )
        order_id = result.lastrowid

        # 주문 아이템 추가
        order_item_query = text("""
            INSERT INTO tb_store_order_item (
                order_id, item_id, item_name, item_price,
                cancel_yn, quantity, created_id, updated_id
            ) VALUES (
                :order_id, 'C', :item_name, :item_price,
                'N', 1, :created_id, :updated_id
            )
        """)
        await db.execute(
            order_item_query,
            {
                "order_id": order_id,
                "item_name": order_item_name,
                "item_price": total_price,
                "created_id": user_id or settings.DB_DML_PORTONE_ID,
                "updated_id": user_id or settings.DB_DML_PORTONE_ID,
            },
        )

        # 결제 정보 저장
        pg_payment_id = actual_payment.id
        pg_tx_id = actual_payment.transaction_id
        order_payment_query = text("""
            INSERT INTO tb_store_payment (
                order_id, total_price, pg_name, pg_payment_id,
                pg_tx_id, created_id, updated_id
            ) VALUES (
                :order_id, :total_price, 'PORTONE_INICIS_V2',
                :pg_payment_id, :pg_tx_id, :created_id, :updated_id
            )
        """)
        await db.execute(
            order_payment_query,
            {
                "order_id": order_id,
                "total_price": total_price,
                "pg_payment_id": pg_payment_id,
                "pg_tx_id": pg_tx_id,
                "created_id": user_id or settings.DB_DML_PORTONE_ID,
                "updated_id": user_id or settings.DB_DML_PORTONE_ID,
            },
        )

        # 캐시 충전 처리
        user_cash_query = text("""
            INSERT INTO tb_user_cashbook (user_id, balance, created_id, updated_id)
            VALUES (:user_id, :cash_amount, :created_id, :updated_id)
        """)
        await db.execute(
            user_cash_query,
            {
                "user_id": user_id,
                "cash_amount": total_price * 1.1,
                "created_id": user_id or settings.DB_DML_PORTONE_ID,
                "updated_id": user_id or settings.DB_DML_PORTONE_ID,
            },
        )

        # 캐시 충전 거래 내역 등록
        cash_transaction_query = text("""
            INSERT INTO tb_user_cashbook_transaction
            (from_user_id, to_user_id, amount, created_id, created_date, updated_id)
            VALUES (:from_user_id, :to_user_id, :amount, :created_id, NOW(), :updated_id)
        """)
        await db.execute(
            cash_transaction_query,
            {
                "from_user_id": user_id,
                "to_user_id": user_id,
                "amount": total_price * 1.1,
                "created_id": user_id or settings.DB_DML_PORTONE_ID,
                "updated_id": user_id or settings.DB_DML_PORTONE_ID,
            },
        )

        # 결제 통계 로그 기록 (실패해도 결제 성공에 영향을 주지 않음)
        try:
            await statistics_service.insert_payment_statistics_log(
                db=db, type="pay", user_id=int(user_id), amount=total_price
            )
        except Exception as stats_error:
            # 통계 로그 실패는 결제 성공에 영향을 주지 않음
            logger.warning(
                f"결제 통계 로그 기록 실패 (결제는 정상 처리됨) - payment_id: {payment_id}, "
                f"user_id: {user_id}, amount: {total_price}, error: {str(stats_error)}"
            )

    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"데이터베이스 트랜잭션 오류: {str(e)}")

        # PortOne 결제 취소 시도
        try:
            cancel_reason = f"데이터베이스 트랜잭션 오류: {str(e)}"
            portone_client.payment.cancel_payment(
                payment_id=payment_id, reason=cancel_reason
            )
            logger.info(
                f"결제 취소 성공 - payment_id: {payment_id}, reason: {cancel_reason}"
            )
        except Exception as cancel_error:
            logger.error(
                f"결제 취소 실패 - payment_id: {payment_id}, error: {str(cancel_error)}"
            )
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.PAYMENT_COMPLETED_BUT_PROCESS_FAILED,
            )

        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_TRANSACTION_ERROR,
        )

    except Exception as e:
        await db.rollback()
        logger.error(f"결제 처리 오류 발생: {str(e)}")

        # PortOne 결제 취소 시도
        try:
            cancel_reason = f"결제 처리 오류: {str(e)}"
            portone_client.payment.cancel_payment(
                payment_id=payment_id, reason=cancel_reason
            )
            logger.info(
                f"결제 취소 성공 - payment_id: {payment_id}, reason: {cancel_reason}"
            )
        except Exception as cancel_error:
            logger.error(
                f"결제 취소 실패 - payment_id: {payment_id}, error: {str(cancel_error)}"
            )
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.PAYMENT_COMPLETED_BUT_PROCESS_FAILED,
            )

        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.PAYMENT_PROCESSING_ERROR,
        )

    return {
        "order_no": order_no,
        "device_type": device_type,
        "payment": payment,
        "order_id": order_id,
        "pg_payment_id": pg_payment_id,
        "pg_tx_id": pg_tx_id,
    }


async def verify_payment(payment: portone.payment.PaidPayment) -> bool:
    """결제 검증"""
    if payment.custom_data is None:
        return False

    custom_data = json.loads(payment.custom_data)
    if "item" not in custom_data or custom_data["item"] not in items:
        return False

    item = items[custom_data["item"]]

    logger.info(f">item: {item}")
    logger.info(f">payment: {payment}")

    return (
        # payment.order_name == item.name
        payment.amount.total == item.price
        # and payment.amount.currency == item.currency
    )
