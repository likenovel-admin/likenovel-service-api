-- Site-wide top bar (상단 띠 공지) attached to a general notice.
-- Clicking the bar opens the notice; one active bar is shown at a time.

SET @has_top_bar_yn := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_notice'
       AND column_name = 'top_bar_yn'
);

SET @sql := IF(
    @has_top_bar_yn = 0,
    'ALTER TABLE tb_notice ADD COLUMN top_bar_yn CHAR(1) NOT NULL DEFAULT ''N'' COMMENT ''상단 띠 공지 노출 여부'', ADD COLUMN top_bar_text VARCHAR(80) NULL COMMENT ''상단 띠 문구'', ADD COLUMN top_bar_start_date DATETIME NULL COMMENT ''상단 띠 노출 시작(KST)'', ADD COLUMN top_bar_end_date DATETIME NULL COMMENT ''상단 띠 노출 종료(KST)'', ALGORITHM=INSTANT',
    'SELECT ''tb_notice top bar columns already exist'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
