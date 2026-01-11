import logging
from app.services.common import comm_service
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.const import settings, ErrorMessages, LOGGER_TYPE
from app.exceptions import CustomResponseException
from app.utils.query import (
    get_file_path_sub_query,
    get_badge_image_sub_query,
)
from app.utils.response import build_list_response
from app.utils.common import handle_exceptions
import app.schemas.user as user_schema
import app.schemas.product as product_schema

from datetime import datetime, timedelta

from app.config.log_config import service_error_logger

# Import from product_service for helper functions
from app.services.product.product_service import (
    convert_product_data,
    get_select_fields_and_joins_for_product,
)
import app.schemas.user_giftbook as user_giftbook_schema
import app.services.user.user_giftbook_service as user_giftbook_service

logger = logging.getLogger(__name__)
error_logger = service_error_logger(LOGGER_TYPE.LOGGER_INSTANCE_NAME_FOR_SERVICE_ERROR)

"""
author(작가) 도메인 개별 서비스 함수 모음
"""


async def get_products(
    kc_user_id: str,
    sort_by: str = "recent_update",
    db: AsyncSession = None,
):
    """
    작가의 작품 목록

    Args:
        kc_user_id: Keycloak user ID
        sort_by: 정렬 기준 (recent_update: 최근 업데이트 순, title: 가나다 순)
        db: 데이터베이스 세션
    """
    try:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 정렬 조건 설정
        if sort_by == "title":
            order_by_clause = "ORDER BY p.title ASC"
        else:  # recent_update (기본값)
            order_by_clause = "ORDER BY p.last_episode_date DESC"

        # 필터 옵션 설정
        query_parts = get_select_fields_and_joins_for_product(
            user_id=user_id, join_rank=False
        )
        query = text(f"""
            SELECT {query_parts["select_fields"]}
            FROM tb_product p
            {query_parts["joins"]}
            WHERE p.user_id = :user_id
            {order_by_clause}
        """)
        result = await db.execute(query, {"user_id": user_id})
        rows = result.mappings().all()

        res_body = dict()
        res_body["data"] = {"products": [convert_product_data(row) for row in rows]}

        return res_body

    except SQLAlchemyError as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )


async def get_products_promotions(
    kc_user_id: str,
    db: AsyncSession,
):
    """
    작가의 작품별 프로모션 데이터
    """
    try:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 필터 옵션 설정
        query_parts = get_select_fields_and_joins_for_product(
            user_id=user_id, join_rank=False
        )
        query = text(f"""
            SELECT {query_parts["select_fields"]}
            FROM tb_product p
            {query_parts["joins"]}
            WHERE p.user_id = :user_id
        """)
        result = await db.execute(query, {"user_id": user_id})
        rows = result.mappings().all()

        res_body = dict()
        res_body["data"] = {"products": [convert_product_data(row) for row in rows]}

        product_ids = [row["productId"] for row in res_body["data"]["products"]]

        # 작품이 없는 경우 빈 데이터 반환
        if not product_ids:
            return res_body

        query = text(f"""
            select *
              from tb_direct_promotion
             where product_id in ({", ".join(map(str, product_ids))})
        """)
        result = await db.execute(query, {})
        direct_promotion_rows = result.mappings().all()
        direct_promotions_by_product = {}
        for dp_row in direct_promotion_rows:
            product_id = dp_row["product_id"]
            if product_id not in direct_promotions_by_product:
                direct_promotions_by_product[product_id] = []
            dp_dict = dict(dp_row)
            direct_promotions_by_product[product_id].append(dp_dict)

        query = text(f"""
            select this_week.*,
                   case
                     when rejected.created_date is not null then
                       concat(DATE_FORMAT(DATE_ADD(rejected.created_date, INTERVAL 6 MONTH), '%Y.%m.%d'), ' 신청 가능')
                     else ''
                   end as can_apply_text,
                   20 - IFNULL(ing_count.cnt, 0) as remaining_slots,
                   case
                     when rejected.created_date is null then true
                     when DATE_ADD(rejected.created_date, INTERVAL 6 MONTH) <= CURDATE() then true
                     else false
                   end as can_apply,
                   case
                     when this_week.status = 'apply' then true
                     else false
                   end as can_cancel
              from (
                select *
                  from tb_applied_promotion
                 where product_id in ({", ".join(map(str, product_ids))})
                   and status not in ('end', 'cancel', 'deny')
                   and created_date >= DATE_SUB(CURDATE(), INTERVAL WEEKDAY(CURDATE()) DAY)
                   and created_date < DATE_ADD(DATE_SUB(CURDATE(), INTERVAL WEEKDAY(CURDATE()) DAY), INTERVAL 7 DAY)
              ) this_week
              left join (
                select product_id, created_date
                  from tb_applied_promotion
                 where product_id in ({", ".join(map(str, product_ids))})
                   and status = 'deny'
                 order by created_date desc
                 limit 1
              ) rejected on this_week.product_id = rejected.product_id
              left join (
                select product_id, count(*) as cnt
                  from tb_applied_promotion
                 where product_id in ({", ".join(map(str, product_ids))})
                   and status = 'ing'
                   and created_date >= DATE_SUB(CURDATE(), INTERVAL WEEKDAY(CURDATE()) DAY)
                   and created_date < DATE_ADD(DATE_SUB(CURDATE(), INTERVAL WEEKDAY(CURDATE()) DAY), INTERVAL 7 DAY)
                 group by product_id
              ) ing_count on this_week.product_id = ing_count.product_id
        """)
        result = await db.execute(query, {})
        applied_promotion_rows = result.mappings().all()
        applied_promotions_by_product = {}
        for ap_row in applied_promotion_rows:
            product_id = ap_row["product_id"]
            if product_id not in applied_promotions_by_product:
                applied_promotions_by_product[product_id] = []
            applied_promotions_by_product[product_id].append(dict(ap_row))

        for product in res_body["data"]["products"]:
            product_id = product["productId"]
            product["directPromotions"] = direct_promotions_by_product.get(
                product_id, []
            )
            product["appliedPromotions"] = applied_promotions_by_product.get(
                product_id, []
            )

        return res_body

    except SQLAlchemyError as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )


