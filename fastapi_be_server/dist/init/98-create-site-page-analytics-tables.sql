CREATE TABLE IF NOT EXISTS tb_site_page_dwell_event (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '사이트 페이지 활성 체류 이벤트 ID',
    event_id CHAR(36) NOT NULL COMMENT '클라이언트 생성 이벤트 UUID',
    occurred_at DATETIME(3) NOT NULL COMMENT '브라우저 route 활성 체류 시작 시각',
    user_id INT NULL COMMENT '로그인 유저 ID, 게스트는 NULL',
    visitor_id VARCHAR(80) NOT NULL COMMENT '브라우저 단위 익명 방문자 ID',
    session_id VARCHAR(80) NOT NULL COMMENT '브라우저 세션 ID',
    route_group VARCHAR(80) NOT NULL COMMENT 'route 대분류',
    route_name VARCHAR(120) NOT NULL COMMENT 'route 세부명',
    path_template VARCHAR(255) NOT NULL COMMENT '정규화된 route template',
    active_ms INT UNSIGNED NOT NULL COMMENT 'visible 상태에서 누적된 활성 체류 시간(ms)',
    source VARCHAR(50) NOT NULL DEFAULT 'service-web' COMMENT '이벤트 소스',
    taxonomy_version INT NOT NULL DEFAULT 1 COMMENT 'route taxonomy version',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_site_page_dwell_event_event_id (event_id),
    KEY idx_site_page_dwell_event_source_occurred (source, occurred_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='유저웹 사이트 페이지 활성 체류 raw 이벤트';

CREATE TABLE IF NOT EXISTS tb_site_page_route_daily (
    stat_date DATE NOT NULL COMMENT '집계 일자(KST)',
    route_group VARCHAR(80) NOT NULL COMMENT 'route 대분류',
    route_name VARCHAR(120) NOT NULL COMMENT 'route 세부명',
    path_template VARCHAR(255) NOT NULL COMMENT '정규화된 route template',
    page_view_count BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '페이지뷰 수',
    visitor_count BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '브라우저 기준 방문자 수',
    session_count BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '브라우저 세션 수',
    dwell_event_count BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '활성 체류 이벤트 수',
    active_dwell_total_ms BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '활성 체류 총합(ms)',
    active_dwell_avg_ms BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '활성 체류 평균(ms)',
    short_dwell_count BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '5초 미만 활성 체류 이벤트 수',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (stat_date, route_group, route_name, path_template),
    KEY idx_site_page_route_daily_route (route_group, route_name),
    KEY idx_site_page_route_daily_stat_date (stat_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='유저웹 사이트 route별 일별 페이지뷰/활성 체류 mart';
