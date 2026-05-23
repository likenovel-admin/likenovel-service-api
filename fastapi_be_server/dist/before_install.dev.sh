#!/bin/bash
# CodeDeploy가 새 bundle을 풀기 전에 dev staging 디렉토리의 stale 파일을 제거한다.

set -euo pipefail

DEPLOY_DIR=/home/ln-admin/likenovel/api-dev-deploy

case "$DEPLOY_DIR" in
  "/home/ln-admin/likenovel/api-dev-deploy") ;;
  *)
    echo "[before_install.dev] unexpected deploy dir: $DEPLOY_DIR" >&2
    exit 1
    ;;
esac

if [ -L "$DEPLOY_DIR" ]; then
  echo "[before_install.dev] deploy dir must not be a symlink: $DEPLOY_DIR" >&2
  exit 1
fi

mkdir -p "$DEPLOY_DIR"
chmod 700 "$DEPLOY_DIR"

find "$DEPLOY_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
