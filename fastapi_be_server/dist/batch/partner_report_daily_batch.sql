
update tb_cms_batch_job_process a
   set a.completed_yn = 'N'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'partner_report_daily_batch.sh'
;

start transaction;

-- 회차별 매출 (당일 데이터 삭제 후 재생성)
delete from tb_ptn_product_episode_sales where DATE(created_date) = CURDATE();

insert into tb_ptn_product_episode_sales (product_id, episode_id, title, author_nickname, episode_no, contract_type, cp_company_name, paid_open_date, count_total_sales, sum_total_sales_price, count_normal_sales, sum_normal_price, count_discount_sales, sum_discount_price, count_paid_ticket_sales, sum_paid_ticket_price, count_comped_ticket_sales, sum_comped_ticket_price, count_free_ticket_sales, sum_free_ticket_price, count_total_refund, sum_total_refund_price, created_id, updated_id)
select m.*
  from (
    with tmp_product_episode_sales_summary as (
        select product_id
             , episode_id
             , count(1) as count_total_sales -- 총 판매
             , sum(item_price * quantity) as sum_total_sales_price
             , sum(case when item_type = 'normal' then 1 else 0 end) as count_normal_sales -- 일반 판매
             , sum(case when item_type = 'normal' then item_price * quantity else 0 end) as sum_normal_price
             , sum(case when item_type = 'discount' then 1 else 0 end) as count_discount_sales -- 할인 판매
             , sum(case when item_type = 'discount' then item_price * quantity else 0 end) as sum_discount_price
             , sum(case when item_type = 'paid' then 1 else 0 end) as count_paid_ticket_sales -- 유상 대여권
             , sum(case when item_type = 'paid' then item_price * quantity else 0 end) as sum_paid_ticket_price
             , sum(case when item_type = 'comped' then 1 else 0 end) as count_comped_ticket_sales -- 무상 대여권
             , sum(case when item_type = 'comped' then item_price * quantity else 0 end) as sum_comped_ticket_price
             , sum(case when item_type = 'free' then 1 else 0 end) as count_free_ticket_sales -- 무료 대여권
             , sum(case when item_type = 'free' then item_price * quantity else 0 end) as sum_free_ticket_price
          from tb_batch_daily_sales_summary
         where item_type in ('normal', 'discount', 'paid', 'comped', 'free')
         group by product_id, episode_id
    ),
    tmp_product_episode_refund_summary as (
        select product_id
             , episode_id
             , count(1) as count_total_refund
             , sum(refund_price) as sum_total_refund_price
          from tb_batch_daily_refund_summary
         where item_type in ('normal', 'discount', 'paid', 'comped', 'free')
         group by product_id, episode_id
    )
    select a.product_id
         , b.episode_id
         , a.title
         , a.author_nickname
         , b.episode_no
         , a.contract_type
         , a.cp_company_name
         , a.paid_open_date
         , c.count_total_sales
         , c.sum_total_sales_price
         , c.count_normal_sales
         , c.sum_normal_price
         , c.count_discount_sales
         , c.sum_discount_price
         , c.count_paid_ticket_sales
         , c.sum_paid_ticket_price
         , c.count_comped_ticket_sales
         , c.sum_comped_ticket_price
         , c.count_free_ticket_sales
         , c.sum_free_ticket_price
         , d.count_total_refund
         , d.sum_total_refund_price
         , 0 as created_id
         , 0 as updated_id
      from tb_batch_daily_product_info_summary a
     inner join tb_batch_daily_product_episode_info_summary b on a.product_id = b.product_id
      left join tmp_product_episode_sales_summary c on a.product_id = c.product_id
       and b.episode_id = c.episode_id
      left join tmp_product_episode_refund_summary d on a.product_id = d.product_id
       and b.episode_id = d.episode_id
    ) m
 where m.count_total_sales is not null
   and m.count_total_refund is not null
;

-- 일별 이용권 상세 (당일 데이터 삭제 후 재생성)
delete from tb_ptn_ticket_usage where DATE(created_date) = CURDATE();