@handle_exceptions
async def stop_direct_promotion(promotion_id: int, kc_user_id: str, db: AsyncSession):
    """
    작가의 직접 프로모션 중지
    """
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    query = text("""
        select *, (select author_id from tb_product where product_id = dp.product_id) as author_user_id
          from tb_direct_promotion dp
         where id = :id
    """)

    result = await db.execute(query, {"id": promotion_id})
    db_rst = result.mappings().one_or_none()

    if not db_rst:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_DIRECT_PROMOTION,
        )

    promotion = dict(db_rst)
    if promotion.get("author_user_id") != user_id:
        raise CustomResponseException(
            status_code=status.HTTP_403_FORBIDDEN,
            message=ErrorMessages.FORBIDDEN_DIRECT_PROMOTION_FOR_STOP,
        )

    # end 상태인 프로모션은 중지할 수 없음
    if promotion.get("status") == "end":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.CANNOT_STOP_ENDED_PROMOTION,
        )

    query = text("""
        update tb_direct_promotion
        set status = 'stop'
        where id = :id
    """)
    await db.execute(query, {"id": promotion_id})

    res_body = dict()
    res_body["result"] = True

    return res_body


@handle_exceptions
async def start_direct_promotion(promotion_id: int, kc_user_id: str, db: AsyncSession):
    """
    작가의 직접 프로모션 시작
    """
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    query = text("""
        select *, (select author_id from tb_product where product_id = dp.product_id) as author_user_id
          from tb_direct_promotion dp
         where id = :id
    """)

    result = await db.execute(query, {"id": promotion_id})
    db_rst = result.mappings().one_or_none()

    if not db_rst:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_DIRECT_PROMOTION,
        )

    promotion = dict(db_rst)
    if promotion.get("author_user_id") != user_id:
        raise CustomResponseException(
            status_code=status.HTTP_403_FORBIDDEN,
            message=ErrorMessages.FORBIDDEN_DIRECT_PROMOTION_FOR_START,
        )

    # end 상태인 프로모션은 시작할 수 없음
    if promotion.get("status") == "end":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.CANNOT_START_ENDED_PROMOTION,
        )

    query = text("""
        update tb_direct_promotion
        set status = 'ing'
        where id = :id
    """)
    await db.execute(query, {"id": promotion_id})

    res_body = dict()
    res_body["result"] = True

    return res_body


@handle_exceptions
async def end_direct_promotion(promotion_id: int, kc_user_id: str, db: AsyncSession):
    """
    작가의 직접 프로모션 종료
    """
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    query = text("""
        select *, (select author_id from tb_product where product_id = dp.product_id) as author_user_id
          from tb_direct_promotion dp
         where id = :id
    """)

    result = await db.execute(query, {"id": promotion_id})
    db_rst = result.mappings().one_or_none()

    if not db_rst:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_DIRECT_PROMOTION,
        )

    promotion = dict(db_rst)
    if promotion.get("author_user_id") != user_id:
        raise CustomResponseException(
            status_code=status.HTTP_403_FORBIDDEN,
            message=ErrorMessages.FORBIDDEN_DIRECT_PROMOTION_FOR_STOP,
        )

    query = text("""
        update tb_direct_promotion
        set status = 'end'
        where id = :id
    """)
    await db.execute(query, {"id": promotion_id})

    res_body = dict()
    res_body["result"] = True

    return res_body


