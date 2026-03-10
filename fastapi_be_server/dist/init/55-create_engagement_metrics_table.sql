USE likenovel;

-- 작품별 독자 행동 지표 (일별 집계)
CREATE TABLE IF NOT EXISTS tb_product_engagement_metrics (
    id               BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id       INT NOT NULL COMMENT '작품 ID',
    computed_date    DATE NOT NULL COMMENT '집계일',
    -- 빈지율
    binge_rate       DECIMAL(5,4) DEFAULT 0 COMMENT '빈지율 (0~1)',
    binge_count      INT DEFAULT 0 COMMENT '실제 읽기 후 다음화 클릭 수',
    total_next_clicks INT DEFAULT 0 COMMENT '다음화 클릭 총 횟수',
    -- 이탈
    total_readers    INT DEFAULT 0 COMMENT '총 독자 수',
    dropoff_3d       INT DEFAULT 0 COMMENT '3일+ 이탈 수',
    dropoff_7d       INT DEFAULT 0 COMMENT '7일+ 이탈 확정 수',
    dropoff_30d      INT DEFAULT 0 COMMENT '30일+ 완전 이탈 수',
    avg_dropoff_ep   DECIMAL(6,1) DEFAULT NULL COMMENT '평균 이탈 회차',
    -- 재방문
    reengage_count   INT DEFAULT 0 COMMENT '재방문 수 (7일+ 공백 후 2회차+)',
    strong_reengage  INT DEFAULT 0 COMMENT '강한 재방문 수 (7일+ 공백 후 5회차+)',
    reengage_rate    DECIMAL(5,4) DEFAULT 0 COMMENT '재방문율 (재방문/이탈확정)',
    -- 읽기 속도
    avg_speed_cpm    DECIMAL(8,1) DEFAULT NULL COMMENT '평균 읽기 속도 (chars/min)',
    -- 메타
    created_date     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_date     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_product_date (product_id, computed_date),
    KEY idx_computed_date (computed_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='작품별 독자 행동 지표 (일별 집계)';
