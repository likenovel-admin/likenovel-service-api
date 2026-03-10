#!/bin/bash

#
# Meilisearch 실행 스크립트 (로컬/운영 공용)
# - master key 등 민감 값은 레포에 두지 않고 환경변수로 주입합니다.
#

MEILI_HTTP_ADDR="${MEILI_HTTP_ADDR:-0.0.0.0:7700}"
MEILI_MASTER_KEY="${MEILI_MASTER_KEY:-}"

if [ -z "$MEILI_MASTER_KEY" ]; then
  echo "[start_meilisearch.sh] ERROR: MEILI_MASTER_KEY is missing" >&2
  exit 1
fi

meilisearch --http-addr "$MEILI_HTTP_ADDR" --master-key="$MEILI_MASTER_KEY"
