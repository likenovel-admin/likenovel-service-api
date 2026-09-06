import json
from copy import deepcopy
from unittest import IsolatedAsyncioTestCase

import pymysql
import pytest

from scripts.character_asset_attempt import CharacterAssetAttemptStore, CharacterAssetAttemptBlocked, attempt_key


class ReceiptConnection:
    """DB boundary fake; real store SQL, hashes and state transitions still run."""
    def __init__(self):
        self.rows = {}
        self.closed = False

    def cursor(self):
        return ReceiptCursor(self)

    def close(self):
        self.closed = True


class ReceiptCursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = None
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, params=()):
        if "WHERE 1 = 0" in sql:
            return
        if sql.lstrip().startswith("SELECT"):
            self.result = deepcopy(self.conn.rows.get(tuple(params)))
        elif sql.lstrip().startswith("INSERT"):
            key = tuple(params[:4])
            if key in self.conn.rows:
                raise pymysql.err.IntegrityError(1062, "duplicate")
            self.conn.rows[key] = {"status": "inflight", "accepted_payload": None, "payload_hash": None, "error_code": None}
            self.rowcount = 1
        elif sql.lstrip().startswith("UPDATE"):
            status, payload, digest, error, *key = params
            row = self.conn.rows.get(tuple(key))
            if row and row["status"] == "inflight":
                row.update(status=status, accepted_payload=payload, payload_hash=digest, error_code=error)
                self.rowcount = 1
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.result


def require_payload(payload):
    if not isinstance(payload, dict) or payload.get("valid") is not True:
        raise ValueError("contract_invalid")
    return payload


def test_accepted_receipt_survives_work_rollback_and_revalidates():
    db = ReceiptConnection()
    store = CharacterAssetAttemptStore(db)
    key = attempt_key(10, "signals", "episode:1", "v5", {"messages": ["bounded text"]})
    assert store.load(key, require_payload) is None
    store.claim(key)
    store.accept(key, {"valid": True})
    # A different serving transaction can roll back; this receipt owns its connection.
    assert CharacterAssetAttemptStore(db).load(key, require_payload) == {"valid": True}
    with pytest.raises(CharacterAssetAttemptBlocked, match="terminal_transition"):
        store.reject(key, "contract_invalid")


@pytest.mark.parametrize("state", ["inflight", "terminal_invalid"])
def test_unresolved_or_invalid_receipt_never_becomes_reusable(state):
    store = CharacterAssetAttemptStore(ReceiptConnection())
    key = attempt_key(10, "signals", "episode:1", "v5", {"text": "source"})
    store.claim(key)
    if state == "terminal_invalid":
        store.reject(key, "ungrounded_quote")
    with pytest.raises(CharacterAssetAttemptBlocked, match=state):
        store.load(key, require_payload)
    with pytest.raises(CharacterAssetAttemptBlocked, match="duplicate_claim"):
        store.claim(key)


def test_corrupt_accepted_receipt_blocks_instead_of_recalling():
    db = ReceiptConnection()
    store = CharacterAssetAttemptStore(db)
    key = attempt_key(10, "signals", "episode:1", "v5", {"text": "source"})
    store.claim(key)
    store.accept(key, {"valid": True})
    db.rows[key]["accepted_payload"] = json.dumps({"valid": True, "forged": True})
    with pytest.raises(CharacterAssetAttemptBlocked, match="payload_hash"):
        store.load(key, require_payload)


def test_hash_uses_request_not_surrogate_or_execution_mode():
    key = attempt_key(10, "signals", "episode:1", "v5", {"b": 2, "a": 1})
    assert key == attempt_key(10, "signals", "episode:1", "v5", {"a": 1, "b": 2})
    assert key != attempt_key(10, "signals", "episode:1", "v6", {"a": 1, "b": 2})
    assert key != attempt_key(10, "signals", "episode:1", "v5", {"a": 2, "b": 2})


