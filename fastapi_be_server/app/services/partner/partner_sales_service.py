import logging
import re
from decimal import Decimal, ROUND_HALF_UP
from fastapi import status
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime

from app.exceptions import CustomResponseException
import app.schemas.partner as partner_schema
from app.utils.query import (
    get_pagination_params,
    build_search_where_clause,
)
from app.utils.response import build_paginated_response, check_exists_or_404
from app.const import CommonConstants
from app.const import ErrorMessages

logger = logging.getLogger("partner_app")  # 커스텀 로거 생성

PRODUCT_WEB_FEE_RATE = Decimal("0")
PRODUCT_PLATFORM_SERVICE_RATE = Decimal("30")
PRODUCT_COMPED_FEE_RATE = Decimal("0")
GLOBAL_PLATFORM_SERVICE_SCOPE = "global"
PRODUCT_PLATFORM_SERVICE_SCOPE = "product"
GLOBAL_PLATFORM_SERVICE_PRODUCT_ID = 0

"""
partner 파트너 매출/정산 관련 서비스 함수 모음
"""


def _normalize_episode_title(title):
    if title is None:
        return None
    return re.sub(r"\.epub$", "", str(title).strip(), flags=re.IGNORECASE)


def _cp_owned_product_ids_subquery(user_id: int) -> str:
    return f"""
        SELECT product_id
        FROM tb_product
        WHERE cp_user_id = {user_id}
           OR user_id = {user_id}
    """


def _cp_company_name_product_ids_subquery(search_word: str) -> str:
    return f"""
        SELECT p.product_id
        FROM tb_product p
        INNER JOIN tb_user_profile_apply y ON p.cp_user_id = y.user_id
            AND y.apply_type = 'cp'
            AND y.approval_code = 'accepted'
            AND y.approval_date IS NOT NULL
        WHERE y.company_name LIKE '%{search_word}%'
    """


def _cp_company_name_lookup_subquery(product_id_column: str) -> str:
    return f"""
        (
            SELECT y.company_name
            FROM tb_product p
            INNER JOIN tb_user_profile_apply y ON p.cp_user_id = y.user_id
                AND y.apply_type = 'cp'
                AND y.approval_code = 'accepted'
                AND y.approval_date IS NOT NULL
            WHERE p.product_id = {product_id_column}
            LIMIT 1
        )
    """


async def _get_cp_metadata_map_by_product_ids(
    product_ids: list[int], db: AsyncSession
) -> dict[int, dict[str, str | None]]:
    normalized_product_ids = sorted(
        {product_id for product_id in product_ids if product_id is not None}
    )
    if not normalized_product_ids:
        return {}

    query = (
        text(
            """
            WITH ranked_cp_summary AS (
                SELECT ranked.user_id,
                       ranked.company_name
                  FROM (
                        SELECT user_id,
                               company_name,
                               ROW_NUMBER() OVER (
                                   PARTITION BY user_id
                                   ORDER BY approval_date DESC, id DESC
                               ) AS rn
                          FROM tb_user_profile_apply
                         WHERE apply_type = 'cp'
                           AND approval_code = 'accepted'
                           AND approval_date IS NOT NULL
                  ) ranked
                 WHERE ranked.rn = 1
            )
            SELECT p.product_id,
                   cp.company_name AS cp_company_name
              FROM tb_product p
              LEFT JOIN ranked_cp_summary cp ON p.cp_user_id = cp.user_id
             WHERE p.product_id IN :product_ids
            """
        ).bindparams(bindparam("product_ids", expanding=True))
    )
    result = await db.execute(query, {"product_ids": normalized_product_ids})
    metadata_map: dict[int, dict[str, str | None]] = {}
    for row in result.mappings().all():
        cp_company_name = row.get("cp_company_name")
        if cp_company_name is None:
            contract_type = None
        elif cp_company_name == CommonConstants.COMPANY_LIKENOVEL:
            contract_type = "일반"
        else:
            contract_type = "cp"
        metadata_map[row["product_id"]] = {
            "cp_company_name": cp_company_name,
            "contract_type": contract_type,
        }
    return metadata_map


def _to_decimal(value) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal("0")


