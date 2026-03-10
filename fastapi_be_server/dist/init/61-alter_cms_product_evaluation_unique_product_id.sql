-- 중복 행 정리: product_id별 최신 1건만 남기고 삭제
DELETE e1 FROM tb_cms_product_evaluation e1
 INNER JOIN tb_cms_product_evaluation e2
    ON e1.product_id = e2.product_id
   AND e1.id < e2.id;

-- 일반 인덱스 → UNIQUE 인덱스로 교체
ALTER TABLE tb_cms_product_evaluation
  DROP INDEX product_id,
  ADD UNIQUE INDEX product_id (product_id);