async def issue_reader_of_prev_promotion(
    promotion_id: int, kc_user_id: str, db: AsyncSession
):
    """
    선작 독자 무료 대여권 발급 (일주일에 한번만 가능, 매주 월요일 리셋)
    """
    try:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 프로모션 정보 조회
        query = text("""
            select dp.*,
                   (select author_id from tb_product where product_id = dp.product_id) as author_user_id,
                   (select title from tb_product where product_id = dp.product_id) as product_title
              from tb_direct_promotion dp
             where id = :id
        """)
        result = await db.execute(query, {"id": promotion_id})
        db_rst = result.mappings().one_or_none()

        if not db_rst:
            raise CustomResponseException(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ErrorMessages.NOT_FOUND_DIRECT_PROMOTION,
            )

        promotion = dict(db_rst)

        # 작가 권한 체크
        if promotion.get("author_user_id") != user_id:
            raise CustomResponseException(
                status_code=status.HTTP_403_FORBIDDEN,
                message=ErrorMessages.FORBIDDEN_PRODUCT_FOR_DIRECT_PROMOTION,
            )

        # reader-of-prev 타입만 발급 가능
        if promotion.get("type") != "reader-of-prev":
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.CANNOT_ISSUE_NON_READER_OF_PREV_PROMOTION,
            )

        # 상태 체크 (ing 또는 pending 상태에서 발급 가능)
        # PM 요청: 시작 전(pending) 상태에서도 선물함 발급이 가능하도록 수정
        if promotion.get("status") not in ("ing", "pending"):
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.CANNOT_ISSUE_NOT_IN_PROGRESS_PROMOTION,
            )

        # 작가의 모든 작품에 reader-of-prev 프로모션이 설정되어 있는지 조회
        author_user_id = promotion.get("author_user_id")
        query = text("""
            select dp.id as promotion_id, dp.product_id, dp.num_of_ticket_per_person, dp.type,
                   p.title as product_title, p.author_name
              from tb_direct_promotion dp
             inner join tb_product p on dp.product_id = p.product_id
             where p.author_id = :author_id
               and dp.type = 'reader-of-prev'
               and dp.status in ('ing', 'pending')
        """)
        result = await db.execute(query, {"author_id": author_user_id})
        author_promotions = result.mappings().all()

        if not author_promotions:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.NO_READER_OF_PREV_PROMOTION_IN_PROGRESS,
            )

        total_issued_count = 0
        total_tickets = 0

        # 각 작품별로 처리
        for promo in author_promotions:
            promo_product_id = promo["product_id"]
            promo_id = promo["promotion_id"]
            num_of_ticket = promo["num_of_ticket_per_person"]

            # 해당 작품을 북마크한 유저 조회
            query = text("""
                select user_id
                  from tb_user_bookmark
                 where product_id = :product_id
                   and use_yn = 'Y'
            """)
            result = await db.execute(query, {"product_id": promo_product_id})
            bookmark_users = result.mappings().all()

            # 이 작품에 북마크한 유저가 없으면 스킵
            if not bookmark_users:
                continue

            # 각 유저에게 선물함으로 대여권 지급
            product_title = promo["product_title"]

            for bookmark_user in bookmark_users:
                bookmark_user_id = bookmark_user["user_id"]

                # 해당 유저가 이번 주에 이 작품으로 선물함에 받았는지 체크 (작품별로 일주일에 한 번)
                query = text("""
                    select count(*) as count
                      from tb_user_giftbook ug
                     inner join tb_direct_promotion dp on ug.acquisition_id = dp.id
                     where ug.user_id = :user_id
                       and dp.product_id = :product_id
                       and ug.acquisition_type = 'direct_promotion'
                       and dp.type = 'reader-of-prev'
                       and YEARWEEK(ug.created_date, 1) = YEARWEEK(NOW(), 1)
                """)
                result = await db.execute(
                    query,
                    {
                        "user_id": bookmark_user_id,
                        "product_id": promo_product_id,
                    },
                )
                already_received_this_week = result.scalar()

                # 이미 이번 주에 이 작품에서 받았으면 스킵
                if already_received_this_week > 0:
                    continue

                # 선작독자: 유효기간 1주일 (선물함 유효기간도 1주일)
                expiration_date_str = (datetime.now() + timedelta(days=7)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                giftbook_req = user_giftbook_schema.PostUserGiftbookReqBody(
                    user_id=bookmark_user_id,
                    product_id=promo_product_id,
                    episode_id=None,
                    ticket_type=promo["type"],
                    own_type="rental",
                    acquisition_type="direct_promotion",
                    acquisition_id=promo_id,
                    reason="선작독자 무료 대여권",
                    amount=num_of_ticket,
                    promotion_type="reader-of-prev",
                    expiration_date=expiration_date_str,  # 선물함 유효기간 1주일
                    ticket_expiration_type="days",  # 수령 후 대여권 유효기간 7일
                    ticket_expiration_value=7,
                )
                await user_giftbook_service.post_user_giftbook(
                    req_body=giftbook_req,
                    kc_user_id="",
                    db=db,
                    user_id=bookmark_user_id,
                )

                # 선작독자 무료 대여권 지급 알림 전송
                try:
                    notification_title = f"{product_title} 작가가 회원님께 드리는 무료열람권(대여권)이 도착하였습니다"
                    notification_query = text("""
                        INSERT INTO tb_user_notification_item
                        (user_id, noti_type, title, content, read_yn, created_id, created_date)
                        VALUES (:user_id, 'promotion', :title, '', 'N', :created_id, NOW())
                    """)
                    await db.execute(
                        notification_query,
                        {
                            "user_id": bookmark_user_id,
                            "title": notification_title,
                            "created_id": author_user_id,
                        },
                    )
                except Exception as e:
                    # 알림 실패해도 대여권 지급은 성공으로 처리
                    logger.error(f"Failed to send reader-of-prev notification: {e}")

                total_tickets += num_of_ticket
                total_issued_count += 1

        # 발급 완료 후 해당 프로모션들의 status를 'end'로 변경하고 start_date를 현재 날짜로 업데이트
        for promo in author_promotions:
            query = text("""
                update tb_direct_promotion
                   set status = 'end'
                     , start_date = NOW()
                     , updated_date = NOW()
                 where id = :promo_id
            """)
            await db.execute(query, {"promo_id": promo["promotion_id"]})

        res_body = dict()
        res_body["result"] = True
        res_body["total_issued_count"] = total_issued_count
        res_body["total_tickets"] = total_tickets

        return res_body

    except SQLAlchemyError as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )


