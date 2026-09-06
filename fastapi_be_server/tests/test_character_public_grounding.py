"""Opt-in public-consumer regressions; eligibility flags are input, not producer proof."""
import copy
import asyncio
import hashlib
import json

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.mysql import pymysql

from app.services.product import main_character_slot_service as catalog
from app.exceptions import CustomResponseException
from scripts.build_story_agent_context import (
    build_usable_character_scene_episodes_by_scope,
    fetch_active_character_asset_summary_rows,
    fetch_character_chat_catalog_scene_episode_scope_map,
    upsert_summary,
)
from tests.test_character_asset_mysql import _summary_table, local_mysql, pytestmark


PRODUCT_ID = 71
SCOPE = "character:public-test"
QUOTE = "그는 말없이 출구를 살폈다."


def _assets(*, legacy=False, example_count=0, alias=False):
    asset_key = "character:old-name" if alias else SCOPE
    inventory = {
        "canonical_character_key": SCOPE,
        "display_name": "대화 상대",
        "display_safety": {"status": "pass"},
        "public_chat_eligible": True,
        "public_slot_eligible": True,
        "work_role": "main_protagonist",
        "distinct_episode_count": 10,
        "source_character_keys": [asset_key] if alias else [],
    }
    profile = {"character_key": asset_key, "display_name": "대화 상대"}
    examples = {
        "character_key": asset_key,
        "examples": [{"text": QUOTE, "episode_no": 1} for _ in range(example_count)],
    }
    if legacy:
        profile.update({
            "personality_core": ["신중함"],
            "speech_style": {"tone": ["차분함"], "formality": "존댓말", "sentence_length": "짧음"},
        })
    else:
        inventory["chat_readiness_v1"] = {
            "character_chat_allowed": True, "public_slot_allowed": True,
            "exposure_decision": "eligible",
        }
        contract = {"version": "v1", "generation_hash": "a" * 64, "character_key": asset_key}
        for payload in (inventory, profile, examples):
            payload["character_contract"] = copy.deepcopy(contract)
        profile["identity_labels_v1"] = []
        examples["grounding_v1"] = [{
            "episode_no": 1, "episode_scope_key": "episode:1", "character_key": asset_key,
            "kind": "narrated_action", "quote": QUOTE,
            "source_part": "episode_source", "counterpart_label": "",
        }]
    return inventory, profile, examples


def _seed(connection, assets):
    _summary_table(connection)
    with connection.cursor() as cur:
        for summary_type, payload in zip(
            ("character_inventory_v3", "character_rp_profile", "character_rp_examples"), assets
        ):
            encoded = json.dumps(payload, ensure_ascii=False)
            upsert_summary(
                cur, product_id=PRODUCT_ID, summary_type=summary_type,
                scope_key=SCOPE if summary_type == "character_inventory_v3" else payload["character_key"],
                source_hash=hashlib.sha256(encoded.encode()).hexdigest(),
                source_doc_count=(
                    len({entry["episode_no"] for entry in payload["grounding_v1"]})
                    if "grounding_v1" in payload
                    else len(payload["examples"]) if summary_type == "character_rp_examples" else 10
                ),
                summary_text=encoded, episode_from=1, episode_to=10,
            )


def _query(connection, selector):
    if selector == "slot":
        sql = """
            SELECT inventory.product_id AS productId,
                   inventory.scope_key AS characterScopeKey
            FROM tb_story_agent_context_summary inventory
            WHERE inventory.product_id IN :product_ids
              AND inventory.summary_type = 'character_inventory_v3'
              AND inventory.is_active = 'Y'
        """ + catalog._chat_ready_rp_assets_predicate("inventory")
    elif selector == "exact":
        sql = catalog.build_public_character_catalog_assets_query()
    else:
        sql = catalog.build_public_character_catalog_alias_fallback_query()
    statement = text(sql).bindparams(bindparam("product_ids", expanding=True))
    compiled = statement.params(product_ids=[PRODUCT_ID]).compile(
        dialect=pymysql.dialect(paramstyle="pyformat"), compile_kwargs={"render_postcompile": True}
    )
    with connection.cursor() as cur:
        cur.execute(str(compiled), compiled.params)
        return list(cur.fetchall())


def _context():
    products = [{"productId": PRODUCT_ID, "productTitle": "검증 작품", "_latestPublicEpisodeNo": 10, "_chatTotalEpisodeCount": 10}]
    readiness = [{"productId": PRODUCT_ID, "_chatReadyEpisodeCount": 10, "_continuousReadyEpisodeNo": 10}]
    return products, readiness


