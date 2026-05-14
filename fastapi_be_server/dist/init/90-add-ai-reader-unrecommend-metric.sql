SET @ai_reader_public_metric_table_exists = (
    SELECT COUNT(*)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_public_metric_daily'
);

SET @ai_unrecommend_column_exists = (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_public_metric_daily'
       AND column_name = 'ai_unrecommend_count'
);

SET @sql_add_ai_unrecommend_column = IF(
    @ai_reader_public_metric_table_exists = 0,
    'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''tb_ai_reader_public_metric_daily is required before adding ai_unrecommend_count''',
    IF(
        @ai_unrecommend_column_exists = 0,
        'ALTER TABLE tb_ai_reader_public_metric_daily ADD COLUMN ai_unrecommend_count INT NOT NULL DEFAULT 0 AFTER ai_recommend_count',
        'SELECT ''ai_unrecommend_count already exists'''
    )
);
PREPARE stmt_add_ai_unrecommend_column FROM @sql_add_ai_unrecommend_column;
EXECUTE stmt_add_ai_unrecommend_column;
DEALLOCATE PREPARE stmt_add_ai_unrecommend_column;
