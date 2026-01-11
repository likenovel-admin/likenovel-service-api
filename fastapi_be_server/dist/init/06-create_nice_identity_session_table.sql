-- NICE 본인인증 세션 데이터 저장용 테이블 생성

USE likenovel;

-- tb_user_identity_session
CREATE TABLE tb_user_identity_session (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT '유저 아이디',
    token_version_id VARCHAR(100) NOT NULL COMMENT 'NICE 토큰 버전 ID',
    req_no VARCHAR(50) NOT NULL COMMENT '요청 고유번호',
    encryption_key VARCHAR(32) NOT NULL COMMENT '암복호화 키',
    encryption_iv VARCHAR(16) NOT NULL COMMENT '암복호화 IV',
    hmac_key VARCHAR(32) NOT NULL COMMENT 'HMAC 키',
    expired_date TIMESTAMP NOT NULL COMMENT '만료 시간 (30분)',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_user_id (user_id),
    INDEX idx_token_version_id (token_version_id),
    INDEX idx_req_no (req_no),
    INDEX idx_expired_date (expired_date)
);
