#!/bin/bash

# 작품 AI DNA 메타데이터 추출 배치
# - Claude API로 작품 본문(1~10화)을 분석하여 7축 DNA 추출
# - 미분석/10화 미만 작품 자동 갱신
# - 매일 03:00 실행 (cron_job.sh)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LOCK_DIR="/tmp/ai-dna-extract-daily-batch.lock"

# 동시실행 방지 락
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[WARN] ai_dna_extract_daily_batch already running ($LOCK_DIR exists), skipping." 1>&2
  exit 0
fi
trap 'rm -rf "$LOCK_DIR"' EXIT

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

# DB 환경변수를 Python 스크립트용으로 매핑
export BATCH_DB_HOST="${DB_HOST:-mysql}"
export BATCH_DB_PORT="${DB_PORT:-3306}"
export BATCH_DB_USER="${DB_USER:-}"
export BATCH_DB_PASSWORD="${DB_PW:-}"
export BATCH_DB_NAME="${DB_NAME:-likenovel}"

if [ -z "$BATCH_DB_USER" ] || [ -z "$BATCH_DB_PASSWORD" ]; then
  echo "[ERROR] Missing DB_USER or DB_PW env for batch." 1>&2
  exit 1
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "[ERROR] Missing ANTHROPIC_API_KEY env for batch." 1>&2
  exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting AI DNA extract batch..."

python3 "${SCRIPT_DIR}/extract_product_dna.py" --all

echo "[$(date '+%Y-%m-%d %H:%M:%S')] AI DNA extract batch completed."

exit 0
