# 프로모션 / 배너 / 유료 승인 MCP 확장 준비

이 모듈은 도구 등록과 OAuth scope 등록 없이 준비된 어댑터다. 기본 쓰기는
비활성이고 기존 구좌 자동 실행 허가는 이 모듈에 적용되지 않는다.
사용자 직접 실행 지시 또는 대상·기간·조건이 고정된 계획 승인이 실행 허가다.
직접 지시가 이미 있으면 중복 확인을 요구하지 않는다. Dot의 자율 제안만으로는 실행하지 않는다.

## 계획과 적용

- `prepare_hundred_free`: 서버에서 조회한 작품/회차/진행 중 캠페인을 고정한다.
  인증된 CP 본인 소유·계약 작품, 기존 100원 유료 연재, 1~100회차 존재,
  명시된 타임존의 종료 일시를 요구한다. 관리자 identity를 CP로 치환하지 않는다.
- `prepare_paid_approval`: 활성 `review` 신청과 CP 계약을 계획에 고정한다.
  기존 `admin_user_service.accept_apply_rank_up` 재사용은 심사 승인만 수행한다.
  가격 저장이나 실제 유료 전환은 별도 운영 단계다. 자동으로 가격을 설정하지 않는다.
- `prepare_banner`: 기존 `PostBannerReqBody`와 위치 검증기를 사용한다.
  서버의 허용 호스트 목록에 속한 HTTPS 링크와 실제 업로드된 파일 ID가 필요하다.
  준비는 파일 ID의 실제 업로드나 픽셀을 증명하지 않으며, 배너 적용은 명시적으로 막힌다.
- `apply_plan`: 신규 scope, 정확한 승인 plan ID, 같은 OAuth owner/actor를 요구한다.
  30분 계획 만료, 쓰기 기본 비활성, 소유권 확인, 트랜잭션 안의
  product/application/episode/campaign `FOR UPDATE` 및 expected-before 비교를 사용한다.
  기존 `mcp_store`의 durable claim이 중복 실행을 막고, 불확실한 적용 상태는 자동 재시도하지 않는다.
  저장 후 readback을 검사하고 비대상 상품 필드 변경은 rollback한다.
  공개 노출은 아직 검증되지 않았으므로 `public_verified=false`다.

호스트만 제공하는 `actor`, `scopes`, `approved_plan_id`, `writes_enabled`,
`expected_cp_company_name`은 모델 호출 인자로 노출하면 안 된다.
직접 지시/계획 승인을 처리하는 첫 번째 당사자 서버에서 저장한 intent와
계획 ID를 연결하고, actor는 기존 OAuth 및 DB의 현재 역할 검증 결과를 사용한다.
`writes_enabled=True`만으로 사용자의 승인 의도를 만들 수 없다.

별도 scope:

| 동작 | scope |
| --- | --- |
| 100화 무료 설정 | `likenovel.mcp.promotion.write` |
| 배너 게시 | `likenovel.mcp.banner.write` |
| 유료 심사 승인 | `likenovel.mcp.paid-approval.write` |

현재 OAuth scope, `mcp_server.py`, config, 공유 receipt/schema 파일은 변경하지 않았다.
실제 CP 로그인·매핑과 신규 scope의 재동의가 끝나기 전에는 등록/활성화하지 않는다.

## 기존 서비스 SSOT와 복원 정책

- `partner_product_service.put_product`는 `hundred_free_campaign_enabled`,
  `hundred_free_campaign_ends_at`를 받아 1~100화를 무료로 변경한다.
  유료작 UCI/ISBN과 연재 가격 규칙을 기존 서비스가 다시 검사한다.
  서비스는 `status_code`를 필수처럼 검증하고 두 장르 ID를 항상 비교하므로
  현재 `status_code`, `primary_genre_id`, `sub_genre_id` 값을 그대로 patch에 포함한다.
  장르를 모두 생략하면 기본값 `None == None`으로 거절되는 경로를 실제 서비스
  검증·query builder 테스트(DB transport만 대체)로 재현하고 방지했다.
- 종료 시 복원은 **1~25화 무료, 26화부터 유료**로 고정되어 있다.
  캠페인 전 임의의 무료 범위를 복원하는 기능은 아니다.
  기존 `dist/batch/free_episode_campaign_expire_batch.sql`과 cron 등록은 5분 주기다.
  실제 운영 서버의 배치 최근 성공·실행 등록은 이 준비 작업에서 미검증이다.
- CP 소유권은 `author_id` / `user_id` / `cp_user_id`로 검사하고
  현재 승인된 CP 회사명을 `get_approved_cp_company_name_by_user_id`로 재확인한다.
  서버 config의 검증된 LikeNovel CP 회사명과 exact match가 필요하다.

## 배너 이미지와 연결에 필요한 작업

현재 CMS 실제 업로드는 `POST /v1/command/storages/upload-url`
(`group_type=user`, 파일명) → 반환 presigned URL에 이미지 바이트 PUT → 파일 ID로
`admin_event_service.post_banner` 순서다. 임의 파일 ID나 dummy 이미지를 게시하지 않는다.
이미지 제작용 생성 모델은 이 모듈에 연결되지 않았다. Pillow는 검증/변환 도구다.

CMS `lib/bannerImagePolicy.ts`의 현재 권장 규격:

| 위치 | 이미지 | 모바일 |
| --- | --- | --- |
| main-top / paid / review | 364×414 | 같은 파일 |
| companyNotice | 734×367, 2:1 | 같은 파일 |
| main-mid | 1080×116 | 별도 업로드 없음 |
| viewer | 839×122 | 375×122 |

main-bot / promotion / search는 현재 정책 함수에 크기 규격이 없다.
추정 크기를 SSOT로 등록하지 않는다. 이미지 생성 후 픽셀·문구·권리·링크를
검수하고 업로드 완료를 재검증해야 한다. 동일 위치의 전체 순서 CAS,
`post_banner` 후 신규 banner ID 확인, 공개 배너 readback 어댑터가 필요하다.

## 아직 연결되지 않은 경계

1. 인증된 LikeNovel CP OAuth 또는 검증된 account mapping.
2. 신규 scope의 승인과 첫 번째 당사자 intent 저장/plan 연결.
3. MCP tool 등록 및 신규 config별 비활성 → 활성 절차.
4. 이미지 생성 provider, 실제 upload/pixel proof, 배너 public readback.
5. 100화 무료 공개 가격/readback과 실제 종료 복원 배치 실행 확인.
6. 유료 승인 이후 별도의 실제 가격/전환 단계에 대한 구체적인 사용자 지시.

대상·기간·배너·유료 심사 후보는 미리 알려 줄 수 있지만, 어떤 작품에 무엇을
적용할지 사용자가 지정하거나 구체적 계획을 승인하기 전에는 실행하지 않는다.
준비만 된 파일을 설치·운영 완료로 보고하지 않는다.
