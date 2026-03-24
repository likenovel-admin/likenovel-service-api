ALTER TABLE tb_product
  ADD COLUMN cp_user_id INT NULL COMMENT '담당 CP 사용자 ID' AFTER contract_yn,
  ADD INDEX idx_cp_user_id (cp_user_id),
  ADD INDEX idx_contract_cp_user (contract_yn, cp_user_id);

UPDATE tb_product p
INNER JOIN (
    SELECT z.product_id, MIN(z.offer_user_id) AS offer_user_id
      FROM tb_product_contract_offer z
      INNER JOIN tb_user_profile_apply upa
         ON upa.user_id = z.offer_user_id
        AND upa.apply_type = 'cp'
        AND upa.approval_code = 'accepted'
        AND upa.approval_date IS NOT NULL
     WHERE z.use_yn = 'Y'
       AND z.author_accept_yn = 'Y'
     GROUP BY z.product_id
    HAVING COUNT(DISTINCT z.offer_user_id) = 1
) accepted_offer ON accepted_offer.product_id = p.product_id
   SET p.cp_user_id = accepted_offer.offer_user_id
 WHERE p.cp_user_id IS NULL
   AND p.contract_yn = 'Y';
