USE likenovel;

SET @column_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'tb_product_ai_metadata'
      AND COLUMN_NAME = 'axis_label_scores'
);
SET @sql = IF(
    @column_exists = 0,
    'ALTER TABLE tb_product_ai_metadata ADD COLUMN axis_label_scores JSON NULL COMMENT ''축별 라벨 점수'' AFTER overall_confidence',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
