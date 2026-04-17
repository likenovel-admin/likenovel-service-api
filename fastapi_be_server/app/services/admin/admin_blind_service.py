import io
import re
from urllib.parse import quote

from bs4 import BeautifulSoup, NavigableString, Tag
from fastapi.responses import StreamingResponse
from sqlalchemy import text, bindparam
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import ErrorMessages
from app.utils.response import check_exists_or_404


async def blind_list(
    page: int,
    count_per_page: int,
    blind_yn: str | None,
    search_target: str | None,
    search_word: str | None,
    db: AsyncSession,
):
    where_clauses = ["1=1"]
    params: dict = {}

    if blind_yn and blind_yn in ("Y", "N"):
        where_clauses.append("a.blind_yn = :blind_yn")
        params["blind_yn"] = blind_yn

    if search_target and search_word:
        word = search_word.strip()
        if word:
            if search_target == "product-title":
                where_clauses.append("a.title LIKE :sw")
                params["sw"] = f"%{word}%"
            elif search_target == "author-name":
                where_clauses.append("a.author_name LIKE :sw")
                params["sw"] = f"%{word}%"
            elif search_target == "product-id":
                try:
                    params["pid"] = int(word)
                    where_clauses.append("a.product_id = :pid")
                except ValueError:
                    where_clauses.append("1=0")
            elif search_target == "user-id":
                try:
                    params["uid"] = int(word)
                    where_clauses.append("a.user_id = :uid")
                except ValueError:
                    where_clauses.append("1=0")

    where_sql = " AND ".join(where_clauses)

    count_query = text(f"""
        SELECT COUNT(*) AS cnt
          FROM tb_product a
         WHERE {where_sql}
    """)
    count_result = await db.execute(count_query, params)
    total_count = count_result.scalar() or 0

    offset = (page - 1) * count_per_page
    limit_params = {**params, "limit": count_per_page, "offset": offset}

    query = text(f"""
        SELECT a.product_id
             , a.title
             , a.user_id
             , a.author_name
             , COALESCE(u.email, '') AS author_email
             , COALESCE(g.keyword_name, '') AS primary_genre
             , a.open_yn
             , a.blind_yn
             , a.created_date
             , (SELECT COUNT(*)
                  FROM tb_product_episode e
                 WHERE e.product_id = a.product_id
                   AND e.use_yn = 'Y') AS episode_count
          FROM tb_product a
          LEFT JOIN tb_user u
            ON u.user_id = a.author_id
          LEFT JOIN tb_standard_keyword g
            ON g.keyword_id = a.primary_genre_id
         WHERE {where_sql}
         ORDER BY a.product_id DESC
         LIMIT :limit OFFSET :offset
    """)
    result = await db.execute(query, limit_params)
    rows = result.mappings().all()

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "results": [dict(row) for row in rows],
    }


async def batch_blind(
    product_ids: list[int],
    blind_yn: str,
    db: AsyncSession,
):
    if not product_ids:
        return {"result": True, "updated_count": 0}

    blind_val = blind_yn.upper()
    if blind_val not in ("Y", "N"):
        blind_val = "N"

    if blind_val == "Y":
        query = text("""
            UPDATE tb_product
               SET blind_yn = 'Y'
                 , open_yn = 'N'
                 , updated_date = NOW()
             WHERE product_id IN :ids
        """).bindparams(bindparam("ids", expanding=True))
    else:
        query = text("""
            UPDATE tb_product
               SET blind_yn = 'N'
                 , updated_date = NOW()
             WHERE product_id IN :ids
        """).bindparams(bindparam("ids", expanding=True))

    result = await db.execute(query, {"ids": product_ids})

    return {"result": True, "updated_count": result.rowcount}


async def batch_open(
    product_ids: list[int],
    open_yn: str,
    db: AsyncSession,
):
    if not product_ids:
        return {"result": True, "updated_count": 0}

    open_val = open_yn.upper()
    if open_val not in ("Y", "N"):
        open_val = "N"

    query = text("""
        UPDATE tb_product
           SET open_yn = CASE
                           WHEN blind_yn = 'Y' AND :open_yn = 'Y' THEN 'N'
                           ELSE :open_yn
                         END
             , updated_date = NOW()
         WHERE product_id IN :ids
    """).bindparams(bindparam("ids", expanding=True))

    result = await db.execute(query, {"ids": product_ids, "open_yn": open_val})

    return {"result": True, "updated_count": result.rowcount}


def _serialize_html_node_to_text(node) -> str:
    if isinstance(node, NavigableString):
        return str(node).replace("\xa0", " ")

    if not isinstance(node, Tag):
        return ""

    tag_name = (node.name or "").lower()

    if tag_name == "br":
        return "\n"

    return "".join(_serialize_html_node_to_text(child) for child in node.children)