async def check_reader_of_prev_issuance_status(
    promotion_id: int, kc_user_id: str, db: AsyncSession
):
    """
    선작 독자 무료 대여권 발급 상태 확인
    - 이번 주에 발급했는지 여부
    - 마지막 발급 날짜
    - 다음 발급 가능 날짜 (다음 주 월요일)
    """
    try:
        # user_id = await comm_service.get_user_from_kc(kc_user_id, db)

        # 프로모션 조회 (product 테이블과 조인해서 author_id 가져오기)
        query = text("""
            select dp.id, dp.product_id, dp.type, dp.status, p.author_id
              from tb_direct_promotion dp
             inner join tb_product p on dp.product_id = p.product_id
             where dp.id = :id
        """)
        result = await db.execute(query, {"id": promotion_id})
        promotion = result.mappings().one_or_none()

        if not promotion:
            raise CustomResponseException(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ErrorMessages.NOT_FOUND_DIRECT_PROMOTION,
            )

        # 권한 확인: 작가만 확인 가능
        # if promotion.get("author_id") != user_id:
        #     raise CustomResponseException(
        #         status_code=status.HTTP_403_FORBIDDEN,
        #         message=ErrorMessages.FORBIDDEN_DIRECT_PROMOTION_FOR_CHECK,
        #     )

        # reader-of-prev 타입만 확인 가능
        if promotion.get("type") != "reader-of-prev":
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.CANNOT_CHECK_NON_READER_OF_PREV_PROMOTION,
            )

        promo_product_id = promotion.get("product_id")

        # 이번 주에 이 작품에서 선물함으로 발급한 내역 조회 (작품 기준)
        query = text("""
            select MAX(ug.created_date) as created_date, count(*) as issued_count
              from tb_user_giftbook ug
             inner join tb_direct_promotion dp on ug.acquisition_id = dp.id
             where dp.product_id = :product_id
               and ug.acquisition_type = 'direct_promotion'
               and dp.type = 'reader-of-prev'
               and YEARWEEK(ug.created_date, 1) = YEARWEEK(NOW(), 1)
             group by DATE(ug.created_date)
             order by MAX(ug.created_date) desc
             limit 1
        """)
        result = await db.execute(query, {"product_id": promo_product_id})
        this_week_issuance = result.mappings().one_or_none()

        # 마지막 발급 날짜 조회 (전체 기간, 작품 기준)
        query = text("""
            select MAX(ug.created_date) as created_date, count(*) as issued_count
              from tb_user_giftbook ug
             inner join tb_direct_promotion dp on ug.acquisition_id = dp.id
             where dp.product_id = :product_id
               and ug.acquisition_type = 'direct_promotion'
               and dp.type = 'reader-of-prev'
             group by DATE(ug.created_date)
             order by MAX(ug.created_date) desc
             limit 1
        """)
        result = await db.execute(query, {"product_id": promo_product_id})
        last_issuance = result.mappings().one_or_none()

        # 다음 월요일 계산
        query = text("""
            select CASE
                     WHEN DAYOFWEEK(CURDATE()) = 2 THEN CURDATE()
                     ELSE DATE_ADD(CURDATE(), INTERVAL (9 - DAYOFWEEK(CURDATE())) % 7 DAY)
                   END as next_monday
        """)
        result = await db.execute(query)
        next_monday = result.scalar()

        res_body = dict()
        res_body["issued_this_week"] = this_week_issuance is not None
        res_body["last_issued_date"] = (
            last_issuance["created_date"].strftime("%Y-%m-%d %H:%M:%S")
            if last_issuance
            else None
        )
        res_body["last_issued_count"] = (
            int(last_issuance["issued_count"]) if last_issuance else 0
        )
        res_body["this_week_issued_date"] = (
            this_week_issuance["created_date"].strftime("%Y-%m-%d %H:%M:%S")
            if this_week_issuance
            else None
        )
        res_body["this_week_issued_count"] = (
            int(this_week_issuance["issued_count"]) if this_week_issuance else 0
        )
        res_body["next_available_date"] = (
            next_monday.strftime("%Y-%m-%d") if next_monday else None
        )

        return res_body

    except SQLAlchemyError as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )


