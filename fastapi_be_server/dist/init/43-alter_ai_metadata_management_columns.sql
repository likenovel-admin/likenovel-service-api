USE likenovel;

SET @column_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'tb_product_ai_metadata'
      AND COLUMN_NAME = 'analysis_status'
);
SET @sql = IF(
    @column_exists = 0,
    'ALTER TABLE tb_product_ai_metadata ADD COLUMN analysis_status VARCHAR(20) NOT NULL DEFAULT ''pending'' COMMENT ''분석 상태 (pending/success/failed)'' AFTER model_version',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'tb_product_ai_metadata'
      AND COLUMN_NAME = 'analysis_attempt_count'
);
SET @sql = IF(
    @column_exists = 0,
    'ALTER TABLE tb_product_ai_metadata ADD COLUMN analysis_attempt_count INT NOT NULL DEFAULT 0 COMMENT ''분석 시도 누적 횟수'' AFTER analysis_status',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'tb_product_ai_metadata'
      AND COLUMN_NAME = 'analysis_error_message'
);
SET @sql = IF(
    @column_exists = 0,
    'ALTER TABLE tb_product_ai_metadata ADD COLUMN analysis_error_message VARCHAR(1000) NULL COMMENT ''마지막 분석 실패 사유'' AFTER analysis_attempt_count',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @column_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'tb_product_ai_metadata'
      AND COLUMN_NAME = 'exclude_from_recommend_yn'
);
SET @sql = IF(
    @column_exists = 0,
    'ALTER TABLE tb_product_ai_metadata ADD COLUMN exclude_from_recommend_yn CHAR(1) NOT NULL DEFAULT ''N'' COMMENT ''추천 제외 여부'' AFTER analysis_error_message',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE tb_product_ai_metadata
SET analysis_status = 'success'
WHERE analyzed_at IS NOT NULL
  AND analysis_status = 'pending';

SET @index_exists = (
    SELECT COUNT(*)
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'tb_product_ai_metadata'
      AND INDEX_NAME = 'idx_ai_metadata_recommendable'
);
SET @sql = IF(
    @index_exists = 0,
    'ALTER TABLE tb_product_ai_metadata ADD INDEX idx_ai_metadata_recommendable (analysis_status, exclude_from_recommend_yn)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
