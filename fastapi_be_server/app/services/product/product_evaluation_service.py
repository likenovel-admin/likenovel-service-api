import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import app.schemas.product_evaluation as product_evaluation_schema
from app.utils.query import build_insert_query, build_update_query
from app.utils.response import build_list_response, build_detail_response

logger = logging.getLogger("product_evaluation_app")  # 커스텀 로거 생성

"""
product_evaluation 작품 평가 개별 서비스 함수 모음
"""


async def product_evaluation_list(db: AsyncSession):
    query = text("""
                 SELECT * FROM tb_product_evaluation ORDER BY updated_date DESC
                 """)
    result = await db.execute(query, {})
    rows = result.mappings().all()
    return build_list_response(rows)


async def product_evaluation_detail_by_id(id, db: AsyncSession):
    """
    작품 평가(product_evaluation) 상세 조회
    """
    query = text("""
                 SELECT * FROM tb_product_evaluation WHERE id = :id
                 """)
    result = await db.execute(query, {"id": id})
    row = result.mappings().one_or_none()
    return build_detail_response(row)


async def post_product_evaluation(
    req_body: product_evaluation_schema.PostProductEvaluationReqBody,
    user_id: str,
    db: AsyncSession,
):
    if req_body is not None:
        logger.info(f"post_product_evaluation: {req_body}")

    columns, values, params = build_insert_query(
        req_body,
        required_fields=["product_id", "episode_id", "user_id", "eval_code"],
        optional_fields=["use_yn"],
        field_defaults={"use_yn": "Y"},
    )

    query = text(
        f"INSERT INTO tb_product_evaluation (id, {columns}, created_id, created_date) VALUES (default, {values}, :created_id, :created_date)"
    )

    await db.execute(query, params)

    return {"result": req_body}


async def put_product_evaluation(
    id: int,
    req_body: product_evaluation_schema.PutProductEvaluationReqBody,
    user_id: str,
    db: AsyncSession,
):
    if req_body is not None:
        logger.info(f"put_product_evaluation: {req_body}")

    set_clause, params = build_update_query(
        req_body,
        allowed_fields=["product_id", "episode_id", "user_id", "eval_code", "use_yn"],
    )
    params["id"] = id

    query = text(f"UPDATE tb_product_evaluation SET {set_clause} WHERE id = :id")

    await db.execute(query, params)

    return {"result": req_body}


async def delete_product_evaluation(id: int, user_id: str, db: AsyncSession):
    query = text("""
                        delete from tb_product_evaluation where id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}
