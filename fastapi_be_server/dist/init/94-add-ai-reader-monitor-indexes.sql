-- AI reader CMS monitor indexes.
-- These indexes keep the 60s CMS monitor off broad scans as action/decision rows grow.

SET @ai_reader_action_queue_exists := (
    SELECT COUNT(*)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_action_queue'
);

SET @ai_reader_llm_decision_exists := (
    SELECT COUNT(*)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_llm_decision'
);

SET @sql := IF(
    @ai_reader_action_queue_exists = 0 OR @ai_reader_llm_decision_exists = 0,
    'SIGNAL SQLSTATE ''45000'' SET MESSAGE_TEXT = ''AI reader tables are required before adding monitor indexes''',
    'SELECT ''AI reader monitor index prerequisites ok'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_action_monitor_index := (
    SELECT COUNT(*)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_action_queue'
       AND index_name = 'idx_ai_reader_action_queue_status_applied_product'
);

SET @sql := IF(
    @has_action_monitor_index = 0,
    'ALTER TABLE tb_ai_reader_action_queue ADD KEY idx_ai_reader_action_queue_status_applied_product (status, applied_at, product_id, action_type)',
    'SELECT ''idx_ai_reader_action_queue_status_applied_product already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_action_failed_updated_index := (
    SELECT COUNT(*)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_action_queue'
       AND index_name = 'idx_ai_reader_action_queue_failed_updated_product'
);

SET @sql := IF(
    @has_action_failed_updated_index = 0,
    'ALTER TABLE tb_ai_reader_action_queue ADD KEY idx_ai_reader_action_queue_failed_updated_product (status, updated_date, product_id)',
    'SELECT ''idx_ai_reader_action_queue_failed_updated_product already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_decision_monitor_index := (
    SELECT COUNT(*)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_llm_decision'
       AND index_name = 'idx_ai_reader_llm_decision_status_created_product'
);

SET @sql := IF(
    @has_decision_monitor_index = 0,
    'ALTER TABLE tb_ai_reader_llm_decision ADD KEY idx_ai_reader_llm_decision_status_created_product (decision_status, created_date, product_id)',
    'SELECT ''idx_ai_reader_llm_decision_status_created_product already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
