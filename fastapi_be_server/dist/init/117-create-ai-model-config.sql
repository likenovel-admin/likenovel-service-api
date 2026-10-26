-- Models and routes only. Provider credentials remain in a server-owned file.
CREATE TABLE IF NOT EXISTS tb_ai_model_config (
    feature_key VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    model_id VARCHAR(200) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    billing_route VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    revision BIGINT UNSIGNED NOT NULL,
    created_id BIGINT NOT NULL,
    updated_id BIGINT NOT NULL,
    created_date DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_date DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (feature_key),
    CHECK (revision > 0),
    CHECK (billing_route IN ('openrouter', 'hive', 'river'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tb_ai_model_config_history (
    history_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    feature_key VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    revision BIGINT UNSIGNED NOT NULL,
    model_id VARCHAR(200) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    billing_route VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    previous_model_id VARCHAR(200) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    previous_billing_route VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    changed_by BIGINT NOT NULL,
    created_date DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (history_id),
    UNIQUE KEY uq_ai_model_config_history_revision (feature_key, revision),
    CHECK (revision > 0),
    CHECK (billing_route IN ('openrouter', 'hive', 'river'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
