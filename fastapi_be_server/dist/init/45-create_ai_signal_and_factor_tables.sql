USE likenovel;

-- -------------------------------------------------------------------
-- 1) 작품 AI 메타 확장 컬럼
-- -------------------------------------------------------------------

ALTER TABLE tb_product_ai_metadata
    ADD COLUMN protagonist_current_age_band VARCHAR(30) NULL COMMENT '주인공 현재 연령대';

ALTER TABLE tb_product_ai_metadata
    ADD COLUMN protagonist_mental_age_band VARCHAR(30) NULL COMMENT '주인공 정신연령대';

ALTER TABLE tb_product_ai_metadata
    ADD COLUMN past_life_age_band VARCHAR(30) NULL COMMENT '전생 연령대';

ALTER TABLE tb_product_ai_metadata
    ADD COLUMN regression_type VARCHAR(30) NULL COMMENT '회귀/빙의/환생/none';

ALTER TABLE tb_product_ai_metadata
    ADD COLUMN romance_chemistry_weight VARCHAR(20) NULL COMMENT '연애 케미 비중(none/low/mid/high)';

ALTER TABLE tb_product_ai_metadata
    ADD COLUMN protagonist_goal_primary VARCHAR(30) NULL COMMENT '주인공 대목표';

ALTER TABLE tb_product_ai_metadata
    ADD COLUMN goal_confidence DOUBLE NULL COMMENT '주인공 대목표 confidence(0~1)';

ALTER TABLE tb_product_ai_metadata
    ADD COLUMN overall_confidence DOUBLE NULL COMMENT '메타 전체 confidence(0~1)';

ALTER TABLE tb_product_ai_metadata
    ADD COLUMN protagonist_material_tags JSON NULL COMMENT '주인공 능력/매력 태그';

ALTER TABLE tb_product_ai_metadata
    ADD COLUMN worldview_tags JSON NULL COMMENT '세계관 태그';

ALTER TABLE tb_product_ai_metadata
    ADD INDEX idx_ai_metadata_goal_primary (protagonist_goal_primary);

ALTER TABLE tb_product_ai_metadata
    ADD INDEX idx_ai_metadata_regression_type (regression_type);

