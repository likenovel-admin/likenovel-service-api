-- Store product-detail entry attribution on raw site PV events for author analytics.

SET @site_page_view_event_exists := (
    SELECT COUNT(*)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_site_page_view_event'
);

SET @sql := IF(
    @site_page_view_event_exists = 0,
    'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''tb_site_page_view_event is required before adding product entry attribution columns''',
    'SELECT ''tb_site_page_view_event exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_product_id := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_site_page_view_event'
       AND column_name = 'product_id'
);

SET @sql := IF(
    @has_product_id = 0,
    'ALTER TABLE tb_site_page_view_event ADD COLUMN product_id INT NULL COMMENT ''작품 상세 진입 작품 ID'' AFTER external_referrer_group',
    'SELECT ''product_id already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_entry_source := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_site_page_view_event'
       AND column_name = 'entry_source'
);

SET @sql := IF(
    @has_entry_source = 0,
    'ALTER TABLE tb_site_page_view_event ADD COLUMN entry_source VARCHAR(120) NULL COMMENT ''작품 상세 진입 source'' AFTER product_id',
    'SELECT ''entry_source already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_entry_source_group := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_site_page_view_event'
       AND column_name = 'entry_source_group'
);

SET @sql := IF(
    @has_entry_source_group = 0,
    'ALTER TABLE tb_site_page_view_event ADD COLUMN entry_source_group VARCHAR(80) NULL COMMENT ''작가 노출용 작품 상세 진입 source 그룹'' AFTER entry_source',
    'SELECT ''entry_source_group already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_product_entry_index := (
    SELECT COUNT(*)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_site_page_view_event'
       AND index_name = 'idx_site_page_view_event_product_entry_occurred'
);

SET @sql := IF(
    @has_product_entry_index = 0,
    'ALTER TABLE tb_site_page_view_event ADD INDEX idx_site_page_view_event_product_entry_occurred (product_id, entry_source_group, occurred_at)',
    'SELECT ''idx_site_page_view_event_product_entry_occurred already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
