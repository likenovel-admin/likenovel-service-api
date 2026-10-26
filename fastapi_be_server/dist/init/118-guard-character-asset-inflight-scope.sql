-- A model/route change must not bypass an unresolved physical request.
-- Existing receipts are immutable. Duplicate inflight scopes deliberately make
-- the unique-index DDL fail. An operator must reconcile them before deployment.
-- No receipt is deleted, reset, or assigned an expiry by this migration.
SET @has_inflight_scope := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema=DATABASE()
      AND table_name='tb_story_agent_character_asset_attempt'
      AND column_name='inflight_scope_key'
);
SET @sql := IF(@has_inflight_scope = 0,
    'ALTER TABLE tb_story_agent_character_asset_attempt ADD COLUMN inflight_scope_key VARCHAR(160) COLLATE utf8mb4_bin GENERATED ALWAYS AS (CASE WHEN status = ''inflight'' THEN CONCAT(product_id, '':'', stage_key, '':'', scope_key) ELSE NULL END) STORED',
    'SELECT ''inflight_scope_key already exists''');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_inflight_guard := (
    SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema=DATABASE()
      AND table_name='tb_story_agent_character_asset_attempt'
      AND index_name='uq_character_asset_inflight_scope'
);
SET @sql := IF(@has_inflight_guard = 0,
    'ALTER TABLE tb_story_agent_character_asset_attempt ADD UNIQUE KEY uq_character_asset_inflight_scope (inflight_scope_key)',
    'SELECT ''uq_character_asset_inflight_scope already exists''');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
