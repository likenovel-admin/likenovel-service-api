CREATE TABLE IF NOT EXISTS tb_main_character_slot (
    character_slot_id INT NOT NULL AUTO_INCREMENT COMMENT '캐릭터 구좌 카드 ID',
    product_id INT NOT NULL COMMENT '노출 작품 ID',
    character_scope_key VARCHAR(200) NOT NULL COMMENT '웹소챗 캐릭터 scope_key (대화 진입 해소용)',
    character_name VARCHAR(100) NOT NULL COMMENT '노출 캐릭터 이름(display_name)',
    character_image_file_id INT NOT NULL COMMENT '관리자 업로드 캐릭터 이미지 file_group_id',
    card_order INT NOT NULL DEFAULT 1 COMMENT '캐러셀 카드 순서',
    publish_start_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '노출 시작 일시',
    publish_end_at TIMESTAMP NULL COMMENT '노출 종료 일시(NULL이면 항시)',
    cancelled_at TIMESTAMP NULL COMMENT '취소 일시',
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT NULL COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (character_slot_id),
    KEY idx_main_character_slot_active (cancelled_at, publish_start_at, publish_end_at, card_order),
    KEY idx_main_character_slot_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='메인 캐릭터 발견 구좌 카드';
