SET @has_ai_reader_llm_session_duplicates := (
    SELECT COUNT(*)
      FROM (
            SELECT ai_reader_agent_id, session_id, prompt_version
              FROM tb_ai_reader_llm_decision
             GROUP BY ai_reader_agent_id, session_id, prompt_version
            HAVING COUNT(*) > 1
           ) duplicate_sessions
);

CREATE TEMPORARY TABLE IF NOT EXISTS tmp_ai_reader_llm_decision_duplicate_guard (
    must_be_zero TINYINT NOT NULL,
    CONSTRAINT chk_ai_reader_llm_no_duplicate_sessions CHECK (must_be_zero = 0)
);

INSERT INTO tmp_ai_reader_llm_decision_duplicate_guard (must_be_zero)
SELECT 1
 WHERE @has_ai_reader_llm_session_duplicates > 0;

DROP TEMPORARY TABLE IF EXISTS tmp_ai_reader_llm_decision_duplicate_guard;

SET @has_ai_reader_llm_session_unique := (
    SELECT COUNT(*)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_llm_decision'
       AND index_name = 'uk_ai_reader_llm_decision_session'
);

SET @sql := IF(
    @has_ai_reader_llm_session_unique = 0,
    'ALTER TABLE tb_ai_reader_llm_decision ADD UNIQUE KEY uk_ai_reader_llm_decision_session (ai_reader_agent_id, session_id, prompt_version)',
    'SELECT ''uk_ai_reader_llm_decision_session already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_ai_reader_llm_request_unique := (
    SELECT COUNT(*)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_llm_decision'
       AND index_name = 'uk_ai_reader_llm_decision_request'
);

SET @sql := IF(
    @has_ai_reader_llm_request_unique > 0,
    'ALTER TABLE tb_ai_reader_llm_decision DROP INDEX uk_ai_reader_llm_decision_request',
    'SELECT ''uk_ai_reader_llm_decision_request already absent'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_ai_reader_llm_request_index := (
    SELECT COUNT(*)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_ai_reader_llm_decision'
       AND index_name = 'idx_ai_reader_llm_decision_request'
);

SET @sql := IF(
    @has_ai_reader_llm_request_index = 0,
    'ALTER TABLE tb_ai_reader_llm_decision ADD KEY idx_ai_reader_llm_decision_request (request_hash)',
    'SELECT ''idx_ai_reader_llm_decision_request already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