class _MySQLSession:
    """Execute the application's SQL unchanged on the guarded test connection."""

    def __init__(self, connection):
        self.connection = connection

    async def execute(self, statement, parameters=None):
        compiled = statement.params(**(parameters or {})).compile(
            dialect=pymysql.dialect(paramstyle="pyformat"),
            compile_kwargs={"render_postcompile": True},
        )
        with self.connection.cursor() as cur:
            cur.execute(str(compiled), compiled.params)
            rows = list(cur.fetchall())

        class Result:
            def mappings(self):
                return self

            def all(self):
                return rows

            def one_or_none(self):
                assert len(rows) <= 1
                return rows[0] if rows else None

        return Result()


def _seed_consumer_context(connection, *, scene_count=5, first_episode_no=1, episode_count=15):
    # Only columns consumed by the real queries; all tables live in the guarded schema.
    with connection.cursor() as cur:
        cur.execute("""CREATE TABLE tb_product (
            product_id BIGINT PRIMARY KEY, open_yn CHAR(1), blind_yn CHAR(1),
            ai_content_service_enabled_yn CHAR(1), status_code VARCHAR(30))""")
        cur.execute("INSERT INTO tb_product VALUES (%s, 'Y', 'N', 'Y', 'ongoing')", (PRODUCT_ID,))
        cur.execute("""CREATE TABLE tb_product_episode (
            episode_id BIGINT PRIMARY KEY, product_id BIGINT, episode_no INT,
            episode_title VARCHAR(100), use_yn CHAR(1), open_yn CHAR(1), price_type VARCHAR(10),
            open_changed_date DATETIME, publish_reserve_date DATETIME, created_date DATETIME)""")
        cur.execute("""CREATE TABLE tb_story_agent_context_doc (
            context_doc_id BIGINT PRIMARY KEY, is_active CHAR(1))""")
        cur.execute("""CREATE TABLE tb_story_agent_context_chunk (
            context_doc_id BIGINT, product_id BIGINT, episode_id BIGINT,
            char_start INT, char_end INT, chunk_no INT, text TEXT)""")
        for public_ordinal, episode_no in enumerate(range(first_episode_no, first_episode_no + episode_count), start=1):
            cur.execute("""INSERT INTO tb_product_episode VALUES
                (%s, %s, %s, '검증 회차', 'Y', 'Y', 'free', '2026-09-01', NULL, '2026-09-01')
            """, (episode_no, PRODUCT_ID, episode_no))
            for summary_type, payload in [
                ("episode_summary", {"summary": "그가 출구를 살피는 장면이다."}),
                *([("episode_scene_extraction", {
                    "status": "ok", "episode_no": episode_no, "scenes": [{
                        "scene_index": 1, "scene_gist": "출구를 살핀다.",
                        "char_start": 0, "char_end": len(QUOTE),
                        "participants": [{"scope_key": SCOPE}], "action_ownership": [],
                    }],
                })] if public_ordinal <= scene_count else []),
            ]:
                encoded = json.dumps(payload, ensure_ascii=False)
                upsert_summary(
                    cur, product_id=PRODUCT_ID, summary_type=summary_type,
                    scope_key=f"episode:{episode_no}",
                    source_hash=hashlib.sha256(encoded.encode()).hexdigest(),
                    source_doc_count=1, summary_text=encoded,
                    episode_from=episode_no, episode_to=episode_no,
                )
            cur.execute("INSERT INTO tb_story_agent_context_doc VALUES (%s, 'Y')", (episode_no,))
            cur.execute("INSERT INTO tb_story_agent_context_chunk VALUES (%s, %s, %s, 0, %s, 1, %s)",
                        (episode_no, PRODUCT_ID, episode_no, len(QUOTE), QUOTE))


@pytest.mark.parametrize("selector", ["slot", "exact", "alias"])
def test_grounded_action_without_dialogue_is_a_public_asset(local_mysql, selector):
    connection = local_mysql["attempt"]
    _seed(connection, _assets())
    rows = _query(connection, selector)
    assert [row["characterScopeKey"] for row in rows] == [SCOPE]
    if selector != "slot":
        assert rows[0]["_exampleCount"] == 0, "grounding must not inflate actual dialogue example count"


@pytest.mark.parametrize("selector", ["slot", "exact", "alias"])
def test_legacy_dialogue_asset_remains_public(local_mysql, selector):
    connection = local_mysql["attempt"]
    _seed(connection, _assets(legacy=True, example_count=1))
    assert [row["characterScopeKey"] for row in _query(connection, selector)] == [SCOPE]


