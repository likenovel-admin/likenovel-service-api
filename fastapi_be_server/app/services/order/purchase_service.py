from app.services.common import comm_service
from app.services.order.product_order_service import create_product_order_with_items
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import settings, CommonConstants, ErrorMessages
from app.exceptions import CustomResponseException
from app.utils.common import handle_exceptions
import app.services.common.statistics_service as statistics_service
import app.schemas.episode as episode_schema
import app.schemas.product as product_schema

"""
purchase 도메인 개별 서비스 함수 모음
"""


@handle_exceptions
async def purchase_episode_with_cash(
    episode_id: int,
    req_body: episode_schema.PurchaseEpisodeWithCashReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    캐시로 에피소드 구매 (소장)
    """
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    async with db.begin():
        # kc_user_id로 user_id 조회
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 에피소드 정보 조회 (product_id, price_type, item_name)
        query = text("""
            SELECT e.product_id, e.price_type, e.episode_no,
                   p.title as product_title
            FROM tb_product_episode e
            INNER JOIN tb_product p ON e.product_id = p.product_id
            WHERE e.episode_id = :episode_id
            AND e.use_yn = 'Y'
        """)
        result = await db.execute(query, {"episode_id": episode_id})
        episode_row = result.mappings().one_or_none()

        if not episode_row:
            raise CustomResponseException(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ErrorMessages.NOT_FOUND_EPISODE,
            )

        product_id = episode_row["product_id"]
        price_type = episode_row["price_type"]
        item_name = f"{episode_row['product_title']} - {episode_row['episode_no']}화"

        # 무료 에피소드는 구매 불가
        if price_type == "free" or price_type is None:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.FREE_EPISODE_CANNOT_PURCHASE,
            )

        # 이미 소장한 에피소드인지 확인
        # 1. 해당 에피소드를 직접 소장 (episode_id = X)
        # 2. 작품 전체 소장 (product_id = X AND episode_id IS NULL)
        # 3. 전체 무제한 이용권 (product_id IS NULL AND episode_id IS NULL)
        query = text("""
            SELECT id
            FROM tb_user_productbook
            WHERE user_id = :user_id
            AND use_yn = 'Y'
            AND own_type = 'own'
            AND (
                episode_id = :episode_id
                OR
                (product_id = (SELECT product_id FROM tb_product_episode WHERE episode_id = :episode_id) AND episode_id IS NULL)
                OR
                (product_id IS NULL AND episode_id IS NULL)
            )
        """)
        result = await db.execute(query, {"user_id": user_id, "episode_id": episode_id})
        owned_row = result.mappings().one_or_none()

        if owned_row:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.ALREADY_OWNED_EPISODE,
            )

        # 사용자 캐시 잔액 조회
        query = text("""
            SELECT COALESCE(SUM(balance), 0) AS balance
            FROM tb_user_cashbook
            WHERE user_id = :user_id
        """)
        result = await db.execute(query, {"user_id": user_id})
        cashbook_row = result.mappings().one_or_none()

        if (
            not cashbook_row
            or cashbook_row["balance"] < CommonConstants.EPISODE_PURCHASE_PRICE
        ):
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
                "amount": -CommonConstants.EPISODE_PURCHASE_PRICE,
                "created_id": settings.DB_DML_DEFAULT_ID,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        # 캐시 거래 내역 등록
        query = text("""
            INSERT INTO tb_user_cashbook_transaction
            (from_user_id, to_user_id, amount, created_id, created_date)
            VALUES (:from_user_id, :to_user_id, :amount, :created_id, NOW())
        """)
        await db.execute(
            query,
            {
                "from_user_id": user_id,
                "to_user_id": -1,  # 시스템
                "amount": CommonConstants.EPISODE_PURCHASE_PRICE,
                "created_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        # 소장 기록 등록
        query = text("""
            INSERT INTO tb_user_productbook
            (user_id, profile_id, product_id, episode_id, own_type, ticket_type, use_yn, created_id, created_date, updated_id, updated_date)
            VALUES (:user_id, :profile_id, :product_id, :episode_id, 'own', 'cash', 'Y', :created_id, NOW(), :updated_id, NOW())
        """)
        await db.execute(
            query,
            {
                "user_id": user_id,
                "profile_id": req_body.profile_id,
                "product_id": product_id,
                "episode_id": episode_id,
                "created_id": settings.DB_DML_DEFAULT_ID,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        await create_product_order_with_items(
            db=db,
            user_id=user_id,
            pay_type="cash",
            device_type="web",
            created_id=settings.DB_DML_DEFAULT_ID,
            items=[
                {
                    "item_name": item_name,
                    "item_price": CommonConstants.EPISODE_PURCHASE_PRICE,
                    "quantity": 1,
                    "product_id": product_id,
                    "episode_id": episode_id,
                }
            ],
        )

        # 통계 로그 추가
        await statistics_service.insert_site_statistics_log(
            db=db, type="active", user_id=user_id
        )

    return {"result": True}


@handle_exceptions
async def purchase_all_episodes_with_cash(
    product_id: int,
    req_body: product_schema.PurchaseAllEpisodesWithCashReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    캐시로 작품의 전체 에피소드 구매 또는 단행본 대여
    """
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    async with db.begin():
        # kc_user_id로 user_id 조회
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 작품 존재 여부 확인 및 작품명 조회
        purchase_type = getattr(req_body, "purchase_type", "own") or "own"
        if purchase_type not in {"own", "rental"}:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="유효하지 않은 구매 타입입니다.",
            )

        query = text("""
            SELECT product_id, title,
                   COALESCE(single_regular_price, 0) as single_regular_price,
                   COALESCE(single_rental_price, 0) as single_rental_price,
                   COALESCE(series_regular_price, 0) as series_regular_price
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
        single_regular_price = int(product_row.get("single_regular_price") or 0)
        single_rental_price = int(product_row.get("single_rental_price") or 0)
        series_regular_price = int(product_row.get("series_regular_price") or 0)
        if (
            series_regular_price > 0
            and (single_regular_price > 0 or single_rental_price > 0)
        ):
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="작품 가격 설정이 올바르지 않습니다.",
            )
        is_volume_product = (
            series_regular_price <= 0 and single_regular_price > 0
        )

        # 작품의 모든 에피소드 조회
        query = text("""
            SELECT episode_id, episode_no, price_type
            FROM tb_product_episode
            WHERE product_id = :product_id
            AND use_yn = 'Y'
            ORDER BY episode_id
        """)
        result = await db.execute(query, {"product_id": product_id})
        episodes = result.mappings().all()

        if not episodes:
            raise CustomResponseException(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ErrorMessages.NOT_FOUND_EPISODE,
            )

        # 이미 소장한 에피소드 조회
        # 1. 해당 작품의 특정 에피소드 소장
        # 2. 작품 전체 소장 (product_id = X AND episode_id IS NULL)
        # 3. 전체 무제한 이용권 (product_id IS NULL AND episode_id IS NULL)
        query = text("""
            SELECT episode_id
            FROM tb_user_productbook
            WHERE user_id = :user_id
            AND use_yn = 'Y'
            AND own_type = 'own'
            AND (
                episode_id IN (SELECT episode_id FROM tb_product_episode WHERE product_id = :product_id)
                OR
                (product_id = :product_id AND episode_id IS NULL)
                OR
                (product_id IS NULL AND episode_id IS NULL)
            )
        """)
        result = await db.execute(query, {"user_id": user_id, "product_id": product_id})
        owned_rows = result.mappings().all()
        owned_episodes = {row["episode_id"] for row in owned_rows}

        # 전체 무제한 이용권 또는 작품 전체 소장 여부 확인
        has_full_access = None in owned_episodes

        active_rental_query = text("""
            SELECT id
            FROM tb_user_productbook
            WHERE user_id = :user_id
              AND use_yn = 'Y'
              AND own_type = 'rental'
              AND (
                (product_id = :product_id AND episode_id IS NULL)
                OR
                (product_id IS NULL AND episode_id IS NULL)
              )
              AND (rental_expired_date IS NULL OR rental_expired_date > NOW())
            LIMIT 1
        """)
        active_rental_result = await db.execute(
            active_rental_query, {"user_id": user_id, "product_id": product_id}
        )
        has_active_rental_access = active_rental_result.mappings().first() is not None

        # 구매 가능한 에피소드 필터링
        episodes_to_purchase = []
        skipped_free_count = 0
        skipped_owned_count = 0

        for episode in episodes:
            episode_id = episode["episode_id"]
            price_type = episode["price_type"]

            # 무료 에피소드는 건너뛰기
            if price_type == "free" or price_type is None:
                skipped_free_count += 1
                continue

            # 전체 이용권이 있거나 이미 소장한 에피소드는 건너뛰기
            if has_full_access or episode_id in owned_episodes:
                skipped_owned_count += 1
                continue

            episodes_to_purchase.append(episode_id)

        # 구매할 에피소드가 없으면 에러
        if not episodes_to_purchase:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.FREE_EPISODE_CANNOT_PURCHASE,
            )

        if purchase_type == "rental":
            if not is_volume_product:
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="단행본만 대여할 수 있습니다.",
                )
            if single_rental_price <= 0:
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="대여 가격이 설정되지 않은 작품입니다.",
                )
            if has_full_access or has_active_rental_access:
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="이미 이용 중인 작품입니다.",
                )
            total_cash_needed = single_rental_price
        elif is_volume_product:
            if has_full_access:
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.ALREADY_OWNED_EPISODE,
                )
            total_cash_needed = single_regular_price
        else:
            total_cash_needed = (
                len(episodes_to_purchase) * CommonConstants.EPISODE_PURCHASE_PRICE
            )

        # 사용자 캐시 잔액 조회
        query = text("""
            SELECT COALESCE(SUM(balance), 0) AS balance
            FROM tb_user_cashbook
            WHERE user_id = :user_id
        """)
        result = await db.execute(query, {"user_id": user_id})
        cashbook_row = result.mappings().one_or_none()

        if not cashbook_row or cashbook_row["balance"] < total_cash_needed:
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
                "amount": -total_cash_needed,
                "created_id": settings.DB_DML_DEFAULT_ID,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        # 캐시 거래 내역 등록
        query = text("""
            INSERT INTO tb_user_cashbook_transaction
            (from_user_id, to_user_id, amount, created_id, created_date)
            VALUES (:from_user_id, :to_user_id, :amount, :created_id, NOW())
        """)
        await db.execute(
            query,
            {
                "from_user_id": user_id,
                "to_user_id": -1,  # 시스템
                "amount": total_cash_needed,
                "created_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        # 단행본 대여 기록 등록
        if purchase_type == "rental":
            query = text("""
                INSERT INTO tb_user_productbook
                (user_id, profile_id, product_id, episode_id, own_type, ticket_type, use_yn, rental_expired_date, created_id, created_date, updated_id, updated_date)
                VALUES (:user_id, :profile_id, :product_id, NULL, 'rental', 'cash', 'Y', DATE_ADD(NOW(), INTERVAL 3 DAY), :created_id, NOW(), :updated_id, NOW())
            """)
            await db.execute(
                query,
                {
                    "user_id": user_id,
                    "profile_id": req_body.profile_id,
                    "product_id": product_id,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            await create_product_order_with_items(
                db=db,
                user_id=user_id,
                pay_type="cash",
                device_type="web",
                created_id=settings.DB_DML_DEFAULT_ID,
                items=[
                    {
                        "item_name": f"{product_title} - 단행본 대여",
                        "item_price": total_cash_needed,
                        "quantity": 1,
                        "product_id": product_id,
                        "episode_id": None,
                    }
                ],
            )

            await statistics_service.insert_site_statistics_log(
                db=db, type="active", user_id=user_id
            )

            return {
                "result": True,
                "data": {
                    "purchasedCount": len(episodes_to_purchase),
                    "totalCashUsed": total_cash_needed,
                    "skippedFreeCount": skipped_free_count,
                    "skippedOwnedCount": skipped_owned_count,
                },
            }

        # 단행본 소장 기록 등록
        if is_volume_product:
            query = text("""
                INSERT INTO tb_user_productbook
                (user_id, profile_id, product_id, episode_id, own_type, ticket_type, use_yn, created_id, created_date, updated_id, updated_date)
                VALUES (:user_id, :profile_id, :product_id, NULL, 'own', 'cash', 'Y', :created_id, NOW(), :updated_id, NOW())
            """)
            await db.execute(
                query,
                {
                    "user_id": user_id,
                    "profile_id": req_body.profile_id,
                    "product_id": product_id,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            await create_product_order_with_items(
                db=db,
                user_id=user_id,
                pay_type="cash",
                device_type="web",
                created_id=settings.DB_DML_DEFAULT_ID,
                items=[
                    {
                        "item_name": f"{product_title} - 단행본 소장",
                        "item_price": total_cash_needed,
                        "quantity": 1,
                        "product_id": product_id,
                        "episode_id": None,
                    }
                ],
            )

            await statistics_service.insert_site_statistics_log(
                db=db, type="active", user_id=user_id
            )

            return {
                "result": True,
                "data": {
                    "purchasedCount": len(episodes_to_purchase),
                    "totalCashUsed": total_cash_needed,
                    "skippedFreeCount": skipped_free_count,
                    "skippedOwnedCount": skipped_owned_count,
                },
            }

        # 각 에피소드에 대한 소장 기록 등록
        order_items = []
        for episode_id in episodes_to_purchase:
            query = text("""
                INSERT INTO tb_user_productbook
                (user_id, profile_id, product_id, episode_id, own_type, ticket_type, use_yn, created_id, created_date, updated_id, updated_date)
                VALUES (:user_id, :profile_id, :product_id, :episode_id, 'own', 'cash', 'Y', :created_id, NOW(), :updated_id, NOW())
            """)
            await db.execute(
                query,
                {
                    "user_id": user_id,
                    "profile_id": req_body.profile_id,
                    "product_id": product_id,
                    "episode_id": episode_id,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            # 정산용 일별 판매 데이터 기록
            episode_info = next(
                (ep for ep in episodes if ep["episode_id"] == episode_id), None
            )
            item_name = (
                f"{product_title} - {episode_info['episode_no']}화"
                if episode_info
                else product_title
            )

            order_items.append(
                {
                    "item_name": item_name,
                    "item_price": CommonConstants.EPISODE_PURCHASE_PRICE,
                    "quantity": 1,
                    "product_id": product_id,
                    "episode_id": episode_id,
                }
            )

        if order_items:
            await create_product_order_with_items(
                db=db,
                user_id=user_id,
                pay_type="cash",
                device_type="web",
                created_id=settings.DB_DML_DEFAULT_ID,
                items=order_items,
            )

        # 통계 로그 추가
        await statistics_service.insert_site_statistics_log(
            db=db, type="active", user_id=user_id
        )

        return {
            "result": True,
            "data": {
                "purchasedCount": len(episodes_to_purchase),
                "totalCashUsed": total_cash_needed,
                "skippedFreeCount": skipped_free_count,
                "skippedOwnedCount": skipped_owned_count,
            },
        }
