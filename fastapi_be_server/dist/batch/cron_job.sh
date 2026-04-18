SHELL=/bin/bash
BASH_ENV=/app/dist/batch/cron_env.sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

30 * * * *  bash /app/dist/batch/service_reset_hourly_batch.sh >> /app/logs/service_reset_hourly_batch.log 2>&1
20 * * * *  bash /app/dist/batch/ai_taste_hourly_batch.sh >> /app/logs/ai_taste_hourly_batch.log 2>&1
0 0 * * *   bash /app/dist/batch/service_reset_daily_batch.sh >> /app/logs/service_reset_daily_batch.log 2>&1
20 0 * * *  bash /app/dist/batch/summary_daily_batch.sh >> /app/logs/summary_daily_batch.log 2>&1
30 1 * * *  bash /app/dist/batch/ai_signal_daily_batch.sh >> /app/logs/ai_signal_daily_batch.log 2>&1
35 1 * * *  bash /app/dist/batch/ai_product_detail_funnel_daily_batch.sh >> /app/logs/ai_product_detail_funnel_daily_batch.log 2>&1
40 1 * * *  bash /app/dist/batch/ai_engagement_metrics_daily_batch.sh >> /app/logs/ai_engagement_metrics_daily_batch.log 2>&1
45 1 * * *  bash /app/dist/batch/main_rule_slot_snapshot_batch.sh >> /app/logs/main_rule_slot_snapshot_batch.log 2>&1
50 1 * * *  bash /app/dist/batch/ai_product_episode_dropoff_daily_batch.sh >> /app/logs/ai_product_episode_dropoff_daily_batch.log 2>&1
0 0 * * 1   bash /app/dist/batch/service_reset_weekly_batch.sh >> /app/logs/service_reset_weekly_batch.log 2>&1
0 0 1 * *   bash /app/dist/batch/partner_report_monthly_batch.sh >> /app/logs/partner_report_monthly_batch.log 2>&1

50 * * * *  bash /app/dist/batch/summary_hourly_batch.sh >> /app/logs/summary_hourly_batch.log 2>&1
0 0 * * *  bash /app/dist/batch/statistics_aggregation_daily_batch.sh >> /app/logs/statistics_aggregation_daily_batch.log 2>&1
0 3 * * *  bash /app/dist/batch/ai_dna_extract_daily_batch.sh >> /app/logs/ai_dna_extract_daily_batch.log 2>&1
* * * * *  EPISODE_STATE_TRANSITION_BATCH_ENABLE=1 bash /app/dist/batch/episode_state_transition_minute_batch.sh >> /app/logs/episode_state_transition_minute_batch.log 2>&1
# websochat/story-agent 컨텍스트 수집은 매시 10분에 보수적으로 실행
10 * * * *  STORYCTX_MAX_PARALLEL=2 bash /app/dist/batch/build_story_agent_context_batch.sh >> /app/logs/build_story_agent_context_batch.log 2>&1
