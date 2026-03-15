USE likenovel;

CREATE TABLE IF NOT EXISTS tb_user_ai_signal_event_factor (
    id              BIGINT NOT NULL AUTO_INCREMENT COMMENT 'PK',
    event_id        BIGINT NOT NULL COMMENT '원본 AI 신호 이벤트 ID',
    user_id         INT NOT NULL COMMENT '유저 ID',
    product_id      INT NOT NULL COMMENT '작품 ID',
    episode_id      INT NULL COMMENT '회차 ID',
    event_type      VARCHAR(50) NOT NULL COMMENT '원본 이벤트 타입',
    factor_type     VARCHAR(50) NOT NULL COMMENT '취향 축 타입',
    factor_key      VARCHAR(120) NOT NULL COMMENT '취향 축 키',
    signal_score    DOUBLE NOT NULL DEFAULT 0 COMMENT '신호 점수',
    created_date    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    PRIMARY KEY (id),
    UNIQUE KEY uk_ai_signal_event_factor_unique (event_id, factor_type, factor_key),
    KEY idx_ai_signal_factor_created_user_factor (created_date, user_id, factor_type, factor_key),
    KEY idx_ai_signal_factor_event_id (event_id),
    KEY idx_ai_signal_factor_product_created (product_id, created_date),
    KEY idx_ai_signal_factor_event_type_created (event_type, created_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
COMMENT='AI 추천용 유저 행동 이벤트별 취향 factor detail';
