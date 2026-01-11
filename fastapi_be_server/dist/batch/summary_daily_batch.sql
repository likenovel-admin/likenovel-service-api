
update tb_cms_batch_job_process a
   set a.completed_yn = 'N'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'summary_daily_batch.sh'
;

start transaction;

-- 일별 집계(매출)
truncate tb_batch_daily_sales_summary
;

insert into tb_batch_daily_sales_summary (item_type, item_name, item_price, quantity, device_type, user_id, order_date, product_id, episode_id, pay_type, created_id, updated_id)
select (case when e.ticket_id is not null then e.ticket_type
             when c.item_info_id is not null then 'normal'
             else 'sponsorship' -- TODO: 후원(sponsorship), 광고(ad), 할인(discount) 테이블 신규 설계 후, 조건문 추가 필
       end) as item_type
     , a.item_name
     , a.item_price
     , a.quantity
     , b.device_type
     , b.user_id
     , b.order_date
     , c.product_id
     , c.episode_id
     , d.pay_type
     , 0 as created_id
     , 0 as updated_id
  from tb_product_order_item a
 inner join tb_product_order b on a.order_id = b.order_id
  left join tb_product_order_item_info c on a.item_id = c.item_info_id
 inner join tb_product_payment d on a.order_id = d.order_id -- 현재 1:1 관계
  left join tb_ticket_item e on a.item_id = e.ticket_id
   and e.use_yn = 'Y'
 where a.cancel_yn = 'N' -- 일부 환불 처리가 되지 않은 건
   and a.created_date >= date_sub(curdate(), interval 1 day)
   and a.created_date < curdate()
;

-- 일별 집계(환불)
truncate tb_batch_daily_refund_summary
;

insert into tb_batch_daily_refund_summary (item_type, item_name, refund_type, refund_price, device_type, user_id, order_date, product_id, episode_id, pay_type, created_id, updated_id)
select (case when f.ticket_id is not null then f.ticket_type
             when c.item_info_id is not null then 'normal'
             else 'sponsorship' -- TODO: 후원(sponsorship), 광고(ad), 할인(discount) 테이블 신규 설계 후, 조건문 추가 필
       end) as item_type
     , a.item_name
     , e.refund_type
     , e.refund_price
     , b.device_type
     , e.user_id
     , b.order_date
     , c.product_id
     , c.episode_id
     , d.pay_type
     , 0 as created_id
     , 0 as updated_id
  from tb_product_order_item a
 inner join tb_product_order b on a.order_id = b.order_id
  left join tb_product_order_item_info c on a.item_id = c.item_info_id
 inner join tb_product_payment d on a.order_id = d.order_id
 inner join tb_product_refund e on a.item_id = e.order_item_id
  left join tb_ticket_item f on a.item_id = f.ticket_id
   and f.use_yn = 'Y'
 where a.cancel_yn = 'Y'
   and a.created_date >= date_sub(curdate(), interval 1 day)
   and a.created_date < curdate()
;

-- 전체연독률 = 15화 이상 회차 작품만 계산 (뒤 4번째 조회수/앞 4번째 조회수*100)
update tb_product_trend_index a
  join (
    select z.product_id
         , coalesce(round((left(cast(z.count_hit as char), 4) / right(cast(z.count_hit as char), 4)), 1), 0) * 100 as reading_rate
      from tb_product z
     where exists (select y.product_id from tb_product_episode y
                    where y.product_id = z.product_id
                    group by z.product_id
                   having count(1) >= 15)
  ) as t on a.product_id = t.product_id
   set a.reading_rate = t.reading_rate
 where 1=1
;

-- 주평균 연재횟수
update tb_product_trend_index a
  left join (
    select t.product_id
         , t.count_write / ceil((datediff(curdate(), t.created_date) + 1) / 7) as writing_count_per_week
      from (
        select z.product_id
               , (select count(1) from tb_product_episode x
                   where z.product_id = x.product_id
                     and x.use_yn = 'Y') as count_write
               , y.created_date
            from tb_product z
           inner join tb_product_episode y on z.product_id = y.product_id
             and y.use_yn = 'Y'
             and y.episode_no = 1
      ) t
  ) as t on a.product_id = t.product_id
   set a.writing_count_per_week = coalesce(t.writing_count_per_week, 0)
 where 1=1
