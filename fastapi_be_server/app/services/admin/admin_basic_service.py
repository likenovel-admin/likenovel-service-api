import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import ErrorMessages
import app.schemas.admin as admin_schema
from app.utils.query import build_update_query, get_file_path_sub_query
from app.utils.response import check_exists_or_404

logger = logging.getLogger("admin_app")

"""
관리자 기본 서비스 함수 모음
"""


async def get_latest_updated_date(table_name: str, db: AsyncSession):
    """
    테이블의 최신 업데이트 날짜 조회

    Args:
        table_name: 조회할 테이블명
        db: 데이터베이스 세션

    Returns:
        최신 업데이트 날짜 (created_date 또는 updated_date 중 최신값)
    """
    query = text(f"""
                 SELECT MAX(IF(updated_date IS NULL, created_date, updated_date)) AS latest_updated_date FROM {table_name}
                 """)
    result = await db.execute(query, {})
    row = result.mappings().one()
    return dict(row).get("latest_updated_date")


async def admin_detail_by_user_id(user_id, db: AsyncSession):
    """
    관리자(admin) 상세 조회

    Args:
        user_id: 조회할 관리자 ID
        db: 데이터베이스 세션

    Returns:
        관리자 상세 정보
    """
    query = text("""
                    SELECT * FROM tb_user WHERE user_id = :user_id AND role_type = "admin"
                    """)
    result = await db.execute(query, {"user_id": user_id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_MEMBER)

    return dict(rows[0])


async def admin_profiles_of_admin(user_id, db: AsyncSession):
    """
    관리자(admin) 프로필 조회

    Args:
        user_id: 조회할 관리자 ID
        db: 데이터베이스 세션

    Returns:
        관리자 프로필 리스트
    """
    await admin_detail_by_user_id(user_id, db)

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


async def put_user(
    user_id: int, req_body: admin_schema.PutUserReqBody, db: AsyncSession
):
    """
    사용자 정보 수정

    Args:
        user_id: 수정할 사용자 ID
        req_body: 수정할 사용자 정보 (역할 타입 등)
        db: 데이터베이스 세션

    Returns:
        수정 결과 정보
    """

    if req_body is not None:
        logger.info(f"put_user: {req_body}")

    query = text("""
                    SELECT * FROM tb_user WHERE user_id = :user_id
                    """)
    result = await db.execute(query, {"user_id": user_id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_MEMBER)

    set_clause, params = build_update_query(req_body, allowed_fields=["role_type"])
    params["user_id"] = user_id

    query = text(f"UPDATE tb_user SET {set_clause} WHERE user_id = :user_id")

    await db.execute(query, params)

    return {"result": req_body}


async def get_product_simple_list(db: AsyncSession):
    """
    상품 간단 목록 조회

    Args:
        db: 데이터베이스 세션

    Returns:
        상품 ID와 제목이 포함된 간단 리스트
    """
    query = text("""
        SELECT
            product_id, title
        FROM tb_product
        ORDER BY created_date DESC
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    return [dict(row) for row in rows]


async def get_common_rate_data(db: AsyncSession):
    """
    비율 조정 데이터 조회

    Args:
        db: 데이터베이스 세션

    Returns:
        비율 조정 데이터
    """

    query = text("""
        SELECT
            *
        FROM tb_common_code
        WHERE code_group = 'common_rate'
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    default_settlement_rate = 0
    donation_settlement_rate = 0
    payment_fee_rate = 0
    tax_amount_rate = 0
    for row in rows:
        data = dict(row)
        if data["code_key"] == "default_settlement_rate":
            default_settlement_rate = float(data["code_value"])
        if data["code_key"] == "donation_settlement_rate":
            donation_settlement_rate = float(data["code_value"])
        if data["code_key"] == "payment_fee_rate":
            payment_fee_rate = float(data["code_value"])
        if data["code_key"] == "tax_amount_rate":
            tax_amount_rate = float(data["code_value"])

    return {
        "default_settlement_rate": default_settlement_rate,
        "donation_settlement_rate": donation_settlement_rate,
        "payment_fee_rate": payment_fee_rate,
        "tax_amount_rate": tax_amount_rate,
    }


async def save_common_rate_data(
    req_body: admin_schema.PostCommonRateReqBody, db: AsyncSession
):
    """
    비율 조정 데이터 조회

    Args:
        req_body: 저장할 비율 조정 데이터
        db: 데이터베이스 세션

    Returns:
        저장된 비율 조정 데이터
    """

    query = text("""
        SELECT
            *
        FROM tb_common_code
        WHERE code_group = 'common_rate'
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    default_settlement_rate_id = 0
    donation_settlement_rate_id = 0
    payment_fee_rate_id = 0
    tax_amount_rate_id = 0
    for row in rows:
        data = dict(row)
        if data["code_key"] == "default_settlement_rate":
            default_settlement_rate_id = int(data["id"])
        if data["code_key"] == "donation_settlement_rate":
            donation_settlement_rate_id = int(data["id"])
        if data["code_key"] == "payment_fee_rate":
            payment_fee_rate_id = int(data["id"])
        if data["code_key"] == "tax_amount_rate":
            tax_amount_rate_id = int(data["id"])

    if default_settlement_rate_id == 0:
        # 없으면 insert
        query = text("""
                     INSERT INTO tb_common_code (id, code_group, code_key, code_value, code_desc, created_id, created_date)
                     VALUES (DEFAULT, 'common_rate', 'default_settlement_rate', :value, '기본 정산율 - 작가 기준', -1, CURRENT_TIMESTAMP)
                     """)
        await db.execute(query, {"value": req_body.default_settlement_rate})
    else:
        # 있으면 update
        query = text("""
                     UPDATE tb_common_code SET code_value = :value WHERE id = :id
                     """)
        await db.execute(
            query,
            {
                "value": req_body.default_settlement_rate,
                "id": default_settlement_rate_id,
            },
        )

    if donation_settlement_rate_id == 0:
        # 없으면 insert
        query = text("""
                     INSERT INTO tb_common_code (id, code_group, code_key, code_value, code_desc, created_id, created_date)
                     VALUES (DEFAULT, 'common_rate', 'donation_settlement_rate', :value, '후원 정산율 - 작가 기준', -1, CURRENT_TIMESTAMP)
                     """)
        await db.execute(query, {"value": req_body.donation_settlement_rate})
    else:
        # 있으면 update
        query = text("""
                     UPDATE tb_common_code SET code_value = :value WHERE id = :id
                     """)
        await db.execute(
            query,
            {
                "value": req_body.donation_settlement_rate,
                "id": donation_settlement_rate_id,
            },
        )

    if payment_fee_rate_id == 0:
        # 없으면 insert
        query = text("""
                     INSERT INTO tb_common_code (id, code_group, code_key, code_value, code_desc, created_id, created_date)
                     VALUES (DEFAULT, 'common_rate', 'payment_fee_rate', :value, '결제 수수료', -1, CURRENT_TIMESTAMP)
                     """)
        await db.execute(query, {"value": req_body.payment_fee_rate})
    else:
        # 있으면 update
        query = text("""
                     UPDATE tb_common_code SET code_value = :value WHERE id = :id
                     """)
        await db.execute(
            query, {"value": req_body.payment_fee_rate, "id": payment_fee_rate_id}
        )

    if tax_amount_rate_id == 0:
        # 없으면 insert
        query = text("""
                     INSERT INTO tb_common_code (id, code_group, code_key, code_value, code_desc, created_id, created_date)
                     VALUES (DEFAULT, 'common_rate', 'tax_amount_rate', :value, '세액', -1, CURRENT_TIMESTAMP)
                     """)
        await db.execute(query, {"value": req_body.tax_amount_rate})
    else:
        # 있으면 update
        query = text("""
                     UPDATE tb_common_code SET code_value = :value WHERE id = :id
                     """)
        await db.execute(
            query, {"value": req_body.tax_amount_rate, "id": tax_amount_rate_id}
        )

    return {
        "default_settlement_rate": req_body.default_settlement_rate,
        "donation_settlement_rate": req_body.donation_settlement_rate,
        "payment_fee_rate": req_body.payment_fee_rate,
        "tax_amount_rate": req_body.tax_amount_rate,
    }
