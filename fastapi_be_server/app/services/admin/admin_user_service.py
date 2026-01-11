import logging
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import CustomResponseException
import app.schemas.admin as admin_schema
import app.schemas.auth as auth_schema
from app.utils.query import (
    get_file_path_sub_query,
    get_file_name_sub_query,
    get_nickname_sub_query,
    get_pagination_params,
)
from app.utils.response import build_paginated_response, check_exists_or_404
from app.utils.common import handle_exceptions
from app.const import CommonConstants
from app.services.common import comm_service
from app.const import ErrorMessages

logger = logging.getLogger("admin_app")

"""
관리자 사용자 관리 서비스 함수 모음
"""


async def user_list(
    status: str,
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    회원 목록

    Args:
        status: 회원 상태 (all, normal, admin, signout)
        search_target: 검색 대상 (nickname, name, contact, email)
        search_word: 검색어
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        회원 목록과 페이징 정보
    """

    if search_word != "":
        if search_target == "nickname":
            where = text(f"""
                        AND user_id IN (SELECT user_id FROM tb_user_profile WHERE nickname LIKE '%{search_word}%')
                        """)
        elif search_target == "name":
            where = text(f"""
                        AND user_name LIKE '%{search_word}%'
                        """)
        elif search_target == "contact":
            where = text(f"""
                         AND mobile_no LIKE '%{search_word}%'
                        """)
        elif search_target == CommonConstants.SEARCH_EMAIL:
            where = text(f"""
                        AND email LIKE '%{search_word}%'
                        """)
        else:
            where = text("""""")
    else:
        where = text("""""")

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    if status == "all":
        count_query = text(f"""
            SELECT COUNT(*) AS total_count FROM tb_user WHERE use_yn = 'Y' {where}
        """)
    elif status == CommonConstants.ROLE_NORMAL:
        count_query = text(f"""
            SELECT COUNT(*) AS total_count FROM tb_user WHERE use_yn = 'Y' AND role_type = 'normal' {where}
        """)
    elif status == CommonConstants.ROLE_ADMIN:
        count_query = text(f"""
            SELECT COUNT(*) AS total_count FROM tb_user WHERE use_yn = 'Y' AND role_type = 'admin' {where}
        """)
    elif status == "signout":
        count_query = text(f"""
            SELECT COUNT(*) AS total_count FROM tb_user WHERE use_yn = 'N' {where}
        """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    if status == "all":
        query = text(f"""
            SELECT
                user_id,
                user_name AS name,
                {get_nickname_sub_query("u.user_id")},
                email,
                mobile_no AS phone,
                created_date,
                latest_signed_date,
                NULL AS signoff_date,
                agree_terms_yn,
                (SELECT noti_yn FROM tb_user_notification WHERE user_id = u.user_id ORDER BY created_date DESC LIMIT 1) AS noti_yn
            FROM tb_user u WHERE use_yn = 'Y' {where}
            ORDER BY created_date DESC
            {limit_clause}
        """)
    elif status == CommonConstants.ROLE_NORMAL:
        query = text(f"""
            SELECT
                user_id,
                user_name AS name,
                {get_nickname_sub_query("u.user_id")},
                email,
                mobile_no AS phone,
                created_date,
                latest_signed_date,
                NULL AS signoff_date,
                agree_terms_yn,
                (SELECT noti_yn FROM tb_user_notification WHERE user_id = u.user_id ORDER BY created_date DESC LIMIT 1) AS noti_yn
            FROM tb_user u WHERE use_yn = 'Y' AND role_type = 'normal' {where}
            ORDER BY created_date DESC
            {limit_clause}
        """)
    elif status == CommonConstants.ROLE_ADMIN:
        query = text(f"""
            SELECT
                user_id,
                user_name AS name,
                {get_nickname_sub_query("u.user_id")},
                email,
                mobile_no AS phone,
                created_date,
                latest_signed_date,
                NULL AS signoff_date,
                agree_terms_yn,
                (SELECT noti_yn FROM tb_user_notification WHERE user_id = u.user_id ORDER BY created_date DESC LIMIT 1) AS noti_yn
            FROM tb_user u WHERE use_yn = 'Y' AND role_type = 'admin' {where}
            ORDER BY created_date DESC
            {limit_clause}
        """)
    elif status == "signout":
        query = text(f"""
            SELECT
                user_id,
                user_name AS name,
                {get_nickname_sub_query("u.user_id")},
                email,
                mobile_no AS phone,
                created_date,
                latest_signed_date,
                updated_date AS signoff_date,
                agree_terms_yn,
                (SELECT noti_yn FROM tb_user_notification WHERE user_id = u.user_id ORDER BY created_date DESC LIMIT 1) AS noti_yn
            FROM tb_user u WHERE use_yn = 'N' {where}
            ORDER BY created_date DESC
            {limit_clause}
        """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    results = [dict(row) for row in rows]

    # 탈퇴한 유저의 이메일은 이미 DB에 outed;timestamp;email 형식으로 저장되어 있음
    # 별도 가공 불필요

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "results": results,
    }


async def user_detail_by_user_id(user_id, db: AsyncSession):
    """
    유저 상세 조회

    Args:
        user_id: 조회할 유저 ID
        db: 데이터베이스 세션

    Returns:
        유저 상세 정보 (기본 정보 + 프로필 리스트)
    """
    query = text("""
                SELECT
                    *,
                    {get_nickname_sub_query("u.user_id")},
                    mobile_no AS phone
                FROM tb_user u WHERE user_id = :user_id
                """)
    result = await db.execute(query, {"user_id": user_id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_MEMBER)

    user = dict(rows[0])

    # 탈퇴한 유저의 이메일은 이미 DB에 outed;timestamp;email 형식으로 저장되어 있음
    # 별도 가공 불필요

    # 알림 설정 조회 (타입별로 분리)
    noti_query = text("""
                SELECT noti_type, noti_yn
                FROM tb_user_notification
                WHERE user_id = :user_id
                """)
    noti_result = await db.execute(noti_query, {"user_id": user_id})
    noti_rows = noti_result.mappings().all()

    # 알림 타입별로 매핑
    notifications_status = {}
    for noti_row in noti_rows:
        noti_type = noti_row["noti_type"]
        noti_yn = noti_row["noti_yn"]
        notifications_status[f"{noti_type}_yn"] = noti_yn

    # user 딕셔너리에 알림 설정 추가
    user["notifications_status"] = notifications_status

    query = text(f"""
                SELECT
                    *,
                    {get_file_path_sub_query("up.profile_image_id", "profile_image_path")}
                FROM tb_user_profile up WHERE user_id = :user_id
                """)
    result = await db.execute(query, {"user_id": user_id})
    rows = result.mappings().all()

    user["profiles"] = [dict(row) for row in rows]
    return user


async def apply_role(status: str, page: int, count_per_page: int, db: AsyncSession):
    """
    자격 신청 목록

    Args:
        status: 신청 상태 (all, waiting, completed, editor, cp)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        자격 신청 목록과 페이징 정보
    """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    if status == "all":
        where_query = text("""
                           1=1
                           """)
    elif status == "waiting":
        where_query = text("""
                           approval_code != 'accepted' AND approval_code != 'denied'
                           """)
    elif status == "completed":
        where_query = text("""
                           approval_code = 'accepted'
                           """)
    elif status == "editor":
        where_query = text("""
                           apply_type = 'editor'
                           """)
    elif status == "cp":
        where_query = text("""
                           apply_type = 'cp'
                           """)

    # 전체 개수 구하기
    count_query = text(f"""
                       SELECT COUNT(*) AS total_count FROM tb_user_profile_apply WHERE {where_query}
                       """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
                 SELECT
                    upa.*
                    , upa.email AS contact_email
                    , u.email AS email
                    , {get_file_path_sub_query("upa.attach_file_id_1st", "attach_file_path_1st")}
                    , {get_file_path_sub_query("upa.attach_file_id_2nd", "attach_file_path_2nd")}
                    , {get_file_name_sub_query("upa.attach_file_id_1st", "attach_file_name_1st")}
                    , {get_file_name_sub_query("upa.attach_file_id_2nd", "attach_file_name_2nd")}
                    , {get_nickname_sub_query("upa.user_id")}
                 FROM tb_user_profile_apply upa
                 INNER JOIN tb_user u ON upa.user_id = u.user_id
                 WHERE {where_query}
                 ORDER BY id DESC {limit_clause}
                 """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def accept_apply_role(id: int, db: AsyncSession):
    """
    자격 신청 승인 처리

    Args:
        id: 승인할 자격 신청 ID
        db: 데이터베이스 세션

    Returns:
        승인 처리 결과
    """
    query = text("""
                 SELECT * FROM tb_user_profile_apply WHERE id = :id
                 """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()
    check_exists_or_404(rows, ErrorMessages.APPLICATION_INFO_NOT_FOUND)

    row = dict(rows[0])

    if row["approval_code"] == "accepted":
        # 이미 승인 함
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_APPROVED,
        )

    # tb_user_profile_apply 승인 처리
    query = text("""
                 UPDATE tb_user_profile_apply SET approval_code = 'accepted', approval_message = '승인되었습니다', approval_date = now() WHERE id = :id
                 """)
    await db.execute(query, {"id": id})

    # tb_user_profile의 role_type을 apply_type으로 업데이트
    # 1. default_yn = 'Y' 프로필 확인
    query = text("""
                 SELECT profile_id FROM tb_user_profile
                 WHERE user_id = :user_id AND default_yn = 'Y'
                 """)
    result = await db.execute(query, {"user_id": row["user_id"]})
    default_profile = result.mappings().first()

    if default_profile:
        # default 프로필이 있으면 업데이트
        query = text("""
                     UPDATE tb_user_profile
                     SET role_type = :apply_type
                     WHERE user_id = :user_id AND default_yn = 'Y'
                     """)
        await db.execute(
            query, {"apply_type": row["apply_type"], "user_id": row["user_id"]}
        )
    else:
        # default 프로필이 없으면 프로필 존재 여부 확인
        query = text("""
                     SELECT profile_id FROM tb_user_profile
                     WHERE user_id = :user_id
                     ORDER BY profile_id ASC LIMIT 1
                     """)
        result = await db.execute(query, {"user_id": row["user_id"]})
        first_profile = result.mappings().first()

        if first_profile:
            # 프로필이 있으면 profile_id가 가장 작은 프로필 업데이트
            query = text("""
                         UPDATE tb_user_profile
                         SET role_type = :apply_type
                         WHERE profile_id = :profile_id
                         """)
            await db.execute(
                query,
                {
                    "apply_type": row["apply_type"],
                    "profile_id": first_profile["profile_id"],
                },
            )
        else:
            # 프로필이 아예 없으면 새로 생성
            query = text("""
                         INSERT INTO tb_user_profile (user_id, nickname, role_type, default_yn, created_id, created_date, updated_id, updated_date)
                         VALUES (:user_id, :nickname, :role_type, 'Y', -1, NOW(), -1, NOW())
                         """)
            # 랜덤 닉네임 생성
            nickname = comm_service.make_rand_nickname()

            await db.execute(
                query,
                {
                    "user_id": row["user_id"],
                    "nickname": nickname,
                    "role_type": row["apply_type"],
                },
            )

    return {"result": True}


async def deny_apply_role(id: int, db: AsyncSession):
    """
    자격 신청 반려 처리

    Args:
        id: 반려할 자격 신청 ID
        db: 데이터베이스 세션

    Returns:
        반려 처리 결과
    """
    query = text("""
                 SELECT * FROM tb_user_profile_apply WHERE id = :id
                 """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()
    check_exists_or_404(rows, ErrorMessages.APPLICATION_INFO_NOT_FOUND)

    row = dict(rows[0])

    if row["approval_code"] == "denied":
        # 이미 반려 함
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_REJECTED,
        )

    query = text("""
                 UPDATE tb_user_profile_apply SET approval_code = 'denied', approval_message = '반려되었습니다', approval_date = now() WHERE id = :id
                 """)
    await db.execute(query, {"id": id})

    return {"result": True}


async def badge(db: AsyncSession):
    """
    뱃지 목록

    Args:
        db: 데이터베이스 세션

    Returns:
        뱃지 목록
    """

    query = text("""
                 SELECT * FROM tb_badge
                 """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    return {"results": [dict(row) for row in rows]}


async def put_badge(req_body: admin_schema.PutBadgeReqBody, id: int, db: AsyncSession):
    """
    뱃지 승급 조건 수정

    Args:
        req_body: 뱃지 수정 정보 (승급 조건 등)
        id: 수정할 뱃지 ID
        db: 데이터베이스 세션

    Returns:
        수정 결과
    """

    query = text("""
                    SELECT * FROM tb_badge WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_BADGE)

    query = text("""
                 UPDATE tb_badge SET promotion_conditions = :promotion_conditions WHERE id = :id
                 """)
    await db.execute(
        query,
        {
            "promotion_conditions": req_body.promotion_conditions,
            "id": id,
        },
    )

    return {"results": True}


async def apply_rank_up(
    status: str,
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    승급 신청 목록 조회

    Args:
        status: 승급 상태 ('all', 'rank-up', 'paid')
        search_target: 검색 대상 (제목, 작가명)
        search_word: 검색어
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        승급 신청 목록과 페이징 정보
    """

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where = text(f"""
                         AND title LIKE '%{search_word}%'
                         """)
        elif search_target == CommonConstants.SEARCH_WRITER_NAME:
            where = text(f"""
                         AND author_name LIKE '%{search_word}%'
                         """)
        else:
            where = text("""""")
    else:
        where = text("""""")

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    # JOIN을 사용하여 서브쿼리 최적화
    if status == "all":
        # 무료 작품(normal) + 유료 전환 신청 작품 모두 포함 (작품당 1건씩만)
        count_query = text(f"""
            SELECT COUNT(*) AS total_count
            FROM (
                SELECT p.product_id
                FROM tb_product p
                WHERE p.product_type = 'normal' {where}
                UNION
                SELECT DISTINCT p.product_id
                FROM tb_product p
                INNER JOIN tb_product_paid_apply ppa ON p.product_id = ppa.product_id
                WHERE 1=1 {where}
            ) AS combined
        """)
    elif status == "rank-up":
        count_query = text(f"""
            SELECT COUNT(*) AS total_count FROM tb_product WHERE product_type = 'normal' {where}
        """)
    elif status == "paid":
        # 작품당 1건씩만 카운트
        count_query = text(f"""
            SELECT COUNT(DISTINCT p.product_id) AS total_count
            FROM tb_product p
            INNER JOIN tb_product_paid_apply ppa ON p.product_id = ppa.product_id
            WHERE 1=1 {where}
        """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회 - JOIN을 사용하여 서브쿼리 최적화
    if status == "all":
        # UNION ALL로 무료 작품과 유료 신청 작품을 명확히 분리
        # 유료 신청의 경우 작품당 최신 신청만 조회, 반려 횟수 포함
        query = text(f"""
            SELECT * FROM (
                SELECT
                    p.*,
                    'accepted' AS `status`,
                    'rank-up' AS `type`,
                    COALESCE(pe.episode_count, 0) AS `count_episode`,
                    NULL AS `apply_id`,
                    p.created_date AS `req_apply_date`,
                    0 AS `denied_count`
                FROM tb_product p
                LEFT JOIN (
                    SELECT product_id, COUNT(*) as episode_count
                    FROM tb_product_episode
                    WHERE use_yn = 'Y'
                    GROUP BY product_id
                ) pe ON p.product_id = pe.product_id
                WHERE p.product_type = 'normal' {where}

                UNION ALL

                SELECT
                    p.*,
                    ppa.status_code AS `status`,
                    'paid' AS `type`,
                    COALESCE(pe.episode_count, 0) AS `count_episode`,
                    ppa.id AS `apply_id`,
                    ppa.req_date AS `req_apply_date`,
                    COALESCE(dc.denied_count, 0) AS `denied_count`
                FROM tb_product p
                INNER JOIN (
                    SELECT ppa1.*
                    FROM tb_product_paid_apply ppa1
                    INNER JOIN (
                        SELECT product_id, MAX(id) as max_id
                        FROM tb_product_paid_apply
                        GROUP BY product_id
                    ) ppa2 ON ppa1.product_id = ppa2.product_id AND ppa1.id = ppa2.max_id
                ) ppa ON p.product_id = ppa.product_id
                LEFT JOIN (
                    SELECT product_id, COUNT(*) as episode_count
                    FROM tb_product_episode
                    WHERE use_yn = 'Y'
                    GROUP BY product_id
                ) pe ON p.product_id = pe.product_id
                LEFT JOIN (
                    SELECT product_id, COUNT(*) as denied_count
                    FROM tb_product_paid_apply
                    WHERE status_code = 'denied'
                    GROUP BY product_id
                ) dc ON p.product_id = dc.product_id
                WHERE 1=1 {where}
            ) AS combined_results
            ORDER BY req_apply_date DESC
            {limit_clause}
        """)
    elif status == "rank-up":
        query = text(f"""
            SELECT
                p.*,
                'accepted' AS `status`,
                'rank-up' AS `type`,
                COALESCE(pe.episode_count, 0) AS `count_episode`,
                NULL AS `apply_id`
            FROM tb_product p
            LEFT JOIN (
                SELECT product_id, COUNT(*) as episode_count
                FROM tb_product_episode
                WHERE use_yn = 'Y'
                GROUP BY product_id
            ) pe ON p.product_id = pe.product_id
            WHERE p.product_type = 'normal' {where}
            ORDER BY p.created_date DESC
            {limit_clause}
        """)
    elif status == "paid":
        # 작품당 최신 신청만 조회, 반려 횟수 포함
        query = text(f"""
            SELECT
                p.*,
                ppa.status_code AS `status`,
                'paid' AS `type`,
                COALESCE(pe.episode_count, 0) AS `count_episode`,
                ppa.id AS `apply_id`,
                ppa.req_date AS `req_apply_date`,
                COALESCE(dc.denied_count, 0) AS `denied_count`
            FROM tb_product p
            INNER JOIN (
                SELECT ppa1.*
                FROM tb_product_paid_apply ppa1
                INNER JOIN (
                    SELECT product_id, MAX(id) as max_id
                    FROM tb_product_paid_apply
                    GROUP BY product_id
                ) ppa2 ON ppa1.product_id = ppa2.product_id AND ppa1.id = ppa2.max_id
            ) ppa ON p.product_id = ppa.product_id
            LEFT JOIN (
                SELECT product_id, COUNT(*) as episode_count
                FROM tb_product_episode
                WHERE use_yn = 'Y'
                GROUP BY product_id
            ) pe ON p.product_id = pe.product_id
            LEFT JOIN (
                SELECT product_id, COUNT(*) as denied_count
                FROM tb_product_paid_apply
                WHERE status_code = 'denied'
                GROUP BY product_id
            ) dc ON p.product_id = dc.product_id
            WHERE 1=1 {where}
            ORDER BY ppa.req_date DESC
            {limit_clause}
        """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def accept_apply_rank_up(apply_id: int, db: AsyncSession):
    """
    작품 승급 신청 승인 처리

    Args:
        apply_id: 승인할 신청 ID (tb_product_paid_apply.id)
        db: 데이터베이스 세션

    Returns:
        승인 처리 결과
    """
    query = text("""
                 SELECT * FROM tb_product_paid_apply WHERE id = :apply_id
                 """)
    result = await db.execute(query, {"apply_id": apply_id})
    rows = result.mappings().all()
    check_exists_or_404(rows, ErrorMessages.PROMOTION_UPGRADE_INFO_NOT_FOUND)

    row = dict(rows[0])

    if row["status_code"] == "accepted":
        # 이미 승인 함
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_APPROVED,
        )

    product_id = row["product_id"]

    # 1. 신청 상태를 승인으로 변경
    query = text("""
                 UPDATE tb_product_paid_apply SET status_code = 'accepted', approval_date = now() WHERE id = :apply_id
                 """)
    await db.execute(query, {"apply_id": apply_id})

    # 2. 작품을 유료로 전환
    query = text("""
                 UPDATE tb_product SET price_type = 'paid' WHERE product_id = :product_id
                 """)
    await db.execute(query, {"product_id": product_id})

    return {"result": True}


async def deny_apply_rank_up(apply_id: int, db: AsyncSession):
    """
    작품 승급 신청 반려 처리

    Args:
        apply_id: 반려할 신청 ID (tb_product_paid_apply.id)
        db: 데이터베이스 세션

    Returns:
        반려 처리 결과
    """
    query = text("""
                 SELECT * FROM tb_product_paid_apply WHERE id = :apply_id
                 """)
    result = await db.execute(query, {"apply_id": apply_id})
    rows = result.mappings().all()
    check_exists_or_404(rows, ErrorMessages.PROMOTION_UPGRADE_INFO_NOT_FOUND)

    row = dict(rows[0])

    if row["status_code"] == "denied":
        # 이미 반려 함
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_REJECTED,
        )

    query = text("""
                 UPDATE tb_product_paid_apply SET status_code = 'denied', approval_date = now() WHERE id = :apply_id
                 """)
    await db.execute(query, {"apply_id": apply_id})

    return {"result": True}


@handle_exceptions
async def put_auth_identity_password_reset(
    req_body: auth_schema.IdentityPasswordResetReqBody, user_id: int, db: AsyncSession
):
    """
    사용자 비밀번호 재설정 (본인인증)

    Args:
        req_body: 비밀번호 재설정 요청 데이터 (이름, 성별, 생년월일, 이메일, 새 비밀번호)
        user_id: 비밀번호를 재설정할 사용자 ID
        db: 데이터베이스 세션

    Returns:
        비밀번호 재설정 결과 (void)
    """
    # TODO: 본인인증 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)
    where_fields = []
    execute_params = {}
    if req_body.user_name is not None:
        where_fields.append("a.user_name = :user_name")
        execute_params["user_name"] = req_body.user_name
    if req_body.gender is not None:
        where_fields.append("a.gender = :gender")
        execute_params["gender"] = req_body.gender
    if req_body.birthdate is not None:
        where_fields.append(
            "REPLACE(a.birthdate, '-', '') = REPLACE(:birthdate, '-', '')"
        )
        execute_params["birthdate"] = req_body.birthdate
    if req_body.email is not None:
        where_fields.append("a.email = :email")
        execute_params["email"] = req_body.email
    if (
        len(where_fields) == 0
    ):  # 위의 4개의 필드로 검색을 하는 로직인데, 위의 4개의 필드가 없으면 로그인한 유저의 정보로 검색
        where_fields.append("a.user_id = :user_id")
        execute_params["user_id"] = user_id
    # 먼저 유저 정보 확인 (SNS 타입 및 탈퇴 여부 체크 포함)
    query = text(f"""
                        select a.kc_user_id, a.latest_signed_type, a.use_yn
                        from tb_user a
                        where {" and ".join(where_fields)}
                        """)

    result = await db.execute(query, execute_params)
    db_rst = result.mappings().all()

    if not db_rst:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_USER,
        )

    kc_user_id = db_rst[0].get("kc_user_id")
    latest_signed_type = db_rst[0].get("latest_signed_type")
    use_yn = db_rst[0].get("use_yn")

    # 탈퇴한 회원 체크
    if use_yn == "N":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_WITHDRAWN_MEMBER,
        )

    # SNS 계정 체크 (네이버, 구글, 카카오, 애플은 비밀번호 변경 불가)
    if latest_signed_type in ("naver", "google", "kakao", "apple"):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.SNS_ACCOUNT_PASSWORD_RESET_NOT_ALLOWED_ADMIN,
        )

    # Keycloak에서 비밀번호 변경
    res_json = await comm_service.kc_token_endpoint(method="POST", type="client_normal")
    admin_acc_token = res_json.get("access_token")

    cred_data = {
        "type": "password",
        "value": req_body.password,
        "temporary": False,
    }

    cred_data_to_list = list()
    cred_data_to_list.append(cred_data)

    data = {"credentials": cred_data_to_list}
    try:
        await comm_service.kc_users_id_endpoint(
            method="PUT",
            admin_acc_token=admin_acc_token,
            id=kc_user_id,
            data_dict=data,
        )
    except CustomResponseException as e:
        if e.status_code == status.HTTP_404_NOT_FOUND:
            # keycloak쪽 데이터가 없음
            pass
        else:
            raise e

    return


