from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from functools import wraps
import logging

from app.exceptions import CustomResponseException
from app.const import ErrorMessages

"""
기타 공통 유틸 함수 모음
"""

logger = logging.getLogger(__name__)


def handle_exceptions(func):
    """
    서비스 함수의 공통 예외 처리 데코레이터.

    CustomResponseException은 그대로 전파하고,
    OperationalError는 503, SQLAlchemyError와 기타 Exception은 500으로 변환합니다.

    사용 예시:
        @handle_exceptions
        async def my_service_function(...):
            ...
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except CustomResponseException:
            raise
        except OperationalError as e:
            logger.error(f"[{func.__name__}] OperationalError: {e}")
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError as e:
            logger.error(f"[{func.__name__}] SQLAlchemyError: {e}")
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.error(f"[{func.__name__}] Exception: {e}")
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    return wrapper


def age_2_age_group(age: int | str | None) -> int:
    if isinstance(age, str):
        if age.isdigit():
            return age_2_age_group(int(age))
        else:
            # 숫자가 아니라서 변환 불가
            return -1
    if age is None or (isinstance(age, int) and age < 0):
        return -1
    if age < 20:
        return 1  # 10대 이하
    if age < 30:
        return 2  # 20대
    if age < 40:
        return 3  # 30대
    if age < 50:
        return 4  # 40대
    if age < 60:
        return 5  # 50대
    return 6  # 60대 이상


async def check_user(kc_user_id: str | None, db: AsyncSession, role: str = "") -> dict:
    """
    사용자 정보 체크 및 반환

    Args:
        kc_user_id: Keycloak 사용자 ID
        db: 데이터베이스 세션
        role: 체크할 역할 (admin: 관리자, partner: CP, author: 작가, 빈값: 전체)

    Returns:
        사용자 정보 딕셔너리 (user_id, role)
    """
    if kc_user_id is None:
        # 비로그인
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED, message=ErrorMessages.LOGIN_PLEASE
        )
    query = text("""
        select user_id, role_type, (select apply_type from tb_user_profile_apply where user_id = u.user_id order by created_date desc limit 1) as apply_type from tb_user u where kc_user_id = :kc_user_id
    """)
    results = await db.execute(query, {"kc_user_id": kc_user_id})
    row = results.mappings().one_or_none()
    if row is None:
        # 사용자 데이터가 없는 경우
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED, message=ErrorMessages.LOGIN_PLEASE
        )
    user = dict(row)
    if role == "admin":
        # 관리자 계정인지 체크
        if user["role_type"] != "admin":
            # 관리자 계정이 아니면 에러
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.ADMIN_LOGIN_REQUIRED,
            )
    if user["role_type"] == "admin":
        return {"user_id": int(user["user_id"]), "role": "admin"}
    elif user["apply_type"] == "cp":
        return {"user_id": int(user["user_id"]), "role": "partner"}
    elif user["apply_type"] == "editor":
        return {"user_id": int(user["user_id"]), "role": "author"}
    return {"user_id": int(user["user_id"]), "role": "author"}
