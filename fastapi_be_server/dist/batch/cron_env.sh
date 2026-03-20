#!/bin/bash

# 배치용 환경변수 로더
# 서버: 배치 디렉토리명으로 dev/prod 판별 후 올바른 .env 로딩
# Docker: /proc/1/environ fallback

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 환경 판별: batch-dev → api-dev/.env, batch → api/.env
if [[ "$SCRIPT_DIR" == *"batch-dev"* ]]; then
  _ENV_FILE="${SCRIPT_DIR}/../api-dev/.env"
else
  _ENV_FILE="${SCRIPT_DIR}/../api/.env"
fi

# BATCH_ENV_FILE 명시 지정 시 우선
ENV_FILE="${BATCH_ENV_FILE:-$_ENV_FILE}"

_loaded=false
for _try in 1 2 3; do
  if [ -r "$ENV_FILE" ] && [ -s "$ENV_FILE" ]; then
    while IFS="=" read -r key value; do
      case "$key" in
        DB_HOST|DB_IP|DB_PORT|DB_USER|DB_PW|DB_USER_ID|DB_USER_PW|DB_NAME|ANTHROPIC_API_KEY|ANTHROPIC_MODEL)
          export "$key=$value"
          ;;
      esac
    done < "$ENV_FILE"
    _loaded=true
    break
  fi
  sleep 3
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
