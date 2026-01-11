#!/bin/bash

DB_HOST="mysql"
DB_PORT="3306"
DB_USER="ln-admin"
DB_PW="likenovel684233^^"
DB_NAME="likenovel"

# 일별 집계(매출), 일별 집계(환불), 전체연독률, 주평균 연재횟수, 작품 일별 집계(조회수), 회차 일별 집계(조회수), 작품 집계(정보), 회차 집계(정보)
mysql -h $DB_HOST -P $DB_PORT -u $DB_USER -p$DB_PW $DB_NAME --skip-ssl < /app/dist/batch/summary_daily_batch.sql

# 퀘스트(출석체크, 평가하기, 작품 리뷰 작성하기, 회차 결제하기), 작가홈 관련 인디케이터(작품, 회차)
mysql -h $DB_HOST -P $DB_PORT -u $DB_USER -p$DB_PW $DB_NAME --skip-ssl < /app/dist/batch/service_reset_daily_batch.sql

# 회차별 매출, 일별 이용권 상세, 후원 내역, 기타 수익 내역, 작품별 통계, 회차별 통계, 발굴통계, 작품별 월매출 및 월별 정산용 임시 합산, 후원 및 기타 정산용 임시 합산
mysql -h $DB_HOST -P $DB_PORT -u $DB_USER -p$DB_PW $DB_NAME --skip-ssl < /app/dist/batch/partner_report_daily_batch.sql

exit 0

