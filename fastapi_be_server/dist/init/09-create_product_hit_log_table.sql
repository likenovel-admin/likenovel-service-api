-- tb_product_hit_log 테이블 생성
-- 작품의 일별 조회수를 기록하는 테이블

USE likenovel;

CREATE TABLE IF NOT EXISTS tb_product_hit_log (
    product_id INT NOT NULL COMMENT '작품 아이디',
    hit_date DATE NOT NULL COMMENT '조회 날짜',
    hit_count INT NOT NULL DEFAULT 0 COMMENT '조회수',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (product_id, hit_date),
    INDEX idx_hit_date (hit_date),
    INDEX idx_hit_date_count (hit_date, hit_count)
) COMMENT='작품 일별 조회수 로그';
