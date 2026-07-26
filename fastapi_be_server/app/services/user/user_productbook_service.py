import logging
from app.services.common import comm_service
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.rdb import likenovel_db_engine
from app.exceptions import CustomResponseException
from app.const import ErrorMessages, settings
from app.utils.query import build_insert_query, build_update_query
from app.utils.response import build_list_response, build_detail_response
import app.schemas.user_productbook as user_productbook_schema
import app.services.common.statistics_service as statistics_service
from app.services.order.product_order_service import create_product_order_with_items

logger = logging.getLogger("user_productbook_app")  # 커스텀 로거 생성

"""
user_productbook 사용자 대여권 개별 서비스 함수 모음
"""


async def user_productbook_list(kc_user_id: str, db: AsyncSession):
    # kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # 해당 user_id의 대여권만 조회
    query = text("""
                 SELECT * FROM tb_user_productbook
                 WHERE user_id = :user_id AND own_type = 'rental'
                 ORDER BY updated_date DESC
                 """)
    result = await db.execute(query, {"user_id": user_id})
    rows = result.mappings().all()
    return build_list_response(rows)


async def user_productbook_detail_by_id(
    id: int, kc_user_id: str, db: AsyncSession
):
    """
    사용자 대여권(user_productbook) 상세 조회
    """
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    query = text("""
                 SELECT * FROM tb_user_productbook
                 WHERE id = :id AND user_id = :user_id
                 """)
    result = await db.execute(query, {"id": id, "user_id": user_id})
    row = result.mappings().one_or_none()
    if row is None:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_PRODUCTBOOK,
        )
    return build_detail_response(row)


async def post_user_productbook(
    req_body: user_productbook_schema.PostUserProductbookReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    if req_body is not None:
        logger.info(f"post_user_productbook: {req_body}")

    # kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    columns, values, params = build_insert_query(
        req_body,
        required_fields=["ticket_type", "own_type", "user_id", "profile_id"],
        optional_fields=[
            "product_id",
            "episode_id",
            "acquisition_type",
            "acquisition_id",
            "rental_expired_date",
            "use_yn",
        ],
        field_defaults={"use_yn": "N"},
    )

    query = text(
        f"INSERT INTO tb_user_productbook (id, {columns}, created_id, created_date) VALUES (default, {values}, :created_id, :created_date)"
    )

    await db.execute(query, params)

    await statistics_service.insert_site_statistics_log(
        db=db, type="active", user_id=user_id
    )

    return {"result": req_body}


async def put_user_productbook(
    id: int,
    req_body: user_productbook_schema.PutUserProductbookReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    if req_body is not None:
        logger.info(f"put_user_productbook: {req_body}")

    # kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    set_clause, params = build_update_query(
        req_body,
        allowed_fields=[
            "ticket_type",
            "own_type",
            "user_id",
            "profile_id",
            "product_id",
            "episode_id",
            "acquisition_type",
            "acquisition_id",
            "rental_expired_date",
            "use_yn",
        ],
    )
    params["id"] = id

    query = text(f"UPDATE tb_user_productbook SET {set_clause} WHERE id = :id")

    await db.execute(query, params)

    return {"result": req_body}


