import csv
import io
import json
import logging
from fastapi import status, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from urllib.parse import quote

from app.exceptions import CustomResponseException
import app.schemas.admin as admin_schema
from app.utils.common import age_2_age_group
from app.utils.query import (
    build_insert_query,
    build_update_query,
    get_pagination_params,
)
from app.utils.response import build_paginated_response, check_exists_or_404
from app.const import CommonConstants
from app.const import ErrorMessages

logger = logging.getLogger("admin_app")

"""
관리자 추천 알고리즘 관리 서비스 함수 모음
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


async def algorithm_recommend_user_list(
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    알고리즘 추천 사용자 리스트 조회

    Args:
        search_target: 검색 대상 (이메일)
        search_word: 검색어
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        알고리즘 추천 사용자 리스트와 페이징 정보
    """

    if search_word != "":
        if search_target == CommonConstants.SEARCH_EMAIL:
            where = text(f"""
                          AND u.email LIKE '%{search_word}%'
                          """)
        else:
            where = text("""""")
    else:
        where = text("""""")

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        SELECT COUNT(*) AS total_count FROM tb_algorithm_recommend_user aru INNER JOIN tb_user u ON u.user_id = aru.user_id WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            aru.id,
            aru.user_id,
            aru.feature_basic,
            aru.feature_1,
            aru.feature_2,
            aru.feature_3,
            aru.feature_4,
            aru.feature_5,
            aru.feature_6,
            aru.feature_7,
            aru.feature_8,
            aru.feature_9,
            aru.feature_10,
            aru.created_date,
            aru.updated_date,
            u.email,
            u.role_type,
            CASE
                WHEN u.gender = 'M' THEN 'male'
                WHEN u.gender = 'F' THEN 'female'
                ELSE REGEXP_SUBSTR(feature_basic, '[a-zA-Z]+')
            END AS gender,
            IFNULL(TIMESTAMPDIFF(YEAR, u.birthdate, CURDATE()), REGEXP_SUBSTR(feature_basic, '[0-9]+')) AS age
        FROM tb_algorithm_recommend_user aru
        INNER JOIN tb_user u ON u.user_id = aru.user_id
        WHERE 1=1 {where}
        ORDER BY aru.created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "results": [dict(row) for row in rows],
        "latest_updated_date": await get_latest_updated_date(
            "tb_algorithm_recommend_user", db
        ),
    }


