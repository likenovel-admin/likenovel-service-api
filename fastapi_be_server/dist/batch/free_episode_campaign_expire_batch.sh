#!/bin/bash

# 기간 한정 1~100화 무료 캠페인 종료 배치
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/batch_timestamp_logging.sh"
enable_timestamped_logging

BATCH_NAME="free_episode_campaign_expire_batch"
RUN_STARTED_AT="$(date +%s)"

log_exit() {
  local rc=$?
  local duration
  duration=$(( $(date +%s) - RUN_STARTED_AT ))
  echo "[INFO] ${BATCH_NAME} completed with exit=${rc} in ${duration}s"
  exit "$rc"
}

trap log_exit EXIT

echo "[INFO] ${BATCH_NAME} started"

LOCK_FILE="${LOCK_FILE:-/tmp/likenovel_free_episode_campaign_expire_batch.lock}"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[INFO] free_episode_campaign_expire_batch skip: self lock busy" 1>&2
  exit 0
fi

DB_HOST="${DB_HOST:-mysql}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-}"
DB_PW="${DB_PW:-}"
DB_NAME="${DB_NAME:-likenovel}"

if [ -z "${MYSQL_SSL_OPT:-}" ]; then
  if mysql --version 2>&1 | grep -qi mariadb; then MYSQL_SSL_OPT="--skip-ssl"; else MYSQL_SSL_OPT="--ssl-mode=DISABLED"; fi
fi
SQL_FILE="${SQL_FILE:-${SCRIPT_DIR}/free_episode_campaign_expire_batch.sql}"

if [ -z "$DB_USER" ] || [ -z "$DB_PW" ]; then
  echo "[ERROR] Missing DB_USER or DB_PW env for batch." 1>&2
  exit 1
fi

mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PW" "$DB_NAME" --default-character-set=utf8mb4 $MYSQL_SSL_OPT < "$SQL_FILE"
