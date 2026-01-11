import base64
import time
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from typing import Optional

import re
import jwt
import logging

from app.const import settings, CommonConstants, ErrorMessages
from app.exceptions import CustomResponseException
from app.utils.auth import get_kc_signing_key
from app.utils.time import get_cur_time
import app.services.common.comm_service as comm_service
import app.schemas.auth as auth_schema
import app.services.common.statistics_service as statistics_service

from httpx import AsyncClient
from datetime import datetime

logger = logging.getLogger(__name__)

"""
auth 도메인 개별 서비스 함수 모음
"""


async def post_auth_signup(req_body: auth_schema.SignupReqBody, db: AsyncSession):
    admin_acc_token = None
    id = None
    try:
        async with db.begin():
            if req_body.sns_signup_type in ("naver", "google", "kakao", "apple"):
                keep_signin_yn = req_body.sns_keep_signin_yn
            else:
                # 라이크노벨 자체가입
                keep_signin_yn = "N"

            type = "client_normal" if keep_signin_yn == "N" else "client_keep"

            res_json = await comm_service.kc_token_endpoint(method="POST", type=type)
            admin_acc_token = res_json.get("access_token")

            """
            kc_users_endpoint (post)
              신규 user 회원정보 insert(user_entity, credential)
              인증과 관련된 정보만 저장
            """
            cred_data = {
                "type": "password",
                "value": req_body.password,
                "temporary": False,
            }

            cred_data_to_list = list()
            cred_data_to_list.append(cred_data)

            if req_body.sns_signup_type in ("naver", "google", "kakao", "apple"):
                # 랜덤 생성 uuid 중복 체크 및 Keycloak 사용자 생성
                max_retries = 10
                for attempt in range(max_retries):
                    username = comm_service.make_rand_uuid()  # 키클록에서 Case-sensitive 처리가 불가능하기에 별도의 uuid로 로그인 처리

                    params = {"username": username, "exact": "true"}

                    res_json = await comm_service.kc_users_endpoint(
                        method="GET",
                        admin_acc_token=admin_acc_token,
                        params_dict=params,
                    )

                    if not res_json:
                        # username이 사용 가능하면 Keycloak 사용자 생성 시도
                        data = {
                            "username": username,
                            "email": req_body.email,
                            "enabled": True,
                            "credentials": cred_data_to_list,
                        }

                        try:
                            id = await comm_service.kc_users_endpoint(
                                method="POST",
                                admin_acc_token=admin_acc_token,
                                data_dict=data,
                            )
                            break  # 성공하면 루프 종료
                        except CustomResponseException as e:
                            # 409 Conflict (사용자가 이미 존재) - 재시도
                            if e.status_code == 409:
                                logger.warning(
                                    f"Username {username} already exists (409), retrying... (attempt {attempt + 1}/{max_retries})"
                                )
                                continue
                            else:
                                raise
                else:
                    # max_retries 도달
                    raise CustomResponseException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        message=f"Failed to create unique username after {max_retries} attempts",
                    )
            else:
                username = req_body.email

                data = {
                    "username": username,
                    "email": req_body.email,
                    "enabled": True,
                    "credentials": cred_data_to_list,
                }

                try:
                    id = await comm_service.kc_users_endpoint(
                        method="POST", admin_acc_token=admin_acc_token, data_dict=data
                    )
                except CustomResponseException as e:
                    if e.status_code == 409:
                        raise CustomResponseException(
                            status_code=status.HTTP_409_CONFLICT,
                            message=ErrorMessages.ALREADY_EXIST_EMAIL,
                        )
                    else:
                        raise

            """
            tb_user
            """
            query = text("""
                             insert into tb_user (kc_user_id, email, gender, birthdate, latest_signed_type, created_id, updated_id)
                             values (:kc_user_id, :email, :gender, :birthdate, :latest_signed_type, :created_id, :updated_id)
                             """)

            await db.execute(
                query,
                {
                    "kc_user_id": id,
                    "email": req_body.email,
                    "gender": req_body.gender,
                    "birthdate": req_body.birthdate,
                    "latest_signed_type": req_body.sns_signup_type
                    if req_body.sns_signup_type in ("naver", "google", "kakao", "apple")
                    else "likenovel",
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            query = text("""
                             select last_insert_id()
                             """)

            result = await db.execute(query)
            new_user_id = result.scalar()

            """
            tb_user_notification
            """
            # 이용약관 동의 여부(필수), 개인정보 수집 및 이용 동의 여부(필수) 값은 화면 단에서 체크
            # 필수값을 체크하지 않으면 다음 단계로 넘어가지 않는 형태
            # 광고성정보 수신동의 여부 Y/N에 따라 혜택정보 알림 여부, 댓글 알림 여부, 시스템 알림 여부, 이벤트 알림 여부 일괄 Y/N 적용
            query = text("""
                             insert into tb_user_notification (user_id, noti_type, noti_yn, created_id, updated_id)
                             values (:user_id, :noti_type, :noti_yn, :created_id, :updated_id)
                             """)

            ins_datas = [
                {
                    "user_id": new_user_id,
                    "noti_type": "benefit",
                    "noti_yn": req_body.ad_info_agree_yn,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
                {
                    "user_id": new_user_id,
                    "noti_type": "comment",
                    "noti_yn": req_body.ad_info_agree_yn,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
                {
                    "user_id": new_user_id,
                    "noti_type": "system",
                    "noti_yn": req_body.ad_info_agree_yn,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
                {
                    "user_id": new_user_id,
                    "noti_type": "event",
                    "noti_yn": req_body.ad_info_agree_yn,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
                {
                    "user_id": new_user_id,
                    "noti_type": "marketing",
                    "noti_yn": req_body.ad_info_agree_yn,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            ]

            await db.execute(query, ins_datas)

            """
            tb_algorithm_recommend_user
            알고리즘 추천구좌 관리 - 회원가입 시 자동으로 레코드 생성
            - user_id, email(조인으로 가져옴), role_type(조인으로 가져옴), gender, age 자동 입력
            - feature_basic과 feature_1~10은 CSV 업로드 전까지 빈 문자열
            """
            # feature_basic 생성: gender(male/female) + age_group(1=10s, 2=20s, 3=30s, 4=40s, 5=50s+)
            # 빈 문자열로 설정 (CSV 업로드 전까지)
            feature_basic = ""

            # 중복 체크: user_id가 이미 존재하면 UPDATE, 없으면 INSERT
            check_query = text("""
                SELECT id FROM tb_algorithm_recommend_user WHERE user_id = :user_id
            """)
            existing_record = await db.execute(check_query, {"user_id": new_user_id})
            existing_row = existing_record.mappings().first()

            if existing_row:
                # 이미 존재하면 UPDATE
                update_query = text("""
                    UPDATE tb_algorithm_recommend_user
                    SET updated_id = :updated_id,
                        updated_date = NOW()
                    WHERE user_id = :user_id
                """)
                await db.execute(
                    update_query,
                    {
                        "user_id": new_user_id,
                        "updated_id": settings.DB_DML_DEFAULT_ID,
                    },
                )
            else:
                # 존재하지 않으면 INSERT
                insert_query = text("""
                    INSERT INTO tb_algorithm_recommend_user (
                        user_id,
                        feature_basic,
                        feature_1,
                        feature_2,
                        feature_3,
                        feature_4,
                        feature_5,
                        feature_6,
                        feature_7,
                        feature_8,
                        feature_9,
                        feature_10,
                        created_id,
                        updated_id
                    ) VALUES (
                        :user_id,
                        :feature_basic,
                        '',
                        '',
                        '',
                        '',
                        '',
                        '',
                        '',
                        '',
                        '',
                        '',
                        :created_id,
                        :updated_id
                    )
                """)
                await db.execute(
                    insert_query,
                    {
                        "user_id": new_user_id,
                        "feature_basic": feature_basic,
                        "created_id": settings.DB_DML_DEFAULT_ID,
                        "updated_id": settings.DB_DML_DEFAULT_ID,
                    },
                )

            """
            tb_user_social
            """
            if req_body.sns_signup_type in ("naver", "google", "kakao", "apple"):
                query = text("""
                                 insert into tb_user_social (user_id, sns_type, sns_link_id, created_id, updated_id)
                                 values (:user_id, :sns_type, :sns_link_id, :created_id, :updated_id)
                                 """)

                await db.execute(
                    query,
                    {
                        "user_id": new_user_id,
                        "sns_type": req_body.sns_signup_type,
                        "sns_link_id": req_body.sns_link_id,
                        "created_id": settings.DB_DML_DEFAULT_ID,
                        "updated_id": settings.DB_DML_DEFAULT_ID,
                    },
                )
            else:
                query = text("""
                                 insert into tb_user_social (user_id, sns_type, sns_link_id, created_id, updated_id)
                                 values (:user_id, :sns_type, :sns_link_id, :created_id, :updated_id)
                                 """)

                await db.execute(
                    query,
                    {
                        "user_id": new_user_id,
                        "sns_type": "likenovel",
                        "sns_link_id": "",
                        "created_id": settings.DB_DML_DEFAULT_ID,
                        "updated_id": settings.DB_DML_DEFAULT_ID,
                    },
                )

            """
            tb_user_profile
            """
            # 랜덤 생성 닉네임 중복 체크
            while True:
                rand_nickname = comm_service.make_rand_nickname()

                query = text("""
                                 select a.profile_id
                                   from tb_user_profile a
                                  where a.nickname = :rand_nickname
                                 """)

                result = await db.execute(query, {"rand_nickname": rand_nickname})
                db_rst = result.mappings().all()

                if not db_rst:
                    break

            query = text("""
                             insert into tb_user_profile (user_id, nickname, default_yn, role_type, profile_image_id, created_id, updated_id)
                             values (:user_id, :nickname, :default_yn, :role_type, :profile_image_id, :created_id, :updated_id)
                             """)

            await db.execute(
                query,
                {
                    "user_id": new_user_id,
                    "nickname": rand_nickname,
                    "default_yn": "Y",
                    "role_type": "user",
                    "profile_image_id": settings.R2_PROFILE_DEFAULT_IMAGE,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            query = text("""
                             select last_insert_id()
                             """)

            result = await db.execute(query)
            new_profile_id = result.scalar()

            """
            tb_user_badge
            """
            query = text("""
                             insert into tb_user_badge (profile_id, user_id, badge_type, badge_image_id, display_yn, created_id, updated_id)
                             values (:profile_id, :user_id, :badge_type, :badge_image_id, :display_yn, :created_id, :updated_id)
                             """)

            ins_datas = [
                {
                    "profile_id": new_profile_id,
                    "user_id": new_user_id,
                    "badge_type": "interest",
                    "badge_image_id": settings.R2_INTEREST_BADGE_DEFAULT_IMAGE,
                    "display_yn": "Y",
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
                {
                    "profile_id": new_profile_id,
                    "user_id": new_user_id,
                    "badge_type": "event",
                    "badge_image_id": settings.R2_EVENT_BADGE_DEFAULT_IMAGE,
                    "display_yn": "Y",
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            ]

            await db.execute(query, ins_datas)

            """
            tb_quest_user
            """
            query = text("""
                             insert into tb_quest_user (quest_id, user_id, created_id, updated_id)
                             values (:quest_id, :user_id, :created_id, :updated_id)
                             """)

            ins_datas = [
                {
                    "quest_id": 1,
                    "user_id": new_user_id,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
                {
                    "quest_id": 2,
                    "user_id": new_user_id,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
                {
                    "quest_id": 3,
                    "user_id": new_user_id,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
                {
                    "quest_id": 6,
                    "user_id": new_user_id,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
                {
                    "quest_id": 9,
                    "user_id": new_user_id,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            ]

            await db.execute(query, ins_datas)
    except OperationalError as e:
        logger.error(f"OperationalError in post_auth_signup: {e}")
        if admin_acc_token is not None and id is not None:
            await comm_service.kc_users_id_endpoint(
                method="DELETE", admin_acc_token=admin_acc_token, id=id
            )  # 키클록 데이터 롤백
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError as e:
        logger.error(f"SQLAlchemyError in post_auth_signup: {e}")
        if admin_acc_token is not None and id is not None:
            await comm_service.kc_users_id_endpoint(
                method="DELETE", admin_acc_token=admin_acc_token, id=id
            )  # 키클록 데이터 롤백
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception as e:
        logger.error(f"Exception in post_auth_signup: {e}")
        if admin_acc_token is not None and id is not None:
            await comm_service.kc_users_id_endpoint(
                method="DELETE", admin_acc_token=admin_acc_token, id=id
            )  # 키클록 데이터 롤백
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )

    """
    로그인 처리 전달
    """
    if req_body.sns_signup_type in ("naver", "google", "kakao", "apple"):
        res_body = {
            "email": req_body.email,
            "password": req_body.password,
            "keep_signin_yn": keep_signin_yn,
            "sns_signup_type": req_body.sns_signup_type,
            "sns_link_id": username,
        }
    else:
        # 라이크노벨 자체가입
        res_body = {
            "email": req_body.email,
            "password": req_body.password,
            "keep_signin_yn": keep_signin_yn,
        }

    return res_body


async def get_auth_signup_naver_callback(
    db: AsyncSession,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    if error:
        raise CustomResponseException(
            status_code=int(error),
            message=ErrorMessages.EXTERNAL_API_ERROR,
        )

    if state:
        # N-likenovel 혹은 Y-likenovel 형식 체크
        chk_flag = "N"
        if len(state) != 11:
            chk_flag = "Y"
        elif state[0] not in ("N", "Y"):
            chk_flag = "Y"
        elif state[1:] != "-likenovel":
            chk_flag = "Y"

        if chk_flag == "Y":
            raise CustomResponseException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                message=ErrorMessages.INVALID_STATE,
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=ErrorMessages.INVALID_STATE,
        )

    """
    sns_token_endpoint (post)
      전달받은 code, state를 사용해서 네이버 토큰 발급
    """
    res_json = await comm_service.sns_token_endpoint(
        method="POST", type="naver", code=code, state=state
    )
    naver_access_token = res_json.get("access_token")

    """
    sns_me_endpoint (get)
      네이버 access 토큰을 이용하여 프로필 API 호출
    """
    res_json = await comm_service.sns_me_endpoint(
        method="GET", type="naver", sns_acc_token=naver_access_token
    )
    tmp_res_json = res_json.get("response")
    naver_link_id = tmp_res_json.get("id")
    naver_email = (
        tmp_res_json.get("email") if tmp_res_json.get("email") else "none@naver.com"
    )
    naver_birthyear = (
        tmp_res_json.get("birthyear") if tmp_res_json.get("birthyear") else "9999"
    )
    naver_birthday = (
        tmp_res_json.get("birthday") if tmp_res_json.get("birthday") else "12-31"
    )
    naver_gender_raw = tmp_res_json.get("gender") if tmp_res_json.get("gender") else "U"

    # gender 값을 M 또는 F로 변환
    naver_gender = "U"
    if naver_gender_raw and naver_gender_raw != "U":
        if naver_gender_raw == "1" or naver_gender_raw.upper() == "M":
            naver_gender = "M"
        elif naver_gender_raw == "0" or naver_gender_raw.upper() == "F":
            naver_gender = "F"

    try:
        async with db.begin():
            query = text("""
                             select a.kc_user_id
                               from tb_user a
                              where exists (select 1 from tb_user_social z
                                             where a.user_id = z.user_id
                                               and z.sns_link_id = :sns_link_id
                                               and z.sns_type = 'naver')
                                and a.use_yn = 'Y'
                             """)

            result = await db.execute(query, {"sns_link_id": naver_link_id})
            db_rst = result.mappings().all()

            # tb_user_social에 없으면 tb_user에서 확인 (오래된 계정 대응)
            if not db_rst:
                query = text("""
                             select a.kc_user_id
                               from tb_user a
                              where a.email = :email
                                and a.latest_signed_type = 'naver'
                                and a.use_yn = 'Y'
                             """)
                result = await db.execute(query, {"email": naver_email})
                db_rst = result.mappings().all()

            # 다른 로그인 방식으로 가입된 계정 확인
            if not db_rst:
                query = text("""
                             select a.kc_user_id, a.latest_signed_type, a.use_yn
                               from tb_user a
                              where a.email = :email
                             """)
                result = await db.execute(query, {"email": naver_email})
                existing_account = result.mappings().all()

                if existing_account:
                    account = existing_account[0]
                    # 탈퇴한 계정인 경우
                    if account.get("use_yn") == "N":
                        raise CustomResponseException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            message=ErrorMessages.ALREADY_WITHDRAWN_MEMBER,
                        )
                    # 다른 방식으로 가입된 계정인 경우
                    else:
                        raise CustomResponseException(
                            status_code=status.HTTP_409_CONFLICT,
                            message=ErrorMessages.ALREADY_EXIST_EMAIL_WITH_DIFFERENT_METHOD,
                        )

            if db_rst:
                # 기 등록(로그인)
                kc_user_id = db_rst[0].get("kc_user_id")
                keep_signin_yn = "N"

                res_json = await comm_service.kc_token_endpoint(
                    method="POST", type="client_normal"
                )
                admin_acc_token = res_json.get("access_token")

                """
                kc_users_id_endpoint (get)
                  user 회원정보 조회 후 username 조회
                """
                try:
                    res_json = await comm_service.kc_users_id_endpoint(
                        method="GET", admin_acc_token=admin_acc_token, id=kc_user_id
                    )
                    username = res_json.get("username")

                    """
                    로그인 처리 전달
                    """
                    res_body = {
                        "email": naver_email,
                        "password": settings.NAVER_PASSWORD,
                        "keep_signin_yn": keep_signin_yn,
                        "sns_signup_type": "naver",
                        "sns_link_id": username,
                    }
                except CustomResponseException as e:
                    # Keycloak에서 사용자를 찾지 못한 경우 (DB와 Keycloak 불일치)
                    # DB 데이터로 Keycloak에 사용자 생성 후 로그인 처리
                    if e.status_code == 404:
                        logger.warning(
                            f"Keycloak user not found for kc_user_id: {kc_user_id}, creating Keycloak user from DB data"
                        )

                        # DB에서 사용자 정보 조회
                        query = text("""
                            SELECT email, birthdate, gender
                            FROM tb_user
                            WHERE kc_user_id = :kc_user_id
                              AND use_yn = 'Y'
                        """)
                        result = await db.execute(query, {"kc_user_id": kc_user_id})
                        user_data = result.mappings().one()

                        # Keycloak 사용자 생성
                        import secrets

                        new_username = secrets.token_urlsafe(16)

                        res_json = await comm_service.kc_users_endpoint(
                            method="POST",
                            admin_acc_token=admin_acc_token,
                            data_dict={
                                "username": new_username,
                                "email": user_data["email"],
                                "enabled": True,
                                "credentials": [
                                    {
                                        "type": "password",
                                        "value": settings.NAVER_PASSWORD,
                                        "temporary": False,
                                    }
                                ],
                            },
                        )

                        # 생성된 사용자의 Keycloak ID 조회
                        res_json = await comm_service.kc_users_endpoint(
                            method="GET",
                            admin_acc_token=admin_acc_token,
                            username=new_username,
                        )
                        new_kc_user_id = res_json[0].get("id")

                        # DB의 kc_user_id 업데이트
                        query = text("""
                            UPDATE tb_user
                            SET kc_user_id = :new_kc_user_id
                            WHERE kc_user_id = :old_kc_user_id
                              AND use_yn = 'Y'
                        """)
                        await db.execute(
                            query,
                            {
                                "new_kc_user_id": new_kc_user_id,
                                "old_kc_user_id": kc_user_id,
                            },
                        )
                        await db.commit()

                        logger.info(
                            f"Created Keycloak user {new_kc_user_id} for existing DB user"
                        )

                        # 로그인 처리
                        res_body = {
                            "email": naver_email,
                            "password": settings.NAVER_PASSWORD,
                            "keep_signin_yn": keep_signin_yn,
                            "sns_signup_type": "naver",
                            "sns_link_id": new_username,
                        }
                    else:
                        raise
            else:
                # 미등록(회원가입 후 로그인)
                """
                naver token 및 프로필 정보 리턴
                """
                keep_signin_yn = "N"
                ad_info_agree_yn = state[0]

                res_body = {
                    "email": naver_email,
                    "password": settings.NAVER_PASSWORD,
                    "birthdate": f"{naver_birthyear}-{naver_birthday}",
                    "gender": naver_gender,
                    "ad_info_agree_yn": ad_info_agree_yn,
                    "sns_signup_type": "naver",
                    "sns_link_id": naver_link_id,
                    "sns_keep_signin_yn": keep_signin_yn,
                }
    except OperationalError:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )

    return res_body


async def get_auth_signup_google_callback(
    db: AsyncSession,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    logger.info(
        f"Google Signup Callback - code: {code[:10] if code else None}..., state: {state}, error: {error}"
    )

    if error:
        logger.error(f"Google OAuth Error - error: {error}")
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=f"구글 로그인 오류: {error}",
        )

    pattern = r"^(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"  # YYYY-MM-DD

    if state:
        # N-1900-01-01-M-likenovel 형식 체크
        chk_flag = "N"
        if len(state) != 24:
            chk_flag = "Y"
        elif state[0] not in ("N", "Y"):
            chk_flag = "Y"
        elif re.match(pattern, state[2:12]) is None:
            chk_flag = "Y"
        elif state[13] not in ("M", "F"):
            chk_flag = "Y"
        elif state[14:] != "-likenovel":
            chk_flag = "Y"

        if chk_flag == "Y":
            raise CustomResponseException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                message=ErrorMessages.INVALID_STATE,
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=ErrorMessages.INVALID_STATE,
        )

    """
    sns_token_endpoint (post)
      전달받은 code, state를 사용해서 구글 토큰 발급
    """
    redirect_uri = settings.GOOGLE_SIGNUP_REDIRECT_URL
    res_json = await comm_service.sns_token_endpoint(
        method="POST", type="google", code=code, state=state, redirect_uri=redirect_uri
    )
    google_access_token = res_json.get("access_token")

    """
    sns_me_endpoint (get)
      구글 access 토큰을 이용하여 프로필 API 호출
    """
    res_json = await comm_service.sns_me_endpoint(
        method="GET", type="google", sns_acc_token=google_access_token
    )
    google_link_id = res_json.get("id")
    google_email = res_json.get("email") if res_json.get("email") else "none@gmail.com"
    google_birthdate = state[2:12]
    google_gender_raw = state[13]

    # gender 값을 M 또는 F로 변환 (1=남성, 0=여성)
    google_gender = None
    if google_gender_raw:
        if google_gender_raw == "1" or google_gender_raw.upper() == "M":
            google_gender = "M"
        elif google_gender_raw == "0" or google_gender_raw.upper() == "F":
            google_gender = "F"

    try:
        async with db.begin():
            query = text("""
                             select a.kc_user_id
                               from tb_user a
                              where exists (select 1 from tb_user_social z
                                             where a.user_id = z.user_id
                                               and z.sns_link_id = :sns_link_id
                                               and z.sns_type = 'google')
                                and a.use_yn = 'Y'
                             """)

            result = await db.execute(query, {"sns_link_id": google_link_id})
            db_rst = result.mappings().all()

            # tb_user_social에 없으면 tb_user에서 확인 (오래된 계정 대응)
            if not db_rst:
                query = text("""
                             select a.kc_user_id
                               from tb_user a
                              where a.email = :email
                                and a.latest_signed_type = 'google'
                                and a.use_yn = 'Y'
                             """)
                result = await db.execute(query, {"email": google_email})
                db_rst = result.mappings().all()

            # 다른 로그인 방식으로 가입된 계정 확인
            if not db_rst:
                query = text("""
                             select a.kc_user_id, a.latest_signed_type, a.use_yn
                               from tb_user a
                              where a.email = :email
                             """)
                result = await db.execute(query, {"email": google_email})
                existing_account = result.mappings().all()

                if existing_account:
                    account = existing_account[0]
                    # 탈퇴한 계정인 경우
                    if account.get("use_yn") == "N":
                        raise CustomResponseException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            message=ErrorMessages.ALREADY_WITHDRAWN_MEMBER,
                        )
                    # 다른 방식으로 가입된 계정인 경우
                    else:
                        raise CustomResponseException(
                            status_code=status.HTTP_409_CONFLICT,
                            message=ErrorMessages.ALREADY_EXIST_EMAIL_WITH_DIFFERENT_METHOD,
                        )

            if db_rst:
                # 기 등록(로그인)
                kc_user_id = db_rst[0].get("kc_user_id")
                keep_signin_yn = "N"

                res_json = await comm_service.kc_token_endpoint(
                    method="POST", type="client_normal"
                )
                admin_acc_token = res_json.get("access_token")

                """
                kc_users_id_endpoint (get)
                  user 회원정보 조회 후 username 조회
                """
                res_json = await comm_service.kc_users_id_endpoint(
                    method="GET", admin_acc_token=admin_acc_token, id=kc_user_id
                )
                username = res_json.get("username")

                """
                로그인 처리 전달
                """
                res_body = {
                    "email": google_email,
                    "password": settings.GOOGLE_PASSWORD,
                    "keep_signin_yn": keep_signin_yn,
                    "sns_signup_type": "google",
                    "sns_link_id": username,
                }
            else:
                # 미등록(회원가입 후 로그인)
                """
                google token 및 프로필 정보 리턴
                """
                keep_signin_yn = "N"
                ad_info_agree_yn = state[0]

                res_body = {
                    "email": google_email,
                    "password": settings.GOOGLE_PASSWORD,
                    "birthdate": google_birthdate,
                    "gender": google_gender,
                    "ad_info_agree_yn": ad_info_agree_yn,
                    "sns_signup_type": "google",
                    "sns_link_id": google_link_id,
                    "sns_keep_signin_yn": keep_signin_yn,
                }
    except OperationalError:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )

    return res_body


async def get_auth_signup_kakao_callback(
    db: AsyncSession,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    logger.info(
        f"Kakao Signup Callback - code: {code[:10] if code else None}..., state: {state}, error: {error}"
    )

    if error:
        logger.error(f"Kakao OAuth Error - error: {error}")
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=f"카카오 로그인 오류: {error}",
        )

    if state:
        # N-likenovel 혹은 Y-likenovel 형식 체크
        chk_flag = "N"
        if len(state) != 11:
            chk_flag = "Y"
        elif state[0] not in ("N", "Y"):
            chk_flag = "Y"
        elif state[1:] != "-likenovel":
            chk_flag = "Y"

        if chk_flag == "Y":
            raise CustomResponseException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                message=ErrorMessages.INVALID_STATE,
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=ErrorMessages.INVALID_STATE,
        )

    """
    sns_token_endpoint (post)
      전달받은 code, state를 사용해서 카카오 토큰 발급
    """
    redirect_uri = settings.KAKAO_SIGNUP_REDIRECT_URL
    res_json = await comm_service.sns_token_endpoint(
        method="POST", type="kakao", code=code, state=state, redirect_uri=redirect_uri
    )
    kakao_access_token = res_json.get("access_token")

    """
    sns_me_endpoint (get)
      카카오 access 토큰을 이용하여 프로필 API 호출
    """
    res_json = await comm_service.sns_me_endpoint(
        method="GET", type="kakao", sns_acc_token=kakao_access_token
    )
    kakao_link_id = str(res_json.get("id"))
    if res_json.get("kakao_account"):
        kakao_email = (
            res_json.get("kakao_account").get("email")
            if res_json.get("kakao_account").get("email")
            else "none@kakao.com"
        )
        kakao_birthyear = (
            res_json.get("kakao_account").get("birthyear")
            if res_json.get("kakao_account").get("birthyear")
            else "9999"
        )
        kakao_birthday = (
            res_json.get("kakao_account").get("birthday")
            if res_json.get("kakao_account").get("birthday")
            else "12-31"
        )
        if res_json.get("kakao_account").get("gender"):
            kakao_gender = (
                "M" if res_json.get("kakao_account").get("gender") == "male" else "F"
            )
        else:
            kakao_gender = "U"
    else:
        kakao_email = "none@kakao.com"
        kakao_birthyear = "9999"
        kakao_birthday = "12-31"
        kakao_gender = "U"

    try:
        async with db.begin():
            query = text("""
                             select a.kc_user_id
                               from tb_user a
                              where exists (select 1 from tb_user_social z
                                             where a.user_id = z.user_id
                                               and z.sns_link_id = :sns_link_id
                                               and z.sns_type = 'kakao')
                                and a.use_yn = 'Y'
                             """)

            result = await db.execute(query, {"sns_link_id": kakao_link_id})
            db_rst = result.mappings().all()

            # tb_user_social에 없으면 tb_user에서 확인 (오래된 계정 대응)
            if not db_rst:
                query = text("""
                             select a.kc_user_id
                               from tb_user a
                              where a.email = :email
                                and a.latest_signed_type = 'kakao'
                                and a.use_yn = 'Y'
                             """)
                result = await db.execute(query, {"email": kakao_email})
                db_rst = result.mappings().all()

            # 다른 로그인 방식으로 가입된 계정 확인
            if not db_rst:
                query = text("""
                             select a.kc_user_id, a.latest_signed_type, a.use_yn
                               from tb_user a
                              where a.email = :email
                             """)
                result = await db.execute(query, {"email": kakao_email})
                existing_account = result.mappings().all()

                if existing_account:
                    account = existing_account[0]
                    # 탈퇴한 계정인 경우
                    if account.get("use_yn") == "N":
                        raise CustomResponseException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            message=ErrorMessages.ALREADY_WITHDRAWN_MEMBER,
                        )
                    # 다른 방식으로 가입된 계정인 경우
                    else:
                        raise CustomResponseException(
                            status_code=status.HTTP_409_CONFLICT,
                            message=ErrorMessages.ALREADY_EXIST_EMAIL_WITH_DIFFERENT_METHOD,
                        )

            if db_rst:
                # 기 등록(로그인)
                kc_user_id = db_rst[0].get("kc_user_id")
                keep_signin_yn = "N"

                res_json = await comm_service.kc_token_endpoint(
                    method="POST", type="client_normal"
                )
                admin_acc_token = res_json.get("access_token")

                """
                kc_users_id_endpoint (get)
                  user 회원정보 조회 후 username 조회
                """
                res_json = await comm_service.kc_users_id_endpoint(
                    method="GET", admin_acc_token=admin_acc_token, id=kc_user_id
                )
                username = res_json.get("username")

                """
                로그인 처리 전달
                """
                res_body = {
                    "email": kakao_email,
                    "password": settings.KAKAO_PASSWORD,
                    "keep_signin_yn": keep_signin_yn,
                    "sns_signup_type": "kakao",
                    "sns_link_id": username,
                }
            else:
                # 미등록(회원가입 후 로그인)
                """
                kakao token 및 프로필 정보 리턴
                """
                keep_signin_yn = "N"
                ad_info_agree_yn = state[0]

                res_body = {
                    "email": kakao_email,
                    "password": settings.KAKAO_PASSWORD,
                    "birthdate": f"{kakao_birthyear}-{kakao_birthday}",
                    "gender": kakao_gender,
                    "ad_info_agree_yn": ad_info_agree_yn,
                    "sns_signup_type": "kakao",
                    "sns_link_id": kakao_link_id,
                    "sns_keep_signin_yn": keep_signin_yn,
                }
    except OperationalError:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )

    return res_body


async def get_auth_signup_apple_callback(
    db: AsyncSession,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    if error:
        raise CustomResponseException(
            status_code=int(error),
            message=ErrorMessages.EXTERNAL_API_ERROR,
        )

    pattern = r"^(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"  # YYYY-MM-DD

    if state:
        # N-1900-01-01-M-likenovel 형식 체크
        chk_flag = "N"
        if len(state) != 24:
            chk_flag = "Y"
        elif state[0] not in ("N", "Y"):
            chk_flag = "Y"
        elif re.match(pattern, state[2:12]) is None:
            chk_flag = "Y"
        elif state[13] not in ("M", "F"):
            chk_flag = "Y"
        elif state[14:] != "-likenovel":
            chk_flag = "Y"

        if chk_flag == "Y":
            raise CustomResponseException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                message=ErrorMessages.INVALID_STATE,
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=ErrorMessages.INVALID_STATE,
        )

    """
    sns_token_endpoint (post)
      전달받은 code, state를 사용해서 애플 토큰 발급
    """
    redirect_uri = settings.APPLE_SIGNUP_REDIRECT_URL
    res_json = await comm_service.sns_token_endpoint(
        method="POST", type="apple", code=code, state=state, redirect_uri=redirect_uri
    )
    apple_id_token = res_json.get("id_token")

    """
    id token 값 디코딩 후 분석
      애플 id 토큰을 이용하여 프로필 조회
    """
    decoded_token = await comm_service.decode_apple_token(id_token=apple_id_token)

    apple_link_id = decoded_token.get("sub")
    apple_email = (
        decoded_token.get("email") if decoded_token.get("email") else "none@apple.com"
    )
    # @privaterelay.appleid.com 형식 필터링 필요
    if apple_email != "" and apple_email[0] == "@":
        apple_email = "none@apple.com"
    apple_birthdate = state[2:12]
    apple_gender_raw = state[13]

    # gender 값을 M 또는 F로 변환 (1=남성, 0=여성)
    apple_gender = None
    if apple_gender_raw:
        if apple_gender_raw == "1" or apple_gender_raw.upper() == "M":
            apple_gender = "M"
        elif apple_gender_raw == "0" or apple_gender_raw.upper() == "F":
            apple_gender = "F"

    try:
        async with db.begin():
            query = text("""
                             select a.kc_user_id
                               from tb_user a
                              where exists (select 1 from tb_user_social z
                                             where a.user_id = z.user_id
                                               and z.sns_link_id = :sns_link_id
                                               and z.sns_type = 'apple')
                                and a.use_yn = 'Y'
                             """)

            result = await db.execute(query, {"sns_link_id": apple_link_id})
            db_rst = result.mappings().all()

            if db_rst:
                # 기 등록(로그인)
                kc_user_id = db_rst[0].get("kc_user_id")
                keep_signin_yn = "N"

                res_json = await comm_service.kc_token_endpoint(
                    method="POST", type="client_normal"
                )
                admin_acc_token = res_json.get("access_token")

                """
                kc_users_id_endpoint (get)
                  user 회원정보 조회 후 username 조회
                """
                res_json = await comm_service.kc_users_id_endpoint(
                    method="GET", admin_acc_token=admin_acc_token, id=kc_user_id
                )
                username = res_json.get("username")

                """
                로그인 처리 전달
                """
                res_body = {
                    "email": apple_email,
                    "password": settings.APPLE_PASSWORD,
                    "keep_signin_yn": keep_signin_yn,
                    "sns_signup_type": "apple",
                    "sns_link_id": username,
                }
            else:
                # 미등록(회원가입 후 로그인)
                """
                apple token 및 프로필 정보 리턴
                """
                keep_signin_yn = "N"
                ad_info_agree_yn = state[0]

                res_body = {
                    "email": apple_email,
                    "password": settings.APPLE_PASSWORD,
                    "birthdate": apple_birthdate,
                    "gender": apple_gender,
                    "ad_info_agree_yn": ad_info_agree_yn,
                    "sns_signup_type": "apple",
                    "sns_link_id": apple_link_id,
                    "sns_keep_signin_yn": keep_signin_yn,
                }
    except OperationalError:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )

    return res_body


async def post_auth_email_duplicate_check(
    req_body: auth_schema.EmailDuplicateCheckReqBody,
    db: AsyncSession,
):
    # DB에서 이메일 중복 체크 (use_yn='Y'인 활성 계정만)
    query = text("""
        SELECT user_id FROM tb_user
        WHERE email = :email AND use_yn = 'Y'
    """)
    result = await db.execute(query, {"email": req_body.email})
    existing_user = result.mappings().first()

    if existing_user:
        raise CustomResponseException(
            status_code=status.HTTP_409_CONFLICT,
            message=ErrorMessages.ALREADY_EXIST_EMAIL,
        )
    else:
        return


async def post_auth_signin(
    req_body: auth_schema.SigninReqBody, db: AsyncSession, call_from: str = "user"
):
    try:
        async with db.begin():
            if req_body.sns_signup_type in ("naver", "google", "kakao", "apple"):
                username = req_body.sns_link_id
                latest_signed_type = req_body.sns_signup_type
            else:
                # 라이크노벨 자체가입
                username = req_body.email
                latest_signed_type = "likenovel"

            keep_signin_yn = req_body.keep_signin_yn
            data = {"username": username, "password": req_body.password}

            type = "user_normal_signin" if keep_signin_yn == "N" else "user_keep_signin"

            res_json = await comm_service.kc_token_endpoint(
                method="POST", type=type, data_dict=data
            )
            access_token = res_json.get("access_token")
            access_expires_in = res_json.get("expires_in")
            refresh_token = res_json.get("refresh_token")
            refresh_expires_in = res_json.get("refresh_expires_in")

            """
            kc_userinfo_endpoint (get)
              user_entity 테이블의 id 값 조회
            """
            id = await comm_service.kc_userinfo_endpoint(
                method="GET", user_acc_token=access_token
            )

            # 탈퇴 계정 체크
            check_query = text("""
                             select use_yn
                               from tb_user
                              where kc_user_id = :kc_user_id
                             """)
            check_result = await db.execute(check_query, {"kc_user_id": id})
            check_rst = check_result.mappings().one_or_none()

            if check_rst and check_rst.get("use_yn") == "N":
                raise CustomResponseException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message=ErrorMessages.ALREADY_WITHDRAWN_MEMBER,
                )

            # 통합아이디 존재하면 통합아이디로 로그인
            query = text("""
                             with tmp_post_auth_signin as (
                                 select x.integrated_user_id
                                   from tb_user z
                                  inner join tb_user_social x on z.user_id = x.user_id
                                  where z.kc_user_id = :kc_user_id
                                    and z.use_yn = 'Y'
                             )
                             select a.kc_user_id
                                  , b.sns_type
                                  , a.role_type
                               from tb_user a
                              inner join tb_user_social b on a.user_id = b.user_id
                                and b.default_yn = 'Y'
                              inner join tmp_post_auth_signin c on a.user_id = c.integrated_user_id
                              where a.use_yn = 'Y'
                             """)

            result = await db.execute(query, {"kc_user_id": id})
            db_rst = result.mappings().all()

            if db_rst:
                id = db_rst[0].get("kc_user_id")
                integrated_sns_type = db_rst[0].get("sns_type")
                role_type = db_rst[0].get("role_type")

                if (
                    call_from == CommonConstants.ROLE_ADMIN
                    and role_type == CommonConstants.ROLE_NORMAL
                ):  # 일반 사용자 계정으로 관리자 로그인 -> 로그인이 되면 안됨
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.ADMIN_ACCOUNT_REQUIRED,
                    )

                if integrated_sns_type in ("naver", "google", "kakao", "apple"):
                    type = "client_normal" if keep_signin_yn == "N" else "client_keep"

                    res_json = await comm_service.kc_token_endpoint(
                        method="POST", type=type
                    )
                    admin_acc_token = res_json.get("access_token")

                    res_json = await comm_service.kc_users_id_endpoint(
                        method="GET", admin_acc_token=admin_acc_token, id=id
                    )

                    username = res_json.get("username")
                    latest_signed_type = integrated_sns_type

                    if latest_signed_type == "naver":
                        integrated_pw = settings.NAVER_PASSWORD
                    if latest_signed_type == "google":
                        integrated_pw = settings.GOOGLE_PASSWORD
                    if latest_signed_type == "kakao":
                        integrated_pw = settings.KAKAO_PASSWORD
                    if latest_signed_type == "apple":
                        integrated_pw = settings.APPLE_PASSWORD

                    data = {"username": username, "password": integrated_pw}

                    type = (
                        "user_normal_signin"
                        if keep_signin_yn == "N"
                        else "user_keep_signin"
                    )

                    res_json = await comm_service.kc_token_endpoint(
                        method="POST", type=type, data_dict=data
                    )
                    access_token = res_json.get("access_token")
                    access_expires_in = res_json.get("expires_in")
                    refresh_token = res_json.get("refresh_token")
                    refresh_expires_in = res_json.get("refresh_expires_in")
                else:
                    # 라이크노벨 자체가입
                    # TODO: 통합아이디 연동 모듈 구현 후 수정 및 최종 테스트 필(현재 개별아이디 개발 완료. 나머지 초안 개발 완료)
                    type = "client_normal" if keep_signin_yn == "N" else "client_keep"

                    res_json = await comm_service.kc_token_endpoint(
                        method="POST", type=type
                    )
                    admin_acc_token = res_json.get("access_token")

                    redirect_uri = await comm_service.kc_users_id_imperson_endpoint(
                        method="POST", admin_acc_token=admin_acc_token, id=id
                    )

                    code = await comm_service.kc_users_id_imperson_auth_endpoint(
                        method="GET", type=type, redirect_uri=redirect_uri
                    )

                    latest_signed_type = "likenovel"

                    data = {"code": code, "redirect_uri": redirect_uri}

                    type = (
                        "user_normal_signin_code"
                        if keep_signin_yn == "N"
                        else "user_keep_signin_code"
                    )

                    res_json = await comm_service.kc_token_endpoint(
                        method="POST", type=type, data_dict=data
                    )
                    access_token = res_json.get("access_token")
                    access_expires_in = res_json.get("expires_in")
                    refresh_token = res_json.get("refresh_token")
                    refresh_expires_in = res_json.get("refresh_expires_in")

            query = text("""
                             update tb_user
                                set stay_signed_yn = :stay_signed_yn
                                  , latest_signed_date = :latest_signed_date
                                  , latest_signed_type = :latest_signed_type
                              where kc_user_id = :kc_user_id
                             """)

            await db.execute(
                query,
                {
                    "stay_signed_yn": keep_signin_yn,
                    "latest_signed_date": get_cur_time("iso"),
                    "latest_signed_type": latest_signed_type,
                    "kc_user_id": id,
                },
            )

            if latest_signed_type in ("naver", "google", "kakao", "apple"):
                tmp_key = comm_service.make_rand_uuid()

                query = text("""
                                 select a.user_id, b.sns_id, a.role_type
                                   from tb_user a
                                  inner join tb_user_social b on a.user_id = b.user_id
                                    and b.sns_type = :sns_type
                                  where a.kc_user_id = :kc_user_id
                                    and a.use_yn = 'Y'
                                 """)

                result = await db.execute(
                    query, {"kc_user_id": id, "sns_type": latest_signed_type}
                )
                db_rst = result.mappings().all()

                if (
                    call_from == CommonConstants.ROLE_ADMIN
                    and db_rst[0].get("role_type") == CommonConstants.ROLE_NORMAL
                ):  # 일반 사용자 계정으로 관리자 로그인 -> 로그인이 되면 안됨
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.ADMIN_ACCOUNT_REQUIRED,
                    )

                user_id = db_rst[0].get("user_id") if db_rst else None

                auth_data = {"snsId": db_rst[0].get("sns_id"), "tempIssuedKey": tmp_key}

                query = text("""
                                 update tb_user_social
                                    set temp_issued_key = :temp_issued_key
                                      , access_token = :access_token
                                      , access_expire_in = :access_expire_in
                                      , refresh_token = :refresh_token
                                      , refresh_expire_in = :refresh_expire_in
                                  where sns_id = :sns_id
                                 """)

                await db.execute(
                    query,
                    {
                        "sns_id": db_rst[0].get("sns_id"),
                        "temp_issued_key": tmp_key,
                        "access_token": access_token,
                        "access_expire_in": access_expires_in,
                        "refresh_token": refresh_token,
                        "refresh_expire_in": refresh_expires_in,
                    },
                )
            else:
                query = text("""
                                 select a.user_id
                                      , a.birthdate
                                      , a.gender
                                      , a.role_type
                                   from tb_user a
                                  where a.kc_user_id = :kc_user_id
                                    and a.use_yn = 'Y'
                                 """)

                result = await db.execute(query, {"kc_user_id": id})
                db_rst = result.mappings().all()

                if (
                    call_from == CommonConstants.ROLE_ADMIN
                    and db_rst[0].get("role_type") == CommonConstants.ROLE_NORMAL
                ):  # 일반 사용자 계정으로 관리자 로그인 -> 로그인이 되면 안됨
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.ADMIN_ACCOUNT_REQUIRED,
                    )

                user_id = ""
                birthdate = ""
                gender = ""
                if db_rst:
                    user_id = db_rst[0].get("user_id")
                    birthdate = db_rst[0].get("birthdate")
                    gender = db_rst[0].get("gender")
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_LOGIN_INFO,
                    )

                auth_data = {
                    "accessToken": access_token,
                    "accessTokenExpiresIn": access_expires_in,
                    "refreshToken": refresh_token,
                    "refreshTokenExpiresIn": refresh_expires_in,
                    "recentSignInType": latest_signed_type,
                    "userId": user_id,
                    "birthDate": birthdate,
                    "gender": gender,
                }

            # 로그인 성공 시점에 로그 기록
            if user_id:
                await statistics_service.insert_site_statistics_log(
                    db=db, type="login", user_id=user_id
                )
    except CustomResponseException:
        raise
    except OperationalError:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )

    res_data = {"auth": auth_data}

    res_body = {"data": res_data}

    return res_body