def _to_int(decimal_value: Decimal) -> int:
    return int(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _calculate_channel_payout(gross_sales: Decimal, fee: Decimal, payout_rate: Decimal) -> Decimal:
    if gross_sales <= 0:
        return Decimal("0")
    return max(
        Decimal("0"),
        (gross_sales - fee) * (payout_rate / Decimal("100")),
    )


def _calculate_product_sales_totals(data: dict) -> dict[str, Decimal]:
    gross_sales_web = (
        _to_decimal(data.get("sum_normal_price_web"))
        + _to_decimal(data.get("sum_ticket_price_web"))
        - _to_decimal(data.get("sum_refund_price_web"))
    )
    gross_sales_playstore = (
        _to_decimal(data.get("sum_normal_price_playstore"))
        + _to_decimal(data.get("sum_ticket_price_playstore"))
        - _to_decimal(data.get("sum_refund_price_playstore"))
    )
    gross_sales_ios = (
        _to_decimal(data.get("sum_normal_price_ios"))
        + _to_decimal(data.get("sum_ticket_price_ios"))
        - _to_decimal(data.get("sum_refund_price_ios"))
    )
    gross_sales_onestore = (
        _to_decimal(data.get("sum_normal_price_onestore"))
        + _to_decimal(data.get("sum_ticket_price_onestore"))
        - _to_decimal(data.get("sum_refund_price_onestore"))
    )
    gross_comped_ticket = _to_decimal(data.get("sum_comped_ticket_price")) - _to_decimal(
        data.get("sum_refund_comped_ticket_price")
    )

    fee_web = _to_decimal(data.get("fee_web")) if gross_sales_web > 0 else Decimal("0")
    fee_playstore = (
        _to_decimal(data.get("fee_playstore"))
        if gross_sales_playstore > 0
        else Decimal("0")
    )
    fee_ios = _to_decimal(data.get("fee_ios")) if gross_sales_ios > 0 else Decimal("0")
    fee_onestore = (
        _to_decimal(data.get("fee_onestore"))
        if gross_sales_onestore > 0
        else Decimal("0")
    )
    fee_comped_ticket = (
        _to_decimal(data.get("fee_comped_ticket"))
        if gross_comped_ticket > 0
        else Decimal("0")
    )

    paid_price_web = _calculate_channel_payout(
        gross_sales_web,
        fee_web,
        _to_decimal(data.get("settlement_rate_web")),
    )
    paid_price_playstore = _calculate_channel_payout(
        gross_sales_playstore,
        fee_playstore,
        _to_decimal(data.get("settlement_rate_playstore")),
    )
    paid_price_ios = _calculate_channel_payout(
        gross_sales_ios,
        fee_ios,
        _to_decimal(data.get("settlement_rate_ios")),
    )
    paid_price_onestore = _calculate_channel_payout(
        gross_sales_onestore,
        fee_onestore,
        _to_decimal(data.get("settlement_rate_onestore")),
    )
    free_price = _calculate_channel_payout(
        gross_comped_ticket,
        fee_comped_ticket,
        _to_decimal(data.get("settlement_rate_comped_ticket")),
    )

    paid_price = (
        paid_price_web
        + paid_price_playstore
        + paid_price_ios
        + paid_price_onestore
    )
    gross_paid_price = (
        gross_sales_web
        + gross_sales_playstore
        + gross_sales_ios
        + gross_sales_onestore
    )
    gross_free_price = gross_comped_ticket
    gross_total = (
        gross_paid_price + gross_free_price
    )
    sum_price = paid_price + free_price

    return {
        "gross_total": gross_total,
        "gross_paid_price": gross_paid_price,
        "gross_free_price": gross_free_price,
        "paid_price": paid_price,
        "free_price": free_price,
        "sum_price": sum_price,
    }


def _apply_author_settlement(
    amount: Decimal, author_profit: Decimal | None
) -> Decimal | None:
    if author_profit is None or author_profit <= 0:
        return None
    return _calculate_channel_payout(amount, Decimal("0"), author_profit)


async def _get_author_profit_map(product_ids: list[int], db: AsyncSession) -> dict[int, Decimal]:
    normalized_product_ids = sorted({product_id for product_id in product_ids if product_id is not None})
    if not normalized_product_ids:
        return {}

    query = (
        text(
            """
            SELECT ranked.product_id, ranked.author_profit
              FROM (
                    SELECT z.product_id,
                           z.author_profit,
                           ROW_NUMBER() OVER (
                               PARTITION BY z.product_id
                               ORDER BY COALESCE(z.updated_date, z.created_date) DESC, z.offer_id DESC
                           ) AS rn
                      FROM tb_product_contract_offer z
                      INNER JOIN tb_product p ON p.product_id = z.product_id
                     WHERE z.use_yn = 'Y'
                       AND z.offer_user_id = p.cp_user_id
                       AND z.author_profit IS NOT NULL
                       AND z.author_profit > 0
                       AND z.product_id IN :product_ids
              ) ranked
             WHERE ranked.rn = 1
            """
        ).bindparams(bindparam("product_ids", expanding=True))
    )
    result = await db.execute(query, {"product_ids": normalized_product_ids})
    rows = result.mappings().all()
    return {
        row["product_id"]: _to_decimal(row["author_profit"])
        for row in rows
        if row.get("author_profit") is not None
        and _to_decimal(row["author_profit"]) > 0
    }


async def _get_product_sales_app_fee_rate(db: AsyncSession) -> Decimal:
    query = text(
        """
        SELECT code_value
          FROM tb_common_code
         WHERE code_group = 'common_rate'
           AND code_key = 'payment_fee_rate'
           AND use_yn = 'Y'
         LIMIT 1
        """
    )
    result = await db.execute(query, {})
    row = result.mappings().one_or_none()
    if row is None or row.get("code_value") is None:
        return Decimal("30")
    return _to_decimal(row["code_value"]) * Decimal("100")


def _month_start(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return date(value.year, value.month, 1)
    if isinstance(value, date):
        return date(value.year, value.month, 1)
    value_str = str(value)
    try:
        parsed = datetime.fromisoformat(value_str.replace("Z", "+00:00"))
        return date(parsed.year, parsed.month, 1)
    except ValueError:
        if len(value_str) >= 10:
            parsed_date = date.fromisoformat(value_str[:10])
            return date(parsed_date.year, parsed_date.month, 1)
    return None


async def _get_platform_service_rate_context(
    product_ids: list[int], db: AsyncSession
) -> dict:
    normalized_product_ids = sorted(
        {product_id for product_id in product_ids if product_id is not None}
    )

    if normalized_product_ids:
        query = (
            text(
                """
                SELECT scope_type, product_id, rate, effective_month, id
                  FROM tb_platform_service_rate_history
                 WHERE use_yn = 'Y'
                   AND (
                        scope_type = :global_scope
                        OR product_id IN :product_ids
                   )
                 ORDER BY effective_month DESC, id DESC
                """
            ).bindparams(bindparam("product_ids", expanding=True))
        )
        result = await db.execute(
            query,
            {
                "global_scope": GLOBAL_PLATFORM_SERVICE_SCOPE,
                "product_ids": normalized_product_ids,
            },
        )
    else:
        query = text(
            """
            SELECT scope_type, product_id, rate, effective_month, id
              FROM tb_platform_service_rate_history
             WHERE use_yn = 'Y'
               AND scope_type = :global_scope
             ORDER BY effective_month DESC, id DESC
            """
        )
        result = await db.execute(query, {"global_scope": GLOBAL_PLATFORM_SERVICE_SCOPE})

    global_rows: list[dict] = []
    product_rows: dict[int, list[dict]] = {}
    for row in result.mappings().all():
        row_dict = dict(row)
        if (
            row_dict["scope_type"] == GLOBAL_PLATFORM_SERVICE_SCOPE
            and row_dict["product_id"] == GLOBAL_PLATFORM_SERVICE_PRODUCT_ID
        ):
            global_rows.append(row_dict)
            continue
        product_rows.setdefault(row_dict["product_id"], []).append(row_dict)

    return {
        "global_rows": global_rows,
        "product_rows": product_rows,
    }


def _resolve_platform_service_rate(
    product_id: int | None, created_date_value, context: dict
) -> Decimal:
    target_month = _month_start(created_date_value)
    if target_month is None:
        return PRODUCT_PLATFORM_SERVICE_RATE

    for row in context.get("product_rows", {}).get(product_id, []):
        effective_month = row.get("effective_month")
        if effective_month is None or effective_month > target_month:
            continue
        if row.get("rate") is None:
            break
        return _to_decimal(row["rate"])

    for row in context.get("global_rows", []):
        effective_month = row.get("effective_month")
        if effective_month is None or effective_month > target_month:
            continue
        if row.get("rate") is None:
            continue
        return _to_decimal(row["rate"])

    return PRODUCT_PLATFORM_SERVICE_RATE


def _normalize_product_sales_row(
    data: dict, app_fee_rate: Decimal, platform_service_rate: Decimal
) -> dict:
    normalized = dict(data)
    normalized["fee_web"] = _to_int(PRODUCT_WEB_FEE_RATE)
    normalized["fee_playstore"] = _to_int(app_fee_rate)
    normalized["fee_ios"] = _to_int(app_fee_rate)
    normalized["fee_onestore"] = _to_int(app_fee_rate)
    normalized["fee_comped_ticket"] = _to_int(PRODUCT_COMPED_FEE_RATE)
    payout_rate = Decimal("100") - platform_service_rate
    normalized["settlement_rate_web"] = _to_int(payout_rate)
    normalized["settlement_rate_playstore"] = _to_int(payout_rate)
    normalized["settlement_rate_ios"] = _to_int(payout_rate)
    normalized["settlement_rate_onestore"] = _to_int(payout_rate)
    normalized["settlement_rate_comped_ticket"] = _to_int(payout_rate)
    return normalized


def _normalize_monthly_settlement_row(
    data: dict, app_fee_rate: Decimal, platform_service_rate: Decimal
) -> dict:
    normalized = dict(data)
    gross_sales = _to_decimal(normalized.get("sum_total_sales_price"))
    if normalized.get("item_type") == "comped":
        fee_rate = PRODUCT_COMPED_FEE_RATE
    elif normalized.get("device_type") == "web":
        fee_rate = PRODUCT_WEB_FEE_RATE
    else:
        fee_rate = app_fee_rate

    fee = _calculate_channel_payout(gross_sales, Decimal("0"), fee_rate)
    net_sales_price = gross_sales - fee
    platform_revenue = _calculate_channel_payout(
        net_sales_price, Decimal("0"), platform_service_rate
    )
    settlement_price = max(Decimal("0"), net_sales_price - platform_revenue)

    normalized["fee"] = _to_int(fee)
    normalized["net_sales_price"] = _to_int(net_sales_price)
    normalized["taxable_price"] = _to_int(settlement_price)
    normalized["vat_price"] = 0
    normalized["settlement_price"] = _to_int(settlement_price)
    normalized["platform_revenue"] = _to_int(platform_revenue)
    return normalized


async def monthly_sales_by_product_list(
    search_target: str,
    search_word: str,
    search_start_date: str,
    search_end_date: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
    user_data: dict,
):
    """
    작품별 월매출 데이터를 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        search_target: 검색 대상 (product-title, product-id, author-name, cp-name)
        search_word: 검색어
        search_start_date: 검색 시작 날짜 (YYYY-MM-DD)
        search_end_date: 검색 종료 날짜 (YYYY-MM-DD)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 작품별 월매출 데이터 목록
    """

    where = """"""
    # JOIN 최적화를 위한 추가 테이블 조인 설정
    additional_joins = ""

    if user_data["role"] == "author":
        additional_joins += """
            INNER JOIN tb_product p ON pps.product_id = p.product_id
        """
        where += f"""
            AND p.author_id = {user_data["user_id"]}
        """
    elif user_data["role"] == "CP":
        additional_joins += """
            INNER JOIN tb_product p ON pps.product_id = p.product_id
        """
        where += f"""
            AND (p.cp_user_id = {user_data["user_id"]}
                 OR p.user_id = {user_data["user_id"]})
        """

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            if additional_joins == "":
                additional_joins += """
                    INNER JOIN tb_product p ON pps.product_id = p.product_id
                """
            where += f"""
                          AND p.title LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_PRODUCT_ID:
            if not search_word.isdigit():
                # 숫자가 아닌 경우 에러 처리
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.SEARCH_WORD_MUST_BE_NUMBER,
                )
            where += f"""
                          AND pps.product_id = {search_word}
                          """
        elif search_target == CommonConstants.SEARCH_AUTHOR_NAME:
            where += f"""
                          AND pps.author_nickname LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_CP_NAME:
            where += f"""
                          AND pps.product_id IN (
                              {_cp_company_name_product_ids_subquery(search_word)}
                          )
                          """

    if search_start_date != "":
        where += f"""
                      AND DATE(pps.created_date) >= '{search_start_date}'
                      """

    if search_end_date != "":
        where += f"""
                      AND DATE(pps.created_date) <= '{search_end_date}'
                      """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기 - JOIN 최적화 적용
    count_query = text(f"""
        select count(DISTINCT pps.id) as total_count
        from tb_ptn_product_sales pps
        {additional_joins}
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회 - JOIN 최적화 적용
    query = text(f"""
        select DISTINCT pps.*
        from tb_ptn_product_sales pps
        {additional_joins}
        WHERE 1=1 {where}
        ORDER BY pps.created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()
    app_fee_rate = await _get_product_sales_app_fee_rate(db)
    platform_rate_context = await _get_platform_service_rate_context(
        [row["product_id"] for row in rows], db
    )
    cp_metadata_map = await _get_cp_metadata_map_by_product_ids(
        [row["product_id"] for row in rows], db
    )

    author_profit_map = {}
    if rows and user_data["role"] == "author":
        author_profit_map = await _get_author_profit_map(
            [row["product_id"] for row in rows], db
        )

    normalized_rows = []
    for row in rows:
        platform_service_rate = _resolve_platform_service_rate(
            row["product_id"], row.get("created_date"), platform_rate_context
        )
        data = _normalize_product_sales_row(
            dict(row), app_fee_rate, platform_service_rate
        )
        totals = _calculate_product_sales_totals(data)
        data["gross_total_price"] = _to_int(totals["gross_total"])
        cp_metadata = cp_metadata_map.get(data["product_id"], {})
        data["cp_company_name"] = cp_metadata.get("cp_company_name")
        data["contract_type"] = cp_metadata.get("contract_type")
        if user_data["role"] == "author":
            author_settlement = _apply_author_settlement(
                totals["sum_price"], author_profit_map.get(data["product_id"])
            )
            data["settlement_price"] = (
                _to_int(author_settlement) if author_settlement is not None else None
            )
        else:
            data["settlement_price"] = _to_int(totals["sum_price"])
        normalized_rows.append(data)

    return build_paginated_response(normalized_rows, total_count, page, count_per_page)


async def monthly_sales_by_product_detail_by_product_id(
    id: int, db: AsyncSession, user_data: dict
):
    """
    특정 작품의 월매출 상세 정보를 조회

    Args:
        id: 작품 ID
        db: 데이터베이스 세션

    Returns:
        dict: 해당 작품의 월매출 상세 데이터
    """
    access_where = ""
    if user_data["role"] == "author":
        access_where = "AND author_id = :user_id"
    elif user_data["role"] == "CP":
        access_where = "AND (cp_user_id = :user_id OR user_id = :user_id)"

    if access_where:
        access_query = text(f"""
            SELECT 1
              FROM tb_product
             WHERE product_id = :product_id
               {access_where}
             LIMIT 1
        """)
        access_result = await db.execute(
            access_query,
            {"product_id": id, "user_id": user_data["user_id"]},
        )
        if access_result.scalar() is None:
            raise CustomResponseException(
                status_code=status.HTTP_403_FORBIDDEN,
                message=ErrorMessages.PERMISSION_DENIED,
            )

    query = text("""
        SELECT
            *
        FROM tb_ptn_product_sales
        WHERE product_id = :product_id
    """)
    result = await db.execute(query, {"product_id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_PRODUCT)

    data = dict(rows[0])
    app_fee_rate = await _get_product_sales_app_fee_rate(db)
    platform_rate_context = await _get_platform_service_rate_context([id], db)
    platform_service_rate = _resolve_platform_service_rate(
        id, data.get("created_date"), platform_rate_context
    )
    data = _normalize_product_sales_row(data, app_fee_rate, platform_service_rate)
    cp_metadata = (await _get_cp_metadata_map_by_product_ids([id], db)).get(id, {})
    data["cp_company_name"] = cp_metadata.get("cp_company_name")
    data["contract_type"] = cp_metadata.get("contract_type")
    totals = _calculate_product_sales_totals(data)

    gross_paid_price = totals["gross_paid_price"]
    gross_free_price = totals["gross_free_price"]
    gross_total_price = totals["gross_total"]
    tax_price = Decimal("0")
    paid_settlement_price = totals["paid_price"]
    free_settlement_price = totals["free_price"]
    settlement_price = totals["sum_price"]

    if user_data["role"] == "author":
        author_profit_map = await _get_author_profit_map([id], db)
        author_profit = author_profit_map.get(id)
        if author_profit is None:
            paid_settlement_price = None
            free_settlement_price = None
            settlement_price = None
        else:
            paid_settlement_price = _apply_author_settlement(
                paid_settlement_price, author_profit
            )
            free_settlement_price = _apply_author_settlement(
                free_settlement_price, author_profit
            )
            settlement_price = _apply_author_settlement(
                settlement_price, author_profit
            )

    data["gross_paid_price"] = (
        _to_int(gross_paid_price) if gross_paid_price is not None else None
    )
    data["gross_free_price"] = (
        _to_int(gross_free_price) if gross_free_price is not None else None
    )
    data["gross_total_price"] = (
        _to_int(gross_total_price) if gross_total_price is not None else None
    )

    return {
        "result": data,
        "summary": {
            "paid_price": (
                _to_int(totals["paid_price"])
                if totals["paid_price"] is not None
                else None
            ),
            "free_price": (
                _to_int(totals["free_price"])
                if totals["free_price"] is not None
                else None
            ),
            "sum_price": (
                _to_int(totals["sum_price"])
                if totals["sum_price"] is not None
                else None
            ),
            "tax_price": _to_int(tax_price) if tax_price is not None else None,
            "total_price": (
                _to_int(_to_decimal(data.get("total_price")))
                if data.get("total_price") is not None
                else None
            ),
            "gross_paid_price": (
                _to_int(gross_paid_price) if gross_paid_price is not None else None
            ),
            "gross_free_price": (
                _to_int(gross_free_price) if gross_free_price is not None else None
            ),
            "gross_total_price": (
                _to_int(gross_total_price) if gross_total_price is not None else None
            ),
            "paid_settlement_price": (
                _to_int(paid_settlement_price)
                if paid_settlement_price is not None
                else None
            ),
            "free_settlement_price": (
                _to_int(free_settlement_price)
                if free_settlement_price is not None
                else None
            ),
            "settlement_price": (
                _to_int(settlement_price)
                if settlement_price is not None
                else None
            ),
        },
    }


async def put_monthly_sales_by_product(
    req_body: partner_schema.PutPtnProductSalesReqBody,
    product_id: int,
    db: AsyncSession,
):
    """
    작품별 월매출 정보를 업데이트

    Args:
        req_body: 월매출 수정 요청 데이터 (정산액, 정산율, 수수료, 세액 등)
        product_id: 작품 ID
        db: 데이터베이스 세션

    Returns:
        dict: 업데이트된 요청 데이터
    """

    update_filed_query_list = [
        "updated_id = :updated_id",
        "updated_date = :updated_date",
    ]

    db_execute_params = {
        "updated_id": -1,
        "updated_date": datetime.now(),
        "product_id": product_id,
    }

    if (
        req_body.sum_settlement_price_web is not None
        and req_body.sum_settlement_comped_ticket_price is not None
        and req_body.tax_price is not None
    ):
        if req_body.sum_settlement_price_web < 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.PAID_AMOUNT_NEGATIVE,
            )

        if req_body.sum_settlement_comped_ticket_price < 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.FREE_AMOUNT_NEGATIVE,
            )

        if req_body.tax_price < 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.TAX_AMOUNT_NEGATIVE,
            )

        update_filed_query_list.append(
            "sum_settlement_price_web = :sum_settlement_price_web"
        )
        db_execute_params["sum_settlement_price_web"] = (
            req_body.sum_settlement_price_web
        )

        update_filed_query_list.append(
            "sum_settlement_comped_ticket_price = :sum_settlement_comped_ticket_price"
        )
        db_execute_params["sum_settlement_comped_ticket_price"] = (
            req_body.sum_settlement_comped_ticket_price
        )

        update_filed_query_list.append("tax_price = :tax_price")
        db_execute_params["tax_price"] = req_body.tax_price

        update_filed_query_list.append("total_price = :total_price")
        db_execute_params["total_price"] = (
            req_body.sum_settlement_price_web
            + req_body.sum_settlement_comped_ticket_price
            - req_body.tax_price
        )
    elif (
        req_body.settlement_rate is not None
        and req_body.fee is not None
        and req_body.tax_price is not None
    ):
        if req_body.settlement_rate < 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.SETTLEMENT_RATE_NEGATIVE,
            )

        if req_body.fee < 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.PAYMENT_FEE_NEGATIVE,
            )

        if req_body.tax_price < 0:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.TAX_AMOUNT_NEGATIVE,
            )

        update_filed_query_list.append("settlement_rate_web = :settlement_rate")
        update_filed_query_list.append("settlement_rate_playstore = :settlement_rate")
        update_filed_query_list.append("settlement_rate_ios = :settlement_rate")
        update_filed_query_list.append("settlement_rate_onestore = :settlement_rate")
        update_filed_query_list.append(
            "settlement_rate_comped_ticket = :settlement_rate"
        )
        db_execute_params["settlement_rate"] = req_body.settlement_rate

        update_filed_query_list.append("fee_web = :fee")
        update_filed_query_list.append("fee_playstore = :fee")
        update_filed_query_list.append("fee_ios = :fee")
        update_filed_query_list.append("fee_onestore = :fee")
        update_filed_query_list.append("fee_comped_ticket = :fee")
        db_execute_params["fee"] = req_body.fee

        update_filed_query_list.append("tax_price = :tax_price")
        db_execute_params["tax_price"] = req_body.tax_price
    else:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.SETTLEMENT_FIELDS_REQUIRED,
        )

    update_filed_query = ",".join(update_filed_query_list)

    query = text(f"""
                        update tb_ptn_product_sales set
                        {update_filed_query}
                        where product_id = :product_id
                    """)

    await db.execute(query, db_execute_params)

    return {"result": req_body}


