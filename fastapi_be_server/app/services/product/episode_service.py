import asyncio
import logging
import posixpath
from datetime import datetime, timedelta
from io import BytesIO
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from typing import Optional
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
from httpx import AsyncClient, HTTPStatusError, RequestError, Timeout

from app.const import settings, CommonConstants, ErrorMessages
from app.exceptions import CustomResponseException
from app.rdb import likenovel_db_session
from app.utils.time import convert_to_kor_time
from app.utils.query import get_file_path_sub_query
import app.services.common.comm_service as comm_service
import app.schemas.episode as episode_schema
import app.services.common.statistics_service as statistics_service
import app.services.product.product_service as product_service
import app.services.event.event_reward_service as event_reward_service

logger = logging.getLogger(__name__)

"""
Episodes service
"""

_EPUB_XHTML_EXTENSIONS = (".xhtml", ".html", ".htm")
_COPYRIGHT_KEYWORDS = ("발행일", "발행인", "isbn", "uci", "ⓒ", "©", "copyright")
_COPYRIGHT_FILE_NAMES = {"copy", "right", "rights", "colophon"}
_MIN_RESERVE_LEAD_MINUTES = 5


@asynccontextmanager
async def _transaction_scope(db: AsyncSession):
    """
    Avoid nested transaction begin() errors when the session already has a transaction.
    """
    if db.in_transaction():
        yield
        return

    async with db.begin():
        yield


def _to_kst_naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None

    if dt.tzinfo is not None:
        return dt.astimezone(ZoneInfo(settings.KOREA_TIMEZONE)).replace(tzinfo=None)

    return dt


def _minimum_reserve_datetime_kst() -> datetime:
    base = datetime.now(ZoneInfo(settings.KOREA_TIMEZONE)).replace(
        tzinfo=None
    ) + timedelta(minutes=_MIN_RESERVE_LEAD_MINUTES)

    if base.second > 0 or base.microsecond > 0:
        base += timedelta(minutes=1)

    return base.replace(second=0, microsecond=0)


def _normalize_publish_reserve_datetime(
    dt: Optional[datetime],
    *,
    message: Optional[str] = None,
) -> datetime:
    reserve_at = convert_to_kor_time(dt)
    if reserve_at is None:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=ErrorMessages.INVALID_EPISODE_INFO,
        )

    if getattr(reserve_at, "tzinfo", None) is not None:
        reserve_at = reserve_at.replace(tzinfo=None)

    if reserve_at < _minimum_reserve_datetime_kst():
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=message
            or f"예약일시는 현재 시각 기준 {_MIN_RESERVE_LEAD_MINUTES}분 이후만 설정할 수 있습니다.",
        )

    return reserve_at


def _is_paid_conversion_effective(
    is_paid_product: bool,
    paid_open_date: Optional[datetime],
    paid_episode_no: Optional[int],
    episode_no: int,
) -> bool:
    # Always-paid products (no schedule) are paid from the first episode.
    if paid_open_date is None:
        return is_paid_product

    now_kst = datetime.now(ZoneInfo(settings.KOREA_TIMEZONE)).replace(tzinfo=None)
    paid_open_date_kst = _to_kst_naive(paid_open_date)
    if paid_open_date_kst is None or now_kst < paid_open_date_kst:
        return False

    start_episode_no = paid_episode_no if paid_episode_no and paid_episode_no > 0 else 1
    return episode_no >= start_episode_no


def _default_episode_price_type(
    is_paid_product: bool,
    paid_open_date: Optional[datetime],
    paid_episode_no: Optional[int],
    episode_no: int,
) -> str:
    return (
        "paid"
        if _is_paid_conversion_effective(
            is_paid_product=is_paid_product,
            paid_open_date=paid_open_date,
            paid_episode_no=paid_episode_no,
            episode_no=episode_no,
        )
        else "free"
    )


def _is_episode_upload_completed(
    latest_apply_status: Optional[str],
    open_yn: Optional[str],
    publish_reserve_date: Optional[datetime],
) -> bool:
    effective_open_yn = open_yn or "N"
    if effective_open_yn == "Y":
        return False

    if latest_apply_status not in (None, "", "cancel"):
        return False

    reserve_at = _to_kst_naive(publish_reserve_date)
    if reserve_at is None:
        return True

    now_kst = datetime.now(ZoneInfo(settings.KOREA_TIMEZONE)).replace(tzinfo=None)
    return reserve_at <= now_kst


