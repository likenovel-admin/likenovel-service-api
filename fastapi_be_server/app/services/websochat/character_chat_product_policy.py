from typing import Any


CHARACTER_CHAT_MINIMUM_OPEN_EPISODE_COUNT = 15
CHARACTER_CHAT_FIRST_PUBLIC_EPISODE_AT = "2026-03-01 00:00:00"
CHARACTER_CHAT_ELIGIBLE_STATUS_CODE = "ongoing"


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
