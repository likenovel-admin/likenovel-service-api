USE likenovel;

-- 시간별 유입 통계
CREATE TABLE tb_hourly_inflow (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '고유 번호',
    `product_id` INT NOT NULL COMMENT '상품 ID',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '집계 시간',
    `total_view_count` INT DEFAULT 0 COMMENT '총 조회수',
    `total_payment_count` INT DEFAULT 0 COMMENT '총 결제 건수',
    `male_view_count` INT DEFAULT 0 COMMENT '남성 조회수',
    `female_view_count` INT DEFAULT 0 COMMENT '여성 조회수',
    `male_payment_count` INT DEFAULT 0 COMMENT '남성 결제 건수',
    `female_payment_count` INT DEFAULT 0 COMMENT '여성 결제 건수',
    `male_20_under_payment_count` INT DEFAULT 0 COMMENT '남성 20대 이하 결제 건수',
    `male_30_payment_count` INT DEFAULT 0 COMMENT '남성 30대 결제 건수',
    `male_40_payment_count` INT DEFAULT 0 COMMENT '남성 40대 결제 건수',
    `male_50_payment_count` INT DEFAULT 0 COMMENT '남성 50대 결제 건수',
    `male_60_over_payment_count` INT DEFAULT 0 COMMENT '남성 60대 이상 결제 건수',
    `female_20_under_payment_count` INT DEFAULT 0 COMMENT '여성 20대 이하 결제 건수',
    `female_30_payment_count` INT DEFAULT 0 COMMENT '여성 30대 결제 건수',
    `female_40_payment_count` INT DEFAULT 0 COMMENT '여성 40대 결제 건수',
    `female_50_payment_count` INT DEFAULT 0 COMMENT '여성 50대 결제 건수',
    `female_60_over_payment_count` INT DEFAULT 0 COMMENT '여성 60대 이상 결제 건수',
    `male_20_under_view_count` INT DEFAULT 0 COMMENT '남성 20대 이하 조회수',
    `male_30_view_count` INT DEFAULT 0 COMMENT '남성 30대 조회수',
    `male_40_view_count` INT DEFAULT 0 COMMENT '남성 40대 조회수',
    `male_50_view_count` INT DEFAULT 0 COMMENT '남성 50대 조회수',
    `male_60_over_view_count` INT DEFAULT 0 COMMENT '남성 60대 이상 조회수',
    `female_20_under_view_count` INT DEFAULT 0 COMMENT '여성 20대 이하 조회수',
    `female_30_view_count` INT DEFAULT 0 COMMENT '여성 30대 조회수',
    `female_40_view_count` INT DEFAULT 0 COMMENT '여성 40대 조회수',
    `female_50_view_count` INT DEFAULT 0 COMMENT '여성 50대 조회수',
    `female_60_over_view_count` INT DEFAULT 0 COMMENT '여성 60대 이상 조회수'
);
