from fastapi import status
from datetime import datetime

from app.exceptions import CustomResponseException
from app.const import CommonConstants, ErrorMessages

"""
DB 쿼리 빌더 관련 유틸 함수 모음
"""


def get_limit_offset_str(page: int, count_per_page: int) -> str:
    """
    페이징을 위한 LIMIT OFFSET 문자열 생성

    Args:
        page: 페이지 번호 (1부터 시작)
        count_per_page: 페이지당 개수

    Returns:
        LIMIT OFFSET 문자열 또는 빈 문자열
    """
    if page == -1 or count_per_page == -1:
        return ""
    if page < 1:
        page = 1
    offset = (page - 1) * count_per_page
    return f"LIMIT {count_per_page} OFFSET {offset}"


def get_pagination_params(page: int, count_per_page: int) -> tuple[str, dict]:
    """
    페이징을 위한 파라미터 바인딩 생성 (SQL injection 방지)

    Args:
        page: 페이지 번호 (1부터 시작)
        count_per_page: 페이지당 개수

    Returns:
        tuple: (limit_clause, parameters_dict)
    """
    if page == -1 or count_per_page == -1:
        return "", {}
    if page < 1:
        page = 1
    offset = (page - 1) * count_per_page
    return "LIMIT :limit_count OFFSET :offset_count", {
        "limit_count": count_per_page,
        "offset_count": offset,
    }


def get_file_path_sub_query(
    file_group_id_column: str, return_name: str, group_type: str = None
) -> str:
    """
    file_group_id 컬럼을 기준으로 파일 경로를 조회하는 서브쿼리 생성

    Args:
        file_group_id_column: 파일 그룹 ID 컬럼명
        return_name: 반환할 컬럼명
        group_type: 파일 그룹 타입 (예: 'user', 'cover' 등). None이면 조건 없음

    Returns:
        서브쿼리 문자열
    """
    group_type_condition = f"AND q.group_type = '{group_type}'" if group_type else ""
    return f"""IF({file_group_id_column} IS NULL, NULL, (SELECT w.file_path FROM tb_common_file q, tb_common_file_item w
        WHERE q.file_group_id = w.file_group_id AND q.use_yn = 'Y' AND w.use_yn = 'Y' {group_type_condition} AND q.file_group_id = {file_group_id_column})) AS {return_name}"""


def get_file_name_sub_query(file_group_id_column: str, return_name: str) -> str:
    """
    file_group_id 컬럼을 기준으로 파일 원본명을 조회하는 서브쿼리 생성

    Args:
        file_group_id_column: 파일 그룹 ID 컬럼명
        return_name: 반환할 컬럼명

    Returns:
        서브쿼리 문자열
    """
    return f"""IF({file_group_id_column} IS NULL, NULL, (SELECT w.file_org_name FROM tb_common_file q, tb_common_file_item w
        WHERE q.file_group_id = w.file_group_id AND q.use_yn = 'Y' AND w.use_yn = 'Y' AND q.file_group_id = {file_group_id_column})) AS {return_name}"""


def get_nickname_sub_query(user_id_column: str, return_name: str = "nickname") -> str:
    """
    사용자의 기본 닉네임을 조회하는 서브쿼리 생성

    Args:
        user_id_column: 사용자 ID 컬럼명 (예: 'u.user_id', 'log.user_id')
        return_name: 반환할 컬럼명 (기본값: 'nickname')

    Returns:
        서브쿼리 문자열
    """
    return f"""(SELECT nickname FROM tb_user_profile WHERE user_id = {user_id_column} ORDER BY default_yn DESC, profile_id ASC LIMIT 1) AS {return_name}"""


