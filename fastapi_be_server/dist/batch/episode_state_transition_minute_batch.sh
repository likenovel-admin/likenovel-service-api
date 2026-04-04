#!/bin/bash

# 회차/작품 상태 전이 단일 1분 배치
# - 예약공개, 작품 공개, last_episode_date 갱신, 유료전환, 작품 price_type 승격을 한 실행 흐름으로 수행
# - 현재 단계에서는 cron 미연결 상태의 신규 배치이며, 기본 비활성화로 accidental run을 막는다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DB_HOST="${DB_HOST:-mysql}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-}"
DB_PW="${DB_PW:-}"
DB_NAME="${DB_NAME:-likenovel}"
EPISODE_STATE_TRANSITION_BATCH_ENABLE="${EPISODE_STATE_TRANSITION_BATCH_ENABLE:-0}"

# SSL: MariaDB(--skip-ssl) vs MySQL 8.0+(--ssl-mode=DISABLED)
if [ -z "${MYSQL_SSL_OPT:-}" ]; then
  if mysql --version 2>&1 | grep -qi mariadb; then MYSQL_SSL_OPT="--skip-ssl"; else MYSQL_SSL_OPT="--ssl-mode=DISABLED"; fi
fi
SQL_FILE="${SQL_FILE:-${SCRIPT_DIR}/episode_state_transition_minute_batch.sql}"

if [ -z "$DB_USER" ] || [ -z "$DB_PW" ]; then
  echo "[ERROR] Missing DB_USER or DB_PW env for batch." 1>&2
  exit 1
fi

if [ "$EPISODE_STATE_TRANSITION_BATCH_ENABLE" != "1" ]; then
  echo "[ERROR] episode_state_transition_minute_batch is disabled by default. Set EPISODE_STATE_TRANSITION_BATCH_ENABLE=1 to run it intentionally." 1>&2
  exit 64
fi

mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PW" "$DB_NAME" --default-character-set=utf8mb4 $MYSQL_SSL_OPT < "$SQL_FILE"
