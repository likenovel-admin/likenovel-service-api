import logging
from app.services.common import comm_service
from fastapi import status
from app.const import ErrorMessages
from app.services.product.product_service import (
    convert_product_data,
    get_select_fields_and_joins_for_product,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

import app.schemas.product_review as product_review_schema
import app.services.common.statistics_service as statistics_service
from app.exceptions import CustomResponseException
from app.utils.query import (
    build_insert_query,
    build_update_query,
    get_file_path_sub_query,
    get_badge_image_sub_query,
)

logger = logging.getLogger("product_review_app")  # 커스텀 로거 생성

"""
product_review 작품 리뷰 개별 서비스 함수 모음
"""


async def product_review_list(
    kc_user_id: str | None, genres: list[str] | None, db: AsyncSession
):
    # 1. kc_user_id로 user_id 조회 (로그인 안되어 있으면 None)
    user_id = None
    if kc_user_id:
        user_query = text("""
            SELECT user_id
            FROM tb_user
            WHERE kc_user_id = :kc_user_id AND use_yn = 'Y'
        """)
        user_result = await db.execute(user_query, {"kc_user_id": kc_user_id})
        user_row = user_result.mappings().one_or_none()

        if user_row:
            user_id = user_row["user_id"]

    # 2. 작품 정보를 가져오기 위한 select fields와 joins 가져오기
    product_fields = get_select_fields_and_joins_for_product(user_id=user_id)

    # 3. 장르 필터링 조건 추가
    genre_filter = ""
    params = {}

    if genres:
        genre_placeholders = ", ".join([f":genre_{i}" for i in range(len(genres))])
        genre_filter = f"AND (pg.keyword_name IN ({genre_placeholders}) OR sg.keyword_name IN ({genre_placeholders}))"
        for i, genre in enumerate(genres):
            params[f"genre_{i}"] = genre

    # 4. liked, commented 조건부 쿼리 생성
    liked_query = (
        f"COALESCE((SELECT 1 FROM tb_product_review_like prl WHERE prl.review_id = pr.id AND prl.user_id = {user_id} LIMIT 1), 0)"
        if user_id
        else "0"
    )
    commented_query = (
        f"COALESCE((SELECT 1 FROM tb_product_review_comment prc WHERE prc.review_id = pr.id AND prc.user_id = {user_id} LIMIT 1), 0)"
        if user_id
        else "0"
    )

    # 5. 차단된 유저 제외 조건 추가 (댓글 차단이든 리뷰 차단이든 상관없이 작성자가 차단되면 제외)
    blocked_user_filter = ""
    if user_id:
        blocked_user_filter = f"""
            AND NOT EXISTS (
                SELECT 1 FROM tb_user_block ub
                WHERE ub.user_id = {user_id}
                    AND ub.off_user_id = pr.user_id
                    AND ub.off_yn = 'Y'
                    AND ub.use_yn = 'Y'
            )
        """

    # 6. 리뷰 정보와 작품 정보를 함께 조회
    query = text(f"""
        SELECT
            pr.id as review_id,
            pr.product_id as review_product_id,
            pr.episode_id as review_episode_id,
            pr.user_id as review_user_id,
            pr.review_title as review_title,
            pr.review_text as review_text,
            pr.created_date as review_created_date,
            pr.updated_date as review_updated_date,
            up.profile_id as reviewer_profile_id,
            up.nickname as reviewer_nickname,
            up.role_type as reviewer_role,
            {get_file_path_sub_query("up.profile_image_id", "reviewer_profile_image_path")},
            {get_badge_image_sub_query("pr.user_id", "interest", "reviewer_interest_level_badge_image_path", "up.profile_id")},
            {get_badge_image_sub_query("pr.user_id", "event", "reviewer_event_level_badge_image_path", "up.profile_id")},
            COALESCE((SELECT COUNT(*) FROM tb_product_review_like prl WHERE prl.review_id = pr.id), 0) as review_likes_count,
            COALESCE((SELECT COUNT(*) FROM tb_product_review_comment prc WHERE prc.review_id = pr.id), 0) as review_comments_count,
            {liked_query} as review_liked,
            {commented_query} as review_commented,
            {product_fields["select_fields"]}
        FROM tb_product_review pr
        INNER JOIN tb_product p ON pr.product_id = p.product_id
        LEFT JOIN tb_user_profile up ON pr.user_id = up.user_id AND up.default_yn = 'Y'
        {product_fields["joins"]}
        WHERE 1=1
          AND pr.open_yn = 'Y'
          {genre_filter} {blocked_user_filter}
        ORDER BY pr.updated_date DESC
    """)

    result = await db.execute(query, params)
    rows = result.mappings().all()

    # 6. 작품 데이터를 convert_product_data로 변환
    converted_data = []
    for row in rows:
        product_data = convert_product_data(row)
        # 리뷰 정보 추가
        review_data = {
            "id": row["review_id"],
            "productId": row["review_product_id"],
            "episodeId": row["review_episode_id"],
            "userId": row["review_user_id"],
            "reviewTitle": row["review_title"],
            "reviewText": row["review_text"],
            "createdDate": row["review_created_date"],
            "updatedDate": row["review_updated_date"],
            "reviewer": {
                "profileId": row["reviewer_profile_id"],
                "nickname": row["reviewer_nickname"],
                "profileImagePath": row["reviewer_profile_image_path"],
                "userInterestLevelBadgeImagePath": row[
                    "reviewer_interest_level_badge_image_path"
                ],
                "userEventLevelBadgeImagePath": row[
                    "reviewer_event_level_badge_image_path"
                ],
                "userRole": row["reviewer_role"],
            },
            "likesCount": row["review_likes_count"],
            "liked": "Y" if bool(row["review_liked"]) else "N",
            "commentsCount": row["review_comments_count"],
            "commented": "Y" if bool(row["review_commented"]) else "N",
        }
        converted_data.append({"product": product_data, "review": review_data})

    res_body = dict()
    res_body["data"] = converted_data

    return res_body


async def product_review_detail_by_id(
    id: int, kc_user_id: str | None, db: AsyncSession
):
    """
    작품 리뷰(product_review) 상세 조회
    """
    # 1. kc_user_id로 user_id 조회 (로그인 안되어 있으면 None)
    user_id = None
    if kc_user_id:
        user_query = text("""
            SELECT user_id
            FROM tb_user
            WHERE kc_user_id = :kc_user_id AND use_yn = 'Y'
        """)
        user_result = await db.execute(user_query, {"kc_user_id": kc_user_id})
        user_row = user_result.mappings().one_or_none()

        if user_row:
            user_id = user_row["user_id"]

    # 2. 작품 정보를 가져오기 위한 select fields와 joins 가져오기
    product_fields = get_select_fields_and_joins_for_product(user_id=user_id)

    # 3. liked, commented 조건부 쿼리 생성
    liked_query = (
        f"COALESCE((SELECT 1 FROM tb_product_review_like prl WHERE prl.review_id = pr.id AND prl.user_id = {user_id} LIMIT 1), 0)"
        if user_id
        else "0"
    )
    commented_query = (
        f"COALESCE((SELECT 1 FROM tb_product_review_comment prc WHERE prc.review_id = pr.id AND prc.user_id = {user_id} LIMIT 1), 0)"
        if user_id
        else "0"
    )

    # 4. 리뷰 정보와 작품 정보를 함께 조회
    query = text(f"""
        SELECT
            pr.id as review_id,
            pr.product_id as review_product_id,
            pr.episode_id as review_episode_id,
            pr.user_id as review_user_id,
            pr.review_title as review_title,
            pr.review_text as review_text,
            pr.created_date as review_created_date,
            pr.updated_date as review_updated_date,
            up.profile_id as reviewer_profile_id,
            up.nickname as reviewer_nickname,
            up.role_type as reviewer_role,
            {get_file_path_sub_query("up.profile_image_id", "reviewer_profile_image_path")},
            {get_badge_image_sub_query("pr.user_id", "interest", "reviewer_interest_level_badge_image_path", "up.profile_id")},
            {get_badge_image_sub_query("pr.user_id", "event", "reviewer_event_level_badge_image_path", "up.profile_id")},
            COALESCE((SELECT COUNT(*) FROM tb_product_review_like prl WHERE prl.review_id = pr.id), 0) as likes_count,
            COALESCE((SELECT COUNT(*) FROM tb_product_review_comment prc WHERE prc.review_id = pr.id), 0) as comments_count,
            {liked_query} as liked,
            {commented_query} as commented,
            {product_fields["select_fields"]}
        FROM tb_product_review pr
        INNER JOIN tb_product p ON pr.product_id = p.product_id
        LEFT JOIN tb_user_profile up ON pr.user_id = up.user_id AND up.default_yn = 'Y'
        {product_fields["joins"]}
        WHERE pr.id = :id
    """)

    result = await db.execute(query, {"id": id})
    row = result.mappings().one_or_none()

    if not row:
        res_body = {"data": None}
        return res_body

    # 5. 차단된 유저 제외 조건 추가
    blocked_comment_user_filter = ""
    if user_id:
        blocked_comment_user_filter = f"""
            AND NOT EXISTS (
                SELECT 1 FROM tb_user_block ub
                WHERE ub.user_id = {user_id}
                    AND ub.off_user_id = prc.user_id
                    AND ub.off_yn = 'Y'
                    AND ub.use_yn = 'Y'
            )
        """

    # 6. 댓글 리스트 조회
    comment_query = text(f"""
        SELECT
            prc.id as comment_id,
            prc.review_id,
            prc.user_id as comment_user_id,
            prc.comment_text,
            prc.created_date as comment_created_date,
            prc.updated_date as comment_updated_date,
            cup.profile_id as commenter_profile_id,
            cup.nickname as commenter_nickname,
            cup.role_type as commenter_role,
            {get_file_path_sub_query("cup.profile_image_id", "commenter_profile_image_path")},
            {get_badge_image_sub_query("prc.user_id", "interest", "commenter_interest_level_badge_image_path", "cup.profile_id")},
            {get_badge_image_sub_query("prc.user_id", "event", "commenter_event_level_badge_image_path", "cup.profile_id")}
        FROM tb_product_review_comment prc
        LEFT JOIN tb_user_profile cup ON prc.user_id = cup.user_id AND cup.default_yn = 'Y'
        WHERE prc.review_id = :id
          {blocked_comment_user_filter}
        ORDER BY prc.created_date ASC
    """)

    comment_result = await db.execute(comment_query, {"id": id})
    comment_rows = comment_result.mappings().all()

    # 6. 댓글 데이터 변환
    comments = []
    for comment_row in comment_rows:
        comments.append(
            {
                "id": comment_row["comment_id"],
                "reviewId": comment_row["review_id"],
                "userId": comment_row["comment_user_id"],
                "commentText": comment_row["comment_text"],
                "createdDate": comment_row["comment_created_date"],
                "updatedDate": comment_row["comment_updated_date"],
                "commenter": {
                    "profileId": comment_row["commenter_profile_id"],
                    "nickname": comment_row["commenter_nickname"],
                    "profileImagePath": comment_row["commenter_profile_image_path"],
                    "userInterestLevelBadgeImagePath": comment_row[
                        "commenter_interest_level_badge_image_path"
                    ],
                    "userEventLevelBadgeImagePath": comment_row[
                        "commenter_event_level_badge_image_path"
                    ],
                    "userRole": comment_row["commenter_role"],
                },
            }
        )

    # 7. 작품 데이터를 convert_product_data로 변환
    product_data = convert_product_data(row)
    review_data = {
        "id": row["review_id"],
        "productId": row["review_product_id"],
        "episodeId": row["review_episode_id"],
        "userId": row["review_user_id"],
        "reviewTitle": row["review_title"],
        "reviewText": row["review_text"],
        "createdDate": row["review_created_date"],
        "updatedDate": row["review_updated_date"],
        "reviewer": {
            "profileId": row["reviewer_profile_id"],
            "nickname": row["reviewer_nickname"],
            "profileImagePath": row["reviewer_profile_image_path"],
            "userInterestLevelBadgeImagePath": row[
                "reviewer_interest_level_badge_image_path"
            ],
            "userEventLevelBadgeImagePath": row[
                "reviewer_event_level_badge_image_path"
            ],
            "userRole": row["reviewer_role"],
        },
        "likesCount": row["likes_count"],
        "liked": bool(row["liked"]),
        "commentsCount": row["comments_count"],
        "commented": bool(row["commented"]),
    }

    res_body = {
        "data": {"product": product_data, "review": review_data, "comments": comments}
    }
    return res_body


async def post_product_review(
    req_body: product_review_schema.PostProductReviewReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    if req_body is not None:
        logger.info(f"post_product_review: {req_body}")

    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    columns, values, params = build_insert_query(
        req_body,
        required_fields=["product_id", "user_id", "review_title", "review_text"],
    )

    query = text(
        f"INSERT INTO tb_product_review (id, {columns}, created_id, created_date) VALUES (default, {values}, :created_id, :created_date)"
    )

    await db.execute(query, params)

    await statistics_service.insert_site_statistics_log(
        db=db, type="active", user_id=user_id
    )

    return {"result": req_body}


async def put_product_review(
    id: int,
    req_body: product_review_schema.PutProductReviewReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    if req_body is not None:
        logger.info(f"put_product_review: {req_body}")

    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    set_clause, params = build_update_query(
        req_body,
        allowed_fields=["product_id", "user_id", "review_title", "review_text"],
    )
    params["id"] = id

    query = text(f"UPDATE tb_product_review SET {set_clause} WHERE id = :id")

    await db.execute(query, params)

    return {"result": req_body}


async def delete_product_review(id: int, user_id: str, db: AsyncSession):
    query = text("""
                        delete from tb_product_review where id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}


async def check_like_product_review(review_id: int, kc_user_id: str, db: AsyncSession):
    """
    리뷰 좋아요 여부 체크
    """
    query = text("""
        SELECT 1
        FROM tb_product_review_like
        WHERE review_id = :review_id
          AND user_id = (SELECT user_id FROM tb_user WHERE kc_user_id = :kc_user_id)
    """)
    result = await db.execute(query, {"review_id": review_id, "kc_user_id": kc_user_id})
    row = result.mappings().one_or_none()
    return row is not None


async def add_like_product_review(review_id: int, kc_user_id: str, db: AsyncSession):
    """
    리뷰 좋아요 추가
    """
    check = await check_like_product_review(review_id, kc_user_id, db)
    if check is True:
        raise CustomResponseException(
            status_code=400, message=ErrorMessages.ALREADY_LIKED
        )

    query = text("""
        INSERT INTO tb_product_review_like (review_id, user_id, created_id)
        VALUES (
            :review_id,
            (SELECT user_id FROM tb_user WHERE kc_user_id = :kc_user_id),
            -1
        )
    """)
    await db.execute(query, {"review_id": review_id, "kc_user_id": kc_user_id})
    return {"result": True}


async def remove_like_product_review(review_id: int, kc_user_id: str, db: AsyncSession):
    """
    리뷰 좋아요 삭제
    """
    check = await check_like_product_review(review_id, kc_user_id, db)
    if check is False:
        raise CustomResponseException(
            status_code=400, message=ErrorMessages.NOT_LIKED_YET
        )

    query = text("""
        DELETE FROM tb_product_review_like
        WHERE review_id = :review_id
          AND user_id = (SELECT user_id FROM tb_user WHERE kc_user_id = :kc_user_id)
    """)
    await db.execute(query, {"review_id": review_id, "kc_user_id": kc_user_id})
    return {"result": True}


async def post_product_review_comment(
    review_id: int,
    req_body: product_review_schema.PostProductReviewCommentReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    리뷰 댓글 작성
    """
    if req_body is not None:
        logger.info(f"post_product_review_comment: {req_body}")

    # 1. kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # 2. 리뷰가 존재하는지 확인
    review_check_query = text("""
        SELECT id FROM tb_product_review WHERE id = :review_id
    """)
    review_result = await db.execute(review_check_query, {"review_id": review_id})
    review_row = review_result.mappings().one_or_none()

    if not review_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_REVIEW,
        )

    # 3. 댓글 등록
    db_execute_params = {
        "review_id": review_id,
        "user_id": user_id,
        "comment_text": req_body.comment_text,
        "created_id": -1,
        "created_date": datetime.now(),
    }

    insert_query = text("""
        INSERT INTO tb_product_review_comment
        (review_id, user_id, comment_text, created_id, created_date)
        VALUES (:review_id, :user_id, :comment_text, :created_id, :created_date)
    """)

    result = await db.execute(insert_query, db_execute_params)
    comment_id = result.lastrowid

    # 4. 통계 로그 기록
    await statistics_service.insert_site_statistics_log(
        db=db, type="active", user_id=user_id
    )

    return {
        "result": {
            "id": comment_id,
            "reviewId": review_id,
            "userId": user_id,
            "commentText": req_body.comment_text,
        }
    }


async def put_product_review_comment(
    comment_id: int,
    req_body: product_review_schema.PutProductReviewCommentReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    리뷰 댓글 수정
    """
    if req_body is not None:
        logger.info(f"put_product_review_comment: {req_body}")

    # 1. kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # 2. 댓글 존재 여부 및 작성자 확인
    comment_check_query = text("""
        SELECT user_id, review_id
        FROM tb_product_review_comment
        WHERE id = :comment_id
    """)
    comment_result = await db.execute(comment_check_query, {"comment_id": comment_id})
    comment_row = comment_result.mappings().one_or_none()

    if not comment_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_COMMENT,
        )

    if comment_row["user_id"] != user_id:
        raise CustomResponseException(
            status_code=status.HTTP_403_FORBIDDEN,
            message=ErrorMessages.COMMENT_AUTHOR_ONLY_MODIFY,
        )

    # 3. 댓글 수정
    db_execute_params = {
        "comment_id": comment_id,
        "comment_text": req_body.comment_text,
        "updated_id": -1,
        "updated_date": datetime.now(),
    }

    update_query = text("""
        UPDATE tb_product_review_comment
        SET comment_text = :comment_text,
            updated_id = :updated_id,
            updated_date = :updated_date
        WHERE id = :comment_id
    """)

    await db.execute(update_query, db_execute_params)
    return {
        "result": {
            "id": comment_id,
            "reviewId": comment_row["review_id"],
            "userId": user_id,
            "commentText": req_body.comment_text,
        }
    }


async def delete_product_review_comment(
    comment_id: int,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    리뷰 댓글 삭제
    """
    # 1. kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # 2. 댓글 존재 여부 및 작성자 확인
    comment_check_query = text("""
        SELECT user_id
        FROM tb_product_review_comment
        WHERE id = :comment_id
    """)
    comment_result = await db.execute(comment_check_query, {"comment_id": comment_id})
    comment_row = comment_result.mappings().one_or_none()

    if not comment_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_COMMENT,
        )

    if comment_row["user_id"] != user_id:
        raise CustomResponseException(
            status_code=status.HTTP_403_FORBIDDEN,
            message=ErrorMessages.COMMENT_AUTHOR_ONLY_DELETE,
        )

    # 3. 댓글 삭제
    delete_query = text("""
        DELETE FROM tb_product_review_comment
        WHERE id = :comment_id
    """)

    await db.execute(delete_query, {"comment_id": comment_id})

    return {"result": True}


async def post_product_review_report(
    review_id: int,
    req_body: product_review_schema.PostProductReviewReportReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    리뷰 신고
    """
    if req_body is not None:
        logger.info(f"post_product_review_report: {req_body}")

    # 1. kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # 2. 리뷰가 존재하는지 확인
    review_check_query = text("""
        SELECT id, user_id FROM tb_product_review WHERE id = :review_id
    """)
    review_result = await db.execute(review_check_query, {"review_id": review_id})
    review_row = review_result.mappings().one_or_none()

    if not review_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_REVIEW,
        )

    # 3. 자신의 리뷰를 신고하는 것인지 확인
    if review_row["user_id"] == user_id:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.CANNOT_REPORT_OWN_REVIEW,
        )

    # 4. 이미 신고한 리뷰인지 확인
    duplicate_check_query = text("""
        SELECT id FROM tb_product_review_report
        WHERE review_id = :review_id AND reporter_user_id = :reporter_user_id
    """)
    duplicate_result = await db.execute(
        duplicate_check_query, {"review_id": review_id, "reporter_user_id": user_id}
    )
    duplicate_row = duplicate_result.mappings().one_or_none()

    if duplicate_row:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_REPORTED_REVIEW,
        )

    # 5. 신고 등록
    db_execute_params = {
        "review_id": review_id,
        "reporter_user_id": user_id,
        "report_reason": req_body.report_reason,
        "report_detail": req_body.report_detail,
        "status": "pending",
        "created_id": -1,
        "created_date": datetime.now(),
    }

    insert_query = text("""
        INSERT INTO tb_product_review_report
        (review_id, reporter_user_id, report_reason, report_detail, status, created_id, created_date)
        VALUES (:review_id, :reporter_user_id, :report_reason, :report_detail, :status, :created_id, :created_date)
    """)

    result = await db.execute(insert_query, db_execute_params)
    report_id = result.lastrowid

    # 6. 통계 로그 기록
    await statistics_service.insert_site_statistics_log(
        db=db, type="active", user_id=user_id
    )

    return {
        "result": {
            "id": report_id,
            "reviewId": review_id,
            "reporterUserId": user_id,
            "reportReason": req_body.report_reason,
            "reportDetail": req_body.report_detail,
            "status": "pending",
        }
    }


async def post_product_review_comment_report(
    comment_id: int,
    req_body: product_review_schema.PostProductReviewCommentReportReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    리뷰 댓글 신고
    """
    if req_body is not None:
        logger.info(f"post_product_review_comment_report: {req_body}")

    # 1. kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # 2. 댓글이 존재하는지 확인
    comment_check_query = text("""
        SELECT id, user_id, review_id FROM tb_product_review_comment WHERE id = :comment_id
    """)
    comment_result = await db.execute(comment_check_query, {"comment_id": comment_id})
    comment_row = comment_result.mappings().one_or_none()

    if not comment_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_REVIEW_COMMENT,
        )

    # 3. 자신의 댓글을 신고하는 것인지 확인
    if comment_row["user_id"] == user_id:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.CANNOT_REPORT_OWN_REVIEW_COMMENT,
        )

    # 4. 이미 신고한 댓글인지 확인
    duplicate_check_query = text("""
        SELECT id FROM tb_product_review_comment_report
        WHERE comment_id = :comment_id AND reporter_user_id = :reporter_user_id
    """)
    duplicate_result = await db.execute(
        duplicate_check_query, {"comment_id": comment_id, "reporter_user_id": user_id}
    )
    duplicate_row = duplicate_result.mappings().one_or_none()

    if duplicate_row:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_REPORTED_REVIEW_COMMENT,
        )

    # 5. 신고 등록
    db_execute_params = {
        "comment_id": comment_id,
        "reporter_user_id": user_id,
        "report_reason": req_body.report_reason,
        "report_detail": req_body.report_detail,
        "status": "pending",
        "created_id": -1,
        "created_date": datetime.now(),
    }

    insert_query = text("""
        INSERT INTO tb_product_review_comment_report
        (comment_id, reporter_user_id, report_reason, report_detail, status, created_id, created_date)
        VALUES (:comment_id, :reporter_user_id, :report_reason, :report_detail, :status, :created_id, :created_date)
    """)

    result = await db.execute(insert_query, db_execute_params)
    report_id = result.lastrowid

    # 6. 통계 로그 기록
    await statistics_service.insert_site_statistics_log(
        db=db, type="active", user_id=user_id
    )

    return {
        "result": {
            "id": report_id,
            "commentId": comment_id,
            "reviewId": comment_row["review_id"],
            "reporterUserId": user_id,
            "reportReason": req_body.report_reason,
            "reportDetail": req_body.report_detail,
            "status": "pending",
        }
    }


async def put_product_review_block(
    review_id: int,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    리뷰 작성자 차단/차단해제
    """
    res_data = {}
    review_id_to_int = int(review_id)

    if kc_user_id:
        try:
            async with db.begin():
                # 1. kc_user_id로 user_id 조회
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                # 2. 차단 상태 조회
                query = text("""
                    SELECT id, off_yn
                    FROM tb_user_block
                    WHERE user_id = :user_id
                        AND review_id = :review_id
                        AND use_yn = 'Y'
                """)

                result = await db.execute(
                    query, {"user_id": user_id, "review_id": review_id_to_int}
                )
                db_rst = result.mappings().all()

                if db_rst:
                    # 3-1. 기존 차단 정보 있음 - 차단 상태 반전
                    id = db_rst[0].get("id")
                    off_yn = db_rst[0].get("off_yn")

                    query = text("""
                        UPDATE tb_user_block
                        SET off_yn = (CASE WHEN off_yn = 'Y' THEN 'N' ELSE 'Y' END),
                            updated_id = :user_id
                        WHERE id = :id
                    """)

                    await db.execute(query, {"id": id, "user_id": user_id})

                    if off_yn == "N":
                        block_yn = "Y"
                    else:
                        block_yn = "N"
                else:
                    # 3-2. 차단 정보 없음 - 신규 차단 정보 생성
                    query = text("""
                        INSERT INTO tb_user_block (product_id, episode_id, comment_id, review_id, user_id, off_user_id, created_id, updated_id)
                        SELECT product_id, episode_id, NULL, :review_id, :user_id, user_id AS off_user_id, :created_id, :updated_id
                        FROM tb_product_review
                        WHERE id = :review_id
                    """)

                    await db.execute(
                        query,
                        {
                            "review_id": review_id_to_int,
                            "user_id": user_id,
                            "created_id": -1,
                            "updated_id": -1,
                        },
                    )

                    block_yn = "Y"

                res_data = {"reviewId": review_id_to_int, "blockYn": block_yn}

                # 4. 통계 로그 기록
                await statistics_service.insert_site_statistics_log(
                    db=db, type="active", user_id=user_id
                )

        except CustomResponseException:
            raise
        except Exception:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


async def put_product_review_comment_block(
    comment_id: int,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    리뷰 댓글 작성자 차단/차단해제
    """
    res_data = {}
    comment_id_to_int = int(comment_id)

    if kc_user_id:
        try:
            async with db.begin():
                # 1. kc_user_id로 user_id 조회
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                # 2. 차단 상태 조회
                query = text("""
                    SELECT id, off_yn
                    FROM tb_user_block
                    WHERE user_id = :user_id
                        AND comment_id = :comment_id
                        AND use_yn = 'Y'
                """)

                result = await db.execute(
                    query, {"user_id": user_id, "comment_id": comment_id_to_int}
                )
                db_rst = result.mappings().all()

                if db_rst:
                    # 3-1. 기존 차단 정보 있음 - 차단 상태 반전
                    id = db_rst[0].get("id")
                    off_yn = db_rst[0].get("off_yn")

                    query = text("""
                        UPDATE tb_user_block
                        SET off_yn = (CASE WHEN off_yn = 'Y' THEN 'N' ELSE 'Y' END),
                            updated_id = :user_id
                        WHERE id = :id
                    """)

                    await db.execute(query, {"id": id, "user_id": user_id})

                    if off_yn == "N":
                        block_yn = "Y"
                    else:
                        block_yn = "N"
                else:
                    # 3-2. 차단 정보 없음 - 신규 차단 정보 생성
                    query = text("""
                        INSERT INTO tb_user_block (product_id, episode_id, comment_id, review_id, user_id, off_user_id, created_id, updated_id)
                        SELECT NULL, NULL, :comment_id, review_id, :user_id, user_id AS off_user_id, :created_id, :updated_id
                        FROM tb_product_review_comment
                        WHERE id = :comment_id
                    """)

                    await db.execute(
                        query,
                        {
                            "comment_id": comment_id_to_int,
                            "user_id": user_id,
                            "created_id": -1,
                            "updated_id": -1,
                        },
                    )

                    block_yn = "Y"

                res_data = {"commentId": comment_id_to_int, "blockYn": block_yn}

                # 4. 통계 로그 기록
                await statistics_service.insert_site_statistics_log(
                    db=db, type="active", user_id=user_id
                )

        except CustomResponseException:
            raise
        except Exception:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body
