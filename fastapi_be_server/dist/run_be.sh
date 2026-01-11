#!/bin/bash

# 백엔드 서버 새로운 배포 버전으로 재기동
# 운영 시에는 서버점검 공지 후 해당 작업 권장(가장 안전한 방법)
# -HUP을 통한 무중단 재기동 방법은 상황에 따라 잠재적 문제점이 있기에 패스

sudo chown -R ln-admin:ln-admin /home/ln-admin/likenovel/api
sudo chmod -R 700 /home/ln-admin/likenovel/api

cd /home/ln-admin/likenovel/api

kill -TERM $(cat gunicorn.pid)
# graceful_timeout의 기본값은 30
# 보통 1~2초 사이에 끝나지만 안전하게 10초 정도 대기
sleep 10

rm -r ./__pycache__
rm -r ./.venv

python3 -m venv .venv
source .venv/bin/activate
pip3 install --upgrade pip
pip3 install "$(ls -v app-*.whl | tail -n 1)"
gunicorn -c ./gconf.py
deactivate

exit 0

