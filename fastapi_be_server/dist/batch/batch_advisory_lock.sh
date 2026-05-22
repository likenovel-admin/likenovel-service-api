#!/bin/bash

run_sql_with_advisory_lock() {
  local lock_name="$1"
  local sql_file="$2"
  local log_label="$3"
  local lock_holder=""
  local wrapped_sql=""
  local rc=0

  if [ ! -f "$sql_file" ]; then
    echo "[ERROR] Missing SQL file: ${sql_file}" 1>&2
    return 1
  fi

  lock_holder="$(
    mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PW" "$DB_NAME" \
      --default-character-set=utf8mb4 $MYSQL_SSL_OPT --batch --raw --skip-column-names \
      -e "SELECT COALESCE(IS_USED_LOCK('${lock_name}'), 0)"
  )"

  if [ "$lock_holder" != "0" ]; then
    echo "[INFO] ${log_label} skip: advisory lock busy (${lock_name})" 1>&2
    return 2
  fi

  wrapped_sql="$(mktemp /tmp/likenovel_batch_advisory_lock.XXXXXX.sql)"
  {
    printf "SET @likenovel_batch_lock_result = GET_LOCK('%s', 0);\n" "$lock_name"
    printf "SET @likenovel_batch_lock_guard_sql = IF(@likenovel_batch_lock_result = 1, 'SELECT 1', 'SIGNAL SQLSTATE ''45000'' SET MYSQL_ERRNO = 1205, MESSAGE_TEXT = ''advisory lock busy''');\n"
    printf "PREPARE stmt_likenovel_batch_lock_guard FROM @likenovel_batch_lock_guard_sql;\n"
    printf "EXECUTE stmt_likenovel_batch_lock_guard;\n"
    printf "DEALLOCATE PREPARE stmt_likenovel_batch_lock_guard;\n"
    printf "source %s;\n" "$sql_file"
    printf "SELECT RELEASE_LOCK('%s');\n" "$lock_name"
  } > "$wrapped_sql"

  mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PW" "$DB_NAME" \
    --default-character-set=utf8mb4 $MYSQL_SSL_OPT < "$wrapped_sql"
  rc=$?
  rm -f "$wrapped_sql"
  return "$rc"
}