async def algorithm_recommend_user_csv_format_download(db: AsyncSession):
    """
    알고리즘 추천 사용자 데이터 CSV 파일 다운로드

    Args:
        db: 데이터베이스 세션

    Returns:
        CSV 파일 스트리밍 응답 (사용자 특성 데이터 포함)
    """

    query = text("""
        SELECT
            aru.id,
            aru.user_id,
            aru.feature_basic,
            aru.feature_1,
            aru.feature_2,
            aru.feature_3,
            aru.feature_4,
            aru.feature_5,
            aru.feature_6,
            aru.feature_7,
            aru.feature_8,
            aru.feature_9,
            aru.feature_10,
            u.email,
            u.role_type,
            CASE
                WHEN u.gender = 'M' THEN 'male'
                WHEN u.gender = 'F' THEN 'female'
                ELSE REGEXP_SUBSTR(feature_basic, '[a-zA-Z]+')
            END AS gender,
            IFNULL(TIMESTAMPDIFF(YEAR, u.birthdate, CURDATE()), REGEXP_SUBSTR(feature_basic, '[0-9]+')) AS age
        FROM tb_algorithm_recommend_user aru
        INNER JOIN tb_user u ON u.user_id = aru.user_id
        ORDER BY aru.id DESC
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    rows_dict = [dict(row) for row in rows]

    data = [
        {
            "user_id": row.get("user_id"),
            "이메일": row.get("email"),
            "유저타입": row.get("role_type"),
            "성별": row.get("gender"),
            "연령": age_2_age_group(row.get("age")),
            "feature_basic": row.get("feature_basic"),
            "feature_1": row.get("feature_1"),
            "feature_2": row.get("feature_2"),
            "feature_3": row.get("feature_3"),
            "feature_4": row.get("feature_4"),
            "feature_5": row.get("feature_5"),
            "feature_6": row.get("feature_6"),
            "feature_7": row.get("feature_7"),
            "feature_8": row.get("feature_8"),
            "feature_9": row.get("feature_9"),
            "feature_10": row.get("feature_10"),
        }
        for row in rows_dict
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote('알고리즘 추천구좌 - 유저 테이블.csv')}"
        },
    )


async def algorithm_recommend_user_csv_upload(file: UploadFile, db: AsyncSession):
    """
    알고리즘 추천 사용자 데이터 CSV 파일 업로드

    Args:
        file: 업로드할 CSV 파일
        db: 데이터베이스 세션

    Returns:
        CSV 업로드 처리 결과
    """

    # 파일 내용 읽기
    contents = await file.read()
    decoded = contents.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))

    # 각 row 처리
    for row in reader:
        # 기존 데이터가 있는지 체크
        query = text("""
                        SELECT id FROM tb_algorithm_recommend_user WHERE user_id = :user_id
                     """)
        result = await db.execute(
            query,
            {
                "user_id": row["user_id"],
            },
        )
        data = result.mappings().one_or_none()  # 있으면 데이터가 조회되고 없으면 None
        if data is None:
            # 없으면 insert
            query = text("""
                            INSERT INTO tb_algorithm_recommend_user (
                                feature_basic,
                                feature_1,
                                feature_2,
                                feature_3,
                                feature_4,
                                feature_5,
                                feature_6,
                                feature_7,
                                feature_8,
                                feature_9,
                                feature_10,
                                user_id
                            ) VALUES (
                                :feature_basic,
                                :feature_1,
                                :feature_2,
                                :feature_3,
                                :feature_4,
                                :feature_5,
                                :feature_6,
                                :feature_7,
                                :feature_8,
                                :feature_9,
                                :feature_10,
                                :user_id
                            )
                        """)
        else:
            # 있으면 update
            query = text("""
                            UPDATE tb_algorithm_recommend_user SET
                                feature_basic = :feature_basic,
                                feature_1 = :feature_1,
                                feature_2 = :feature_2,
                                feature_3 = :feature_3,
                                feature_4 = :feature_4,
                                feature_5 = :feature_5,
                                feature_6 = :feature_6,
                                feature_7 = :feature_7,
                                feature_8 = :feature_8,
                                feature_9 = :feature_9,
                                feature_10 = :feature_10
                            WHERE user_id = :user_id
                        """)
        await db.execute(
            query,
            {
                "feature_basic": row["feature_basic"],
                "feature_1": row["feature_1"],
                "feature_2": row["feature_2"],
                "feature_3": row["feature_3"],
                "feature_4": row["feature_4"],
                "feature_5": row["feature_5"],
                "feature_6": row["feature_6"],
                "feature_7": row["feature_7"],
                "feature_8": row["feature_8"],
                "feature_9": row["feature_9"],
                "feature_10": row["feature_10"],
                "user_id": row["user_id"],
            },
        )

    return {"result": True}


async def algorithm_recommend_set_topic_list(
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    알고리즘 추천 주제 설정 리스트 조회

    Args:
        search_target: 검색 대상 ('product_id')
        search_word: 검색어
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        알고리즘 추천 주제 설정 리스트와 페이징 정보
    """

    if search_word != "":
        if search_target == "product_id":
            where = text(f"""
                          AND novel_list LIKE '%{search_word}%'
                          """)
        else:
            where = text("""""")
    else:
        where = text("""""")

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        SELECT COUNT(*) AS total_count FROM tb_algorithm_recommend_set_topic WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            *
        FROM tb_algorithm_recommend_set_topic WHERE 1=1 {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "results": [dict(row) for row in rows],
        "latest_updated_date": await get_latest_updated_date(
            "tb_algorithm_recommend_set_topic", db
        ),
    }


async def algorithm_recommend_set_topic_csv_format_download(db: AsyncSession):
    """
    알고리즘 추천 주제 설정 CSV 파일 다운로드

    Args:
        db: 데이터베이스 세션

    Returns:
        CSV 파일 스트리밍 응답 (주제 설정 데이터 포함)
    """

    query = text("""
        SELECT
            *
        FROM tb_algorithm_recommend_set_topic
        ORDER BY id DESC
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    rows_dict = [dict(row) for row in rows]

    data = [
        {
            "feature": row.get("feature"),
            "target": row.get("target"),
            "title": row.get("title"),
            "novel_list": row.get("novel_list"),
        }
        for row in rows_dict
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote('알고리즘 추천구좌 - 주제 설정 테이블.csv')}"
        },
    )


async def algorithm_recommend_set_topic_csv_upload(file: UploadFile, db: AsyncSession):
    """
    알고리즘 추천 주제 설정 CSV 파일 업로드

    Args:
        file: 업로드할 CSV 파일
        db: 데이터베이스 세션

    Returns:
        CSV 업로드 처리 결과
    """

    # 파일 내용 읽기
    contents = await file.read()
    decoded = contents.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))

    # 각 row 처리
    for row in reader:
        query = text("""
                    UPDATE tb_algorithm_recommend_set_topic SET
                        title = :title,
                        novel_list = :novel_list
                    WHERE feature = :feature AND target = :target
                    """)
        await db.execute(query, row)

    # 업로드된 데이터 중 유효한 데이터 반환
    return {"result": True}


async def algorithm_recommend_section_list(
    page: int, count_per_page: int, db: AsyncSession
):
    """
    알고리즘 추천 섹션 리스트 조회

    Args:
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        알고리즘 추천 섹션 리스트와 페이징 정보
    """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text("""
        SELECT COUNT(*) AS total_count FROM tb_algorithm_recommend_section
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            *
        FROM tb_algorithm_recommend_section
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def put_algorithm_recommend_section(
    id: int,
    req_body: admin_schema.PutAlgorithmRecommendSectionReqBody,
    db: AsyncSession,
):
    """
    알고리즘 추천 섹션 수정

    Args:
        id: 수정할 섹션 ID
        req_body: 수정할 섹션 정보 (위치, 특성 등)
        db: 데이터베이스 세션

    Returns:
        섹션 수정 결과
    """

    if req_body is not None:
        logger.info(f"put_algorithm_recommend_section: {req_body}")

    query = text("""
                    SELECT * FROM tb_algorithm_recommend_section WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_ALGORITHM_RECOMMEND)

    set_clause, params = build_update_query(
        req_body, allowed_fields=["position", "feature"]
    )
    params["id"] = id

    query = text(
        f"UPDATE tb_algorithm_recommend_section SET {set_clause} WHERE id = :id"
    )

    await db.execute(query, params)

    return {"result": req_body}


async def algorithm_recommend_similar_list(
    type: str,
    search_target: str,
    search_word: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    알고리즘 추천구좌 관리 - 추천1 내용비슷
    알고리즘 추천구좌 관리 - 추천2 장르비슷
    알고리즘 추천구좌 관리 - 추천3 장바구니

    Args:
        type: 추천 유형 ('content', 'genre', 'cart')
        search_target: 검색 대상 ('product_id')
        search_word: 검색어
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        추천 유형에 따른 추천구좌 리스트와 페이징 정보
    """

    if type == "content":
        where = """
                     WHERE type = 'content'
                     """
    elif type == "genre":
        where = """
                     WHERE type = 'genre'
                     """
    elif type == "cart":
        where = """
                     WHERE type = 'cart'
                     """

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_ID:
            where += f"""
                          AND product_id = {search_word}
                          """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        SELECT COUNT(*) AS total_count FROM tb_algorithm_recommend_similar {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            *
        FROM tb_algorithm_recommend_similar
        {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "results": [dict(row) for row in rows],
        "latest_updated_date": await get_latest_updated_date(
            "tb_algorithm_recommend_similar", db
        ),
    }


async def algorithm_recommend_similar_csv_format_download(type: str, db: AsyncSession):
    """
    알고리즘 추천구좌 관리 - 추천1 내용비슷 csv 다운로드
    알고리즘 추천구좌 관리 - 추천2 장르비슷 csv 다운로드
    알고리즘 추천구좌 관리 - 추천3 장바구니 csv 다운로드

    Args:
        type: 추천 유형 ('content', 'genre', 'cart')
        db: 데이터베이스 세션

    Returns:
        추천 유형에 따른 추천구좌 CSV 파일 스트리밍 응답
    """

    if type == "content":
        where = """
                     WHERE type = 'content'
                     """
    elif type == "genre":
        where = """
                     WHERE type = 'genre'
                     """
    elif type == "cart":
        where = """
                     WHERE type = 'cart'
                     """

    query = text(f"""
        SELECT
            *
        FROM tb_algorithm_recommend_similar
        {where}
        ORDER BY created_date DESC
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    rows_dict = [dict(row) for row in rows]

    data = [
        {
            "product_id": row.get("product_id"),
            "similar_subject_ids": row.get("similar_subject_ids"),
        }
        for row in rows_dict
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)

    output.seek(0)

    if type == "content":
        typeKor = "추천1 내용비슷"
    elif type == "genre":
        typeKor = "추천2 장르비슷"
    elif type == "cart":
        typeKor = "추천3 장바구니"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(f'알고리즘 추천구좌 - {typeKor}.csv')}"
        },
    )


async def algorithm_recommend_similar_csv_upload(
    type: str, file: UploadFile, db: AsyncSession
):
    """
    알고리즘 추천구좌 관리 - 추천1 내용비슷 csv 업로드
    알고리즘 추천구좌 관리 - 추천2 장르비슷 csv 업로드
    알고리즘 추천구좌 관리 - 추천3 장바구니 csv 업로드

    Args:
        type: 추천 유형 ('content', 'genre', 'cart')
        file: 업로드할 CSV 파일
        db: 데이터베이스 세션

    Returns:
        CSV 업로드 처리 결과
    """

    # 파일 내용 읽기
    contents = await file.read()
    decoded = contents.decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))

    # 각 row 처리
    for row in reader:
        query = text("""
            select * from tb_algorithm_recommend_similar where type = :type and product_id = :product_id
        """)
        result = await db.execute(
            query, {"type": type, "product_id": row["product_id"]}
        )
        rows = result.mappings().all()
        if len(rows) > 0:
            query = text("""
                        UPDATE tb_algorithm_recommend_similar SET
                            similar_subject_ids = :similar_subject_ids
                        WHERE type = :type AND product_id = :product_id
                        """)
        else:
            query = text("""
                        INSERT INTO tb_algorithm_recommend_similar (type, product_id, similar_subject_ids)
                        VALUES (:type, :product_id, :similar_subject_ids)
                        """)
        await db.execute(
            query,
            {
                "type": type,
                "product_id": row["product_id"],
                "similar_subject_ids": row["similar_subject_ids"],
            },
        )

    return {"result": True}


async def direct_recommend_list(page: int, count_per_page: int, db: AsyncSession):
    """
    직접 추천구좌 리스트 조회

    Args:
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        직접 추천구좌 리스트와 페이징 정보
    """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text("""
        SELECT COUNT(*) AS total_count FROM tb_direct_recommend
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            *
        FROM tb_direct_recommend
        ORDER BY `order` ASC, created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def direct_recommend_detail_by_id(id: int, db: AsyncSession):
    """
    직접 추천구좌 상세 조회 (ID 기준)

    Args:
        id: 조회할 직접 추천구좌 ID
        db: 데이터베이스 세션

    Returns:
        직접 추천구좌 상세 정보
    """

    query = text("""
        SELECT
            *
        FROM tb_direct_recommend
        WHERE id = :id
    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_RECOMMEND_SLOT)

    return dict(rows[0])


async def post_direct_recommend(
    req_body: admin_schema.PostDirectRecommendReqBody, db: AsyncSession
):
    """
    직접 추천구좌 등록

    Args:
        req_body: 등록할 직접 추천구좌 정보
        db: 데이터베이스 세션

    Returns:
        직접 추천구좌 등록 결과
    """

    if req_body is not None:
        logger.info(f"direct_recommend: {req_body}")

    exposure_start_date = datetime.strptime(req_body.exposure_start_date, "%Y-%m-%d")
    exposure_end_date = datetime.strptime(req_body.exposure_end_date, "%Y-%m-%d")
    if exposure_start_date > exposure_end_date:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_RECOMMEND_EXPOSE_START_DATE,
        )

    exposure_start_time_weekday = datetime.strptime(
        req_body.exposure_start_time_weekday, "%H:%M"
    )
    exposure_end_time_weekday = datetime.strptime(
        req_body.exposure_end_time_weekday, "%H:%M"
    )
    if exposure_start_time_weekday >= exposure_end_time_weekday:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_TIME_RANGE_WEEKDAY,
        )

    exposure_start_time_weekend = datetime.strptime(
        req_body.exposure_start_time_weekend, "%H:%M"
    )
    exposure_end_time_weekend = datetime.strptime(
        req_body.exposure_end_time_weekend, "%H:%M"
    )
    if exposure_start_time_weekend >= exposure_end_time_weekend:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_TIME_RANGE_WEEKEND,
        )

    columns, values, params = build_insert_query(
        req_body,
        required_fields=[
            "name",
            "order",
            "product_ids",
            "exposure_start_date",
            "exposure_end_date",
            "exposure_start_time_weekday",
            "exposure_end_time_weekday",
            "exposure_start_time_weekend",
            "exposure_end_time_weekend",
        ],
        field_mapping={"order": "`order`"},
        field_transforms={"product_ids": json.dumps},
    )

    query = text(
        f"INSERT INTO tb_direct_recommend (id, {columns}, created_id, created_date) VALUES (default, {values}, :created_id, :created_date)"
    )

    await db.execute(query, params)

    return {"result": req_body}


async def put_direct_recommend(
    id: int, req_body: admin_schema.PutDirectRecommendReqBody, db: AsyncSession
):
    """
    직접 추천구좌 수정

    Args:
        id: 수정할 직접 추천구좌 ID
        req_body: 수정할 직접 추천구좌 정보
        db: 데이터베이스 세션

    Returns:
        직접 추천구좌 수정 결과
    """

    if req_body is not None:
        logger.info(f"put_direct_recommend: {req_body}")

    query = text("""
                    SELECT * FROM tb_direct_recommend WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_RECOMMEND_SLOT)

    org_direct_recommend = dict(rows[0])

    if (
        req_body.exposure_start_date is not None
        or req_body.exposure_end_date is not None
    ):
        exposure_start_date = (
            datetime.strptime(req_body.exposure_start_date, "%Y-%m-%d")
            if req_body.exposure_start_date is not None
            else org_direct_recommend.get("exposure_start_date")
        )
        exposure_end_date = (
            datetime.strptime(req_body.exposure_end_date, "%Y-%m-%d")
            if req_body.exposure_end_date is not None
            else org_direct_recommend.get("exposure_end_date")
        )
        if exposure_start_date > exposure_end_date:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.INVALID_RECOMMEND_EXPOSE_START_DATE,
            )

    if (
        req_body.exposure_start_time_weekday is not None
        or req_body.exposure_end_time_weekday is not None
    ):
        exposure_start_time_weekday = (
            datetime.strptime(req_body.exposure_start_time_weekday, "%H:%M")
            if req_body.exposure_start_time_weekday is not None
            else datetime.strptime(
                org_direct_recommend.get("exposure_start_time_weekday"), "%H:%M"
            )
        )
        exposure_end_time_weekday = (
            datetime.strptime(req_body.exposure_end_time_weekday, "%H:%M")
            if req_body.exposure_end_time_weekday is not None
            else datetime.strptime(
                org_direct_recommend.get("exposure_end_time_weekday"), "%H:%M"
            )
        )
        if exposure_start_time_weekday >= exposure_end_time_weekday:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.INVALID_TIME_RANGE_WEEKDAY,
            )

    if (
        req_body.exposure_start_time_weekend is not None
        or req_body.exposure_end_time_weekend is not None
    ):
        exposure_start_time_weekend = (
            datetime.strptime(req_body.exposure_start_time_weekend, "%H:%M")
            if req_body.exposure_start_time_weekend is not None
            else datetime.strptime(
                org_direct_recommend.get("exposure_start_time_weekend"), "%H:%M"
            )
        )
        exposure_end_time_weekend = (
            datetime.strptime(req_body.exposure_end_time_weekend, "%H:%M")
            if req_body.exposure_end_time_weekend is not None
            else datetime.strptime(
                org_direct_recommend.get("exposure_end_time_weekend"), "%H:%M"
            )
        )
        if exposure_start_time_weekend >= exposure_end_time_weekend:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.INVALID_TIME_RANGE_WEEKEND,
            )

    set_clause, params = build_update_query(
        req_body,
        allowed_fields=[
            "name",
            "order",
            "product_ids",
            "exposure_start_date",
            "exposure_end_date",
            "exposure_start_time_weekday",
            "exposure_end_time_weekday",
            "exposure_start_time_weekend",
            "exposure_end_time_weekend",
        ],
        field_mapping={"order": "`order`"},
        field_transforms={"product_ids": json.dumps},
    )
    params["id"] = id

    query = text(f"UPDATE tb_direct_recommend SET {set_clause} WHERE id = :id")

    await db.execute(query, params)

    return {"result": req_body}


async def delete_direct_recommend(id: int, db: AsyncSession):
    """
    직접 추천구좌 삭제

    Args:
        id: 삭제할 직접 추천구좌 ID
        db: 데이터베이스 세션

    Returns:
        직접 추천구좌 삭제 결과
    """

    query = text("""
                    SELECT * FROM tb_direct_recommend WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_RECOMMEND_SLOT)

    query = text("""
                    delete from tb_direct_recommend where id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}
