CREATE TABLE IF NOT EXISTS tb_main_single_slot (
    single_slot_id INT NOT NULL AUTO_INCREMENT,
    slot_key VARCHAR(50) NOT NULL COMMENT '단일구좌 위치 키',
    slot_name VARCHAR(100) NOT NULL COMMENT '단일구좌 이름',
    slot_order INT NOT NULL DEFAULT 1 COMMENT '노출 순서',
    product_id INT NOT NULL COMMENT '노출 작품 ID',
    summary_text VARCHAR(500) NOT NULL COMMENT '관리자가 작성한 소개글',
    publish_start_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '노출 시작 일시',
    publish_end_at TIMESTAMP NULL DEFAULT NULL COMMENT '노출 종료 일시(NULL이면 항시)',
    cancelled_at TIMESTAMP NULL DEFAULT NULL COMMENT '취소 일시',
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_id INT NULL COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (single_slot_id),
    KEY idx_main_single_slot_active (
        slot_key,
        cancelled_at,
        publish_start_at,
        publish_end_at,
        slot_order
    ),
    KEY idx_main_single_slot_product (product_id),
    KEY idx_main_single_slot_order (slot_order, slot_key, publish_start_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='메인 단일구좌 예약 큐';
