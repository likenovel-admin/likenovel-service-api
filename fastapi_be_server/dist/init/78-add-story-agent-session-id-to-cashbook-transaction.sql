ALTER TABLE tb_user_cashbook_transaction
ADD COLUMN story_agent_session_id BIGINT NULL COMMENT '스토리 에이전트 세션 ID' AFTER product_id;

ALTER TABLE tb_user_cashbook_transaction
ADD INDEX idx_cashbook_transaction_story_agent_session (story_agent_session_id);
