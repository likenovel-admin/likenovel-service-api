update tb_cms_batch_job_process a
   set a.completed_yn = 'N'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'statistics_aggregation_daily_batch.sh'
;

start transaction;

-- site 통계 테이블에서 전날 데이터 삭제 (중복 방지)
DELETE FROM tb_site_statistics WHERE DATE(date) = DATE_SUB(CURDATE(), INTERVAL 1 DAY);

-- 전날 로그 집계하여 site 통계 테이블에 insert
INSERT INTO tb_site_statistics (date, visitors, page_view, login_count, dau, mau, created_date)
SELECT 
    DATE_SUB(CURDATE(), INTERVAL 1 DAY) as date,
    COUNT(DISTINCT CASE WHEN type = 'visit' THEN user_id END) as visitors,
    COUNT(CASE WHEN type = 'page_view' THEN 1 END) as page_view,
    COUNT(CASE WHEN type = 'login' THEN 1 END) as login_count,
    COUNT(DISTINCT CASE WHEN type = 'active' THEN user_id END) as dau,
    (SELECT COUNT(DISTINCT user_id) 
        FROM tb_site_statistics_log 
        WHERE date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) 
        AND date < CURDATE()
        AND type = 'active') as mau,
    NOW() as created_date
FROM tb_site_statistics_log
WHERE DATE(date) = DATE_SUB(CURDATE(), INTERVAL 1 DAY);

-- 결제 통계 테이블에서 전날 데이터 삭제 (중복 방지)
DELETE FROM tb_payment_statistics 
WHERE DATE(date) = DATE_SUB(CURDATE(), INTERVAL 1 DAY);

-- 회원별 결제 통계 테이블에서 전날 데이터 삭제 (중복 방지)
DELETE FROM tb_payment_statistics_by_user
WHERE DATE(date) = DATE_SUB(CURDATE(), INTERVAL 1 DAY);

-- 전날 로그 집계하여 결제 통계 테이블에 insert
INSERT INTO tb_payment_statistics (
    date,
    pay_count,
    pay_coin,
    pay_amount,
    use_coin_count,
    use_coin,
    donation_count,
    donation_coin,
    ad_revenue,
    created_date
)
SELECT
    DATE(date) AS stat_date,
    SUM(CASE WHEN type = 'pay' THEN 1 ELSE 0 END) AS pay_count,
    SUM(CASE WHEN type = 'pay' THEN amount ELSE 0 END) AS pay_coin,
    SUM(CASE WHEN type = 'pay' THEN amount ELSE 0 END) AS pay_amount,
    SUM(CASE WHEN type = 'use_coin' THEN 1 ELSE 0 END) AS use_coin_count,
    SUM(CASE WHEN type = 'use_coin' THEN amount ELSE 0 END) AS use_coin,
    SUM(CASE WHEN type = 'donation' THEN 1 ELSE 0 END) AS donation_count,
    SUM(CASE WHEN type = 'donation' THEN amount ELSE 0 END) AS donation_coin,
    SUM(CASE WHEN type = 'ad' THEN amount ELSE 0 END) AS ad_revenue,
    NOW()
FROM tb_payment_statistics_log
WHERE DATE(date) = DATE_SUB(CURDATE(), INTERVAL 1 DAY)
GROUP BY stat_date
ON DUPLICATE KEY UPDATE
    pay_count = VALUES(pay_count),
    pay_coin = VALUES(pay_coin),
    pay_amount = VALUES(pay_amount),
    use_coin_count = VALUES(use_coin_count),
    use_coin = VALUES(use_coin),
    donation_count = VALUES(donation_count),
    donation_coin = VALUES(donation_coin),
    ad_revenue = VALUES(ad_revenue),
    created_date = VALUES(created_date);

-- 전날 로그 집계하여 회원별 결제 통계 테이블에 insert
INSERT INTO tb_payment_statistics_by_user (
    date,
    user_id,
    pay_count,
    pay_coin,
    pay_amount,
    use_coin_count,
    use_coin,
    donation_count,
    donation_coin,
    ad_revenue,
    created_date
)
SELECT
    DATE(date) AS stat_date,
    user_id,
    SUM(CASE WHEN type = 'pay' THEN 1 ELSE 0 END) AS pay_count,
    SUM(CASE WHEN type = 'pay' THEN amount ELSE 0 END) AS pay_coin,
    SUM(CASE WHEN type = 'pay' THEN amount ELSE 0 END) AS pay_amount,
    SUM(CASE WHEN type = 'use_coin' THEN 1 ELSE 0 END) AS use_coin_count,
    SUM(CASE WHEN type = 'use_coin' THEN amount ELSE 0 END) AS use_coin,
    SUM(CASE WHEN type = 'donation' THEN 1 ELSE 0 END) AS donation_count,
    SUM(CASE WHEN type = 'donation' THEN amount ELSE 0 END) AS donation_coin,
    SUM(CASE WHEN type = 'ad' THEN amount ELSE 0 END) AS ad_revenue,
    NOW()
FROM tb_payment_statistics_log
WHERE DATE(date) = DATE_SUB(CURDATE(), INTERVAL 1 DAY)
GROUP BY stat_date, user_id
ON DUPLICATE KEY UPDATE
    pay_count = VALUES(pay_count),
    pay_coin = VALUES(pay_coin),
    pay_amount = VALUES(pay_amount),
    use_coin_count = VALUES(use_coin_count),
    use_coin = VALUES(use_coin),
    donation_count = VALUES(donation_count),
    donation_coin = VALUES(donation_coin),
    ad_revenue = VALUES(ad_revenue),
    created_date = VALUES(created_date);

update tb_cms_batch_job_process a
   set a.completed_yn = 'Y'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'statistics_aggregation_daily_batch.sh'
;

commit;
