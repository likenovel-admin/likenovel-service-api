import csv
import io
import json
import logging
from fastapi import status
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.exceptions import CustomResponseException
import app.schemas.admin as admin_schema

from app.utils.query import (
    build_insert_query,
    build_update_query,
    get_file_name_sub_query,
    get_file_path_sub_query,
    get_pagination_params,
)
from app.utils.response import build_paginated_response, check_exists_or_404
from app.const import CommonConstants

from urllib.parse import quote
from app.const import ErrorMessages

logger = logging.getLogger("admin_app")  # 커스텀 로거 생성

"""
관리자 이벤트/배너 관리 서비스 함수 모음
"""


async def events_list(type: str, page: int, count_per_page: int, db: AsyncSession):
    """
    이벤트 목록 조회

    Args:
        type: 이벤트 종류 (all, view-3-times, add-comment, add-product, etc)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        이벤트 목록과 페이징 정보
    """

    if type != "all":
        where = text(f"""
                     AND `type` = '{type}'
                     """)
    else:
        where = text("""""")

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        SELECT COUNT(*) AS total_count FROM tb_event_v2 WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            *,
            '' AS link,
            (SELECT p.title FROM tb_product p WHERE FIND_IN_SET(
                p.product_id,
                REPLACE(REPLACE(REPLACE(e.product_ids, '[', ''), ']', ''), ' ', '')
            ) LIMIT 1) AS product_title,
            CASE
                WHEN CURRENT_TIMESTAMP < start_date THEN 'before-start'
                WHEN end_date < CURRENT_TIMESTAMP THEN 'after-end'
                ELSE 'ing'
            END AS status,
            CASE
                WHEN show_yn_thumbnail_img = 'Y' AND show_yn_detail_img = 'Y' AND show_yn_product = 'Y' AND show_yn_information = 'Y' THEN 'Y'
                ELSE 'N'
            END AS `show`
        FROM tb_event_v2 e
        WHERE 1=1 {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def event_detail_by_id(id: int, db: AsyncSession):
    """
    이벤트 상세 조회

    Args:
        id: 조회할 이벤트 ID
        db: 데이터베이스 세션

    Returns:
        이벤트 상세 정보
    """

    query = text(f"""
        SELECT
            *,
            '' AS link,
            (SELECT p.title FROM tb_product p WHERE FIND_IN_SET(
                p.product_id,
                REPLACE(REPLACE(REPLACE(e.product_ids, '[', ''), ']', ''), ' ', '')
            ) LIMIT 1) AS product_title,
            CASE
                WHEN CURRENT_TIMESTAMP < start_date THEN 'before-start'
                WHEN end_date < CURRENT_TIMESTAMP THEN 'after-end'
                ELSE 'ing'
            END AS status,
            CASE
                WHEN show_yn_thumbnail_img = 'Y' AND show_yn_detail_img = 'Y' AND show_yn_product = 'Y' AND show_yn_information = 'Y' THEN 'Y'
                ELSE 'N'
            END AS `show`,
            {get_file_path_sub_query("e.thumbnail_image_id", "thumbnail_image_path")},
            {get_file_path_sub_query("e.detail_image_id", "detail_image_path")},
            {get_file_name_sub_query("e.thumbnail_image_id", "thumbnail_image_filename")},
            {get_file_name_sub_query("e.detail_image_id", "detail_image_filename")}
        FROM tb_event_v2 e
        WHERE id = {id}
        ORDER BY created_date DESC LIMIT 1
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_EVENT)

    return dict(rows[0])


async def event_download_recipient_by_id(id: int, db: AsyncSession):
    """
    이벤트 수령인 목록 다운로드

    Args:
        id: 조회할 이벤트 ID
        db: 데이터베이스 세션

    Returns:
        이벤트 수령인 목록 CSV 파일 스트리밍 응답
    """

    query = text("""
        SELECT
            *
        FROM tb_event_v2
        WHERE id = :id
        ORDER BY created_date DESC LIMIT 1
    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_EVENT)
    event = dict(rows[0])

    query = text("""
                 SELECT
                    user_id,
                    email,
                    gender,
                    birthdate,
                    user_name
                 FROM tb_user WHERE user_id IN (SELECT user_id FROM tb_event_v2_reward_recipient WHERE event_id = :id)
                 """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    recipients = [dict(row) for row in rows]

    if len(recipients) == 0:
        # 데이터가 없는 경우 키만 있는거 하나 추가해줘야함
        recipients = [
            {
                "user_id": "",
                "email": "",
                "gender": "",
                "birthdate": "",
                "user_name": "",
            }
        ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=recipients[0].keys())
    writer.writeheader()
    writer.writerows(recipients)

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(f'{event["title"]} 수령인 목록.csv')}"
        },
    )


