#!/bin/bash

# 배치 스크립트 공통 DB 접속 설정(Defensive)
# - 민감정보(DB 계정/비밀번호)는 절대 하드코딩하지 않고 환경변수로만 주입합니다.
# - env가 누락되면 조용히 실패하지 않고 명확한 에러로 종료합니다.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/batch_advisory_lock.sh"

DB_HOST="${DB_HOST:-mysql}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-}"
DB_PW="${DB_PW:-}"
DB_NAME="${DB_NAME:-likenovel}"
LOCK_NAME="${LOCK_NAME:-likenovel_batch_episode_release}"

# SSL: MariaDB(--skip-ssl) vs MySQL 8.0+(--ssl-mode=DISABLED)
if [ -z "${MYSQL_SSL_OPT:-}" ]; then
  if mysql --version 2>&1 | grep -qi mariadb; then MYSQL_SSL_OPT="--skip-ssl"; else MYSQL_SSL_OPT="--ssl-mode=DISABLED"; fi
fi
SQL_FILE="${SQL_FILE:-${SCRIPT_DIR}/paid_episode_convert_batch.sql}"

if [ -z "$DB_USER" ] || [ -z "$DB_PW" ]; then
  echo "[ERROR] Missing DB_USER or DB_PW env for batch." 1>&2
  exit 1
fi

run_sql_with_advisory_lock "$LOCK_NAME" "$SQL_FILE" "paid_episode_convert_batch"
rc=$?
if [ "$rc" -eq 2 ]; then
  exit 0
fi
exit "$rc"
