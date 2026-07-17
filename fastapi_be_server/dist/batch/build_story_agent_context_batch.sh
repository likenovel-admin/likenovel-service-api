#!/bin/bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "${SCRIPT_DIR}/cron_env.sh" ]; then
  # shellcheck source=/dev/null
  source "${SCRIPT_DIR}/cron_env.sh"
fi

LOG_FILE="${STORYCTX_LOG_FILE:-${SCRIPT_DIR}/build_story_agent_context_batch.log}"
LOCK_DIR="${STORYCTX_LOCK_DIR:-/tmp/build-story-agent-context-batch.lock}"
LOCK_PID_FILE="${LOCK_DIR}/pid"
MAX_LOCK_AGE_SECONDS="${STORYCTX_MAX_LOCK_AGE_SECONDS:-21600}"
MAX_PARALLEL="${STORYCTX_MAX_PARALLEL:-2}"
BUILD_MODE="${STORYCTX_BUILD_MODE:-delta}"
MAX_DELTA_EPISODES="${STORYCTX_MAX_DELTA_EPISODES:-${STORYCTX_MAX_MISSING_EPISODES:-5}}"
BACKLOG_PRIORITY_THRESHOLD="${STORYCTX_BACKLOG_PRIORITY_THRESHOLD:-20}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "${LOG_FILE}"
}

append_timestamped_to_log() {
  while IFS= read -r line || [ -n "$line" ]; do
    printf '[%(%Y-%m-%d %H:%M:%S %Z)T] %s\n' -1 "$line"
  done >> "${LOG_FILE}"
}

resolve_api_root() {
  if [ -f "${SCRIPT_DIR}/../../scripts/build_story_agent_context.py" ]; then
    cd "${SCRIPT_DIR}/../.." && pwd
    return
  fi

  if [[ "${SCRIPT_DIR}" == *"batch-dev"* ]]; then
    cd "${SCRIPT_DIR}/../api-dev" && pwd
    return
  fi

  cd "${SCRIPT_DIR}/../api" && pwd
}

# shellcheck disable=SC2329
cleanup_on_exit() {
  local exit_code=$?
  rm -rf "${LOCK_DIR}"
  exit "${exit_code}"
}

acquire_lock() {
  if mkdir "${LOCK_DIR}" 2>/dev/null; then
    echo "$$" > "${LOCK_PID_FILE}"
    trap cleanup_on_exit EXIT
    return 0
  fi

  local stale_lock=0
  local now_ts
  local lock_ts
  now_ts="$(date +%s)"
  lock_ts="$(stat -c %Y "${LOCK_DIR}" 2>/dev/null || echo 0)"

  if [ -f "${LOCK_PID_FILE}" ]; then
    local existing_pid
    existing_pid="$(cat "${LOCK_PID_FILE}" 2>/dev/null || true)"
    if ! [[ "${existing_pid}" =~ ^[0-9]+$ ]] || ! kill -0 "${existing_pid}" 2>/dev/null; then
      stale_lock=1
    fi
  elif [ "${lock_ts}" -gt 0 ] && [ $((now_ts - lock_ts)) -gt "${MAX_LOCK_AGE_SECONDS}" ]; then
    stale_lock=1
  fi

  if [ "${stale_lock}" -eq 1 ]; then
    log "[warn] stale lock detected. removing ${LOCK_DIR}"
    rm -rf "${LOCK_DIR}"
    if mkdir "${LOCK_DIR}" 2>/dev/null; then
      echo "$$" > "${LOCK_PID_FILE}"
      trap cleanup_on_exit EXIT
      return 0
    fi
  fi

  log "[skip] batch lock busy (${LOCK_DIR})"
  exit 0
}

normalize_parallel() {
  if ! [[ "${MAX_PARALLEL}" =~ ^[0-9]+$ ]]; then
    MAX_PARALLEL=2
  fi
  if [ "${MAX_PARALLEL}" -lt 1 ]; then
    MAX_PARALLEL=1
  fi
  if [ "${MAX_PARALLEL}" -gt 2 ]; then
    MAX_PARALLEL=2
  fi
}

