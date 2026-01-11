from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import CommonConstants
from app.utils.query import get_file_path_sub_query
from app.utils.response import build_list_response, build_detail_response

"""
events 도메인 개별 서비스 함수 모음
"""


async def events_all_whether_close_or_not(close_yn, db: AsyncSession):
    # close_yn이 'N'이면 진행중, 'Y'이면 종료된 이벤트
    if close_yn == CommonConstants.NO:
        # 진행중인 이벤트
        query = text(f"""
            SELECT
                *,
                {get_file_path_sub_query("e.thumbnail_image_id", "thumbnail_image_path")},
                {get_file_path_sub_query("e.detail_image_id", "detail_image_path")}
            FROM tb_event_v2 e
            WHERE CURRENT_TIMESTAMP BETWEEN start_date AND end_date
            ORDER BY updated_date DESC
        """)
    else:
        # 종료된 이벤트
        query = text(f"""
            SELECT
                *,
                {get_file_path_sub_query("e.thumbnail_image_id", "thumbnail_image_path")},
                {get_file_path_sub_query("e.detail_image_id", "detail_image_path")}
            FROM tb_event_v2 e
            WHERE end_date < CURRENT_TIMESTAMP
            ORDER BY updated_date DESC
        """)

    result = await db.execute(query)
    rows = result.mappings().all()
    return build_list_response(rows)


async def event_detail_by_eventid(event_id, db: AsyncSession, round_no=0):
    """
    이벤트(event) 상세 조회
    """
    query = text(f"""
        SELECT
            *,
            {get_file_path_sub_query("e.thumbnail_image_id", "thumbnail_image_path")},
            {get_file_path_sub_query("e.detail_image_id", "detail_image_path")}
        FROM tb_event_v2 e
        WHERE id = :id
    """)
    result = await db.execute(query, {"id": event_id})
    row = result.mappings().one_or_none()
    return build_detail_response(row)
