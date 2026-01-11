USE likenovel;

ALTER TABLE tb_user_productbook
CHANGE COLUMN `product_id` `product_id` INT NULL COMMENT '작품 아이디',
CHANGE COLUMN `episode_id` `episode_id` INT NULL COMMENT '회차 아이디';
