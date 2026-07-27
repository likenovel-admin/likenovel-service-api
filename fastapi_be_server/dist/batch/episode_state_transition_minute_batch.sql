SET @job_lock_name = 'lk_episode_state_transition_minute_batch';
SET @job_lock_acquired = GET_LOCK(@job_lock_name, 30);
SET @job_lock_guard_sql = IF(
    @job_lock_acquired = 1,
    'SELECT 1',
    'SELECT * FROM __episode_state_transition_lock_not_acquired__'
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
SELECT 'episode_state_transition_minute_batch.sh',
       0,
       0,
       'N',
       'episode_state_transition_minute_batch.sh',
       0,
       0
  FROM dual
 WHERE NOT EXISTS (
    SELECT 1
      FROM tb_cms_batch_job_process x
     WHERE x.job_file_id = 'episode_state_transition_minute_batch.sh'
 );

SELECT a.id
  INTO @job_id
  FROM tb_cms_batch_job_process a
 WHERE a.job_file_id = 'episode_state_transition_minute_batch.sh'
 ORDER BY a.updated_date DESC, a.id DESC
 LIMIT 1;

UPDATE tb_cms_batch_job_process a
   SET a.completed_yn = 'N'
     , a.created_id = 0
     , a.updated_id = 0
 WHERE a.id = @job_id;

-- 동일 실행 내 시각 경계를 고정해 statement 간 NOW() drift를 제거한다.
SET @batch_now = NOW();

DROP TEMPORARY TABLE IF EXISTS tmp_episode_state_transition_release_episodes;
CREATE TEMPORARY TABLE tmp_episode_state_transition_release_episodes AS
SELECT e.episode_id,
       e.product_id
  FROM tb_product_episode e
 WHERE e.publish_reserve_date IS NOT NULL
   AND e.publish_reserve_date <= @batch_now
   AND (e.open_changed_date IS NULL OR e.open_changed_date <= e.publish_reserve_date)
   AND e.open_yn = 'N'
   AND e.use_yn = 'Y';

DROP TEMPORARY TABLE IF EXISTS tmp_episode_state_transition_release_products;
CREATE TEMPORARY TABLE tmp_episode_state_transition_release_products AS
SELECT DISTINCT r.product_id
  FROM tmp_episode_state_transition_release_episodes r;

DROP TEMPORARY TABLE IF EXISTS tmp_episode_state_transition_normal_promotions;
CREATE TEMPORARY TABLE tmp_episode_state_transition_normal_promotions (
    product_id INT NOT NULL PRIMARY KEY,
    user_id INT NOT NULL,
    title VARCHAR(100) NOT NULL
) ENGINE=InnoDB;

START TRANSACTION;

UPDATE tb_product_episode e
 INNER JOIN tmp_episode_state_transition_release_episodes r
    ON r.episode_id = e.episode_id
   SET e.open_yn = 'Y'
     , e.open_changed_date = @batch_now
     , e.updated_id = 0
     , e.updated_date = @batch_now;

UPDATE tb_product p
 INNER JOIN tmp_episode_state_transition_release_products r
    ON r.product_id = p.product_id
   SET p.open_yn = 'Y'
     , p.last_episode_date = @batch_now
     , p.updated_id = 0
     , p.updated_date = @batch_now
 WHERE p.open_yn = 'N'
   AND p.blind_yn = 'N';

UPDATE tb_product p
 INNER JOIN tmp_episode_state_transition_release_products r
    ON r.product_id = p.product_id
   SET p.last_episode_date = @batch_now
     , p.updated_date = @batch_now
 WHERE p.open_yn = 'Y';

SELECT p.product_id
  FROM tb_product p
 INNER JOIN tmp_episode_state_transition_release_products r
    ON r.product_id = p.product_id
 ORDER BY p.product_id
 FOR UPDATE;

INSERT INTO tmp_episode_state_transition_normal_promotions
    (product_id, user_id, title)
SELECT p.product_id,
       p.user_id,
       p.title
  FROM tb_product p
 INNER JOIN tmp_episode_state_transition_release_products r
    ON r.product_id = p.product_id
 WHERE p.price_type = 'free'
   AND p.open_yn = 'Y'
   AND COALESCE(p.blind_yn, 'N') = 'N'
   AND COALESCE(p.product_type, 'free') = 'free'
   AND EXISTS (
       SELECT 1
         FROM tb_product_episode e
        WHERE e.product_id = p.product_id
          AND e.use_yn = 'Y'
          AND e.open_yn = 'Y'
        GROUP BY e.product_id
       HAVING COUNT(*) >= 5
          AND COALESCE(SUM(e.episode_text_count), 0) >= 20000
   );

UPDATE tb_product p
 INNER JOIN tmp_episode_state_transition_normal_promotions target
    ON target.product_id = p.product_id
   SET p.product_type = 'normal'
     , p.apply_date = COALESCE(p.apply_date, @batch_now)
     , p.updated_id = target.user_id
     , p.updated_date = @batch_now
 WHERE COALESCE(p.product_type, 'free') = 'free';

INSERT INTO tb_user_notification_item (
    user_id,
    noti_type,
    title,
    content,
    read_yn,
    created_id,
    created_date
)
SELECT target.user_id,
       'system',
       CONCAT('[', target.title, '] 일반연재로 자동승급되었습니다.'),
       '일반연재 조건을 충족했습니다.',
       'N',
       target.user_id,
       @batch_now
  FROM tmp_episode_state_transition_normal_promotions target
 INNER JOIN tb_product p
    ON p.product_id = target.product_id
 WHERE p.product_type = 'normal'
   AND NOT EXISTS (
       SELECT 1
         FROM tb_user_notification_item n
        WHERE n.user_id = target.user_id
          AND n.noti_type = 'system'
          AND n.title = CONCAT('[', target.title, '] 일반연재로 자동승급되었습니다.')
          AND n.content = '일반연재 조건을 충족했습니다.'
   );

COMMIT;

DROP TEMPORARY TABLE IF EXISTS tmp_episode_state_transition_normal_promotions;

DROP TEMPORARY TABLE IF EXISTS tmp_episode_state_transition_paid_episodes;
CREATE TEMPORARY TABLE tmp_episode_state_transition_paid_episodes AS
SELECT e.episode_id,
       e.product_id
  FROM tb_product_episode e
 INNER JOIN tb_product p
    ON p.product_id = e.product_id
 WHERE p.paid_open_date IS NOT NULL
   AND p.paid_open_date <= @batch_now
   AND p.paid_episode_no IS NOT NULL
   AND e.episode_no >= p.paid_episode_no
   AND (e.price_type = 'free' OR e.price_type IS NULL)
   AND e.use_yn = 'Y';

DROP TEMPORARY TABLE IF EXISTS tmp_episode_state_transition_paid_products;
CREATE TEMPORARY TABLE tmp_episode_state_transition_paid_products AS
SELECT DISTINCT r.product_id
  FROM tmp_episode_state_transition_paid_episodes r;

START TRANSACTION;

UPDATE tb_product_episode e
 INNER JOIN tmp_episode_state_transition_paid_episodes r
    ON r.episode_id = e.episode_id
   SET e.price_type = 'paid'
     , e.updated_id = 0
     , e.updated_date = @batch_now;

UPDATE tb_product p
 INNER JOIN tmp_episode_state_transition_paid_products r
    ON r.product_id = p.product_id
   SET p.price_type = 'paid'
     , p.updated_id = 0
     , p.updated_date = @batch_now
 WHERE p.price_type = 'free'
   AND p.paid_open_date IS NOT NULL
   AND p.paid_open_date <= @batch_now
   AND p.paid_episode_no IS NOT NULL
   AND EXISTS (
       SELECT 1
         FROM tb_product_episode e
        WHERE e.product_id = p.product_id
          AND e.episode_no >= p.paid_episode_no
          AND e.price_type = 'paid'
          AND e.open_yn = 'Y'
          AND e.use_yn = 'Y'
   );

COMMIT;

UPDATE tb_cms_batch_job_process a
   SET a.completed_yn = 'Y'
     , a.created_id = 0
     , a.updated_id = 0
 WHERE a.id = @job_id;

SELECT RELEASE_LOCK(@job_lock_name) INTO @job_lock_released;
