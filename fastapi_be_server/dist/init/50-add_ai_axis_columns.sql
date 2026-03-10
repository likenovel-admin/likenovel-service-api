USE likenovel;

SET @table_exists = (
    SELECT COUNT(1)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_ai_metadata'
);

SET @col_exists = (
    SELECT COUNT(1)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_ai_metadata'
       AND column_name = 'protagonist_type_tags'
);

SET @sql_add_protagonist_type_tags = IF(
    @table_exists = 1 AND @col_exists = 0,
    'ALTER TABLE tb_product_ai_metadata ADD COLUMN protagonist_type_tags JSON NULL COMMENT ''주인공 타입(타) 태그'' AFTER worldview_tags',
    'SELECT 1'
);
PREPARE stmt_add_protagonist_type_tags FROM @sql_add_protagonist_type_tags;
EXECUTE stmt_add_protagonist_type_tags;
DEALLOCATE PREPARE stmt_add_protagonist_type_tags;

SET @col_exists = (
    SELECT COUNT(1)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_ai_metadata'
       AND column_name = 'protagonist_job_tags'
);

SET @sql_add_protagonist_job_tags = IF(
    @table_exists = 1 AND @col_exists = 0,
    'ALTER TABLE tb_product_ai_metadata ADD COLUMN protagonist_job_tags JSON NULL COMMENT ''주인공 직업(직) 태그'' AFTER protagonist_type_tags',
    'SELECT 1'
);
PREPARE stmt_add_protagonist_job_tags FROM @sql_add_protagonist_job_tags;
EXECUTE stmt_add_protagonist_job_tags;
DEALLOCATE PREPARE stmt_add_protagonist_job_tags;

SET @col_exists = (
    SELECT COUNT(1)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_ai_metadata'
       AND column_name = 'axis_style_tags'
);

SET @sql_add_axis_style_tags = IF(
    @table_exists = 1 AND @col_exists = 0,
    'ALTER TABLE tb_product_ai_metadata ADD COLUMN axis_style_tags JSON NULL COMMENT ''작풍(작) 태그'' AFTER protagonist_job_tags',
    'SELECT 1'
);
PREPARE stmt_add_axis_style_tags FROM @sql_add_axis_style_tags;
EXECUTE stmt_add_axis_style_tags;
DEALLOCATE PREPARE stmt_add_axis_style_tags;

SET @col_exists = (
    SELECT COUNT(1)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_ai_metadata'
       AND column_name = 'axis_romance_tags'
);

SET @sql_add_axis_romance_tags = IF(
    @table_exists = 1 AND @col_exists = 0,
    'ALTER TABLE tb_product_ai_metadata ADD COLUMN axis_romance_tags JSON NULL COMMENT ''연애/케미(연) 태그'' AFTER axis_style_tags',
    'SELECT 1'
);
PREPARE stmt_add_axis_romance_tags FROM @sql_add_axis_romance_tags;
EXECUTE stmt_add_axis_romance_tags;
DEALLOCATE PREPARE stmt_add_axis_romance_tags;
