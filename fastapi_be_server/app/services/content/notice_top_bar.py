"""상단 띠 공지(site-wide top bar) attached to a general notice.

Operators turn it on while writing or editing a notice in CMS. The service web
shows the single active bar and links it to the notice detail page.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import CustomResponseException

TOP_BAR_TEXT_MAX_LENGTH = 80
_DATETIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M")


def _bad_request(message: str) -> CustomResponseException:
    return CustomResponseException(
        status_code=status.HTTP_400_BAD_REQUEST,
        message=message,
    )


def _parse_datetime(value: str | None, *, label: str) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    raise _bad_request(f"상단 띠 {label} 형식이 올바르지 않습니다.")


def resolve_notice_top_bar_columns(req_body: Any) -> dict[str, Any] | None:
    """Return all four top-bar column values, or None when the request omits them.

    Turning the bar off clears its text and period so a stale bar never returns.
    """
    top_bar_yn = getattr(req_body, "top_bar_yn", None)
    if top_bar_yn is None:
        return None
    normalized_yn = str(top_bar_yn).strip().upper()
    if normalized_yn not in {"Y", "N"}:
        raise _bad_request("상단 띠 노출 여부는 Y 또는 N이어야 합니다.")
    if normalized_yn == "N":
        return {
            "top_bar_yn": "N",
            "top_bar_text": None,
            "top_bar_start_date": None,
            "top_bar_end_date": None,
        }

    bar_text = " ".join(str(getattr(req_body, "top_bar_text", "") or "").split())
    if not bar_text:
        raise _bad_request("상단 띠 문구를 입력해주세요.")
    if len(bar_text) > TOP_BAR_TEXT_MAX_LENGTH:
        raise _bad_request(f"상단 띠 문구는 {TOP_BAR_TEXT_MAX_LENGTH}자 이내로 입력해주세요.")
    start_date = _parse_datetime(getattr(req_body, "top_bar_start_date", None), label="시작 시각")
    end_date = _parse_datetime(getattr(req_body, "top_bar_end_date", None), label="종료 시각")
    if start_date and end_date and end_date <= start_date:
        raise _bad_request("상단 띠 종료 시각은 시작 시각보다 뒤여야 합니다.")
    return {
        "top_bar_yn": "Y",
        "top_bar_text": bar_text,
        "top_bar_start_date": start_date,
        "top_bar_end_date": end_date,
    }


async def get_active_notice_top_bar(db: AsyncSession) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT id AS noticeId, top_bar_text AS text
            FROM tb_notice
            WHERE use_yn = 'Y'
              AND top_bar_yn = 'Y'
              AND top_bar_text IS NOT NULL
              AND (top_bar_start_date IS NULL OR top_bar_start_date <= NOW())
              AND (top_bar_end_date IS NULL OR top_bar_end_date > NOW())
            ORDER BY COALESCE(top_bar_start_date, created_date) DESC, id DESC
            LIMIT 1
            """
        )
    )
    row = result.mappings().one_or_none()
    return {"data": dict(row) if row else None}
