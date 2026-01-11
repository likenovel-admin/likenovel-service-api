30 * * * *  bash /app/dist/batch/service_reset_hourly_batch.sh >> /app/logs/service_reset_hourly_batch.log 2>&1
0 0 * * *   bash /app/dist/batch/service_reset_daily_batch.sh >> /app/logs/service_reset_daily_batch.log 2>&1
0 0 * * *   bash /app/dist/batch/summary_daily_batch.sh >> /app/logs/summary_daily_batch.log 2>&1
0 0 * * 1   bash /app/dist/batch/service_reset_weekly_batch.sh >> /app/logs/service_reset_weekly_batch.log 2>&1
0 0 1 * *   bash /app/dist/batch/partner_report_monthly_batch.sh >> /app/logs/partner_report_monthly_batch.log 2>&1

50 * * * *  bash /app/dist/batch/summary_hourly_batch.sh >> /app/logs/summary_hourly_batch.log 2>&1
0 0 * * *  bash /app/dist/batch/statistics_aggregation_daily_batch.sh >> /app/logs/statistics_aggregation_daily_batch.log 2>&1
