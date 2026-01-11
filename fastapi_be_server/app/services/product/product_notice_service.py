from typing import Optional
from app.services.common import comm_service
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from bs4 import BeautifulSoup

from app.const import LOGGER_TYPE, settings, ErrorMessages
from app.exceptions import CustomResponseException
from app.utils.time import convert_to_kor_time
import app.schemas.product as product_schema

from app.config.log_config import service_error_logger

error_logger = service_error_logger(LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_ERROR)

"""
product notice 도메인 개별 서비스 함수 모음
"""


async def get_products_notices_product_notice_id_info(
    product_notice_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    product_notice_id_to_int = int(product_notice_id)

    try:
        # 로그인한 사용자인 경우 user_id 조회
        user_id = None
        if kc_user_id:
            user_id = await comm_service.get_user_from_kc(kc_user_id, db)
            if user_id == -1:
                user_id = None

        # 로그인한 사용자: 본인이 작성한 공지(공개/비공개 모두) + 다른 사람의 공개 공지 조회
        # 비로그인 사용자: 공개된 공지만 조회
        if user_id:
            # 로그인 사용자: 본인 작성 공지는 모두 조회, 타인 작성 공지는 공개된 것만 조회
            query = text("""
                                select a.id
                                    , a.subject as title
                                    , a.content
                                    , a.open_yn
                                    , case when a.publish_reserve_date is null then 'N'
                                            else 'Y'
                                    end as reserve_yn
                                    , a.publish_reserve_date
                                from tb_product_notice a
                                where a.id = :product_notice_id
                                and a.use_yn = 'Y'
                                and (a.user_id = :user_id OR a.open_yn = 'Y')
                                """)

            result = await db.execute(
                query,
                {"user_id": user_id, "product_notice_id": product_notice_id_to_int},
            )
        else:
            # 비로그인 사용자: 공개된 공지만 조회
            query = text("""
                                select a.id
                                    , a.subject as title
                                    , a.content
                                    , a.open_yn
                                    , case when a.publish_reserve_date is null then 'N'
                                            else 'Y'
                                    end as reserve_yn
                                    , a.publish_reserve_date
                                from tb_product_notice a
                                where a.id = :product_notice_id
                                and a.use_yn = 'Y'
                                and a.open_yn = 'Y'
                                """)

            result = await db.execute(
                query,
                {"product_notice_id": product_notice_id_to_int},
            )

        db_rst = result.mappings().all()

        if db_rst:
            res_data = {
                "productNoticeId": product_notice_id_to_int,
                "title": db_rst[0].get("title"),
                "content": db_rst[0].get("content"),
                "openYn": db_rst[0].get("open_yn"),
                "publishReserveYn": db_rst[0].get("reserve_yn"),
                "publishReserveDate": db_rst[0].get("publish_reserve_date"),
            }
        else:
            # 공지를 찾을 수 없는 경우
            raise CustomResponseException(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ErrorMessages.NOT_FOUND_PRODUCT_NOTICE,
            )
    except CustomResponseException:
        raise
    except OperationalError:
        raise CustomResponseException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    except SQLAlchemyError:
        raise CustomResponseException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception:
        raise CustomResponseException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    res_body = {"data": res_data}

    return res_body


async def post_products_product_id_notices(
    product_id: str,
    req_body: product_schema.PostProductsProductIdNoticesReqBody,
    kc_user_id: str,
    db: AsyncSession,
    save: Optional[str] = None,
    product_notice_id: Optional[str] = None,
):
    res_data = {}
    product_id_to_int = int(product_id)
    product_notice_id_to_int = int(product_notice_id) if product_notice_id else None

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                # 본인이 등록한 작품인지 검증
                query = text("""
                                 select 1
                                   from tb_product
                                  where user_id = :user_id
                                    and product_id = :product_id
                                 """)

                result = await db.execute(
                    query, {"user_id": user_id, "product_id": product_id_to_int}
                )
                db_rst = result.mappings().all()

                if db_rst:
                    pass
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_PRODUCT_NOTICE_INFO,
                    )

                # 내용 글자수 검증
                try:
                    soup = BeautifulSoup(req_body.content, "html.parser")
                    text_content = soup.get_text(separator=" ", strip=True)  # 태그 제외
                except Exception:
                    # HTML이 아닌 일반 텍스트인 경우
                    text_content = req_body.content

                if len(text_content) > 20000:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.PRODUCT_NOTICE_LENGTH_EXCEEDED,
                    )

                # 저장 버튼 클릭시 공지목록에 비공개 공지로 등록
                if save == "Y":
                    open_yn = "N"
                elif save == "N":
                    open_yn = req_body.open_yn
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_PRODUCT_NOTICE_INFO,
                    )

                query = text("""
                                 select 1
                                   from tb_product_notice
                                  where id = :id
                                    and user_id = :user_id
                                 """)

                result = await db.execute(
                    query, {"user_id": user_id, "id": product_notice_id_to_int}
                )
                db_rst = result.mappings().all()

                if db_rst:
                    # upd
                    query = text("""
                                     update tb_product_notice a
                                        set a.subject = :subject
                                          , a.content = :content
                                          , a.publish_reserve_date = :publish_reserve_date
                                          , a.open_yn = :open_yn
                                          , a.updated_id = :user_id
                                      where a.id = :id
                                     """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "id": product_notice_id_to_int,
                            "subject": req_body.title,
                            "content": req_body.content,
                            "publish_reserve_date": convert_to_kor_time(
                                req_body.publish_reserve_date
                            )
                            if req_body.publish_reserve_yn == "Y"
                            else None,
                            "open_yn": open_yn,
                        },
                    )

                    res_data = {"productNoticeId": product_notice_id_to_int}
                else:
                    # ins
                    query = text("""
                                     insert into tb_product_notice (product_id, user_id, subject, content, publish_reserve_date, open_yn, created_id, updated_id)
                                     values (:product_id, :user_id, :subject, :content, :publish_reserve_date, :open_yn, :created_id, :updated_id)
                                     """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "product_id": product_id_to_int,
                            "subject": req_body.title,
                            "content": req_body.content,
                            "publish_reserve_date": convert_to_kor_time(
                                req_body.publish_reserve_date
                            )
                            if req_body.publish_reserve_yn == "Y"
                            else None,
                            "open_yn": open_yn,
                            "created_id": settings.DB_DML_DEFAULT_ID,
                            "updated_id": settings.DB_DML_DEFAULT_ID,
                        },
                    )

                    query = text("""
                                     select last_insert_id()
                                     """)

                    result = await db.execute(query)
                    new_product_notice_id = result.scalar()

                    res_data = {"productNoticeId": new_product_notice_id}
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


