SET @job_lock_name = 'lk_free_episode_campaign_expire_batch';
SET @job_lock_acquired = GET_LOCK(@job_lock_name, 30);
SET @job_lock_guard_sql = IF(
    @job_lock_acquired = 1,
    'SELECT 1',
    'SELECT * FROM __free_episode_campaign_expire_lock_not_acquired__'
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
SELECT 'free_episode_campaign_expire_batch.sh',
       0,
       0,
       'N',
       'free_episode_campaign_expire_batch.sh',
       0,
       0
  FROM dual
 WHERE NOT EXISTS (
    SELECT 1
      FROM tb_cms_batch_job_process x
     WHERE x.job_file_id = 'free_episode_campaign_expire_batch.sh'
 );

SELECT a.id
  INTO @job_id
  FROM tb_cms_batch_job_process a
 WHERE a.job_file_id = 'free_episode_campaign_expire_batch.sh'
 ORDER BY a.updated_date DESC, a.id DESC
 LIMIT 1;

UPDATE tb_cms_batch_job_process a
   SET a.completed_yn = 'N'
     , a.created_id = 0
     , a.updated_id = 0
 WHERE a.id = @job_id;

SET @batch_now = NOW();

DROP TEMPORARY TABLE IF EXISTS tmp_free_episode_campaign_expired;
CREATE TEMPORARY TABLE tmp_free_episode_campaign_expired AS
SELECT c.id,
       c.product_id,
       c.restore_free_start_no,
       c.restore_free_end_no
  FROM tb_product_free_episode_campaign c
 WHERE c.active_yn = 'Y'
   AND c.ends_at <= @batch_now;

START TRANSACTION;

UPDATE tb_product_episode e
 INNER JOIN tmp_free_episode_campaign_expired c
    ON c.product_id = e.product_id
   SET e.price_type = CASE
           WHEN e.episode_no BETWEEN c.restore_free_start_no AND c.restore_free_end_no THEN 'free'
           ELSE 'paid'
       END,
       e.updated_id = 0,
       e.updated_date = @batch_now
 WHERE e.use_yn = 'Y';

UPDATE tb_product p
 INNER JOIN tmp_free_episode_campaign_expired c
    ON c.product_id = p.product_id
   SET p.price_type = 'paid',
       p.paid_episode_no = c.restore_free_end_no + 1,
       p.updated_id = 0,
       p.updated_date = @batch_now;

UPDATE tb_product_free_episode_campaign c
 INNER JOIN tmp_free_episode_campaign_expired x
    ON x.id = c.id
   SET c.active_yn = 'N',
       c.ended_at = @batch_now,
       c.updated_id = 0,
       c.updated_date = @batch_now;

COMMIT;

UPDATE tb_cms_batch_job_process a
   SET a.completed_yn = 'Y'
     , a.created_id = 0
     , a.updated_id = 0
 WHERE a.id = @job_id;

SELECT RELEASE_LOCK(@job_lock_name) INTO @job_lock_released;
