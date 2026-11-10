#!/bin/bash

# 주간 유료화 신작 이벤트 갱신 배치 (10분 주기)
# - 이번 주 유료 전환작이 있으면 'N월 M주차 유료화 신작' 이벤트를 이번 주 기준으로 교체
# - 이번 주 전환작이 없으면 변경 없음
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/batch_timestamp_logging.sh"
enable_timestamped_logging

BATCH_NAME="weekly_paid_new_event_batch"
RUN_STARTED_AT="$(date +%s)"
trap 'rc=$?; duration=$(( $(date +%s) - RUN_STARTED_AT )); echo "[INFO] ${BATCH_NAME} completed with exit=${rc} in ${duration}s"; exit "$rc"' EXIT

echo "[INFO] ${BATCH_NAME} started"

DB_HOST="${DB_HOST:-mysql}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-}"
DB_PW="${DB_PW:-}"
DB_NAME="${DB_NAME:-likenovel}"

# SSL: MariaDB(--skip-ssl) vs MySQL 8.0+(--ssl-mode=DISABLED)
if [ -z "${MYSQL_SSL_OPT:-}" ]; then
  if mysql --version 2>&1 | grep -qi mariadb; then MYSQL_SSL_OPT="--skip-ssl"; else MYSQL_SSL_OPT="--ssl-mode=DISABLED"; fi
fi
SQL_FILE="${SQL_FILE:-${SCRIPT_DIR}/weekly_paid_new_event_batch.sql}"

if [ -z "$DB_USER" ] || [ -z "$DB_PW" ]; then
  echo "[ERROR] Missing DB_USER or DB_PW env for batch." 1>&2
  exit 1
fi

result="$(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PW" "$DB_NAME" --default-character-set=utf8mb4 $MYSQL_SSL_OPT --batch --skip-column-names < "$SQL_FILE")"
echo "[INFO] match_count/event_id/title/product_ids/updated_rows: ${result}"

event_match_count="$(printf '%s\n' "$result" | tail -n 1 | cut -f1)"
if [ "$event_match_count" != "1" ]; then
  echo "[ERROR] expected exactly 1 weekly paid-new event by title pattern, found ${event_match_count}" 1>&2
  exit 1
fi
