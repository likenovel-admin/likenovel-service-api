USE likenovel;

CREATE TABLE IF NOT EXISTS tb_product_episode_dropoff_daily (
    id                                BIGINT NOT NULL AUTO_INCREMENT COMMENT 'PK',
    computed_date                     DATE NOT NULL COMMENT '집계일(회차 읽기 시작일)',
    product_id                        INT NOT NULL COMMENT '작품 ID',
    episode_id                        INT NOT NULL COMMENT '회차 ID',
    episode_no                        INT NOT NULL DEFAULT 0 COMMENT '회차 번호',
    episode_title                     VARCHAR(300) NULL COMMENT '회차 제목',
    read_start_count                  INT NOT NULL DEFAULT 0 COMMENT '읽기 시작 수',
    episode_dropoff_count             INT NOT NULL DEFAULT 0 COMMENT '읽다 나감 수(progress 95% 미만)',
    episode_dropoff_rate              DOUBLE NOT NULL DEFAULT 0 COMMENT '읽다 나감 비율',
    avg_dropoff_progress_ratio        DOUBLE NULL COMMENT '평균 이탈 지점(progress 95% 미만)',
    near_complete_count               INT NOT NULL DEFAULT 0 COMMENT '거의 다 읽음 수(progress 95% 이상)',
    dropoff_0_10_count                INT NOT NULL DEFAULT 0 COMMENT '0~10% 구간 이탈 수',
    dropoff_10_30_count               INT NOT NULL DEFAULT 0 COMMENT '10~30% 구간 이탈 수',
    dropoff_30_60_count               INT NOT NULL DEFAULT 0 COMMENT '30~60% 구간 이탈 수',
    dropoff_60_90_count               INT NOT NULL DEFAULT 0 COMMENT '60~90% 구간 이탈 수',
    dropoff_90_plus_count             INT NOT NULL DEFAULT 0 COMMENT '90% 이상 이탈 수(95% 미만)',
    created_date                      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_date                      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (id),
    UNIQUE KEY uk_product_episode_dropoff_daily (computed_date, product_id, episode_id),
    KEY idx_product_episode_dropoff_daily_product_date (product_id, computed_date),
    KEY idx_product_episode_dropoff_daily_episode_date (episode_id, computed_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='작품 회차별 읽다 나감 일별 mart';
