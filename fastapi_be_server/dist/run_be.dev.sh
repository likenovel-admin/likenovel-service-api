#!/bin/bash

# dev 백엔드 서버를 release 디렉토리로 준비한 뒤 symlink를 전환해 재기동한다.

set -euo pipefail

DEPLOY_DIR=/home/ln-admin/likenovel/api-dev-deploy
CURRENT_LINK=/home/ln-admin/likenovel/api-dev
RELEASE_BASE=/home/ln-admin/likenovel/releases/api-dev
RELEASE_KEEP=5
SERVICE_NAME=likenovel-api-dev.service

RELEASE_ID="$(date +%Y%m%d%H%M%S)-${DEPLOYMENT_ID:-${CODEDEPLOY_DEPLOYMENT_ID:-manual-$$}}"
NEW_RELEASE_DIR="$RELEASE_BASE/$RELEASE_ID"
PREVIOUS_RELEASE=""
LEGACY_BACKUP=""

log() {
  echo "[run_be.dev] $*"
}

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

prepare_release() {
  local wheel_file

  if [ ! -d "$DEPLOY_DIR" ]; then
    echo "[run_be.dev] deploy dir missing: $DEPLOY_DIR" >&2
    exit 1
  fi

  mkdir -p "$RELEASE_BASE"
  sudo -n chown -R ln-admin:ln-admin "$DEPLOY_DIR" "$RELEASE_BASE" 2>/dev/null || true
  chmod 700 "$DEPLOY_DIR" "$RELEASE_BASE"

  rm -rf "$NEW_RELEASE_DIR"
  mkdir -p "$NEW_RELEASE_DIR"
  cp -a "$DEPLOY_DIR"/. "$NEW_RELEASE_DIR"/
  chmod -R u+rwX,go-rwx "$NEW_RELEASE_DIR"

  cd "$NEW_RELEASE_DIR"

  wheel_file="$(ls -t app-*.whl | head -n 1)"
  find . -maxdepth 1 -name 'app-*.whl' ! -name "$(basename "$wheel_file")" -delete

  rm -rf ./__pycache__
  rm -rf ./.venv

  # 로그 디렉토리 생성 (없으면 라우터 import 실패)
  mkdir -p ./logs/data ./logs/error

  # .env.production -> .env (pydantic_settings가 .env를 읽음)
  cp .env.production .env
  # trailing newline 보장 (없으면 cron_env.sh의 while read가 마지막 줄 스킵)
  tail -c1 .env | read -r _ || echo >> .env

  chmod +x ./run_be.sh ./boot-start-api-dev.sh

  python3 -m venv .venv
  source .venv/bin/activate
  pip3 install --upgrade pip
  pip3 install "$wheel_file"

  # .env를 시스템 환경변수로 export (const.py의 os.getenv가 읽을 수 있도록)
  # SMTP_PASSWORD처럼 공백이 포함된 값이 있어 shell source를 쓰지 않는다.
  load_env_file .env

  deactivate
}

stop_service_and_orphans() {
  sudo -n systemctl stop "$SERVICE_NAME" || true

  # 이전 CodeDeploy 경로가 systemd 밖에서 띄운 gunicorn을 정리한다.
  pkill -TERM -f "$CURRENT_LINK/.venv/bin/gunicorn -c" || true
  for _ in 1 2 3 4 5; do
    if ! pgrep -f "$CURRENT_LINK/.venv/bin/gunicorn -c" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  pkill -KILL -f "$CURRENT_LINK/.venv/bin/gunicorn -c" || true
  rm -f "$CURRENT_LINK/gunicorn.pid"
}

start_service_and_verify() {
  sudo -n systemctl reset-failed "$SERVICE_NAME" || true
  if ! sudo -n systemctl start "$SERVICE_NAME"; then
    sudo -n systemctl status "$SERVICE_NAME" --no-pager || true
    return 1
  fi

  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if sudo -n systemctl is-active --quiet "$SERVICE_NAME" \
      && [ -f "$CURRENT_LINK/gunicorn.pid" ] \
      && kill -0 "$(cat "$CURRENT_LINK/gunicorn.pid")" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done

  echo "[run_be.dev] $SERVICE_NAME failed to become active with a live pidfile" >&2
  sudo -n systemctl status "$SERVICE_NAME" --no-pager || true
  return 1
}

