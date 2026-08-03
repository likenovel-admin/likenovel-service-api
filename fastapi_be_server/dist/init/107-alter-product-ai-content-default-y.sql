-- 신규 작품의 플랫폼 내 AI 콘텐츠 서비스 기본값을 활성화한다.
-- 기존 행의 명시적 Y/N 값은 변경하지 않는다.
ALTER TABLE tb_product
  ALTER COLUMN ai_content_service_enabled_yn SET DEFAULT 'Y';
