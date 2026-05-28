
update tb_cms_batch_job_process a
   set a.completed_yn = 'N'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'service_reset_hourly_batch.sh'
;

SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED;

SET @recent_24h_basis_at = STR_TO_DATE(
    DATE_FORMAT(
        CASE
            WHEN MINUTE(NOW()) < 30 THEN DATE_SUB(NOW(), INTERVAL 1 HOUR)
            ELSE NOW()
        END,
        '%Y-%m-%d %H:30:00'
    ),
    '%Y-%m-%d %H:%i:%s'
);

start transaction;

-- 기존 랭킹을 임시 테이블에 저장 (privious_rank 계산용)
DROP TEMPORARY TABLE IF EXISTS tmp_previous_rank;
CREATE TEMPORARY TABLE tmp_previous_rank AS
SELECT product_id, current_rank
FROM tb_product_rank
WHERE created_date = (SELECT MAX(created_date) FROM tb_product_rank);

-- Top 랭킹 기준 데이터
-- 산식: 최근 24시간 조회수 90%, 누적 조회수 10%, CMS 평가는 산식 반영 없음
-- 연재 Top 후보: 공개 회차 3화 이상이며 최근 30일 내 공개 또는 미래 예약 공개가 있는 연재중 작품
SET @rank_freshness_basis_at = NOW();

SET @prev_24h_snapshot_exists = (
    SELECT COUNT(*)
      FROM tb_product_hit_snapshot_hourly
     WHERE basis_at = DATE_SUB(@recent_24h_basis_at, INTERVAL 24 HOUR)
);

DROP TEMPORARY TABLE IF EXISTS tmp_product_rank_basis;
CREATE TEMPORARY TABLE tmp_product_rank_basis AS
SELECT p.product_id
     , GREATEST(COALESCE(p.count_hit, 0), 0) AS count_hit
     , CASE
         WHEN @prev_24h_snapshot_exists > 0 THEN
           GREATEST(COALESCE(p.count_hit, 0) - COALESCE(prev_24h.count_hit, 0), 0)
         ELSE 0
       END AS recent_24h_count_hit
     , ep.open_episode_count
     , ep.latest_open_at
     , ep.next_reserved_at
  FROM tb_product p
  LEFT JOIN tb_product_hit_snapshot_hourly prev_24h
    ON prev_24h.product_id = p.product_id
   AND prev_24h.basis_at = DATE_SUB(@recent_24h_basis_at, INTERVAL 24 HOUR)
 INNER JOIN (
    SELECT b.product_id
         , SUM(CASE WHEN b.open_yn = 'Y' AND b.use_yn = 'Y' THEN 1 ELSE 0 END) AS open_episode_count
         , MAX(CASE WHEN b.open_yn = 'Y' AND b.use_yn = 'Y' THEN COALESCE(b.publish_reserve_date, b.open_changed_date, b.created_date) ELSE NULL END) AS latest_open_at
         , MIN(CASE WHEN b.open_yn = 'N' AND b.use_yn = 'Y' AND b.publish_reserve_date > @rank_freshness_basis_at THEN b.publish_reserve_date ELSE NULL END) AS next_reserved_at
      FROM tb_product_episode b
     WHERE b.use_yn = 'Y'
     GROUP BY b.product_id
 ) ep ON ep.product_id = p.product_id
 WHERE ep.open_episode_count >= 3
;

-- 기존 랭킹 데이터 전체 삭제 (중복 방지)
DELETE FROM tb_product_rank;

-- 무료 Top 랭킹 재계산
-- 공개 3회차 이상 작품만
-- 총점 = 90 * log(1 + 최근 24시간 조회수 정규화) + 10 * log(1 + 누적 조회수 정규화)
insert into tb_product_rank (product_id, current_rank, privious_rank, created_id, updated_id)
select t.product_id
     , t.current_rank
     , t.privious_rank
     , 0 as created_id
     , 0 as updated_id
  from (
    select z.product_id
         , ROW_NUMBER() OVER (order by round((
             90 * CASE WHEN z.max_recent_24h_count_hit > 0 THEN LN(1 + z.recent_24h_count_hit) / LN(1 + z.max_recent_24h_count_hit) ELSE 0 END
             + 10 * CASE WHEN z.max_count_hit > 0 THEN LN(1 + z.count_hit) / LN(1 + z.max_count_hit) ELSE 0 END
           ) / 100, 4) desc, z.recent_24h_count_hit desc, z.count_hit desc, z.product_id desc) as current_rank
         , w.current_rank as privious_rank
      from (
        select filtered.product_id
             , filtered.count_hit
             , filtered.recent_24h_count_hit
             , MAX(filtered.count_hit) OVER() AS max_count_hit
             , MAX(filtered.recent_24h_count_hit) OVER() AS max_recent_24h_count_hit
          from tmp_product_rank_basis filtered
         inner join tb_product y on filtered.product_id = y.product_id
           and y.price_type = 'free'
      ) z
      left join tmp_previous_rank w on z.product_id = w.product_id
     ORDER BY current_rank ASC
     limit 50 offset 0
  ) t
