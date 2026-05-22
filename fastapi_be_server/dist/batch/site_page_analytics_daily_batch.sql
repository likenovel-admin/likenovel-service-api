SET time_zone = '+09:00';
SET @site_page_analytics_target_date = COALESCE(@site_page_analytics_target_date, DATE_SUB(CURDATE(), INTERVAL 1 DAY));
SET @site_page_analytics_target_start = TIMESTAMP(@site_page_analytics_target_date);
SET @site_page_analytics_target_end = DATE_ADD(@site_page_analytics_target_start, INTERVAL 1 DAY);

INSERT IGNORE INTO tb_cms_batch_job_process (
    job_file_id,
    job_group_id,
    job_order,
    completed_yn,
    job_list,
    created_id,
    updated_id
)
SELECT 'site_page_analytics_daily_batch.sh',
       0,
       0,
       'Y',
       'site_page_analytics_daily_batch.sh',
       0,
       0
  FROM dual
 WHERE NOT EXISTS (
    SELECT 1
      FROM tb_cms_batch_job_process x
     WHERE x.job_file_id = 'site_page_analytics_daily_batch.sh'
 );

UPDATE tb_cms_batch_job_process a
   SET a.completed_yn = 'N',
       a.created_id = 0,
       a.updated_id = 0
 WHERE a.job_file_id = 'site_page_analytics_daily_batch.sh';

START TRANSACTION;

DROP TEMPORARY TABLE IF EXISTS tmp_site_page_route_pv;
DROP TEMPORARY TABLE IF EXISTS tmp_site_page_route_dwell;

CREATE TEMPORARY TABLE tmp_site_page_route_pv AS
SELECT
    pv.route_group,
    pv.route_name,
    pv.path_template,
    COUNT(*) AS page_view_count,
    COUNT(DISTINCT pv.visitor_id) AS visitor_count,
    COUNT(DISTINCT pv.session_id) AS session_count
FROM tb_site_page_view_event pv
WHERE pv.source = 'service-web'
  AND pv.occurred_at >= @site_page_analytics_target_start
  AND pv.occurred_at < @site_page_analytics_target_end
GROUP BY pv.route_group, pv.route_name, pv.path_template;

CREATE TEMPORARY TABLE tmp_site_page_route_dwell AS
SELECT
    dw.route_group,
    dw.route_name,
    dw.path_template,
    COUNT(*) AS dwell_event_count,
    COALESCE(SUM(dw.active_ms), 0) AS active_dwell_total_ms,
    COALESCE(ROUND(AVG(dw.active_ms)), 0) AS active_dwell_avg_ms,
    SUM(CASE WHEN dw.active_ms < 5000 THEN 1 ELSE 0 END) AS short_dwell_count
FROM tb_site_page_dwell_event dw
WHERE dw.source = 'service-web'
  AND dw.occurred_at >= @site_page_analytics_target_start
  AND dw.occurred_at < @site_page_analytics_target_end
GROUP BY dw.route_group, dw.route_name, dw.path_template;

DELETE FROM tb_site_page_route_daily
WHERE stat_date = @site_page_analytics_target_date;

INSERT INTO tb_site_page_route_daily (
    stat_date,
    route_group,
    route_name,
    path_template,
    page_view_count,
    visitor_count,
    session_count,
    dwell_event_count,
    active_dwell_total_ms,
    active_dwell_avg_ms,
    short_dwell_count,
    created_date,
    updated_date
)
SELECT
    @site_page_analytics_target_date AS stat_date,
    COALESCE(pv.route_group, dw.route_group) AS route_group,
    COALESCE(pv.route_name, dw.route_name) AS route_name,
    COALESCE(pv.path_template, dw.path_template) AS path_template,
    COALESCE(pv.page_view_count, 0) AS page_view_count,
    COALESCE(pv.visitor_count, 0) AS visitor_count,
    COALESCE(pv.session_count, 0) AS session_count,
    COALESCE(dw.dwell_event_count, 0) AS dwell_event_count,
    COALESCE(dw.active_dwell_total_ms, 0) AS active_dwell_total_ms,
    COALESCE(dw.active_dwell_avg_ms, 0) AS active_dwell_avg_ms,
    COALESCE(dw.short_dwell_count, 0) AS short_dwell_count,
    NOW() AS created_date,
    NOW() AS updated_date
FROM tmp_site_page_route_pv pv
LEFT JOIN tmp_site_page_route_dwell dw
  ON dw.route_group = pv.route_group
 AND dw.route_name = pv.route_name
 AND dw.path_template = pv.path_template
UNION ALL
SELECT
    @site_page_analytics_target_date AS stat_date,
    dw.route_group,
    dw.route_name,
    dw.path_template,
    0 AS page_view_count,
    0 AS visitor_count,
    0 AS session_count,
    dw.dwell_event_count,
    dw.active_dwell_total_ms,
    dw.active_dwell_avg_ms,
    dw.short_dwell_count,
    NOW() AS created_date,
    NOW() AS updated_date
FROM tmp_site_page_route_dwell dw
LEFT JOIN tmp_site_page_route_pv pv
  ON pv.route_group = dw.route_group
 AND pv.route_name = dw.route_name
 AND pv.path_template = dw.path_template
WHERE pv.path_template IS NULL;

DROP TEMPORARY TABLE IF EXISTS tmp_site_page_route_pv;
DROP TEMPORARY TABLE IF EXISTS tmp_site_page_route_dwell;

UPDATE tb_cms_batch_job_process a
   SET a.completed_yn = 'Y',
       a.created_id = 0,
       a.updated_id = 0
 WHERE a.job_file_id = 'site_page_analytics_daily_batch.sh';

COMMIT;
