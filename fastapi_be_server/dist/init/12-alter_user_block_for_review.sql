-- tb_user_block 테이블에 review_id 컬럼 추가 및 기존 컬럼 NULL 허용으로 변경
ALTER TABLE tb_user_block
    MODIFY COLUMN product_id INT NULL COMMENT '작품 아이디',
    MODIFY COLUMN episode_id INT NULL COMMENT '회차 아이디',
    MODIFY COLUMN comment_id INT NULL COMMENT '댓글 아이디',
    ADD COLUMN review_id INT NULL COMMENT '리뷰 아이디' AFTER comment_id,
    ADD INDEX idx_review_id (review_id);
