USE likenovel;

ALTER TABLE tb_product
    ADD COLUMN single_rental_price INT NOT NULL DEFAULT 0 COMMENT '단행본 대여 가격'
    AFTER single_regular_price;
