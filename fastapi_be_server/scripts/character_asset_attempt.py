"""Non-serving, immutable receipts for finite character asset requests.

Owned by one batch-lifetime autocommit connection, never the serving transaction.
An ambiguous submission stays inflight; there is deliberately no TTL or retry reset.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

import pymysql


STAGES = frozenset({"signals", "scenes", "protagonist_resolution", "rp_profile", "rp_dialogue"})


class CharacterAssetAttemptBlocked(RuntimeError):
    pass


def canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def payload_hash(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def attempt_key(product_id: int, stage: str, scope: str, contract: str, request: dict) -> tuple[int, str, str, str]:
    if product_id <= 0 or stage not in STAGES or not scope or len(scope) > 80 or not contract:
        raise CharacterAssetAttemptBlocked("invalid_attempt_identity")
    return (product_id, stage, scope, payload_hash({"contract": contract, "request": request}))


class CharacterAssetAttemptStore:
    def __init__(self, connection):
        # Caller must supply a separate autocommit connection; no reconnect fallback.
        self.connection = connection
        with connection.cursor() as cur:
            cur.execute("""SELECT product_id, stage_key, scope_key, input_hash, status,
                accepted_payload, payload_hash, error_code
                FROM tb_story_agent_character_asset_attempt WHERE 1 = 0""")

    def load(self, key, validate: Callable[[object], dict]) -> dict | None:
        with self.connection.cursor() as cur:
            cur.execute("""SELECT status, accepted_payload, payload_hash, error_code
                FROM tb_story_agent_character_asset_attempt
                WHERE product_id=%s AND stage_key=%s AND scope_key=%s AND input_hash=%s""", key)
            row = cur.fetchone()
        if row is None:
            return None
        if row["status"] != "accepted":
            raise CharacterAssetAttemptBlocked(f"character_asset_attempt:{row['status']}:{row.get('error_code') or 'attention'}")
        try:
            payload = json.loads(row["accepted_payload"])
            if payload_hash(payload) != row["payload_hash"]:
                raise ValueError("payload_hash")
            validated = validate(payload)
            if canonical_json(validated) != canonical_json(payload):
                raise ValueError("noncanonical_payload")
            return validated
        except (TypeError, ValueError, KeyError) as exc:
            raise CharacterAssetAttemptBlocked(f"accepted_receipt_invalid:{exc}") from exc

    def claim(self, key) -> None:
        try:
            with self.connection.cursor() as cur:
                cur.execute("""INSERT INTO tb_story_agent_character_asset_attempt
                    (product_id, stage_key, scope_key, input_hash, status)
                    VALUES (%s,%s,%s,%s,'inflight')""", key)
        except pymysql.err.IntegrityError as exc:
            if exc.args[0] != 1062:
                raise
            raise CharacterAssetAttemptBlocked("duplicate_claim:recheck_on_next_run") from exc

    def accept(self, key, payload: dict) -> None:
        self._finish(key, "accepted", canonical_json(payload), payload_hash(payload), None)

    def reject(self, key, error: str) -> None:
        self._finish(key, "terminal_invalid", None, None, error[:100])

    def _finish(self, key, status, payload, digest, error) -> None:
        with self.connection.cursor() as cur:
            cur.execute("""UPDATE tb_story_agent_character_asset_attempt
                SET status=%s, accepted_payload=%s, payload_hash=%s, error_code=%s
                WHERE product_id=%s AND stage_key=%s AND scope_key=%s AND input_hash=%s
                  AND status='inflight'""", (status, payload, digest, error, *key))
            if cur.rowcount != 1:
                raise CharacterAssetAttemptBlocked("invalid_terminal_transition")
