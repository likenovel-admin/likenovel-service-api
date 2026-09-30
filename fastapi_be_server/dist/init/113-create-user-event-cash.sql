CREATE TABLE IF NOT EXISTS tb_user_event_cashbook (
    user_id INT NOT NULL COMMENT '사용자 ID',
    balance INT NOT NULL DEFAULT 0 COMMENT '웹소챗/주인공챗 전용 이벤트 캐시 잔액',
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT NULL COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (user_id),
    CONSTRAINT chk_user_event_cashbook_balance CHECK (balance >= 0)
) COMMENT='웹소챗/주인공챗 전용 이벤트 캐시 잔액';

CREATE TABLE IF NOT EXISTS tb_user_event_cash_transaction (
    id BIGINT NOT NULL AUTO_INCREMENT COMMENT '이벤트 캐시 원장 ID',
    user_id INT NOT NULL COMMENT '사용자 ID',
    amount INT NOT NULL COMMENT '지급(+) 또는 사용(-) 금액',
    reason_code VARCHAR(40) NOT NULL COMMENT 'grant | websochat_message',
    grant_key VARCHAR(100) NULL COMMENT '지급 멱등 키(사용자별 1회)',
    product_id INT NULL COMMENT '사용 작품 ID',
    story_agent_session_id BIGINT NULL COMMENT '사용 웹소챗 세션 ID',
    memo VARCHAR(255) NULL COMMENT '지급 사유',
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    PRIMARY KEY (id),
    UNIQUE KEY uq_user_event_cash_grant (user_id, grant_key),
    KEY idx_user_event_cash_user_created (user_id, created_date)
) COMMENT='웹소챗/주인공챗 전용 이벤트 캐시 원장';