insert into tb_ptn_ticket_usage (product_id, title, author_nickname, episode_no, contract_type, cp_company_name, paid_open_date, isbn, uci, item_name, count_ticket_usage, created_id, updated_id)
with tmp_product_episode_ticket_usage_summary as (
    select product_id
         , episode_id
         , item_name
         , count(1) as count_ticket_usage
      from tb_batch_daily_sales_summary
     where item_type in ('normal', 'paid', 'comped', 'free')
     group by product_id, episode_id, item_name
)
select a.product_id
     , a.title
     , a.author_nickname
     , b.episode_no
     , a.contract_type
     , a.cp_company_name
     , a.paid_open_date
     , a.isbn
     , a.uci
     , c.item_name
     , c.count_ticket_usage
     , 0 as created_id
     , 0 as updated_id
  from tb_batch_daily_product_info_summary a
 inner join tb_batch_daily_product_episode_info_summary b on a.product_id = b.product_id
 inner join tmp_product_episode_ticket_usage_summary c on a.product_id = c.product_id
   and b.episode_id = c.episode_id
;

-- 후원 내역 (당일 데이터 삭제 후 재생성)
delete from tb_ptn_sponsorship_recodes where DATE(created_date) = CURDATE();

insert into tb_ptn_sponsorship_recodes (product_id, title, author_nickname, user_name, donation_price, created_id, updated_id)
with tmp_product_donation_summary as (
    select z.product_id
         , x.user_name
         , (z.item_price * z.quantity) as donation_price
      from tb_batch_daily_sales_summary z
     inner join tb_user x on z.user_id = x.user_id
     where z.item_type = 'sponsorship'
)
select a.product_id
     , a.title
     , a.author_nickname
     , b.user_name
     , b.donation_price
     , 0 as created_id
     , 0 as updated_id
  from tb_batch_daily_product_info_summary a
 inner join tmp_product_donation_summary b on a.product_id = b.product_id
;

-- 기타 수익 내역 (당일 데이터 삭제 후 재생성)
delete from tb_ptn_income_recodes where DATE(created_date) = CURDATE();

insert into tb_ptn_income_recodes (product_id, title, author_nickname, item_type, sum_income_price, created_id, updated_id)
with tmp_product_income_summary as (
    select product_id
         , item_type
         , sum(item_price * quantity) as sum_income_price
      from tb_batch_daily_sales_summary
     where item_type in ('sponsorship', 'ad')
     group by product_id, item_type
)
select a.product_id
     , a.title
     , a.author_nickname
     , b.item_type
     , b.sum_income_price
     , 0 as created_id
     , 0 as updated_id
  from tb_batch_daily_product_info_summary a
 inner join tmp_product_income_summary b on a.product_id = b.product_id
;

-- 작품별 통계 (당일 데이터 삭제 후 재생성)
delete from tb_ptn_product_statistics where DATE(created_date) = CURDATE();

insert into tb_ptn_product_statistics (product_id, title, author_nickname, count_episode, paid_yn, count_hit, count_bookmark, count_unbookmark, count_recommend, count_evaluation, count_total_sales, sum_total_sales_price, sales_price_per_count_hit, count_cp_hit, reading_rate, created_id, updated_id)
with tmp_product_sales_all_summary as (
    -- 누적
    select product_id
         , sum(count_total_sales) as count_total_sales
         , sum(sum_total_sales_price) as sum_total_sales_price
      from tb_ptn_product_episode_sales
     group by product_id
)
select a.product_id
     , a.title
     , a.author_nickname
     , a.count_episode
     , a.paid_yn
     , b.current_count_hit as count_hit
     , b.current_count_bookmark as count_bookmark
     , b.current_count_unbookmark as count_unbookmark
     , b.current_count_recommend as count_recommend
     , a.count_evaluation
     , coalesce(c.count_total_sales, 0) as count_total_sales
     , coalesce(c.sum_total_sales_price, 0) as sum_total_sales_price
     , case when b.current_count_hit = 0 then 0 else round(coalesce(c.sum_total_sales_price, 0) / b.current_count_hit, 1) end as sales_price_per_count_hit
     , b.current_count_cp_hit as count_cp_hit
     , b.current_reading_rate as reading_rate
     , 0 as created_id
     , 0 as updated_id
  from tb_batch_daily_product_info_summary a
 inner join tb_batch_daily_product_count_summary b on a.product_id = b.product_id
  left join tmp_product_sales_all_summary c on a.product_id = c.product_id
