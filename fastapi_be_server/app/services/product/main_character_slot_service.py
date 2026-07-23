import json
from collections import defaultdict

from fastapi import status
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

import app.schemas.admin as admin_schema
from app.exceptions import CustomResponseException
from app.services.websochat.character_chat_product_policy import (
    CHARACTER_CHAT_FIRST_PUBLIC_EPISODE_AT,
    CHARACTER_CHAT_MINIMUM_OPEN_EPISODE_COUNT,
    build_correlated_character_chat_product_policy_sql,
    build_public_episode_opened_at_sql,
)
from app.services.websochat.websochat_utils import _extract_websochat_json_object
from app.utils.query import get_file_path_sub_query, get_pagination_params
from app.utils.response import build_paginated_response


MAIN_CHARACTER_SLOT_MINIMUM_OPEN_EPISODE_COUNT = (
    CHARACTER_CHAT_MINIMUM_OPEN_EPISODE_COUNT
)
MAIN_CHARACTER_SLOT_MAX_CHARACTERS_PER_PRODUCT = 2
MAIN_CHARACTER_CHAT_GOOD_MIN_DISTINCT_EPISODES = 10
MAIN_CHARACTER_CHAT_GOOD_MIN_EXAMPLES = 4
MAIN_CHARACTER_CHAT_GOOD_MIN_SCENES = 5
CHARACTER_CHAT_PREVIEW_EXCERPT_MAX_CHARS = 900


def _main_character_product_policy_sql(
    *, product_alias: str, episode_alias: str
) -> str:
    return build_correlated_character_chat_product_policy_sql(
        product_alias=product_alias,
        episode_alias=episode_alias,
        minimum_open_episode_count_sql=str(
            MAIN_CHARACTER_SLOT_MINIMUM_OPEN_EPISODE_COUNT
        ),
    )


def _chat_ready_episode_count_sql(product_id_sql: str) -> str:
    return f"""(
        SELECT COUNT(DISTINCT readiness_episode.episode_id)
        FROM tb_product_episode readiness_episode
        WHERE readiness_episode.product_id = {product_id_sql}
          AND readiness_episode.use_yn = 'Y'
          AND readiness_episode.open_yn = 'Y'
          AND EXISTS (
              SELECT 1
              FROM tb_story_agent_context_summary readiness_summary
              WHERE readiness_summary.product_id = readiness_episode.product_id
                AND readiness_summary.scope_key =
                    CONCAT('episode:', readiness_episode.episode_id)
                AND readiness_summary.summary_type = 'episode_summary'
                AND readiness_summary.is_active = 'Y'
                AND readiness_summary.episode_to = readiness_episode.episode_no
                AND TRIM(COALESCE(readiness_summary.summary_text, '')) <> ''
          )
    )"""


def _chat_total_episode_count_sql(product_id_sql: str) -> str:
    return f"""(
        SELECT COUNT(DISTINCT readiness_episode.episode_id)
        FROM tb_product_episode readiness_episode
        WHERE readiness_episode.product_id = {product_id_sql}
          AND readiness_episode.use_yn = 'Y'
          AND readiness_episode.open_yn = 'Y'
    )"""


def classify_main_character_chat_quality(
    *,
    distinct_episode_count: int,
    example_count: int,
    scene_count: int,
) -> tuple[str, str]:
    if example_count <= 0:
        return "insufficient", "RP 예시 데이터 없음"
    if scene_count <= 0:
        return "insufficient", "캐릭터 장면 데이터 없음"
    if (
        distinct_episode_count >= MAIN_CHARACTER_CHAT_GOOD_MIN_DISTINCT_EPISODES
        and example_count >= MAIN_CHARACTER_CHAT_GOOD_MIN_EXAMPLES
        and scene_count >= MAIN_CHARACTER_CHAT_GOOD_MIN_SCENES
    ):
        return "good", "회차·RP 예시·장면 데이터 충분"
    return "normal", "대화 가능, 추가 재료 수집 중"


def _normalize_aliases(raw_aliases) -> list[str]:
    aliases: list[str] = []
    if not isinstance(raw_aliases, list):
        return aliases
    for raw_alias in raw_aliases:
        alias = str(raw_alias or "").strip()
        if alias and alias not in aliases:
            aliases.append(alias)
    return aliases


def _extract_summary_payload(raw_summary) -> dict:
    if isinstance(raw_summary, dict):
        return raw_summary
    return _extract_websochat_json_object(str(raw_summary or "")) or {}


def _normalize_text_list(value) -> list[str]:
    values = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for item in values:
        text_value = str(item or "").strip()
        if text_value and text_value not in normalized:
            normalized.append(text_value)
    return normalized


def _parse_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _scene_contains_character(scene: dict, character_scope_key: str) -> bool:
    participants = scene.get("participants") or scene.get("characters") or []
    if not isinstance(participants, list):
        return False
    for participant in participants:
        if isinstance(participant, dict):
            scope_key = participant.get("scope_key") or participant.get("character_key")
        else:
            scope_key = participant
        if str(scope_key or "").strip() == character_scope_key:
            return True
    return False


def _extract_scene_excerpt(
    *,
    chunk_rows,
    char_start: int,
    char_end: int,
) -> str:
    if char_end <= char_start:
        return ""

    excerpt_parts: list[str] = []
    for row in sorted(chunk_rows, key=lambda item: int(dict(item).get("charStart") or 0)):
        row_data = dict(row)
        chunk_start = int(row_data.get("charStart") or 0)
        chunk_text = str(row_data.get("text") or "")
        chunk_end = int(row_data.get("charEnd") or (chunk_start + len(chunk_text)))
        overlap_start = max(char_start, chunk_start)
        overlap_end = min(char_end, chunk_end)
        if overlap_end <= overlap_start:
            continue
        excerpt_parts.append(
            chunk_text[overlap_start - chunk_start : overlap_end - chunk_start]
        )

    return "".join(excerpt_parts).strip()[:CHARACTER_CHAT_PREVIEW_EXCERPT_MAX_CHARS]


