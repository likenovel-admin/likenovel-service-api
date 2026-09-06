"""Opt-in tests against the explicitly scoped, existing local MySQL container."""
import copy
import json
import os
from pathlib import Path
import subprocess

import pymysql
from pymysql.cursors import DictCursor
import pytest

from app.services.websochat.character_chat_product_policy import (
    build_character_chat_rp_profile_ready_sql,
    is_character_chat_rp_profile_payload_ready,
)
from app.services.websochat import character_chat_product_policy as character_policy
from scripts.build_story_agent_context import upsert_summary
from scripts.character_asset_attempt import (
    CharacterAssetAttemptBlocked,
    CharacterAssetAttemptStore,
    attempt_key,
)


pytestmark = pytest.mark.skipif(
    os.getenv("LN_CHARACTER_CONTRACT_MYSQL_TEST") != "1",
    reason="requires explicit isolated local MySQL opt-in",
)
SCHEMA = "ln_character_contract_test_20260906"
ROOT = Path(__file__).resolve().parents[1]
SCOPE = "character:test"


@pytest.fixture
def local_mysql():
    """Never adopt or clean up a schema that existed before this test."""
    if os.getenv("DB_IP") != "127.0.0.1" or os.getenv("DB_PORT") != "1":
        pytest.fail("default application DB must be disabled with 127.0.0.1:1")
    result = subprocess.run(
        ["docker", "inspect", "likenovel-mysql"],
        check=True, capture_output=True, text=True,
    )
    metadata = json.loads(result.stdout)[0]
    config = metadata["Config"]
    labels = config.get("Labels") or {}
    ports = metadata["NetworkSettings"]["Ports"].get("3306/tcp") or []
    if (
        metadata["Name"] != "/likenovel-mysql"
        or config["Image"] != "mysql:8.0"
        or not metadata["State"]["Running"]
        or metadata["State"].get("Health", {}).get("Status") != "healthy"
        or labels.get("com.docker.compose.service") != "mysql"
        or labels.get("com.docker.compose.project.working_dir") != str(ROOT)
        or not ports
        or any(binding["HostPort"] != "3806" for binding in ports)
    ):
        pytest.fail("local MySQL container identity or health mismatch; no mutation")
    environment = dict(item.split("=", 1) for item in config["Env"] if "=" in item)
    password = environment.get("MYSQL_ROOT_PASSWORD")
    if not password:
        pytest.fail("container-owned root credential unavailable; no mutation")
    connection_args = {
        "host": "127.0.0.1", "port": 3806, "user": "root", "password": password,
        "charset": "utf8mb4", "cursorclass": DictCursor,
        "connect_timeout": 5, "read_timeout": 10, "write_timeout": 10,
    }
    control = pymysql.connect(**connection_args, autocommit=True)
    connections = []
    created_schema = False
    try:
        with control.cursor() as cur:
            cur.execute("SELECT @@hostname AS hostname, @@port AS port, VERSION() AS version")
            identity = cur.fetchone()
            if identity["hostname"] != config["Hostname"] or identity["port"] != 3306:
                pytest.fail("forwarded server identity mismatch; no mutation")
            cur.execute("SELECT COUNT(*) AS n FROM information_schema.schemata WHERE schema_name=%s", (SCHEMA,))
            if cur.fetchone()["n"]:
                pytest.fail("test schema already exists; refusing adoption or cleanup")
            cur.execute(f"CREATE DATABASE `{SCHEMA}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
            created_schema = True
        for autocommit in (True, True, False):
            connection = pymysql.connect(**connection_args, database=SCHEMA, autocommit=autocommit)
            connections.append(connection)
        yield {"attempt": connections[0], "competitor": connections[1], "work": connections[2]}
    finally:
        close_errors = []
        for connection in reversed(connections):
            try:
                connection.close()
            except Exception as exc:
                close_errors.append(type(exc).__name__)
        try:
            if created_schema:
                if close_errors:
                    raise RuntimeError("test connection cleanup failed; owned schema remains: " + SCHEMA)
                with control.cursor() as cur:
                    cur.execute(f"DROP DATABASE `{SCHEMA}`")
                    cur.execute("SELECT COUNT(*) AS n FROM information_schema.schemata WHERE schema_name=%s", (SCHEMA,))
                    if cur.fetchone()["n"]:
                        raise RuntimeError("test schema cleanup did not remove " + SCHEMA)
                print(f"cleanup schema={SCHEMA} schema_absent=true work_and_attempt_connections_closed=true")
        finally:
            control.close()


def _migrate(connection):
    sql = (ROOT / "dist/init/111-create-character-asset-attempt.sql").read_text()
    with connection.cursor() as cur:
        cur.execute(sql)


def _summary_table(connection):
    statements = (ROOT / "dist/init/80-create-story-agent-context-tables.sql").read_text().split(";")
    ddl = next(statement for statement in statements if "CREATE TABLE IF NOT EXISTS tb_story_agent_context_summary (" in statement)
    with connection.cursor() as cur:
        cur.execute(ddl)


def test_migration_is_idempotent_and_missing_table_preflight_fails(local_mysql):
    connection = local_mysql["attempt"]
    with pytest.raises(pymysql.err.ProgrammingError) as failure:
        CharacterAssetAttemptStore(connection)
    assert failure.value.args[0] == 1146
    _migrate(connection)
    first = CharacterAssetAttemptStore(connection)
    key = attempt_key(1, "signals", "episode:1", "v1", {"source": "원문"})
    first.claim(key)
    _migrate(connection)
    with pytest.raises(CharacterAssetAttemptBlocked, match="inflight"):
        CharacterAssetAttemptStore(connection).load(key, lambda value: value)
    with connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM tb_story_agent_character_asset_attempt")
        assert cur.fetchone()["n"] == 1


def test_receipt_commit_survives_actual_serving_summary_rollback(local_mysql):
    attempt, observer, work = (local_mysql[key] for key in ("attempt", "competitor", "work"))
    _migrate(attempt)
    _summary_table(attempt)
    common = {"product_id": 2, "summary_type": "character_rp_profile", "scope_key": SCOPE, "source_doc_count": 1}
    with work.cursor() as cur:
        old_id, created = upsert_summary(cur, **common, source_hash="a" * 64, summary_text='{"old":true}')
    assert created
    work.commit()
    store = CharacterAssetAttemptStore(attempt)
    key = attempt_key(2, "signals", "episode:1", "v1", {"source": "새 원문"})
    store.claim(key)
    accepted = {"character_key": SCOPE, "quote": "먼저 출구를 살폈다."}
    store.accept(key, accepted)
    with work.cursor() as cur:
        new_id, created = upsert_summary(cur, **common, source_hash="b" * 64, summary_text=json.dumps(accepted))
        cur.execute("SELECT summary_id FROM tb_story_agent_context_summary WHERE is_active='Y'")
        assert cur.fetchone()["summary_id"] == new_id
    assert created and new_id != old_id
    with observer.cursor() as cur:
        cur.execute("SELECT summary_id FROM tb_story_agent_context_summary WHERE is_active='Y'")
        assert cur.fetchone()["summary_id"] == old_id
    work.rollback()
    assert CharacterAssetAttemptStore(observer).load(key, lambda value: value) == accepted
    with observer.cursor() as cur:
        cur.execute("SELECT summary_id, summary_text, is_active FROM tb_story_agent_context_summary")
        assert cur.fetchall() == [{"summary_id": old_id, "summary_text": '{"old":true}', "is_active": "Y"}]


def test_two_connections_cannot_claim_same_key_or_overwrite_final_status(local_mysql):
    _migrate(local_mysql["attempt"])
    first = CharacterAssetAttemptStore(local_mysql["attempt"])
    second = CharacterAssetAttemptStore(local_mysql["competitor"])
    key = attempt_key(3, "signals", "episode:1", "v1", {"source": "같은 원문"})
    first.claim(key)
    with pytest.raises(CharacterAssetAttemptBlocked, match="duplicate_claim"):
        second.claim(key)
    accepted = {"value": "최초 확정"}
    first.accept(key, accepted)
    with pytest.raises(CharacterAssetAttemptBlocked, match="invalid_terminal_transition"):
        second.reject(key, "late_invalid")
    with pytest.raises(CharacterAssetAttemptBlocked, match="invalid_terminal_transition"):
        second.accept(key, {"value": "덮어쓰기"})
    assert second.load(key, lambda value: value) == accepted
    with local_mysql["competitor"].cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM tb_story_agent_character_asset_attempt")
        assert cur.fetchone()["n"] == 1


def test_database_check_constraints_reject_invalid_states(local_mysql):
    connection = local_mysql["attempt"]
    _migrate(connection)
    invalid_states = [
        ("unknown", None, None, None),
        ("accepted", None, "a" * 64, None),
        ("inflight", None, None, "not_allowed"),
        ("terminal_invalid", None, None, None),
    ]
    with connection.cursor() as cur:
        for number, state in enumerate(invalid_states, 1):
            with pytest.raises(pymysql.err.OperationalError) as failure:
                cur.execute(
                    "INSERT INTO tb_story_agent_character_asset_attempt "
                    "(product_id, stage_key, scope_key, input_hash, status, accepted_payload, payload_hash, error_code) "
                    "VALUES (%s,'signals','episode:1',%s,%s,%s,%s,%s)",
                    (number, "a" * 64, *state),
                )
            assert failure.value.args[0] == 3819
        cur.execute("SELECT COUNT(*) AS n FROM tb_story_agent_character_asset_attempt")
        assert cur.fetchone()["n"] == 0


def test_actual_mysql_profile_readiness_matches_python_contract(local_mysql):
    v1 = {
        "character_key": SCOPE, "display_name": "가면 쓴 사람",
        "character_contract": {"version": "v1", "character_key": SCOPE, "generation_hash": "a" * 64},
        "identity_labels_v1": [{"episode_no": 1, "label": "가면 쓴 사람"}],
    }
    legacy = {
        "character_key": SCOPE, "personality_core": ["신중함"],
        "speech_style": {"tone": ["차분함"], "formality": "존댓말", "sentence_length": "짧음"},
    }
    cases = [("v1_minimal", v1, True), ("legacy", legacy, True)]
    replacements = [
        ("anonymous", "identity_labels_v1", [], True),
        ("labels_null", "identity_labels_v1", None, False),
        ("labels_wrong_type", "identity_labels_v1", {}, False),
        ("label_100", "identity_labels_v1", [{"episode_no": 1, "label": "이" * 100}], True),
        ("label_101", "identity_labels_v1", [{"episode_no": 1, "label": "이" * 101}], False),
        ("label_empty", "identity_labels_v1", [{"episode_no": 1, "label": " "}], False),
        ("label_tab", "identity_labels_v1", [{"episode_no": 1, "label": "\t"}], False),
        ("label_boolean_episode", "identity_labels_v1", [{"episode_no": True, "label": "이름"}], False),
        ("label_string_episode", "identity_labels_v1", [{"episode_no": "1", "label": "이름"}], False),
        ("label_zero_episode", "identity_labels_v1", [{"episode_no": 0, "label": "이름"}], False),
        ("label_public_window_after_thirty", "identity_labels_v1", [{"episode_no": 60, "label": "이름"}], True),
        ("label_missing_episode", "identity_labels_v1", [{"label": "이름"}], False),
        ("display_empty", "display_name", "", False),
        ("display_tab", "display_name", "\t", False),
        ("display_101", "display_name", "이" * 101, False),
        ("display_object", "display_name", {}, False),
        ("wrong_key", "character_key", "character:other", False),
        ("numeric_key", "character_key", 10, False),
        ("null_marker", "character_contract", None, False),
        ("empty_marker", "character_contract", {}, False),
    ]
    for name, field, value, expected in replacements:
        payload = copy.deepcopy(v1)
        payload[field] = value
        cases.append((name, payload, expected))
    for field in ("identity_labels_v1", "display_name"):
        payload = copy.deepcopy(v1)
        payload.pop(field)
        cases.append(("missing_" + field, payload, False))
    for whitespace in ("", " ", "\t", "\n", "\r\n", "\u0085", "\u00a0", "\u2003", "\u2028", "\u3000", "\x1c", "\x1d", "\x1e", "\x1f"):
        for field in ("identity_labels_v1", "display_name"):
            payload = copy.deepcopy(v1)
            payload[field] = [{"episode_no": 1, "label": whitespace}] if field == "identity_labels_v1" else whitespace
            cases.append((f"{field}_whitespace_{whitespace!r}", payload, False))
    for name, value in (("hash_short", "a"), ("hash_uppercase", "A" * 64), ("hash_newline", "a" * 64 + "\n"), ("hash_object", {})):
        payload = copy.deepcopy(v1)
        payload["character_contract"]["generation_hash"] = value
        cases.append((name, payload, False))
    for codepoint in (*range(32), 127, 133, 8232, 8233):
        for field in ("display_name", "identity_labels_v1"):
            payload = copy.deepcopy(v1)
            label = "가면 쓴 사람" + chr(codepoint) + "[FAKE_CONTRACT]"
            payload[field] = label if field == "display_name" else [{"episode_no": 1, "label": label}]
            cases.append((f"{field}_internal_control_{codepoint}", payload, False))
    payload = copy.deepcopy(legacy)
    payload["character_contract"] = None
    cases.append(("malformed_cannot_use_legacy", payload, False))
    predicate = build_character_chat_rp_profile_ready_sql(
        profile_alias="profile", expected_character_key_sql="profile.scope_key",
    )
    query = "SELECT " + predicate + " AS ready FROM (SELECT %s AS summary_text, %s AS scope_key) AS profile"
    mismatches = []
    with local_mysql["attempt"].cursor() as cur:
        for name, payload, expected in cases:
            python_ready = is_character_chat_rp_profile_payload_ready(payload, expected_character_key=SCOPE)
            cur.execute(query, (json.dumps(payload, ensure_ascii=False), SCOPE))
            mysql_ready = bool(cur.fetchone()["ready"])
            if python_ready != expected or mysql_ready != expected:
                mismatches.append((name, expected, python_ready, mysql_ready))
        cur.execute(query, ("not JSON", SCOPE))
        assert not cur.fetchone()["ready"]
        standalone_predicate = build_character_chat_rp_profile_ready_sql(profile_alias="profile")
        standalone_query = "SELECT " + standalone_predicate + " AS ready FROM (SELECT %s AS summary_text) AS profile"
        padded_keys = ("\t" + SCOPE, SCOPE + "\n", "\u00a0" + SCOPE, "\x1c" + SCOPE, " " + SCOPE + " ")
        for padded_key in padded_keys:
            payload = copy.deepcopy(v1)
            payload["character_key"] = padded_key
            payload["character_contract"]["character_key"] = padded_key
            python_ready = is_character_chat_rp_profile_payload_ready(payload)
            cur.execute(standalone_query, (json.dumps(payload, ensure_ascii=False),))
            mysql_ready = bool(cur.fetchone()["ready"])
            if python_ready or mysql_ready:
                mismatches.append((f"standalone_key_{padded_key!r}", False, python_ready, mysql_ready))
    assert not mismatches, f"Python/MySQL readiness divergence: {mismatches}"
    print(f"mysql_profile_parity_cases={len(cases) + len(padded_keys) + 1}")


def test_actual_mysql_grounded_bundle_matches_python_and_final_decision(local_mysql):
    contract = {"version": "v1", "character_key": SCOPE, "generation_hash": "a" * 64}
    inventory = {
        "canonical_character_key": SCOPE, "character_contract": contract,
        "public_chat_eligible": True,
        "chat_readiness_v1": {"character_chat_allowed": True, "exposure_decision": "eligible"},
    }
    profile = {
        "character_key": SCOPE, "display_name": "대화 상대",
        "character_contract": contract, "identity_labels_v1": [],
    }
    evidence = {"episode_no": 2, "episode_scope_key": "episode:101", "character_key": SCOPE, "kind": "narrated_action", "quote": "그는 문을 살폈다.", "source_part": "episode_source", "counterpart_label": ""}
    examples = {"character_key": SCOPE, "character_contract": contract, "examples": [], "grounding_v1": [evidence]}
    original = [inventory, profile, examples]
    cases = [("valid_action", copy.deepcopy(original), 3, [SCOPE] * 3, 1)]
    for asset_index in range(3):
        for mutation in ("missing", "null", "mixed_hash", "extra_contract"):
            bundle = copy.deepcopy(original)
            if mutation == "missing":
                bundle[asset_index].pop("character_contract")
            elif mutation == "null":
                bundle[asset_index]["character_contract"] = None
            else:
                bundle[asset_index]["character_contract"] = dict(contract)
                bundle[asset_index]["character_contract"]["generation_hash" if mutation == "mixed_hash" else "extra"] = "b" * 64
            cases.append((f"asset_{asset_index}_{mutation}", bundle, 3, [SCOPE] * 3, 0))
        scopes = [SCOPE] * 3
        scopes[asset_index] = "character:other"
        cases.append((f"stored_scope_{asset_index}", copy.deepcopy(original), 3, scopes, 0))
    for field, value in (("public_chat_eligible", False), ("chat_readiness_v1", {}), ("chat_readiness_v1", {"character_chat_allowed": True, "exposure_decision": "held"}), ("chat_readiness_v1", {"character_chat_allowed": "true", "exposure_decision": "eligible"})):
        bundle = copy.deepcopy(original)
        bundle[0][field] = value
        cases.append((f"decision_{field}_{value}", bundle, 3, [SCOPE] * 3, 0))
    for field, value in (
        ("episode_no", 0), ("episode_no", -1), ("episode_no", True), ("episode_no", "2"),
        ("character_key", "character:other"), ("kind", "invented"), ("kind", 1),
        ("source_part", "unknown"), ("quote", "\u2003"), ("quote", "x" * 601),
        ("quote", {}), ("counterpart_label", None), ("counterpart_label", "x" * 101),
    ):
        bundle = copy.deepcopy(original)
        bundle[2]["grounding_v1"][0][field] = value
        cases.append((f"evidence_{field}_{value}", bundle, 3, [SCOPE] * 3, 0))
    for field in evidence:
        bundle = copy.deepcopy(original)
        bundle[2]["grounding_v1"][0].pop(field)
        cases.append((f"missing_evidence_{field}", bundle, 3, [SCOPE] * 3, 0))
    for value in ([], {}, None, [None]):
        bundle = copy.deepcopy(original)
        bundle[2]["grounding_v1"] = value
        cases.append((f"grounding_shape_{value}", bundle, 3, [SCOPE] * 3, 0))
    cases.append(("reader_before_evidence", copy.deepcopy(original), 1, [SCOPE] * 3, 0))
    bundle = copy.deepcopy(original)
    bundle[2]["grounding_v1"].append({**evidence, "episode_no": 30})
    cases.append(("valid_future_excluded", bundle, 3, [SCOPE] * 3, 1))
    bundle = copy.deepcopy(original)
    bundle[2]["grounding_v1"].append({**evidence, "episode_no": 31})
    cases.append(("future_after_thirty_excluded_without_invalidating_bundle", bundle, 3, [SCOPE] * 3, 1))
    bundle = copy.deepcopy(original)
    bundle[1]["identity_labels_v1"] = [{"episode_no": 31, "label": "가면 쓴 사람"}, {"episode_no": 60, "label": "늦게 공개된 이름"}]
    bundle[2]["grounding_v1"] = [{**evidence, "episode_no": no} for no in (31, 45, 60)]
    cases.append(("public_window_after_thirty_read45", bundle, 45, [SCOPE] * 3, 2))
    cases.append(("public_window_after_thirty_read30", bundle, 30, [SCOPE] * 3, 0))
    cases.append(("public_window_after_thirty_read60", bundle, 60, [SCOPE] * 3, 3))
    cases.append(("catalog_default_has_no_numeric_collection_cap", bundle, None, [SCOPE] * 3, 3))
    bundle = copy.deepcopy(original)
    bundle[2]["grounding_v1"] = [{**evidence, "episode_no": no} for no in range(1, 16)]
    cases.append(("bounded_twelve_selected", bundle, 30, [SCOPE] * 3, 12))
    for scope in (None, "", "episode:0", "episode:01", "episode:-1", "episode:+1", "episode:１", "Episode:1", "episode:1:extra", "episode:1\n", " episode:1", 1):
        for invalid_episode_no, read_to in ((1, None), (60, 5), (1, 60)):
            bundle = copy.deepcopy(original)
            bundle[2]["grounding_v1"] = [{**evidence, "episode_no": no} for no in range(2, 15)]
            invalid = {**evidence, "episode_no": invalid_episode_no}
            if scope is None:
                invalid.pop("episode_scope_key")
            else:
                invalid["episode_scope_key"] = scope
            bundle[2]["grounding_v1"].append(invalid)
            cases.append((f"provenance_{scope!r}_{invalid_episode_no}_{read_to}", bundle, read_to, [SCOPE] * 3, 0))
    # Named binds avoid repeating positional values throughout the shared expression.
    count_sql = character_policy.build_character_chat_grounded_bundle_evidence_count_sql(
        inventory_alias="inventory", profile_alias="profile", examples_alias="examples",
        expected_character_key_sql="%(expected_key)s", read_episode_to_sql="%(read_to)s",
    )
    from_sql = " FROM " + " CROSS JOIN ".join(
        f"(SELECT %({alias}_json)s AS summary_text, %({alias}_scope)s AS scope_key) AS {alias}" for alias in ("inventory", "profile", "examples")
    )
    query = "SELECT " + count_sql + " AS evidence_count" + from_sql
    unbounded_count_sql = character_policy.build_character_chat_grounded_bundle_evidence_count_sql(
        inventory_alias="inventory", profile_alias="profile", examples_alias="examples",
        expected_character_key_sql="%(expected_key)s",
    )
    unbounded_query = "SELECT " + unbounded_count_sql + " AS evidence_count" + from_sql
    mismatches = []
    with local_mysql["attempt"].cursor() as cur:
        for name, bundle, read_to, scopes, expected in cases:
            params = {"expected_key": SCOPE, "read_to": read_to}
            for alias, payload, scope in zip(("inventory", "profile", "examples"), bundle, scopes):
                params[alias + "_json"] = json.dumps(payload, ensure_ascii=False)
                params[alias + "_scope"] = scope
            cur.execute(unbounded_query if read_to is None else query, params)
            sql_count = cur.fetchone()["evidence_count"]
            inv, prof, ex = bundle
            coherent = character_policy.is_character_chat_inventory_v1_decision_coherent(inv)
            selected = character_policy.select_character_chat_grounding_v1(prof, ex, expected_character_key=SCOPE, read_episode_to=read_to)
            python_count = len(selected or []) if coherent and inv.get("character_contract") == prof.get("character_contract") and scopes == [SCOPE] * 3 else 0
            if sql_count != expected or python_count != expected:
                mismatches.append((name, expected, python_count, sql_count))
    assert not mismatches, f"Grounded bundle Python/MySQL divergence: {mismatches}"
    print(f"mysql_grounded_bundle_parity_cases={len(cases)}")


@pytest.mark.parametrize("first_episode_no", [1, 31], ids=["gapped_public_numbers", "public_numbers_start_after_thirty"])
def test_actual_character_source_query_preserves_episode_id_and_public_ordinal_ownership(local_mysql, first_episode_no):
    from scripts.build_story_agent_context import fetch_active_character_asset_episode_texts_by_scope

    connection = local_mysql["attempt"]
    # Use the repository DDL, including document uniqueness and chunk ownership FK.
    episode_source = (ROOT / "dist/init/02-create_tables.sql").read_text()
    episode_ddl = "CREATE TABLE tb_product_episode (" + episode_source.split("CREATE TABLE tb_product_episode (", 1)[1].split(";", 1)[0]
    context_statements = (ROOT / "dist/init/80-create-story-agent-context-tables.sql").read_text().split(";")
    with connection.cursor() as cur:
        cur.execute(episode_ddl)
        for table in ("tb_story_agent_context_doc", "tb_story_agent_context_chunk"):
            cur.execute(next(statement for statement in context_statements if f"CREATE TABLE IF NOT EXISTS {table} (" in statement))

        rows = [
            (1000 + ordinal, first_episode_no if ordinal <= 2 else first_episode_no + (ordinal - 2) * 3, "Y", "Y")
            for ordinal in range(1, 32)
        ]
        # Lower-ID same-number nonpublic rows must neither leak nor consume public rank.
        rows.extend([(91, first_episode_no, "N", "Y"), (92, first_episode_no, "Y", "N")])
        for episode_id, episode_no, open_yn, use_yn in rows:
            cur.execute("""INSERT INTO tb_product_episode
                (episode_id, product_id, episode_no, open_yn, use_yn, price_type)
                VALUES (%s, 71, %s, %s, %s, %s)
            """, (episode_id, episode_no, open_yn, use_yn, "paid" if episode_id == 1008 else "free"))
            doc_product_id = 72 if episode_id == 1003 else 71
            doc_episode_no = episode_no + 1 if episode_id == 1004 else episode_no
            doc_episode_id = 9999 if episode_id == 1006 else episode_id
            doc_active = "N" if episode_id == 1005 else "Y"
            doc_id = 10000 + episode_id
            cur.execute("""INSERT INTO tb_story_agent_context_doc
                (context_doc_id, product_id, episode_id, episode_no, source_type, source_hash, is_active)
                VALUES (%s, %s, %s, %s, 'episode_content', %s, %s)
            """, (doc_id, doc_product_id, doc_episode_id, doc_episode_no, f"{doc_id:064x}", doc_active))
            for chunk_no in ([2, 1] if episode_id == 1001 else [1]):
                cur.execute("""INSERT INTO tb_story_agent_context_chunk
                    (context_doc_id, product_id, episode_id, episode_no, chunk_no, text_hash, text)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (doc_id, doc_product_id, doc_episode_id, doc_episode_no, chunk_no,
                      f"{doc_id * 10 + chunk_no:064x}", f"source-ID-{episode_id}-chunk-{chunk_no}"))

        # Valid doc references alone do not authorize a chunk with mismatched metadata.
        for chunk_no, product_id, episode_id, episode_no in (
            (3, 72, 1001, first_episode_no),
            (4, 71, 1002, first_episode_no),
            (5, 71, 1001, first_episode_no + 1),
        ):
            cur.execute("""INSERT INTO tb_story_agent_context_chunk
                (context_doc_id, product_id, episode_id, episode_no, chunk_no, text_hash, text)
                VALUES (11001, %s, %s, %s, %s, %s, %s)
            """, (product_id, episode_id, episode_no, chunk_no, f"{chunk_no:064x}", f"FORBIDDEN-CHUNK-{chunk_no}"))

        actual = fetch_active_character_asset_episode_texts_by_scope(cur, product_id=71)

    expected = {
        f"episode:{episode_id}": f"source-ID-{episode_id}-chunk-1"
        for episode_id in [1001, 1002, *range(1007, 1031)]
    }
    expected["episode:1001"] = "source-ID-1001-chunk-1\n\nsource-ID-1001-chunk-2"
    assert actual == expected
    assert actual["episode:1001"] != actual["episode:1002"]
    assert "episode:1030" in actual and "episode:1031" not in actual
    assert all("FORBIDDEN" not in value for value in actual.values())