;

-- 회차별 통계 (당일 데이터 삭제 후 재생성)
delete from tb_ptn_product_episode_statistics where DATE(created_date) = CURDATE();

insert into tb_ptn_product_episode_statistics (product_id, title, author_nickname, episode_no, paid_yn, count_hit, count_recommend, count_evaluation, count_total_sales, sum_total_sales_price, sales_price_per_count_hit, count_hit_in_24h, created_id, updated_id)
with tmp_product_episode_sales_all_summary as (
    -- 누적
    select product_id
         , episode_id
         , sum(count_total_sales) as count_total_sales
         , sum(sum_total_sales_price) as sum_total_sales_price
      from tb_ptn_product_episode_sales
     group by product_id, episode_id
)
select a.product_id
     , a.title
     , a.author_nickname
     , b.episode_no
     , b.paid_yn
     , c.current_count_hit as count_hit
     , c.current_count_recommend as count_recommend
     , c.current_count_evaluation as count_evaluation
     , coalesce(d.count_total_sales, 0) as count_total_sales
     , coalesce(d.sum_total_sales_price, 0) as sum_total_sales_price
     , case when c.current_count_hit = 0 then 0 else round(coalesce(d.sum_total_sales_price, 0) / c.current_count_hit, 1) end as sales_price_per_count_hit
     , b.current_count_hit_in_24h as count_hit_in_24h
     , 0 as created_id
     , 0 as updated_id
  from tb_batch_daily_product_info_summary a
 inner join tb_batch_daily_product_episode_info_summary b on a.product_id = b.product_id
 inner join tb_batch_daily_product_episode_count_summary c on a.product_id = c.product_id
   and b.episode_id = c.episode_id
  left join tmp_product_episode_sales_all_summary d on a.product_id = d.product_id
   and b.episode_id = d.episode_id
;

-- 발굴통계
truncate tb_ptn_product_discovery_statistics
;

insert into tb_ptn_product_discovery_statistics (product_id, title, author_nickname, count_episode, count_hit, count_hit_per_episode, count_read_user, count_bookmark, count_unbookmark, count_recommend, count_evaluation, count_cp_hit, reading_rate, writing_count_per_week, count_interest_sustain, count_interest_loss, primary_reader_group1, primary_reader_group2, primary_genre, sub_genre, score1, score2, score3, created_id, updated_id)
select a.product_id
     , a.title
     , a.author_nickname
     , a.count_episode
     , b.current_count_hit as count_hit
     , coalesce(round(b.current_count_hit / a.count_episode, 1), 0) as count_hit_per_episode
     , a.count_read_user
     , b.current_count_bookmark as count_bookmark
     , b.current_count_unbookmark as count_unbookmark
     , b.current_count_recommend as count_recommend
     , a.count_evaluation
     , b.current_count_cp_hit as count_cp_hit
     , b.current_reading_rate as reading_rate
     , c.writing_count_per_week
     , b.current_count_interest_sustain as count_interest_sustain
     , b.current_count_interest_loss as count_interest_loss
     , a.primary_reader_group1
     , a.primary_reader_group2
     , a.primary_genre
     , a.sub_genre
     , d.score1
     , d.score2
     , d.score3
     , 0 as created_id
     , 0 as updated_id
  from tb_batch_daily_product_info_summary a
 inner join tb_batch_daily_product_count_summary b on a.product_id = b.product_id
 inner join tb_product_trend_index c on a.product_id = c.product_id
 inner join tb_cms_product_evaluation d on a.product_id = d.product_id
   and d.evaluation_yn = 'Y'
;

-- 작품별 월매출 및 월별 정산용 임시 합산 (당일 데이터 삭제 후 재생성)
delete from tb_ptn_product_sales_temp_summary where DATE(created_date) = CURDATE();

