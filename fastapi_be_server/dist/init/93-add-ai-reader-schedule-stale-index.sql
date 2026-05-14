SET @ai_reader_schedule_table_exists = (
    SELECT COUNT(*)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_daily_schedule'
);

SET @ai_reader_schedule_stale_index_exists = (
    SELECT COUNT(*)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_daily_schedule'
       AND index_name = 'idx_ai_reader_daily_schedule_stale'
);

SET @ai_reader_schedule_stale_index_required_column_count = (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_daily_schedule'
       AND column_name IN (
            'status',
            'locked_at',
            'active_start_at',
            'active_end_at',
            'ai_reader_schedule_id'
       )
);

SET @ai_reader_schedule_stale_index_columns = (
    SELECT GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ',')
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_daily_schedule'
       AND index_name = 'idx_ai_reader_daily_schedule_stale'
);

SET @ai_reader_schedule_stale_index_non_unique = (
    SELECT MAX(non_unique)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_daily_schedule'
       AND index_name = 'idx_ai_reader_daily_schedule_stale'
);

SET @sql_add_ai_reader_schedule_stale_index = IF(
    @ai_reader_schedule_table_exists = 0,
    'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''tb_ai_reader_daily_schedule is required before adding idx_ai_reader_daily_schedule_stale''',
    IF(
        @ai_reader_schedule_stale_index_required_column_count < 5,
        'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''tb_ai_reader_daily_schedule stale index required columns are missing''',
        IF(
            @ai_reader_schedule_stale_index_exists = 0,
            'ALTER TABLE tb_ai_reader_daily_schedule ADD KEY idx_ai_reader_daily_schedule_stale (status, locked_at, active_start_at, active_end_at, ai_reader_schedule_id)',
            IF(
                @ai_reader_schedule_stale_index_columns = 'status,locked_at,active_start_at,active_end_at,ai_reader_schedule_id'
                AND @ai_reader_schedule_stale_index_non_unique = 1,
                'SELECT ''idx_ai_reader_daily_schedule_stale already exists''',
                'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''idx_ai_reader_daily_schedule_stale drift'''
            )
        )
    )
);
PREPARE stmt_add_ai_reader_schedule_stale_index FROM @sql_add_ai_reader_schedule_stale_index;
EXECUTE stmt_add_ai_reader_schedule_stale_index;
DEALLOCATE PREPARE stmt_add_ai_reader_schedule_stale_index;
