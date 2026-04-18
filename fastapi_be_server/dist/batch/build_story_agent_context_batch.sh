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

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "${LOG_FILE}"
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

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  log "[error] missing ANTHROPIC_API_KEY env"
  exit 1
fi

if [ -z "${OPENROUTER_API_KEY:-}" ]; then
  log "[error] missing OPENROUTER_API_KEY env"
  exit 1
fi

normalize_parallel
acquire_lock

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

readarray -t CANDIDATE_ROWS < <("${MYSQL_CMD[@]}" <<SQL
SELECT
  p.product_id,
  REPLACE(REPLACE(p.title, '\t', ' '), '\n', ' ') AS title
FROM tb_product p
JOIN tb_product_episode pe
  ON pe.product_id = p.product_id
 AND pe.use_yn = 'Y'
 AND pe.open_yn = 'Y'
LEFT JOIN tb_story_agent_context_product sacp
  ON sacp.product_id = p.product_id
WHERE p.price_type = 'free'
  AND p.open_yn = 'Y'
GROUP BY
  p.product_id,
  p.title,
  sacp.context_status,
  sacp.ready_episode_count
HAVING
  COALESCE(sacp.context_status, 'pending') IN ('pending', 'processing', 'failed')
  OR COALESCE(sacp.ready_episode_count, 0) < MAX(pe.episode_no)
ORDER BY
  CASE COALESCE(sacp.context_status, 'pending')
    WHEN 'failed' THEN 0
    WHEN 'processing' THEN 1
    WHEN 'pending' THEN 2
    ELSE 3
  END ASC,
  (MAX(pe.episode_no) - COALESCE(sacp.ready_episode_count, 0)) DESC,
  p.product_id ASC
LIMIT ${MAX_PARALLEL};
SQL
)

if [ "${#CANDIDATE_ROWS[@]}" -eq 0 ]; then
  log "[batch-empty] no eligible products"
  exit 0
fi

declare -a PIDS=()
declare -A PID_TO_PRODUCT_ID=()
declare -A PID_TO_PRODUCT_TITLE=()
declare -A PID_TO_START_TS=()

run_product() {
  local product_id="$1"
  local product_title="$2"

  (
    export PYTHONUNBUFFERED=1
    exec "${PYTHON_BIN}" "${BUILD_SCRIPT}" \
      --product-id "${product_id}" \
      --build-mode full \
      --apply \
      --verbose
  ) >> "${LOG_FILE}" 2>&1 &

  local pid=$!
  PIDS+=("${pid}")
  PID_TO_PRODUCT_ID["${pid}"]="${product_id}"
  PID_TO_PRODUCT_TITLE["${pid}"]="${product_title}"
  PID_TO_START_TS["${pid}"]="$(date +%s)"
  log "[start] product_id=${product_id} title=\"${product_title}\" pid=${pid}"
}

for row in "${CANDIDATE_ROWS[@]}"; do
  IFS=$'\t' read -r product_id product_title <<< "${row}"
  if [ -z "${product_id:-}" ] || [ -z "${product_title:-}" ]; then
    continue
  fi
  run_product "${product_id}" "${product_title}"
done

if [ "${#PIDS[@]}" -eq 0 ]; then
  log "[batch-empty] selected rows were unparsable"
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

log "[summary] launched=${#PIDS[@]} ready=${success_count} failed=${fail_count} max_parallel=${MAX_PARALLEL}"

if [ "${fail_count}" -gt 0 ]; then
  exit 1
fi

exit 0
