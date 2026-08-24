CREATE TABLE IF NOT EXISTS tb_main_character_slot_config (
    config_id TINYINT NOT NULL COMMENT '고정 설정 ID(1)',
    display_mode VARCHAR(10) NOT NULL DEFAULT 'auto' COMMENT '홈 구좌 노출 모드(auto/manual)',
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT NULL COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (config_id)
);

INSERT INTO tb_main_character_slot_config (
    config_id,
    display_mode,
    created_id,
    updated_id
)
SELECT 1, 'auto', 0, 0
WHERE NOT EXISTS (
    SELECT 1
    FROM tb_main_character_slot_config
    WHERE config_id = 1
);
