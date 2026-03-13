-- 기존 작품 publish_regular_yn 보정
-- 2024년 데이터는 단행본 기능이 없었으므로 전부 연재(Y)여야 함
-- publish_regular_yn = 'N'인 기존 작품을 'Y'로 일괄 변경
UPDATE tb_product
   SET publish_regular_yn = 'Y'
 WHERE publish_regular_yn = 'N'
   AND created_date < '2026-01-01';