@handle_exceptions
async def put_auth_signoff(user_id: int, db: AsyncSession):
    """
    사용자 탈퇴 처리

    Args:
        user_id: 탈퇴할 사용자 ID
        db: 데이터베이스 세션

    Returns:
        탈퇴 처리 결과 (void)
    """
    # 탈퇴 전 이메일 조회
    query = text("""
                    select email
                    from tb_user
                    where user_id = :user_id
                    """)
    result = await db.execute(query, {"user_id": user_id})
    email_rst = result.mappings().all()
    original_email = email_rst[0].get("email") if email_rst else ""

    query = text("""
                        select 1
                        from tb_user_social
                        where integrated_user_id = :user_id
                        and default_yn = 'Y'
                        """)

    result = await db.execute(query, {"user_id": user_id})
    db_rst = result.mappings().all()

    # 개별아이디 혹은 통합아이디 로그인 상태
    if db_rst:
        # 통합아이디
        # TODO: 통합아이디 연동 모듈 구현 후 수정 및 최종 테스트 필(현재 개별아이디 개발 완료. 나머지 초안 개발 완료)

        # 탈퇴 시간 생성
        import time

        timestamp = int(time.time())
        outed_email = f"outed;{timestamp};{original_email}"

        query = text("""
                            update tb_user a
                            inner join (
                                select z.user_id
                                from tb_user_social z
                                where z.integrated_user_id = :user_id
                            ) as t on a.user_id = t.user_id
                            set a.use_yn = 'N',
                                a.email = :outed_email
                            where 1=1
                            """)

        await db.execute(query, {"user_id": user_id, "outed_email": outed_email})

        # tb_algorithm_recommend_user 레코드 삭제
        query = text("""
                            delete from tb_algorithm_recommend_user
                            where user_id in (
                                select z.user_id
                                from tb_user_social z
                                where z.integrated_user_id = :user_id
                            )
                            """)

        await db.execute(query, {"user_id": user_id})

        res_json = await comm_service.kc_token_endpoint(
            method="POST", type="client_normal"
        )
        admin_acc_token = res_json.get("access_token")

        """
        kc_users_id_endpoint (delete)
            user 회원정보 delete
            user_entity의 enabled False 처리 대신에, 이후 재가입할 경우 완전한 초기화 방향으로
        """
        query = text("""
                            select a.kc_user_id
                            from tb_user a
                            where a.user_id in (select z.user_id from tb_user_social z
                                                where z.integrated_user_id = :user_id)
                            """)

        result = await db.execute(query, {"user_id": user_id})
        db_rst = result.mappings().all()

        for row in db_rst:
            kc_user_id = row.get("kc_user_id")
            try:
                await comm_service.kc_users_id_endpoint(
                    method="DELETE",
                    admin_acc_token=admin_acc_token,
                    id=kc_user_id,
                )
            except CustomResponseException as e:
                if e.status_code == status.HTTP_404_NOT_FOUND:
                    # keycloak쪽 데이터가 없음
                    pass
                else:
                    raise e

        query = text("""
                            delete from tb_user_social a
                            where a.user_id in (select z.user_id from tb_user_social z
                                                where z.integrated_user_id = :user_id)
                            """)

        await db.execute(query, {"user_id": user_id})
    else:
        query = text("""
                            select kc_user_id, use_yn
                            from tb_user
                            where user_id = :user_id
                            """)

        result = await db.execute(query, {"user_id": user_id})
        db_rst = result.mappings().all()
        kc_user_id = db_rst[0].get("kc_user_id")
        use_yn = db_rst[0].get("use_yn")

        if use_yn == "N":
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.ALREADY_WITHDRAWN_MEMBER,
            )

        # 개별아이디

        # 탈퇴 시간 생성
        import time

        timestamp = int(time.time())
        outed_email = f"outed;{timestamp};{original_email}"

        query = text("""
                            update tb_user
                            set use_yn = 'N',
                                email = :outed_email
                            where user_id = :user_id
                            """)

        await db.execute(query, {"user_id": user_id, "outed_email": outed_email})

        # tb_algorithm_recommend_user 레코드 삭제
        query = text("""
                            delete from tb_algorithm_recommend_user
                            where user_id = :user_id
                            """)

        await db.execute(query, {"user_id": user_id})

        query = text("""
                            delete from tb_user_social
                            where user_id = :user_id
                            """)

        await db.execute(query, {"user_id": user_id})

        res_json = await comm_service.kc_token_endpoint(
            method="POST", type="client_normal"
        )
        admin_acc_token = res_json.get("access_token")

        """
        kc_users_id_endpoint (delete)
            user 회원정보 delete
            user_entity의 enabled False 처리 대신에, 이후 재가입할 경우 완전한 초기화 방향으로
        """
        try:
            await comm_service.kc_users_id_endpoint(
                method="DELETE", admin_acc_token=admin_acc_token, id=kc_user_id
            )
        except CustomResponseException as e:
            if e.status_code == status.HTTP_404_NOT_FOUND:
                # keycloak쪽 데이터가 없음
                pass
            else:
                raise e

    return