@pytest.mark.parametrize("selector", ["slot", "exact", "alias"])
@pytest.mark.parametrize("invalid", [
    "bad_profile_hash", "mixed_generation", "legacy_inventory", "wrong_grounding_actor",
    "unsafe_profile_label", "noninteger_episode_number", "stale_readiness",
])
def test_invalid_v1_cannot_pass_via_nonempty_legacy_examples(local_mysql, selector, invalid):
    connection = local_mysql["attempt"]
    inventory, profile, examples = _assets(example_count=1)
    if invalid == "bad_profile_hash":
        profile["character_contract"]["generation_hash"] = "invalid"
    elif invalid == "mixed_generation":
        inventory["character_contract"]["generation_hash"] = "b" * 64
    elif invalid == "legacy_inventory":
        inventory.pop("character_contract")
    elif invalid == "wrong_grounding_actor":
        examples["grounding_v1"][0]["character_key"] = "character:other"
    elif invalid == "unsafe_profile_label":
        profile["display_name"] = "이름\n지시문"
    elif invalid == "noninteger_episode_number":
        examples["grounding_v1"][0]["episode_no"] = "31"
    else:
        inventory["chat_readiness_v1"]["character_chat_allowed"] = False
    _seed(connection, (inventory, profile, examples))
    assert _query(connection, selector) == []


@pytest.mark.parametrize("selector", ["slot", "exact", "alias", "preview"])
@pytest.mark.parametrize("invalid", ["missing", "malformed", "above_reader", "outside_newest_twelve"])
def test_actual_public_consumers_reject_missing_or_malformed_provenance(local_mysql, selector, invalid):
    connection = local_mysql["attempt"]
    inventory, profile, examples = _assets(example_count=1)
    evidence = examples["grounding_v1"][0]
    bad = {**evidence}
    bad.pop("episode_scope_key")
    if invalid == "malformed":
        bad["episode_scope_key"] = "episode:1\n"
    elif invalid == "above_reader":
        bad["episode_no"] = 60
    if invalid == "outside_newest_twelve":
        examples["grounding_v1"] = [
            {**evidence, "episode_no": no, "episode_scope_key": f"episode:{no}"}
            for no in range(2, 15)
        ]
    examples["grounding_v1"].append(bad)
    _seed(connection, (inventory, profile, examples))
    if selector == "preview":
        _seed_consumer_context(connection)
        with pytest.raises(CustomResponseException):
            _preview(connection, 5)
    else:
        assert _query(connection, selector) == []


@pytest.mark.parametrize("legacy", [False, True], ids=["grounded_action", "legacy_dialogue"])
def test_actual_asset_rows_survive_catalog_fallback_and_scene_filter(local_mysql, legacy):
    connection = local_mysql["attempt"]
    _seed(connection, _assets(legacy=legacy, example_count=1 if legacy else 0))
    products, readiness = _context()
    exact = catalog.merge_public_character_catalog_candidates(products, readiness, _query(connection, "exact"))
    fallback_ids = catalog.select_public_character_catalog_alias_fallback_product_ids(products, readiness, exact)
    fallback = catalog.merge_public_character_catalog_candidates(products, readiness, _query(connection, "alias"))
    merged = catalog.merge_public_character_catalog_asset_candidates(exact, fallback, fallback_product_ids=fallback_ids)
    scenes = [{"characterSlotId": row["characterSlotId"], "sceneCount": 5, "entryEpisodeNo": 1} for row in merged]
    visible = catalog.filter_public_character_catalog_candidates(merged, scenes)
    assert [row["characterScopeKey"] for row in visible] == [SCOPE]
    assert visible[0]["_exampleCount"] == (1 if legacy else 0)


def test_empty_fallback_does_not_erase_actual_ready_exact_asset(local_mysql):
    connection = local_mysql["attempt"]
    _seed(connection, _assets(legacy=True, example_count=4))
    products, readiness = _context()
    exact = catalog.merge_public_character_catalog_candidates(products, readiness, _query(connection, "exact"))
    assert len(exact) == 1
    fallback_ids = catalog.select_public_character_catalog_alias_fallback_product_ids(products, readiness, exact)
    # Empty candidate result is the agreed merge boundary input, not fake DB success.
    merged = catalog.merge_public_character_catalog_asset_candidates(exact, [], fallback_product_ids=fallback_ids)
    scenes = [{"characterSlotId": exact[0]["characterSlotId"], "sceneCount": 5, "entryEpisodeNo": 1}]
    assert [row["characterScopeKey"] for row in catalog.filter_public_character_catalog_candidates(merged, scenes)] == [SCOPE]


def test_legacy_alias_fallback_keeps_its_existing_identity_compatibility(local_mysql):
    connection = local_mysql["attempt"]
    _seed(connection, _assets(legacy=True, example_count=1, alias=True))
    assert _query(connection, "exact") == []
    assert [row["characterScopeKey"] for row in _query(connection, "alias")] == [SCOPE]