def get_nickname_or_fallback_sub_query(
    user_id_column: str, fallback_column: str, return_name: str = "user_name"
) -> str:
    """
    사용자 닉네임이 있으면 닉네임을, 없으면 fallback 컬럼 값을 반환하는 서브쿼리 생성

    Args:
        user_id_column: 사용자 ID 컬럼명 (예: 'u.user_id')
        fallback_column: 프로필이 없을 때 사용할 컬럼명 (예: 'u.user_name', 'NULL')
        return_name: 반환할 컬럼명 (기본값: 'user_name')

    Returns:
        IF 조건문이 포함된 서브쿼리 문자열
    """
    return f"""IF(
                (SELECT COUNT(*) FROM tb_user_profile WHERE user_id = {user_id_column}) = 0,
                {fallback_column},
                (SELECT nickname FROM tb_user_profile WHERE user_id = {user_id_column} ORDER BY default_yn DESC, profile_id ASC LIMIT 1)
            ) AS {return_name}"""


def get_badge_image_sub_query(
    user_id_column: str,
    badge_type: str,
    return_name: str,
    profile_id_column: str = None,
) -> str:
    """
    사용자 배지 이미지 경로를 조회하는 서브쿼리 생성

    Args:
        user_id_column: 사용자 ID 컬럼명 (예: 'a.user_id', 'pr.user_id')
        badge_type: 배지 타입 ('interest', 'event' 등)
        return_name: 반환할 컬럼명
        profile_id_column: 프로필 ID 컬럼명 (선택사항, 예: 'up.profile_id')

    Returns:
        서브쿼리 문자열
    """
    profile_condition = (
        f"AND x.profile_id = {profile_id_column}" if profile_id_column else ""
    )
    return f"""(SELECT y.file_path
        FROM tb_common_file z, tb_common_file_item y, tb_user_badge x
        WHERE z.file_group_id = y.file_group_id
        AND z.use_yn = 'Y' AND y.use_yn = 'Y'
        AND z.group_type = 'badge'
        AND x.badge_image_id = z.file_group_id
        AND x.badge_type = '{badge_type}'
        AND x.use_yn = 'Y' AND x.display_yn = 'Y'
        AND x.user_id = {user_id_column} {profile_condition} LIMIT 1) AS {return_name}"""


def build_search_where_clause(
    search_word: str,
    search_target: str,
    search_start_date: str = "",
    search_end_date: str = "",
    table_prefix: str = "",
    search_type: str = "admin",
) -> tuple[str, dict]:
    """
    검색 조건에 따른 WHERE 절을 구성하는 공통 함수 (SQL injection 방지)

    Args:
        search_word: 검색어
        search_target: 검색 대상 ('product-title', 'writer-name', 'product-id', 'author-name', 'email', 'user-name')
        search_start_date: 검색 시작 날짜
        search_end_date: 검색 종료 날짜
        table_prefix: 테이블 prefix (예: 'main', 's', 'a' 등)
        search_type: 검색 타입 ('admin' 또는 'partner')

    Returns:
        tuple: (where_clause, parameters_dict)
    """
    where = ""
    params = {}
    prefix = f"{table_prefix}." if table_prefix else ""

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            if search_type == CommonConstants.SEARCH_TYPE_ADMIN:
                where = f"""
                             AND {prefix if prefix else "main."}product_id IN (SELECT product_id FROM tb_product WHERE title LIKE :search_word)
                             """
            else:  # partner
                where += f"""
                              AND {prefix}title LIKE :search_word
                              """
            params["search_word"] = f"%{search_word}%"

        elif search_target == CommonConstants.SEARCH_WRITER_NAME:
            if search_type == CommonConstants.SEARCH_TYPE_ADMIN:
                where = f"""
                             AND {prefix if prefix else "main."}user_id IN (SELECT user_id FROM tb_user_profile WHERE nickname LIKE :search_word)
                             """
            params["search_word"] = f"%{search_word}%"

        elif search_target == CommonConstants.SEARCH_PRODUCT_ID:
            if not search_word.isdigit():
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.SEARCH_WORD_MUST_BE_NUMBER,
                )
            where += f"""
                          AND {prefix}product_id = :product_id
                          """
            params["product_id"] = int(search_word)

        elif search_target == CommonConstants.SEARCH_AUTHOR_NAME:
            where += f"""
                          AND {prefix}author_name LIKE :search_word
                          """
            params["search_word"] = f"%{search_word}%"

        elif search_target == CommonConstants.SEARCH_EMAIL:
            where += f"""
                          AND {prefix}email LIKE :search_word
                          """
            params["search_word"] = f"%{search_word}%"

        elif search_target == CommonConstants.SEARCH_USER_NAME:
            where += f"""
                          AND {prefix}user_name LIKE :search_word
                          """
            params["search_word"] = f"%{search_word}%"

    if search_start_date != "":
        date_column = f"{prefix}created_date" if prefix else "main.created_date"
        where += f"""
                      AND DATE({date_column}) >= :search_start_date
                      """
        params["search_start_date"] = search_start_date

    if search_end_date != "":
        date_column = f"{prefix}created_date" if prefix else "main.created_date"
        where += f"""
                      AND DATE({date_column}) <= :search_end_date
                      """
        params["search_end_date"] = search_end_date

    return where, params


