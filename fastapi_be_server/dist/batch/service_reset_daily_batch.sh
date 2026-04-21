#!/bin/bash

# 배치 스크립트 공통 DB 접속 설정(Defensive)
# - 민감정보(DB 계정/비밀번호)는 절대 하드코딩하지 않고 환경변수로만 주입합니다.
# - env가 누락되면 조용히 실패하지 않고 명확한 에러로 종료합니다.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

timestamp() {
  date '+%F %T %Z'
}

log_info() {
  echo "[$(timestamp)] [INFO] $*"
}

log_warn() {
  echo "[$(timestamp)] [WARN] $*" 1>&2
}

log_error() {
  echo "[$(timestamp)] [ERROR] $*" 1>&2
}

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

MAX_RETRIES=5
RETRY_DELAY=10
BATCH_FAILED=0
RUN_STARTED_AT="$(date +%s)"

run_with_retry() {
  local sql_file="$1"
  local batch_name="$2"
  log_info "${batch_name} started (sql=$(basename "$sql_file"))"
  for attempt in $(seq 1 $MAX_RETRIES); do
    log_info "${batch_name} attempt ${attempt}/${MAX_RETRIES} started"
    mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PW" "$DB_NAME" --default-character-set=utf8mb4 $MYSQL_SSL_OPT < "$sql_file"
    rc=$?
    if [ $rc -eq 0 ]; then
      log_info "${batch_name} attempt ${attempt}/${MAX_RETRIES} succeeded"
      return 0
    fi
    log_warn "${batch_name} attempt ${attempt}/${MAX_RETRIES} failed (exit=${rc})"
    if [ $attempt -lt $MAX_RETRIES ]; then
      log_info "${batch_name} retrying after ${RETRY_DELAY}s"
      sleep $RETRY_DELAY
    fi
  done
  log_error "${batch_name} failed after ${MAX_RETRIES} attempts"
  return 1
}

log_info "service_reset_daily_batch wrapper started"

# 퀘스트(출석체크, 평가하기, 작품 리뷰 작성하기, 회차 결제하기), 작가홈 관련 인디케이터(작품, 회차)
run_with_retry ${SCRIPT_DIR}/service_reset_daily_batch.sql "service_reset_daily_batch" || BATCH_FAILED=1

# 회차별 매출, 일별 이용권 상세, 후원 내역, 기타 수익 내역, 작품별 통계, 회차별 통계, 발굴통계, 작품별 월매출 및 월별 정산용 임시 합산, 후원 및 기타 정산용 임시 합산
run_with_retry ${SCRIPT_DIR}/partner_report_daily_batch.sql "partner_report_daily_batch" || BATCH_FAILED=1

if [ "$BATCH_FAILED" -eq 0 ]; then
  log_info "service_reset_daily_batch wrapper completed successfully in $(( $(date +%s) - RUN_STARTED_AT ))s"
else
  log_error "service_reset_daily_batch wrapper completed with failure in $(( $(date +%s) - RUN_STARTED_AT ))s"
fi

exit $BATCH_FAILED