async def get_auth_signin_naver_callback(
    db: AsyncSession,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    if error:
        raise CustomResponseException(
            status_code=int(error),
            message=ErrorMessages.EXTERNAL_API_ERROR,
        )

    if state:
        # N-likenovel 혹은 Y-likenovel 형식 체크
        chk_flag = "N"
        if len(state) != 11:
            chk_flag = "Y"
        elif state[0] not in ("N", "Y"):
            chk_flag = "Y"
        elif state[1:] != "-likenovel":
            chk_flag = "Y"

        if chk_flag == "Y":
            raise CustomResponseException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                message=ErrorMessages.INVALID_STATE,
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=ErrorMessages.INVALID_STATE,
        )

    """
    sns_token_endpoint (post)
      전달받은 code, state를 사용해서 네이버 토큰 발급
    """
    res_json = await comm_service.sns_token_endpoint(
        method="POST", type="naver", code=code, state=state
    )
    naver_access_token = res_json.get("access_token")

    """
    sns_me_endpoint (get)
      네이버 access 토큰을 이용하여 프로필 API 호출
    """
    res_json = await comm_service.sns_me_endpoint(
        method="GET", type="naver", sns_acc_token=naver_access_token
    )
    tmp_res_json = res_json.get("response")
    naver_link_id = tmp_res_json.get("id")
    naver_email = (
        tmp_res_json.get("email") if tmp_res_json.get("email") else "none@naver.com"
    )

    try:
        async with db.begin():
            query = text("""
                             select a.kc_user_id
                               from tb_user a
                              where exists (select 1 from tb_user_social z
                                             where a.user_id = z.user_id
                                               and z.sns_link_id = :sns_link_id
                                               and z.sns_type = 'naver')
                                and a.use_yn = 'Y'
                             """)

            result = await db.execute(query, {"sns_link_id": naver_link_id})
            db_rst = result.mappings().all()

            # tb_user_social에 없으면 tb_user에서 확인 (오래된 계정 대응)
            if not db_rst:
                query = text("""
                             select a.kc_user_id
                               from tb_user a
                              where a.email = :email
                                and a.latest_signed_type = 'naver'
                                and a.use_yn = 'Y'
                             """)
                result = await db.execute(query, {"email": naver_email})
                db_rst = result.mappings().all()

            if db_rst:
                # 기 등록(로그인)
                kc_user_id = db_rst[0].get("kc_user_id")
                keep_signin_yn = state[0]

                type = "client_normal" if keep_signin_yn == "N" else "client_keep"

                res_json = await comm_service.kc_token_endpoint(
                    method="POST", type=type
                )
                admin_acc_token = res_json.get("access_token")

                """
                kc_users_id_endpoint (get)
                  user 회원정보 조회 후 username 조회
                """
                try:
                    res_json = await comm_service.kc_users_id_endpoint(
                        method="GET", admin_acc_token=admin_acc_token, id=kc_user_id
                    )
                    username = res_json.get("username")

                    """
                    로그인 처리 전달
                    """
                    res_body = {
                        "email": naver_email,
                        "password": settings.NAVER_PASSWORD,
                        "keep_signin_yn": keep_signin_yn,
                        "sns_signup_type": "naver",
                        "sns_link_id": username,
                    }
                except CustomResponseException as e:
                    # Keycloak에서 사용자를 찾지 못한 경우 (DB와 Keycloak 불일치)
                    # DB 데이터로 Keycloak에 사용자 생성 후 로그인 처리
                    if e.status_code == 404:
                        logger.warning(
                            f"Keycloak user not found for kc_user_id: {kc_user_id}, creating Keycloak user from DB data"
                        )

                        # DB에서 사용자 정보 조회
                        query = text("""
                            SELECT email, birthdate, gender
                            FROM tb_user
                            WHERE kc_user_id = :kc_user_id
                              AND use_yn = 'Y'
                        """)
                        result = await db.execute(query, {"kc_user_id": kc_user_id})
                        user_data = result.mappings().one()

                        # Keycloak 사용자 생성
                        import secrets

                        new_username = secrets.token_urlsafe(16)

                        res_json = await comm_service.kc_users_endpoint(
                            method="POST",
                            admin_acc_token=admin_acc_token,
                            data_dict={
                                "username": new_username,
                                "email": user_data["email"],
                                "enabled": True,
                                "credentials": [
                                    {
                                        "type": "password",
                                        "value": settings.NAVER_PASSWORD,
                                        "temporary": False,
                                    }
                                ],
                            },
                        )

                        # 생성된 사용자의 Keycloak ID 조회
                        res_json = await comm_service.kc_users_endpoint(
                            method="GET",
                            admin_acc_token=admin_acc_token,
                            username=new_username,
                        )
                        new_kc_user_id = res_json[0].get("id")

                        # DB의 kc_user_id 업데이트
                        query = text("""
                            UPDATE tb_user
                            SET kc_user_id = :new_kc_user_id
                            WHERE kc_user_id = :old_kc_user_id
                              AND use_yn = 'Y'
                        """)
                        await db.execute(
                            query,
                            {
                                "new_kc_user_id": new_kc_user_id,
                                "old_kc_user_id": kc_user_id,
                            },
                        )
                        await db.commit()

                        logger.info(
                            f"Created Keycloak user {new_kc_user_id} for existing DB user"
                        )

                        # 로그인 처리
                        res_body = {
                            "email": naver_email,
                            "password": settings.NAVER_PASSWORD,
                            "keep_signin_yn": keep_signin_yn,
                            "sns_signup_type": "naver",
                            "sns_link_id": new_username,
                        }
                    else:
                        raise
            else:
                # 미등록 계정 - 에러 반환
                raise CustomResponseException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=ErrorMessages.NOT_REGISTERED_ACCOUNT,
                )
    except OperationalError:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )

    return res_body


