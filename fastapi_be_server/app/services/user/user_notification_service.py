from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.const import settings, ErrorMessages, LOGGER_TYPE
from app.exceptions import CustomResponseException
from app.utils.common import handle_exceptions
import app.schemas.user as user_schema

from app.config.log_config import service_error_logger
import app.services.common.comm_service as comm_service

error_logger = service_error_logger(LOGGER_TYPE.LOGGER_INSTANCE_NAME_FOR_SERVICE_ERROR)

"""
user notification 도메인 개별 서비스 함수 모음
"""


async def get_user_alarms(kc_user_id: str, db: AsyncSession):
    res_data = list()

    if kc_user_id:
        try:
            async with db.begin():
                query = text("""
                                 select
                                    c.id
                                    , c.title
                                    , case when c.noti_type='author' then true else false end as author
                                    , c.content
                                    , c.read_yn as readYn
                                    , date_format(c.created_date, '%Y-%m-%d %H:%i:%s') as createdAt
                                 from tb_user a
                                    inner join tb_user_notification_item c on a.user_id = c.user_id
                                 where a.kc_user_id = :kc_user_id
                                    and a.use_yn = 'Y'
                                 """)

                result = await db.execute(query, {"kc_user_id": kc_user_id})
                db_rst = result.mappings().all()

                if db_rst:
                    for row in db_rst:
                        data = dict(row)
                        data["author"] = data["author"] == 1
                        res_data.append(data)
                # else:
                #     raise CustomResponseException(status_code=status.HTTP_401_UNAUTHORIZED, code=settings.CustomStatusCode.NEED_IDENTITY.value)

                # user_id = db_rst[0].get("user_id")

                # if db_rst:
                #     query = text("""
                #                      select a.id as alarm_id
                #                           , a.noti_type
                #                           , a.noti_yn
                #                        from tb_user_notification a
                #                       where a.user_id = :user_id
                #                      """)

                #     result = await db.execute(query, {
                #         "user_id": user_id
                #     })
                #     db_rst = result.mappings().all()

                #     if db_rst:
                #         res_data = [user_schema.GetUserAlarmsToCamel(**row) for row in db_rst]

        # except OperationalError as e:
        #     raise CustomResponseException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        # except SQLAlchemyError as e:
        #     raise CustomResponseException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception:
            # error_logger.error(f'user: {kc_user_id} - {e}')
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        # error_logger.error(f'user: {kc_user_id} - get_user_alarms:HTTP_401_UNAUTHORIZED')
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


async def put_user_alarms_alarm_id(kc_user_id: str, db: AsyncSession):
    # alarm_id_to_int = int(alarm_id)

    if kc_user_id:
        try:
            async with db.begin():
                # query = text("""
                #                  select user_id
                #                    from tb_user
                #                   where kc_user_id = :kc_user_id
                #                     and use_yn = 'Y'
                #                  """)

                # result = await db.execute(query, {
                #     "kc_user_id": kc_user_id
                # })
                # db_rst = result.mappings().all()
                # user_id = db_rst[0].get("user_id")

                query = text("""
                                 update tb_user_notification_item a
                                    set a.read_yn = 'Y'
                                      , a.updated_id = ifnull((select user_id from tb_user where kc_user_id = :kc_user_id and use_yn = 'Y'), 0)
                                      , a.updated_date = now()
                                  where exists (
                                        select user_id
                                        from tb_user b
                                        where b.kc_user_id = :kc_user_id
                                        and b.use_yn = 'Y'
                                        and b.user_id = a.user_id
                                    )
                                 """)

                await db.execute(query, {"kc_user_id": kc_user_id})
        # except OperationalError as e:
        #     raise CustomResponseException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        # except SQLAlchemyError as e:
        #     raise CustomResponseException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception:
            # error_logger.error(f'user: {kc_user_id} - {e}')
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    return


