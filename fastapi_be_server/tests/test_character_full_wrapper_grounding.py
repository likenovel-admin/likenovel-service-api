"""Execute the wrapper's repair predicate and delta candidate SQL on local MySQL."""
import copy
import json
import subprocess

import pytest

from tests.test_character_asset_mysql import ROOT, SCOPE, local_mysql, pytestmark
from tests.test_story_agent_context_batch_sql import _batch_sh, _run_full_wrapper


def _candidate_sql(build_mode="full"):
    query = _batch_sh().split('if ! CANDIDATE_OUTPUT="$("${MYSQL_CMD[@]}" <<SQL\n', 1)[1].split('\nSQL\n', 1)[0]
    values = {
        "BUILD_MODE": build_mode, "CHAT_ASSET_TARGET_EPISODES": "30",
        "CHAT_ASSET_PRIORITY_HEADROOM_USD": "1.00", "CHAT_ASSET_SURPLUS_HEADROOM_USD": "2.00",
        "REVIEW_REQUIRED_PRODUCT_IDS_SQL": "0", "SCHEDULED_BLOCKED_IDS_SQL": "0",
        "SCHEDULED_REPAIR_IDS_SQL": "0", "BACKLOG_PRIORITY_THRESHOLD": "20", "MAX_PARALLEL": "1",
    }
    return subprocess.run(
        ["bash", "-c", "cat <<SQL\n" + query + "\nSQL\n"],
        env=values, capture_output=True, text=True, check=True,
    ).stdout


def _full_repair_sql():
    # Execute the shipped full-only repair predicate, including its scene clause.
    predicate = _batch_sh().split("CASE WHEN collection_cohort.product_id IS NULL THEN 0 ELSE (", 1)[1]
    predicate = predicate.split(") END\n    END AS character_asset_repair_needed", 1)[0]
    return "SELECT (" + predicate + ") AS repair_needed FROM tb_product p WHERE p.product_id=1"


def _ready_context(connection, *, episode_nos=range(1, 16)):
    """Canonical context tables plus the exact columns read from unrelated tables."""
    with connection.cursor() as cur:
        for statement in (ROOT / "dist/init/80-create-story-agent-context-tables.sql").read_text().split(";"):
            if any("CREATE TABLE IF NOT EXISTS " + table + " (" in statement for table in (
                "tb_story_agent_context_product", "tb_story_agent_context_summary",
            )):
                cur.execute(statement)
        cur.execute("CREATE TABLE tb_product (product_id BIGINT PRIMARY KEY, title VARCHAR(100), "
                    "price_type VARCHAR(20), status_code VARCHAR(20), open_yn CHAR(1), "
                    "blind_yn CHAR(1), ai_content_service_enabled_yn CHAR(1))")
        cur.execute("CREATE TABLE tb_product_episode (episode_id BIGINT PRIMARY KEY, product_id BIGINT, "
                    "episode_no INT, use_yn CHAR(1), open_yn CHAR(1), open_changed_date DATETIME, "
                    "publish_reserve_date DATETIME, created_date DATETIME)")
        cur.execute("CREATE TABLE tb_user_ai_signal_event (product_id BIGINT, episode_id BIGINT, "
                    "event_type VARCHAR(50), created_date DATETIME)")
        cur.execute("INSERT INTO tb_product VALUES (1,'Synthetic title','free','ongoing','Y','N','Y')")
        cur.execute("INSERT INTO tb_story_agent_context_product "
                    "(product_id,context_status,total_episode_count,ready_episode_count) VALUES (1,'ready',15,15)")
        for episode in episode_nos:
            cur.execute("INSERT INTO tb_product_episode VALUES (%s,1,%s,'Y','Y','2026-04-01',NULL,'2026-04-01')",
                        (episode, episode))
            for kind, payload in (
                ("episode_summary", {}), ("episode_character_signals", {}),
                ("episode_scene_extraction", {"status": "ok", "scene_count": 1,
                    "scenes": [{"scene_gist": "출구를 살핀다.", "participants": [{"scope_key": SCOPE}]}]}),
            ):
                _insert_summary(cur, kind, payload, scope=f"episode:{episode}")
        _insert_summary(cur, "character_inventory", {})


def _insert_summary(cur, kind, payload, *, scope=SCOPE):
    cur.execute("INSERT INTO tb_story_agent_context_summary "
                "(product_id,summary_type,scope_key,source_hash,summary_text) VALUES (1,%s,%s,%s,%s)",
                (kind, scope, "a" * 64, json.dumps(payload, ensure_ascii=False)))


def _v1_bundle():
    marker = {"version": "v1", "character_key": SCOPE, "generation_hash": "a" * 64}
    inventory = {"public_chat_eligible": True, "character_contract": copy.deepcopy(marker)}
    profile = {"character_key": SCOPE, "display_name": "검증 인물", "identity_labels_v1": [],
               "character_contract": copy.deepcopy(marker)}
    examples = {"character_key": SCOPE, "examples": [], "grounding_v1": [{"episode_no": 1}],
                "character_contract": copy.deepcopy(marker)}
    return [inventory, profile, examples]