def _normalize_viewer_block_text(text: str) -> str:
    normalized = text.replace("\xa0", " ")
    normalized = re.sub(r"\r\n?", "\n", normalized)
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    return normalized.strip("\n")


def _iter_viewer_text_blocks(root) -> list[str]:
    blocks: list[str] = []

    for child in root.children:
        if isinstance(child, NavigableString):
            block = _normalize_viewer_block_text(str(child))
            if block:
                blocks.append(block)
            continue

        if not isinstance(child, Tag):
            continue

        tag_name = (child.name or "").lower()

        if tag_name in {"ul", "ol"}:
            list_items = [
                _normalize_viewer_block_text(_serialize_html_node_to_text(grandchild))
                for grandchild in child.find_all("li", recursive=False)
            ]
            blocks.extend(list_items if list_items else [""])
            continue

        block = _normalize_viewer_block_text(_serialize_html_node_to_text(child))
        if tag_name in {"p", "div", "section", "article", "blockquote", "pre", "li"}:
            blocks.append(block)
        elif block:
            blocks.append(block)

    return blocks


def _html_to_plain_text(value: str | None) -> str:
    if not value:
        return ""

    soup = BeautifulSoup(value, "html.parser")
    root = soup.body if soup.body else soup
    blocks = _iter_viewer_text_blocks(root)

    collapsed: list[str] = []
    blank_pending = False

    for block in blocks:
        if block == "":
            if collapsed:
                blank_pending = True
            continue

        if blank_pending:
            collapsed.append("")
            blank_pending = False
        collapsed.append(block)

    return "\n".join(collapsed).strip()


def _sanitize_file_name(value: str) -> str:
    normalized = re.sub(r'[\/:*?"<>|]+', "_", (value or "").strip())
    normalized = re.sub(r"\s+", " ", normalized).strip(" .")
    return normalized or "product"


async def download_product_episodes_txt(
    product_id: int,
    db: AsyncSession,
):
    product_query = text("""
        SELECT product_id, title, author_name
          FROM tb_product
         WHERE product_id = :product_id
         LIMIT 1
    """)
    product_result = await db.execute(product_query, {"product_id": product_id})
    product_row = product_result.mappings().first()
    check_exists_or_404([product_row] if product_row else [], ErrorMessages.NOT_FOUND_PRODUCT)

    episode_query = text("""
        SELECT e.episode_id,
               e.episode_no,
               e.episode_title,
               e.episode_content,
               e.open_yn,
               e.publish_reserve_date,
               e.created_date
          FROM tb_product_episode e
         WHERE e.product_id = :product_id
           AND e.use_yn = 'Y'
         ORDER BY e.episode_no ASC, e.created_date ASC, e.episode_id ASC
    """)
    episode_result = await db.execute(episode_query, {"product_id": product_id})
    episode_rows = [dict(row) for row in episode_result.mappings().all()]

    output = io.StringIO()
    product_title = str(product_row.get("title") or "")
    author_name = str(product_row.get("author_name") or "")

    output.write(f"작품명: {product_title}\n")
    output.write(f"작가명: {author_name or '-'}\n")
    output.write(f"회차수: {len(episode_rows)}\n\n")

    if not episode_rows:
        output.write("등록된 회차가 없습니다.\n")
    else:
        for episode in episode_rows:
            output.write("=" * 30 + "\n")
            output.write(
                f"{episode.get('episode_no') or 0}화. {episode.get('episode_title') or '-'}\n"
            )
            output.write(f"에피소드ID: {episode.get('episode_id') or 0}\n")
            output.write(f"공개여부: {episode.get('open_yn') or 'N'}\n")

            publish_reserve_date = episode.get("publish_reserve_date")
            if publish_reserve_date:
                output.write(f"예약공개일: {publish_reserve_date}\n")

            created_date = episode.get("created_date")
            if created_date:
                output.write(f"등록일: {created_date}\n")

            output.write("\n")
            output.write(_html_to_plain_text(episode.get("episode_content")))
            output.write("\n\n")

    output.seek(0)

    file_name = _sanitize_file_name(
        f"{author_name}_{product_title}" if author_name else product_title
    )
    encoded_file_name = quote(file_name + ".txt")
    ascii_file_name = re.sub(r'[^A-Za-z0-9._-]+', '_', file_name).strip('._') or 'product'
    ascii_file_name = f"{ascii_file_name}.txt"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_file_name}"; '
                f"filename*=UTF-8''{encoded_file_name}"
            )
        },
    )
