import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import app.schemas.notice as notice_schema
from app.utils.query import (
    build_insert_query,
    build_update_query,
    get_file_name_sub_query,
    get_file_path_sub_query,
)
from app.utils.response import build_list_response, build_detail_response

logger = logging.getLogger("notice_app")  # 커스텀 로거 생성

"""
공지사항 도메인 조회 서비스
"""


async def rolling_broadcast_notices():
    """
    최상위 메시지 롤링 공지사항 조회
    """

    # # MeiliSearch 클라이언트 & 인덱스 설정
    # client = meilisearch.Client(f"{settings.MEILISEARCH_HOST}", f"{settings.MEILISEARCH_API_KEY}")
    # index = client.get_index('notices-broadcast')

    # # 검색어 및 검색 매개변수 설정
    # query = ''
    # search_params = {
    #     'sort': ['actionTime:desc'],
    #     'limit': 60
    # }

    # # 검색 수행
    # results = index.search(query, search_params)
    # # print(results)

    res_body = dict()
    # res_body["data"] = results['hits']

    # TODO 이걸 추가/수정/삭제하는 등의 관리 기능이 관리자에도 없는 상태라서 여기서 데이터가 조회되지 않아도 문제가 없을것 같음
    # 추후에 혹시나 관리자에서 추가/수정/삭제 등의 기능이 구현되고 이걸 사용하게 되면 그때 구현하는게 맞을듯
    res_body["data"] = []

    return res_body


async def rolling_primary_notices(db: AsyncSession):
    """
    공지사항(notice) 하단 중요 공지사항 목록 조회
    """
    query = text("""
                 SELECT * FROM tb_notice WHERE primary_yn = 'Y' ORDER BY id DESC
                 """)
    result = await db.execute(query, {})
    rows = result.mappings().all()
    return build_list_response(rows)


async def notices_all(page, limit, db: AsyncSession):
    """
    공지사항(notice) 목록 조회
    """
    # 총 개수 조회
    count_query = text("""
                      SELECT COUNT(*) as total FROM tb_notice
                      """)
    count_result = await db.execute(count_query, {})
    total_items = count_result.scalar()

    # OFFSET 계산 (page는 1-based 페이지 번호)
    offset = (page - 1) * limit

    # 목록 조회 (primary_yn='Y'를 상단에 정렬)
    query = text(f"""
                 SELECT
                    *
                    , {get_file_path_sub_query("n.file_id", "file_path")}
                    , {get_file_name_sub_query("n.file_id", "file_name")}
                 FROM tb_notice n
                 ORDER BY primary_yn DESC, id DESC
                 LIMIT :limit OFFSET :offset
                 """)
    result = await db.execute(query, {"limit": limit, "offset": offset})
    rows = result.mappings().all()
    return build_list_response(rows, total_items)


async def notice_detail_by_notice_id(notice_id, db: AsyncSession):
    """
    공지사항(notice) 상세 조회
    """
    query = text(f"""
                 SELECT
                    *
                    , {get_file_path_sub_query("n.file_id", "file_path")}
                    , {get_file_name_sub_query("n.file_id", "file_name")}
                 FROM tb_notice n WHERE id = :id
                 """)
    result = await db.execute(query, {"id": notice_id})
    row = result.mappings().one_or_none()

    if row is not None:
        query = text("""
                     update tb_notice set view_count = view_count + 1 where id = :id
                     """)
        await db.execute(query, {"id": notice_id})

    return build_detail_response(row)


async def post_notice(
    req_body: notice_schema.PostNoticeReqBody, user_id: str, db: AsyncSession
):
    if req_body is not None:
        logger.info(f"post_notice: {req_body}")

    columns, values, params = build_insert_query(
        req_body,
        optional_fields=["subject", "content", "primary_yn", "use_yn"],
        field_defaults={"primary_yn": "N", "use_yn": "Y"},
    )

    query = text(
        f"INSERT INTO tb_notice (id, {columns}, created_id, created_date) VALUES (default, {values}, :created_id, :created_date)"
    )

    await db.execute(query, params)

    return {"result": req_body}


async def put_notice(
    id: int, req_body: notice_schema.PutNoticeReqBody, user_id: str, db: AsyncSession
):
    if req_body is not None:
        logger.info(f"put_product_review: {req_body}")

    set_clause, params = build_update_query(
        req_body, allowed_fields=["subject", "content", "primary_yn", "use_yn"]
    )
    params["id"] = id

    query = text(f"UPDATE tb_notice SET {set_clause} WHERE id = :id")

    await db.execute(query, params)

    return {"result": req_body}


async def delete_notice(id: int, user_id: str, db: AsyncSession):
    query = text("""
                        delete from tb_notice where id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}
