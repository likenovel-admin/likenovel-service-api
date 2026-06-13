-- AI 사서 카드 노출용 카피 컬럼 (LLM 생성, NULL이면 프론트 템플릿 fallback)
-- 중복 실행 시 1060(duplicate column)은 auto_migrate가 자동 스킵한다.
ALTER TABLE tb_product_ai_metadata
    ADD COLUMN librarian_intro TEXT NULL COMMENT 'AI사서 소개문 (2문장 이내, LLM 생성)' AFTER taste_tags;

ALTER TABLE tb_product_ai_metadata
    ADD COLUMN librarian_points JSON NULL COMMENT 'AI사서 포인트 3개 ["...","...","..."]' AFTER librarian_intro;

ALTER TABLE tb_product_ai_metadata
    ADD COLUMN librarian_chips JSON NULL COMMENT 'AI사서 태그칩 3~4개 ["먼치킨","아카데미"]' AFTER librarian_points;
