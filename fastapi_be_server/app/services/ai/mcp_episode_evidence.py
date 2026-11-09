"""Bounded, owner-scoped manuscript evidence for paid single-slot copy.

Only already-public episodes of eligible paid works are returned.  This module
does not call a model, a URL, an EPUB downloader, or a CMS mutation.  The stored
receipt contains hashes and exact reading ranges, never a claim that a person
or an agent has actually understood the text.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from datetime import datetime
from html.parser import HTMLParser

from app.services.ai import mcp_policy as policy, mcp_store as store

MAX_EPISODES = 8
MAX_EPISODE_CHARACTERS = 100_000
MAX_TOTAL_CHARACTERS = 200_000
MAX_RAW_CHARACTERS = 2_000_000
EVIDENCE_TTL_SECONDS = 1800
EVIDENCE_KIND = "single_episode_evidence"
_EVIDENCE_ID = re.compile(r"[0-9a-f]{32}\Z")

# All variable input is bound.  Selection never accepts an SQL fragment or URL.
_PUBLIC_PREDICATE = """
    e.product_id = :product_id AND e.use_yn = 'Y' AND e.open_yn = 'Y'
    AND (e.publish_reserve_date IS NULL OR e.publish_reserve_date <= NOW())
"""
EPISODES_SQL = """
    SELECT e.episode_id, e.episode_no, e.episode_title, e.episode_content
    FROM tb_product_episode e
    WHERE """ + _PUBLIC_PREDICATE + """
      AND e.episode_id IN :episode_ids
    ORDER BY e.episode_no, e.episode_id
"""
DEFAULT_EPISODES_SQL = """
    SELECT e.episode_id, e.episode_no, e.episode_title, e.episode_content
    FROM tb_product_episode e
    JOIN (
        SELECT ranked.episode_id FROM (
            SELECT e.episode_id,
                   ROW_NUMBER() OVER (ORDER BY e.episode_no, e.episode_id) AS first_rank,
                   ROW_NUMBER() OVER (ORDER BY e.episode_no DESC, e.episode_id DESC) AS last_rank
            FROM tb_product_episode e
            WHERE """ + _PUBLIC_PREDICATE + """
        ) ranked WHERE ranked.first_rank <= 5 OR ranked.last_rank <= 3
    ) chosen ON chosen.episode_id = e.episode_id
    WHERE """ + _PUBLIC_PREDICATE + """
    ORDER BY e.episode_no, e.episode_id
