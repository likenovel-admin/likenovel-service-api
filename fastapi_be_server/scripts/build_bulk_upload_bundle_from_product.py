#!/usr/bin/env python3
"""기존 업로드 작품에서 CMS 일괄업로드용 xlsx/zip을 생성한다.

지원 범위
- source product_id 기준 메타/회차/표지를 조회
- 회차 EPUB에서 section0001.xhtml 본문을 우선 추출해 txt로 변환
- CMS 일괄업로드용 `bulk-upload.xlsx`, `episodes.zip` 생성

기본값
- 공개여부: N
- 최초공개회차: 선택된 마지막 회차 번호
- 예약공개시작일: KST 기준 내일
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import unescape
from io import BytesIO
from pathlib import Path
from typing import Iterable
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED

import pymysql
from httpx import AsyncClient, HTTPStatusError, RequestError
from openpyxl import Workbook
from pymysql.constants import CLIENT
from pymysql.cursors import DictCursor

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.const import settings  # noqa: E402
from app.services.common import comm_service  # noqa: E402
from app.services.product.episode_service import (  # noqa: E402
    _extract_epub_document_parts,
    _extract_epub_payload_from_epub,
)

DB_HOST = os.getenv("BATCH_DB_HOST", settings.DB_IP or "127.0.0.1")
DB_PORT = int(os.getenv("BATCH_DB_PORT", settings.DB_PORT or "3306"))
DB_USER = os.getenv("BATCH_DB_USER", settings.DB_USER_ID or "")
DB_PASSWORD = os.getenv("BATCH_DB_PASSWORD", settings.DB_USER_PW or "")
DB_NAME = os.getenv("BATCH_DB_NAME", "likenovel")

SECTION_PATTERN = re.compile(r"(^|/)section0*1\.(xhtml|xhtm|html|htm)$", re.IGNORECASE)
GENERIC_SECTION_PATTERN = re.compile(r"(^|/)section\d+\.(xhtml|xhtm|html|htm)$", re.IGNORECASE)
DAY_ORDER = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
DAY_LABEL = {
    "MON": "월",
    "TUE": "화",
    "WED": "수",
    "THU": "목",
    "FRI": "금",
    "SAT": "토",
    "SUN": "일",
}
RATING_TO_BULK = {"all": "all", "15": "15", "adult": "19"}
INLINE_WHITESPACE_PATTERN = re.compile(r"[^\S\n]+")
SCRIPT_STYLE_PATTERN = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\\1>", re.IGNORECASE | re.DOTALL)
BR_TAG_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
BLOCK_ELEMENT_PATTERN = re.compile(
    r"<(?P<tag>h[1-6]|p|li|blockquote|pre)\b[^>]*>(?P<inner>.*?)</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)
GENERIC_TAG_PATTERN = re.compile(r"<[^>]+>")


@dataclass
class ProductMeta:
    product_id: int
    title: str
    email: str
    nickname: str
    author_name: str
    genre1: str
    genre2: str
    tags: list[str]
    rating: str
    monopoly: str
    contract: str
    open_yn: str
    synopsis: str
    schedule_days: str
    cover_file_name: str | None
    cover_org_name: str | None


@dataclass
class EpisodeAsset:
    episode_id: int
    episode_no: int
    episode_title: str
    epub_file_name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="작품 -> CMS 일괄업로드 번들 생성")
    parser.add_argument("--product-id", type=int, required=True, help="원본 작품 ID")
    parser.add_argument(
        "--source-epub-dir",
        type=Path,
        default=None,
        help="원본 EPUB 폴더. 지정 시 파트너 저장 EPUB 대신 '<회차번호>.epub' 파일을 직접 읽음",
    )
    parser.add_argument("--episode-start", type=int, default=1, help="포함 시작 회차")
    parser.add_argument("--episode-end", type=int, default=0, help="포함 종료 회차. 0이면 마지막 회차까지")
    parser.add_argument("--title", type=str, default="", help="생성용 작품명 override")
    parser.add_argument("--email", type=str, default="", help="생성용 작가 이메일 override")
    parser.add_argument("--nickname", type=str, default="", help="생성용 작가 닉네임 override")
    parser.add_argument("--schedule-days", type=str, default="", help="연재주기 override. 예: 월화수목금토일")
    parser.add_argument("--first-open-episode", type=int, default=0, help="최초공개회차 override")
    parser.add_argument("--start-date", type=str, default="", help="예약공개시작일 override (YYYY-MM-DD)")
    parser.add_argument("--open-yn", type=str, default="N", choices=["Y", "N"], help="일괄업로드 공개여부")
    parser.add_argument("--include-cover", action="store_true", help="원본 표지를 ZIP에 포함")
    parser.add_argument("--out-dir", type=Path, default=None, help="출력 디렉터리")
    parser.add_argument("--verbose", action="store_true", help="상세 로그 출력")
    return parser.parse_args()


def db_connect():
    if not DB_USER or not DB_PASSWORD:
        raise RuntimeError("DB 접속 정보가 없습니다. BATCH_DB_USER/BATCH_DB_PASSWORD 또는 앱 DB 환경변수를 확인하세요.")
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        autocommit=False,
        client_flag=CLIENT.MULTI_STATEMENTS,
        cursorclass=DictCursor,
    )


def sanitize_title_for_zip(title: str) -> str:
    return title.replace("/", "／").replace("\\", "＼").strip()


def normalize_kst_date(date_str: str) -> str:
    if date_str:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


def load_local_epub_binary(source_epub_dir: Path, episode_no: int) -> bytes:
    epub_path = source_epub_dir / f"{episode_no}.epub"
    if not epub_path.exists():
        raise RuntimeError(f"원본 EPUB를 찾을 수 없습니다: {epub_path}")
    return epub_path.read_bytes()


def json_publish_days_to_korean(raw: str) -> str:
    if not raw:
        return "월화수목금토일"
    try:
        payload = json.loads(raw)
        selected = [DAY_LABEL[key] for key in DAY_ORDER if payload.get(key) == "Y"]
        return "".join(selected) if selected else "월화수목금토일"
    except json.JSONDecodeError:
        return raw


def extract_text_from_html(html_content: str) -> str:
    sanitized = SCRIPT_STYLE_PATTERN.sub("", html_content or "")
    paragraphs: list[str] = []

    def normalize_lines(raw_text: str) -> list[str]:
        normalized_lines: list[str] = []
        prepared = BR_TAG_PATTERN.sub("\n", raw_text)
        prepared = GENERIC_TAG_PATTERN.sub("", prepared)
        for line in prepared.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            normalized = INLINE_WHITESPACE_PATTERN.sub(" ", unescape(line).replace("\xa0", " ")).strip()
            if normalized:
                normalized_lines.append(normalized)
        return normalized_lines

    for match in BLOCK_ELEMENT_PATTERN.finditer(sanitized):
        lines = normalize_lines(match.group("inner") or "")
        if not lines:
            continue
        paragraphs.extend(lines)

    return "\n\n".join(paragraphs).strip()


def select_preferred_section(epub_binary: bytes) -> str | None:
    try:
        with ZipFile(BytesIO(epub_binary)) as epub_zip:
            names = [name for name in epub_zip.namelist() if not name.endswith("/")]
            preferred = next((name for name in names if SECTION_PATTERN.search(name)), None)
            if not preferred:
                preferred = next((name for name in names if GENERIC_SECTION_PATTERN.search(name)), None)
            if not preferred:
                return None
            html_bytes = epub_zip.read(preferred)
            return html_bytes.decode("utf-8", errors="ignore")
    except (BadZipFile, KeyError, ValueError):
        return None


def extract_txt_from_epub(epub_binary: bytes) -> str:
    preferred = select_preferred_section(epub_binary)
    if preferred is not None:
        return extract_text_from_html(preferred)

    payload = _extract_epub_payload_from_epub(epub_binary)
    html_content = str(payload.get("html_content") or "")
    return extract_text_from_html(html_content)


async def download_epub_binary(file_name: str) -> bytes:
    presigned_url = comm_service.make_r2_presigned_url(
        type="download",
        bucket_name=settings.R2_SC_EPUB_BUCKET,
        file_id=file_name,
    )
    async with AsyncClient(timeout=120.0) as client:
        response = await client.get(presigned_url)
        response.raise_for_status()
        return response.content


async def download_cover_binary(file_name: str) -> bytes:
    presigned_url = comm_service.make_r2_presigned_url(
        type="download",
        bucket_name=settings.R2_SC_IMAGE_BUCKET,
        file_id=f"cover/{file_name}",
    )
    async with AsyncClient(timeout=120.0) as client:
        response = await client.get(presigned_url)
        response.raise_for_status()
        return response.content


def load_product_meta(conn, product_id: int) -> ProductMeta:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                p.product_id,
                p.title,
                COALESCE(u.email, '') AS email,
                COALESCE(up.nickname, '') AS nickname,
                COALESCE(p.author_name, '') AS author_name,
                COALESCE(g1.keyword_name, '') AS genre1,
                COALESCE(g2.keyword_name, '') AS genre2,
                COALESCE(p.ratings_code, 'all') AS ratings_code,
                COALESCE(p.monopoly_yn, 'N') AS monopoly_yn,
                COALESCE(p.contract_yn, 'N') AS contract_yn,
                COALESCE(p.open_yn, 'N') AS open_yn,
                COALESCE(p.synopsis_text, '') AS synopsis_text,
                COALESCE(p.publish_days, '') AS publish_days,
                cfi.file_name AS cover_file_name,
                cfi.file_org_name AS cover_org_name
            FROM tb_product p
            LEFT JOIN tb_user u
              ON u.user_id = p.user_id
            LEFT JOIN tb_user_profile up
              ON up.user_id = p.user_id
             AND up.default_yn = 'Y'
            LEFT JOIN tb_standard_keyword g1
              ON g1.keyword_id = p.primary_genre_id
            LEFT JOIN tb_standard_keyword g2
              ON g2.keyword_id = p.sub_genre_id
            LEFT JOIN tb_common_file cf
              ON cf.file_group_id = p.thumbnail_file_id
             AND cf.use_yn = 'Y'
            LEFT JOIN tb_common_file_item cfi
              ON cfi.file_group_id = cf.file_group_id
             AND cfi.use_yn = 'Y'
            WHERE p.product_id = %s
            LIMIT 1
            """,
            (product_id,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"product_id={product_id} 작품을 찾지 못했습니다.")

        cur.execute(
            """
            SELECT sk.keyword_name
            FROM tb_mapped_product_keyword mpk
            INNER JOIN tb_standard_keyword sk
              ON sk.keyword_id = mpk.keyword_id
             AND sk.use_yn = 'Y'
            WHERE mpk.product_id = %s
            ORDER BY sk.keyword_name ASC
            """,
            (product_id,),
        )
        tags = [item["keyword_name"] for item in cur.fetchall()]

    return ProductMeta(
        product_id=int(row["product_id"]),
        title=str(row["title"] or ""),
        email=str(row["email"] or ""),
        nickname=str(row["nickname"] or ""),
        author_name=str(row["author_name"] or ""),
        genre1=str(row["genre1"] or ""),
        genre2=str(row["genre2"] or ""),
        tags=tags,
        rating=RATING_TO_BULK.get(str(row["ratings_code"] or "all"), "all"),
        monopoly=str(row["monopoly_yn"] or "N"),
        contract=str(row["contract_yn"] or "N"),
        open_yn=str(row["open_yn"] or "N"),
        synopsis=str(row["synopsis_text"] or ""),
        schedule_days=json_publish_days_to_korean(str(row["publish_days"] or "")),
        cover_file_name=row.get("cover_file_name"),
        cover_org_name=row.get("cover_org_name"),
    )


