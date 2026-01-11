import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.query import get_file_path_sub_query
from app.utils.response import check_exists_or_404
from app.const import ErrorMessages

logger = logging.getLogger("partner_app")


async def partner_detail_by_user_id(user_id, db: AsyncSession):
    """
    파트너 상세 조회

    Args:
        user_id: 사용자 ID
        db: 데이터베이스 세션

    Returns:
        사용자 정보 딕셔너리
    """
    query = text("""
                    SELECT * FROM tb_user WHERE user_id = :user_id
                    """)
    result = await db.execute(query, {"user_id": user_id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_MEMBER)

    return dict(rows[0])


async def partner_profiles_of_partner(user_id, db: AsyncSession):
    """
    파트너 프로필 조회

    Args:
        user_id: 사용자 ID
        db: 데이터베이스 세션

    Returns:
        사용자 프로필 리스트
    """
    await partner_detail_by_user_id(user_id, db)

    query = text(f"""
                 SELECT
                    *,
                    {get_file_path_sub_query("up.profile_image_id", "profile_image_path")}
                 FROM tb_user_profile up WHERE user_id = :user_id
                 """)
    result = await db.execute(query, {"user_id": user_id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_MEMBER)

    return [dict(row) for row in rows]


async def get_genre_list(db: AsyncSession):
    """
    1차, 2차 장르 리스트 조회

    Args:
        db: 데이터베이스 세션

    Returns:
        장르 리스트
    """
    query = text("""
                 SELECT * FROM tb_standard_keyword WHERE use_yn = 'Y' AND major_genre_yn = 'Y' AND category_id = 1 ORDER BY keyword_id ASC
                 """)
    result = await db.execute(query, {})
    rows = result.mappings().all()
    return [dict(row) for row in rows]


async def get_cp_company_name_list(db: AsyncSession):
    """
    CP 회사명 리스트 조회

    Args:
        db: 데이터베이스 세션

    Returns:
        CP 회사명 리스트
    """
    query = text("""
                 SELECT DISTINCT company_name FROM tb_user_profile_apply ORDER BY company_name ASC
                 """)
    result = await db.execute(query, {})
    rows = result.mappings().all()
    return [dict(row) for row in rows]
