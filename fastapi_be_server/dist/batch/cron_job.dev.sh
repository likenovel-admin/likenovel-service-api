# /etc/cron.d/likenovel-dev — dev 환경 배치 스케줄
# run_be.dev.sh에서 자동 설치됨 (sudo cp → /etc/cron.d/likenovel-dev)

SHELL=/bin/bash
BASH_ENV=/home/ln-admin/likenovel/batch-dev/cron_env.sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

30 * * * * ln-admin bash /home/ln-admin/likenovel/batch-dev/service_reset_hourly_batch.sh >> /home/ln-admin/likenovel/batch-dev/service_reset_hourly_batch.log 2>&1
20 * * * * ln-admin bash /home/ln-admin/likenovel/batch-dev/ai_taste_hourly_batch.sh >> /home/ln-admin/likenovel/batch-dev/ai_taste_hourly_batch.log 2>&1
0 0 * * *  ln-admin bash /home/ln-admin/likenovel/batch-dev/service_reset_daily_batch.sh >> /home/ln-admin/likenovel/batch-dev/service_reset_daily_batch.log 2>&1
20 0 * * * ln-admin bash /home/ln-admin/likenovel/batch-dev/summary_daily_batch.sh >> /home/ln-admin/likenovel/batch-dev/summary_daily_batch.log 2>&1
30 1 * * * ln-admin bash /home/ln-admin/likenovel/batch-dev/ai_signal_daily_batch.sh >> /home/ln-admin/likenovel/batch-dev/ai_signal_daily_batch.log 2>&1
35 1 * * * ln-admin bash /home/ln-admin/likenovel/batch-dev/ai_product_detail_funnel_daily_batch.sh >> /home/ln-admin/likenovel/batch-dev/ai_product_detail_funnel_daily_batch.log 2>&1
40 1 * * * ln-admin bash /home/ln-admin/likenovel/batch-dev/ai_engagement_metrics_daily_batch.sh >> /home/ln-admin/likenovel/batch-dev/ai_engagement_metrics_daily_batch.log 2>&1
45 1 * * * ln-admin bash /home/ln-admin/likenovel/batch-dev/main_rule_slot_snapshot_batch.sh >> /home/ln-admin/likenovel/batch-dev/main_rule_slot_snapshot_batch.log 2>&1
0 0 * * 1  ln-admin bash /home/ln-admin/likenovel/batch-dev/service_reset_weekly_batch.sh >> /home/ln-admin/likenovel/batch-dev/service_reset_weekly_batch.log 2>&1
0 0 1 * *  ln-admin bash /home/ln-admin/likenovel/batch-dev/partner_report_monthly_batch.sh >> /home/ln-admin/likenovel/batch-dev/partner_report_monthly_batch.log 2>&1

50 * * * * ln-admin bash /home/ln-admin/likenovel/batch-dev/summary_hourly_batch.sh >> /home/ln-admin/likenovel/batch-dev/summary_hourly_batch.log 2>&1
0 0 * * *  ln-admin bash /home/ln-admin/likenovel/batch-dev/statistics_aggregation_daily_batch.sh >> /home/ln-admin/likenovel/batch-dev/statistics_aggregation_daily_batch.log 2>&1
0 3 * * *  ln-admin bash /home/ln-admin/likenovel/batch-dev/ai_dna_extract_daily_batch.sh >> /home/ln-admin/likenovel/batch-dev/ai_dna_extract_daily_batch.log 2>&1
* * * * *  ln-admin bash /home/ln-admin/likenovel/batch-dev/paid_episode_convert_batch.sh >> /home/ln-admin/likenovel/batch-dev/paid_episode_convert_batch.log 2>&1
* * * * *  ln-admin bash /home/ln-admin/likenovel/batch-dev/scheduled_open_batch.sh >> /home/ln-admin/likenovel/batch-dev/scheduled_open_batch.log 2>&1