;

-- 유료 Top 랭킹 재계산
-- 공개 3회차 이상 작품만
-- 총점 = 90 * log(1 + 최근 24시간 조회수 정규화) + 10 * log(1 + 누적 조회수 정규화)
insert into tb_product_rank (product_id, current_rank, privious_rank, created_id, updated_id)
select t.product_id
     , t.current_rank
     , t.privious_rank
     , 0 as created_id
     , 0 as updated_id
  from (
    select z.product_id
         , ROW_NUMBER() OVER (order by round((
             90 * CASE WHEN z.max_recent_24h_count_hit > 0 THEN LN(1 + z.recent_24h_count_hit) / LN(1 + z.max_recent_24h_count_hit) ELSE 0 END
             + 10 * CASE WHEN z.max_count_hit > 0 THEN LN(1 + z.count_hit) / LN(1 + z.max_count_hit) ELSE 0 END
           ) / 100, 4) desc, z.recent_24h_count_hit desc, z.count_hit desc, z.product_id desc) as current_rank
         , w.current_rank as privious_rank
      from (
        select filtered.product_id
             , filtered.count_hit
             , filtered.recent_24h_count_hit
             , MAX(filtered.count_hit) OVER() AS max_count_hit
             , MAX(filtered.recent_24h_count_hit) OVER() AS max_recent_24h_count_hit
          from tmp_product_rank_basis filtered
         inner join tb_product y on filtered.product_id = y.product_id
           and y.price_type = 'paid'
      ) z
      left join tmp_previous_rank w on z.product_id = w.product_id
     ORDER BY current_rank ASC
     limit 50 offset 0
  ) t
;

-- 영역별 Top 랭킹 이전값 저장
DROP TEMPORARY TABLE IF EXISTS tmp_previous_rank_area;
CREATE TEMPORARY TABLE tmp_previous_rank_area AS
SELECT r1.area_code, r1.product_id, r1.current_rank
  FROM tb_product_rank_area r1
 INNER JOIN (
    SELECT area_code, product_id, MAX(created_date) AS max_created_date
      FROM tb_product_rank_area
     GROUP BY area_code, product_id
 ) r2
    ON r1.area_code = r2.area_code
   AND r1.product_id = r2.product_id
   AND r1.created_date = r2.max_created_date
;

DELETE FROM tb_product_rank_area;

-- 무료연재 Top 랭킹 재계산
insert into tb_product_rank_area (area_code, product_id, current_rank, previous_rank, created_id, updated_id)
select 'freeSerialTop'
     , t.product_id
     , t.current_rank
     , t.previous_rank
     , 0 as created_id
     , 0 as updated_id
  from (
    select z.product_id
         , ROW_NUMBER() OVER (order by round((
             90 * CASE WHEN z.max_recent_24h_count_hit > 0 THEN LN(1 + z.recent_24h_count_hit) / LN(1 + z.max_recent_24h_count_hit) ELSE 0 END
             + 10 * CASE WHEN z.max_count_hit > 0 THEN LN(1 + z.count_hit) / LN(1 + z.max_count_hit) ELSE 0 END
           ) / 100, 4) desc, z.recent_24h_count_hit desc, z.count_hit desc, z.product_id desc) as current_rank
         , w.current_rank as previous_rank
      from (
        select filtered.product_id
             , filtered.count_hit
             , filtered.recent_24h_count_hit
             , filtered.open_episode_count
             , filtered.latest_open_at
             , filtered.next_reserved_at
             , MAX(filtered.count_hit) OVER() AS max_count_hit
             , MAX(filtered.recent_24h_count_hit) OVER() AS max_recent_24h_count_hit
          from tmp_product_rank_basis filtered
         inner join tb_product y on filtered.product_id = y.product_id
           and y.price_type = 'free'
           and y.status_code = 'ongoing'
           and y.open_yn = 'Y'
         where filtered.open_episode_count >= 3
           and (
                filtered.latest_open_at >= DATE_SUB(@rank_freshness_basis_at, INTERVAL 30 DAY)
                or filtered.next_reserved_at IS NOT NULL
           )
      ) z
      left join tmp_previous_rank_area w on z.product_id = w.product_id
       and w.area_code = 'freeSerialTop'
     ORDER BY current_rank ASC, z.recent_24h_count_hit DESC, z.count_hit DESC
     limit 50 offset 0
  ) t
;

