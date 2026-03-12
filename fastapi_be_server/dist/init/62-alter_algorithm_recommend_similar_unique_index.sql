-- 중복 레코드 정리: (type, product_id) 기준으로 id가 가장 큰 행만 유지
DELETE t1
FROM tb_algorithm_recommend_similar t1
INNER JOIN tb_algorithm_recommend_similar t2
  ON t1.type = t2.type
  AND t1.product_id = t2.product_id
  AND t1.id < t2.id;

-- UNIQUE 인덱스 추가
ALTER TABLE tb_algorithm_recommend_similar
  ADD UNIQUE INDEX uq_type_product_id (`type`(50), `product_id`);
