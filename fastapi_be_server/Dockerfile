FROM python:3.12-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 패키지 업데이트 및 필요한 패키지 설치
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    cron \
    default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

# Poetry 설치
RUN pip install "poetry>=1.8"

# Poetry 설정 (가상환경 생성하지 않음)
RUN poetry config virtualenvs.create false

# 의존성 파일 복사
COPY pyproject.toml poetry.lock* ./

# 의존성 설치 (프로젝트 패키지 포함 설치)
RUN poetry install --only=main --no-interaction --no-ansi --no-root

# secrets 폴더 복사 (컨테이너 /app/secrets 로 복사됨)
COPY ./secrets ./secrets

# 애플리케이션 코드 복사
COPY . .

# 로그 디렉토리 생성 및 권한 설정
RUN mkdir -p logs/data logs/error && \
    chmod -R 755 logs && \
    touch logs/data/service_data_log_$(date +%Y%m%d_%H).log && \
    touch logs/error/service_error_log_$(date +%Y%m%d).log && \
    chmod 666 logs/data/*.log logs/error/*.log

# 포트 노출
EXPOSE 8000

# 헬스체크 추가
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 마지막 CMD만 아래처럼 변경
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "app.main:be_app", "--bind", "0.0.0.0:8000", "--workers", "4"]