;

-- 작품 일별 집계(조회수)
-- 전날 누적 조회수(privious) 및 현재 누적 조회수(current)
insert into tb_batch_daily_product_count_summary (product_id, current_count_hit, privious_count_hit, current_count_recommend, privious_count_recommend, current_count_bookmark, privious_count_bookmark, current_count_unbookmark, privious_count_unbookmark, current_count_cp_hit, privious_count_cp_hit, current_reading_rate, privious_reading_rate, current_count_interest, privious_count_interest, current_count_interest_sustain, privious_count_interest_sustain, current_count_interest_loss, privious_count_interest_loss, created_id, updated_id)
with tmp_interest_summary as (
    select y.product_id
         , count(y.free_keep_interest) as count_free_interest
	         -- 관심 수 = 해당 작품 관심 유지 유저수 + 관심 탈락 유저수 (일반)
         , sum(case when y.free_keep_interest = 'sustain' then 1 else 0 end) as count_free_interest_sustain
         , sum(case when y.free_keep_interest = 'loss' then 1 else 0 end) as count_free_interest_loss
      from (
        select z.user_id
             , z.product_id
             , case when floor(timestampdiff(second, curdate(), max(z.updated_date)) / 3600) <= 72
                    then 'loss'
                    else 'sustain'
               end as free_keep_interest   -- 특정 기간 내에 재방문 여부(기간은 자유 72시간)
          from tb_user_product_usage z
         where z.use_yn = 'Y'
           and z.updated_date < curdate()
         group by z.user_id, z.product_id
      ) y
    group by y.product_id
)
select a.product_id
     , coalesce(a.count_hit, 0) as current_count_hit
     , coalesce(d.current_count_hit, 0) as privious_count_hit
     , coalesce(a.count_recommend, 0) as current_count_recommend
     , coalesce(d.current_count_recommend, 0) as privious_count_recommend
     , coalesce(a.count_bookmark, 0) as current_count_bookmark
     , coalesce(d.current_count_bookmark, 0) as privious_count_bookmark
     , coalesce(a.count_unbookmark, 0) as current_count_unbookmark
     , coalesce(d.current_count_unbookmark, 0) as privious_count_unbookmark
     , coalesce(a.count_cp_hit, 0) as current_count_cp_hit
     , coalesce(d.current_count_cp_hit, 0) as privious_count_cp_hit
     , coalesce(b.reading_rate, 0) as current_reading_rate
     , coalesce(d.current_reading_rate, 0) as privious_reading_rate
     , coalesce(case when a.price_type = 'free' then c.count_free_interest
                     else 0
                end, 0) as current_count_interest
     , coalesce(d.current_count_interest, 0) as privious_count_interest
     , coalesce(case when a.price_type = 'free' then c.count_free_interest_sustain
                     else 0
                end, 0) as current_count_interest_sustain
     , coalesce(d.current_count_interest_sustain, 0) as privious_count_interest_sustain
     , coalesce(case when a.price_type = 'free' then c.count_free_interest_loss
                     else 0
                end, 0) as current_count_interest_loss
     , coalesce(d.current_count_interest_loss, 0) as privious_count_interest_loss
     , 0 as created_id
     , 0 as updated_id
  from tb_product a
 inner join tb_product_trend_index b on a.product_id = b.product_id
  left join tmp_interest_summary c on a.product_id = c.product_id
  left join tb_batch_daily_product_count_summary d on a.product_id = d.product_id
   and d.created_date >= date_sub(curdate(), interval 1 day)
   and d.created_date < curdate()
;