def build_character_chat_preview_payload(
    *,
    character_scope_key: str,
    profile_row,
    scene_row,
    chunk_rows,
) -> dict | None:
    profile_data = dict(profile_row)
    scene_data = dict(scene_row)
    inventory = _extract_summary_payload(profile_data.get("inventorySummaryText"))
    profile = _extract_summary_payload(profile_data.get("profileSummaryText"))
    scene_payload = _extract_summary_payload(scene_data.get("sceneSummaryText"))
    scenes = scene_payload.get("scenes")
    if not isinstance(scenes, list):
        return None

    matching_scenes: list[tuple[int, int, int, dict]] = []
    for scene in scenes:
        if not isinstance(scene, dict) or not _scene_contains_character(
            scene, character_scope_key
        ):
            continue
        scene_index = _parse_int(scene.get("scene_index") or 0)
        char_start = _parse_int(scene.get("char_start") or 0)
        char_end = _parse_int(scene.get("char_end") or 0)
        if scene_index is None or char_start is None or char_end is None:
            continue
        matching_scenes.append((scene_index, char_start, char_end, scene))
    if not matching_scenes:
        return None
    _, char_start, char_end, selected_scene = max(
        matching_scenes,
        key=lambda scene_data: scene_data[0],
    )
    scene_excerpt = _extract_scene_excerpt(
        chunk_rows=chunk_rows,
        char_start=char_start,
        char_end=char_end,
    )
    if not scene_excerpt:
        return None

    episode_summary_raw = scene_data.get("episodeSummaryText")
    episode_summary_payload = _extract_summary_payload(episode_summary_raw)
    episode_summary = str(
        episode_summary_payload.get("summary")
        or episode_summary_payload.get("episode_summary")
        or episode_summary_raw
        or ""
    ).strip()
    speech_style = profile.get("speech_style")
    if not isinstance(speech_style, dict):
        speech_style = {}

    return {
        "episodeNo": int(scene_data.get("episodeNo") or 0),
        "episodeTitle": str(scene_data.get("episodeTitle") or "").strip(),
        "episodeSummary": episode_summary,
        "roleLabel": str(
            profile.get("role_label") or inventory.get("work_role") or ""
        ).strip(),
        "aliases": _normalize_aliases(inventory.get("aliases")),
        "personalityCore": _normalize_text_list(profile.get("personality_core")),
        "speechStyle": {
            "tone": _normalize_text_list(speech_style.get("tone")),
            "formality": str(speech_style.get("formality") or "").strip(),
            "sentenceLength": str(
                speech_style.get("sentence_length") or ""
            ).strip(),
        },
        "sceneSummary": str(selected_scene.get("scene_gist") or "").strip(),
        "sceneExcerpt": scene_excerpt,
    }


def _canonical_character_scope_key_sql(inventory_alias: str) -> str:
    return f"""COALESCE(
        NULLIF(TRIM(JSON_UNQUOTE(JSON_EXTRACT(
            {inventory_alias}.summary_text, '$.canonical_character_key'
        ))), ''),
        {inventory_alias}.scope_key
    )"""


def _chat_ready_rp_assets_predicate(inventory_alias: str) -> str:
    canonical_scope_key = _canonical_character_scope_key_sql(inventory_alias)
    return f"""
        AND EXISTS (
            SELECT 1
            FROM tb_story_agent_context_summary profile
            WHERE profile.product_id = {inventory_alias}.product_id
              AND profile.scope_key = {canonical_scope_key}
              AND profile.summary_type = 'character_rp_profile'
              AND profile.is_active = 'Y'
              AND JSON_VALID(profile.summary_text)
              AND JSON_UNQUOTE(JSON_EXTRACT(
                  profile.summary_text, '$.character_key'
              )) = {canonical_scope_key}
        )
        AND EXISTS (
            SELECT 1
            FROM tb_story_agent_context_summary examples
            WHERE examples.product_id = {inventory_alias}.product_id
              AND examples.scope_key = {canonical_scope_key}
              AND examples.summary_type = 'character_rp_examples'
              AND examples.is_active = 'Y'
              AND JSON_VALID(examples.summary_text)
              AND JSON_TYPE(JSON_EXTRACT(
                  examples.summary_text, '$.examples'
              )) = 'ARRAY'
              AND JSON_LENGTH(JSON_EXTRACT(
                  examples.summary_text, '$.examples'
              )) > 0
              AND JSON_UNQUOTE(JSON_EXTRACT(
                  examples.summary_text, '$.character_key'
              )) = {canonical_scope_key}
              AND EXISTS (
                  SELECT 1
                  FROM JSON_TABLE(
                      examples.summary_text,
                      '$.examples[*]' COLUMNS (
                          episode_no INT PATH '$.episode_no'
                      )
                  ) AS eligible_rp_example
                  WHERE eligible_rp_example.episode_no BETWEEN 0 AND 1
              )
        )
    """


def _character_chat_first_episode_readiness_predicate(
    *, product_id_sql: str, character_scope_key_sql: str
) -> str:
    return f"""
        AND EXISTS (
            SELECT 1
            FROM tb_story_agent_context_summary eligible_scene
            INNER JOIN tb_product_episode eligible_episode
                ON eligible_episode.product_id = eligible_scene.product_id
               AND eligible_episode.episode_no = eligible_scene.episode_to
            INNER JOIN tb_story_agent_context_doc eligible_doc
                ON eligible_doc.product_id = eligible_scene.product_id
               AND eligible_doc.episode_id = eligible_episode.episode_id
               AND eligible_doc.episode_no = eligible_scene.episode_to
               AND eligible_doc.is_active = 'Y'
            WHERE eligible_scene.product_id = {product_id_sql}
              AND eligible_scene.summary_type = 'episode_scene_extraction'
              AND eligible_scene.is_active = 'Y'
              AND eligible_scene.episode_to = 1
              AND JSON_VALID(eligible_scene.summary_text)
              AND LOWER(TRIM(JSON_UNQUOTE(JSON_EXTRACT(
                  eligible_scene.summary_text, '$.status'
              )))) IN ('ok', 'partial')
              AND JSON_TYPE(JSON_EXTRACT(
                  eligible_scene.summary_text, '$.scenes'
              )) = 'ARRAY'
              AND EXISTS (
                  SELECT 1
                  FROM JSON_TABLE(
                      eligible_scene.summary_text,
                      '$.scenes[*]' COLUMNS (
                          scene_gist VARCHAR(160) PATH '$.scene_gist',
                          NESTED PATH '$.participants[*]' COLUMNS (
                              participant_scope_key VARCHAR(80) PATH '$.scope_key'
                          ),
                          NESTED PATH '$.action_ownership[*]' COLUMNS (
                              action_scope_key VARCHAR(80) PATH '$.actor_scope_key'
                          )
                      )
                  ) AS eligible_scene_row
                  WHERE TRIM(COALESCE(eligible_scene_row.scene_gist, '')) <> ''
                    AND (
                        eligible_scene_row.participant_scope_key =
                            {character_scope_key_sql}
                        OR eligible_scene_row.action_scope_key =
                            {character_scope_key_sql}
                    )
              )
              AND eligible_episode.use_yn = 'Y'
              AND eligible_episode.open_yn = 'Y'
              AND COALESCE(eligible_episode.price_type, 'free') = 'free'
              AND EXISTS (
                  SELECT 1
                  FROM tb_story_agent_context_chunk eligible_chunk
                  WHERE eligible_chunk.context_doc_id = eligible_doc.context_doc_id
              )
              AND EXISTS (
                  SELECT 1
                  FROM tb_story_agent_context_summary eligible_episode_summary
                  WHERE eligible_episode_summary.product_id = eligible_scene.product_id
                    AND eligible_episode_summary.summary_type = 'episode_summary'
                    AND eligible_episode_summary.is_active = 'Y'
                    AND eligible_episode_summary.episode_to = 1
                    AND eligible_episode_summary.scope_key =
                        CONCAT('episode:', eligible_episode.episode_id)
                    AND TRIM(COALESCE(eligible_episode_summary.summary_text, '')) <> ''
              )
        )
    """