def _normalize_bulk_episode_title(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _has_disallowed_control_chars(value: str) -> bool:
    return any(ord(char) < 32 for char in value)


def _xml_local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _is_xhtml_path(file_name: str) -> bool:
    return file_name.lower().endswith(_EPUB_XHTML_EXTENSIONS)


def _is_copyright_file_name(file_name: str) -> bool:
    base_name = posixpath.splitext(posixpath.basename(file_name.lower()))[0]
    return base_name.startswith("copyright") or base_name in _COPYRIGHT_FILE_NAMES


def _count_copyright_keyword_hits(text: str) -> int:
    normalized_text = text.lower()
    return sum(1 for keyword in _COPYRIGHT_KEYWORDS if keyword.lower() in normalized_text)


def _extract_epub_document_parts(html_bytes: bytes) -> tuple[str, str]:
    soup = BeautifulSoup(html_bytes, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    body = soup.find("body")
    html_content = body.decode_contents() if body else str(soup)
    text_content = soup.get_text(separator=" ", strip=True)
    return html_content, text_content


def _read_spine_xhtml_paths_from_epub(epub_zip: ZipFile) -> Optional[list[str]]:
    try:
        container_xml = epub_zip.read("META-INF/container.xml")
        container_root = ET.fromstring(container_xml)
    except Exception:
        return None

    opf_path: Optional[str] = None
    for element in container_root.iter():
        if _xml_local_name(element.tag) != "rootfile":
            continue
        full_path = element.attrib.get("full-path")
        if full_path:
            opf_path = full_path
            break

    if not opf_path:
        return None

    try:
        opf_xml = epub_zip.read(opf_path)
        opf_root = ET.fromstring(opf_xml)
    except Exception:
        return None

    opf_dir = posixpath.dirname(opf_path)
    manifest_map: dict[str, str] = {}
    spine_paths: list[str] = []

    for element in opf_root.iter():
        if _xml_local_name(element.tag) != "item":
            continue
        item_id = element.attrib.get("id")
        href = element.attrib.get("href")
        if not item_id or not href:
            continue
        manifest_map[item_id] = posixpath.normpath(posixpath.join(opf_dir, href))

    for element in opf_root.iter():
        if _xml_local_name(element.tag) != "itemref":
            continue
        idref = element.attrib.get("idref")
        if not idref:
            continue
        resolved_path = manifest_map.get(idref)
        if not resolved_path or not _is_xhtml_path(resolved_path):
            continue
        spine_paths.append(resolved_path)

    return spine_paths or None


def _extract_epub_payload_via_spine(epub_binary: bytes) -> Optional[dict[str, object]]:
    try:
        with ZipFile(BytesIO(epub_binary)) as epub_zip:
            spine_paths = _read_spine_xhtml_paths_from_epub(epub_zip)
            if not spine_paths:
                return None

            docs: list[dict[str, str]] = []
            for spine_path in spine_paths:
                if not _is_xhtml_path(spine_path):
                    continue
                try:
                    html_bytes = epub_zip.read(spine_path)
                except KeyError:
                    return None
                html_content, text_content = _extract_epub_document_parts(html_bytes)
                docs.append(
                    {
                        "path": spine_path,
                        "html": html_content,
                        "text": text_content,
                    }
                )

            if not docs:
                return None

            filtered_docs = docs[:] if len(docs) == 1 else docs[1:]
            if not filtered_docs:
                return {"text_count": 0, "html_content": ""}

            copyright_indexes: set[int] = set()
            inspect_start_idx = max(0, len(filtered_docs) - 3)
            for idx in range(inspect_start_idx, len(filtered_docs)):
                doc = filtered_docs[idx]
                keyword_hits = _count_copyright_keyword_hits(doc["text"])
                if keyword_hits >= 2 or (
                    keyword_hits >= 1 and _is_copyright_file_name(doc["path"])
                ):
                    copyright_indexes.add(idx)

            if copyright_indexes:
                filtered_docs = [
                    doc
                    for idx, doc in enumerate(filtered_docs)
                    if idx not in copyright_indexes
                ]

            html_content = "".join(doc["html"] for doc in filtered_docs)
            text_count = sum(len(doc["text"]) for doc in filtered_docs if doc["text"])
            return {"text_count": text_count, "html_content": html_content}
    except (BadZipFile, ValueError):
        raise
    except Exception:
        return None


def _extract_epub_payload_via_zip_fallback(epub_binary: bytes) -> dict[str, object]:
    docs: list[dict[str, str]] = []

    with ZipFile(BytesIO(epub_binary)) as epub_zip:
        for file_info in epub_zip.infolist():
            if file_info.is_dir():
                continue

            file_name = file_info.filename
            if not _is_xhtml_path(file_name):
                continue

            html_content = epub_zip.read(file_info)
            body_html, text_content = _extract_epub_document_parts(html_content)
            docs.append(
                {
                    "path": file_name,
                    "html": body_html,
                    "text": text_content,
                }
            )

    filtered_docs = [
        doc for doc in docs if "cover" not in doc["path"].lower()
    ]
    inspect_start_idx = max(0, len(filtered_docs) - 3)
    copyright_indexes: set[int] = set()
    for idx in range(inspect_start_idx, len(filtered_docs)):
        doc = filtered_docs[idx]
        keyword_hits = _count_copyright_keyword_hits(doc["text"])
        if keyword_hits >= 2 or (
            keyword_hits >= 1 and _is_copyright_file_name(doc["path"])
        ):
            copyright_indexes.add(idx)

    if copyright_indexes:
        filtered_docs = [
            doc
            for idx, doc in enumerate(filtered_docs)
            if idx not in copyright_indexes
        ]

    return {
        "text_count": sum(len(doc["text"]) for doc in filtered_docs if doc["text"]),
        "html_content": "".join(doc["html"] for doc in filtered_docs),
    }


def _extract_epub_payload_from_epub(epub_binary: bytes) -> dict[str, object]:
    payload = _extract_epub_payload_via_spine(epub_binary)
    if payload is not None:
        return {
            "text_count": int(payload.get("text_count") or 0),
            "html_content": str(payload.get("html_content") or ""),
        }

    return _extract_epub_payload_via_zip_fallback(epub_binary)


async def _promote_product_price_type_to_paid(
    product_id: int, updated_id: int, db: AsyncSession
) -> None:
    query = text("""
        update tb_product
           set price_type = 'paid'
             , updated_id = :updated_id
         where product_id = :product_id
           and price_type = 'free'
    """)
    await db.execute(
        query,
        {
            "product_id": product_id,
            "updated_id": updated_id,
        },
    )


def _extract_text_count_from_epub(epub_binary: bytes) -> int:
    payload = _extract_epub_payload_from_epub(epub_binary)
    return int(payload.get("text_count") or 0)


def _extract_html_content_from_epub(epub_binary: bytes) -> str:
    """EPUB에서 본문 HTML을 추출한다."""
    payload = _extract_epub_payload_from_epub(epub_binary)
    return str(payload.get("html_content") or "")


async def _download_epub_binary_from_r2(
    file_group_id: int, db: AsyncSession
) -> Optional[bytes]:
    """R2에서 EPUB 바이너리를 다운로드한다. 실패 시 None."""
    query = text(
        """
        select b.file_name
          from tb_common_file a
          inner join tb_common_file_item b on a.file_group_id = b.file_group_id
           and b.use_yn = 'Y'
         where a.file_group_id = :file_group_id
           and a.group_type = 'epub'
           and a.use_yn = 'Y'
         limit 1
        """
    )
    result = await db.execute(query, {"file_group_id": file_group_id})
    row = result.mappings().first()

    if not row:
        return None

    file_name = row.get("file_name")
    if not file_name:
        return None

    presigned_url = comm_service.make_r2_presigned_url(
        type="download",
        bucket_name=settings.R2_SC_EPUB_BUCKET,
        file_id=file_name,
    )

    try:
        async with AsyncClient(timeout=60.0) as ac:
            response = await ac.get(url=presigned_url)
            response.raise_for_status()
        return response.content
    except (HTTPStatusError, RequestError) as e:
        logger.warning(
            "Failed to download epub. file_group_id=%s, reason=%s",
            file_group_id,
            str(e),
        )
        return None
    except Exception as e:
        logger.warning(
            "Unexpected error while downloading epub. file_group_id=%s, reason=%s",
            file_group_id,
            str(e),
        )
        return None


async def _get_episode_text_count_from_epub_file(
    file_group_id: int, db: AsyncSession
) -> int:
    epub_binary = await _download_epub_binary_from_r2(file_group_id, db)
    if epub_binary is None:
        return 0
    try:
        return _extract_text_count_from_epub(epub_binary)
    except (BadZipFile, ValueError) as e:
        logger.warning(
            "Failed to extract epub text count. file_group_id=%s, reason=%s",
            file_group_id,
            str(e),
        )
        return 0


async def _get_epub_cache_from_epub_files(
    file_group_ids: set[int], db: AsyncSession
) -> dict[int, dict]:
    """벌크 EPUB에서 text_count + html_content를 추출한다."""
    if not file_group_ids:
        return {}

    params = {}
    placeholders = []
    for idx, file_group_id in enumerate(sorted(file_group_ids)):
        key = f"file_group_id_{idx}"
        params[key] = file_group_id
        placeholders.append(f":{key}")
    in_clause = ", ".join(placeholders)

    query = text(
        f"""
        select a.file_group_id, b.file_name
          from tb_common_file a
          inner join tb_common_file_item b on a.file_group_id = b.file_group_id
           and b.use_yn = 'Y'
         where a.file_group_id in ({in_clause})
           and a.group_type = 'epub'
           and a.use_yn = 'Y'
        """
    )

    result = await db.execute(query, params)
    rows = result.mappings().all()

    file_name_by_group_id: dict[int, str] = {}
    for row in rows:
        file_group_id = int(row.get("file_group_id"))
        file_name = row.get("file_name")
        if file_name and file_group_id not in file_name_by_group_id:
            file_name_by_group_id[file_group_id] = file_name

    # TODO: cleaned garbled comment (encoding issue).
    for file_group_id in file_group_ids:
        if file_group_id not in file_name_by_group_id:
            raise CustomResponseException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                message=ErrorMessages.INVALID_EPISODE_INFO,
            )

    semaphore = asyncio.Semaphore(24)
    timeout = Timeout(connect=10.0, read=20.0, write=20.0, pool=20.0)

    async with AsyncClient(timeout=timeout) as ac:

        async def _extract(file_group_id: int, file_name: str) -> tuple[int, dict]:
            presigned_url = comm_service.make_r2_presigned_url(
                type="download",
                bucket_name=settings.R2_SC_EPUB_BUCKET,
                file_id=file_name,
            )
            try:
                async with semaphore:
                    response = await ac.get(url=presigned_url)
                    response.raise_for_status()
                epub_bytes = response.content
                epub_payload = await asyncio.to_thread(
                    _extract_epub_payload_from_epub, epub_bytes
                )
                return file_group_id, epub_payload
            except (HTTPStatusError, RequestError, BadZipFile, ValueError) as e:
                logger.warning(
                    "Failed to extract epub in batch. file_group_id=%s, reason=%s",
                    file_group_id,
                    str(e),
                )
                return file_group_id, {"text_count": 0, "html_content": ""}
            except Exception as e:
                logger.warning(
                    "Unexpected error while extracting epub in batch. file_group_id=%s, reason=%s",
                    file_group_id,
                    str(e),
                )
                return file_group_id, {"text_count": 0, "html_content": ""}

        results = await asyncio.gather(
            *[
                _extract(file_group_id=file_group_id, file_name=file_name)
                for file_group_id, file_name in file_name_by_group_id.items()
            ]
        )

    return {file_group_id: data for file_group_id, data in results}


async def _create_review_apply_for_episode_ids(
    episode_ids: list[int], req_user_id: int, db: AsyncSession
) -> list[int]:
    normalized_episode_ids = sorted({int(episode_id) for episode_id in episode_ids if episode_id})
    if not normalized_episode_ids:
        return []

    params = {}
    placeholders = []
    for idx, episode_id in enumerate(normalized_episode_ids):
        key = f"episode_id_{idx}"
        params[key] = episode_id
        placeholders.append(f":{key}")
    in_clause = ", ".join(placeholders)

    # 이미 심사중(review) 건이 있으면 중복 신청을 막는다.
    query = text(
        f"""
        select id
          from tb_product_episode_apply
         where episode_id in ({in_clause})
           and use_yn = 'Y'
           and status_code = 'review'
         limit 1
        """
    )
    result = await db.execute(query, params)
    if result.mappings().first():
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_APPLIED_STATE,
        )

    apply_ids: list[int] = []
    for episode_id in normalized_episode_ids:
        query = text(
            """
            insert into tb_product_episode_apply (
                episode_id, status_code, req_user_id, created_id, updated_id
            )
            values (
                :episode_id, :status_code, :req_user_id, :created_id, :updated_id
            )
            """
        )
        await db.execute(
            query,
            {
                "episode_id": episode_id,
                "status_code": "review",
                "req_user_id": req_user_id,
                "created_id": settings.DB_DML_DEFAULT_ID,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        query = text("select last_insert_id()")
        result = await db.execute(query)
        apply_ids.append(int(result.scalar()))

        query = text(
            """
            update tb_product_episode
               set open_yn = 'N',
                   updated_id = :updated_id
             where episode_id = :episode_id
               and use_yn = 'Y'
            """
        )
        await db.execute(
            query,
            {"episode_id": episode_id, "updated_id": req_user_id},
        )

    return apply_ids


async def get_episodes_episode_id(episode_id: str, kc_user_id: str, db: AsyncSession):
    res_data = {}
    episode_id_to_int = int(episode_id)

    if kc_user_id:
        try:
            liked = await check_like_product_episode(
                episode_id=episode_id_to_int, kc_user_id=kc_user_id, db=db
            )

            query = text("""
                                select user_id
                                from tb_user
                                where kc_user_id = :kc_user_id
                                and use_yn = 'Y'
                                """)

            result = await db.execute(query, {"kc_user_id": kc_user_id})
            db_rst = result.mappings().all()
            if not db_rst:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )
            user_id = db_rst[0].get("user_id")

            query = text("""
                                with tmp_get_episodes_episode_id_1 as (                                     
                                select 
                                    a.product_id
                                    , max(a.episode_no) as max_episode
                                    , b.title
                                    , b.thumbnail_file_id
                                from tb_product_episode a
                                    inner join tb_product b on a.product_id = b.product_id
                                where exists ( 
                                    select b.product_id from tb_product_episode b
                                    where b.episode_id = :episode_id
                                        and b.product_id = a.product_id 
                                )
                                and a.use_yn = 'Y'
                                and (a.open_yn = 'Y' OR a.episode_id = :episode_id
                                    OR EXISTS (
                                        select 1 from tb_user_productbook pb
                                        where (pb.episode_id = a.episode_id
                                               OR (pb.episode_id IS NULL
                                                   AND (pb.product_id = a.product_id
                                                        OR pb.product_id IS NULL)))
                                          AND pb.user_id = :user_id
                                          AND pb.use_yn = 'Y'
                                          AND (pb.rental_expired_date IS NULL OR pb.rental_expired_date > NOW())
                                    ))
                                group by a.product_id
                                ),
                                tmp_get_episodes_episode_id_2 as (
                                    select e.product_id
                                        , e.prev_episode_id
                                        , e.next_episode_id
                                    from (
                                        select q.product_id
                                            , q.episode_id
                                            , lag(q.episode_id, 1) over (partition by q.product_id order by q.episode_no) as prev_episode_id
                                            , lead(q.episode_id, 1) over (partition by q.product_id order by q.episode_no) as next_episode_id
                                            from tb_product_episode q
                                        where exists (select w.product_id from tb_product_episode w
                                                        where w.episode_id = :episode_id
                                                        and q.product_id = w.product_id)
                                            and q.use_yn = 'Y'
                                            and (q.open_yn = 'Y' OR q.episode_id = :episode_id
                                                OR EXISTS (
                                                    select 1 from tb_user_productbook pb
                                                    where (pb.episode_id = q.episode_id
                                                           OR (pb.episode_id IS NULL
                                                               AND (pb.product_id = q.product_id
                                                                    OR pb.product_id IS NULL)))
                                                      AND pb.user_id = :user_id
                                                      AND pb.use_yn = 'Y'
                                                      AND (pb.rental_expired_date IS NULL OR pb.rental_expired_date > NOW())
                                                ))
                                    ) e
                                    where e.episode_id = :episode_id
                                ),
                                tmp_get_episodes_episode_id_3 as (
                                    select user_id
                                    from tb_user_profile
                                    where user_id = :user_id
                                    and role_type = 'cp'
                                )
                                select a.product_id
                                    , e.title
                                    , IF(e.thumbnail_file_id IS NULL, NULL, (SELECT w.file_path FROM tb_common_file q, tb_common_file_item w
                                        WHERE q.file_group_id = w.file_group_id AND q.use_yn = 'Y' AND w.use_yn = 'Y'
                                        AND q.group_type = 'cover' AND q.file_group_id = e.thumbnail_file_id)) as cover_image_path
                                    , a.episode_title as episode_title
                                    , (select y.file_name from tb_common_file z, tb_common_file_item y
                                        where z.file_group_id = y.file_group_id
                                        and z.use_yn = 'Y'
                                        and y.use_yn = 'Y'
                                        and z.group_type = 'epub'
                                        and a.epub_file_id = z.file_group_id) as epub_file_name
                                    , a.count_comment
                                    , b.id as usage_id
                                    , coalesce(b.recommend_yn, 'N') as recommend_yn
                                    , coalesce(c.use_yn, 'N') as bookmark_yn
                                    , a.author_comment
                                    , case when d.eval_code is null then 'N'
                                            else 'Y'
                                    end as evaluation_yn
                                    , case when a.episode_no = e.max_episode then null
                                            else a.episode_no + 1
                                    end as next_episode
                                    , a.comment_open_yn
                                    , a.evaluation_open_yn
                                    , (select count(*) from tb_product_episode_like where episode_id = a.episode_id) as count_like
                                    , f.prev_episode_id
                                    , f.next_episode_id
                                    , a.price_type
                                    , a.open_yn
                                    , (select p.open_yn from tb_product p where p.product_id = a.product_id) as product_open_yn
                                    , (select p.author_id from tb_product p where p.product_id = a.product_id) as product_author_id
                                    , (select p.user_id from tb_product p where p.product_id = a.product_id) as product_user_id
                                    , (select own_type from tb_user_productbook where (
                                        episode_id = a.episode_id -- note: cleaned garbled comment (encoding issue)
                                        or
                                        (episode_id is null and (product_id = a.product_id or product_id is null)) -- note: cleaned garbled comment (encoding issue)
                                    ) and user_id = :user_id
                                    and use_yn = 'Y'
                                    and (own_type = 'own' or (own_type = 'rental' and (rental_expired_date IS NULL OR rental_expired_date > NOW())))
                                    order by case when own_type = 'own' then 0 else 1 end, id desc limit 1) as own_type
                                    , (select own_type from tb_user_productbook where (
                                        episode_id = f.prev_episode_id -- note: cleaned garbled comment (encoding issue)
                                        or
                                        (episode_id is null and (product_id = a.product_id or product_id is null)) -- note: cleaned garbled comment (encoding issue)
                                    ) and user_id = :user_id
                                    and use_yn = 'Y'
                                    and (own_type = 'own' or (own_type = 'rental' and (rental_expired_date IS NULL OR rental_expired_date > NOW())))
                                    order by case when own_type = 'own' then 0 else 1 end, id desc limit 1) as prev_own_type
                                    , (select own_type from tb_user_productbook where (
                                        episode_id = f.next_episode_id -- note: cleaned garbled comment (encoding issue)
                                        or
                                        (episode_id is null and (product_id = a.product_id or product_id is null)) -- note: cleaned garbled comment (encoding issue)
                                    ) and user_id = :user_id
                                    and use_yn = 'Y'
                                    and (own_type = 'own' or (own_type = 'rental' and (rental_expired_date IS NULL OR rental_expired_date > NOW())))
                                    order by case when own_type = 'own' then 0 else 1 end, id desc limit 1) as next_own_type
                                    , (select price_type from tb_product_episode where episode_id = f.prev_episode_id) as prev_price_type
                                    , (select price_type from tb_product_episode where episode_id = f.next_episode_id) as next_price_type
                                    , (select TIMESTAMPDIFF(SECOND, NOW(), rental_expired_date) from tb_user_productbook where (
                                        episode_id = f.prev_episode_id
                                        or
                                        (episode_id is null and (product_id = a.product_id or product_id is null))
                                    ) and user_id = :user_id
                                    and own_type = 'rental' and use_yn = 'Y'
                                    and rental_expired_date > NOW()
                                    order by id desc limit 1) as prev_rental_remaining
                                    , (select TIMESTAMPDIFF(SECOND, NOW(), rental_expired_date) from tb_user_productbook where (
                                        episode_id = f.next_episode_id
                                        or
                                        (episode_id is null and (product_id = a.product_id or product_id is null))
                                    ) and user_id = :user_id
                                    and own_type = 'rental' and use_yn = 'Y'
                                    and rental_expired_date > NOW()
                                    order by id desc limit 1) as next_rental_remaining
                                from tb_product_episode a
                                inner join tmp_get_episodes_episode_id_1 e on a.product_id = e.product_id
                                inner join tmp_get_episodes_episode_id_2 f on a.product_id = f.product_id
                                left join tb_user_product_usage b on a.product_id = b.product_id
                                    and a.episode_id = b.episode_id
                                    and b.use_yn = 'Y'
                                    and b.user_id = :user_id
                                left join tb_user_bookmark c on a.product_id = c.product_id
                                    and c.user_id = :user_id
                                left join tb_product_evaluation d on a.product_id = d.product_id
                                    and a.episode_id = d.episode_id
                                    and d.use_yn = 'Y'
                                    and d.user_id = :user_id                                    
                                left join tmp_get_episodes_episode_id_3 g on g.user_id = :user_id
                                where a.episode_id = :episode_id
                                and a.use_yn = 'Y'
                                """)

            result = await db.execute(
                query, {"user_id": user_id, "episode_id": episode_id_to_int}
            )
            db_rst = result.mappings().all()

            if db_rst:
                # 비공개 에피소드: 소유/대여 중이 아니면 접근 차단 (작품 소유자는 예외)
                episode_open_yn = db_rst[0].get("open_yn", "Y")
                episode_own_type = db_rst[0].get("own_type")
                product_open_yn = db_rst[0].get("product_open_yn", "Y")
                product_author_id = db_rst[0].get("product_author_id")
                product_user_id = db_rst[0].get("product_user_id")
                is_owner = (product_author_id is not None and product_author_id == user_id) or \
                           (product_user_id is not None and product_user_id == user_id)
                if not is_owner and (product_open_yn == "N" or (episode_open_yn == "N" and not episode_own_type)):
                    res_data = {
                        "product_id": db_rst[0].get("product_id"),
                        "title": db_rst[0].get("title"),
                        "episodeTitle": db_rst[0].get("episode_title"),
                        "privateYn": "Y",
                        "productPrivateYn": "Y" if product_open_yn == "N" else "N",
                    }
                else:
                    epub_file_path = comm_service.make_r2_presigned_url(
                        type="download",
                        bucket_name=settings.R2_SC_EPUB_BUCKET,
                        file_id=db_rst[0].get("epub_file_name"),
                    )

                    product_id = db_rst[0].get("product_id")
                    try:
                        usage_id = db_rst[0].get("usage_id")
                    except Exception:
                        usage_id = None

                    is_private = episode_open_yn == "N"

                    res_data = {
                        "product_id": product_id,
                        "title": db_rst[0].get("title"),
                        "coverImagePath": db_rst[0].get("cover_image_path"),
                        "episodeTitle": db_rst[0].get("episode_title"),
                        "epubFilePath": epub_file_path,
                        "privateYn": "Y" if is_private else "N",
                        "productPrivateYn": "Y" if product_open_yn == "N" else "N",
                        "bingeWatchYn": "N",  # TODO: cleaned garbled comment (encoding issue).
                        "commentCount": db_rst[0].get("count_comment"),
                        "likeCount": db_rst[0].get("count_like"),
                        "liked": "Y" if liked else "N",
                        "recommendYn": db_rst[0].get("recommend_yn"),
                        "bookmarkYn": db_rst[0].get("bookmark_yn"),
                        "authorComment": db_rst[0].get("author_comment"),
                        "evaluationYn": db_rst[0].get("evaluation_yn"),
                        "nextEpisodes": db_rst[0].get("next_episode"),
                        "commentOpenYn": db_rst[0].get("comment_open_yn"),
                        "evaluationOpenYn": db_rst[0].get("evaluation_open_yn"),
                        "previousEpisodeId": db_rst[0].get("prev_episode_id"),
                        "nextEpisodeId": db_rst[0].get("next_episode_id"),
                        "priceType": db_rst[0].get("price_type"),
                        "ownType": db_rst[0].get("own_type")
                        if db_rst[0].get("own_type")
                        else None,
                        "previousEpisodeOwnType": db_rst[0].get("prev_own_type")
                        if db_rst[0].get("prev_own_type")
                        else None,
                        "nextEpisodeOwnType": db_rst[0].get("next_own_type")
                        if db_rst[0].get("next_own_type")
                        else None,
                        "previousEpisodePriceType": db_rst[0].get("prev_price_type"),
                        "nextEpisodePriceType": db_rst[0].get("next_price_type"),
                        "previousEpisodeRentalRemaining": db_rst[0].get(
                            "prev_rental_remaining"
                        ),
                        "nextEpisodeRentalRemaining": db_rst[0].get(
                            "next_rental_remaining"
                        ),
                    }

                    if usage_id is not None:
                        query = text("""
                                            update tb_user_product_usage
                                            set updated_id = :user_id
                                            where id = :id
                                            """)

                        await db.execute(query, {"id": usage_id, "user_id": user_id})
                    else:
                        query = text("""
                                            insert into tb_user_product_usage (user_id, product_id, episode_id, created_id, updated_id)
                                            values (:user_id, :product_id, :episode_id, :created_id, :updated_id)
                                            """)

                        await db.execute(
                            query,
                            {
                                "user_id": user_id,
                                "product_id": product_id,
                                "episode_id": episode_id_to_int,
                                "created_id": settings.DB_DML_DEFAULT_ID,
                                "updated_id": settings.DB_DML_DEFAULT_ID,
                            },
                        )

                    query = text("""
                                        select 1
                                        from tb_user_profile
                                        where user_id = :user_id
                                        and role_type = 'cp'
                                        """)

                    result = await db.execute(query, {"user_id": user_id})
                    db_rst = result.mappings().all()

                    cp_yn = CommonConstants.YES if db_rst else CommonConstants.NO

                    query = text("""
                                        update tb_product_episode
                                        set count_hit = count_hit + 1
                                        where episode_id = :episode_id
                                        """)

                    await db.execute(query, {"episode_id": episode_id_to_int})

                    query = text("""
                                        update tb_product
                                        set count_hit = count_hit + 1
                                            , count_cp_hit = (case when :cp_yn = 'Y' then count_cp_hit + 1 else count_cp_hit end)
                                        where product_id = :product_id
                                        """)

                    await db.execute(query, {"product_id": product_id, "cp_yn": cp_yn})

                    await product_service.save_product_hit_log(product_id=product_id, db=db)

                    try:
                        await event_reward_service.check_and_grant_event_reward(
                            event_type="view-3-times", user_id=user_id, product_id=product_id, db=db
                        )
                    except Exception as e:
                        logger.error(f"Event reward check failed: {e}")

            else:
                logger.warning("db_rst is None")

            await statistics_service.insert_site_statistics_log(
                db=db, type="visit", user_id=user_id
            )
            await statistics_service.insert_site_statistics_log(
                db=db, type="page_view", user_id=user_id
            )
        except OperationalError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message=ErrorMessages.DB_CONNECTION_ERROR,
            )
        except SQLAlchemyError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.DB_OPERATION_ERROR,
            )
        except CustomResponseException:
            raise
        except Exception as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        try:
            # 비로그인 유저: 비공개 회차/작품 사전 체크
            private_check_query = text("""
                select e.open_yn as episode_open_yn,
                       (select p.open_yn from tb_product p where p.product_id = e.product_id) as product_open_yn,
                       e.product_id,
                       (select z.title from tb_product z where z.product_id = e.product_id) as title,
                       e.episode_title as episode_title
                from tb_product_episode e
                where e.episode_id = :episode_id and e.use_yn = 'Y'
            """)
            private_check_result = await db.execute(private_check_query, {"episode_id": episode_id_to_int})
            private_check_row = private_check_result.mappings().first()

            if private_check_row:
                ep_open = private_check_row.get("episode_open_yn", "Y")
                pd_open = private_check_row.get("product_open_yn", "Y")
                if ep_open == "N" or pd_open == "N":
                    res_data = {
                        "product_id": private_check_row.get("product_id"),
                        "title": private_check_row.get("title"),
                        "episodeTitle": private_check_row.get("episode_title"),
                        "privateYn": "Y",
                        "productPrivateYn": "Y" if pd_open == "N" else "N",
                    }
                    return {"data": res_data}

            query = text("""
                                with tmp_get_episodes_episode_id_1 as (
                                    select product_id
                                        , max(episode_no) as max_episode
                                    from tb_product_episode
                                    where product_id in (select product_id from tb_product_episode
                                                        where episode_id = :episode_id)
                                    and use_yn = 'Y'
                                    and open_yn = 'Y'
                                    group by product_id
                                ),
                                tmp_get_episodes_episode_id_2 as (
                                    select e.product_id
                                        , e.prev_episode_id
                                        , e.next_episode_id
                                    from (
                                        select q.product_id
                                            , q.episode_id
                                            , lag(q.episode_id, 1) over (partition by q.product_id order by q.episode_no) as prev_episode_id
                                            , lead(q.episode_id, 1) over (partition by q.product_id order by q.episode_no) as next_episode_id
                                            from tb_product_episode q
                                        where q.product_id in (select w.product_id from tb_product_episode w
                                                                where w.episode_id = :episode_id)
                                            and q.use_yn = 'Y'
                                            and q.open_yn = 'Y'
                                    ) e
                                    where e.episode_id = :episode_id
                                )
                                select a.product_id
                                    , a.episode_no
                                    , (select z.title from tb_product z
                                        where z.product_id = a.product_id) as title
                                    , (SELECT w.file_path FROM tb_common_file q, tb_common_file_item w
                                        WHERE q.file_group_id = w.file_group_id AND q.use_yn = 'Y' AND w.use_yn = 'Y'
                                        AND q.group_type = 'cover'
                                        AND q.file_group_id = (SELECT thumbnail_file_id FROM tb_product WHERE product_id = a.product_id)) as cover_image_path
                                    , a.episode_title as episode_title
                                    , (select y.file_name from tb_common_file z, tb_common_file_item y
                                        where z.file_group_id = y.file_group_id
                                        and z.use_yn = 'Y'
                                        and y.use_yn = 'Y'
                                        and z.group_type = 'epub'
                                        and a.epub_file_id = z.file_group_id) as epub_file_name
                                    , a.count_comment
                                    , a.author_comment
                                    , case when a.episode_no = b.max_episode then null
                                            else a.episode_no + 1
                                    end as next_episode
                                    , (select count(*) from tb_product_episode_like where episode_id = a.episode_id) as count_like
                                    , a.comment_open_yn
                                    , a.evaluation_open_yn
                                    , c.prev_episode_id
                                    , c.next_episode_id
                                    , a.price_type
                                    , (select price_type from tb_product_episode where episode_id = c.prev_episode_id) as prev_price_type
                                    , (select price_type from tb_product_episode where episode_id = c.next_episode_id) as next_price_type
                                from tb_product_episode a
                                inner join tmp_get_episodes_episode_id_1 b on a.product_id = b.product_id
                                inner join tmp_get_episodes_episode_id_2 c on a.product_id = c.product_id
                                where a.episode_id = :episode_id
                                and a.use_yn = 'Y'
                                """)

            result = await db.execute(query, {"episode_id": episode_id_to_int})
            db_rst = result.mappings().all()

            if db_rst:
                if (db_rst[0].get("episode_no") or 0) > 5:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                epub_file_path = comm_service.make_r2_presigned_url(
                    type="download",
                    bucket_name=settings.R2_SC_EPUB_BUCKET,
                    file_id=db_rst[0].get("epub_file_name"),
                )

                res_data = {
                    "product_id": db_rst[0].get("product_id"),
                    "title": db_rst[0].get("title"),
                    "coverImagePath": db_rst[0].get("cover_image_path"),
                    "episodeTitle": db_rst[0].get("episode_title"),
                    "epubFilePath": epub_file_path,
                    "bingeWatchYn": "N",  # TODO: cleaned garbled comment (encoding issue).
                    "commentCount": db_rst[0].get("count_comment"),
                    "likeCount": db_rst[0].get("count_like"),
                    "liked": "N",
                    "recommendYn": "N",
                    "bookmarkYn": "N",
                    "authorComment": db_rst[0].get("author_comment"),
                    "evaluationYn": "N",
                    "nextEpisodes": db_rst[0].get("next_episode"),
                    "commentOpenYn": db_rst[0].get("comment_open_yn"),
                    "evaluationOpenYn": db_rst[0].get("evaluation_open_yn"),
                    "previousEpisodeId": db_rst[0].get(
                        "prev_episode_id"
                    ),  # TODO: cleaned garbled comment (encoding issue).
                    "nextEpisodeId": db_rst[0].get(
                        "next_episode_id"
                    ),  # TODO: cleaned garbled comment (encoding issue).
                    "priceType": db_rst[0].get("price_type"),
                    "ownType": None,
                    "previousEpisodeOwnType": None,
                    "nextEpisodeOwnType": None,
                    "previousEpisodePriceType": db_rst[0].get("prev_price_type"),
                    "nextEpisodePriceType": db_rst[0].get("next_price_type"),
                    "previousEpisodeRentalRemaining": None,
                    "nextEpisodeRentalRemaining": None,
                }

                # TODO: cleaned garbled comment (encoding issue).
                query = text("""
                                    update tb_product_episode
                                    set count_hit = count_hit + 1
                                    where episode_id = :episode_id
                                    """)

                await db.execute(query, {"episode_id": episode_id_to_int})
            else:
                logger.warning("db_rst is None")

            await statistics_service.insert_site_statistics_log(
                db=db, type="visit", user_id=None
            )
            await statistics_service.insert_site_statistics_log(
                db=db, type="page_view", user_id=None
            )
        except OperationalError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message=ErrorMessages.DB_CONNECTION_ERROR,
            )
        except SQLAlchemyError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.DB_OPERATION_ERROR,
            )
        except CustomResponseException:
            raise
        except Exception as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    res_body = {"data": res_data}

    return res_body


