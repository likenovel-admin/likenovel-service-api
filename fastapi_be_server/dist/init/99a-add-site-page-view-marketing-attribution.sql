-- Store marketing attribution on raw site PV events for CMS inflow analysis.

SET @site_page_view_event_exists := (
    SELECT COUNT(*)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_site_page_view_event'
);

SET @sql := IF(
    @site_page_view_event_exists = 0,
    'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''tb_site_page_view_event is required before adding marketing attribution columns''',
    'SELECT ''tb_site_page_view_event exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_utm_source := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_site_page_view_event'
       AND column_name = 'utm_source'
);

SET @sql := IF(
    @has_utm_source = 0,
    'ALTER TABLE tb_site_page_view_event ADD COLUMN utm_source VARCHAR(80) NULL COMMENT ''마케팅 UTM source'' AFTER referrer_path',
    'SELECT ''utm_source already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_utm_medium := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_site_page_view_event'
       AND column_name = 'utm_medium'
);

SET @sql := IF(
    @has_utm_medium = 0,
    'ALTER TABLE tb_site_page_view_event ADD COLUMN utm_medium VARCHAR(80) NULL COMMENT ''마케팅 UTM medium'' AFTER utm_source',
    'SELECT ''utm_medium already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_utm_campaign := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_site_page_view_event'
       AND column_name = 'utm_campaign'
);

SET @sql := IF(
    @has_utm_campaign = 0,
    'ALTER TABLE tb_site_page_view_event ADD COLUMN utm_campaign VARCHAR(120) NULL COMMENT ''마케팅 UTM campaign'' AFTER utm_medium',
    'SELECT ''utm_campaign already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_utm_content := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_site_page_view_event'
       AND column_name = 'utm_content'
);

SET @sql := IF(
    @has_utm_content = 0,
    'ALTER TABLE tb_site_page_view_event ADD COLUMN utm_content VARCHAR(120) NULL COMMENT ''마케팅 UTM content'' AFTER utm_campaign',
    'SELECT ''utm_content already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_external_referrer_host := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_site_page_view_event'
       AND column_name = 'external_referrer_host'
);

SET @sql := IF(
    @has_external_referrer_host = 0,
    'ALTER TABLE tb_site_page_view_event ADD COLUMN external_referrer_host VARCHAR(255) NULL COMMENT ''외부 유입 referrer host'' AFTER utm_content',
    'SELECT ''external_referrer_host already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_external_referrer_group := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_site_page_view_event'
       AND column_name = 'external_referrer_group'
);

SET @sql := IF(
    @has_external_referrer_group = 0,
    'ALTER TABLE tb_site_page_view_event ADD COLUMN external_referrer_group VARCHAR(80) NULL COMMENT ''외부 유입 referrer 그룹'' AFTER external_referrer_host',
    'SELECT ''external_referrer_group already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_utm_index := (
    SELECT COUNT(*)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_site_page_view_event'
       AND index_name = 'idx_site_page_view_event_utm_occurred'
);

SET @sql := IF(
    @has_utm_index = 0,
    'ALTER TABLE tb_site_page_view_event ADD KEY idx_site_page_view_event_utm_occurred (utm_source, utm_campaign, occurred_at)',
    'SELECT ''idx_site_page_view_event_utm_occurred already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_referrer_index := (
    SELECT COUNT(*)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_site_page_view_event'
       AND index_name = 'idx_site_page_view_event_referrer_occurred'
);

SET @sql := IF(
    @has_referrer_index = 0,
    'ALTER TABLE tb_site_page_view_event ADD KEY idx_site_page_view_event_referrer_occurred (external_referrer_group, occurred_at)',
    'SELECT ''idx_site_page_view_event_referrer_occurred already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
