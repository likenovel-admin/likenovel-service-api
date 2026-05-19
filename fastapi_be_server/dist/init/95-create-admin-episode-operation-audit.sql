-- Admin delegated episode operation audit.
-- This table records admin actor, target product/episode, input fingerprint,
-- and before/after snapshots for high-risk episode append/replace operations.

CREATE TABLE IF NOT EXISTS tb_admin_episode_operation_audit (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    idempotency_key CHAR(64) NOT NULL COMMENT 'operation fingerprint',
    item_key VARCHAR(64) NOT NULL COMMENT 'item key inside the operation',
    admin_user_id INT NOT NULL COMMENT 'admin user id',
    product_id INT NOT NULL COMMENT 'target product id',
    episode_id INT NULL COMMENT 'target episode id',
    episode_no INT NULL COMMENT 'target episode no',
    action VARCHAR(30) NOT NULL COMMENT 'append_epub or replace_epub',
    status VARCHAR(30) NOT NULL COMMENT 'succeeded or failed',
    before_json JSON NULL COMMENT 'snapshot before operation',
    after_json JSON NULL COMMENT 'snapshot after operation',
    error_message VARCHAR(1000) NULL COMMENT 'failure detail',
    created_id INT NULL COMMENT 'row creator',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'created at',
    updated_id INT NULL COMMENT 'row updater',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'updated at',
    UNIQUE KEY ux_admin_episode_operation_item (idempotency_key, item_key),
    KEY idx_admin_episode_operation_product (product_id, created_date),
    KEY idx_admin_episode_operation_episode (episode_id, created_date),
    KEY idx_admin_episode_operation_admin (admin_user_id, created_date),
    KEY idx_admin_episode_operation_status (status, created_date)
);

SET @episode_table_exists = (
    SELECT COUNT(1)
      FROM information_schema.tables
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_episode'
);

SET @product_episode_no_use_idx_exists = (
    SELECT COUNT(1)
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_episode'
       AND index_name = 'idx_product_episode_product_no_use'
);

SET @sql_add_product_episode_no_use_idx = IF(
    @episode_table_exists = 1 AND @product_episode_no_use_idx_exists = 0,
    'ALTER TABLE tb_product_episode ADD INDEX idx_product_episode_product_no_use (product_id, episode_no, use_yn)',
    'SELECT 1'
);

PREPARE stmt_add_product_episode_no_use_idx FROM @sql_add_product_episode_no_use_idx;
EXECUTE stmt_add_product_episode_no_use_idx;
DEALLOCATE PREPARE stmt_add_product_episode_no_use_idx;
