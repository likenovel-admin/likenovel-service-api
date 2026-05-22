SET @site_page_route_daily_pk = (
    SELECT GROUP_CONCAT(column_name ORDER BY ordinal_position)
    FROM information_schema.key_column_usage
    WHERE table_schema = DATABASE()
      AND table_name = 'tb_site_page_route_daily'
      AND constraint_name = 'PRIMARY'
);

SET @site_page_route_daily_exists = (
    SELECT COUNT(*)
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = 'tb_site_page_route_daily'
);

SET @sql_alter_site_page_route_daily_pk = IF(
    @site_page_route_daily_exists = 1
    AND COALESCE(@site_page_route_daily_pk, '') <> 'stat_date,route_group,route_name,path_template',
    'ALTER TABLE tb_site_page_route_daily DROP PRIMARY KEY, ADD PRIMARY KEY (stat_date, route_group, route_name, path_template)',
    'SELECT 1'
);

PREPARE stmt_alter_site_page_route_daily_pk FROM @sql_alter_site_page_route_daily_pk;
EXECUTE stmt_alter_site_page_route_daily_pk;
DEALLOCATE PREPARE stmt_alter_site_page_route_daily_pk;
