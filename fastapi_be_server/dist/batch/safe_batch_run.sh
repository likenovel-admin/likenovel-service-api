#!/bin/bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "${SCRIPT_DIR}/cron_env.sh" ]; then
  # shellcheck source=/dev/null
  source "${SCRIPT_DIR}/cron_env.sh"
fi

LOCK_DIR="/tmp/likenovel-safe-batch-run.lock"

usage() {
  cat <<'EOF'
Usage:
  bash safe_batch_run.sh <mode> [--force-cycle] [--no-lock] [--ai-strict]

Modes:
  hourly   : ai_taste_hourly + service_reset_hourly + summary_hourly
  daily    : ai_signal_daily + ai_engagement_metrics_daily + main_rule_slot_snapshot + summary_daily + service_reset_daily + partner_report_daily + statistics_aggregation_daily
  weekly   : service_reset_weekly (runs only on Monday unless --force-cycle)
  monthly  : partner_report_monthly (runs only on day 1 unless --force-cycle)
  all      : hourly + daily + weekly + monthly (weekly/monthly still date-guarded)

Options:
  --force-cycle  Run weekly/monthly regardless of calendar day.
  --no-lock      Skip process lock (not recommended).
  --ai-strict    Fail entire chain if AI batch scripts fail (default: soft-fail).
EOF
}

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

run_script() {
  local script_name="$1"
  local script_path="${SCRIPT_DIR}/${script_name}"
  if [ ! -f "${script_path}" ]; then
    log "ERROR: Missing script: ${script_path}"
    exit 1
  fi
  log "START ${script_name}"
  bash "${script_path}"
  log "DONE  ${script_name}"
}

run_ai_script() {
  local script_name="$1"
  local script_path="${SCRIPT_DIR}/${script_name}"

  if [ ! -f "${script_path}" ]; then
    if [ "${AI_SOFT_FAIL}" -eq 1 ]; then
      log "WARN: AI soft-fail enabled, missing script: ${script_path}"
      return 0
    fi
    log "ERROR: Missing script: ${script_path}"
    exit 1
  fi

  log "START ${script_name}"
  if bash "${script_path}"; then
    log "DONE  ${script_name}"
    return 0
  fi

  if [ "${AI_SOFT_FAIL}" -eq 1 ]; then
    log "WARN: AI soft-fail enabled, continuing after failure: ${script_name}"
    return 0
  fi

  log "ERROR: AI batch failed: ${script_name}"
  return 1
}

acquire_lock() {
  if mkdir "${LOCK_DIR}" 2>/dev/null; then
    trap 'rm -rf "${LOCK_DIR}"' EXIT
    return 0
  fi
  log "ERROR: another safe_batch_run process is already running (${LOCK_DIR})"
  exit 1
}

is_monday() {
  [ "$(date +%u)" = "1" ]
}

is_first_day_of_month() {
  [ "$(date +%d)" = "01" ]
}

FORCE_CYCLE=0
USE_LOCK=1
AI_SOFT_FAIL=1
MODE=""

for arg in "$@"; do
  case "$arg" in
    hourly|daily|weekly|monthly|all)
      MODE="$arg"
      ;;
    --force-cycle)
      FORCE_CYCLE=1
      ;;
    --no-lock)
      USE_LOCK=0
      ;;
    --ai-strict)
      AI_SOFT_FAIL=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      log "ERROR: unknown option or mode: $arg"
      usage
      exit 1
      ;;
  esac
done

if [ -z "${MODE}" ]; then
  usage
  exit 1
fi

if [ "${USE_LOCK}" -eq 1 ]; then
  acquire_lock
fi

run_hourly() {
  run_ai_script "ai_taste_hourly_batch.sh"
  run_script "service_reset_hourly_batch.sh"
  run_script "summary_hourly_batch.sh"
}

run_daily() {
  run_script "service_reset_daily_batch.sh"
  run_script "summary_daily_batch.sh"
  run_ai_script "ai_signal_daily_batch.sh"
  run_ai_script "ai_product_detail_funnel_daily_batch.sh"
  run_ai_script "ai_engagement_metrics_daily_batch.sh"
  run_ai_script "main_rule_slot_snapshot_batch.sh"
  run_script "partner_report_daily_batch.sh"
  run_script "statistics_aggregation_daily_batch.sh"
}

run_weekly() {
  if [ "${FORCE_CYCLE}" -eq 1 ] || is_monday; then
    run_script "service_reset_weekly_batch.sh"
  else
    log "SKIP service_reset_weekly_batch.sh (today is not Monday, use --force-cycle to override)"
  fi
}

run_monthly() {
  if [ "${FORCE_CYCLE}" -eq 1 ] || is_first_day_of_month; then
    run_script "partner_report_monthly_batch.sh"
  else
    log "SKIP partner_report_monthly_batch.sh (today is not day 1, use --force-cycle to override)"
  fi
}

log "SAFE BATCH RUN START mode=${MODE} force_cycle=${FORCE_CYCLE} lock=${USE_LOCK} ai_soft_fail=${AI_SOFT_FAIL}"

case "${MODE}" in
  hourly)
    run_hourly
    ;;
  daily)
    run_daily
    ;;
  weekly)
    run_weekly
    ;;
  monthly)
    run_monthly
    ;;
  all)
    run_hourly
    run_daily
    run_weekly
    run_monthly
    ;;
esac

log "SAFE BATCH RUN DONE mode=${MODE}"
exit 0
