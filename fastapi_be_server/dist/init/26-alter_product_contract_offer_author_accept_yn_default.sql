-- tb_product_contract_offer의 author_accept_yn DEFAULT 값을 NULL로 변경
-- NULL: 대기 중 (작가가 아직 응답하지 않음)
-- 'Y': 수락됨
-- 'N': 거절됨

ALTER TABLE tb_product_contract_offer
MODIFY COLUMN author_accept_yn VARCHAR(1) DEFAULT NULL COMMENT '최종 제안 수락 여부 (NULL:대기중, Y:수락, N:거절)';
