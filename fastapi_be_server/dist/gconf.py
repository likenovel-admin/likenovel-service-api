wsgi_app = 'app.main:be_app'
forwarded_allow_ips = "*"
bind = ['10.0.100.110:3010']
# worker 수: 공식 매뉴얼에서 (2 x $num_cores) + 1 권장
# 단, 최소 스펙(t2.micro)을 고려했을 때, 우선 2개로 사용
workers = 2
# uvicorn worker
worker_class = 'uvicorn_worker.UvicornWorker'
pidfile = '/home/ln-admin/likenovel/api/gunicorn.pid'
daemon = True

