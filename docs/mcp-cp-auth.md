# 라이크노벨 CP 계정 별도 연결

관리자 OAuth는 CP 인증으로 취급하지 않는다. `mcp_cp_auth`는 기존 파트너 계정 로그인과 같은 Keycloak keep-sign-in 클라이언트를 사용하고 새 클라이언트·패키지·관리자 권한을 추가하지 않는다.

- `begin_connection(owner)`는 설정된 관리자 소유의 10분 연결 URL을 반환한다. CP 비밀번호는 MCP 도구 인자가 아니며 사용자가 라이크노벨의 HTML 로그인 화면에서 직접 입력한다.
- `CP_AUTH_ROUTES`는 GET/POST `/oauth/cp/login`과 동일 사이트 결과 화면 `/oauth/cp/connected`를 제공한다. 상위 서버에서 명시적으로 등록해야 사용할 수 있다.
- `get_actor(owner)`는 비동기 함수로 실제 CP의 `{user_id, role: "CP", company_name}`만 반환한다. 토큰은 반환하지 않는다.
- `connection_status(owner)`는 비동기 함수로 실제 인증 및 회사 권한을 확인하고 연결 여부를 반환한다.
- `connect_credentials(owner, username, password)`는 사용자가 제공한 계정으로 서버에서 최초 연결하는 내부 비동기 함수다. HTML 로그인과 동일한 인증 검증을 재사용한다. MCP 도구로 공개하지 않으며 반환값은 CP 실행 계정 정보뿐이다.

설정의 `cp_company_name`은 실제 승인된 CP 회사명과 정확히 일치해야 한다. 로그인·상태 조회·실행 계정 조회 때마다 기존 JWT 검증과 `check_user` 및 승인 CP 회사 조회를 수행한다. `check_user(role="partner")`가 관리자·작가도 반환할 수 있으므로 반환 역할이 정확히 `CP`인지 추가 검사한다. 관리자 대행·계정 impersonation은 허용하지 않는다.

연결 요청은 관리자 소유자·만료·서버 저장 CSRF·보안 쿠키·동일 Origin·일회 사용에 묶인다. 폼 크기 제한과 시간당 시도 제한을 적용한다. Keycloak offline access/refresh 토큰은 기존 Fernet 키로 암호화해 private SQLite에 저장하며 CP 비밀번호를 저장하지 않는다. 갱신 시 기존 CP subject를 유지하고 역할·회사 권한을 재검사한다. 갱신이 실패하면 암호문을 지우고 재연결을 요구한다.

CP 연결은 인증 기반 준비다. 100화 무료 설정, 배너 노출 및 다른 프로모션 실행은 사용자 지시 또는 승인과 해당 기능의 실행 검증을 별도로 충족해야 한다. 이 모듈은 프로모션이나 CMS 데이터 변경을 실행하지 않는다.