-- 회차 일별 집계(조회수)
-- 전날 누적 조회수(privious) 및 현재 누적 조회수(current)
-- 24시간 이내 조회수는 데이터 갱신 없이 배치 도는 시점(정각) 기준으로 산정 요청
insert into tb_batch_daily_product_episode_count_summary (product_id, episode_id, episode_no, current_count_hit, privious_count_hit, current_count_recommend, privious_count_recommend, current_count_comment, privious_count_comment, current_count_evaluation, privious_count_evaluation, current_count_hit_in_24h, privious_count_hit_in_24h, created_id, updated_id)
with tmp_user_product_usage_24h_summary as (
    select z.product_id
         , z.episode_id
         , count(1) as count_hit_in_24h
      from tb_user_product_usage z
     inner join tb_product_episode y on z.product_id = y.product_id
       and z.episode_id = y.episode_id
       and z.created_date >= (case when y.publish_reserve_date is null then y.created_date
                                   else y.publish_reserve_date end)
       and z.created_date < date_add((case when y.publish_reserve_date is null then y.created_date
                                           else y.publish_reserve_date end), interval 1 day)
       and y.open_yn = 'Y'
     where z.use_yn = 'Y'
       and z.updated_date < curdate()
     group by z.product_id, z.episode_id
)
select a.product_id
     , a.episode_id
     , a.episode_no
     , coalesce(a.count_hit, 0) as current_count_hit
     , coalesce(b.current_count_hit, 0) as privious_count_hit
     , coalesce(a.count_recommend, 0) as current_count_recommend
     , coalesce(b.current_count_recommend, 0) as privious_count_recommend
     , coalesce(a.count_comment, 0) as current_count_comment
     , coalesce(b.current_count_comment, 0) as privious_count_comment
     , coalesce(a.count_evaluation, 0) as current_count_evaluation
     , coalesce(b.current_count_evaluation, 0) as privious_count_evaluation
     , coalesce(c.count_hit_in_24h, 0) as current_count_hit_in_24h
     , coalesce(b.current_count_hit_in_24h, 0) as privious_count_hit_in_24h
     , 0 as created_id
     , 0 as updated_id
  from tb_product_episode a
  left join tb_batch_daily_product_episode_count_summary b on a.product_id = b.product_id
   and a.episode_id = b.episode_id
   and b.created_date >= date_sub(curdate(), interval 1 day)
   and b.created_date < curdate()
  left join tmp_user_product_usage_24h_summary c on a.product_id = c.product_id
   and a.episode_id = c.episode_id
 where a.use_yn = 'Y'
;

-- 기존 작품 일별 집계(조회수) 데이터 삭제
delete from tb_batch_daily_product_count_summary
      where created_date < curdate()
;

-- 기존 회차 일별 집계(조회수) 데이터 삭제
delete from tb_batch_daily_product_episode_count_summary
      where created_date < curdate()
;

-- 작품 집계(정보)
truncate tb_batch_daily_product_info_summary
;

