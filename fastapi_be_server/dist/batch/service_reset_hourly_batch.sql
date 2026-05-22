
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

-- 기존 랭킹 데이터 전체 삭제 (중복 방지)
DELETE FROM tb_product_rank;

-- 무료 Top 랭킹 재계산
-- 5회차 이상 작품만
-- 평가 없어도 조회수 기반으로 랭킹 진입, 평가가 있으면 가산
-- 총점 = W₁ * (해당 작품 조회수 / 조건에 맞는 작품 목록 중 가장 큰 조회수) + W₂ * 평가점수
-- 소수점 둘째자리까지 반올림, 총점이 같을 경우 조회수 기준 내림차순
insert into tb_product_rank (product_id, current_rank, privious_rank, created_id, updated_id)
select t.product_id
     , t.current_rank
     , t.privious_rank
     , 0 as created_id
     , 0 as updated_id
  from (
    select z.product_id
         , rank() over (order by round((COALESCE(x.weight_count_hit, 50) * (z.count_hit / z.max_count_hit) + COALESCE(x.weight_evaluation_score, 0) * COALESCE(x.evaluation_score, 0)) / 100, 2) desc, z.count_hit desc) as current_rank
         , w.current_rank as privious_rank
      from (
        select a.product_id
             , a.count_hit
             , max(a.count_hit) over() as max_count_hit
          from tb_product a
         where exists (select 1 from tb_product_episode b
                        where a.product_id = b.product_id
                          and b.episode_no >= 5
                          -- and b.open_yn = 'Y'
                          and b.use_yn = 'Y')
      ) z
     inner join tb_product y on z.product_id = y.product_id
       and y.price_type = 'free'
      left join tb_cms_product_evaluation x on z.product_id = x.product_id
       and x.evaluation_yn = 'Y'
      left join tmp_previous_rank w on z.product_id = w.product_id
     limit 50 offset 0
  ) t
;

