USE likenovel;

ALTER TABLE tb_user_report
CHANGE COLUMN `order_no` `order_no` VARCHAR(20) NOT NULL COMMENT '주문 번호';

ALTER TABLE tb_store_order_item
CHANGE COLUMN `item_id` `item_id` VARCHAR(20) NOT NULL COMMENT '아이템 아이디';