async def get_auth_signin_google_callback(
    db: AsyncSession,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    logger.info(
        f"Google Signin Callback - code: {code[:10] if code else None}..., state: {state}, error: {error}"
    )

    if error:
        logger.error(f"Google OAuth Error - error: {error}")
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=f"구글 로그인 오류: {error}",
        )

    pattern = r"^(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"  # YYYY-MM-DD

    if state:
        # N-1900-01-01-M-likenovel 형식 체크
        chk_flag = "N"
        if len(state) != 24:
            chk_flag = "Y"
        elif state[0] not in ("N", "Y"):
            chk_flag = "Y"
        elif re.match(pattern, state[2:12]) is None:
            chk_flag = "Y"
        elif state[13] not in ("M", "F"):
            chk_flag = "Y"
        elif state[14:] != "-likenovel":
            chk_flag = "Y"

        if chk_flag == "Y":
            raise CustomResponseException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                message=ErrorMessages.INVALID_STATE,
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=ErrorMessages.INVALID_STATE,
        )

    """
    sns_token_endpoint (post)
      전달받은 code, state를 사용해서 구글 토큰 발급
    """
    redirect_uri = settings.GOOGLE_SIGNIN_REDIRECT_URL
    res_json = await comm_service.sns_token_endpoint(
        method="POST", type="google", code=code, state=state, redirect_uri=redirect_uri
    )
    google_access_token = res_json.get("access_token")

    """
    sns_me_endpoint (get)
      구글 access 토큰을 이용하여 프로필 API 호출
    """
    res_json = await comm_service.sns_me_endpoint(
        method="GET", type="google", sns_acc_token=google_access_token
    )
    google_link_id = res_json.get("id")
    google_email = res_json.get("email") if res_json.get("email") else "none@gmail.com"

    try:
        async with db.begin():
            query = text("""
                             select a.kc_user_id
                               from tb_user a
                              where exists (select 1 from tb_user_social z
                                             where a.user_id = z.user_id
                                               and z.sns_link_id = :sns_link_id
                                               and z.sns_type = 'google')
                                and a.use_yn = 'Y'
                             """)

            result = await db.execute(query, {"sns_link_id": google_link_id})
            db_rst = result.mappings().all()

            # tb_user_social에 없으면 tb_user에서 확인 (오래된 계정 대응)
            if not db_rst:
                query = text("""
                             select a.kc_user_id
                               from tb_user a
                              where a.email = :email
                                and a.latest_signed_type = 'google'
                                and a.use_yn = 'Y'
                             """)
                result = await db.execute(query, {"email": google_email})
                db_rst = result.mappings().all()

            if db_rst:
                # 기 등록(로그인)
                kc_user_id = db_rst[0].get("kc_user_id")
                keep_signin_yn = state[0]

                type = "client_normal" if keep_signin_yn == "N" else "client_keep"

                res_json = await comm_service.kc_token_endpoint(
                    method="POST", type=type
                )
                admin_acc_token = res_json.get("access_token")

                """
                kc_users_id_endpoint (get)
                  user 회원정보 조회 후 username 조회
                """
                try:
                    res_json = await comm_service.kc_users_id_endpoint(
                        method="GET", admin_acc_token=admin_acc_token, id=kc_user_id
                    )
                    username = res_json.get("username")

                    """
                    로그인 처리 전달
                    """
                    res_body = {
                        "email": google_email,
                        "password": settings.GOOGLE_PASSWORD,
                        "keep_signin_yn": keep_signin_yn,
                        "sns_signup_type": "google",
                        "sns_link_id": username,
                    }
                except CustomResponseException as e:
                    # Keycloak에서 사용자를 찾지 못한 경우 (DB와 Keycloak 불일치)
                    # DB 데이터로 Keycloak에 사용자 생성 후 로그인 처리
                    if e.status_code == 404:
                        logger.warning(
                            f"Keycloak user not found for kc_user_id: {kc_user_id}, creating Keycloak user from DB data"
                        )

                        # DB에서 사용자 정보 조회
                        query = text("""
                            SELECT email, birthdate, gender
                            FROM tb_user
                            WHERE kc_user_id = :kc_user_id
                              AND use_yn = 'Y'
                        """)
                        result = await db.execute(query, {"kc_user_id": kc_user_id})
                        user_data = result.mappings().one()

                        # Keycloak 사용자 생성
                        import secrets

                        new_username = secrets.token_urlsafe(16)

                        res_json = await comm_service.kc_users_endpoint(
                            method="POST",
                            admin_acc_token=admin_acc_token,
                            data_dict={
                                "username": new_username,
                                "email": user_data["email"],
                                "enabled": True,
                                "credentials": [
                                    {
                                        "type": "password",
                                        "value": settings.GOOGLE_PASSWORD,
                                        "temporary": False,
                                    }
                                ],
                            },
                        )

                        # 생성된 사용자의 Keycloak ID 조회
                        res_json = await comm_service.kc_users_endpoint(
                            method="GET",
                            admin_acc_token=admin_acc_token,
                            username=new_username,
                        )
                        new_kc_user_id = res_json[0].get("id")

                        # DB의 kc_user_id 업데이트
                        query = text("""
                            UPDATE tb_user
                            SET kc_user_id = :new_kc_user_id
                            WHERE kc_user_id = :old_kc_user_id
                              AND use_yn = 'Y'
                        """)
                        await db.execute(
                            query,
                            {
                                "new_kc_user_id": new_kc_user_id,
                                "old_kc_user_id": kc_user_id,
                            },
                        )
                        await db.commit()

                        logger.info(
                            f"Created Keycloak user {new_kc_user_id} for existing DB user"
                        )

                        # 로그인 처리
                        res_body = {
                            "email": google_email,
                            "password": settings.GOOGLE_PASSWORD,
                            "keep_signin_yn": keep_signin_yn,
                            "sns_signup_type": "google",
                            "sns_link_id": new_username,
                        }
                    else:
                        raise
            else:
                # 미등록 계정 - 에러 반환
                raise CustomResponseException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=ErrorMessages.NOT_REGISTERED_ACCOUNT,
                )
    except OperationalError:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )

    return res_body