-- 유료연재 Top 랭킹 재계산
insert into tb_product_rank_area (area_code, product_id, current_rank, previous_rank, created_id, updated_id)
select 'paidSerialTop'
     , t.product_id
     , t.current_rank
     , t.previous_rank
     , 0 as created_id
     , 0 as updated_id
  from (
    select z.product_id
         , ROW_NUMBER() OVER (order by round((
             90 * CASE WHEN z.max_recent_24h_count_hit > 0 THEN LN(1 + z.recent_24h_count_hit) / LN(1 + z.max_recent_24h_count_hit) ELSE 0 END
             + 10 * CASE WHEN z.max_count_hit > 0 THEN LN(1 + z.count_hit) / LN(1 + z.max_count_hit) ELSE 0 END
           ) / 100, 4) desc, z.recent_24h_count_hit desc, z.count_hit desc, z.product_id desc) as current_rank
         , w.current_rank as previous_rank
      from (
        select filtered.product_id
             , filtered.count_hit
             , filtered.recent_24h_count_hit
             , filtered.open_episode_count
             , filtered.latest_open_at
             , filtered.next_reserved_at
             , MAX(filtered.count_hit) OVER() AS max_count_hit
             , MAX(filtered.recent_24h_count_hit) OVER() AS max_recent_24h_count_hit
          from tmp_product_rank_basis filtered
         inner join tb_product y on filtered.product_id = y.product_id
           and y.price_type = 'paid'
           and y.publish_regular_yn = 'Y'
           and y.status_code = 'ongoing'
           and y.open_yn = 'Y'
         where filtered.open_episode_count >= 3
           and (
                filtered.latest_open_at >= DATE_SUB(@rank_freshness_basis_at, INTERVAL 30 DAY)
                or filtered.next_reserved_at IS NOT NULL
           )
      ) z
      left join tmp_previous_rank_area w on z.product_id = w.product_id
       and w.area_code = 'paidSerialTop'
     ORDER BY current_rank ASC, z.recent_24h_count_hit DESC, z.count_hit DESC
     limit 50 offset 0
  ) t
;

-- 연재완결 Top 랭킹 재계산
insert into tb_product_rank_area (area_code, product_id, current_rank, previous_rank, created_id, updated_id)
select 'paidEndTop'
     , t.product_id
     , t.current_rank
     , t.previous_rank
     , 0 as created_id
     , 0 as updated_id
  from (
    select z.product_id
         , ROW_NUMBER() OVER (order by round((
             90 * CASE WHEN z.max_recent_24h_count_hit > 0 THEN LN(1 + z.recent_24h_count_hit) / LN(1 + z.max_recent_24h_count_hit) ELSE 0 END
             + 10 * CASE WHEN z.max_count_hit > 0 THEN LN(1 + z.count_hit) / LN(1 + z.max_count_hit) ELSE 0 END
           ) / 100, 4) desc, z.recent_24h_count_hit desc, z.count_hit desc, z.product_id desc) as current_rank
         , w.current_rank as previous_rank
      from (
        select filtered.product_id
             , filtered.count_hit
             , filtered.recent_24h_count_hit
             , MAX(filtered.count_hit) OVER() AS max_count_hit
             , MAX(filtered.recent_24h_count_hit) OVER() AS max_recent_24h_count_hit
          from tmp_product_rank_basis filtered
         inner join tb_product y on filtered.product_id = y.product_id
           and y.price_type = 'paid'
           and y.publish_regular_yn = 'Y'
           and y.status_code = 'end'
           and y.open_yn = 'Y'
      ) z
      left join tmp_previous_rank_area w on z.product_id = w.product_id
       and w.area_code = 'paidEndTop'
     ORDER BY current_rank ASC, z.recent_24h_count_hit DESC, z.count_hit DESC
     limit 50 offset 0
  ) t
;

-- 단행본 Top 랭킹 재계산
insert into tb_product_rank_area (area_code, product_id, current_rank, previous_rank, created_id, updated_id)
select 'paidStandaloneTop'
     , t.product_id
     , t.current_rank
     , t.previous_rank
     , 0 as created_id
     , 0 as updated_id
  from (
    select z.product_id
         , ROW_NUMBER() OVER (order by round((
             90 * CASE WHEN z.max_recent_24h_count_hit > 0 THEN LN(1 + z.recent_24h_count_hit) / LN(1 + z.max_recent_24h_count_hit) ELSE 0 END
             + 10 * CASE WHEN z.max_count_hit > 0 THEN LN(1 + z.count_hit) / LN(1 + z.max_count_hit) ELSE 0 END
           ) / 100, 4) desc, z.recent_24h_count_hit desc, z.count_hit desc, z.product_id desc) as current_rank
         , w.current_rank as previous_rank
      from (
        select filtered.product_id
             , filtered.count_hit
             , filtered.recent_24h_count_hit
             , MAX(filtered.count_hit) OVER() AS max_count_hit
             , MAX(filtered.recent_24h_count_hit) OVER() AS max_recent_24h_count_hit
          from tmp_product_rank_basis filtered
         inner join tb_product y on filtered.product_id = y.product_id
           and y.price_type = 'paid'
           and y.publish_regular_yn = 'N'
           and y.open_yn = 'Y'
      ) z
      left join tmp_previous_rank_area w on z.product_id = w.product_id
       and w.area_code = 'paidStandaloneTop'
     ORDER BY current_rank ASC, z.recent_24h_count_hit DESC, z.count_hit DESC
     limit 50 offset 0
  ) t
