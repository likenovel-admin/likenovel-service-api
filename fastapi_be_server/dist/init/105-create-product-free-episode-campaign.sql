CREATE TABLE IF NOT EXISTS tb_product_free_episode_campaign (
    id INT NOT NULL AUTO_INCREMENT,
    product_id INT NOT NULL,
    active_yn VARCHAR(1) NOT NULL DEFAULT 'Y',
    campaign_free_start_no INT NOT NULL DEFAULT 1,
    campaign_free_end_no INT NOT NULL DEFAULT 100,
    restore_free_start_no INT NOT NULL DEFAULT 1,
    restore_free_end_no INT NOT NULL DEFAULT 25,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ends_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP NULL DEFAULT NULL,
    created_id INT NOT NULL DEFAULT 0,
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_id INT NOT NULL DEFAULT 0,
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_product_free_episode_campaign_product_active (product_id, active_yn),
    KEY idx_product_free_episode_campaign_active_ends (active_yn, ends_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