async def get_auth_signin_kakao_callback(
    db: AsyncSession,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    logger.info(
        f"Kakao Signin Callback - code: {code[:10] if code else None}..., state: {state}, error: {error}"
    )

    if error:
        logger.error(f"Kakao OAuth Error - error: {error}")
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=f"카카오 로그인 오류: {error}",
        )

    if state:
        # N-likenovel 혹은 Y-likenovel 형식 체크
        chk_flag = "N"
        if len(state) != 11:
            chk_flag = "Y"
        elif state[0] not in ("N", "Y"):
            chk_flag = "Y"
        elif state[1:] != "-likenovel":
            chk_flag = "Y"

        if chk_flag == "Y":
            raise CustomResponseException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                message=ErrorMessages.INVALID_STATE,
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=ErrorMessages.INVALID_STATE,
        )

    """
    sns_token_endpoint (post)
      전달받은 code, state를 사용해서 카카오 토큰 발급
    """
    redirect_uri = settings.KAKAO_SIGNIN_REDIRECT_URL
    res_json = await comm_service.sns_token_endpoint(
        method="POST", type="kakao", code=code, state=state, redirect_uri=redirect_uri
    )
    kakao_access_token = res_json.get("access_token")

    """
    sns_me_endpoint (get)
      카카오 access 토큰을 이용하여 프로필 API 호출
    """
    res_json = await comm_service.sns_me_endpoint(
        method="GET", type="kakao", sns_acc_token=kakao_access_token
    )
    kakao_link_id = str(res_json.get("id"))
    if res_json.get("kakao_account"):
        kakao_email = (
            res_json.get("kakao_account").get("email")
            if res_json.get("kakao_account").get("email")
            else "none@kakao.com"
        )
    else:
        kakao_email = "none@kakao.com"

    try:
        async with db.begin():
            query = text("""
                             select a.kc_user_id
                               from tb_user a
                              where exists (select 1 from tb_user_social z
                                             where a.user_id = z.user_id
                                               and z.sns_link_id = :sns_link_id
                                               and z.sns_type = 'kakao')
                                and a.use_yn = 'Y'
                             """)

            result = await db.execute(query, {"sns_link_id": kakao_link_id})
            db_rst = result.mappings().all()

            # tb_user_social에 없으면 tb_user에서 확인 (오래된 계정 대응)
            if not db_rst:
                query = text("""
                             select a.kc_user_id
                               from tb_user a
                              where a.email = :email
                                and a.latest_signed_type = 'kakao'
                                and a.use_yn = 'Y'
                             """)
                result = await db.execute(query, {"email": kakao_email})
                db_rst = result.mappings().all()

            if db_rst:
                # 기 등록(로그인)
                kc_user_id = db_rst[0].get("kc_user_id")
                keep_signin_yn = state[0]

                type = "client_normal" if keep_signin_yn == "N" else "client_keep"

                res_json = await comm_service.kc_token_endpoint(
                    method="POST", type=type
                )
                admin_acc_token = res_json.get("access_token")

                """
                kc_users_id_endpoint (get)
                  user 회원정보 조회 후 username 조회
                """
                try:
                    res_json = await comm_service.kc_users_id_endpoint(
                        method="GET", admin_acc_token=admin_acc_token, id=kc_user_id
                    )
                    username = res_json.get("username")

                    """
                    로그인 처리 전달
                    """
                    res_body = {
                        "email": kakao_email,
                        "password": settings.KAKAO_PASSWORD,
                        "keep_signin_yn": keep_signin_yn,
                        "sns_signup_type": "kakao",
                        "sns_link_id": username,
                    }
                except CustomResponseException as e:
                    # Keycloak에서 사용자를 찾지 못한 경우 (DB와 Keycloak 불일치)
                    # DB 데이터로 Keycloak에 사용자 생성 후 로그인 처리
                    if e.status_code == 404:
                        logger.warning(
                            f"Keycloak user not found for kc_user_id: {kc_user_id}, creating Keycloak user from DB data"
                        )

                        # DB에서 사용자 정보 조회
                        query = text("""
                            SELECT email, birthdate, gender
                            FROM tb_user
                            WHERE kc_user_id = :kc_user_id
                              AND use_yn = 'Y'
                        """)
                        result = await db.execute(query, {"kc_user_id": kc_user_id})
                        user_data = result.mappings().one()

                        # Keycloak에 사용자 생성
                        res_json = await comm_service.kc_token_endpoint(
                            method="POST", type="client_normal"
                        )
                        admin_acc_token = res_json.get("access_token")

                        # username 생성 (DB의 sns_link_id 사용)
                        import secrets

                        new_username = secrets.token_urlsafe(16)

                        # Keycloak 사용자 생성
                        res_json = await comm_service.kc_users_endpoint(
                            method="POST",
                            admin_acc_token=admin_acc_token,
                            data_dict={
                                "username": new_username,
                                "email": user_data["email"],
                                "enabled": True,
                                "credentials": [
                                    {
                                        "type": "password",
                                        "value": settings.KAKAO_PASSWORD,
                                        "temporary": False,
                                    }
                                ],
                            },
                        )

                        # 생성된 사용자의 Keycloak ID 조회
                        res_json = await comm_service.kc_users_endpoint(
                            method="GET",
                            admin_acc_token=admin_acc_token,
                            username=new_username,
                        )
                        new_kc_user_id = res_json[0].get("id")

                        # DB의 kc_user_id 업데이트
                        query = text("""
                            UPDATE tb_user
                            SET kc_user_id = :new_kc_user_id
                            WHERE kc_user_id = :old_kc_user_id
                              AND use_yn = 'Y'
                        """)
                        await db.execute(
                            query,
                            {
                                "new_kc_user_id": new_kc_user_id,
                                "old_kc_user_id": kc_user_id,
                            },
                        )
                        await db.commit()

                        logger.info(
                            f"Created Keycloak user {new_kc_user_id} for existing DB user"
                        )

                        # 로그인 처리
                        res_body = {
                            "email": kakao_email,
                            "password": settings.KAKAO_PASSWORD,
                            "keep_signin_yn": keep_signin_yn,
                            "sns_signup_type": "kakao",
                            "sns_link_id": new_username,
                        }
                    else:
                        raise
            else:
                # 미등록 계정 - 에러 반환
                raise CustomResponseException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=ErrorMessages.NOT_REGISTERED_ACCOUNT,
                )
    except OperationalError as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )

    return res_body