normalize_build_mode() {
  case "${BUILD_MODE}" in
    delta|full)
      ;;
    *)
      log "[error] invalid STORYCTX_BUILD_MODE=${BUILD_MODE}"
      exit 1
      ;;
  esac

  if [ "${BUILD_MODE}" = "full" ] && [ "${STORYCTX_ALLOW_FULL:-0}" != "1" ]; then
    log "[error] full build blocked. set STORYCTX_ALLOW_FULL=1 for manual backfill only"
    exit 1
  fi

  if ! [[ "${MAX_DELTA_EPISODES}" =~ ^[0-9]+$ ]]; then
    MAX_DELTA_EPISODES=5
  fi
  if [ "${MAX_DELTA_EPISODES}" -lt 1 ]; then
    MAX_DELTA_EPISODES=1
  fi
  if ! [[ "${BACKLOG_PRIORITY_THRESHOLD}" =~ ^[0-9]+$ ]]; then
    BACKLOG_PRIORITY_THRESHOLD=20
  fi
  if [ "${BACKLOG_PRIORITY_THRESHOLD}" -lt 1 ]; then
    BACKLOG_PRIORITY_THRESHOLD=1
  fi
}

API_ROOT="$(resolve_api_root)"
BUILD_SCRIPT="${API_ROOT}/scripts/build_story_agent_context.py"

if [ -x "${API_ROOT}/.venv/bin/python" ]; then
  PYTHON_BIN="${API_ROOT}/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [ ! -x "${PYTHON_BIN}" ]; then
  log "[error] missing python executable: ${PYTHON_BIN}"
  exit 1
fi

if [ ! -f "${BUILD_SCRIPT}" ]; then
  log "[error] missing build script: ${BUILD_SCRIPT}"
  exit 1
fi

if [ -z "${DB_USER:-}" ] || [ -z "${DB_PW:-}" ]; then
  log "[error] missing DB_USER or DB_PW env"
  exit 1
fi

if [ -z "${OPENROUTER_API_KEY:-}" ]; then
  log "[error] missing OPENROUTER_API_KEY env"
  exit 1
fi

normalize_parallel
normalize_build_mode
acquire_lock
log "[INFO] build_story_agent_context_batch started max_parallel=${MAX_PARALLEL} build_mode=${BUILD_MODE} max_delta_episodes=${MAX_DELTA_EPISODES} backlog_priority_threshold=${BACKLOG_PRIORITY_THRESHOLD}"

MYSQL_CMD=(
  mysql
  -h "${DB_HOST}"
  -P "${DB_PORT}"
  -u "${DB_USER}"
  -p"${DB_PW}"
  "${DB_NAME}"
  --default-character-set=utf8mb4
  --batch
  --raw
  --skip-column-names
)
if [ -n "${MYSQL_SSL_OPT:-}" ]; then
  MYSQL_CMD+=("${MYSQL_SSL_OPT}")
fi

CANDIDATE_OUTPUT=""
if ! CANDIDATE_OUTPUT="$("${MYSQL_CMD[@]}" <<SQL
SELECT
  candidates.product_id,
  candidates.title,
  candidates.character_asset_repair_needed
