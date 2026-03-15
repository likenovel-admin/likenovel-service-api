USE likenovel;

START TRANSACTION;

SET @job_lock_name = 'lk_ai_engagement_metrics_daily_batch';
SET @job_lock_acquired = GET_LOCK(@job_lock_name, 30);
SET @job_lock_guard_sql = IF(
    @job_lock_acquired = 1,
    'SELECT 1',
    'SELECT * FROM __ai_engagement_metrics_lock_not_acquired__'
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
SELECT 'ai_engagement_metrics_daily_batch.sh',
       0,
       0,
       'N',
       'ai_engagement_metrics_daily_batch.sh',
       0,
       0
  FROM dual
 WHERE NOT EXISTS (
    SELECT 1
      FROM tb_cms_batch_job_process x
     WHERE x.job_file_id = 'ai_engagement_metrics_daily_batch.sh'
 );

SET @target_date = DATE_SUB(CURDATE(), INTERVAL 1 DAY);
SET @batch_end = DATE_ADD(@target_date, INTERVAL 1 DAY);
SET @engagement_window_start = DATE_SUB(@batch_end, INTERVAL 30 DAY);
SET @history_window_start = DATE_SUB(@batch_end, INTERVAL 90 DAY);

SELECT a.id
  INTO @job_id
  FROM tb_cms_batch_job_process a
 WHERE a.job_file_id = 'ai_engagement_metrics_daily_batch.sh'
 ORDER BY a.updated_date DESC, a.id DESC
 LIMIT 1
 FOR UPDATE;

UPDATE tb_cms_batch_job_process a
   SET a.completed_yn = 'N'
     , a.created_id = 0
     , a.updated_id = 0
 WHERE a.id = @job_id;

DROP TABLE IF EXISTS tmp_ai_engagement_views;
CREATE TABLE tmp_ai_engagement_views AS
SELECT
    e.id,
    e.user_id,
    e.product_id,
    e.episode_id,
    e.session_id,
    e.next_available_yn,
    e.created_date
FROM tb_user_ai_signal_event e
WHERE e.event_type = 'episode_view'
  AND e.created_date >= @history_window_start
  AND e.created_date < @batch_end
  AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(e.event_payload, '$.trigger')), '') <> 'exit'
  AND e.user_id > 0
  AND e.product_id > 0;
ALTER TABLE tmp_ai_engagement_views
  ADD INDEX idx_tmp_aiev_user_product_created (user_id, product_id, created_date),
  ADD INDEX idx_tmp_aiev_product_episode_user (product_id, episode_id, user_id),
  ADD INDEX idx_tmp_aiev_product_created (product_id, created_date);

DROP TABLE IF EXISTS tmp_ai_engagement_next_clicks;
CREATE TABLE tmp_ai_engagement_next_clicks AS
SELECT
    e.id,
    e.user_id,
    e.product_id,
    e.episode_id,
    e.created_date
FROM tb_user_ai_signal_event e
WHERE e.event_type = 'next_episode_click'
  AND e.created_date >= @engagement_window_start
  AND e.created_date < @batch_end
  AND e.user_id > 0
  AND e.product_id > 0
  AND e.episode_id IS NOT NULL;
ALTER TABLE tmp_ai_engagement_next_clicks
  ADD INDEX idx_tmp_aienc_product_episode_user (product_id, episode_id, user_id),
  ADD INDEX idx_tmp_aienc_user_product_created (user_id, product_id, created_date);

DROP TABLE IF EXISTS tmp_ai_engagement_exit_events;
CREATE TABLE tmp_ai_engagement_exit_events AS
SELECT
    e.user_id,
    e.product_id,
    e.episode_id,
    COALESCE(NULLIF(e.session_id, ''), CONCAT('row-', e.id)) AS exit_session_key,
    MAX(COALESCE(e.active_seconds, 0)) AS active_seconds
FROM tb_user_ai_signal_event e
WHERE e.event_type = 'episode_view'
  AND e.created_date >= @engagement_window_start
  AND e.created_date < @batch_end
  AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(e.event_payload, '$.trigger')), '') = 'exit'
  AND e.user_id > 0
  AND e.product_id > 0
  AND e.episode_id IS NOT NULL
  AND COALESCE(e.active_seconds, 0) > 0
GROUP BY
    e.user_id,
    e.product_id,
    e.episode_id,
    COALESCE(NULLIF(e.session_id, ''), CONCAT('row-', e.id));
ALTER TABLE tmp_ai_engagement_exit_events
  ADD INDEX idx_tmp_aiee_product_episode (product_id, episode_id),
  ADD INDEX idx_tmp_aiee_product_user (product_id, user_id);

