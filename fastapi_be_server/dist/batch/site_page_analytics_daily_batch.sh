#!/bin/bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/batch_timestamp_logging.sh"
enable_timestamped_logging
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/batch_advisory_lock.sh"

BATCH_NAME="site_page_analytics_daily_batch"
RUN_STARTED_AT="$(date +%s)"
TEMP_SQL=""

cleanup() {
  local rc=$?
  if [ -n "${TEMP_SQL}" ] && [ -f "${TEMP_SQL}" ]; then
    rm -f "${TEMP_SQL}"
  fi
  local duration=$(( $(date +%s) - RUN_STARTED_AT ))
  echo "[INFO] ${BATCH_NAME} completed with exit=${rc} in ${duration}s"
  exit "$rc"
}
trap cleanup EXIT

echo "[INFO] ${BATCH_NAME} started"

DB_HOST="${DB_HOST:-mysql}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-}"
DB_PW="${DB_PW:-}"
DB_NAME="${DB_NAME:-likenovel}"

if [ -z "${MYSQL_SSL_OPT:-}" ]; then
  if mysql --version 2>&1 | grep -qi mariadb; then MYSQL_SSL_OPT="--skip-ssl"; else MYSQL_SSL_OPT="--ssl-mode=DISABLED"; fi
fi

if [ -z "$DB_USER" ] || [ -z "$DB_PW" ]; then
  echo "[ERROR] Missing DB_USER or DB_PW env for batch." 1>&2
  exit 1
fi

SQL_FILE="${SCRIPT_DIR}/site_page_analytics_daily_batch.sql"

if [ -n "${BATCH_DATE:-}" ]; then
  if ! [[ "${BATCH_DATE}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "[ERROR] BATCH_DATE must be YYYY-MM-DD: ${BATCH_DATE}" 1>&2
    exit 1
  fi
  TEMP_SQL="$(mktemp /tmp/site_page_analytics_daily_batch.XXXXXX.sql)"
  printf "SET @site_page_analytics_target_date = DATE('%s');\nsource %s;\n" "${BATCH_DATE}" "${SQL_FILE}" > "${TEMP_SQL}"
  SQL_FILE="${TEMP_SQL}"
fi

MAX_RETRIES=3
RETRY_DELAY=10

for attempt in $(seq 1 $MAX_RETRIES); do
  run_sql_with_advisory_lock "lk_site_page_analytics_daily_batch" "$SQL_FILE" "$BATCH_NAME"
  rc=$?
  if [ $rc -eq 0 ]; then
    exit 0
  fi
  if [ $rc -eq 2 ]; then
    echo "[WARN] ${BATCH_NAME} skipped because advisory lock is busy" 1>&2
    exit 2
  fi
  echo "[WARN] ${BATCH_NAME} attempt $attempt/$MAX_RETRIES failed (exit=$rc)" 1>&2
  if [ $attempt -lt $MAX_RETRIES ]; then
    sleep $RETRY_DELAY
  fi
done

echo "[ERROR] ${BATCH_NAME} failed after $MAX_RETRIES attempts" 1>&2
exit 1
