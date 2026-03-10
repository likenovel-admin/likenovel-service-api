USE likenovel;

CREATE TABLE IF NOT EXISTS tb_ai_onboarding_tag (
    id INT NOT NULL AUTO_INCREMENT,
    tab_key VARCHAR(20) NOT NULL COMMENT '탭 키 (hero/worldTone/relation)',
    tag_name VARCHAR(100) NOT NULL COMMENT '태그명',
    sort_order INT NOT NULL DEFAULT 0 COMMENT '탭 내 노출 순서',
    use_yn CHAR(1) NOT NULL DEFAULT 'Y' COMMENT '사용 여부',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (id),
    KEY idx_ai_onboarding_tag_use_tab_sort (use_yn, tab_key, sort_order),
    KEY idx_ai_onboarding_tag_tab_name (tab_key, tag_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 온보딩 태그 노출 관리';