def load_episodes(conn, product_id: int, episode_start: int, episode_end: int) -> list[EpisodeAsset]:
    params: list[int] = [product_id, episode_start]
    end_sql = ""
    if episode_end > 0:
        end_sql = "AND pe.episode_no <= %s"
        params.append(episode_end)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                pe.episode_id,
                pe.episode_no,
                COALESCE(pe.episode_title, '') AS episode_title,
                cfi.file_name AS epub_file_name
            FROM tb_product_episode pe
            INNER JOIN tb_common_file cf
              ON cf.file_group_id = pe.epub_file_id
             AND cf.group_type = 'epub'
             AND cf.use_yn = 'Y'
            INNER JOIN tb_common_file_item cfi
              ON cfi.file_group_id = cf.file_group_id
             AND cfi.use_yn = 'Y'
            WHERE pe.product_id = %s
              AND pe.use_yn = 'Y'
              AND pe.episode_no >= %s
              {end_sql}
            ORDER BY pe.episode_no ASC
            """,
            params,
        )
        rows = cur.fetchall()

    episodes = [
        EpisodeAsset(
            episode_id=int(row["episode_id"]),
            episode_no=int(row["episode_no"]),
            episode_title=str(row["episode_title"] or ""),
            epub_file_name=str(row["epub_file_name"] or ""),
        )
        for row in rows
        if row.get("epub_file_name")
    ]
    if not episodes:
        raise RuntimeError("선택 범위에 EPUB이 연결된 회차가 없습니다.")
    return episodes


def write_workbook(
    out_path: Path,
    *,
    email: str,
    nickname: str,
    title: str,
    genre1: str,
    genre2: str,
    tags: Iterable[str],
    rating: str,
    monopoly: str,
    contract: str,
    open_yn: str,
    synopsis: str,
    schedule_days: str,
    first_open_episode: int,
    start_date: str,
) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "bulk-upload"
    headers = [
        "작가이메일",
        "작가닉네임",
        "작품제목",
        "1차장르",
        "2차장르",
        "태그",
        "연령등급",
        "독점여부",
        "계약여부",
        "공개여부",
        "시놉시스",
        "연재주기",
        "최초공개회차",
        "예약공개시작일",
    ]
    ws.append(headers)
    ws.append(
        [
            email,
            nickname,
            title,
            genre1,
            genre2,
            ", ".join(tags),
            rating,
            monopoly,
            contract,
            open_yn,
            synopsis,
            schedule_days,
            first_open_episode,
            start_date,
        ]
    )
    for idx, width in enumerate((28, 20, 40, 16, 16, 24, 10, 10, 10, 10, 70, 16, 14, 18), start=1):
        ws.column_dimensions[chr(64 + idx)].width = width
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


async def build_bundle(args: argparse.Namespace) -> dict:
    with db_connect() as conn:
        meta = load_product_meta(conn, args.product_id)
        episodes = load_episodes(conn, args.product_id, args.episode_start, args.episode_end)

    title = sanitize_title_for_zip(args.title or meta.title)
    email = args.email or meta.email
    nickname = args.nickname or meta.nickname or meta.author_name
    schedule_days = args.schedule_days or meta.schedule_days
    first_open_episode = args.first_open_episode or episodes[-1].episode_no
    start_date = normalize_kst_date(args.start_date)

    if not email:
        raise RuntimeError("작가 이메일이 비어 있습니다. --email로 지정하세요.")
    if not nickname:
        raise RuntimeError("작가 닉네임이 비어 있습니다. --nickname으로 지정하세요.")
    if not meta.genre1:
        raise RuntimeError("원본 작품의 1차 장르가 비어 있습니다.")
    if args.source_epub_dir and not args.source_epub_dir.exists():
        raise RuntimeError(f"원본 EPUB 폴더가 없습니다: {args.source_epub_dir}")

    output_dir = args.out_dir or (Path.cwd() / "output" / "spreadsheet" / f"bulk-upload-product-{args.product_id}")
    output_dir.mkdir(parents=True, exist_ok=True)
    excel_path = output_dir / "bulk-upload.xlsx"
    zip_path = output_dir / "episodes.zip"
    manifest_path = output_dir / "manifest.json"

    cover_bytes = None
    cover_ext = ".jpg"
    if args.include_cover and meta.cover_file_name:
        try:
            cover_bytes = await download_cover_binary(meta.cover_file_name)
            cover_ext = Path(meta.cover_org_name or meta.cover_file_name).suffix or ".jpg"
        except (HTTPStatusError, RequestError):
            cover_bytes = None

    write_workbook(
        excel_path,
        email=email,
        nickname=nickname,
        title=title,
        genre1=meta.genre1,
        genre2=meta.genre2,
        tags=meta.tags,
        rating=meta.rating,
        monopoly=meta.monopoly,
        contract=meta.contract,
        open_yn=args.open_yn,
        synopsis=meta.synopsis,
        schedule_days=schedule_days,
        first_open_episode=first_open_episode,
        start_date=start_date,
    )

    manifest = {
        "source_product_id": args.product_id,
        "source_title": meta.title,
        "output_title": title,
        "email": email,
        "nickname": nickname,
        "episode_start": args.episode_start,
        "episode_end": episodes[-1].episode_no,
        "episode_count": len(episodes),
        "first_open_episode": first_open_episode,
        "schedule_days": schedule_days,
        "start_date": start_date,
        "open_yn": args.open_yn,
        "include_cover": args.include_cover,
        "source_epub_dir": str(args.source_epub_dir) if args.source_epub_dir else "",
        "generated_at": datetime.now().isoformat(),
        "episodes": [],
    }

    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as bundle_zip:
        if cover_bytes:
            bundle_zip.writestr(f"{title}/cover{cover_ext}", cover_bytes)
        for episode in episodes:
            if args.source_epub_dir:
                epub_binary = load_local_epub_binary(args.source_epub_dir, episode.episode_no)
            else:
                epub_binary = await download_epub_binary(episode.epub_file_name)
            txt_content = extract_txt_from_epub(epub_binary)
            file_name = f"{title} {episode.episode_no}화.txt"
            bundle_zip.writestr(f"{title}/{file_name}", txt_content)
            manifest["episodes"].append(
                {
                    "episode_id": episode.episode_id,
                    "episode_no": episode.episode_no,
                    "source_title": episode.episode_title,
                    "bundle_file_name": file_name,
                }
            )
            if args.verbose:
                print(f"[ok] episode_no={episode.episode_no} episode_id={episode.episode_id}")

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "excel": str(excel_path),
        "zip": str(zip_path),
        "manifest": str(manifest_path),
        "episode_count": len(episodes),
        "title": title,
    }


def main() -> int:
    args = parse_args()
    result = asyncio.run(build_bundle(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
