USE likenovel;

-- 작품 AI DNA 메타데이터
CREATE TABLE IF NOT EXISTS tb_product_ai_metadata (
    id              INT NOT NULL AUTO_INCREMENT,
    product_id      INT NOT NULL COMMENT '작품 ID',
    protagonist_type VARCHAR(200) COMMENT '주인공 유형 (냉철한 전략가, 먼치킨 등)',
    protagonist_desc VARCHAR(500) COMMENT '주인공 설명 한줄',
    heroine_type    VARCHAR(200) COMMENT '히로인 유형',
    heroine_weight  VARCHAR(50)  COMMENT '히로인 비중 (high/mid/low/none)',
    mood            VARCHAR(200) COMMENT '분위기 (어두운, 밝은, 긴장감 등)',
    pacing          VARCHAR(50)  COMMENT '전개 속도 (fast/medium/slow)',
    premise         VARCHAR(500) COMMENT '핵심 소재/설정 한줄',
    hook            VARCHAR(300) COMMENT '1화 훅 설명',
    themes          JSON         COMMENT '테마 태그 배열 ["회귀","복수","성장"]',
    similar_famous  JSON         COMMENT '유사 유명작 배열 ["전독시","나혼렙"]',
    taste_tags      JSON         COMMENT '취향 태그 (AI 생성) ["먼치킨","암울","두뇌전"]',
    raw_analysis    JSON         COMMENT 'LLM 원본 응답 (디버깅용)',
    analyzed_at     TIMESTAMP NULL COMMENT '분석 일시',
    model_version   VARCHAR(50)  COMMENT '사용된 LLM 모델',
    created_date    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_date    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (id),
    UNIQUE KEY uk_product_id (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='작품 AI DNA 메타데이터';

-- 독자 취향 프로파일
CREATE TABLE IF NOT EXISTS tb_user_taste_profile (
    id                      INT NOT NULL AUTO_INCREMENT,
    user_id                 INT NOT NULL COMMENT '유저 ID',
    onboarding_picks        JSON COMMENT '온보딩 시 선택한 작품 IDs',
    onboarding_moods        JSON COMMENT '온보딩 시 선택한 분위기 태그',
    preferred_protagonist   JSON COMMENT '선호 주인공 유형 집계 {"전략가":3,"먼치킨":1}',
    preferred_mood          JSON COMMENT '선호 분위기 집계',
    preferred_themes        JSON COMMENT '선호 테마 집계',
    preferred_heroine_weight VARCHAR(50)  COMMENT '선호 히로인 비중',
    preferred_pacing        VARCHAR(50)  COMMENT '선호 전개 속도',
    taste_summary           VARCHAR(500) COMMENT 'AI 생성 취향 요약문',
    taste_tags              JSON COMMENT '취향 태그 배열 (매칭용)',
    recommendation_sections JSON COMMENT 'AI 생성 추천 섹션 [{dimension,title,reason}]',
    read_product_ids        JSON COMMENT '읽은 작품 ID 배열 (추천 제외용)',
    last_computed_at        TIMESTAMP NULL COMMENT '마지막 프로파일 계산 일시',
    created_date            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_date            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='독자 취향 프로파일';
