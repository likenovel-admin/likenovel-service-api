
update tb_cms_batch_job_process a
   set a.completed_yn = 'N'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'service_reset_hourly_batch.sh'
;

start transaction;

-- 예약 공개 처리: 예약일이 현재 시간을 지났고 비공개 상태인 회차를 공개로 변경
-- open_changed_date가 publish_reserve_date보다 이후인 경우(작가가 수동으로 변경한 경우)는 제외
update tb_product_episode
   set open_yn = 'Y'
     , open_changed_date = NOW()
     , updated_id = 0
     , updated_date = NOW()
 where publish_reserve_date IS NOT NULL
   and publish_reserve_date <= NOW()
   and (open_changed_date IS NULL OR open_changed_date <= publish_reserve_date)
   and open_yn = 'N'
   and use_yn = 'Y'
;

-- 예약 공개된 에피소드의 작품도 공개 전환 (작품이 아직 비공개인 경우)
update tb_product p
 inner join (
    select distinct e.product_id
      from tb_product_episode e
     where e.open_yn = 'Y'
       and e.use_yn = 'Y'
 ) pe on pe.product_id = p.product_id
   set p.open_yn = 'Y'
     , p.last_episode_date = NOW()
     , p.updated_id = 0
     , p.updated_date = NOW()
 where p.open_yn = 'N'
   and p.blind_yn = 'N'
;

-- 예약 공개로 회차가 공개된 작품의 last_episode_date 갱신 (이미 공개된 작품 포함)
update tb_product p
 inner join (
    select distinct e.product_id
      from tb_product_episode e
     where e.open_changed_date = NOW()
       and e.open_yn = 'Y'
       and e.use_yn = 'Y'
 ) pe on pe.product_id = p.product_id
   set p.last_episode_date = NOW()
     , p.updated_date = NOW()
 where p.open_yn = 'Y'
;

-- 예약 유료 전환 처리: paid_open_date가 현재 시간을 지났으면
-- paid_episode_no 이상의 회차를 유료로 전환
update tb_product_episode e
 inner join tb_product p on e.product_id = p.product_id
   set e.price_type = 'paid'
     , e.updated_id = 0
     , e.updated_date = NOW()
 where p.paid_open_date IS NOT NULL
   and p.paid_open_date <= NOW()
   and p.paid_episode_no IS NOT NULL
   and e.episode_no >= p.paid_episode_no
   and (e.price_type = 'free' or e.price_type is null)
   and e.use_yn = 'Y'
;

update tb_product p
   set p.price_type = 'paid'
     , p.updated_id = 0
     , p.updated_date = NOW()
 where p.price_type = 'free'
   and p.paid_open_date IS NOT NULL
   and p.paid_open_date <= NOW()
   and p.paid_episode_no IS NOT NULL
   and exists (
       select 1
         from tb_product_episode e
        where e.product_id = p.product_id
          and e.episode_no >= p.paid_episode_no
          and e.price_type = 'paid'
          and e.open_yn = 'Y'
          and e.use_yn = 'Y'
   )
;

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

-- 임시 테이블 삭제
DROP TEMPORARY TABLE IF EXISTS tmp_previous_rank;

update tb_cms_batch_job_process a
   set a.completed_yn = 'Y'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'service_reset_hourly_batch.sh'
;

commit;
