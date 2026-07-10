CREATE TABLE IF NOT EXISTS tb_main_character_slot (
    main_character_slot_id INT NOT NULL AUTO_INCREMENT,
    product_id INT NOT NULL COMMENT '노출 작품 ID',
    character_scope_key VARCHAR(80) NOT NULL COMMENT 'character_inventory_v3 canonical scope key',
    character_name VARCHAR(100) NOT NULL COMMENT '노출 캐릭터명',
    character_image_file_id INT NOT NULL COMMENT 'character 파일 그룹 ID',
    card_order INT NOT NULL DEFAULT 1 COMMENT '카드 노출 순서',
    publish_start_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '노출 시작 일시',
    publish_end_date TIMESTAMP NULL DEFAULT NULL COMMENT '노출 종료 일시(NULL이면 항시)',
    use_yn CHAR(1) NOT NULL DEFAULT 'Y' COMMENT '사용 여부',
    deleted_yn CHAR(1) NOT NULL DEFAULT 'N' COMMENT '삭제 여부',
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT NULL COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (main_character_slot_id),
    KEY idx_main_character_slot_public (
        use_yn,
        deleted_yn,
        publish_start_date,
        publish_end_date,
        card_order,
        main_character_slot_id
    ),
    KEY idx_main_character_slot_product (product_id, deleted_yn)
);