class CharacterAssetHTTPTests(IsolatedAsyncioTestCase):
    async def test_real_submit_is_reused_after_failed_promotion_and_new_summary_id(self):
        from tests.test_story_agent_context_cost_guard import EpisodeCharacterSignalsContractTests
        fixture = EpisodeCharacterSignalsContractTests()
        with fixture.environment(fixture.response_payload()) as state:
            state.upsert.side_effect = RuntimeError("serving transaction failed")
            with pytest.raises(RuntimeError, match="serving transaction failed"):
                await state.module.build_episode_character_signals_summaries(
                    state.conn, product_id=687, episode_rows=[state.row], summary_client=state.client,
                    cleanup_missing_scopes=False, commit_changes=False,
                )
            assert len(state.client.calls) == 1
            state.conn.rollback()
            state.upsert.side_effect = None
            counts = await state.module.build_episode_character_signals_summaries(
                state.conn, product_id=687, episode_rows=[{**state.row, "summary_id": 987654}],
                summary_client=state.client, cleanup_missing_scopes=False, commit_changes=False,
            )
            assert counts == (1, 0)
            assert len(state.client.calls) == 1


    async def test_bad_second_scope_does_not_activate_good_first_scope(self):
        from tests.test_story_agent_context_cost_guard import EpisodeCharacterSignalsContractTests
        fixture = EpisodeCharacterSignalsContractTests()
        with fixture.environment(fixture.response_payload()) as state:
            # The HTTP fake repeats episode 1 output; episode 2 must fail closed.
            with pytest.raises(CharacterAssetAttemptBlocked, match="terminal_invalid"):
                await state.module.build_episode_character_signals_summaries(
                    state.conn, product_id=687, episode_rows=[state.row, {
                        **state.row, "summary_id": 2, "scope_key": "episode:2", "episode_from": 2,
                    }], summary_client=state.client, cleanup_missing_scopes=True,
                )
            assert len(state.client.calls) == 2
            state.upsert.assert_not_called()
            state.activate.assert_not_called()
            state.cleanup.assert_not_called()
            assert state.conn.commit_count == 0
            # The first accepted response survives; the second rejected response is sticky.
            with pytest.raises(CharacterAssetAttemptBlocked, match="terminal_invalid"):
                await state.module.build_episode_character_signals_summaries(
                    state.conn, product_id=687, episode_rows=[state.row, {
                        **state.row, "summary_id": 3, "scope_key": "episode:2", "episode_from": 2,
                    }], summary_client=state.client, cleanup_missing_scopes=True,
                )
            assert len(state.client.calls) == 2
            state.upsert.assert_not_called()


    async def test_no_migration_or_reserve_means_no_claim_and_no_post(self):
        from unittest.mock import patch
        from tests.test_story_agent_context_cost_guard import EpisodeCharacterSignalsContractTests
        fixture = EpisodeCharacterSignalsContractTests()
        with fixture.environment(fixture.response_payload()) as state:
            with patch.object(state.module, "_character_asset_attempt_store", None):
                with pytest.raises(CharacterAssetAttemptBlocked, match="not_initialized"):
                    await state.module.request_episode_character_signals_payload(
                        state.client, row={"episode_id": 1001, "episode_no": 1}, summary_text=state.row["summary_text"],
                    )
            assert not state.client.calls
            with patch("app.services.common.openrouter_background_credit_guard.assert_openrouter_background_credit_available_async", side_effect=state.module.OpenRouterBackgroundCreditReserveError("insufficient reserve")):
                with pytest.raises(state.module.OpenRouterBackgroundCreditReserveError):
                    await state.module.request_episode_character_signals_payload(
                        state.client, row={"episode_id": 1001, "episode_no": 1}, summary_text=state.row["summary_text"],
                    )
            assert not state.client.calls
            assert not state.module._character_asset_attempt_store.connection.rows
