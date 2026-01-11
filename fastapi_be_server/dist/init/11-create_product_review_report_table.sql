-- 작품 리뷰 신고 테이블 생성
CREATE TABLE IF NOT EXISTS tb_product_review_report (
    id INT AUTO_INCREMENT PRIMARY KEY,
    review_id INT NOT NULL COMMENT '리뷰 아이디',
    reporter_user_id INT NOT NULL COMMENT '신고자 유저 아이디',
    report_reason VARCHAR(50) NOT NULL COMMENT '신고 사유 (spam, inappropriate, offensive, etc.)',
    report_detail VARCHAR(1000) COMMENT '신고 상세 내용',
    status VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT '처리 상태 (pending, reviewed, resolved, rejected)',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_review_id (review_id),
    INDEX idx_reporter_user_id (reporter_user_id),
    INDEX idx_status (status),
    INDEX idx_created_date (created_date)
);
