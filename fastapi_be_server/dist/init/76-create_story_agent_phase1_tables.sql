CREATE TABLE IF NOT EXISTS tb_story_agent_session (
    session_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 ID',
    user_id INT NULL COMMENT '로그인 사용자 ID',
    guest_key VARCHAR(64) NULL COMMENT '비로그인 식별 키',
    title VARCHAR(120) NOT NULL DEFAULT '새 대화' COMMENT '세션 제목',
    deleted_yn CHAR(1) NOT NULL DEFAULT 'N' COMMENT '삭제 여부',
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT NULL COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    KEY idx_story_agent_session_product (product_id),
    KEY idx_story_agent_session_user_product (user_id, product_id),
    KEY idx_story_agent_session_guest_product (guest_key, product_id),
    KEY idx_story_agent_session_updated (updated_date)
);

CREATE TABLE IF NOT EXISTS tb_story_agent_message (
    message_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id BIGINT NOT NULL COMMENT '세션 ID',
    role VARCHAR(20) NOT NULL COMMENT 'user | assistant',
    content TEXT NOT NULL COMMENT '메시지 본문',
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    KEY idx_story_agent_message_session_created (session_id, created_date),
    CONSTRAINT fk_story_agent_message_session
        FOREIGN KEY (session_id) REFERENCES tb_story_agent_session(session_id)
        ON DELETE CASCADE
);