async def get_episodes_episode_upload_file_name(
    file_name: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}

    if kc_user_id:
        try:

            # TODO: cleaned garbled comment (encoding issue).
            while True:
                file_name_to_uuid = comm_service.make_rand_uuid()
                file_name_to_uuid = f"{file_name_to_uuid}.webp"

                query = text("""
                                    select a.file_group_id
                                    from tb_common_file a
                                    inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                    and b.use_yn = 'Y'
                                    and b.file_name = :file_name
                                    where a.group_type = 'episode'
                                    and a.use_yn = 'Y'
                                """)

                result = await db.execute(query, {"file_name": file_name_to_uuid})
                db_rst = result.mappings().all()

                if not db_rst:
                    break

            presigned_url = comm_service.make_r2_presigned_url(
                type="upload",
                bucket_name=settings.R2_SC_IMAGE_BUCKET,
                file_id=f"episode/{file_name_to_uuid}",
            )

            query = text("""
                                insert into tb_common_file (group_type, created_id, updated_id)
                                values (:group_type, :created_id, :updated_id)
                                """)

            await db.execute(
                query,
                {
                    "group_type": "episode",
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            query = text("""
                                select last_insert_id()
                                """)

            result = await db.execute(query)
            new_file_group_id = result.scalar()

            query = text("""
                                insert into tb_common_file_item (file_group_id, file_name, file_org_name, file_path, created_id, updated_id)
                                values (:file_group_id, :file_name, :file_org_name, :file_path, :created_id, :updated_id)
                                """)

            await db.execute(
                query,
                {
                    "file_group_id": new_file_group_id,
                    "file_name": file_name_to_uuid,
                    "file_org_name": file_name,
                    "file_path": f"{settings.R2_SC_CDN_URL}/episode/{file_name_to_uuid}",
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            res_data = {
                "episodeImageFileId": new_file_group_id,
                "episodeImageUploadPath": presigned_url,
            }
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
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


async def get_episodes_episode_download_episode_image_file_id(
    episode_image_file_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    episode_image_file_id_to_int = int(episode_image_file_id)

    if kc_user_id:
        try:
            user_id = await comm_service.get_user_from_kc(kc_user_id, db)
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )

            query = text("""
                                select b.file_path
                                from tb_common_file a
                                inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                and b.use_yn = 'Y'
                                where a.use_yn = 'Y'
                                and a.group_type = 'episode'
                                and a.file_group_id = :file_group_id
                                """)

            result = await db.execute(
                query, {"file_group_id": episode_image_file_id_to_int}
            )
            db_rst = result.mappings().all()

            if db_rst:
                res_data = {
                    "episodeImageFileId": episode_image_file_id_to_int,
                    "episodeImageDownloadPath": db_rst[0].get("file_path"),
                }
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
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


async def get_episodes_episode_id_info(
    episode_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    episode_id_to_int = int(episode_id)

    if kc_user_id:
        try:
            liked = await check_like_product_episode(
                episode_id=episode_id_to_int, kc_user_id=kc_user_id, db=db
            )

            user_id = await comm_service.get_user_from_kc(kc_user_id, db)
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )

            # TODO: cleaned garbled comment (encoding issue).
            check_query = text("""
                                select a.episode_id
                                    , a.use_yn
                                from tb_product_episode a
                                where a.episode_id = :episode_id
                                """)

            check_result = await db.execute(
                check_query, {"episode_id": episode_id_to_int}
            )
            check_row = check_result.mappings().one_or_none()

            if not check_row:
                # TODO: cleaned garbled comment (encoding issue).
                raise CustomResponseException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=ErrorMessages.NOT_FOUND_EPISODE,
                )

            if check_row["use_yn"] == "N":
                # TODO: cleaned garbled comment (encoding issue).
                raise CustomResponseException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=ErrorMessages.DELETED_EPISODE,
                )

            query = text("""
                                select a.episode_id
                                    , a.episode_title as title
                                    , a.episode_content as content
                                    , a.author_comment
                                    , a.evaluation_open_yn
                                    , a.comment_open_yn
                                    , a.open_yn as episode_open_yn
                                    , case when a.publish_reserve_date is null then 'N'
                                            else 'Y'
                                    end as reserve_yn
                                    , a.publish_reserve_date
                                    , a.price_type
                                    , (select count(*) from tb_product_episode_like where episode_id = a.episode_id) as count_like
                                from tb_product_episode a
                                inner join tb_product b on a.product_id = b.product_id
                                and b.user_id = :user_id
                                where a.episode_id = :episode_id
                                and use_yn = 'Y'
                                """)

            result = await db.execute(
                query, {"user_id": user_id, "episode_id": episode_id_to_int}
            )
            db_rst = result.mappings().all()

            if db_rst:
                res_data = {
                    "episodeId": episode_id_to_int,
                    "title": db_rst[0].get("title"),
                    "content": db_rst[0].get("content"),
                    "authorComment": db_rst[0].get("author_comment"),
                    "evaluationOpenYn": db_rst[0].get("evaluation_open_yn"),
                    "commentOpenYn": db_rst[0].get("comment_open_yn"),
                    "episodeOpenYn": db_rst[0].get("episode_open_yn"),
                    "publishReserveYn": db_rst[0].get("reserve_yn"),
                    "publishReserveDate": db_rst[0].get("publish_reserve_date"),
                    "priceType": db_rst[0].get("price_type"),
                    "likeCount": db_rst[0].get("count_like"),
                    "liked": "Y" if liked else "N",
                }
        except CustomResponseException as e:
            logger.error(e, exc_info=True)
            raise
        except OperationalError as e:
            logger.error(e, exc_info=True)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message=ErrorMessages.DB_CONNECTION_ERROR,
            )
        except SQLAlchemyError as e:
            logger.error(e, exc_info=True)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.DB_OPERATION_ERROR,
            )
        except Exception as e:
            logger.error(e, exc_info=True)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        try:
            # TODO: cleaned garbled comment (encoding issue).
            check_query = text("""
                                select a.episode_id
                                    , a.use_yn
                                from tb_product_episode a
                                where a.episode_id = :episode_id
                                """)

            check_result = await db.execute(
                check_query, {"episode_id": episode_id_to_int}
            )
            check_row = check_result.mappings().one_or_none()

            if not check_row:
                # TODO: cleaned garbled comment (encoding issue).
                raise CustomResponseException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=ErrorMessages.NOT_FOUND_EPISODE,
                )

            if check_row["use_yn"] == "N":
                # TODO: cleaned garbled comment (encoding issue).
                raise CustomResponseException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=ErrorMessages.DELETED_EPISODE,
                )

            query = text("""
                                select a.episode_id
                                    , a.episode_title as title
                                    , a.episode_content as content
                                    , a.author_comment
                                    , a.evaluation_open_yn
                                    , a.comment_open_yn
                                    , a.open_yn as episode_open_yn
                                    , case when a.publish_reserve_date is null then 'N'
                                            else 'Y'
                                    end as reserve_yn
                                    , a.publish_reserve_date
                                    , a.price_type
                                    , (select count(*) from tb_product_episode_like where episode_id = a.episode_id) as count_like
                                from tb_product_episode a
                                inner join tb_product b on a.product_id = b.product_id
                                where a.episode_id = :episode_id
                                and a.use_yn = 'Y'
                                """)
            result = await db.execute(query, {"episode_id": episode_id_to_int})
            db_rst = result.mappings().all()
            if db_rst:
                res_data = {
                    "episodeId": episode_id_to_int,
                    "title": db_rst[0].get("title"),
                    "content": db_rst[0].get("content"),
                    "authorComment": db_rst[0].get("author_comment"),
                    "evaluationOpenYn": db_rst[0].get("evaluation_open_yn"),
                    "commentOpenYn": db_rst[0].get("comment_open_yn"),
                    "episodeOpenYn": db_rst[0].get("episode_open_yn"),
                    "publishReserveYn": db_rst[0].get("reserve_yn"),
                    "publishReserveDate": db_rst[0].get("publish_reserve_date"),
                    "priceType": db_rst[0].get("price_type"),
                    "likeCount": db_rst[0].get("count_like"),
                    "liked": "N",
                }
        except OperationalError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    res_body = {"data": res_data}

    return res_body


async def get_episodes_products_product_id_info(
    product_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    product_id_to_int = int(product_id)

    if kc_user_id:
        try:
            user_id = await comm_service.get_user_from_kc(kc_user_id, db)
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )

            query = text("""
                                select a.title
                                from tb_product a
                                where a.product_id = :product_id
                                """)

            result = await db.execute(query, {"product_id": product_id_to_int})
            db_rst = result.mappings().all()

            if db_rst:
                title = db_rst[0].get("title")

                query = text("""
                                    with tmp_get_episodes_products_product_id_info as (
                                        select product_id
                                            , max(episode_no) as max_episode
                                        from tb_product_episode
                                        where product_id = :product_id
                                        and use_yn = 'Y'
                                        group by product_id
                                    )
                                    select concat(a.episode_no, '화. ', a.episode_title) as episode_title
                                    from tb_product_episode a
                                    inner join tmp_get_episodes_products_product_id_info b on a.product_id = b.product_id
                                    and a.episode_no = b.max_episode
                                    """)

                result = await db.execute(query, {"product_id": product_id_to_int})
                db_rst = result.mappings().all()

                if db_rst:
                    res_data = {
                        "title": title,
                        "episodeTitle": db_rst[0].get("episode_title"),
                    }
                else:
                    res_data = {"title": title, "episodeTitle": None}
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
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