async def delete_user_productbook(id: int, kc_user_id: str, db: AsyncSession):
    # kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    query = text("""
                 SELECT upb.id,
                        upb.user_id,
                        ap.type AS applied_promotion_type,
                        ug.promotion_type AS gift_promotion_type
                   FROM tb_user_productbook upb
                   LEFT JOIN tb_applied_promotion ap
                     ON upb.acquisition_type = 'applied_promotion'
                    AND upb.acquisition_id = ap.id
                   LEFT JOIN tb_user_giftbook ug
                     ON upb.acquisition_type = 'gift'
                    AND upb.acquisition_id = ug.id
                  WHERE upb.id = :id
                  FOR UPDATE
                 """)
    result = await db.execute(query, {"id": id})
    productbook = result.mappings().one_or_none()
    if productbook is None:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_PRODUCTBOOK,
        )
    if productbook["user_id"] != user_id:
        raise CustomResponseException(
            status_code=status.HTTP_403_FORBIDDEN,
            message=ErrorMessages.FORBIDDEN_NOT_OWNER_OF_PRODUCTBOOK,
        )
    if (
        productbook["applied_promotion_type"] == "waiting-for-free"
        or productbook["gift_promotion_type"] == "waiting-for-free"
    ):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="기다리면 무료 대여권은 삭제할 수 없습니다.",
        )

    query = text("""
                 DELETE upb
                   FROM tb_user_productbook upb
                  WHERE upb.id = :id
                    AND upb.user_id = :user_id
                 """)
    await db.execute(query, {"id": id, "user_id": user_id})

    return {"result": True}


async def use_user_productbook(
    id: int, episode_id: int, kc_user_id: str, db: AsyncSession
):
    """
    사용자 대여권(user_productbook) 사용

    Args:
        id: 대여권 ID
        episode_id: 사용할 에피소드 ID
        kc_user_id: Keycloak user ID
        db: 데이터베이스 세션
    """

    # kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # 사용할 에피소드 정보 조회 (product_id, episode_no 필요)
    episode_query = text("""
                         SELECT e.product_id, e.episode_no, p.title as product_title
                         FROM tb_product_episode e
                         INNER JOIN tb_product p ON e.product_id = p.product_id
                         WHERE e.episode_id = :episode_id
                         AND e.use_yn = 'Y'
                         """)
    episode_result = await db.execute(episode_query, {"episode_id": episode_id})
    episode_row = episode_result.mappings().one_or_none()

    if not episode_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_EPISODE,
        )

    target_product_id = episode_row["product_id"]
    episode_no = episode_row["episode_no"]
    product_title = episode_row["product_title"]

    # 대여권과 기다무 원천을 함께 잠가 사용 가능 상태를 확인한다.
    productbook_query = text("""
                              SELECT upb.user_id,
                                     upb.product_id,
                                     upb.episode_id,
                                     upb.use_yn,
                                     upb.own_type,
                                     upb.ticket_type,
                                     upb.rental_expired_date,
                                     upb.acquisition_type,
                                     ap.type AS applied_promotion_type,
                                     ug.promotion_type AS gift_promotion_type,
                                     CASE
                                         WHEN ap.type = 'waiting-for-free'
                                          AND ap.status = 'ing'
                                          AND ap.start_date <= NOW()
                                          AND (ap.end_date IS NULL OR DATE(ap.end_date) >= CURDATE())
                                         THEN 'Y' ELSE 'N'
                                     END AS applied_wff_active_yn,
                                     CASE
                                         WHEN ug.promotion_type = 'waiting-for-free'
                                          AND ug.acquisition_type = 'applied_promotion'
                                          AND ap_from_gift.type = 'waiting-for-free'
                                          AND ap_from_gift.status = 'ing'
                                          AND ap_from_gift.start_date <= NOW()
                                          AND (ap_from_gift.end_date IS NULL OR DATE(ap_from_gift.end_date) >= CURDATE())
                                         THEN 'Y' ELSE 'N'
                                     END AS gift_wff_active_yn
                                FROM tb_user_productbook upb
                                LEFT JOIN tb_applied_promotion ap
                                  ON upb.acquisition_type = 'applied_promotion'
                                 AND upb.acquisition_id = ap.id
                                LEFT JOIN tb_user_giftbook ug
                                  ON upb.acquisition_type = 'gift'
                                 AND upb.acquisition_id = ug.id
                                LEFT JOIN tb_applied_promotion ap_from_gift
                                  ON ug.acquisition_type = 'applied_promotion'
                                 AND ug.acquisition_id = ap_from_gift.id
                               WHERE upb.id = :id
                               FOR UPDATE
                              """)
    productbook_result = await db.execute(productbook_query, {"id": id})
    productbook_row = productbook_result.mappings().one_or_none()

    if not productbook_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_PRODUCTBOOK,
        )

    # 대여권 소유자와 현재 사용자 일치 여부 확인
    if productbook_row["user_id"] != user_id:
        raise CustomResponseException(
            status_code=status.HTTP_403_FORBIDDEN,
            message=ErrorMessages.FORBIDDEN_NOT_OWNER_OF_PRODUCTBOOK,
        )

    # own_type이 'rental'인 경우만 사용 가능 (대여권만 사용, 소장은 사용 개념 없음)
    if productbook_row["own_type"] != "rental":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.OWNED_PRODUCT_CANNOT_USE,
        )

    # use_yn이 'N'일 때만 사용 가능
    if productbook_row["use_yn"] != "N":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_USED_PRODUCTBOOK,
        )

    rental_expired_date = productbook_row["rental_expired_date"]
    if rental_expired_date is not None and rental_expired_date <= datetime.now():
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.EXPIRED_PRODUCTBOOK,
        )

    is_applied_wff = (
        productbook_row["acquisition_type"] == "applied_promotion"
        and productbook_row["applied_promotion_type"] == "waiting-for-free"
    )
    is_gift_wff = (
        productbook_row["acquisition_type"] == "gift"
        and productbook_row["gift_promotion_type"] == "waiting-for-free"
    )
    if (
        (is_applied_wff and productbook_row["applied_wff_active_yn"] != "Y")
        or (is_gift_wff and productbook_row["gift_wff_active_yn"] != "Y")
    ):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.EXPIRED_GIFT_VALIDITY,
        )

    # 대여권 사용 가능 여부 체크
    ticket_product_id = productbook_row["product_id"]
    ticket_episode_id = productbook_row["episode_id"]

    can_use = False

    if ticket_product_id is None:
        if is_applied_wff or is_gift_wff:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.PRODUCTBOOK_NOT_APPLICABLE_FOR_EPISODE,
            )
        # product_id가 null이면 전체 작품/에피소드에 사용 가능
        can_use = True
    elif ticket_product_id == target_product_id:
        # product_id가 일치하는 경우
        if ticket_episode_id is None:
            # episode_id가 null이면 해당 작품의 모든 에피소드에 사용 가능
            can_use = True
        elif ticket_episode_id == episode_id:
            # episode_id가 일치하면 해당 에피소드에만 사용 가능
            can_use = True

    if not can_use:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.PRODUCTBOOK_NOT_APPLICABLE_FOR_EPISODE,
        )

    # 사용 처리: use_yn = 'Y', product_id와 episode_id에 실제 사용한 작품/에피소드 저장
    # 대여권의 경우 rental_expired_date를 현재 시간 + 3일로 설정
    update_filed_query_list = [
        "updated_id = :updated_id",
        "updated_date = :updated_date",
        "use_yn = 'Y'",
        "use_date = NOW()",
        "product_id = :product_id",
        "episode_id = :episode_id",
        "rental_expired_date = DATE_ADD(NOW(), INTERVAL 3 DAY)",
    ]

    db_execute_params = {
        "updated_id": -1,
        "updated_date": datetime.now(),
        "id": id,
        "user_id": user_id,
        "product_id": target_product_id,
        "episode_id": episode_id,
    }

    update_filed_query = ",".join(update_filed_query_list)

    query = text(f"""
                        update tb_user_productbook
                        set {update_filed_query}
                        where id = :id
                        and user_id = :user_id
                        and own_type = 'rental'
                        and use_yn = 'N'
                        and (rental_expired_date IS NULL OR rental_expired_date > NOW())
                    """)

    update_result = await db.execute(query, db_execute_params)
    if update_result.rowcount != 1:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_USED_PRODUCTBOOK,
        )

    # 정산용 일별 판매 데이터 기록 (유료 대여권만)
    ticket_type = productbook_row["ticket_type"]

    if ticket_type == "paid":
        item_name = f"{product_title} - {episode_no}화"

        await create_product_order_with_items(
            db=db,
            user_id=user_id,
            pay_type="ticket_paid",
            device_type="web",
            created_id=settings.DB_DML_DEFAULT_ID,
            items=[
                {
                    "item_name": item_name,
                    "item_price": 0,
                    "quantity": 1,
                    "product_id": target_product_id,
                    "episode_id": episode_id,
                }
            ],
        )

    return {"result": True}


async def _issue_due_waiting_for_free_ticket(user_id: int, product_id: int):
    lock_name = "lk_summary_hourly_batch"

    async with likenovel_db_engine.connect() as conn:
        lock_result = await conn.execute(
            text("SELECT GET_LOCK(:lock_name, 5) AS lock_acquired"),
            {"lock_name": lock_name},
        )
        lock_row = lock_result.mappings().one_or_none()
        if not lock_row or lock_row["lock_acquired"] != 1:
            logger.warning(
                "Skipped waiting-for-free recharge; hourly batch lock is busy "
                f"(user_id={user_id}, product_id={product_id})"
            )
            return "lock_busy"

        try:
            query = text("""
                INSERT INTO tb_user_productbook (
                    user_id, profile_id, product_id, episode_id, own_type,
                    ticket_type, acquisition_type, acquisition_id, use_yn,
                    created_id, created_date, updated_id, updated_date
                )
                SELECT seed.user_id,
                       seed.profile_id,
                       seed.product_id,
                       NULL,
                       'rental',
                       'waiting-for-free' as ticket_type,
                       'applied_promotion',
                       seed.promotion_id,
                       'N',
                       0,
                       NOW(),
                       0,
                       NOW()
                  FROM (
                      SELECT source.user_id,
                             source.profile_id,
                             source.product_id,
                             source.promotion_id,
                             MAX(source.use_date) AS last_use_date
                        FROM (
                            SELECT upb.user_id,
                                   upb.profile_id,
                                   upb.product_id,
                                   upb.acquisition_id AS promotion_id,
                                   upb.use_date
                              FROM tb_user_productbook upb
                              JOIN tb_applied_promotion ap
                                ON upb.acquisition_type = 'applied_promotion'
                               AND upb.acquisition_id = ap.id
                             WHERE upb.user_id = :user_id
                               AND upb.product_id = :product_id
                               AND upb.use_yn = 'Y'
                               AND upb.use_date IS NOT NULL
                               AND ap.type = 'waiting-for-free'
                               AND ap.status = 'ing'
                               AND ap.start_date <= NOW()
                               AND (ap.end_date IS NULL OR DATE(ap.end_date) >= CURDATE())
                            UNION ALL
                            SELECT upb.user_id,
                                   upb.profile_id,
                                   upb.product_id,
                                   ug.acquisition_id AS promotion_id,
                                   upb.use_date
                              FROM tb_user_productbook upb
                              JOIN tb_user_giftbook ug
                                ON upb.acquisition_type = 'gift'
                               AND upb.acquisition_id = ug.id
                              JOIN tb_applied_promotion ap
                                ON ug.acquisition_type = 'applied_promotion'
                               AND ug.acquisition_id = ap.id
                             WHERE upb.user_id = :user_id
                               AND upb.product_id = :product_id
                               AND upb.use_yn = 'Y'
                               AND upb.use_date IS NOT NULL
                               AND ug.promotion_type = 'waiting-for-free'
                               AND ug.acquisition_type = 'applied_promotion'
                               AND ap.type = 'waiting-for-free'
                               AND ap.status = 'ing'
                               AND ap.start_date <= NOW()
                               AND (ap.end_date IS NULL OR DATE(ap.end_date) >= CURDATE())
                        ) source
                       GROUP BY source.user_id,
                                source.profile_id,
                                source.product_id,
                                source.promotion_id
                  ) seed
                  JOIN tb_applied_promotion ap ON ap.id = seed.promotion_id
                 WHERE timestampdiff(hour, seed.last_use_date, now()) >= 24
                   AND ap.type = 'waiting-for-free'
                   AND ap.status = 'ing'
                   AND ap.start_date <= NOW()
                   AND (ap.end_date IS NULL OR DATE(ap.end_date) >= CURDATE())
                   AND NOT EXISTS (
                       SELECT 1
                         FROM tb_user_productbook upb2
                         LEFT JOIN tb_user_giftbook ug2
                           ON upb2.acquisition_type = 'gift'
                          AND upb2.acquisition_id = ug2.id
                        WHERE upb2.user_id = seed.user_id
                          AND upb2.profile_id = seed.profile_id
                          AND upb2.product_id = seed.product_id
                          AND upb2.use_yn = 'N'
                          AND (
                              (upb2.acquisition_type = 'applied_promotion' AND upb2.acquisition_id = seed.promotion_id)
                              OR
                              (upb2.acquisition_type = 'gift' AND ug2.promotion_type = 'waiting-for-free'
                               AND ug2.acquisition_type = 'applied_promotion' AND ug2.acquisition_id = seed.promotion_id)
                          )
                   )
                   AND NOT EXISTS (
                       SELECT 1
                         FROM tb_user_productbook upb3
                         LEFT JOIN tb_user_giftbook ug3
                           ON upb3.acquisition_type = 'gift'
                          AND upb3.acquisition_id = ug3.id
                        WHERE upb3.user_id = seed.user_id
                          AND upb3.profile_id = seed.profile_id
                          AND upb3.product_id = seed.product_id
                          AND upb3.created_date > seed.last_use_date
                          AND (
                              (upb3.acquisition_type = 'applied_promotion' AND upb3.acquisition_id = seed.promotion_id)
                              OR
                              (upb3.acquisition_type = 'gift' AND ug3.promotion_type = 'waiting-for-free'
                               AND ug3.acquisition_type = 'applied_promotion' AND ug3.acquisition_id = seed.promotion_id)
                          )
                   )
            """)
            await conn.execute(query, {"user_id": user_id, "product_id": product_id})
            await conn.commit()
            return "checked"
        except Exception:
            await conn.rollback()
            raise
        finally:
            await conn.execute(
                text("SELECT RELEASE_LOCK(:lock_name)"),
                {"lock_name": lock_name},
            )


async def get_available_rental_tickets(
    kc_user_id: str,
    db: AsyncSession,
    episode_id: int | None = None,
    product_id: int | None = None,
):
    """
    특정 에피소드 또는 작품에서 사용 가능한 대여권 리스트 조회
    """

    # episode_id와 product_id가 모두 없으면 에러
    if episode_id is None and product_id is None:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.REQUIRED_EPISODE_ID_OR_PRODUCT_ID,
        )

    # kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # episode_id가 주어진 경우, 에피소드 정보 조회하여 product_id 획득
    if episode_id is not None:
        episode_query = text("""
                             SELECT product_id
                             FROM tb_product_episode
                             WHERE episode_id = :episode_id
                             AND use_yn = 'Y'
                             """)
        episode_result = await db.execute(episode_query, {"episode_id": episode_id})
        episode_row = episode_result.mappings().one_or_none()

        if not episode_row:
            raise CustomResponseException(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ErrorMessages.NOT_FOUND_EPISODE,
            )

        product_id = episode_row["product_id"]

    # product_id가 없으면 에러 (episode_id로도 조회 안됨)
    if product_id is None:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_PRODUCT_ID,
        )

    active_wff_query = text("""
                            SELECT 1
                              FROM tb_applied_promotion
                             WHERE product_id = :product_id
                               AND type = 'waiting-for-free'
                               AND status = 'ing'
                               AND start_date <= NOW()
                               AND (end_date IS NULL OR DATE(end_date) >= CURDATE())
                             LIMIT 1
                            """)
    active_wff_result = await db.execute(
        active_wff_query, {"product_id": product_id}
    )
    wff_recharge_status = "not_applicable"
    if active_wff_result.scalar_one_or_none() is not None:
        wff_recharge_status = await _issue_due_waiting_for_free_ticket(
            user_id=user_id,
            product_id=product_id,
        )
        # 위 발급은 별도 커넥션에서 commit되므로 현재 read snapshot을 갱신한다.
        await db.rollback()

    # tb_user_productbook에서 사용 가능한 대여권 조회
    # episode_id가 있으면 특정 에피소드, 없으면 해당 작품 전체의 대여권 조회
    if episode_id is not None:
        productbook_query = text("""
                                 SELECT upb.*,
                                        COALESCE(
                                            ap.type,
                                            dp.type,
                                            ug.promotion_type,
                                            CASE upb.acquisition_type
                                                WHEN 'event' THEN 'event'
                                                WHEN 'gift' THEN 'gift'
                                                WHEN 'quest' THEN 'quest'
                                                ELSE NULL
                                            END
                                        ) as type
                                 FROM tb_user_productbook upb
                                 LEFT JOIN tb_applied_promotion ap
                                    ON upb.acquisition_type = 'applied_promotion'
                                    AND upb.acquisition_id = ap.id
                                 LEFT JOIN tb_direct_promotion dp
                                    ON upb.acquisition_type = 'direct_promotion'
                                    AND upb.acquisition_id = dp.id
                                 LEFT JOIN tb_user_giftbook ug
                                    ON upb.acquisition_type = 'gift'
                                    AND upb.acquisition_id = ug.id
                                 LEFT JOIN tb_applied_promotion ap_from_gift
                                    ON ug.acquisition_type = 'applied_promotion'
                                    AND ug.acquisition_id = ap_from_gift.id
                                    AND ap_from_gift.type = 'waiting-for-free'
                                    AND ap_from_gift.status = 'ing'
                                    AND ap_from_gift.start_date <= NOW()
                                    AND (ap_from_gift.end_date IS NULL OR DATE(ap_from_gift.end_date) >= CURDATE())
                                 WHERE upb.user_id = :user_id
                                 AND (
                                     upb.episode_id = :episode_id
                                     or
                                     (upb.episode_id is null and (upb.product_id = :product_id or upb.product_id is null))
                                 )
                                 AND upb.own_type = 'rental'
                                 AND upb.use_yn = 'N'
                                 AND (upb.rental_expired_date IS NULL OR upb.rental_expired_date > NOW())
                                 AND (
                                     ap.type IS NULL OR ap.type <> 'waiting-for-free'
                                     OR (ap.status = 'ing' AND ap.start_date <= NOW() AND (ap.end_date IS NULL OR DATE(ap.end_date) >= CURDATE()))
                                 )
                                 AND (
                                     ug.promotion_type IS NULL OR ug.promotion_type <> 'waiting-for-free'
                                     OR ap_from_gift.id IS NOT NULL
                                 )
                                 AND (
                                     (COALESCE(ap.type, ug.promotion_type) = 'waiting-for-free' AND upb.product_id = :product_id)
                                     OR COALESCE(ap.type, ug.promotion_type, '') <> 'waiting-for-free'
                                 )
                                 ORDER BY FIELD(
                                     COALESCE(
                                         ap.type,
                                         dp.type,
                                         ug.promotion_type,
                                         CASE upb.acquisition_type
                                            WHEN 'event' THEN 'event'
                                            WHEN 'gift' THEN 'gift'
                                            WHEN 'quest' THEN 'quest'
                                            ELSE NULL
                                        END
                                    ),
                                    '6-9-path',
                                    'reader-of-prev',
                                    'free-for-first',
                                    'waiting-for-free',
                                    'event'
                                ), COALESCE(upb.rental_expired_date, '9999-12-31') ASC, upb.updated_date DESC
                                 """)
        productbook_result = await db.execute(
            productbook_query,
            {"user_id": user_id, "episode_id": episode_id, "product_id": product_id},
        )
    else:
        productbook_query = text("""
                                 SELECT upb.*,
                                        COALESCE(
                                            ap.type,
                                            dp.type,
                                            ug.promotion_type,
                                            CASE upb.acquisition_type
                                                WHEN 'event' THEN 'event'
                                                WHEN 'gift' THEN 'gift'
                                                WHEN 'quest' THEN 'quest'
                                                ELSE NULL
                                            END
                                        ) as type
                                 FROM tb_user_productbook upb
                                 LEFT JOIN tb_applied_promotion ap
                                    ON upb.acquisition_type = 'applied_promotion'
                                    AND upb.acquisition_id = ap.id
                                 LEFT JOIN tb_direct_promotion dp
                                    ON upb.acquisition_type = 'direct_promotion'
                                    AND upb.acquisition_id = dp.id
                                 LEFT JOIN tb_user_giftbook ug
                                    ON upb.acquisition_type = 'gift'
                                    AND upb.acquisition_id = ug.id
                                 LEFT JOIN tb_applied_promotion ap_from_gift
                                    ON ug.acquisition_type = 'applied_promotion'
                                    AND ug.acquisition_id = ap_from_gift.id
                                    AND ap_from_gift.type = 'waiting-for-free'
                                    AND ap_from_gift.status = 'ing'
                                    AND ap_from_gift.start_date <= NOW()
                                    AND (ap_from_gift.end_date IS NULL OR DATE(ap_from_gift.end_date) >= CURDATE())
                                 WHERE upb.user_id = :user_id
                                 AND (
                                     upb.episode_id in (select episode_id from tb_product_episode where product_id = :product_id)
                                     or
                                     (upb.episode_id is null and (upb.product_id = :product_id or upb.product_id is null))
                                 )
                                 AND upb.own_type = 'rental'
                                 AND upb.use_yn = 'N'
                                 AND (upb.rental_expired_date IS NULL OR upb.rental_expired_date > NOW())
                                 AND (
                                     ap.type IS NULL OR ap.type <> 'waiting-for-free'
                                     OR (ap.status = 'ing' AND ap.start_date <= NOW() AND (ap.end_date IS NULL OR DATE(ap.end_date) >= CURDATE()))
                                 )
                                 AND (
                                     ug.promotion_type IS NULL OR ug.promotion_type <> 'waiting-for-free'
                                     OR ap_from_gift.id IS NOT NULL
                                 )
                                 AND (
                                     (COALESCE(ap.type, ug.promotion_type) = 'waiting-for-free' AND upb.product_id = :product_id)
                                     OR COALESCE(ap.type, ug.promotion_type, '') <> 'waiting-for-free'
                                 )
                                 ORDER BY FIELD(
                                     COALESCE(
                                         ap.type,
                                         dp.type,
                                         ug.promotion_type,
                                         CASE upb.acquisition_type
                                            WHEN 'event' THEN 'event'
                                            WHEN 'gift' THEN 'gift'
                                            WHEN 'quest' THEN 'quest'
                                            ELSE NULL
                                        END
                                    ),
                                    '6-9-path',
                                    'reader-of-prev',
                                    'free-for-first',
                                    'waiting-for-free',
                                    'event'
                                ), COALESCE(upb.rental_expired_date, '9999-12-31') ASC, upb.updated_date DESC
                                 """)
        productbook_result = await db.execute(
            productbook_query, {"user_id": user_id, "product_id": product_id}
        )

    productbook_rows = productbook_result.mappings().all()

    # 데이터 리스트와 타입별 카운트 준비
    data_list = []
    count_by_type = {}

    for row in productbook_rows:
        row_dict = dict(row)
        data_list.append(row_dict)

        # type 필드로 카운트
        type_value = row_dict.get("type")
        if type_value:
            type_value = type_value.replace("-", "_")
            count_by_type[type_value] = count_by_type.get(type_value, 0) + 1

    # 기다무 타이머: 미사용 WFF 티켓이 0장일 때, 마지막 사용 시점 + 24h를 계산
    wff_next_charge_at = None
    wff_next_charge_at_ms = None
    if count_by_type.get("waiting_for_free", 0) == 0 and product_id is not None:
        wff_timer_query = text("""
            SELECT DATE_ADD(MAX(upb.use_date), INTERVAL 24 HOUR) as next_charge_at,
                   CAST(UNIX_TIMESTAMP(DATE_ADD(MAX(upb.use_date), INTERVAL 24 HOUR)) * 1000 AS UNSIGNED) as next_charge_at_ms
            FROM tb_user_productbook upb
            LEFT JOIN tb_applied_promotion ap
              ON upb.acquisition_type = 'applied_promotion' AND upb.acquisition_id = ap.id
            LEFT JOIN tb_user_giftbook ug
              ON upb.acquisition_type = 'gift' AND upb.acquisition_id = ug.id
            LEFT JOIN tb_applied_promotion ap_from_gift
              ON ug.acquisition_type = 'applied_promotion'
             AND ug.acquisition_id = ap_from_gift.id
             AND ap_from_gift.type = 'waiting-for-free'
             AND ap_from_gift.status = 'ing'
             AND ap_from_gift.start_date <= NOW()
             AND (ap_from_gift.end_date IS NULL OR DATE(ap_from_gift.end_date) >= CURDATE())
            WHERE upb.user_id = :user_id
              AND (
                (ap.type = 'waiting-for-free' AND ap.status = 'ing' AND ap.start_date <= NOW() AND (ap.end_date IS NULL OR DATE(ap.end_date) >= CURDATE()))
                OR
                (ug.promotion_type = 'waiting-for-free' AND ap_from_gift.id IS NOT NULL)
              )
              AND upb.use_yn = 'Y'
              AND upb.use_date IS NOT NULL
              AND upb.product_id = :product_id
              AND timestampdiff(hour, upb.use_date, now()) < 24
        """)
        wff_result = await db.execute(
            wff_timer_query, {"user_id": user_id, "product_id": product_id}
        )
        wff_row = wff_result.mappings().one_or_none()
        if wff_row and wff_row["next_charge_at"]:
            wff_next_charge_at = wff_row["next_charge_at"].isoformat()
            wff_next_charge_at_ms = int(wff_row["next_charge_at_ms"])

    res_body = dict()
    res_body["data"] = data_list
    res_body["count_by_type"] = count_by_type
    res_body["wff_next_charge_at"] = wff_next_charge_at
    res_body["wff_next_charge_at_ms"] = wff_next_charge_at_ms
    res_body["wff_recharge_pending"] = wff_recharge_status == "lock_busy"

    return res_body
