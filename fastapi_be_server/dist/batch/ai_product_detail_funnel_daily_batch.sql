USE likenovel;

START TRANSACTION;

SET time_zone = '+09:00';
SET @job_lock_name = 'lk_ai_product_detail_funnel_daily_batch';
SET @job_lock_acquired = GET_LOCK(@job_lock_name, 30);
SET @job_lock_guard_sql = IF(
    @job_lock_acquired = 1,
    'SELECT 1',
    'SELECT * FROM __ai_product_detail_funnel_daily_lock_not_acquired__'
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
SELECT 'ai_product_detail_funnel_daily_batch.sh',
       0,
       0,
       'Y',
       'ai_product_detail_funnel_daily_batch.sh',
       0,
       0
  FROM dual
 WHERE NOT EXISTS (
    SELECT 1
      FROM tb_cms_batch_job_process x
     WHERE x.job_file_id = 'ai_product_detail_funnel_daily_batch.sh'
 );

SELECT a.id,
       a.completed_yn,
       COALESCE(a.updated_date, '1970-01-01 00:00:00')
  INTO @job_id,
       @job_completed_yn,
       @job_updated_date
  FROM tb_cms_batch_job_process a
 WHERE a.job_file_id = 'ai_product_detail_funnel_daily_batch.sh'
 ORDER BY a.updated_date DESC, a.id DESC
 LIMIT 1
 FOR UPDATE;

SET @in_progress_stale_minutes = COALESCE(@in_progress_stale_minutes, 60);
SET @in_progress_guard_sql = IF(
    @job_completed_yn = 'N'
    AND TIMESTAMPDIFF(MINUTE, @job_updated_date, NOW()) < @in_progress_stale_minutes,
    'SELECT * FROM __ai_product_detail_funnel_daily_batch_in_progress__',
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

SET @target_date = COALESCE(@target_date, DATE_SUB(CURDATE(), INTERVAL 1 DAY));
SET @window_start = DATE_SUB(@target_date, INTERVAL 60 MINUTE);
SET @window_end = DATE_ADD(DATE_ADD(@target_date, INTERVAL 1 DAY), INTERVAL 60 MINUTE);
SET @guest_reader_cutover_date = (
    SELECT c.cutover_date
      FROM tb_site_reader_funnel_config c
     WHERE c.config_key = 'author_guest_funnel_v2'
     LIMIT 1
);
SET @metric_version = IF(
    @guest_reader_cutover_date IS NOT NULL
    AND @target_date >= @guest_reader_cutover_date,
    2,
    1
);

DROP TEMPORARY TABLE IF EXISTS tmp_product_detail_funnel_daily;

CREATE TEMPORARY TABLE tmp_product_detail_funnel_daily AS
WITH
product_detail_view_events AS (
    SELECT
        e.id,
        e.user_id,
        e.product_id,
        e.created_date AS event_at,
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(e.event_payload, '$.entry_source')), '') AS entry_source
    FROM tb_user_ai_signal_event e
    WHERE e.event_type = 'product_detail_view'
      AND e.created_date >= @window_start
      AND e.created_date < @window_end
      AND e.user_id > 0
      AND e.product_id > 0
),
product_detail_exit_events AS (
    SELECT
        e.id,
        e.user_id,
        e.product_id,
        e.created_date AS event_at,
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(e.event_payload, '$.reason')), '') AS exit_reason,
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(e.event_payload, '$.destination_path')), '') AS destination_path,
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(e.event_payload, '$.destination_page_type')), '') AS destination_page_type,
        CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(e.event_payload, '$.destination_product_id')), '') AS SIGNED) AS destination_product_id
    FROM tb_user_ai_signal_event e
    WHERE e.event_type = 'product_detail_exit'
      AND e.created_date >= @window_start
      AND e.created_date < @window_end
      AND e.user_id > 0
      AND e.product_id > 0
),
episode_view_events AS (
    SELECT
        e.id,
        e.user_id,
        e.product_id,
        e.episode_id,
        e.created_date AS event_at
    FROM tb_user_ai_signal_event e
    WHERE e.event_type = 'episode_view'
      AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(e.event_payload, '$.trigger')), '') <> 'exit'
      AND e.created_date >= @window_start
      AND e.created_date < @window_end
      AND e.user_id > 0
      AND e.product_id > 0
),
episode_exit_events AS (
    SELECT
        e.id,
        e.user_id,
        e.product_id,
        e.episode_id,
        e.created_date AS event_at,
        COALESCE(e.progress_ratio, 0) AS progress_ratio
    FROM tb_user_ai_signal_event e
    WHERE e.event_type = 'episode_view'
      AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(e.event_payload, '$.trigger')), '') = 'exit'
      AND e.created_date >= @window_start
      AND e.created_date < @window_end
      AND e.user_id > 0
      AND e.product_id > 0
),
unified_events AS (
    SELECT
        v.id,
        v.user_id,
        v.product_id,
        NULL AS episode_id,
        v.event_at,
        'detail_view' AS event_kind,
        10 AS event_order,
        v.entry_source,
        NULL AS exit_reason,
        NULL AS destination_path,
        NULL AS destination_page_type,
        NULL AS destination_product_id,
        NULL AS progress_ratio
    FROM product_detail_view_events v

    UNION ALL

    SELECT
        v.id,
        v.user_id,
        v.product_id,
        v.episode_id,
        v.event_at,
        'episode_view' AS event_kind,
        20 AS event_order,
        NULL AS entry_source,
        NULL AS exit_reason,
        NULL AS destination_path,
        NULL AS destination_page_type,
        NULL AS destination_product_id,
        NULL AS progress_ratio
    FROM episode_view_events v

    UNION ALL

    SELECT
        x.id,
        x.user_id,
        x.product_id,
        x.episode_id,
        x.event_at,
        'episode_exit' AS event_kind,
        30 AS event_order,
        NULL AS entry_source,
        NULL AS exit_reason,
        NULL AS destination_path,
        NULL AS destination_page_type,
        NULL AS destination_product_id,
        x.progress_ratio
    FROM episode_exit_events x

    UNION ALL

    SELECT
        x.id,
        x.user_id,
        x.product_id,
        NULL AS episode_id,
        x.event_at,
        'detail_exit' AS event_kind,
        40 AS event_order,
        NULL AS entry_source,
        x.exit_reason,
        x.destination_path,
        x.destination_page_type,
        x.destination_product_id,
        NULL AS progress_ratio
    FROM product_detail_exit_events x
),
ordered_events AS (
    SELECT
        u.*,
        LAG(u.event_at) OVER (
            PARTITION BY u.user_id, u.product_id
            ORDER BY u.event_at, u.id
        ) AS prev_event_at,
        LAG(u.event_kind) OVER (
            PARTITION BY u.user_id, u.product_id
            ORDER BY u.event_at, u.id
        ) AS prev_event_kind
    FROM unified_events u
),
context_session_events AS (
    SELECT
        o.*,
        SUM(
            CASE
                WHEN o.prev_event_at IS NULL THEN 1
                WHEN TIMESTAMPDIFF(MINUTE, o.prev_event_at, o.event_at) > 60 THEN 1
                WHEN o.prev_event_kind = 'detail_exit' THEN 1
                ELSE 0
            END
        ) OVER (
            PARTITION BY o.user_id, o.product_id
            ORDER BY o.event_at, o.id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS context_session_seq
    FROM ordered_events o
),
detail_funnel_context_events AS (
    SELECT
        s.*,
        MAX(CASE WHEN s.event_kind = 'detail_view' THEN s.event_at END) OVER (
            PARTITION BY s.user_id, s.product_id, s.context_session_seq
            ORDER BY s.event_at, s.id
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS last_detail_view_at_before,
        MAX(CASE WHEN s.event_kind = 'detail_exit' THEN s.event_at END) OVER (
            PARTITION BY s.user_id, s.product_id, s.context_session_seq
            ORDER BY s.event_at, s.id
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS last_detail_exit_at_before
    FROM context_session_events s
),
detail_funnel_marked_events AS (
    SELECT
        c.*,
        CASE
            WHEN c.event_kind <> 'detail_view' THEN 0
            WHEN c.last_detail_view_at_before IS NULL THEN 1
            WHEN c.last_detail_exit_at_before IS NOT NULL
             AND c.last_detail_exit_at_before >= c.last_detail_view_at_before THEN 1
            ELSE 0
        END AS detail_funnel_start_yn
    FROM detail_funnel_context_events c
),
detail_funnel_events AS (
    SELECT
        m.*,
        SUM(m.detail_funnel_start_yn) OVER (
            PARTITION BY m.user_id, m.product_id, m.context_session_seq
            ORDER BY m.event_at, m.id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS detail_funnel_seq
    FROM detail_funnel_marked_events m
),
detail_funnel_start_rows AS (
    SELECT
        s.user_id,
        s.product_id,
        s.context_session_seq,
        s.detail_funnel_seq,
        s.event_at AS funnel_started_at,
        s.entry_source,
        LEAD(s.event_at) OVER (
            PARTITION BY s.user_id, s.product_id, s.context_session_seq
            ORDER BY s.detail_funnel_seq
        ) AS next_funnel_started_at
    FROM detail_funnel_events s
    WHERE s.detail_funnel_start_yn = 1
),
first_detail_exit_in_funnel AS (
    SELECT
        e.user_id,
        e.product_id,
        e.context_session_seq,
        e.detail_funnel_seq,
        MIN(e.event_at) AS first_detail_exit_at
    FROM detail_funnel_events e
    WHERE e.detail_funnel_seq > 0
      AND e.event_kind = 'detail_exit'
    GROUP BY
        e.user_id,
        e.product_id,
        e.context_session_seq,
        e.detail_funnel_seq
),
scoped_funnel_events AS (
    SELECT
        e.*, 
        s.funnel_started_at,
        s.entry_source AS funnel_entry_source,
        s.next_funnel_started_at,
        x.first_detail_exit_at
    FROM detail_funnel_events e
    INNER JOIN detail_funnel_start_rows s
        ON s.user_id = e.user_id
       AND s.product_id = e.product_id
       AND s.context_session_seq = e.context_session_seq
       AND s.detail_funnel_seq = e.detail_funnel_seq
    LEFT JOIN first_detail_exit_in_funnel x
        ON x.user_id = e.user_id
       AND x.product_id = e.product_id
       AND x.context_session_seq = e.context_session_seq
       AND x.detail_funnel_seq = e.detail_funnel_seq
    WHERE e.detail_funnel_seq > 0
      AND e.event_at >= s.funnel_started_at
      AND (s.next_funnel_started_at IS NULL OR e.event_at < s.next_funnel_started_at)
      AND (x.first_detail_exit_at IS NULL OR e.event_at <= x.first_detail_exit_at)
),
session_rollup AS (
    SELECT
        s.user_id,
        s.product_id,
        s.context_session_seq,
        s.detail_funnel_seq,
        MIN(s.funnel_started_at) AS session_started_at,
        MAX(s.funnel_entry_source) AS entry_source,
        SUM(CASE WHEN s.event_kind = 'detail_view' THEN 1 ELSE 0 END) AS detail_view_raw_count,
        MAX(CASE WHEN s.event_kind = 'episode_view' THEN 1 ELSE 0 END) AS has_episode_view,
        MAX(CASE WHEN s.event_kind = 'detail_exit' THEN 1 ELSE 0 END) AS has_detail_exit,
        MAX(CASE WHEN s.event_kind = 'detail_exit' AND COALESCE(s.destination_path, '') = '/' THEN 1 ELSE 0 END) AS has_exit_home,
        MAX(CASE WHEN s.event_kind = 'detail_exit' AND COALESCE(s.destination_path, '') LIKE '/product/search%' THEN 1 ELSE 0 END) AS has_exit_search,
        MAX(CASE WHEN s.event_kind = 'detail_exit' AND s.exit_reason = 'different_product_detail' THEN 1 ELSE 0 END) AS has_exit_other_product_detail,
        MAX(
            CASE
                WHEN s.event_kind = 'detail_exit'
                 AND s.exit_reason = 'other_route'
                 AND COALESCE(s.destination_path, '') <> '/'
                 AND COALESCE(s.destination_path, '') NOT LIKE '/product/search%'
                THEN 1 ELSE 0
            END
        ) AS has_exit_other_route,
        SUM(CASE WHEN s.event_kind = 'episode_exit' THEN 1 ELSE 0 END) AS episode_exit_event_count,
        SUM(CASE WHEN s.event_kind = 'episode_exit' THEN COALESCE(s.progress_ratio, 0) ELSE 0 END) AS episode_exit_progress_ratio_sum
    FROM scoped_funnel_events s
    GROUP BY
        s.user_id,
        s.product_id,
        s.context_session_seq,
        s.detail_funnel_seq
),
member_qualifying_sessions AS (
    SELECT
        DATE(s.session_started_at) AS computed_date,
        s.user_id,
        s.product_id,
        s.entry_source,
        COALESCE(s.entry_source, '__null__') AS entry_source_norm,
        s.detail_view_raw_count,
        s.has_episode_view,
        s.has_detail_exit,
        s.has_exit_home,
        s.has_exit_search,
        s.has_exit_other_product_detail,
        s.has_exit_other_route,
        s.episode_exit_event_count,
        s.episode_exit_progress_ratio_sum
    FROM session_rollup s
    WHERE DATE(s.session_started_at) = @target_date
),
guest_product_detail_views AS (
    SELECT
        pv.id,
        pv.visitor_id,
        pv.session_id AS browser_session_id,
        COALESCE(
            pv.product_id,
            CASE
                WHEN pv.path REGEXP '^/product/[0-9]+$'
                THEN CAST(SUBSTRING(pv.path, LENGTH('/product/') + 1) AS UNSIGNED)
                ELSE NULL
            END
        ) AS product_id,
        pv.occurred_at AS event_at,
        pv.entry_source
    FROM tb_site_page_view_event pv
    WHERE @metric_version = 2
      AND pv.user_id IS NULL
      AND pv.route_group = 'product_detail'
      AND pv.occurred_at >= @window_start
      AND pv.occurred_at < @window_end
),
guest_episode_sessions AS (
    SELECT
        e.visitor_id,
        e.browser_session_id,
        e.viewer_session_id,
        e.product_id,
        e.episode_id,
        MIN(CASE WHEN e.event_type = 'episode_start' THEN e.occurred_at END) AS started_at,
        MAX(CASE WHEN e.event_type = 'episode_exit' THEN e.active_ms END) AS exit_active_ms,
        MAX(CASE WHEN e.event_type = 'episode_exit' THEN e.progress_ratio END) AS exit_progress_ratio,
        MAX(CASE WHEN e.event_type = 'episode_complete' THEN 1 ELSE 0 END) AS completed_yn
    FROM tb_site_reader_funnel_event e
    INNER JOIN tb_site_reader_funnel_event start_event
        ON start_event.viewer_session_id = e.viewer_session_id
       AND start_event.event_type = 'episode_start'
       AND start_event.audience_type_at_start = 'guest'
    WHERE @metric_version = 2
      AND e.event_type IN ('episode_start', 'episode_exit', 'episode_complete')
      AND e.occurred_at >= @window_start
      AND e.occurred_at < @window_end
      AND e.viewer_session_id IS NOT NULL
      AND e.product_id > 0
      AND e.episode_id IS NOT NULL
    GROUP BY
        e.visitor_id,
        e.browser_session_id,
        e.viewer_session_id,
        e.product_id,
        e.episode_id
    HAVING started_at IS NOT NULL
),
guest_episode_session_link_candidates AS (
    SELECT
        s.*,
        pv.id AS detail_view_id,
        ROW_NUMBER() OVER (
            PARTITION BY
                s.visitor_id,
                s.browser_session_id,
                s.viewer_session_id,
                s.product_id,
                s.episode_id
            ORDER BY pv.event_at DESC, pv.id DESC
        ) AS link_rank
    FROM guest_episode_sessions s
    INNER JOIN guest_product_detail_views pv
        ON pv.visitor_id = s.visitor_id
       AND pv.browser_session_id = s.browser_session_id
       AND pv.product_id = s.product_id
       AND pv.event_at <= s.started_at
       AND s.started_at <= DATE_ADD(pv.event_at, INTERVAL 60 MINUTE)
),
guest_episode_by_detail AS (
    SELECT
        e.detail_view_id,
        COUNT(*) AS episode_session_count,
        SUM(
            CASE
                WHEN e.exit_progress_ratio IS NOT NULL
                THEN 1 ELSE 0
            END
        ) AS episode_exit_event_count,
        SUM(
            CASE
                WHEN e.exit_progress_ratio IS NOT NULL
                THEN e.exit_progress_ratio ELSE 0
            END
        ) AS episode_exit_progress_ratio_sum
    FROM guest_episode_session_link_candidates e
    WHERE e.link_rank = 1
    GROUP BY e.detail_view_id
),
guest_product_detail_exit_events AS (
    SELECT
        e.event_id,
        e.visitor_id,
        e.browser_session_id,
        e.product_id,
        e.occurred_at AS event_at,
        e.destination_group
    FROM tb_site_reader_funnel_event e
    WHERE @metric_version = 2
      AND e.audience_type_at_start = 'guest'
      AND e.event_type = 'product_detail_exit'
      AND e.occurred_at >= @window_start
      AND e.occurred_at < @window_end
      AND e.product_id > 0
),
guest_detail_exit_link_candidates AS (
    SELECT
        e.*,
        pv.id AS detail_view_id,
        ROW_NUMBER() OVER (
            PARTITION BY e.event_id
            ORDER BY pv.event_at DESC, pv.id DESC
        ) AS link_rank
    FROM guest_product_detail_exit_events e
    INNER JOIN guest_product_detail_views pv
        ON pv.visitor_id = e.visitor_id
       AND pv.browser_session_id = e.browser_session_id
       AND pv.product_id = e.product_id
       AND pv.event_at <= e.event_at
       AND e.event_at <= DATE_ADD(pv.event_at, INTERVAL 60 MINUTE)
),
guest_exit_by_detail AS (
    SELECT
        e.detail_view_id,
        1 AS has_detail_exit,
        MAX(CASE WHEN e.destination_group = 'home' THEN 1 ELSE 0 END) AS has_exit_home,
        MAX(CASE WHEN e.destination_group = 'search' THEN 1 ELSE 0 END) AS has_exit_search,
        MAX(CASE WHEN e.destination_group = 'other_product' THEN 1 ELSE 0 END) AS has_exit_other_product_detail,
        MAX(CASE WHEN e.destination_group = 'other_route' THEN 1 ELSE 0 END) AS has_exit_other_route
    FROM guest_detail_exit_link_candidates e
    WHERE e.link_rank = 1
    GROUP BY e.detail_view_id
),
guest_qualifying_sessions AS (
    SELECT
        DATE(pv.event_at) AS computed_date,
        NULL AS user_id,
        pv.product_id,
        pv.entry_source,
        COALESCE(pv.entry_source, '__null__') AS entry_source_norm,
        COUNT(*) AS detail_view_raw_count,
        CASE
            WHEN SUM(COALESCE(ep.episode_session_count, 0)) > 0
            THEN 1 ELSE 0
        END AS has_episode_view,
        MAX(COALESCE(dx.has_detail_exit, 0)) AS has_detail_exit,
        MAX(COALESCE(dx.has_exit_home, 0)) AS has_exit_home,
        MAX(COALESCE(dx.has_exit_search, 0)) AS has_exit_search,
        MAX(COALESCE(dx.has_exit_other_product_detail, 0)) AS has_exit_other_product_detail,
        MAX(COALESCE(dx.has_exit_other_route, 0)) AS has_exit_other_route,
        SUM(COALESCE(ep.episode_exit_event_count, 0)) AS episode_exit_event_count,
        SUM(COALESCE(ep.episode_exit_progress_ratio_sum, 0)) AS episode_exit_progress_ratio_sum
    FROM guest_product_detail_views pv
    LEFT JOIN guest_episode_by_detail ep
        ON ep.detail_view_id = pv.id
    LEFT JOIN guest_exit_by_detail dx
        ON dx.detail_view_id = pv.id
    WHERE pv.product_id IS NOT NULL
      AND DATE(pv.event_at) = @target_date
    GROUP BY
        DATE(pv.event_at),
        pv.visitor_id,
        pv.browser_session_id,
        pv.product_id,
        pv.entry_source,
        COALESCE(pv.entry_source, '__null__')
),
qualifying_sessions AS (
    SELECT
        m.*,
        0 AS is_guest
    FROM member_qualifying_sessions m

    UNION ALL

    SELECT
        g.*,
        1 AS is_guest
    FROM guest_qualifying_sessions g
)
SELECT
    @target_date AS computed_date,
    q.product_id,
    q.entry_source,
    q.entry_source_norm,
    SUM(q.detail_view_raw_count) AS detail_view_raw_count,
    COUNT(*) AS detail_view_session_count,
    COUNT(DISTINCT q.user_id) AS detail_view_user_count,
    SUM(q.has_episode_view) AS detail_to_view_session_count,
    COUNT(DISTINCT CASE WHEN q.has_episode_view = 1 THEN q.user_id END) AS detail_to_view_user_count,
    SUM(q.has_detail_exit) AS detail_exit_session_count,
    SUM(q.has_exit_home) AS exit_home_session_count,
    SUM(q.has_exit_search) AS exit_search_session_count,
    SUM(q.has_exit_other_product_detail) AS exit_other_product_detail_session_count,
    SUM(q.has_exit_other_route) AS exit_other_route_session_count,
    SUM(q.episode_exit_event_count) AS episode_exit_event_count,
    CASE
        WHEN SUM(q.episode_exit_event_count) = 0 THEN NULL
        ELSE SUM(q.episode_exit_progress_ratio_sum) / SUM(q.episode_exit_event_count)
    END AS avg_episode_exit_progress_ratio,
    @metric_version AS metric_version,
    SUM(CASE WHEN q.is_guest = 1 THEN 1 ELSE 0 END) AS guest_detail_view_session_count,
    SUM(CASE WHEN q.is_guest = 1 THEN q.has_episode_view ELSE 0 END) AS guest_detail_to_view_session_count,
    SUM(CASE WHEN q.is_guest = 1 THEN q.has_detail_exit ELSE 0 END) AS guest_detail_exit_session_count,
    SUM(CASE WHEN q.is_guest = 1 THEN q.episode_exit_event_count ELSE 0 END) AS guest_episode_exit_event_count,
    NOW() AS created_date,
    NOW() AS updated_date
FROM qualifying_sessions q
GROUP BY
    q.product_id,
    q.entry_source,
    q.entry_source_norm;

DELETE FROM tb_product_detail_funnel_daily
 WHERE computed_date = @target_date;

INSERT INTO tb_product_detail_funnel_daily (
    computed_date,
    product_id,
    entry_source,
    entry_source_norm,
    detail_view_raw_count,
    detail_view_session_count,
    detail_view_user_count,
    detail_to_view_session_count,
    detail_to_view_user_count,
    detail_exit_session_count,
    exit_home_session_count,
    exit_search_session_count,
    exit_other_product_detail_session_count,
    exit_other_route_session_count,
    episode_exit_event_count,
    avg_episode_exit_progress_ratio,
    metric_version,
    guest_detail_view_session_count,
    guest_detail_to_view_session_count,
    guest_detail_exit_session_count,
    guest_episode_exit_event_count,
    created_date,
    updated_date
)
SELECT
    computed_date,
    product_id,
    entry_source,
    entry_source_norm,
    detail_view_raw_count,
    detail_view_session_count,
    detail_view_user_count,
    detail_to_view_session_count,
    detail_to_view_user_count,
    detail_exit_session_count,
    exit_home_session_count,
    exit_search_session_count,
    exit_other_product_detail_session_count,
    exit_other_route_session_count,
    episode_exit_event_count,
    avg_episode_exit_progress_ratio,
    metric_version,
    guest_detail_view_session_count,
    guest_detail_to_view_session_count,
    guest_detail_exit_session_count,
    guest_episode_exit_event_count,
    created_date,
    updated_date
FROM tmp_product_detail_funnel_daily;

DROP TEMPORARY TABLE tmp_product_detail_funnel_daily;

UPDATE tb_cms_batch_job_process a
   SET a.completed_yn = 'Y',
       a.last_processed_date = DATE_ADD(@target_date, INTERVAL 1 DAY),
       a.created_id = 0,
       a.updated_id = 0
 WHERE a.id = @job_id;

COMMIT;

SELECT RELEASE_LOCK(@job_lock_name);
