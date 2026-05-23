#!/bin/bash
set -euo pipefail

SERVICE_NAME=likenovel-api.service
APP_DIR=/home/ln-admin/likenovel/api
PID_FILE=/home/ln-admin/likenovel/api/gunicorn.pid
AI_READER_WORKER_PID=/home/ln-admin/likenovel/api/ai_reader_worker.pid
AI_READER_WORKER_LOG=/home/ln-admin/likenovel/api/logs/data/ai_reader_worker.log
HEALTH_URL=http://10.0.100.110:3010/health
AI_READER_WORKER_LOG_MAX_AGE_SECONDS=300

# expected runtime output:
# sqlalchemy==2.0.41
# pymysql==1.1.1
# aiomysql==0.2.0

failures=0

note() {
  echo "[verify_backend_prod_deploy] $*"
}

fail() {
  echo "[verify_backend_prod_deploy] FAIL: $*" >&2
  failures=$((failures + 1))
}

require_file() {
  local path="$1"
  if [ ! -f "$path" ]; then
    fail "missing file: $path"
    return 1
  fi
  return 0
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

note "checking systemd service state"
systemctl show "$SERVICE_NAME" \
  --property=ActiveState,SubState,MainPID,Result,NRestarts,ExecMainStatus,ExecMainStartTimestamp

active_state="$(systemctl show "$SERVICE_NAME" --property=ActiveState --value)"
sub_state="$(systemctl show "$SERVICE_NAME" --property=SubState --value)"
main_pid="$(systemctl show "$SERVICE_NAME" --property=MainPID --value)"

if [ "$active_state" != "active" ]; then
  fail "$SERVICE_NAME ActiveState is $active_state"
fi
if [ "$sub_state" != "running" ]; then
  fail "$SERVICE_NAME SubState is $sub_state"
fi
require_live_pid "$main_pid" "$SERVICE_NAME MainPID" || true

note "checking gunicorn pidfile"
if require_file "$PID_FILE"; then
  pidfile_pid="$(tr -d '[:space:]' < "$PID_FILE")"
  require_live_pid "$pidfile_pid" "gunicorn pidfile" || true
  if [ -n "$main_pid" ] && [ "$main_pid" != "0" ] && [ "$pidfile_pid" != "$main_pid" ]; then
    fail "pidfile pid $pidfile_pid does not match systemd MainPID $main_pid"
  fi
fi

note "checking port listener"
ss -ltnp | grep -F "10.0.100.110:3010" || fail "10.0.100.110:3010 listener missing"

note "checking health endpoint"
curl -fsS "$HEALTH_URL" >/dev/null || fail "$HEALTH_URL failed"

note "checking AI reader worker pid"
if require_file "$AI_READER_WORKER_PID"; then
  worker_pid="$(tr -d '[:space:]' < "$AI_READER_WORKER_PID")"
  require_live_pid "$worker_pid" "ai_reader_worker.pid" || true
fi

note "checking AI reader worker fresh cycle log"
if require_file "$AI_READER_WORKER_LOG"; then
  grep -F "ai reader worker cycle completed" "$AI_READER_WORKER_LOG" >/dev/null \
    || fail "ai reader worker cycle completed log missing"
  now_epoch="$(date +%s)"
  log_mtime="$(stat -c %Y "$AI_READER_WORKER_LOG")"
  log_age="$((now_epoch - log_mtime))"
  note "AI reader worker log age seconds: $log_age"
  if [ "$log_age" -gt "$AI_READER_WORKER_LOG_MAX_AGE_SECONDS" ]; then
    fail "AI reader worker log is stale: ${log_age}s"
  fi
fi

note "checking prod venv dependency versions"
"$APP_DIR/.venv/bin/python" - <<'PY' || fail "prod venv dependency version check failed"
from importlib.metadata import version

expected = {
    "sqlalchemy": "2.0.41",
    "pymysql": "1.1.1",
    "aiomysql": "0.2.0",
}
actual = {
    name: version(name)
    for name in expected
}

for name, version in actual.items():
    print(f"{name}=={version}")
    if version != expected[name]:
        raise SystemExit(f"{name} expected {expected[name]}, got {version}")
PY

if [ "$failures" -gt 0 ]; then
  note "failed checks: $failures"
  exit 1
fi

note "prod backend runtime readback passed"