async def post_event(req_body: admin_schema.PostEventReqBody, db: AsyncSession):
    """
    새로운 이벤트 등록

    Args:
        req_body: 등록할 이벤트 정보
        db: 데이터베이스 세션

    Returns:
        이벤트 등록 결과
    """

    if req_body is not None:
        logger.info(f"post_event: {req_body}")

    start_date = datetime.strptime(req_body.start_date, "%Y-%m-%d")
    end_date = datetime.strptime(req_body.end_date, "%Y-%m-%d")
    if start_date > end_date:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_RECOMMEND_EXPOSE_START_DATE,
        )

    if req_body.type not in ["view-3-times", "add-comment", "add-product", "etc"]:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.NOT_ALLOWED_TYPE.format(req_body.type),
        )

    if req_body.reward_type is not None and req_body.reward_type not in [
        "ticket",
        "cash",
    ]:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.NOT_ALLOWED_REWARD_TYPE.format(req_body.reward_type),
        )

    columns, values, params = build_insert_query(
        req_body,
        required_fields=[
            "title",
            "start_date",
            "end_date",
            "type",
            "show_yn_thumbnail_img",
            "show_yn_detail_img",
            "show_yn_product",
            "show_yn_information",
            "thumbnail_image_id",
            "detail_image_id",
            "account_name",
            "product_ids",
            "information",
        ],
        optional_fields=[
            "target_product_ids",
            "reward_type",
            "reward_amount",
            "reward_max_people",
        ],
        field_transforms={"target_product_ids": json.dumps, "product_ids": json.dumps},
    )

    query = text(
        f"INSERT INTO tb_event_v2 (id, {columns}, created_id, created_date) VALUES (default, {values}, :created_id, :created_date)"
    )

    await db.execute(query, params)

    return {"result": req_body}


