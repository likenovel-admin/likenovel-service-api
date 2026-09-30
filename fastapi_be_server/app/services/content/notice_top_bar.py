"""상단 띠 공지(site-wide top bar) attached to a general notice.

Operators turn it on while writing or editing a notice in CMS. The service web
shows the single active bar and links it to the operator's link, or to the
notice detail page when the link is empty.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import CustomResponseException

TOP_BAR_TEXT_MAX_LENGTH = 80
TOP_BAR_LINK_MAX_LENGTH = 500
_LINK_FORMAT_MESSAGE = "상단 띠 링크는 /로 시작하는 사이트 주소나 https:// 주소만 넣을 수 있습니다."
# Same link rule as the CMS (noticeTopBar.ts) and the service web (topNoticeBar.ts); change all three together.
# Backslashes read like slashes in browsers; spaces, controls, and invisible format characters are rejected.
_UNSAFE_LINK_CHARS = re.compile(
    r"[\\\x00-\x20\x7f-\xa0\xad\u1680\u180e\u2000-\u200f\u2028-\u202f\u205f-\u206f\u3000\ufeff\ufff0-\uffff]"
)
# https host: letters, digits, hyphens, and dots, ending in a label that starts with a letter
# (no port, IP address, user info such as "@", or punycode "xn--" labels).
_HTTPS_LINK = re.compile(
    r"https://(?:(?!xn--)[a-z0-9-]+\.)*(?!xn--)[a-z][a-z0-9-]*(?:[/?#]|$)", re.IGNORECASE | re.ASCII
)
_DOT_SEGMENT = re.compile(r"/\.\.?(?:/|$)")
# Characters JavaScript String.prototype.trim() removes, so the CMS and the backend trim alike.
_LINK_TRIM_CHARS = "\t\n\v\f\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_DATETIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M")
_KST = ZoneInfo("Asia/Seoul")


def _now_kst() -> datetime:
    # tb_notice top-bar times are stored as naive KST, matching the DB NOW().
    return datetime.now(_KST).replace(tzinfo=None, microsecond=0)


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


def _is_allowed_link(link: str) -> bool:
    if _UNSAFE_LINK_CHARS.search(link):
        return False
    if _HTTPS_LINK.match(link):
        return True
    if not link.startswith("/") or link.startswith("//"):
        return False
    # Keep site paths on this site: no "//", dot segments, or encoded dots before the query.
    path = re.split(r"[?#]", link, maxsplit=1)[0]
    return "//" not in path and "%2e" not in path.lower() and not _DOT_SEGMENT.search(path)


def _normalize_link_url(value: Any) -> str | None:
    """Empty means the notice detail page. Only site paths and https URLs are allowed."""
    link = str(value or "").strip(_LINK_TRIM_CHARS)
    if not link:
        return None
    if len(link) > TOP_BAR_LINK_MAX_LENGTH:
        raise _bad_request(f"상단 띠 링크는 {TOP_BAR_LINK_MAX_LENGTH}자 이내로 입력해주세요.")
    if not _is_allowed_link(link):
        raise _bad_request(_LINK_FORMAT_MESSAGE)
    return link


def resolve_notice_top_bar_columns(req_body: Any) -> dict[str, Any] | None:
    """Return all top-bar column values, or None when the request omits them.

    Turning the bar off clears its text, period, and link so a stale bar never returns.
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
            "top_bar_link_url": None,
        }

    bar_text = " ".join(str(getattr(req_body, "top_bar_text", "") or "").split())
    if not bar_text:
        raise _bad_request("상단 띠 문구를 입력해주세요.")
    if len(bar_text) > TOP_BAR_TEXT_MAX_LENGTH:
        raise _bad_request(f"상단 띠 문구는 {TOP_BAR_TEXT_MAX_LENGTH}자 이내로 입력해주세요.")
    start_date = _parse_datetime(getattr(req_body, "top_bar_start_date", None), label="시작 시각")
    end_date = _parse_datetime(getattr(req_body, "top_bar_end_date", None), label="종료 시각")
    start_defaulted = start_date is None
    if start_defaulted:
        # "비우면 저장 즉시": record the save time so the newest bar wins ordering.
        start_date = _now_kst()
    if end_date and end_date <= start_date:
        raise _bad_request(
            "상단 띠 종료 시각은 지금보다 뒤여야 합니다."
            if start_defaulted
            else "상단 띠 종료 시각은 시작 시각보다 뒤여야 합니다."
        )
    return {
        "top_bar_yn": "Y",
        "top_bar_text": bar_text,
        "top_bar_start_date": start_date,
        "top_bar_end_date": end_date,
        "top_bar_link_url": _normalize_link_url(getattr(req_body, "top_bar_link_url", None)),
    }


async def get_active_notice_top_bar(db: AsyncSession) -> dict[str, Any]:
    result = await db.execute(
        text(
            """
            SELECT id AS noticeId,
                   top_bar_text AS text,
                   top_bar_link_url AS linkUrl,
                   DATE_FORMAT(top_bar_end_date, '%Y-%m-%d %H:%i:%s') AS endAt
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
