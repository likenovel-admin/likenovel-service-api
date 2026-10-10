# 회원 메일 MCP 확장 준비

상태: 로컬 준비 모듈. MCP 등록·OAuth scope 추가·WAS Workspace credential 연결·배포·실제 회원 조회·실제 Gmail 발송은 수행하지 않았다.

## 현재 코드 근거

- `tb_user`: `user_id`, `email`, `use_yn`, `role_type`, `created_date`.
- `tb_user_notification`: `noti_type='marketing'`, `noti_yn`; 최신 `updated_date`, `id` 순서로 수신 여부를 확인한다. 기존 사용자 설정 서비스는 누락된 설정을 `N`으로 취급한다.
- `tb_ai_reader_agent.user_id` 및 `settings.AI_READER_ACCOUNT_ALLOWED_DOMAINS`: AI 독자 계정 제외.
- 기존 Windows DWD 서버 `C:\Users\Hongsan\.codex\local-mcp\gmail-dwd\server.mjs`: 서비스 계정 RS256 JWT의 `sub`로 Workspace 사용자를 impersonate하고 Google token endpoint에서 access token을 받은 뒤 Gmail API를 호출한다. 네 Workspace 계정 권한은 기존 사용자 확인 baseline이며, 이 준비 작업에서 실제 서버 인증은 검증하지 않았다.

## 준비된 함수 계약

`app/services/ai/mcp_member_mail.py`:

1. `preview_members(owner, db, filters)`는 활성 일반 회원을 parameterized SELECT로 읽는다. `purpose`는 기본 `marketing`, 또는 명시한 `service_notice`. 마케팅은 최신 수신동의 `Y`인 회원만 포함한다. 가입 구간은 DB의 기존 local-time convention으로 `[joined_from, joined_before)`이다. 정확한 `user_ids`도 지원한다. AI 독자, 탈퇴·휴면 `use_yn=N`, 관리자, 잘못된 이메일, 중복 주소, admin 발신자 주소는 제외한다. 500명 초과 시 전체 실패하여 일부 대상만 잘라 준비하지 않는다.
2. 반환은 인원·필터·hash·수신자 ID와 마스킹 샘플만 포함한다. 정확한 수신자 목록은 기존 MCP receipt DB에 Fernet 암호화하여 보관한다.
3. `prepare_campaign(owner, preview_id, subject, body)`는 고정 발신자 `admin@likenovel.net`, 정확한 대상, 제목·plain-text 본문, 목적을 함께 묶어 SHA256 hash를 만든다. 미리보기와 캠페인은 15분 후 만료된다. 원문 제목·본문을 계획 확인용으로 반환한다. 파일 첨부·임의 From/To/CC·임의 외부 수신자·HTML은 지원하지 않는다.
4. `record_user_authorization(...)`는 **trusted user-command ingress 전용이며 MCP tool로 등록하면 안 된다**. 직접 실행 지시 또는 구체적 계획 승인이라는 실제 사용자 이벤트를 부모 adapter가 검증한 뒤, 해당 이벤트 참조와 정확한 campaign hash를 기록해야 한다. Dot의 자율 제안·LLM이 만든 evidence 문자열·구좌 자동 실행 허가를 메일 발송 승인으로 바꾸면 안 된다. 직접 실행 지시는 이미 승인이므로 같은 지시에 재승인을 묻지 않는다.
5. `send_campaign(owner, campaign_id, db)`는 hash·사용자 지시·현재 회원 상태/마케팅 수신동의·exact audience를 다시 확인한다. 대상 변경 시 발송하지 않고 새 미리보기와 새 승인/지시를 요구한다. 기존 receipt의 atomic consume으로 중복 호출을 차단한다. 발신자/대표 To는 admin 고정, 수신자는 전원 BCC, CC 없음이다.
6. `WorkspaceAdminGmail`는 신규 패키지 없이 기존 PyJWT/httpx로 기존 DWD 패턴을 구현한다. Google URL·impersonated admin subject를 고정한다. 키 파일은 WAS의 private absolute path이며 token URI도 Google 공식 주소만 허용한다. 키·token·수신자 주소를 로그나 응답에 출력하지 않는다.
7. `verify_sent(owner, campaign_id)`는 Gmail `format=full`로 SENT label, From/To/CC/BCC exact set, 제목, Message-ID, UTF-8 본문을 검증한다. 응답 소실은 고정 RFC822 Message-ID로 Sent를 검색한다. 일치하는 단일 Sent가 없거나 내용이 다르면 `sent_verified=false`; **발송되지 않았다고 단정하거나 자동 재발송하지 않는다**. `verified`는 Gmail의 보낸편지함에 정확한 메시지가 확인됐다는 뜻이며 수신자 도착·열람을 보장하지 않는다.

## 부모 연결 시 필요한 작업

- 회원 읽기 `likenovel.mcp.members.read`, 메일 발송 `likenovel.mcp.mail.write`를 기존 구좌 권한과 별도로 OAuth와 MCP guards에 연결한다.
- 기능 연결은 기존 구좌 자동허가에 포함되지 않는다. 회원 메일은 직접 실행 지시 또는 구체적 계획 승인에만 의존하며 자율 제안으로 실행하지 않는다.
- `member_mail_enabled=true`와 `member_mail_service_account_file=<WAS private credential path>`는 보안 검토·정확한 서버 credential 연결 이후에만 설정한다. 현재 두 설정이 없으면 명시적으로 disabled이다. Windows credential을 채팅/저장소에 복사하지 않는다.
- `capability_status()`의 configured/enabled는 설정 유무이고 `runtime_connection_verified=false`는 실제 인증 미검증을 뜻한다. 설정만 보고 연결 성공으로 보고하지 않는다.
- 일반 서비스 공지는 프로모션 내용을 담지 않는 실제 운영 공지로 한정한다. 프로모션 메일은 `marketing` 목적을 써서 수신동의를 확인한다.
- 적극적 제안/알림은 캠페인 계획·부족한 조건·대상 변경·실패/불명확한 결과를 Dot에 보고하는 별도 흐름으로 연결한다. 준비 모듈은 자율 제안을 승인으로 승격하지 않는다.
- Gmail timeout/readback mismatch는 실패/미확인 알림을 만들고 정확한 Sent 검증으로만 해결한다. 무조건 재전송 버튼이나 일반 retry loop에 연결하지 않는다.

## 검증 범위

`tests/test_mcp_member_mail.py`는 실제 암호화·SQLite receipt를 사용하고 회원 DB/Gmail만 mock한다. parameterized SQL 계약, 주소 비노출, 최대 인원/탈퇴형 주소/AI domain 제외, injection/기간/만료, 승인 hash·발송 비활성화, BCC MIME, 발송 후 exact full readback, 응답 소실→Sent 확인, 대상 변경 시 발송 전 차단을 검증한다.

실제 MySQL schema/query 실행, Workspace 서버 인증, Gmail 발송, Dot tool 호출, OAuth 권한 확대, cloud notification은 미검증이다.

Google 공식 계약: [MIME/raw Gmail 발송](https://developers.google.com/workspace/gmail/api/guides/sending), [서비스 계정과 DWD](https://developers.google.com/identity/protocols/oauth2/service-account), [messages.get format](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get).