-- 유료 Top 랭킹 재계산
-- 5회차 이상 작품만
-- 평가 없어도 조회수 기반으로 랭킹 진입, 평가가 있으면 가산
-- 총점 = W₁ * (해당 작품 조회수 / 조건에 맞는 작품 목록 중 가장 큰 조회수) + W₂ * 평가점수
-- 소수점 둘째자리까지 반올림, 총점이 같을 경우 조회수 기준 내림차순
insert into tb_product_rank (product_id, current_rank, privious_rank, created_id, updated_id)
select t.product_id
     , t.current_rank
     , t.privious_rank
     , 0 as created_id
     , 0 as updated_id
  from (
    select z.product_id
         , rank() over (order by round((COALESCE(x.weight_count_hit, 50) * (z.count_hit / z.max_count_hit) + COALESCE(x.weight_evaluation_score, 0) * COALESCE(x.evaluation_score, 0)) / 100, 2) desc, z.count_hit desc) as current_rank
         , w.current_rank as privious_rank
      from (
        select a.product_id
             , a.count_hit
             , max(a.count_hit) over() as max_count_hit
          from tb_product a
         where exists (select 1 from tb_product_episode b
                        where a.product_id = b.product_id
                          and b.episode_no >= 5
                          -- and b.open_yn = 'Y'
                          and b.use_yn = 'Y')
      ) z
     inner join tb_product y on z.product_id = y.product_id
       and y.price_type = 'paid'
      left join tb_cms_product_evaluation x on z.product_id = x.product_id
       and x.evaluation_yn = 'Y'
      left join tmp_previous_rank w on z.product_id = w.product_id
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
         , rank() over (order by round((COALESCE(x.weight_count_hit, 50) * (z.count_hit / z.max_count_hit) + COALESCE(x.weight_evaluation_score, 0) * COALESCE(x.evaluation_score, 0)) / 100, 2) desc, z.count_hit desc) as current_rank
         , w.current_rank as previous_rank
      from (
        select a.product_id
             , a.count_hit
             , max(a.count_hit) over() as max_count_hit
          from tb_product a
         where exists (select 1 from tb_product_episode b
                        where a.product_id = b.product_id
                          and b.episode_no >= 5
                          and b.use_yn = 'Y')
      ) z
     inner join tb_product y on z.product_id = y.product_id
       and y.price_type = 'free'
       and y.status_code in ('ongoing', 'rest')
       and y.open_yn = 'Y'
      left join tb_cms_product_evaluation x on z.product_id = x.product_id
       and x.evaluation_yn = 'Y'
      left join tmp_previous_rank_area w on z.product_id = w.product_id
       and w.area_code = 'freeSerialTop'
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
         , rank() over (order by round((COALESCE(x.weight_count_hit, 50) * (z.count_hit / z.max_count_hit) + COALESCE(x.weight_evaluation_score, 0) * COALESCE(x.evaluation_score, 0)) / 100, 2) desc, z.count_hit desc) as current_rank
         , w.current_rank as previous_rank
      from (
        select a.product_id
             , a.count_hit
             , max(a.count_hit) over() as max_count_hit
          from tb_product a
         where exists (select 1 from tb_product_episode b
                        where a.product_id = b.product_id
                          and b.episode_no >= 5
                          and b.use_yn = 'Y')
      ) z
     inner join tb_product y on z.product_id = y.product_id
       and y.price_type = 'paid'
       and y.publish_regular_yn = 'Y'
       and y.status_code in ('ongoing', 'rest')
       and y.open_yn = 'Y'
      left join tb_cms_product_evaluation x on z.product_id = x.product_id
       and x.evaluation_yn = 'Y'
      left join tmp_previous_rank_area w on z.product_id = w.product_id
       and w.area_code = 'paidSerialTop'
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
         , rank() over (order by round((COALESCE(x.weight_count_hit, 50) * (z.count_hit / z.max_count_hit) + COALESCE(x.weight_evaluation_score, 0) * COALESCE(x.evaluation_score, 0)) / 100, 2) desc, z.count_hit desc) as current_rank
         , w.current_rank as previous_rank
      from (
        select a.product_id
             , a.count_hit
             , max(a.count_hit) over() as max_count_hit
          from tb_product a
         where exists (select 1 from tb_product_episode b
                        where a.product_id = b.product_id
                          and b.episode_no >= 5
                          and b.use_yn = 'Y')
      ) z
     inner join tb_product y on z.product_id = y.product_id
       and y.price_type = 'paid'
       and y.publish_regular_yn = 'Y'
       and y.status_code = 'end'
       and y.open_yn = 'Y'
      left join tb_cms_product_evaluation x on z.product_id = x.product_id
       and x.evaluation_yn = 'Y'
      left join tmp_previous_rank_area w on z.product_id = w.product_id
       and w.area_code = 'paidEndTop'
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
         , rank() over (order by round((COALESCE(x.weight_count_hit, 50) * (z.count_hit / z.max_count_hit) + COALESCE(x.weight_evaluation_score, 0) * COALESCE(x.evaluation_score, 0)) / 100, 2) desc, z.count_hit desc) as current_rank
         , w.current_rank as previous_rank
      from (
        select a.product_id
             , a.count_hit
             , max(a.count_hit) over() as max_count_hit
          from tb_product a
         where exists (select 1 from tb_product_episode b
                        where a.product_id = b.product_id
                          and b.episode_no >= 5
                          and b.use_yn = 'Y')
      ) z
     inner join tb_product y on z.product_id = y.product_id
       and y.price_type = 'paid'
       and y.publish_regular_yn = 'N'
       and y.open_yn = 'Y'
      left join tb_cms_product_evaluation x on z.product_id = x.product_id
       and x.evaluation_yn = 'Y'
      left join tmp_previous_rank_area w on z.product_id = w.product_id
       and w.area_code = 'paidStandaloneTop'
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
         , rank() over (order by round((COALESCE(x.weight_count_hit, 50) * (z.count_hit / z.max_count_hit) + COALESCE(x.weight_evaluation_score, 0) * COALESCE(x.evaluation_score, 0)) / 100, 2) desc, z.count_hit desc) as current_rank
         , w.current_rank as previous_rank
      from (
        select a.product_id
             , a.count_hit
             , max(a.count_hit) over() as max_count_hit
          from tb_product a
         where exists (select 1 from tb_product_episode b
                        where a.product_id = b.product_id
                          and b.episode_no >= 5
                          and b.use_yn = 'Y')
      ) z
     inner join tb_product y on z.product_id = y.product_id
       and y.price_type = 'paid'
       and y.publish_regular_yn = 'Y'
       and y.status_code in ('ongoing', 'rest', 'end')
       and y.open_yn = 'Y'
      left join tb_cms_product_evaluation x on z.product_id = x.product_id
       and x.evaluation_yn = 'Y'
      left join tmp_previous_rank_area w on z.product_id = w.product_id
       and w.area_code = 'paidMainTop'
     limit 50 offset 0
  ) t
;

-- 임시 테이블 삭제
DROP TEMPORARY TABLE IF EXISTS tmp_previous_rank;
DROP TEMPORARY TABLE IF EXISTS tmp_previous_rank_area;

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
 WHERE p.use_yn = 'Y'
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
   AND p.use_yn = 'Y'
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