def _public_character_slot_eligibility_predicate(
    *, slot_alias: str, product_alias: str
) -> str:
    return f"""
        AND {slot_alias}.use_yn = 'Y'
        AND {slot_alias}.deleted_yn = 'N'
        AND {slot_alias}.publish_start_date <= NOW()
        AND ({slot_alias}.publish_end_date IS NULL OR {slot_alias}.publish_end_date > NOW())
        AND {product_alias}.open_yn = 'Y'
        AND COALESCE({product_alias}.blind_yn, 'N') = 'N'
        AND COALESCE({product_alias}.ai_content_service_enabled_yn, 'N') = 'Y'
        {_main_character_product_policy_sql(product_alias=product_alias, episode_alias="pe")}
        AND EXISTS (
            SELECT 1
            FROM tb_story_agent_context_summary inventory
            WHERE inventory.product_id = {slot_alias}.product_id
              AND inventory.scope_key = {slot_alias}.character_scope_key
              AND inventory.summary_type = 'character_inventory_v3'
              AND inventory.is_active = 'Y'
              AND JSON_VALID(inventory.summary_text)
              AND JSON_UNQUOTE(
                  JSON_EXTRACT(
                      inventory.summary_text,
                      '$.public_slot_eligible'
                  )
              ) = 'true'
              AND JSON_UNQUOTE(
                  JSON_EXTRACT(
                      inventory.summary_text,
                      '$.public_chat_eligible'
                  )
              ) = 'true'
              AND JSON_UNQUOTE(
                  JSON_EXTRACT(
                      inventory.summary_text,
                      '$.display_safety.status'
                  )
              ) = 'pass'
              {_chat_ready_rp_assets_predicate("inventory")}
        )
        {_character_chat_first_episode_readiness_predicate(
            product_id_sql=f"{slot_alias}.product_id",
            character_scope_key_sql=f"{slot_alias}.character_scope_key",
        )}
    """


def _extract_eligible_character_payload(row) -> dict | None:
    row_data = dict(row)
    payload = _extract_websochat_json_object(
        str(row_data.get("summaryText") or row_data.get("summary_text") or "")
    )
    if not payload:
        return None
    display_safety = payload.get("display_safety")
    if not isinstance(display_safety, dict):
        return None
    if str(display_safety.get("status") or "").strip().lower() != "pass":
        return None
    if payload.get("public_chat_eligible") is not True:
        return None
    if payload.get("public_slot_eligible") is not True:
        return None
    return payload


def _character_priority(payload: dict) -> tuple[object, ...]:
    return (
        0
        if str(payload.get("work_role") or "").strip().lower()
        == "main_protagonist"
        or payload.get("is_protagonist") is True
        else 1,
        -int(payload.get("distinct_episode_count") or 0),
        -int(payload.get("voice_evidence_count") or 0),
        str(payload.get("display_name") or "").strip(),
    )


def extract_eligible_main_character_roster(rows) -> list[dict]:
    roster: list[tuple[tuple[object, ...], dict]] = []
    seen_scope_keys: set[str] = set()
    for row in rows:
        row_data = dict(row)
        payload = _extract_eligible_character_payload(row_data)
        if not payload:
            continue

        scope_key = str(payload.get("canonical_character_key") or "").strip()
        display_name = str(payload.get("display_name") or "").strip()
        if not scope_key or not display_name or scope_key in seen_scope_keys:
            continue
        seen_scope_keys.add(scope_key)
        distinct_episode_count = int(payload.get("distinct_episode_count") or 0)
        example_count = int(row_data.get("exampleCount") or 0)
        scene_count = int(row_data.get("sceneCount") or 0)
        chat_quality, quality_reason = classify_main_character_chat_quality(
            distinct_episode_count=distinct_episode_count,
            example_count=example_count,
            scene_count=scene_count,
        )
        roster.append(
            (
                _character_priority(payload),
                {
                    "scopeKey": scope_key,
                    "displayName": display_name,
                    "aliases": _normalize_aliases(payload.get("aliases")),
                    "distinctEpisodeCount": distinct_episode_count,
                    "exampleCount": example_count,
                    "sceneCount": scene_count,
                    "chatQuality": chat_quality,
                    "qualityReason": quality_reason,
                },
            )
        )
    return [
        item
        for _, item in sorted(roster, key=lambda candidate: candidate[0])[
            :MAIN_CHARACTER_SLOT_MAX_CHARACTERS_PER_PRODUCT
        ]
    ]


def build_main_character_chat_quality_by_product(candidate_rows) -> dict[int, str]:
    candidates_by_product: dict[
        int, list[tuple[tuple[object, ...], dict[str, object]]]
    ] = defaultdict(list)
    seen_scope_keys: set[tuple[int, str]] = set()
    for row in candidate_rows:
        row_data = dict(row)
        product_id = int(row_data.get("productId") or 0)
        payload = _extract_eligible_character_payload(row_data)
        if not product_id or not payload:
            continue
        scope_key = str(payload.get("canonical_character_key") or "").strip()
        display_name = str(payload.get("display_name") or "").strip()
        if (
            not scope_key
            or not display_name
            or (product_id, scope_key) in seen_scope_keys
        ):
            continue
        seen_scope_keys.add((product_id, scope_key))
        candidates_by_product[product_id].append(
            (
                _character_priority(payload),
                {
                    "scopeKey": scope_key,
                    "distinctEpisodeCount": int(
                        payload.get("distinct_episode_count") or 0
                    ),
                    "exampleCount": int(row_data.get("exampleCount") or 0),
                    "sceneCount": int(row_data.get("sceneCount") or 0),
                },
            )
        )

    quality_by_product: dict[int, str] = {}
    severity = {"good": 0, "normal": 1, "insufficient": 2}
    for product_id, candidates in candidates_by_product.items():
        candidate_qualities: list[str] = []
        for _, candidate in sorted(candidates, key=lambda item: item[0])[
            :MAIN_CHARACTER_SLOT_MAX_CHARACTERS_PER_PRODUCT
        ]:
            quality, _ = classify_main_character_chat_quality(
                distinct_episode_count=int(candidate["distinctEpisodeCount"]),
                example_count=int(candidate["exampleCount"]),
                scene_count=int(candidate["sceneCount"]),
            )
            candidate_qualities.append(quality)

        if candidate_qualities:
            quality_by_product[product_id] = max(
                candidate_qualities, key=severity.__getitem__
            )
    return quality_by_product


