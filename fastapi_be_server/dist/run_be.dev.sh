#!/bin/bash

# dev 백엔드 서버 새로운 배포 버전으로 재기동

sudo chown -R ln-admin:ln-admin /home/ln-admin/likenovel/api-dev
sudo chmod -R 700 /home/ln-admin/likenovel/api-dev

cd /home/ln-admin/likenovel/api-dev

# 최초 배포 시 pidfile이 없을 수 있음
if [ -f gunicorn.pid ]; then
  kill -TERM $(cat gunicorn.pid)
  sleep 10
fi

rm -rf ./__pycache__
rm -rf ./.venv

# 로그 디렉토리 생성 (없으면 라우터 import 실패)
mkdir -p ./logs/data ./logs/error

# .env.production → .env (pydantic_settings가 .env를 읽음)
cp .env.production .env
# trailing newline 보장 (없으면 cron_env.sh의 while read가 마지막 줄 스킵)
tail -c1 .env | read -r _ || echo >> .env

python3 -m venv .venv
source .venv/bin/activate
pip3 install --upgrade pip
pip3 install "$(ls -v app-*.whl | tail -n 1)"

# .env를 시스템 환경변수로 export (const.py의 os.getenv가 읽을 수 있도록)
set -a
source .env
set +a

gunicorn -c ./gconf.py
deactivate

# 배치 파일 동기화 + cron.d 등록
BATCH_SRC=/home/ln-admin/likenovel/api-dev/batch
BATCH_DST=/home/ln-admin/likenovel/batch-dev
mkdir -p "$BATCH_DST"
cp "$BATCH_SRC"/*.sh "$BATCH_DST/"
cp "$BATCH_SRC"/*.sql "$BATCH_DST/"
cp "$BATCH_SRC"/*.py "$BATCH_DST/" 2>/dev/null || true
chmod +x "$BATCH_DST"/*.sh
# dev 배치 cron은 수동으로만 활성화 (필요 시: sudo cp "$BATCH_SRC/cron_job.dev.sh" /etc/cron.d/likenovel-dev)
# sudo cp "$BATCH_SRC/cron_job.dev.sh" /etc/cron.d/likenovel-dev
# sudo chmod 644 /etc/cron.d/likenovel-dev

exit 0
