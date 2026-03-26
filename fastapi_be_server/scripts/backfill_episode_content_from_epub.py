#!/usr/bin/env python3
"""EPUB 업로드본에서 회차 본문(episode_content)을 백필하는 배치.

기본 정책
- 대상은 이미 업로드된 회차(`epub_file_id` 존재)
- 구조가 `cover.xhtml / section0001.xhtml / copyright.xhtml`인 EPUB을 우선 지원
- `section0001.xhtml` 본문만 우선 추출
- `section0001`이 없으면 기존 업로드 로직과 동일한 fallback 추출 사용
- 기본은 dry-run, `--apply`일 때만 DB 업데이트
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from io import BytesIO
from pathlib import Path
from typing import Iterable
from zipfile import BadZipFile, ZipFile

import pymysql
from httpx import AsyncClient, HTTPStatusError, RequestError
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

DB_HOST = os.getenv("BATCH_DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("BATCH_DB_PORT", "13306"))
DB_USER = os.getenv("BATCH_DB_USER", "ln_root")
DB_PASSWORD = os.getenv("BATCH_DB_PASSWORD", "")
DB_NAME = os.getenv("BATCH_DB_NAME", "likenovel")

SECTION_PATTERN = re.compile(r"(^|/)section0*1\.(xhtml|xhtm|html|htm)$", re.IGNORECASE)
GENERIC_SECTION_PATTERN = re.compile(r"(^|/)section\d+\.(xhtml|xhtm|html|htm)$", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EPUB 본문 백필 배치")
    parser.add_argument("--product-id", type=int, action="append", dest="product_ids", help="대상 작품 ID. 여러 번 지정 가능")
    parser.add_argument("--episode-id", type=int, action="append", dest="episode_ids", help="대상 회차 ID. 여러 번 지정 가능")
    parser.add_argument("--only-empty", action="store_true", help="episode_content가 비어 있는 회차만 대상")
    parser.add_argument("--limit", type=int, default=0, help="대상 제한 건수")
    parser.add_argument("--apply", action="store_true", help="실제 DB 업데이트 수행")
    parser.add_argument("--verbose", action="store_true", help="회차별 처리 로그 출력")
    return parser.parse_args()


def db_connect():
    if not DB_USER or not DB_PASSWORD:
        raise RuntimeError("BATCH_DB_USER/BATCH_DB_PASSWORD 환경변수를 설정하세요.")
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


def build_target_query(args: argparse.Namespace) -> tuple[str, list[object]]:
    where = [
        "pe.use_yn = 'Y'",
        "pe.epub_file_id IS NOT NULL",
        "cf.group_type = 'epub'",
        "cf.use_yn = 'Y'",
        "cfi.use_yn = 'Y'",
    ]
    params: list[object] = []

    if args.only_empty:
        where.append("COALESCE(TRIM(pe.episode_content), '') = ''")

    if args.product_ids:
        placeholders = ", ".join(["%s"] * len(args.product_ids))
        where.append(f"pe.product_id IN ({placeholders})")
        params.extend(args.product_ids)

    if args.episode_ids:
        placeholders = ", ".join(["%s"] * len(args.episode_ids))
        where.append(f"pe.episode_id IN ({placeholders})")
        params.extend(args.episode_ids)

    where_sql = " AND ".join(where)
    limit_sql = ""
    if args.limit and args.limit > 0:
        limit_sql = f" LIMIT {int(args.limit)}"

    query = f"""
        SELECT
            pe.episode_id,
            pe.product_id,
            pe.episode_no,
            pe.episode_title,
            pe.episode_content,
            pe.episode_text_count,
            pe.epub_file_id,
            cfi.file_name,
            cfi.file_org_name,
            cfi.file_path
        FROM tb_product_episode pe
        JOIN tb_common_file cf
          ON cf.file_group_id = pe.epub_file_id
        JOIN tb_common_file_item cfi
          ON cfi.file_group_id = cf.file_group_id
        WHERE {where_sql}
        ORDER BY pe.product_id ASC, pe.episode_no ASC
        {limit_sql}
    """
    return query, params


async def download_epub_binary(file_name: str) -> bytes | None:
    presigned_url = comm_service.make_r2_presigned_url(
        type="download",
        bucket_name=settings.R2_SC_EPUB_BUCKET,
        file_id=file_name,
    )
    try:
        async with AsyncClient(timeout=120.0) as client:
            response = await client.get(presigned_url)
            response.raise_for_status()
            return response.content
    except (HTTPStatusError, RequestError):
        return None


def select_preferred_section(epub_binary: bytes) -> tuple[str, str] | None:
    try:
        with ZipFile(BytesIO(epub_binary)) as epub_zip:
            names = [name for name in epub_zip.namelist() if not name.endswith("/")]
            preferred = next((name for name in names if SECTION_PATTERN.search(name)), None)
            if not preferred:
                preferred = next((name for name in names if GENERIC_SECTION_PATTERN.search(name)), None)
            if not preferred:
                return None
            html_bytes = epub_zip.read(preferred)
            return _extract_epub_document_parts(html_bytes)
    except (BadZipFile, KeyError, ValueError):
        return None


def extract_payload(epub_binary: bytes) -> tuple[str, int, str]:
    preferred = select_preferred_section(epub_binary)
    if preferred is not None:
        html_content, text_content = preferred
        return html_content, len(text_content), "section0001"

    payload = _extract_epub_payload_from_epub(epub_binary)
    html_content = str(payload.get("html_content") or "")
    text_count = int(payload.get("text_count") or 0)
    return html_content, text_count, "fallback"


async def collect_updates(rows: Iterable[dict], verbose: bool = False) -> list[dict]:
    updates: list[dict] = []
    for row in rows:
        episode_id = int(row["episode_id"])
        file_name = row.get("file_name")
        if not file_name:
            if verbose:
                print(f"[skip] episode_id={episode_id} file_name missing")
            continue

        epub_binary = await download_epub_binary(str(file_name))
        if epub_binary is None:
            if verbose:
                print(f"[skip] episode_id={episode_id} download failed")
            continue

        try:
            html_content, text_count, mode = extract_payload(epub_binary)
        except Exception as exc:
            if verbose:
                print(f"[skip] episode_id={episode_id} extract failed: {exc}")
            continue

        if not html_content.strip():
            if verbose:
                print(f"[skip] episode_id={episode_id} empty content")
            continue

        updates.append(
            {
                "episode_id": episode_id,
                "product_id": int(row["product_id"]),
                "episode_no": int(row["episode_no"] or 0),
                "title": row.get("episode_title") or "",
                "text_count": text_count,
                "content": html_content,
                "mode": mode,
                "prev_text_count": int(row.get("episode_text_count") or 0),
                "prev_content_empty": "Y" if not (row.get("episode_content") or "").strip() else "N",
            }
        )
        if verbose:
            print(
                f"[ok] episode_id={episode_id} product_id={row['product_id']} episode_no={row['episode_no']} mode={mode} text_count={text_count}"
            )
    return updates


def apply_updates(conn, updates: list[dict]) -> int:
    if not updates:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            UPDATE tb_product_episode
               SET episode_content = %s,
                   episode_text_count = %s,
                   updated_id = %s
             WHERE episode_id = %s
            """,
            [
                (
                    item["content"],
                    item["text_count"],
                    settings.DB_DML_DEFAULT_ID,
                    item["episode_id"],
                )
                for item in updates
            ],
        )
    conn.commit()
    return len(updates)


def print_summary(updates: list[dict], apply: bool) -> None:
    print(f"target_updates={len(updates)} mode={'apply' if apply else 'dry-run'}")
    if not updates:
        return

    section_count = sum(1 for item in updates if item["mode"] == "section0001")
    fallback_count = len(updates) - section_count
    print(f"section0001={section_count} fallback={fallback_count}")

    for sample in updates[:10]:
        print(
            "sample",
            f"product_id={sample['product_id']}",
            f"episode_no={sample['episode_no']}",
            f"episode_id={sample['episode_id']}",
            f"prev_empty={sample['prev_content_empty']}",
            f"text_count={sample['text_count']}",
            f"mode={sample['mode']}",
            f"title={sample['title']}",
        )


async def async_main(args: argparse.Namespace) -> int:
    query, params = build_target_query(args)
    conn = db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

        print(f"selected_rows={len(rows)}")
        updates = await collect_updates(rows, verbose=args.verbose)
        print_summary(updates, apply=args.apply)

        if args.apply:
            updated_count = apply_updates(conn, updates)
            print(f"updated_rows={updated_count}")
        else:
            conn.rollback()
        return 0
    finally:
        conn.close()


def main() -> int:
    args = parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