async def get_auth_signin_apple_callback(
    db: AsyncSession,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    if error:
        raise CustomResponseException(
            status_code=int(error),
            message=ErrorMessages.EXTERNAL_API_ERROR,
        )

    pattern = r"^(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"  # YYYY-MM-DD

    if state:
        # N-1900-01-01-M-likenovel 형식 체크
        chk_flag = "N"
        if len(state) != 24:
            chk_flag = "Y"
        elif state[0] not in ("N", "Y"):
            chk_flag = "Y"
        elif re.match(pattern, state[2:12]) is None:
            chk_flag = "Y"
        elif state[13] not in ("M", "F"):
            chk_flag = "Y"
        elif state[14:] != "-likenovel":
            chk_flag = "Y"

        if chk_flag == "Y":
            raise CustomResponseException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                message=ErrorMessages.INVALID_STATE,
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=ErrorMessages.INVALID_STATE,
        )

    """
    sns_token_endpoint (post)
      전달받은 code, state를 사용해서 애플 토큰 발급
    """
    redirect_uri = settings.APPLE_SIGNIN_REDIRECT_URL
    res_json = await comm_service.sns_token_endpoint(
        method="POST", type="apple", code=code, state=state, redirect_uri=redirect_uri
    )
    apple_id_token = res_json.get("id_token")

    """
    id token 값 디코딩 후 분석
      애플 id 토큰을 이용하여 프로필 조회
    """
    decoded_token = await comm_service.decode_apple_token(id_token=apple_id_token)

    apple_link_id = decoded_token.get("sub")
    apple_email = (
        decoded_token.get("email") if decoded_token.get("email") else "none@apple.com"
    )
    # @privaterelay.appleid.com 형식 필터링 필요
    if apple_email != "" and apple_email[0] == "@":
        apple_email = "none@apple.com"

    try:
        async with db.begin():
            query = text("""
                             select a.kc_user_id
                               from tb_user a
                              where exists (select 1 from tb_user_social z
                                             where a.user_id = z.user_id
                                               and z.sns_link_id = :sns_link_id
                                               and z.sns_type = 'apple')
                                and a.use_yn = 'Y'
                             """)

            result = await db.execute(query, {"sns_link_id": apple_link_id})
            db_rst = result.mappings().all()

            if db_rst:
                # 기 등록(로그인)
                kc_user_id = db_rst[0].get("kc_user_id")
                keep_signin_yn = state[0]

                type = "client_normal" if keep_signin_yn == "N" else "client_keep"

                res_json = await comm_service.kc_token_endpoint(
                    method="POST", type=type
                )
                admin_acc_token = res_json.get("access_token")

                """
                kc_users_id_endpoint (get)
                  user 회원정보 조회 후 username 조회
                """
                res_json = await comm_service.kc_users_id_endpoint(
                    method="GET", admin_acc_token=admin_acc_token, id=kc_user_id
                )
                username = res_json.get("username")

                """
                로그인 처리 전달
                """
                res_body = {
                    "email": apple_email,
                    "password": settings.APPLE_PASSWORD,
                    "keep_signin_yn": keep_signin_yn,
                    "sns_signup_type": "apple",
                    "sns_link_id": username,
                }
            else:
                # 미등록 계정 - 에러 반환
                raise CustomResponseException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=ErrorMessages.NOT_REGISTERED_ACCOUNT,
                )
    except OperationalError:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )

    return res_body


