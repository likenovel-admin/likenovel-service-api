
update tb_cms_batch_job_process a
   set a.completed_yn = 'N'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'service_reset_daily_batch.sh'
;

start transaction;

-- 퀘스트 진행상황 초기화(출석체크, 평가하기, 작품 리뷰 작성하기, 회차 결제하기)
update tb_quest_user a
  inner join (
    select z.quest_id
         , z.title
         , coalesce(lag(z.goal_stage, 1) over (partition by title order by quest_id), 0) as initial_stage
      from tb_quest z
     where z.use_yn = 'Y'
       and z.title in ('출석체크', '평가하기', '작품 리뷰 작성하기', '회차 결제하기')
  ) as t on a.quest_id = t.quest_id
   set a.current_stage = t.initial_stage
     , a.achieve_yn = 'N'
     , a.reward_own_yn = 'N'
 where 1=1
;

-- 작가 홈(내 작품 관리) 관련 인디케이터
truncate tb_product_count_variance
;

insert into tb_product_count_variance (product_id, count_hit_indicator, count_recommend_indicator, count_bookmark_indicator, count_unbookmark_indicator, count_cp_hit_indicator, reading_rate_indicator, count_interest_indicator, count_interest_sustain_indicator, count_interest_loss_indicator, created_id, updated_id)
select a.product_id
     , case when b.privious_count_hit is null then b.current_count_hit
            else b.current_count_hit - b.privious_count_hit
       end as count_hit_indicator
     , case when b.privious_count_recommend is null then b.current_count_recommend
            else b.current_count_recommend - b.privious_count_recommend
       end as count_recommend_indicator
     , case when b.privious_count_bookmark is null then b.current_count_bookmark
            else b.current_count_bookmark - b.privious_count_bookmark
       end as count_bookmark_indicator
     , case when b.privious_count_unbookmark is null then b.current_count_unbookmark
            else b.current_count_unbookmark - b.privious_count_unbookmark
       end as count_unbookmark_indicator
     , case when b.privious_count_cp_hit is null then b.current_count_cp_hit
            else b.current_count_cp_hit - b.privious_count_cp_hit
       end as count_cp_hit_indicator
     , case when b.privious_reading_rate is null then b.current_reading_rate
            else b.current_reading_rate - b.privious_reading_rate
       end as reading_rate_indicator
     , case when b.privious_count_interest is null then b.current_count_interest
            else b.current_count_interest - b.privious_count_interest
       end as count_interest_indicator
     , case when b.privious_count_interest_sustain is null then b.current_count_interest_sustain
            else b.current_count_interest_sustain - b.privious_count_interest_sustain
       end as count_interest_sustain_indicator
     , case when b.privious_count_interest_loss is null then b.current_count_interest_loss
            else b.current_count_interest_loss - b.privious_count_interest_loss
       end as count_interest_loss_indicator
     , 0 as created_id
     , 0 as updated_id
  from tb_product a
  left join tb_batch_daily_product_count_summary b on a.product_id = b.product_id
;

-- 작가 홈(회차 관리) 관련 인디케이터
truncate tb_product_episode_count_variance
;

insert into tb_product_episode_count_variance (product_id, episode_id, episode_no, count_hit_indicator, count_recommend_indicator, count_comment_indicator, count_evaluation_indicator, created_id, updated_id)
select a.product_id
     , a.episode_id
     , a.episode_no
     , case when b.privious_count_hit is null then b.current_count_hit
            else b.current_count_hit - b.privious_count_hit
       end as count_hit_indicator
     , case when b.privious_count_recommend is null then b.current_count_recommend
            else b.current_count_recommend - b.privious_count_recommend
       end as count_recommend_indicator
     , case when b.privious_count_comment is null then b.current_count_comment
            else b.current_count_comment - b.privious_count_comment
       end as count_comment_indicator
     , case when b.privious_count_evaluation is null then b.current_count_evaluation
            else b.current_count_evaluation - b.privious_count_evaluation
       end as count_evaluation_indicator
     , 0 as created_id
     , 0 as updated_id
  from tb_product_episode a
  left join tb_batch_daily_product_episode_count_summary b on a.product_id = b.product_id
   and a.episode_id = b.episode_id
;

-- 만료된 선물함 항목 삭제 (received_yn = 'N'이고 유효기간 지남)
-- expiration_date가 있는 경우: expiration_date 기준
-- expiration_date가 없는 경우: created_date + 7일 기준 (기본 유효기간)
-- 단, promotion_type이 'waiting-for-free'인 경우는 유효기간 없음 (삭제 안함)
DELETE FROM tb_user_giftbook
WHERE received_yn = 'N'
  AND (promotion_type IS NULL OR promotion_type != 'waiting-for-free')
  AND (
      (expiration_date IS NOT NULL AND expiration_date < NOW())
      OR (expiration_date IS NULL AND DATE_ADD(created_date, INTERVAL 7 DAY) < NOW())
  )
;

update tb_cms_batch_job_process a
   set a.completed_yn = 'Y'
     , a.created_id = 0
     , a.updated_id = 0
 where a.job_file_id = 'service_reset_daily_batch.sh'
;

commit;

