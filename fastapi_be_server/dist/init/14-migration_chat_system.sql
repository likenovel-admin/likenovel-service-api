USE likenovel;

-- 기존 tb_messages_between_users 테이블 삭제
DROP TABLE IF EXISTS tb_messages_between_users;

-- 대화방 테이블
CREATE TABLE tb_chat_rooms (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '대화방 ID',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    INDEX idx_created_date (`created_date`)
) COMMENT='1:1 대화방 테이블';

-- 대화방 멤버 테이블 (읽음 상태, 나가기 관리)
CREATE TABLE tb_chat_room_members (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '멤버 ID',
    `room_id` INT NOT NULL COMMENT '대화방 ID',
    `profile_id` INT NOT NULL COMMENT '프로필 ID',
    `last_read_message_id` INT NULL COMMENT '마지막으로 읽은 메시지 ID',
    `is_active` VARCHAR(1) NOT NULL DEFAULT 'Y' COMMENT '활성 여부 (채팅방 나갔는지)',
    `left_date` TIMESTAMP NULL COMMENT '채팅방 나간 시간',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    UNIQUE KEY uk_room_profile (`room_id`, `profile_id`),
    INDEX idx_profile_id (`profile_id`),
    INDEX idx_room_id (`room_id`),
    INDEX idx_is_active (`is_active`),
    FOREIGN KEY (`room_id`) REFERENCES tb_chat_rooms(`id`) ON DELETE CASCADE
) COMMENT='대화방 멤버 및 읽음 상태 관리';

-- 메시지 테이블
CREATE TABLE tb_chat_messages (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '메시지 ID',
    `room_id` INT NOT NULL COMMENT '대화방 ID',
    `sender_profile_id` INT NOT NULL COMMENT '발신인 profile_id',
    `content` TEXT NOT NULL COMMENT '메시지 내용',
    `is_deleted` VARCHAR(1) NOT NULL DEFAULT 'N' COMMENT '삭제 여부',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    INDEX idx_room_id (`room_id`),
    INDEX idx_sender_profile_id (`sender_profile_id`),
    INDEX idx_created_date (`created_date`),
    FOREIGN KEY (`room_id`) REFERENCES tb_chat_rooms(`id`) ON DELETE CASCADE
) COMMENT='1:1 대화 메시지';

-- 메시지 신고 테이블
CREATE TABLE tb_chat_message_reports (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '신고 ID',
    `message_id` INT NOT NULL COMMENT '신고된 메시지 ID',
    `reporter_profile_id` INT NOT NULL COMMENT '신고자 profile_id',
    `reason` VARCHAR(1000) NULL COMMENT '신고 사유',
    `status` VARCHAR(50) NOT NULL DEFAULT 'pending' COMMENT '처리 상태 (pending, reviewed, rejected)',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '신고일시',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    INDEX idx_message_id (`message_id`),
    INDEX idx_reporter_profile_id (`reporter_profile_id`),
    INDEX idx_status (`status`),
    FOREIGN KEY (`message_id`) REFERENCES tb_chat_messages(`id`) ON DELETE CASCADE
) COMMENT='메시지 신고 관리';
