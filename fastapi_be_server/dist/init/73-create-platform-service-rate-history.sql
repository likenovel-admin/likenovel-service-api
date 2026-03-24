CREATE TABLE IF NOT EXISTS tb_platform_service_rate_history
(
    id              INT AUTO_INCREMENT PRIMARY KEY,
    scope_type      VARCHAR(20) NOT NULL COMMENT '적용 범위(global|product)',
    product_id      INT NOT NULL DEFAULT 0 COMMENT '작품 ID(global은 0)',
    rate            DECIMAL(10,4) NULL COMMENT '플랫폼 수수료율(0~100, NULL이면 글로벌 복귀)',
    effective_month DATE NOT NULL COMMENT '적용 시작 월(항상 해당 월 1일)',
    use_yn          CHAR(1) NOT NULL DEFAULT 'Y' COMMENT '사용 여부',
    created_id      INT NULL COMMENT 'row를 생성한 id',
    created_date    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_id      INT NULL COMMENT 'row를 갱신한 id',
    updated_date    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_platform_service_rate_history_scope_product_month (scope_type, product_id, effective_month),
    KEY idx_platform_service_rate_history_month (effective_month),
    KEY idx_platform_service_rate_history_product_month (product_id, effective_month)
) COMMENT='플랫폼 수수료율 이력(전역/작품 예외)';