async def post_episodes_products_product_id(
    product_id: str,
    req_body: episode_schema.PostEpisodesProductsProductIdReqBody,
    kc_user_id: str,
    db: AsyncSession,
    save: Optional[str] = None,
    episode_id: Optional[str] = None,
):
    res_data = {}
    try:
        product_id_to_int = int(product_id)
        episode_id_to_int = int(episode_id) if episode_id else None
    except (TypeError, ValueError):
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=ErrorMessages.INVALID_EPISODE_INFO,
        )

    if kc_user_id:
        try:
            async with _transaction_scope(db):
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                # TODO: cleaned garbled comment (encoding issue).
                if episode_id_to_int is None:
                    duplicate_check_query = text("""
                        SELECT COUNT(*) as cnt FROM tb_product_episode
                        WHERE product_id = :product_id
                          AND episode_title = :episode_title
                          AND created_date > DATE_SUB(NOW(), INTERVAL 10 SECOND)
                    """)
                    duplicate_result = await db.execute(
                        duplicate_check_query,
                        {"product_id": product_id_to_int, "episode_title": req_body.title}
                    )
                    duplicate_count = duplicate_result.scalar()
                    if duplicate_count > 0:
                        raise CustomResponseException(
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            message=ErrorMessages.DUPLICATE_EPISODE_CREATION,
                        )

                # TODO: cleaned garbled comment (encoding issue).
                query = text("""
                                 select price_type
                                      , paid_open_date
                                      , paid_episode_no
                                      , coalesce(series_regular_price, 0) as series_regular_price
                                      , coalesce(single_regular_price, 0) as single_regular_price
                                   from tb_product
                                  where user_id = :user_id
                                    and product_id = :product_id
                                  for update
                                 """)

                result = await db.execute(
                    query, {"user_id": user_id, "product_id": product_id_to_int}
                )
                db_rst = result.mappings().all()

                if db_rst:
                    product_price_type = db_rst[0]["price_type"]
                    paid_open_date = db_rst[0].get("paid_open_date")
                    paid_episode_no = db_rst[0].get("paid_episode_no")
                    series_regular_price = int(
                        db_rst[0].get("series_regular_price") or 0
                    )
                    single_regular_price = int(
                        db_rst[0].get("single_regular_price") or 0
                    )
                    is_paid_product = (
                        product_price_type == "paid"
                        or series_regular_price > 0
                        or single_regular_price > 0
                    )
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                # TODO: cleaned garbled comment (encoding issue).
                price_type = None
                if req_body.price_type is None or req_body.price_type == "":
                    pass
                else:
                    query = text("""
                                     select 1
                                       from tb_common_code
                                      where code_group = 'PROD_PRICE_TYPE'
                                        and code_key = :code_key
                                        and use_yn = 'Y'
                                     """)

                    result = await db.execute(query, {"code_key": req_body.price_type})
                    db_rst = result.mappings().all()

                    if db_rst:
                        price_type = req_body.price_type
                    else:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                # TODO: cleaned garbled comment (encoding issue).
                if price_type == "paid" and product_price_type != "paid":
                    raise CustomResponseException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message=ErrorMessages.FREE_PRODUCT_CANNOT_CREATE_PAID_EPISODE,
                    )

                # TODO: cleaned garbled comment (encoding issue).
                try:
                    soup = BeautifulSoup(req_body.content, "html.parser")
                    text_content = soup.get_text(separator=" ", strip=True)  # TODO: cleaned garbled comment (encoding issue).
                except Exception:
                    # TODO: cleaned garbled comment (encoding issue).
                    text_content = req_body.content

                if len(text_content) > 20000:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                # TODO: cleaned garbled comment (encoding issue).
                if req_body.author_comment is None or req_body.author_comment == "":
                    pass
                else:
                    if len(req_body.author_comment) > 2000:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                # 저장 버튼 클릭시 회차목록에 비공개 회차로 등록
                if save == "Y":
                    open_yn = "N"
                elif save == "N":
                    # 예약 공개 설정 시 즉시 공개되지 않도록 강제 비공개
                    open_yn = (
                        "N"
                        if req_body.publish_reserve_yn == "Y"
                        else req_body.episode_open_yn
                    )
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                query = text("""
                                 select coalesce(a.price_type, 'free') as episode_price_type
                                      , a.episode_no
                                   from tb_product_episode a
                                  inner join tb_product b on a.product_id = b.product_id
                                    and b.user_id = :user_id
                                  where a.episode_id = :episode_id
                                 """)

                result = await db.execute(
                    query, {"user_id": user_id, "episode_id": episode_id_to_int}
                )
                db_rst = result.mappings().all()

                if db_rst:
                    current_episode_price_type = db_rst[0].get("episode_price_type") or "free"

                    if price_type is None:
                        # Keep persisted value on save/edit flow when price_type is omitted.
                        price_type = current_episode_price_type

                    # TODO: cleaned garbled comment (encoding issue).
                    if price_type == "paid" and not is_paid_product:
                        raise CustomResponseException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            message=ErrorMessages.FREE_PRODUCT_CANNOT_CREATE_PAID_EPISODE,
                        )

                    query = text("""
                                     update tb_product_episode a
                                        set a.price_type = :price_type
                                          , a.episode_title = :episode_title
                                          , a.episode_text_count = :episode_text_count
                                          , a.episode_content = :episode_content
                                          , a.author_comment = :author_comment
                                          , a.comment_open_yn = :comment_open_yn
                                          , a.evaluation_open_yn = :evaluation_open_yn
                                          , a.publish_reserve_date = :publish_reserve_date
                                          , a.open_yn = :open_yn
                                          , a.updated_id = :user_id
                                      where a.episode_id = :episode_id
                                     """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "episode_id": episode_id_to_int,
                            "price_type": price_type,
                            "episode_title": req_body.title,
                            "episode_text_count": len(text_content),
                            "episode_content": req_body.content,
                            "author_comment": req_body.author_comment,
                            "comment_open_yn": req_body.comment_open_yn,
                            "evaluation_open_yn": req_body.evaluation_open_yn,
                            "publish_reserve_date": _normalize_publish_reserve_datetime(
                                req_body.publish_reserve_date
                            )
                            if req_body.publish_reserve_yn == "Y"
                            else None,
                            "open_yn": open_yn,
                        },
                    )

                    res_data = {"episodeId": episode_id_to_int}

                    tmp_episode_id = episode_id_to_int
                else:
                    # ins
                    query = text("""
                                     select product_id
                                          , max(episode_no) as max_episode_no
                                       from tb_product_episode
                                      where product_id = :product_id
                                        and use_yn = 'Y'
                                      group by product_id
                                     """)

                    result = await db.execute(query, {"product_id": product_id_to_int})
                    db_rst = result.mappings().all()

                    if db_rst:
                        next_episode_no = db_rst[0].get("max_episode_no") + 1
                    else:
                        next_episode_no = 1

                    if price_type is None:
                        price_type = _default_episode_price_type(
                            is_paid_product=is_paid_product,
                            paid_open_date=paid_open_date,
                            paid_episode_no=paid_episode_no,
                            episode_no=next_episode_no,
                        )

                    query = text("""
                                     insert into tb_product_episode (product_id, price_type, episode_no, episode_title, episode_text_count, episode_content, author_comment, comment_open_yn, evaluation_open_yn, publish_reserve_date, open_yn, created_id, updated_id)
                                     values (:product_id, :price_type, :episode_no, :episode_title, :episode_text_count, :episode_content, :author_comment, :comment_open_yn, :evaluation_open_yn, :publish_reserve_date, :open_yn, :created_id, :updated_id)
                                     """)

                    await db.execute(
                        query,
                        {
                            "product_id": product_id_to_int,
                            "price_type": price_type,
                            "episode_no": next_episode_no,
                            "episode_title": req_body.title,
                            "episode_text_count": len(text_content),
                            "episode_content": req_body.content,
                            "author_comment": req_body.author_comment,
                            "comment_open_yn": req_body.comment_open_yn,
                            "evaluation_open_yn": req_body.evaluation_open_yn,
                            "publish_reserve_date": _normalize_publish_reserve_datetime(
                                req_body.publish_reserve_date
                            )
                            if req_body.publish_reserve_yn == "Y"
                            else None,
                            "open_yn": open_yn,
                            "created_id": settings.DB_DML_DEFAULT_ID,
                            "updated_id": settings.DB_DML_DEFAULT_ID,
                        },
                    )

                    query = text("""
                                     select last_insert_id()
                                     """)

                    result = await db.execute(query)
                    new_episode_id = result.scalar()

                    res_data = {"episodeId": new_episode_id}

                    tmp_episode_id = new_episode_id

                if (
                    price_type == "paid"
                    and product_price_type != "paid"
                    and open_yn == "Y"
                    and req_body.publish_reserve_yn == "N"
                ):
                    await _promote_product_price_type_to_paid(
                        product_id=product_id_to_int,
                        updated_id=user_id,
                        db=db,
                    )
                    product_price_type = "paid"

                # last_episode_date upd
                if open_yn == "Y" and req_body.publish_reserve_yn == "N":
                    query = text("""
                                     update tb_product
                                        set last_episode_date = now()
                                      where product_id = :product_id
                                     """)

                    await db.execute(query, {"product_id": product_id_to_int})

                # TODO: cleaned garbled comment (encoding issue).
                query = text(f"""
                                 select {get_file_path_sub_query("b.thumbnail_file_id", "cover_image_path", "cover")}
                                      , concat(a.episode_no, '화. ', a.episode_title) as episode_title
                                      , a.episode_content
                                      , a.epub_file_id
                                   from tb_product_episode a
                                  inner join tb_product b on a.product_id = b.product_id
                                  where episode_id = :episode_id
                                 """)

                result = await db.execute(query, {"episode_id": tmp_episode_id})
                db_rst = result.mappings().all()

                if db_rst:
                    cover_image_path = db_rst[0].get("cover_image_path")
                    episode_title = db_rst[0].get("episode_title")
                    episode_content = db_rst[0].get("episode_content")
                    epub_file_id = db_rst[0].get("epub_file_id")

                    file_org_name = f"{str(tmp_episode_id)}.epub"

                    # TODO: cleaned garbled comment (encoding issue).
                    await comm_service.make_epub(
                        file_org_name=file_org_name,
                        cover_image_path=cover_image_path,
                        episode_title=episode_title,
                        content_db=episode_content,
                    )

                    if epub_file_id is None:
                        # ins
                        # TODO: cleaned garbled comment (encoding issue).
                        while True:
                            file_name_to_uuid = comm_service.make_rand_uuid()
                            file_name_to_uuid = f"{file_name_to_uuid}.epub"

                            query = text("""
                                             select a.file_group_id
                                               from tb_common_file a
                                              inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                                and b.use_yn = 'Y'
                                                and b.file_name = :file_name
                                              where a.group_type = 'epub'
                                                and a.use_yn = 'Y'
                                            """)

                            result = await db.execute(
                                query, {"file_name": file_name_to_uuid}
                            )
                            db_rst = result.mappings().all()

                            if not db_rst:
                                break

                        query = text("""
                                         insert into tb_common_file (group_type, created_id, updated_id)
                                         values (:group_type, :created_id, :updated_id)
                                         """)

                        await db.execute(
                            query,
                            {
                                "group_type": "epub",
                                "created_id": settings.DB_DML_DEFAULT_ID,
                                "updated_id": settings.DB_DML_DEFAULT_ID,
                            },
                        )

                        query = text("""
                                         select last_insert_id()
                                         """)

                        result = await db.execute(query)
                        new_file_group_id = result.scalar()

                        query = text("""
                                         insert into tb_common_file_item (file_group_id, file_name, file_org_name, file_path, created_id, updated_id)
                                         values (:file_group_id, :file_name, :file_org_name, :file_path, :created_id, :updated_id)
                                         """)

                        await db.execute(
                            query,
                            {
                                "file_group_id": new_file_group_id,
                                "file_name": file_name_to_uuid,
                                "file_org_name": file_org_name,
                                "file_path": f"{settings.R2_SC_DOMAIN}/epub/{file_name_to_uuid}",
                                "created_id": settings.DB_DML_DEFAULT_ID,
                                "updated_id": settings.DB_DML_DEFAULT_ID,
                            },
                        )

                        epub_file_id = new_file_group_id
                    else:
                        # upd
                        query = text("""
                                         select b.file_name
                                           from tb_common_file a
                                          inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                            and b.use_yn = 'Y'
                                          where a.group_type = 'epub'
                                            and a.use_yn = 'Y'
                                            and a.file_group_id = :epub_file_id
                                        """)

                        result = await db.execute(query, {"epub_file_id": epub_file_id})
                        db_rst = result.mappings().all()

                        if db_rst:
                            file_name_to_uuid = db_rst[0].get("file_name")

                    presigned_url = comm_service.make_r2_presigned_url(
                        type="upload",
                        bucket_name=settings.R2_SC_EPUB_BUCKET,
                        file_id=file_name_to_uuid,
                    )

                    # TODO: cleaned garbled comment (encoding issue).
                    await comm_service.upload_epub_to_r2(
                        url=presigned_url, file_name=file_org_name
                    )

                    query = text("""
                                     update tb_product_episode a
                                        set a.epub_file_id = :epub_file_id
                                          , a.updated_id = :user_id
                                      where a.episode_id = :episode_id
                                     """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "episode_id": tmp_episode_id,
                            "epub_file_id": epub_file_id,
                        },
                    )
        except CustomResponseException as e:
            logger.error(e)
            raise
        except OperationalError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.error(e)
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


async def post_episodes_products_product_id_epub(
    product_id: str,
    req_body: episode_schema.PostEpisodesProductsProductIdEpubReqBody,
    kc_user_id: str,
    db: AsyncSession,
    save: Optional[str] = None,
):
    res_data = {}
    product_id_to_int = int(product_id)

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                # TODO: cleaned garbled comment (encoding issue).
                query = text("""
                                 select price_type
                                      , paid_open_date
                                      , paid_episode_no
                                      , coalesce(series_regular_price, 0) as series_regular_price
                                      , coalesce(single_regular_price, 0) as single_regular_price
                                   from tb_product
                                  where user_id = :user_id
                                    and product_id = :product_id
                                  for update
                                 """)

                result = await db.execute(
                    query, {"user_id": user_id, "product_id": product_id_to_int}
                )
                db_rst = result.mappings().all()

                if db_rst:
                    product_price_type = db_rst[0]["price_type"]
                    paid_open_date = db_rst[0].get("paid_open_date")
                    paid_episode_no = db_rst[0].get("paid_episode_no")
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                # Paid product episodes are always created as paid on upload.
                # Determine paid state by either price_type or entered price fields.
                series_regular_price = int(db_rst[0].get("series_regular_price") or 0)
                single_regular_price = int(db_rst[0].get("single_regular_price") or 0)
                is_paid_product = (
                    product_price_type == "paid"
                    or series_regular_price > 0
                    or single_regular_price > 0
                )
                price_type = None
                if req_body.price_type is not None and req_body.price_type != "":
                    query = text("""
                                     select 1
                                       from tb_common_code
                                      where code_group = 'PROD_PRICE_TYPE'
                                        and code_key = :code_key
                                        and use_yn = 'Y'
                                     """)
                    result = await db.execute(query, {"code_key": req_body.price_type})
                    db_rst = result.mappings().all()
                    if not db_rst:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )
                    if not is_paid_product:
                        price_type = req_body.price_type

                if price_type == "paid" and product_price_type != "paid":
                    raise CustomResponseException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message=ErrorMessages.FREE_PRODUCT_CANNOT_CREATE_PAID_EPISODE,
                    )

                # TODO: cleaned garbled comment (encoding issue).
                if req_body.author_comment and len(req_body.author_comment) > 2000:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                # 업로드 완료 상태로 저장한다. (심사 신청은 별도 API)
                open_yn = "N"

                # TODO: cleaned garbled comment (encoding issue).
                query = text("""
                                 select 1
                                   from tb_common_file a
                                  inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                    and b.use_yn = 'Y'
                                  where a.file_group_id = :file_group_id
                                    and a.group_type = 'epub'
                                    and a.use_yn = 'Y'
                                 """)
                result = await db.execute(
                    query, {"file_group_id": req_body.epub_file_id}
                )
                db_rst = result.mappings().all()
                if not db_rst:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                # TODO: cleaned garbled comment (encoding issue).
                if req_body.episode_no is not None:
                    if req_body.episode_no <= 0:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                    query = text("""
                                     select 1
                                       from tb_product_episode
                                      where product_id = :product_id
                                        and episode_no = :episode_no
                                        and use_yn = 'Y'
                                     """)
                    result = await db.execute(
                        query,
                        {
                            "product_id": product_id_to_int,
                            "episode_no": req_body.episode_no,
                        },
                    )
                    db_rst = result.mappings().all()
                    if db_rst:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                    episode_no = req_body.episode_no
                else:
                    query = text("""
                                     select max(episode_no) as max_episode_no
                                       from tb_product_episode
                                      where product_id = :product_id
                                        and use_yn = 'Y'
                                     """)
                    result = await db.execute(query, {"product_id": product_id_to_int})
                    row = result.mappings().first()
                    episode_no = (row.get("max_episode_no") or 0) + 1

                if price_type is None:
                    price_type = _default_episode_price_type(
                        is_paid_product=is_paid_product,
                        paid_open_date=paid_open_date,
                        paid_episode_no=paid_episode_no,
                        episode_no=episode_no,
                    )

                epub_binary = await _download_epub_binary_from_r2(
                    req_body.epub_file_id, db
                )
                epub_payload = (
                    _extract_epub_payload_from_epub(epub_binary)
                    if epub_binary
                    else {"text_count": 0, "html_content": ""}
                )
                episode_text_count = int(epub_payload.get("text_count") or 0)
                episode_content_from_epub = str(
                    epub_payload.get("html_content") or ""
                )


                # TODO: cleaned garbled comment (encoding issue).
                query = text("""
                                 insert into tb_product_episode (
                                     product_id, price_type, episode_no, episode_title,
                                     episode_text_count, episode_content, epub_file_id,
                                     author_comment, comment_open_yn, evaluation_open_yn,
                                     publish_reserve_date, open_yn, created_id, updated_id
                                 )
                                 values (
                                     :product_id, :price_type, :episode_no, :episode_title,
                                     :episode_text_count, :episode_content, :epub_file_id,
                                     :author_comment, :comment_open_yn, :evaluation_open_yn,
                                     :publish_reserve_date, :open_yn, :created_id, :updated_id
                                 )
                                 """)

                await db.execute(
                    query,
                    {
                        "product_id": product_id_to_int,
                        "price_type": price_type,
                        "episode_no": episode_no,
                        "episode_title": req_body.title,
                        "episode_text_count": episode_text_count,
                        "episode_content": episode_content_from_epub,
                        "epub_file_id": req_body.epub_file_id,
                        "author_comment": req_body.author_comment,
                        "comment_open_yn": req_body.comment_open_yn,
                        "evaluation_open_yn": req_body.evaluation_open_yn,
                        "publish_reserve_date": _normalize_publish_reserve_datetime(
                            req_body.publish_reserve_date
                        )
                        if req_body.publish_reserve_yn == "Y"
                        else None,
                        "open_yn": open_yn,
                        "created_id": settings.DB_DML_DEFAULT_ID,
                        "updated_id": settings.DB_DML_DEFAULT_ID,
                    },
                )

                query = text("""
                                 select last_insert_id()
                                 """)
                result = await db.execute(query)
                new_episode_id = result.scalar()

                apply_ids = []

                if (
                    price_type == "paid"
                    and product_price_type != "paid"
                    and open_yn == "Y"
                    and req_body.publish_reserve_yn == "N"
                ):
                    await _promote_product_price_type_to_paid(
                        product_id=product_id_to_int,
                        updated_id=user_id,
                        db=db,
                    )
                    product_price_type = "paid"

                # TODO: cleaned garbled comment (encoding issue).
                if open_yn == "Y" and req_body.publish_reserve_yn == "N":
                    query = text("""
                                     update tb_product
                                        set last_episode_date = now()
                                      where product_id = :product_id
                                     """)
                    await db.execute(query, {"product_id": product_id_to_int})

                res_data = {
                    "episodeId": new_episode_id,
                    "applyIds": apply_ids,
                }
        except CustomResponseException as e:
            logger.error(e, exc_info=True)
            raise
        except OperationalError as e:
            logger.error(e, exc_info=True)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message=ErrorMessages.DB_CONNECTION_ERROR,
            )
        except SQLAlchemyError as e:
            logger.error(e, exc_info=True)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.DB_OPERATION_ERROR,
            )
        except Exception as e:
            logger.error(e, exc_info=True)
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


