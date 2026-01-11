# LikeNovel Service API (FastAPI)

## 개요
이 프로젝트는 웹소설 플랫폼 LikeNovel의 백엔드 API 서버입니다. FastAPI 기반으로 작성되었으며, 다양한 인증, 결제, 작품, 유저, 이벤트, 알림 등 기능을 제공합니다.

- **버전**: 0.1.394
- **Python**: 3.12+
- **프레임워크**: FastAPI 0.112.2+

---

## 프로젝트 구조

```
fastapi_be_server/
  └── app/
      ├── main.py                # FastAPI 진입점, 미들웨어/라우터 등록
      ├── const.py               # 환경변수 및 상수 관리 (공통 상수 클래스 포함)
      ├── rdb.py                 # DB 연결 및 세션 관리
      ├── config/                # 로그 등 환경설정
      ├── models/                # ORM 모델 정의 (9개 모델 파일)
      ├── routers/               # API 라우터 (도메인별 디렉토리 분리)
      │   ├── admin/             # 관리자(CMS) 라우터
      │   ├── auth/              # 인증 라우터
      │   ├── common/            # 공통 기능 라우터 (배너, 검색, 통계 등)
      │   ├── content/           # 콘텐츠 라우터 (공지, 메시지, 지원)
      │   ├── event/             # 이벤트/퀘스트 라우터
      │   ├── gift/              # 선물/후원 라우터
      │   ├── order/             # 주문/결제 라우터
      │   ├── partner/           # 파트너 라우터
      │   ├── product/           # 작품/에피소드 라우터
      │   └── user/              # 사용자 라우터
      ├── schemas/               # Pydantic 스키마 (27개 스키마 파일)
      ├── services/              # 비즈니스 로직 서비스 (도메인별 디렉토리 분리)
      │   ├── admin/             # 관리자 서비스 (10개)
      │   ├── auth/              # 인증 서비스
      │   ├── common/            # 공통 서비스 (통계, 검색 등)
      │   ├── content/           # 콘텐츠 서비스
      │   ├── event/             # 이벤트/퀘스트 서비스
      │   ├── gift/              # 선물/후원 서비스
      │   ├── order/             # 주문/결제 서비스
      │   ├── partner/           # 파트너 서비스 (5개)
      │   ├── product/           # 작품 서비스 (7개)
      │   └── user/              # 사용자 서비스 (5개)
      ├── utils/                 # 유틸리티 모듈 (FCM, 공통 함수 등)
      ├── util.py, tags.py       # 유틸리티, 태그 등
```

### 주요 디렉토리 설명

#### routers/ (API 엔드포인트)
도메인별 디렉토리로 분리되어 있으며, Command/Query 패턴 적용

- `*_command.py`: 데이터 변경 작업 (POST, PUT, DELETE)
- `*_query.py`: 데이터 조회 작업 (GET)

| 디렉토리 | 설명 | 주요 파일 |
|----------|------|----------|
| `admin/` | 관리자(CMS) | admin_command.py, admin_query.py |
| `auth/` | 인증 | auth_command.py |
| `user/` | 사용자 | user_*.py, user_productbook_*.py, user_giftbook_*.py, user_ticketbook_*.py |
| `product/` | 작품/에피소드 | product_*.py, episode_*.py, product_review_*.py, product_evaluation_*.py |
| `order/` | 주문/결제 | order_*.py, payment_*.py |
| `content/` | 콘텐츠 | notice_*.py, message_*.py, support_*.py |
| `event/` | 이벤트/퀘스트 | event_*.py, quest_*.py |
| `gift/` | 선물/후원 | gift_*.py, author_command.py |
| `partner/` | 파트너 | partner_command.py, partner_query.py |
| `common/` | 공통 기능 | banner_query.py, search_query.py, statistics_query.py, alarm_*.py, carousel_*.py 등 |

#### services/ (비즈니스 로직)
도메인별 디렉토리로 분리되어 있으며, 각 도메인별 실제 비즈니스 로직 처리

| 디렉토리 | 설명 | 주요 파일 |
|----------|------|----------|
| `admin/` | 관리자(CMS) 서비스 (10개) | admin_basic, admin_content, admin_event, admin_user 등 |
| `auth/` | 인증 서비스 | auth_service.py (OAuth, Keycloak 연동) |
| `user/` | 사용자 서비스 (5개) | user_service, user_giftbook, user_productbook, user_ticketbook, user_notification |
| `product/` | 작품 서비스 (7개) | product_service, episode_service, product_comment, product_review, product_bookmark 등 |
| `order/` | 주문/결제 서비스 | order_service, payment_service, purchase_service |
| `content/` | 콘텐츠 서비스 | notice_service, message_service, support_service |
| `event/` | 이벤트/퀘스트 서비스 | event_service, quest_service |
| `gift/` | 선물/후원 서비스 | gift_service, sponsor_service, author_service |
| `partner/` | 파트너 서비스 (5개) | partner_basic, partner_product, partner_sales, partner_income, partner_statistics |
| `common/` | 공통 서비스 | comm_service, statistics_service, search_service, banner_service 등 |

