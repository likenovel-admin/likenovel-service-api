#!/bin/bash

# dev 백엔드 서버 새로운 배포 버전으로 재기동

APP_DIR=/home/ln-admin/likenovel/api-dev
SERVICE_NAME=likenovel-api-dev.service

sudo chown -R ln-admin:ln-admin "$APP_DIR"
sudo chmod -R 700 "$APP_DIR"

cd "$APP_DIR"

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
          echo "[run_be.dev] ignore invalid env key: $key" >&2
          continue
        fi

        quote="${value:0:1}"
        if [[ "$quote" == '"' || "$quote" == "'" ]] && [[ "${value: -1}" == "$quote" ]]; then
          value="${value:1:${#value}-2}"
        fi

        export "$key=$value"
        ;;
      *)
        echo "[run_be.dev] ignore malformed env line: $line" >&2
        ;;
    esac
  done < "$env_file"
}

require_systemd_access() {
  if ! sudo -n systemctl show "$SERVICE_NAME" >/dev/null 2>&1; then
    echo "[run_be.dev] cannot access $SERVICE_NAME via sudo -n systemctl" >&2
    exit 1
  fi
}

stop_service_and_orphans() {
  sudo -n systemctl stop "$SERVICE_NAME" || true

  # 이전 CodeDeploy 경로가 systemd 밖에서 띄운 gunicorn을 정리한다.
  pkill -TERM -f "$APP_DIR/.venv/bin/gunicorn -c" || true
  sleep 5
  pkill -KILL -f "$APP_DIR/.venv/bin/gunicorn -c" || true
  rm -f gunicorn.pid
}

start_service_and_verify() {
  sudo -n systemctl reset-failed "$SERVICE_NAME" || true
  sudo -n systemctl start "$SERVICE_NAME"
  sleep 5

  if ! sudo -n systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "[run_be.dev] $SERVICE_NAME failed to become active" >&2
    sudo -n systemctl status "$SERVICE_NAME" --no-pager || true
    exit 1
  fi

  if [ ! -f gunicorn.pid ] || ! kill -0 "$(cat gunicorn.pid)" 2>/dev/null; then
    echo "[run_be.dev] $SERVICE_NAME active but gunicorn.pid is missing or stale" >&2
    sudo -n systemctl status "$SERVICE_NAME" --no-pager || true
    exit 1
  fi
}

require_systemd_access
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
source .venv/bin/activate
pip3 install --upgrade pip
pip3 install "$(ls -v app-*.whl | tail -n 1)"

# .env를 시스템 환경변수로 export (const.py의 os.getenv가 읽을 수 있도록)
# SMTP_PASSWORD처럼 공백이 포함된 값이 있어 shell source를 쓰지 않는다.
load_env_file .env

deactivate

# 배치 파일 동기화 + cron.d 등록
BATCH_SRC=/home/ln-admin/likenovel/api-dev/batch
BATCH_DST=/home/ln-admin/likenovel/batch-dev
mkdir -p "$BATCH_DST"
cp "$BATCH_SRC"/*.sh "$BATCH_DST/"
cp "$BATCH_SRC"/*.sql "$BATCH_DST/"
cp "$BATCH_SRC"/*.py "$BATCH_DST/" 2>/dev/null || true
chmod +x "$BATCH_DST"/*.sh
# dev 배치 cron은 수동으로만 활성화 (필요 시: sudo cp "$BATCH_SRC/cron_job.dev.sh" /etc/cron.d/likenovel-dev)
# sudo cp "$BATCH_SRC/cron_job.dev.sh" /etc/cron.d/likenovel-dev
# sudo chmod 644 /etc/cron.d/likenovel-dev

start_service_and_verify

exit 0
