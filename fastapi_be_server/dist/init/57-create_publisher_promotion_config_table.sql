USE likenovel;

CREATE TABLE IF NOT EXISTS tb_publisher_promotion_config (
    id           INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    title        VARCHAR(100) NOT NULL COMMENT '출판사 프로모션 구좌명',
    created_id   INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_id   INT NULL COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='출판사 프로모션 구좌 설정';

INSERT INTO tb_publisher_promotion_config (id, title, created_id, updated_id)
SELECT 1, '출판사 프로모션', 0, 0
WHERE NOT EXISTS (
    SELECT 1
    FROM tb_publisher_promotion_config
    WHERE id = 1
);
