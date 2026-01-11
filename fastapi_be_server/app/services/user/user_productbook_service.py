import logging
from app.services.common import comm_service
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.exceptions import CustomResponseException
from app.const import ErrorMessages
from app.utils.query import build_insert_query, build_update_query
from app.utils.response import build_list_response, build_detail_response
import app.schemas.user_productbook as user_productbook_schema
import app.services.common.statistics_service as statistics_service

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


async def user_productbook_detail_by_id(id, db: AsyncSession):
    """
    사용자 대여권(user_productbook) 상세 조회
    """
    query = text("""
                 SELECT * FROM tb_user_productbook WHERE id = :id
                 """)
    result = await db.execute(query, {"id": id})
    row = result.mappings().one_or_none()
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
                        delete from tb_user_productbook where id = :id
                    """)

    await db.execute(query, {"id": id})

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

    # 대여권 조회 (product_id, episode_id, use_yn, own_type, ticket_type 포함)
    productbook_query = text("""
                              SELECT user_id, product_id, episode_id, use_yn, own_type, ticket_type
                              FROM tb_user_productbook
                              WHERE id = :id
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

    # 대여권 사용 가능 여부 체크
    ticket_product_id = productbook_row["product_id"]
    ticket_episode_id = productbook_row["episode_id"]

    can_use = False

    if ticket_product_id is None:
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
        "product_id = :product_id",
        "episode_id = :episode_id",
        "rental_expired_date = DATE_ADD(NOW(), INTERVAL 3 DAY)",
    ]

    db_execute_params = {
        "updated_id": -1,
        "updated_date": datetime.now(),
        "id": id,
        "product_id": target_product_id,
        "episode_id": episode_id,
    }

    update_filed_query = ",".join(update_filed_query_list)

    query = text(f"""
                        update tb_user_productbook
                        set {update_filed_query}
                        where id = :id
                    """)

    await db.execute(query, db_execute_params)

    # 정산용 일별 판매 데이터 기록 (유료 대여권만)
    ticket_type = productbook_row["ticket_type"]

    if ticket_type == "paid":
        item_name = f"{product_title} - {episode_no}화"

        sales_query = text("""
            INSERT INTO tb_batch_daily_sales_summary
            (item_type, item_name, item_price, quantity, device_type, user_id, product_id, episode_id, order_date, pay_type, created_date)
            VALUES ('paid', :item_name, 0, 1, 'web', :user_id, :product_id, :episode_id, NOW(), 'ticket', NOW())
        """)
        await db.execute(
            sales_query,
            {
                "item_name": item_name,
                "user_id": user_id,
                "product_id": target_product_id,
                "episode_id": episode_id,
            },
        )

    return {"result": True}


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

    # tb_user_productbook에서 사용 가능한 대여권 조회
    # episode_id가 있으면 특정 에피소드, 없으면 해당 작품 전체의 대여권 조회
    if episode_id is not None:
        productbook_query = text("""
                                 SELECT upb.*,
                                        COALESCE(
                                            ap.type,
                                            dp.type,
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
                                 WHERE upb.user_id = :user_id
                                 AND (
                                     upb.episode_id = :episode_id
                                     or
                                     (upb.product_id = :product_id and upb.episode_id is null)
                                     or
                                     upb.product_id is null
                                 )
                                 AND upb.own_type = 'rental'
                                 AND upb.use_yn = 'N'
                                 AND (upb.rental_expired_date IS NULL OR upb.rental_expired_date > NOW())
                                 ORDER BY FIELD(
                                     COALESCE(
                                         ap.type,
                                         dp.type,
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
                                 WHERE upb.user_id = :user_id
                                 AND (
                                     upb.episode_id in (select episode_id from tb_product_episode where product_id = :product_id)
                                     or
                                     (upb.product_id = :product_id and upb.episode_id is null)
                                     or
                                     upb.product_id is null
                                 )
                                 AND upb.own_type = 'rental'
                                 AND upb.use_yn = 'N'
                                 AND (upb.rental_expired_date IS NULL OR upb.rental_expired_date > NOW())
                                 ORDER BY FIELD(
                                     COALESCE(
                                         ap.type,
                                         dp.type,
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

    res_body = dict()
    res_body["data"] = data_list
    res_body["count_by_type"] = count_by_type

    return res_body
