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
   and e.price_type = 'free'
   and e.use_yn = 'Y'
;
