#!/bin/bash

# NOTE(Windows):
# - 이 파일이 CRLF(\r\n)로 저장되면 컨테이너에서 shebang이 `/bin/bash\r`로 인식되어
#   "no such file or directory"로 실행이 실패할 수 있습니다. (반드시 LF로 유지)

# 로컬 배치는 명시적으로 켠 경우에만 cron을 등록한다.
case "${LOCAL_BATCH_CRON_ENABLE:-0}" in
  1)
    if ! crontab /app/dist/batch/cron_job.sh; then
      echo "ERROR: failed to install local batch crontab" >&2
      exit 1
    fi
    if ! service cron start >/dev/null 2>&1; then
      echo "ERROR: failed to start local cron service" >&2
      exit 1
    fi
    if ! service cron status >/dev/null 2>&1 || ! crontab -l >/dev/null 2>&1; then
      echo "ERROR: local batch cron did not start cleanly" >&2
      exit 1
    fi
    echo "Local container cron enabled"
    crontab -l
    ;;
  0)
    crontab -r >/dev/null 2>&1 || true
    service cron stop >/dev/null 2>&1 || true
    if crontab -l >/dev/null 2>&1; then
      echo "ERROR: local crontab remains after API startup" >&2
      exit 1
    fi
    echo "Local container cron disabled"
    ;;
  *)
    echo "ERROR: LOCAL_BATCH_CRON_ENABLE must be 0 or 1" >&2
    exit 1
    ;;
esac

# 메인 애플리케이션 시작
exec "$@"