async def send_notification_to_bookmarked_users(
    product_id: int, content: str, kc_user_id: str, db: AsyncSession
):
    """
    작품을 북마크한 유저들에게 알림을 발송하는 함수

    Args:
        product_id: 작품 ID
        content: 알림 내용 (50자 이내)
        kc_user_id: 작가의 Keycloak 유저 ID
        db: DB 세션

    Returns:
        dict: 이번 주에 남은 알림 발송 가능 횟수
    """
    try:
        # content 길이 체크 (50자 이내)
        if len(content) > 50:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.NOTIFICATION_CONTENT_LENGTH_EXCEEDED,
            )

        # kc_user_id로 user_id 조회
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # product의 author_id와 user_id가 일치하는지 확인 및 작품 정보 조회
        query = text("""
            select author_id, title
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

        product_data = dict(db_rst)
        author_id = product_data.get("author_id")
        product_title = product_data.get("title")

        if author_id != user_id:
            raise CustomResponseException(
                status_code=status.HTTP_403_FORBIDDEN,
                message=ErrorMessages.FORBIDDEN_NOT_AUTHOR_OF_PRODUCT,
            )

        # 이번 주 알림 발송 횟수 체크 (월요일 00:00 기준)
        query = text("""
            select count(*) as notification_count
            from tb_user_notification_log
            where product_id = :product_id
            and created_date >= DATE_SUB(CURDATE(), INTERVAL WEEKDAY(CURDATE()) DAY)
            and created_date < DATE_ADD(DATE_SUB(CURDATE(), INTERVAL WEEKDAY(CURDATE()) DAY), INTERVAL 7 DAY)
        """)
        result = await db.execute(query, {"product_id": product_id})
        notification_count_result = result.mappings().one_or_none()
        current_week_count = (
            notification_count_result.get("notification_count", 0)
            if notification_count_result
            else 0
        )

        if current_week_count >= 5:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.EXCEEDED_WEEKLY_NOTIFICATION_LIMIT,
            )

        # 해당 작품을 북마크한 유저 조회
        query = text("""
            select user_id
            from tb_user_bookmark
            where product_id = :product_id
        """)
        result = await db.execute(query, {"product_id": product_id})
        bookmarked_users = result.mappings().all()

        notified_user_count = 0

        if bookmarked_users:
            # 알림 제목 생성 (작품 이름 포함)
            notification_title = f"[{product_title}] 작가의 독자 알림"

            # 각 유저에게 알림 생성 (bulk insert)
            notification_data = [
                {
                    "user_id": dict(user_row)["user_id"],
                    "title": notification_title,
                    "content": content,
                    "created_id": user_id,
                }
                for user_row in bookmarked_users
            ]

            # 한 번의 쿼리로 모든 알림 생성
            insert_query = text("""
                insert into tb_user_notification_item
                (user_id, noti_type, title, content, read_yn, created_id, created_date)
                values (:user_id, 'author', :title, :content, 'N', :created_id, NOW())
            """)
            await db.execute(insert_query, notification_data)

            # 알림 발송 로그 저장
            log_query = text("""
                insert into tb_user_notification_log
                (product_id, notification_count, created_id, updated_id)
                values (:product_id, :notification_count, :created_id, :updated_id)
            """)
            await db.execute(
                log_query,
                {
                    "product_id": product_id,
                    "notification_count": len(bookmarked_users),
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            notified_user_count = len(bookmarked_users)

        # 이번 주 남은 알림 발송 가능 횟수 계산
        remaining_count = (
            5 - (current_week_count + 1) if bookmarked_users else 5 - current_week_count
        )
        return {
            "result": True,
            "remaining_notification_count": remaining_count,
            "notified_user_count": notified_user_count,
        }

    except CustomResponseException:
        raise
    except SQLAlchemyError as e:
        error_logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )


@handle_exceptions
async def get_notification_settings(kc_user_id: str, db: AsyncSession):
    """
    해당 유저의 알림 설정 상태 조회
    """

    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    query = text("""
        select *
        from tb_user_notification
        where user_id = :user_id
        and noti_type IN ('benefit', 'comment', 'system', 'event', 'marketing')
    """)
    result = await db.execute(query, {"user_id": user_id})
    db_rst = result.mappings().all()

    # 각 데이터가 있는지 체크
    notification_status = {
        "benefit": None,
        "comment": None,
        "system": None,
        "event": None,
        "marketing": None,
    }

    if db_rst:
        for row in db_rst:
            setting = dict(row)
            noti_type = setting.get("noti_type")
            noti_yn = setting.get("noti_yn")
            notification_status[noti_type] = noti_yn

    res_body = dict()

    insert_noti_type = []
    for noti_type in ["benefit", "comment", "system", "event", "marketing"]:
        if notification_status[noti_type] is not None:
            # None이 아니면 조회된 데이터 사용
            res_body[noti_type] = notification_status[noti_type]
        else:
            # None이면 insert
            insert_noti_type.append(noti_type)
            res_body[noti_type] = "N"

    if len(insert_noti_type) > 0:
        query = text("""
            insert into tb_user_notification
            (user_id, noti_type, noti_yn, created_id, updated_id)
            values
            (:user_id, :noti_type, 'N', :created_id, :updated_id)
        """)
        await db.execute(
            query,
            [
                {
                    "user_id": user_id,
                    "noti_type": noti_type,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                }
                for noti_type in insert_noti_type
            ],
        )

    return {"data": res_body}


async def update_notification_settings(
    req_body: user_schema.PutNotificationSettingsReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    해당 유저의 알림 설정 상태 수정
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
            from tb_user_notification
            where user_id = :user_id
            and noti_type IN ('benefit', 'comment', 'system', 'event', 'marketing')
        """)
        result = await db.execute(query, {"user_id": user_id})
        db_rst = result.mappings().all()

        # 각 데이터가 있는지 체크
        notification_status = {
            "benefit": None,
            "comment": None,
            "system": None,
            "event": None,
            "marketing": None,
        }

        if db_rst:
            for row in db_rst:
                setting = dict(row)
                noti_type = setting.get("noti_type")
                noti_yn = setting.get("noti_yn")
                notification_status[noti_type] = noti_yn

        # optional이라 None일 수 있음
        # None이면 기존 값 유지, None이 아니면 요청 값으로 변경, 요청 값도 없으면 default로 "N"
        if req_body.benefit is None:
            req_body.benefit = (
                notification_status["benefit"]
                if notification_status["benefit"] is not None
                else "N"
            )
        if req_body.comment is None:
            req_body.comment = (
                notification_status["comment"]
                if notification_status["comment"] is not None
                else "N"
            )
        if req_body.system is None:
            req_body.system = (
                notification_status["system"]
                if notification_status["system"] is not None
                else "N"
            )
        if req_body.event is None:
            req_body.event = (
                notification_status["event"]
                if notification_status["event"] is not None
                else "N"
            )
        if req_body.marketing is None:
            req_body.marketing = (
                notification_status["marketing"]
                if notification_status["marketing"] is not None
                else "N"
            )

        insert_noti_type = []
        update_noti_type = []
        for noti_type in ["benefit", "comment", "system", "event", "marketing"]:
            if notification_status[noti_type] is not None:
                # None이 아니면 기존꺼 update
                update_noti_type.append(noti_type)
            else:
                # None이면 insert
                insert_noti_type.append(noti_type)

        if len(insert_noti_type) > 0:
            query = text("""
                insert into tb_user_notification
                (user_id, noti_type, noti_yn, created_id, updated_id)
                values
                (:user_id, :noti_type, :noti_yn, :created_id, :updated_id)
            """)
            await db.execute(
                query,
                [
                    {
                        "user_id": user_id,
                        "noti_type": noti_type,
                        "noti_yn": getattr(req_body, noti_type),
                        "created_id": settings.DB_DML_DEFAULT_ID,
                        "updated_id": settings.DB_DML_DEFAULT_ID,
                    }
                    for noti_type in insert_noti_type
                ],
            )

        if len(update_noti_type) > 0:
            query = text(f"""
                update tb_user_notification
                set noti_yn = CASE 
                    {" ".join([f"WHEN noti_type = '{noti_type}' THEN :{noti_type}_yn" for noti_type in update_noti_type])}
                    ELSE noti_yn
                END,
                updated_id = :updated_id,
                updated_date = NOW()
                where user_id = :user_id
                and noti_type IN ({", ".join([f"'{noti_type}'" for noti_type in update_noti_type])})
            """)
            params = {
                "user_id": user_id,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            }
            for noti_type in update_noti_type:
                params[f"{noti_type}_yn"] = getattr(req_body, noti_type)
            await db.execute(query, params)

        return {"data": True}

    except SQLAlchemyError as e:
        error_logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
