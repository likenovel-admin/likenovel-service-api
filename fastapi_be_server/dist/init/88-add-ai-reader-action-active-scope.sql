USE likenovel;

SET @ai_reader_action_table_exists = (
    SELECT COUNT(1)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_action_queue'
);

SET @active_scope_column_exists = (
    SELECT COUNT(1)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_action_queue'
       AND column_name = 'active_scope_key'
);

SET @sql_add_active_scope_column = IF(
    @ai_reader_action_table_exists = 1 AND @active_scope_column_exists = 0,
    'ALTER TABLE tb_ai_reader_action_queue ADD COLUMN active_scope_key CHAR(64) NULL COMMENT ''Queued/running duplicate guard cleared on terminal state for rereads'' AFTER idempotency_key',
    'SELECT 1'
);

PREPARE stmt_add_active_scope_column FROM @sql_add_active_scope_column;
EXECUTE stmt_add_active_scope_column;
DEALLOCATE PREPARE stmt_add_active_scope_column;

SET @active_scope_index_exists = (
    SELECT COUNT(1)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_action_queue'
       AND index_name = 'uk_ai_reader_action_active_scope'
);

SET @sql_add_active_scope_index = IF(
    @ai_reader_action_table_exists = 1 AND @active_scope_index_exists = 0,
    'ALTER TABLE tb_ai_reader_action_queue ADD UNIQUE KEY uk_ai_reader_action_active_scope (active_scope_key)',
    'SELECT 1'
);

PREPARE stmt_add_active_scope_index FROM @sql_add_active_scope_index;
EXECUTE stmt_add_active_scope_index;
DEALLOCATE PREPARE stmt_add_active_scope_index;
