import time
from app.services.common import statistics_service
from app.services.product.product_service import (
    _count_evaluations,
)
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from pathlib import Path
import re
import base64
import json
import hashlib
from Crypto.Cipher import AES

from app.const import CommonConstants, settings, ErrorMessages
from app.exceptions import CustomResponseException
from app.utils.time import get_full_age
import app.services.common.comm_service as comm_service
import app.schemas.user as user_schema

from httpx import AsyncClient
from datetime import datetime
import hmac

from app.config.log_config import service_error_logger
from app.const import LOGGER_TYPE
from app.utils.query import (
    get_file_path_sub_query,
    get_badge_image_sub_query,
    get_user_block_filter,
)
from app.utils.common import handle_exceptions

error_logger = service_error_logger(LOGGER_TYPE.LOGGER_INSTANCE_NAME_FOR_SERVICE_ERROR)

"""
users 도메인 개별 서비스 함수 모음
"""

# 로그 설정
logging.basicConfig(
    level=logging.INFO,  # 로그 수준: DEBUG, INFO, WARNING, ERROR, CRITICAL
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger("my_fastapi_app")  # 커스텀 로거 생성


@handle_exceptions
async def get_user(kc_user_id: str, db: AsyncSession):
    res_data = {}

    if kc_user_id:
        async with db.begin():
            query = text("""
                             select a.user_id
                                  , DATE_FORMAT(a.birthdate, '%Y-%m-%d') as birthdate
                                  , a.gender
                                  , a.latest_signed_type
                                  , b.role_type
                                  , (select apply_type from tb_user_profile_apply where user_id = a.user_id and approval_code = 'accepted' order by created_date desc limit 1) as apply_type
                               from tb_user a
                              inner join tb_user_profile b on a.user_id = b.user_id
                                and b.default_yn = 'Y'
                              where a.kc_user_id = :kc_user_id
                                and a.use_yn = 'Y'
                             """)
            # TODO: 내 정보 수정, 캐시 모듈 구현 후 수정 및 최종 테스트 필(현재 초안 개발 완료. 추가된 정보(본인인증여부, 이메일, 연동내용, 보유캐시) 활용하여 구현 필)
            # 추후 주석 제거하면서 아래 쿼리로 대체 요망
            # query = text("""
            #                 select a.user_id
            #                      , a.birthdate
            #                      , a.gender
            #                      , a.latest_signed_type
            #                      , b.role_type
            #                      , a.email
            #                      , coalesce(c.balance, 0) as balance
            #                      , (select json_arrayagg(z.sns_type) from tb_user_social z
            #                          where a.user_id = z.integrated_user_id) as sns_links
            #                   from tb_user a
            #                  inner join tb_user_profile b on a.user_id = b.user_id
            #                   left join tb_user_cashbook c on a.user_id = c.user_id
            #                  inner join tb_user_social d on a.user_id = d.user_id
            #                    and b.default_yn = 'Y'
            #                  where a.kc_user_id = :kc_user_id
            #                    and a.use_yn = 'Y'
            #                 """)

            result = await db.execute(query, {"kc_user_id": kc_user_id})
            db_rst = result.mappings().all()

            if db_rst:
                user_id = db_rst[0].get("user_id")
                birthdate = db_rst[0].get("birthdate")
                gender = db_rst[0].get("gender")
                recent_signin_type = db_rst[0].get("latest_signed_type")
                role_type = db_rst[0].get("role_type")
                apply_type = db_rst[0].get("apply_type")

                # check_user 함수 로직 참고하여 role 결정
                if role_type == "admin":
                    user_role = "admin"
                elif apply_type == "cp":
                    user_role = "CP"
                elif apply_type == "editor":
                    user_role = "editor"
                else:
                    user_role = role_type

                adult_yn = (
                    "Y" if get_full_age(date=db_rst[0].get("birthdate")) >= 19 else "N"
                )
                # TODO: 내 정보 수정, 캐시 모듈 구현 후 수정 및 최종 테스트 필(현재 초안 개발 완료. 추가된 정보(본인인증여부, 이메일, 연동내용, 보유캐시) 활용하여 구현 필)
                # 추후 주석 제거 요망
                # email = db_rst[0].get("email")
                # balance = db_rst[0].get("balance")
                # sns_links = json.loads(db_rst[0].get("sns_links"))

                query = text("""
                                 select 1
                                   from tb_user
                                  where kc_user_id = :kc_user_id
                                    and use_yn = 'Y'
                                 """)

                result = await db.execute(query, {"kc_user_id": kc_user_id})
                db_rst = result.mappings().all()

                if db_rst:
                    identity_yn = "Y"
                else:
                    identity_yn = "N"

                res_data = {
                    "userId": user_id,
                    "birthDate": birthdate,
                    "gender": gender,
                    "recentSignInType": recent_signin_type,
                    "adultToggleDisplayYn": "Y"
                    if identity_yn == "Y" and adult_yn == "Y"
                    else "N",
                    "userRole": user_role,
                    # TODO: 내 정보 수정, 캐시 모듈 구현 후 수정 및 최종 테스트 필(현재 초안 개발 완료. 추가된 정보(본인인증여부, 이메일, 연동내용, 보유캐시) 활용하여 구현 필)
                    # 추후 주석 제거 요망
                    # "identityYn": identity_yn,
                    # "email": email,
                    # "snsLinks": sns_links,
                    # "totalCash": balance
                }
    else:
        pass

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def get_user_info(kc_user_id: str, db: AsyncSession):
    res_data = {}

    if kc_user_id:
        async with db.begin():
            user_id = await comm_service.get_user_from_kc(kc_user_id, db)

            query = text(f"""
                             select c.profile_id
                                  , DATE_FORMAT(a.birthdate, '%Y-%m-%d') as birthdate
                                  , {get_file_path_sub_query("c.profile_image_id", "profile_image_path", "user")}
                                  , c.nickname
                                  , {get_badge_image_sub_query("a.user_id", "interest", "user_interest_level_badge_image_path", "c.profile_id")}
                                  , {get_badge_image_sub_query("a.user_id", "event", "user_event_level_badge_image_path", "c.profile_id")}
                                  , c.role_type
                                  , (select apply_type from tb_user_profile_apply where user_id = a.user_id and approval_code = 'accepted' order by created_date desc limit 1) as apply_type
                                  , (select approval_code from tb_user_profile_apply where user_id = a.user_id and approval_code in ('review', 'accepted') order by created_date desc limit 1) as apply_status
                                  , a.identity_yn
                                  , a.email
                                  , d.default_yn
                                  , (select sum(balance) from tb_user_cashbook b where a.user_id = b.user_id) as balance
                                  , coalesce((select count(1) from tb_user_productbook z
                                               where z.user_id = a.user_id
                                                 and (z.own_type = 'rental' OR z.acquisition_type = 'gift')
                                                 and z.use_yn = 'N'), 0) as ticket
                                  , coalesce((select count(1) from tb_user_product_usage z, tb_product y
                                  	           where z.product_id = y.product_id
                                                 and a.user_id = z.user_id
                                                 and y.price_type = 'free'
                                                 and z.use_yn = 'Y'
                                  		         and z.updated_date > date_sub(now(), interval 3 day)), 0) as interest_count
                                  , coalesce((select count(1) from tb_event_vote_winner z
                                               where z.user_id = a.user_id
                                                 and z.use_yn = 'Y'), 0) as vote_win
                                  , coalesce((select max(round_no) from tb_event_vote_round z
                                               where z.use_yn = 'Y'), 0) as vote_round
                                  , coalesce((select count(distinct z.product_id) from tb_user_product_usage z
                                  	           where a.user_id = z.user_id
                                                 and z.use_yn = 'Y'), 0) as read_count
                                  , coalesce((select count(1) from tb_product z
                                               where a.user_id = z.user_id), 0) as product_count
                               from tb_user a
                              inner join tb_user_profile c on a.user_id = c.user_id
                                and c.default_yn = 'Y'
                              inner join tb_user_social d on a.user_id = d.user_id
                              where a.user_id = :user_id
                             """)

            result = await db.execute(query, {"user_id": user_id})
            db_rst = result.mappings().all()

            if db_rst:
                # get_user 함수 로직과 동일하게 role 결정
                role_type = db_rst[0].get("role_type")
                apply_type = db_rst[0].get("apply_type")
                apply_status = db_rst[0].get("apply_status")

                if role_type == "admin":
                    user_role = "admin"
                elif apply_type == "cp":
                    user_role = "CP"
                elif apply_type == "editor":
                    user_role = "editor"
                else:
                    user_role = role_type

                # CP 또는 편집자 신청/승인 여부 확인
                # apply_status가 'review' 또는 'accepted'이면 "Y", 그 외(rejected, null)는 "N"
                apply_cp_editor_yn = (
                    "Y" if apply_status in ["review", "accepted"] else "N"
                )

                res_data = {
                    "profileId": db_rst[0].get("profile_id"),
                    "birthDate": db_rst[0].get("birthdate"),
                    "userProfileImagePath": db_rst[0].get("profile_image_path"),
                    "userNickname": db_rst[0].get("nickname"),
                    "userInterestLevelBadgeImagePath": db_rst[0].get(
                        "user_interest_level_badge_image_path"
                    ),
                    "userEventLevelBadgeImagePath": db_rst[0].get(
                        "user_event_level_badge_image_path"
                    ),
                    "userRole": user_role,
                    "identityYn": db_rst[0].get("identity_yn"),
                    "email": db_rst[0].get("email"),
                    "totalCash": db_rst[0].get("balance"),
                    "totalTicket": db_rst[0].get("ticket"),
                    "totalInterestSustainCount": db_rst[0].get("interest_count"),
                    "totalVoteWinCount": db_rst[0].get("vote_win"),
                    "totalVoteRound": db_rst[0].get("vote_round"),
                    "totalReadProductCount": db_rst[0].get("read_count"),
                    "totalWrittenProductCount": db_rst[0].get("product_count"),
                    "isAuthor": "Y" if db_rst[0].get("product_count") > 0 else "N",
                    "isIdentityVerified": db_rst[0].get("default_yn"),
                    "applyCPEditorYN": apply_cp_editor_yn,
                }
    else:
        pass

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def get_user_attachment_upload_file_name(
    file_name: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}

    if kc_user_id:
        file_path = Path(file_name)
        ext = file_path.suffix.lower()

        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 랜덤 생성 uuid 중복 체크
        while True:
            file_name_to_uuid = comm_service.make_rand_uuid()
            file_name_to_uuid = f"{file_name_to_uuid}{ext}"

            query = text("""
                                select a.file_group_id
                                from tb_common_file a
                                inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                and b.use_yn = 'Y'
                                and b.file_name = :file_name
                                where a.group_type = 'attachment'
                                and a.use_yn = 'Y'
                            """)

            result = await db.execute(query, {"file_name": file_name_to_uuid})
            db_rst = result.mappings().all()

            if not db_rst:
                break

        presigned_url = comm_service.make_r2_presigned_url(
            type="upload",
            bucket_name=settings.R2_SC_ATTACHMENT_BUCKET,
            file_id=file_name_to_uuid,
        )

        query = text("""
                            insert into tb_common_file (group_type, created_id, updated_id)
                            values (:group_type, :created_id, :updated_id)
                            """)

        await db.execute(
            query,
            {
                "group_type": "attachment",
                "created_id": settings.DB_DML_DEFAULT_ID,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        query = text("""
                            select last_insert_id()
                            """)

        result = await db.execute(query)
        new_file_group_id = result.scalar()

        query = text("""
                            insert into tb_common_file_item (file_group_id, file_name, file_org_name, file_path, created_id, updated_id)
                            values (:file_group_id, :file_name, :file_org_name, :file_path, :created_id, :updated_id)
                            """)

        await db.execute(
            query,
            {
                "file_group_id": new_file_group_id,
                "file_name": file_name_to_uuid,
                "file_org_name": file_name,
                "file_path": f"{settings.R2_SC_DOMAIN}/attachment/{file_name_to_uuid}",
                "created_id": settings.DB_DML_DEFAULT_ID,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        res_data = {
            "attachmentFileId": new_file_group_id,
            "attachmentUploadPath": presigned_url,
        }
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def get_user_profiles_upload_file_name(
    file_name: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}

    if kc_user_id:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 랜덤 생성 uuid 중복 체크
        while True:
            file_name_to_uuid = comm_service.make_rand_uuid()
            file_name_to_uuid = f"{file_name_to_uuid}.webp"

            query = text("""
                                select a.file_group_id
                                from tb_common_file a
                                inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                and b.use_yn = 'Y'
                                and b.file_name = :file_name
                                where a.group_type = 'user'
                                and a.use_yn = 'Y'
                            """)

            result = await db.execute(query, {"file_name": file_name_to_uuid})
            db_rst = result.mappings().all()

            if not db_rst:
                break

        presigned_url = comm_service.make_r2_presigned_url(
            type="upload",
            bucket_name=settings.R2_SC_IMAGE_BUCKET,
            file_id=f"user/{file_name_to_uuid}",
        )

        query = text("""
                            insert into tb_common_file (group_type, created_id, updated_id)
                            values (:group_type, :created_id, :updated_id)
                            """)

        await db.execute(
            query,
            {
                "group_type": "user",
                "created_id": settings.DB_DML_DEFAULT_ID,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        query = text("""
                            select last_insert_id()
                            """)

        result = await db.execute(query)
        new_file_group_id = result.scalar()

        query = text("""
                            insert into tb_common_file_item (file_group_id, file_name, file_org_name, file_path, created_id, updated_id)
                            values (:file_group_id, :file_name, :file_org_name, :file_path, :created_id, :updated_id)
                            """)

        await db.execute(
            query,
            {
                "file_group_id": new_file_group_id,
                "file_name": file_name_to_uuid,
                "file_org_name": file_name,
                "file_path": f"{settings.R2_SC_CDN_URL}/user/{file_name_to_uuid}",
                "created_id": settings.DB_DML_DEFAULT_ID,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        res_data = {
            "profileImageFileId": new_file_group_id,
            "profileImageUploadPath": presigned_url,
        }
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def get_user_profiles(kc_user_id: str, db: AsyncSession):
    res_data = list()

    if kc_user_id:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text(f"""
                            select a.profile_id
                                , {get_file_path_sub_query("a.profile_image_id", "user_profile_image_path", "user")}
                                , a.nickname as user_nickname
                                , {get_badge_image_sub_query("a.user_id", "interest", "user_interest_level_badge_image_path", "a.profile_id")}
                                , {get_badge_image_sub_query("a.user_id", "event", "user_event_level_badge_image_path", "a.profile_id")}
                                , a.role_type as user_role
                                , a.default_yn
                                , a.nickname_change_count as nickname_changeable_count
                            from tb_user_profile a
                            where a.user_id = :user_id
                            """)

        result = await db.execute(query, {"user_id": user_id})
        db_rst = result.mappings().all()

        if db_rst:
            res_data = [user_schema.GetUserProfilesToCamel(**row) for row in db_rst]
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def get_user_profiles_profile_id_info(
    profile_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    profile_id_to_int = int(profile_id)

    if kc_user_id:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text(f"""
                            with tmp_get_user_profiles_profile_id_info as (
                                select x.badge_id
                                    , x.badge_type
                                    , y.file_path
                                    , x.display_yn
                                from tb_common_file z, tb_common_file_item y, tb_user_badge x
                                where z.file_group_id = y.file_group_id
                                and z.use_yn = 'Y'
                                and y.use_yn = 'Y'
                                and z.group_type = 'badge'
                                and x.badge_image_id = z.file_group_id
                                and x.use_yn = 'Y'
                                and x.user_id = :user_id
                                and x.profile_id = :profile_id
                            )
                            select a.profile_id
                                , {get_file_path_sub_query("a.profile_image_id", "user_profile_image_path", "user")}
                                , a.nickname as user_nickname
                                , a.role_type as user_role
                                , a.default_yn
                                , a.nickname_change_count as nickname_changeable_count
                                , (select badge_id from tmp_get_user_profiles_profile_id_info
                                    where badge_type = 'interest'
                                    and display_yn = 'Y') as selected_interest_badge
                                , (select json_objectagg(badge_id, file_path) from tmp_get_user_profiles_profile_id_info
                                    where badge_type = 'interest') as interest_badge_list
                                , (select badge_id from tmp_get_user_profiles_profile_id_info
                                    where badge_type = 'event'
                                    and display_yn = 'Y') as selected_event_badge
                                , (select json_objectagg(badge_id, file_path) from tmp_get_user_profiles_profile_id_info
                                    where badge_type = 'event') as event_badge_list
                            from tb_user_profile a
                            where a.profile_id = :profile_id
                            """)

        result = await db.execute(
            query, {"user_id": user_id, "profile_id": profile_id_to_int}
        )
        db_rst = result.mappings().all()

        if db_rst:
            res_data = {
                "profileId": db_rst[0].get("profile_id"),
                "userProfileImagePath": db_rst[0].get("user_profile_image_path"),
                "userNickname": db_rst[0].get("user_nickname"),
                "userRole": db_rst[0].get("user_role"),
                "defaultYn": db_rst[0].get("default_yn"),
                "nicknameChangeableCount": db_rst[0].get("nickname_changeable_count"),
                "selectedUserInterestBadgeId": db_rst[0].get("selected_interest_badge"),
                "userInterestLevelBadgeImagePaths": json.loads(
                    db_rst[0].get("interest_badge_list")
                ),
                "selectedUserEventBadgeId": db_rst[0].get("selected_event_badge"),
                "userEventLevelBadgeImagePaths": json.loads(
                    db_rst[0].get("event_badge_list")
                ),
            }
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def get_user_cash(kc_user_id: str, db: AsyncSession):
    res_data = list()

    if kc_user_id:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text("""
                            select t.*
                            from (
                                select case when a.amount > 0 then 'charge' else 'use' end as category
                                    , a.amount
                                    , null as product_title
                                    , null as episode_title
                                    , a.created_date
                                from tb_user_cashbook_transaction a
                                where a.from_user_id = :user_id
                                and a.use_yn = 'Y'
                                union all
                                select 'used' as category
                                    , a.item_price * a.quantity as amount
                                    , (select z.title from tb_product z
                                        where z.product_id = c.product_id) as product_title
                                    , (select concat(z.episode_no, '화. ', z.episode_title) from tb_product_episode z
                                        where z.episode_id = c.episode_id) as episode_title
                                    , c.created_date
                                from tb_product_order_item a
                                inner join tb_product_order b on a.order_id = b.order_id
                                and b.user_id = :user_id
                                inner join tb_product_order_item_info c on a.item_id = c.item_info_id
                                where a.cancel_yn = 'N'
                            ) t
                            order by t.created_date desc
                            """)

        result = await db.execute(query, {"user_id": user_id})
        db_rst = result.mappings().all()

        if db_rst:
            res_data = [user_schema.GetUserCashToCamel(**row) for row in db_rst]
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def get_user_cash_balance(kc_user_id: str, db: AsyncSession):
    """
    사용자 캐시 잔액 조회
    """
    if kc_user_id:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text("""
            SELECT COALESCE(SUM(balance), 0) AS balance
            FROM tb_user_cashbook
            WHERE user_id = :user_id
        """)
        result = await db.execute(query, {"user_id": user_id})
        cashbook_row = result.mappings().one_or_none()

        balance = cashbook_row["balance"] if cashbook_row else 0

    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    return {"data": {"balance": balance}}


@handle_exceptions
async def get_user_comments(kc_user_id: str, db: AsyncSession):
    res_data = list()

    if kc_user_id:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 에피소드 댓글 조회
        episode_comments_query = text(f"""
                            with tmp_get_user_comments_1 as (
                                    select comment_id
                                        , recommend_yn as recommend_yn
                                        , not_recommend_yn as not_recommend_yn
                                    from tb_user_product_comment_recommend
                                    where user_id = :user_id
                                    and use_yn = 'Y'
                                )
                                select a.comment_id
                                    , a.user_id
                                    , b.nickname as user_nickname
                                    , {get_file_path_sub_query("b.profile_image_id", "user_profile_image_path", "user")}
                                    , {get_badge_image_sub_query("a.user_id", "interest", "user_interest_level_badge_image_path", "a.profile_id")}
                                    , {get_badge_image_sub_query("a.user_id", "event", "user_event_level_badge_image_path", "a.profile_id")}
                                    , a.content
                                    , a.created_date as publish_date
                                    , a.count_recommend as recommend_count
                                    , a.count_not_recommend as not_recommend_count
                                    , coalesce(d.recommend_yn, 'N') as recommend_yn
                                    , coalesce(d.not_recommend_yn, 'N') as not_recommend_yn
                                    , b.role_type as user_role
                                    , concat('댓글 회차 : ', c.episode_no, '화. ', c.episode_title) as comment_episode
                                    , null as review_title
                                    , e.title as product_title
                                    , 'episode' as comment_type
                                from tb_product_comment a
                                inner join tb_user_profile b on a.user_id = b.user_id
                                and a.profile_id = b.profile_id
                                inner join tb_product_episode c on a.episode_id = c.episode_id
                                and c.use_yn = 'Y'
                                inner join tb_product e on c.product_id = e.product_id
                                and e.open_yn = 'Y'
                                left join tmp_get_user_comments_1 d on a.comment_id = d.comment_id
                                where a.user_id = :user_id
                                and a.use_yn = 'Y'
                                {get_user_block_filter("a.user_id", "a.comment_id")}
                            """)

        episode_result = await db.execute(episode_comments_query, {"user_id": user_id})
        episode_comments = episode_result.mappings().all()

        # 리뷰 댓글 조회
        review_comments_query = text(f"""
                                select a.id as comment_id
                                    , a.user_id
                                    , b.nickname as user_nickname
                                    , {get_file_path_sub_query("b.profile_image_id", "user_profile_image_path", "user")}
                                    , {get_badge_image_sub_query("a.user_id", "interest", "user_interest_level_badge_image_path", "b.profile_id")}
                                    , {get_badge_image_sub_query("a.user_id", "event", "user_event_level_badge_image_path", "b.profile_id")}
                                    , a.comment_text as content
                                    , a.created_date as publish_date
                                    , 0 as recommend_count
                                    , 0 as not_recommend_count
                                    , 'N' as recommend_yn
                                    , 'N' as not_recommend_yn
                                    , b.role_type as user_role
                                    , null as comment_episode
                                    , c.review_title as review_title
                                    , d.title as product_title
                                    , 'review' as comment_type
                                from tb_product_review_comment a
                                inner join tb_user_profile b on a.user_id = b.user_id
                                and b.default_yn = 'Y'
                                inner join tb_product_review c on a.review_id = c.id
                                and c.open_yn = 'Y'
                                inner join tb_product d on c.product_id = d.product_id
                                and d.open_yn = 'Y'
                                where a.user_id = :user_id
                            """)

        review_result = await db.execute(review_comments_query, {"user_id": user_id})
        review_comments = review_result.mappings().all()

        # 두 결과를 합치고 날짜순으로 정렬
        all_comments = list(episode_comments) + list(review_comments)
        all_comments.sort(key=lambda x: x["publish_date"], reverse=True)

        if all_comments:
            res_data = [
                user_schema.GetUserCommentsToCamel(**row) for row in all_comments
            ]
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def get_user_comments_block(kc_user_id: str, db: AsyncSession):
    res_data = list()

    if kc_user_id:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 에피소드 댓글 차단 목록 조회 (episode_id != null && comment_id != null && review_id == null)
        episode_block_query = text(f"""
                            select a.comment_id
                                , a.off_user_id as user_id
                                , c.nickname as user_nickname
                                , {get_file_path_sub_query("c.profile_image_id", "user_profile_image_path", "user")}
                                , {get_badge_image_sub_query("a.off_user_id", "interest", "user_interest_level_badge_image_path", "c.profile_id")}
                                , {get_badge_image_sub_query("a.off_user_id", "event", "user_event_level_badge_image_path", "c.profile_id")}
                                , a.created_date as publish_date
                                , 'episode' as comment_type
                            from tb_user_block a
                            inner join tb_product_comment b on a.comment_id = b.comment_id
                            inner join tb_user_profile c on a.off_user_id = c.user_id
                            and b.profile_id = c.profile_id
                            where a.user_id = :user_id
                            and a.use_yn = 'Y'
                            and a.off_yn = 'Y'
                            and a.episode_id is not null
                            and a.comment_id is not null
                            and a.review_id is null
                            """)

        episode_result = await db.execute(episode_block_query, {"user_id": user_id})
        episode_blocks = episode_result.mappings().all()

        # 리뷰 댓글 차단 목록 조회 (review_id != null && comment_id != null)
        review_block_query = text(f"""
                            select a.comment_id
                                , a.off_user_id as user_id
                                , c.nickname as user_nickname
                                , {get_file_path_sub_query("c.profile_image_id", "user_profile_image_path", "user")}
                                , {get_badge_image_sub_query("a.off_user_id", "interest", "user_interest_level_badge_image_path", "c.profile_id")}
                                , {get_badge_image_sub_query("a.off_user_id", "event", "user_event_level_badge_image_path", "c.profile_id")}
                                , a.created_date as publish_date
                                , 'review' as comment_type
                            from tb_user_block a
                            inner join tb_product_review_comment b on a.comment_id = b.id
                            inner join tb_user_profile c on a.off_user_id = c.user_id
                            and c.default_yn = 'Y'
                            where a.user_id = :user_id
                            and a.use_yn = 'Y'
                            and a.off_yn = 'Y'
                            and a.review_id is not null
                            and a.comment_id is not null
                            """)

        review_result = await db.execute(review_block_query, {"user_id": user_id})
        review_blocks = review_result.mappings().all()

        # 작품 리뷰 차단 목록 조회 (review_id != null && comment_id == null)
        product_review_block_query = text(f"""
                            select a.review_id
                                , a.off_user_id as user_id
                                , c.nickname as user_nickname
                                , {get_file_path_sub_query("c.profile_image_id", "user_profile_image_path", "user")}
                                , {get_badge_image_sub_query("a.off_user_id", "interest", "user_interest_level_badge_image_path", "c.profile_id")}
                                , {get_badge_image_sub_query("a.off_user_id", "event", "user_event_level_badge_image_path", "c.profile_id")}
                                , a.created_date as publish_date
                                , 'product_review' as comment_type
                            from tb_user_block a
                            inner join tb_product_review b on a.review_id = b.id
                            inner join tb_user_profile c on a.off_user_id = c.user_id
                            and c.default_yn = 'Y'
                            where a.user_id = :user_id
                            and a.use_yn = 'Y'
                            and a.off_yn = 'Y'
                            and a.review_id is not null
                            and a.comment_id is null
                            """)

        product_review_result = await db.execute(
            product_review_block_query, {"user_id": user_id}
        )
        product_review_blocks = product_review_result.mappings().all()

        # 세 결과를 합치고 날짜순으로 정렬
        all_blocks = (
            list(episode_blocks) + list(review_blocks) + list(product_review_blocks)
        )
        all_blocks.sort(key=lambda x: x["publish_date"], reverse=True)

        if all_blocks:
            res_data = [
                user_schema.GetUserCommentsBlockToCamel(**row) for row in all_blocks
            ]
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def post_user_apply_role(
    req_body: user_schema.PostUserApplyRoleReqBody, kc_user_id: str, db: AsyncSession
):
    res_data = {}

    if kc_user_id:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 신청구분 검증
        query = text("""
                            select 1
                            from tb_common_code
                            where code_group = 'PRFL_ROLE_CODE'
                            and code_key = :code_key
                            and code_key not in ('user', 'author', 'enter')
                            and use_yn = 'Y'
                            """)

        result = await db.execute(query, {"code_key": req_body.apply_type})
        db_rst = result.mappings().all()

        if db_rst:
            pass
        else:
            raise CustomResponseException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                message=ErrorMessages.INVALID_APPLY_ROLE_INFO,
            )

        # 권한 부여 상태 체크
        query = text("""
                            select 1
                            from tb_user_profile
                            where user_id = :user_id
                            and role_type = :code_key
                            """)

        result = await db.execute(
            query, {"user_id": user_id, "code_key": req_body.apply_type}
        )
        db_rst = result.mappings().all()

        if db_rst:
            # 이미 권한이 부여된 상태
            res_data = {"applyCPEditorYN": "Y"}
        else:
            # 기등록 상태 체크
            query = text("""
                                select 1
                                from tb_user_profile_apply a
                                where a.user_id = :user_id
                                and a.approval_code = 'review'
                                """)

            result = await db.execute(query, {"user_id": user_id})
            db_rst = result.mappings().all()

            if db_rst:
                raise CustomResponseException(
                    status_code=status.HTTP_409_CONFLICT,
                    message=ErrorMessages.ALREADY_APPLIED_STATE,
                )
            else:
                query = text("""
                                select 1 from tb_user_profile_apply a where a.company_name = :company_name
                                """)
                result = await db.execute(
                    query, {"company_name": req_body.company_name}
                )
                db_rst = result.mappings().all()
                if db_rst:
                    raise CustomResponseException(
                        status_code=status.HTTP_409_CONFLICT,
                        message=ErrorMessages.ALREADY_EXIST_COMPANY,
                    )
                else:
                    query = text("""
                                    insert into tb_user_profile_apply (user_id, apply_type, company_name, email, attach_file_id_1st, attach_file_id_2nd, approval_code, created_id, updated_id)
                                    values (:user_id, :apply_type, :company_name, :email, :attach_file_id_1st, :attach_file_id_2nd, :approval_code, :created_id, :updated_id)
                                    """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "apply_type": req_body.apply_type,
                            "company_name": req_body.company_name,
                            "email": req_body.email,
                            "attach_file_id_1st": req_body.attachment_file_id_1st,
                            "attach_file_id_2nd": req_body.attachment_file_id_2nd
                            if req_body.attachment_file_id_2nd != ""
                            else None,
                            "approval_code": "review",
                            "created_id": settings.DB_DML_DEFAULT_ID,
                            "updated_id": settings.DB_DML_DEFAULT_ID,
                        },
                    )

            res_data = {"applyRoleYn": "Y", "applyCPEditorYN": "N"}
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def post_user_profiles(
    req_body: user_schema.PostUserProfilesReqBody, kc_user_id: str, db: AsyncSession
):
    if kc_user_id:
        async with db.begin():
            user_id, userInfo = await comm_service.get_user_from_kc(
                kc_user_id, db, ["email"]
            )
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )
            email = userInfo["email"]

            # 프로필 수 검증(일반 최대 2개)
            query = text("""
                             select user_id
                               from tb_user_profile
                              where user_id = :user_id
                                and role_type = 'user'
                              group by user_id
                              having count(1) < 2
                             """)

            result = await db.execute(query, {"user_id": user_id})
            db_rst = result.mappings().all()

            if db_rst:
                # 닉네임 검증
                nickname = req_body.user_nickname
                pattern = r"^[가-힣a-zA-Z0-9]+$"  # 한글, 영문, 숫자만

                if (
                    re.match(pattern, nickname) is None
                    or nickname == email.split("@")[0]
                ):
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_PROFILE_INFO,
                    )

                query = text("""
                                 insert into tb_user_profile (user_id, nickname, default_yn, role_type, profile_image_id, created_id, updated_id)
                                 values (:user_id, :nickname, :default_yn, :role_type, :profile_image_id, :created_id, :updated_id)
                                 """)

                await db.execute(
                    query,
                    {
                        "user_id": user_id,
                        "nickname": nickname,
                        "default_yn": req_body.default_yn,
                        "role_type": "user",
                        "profile_image_id": req_body.profile_image_file_id
                        if req_body.profile_image_file_id
                        else settings.R2_PROFILE_DEFAULT_IMAGE,  # 기본 표지처럼 pk로 변경 필**
                        "created_id": settings.DB_DML_DEFAULT_ID,
                        "updated_id": settings.DB_DML_DEFAULT_ID,
                    },
                )

                query = text("""
                                 select last_insert_id()
                                 """)

                result = await db.execute(query)
                new_profile_id = result.scalar()

                query = text("""
                                 insert into tb_user_badge (profile_id, user_id, badge_type, badge_image_id, display_yn, created_id, updated_id)
                                 values (:profile_id, :user_id, :badge_type, :badge_image_id, :display_yn, :created_id, :updated_id)
                                 """)

                ins_datas = [
                    {
                        "profile_id": new_profile_id,
                        "user_id": user_id,
                        "badge_type": "interest",
                        "badge_image_id": settings.R2_INTEREST_BADGE_DEFAULT_IMAGE,
                        "display_yn": "Y" if req_body.interest_badge_yn == "Y" else "N",
                        "created_id": settings.DB_DML_DEFAULT_ID,
                        "updated_id": settings.DB_DML_DEFAULT_ID,
                    },
                    {
                        "profile_id": new_profile_id,
                        "user_id": user_id,
                        "badge_type": "event",
                        "badge_image_id": settings.R2_EVENT_BADGE_DEFAULT_IMAGE,
                        "display_yn": "Y" if req_body.event_badge_yn == "Y" else "N",
                        "created_id": settings.DB_DML_DEFAULT_ID,
                        "updated_id": settings.DB_DML_DEFAULT_ID,
                    },
                ]

                await db.execute(query, ins_datas)

                # 현재 프로필을 대표 프로필로(나머지는 n처리)
                if req_body.default_yn == "Y":
                    query = text("""
                                     update tb_user_profile
                                        set default_yn = 'N'
                                          , updated_id = :user_id
                                      where user_id = :user_id
                                        and profile_id != :profile_id
                                     """)

                    await db.execute(
                        query, {"user_id": user_id, "profile_id": new_profile_id}
                    )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    return


@handle_exceptions
async def put_user_profiles_profile_id(
    profile_id: str,
    req_body: user_schema.PutUserProfilesProfileIdReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    profile_id_to_int = int(profile_id)

    if kc_user_id:
        async with db.begin():
            user_id, userInfo = await comm_service.get_user_from_kc(
                kc_user_id, db, ["email"]
            )
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )
            email = userInfo["email"]

            if req_body.user_nickname is not None:
                # 닉네임 검증
                nickname = req_body.user_nickname
                pattern = r"^[가-힣a-zA-Z0-9]+$"  # 한글, 영문, 숫자만

                if (
                    re.match(pattern, nickname) is None
                    or nickname == email.split("@")[0]
                ):
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_PROFILE_INFO,
                    )

                query = text("""
                                select nickname
                                    , nickname_change_count
                                    , paid_change_count
                                from tb_user_profile
                                where user_id = :user_id
                                    and profile_id = :profile_id
                                """)

                result = await db.execute(
                    query, {"user_id": user_id, "profile_id": profile_id_to_int}
                )
                db_rst = result.mappings().all()

                bef_nickname = db_rst[0].get("nickname")

                nickname_change_count_down = "N"
                paid_change_count_down = "N"
                if bef_nickname != nickname:
                    # 무료 변경 횟수와 유료 변경 횟수 모두 체크
                    free_count = db_rst[0].get("nickname_change_count")
                    paid_count = db_rst[0].get("paid_change_count")

                    if free_count == 0 and paid_count == 0:
                        raise CustomResponseException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            message=ErrorMessages.NICKNAME_CHANGE_COUNT_EXHAUSTED,
                        )
                    elif free_count > 0:
                        # 무료 횟수 먼저 차감
                        nickname_change_count_down = "Y"
                    else:
                        # 유료 횟수 차감
                        paid_change_count_down = "Y"

                if nickname_change_count_down == "N":
                    if req_body.default_yn is not None:
                        query = text("""
                                        update tb_user_profile
                                            set nickname = :nickname
                                            , default_yn = :default_yn
                                            , profile_image_id = :profile_image_id
                                            , updated_id = :user_id
                                        where profile_id = :profile_id
                                        """)

                        await db.execute(
                            query,
                            {
                                "user_id": user_id,
                                "profile_id": profile_id_to_int,
                                "nickname": nickname,
                                "default_yn": req_body.default_yn,
                                "profile_image_id": req_body.profile_image_file_id
                                if req_body.profile_image_file_id
                                else settings.R2_PROFILE_DEFAULT_IMAGE,
                            },
                        )
                    else:
                        query = text("""
                                        update tb_user_profile
                                            set nickname = :nickname
                                            , profile_image_id = :profile_image_id
                                            , updated_id = :user_id
                                        where profile_id = :profile_id
                                        """)

                        await db.execute(
                            query,
                            {
                                "user_id": user_id,
                                "profile_id": profile_id_to_int,
                                "nickname": nickname,
                                "profile_image_id": req_body.profile_image_file_id
                                if req_body.profile_image_file_id
                                else settings.R2_PROFILE_DEFAULT_IMAGE,
                            },
                        )
                elif nickname_change_count_down == "Y":
                    # 무료 횟수 차감
                    if req_body.default_yn is not None:
                        query = text("""
                                        update tb_user_profile
                                            set nickname = :nickname
                                            , default_yn = :default_yn
                                            , profile_image_id = :profile_image_id
                                            , nickname_change_count = nickname_change_count - 1
                                            , updated_id = :user_id
                                        where profile_id = :profile_id
                                        """)

                        await db.execute(
                            query,
                            {
                                "user_id": user_id,
                                "profile_id": profile_id_to_int,
                                "nickname": nickname,
                                "default_yn": req_body.default_yn,
                                "profile_image_id": req_body.profile_image_file_id
                                if req_body.profile_image_file_id
                                else settings.R2_PROFILE_DEFAULT_IMAGE,
                            },
                        )
                    else:
                        query = text("""
                                        update tb_user_profile
                                            set nickname = :nickname
                                            , profile_image_id = :profile_image_id
                                            , nickname_change_count = nickname_change_count - 1
                                            , updated_id = :user_id
                                        where profile_id = :profile_id
                                        """)

                        await db.execute(
                            query,
                            {
                                "user_id": user_id,
                                "profile_id": profile_id_to_int,
                                "nickname": nickname,
                                "profile_image_id": req_body.profile_image_file_id
                                if req_body.profile_image_file_id
                                else settings.R2_PROFILE_DEFAULT_IMAGE,
                            },
                        )

                    query = text("""
                                    update tb_product
                                        set author_name = :nickname
                                        , updated_id = :user_id
                                    where author_id = :user_id
                                        and author_name = :bef_nickname
                                    """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "nickname": nickname,
                            "bef_nickname": bef_nickname,
                        },
                    )
                elif paid_change_count_down == "Y":
                    # 유료 횟수 차감
                    if req_body.default_yn is not None:
                        query = text("""
                                        update tb_user_profile
                                            set nickname = :nickname
                                            , default_yn = :default_yn
                                            , profile_image_id = :profile_image_id
                                            , paid_change_count = paid_change_count - 1
                                            , updated_id = :user_id
                                        where profile_id = :profile_id
                                        """)

                        await db.execute(
                            query,
                            {
                                "user_id": user_id,
                                "profile_id": profile_id_to_int,
                                "nickname": nickname,
                                "default_yn": req_body.default_yn,
                                "profile_image_id": req_body.profile_image_file_id
                                if req_body.profile_image_file_id
                                else settings.R2_PROFILE_DEFAULT_IMAGE,
                            },
                        )
                    else:
                        query = text("""
                                        update tb_user_profile
                                            set nickname = :nickname
                                            , profile_image_id = :profile_image_id
                                            , paid_change_count = paid_change_count - 1
                                            , updated_id = :user_id
                                        where profile_id = :profile_id
                                        """)

                        await db.execute(
                            query,
                            {
                                "user_id": user_id,
                                "profile_id": profile_id_to_int,
                                "nickname": nickname,
                                "profile_image_id": req_body.profile_image_file_id
                                if req_body.profile_image_file_id
                                else settings.R2_PROFILE_DEFAULT_IMAGE,
                            },
                        )

                    query = text("""
                                    update tb_product
                                        set author_name = :nickname
                                        , updated_id = :user_id
                                    where author_id = :user_id
                                        and author_name = :bef_nickname
                                    """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "nickname": nickname,
                            "bef_nickname": bef_nickname,
                        },
                    )
            elif req_body.profile_image_file_id is not None:
                if req_body.default_yn is not None:
                    query = text("""
                                    update tb_user_profile
                                        set default_yn = :default_yn
                                        , profile_image_id = :profile_image_id
                                        , updated_id = :user_id
                                    where profile_id = :profile_id
                                    """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "profile_id": profile_id_to_int,
                            "default_yn": req_body.default_yn,
                            "profile_image_id": req_body.profile_image_file_id,
                        },
                    )
                else:
                    query = text("""
                                    update tb_user_profile
                                        set profile_image_id = :profile_image_id
                                        , updated_id = :user_id
                                    where profile_id = :profile_id
                                    """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "profile_id": profile_id_to_int,
                            "profile_image_id": req_body.profile_image_file_id,
                        },
                    )

            # 현재 프로필을 대표 프로필로(나머지는 n처리)
            if req_body.default_yn is not None and req_body.default_yn == "Y":
                query = text("""
                                 update tb_user_profile
                                    set default_yn = 'N'
                                      , updated_id = :user_id
                                  where user_id = :user_id
                                    and profile_id != :profile_id
                                 """)

                await db.execute(
                    query, {"user_id": user_id, "profile_id": profile_id_to_int}
                )

            if req_body.event_badge_id is None or req_body.event_badge_id == 0:
                pass
            else:
                query = text("""
                                 update tb_user_badge
                                    set display_yn = 'N'
                                      , updated_id = :user_id
                                  where profile_id = :profile_id
                                    and badge_type = 'event'
                                    and use_yn = 'Y'
                                 """)

                await db.execute(
                    query, {"user_id": user_id, "profile_id": profile_id_to_int}
                )

                query = text("""
                                 update tb_user_badge
                                    set display_yn = 'Y'
                                      , updated_id = :user_id
                                  where id = :id
                                    and use_yn = 'Y'
                                 """)

                await db.execute(
                    query, {"user_id": user_id, "id": req_body.event_badge_id}
                )

            if req_body.interest_badge_id is None or req_body.interest_badge_id == 0:
                pass
            else:
                query = text("""
                                 update tb_user_badge
                                    set display_yn = 'N'
                                      , updated_id = :user_id
                                  where profile_id = :profile_id
                                    and badge_type = 'interest'
                                    and use_yn = 'Y'
                                 """)

                await db.execute(
                    query, {"user_id": user_id, "profile_id": profile_id_to_int}
                )

                query = text("""
                                 update tb_user_badge
                                    set display_yn = 'Y'
                                      , updated_id = :user_id
                                  where id = :id
                                    and use_yn = 'Y'
                                 """)

                await db.execute(
                    query, {"user_id": user_id, "id": req_body.interest_badge_id}
                )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    return


