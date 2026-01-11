-- tb_payment_statistics_by_user 테이블의 유니크 키 수정
-- 기존: uk_date (date만 유니크) -> 하루에 1개 레코드만 가능
-- 수정: uk_date_user (date, user_id 복합 유니크) -> 하루에 여러 사용자 데이터 저장 가능

-- 기존 유니크 키 삭제
ALTER TABLE tb_payment_statistics_by_user DROP INDEX uk_date;

-- (date, user_id) 복합 유니크 키 추가
ALTER TABLE tb_payment_statistics_by_user ADD UNIQUE KEY uk_date_user (date, user_id);