async def post_episodes_products_product_id_epub_batch(
    product_id: str,
    req_body: episode_schema.PostEpisodesProductsProductIdEpubBatchReqBody,
    kc_user_id: str,
    db: AsyncSession,
    save: Optional[str] = None,
):
    res_data = {}
    product_id_to_int = int(product_id)

    if kc_user_id:
        try:
            if not req_body.episodes:
                raise CustomResponseException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=ErrorMessages.INVALID_EPISODE_INFO,
                )

            # TODO: cleaned garbled comment (encoding issue).
            requested_file_group_ids = {
                int(episode.epub_file_id) for episode in req_body.episodes
            }
            async with likenovel_db_session() as read_db:
                epub_cache = await _get_epub_cache_from_epub_files(
                    file_group_ids=requested_file_group_ids,
                    db=read_db,
                )

            async with _transaction_scope(db):
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                # TODO: cleaned garbled comment (encoding issue).
                query = text("""
                                 select price_type
                                      , paid_open_date
                                      , paid_episode_no
                                      , coalesce(series_regular_price, 0) as series_regular_price
                                      , coalesce(single_regular_price, 0) as single_regular_price
                                   from tb_product
                                  where user_id = :user_id
                                    and product_id = :product_id
                                  for update
                                 """)

                result = await db.execute(
                    query, {"user_id": user_id, "product_id": product_id_to_int}
                )
                db_rst = result.mappings().all()

                if not db_rst:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )
                product_price_type = db_rst[0]["price_type"]
                paid_open_date = db_rst[0].get("paid_open_date")
                paid_episode_no = db_rst[0].get("paid_episode_no")
                series_regular_price = int(db_rst[0].get("series_regular_price") or 0)
                single_regular_price = int(db_rst[0].get("single_regular_price") or 0)
                is_paid_product = (
                    product_price_type == "paid"
                    or series_regular_price > 0
                    or single_regular_price > 0
                )

                # TODO: cleaned garbled comment (encoding issue).
                query = text("""
                                 select episode_no
                                   from tb_product_episode
                                  where product_id = :product_id
                                    and use_yn = 'Y'
                                 """)
                result = await db.execute(query, {"product_id": product_id_to_int})
                existing_episode_rows = result.mappings().all()
                used_episode_no_set = {
                    int(row.get("episode_no"))
                    for row in existing_episode_rows
                    if row.get("episode_no") is not None
                }
                max_episode_no = max(used_episode_no_set) if used_episode_no_set else 0

                created_episode_ids = []
                created_episode_nos = []
                has_immediate_open_episode = False

                query = text("""
                                 select code_key
                                   from tb_common_code
                                  where code_group = 'PROD_PRICE_TYPE'
                                    and use_yn = 'Y'
                                 """)
                result = await db.execute(query)
                valid_price_type_set = {
                    row.get("code_key")
                    for row in result.mappings().all()
                    if row.get("code_key")
                }
                if not valid_price_type_set:
                    valid_price_type_set = {"free", "paid"}

                insert_rows = []

                for episode in req_body.episodes:
                    # price_type validation
                    price_type = None
                    if episode.price_type is not None and episode.price_type != "":
                        if episode.price_type not in valid_price_type_set:
                            raise CustomResponseException(
                                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                message=ErrorMessages.INVALID_EPISODE_INFO,
                            )
                        if not is_paid_product:
                            price_type = episode.price_type

                    if price_type == "paid" and product_price_type != "paid":
                        raise CustomResponseException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            message=ErrorMessages.FREE_PRODUCT_CANNOT_CREATE_PAID_EPISODE,
                        )

                    if episode.author_comment and len(episode.author_comment) > 2000:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                    if int(episode.epub_file_id) not in epub_cache:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                    if episode.episode_no is not None:
                        if episode.episode_no <= 0:
                            raise CustomResponseException(
                                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                message=ErrorMessages.INVALID_EPISODE_INFO,
                            )
                        if episode.episode_no in used_episode_no_set:
                            raise CustomResponseException(
                                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                message=ErrorMessages.INVALID_EPISODE_INFO,
                            )
                        episode_no = episode.episode_no
                    else:
                        next_episode_no = max_episode_no + 1
                        while next_episode_no in used_episode_no_set:
                            next_episode_no += 1
                        episode_no = next_episode_no

                    if price_type is None:
                        price_type = _default_episode_price_type(
                            is_paid_product=is_paid_product,
                            paid_open_date=paid_open_date,
                            paid_episode_no=paid_episode_no,
                            episode_no=episode_no,
                        )

                    used_episode_no_set.add(episode_no)
                    if episode_no > max_episode_no:
                        max_episode_no = episode_no

                    # 업로드 완료 상태로 저장한다. (심사 신청/판매 시작은 별도 API)
                    open_yn = "N"
                    epub_data = epub_cache.get(
                        int(episode.epub_file_id), {"text_count": 0, "html_content": ""}
                    )
                    episode_text_count = epub_data["text_count"]

                    insert_rows.append(
                        {
                            "product_id": product_id_to_int,
                            "price_type": price_type,
                            "episode_no": episode_no,
                            "episode_title": episode.title,
                            "episode_text_count": episode_text_count,
                            "episode_content": epub_data["html_content"],
                            "epub_file_id": episode.epub_file_id,
                            "author_comment": episode.author_comment,
                            "comment_open_yn": episode.comment_open_yn,
                            "evaluation_open_yn": episode.evaluation_open_yn,
                            "publish_reserve_date": _normalize_publish_reserve_datetime(
                                episode.publish_reserve_date
                            )
                            if episode.publish_reserve_yn == "Y"
                            else None,
                            "open_yn": open_yn,
                            "created_id": settings.DB_DML_DEFAULT_ID,
                            "updated_id": settings.DB_DML_DEFAULT_ID,
                        }
                    )
                    created_episode_nos.append(episode_no)

                    if open_yn == "Y" and episode.publish_reserve_yn == "N":
                        has_immediate_open_episode = True

                query = text("""
                                 insert into tb_product_episode (
                                     product_id, price_type, episode_no, episode_title,
                                     episode_text_count, episode_content, epub_file_id,
                                     author_comment, comment_open_yn, evaluation_open_yn,
                                     publish_reserve_date, open_yn, created_id, updated_id
                                 )
                                 values (
                                     :product_id, :price_type, :episode_no, :episode_title,
                                     :episode_text_count, :episode_content, :epub_file_id,
                                     :author_comment, :comment_open_yn, :evaluation_open_yn,
                                     :publish_reserve_date, :open_yn, :created_id, :updated_id
                                 )
                                 """)
                await db.execute(query, insert_rows)

                if created_episode_nos:
                    params = {"product_id": product_id_to_int}
                    placeholders = []
                    for idx, episode_no in enumerate(created_episode_nos):
                        key = f"episode_no_{idx}"
                        params[key] = episode_no
                        placeholders.append(f":{key}")
                    in_clause = ", ".join(placeholders)

                    query = text(f"""
                                     select episode_id, episode_no
                                       from tb_product_episode
                                      where product_id = :product_id
                                        and use_yn = 'Y'
                                        and episode_no in ({in_clause})
                                     """)
                    result = await db.execute(query, params)
                    rows = result.mappings().all()
                    episode_id_by_no = {
                        int(row.get("episode_no")): int(row.get("episode_id"))
                        for row in rows
                        if row.get("episode_no") is not None and row.get("episode_id") is not None
                    }
                    created_episode_ids = [
                        episode_id_by_no.get(episode_no) for episode_no in created_episode_nos
                    ]
                    if any(episode_id is None for episode_id in created_episode_ids):
                        raise CustomResponseException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            message=ErrorMessages.DB_OPERATION_ERROR,
                        )

                if product_price_type != "paid" and any(
                    row.get("price_type") == "paid" and row.get("open_yn") == "Y"
                    for row in insert_rows
                ):
                    await _promote_product_price_type_to_paid(
                        product_id=product_id_to_int,
                        updated_id=user_id,
                        db=db,
                    )
                    product_price_type = "paid"

                if has_immediate_open_episode:
                    query = text("""
                                     update tb_product
                                        set last_episode_date = now()
                                      where product_id = :product_id
                                     """)
                    await db.execute(query, {"product_id": product_id_to_int})

                apply_ids = []

                res_data = {
                    "count": len(created_episode_ids),
                    "episodeIds": created_episode_ids,
                    "applyIds": apply_ids,
                }
        except CustomResponseException as e:
            logger.error(e, exc_info=True)
            raise
        except OperationalError as e:
            logger.error(e, exc_info=True)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message=ErrorMessages.DB_CONNECTION_ERROR,
            )
        except SQLAlchemyError as e:
            logger.error(e, exc_info=True)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.DB_OPERATION_ERROR,
            )
        except Exception as e:
            logger.error(e, exc_info=True)
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


async def post_episodes_products_product_id_titles_bulk(
    product_id: str,
    req_body: episode_schema.PostEpisodesProductsProductIdTitlesBulkReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    res_data = {}

    if kc_user_id:
        try:
            async with _transaction_scope(db):
                user_id, user_info = await comm_service.get_user_from_kc(
                    kc_user_id, db, addUserInfo=["role_type"]
                )
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                product_id_to_int = int(product_id)
                rows_from_sheet = req_body.episodes or []
                if not rows_from_sheet:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                normalized_rows: list[dict] = []
                seen_episode_nos: set[int] = set()
                for row in rows_from_sheet:
                    episode_no = int(row.no) if int(row.no) > 0 else 0
                    file_name = _normalize_bulk_episode_title(row.file_name)
                    episode_title = _normalize_bulk_episode_title(row.title)

                    if (
                        episode_no <= 0
                        or not file_name
                        or not episode_title
                        or len(episode_title) > 300
                        or _has_disallowed_control_chars(file_name)
                        or _has_disallowed_control_chars(episode_title)
                        or episode_no in seen_episode_nos
                    ):
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                    seen_episode_nos.add(episode_no)
                    normalized_rows.append(
                        {
                            "episode_no": episode_no,
                            "file_name": file_name,
                            "episode_title": episode_title,
                        }
                    )

                is_admin = (user_info or {}).get("role_type") == "admin"

                query = text(
                    """
                    select
                        e.episode_id,
                        e.episode_no,
                        e.episode_title,
                        e.open_yn,
                        e.publish_reserve_date,
                        pea_latest.latest_apply_status,
                        cfi.file_org_name as epub_file_name
                    from tb_product_episode e
                    inner join tb_product p
                       on p.product_id = e.product_id
                    left join (
                        select
                            pea.episode_id,
                            pea.status_code as latest_apply_status
                        from tb_product_episode_apply pea
                        inner join (
                            select episode_id, max(id) as max_id
                            from tb_product_episode_apply
                            where use_yn = 'Y'
                            group by episode_id
                        ) pea_max
                          on pea_max.episode_id = pea.episode_id
                         and pea_max.max_id = pea.id
                        where pea.use_yn = 'Y'
                    ) pea_latest
                      on pea_latest.episode_id = e.episode_id
                    left join tb_common_file cf
                      on cf.file_group_id = e.epub_file_id
                     and cf.group_type = 'epub'
                     and cf.use_yn = 'Y'
                    left join tb_common_file_item cfi
                      on cfi.file_group_id = cf.file_group_id
                     and cfi.use_yn = 'Y'
                    where e.product_id = :product_id
                      and e.use_yn = 'Y'
                      and (:is_admin = 1 or p.user_id = :user_id)
                    for update
                    """
                )
                result = await db.execute(
                    query,
                    {
                        "product_id": product_id_to_int,
                        "is_admin": 1 if is_admin else 0,
                        "user_id": user_id,
                    },
                )
                rows = result.mappings().all()
                if not rows:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                eligible_rows = []
                episode_row_by_no: dict[int, dict] = {}
                for row in rows:
                    if _is_episode_upload_completed(
                        latest_apply_status=row.get("latest_apply_status"),
                        open_yn=row.get("open_yn"),
                        publish_reserve_date=row.get("publish_reserve_date"),
                    ):
                        episode_no = int(row.get("episode_no"))
                        if episode_no in episode_row_by_no:
                            raise CustomResponseException(
                                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                message=ErrorMessages.INVALID_EPISODE_INFO,
                            )
                        episode_row_by_no[episode_no] = dict(row)
                        eligible_rows.append(dict(row))

                if len(eligible_rows) != len(normalized_rows):
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                update_rows = []
                updated_episode_ids = []
                for sheet_row in normalized_rows:
                    current_row = episode_row_by_no.get(sheet_row["episode_no"])
                    if current_row is None:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                    current_file_name = _normalize_bulk_episode_title(
                        current_row.get("epub_file_name")
                    )
                    if not current_file_name or current_file_name != sheet_row["file_name"]:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                    update_rows.append(
                        {
                            "episode_id": int(current_row.get("episode_id")),
                            "episode_title": sheet_row["episode_title"],
                            "updated_id": user_id,
                        }
                    )
                    updated_episode_ids.append(int(current_row.get("episode_id")))

                query = text(
                    """
                    update tb_product_episode
                       set episode_title = :episode_title,
                           updated_id = :updated_id
                     where episode_id = :episode_id
                       and use_yn = 'Y'
                    """
                )
                await db.execute(query, update_rows)

                res_data = {
                    "count": len(update_rows),
                    "episodeIds": updated_episode_ids,
                }
        except ValueError as e:
            logger.error(e, exc_info=True)
            raise CustomResponseException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                message=ErrorMessages.INVALID_EPISODE_INFO,
            )
        except CustomResponseException as e:
            logger.error(e, exc_info=True)
            raise
        except OperationalError as e:
            logger.error(e, exc_info=True)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message=ErrorMessages.DB_CONNECTION_ERROR,
            )
        except SQLAlchemyError as e:
            logger.error(e, exc_info=True)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.DB_OPERATION_ERROR,
            )
        except Exception as e:
            logger.error(e, exc_info=True)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    return {"data": res_data}