async def _load_eligible_main_character_roster(
    product_id: int, db: AsyncSession
) -> list[dict]:
    result = await db.execute(
        text(f"""
            SELECT
                sacs.scope_key AS scopeKey,
                sacs.summary_text AS summaryText,
                COALESCE((
                    SELECT MAX(JSON_LENGTH(JSON_EXTRACT(
                        examples.summary_text, '$.examples'
                    )))
                    FROM tb_story_agent_context_summary examples
                    WHERE examples.product_id = sacs.product_id
                      AND examples.scope_key = COALESCE(
                          NULLIF(TRIM(JSON_UNQUOTE(JSON_EXTRACT(
                              sacs.summary_text, '$.canonical_character_key'
                          ))), ''),
                          sacs.scope_key
                      )
                      AND examples.summary_type = 'character_rp_examples'
                      AND examples.is_active = 'Y'
                      AND JSON_VALID(examples.summary_text)
                      AND JSON_TYPE(JSON_EXTRACT(
                          examples.summary_text, '$.examples'
                      )) = 'ARRAY'
                ), 0) AS exampleCount,
                (
                    SELECT COUNT(*)
                    FROM tb_story_agent_context_summary scene
                    WHERE scene.product_id = sacs.product_id
                      AND scene.summary_type = 'episode_scene_extraction'
                      AND scene.is_active = 'Y'
                      AND LOCATE(
                          JSON_QUOTE(COALESCE(
                              NULLIF(TRIM(JSON_UNQUOTE(JSON_EXTRACT(
                                  sacs.summary_text, '$.canonical_character_key'
                              ))), ''),
                              sacs.scope_key
                          )),
                          scene.summary_text
                      ) > 0
                ) AS sceneCount
            FROM tb_story_agent_context_summary sacs
            INNER JOIN tb_product p ON p.product_id = sacs.product_id
            WHERE sacs.product_id = :product_id
              AND sacs.summary_type = 'character_inventory_v3'
              AND sacs.is_active = 'Y'
              AND JSON_VALID(sacs.summary_text)
              AND JSON_UNQUOTE(JSON_EXTRACT(
                  sacs.summary_text, '$.public_slot_eligible'
              )) = 'true'
              AND JSON_UNQUOTE(JSON_EXTRACT(
                  sacs.summary_text, '$.public_chat_eligible'
              )) = 'true'
              AND LOWER(TRIM(JSON_UNQUOTE(JSON_EXTRACT(
                  sacs.summary_text, '$.display_safety.status'
              )))) = 'pass'
              AND p.open_yn = 'Y'
              AND COALESCE(p.blind_yn, 'N') = 'N'
              AND COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'
              {_main_character_product_policy_sql(product_alias="p", episode_alias="pe")}
              {_chat_ready_rp_assets_predicate("sacs")}
              {_character_chat_first_episode_readiness_predicate(
                  product_id_sql="sacs.product_id",
                  character_scope_key_sql=_canonical_character_scope_key_sql("sacs"),
              )}
            ORDER BY sacs.summary_id DESC
        """),
        {"product_id": product_id},
    )
    return extract_eligible_main_character_roster(result.mappings().all())


async def get_admin_main_character_roster(product_id: int, db: AsyncSession):
    return {"data": await _load_eligible_main_character_roster(product_id, db)}


async def _ensure_character_slot_selection_eligible(
    *,
    product_id: int,
    character_scope_key: str,
    db: AsyncSession,
) -> str:
    roster = await _load_eligible_main_character_roster(product_id, db)
    selected = next(
        (item for item in roster if item["scopeKey"] == character_scope_key),
        None,
    )
    if selected is None:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="메인 캐릭터 카드에 사용할 수 없는 인물입니다.",
        )
    if selected["chatQuality"] == "insufficient":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=f"품질 미달 캐릭터는 공개할 수 없습니다. ({selected['qualityReason']})",
        )
    return selected["displayName"]


async def _ensure_character_image_file(
    *, character_image_file_id: int, db: AsyncSession
) -> None:
    result = await db.execute(
        text("""
            SELECT cf.file_group_id
            FROM tb_common_file cf
            INNER JOIN tb_common_file_item cfi
                ON cfi.file_group_id = cf.file_group_id
               AND cfi.use_yn = 'Y'
            WHERE cf.file_group_id = :character_image_file_id
              AND cf.group_type = 'character'
              AND cf.use_yn = 'Y'
            LIMIT 1
        """),
        {"character_image_file_id": character_image_file_id},
    )
    if result.mappings().one_or_none() is None:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="유효하지 않은 캐릭터 이미지 파일입니다.",
        )


def _build_public_character_slots_query(
    *, include_catalog_readiness: bool = False
) -> str:
    catalog_readiness_columns = ""
    if include_catalog_readiness:
        catalog_readiness_columns = f""",
            {_chat_ready_episode_count_sql("mcs.product_id")}
                AS _chatReadyEpisodeCount,
            {_chat_total_episode_count_sql("mcs.product_id")}
                AS _chatTotalEpisodeCount"""
    return f"""
        SELECT
            mcs.main_character_slot_id AS characterSlotId,
            mcs.product_id AS productId,
            mcs.character_scope_key AS characterScopeKey,
            mcs.character_name AS characterName,
            {get_file_path_sub_query("mcs.character_image_file_id", "characterImagePath", "character")},
            mcs.card_order AS cardOrder,
            p.title AS productTitle,
            p.author_name AS authorNickname,
            LEAST(
                COALESCE(sacp.ready_episode_count, 0),
                COALESCE((
                    SELECT MAX(public_episode.episode_no)
                    FROM tb_product_episode public_episode
                    WHERE public_episode.product_id = mcs.product_id
                      AND public_episode.use_yn = 'Y'
                      AND public_episode.open_yn = 'Y'
                ), 0)
            ) AS syncedLatestEpisodeNo,
            mcs.publish_start_date AS publishStartAt,
            mcs.publish_end_date AS publishEndAt,
            mcs.created_date AS createdDate,
            mcs.updated_date AS updatedDate
            {catalog_readiness_columns}
        FROM tb_main_character_slot mcs
        INNER JOIN tb_product p ON p.product_id = mcs.product_id
        LEFT JOIN tb_story_agent_context_product sacp
            ON sacp.product_id = mcs.product_id
        WHERE 1 = 1
          {_public_character_slot_eligibility_predicate(slot_alias="mcs", product_alias="p")}
          AND (:adult_yn = 'Y' OR p.ratings_code != 'adult')
        ORDER BY mcs.card_order ASC, mcs.main_character_slot_id ASC
    """


