#!/bin/bash

run_sql_with_advisory_lock() {
  local lock_name="$1"
  local sql_file="$2"
  local log_label="$3"
  local lock_result=""
  local session_pid=""
  local session_in=""
  local session_out=""

  if [ ! -f "$sql_file" ]; then
    echo "[ERROR] Missing SQL file: ${sql_file}" 1>&2
    return 1
  fi

  coproc LOCK_SESSION {
    mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PW" "$DB_NAME" \
      --default-character-set=utf8mb4 $MYSQL_SSL_OPT --batch --raw --skip-column-names
  }

  session_pid="${LOCK_SESSION_PID:-}"
  session_in="${LOCK_SESSION[1]:-}"
  session_out="${LOCK_SESSION[0]:-}"

  if [ -z "$session_pid" ] || [ -z "$session_in" ] || [ -z "$session_out" ]; then
    echo "[ERROR] Failed to start advisory lock session (${log_label})." 1>&2
    return 1
  fi

  printf "SELECT GET_LOCK('%s', 0);\n" "$lock_name" >&"$session_in"
  IFS= read -r lock_result <&"$session_out" || lock_result=""

  if [ "$lock_result" != "1" ]; then
    echo "[INFO] ${log_label} skip: advisory lock busy (${lock_name})" 1>&2
    printf "exit\n" >&"$session_in" 2>/dev/null || true
    wait "$session_pid" 2>/dev/null || true
    return 2
  fi

  printf "source %s;\nSELECT RELEASE_LOCK('%s');\nexit\n" "$sql_file" "$lock_name" >&"$session_in"
  wait "$session_pid"
}
