# 라이크노벨 닷 MCP 운영 확장

2026-10-11. 등록 코드는 기존 구좌 7개에 확장 15개를 추가한다. 운영 배포·계정 연결의 최종 상태는 실제 MCP status와 배포 ledger로 확인한다. 모듈 준비와 실제 배포를 혼동하지 않는다.

## 사용자 실행 경계

- 기존 일반 구좌 5개 매일 10:00 KST, 유료 단일구좌 3개·문구 월·목 10:05는 기존 상시 허가를 유지한다.
- AI 독자·회원메일·100화 무료·배너 게시·심사 승인·실제 유료 전환은 구체적인 계획에 대한 사용자 실행 승인이 필요하다. 조회·계획·이미지 시안·배치 제안은 적극적으로 준비한다.
- 모델이 만든 승인 문자열은 승인 증거가 아니다. 준비 도구는 서버에 고정된 계획과 15분 유효한 일회 승인 nonce를 만들고, nonce는 MCP `_meta`로 승인 화면에만 전달한다. `content`·`structuredContent`·공개 receipt에는 nonce가 없다.
- 실행 도구는 `ui.visibility=[app]`/private로 모델에 공개하지 않는다. 사용자 승인 버튼만 정확한 nonce를 전달한다. 닷이 브라우저로 대신 버튼을 누르거나 자율 제안을 실행 지시로 바꾸지 않도록 닷 규칙도 함께 유지해야 한다.
- 실행 시 owner·kind·계획 hash·TTL·atomic consume·각 쓰기 scope·기능 스위치를 검사한다. 직접 지시도 모델의 자기 주장으로 인증하지 않으며, 호스트가 검증한 승인 화면에서 구체화한다.
- nonce는 승인 화면용 bearer capability다. 전체 MCP 응답을 읽을 수 있는 외부 API 클라이언트를 사람으로 증명하는 수단은 아니다. 이 연결은 해당 계정의 닷·사용자 화면으로 한정한다.

## 기능과 실제 도구

| 기능 | 조회·준비 | 실행·결과 |
|---|---|---|
| AI 독자 | `likenovel_ai_reader_status`, `likenovel_prepare_ai_readers(count,starts_on,duration_days,mode)` | 기존 CMS dry-run/HMAC, 정확한 인원·일수·KST 시작일·종료 자동정지; 승인 뒤 서비스 재사용. 미래 시작·기간 밖 잔여 스케줄·액션은 공유 guard로 차단 |
| 회원메일 | `likenovel_member_preview(filters)`, `likenovel_prepare_member_mail(preview_id,subject,body)` | admin@likenovel.net 고정·전원 BCC, 최신 마케팅 동의와 실제 회원 테이블, exact audience/text hash, DWD와 Sent readback. 단일 캠페인 최대 500명; 초과 전체 발송은 분할 manifest 구현 전 차단 |
| 100화 무료 | `likenovel_cp_connection`, `likenovel_promotion_snapshot`, `likenovel_prepare_hundred_free(product_id,ends_at)` | 별도 실제 CP OAuth 로그인·승인 회사 exact·소유 작품 검증. 즉시 시작과 명시 종료; 기존 복원 정책은 1~25 무료/26부터 유료 |
| 배너 | `likenovel_banner_brief`, `likenovel_prepare_banner(request,file,mobile_file)` | 닷 자체 이미지 생성 → ChatGPT fileParams → private 원본 저장·실제 픽셀/hash 검사 → 시안 승인 → 기존 storage upload + CMS insert. 기존 위치 순서 CAS·중복 게시 방지·공개 이미지/링크 확인 |
| 유료전환 | `likenovel_paid_applications`, `likenovel_prepare_paid_approval`, `likenovel_prepare_paid_conversion(apply_id,paid_episode_no)` | 심사 승인과 실제 유료 설정은 별도 scope/계획. 실제 가격은 기존 분 배치 반영 뒤 확인. 저장 완료를 공개 전환 완료로 보고하지 않음 |
| 상태·결과 | `likenovel_expansion_status`, `likenovel_expansion_receipt` | 기능별 설정/권한과 실제 영수증을 조회. 불확실한 실행은 즉시 반복하지 말고 먼저 결과 확인 |

## 배너 이미지와 배치 제안

- 닷이 후보 작품, 실제 혜택 근거, 문구, 이미지 시안, PC/모바일 규격, 위치, 순서, 링크, 기간을 묶어 제안한다. 이미지 제작을 사용자의 매번 요청에만 맡기지 않는다.
- 같은 작품을 며칠 안에 다시 제안하지 않는다. 최근 7일 제안·노출 이력을 우선 제외하고, 남은 신작·기존작에 동등하게 기회를 준다. 조회수·반응·오래된 정도로 기회를 편중하지 않는다.
- CMS 규격 SSOT: main-top/paid/review 364×414, companyNotice 734×367, main-mid 1080×116, viewer PC839×122/모바일375×122. 규격 없는 position은 명시된 width/height가 필요하다.
- 실제 파일은 허용된 ChatGPT file host, public DNS, redirect 금지, 15 MiB 제한을 검사한다. 이미 검증한 원본에서 만든 제한된 미리보기를 승인 화면에 표시한다. 원본 파일은 변경하지 않는다.
- 작품·혜택 근거가 없는 과장 문구를 만들지 않는다. 유료/무료 변경 승인 전의 시안은 실제 게시와 구분한다.

## 인증·배포·검증

- 기존 관리자 인증 서버 client/PKCE와 암호화 offline grant를 재사용하며 realm 권한을 만들지 않는다. 확장은 별도 OAuth scopes를 받는다.
- 실제 CP 계정은 서버의 `mcp_cp_auth`에서 로그인·role CP·승인 회사명을 검증한다. 관리자 identity를 CP로 바꾸지 않는다. CP 비밀번호·토큰을 닷·tracked 코드·문서에 반환하지 않는다.
- Workspace 키는 서버의 private mode600 파일에만 두고 `member_mail_service_account_file`에서 참조한다. 앱 발신자는 admin 계정으로 제한한다. 발송 없이 DWD profile 검증이 가능하다.
- 기능별 `ai_reader_writes_enabled`, `member_mail_enabled`, `promotion_writes_enabled`, `banner_writes_enabled`, `paid_conversion_writes_enabled`를 독립적으로 적용한다.
- 회귀 검증에는 SDK/PKCE/refresh/revocation, 승인 nonce wire·owner/replay/변조·scope, 위젯 envelope와 명시 클릭, AI 기간 bounds, Gmail 불확실 발송/Sent, 실제 기존 서비스 호출, 배너 픽셀·SSRF·CAS·이미지 보존과 공개 검증이 포함된다.
- 구체적인 운영 계획 없이 AI 독자 투입·회원메일 발송·무료회차 설정·배너 게시·유료전환을 시험하지 않는다. 계정 인증/읽기·이미지 시안 준비까지의 live 증거와 실제 실행/자연발동은 별도로 보고한다.
