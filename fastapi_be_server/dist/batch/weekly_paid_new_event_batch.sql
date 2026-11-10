-- 주간 유료화 신작 이벤트 갱신 (10분 주기)
-- - 이번 주(월 00:00 ~ 다음 주 월 00:00, DB time_zone 기준)에 유료 전환된 작품이 있으면
--   'N월 M주차 유료화 신작' 이벤트의 제목/구좌명/작품 목록/시작일을 이번 주 기준으로 교체한다.
-- - 이번 주 전환작이 없으면 아무것도 바꾸지 않는다(지난 주 제목과 작품 유지).
-- - 주차는 그 주 목요일이 속한 달 기준이다(목요일 일자 1~7일 = 1주차).
-- - 대상 이벤트는 홈 전광판과 같은 제목 패턴으로 찾으며, 정확히 1개일 때만 갱신한다.

SET @batch_now = NOW();
SET @week_start = DATE_SUB(DATE(@batch_now), INTERVAL WEEKDAY(@batch_now) DAY);
SET @week_end = DATE_ADD(@week_start, INTERVAL 7 DAY);
SET @week_thursday = DATE_ADD(@week_start, INTERVAL 3 DAY);
SET @event_title = CONCAT(
    MONTH(@week_thursday), '월 ',
    FLOOR((DAY(@week_thursday) - 1) / 7) + 1, '주차 유료화 신작'
);
SET @event_title_pattern = '^[0-9]+월[[:space:]]*[0-9]+주차?[[:space:]]*유료(화|전환)?[[:space:]]*신작$';

SET @product_ids = (
    SELECT CONCAT(
               '[',
               GROUP_CONCAT(p.product_id ORDER BY p.paid_open_date, p.product_id SEPARATOR ', '),
               ']'
           )
      FROM tb_product p
     WHERE p.price_type = 'paid'
       AND p.paid_open_date >= @week_start
       AND p.paid_open_date < @week_end
       AND p.paid_open_date <= @batch_now
       AND p.open_yn = 'Y'
       AND p.blind_yn = 'N'
);

SET @event_match_count = (
    SELECT COUNT(*)
      FROM tb_event_v2 e
     WHERE e.title REGEXP @event_title_pattern
);
SET @event_id = (
    SELECT MAX(e.id)
      FROM tb_event_v2 e
     WHERE e.title REGEXP @event_title_pattern
);

UPDATE tb_event_v2 e
   SET e.title = @event_title
     , e.account_name = CASE
           WHEN e.account_name REGEXP @event_title_pattern THEN @event_title
           ELSE e.account_name
       END
     , e.product_ids = @product_ids
     , e.start_date = @week_start
     , e.updated_id = 0
     , e.updated_date = @batch_now
 WHERE e.id = @event_id
   AND @event_match_count = 1
   AND @product_ids IS NOT NULL
   AND (
           e.title <> @event_title
        OR e.product_ids <> @product_ids
        OR e.start_date <> @week_start
        OR (e.account_name REGEXP @event_title_pattern AND e.account_name <> @event_title)
       );

SELECT @event_match_count AS event_match_count
     , @event_id AS event_id
     , @event_title AS event_title
     , @product_ids AS product_ids
     , ROW_COUNT() AS updated_rows;