@handle_exceptions
async def delete_user_profiles_profile_id(
    profile_id: str, kc_user_id: str, db: AsyncSession
):
    profile_id_to_int = int(profile_id)

    if kc_user_id:
        async with db.begin():
            user_id = await comm_service.get_user_from_kc(kc_user_id, db)
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )

            query = text("""
                             delete from tb_user_profile
                              where profile_id = :profile_id
                             """)

            await db.execute(query, {"profile_id": profile_id_to_int})

            query = text("""
                             update tb_user_badge
                                set use_yn = 'N'
                                  , updated_id = :user_id
                              where profile_id = :profile_id
                             """)

            await db.execute(
                query, {"profile_id": profile_id_to_int, "user_id": user_id}
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    return


@handle_exceptions
async def post_user_nickname_duplicate_check(
    req_body: user_schema.PostUserNicknameDuplicateCheckReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    if kc_user_id:
        async with db.begin():
            user_id, userInfo = await comm_service.get_user_from_kc(
                kc_user_id, db, ["email"]
            )
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )

            email = userInfo["email"]

            # 닉네임 검증
            nickname = req_body.user_nickname
            pattern = r"^[가-힣a-zA-Z0-9]+$"  # 한글, 영문, 숫자만

            if re.match(pattern, nickname) is None or nickname == email.split("@")[0]:
                raise CustomResponseException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=ErrorMessages.INVALID_PROFILE_INFO,
                )

            query = text("""
                             select 1
                               from tb_user_profile
                              where nickname = :nickname
                             """)

            result = await db.execute(query, {"nickname": nickname})
            db_rst = result.mappings().all()

            if db_rst:
                raise CustomResponseException(
                    status_code=status.HTTP_409_CONFLICT,
                    message=ErrorMessages.ALREADY_EXIST_NICKNAME,
                )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    return


