#!/bin/bash
set -euo pipefail

# 백엔드 서버 새로운 배포 버전으로 재기동
# 운영 시에는 서버점검 공지 후 해당 작업 권장(가장 안전한 방법)
# -HUP을 통한 무중단 재기동 방법은 상황에 따라 잠재적 문제점이 있기에 패스

sudo chown -R ln-admin:ln-admin /home/ln-admin/likenovel/api
sudo chmod -R 700 /home/ln-admin/likenovel/api

cd /home/ln-admin/likenovel/api || exit 1

SERVICE_NAME=likenovel-api.service

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
  sudo -n systemctl stop "$SERVICE_NAME" || true
  rm -f gunicorn.pid

  # 이전 CodeDeploy 경로가 systemd 밖에서 띄운 gunicorn을 정리한다.
  pkill -TERM -f "/home/ln-admin/likenovel/api/.venv/bin/gunicorn -c" || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! pgrep -f "/home/ln-admin/likenovel/api/.venv/bin/gunicorn -c" >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  pkill -KILL -f "/home/ln-admin/likenovel/api/.venv/bin/gunicorn -c" || true
}

start_service_and_verify() {
  sudo -n systemctl reset-failed "$SERVICE_NAME" || true
  if ! sudo -n systemctl start "$SERVICE_NAME"; then
    sudo -n systemctl status "$SERVICE_NAME" --no-pager || true
    exit 1
  fi

  for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
    if sudo -n systemctl is-active --quiet "$SERVICE_NAME" \
      && [ -f gunicorn.pid ] \
      && kill -0 "$(cat gunicorn.pid)" 2>/dev/null; then
      return
    fi
    sleep 2
  done

  sudo -n systemctl status "$SERVICE_NAME" --no-pager || true
  echo "[run_be] $SERVICE_NAME did not become active with live gunicorn.pid" >&2
  exit 1
}

require_systemd_access

for worker_pidfile in ai_reader_worker.pid ai_reader_worker_manual_*.pid; do
  stop_pidfile_process "$worker_pidfile"
done
pkill -TERM -f "/home/ln-admin/likenovel/api/.venv/bin/python .*scripts/run_ai_reader_worker.py" || true
sleep 3

stop_service_and_orphans

rm -rf ./__pycache__
rm -rf ./.venv

# 로그 디렉토리 생성 (없으면 라우터 import 실패)
mkdir -p ./logs/data ./logs/error

# .env.production → .env (pydantic_settings가 .env를 읽음)
cp .env.production .env
# trailing newline 보장 (없으면 cron_env.sh의 while read가 마지막 줄 스킵)
tail -c1 .env | read -r _ || echo >> .env

python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/pip install "$(ls -v app-*.whl | tail -n 1)"
./.venv/bin/python - <<'PY'
from importlib.metadata import version

for package in ("sqlalchemy", "pymysql", "aiomysql"):
    print(f"[run_be] installed {package}=={version(package)}")
PY

# .env를 시스템 환경변수로 export (const.py의 os.getenv가 읽을 수 있도록)
# SMTP_PASSWORD처럼 공백이 포함된 값이 있어 shell source를 쓰지 않는다.
load_env_file .env

start_service_and_verify

AI_READER_WORKER_LOG=./logs/data/ai_reader_worker.log
AI_READER_WORKER_PID=./ai_reader_worker.pid
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
  exit 1
fi

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
