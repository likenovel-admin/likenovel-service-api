start transaction;

-- 자동 시간배치와 동일한 전역 락을 사용해 동시 반영 충돌을 방지한다.
set @job_lock_name = 'lk_ai_taste_hourly_batch';
set @job_lock_acquired = get_lock(@job_lock_name, 30);
set @job_lock_guard_sql = if(
    @job_lock_acquired = 1,
    'select 1',
    'select * from __ai_taste_lock_not_acquired__'
);
prepare stmt_job_lock_guard from @job_lock_guard_sql;
execute stmt_job_lock_guard;
deallocate prepare stmt_job_lock_guard;

set @replay_from_id = coalesce(@replay_from_id, 0);
set @replay_to_id = coalesce(@replay_to_id, 0);
set @manual_run_token = coalesce(@manual_run_token, 0);
set @manual_allow_duplicate_yn = if(@manual_allow_duplicate_yn = 'Y', 'Y', 'N');
set @manual_source_total_count = coalesce(@manual_source_total_count, 0);
set @manual_source_valid_count = coalesce(@manual_source_valid_count, 0);
set @manual_requested_by = coalesce(@manual_requested_by, 'manual-admin');

set @replay_range_guard_sql = if(
    @replay_from_id > 0 and @replay_to_id > 0 and @replay_from_id <= @replay_to_id,
    'select 1',
    'select * from __ai_taste_invalid_replay_range__'
);
prepare stmt_replay_range_guard from @replay_range_guard_sql;
execute stmt_replay_range_guard;
deallocate prepare stmt_replay_range_guard;

set @run_token_guard_sql = if(
    @manual_run_token > 0,
    'select 1',
    'select * from __ai_taste_invalid_run_token__'
);
prepare stmt_run_token_guard from @run_token_guard_sql;
execute stmt_run_token_guard;
deallocate prepare stmt_run_token_guard;

set @already_success_count = (
    select count(1)
      from tb_ai_taste_manual_replay_log x
     where x.to_event_id >= @replay_from_id
       and x.from_event_id <= @replay_to_id
       and x.status = 'SUCCESS'
);

set @already_success_guard_sql = if(
    @manual_allow_duplicate_yn = 'Y' or @already_success_count = 0,
    'select 1',
    'select * from __ai_taste_replay_already_succeeded__'
);
prepare stmt_already_success_guard from @already_success_guard_sql;
execute stmt_already_success_guard;
deallocate prepare stmt_already_success_guard;

insert into tb_ai_taste_manual_replay_log (
    run_token,
    from_event_id,
    to_event_id,
    allow_duplicate_yn,
    status,
    source_total_count,
    source_valid_count,
    requested_by
) values (
    @manual_run_token,
    @replay_from_id,
    @replay_to_id,
    @manual_allow_duplicate_yn,
    'RUNNING',
    @manual_source_total_count,
    @manual_source_valid_count,
    @manual_requested_by
);

-- 지정한 event id 범위만 수동 재반영한다(워터마크 갱신 없음).
insert into tb_user_taste_factor_score (
    user_id,
    factor_type,
    factor_key,
    score,
    signal_count,
    last_event_date,
    created_date,
    updated_date
)
select s.user_id
     , s.factor_type
     , s.factor_key
     , sum(s.signal_score) as score
     , count(1) as signal_count
     , max(s.created_date) as last_event_date
     , now() as created_date
     , now() as updated_date
  from (
        select f.user_id
             , f.factor_type
             , f.factor_key
             , cast(f.signal_score as decimal(18,6)) as signal_score
             , f.created_date
          from tb_user_ai_signal_event_factor f
         where f.event_id >= @replay_from_id
           and f.event_id <= @replay_to_id
        union all
        select e.user_id
             , json_unquote(json_extract(e.event_payload, '$.factor_type')) as factor_type
             , json_unquote(json_extract(e.event_payload, '$.factor_key')) as factor_key
             , coalesce(
                    cast(trim(json_unquote(json_extract(e.event_payload, '$.signal_score'))) as decimal(18,6)),
                    0
               ) as signal_score
             , e.created_date
          from tb_user_ai_signal_event e
         where e.id >= @replay_from_id
           and e.id <= @replay_to_id
           and json_extract(e.event_payload, '$.factor_type') is not null
           and json_extract(e.event_payload, '$.factor_key') is not null
           and nullif(json_unquote(json_extract(e.event_payload, '$.factor_type')), '') is not null
           and nullif(json_unquote(json_extract(e.event_payload, '$.factor_key')), '') is not null
           and trim(json_unquote(json_extract(e.event_payload, '$.signal_score'))) regexp '^-?[0-9]+(\\.[0-9]+)?$'
           and not exists (
                select 1
                  from tb_user_ai_signal_event_factor fx
                 where fx.event_id = e.id
           )
  ) s
 group by s.user_id
        , s.factor_type
        , s.factor_key
on duplicate key update
    score = coalesce(score, 0) + values(score),
    signal_count = coalesce(signal_count, 0) + values(signal_count),
    last_event_date = greatest(coalesce(last_event_date, '1970-01-01 00:00:00'), values(last_event_date)),
    updated_date = now()
;

set @upsert_affected_rows = row_count();

update tb_ai_taste_manual_replay_log
   set status = 'SUCCESS'
     , error_message = null
     , updated_date = now()
 where run_token = @manual_run_token
   and status = 'RUNNING'
;

select @upsert_affected_rows as upsert_affected_rows;

commit;

select release_lock(@job_lock_name);
