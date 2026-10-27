-- 외부 유통(카카오페이지/리디) 연재본과 라이크노벨 유료작 매핑
-- 수집기(devtools/external-distribution)가 관측한 외부 연재본을 관리자 sync API가 매칭해 저장한다.
CREATE TABLE IF NOT EXISTS tb_product_external_distribution (
    id INT NOT NULL AUTO_INCREMENT,
    product_id INT NOT NULL COMMENT '라이크노벨 작품 ID',
    platform VARCHAR(20) NOT NULL COMMENT 'kakaopage | ridi',
    external_id VARCHAR(50) NOT NULL COMMENT '외부 플랫폼 연재본 ID',
    external_title VARCHAR(500) NULL COMMENT '외부 플랫폼 표기 제목',
    external_author VARCHAR(200) NULL COMMENT '외부 플랫폼 표기 작가명',
    match_method VARCHAR(20) NOT NULL COMMENT 'exact | author_similar | manual',
    status VARCHAR(20) NOT NULL DEFAULT 'active' COMMENT 'active | hidden',
    miss_count INT NOT NULL DEFAULT 0 COMMENT '연속 미관측 횟수',
    first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_id INT NULL,
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_id INT NULL,
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_product_external_distribution_product_platform (product_id, platform),
    KEY idx_product_external_distribution_platform_external (platform, external_id),
    KEY idx_product_external_distribution_visible (platform, status, miss_count)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='외부 유통 연재본 매핑';

ALTER TABLE tb_direct_recommend
    ADD COLUMN source_type VARCHAR(30) NOT NULL DEFAULT 'manual' COMMENT 'manual | external_distribution';

ALTER TABLE tb_direct_recommend
    ADD COLUMN source_platform VARCHAR(20) NULL COMMENT 'external_distribution 구좌의 플랫폼 (kakaopage | ridi)';
