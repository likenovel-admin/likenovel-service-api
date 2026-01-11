-- tb_user_product_recent에 UNIQUE INDEX 추가
-- 같은 사용자가 같은 작품을 다시 볼 때 중복 row 생성 방지

ALTER TABLE tb_user_product_recent
ADD UNIQUE INDEX idx_user_product_unique (user_id, product_id);