-- -------------------------------------------------------------------
-- 2) 원천 이벤트 로그 (고용량)
-- -------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tb_user_ai_signal_event (
    id                           BIGINT NOT NULL AUTO_INCREMENT COMMENT 'PK',
    user_id                      INT NOT NULL COMMENT '유저 ID',
    product_id                   INT NOT NULL COMMENT '작품 ID',
    episode_id                   INT NULL COMMENT '회차 ID',
    event_type                   VARCHAR(50) NOT NULL COMMENT '이벤트 타입',
    session_id                   VARCHAR(64) NULL COMMENT '세션 ID',
    active_seconds               INT NOT NULL DEFAULT 0 COMMENT '활성 열람 시간(초)',
    scroll_depth                 DOUBLE NOT NULL DEFAULT 0 COMMENT '스크롤 깊이(0~1)',
    progress_ratio               DOUBLE NOT NULL DEFAULT 0 COMMENT '진행률(0~1)',
    next_available_yn            CHAR(1) NOT NULL DEFAULT 'N' COMMENT '다음화 존재 여부',
    latest_episode_reached_yn    CHAR(1) NOT NULL DEFAULT 'N' COMMENT '최신화 도달 여부',
    event_payload                JSON NULL COMMENT '추가 이벤트 페이로드',
    created_date                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    PRIMARY KEY (id),
    KEY idx_ai_signal_user_created (user_id, created_date),
    KEY idx_ai_signal_product_created (product_id, created_date),
    KEY idx_ai_signal_event_created (event_type, created_date),
    KEY idx_ai_signal_session_created (session_id, created_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
COMMENT='AI 추천용 유저 행동 원천 이벤트 로그';

-- -------------------------------------------------------------------
-- 3) 원천 이벤트 롤업 테이블 (일/주)
-- -------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tb_user_ai_signal_event_daily (
    id                           BIGINT NOT NULL AUTO_INCREMENT COMMENT 'PK',
    stat_date                    DATE NOT NULL COMMENT '집계일',
    user_id                      INT NOT NULL COMMENT '유저 ID',
    product_id                   INT NOT NULL COMMENT '작품 ID',
    event_type                   VARCHAR(50) NOT NULL COMMENT '이벤트 타입',
    event_count                  INT NOT NULL DEFAULT 0 COMMENT '이벤트 건수',
    sum_active_seconds           INT NOT NULL DEFAULT 0 COMMENT '활성 열람 시간 합계(초)',
    avg_scroll_depth             DOUBLE NOT NULL DEFAULT 0 COMMENT '평균 스크롤 깊이',
    avg_progress_ratio           DOUBLE NOT NULL DEFAULT 0 COMMENT '평균 진행률',
    latest_episode_reached_count INT NOT NULL DEFAULT 0 COMMENT '최신화 도달 건수',
    revisit_24h_count            INT NOT NULL DEFAULT 0 COMMENT '24시간 내 재방문 열람 건수',
    created_date                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_date                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (id),
    UNIQUE KEY uk_ai_signal_daily (stat_date, user_id, product_id, event_type),
    KEY idx_ai_signal_daily_user_date (user_id, stat_date),
    KEY idx_ai_signal_daily_product_date (product_id, stat_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 추천용 유저 행동 일단위 집계';

CREATE TABLE IF NOT EXISTS tb_user_ai_signal_event_weekly (
    id                           BIGINT NOT NULL AUTO_INCREMENT COMMENT 'PK',
    week_start_date              DATE NOT NULL COMMENT '주 시작일(월요일)',
    user_id                      INT NOT NULL COMMENT '유저 ID',
    product_id                   INT NOT NULL COMMENT '작품 ID',
    event_type                   VARCHAR(50) NOT NULL COMMENT '이벤트 타입',
    event_count                  INT NOT NULL DEFAULT 0 COMMENT '이벤트 건수',
    sum_active_seconds           INT NOT NULL DEFAULT 0 COMMENT '활성 열람 시간 합계(초)',
    avg_scroll_depth             DOUBLE NOT NULL DEFAULT 0 COMMENT '평균 스크롤 깊이',
    avg_progress_ratio           DOUBLE NOT NULL DEFAULT 0 COMMENT '평균 진행률',
    latest_episode_reached_count INT NOT NULL DEFAULT 0 COMMENT '최신화 도달 건수',
    revisit_24h_count            INT NOT NULL DEFAULT 0 COMMENT '24시간 내 재방문 열람 건수',
    created_date                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_date                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (id),
    UNIQUE KEY uk_ai_signal_weekly (week_start_date, user_id, product_id, event_type),
    KEY idx_ai_signal_weekly_user_week (user_id, week_start_date),
    KEY idx_ai_signal_weekly_product_week (product_id, week_start_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 추천용 유저 행동 주단위 집계';

-- -------------------------------------------------------------------
-- 4) 유저 취향 축 점수 테이블
-- -------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tb_user_taste_factor_score (
    id               BIGINT NOT NULL AUTO_INCREMENT COMMENT 'PK',
    user_id          INT NOT NULL COMMENT '유저 ID',
    factor_type      VARCHAR(50) NOT NULL COMMENT '축 타입(protagonist/material/worldview/romance/style)',
    factor_key       VARCHAR(120) NOT NULL COMMENT '축 키',
    score            DOUBLE NOT NULL DEFAULT 0 COMMENT '점수',
    signal_count     INT NOT NULL DEFAULT 0 COMMENT '반영 신호 수',
    last_event_date  TIMESTAMP NULL COMMENT '최종 반영 이벤트 시각',
    created_date     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_date     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_taste_factor (user_id, factor_type, factor_key),
    KEY idx_user_taste_factor_user_updated (user_id, updated_date),
    KEY idx_user_taste_factor_type_score (factor_type, score)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='유저 취향 축 점수';

-- -------------------------------------------------------------------
-- 5) AI 구좌 서빙 로그
-- -------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tb_ai_slot_serving_log (
    id                BIGINT NOT NULL AUTO_INCREMENT COMMENT 'PK',
    user_id           INT NOT NULL COMMENT '유저 ID',
    slot_type         VARCHAR(50) NOT NULL COMMENT '구좌 타입',
    slot_key          VARCHAR(100) NULL COMMENT '구좌 키(운영 식별자)',
    product_id        INT NOT NULL COMMENT '작품 ID',
    served_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '노출 시각',
    clicked_yn        CHAR(1) NOT NULL DEFAULT 'N' COMMENT '클릭 여부',
    continued_3ep_yn  CHAR(1) NOT NULL DEFAULT 'N' COMMENT '3화 연독 여부',
    created_date      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_date      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (id),
    KEY idx_ai_slot_serving_user_served (user_id, served_at),
    KEY idx_ai_slot_serving_slot_served (slot_type, served_at),
    KEY idx_ai_slot_serving_product_served (product_id, served_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 추천 구좌 노출/성과 로그';

-- -------------------------------------------------------------------
-- 6) 보관 정책 테이블 (기본 90일)
-- -------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tb_ai_signal_retention_policy (
    id                       INT NOT NULL AUTO_INCREMENT COMMENT 'PK',
    retention_days           INT NOT NULL DEFAULT 90 COMMENT '원천 이벤트 보관일',
    rollup_before_delete_yn  CHAR(1) NOT NULL DEFAULT 'Y' COMMENT '삭제 전 롤업 여부',
    enabled_yn               CHAR(1) NOT NULL DEFAULT 'Y' COMMENT '정책 사용 여부',
    last_rollup_date         DATE NULL COMMENT '마지막 롤업 기준일',
    last_purge_before_date   DATE NULL COMMENT '마지막 삭제 기준일',
    created_date             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_date             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (id),
    KEY idx_ai_signal_retention_enabled (enabled_yn)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 시그널 원천로그 보관 정책';

INSERT INTO tb_ai_signal_retention_policy (
    retention_days,
    rollup_before_delete_yn,
    enabled_yn
)
SELECT
    90,
    'Y',
    'Y'
WHERE NOT EXISTS (
    SELECT 1
    FROM tb_ai_signal_retention_policy
);
