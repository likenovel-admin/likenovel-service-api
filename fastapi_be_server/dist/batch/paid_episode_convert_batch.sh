#!/bin/bash

# 배치 스크립트 공통 DB 접속 설정(Defensive)
# - 민감정보(DB 계정/비밀번호)는 절대 하드코딩하지 않고 환경변수로만 주입합니다.
# - env가 누락되면 조용히 실패하지 않고 명확한 에러로 종료합니다.
set -euo pipefail

# 기존 동작을 최대한 유지하기 위해 DB_HOST/SQL_FILE은 기본값을 두고, 필요시 env로 override 합니다.
DB_HOST="${DB_HOST:-10.0.100.78}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-}"
DB_PW="${DB_PW:-}"
DB_NAME="${DB_NAME:-likenovel}"
SQL_FILE="${SQL_FILE:-/home/ln-admin/likenovel/batch/paid_episode_convert_batch.sql}"

if [ -z "$DB_USER" ] || [ -z "$DB_PW" ]; then
  echo "[ERROR] Missing DB_USER or DB_PW env for batch." 1>&2
  exit 1
fi

mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PW" "$DB_NAME" < "$SQL_FILE"

exit 0