current_release_target() {
  if [ -L "$CURRENT_LINK" ]; then
    readlink -f "$CURRENT_LINK" 2>/dev/null || true
  fi
}

switch_current_link() {
  local tmp_link="${CURRENT_LINK}.next"

  PREVIOUS_RELEASE="$(current_release_target)"
  rm -f "$tmp_link"

  if [ -L "$CURRENT_LINK" ]; then
    rm -f "$CURRENT_LINK"
  elif [ -d "$CURRENT_LINK" ]; then
    LEGACY_BACKUP="$RELEASE_BASE/$(date +%Y%m%d%H%M%S)-pre-symlink"
    mv "$CURRENT_LINK" "$LEGACY_BACKUP"
  elif [ -e "$CURRENT_LINK" ]; then
    echo "[run_be.dev] current path is not a directory or symlink: $CURRENT_LINK" >&2
    exit 1
  fi

  ln -s "$NEW_RELEASE_DIR" "$tmp_link"
  mv -T "$tmp_link" "$CURRENT_LINK"
}

rollback_to_previous_release() {
  local tmp_link="${CURRENT_LINK}.rollback"

  rm -f "$tmp_link"
  if [ -n "$PREVIOUS_RELEASE" ] && [ -d "$PREVIOUS_RELEASE" ]; then
    ln -s "$PREVIOUS_RELEASE" "$tmp_link"
    rm -f "$CURRENT_LINK"
    mv -T "$tmp_link" "$CURRENT_LINK"
    log "rolled back current link to $PREVIOUS_RELEASE"
    return 0
  fi

  if [ -n "$LEGACY_BACKUP" ] && [ -d "$LEGACY_BACKUP" ]; then
    rm -f "$CURRENT_LINK"
    mv "$LEGACY_BACKUP" "$CURRENT_LINK"
    log "rolled back current directory from $LEGACY_BACKUP"
    return 0
  fi

  echo "[run_be.dev] no previous release available for rollback" >&2
  return 1
}

sync_batch_files() {
  local batch_src="$CURRENT_LINK/batch"
  local batch_dst=/home/ln-admin/likenovel/batch-dev

  mkdir -p "$batch_dst"
  cp "$batch_src"/*.sh "$batch_dst/" 2>/dev/null || true
  cp "$batch_src"/*.sql "$batch_dst/" 2>/dev/null || true
  cp "$batch_src"/*.py "$batch_dst/" 2>/dev/null || true
  if compgen -G "$batch_dst/*.sh" >/dev/null; then
    chmod +x "$batch_dst"/*.sh
  fi
  # dev 배치 cron은 수동으로만 활성화 (필요 시: sudo cp "$batch_src/cron_job.dev.sh" /etc/cron.d/likenovel-dev)
  # sudo cp "$batch_src/cron_job.dev.sh" /etc/cron.d/likenovel-dev
  # sudo chmod 644 /etc/cron.d/likenovel-dev
}

cleanup_old_releases() {
  local keep="$1"
  local current_target
  local count=0
  local release_dir release_name

  current_target="$(current_release_target)"

  while IFS= read -r release_dir; do
    release_name="$(basename "$release_dir")"
    case "$release_name" in
      20*) ;;
      *) continue ;;
    esac

    case "$release_dir" in
      "$RELEASE_BASE"/*) ;;
      *) continue ;;
    esac

    count=$((count + 1))
    if [ "$count" -le "$keep" ]; then
      continue
    fi
    if [ "$release_dir" = "$current_target" ] || [ "$release_dir" = "$PREVIOUS_RELEASE" ]; then
      continue
    fi

    rm -rf -- "$release_dir"
  done < <(find "$RELEASE_BASE" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn | sed 's/^[^ ]* //')
}

require_systemd_access
prepare_release
stop_service_and_orphans
switch_current_link

if ! start_service_and_verify; then
  echo "[run_be.dev] new release failed; attempting rollback" >&2
  stop_service_and_orphans || true
  if rollback_to_previous_release && start_service_and_verify; then
    echo "[run_be.dev] rollback succeeded" >&2
  else
    echo "[run_be.dev] rollback failed" >&2
  fi
  exit 1
fi

sync_batch_files
cleanup_old_releases "$RELEASE_KEEP"

exit 0