def get_user_block_filter(
    user_id_column: str = "a.user_id",
    comment_id_column: str = None,
) -> str:
    """
    차단된 사용자를 필터링하는 NOT EXISTS 서브쿼리 생성

    Args:
        user_id_column: 사용자 ID 컬럼명 (예: 'a.user_id')
        comment_id_column: 댓글 ID 컬럼명 (선택사항, 예: 'a.comment_id')

    Returns:
        NOT EXISTS 서브쿼리 문자열
    """
    comment_condition = (
        f"AND {comment_id_column} = t.comment_id " if comment_id_column else ""
    )
    return f"""AND NOT EXISTS (SELECT 1 FROM tb_user_block t
                WHERE t.user_id = :user_id
                {comment_condition}AND {user_id_column} = t.off_user_id
                AND t.off_yn = 'Y'
                AND t.use_yn = 'Y')"""


def build_role_where_clause(
    user_data: dict,
    author_id_column: str = "p.author_id",
    product_id_column: str = "p.product_id",
) -> str:
    """
    사용자 역할에 따른 권한 체크 WHERE 절을 생성하는 함수

    Args:
        user_data: 사용자 정보 딕셔너리 (user_id, role 포함)
        author_id_column: 작가 ID 컬럼명 (예: 'p.author_id', 'author_id')
        product_id_column: 작품 ID 컬럼명 (예: 'p.product_id', 'product_id')

    Returns:
        WHERE 절 문자열
    """
    if user_data["role"] == "author":
        return f"""
            AND {author_id_column} = {user_data["user_id"]}
        """
    elif user_data["role"] == "partner":
        return f"""
            AND {product_id_column} IN (
                SELECT z.product_id
                FROM tb_product_contract_offer z
                INNER JOIN tb_user_profile_apply y ON z.offer_user_id = y.user_id
                AND y.apply_type = 'cp'
                AND y.approval_date IS NOT NULL
                WHERE z.use_yn = 'Y'
                AND z.author_accept_yn = 'Y'
                AND y.user_id = {user_data["user_id"]}
            )
        """
    return ""


