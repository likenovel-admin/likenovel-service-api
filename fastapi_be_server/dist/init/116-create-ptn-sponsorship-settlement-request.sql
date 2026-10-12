-- 후원금 정산신청 이력 (작가별 월 1회 제한용).
-- 계좌번호, 주민등록번호 등 입금/원천징수 정보는 운영 메일로만 전달하고 이 테이블에는 저장하지 않는다.
CREATE TABLE IF NOT EXISTS tb_ptn_sponsorship_settlement_request (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '정산신청 ID',
    user_id INT NOT NULL COMMENT '신청 작가 user_id',
    request_month CHAR(7) NOT NULL COMMENT '신청 월 (YYYY-MM, KST)',
    total_donation INT NOT NULL DEFAULT 0 COMMENT '신청 시점 후원 총액',
    confirmed_final INT NOT NULL DEFAULT 0 COMMENT '신청 시점 확정 정산액 누적 (수수료, 원천세 공제 후)',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_ptn_sponsorship_settlement_request_user_month (user_id, request_month)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='후원금 정산신청 이력';
