-- Non-serving receipts survive rollback of the character serving bundle.
-- No automatic retry/reset/expiry: ambiguous inflight requests need inspection.
CREATE TABLE IF NOT EXISTS tb_story_agent_character_asset_attempt (
    product_id BIGINT NOT NULL,
    stage_key VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    scope_key VARCHAR(80) COLLATE utf8mb4_bin NOT NULL,
    input_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    status VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    accepted_payload LONGTEXT NULL,
    payload_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    error_code VARCHAR(100) NULL,
    created_date DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_date DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (product_id, stage_key, scope_key, input_hash),
    CHECK (stage_key IN ('signals','scenes','protagonist_resolution','rp_profile','rp_dialogue')),
    CHECK (
        (status='inflight' AND accepted_payload IS NULL AND payload_hash IS NULL AND error_code IS NULL)
        OR (status='accepted' AND accepted_payload IS NOT NULL AND payload_hash IS NOT NULL AND error_code IS NULL)
        OR (status='terminal_invalid' AND accepted_payload IS NULL AND payload_hash IS NULL AND error_code IS NOT NULL)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
