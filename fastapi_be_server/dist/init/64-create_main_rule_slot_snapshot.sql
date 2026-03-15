USE likenovel;

CREATE TABLE IF NOT EXISTS tb_main_rule_slot_snapshot (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    slot_key VARCHAR(50) NOT NULL COMMENT '구좌 키',
    adult_yn VARCHAR(1) NOT NULL DEFAULT 'N' COMMENT '성인 작품 포함 여부',
    snapshot_start_date DATE NOT NULL COMMENT '스냅샷 시작일',
    snapshot_end_date DATE NOT NULL COMMENT '스냅샷 종료일',
    display_order INT NOT NULL DEFAULT 0 COMMENT '노출 순서',
    product_id INT NULL COMMENT '작품 ID, 후보가 없으면 NULL sentinel',
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT NULL COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    UNIQUE KEY uk_slot_window_order (slot_key, adult_yn, snapshot_start_date, display_order),
    KEY idx_active_slot_lookup (adult_yn, snapshot_start_date, snapshot_end_date, slot_key, display_order),
    KEY idx_product_id (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='메인 규칙형 구좌 3일 스냅샷';
