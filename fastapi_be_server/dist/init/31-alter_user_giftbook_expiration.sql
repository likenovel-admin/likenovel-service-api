-- tb_user_giftbook 테이블에 유효기간 관련 컬럼 추가
-- 대여권을 선물함을 통해 지급하고, 수령 시점에 유효기간을 설정하도록 변경
-- 2025-11-25

USE likenovel;

-- Step 1: 유효기간 관련 컬럼 추가
ALTER TABLE tb_user_giftbook
ADD COLUMN expiration_date TIMESTAMP NULL COMMENT '선물함 만료일 (NULL이면 무기한)' AFTER received_date,
ADD COLUMN promotion_type VARCHAR(50) NULL COMMENT '프로모션 타입 (free-for-first, reader-of-prev, 6-9-path, waiting-for-free 등)' AFTER acquisition_id,
ADD COLUMN ticket_expiration_type VARCHAR(50) NULL COMMENT '수령 후 대여권 유효기간 타입 (none, days, hours, on_receive_days)' AFTER promotion_type,
ADD COLUMN ticket_expiration_value INT NULL COMMENT '유효기간 값 (days, hours에 따른 숫자)' AFTER ticket_expiration_type;

-- Step 2: 기존 데이터에 기본값 설정 (7일 유효기간)
UPDATE tb_user_giftbook
SET expiration_date = DATE_ADD(created_date, INTERVAL 7 DAY)
WHERE expiration_date IS NULL AND received_yn = 'N';

-- Step 3: 인덱스 추가
CREATE INDEX idx_expiration_date ON tb_user_giftbook(expiration_date);
CREATE INDEX idx_promotion_type ON tb_user_giftbook(promotion_type);
CREATE INDEX idx_received_yn ON tb_user_giftbook(received_yn);
