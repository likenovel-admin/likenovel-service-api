USE likenovel;

DELETE t1
FROM tb_ai_onboarding_tag t1
INNER JOIN tb_ai_onboarding_tag t2
  ON t1.tab_key = t2.tab_key
 AND t1.tag_name = t2.tag_name
 AND t1.id > t2.id;

SET @index_exists = (
    SELECT COUNT(*)
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'tb_ai_onboarding_tag'
      AND INDEX_NAME = 'uk_ai_onboarding_tag_tab_name'
);
SET @sql = IF(
    @index_exists = 0,
    'ALTER TABLE tb_ai_onboarding_tag ADD UNIQUE KEY uk_ai_onboarding_tag_tab_name (tab_key, tag_name)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