@handle_exceptions
async def post_userid_identity_token(user_id: str, kc_user_id: str, db: AsyncSession):
    """
    본인인증 토큰 발급
    """
    res_data = {}
    secure_token_headers = {}
    secure_token_data = {}
    secure_token_res_data = {}

    # NICE API 토큰 발급 요청 준비
    url = "https://svc.niceapi.co.kr:22001/digital/niceid/oauth/oauth/token"

    # payload = {
    #     "grant_type": settings.NICE_GRANT_TYPE,
    #     "scope": "default"
    # }

    # Base64 인코딩된 인증 정보 생성
    credentials = f"{settings.NICE_CLIENT_ID}:{settings.NICE_CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {encoded_credentials}",
    }
    url = "https://svc.niceapi.co.kr:22001/digital/niceid/oauth/oauth/token"
    data = {"grant_type": settings.NICE_GRANT_TYPE, "scope": "default"}

    async with AsyncClient() as ac:
        res = await ac.post(url=url, headers=headers, data=data)
        res.raise_for_status()
        res_data = res.json()

        # 응답 데이터 형식
        # {
        #     "data": {
        #         "dataHeader": {
        #             "GW_RSLT_CD": "1200",
        #             "GW_RSLT_MSG": "오류 없음"
        #         },
        #         "dataBody": {
        #             "access_token": "451ad655-9ee0-4340-8513-2e52f4bec586",
        #             "token_type": "bearer",
        #             "expires_in": 1576725720,
        #             "scope": "default"
        #         }
        #     }
        # }

        # 암호화 토큰 통신
        if res_data.get("dataHeader").get("GW_RSLT_CD") == "1200":
            access_token = res_data.get("dataBody").get("access_token")
            nowDate = datetime.now()
            # currentTimestamp = str(math.floor(nowDate.timestamp()/1000))
            currentTimestamp = str(int(time.time()))

            nice_product_id = "2101979031"  # 본인확인(통합형) 상품

            # access_token base64 인코딩
            secure_token_credentials = (
                f"{access_token}:{currentTimestamp}:{settings.NICE_CLIENT_ID}"
            )
            encoded_secure_token_credentials = base64.b64encode(
                secure_token_credentials.encode("utf-8")
            ).decode("utf-8")
            auth_sucure_token = f"bearer {encoded_secure_token_credentials}"

            # 현재 시간 포맷
            formatted_datetime = f"{nowDate.year}{nowDate.month}{nowDate.day}{nowDate.hour}{nowDate.minute}{nowDate.second}"
            # # Nice 요청 번호 생성
            request_no = formatted_datetime

            secure_token_headers = {
                "Content-Type": "application/json",
                "Authorization": str(f"{auth_sucure_token}"),
                "client_id": str(f"{settings.NICE_CLIENT_ID}"),
                "ProductID": str(f"{nice_product_id}"),
            }
            secure_token_data = {
                "dataHeader": {"CNTY_CD": "ko"},
                "dataBody": {
                    "req_dtim": str(formatted_datetime),
                    "req_no": "req" + str(request_no),
                    "enc_mode": "1",
                },
            }

            # Base64 인코딩된 인증 정보 생성
            # credentials = f"{settings.NICE_CLIENT_ID}:{settings.NICE_CLIENT_SECRET}"
            # encoded_credentials = base64.b64encode(credentials.encode()).decode()

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"bearer {encoded_secure_token_credentials}",
                "client_id": f"{settings.NICE_CLIENT_ID}",
                "ProductID": f"{nice_product_id}",
            }
            url = "https://svc.niceapi.co.kr:22001/digital/niceid/api/v1.0/common/crypto/token"
            data = {
                "dataHeader": {"CNTY_CD": "ko"},
                "dataBody": {
                    "req_dtim": str(formatted_datetime),
                    "req_no": "req" + str(request_no),
                    "enc_mode": "1",
                },
            }

            async with AsyncClient() as acc:
                secure_token_resp = await acc.post(
                    url=url, headers=headers, data=str(data)
                )
                secure_token_resp.raise_for_status()
                secure_token_res_data = secure_token_resp.json()

                # 암호화 토큰 통신 성공 시 세션 데이터 저장
                if secure_token_res_data.get("dataHeader").get("GW_RSLT_CD") == "1200":
                    token_version_id = secure_token_res_data.get("dataBody").get(
                        "token_version_id"
                    )
                    token_val = secure_token_res_data.get("dataBody").get("token_val")

                    # key, iv, hmac_key 생성 (샘플 코드와 동일한 방식)
                    result = formatted_datetime + request_no + token_val
                    result_val = base64.b64encode(
                        hashlib.sha256(result.encode()).digest()
                    ).decode("utf-8")

                    encryption_key = result_val[:16]
                    encryption_iv = result_val[-16:]
                    hmac_key = result_val[:32]

                    # DB에 세션 데이터 저장
                    async with db.begin():
                        # 기존 세션 데이터 무효화
                        query = text("""
                            UPDATE tb_user_identity_session
                            SET use_yn = 'N', updated_date = NOW()
                            WHERE user_id = (SELECT user_id FROM tb_user WHERE kc_user_id = :kc_user_id AND use_yn = 'Y')
                            AND use_yn = 'Y'
                        """)
                        await db.execute(query, {"kc_user_id": kc_user_id})

                        # 새 세션 데이터 저장
                        query = text("""
                            INSERT INTO tb_user_identity_session
                            (user_id, token_version_id, req_no, encryption_key, encryption_iv, hmac_key,
                             expired_date, created_id, updated_id)
                            VALUES (
                                (SELECT user_id FROM tb_user WHERE kc_user_id = :kc_user_id AND use_yn = 'Y'),
                                :token_version_id, :req_no, :encryption_key, :encryption_iv, :hmac_key,
                                DATE_ADD(NOW(), INTERVAL 30 MINUTE), :created_id, :updated_id
                            )
                        """)
                        await db.execute(
                            query,
                            {
                                "kc_user_id": kc_user_id,
                                "token_version_id": token_version_id,
                                "req_no": "req" + request_no,
                                "encryption_key": encryption_key,
                                "encryption_iv": encryption_iv,
                                "hmac_key": hmac_key,
                                "created_id": settings.DB_DML_DEFAULT_ID,
                                "updated_id": settings.DB_DML_DEFAULT_ID,
                            },
                        )

    return {
        "institution_token_response": res_data,
        "encrypted_token_headers": secure_token_headers,
        "encrypted_token_data": secure_token_data,
        "encrypted_token_response": secure_token_res_data,
    }


