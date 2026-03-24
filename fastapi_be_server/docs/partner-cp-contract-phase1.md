# Partner CP 계약 1단계 정리

> 주의: 작품-CP 연결 SSOT는 현재 [cp-link-source-of-truth-phase1.md](./cp-link-source-of-truth-phase1.md)의 `tb_product.cp_user_id` 기준이 우선이다.  
> 이 문서는 partner 신규작품생성에서 계약행 쓰기를 defer했던 1단계 맥락만 보존한다.

## 배경
- 파트너 `신규작품생성`은 생성 직후 `PUT /v1/command/partners/products/{id}`를 한 번 더 호출한다.
- 이 화면은 `cp_company_name`만 보내고, `cp_offered_price` / `cp_settlement_rate`는 보내지 않는다.
- 기존 백엔드는 `cp_company_name`이 있으면 항상 `tb_product_contract_offer`를 insert/update 하려고 했고,
  `author_profit = cp_settlement_rate`에 `NULL`이 들어가면서 500이 발생했다.

## 1단계 목표
- 신규 CP 작품 생성에서 500을 없앤다.
- 계약행 의미를 바꾸거나 정산 배치 공식을 손대지 않는다.
- `cp_settlement_rate`는 신규 CP 작품 생성 단계에서 강제하지 않는다.

## 1단계 정책
1. `cp_company_name`만 있는 신규 CP 작품 생성/수정은 허용한다.
2. 이 경우 `tb_product_contract_offer`는 생성/수정하지 않는다.
3. CP 계약 정보(`cp_offered_price`, `cp_settlement_rate`)는 상세 수정/계약 설정 단계에서만 다룬다.
4. 승인된 본인 CP 계정이 아닌 회사명을 CP가 직접 선택하는 것은 400으로 막는다.
5. 이 defer는 `tb_product.user_id == 현재 CP user_id`인 본인 소유 작품에만 허용한다.
6. 관리자/비CP 사용자는 신규작품생성 단계에서 CP사를 선택할 수 없고, 상세 수정으로 유도한다.
7. 관리자/비CP 사용자가 계약 정보 없이 CP사를 붙이려고 하면 400으로 막고 상세 수정으로 유도한다.
8. 상세 수정에서 계약 정보를 넣을 때는 `cp_offered_price`와 `cp_settlement_rate`를 둘 다 함께 입력해야 한다.

## UI 보강
- CP 계정의 신규작품생성 `CP명`은 본인 승인된 CP사로 자동 귀속되고 드롭다운은 비활성화된다.
- 관리자 신규작품생성은 프론트에서 `CP명` 선택 즉시 차단해 `POST 성공 -> PUT 400` 부분 생성 시나리오를 줄인다.

## 이번 단계에서 바뀐 동작
- `tb_product.contract_yn`은 `cp_company_name` 존재 여부에 맞춰 함께 갱신된다.
- 작품-CP 귀속과 CP명 표시는 `tb_product.cp_user_id`를 기준으로 읽는다.
- accepted 계약행이 없는 defer 작품이라도, 신규 저장 시 `cp_user_id`가 함께 저장되므로 파트너 조회에서 별도 owner fallback을 두지 않는다.

## 의도적으로 하지 않은 것
- accepted 계약행 자동 생성
- `cp_offered_price` 없는 계약행 생성
- `cp_settlement_rate` 기본값 주입
- 정산 배치 공식 개편
- `default_settlement_rate`/`payment_fee_rate` 구조 개편

## 남은 제약
- `contract_yn='Y'`인데 `tb_product_contract_offer`가 없는 1단계 상태가 존재한다.
- 다만 작품 귀속과 CP명 표시는 `tb_product.cp_user_id`를 기준으로 읽고, `tb_product_contract_offer`는 협상/제안 메타데이터로만 남는다.
- 선인세/제안 스냅샷처럼 `offer_id`가 필요한 경로는 2단계 전까지 기존 계약행을 계속 본다.

## 다음 단계
1. 정산 모델 분리
   - `payment_fee`
   - `platform_service_rate`
   - `cp_settlement_rate`
2. 작가 작품에 CP 계약을 붙일 때만 `cp_settlement_rate`를 입력받도록 분리
3. 작가 화면은 `cp_settlement_rate` 미입력 시 정산금 비노출 처리