insert into tb_ptn_product_sales_temp_summary (product_id, sum_normal_price_web, sum_normal_price_playstore, sum_normal_price_ios, sum_normal_price_onestore, sum_discount_price_web, sum_discount_price_playstore, sum_discount_price_ios, sum_discount_price_onestore, sum_paid_ticket_price_web, sum_paid_ticket_price_playstore, sum_paid_ticket_price_ios, sum_paid_ticket_price_onestore, sum_comped_ticket_price_web, sum_comped_ticket_price_playstore, sum_comped_ticket_price_ios, sum_comped_ticket_price_onestore, sum_free_ticket_price_web, sum_free_ticket_price_playstore, sum_free_ticket_price_ios, sum_free_ticket_price_onestore, sum_refund_normal_price_web, sum_refund_normal_price_playstore, sum_refund_normal_price_ios, sum_refund_normal_price_onestore, sum_refund_discount_price_web, sum_refund_discount_price_playstore, sum_refund_discount_price_ios, sum_refund_discount_price_onestore, sum_refund_paid_ticket_price_web, sum_refund_paid_ticket_price_playstore, sum_refund_paid_ticket_price_ios, sum_refund_paid_ticket_price_onestore, sum_refund_comped_ticket_price_web, sum_refund_comped_ticket_price_playstore, sum_refund_comped_ticket_price_ios, sum_refund_comped_ticket_price_onestore, sum_refund_free_ticket_price_web, sum_refund_free_ticket_price_playstore, sum_refund_free_ticket_price_ios, sum_refund_free_ticket_price_onestore, created_id, updated_id)
select m.*
  from (
    with tmp_product_sales_daily_summary as (
        select product_id
             , sum(case when item_type = 'normal' and device_type = 'web' then item_price * quantity else 0 end) as sum_normal_price_web -- 일반구매(웹)
             , sum(case when item_type = 'normal' and device_type = 'playstore' then item_price * quantity else 0 end) as sum_normal_price_playstore -- 일반구매(구글)
             , sum(case when item_type = 'normal' and device_type = 'ios' then item_price * quantity else 0 end) as sum_normal_price_ios -- 일반구매(애플)
             , sum(case when item_type = 'normal' and device_type = 'onestore' then item_price * quantity else 0 end) as sum_normal_price_onestore -- 일반구매(원스토어)
             , sum(case when item_type = 'discount' and device_type = 'web' then item_price * quantity else 0 end) as sum_discount_price_web -- 할인구매(웹)
             , sum(case when item_type = 'discount' and device_type = 'playstore' then item_price * quantity else 0 end) as sum_discount_price_playstore -- 할인구매(구글)
             , sum(case when item_type = 'discount' and device_type = 'ios' then item_price * quantity else 0 end) as sum_discount_price_ios -- 할인구매(애플)
             , sum(case when item_type = 'discount' and device_type = 'onestore' then item_price * quantity else 0 end) as sum_discount_price_onestore -- 할인구매(원스토어)
             , sum(case when item_type = 'paid' and device_type = 'web' then item_price * quantity else 0 end) as sum_paid_ticket_price_web -- 유상 대여권(웹)
             , sum(case when item_type = 'paid' and device_type = 'playstore' then item_price * quantity else 0 end) as sum_paid_ticket_price_playstore -- 유상 대여권(구글)
             , sum(case when item_type = 'paid' and device_type = 'ios' then item_price * quantity else 0 end) as sum_paid_ticket_price_ios -- 유상 대여권(애플)
             , sum(case when item_type = 'paid' and device_type = 'onestore' then item_price * quantity else 0 end) as sum_paid_ticket_price_onestore -- 유상 대여권(원스토어)
             , sum(case when item_type = 'comped' and device_type = 'web' then item_price * quantity else 0 end) as sum_comped_ticket_price_web -- 무상 대여권(웹)
             , sum(case when item_type = 'comped' and device_type = 'playstore' then item_price * quantity else 0 end) as sum_comped_ticket_price_playstore -- 무상 대여권(구글)
             , sum(case when item_type = 'comped' and device_type = 'ios' then item_price * quantity else 0 end) as sum_comped_ticket_price_ios -- 무상 대여권(애플)
             , sum(case when item_type = 'comped' and device_type = 'onestore' then item_price * quantity else 0 end) as sum_comped_ticket_price_onestore -- 무상 대여권(원스토어)
             , sum(case when item_type = 'free' and device_type = 'web' then item_price * quantity else 0 end) as sum_free_ticket_price_web -- 무료 대여권(웹)
             , sum(case when item_type = 'free' and device_type = 'playstore' then item_price * quantity else 0 end) as sum_free_ticket_price_playstore -- 무료 대여권(구글)
             , sum(case when item_type = 'free' and device_type = 'ios' then item_price * quantity else 0 end) as sum_free_ticket_price_ios -- 무료 대여권(애플)
             , sum(case when item_type = 'free' and device_type = 'onestore' then item_price * quantity else 0 end) as sum_free_ticket_price_onestore -- 무료 대여권(원스토어)
             , count(1) as count_total_sales -- 총 판매
          from tb_batch_daily_sales_summary
         where item_type in ('normal', 'discount', 'paid', 'comped', 'free')
         group by product_id
    ),
    tmp_product_refund_daily_summary as (
        select product_id
             , sum(case when item_type = 'normal' and device_type = 'web' then refund_price else 0 end) as sum_refund_normal_price_web
             , sum(case when item_type = 'normal' and device_type = 'playstore' then refund_price else 0 end) as sum_refund_normal_price_playstore
             , sum(case when item_type = 'normal' and device_type = 'ios' then refund_price else 0 end) as sum_refund_normal_price_ios
             , sum(case when item_type = 'normal' and device_type = 'onestore' then refund_price else 0 end) as sum_refund_normal_price_onestore
             , sum(case when item_type = 'discount' and device_type = 'web' then refund_price else 0 end) as sum_refund_discount_price_web
             , sum(case when item_type = 'discount' and device_type = 'playstore' then refund_price else 0 end) as sum_refund_discount_price_playstore
             , sum(case when item_type = 'discount' and device_type = 'ios' then refund_price else 0 end) as sum_refund_discount_price_ios
             , sum(case when item_type = 'discount' and device_type = 'onestore' then refund_price else 0 end) as sum_refund_discount_price_onestore
             , sum(case when item_type = 'paid' and device_type = 'web' then refund_price else 0 end) as sum_refund_paid_ticket_price_web
             , sum(case when item_type = 'paid' and device_type = 'playstore' then refund_price else 0 end) as sum_refund_paid_ticket_price_playstore
             , sum(case when item_type = 'paid' and device_type = 'ios' then refund_price else 0 end) as sum_refund_paid_ticket_price_ios
             , sum(case when item_type = 'paid' and device_type = 'onestore' then refund_price else 0 end) as sum_refund_paid_ticket_price_onestore
             , sum(case when item_type = 'comped' and device_type = 'web' then refund_price else 0 end) as sum_refund_comped_ticket_price_web
             , sum(case when item_type = 'comped' and device_type = 'playstore' then refund_price else 0 end) as sum_refund_comped_ticket_price_playstore
             , sum(case when item_type = 'comped' and device_type = 'ios' then refund_price else 0 end) as sum_refund_comped_ticket_price_ios
             , sum(case when item_type = 'comped' and device_type = 'onestore' then refund_price else 0 end) as sum_refund_comped_ticket_price_onestore
             , sum(case when item_type = 'free' and device_type = 'web' then refund_price else 0 end) as sum_refund_free_ticket_price_web
             , sum(case when item_type = 'free' and device_type = 'playstore' then refund_price else 0 end) as sum_refund_free_ticket_price_playstore
             , sum(case when item_type = 'free' and device_type = 'ios' then refund_price else 0 end) as sum_refund_free_ticket_price_ios
             , sum(case when item_type = 'free' and device_type = 'onestore' then refund_price else 0 end) as sum_refund_free_ticket_price_onestore
             , count(1) as count_total_refund
          from tb_batch_daily_refund_summary
         where item_type in ('normal', 'discount', 'paid', 'comped', 'free')
         group by product_id
    )
    select a.product_id
         , b.sum_normal_price_web
         , b.sum_normal_price_playstore
         , b.sum_normal_price_ios
         , b.sum_normal_price_onestore
         , b.sum_discount_price_web
         , b.sum_discount_price_playstore
         , b.sum_discount_price_ios
         , b.sum_discount_price_onestore
         , b.sum_paid_ticket_price_web
         , b.sum_paid_ticket_price_playstore
         , b.sum_paid_ticket_price_ios
         , b.sum_paid_ticket_price_onestore
         , b.sum_comped_ticket_price_web
         , b.sum_comped_ticket_price_playstore
         , b.sum_comped_ticket_price_ios
         , b.sum_comped_ticket_price_onestore
         , b.sum_free_ticket_price_web
         , b.sum_free_ticket_price_playstore
         , b.sum_free_ticket_price_ios
         , b.sum_free_ticket_price_onestore
         , c.sum_refund_normal_price_web
         , c.sum_refund_normal_price_playstore
         , c.sum_refund_normal_price_ios
         , c.sum_refund_normal_price_onestore
         , c.sum_refund_discount_price_web
         , c.sum_refund_discount_price_playstore
         , c.sum_refund_discount_price_ios
         , c.sum_refund_discount_price_onestore
         , c.sum_refund_paid_ticket_price_web
         , c.sum_refund_paid_ticket_price_playstore
         , c.sum_refund_paid_ticket_price_ios
         , c.sum_refund_paid_ticket_price_onestore
         , c.sum_refund_comped_ticket_price_web
         , c.sum_refund_comped_ticket_price_playstore
         , c.sum_refund_comped_ticket_price_ios
         , c.sum_refund_comped_ticket_price_onestore
         , c.sum_refund_free_ticket_price_web
         , c.sum_refund_free_ticket_price_playstore
         , c.sum_refund_free_ticket_price_ios
         , c.sum_refund_free_ticket_price_onestore
         , 0 as created_id
         , 0 as updated_id
      from tb_batch_daily_product_info_summary a
      left join tmp_product_sales_daily_summary b on a.product_id = b.product_id
      left join tmp_product_refund_daily_summary c on a.product_id = c.product_id
      where b.count_total_sales is not null
         and c.count_total_refund is not null
    ) m
