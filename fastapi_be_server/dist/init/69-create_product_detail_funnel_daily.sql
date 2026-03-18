USE likenovel;

CREATE TABLE IF NOT EXISTS tb_product_detail_funnel_daily (
    id                                           BIGINT NOT NULL AUTO_INCREMENT COMMENT 'PK',
    computed_date                                DATE NOT NULL COMMENT '집계일(퍼널 세션 시작일)',
    product_id                                   INT NOT NULL COMMENT '작품 ID',
    entry_source                                 VARCHAR(50) NULL COMMENT '상세 진입 source(nullable)',
    entry_source_norm                            VARCHAR(50) NOT NULL DEFAULT '__null__' COMMENT 'NULL dedupe용 source key',
    detail_view_raw_count                        INT NOT NULL DEFAULT 0 COMMENT 'raw 상세 진입 이벤트 수',
    detail_view_session_count                    INT NOT NULL DEFAULT 0 COMMENT 'dedupe된 상세 퍼널 세션 수',
    detail_view_user_count                       INT NOT NULL DEFAULT 0 COMMENT '상세 퍼널 진입 유저 수',
    detail_to_view_session_count                 INT NOT NULL DEFAULT 0 COMMENT '상세->viewer 전환 세션 수',
    detail_to_view_user_count                    INT NOT NULL DEFAULT 0 COMMENT '상세->viewer 전환 유저 수',
    detail_exit_session_count                    INT NOT NULL DEFAULT 0 COMMENT '작품 컨텍스트 이탈 세션 수',
    exit_home_session_count                      INT NOT NULL DEFAULT 0 COMMENT '홈 이동 이탈 세션 수',
    exit_search_session_count                    INT NOT NULL DEFAULT 0 COMMENT '검색 이동 이탈 세션 수',
    exit_other_product_detail_session_count      INT NOT NULL DEFAULT 0 COMMENT '다른 작품 상세 이동 이탈 세션 수',
    exit_other_route_session_count               INT NOT NULL DEFAULT 0 COMMENT '기타 경로 이동 이탈 세션 수',
    episode_exit_event_count                     INT NOT NULL DEFAULT 0 COMMENT '세션 내 회차 exit 이벤트 수',
    avg_episode_exit_progress_ratio              DOUBLE NULL COMMENT '세션 내 회차 exit 평균 진행률',
    created_date                                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_date                                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (id),
    UNIQUE KEY uk_product_detail_funnel_daily (computed_date, product_id, entry_source_norm),
    KEY idx_product_detail_funnel_daily_product_date (product_id, computed_date),
    KEY idx_product_detail_funnel_daily_date_source (computed_date, entry_source_norm)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='작품 상세 퍼널 일별 mart';