FROM (
  SELECT
    p.product_id,
    REPLACE(REPLACE(p.title, '\t', ' '), '\n', ' ') AS title,
    COALESCE(sacp.context_status, 'pending') AS context_status,
    sacp.last_built_at AS last_built_at,
    SUM(CASE WHEN sacs.summary_id IS NULL THEN 1 ELSE 0 END) AS missing_open_episode_count,
    SUM(CASE WHEN sacs_signal.summary_id IS NULL THEN 1 ELSE 0 END) AS missing_open_character_signal_count,
    SUM(CASE WHEN sacs_scene.summary_id IS NULL THEN 1 ELSE 0 END) AS missing_open_scene_count,
    GREATEST(
      SUM(CASE WHEN sacs.summary_id IS NULL THEN 1 ELSE 0 END),
      SUM(CASE WHEN sacs_signal.summary_id IS NULL THEN 1 ELSE 0 END)
    ) AS missing_foundation_episode_count,
    (
      SELECT COUNT(*)
      FROM tb_story_agent_context_summary ci
      WHERE ci.product_id = p.product_id
        AND ci.summary_type = 'character_inventory'
        AND ci.is_active = 'Y'
    ) AS active_character_inventory_count,
    (
      SELECT COUNT(*)
      FROM tb_story_agent_context_summary civ3
      WHERE civ3.product_id = p.product_id
        AND civ3.summary_type = 'character_inventory_v3'
        AND civ3.is_active = 'Y'
    ) AS active_character_inventory_v3_count,
    (
      SELECT COUNT(*)
      FROM tb_story_agent_context_summary repair_inventory
      WHERE repair_inventory.product_id = p.product_id
        AND repair_inventory.summary_type = 'character_inventory_v3'
        AND repair_inventory.is_active = 'Y'
        AND NULLIF(TRIM(repair_inventory.scope_key), '') IS NOT NULL
        AND JSON_VALID(repair_inventory.summary_text)
        AND NOT (
          LOWER(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(repair_inventory.summary_text, '$.continuity_status')), '')) = 'ambiguous'
          OR JSON_CONTAINS(
            COALESCE(JSON_EXTRACT(repair_inventory.summary_text, '$.identity_conflict_reasons'), JSON_ARRAY()),
            JSON_QUOTE('identity_continuity_ambiguous')
          ) = 1
        )
        AND (
          LOWER(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(repair_inventory.summary_text, '$.public_chat_eligible')), 'false')) = 'true'
          OR LOWER(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(repair_inventory.summary_text, '$.public_slot_eligible')), 'false')) = 'true'
          OR LOWER(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(repair_inventory.summary_text, '$.chat_readiness_v1.character_chat_allowed')), 'false')) = 'true'
          OR LOWER(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(repair_inventory.summary_text, '$.chat_readiness_v1.public_slot_allowed')), 'false')) = 'true'
          OR LOWER(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(repair_inventory.summary_text, '$.chat_readiness_v1.exposure_decision')), '')) = 'eligible'
        )
        AND (
          NOT EXISTS (
            SELECT 1
            FROM tb_story_agent_context_summary repair_profile
            WHERE repair_profile.product_id = p.product_id
              AND repair_profile.summary_type = 'character_rp_profile'
              AND repair_profile.is_active = 'Y'
              AND repair_profile.scope_key = repair_inventory.scope_key
              AND JSON_VALID(repair_profile.summary_text)
              AND JSON_UNQUOTE(JSON_EXTRACT(repair_profile.summary_text, '$.character_key')) = repair_inventory.scope_key
          )
          OR NOT EXISTS (
            SELECT 1
            FROM tb_story_agent_context_summary repair_examples
            WHERE repair_examples.product_id = p.product_id
              AND repair_examples.summary_type = 'character_rp_examples'
              AND repair_examples.is_active = 'Y'
              AND repair_examples.scope_key = repair_inventory.scope_key
              AND JSON_VALID(repair_examples.summary_text)
              AND JSON_UNQUOTE(JSON_EXTRACT(repair_examples.summary_text, '$.character_key')) = repair_inventory.scope_key
              AND JSON_TYPE(JSON_EXTRACT(repair_examples.summary_text, '$.examples')) = 'ARRAY'
              AND COALESCE(JSON_LENGTH(JSON_EXTRACT(repair_examples.summary_text, '$.examples')), 0) > 0
              AND EXISTS (
                SELECT 1
                FROM JSON_TABLE(
                  repair_examples.summary_text,
                  '$.examples[*]' COLUMNS (
                    example_text TEXT PATH '$.text'
                  )
                ) repair_example_item
                WHERE NULLIF(TRIM(repair_example_item.example_text), '') IS NOT NULL
              )
          )
          OR NOT EXISTS (
            SELECT 1
            FROM tb_story_agent_context_summary repair_scene
            WHERE repair_scene.product_id = p.product_id
              AND repair_scene.summary_type = 'episode_scene_extraction'
              AND repair_scene.is_active = 'Y'
              AND JSON_VALID(repair_scene.summary_text)
              AND (
                EXISTS (
                  SELECT 1
                  FROM JSON_TABLE(
                    repair_scene.summary_text,
                    '$.scenes[*].participants[*]' COLUMNS (
                      character_scope_key VARCHAR(255) PATH '$.scope_key'
                    )
                  ) repair_scene_participant
                  WHERE repair_scene_participant.character_scope_key = repair_inventory.scope_key
                )
                OR EXISTS (
                  SELECT 1
                  FROM JSON_TABLE(
                    repair_scene.summary_text,
                    '$.scenes[*].action_ownership[*]' COLUMNS (
                      character_scope_key VARCHAR(255) PATH '$.actor_scope_key'
                    )
                  ) repair_scene_actor
                  WHERE repair_scene_actor.character_scope_key = repair_inventory.scope_key
                )
              )
          )
        )
    ) AS character_asset_repair_needed
  FROM tb_product p
  JOIN tb_product_episode pe
    ON pe.product_id = p.product_id
   AND pe.use_yn = 'Y'
   AND pe.open_yn = 'Y'
  LEFT JOIN tb_story_agent_context_product sacp
    ON sacp.product_id = p.product_id
  LEFT JOIN tb_story_agent_context_summary sacs
    ON sacs.product_id = p.product_id
   AND sacs.summary_type = 'episode_summary'
   AND sacs.is_active = 'Y'
   AND sacs.scope_key = CONCAT('episode:', pe.episode_id)
  LEFT JOIN tb_story_agent_context_summary sacs_signal
    ON sacs_signal.product_id = p.product_id
   AND sacs_signal.summary_type = 'episode_character_signals'
   AND sacs_signal.is_active = 'Y'
   AND sacs_signal.scope_key = CONCAT('episode:', pe.episode_id)
  LEFT JOIN tb_story_agent_context_summary sacs_scene
    ON sacs_scene.product_id = p.product_id
   AND sacs_scene.summary_type = 'episode_scene_extraction'
   AND sacs_scene.is_active = 'Y'
   AND sacs_scene.scope_key = CONCAT('episode:', pe.episode_id)
   AND sacs_scene.summary_id > sacs.summary_id
   AND LOWER(TRIM(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
         IF(JSON_VALID(sacs_scene.summary_text), sacs_scene.summary_text, '{}'),
         '$.status'
       )), ''))) IN ('ok', 'partial')
   AND JSON_TYPE(JSON_EXTRACT(
         IF(JSON_VALID(sacs_scene.summary_text), sacs_scene.summary_text, '{}'),
         '$.scene_count'
       )) = 'INTEGER'
   AND CAST(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
         IF(JSON_VALID(sacs_scene.summary_text), sacs_scene.summary_text, '{}'),
         '$.scene_count'
       )), '0') AS SIGNED) > 0
   AND JSON_TYPE(JSON_EXTRACT(
         IF(JSON_VALID(sacs_scene.summary_text), sacs_scene.summary_text, '{}'),
         '$.scenes'
       )) = 'ARRAY'
   AND COALESCE(JSON_LENGTH(JSON_EXTRACT(
         IF(JSON_VALID(sacs_scene.summary_text), sacs_scene.summary_text, '{}'),
         '$.scenes'
       )), 0) > 0
   AND NULLIF(TRIM(COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
         IF(JSON_VALID(sacs_scene.summary_text), sacs_scene.summary_text, '{}'),
         '$.scenes[0].scene_gist'
       )), '')), '') IS NOT NULL
  WHERE p.price_type IN ('free', 'paid')
    AND p.status_code = 'ongoing'
    AND p.open_yn = 'Y'
    AND p.blind_yn = 'N'
    AND COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'
    AND COALESCE(sacp.context_status, 'pending') <> 'disabled'
  GROUP BY
    p.product_id,
    p.title,
    sacp.context_status,
    sacp.last_built_at
  HAVING
    missing_foundation_episode_count > 0
    OR missing_open_scene_count > 0
    OR character_asset_repair_needed > 0
    OR (
      context_status = 'failed'
      AND missing_foundation_episode_count = 0
      AND active_character_inventory_count > 0
      AND active_character_inventory_v3_count > 0
    )
) candidates
ORDER BY
  COALESCE(candidates.last_built_at, '1970-01-01') ASC,
  CASE
    WHEN candidates.context_status = 'failed' THEN 0
    WHEN candidates.missing_foundation_episode_count >= ${BACKLOG_PRIORITY_THRESHOLD} THEN 1
    WHEN candidates.missing_foundation_episode_count > 0 OR candidates.missing_open_scene_count > 0 THEN 2
    WHEN candidates.character_asset_repair_needed > 0 THEN 3
    ELSE 4
  END ASC,
  CASE candidates.context_status
    WHEN 'processing' THEN 0
    WHEN 'pending' THEN 1
    ELSE 2
  END ASC,
  candidates.missing_foundation_episode_count DESC,
  candidates.missing_open_character_signal_count DESC,
  candidates.character_asset_repair_needed ASC,
  candidates.missing_open_scene_count DESC,
  candidates.product_id ASC