#### models/ (ORM 모델)
| 모델 파일 | 설명 |
|----------|------|
| `admin.py` | 관리자 관련 테이블 |
| `user.py` | 사용자 관련 테이블 |
| `product.py` | 작품 관련 테이블 |
| `payment.py` | 결제 관련 테이블 |
| `event_quest_promotion.py` | 이벤트/퀘스트/프로모션 테이블 |
| `notice_qna.py` | 공지/QnA 테이블 |
| `statistics.py` | 통계 테이블 |
| `comm.py` | 공통 테이블 |

#### schemas/ (Pydantic 스키마)
API 요청/응답 데이터 구조 정의 (27개 파일)
- `admin.py`, `auth.py`, `user.py`, `product.py`, `episode.py`, `partner.py` 등

#### utils/ (유틸리티)
- `fcm.py`: Firebase Cloud Messaging 푸시 알림
- `common.py`: 공통 유틸리티 함수

---

## 주요 의존성

| 패키지 | 버전 | 용도 |
|--------|------|------|
| fastapi | ^0.112.2 | 웹 프레임워크 |
| uvicorn | ^0.30.6 | ASGI 서버 |
| gunicorn | ^23.0.0 | 프로덕션 서버 |
| sqlalchemy | ^2.0.32 | ORM (asyncio 지원) |
| aiomysql | ^0.2.0 | MySQL 비동기 드라이버 |
| pydantic | ^2.8.2 | 데이터 검증 |
| httpx | ^0.27.2 | HTTP 클라이언트 |
| pyjwt | ^2.9.0 | JWT 토큰 처리 |
| boto3 | ^1.35.17 | AWS S3/R2 연동 |
| meilisearch | ^0.31.5 | 검색 엔진 클라이언트 |
| firebase-admin | 7.0.0 | FCM 푸시 알림 |
| portone-server-sdk | ^0.8.0 | 결제 연동 |
| pandas | 2.2.3 | 데이터 처리 |
| bcrypt | ^4.3.0 | 비밀번호 해싱 |

---

## 환경 변수 및 설정

환경변수는 `app/const.py`에서 관리하며, pydantic의 BaseSettings를 사용합니다. 주요 변수는 아래와 같습니다.

- **DB 연결**: `LIKENOVEL_DB_URL` (MySQL, aiomysql)
- **Keycloak 인증**: `KC_DOMAIN`, `KC_CLIENT_ID`, `KC_CLIENT_SECRET` 등
- **외부 OAuth**: 네이버, 구글, 카카오, 애플 등 연동 정보
- **MeiliSearch**: `MEILISEARCH_HOST`, `MEILISEARCH_API_KEY`
- **정적 컨텐츠**: R2, CDN 등
- **FCM**: Firebase Cloud Messaging 설정
- **결제**: PortOne 결제 연동 설정
- **기타**: 페이징, 커스텀 상태코드 등

> **주의**: 실제 서비스 배포 시에는 민감 정보(비밀번호, 시크릿키 등)를 반드시 환경변수로 분리하거나 별도 보안 관리 필요.

---

## 설치 및 실행 방법

### Docker Compose를 사용한 전체 서비스 실행 (개발용으로 세팅했습니다 실제 운영서버에서는 사용되지 않고 있는것 같습니다)

1. **Docker 및 Docker Compose 설치 필요**
2. 프로젝트 루트 디렉토리에서 실행:

```bash
cd fastapi_be_server
docker-compose up -d
```

3. 서비스가 자동으로 시작됩니다:
   - **MySQL**: 데이터베이스 서버
   - **Keycloak**: 인증 서버 (자동 초기 설정 포함)
   - **MeiliSearch**: 검색 엔진
   - **API 서버**: FastAPI 애플리케이션

4. 서비스 접속:
   - **API 서버**: http://localhost:8800
   - **Keycloak 관리 콘솔**: http://localhost:8080
     - 관리자 계정: `admin` / `admin1234`
     - Realm: `likenovel`

> 🎉 **자동 설정**: Keycloak은 컨테이너 시작 시 자동으로 초기화되며, 필요한 realm과 클라이언트가 자동으로 생성됩니다.

