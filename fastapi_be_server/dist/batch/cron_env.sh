#!/bin/bash

# Load DB-related environment values from PID 1 process environment.
# This avoids relying on cron's minimal env and keeps compatibility with
# both DB_HOST-style and DB_IP-style variable naming.
if [ -r /proc/1/environ ]; then
  while IFS='=' read -r key value; do
    case "$key" in
      DB_HOST|DB_IP|DB_PORT|DB_USER|DB_PW|DB_USER_ID|DB_USER_PW|DB_NAME)
        export "$key=$value"
        ;;
    esac
  done < <(tr '\0' '\n' < /proc/1/environ)
fi

# Fallback aliases (non-destructive)
export DB_HOST="${DB_HOST:-${DB_IP:-mysql}}"
export DB_PORT="${DB_PORT:-3306}"
export DB_USER="${DB_USER:-${DB_USER_ID:-}}"
export DB_PW="${DB_PW:-${DB_USER_PW:-}}"
export DB_NAME="${DB_NAME:-likenovel}"

# MariaDB는 --skip-ssl, MySQL 8.0+는 --ssl-mode=DISABLED
if mysql --version 2>&1 | grep -qi mariadb; then
  export MYSQL_SSL_OPT="--skip-ssl"
else
  export MYSQL_SSL_OPT="--ssl-mode=DISABLED"
fi
