from typing import Any


CHARACTER_CHAT_MINIMUM_OPEN_EPISODE_COUNT = 15
CHARACTER_CHAT_MAX_COLLECTED_PUBLIC_EPISODES = 30
CHARACTER_CHAT_FIRST_PUBLIC_EPISODE_AT = "2026-03-01 00:00:00"
CHARACTER_CHAT_ELIGIBLE_STATUS_CODE = "ongoing"


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
    return f"""(
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