def test_v1_alias_cannot_borrow_another_character_asset(local_mysql):
    connection = local_mysql["attempt"]
    _seed(connection, _assets(alias=True))
    assert _query(connection, "alias") == []


@pytest.mark.parametrize("selector", ["slot", "exact", "alias"])
def test_empty_legacy_examples_remain_ineligible(local_mysql, selector):
    connection = local_mysql["attempt"]
    _seed(connection, _assets(legacy=True))
    assert _query(connection, selector) == []


@pytest.mark.parametrize("example_text", [QUOTE, "   "], ids=["nonblank", "blank"])
def test_exact_legacy_preserves_source_count_gate_without_changing_alias_or_slot(local_mysql, example_text):
    connection = local_mysql["attempt"]
    inventory, profile, examples = _assets(legacy=True, example_count=1)
    examples["examples"][0]["text"] = example_text
    _seed(connection, (inventory, profile, examples))
    with connection.cursor() as cur:
        cur.execute("""UPDATE tb_story_agent_context_summary SET source_doc_count=0
            WHERE product_id=%s AND summary_type='character_rp_examples' AND scope_key=%s
        """, (PRODUCT_ID, SCOPE))
    assert _query(connection, "exact") == []
    for selector in ("alias", "slot"):
        assert [row["characterScopeKey"] for row in _query(connection, selector)] == [SCOPE]


@pytest.mark.parametrize("legacy", [False, True])
def test_real_roster_quality_and_full_preview_consume_the_same_bundle(local_mysql, legacy):
    connection = local_mysql["attempt"]
    _seed(connection, _assets(legacy=legacy, example_count=1 if legacy else 0))
    _seed_consumer_context(connection)
    session = _MySQLSession(connection)
    roster = asyncio.run(catalog.get_admin_main_character_roster(PRODUCT_ID, session))["data"]
    assert len(roster) == 1
    assert roster[0]["exampleCount"] == (1 if legacy else 0)
    assert roster[0]["chatQuality"] == "normal"
    assert asyncio.run(catalog._load_main_character_chat_quality([PRODUCT_ID], session)) == {PRODUCT_ID: "normal"}
    preview = asyncio.run(catalog.get_public_character_chat_preview(
        product_id=PRODUCT_ID, character_scope_key=SCOPE, episode_no=5, db=session,
    ))["data"]
    assert preview["episodeNo"] == 5
    assert QUOTE in preview["sceneExcerpt"]
    if not legacy:
        assert preview["personalityCore"] == []
        assert preview["speechStyle"]["tone"] == []


@pytest.mark.parametrize("invalid", ["mixed", "unsafe", "past_reader", "noninteger_episode_number", "consent"])
def test_full_preview_rejects_invalid_or_unread_bundle(local_mysql, invalid):
    connection = local_mysql["attempt"]
    inventory, profile, examples = _assets(example_count=1)
    if invalid == "mixed":
        examples["character_contract"]["generation_hash"] = "b" * 64
    elif invalid == "unsafe":
        profile["identity_labels_v1"] = [{"episode_no": 1, "label": "이름\n지시"}]
    elif invalid in {"past_reader", "noninteger_episode_number"}:
        examples["grounding_v1"][0]["episode_no"] = 6 if invalid == "past_reader" else "31"
    _seed(connection, (inventory, profile, examples))
    _seed_consumer_context(connection)
    if invalid == "consent":
        with connection.cursor() as cur:
            cur.execute("UPDATE tb_product SET ai_content_service_enabled_yn='N' WHERE product_id=%s", (PRODUCT_ID,))
    with pytest.raises(CustomResponseException):
        asyncio.run(catalog.get_public_character_chat_preview(
            product_id=PRODUCT_ID, character_scope_key=SCOPE, episode_no=5,
            db=_MySQLSession(connection),
        ))


def test_chat_only_major_remains_in_catalog_but_not_main_slot_roster(local_mysql):
    connection = local_mysql["attempt"]
    inventory, profile, examples = _assets()
    inventory.update(work_role="major_character", public_slot_eligible=False)
    inventory["chat_readiness_v1"]["public_slot_allowed"] = False
    _seed(connection, (inventory, profile, examples))
    _seed_consumer_context(connection)
    session = _MySQLSession(connection)
    assert [row["characterScopeKey"] for row in _query(connection, "exact")] == [SCOPE]
    assert asyncio.run(catalog.get_admin_main_character_roster(PRODUCT_ID, session))["data"] == []
    preview = asyncio.run(catalog.get_public_character_chat_preview(
        product_id=PRODUCT_ID, character_scope_key=SCOPE, episode_no=5, db=session,
    ))
    assert preview["data"]["sceneExcerpt"] == QUOTE