insert into tb_batch_daily_product_info_summary (product_id, title, author_nickname, count_episode, count_evaluation, count_read_user, contract_type, cp_company_name, publish_date, paid_open_date, isbn, uci, status_code, ratings_code, paid_yn, primary_genre, sub_genre, single_regular_price, series_regular_price, sale_price, primary_reader_group1, primary_reader_group2, created_id, updated_id)
with tmp_product_episode_count_summary as (
    select product_id
         , count(1) as count_episode
         , sum(current_count_evaluation) as count_evaluation
      from tb_batch_daily_product_episode_count_summary
     group by product_id
),
tmp_user_product_usage_count_summary as (
    select product_id
         , count(1) as count_read_user
      from tb_user_product_usage
     where use_yn = 'Y'
       and updated_date < curdate()
     group by product_id
),
tmp_contract_offer_list_summary as (
    select product_id
         , cp_company_name
      from (
          select z.product_id
               , y.company_name as cp_company_name
               , ROW_NUMBER() OVER (PARTITION BY z.product_id ORDER BY z.updated_date DESC) as rn
            from tb_product_contract_offer z
           inner join tb_user_profile_apply y on z.offer_user_id = y.user_id -- TODO: cp 계약, cp 부여 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료. 신규유저 아이디 컬럼 추가 혹은 회사명 컬럼 추가 필)
             and y.apply_type = 'cp'
             and y.approval_date is not null
           where z.use_yn = 'Y'
             and z.author_accept_yn = 'Y'
      ) ranked
     where rn = 1
)
select a.product_id
     , a.title
     , a.author_name as author_nickname
     , coalesce(b.count_episode, 0) as count_episode -- 회차수
     , coalesce(b.count_evaluation, 0) as count_evaluation -- 평가수
     , coalesce(c.count_read_user, 0) as count_read_user -- 독자수
     , case when f.cp_company_name is null then null
            when f.cp_company_name = '라이크노벨' then '일반'
            else 'cp'
       end as contract_type -- 계약유형
     , f.cp_company_name -- 담당CP
     , a.created_date -- 작품등록일
     , a.paid_open_date -- 유료시작일(판매시작일)
     , a.isbn -- isbn
     , a.uci -- uci
     , a.status_code -- 연재상태
     , a.ratings_code -- 연령등급
     , case when a.price_type = 'paid' then 'Y'
            else 'N'
       end as paid_yn -- 유료여부
     , (select z.keyword_name from tb_standard_keyword z
         where z.use_yn = 'Y'
           and z.major_genre_yn = 'Y'
           and a.primary_genre_id = z.keyword_id) as primary_genre -- 1차 장르
     , (select z.keyword_name from tb_standard_keyword z
         where z.use_yn = 'Y'
           and z.major_genre_yn = 'Y'
           and a.sub_genre_id = z.keyword_id) as sub_genre -- 2차 장르
     , a.single_regular_price -- 단행본
     , a.series_regular_price -- 연재
     , a.sale_price -- 판매가
     , case when e.primary_reader_group is null then null
            else replace(json_extract(e.primary_reader_group, '$."1"'), '"', '')
       end as primary_reader_group1 -- 주요 독자층1
     , case when e.primary_reader_group is null then null
            else replace(json_extract(e.primary_reader_group, '$."2"'), '"', '')
       end as primary_reader_group2 -- 주요 독자층2
     , 0 as created_id
     , 0 as updated_id
  from tb_product a
  left join tmp_product_episode_count_summary b on a.product_id = b.product_id
  left join tmp_user_product_usage_count_summary c on a.product_id = c.product_id
 inner join tb_product_trend_index e on a.product_id = e.product_id
  left join tmp_contract_offer_list_summary f on a.product_id = f.product_id
;

-- 회차 집계(정보)
truncate tb_batch_daily_product_episode_info_summary
;

insert into tb_batch_daily_product_episode_info_summary (product_id, episode_id, episode_no, paid_yn, current_count_hit_in_24h, created_id, updated_id)
select a.product_id
     , a.episode_id
     , a.episode_no
     , case when a.price_type = 'paid' then 'Y'
            else 'N'
       end as paid_yn -- 유료여부
     , b.current_count_hit_in_24h -- 24시간이내 조회수
     , 0 as created_id
     , 0 as updated_id
  from tb_product_episode a
 inner join tb_batch_daily_product_episode_count_summary b on a.product_id = b.product_id
   and a.episode_id = b.episode_id
 where a.use_yn = 'Y'
;

-- 직접 프로모션 자동 시작 (start_date가 오늘이고 status가 pending인 경우)
update tb_direct_promotion
   set status = 'ing'
     , updated_id = 0
     , updated_date = NOW()
 where date(start_date) = curdate()
   and status = 'pending'
;

-- 신청 프로모션 자동 종료 (end_date가 지났고 status가 ing인 경우)
update tb_applied_promotion
   set status = 'end'
     , updated_id = 0
     , updated_date = NOW()
 where end_date is not null
   and date(end_date) < curdate()
   and status = 'ing'
;

-- 기다리면 무료 (waiting-for-free) 프로모션 종료시 해당 대여권 삭제
delete from tb_user_productbook
 where acquisition_type = 'applied_promotion'
   and acquisition_id in (
       select id from tb_applied_promotion
        where type = 'waiting-for-free'
          and status = 'end'
   )
   and use_yn = 'N'  -- 사용하지 않은 대여권만 삭제
;

update tb_cms_batch_job_process a
   set a.completed_yn = 'Y'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'summary_daily_batch.sh'
;

commit;

