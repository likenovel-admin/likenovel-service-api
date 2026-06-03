CREATE TABLE IF NOT EXISTS tb_product_rank_snapshot_hourly (
    basis_at DATETIME NOT NULL COMMENT 'Top50 기준시각(HH:30)',
    area_code VARCHAR(100) NOT NULL COMMENT '랭킹 영역 코드',
    rank_no INT NOT NULL COMMENT '기준시점 순위',
    product_id INT NOT NULL COMMENT '작품 ID',
    title_snapshot VARCHAR(100) NOT NULL COMMENT '기준시점 작품명',
    author_name_snapshot VARCHAR(100) NULL COMMENT '기준시점 작가명',
    count_hit BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '기준시점 작품 누적 조회수',
    recent_24h_count_hit BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '기준시점 최근 24시간 조회수',
    previous_rank INT NULL COMMENT '기준시점 이전 순위',
    created_id INT NOT NULL DEFAULT 0 COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT NOT NULL DEFAULT 0 COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (basis_at, area_code, rank_no),
    KEY idx_product_rank_snapshot_product_basis (product_id, basis_at),
    KEY idx_product_rank_snapshot_area_basis (area_code, basis_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='작품 영역별 시간대별 랭킹 스냅샷';
