-- 작품 리뷰 좋아요 테이블 생성
CREATE TABLE IF NOT EXISTS tb_product_review_like (
    id INT AUTO_INCREMENT PRIMARY KEY,
    review_id INT NOT NULL COMMENT '리뷰 아이디',
    user_id INT NOT NULL COMMENT '유저 아이디',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_review_id (review_id),
    INDEX idx_user_id (user_id),
    UNIQUE KEY unique_review_user (review_id, user_id)
);

-- 작품 리뷰 댓글 테이블 생성
CREATE TABLE IF NOT EXISTS tb_product_review_comment (
    id INT AUTO_INCREMENT PRIMARY KEY,
    review_id INT NOT NULL COMMENT '리뷰 아이디',
    user_id INT NOT NULL COMMENT '유저 아이디',
    comment_text VARCHAR(3000) NOT NULL COMMENT '댓글 내용',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_review_id (review_id),
    INDEX idx_user_id (user_id)
);