def build_update_query(
    req_body,
    allowed_fields: list[str],
    field_mapping: dict[str, str] = None,
    field_transforms: dict[str, callable] = None,
) -> tuple[str, dict]:
    """
    동적 UPDATE 쿼리의 SET 절과 파라미터를 생성하는 함수

    Args:
        req_body: 요청 바디 객체 (Pydantic 모델 또는 일반 객체)
        allowed_fields: 업데이트 허용 필드 목록
        field_mapping: 필드명 매핑 (req_field -> db_column), None이면 동일한 이름 사용
        field_transforms: 필드별 변환 함수 (req_field -> transform_func), 예: {"ids": json.dumps}

    Returns:
        tuple: (SET 절 문자열, 파라미터 딕셔너리)

    사용 예시:
        set_clause, params = build_update_query(
            req_body,
            allowed_fields=["product_id", "episode_id", "product_ids"],
            field_transforms={"product_ids": json.dumps}
        )
        params["id"] = id
        query = text(f"UPDATE table_name SET {set_clause} WHERE id = :id")
        await db.execute(query, params)
    """
    update_fields = ["updated_id = :updated_id", "updated_date = :updated_date"]
    params = {"updated_id": -1, "updated_date": datetime.now()}

    for field_name in allowed_fields:
        value = getattr(req_body, field_name, None)
        if value is not None:
            db_column = (
                field_mapping.get(field_name, field_name)
                if field_mapping
                else field_name
            )
            if field_transforms and field_name in field_transforms:
                value = field_transforms[field_name](value)
            update_fields.append(f"{db_column} = :{field_name}")
            params[field_name] = value

    return ", ".join(update_fields), params


def build_insert_query(
    req_body,
    required_fields: list[str] = None,
    optional_fields: list[str] = None,
    field_mapping: dict[str, str] = None,
    field_transforms: dict[str, callable] = None,
    field_defaults: dict[str, any] = None,
) -> tuple[str, str, dict]:
    """
    동적 INSERT 쿼리의 columns, values 절과 파라미터를 생성하는 함수

    Args:
        req_body: 요청 바디 객체
        required_fields: 필수 필드 목록 (항상 포함, None 값도 포함)
        optional_fields: 선택적 필드 목록 (값이 있을 때만 포함, 또는 기본값 사용)
        field_mapping: 필드명 매핑 (req_field -> db_column), 예: {"order": "`order`"}
        field_transforms: 필드별 변환 함수 (예: {"ids": json.dumps})
        field_defaults: 필드별 기본값 (값이 None일 때 사용)

    Returns:
        tuple: (columns_clause, values_clause, parameters_dict)

    사용 예시:
        columns, values, params = build_insert_query(
            req_body,
            required_fields=["product_id", "user_id"],
            optional_fields=["title", "use_yn"],
            field_defaults={"use_yn": "Y"}
        )
        query = text(f"INSERT INTO table_name (id, {columns}, created_id, created_date) VALUES (default, {values}, :created_id, :created_date)")
        await db.execute(query, params)
    """
    columns = []
    values = []
    params = {"created_id": -1, "created_date": datetime.now()}

    # 필수 필드 처리 (항상 포함)
    if required_fields:
        for field_name in required_fields:
            value = getattr(req_body, field_name, None)
            # 값이 None이고 기본값이 있으면 기본값 사용
            if value is None and field_defaults and field_name in field_defaults:
                value = field_defaults[field_name]
            if field_transforms and field_name in field_transforms:
                value = field_transforms[field_name](value)
            db_column = (
                field_mapping.get(field_name, field_name)
                if field_mapping
                else field_name
            )
            columns.append(db_column)
            values.append(f":{field_name}")
            params[field_name] = value

    # 선택적 필드 처리 (값이 있거나 기본값이 있을 때만 포함)
    if optional_fields:
        for field_name in optional_fields:
            value = getattr(req_body, field_name, None)
            if value is not None:
                if field_transforms and field_name in field_transforms:
                    value = field_transforms[field_name](value)
                db_column = (
                    field_mapping.get(field_name, field_name)
                    if field_mapping
                    else field_name
                )
                columns.append(db_column)
                values.append(f":{field_name}")
                params[field_name] = value
            elif field_defaults and field_name in field_defaults:
                db_column = (
                    field_mapping.get(field_name, field_name)
                    if field_mapping
                    else field_name
                )
                columns.append(db_column)
                values.append(f":{field_name}")
                params[field_name] = field_defaults[field_name]

    return ", ".join(columns), ", ".join(values), params
