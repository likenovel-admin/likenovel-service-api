#!/usr/bin/env python3
"""스토리 에이전트 원문 컨텍스트 적재 배치.

기본 정책
- 대상은 무료 작품 전체
- SSOT는 tb_product_episode.episode_content
- EPUB fallback은 기본 비활성, 필요 시에만 임시 원문으로 사용
- tb_product_episode 자체는 절대 update 하지 않음
- context_doc/context_chunk는 append-only, active 포인터만 전환
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Iterable

import pymysql
from bs4 import BeautifulSoup
from httpx import AsyncClient, HTTPStatusError, RequestError
from pymysql.constants import CLIENT
from pymysql.cursors import DictCursor

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.const import settings  # noqa: E402
from app.services.common import comm_service  # noqa: E402
from app.services.product.episode_service import _extract_epub_payload_from_epub  # noqa: E402

DB_HOST = os.getenv("BATCH_DB_HOST", settings.DB_IP)
DB_PORT = int(os.getenv("BATCH_DB_PORT", str(settings.DB_PORT)))
DB_USER = os.getenv("BATCH_DB_USER", settings.DB_USER_ID)
DB_PASSWORD = os.getenv("BATCH_DB_PASSWORD", settings.DB_USER_PW)
DB_NAME = os.getenv("BATCH_DB_NAME", "likenovel")

TARGET_CHUNK_LEN = 1600
MAX_CHUNK_LEN = 2500
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|(?<=다\.)\s+|(?<=요\.)\s+")
KEYWORD_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
EPISODE_SUMMARY_FORMAT_VERSION = "episode_summary_v1"
RANGE_SUMMARY_FORMAT_VERSION = "range_summary_v1"
PRODUCT_SUMMARY_FORMAT_VERSION = "product_summary_v1"
CHARACTER_SNAPSHOT_FORMAT_VERSION = "character_snapshot_v1"
RANGE_SUMMARY_EPISODE_SPAN = 20
KEYWORD_STOPWORDS = {
    "그리고", "하지만", "그러나", "이번", "저번", "그녀", "그는", "그것", "이것", "저것",
    "에게", "에서", "한다", "했다", "했다는", "있다", "있는", "없다", "없고", "정도", "처럼",
    "위해", "통해", "이후", "이전", "장면", "회차", "작품", "내용", "상태",
}
CHARACTER_STOPWORDS = KEYWORD_STOPWORDS | {
    "주인공", "조연", "악역", "능력", "시간정지", "발현", "전학생", "전학", "학교", "학생",
    "작전", "전쟁", "요약", "키워드", "장면", "회차", "작품", "사건", "한계", "실전", "결투",
    "강북고", "발동", "처음", "최초", "직후", "순간", "소년", "소녀", "남자", "여자",
    "세계", "사람", "게임", "신화", "인화", "신의", "학교", "도시", "능력자", "헌터",
}
NAME_WITH_PARTICLE_RE = re.compile(r"([가-힣A-Za-z][가-힣A-Za-z0-9]{1,6})(?:은|는|이|가|을|를|과|와|의|에게|한테)")
COMMON_KOREAN_SURNAMES = {
    "김", "이", "박", "최", "정", "강", "조", "윤", "장", "임", "한", "오", "서", "신", "권",
    "황", "안", "송", "류", "홍", "전", "고", "문", "양", "손", "배", "백", "허", "유", "남",
    "심", "노", "하", "곽", "성", "차", "주", "우", "구", "민", "진", "지", "엄", "채", "원",
    "천", "방", "공", "현", "함", "변", "염", "여", "추", "도", "소", "석", "선", "설", "마",
    "길", "연", "위", "표", "명", "기", "반", "왕", "금", "옥", "육", "인", "맹", "제", "모",
    "탁", "국", "어", "은", "편", "용",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="스토리 에이전트 원문 컨텍스트 적재")
    parser.add_argument("--product-id", type=int, action="append", dest="product_ids", help="대상 작품 ID. 여러 번 지정 가능")
    parser.add_argument("--episode-id", type=int, action="append", dest="episode_ids", help="대상 회차 ID. 여러 번 지정 가능")
    parser.add_argument("--limit", type=int, default=0, help="대상 제한 건수")
    parser.add_argument("--apply", action="store_true", help="실제 DB 적재 수행")
    parser.add_argument("--verbose", action="store_true", help="상세 로그 출력")
    parser.add_argument("--use-epub-fallback", action="store_true", help="episode_content가 비어 있으면 EPUB에서 임시 원문 추출")
    return parser.parse_args()


def db_connect():
    if not DB_USER or not DB_PASSWORD:
        raise RuntimeError("DB 접속 정보가 비어 있습니다. BATCH_DB_* 또는 app.const.settings를 확인하세요.")
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


def acquire_product_lock(cur, product_id: int) -> bool:
    cur.execute("SELECT GET_LOCK(%s, 0) AS locked", (f"story-agent-context-product:{product_id}",))
    row = cur.fetchone() or {}
    return int(row.get("locked") or 0) == 1


def release_product_lock(cur, product_id: int) -> None:
    cur.execute("SELECT RELEASE_LOCK(%s)", (f"story-agent-context-product:{product_id}",))


def build_target_query(args: argparse.Namespace, use_epub_fallback: bool) -> tuple[str, list[object]]:
    where = [
        "p.price_type = 'free'",
        "pe.use_yn = 'Y'",
    ]
    params: list[object] = []

    if args.product_ids:
        placeholders = ", ".join(["%s"] * len(args.product_ids))
        where.append(f"p.product_id IN ({placeholders})")
        params.extend(args.product_ids)

    if args.episode_ids:
        placeholders = ", ".join(["%s"] * len(args.episode_ids))
        where.append(f"pe.episode_id IN ({placeholders})")
        params.extend(args.episode_ids)

    where_sql = " AND ".join(where)
    limit_sql = f" LIMIT {int(args.limit)}" if args.limit and args.limit > 0 else ""

    file_join_sql = ""
    file_select_sql = "NULL AS file_name"
    if use_epub_fallback:
        file_join_sql = """
        LEFT JOIN tb_common_file cf
          ON cf.file_group_id = pe.epub_file_id
         AND cf.group_type = 'epub'
         AND cf.use_yn = 'Y'
        LEFT JOIN tb_common_file_item cfi
          ON cfi.file_group_id = cf.file_group_id
         AND cfi.use_yn = 'Y'
        """
        file_select_sql = "cfi.file_name"

    query = f"""
        SELECT
            p.product_id,
            p.title,
            pe.episode_id,
            pe.episode_no,
            pe.episode_title,
            pe.episode_content,
            pe.episode_text_count,
            pe.epub_file_id,
            {file_select_sql}
        FROM tb_product p
        JOIN tb_product_episode pe
          ON pe.product_id = p.product_id
        {file_join_sql}
        WHERE {where_sql}
        ORDER BY p.product_id ASC, pe.episode_no ASC
        {limit_sql}
    """
    return query, params


def normalize_episode_html(html_content: str) -> str:
    soup = BeautifulSoup(html_content or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text(separator="\n")
    text = text.replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    paragraphs: list[str] = []
    blank_open = False
    for line in lines:
        if not line:
            if paragraphs and not blank_open:
                paragraphs.append("")
                blank_open = True
            continue
        paragraphs.append(line)
        blank_open = False
    normalized = "\n".join(paragraphs).strip()
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def split_long_paragraph(paragraph: str) -> list[str]:
    if len(paragraph) <= MAX_CHUNK_LEN:
        return [paragraph]

    sentences = [item.strip() for item in SENTENCE_SPLIT_RE.split(paragraph) if item.strip()]
    if len(sentences) <= 1:
        return [paragraph[i:i + MAX_CHUNK_LEN] for i in range(0, len(paragraph), MAX_CHUNK_LEN)]

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and len(candidate) > MAX_CHUNK_LEN:
            chunks.append(current)
            current = sentence
            continue
        current = candidate
    if current:
        chunks.append(current)
    return chunks


def build_chunks(normalized_text: str) -> list[dict[str, object]]:
    if not normalized_text:
        return []

    units: list[str] = []
    for paragraph in normalized_text.split("\n\n"):
        cleaned = paragraph.strip()
        if not cleaned:
            continue
        units.extend(split_long_paragraph(cleaned))

    chunks: list[dict[str, object]] = []
    buffer = ""
    for unit in units:
        candidate = f"{buffer}\n\n{unit}".strip() if buffer else unit
        if buffer and len(candidate) > TARGET_CHUNK_LEN:
            chunks.append({"text": buffer})
            buffer = unit
            continue
        buffer = candidate
    if buffer:
        chunks.append({"text": buffer})

    offset = 0
    for idx, chunk in enumerate(chunks, start=1):
        text = str(chunk["text"])
        start = normalized_text.find(text, offset)
        if start < 0:
            start = offset
        end = start + len(text)
        chunk["chunk_no"] = idx
        chunk["char_start"] = start
        chunk["char_end"] = end
        chunk["text_hash"] = sha256_text(text)
        offset = end
    return chunks


def extract_summary_sentences(normalized_text: str, limit: int = 3) -> list[str]:
    sentences: list[str] = []
    for paragraph in normalized_text.split("\n\n"):
        cleaned = paragraph.strip()
        if not cleaned:
            continue
        candidates = [item.strip() for item in SENTENCE_SPLIT_RE.split(cleaned) if item.strip()]
        if not candidates:
            candidates = [cleaned]
        for candidate in candidates:
            if candidate in sentences:
                continue
            sentences.append(candidate)
            if len(sentences) >= limit:
                return sentences
    return sentences[:limit]


def extract_keywords(title: str, normalized_text: str, limit: int = 8) -> list[str]:
    counts: dict[str, int] = {}
    source = f"{title}\n{normalized_text[:3000]}"
    for token in KEYWORD_RE.findall(source):
        normalized = token.strip()
        if len(normalized) < 2:
            continue
        if normalized in KEYWORD_STOPWORDS:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [item[0] for item in ranked[:limit]]


def build_episode_summary_text(row: dict, normalized_text: str) -> str:
    episode_label = f"[{int(row['episode_no'])}화] {str(row.get('episode_title') or '').strip() or '요약'}"
    sentences = extract_summary_sentences(normalized_text)
    keywords = extract_keywords(str(row.get("episode_title") or ""), normalized_text)

    bullet_lines = [f"- {sentence}" for sentence in sentences[:3]]
    if not bullet_lines:
        bullet_lines = ["- 요약 가능한 문장을 찾지 못했습니다."]
    keyword_line = f"- 키워드: {', '.join(keywords)}" if keywords else "- 키워드:"
    return "\n".join([episode_label, *bullet_lines, keyword_line]).strip()


def build_summary_source_hash(source_hash: str, episode_title: str) -> str:
    normalized_title = (episode_title or "").strip()
    return sha256_text(f"{EPISODE_SUMMARY_FORMAT_VERSION}:{source_hash}:{normalized_title}")


def build_compound_summary_source_hash(format_version: str, components: list[str]) -> str:
    normalized_components = [component.strip() for component in components if component and component.strip()]
    return sha256_text(f"{format_version}:{'|'.join(normalized_components)}")


def parse_summary_text(summary_text: str) -> dict[str, object]:
    lines = [line.strip() for line in (summary_text or "").splitlines() if line.strip()]
    header = lines[0] if lines else ""
    bullets: list[str] = []
    keywords: list[str] = []
    for line in lines[1:]:
        if line.startswith("- 키워드:"):
            keyword_text = line.replace("- 키워드:", "", 1).strip()
            keywords = [item.strip() for item in keyword_text.split(",") if item.strip()]
            continue
        if line.startswith("- "):
            bullets.append(line[2:].strip())
    return {
        "header": header,
        "bullets": bullets,
        "keywords": keywords,
    }


def fetch_active_summary_rows(cur, product_id: int, summary_type: str) -> list[dict]:
    cur.execute(
        """
        SELECT summary_id, scope_key, episode_from, episode_to, source_hash, summary_text
          FROM tb_story_agent_context_summary
         WHERE product_id = %s
           AND summary_type = %s
           AND is_active = 'Y'
         ORDER BY COALESCE(episode_from, 0) ASC, summary_id ASC
        """,
        (product_id, summary_type),
    )
    return list(cur.fetchall())


def pick_spread_rows(rows: list[dict], limit: int) -> list[dict]:
    if len(rows) <= limit:
        return rows
    if limit <= 1:
        return [rows[0]]
    last_index = len(rows) - 1
    indexes: list[int] = []
    for step in range(limit):
        idx = round((last_index * step) / (limit - 1))
        if idx not in indexes:
            indexes.append(idx)
    return [rows[idx] for idx in indexes]


def build_range_scope_keys(episode_nos: list[int]) -> list[tuple[str, int, int]]:
    if not episode_nos:
        return []
    max_episode_no = max(episode_nos)
    scopes: list[tuple[str, int, int]] = []
    start = 1
    while start <= max_episode_no:
        end = start + RANGE_SUMMARY_EPISODE_SPAN - 1
        scopes.append((f"range:{start}-{end}", start, end))
        start = end + 1
    return scopes


def build_range_summary_text(start_episode: int, end_episode: int, rows: list[dict]) -> str:
    sampled_rows = pick_spread_rows(rows, limit=4)
    merged_keywords: list[str] = []
    keyword_seen: set[str] = set()
    lines = [f"[{start_episode}~{end_episode}화] 구간 요약"]
    for row in sampled_rows:
        parsed = parse_summary_text(str(row.get("summary_text") or ""))
        first_bullet = next((bullet for bullet in list(parsed["bullets"]) if bullet), "")
        episode_no = int(row.get("episode_from") or 0)
        if first_bullet:
            lines.append(f"- {episode_no}화: {first_bullet}")
        for keyword in list(parsed["keywords"]):
            if keyword in keyword_seen:
                continue
            keyword_seen.add(keyword)
            merged_keywords.append(keyword)
            if len(merged_keywords) >= 10:
                break
        if len(merged_keywords) >= 10:
            continue
    lines.append(f"- 키워드: {', '.join(merged_keywords)}" if merged_keywords else "- 키워드:")
    return "\n".join(lines).strip()


def build_product_summary_text(product_title: str, rows: list[dict]) -> str:
    sampled_rows = pick_spread_rows(rows, limit=4)
    merged_keywords: list[str] = []
    keyword_seen: set[str] = set()
    lines = [f"[작품 전체] {product_title or '요약'}"]
    for row in sampled_rows:
        parsed = parse_summary_text(str(row.get("summary_text") or ""))
        first_bullet = next((bullet for bullet in list(parsed["bullets"]) if bullet), "")
        from_episode = int(row.get("episode_from") or 0)
        to_episode = int(row.get("episode_to") or 0)
        if first_bullet:
            if from_episode and to_episode and from_episode != to_episode:
                lines.append(f"- {from_episode}~{to_episode}화: {first_bullet}")
            elif from_episode:
                lines.append(f"- {from_episode}화: {first_bullet}")
            else:
                lines.append(f"- {first_bullet}")
        for keyword in list(parsed["keywords"]):
            if keyword in keyword_seen:
                continue
            keyword_seen.add(keyword)
            merged_keywords.append(keyword)
            if len(merged_keywords) >= 12:
                break
        if len(merged_keywords) >= 12:
            continue
    lines.append(f"- 키워드: {', '.join(merged_keywords)}" if merged_keywords else "- 키워드:")
    return "\n".join(lines).strip()


def build_character_scope_key(name: str) -> str:
    slug = re.sub(r"[^가-힣A-Za-z0-9]", "", (name or "").strip().lower())
    return f"character:{slug}" if slug else "character:unknown"


def is_valid_character_token(token: str) -> bool:
    normalized = (token or "").strip()
    if not re.fullmatch(r"[가-힣]{3,4}", normalized):
        return False
    if normalized in CHARACTER_STOPWORDS:
        return False
    if normalized[0] not in COMMON_KOREAN_SURNAMES:
        return False
    return True


def extract_character_candidates(rows: list[dict]) -> list[dict[str, object]]:
    candidate_map: dict[str, dict[str, object]] = {}
    for row in rows:
        episode_no = int(row.get("episode_from") or 0)
        parsed = parse_summary_text(str(row.get("summary_text") or ""))
        bullet_text = " ".join(list(parsed["bullets"]))
        tokens: set[str] = set()
        for token in NAME_WITH_PARTICLE_RE.findall(bullet_text):
            if is_valid_character_token(token):
                tokens.add(token)
        for token in tokens:
            current = candidate_map.setdefault(
                token,
                {
                    "name": token,
                    "episode_nos": set(),
                    "summary_rows": [],
                    "keywords": set(),
                },
            )
            current["episode_nos"].add(episode_no)
            current["summary_rows"].append(row)
            current["keywords"].update(list(parsed["keywords"]))
    ranked = sorted(
        candidate_map.values(),
        key=lambda item: (-len(item["episode_nos"]), str(item["name"])),
    )
    return [item for item in ranked if len(item["episode_nos"]) >= 2][:8]


def deactivate_missing_active_scopes(cur, product_id: int, summary_type: str, valid_scope_keys: set[str]) -> None:
    if valid_scope_keys:
        placeholders = ", ".join(["%s"] * len(valid_scope_keys))
        cur.execute(
            f"""
            UPDATE tb_story_agent_context_summary
               SET is_active = 'N'
             WHERE product_id = %s
               AND summary_type = %s
               AND is_active = 'Y'
               AND scope_key NOT IN ({placeholders})
            """,
            (product_id, summary_type, *sorted(valid_scope_keys)),
        )
        return
    cur.execute(
        """
        UPDATE tb_story_agent_context_summary
           SET is_active = 'N'
         WHERE product_id = %s
           AND summary_type = %s
           AND is_active = 'Y'
        """,
        (product_id, summary_type),
    )


def build_character_snapshot_text(name: str, candidate: dict[str, object]) -> str:
    episode_nos = sorted(int(item) for item in set(candidate["episode_nos"]))
    sampled_rows = pick_spread_rows(list(candidate["summary_rows"]), limit=3)
    merged_keywords: list[str] = []
    keyword_seen: set[str] = set()
    lines = [f"[인물] {name}"]
    lines.append(f"- 등장 회차: {', '.join(str(no) for no in episode_nos[:8])}")
    for row in sampled_rows:
        parsed = parse_summary_text(str(row.get("summary_text") or ""))
        first_bullet = next((bullet for bullet in list(parsed["bullets"]) if bullet), "")
        episode_no = int(row.get("episode_from") or 0)
        if first_bullet:
            lines.append(f"- {episode_no}화: {first_bullet}")
        for keyword in list(parsed["keywords"]):
            if keyword == name or keyword in keyword_seen:
                continue
            keyword_seen.add(keyword)
            merged_keywords.append(keyword)
            if len(merged_keywords) >= 8:
                break
        if len(merged_keywords) >= 8:
            continue
    lines.append(f"- 관련 키워드: {', '.join(merged_keywords)}" if merged_keywords else "- 관련 키워드:")
    return "\n".join(lines).strip()


def upsert_summary(
    cur,
    *,
    product_id: int,
    summary_type: str,
    scope_key: str,
    source_hash: str,
    source_doc_count: int,
    summary_text: str,
    episode_from: int | None = None,
    episode_to: int | None = None,
) -> tuple[int, bool]:
    existing = fetch_existing_summary(
        cur=cur,
        product_id=product_id,
        summary_type=summary_type,
        scope_key=scope_key,
        source_hash=source_hash,
    )
    if existing:
        activate_existing_summary(cur, int(existing["summary_id"]), product_id, summary_type, scope_key)
        return int(existing["summary_id"]), False

    version_no = fetch_next_summary_version_no(cur, product_id, summary_type, scope_key)
    cur.execute(
        """
        UPDATE tb_story_agent_context_summary
           SET is_active = 'N'
         WHERE product_id = %s
           AND summary_type = %s
           AND scope_key = %s
           AND is_active = 'Y'
        """,
        (product_id, summary_type, scope_key),
    )
    cur.execute(
        """
        INSERT INTO tb_story_agent_context_summary (
            product_id,
            summary_type,
            scope_key,
            episode_from,
            episode_to,
            source_hash,
            source_doc_count,
            version_no,
            is_active,
            summary_text,
            created_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Y', %s, %s)
        """,
        (
            product_id,
            summary_type,
            scope_key,
            episode_from,
            episode_to,
            source_hash,
            source_doc_count,
            version_no,
            summary_text,
            settings.DB_DML_DEFAULT_ID,
        ),
    )
    return int(cur.lastrowid), True


def build_compound_summaries(cur, product_id: int, product_title: str) -> dict[str, tuple[int, int]]:
    counts = {
        "range": [0, 0],
        "product": [0, 0],
        "character": [0, 0],
    }
    episode_rows = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="episode_summary")
    if not episode_rows:
        return {key: (value[0], value[1]) for key, value in counts.items()}

    episode_nos = [int(row.get("episode_from") or 0) for row in episode_rows if int(row.get("episode_from") or 0) > 0]
    desired_range_scope_keys: set[str] = set()
    for scope_key, start_episode, end_episode in build_range_scope_keys(episode_nos):
        desired_range_scope_keys.add(scope_key)
        scoped_rows = [
            row for row in episode_rows
            if start_episode <= int(row.get("episode_from") or 0) <= end_episode
        ]
        if not scoped_rows:
            continue
        upstream_components = [
            f"{int(row['summary_id'])}:{str(row['source_hash'])}"
            for row in scoped_rows
        ]
        source_hash = build_compound_summary_source_hash(RANGE_SUMMARY_FORMAT_VERSION, upstream_components)
        _, inserted = upsert_summary(
            cur,
            product_id=product_id,
            summary_type="range_summary",
            scope_key=scope_key,
            source_hash=source_hash,
            source_doc_count=len(scoped_rows),
            summary_text=build_range_summary_text(start_episode, end_episode, scoped_rows),
            episode_from=start_episode,
            episode_to=end_episode,
        )
        counts["range"][0 if inserted else 1] += 1

    deactivate_missing_active_scopes(cur, product_id, "range_summary", desired_range_scope_keys)

    range_rows_for_product = fetch_active_summary_rows(cur=cur, product_id=product_id, summary_type="range_summary")
    product_upstream_rows = range_rows_for_product or episode_rows
    product_upstream_components = [
        f"{int(row['summary_id'])}:{str(row['source_hash'])}"
        for row in product_upstream_rows
    ]
    product_summary_id, product_inserted = upsert_summary(
        cur,
        product_id=product_id,
        summary_type="product_summary",
        scope_key="product:all",
        source_hash=build_compound_summary_source_hash(PRODUCT_SUMMARY_FORMAT_VERSION, product_upstream_components),
        source_doc_count=len(product_upstream_rows),
        summary_text=build_product_summary_text(product_title=product_title, rows=product_upstream_rows),
        episode_from=min(episode_nos) if episode_nos else None,
        episode_to=max(episode_nos) if episode_nos else None,
    )
    counts["product"][0 if product_inserted else 1] += 1

    desired_character_scope_keys: set[str] = set()
    for candidate in extract_character_candidates(episode_rows):
        name = str(candidate["name"])
        scope_key = build_character_scope_key(name)
        desired_character_scope_keys.add(scope_key)
        supporting_rows = sorted(
            list(candidate["summary_rows"]),
            key=lambda row: (int(row.get("episode_from") or 0), int(row.get("summary_id") or 0)),
        )
        upstream_components = [
            f"{int(row['summary_id'])}:{str(row['source_hash'])}"
            for row in supporting_rows
        ]
        _, inserted = upsert_summary(
            cur,
            product_id=product_id,
            summary_type="character_snapshot",
            scope_key=scope_key,
            source_hash=build_compound_summary_source_hash(
                CHARACTER_SNAPSHOT_FORMAT_VERSION,
                [name, *upstream_components],
            ),
            source_doc_count=len(supporting_rows),
            summary_text=build_character_snapshot_text(name=name, candidate=candidate),
            episode_from=min(int(item) for item in set(candidate["episode_nos"])),
            episode_to=max(int(item) for item in set(candidate["episode_nos"])),
        )
        counts["character"][0 if inserted else 1] += 1

    deactivate_missing_active_scopes(cur, product_id, "character_snapshot", desired_character_scope_keys)

    return {key: (value[0], value[1]) for key, value in counts.items()}


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


async def resolve_source_payload(row: dict, use_epub_fallback: bool) -> dict[str, str] | None:
    episode_content = str(row.get("episode_content") or "").strip()
    if episode_content:
        return {
            "source_type": "episode_content",
            "source_locator": f"episode:{row['episode_id']}",
            "html_content": episode_content,
        }

    if not use_epub_fallback:
        return None

    file_name = row.get("file_name")
    if not file_name:
        return None

    epub_binary = await download_epub_binary(str(file_name))
    if epub_binary is None:
        return None

    payload = _extract_epub_payload_from_epub(epub_binary)
    html_content = str(payload.get("html_content") or "").strip()
    if not html_content:
        return None

    return {
        "source_type": "epub_fallback",
        "source_locator": str(file_name),
        "html_content": html_content,
    }


def fetch_existing_doc(cur, episode_id: int, source_hash: str, source_type: str) -> dict | None:
    cur.execute(
        """
        SELECT context_doc_id, version_no, is_active
          FROM tb_story_agent_context_doc
         WHERE episode_id = %s
           AND source_hash = %s
           AND source_type = %s
         LIMIT 1
        """,
        (episode_id, source_hash, source_type),
    )
    return cur.fetchone()


def fetch_next_version_no(cur, episode_id: int) -> int:
    cur.execute(
        """
        SELECT COALESCE(MAX(version_no), 0) AS max_version_no
          FROM tb_story_agent_context_doc
         WHERE episode_id = %s
        """,
        (episode_id,),
    )
    row = cur.fetchone() or {}
    return int(row.get("max_version_no") or 0) + 1


def fetch_existing_summary(cur, product_id: int, summary_type: str, scope_key: str, source_hash: str) -> dict | None:
    cur.execute(
        """
        SELECT summary_id, version_no, is_active
          FROM tb_story_agent_context_summary
         WHERE product_id = %s
           AND summary_type = %s
           AND scope_key = %s
           AND source_hash = %s
         LIMIT 1
        """,
        (product_id, summary_type, scope_key, source_hash),
    )
    return cur.fetchone()


def fetch_next_summary_version_no(cur, product_id: int, summary_type: str, scope_key: str) -> int:
    cur.execute(
        """
        SELECT COALESCE(MAX(version_no), 0) AS max_version_no
          FROM tb_story_agent_context_summary
         WHERE product_id = %s
           AND summary_type = %s
           AND scope_key = %s
        """,
        (product_id, summary_type, scope_key),
    )
    row = cur.fetchone() or {}
    return int(row.get("max_version_no") or 0) + 1


def activate_existing_summary(cur, summary_id: int, product_id: int, summary_type: str, scope_key: str) -> None:
    cur.execute(
        """
        UPDATE tb_story_agent_context_summary
           SET is_active = 'N'
         WHERE product_id = %s
           AND summary_type = %s
           AND scope_key = %s
           AND is_active = 'Y'
           AND summary_id <> %s
        """,
        (product_id, summary_type, scope_key, summary_id),
    )
    cur.execute(
        """
        UPDATE tb_story_agent_context_summary
           SET is_active = 'Y'
         WHERE summary_id = %s
        """,
        (summary_id,),
    )


def activate_existing_doc(cur, episode_id: int, context_doc_id: int) -> None:
    cur.execute(
        """
        UPDATE tb_story_agent_context_doc
           SET is_active = 'N'
         WHERE episode_id = %s
           AND is_active = 'Y'
           AND context_doc_id <> %s
        """,
        (episode_id, context_doc_id),
    )
    cur.execute(
        """
        UPDATE tb_story_agent_context_doc
           SET is_active = 'Y'
         WHERE context_doc_id = %s
        """,
        (context_doc_id,),
    )


def insert_doc_and_chunks(cur, row: dict, source: dict[str, str], normalized_text: str, chunks: list[dict[str, object]]) -> int:
    source_hash = sha256_text(normalized_text)
    existing = fetch_existing_doc(
        cur=cur,
        episode_id=int(row["episode_id"]),
        source_hash=source_hash,
        source_type=str(source["source_type"]),
    )
    if existing:
        activate_existing_doc(cur, int(row["episode_id"]), int(existing["context_doc_id"]))
        return int(existing["context_doc_id"])

    version_no = fetch_next_version_no(cur, int(row["episode_id"]))
    cur.execute(
        """
        UPDATE tb_story_agent_context_doc
           SET is_active = 'N'
         WHERE episode_id = %s
           AND is_active = 'Y'
        """,
        (int(row["episode_id"]),),
    )
    cur.execute(
        """
        INSERT INTO tb_story_agent_context_doc (
            product_id,
            episode_id,
            episode_no,
            source_type,
            source_locator,
            source_hash,
            source_text_length,
            version_no,
            is_active,
            created_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Y', %s)
        """,
        (
            int(row["product_id"]),
            int(row["episode_id"]),
            int(row["episode_no"]),
            str(source["source_type"]),
            str(source["source_locator"]),
            source_hash,
            len(normalized_text),
            version_no,
            settings.DB_DML_DEFAULT_ID,
        ),
    )
    context_doc_id = int(cur.lastrowid)

    cur.executemany(
        """
        INSERT INTO tb_story_agent_context_chunk (
            context_doc_id,
            product_id,
            episode_id,
            episode_no,
            chunk_no,
            text_hash,
            char_start,
            char_end,
            text,
            created_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        [
            (
                context_doc_id,
                int(row["product_id"]),
                int(row["episode_id"]),
                int(row["episode_no"]),
                int(chunk["chunk_no"]),
                str(chunk["text_hash"]),
                int(chunk["char_start"]),
                int(chunk["char_end"]),
                str(chunk["text"]),
                settings.DB_DML_DEFAULT_ID,
            )
            for chunk in chunks
        ],
    )
    return context_doc_id


def insert_episode_summary(
    cur,
    row: dict,
    source_hash: str,
    normalized_text: str,
) -> tuple[int, bool]:
    product_id = int(row["product_id"])
    episode_id = int(row["episode_id"])
    episode_no = int(row["episode_no"])
    scope_key = f"episode:{episode_id}"
    summary_type = "episode_summary"
    summary_source_hash = build_summary_source_hash(source_hash, str(row.get("episode_title") or ""))

    existing = fetch_existing_summary(
        cur=cur,
        product_id=product_id,
        summary_type=summary_type,
        scope_key=scope_key,
        source_hash=summary_source_hash,
    )
    if existing:
        activate_existing_summary(cur, int(existing["summary_id"]), product_id, summary_type, scope_key)
        return int(existing["summary_id"]), False

    version_no = fetch_next_summary_version_no(cur, product_id, summary_type, scope_key)
    cur.execute(
        """
        UPDATE tb_story_agent_context_summary
           SET is_active = 'N'
         WHERE product_id = %s
           AND summary_type = %s
           AND scope_key = %s
           AND is_active = 'Y'
        """,
        (product_id, summary_type, scope_key),
    )
    summary_text = build_episode_summary_text(row=row, normalized_text=normalized_text)
    cur.execute(
        """
        INSERT INTO tb_story_agent_context_summary (
            product_id,
            summary_type,
            scope_key,
            episode_from,
            episode_to,
            source_hash,
            source_doc_count,
            version_no,
            is_active,
            summary_text,
            created_id
        ) VALUES (%s, %s, %s, %s, %s, %s, 1, %s, 'Y', %s, %s)
        """,
        (
            product_id,
            summary_type,
            scope_key,
            episode_no,
            episode_no,
            summary_source_hash,
            version_no,
            summary_text,
            settings.DB_DML_DEFAULT_ID,
        ),
    )
    return int(cur.lastrowid), True


def refresh_product_context_status(cur, product_id: int, total_episode_count: int) -> dict[str, object]:
    cur.execute(
        """
        SELECT COUNT(*) AS ready_episode_count
          FROM tb_story_agent_context_summary
         WHERE product_id = %s
           AND summary_type = 'episode_summary'
           AND is_active = 'Y'
        """,
        (product_id,),
    )
    row = cur.fetchone() or {}
    ready_episode_count = int(row.get("ready_episode_count") or 0)

    if ready_episode_count <= 0:
        context_status = "pending"
    elif ready_episode_count < total_episode_count:
        context_status = "processing"
    else:
        context_status = "ready"

    cur.execute(
        """
        INSERT INTO tb_story_agent_context_product (
            product_id,
            context_status,
            total_episode_count,
            ready_episode_count,
            last_built_at,
            last_error_message,
            created_id,
            updated_id
        ) VALUES (%s, %s, %s, %s, NOW(), NULL, %s, %s)
        ON DUPLICATE KEY UPDATE
            context_status = VALUES(context_status),
            total_episode_count = VALUES(total_episode_count),
            ready_episode_count = VALUES(ready_episode_count),
            last_built_at = VALUES(last_built_at),
            last_error_message = NULL,
            updated_id = VALUES(updated_id)
        """,
        (
            product_id,
            context_status,
            total_episode_count,
            ready_episode_count,
            settings.DB_DML_DEFAULT_ID,
            settings.DB_DML_DEFAULT_ID,
        ),
    )
    return {
        "product_id": product_id,
        "context_status": context_status,
        "total_episode_count": total_episode_count,
        "ready_episode_count": ready_episode_count,
    }


def fetch_total_episode_count(cur, product_id: int) -> int:
    cur.execute(
        """
        SELECT COUNT(*) AS total_episode_count
          FROM tb_product p
          JOIN tb_product_episode pe
            ON pe.product_id = p.product_id
         WHERE p.product_id = %s
           AND p.price_type = 'free'
           AND pe.use_yn = 'Y'
        """,
        (product_id,),
    )
    row = cur.fetchone() or {}
    return int(row.get("total_episode_count") or 0)


async def build_context_rows(rows: Iterable[dict], args: argparse.Namespace, conn) -> dict[str, object]:
    results = {
        "inserted_docs": 0,
        "reused_docs": 0,
        "inserted_summaries": 0,
        "reused_summaries": 0,
        "inserted_range_summaries": 0,
        "reused_range_summaries": 0,
        "inserted_product_summaries": 0,
        "reused_product_summaries": 0,
        "inserted_character_snapshots": 0,
        "reused_character_snapshots": 0,
        "skipped_rows": 0,
        "products": [],
    }

    rows_by_product: dict[int, list[dict]] = {}
    for row in rows:
        rows_by_product.setdefault(int(row["product_id"]), []).append(row)

    with conn.cursor() as cur:
        for product_id, product_rows in rows_by_product.items():
            product_failed = False
            failed_ready_episode_count = 0
            total_episode_count = fetch_total_episode_count(cur=cur, product_id=product_id)
            product_lock_acquired = False
            if args.apply:
                product_lock_acquired = acquire_product_lock(cur, product_id)
                if not product_lock_acquired:
                    results["products"].append(
                        {
                            "product_id": product_id,
                            "context_status": "locked",
                            "total_episode_count": total_episode_count,
                            "ready_episode_count": 0,
                        }
                    )
                    if args.verbose:
                        print(f"[skip] product_id={product_id} lock busy")
                    continue
                cur.execute("SAVEPOINT story_agent_product_batch")
            try:
                for row in product_rows:
                    source = await resolve_source_payload(row=row, use_epub_fallback=args.use_epub_fallback)
                    if source is None:
                        results["skipped_rows"] += 1
                        if args.verbose:
                            print(
                                f"[skip] product_id={row['product_id']} episode_id={row['episode_id']} source unavailable"
                            )
                        continue

                    normalized_text = normalize_episode_html(source["html_content"])
                    if not normalized_text:
                        results["skipped_rows"] += 1
                        if args.verbose:
                            print(
                                f"[skip] product_id={row['product_id']} episode_id={row['episode_id']} normalized text empty"
                            )
                        continue

                    chunks = build_chunks(normalized_text)
                    if not chunks:
                        results["skipped_rows"] += 1
                        if args.verbose:
                            print(
                                f"[skip] product_id={row['product_id']} episode_id={row['episode_id']} chunks empty"
                            )
                        continue

                    source_hash = sha256_text(normalized_text)
                    existing = fetch_existing_doc(
                        cur=cur,
                        episode_id=int(row["episode_id"]),
                        source_hash=source_hash,
                        source_type=str(source["source_type"]),
                    )

                    if args.apply:
                        try:
                            context_doc_id = insert_doc_and_chunks(
                                cur=cur,
                                row=row,
                                source=source,
                                normalized_text=normalized_text,
                                chunks=chunks,
                            )
                            if existing:
                                results["reused_docs"] += 1
                            else:
                                results["inserted_docs"] += 1
                            _, inserted_summary = insert_episode_summary(
                                cur=cur,
                                row=row,
                                source_hash=source_hash,
                                normalized_text=normalized_text,
                            )
                            if inserted_summary:
                                results["inserted_summaries"] += 1
                            else:
                                results["reused_summaries"] += 1
                            if args.verbose:
                                print(
                                    f"[ok] product_id={row['product_id']} episode_no={row['episode_no']} "
                                    f"context_doc_id={context_doc_id} source={source['source_type']} chunks={len(chunks)}"
                                )
                        except Exception as exc:
                            product_failed = True
                            cur.execute("ROLLBACK TO SAVEPOINT story_agent_product_batch")
                            cur.execute(
                                """
                                SELECT COUNT(*) AS ready_episode_count
                                  FROM tb_story_agent_context_summary
                                 WHERE product_id = %s
                                   AND summary_type = 'episode_summary'
                                   AND is_active = 'Y'
                                """,
                                (product_id,),
                            )
                            ready_row = cur.fetchone() or {}
                            failed_ready_episode_count = int(ready_row.get("ready_episode_count") or 0)
                            cur.execute(
                                """
                                INSERT INTO tb_story_agent_context_product (
                                    product_id,
                                    context_status,
                                    total_episode_count,
                                    ready_episode_count,
                                    last_error_message,
                                    created_id,
                                    updated_id
                                ) VALUES (%s, 'failed', %s, %s, %s, %s, %s)
                                ON DUPLICATE KEY UPDATE
                                    context_status = 'failed',
                                    total_episode_count = VALUES(total_episode_count),
                                    ready_episode_count = VALUES(ready_episode_count),
                                    last_error_message = VALUES(last_error_message),
                                    updated_id = VALUES(updated_id)
                                """,
                                (
                                    product_id,
                                    total_episode_count,
                                    failed_ready_episode_count,
                                    str(exc)[:500],
                                    settings.DB_DML_DEFAULT_ID,
                                    settings.DB_DML_DEFAULT_ID,
                                ),
                            )
                            if args.verbose:
                                print(
                                    f"[failed] product_id={product_id} episode_id={row['episode_id']} error={str(exc)[:200]}"
                                )
                            break
                    else:
                        if existing:
                            results["reused_docs"] += 1
                        else:
                            results["inserted_docs"] += 1
                        existing_summary = fetch_existing_summary(
                            cur=cur,
                            product_id=int(row["product_id"]),
                            summary_type="episode_summary",
                            scope_key=f"episode:{int(row['episode_id'])}",
                            source_hash=build_summary_source_hash(source_hash, str(row.get("episode_title") or "")),
                        )
                        if existing_summary:
                            results["reused_summaries"] += 1
                        else:
                            results["inserted_summaries"] += 1
                        if args.verbose:
                            print(
                                f"[dry-run] product_id={row['product_id']} episode_no={row['episode_no']} "
                                f"source={source['source_type']} hash={source_hash[:10]} chunks={len(chunks)}"
                            )

                if args.apply and not product_failed:
                    compound_counts = build_compound_summaries(
                        cur=cur,
                        product_id=product_id,
                        product_title=str(product_rows[0].get("title") or ""),
                    )
                    results["inserted_range_summaries"] += compound_counts["range"][0]
                    results["reused_range_summaries"] += compound_counts["range"][1]
                    results["inserted_product_summaries"] += compound_counts["product"][0]
                    results["reused_product_summaries"] += compound_counts["product"][1]
                    results["inserted_character_snapshots"] += compound_counts["character"][0]
                    results["reused_character_snapshots"] += compound_counts["character"][1]

                    status_row = refresh_product_context_status(
                        cur=cur,
                        product_id=product_id,
                        total_episode_count=total_episode_count,
                    )
                    results["products"].append(status_row)
                    cur.execute("RELEASE SAVEPOINT story_agent_product_batch")
                    conn.commit()
                elif args.apply and product_failed:
                    results["products"].append(
                        {
                            "product_id": product_id,
                            "context_status": "failed",
                            "total_episode_count": total_episode_count,
                            "ready_episode_count": failed_ready_episode_count,
                        }
                    )
                    cur.execute("RELEASE SAVEPOINT story_agent_product_batch")
                    conn.commit()
                elif not args.apply:
                    results["products"].append(
                        {
                            "product_id": product_id,
                            "context_status": "dry-run",
                            "total_episode_count": total_episode_count,
                            "ready_episode_count": 0,
                        }
                    )
            finally:
                if args.apply and product_lock_acquired:
                    release_product_lock(cur, product_id)
    return results


def print_summary(results: dict[str, object], apply: bool) -> None:
    print(
        f"mode={'apply' if apply else 'dry-run'} "
        f"inserted_docs={results['inserted_docs']} reused_docs={results['reused_docs']} "
        f"inserted_summaries={results['inserted_summaries']} reused_summaries={results['reused_summaries']} "
        f"inserted_range_summaries={results['inserted_range_summaries']} reused_range_summaries={results['reused_range_summaries']} "
        f"inserted_product_summaries={results['inserted_product_summaries']} reused_product_summaries={results['reused_product_summaries']} "
        f"inserted_character_snapshots={results['inserted_character_snapshots']} reused_character_snapshots={results['reused_character_snapshots']} "
        f"skipped_rows={results['skipped_rows']}"
    )
    for product in list(results.get("products") or [])[:20]:
        print(
            "product",
            f"product_id={product['product_id']}",
            f"status={product['context_status']}",
            f"ready={product['ready_episode_count']}",
            f"total={product['total_episode_count']}",
        )


async def main() -> int:
    args = parse_args()
    query, params = build_target_query(args=args, use_epub_fallback=args.use_epub_fallback)
    conn = db_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = list(cur.fetchall())

        results = await build_context_rows(rows=rows, args=args, conn=conn)
        print_summary(results=results, apply=args.apply)
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
