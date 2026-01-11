#!/bin/bash

# 배치 스크립트 공통 DB 접속 설정(Defensive)
# - 민감정보(DB 계정/비밀번호)는 절대 하드코딩하지 않고 환경변수로만 주입합니다.
# - env가 누락되면 조용히 실패하지 않고 명확한 에러로 종료합니다.
set -euo pipefail

DB_HOST="${DB_HOST:-mysql}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-}"
DB_PW="${DB_PW:-}"
DB_NAME="${DB_NAME:-likenovel}"

if [ -z "$DB_USER" ] || [ -z "$DB_PW" ]; then
  echo "[ERROR] Missing DB_USER or DB_PW env for batch." 1>&2
  exit 1
fi

# 유/무료 Top 랭킹
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PW" "$DB_NAME" --skip-ssl < /app/dist/batch/service_reset_hourly_batch.sql

exit 0
