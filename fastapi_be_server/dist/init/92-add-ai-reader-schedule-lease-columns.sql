SET @ai_reader_schedule_table_exists = (
    SELECT COUNT(*)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_daily_schedule'
);

SET @schedule_locked_by_column_exists = (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_daily_schedule'
       AND column_name = 'locked_by'
);

SET @sql_add_schedule_locked_by_column = IF(
    @ai_reader_schedule_table_exists = 0,
    'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''tb_ai_reader_daily_schedule is required before adding locked_by''',
    IF(
        @schedule_locked_by_column_exists = 0,
        'ALTER TABLE tb_ai_reader_daily_schedule ADD COLUMN locked_by VARCHAR(100) NULL AFTER status',
        'SELECT ''locked_by already exists'''
    )
);
PREPARE stmt_add_schedule_locked_by_column FROM @sql_add_schedule_locked_by_column;
EXECUTE stmt_add_schedule_locked_by_column;
DEALLOCATE PREPARE stmt_add_schedule_locked_by_column;

SET @schedule_locked_at_column_exists = (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_daily_schedule'
       AND column_name = 'locked_at'
);

SET @sql_add_schedule_locked_at_column = IF(
    @ai_reader_schedule_table_exists = 0,
    'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''tb_ai_reader_daily_schedule is required before adding locked_at''',
    IF(
        @schedule_locked_at_column_exists = 0,
        'ALTER TABLE tb_ai_reader_daily_schedule ADD COLUMN locked_at TIMESTAMP NULL AFTER locked_by',
        'SELECT ''locked_at already exists'''
    )
);
PREPARE stmt_add_schedule_locked_at_column FROM @sql_add_schedule_locked_at_column;
EXECUTE stmt_add_schedule_locked_at_column;
DEALLOCATE PREPARE stmt_add_schedule_locked_at_column;

SET @schedule_error_message_column_exists = (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_daily_schedule'
       AND column_name = 'error_message'
);

SET @sql_add_schedule_error_message_column = IF(
    @ai_reader_schedule_table_exists = 0,
    'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''tb_ai_reader_daily_schedule is required before adding error_message''',
    IF(
        @schedule_error_message_column_exists = 0,
        'ALTER TABLE tb_ai_reader_daily_schedule ADD COLUMN error_message VARCHAR(1000) NULL AFTER locked_at',
        'SELECT ''error_message already exists'''
    )
);
PREPARE stmt_add_schedule_error_message_column FROM @sql_add_schedule_error_message_column;
EXECUTE stmt_add_schedule_error_message_column;
DEALLOCATE PREPARE stmt_add_schedule_error_message_column;
