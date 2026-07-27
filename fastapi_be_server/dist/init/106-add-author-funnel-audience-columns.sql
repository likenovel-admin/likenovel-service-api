-- Add audience split columns without changing the existing mart grains.

SET @has_author_metric_version := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_author_product_entry_daily'
       AND column_name = 'metric_version'
);
SET @sql := IF(
    @has_author_metric_version = 0,
    'ALTER TABLE tb_author_product_entry_daily ADD COLUMN metric_version INT NOT NULL DEFAULT 1 COMMENT ''집계 기준 버전'' AFTER login_user_count',
    'SELECT ''tb_author_product_entry_daily.metric_version already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_author_guest_detail_view_count := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_author_product_entry_daily'
       AND column_name = 'guest_detail_view_count'
);
SET @sql := IF(
    @has_author_guest_detail_view_count = 0,
    'ALTER TABLE tb_author_product_entry_daily ADD COLUMN guest_detail_view_count INT NOT NULL DEFAULT 0 COMMENT ''게스트 작품 상세 PV 수'' AFTER metric_version',
    'SELECT ''tb_author_product_entry_daily.guest_detail_view_count already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_author_guest_detail_session_count := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_author_product_entry_daily'
       AND column_name = 'guest_detail_session_count'
);
SET @sql := IF(
    @has_author_guest_detail_session_count = 0,
    'ALTER TABLE tb_author_product_entry_daily ADD COLUMN guest_detail_session_count INT NOT NULL DEFAULT 0 COMMENT ''게스트 작품 상세 진입 세션 수'' AFTER guest_detail_view_count',
    'SELECT ''tb_author_product_entry_daily.guest_detail_session_count already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_author_guest_detail_visitor_count := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_author_product_entry_daily'
       AND column_name = 'guest_detail_visitor_count'
);
SET @sql := IF(
    @has_author_guest_detail_visitor_count = 0,
    'ALTER TABLE tb_author_product_entry_daily ADD COLUMN guest_detail_visitor_count INT NOT NULL DEFAULT 0 COMMENT ''게스트 작품 상세 진입 방문자 수'' AFTER guest_detail_session_count',
    'SELECT ''tb_author_product_entry_daily.guest_detail_visitor_count already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_detail_metric_version := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_detail_funnel_daily'
       AND column_name = 'metric_version'
);
SET @sql := IF(
    @has_detail_metric_version = 0,
    'ALTER TABLE tb_product_detail_funnel_daily ADD COLUMN metric_version INT NOT NULL DEFAULT 1 COMMENT ''집계 기준 버전'' AFTER avg_episode_exit_progress_ratio',
    'SELECT ''tb_product_detail_funnel_daily.metric_version already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_guest_detail_view_session_count := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_detail_funnel_daily'
       AND column_name = 'guest_detail_view_session_count'
);
SET @sql := IF(
    @has_guest_detail_view_session_count = 0,
    'ALTER TABLE tb_product_detail_funnel_daily ADD COLUMN guest_detail_view_session_count INT NOT NULL DEFAULT 0 COMMENT ''게스트 상세 퍼널 세션 수'' AFTER metric_version',
    'SELECT ''tb_product_detail_funnel_daily.guest_detail_view_session_count already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_guest_detail_to_view_session_count := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_detail_funnel_daily'
       AND column_name = 'guest_detail_to_view_session_count'
);
SET @sql := IF(
    @has_guest_detail_to_view_session_count = 0,
    'ALTER TABLE tb_product_detail_funnel_daily ADD COLUMN guest_detail_to_view_session_count INT NOT NULL DEFAULT 0 COMMENT ''게스트 상세에서 viewer 전환 세션 수'' AFTER guest_detail_view_session_count',
    'SELECT ''tb_product_detail_funnel_daily.guest_detail_to_view_session_count already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_guest_detail_exit_session_count := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_detail_funnel_daily'
       AND column_name = 'guest_detail_exit_session_count'
);
SET @sql := IF(
    @has_guest_detail_exit_session_count = 0,
    'ALTER TABLE tb_product_detail_funnel_daily ADD COLUMN guest_detail_exit_session_count INT NOT NULL DEFAULT 0 COMMENT ''게스트 작품 상세 이탈 세션 수'' AFTER guest_detail_to_view_session_count',
    'SELECT ''tb_product_detail_funnel_daily.guest_detail_exit_session_count already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_guest_episode_exit_event_count := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_detail_funnel_daily'
       AND column_name = 'guest_episode_exit_event_count'
);
SET @sql := IF(
    @has_guest_episode_exit_event_count = 0,
    'ALTER TABLE tb_product_detail_funnel_daily ADD COLUMN guest_episode_exit_event_count INT NOT NULL DEFAULT 0 COMMENT ''게스트 viewer 세션 explicit exit 수'' AFTER guest_detail_exit_session_count',
    'SELECT ''tb_product_detail_funnel_daily.guest_episode_exit_event_count already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_dropoff_metric_version := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_episode_dropoff_daily'
       AND column_name = 'metric_version'
);
SET @sql := IF(
    @has_dropoff_metric_version = 0,
    'ALTER TABLE tb_product_episode_dropoff_daily ADD COLUMN metric_version INT NOT NULL DEFAULT 1 COMMENT ''집계 기준 버전'' AFTER dropoff_90_plus_count',
    'SELECT ''tb_product_episode_dropoff_daily.metric_version already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_guest_read_start_count := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_episode_dropoff_daily'
       AND column_name = 'guest_read_start_count'
);
SET @sql := IF(
    @has_guest_read_start_count = 0,
    'ALTER TABLE tb_product_episode_dropoff_daily ADD COLUMN guest_read_start_count INT NOT NULL DEFAULT 0 COMMENT ''게스트 viewer 세션 읽기 시작 수'' AFTER metric_version',
    'SELECT ''tb_product_episode_dropoff_daily.guest_read_start_count already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_guest_episode_dropoff_count := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_episode_dropoff_daily'
       AND column_name = 'guest_episode_dropoff_count'
);
SET @sql := IF(
    @has_guest_episode_dropoff_count = 0,
    'ALTER TABLE tb_product_episode_dropoff_daily ADD COLUMN guest_episode_dropoff_count INT NOT NULL DEFAULT 0 COMMENT ''게스트 explicit exit 이탈 수'' AFTER guest_read_start_count',
    'SELECT ''tb_product_episode_dropoff_daily.guest_episode_dropoff_count already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_guest_near_complete_count := (
    SELECT COUNT(*)
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'tb_product_episode_dropoff_daily'
       AND column_name = 'guest_near_complete_count'
);
SET @sql := IF(
    @has_guest_near_complete_count = 0,
    'ALTER TABLE tb_product_episode_dropoff_daily ADD COLUMN guest_near_complete_count INT NOT NULL DEFAULT 0 COMMENT ''게스트 거의 다 읽음 수'' AFTER guest_episode_dropoff_count',
    'SELECT ''tb_product_episode_dropoff_daily.guest_near_complete_count already exists'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
