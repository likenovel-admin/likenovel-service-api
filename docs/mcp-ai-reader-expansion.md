# AI 독자 MCP 확장 준비

상태: 로컬 서비스 모듈 및 mock 단위 검증. MCP 도구 등록·OAuth 권한 추가·배포·운영 투입은 아직 하지 않았다.

`app/services/ai/mcp_ai_reader.py`는 기존 `admin_ai_reader_service`와 관리자 요청 schema를 재사용한다.
회원 생성 또는 LLM/배치 실행은 호출하지 않는다.

## 계약

- `status(starts_on=None, page=1)`: 현재 CMS 독자/일별 스케줄을 페이지당 100명 조회. 이메일은 출력에서 제거한다.
- `plan(owner, count, starts_on, duration_days, mode="resume", email_prefix=None)`: 읽기 전용 미리보기.
  인원은 기존 schema의 1~1,000명, 기간은 1~90일, 시작일은 한국시간 오늘 이후의 `YYYY-MM-DD`.
  시작일 포함 N일이며 종료일은 시작일 + N - 1일이다. 기존 활동 패턴과 종료 후 자동 일시중지를 재사용한다.
  새 계획은 `auto_start_schedule_start_date`를 저장하며 워커의 생성·세션/행동 선택·실행 전 검증에
  시작일 하한과 종료일·종료시각 상한을 적용한다. 미래 계획을 미리 적용해도 시작 전 투입은 차단한다.
  즉시 시작은 꺼져 있으며, 기존 CMS 기본 시간표에 따른다. 시간 단위 시작 지정은 미지원이다.
- `bootstrap`: 기존 전용 AI 회원만 사용한다. `email_prefix`가 필요하며 부족분 자동 계정 발급·부분 인원 적용은 금지한다.
- `resume`: 선택한 paused 독자만 재개한다. 다른 active 독자의 상태는 바꾸지 않는다.
- `restart`: 기존 CMS 전체 재시작이다. 선택한 독자 외 기존 독자를 일시중지하고 기존 ready/running 스케줄과 queued/running 행동을 정리한다.
  계획의 `restart_affects_all_existing_agents`와 `existing_agent_count`로 전체 영향 범위를 알린다.
- `apply(owner, plan_id, authorized_plan_hash=None)`: 직접 지시 또는 구체적인 계획 승인으로
  서버가 확보한 hash가 저장된 immutable 계획 hash와 정확히 같아야 한다.
  이 인자는 모델의 자율적 도구 입력에서 가져오면 안 된다.
  `ai_reader_writes_enabled`도 별도로 true여야 하며 기본 미허용이다. 일반 구좌 `writes_enabled`와 독립적이다.

읽기 scope `likenovel.mcp.ai-reader.read`, 쓰기 scope `likenovel.mcp.ai-reader.write`를 제공한다.
모듈 자체는 인증 계층이 아니므로 외부 도구로 직접 노출하면 안 된다. 등록 측이 관리자 OAuth subject와 scope를 검증해야 한다.
현재 구좌의 자동 운영 허가는 AI 독자 실행 허가로 사용하지 않는다.

## 변경·중복·기간 확인

계획은 기존 외부-release SQLite receipt 저장소에 owner별로 보관하며 30분 후 만료한다.
요청·dry-run preview·현재 전체 AI 독자 구성의 hash를 저장하고 적용 전에 실제 구성을 다시 읽는다.
대상과 기간의 변경은 새 계획으로 처리하며 저장된 plan payload의 hash도 다시 확인한다.
기존 CMS dry-run HMAC token을 함께 적용한다.

적용은 전체 독자 행을 잠근 외부 MySQL transaction 안에서 수행한다.
CMS 함수의 자체 `commit()`은 bound `AsyncSession(join_transaction_mode="create_savepoint")`의 savepoint를
종료하며 외부 transaction/행 잠금은 유지된다.
독자 active 상태, 계획 활동 패턴(자동 중지 날짜 포함), 인원, 일별 스케줄의 시작·종료일과 날짜 수를 readback한 뒤 외부 commit한다.
기간 밖의 오래된 스케줄이 남아 있어도 새 세션·행동 선택은 금지하며 자동 중지를 늦추지 않도록
만료 판정은 종료시각 전 시작한 스케줄만 대기한다. 메타데이터가 없는 기존 독자의 기존 동작은 유지한다.
계획 consume과 durable applying intent가 적용 전에 기록되므로 동일 plan은 재실행하지 않는다.
commit/응답 경계의 실패 또는 프로세스 중단 때 `applying`은 성공으로 해석하지 않으며 운영자가 DB readback으로 조정해야 한다.
현재 구현은 불확실한 intent의 자동 복구/재실행을 제공하지 않는다.

## 남은 연결 작업 / 미검증

- 상위 MCP 등록, OAuth scope 노출/동의, 직접 사용자 지시를 검증해 hash를 공급하는 권한 wrapper.
- 실제 MySQL/InnoDB와 CMS 서비스에 대한 외부 transaction/savepoint·기간 readback 통합 검증.
  2026-10-11 운영 MySQL에서 상수 JSON/날짜 derived `SELECT` 7개 경계(시작 전/정각/종료일/
  종료 후/오래된 날짜의 종료 후 실행/메타데이터 없는 기존 독자)를 읽기 전용으로 검증했다.
  같은 연결에서 `AsyncSession(create_savepoint)`의 commit·rollback이 외부 transaction을 유지하는
  것도 `SELECT`만으로 확인했다. 실제 CMS 데이터 write·행 잠금·최종 rollback 검증은 아직 하지 않았다.
  mock 단위 테스트와 이 상수 SQL 검증은 실DB 동시성·워커 자연발동의 증명이 아니다.
- 실제 워커가 새 스케줄을 소비하고 기간 종료 후 중지하는 자연발동 검증.
- 사용자가 지정할 정확한 인원·시작일·기간·모드. 아직 운영 계획이나 독자를 생성하지 않았다.
- 새로운 전용 회원이 필요하면 기존 CMS의 계정 발급 경로에 대한 별도 계획과 명시 지시가 필요하다.
  현재 MCP 준비 모듈은 기존 회원만 지원한다.

운영 DB의 Decimal 예산은 JSON에서 소수 정밀도를 보존하는 문자열로 전달하고, 적용 readback은 Decimal 숫자값으로 비교한다. 동일 예산의 scale 차이는 오류로 판단하지 않으며, 실제 숫자가 달라지면 적용 검증에 실패한다.
