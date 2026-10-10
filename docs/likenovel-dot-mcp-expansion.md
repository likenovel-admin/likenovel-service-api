# 라이크노벨 닷 MCP 확장 준비

2026-10-11 사용자 요청. 상태: 소스 조사 및 도구 계약 준비. 아래 도구는 아직 설치된 MCP에 노출하거나 활성화하지 않았다. 현재 구좌 7개 도구의 자동운영 허가가 다른 영역에 자동 확장되지는 않는다.

## 기존 코드 연결점

| 영역 | 현재 코드 | 확장 입력 및 결과 |
|---|---|---|
| AI 독자 | `app/services/admin/admin_ai_reader_service.py`, `app/schemas/admin.py`, admin `ai-readers` query/command | 인원, 시작일(KST), 운영일수, 시간대, 일일 세션/LLM 예산, 읽기/댓글 설정; dry-run 대상 수와 종료일, 적용 후 active 및 schedule 수 |
| 회원 메일 | `app/services/admin/admin_user_service.py`의 `tb_user`, `app/services/user/user_notification_service.py`의 `tb_user_notification` | 대상 조건, 메일 목적, 제목/본문, 발송시각; 수신자 스냅샷 수, 제외 이유, 발송별 receipt 및 Sent readback |
| 백화무료 | `app/services/partner/partner_product_service.py:put_product`, `app/schemas/partner.py` | 정확한 작품, 라이크노벨 CP identity, 시작/종료, `hundred_free_campaign_enabled`, `hundred_free_campaign_ends_at`; 1~100화 무료 설정 및 종료 복원 readback |
| 배너 | `app/services/admin/admin_event_service.py`, `PostBannerReqBody`, `PutBannerReqBody` | PC/모바일 이미지, 위치/세부위치, 노출 기간, 순서, 링크; image id, banner id, 공개 노출 및 링크 확인 |
| 유료전환 | `app/services/admin/admin_user_service.py:accept_apply_rank_up`, `apply_paid_conversion_by_admin`, `PostApplyPaidConversionReqBody` | 신청 id/작품, 승인 여부, 유료 시작 회차, 기다리면 무료 옵션; 승인과 실제 유료 적용을 별도 receipt로 확인 |

## 예정 도구 계약

- `likenovel_ai_reader_snapshot`: 기존 인원/상태/일정 조회.
- `likenovel_plan_ai_readers(count, starts_on, duration_days, ...)`: 기존 `apply=false` dry-run으로 실제 가능한 대상과 비용 관련 예산 확인. `bootstrap`(새 전용 계정 생성), `resume`(기존 paused 재개), `restart`(기존 전체 활동 교체)는 구분한다.
- `likenovel_apply_ai_reader_plan(plan_id)`: 사용자가 지정한 인원과 기간만 적용. `auto_pause_schedule_end_date` 기존 처리를 사용하고 신규 독자 worker를 별도 구현하지 않는다. 재시도는 동일 계획 receipt로 합친다.
- `likenovel_pause_ai_readers(plan_id)`: 해당 계획이 만든/재개한 독자만 멈춘다. 기존 `pause-all`은 명시적인 전체 중지 지시에만 사용한다.
- `likenovel_prepare_member_mail(filters, purpose, subject, body, send_at)`: 회원 테이블을 페이지 단위로 조회하고 `use_yn`, 실제 이메일, 중복, AI 전용/관리자 계정, 목적에 따른 수신설정을 검증한다. `noti_yn` 하나만으로 모든 메일 동의를 추정하지 않는다. 마케팅 목적은 `noti_type=marketing` 설정과 실제 정책을 확인한다.
- `likenovel_send_member_mail(campaign_id)`: 발신자 고정 `admin@likenovel.net`, 수신자 확정 스냅샷/본문 해시/배치별 receipt 사용. 대량 주소를 다른 수신자에게 노출하지 않는다. 불확실한 Gmail 응답은 Sent 조회로 조정하며 즉시 재발송하지 않는다.
- `likenovel_plan_hundred_free(product_id, cp_identity, starts_at, ends_at)`: 라이크노벨 CP 소유/계약 범위, 현재 유료작, 충분한 회차, 종료일, 기존 캠페인 확인. 기존 `put_product` 전체 요청의 비대상 필드를 현재 값으로 유지한다.
- `likenovel_apply_hundred_free(plan_id)`: 기존 파트너 서비스와 캠페인 테이블 사용. 관리자 전체권한으로 CP identity를 흉내내지 않는다. 예약 시작/종료와 1~100화 공개/무료 실제 노출 확인.
- `likenovel_prepare_banner(brief, products, placements, starts_at, ends_at, url)`: 표지/제목/혜택 근거와 현재 CMS 이미지 규격을 확인해 PC/모바일 결과물을 준비한다. 이미지 생성은 닷의 이미지 생성 도구 또는 검증된 서버 이미지 공급자를 사용한다. 현재 Pillow는 검증용이며 이미지 생성 모델이 아니다.
- `likenovel_publish_banner(plan_id)`: 승인된 이미지 업로드/파일 등록을 통해 image id를 얻고 공식 배너 서비스를 호출한다. 대상 위치의 기존 순서는 보존하며 동일 계획 중복 게시를 막는다. 공개 이미지와 링크/노출기간 확인.
- `likenovel_review_paid_application(apply_id)`, `likenovel_accept_paid_application(plan_id)`, `likenovel_apply_paid_conversion(plan_id)`: 신청 승인과 실제 가격 전환은 별개로 처리한다. 현재 서비스는 승인된 일반연재 무료작만 실제 적용 가능하므로 해당 검증을 유지한다.

