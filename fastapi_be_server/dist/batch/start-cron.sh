#!/bin/bash

# NOTE(Windows):
# - 이 파일이 CRLF(\r\n)로 저장되면 컨테이너에서 shebang이 `/bin/bash\r`로 인식되어
#   "no such file or directory"로 실행이 실패할 수 있습니다. (반드시 LF로 유지)

# 로컬 API 컨테이너는 cron을 실행하지 않는다.
crontab -r >/dev/null 2>&1 || true
service cron stop >/dev/null 2>&1 || true

if crontab -l >/dev/null 2>&1; then
  echo "ERROR: local crontab remains after API startup" >&2
  exit 1
fi
echo "Local container cron disabled"

# 메인 애플리케이션 시작
exec "$@"
