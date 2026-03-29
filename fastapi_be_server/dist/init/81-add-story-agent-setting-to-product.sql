ALTER TABLE tb_product
ADD COLUMN story_agent_setting_text VARCHAR(1000) NULL COMMENT '스토리 에이전트 보조 설정' AFTER synopsis_text;