async def save_direct_promotion(
    req_body: user_schema.PostDirectPromotionTicketCountReqBody,
    product_id: int,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    작가의 직접 프로모션 티켓 수 저장
    """
    try:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text("""
            select *
            from tb_product
            where product_id = :product_id
        """)
        result = await db.execute(query, {"product_id": product_id})
        db_rst = result.mappings().one_or_none()

        if not db_rst:
            raise CustomResponseException(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ErrorMessages.NOT_FOUND_PRODUCT,
            )

        product = dict(db_rst)

        if product.get("author_id") != user_id:
            raise CustomResponseException(
                status_code=status.HTTP_403_FORBIDDEN,
                message=ErrorMessages.FORBIDDEN_PRODUCT_FOR_DIRECT_PROMOTION,
            )

        query = text("""
            select * from tb_direct_promotion where product_id = :product_id and `type` = 'free-for-first'
        """)
        result = await db.execute(query, {"product_id": product_id})
        db_rst = result.mappings().one_or_none()

        if not db_rst:
            # 없으면 등록해서 값 저장
            query = text("""
                insert into tb_direct_promotion
                (product_id, start_date, `type`, status, num_of_ticket_per_person, created_id, updated_id)
                values
                (:product_id, now(), 'free-for-first', 'pending', :ticket_count, :created_id, :updated_id)
            """)
            await db.execute(
                query,
                {
                    "product_id": product_id,
                    "ticket_count": req_body.num_of_ticket_per_person_for_free_for_first,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )
        else:
            # 있으면 업데이트
            query = text("""
                update tb_direct_promotion
                set num_of_ticket_per_person = :ticket_count,
                    updated_date = NOW()
                where product_id = :product_id and `type` = 'free-for-first'
            """)
            await db.execute(
                query,
                {
                    "ticket_count": req_body.num_of_ticket_per_person_for_free_for_first,
                    "product_id": product_id,
                },
            )

        query = text("""
            select * from tb_direct_promotion where product_id = :product_id and `type` = 'reader-of-prev'
        """)
        result = await db.execute(query, {"product_id": product_id})
        db_rst = result.mappings().one_or_none()

        if not db_rst:
            # 없으면 등록해서 값 저장
            query = text("""
                insert into tb_direct_promotion
                (product_id, start_date, `type`, status, num_of_ticket_per_person, created_id, updated_id)
                values
                (:product_id, now(), 'reader-of-prev', 'pending', :ticket_count, :created_id, :updated_id)
            """)
            await db.execute(
                query,
                {
                    "product_id": product_id,
                    "ticket_count": req_body.num_of_ticket_per_person_for_reader_of_prev,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )
        else:
            # 있으면 업데이트
            query = text("""
                update tb_direct_promotion
                set num_of_ticket_per_person = :ticket_count,
                    updated_date = NOW()
                where product_id = :product_id and `type` = 'reader-of-prev'
            """)
            await db.execute(
                query,
                {
                    "ticket_count": req_body.num_of_ticket_per_person_for_reader_of_prev,
                    "product_id": product_id,
                },
            )

        res_body = dict()
        res_body["result"] = True

        return res_body

    except SQLAlchemyError as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )


async def apply_applied_promotion(
    req_body: user_schema.PostAppliedPromotionReqBody,
    product_id: int,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    작가의 신청 프로모션 신청
    """
    try:
        # 이번주의 신청 프로모션 남은 자리 체크
        query = text("""
            select count(*) as cnt
              from tb_applied_promotion
             where status = 'ing'
               and created_date >= DATE_SUB(CURDATE(), INTERVAL WEEKDAY(CURDATE()) DAY)
               and created_date < DATE_ADD(DATE_SUB(CURDATE(), INTERVAL WEEKDAY(CURDATE()) DAY), INTERVAL 7 DAY)
        """)
        result = await db.execute(query, {})
        ing_count = result.scalar() or 0
        remaining_slots = 20 - ing_count

        if remaining_slots <= 0:
            # 남은 자리가 없음
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.NO_AVAILABLE_APPLIED_PROMOTION_SLOT,
            )

        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text("""
            select *
            from tb_product
            where product_id = :product_id
        """)
        result = await db.execute(query, {"product_id": product_id})
        db_rst = result.mappings().one_or_none()

        if not db_rst:
            raise CustomResponseException(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ErrorMessages.NOT_FOUND_PRODUCT,
            )

        product = dict(db_rst)

        if product.get("author_id") != user_id:
            raise CustomResponseException(
                status_code=status.HTTP_403_FORBIDDEN,
                message=ErrorMessages.FORBIDDEN_PRODUCT_FOR_APPLIED_PROMOTION,
            )

        # 중복 신청 체크 (같은 타입의 프로모션이 이미 신청 중이거나 진행 중인지)
        query = text("""
            select status
              from tb_applied_promotion
             where product_id = :product_id
               and type = :type
               and status in ('apply', 'ing')
             limit 1
        """)
        result = await db.execute(
            query, {"product_id": product_id, "type": req_body.type}
        )
        existing_promotion = result.mappings().one_or_none()

        if existing_promotion:
            if existing_promotion["status"] == "apply":
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.ALREADY_APPLIED_PROMOTION,
                )
            else:  # ing
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.ALREADY_IN_PROGRESS_PROMOTION,
                )

        # 반려 후 재신청 가능 여부 체크
        if req_body.type == "6-9-path":
            # 6-9 패스: 이번 주 월요일 이후 반려된 경우 재신청 불가 (매주 월요일 초기화)
            query = text("""
                select updated_date
                  from tb_applied_promotion
                 where product_id = :product_id
                   and type = :type
                   and status = 'deny'
                   and updated_date >= DATE_SUB(CURDATE(), INTERVAL WEEKDAY(CURDATE()) DAY)
                 order by updated_date desc
                 limit 1
            """)
            result = await db.execute(
                query, {"product_id": product_id, "type": req_body.type}
            )
            last_deny = result.mappings().one_or_none()

            if last_deny:
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.CANNOT_APPLY_UNTIL_NEXT_WEEK_AFTER_DENY,
                )
        else:
            # 기다리면 무료 등 기타: 반려 후 180일 체크
            query = text("""
                select updated_date
                  from tb_applied_promotion
                 where product_id = :product_id
                   and type = :type
                   and status = 'deny'
                 order by updated_date desc
                 limit 1
            """)
            result = await db.execute(
                query, {"product_id": product_id, "type": req_body.type}
            )
            last_deny = result.mappings().one_or_none()

            if last_deny:
                deny_date = last_deny["updated_date"]
                days_since_deny = (datetime.now() - deny_date).days
                if days_since_deny < 180:
                    raise CustomResponseException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message=ErrorMessages.CANNOT_APPLY_WITHIN_180_DAYS_AFTER_DENY,
                    )

        # start_date, end_date 필수 체크
        if not req_body.start_date:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.REQUIRED_APPLIED_PROMOTION_START_DATE,
            )

        if not req_body.end_date:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.REQUIRED_APPLIED_PROMOTION_END_DATE,
            )

        query = text("""
            insert into tb_applied_promotion (id, product_id, type, status, start_date, end_date, num_of_ticket_per_person, created_id, created_date)
            values (default, :product_id, :type, 'apply', :start_date, :end_date, 1, :created_id, :created_date)
        """)
        await db.execute(
            query,
            {
                "product_id": product_id,
                "type": req_body.type,
                "start_date": req_body.start_date,
                "end_date": req_body.end_date,
                "created_id": -1,
                "created_date": datetime.now(),
            },
        )

        res_body = dict()
        res_body["result"] = True

        return res_body

    except SQLAlchemyError as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )


