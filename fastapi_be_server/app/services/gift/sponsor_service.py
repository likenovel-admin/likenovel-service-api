from app.services.common import comm_service
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.const import settings, ErrorMessages
from app.exceptions import CustomResponseException
from app.utils.common import handle_exceptions
import app.services.common.statistics_service as statistics_service
import app.schemas.author as author_schema
import app.schemas.product as product_schema

logger = logging.getLogger(__name__)

"""
sponsor 도메인 개별 서비스 함수 모음
"""


@handle_exceptions
async def sponsor_author(
    author_id: int,
    req_body: author_schema.SponsorAuthorReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    캐시로 작가 후원
    """
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    # kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # 작가 존재 여부 확인 (작가의 작품이 있는지 확인)
    query = text("""
        SELECT author_name
        FROM tb_product
        WHERE author_id = :author_id
        LIMIT 1
    """)
    result = await db.execute(query, {"author_id": author_id})
    author_product_row = result.mappings().one_or_none()

    if not author_product_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_AUTHOR,
        )

    author_nickname = author_product_row["author_name"]

    # 후원자(사용자) 닉네임 조회
    query = text("""
        SELECT nickname
        FROM tb_user_profile
        WHERE user_id = :user_id
        AND profile_id = :profile_id
    """)
    result = await db.execute(
        query, {"user_id": user_id, "profile_id": req_body.profile_id}
    )
    profile_row = result.mappings().one_or_none()

    if not profile_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_PROFILE,
        )

    sponsor_nickname = profile_row["nickname"]

    # 사용자 캐시 잔액 조회
    query = text("""
        SELECT COALESCE(SUM(balance), 0) AS balance
        FROM tb_user_cashbook
        WHERE user_id = :user_id
    """)
    result = await db.execute(query, {"user_id": user_id})
    cashbook_row = result.mappings().one_or_none()

    if not cashbook_row or cashbook_row["balance"] < req_body.donation_price:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INSUFFICIENT_CASH_BALANCE,
        )

    # 캐시 차감
    query = text("""
        INSERT INTO tb_user_cashbook
        (user_id, balance, created_id, created_date, updated_id, updated_date)
        VALUES (:user_id, :amount, :created_id, NOW(), :updated_id, NOW())
    """)
    await db.execute(
        query,
        {
            "user_id": user_id,
            "amount": -req_body.donation_price,
            "created_id": settings.DB_DML_DEFAULT_ID,
            "updated_id": settings.DB_DML_DEFAULT_ID,
        },
    )

    # 캐시 거래 내역 등록 (작가 후원)
    query = text("""
        INSERT INTO tb_user_cashbook_transaction
        (from_user_id, to_user_id, amount, sponsor_type, product_id, created_id, created_date)
        VALUES (:from_user_id, :to_user_id, :amount, 'author', 0, :created_id, NOW())
    """)
    await db.execute(
        query,
        {
            "from_user_id": user_id,
            "to_user_id": author_id,  # 후원 대상 작가
            "amount": req_body.donation_price,
            "created_id": settings.DB_DML_DEFAULT_ID,
        },
    )

    # 후원 기록 저장 (tb_ptn_sponsorship_recodes) - 작가 후원
    query = text("""
        INSERT INTO tb_ptn_sponsorship_recodes
        (product_id, title, author_nickname, author_id, user_name, donation_price, sponsor_type, created_id, created_date, updated_id, updated_date)
        VALUES (0, '', :author_nickname, :author_id, :user_name, :donation_price, 'author', :created_id, NOW(), :updated_id, NOW())
    """)
    await db.execute(
        query,
        {
            "author_nickname": author_nickname,
            "author_id": author_id,
            "user_name": sponsor_nickname,
            "donation_price": req_body.donation_price,
            "created_id": user_id,
            "updated_id": user_id,
        },
    )

    # 정산용 일별 판매 데이터 기록 - 작가 후원
    query = text("""
        INSERT INTO tb_batch_daily_sales_summary
        (item_type, item_name, item_price, quantity, device_type, user_id, order_date, product_id, episode_id, author_id, pay_type, created_date)
        VALUES ('sponsorship', :item_name, :item_price, 1, 'web', :user_id, NOW(), 0, 0, :author_id, 'cash', NOW())
    """)
    await db.execute(
        query,
        {
            "item_name": f"{author_nickname} 작가 후원",
            "item_price": req_body.donation_price,
            "user_id": user_id,
            "author_id": author_id,
        },
    )

    # 통계 로그 추가
    await statistics_service.insert_site_statistics_log(
        db=db, type="active", user_id=user_id
    )

    # 작가에게 후원 알림 전송 (3. 후원 알림)
    try:
        notification_title = (
            f"[{sponsor_nickname}]님이 작가에게 {req_body.donation_price:,}원 후원"
        )
        notification_content = req_body.message if req_body.message else ""

        notification_query = text("""
            INSERT INTO tb_user_notification_item
            (user_id, noti_type, title, content, read_yn, created_id, created_date)
            VALUES (:user_id, 'sponsor', :title, :content, 'N', :created_id, NOW())
        """)
        await db.execute(
            notification_query,
            {
                "user_id": author_id,
                "title": notification_title,
                "content": notification_content,
                "created_id": user_id,
            },
        )
    except Exception as e:
        # 알림 실패해도 후원은 성공으로 처리
        logger.warning(f"Failed to send sponsor notification: {e}")

    # 남은 캐시 잔액 조회
    query = text("""
        SELECT COALESCE(SUM(balance), 0) AS balance
        FROM tb_user_cashbook
        WHERE user_id = :user_id
    """)
    result = await db.execute(query, {"user_id": user_id})
    remaining_balance_row = result.mappings().one_or_none()
    remaining_balance = remaining_balance_row["balance"] if remaining_balance_row else 0

    return {
        "result": True,
        "data": {
            "donationPrice": req_body.donation_price,
            "remainingBalance": remaining_balance,
        },
    }


@handle_exceptions
async def sponsor_product(
    product_id: int,
    req_body: product_schema.SponsorProductReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    캐시로 작품 후원
    """
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    # kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # 작품 존재 여부 확인
    query = text("""
        SELECT product_id, title, author_name, author_id
        FROM tb_product
        WHERE product_id = :product_id
    """)
    result = await db.execute(query, {"product_id": product_id})
    product_row = result.mappings().one_or_none()

    if not product_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_PRODUCT,
        )

    product_title = product_row["title"]
    author_nickname = product_row["author_name"]
    author_id = product_row["author_id"]

    # 후원자(사용자) 닉네임 조회
    query = text("""
        SELECT nickname
        FROM tb_user_profile
        WHERE user_id = :user_id
        AND profile_id = :profile_id
    """)
    result = await db.execute(
        query, {"user_id": user_id, "profile_id": req_body.profile_id}
    )
    profile_row = result.mappings().one_or_none()

    if not profile_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_PROFILE,
        )

    sponsor_nickname = profile_row["nickname"]

    # 사용자 캐시 잔액 조회
    query = text("""
        SELECT COALESCE(SUM(balance), 0) AS balance
        FROM tb_user_cashbook
        WHERE user_id = :user_id
    """)
    result = await db.execute(query, {"user_id": user_id})
    cashbook_row = result.mappings().one_or_none()

    if not cashbook_row or cashbook_row["balance"] < req_body.donation_price:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INSUFFICIENT_CASH_BALANCE,
        )

    # 캐시 차감
    query = text("""
        INSERT INTO tb_user_cashbook
        (user_id, balance, created_id, created_date, updated_id, updated_date)
        VALUES (:user_id, :amount, :created_id, NOW(), :updated_id, NOW())
    """)
    await db.execute(
        query,
        {
            "user_id": user_id,
            "amount": -req_body.donation_price,
            "created_id": settings.DB_DML_DEFAULT_ID,
            "updated_id": settings.DB_DML_DEFAULT_ID,
        },
    )

    # 캐시 거래 내역 등록 (작품 후원)
    query = text("""
        INSERT INTO tb_user_cashbook_transaction
        (from_user_id, to_user_id, amount, sponsor_type, product_id, created_id, created_date)
        VALUES (:from_user_id, :to_user_id, :amount, 'product', :product_id, :created_id, NOW())
    """)
    await db.execute(
        query,
        {
            "from_user_id": user_id,
            "to_user_id": author_id,  # 후원 대상 작가
            "amount": req_body.donation_price,
            "product_id": product_id,
            "created_id": settings.DB_DML_DEFAULT_ID,
        },
    )

    # 후원 기록 저장 (tb_ptn_sponsorship_recodes) - 작품 후원
    query = text("""
        INSERT INTO tb_ptn_sponsorship_recodes
        (product_id, title, author_nickname, author_id, user_name, donation_price, sponsor_type, created_id, created_date, updated_id, updated_date)
        VALUES (:product_id, :title, :author_nickname, :author_id, :user_name, :donation_price, 'product', :created_id, NOW(), :updated_id, NOW())
    """)
    await db.execute(
        query,
        {
            "product_id": product_id,
            "title": product_title,
            "author_nickname": author_nickname,
            "author_id": author_id,
            "user_name": sponsor_nickname,
            "donation_price": req_body.donation_price,
            "created_id": user_id,
            "updated_id": user_id,
        },
    )

    # 정산용 일별 판매 데이터 기록
    query = text("""
        INSERT INTO tb_batch_daily_sales_summary
        (item_type, item_name, item_price, quantity, device_type, user_id, order_date, product_id, episode_id, author_id, pay_type, created_date)
        VALUES ('sponsorship', :item_name, :item_price, 1, 'web', :user_id, NOW(), :product_id, 0, :author_id, 'cash', NOW())
    """)
    await db.execute(
        query,
        {
            "item_name": f"{product_title} 후원",
            "item_price": req_body.donation_price,
            "user_id": user_id,
            "product_id": product_id,
            "author_id": author_id,
        },
    )

    # 통계 로그 추가
    await statistics_service.insert_site_statistics_log(
        db=db, type="active", user_id=user_id
    )

    # 작가에게 후원 알림 전송
    try:
        notification_title = f"[{sponsor_nickname}]님이 [{product_title}]에 {req_body.donation_price:,}원 후원"
        notification_content = req_body.message if req_body.message else ""

        notification_query = text("""
            INSERT INTO tb_user_notification_item
            (user_id, noti_type, title, content, read_yn, created_id, created_date)
            VALUES (:user_id, 'sponsor', :title, :content, 'N', :created_id, NOW())
        """)
        await db.execute(
            notification_query,
            {
                "user_id": author_id,
                "title": notification_title,
                "content": notification_content,
                "created_id": user_id,
            },
        )
    except Exception as e:
        # 알림 실패해도 후원은 성공으로 처리
        logger.warning(f"Failed to send sponsor notification: {e}")

    # 남은 캐시 잔액 조회
    query = text("""
        SELECT COALESCE(SUM(balance), 0) AS balance
        FROM tb_user_cashbook
        WHERE user_id = :user_id
    """)
    result = await db.execute(query, {"user_id": user_id})
    remaining_balance_row = result.mappings().one_or_none()
    remaining_balance = remaining_balance_row["balance"] if remaining_balance_row else 0

    return {
        "result": True,
        "data": {
            "donationPrice": req_body.donation_price,
            "remainingBalance": remaining_balance,
        },
    }
