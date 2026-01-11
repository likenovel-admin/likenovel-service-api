-- 후원 타입 구분을 위한 컬럼 추가
-- sponsor_type: 'author' (작가 후원), 'product' (작품 후원)
-- product_id: 후원 대상 작품 ID (작품 후원인 경우)

ALTER TABLE tb_user_cashbook_transaction
ADD COLUMN sponsor_type VARCHAR(20) DEFAULT NULL COMMENT '후원 타입 (author: 작가 후원, product: 작품 후원)' AFTER amount,
ADD COLUMN product_id INT DEFAULT NULL COMMENT '후원 대상 작품 ID (작품 후원인 경우)' AFTER sponsor_type;