async def sales_by_episode_list(
    search_target: str,
    search_word: str,
    search_start_date: str,
    search_end_date: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
    user_data: dict,
):
    """
    회차별 매출 데이터를 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        search_target: 검색 대상 (product-title, product-id, author-name, cp-name)
        search_word: 검색어
        search_start_date: 검색 시작 날짜 (YYYY-MM-DD)
        search_end_date: 검색 종료 날짜 (YYYY-MM-DD)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 회차별 매출 데이터 목록
    """

    where = """"""
    if user_data["role"] == "author":
        where += f"""
            AND product_id IN (SELECT product_id FROM tb_product WHERE author_id = {user_data["user_id"]})
        """
    elif user_data["role"] == "CP":
        where += f"""
            AND product_id IN (
                {_cp_owned_product_ids_subquery(user_data["user_id"])}
            )
        """

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where += f"""
                          AND product_id IN (SELECT product_id FROM tb_product WHERE title LIKE '%{search_word}%')
                          """
        elif search_target == CommonConstants.SEARCH_PRODUCT_ID:
            if not search_word.isdigit():
                # 숫자가 아닌 경우 에러 처리
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.SEARCH_WORD_MUST_BE_NUMBER,
                )
            where += f"""
                          AND product_id = {search_word}
                          """
        elif search_target == CommonConstants.SEARCH_AUTHOR_NAME:
            where += f"""
                          AND author_nickname LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_CP_NAME:
            where += f"""
                          AND product_id IN (
                                {_cp_company_name_product_ids_subquery(search_word)}
                          )
                          """

    if search_start_date != "":
        where += f"""
                      AND DATE(created_date) >= '{search_start_date}'
                      """

    if search_end_date != "":
        where += f"""
                      AND DATE(created_date) <= '{search_end_date}'
                      """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)
    is_full_query = page == -1 or count_per_page == -1

    total_count = 0
    if not is_full_query:
        count_query = text(f"""
            select count(distinct product_id) as total_count
            from tb_ptn_product_episode_sales
            WHERE 1=1 {where}
        """)
        count_result = await db.execute(count_query, {})
        total_count = count_result.mappings().first()["total_count"]

        query = text(f"""
            select sales.*
                , e.episode_title
            from (
                select ranked.*
                from (
                    select s.*
                        , row_number() over (
                            partition by s.product_id
                            order by s.created_date desc, s.id desc
                        ) as rn
                    from tb_ptn_product_episode_sales s
                    WHERE 1=1 {where}
                ) ranked
                where ranked.rn = 1
                order by ranked.created_date desc, ranked.id desc
                {limit_clause}
            ) sales
            left join tb_product_episode e on e.episode_id = sales.episode_id
            order by sales.created_date desc, sales.id desc
        """)
        result = await db.execute(query, limit_params)
    else:
        # 전체 다운로드는 기존처럼 회차 row 전체를 반환하되 count 쿼리는 건너뛴다.
        query = text(f"""
            select sales.*
                , e.episode_title
            from (
                select s.*
                from tb_ptn_product_episode_sales s
                WHERE 1=1 {where}
                ORDER BY s.created_date DESC, s.id DESC
                {limit_clause}
            ) sales
            left join tb_product_episode e on e.episode_id = sales.episode_id
            ORDER BY sales.created_date DESC, sales.id DESC
        """)
        result = await db.execute(query, limit_params)
    rows = result.mappings().all()
    normalized_rows = []
    for row in rows:
        row_dict = dict(row)
        row_dict["episode_title"] = _normalize_episode_title(
            row_dict.get("episode_title")
        )
        normalized_rows.append(row_dict)

    if is_full_query:
        total_count = len(normalized_rows)

    return build_paginated_response(
        normalized_rows, total_count, page, count_per_page
    )


async def sales_by_episode_list_by_product_id(
    product_id: int,
    search_target: str,
    search_word: str,
    search_start_date: str,
    search_end_date: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
):
    """
    특정 작품의 회차별 매출 데이터를 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        product_id: 작품 ID
        search_target: 검색 대상
        search_word: 검색어
        search_start_date: 검색 시작 날짜 (YYYY-MM-DD)
        search_end_date: 검색 종료 날짜 (YYYY-MM-DD)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 해당 작품의 회차별 매출 데이터 목록
    """

    where = f"""
                 AND product_id = {product_id}
                 """

    where, params = build_search_where_clause(
        search_word,
        search_target,
        search_start_date,
        search_end_date,
        search_type="partner",
    )

    limit_clause, limit_params = get_pagination_params(page, count_per_page)
    is_full_query = page == -1 or count_per_page == -1

    non_zero_clause = """
            AND (
                coalesce(count_total_sales, 0) > 0
                OR coalesce(count_total_refund, 0) > 0
            )
    """

    total_count = 0
    if not is_full_query:
        count_query = text(f"""
            select count(*) as total_count
            from tb_ptn_product_episode_sales
            WHERE product_id = {product_id} {where}
            {non_zero_clause}
        """)
        count_result = await db.execute(count_query, params)
        total_count = count_result.mappings().first()["total_count"]

    query = text(f"""
        select sales.*
            , e.episode_title
        from (
            select s.*
            from tb_ptn_product_episode_sales s
            WHERE product_id = {product_id} {where}
            {non_zero_clause}
            ORDER BY s.created_date DESC
            {limit_clause}
        ) sales
        left join tb_product_episode e on e.episode_id = sales.episode_id
        ORDER BY sales.created_date DESC
    """)
    result = await db.execute(query, limit_params | params)
    rows = result.mappings().all()
    normalized_rows = []
    for row in rows:
        row_dict = dict(row)
        row_dict["episode_title"] = _normalize_episode_title(
            row_dict.get("episode_title")
        )
        normalized_rows.append(row_dict)

    if is_full_query:
        total_count = len(normalized_rows)

    return build_paginated_response(
        normalized_rows, total_count, page, count_per_page
    )


async def daily_ticket_list(
    search_target: str,
    search_word: str,
    search_start_date: str,
    search_end_date: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
    user_data: dict,
):
    """
    일별 이용권 상세 데이터를 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        search_target: 검색 대상 (product-title, product-id, author-name, cp-name)
        search_word: 검색어
        search_start_date: 검색 시작 날짜 (YYYY-MM-DD)
        search_end_date: 검색 종료 날짜 (YYYY-MM-DD)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 일별 이용권 상세 데이터 목록
    """

    where = """"""
    if user_data["role"] == "author":
        where += f"""
            AND product_id IN (SELECT product_id FROM tb_product WHERE author_id = {user_data["user_id"]})
        """
    elif user_data["role"] == "CP":
        where += f"""
            AND product_id IN (
                {_cp_owned_product_ids_subquery(user_data["user_id"])}
            )
        """

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where += f"""
                          AND product_id IN (SELECT product_id FROM tb_product WHERE title LIKE '%{search_word}%')
                          """
        elif search_target == CommonConstants.SEARCH_PRODUCT_ID:
            if not search_word.isdigit():
                # 숫자가 아닌 경우 에러 처리
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.SEARCH_WORD_MUST_BE_NUMBER,
                )
            where += f"""
                          AND product_id = {search_word}
                          """
        elif search_target == CommonConstants.SEARCH_AUTHOR_NAME:
            where += f"""
                          AND author_nickname LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_CP_NAME:
            where += f"""
                          AND product_id IN (
                                {_cp_company_name_product_ids_subquery(search_word)}
                          )
                          """

    if search_start_date != "":
        where += f"""
                      AND DATE(created_date) >= '{search_start_date}'
                      """

    if search_end_date != "":
        where += f"""
                      AND DATE(created_date) <= '{search_end_date}'
                      """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        select count(*) as total_count
        from tb_ptn_ticket_usage
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        select *
            , (select publish_regular_yn from tb_product where product_id = ptu.product_id) as publish_regular_yn
        from tb_ptn_ticket_usage ptu
        WHERE 1=1 {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)


