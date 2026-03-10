USE likenovel;

-- tb_cms_batch_job_process에 워터마크 컬럼 추가
-- 시간 배치(ai_taste_hourly)가 재실행 시 중복 가산되지 않도록
-- 마지막 처리 완료 시점을 기록한다.

SET @table_exists = (
    SELECT COUNT(1)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_cms_batch_job_process'
);

SET @col_exists = (
    SELECT COUNT(1)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_cms_batch_job_process'
       AND column_name = 'last_processed_date'
);

SET @sql_add_col = IF(
    @table_exists = 1 AND @col_exists = 0,
    'ALTER TABLE tb_cms_batch_job_process ADD COLUMN last_processed_date TIMESTAMP NULL DEFAULT NULL COMMENT ''마지막 처리 완료 시점 (워터마크)''',
    'SELECT 1'
);

PREPARE stmt FROM @sql_add_col;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
