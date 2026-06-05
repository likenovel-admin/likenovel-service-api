ALTER TABLE tb_product
  ADD COLUMN ai_content_service_enabled_yn VARCHAR(1) NOT NULL DEFAULT 'N' COMMENT '플랫폼 내 AI 콘텐츠 서비스 활성화 동의 여부' AFTER contract_yn;

ALTER TABLE tb_product
  ADD COLUMN ai_external_promotion_yn VARCHAR(1) NOT NULL DEFAULT 'N' COMMENT '홍보·광고 목적 AI 생성 콘텐츠 외부 채널 게재 동의 여부' AFTER ai_content_service_enabled_yn;

UPDATE tb_product
   SET ai_content_service_enabled_yn = 'Y',
       ai_external_promotion_yn = 'Y';

UPDATE tb_product
   SET ai_content_service_enabled_yn = 'N',
       ai_external_promotion_yn = 'N'
 WHERE product_id = 1152;
