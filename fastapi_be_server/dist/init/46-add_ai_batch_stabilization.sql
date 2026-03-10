USE likenovel;

-- -------------------------------------------------------------------
-- 1) tb_user_ai_signal_event created_date 단일 인덱스 추가
-- -------------------------------------------------------------------

SET @ai_signal_table_exists = (
    SELECT COUNT(1)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_user_ai_signal_event'
);

SET @ai_signal_created_idx_exists = (
    SELECT COUNT(1)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_user_ai_signal_event'
       AND index_name = 'idx_ai_signal_created_date'
);

SET @sql_add_ai_signal_created_idx = IF(
    @ai_signal_table_exists = 1 AND @ai_signal_created_idx_exists = 0,
    'ALTER TABLE tb_user_ai_signal_event ADD INDEX idx_ai_signal_created_date (created_date)',
    'SELECT 1'
);

PREPARE stmt_add_ai_signal_created_idx FROM @sql_add_ai_signal_created_idx;
EXECUTE stmt_add_ai_signal_created_idx;
DEALLOCATE PREPARE stmt_add_ai_signal_created_idx;

-- -------------------------------------------------------------------
-- 2) 신규 AI 배치 2건 tb_cms_batch_job_process seed
-- -------------------------------------------------------------------

SET @batch_process_table_exists = (
    SELECT COUNT(1)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_cms_batch_job_process'
);

SET @sql_seed_ai_taste_hourly = IF(
    @batch_process_table_exists = 1,
    'INSERT INTO tb_cms_batch_job_process (job_file_id, job_group_id, job_order, completed_yn, job_list, created_id, updated_id) SELECT ''ai_taste_hourly_batch.sh'', 0, 0, ''N'', ''ai_taste_hourly_batch.sh'', 0, 0 WHERE NOT EXISTS (SELECT 1 FROM tb_cms_batch_job_process WHERE job_file_id = ''ai_taste_hourly_batch.sh'')',
    'SELECT 1'
);

PREPARE stmt_seed_ai_taste_hourly FROM @sql_seed_ai_taste_hourly;
EXECUTE stmt_seed_ai_taste_hourly;
DEALLOCATE PREPARE stmt_seed_ai_taste_hourly;

SET @sql_seed_ai_signal_daily = IF(
    @batch_process_table_exists = 1,
    'INSERT INTO tb_cms_batch_job_process (job_file_id, job_group_id, job_order, completed_yn, job_list, created_id, updated_id) SELECT ''ai_signal_daily_batch.sh'', 0, 0, ''N'', ''ai_signal_daily_batch.sh'', 0, 0 WHERE NOT EXISTS (SELECT 1 FROM tb_cms_batch_job_process WHERE job_file_id = ''ai_signal_daily_batch.sh'')',
    'SELECT 1'
);

PREPARE stmt_seed_ai_signal_daily FROM @sql_seed_ai_signal_daily;
EXECUTE stmt_seed_ai_signal_daily;
DEALLOCATE PREPARE stmt_seed_ai_signal_daily;
