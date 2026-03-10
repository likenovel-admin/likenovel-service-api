#!/usr/bin/env python3
"""
파트너 EPUB 업로드 회차의 episode_content 백필 스크립트.
epub_file_id는 있지만 episode_content가 비어있는 회차를 대상으로
R2에서 EPUB을 다운로드하여 HTML 본문을 추출하고 episode_content에 저장한다.

사용법 (컨테이너 내부):
  python3 /app/dist/batch/backfill_epub_episode_content.py [--dry-run] [--limit N]

사용법 (로컬, SSH 터널 필요):
  python3 backfill_epub_episode_content.py [--dry-run] [--limit N]
"""
import argparse
import os
import sys
from io import BytesIO
from zipfile import BadZipFile, ZipFile

import httpx
import pymysql
from bs4 import BeautifulSoup

# -- 환경변수 기반 DB 접속 --
DB_HOST = os.getenv("BATCH_DB_HOST", os.getenv("DB_IP", "127.0.0.1"))
DB_PORT = int(os.getenv("BATCH_DB_PORT", os.getenv("DB_PORT", "13306")))
DB_USER = os.getenv("BATCH_DB_USER", os.getenv("DB_USER", ""))
DB_PASSWORD = os.getenv("BATCH_DB_PASSWORD", os.getenv("DB_PW", ""))
DB_NAME = os.getenv("BATCH_DB_NAME", os.getenv("DB_NAME", "likenovel"))

# R2 설정 (앱 설정과 동일한 키 이름 사용)
R2_SC_DOMAIN = os.getenv(
    "R2_SC_DOMAIN",
    "https://a168bba93203dec90f4f7ddda837c772.r2.cloudflarestorage.com",
)
R2_SC_EPUB_BUCKET = os.getenv("R2_SC_EPUB_BUCKET", "epub")
R2_CLIENT_ID = os.getenv("R2_CLIENT_ID", "")
R2_CLIENT_SECRET = os.getenv("R2_CLIENT_SECRET", "")


def extract_html_content_from_epub(epub_binary: bytes) -> str:
    """EPUB에서 본문 HTML을 추출한다 (cover.xhtml 제외)."""
    parts = []
    with ZipFile(BytesIO(epub_binary)) as epub_zip:
        for file_info in epub_zip.infolist():
            if file_info.is_dir():
                continue
            file_name = file_info.filename.lower()
            if not file_name.endswith((".xhtml", ".html", ".htm")):
                continue
            if "cover" in file_name:
                continue
            html_content = epub_zip.read(file_info)
            soup = BeautifulSoup(html_content, "html.parser")
            body = soup.find("body")
            if body:
                parts.append(body.decode_contents())
            else:
                parts.append(str(soup))
    return "".join(parts)


def make_r2_presigned_url(file_id: str) -> str:
    """R2 presigned download URL 생성 (boto3 사용, 앱의 comm_service와 동일한 방식)."""
    import boto3
    from botocore.config import Config
    s3 = boto3.client(
        service_name="s3",
        endpoint_url=R2_SC_DOMAIN,
        aws_access_key_id=R2_CLIENT_ID,
        aws_secret_access_key=R2_CLIENT_SECRET,
        region_name="auto",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": R2_SC_EPUB_BUCKET, "Key": file_id},
        ExpiresIn=600,
    )


def main():
    parser = argparse.ArgumentParser(description="Backfill episode_content from EPUB")
    parser.add_argument("--dry-run", action="store_true", help="Count only, no update")
    parser.add_argument("--limit", type=int, default=0, help="Max episodes to process (0=all)")
    args = parser.parse_args()

    if not DB_USER or not DB_PASSWORD:
        print("[ERROR] DB_USER or DB_PASSWORD not set", file=sys.stderr)
        sys.exit(1)

    conn = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, database=DB_NAME,
        charset="utf8mb4",
    )

    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            # 대상 회차 조회
            sql = """
                SELECT e.episode_id, e.epub_file_id, fi.file_name
                FROM tb_product_episode e
                INNER JOIN tb_common_file f ON e.epub_file_id = f.file_group_id
                    AND f.group_type = 'epub' AND f.use_yn = 'Y'
                INNER JOIN tb_common_file_item fi ON f.file_group_id = fi.file_group_id
                    AND fi.use_yn = 'Y'
                WHERE e.epub_file_id IS NOT NULL
                  AND (e.episode_content IS NULL OR e.episode_content = '')
                  AND e.use_yn = 'Y'
                ORDER BY e.episode_id
            """
            if args.limit > 0:
                sql += f" LIMIT {args.limit}"

            cur.execute(sql)
            rows = cur.fetchall()

        print(f"[INFO] {len(rows)} episodes to backfill")

        if args.dry_run:
            print("[INFO] dry-run mode, exiting")
            return

        success = 0
        fail = 0

        for row in rows:
            episode_id = row["episode_id"]
            file_name = row["file_name"]

            try:
                url = make_r2_presigned_url(file_name)
                resp = httpx.get(url, timeout=60.0)
                resp.raise_for_status()

                html_content = extract_html_content_from_epub(resp.content)

                if not html_content:
                    print(f"  [SKIP] episode_id={episode_id}: empty HTML from EPUB")
                    fail += 1
                    continue

                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE tb_product_episode SET episode_content = %s WHERE episode_id = %s",
                        (html_content, episode_id),
                    )
                conn.commit()
                success += 1

                if success % 50 == 0:
                    print(f"  [PROGRESS] {success}/{len(rows)} done")

            except (httpx.HTTPStatusError, httpx.RequestError, BadZipFile, ValueError) as e:
                print(f"  [FAIL] episode_id={episode_id}: {e}")
                fail += 1
            except Exception as e:
                print(f"  [FAIL] episode_id={episode_id}: {e}")
                fail += 1

        print(f"[DONE] success={success}, fail={fail}, total={len(rows)}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