async def post_episodes_review_requests(
    req_body: episode_schema.PostEpisodesReviewRequestsReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    res_data = {}

    if kc_user_id:
        try:
            async with _transaction_scope(db):
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                if not req_body.episode_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                episode_ids = sorted(
                    {episode_id for episode_id in req_body.episode_ids if episode_id > 0}
                )
                if not episode_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                params = {"user_id": user_id}
                placeholders = []
                for idx, episode_id in enumerate(episode_ids):
                    key = f"episode_id_{idx}"
                    params[key] = episode_id
                    placeholders.append(f":{key}")
                in_clause = ", ".join(placeholders)

                # TODO: cleaned garbled comment (encoding issue).
                query = text(f"""
                                 select e.episode_id
                                   from tb_product_episode e
                                  inner join tb_product p on e.product_id = p.product_id
                                  where p.user_id = :user_id
                                    and e.use_yn = 'Y'
                                    and e.episode_id in ({in_clause})
                                 """)
                result = await db.execute(query, params)
                found_episode_ids = {int(row["episode_id"]) for row in result.mappings().all()}
                if len(found_episode_ids) != len(episode_ids):
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                apply_ids = await _create_review_apply_for_episode_ids(
                    episode_ids=episode_ids,
                    req_user_id=user_id,
                    db=db,
                )

                res_data = {"count": len(apply_ids), "applyIds": apply_ids}
        except CustomResponseException as e:
            logger.error(e)
            raise
        except OperationalError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message=ErrorMessages.DB_CONNECTION_ERROR,
            )
        except SQLAlchemyError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.DB_OPERATION_ERROR,
            )
        except Exception as e:
            logger.error(e)
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


async def post_episodes_review_requests_cancel(
    req_body: episode_schema.PostEpisodesReviewCancelReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    res_data = {}

    if kc_user_id:
        try:
            async with _transaction_scope(db):
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                if not req_body.apply_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                apply_ids = sorted(
                    {apply_id for apply_id in req_body.apply_ids if apply_id > 0}
                )
                if not apply_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                params = {"user_id": user_id}
                placeholders = []
                for idx, apply_id in enumerate(apply_ids):
                    key = f"apply_id_{idx}"
                    params[key] = apply_id
                    placeholders.append(f":{key}")
                in_clause = ", ".join(placeholders)

                query = text(f"""
                                 select a.id, a.status_code
                                   from tb_product_episode_apply a
                                  inner join tb_product_episode e
                                     on e.episode_id = a.episode_id
                                    and e.use_yn = 'Y'
                                  inner join tb_product p
                                     on p.product_id = e.product_id
                                    and p.user_id = :user_id
                                  where a.use_yn = 'Y'
                                    and a.id in ({in_clause})
                                  for update
                                 """)
                result = await db.execute(query, params)
                rows = result.mappings().all()
                if len(rows) != len(apply_ids):
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                if any(row.get("status_code") != "review" for row in rows):
                    raise CustomResponseException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                query = text(f"""
                                 update tb_product_episode_apply
                                    set status_code = 'cancel',
                                        approval_user_id = null,
                                        approval_date = null,
                                        updated_id = :updated_id
                                  where id in ({in_clause})
                                    and use_yn = 'Y'
                                    and status_code = 'review'
                                 """)
                update_params = {"updated_id": user_id}
                update_params.update(params)
                result = await db.execute(query, update_params)
                if result.rowcount != len(apply_ids):
                    raise CustomResponseException(
                        status_code=status.HTTP_409_CONFLICT,
                        message=ErrorMessages.ALREADY_APPLIED_STATE,
                    )

                res_data = {"count": len(apply_ids), "applyIds": apply_ids}
        except CustomResponseException as e:
            logger.error(e)
            raise
        except OperationalError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message=ErrorMessages.DB_CONNECTION_ERROR,
            )
        except SQLAlchemyError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.DB_OPERATION_ERROR,
            )
        except Exception as e:
            logger.error(e)
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


async def post_episodes_delete(
    req_body: episode_schema.PostEpisodesDeleteReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    res_data = {}

    if kc_user_id:
        try:
            async with _transaction_scope(db):
                user_id, user_info = await comm_service.get_user_from_kc(
                    kc_user_id, db, addUserInfo=["role_type"]
                )
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                if not req_body.episode_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                episode_ids: list[int] = []
                for episode_id in req_body.episode_ids:
                    try:
                        episode_id_int = int(episode_id)
                    except (TypeError, ValueError):
                        continue
                    if episode_id_int > 0:
                        episode_ids.append(episode_id_int)

                episode_ids = sorted(set(episode_ids))
                if not episode_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                is_admin = (user_info or {}).get("role_type") == "admin"
                params = {"user_id": user_id, "is_admin": 1 if is_admin else 0}
                placeholders = []
                for idx, episode_id in enumerate(episode_ids):
                    key = f"episode_id_{idx}"
                    params[key] = episode_id
                    placeholders.append(f":{key}")
                in_clause = ", ".join(placeholders)

                query = text(
                    f"""
                    select
                        e.episode_id,
                        e.epub_file_id,
                        pea_latest.latest_apply_status
                    from tb_product_episode e
                    inner join tb_product p
                       on p.product_id = e.product_id
                    left join (
                        select
                            pea.episode_id,
                            pea.status_code as latest_apply_status
                        from tb_product_episode_apply pea
                        inner join (
                            select episode_id, max(id) as max_id
                            from tb_product_episode_apply
                            where use_yn = 'Y'
                            group by episode_id
                        ) pea_max
                          on pea_max.episode_id = pea.episode_id
                         and pea_max.max_id = pea.id
                        where pea.use_yn = 'Y'
                    ) pea_latest
                      on pea_latest.episode_id = e.episode_id
                    where e.use_yn = 'Y'
                      and e.episode_id in ({in_clause})
                      and (:is_admin = 1 or p.user_id = :user_id)
                    for update
                    """
                )
                result = await db.execute(query, params)
                rows = result.mappings().all()

                if len(rows) != len(episode_ids):
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                review_episode_ids = [
                    int(row.get("episode_id"))
                    for row in rows
                    if row.get("latest_apply_status") == "review"
                ]
                if review_episode_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message="심사중 회차는 삭제할 수 없습니다.",
                    )

                epub_file_group_ids = sorted(
                    {
                        int(row.get("epub_file_id"))
                        for row in rows
                        if row.get("epub_file_id") is not None
                        and int(row.get("epub_file_id")) > 0
                    }
                )

                update_params = {"updated_id": user_id}
                update_params.update(params)

                query = text(
                    f"""
                    update tb_product_episode
                       set use_yn = 'N',
                           open_yn = 'N',
                           updated_id = :updated_id
                     where use_yn = 'Y'
                       and episode_id in ({in_clause})
                    """
                )
                await db.execute(query, update_params)

                query = text(
                    f"""
                    update tb_product_episode_apply
                       set use_yn = 'N',
                           updated_id = :updated_id
                     where use_yn = 'Y'
                       and episode_id in ({in_clause})
                    """
                )
                await db.execute(query, update_params)

                query = text(
                    f"""
                    delete from tb_product_episode_like
                     where episode_id in ({in_clause})
                    """
                )
                await db.execute(query, params)

                if epub_file_group_ids:
                    file_params = {"updated_id": user_id}
                    file_placeholders = []
                    for idx, file_group_id in enumerate(epub_file_group_ids):
                        key = f"file_group_id_{idx}"
                        file_params[key] = file_group_id
                        file_placeholders.append(f":{key}")
                    file_in_clause = ", ".join(file_placeholders)

                    query = text(
                        f"""
                        update tb_common_file_item
                           set use_yn = 'N',
                               updated_id = :updated_id
                         where use_yn = 'Y'
                           and file_group_id in ({file_in_clause})
                        """
                    )
                    await db.execute(query, file_params)

                    query = text(
                        f"""
                        update tb_common_file
                           set use_yn = 'N',
                               updated_id = :updated_id
                         where use_yn = 'Y'
                           and group_type = 'epub'
                           and file_group_id in ({file_in_clause})
                        """
                    )
                    await db.execute(query, file_params)

                res_data = {"count": len(episode_ids), "episodeIds": episode_ids}
        except CustomResponseException as e:
            logger.error(e)
            raise
        except OperationalError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message=ErrorMessages.DB_CONNECTION_ERROR,
            )
        except SQLAlchemyError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.DB_OPERATION_ERROR,
            )
        except Exception as e:
            logger.error(e)
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


async def post_episodes_sale_start(
    req_body: episode_schema.PostEpisodesSaleStartReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    res_data = {}

    if kc_user_id:
        try:
            async with _transaction_scope(db):
                user_id, user_info = await comm_service.get_user_from_kc(
                    kc_user_id, db, addUserInfo=["role_type"]
                )
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                if not req_body.episode_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                episode_ids = sorted(
                    {
                        int(episode_id)
                        for episode_id in req_body.episode_ids
                        if int(episode_id) > 0
                    }
                )
                if not episode_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                is_admin = (user_info or {}).get("role_type") == "admin"
                params = {"user_id": user_id, "is_admin": 1 if is_admin else 0}
                placeholders = []
                for idx, episode_id in enumerate(episode_ids):
                    key = f"episode_id_{idx}"
                    params[key] = episode_id
                    placeholders.append(f":{key}")
                in_clause = ", ".join(placeholders)

                query = text(
                    f"""
                    select
                        e.episode_id,
                        e.product_id,
                        e.open_yn,
                        coalesce(e.price_type, 'free') as price_type,
                        pea_latest.latest_apply_status
                    from tb_product_episode e
                    inner join tb_product p
                       on p.product_id = e.product_id
                    left join (
                        select
                            pea.episode_id,
                            pea.status_code as latest_apply_status
                        from tb_product_episode_apply pea
                        inner join (
                            select episode_id, max(id) as max_id
                            from tb_product_episode_apply
                            where use_yn = 'Y'
                            group by episode_id
                        ) pea_max
                          on pea_max.episode_id = pea.episode_id
                         and pea_max.max_id = pea.id
                        where pea.use_yn = 'Y'
                    ) pea_latest
                      on pea_latest.episode_id = e.episode_id
                    where e.use_yn = 'Y'
                      and e.episode_id in ({in_clause})
                      and (:is_admin = 1 or p.user_id = :user_id)
                    for update
                    """
                )
                result = await db.execute(query, params)
                rows = result.mappings().all()

                if len(rows) != len(episode_ids):
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                eligible_episode_ids = []
                skipped_episode_ids = []
                for row in rows:
                    latest_apply_status = row.get("latest_apply_status")
                    open_yn = row.get("open_yn")
                    episode_id = int(row.get("episode_id"))

                    if latest_apply_status == "accepted" and open_yn != "Y":
                        eligible_episode_ids.append(episode_id)
                    else:
                        skipped_episode_ids.append(episode_id)

                if not eligible_episode_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                update_params = {"updated_id": user_id}
                episode_placeholders = []
                for idx, episode_id in enumerate(eligible_episode_ids):
                    key = f"eligible_episode_id_{idx}"
                    update_params[key] = episode_id
                    episode_placeholders.append(f":{key}")
                eligible_in_clause = ", ".join(episode_placeholders)

                query = text(
                    f"""
                    update tb_product_episode
                       set open_yn = 'Y',
                           publish_reserve_date = null,
                           open_changed_date = now(),
                           updated_id = :updated_id
                     where use_yn = 'Y'
                       and episode_id in ({eligible_in_clause})
                    """
                )
                await db.execute(query, update_params)

                query = text(
                    f"""
                    update tb_product p
                    inner join (
                        select distinct product_id
                        from tb_product_episode
                        where episode_id in ({eligible_in_clause})
                    ) pe on pe.product_id = p.product_id
                       set p.open_yn = 'Y',
                           p.last_episode_date = now(),
                           p.updated_id = :updated_id
                     where p.blind_yn = 'N'
                    """
                )
                await db.execute(query, update_params)

                query = text(
                    f"""
                    update tb_product p
                    inner join (
                        select distinct product_id
                        from tb_product_episode
                        where episode_id in ({eligible_in_clause})
                          and use_yn = 'Y'
                          and open_yn = 'Y'
                          and coalesce(price_type, 'free') = 'paid'
                    ) pe_paid on pe_paid.product_id = p.product_id
                       set p.price_type = 'paid',
                           p.updated_id = :updated_id
                     where p.price_type = 'free'
                    """
                )
                await db.execute(query, update_params)

                res_data = {
                    "count": len(eligible_episode_ids),
                    "episodeIds": eligible_episode_ids,
                    "skippedEpisodeIds": skipped_episode_ids,
                }
        except CustomResponseException as e:
            logger.error(e)
            raise
        except OperationalError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message=ErrorMessages.DB_CONNECTION_ERROR,
            )
        except SQLAlchemyError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.DB_OPERATION_ERROR,
            )
        except Exception as e:
            logger.error(e)
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


async def post_episodes_sale_reserve(
    req_body: episode_schema.PostEpisodesSaleReserveReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    res_data = {}

    if kc_user_id:
        try:
            async with _transaction_scope(db):
                user_id, user_info = await comm_service.get_user_from_kc(
                    kc_user_id, db, addUserInfo=["role_type"]
                )
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                if not req_body.episode_ids or not req_body.publish_reserve_date:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                episode_ids = sorted(
                    {
                        int(episode_id)
                        for episode_id in req_body.episode_ids
                        if int(episode_id) > 0
                    }
                )
                if not episode_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                is_admin = (user_info or {}).get("role_type") == "admin"
                params = {"user_id": user_id, "is_admin": 1 if is_admin else 0}
                placeholders = []
                for idx, episode_id in enumerate(episode_ids):
                    key = f"episode_id_{idx}"
                    params[key] = episode_id
                    placeholders.append(f":{key}")
                in_clause = ", ".join(placeholders)

                query = text(
                    f"""
                    select
                        e.episode_id,
                        e.product_id,
                        e.open_yn,
                        pea_latest.latest_apply_status
                    from tb_product_episode e
                    inner join tb_product p
                       on p.product_id = e.product_id
                    left join (
                        select
                            pea.episode_id,
                            pea.status_code as latest_apply_status
                        from tb_product_episode_apply pea
                        inner join (
                            select episode_id, max(id) as max_id
                            from tb_product_episode_apply
                            where use_yn = 'Y'
                            group by episode_id
                        ) pea_max
                          on pea_max.episode_id = pea.episode_id
                         and pea_max.max_id = pea.id
                        where pea.use_yn = 'Y'
                    ) pea_latest
                      on pea_latest.episode_id = e.episode_id
                    where e.use_yn = 'Y'
                      and e.episode_id in ({in_clause})
                      and (:is_admin = 1 or p.user_id = :user_id)
                    for update
                    """
                )
                result = await db.execute(query, params)
                rows = result.mappings().all()

                if len(rows) != len(episode_ids):
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                eligible_episode_ids = []
                skipped_episode_ids = []
                for row in rows:
                    latest_apply_status = row.get("latest_apply_status")
                    open_yn = row.get("open_yn")
                    episode_id = int(row.get("episode_id"))

                    if latest_apply_status == "accepted" and open_yn != "Y":
                        eligible_episode_ids.append(episode_id)
                    else:
                        skipped_episode_ids.append(episode_id)

                if not eligible_episode_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                publish_reserve_date = _normalize_publish_reserve_datetime(
                    req_body.publish_reserve_date,
                    message=f"예약일시는 현재 시각 기준 {_MIN_RESERVE_LEAD_MINUTES}분 이후만 설정할 수 있습니다.",
                )

                update_params = {
                    "updated_id": user_id,
                    "publish_reserve_date": publish_reserve_date,
                }
                episode_placeholders = []
                for idx, episode_id in enumerate(eligible_episode_ids):
                    key = f"eligible_episode_id_{idx}"
                    update_params[key] = episode_id
                    episode_placeholders.append(f":{key}")
                eligible_in_clause = ", ".join(episode_placeholders)

                query = text(
                    f"""
                    update tb_product_episode
                       set open_yn = 'N',
                           publish_reserve_date = :publish_reserve_date,
                           updated_id = :updated_id
                     where use_yn = 'Y'
                       and episode_id in ({eligible_in_clause})
                    """
                )
                await db.execute(query, update_params)

                res_data = {
                    "count": len(eligible_episode_ids),
                    "episodeIds": eligible_episode_ids,
                    "skippedEpisodeIds": skipped_episode_ids,
                }
        except CustomResponseException as e:
            logger.error(e)
            raise
        except OperationalError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message=ErrorMessages.DB_CONNECTION_ERROR,
            )
        except SQLAlchemyError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.DB_OPERATION_ERROR,
            )
        except Exception as e:
            logger.error(e)
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


