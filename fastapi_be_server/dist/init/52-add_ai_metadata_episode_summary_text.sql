USE likenovel;

SET @column_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'tb_product_ai_metadata'
      AND COLUMN_NAME = 'episode_summary_text'
);
SET @sql = IF(
    @column_exists = 0,
    'ALTER TABLE tb_product_ai_metadata ADD COLUMN episode_summary_text TEXT NULL COMMENT ''작품요약 (1~10화 3문장 요약)'' AFTER hook',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
