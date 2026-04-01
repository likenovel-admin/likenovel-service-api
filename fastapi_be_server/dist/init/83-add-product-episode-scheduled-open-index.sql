USE likenovel;

SET @episode_table_exists = (
    SELECT COUNT(1)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_episode'
);

SET @scheduled_open_idx_exists = (
    SELECT COUNT(1)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_episode'
       AND index_name = 'idx_product_episode_open_use_publish_reserve'
);

SET @sql_add_scheduled_open_idx = IF(
    @episode_table_exists = 1 AND @scheduled_open_idx_exists = 0,
    'ALTER TABLE tb_product_episode ADD INDEX idx_product_episode_open_use_publish_reserve (open_yn, use_yn, publish_reserve_date)',
    'SELECT 1'
);

PREPARE stmt_add_scheduled_open_idx FROM @sql_add_scheduled_open_idx;
EXECUTE stmt_add_scheduled_open_idx;
DEALLOCATE PREPARE stmt_add_scheduled_open_idx;
