#!/bin/bash
set -euo pipefail

EXPECTED_DEPLOYMENT_ID="${1:-}"
SERVICE_NAME=likenovel-api-dev.service
CURRENT_LINK=/home/ln-admin/likenovel/api-dev
RELEASE_BASE=/home/ln-admin/likenovel/releases/api-dev
PID_FILE=/home/ln-admin/likenovel/api-dev/gunicorn.pid
HEALTH_URL=http://10.0.100.110:3011/health

failures=0

note() {
  echo "[verify_backend_dev_deploy] $*"
}

fail() {
  echo "[verify_backend_dev_deploy] FAIL: $*" >&2
  failures=$((failures + 1))
}

require_live_pid() {
  local pid="$1"
  local label="$2"

  if [ -z "$pid" ] || [ "$pid" = "0" ]; then
    fail "$label pid is empty or zero"
    return 1
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    fail "$label pid is not live: $pid"
    return 1
  fi

  note "$label pid live: $pid"
  return 0
}

if [[ ! "$EXPECTED_DEPLOYMENT_ID" =~ ^d-[A-Za-z0-9]+$ ]]; then
  echo "[verify_backend_dev_deploy] invalid deployment id: $EXPECTED_DEPLOYMENT_ID" >&2
  exit 2
fi

note "checking active release"
active_release="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
case "$active_release" in
  "$RELEASE_BASE"/*-"$EXPECTED_DEPLOYMENT_ID")
    note "active release matches deployment: $active_release"
    ;;
  *)
    fail "active release does not match deployment $EXPECTED_DEPLOYMENT_ID: $active_release"
    ;;
esac

note "checking systemd service state"
systemctl show "$SERVICE_NAME" \
  --property=ActiveState,SubState,MainPID,Result,NRestarts,ExecMainStatus,ExecMainStartTimestamp \
  || fail "cannot read $SERVICE_NAME state"

active_state="$(systemctl show "$SERVICE_NAME" --property=ActiveState --value 2>/dev/null || true)"
sub_state="$(systemctl show "$SERVICE_NAME" --property=SubState --value 2>/dev/null || true)"
main_pid="$(systemctl show "$SERVICE_NAME" --property=MainPID --value 2>/dev/null || true)"

if [ "$active_state" != "active" ]; then
  fail "$SERVICE_NAME ActiveState is $active_state"
fi
if [ "$sub_state" != "running" ]; then
  fail "$SERVICE_NAME SubState is $sub_state"
fi
require_live_pid "$main_pid" "$SERVICE_NAME MainPID" || true

note "checking MainPID release ownership"
main_pid_cwd="$(readlink -f "/proc/$main_pid/cwd" 2>/dev/null || true)"
if [ "$main_pid_cwd" != "$active_release" ]; then
  fail "$SERVICE_NAME MainPID cwd $main_pid_cwd does not match active release $active_release"
fi

note "checking gunicorn pidfile"
if [ ! -f "$PID_FILE" ]; then
  fail "missing file: $PID_FILE"
else
  pidfile_pid="$(tr -d '[:space:]' < "$PID_FILE")"
  require_live_pid "$pidfile_pid" "gunicorn pidfile" || true
  if [ -n "$main_pid" ] && [ "$main_pid" != "0" ] && [ "$pidfile_pid" != "$main_pid" ]; then
    fail "pidfile pid $pidfile_pid does not match systemd MainPID $main_pid"
  fi
fi

note "checking port listener"
listener="$(ss -ltnp | grep -F "10.0.100.110:3011" || true)"
if [ -z "$listener" ]; then
  fail "10.0.100.110:3011 listener missing"
else
  echo "$listener"
  case "$listener" in
    *"pid=$main_pid,"*) ;;
    *) fail "10.0.100.110:3011 listener is not owned by MainPID $main_pid" ;;
  esac
fi

note "checking health endpoint"
health_status="$(curl -sS --max-time 10 --output /dev/null --write-out '%{http_code}' "$HEALTH_URL" || true)"
if [[ "$health_status" != 2* ]]; then
  fail "$HEALTH_URL returned HTTP $health_status"
fi

if [ "$failures" -gt 0 ]; then
  note "failed checks: $failures"
  exit 1
fi

note "dev backend runtime readback passed"
