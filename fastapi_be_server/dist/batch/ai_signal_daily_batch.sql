start transaction;

-- 동일 배치 전역 직렬화(멀티 인스턴스 동시 실행 방지)
set @job_lock_name = 'lk_ai_signal_daily_batch';
set @job_lock_acquired = get_lock(@job_lock_name, 30);
set @job_lock_guard_sql = if(
    @job_lock_acquired = 1,
    'select 1',
    'select * from __ai_signal_lock_not_acquired__'
);
prepare stmt_job_lock_guard from @job_lock_guard_sql;
execute stmt_job_lock_guard;
deallocate prepare stmt_job_lock_guard;

-- 배치 상태 row seed (pre-49 환경에서도 중복 최소화를 위해 NOT EXISTS 가드 적용)
insert ignore into tb_cms_batch_job_process (
    job_file_id,
    job_group_id,
    job_order,
    completed_yn,
    job_list,
    created_id,
    updated_id
)
select 'ai_signal_daily_batch.sh',
       0,
       0,
       'N',
       'ai_signal_daily_batch.sh',
       0,
       0
  from dual
 where not exists (
    select 1
      from tb_cms_batch_job_process x
     where x.job_file_id = 'ai_signal_daily_batch.sh'
 );

-- 최신 job row를 for update로 잠가 상태 갱신 대상을 단건으로 고정
select a.id
     , a.completed_yn
     , coalesce(a.updated_date, '1970-01-01 00:00:00')
  into @job_id
     , @job_completed_yn
     , @job_updated_date
  from tb_cms_batch_job_process a
 where a.job_file_id = 'ai_signal_daily_batch.sh'
 order by a.updated_date desc, a.id desc
 limit 1
 for update
;

-- 최근 실행이 아직 진행중(N)으로 보이면 fail-fast
-- (배포 타이밍/수동 재실행 경합에서 purge 단계와 겹치는 중복 실행 방지)
set @in_progress_stale_minutes = coalesce(@in_progress_stale_minutes, 60);
set @in_progress_guard_sql = if(
    @job_completed_yn = 'N'
    and timestampdiff(minute, @job_updated_date, now()) < @in_progress_stale_minutes,
    'select * from __ai_signal_batch_in_progress__',
    'select 1'
);
prepare stmt_in_progress_guard from @in_progress_guard_sql;
execute stmt_in_progress_guard;
deallocate prepare stmt_in_progress_guard;

update tb_cms_batch_job_process a
   set a.completed_yn = 'N'
     , a.created_id = coalesce(@batch_run_token, 0)
     , a.updated_id = coalesce(@batch_run_token, 0)
 where a.id = @job_id
;

-- 일배치 기준일: 전일
set @target_date = date_sub(curdate(), interval 1 day);

-- 보관 정책(기본 90일)
set @retention_days = (
    select p.retention_days
      from tb_ai_signal_retention_policy p
     where p.enabled_yn = 'Y'
     order by p.id desc
     limit 1
);
set @retention_days = coalesce(@retention_days, 90);
set @purge_before_date = date_sub(curdate(), interval @retention_days day);

-- 대상 주 시작일(월요일)
set @target_week_start = date_sub(@target_date, interval weekday(@target_date) day);
set @target_week_end = date_add(@target_week_start, interval 7 day);

-- 1) 원천 이벤트 -> 일 집계
insert into tb_user_ai_signal_event_daily (
    stat_date,
    user_id,
    product_id,
    event_type,
    event_count,
    sum_active_seconds,
    avg_scroll_depth,
    avg_progress_ratio,
    latest_episode_reached_count,
    revisit_24h_count,
    created_date,
    updated_date
)
select date(e.created_date) as stat_date
     , e.user_id
     , e.product_id
     , e.event_type
     , count(1) as event_count
     , sum(coalesce(e.active_seconds, 0)) as sum_active_seconds
     , avg(coalesce(e.scroll_depth, 0)) as avg_scroll_depth
     , avg(coalesce(e.progress_ratio, 0)) as avg_progress_ratio
     , sum(case when e.latest_episode_reached_yn = 'Y' then 1 else 0 end) as latest_episode_reached_count
     , sum(case when e.event_type = 'revisit_24h' then 1 else 0 end) as revisit_24h_count
     , now() as created_date
     , now() as updated_date
  from tb_user_ai_signal_event e
 where e.created_date >= @target_date
   and e.created_date < date_add(@target_date, interval 1 day)
 group by date(e.created_date)
        , e.user_id
        , e.product_id
        , e.event_type
on duplicate key update
    event_count = values(event_count),
    sum_active_seconds = values(sum_active_seconds),
    avg_scroll_depth = values(avg_scroll_depth),
    avg_progress_ratio = values(avg_progress_ratio),
    latest_episode_reached_count = values(latest_episode_reached_count),
    revisit_24h_count = values(revisit_24h_count),
    updated_date = now()
;

-- 2) 일 집계 -> 주 집계
insert into tb_user_ai_signal_event_weekly (
    week_start_date,
    user_id,
    product_id,
    event_type,
    event_count,
    sum_active_seconds,
    avg_scroll_depth,
    avg_progress_ratio,
    latest_episode_reached_count,
    revisit_24h_count,
    created_date,
    updated_date
)
select @target_week_start as week_start_date
     , d.user_id
     , d.product_id
     , d.event_type
     , sum(d.event_count) as event_count
     , sum(d.sum_active_seconds) as sum_active_seconds
     , case when sum(d.event_count) = 0 then 0
            else sum(d.avg_scroll_depth * d.event_count) / sum(d.event_count)
       end as avg_scroll_depth
     , case when sum(d.event_count) = 0 then 0
            else sum(d.avg_progress_ratio * d.event_count) / sum(d.event_count)
       end as avg_progress_ratio
     , sum(d.latest_episode_reached_count) as latest_episode_reached_count
     , sum(d.revisit_24h_count) as revisit_24h_count
     , now() as created_date
     , now() as updated_date
  from tb_user_ai_signal_event_daily d
 where d.stat_date >= @target_week_start
   and d.stat_date < @target_week_end
 group by d.user_id
        , d.product_id
        , d.event_type
on duplicate key update
    event_count = values(event_count),
    sum_active_seconds = values(sum_active_seconds),
    avg_scroll_depth = values(avg_scroll_depth),
    avg_progress_ratio = values(avg_progress_ratio),
    latest_episode_reached_count = values(latest_episode_reached_count),
    revisit_24h_count = values(revisit_24h_count),
    updated_date = now()
;

commit;

-- 3) retention purge + 상태 기록은 셸 스크립트(ai_signal_daily_batch.sh)에서 purge 성공 후 처리
select release_lock(@job_lock_name);