async def post_episodes_publish_reserve_bulk(
    req_body: episode_schema.PostEpisodesPublishReserveBulkReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    res_data = {}

    if kc_user_id:
        try:
            async with _transaction_scope(db):
                user_id, user_info = await comm_service.get_user_from_kc(
                    kc_user_id, db, addUserInfo=["role_type"]
                )
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                schedule_items = req_body.schedules or []
                if not schedule_items:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                normalized_schedule_map: dict[int, datetime] = {}

                for item in schedule_items:
                    episode_id = int(item.episode_id) if int(item.episode_id) > 0 else 0
                    if episode_id <= 0 or item.publish_reserve_date is None:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                    if episode_id in normalized_schedule_map:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                    publish_reserve_date = _normalize_publish_reserve_datetime(
                        item.publish_reserve_date,
                        message=f"예약일시는 현재 시각 기준 {_MIN_RESERVE_LEAD_MINUTES}분 이후만 설정할 수 있습니다.",
                    )

                    normalized_schedule_map[episode_id] = publish_reserve_date

                episode_ids = sorted(normalized_schedule_map.keys())
                is_admin = (user_info or {}).get("role_type") == "admin"
                params = {"user_id": user_id, "is_admin": 1 if is_admin else 0}
                placeholders = []
                for idx, episode_id in enumerate(episode_ids):
                    key = f"episode_id_{idx}"
                    params[key] = episode_id
                    placeholders.append(f":{key}")
                in_clause = ", ".join(placeholders)

                query = text(
                    f"""
                    select
                        e.episode_id,
                        e.product_id,
                        e.episode_no,
                        e.open_yn,
                        p.price_type,
                        p.product_type
                    from tb_product_episode e
                    inner join tb_product p
                       on p.product_id = e.product_id
                    where e.use_yn = 'Y'
                      and e.episode_id in ({in_clause})
                      and (:is_admin = 1 or p.user_id = :user_id)
                    for update
                    """
                )
                result = await db.execute(query, params)
                rows = result.mappings().all()

                if len(rows) != len(episode_ids):
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                product_ids = {int(row.get("product_id")) for row in rows}
                if len(product_ids) != 1:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                sample_row = rows[0]
                if (
                    sample_row.get("price_type") != "free"
                    or sample_row.get("product_type") != "normal"
                ):
                    raise CustomResponseException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message="무료 일반연재 작품만 일괄 예약할 수 있습니다.",
                    )

                opened_episode_ids = [
                    int(row.get("episode_id"))
                    for row in rows
                    if row.get("open_yn") == "Y"
                ]
                if opened_episode_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message="이미 공개된 회차는 일괄 예약할 수 없습니다.",
                    )

                update_rows = [
                    {
                        "episode_id": int(row.get("episode_id")),
                        "publish_reserve_date": normalized_schedule_map[
                            int(row.get("episode_id"))
                        ],
                        "updated_id": user_id,
                    }
                    for row in sorted(rows, key=lambda row: int(row.get("episode_no")))
                ]

                query = text(
                    """
                    update tb_product_episode
                       set open_yn = 'N',
                           publish_reserve_date = :publish_reserve_date,
                           updated_id = :updated_id
                     where use_yn = 'Y'
                       and episode_id = :episode_id
                    """
                )
                await db.execute(query, update_rows)

                res_data = {
                    "count": len(update_rows),
                    "productId": int(sample_row.get("product_id")),
                    "episodeIds": [row["episode_id"] for row in update_rows],
                }
        except CustomResponseException as e:
            logger.error(e)
            raise
        except OperationalError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message=ErrorMessages.DB_CONNECTION_ERROR,
            )
        except SQLAlchemyError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.DB_OPERATION_ERROR,
            )
        except Exception as e:
            logger.error(e)
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


async def post_episodes_sale_reserve_cancel(
    req_body: episode_schema.PostEpisodesSaleReserveCancelReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    res_data = {}

    if kc_user_id:
        try:
            async with _transaction_scope(db):
                user_id, user_info = await comm_service.get_user_from_kc(
                    kc_user_id, db, addUserInfo=["role_type"]
                )
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                if not req_body.episode_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                episode_ids = sorted(
                    {
                        int(episode_id)
                        for episode_id in req_body.episode_ids
                        if int(episode_id) > 0
                    }
                )
                if not episode_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                is_admin = (user_info or {}).get("role_type") == "admin"
                params = {"user_id": user_id, "is_admin": 1 if is_admin else 0}
                placeholders = []
                for idx, episode_id in enumerate(episode_ids):
                    key = f"episode_id_{idx}"
                    params[key] = episode_id
                    placeholders.append(f":{key}")
                in_clause = ", ".join(placeholders)

                # 예약 취소 대상: open_yn='N' AND publish_reserve_date IS NOT NULL
                # 이미 배치에 의해 open_yn='Y'가 된 회차는 조건에 걸리지 않음
                query = text(
                    f"""
                    select
                        e.episode_id
                    from tb_product_episode e
                    inner join tb_product p
                       on p.product_id = e.product_id
                    where e.use_yn = 'Y'
                      and e.open_yn = 'N'
                      and e.publish_reserve_date IS NOT NULL
                      and e.episode_id in ({in_clause})
                      and (:is_admin = 1 or p.user_id = :user_id)
                    for update
                    """
                )
                result = await db.execute(query, params)
                rows = result.mappings().all()

                eligible_episode_ids = [int(row["episode_id"]) for row in rows]
                skipped_episode_ids = [
                    eid for eid in episode_ids if eid not in eligible_episode_ids
                ]

                if not eligible_episode_ids:
                    raise CustomResponseException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message="이미 판매중이거나 예약된 회차가 없습니다.",
                    )

                update_params = {"updated_id": user_id}
                episode_placeholders = []
                for idx, eid in enumerate(eligible_episode_ids):
                    key = f"eligible_episode_id_{idx}"
                    update_params[key] = eid
                    episode_placeholders.append(f":{key}")
                eligible_in_clause = ", ".join(episode_placeholders)

                query = text(
                    f"""
                    update tb_product_episode
                       set publish_reserve_date = NULL,
                           updated_id = :updated_id,
                           updated_date = NOW()
                     where use_yn = 'Y'
                       and episode_id in ({eligible_in_clause})
                    """
                )
                await db.execute(query, update_params)

                res_data = {
                    "count": len(eligible_episode_ids),
                    "episodeIds": eligible_episode_ids,
                    "skippedEpisodeIds": skipped_episode_ids,
                }
        except CustomResponseException as e:
            logger.error(e)
            raise
        except OperationalError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message=ErrorMessages.DB_CONNECTION_ERROR,
            )
        except SQLAlchemyError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=ErrorMessages.DB_OPERATION_ERROR,
            )
        except Exception as e:
            logger.error(e)
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


async def put_episodes_episode_id(
    episode_id: str,
    req_body: episode_schema.PutEpisodesEpisodeIdReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    try:
        episode_id_to_int = int(episode_id)
    except (TypeError, ValueError):
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=ErrorMessages.INVALID_EPISODE_INFO,
        )

    if kc_user_id:
        try:
            async with _transaction_scope(db):
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                # TODO: cleaned garbled comment (encoding issue).
                query = text("""
                                 select a.product_id
                                      , a.last_episode_date
                                      , a.price_type
                                   from tb_product a
                                  inner join tb_product_episode b on a.product_id = b.product_id
                                    and b.use_yn = 'Y'
                                    and b.episode_id = :episode_id
                                  where a.user_id = :user_id
                                 """)

                result = await db.execute(
                    query, {"user_id": user_id, "episode_id": episode_id_to_int}
                )
                db_rst = result.mappings().all()

                if db_rst:
                    product_id = db_rst[0].get("product_id")
                    last_episode_date = db_rst[0].get("last_episode_date")
                    product_price_type = db_rst[0].get("price_type")
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                # TODO: cleaned garbled comment (encoding issue).
                price_type = None
                if req_body.price_type is None or req_body.price_type == "":
                    pass
                else:
                    # TODO: cleaned garbled comment (encoding issue).
                    if product_price_type == "free" and req_body.price_type != "free":
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.FREE_PRODUCT_CANNOT_CREATE_PAID_EPISODE,
                        )

                    query = text("""
                                     select 1
                                       from tb_common_code
                                      where code_group = 'PROD_PRICE_TYPE'
                                        and code_key = :code_key
                                        and use_yn = 'Y'
                                     """)

                    result = await db.execute(query, {"code_key": req_body.price_type})
                    db_rst = result.mappings().all()

                    if db_rst:
                        price_type = req_body.price_type
                    else:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                # TODO: cleaned garbled comment (encoding issue).
                try:
                    soup = BeautifulSoup(req_body.content, "html.parser")
                    text_content = soup.get_text(separator=" ", strip=True)  # TODO: cleaned garbled comment (encoding issue).
                except Exception:
                    # TODO: cleaned garbled comment (encoding issue).
                    text_content = req_body.content

                if len(text_content) > 20000:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                # TODO: cleaned garbled comment (encoding issue).
                if req_body.author_comment is None or req_body.author_comment == "":
                    pass
                else:
                    if len(req_body.author_comment) > 2000:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                # 예약 공개 설정 시 즉시 공개되지 않도록 강제 비공개
                effective_open_yn = (
                    "N"
                    if req_body.publish_reserve_yn == "Y"
                    else req_body.episode_open_yn
                )

                if price_type is None:
                    query = text("""
                                     update tb_product_episode a
                                        set a.episode_title = :episode_title
                                          , a.episode_text_count = :episode_text_count
                                          , a.episode_content = :episode_content
                                          , a.author_comment = :author_comment
                                          , a.comment_open_yn = :comment_open_yn
                                          , a.evaluation_open_yn = :evaluation_open_yn
                                          , a.publish_reserve_date = :publish_reserve_date
                                          , a.open_yn = :open_yn
                                          , a.updated_id = :user_id
                                      where a.episode_id = :episode_id
                                     """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "episode_id": episode_id_to_int,
                            "episode_title": req_body.title,
                            "episode_text_count": len(text_content),
                            "episode_content": req_body.content,
                            "author_comment": req_body.author_comment,
                            "comment_open_yn": req_body.comment_open_yn,
                            "evaluation_open_yn": req_body.evaluation_open_yn,
                            "publish_reserve_date": _normalize_publish_reserve_datetime(
                                req_body.publish_reserve_date
                            )
                            if req_body.publish_reserve_yn == "Y"
                            else None,
                            "open_yn": effective_open_yn,
                        },
                    )
                else:
                    query = text("""
                                     update tb_product_episode a
                                        set a.price_type = :price_type
                                          , a.episode_title = :episode_title
                                          , a.episode_text_count = :episode_text_count
                                          , a.episode_content = :episode_content
                                          , a.author_comment = :author_comment
                                          , a.comment_open_yn = :comment_open_yn
                                          , a.evaluation_open_yn = :evaluation_open_yn
                                          , a.publish_reserve_date = :publish_reserve_date
                                          , a.open_yn = :open_yn
                                          , a.updated_id = :user_id
                                      where a.episode_id = :episode_id
                                     """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "episode_id": episode_id_to_int,
                            "price_type": price_type,
                            "episode_title": req_body.title,
                            "episode_text_count": len(text_content),
                            "episode_content": req_body.content,
                            "author_comment": req_body.author_comment,
                            "comment_open_yn": req_body.comment_open_yn,
                            "evaluation_open_yn": req_body.evaluation_open_yn,
                            "publish_reserve_date": _normalize_publish_reserve_datetime(
                                req_body.publish_reserve_date
                            )
                            if req_body.publish_reserve_yn == "Y"
                            else None,
                            "open_yn": effective_open_yn,
                        },
                    )

                # last_episode_date upd
                if (
                    effective_open_yn == "Y"
                    and req_body.publish_reserve_yn == "N"
                ):
                    if last_episode_date is None:
                        query = text("""
                                         update tb_product
                                            set last_episode_date = now()
                                          where product_id = :product_id
                                         """)

                        await db.execute(query, {"product_id": product_id})

                # TODO: cleaned garbled comment (encoding issue).
                query = text(f"""
                                 select {get_file_path_sub_query("b.thumbnail_file_id", "cover_image_path", "cover")}
                                      , concat(a.episode_no, '화. ', a.episode_title) as episode_title
                                      , a.episode_content
                                      , a.epub_file_id
                                   from tb_product_episode a
                                  inner join tb_product b on a.product_id = b.product_id
                                  where episode_id = :episode_id
                                 """)

                result = await db.execute(query, {"episode_id": episode_id_to_int})
                db_rst = result.mappings().all()

                if db_rst:
                    cover_image_path = db_rst[0].get("cover_image_path")
                    episode_title = db_rst[0].get("episode_title")
                    episode_content = db_rst[0].get("episode_content")
                    epub_file_id = db_rst[0].get("epub_file_id")

                    file_org_name = f"{str(episode_id_to_int)}.epub"

                    # TODO: cleaned garbled comment (encoding issue).
                    await comm_service.make_epub(
                        file_org_name=file_org_name,
                        cover_image_path=cover_image_path,
                        episode_title=episode_title,
                        content_db=episode_content,
                    )

                    if epub_file_id is None:
                        # ins
                        # TODO: cleaned garbled comment (encoding issue).
                        while True:
                            file_name_to_uuid = comm_service.make_rand_uuid()
                            file_name_to_uuid = f"{file_name_to_uuid}.epub"

                            query = text("""
                                             select a.file_group_id
                                               from tb_common_file a
                                              inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                                and b.use_yn = 'Y'
                                                and b.file_name = :file_name
                                              where a.group_type = 'epub'
                                                and a.use_yn = 'Y'
                                            """)

                            result = await db.execute(
                                query, {"file_name": file_name_to_uuid}
                            )
                            db_rst = result.mappings().all()

                            if not db_rst:
                                break

                        query = text("""
                                         insert into tb_common_file (group_type, created_id, updated_id)
                                         values (:group_type, :created_id, :updated_id)
                                         """)

                        await db.execute(
                            query,
                            {
                                "group_type": "epub",
                                "created_id": settings.DB_DML_DEFAULT_ID,
                                "updated_id": settings.DB_DML_DEFAULT_ID,
                            },
                        )

                        query = text("""
                                         select last_insert_id()
                                         """)

                        result = await db.execute(query)
                        new_file_group_id = result.scalar()

                        query = text("""
                                         insert into tb_common_file_item (file_group_id, file_name, file_org_name, file_path, created_id, updated_id)
                                         values (:file_group_id, :file_name, :file_org_name, :file_path, :created_id, :updated_id)
                                         """)

                        await db.execute(
                            query,
                            {
                                "file_group_id": new_file_group_id,
                                "file_name": file_name_to_uuid,
                                "file_org_name": file_org_name,
                                "file_path": f"{settings.R2_SC_DOMAIN}/epub/{file_name_to_uuid}",
                                "created_id": settings.DB_DML_DEFAULT_ID,
                                "updated_id": settings.DB_DML_DEFAULT_ID,
                            },
                        )

                        epub_file_id = new_file_group_id
                    else:
                        # upd
                        query = text("""
                                         select b.file_name
                                           from tb_common_file a
                                          inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                            and b.use_yn = 'Y'
                                          where a.group_type = 'epub'
                                            and a.use_yn = 'Y'
                                            and a.file_group_id = :epub_file_id
                                        """)

                        result = await db.execute(query, {"epub_file_id": epub_file_id})
                        db_rst = result.mappings().all()

                        if db_rst:
                            file_name_to_uuid = db_rst[0].get("file_name")

                    presigned_url = comm_service.make_r2_presigned_url(
                        type="upload",
                        bucket_name=settings.R2_SC_EPUB_BUCKET,
                        file_id=file_name_to_uuid,
                    )

                    # TODO: cleaned garbled comment (encoding issue).
                    await comm_service.upload_epub_to_r2(
                        url=presigned_url, file_name=file_org_name
                    )

                    query = text("""
                                     update tb_product_episode a
                                        set a.epub_file_id = :epub_file_id
                                          , a.updated_id = :user_id
                                      where a.episode_id = :episode_id
                                     """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "episode_id": episode_id_to_int,
                            "epub_file_id": epub_file_id,
                        },
                    )
        except CustomResponseException:
            raise
        except OperationalError as e:
            logger.error(
                f"OperationalError in put_episodes_episode_id: {str(e)}", exc_info=True
            )
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError as e:
            logger.error(
                f"SQLAlchemyError in put_episodes_episode_id: {str(e)}", exc_info=True
            )
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.error(
                f"Exception in put_episodes_episode_id: {str(e)}", exc_info=True
            )
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    return


