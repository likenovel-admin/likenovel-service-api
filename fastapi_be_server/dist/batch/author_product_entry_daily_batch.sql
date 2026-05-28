USE likenovel;

START TRANSACTION;

SET time_zone = '+09:00';
SET @author_product_entry_target_date = COALESCE(@author_product_entry_target_date, DATE_SUB(CURDATE(), INTERVAL 1 DAY));
SET @author_product_entry_target_start = TIMESTAMP(@author_product_entry_target_date);
SET @author_product_entry_target_end = DATE_ADD(@author_product_entry_target_start, INTERVAL 1 DAY);

INSERT IGNORE INTO tb_cms_batch_job_process (
    job_file_id,
    job_group_id,
    job_order,
    completed_yn,
    job_list,
    created_id,
    updated_id
)
SELECT 'author_product_entry_daily_batch.sh',
       0,
       0,
       'Y',
       'author_product_entry_daily_batch.sh',
       0,
       0
  FROM dual
 WHERE NOT EXISTS (
    SELECT 1
      FROM tb_cms_batch_job_process x
     WHERE x.job_file_id = 'author_product_entry_daily_batch.sh'
 );

SELECT a.id,
       a.completed_yn,
       COALESCE(a.updated_date, '1970-01-01 00:00:00')
  INTO @job_id,
       @job_completed_yn,
       @job_updated_date
  FROM tb_cms_batch_job_process a
 WHERE a.job_file_id = 'author_product_entry_daily_batch.sh'
 ORDER BY a.updated_date DESC, a.id DESC
 LIMIT 1
 FOR UPDATE;

SET @in_progress_stale_minutes = COALESCE(@in_progress_stale_minutes, 60);
SET @in_progress_guard_sql = IF(
    @job_completed_yn = 'N'
    AND TIMESTAMPDIFF(MINUTE, @job_updated_date, NOW()) < @in_progress_stale_minutes,
    'SELECT * FROM __author_product_entry_daily_batch_in_progress__',
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

DELETE FROM tb_author_product_entry_daily
 WHERE stat_date = @author_product_entry_target_date;

INSERT INTO tb_author_product_entry_daily (
    stat_date,
    product_id,
    entry_source_group,
    entry_source_norm,
    detail_view_count,
    detail_session_count,
    detail_visitor_count,
    login_user_count,
    created_date,
    updated_date
)
SELECT
    @author_product_entry_target_date AS stat_date,
    resolved_pv.product_id,
    resolved_pv.entry_source_group,
    resolved_pv.entry_source_norm,
    COUNT(*) AS detail_view_count,
    COUNT(DISTINCT resolved_pv.session_id) AS detail_session_count,
    COUNT(DISTINCT resolved_pv.visitor_id) AS detail_visitor_count,
    COUNT(DISTINCT resolved_pv.user_id) AS login_user_count,
    NOW() AS created_date,
    NOW() AS updated_date
FROM (
    SELECT
        COALESCE(
            pv.product_id,
            CASE
                WHEN pv.path REGEXP '^/product/[0-9]+$'
                THEN CAST(SUBSTRING(pv.path, LENGTH('/product/') + 1) AS UNSIGNED)
                ELSE NULL
            END
        ) AS product_id,
        COALESCE(
            pv.entry_source_group,
            CASE
                WHEN pv.entry_source IN ('social', 'instagram', 'x', 'twitter', 'threads')
                  OR pv.utm_medium = 'social'
                  OR pv.utm_source IN ('social', 'instagram', 'x', 'twitter', 'threads')
                  OR pv.external_referrer_group IN ('social', 'instagram', 'x', 'twitter', 'threads')
                  OR pv.external_referrer_host IN ('t.co', 'x.com', 'twitter.com', 'instagram.com', 'threads.net', 'threads.com')
                THEN 'social'
                WHEN pv.entry_source LIKE 'search_%'
                  OR pv.referrer_path LIKE '/product/search%'
                THEN 'search'
                WHEN pv.entry_source LIKE 'top50_%'
                  OR pv.referrer_path LIKE '/product/top50%'
                THEN 'ranking'
                WHEN pv.entry_source = 'direct'
                THEN 'direct'
                WHEN pv.entry_source = 'other'
                THEN 'other'
                WHEN pv.entry_source IS NOT NULL
                THEN 'recommend_slot'
                WHEN (pv.referrer_path IS NULL OR pv.referrer_path = '')
                  AND (
                    pv.external_referrer_group IS NULL
                    OR pv.external_referrer_group IN ('direct', 'internal', 'unknown')
                  )
                THEN 'direct'
                ELSE 'other'
            END
        ) AS entry_source_group,
        COALESCE(
            pv.entry_source,
            CASE
                WHEN pv.utm_medium = 'social'
                  OR pv.utm_source IN ('social', 'instagram', 'x', 'twitter', 'threads')
                  OR pv.external_referrer_group IN ('social', 'instagram', 'x', 'twitter', 'threads')
                  OR pv.external_referrer_host IN ('t.co', 'x.com', 'twitter.com', 'instagram.com', 'threads.net', 'threads.com')
                THEN 'social'
                WHEN pv.entry_source LIKE 'search_%'
                  OR pv.referrer_path LIKE '/product/search%'
                THEN 'search'
                WHEN pv.entry_source LIKE 'top50_%'
                  OR pv.referrer_path LIKE '/product/top50%'
                THEN 'ranking'
                WHEN (pv.referrer_path IS NULL OR pv.referrer_path = '')
                  AND (
                    pv.external_referrer_group IS NULL
                    OR pv.external_referrer_group IN ('direct', 'internal', 'unknown')
                  )
                THEN 'direct'
                ELSE 'other'
            END,
            '__null__'
        ) AS entry_source_norm,
        pv.session_id,
        pv.visitor_id,
        pv.user_id
    FROM tb_site_page_view_event pv
    WHERE pv.route_group = 'product_detail'
      AND pv.occurred_at >= @author_product_entry_target_start
      AND pv.occurred_at < @author_product_entry_target_end
) resolved_pv
WHERE resolved_pv.product_id IS NOT NULL
GROUP BY
    resolved_pv.product_id,
    resolved_pv.entry_source_group,
    resolved_pv.entry_source_norm;

UPDATE tb_cms_batch_job_process a
   SET a.completed_yn = 'Y',
       a.updated_id = 0
 WHERE a.id = @job_id;

COMMIT;
