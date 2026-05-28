CREATE TABLE IF NOT EXISTS tb_author_product_entry_daily (
    id                       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'PK',
    stat_date                DATE NOT NULL COMMENT '집계일',
    product_id               INT NOT NULL COMMENT '작품 ID',
    entry_source_group       VARCHAR(80) NOT NULL COMMENT '작가 노출용 유입 그룹',
    entry_source_norm        VARCHAR(120) NOT NULL DEFAULT '__null__' COMMENT 'NULL dedupe용 source key',
    detail_view_count        INT NOT NULL DEFAULT 0 COMMENT '작품 상세 PV 수',
    detail_session_count     INT NOT NULL DEFAULT 0 COMMENT '작품 상세 진입 세션 수',
    detail_visitor_count     INT NOT NULL DEFAULT 0 COMMENT '작품 상세 진입 방문자 수',
    login_user_count         INT NOT NULL DEFAULT 0 COMMENT '로그인 유저 수',
    created_date             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_date             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (id),
    UNIQUE KEY uk_author_product_entry_daily (stat_date, product_id, entry_source_group, entry_source_norm),
    KEY idx_author_product_entry_daily_product_date (product_id, stat_date),
    KEY idx_author_product_entry_daily_date_group (stat_date, entry_source_group)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='작가용 작품 상세 유입 일별 mart';
