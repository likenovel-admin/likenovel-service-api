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
    select count(*) from tb_product_order po inner join tb_user u on u.user_id = po.user_id where po.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
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
    select count(*) from tb_product_order po inner join tb_user u on u.user_id = po.user_id where po.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'M'
  ) as male_payment_count,
  (
    select count(*) from tb_product_order po inner join tb_user u on u.user_id = po.user_id where po.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'F'
  ) as female_payment_count,
  (
    select count(*) from tb_product_order po inner join tb_user u on u.user_id = po.user_id where po.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'M' and timestampdiff(year, u.birthdate, curdate()) <= 29
  ) as male_20_under_payment_count,
  (
    select count(*) from tb_product_order po inner join tb_user u on u.user_id = po.user_id where po.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'M' and 30 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 39
  ) as male_30_payment_count,
  (
    select count(*) from tb_product_order po inner join tb_user u on u.user_id = po.user_id where po.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'M' and 40 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 49
  ) as male_40_payment_count,
  (
    select count(*) from tb_product_order po inner join tb_user u on u.user_id = po.user_id where po.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'M' and 50 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 59
  ) as male_50_payment_count,
  (
    select count(*) from tb_product_order po inner join tb_user u on u.user_id = po.user_id where po.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'M' and 60 <= timestampdiff(year, u.birthdate, curdate())
  ) as male_60_over_payment_count,
  (
    select count(*) from tb_product_order po inner join tb_user u on u.user_id = po.user_id where po.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'F' and timestampdiff(year, u.birthdate, curdate()) <= 29
  ) as female_20_under_payment_count,
  (
    select count(*) from tb_product_order po inner join tb_user u on u.user_id = po.user_id where po.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'F' and 30 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 39
  ) as female_30_payment_count,
  (
    select count(*) from tb_product_order po inner join tb_user u on u.user_id = po.user_id where po.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'F' and 40 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 49
  ) as female_40_payment_count,
  (
    select count(*) from tb_product_order po inner join tb_user u on u.user_id = po.user_id where po.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
    and u.gender = 'F' and 50 <= timestampdiff(year, u.birthdate, curdate()) and timestampdiff(year, u.birthdate, curdate()) <= 59
  ) as female_50_payment_count,
  (
    select count(*) from tb_product_order po inner join tb_user u on u.user_id = po.user_id where po.product_id = p.product_id and date_sub(now(), interval 1 hour) <= po.created_date and po.created_date < now()
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
insert into tb_user_productbook (user_id, profile_id, product_id, episode_id, own_type, ticket_type, acquisition_type, acquisition_id, use_yn, created_id, updated_id)
select upb.user_id
     , upb.profile_id
     , upb.product_id
     , NULL as episode_id
     , 'rental' as own_type
     , upb.ticket_type
     , 'applied_promotion' as acquisition_type
     , upb.acquisition_id
     , 'N' as use_yn
     , 0 as created_id
     , 0 as updated_id
  from tb_user_productbook upb
 inner join tb_applied_promotion ap on upb.acquisition_id = ap.id
 where upb.acquisition_type = 'applied_promotion'
   and ap.type = 'waiting-for-free'
   and ap.status = 'ing'
   and (ap.end_date IS NULL OR ap.end_date >= NOW())
   and upb.use_yn = 'Y'  -- 사용한 대여권
   and upb.use_date is not null
   and timestampdiff(hour, upb.use_date, now()) >= 24  -- 사용한지 24시간 이상 경과
   -- 해당 유저가 이 프로모션으로 사용하지 않은 대여권이 없는지 체크
   and not exists (
       select 1 from tb_user_productbook upb2
        where upb2.user_id = upb.user_id
          and upb2.acquisition_id = upb.acquisition_id
          and upb2.acquisition_type = 'applied_promotion'
          and upb2.use_yn = 'N'
   )
   -- 마지막 사용 후 이미 추가 발급 받았는지 체크 (중복 발급 방지)
   and not exists (
       select 1 from tb_user_productbook upb3
        where upb3.user_id = upb.user_id
          and upb3.acquisition_id = upb.acquisition_id
          and upb3.acquisition_type = 'applied_promotion'
          and upb3.created_date > upb.use_date  -- 사용 이후에 생성된 대여권
   )
;

update tb_cms_batch_job_process a
   set a.completed_yn = 'Y'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'summary_hourly_batch.sh'
;

commit;
