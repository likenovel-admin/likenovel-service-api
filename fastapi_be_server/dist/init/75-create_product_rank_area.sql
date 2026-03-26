CREATE TABLE IF NOT EXISTS tb_product_rank_area (
    rank_area_id INT AUTO_INCREMENT PRIMARY KEY,
    area_code VARCHAR(255) NOT NULL COMMENT '랭킹 영역 코드',
    product_id INT NOT NULL COMMENT '작품 아이디',
    current_rank INT COMMENT '현재 랭킹',
    previous_rank INT COMMENT '이전 랭킹',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_rank_area_area_code (area_code),
    INDEX idx_product_rank_area_product_id (product_id),
    INDEX idx_product_rank_area_area_product (area_code, product_id)
);