def build_public_main_character_slots_query() -> str:
    return f"{_build_public_character_slots_query().rstrip()}\n        LIMIT 12\n"


def build_public_character_catalog_query() -> str:
    return _build_public_character_slots_query(include_catalog_readiness=True)


async def get_public_main_character_slots(*, adult_yn: str, db: AsyncSession):
    result = await db.execute(
        text(build_public_main_character_slots_query()),
        {"adult_yn": adult_yn},
    )
    return {"data": [dict(row) for row in result.mappings().all()]}


async def get_public_character_catalog(
    *,
    adult_yn: str,
    kc_user_id: str | None,
    db: AsyncSession,
):
    result = await db.execute(
        text(build_public_character_catalog_query()),
        {"adult_yn": adult_yn},
    )
    catalog_items = [dict(row) for row in result.mappings().all()]
    for item in catalog_items:
        ready_episode_count = int(item.pop("_chatReadyEpisodeCount", 0) or 0)
        total_episode_count = int(item.pop("_chatTotalEpisodeCount", 0) or 0)
        item["fullReady"] = (
            total_episode_count > 0 and ready_episode_count >= total_episode_count
        )
        item["readinessCoverageRatio"] = (
            min(1.0, ready_episode_count / total_episode_count)
            if total_episode_count > 0
            else 0.0
        )
        item["lastViewedEpisodeNo"] = None
        item["lastViewedAt"] = None

    product_ids = sorted(
        {
            int(item["productId"])
            for item in catalog_items
            if int(item.get("productId") or 0) > 0
        }
    )
    if not kc_user_id or not product_ids:
        return {"data": catalog_items}

    progress_result = await db.execute(
        text("""
            SELECT
                usage_row.product_id AS productId,
                MAX(pe.episode_no) AS lastViewedEpisodeNo,
                MAX(usage_row.updated_date) AS lastViewedAt
            FROM tb_user_product_usage usage_row
            INNER JOIN tb_product_episode pe
                ON pe.episode_id = usage_row.episode_id
               AND pe.product_id = usage_row.product_id
            INNER JOIN tb_user u ON u.user_id = usage_row.user_id
            WHERE u.kc_user_id = :kc_user_id
              AND u.use_yn = 'Y'
              AND usage_row.use_yn = 'Y'
              AND pe.use_yn = 'Y'
              AND pe.open_yn = 'Y'
              AND usage_row.product_id IN :product_ids
            GROUP BY usage_row.product_id
        """).bindparams(bindparam("product_ids", expanding=True)),
        {
            "kc_user_id": kc_user_id,
            "product_ids": product_ids,
        },
    )
    progress_by_product: dict[int, dict] = {}
    for row in progress_result.mappings().all():
        row_data = dict(row)
        if row_data.get("productId") is not None:
            progress_by_product[int(row_data["productId"])] = row_data
    for item in catalog_items:
        progress = progress_by_product.get(int(item.get("productId") or 0))
        if progress:
            item["lastViewedEpisodeNo"] = progress.get("lastViewedEpisodeNo")
            item["lastViewedAt"] = progress.get("lastViewedAt")

    return {"data": catalog_items}


async def get_public_character_chat_preview(
    *,
    product_id: int,
    character_scope_key: str,
    episode_no: int,
    db: AsyncSession,
):
    profile_result = await db.execute(
        text(f"""
            SELECT
                inventory.summary_text AS inventorySummaryText,
                profile.summary_text AS profileSummaryText
            FROM tb_main_character_slot mcs
            INNER JOIN tb_product p ON p.product_id = mcs.product_id
            INNER JOIN tb_story_agent_context_summary inventory
                ON inventory.product_id = mcs.product_id
               AND inventory.scope_key = mcs.character_scope_key
               AND inventory.summary_type = 'character_inventory_v3'
               AND inventory.is_active = 'Y'
               AND JSON_VALID(inventory.summary_text)
            INNER JOIN tb_story_agent_context_summary profile
                ON profile.product_id = mcs.product_id
               AND profile.scope_key = {_canonical_character_scope_key_sql("inventory")}
               AND profile.summary_type = 'character_rp_profile'
               AND profile.is_active = 'Y'
               AND JSON_VALID(profile.summary_text)
            WHERE mcs.product_id = :product_id
              AND mcs.character_scope_key = :character_scope_key
              {_public_character_slot_eligibility_predicate(slot_alias="mcs", product_alias="p")}
            ORDER BY inventory.summary_id DESC, profile.summary_id DESC
            LIMIT 1
        """),
        {
            "product_id": product_id,
            "character_scope_key": character_scope_key,
        },
    )
    profile_row = profile_result.mappings().one_or_none()
    if profile_row is None:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="공개 가능한 캐릭터 정보를 찾을 수 없습니다.",
        )

    scene_result = await db.execute(
        text("""
            SELECT
                pe.episode_id AS episodeId,
                pe.episode_no AS episodeNo,
                COALESCE(pe.episode_title, '') AS episodeTitle,
                scene.summary_text AS sceneSummaryText,
                COALESCE((
                    SELECT episode_summary.summary_text
                    FROM tb_story_agent_context_summary episode_summary
                    WHERE episode_summary.product_id = scene.product_id
                      AND episode_summary.scope_key =
                          CONCAT('episode:', pe.episode_id)
                      AND episode_summary.summary_type = 'episode_summary'
                      AND episode_summary.is_active = 'Y'
                      AND episode_summary.episode_to = pe.episode_no
                    ORDER BY episode_summary.summary_id DESC
                    LIMIT 1
                ), '') AS episodeSummaryText
            FROM tb_story_agent_context_summary scene
            INNER JOIN tb_product_episode pe
                ON pe.product_id = scene.product_id
               AND pe.episode_no = scene.episode_to
            WHERE scene.product_id = :product_id
              AND scene.summary_type = 'episode_scene_extraction'
              AND scene.is_active = 'Y'
              AND scene.episode_to <= :episode_no
              AND LOCATE(JSON_QUOTE(:character_scope_key), scene.summary_text) > 0
              AND pe.use_yn = 'Y'
              AND pe.open_yn = 'Y'
              AND COALESCE(pe.price_type, 'free') = 'free'
            ORDER BY scene.episode_to DESC, scene.summary_id DESC
            LIMIT 5
        """),
        {
            "product_id": product_id,
            "character_scope_key": character_scope_key,
            "episode_no": episode_no,
        },
    )

    for scene_row in scene_result.mappings().all():
        scene_data = dict(scene_row)
        chunk_result = await db.execute(
            text("""
                SELECT
                    chunk.char_start AS charStart,
                    chunk.char_end AS charEnd,
                    chunk.text AS text
                FROM tb_story_agent_context_chunk chunk
                INNER JOIN tb_story_agent_context_doc doc
                    ON doc.context_doc_id = chunk.context_doc_id
                   AND doc.is_active = 'Y'
                WHERE chunk.product_id = :product_id
                  AND chunk.episode_id = :episode_id
                ORDER BY chunk.char_start ASC, chunk.chunk_no ASC
            """),
            {
                "product_id": product_id,
                "episode_id": int(scene_data.get("episodeId") or 0),
            },
        )
        payload = build_character_chat_preview_payload(
            character_scope_key=character_scope_key,
            profile_row=profile_row,
            scene_row=scene_data,
            chunk_rows=chunk_result.mappings().all(),
        )
        if payload:
            return {"data": payload}

    raise CustomResponseException(
        status_code=status.HTTP_404_NOT_FOUND,
        message="선택한 회차 범위에서 공개 가능한 장면을 찾을 수 없습니다.",
    )