async def cancel_applied_promotion(
    promotion_id: int, kc_user_id: str, db: AsyncSession
):
    """
    작가의 신청 프로모션 철회
    """
    try:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text("""
            select *
            from tb_applied_promotion
            where id = :id
        """)
        result = await db.execute(query, {"id": promotion_id})
        db_rst = result.mappings().one_or_none()

        if not db_rst:
            raise CustomResponseException(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ErrorMessages.NOT_FOUND_APPLIED_PROMOTION,
            )

        promotion = dict(db_rst)

        query = text("""
            select *
            from tb_product
            where product_id = :product_id
        """)
        result = await db.execute(query, {"product_id": promotion.get("product_id")})
        db_rst = result.mappings().one_or_none()

        if db_rst:
            product = dict(db_rst)

            if product.get("author_id") != user_id:
                raise CustomResponseException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message=ErrorMessages.FORBIDDEN_PRODUCT_FOR_APPLIED_PROMOTION,
                )

        query = text("""
            delete from tb_applied_promotion where id = :id
        """)
        await db.execute(query, {"id": promotion_id})

        res_body = dict()
        res_body["result"] = True

        return res_body

    except SQLAlchemyError as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )


@handle_exceptions
async def get_contract_offers(kc_user_id: str, db: AsyncSession):
    """
    작가의 계약 제안 목록
    """
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    query = text(f"""
        select
            offer.offer_id
            , offer.offer_user_id
            , offer.author_user_id
            , {get_file_path_sub_query("profile.profile_image_id", "offerer_profile_image_path", "user")}
            , profile.nickname as offerer_nickname
            , offer.offer_price
            , offer.offer_profit
            , offer.author_profit
            , {get_file_path_sub_query("p.thumbnail_file_id", "cover_image_path", "cover")}
            , p.title
            , offer.author_accept_yn
            , offer.use_yn
            , offer.updated_date
            , offer.offer_message
            , {get_badge_image_sub_query("profile.user_id", "event", "userEventLevelBadgeImagePath", "profile.profile_id")}
          from tb_product_contract_offer offer
         inner join tb_product p on offer.product_id = p.product_id
         inner join tb_user offerer on offer.offer_user_id = offerer.user_id
         inner join tb_user_profile profile on offerer.user_id = profile.user_id and profile.default_yn = 'Y'
         where offer.author_user_id = :user_id
         order by offer.created_date desc
    """)

    result = await db.execute(query, {"user_id": user_id})
    rows = result.mappings().all()
    return build_list_response(rows)


