CREATE TABLE IF NOT EXISTS tb_site_page_view_event (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '사이트 PV 이벤트 ID',
    event_id CHAR(36) NOT NULL COMMENT '클라이언트 생성 이벤트 UUID',
    occurred_at DATETIME(3) NOT NULL COMMENT '브라우저 route 노출 시각',
    user_id INT NULL COMMENT '로그인 유저 ID, 게스트는 NULL',
    visitor_id VARCHAR(80) NOT NULL COMMENT '브라우저 단위 익명 방문자 ID',
    session_id VARCHAR(80) NOT NULL COMMENT '브라우저 세션 ID',
    route_group VARCHAR(80) NOT NULL COMMENT 'route 대분류',
    route_name VARCHAR(120) NOT NULL COMMENT 'route 세부명',
    path_template VARCHAR(255) NOT NULL COMMENT '정규화된 route template',
    path VARCHAR(255) NOT NULL COMMENT 'query/hash 제거 pathname',
    query_hash CHAR(64) NULL COMMENT '허용된 query identity hash',
    referrer_path VARCHAR(255) NULL COMMENT '이전 pathname',
    source VARCHAR(50) NOT NULL DEFAULT 'service-web' COMMENT '이벤트 소스',
    taxonomy_version INT NOT NULL DEFAULT 1 COMMENT 'route taxonomy version',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_site_page_view_event_event_id (event_id),
    KEY idx_site_page_view_event_source_occurred (source, occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='유저웹 사이트 페이지뷰 raw 이벤트';
