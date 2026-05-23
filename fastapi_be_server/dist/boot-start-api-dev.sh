#!/bin/bash
# systemd(likenovel-api-dev.service)가 호출하는 dev gunicorn 기동 스크립트.

set -euo pipefail

APP_DIR="/home/ln-admin/likenovel/api-dev"
PID_FILE="$APP_DIR/gunicorn.pid"
GCONF="$APP_DIR/gconf.py"

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
          echo "[boot-start-api-dev] ignore invalid env key: $key" >&2
          continue
        fi

        quote="${value:0:1}"
        if [[ "$quote" == '"' || "$quote" == "'" ]] && [[ "${value: -1}" == "$quote" ]]; then
          value="${value:1:${#value}-2}"
        fi

        export "$key=$value"
        ;;
      *)
        echo "[boot-start-api-dev] ignore malformed env line: $line" >&2
        ;;
    esac
  done < "$env_file"
}

cd "$APP_DIR"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "[boot-start-api-dev] already running (pid=$(cat "$PID_FILE"))"
  exit 0
fi

rm -f "$PID_FILE"

if [ ! -f "$APP_DIR/.env" ]; then
  echo "[boot-start-api-dev] .env missing, aborting" >&2
  exit 1
fi
if [ ! -d "$APP_DIR/.venv" ]; then
  echo "[boot-start-api-dev] .venv missing, aborting" >&2
  exit 1
fi
if [ ! -f "$GCONF" ]; then
  echo "[boot-start-api-dev] gconf missing at $GCONF, aborting" >&2
  exit 1
fi

load_env_file "$APP_DIR/.env"
mkdir -p "$APP_DIR/logs/data" "$APP_DIR/logs/error"

exec "$APP_DIR/.venv/bin/gunicorn" -c "$GCONF"