;

-- 후원 및 기타 정산용 임시 합산 (당일 데이터 삭제 후 재생성)
delete from tb_ptn_income_settlement_temp_summary where DATE(created_date) = CURDATE();

insert into tb_ptn_income_settlement_temp_summary (product_id, item_type, device_type, sum_income_price, created_id, updated_id)
select m.*
  from (
    with tmp_income_summary as (
        select product_id
             , item_type
             , device_type
             , sum(item_price * quantity) as sum_income_price
          from tb_batch_daily_sales_summary
         where item_type in ('sponsorship', 'ad')
         group by product_id, item_type, device_type
    ),
    tmp_refund_income_summary as (
        select product_id
             , item_type
             , device_type
             , sum(refund_price) as sum_refund_income_price
          from tb_batch_daily_refund_summary
         where item_type in ('sponsorship', 'ad')
         group by product_id, item_type, device_type
    )
    select t.product_id
         , t.item_type
         , t.device_type
         , (t.sum_income_price - coalesce(z.sum_refund_income_price, 0)) as sum_income_price
         , 0 as created_id
         , 0 as updated_id
      from (
        select a.product_id
             , b.item_type
             , b.device_type
             , coalesce(b.sum_income_price, 0) as sum_income_price
          from tb_batch_daily_product_info_summary a
          left join tmp_income_summary b on a.product_id = b.product_id
      ) t
      left join tmp_refund_income_summary z on t.product_id = z.product_id
       and t.item_type = z.item_type
       and t.device_type = z.device_type
    ) m
 where m.item_type is not null
   and m.device_type is not null
;

update tb_cms_batch_job_process a
   set a.completed_yn = 'Y'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'partner_report_daily_batch.sh'
;

commit;

