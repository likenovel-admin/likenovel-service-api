#!/bin/bash

# cron 서비스 시작
service cron start

# crontab 등록
crontab /app/dist/batch/cron_job.sh

# cron 상태 확인
echo "Cron service started and jobs registered:"
crontab -l

# 메인 애플리케이션 시작
exec "$@"