def test_public_ordinal_window_accepts_episode_numbers_above_thirty_and_respects_reader(local_mysql):
    connection = local_mysql["attempt"]
    inventory, profile, examples = _assets()
    profile["identity_labels_v1"] = [{"episode_no": 31, "label": "대화 상대"}]
    examples["grounding_v1"][0]["episode_no"] = 31
    examples["grounding_v1"][0]["episode_scope_key"] = "episode:31"
    _seed(connection, (inventory, profile, examples))
    _seed_consumer_context(connection, first_episode_no=31)
    for selector in ("slot", "exact", "alias"):
        rows = _query(connection, selector)
        assert [row["characterScopeKey"] for row in rows] == [SCOPE]
        if selector != "slot":
            assert rows[0]["_exampleCount"] == 0
    products, readiness = _context()
    products[0]["_latestPublicEpisodeNo"] = 45
    readiness[0]["_continuousReadyEpisodeNo"] = 45
    candidates = catalog.merge_public_character_catalog_candidates(
        products, readiness, _query(connection, "exact"),
    )
    scenes = [{"characterSlotId": candidates[0]["characterSlotId"], "sceneCount": 5, "entryEpisodeNo": 31}]
    assert [row["characterScopeKey"] for row in catalog.filter_public_character_catalog_candidates(candidates, scenes)] == [SCOPE]
    session = _MySQLSession(connection)
    roster = asyncio.run(catalog.get_admin_main_character_roster(PRODUCT_ID, session))["data"]
    assert roster[0]["exampleCount"] == 0
    assert roster[0]["chatQuality"] == "normal"
    assert asyncio.run(catalog._load_main_character_chat_quality([PRODUCT_ID], session)) == {PRODUCT_ID: "normal"}
    preview = asyncio.run(catalog.get_public_character_chat_preview(
        product_id=PRODUCT_ID, character_scope_key=SCOPE, episode_no=35, db=session,
    ))["data"]
    assert preview["episodeNo"] == 35
    assert preview["sceneExcerpt"] == QUOTE
    with pytest.raises(CustomResponseException):
        asyncio.run(catalog.get_public_character_chat_preview(
            product_id=PRODUCT_ID, character_scope_key=SCOPE, episode_no=30, db=session,
        ))


def _scene_readiness(connection):
    result = asyncio.run(_MySQLSession(connection).execute(
        text(catalog.build_public_character_catalog_scene_query()),
        {"candidate_json": json.dumps([{"characterSlotId": 1, "productId": PRODUCT_ID, "compatibleScopeKeys": [SCOPE]}])},
    ))
    return result.mappings().all()


def _producer_scene_scopes(connection):
    with connection.cursor() as cur:
        episode_scope_map = fetch_character_chat_catalog_scene_episode_scope_map(
            cur, product_id=PRODUCT_ID,
        )
        rows = fetch_active_character_asset_summary_rows(
            cur, product_id=PRODUCT_ID, summary_type="episode_scene_extraction",
        )
    return build_usable_character_scene_episodes_by_scope(rows, episode_scope_map).get(SCOPE, {})


def _preview(connection, episode_no):
    return asyncio.run(catalog.get_public_character_chat_preview(
        product_id=PRODUCT_ID, character_scope_key=SCOPE, episode_no=episode_no,
        db=_MySQLSession(connection),
    ))["data"]


@pytest.mark.parametrize("anchor, expected_aliases", [(30, ["초기 이름"]), (31, ["초기 이름", "나중 이름"])])
def test_actual_preview_bounds_aliases_and_ignores_v1_extra_metadata(local_mysql, anchor, expected_aliases):
    connection = local_mysql["attempt"]
    inventory, profile, examples = _assets()
    inventory["aliases"] = ["초기 이름", "나중 이름"]
    examples["grounding_v1"][0]["episode_no"] = 5
    examples["grounding_v1"][0]["episode_scope_key"] = "episode:5"
    profile.update(
        identity_labels_v1=[{"episode_no": 5, "label": "초기 이름"}, {"episode_no": 31, "label": "나중 이름"}],
        role_label="잔여 역할", personality_core=["잔여 성격"], speech_style={"tone": ["잔여 말투"]},
    )
    _seed(connection, (inventory, profile, examples))
    _seed_consumer_context(connection)
    _add_same_number_scene(connection, episode_id=31, episode_no=31, source_text="나중 이름이 밝혀졌다.")
    preview = _preview(connection, anchor)
    assert preview["aliases"] == expected_aliases
    assert preview["roleLabel"] == "main_protagonist"
    assert preview["personalityCore"] == []
    assert preview["speechStyle"] == {"tone": [], "formality": "", "sentenceLength": ""}
    assert preview["episodeNo"] == (5 if anchor == 30 else 31)