async def put_event(req_body: admin_schema.PutEventReqBody, id: int, db: AsyncSession):
    """
    이벤트 수정

    Args:
        req_body: 수정할 이벤트 정보
        id: 수정할 이벤트 ID
        db: 데이터베이스 세션

    Returns:
        이벤트 수정 결과
    """

    query = text("""
                    SELECT * FROM tb_event_v2 WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_EVENT)

    org_event = dict(rows[0])

    if req_body.start_date is not None or req_body.end_date is not None:
        start_date = (
            datetime.strptime(req_body.start_date, "%Y-%m-%d")
            if req_body.start_date is not None
            else org_event.get("start_date")
        )
        end_date = (
            datetime.strptime(req_body.end_date, "%Y-%m-%d")
            if req_body.end_date is not None
            else org_event.get("end_date")
        )
        if start_date > end_date:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.INVALID_RECOMMEND_EXPOSE_START_DATE,
            )

    if req_body.type not in ["view-3-times", "add-comment", "add-product", "etc"]:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.NOT_ALLOWED_TYPE.format(req_body.type),
        )

    if req_body.reward_type is not None and req_body.reward_type not in [
        "ticket",
        "cash",
    ]:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.NOT_ALLOWED_REWARD_TYPE.format(req_body.reward_type),
        )

    set_clause, params = build_update_query(
        req_body,
        allowed_fields=[
            "title",
            "start_date",
            "end_date",
            "type",
            "target_product_ids",
            "reward_type",
            "reward_amount",
            "reward_max_people",
            "show_yn_thumbnail_img",
            "show_yn_detail_img",
            "show_yn_product",
            "show_yn_information",
            "thumbnail_image_id",
            "detail_image_id",
            "account_name",
            "product_ids",
            "information",
        ],
        field_transforms={"target_product_ids": json.dumps, "product_ids": json.dumps},
    )
    params["id"] = id

    query = text(f"""
                        update tb_event_v2 set
                        {set_clause}
                        where id = :id
                    """)

    await db.execute(query, params)

    return {"result": req_body}


async def show_event(id: int, db: AsyncSession):
    """
    이벤트 노출 ON

    Args:
        id: 노출할 이벤트 ID
        db: 데이터베이스 세션

    Returns:
        이벤트 노출 결과
    """

    update_filed_query_list = [
        "updated_id = :updated_id",
        "updated_date = :updated_date",
    ]

    db_execute_params = {"updated_id": -1, "updated_date": datetime.now(), "id": id}

    update_filed_query_list.append("show_yn_thumbnail_img = :show_yn_thumbnail_img")
    db_execute_params["show_yn_thumbnail_img"] = CommonConstants.YES

    update_filed_query_list.append("show_yn_detail_img = :show_yn_detail_img")
    db_execute_params["show_yn_detail_img"] = CommonConstants.YES

    update_filed_query_list.append("show_yn_product = :show_yn_product")
    db_execute_params["show_yn_product"] = CommonConstants.YES

    update_filed_query_list.append("show_yn_information = :show_yn_information")
    db_execute_params["show_yn_information"] = CommonConstants.YES

    update_filed_query = ",".join(update_filed_query_list)

    query = text(f"""
                        update tb_event_v2 set
                        {update_filed_query}
                        where id = :id
                    """)

    await db.execute(query, db_execute_params)

    return {"result": True}


async def hide_event(id: int, db: AsyncSession):
    """
    이벤트 노출 OFF

    Args:
        id: 노출할 이벤트 ID
        db: 데이터베이스 세션

    Returns:
        이벤트 노출 결과
    """

    update_filed_query_list = [
        "updated_id = :updated_id",
        "updated_date = :updated_date",
    ]

    db_execute_params = {"updated_id": -1, "updated_date": datetime.now(), "id": id}

    update_filed_query_list.append("show_yn_thumbnail_img = :show_yn_thumbnail_img")
    db_execute_params["show_yn_thumbnail_img"] = CommonConstants.NO

    update_filed_query_list.append("show_yn_detail_img = :show_yn_detail_img")
    db_execute_params["show_yn_detail_img"] = CommonConstants.NO

    update_filed_query_list.append("show_yn_product = :show_yn_product")
    db_execute_params["show_yn_product"] = CommonConstants.NO

    update_filed_query_list.append("show_yn_information = :show_yn_information")
    db_execute_params["show_yn_information"] = CommonConstants.NO

    update_filed_query = ",".join(update_filed_query_list)

    query = text(f"""
                        update tb_event_v2 set
                        {update_filed_query}
                        where id = :id
                    """)

    await db.execute(query, db_execute_params)

    return {"result": True}


async def delete_event(id: int, db: AsyncSession):
    """
    이벤트 삭제

    Args:
        id: 삭제할 이벤트 ID
        db: 데이터베이스 세션

    Returns:
        이벤트 삭제 결과
    """

    query = text("""
                    SELECT * FROM tb_event_v2 WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_EVENT)

    query = text("""
                    delete from tb_event_v2 where id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}


async def banners_list(page: int, count_per_page: int, db: AsyncSession):
    """
    배너 목록 조회

    Args:
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        배너 목록과 페이징 정보
    """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text("""
        SELECT COUNT(*) AS total_count FROM tb_carousel_banner
    """)
    count_result = await db.execute(count_query, {})
    total_count = dict(count_result.mappings().first())["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        SELECT
            *,
            CASE
                WHEN show_start_date < CURRENT_TIMESTAMP AND CURRENT_TIMESTAMP < show_end_date THEN 'Y'
                ELSE 'N'
            END AS `show`
        FROM tb_carousel_banner
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def banner_detail_by_id(id: int, db: AsyncSession):
    """
    배너 상세 조회

    Args:
        id: 조회할 배너 ID
        db: 데이터베이스 세션

    Returns:
        배너 상세 정보
    """

    query = text(f"""
        SELECT
            *,
            {get_file_path_sub_query("b.image_id", "image_path")},
            {get_file_name_sub_query("b.image_id", "file_name")},
            {get_file_path_sub_query("b.mobile_image_id", "mobile_image_path")},
            {get_file_name_sub_query("b.mobile_image_id", "mobile_file_name")}
        FROM tb_carousel_banner b
        WHERE id = {id}
        ORDER BY created_date DESC LIMIT 1
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_BANNER)

    return dict(rows[0])


