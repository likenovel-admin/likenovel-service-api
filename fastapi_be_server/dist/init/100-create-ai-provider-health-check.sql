CREATE TABLE IF NOT EXISTS tb_ai_provider_health_check (
    health_check_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    provider VARCHAR(40) NOT NULL COMMENT 'gemini | claude | openrouter | deepseek',
    model VARCHAR(120) NULL COMMENT 'health check model name',
    status VARCHAR(40) NOT NULL COMMENT 'ok | not_configured | credit_depleted | rate_limited | auth_failed | timeout | provider_error | unknown_error',
    http_status INT NULL COMMENT 'provider HTTP status code',
    error_code VARCHAR(120) NULL COMMENT 'provider/internal error code',
    error_message VARCHAR(500) NULL COMMENT 'sanitized provider error summary',
    latency_ms INT NULL COMMENT 'request latency in milliseconds',
    checked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'check timestamp',
    success_at TIMESTAMP NULL COMMENT 'same as checked_at when status=ok',
    affected_features VARCHAR(255) NULL COMMENT 'comma-separated feature keys affected by this provider',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'created timestamp',
    KEY idx_ai_provider_health_provider_checked (provider, checked_at),
    KEY idx_ai_provider_health_status_checked (status, checked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI provider health check log';
