-- 직접 프로모션에 종료일 컬럼 추가
ALTER TABLE tb_direct_promotion
ADD COLUMN end_date TIMESTAMP NULL COMMENT '프로모션 종료일' AFTER start_date;