def test_actual_legacy_preview_retains_metadata(local_mysql):
    connection = local_mysql["attempt"]
    inventory, profile, examples = _assets(legacy=True, example_count=1)
    inventory["aliases"] = ["기존 별칭"]
    profile["role_label"] = "기존 역할"
    _seed(connection, (inventory, profile, examples))
    _seed_consumer_context(connection)
    preview = _preview(connection, 1)
    assert preview["aliases"] == ["기존 별칭"]
    assert preview["roleLabel"] == "기존 역할"
    assert preview["personalityCore"] == ["신중함"]
    assert preview["speechStyle"]["tone"] == ["차분함"]


def test_global_five_scenes_allow_default_first_scene_preview(local_mysql):
    connection = local_mysql["attempt"]
    _seed(connection, _assets())
    _seed_consumer_context(connection)
    assert _scene_readiness(connection)[0]["sceneCount"] == 5
    assert _preview(connection, 1)["episodeNo"] == 1


@pytest.mark.parametrize("invalid", ["ended", "before_cutoff", "fourteen_public", "four_scenes"])
def test_preview_uses_global_public_product_and_scene_gates(local_mysql, invalid):
    connection = local_mysql["attempt"]
    _seed(connection, _assets())
    _seed_consumer_context(connection, scene_count=4 if invalid == "four_scenes" else 5)
    with connection.cursor() as cur:
        if invalid == "ended":
            cur.execute("UPDATE tb_product SET status_code='end' WHERE product_id=%s", (PRODUCT_ID,))
        elif invalid == "before_cutoff":
            cur.execute("UPDATE tb_product_episode SET open_changed_date='2026-02-28' WHERE episode_id=1")
        elif invalid == "fourteen_public":
            cur.execute("UPDATE tb_product_episode SET open_yn='N' WHERE episode_id=15")
    with pytest.raises(CustomResponseException):
        _preview(connection, 5)


def _add_same_number_scene(connection, *, episode_id, episode_no, source_text, open_yn="Y", use_yn="Y", price_type="free"):
    with connection.cursor() as cur:
        cur.execute("""INSERT INTO tb_product_episode VALUES
            (%s, %s, %s, '다른 회차 행', %s, %s, %s, '2026-09-01', NULL, '2026-09-01')
        """, (episode_id, PRODUCT_ID, episode_no, use_yn, open_yn, price_type))
        cur.execute("INSERT INTO tb_story_agent_context_doc VALUES (%s, 'Y')", (episode_id,))
        cur.execute("INSERT INTO tb_story_agent_context_chunk VALUES (%s, %s, %s, 0, %s, 1, %s)",
                    (episode_id, PRODUCT_ID, episode_id, len(source_text), source_text))
        for summary_type, payload in [
            ("episode_summary", {"summary": source_text}),
            ("episode_scene_extraction", {"status": "ok", "episode_no": episode_no, "scenes": [{
                "scene_index": 1, "scene_gist": source_text, "char_start": 0, "char_end": len(source_text),
                "participants": [{"scope_key": SCOPE}], "action_ownership": [],
            }]}),
        ]:
            encoded = json.dumps(payload, ensure_ascii=False)
            upsert_summary(cur, product_id=PRODUCT_ID, summary_type=summary_type,
                           scope_key=f"episode:{episode_id}", source_hash=hashlib.sha256(encoded.encode()).hexdigest(),
                           source_doc_count=1, summary_text=encoded, episode_from=episode_no, episode_to=episode_no)


@pytest.mark.parametrize("visibility", ["private", "inactive", "paid"])
def test_ineligible_same_number_scene_cannot_borrow_public_sibling(local_mysql, visibility):
    connection = local_mysql["attempt"]
    _seed(connection, _assets())
    _seed_consumer_context(connection, scene_count=4)
    _add_same_number_scene(connection, episode_id=100, episode_no=5, source_text="공개하면 안 되는 원문",
                          open_yn="N" if visibility == "private" else "Y",
                          use_yn="N" if visibility == "inactive" else "Y",
                          price_type="paid" if visibility == "paid" else "free")
    assert _scene_readiness(connection)[0]["sceneCount"] == 4
    with pytest.raises(CustomResponseException):
        _preview(connection, 5)


