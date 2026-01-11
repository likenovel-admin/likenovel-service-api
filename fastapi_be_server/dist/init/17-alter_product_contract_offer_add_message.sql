-- tb_product_contract_offer 테이블에 offer_message 컬럼 추가

USE likenovel;

-- offer_message 컬럼 추가
ALTER TABLE tb_product_contract_offer
ADD COLUMN `offer_message` TEXT NULL COMMENT '제안 메시지' AFTER `offer_price`;