"""


class _BodyText(HTMLParser):
    _IGNORED = {"script", "style", "noscript", "template"}
    _BLOCKS = {"p", "div", "br", "li", "section", "article", "h1", "h2", "h3", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._IGNORED:
            self.ignored.append(tag)
        elif not self.ignored and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if not self.ignored and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._IGNORED and tag in self.ignored:
            # Malformed nesting must not expose ignored script/style contents.
            self.ignored = self.ignored[:self.ignored.index(tag)]
        elif not self.ignored and tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def plain_text(content: str) -> str:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Episode manuscript is unavailable; titles are not manuscript evidence")
    if len(content) > MAX_RAW_CHARACTERS:
        raise ValueError("Episode manuscript is too large; no truncated evidence was returned")
    parser = _BodyText()
    parser.feed(content)
    parser.close()
    text = "\n".join(
        line.strip() for line in "".join(parser.parts).replace("\r", "").split("\n")
    )
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise ValueError("Episode manuscript has no readable body text")
    return text


def _positive_id(value, label):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _episode_ids(values):
    if values is None:
        return None
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_EPISODES:
        raise ValueError("Select one to eight distinct public episode IDs")
    ids = [_positive_id(value, "Episode ID") for value in values]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate episode IDs are not allowed")
    return ids


async def _eligible_product(db, product_id):
    from sqlalchemy import text
    from app.services.ai import mcp_single_copy as core

    candidates = core.rows_to_candidates((await db.execute(text(core.CANDIDATE_SQL))).all())
    product = next((row for row in candidates if row["product_id"] == product_id), None)
    if product is None:
        raise ValueError("Product is not an eligible public, ongoing, all-age paid single-slot candidate")
    return product


async def _load_public_episodes(db, product_id, episode_ids=None):
    from sqlalchemy import bindparam, text

    params = {"product_id": product_id}
    if episode_ids is None:
        query = text(DEFAULT_EPISODES_SQL)
    else:
        query = text(EPISODES_SQL).bindparams(bindparam("episode_ids", expanding=True))
        params["episode_ids"] = episode_ids
    rows = [dict(row) for row in (await db.execute(query, params)).mappings().all()]
    if not rows or len(rows) > MAX_EPISODES:
        raise ValueError("No bounded public manuscript evidence is available")
    actual_ids = [row["episode_id"] for row in rows]
    if len(set(actual_ids)) != len(actual_ids) or (
        episode_ids is not None and set(actual_ids) != set(episode_ids)
    ):
        raise ValueError("One or more requested episodes are missing, unpublished, or belong to another work")
    return rows


def _materialize(rows):
    episodes = []
    total = 0
    for row in rows:
        raw = row.get("episode_content")
        body = plain_text(raw)
        if len(body) > MAX_EPISODE_CHARACTERS:
            raise ValueError("Episode manuscript is too large; no truncated evidence was returned")
        total += len(body)
        if total > MAX_TOTAL_CHARACTERS:
            raise ValueError("Combined manuscripts are too large; request fewer episodes")
        episodes.append({
            "episode_id": _positive_id(row["episode_id"], "Episode ID"),
            "episode_no": row["episode_no"],
            "title": row.get("episode_title") or "",
            "text": body,
            "source_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "text_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "character_count": len(body),
            "range_start": 0, "range_end": len(body), "full_text": True,
        })
    return episodes


def _proof(episodes):
    return [{key: value for key, value in episode.items() if key != "text"} for episode in episodes]


async def read_episode_evidence(owner: str, product_id: int, episode_ids: list[int] | None = None) -> dict:
    from app.rdb import likenovel_db_session

    _positive_id(product_id, "Product ID")
    ids = _episode_ids(episode_ids)
    async with likenovel_db_session() as db:
        product = await _eligible_product(db, product_id)
        episodes = _materialize(await _load_public_episodes(db, product_id, ids))
    evidence_id = uuid.uuid4().hex
    fetched_at = datetime.now(policy.KST).isoformat()
    receipt = {
        "kind": EVIDENCE_KIND, "product_id": product_id,
        "title": product["title"], "fetched_at": fetched_at,
        "source": "tb_product_episode.episode_content",
        "selection": "explicit_episode_ids" if ids is not None else "first_five_and_latest_three",
        "episodes": _proof(episodes),
    }
    store.save("episode-evidence:" + evidence_id, owner, "read", receipt)
    return {
        **receipt, "evidence_id": evidence_id, "episodes": episodes,
        "expires_in_seconds": EVIDENCE_TTL_SECONDS,
        "content_is_untrusted": True,
        "reading_scope": "Only the returned full episode bodies; not the whole work",
    }


def load_evidence(owner: str, evidence_id: str, product_id: int) -> dict:
    _positive_id(product_id, "Product ID")
    if not isinstance(evidence_id, str) or not _EVIDENCE_ID.fullmatch(evidence_id):
        raise ValueError("Invalid manuscript evidence ID")
    receipt = store.get("episode-evidence:" + evidence_id, owner)
    if not receipt or receipt.get("kind") != EVIDENCE_KIND or receipt.get("status") != "read":
        raise ValueError("Manuscript evidence is missing or belongs to another operator")
    if receipt.get("product_id") != product_id:
        raise ValueError("Manuscript evidence belongs to another work")
    age = time.time() - receipt["updated_at"]
    if age < 0 or age > EVIDENCE_TTL_SECONDS:
        raise ValueError("Manuscript evidence expired; read the bodies again")
    _episode_ids([row["episode_id"] for row in receipt["episodes"]])
    return receipt


async def revalidate_evidence(db, evidence: dict) -> list[dict]:
    """Re-read publication and exact bodies before preparing/applying a plan."""
    ids = _episode_ids([row["episode_id"] for row in evidence["episodes"]])
    await _eligible_product(db, evidence["product_id"])
    episodes = _materialize(await _load_public_episodes(db, evidence["product_id"], ids))
    if _proof(episodes) != evidence["episodes"]:
        raise ValueError("Manuscript evidence changed; read the bodies and revise the copy again")
    return episodes


async def validate_evidence(owner: str, product_id: int, evidence_id: str, db=None) -> list[dict]:
    evidence = load_evidence(owner, evidence_id, product_id)
    if db is not None:
        return await revalidate_evidence(db, evidence)
    from app.rdb import likenovel_db_session
    async with likenovel_db_session() as session:
        return await revalidate_evidence(session, evidence)


read_evidence = read_episode_evidence