def test_same_number_public_scenes_keep_exact_source_and_summary(local_mysql):
    connection = local_mysql["attempt"]
    _seed(connection, _assets())
    _seed_consumer_context(connection)
    _add_same_number_scene(connection, episode_id=100, episode_no=5, source_text="독립적인 두 번째 원문")
    producer_scopes = _producer_scene_scopes(connection)
    assert producer_scopes["episode:5"] == producer_scopes["episode:100"] == 5
    assert len(producer_scopes) == _scene_readiness(connection)[0]["sceneCount"] == 6
    preview = _preview(connection, 5)
    assert preview["sceneExcerpt"] == "독립적인 두 번째 원문"
    assert preview["episodeSummary"] == "독립적인 두 번째 원문"
    with connection.cursor() as cur:
        cur.execute("UPDATE tb_story_agent_context_summary SET is_active='N' WHERE scope_key='episode:100' AND summary_type='episode_scene_extraction'")
    assert len(_producer_scene_scopes(connection)) == _scene_readiness(connection)[0]["sceneCount"] == 5
    preview = _preview(connection, 5)
    assert preview["sceneExcerpt"] == QUOTE
    assert preview["episodeSummary"] == "그가 출구를 살피는 장면이다."


def test_scene_collection_ranks_paid_rows_before_free_filter(local_mysql):
    connection = local_mysql["attempt"]
    _seed(connection, _assets())
    _seed_consumer_context(connection, scene_count=31, episode_count=31, first_episode_no=31)
    with connection.cursor() as cur:
        cur.execute("UPDATE tb_product_episode SET price_type='paid' WHERE episode_no BETWEEN 36 AND 59")
    # Public ordinals 1..5 and 30 are free; ordinal 31 is never pulled into the window.
    producer_scopes = _producer_scene_scopes(connection)
    assert set(producer_scopes) == {f"episode:{no}" for no in (*range(31, 36), 60)}
    assert len(producer_scopes) == _scene_readiness(connection)[0]["sceneCount"] == 6
    preview = _preview(connection, 61)
    assert preview["episodeNo"] == 60
    with connection.cursor() as cur:
        cur.execute("UPDATE tb_product_episode SET price_type='paid' WHERE episode_no=60")
    assert len(_producer_scene_scopes(connection)) == _scene_readiness(connection)[0]["sceneCount"] == 5
    assert _preview(connection, 61)["episodeNo"] == 35


@pytest.mark.parametrize("invalid", ["episode_to", "episode_from", "payload_mismatch", "payload_missing", "payload_string", "payload_bool", "payload_float"])
@pytest.mark.parametrize("good_scene_count", [4, 5])
def test_scene_metadata_must_match_exact_authoritative_source_before_count_or_preview(local_mysql, invalid, good_scene_count):
    connection = local_mysql["attempt"]
    _seed(connection, _assets())
    _seed_consumer_context(connection, scene_count=good_scene_count)
    _add_same_number_scene(connection, episode_id=104, episode_no=5, source_text="104의 독립적인 원문")
    with connection.cursor() as cur:
        cur.execute("SELECT summary_text FROM tb_story_agent_context_summary WHERE summary_type='episode_scene_extraction' AND scope_key='episode:104'")
        original_payload = json.loads(cur.fetchone()["summary_text"])
        payload = copy.deepcopy(original_payload)
        episode_from = 999 if invalid == "episode_from" else 5
        episode_to = 999 if invalid == "episode_to" else 5
        if invalid == "payload_missing":
            payload.pop("episode_no")
        elif invalid.startswith("payload_"):
            payload["episode_no"] = {"payload_mismatch": 999, "payload_string": "5", "payload_bool": True, "payload_float": 5.0}[invalid]
        cur.execute("""UPDATE tb_story_agent_context_summary
            SET episode_from=%s, episode_to=%s, summary_text=%s
            WHERE summary_type='episode_scene_extraction' AND scope_key='episode:104'
        """, (episode_from, episode_to, json.dumps(payload, ensure_ascii=False)))
    producer_scopes = _producer_scene_scopes(connection)
    assert "episode:104" not in producer_scopes
    assert len(producer_scopes) == _scene_readiness(connection)[0]["sceneCount"] == good_scene_count
    if good_scene_count == 4:
        with pytest.raises(CustomResponseException):
            _preview(connection, 5)
    else:
        assert _preview(connection, 5)["sceneExcerpt"] == QUOTE
    with connection.cursor() as cur:
        cur.execute("""UPDATE tb_story_agent_context_summary
            SET episode_from=5, episode_to=5, summary_text=%s
            WHERE summary_type='episode_scene_extraction' AND scope_key='episode:104'
        """, (json.dumps(original_payload, ensure_ascii=False),))
    producer_scopes = _producer_scene_scopes(connection)
    assert producer_scopes["episode:104"] == 5
    assert len(producer_scopes) == _scene_readiness(connection)[0]["sceneCount"] == good_scene_count + 1
    assert _preview(connection, 5)["sceneExcerpt"] == "104의 독립적인 원문"


