import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import ErrorMessages
import app.schemas.admin as admin_schema
from app.utils.query import (
    build_search_where_clause,
    get_pagination_params,
    build_update_query,
    get_nickname_or_fallback_sub_query,
)
from app.utils.response import build_paginated_response, check_exists_or_404

logger = logging.getLogger("admin_app")

"""
관리자 콘텐츠(리뷰/댓글/공지사항) 관리 서비스 함수 모음
"""


async def reviews_comments_notices(
    search_target: str,
    search_word: str,
    search_start_date: str,
    search_end_date: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    리뷰/댓글/공지 통합 목록 조회

    Args:
        search_target: 검색 대상 필드
        search_word: 검색어
        search_start_date: 검색 시작 날짜
        search_end_date: 검색 끝 날짜
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        리뷰/댓글/공지 통합 리스트와 페이징 정보
    """

    where, params = build_search_where_clause(
        search_word,
        search_target,
        search_start_date,
        search_end_date,
        search_type="admin",
    )

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        SELECT COUNT(*) AS total_count FROM (
            SELECT id FROM tb_product_review main WHERE 1=1 {where}
            UNION
            SELECT comment_id FROM tb_product_comment main WHERE 1=1 {where}
            UNION
            SELECT id FROM tb_product_notice main WHERE 1=1 {where}
        ) u
    """)
    count_result = await db.execute(count_query, params)
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT * FROM (
            SELECT
                'review' AS type,
                main.id,
                main.product_id,
                main.user_id,
                'Y' AS use_yn,
                main.open_yn,
                main.created_date,
                {get_nickname_or_fallback_sub_query("u.user_id", "u.user_name")},
                p.title AS product_title,
                main.review_text AS contents
            FROM tb_product_review main
            INNER JOIN tb_product p ON p.product_id = main.product_id
            INNER JOIN tb_user u ON u.user_id = main.user_id
            WHERE 1=1 {where}
            UNION
            SELECT
                'comment' AS type,
                main.comment_id AS id,
                main.product_id,
                main.user_id,
                main.use_yn,
                main.open_yn,
                main.created_date,
                {get_nickname_or_fallback_sub_query("u.user_id", "u.user_name")},
                p.title AS product_title,
                main.content AS contents
            FROM tb_product_comment main
            INNER JOIN tb_product p ON p.product_id = main.product_id
            INNER JOIN tb_user u ON u.user_id = main.user_id
            WHERE 1=1 {where}
            UNION
            SELECT
                'notice' AS type,
                main.id,
                main.product_id,
                main.user_id,
                main.use_yn,
                main.open_yn,
                main.created_date,
                {get_nickname_or_fallback_sub_query("u.user_id", "u.user_name")},
                p.title AS product_title,
                main.subject AS contents
            FROM tb_product_notice main
            INNER JOIN tb_product p ON p.product_id = main.product_id
            INNER JOIN tb_user u ON u.user_id = main.user_id
            WHERE 1=1 {where}
        ) u
        ORDER BY u.created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params | params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def reviews_list(
    search_target: str,
    search_word: str,
    search_start_date: str,
    search_end_date: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    작품 리뷰 목록 조회

    Args:
        search_target: 검색 대상 필드
        search_word: 검색어
        search_start_date: 검색 시작 날짜
        search_end_date: 검색 끝 날짜
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        리뷰 목록과 페이징 정보
    """

    where, params = build_search_where_clause(
        search_word,
        search_target,
        search_start_date,
        search_end_date,
        search_type="admin",
    )

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        SELECT COUNT(*) AS total_count FROM tb_product_review main WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, params)
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            'review' AS type,
            main.id,
            main.product_id,
            main.user_id,
            'Y' AS use_yn,
            main.open_yn,
            main.created_date,
            {get_nickname_or_fallback_sub_query("u.user_id", "u.user_name")},
            p.title AS product_title,
            main.review_text AS contents
        FROM tb_product_review main
        INNER JOIN tb_product p ON p.product_id = main.product_id
        INNER JOIN tb_user u ON u.user_id = main.user_id
        WHERE 1=1 {where}
        ORDER BY main.created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params | params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def review_detail_by_id(id: int, db: AsyncSession):
    """
    작품 리뷰 상세 정보 조회

    Args:
        id: 조회할 리뷰 ID
        db: 데이터베이스 세션

    Returns:
        리뷰 상세 정보 (작성자, 작품 정보 포함)
    """

    query = text(f"""
        SELECT
            pr.id,
            pr.product_id,
            pr.user_id,
            pr.review_text,
            pr.open_yn,
            pr.created_date,
            pr.updated_date,
            {get_nickname_or_fallback_sub_query("u.user_id", "NULL", "nickname")},
            u.email,
            u.user_name,
            p.title AS product_title
        FROM tb_product_review pr
        INNER JOIN tb_product p ON p.product_id = pr.product_id
        INNER JOIN tb_user u ON u.user_id = pr.user_id
        WHERE id = {id}
        ORDER BY pr.created_date DESC LIMIT 1
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_REVIEW)

    return dict(rows[0])


