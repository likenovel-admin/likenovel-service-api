ALTER TABLE tb_story_agent_session
  ADD COLUMN expires_at TIMESTAMP NULL COMMENT '세션 만료 시각' AFTER deleted_yn;

UPDATE tb_story_agent_session
SET expires_at = DATE_ADD(updated_date, INTERVAL 30 DAY)
WHERE expires_at IS NULL;

ALTER TABLE tb_story_agent_session
  MODIFY COLUMN expires_at TIMESTAMP NOT NULL COMMENT '세션 만료 시각';

CREATE INDEX idx_story_agent_session_expires_at
  ON tb_story_agent_session (expires_at);
