#!/bin/bash
set -euo pipefail

# 백엔드 서버 새로운 배포 버전으로 재기동
# 운영 시에는 서버점검 공지 후 해당 작업 권장(가장 안전한 방법)
# -HUP을 통한 무중단 재기동 방법은 상황에 따라 잠재적 문제점이 있기에 패스

sudo chown -R ln-admin:ln-admin /home/ln-admin/likenovel/api
sudo chmod -R 700 /home/ln-admin/likenovel/api

cd /home/ln-admin/likenovel/api || exit 1

SERVICE_NAME=likenovel-api.service
NEXT_VENV=.venv-next
PREV_VENV=.venv-prev
ENV_BACKUP=.env.prev
AI_READER_WORKER_LOG=./logs/data/ai_reader_worker.log
AI_READER_WORKER_PID=./ai_reader_worker.pid
REQUIRED_ENV_KEYS=(DB_USER_ID DB_USER_PW DB_IP DB_PORT)
PATH_ENV_KEYS=(ROOT_PATH FCM_SERVICE_ACCOUNT_JSON_PATH)

load_env_file() {
  local env_file="$1"
  local line key value quote

  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"

    case "$line" in
      ''|'#'*) continue ;;
      export\ *=*) line="${line#export }" ;;
      *=*)
        key="${line%%=*}"
        value="${line#*=}"

        if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
          echo "[run_be] ignore invalid env key: $key" >&2
          continue
        fi

        quote="${value:0:1}"
        if [[ "$quote" == '"' || "$quote" == "'" ]] && [[ "${value: -1}" == "$quote" ]]; then
          value="${value:1:${#value}-2}"
        fi

        export "$key=$value"
        ;;
      *)
        echo "[run_be] ignore malformed env line: $line" >&2
        ;;
    esac
  done < "$env_file"
}

