USE likenovel;

CREATE TABLE IF NOT EXISTS tb_ai_taste_manual_replay_log (
    id                  BIGINT NOT NULL AUTO_INCREMENT COMMENT 'PK',
    run_token           BIGINT NOT NULL COMMENT '수동 재처리 실행 토큰',
    from_event_id       BIGINT NOT NULL COMMENT '시작 이벤트 ID(포함)',
    to_event_id         BIGINT NOT NULL COMMENT '종료 이벤트 ID(포함)',
    allow_duplicate_yn  CHAR(1) NOT NULL DEFAULT 'N' COMMENT '중복 실행 허용 여부',
    status              VARCHAR(20) NOT NULL COMMENT 'RUNNING/SUCCESS/FAILED',
    source_total_count  INT NOT NULL DEFAULT 0 COMMENT '원천 이벤트 총건수',
    source_valid_count  INT NOT NULL DEFAULT 0 COMMENT '유효 이벤트 건수',
    requested_by        VARCHAR(100) NULL COMMENT '실행자 식별자',
    error_message       VARCHAR(500) NULL COMMENT '실패 에러 메시지',
    created_date        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_date        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (id),
    UNIQUE KEY uk_ai_taste_manual_run_token (run_token),
    KEY idx_ai_taste_manual_range_status (from_event_id, to_event_id, status, created_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
COMMENT='AI 취향 수동 재처리 실행 이력';
