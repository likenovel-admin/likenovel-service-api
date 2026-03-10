-- 작가 예측 정확도 측정용 로그 테이블 생성
-- NOTE:
-- - 실측값은 기존 일배치(summary_daily_batch) 결과 테이블을 재사용하여 계산한다.
-- - 중복 저장을 피하기 위해 prediction log만 신규 생성한다.

USE likenovel;

CREATE TABLE IF NOT EXISTS tb_author_episode_prediction_log (
    prediction_id BIGINT NOT NULL AUTO_INCREMENT COMMENT '예측 로그 PK',
    prediction_key CHAR(36) NOT NULL COMMENT '클라이언트 idempotency 키(UUID)',
    product_id INT NOT NULL COMMENT '작품 ID',
    author_user_id INT NOT NULL COMMENT '작가 사용자 ID',
    screen_name VARCHAR(64) NOT NULL DEFAULT 'author_episode_manager' COMMENT '발생 화면',
    target_week_start_date DATE NOT NULL COMMENT '목표 주 시작일(월요일)',
    target_weekly_upload_goal TINYINT UNSIGNED NOT NULL COMMENT '목표연재주기(주간 목표 화수)',
    recommended_weekly_upload_goal TINYINT UNSIGNED NOT NULL DEFAULT 5 COMMENT '플랫폼 권장 주간 화수',
    uploads_this_week TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '이번 주 업로드 화수',
    remaining_target_uploads TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '목표 달성까지 남은 화수',
    remaining_recommended_uploads TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '권장 달성까지 남은 화수',
    prediction_base_uploads TINYINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '예측 계산 기준 화수',
    sample_episode_count TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '샘플 회차 수',
    sample_window_type VARCHAR(32) NOT NULL DEFAULT 'recent_12' COMMENT '샘플 윈도우 타입(recent_12/recent_8)',
    prediction_basis VARCHAR(32) NOT NULL DEFAULT 'target_goal' COMMENT '예측 기준(target_goal/recommended_goal)',
    expected_views_min INT NOT NULL DEFAULT 0 COMMENT '예상 조회수 최소',
    expected_views_max INT NOT NULL DEFAULT 0 COMMENT '예상 조회수 최대',
    expected_rank_gain_min SMALLINT NOT NULL DEFAULT 0 COMMENT '예상 순위 상승 최소',
    expected_rank_gain_max SMALLINT NOT NULL DEFAULT 0 COMMENT '예상 순위 상승 최대',
    has_enough_data CHAR(1) NOT NULL DEFAULT 'N' COMMENT '충분한 데이터 여부(Y/N)',
    model_version VARCHAR(32) NOT NULL DEFAULT 'v1.0.0' COMMENT '예측 모델 버전',
    baseline_rank INT NULL COMMENT '예측 시점 현재 랭킹',
    baseline_hit_count INT NOT NULL DEFAULT 0 COMMENT '예측 시점 누적 조회수',
    created_id INT DEFAULT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT DEFAULT NULL COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (prediction_id),
    UNIQUE KEY uq_prediction_key (prediction_key),
    KEY idx_product_created (product_id, created_date),
    KEY idx_author_created (author_user_id, created_date)
) COMMENT='작가 화면 예측 노출 로그';
