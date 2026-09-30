-- Optional link for the site top bar (상단 띠 공지).
-- NULL keeps the bar pointing at its notice detail page.

SET @has_top_bar_link_url := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_notice'
       AND column_name = 'top_bar_link_url'
);

SET @sql := IF(
    @has_top_bar_link_url = 0,
    'ALTER TABLE tb_notice ADD COLUMN top_bar_link_url VARCHAR(500) NULL COMMENT ''상단 띠 링크(비우면 공지 상세)'', ALGORITHM=INSTANT',
    'SELECT ''tb_notice.top_bar_link_url already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