# 복호화를 위한 함수
def decrypt_data(enc_data, key, iv):
    encryptor = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv.encode("utf-8"))

    def unpad(s):
        return s[0 : -ord(s[-1:])]

    return unpad(encryptor.decrypt(base64.b64decode(enc_data))).decode("euc-kr")


@handle_exceptions
async def get_user_authed_data(
    enc_data: str,
    token_version_id: str,
    integrity_value: str,
    kc_user_id: str,
    encryption_key: str,
    encryption_iv: str,
    hmac_key: str,
    req_no: str,
    db: AsyncSession,
):
    """
    본인인증 완료 시 유저 데이터 조회
    조회 후 DB 업데이트
    (프론트엔드에서 암호화 키들을 직접 전달받음)
    """
    async with db.begin():
        # 무결성 검증
        h = hmac.new(
            key=hmac_key.encode(),
            msg=enc_data.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        calculated_integrity = base64.b64encode(h).decode("utf-8")

        if calculated_integrity != integrity_value:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.DATA_INTEGRITY_VERIFICATION_FAILED,
            )

        # 복호화
        dec_data = json.loads(decrypt_data(enc_data, encryption_key, encryption_iv))

        # 요청번호 검증
        if req_no != dec_data["requestno"]:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.REQUEST_NUMBER_MISMATCH,
            )

        # 사용자 정보 추출
        name = dec_data.get("name")
        birthdate = dec_data.get("birthdate")
        gender_raw = dec_data.get("gender")
        mobileno = dec_data.get("mobileno")

        # 전화번호 중복 체크 (다른 계정에서 이미 본인인증된 전화번호인지 확인)
        if mobileno:
            duplicate_check_query = text("""
                SELECT user_id
                FROM tb_user
                WHERE mobile_no = :mobileno
                AND identity_yn = 'Y'
                AND kc_user_id != :kc_user_id
                AND use_yn = 'Y'
            """)
            duplicate_result = await db.execute(
                duplicate_check_query,
                {"mobileno": mobileno, "kc_user_id": kc_user_id},
            )
            duplicate_row = duplicate_result.mappings().one_or_none()

            if duplicate_row:
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.ALREADY_VERIFIED_PHONE,
                )

        # gender 값을 M 또는 F로 변환 (본인인증 API는 1=남성, 0=여성을 반환)
        gender = None
        if gender_raw:
            if gender_raw == "1" or gender_raw.upper() == "M":
                gender = "M"
            elif gender_raw == "0" or gender_raw.upper() == "F":
                gender = "F"

        # 업데이트할 필드와 값들을 동적으로 구성
        update_fields = []
        update_params = {
            "kc_user_id": kc_user_id,
            "updated_id": settings.DB_DML_DEFAULT_ID,
        }

        if name:
            update_fields.append("user_name = :name")
            update_params["name"] = name

        if birthdate:
            update_fields.append("birthdate = :birthdate")
            update_params["birthdate"] = birthdate

        if gender:
            update_fields.append("gender = :gender")
            update_params["gender"] = gender

        if mobileno:
            update_fields.append("mobile_no = :mobileno")
            update_params["mobileno"] = mobileno

        # 항상 업데이트되는 필드들
        update_fields.extend(
            [
                "identity_yn = 'Y'",
                "updated_id = :updated_id",
                "updated_date = NOW()",
            ]
        )

        # 사용자 정보 업데이트
        query = text(f"""
            UPDATE tb_user
            SET {", ".join(update_fields)}
            WHERE kc_user_id = :kc_user_id
            AND use_yn = 'Y'
        """)

        await db.execute(query, update_params)

    return {
        "success": True,
        "message": "Identity verification completed successfully",
        "data": {
            "name": name,
            "birthdate": birthdate,
            "gender": gender,
            "mobileno": mobileno,
        },
    }


