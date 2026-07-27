CREATE TABLE IF NOT EXISTS tb_site_reader_funnel_event (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '독자 퍼널 이벤트 ID',
    event_id CHAR(36) NOT NULL COMMENT '클라이언트 생성 이벤트 UUID',
    occurred_at DATETIME(3) NOT NULL COMMENT '브라우저 이벤트 발생 시각',
    user_id INT NULL COMMENT '로그인 유저 ID, 게스트는 NULL',
    audience_type_at_start VARCHAR(10) NOT NULL COMMENT '열람 시작 시점 guest/member',
    visitor_id VARCHAR(80) NOT NULL COMMENT '브라우저 단위 익명 방문자 ID',
    browser_session_id VARCHAR(80) NOT NULL COMMENT '브라우저 세션 ID',
    viewer_session_id VARCHAR(80) NULL COMMENT '회차 뷰어 세션 ID',
    event_type VARCHAR(50) NOT NULL COMMENT '독자 퍼널 이벤트 타입',
    product_id INT NOT NULL COMMENT '작품 ID',
    episode_id INT NULL COMMENT '현재 회차 ID',
    next_episode_id INT NULL COMMENT '다음 공개 회차 ID',
    destination_group VARCHAR(20) NOT NULL DEFAULT 'unknown' COMMENT '이탈 목적지 그룹',
    active_ms INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '활성 체류 시간(ms)',
    progress_ratio DECIMAL(6,5) UNSIGNED NOT NULL DEFAULT 0 COMMENT '열람 진행률',
    tracking_version INT NOT NULL DEFAULT 2 COMMENT '추적 계약 버전',
    source VARCHAR(50) NOT NULL DEFAULT 'service-web' COMMENT '이벤트 소스',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_site_reader_funnel_event_event_id (event_id),
    UNIQUE KEY uq_site_reader_funnel_viewer_event_type (viewer_session_id, event_type),
    KEY idx_site_reader_funnel_source_created (source, created_date),
    KEY idx_site_reader_funnel_audience_event_occurred (
        audience_type_at_start,
        event_type,
        occurred_at
    ),
    KEY idx_site_reader_funnel_audience_event_created (
        audience_type_at_start,
        event_type,
        created_date
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='유저웹 독자 퍼널 raw 이벤트';

CREATE TABLE IF NOT EXISTS tb_site_reader_funnel_config (
    config_key VARCHAR(50) NOT NULL COMMENT '독자 퍼널 설정 키',
    cutover_date DATE NOT NULL COMMENT '해당 지표의 v2 집계 시작일(KST)',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='독자 퍼널 집계 전환일 설정';
