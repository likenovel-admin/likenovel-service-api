use likenovel;

-- tb_direct_promotion 테이블 status에 'pending'과 'end' 상태 추가

-- status 컬럼 주석 수정
ALTER TABLE tb_direct_promotion
MODIFY COLUMN `status` VARCHAR(1000) NOT NULL COMMENT '상태, 대기중 (pending) | 진행중 (ing) | 중지 (stop) | 종료 (end)';
