#!/bin/bash

set -uo pipefail

LOCK_DIR="/tmp/main-rule-slot-snapshot-batch.lock"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[WARN] main_rule_slot_snapshot_batch already running ($LOCK_DIR exists), skipping." 1>&2
  exit 0
fi
trap 'rm -rf "$LOCK_DIR"' EXIT

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

MAX_RETRIES=3
RETRY_DELAY=10

for attempt in $(seq 1 $MAX_RETRIES); do
  mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PW" "$DB_NAME" --default-character-set=utf8mb4 $MYSQL_SSL_OPT < /app/dist/batch/main_rule_slot_snapshot_batch.sql
  rc=$?
  if [ $rc -eq 0 ]; then
    exit 0
  fi
  echo "[WARN] main_rule_slot_snapshot_batch attempt $attempt/$MAX_RETRIES failed (exit=$rc)" 1>&2
  if [ $attempt -lt $MAX_RETRIES ]; then
    sleep $RETRY_DELAY
  fi
done

echo "[ERROR] main_rule_slot_snapshot_batch failed after $MAX_RETRIES attempts" 1>&2
exit 1