async def post_auth_identity_account_search(
    req_body: auth_schema.IdentityAccountSearchReqBody, db: AsyncSession
):
    logger.debug(f"Request body: {req_body}")

    # TODO: 본인인증 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)
    res_data = {}

    try:
        async with db.begin():
            query = text("""
                             select a.email
                                  , b.sns_type
                               from tb_user a
                              inner join tb_user_social b on a.user_id = b.user_id
                              where a.user_name = :user_name
                                and a.gender = :gender
                                and REPLACE(a.birthdate, '-', '') = REPLACE(:birthdate, '-', '')
                                and a.use_yn = 'Y'
                             """)

            result = await db.execute(
                query,
                {
                    "user_name": req_body.user_name,
                    "gender": req_body.gender,
                    "birthdate": req_body.birthdate,
                },
            )
            db_rst = result.mappings().all()

            if db_rst:
                sns_type = db_rst[0].get("sns_type")

                if sns_type == "likenovel":
                    email = db_rst[0].get("email")
                    id, domain = email.split("@")
                    if len(id) <= 4:
                        masked_id = id[:-1] + "*"
                    else:
                        masked_id = id[:-4] + "****"

                    res_data = {
                        "signUpType": sns_type,
                        "masked_email": f"{masked_id}@{domain}",
                        "email": email,
                    }
                else:
                    res_data = {
                        "signUpType": sns_type,
                        "masked_email": None,
                        "email": None,
                    }
            else:
                res_data = {"signUpType": None, "masked_email": None, "email": None}
    except OperationalError:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )

    res_body = {"data": res_data}
    logger.debug(f"Response body: {res_body}")

    return res_body


