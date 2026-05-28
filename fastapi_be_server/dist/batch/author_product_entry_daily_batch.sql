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
    pv.product_id,
    COALESCE(pv.entry_source_group, 'other') AS entry_source_group,
    COALESCE(pv.entry_source, '__null__') AS entry_source_norm,
    COUNT(*) AS detail_view_count,
    COUNT(DISTINCT pv.session_id) AS detail_session_count,
    COUNT(DISTINCT pv.visitor_id) AS detail_visitor_count,
    COUNT(DISTINCT pv.user_id) AS login_user_count,
    NOW() AS created_date,
    NOW() AS updated_date
FROM tb_site_page_view_event pv
WHERE pv.route_group = 'product_detail'
  AND pv.product_id IS NOT NULL
  AND pv.occurred_at >= @author_product_entry_target_start
  AND pv.occurred_at < @author_product_entry_target_end
GROUP BY
    pv.product_id,
    COALESCE(pv.entry_source_group, 'other'),
    COALESCE(pv.entry_source, '__null__');

UPDATE tb_cms_batch_job_process a
   SET a.completed_yn = 'Y',
       a.updated_id = 0
 WHERE a.id = @job_id;

COMMIT;
