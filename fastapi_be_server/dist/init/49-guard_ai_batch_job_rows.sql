USE likenovel;

-- -------------------------------------------------------------------
-- 1) AI 배치 상태 row 중복 정리 (keep latest id)
-- -------------------------------------------------------------------

SET @batch_process_table_exists = (
    SELECT COUNT(1)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_cms_batch_job_process'
);

SET @sql_dedupe_ai_batch_rows = IF(
    @batch_process_table_exists = 1,
    'DELETE t1
       FROM tb_cms_batch_job_process t1
       INNER JOIN tb_cms_batch_job_process t2
               ON t1.job_file_id = t2.job_file_id
              AND t1.id < t2.id
      WHERE t1.job_file_id IN (''ai_taste_hourly_batch.sh'', ''ai_signal_daily_batch.sh'')',
    'SELECT 1'
);

PREPARE stmt_dedupe_ai_batch_rows FROM @sql_dedupe_ai_batch_rows;
EXECUTE stmt_dedupe_ai_batch_rows;
DEALLOCATE PREPARE stmt_dedupe_ai_batch_rows;

-- -------------------------------------------------------------------
-- 2) AI 배치 전용 unique guard column 추가
-- -------------------------------------------------------------------

SET @ai_job_file_key_col_exists = (
    SELECT COUNT(1)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_cms_batch_job_process'
       AND column_name = 'ai_job_file_key'
);

SET @sql_add_ai_job_file_key_col = IF(
    @batch_process_table_exists = 1
    AND @ai_job_file_key_col_exists = 0,
    'ALTER TABLE tb_cms_batch_job_process
       ADD COLUMN ai_job_file_key VARCHAR(50)
       GENERATED ALWAYS AS (
           CASE
               WHEN job_file_id IN (''ai_taste_hourly_batch.sh'', ''ai_signal_daily_batch.sh'')
               THEN job_file_id
               ELSE NULL
           END
       ) STORED',
    'SELECT 1'
);

PREPARE stmt_add_ai_job_file_key_col FROM @sql_add_ai_job_file_key_col;
EXECUTE stmt_add_ai_job_file_key_col;
DEALLOCATE PREPARE stmt_add_ai_job_file_key_col;

-- -------------------------------------------------------------------
-- 3) AI 배치 전용 unique index 추가
-- -------------------------------------------------------------------

SET @ai_job_file_key_col_exists = (
    SELECT COUNT(1)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_cms_batch_job_process'
       AND column_name = 'ai_job_file_key'
);

SET @ai_job_file_key_uniq_exists = (
    SELECT COUNT(1)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_cms_batch_job_process'
       AND column_name = 'ai_job_file_key'
       AND non_unique = 0
);

SET @sql_add_ai_job_file_key_uniq = IF(
    @batch_process_table_exists = 1
    AND @ai_job_file_key_col_exists = 1
    AND @ai_job_file_key_uniq_exists = 0,
    'ALTER TABLE tb_cms_batch_job_process
       ADD UNIQUE INDEX uk_batch_ai_job_file_key (ai_job_file_key)',
    'SELECT 1'
);

PREPARE stmt_add_ai_job_file_key_uniq FROM @sql_add_ai_job_file_key_uniq;
EXECUTE stmt_add_ai_job_file_key_uniq;
DEALLOCATE PREPARE stmt_add_ai_job_file_key_uniq;
