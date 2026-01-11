-- tb_product_review 테이블에 제목(title) 컬럼 추가
ALTER TABLE tb_product_review
    ADD COLUMN review_title VARCHAR(200) NULL COMMENT '리뷰 제목' AFTER user_id,
    ADD INDEX idx_review_title (review_title);
