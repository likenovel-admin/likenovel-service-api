USE likenovel;

CREATE TABLE IF NOT EXISTS tb_user_ai_chat_message (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id       INT NOT NULL COMMENT '유저 ID (tb_user.id)',
    role          VARCHAR(10) NOT NULL COMMENT 'user | assistant',
    content       TEXT NOT NULL COMMENT '메시지 본문',
    product_id    INT DEFAULT NULL COMMENT '추천 작품 ID (assistant만)',
    product_snapshot JSON DEFAULT NULL COMMENT '작품 카드 렌더용 스냅샷',
    taste_match   JSON DEFAULT NULL COMMENT '취향 매칭 점수',
    created_date  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_user_created (user_id, created_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 챗 메시지 히스토리';
