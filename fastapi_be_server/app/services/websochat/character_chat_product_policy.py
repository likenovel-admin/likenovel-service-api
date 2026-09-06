import re
from typing import Any


CHARACTER_CHAT_MINIMUM_OPEN_EPISODE_COUNT = 15
CHARACTER_CHAT_MAX_COLLECTED_PUBLIC_EPISODES = 30
CHARACTER_CHAT_MINIMUM_USABLE_SCENE_EPISODE_COUNT = 5
CHARACTER_CHAT_FIRST_PUBLIC_EPISODE_AT = "2026-03-01 00:00:00"
CHARACTER_CHAT_ELIGIBLE_STATUS_CODE = "ongoing"
_CHARACTER_CHAT_LABEL_UNSAFE_CHARACTERS = "\x00-\x1f\x7f\x85\u2028\u2029"
# Python str.strip also treats U+001C..U+001F as whitespace, unlike ICU [:space:].
_CHARACTER_CHAT_NONSPACE_PATTERN_SQL = "CONCAT('[^[:space:]', CHAR(28, 29, 30, 31 USING utf8mb4), ']')"
_CHARACTER_CHAT_GROUNDING_KINDS = (
    "dialogue", "monologue", "narrated_action", "narrated_state", "presence", "relation",
)
_CHARACTER_CHAT_GROUNDING_SOURCE_PARTS = ("episode_source", "episode_summary")


