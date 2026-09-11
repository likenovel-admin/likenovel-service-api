CREATE TABLE IF NOT EXISTS tb_ai_reader_comment_config (
    config_id TINYINT NOT NULL COMMENT '고정 설정 ID(1)',
    comment_allow_yn CHAR(1) NOT NULL DEFAULT 'Y' COMMENT 'AI 독자 댓글 작성 허용 여부(Y/N)',
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT NULL COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (config_id)
);

INSERT INTO tb_ai_reader_comment_config (
    config_id,
    comment_allow_yn,
    created_id,
    updated_id
)
SELECT 1, 'Y', 0, 0
WHERE NOT EXISTS (
    SELECT 1
    FROM tb_ai_reader_comment_config
    WHERE config_id = 1
);
