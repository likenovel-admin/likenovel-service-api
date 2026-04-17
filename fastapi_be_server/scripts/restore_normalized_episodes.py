#!/usr/bin/env python3
"""
One-off script: restore episodes corrupted by frontend normalizeViewerContentHtml.

The normalizeViewerContentHtml function (introduced in commit fd0c721, removed in
2176c94) transformed editor HardBreak content on save:
  <p>A<br><br>B</p>  →  <p>A</p><p><br></p><p>B</p>

This inflated <p> count and caused excessive spacing in the EPUB viewer due to
default browser <p> margins.

This script reverses the transformation:
  - Consecutive <p> blocks merged into single <p> with <br> separators
  - Blank <p><br></p> contributes just a <br> joiner (no extra content)
  - <p> containing images/videos/headings are kept separate (not merged)
  - DB episode_content updated
  - EPUB regenerated and re-uploaded to R2

Usage:
  # Dry-run (default, no writes)
  python3 scripts/restore_normalized_episodes.py --product-id 1130

  # Apply (updates DB + regenerates EPUB)
  python3 scripts/restore_normalized_episodes.py --product-id 1130 --apply

  # Merge function unit tests only
  python3 scripts/restore_normalized_episodes.py --test

Default scope:
  - updated_date >= 2026-04-16 21:29:00 (normalize first-write time)
  - use_yn = 'Y'
  - Contains at least one <p><br></p> pattern (normalize signature)
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add parent dir to path so we can import app.*
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from bs4 import BeautifulSoup, NavigableString, Tag  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402


NORMALIZE_CUTOFF = "2026-04-16 21:29:00"


# ---------- Merge logic ----------

def _is_blank_paragraph(p: Tag) -> bool:
    """True if <p> has no meaningful content (empty or only <br>/whitespace)."""
    for c in p.children:
        if isinstance(c, NavigableString):
            if c.strip():
                return False
        elif isinstance(c, Tag):
            if c.name != "br":
                return False
    return True


def _has_block_content(p: Tag) -> bool:
    """True if <p> contains embedded blocks (img/video/heading/list) that
    shouldn't be merged into a <br>-joined line."""
    return p.find(
        ["img", "video", "iframe", "h1", "h2", "h3", "h4", "h5", "h6",
         "ul", "ol", "blockquote", "pre", "table"]
    ) is not None


def merge_normalized_paragraphs(html: str) -> str:
    """Merge consecutive plain <p> blocks into single <p> with <br> separators."""
    soup = BeautifulSoup(html or "", "html.parser")

    new_top_level = []
    group: list[Tag] = []

    def flush():
        nonlocal group
        if not group:
            return
        if len(group) == 1:
            new_top_level.append(group[0])
            group = []
            return
        merged = soup.new_tag("p")
        for i, p in enumerate(group):
            if i > 0:
                merged.append(soup.new_tag("br"))
            if not _is_blank_paragraph(p):
                # Move all children from p into merged
                for child in list(p.children):
                    merged.append(child)
        new_top_level.append(merged)
        group = []

    for node in list(soup.children):
        if isinstance(node, Tag) and node.name == "p" and not _has_block_content(node):
            group.append(node)
        else:
            flush()
            new_top_level.append(node)

    flush()

    return "".join(str(n) for n in new_top_level)


# ---------- Tests ----------

