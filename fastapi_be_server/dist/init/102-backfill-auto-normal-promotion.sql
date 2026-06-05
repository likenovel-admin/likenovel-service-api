CREATE TABLE IF NOT EXISTS tb_auto_normal_promotion_backfill_102 (
    product_id INT NOT NULL PRIMARY KEY,
    user_id INT NOT NULL,
    title VARCHAR(100) NOT NULL,
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO tb_auto_normal_promotion_backfill_102
    (product_id, user_id, title)
SELECT
    p.product_id,
    p.user_id,
    p.title
  FROM tb_product p
  INNER JOIN (
      SELECT
          e.product_id,
          COUNT(*) AS episode_count,
          COALESCE(SUM(e.episode_text_count), 0) AS episode_text_count
        FROM tb_product_episode e
       WHERE e.use_yn = 'Y'
         AND e.open_yn = 'Y'
       GROUP BY e.product_id
      HAVING COUNT(*) >= 5
         AND COALESCE(SUM(e.episode_text_count), 0) >= 20000
  ) eligible ON eligible.product_id = p.product_id
 WHERE p.price_type = 'free'
   AND p.open_yn = 'Y'
   AND COALESCE(p.blind_yn, 'N') = 'N'
   AND COALESCE(p.product_type, 'free') = 'free';

UPDATE tb_product p
INNER JOIN tb_auto_normal_promotion_backfill_102 target
   ON target.product_id = p.product_id
  SET p.product_type = 'normal',
      p.apply_date = COALESCE(p.apply_date, NOW()),
      p.updated_id = -1,
      p.updated_date = NOW()
 WHERE p.price_type = 'free'
   AND p.open_yn = 'Y'
   AND COALESCE(p.blind_yn, 'N') = 'N'
   AND COALESCE(p.product_type, 'free') = 'free';

INSERT INTO tb_user_notification_item
    (user_id, noti_type, title, content, read_yn, created_id, created_date)
SELECT
    target.user_id,
    'system',
    CONCAT('[', target.title, '] 일반연재로 자동승급되었습니다.'),
    '일반연재 조건을 충족했습니다.',
    'N',
    -1,
    NOW()
  FROM tb_auto_normal_promotion_backfill_102 target
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

DROP TABLE IF EXISTS tb_auto_normal_promotion_backfill_102;
