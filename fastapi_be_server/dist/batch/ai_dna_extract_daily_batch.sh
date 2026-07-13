#!/bin/bash

# 작품 AI DNA 메타데이터 추출 배치
# - Claude API로 작품 본문(1~10화)을 분석하여 7축 DNA 추출
# - 미분석/10화 미만 작품 자동 갱신
# - 매일 03:00 실행 (cron_job.sh)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JOB_FILE_ID="ai_dna_extract_daily_batch.sh"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/batch_timestamp_logging.sh"
enable_timestamped_logging

BATCH_NAME="ai_dna_extract_daily_batch"
RUN_STARTED_AT="$(date +%s)"

LOCK_DIR="/tmp/ai-dna-extract-daily-batch.lock"
LOCK_PID_FILE="$LOCK_DIR/pid"
MAX_LOCK_AGE_SECONDS="${MAX_LOCK_AGE_SECONDS:-21600}"

# 동시실행 방지 락
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  STALE_LOCK=0
  NOW_TS="$(date +%s)"
  LOCK_TS="$(stat -c %Y "$LOCK_DIR" 2>/dev/null || echo 0)"

  if [ -f "$LOCK_PID_FILE" ]; then
    EXISTING_PID="$(cat "$LOCK_PID_FILE" 2>/dev/null || true)"
    if ! [[ "$EXISTING_PID" =~ ^[0-9]+$ ]] || ! kill -0 "$EXISTING_PID" 2>/dev/null; then
      STALE_LOCK=1
    fi
  elif [ "$LOCK_TS" -gt 0 ] && [ $((NOW_TS - LOCK_TS)) -gt "$MAX_LOCK_AGE_SECONDS" ]; then
    STALE_LOCK=1
  fi

  if [ "$STALE_LOCK" -eq 1 ]; then
    echo "[WARN] stale lock detected. removing $LOCK_DIR and retrying lock acquisition." 1>&2
    rm -rf "$LOCK_DIR"
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
      echo "[ERROR] failed to reacquire lock after stale lock cleanup: $LOCK_DIR" 1>&2
      exit 1
    fi
  else
    echo "[WARN] ai_dna_extract_daily_batch already running ($LOCK_DIR exists), skipping." 1>&2
    exit 0
  fi
fi
echo "$$" > "$LOCK_PID_FILE"

# PID 1에서 환경변수 로딩 (cron_env.sh 누락/cron 직접 실행 fallback)
if [ -r /proc/1/environ ]; then
  while IFS='=' read -r key value; do
    case "$key" in
      ANTHROPIC_API_KEY|ANTHROPIC_MODEL|OPENROUTER_API_KEY|OPENROUTER_BASE_URL|AI_DNA_PROVIDER|AI_DNA_OPENROUTER_MODEL|AI_DNA_OPENROUTER_PROVIDER_ONLY|AI_DNA_RESPONSE_FORMAT|AI_DNA_TIMEOUT_SECONDS|AI_METADATA_MAX_TOKENS|AI_METADATA_PIPELINE_VERSION|AI_METADATA_FAILED_RETRY_COOLDOWN_DAYS|AI_METADATA_INCOMPLETE_RETRY_COOLDOWN_DAYS)
        export "$key=$value"
        ;;
    esac
  done < <(tr '\0' '\n' < /proc/1/environ)
fi

AI_DNA_PROVIDER="${AI_DNA_PROVIDER:-anthropic}"
AI_DNA_PROVIDER="${AI_DNA_PROVIDER//[$'\t\r\n ']/}"
AI_DNA_PROVIDER="${AI_DNA_PROVIDER,,}"

DB_HOST="${DB_HOST:-mysql}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-}"
DB_PW="${DB_PW:-}"
DB_NAME="${DB_NAME:-likenovel}"

# DB 환경변수를 Python 스크립트용으로 매핑
export BATCH_DB_HOST="$DB_HOST"
export BATCH_DB_PORT="$DB_PORT"
export BATCH_DB_USER="$DB_USER"
export BATCH_DB_PASSWORD="$DB_PW"
export BATCH_DB_NAME="$DB_NAME"

# SSL: MariaDB(--skip-ssl) vs MySQL 8.0+(--ssl-mode=DISABLED)
if [ -z "${MYSQL_SSL_OPT:-}" ]; then
  if mysql --version 2>&1 | grep -qi mariadb; then MYSQL_SSL_OPT="--skip-ssl"; else MYSQL_SSL_OPT="--ssl-mode=DISABLED"; fi
