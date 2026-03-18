USE likenovel;

START TRANSACTION;

SET @job_lock_name = 'lk_ai_product_episode_dropoff_daily_batch';
SET @job_lock_acquired = GET_LOCK(@job_lock_name, 30);
SET @job_lock_guard_sql = IF(
    @job_lock_acquired = 1,
    'SELECT 1',
    'SELECT * FROM __ai_product_episode_dropoff_daily_lock_not_acquired__'
);
PREPARE stmt_job_lock_guard FROM @job_lock_guard_sql;
EXECUTE stmt_job_lock_guard;
DEALLOCATE PREPARE stmt_job_lock_guard;

INSERT IGNORE INTO tb_cms_batch_job_process (
    job_file_id,
    job_group_id,
    job_order,
    completed_yn,
    job_list,
    created_id,
    updated_id
)
SELECT 'ai_product_episode_dropoff_daily_batch.sh',
       0,
       0,
       'Y',
       'ai_product_episode_dropoff_daily_batch.sh',
       0,
       0
  FROM dual
 WHERE NOT EXISTS (
    SELECT 1
      FROM tb_cms_batch_job_process x
     WHERE x.job_file_id = 'ai_product_episode_dropoff_daily_batch.sh'
 );

SELECT a.id,
       a.completed_yn,
       COALESCE(a.updated_date, '1970-01-01 00:00:00')
  INTO @job_id,
       @job_completed_yn,
       @job_updated_date
  FROM tb_cms_batch_job_process a
 WHERE a.job_file_id = 'ai_product_episode_dropoff_daily_batch.sh'
 ORDER BY a.updated_date DESC, a.id DESC
 LIMIT 1
 FOR UPDATE;

SET @in_progress_stale_minutes = COALESCE(@in_progress_stale_minutes, 60);
SET @in_progress_guard_sql = IF(
    @job_completed_yn = 'N'
    AND TIMESTAMPDIFF(MINUTE, @job_updated_date, NOW()) < @in_progress_stale_minutes,
    'SELECT * FROM __ai_product_episode_dropoff_daily_batch_in_progress__',
    'SELECT 1'
);
PREPARE stmt_in_progress_guard FROM @in_progress_guard_sql;
EXECUTE stmt_in_progress_guard;
DEALLOCATE PREPARE stmt_in_progress_guard;

UPDATE tb_cms_batch_job_process a
   SET a.completed_yn = 'N',
       a.created_id = 0,
       a.updated_id = 0
 WHERE a.id = @job_id;

SET @target_date = DATE_SUB(CURDATE(), INTERVAL 1 DAY);
SET @window_start = DATE_SUB(@target_date, INTERVAL 60 MINUTE);
SET @window_end = DATE_ADD(DATE_ADD(@target_date, INTERVAL 1 DAY), INTERVAL 60 MINUTE);