validate_env_file() {
  local env_file="$1"
  local line key value quote line_no required_key path_key
  declare -A env_values=()

  if [ ! -s "$env_file" ]; then
    echo "[run_be] env file missing or empty: $env_file" >&2
    return 1
  fi

  line_no=0
  while IFS= read -r line || [ -n "$line" ]; do
    line_no=$((line_no + 1))
    line="${line%$'\r'}"

    case "$line" in
      ''|'#'*) continue ;;
      export\ *=*) line="${line#export }" ;;
      *=*) ;;
      *)
        echo "[run_be] malformed env line ${line_no}: $line" >&2
        return 1
        ;;
    esac

    key="${line%%=*}"
    value="${line#*=}"

    if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      echo "[run_be] invalid env key at line ${line_no}: $key" >&2
      return 1
    fi
    if [[ -v "env_values[$key]" ]]; then
      echo "[run_be] duplicate env key: $key" >&2
      return 1
    fi

    quote="${value:0:1}"
    if [[ "$quote" == '"' || "$quote" == "'" ]]; then
      if [[ "${value: -1}" != "$quote" ]]; then
        echo "[run_be] unclosed env quote at line ${line_no}: $key" >&2
        return 1
      fi
      value="${value:1:${#value}-2}"
    fi

    env_values["$key"]="$value"
  done < "$env_file"

  for required_key in "${REQUIRED_ENV_KEYS[@]}"; do
    if [[ ! -v "env_values[$required_key]" ]] || [ -z "${env_values[$required_key]}" ]; then
      echo "[run_be] missing required env key: $required_key" >&2
      return 1
    fi
  done

  if [[ ! "${env_values[DB_PORT]}" =~ ^[0-9]+$ ]]; then
    echo "[run_be] DB_PORT must be numeric" >&2
    return 1
  fi

  for path_key in "${PATH_ENV_KEYS[@]}"; do
    if [[ -v "env_values[$path_key]" ]] && [ -n "${env_values[$path_key]}" ]; then
      case "${env_values[$path_key]}" in
        /*) ;;
        *)
          echo "[run_be] path env must be absolute: $path_key" >&2
          return 1
          ;;
      esac
    fi
  done
}

stop_pidfile_process() {
  local pidfile="$1"
  if [ ! -f "$pidfile" ]; then
    return
  fi
  local pid
  pid="$(cat "$pidfile")"
  if ! kill -0 "$pid" 2>/dev/null; then
    return
  fi
  kill -TERM "$pid"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return
    fi
    sleep 1
  done
  kill -KILL "$pid" 2>/dev/null || true
}

require_systemd_access() {
  if ! sudo -n systemctl show "$SERVICE_NAME" >/dev/null 2>&1; then
    echo "[run_be] cannot access $SERVICE_NAME via sudo -n systemctl" >&2
    exit 1
  fi
}

stop_service_and_orphans() {
  local orphan_pattern
  local all_stopped
  local orphan_patterns=(
    "/home/ln-admin/likenovel/api/.venv/bin/gunicorn -c"
    "/home/ln-admin/likenovel/api/.venv/bin/python -m gunicorn.app.wsgiapp -c"
  )

  sudo -n systemctl stop "$SERVICE_NAME" || true
  rm -f gunicorn.pid

  # 이전 CodeDeploy 경로가 systemd 밖에서 띄운 gunicorn을 정리한다.
  for orphan_pattern in "${orphan_patterns[@]}"; do
    pkill -TERM -f "$orphan_pattern" || true
  done
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    all_stopped=1
    for orphan_pattern in "${orphan_patterns[@]}"; do
      if pgrep -f "$orphan_pattern" >/dev/null 2>&1; then
        all_stopped=0
        break
      fi
    done
    if [ "$all_stopped" -eq 1 ]; then
      return
    fi
    sleep 1
  done
  for orphan_pattern in "${orphan_patterns[@]}"; do
    pkill -KILL -f "$orphan_pattern" || true
  done
}

prepare_next_venv() {
  rm -rf "$NEXT_VENV" "$NEXT_VENV.failed"
  python3 -m venv "$NEXT_VENV"
  "$NEXT_VENV/bin/python" -m pip install --upgrade pip
  "$NEXT_VENV/bin/pip" install "$(ls -v app-*.whl | tail -n 1)"
  "$NEXT_VENV/bin/python" - <<'PY'
from importlib.metadata import version

for package in ("sqlalchemy", "pymysql", "aiomysql"):
    print(f"[run_be] installed {package}=={version(package)}")
PY
}

verify_env_database_connection() {
  local env_file="$1"

  load_env_file "$env_file"
  "$NEXT_VENV/bin/python" - <<'PY'
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.const import settings


async def main():
    engine = create_async_engine(settings.LIKENOVEL_DB_URL, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


asyncio.run(main())
print("[run_be] DB smoke check passed")
PY
}

activate_next_venv() {
  rm -rf "$PREV_VENV"
  if [ -d .venv ]; then
    mv .venv "$PREV_VENV"
  fi
  mv "$NEXT_VENV" .venv
}

activate_next_env() {
  rm -f "$ENV_BACKUP"
  if [ -f .env ]; then
    cp .env "$ENV_BACKUP"
  fi
  cp .env.production .env
  # trailing newline 보장 (없으면 cron_env.sh의 while read가 마지막 줄 스킵)
  tail -c1 .env | read -r _ || echo >> .env
}

start_service_and_verify() {
  sudo -n systemctl reset-failed "$SERVICE_NAME" || true
  if ! sudo -n systemctl start "$SERVICE_NAME"; then
    sudo -n systemctl status "$SERVICE_NAME" --no-pager || true
    return 1
  fi

  for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
    if sudo -n systemctl is-active --quiet "$SERVICE_NAME" \
      && [ -f gunicorn.pid ] \
      && kill -0 "$(cat gunicorn.pid)" 2>/dev/null; then
      return 0
    fi
    sleep 2
  done

  sudo -n systemctl status "$SERVICE_NAME" --no-pager || true
  echo "[run_be] $SERVICE_NAME did not become active with live gunicorn.pid" >&2
  return 1
}

restore_previous_venv_and_restart() {
  sudo -n systemctl stop "$SERVICE_NAME" || true
  if [ -d .venv ]; then
    rm -rf "$NEXT_VENV.failed"
    mv .venv "$NEXT_VENV.failed"
  fi
  if [ ! -d "$PREV_VENV" ]; then
    echo "[run_be] previous venv missing; rollback unavailable" >&2
    return 1
  fi
  mv "$PREV_VENV" .venv
  start_service_and_verify
}

restore_previous_env() {
  if [ ! -f "$ENV_BACKUP" ]; then
    echo "[run_be] previous env missing; rollback unavailable" >&2
    return 1
  fi
  mv "$ENV_BACKUP" .env
}

start_ai_reader_worker() {
  AI_READER_WORKER_ENABLED=Y nohup ./.venv/bin/python -u scripts/run_ai_reader_worker.py \
    --worker-id "ai-reader-prod-$(hostname)" \
    --session-limit 10 \
    --action-limit 50 \
    --interval-seconds 5 \
    >> "$AI_READER_WORKER_LOG" 2>&1 &
  echo $! > "$AI_READER_WORKER_PID"
  sleep 1
  if ! kill -0 "$(cat "$AI_READER_WORKER_PID")" 2>/dev/null; then
    echo "[ERROR] AI reader worker failed to start"
    tail -50 "$AI_READER_WORKER_LOG" || true
    return 1
  fi
}

require_systemd_access
validate_env_file .env.production

rm -rf ./__pycache__

# 로그 디렉토리 생성 (없으면 라우터 import 실패)
mkdir -p ./logs/data ./logs/error

prepare_next_venv
verify_env_database_connection .env.production

for worker_pidfile in ai_reader_worker.pid ai_reader_worker_manual_*.pid; do
  stop_pidfile_process "$worker_pidfile"
done
pkill -TERM -f "/home/ln-admin/likenovel/api/.venv/bin/python .*scripts/run_ai_reader_worker.py" || true
sleep 3

stop_service_and_orphans
activate_next_venv
activate_next_env

# .env를 시스템 환경변수로 export (const.py의 os.getenv가 읽을 수 있도록)
# SMTP_PASSWORD처럼 공백이 포함된 값이 있어 shell source를 쓰지 않는다.
load_env_file .env

if ! start_service_and_verify; then
  echo "[run_be] start failed; restoring previous env and venv" >&2
  restore_status=0
  restore_previous_env || restore_status=$?
  restore_previous_venv_and_restart || restore_status=$?
  if [ "$restore_status" -eq 0 ]; then
    start_ai_reader_worker || restore_status=$?
  fi
  if [ "$restore_status" -ne 0 ]; then
    echo "[run_be] rollback had failures: $restore_status" >&2
  fi
  exit 1
fi

start_ai_reader_worker
rm -rf "$PREV_VENV" "$NEXT_VENV.failed" "$ENV_BACKUP"

# 배치 파일 동기화: 배포된 batch/ → 크론이 참조하는 /home/ln-admin/likenovel/batch/
BATCH_SRC=/home/ln-admin/likenovel/api/batch
BATCH_DST=/home/ln-admin/likenovel/batch
mkdir -p "$BATCH_DST"
cp "$BATCH_SRC"/*.sh "$BATCH_DST/" 2>/dev/null || true
cp "$BATCH_SRC"/*.sql "$BATCH_DST/" 2>/dev/null || true
cp "$BATCH_SRC"/*.py "$BATCH_DST/" 2>/dev/null || true
for batch_script in "$BATCH_DST"/*.sh; do
  [ -f "$batch_script" ] || continue
  chmod +x "$batch_script"
done

# prod 웹소챗 컨텍스트 배치 cron 보장 (중복 등록 방지)
STORYCTX_CRON_LINE='10 * * * * STORYCTX_MAX_PARALLEL=2 bash /home/ln-admin/likenovel/batch/build_story_agent_context_batch.sh >> /home/ln-admin/likenovel/batch/build_story_agent_context_batch.log 2>&1'
if ! crontab -l 2>/dev/null | grep -Fq "/home/ln-admin/likenovel/batch/build_story_agent_context_batch.sh"; then
  (crontab -l 2>/dev/null; echo "$STORYCTX_CRON_LINE") | crontab -
fi

exit 0
