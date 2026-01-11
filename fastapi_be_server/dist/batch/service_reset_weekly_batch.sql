
update tb_cms_batch_job_process a
   set a.completed_yn = 'N'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'service_reset_weekly_batch.sh'
;

start transaction;

-- 퀘스트 진행상황 초기화(투표하기)
update tb_quest_user a
  inner join (
    select z.quest_id
         , z.title
         , coalesce(lag(z.goal_stage, 1) over (partition by title order by quest_id), 0) as initial_stage
      from tb_quest z
     where z.use_yn = 'Y'
       and z.title = '투표하기'
  ) as t on a.quest_id = t.quest_id
   set a.current_stage = t.initial_stage
     , a.achieve_yn = 'N'
     , a.reward_own_yn = 'N'
 where 1=1
;

-- TODO: 타임패스 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료. 별도 테이블 생성 혹은 컬럼 추가 필)
-- 타임패스 남은 자리(20) 초기화
-- update tb_product_promotion
--    set  = 20
--  where use_yn = 'Y'
--    and req_status = 'approval'
--    and promotion_id = (select promotion_id from tb_promotion z
--                         where use_yn = 'Y'
--                           and promotion_type = 'apply'
--                           and promotion_name = '6-9패스 대여권')
-- ;

-- TODO: 독자알림 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료. 별도 테이블 생성 혹은 컬럼 추가 필)
-- 독자알림 횟수(5) 초기화
-- update tb_product
--    set  = 5
--  where 1=1
-- ;

-- 선작 독자 무료 이용권 프로모션 status 초기화 (end -> ing)
update tb_direct_promotion
   set status = 'ing'
     , updated_date = NOW()
 where type = 'reader-of-prev'
   and status = 'end'
;

update tb_cms_batch_job_process a
   set a.completed_yn = 'Y'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'service_reset_weekly_batch.sh'
;

commit;