@handle_exceptions
async def get_contract_offered(kc_user_id: str, db: AsyncSession):
    """
    보낸 계약 제안 목록
    """
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    query = text(f"""
        select
            offer.offer_id
            , p.product_id
            , {get_file_path_sub_query("p.thumbnail_file_id", "cover_image_path", "cover")}
            , p.title
            , p.author_name
            , p.illustrator_name
            , p.created_date
            , if (wff.product_id IS NOT NULL, 'Y', 'N') as waiting_for_free_yn
            , if (p69.product_id IS NOT NULL, 'Y', 'N') as six_nine_path_yn
            , offer.offer_price
            , offer.offer_profit
            , offer.author_profit
            , offer.author_accept_yn
            , offer.use_yn
            , offer.author_user_id
            , pg.keyword_name as primary_genre
            , sg.keyword_name as sub_genre
            , (SELECT GROUP_CONCAT(DISTINCT sk2.keyword_name SEPARATOR '|') FROM tb_mapped_product_keyword mpk2 LEFT JOIN tb_standard_keyword sk2 ON sk2.keyword_id = mpk2.keyword_id WHERE mpk2.product_id = p.product_id) as keywords
          from tb_product_contract_offer offer
         inner join tb_product p on offer.product_id = p.product_id
          LEFT JOIN tb_applied_promotion wff ON wff.product_id = p.product_id AND wff.type = 'waiting-for-free' AND DATE(wff.start_date) <= CURDATE() AND (wff.end_date IS NULL OR DATE(wff.end_date) >= CURDATE())
          LEFT JOIN tb_applied_promotion p69 ON p69.product_id = p.product_id AND p69.type = '6-9-path' AND DATE(p69.start_date) <= CURDATE() AND (p69.end_date IS NULL OR DATE(p69.end_date) >= CURDATE())
          LEFT JOIN tb_standard_keyword pg ON pg.keyword_id = p.primary_genre_id AND pg.use_yn = 'Y' AND pg.major_genre_yn = 'Y'
          LEFT JOIN tb_standard_keyword sg ON sg.keyword_id = p.sub_genre_id AND sg.use_yn = 'Y' AND sg.major_genre_yn = 'Y'
         where offer.offer_user_id = :user_id
         order by offer.created_date desc
    """)

    result = await db.execute(query, {"user_id": user_id})
    rows = result.mappings().all()

    res_body = dict()
    res_body["data"] = []

    for row in rows:
        row_dict = dict(row)
        # Convert keywords from pipe-separated string to array
        if row_dict.get("keywords"):
            row_dict["keywords"] = row_dict["keywords"].split("|")
        else:
            row_dict["keywords"] = []
        res_body["data"].append(row_dict)

    return res_body


@handle_exceptions
async def accept_contract_offers(offer_id: int, kc_user_id: str, db: AsyncSession):
    """
    작품 계약 제안 수락
    """

    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    query = text("""
        select
            *
          from tb_product_contract_offer
         where offer_id = :offer_id
    """)

    result = await db.execute(query, {"offer_id": offer_id})
    db_rst = result.mappings().one_or_none()

    if not db_rst:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_CONTRACT_OFFER,
        )

    offer = dict(db_rst)
    if offer.get("author_user_id") != user_id:
        raise CustomResponseException(
            status_code=status.HTTP_403_FORBIDDEN,
            message=ErrorMessages.FORBIDDEN_CONTRACT_OFFER_FOR_ACCEPT,
        )

    if offer.get("author_accept_yn") == "Y":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_ACCEPTED_CONTRACT_OFFER,
        )

    query = text("""
        update tb_product_contract_offer
        set author_accept_yn = 'Y',
            updated_date = NOW()
        where offer_id = :offer_id
    """)
    await db.execute(query, {"offer_id": offer_id})

    res_body = dict()
    res_body["result"] = True

    return res_body