async def put_auth_identity_password_reset(
    req_body: auth_schema.IdentityPasswordResetReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    # TODO: 본인인증 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)
    try:
        async with db.begin():
            where_fields = []
            execute_params = {}
            if req_body.user_name is not None:
                where_fields.append("a.user_name = :user_name")
                execute_params["user_name"] = req_body.user_name
            if req_body.gender is not None:
                where_fields.append("a.gender = :gender")
                execute_params["gender"] = req_body.gender
            if req_body.birthdate is not None:
                where_fields.append(
                    "REPLACE(a.birthdate, '-', '') = REPLACE(:birthdate, '-', '')"
                )
                execute_params["birthdate"] = req_body.birthdate
            if req_body.email is not None:
                where_fields.append("a.email = :email")
                execute_params["email"] = req_body.email
            if (
                len(where_fields) == 0
            ):  # 위의 4개의 필드로 검색을 하는 로직인데, 위의 4개의 필드가 없으면 로그인한 유저의 정보로 검색
                if kc_user_id is None:
                    raise CustomResponseException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )
                where_fields.append("a.kc_user_id = :kc_user_id")
                execute_params["kc_user_id"] = kc_user_id
            query = text(f"""
                             select a.kc_user_id
                               from tb_user a
                              where {" and ".join(where_fields)}
                                and a.use_yn = 'Y'
                                and a.latest_signed_type = 'likenovel'
                             """)

            logger.info(f"Executing password reset query with params: {execute_params}")
            result = await db.execute(query, execute_params)
            db_rst = result.mappings().all()

            if not db_rst:
                # latest_signed_type 조건 없이 사용자 조회하여 상세한 에러 메시지 제공
                check_query = text(f"""
                                 select a.kc_user_id, a.use_yn, a.latest_signed_type
                                   from tb_user a
                                  where {" and ".join(where_fields)}
                                 """)
                check_result = await db.execute(check_query, execute_params)
                check_rst = check_result.mappings().all()

                if check_rst:
                    user_info = dict(check_rst[0])
                    # SNS 계정 체크
                    if user_info.get("latest_signed_type") in (
                        "naver",
                        "google",
                        "kakao",
                        "apple",
                    ):
                        raise CustomResponseException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            message=ErrorMessages.SNS_ACCOUNT_PASSWORD_RESET_NOT_ALLOWED,
                        )
                    # 탈퇴 계정 체크
                    elif user_info.get("use_yn") == "N":
                        raise CustomResponseException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            message=ErrorMessages.ALREADY_WITHDRAWN_MEMBER,
                        )
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        message=ErrorMessages.NOT_FOUND_USER,
                    )

            kc_user_id = dict(db_rst[0]).get("kc_user_id")

            res_json = await comm_service.kc_token_endpoint(
                method="POST", type="client_normal"
            )
            admin_acc_token = res_json.get("access_token")

            cred_data = {
                "type": "password",
                "value": req_body.password,
                "temporary": False,
            }

            cred_data_to_list = list()
            cred_data_to_list.append(cred_data)

            data = {"credentials": cred_data_to_list}

            try:
                # Keycloak에서 사용자 비밀번호 업데이트 시도
                logger.info(
                    f"Attempting to update password in Keycloak for kc_user_id: {kc_user_id}"
                )
                await comm_service.kc_users_id_endpoint(
                    method="PUT",
                    admin_acc_token=admin_acc_token,
                    id=kc_user_id,
                    data_dict=data,
                )
                logger.info(
                    f"Successfully updated password in Keycloak for kc_user_id: {kc_user_id}"
                )
            except CustomResponseException as e:
                # Keycloak에서 사용자를 찾지 못한 경우 (DB와 Keycloak 불일치)
                if e.status_code == 404:
                    logger.warning(
                        f"Keycloak user not found for kc_user_id: {kc_user_id}, starting recovery process"
                    )

                    # DB에서 사용자 정보 조회 (SNS 계정 체크 포함)
                    logger.info(
                        f"Fetching user info from DB for kc_user_id: {kc_user_id}"
                    )
                    query = text("""
                        SELECT email, latest_signed_type, use_yn
                        FROM tb_user
                        WHERE kc_user_id = :kc_user_id
                    """)
                    result = await db.execute(query, {"kc_user_id": kc_user_id})
                    user_data = result.mappings().one_or_none()

                    if not user_data:
                        logger.error(
                            f"User data not found in DB for kc_user_id: {kc_user_id}"
                        )
                        raise CustomResponseException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            message=ErrorMessages.NOT_FOUND_USER,
                        )

                    user_info = dict(user_data)

                    # 탈퇴 계정 체크
                    if user_info.get("use_yn") == "N":
                        logger.warning(f"Withdrawn member for kc_user_id: {kc_user_id}")
                        raise CustomResponseException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            message=ErrorMessages.ALREADY_WITHDRAWN_MEMBER,
                        )

                    # SNS 계정 체크
                    if user_info.get("latest_signed_type") in (
                        "naver",
                        "google",
                        "kakao",
                        "apple",
                    ):
                        logger.warning(
                            f"SNS account detected for kc_user_id: {kc_user_id}, "
                            f"type: {user_info.get('latest_signed_type')}"
                        )
                        raise CustomResponseException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            message=ErrorMessages.SNS_ACCOUNT_PASSWORD_RESET_NOT_ALLOWED,
                        )

                    # 자체 가입자만 복구 로직 진행
                    if user_info.get("latest_signed_type") != "likenovel":
                        logger.error(
                            f"Invalid latest_signed_type for kc_user_id: {kc_user_id}"
                        )
                        raise CustomResponseException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            message=ErrorMessages.NOT_FOUND_USER,
                        )

                    username = user_info["email"]  # 자체 가입자는 username = email
                    user_email = user_info["email"]

                    # Keycloak에서 이메일로 사용자 검색 (이미 존재하는 경우 확인)
                    logger.info(
                        f"Searching for existing Keycloak user with email: {user_email}"
                    )
                    try:
                        existing_users = await comm_service.kc_users_endpoint(
                            method="GET",
                            admin_acc_token=admin_acc_token,
                            params_dict={"email": user_email, "exact": "true"},
                        )

                        if existing_users and len(existing_users) > 0:
                            # 이미 Keycloak에 사용자가 존재하는 경우
                            existing_kc_user_id = existing_users[0].get("id")
                            logger.info(
                                f"Found existing Keycloak user with email: {user_email}, "
                                f"kc_user_id: {existing_kc_user_id}"
                            )

                            # DB의 kc_user_id를 기존 Keycloak 사용자의 ID로 업데이트
                            logger.info(
                                f"Syncing DB kc_user_id from {kc_user_id} to {existing_kc_user_id}"
                            )
                            query = text("""
                                UPDATE tb_user
                                SET kc_user_id = :new_kc_user_id
                                WHERE kc_user_id = :old_kc_user_id
                                  AND use_yn = 'Y'
                            """)
                            result = await db.execute(
                                query,
                                {
                                    "new_kc_user_id": existing_kc_user_id,
                                    "old_kc_user_id": kc_user_id,
                                },
                            )
                            await db.commit()
                            logger.info(
                                f"DB sync successful. Rows affected: {result.rowcount}"
                            )

                            # 비밀번호 업데이트 재시도
                            logger.info(
                                f"Retrying password update for synced kc_user_id: {existing_kc_user_id}"
                            )
                            await comm_service.kc_users_id_endpoint(
                                method="PUT",
                                admin_acc_token=admin_acc_token,
                                id=existing_kc_user_id,
                                data_dict=data,
                            )
                            logger.info(
                                f"Recovery completed: Synced DB with existing Keycloak user {existing_kc_user_id} "
                                f"and reset password"
                            )
                            return

                    except CustomResponseException as search_error:
                        logger.warning(
                            f"Error searching for existing Keycloak user: {search_error.status_code}, "
                            f"proceeding with user creation"
                        )

                    # Keycloak에 사용자가 없는 경우 새로 생성
                    logger.info(
                        f"Creating new Keycloak user with username: {username}, email: {user_email}"
                    )
                    try:
                        new_kc_user_id = await comm_service.kc_users_endpoint(
                            method="POST",
                            admin_acc_token=admin_acc_token,
                            data_dict={
                                "username": username,
                                "email": user_email,
                                "enabled": True,
                                "credentials": cred_data_to_list,
                            },
                        )
                        logger.info(
                            f"Successfully created Keycloak user with new kc_user_id: {new_kc_user_id}"
                        )
                    except CustomResponseException as create_error:
                        logger.error(
                            f"Failed to create Keycloak user for username: {username}, "
                            f"status_code: {create_error.status_code}, message: {create_error.message}"
                        )
                        raise

                    # DB의 kc_user_id 업데이트
                    logger.info(
                        f"Updating DB kc_user_id from {kc_user_id} to {new_kc_user_id}"
                    )
                    query = text("""
                        UPDATE tb_user
                        SET kc_user_id = :new_kc_user_id
                        WHERE kc_user_id = :old_kc_user_id
                          AND use_yn = 'Y'
                    """)
                    result = await db.execute(
                        query,
                        {
                            "new_kc_user_id": new_kc_user_id,
                            "old_kc_user_id": kc_user_id,
                        },
                    )
                    await db.commit()
                    logger.info(
                        f"DB update successful. Rows affected: {result.rowcount}"
                    )

                    logger.info(
                        f"Recovery completed: Created Keycloak user {new_kc_user_id} and reset password for existing DB user"
                    )
                else:
                    logger.error(
                        f"Failed to update Keycloak password for kc_user_id: {kc_user_id}, "
                        f"status_code: {e.status_code}, message: {e.message}"
                    )
                    raise
    except CustomResponseException:
        # CustomResponseException은 그대로 raise (정상적인 에러 응답)
        raise
    except OperationalError as e:
        logger.error(f"Database connection error in password reset: {e}")
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError as e:
        logger.error(f"Database operation error in password reset: {e}")
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception as e:
        logger.error(f"Unexpected error in password reset: {e}", exc_info=True)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )

    return


