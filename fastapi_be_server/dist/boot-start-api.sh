#!/bin/bash
# systemd(likenovel-api.service)가 호출하는 prod gunicorn 기동 스크립트.
# CodeDeploy run_be.sh가 준비한 .env, .venv, gconf.py를 사용해 기동만 담당한다.

set -euo pipefail

APP_DIR="/home/ln-admin/likenovel/api"
PID_FILE="$APP_DIR/gunicorn.pid"

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
          echo "[boot-start-api] ignore invalid env key: $key" >&2
          continue
        fi

        quote="${value:0:1}"
        if [[ "$quote" == '"' || "$quote" == "'" ]] && [[ "${value: -1}" == "$quote" ]]; then
          value="${value:1:${#value}-2}"
        fi

        export "$key=$value"
        ;;
      *)
        echo "[boot-start-api] ignore malformed env line: $line" >&2
        ;;
    esac
  done < "$env_file"
}

cd "$APP_DIR"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "[boot-start-api] already running (pid=$(cat "$PID_FILE"))"
  exit 0
fi

rm -f "$PID_FILE"

if [ ! -f "$APP_DIR/.env" ]; then
  echo "[boot-start-api] .env missing, aborting" >&2
  exit 1
fi
if [ ! -d "$APP_DIR/.venv" ]; then
  echo "[boot-start-api] .venv missing, aborting" >&2
  exit 1
fi
if [ ! -f "$APP_DIR/gconf.py" ]; then
  echo "[boot-start-api] gconf.py missing, aborting" >&2
  exit 1
fi

load_env_file "$APP_DIR/.env"
mkdir -p "$APP_DIR/logs/data" "$APP_DIR/logs/error"

exec "$APP_DIR/.venv/bin/python" -m gunicorn.app.wsgiapp -c "$APP_DIR/gconf.py"
