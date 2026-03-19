#!/usr/bin/env python3
"""
깨진 EPUB cover.xhtml 복구용 원오프 스크립트.

- 기존 tb_product_episode.epub_file_id가 가리키는 R2 key를 그대로 재사용한다.
- 대상 회차의 EPUB만 다시 생성해서 기존 file_name(R2 key)에 덮어쓴다.
- DB 메타는 그대로 두고, EPUB 파일만 교체한다.

사용법 (컨테이너 내부):
  python3 /app/dist/batch/repair_epub_cover_xhtml.py --episode-id 6236 --dry-run
  python3 /app/dist/batch/repair_epub_cover_xhtml.py --episode-id 6236
  python3 /app/dist/batch/repair_epub_cover_xhtml.py --product-id 673
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import pymysql

APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.const import settings  # noqa: E402
import app.services.common.comm_service as comm_service  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair malformed EPUB cover.xhtml")
    parser.add_argument("--episode-id", type=int, help="단일 회차만 복구")
    parser.add_argument("--product-id", type=int, help="작품의 모든 회차 복구")
    parser.add_argument(
        "--episode-id-file",
        type=str,
        help="복구 대상 episode_id 목록 파일(줄바꿈 또는 콤마 구분)",
    )
    parser.add_argument("--dry-run", action="store_true", help="대상만 출력하고 종료")
    args = parser.parse_args()

    if not args.episode_id and not args.product_id and not args.episode_id_file:
        parser.error("--episode-id, --product-id, --episode-id-file 중 하나는 필요합니다.")

    return args


def get_connection():
    return pymysql.connect(
        host=settings.DB_IP,
        port=int(settings.DB_PORT),
        user=settings.DB_USER_ID,
        password=settings.DB_USER_PW,
        database="likenovel",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def read_episode_ids(file_path: str | None) -> list[int]:
    if not file_path:
        return []

    raw = Path(file_path).read_text(encoding="utf-8")
    tokens = [token.strip() for token in raw.replace(",", "\n").splitlines()]
    episode_ids: list[int] = []

    for token in tokens:
        if not token:
            continue
        episode_ids.append(int(token))

    return episode_ids


def fetch_targets(
    conn,
    episode_id: int | None,
    product_id: int | None,
    episode_ids: list[int],
):
    where_clauses = ["e.use_yn = 'Y'", "e.epub_file_id IS NOT NULL"]
    params = []

    if episode_id:
        where_clauses.append("e.episode_id = %s")
        params.append(episode_id)

    if episode_ids:
        placeholders = ", ".join(["%s"] * len(episode_ids))
        where_clauses.append(f"e.episode_id IN ({placeholders})")
        params.extend(episode_ids)

    if product_id:
        where_clauses.append("e.product_id = %s")
        params.append(product_id)

    sql = f"""
        SELECT
            e.episode_id,
            e.product_id,
            e.episode_no,
            e.episode_title,
            e.episode_content,
            e.epub_file_id,
            (
                SELECT fi.file_name
                FROM tb_common_file cf
                INNER JOIN tb_common_file_item fi
                  ON cf.file_group_id = fi.file_group_id
                 AND fi.use_yn = 'Y'
                WHERE cf.file_group_id = e.epub_file_id
                  AND cf.group_type = 'epub'
                  AND cf.use_yn = 'Y'
                LIMIT 1
            ) AS epub_file_name,
            (
                SELECT fi.file_path
                FROM tb_product p
                INNER JOIN tb_common_file cf
                  ON p.thumbnail_file_id = cf.file_group_id
                 AND cf.group_type = 'cover'
                 AND cf.use_yn = 'Y'
                INNER JOIN tb_common_file_item fi
                  ON cf.file_group_id = fi.file_group_id
                 AND fi.use_yn = 'Y'
                WHERE p.product_id = e.product_id
                LIMIT 1
            ) AS cover_image_path
        FROM tb_product_episode e
        WHERE {' AND '.join(where_clauses)}
        ORDER BY e.episode_no, e.episode_id
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


async def regenerate_episode(row: dict) -> None:
    episode_id = int(row["episode_id"])
    episode_no = int(row["episode_no"] or 0)
    episode_title = (row.get("episode_title") or "").strip()
    episode_content = row.get("episode_content") or ""
    cover_image_path = row.get("cover_image_path") or ""
    epub_file_name = row.get("epub_file_name")

    if not epub_file_name:
        raise ValueError(f"episode_id={episode_id} 에 대응하는 epub file_name 이 없습니다.")

    combined_title = f"{episode_no}화. {episode_title}".strip()
    temp_file_name = f"{episode_id}.epub"

    await comm_service.make_epub(
        file_org_name=temp_file_name,
        cover_image_path=cover_image_path,
        episode_title=combined_title,
        content_db=episode_content,
    )

    upload_url = comm_service.make_r2_presigned_url(
        type="upload",
        bucket_name=settings.R2_SC_EPUB_BUCKET,
        file_id=epub_file_name,
    )

    await comm_service.upload_epub_to_r2(url=upload_url, file_name=temp_file_name)


def main() -> int:
    args = parse_args()
    episode_ids = read_episode_ids(args.episode_id_file)
    conn = get_connection()

    try:
        rows = fetch_targets(conn, args.episode_id, args.product_id, episode_ids)
    finally:
        conn.close()

    if not rows:
        print("[INFO] 대상 회차가 없습니다.")
        return 0

    print(f"[INFO] 대상 회차 수: {len(rows)}")
    for row in rows:
        print(
            f"  - episode_id={row['episode_id']} product_id={row['product_id']} "
            f"episode_no={row['episode_no']} epub_file_id={row['epub_file_id']} "
            f"epub_file_name={row['epub_file_name']}"
        )

    if args.dry_run:
        print("[INFO] dry-run 종료")
        return 0

    success = 0
    fail = 0

    for row in rows:
        episode_id = row["episode_id"]
        try:
            asyncio.run(regenerate_episode(row))
            success += 1
            print(f"[OK] episode_id={episode_id} regenerated")
        except Exception as e:
            fail += 1
            print(f"[FAIL] episode_id={episode_id} reason={e}")

    print(f"[DONE] success={success} fail={fail} total={len(rows)}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
