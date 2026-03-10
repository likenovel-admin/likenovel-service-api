CREATE TABLE IF NOT EXISTS tb_product_episode_apply (
    id INT AUTO_INCREMENT PRIMARY KEY,
    episode_id INT NOT NULL COMMENT 'Episode ID',
    status_code VARCHAR(20) NOT NULL COMMENT 'Status code: review, denied, accepted',
    req_user_id INT NOT NULL COMMENT 'Requester user ID',
    req_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Request datetime',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT 'Use flag',
    approval_user_id INT COMMENT 'Approver user ID',
    approval_date TIMESTAMP COMMENT 'Approval datetime',
    created_id INT COMMENT 'Created by',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Created at',
    updated_id INT COMMENT 'Updated by',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Updated at',
    INDEX idx_episode_id (episode_id),
    INDEX idx_status_code (status_code),
    INDEX idx_req_user_id (req_user_id),
    INDEX idx_approval_user_id (approval_user_id)
);

