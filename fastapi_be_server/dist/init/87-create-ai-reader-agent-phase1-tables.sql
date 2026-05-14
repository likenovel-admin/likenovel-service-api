CREATE TABLE IF NOT EXISTS tb_ai_reader_agent (
    ai_reader_agent_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT 'Mapped tb_user.user_id',
    agent_key VARCHAR(64) NOT NULL COMMENT 'Stable AI reader key',
    age_group VARCHAR(20) NOT NULL COMMENT 'Reader age group',
    gender VARCHAR(20) NOT NULL COMMENT 'Reader gender',
    persona_json JSON NOT NULL COMMENT 'Fixed persona profile',
    taste_memory_json JSON NULL COMMENT 'LLM-updated taste memory',
    activity_pattern_json JSON NOT NULL COMMENT 'Wake/sleep pattern',
    status VARCHAR(20) NOT NULL DEFAULT 'active' COMMENT 'active/paused/deleted',
    daily_llm_budget INT NOT NULL DEFAULT 8 COMMENT 'Max LLM decisions per day',
    created_id INT NOT NULL DEFAULT 0,
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_id INT NOT NULL DEFAULT 0,
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ai_reader_agent_user (user_id),
    UNIQUE KEY uk_ai_reader_agent_key (agent_key),
    KEY idx_ai_reader_agent_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS tb_ai_reader_daily_schedule (
    ai_reader_schedule_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    ai_reader_agent_id BIGINT NOT NULL,
    schedule_date DATE NOT NULL,
    active_start_at TIMESTAMP NOT NULL,
    active_end_at TIMESTAMP NOT NULL,
    session_budget INT NOT NULL DEFAULT 1,
    used_session_count INT NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'ready',
    locked_by VARCHAR(100) NULL,
    locked_at TIMESTAMP NULL,
    error_message VARCHAR(1000) NULL,
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ai_reader_daily_schedule_agent_window (
        ai_reader_agent_id,
        schedule_date,
        active_start_at
    ),
    KEY idx_ai_reader_daily_schedule_due (status, active_start_at, active_end_at),
    KEY idx_ai_reader_daily_schedule_stale (
        status,
        locked_at,
        active_start_at,
        active_end_at,
        ai_reader_schedule_id
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS tb_ai_reader_product_state (
    ai_reader_product_state_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    ai_reader_agent_id BIGINT NOT NULL,
    product_id INT NOT NULL,
    current_episode_id INT NULL,
    state VARCHAR(20) NOT NULL DEFAULT 'reading',
    read_episode_count INT NOT NULL DEFAULT 0,
    bookmarked_yn CHAR(1) NOT NULL DEFAULT 'N',
    recommended_yn CHAR(1) NOT NULL DEFAULT 'N',
    evaluated_yn CHAR(1) NOT NULL DEFAULT 'N',
    last_decision_id BIGINT NULL,
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ai_reader_product_state_agent_product (ai_reader_agent_id, product_id),
    KEY idx_ai_reader_product_state_product (product_id, state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS tb_ai_reader_llm_decision (
    ai_reader_llm_decision_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    ai_reader_agent_id BIGINT NOT NULL,
    user_id INT NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    product_id INT NOT NULL,
    episode_id INT NULL,
    prompt_version VARCHAR(40) NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    request_hash CHAR(64) NOT NULL,
    input_snapshot_json JSON NOT NULL,
    decision_json JSON NULL,
    decision_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_message VARCHAR(1000) NULL,
    input_tokens INT NULL,
    output_tokens INT NULL,
    estimated_cost_usd DECIMAL(12,6) NULL,
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ai_reader_llm_decision_session (
        ai_reader_agent_id,
        session_id,
        prompt_version
    ),
    KEY idx_ai_reader_llm_decision_request (request_hash),
    KEY idx_ai_reader_llm_decision_agent_created (ai_reader_agent_id, created_date),
    KEY idx_ai_reader_llm_decision_status (decision_status, created_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS tb_ai_reader_action_queue (
    ai_reader_action_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    idempotency_key CHAR(64) NOT NULL,
    active_scope_key CHAR(64) NULL COMMENT 'Unique only while queued/running; cleared on terminal state to allow human-like rereads',
    ai_reader_agent_id BIGINT NOT NULL,
    user_id INT NOT NULL,
    product_id INT NOT NULL,
    episode_id INT NULL,
    action_type VARCHAR(40) NOT NULL,
    target_value VARCHAR(40) NULL,
    llm_decision_id BIGINT NULL,
    decision_json JSON NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    attempt_count INT NOT NULL DEFAULT 0,
    locked_by VARCHAR(100) NULL,
    locked_at TIMESTAMP NULL,
    available_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    applied_at TIMESTAMP NULL,
    error_message VARCHAR(1000) NULL,
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ai_reader_action_idempotency (idempotency_key),
    UNIQUE KEY uk_ai_reader_action_active_scope (active_scope_key),
    KEY idx_ai_reader_action_queue_due (status, available_at, ai_reader_action_id),
    KEY idx_ai_reader_action_queue_stale (status, locked_at, attempt_count, ai_reader_action_id),
    KEY idx_ai_reader_action_queue_agent_created (ai_reader_agent_id, created_date),
    KEY idx_ai_reader_action_queue_target (action_type, product_id, episode_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS tb_ai_reader_public_metric_daily (
    ai_reader_public_metric_daily_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    stat_date DATE NOT NULL,
    product_id INT NOT NULL,
    episode_id INT NOT NULL DEFAULT 0,
    ai_view_count INT NOT NULL DEFAULT 0,
    ai_bookmark_count INT NOT NULL DEFAULT 0,
    ai_unbookmark_count INT NOT NULL DEFAULT 0,
    ai_recommend_count INT NOT NULL DEFAULT 0,
    ai_unrecommend_count INT NOT NULL DEFAULT 0,
    ai_evaluation_count INT NOT NULL DEFAULT 0,
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_ai_reader_public_metric_daily_target (stat_date, product_id, episode_id),
    KEY idx_ai_reader_public_metric_daily_product (product_id, stat_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
