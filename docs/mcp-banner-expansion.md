# 닷 이미지 생성과 배너 게시 확장

현재 모듈은 `app/services/ai/mcp_banner.py`이며 운영 write를 실행하지 않은 준비 코드다. tool 등록, 확장 OAuth scope, 닷 파일 전달과 실제 CMS 공개 조회 연결은 부모 구현/통합 검증 범위다.

## 호출 계약

- `banner_brief(position, division=None, *, product_title, offer, link, width=None, height=None)`는 닷 native 이미지 생성에 사용할 정확한 규격·작품명·확인된 행사 문구·링크와 기존 배너를 유지하는 뒤쪽 배치 권고를 반환한다. 생성 provider나 API 패키지를 새로 추가하지 않는다.
- `prepare_asset(owner, request, file, db, *, mobile_file=None, width=None, height=None)`는 파일을 읽고 실제 이미지 검증 후 비공개 서버 파일 및 계획 영수증을 저장한다. 원격 저장소 업로드와 사이트 게시는 수행하지 않는다. request에는 position/division/title/show_start_date/show_end_date/show_order/url만 허용한다. `image_id`는 모델이 공급하지 않는다.
- `publish_prepared(owner, plan_id, db, actor, *, approved_plan_id=None, scopes=(), writes_enabled=False)`는 첫 호출부터 끝까지 같은 게시 지시/정확 계획 승인을 사용한다. 이 지시에 이미지 업로드가 포함된다. 구좌 자동화의 기존 scope는 허용하지 않으며 별도 `likenovel.mcp.banner.write`와 서버 활성화, trusted host가 공급하는 관리자·정확 승인 ID가 모두 필요하다. 호출 DB 세션은 사용 전이어야 하며 함수가 트랜잭션을 소유한다.
- `verify_public(owner, plan_id)`는 기간 안에 공개 API의 배너 ID·링크 및 CDN 이미지의 실제 픽셀·SHA256을 확인한다. 예약 기간 밖에서는 공개 노출 성공을 주장하지 않는다.

`get_previews(owner, plan_id)`는 승인 UI용 private helper다. 검증된 원본 SHA256과 실제 픽셀을 다시 확인한 뒤 최대 800×600, 각 300KB 이하 WEBP 미리보기를 반환한다. 원본 바이트는 변경하지 않는다. data URL은 모델 content에 넣지 않고 host 응답의 private `_meta`에서만 렌더해야 한다. 사용자가 실제 이미지를 검토한 정확한 계획을 승인한 후 게시한다.

## 이미지와 파일 입력

규격 SSOT는 `cms/lib/bannerImagePolicy.ts`다. main/top, paid, review는 364×414, companyNotice는 734×367, main/mid는 1080×116, viewer는 PC 839×122와 별도 모바일 375×122다. 이 확장은 CMS의 권장 규격을 준비 검사에서는 정확 픽셀 조건으로 사용한다. CMS에 규격이 없는 promotion/search/main/bot은 사용자가 너비·높이를 명시해야 하며, 임의 추정 대신 규격이 확인된 위치도 제안한다.

공식 [OpenAI 파일 입력 계약](https://developers.openai.com/plugins/reference)에 따라 `_meta["openai/fileParams"]`는 `file`, `mobile_file`이고 두 필드의 파일 객체 schema는 `download_url`, `file_id`, `mime_type`, `file_name`을 모두 선언한다. 앞 두 필드만 required다. `mobile_file`은 viewer에서만 필요하다. 닷 native 생성 결과를 공식 파일 입력으로 전달해야 하며 file_id만으로 임의 API를 조회하거나 arbitrary URL을 받아들이지 않는다.

기본 다운로드 host는 정확한 `files.oaiusercontent.com`이며 실제 파일 전달 시 다른 공식 host가 관측되면 운영자가 확인 후 비공개 서버 설정 `banner_file_download_hosts`에 추가해야 한다. 모델이 host를 공급할 수 없다. HTTPS, 표준 포트, 사용자정보 없음, 공인 DNS 주소, redirect 금지, proxy 환경 변수 비사용, 최대 15 MiB를 검사한다. Pillow가 실제 포맷·픽셀·완전 decode를 확인하며 애니메이션은 별도 검토가 필요하다. 만료된 URL은 새 공식 파일 참조를 요청한다. 서명 URL은 영수증·응답·HTTP client log에 저장하지 않는다.

## 게시와 검증

기존 CMS와 동일하게 `storage_service.get_presigned_upload_url(UploadReqBody(group_type="user"))`로 파일 레코드를 만들고 R2 PUT으로 올린다. 업로드는 사이트 미게시 상태여도 외부 write이며 게시 승인 범위에 포함된다. 기존 배너 전체 scope 스냅샷을 업로드 전과 게시 직전에 비교·잠그고, `admin_event_service.post_banner`로 새 배너 하나를 추가한다. 기존 배너의 콘텐츠를 덮어쓰지 않으며 노출 순서는 승인 위치에 맞춰 기존 공식 순서 계산을 재사용한다. 승인 계획에 포함되지 않은 기존 콘텐츠 변경이나 삽입/순서 불일치는 DB transaction을 롤백한다.

영수증은 다중 worker의 중복 적용을 막는다. 실패·응답 유실로 업로드/적용이 미확인 상태가 되면 자동 재실행하지 않고 확인 대상으로 남긴다. DB 롤백은 R2 이미지 업로드를 취소하지 않는다. 준비 계획은 30분 뒤 만료되며 오래된 로컬 준비 이미지와 실패한 staged storage 자산의 정리는 별도 운영 절차가 필요하다.

공개 endpoint는 `app/main.py`의 query-prefix와 `routers/common/banner_query.py`에 따른 `/v1/query/banners/{position}`이다. main은 division별 primaryPanels/secondaryPanels/teriayPanels로 확인한다. 공개 서비스의 기간은 시작일 자정과 종료일 자정 사이이며 종료는 exclusive다. 같은 시작/종료일을 허용하지 않는다. 공개 확인은 게시·업로드 재시도가 아니다.

## 현재 검증 범위

mock 테스트가 실제 픽셀, 크기, SSRF·redirect 차단, 공식 schema, 비공개 준비, 구좌 scope 차단, exact 승인, 기존 CMS 동시 변경 CAS, 1회 업로드·게시, unresolved 재시도 차단, 공개 CDN 픽셀 및 예약 기간 판정을 검증한다. 실제 닷 이미지 생성→file tool 전달, 생산 환경 업로드·배너 게시·공개 노출은 실행하지 않았고 미검증이다.
