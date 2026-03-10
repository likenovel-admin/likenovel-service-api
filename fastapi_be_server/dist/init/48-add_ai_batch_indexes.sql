USE likenovel;

-- -------------------------------------------------------------------
-- 1) AI 배치 상태 row 조회/잠금 경로 인덱스
-- -------------------------------------------------------------------

SET @batch_process_table_exists = (
    SELECT COUNT(1)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_cms_batch_job_process'
);

SET @batch_process_cols_ok = (
    SELECT COUNT(1)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_cms_batch_job_process'
       AND column_name IN ('job_file_id', 'updated_date', 'id')
);

SET @batch_job_same_index_exists = (
    SELECT COUNT(1)
      FROM (
            SELECT index_name
              FROM information_schema.statistics
             WHERE table_schema = DATABASE()
               AND table_name = 'tb_cms_batch_job_process'
             GROUP BY index_name
            HAVING COUNT(*) = 3
               AND SUM(seq_in_index = 1 AND column_name = 'job_file_id') = 1
               AND SUM(seq_in_index = 2 AND column_name = 'updated_date') = 1
               AND SUM(seq_in_index = 3 AND column_name = 'id') = 1
      ) t
);

SET @sql_add_batch_job_idx = IF(
    @batch_process_table_exists = 1
    AND @batch_process_cols_ok = 3
    AND @batch_job_same_index_exists = 0,
    'ALTER TABLE tb_cms_batch_job_process ADD INDEX idx_batch_job_file_updated_id (job_file_id, updated_date, id)',
    'SELECT 1'
);

PREPARE stmt_add_batch_job_idx FROM @sql_add_batch_job_idx;
EXECUTE stmt_add_batch_job_idx;
DEALLOCATE PREPARE stmt_add_batch_job_idx;

-- -------------------------------------------------------------------
-- 2) AI 일배치 원천 이벤트 롤업 경로 인덱스
-- -------------------------------------------------------------------

SET @ai_signal_table_exists = (
    SELECT COUNT(1)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_user_ai_signal_event'
);

SET @ai_signal_cols_ok = (
    SELECT COUNT(1)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_user_ai_signal_event'
       AND column_name IN ('created_date', 'user_id', 'product_id', 'event_type')
);

SET @ai_signal_rollup_same_index_exists = (
    SELECT COUNT(1)
      FROM (
            SELECT index_name
              FROM information_schema.statistics
             WHERE table_schema = DATABASE()
               AND table_name = 'tb_user_ai_signal_event'
             GROUP BY index_name
            HAVING COUNT(*) = 4
               AND SUM(seq_in_index = 1 AND column_name = 'created_date') = 1
               AND SUM(seq_in_index = 2 AND column_name = 'user_id') = 1
               AND SUM(seq_in_index = 3 AND column_name = 'product_id') = 1
               AND SUM(seq_in_index = 4 AND column_name = 'event_type') = 1
      ) t
);

SET @sql_add_ai_signal_rollup_idx = IF(
    @ai_signal_table_exists = 1
    AND @ai_signal_cols_ok = 4
    AND @ai_signal_rollup_same_index_exists = 0,
    'ALTER TABLE tb_user_ai_signal_event ADD INDEX idx_ai_signal_created_user_product_event (created_date, user_id, product_id, event_type)',
    'SELECT 1'
);

PREPARE stmt_add_ai_signal_rollup_idx FROM @sql_add_ai_signal_rollup_idx;
EXECUTE stmt_add_ai_signal_rollup_idx;
DEALLOCATE PREPARE stmt_add_ai_signal_rollup_idx;
