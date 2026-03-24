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
                    up.*,
                    CASE
                        WHEN u.role_type = 'admin' THEN 'admin'
                        WHEN (SELECT apply_type FROM tb_user_profile_apply
                              WHERE user_id = u.user_id AND approval_date IS NOT NULL
                              ORDER BY created_date DESC LIMIT 1) = 'cp' THEN 'CP'
                        ELSE 'author'
                    END as role_type,
                    {get_file_path_sub_query("up.profile_image_id", "profile_image_path")}
                 FROM tb_user_profile up
                 INNER JOIN tb_user u ON u.user_id = up.user_id
                 WHERE up.user_id = :user_id
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
                 SELECT *
                 FROM tb_standard_keyword
                 WHERE use_yn = 'Y'
                   AND category_id = 1
                 ORDER BY CASE keyword_name
                    WHEN '무협' THEN 1
                    WHEN '판타지' THEN 2
                    WHEN '퓨전' THEN 3
                    WHEN '게임' THEN 4
                    WHEN '스포츠' THEN 5
                    WHEN '로맨스' THEN 6
                    WHEN '라이트노벨' THEN 7
                    WHEN '현대판타지' THEN 8
                    WHEN '대체역사' THEN 9
                    WHEN '전쟁·밀리터리' THEN 10
                    WHEN 'SF' THEN 11
                    WHEN '추리' THEN 12
                    WHEN '공포·미스테리' THEN 13
                    WHEN '일반소설' THEN 14
                    WHEN '드라마' THEN 15
                    WHEN '팬픽·패러디' THEN 16
                    ELSE 999
                 END, keyword_id ASC
                 """)
    result = await db.execute(query, {})
    rows = result.mappings().all()
    return [dict(row) for row in rows]


async def get_cp_company_name_list(db: AsyncSession, user_data: dict):
    """
    CP 회사명 리스트 조회

    Args:
        db: 데이터베이스 세션
        user_data: 사용자 정보 딕셔너리 (user_id, role)

    Returns:
        CP 회사명 리스트
    """
    if user_data["role"] == "CP":
        query = text("""
                 SELECT DISTINCT company_name
                   FROM tb_user_profile_apply
                  WHERE apply_type = 'cp'
                    AND approval_code = 'accepted'
                    AND approval_date IS NOT NULL
                    AND user_id = :user_id
                  ORDER BY company_name ASC
                 """)
        params = {"user_id": user_data["user_id"]}
    else:
        query = text("""
                 SELECT DISTINCT company_name
                   FROM tb_user_profile_apply
                  WHERE apply_type = 'cp'
                    AND approval_code = 'accepted'
                    AND approval_date IS NOT NULL
                  ORDER BY company_name ASC
                 """)
        params = {}

    result = await db.execute(query, params)
    rows = result.mappings().all()
    return [dict(row) for row in rows]