;

-- 메인 유료 Top 랭킹 재계산 (유료연재 + 연재완결)
insert into tb_product_rank_area (area_code, product_id, current_rank, previous_rank, created_id, updated_id)
select 'paidMainTop'
     , t.product_id
     , t.current_rank
     , t.previous_rank
     , 0 as created_id
     , 0 as updated_id
  from (
    select z.product_id
         , ROW_NUMBER() OVER (order by round((
             90 * CASE WHEN z.max_recent_24h_count_hit > 0 THEN LN(1 + z.recent_24h_count_hit) / LN(1 + z.max_recent_24h_count_hit) ELSE 0 END
             + 10 * CASE WHEN z.max_count_hit > 0 THEN LN(1 + z.count_hit) / LN(1 + z.max_count_hit) ELSE 0 END
           ) / 100, 4) desc, z.recent_24h_count_hit desc, z.count_hit desc, z.product_id desc) as current_rank
         , w.current_rank as previous_rank
      from (
        select filtered.product_id
             , filtered.count_hit
             , filtered.recent_24h_count_hit
             , filtered.open_episode_count
             , filtered.latest_open_at
             , filtered.next_reserved_at
             , MAX(filtered.count_hit) OVER() AS max_count_hit
             , MAX(filtered.recent_24h_count_hit) OVER() AS max_recent_24h_count_hit
          from tmp_product_rank_basis filtered
         inner join tb_product y on filtered.product_id = y.product_id
           and y.price_type = 'paid'
           and y.publish_regular_yn = 'Y'
           and y.open_yn = 'Y'
         where y.status_code = 'end'
            or (
                 y.status_code = 'ongoing'
                 and filtered.open_episode_count >= 3
                 and (
                      filtered.latest_open_at >= DATE_SUB(@rank_freshness_basis_at, INTERVAL 30 DAY)
                      or filtered.next_reserved_at IS NOT NULL
                 )
            )
      ) z
      left join tmp_previous_rank_area w on z.product_id = w.product_id
       and w.area_code = 'paidMainTop'
     ORDER BY current_rank ASC, z.recent_24h_count_hit DESC, z.count_hit DESC
     limit 50 offset 0
  ) t
;

-- 임시 테이블 삭제
DROP TEMPORARY TABLE IF EXISTS tmp_previous_rank;
DROP TEMPORARY TABLE IF EXISTS tmp_previous_rank_area;
DROP TEMPORARY TABLE IF EXISTS tmp_product_rank_basis;

commit;

INSERT INTO tb_product_hit_snapshot_hourly (
    basis_at, product_id, count_hit, created_id, updated_id
)
SELECT @recent_24h_basis_at
     , p.product_id
     , GREATEST(COALESCE(p.count_hit, 0), 0)
     , 0
     , 0
  FROM tb_product p
ON DUPLICATE KEY UPDATE
    count_hit = VALUES(count_hit),
    updated_id = 0,
    updated_date = CURRENT_TIMESTAMP;

INSERT INTO tb_product_episode_hit_snapshot_hourly (
    basis_at, product_id, episode_id, episode_no, count_hit, created_id, updated_id
)
SELECT @recent_24h_basis_at
     , e.product_id
     , e.episode_id
     , e.episode_no
     , GREATEST(COALESCE(e.count_hit, 0), 0)
     , 0
     , 0
  FROM tb_product_episode e
 INNER JOIN tb_product p
    ON p.product_id = e.product_id
 WHERE e.use_yn = 'Y'
ON DUPLICATE KEY UPDATE
    episode_no = VALUES(episode_no),
    count_hit = VALUES(count_hit),
    updated_id = 0,
    updated_date = CURRENT_TIMESTAMP;

DELETE FROM tb_product_episode_hit_snapshot_hourly
 WHERE basis_at < DATE_SUB(@recent_24h_basis_at, INTERVAL 7 DAY);

DELETE FROM tb_product_hit_snapshot_hourly
 WHERE basis_at < DATE_SUB(@recent_24h_basis_at, INTERVAL 7 DAY);

update tb_cms_batch_job_process a
   set a.completed_yn = 'Y'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'service_reset_hourly_batch.sh'
;
