CREATE TABLE IF NOT EXISTS tb_story_agent_context_product (
    product_id BIGINT PRIMARY KEY COMMENT '작품 ID',
    context_status VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT 'pending | processing | ready | failed',
    total_episode_count INT NOT NULL DEFAULT 0 COMMENT '대상 회차 수',
    ready_episode_count INT NOT NULL DEFAULT 0 COMMENT '적재 완료 회차 수',
    active_product_summary_id BIGINT NULL COMMENT '현재 활성 작품 요약 summary_id',
    last_built_at TIMESTAMP NULL COMMENT '마지막 성공 빌드 시각',
    last_error_message VARCHAR(500) NULL COMMENT '마지막 실패 메시지',
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT NULL COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    KEY idx_story_agent_context_product_status (context_status, updated_date)
);

CREATE TABLE IF NOT EXISTS tb_story_agent_context_doc (
    context_doc_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id BIGINT NOT NULL COMMENT '작품 ID',
    episode_id BIGINT NOT NULL COMMENT '회차 ID',
    episode_no INT NOT NULL COMMENT '회차 번호',
    source_type VARCHAR(30) NOT NULL COMMENT 'episode_content | epub_fallback',
    source_locator VARCHAR(255) NULL COMMENT '원문 출처 식별자',
    source_hash VARCHAR(64) NOT NULL COMMENT '정규화 원문 해시',
    source_text_length INT NOT NULL DEFAULT 0 COMMENT '정규화 원문 길이',
    version_no INT NOT NULL DEFAULT 1 COMMENT '에피소드 내 버전',
    is_active CHAR(1) NOT NULL DEFAULT 'Y' COMMENT '활성 여부',
    active_episode_id BIGINT GENERATED ALWAYS AS (CASE WHEN is_active = 'Y' THEN episode_id ELSE NULL END) STORED,
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    UNIQUE KEY uq_story_agent_context_doc_episode_hash_source (episode_id, source_hash, source_type),
    UNIQUE KEY uq_story_agent_context_doc_active_episode (active_episode_id),
    KEY idx_story_agent_context_doc_product_episode (product_id, episode_no),
    KEY idx_story_agent_context_doc_episode_version (episode_id, version_no),
    KEY idx_story_agent_context_doc_product_active (product_id, is_active)
);

CREATE TABLE IF NOT EXISTS tb_story_agent_context_chunk (
    chunk_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    context_doc_id BIGINT NOT NULL COMMENT 'context_doc_id',
    product_id BIGINT NOT NULL COMMENT '작품 ID',
    episode_id BIGINT NOT NULL COMMENT '회차 ID',
    episode_no INT NOT NULL COMMENT '회차 번호',
    chunk_no INT NOT NULL COMMENT '청크 번호',
    text_hash VARCHAR(64) NOT NULL COMMENT '청크 해시',
    char_start INT NULL COMMENT '시작 위치',
    char_end INT NULL COMMENT '종료 위치',
    text LONGTEXT NOT NULL COMMENT '청크 본문',
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    UNIQUE KEY uq_story_agent_context_chunk_doc_chunk (context_doc_id, chunk_no),
    KEY idx_story_agent_context_chunk_product_episode (product_id, episode_no),
    KEY idx_story_agent_context_chunk_episode (episode_id),
    CONSTRAINT fk_story_agent_context_chunk_doc
        FOREIGN KEY (context_doc_id) REFERENCES tb_story_agent_context_doc(context_doc_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tb_story_agent_context_summary (
    summary_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id BIGINT NOT NULL COMMENT '작품 ID',
    summary_type VARCHAR(30) NOT NULL COMMENT 'episode_summary | range_summary | product_summary | character_snapshot | relation_snapshot | world_snapshot',
    scope_key VARCHAR(80) NOT NULL COMMENT '요약 scope key',
    episode_from INT NULL COMMENT '시작 회차',
    episode_to INT NULL COMMENT '종료 회차',
    source_hash VARCHAR(64) NOT NULL COMMENT '요약 입력 해시',
    source_doc_count INT NOT NULL DEFAULT 0 COMMENT '입력 문서 수',
    version_no INT NOT NULL DEFAULT 1 COMMENT 'scope 내 버전',
    is_active CHAR(1) NOT NULL DEFAULT 'Y' COMMENT '활성 여부',
    active_scope_key VARCHAR(160) GENERATED ALWAYS AS (
        CASE
            WHEN is_active = 'Y' THEN CONCAT(product_id, ':', summary_type, ':', scope_key)
            ELSE NULL
        END
    ) STORED,
    summary_text LONGTEXT NOT NULL COMMENT '요약 본문',
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    UNIQUE KEY uq_story_agent_context_summary_scope_hash (product_id, summary_type, scope_key, source_hash),
    UNIQUE KEY uq_story_agent_context_summary_active_scope (active_scope_key),
    KEY idx_story_agent_context_summary_product_type (product_id, summary_type, is_active),
    KEY idx_story_agent_context_summary_product_range (product_id, episode_from, episode_to)
);
