-- tb_user_gift_transaction 테이블에 컬럼 추가
-- 2025-10-01: 선물함 히스토리 추적을 위한 컬럼 추가

ALTER TABLE tb_user_gift_transaction
ADD COLUMN type VARCHAR(50) NOT NULL COMMENT '타입 - received(받은 내역), used(사용 내역)' AFTER id,
ADD COLUMN user_id INT NOT NULL COMMENT '유저 아이디' AFTER type,
ADD COLUMN giftbook_id INT NULL COMMENT '선물함 아이디' AFTER user_id,
ADD COLUMN ticket_item_id INT NOT NULL COMMENT '대여권 아이디' AFTER giftbook_id,
ADD COLUMN amount INT DEFAULT 1 COMMENT '대여권 장수' AFTER ticket_item_id,
ADD COLUMN reason VARCHAR(200) DEFAULT '' COMMENT '거래 사유' AFTER amount,
ADD INDEX idx_type (type),
ADD INDEX idx_user_id (user_id),
ADD INDEX idx_giftbook_id (giftbook_id),
ADD INDEX idx_ticket_item_id (ticket_item_id);
