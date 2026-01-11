ALTER TABLE tb_product_episode
ADD COLUMN open_changed_date TIMESTAMP NULL COMMENT '공개여부 변경일' AFTER open_yn;
