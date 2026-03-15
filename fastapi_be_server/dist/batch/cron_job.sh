SHELL=/bin/bash
BASH_ENV=/app/dist/batch/cron_env.sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

30 * * * *  bash /app/dist/batch/service_reset_hourly_batch.sh >> /app/logs/service_reset_hourly_batch.log 2>&1
20 * * * *  bash /app/dist/batch/ai_taste_hourly_batch.sh >> /app/logs/ai_taste_hourly_batch.log 2>&1
0 0 * * *   bash /app/dist/batch/service_reset_daily_batch.sh >> /app/logs/service_reset_daily_batch.log 2>&1
20 0 * * *  bash /app/dist/batch/summary_daily_batch.sh >> /app/logs/summary_daily_batch.log 2>&1
30 1 * * *  bash /app/dist/batch/ai_signal_daily_batch.sh >> /app/logs/ai_signal_daily_batch.log 2>&1
40 1 * * *  bash /app/dist/batch/ai_engagement_metrics_daily_batch.sh >> /app/logs/ai_engagement_metrics_daily_batch.log 2>&1
45 1 * * *  bash /app/dist/batch/main_rule_slot_snapshot_batch.sh >> /app/logs/main_rule_slot_snapshot_batch.log 2>&1
0 0 * * 1   bash /app/dist/batch/service_reset_weekly_batch.sh >> /app/logs/service_reset_weekly_batch.log 2>&1
0 0 1 * *   bash /app/dist/batch/partner_report_monthly_batch.sh >> /app/logs/partner_report_monthly_batch.log 2>&1

50 * * * *  bash /app/dist/batch/summary_hourly_batch.sh >> /app/logs/summary_hourly_batch.log 2>&1
0 0 * * *  bash /app/dist/batch/statistics_aggregation_daily_batch.sh >> /app/logs/statistics_aggregation_daily_batch.log 2>&1
0 3 * * *  bash /app/dist/batch/ai_dna_extract_daily_batch.sh >> /app/logs/ai_dna_extract_daily_batch.log 2>&1
* * * * *  bash /app/dist/batch/paid_episode_convert_batch.sh >> /app/logs/paid_episode_convert_batch.log 2>&1
* * * * *  bash /app/dist/batch/scheduled_open_batch.sh >> /app/logs/scheduled_open_batch.log 2>&1
