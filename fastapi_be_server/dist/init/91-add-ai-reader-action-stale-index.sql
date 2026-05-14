SET @ai_reader_action_table_exists = (
    SELECT COUNT(*)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_action_queue'
);

SET @ai_reader_action_stale_index_exists = (
    SELECT COUNT(*)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_action_queue'
       AND index_name = 'idx_ai_reader_action_queue_stale'
);

SET @sql_add_ai_reader_action_stale_index = IF(
    @ai_reader_action_table_exists = 0,
    'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''tb_ai_reader_action_queue is required before adding idx_ai_reader_action_queue_stale''',
    IF(
        @ai_reader_action_stale_index_exists = 0,
        'ALTER TABLE tb_ai_reader_action_queue ADD KEY idx_ai_reader_action_queue_stale (status, locked_at, attempt_count, ai_reader_action_id)',
        'SELECT ''idx_ai_reader_action_queue_stale already exists'''
    )
);
PREPARE stmt_add_ai_reader_action_stale_index FROM @sql_add_ai_reader_action_stale_index;
EXECUTE stmt_add_ai_reader_action_stale_index;
DEALLOCATE PREPARE stmt_add_ai_reader_action_stale_index;
