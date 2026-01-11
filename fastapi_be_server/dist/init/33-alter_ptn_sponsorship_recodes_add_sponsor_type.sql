-- 후원 타입 구분을 위한 컬럼 추가
-- sponsor_type: 'author' (작가 후원), 'product' (작품 후원)

ALTER TABLE tb_ptn_sponsorship_recodes
ADD COLUMN sponsor_type VARCHAR(20) DEFAULT 'author' COMMENT '후원 타입 (author: 작가 후원, product: 작품 후원)' AFTER donation_price;

-- 기존 데이터는 모두 작가 후원으로 간주
-- 기존 작가 후원 데이터의 product_id, title을 초기화
UPDATE tb_ptn_sponsorship_recodes SET product_id = 0, title = '' WHERE sponsor_type = 'author';
