from fastapi import status

from app.exceptions import CustomResponseException

"""
응답 빌더 관련 유틸 함수 모음
"""


def build_list_response(rows, total_items: int = None) -> dict:
    """
    리스트 조회 결과를 응답 형식으로 변환하는 함수

    Args:
        rows: 데이터베이스 조회 결과 (mappings().all() 결과)
        total_items: 전체 아이템 수 (페이징 시 사용, None이면 포함 안함)

    Returns:
        dict: {"data": [...], "totalItems": N} 형식의 응답

    사용 예시:
        rows = result.mappings().all()
        return build_list_response(rows)
        return build_list_response(rows, total_items=100)
    """
    res_body = {"data": [dict(row) for row in rows]}
    if total_items is not None:
        res_body["totalItems"] = total_items
    return res_body


def build_detail_response(row) -> dict:
    """
    상세 조회 결과를 응답 형식으로 변환하는 함수

    Args:
        row: 데이터베이스 조회 결과 (mappings().one_or_none() 결과)

    Returns:
        dict: {"data": {...} 또는 None} 형식의 응답

    사용 예시:
        row = result.mappings().one_or_none()
        return build_detail_response(row)
    """
    return {"data": dict(row) if row is not None else None}


def build_paginated_response(
    rows, total_count: int, page: int, count_per_page: int
) -> dict:
    """
    페이징된 리스트 조회 결과를 응답 형식으로 변환하는 함수 (admin/partner용)

    Args:
        rows: 데이터베이스 조회 결과 (mappings().all() 결과)
        total_count: 전체 아이템 수
        page: 현재 페이지 번호
        count_per_page: 페이지당 아이템 수

    Returns:
        dict: {"total_count": N, "page": N, "count_per_page": N, "results": [...]} 형식의 응답

    사용 예시:
        rows = result.mappings().all()
        return build_paginated_response(rows, total_count, page, count_per_page)
    """
    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "results": [dict(row) for row in rows],
    }


def get_row_or_404(result, error_message: str):
    """
    쿼리 결과에서 첫 번째 row를 반환하거나 없으면 404 예외를 발생시키는 함수

    Args:
        result: db.execute() 결과
        error_message: 404 에러 시 표시할 메시지 (ErrorMessages.XXX)

    Returns:
        RowMapping: 첫 번째 row

    Raises:
        CustomResponseException: row가 없으면 404 Not Found 예외 발생

    사용 예시:
        result = await db.execute(query, {"id": id})
        row = get_row_or_404(result, ErrorMessages.NOT_FOUND_PRODUCT)
    """
    row = result.mappings().one_or_none()
    if row is None:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=error_message,
        )
    return row


def check_exists_or_404(rows, error_message: str):
    """
    rows 리스트가 비어있으면 404 예외를 발생시키는 함수

    Args:
        rows: mappings().all() 결과 리스트
        error_message: 404 에러 시 표시할 메시지 (ErrorMessages.XXX)

    Raises:
        CustomResponseException: rows가 비어있으면 404 Not Found 예외 발생

    사용 예시:
        rows = result.mappings().all()
        check_exists_or_404(rows, ErrorMessages.NOT_FOUND_PRODUCT)
        product = dict(rows[0])
    """
    if len(rows) == 0:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=error_message,
        )