async def monthly_settlement_list(
    search_target: str,
    search_word: str,
    search_start_date: str,
    search_end_date: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
    user_data: dict,
):
    """
    월별 정산 데이터를 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        search_target: 검색 대상 (author-name, cp-name)
        search_word: 검색어
        search_start_date: 검색 시작 날짜 (YYYY-MM-DD)
        search_end_date: 검색 종료 날짜 (YYYY-MM-DD)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 월별 정산 데이터 목록
    """

    where = """"""
    if user_data["role"] == "author":
        where += f"""
            AND product_id IN (SELECT product_id FROM tb_product WHERE author_id = {user_data["user_id"]})
        """
    elif user_data["role"] == "CP":
        where += f"""
            AND product_id IN (
                {_cp_owned_product_ids_subquery(user_data["user_id"])}
            )
        """

    if search_word != "":
        if search_target == "author-name":
            where += f"""
                          AND product_id IN (SELECT product_id FROM tb_product WHERE author_name LIKE '%{search_word}%')
                          """
        elif search_target == CommonConstants.SEARCH_CP_NAME:
            where += f"""
                          AND product_id IN (
                                {_cp_company_name_product_ids_subquery(search_word)}
                          )
                          """

    if search_start_date != "":
        where += f"""
                      AND DATE(created_date) >= '{search_start_date}'
                      """

    if search_end_date != "":
        where += f"""
                      AND DATE(created_date) <= '{search_end_date}'
                      """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        select count(*) as total_count
        from tb_ptn_product_settlement
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        select *,
            (
                select author_name
                from tb_product
                where product_id = pps.product_id
            ) as author_name,
            {_cp_company_name_lookup_subquery("pps.product_id")} as cp_name
        from tb_ptn_product_settlement pps
        WHERE 1=1 {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()
    app_fee_rate = await _get_product_sales_app_fee_rate(db)
    platform_rate_context = await _get_platform_service_rate_context(
        [row["product_id"] for row in rows], db
    )

    author_profit_map = {}
    if rows and user_data["role"] == "author":
        author_profit_map = await _get_author_profit_map(
            [row["product_id"] for row in rows], db
        )

    normalized_rows = []
    for row in rows:
        platform_service_rate = _resolve_platform_service_rate(
            row["product_id"], row.get("created_date"), platform_rate_context
        )
        data = _normalize_monthly_settlement_row(
            dict(row), app_fee_rate, platform_service_rate
        )
        if user_data["role"] == "author":
            author_settlement = _apply_author_settlement(
                _to_decimal(data.get("settlement_price")),
                author_profit_map.get(data["product_id"]),
            )
            data["settlement_price"] = (
                _to_int(author_settlement) if author_settlement is not None else None
            )
            if data["settlement_price"] is None:
                data["final_settlement_price"] = None
            else:
                data["final_settlement_price"] = data["settlement_price"]
        normalized_rows.append(data)

    return build_paginated_response(normalized_rows, total_count, page, count_per_page)


async def product_contract_offer_deduction_list(
    search_target: str,
    search_word: str,
    search_start_date: str,
    search_end_date: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
    user_data: dict,
):
    """
    선계약금 차감 내역을 조건에 따라 검색하고 페이징된 목록을 반환

    Args:
        search_target: 검색 대상 (product-title, product-id, author-name, cp-name)
        search_word: 검색어
        search_start_date: 검색 시작 날짜 (YYYY-MM-DD)
        search_end_date: 검색 종료 날짜 (YYYY-MM-DD)
        page: 페이지 번호
        count_per_page: 페이지당 항목 수
        db: 데이터베이스 세션

    Returns:
        dict: 전체 개수, 페이징 정보, 선계약금 차감 내역 목록
    """

    where = """"""
    if user_data["role"] == "author":
        where += f"""
            AND product_id IN (SELECT product_id FROM tb_product WHERE author_id = {user_data["user_id"]})
        """
    elif user_data["role"] == "CP":
        where += f"""
            AND product_id IN (
                {_cp_owned_product_ids_subquery(user_data["user_id"])}
            )
        """

    if search_word != "":
        if search_target == CommonConstants.SEARCH_PRODUCT_TITLE:
            where += f"""
                          AND product_id IN (SELECT product_id FROM tb_product WHERE title LIKE '%{search_word}%')
                          """
        elif search_target == CommonConstants.SEARCH_PRODUCT_ID:
            if not search_word.isdigit():
                # 숫자가 아닌 경우 에러 처리
                raise CustomResponseException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=ErrorMessages.SEARCH_WORD_MUST_BE_NUMBER,
                )
            where += f"""
                          AND product_id = {search_word}
                          """
        elif search_target == CommonConstants.SEARCH_AUTHOR_NAME:
            where += f"""
                          AND author_nickname LIKE '%{search_word}%'
                          """
        elif search_target == CommonConstants.SEARCH_CP_NAME:
            where += f"""
                          AND product_id IN (
                                {_cp_company_name_product_ids_subquery(search_word)}
                          )
                          """

    if search_start_date != "":
        where += f"""
                      AND DATE(created_date) >= '{search_start_date}'
                      """

    if search_end_date != "":
        where += f"""
                      AND DATE(created_date) <= '{search_end_date}'
                      """

    limit_clause, limit_params = get_pagination_params(page, count_per_page)

    # 전체 개수 구하기
    count_query = text(f"""
        select count(*) as total_count
        from tb_ptn_product_contract_offer_deduction
        WHERE 1=1 {where}
    """)
    count_result = await db.execute(count_query, {})
    total_count = count_result.mappings().first()["total_count"]

    # 실제 데이터 조회
    query = text(f"""
        with tmp_contract_offer_settlement_summary as (
            select z.product_id
                , z.offer_id
            from tb_product_contract_offer z
            where z.use_yn = 'Y'
            and z.author_accept_yn = 'Y'
        )
        select a.*, b.offer_id
        from tb_ptn_product_contract_offer_deduction a
        inner join tmp_contract_offer_settlement_summary b on a.product_id = b.product_id
        WHERE 1=1 {where}
        ORDER BY created_date DESC
        {limit_clause}
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return build_paginated_response(rows, total_count, page, count_per_page)
