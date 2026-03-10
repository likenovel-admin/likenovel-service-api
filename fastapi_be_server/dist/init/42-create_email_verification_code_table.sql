CREATE TABLE IF NOT EXISTS tb_email_verification_code (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(100) NOT NULL,
    token VARCHAR(64) NOT NULL,
    purpose VARCHAR(30) NOT NULL DEFAULT 'password_reset',
    verified_yn CHAR(1) NOT NULL DEFAULT 'N',
    created_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expired_date DATETIME NOT NULL,
    INDEX idx_email_purpose (email, purpose),
    INDEX idx_token (token),
    INDEX idx_expired_date (expired_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