LIMIT ${MAX_PARALLEL};
SQL
)"; then
  log "[error] candidate query failed"
  exit 1
fi

CANDIDATE_ROWS=()
if [ -n "${CANDIDATE_OUTPUT}" ]; then
  readarray -t CANDIDATE_ROWS <<< "${CANDIDATE_OUTPUT}"
fi

if [ "${#CANDIDATE_ROWS[@]}" -eq 0 ]; then
  log "[batch-empty] no eligible products"
  log "[INFO] build_story_agent_context_batch completed ready=0 failed=0 max_parallel=${MAX_PARALLEL}"
  exit 0
fi

declare -a PIDS=()
declare -A PID_TO_PRODUCT_ID=()
declare -A PID_TO_PRODUCT_TITLE=()
declare -A PID_TO_START_TS=()

run_product() {
  local product_id="$1"
  local product_title="$2"
  local character_asset_repair_needed="${3:-0}"

  (
    export PYTHONUNBUFFERED=1
    command=(
      "${PYTHON_BIN}" "${BUILD_SCRIPT}"
      --product-id "${product_id}" \
      --build-mode "${BUILD_MODE}" \
      --max-delta-episodes "${MAX_DELTA_EPISODES}" \
      --apply \
      --verbose
    )
    if [ "${BUILD_MODE}" = "delta" ] && [ "${character_asset_repair_needed}" -gt 0 ]; then
      command+=(--repair-character-assets)
    fi
    exec "${command[@]}"
  ) > >(append_timestamped_to_log) 2>&1 &

  local pid=$!
  PIDS+=("${pid}")
  PID_TO_PRODUCT_ID["${pid}"]="${product_id}"
  PID_TO_PRODUCT_TITLE["${pid}"]="${product_title}"
  PID_TO_START_TS["${pid}"]="$(date +%s)"
  log "[start] product_id=${product_id} title=\"${product_title}\" pid=${pid}"
}

