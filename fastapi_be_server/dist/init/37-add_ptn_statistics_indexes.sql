-- 파트너 통계 테이블 인덱스 추가
-- tb_ptn_product_episode_statistics 테이블에 created_date 인덱스 추가
ALTER TABLE tb_ptn_product_episode_statistics ADD INDEX idx_created_date (created_date);