### 개별 서비스 실행

1. **Python 3.12+ 필요**
2. 의존성 설치 (Poetry 사용)

```bash
cd fastapi_be_server
poetry install
```

3. 환경변수(.env) 또는 `app/const.py` 수정 (DB, 인증 등)
4. DB, 외부 서비스(Keycloak, MeiliSearch 등) 사전 준비 필요
5. 서버 실행

```bash
# 개발용 (hot-reload)
poetry run uvicorn app.main:be_app --reload --host 0.0.0.0 --port 8000

# 운영/배포용 (gunicorn)
poetry run gunicorn -k uvicorn.workers.UvicornWorker app.main:be_app --bind 0.0.0.0:8000
```

---

## Keycloak 설정

### Docker Compose로 실행된 Keycloak (자동 설정)

- **URL**: http://localhost:8080
- **관리자 계정**: `admin` / `admin1234`
- **Realm**: `likenovel` (자동 생성)
- **클라이언트** (자동 생성):
  - `service`: 일반 로그인용
  - `service-keep`: 자동 로그인용
  - `admin-cli`: 관리용

### 수동 설정 (Docker Compose 사용하지 않는 경우)

1. Keycloak 서버 설치 및 실행
2. `likenovel` realm 생성
3. 필요한 클라이언트 생성:
   - `service` (secret: `PaP1ULbtlNzXY2XKyw7juZtH0vqYMauP`)
   - `service-keep` (secret: `3ERXPBS4jTNUxy4Ozz3EQOOkRQKsV8iZ`)
4. `app/const.py`에서 Keycloak URL 수정

---

## 최근 주요 개선사항

- **서비스 계층 리팩토링**: CMS 및 파트너 서비스를 기능별로 세분화 (10개 admin 서비스, 5개 partner 서비스)
- **SQL 쿼리 최적화**: 성능 개선을 위한 쿼리 최적화 작업 완료
- **페이징 로직 개선**: 일관된 페이징 처리로 사용자 경험 향상
- **보안 강화**: SQL Injection 취약점 수정 및 하드코딩된 키값 환경변수 분리
- **코드 품질 개선**: 중복 코드 함수화 및 공통 상수 클래스 추가
- **FCM 푸시 알림**: Firebase Cloud Messaging 연동 추가
- **후원 시스템**: 작가 후원 및 정산 기능 구현
- **작품 통계**: 작품별 통계 데이터 수집 및 조회 기능

## 주요 주의사항 및 팁

- **DB/외부 서비스 연결**: MySQL, Keycloak, MeiliSearch, R2 등 외부 서비스가 정상적으로 구동 중이어야 합니다.
- **환경변수/시크릿**: 운영 환경에서는 반드시 민감정보를 환경변수로 분리하세요. (최근 하드코딩된 키값들이 환경변수로 분리됨)
- **로그/폴더 권한**: `logs/` 폴더가 없으면 생성 필요, 권한 문제로 로그가 기록되지 않을 수 있음
- **CORS**: 프론트엔드 도메인(`FE_DOMAIN`, `FE_WWW_DOMAIN`)이 허용되어야 함
- **라우터/서비스 구조**: 기능별로 파일이 많으니, 작업 전 구조를 충분히 파악하세요.
- **Command/Query 패턴**: 라우터는 데이터 변경(`*_command.py`)과 조회(`*_query.py`)로 분리되어 있음
- **보안**: SQL Injection 등 보안 취약점이 수정되었으니, 새로운 코드 작성 시에도 보안을 고려하세요.
- **테스트**: 별도 테스트 코드(`tests/`) 작성 필요
- **Keycloak**: 인증 시스템의 핵심이므로 반드시 정상 동작 확인 필요

## 개발 가이드라인

- **코드 품질**: 중복 코드는 함수화하여 재사용성을 높이세요.
- **상수 관리**: 공통으로 사용되는 상수는 `const.py`의 상수 클래스를 활용하세요.
- **페이징**: 일관된 페이징 로직을 사용하여 사용자 경험을 향상시키세요.
- **서비스 분리**: 도메인별로 서비스를 세분화하여 유지보수성을 높이세요.
- **Command/Query 분리**: 라우터 작성 시 데이터 변경(`*_command.py`)과 조회(`*_query.py`)를 분리하세요.
- **비동기 처리**: SQLAlchemy asyncio와 aiomysql을 사용하여 비동기 DB 작업을 수행하세요.
- **스키마 정의**: API 요청/응답은 반드시 Pydantic 스키마로 정의하세요.

---

## API 문서

서버 실행 후 아래 URL에서 자동 생성된 API 문서를 확인할 수 있습니다:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