async def get_admin_main_character_slots(
    *, page: int, count_per_page: int, db: AsyncSession
):
    count_result = await db.execute(
        text("""
            SELECT COUNT(*) AS total_count
            FROM tb_main_character_slot
            WHERE deleted_yn = 'N'
        """),
        {},
    )
    count_row = count_result.mappings().first()
    total_count = int(dict(count_row or {}).get("total_count") or 0)
    limit_clause, limit_params = get_pagination_params(page, count_per_page)
    result = await db.execute(
        text(f"""
            SELECT
                mcs.main_character_slot_id AS characterSlotId,
                mcs.product_id AS productId,
                mcs.character_scope_key AS characterScopeKey,
                mcs.character_name AS characterName,
                {get_file_path_sub_query("mcs.character_image_file_id", "characterImagePath", "character")},
                mcs.card_order AS cardOrder,
                p.title AS productTitle,
                p.author_name AS authorNickname,
                mcs.publish_start_date AS publishStartAt,
                mcs.publish_end_date AS publishEndAt,
                mcs.created_date AS createdDate,
                mcs.updated_date AS updatedDate,
                CASE WHEN
                    p.open_yn = 'Y'
                    AND COALESCE(p.blind_yn, 'N') = 'N'
                    AND COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'
                    {_main_character_product_policy_sql(product_alias="p", episode_alias="pe")}
                    AND EXISTS (
                        SELECT 1
                        FROM tb_story_agent_context_summary inventory
                        WHERE inventory.product_id = mcs.product_id
                          AND inventory.scope_key = mcs.character_scope_key
                          AND inventory.summary_type = 'character_inventory_v3'
                          AND inventory.is_active = 'Y'
                          AND JSON_VALID(inventory.summary_text)
                          AND JSON_UNQUOTE(JSON_EXTRACT(
                              inventory.summary_text, '$.public_slot_eligible'
                          )) = 'true'
                          AND JSON_UNQUOTE(JSON_EXTRACT(
                              inventory.summary_text, '$.public_chat_eligible'
                          )) = 'true'
                          AND JSON_UNQUOTE(JSON_EXTRACT(
                              inventory.summary_text, '$.display_safety.status'
                          )) = 'pass'
                          {_chat_ready_rp_assets_predicate("inventory")}
                    )
                    {_character_chat_first_episode_readiness_predicate(
                        product_id_sql="mcs.product_id",
                        character_scope_key_sql="mcs.character_scope_key",
                    )}
                THEN 1 ELSE 0 END AS publicEligible
            FROM tb_main_character_slot mcs
            INNER JOIN tb_product p ON p.product_id = mcs.product_id
            WHERE mcs.deleted_yn = 'N'
            ORDER BY mcs.card_order ASC, mcs.main_character_slot_id ASC
            {limit_clause}
        """),
        limit_params,
    )
    return build_paginated_response(
        result.mappings().all(), total_count, page, count_per_page
    )


async def search_admin_main_character_slot_products(
    *, search_word: str | None, limit: int, db: AsyncSession
):
    normalized_search_word = (search_word or "").strip()
    result = await db.execute(
        text(f"""
            SELECT
                p.product_id AS productId,
                p.title,
                p.author_name AS authorNickname,
                cf.file_path AS coverImagePath,
                episode_stats.open_episode_count AS openEpisodeCount
            FROM tb_product p
            INNER JOIN (
                SELECT
                    pe.product_id,
                    COUNT(*) AS open_episode_count,
                    MIN({build_public_episode_opened_at_sql("pe")}) AS first_public_episode_at
                FROM tb_product_episode pe
                WHERE pe.use_yn = 'Y' AND pe.open_yn = 'Y'
                GROUP BY pe.product_id
            ) episode_stats ON episode_stats.product_id = p.product_id
            LEFT JOIN (
                SELECT cf.file_group_id, cfi.file_path
                FROM tb_common_file cf
                INNER JOIN tb_common_file_item cfi
                    ON cfi.file_group_id = cf.file_group_id
                   AND cfi.use_yn = 'Y'
                WHERE cf.use_yn = 'Y' AND cf.group_type = 'cover'
            ) cf ON cf.file_group_id = p.thumbnail_file_id
            WHERE p.open_yn = 'Y'
              AND COALESCE(p.blind_yn, 'N') = 'N'
              AND COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'
              AND p.status_code = 'ongoing'
              AND episode_stats.open_episode_count >= :minimum_open_episode_count
              AND episode_stats.first_public_episode_at >= :first_public_episode_at
              AND EXISTS (
                  SELECT 1
                  FROM tb_story_agent_context_summary sacs
                  WHERE sacs.product_id = p.product_id
                    AND sacs.summary_type = 'character_inventory_v3'
                    AND sacs.is_active = 'Y'
                    AND JSON_UNQUOTE(
                        JSON_EXTRACT(sacs.summary_text, '$.public_slot_eligible')
                    ) = 'true'
                    AND JSON_UNQUOTE(
                        JSON_EXTRACT(sacs.summary_text, '$.public_chat_eligible')
                    ) = 'true'
                    AND JSON_UNQUOTE(
                        JSON_EXTRACT(sacs.summary_text, '$.display_safety.status')
                    ) = 'pass'
                    {_chat_ready_rp_assets_predicate("sacs")}
                    {_character_chat_first_episode_readiness_predicate(
                        product_id_sql="sacs.product_id",
                        character_scope_key_sql=_canonical_character_scope_key_sql("sacs"),
                    )}
              )
              AND (:search_word = '%%' OR p.title LIKE :search_word)
            ORDER BY p.updated_date DESC, p.product_id DESC
            LIMIT :limit_count
        """),
        {
            "search_word": f"%{normalized_search_word}%",
            "limit_count": limit,
            "minimum_open_episode_count": MAIN_CHARACTER_SLOT_MINIMUM_OPEN_EPISODE_COUNT,
            "first_public_episode_at": CHARACTER_CHAT_FIRST_PUBLIC_EPISODE_AT,
        },
    )
    return {"data": [dict(row) for row in result.mappings().all()]}