async def post_auth_signout(
    req_body: auth_schema.SignoutReqBody, kc_user_id: str, kc_client: str
):
    # access token이 만료된 경우, refresh_token에서 client 정보 추출
    if not kc_user_id or not kc_client:
        try:
            # refresh_token 디코딩 (검증 없이 payload만 추출)
            decoded_refresh = jwt.decode(
                jwt=req_body.refresh_token, options={"verify_signature": False}
            )
            kc_client = decoded_refresh.get("azp")
            logger.info(
                f"Signout with expired access token - using refresh token to get client: {kc_client}"
            )
        except Exception as e:
            logger.warning(f"Failed to decode refresh token during signout: {e}")
            # refresh token도 디코딩 실패하면 그냥 성공으로 처리 (이미 로그아웃된 상태로 간주)
            return

    if kc_client == settings.KC_CLIENT_ID:
        type = "logout_normal"
    elif kc_client == settings.KC_CLIENT_KEEP_SIGNIN_ID:
        type = "logout_keep"
    else:
        # 알 수 없는 client인 경우 그냥 성공으로 처리
        logger.warning(f"Unknown client during signout: {kc_client}")
        return

    try:
        await comm_service.kc_logout_endpoint(
            method="POST", type=type, user_ref_token=req_body.refresh_token
        )
    except CustomResponseException as e:
        # Keycloak 로그아웃 실패해도 클라이언트에는 성공으로 응답
        # (이미 세션이 만료되었을 수 있음)
        logger.warning(f"Keycloak logout failed but returning success: {e}")
        pass

    return


async def put_auth_signoff(kc_user_id: str, kc_client: str, db: AsyncSession):
    if kc_user_id:
        try:
            async with db.begin():
                query = text("""
                                 select user_id, email
                                   from tb_user
                                  where kc_user_id = :kc_user_id
                                    and use_yn = 'Y'
                                 """)

                result = await db.execute(query, {"kc_user_id": kc_user_id})
                db_rst = result.mappings().all()
                user_id = db_rst[0].get("user_id")
                original_email = db_rst[0].get("email")

                query = text("""
                                 select 1
                                   from tb_user_social
                                  where integrated_user_id = :user_id
                                    and default_yn = 'Y'
                                 """)

                result = await db.execute(query, {"user_id": user_id})
                db_rst = result.mappings().all()

                # 개별아이디 혹은 통합아이디 로그인 상태
                if db_rst:
                    # 통합아이디
                    # TODO: 통합아이디 연동 모듈 구현 후 수정 및 최종 테스트 필(현재 개별아이디 개발 완료. 나머지 초안 개발 완료)

                    # 탈퇴 시간 생성
                    import time

                    timestamp = int(time.time())
                    outed_email = f"outed;{timestamp};{original_email}"

                    query = text("""
                                     update tb_user a
                                      inner join (
                                         select z.user_id
                                           from tb_user_social z
                                          where z.integrated_user_id = :user_id
                                      ) as t on a.user_id = t.user_id
                                       set a.use_yn = 'N',
                                           a.email = :outed_email
                                     where 1=1
                                     """)

                    await db.execute(
                        query, {"user_id": user_id, "outed_email": outed_email}
                    )

                    # tb_algorithm_recommend_user 레코드 삭제
                    query = text("""
                                     delete from tb_algorithm_recommend_user
                                      where user_id in (
                                         select z.user_id
                                           from tb_user_social z
                                          where z.integrated_user_id = :user_id
                                      )
                                     """)

                    await db.execute(query, {"user_id": user_id})

                    type = ""
                    if kc_client == settings.KC_CLIENT_ID:
                        type = "client_normal"
                    elif kc_client == settings.KC_CLIENT_KEEP_SIGNIN_ID:
                        type = "client_keep"

                    res_json = await comm_service.kc_token_endpoint(
                        method="POST", type=type
                    )
                    admin_acc_token = res_json.get("access_token")

                    """
                    kc_users_id_endpoint (delete)
                      user 회원정보 delete
                      user_entity의 enabled False 처리 대신에, 이후 재가입할 경우 완전한 초기화 방향으로
                    """
                    query = text("""
                                     select a.kc_user_id
                                       from tb_user a
                                      where a.user_id in (select z.user_id from tb_user_social z
                                                           where z.integrated_user_id = :user_id)
                                     """)

                    result = await db.execute(query, {"user_id": user_id})
                    db_rst = result.mappings().all()

                    for row in db_rst:
                        kc_user_id = row.get("kc_user_id")
                        await comm_service.kc_users_id_endpoint(
                            method="DELETE",
                            admin_acc_token=admin_acc_token,
                            id=kc_user_id,
                        )

                    query = text("""
                                     delete from tb_user_social a
                                      where a.user_id in (select z.user_id from tb_user_social z
                                                           where z.integrated_user_id = :user_id)
                                     """)

                    await db.execute(query, {"user_id": user_id})
                else:
                    # 개별아이디

                    # 탈퇴 시간 생성
                    import time

                    timestamp = int(time.time())
                    outed_email = f"outed;{timestamp};{original_email}"

                    query = text("""
                                     update tb_user
                                        set use_yn = 'N',
                                            email = :outed_email
                                      where user_id = :user_id
                                     """)

                    await db.execute(
                        query, {"user_id": user_id, "outed_email": outed_email}
                    )

                    # tb_algorithm_recommend_user 레코드 삭제
                    query = text("""
                                     delete from tb_algorithm_recommend_user
                                      where user_id = :user_id
                                     """)

                    await db.execute(query, {"user_id": user_id})

                    query = text("""
                                     delete from tb_user_social
                                      where user_id = :user_id
                                     """)

                    await db.execute(query, {"user_id": user_id})

                    type = ""
                    if kc_client == settings.KC_CLIENT_ID:
                        type = "client_normal"
                    elif kc_client == settings.KC_CLIENT_KEEP_SIGNIN_ID:
                        type = "client_keep"

                    res_json = await comm_service.kc_token_endpoint(
                        method="POST", type=type
                    )
                    admin_acc_token = res_json.get("access_token")

                    """
                    kc_users_id_endpoint (delete)
                      user 회원정보 delete
                      user_entity의 enabled False 처리 대신에, 이후 재가입할 경우 완전한 초기화 방향으로
                    """
                    await comm_service.kc_users_id_endpoint(
                        method="DELETE", admin_acc_token=admin_acc_token, id=kc_user_id
                    )
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


async def put_auth_token_reissue(req_body: auth_schema.TokenReissueReqBody):
    try:
        signing_key = await get_kc_signing_key(req_body.access_token)
        decoded_token = jwt.decode(
            jwt=req_body.access_token,
            # JWKS(kid) 기반 공개키를 우선 사용하고, 실패 시 기존 하드코딩 키로 fallback 합니다.
            key=signing_key or settings.KC_PUBLIC_KEY,
            algorithms=settings.KC_PK_ALGORITHMS,
            issuer=settings.KC_ISSUER_BASE_URL,
            audience=settings.KC_AUDIENCE,
            options={"verify_exp": False},
        )
    except jwt.InvalidTokenError:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_REFRESH_TOKEN,
        )

    kc_client = decoded_token.get("azp")

    data = {"refresh_token": req_body.refresh_token}

    type = ""
    if kc_client == settings.KC_CLIENT_ID:
        type = "reissue_normal"
    elif kc_client == settings.KC_CLIENT_KEEP_SIGNIN_ID:
        type = "reissue_keep"

    res_json = await comm_service.kc_token_endpoint(
        method="POST", type=type, data_dict=data
    )
    access_token = res_json.get("access_token")
    access_expires_in = res_json.get("access_expires_in")
    refresh_token = res_json.get("refresh_token")

    if access_token is None or refresh_token is None:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_REFRESH_TOKEN,
        )

    token_data = {
        "accessToken": access_token,
        "accessTokenExpiresIn": access_expires_in,
    }

    res_data = {"token": token_data}

    res_body = {"data": res_data}

    return res_body


async def put_auth_token_relay_callback(
    req_body: auth_schema.TokenRelayReqBody, db: AsyncSession
):
    auth_data = {}

    try:
        async with db.begin():
            query = text("""
                             select a.user_id
                                  , a.birthdate
                                  , a.gender
                                  , b.access_token
                                  , b.access_expire_in
                                  , b.refresh_token
                                  , b.refresh_expire_in
                                  , b.sns_type
                               from tb_user a
                              inner join tb_user_social b on a.user_id = b.user_id
                                and b.sns_id = :sns_id
                                and b.temp_issued_key = :temp_issued_key
                              where a.use_yn = 'Y'
                             """)

            result = await db.execute(
                query,
                {
                    "sns_id": req_body.sns_id,
                    "temp_issued_key": req_body.temp_issued_key,
                },
            )
            db_rst = result.mappings().all()

            if db_rst:
                accessToken = db_rst[0].get("access_token")
                accessTokenExpiresIn = db_rst[0].get("access_expire_in")
                refreshToken = db_rst[0].get("refresh_token")
                refreshTokenExpiresIn = db_rst[0].get("refresh_expire_in")
                recentSignInType = db_rst[0].get("sns_type")
                userId = db_rst[0].get("user_id")
                birthDate = db_rst[0].get("birthdate")
                gender = db_rst[0].get("gender")

                auth_data = {
                    "accessToken": accessToken,
                    "accessTokenExpiresIn": accessTokenExpiresIn,
                    "refreshToken": refreshToken,
                    "refreshTokenExpiresIn": refreshTokenExpiresIn,
                    "recentSignInType": recentSignInType,
                    "userId": userId,
                    "birthDate": birthDate,
                    "gender": gender,
                }

                query = text("""
                                 update tb_user_social
                                    set temp_issued_key = null
                                      , access_token = null
                                      , access_expire_in = null
                                      , refresh_token = null
                                      , refresh_expire_in = null
                                  where sns_id = :sns_id
                                 """)

                await db.execute(query, {"sns_id": req_body.sns_id})
    except OperationalError:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )

    res_data = {"auth": auth_data}

    res_body = {"data": res_data}

    return res_body


async def post_identity_token_for_password(
    req_body: auth_schema.IdentityTokenForPasswordReqBody, db: AsyncSession
):
    """
    본인인증 토큰 발급(비밀번호 찾기용)
    """
    res_data = {}
    secure_token_headers = {}
    secure_token_data = {}
    secure_token_res_data = {}

    try:
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

                #     if res_data.get("dataHeader").get("GW_RSLT_CD") == "1200":
                #         # 암호화 토큰 통신 성공
                #         return {"_data": res_data}
                #     else:
                #         # 암호화 토큰 통신 실패
                #         pass

    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )

    return {
        "institution_token_response": res_data,
        "encrypted_token_headers": secure_token_headers,
        "encrypted_token_data": secure_token_data,
        "encrypted_token_response": secure_token_res_data,
    }
