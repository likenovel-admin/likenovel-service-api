USE likenovel;

SET @column_exists = (
    SELECT COUNT(*)
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'tb_user'
      AND COLUMN_NAME = 'ai_onboarding_dismissed_yn'
);
SET @sql = IF(
    @column_exists = 0,
    'ALTER TABLE tb_user ADD COLUMN ai_onboarding_dismissed_yn VARCHAR(1) NOT NULL DEFAULT ''N'' COMMENT ''AI 온보딩 모달 숨김 여부(계정 기준)'' AFTER role_type',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
