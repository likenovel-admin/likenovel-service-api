-- UCI 컬럼 크기 확장 (20 -> 50)
-- UCI 코드가 20자를 초과하는 경우가 있어 컬럼 크기 확장

ALTER TABLE tb_product MODIFY COLUMN uci VARCHAR(50) DEFAULT NULL COMMENT 'uci 코드';
