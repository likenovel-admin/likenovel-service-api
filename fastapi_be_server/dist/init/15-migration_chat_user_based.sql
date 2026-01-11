USE likenovel;

-- 채팅 시스템을 profile_id 기반에서 user_id 기반으로 변경

-- 1. 기존 데이터 백업용 임시 테이블 생성 (필요시 복구용)
CREATE TABLE IF NOT EXISTS tb_chat_room_members_backup AS SELECT * FROM tb_chat_room_members;
CREATE TABLE IF NOT EXISTS tb_chat_messages_backup AS SELECT * FROM tb_chat_messages;
CREATE TABLE IF NOT EXISTS tb_chat_message_reports_backup AS SELECT * FROM tb_chat_message_reports;

-- 2. 기존 외래키 제약조건 찾아서 제거
SET @fk_name = NULL;
SELECT CONSTRAINT_NAME INTO @fk_name
FROM information_schema.TABLE_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA = 'likenovel'
  AND TABLE_NAME = 'tb_chat_room_members'
  AND CONSTRAINT_TYPE = 'FOREIGN KEY'
LIMIT 1;

SET @drop_fk1 = IF(@fk_name IS NOT NULL,
    CONCAT('ALTER TABLE tb_chat_room_members DROP FOREIGN KEY ', @fk_name),
    'SELECT "No FK on tb_chat_room_members"');
PREPARE stmt FROM @drop_fk1;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @fk_name = NULL;
SELECT CONSTRAINT_NAME INTO @fk_name
FROM information_schema.TABLE_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA = 'likenovel'
  AND TABLE_NAME = 'tb_chat_messages'
  AND CONSTRAINT_TYPE = 'FOREIGN KEY'
LIMIT 1;

SET @drop_fk2 = IF(@fk_name IS NOT NULL,
    CONCAT('ALTER TABLE tb_chat_messages DROP FOREIGN KEY ', @fk_name),
    'SELECT "No FK on tb_chat_messages"');
PREPARE stmt FROM @drop_fk2;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @fk_name = NULL;
SELECT CONSTRAINT_NAME INTO @fk_name
FROM information_schema.TABLE_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA = 'likenovel'
  AND TABLE_NAME = 'tb_chat_message_reports'
  AND CONSTRAINT_TYPE = 'FOREIGN KEY'
LIMIT 1;

SET @drop_fk3 = IF(@fk_name IS NOT NULL,
    CONCAT('ALTER TABLE tb_chat_message_reports DROP FOREIGN KEY ', @fk_name),
    'SELECT "No FK on tb_chat_message_reports"');
PREPARE stmt FROM @drop_fk3;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 3. tb_chat_room_members 테이블 수정
-- profile_id → user_id 변경

-- 인덱스 삭제 (존재하는 경우에만)
SET @index_exists = (SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = 'likenovel' AND TABLE_NAME = 'tb_chat_room_members' AND INDEX_NAME = 'uk_room_profile');
SET @drop_idx = IF(@index_exists > 0,
    'ALTER TABLE tb_chat_room_members DROP INDEX uk_room_profile',
    'SELECT "Index uk_room_profile does not exist"');
PREPARE stmt FROM @drop_idx;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @index_exists = (SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = 'likenovel' AND TABLE_NAME = 'tb_chat_room_members' AND INDEX_NAME = 'idx_profile_id');
SET @drop_idx = IF(@index_exists > 0,
    'ALTER TABLE tb_chat_room_members DROP INDEX idx_profile_id',
    'SELECT "Index idx_profile_id does not exist"');
PREPARE stmt FROM @drop_idx;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

ALTER TABLE tb_chat_room_members
    CHANGE COLUMN `profile_id` `user_id` INT NOT NULL COMMENT '유저 ID';

ALTER TABLE tb_chat_room_members
    ADD UNIQUE KEY uk_room_user (`room_id`, `user_id`),
    ADD INDEX idx_user_id (`user_id`);

-- 4. tb_chat_messages 테이블 수정
-- sender_profile_id → sender_user_id 변경

SET @index_exists = (SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = 'likenovel' AND TABLE_NAME = 'tb_chat_messages' AND INDEX_NAME = 'idx_sender_profile_id');
SET @drop_idx = IF(@index_exists > 0,
    'ALTER TABLE tb_chat_messages DROP INDEX idx_sender_profile_id',
    'SELECT "Index idx_sender_profile_id does not exist"');
PREPARE stmt FROM @drop_idx;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

ALTER TABLE tb_chat_messages
    CHANGE COLUMN `sender_profile_id` `sender_user_id` INT NOT NULL COMMENT '발신인 user_id';

ALTER TABLE tb_chat_messages
    ADD INDEX idx_sender_user_id (`sender_user_id`);

-- 5. tb_chat_message_reports 테이블 수정
-- reporter_profile_id → reporter_user_id 변경

SET @index_exists = (SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = 'likenovel' AND TABLE_NAME = 'tb_chat_message_reports' AND INDEX_NAME = 'idx_reporter_profile_id');
SET @drop_idx = IF(@index_exists > 0,
    'ALTER TABLE tb_chat_message_reports DROP INDEX idx_reporter_profile_id',
    'SELECT "Index idx_reporter_profile_id does not exist"');
PREPARE stmt FROM @drop_idx;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

ALTER TABLE tb_chat_message_reports
    CHANGE COLUMN `reporter_profile_id` `reporter_user_id` INT NOT NULL COMMENT '신고자 user_id';

ALTER TABLE tb_chat_message_reports
    ADD INDEX idx_reporter_user_id (`reporter_user_id`);

-- 6. 외래키 제약조건 다시 추가
ALTER TABLE tb_chat_room_members
    ADD CONSTRAINT fk_chat_room_members_room
    FOREIGN KEY (`room_id`) REFERENCES tb_chat_rooms(`id`) ON DELETE CASCADE;

ALTER TABLE tb_chat_messages
    ADD CONSTRAINT fk_chat_messages_room
    FOREIGN KEY (`room_id`) REFERENCES tb_chat_rooms(`id`) ON DELETE CASCADE;

ALTER TABLE tb_chat_message_reports
    ADD CONSTRAINT fk_chat_message_reports_message
    FOREIGN KEY (`message_id`) REFERENCES tb_chat_messages(`id`) ON DELETE CASCADE;

-- 테이블 코멘트 업데이트
ALTER TABLE tb_chat_room_members COMMENT='대화방 멤버 및 읽음 상태 관리 (user_id 기반)';
ALTER TABLE tb_chat_messages COMMENT='1:1 대화 메시지 (user_id 기반)';
ALTER TABLE tb_chat_message_reports COMMENT='메시지 신고 관리 (user_id 기반)';