fi

if [ -z "$BATCH_DB_USER" ] || [ -z "$BATCH_DB_PASSWORD" ]; then
  echo "[ERROR] Missing DB_USER or DB_PW env for batch." 1>&2
  exit 1
fi

case "$AI_DNA_PROVIDER" in
  anthropic)
    AI_DNA_SELECTED_MODEL="${ANTHROPIC_MODEL:-unknown}"
    if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
      echo "[ERROR] Missing ANTHROPIC_API_KEY env for AI_DNA_PROVIDER=anthropic." 1>&2
      exit 1
    fi
    ;;
  openrouter)
    AI_DNA_SELECTED_MODEL="${AI_DNA_OPENROUTER_MODEL:-unknown}"
    if [ -z "${OPENROUTER_API_KEY:-}" ]; then
      echo "[ERROR] Missing OPENROUTER_API_KEY env for AI_DNA_PROVIDER=openrouter." 1>&2
      exit 1
    fi
    ;;
  *)
    echo "[ERROR] Unsupported AI_DNA_PROVIDER: $AI_DNA_PROVIDER" 1>&2
    exit 1
    ;;
esac

echo "[INFO] AI DNA provider=$AI_DNA_PROVIDER model=$AI_DNA_SELECTED_MODEL"

MYSQL_CMD=(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PW" "$DB_NAME" --default-character-set=utf8mb4)
if [ -n "${MYSQL_SSL_OPT:-}" ]; then
  MYSQL_CMD+=("$MYSQL_SSL_OPT")
fi

JOB_MARKED_RUNNING=0

ensure_job_started() {
  "${MYSQL_CMD[@]}" <<SQL
INSERT IGNORE INTO tb_cms_batch_job_process (
    job_file_id,
    job_group_id,
    job_order,
    completed_yn,
    job_list,
    created_id,
    updated_id
)
SELECT '${JOB_FILE_ID}',
       0,
       0,
       'N',
       '${JOB_FILE_ID}',
       0,
       0
  FROM dual
 WHERE NOT EXISTS (
    SELECT 1
      FROM tb_cms_batch_job_process x
     WHERE x.job_file_id = '${JOB_FILE_ID}'
 );

UPDATE tb_cms_batch_job_process
   SET completed_yn = 'N',
       updated_date = NOW(),
       created_id = 0,
       updated_id = 0
 WHERE job_file_id = '${JOB_FILE_ID}';
SQL
}

mark_job_success() {
  "${MYSQL_CMD[@]}" <<SQL
UPDATE tb_cms_batch_job_process
   SET completed_yn = 'Y',
       last_processed_date = NOW(),
       updated_date = NOW(),
       created_id = 0,
       updated_id = 0
 WHERE job_file_id = '${JOB_FILE_ID}';
SQL
}

mark_job_failed_if_needed() {
  "${MYSQL_CMD[@]}" <<SQL >/dev/null 2>&1
UPDATE tb_cms_batch_job_process
   SET completed_yn = 'F',
       updated_date = NOW(),
       created_id = 0,
       updated_id = 0
 WHERE job_file_id = '${JOB_FILE_ID}'
   AND completed_yn = 'N';
SQL
}

cleanup_on_exit() {
  local exit_code=$?
  local duration=$(( $(date +%s) - RUN_STARTED_AT ))
  if [ "$JOB_MARKED_RUNNING" -eq 1 ] && [ "$exit_code" -ne 0 ]; then
    mark_job_failed_if_needed
  fi
  rm -rf "$LOCK_DIR"
  echo "[INFO] ${BATCH_NAME} completed with exit=${exit_code} in ${duration}s"
  exit "$exit_code"
}
trap cleanup_on_exit EXIT

echo "[INFO] ${BATCH_NAME} started"

ensure_job_started
JOB_MARKED_RUNNING=1

python3 "${SCRIPT_DIR}/extract_product_dna.py" --all
rc=$?
if [ $rc -ne 0 ]; then
  echo "[ERROR] AI DNA extract batch failed (exit=$rc)." 1>&2
  exit $rc
fi

mark_job_success

echo "[INFO] ${BATCH_NAME} work completed."

exit 0
