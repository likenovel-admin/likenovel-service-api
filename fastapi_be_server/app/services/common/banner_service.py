from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.query import get_file_path_sub_query
from app.utils.response import build_list_response

"""
배너 도메인 서비스
"""


async def banners_by_division(division: str, db: AsyncSession):
    """
    영역별 배너 목록
    """

    select_files = [
        "id",
        "division",
        "NULL AS textType",
        "NULL AS topText",
        "NULL AS middleText",
        "NULL AS bottomText",
        "NULL AS textImgPath",
        "NULL AS mobileTextImgPath",
        "NULL AS textPosition",
        "NULL AS overlayYn",
        "NULL AS overlayType",
        "NULL AS overlayImgPath",
        "NULL AS mobileOverlayImgPath",
        "url AS linkPath",
        get_file_path_sub_query("b.image_id", "pcImgPath"),
        get_file_path_sub_query("b.mobile_image_id", "mobileImgPath"),
    ]

    if division == "main":
        query = text(f"""
                    SELECT
                        {",".join(select_files)}, 'primaryPanel' AS area
                    FROM tb_carousel_banner b WHERE position = 'main' AND division = 'top' AND show_start_date < now() AND now() < show_end_date ORDER BY show_order ASC
                    """)
        result = await db.execute(query, {})
        rows = result.mappings().all()
        primary_panels = [dict(row) for row in rows]

        query = text(f"""
                    SELECT
                        {",".join(select_files)}, 'secondaryPanel' AS area
                    FROM tb_carousel_banner b WHERE position = 'main' AND division = 'mid' AND show_start_date < now() AND now() < show_end_date ORDER BY show_order ASC
                    """)
        result = await db.execute(query, {})
        rows = result.mappings().all()
        secondary_panels = [dict(row) for row in rows]

        query = text(f"""
                    SELECT
                        {",".join(select_files)}, 'thirdPanel' AS area
                    FROM tb_carousel_banner b WHERE position = 'main' AND division = 'bot' AND show_start_date < now() AND now() < show_end_date ORDER BY show_order ASC
                    """)
        result = await db.execute(query, {})
        rows = result.mappings().all()
        teriay_panels = [dict(row) for row in rows]

        res_fetched = dict()
        res_fetched["primaryPanels"] = primary_panels
        res_fetched["secondaryPanels"] = secondary_panels
        res_fetched["teriayPanels"] = teriay_panels

        res_body = dict()
        res_body["data"] = res_fetched

        return res_body
    else:
        query = text(f"""
                    SELECT
                        {",".join(select_files)}
                    FROM tb_carousel_banner b WHERE position = :division AND show_start_date < now() AND now() < show_end_date ORDER BY show_order ASC
                    """)
        result = await db.execute(query, {"division": division})
        rows = result.mappings().all()
        return build_list_response(rows)
