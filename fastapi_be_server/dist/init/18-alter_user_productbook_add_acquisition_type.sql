-- tb_user_productbook 테이블에 acquisition_type, acquisition_id 컬럼 추가

USE likenovel;

-- acquisition_type 컬럼 추가
ALTER TABLE tb_user_productbook
ADD COLUMN `acquisition_type` VARCHAR(50) NULL COMMENT '획득 방식 - applied_promotion(신청 프로모션), direct_promotion(직접 프로모션), event(이벤트), gift(선물), quest(퀘스트)' AFTER `ticket_type`;

-- acquisition_id 컬럼 추가
ALTER TABLE tb_user_productbook
ADD COLUMN `acquisition_id` INT NULL COMMENT '획득 방식의 ID (프로모션 ID, 이벤트 ID 등)' AFTER `acquisition_type`;

-- 인덱스 추가
CREATE INDEX idx_acquisition_type ON tb_user_productbook(acquisition_type);
CREATE INDEX idx_acquisition_id ON tb_user_productbook(acquisition_id);
