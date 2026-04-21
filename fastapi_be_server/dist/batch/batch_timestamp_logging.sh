#!/usr/bin/env bash

# 배치 stdout/stderr 전 라인에 KST 타임스탬프 프리픽스를 붙인다.
# - batch_recent가 최근 실패를 정확히 판정할 수 있도록 실패 라인 자체에 시각을 남긴다.
# - 중복 적용은 방지한다.

enable_timestamped_logging() {
  if [ "${BATCH_TIMESTAMP_LOGGING_ENABLED:-0}" = "1" ]; then
    return 0
  fi

  export BATCH_TIMESTAMP_LOGGING_ENABLED=1
  exec > >(while IFS= read -r line || [ -n "$line" ]; do
    printf '[%(%Y-%m-%d %H:%M:%S %Z)T] %s\n' -1 "$line"
  done) 2>&1
}