@handle_exceptions
async def get_user_summary_info(kc_user_id: str, db: AsyncSession):
    """
    유저 요약 정보 조회
    프로필 이미지, 닉네임, 뱃지, 이메일
    총조회수, 총 선정작, 총 추천수, CP 조회수
    누적 관심 수, 관심 유지, 관심 이탈
    """
    res_data = {}

    if kc_user_id:
        async with db.begin():
            user_id = await comm_service.get_user_from_kc(kc_user_id, db)

            comparison_days = 1  # indicator 비교 일수 (1일 전)

            query = text(f"""
                         with tmp_interest as (
                             select y.product_id
                                , count(y.free_keep_interest) as count_free_interest
                                , sum(case when y.free_keep_interest = 'sustain' then 1 else 0 end) as count_free_interest_sustain
                                , sum(case when y.free_keep_interest = 'loss' then 1 else 0 end) as count_free_interest_loss
                            from (
                                select z.user_id
                                    , z.product_id
                                    , case when floor(timestampdiff(second, curdate(), max(z.updated_date)) / 3600) <= 72
                                            then 'loss'
                                            else 'sustain'
                                    end as free_keep_interest
                                from tb_user_product_usage z
                                where z.use_yn = 'Y'
                                and z.updated_date < curdate()
                                group by z.user_id, z.product_id
                            ) y
                            where y.user_id = :user_id
                            group by y.product_id
                         ),
                         tmp_previous_interest as (
                             select y.product_id
                                , count(y.free_keep_interest) as count_free_interest
                                , sum(case when y.free_keep_interest = 'sustain' then 1 else 0 end) as count_free_interest_sustain
                                , sum(case when y.free_keep_interest = 'loss' then 1 else 0 end) as count_free_interest_loss
                            from (
                                select z.user_id
                                    , z.product_id
                                    , case when floor(timestampdiff(second, date_sub(curdate(), interval :comparison_days day), max(z.updated_date)) / 3600) <= 72
                                            then 'loss'
                                            else 'sustain'
                                    end as free_keep_interest
                                from tb_user_product_usage z
                                where z.use_yn = 'Y'
                                and z.updated_date < date_sub(curdate(), interval :comparison_days day)
                                group by z.user_id, z.product_id
                            ) y
                            where y.user_id = :user_id
                            group by y.product_id
                         ),
                         tmp_previous_stats as (
                             select :user_id as user_id
                                  , coalesce((select sum(bdpcs.current_count_hit)
                                              from tb_batch_daily_product_count_summary bdpcs
                                              inner join tb_product p on bdpcs.product_id = p.product_id
                                              where p.user_id = :user_id
                                                and date(bdpcs.created_date) = date_sub(curdate(), interval :comparison_days day)), 0) as prev_total_view_count
                                  , coalesce((select sum(bdpcs.current_count_bookmark)
                                              from tb_batch_daily_product_count_summary bdpcs
                                              inner join tb_product p on bdpcs.product_id = p.product_id
                                              where p.user_id = :user_id
                                                and date(bdpcs.created_date) = date_sub(curdate(), interval :comparison_days day)), 0) as prev_total_bookmark_count
                                  , coalesce((select sum(bdpcs.current_count_recommend)
                                              from tb_batch_daily_product_count_summary bdpcs
                                              inner join tb_product p on bdpcs.product_id = p.product_id
                                              where p.user_id = :user_id
                                                and date(bdpcs.created_date) = date_sub(curdate(), interval :comparison_days day)), 0) as prev_total_recommend_count
                                  , coalesce((select sum(bdpcs.current_count_cp_hit)
                                              from tb_batch_daily_product_count_summary bdpcs
                                              inner join tb_product p on bdpcs.product_id = p.product_id
                                              where p.user_id = :user_id
                                                and date(bdpcs.created_date) = date_sub(curdate(), interval :comparison_days day)), 0) as prev_total_cp_view_count
                                  , coalesce((select sum(pi.count_free_interest) from tmp_previous_interest pi), 0) as prev_interest_total_count
                                  , coalesce((select sum(pi.count_free_interest_sustain) from tmp_previous_interest pi), 0) as prev_interest_sustain_count
                                  , coalesce((select sum(pi.count_free_interest_loss) from tmp_previous_interest pi), 0) as prev_interest_loss_count
                         )
                             select c.profile_id as profileId
                                  , {get_file_path_sub_query("c.profile_image_id", "profileImagePath", "user")}
                                  , c.nickname
                                  , {get_badge_image_sub_query("a.user_id", "interest", "badgeImagePath", "c.profile_id")}
                                  , a.email
                                  , coalesce((select sum(z.count_hit) from tb_product z
                                               where a.user_id = z.user_id), 0) as totalViewCount
                                  , (coalesce((select sum(z.count_hit) from tb_product z where a.user_id = z.user_id), 0) - p.prev_total_view_count) as totalViewCountIndicator
                                  , coalesce((select sum(z.count_bookmark) from tb_product z
                                               where a.user_id = z.user_id), 0) as totalBookmarkCount
                                  , (coalesce((select sum(z.count_bookmark) from tb_product z where a.user_id = z.user_id), 0) - p.prev_total_bookmark_count) as totalBookmarkCountIndicator
                                  , coalesce((select sum(z.count_recommend) from tb_product z
                                               where a.user_id = z.user_id), 0) as totalRecommendCount
                                  , (coalesce((select sum(z.count_recommend) from tb_product z where a.user_id = z.user_id), 0) - p.prev_total_recommend_count) as totalRecommendCountIndicator
                                  , coalesce((select sum(z.count_cp_hit) from tb_product z
                                               where a.user_id = z.user_id), 0) as totalCPViewCount
                                  , (coalesce((select sum(z.count_cp_hit) from tb_product z where a.user_id = z.user_id), 0) - p.prev_total_cp_view_count) as totalCPViewCountIndicator
                                  , coalesce(d.count_free_interest, 0) as interestTotalCount
                                  , (coalesce(d.count_free_interest, 0) - p.prev_interest_total_count) as interestTotalCountIndicator
                                  , coalesce(d.count_free_interest_sustain, 0) as interestSustainCount
                                  , (coalesce(d.count_free_interest_sustain, 0) - p.prev_interest_sustain_count) as interestSustainCountIndicator
                                  , coalesce(d.count_free_interest_loss, 0) as interestLossCount
                                  , (coalesce(d.count_free_interest_loss, 0) - p.prev_interest_loss_count) as interestLossCountIndicator
                               from tb_user a
                              inner join tb_user_profile c on a.user_id = c.user_id
                                and c.default_yn = 'Y'
                               left join tmp_interest d on a.user_id = d.product_id
                               left join tmp_previous_stats p on a.user_id = p.user_id
                              where a.user_id = :user_id
                             """)

            result = await db.execute(
                query, {"user_id": user_id, "comparison_days": comparison_days}
            )
            db_rst = result.mappings().all()

            if db_rst:
                res_data = db_rst[0]
    else:
        pass

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def get_user_evaluation_info(kc_user_id: str, db: AsyncSession):
    """
    유저 평가 정보 조회
    """
    res_data = {}

    if kc_user_id:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text("""
                            select *
                            from tb_product_evaluation pe
                            inner join tb_product p on pe.product_id = p.product_id
                            where p.user_id = :user_id
                            """)

        result = await db.execute(query, {"user_id": user_id})
        db_rst = result.mappings().all()

        if db_rst:
            res_data = _count_evaluations([dict(row) for row in db_rst])
    else:
        pass

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def purchase_nickname_change_ticket(
    profile_id: int,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    닉네임 변경권 구매 (500 캐시)
    """
    if kc_user_id:
        # kc_user_id로 user_id 조회
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 프로필 정보 조회 및 소유권 확인
        query = text("""
            SELECT user_id, nickname_change_count, paid_change_count
            FROM tb_user_profile
            WHERE profile_id = :profile_id
        """)
        result = await db.execute(query, {"profile_id": profile_id})
        profile_row = result.mappings().one_or_none()

        if not profile_row:
            raise CustomResponseException(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ErrorMessages.NOT_FOUND_PROFILE,
            )

        # 프로필 소유권 확인
        if profile_row["user_id"] != user_id:
            raise CustomResponseException(
                status_code=status.HTTP_403_FORBIDDEN,
                message=ErrorMessages.FORBIDDEN,
            )

        # 무료 변경 횟수 체크
        if profile_row["nickname_change_count"] > 0:
            raise CustomResponseException(
                status_code=status.HTTP_403_FORBIDDEN,
                message=ErrorMessages.FREE_NICKNAME_CHANGE_REMAINING,
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
            or cashbook_row["balance"] < CommonConstants.NICKNAME_CHANGE_TICKET_PRICE
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
                "amount": -CommonConstants.NICKNAME_CHANGE_TICKET_PRICE,
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
                "amount": CommonConstants.NICKNAME_CHANGE_TICKET_PRICE,
                "created_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        # 주문 생성 (tb_store_order)
        query = text("""
            INSERT INTO tb_store_order
            (order_no, device_type, user_id, order_date, order_status, total_price, cancel_yn, created_id, updated_id)
            VALUES (0, 'web', :user_id, NOW(), 'completed', :total_price, 'N', :created_id, :updated_id)
        """)
        result = await db.execute(
            query,
            {
                "user_id": user_id,
                "total_price": CommonConstants.NICKNAME_CHANGE_TICKET_PRICE,
                "created_id": settings.DB_DML_DEFAULT_ID,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            },
        )
        order_id = result.lastrowid

        # 주문 아이템 생성 (tb_store_order_item)
        query = text("""
            INSERT INTO tb_store_order_item
            (order_id, item_id, item_name, item_price, cancel_yn, quantity, created_id, updated_id)
            VALUES (:order_id, 'nickname_change', '닉네임 변경권', :item_price, 'N', 1, :created_id, :updated_id)
        """)
        await db.execute(
            query,
            {
                "order_id": order_id,
                "item_price": CommonConstants.NICKNAME_CHANGE_TICKET_PRICE,
                "created_id": settings.DB_DML_DEFAULT_ID,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        # paid_change_count 증가
        query = text("""
            UPDATE tb_user_profile
            SET paid_change_count = paid_change_count + 1,
                updated_id = :updated_id,
                updated_date = NOW()
            WHERE profile_id = :profile_id
        """)
        await db.execute(
            query,
            {
                "profile_id": profile_id,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        # 통계 로그 추가
        await statistics_service.insert_site_statistics_log(
            db=db, type="active", user_id=user_id
        )

        # 최종 잔액 및 변경 횟수 조회
        query = text("""
            SELECT COALESCE(SUM(balance), 0) AS balance
            FROM tb_user_cashbook
            WHERE user_id = :user_id
        """)
        result = await db.execute(query, {"user_id": user_id})
        final_balance_row = result.mappings().one_or_none()

        query = text("""
            SELECT nickname_change_count, paid_change_count
            FROM tb_user_profile
            WHERE profile_id = :profile_id
        """)
        result = await db.execute(query, {"profile_id": profile_id})
        final_profile_row = result.mappings().one_or_none()

        return {
            "success": True,
            "remaining_cash": final_balance_row["balance"],
            "nickname_change_count": final_profile_row["nickname_change_count"],
            "paid_change_count": final_profile_row["paid_change_count"],
        }

    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )


@handle_exceptions
async def get_user_recent_products(
    kc_user_id: str, limit: int, adult_yn: str, db: AsyncSession
):
    """
    최근 본 작품 목록 조회
    """
    if kc_user_id:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # limit이 None이거나 0 이하이면 전체 조회
        limit_clause = f"limit {limit}" if limit and limit > 0 else ""
        adult_filter = "and p.ratings_code = 'all'" if adult_yn == "N" else ""

        query = text(f"""
            select r.product_id as productId
                , p.title
                , p.author_name as authorName
                , p.illustrator_name as illustratorName
                , p.price_type as priceType
                , {get_file_path_sub_query("p.thumbnail_file_id", "coverImagePath", "cover")}
                , p.count_hit as countHit
                , p.count_recommend as countRecommend
                , r.updated_date as lastViewedDate
                , (select pe.episode_no
                   from tb_user_product_usage upu
                   inner join tb_product_episode pe on upu.episode_id = pe.episode_id
                   where upu.user_id = :user_id
                     and upu.product_id = r.product_id
                     and upu.use_yn = 'Y'
                   order by upu.updated_date desc
                   limit 1) as lastViewedEpisodeNo
                , (select upu.episode_id
                   from tb_user_product_usage upu
                   where upu.user_id = :user_id
                     and upu.product_id = r.product_id
                     and upu.use_yn = 'Y'
                   order by upu.updated_date desc
                   limit 1) as lastViewedEpisodeId
                , (SELECT MAX(pe.episode_no) FROM tb_product_episode pe
                    WHERE pe.product_id = p.product_id AND pe.use_yn = 'Y' AND pe.open_yn = 'Y') as latestEpisodeNo
                , (SELECT pe.episode_id FROM tb_product_episode pe
                    WHERE pe.product_id = p.product_id AND pe.use_yn = 'Y' AND pe.open_yn = 'Y'
                    ORDER BY pe.episode_no ASC LIMIT 1) as firstEpisodeId
                , p.created_date as createdDate
                , p.last_episode_date as latestEpisodeDate
                , (SELECT DATE_ADD(MAX(upu2.updated_date), INTERVAL 3 DAY)
                   FROM tb_user_product_usage upu2
                   WHERE upu2.product_id = p.product_id
                     AND upu2.user_id = :user_id
                     AND upu2.use_yn = 'Y') as interestEndDate
                , {get_badge_image_sub_query("p.author_id", "event", "authorEventLevelBadgeImagePath")}
                , COALESCE((SELECT COUNT(*) FROM tb_product_episode pe
                    WHERE pe.product_id = p.product_id AND pe.use_yn = 'Y' AND pe.open_yn = 'Y'), 0) as totalOpenEpisodeCount
                , COALESCE((SELECT COUNT(DISTINCT upu3.episode_id) FROM tb_user_product_usage upu3
                    WHERE upu3.product_id = p.product_id AND upu3.user_id = :user_id AND upu3.use_yn = 'Y'), 0) as readedEpisodeCount
              from tb_user_product_recent r
             inner join tb_product p on r.product_id = p.product_id
             where r.user_id = :user_id
               and r.use_yn = 'Y'
               and p.open_yn = 'Y'
               {adult_filter}
             order by r.updated_date desc
             {limit_clause}
        """)

        result = await db.execute(query, {"user_id": user_id})
        rows = result.mappings().all()

        res_data = [dict(row) for row in rows]

        return {"data": res_data}

    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )


@handle_exceptions
async def save_user_recent_product(product_id: int, kc_user_id: str, db: AsyncSession):
    """
    최근 본 작품 수동 저장
    """
    if kc_user_id:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 작품 존재 여부 확인
        query = text("""
            select product_id
              from tb_product
             where product_id = :product_id
               and open_yn = 'Y'
        """)
        result = await db.execute(query, {"product_id": product_id})
        product = result.mappings().first()

        if not product:
            raise CustomResponseException(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ErrorMessages.NOT_FOUND_PRODUCT,
            )

        # 최근 본 작품에 저장
        query = text("""
            insert into tb_user_product_recent (user_id, product_id, created_id, updated_id)
            values (:user_id, :product_id, :user_id, :user_id)
            on duplicate key update updated_date = now(), updated_id = :user_id, use_yn = 'Y'
        """)
        await db.execute(query, {"user_id": user_id, "product_id": product_id})
        await db.commit()

        return {"result": "success", "productId": product_id}

    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )


@handle_exceptions
async def delete_user_recent_product(
    product_id: int, kc_user_id: str, db: AsyncSession
):
    """
    최근 본 작품 개별 삭제
    """
    if kc_user_id:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 최근 본 작품에서 삭제 (soft delete)
        query = text("""
            update tb_user_product_recent
               set use_yn = 'N', updated_id = :user_id, updated_date = now()
             where user_id = :user_id
               and product_id = :product_id
        """)
        await db.execute(query, {"user_id": user_id, "product_id": product_id})
        await db.commit()

        return {"result": "success", "productId": product_id}

    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )


@handle_exceptions
async def delete_all_user_recent_products(kc_user_id: str, db: AsyncSession):
    """
    최근 본 작품 전체 삭제
    """
    if kc_user_id:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 모든 최근 본 작품 삭제 (soft delete)
        query = text("""
            update tb_user_product_recent
               set use_yn = 'N', updated_id = :user_id, updated_date = now()
             where user_id = :user_id
               and use_yn = 'Y'
        """)
        result = await db.execute(query, {"user_id": user_id})
        await db.commit()

        return {"result": "success", "deletedCount": result.rowcount}

    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )
