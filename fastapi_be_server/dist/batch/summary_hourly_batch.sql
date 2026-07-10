SET @job_lock_name = 'lk_summary_hourly_batch';
SET @job_lock_acquired = GET_LOCK(@job_lock_name, 30);
SET @job_lock_guard_sql = IF(
    @job_lock_acquired = 1,
    'SELECT 1',
    'SELECT * FROM __summary_hourly_lock_not_acquired__'
);
PREPARE stmt_job_lock_guard FROM @job_lock_guard_sql;
EXECUTE stmt_job_lock_guard;
DEALLOCATE PREPARE stmt_job_lock_guard;

update tb_cms_batch_job_process a
   set a.completed_yn = 'N'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'summary_hourly_batch.sh'
;

start transaction;

-- 시간별 유입 통계
insert into tb_hourly_inflow (product_id, created_date,
  total_view_count, total_payment_count, male_view_count, female_view_count, male_payment_count, female_payment_count,
  male_20_under_payment_count, male_30_payment_count, male_40_payment_count, male_50_payment_count, male_60_over_payment_count,
  female_20_under_payment_count, female_30_payment_count, female_40_payment_count, female_50_payment_count, female_60_over_payment_count,
  male_20_under_view_count, male_30_view_count, male_40_view_count, male_50_view_count, male_60_over_view_count,
  female_20_under_view_count, female_30_view_count, female_40_view_count, female_50_view_count, female_60_over_view_count)
select p.product_id, now() as created_date,
  (
    select count(*) from tb_user_product_usage upu inner join tb_user u on u.user_id = upu.user_id where upu.product_id = p.product_id and date_sub(now(), interval 1 hour) <= upu.created_date and upu.created_date < now()
  ) as total_view_count,
  (
    select count(*) from tb_product_order po
    inner join tb_product_order_item poi on poi.order_id = po.order_id
    inner join tb_product_order_item_info poii on poii.item_info_id = poi.item_id
    inner join tb_user u on u.user_id = po.user_id
    where poii.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
  ) as total_payment_count,
  (
    select count(*) from tb_user_product_usage upu inner join tb_user u on u.user_id = upu.user_id where upu.product_id = p.product_id and date_sub(now(), interval 1 hour) <= upu.created_date and upu.created_date < now()
    and u.gender = 'M'
  ) as male_view_count,
  (
    select count(*) from tb_user_product_usage upu inner join tb_user u on u.user_id = upu.user_id where upu.product_id = p.product_id and date_sub(now(), interval 1 hour) <= upu.created_date and upu.created_date < now()
    and u.gender = 'F'
  ) as female_view_count,
  (
    select count(*) from tb_product_order po
    inner join tb_product_order_item poi on poi.order_id = po.order_id
    inner join tb_product_order_item_info poii on poii.item_info_id = poi.item_id
    inner join tb_user u on u.user_id = po.user_id
    where poii.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'M'
  ) as male_payment_count,
  (
    select count(*) from tb_product_order po
    inner join tb_product_order_item poi on poi.order_id = po.order_id
    inner join tb_product_order_item_info poii on poii.item_info_id = poi.item_id
    inner join tb_user u on u.user_id = po.user_id
    where poii.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'F'
  ) as female_payment_count,
  (
    select count(*) from tb_product_order po
    inner join tb_product_order_item poi on poi.order_id = po.order_id
    inner join tb_product_order_item_info poii on poii.item_info_id = poi.item_id
    inner join tb_user u on u.user_id = po.user_id
    where poii.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'M' and timestampdiff(year, u.birthdate, curdate()) <= 29
  ) as male_20_under_payment_count,
  (
    select count(*) from tb_product_order po
    inner join tb_product_order_item poi on poi.order_id = po.order_id
    inner join tb_product_order_item_info poii on poii.item_info_id = poi.item_id
    inner join tb_user u on u.user_id = po.user_id
    where poii.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'M' and 30 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 39
  ) as male_30_payment_count,
  (
    select count(*) from tb_product_order po
    inner join tb_product_order_item poi on poi.order_id = po.order_id
    inner join tb_product_order_item_info poii on poii.item_info_id = poi.item_id
    inner join tb_user u on u.user_id = po.user_id
    where poii.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'M' and 40 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 49
  ) as male_40_payment_count,
  (
    select count(*) from tb_product_order po
    inner join tb_product_order_item poi on poi.order_id = po.order_id
    inner join tb_product_order_item_info poii on poii.item_info_id = poi.item_id
    inner join tb_user u on u.user_id = po.user_id
    where poii.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'M' and 50 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 59
  ) as male_50_payment_count,
  (
    select count(*) from tb_product_order po
    inner join tb_product_order_item poi on poi.order_id = po.order_id
    inner join tb_product_order_item_info poii on poii.item_info_id = poi.item_id
    inner join tb_user u on u.user_id = po.user_id
    where poii.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'M' and 60 <= timestampdiff(year, u.birthdate, curdate())
  ) as male_60_over_payment_count,
  (
    select count(*) from tb_product_order po
    inner join tb_product_order_item poi on poi.order_id = po.order_id
    inner join tb_product_order_item_info poii on poii.item_info_id = poi.item_id
    inner join tb_user u on u.user_id = po.user_id
    where poii.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'F' and timestampdiff(year, u.birthdate, curdate()) <= 29
  ) as female_20_under_payment_count,
  (
    select count(*) from tb_product_order po
    inner join tb_product_order_item poi on poi.order_id = po.order_id
    inner join tb_product_order_item_info poii on poii.item_info_id = poi.item_id
    inner join tb_user u on u.user_id = po.user_id
    where poii.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'F' and 30 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 39
  ) as female_30_payment_count,
  (
    select count(*) from tb_product_order po
    inner join tb_product_order_item poi on poi.order_id = po.order_id
    inner join tb_product_order_item_info poii on poii.item_info_id = poi.item_id
    inner join tb_user u on u.user_id = po.user_id
    where poii.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'F' and 40 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 49
  ) as female_40_payment_count,
  (
    select count(*) from tb_product_order po
    inner join tb_product_order_item poi on poi.order_id = po.order_id
    inner join tb_product_order_item_info poii on poii.item_info_id = poi.item_id
    inner join tb_user u on u.user_id = po.user_id
    where poii.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'F' and 50 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 59
  ) as female_50_payment_count,
  (
    select count(*) from tb_product_order po
    inner join tb_product_order_item poi on poi.order_id = po.order_id
    inner join tb_product_order_item_info poii on poii.item_info_id = poi.item_id
    inner join tb_user u on u.user_id = po.user_id
    where poii.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'F' and 60 <= timestampdiff(year, u.birthdate, curdate())
  ) as female_60_over_payment_count,
  (
    select count(*) from tb_user_product_usage upu inner join tb_user u on u.user_id = upu.user_id where upu.product_id = p.product_id and date_sub(now(), interval 1 hour) <= upu.created_date and upu.created_date < now()
    and u.gender = 'M' and timestampdiff(year, u.birthdate, curdate()) <= 29
  ) as male_20_under_view_count,
  (
    select count(*) from tb_user_product_usage upu inner join tb_user u on u.user_id = upu.user_id where upu.product_id = p.product_id and date_sub(now(), interval 1 hour) <= upu.created_date and upu.created_date < now()
    and u.gender = 'M' and 30 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 39
  ) as male_30_view_count,
  (
    select count(*) from tb_user_product_usage upu inner join tb_user u on u.user_id = upu.user_id where upu.product_id = p.product_id and date_sub(now(), interval 1 hour) <= upu.created_date and upu.created_date < now()
    and u.gender = 'M' and 40 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 49
  ) as male_40_view_count,
  (
    select count(*) from tb_user_product_usage upu inner join tb_user u on u.user_id = upu.user_id where upu.product_id = p.product_id and date_sub(now(), interval 1 hour) <= upu.created_date and upu.created_date < now()
    and u.gender = 'M' and 50 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 59
  ) as male_50_view_count,
  (
    select count(*) from tb_user_product_usage upu inner join tb_user u on u.user_id = upu.user_id where upu.product_id = p.product_id and date_sub(now(), interval 1 hour) <= upu.created_date and upu.created_date < now()
    and u.gender = 'M' and 60 <= timestampdiff(year, u.birthdate, curdate())
  ) as male_60_over_view_count,
  (
    select count(*) from tb_user_product_usage upu inner join tb_user u on u.user_id = upu.user_id where upu.product_id = p.product_id and date_sub(now(), interval 1 hour) <= upu.created_date and upu.created_date < now()
    and u.gender = 'F' and timestampdiff(year, u.birthdate, curdate()) <= 29
  ) as female_20_under_view_count,
  (
    select count(*) from tb_user_product_usage upu inner join tb_user u on u.user_id = upu.user_id where upu.product_id = p.product_id and date_sub(now(), interval 1 hour) <= upu.created_date and upu.created_date < now()
    and u.gender = 'F' and 30 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 39
  ) as female_30_view_count,
  (
    select count(*) from tb_user_product_usage upu inner join tb_user u on u.user_id = upu.user_id where upu.product_id = p.product_id and date_sub(now(), interval 1 hour) <= upu.created_date and upu.created_date < now()
    and u.gender = 'F' and 40 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 49
  ) as female_40_view_count,
  (
    select count(*) from tb_user_product_usage upu inner join tb_user u on u.user_id = upu.user_id where upu.product_id = p.product_id and date_sub(now(), interval 1 hour) <= upu.created_date and upu.created_date < now()
    and u.gender = 'F' and 50 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 59
  ) as female_50_view_count,
  (
    select count(*) from tb_user_product_usage upu inner join tb_user u on u.user_id = upu.user_id where upu.product_id = p.product_id and date_sub(now(), interval 1 hour) <= upu.created_date and upu.created_date < now()
    and u.gender = 'F' and 60 <= timestampdiff(year, u.birthdate, curdate())
  ) as female_60_over_view_count
from tb_product p;

-- 기다리면 무료 (waiting-for-free) 24시간 후 추가 발급
-- 대여권을 사용한지 24시간이 지났고, 현재 사용하지 않은 대여권이 없는 유저에게 1개 추가 발급
insert into tb_user_productbook (user_id, profile_id, product_id, episode_id, own_type, ticket_type, acquisition_type, acquisition_id, use_yn, created_id, created_date, updated_id, updated_date)
select seed.user_id
     , seed.profile_id
     , seed.product_id
     , NULL as episode_id
     , 'rental' as own_type
     , 'waiting-for-free' as ticket_type
     , 'applied_promotion' as acquisition_type
     , seed.promotion_id
     , 'N' as use_yn
     , 0 as created_id
     , NOW() as created_date
     , 0 as updated_id
     , NOW() as updated_date
  from (
      select source.user_id
           , source.profile_id
           , source.product_id
           , source.promotion_id
           , max(source.use_date) as last_use_date
        from (
            select upb.user_id
                 , upb.profile_id
                 , upb.product_id
                 , upb.acquisition_id as promotion_id
                 , upb.use_date
              from tb_user_productbook upb
             inner join tb_applied_promotion ap
                on upb.acquisition_type = 'applied_promotion'
               and upb.acquisition_id = ap.id
             where upb.use_yn = 'Y'
               and upb.use_date is not null
               and ap.type = 'waiting-for-free'
               and ap.status = 'ing'
               and ap.start_date <= NOW()
               and (ap.end_date IS NULL OR DATE(ap.end_date) >= CURDATE())
            union all
            select upb.user_id
                 , upb.profile_id
                 , upb.product_id
                 , ug.acquisition_id as promotion_id
                 , upb.use_date
              from tb_user_productbook upb
             inner join tb_user_giftbook ug
                on upb.acquisition_type = 'gift'
               and upb.acquisition_id = ug.id
             inner join tb_applied_promotion ap
                on ug.acquisition_type = 'applied_promotion'
               and ug.acquisition_id = ap.id
             where upb.use_yn = 'Y'
               and upb.use_date is not null
               and ug.promotion_type = 'waiting-for-free'
               and ug.acquisition_type = 'applied_promotion'
               and ap.type = 'waiting-for-free'
               and ap.status = 'ing'
               and ap.start_date <= NOW()
               and (ap.end_date IS NULL OR DATE(ap.end_date) >= CURDATE())
        ) source
       group by source.user_id
              , source.profile_id
              , source.product_id
              , source.promotion_id
  ) seed
 inner join tb_applied_promotion ap on ap.id = seed.promotion_id
 where timestampdiff(hour, seed.last_use_date, now()) >= 24
   and ap.type = 'waiting-for-free'
   and ap.status = 'ing'
   and ap.start_date <= NOW()
   and (ap.end_date IS NULL OR DATE(ap.end_date) >= CURDATE())
   -- 해당 유저가 이 프로모션으로 사용하지 않은 대여권이 없는지 체크
   and not exists (
       select 1
         from tb_user_productbook upb2
         left join tb_user_giftbook ug2
           on upb2.acquisition_type = 'gift'
          and upb2.acquisition_id = ug2.id
        where upb2.user_id = seed.user_id
          and upb2.profile_id = seed.profile_id
          and upb2.product_id = seed.product_id
          and upb2.use_yn = 'N'
          and (
              (upb2.acquisition_type = 'applied_promotion' and upb2.acquisition_id = seed.promotion_id)
              or
              (upb2.acquisition_type = 'gift' and ug2.promotion_type = 'waiting-for-free'
               and ug2.acquisition_type = 'applied_promotion' and ug2.acquisition_id = seed.promotion_id)
          )
   )
   -- 마지막 사용 후 이미 추가 발급 받았는지 체크 (중복 발급 방지)
   and not exists (
       select 1
         from tb_user_productbook upb3
         left join tb_user_giftbook ug3
           on upb3.acquisition_type = 'gift'
          and upb3.acquisition_id = ug3.id
        where upb3.user_id = seed.user_id
          and upb3.profile_id = seed.profile_id
          and upb3.product_id = seed.product_id
          and upb3.created_date > seed.last_use_date
          and (
              (upb3.acquisition_type = 'applied_promotion' and upb3.acquisition_id = seed.promotion_id)
              or
              (upb3.acquisition_type = 'gift' and ug3.promotion_type = 'waiting-for-free'
               and ug3.acquisition_type = 'applied_promotion' and ug3.acquisition_id = seed.promotion_id)
          )
   )
;

update tb_cms_batch_job_process a
   set a.completed_yn = 'Y'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'summary_hourly_batch.sh'
;

commit;

SELECT RELEASE_LOCK(@job_lock_name) INTO @job_lock_released;