def _admin_chat_ready_product_where_clause() -> str:
    return f"""
        WHERE p.open_yn = 'Y'
          AND COALESCE(p.blind_yn, 'N') = 'N'
          AND COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'
          {build_correlated_character_chat_product_policy_sql(
              product_alias="p",
              episode_alias="pe",
              minimum_open_episode_count_sql=":minimum_open_episode_count",
              first_public_episode_at_sql=":first_public_episode_at",
          )}
          AND (
              :search_word = '%%'
              OR p.title LIKE :search_word
              OR p.author_name LIKE :search_word
          )
          AND EXISTS (
              SELECT 1
              FROM tb_story_agent_context_summary inventory
              WHERE inventory.product_id = p.product_id
                AND inventory.summary_type = 'character_inventory_v3'
                AND inventory.is_active = 'Y'
                AND JSON_VALID(inventory.summary_text)
                AND JSON_UNQUOTE(JSON_EXTRACT(
                    inventory.summary_text, '$.public_slot_eligible'
                )) = 'true'
                AND JSON_UNQUOTE(JSON_EXTRACT(
                    inventory.summary_text, '$.public_chat_eligible'
                )) = 'true'
                AND LOWER(TRIM(JSON_UNQUOTE(JSON_EXTRACT(
                    inventory.summary_text, '$.display_safety.status'
                )))) = 'pass'
                AND TRIM(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
                    inventory.summary_text, '$.canonical_character_key'
                )), '')) != ''
                AND TRIM(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
                    inventory.summary_text, '$.display_name'
                )), '')) != ''
                {_chat_ready_rp_assets_predicate("inventory")}
                {_character_chat_first_episode_readiness_predicate(
                    product_id_sql="inventory.product_id",
                    character_scope_key_sql=_canonical_character_scope_key_sql("inventory"),
                )}
          )
    """


async def _load_main_character_chat_quality(
    product_ids: list[int], db: AsyncSession
) -> dict[int, str]:
    if not product_ids:
        return {}

    candidate_query = text("""
        SELECT
            inventory.product_id AS productId,
            inventory.summary_text AS summaryText
        FROM tb_story_agent_context_summary inventory
        WHERE inventory.product_id IN :product_ids
          AND inventory.summary_type = 'character_inventory_v3'
          AND inventory.is_active = 'Y'
          AND JSON_VALID(inventory.summary_text)
          AND JSON_UNQUOTE(JSON_EXTRACT(
              inventory.summary_text, '$.public_slot_eligible'
          )) = 'true'
          AND JSON_UNQUOTE(JSON_EXTRACT(
              inventory.summary_text, '$.public_chat_eligible'
          )) = 'true'
          AND LOWER(TRIM(JSON_UNQUOTE(JSON_EXTRACT(
              inventory.summary_text, '$.display_safety.status'
          )))) = 'pass'
        ORDER BY inventory.product_id ASC, inventory.summary_id DESC
    """).bindparams(bindparam("product_ids", expanding=True))
    candidate_result = await db.execute(
        candidate_query,
        {"product_ids": product_ids},
    )

    asset_query = text("""
        SELECT
            product_id AS productId,
            scope_key AS scopeKey,
            summary_type AS summaryType,
            CASE
                WHEN summary_type = 'character_rp_examples'
                 AND JSON_TYPE(JSON_EXTRACT(summary_text, '$.examples')) = 'ARRAY'
                THEN JSON_LENGTH(JSON_EXTRACT(summary_text, '$.examples'))
                ELSE 0
            END AS exampleCount
        FROM tb_story_agent_context_summary
        WHERE product_id IN :product_ids
          AND summary_type IN ('character_rp_profile', 'character_rp_examples')
          AND is_active = 'Y'
          AND JSON_VALID(summary_text)
    """).bindparams(bindparam("product_ids", expanding=True))
    asset_result = await db.execute(asset_query, {"product_ids": product_ids})

    scene_query = text("""
        SELECT product_id AS productId, summary_text AS summaryText
        FROM tb_story_agent_context_summary
        WHERE product_id IN :product_ids
          AND summary_type = 'episode_scene_extraction'
          AND is_active = 'Y'
    """).bindparams(bindparam("product_ids", expanding=True))
    scene_result = await db.execute(scene_query, {"product_ids": product_ids})

    profile_keys: set[tuple[int, str]] = set()
    example_counts: dict[tuple[int, str], int] = defaultdict(int)
    for row in asset_result.mappings().all():
        row_data = dict(row)
        key = (
            int(row_data.get("productId") or 0),
            str(row_data.get("scopeKey") or "").strip(),
        )
        if not key[0] or not key[1]:
            continue
        if row_data.get("summaryType") == "character_rp_profile":
            profile_keys.add(key)
        elif row_data.get("summaryType") == "character_rp_examples":
            example_counts[key] = max(
                example_counts[key], int(row_data.get("exampleCount") or 0)
            )

    scene_texts: dict[int, list[str]] = defaultdict(list)
    for row in scene_result.mappings().all():
        row_data = dict(row)
        scene_texts[int(row_data.get("productId") or 0)].append(
            str(row_data.get("summaryText") or "")
        )

    enriched_candidates: list[dict] = []
    for row in candidate_result.mappings().all():
        row_data = dict(row)
        payload = _extract_eligible_character_payload(row_data)
        if not payload:
            continue
        product_id = int(row_data.get("productId") or 0)
        scope_key = str(payload.get("canonical_character_key") or "").strip()
        key = (product_id, scope_key)
        example_count = example_counts.get(key, 0)
        if key not in profile_keys or example_count <= 0:
            continue
        scope_token = json.dumps(scope_key, ensure_ascii=False)
        enriched_candidates.append(
            {
                **row_data,
                "exampleCount": example_count,
                "sceneCount": sum(
                    scope_token in scene_text
                    for scene_text in scene_texts.get(product_id, [])
                ),
            }
        )

    return build_main_character_chat_quality_by_product(
        enriched_candidates
    )