@handle_exceptions
async def reject_contract_offers(offer_id: int, kc_user_id: str, db: AsyncSession):
    """
    작품 계약 제안 거절
    """

    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    query = text("""
        select
            *
          from tb_product_contract_offer
         where offer_id = :offer_id
    """)

    result = await db.execute(query, {"offer_id": offer_id})
    db_rst = result.mappings().one_or_none()

    if not db_rst:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_CONTRACT_OFFER,
        )

    offer = dict(db_rst)
    if offer.get("author_user_id") != user_id:
        raise CustomResponseException(
            status_code=status.HTTP_403_FORBIDDEN,
            message=ErrorMessages.FORBIDDEN_CONTRACT_OFFER_FOR_REJECT,
        )

    if offer.get("author_accept_yn") == "N":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_REJECTED_CONTRACT_OFFER,
        )

    query = text("""
        update tb_product_contract_offer
        set author_accept_yn = 'N',
            updated_date = NOW()
        where offer_id = :offer_id
    """)
    await db.execute(query, {"offer_id": offer_id})

    res_body = dict()
    res_body["result"] = True

    return res_body


async def post_products_product_id_contract_offer(
    product_id: str,
    req_body: product_schema.PostProductsProductIdContractOfferReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    계약 제안 생성
    """
    res_body = {}
    product_id_to_int = int(product_id)

    # 정산 비율 validation
    if req_body.cp_profit_rate <= 0 or req_body.author_profit_rate <= 0:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_CONTRACT_OFFER_PROFIT_RATE_POSITIVE,
        )

    if req_body.cp_profit_rate + req_body.author_profit_rate != 100:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_CONTRACT_OFFER_PROFIT_RATE,
        )

    try:
        offer_user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if offer_user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 작품 정보 및 작가 user_id 조회
        query = text("""
            SELECT user_id as author_user_id, title
            FROM tb_product
            WHERE product_id = :product_id
        """)
        result = await db.execute(query, {"product_id": product_id_to_int})
        db_rst = result.mappings().all()

        if not db_rst:
            raise CustomResponseException(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ErrorMessages.NOT_FOUND_PRODUCT,
            )

        product_data = db_rst[0]
        author_user_id = product_data.get("author_user_id")
        product_title = product_data.get("title")

        # 계약 제안 데이터 insert
        query = text("""
            INSERT INTO tb_product_contract_offer (
                product_id,
                profit_type,
                author_profit,
                offer_profit,
                author_user_id,
                author_accept_yn,
                offer_user_id,
                offer_type,
                offer_code,
                offer_price,
                offer_message,
                offer_date,
                use_yn,
                created_id
            ) VALUES (
                :product_id,
                'percent',
                :author_profit,
                :offer_profit,
                :author_user_id,
                NULL,
                :offer_user_id,
                :offer_type,
                :offer_code,
                :offer_price,
                :offer_message,
                NOW(),
                'Y',
                :created_id
            )
        """)

        await db.execute(
            query,
            {
                "product_id": product_id_to_int,
                "author_profit": req_body.author_profit_rate,
                "offer_profit": req_body.cp_profit_rate,
                "author_user_id": author_user_id,
                "offer_user_id": offer_user_id,
                "offer_type": req_body.advance_payment_range,
                "offer_code": req_body.advance_payment_range,
                "offer_price": 0,
                "offer_message": req_body.message,
                "created_id": offer_user_id,
            },
        )

        # 작가에게 계약 제안 알림 전송 (4. 받은 제안 알림)
        try:
            # CP사 또는 편집자 이름 조회
            query = text("""
                SELECT nickname
                FROM tb_user_profile
                WHERE user_id = :user_id
                AND default_yn = 'Y'
            """)
            result = await db.execute(query, {"user_id": offer_user_id})
            cp_profile = result.mappings().one_or_none()
            cp_name = cp_profile.get("nickname") if cp_profile else "CP"

            notification_title = f"[{cp_name}]님의 [{product_title}] 작품에 계약 제안"
            notification_content = req_body.message if req_body.message else ""

            notification_query = text("""
                INSERT INTO tb_user_notification_item
                (user_id, noti_type, title, content, read_yn, created_id, created_date)
                VALUES (:user_id, 'contract_offer', :title, :content, 'N', :created_id, NOW())
            """)
            await db.execute(
                notification_query,
                {
                    "user_id": author_user_id,
                    "title": notification_title,
                    "content": notification_content,
                    "created_id": offer_user_id,
                },
            )
        except Exception as e:
            # 알림 실패해도 계약 제안은 성공으로 처리
            logger.error(f"Failed to send contract offer notification: {e}")

        res_body["data"] = {
            "productId": product_id_to_int,
            "message": "계약 제안이 성공적으로 생성되었습니다.",
        }

    except CustomResponseException:
        raise
    except OperationalError as e:
        error_logger.error(f"post_products_product_id_contract_offer => {e}")
        raise CustomResponseException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    except SQLAlchemyError as e:
        error_logger.error(f"post_products_product_id_contract_offer => {e}")
        raise CustomResponseException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        error_logger.error(f"post_products_product_id_contract_offer => {e}")
        raise CustomResponseException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return res_body
