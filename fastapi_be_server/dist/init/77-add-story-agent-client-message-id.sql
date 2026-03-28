ALTER TABLE tb_story_agent_message
ADD COLUMN client_message_id VARCHAR(64) NULL COMMENT '클라이언트 메시지 ID' AFTER role;

ALTER TABLE tb_story_agent_message
ADD UNIQUE INDEX uq_story_agent_message_session_role_client_message (
    session_id,
    role,
    client_message_id
);