async def put_review(
    id: int, req_body: admin_schema.PutProductReviewReqBody, db: AsyncSession
):
    """
    작품 리뷰 수정

    Args:
        id: 수정할 리뷰 ID
        req_body: 수정할 리뷰 데이터 (리뷰 텍스트, 공개여부 등)
        db: 데이터베이스 세션

    Returns:
        리뷰 수정 결과
    """

    if req_body is not None:
        logger.info(f"put_review: {req_body}")

    query = text("""
                    SELECT * FROM tb_product_review WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_REVIEW)

    set_clause, params = build_update_query(
        req_body,
        allowed_fields=[
            "product_id",
            "episode_id",
            "user_id",
            "review_text",
            "open_yn",
        ],
    )
    params["id"] = id

    query = text(f"""
                        update tb_product_review set
                        {set_clause}
                        where id = :id
                    """)

    await db.execute(query, params)

    return {"result": req_body}


async def delete_review(id: int, db: AsyncSession):
    """
    작품 리뷰 삭제

    Args:
        id: 삭제할 리뷰 ID
        db: 데이터베이스 세션

    Returns:
        리뷰 삭제 결과
    """

    query = text("""
                    SELECT * FROM tb_product_review WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_REVIEW)

    query = text("""
                    delete from tb_product_review where id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}


async def comments_list(
    search_target: str,
    search_word: str,
    search_start_date: str,
    search_end_date: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    작품 댓글 목록 조회

    Args:
        search_target: 검색 대상 필드
        search_word: 검색어
        search_start_date: 검색 시작 날짜
        search_end_date: 검색 끝 날짜
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        댓글 목록과 페이징 정보
    """

    where, params = build_search_where_clause(
        search_word,
        search_target,
        search_start_date,
        search_end_date,
        search_type="admin",
    )

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        SELECT COUNT(*) AS total_count FROM tb_product_comment main WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, params)
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            'comment' AS type,
            main.comment_id AS id,
            main.product_id,
            main.user_id,
            main.use_yn,
            main.open_yn,
            main.created_date,
            {get_nickname_or_fallback_sub_query("u.user_id", "u.user_name")},
            p.title AS product_title,
            main.content AS contents
        FROM tb_product_comment main
        INNER JOIN tb_product p ON p.product_id = main.product_id
        INNER JOIN tb_user u ON u.user_id = main.user_id
        WHERE 1=1 {where}
        ORDER BY main.created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params | params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def comment_detail_by_id(id: int, db: AsyncSession):
    """
    작품 댓글 상세 정보 조회

    Args:
        id: 조회할 댓글 ID
        db: 데이터베이스 세션

    Returns:
        댓글 상세 정보 (작성자, 작품 정보 포함)
    """

    query = text(f"""
        SELECT
            pc.comment_id,
            pc.product_id,
            pc.episode_id,
            pc.user_id,
            pc.profile_id,
            pc.author_recommend_yn,
            pc.content,
            pc.count_recommend,
            pc.count_not_recommend,
            pc.use_yn,
            pc.open_yn,
            pc.display_top_yn,
            pc.created_date,
            pc.updated_date,
            {get_nickname_or_fallback_sub_query("u.user_id", "NULL", "nickname")},
            u.email,
            u.user_name,
            p.title AS product_title
        FROM tb_product_comment pc
        INNER JOIN tb_product p ON p.product_id = pc.product_id
        INNER JOIN tb_user u ON u.user_id = pc.user_id
        WHERE comment_id = {id}
        ORDER BY pc.created_date DESC LIMIT 1
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_COMMENT)

    return dict(rows[0])


async def put_comment(
    id: int, req_body: admin_schema.PutProductCommentReqBody, db: AsyncSession
):
    """
    작품 댓글 수정

    Args:
        id: 수정할 댓글 ID
        req_body: 수정할 댓글 데이터 (내용, 사용여부, 공개여부 등)
        db: 데이터베이스 세션

    Returns:
        댓글 수정 결과
    """

    if req_body is not None:
        logger.info(f"put_comment: {req_body}")

    query = text("""
                    SELECT * FROM tb_product_comment WHERE comment_id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_COMMENT)

    set_clause, params = build_update_query(
        req_body,
        allowed_fields=[
            "product_id",
            "episode_id",
            "user_id",
            "profile_id",
            "author_recommend_yn",
            "content",
            "use_yn",
            "open_yn",
            "display_top_yn",
        ],
    )
    params["id"] = id

    query = text(f"""
                        update tb_product_comment set
                        {set_clause}
                        where comment_id = :id
                    """)

    await db.execute(query, params)

    return {"result": req_body}


