#!/bin/bash

# 관리자가 미처리 이벤트 범위만 수동 재처리할 때 사용하는 스크립트
set -uo pipefail

FROM_ID=""
TO_ID=""
DRY_RUN=0
ALLOW_DUPLICATE=0
RUN_TOKEN=""

usage() {
  cat <<'EOF'
Usage:
  bash /app/dist/batch/ai_taste_manual_replay_batch.sh --from-id <event_id> --to-id <event_id> [--dry-run] [--allow-duplicate]

Options:
  --from-id   replay 시작 event id (포함)
  --to-id     replay 종료 event id (포함)
  --dry-run   대상 건수만 확인하고 실제 반영은 하지 않음
  --allow-duplicate 동일 범위 재실행 차단을 무시하고 강제 실행
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --from-id)
      if [ $# -lt 2 ]; then
        echo "[ERROR] --from-id requires a value." 1>&2
        usage
        exit 1
      fi
      FROM_ID="${2:-}"
      shift 2
      ;;
    --to-id)
      if [ $# -lt 2 ]; then
        echo "[ERROR] --to-id requires a value." 1>&2
        usage
        exit 1
      fi
      TO_ID="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --allow-duplicate)
      ALLOW_DUPLICATE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown option: $1" 1>&2
      usage
      exit 1
      ;;
  esac
done

if [ -z "$FROM_ID" ] || [ -z "$TO_ID" ]; then
  echo "[ERROR] --from-id, --to-id are required." 1>&2
  usage
  exit 1
fi

if ! [[ "$FROM_ID" =~ ^[0-9]+$ ]] || [ "$FROM_ID" -lt 1 ]; then
  echo "[ERROR] --from-id must be a positive integer." 1>&2
  exit 1
fi

if ! [[ "$TO_ID" =~ ^[0-9]+$ ]] || [ "$TO_ID" -lt 1 ]; then
  echo "[ERROR] --to-id must be a positive integer." 1>&2
  exit 1
fi

if [ "$FROM_ID" -gt "$TO_ID" ]; then
  echo "[ERROR] --from-id must be less than or equal to --to-id." 1>&2
  exit 1
fi

DB_HOST="${DB_HOST:-mysql}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-}"
DB_PW="${DB_PW:-}"
DB_NAME="${DB_NAME:-likenovel}"

# SSL: MariaDB(--skip-ssl) vs MySQL 8.0+(--ssl-mode=DISABLED)
if [ -z "${MYSQL_SSL_OPT:-}" ]; then
  if mysql --version 2>&1 | grep -qi mariadb; then MYSQL_SSL_OPT="--skip-ssl"; else MYSQL_SSL_OPT="--ssl-mode=DISABLED"; fi
fi

if [ -z "$DB_USER" ] || [ -z "$DB_PW" ]; then
  echo "[ERROR] Missing DB_USER or DB_PW env for batch." 1>&2
  exit 1
fi

MYSQL_CMD=(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" "$DB_NAME" $MYSQL_SSL_OPT)
ALLOW_DUPLICATE_YN='N'
if [ "$ALLOW_DUPLICATE" -eq 1 ]; then
  ALLOW_DUPLICATE_YN='Y'
fi

REPLAY_LOG_TABLE_EXISTS=$(MYSQL_PWD="$DB_PW" "${MYSQL_CMD[@]}" -N -e "
  SELECT COUNT(1)
    FROM information_schema.tables
   WHERE table_schema = DATABASE()
     AND table_name = 'tb_ai_taste_manual_replay_log';
")
if [ "${REPLAY_LOG_TABLE_EXISTS:-0}" -ne 1 ]; then
  echo "[ERROR] Missing table tb_ai_taste_manual_replay_log. run dist/init/51-create_ai_taste_manual_replay_log.sql first." 1>&2
  exit 1
fi

VALID_EVENT_CONDITION="
json_extract(event_payload, '$.factor_type') is not null
and json_extract(event_payload, '$.factor_key') is not null
and nullif(json_unquote(json_extract(event_payload, '$.factor_type')), '') is not null
and nullif(json_unquote(json_extract(event_payload, '$.factor_key')), '') is not null
and trim(json_unquote(json_extract(event_payload, '$.signal_score'))) regexp '^-?[0-9]+(\\\\.[0-9]+)?$'
"

STATS=$(MYSQL_PWD="$DB_PW" "${MYSQL_CMD[@]}" -N -e "
  SELECT
      COUNT(1) AS total_count,
      SUM(CASE WHEN ${VALID_EVENT_CONDITION} THEN 1 ELSE 0 END) AS valid_count,
      COALESCE(DATE_FORMAT(MIN(created_date), '%Y-%m-%dT%H:%i:%s'), '') AS min_created_date,
      COALESCE(DATE_FORMAT(MAX(created_date), '%Y-%m-%dT%H:%i:%s'), '') AS max_created_date
    FROM tb_user_ai_signal_event
   WHERE id >= ${FROM_ID}
     AND id <= ${TO_ID};
")

TOTAL_COUNT=0
VALID_COUNT=0
MIN_CREATED_DATE=""
MAX_CREATED_DATE=""
if [ -n "$STATS" ]; then
  read -r TOTAL_COUNT VALID_COUNT MIN_CREATED_DATE MAX_CREATED_DATE <<< "$STATS"
fi

echo "[INFO] replay range: id ${FROM_ID} ~ ${TO_ID}"
echo "[INFO] source events: total=${TOTAL_COUNT}, valid=${VALID_COUNT}, created_date=${MIN_CREATED_DATE}~${MAX_CREATED_DATE}"

if [ "${TOTAL_COUNT:-0}" -eq 0 ]; then
  echo "[INFO] No source events in range. nothing to do."
  exit 0
fi

if [ "${VALID_COUNT:-0}" -eq 0 ]; then
  echo "[INFO] No valid factor events in range. nothing to do."
  exit 0
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[INFO] dry-run mode. skip replay apply."
  exit 0
fi

RUN_TOKEN=$(( $(date +%s) * 1000000 + $$ ))
if ! MYSQL_PWD="$DB_PW" "${MYSQL_CMD[@]}" \
  --init-command="SET @replay_from_id=${FROM_ID}; SET @replay_to_id=${TO_ID}; SET @manual_run_token=${RUN_TOKEN}; SET @manual_allow_duplicate_yn='${ALLOW_DUPLICATE_YN}'; SET @manual_source_total_count=${TOTAL_COUNT}; SET @manual_source_valid_count=${VALID_COUNT}; SET @manual_requested_by='manual-admin';" \
  < /app/dist/batch/ai_taste_manual_replay_batch.sql; then
  MYSQL_PWD="$DB_PW" "${MYSQL_CMD[@]}" -e "
    INSERT INTO tb_ai_taste_manual_replay_log (
        run_token,
        from_event_id,
        to_event_id,
        allow_duplicate_yn,
        status,
        source_total_count,
        source_valid_count,
        requested_by,
        error_message
    ) VALUES (
        ${RUN_TOKEN},
        ${FROM_ID},
        ${TO_ID},
        '${ALLOW_DUPLICATE_YN}',
        'FAILED',
        ${TOTAL_COUNT},
        ${VALID_COUNT},
        'manual-admin',
        'manual replay failed'
    )
    ON DUPLICATE KEY UPDATE
        status = CASE WHEN status = 'SUCCESS' THEN 'SUCCESS' ELSE 'FAILED' END,
        error_message = CASE WHEN status = 'SUCCESS' THEN error_message ELSE 'manual replay failed' END,
        updated_date = NOW();
  "
  exit 1
fi

echo "[INFO] replay completed for id ${FROM_ID} ~ ${TO_ID}"
exit 0