async def post_banner(req_body: admin_schema.PostBannerReqBody, db: AsyncSession):
    """
    새로운 배너 등록

    Args:
        req_body: 등록할 배너 정보 (위치, 제목, 노출 기간 등)
        db: 데이터베이스 세션

    Returns:
        배너 등록 결과
    """

    if req_body is not None:
        logger.info(f"post_banner: {req_body}")

    show_start_date = datetime.strptime(req_body.show_start_date, "%Y-%m-%d")
    show_end_date = datetime.strptime(req_body.show_end_date, "%Y-%m-%d")
    if show_start_date > show_end_date:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_RECOMMEND_EXPOSE_START_DATE,
        )

    if req_body.position not in [
        "main",
        "paid",
        "review",
        "promotion",
        "search",
        "viewer",
    ]:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.NOT_ALLOWED_POSITION.format(req_body.position),
        )

    if req_body.position == "main":
        if req_body.division is None:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.DETAIL_POSITION_REQUIRED,
            )

        if req_body.division not in ["top", "mid", "bot"]:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.NOT_ALLOWED_POSITION.format(req_body.division),
            )

    columns, values, params = build_insert_query(
        req_body,
        required_fields=[
            "position",
            "title",
            "show_start_date",
            "show_end_date",
            "url",
            "image_id",
            "mobile_image_id",
        ],
        optional_fields=["division", "show_order"],
        field_defaults={"show_order": 1},
    )

    query = text(
        f"INSERT INTO tb_carousel_banner (id, {columns}, created_id, created_date) VALUES (default, {values}, :created_id, :created_date)"
    )

    await db.execute(query, params)

    return {"result": req_body}


