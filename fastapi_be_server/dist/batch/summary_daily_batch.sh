#!/bin/bash

# 배치 스크립트 공통 DB 접속 설정(Defensive)
# - 민감정보(DB 계정/비밀번호)는 절대 하드코딩하지 않고 환경변수로만 주입합니다.
# - env가 누락되면 조용히 실패하지 않고 명확한 에러로 종료합니다.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DB_HOST="${DB_HOST:-mysql}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-}"
DB_PW="${DB_PW:-}"
DB_NAME="${DB_NAME:-likenovel}"

# SSL: MariaDB(--skip-ssl) vs MySQL 8.0+(--ssl-mode=DISABLED)
if [ -z "${MYSQL_SSL_OPT:-}" ]; then
  if mysql --version 2>&1 | grep -qi mariadb; then MYSQL_SSL_OPT="--skip-ssl"; else MYSQL_SSL_OPT="--ssl-mode=DISABLED"; fi
fi

if [ -z "$DB_USER" ] || [ -z "$DB_PW" ]; then
  echo "[ERROR] Missing DB_USER or DB_PW env for batch." 1>&2
  exit 1
fi

MAX_RETRIES=3
RETRY_DELAY=10
BATCH_FAILED=0

run_with_retry() {
  local sql_file="$1"
  local batch_name="$2"
  for attempt in $(seq 1 $MAX_RETRIES); do
    mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PW" "$DB_NAME" --default-character-set=utf8mb4 $MYSQL_SSL_OPT < "$sql_file"
    rc=$?
    if [ $rc -eq 0 ]; then
      return 0
    fi
    echo "[WARN] $batch_name attempt $attempt/$MAX_RETRIES failed (exit=$rc)" 1>&2
    if [ $attempt -lt $MAX_RETRIES ]; then
      sleep $RETRY_DELAY
    fi
  done
  echo "[ERROR] $batch_name failed after $MAX_RETRIES attempts" 1>&2
  return 1
}

# 일별 집계(매출), 일별 집계(환불), 전체연독률, 주평균 연재횟수, 작품 일별 집계(조회수), 회차 일별 집계(조회수), 작품 집계(정보), 회차 집계(정보)
run_with_retry ${SCRIPT_DIR}/summary_daily_batch.sql "summary_daily_batch" || BATCH_FAILED=1

# 퀘스트(출석체크, 평가하기, 작품 리뷰 작성하기, 회차 결제하기), 작가홈 관련 인디케이터(작품, 회차)
run_with_retry ${SCRIPT_DIR}/service_reset_daily_batch.sql "service_reset_daily_batch" || BATCH_FAILED=1

# 회차별 매출, 일별 이용권 상세, 후원 내역, 기타 수익 내역, 작품별 통계, 회차별 통계, 발굴통계, 작품별 월매출 및 월별 정산용 임시 합산, 후원 및 기타 정산용 임시 합산
run_with_retry ${SCRIPT_DIR}/partner_report_daily_batch.sql "partner_report_daily_batch" || BATCH_FAILED=1

exit $BATCH_FAILED
