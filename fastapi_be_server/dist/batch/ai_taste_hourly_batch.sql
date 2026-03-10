start transaction;

-- 동일 배치 전역 직렬화(멀티 인스턴스 동시 실행 방지)
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
select 'ai_taste_hourly_batch.sh',
       0,
       0,
       'N',
       'ai_taste_hourly_batch.sh',
       0,
       0
  from dual
 where not exists (
    select 1
      from tb_cms_batch_job_process x
     where x.job_file_id = 'ai_taste_hourly_batch.sh'
 );

-- 배치 종료 시각 고정 (동일 실행 내 시간경계 일관성)
set @batch_end = now();

-- 최신 job row를 for update로 잠가 동시 실행 시 워터마크 중복 가산 방지
select a.id
     , a.last_processed_date
  into @job_id, @last_processed_date
  from tb_cms_batch_job_process a
 where a.job_file_id = 'ai_taste_hourly_batch.sh'
 order by a.updated_date desc, a.id desc
 limit 1
 for update
;

set @watermark = @last_processed_date;

-- 첫 실행(last_processed_date is null)에서만 초기 워터마크를 계산한다.
set @init_watermark_sql = if(
    @watermark is null,
    'select coalesce(min(e.created_date), @batch_end) into @watermark
       from tb_user_ai_signal_event e
      where json_extract(e.event_payload, ''$.factor_type'') is not null
        and json_extract(e.event_payload, ''$.factor_key'') is not null
        and nullif(json_unquote(json_extract(e.event_payload, ''$.factor_type'')), '''') is not null
        and nullif(json_unquote(json_extract(e.event_payload, ''$.factor_key'')), '''') is not null
        and trim(json_unquote(json_extract(e.event_payload, ''$.signal_score''))) regexp ''^-?[0-9]+(\\\\.[0-9]+)?$''',
    'select 1'
);
prepare stmt_init_watermark from @init_watermark_sql;
execute stmt_init_watermark;
deallocate prepare stmt_init_watermark;

-- 배치 시작 마킹
update tb_cms_batch_job_process a
   set a.completed_yn = 'N'
     , a.created_id = 0
     , a.updated_id = 0
 where a.id = @job_id
;

-- 이벤트 payload에서 factor_type/factor_key/signal_score를 추출해
-- 유저 취향 축 점수 테이블에 워터마크 이후 신규 이벤트만 증분 반영
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
select e.user_id
     , json_unquote(json_extract(e.event_payload, '$.factor_type')) as factor_type
     , json_unquote(json_extract(e.event_payload, '$.factor_key')) as factor_key
     , sum(
         coalesce(
             cast(trim(json_unquote(json_extract(e.event_payload, '$.signal_score'))) as decimal(18,6)),
             0
         )
       ) as score
     , count(1) as signal_count
     , max(e.created_date) as last_event_date
     , now() as created_date
     , now() as updated_date
  from tb_user_ai_signal_event e
 where e.created_date >= @watermark
   and e.created_date < @batch_end
   and json_extract(e.event_payload, '$.factor_type') is not null
   and json_extract(e.event_payload, '$.factor_key') is not null
   and nullif(json_unquote(json_extract(e.event_payload, '$.factor_type')), '') is not null
   and nullif(json_unquote(json_extract(e.event_payload, '$.factor_key')), '') is not null
   and trim(json_unquote(json_extract(e.event_payload, '$.signal_score'))) regexp '^-?[0-9]+(\\.[0-9]+)?$'
 group by e.user_id
        , json_unquote(json_extract(e.event_payload, '$.factor_type'))
        , json_unquote(json_extract(e.event_payload, '$.factor_key'))
on duplicate key update
    score = coalesce(score, 0) + values(score),
    signal_count = coalesce(signal_count, 0) + values(signal_count),
    last_event_date = greatest(coalesce(last_event_date, '1970-01-01 00:00:00'), values(last_event_date)),
    updated_date = now()
;

-- 이번 실행에서 실제 반영된 이벤트의 최대 created_date를 계산한다.
set @processed_max_created_date = (
    select max(e.created_date)
      from tb_user_ai_signal_event e
     where e.created_date >= @watermark
       and e.created_date < @batch_end
       and json_extract(e.event_payload, '$.factor_type') is not null
       and json_extract(e.event_payload, '$.factor_key') is not null
       and nullif(json_unquote(json_extract(e.event_payload, '$.factor_type')), '') is not null
       and nullif(json_unquote(json_extract(e.event_payload, '$.factor_key')), '') is not null
       and trim(json_unquote(json_extract(e.event_payload, '$.signal_score'))) regexp '^-?[0-9]+(\\.[0-9]+)?$'
);

-- 워터마크 + 완료 마킹 (트랜잭션 내에서 원자적으로)
update tb_cms_batch_job_process a
   set a.completed_yn = 'Y'
     , a.last_processed_date = coalesce(
         date_add(@processed_max_created_date, interval 1 second),
         cast(@watermark as datetime)
       )
     , a.created_id = 0
     , a.updated_id = 0
 where a.id = @job_id
;

commit;

select release_lock(@job_lock_name);
