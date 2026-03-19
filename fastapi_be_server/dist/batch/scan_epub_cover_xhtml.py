#!/usr/bin/env python3
"""
EPUB cover.xhtml 전수 점검 스크립트.

- 모든 회차(또는 특정 작품/회차)의 EPUB을 다운로드해 cover.xhtml 파싱 상태를 점검한다.
- 결과를 CSV로 저장하고, 비정상 회차 episode_id 목록 파일도 같이 저장할 수 있다.
- 실제 복구는 repair_epub_cover_xhtml.py 로 수행한다.

사용법 (컨테이너 내부):
  python3 /app/dist/batch/scan_epub_cover_xhtml.py --output-csv /tmp/epub_cover_scan.csv
  python3 /app/dist/batch/scan_epub_cover_xhtml.py --product-id 673 --output-csv /tmp/p673.csv --broken-ids-out /tmp/p673.ids
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pymysql

APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.const import settings  # noqa: E402
import app.services.common.comm_service as comm_service  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan EPUB cover.xhtml validity")
    parser.add_argument("--episode-id", type=int, help="단일 회차만 점검")
    parser.add_argument("--product-id", type=int, help="작품의 모든 회차 점검")
    parser.add_argument(
        "--output-csv",
        type=str,
        default="/tmp/epub_cover_scan.csv",
        help="스캔 결과 CSV 경로",
    )
    parser.add_argument(
        "--broken-ids-out",
        type=str,
        help="비정상 episode_id 목록 출력 파일",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="테스트용 제한 개수",
    )
    return parser.parse_args()


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


def fetch_targets(conn, episode_id: int | None, product_id: int | None, limit: int | None):
    where_clauses = ["e.use_yn = 'Y'", "e.epub_file_id IS NOT NULL"]
    params: list[object] = []

    if episode_id:
        where_clauses.append("e.episode_id = %s")
        params.append(episode_id)

    if product_id:
        where_clauses.append("e.product_id = %s")
        params.append(product_id)

    limit_sql = " LIMIT %s" if limit else ""
    if limit:
        params.append(limit)

    sql = f"""
        SELECT
            e.episode_id,
            e.product_id,
            e.episode_no,
            e.episode_title,
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
            ) AS epub_file_name
        FROM tb_product_episode e
        WHERE {' AND '.join(where_clauses)}
        ORDER BY e.product_id, e.episode_no, e.episode_id
        {limit_sql}
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def inspect_cover_xhtml(epub_file_name: str) -> tuple[str, str]:
    url = comm_service.make_r2_presigned_url(
        type="download",
        bucket_name=settings.R2_SC_EPUB_BUCKET,
        file_id=epub_file_name,
    )

    fd, temp_path = tempfile.mkstemp(suffix=".epub")
    os.close(fd)

    try:
        urllib.request.urlretrieve(url, temp_path)
        with zipfile.ZipFile(temp_path) as zf:
            if "EPUB/cover.xhtml" not in zf.namelist():
                return ("broken", "missing_cover_xhtml")

            raw = zf.read("EPUB/cover.xhtml").decode("utf-8", errors="replace")

            try:
                root = ET.fromstring(raw)
            except ET.ParseError as exc:
                return ("broken", f"xml_parse_error:{exc}")

            img = None
            for elem in root.iter():
                if elem.tag.endswith("img"):
                    img = elem
                    break

            if img is None:
                return ("broken", "missing_img")

            src = (img.attrib.get("src") or "").strip()
            if not src:
                return ("broken", "missing_img_src")

            return ("ok", src)
    except zipfile.BadZipFile as exc:
        return ("broken", f"bad_zip:{exc}")
    except Exception as exc:  # noqa: BLE001
        return ("broken", f"download_or_read_error:{exc}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def main() -> int:
    args = parse_args()
    conn = get_connection()

    try:
        rows = fetch_targets(conn, args.episode_id, args.product_id, args.limit)
    finally:
        conn.close()

    if not rows:
        print("[INFO] 대상 회차가 없습니다.")
        return 0

    output_csv = Path(args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    broken_ids: list[int] = []

    with output_csv.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "episode_id",
                "product_id",
                "episode_no",
                "episode_title",
                "epub_file_id",
                "epub_file_name",
                "status",
                "detail",
            ],
        )
        writer.writeheader()

        for index, row in enumerate(rows, start=1):
            status, detail = inspect_cover_xhtml(row["epub_file_name"])
            if status != "ok":
                broken_ids.append(int(row["episode_id"]))

            writer.writerow(
                {
                    "episode_id": row["episode_id"],
                    "product_id": row["product_id"],
                    "episode_no": row["episode_no"],
                    "episode_title": row["episode_title"],
                    "epub_file_id": row["epub_file_id"],
                    "epub_file_name": row["epub_file_name"],
                    "status": status,
                    "detail": detail,
                }
            )

            if index % 100 == 0:
                print(f"[INFO] scanned={index}/{len(rows)} broken={len(broken_ids)}")

    if args.broken_ids_out:
        broken_path = Path(args.broken_ids_out)
        broken_path.parent.mkdir(parents=True, exist_ok=True)
        broken_path.write_text(
            "\n".join(str(episode_id) for episode_id in broken_ids) + ("\n" if broken_ids else ""),
            encoding="utf-8",
        )

    print(f"[DONE] total={len(rows)} broken={len(broken_ids)} csv={output_csv}")
    if args.broken_ids_out:
        print(f"[DONE] broken_ids={args.broken_ids_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
