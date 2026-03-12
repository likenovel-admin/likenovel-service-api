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
