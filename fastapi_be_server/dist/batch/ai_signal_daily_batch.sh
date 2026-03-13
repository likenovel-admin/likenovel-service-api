#!/bin/bash

# 배치 스크립트 공통 DB 접속 설정(Defensive)
# - 민감정보(DB 계정/비밀번호)는 절대 하드코딩하지 않고 환경변수로만 주입합니다.
# - env가 누락되면 조용히 실패하지 않고 명확한 에러로 종료합니다.
set -uo pipefail

LOCK_DIR="/tmp/ai-signal-daily-batch.lock"
LOCK_PID_FILE="$LOCK_DIR/pid"
MAX_LOCK_AGE_SECONDS="${MAX_LOCK_AGE_SECONDS:-21600}"
HEARTBEAT_INTERVAL_SECONDS="${HEARTBEAT_INTERVAL_SECONDS:-30}"

# 동시실행 방지 락 (cron + 수동 실행 경합 방어)
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  STALE_LOCK=0
  NOW_TS="$(date +%s)"
  LOCK_TS="$(stat -c %Y "$LOCK_DIR" 2>/dev/null || echo 0)"

  if [ -f "$LOCK_PID_FILE" ]; then
    EXISTING_PID="$(cat "$LOCK_PID_FILE" 2>/dev/null || true)"
    if ! [[ "$EXISTING_PID" =~ ^[0-9]+$ ]] || ! kill -0 "$EXISTING_PID" 2>/dev/null; then
      STALE_LOCK=1
    fi
  else
    if [ "$LOCK_TS" -gt 0 ] && [ $((NOW_TS - LOCK_TS)) -gt "$MAX_LOCK_AGE_SECONDS" ]; then
      STALE_LOCK=1
    fi
  fi

  if [ "$STALE_LOCK" -eq 1 ]; then
    echo "[WARN] stale lock detected. removing $LOCK_DIR and retrying lock acquisition." 1>&2
    rm -rf "$LOCK_DIR"
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
      echo "[ERROR] failed to reacquire lock after stale lock cleanup: $LOCK_DIR" 1>&2
      exit 1
    fi
  else
    echo "[ERROR] ai_signal_daily_batch already running ($LOCK_DIR exists)." 1>&2
    exit 1
  fi
fi
echo "$$" > "$LOCK_PID_FILE"
trap 'rm -rf "$LOCK_DIR"' EXIT

DB_HOST="${DB_HOST:-mysql}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-}"
DB_PW="${DB_PW:-}"
DB_NAME="${DB_NAME:-likenovel}"

# SSL: MariaDB(--skip-ssl) vs MySQL 8.0+(--ssl-mode=DISABLED)
if [ -z "${MYSQL_SSL_OPT:-}" ]; then
  if mysql --version 2>&1 | grep -qi mariadb; then MYSQL_SSL_OPT="--skip-ssl"; else MYSQL_SSL_OPT="--ssl-mode=DISABLED"; fi
fi
IN_PROGRESS_STALE_MINUTES="${IN_PROGRESS_STALE_MINUTES:-${IN_PROGRESS_GUARD_MINUTES:-60}}"
HEARTBEAT_EVERY_LOOPS="${HEARTBEAT_EVERY_LOOPS:-20}"
MAX_PURGE_LOOPS="${MAX_PURGE_LOOPS:-10000}"

if [ -z "$DB_USER" ] || [ -z "$DB_PW" ]; then
  echo "[ERROR] Missing DB_USER or DB_PW env for batch." 1>&2
  exit 1
fi

if ! [[ "$IN_PROGRESS_STALE_MINUTES" =~ ^[0-9]+$ ]] || [ "$IN_PROGRESS_STALE_MINUTES" -lt 1 ]; then
  echo "[ERROR] IN_PROGRESS_STALE_MINUTES must be a positive integer." 1>&2
  exit 1
fi

if ! [[ "$HEARTBEAT_EVERY_LOOPS" =~ ^[0-9]+$ ]] || [ "$HEARTBEAT_EVERY_LOOPS" -lt 1 ]; then
  echo "[ERROR] HEARTBEAT_EVERY_LOOPS must be a positive integer." 1>&2
  exit 1
fi

if ! [[ "$HEARTBEAT_INTERVAL_SECONDS" =~ ^[0-9]+$ ]] || [ "$HEARTBEAT_INTERVAL_SECONDS" -lt 1 ]; then
  echo "[ERROR] HEARTBEAT_INTERVAL_SECONDS must be a positive integer." 1>&2
  exit 1
fi

if ! [[ "$MAX_PURGE_LOOPS" =~ ^[0-9]+$ ]] || [ "$MAX_PURGE_LOOPS" -lt 1 ]; then
  echo "[ERROR] MAX_PURGE_LOOPS must be a positive integer." 1>&2
  exit 1
fi