def run_tests():
    cases = [
        # (name, input, expected)
        (
            "1 blank line between paragraphs",
            "<p>A</p><p><br></p><p>B</p>",
            "<p>A<br/><br/>B</p>",
        ),
        (
            "2 blank lines between paragraphs",
            "<p>A</p><p><br></p><p><br></p><p>B</p>",
            "<p>A<br/><br/><br/>B</p>",
        ),
        (
            "No blank lines (adjacent)",
            "<p>A</p><p>B</p>",
            "<p>A<br/>B</p>",
        ),
        (
            "Empty p (no br) between paragraphs",
            "<p>A</p><p></p><p>B</p>",
            "<p>A<br/><br/>B</p>",
        ),
        (
            "Single paragraph unchanged",
            "<p>Hello world</p>",
            "<p>Hello world</p>",
        ),
        (
            "Image paragraph kept separate",
            "<p>A</p><p><img src='x.png'/></p><p>B</p>",
            "<p>A</p><p><img src=\"x.png\"/></p><p>B</p>",
        ),
        (
            "Internal br preserved",
            "<p>Line1<br/>Line2</p><p><br></p><p>Line3</p>",
            "<p>Line1<br/>Line2<br/><br/>Line3</p>",
        ),
    ]

    passed = 0
    failed = 0
    for name, inp, expected in cases:
        actual = merge_normalized_paragraphs(inp)
        # Normalize <br> vs <br/> differences for comparison
        actual_norm = actual.replace("<br>", "<br/>").replace("<br/>", "<br/>")
        expected_norm = expected.replace("<br>", "<br/>")
        if actual_norm == expected_norm:
            print(f"✓ {name}")
            passed += 1
        else:
            print(f"✗ {name}")
            print(f"   input:    {inp}")
            print(f"   expected: {expected_norm}")
            print(f"   actual:   {actual_norm}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    return failed == 0


# ---------- DB + EPUB regen ----------

async def regenerate_epub(conn, episode_row, new_content: str, dry_run: bool):
    """Regenerate EPUB file for an episode and upload to R2."""
    from app.services.common import comm_service
    from app.core.settings import settings

    epub_file_id = episode_row.get("epub_file_id")
    if not epub_file_id:
        print("    (skip EPUB: no epub_file_id)")
        return

    # Look up file_name + bucket
    file_query = text("""
        SELECT b.file_name, b.file_original_name
        FROM tb_common_file a
        JOIN tb_common_file_item b ON a.file_group_id = b.file_group_id
        WHERE a.file_group_id = :fid
          AND a.group_type = 'epub'
          AND b.use_yn = 'Y'
        LIMIT 1
    """)
    file_result = await conn.execute(file_query, {"fid": epub_file_id})
    file_row = file_result.mappings().first()
    if not file_row:
        print("    (skip EPUB: file_row not found)")
        return

    file_org_name = file_row["file_name"]

    cover_query = text("""
        SELECT cover_image_path FROM tb_product WHERE product_id = :pid
    """)
    cover_result = await conn.execute(cover_query, {"pid": episode_row["product_id"]})
    cover_row = cover_result.mappings().first()
    cover_image_path = (cover_row or {}).get("cover_image_path") or ""

    if dry_run:
        print(f"    [dry-run] would regenerate EPUB: {file_org_name}")
        return

    try:
        await comm_service.make_epub(
            file_org_name=file_org_name,
            cover_image_path=cover_image_path,
            episode_title=episode_row.get("episode_title") or "",
            content_db=new_content,
        )
        presigned_url = comm_service.make_r2_presigned_url(
            type="upload",
            bucket_name=settings.R2_SC_EPUB_BUCKET,
            file_id=file_org_name,
        )
        await comm_service.upload_epub_to_r2(url=presigned_url, file_name=file_org_name)
        print(f"    ✓ EPUB regenerated + uploaded: {file_org_name}")
    except Exception as e:  # noqa: BLE001
        print(f"    ✗ EPUB regen failed: {e}")


async def run(product_id: int, apply: bool):
    db_user = os.environ.get("DB_USER_ID") or os.environ.get("DB_USER")
    db_pw = os.environ.get("DB_USER_PW") or os.environ.get("DB_PW")
    db_ip = os.environ.get("DB_IP")
    db_port = os.environ.get("DB_PORT")
    db_name = os.environ.get("DB_NAME", "likenovel")

    if not all([db_user, db_pw, db_ip, db_port]):
        print("ERROR: DB env not set. Source .env or pass DB_* vars.")
        sys.exit(1)

    url = f"mysql+aiomysql://{db_user}:{db_pw}@{db_ip}:{db_port}/{db_name}"
    engine = create_async_engine(url, pool_pre_ping=True)

    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text("""
                    SELECT episode_id, product_id, episode_no, episode_title,
                           episode_content, epub_file_id
                    FROM tb_product_episode
                    WHERE product_id = :pid
                      AND use_yn = 'Y'
                      AND updated_date >= :cutoff
                      AND (LENGTH(episode_content) -
                           LENGTH(REPLACE(episode_content, '<p><br></p>', ''))) >= 11
                    ORDER BY episode_no ASC
                """),
                {"pid": product_id, "cutoff": NORMALIZE_CUTOFF},
            )
            episodes = result.mappings().all()

        print(f"Target product: {product_id}")
        print(f"Mode: {'APPLY' if apply else 'DRY-RUN'}")
        print(f"Cutoff: updated_date >= {NORMALIZE_CUTOFF}")
        print(f"Found: {len(episodes)} episodes")
        print("=" * 70)

        for ep in episodes:
            ep_id = ep["episode_id"]
            before = ep["episode_content"] or ""
            after = merge_normalized_paragraphs(before)

            before_p = before.count("<p>")
            after_p = after.count("<p>")
            before_blank = before.count("<p><br></p>") + before.count("<p></p>")
            size_before = len(before)
            size_after = len(after)

            print(
                f"Ep {ep_id} ({ep['episode_no']}화): {ep['episode_title']}"
            )
            print(
                f"  <p> {before_p} → {after_p} | blanks {before_blank} → 0 | "
                f"bytes {size_before} → {size_after} (-{size_before - size_after})"
            )

            if apply:
                async with engine.begin() as conn:
                    await conn.execute(
                        text("""
                            UPDATE tb_product_episode
                            SET episode_content = :content
                            WHERE episode_id = :eid
                        """),
                        {"content": after, "eid": ep_id},
                    )
                    await regenerate_epub(conn, dict(ep), after, dry_run=False)
                print("  ✓ DB + EPUB updated")
            else:
                async with engine.connect() as conn:
                    await regenerate_epub(conn, dict(ep), after, dry_run=True)

        print("=" * 70)
        print(f"Done. {'Changes applied.' if apply else 'Dry-run — no writes made.'}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-id", type=int, help="Target product ID")
    parser.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run)")
    parser.add_argument("--test", action="store_true", help="Run merge function tests only")
    args = parser.parse_args()

    if args.test:
        ok = run_tests()
        sys.exit(0 if ok else 1)

    if not args.product_id:
        parser.error("--product-id required (unless --test)")

    asyncio.run(run(product_id=args.product_id, apply=args.apply))
