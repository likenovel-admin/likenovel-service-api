#!/bin/bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "${SCRIPT_DIR}/cron_env.sh" ]; then
  # shellcheck source=/dev/null
  source "${SCRIPT_DIR}/cron_env.sh"
fi

timestamp() {
  date '+%F %T %Z'
}

log_info() {
  echo "[$(timestamp)] [INFO] $*"
}

log_error() {
  echo "[$(timestamp)] [ERROR] $*" 1>&2
}

resolve_api_root() {
  if [ -f "${SCRIPT_DIR}/../../scripts/refresh_public_character_catalog_snapshot.py" ]; then
    cd "${SCRIPT_DIR}/../.." && pwd
    return
  fi

  if [[ "${SCRIPT_DIR}" == *"batch-dev"* ]]; then
    cd "${SCRIPT_DIR}/../api-dev" && pwd
    return
  fi

  cd "${SCRIPT_DIR}/../api" && pwd
}

API_ROOT="$(resolve_api_root)"
REFRESH_SCRIPT="${API_ROOT}/scripts/refresh_public_character_catalog_snapshot.py"

if [ -x "${API_ROOT}/.venv/bin/python" ]; then
  PYTHON_BIN="${API_ROOT}/.venv/bin/python"
else
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [ ! -x "${PYTHON_BIN}" ]; then
  log_error "missing python executable: ${PYTHON_BIN}"
  exit 1
fi

if [ ! -f "${REFRESH_SCRIPT}" ]; then
  log_error "missing refresh script: ${REFRESH_SCRIPT}"
  exit 1
fi

log_info "public character catalog snapshot refresh started"
if timeout --signal=TERM --kill-after=10s 120s \
  "${PYTHON_BIN}" "${REFRESH_SCRIPT}"; then
  log_info "public character catalog snapshot refresh completed"
  exit 0
else
  rc=$?
  log_error "public character catalog snapshot refresh failed exit=${rc}"
  exit "${rc}"
fi