INSERT INTO tb_product_episode_dropoff_daily (
    computed_date,
    product_id,
    episode_id,
    episode_no,
    episode_title,
    read_start_count,
    episode_dropoff_count,
    episode_dropoff_rate,
    avg_dropoff_progress_ratio,
    near_complete_count,
    dropoff_0_10_count,
    dropoff_10_30_count,
    dropoff_30_60_count,
    dropoff_60_90_count,
    dropoff_90_plus_count,
    created_date,
    updated_date
)
WITH
episode_view_start_events AS (
    SELECT
        e.id,
        e.user_id,
        e.product_id,
        e.episode_id,
        COALESCE(NULLIF(e.session_id, ''), CONCAT('start-', e.id)) AS session_key,
        e.created_date AS event_at
    FROM tb_user_ai_signal_event e
    WHERE e.event_type = 'episode_view'
      AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(e.event_payload, '$.trigger')), '') <> 'exit'
      AND e.created_date >= @window_start
      AND e.created_date < @window_end
      AND e.user_id > 0
      AND e.product_id > 0
      AND e.episode_id IS NOT NULL
),
episode_exit_events AS (
    SELECT
        e.id,
        e.user_id,
        e.product_id,
        e.episode_id,
        COALESCE(NULLIF(e.session_id, ''), CONCAT('exit-', e.id)) AS session_key,
        e.created_date AS event_at,
        COALESCE(e.progress_ratio, 0) AS progress_ratio
    FROM tb_user_ai_signal_event e
    WHERE e.event_type = 'episode_view'
      AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(e.event_payload, '$.trigger')), '') = 'exit'
      AND COALESCE(e.active_seconds, 0) >= 3
      AND e.created_date >= @window_start
      AND e.created_date < @window_end
      AND e.user_id > 0
      AND e.product_id > 0
      AND e.episode_id IS NOT NULL
),
episode_end_events AS (
    SELECT
        e.id,
        e.user_id,
        e.product_id,
        e.episode_id,
        COALESCE(NULLIF(e.session_id, ''), CONCAT('end-', e.id)) AS session_key,
        e.created_date AS event_at,
        COALESCE(e.progress_ratio, 0) AS progress_ratio
    FROM tb_user_ai_signal_event e
    WHERE e.event_type = 'episode_end'
      AND e.created_date >= @window_start
      AND e.created_date < @window_end
      AND e.user_id > 0
      AND e.product_id > 0
      AND e.episode_id IS NOT NULL
),
start_sessions AS (
    SELECT
        e.user_id,
        e.product_id,
        e.episode_id,
        e.session_key,
        MIN(e.event_at) AS started_at
    FROM episode_view_start_events e
    GROUP BY
        e.user_id,
        e.product_id,
        e.episode_id,
        e.session_key
),
dropoff_sessions AS (
    SELECT
        e.user_id,
        e.product_id,
        e.episode_id,
        e.session_key,
        MAX(e.progress_ratio) AS dropoff_progress_ratio,
        MAX(e.event_at) AS last_exit_at
    FROM episode_exit_events e
    WHERE e.progress_ratio < 0.95
    GROUP BY
        e.user_id,
        e.product_id,
        e.episode_id,
        e.session_key
),
near_complete_sessions AS (
    SELECT
        x.user_id,
        x.product_id,
        x.episode_id,
        x.session_key,
        MAX(x.event_at) AS near_complete_at
    FROM (
        SELECT
            e.user_id,
            e.product_id,
            e.episode_id,
            e.session_key,
            e.event_at
        FROM episode_exit_events e
        WHERE e.progress_ratio >= 0.95

        UNION ALL

        SELECT
            e.user_id,
            e.product_id,
            e.episode_id,
            e.session_key,
            e.event_at
        FROM episode_end_events e
    ) x
    GROUP BY
        x.user_id,
        x.product_id,
        x.episode_id,
        x.session_key
),
qualifying_sessions AS (
    SELECT
        DATE(s.started_at) AS computed_date,
        s.user_id,
        s.product_id,
        s.episode_id,
        s.session_key,
        s.started_at,
        CASE
            WHEN d.last_exit_at IS NOT NULL AND d.last_exit_at >= s.started_at THEN 1
            ELSE 0
        END AS has_dropoff,
        CASE
            WHEN d.last_exit_at IS NOT NULL AND d.last_exit_at >= s.started_at
            THEN d.dropoff_progress_ratio
            ELSE NULL
        END AS dropoff_progress_ratio,
        CASE
            WHEN n.near_complete_at IS NOT NULL AND n.near_complete_at >= s.started_at THEN 1
            ELSE 0
        END AS near_complete_yn
    FROM start_sessions s
    LEFT JOIN dropoff_sessions d
        ON d.user_id = s.user_id
       AND d.product_id = s.product_id
       AND d.episode_id = s.episode_id
       AND d.session_key = s.session_key
    LEFT JOIN near_complete_sessions n
        ON n.user_id = s.user_id
       AND n.product_id = s.product_id
       AND n.episode_id = s.episode_id
       AND n.session_key = s.session_key
    WHERE DATE(s.started_at) = @target_date
)
SELECT
    @target_date AS computed_date,
    q.product_id,
    q.episode_id,
    COALESCE(MAX(pe.episode_no), 0) AS episode_no,
    MAX(pe.episode_title) AS episode_title,
    COUNT(*) AS read_start_count,
    SUM(q.has_dropoff) AS episode_dropoff_count,
    CASE
        WHEN COUNT(*) = 0 THEN 0
        ELSE SUM(q.has_dropoff) / COUNT(*)
    END AS episode_dropoff_rate,
    CASE
        WHEN SUM(q.has_dropoff) = 0 THEN NULL
        ELSE SUM(CASE WHEN q.has_dropoff = 1 THEN q.dropoff_progress_ratio ELSE 0 END) / SUM(q.has_dropoff)
    END AS avg_dropoff_progress_ratio,
    SUM(q.near_complete_yn) AS near_complete_count,
    SUM(CASE WHEN q.has_dropoff = 1 AND q.dropoff_progress_ratio < 0.10 THEN 1 ELSE 0 END) AS dropoff_0_10_count,
    SUM(CASE WHEN q.has_dropoff = 1 AND q.dropoff_progress_ratio >= 0.10 AND q.dropoff_progress_ratio < 0.30 THEN 1 ELSE 0 END) AS dropoff_10_30_count,
    SUM(CASE WHEN q.has_dropoff = 1 AND q.dropoff_progress_ratio >= 0.30 AND q.dropoff_progress_ratio < 0.60 THEN 1 ELSE 0 END) AS dropoff_30_60_count,
    SUM(CASE WHEN q.has_dropoff = 1 AND q.dropoff_progress_ratio >= 0.60 AND q.dropoff_progress_ratio < 0.90 THEN 1 ELSE 0 END) AS dropoff_60_90_count,
    SUM(CASE WHEN q.has_dropoff = 1 AND q.dropoff_progress_ratio >= 0.90 THEN 1 ELSE 0 END) AS dropoff_90_plus_count,
    NOW() AS created_date,
    NOW() AS updated_date
FROM qualifying_sessions q
LEFT JOIN tb_product_episode pe
    ON pe.episode_id = q.episode_id
   AND pe.product_id = q.product_id
GROUP BY
    q.product_id,
    q.episode_id
ON DUPLICATE KEY UPDATE
    episode_no = VALUES(episode_no),
    episode_title = VALUES(episode_title),
    read_start_count = VALUES(read_start_count),
    episode_dropoff_count = VALUES(episode_dropoff_count),
    episode_dropoff_rate = VALUES(episode_dropoff_rate),
    avg_dropoff_progress_ratio = VALUES(avg_dropoff_progress_ratio),
    near_complete_count = VALUES(near_complete_count),
    dropoff_0_10_count = VALUES(dropoff_0_10_count),
    dropoff_10_30_count = VALUES(dropoff_10_30_count),
    dropoff_30_60_count = VALUES(dropoff_30_60_count),
    dropoff_60_90_count = VALUES(dropoff_60_90_count),
    dropoff_90_plus_count = VALUES(dropoff_90_plus_count),
    updated_date = NOW();

UPDATE tb_cms_batch_job_process a
   SET a.completed_yn = 'Y',
       a.last_processed_date = DATE_ADD(@target_date, INTERVAL 1 DAY),
       a.created_id = 0,
       a.updated_id = 0
 WHERE a.id = @job_id;

COMMIT;

SELECT RELEASE_LOCK(@job_lock_name);