async def put_products_notices_product_notice_id(
    product_notice_id: str,
    req_body: product_schema.PutProductsNoticesProductNoticeIdReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    product_notice_id_to_int = int(product_notice_id)

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                # 본인이 등록한 작품인지 검증
                query = text("""
                                 select 1
                                   from tb_product a
                                  inner join tb_product_notice b on a.product_id = b.product_id
                                    and b.use_yn = 'Y'
                                    and b.id = :id
                                  where a.user_id = :user_id
                                 """)

                result = await db.execute(
                    query, {"user_id": user_id, "id": product_notice_id_to_int}
                )
                db_rst = result.mappings().all()

                if db_rst:
                    pass
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_PRODUCT_NOTICE_INFO,
                    )

                # 내용 글자수 검증
                try:
                    soup = BeautifulSoup(req_body.content, "html.parser")
                    text_content = soup.get_text(separator=" ", strip=True)  # 태그 제외
                except Exception:
                    # HTML이 아닌 일반 텍스트인 경우
                    text_content = req_body.content

                if len(text_content) > 20000:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.PRODUCT_NOTICE_LENGTH_EXCEEDED,
                    )

                query = text("""
                                 update tb_product_notice a
                                    set a.subject = :subject
                                      , a.content = :content
                                      , a.publish_reserve_date = :publish_reserve_date
                                      , a.open_yn = :open_yn
                                      , a.updated_id = :user_id
                                  where a.id = :id
                                 """)

                await db.execute(
                    query,
                    {
                        "user_id": user_id,
                        "id": product_notice_id_to_int,
                        "subject": req_body.title,
                        "content": req_body.content,
                        "publish_reserve_date": convert_to_kor_time(
                            req_body.publish_reserve_date
                        )
                        if req_body.publish_reserve_yn == "Y"
                        else None,
                        "open_yn": req_body.open_yn,
                    },
                )
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    return


async def put_products_notices_product_notice_id_open(
    product_notice_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    product_notice_id_to_int = int(product_notice_id)

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                query = text("""
                                 select open_yn
                                   from tb_product_notice
                                  where id = :id
                                    and use_yn = 'Y'
                                 """)

                result = await db.execute(query, {"id": product_notice_id_to_int})
                db_rst = result.mappings().all()

                if db_rst:
                    open_yn = db_rst[0].get("open_yn")

                    # 현재 값이 N이면 Y, Y면 N으로 전환
                    query = text("""
                                     update tb_product_notice a
                                        set a.open_yn = (case when a.open_yn = 'N' then 'Y' else 'N' end)
                                          , a.updated_id = :user_id
                                      where a.id = :id
                                        and a.use_yn = 'Y'
                                        and exists (select 1 from tb_product z
                                                     where a.product_id = z.product_id
                                                       and z.user_id = :user_id)
                                     """)

                    result = await db.execute(
                        query, {"id": product_notice_id_to_int, "user_id": user_id}
                    )

                    if open_yn == "N":
                        # N -> Y
                        notice_open_yn = "Y"
                    else:
                        # Y -> N
                        notice_open_yn = "N"

                    # upd된 경우만
                    if result.rowcount != 0:
                        res_data = {
                            "productNoticeId": product_notice_id_to_int,
                            "openYn": notice_open_yn,
                        }
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body
