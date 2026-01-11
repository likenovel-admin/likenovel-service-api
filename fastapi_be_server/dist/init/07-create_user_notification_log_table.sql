-- tb_user_notification_log 테이블 생성
-- 작가가 북마크 유저에게 알림을 발송한 이력을 관리하는 테이블

USE likenovel;

CREATE TABLE IF NOT EXISTS tb_user_notification_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    notification_count INT NOT NULL COMMENT '발송된 알림 개수',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id),
    INDEX idx_created_date (created_date)
) COMMENT='작가 알림 발송 로그';