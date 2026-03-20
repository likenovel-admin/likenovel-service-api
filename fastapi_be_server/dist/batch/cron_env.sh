#!/bin/bash

# 배치용 환경변수 로더
# 서버: BATCH_ENV_FILE 또는 ../api/.env, ../api-dev/.env 에서 읽음
# Docker: /proc/1/environ 에서 읽음

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_CANDIDATES=(
  "${BATCH_ENV_FILE:-}"
  "${SCRIPT_DIR}/../api/.env"
  "${SCRIPT_DIR}/../api-dev/.env"
)

_loaded=false
for ef in "${ENV_CANDIDATES[@]}"; do
  if [ -n "$ef" ] && [ -r "$ef" ]; then
    while IFS="=" read -r key value; do
      case "$key" in
        DB_HOST|DB_IP|DB_PORT|DB_USER|DB_PW|DB_USER_ID|DB_USER_PW|DB_NAME|ANTHROPIC_API_KEY|ANTHROPIC_MODEL)
          export "$key=$value"
          ;;
      esac
    done < "$ef"
    _loaded=true
    break
  fi
done

# Docker 환경 fallback
if [ "$_loaded" = false ] && [ -r /proc/1/environ ]; then
  while IFS='=' read -r key value; do
    case "$key" in
      DB_HOST|DB_IP|DB_PORT|DB_USER|DB_PW|DB_USER_ID|DB_USER_PW|DB_NAME|ANTHROPIC_API_KEY|ANTHROPIC_MODEL)
        export "$key=$value"
        ;;
    esac
  done < <(tr '\0' '\n' < /proc/1/environ)
fi

# Fallback aliases
export DB_HOST="${DB_HOST:-${DB_IP:-mysql}}"
export DB_PORT="${DB_PORT:-3306}"
export DB_USER="${DB_USER:-${DB_USER_ID:-}}"
export DB_PW="${DB_PW:-${DB_USER_PW:-}}"
export DB_NAME="${DB_NAME:-likenovel}"

# Python 배치(extract_product_dna.py)용 변수 alias
export BATCH_DB_HOST="${DB_HOST}"
export BATCH_DB_PORT="${DB_PORT}"
export BATCH_DB_USER="${DB_USER}"
export BATCH_DB_PASSWORD="${DB_PW}"
export BATCH_DB_NAME="${DB_NAME}"

# MariaDB는 --skip-ssl, MySQL 8.0+는 --ssl-mode=DISABLED
if mysql --version 2>&1 | grep -qi mariadb; then
  export MYSQL_SSL_OPT="--skip-ssl"
else
  export MYSQL_SSL_OPT="--ssl-mode=DISABLED"
fi