async def put_banner(
    req_body: admin_schema.PutBannerReqBody, id: int, db: AsyncSession
):
    """
    배너 수정

    Args:
        req_body: 수정할 배너 정보
        id: 수정할 배너 ID
        db: 데이터베이스 세션

    Returns:
        배너 수정 결과
    """

    query = text("""
                    SELECT * FROM tb_carousel_banner WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_BANNER)

    org_banner = dict(rows[0])

    if req_body.show_start_date is not None or req_body.show_end_date is not None:
        show_start_date = (
            datetime.strptime(req_body.show_start_date, "%Y-%m-%d")
            if req_body.show_start_date is not None
            else org_banner.get("show_start_date")
        )
        show_end_date = (
            datetime.strptime(req_body.show_end_date, "%Y-%m-%d")
            if req_body.show_end_date is not None
            else org_banner.get("show_end_date")
        )
        if show_start_date > show_end_date:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.INVALID_RECOMMEND_EXPOSE_START_DATE,
            )

    if req_body.position is not None and req_body.position not in [
        "main",
        "paid",
        "review",
        "promotion",
        "search",
        "viewer",
    ]:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.NOT_ALLOWED_POSITION.format(req_body.position),
        )

    if (
        org_banner["position"] == "main" and req_body.position is None
    ) or req_body.position == "main":
        if req_body.division is None:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.DETAIL_POSITION_REQUIRED,
            )

        if req_body.division not in ["top", "mid", "bot"]:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.NOT_ALLOWED_POSITION.format(req_body.division),
            )

    update_filed_query_list = [
        "updated_id = :updated_id",
        "updated_date = :updated_date",
    ]

    db_execute_params = {"updated_id": -1, "updated_date": datetime.now(), "id": id}

    if req_body.position is not None:
        update_filed_query_list.append("position = :position")
        db_execute_params["position"] = req_body.position

    if (
        org_banner["position"] == "main" and req_body.position is None
    ) or req_body.position == "main":
        if req_body.division is not None:
            update_filed_query_list.append("division = :division")
            db_execute_params["division"] = req_body.division
    else:
        update_filed_query_list.append("division = :division")
        db_execute_params["division"] = None

    if req_body.title is not None:
        update_filed_query_list.append("title = :title")
        db_execute_params["title"] = req_body.title

    if req_body.show_start_date is not None:
        update_filed_query_list.append("show_start_date = :show_start_date")
        db_execute_params["show_start_date"] = req_body.show_start_date

    if req_body.show_end_date is not None:
        update_filed_query_list.append("show_end_date = :show_end_date")
        db_execute_params["show_end_date"] = req_body.show_end_date

    if req_body.show_order is not None:
        update_filed_query_list.append("show_order = :show_order")
        db_execute_params["show_order"] = req_body.show_order

    if req_body.url is not None:
        update_filed_query_list.append("url = :url")
        db_execute_params["url"] = req_body.url

    if req_body.image_id is not None:
        update_filed_query_list.append("image_id = :image_id")
        db_execute_params["image_id"] = req_body.image_id

    if req_body.mobile_image_id is not None:
        update_filed_query_list.append("mobile_image_id = :mobile_image_id")
        db_execute_params["mobile_image_id"] = req_body.mobile_image_id

    update_filed_query = ",".join(update_filed_query_list)

    query = text(f"""
                        update tb_carousel_banner set
                        {update_filed_query}
                        where id = :id
                    """)

    await db.execute(query, db_execute_params)

    return {"result": req_body}


async def delete_banner(id: int, db: AsyncSession):
    """
    배너 삭제

    Args:
        id: 삭제할 배너 ID
        db: 데이터베이스 세션

    Returns:
        배너 삭제 결과
    """

    query = text("""
                    SELECT * FROM tb_carousel_banner WHERE id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_BANNER)

    query = text("""
                    delete from tb_carousel_banner where id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}


async def get_current_popup_data(db: AsyncSession):
    """
    현재 팝업 데이터 조회 (없으면 기본값 생성 후 반환)

    Args:
        db: 데이터베이스 세션

    Returns:
        현재 팝업 데이터
    """

    query = text(f"""
        SELECT
            *,
            {get_file_path_sub_query("p.image_id", "image_path")},
            {get_file_name_sub_query("p.image_id", "image_filename")}
        FROM tb_comm_popup p
        WHERE title = 'default-popup'
        ORDER BY created_date ASC LIMIT 1
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    if len(rows) == 0:
        query = text("""
                     INSERT INTO tb_comm_popup (id, title, content, image_id, start_date, end_date, use_yn, created_id, created_date)
                     VALUES (DEFAULT, 'default-popup', '', NULL, '1970-01-01', '9999-12-31', 'Y', -1, CURRENT_TIMESTAMP)
                     """)
        await db.execute(query, {})
        query = text(f"""
            SELECT
                *,
                {get_file_path_sub_query("p.image_id", "image_path")},
                {get_file_name_sub_query("p.image_id", "image_filename")}
            FROM tb_comm_popup p
            WHERE title = 'default-popup'
            ORDER BY created_date ASC LIMIT 1
        """)
        result = await db.execute(query, {})
        rows = result.mappings().all()

    return dict(rows[0])


async def put_popup(req_body: admin_schema.PutPopupReqBody, db: AsyncSession):
    """
    팝업 수정

    Args:
        req_body: 수정할 팝업 정보
        db: 데이터베이스 세션

    Returns:
        팝업 수정 결과
    """

    popup = await get_current_popup_data(db)

    set_clause, params = build_update_query(
        req_body, allowed_fields=["use_yn", "url", "image_id"]
    )
    params["id"] = popup["id"]

    query = text(f"UPDATE tb_comm_popup SET {set_clause} WHERE id = :id")

    await db.execute(query, params)

    return {"result": await get_current_popup_data(db)}