## 준비된 것과 남은 연결

- 소스에서 AI 독자 `schedule_date`, `schedule_duration_days`, `agent_count`, 종료 자동정지와 dry-run을 확인했다. 인원/기간/시작일은 사용자가 지정할 예정이다.
- 백화무료 기존 서비스는 유료작만 허용하고 무료 범위를 1~100으로 정하며 종료 일시를 필수로 받는다. 소유/계약 권한도 기존 CP 검증을 유지한다.
- 배너는 `position`, `division`, `show_start_date`, `show_end_date`, `show_order`, `url`, `image_id`, `mobile_image_id`를 사용한다. 실제 규격/업로드 경로 및 이미지 생성 공급자는 구현 단계에서 readback이 필요하다.
- 기존 Google Workspace DWD 경로는 Windows 로컬에 있다. PC가 꺼져도 발송하려면 서버용 제한된 admin 발송 인증을 별도로 연결해야 한다. 로컬 키를 문서/닷/소스에 복사하지 않는다. 계정 권한이 없다고 추정하지 말고 기존 인증 로직을 재사용한다.
- 현재 로컬 계정 문서는 CMS 관리자용 1개만 확인했다. 라이크노벨 CP의 실제 로그인 identity/허용 작품을 확인한 다음 해당 파트너 권한으로 연동한다.
- 확장 시 read / AI 독자 / 메일 / CP 캠페인 / 배너 / 유료전환을 분리된 OAuth scope와 서버 기능 스위치로 제한한다. 도구 목록 변경 후 닷 플러그인을 새로고침하고 넓어진 영역에 대한 1회 계정 권한 허용을 별도로 받는다.
- 영수증/동시 변경 방지/실제 readback을 재사용하되 메일, 배너, 캠페인은 같은 DB transaction으로 묶을 수 없으므로 단계별 상태와 실패 복구를 기록한다. 부분 실패를 전체 성공으로 보고하지 않는다.

## 검증 및 실행 경계

이번 준비는 코드 및 스키마 조사이며 운영 인원 투입, 회원 이메일 추출/발송, CP 로그인, 무료회차 변경, 배너 생성/게시, 유료 승인·가격변경은 실행하지 않았다. 회원 개인정보와 OAuth/Workspace 자격증명은 이 문서에 포함하지 않았다.

구현 수용기준: exact identity/scopes, dry-run과 실제 대상 수 비교, 같은 계획 재시도 중복 효과 없음, concurrent edit 차단, 시작/종료 KST 검증, 실패/부분성공 receipt, 공개 readback 또는 Gmail Sent readback. 실제 입력을 받으면 먼저 해당 계획을 구체화하고 허용된 영역만 실행한다.