def test_scene_collection_episode_zero_consumes_a_public_ordinal(local_mysql):
    connection = local_mysql["attempt"]
    _seed(connection, _assets())
    _seed_consumer_context(connection, scene_count=31, episode_count=31, first_episode_no=0)
    # Zero consumes the first public position but cannot supply positive scene evidence.
    producer_scopes = _producer_scene_scopes(connection)
    assert set(producer_scopes) == {f"episode:{no}" for no in range(1, 30)}
    assert len(producer_scopes) == _scene_readiness(connection)[0]["sceneCount"] == 29
    assert _preview(connection, 30)["episodeNo"] == 29


def test_noncanonical_scene_scope_cannot_inflate_episode_readiness(local_mysql):
    connection = local_mysql["attempt"]
    _seed(connection, _assets())
    _seed_consumer_context(connection, scene_count=4)
    with connection.cursor() as cur:
        cur.execute("""INSERT INTO tb_story_agent_context_summary
            (product_id, summary_type, scope_key, source_hash, source_doc_count, summary_text, episode_from, episode_to, is_active)
            SELECT product_id, summary_type, 'episode:0004', %s, source_doc_count, summary_text, episode_from, episode_to, 'Y'
            FROM tb_story_agent_context_summary WHERE summary_type='episode_scene_extraction' AND scope_key='episode:4'
        """, ("f" * 64,))
    assert _scene_readiness(connection)[0]["sceneCount"] == 4
    with pytest.raises(CustomResponseException):
        _preview(connection, 5)


def test_episode_summary_gate_cannot_borrow_a_private_same_number_row(local_mysql):
    connection = local_mysql["attempt"]
    _seed(connection, _assets())
    _seed_consumer_context(connection)
    with connection.cursor() as cur:
        cur.execute("UPDATE tb_story_agent_context_summary SET is_active='N' WHERE summary_type='episode_summary'")
    _add_same_number_scene(connection, episode_id=100, episode_no=5, source_text="비공개 요약만 존재", open_yn="N")
    assert _scene_readiness(connection)[0]["sceneCount"] == 5
    with pytest.raises(CustomResponseException):
        _preview(connection, 5)


@pytest.mark.parametrize("case", ["valid_five", "legacy_five", "paid", "private", "inactive", "outwindow", "malformed"])
def test_admin_selection_and_quality_use_the_same_exact_public_scene_count(local_mysql, case):
    connection = local_mysql["attempt"]
    valid = case in {"valid_five", "legacy_five"}
    _seed(connection, _assets(legacy=case == "legacy_five", example_count=1 if case == "legacy_five" else 0))
    _seed_consumer_context(connection, scene_count=5 if valid else 4, episode_count=31 if case == "outwindow" else 15)
    if case in {"paid", "private", "inactive"}:
        _add_same_number_scene(connection, episode_id=100, episode_no=5, source_text="집계하면 안 되는 다섯 번째 장면",
                              price_type="paid" if case == "paid" else "free",
                              open_yn="N" if case == "private" else "Y",
                              use_yn="N" if case == "inactive" else "Y")
    elif case in {"outwindow", "malformed"}:
        episode_no = 31 if case == "outwindow" else 5
        payload = {"status": "failed", "notes": [SCOPE]} if case == "malformed" else {
            "status": "ok", "episode_no": episode_no, "scenes": [{"scene_gist": "수집 범위 밖 장면", "participants": [{"scope_key": SCOPE}]}],
        }
        encoded = json.dumps(payload, ensure_ascii=False)
        with connection.cursor() as cur:
            upsert_summary(cur, product_id=PRODUCT_ID, summary_type="episode_scene_extraction", scope_key=f"episode:{episode_no}",
                           source_hash=hashlib.sha256(encoded.encode()).hexdigest(), source_doc_count=1,
                           summary_text=encoded, episode_from=episode_no, episode_to=episode_no)
    session = _MySQLSession(connection)
    public_count = _scene_readiness(connection)[0]["sceneCount"]
    roster = asyncio.run(catalog.get_admin_main_character_roster(PRODUCT_ID, session))["data"]
    assert public_count == (5 if valid else 4)
    assert roster[0]["sceneCount"] == public_count
    assert roster[0]["chatQuality"] == ("normal" if valid else "insufficient")
    assert asyncio.run(catalog._load_main_character_chat_quality([PRODUCT_ID], session)) == {
        PRODUCT_ID: "normal" if valid else "insufficient",
    }
    if valid:
        assert asyncio.run(catalog._ensure_character_slot_selection_eligible(
            product_id=PRODUCT_ID, character_scope_key=SCOPE, db=session,
        )) == "대화 상대"
    else:
        with pytest.raises(CustomResponseException) as failure:
            asyncio.run(catalog._ensure_character_slot_selection_eligible(
                product_id=PRODUCT_ID, character_scope_key=SCOPE, db=session,
            ))
        assert failure.value.status_code == 400
