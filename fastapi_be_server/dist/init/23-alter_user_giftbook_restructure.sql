-- tb_user_giftbook 테이블 구조 개편
-- ticket_item_id 제거, product_id/episode_id로 직접 관리하도록 변경
-- 2025-10-24

USE likenovel;

-- Step 1: 새 컬럼 추가 (NULL 허용)
ALTER TABLE tb_user_giftbook
ADD COLUMN product_id INT NULL COMMENT '대여권 발급 대상 작품 (NULL이면 전체 작품)' AFTER user_id,
ADD COLUMN episode_id INT NULL COMMENT '대여권 발급 대상 에피소드 (NULL이면 해당 작품의 전체 에피소드)' AFTER product_id,
ADD COLUMN ticket_type VARCHAR(20) NULL COMMENT '대여권 타입 (comped, paid 등)' AFTER episode_id,
ADD COLUMN own_type VARCHAR(20) NULL COMMENT '보유 타입 (rental, own)' AFTER ticket_type,
ADD COLUMN acquisition_type VARCHAR(20) NULL COMMENT '획득 방식 (event, promotion, admin_direct, legacy 등)' AFTER amount,
ADD COLUMN acquisition_id INT NULL COMMENT '획득 방식의 ID (프로모션 ID, 이벤트 ID 등)' AFTER acquisition_type;

-- Step 2: 기존 데이터 변환
-- ticket_item 테이블에서 ticket_type 정보 복사
UPDATE tb_user_giftbook ug
INNER JOIN tb_ticket_item ti ON ug.ticket_item_id = ti.ticket_id
SET
    ug.ticket_type = ti.ticket_type,
    ug.own_type = 'rental',
    ug.acquisition_type = 'legacy',
    ug.product_id = NULL,
    ug.episode_id = NULL
WHERE ug.ticket_type IS NULL;

-- ticket_item이 존재하지 않는 경우 기본값 설정
UPDATE tb_user_giftbook
SET
    ticket_type = 'comped',
    own_type = 'rental',
    acquisition_type = 'legacy'
WHERE ticket_type IS NULL;

-- Step 3: NOT NULL 제약 추가
ALTER TABLE tb_user_giftbook
MODIFY COLUMN ticket_type VARCHAR(20) NOT NULL COMMENT '대여권 타입 (comped, paid 등)',
MODIFY COLUMN own_type VARCHAR(20) NOT NULL COMMENT '보유 타입 (rental, own)';

-- Step 4: 기존 인덱스 및 컬럼 제거
DROP INDEX idx_item_id ON tb_user_giftbook;
ALTER TABLE tb_user_giftbook
DROP COLUMN ticket_item_id;

-- Step 5: 새 인덱스 추가
CREATE INDEX idx_product_id ON tb_user_giftbook(product_id);
CREATE INDEX idx_episode_id ON tb_user_giftbook(episode_id);
CREATE INDEX idx_ticket_type ON tb_user_giftbook(ticket_type);
CREATE INDEX idx_acquisition_type ON tb_user_giftbook(acquisition_type);

-- Step 6: tb_user_gift_transaction 수정 (ticket_item_id를 nullable로 변경)
ALTER TABLE tb_user_gift_transaction
MODIFY COLUMN ticket_item_id INT NULL COMMENT '대여권 아이디 (레거시, 새 구조에서는 사용 안함)';