INSERT INTO tb_product_engagement_metrics (
    product_id,
    computed_date,
    binge_rate,
    binge_count,
    total_next_clicks,
    total_readers,
    dropoff_3d,
    dropoff_7d,
    dropoff_30d,
    avg_dropoff_ep,
    reengage_count,
    strong_reengage,
    reengage_rate,
    avg_speed_cpm,
    created_date,
    updated_date
)
WITH
product_pool AS (
    SELECT DISTINCT product_id FROM tmp_ai_engagement_views
    UNION DISTINCT
    SELECT DISTINCT product_id FROM tmp_ai_engagement_next_clicks
    UNION DISTINCT
    SELECT DISTINCT product_id FROM tmp_ai_engagement_exit_events
),
view_keys AS (
    SELECT DISTINCT
        v.user_id,
        v.product_id,
        v.episode_id
    FROM tmp_ai_engagement_views v
    WHERE v.created_date >= @engagement_window_start
      AND v.episode_id IS NOT NULL
      AND v.next_available_yn = 'Y'
),
view_counts AS (
    SELECT
        v.product_id,
        COUNT(DISTINCT v.user_id) AS total_readers,
        COUNT(*) AS eligible_view_count
    FROM view_keys v
    GROUP BY v.product_id
),
next_counts AS (
    SELECT
        n.product_id,
        COUNT(*) AS total_next_clicks,
        COUNT(DISTINCT CONCAT_WS(':', n.user_id, n.product_id, n.episode_id)) AS distinct_next_click_count
    FROM tmp_ai_engagement_next_clicks n
    GROUP BY n.product_id
),
binge AS (
    SELECT
        n.product_id,
        COUNT(DISTINCT CONCAT_WS(':', n.user_id, n.product_id, n.episode_id)) AS binge_count
    FROM tmp_ai_engagement_next_clicks n
    INNER JOIN view_keys v
        ON v.user_id = n.user_id
       AND v.product_id = n.product_id
       AND v.episode_id = n.episode_id
    GROUP BY n.product_id
),
last_views AS (
    SELECT
        v.user_id,
        v.product_id,
        v.episode_id,
        v.created_date,
        ROW_NUMBER() OVER (
            PARTITION BY v.user_id, v.product_id
            ORDER BY v.created_date DESC, v.episode_id DESC
        ) AS rn
    FROM tmp_ai_engagement_views v
),
dropoff AS (
    SELECT
        l.product_id,
        SUM(CASE WHEN l.created_date < DATE_SUB(@batch_end, INTERVAL 3 DAY) THEN 1 ELSE 0 END) AS dropoff_3d,
        SUM(CASE WHEN l.created_date < DATE_SUB(@batch_end, INTERVAL 7 DAY) THEN 1 ELSE 0 END) AS dropoff_7d,
        SUM(CASE WHEN l.created_date < DATE_SUB(@batch_end, INTERVAL 30 DAY) THEN 1 ELSE 0 END) AS dropoff_30d,
        ROUND(AVG(CASE
            WHEN l.created_date < DATE_SUB(@batch_end, INTERVAL 7 DAY) AND l.episode_id IS NOT NULL THEN l.episode_id
            ELSE NULL
        END), 1) AS avg_dropoff_ep
    FROM last_views l
    WHERE l.rn = 1
    GROUP BY l.product_id
),
ordered_views AS (
    SELECT
        v.user_id,
        v.product_id,
        v.episode_id,
        v.created_date,
        LAG(v.created_date) OVER (
            PARTITION BY v.user_id, v.product_id
            ORDER BY v.created_date, v.episode_id
        ) AS prev_view_at
    FROM tmp_ai_engagement_views v
),
reengage_candidates AS (
    SELECT
        o.user_id,
        o.product_id,
        MAX(o.created_date) AS reengage_at
    FROM ordered_views o
    WHERE o.prev_view_at IS NOT NULL
      AND TIMESTAMPDIFF(DAY, o.prev_view_at, o.created_date) >= 7
      AND o.created_date >= @engagement_window_start
    GROUP BY o.user_id, o.product_id
),
reengage_strength AS (
    SELECT
        r.user_id,
        r.product_id,
        COUNT(DISTINCT CASE WHEN v.episode_id IS NOT NULL THEN v.episode_id END) AS episodes_after_reengage
    FROM reengage_candidates r
    INNER JOIN tmp_ai_engagement_views v
        ON v.user_id = r.user_id
       AND v.product_id = r.product_id
       AND v.created_date >= r.reengage_at
       AND v.created_date < @batch_end
    GROUP BY r.user_id, r.product_id
),
reengage AS (
    SELECT
        s.product_id,
        SUM(CASE WHEN s.episodes_after_reengage >= 2 THEN 1 ELSE 0 END) AS reengage_count,
        SUM(CASE WHEN s.episodes_after_reengage >= 5 THEN 1 ELSE 0 END) AS strong_reengage
    FROM reengage_strength s
    GROUP BY s.product_id
),
reengage_cohort AS (
    SELECT
        l.user_id,
        l.product_id
    FROM last_views l
    WHERE l.rn = 1
      AND l.created_date < DATE_SUB(@batch_end, INTERVAL 7 DAY)
    UNION DISTINCT
    SELECT
        r.user_id,
        r.product_id
    FROM reengage_candidates r
),
reengage_base AS (
    SELECT
        c.product_id,
        COUNT(*) AS reengage_eligible_count
    FROM reengage_cohort c
    GROUP BY c.product_id
),
speed AS (
    SELECT
        e.product_id,
        ROUND(SUM(pe.episode_text_count) / NULLIF(SUM(e.active_seconds), 0) * 60, 1) AS avg_speed_cpm
    FROM tmp_ai_engagement_exit_events e
    INNER JOIN tb_product_episode pe
        ON pe.episode_id = e.episode_id
    WHERE COALESCE(pe.episode_text_count, 0) > 0
    GROUP BY e.product_id
)
SELECT
    p.product_id,
    @target_date AS computed_date,
    ROUND(
        CASE
            WHEN COALESCE(vc.eligible_view_count, 0) = 0 THEN 0
            ELSE COALESCE(b.binge_count, 0) / vc.eligible_view_count
        END,
        4
    ) AS binge_rate,
    COALESCE(b.binge_count, 0) AS binge_count,
    COALESCE(nc.total_next_clicks, 0) AS total_next_clicks,
    COALESCE(vc.total_readers, 0) AS total_readers,
    COALESCE(d.dropoff_3d, 0) AS dropoff_3d,
    COALESCE(d.dropoff_7d, 0) AS dropoff_7d,
    COALESCE(d.dropoff_30d, 0) AS dropoff_30d,
    d.avg_dropoff_ep AS avg_dropoff_ep,
    COALESCE(r.reengage_count, 0) AS reengage_count,
    COALESCE(r.strong_reengage, 0) AS strong_reengage,
    ROUND(
        CASE
            WHEN COALESCE(rb.reengage_eligible_count, 0) = 0 THEN 0
            ELSE COALESCE(r.reengage_count, 0) / rb.reengage_eligible_count
        END,
        4
    ) AS reengage_rate,
    s.avg_speed_cpm AS avg_speed_cpm,
    NOW() AS created_date,
    NOW() AS updated_date
