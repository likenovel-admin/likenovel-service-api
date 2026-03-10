USE likenovel;

SET @idx_exists := (
    SELECT COUNT(1)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'tb_ptn_product_episode_sales'
      AND index_name = 'idx_ptn_product_episode_sales_created_date_product_id'
);

SET @sql := IF(
    @idx_exists = 0,
    'ALTER TABLE tb_ptn_product_episode_sales ADD INDEX idx_ptn_product_episode_sales_created_date_product_id (created_date, product_id)',
    'SELECT 1'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