def is_character_chat_inventory_v1_decision_coherent(
    payload: dict[str, Any], *, require_public_slot: bool = False,
) -> bool:
    """Check the finalized marked decision; intrinsic evidence is producer-owned."""
    if not isinstance(payload, dict):
        return False
    contract = payload.get("character_contract")
    readiness = payload.get("chat_readiness_v1")
    key = payload.get("canonical_character_key")
    if (
        not isinstance(contract, dict)
        or contract.get("version") != "v1"
        or not isinstance(key, str)
        or not key or key != key.strip()
        or contract.get("character_key") != key
        or not isinstance(contract.get("generation_hash"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", contract["generation_hash"])
        or not isinstance(readiness, dict)
        or payload.get("public_chat_eligible") is not True
        or readiness.get("character_chat_allowed") is not True
        or readiness.get("exposure_decision") != "eligible"
    ):
        return False
    return not require_public_slot or (
        payload.get("public_slot_eligible") is True
        and readiness.get("public_slot_allowed") is True
    )


def is_character_chat_single_line_label(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= 100
        and re.search(f"[{_CHARACTER_CHAT_LABEL_UNSAFE_CHARACTERS}]", value) is None
    )


def _build_character_chat_single_line_label_sql(value_sql: str) -> str:
    unsafe_characters_hex = _CHARACTER_CHAT_LABEL_UNSAFE_CHARACTERS.encode("utf-8").hex()
    return f"""(
        {value_sql} REGEXP {_CHARACTER_CHAT_NONSPACE_PATTERN_SQL}
        AND CHAR_LENGTH({value_sql}) <= 100
        AND NOT {value_sql} REGEXP CONCAT(
            '[', CONVERT(0x{unsafe_characters_hex} USING utf8mb4), ']'
        )
    )"""


def select_character_chat_grounding_v1(
    profile: dict[str, Any],
    examples_payload: dict[str, Any],
    *,
    expected_character_key: str,
    read_episode_to: int | None,
) -> list[dict[str, Any]] | None:
    """Validate all items; None is producer/catalog validation without a reader bound."""
    contract = profile.get("character_contract")
    if (
        "character_contract" not in profile
        or not is_character_chat_rp_profile_payload_ready(
            profile, expected_character_key=expected_character_key
        )
        or examples_payload.get("character_contract") != contract
        or profile.get("character_key") != expected_character_key
        or examples_payload.get("character_key") != expected_character_key
    ):
        return None
    evidence = examples_payload.get("grounding_v1")
    if not isinstance(evidence, list) or not evidence:
        return None
    selected = []
    for item in evidence:
        if (
            not isinstance(item, dict)
            or type(item.get("episode_no")) is not int
            or item["episode_no"] <= 0
            or not isinstance(item.get("episode_scope_key"), str)
            or not re.fullmatch(r"episode:[1-9][0-9]*", item["episode_scope_key"])
            or item.get("character_key") != expected_character_key
            or not isinstance(item.get("kind"), str)
            or item.get("kind") not in _CHARACTER_CHAT_GROUNDING_KINDS
            or not isinstance(item.get("source_part"), str)
            or item["source_part"] not in _CHARACTER_CHAT_GROUNDING_SOURCE_PARTS
            or not isinstance(item.get("quote"), str)
            or not item["quote"].strip()
            or len(item["quote"]) > 600
            or not isinstance(item.get("counterpart_label"), str)
            or len(item["counterpart_label"]) > 100
        ):
            return None
        if read_episode_to is None or item["episode_no"] <= read_episode_to:
            selected.append(item)
    return sorted(selected, key=lambda item: item["episode_no"], reverse=True)[:12]


def _has_nonempty_profile_text(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(
            value
            and isinstance(value[0], str)
            and value[0].strip()
        )
    return False


def is_character_chat_rp_profile_payload_ready(
    payload: dict[str, Any] | None,
    *,
    expected_character_key: str | None = None,
) -> bool:
    if not isinstance(payload, dict):
        return False

    character_key = str(payload.get("character_key") or "").strip()
    if not character_key:
        return False
    normalized_expected_key = str(expected_character_key or "").strip()
    if normalized_expected_key and character_key != normalized_expected_key:
        return False

    if "character_contract" in payload:
        contract = payload["character_contract"]
        labels = payload.get("identity_labels_v1")
        if (
            not isinstance(contract, dict)
            or contract.get("version") != "v1"
            or payload.get("character_key") != character_key
            or contract.get("character_key") != character_key
            or not isinstance(contract.get("generation_hash"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", contract["generation_hash"])
            or not is_character_chat_single_line_label(payload.get("display_name"))
            or not isinstance(labels, list)
        ):
            return False
        return all(
            isinstance(label, dict)
            and type(label.get("episode_no")) is int
            and label["episode_no"] > 0
            and is_character_chat_single_line_label(label.get("label"))
            for label in labels
        )

    personality_core = payload.get("personality_core")
    speech_style = payload.get("speech_style")
    if not isinstance(personality_core, list) or not _has_nonempty_profile_text(
        personality_core
    ):
        return False
    if not isinstance(speech_style, dict):
        return False
    return all(
        (
            _has_nonempty_profile_text(speech_style.get("tone")),
            _has_nonempty_profile_text(speech_style.get("formality")),
            _has_nonempty_profile_text(speech_style.get("sentence_length")),
        )
    )


def build_character_chat_rp_profile_ready_sql(
    *,
    profile_alias: str,
    expected_character_key_sql: str | None = None,
) -> str:
    character_key_sql = f"""TRIM(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
        {profile_alias}.summary_text, '$.character_key'
    )), ''))"""
    expected_key_predicate = (
        f"AND {character_key_sql} = {expected_character_key_sql}"
        if expected_character_key_sql
        else f"AND {character_key_sql} <> ''"
    )
    legacy_sql = f"""(
        JSON_VALID({profile_alias}.summary_text)
        {expected_key_predicate}
        AND JSON_TYPE(JSON_EXTRACT(
            {profile_alias}.summary_text, '$.personality_core'
        )) = 'ARRAY'
        AND JSON_LENGTH(JSON_EXTRACT(
            {profile_alias}.summary_text, '$.personality_core'
        )) > 0
        AND TRIM(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
            {profile_alias}.summary_text, '$.personality_core[0]'
        )), '')) <> ''
        AND JSON_TYPE(JSON_EXTRACT(
            {profile_alias}.summary_text, '$.speech_style'
        )) = 'OBJECT'
        AND (
            (
                JSON_TYPE(JSON_EXTRACT(
                    {profile_alias}.summary_text, '$.speech_style.tone'
                )) = 'STRING'
                AND TRIM(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
                    {profile_alias}.summary_text, '$.speech_style.tone'
                )), '')) <> ''
            )
            OR (
                JSON_TYPE(JSON_EXTRACT(
                    {profile_alias}.summary_text, '$.speech_style.tone'
                )) = 'ARRAY'
                AND JSON_LENGTH(JSON_EXTRACT(
                    {profile_alias}.summary_text, '$.speech_style.tone'
                )) > 0
                AND TRIM(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
                    {profile_alias}.summary_text, '$.speech_style.tone[0]'
                )), '')) <> ''
            )
        )
        AND TRIM(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
            {profile_alias}.summary_text, '$.speech_style.formality'
        )), '')) <> ''
        AND TRIM(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
            {profile_alias}.summary_text, '$.speech_style.sentence_length'
        )), '')) <> ''
    )"""
    raw_key_sql = f"JSON_UNQUOTE(JSON_EXTRACT({profile_alias}.summary_text, '$.character_key'))"
    contract_key_sql = f"JSON_UNQUOTE(JSON_EXTRACT({profile_alias}.summary_text, '$.character_contract.character_key'))"
    generation_hash_sql = f"JSON_UNQUOTE(JSON_EXTRACT({profile_alias}.summary_text, '$.character_contract.generation_hash'))"
    display_name_sql = f"JSON_UNQUOTE(JSON_EXTRACT({profile_alias}.summary_text, '$.display_name'))"
    labels_sql = f"JSON_EXTRACT({profile_alias}.summary_text, '$.identity_labels_v1')"
    label_episode_sql = f"JSON_EXTRACT({labels_sql}, CONCAT('$[', identity_label.label_ordinal - 1, '].episode_no'))"
    label_text_sql = f"JSON_EXTRACT({labels_sql}, CONCAT('$[', identity_label.label_ordinal - 1, '].label'))"
    display_name_ready_sql = _build_character_chat_single_line_label_sql(display_name_sql)
    label_text_ready_sql = _build_character_chat_single_line_label_sql(f"JSON_UNQUOTE({label_text_sql})")
    v1_expected_key_sql = (
        f"AND BINARY {raw_key_sql} = BINARY {expected_character_key_sql}"
        if expected_character_key_sql else ""
    )
    return f"""(CASE
        WHEN NOT JSON_VALID({profile_alias}.summary_text) THEN 0
        WHEN JSON_CONTAINS_PATH({profile_alias}.summary_text, 'one', '$.character_contract')
        THEN COALESCE((
            JSON_TYPE(JSON_EXTRACT({profile_alias}.summary_text, '$.character_contract')) = 'OBJECT'
            AND BINARY JSON_UNQUOTE(JSON_EXTRACT({profile_alias}.summary_text, '$.character_contract.version')) = BINARY 'v1'
            AND JSON_TYPE(JSON_EXTRACT({profile_alias}.summary_text, '$.character_key')) = 'STRING'
            AND LEFT({raw_key_sql}, 1) REGEXP {_CHARACTER_CHAT_NONSPACE_PATTERN_SQL}
            AND RIGHT({raw_key_sql}, 1) REGEXP {_CHARACTER_CHAT_NONSPACE_PATTERN_SQL}
            AND JSON_TYPE(JSON_EXTRACT({profile_alias}.summary_text, '$.character_contract.character_key')) = 'STRING'
            AND BINARY {contract_key_sql} = BINARY {raw_key_sql}
            {v1_expected_key_sql}
            AND JSON_TYPE(JSON_EXTRACT({profile_alias}.summary_text, '$.character_contract.generation_hash')) = 'STRING'
            AND CHAR_LENGTH({generation_hash_sql}) = 64
            AND {generation_hash_sql} COLLATE utf8mb4_0900_bin REGEXP '^[0-9a-f]{{64}}$'
            AND JSON_TYPE(JSON_EXTRACT({profile_alias}.summary_text, '$.display_name')) = 'STRING'
            AND {display_name_ready_sql}
            AND JSON_TYPE({labels_sql}) = 'ARRAY'
            AND NOT EXISTS (
                SELECT 1
                FROM JSON_TABLE(
                    IF(JSON_TYPE({labels_sql}) = 'ARRAY', {labels_sql}, JSON_ARRAY()),
                    '$[*]' COLUMNS(label_ordinal FOR ORDINALITY)
                ) AS identity_label
                WHERE NOT COALESCE((
                    JSON_TYPE({label_episode_sql}) = 'INTEGER'
                    AND {label_episode_sql} > 0
                    AND JSON_TYPE({label_text_sql}) = 'STRING'
                    AND {label_text_ready_sql}
                ), 0)
            )
        ), 0)
        ELSE {legacy_sql}
    END)"""


def build_character_chat_grounded_bundle_evidence_count_sql(
    *,
    inventory_alias: str,
    profile_alias: str,
    examples_alias: str,
    expected_character_key_sql: str | None = None,
    inventory_scope_key_sql: str | None = None,
    read_episode_to_sql: str | None = None,
) -> str:
    """V1-only count of the reader-safe selection; invalid bundles yield zero.

    None means no reader-specific bound, not an episode-number collection cap.
    Callers own product joins, active-row, scene and public-slot policy. An absent
    or malformed marker never enters a legacy path inside this expression.
    """
    expected_key = expected_character_key_sql or f"{inventory_alias}.scope_key"
    inventory_scope = inventory_scope_key_sql or f"{inventory_alias}.scope_key"
    inventory_json = f"{inventory_alias}.summary_text"
    profile_json = f"{profile_alias}.summary_text"
    examples_json = f"{examples_alias}.summary_text"
    profile_ready = build_character_chat_rp_profile_ready_sql(
        profile_alias=profile_alias, expected_character_key_sql=expected_key,
    )
    evidence_json = f"JSON_EXTRACT(IF(JSON_VALID({examples_json}), {examples_json}, JSON_OBJECT()), '$.grounding_v1')"
    evidence_table = f"""JSON_TABLE(
        IF(JSON_TYPE({evidence_json}) = 'ARRAY', {evidence_json}, JSON_ARRAY()),
        '$[*]' COLUMNS(evidence_ordinal FOR ORDINALITY)
    ) AS grounded_evidence"""
    item_sql = f"JSON_EXTRACT({evidence_json}, CONCAT('$[', grounded_evidence.evidence_ordinal - 1, ']'))"
    episode_sql = f"JSON_EXTRACT({item_sql}, '$.episode_no')"
    episode_scope_sql = f"JSON_EXTRACT({item_sql}, '$.episode_scope_key')"
    reader_where_sql = (
        f"WHERE {episode_sql} <= {read_episode_to_sql}"
        if read_episode_to_sql is not None else ""
    )
    actor_sql = f"JSON_EXTRACT({item_sql}, '$.character_key')"
    kind_sql = f"JSON_EXTRACT({item_sql}, '$.kind')"
    source_sql = f"JSON_EXTRACT({item_sql}, '$.source_part')"
    quote_sql = f"JSON_EXTRACT({item_sql}, '$.quote')"
    counterpart_sql = f"JSON_EXTRACT({item_sql}, '$.counterpart_label')"
    allowed_kinds = ", ".join(f"BINARY '{kind}'" for kind in _CHARACTER_CHAT_GROUNDING_KINDS)
    allowed_sources = ", ".join(f"BINARY '{part}'" for part in _CHARACTER_CHAT_GROUNDING_SOURCE_PARTS)
    item_ready = f"""(
        JSON_TYPE({item_sql}) = 'OBJECT'
        AND JSON_TYPE({episode_sql}) = 'INTEGER'
        AND {episode_sql} > 0
        AND JSON_TYPE({episode_scope_sql}) = 'STRING'
        AND JSON_UNQUOTE({episode_scope_sql}) COLLATE utf8mb4_0900_bin REGEXP '^episode:[1-9][0-9]*\\\\z'
        AND JSON_TYPE({actor_sql}) = 'STRING'
        AND BINARY JSON_UNQUOTE({actor_sql}) = BINARY {expected_key}
        AND JSON_TYPE({kind_sql}) = 'STRING'
        AND BINARY JSON_UNQUOTE({kind_sql}) IN ({allowed_kinds})
        AND JSON_TYPE({source_sql}) = 'STRING'
        AND BINARY JSON_UNQUOTE({source_sql}) IN ({allowed_sources})
        AND JSON_TYPE({quote_sql}) = 'STRING'
        AND JSON_UNQUOTE({quote_sql}) REGEXP {_CHARACTER_CHAT_NONSPACE_PATTERN_SQL}
        AND CHAR_LENGTH(JSON_UNQUOTE({quote_sql})) <= 600
        AND JSON_TYPE({counterpart_sql}) = 'STRING'
        AND CHAR_LENGTH(JSON_UNQUOTE({counterpart_sql})) <= 100
    )"""
    return f"""(CASE
        WHEN NOT JSON_VALID({inventory_json})
          OR NOT JSON_VALID({profile_json})
          OR NOT JSON_VALID({examples_json}) THEN 0
        WHEN COALESCE((
            JSON_TYPE(JSON_EXTRACT({inventory_json}, '$.character_contract')) = 'OBJECT'
            AND JSON_TYPE(JSON_EXTRACT({profile_json}, '$.character_contract')) = 'OBJECT'
            AND JSON_TYPE(JSON_EXTRACT({examples_json}, '$.character_contract')) = 'OBJECT'
            AND JSON_EXTRACT({inventory_json}, '$.character_contract') = JSON_EXTRACT({profile_json}, '$.character_contract')
            AND JSON_EXTRACT({examples_json}, '$.character_contract') = JSON_EXTRACT({profile_json}, '$.character_contract')
            AND BINARY {inventory_scope} = BINARY {expected_key}
            AND BINARY {profile_alias}.scope_key = BINARY {expected_key}
            AND BINARY {examples_alias}.scope_key = BINARY {expected_key}
            AND JSON_TYPE(JSON_EXTRACT({inventory_json}, '$.canonical_character_key')) = 'STRING'
            AND BINARY JSON_UNQUOTE(JSON_EXTRACT({inventory_json}, '$.canonical_character_key')) = BINARY {expected_key}
            AND JSON_TYPE(JSON_EXTRACT({examples_json}, '$.character_key')) = 'STRING'
            AND BINARY JSON_UNQUOTE(JSON_EXTRACT({examples_json}, '$.character_key')) = BINARY {expected_key}
            AND JSON_TYPE(JSON_EXTRACT({inventory_json}, '$.public_chat_eligible')) = 'BOOLEAN'
            AND JSON_EXTRACT({inventory_json}, '$.public_chat_eligible') = CAST('true' AS JSON)
            AND JSON_TYPE(JSON_EXTRACT({inventory_json}, '$.chat_readiness_v1.character_chat_allowed')) = 'BOOLEAN'
            AND JSON_EXTRACT({inventory_json}, '$.chat_readiness_v1.character_chat_allowed') = CAST('true' AS JSON)
            AND BINARY JSON_UNQUOTE(JSON_EXTRACT({inventory_json}, '$.chat_readiness_v1.exposure_decision')) = BINARY 'eligible'
            AND {profile_ready}
            AND JSON_TYPE({evidence_json}) = 'ARRAY'
            AND JSON_LENGTH({evidence_json}) > 0
            AND NOT EXISTS (
                SELECT 1 FROM {evidence_table}
                WHERE NOT COALESCE({item_ready}, 0)
            )
        ), 0) THEN (
            SELECT LEAST(12, COUNT(*)) FROM {evidence_table}
            {reader_where_sql}
        )
        ELSE 0
    END)"""


def build_public_episode_opened_at_sql(episode_alias: str) -> str:
    return (
        f"COALESCE({episode_alias}.open_changed_date, "
        f"{episode_alias}.publish_reserve_date, {episode_alias}.created_date)"
    )


def build_correlated_character_chat_product_policy_sql(
    *,
    product_alias: str,
    episode_alias: str,
    minimum_open_episode_count_sql: str | None = None,
    first_public_episode_at_sql: str | None = None,
) -> str:
    minimum_sql = minimum_open_episode_count_sql or str(
        CHARACTER_CHAT_MINIMUM_OPEN_EPISODE_COUNT
    )
    cutoff_sql = first_public_episode_at_sql or (
        f"'{CHARACTER_CHAT_FIRST_PUBLIC_EPISODE_AT}'"
    )
    opened_at_sql = build_public_episode_opened_at_sql(episode_alias)
    return f"""
        AND {product_alias}.status_code = '{CHARACTER_CHAT_ELIGIBLE_STATUS_CODE}'
        AND EXISTS (
            SELECT 1
            FROM tb_product_episode {episode_alias}
            WHERE {episode_alias}.product_id = {product_alias}.product_id
              AND {episode_alias}.use_yn = 'Y'
              AND {episode_alias}.open_yn = 'Y'
            GROUP BY {episode_alias}.product_id
            HAVING COUNT(*) >= {minimum_sql}
               AND MIN({opened_at_sql}) >= {cutoff_sql}
        )
    """


def build_aggregate_character_chat_product_eligibility_sql(
    *, product_alias: str, episode_alias: str
) -> str:
    opened_at_sql = build_public_episode_opened_at_sql(episode_alias)
    return f"""
        CASE
            WHEN {product_alias}.status_code = '{CHARACTER_CHAT_ELIGIBLE_STATUS_CODE}'
             AND COUNT({episode_alias}.episode_id) >= {CHARACTER_CHAT_MINIMUM_OPEN_EPISODE_COUNT}
             AND MIN({opened_at_sql}) >= '{CHARACTER_CHAT_FIRST_PUBLIC_EPISODE_AT}'
            THEN 1
            ELSE 0
        END
    """


def is_character_chat_product_eligible(product_row: dict[str, Any]) -> bool:
    value = product_row.get("characterChatEligible")
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "y", "yes"}
    return bool(value)
