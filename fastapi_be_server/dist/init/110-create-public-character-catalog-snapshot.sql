USE likenovel;

CREATE TABLE IF NOT EXISTS tb_public_character_catalog_generation (
    generation_id CHAR(36) NOT NULL COMMENT 'N/Y 범위를 함께 발행하는 세대 ID',
    adult_yn CHAR(1) NOT NULL COMMENT 'N: 일반, Y: 성인 포함',
    active_scope CHAR(1) NULL COMMENT '활성 세대만 adult_yn과 같은 값, 이력은 NULL',
    item_count INT UNSIGNED NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    created_date DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    published_date DATETIME(6) NULL,
    PRIMARY KEY (generation_id, adult_yn),
    UNIQUE KEY uk_public_character_catalog_active_scope (active_scope),
    KEY idx_public_character_catalog_scope_created (adult_yn, created_date),
    CONSTRAINT chk_public_character_catalog_adult_yn
        CHECK (adult_yn IN ('N', 'Y')),
    CONSTRAINT chk_public_character_catalog_active_scope
        CHECK (active_scope IS NULL OR active_scope = adult_yn)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='공개 캐릭터 추천순 세대';

CREATE TABLE IF NOT EXISTS tb_public_character_catalog_snapshot (
    generation_id CHAR(36) NOT NULL,
    adult_yn CHAR(1) NOT NULL,
    display_order INT UNSIGNED NOT NULL,
    product_id BIGINT NOT NULL,
    character_slot_id BIGINT NOT NULL,
    character_scope_key VARCHAR(191) NOT NULL,
    payload_json JSON NOT NULL,
    created_date DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (generation_id, adult_yn, display_order),
    UNIQUE KEY uk_public_character_catalog_identity (
        generation_id,
        adult_yn,
        product_id,
        character_scope_key
    ),
    KEY idx_public_character_catalog_product (product_id),
    CONSTRAINT fk_public_character_catalog_generation
        FOREIGN KEY (generation_id, adult_yn)
        REFERENCES tb_public_character_catalog_generation (
            generation_id,
            adult_yn
        )
        ON DELETE CASCADE,
    CONSTRAINT chk_public_character_catalog_snapshot_adult_yn
        CHECK (adult_yn IN ('N', 'Y'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='공개 캐릭터 추천순 item snapshot';
