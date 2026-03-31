ALTER TABLE tb_story_agent_session
ADD COLUMN session_memory_json TEXT NULL COMMENT 'RP/세션 메모리 JSON' AFTER title;