MYSQL_CMD=(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" "$DB_NAME" --default-character-set=utf8mb4 $MYSQL_SSL_OPT)
HEARTBEAT_WORKER_PID=""
BATCH_RUN_TOKEN=$(( (RANDOM << 16) | RANDOM ))

mark_job_failed_if_needed() {
  MYSQL_PWD="$DB_PW" "${MYSQL_CMD[@]}" -e "
    UPDATE tb_cms_batch_job_process
       SET completed_yn = 'F'
         , updated_date = NOW()
         , updated_id = ${BATCH_RUN_TOKEN}
     WHERE id = (
       SELECT z.id
         FROM (
           SELECT id
             FROM tb_cms_batch_job_process
            WHERE job_file_id = 'ai_signal_daily_batch.sh'
              AND completed_yn = 'N'
              AND updated_id = ${BATCH_RUN_TOKEN}
            ORDER BY updated_date DESC, id DESC
            LIMIT 1
         ) z
     )
       AND completed_yn = 'N'
       AND updated_id = ${BATCH_RUN_TOKEN};
  " >/dev/null 2>&1 || true
}

heartbeat_job_running() {
  MYSQL_PWD="$DB_PW" "${MYSQL_CMD[@]}" -e "
    UPDATE tb_cms_batch_job_process
       SET updated_date = NOW()
         , updated_id = ${BATCH_RUN_TOKEN}
     WHERE id = (
       SELECT z.id
         FROM (
           SELECT id
             FROM tb_cms_batch_job_process
            WHERE job_file_id = 'ai_signal_daily_batch.sh'
              AND completed_yn = 'N'
              AND updated_id = ${BATCH_RUN_TOKEN}
            ORDER BY updated_date DESC, id DESC
            LIMIT 1
         ) z
     )
       AND completed_yn = 'N'
       AND updated_id = ${BATCH_RUN_TOKEN};
  " >/dev/null
}

start_heartbeat_worker() {
  (
    while true; do
      sleep "$HEARTBEAT_INTERVAL_SECONDS"
      heartbeat_job_running || true
    done
  ) &
  HEARTBEAT_WORKER_PID=$!
}

stop_heartbeat_worker() {
  if [ -n "${HEARTBEAT_WORKER_PID}" ] && kill -0 "$HEARTBEAT_WORKER_PID" 2>/dev/null; then
    kill "$HEARTBEAT_WORKER_PID" 2>/dev/null || true
    wait "$HEARTBEAT_WORKER_PID" 2>/dev/null || true
  fi
  HEARTBEAT_WORKER_PID=""
}

cleanup_on_exit() {
  local exit_code=$?
  stop_heartbeat_worker
  if [ "$exit_code" -ne 0 ]; then
    mark_job_failed_if_needed
  fi
  rm -rf "$LOCK_DIR"
  exit "$exit_code"
}
trap cleanup_on_exit EXIT

# 1) 일/주 집계 (SQL)
MYSQL_PWD="$DB_PW" "${MYSQL_CMD[@]}" \
  --init-command="SET @batch_run_token=${BATCH_RUN_TOKEN}; SET @in_progress_stale_minutes=${IN_PROGRESS_STALE_MINUTES};" \
  < /app/dist/batch/ai_signal_daily_batch.sql

# 2) retention 청크 삭제 (CREATE PROCEDURE 권한 불필요)
PURGE_DATE=$(MYSQL_PWD="$DB_PW" "${MYSQL_CMD[@]}" -N -e "
  SELECT DATE_SUB(CURDATE(), INTERVAL GREATEST(COALESCE(
    (SELECT retention_days FROM tb_ai_signal_retention_policy
      WHERE enabled_yn='Y' ORDER BY id DESC LIMIT 1), 90), 1) DAY)
")

if [ -z "$PURGE_DATE" ]; then
  echo "[WARN] Could not determine purge date, skipping purge."
  exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Purging events before $PURGE_DATE in 5000-row chunks..."
heartbeat_job_running
start_heartbeat_worker
LAST_HEARTBEAT_TS="$(date +%s)"

DELETED=1
TOTAL_DELETED=0
LOOP_COUNT=0
while [ "$DELETED" -gt 0 ]; do
  LOOP_COUNT=$((LOOP_COUNT + 1))
  if [ "$LOOP_COUNT" -gt "$MAX_PURGE_LOOPS" ]; then
    echo "[ERROR] Purge loop exceeded MAX_PURGE_LOOPS=${MAX_PURGE_LOOPS}" 1>&2
    exit 1
  fi

  DELETED=$(MYSQL_PWD="$DB_PW" "${MYSQL_CMD[@]}" -N -e "
    DELETE FROM tb_user_ai_signal_event
     WHERE created_date < '$PURGE_DATE'
     LIMIT 5000;
    SELECT ROW_COUNT();
  ")
  TOTAL_DELETED=$((TOTAL_DELETED + DELETED))

  NOW_TS="$(date +%s)"
  if [ $((LOOP_COUNT % HEARTBEAT_EVERY_LOOPS)) -eq 0 ] || [ $((NOW_TS - LAST_HEARTBEAT_TS)) -ge "$HEARTBEAT_INTERVAL_SECONDS" ]; then
    heartbeat_job_running
    LAST_HEARTBEAT_TS="$NOW_TS"
  fi

  if [ "$DELETED" -gt 0 ]; then
    sleep 0.05
  fi
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Purge complete: ${TOTAL_DELETED} rows deleted."

# 3) purge 성공 후에만 정책/상태 기록
TARGET_DATE=$(date -d 'yesterday' '+%Y-%m-%d')

MYSQL_PWD="$DB_PW" "${MYSQL_CMD[@]}" -e "
  START TRANSACTION;

  UPDATE tb_ai_signal_retention_policy
     SET last_rollup_date = '$TARGET_DATE'
       , last_purge_before_date = '$PURGE_DATE'
       , updated_date = NOW()
   WHERE enabled_yn = 'Y';

  UPDATE tb_cms_batch_job_process
     SET completed_yn = 'Y'
       , last_processed_date = NOW()
       , created_id = 0
       , updated_id = 0
   WHERE id = (
     SELECT z.id
       FROM (
         SELECT id
           FROM tb_cms_batch_job_process
          WHERE job_file_id = 'ai_signal_daily_batch.sh'
            AND completed_yn = 'N'
            AND updated_id = ${BATCH_RUN_TOKEN}
          ORDER BY updated_date DESC, id DESC
          LIMIT 1
       ) z
   )
     AND completed_yn = 'N'
     AND updated_id = ${BATCH_RUN_TOKEN};

  COMMIT;
"

exit 0
