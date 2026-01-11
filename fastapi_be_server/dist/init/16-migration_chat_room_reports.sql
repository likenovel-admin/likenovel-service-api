-- 대화방 신고 테이블로 마이그레이션
-- tb_chat_message_reports 삭제 및 tb_chat_room_reports 생성

USE likenovel;

-- 1. 기존 tb_chat_message_reports 테이블 삭제
DROP TABLE IF EXISTS tb_chat_message_reports;

-- 2. 새로운 tb_chat_room_reports 테이블 생성
CREATE TABLE tb_chat_room_reports (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '신고 ID',
    `room_id` INT NOT NULL COMMENT '신고된 대화방 ID',
    `reporter_user_id` INT NOT NULL COMMENT '신고자 user_id',
    `report_reason` VARCHAR(100) NOT NULL COMMENT '신고 사유 타입 (threat_extortion, fraud_impersonation, spam_off_platform, privacy_copyright, illegal_content, spam_advertisement)',
    `report_detail` TEXT NULL COMMENT '신고 상세 내용',
    `status` VARCHAR(50) NOT NULL DEFAULT 'pending' COMMENT '처리 상태 (pending, reviewed, rejected)',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '신고일시',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    INDEX idx_room_id (`room_id`),
    INDEX idx_reporter_user_id (`reporter_user_id`),
    INDEX idx_status (`status`),
    FOREIGN KEY (`room_id`) REFERENCES tb_chat_rooms(`id`) ON DELETE CASCADE,
    FOREIGN KEY (`reporter_user_id`) REFERENCES tb_user(`user_id`) ON DELETE CASCADE
) COMMENT='대화방 신고 관리';