for row in "${CANDIDATE_ROWS[@]}"; do
  IFS=$'\t' read -r product_id product_title character_asset_repair_needed <<< "${row}"
  if [ -z "${product_id:-}" ] || [ -z "${product_title:-}" ]; then
    continue
  fi
  run_product "${product_id}" "${product_title}" "${character_asset_repair_needed:-0}"
done

if [ "${#PIDS[@]}" -eq 0 ]; then
  log "[batch-empty] selected rows were unparsable"
  log "[INFO] build_story_agent_context_batch completed ready=0 failed=0 max_parallel=${MAX_PARALLEL}"
  exit 0
fi

fail_count=0
success_count=0

for pid in "${PIDS[@]}"; do
  product_id="${PID_TO_PRODUCT_ID[${pid}]}"
  product_title="${PID_TO_PRODUCT_TITLE[${pid}]}"
  start_ts="${PID_TO_START_TS[${pid}]}"

  if wait "${pid}"; then
    success_count=$((success_count + 1))
    duration_sec=$(( $(date +%s) - start_ts ))
    log "[done] product_id=${product_id} title=\"${product_title}\" duration_sec=${duration_sec}"
  else
    fail_count=$((fail_count + 1))
    duration_sec=$(( $(date +%s) - start_ts ))
    log "[fail] product_id=${product_id} title=\"${product_title}\" duration_sec=${duration_sec}"
  fi
done

log "[summary] launched=${#PIDS[@]} ready=${success_count} failed=${fail_count} max_parallel=${MAX_PARALLEL} build_mode=${BUILD_MODE}"
log "[INFO] build_story_agent_context_batch completed ready=${success_count} failed=${fail_count} max_parallel=${MAX_PARALLEL} build_mode=${BUILD_MODE}"

if [ "${fail_count}" -gt 0 ]; then
  exit 1
fi

exit 0