async def get_admin_main_character_slot_products(
    *,
    page: int,
    count_per_page: int,
    search_word: str | None,
    db: AsyncSession,
):
    normalized_search_word = (search_word or "").strip()
    params = {
        "search_word": f"%{normalized_search_word}%",
        "minimum_open_episode_count": MAIN_CHARACTER_SLOT_MINIMUM_OPEN_EPISODE_COUNT,
        "first_public_episode_at": CHARACTER_CHAT_FIRST_PUBLIC_EPISODE_AT,
    }
    where_clause = _admin_chat_ready_product_where_clause()

    count_result = await db.execute(
        text(f"SELECT COUNT(*) AS total_count FROM tb_product p {where_clause}"),
        params,
    )
    count_row = count_result.mappings().first()
    total_count = int(dict(count_row or {}).get("total_count") or 0)

    limit_clause, limit_params = get_pagination_params(page, count_per_page)
    result = await db.execute(
        text(f"""
            SELECT
                p.product_id AS productId,
                p.title,
                p.author_name AS authorNickname,
                cf.file_path AS coverImagePath,
                (
                    SELECT COUNT(*)
                    FROM tb_product_episode pe
                    WHERE pe.product_id = p.product_id
                      AND pe.use_yn = 'Y'
                      AND pe.open_yn = 'Y'
                ) AS openEpisodeCount
            FROM tb_product p
            LEFT JOIN (
                SELECT cf.file_group_id, cfi.file_path
                FROM tb_common_file cf
                INNER JOIN tb_common_file_item cfi
                    ON cfi.file_group_id = cf.file_group_id
                   AND cfi.use_yn = 'Y'
                WHERE cf.use_yn = 'Y' AND cf.group_type = 'cover'
            ) cf ON cf.file_group_id = p.thumbnail_file_id
            {where_clause}
            ORDER BY p.updated_date DESC, p.product_id DESC
            {limit_clause}
        """),
        {**params, **limit_params},
    )
    products = [dict(row) for row in result.mappings().all()]
    quality_by_product = await _load_main_character_chat_quality(
        [int(product["productId"]) for product in products],
        db,
    )
    for product in products:
        product["chatQuality"] = quality_by_product.get(
            int(product["productId"]), "insufficient"
        )
    return build_paginated_response(products, total_count, page, count_per_page)


def _main_character_slot_params(
    req_body,
    *,
    character_name: str,
    admin_user_id: int | None,
) -> dict:
    return {
        "product_id": req_body.product_id,
        "character_scope_key": req_body.character_scope_key,
        "character_name": character_name,
        "character_image_file_id": req_body.character_image_file_id,
        "card_order": req_body.card_order,
        "publish_start_at": getattr(req_body, "publish_start_at", None),
        "publish_end_at": getattr(req_body, "publish_end_at", None),
        "created_id": admin_user_id,
        "updated_id": admin_user_id,
    }


async def _validated_character_slot_params(
    req_body,
    *,
    admin_user_id: int | None,
    db: AsyncSession,
) -> dict:
    character_name = await _ensure_character_slot_selection_eligible(
        product_id=req_body.product_id,
        character_scope_key=req_body.character_scope_key,
        db=db,
    )
    if req_body.character_image_file_id is not None:
        await _ensure_character_image_file(
            character_image_file_id=req_body.character_image_file_id,
            db=db,
        )
    return _main_character_slot_params(
        req_body,
        character_name=character_name,
        admin_user_id=admin_user_id,
    )


async def post_admin_main_character_slot(
    *,
    req_body: admin_schema.PostMainCharacterSlotReqBody,
    admin_user_id: int | None,
    db: AsyncSession,
):
    params = await _validated_character_slot_params(
        req_body, admin_user_id=admin_user_id, db=db
    )
    result = await db.execute(
        text("""
            INSERT INTO tb_main_character_slot (
                product_id,
                character_scope_key,
                character_name,
                character_image_file_id,
                card_order,
                publish_start_date,
                publish_end_date,
                use_yn,
                created_id,
                updated_id
            ) VALUES (
                :product_id,
                :character_scope_key,
                :character_name,
                :character_image_file_id,
                :card_order,
                COALESCE(:publish_start_at, NOW()),
                :publish_end_at,
                'Y',
                :created_id,
                :updated_id
            )
        """),
        params,
    )
    return {"result": {"characterSlotId": result.lastrowid}}


async def publish_admin_main_character_slot_now(
    *,
    req_body: admin_schema.PostMainCharacterSlotPublishNowReqBody,
    admin_user_id: int | None,
    db: AsyncSession,
):
    params = await _validated_character_slot_params(
        req_body, admin_user_id=admin_user_id, db=db
    )
    result = await db.execute(
        text("""
            INSERT INTO tb_main_character_slot (
                product_id,
                character_scope_key,
                character_name,
                character_image_file_id,
                card_order,
                publish_start_date,
                publish_end_date,
                use_yn,
                created_id,
                updated_id
            ) VALUES (
                :product_id,
                :character_scope_key,
                :character_name,
                :character_image_file_id,
                :card_order,
                NOW(),
                NULL,
                'Y',
                :created_id,
                :updated_id
            )
        """),
        params,
    )
    return {"result": {"characterSlotId": result.lastrowid}}


async def update_admin_main_character_slot(
    *,
    character_slot_id: int,
    req_body: admin_schema.PutMainCharacterSlotReqBody,
    admin_user_id: int | None,
    db: AsyncSession,
):
    params = await _validated_character_slot_params(
        req_body, admin_user_id=admin_user_id, db=db
    )
    params["character_slot_id"] = character_slot_id
    result = await db.execute(
        text("""
            UPDATE tb_main_character_slot
            SET
                product_id = :product_id,
                character_scope_key = :character_scope_key,
                character_name = :character_name,
                character_image_file_id = COALESCE(
                    :character_image_file_id,
                    character_image_file_id
                ),
                card_order = :card_order,
                publish_start_date = COALESCE(:publish_start_at, publish_start_date),
                publish_end_date = :publish_end_at,
                updated_id = :updated_id
            WHERE main_character_slot_id = :character_slot_id
              AND deleted_yn = 'N'
        """),
        params,
    )
    if result.rowcount == 0:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="존재하지 않는 메인 주인공 카드입니다.",
        )
    return {"result": {"characterSlotId": character_slot_id}}


async def delete_admin_main_character_slot(
    *, character_slot_id: int, admin_user_id: int | None, db: AsyncSession
):
    result = await db.execute(
        text("""
            UPDATE tb_main_character_slot
            SET use_yn = 'N', deleted_yn = 'Y', updated_id = :updated_id
            WHERE main_character_slot_id = :character_slot_id
              AND deleted_yn = 'N'
        """),
        {
            "character_slot_id": character_slot_id,
            "updated_id": admin_user_id,
        },
    )
    if result.rowcount == 0:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="존재하지 않는 메인 주인공 카드입니다.",
        )
    return {"result": {"characterSlotId": character_slot_id}}
