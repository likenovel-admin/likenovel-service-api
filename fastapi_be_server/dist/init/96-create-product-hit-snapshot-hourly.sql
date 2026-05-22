CREATE TABLE IF NOT EXISTS tb_product_hit_snapshot_hourly (
    basis_at DATETIME NOT NULL COMMENT 'Top50 기준시각(HH:30)',
    product_id INT NOT NULL COMMENT '작품 ID',
    count_hit BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '기준시점 작품 누적 조회수',
    created_id INT NOT NULL DEFAULT 0 COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT NOT NULL DEFAULT 0 COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (basis_at, product_id),
    KEY idx_product_hit_snapshot_hourly_product_basis (product_id, basis_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='작품 시간별 누적 조회수 스냅샷';

CREATE TABLE IF NOT EXISTS tb_product_episode_hit_snapshot_hourly (
    basis_at DATETIME NOT NULL COMMENT 'Top50 기준시각(HH:30)',
    product_id INT NOT NULL COMMENT '작품 ID',
    episode_id INT NOT NULL COMMENT '회차 ID',
    episode_no INT NOT NULL COMMENT '회차 번호',
    count_hit BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '기준시점 회차 누적 조회수',
    created_id INT NOT NULL DEFAULT 0 COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT NOT NULL DEFAULT 0 COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (basis_at, product_id, episode_id),
    KEY idx_product_episode_hit_snapshot_hourly_product_basis (product_id, basis_at),
    KEY idx_product_episode_hit_snapshot_hourly_basis_product_episode_no (basis_at, product_id, episode_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='작품 회차 시간별 누적 조회수 스냅샷';