async def delete_comment(id: int, db: AsyncSession):
    """
    작품 댓글 삭제

    Args:
        id: 삭제할 댓글 ID
        db: 데이터베이스 세션

    Returns:
        댓글 삭제 결과
    """

    query = text("""
                    SELECT * FROM tb_product_comment WHERE comment_id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_COMMENT)

    query = text("""
                    delete from tb_product_comment where comment_id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}


async def notices_list(
    search_target: str,
    search_word: str,
    search_start_date: str,
    search_end_date: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    작품 공지사항 목록 조회

    Args:
        search_target: 검색 대상 필드
        search_word: 검색어
        search_start_date: 검색 시작 날짜
        search_end_date: 검색 끝 날짜
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        공지사항 목록과 페이징 정보
    """

    where, params = build_search_where_clause(
        search_word,
        search_target,
        search_start_date,
        search_end_date,
        search_type="admin",
    )

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        SELECT COUNT(*) AS total_count FROM tb_product_notice main WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, params)
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            'notice' AS type,
            main.id,
            main.product_id,
            main.user_id,
            main.use_yn,
            main.open_yn,
            main.created_date,
            {get_nickname_or_fallback_sub_query("u.user_id", "u.user_name")},
            p.title AS product_title,
            main.subject AS contents
        FROM tb_product_notice main
        INNER JOIN tb_product p ON p.product_id = main.product_id
        INNER JOIN tb_user u ON u.user_id = main.user_id
        WHERE 1=1 {where}
        ORDER BY main.created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params | params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def notice_detail_by_id(id: int, db: AsyncSession):
    """
    작품 공지사항 상세 정보 조회

    Args:
        id: 조회할 공지사항 ID
        db: 데이터베이스 세션

    Returns:
        공지사항 상세 정보 (작성자, 작품 정보 포함)
    """

    query = text(f"""
        SELECT
            pn.id,
            pn.product_id,
            pn.user_id,
            pn.subject,
            pn.content,
            pn.use_yn,
            pn.open_yn,
            pn.created_date,
            pn.updated_date,
            {get_nickname_or_fallback_sub_query("u.user_id", "NULL", "nickname")},
            u.email,
            u.user_name,
            p.title AS product_title
        FROM tb_product_notice pn
        INNER JOIN tb_product p ON p.product_id = pn.product_id
        INNER JOIN tb_user u ON u.user_id = pn.user_id
        WHERE id = {id}
        ORDER BY pn.created_date DESC LIMIT 1
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_NOTICE)

    return dict(rows[0])


async def put_notice(
    id: int, req_body: admin_schema.PutProductNoticeReqBody, db: AsyncSession
):
    """
    작품 공지사항 수정

    Args:
        id: 수정할 공지사항 ID
        req_body: 수정할 공지사항 데이터 (제목, 내용, 공개여부 등)
        db: 데이터베이스 세션

    Returns:
        공지사항 수정 결과
    """

    if req_body is not None:
        logger.info(f"put_notice: {req_body}")

    query = text("""
                    SELECT * FROM tb_product_notice WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_REVIEW)

    set_clause, params = build_update_query(
        req_body,
        allowed_fields=[
            "product_id",
            "user_id",
            "subject",
            "content",
            "publish_reserve_date",
            "open_yn",
            "use_yn",
        ],
    )
    params["id"] = id

    query = text(f"""
                        update tb_product_notice set
                        {set_clause}
                        where id = :id
                    """)

    await db.execute(query, params)

    return {"result": req_body}


async def delete_notice(id: int, db: AsyncSession):
    """
    작품 공지사항 삭제

    Args:
        id: 삭제할 공지사항 ID
        db: 데이터베이스 세션

    Returns:
        공지사항 삭제 결과
    """

    query = text("""
                    SELECT * FROM tb_product_notice WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_REVIEW)

    query = text("""
                    delete from tb_product_notice where id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}
