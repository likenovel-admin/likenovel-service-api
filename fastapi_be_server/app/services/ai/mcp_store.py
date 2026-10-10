"""Durable receipts outside release directories, shared by API workers."""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


def _path() -> Path:
    from app.services.ai.mcp_config import load
    value = os.environ.get("LIKENOVEL_MCP_STATE_DB") or load().get("state_db", "")
    if not value:
        raise RuntimeError("LIKENOVEL_MCP_STATE_DB is not configured")
    path = Path(value)
    if not path.is_absolute() or not path.parent.is_dir():
        raise RuntimeError("MCP state directory must exist outside the release")
    return path


@contextmanager
def connection():
    path = _path()
    db = sqlite3.connect(path, timeout=5)
    os.chmod(path, 0o600)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS receipts (
            job_id TEXT PRIMARY KEY, owner TEXT NOT NULL, status TEXT NOT NULL,
            payload TEXT NOT NULL, updated REAL NOT NULL
        )
    """)
    db.commit()
    try:
        yield db
    finally:
        db.close()


def get(job_id: str, owner: str) -> dict | None:
    with connection() as db:
        row = db.execute(
            "SELECT status, payload, updated FROM receipts WHERE job_id=? AND owner=?",
            (job_id, owner),
        ).fetchone()
    return None if row is None else {
        "job_id": job_id, "status": row[0], **json.loads(row[1]), "updated_at": row[2],
    }


def save(job_id: str, owner: str, status: str, payload: dict):
    with connection() as db:
        result = db.execute("""
            INSERT INTO receipts VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET status=excluded.status,
              payload=excluded.payload, updated=excluded.updated
            WHERE receipts.owner=excluded.owner
        """, (job_id, owner, status, json.dumps(payload, ensure_ascii=False), time.time()))
        if result.rowcount != 1:
            raise RuntimeError("Receipt belongs to another identity")
        db.commit()


def claim(job_id: str, owner: str, payload: dict) -> bool:
    with connection() as db:
        result = db.execute(
            "INSERT OR IGNORE INTO receipts VALUES (?, ?, 'generating', ?, ?)",
            (job_id, owner, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        db.commit()
        return result.rowcount == 1


def consume(job_id: str, owner: str, expected: str) -> bool:
    with connection() as db:
        result = db.execute(
            "UPDATE receipts SET status='used', updated=? WHERE job_id=? AND owner=? AND status=?",
            (time.time(), job_id, owner, expected),
        )
        db.commit()
        return result.rowcount == 1


def increment_counter(job_id: str, owner: str) -> int:
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT owner,payload FROM receipts WHERE job_id=?", (job_id,),
        ).fetchone()
        if row and row[0] != owner:
            raise RuntimeError("Counter belongs to another identity")
        count = (json.loads(row[1])["count"] if row else 0) + 1
        db.execute(
            "INSERT OR REPLACE INTO receipts VALUES (?,?,'counter',?,?)",
            (job_id, owner, json.dumps({"count": count}), time.time()),
        )
        db.commit()
        return count


def recent(owner: str) -> list[dict]:
    with connection() as db:
        rows = db.execute(
            """SELECT job_id,status,updated FROM receipts WHERE owner=?
               AND (job_id LIKE 'direct:%' OR job_id LIKE 'single:%')
               ORDER BY updated DESC LIMIT 20""",
            (owner,),
        ).fetchall()
    return [{"job_id": row[0], "status": row[1], "updated_at": row[2]} for row in rows]
