USE likenovel;

CREATE TABLE IF NOT EXISTS tb_social_signup_session (
    social_signup_session_id BIGINT NOT NULL AUTO_INCREMENT,
    token_hash CHAR(64) NOT NULL COMMENT 'SHA-256 hash of the opaque client token',
    binding_hash CHAR(64) NOT NULL COMMENT 'SHA-256 hash of the browser binding secret',
    provider VARCHAR(20) NOT NULL COMMENT 'naver, kakao, google, apple',
    sns_link_id VARCHAR(255) NOT NULL COMMENT 'SNS provider account id',
    email VARCHAR(100) NOT NULL COMMENT 'SNS account email',
    birthdate VARCHAR(10) NOT NULL COMMENT 'SNS profile birthdate',
    gender VARCHAR(1) NOT NULL COMMENT 'SNS profile gender',
    keep_signin_yn CHAR(1) NOT NULL DEFAULT 'Y',
    expired_date TIMESTAMP NOT NULL COMMENT '10 minute expiry',
    use_yn CHAR(1) NOT NULL DEFAULT 'Y' COMMENT 'Y: available, N: consumed',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (social_signup_session_id),
    UNIQUE KEY uk_social_signup_session_token_hash (token_hash),
    KEY idx_social_signup_session_expiry (use_yn, expired_date)
);
