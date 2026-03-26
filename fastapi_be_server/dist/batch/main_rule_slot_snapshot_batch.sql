USE likenovel;

START TRANSACTION;

SET @job_lock_name = 'lk_main_rule_slot_snapshot_batch';
SET @job_lock_acquired = GET_LOCK(@job_lock_name, 30);
SET @job_lock_guard_sql = IF(
    @job_lock_acquired = 1,
    'SELECT 1',
    'SELECT * FROM __main_rule_slot_snapshot_lock_not_acquired__'
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
SELECT 'main_rule_slot_snapshot_batch.sh',
       0,
       0,
       'N',
       'main_rule_slot_snapshot_batch.sh',
       0,
       0
  FROM dual
 WHERE NOT EXISTS (
    SELECT 1
      FROM tb_cms_batch_job_process x
     WHERE x.job_file_id = 'main_rule_slot_snapshot_batch.sh'
 );

SELECT a.id
  INTO @job_id
  FROM tb_cms_batch_job_process a
 WHERE a.job_file_id = 'main_rule_slot_snapshot_batch.sh'
 ORDER BY a.updated_date DESC, a.id DESC
 LIMIT 1
 FOR UPDATE;

UPDATE tb_cms_batch_job_process a
   SET a.completed_yn = 'N'
     , a.created_id = 0
     , a.updated_id = 0
 WHERE a.id = @job_id;

SET @anchor_date = DATE('2026-01-01');
SET @snapshot_ref_at = CURDATE();
SET @snapshot_start_date = DATE_SUB(
    @snapshot_ref_at,
    INTERVAL MOD(DATEDIFF(@snapshot_ref_at, @anchor_date), 3) DAY
);
SET @snapshot_end_date = DATE_ADD(@snapshot_start_date, INTERVAL 2 DAY);

SELECT COUNT(DISTINCT CONCAT(slot_key, ':', adult_yn))
  INTO @current_snapshot_slot_count
  FROM tb_main_rule_slot_snapshot
 WHERE snapshot_start_date = @snapshot_start_date
   AND snapshot_end_date = @snapshot_end_date;

SELECT (
    CASE WHEN EXISTS (
        SELECT 1
          FROM tb_main_rule_slot_snapshot s
         WHERE s.snapshot_start_date = @snapshot_start_date
           AND s.snapshot_end_date = @snapshot_end_date
           AND s.slot_key = 'free-new-3up'
           AND s.adult_yn = 'N'
           AND s.product_id IS NULL
    ) AND EXISTS (
        SELECT 1
          FROM tb_product p
          LEFT JOIN (
              SELECT product_id, SUM(CASE WHEN open_yn = 'Y' THEN 1 ELSE 0 END) AS open_episode_count
              FROM tb_product_episode
              WHERE use_yn = 'Y'
              GROUP BY product_id
          ) ep_count ON ep_count.product_id = p.product_id
         WHERE p.price_type = 'free'
           AND p.open_yn = 'Y'
           AND p.blind_yn = 'N'
           AND p.status_code IN ('ongoing', 'rest')
           AND p.ratings_code = 'all'
           AND COALESCE(ep_count.open_episode_count, 0) >= 3
           AND p.created_date >= DATE_SUB(@snapshot_ref_at, INTERVAL 3 DAY)
    ) THEN 1 ELSE 0 END
  + CASE WHEN EXISTS (
        SELECT 1
          FROM tb_main_rule_slot_snapshot s
         WHERE s.snapshot_start_date = @snapshot_start_date
           AND s.snapshot_end_date = @snapshot_end_date
           AND s.slot_key = 'free-binge-10up'
           AND s.adult_yn = 'N'
           AND s.product_id IS NULL
    ) AND EXISTS (
        SELECT 1
          FROM tb_product p
          LEFT JOIN (
              SELECT product_id, SUM(CASE WHEN open_yn = 'Y' THEN 1 ELSE 0 END) AS open_episode_count
              FROM tb_product_episode
              WHERE use_yn = 'Y'
              GROUP BY product_id
          ) ep_count ON ep_count.product_id = p.product_id
         WHERE p.price_type = 'free'
           AND p.open_yn = 'Y'
           AND p.blind_yn = 'N'
           AND p.status_code IN ('ongoing', 'rest')
           AND p.ratings_code = 'all'
           AND COALESCE(ep_count.open_episode_count, 0) >= 10
           AND p.last_episode_date >= DATE_SUB(@snapshot_ref_at, INTERVAL 7 DAY)
    ) THEN 1 ELSE 0 END
  + CASE WHEN EXISTS (
        SELECT 1
          FROM tb_main_rule_slot_snapshot s
         WHERE s.snapshot_start_date = @snapshot_start_date
           AND s.snapshot_end_date = @snapshot_end_date
           AND s.slot_key = 'free-new-3up'
           AND s.adult_yn = 'Y'
           AND s.product_id IS NULL
    ) AND EXISTS (
        SELECT 1
          FROM tb_product p
          LEFT JOIN (
              SELECT product_id, SUM(CASE WHEN open_yn = 'Y' THEN 1 ELSE 0 END) AS open_episode_count
              FROM tb_product_episode
              WHERE use_yn = 'Y'
              GROUP BY product_id
          ) ep_count ON ep_count.product_id = p.product_id
         WHERE p.price_type = 'free'
           AND p.open_yn = 'Y'
           AND p.blind_yn = 'N'
           AND p.status_code IN ('ongoing', 'rest')
           AND p.ratings_code IN ('all', 'adult')
           AND COALESCE(ep_count.open_episode_count, 0) >= 3
           AND p.created_date >= DATE_SUB(@snapshot_ref_at, INTERVAL 3 DAY)
    ) THEN 1 ELSE 0 END
  + CASE WHEN EXISTS (
        SELECT 1
          FROM tb_main_rule_slot_snapshot s
         WHERE s.snapshot_start_date = @snapshot_start_date
           AND s.snapshot_end_date = @snapshot_end_date
           AND s.slot_key = 'free-binge-10up'
           AND s.adult_yn = 'Y'
           AND s.product_id IS NULL
    ) AND EXISTS (
        SELECT 1
          FROM tb_product p
          LEFT JOIN (
              SELECT product_id, SUM(CASE WHEN open_yn = 'Y' THEN 1 ELSE 0 END) AS open_episode_count
              FROM tb_product_episode
              WHERE use_yn = 'Y'
              GROUP BY product_id
          ) ep_count ON ep_count.product_id = p.product_id
         WHERE p.price_type = 'free'
           AND p.open_yn = 'Y'
           AND p.blind_yn = 'N'
           AND p.status_code IN ('ongoing', 'rest')
           AND p.ratings_code IN ('all', 'adult')
           AND COALESCE(ep_count.open_episode_count, 0) >= 10
           AND p.last_episode_date >= DATE_SUB(@snapshot_ref_at, INTERVAL 7 DAY)
    ) THEN 1 ELSE 0 END
) INTO @stale_placeholder_slot_count;

SET @should_build = IF(@current_snapshot_slot_count >= 4 AND @stale_placeholder_slot_count = 0, 0, 1);

DELETE FROM tb_main_rule_slot_snapshot
 WHERE snapshot_start_date = @snapshot_start_date
   AND snapshot_end_date = @snapshot_end_date
   AND @should_build = 1;

INSERT INTO tb_main_rule_slot_snapshot (
    slot_key,
    adult_yn,
    snapshot_start_date,
    snapshot_end_date,
    display_order,
    product_id,
    created_id,
    created_date,
    updated_id,
    updated_date
)
SELECT
    'free-new-3up',
    'N',
    @snapshot_start_date,
    @snapshot_end_date,
    ranked.display_order,
    ranked.product_id,
    0,
    NOW(),
    0,
    NOW()
FROM (
    SELECT
        p.product_id,
        ROW_NUMBER() OVER (
            ORDER BY
                COALESCE(pcv.count_hit_indicator, 0) DESC,
                COALESCE(pcv.count_bookmark_indicator, 0) DESC,
                p.count_hit DESC,
                p.created_date DESC,
                p.product_id DESC
        ) AS display_order
    FROM tb_product p
    LEFT JOIN (
        SELECT
            product_id,
            SUM(CASE WHEN open_yn = 'Y' THEN 1 ELSE 0 END) AS open_episode_count
        FROM tb_product_episode
        WHERE use_yn = 'Y'
        GROUP BY product_id
    ) ep_count ON ep_count.product_id = p.product_id
    LEFT JOIN tb_product_count_variance pcv
        ON pcv.product_id = p.product_id
    WHERE p.price_type = 'free'
      AND p.open_yn = 'Y'
      AND p.blind_yn = 'N'
      AND p.status_code IN ('ongoing', 'rest')
      AND p.ratings_code = 'all'
      AND COALESCE(ep_count.open_episode_count, 0) >= 3
      AND p.created_date >= DATE_SUB(@snapshot_ref_at, INTERVAL 3 DAY)
) ranked
WHERE ranked.display_order <= 12
  AND @should_build = 1;

INSERT INTO tb_main_rule_slot_snapshot (
    slot_key,
    adult_yn,
    snapshot_start_date,
    snapshot_end_date,
    display_order,
    product_id,
    created_id,
    created_date,
    updated_id,
    updated_date
)
SELECT
    'free-new-3up',
    'N',
    @snapshot_start_date,
    @snapshot_end_date,
    0,
    NULL,
    0,
    NOW(),
    0,
    NOW()
FROM dual
WHERE @should_build = 1
  AND NOT EXISTS (
      SELECT 1
        FROM tb_main_rule_slot_snapshot s
       WHERE s.slot_key = 'free-new-3up'
         AND s.adult_yn = 'N'
         AND s.snapshot_start_date = @snapshot_start_date
         AND s.snapshot_end_date = @snapshot_end_date
  );

INSERT INTO tb_main_rule_slot_snapshot (
    slot_key,
    adult_yn,
    snapshot_start_date,
    snapshot_end_date,
    display_order,
    product_id,
    created_id,
    created_date,
    updated_id,
    updated_date
)
SELECT
    'free-binge-10up',
    'N',
    @snapshot_start_date,
    @snapshot_end_date,
    ranked.display_order,
    ranked.product_id,
    0,
    NOW(),
    0,
    NOW()
FROM (
    SELECT
        p.product_id,
        ROW_NUMBER() OVER (
            ORDER BY
                COALESCE(pti.reading_rate, 0) DESC,
                COALESCE(pcv.count_hit_indicator, 0) DESC,
                p.count_bookmark DESC,
                p.count_hit DESC,
                p.product_id DESC
        ) AS display_order
    FROM tb_product p
    LEFT JOIN (
        SELECT
            product_id,
            SUM(CASE WHEN open_yn = 'Y' THEN 1 ELSE 0 END) AS open_episode_count
        FROM tb_product_episode
        WHERE use_yn = 'Y'
        GROUP BY product_id
    ) ep_count ON ep_count.product_id = p.product_id
    LEFT JOIN tb_product_trend_index pti
        ON pti.product_id = p.product_id
    LEFT JOIN tb_product_count_variance pcv
        ON pcv.product_id = p.product_id
    WHERE p.price_type = 'free'
      AND p.open_yn = 'Y'
      AND p.blind_yn = 'N'
      AND p.status_code IN ('ongoing', 'rest')
      AND p.ratings_code = 'all'
      AND COALESCE(ep_count.open_episode_count, 0) >= 10
      AND p.last_episode_date >= DATE_SUB(@snapshot_ref_at, INTERVAL 7 DAY)
      AND NOT EXISTS (
          SELECT 1
            FROM tb_main_rule_slot_snapshot s
           WHERE s.slot_key = 'free-new-3up'
             AND s.adult_yn = 'N'
             AND s.snapshot_start_date = @snapshot_start_date
             AND s.snapshot_end_date = @snapshot_end_date
             AND s.product_id = p.product_id
      )
) ranked
WHERE ranked.display_order <= 12
  AND @should_build = 1;

INSERT INTO tb_main_rule_slot_snapshot (
    slot_key,
    adult_yn,
    snapshot_start_date,
    snapshot_end_date,
    display_order,
    product_id,
    created_id,
    created_date,
    updated_id,
    updated_date
)
SELECT
    'free-binge-10up',
    'N',
    @snapshot_start_date,
    @snapshot_end_date,
    0,
    NULL,
    0,
    NOW(),
    0,
    NOW()
FROM dual
WHERE @should_build = 1
  AND NOT EXISTS (
      SELECT 1
        FROM tb_main_rule_slot_snapshot s
       WHERE s.slot_key = 'free-binge-10up'
         AND s.adult_yn = 'N'
         AND s.snapshot_start_date = @snapshot_start_date
         AND s.snapshot_end_date = @snapshot_end_date
  );

INSERT INTO tb_main_rule_slot_snapshot (
    slot_key,
    adult_yn,
    snapshot_start_date,
    snapshot_end_date,
    display_order,
    product_id,
    created_id,
    created_date,
    updated_id,
    updated_date
)
SELECT
    'free-new-3up',
    'Y',
    @snapshot_start_date,
    @snapshot_end_date,
    ranked.display_order,
    ranked.product_id,
    0,
    NOW(),
    0,
    NOW()
FROM (
    SELECT
        p.product_id,
        ROW_NUMBER() OVER (
            ORDER BY
                COALESCE(pcv.count_hit_indicator, 0) DESC,
                COALESCE(pcv.count_bookmark_indicator, 0) DESC,
                p.count_hit DESC,
                p.created_date DESC,
                p.product_id DESC
        ) AS display_order
    FROM tb_product p
    LEFT JOIN (
        SELECT
            product_id,
            SUM(CASE WHEN open_yn = 'Y' THEN 1 ELSE 0 END) AS open_episode_count
        FROM tb_product_episode
        WHERE use_yn = 'Y'
        GROUP BY product_id
    ) ep_count ON ep_count.product_id = p.product_id
    LEFT JOIN tb_product_count_variance pcv
        ON pcv.product_id = p.product_id
    WHERE p.price_type = 'free'
      AND p.open_yn = 'Y'
      AND p.blind_yn = 'N'
      AND p.status_code IN ('ongoing', 'rest')
      AND p.ratings_code IN ('all', 'adult')
      AND COALESCE(ep_count.open_episode_count, 0) >= 3
      AND p.created_date >= DATE_SUB(@snapshot_ref_at, INTERVAL 3 DAY)
) ranked
WHERE ranked.display_order <= 12
  AND @should_build = 1;

INSERT INTO tb_main_rule_slot_snapshot (
    slot_key,
    adult_yn,
    snapshot_start_date,
    snapshot_end_date,
    display_order,
    product_id,
    created_id,
    created_date,
    updated_id,
    updated_date
)
SELECT
    'free-new-3up',
    'Y',
    @snapshot_start_date,
    @snapshot_end_date,
    0,
    NULL,
    0,
    NOW(),
    0,
    NOW()
FROM dual
WHERE @should_build = 1
  AND NOT EXISTS (
      SELECT 1
        FROM tb_main_rule_slot_snapshot s
       WHERE s.slot_key = 'free-new-3up'
         AND s.adult_yn = 'Y'
         AND s.snapshot_start_date = @snapshot_start_date
         AND s.snapshot_end_date = @snapshot_end_date
  );

INSERT INTO tb_main_rule_slot_snapshot (
    slot_key,
    adult_yn,
    snapshot_start_date,
    snapshot_end_date,
    display_order,
    product_id,
    created_id,
    created_date,
    updated_id,
    updated_date
)
SELECT
    'free-binge-10up',
    'Y',
    @snapshot_start_date,
    @snapshot_end_date,
    ranked.display_order,
    ranked.product_id,
    0,
    NOW(),
    0,
    NOW()
FROM (
    SELECT
        p.product_id,
        ROW_NUMBER() OVER (
            ORDER BY
                COALESCE(pti.reading_rate, 0) DESC,
                COALESCE(pcv.count_hit_indicator, 0) DESC,
                p.count_bookmark DESC,
                p.count_hit DESC,
                p.product_id DESC
        ) AS display_order
    FROM tb_product p
    LEFT JOIN (
        SELECT
            product_id,
            SUM(CASE WHEN open_yn = 'Y' THEN 1 ELSE 0 END) AS open_episode_count
        FROM tb_product_episode
        WHERE use_yn = 'Y'
        GROUP BY product_id
    ) ep_count ON ep_count.product_id = p.product_id
    LEFT JOIN tb_product_trend_index pti
        ON pti.product_id = p.product_id
    LEFT JOIN tb_product_count_variance pcv
        ON pcv.product_id = p.product_id
    WHERE p.price_type = 'free'
      AND p.open_yn = 'Y'
      AND p.blind_yn = 'N'
      AND p.status_code IN ('ongoing', 'rest')
      AND p.ratings_code IN ('all', 'adult')
      AND COALESCE(ep_count.open_episode_count, 0) >= 10
      AND p.last_episode_date >= DATE_SUB(@snapshot_ref_at, INTERVAL 7 DAY)
      AND NOT EXISTS (
          SELECT 1
            FROM tb_main_rule_slot_snapshot s
           WHERE s.slot_key = 'free-new-3up'
             AND s.adult_yn = 'Y'
             AND s.snapshot_start_date = @snapshot_start_date
             AND s.snapshot_end_date = @snapshot_end_date
             AND s.product_id = p.product_id
      )
) ranked
WHERE ranked.display_order <= 12
  AND @should_build = 1;

INSERT INTO tb_main_rule_slot_snapshot (
    slot_key,
    adult_yn,
    snapshot_start_date,
    snapshot_end_date,
    display_order,
    product_id,
    created_id,
    created_date,
    updated_id,
    updated_date
)
SELECT
    'free-binge-10up',
    'Y',
    @snapshot_start_date,
    @snapshot_end_date,
    0,
    NULL,
    0,
    NOW(),
    0,
    NOW()
FROM dual
WHERE @should_build = 1
  AND NOT EXISTS (
      SELECT 1
        FROM tb_main_rule_slot_snapshot s
       WHERE s.slot_key = 'free-binge-10up'
         AND s.adult_yn = 'Y'
         AND s.snapshot_start_date = @snapshot_start_date
         AND s.snapshot_end_date = @snapshot_end_date
  );

UPDATE tb_cms_batch_job_process a
   SET a.completed_yn = 'Y'
     , a.last_processed_date = NOW()
     , a.created_id = 0
     , a.updated_id = 0
 WHERE a.id = @job_id;

COMMIT;

SELECT RELEASE_LOCK(@job_lock_name);
