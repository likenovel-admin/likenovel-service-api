"""Main service"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.query import get_file_path_sub_query


async def get_popup(db: AsyncSession):
    """
    현재 노출 중인 팝업 데이터 조회 (인증 불필요)

    Args:
        db: 데이터베이스 세션

    Returns:
        현재 노출 중인 팝업 데이터 (use_yn='Y')
    """

    query = text(f"""
        SELECT
            p.id,
            p.url,
            {get_file_path_sub_query("p.image_id", "image_path")}
        FROM tb_comm_popup p
        WHERE p.use_yn = 'Y'
        ORDER BY p.created_date DESC
        LIMIT 1
    """)
    result = await db.execute(query, {})
    row = result.mappings().first()

    if row is None:
        return {"data": None}

    return {
        "data": {
            "id": row["id"],
            "url": row["url"],
            "imagePath": row["image_path"],
        }
    }
