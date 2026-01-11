-- 35-alter_sponsorship_add_author_id.sql
-- 후원 관련 테이블에 author_id 컬럼 추가
--
-- 목적:
-- 1. 작가 후원(sponsor_type='author')의 경우 product_id=0으로 저장되어 작가 식별 불가
-- 2. author_id 컬럼 추가하여 작가별 후원 내역 정확히 조회 가능하도록 개선
--
-- 실행 일시: 2025-11-26
-- 작성자: Claude Code

-- 1. tb_ptn_sponsorship_recodes에 author_id 컬럼 추가
ALTER TABLE tb_ptn_sponsorship_recodes
ADD COLUMN author_id INT NULL COMMENT '작가 ID' AFTER author_nickname;

-- 2. tb_batch_daily_sales_summary에 author_id 컬럼 추가
ALTER TABLE tb_batch_daily_sales_summary
ADD COLUMN author_id INT NULL COMMENT '작가 ID' AFTER episode_id;

-- 3. tb_ptn_income_settlement에 author_id 컬럼 추가
ALTER TABLE tb_ptn_income_settlement
ADD COLUMN author_id INT NULL COMMENT '작가 ID' AFTER product_id;

-- 4. tb_ptn_income_settlement_temp_summary에 author_id 컬럼 추가
ALTER TABLE tb_ptn_income_settlement_temp_summary
ADD COLUMN author_id INT NULL COMMENT '작가 ID' AFTER product_id;

-- 5. 기존 tb_ptn_sponsorship_recodes 데이터 마이그레이션
-- 작품 후원: product_id로 tb_product에서 author_id 조회
UPDATE tb_ptn_sponsorship_recodes sr
INNER JOIN tb_product p ON sr.product_id = p.product_id
SET sr.author_id = p.author_id
WHERE sr.product_id > 0;

-- 작가 후원: author_nickname으로 tb_product에서 author_id 조회
UPDATE tb_ptn_sponsorship_recodes sr
INNER JOIN (
    SELECT author_name, author_id
    FROM tb_product
    GROUP BY author_name, author_id
) p ON sr.author_nickname COLLATE utf8mb4_unicode_ci = p.author_name COLLATE utf8mb4_unicode_ci
SET sr.author_id = p.author_id
WHERE sr.product_id = 0 AND sr.sponsor_type = 'author';

-- 6. 기존 tb_batch_daily_sales_summary 데이터 마이그레이션 (후원 항목만)
UPDATE tb_batch_daily_sales_summary bds
INNER JOIN tb_product p ON bds.product_id = p.product_id
SET bds.author_id = p.author_id
WHERE bds.item_type = 'sponsorship' AND bds.product_id > 0;

-- 작가 후원 (product_id = 0): item_name에서 작가명 추출하여 매칭
UPDATE tb_batch_daily_sales_summary bds
INNER JOIN (
    SELECT author_name, author_id
    FROM tb_product
    GROUP BY author_name, author_id
) p ON bds.item_name COLLATE utf8mb4_unicode_ci LIKE CONCAT(p.author_name COLLATE utf8mb4_unicode_ci, ' 작가 후원')
SET bds.author_id = p.author_id
WHERE bds.item_type = 'sponsorship' AND bds.product_id = 0;

-- 7. 기존 tb_ptn_income_settlement 데이터 마이그레이션
UPDATE tb_ptn_income_settlement pis
INNER JOIN tb_product p ON pis.product_id = p.product_id
SET pis.author_id = p.author_id
WHERE pis.product_id > 0;

-- 8. 기존 tb_ptn_income_settlement_temp_summary 데이터 마이그레이션
UPDATE tb_ptn_income_settlement_temp_summary pists
INNER JOIN tb_product p ON pists.product_id = p.product_id
SET pists.author_id = p.author_id
WHERE pists.product_id > 0;

-- 마이그레이션 결과 확인 쿼리 (선택사항)
-- SELECT
--     'tb_ptn_sponsorship_recodes' as table_name,
--     COUNT(*) as total,
--     SUM(CASE WHEN author_id IS NOT NULL THEN 1 ELSE 0 END) as with_author_id,
--     SUM(CASE WHEN author_id IS NULL THEN 1 ELSE 0 END) as without_author_id
-- FROM tb_ptn_sponsorship_recodes
-- UNION ALL
-- SELECT
--     'tb_batch_daily_sales_summary' as table_name,
--     COUNT(*) as total,
--     SUM(CASE WHEN author_id IS NOT NULL THEN 1 ELSE 0 END) as with_author_id,
--     SUM(CASE WHEN author_id IS NULL THEN 1 ELSE 0 END) as without_author_id
-- FROM tb_batch_daily_sales_summary
-- WHERE item_type = 'sponsorship';
