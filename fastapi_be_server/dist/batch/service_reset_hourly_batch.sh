#!/bin/bash

DB_HOST="mysql"
DB_PORT="3306"
DB_USER="ln-admin"
DB_PW="likenovel684233^^"
DB_NAME="likenovel"

# 유/무료 Top 랭킹
mysql -h $DB_HOST -P $DB_PORT -u $DB_USER -p$DB_PW $DB_NAME --skip-ssl < /app/dist/batch/service_reset_hourly_batch.sql

exit 0