def _bundle_cases():
    bundle = _v1_bundle()
    cases = [pytest.param(bundle, False, id="valid_v1_empty_legacy_examples")]
    for index, owner in enumerate(("inventory", "profile", "examples")):
        for field, value in (
            ("version", "v2"), ("version", "V1"), ("character_key", "character:other"),
            ("generation_hash", "b" * 64), ("generation_hash", "A" * 64),
            ("generation_hash", "a" * 64 + "\n"), ("generation_hash", None),
        ):
            changed = copy.deepcopy(bundle)
            changed[index]["character_contract"][field] = value
            cases.append(pytest.param(changed, True, id=f"{owner}_{field}_{value!r}"))
        for marker_value in (None, {}, [], "v1", "absent"):
            changed = copy.deepcopy(bundle)
            changed[2]["examples"] = [{"text": "레거시 대사"}]
            if marker_value == "absent":
                changed[index].pop("character_contract")
            else:
                changed[index]["character_contract"] = marker_value
            cases.append(pytest.param(changed, True, id=f"{owner}_marker_{marker_value!r}"))
    for index, field, value in (
        (1, "character_key", "character:other"), (2, "character_key", "character:other"),
        (1, "display_name", ""), (1, "display_name", " \t\n"), (1, "display_name", {}),
        (1, "identity_labels_v1", None), (1, "identity_labels_v1", {}),
        (2, "grounding_v1", []), (2, "grounding_v1", None), (2, "grounding_v1", {}),
    ):
        changed = copy.deepcopy(bundle)
        changed[index][field] = value
        cases.append(pytest.param(changed, True, id=f"payload_{index}_{field}_{value!r}"))
    for index, field in ((1, "display_name"), (1, "identity_labels_v1"), (2, "grounding_v1")):
        changed = copy.deepcopy(bundle)
        changed[index].pop(field)
        cases.append(pytest.param(changed, True, id=f"missing_{field}"))
    legacy = copy.deepcopy(bundle)
    for payload in legacy:
        payload.pop("character_contract")
    legacy[1] = {"character_key": SCOPE}
    legacy[2] = {"character_key": SCOPE, "examples": [{"text": "기존 대사"}]}
    cases.append(pytest.param(legacy, False, id="valid_unmarked_legacy"))
    for values in ([], [{"text": ""}], [{"text": " \t\n"}]):
        changed = copy.deepcopy(legacy)
        changed[2]["examples"] = values
        cases.append(pytest.param(changed, True, id=f"empty_legacy_{values!r}"))
    for marker_value in (None, {}, []):
        changed = copy.deepcopy(legacy)
        for payload in changed:
            payload["character_contract"] = marker_value
        cases.append(pytest.param(changed, True, id=f"all_malformed_markers_{marker_value!r}"))
    return cases


@pytest.mark.parametrize("bundle,repair_needed", _bundle_cases())
def test_full_candidate_sql_generation_pair_and_child_boundary(local_mysql, bundle, repair_needed):
    connection = local_mysql["attempt"]
    _ready_context(connection)
    with connection.cursor() as cur:
        for kind, payload in zip(("character_inventory_v3", "character_rp_profile", "character_rp_examples"),
                                 bundle):
            _insert_summary(cur, kind, payload)
        cur.execute(_full_repair_sql())
        assert cur.fetchone()["repair_needed"] == int(repair_needed)
        cur.execute(_candidate_sql())
        rows = cur.fetchall()
        assert bool(rows) == repair_needed
    candidate_output = "".join("\t".join(str(value) for value in row.values()) + "\n" for row in rows)
    result, args, log = _run_full_wrapper(candidate_output)
    assert result.returncode == 0, result.stderr
    if repair_needed:
        assert args[1:] == ["--product-id", "1", "--build-mode", "full",
                           "--max-delta-episodes", "5", "--apply", "--verbose"]
    else:
        assert args == []
        assert "[batch-empty] no eligible products" in log


def test_episode_gap_includes_30th_public_row_but_excludes_31st_asset_row(local_mysql):
    connection = local_mysql["attempt"]
    _ready_context(connection, episode_nos=(*range(1, 27), 28, 29, 30, 31, 32))
    with connection.cursor() as cur:
        _insert_summary(cur, "character_inventory_v3", {})
        cur.execute("DELETE FROM tb_story_agent_context_summary WHERE scope_key='episode:32'")
        cur.execute(_candidate_sql("delta"))
        assert not cur.fetchall(), "the 31st public row is outside delta collection"
        cur.execute(_candidate_sql("full"))
        assert len(cur.fetchall()) == 1, "full still collects ordinary summaries beyond 30 public rows"
        _insert_summary(cur, "episode_summary", {}, scope="episode:32")
        cur.execute(_candidate_sql("full"))
        assert not cur.fetchall(), "the 31st public row's signals/scenes must not trigger asset work"
        cur.execute("DELETE FROM tb_story_agent_context_summary "
                    "WHERE scope_key='episode:31' AND summary_type='episode_character_signals'")
        for mode in ("delta", "full"):
            cur.execute(_candidate_sql(mode))
            rows = cur.fetchall()
            assert len(rows) == 1, "episode 31 is the 30th public row when episode 27 is absent"
            assert rows[0]["inventory_reaggregation_needed"] == 1


@pytest.mark.parametrize("has_actor,repair_needed", [(False, True), (True, False)])
def test_full_v1_pair_still_requires_scene_participant_or_actor(local_mysql, has_actor, repair_needed):
    connection = local_mysql["attempt"]
    _ready_context(connection)
    with connection.cursor() as cur:
        for kind, payload in zip(("character_inventory_v3", "character_rp_profile", "character_rp_examples"),
                                 _v1_bundle()):
            _insert_summary(cur, kind, payload)
        scene = {"status": "ok", "scene_count": 1, "scenes": [{
            "scene_gist": "출구를 살핀다.", "participants": [],
            "action_ownership": [{"actor_scope_key": SCOPE}] if has_actor else [],
        }]}
        cur.execute("UPDATE tb_story_agent_context_summary SET summary_text=%s "
                    "WHERE summary_type='episode_scene_extraction'", (json.dumps(scene),))
        cur.execute(_candidate_sql())
        rows = cur.fetchall()
        assert bool(rows) == repair_needed
        if repair_needed:
            assert rows[0]["character_asset_repair_needed"] == 1