FROM product_pool p
LEFT JOIN view_counts vc
    ON vc.product_id = p.product_id
LEFT JOIN next_counts nc
    ON nc.product_id = p.product_id
LEFT JOIN binge b
    ON b.product_id = p.product_id
LEFT JOIN dropoff d
    ON d.product_id = p.product_id
LEFT JOIN reengage r
    ON r.product_id = p.product_id
LEFT JOIN reengage_base rb
    ON rb.product_id = p.product_id
LEFT JOIN speed s
    ON s.product_id = p.product_id
ON DUPLICATE KEY UPDATE
    binge_rate = VALUES(binge_rate),
    binge_count = VALUES(binge_count),
    total_next_clicks = VALUES(total_next_clicks),
    total_readers = VALUES(total_readers),
    dropoff_3d = VALUES(dropoff_3d),
    dropoff_7d = VALUES(dropoff_7d),
    dropoff_30d = VALUES(dropoff_30d),
    avg_dropoff_ep = VALUES(avg_dropoff_ep),
    reengage_count = VALUES(reengage_count),
    strong_reengage = VALUES(strong_reengage),
    reengage_rate = VALUES(reengage_rate),
    avg_speed_cpm = VALUES(avg_speed_cpm),
    updated_date = NOW();

DROP TABLE IF EXISTS tmp_ai_engagement_views;
DROP TABLE IF EXISTS tmp_ai_engagement_next_clicks;
DROP TABLE IF EXISTS tmp_ai_engagement_exit_events;

UPDATE tb_cms_batch_job_process a
   SET a.completed_yn = 'Y'
     , a.last_processed_date = @batch_end
     , a.created_id = 0
     , a.updated_id = 0
 WHERE a.id = @job_id;

COMMIT;

SELECT RELEASE_LOCK(@job_lock_name);
