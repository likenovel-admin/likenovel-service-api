#!/bin/bash

# 작품 AI DNA 메타데이터 추출 배치
# - Claude API로 작품 본문(1~10화)을 분석하여 7축 DNA 추출
# - 미분석/10화 미만 작품 자동 갱신
# - 매일 03:00 실행 (cron_job.sh)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JOB_FILE_ID="ai_dna_extract_daily_batch.sh"

LOCK_DIR="/tmp/ai-dna-extract-daily-batch.lock"

# 동시실행 방지 락
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[WARN] ai_dna_extract_daily_batch already running ($LOCK_DIR exists), skipping." 1>&2
  exit 0
fi

# PID 1에서 환경변수 로딩 (cron_env.sh가 DB만 로드하므로 ANTHROPIC 키도 가져옴)
if [ -r /proc/1/environ ]; then
  while IFS='=' read -r key value; do
    case "$key" in
      ANTHROPIC_API_KEY|ANTHROPIC_MODEL|AI_METADATA_MAX_TOKENS)
        export "$key=$value"
        ;;
    esac
  done < <(tr '\0' '\n' < /proc/1/environ)
fi

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

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "[ERROR] Missing ANTHROPIC_API_KEY env for batch." 1>&2
  exit 1
fi

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
  if [ "$JOB_MARKED_RUNNING" -eq 1 ] && [ "$exit_code" -ne 0 ]; then
    mark_job_failed_if_needed
  fi
  rm -rf "$LOCK_DIR"
  exit "$exit_code"
}
trap cleanup_on_exit EXIT

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting AI DNA extract batch..."

ensure_job_started
JOB_MARKED_RUNNING=1

python3 "${SCRIPT_DIR}/extract_product_dna.py" --all
rc=$?
if [ $rc -ne 0 ]; then
  echo "[ERROR] AI DNA extract batch failed (exit=$rc)." 1>&2
  exit $rc
fi

mark_job_success

echo "[$(date '+%Y-%m-%d %H:%M:%S')] AI DNA extract batch completed."

exit 0
