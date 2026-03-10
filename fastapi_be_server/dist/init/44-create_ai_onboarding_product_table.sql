USE likenovel;

CREATE TABLE IF NOT EXISTS tb_ai_onboarding_product (
    id           INT NOT NULL AUTO_INCREMENT COMMENT 'PK',
    product_id   INT NOT NULL COMMENT '작품 ID (온보딩 노출 대상)',
    sort_order   INT NOT NULL DEFAULT 0 COMMENT '온보딩 노출 순서 (오름차순)',
    use_yn       CHAR(1) NOT NULL DEFAULT 'Y' COMMENT '사용 여부',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (id),
    UNIQUE KEY uk_ai_onboarding_product (product_id),
    KEY idx_ai_onboarding_use_order (use_yn, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 온보딩 작품 노출 관리';
