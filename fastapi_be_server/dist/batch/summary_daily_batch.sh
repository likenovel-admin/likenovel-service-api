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

# 일별 집계(매출), 일별 집계(환불), 전체연독률, 주평균 연재횟수, 작품 일별 집계(조회수), 회차 일별 집계(조회수), 작품 집계(정보), 회차 집계(정보)
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PW" "$DB_NAME" --skip-ssl < /app/dist/batch/summary_daily_batch.sql

# 퀘스트(출석체크, 평가하기, 작품 리뷰 작성하기, 회차 결제하기), 작가홈 관련 인디케이터(작품, 회차)
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PW" "$DB_NAME" --skip-ssl < /app/dist/batch/service_reset_daily_batch.sql

# 회차별 매출, 일별 이용권 상세, 후원 내역, 기타 수익 내역, 작품별 통계, 회차별 통계, 발굴통계, 작품별 월매출 및 월별 정산용 임시 합산, 후원 및 기타 정산용 임시 합산
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PW" "$DB_NAME" --skip-ssl < /app/dist/batch/partner_report_daily_batch.sql

exit 0