async def put_episodes_episode_id_open(
    episode_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    episode_id_to_int = int(episode_id)

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                query = text("""
                                 select a.product_id
                                      , a.open_yn
                                      , coalesce(a.price_type, 'free') as episode_price_type
                                      , b.price_type as product_price_type
                                      , case when a.publish_reserve_date is null then 'N'
                                             else 'Y'
                                        end as publish_reserve_yn
                                      , b.last_episode_date
                                   from tb_product_episode a
                                  inner join tb_product b on a.product_id = b.product_id
                                  where a.episode_id = :episode_id
                                    and a.use_yn = 'Y'
                                 """)

                result = await db.execute(query, {"episode_id": episode_id_to_int})
                db_rst = result.mappings().all()

                if db_rst:
                    product_id = db_rst[0].get("product_id")
                    open_yn = db_rst[0].get("open_yn")
                    episode_price_type = db_rst[0].get("episode_price_type")
                    product_price_type = db_rst[0].get("product_price_type")
                    publish_reserve_yn = db_rst[0].get("publish_reserve_yn")
                    last_episode_date = db_rst[0].get("last_episode_date")

                    query = text("""
                                     update tb_product_episode a
                                        set a.open_yn = (case when a.open_yn = 'N' then 'Y' else 'N' end)
                                          , a.publish_reserve_date = (case when a.open_yn = 'N' then NULL else a.publish_reserve_date end)
                                          , a.open_changed_date = NOW()
                                          , a.updated_id = :user_id
                                      where a.episode_id = :episode_id
                                        and a.use_yn = 'Y'
                                        and exists (select 1 from tb_product z
                                                     where a.product_id = z.product_id
                                                       and z.user_id = :user_id)
                                     """)

                    result = await db.execute(
                        query, {"episode_id": episode_id_to_int, "user_id": user_id}
                    )

                    if open_yn == "N":
                        # N -> Y
                        episode_open_yn = "Y"
                    else:
                        # Y -> N
                        episode_open_yn = "N"

                    # TODO: cleaned garbled comment (encoding issue).
                    if result.rowcount != 0:
                        res_data = {
                            "episodeId": episode_id_to_int,
                            "openYn": episode_open_yn,
                        }

                        # last_episode_date upd
                        if episode_open_yn == "Y" and publish_reserve_yn == "N":
                            if (
                                episode_price_type == "paid"
                                and product_price_type != "paid"
                            ):
                                await _promote_product_price_type_to_paid(
                                    product_id=product_id,
                                    updated_id=user_id,
                                    db=db,
                                )

                            if last_episode_date is None:
                                query = text("""
                                                 update tb_product
                                                    set last_episode_date = now()
                                                  where product_id = :product_id
                                                 """)

                                await db.execute(query, {"product_id": product_id})

                            # TODO: cleaned garbled comment (encoding issue).
                            try:
                                # TODO: cleaned garbled comment (encoding issue).
                                query = text("""
                                    select p.title as product_title, e.episode_no, e.episode_title
                                      from tb_product p
                                     inner join tb_product_episode e on p.product_id = e.product_id
                                     where e.episode_id = :episode_id
                                """)
                                result = await db.execute(
                                    query, {"episode_id": episode_id_to_int}
                                )
                                episode_info = result.mappings().first()

                                if episode_info:
                                    product_title = episode_info.get("product_title")
                                    episode_no = episode_info.get("episode_no")
                                    episode_title = episode_info.get("episode_title")

                                    # TODO: cleaned garbled comment (encoding issue).
                                    query = text("""
                                        select b.user_id
                                          from tb_user_bookmark b
                                         where b.product_id = :product_id
                                           and b.use_yn = 'Y'
                                           and (
                                               not exists (
                                                   select 1 from tb_user_notification n
                                                    where n.user_id = b.user_id
                                                      and n.noti_type = 'benefit'
                                               )
                                               or exists (
                                                   select 1 from tb_user_notification n
                                                    where n.user_id = b.user_id
                                                      and n.noti_type = 'benefit'
                                                      and n.noti_yn = 'Y'
                                               )
                                           )
                                    """)
                                    result = await db.execute(
                                        query, {"product_id": product_id}
                                    )
                                    bookmarked_users = result.mappings().all()

                                    # TODO: cleaned garbled comment (encoding issue).
                                    noti_title = (
                                        f"[{product_title}] \uc5c5\ub370\uc774\ud2b8 \ud68c\ucc28\uac00 \uacf5\uac1c\ub418\uc5c8\uc2b5\ub2c8\ub2e4"
                                    )
                                    noti_content = (
                                        f"{episode_no}\ud654. {episode_title}"
                                    )

                                    for user in bookmarked_users:
                                        query = text("""
                                            insert into tb_user_notification_item
                                            (user_id, noti_type, title, content, read_yn, created_id, created_date)
                                            values (:user_id, 'benefit', :title, :content, 'N', :created_id, NOW())
                                        """)
                                        await db.execute(
                                            query,
                                            {
                                                "user_id": user.get("user_id"),
                                                "title": noti_title,
                                                "content": noti_content,
                                                "created_id": user_id,
                                            },
                                        )

                                    # TODO: cleaned garbled comment (encoding issue).
                            except Exception as e:
                                # TODO: cleaned garbled comment (encoding issue).
                                logger.error(
                                    f"Failed to send episode update notification: {e}"
                                )
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
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


async def put_episodes_episode_id_paid(
    episode_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    episode_id_to_int = int(episode_id)

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                query = text("""
                                 select coalesce(price_type, 'free') as price_type
                                   from tb_product_episode
                                  where episode_id = :episode_id
                                    and use_yn = 'Y'
                                 """)

                result = await db.execute(query, {"episode_id": episode_id_to_int})
                db_rst = result.mappings().all()

                if db_rst:
                    price_type = db_rst[0].get("price_type")

                    # TODO: cleaned garbled comment (encoding issue).
                    query = text("""
                                     update tb_product_episode a
                                        set a.price_type = (case when a.price_type is null or a.price_type = 'free' then 'paid' else 'free' end)
                                          , a.updated_id = :user_id
                                      where a.episode_id = :episode_id
                                        and a.use_yn = 'Y'
                                        and exists (select 1 from tb_product z
                                                     where a.product_id = z.product_id
                                                       and z.user_id = :user_id
                                                       and z.price_type = 'paid')
                                     """)

                    result = await db.execute(
                        query, {"episode_id": episode_id_to_int, "user_id": user_id}
                    )

                    if price_type == "free":
                        # N -> Y
                        episode_price_type = "paid"
                    else:
                        # Y -> N
                        episode_price_type = "free"

                    # TODO: cleaned garbled comment (encoding issue).
                    if result.rowcount != 0:
                        res_data = {
                            "episodeId": episode_id_to_int,
                            "priceType": episode_price_type,
                        }
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
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


async def put_episodes_episode_id_reaction(
    episode_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    episode_id_to_int = int(episode_id)

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                query = text("""
                                 select product_id
                                   from tb_product_episode
                                  where episode_id = :episode_id
                                    and use_yn = 'Y'
                                 """)

                result = await db.execute(query, {"episode_id": episode_id_to_int})
                db_rst = result.mappings().all()

                if db_rst:
                    product_id = db_rst[0].get("product_id")

                    query = text("""
                                     select id
                                          , recommend_yn
                                       from tb_user_product_usage
                                      where user_id = :user_id
                                        and product_id = :product_id
                                        and episode_id = :episode_id
                                     """)

                    result = await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "product_id": product_id,
                            "episode_id": episode_id_to_int,
                        },
                    )
                    db_rst = result.mappings().all()

                    if db_rst:
                        # tb_user_product_usage upd
                        id = db_rst[0].get("id")
                        thumbs_up_yn = db_rst[0].get("recommend_yn")

                        # TODO: cleaned garbled comment (encoding issue).
                        query = text("""
                                         update tb_user_product_usage
                                            set recommend_yn = (case when recommend_yn = 'Y' then 'N' else 'Y' end)
                                              , updated_id = :user_id
                                          where id = :id
                                         """)

                        await db.execute(query, {"id": id, "user_id": user_id})

                        if thumbs_up_yn == "N":
                            # N -> Y
                            recommend_yn = "Y"
                        else:
                            # Y -> N
                            recommend_yn = "N"
                    else:
                        # tb_user_product_usage ins
                        query = text("""
                                         insert into tb_user_product_usage (user_id, product_id, episode_id, created_id, updated_id)
                                         values (:user_id, :product_id, :episode_id, :created_id, :updated_id)
                                         """)

                        await db.execute(
                            query,
                            {
                                "user_id": user_id,
                                "product_id": product_id,
                                "episode_id": episode_id_to_int,
                                "created_id": settings.DB_DML_DEFAULT_ID,
                                "updated_id": settings.DB_DML_DEFAULT_ID,
                            },
                        )

                        # TODO: cleaned garbled comment (encoding issue).
                        recommend_yn = "Y"

                    # TODO: cleaned garbled comment (encoding issue).
                    query = text("""
                                     update tb_product_episode a
                                      inner join (
                                         select z.product_id
                                              , z.episode_id
                                              , sum(case when z.recommend_yn = 'Y' then 1 else 0 end) as count_recommend
                                           from tb_user_product_usage z
                                          where z.product_id = :product_id
                                            and z.episode_id = :episode_id
                                            and z.use_yn = 'Y'
                                          group by z.product_id, z.episode_id
                                       ) as t on a.product_id = t.product_id and a.episode_id = t.episode_id
                                        set a.count_recommend = t.count_recommend
                                      where 1=1
                                     """)

                    await db.execute(
                        query,
                        {"product_id": product_id, "episode_id": episode_id_to_int},
                    )

                    query = text("""
                                     update tb_product a
                                      inner join (
                                         select z.product_id
                                              , sum(case when z.recommend_yn = 'Y' then 1 else 0 end) as count_recommend
                                           from tb_user_product_usage z
                                          where z.product_id = :product_id
                                            and z.use_yn = 'Y'
                                          group by z.product_id
                                       ) as t on a.product_id = t.product_id
                                        set a.count_recommend = t.count_recommend
                                      where 1=1
                                     """)

                    await db.execute(query, {"product_id": product_id})

                    res_data = {
                        "episodeId": episode_id_to_int,
                        "recommendYn": recommend_yn,
                    }
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
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


async def post_episodes_episode_id_evaluation(
    episode_id: str,
    req_body: episode_schema.PostEpisodesEpisodeIdEvaluationReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    episode_id_to_int = int(episode_id)

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                query = text("""
                                 select product_id
                                   from tb_product_episode
                                  where episode_id = :episode_id
                                    and use_yn = 'Y'
                                 """)

                result = await db.execute(query, {"episode_id": episode_id_to_int})
                db_rst = result.mappings().all()

                if db_rst:
                    product_id = db_rst[0].get("product_id")

                    # TODO: cleaned garbled comment (encoding issue).
                    query = text("""
                                     select 1
                                       from tb_common_code
                                      where code_group = 'PROD_EVAL_CODE'
                                        and code_key = :code_key
                                        and use_yn = 'Y'
                                     """)

                    result = await db.execute(query, {"code_key": req_body.rating})
                    db_rst = result.mappings().all()

                    if db_rst:
                        query = text("""
                                         select 1
                                           from tb_product_evaluation
                                          where user_id = :user_id
                                            and product_id = :product_id
                                            and episode_id = :episode_id
                                         """)

                        result = await db.execute(
                            query,
                            {
                                "user_id": user_id,
                                "product_id": product_id,
                                "episode_id": episode_id_to_int,
                            },
                        )
                        db_rst = result.mappings().all()

                        if db_rst:
                            pass
                        else:
                            query = text("""
                                             insert into tb_product_evaluation (product_id, episode_id, user_id, eval_code, created_id, updated_id)
                                             values (:product_id, :episode_id, :user_id, :eval_code, :created_id, :updated_id)
                                             """)

                            await db.execute(
                                query,
                                {
                                    "user_id": user_id,
                                    "product_id": product_id,
                                    "episode_id": episode_id_to_int,
                                    "eval_code": req_body.rating,
                                    "created_id": settings.DB_DML_DEFAULT_ID,
                                    "updated_id": settings.DB_DML_DEFAULT_ID,
                                },
                            )

                            # TODO: cleaned garbled comment (encoding issue).
                            query = text("""
                                             update tb_product_episode
                                                set count_evaluation = count_evaluation + 1
                                              where episode_id = :episode_id
                                             """)

                            await db.execute(query, {"episode_id": episode_id_to_int})
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    return


async def check_like_product_episode(
    episode_id: int, kc_user_id: str, db: AsyncSession
):
    """
    Check whether the current user already liked the episode.
    """
    query = text("""
        select count(*) as cnt from tb_product_episode_like
        where product_id = (select product_id from tb_product_episode where episode_id = :episode_id)
          and episode_id = :episode_id
          and user_id = (select user_id from tb_user where kc_user_id = :kc_user_id)
    """)
    result = await db.execute(
        query, {"episode_id": episode_id, "kc_user_id": kc_user_id}
    )
    db_rst = result.mappings().all()
    cnt = db_rst[0].get("cnt")
    return cnt > 0


async def add_like_product_episode(episode_id: int, kc_user_id: str, db: AsyncSession):
    """
    Add like to an episode.
    """
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    check = await check_like_product_episode(episode_id, kc_user_id, db)
    if check is True:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST, message=ErrorMessages.ALREADY_LIKED
        )

    query = text("""
        insert into tb_product_episode_like (product_id, episode_id, user_id)
        values (
            (select product_id from tb_product_episode where episode_id = :episode_id),
            :episode_id,
            :user_id
        )
    """)
    await db.execute(query, {"episode_id": episode_id, "user_id": user_id})

    # TODO: cleaned garbled comment (encoding issue).
    query = text("""
        update tb_product_episode
        set count_recommend = (select count(*) from tb_product_episode_like where episode_id = :episode_id)
        where episode_id = :episode_id
    """)
    await db.execute(query, {"episode_id": episode_id})

    # TODO: cleaned garbled comment (encoding issue).
    query = text("""
        update tb_product
        set count_recommend = (
            select count(*) from tb_product_episode_like
            where product_id = (select product_id from tb_product_episode where episode_id = :episode_id)
        )
        where product_id = (select product_id from tb_product_episode where episode_id = :episode_id)
    """)
    await db.execute(query, {"episode_id": episode_id})

    return {"result": True}


async def remove_like_product_episode(
    episode_id: int, kc_user_id: str, db: AsyncSession
):
    """
    Remove like from an episode.
    """
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    check = await check_like_product_episode(episode_id, kc_user_id, db)
    if check is False:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST, message=ErrorMessages.NOT_LIKED_YET
        )

    query = text("""
        delete from tb_product_episode_like
        where product_id = (select product_id from tb_product_episode where episode_id = :episode_id)
          and episode_id = :episode_id
          and user_id = :user_id
    """)
    await db.execute(query, {"episode_id": episode_id, "user_id": user_id})

    # TODO: cleaned garbled comment (encoding issue).
    query = text("""
        update tb_product_episode
        set count_recommend = (select count(*) from tb_product_episode_like where episode_id = :episode_id)
        where episode_id = :episode_id
    """)
    await db.execute(query, {"episode_id": episode_id})

    # TODO: cleaned garbled comment (encoding issue).
    query = text("""
        update tb_product
        set count_recommend = (
            select count(*) from tb_product_episode_like
            where product_id = (select product_id from tb_product_episode where episode_id = :episode_id)
        )
        where product_id = (select product_id from tb_product_episode where episode_id = :episode_id)
    """)
    await db.execute(query, {"episode_id": episode_id})

    return {"result": True}
