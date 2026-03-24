# CP 링크 SSOT 1단계

## 목적
- 작품의 유통 주체를 `tb_product_contract_offer.author_accept_yn`이 아니라 `tb_product.cp_user_id`로 고정한다.
- `tb_product_contract_offer`는 제안/채팅/협상 이력으로만 남긴다.
- 작가 작품 수정, 유료전환 심사, 파트너 매출/정산/통계가 같은 CP 식별값을 보도록 맞춘다.

## 핵심 원칙
1. 작품과 CP의 연결 SSOT는 `tb_product.cp_user_id`다.
2. `tb_product_contract_offer`와 `author_accept_yn`은 계약 SSOT가 아니다.
3. `cp_settlement_rate`는 플랫폼 수수료와 무관한 CP-작가 내부 정산비율이다.
4. `contract_yn='Y'` 작품은 반드시 유효한 `cp_user_id`를 가져야 한다.
5. `contract_yn='N'`은 CP 링크가 없는 상태다.

## 데이터 책임 분리
| 영역 | 사용 필드/테이블 | 의미 |
| --- | --- | --- |
| 작품-CP 연결 | `tb_product.cp_user_id` | 작품이 어느 CP 유통인지 나타내는 단일 값 |
| 계약 여부 UI | `tb_product.contract_yn` | 작품이 CP 계약 상태인지 여부 |
| 제안/채팅 | `tb_product_contract_offer` | 메시지, 제안, 협상 이력 |
| CP-작가 정산비 | `cp_settlement_rate` | 승인 후 CP가 입력하는 내부 정산비율 |

## 저장 규칙
### 작가 작품 수정
- `contract_yn='Y'`면 `cp_nickname` 입력이 필수다.
- `cp_nickname`은 `trim` 후 exact match로 검증한다.
- 검증 대상은 아래 조건을 모두 만족하는 계정이다.
  - `tb_user.role_type='CP'`
  - 승인된 CP 신청(`tb_user_profile_apply.apply_type='cp'`, `approval_code='accepted'`)
  - 기본 프로필(`tb_user_profile.default_yn='Y'`) 닉네임
- 검증 성공 시 `tb_product.cp_user_id`에 CP `user_id`를 저장한다.
- 화면 표시용 닉네임은 현재 기본 닉네임을 읽는다.

### 락 정책
- 유료전환 신청이 `review` 상태에 들어가면 `contract_yn`, `cp_nickname` 수정은 잠근다.
- `accepted` 상태도 동일하게 잠근다.

### 유료전환 신청
- `contract_yn='Y'`이면서 `cp_user_id`가 존재해야 신청할 수 있다.
- 신청 시점에도 `cp_user_id`가 여전히 유효한 승인 CP인지 재검증한다.

### CMS 유료전환 승인
- 승인 시점에 다시 한 번 아래를 확인한다.
  - `tb_product.contract_yn='Y'`
  - `tb_product.cp_user_id IS NOT NULL`
  - `cp_user_id`가 여전히 승인된 CP 계정인지
- 실패하면 승인하지 않는다.

## 파트너 조회 기준
아래 경로는 계약 SSOT로 `tb_product.cp_user_id`를 본다.
- 파트너 작품 목록/검색/필터
- 파트너 매출 화면
- 파트너 정산 화면
- 파트너 통계 화면
- CMS 유료전환 승인 목록의 CP 닉네임 표시

### 의도적으로 유지하는 accepted offer 경로
아래는 1단계에서 그대로 둔다.
- 계약 제안/채팅/협상 이력
- 선인세 제안 row 식별(`offer_id`)이 필요한 상세 경로
- discovery detail에서 제안 기반 선인세 세부 범위

## 기존 데이터 보정
운영 전 일괄 보정 원칙:
1. `contract_yn='Y'`이면서 accepted CP가 단일하게 확정되는 작품만 `cp_user_id`를 backfill한다.
2. accepted offer가 없거나, accepted CP가 여러 명이라 단일하게 결정할 수 없는 작품은 자동 추정하지 않는다.
3. `contract_yn='Y' AND cp_user_id IS NULL` 작품은 운영 전 수동 보정 목록으로 남기고, 실제 유통 CP를 확인한 뒤 채운다.

### 운영 전 확인 쿼리
```sql
-- 1) accepted CP가 여러 명이라 자동 backfill 대상에서 제외되는 작품
SELECT z.product_id, COUNT(DISTINCT z.offer_user_id) AS cp_count
FROM tb_product_contract_offer z
JOIN tb_user_profile_apply upa
  ON upa.user_id = z.offer_user_id
 AND upa.apply_type = 'cp'
 AND upa.approval_code = 'accepted'
 AND upa.approval_date IS NOT NULL
WHERE z.use_yn = 'Y'
  AND z.author_accept_yn = 'Y'
GROUP BY z.product_id
HAVING COUNT(DISTINCT z.offer_user_id) > 1;
```

```sql
-- 2) 계약 플래그는 Y인데 cp_user_id가 비어 있어 수동 보정이 필요한 작품
SELECT product_id
FROM tb_product
WHERE contract_yn = 'Y'
  AND cp_user_id IS NULL;
```

```sql
-- 3) accepted CP 제안은 있지만 contract_yn이 N인 drift 작품
SELECT DISTINCT p.product_id
FROM tb_product p
JOIN tb_product_contract_offer z
  ON z.product_id = p.product_id
JOIN tb_user_profile_apply upa
  ON upa.user_id = z.offer_user_id
 AND upa.apply_type = 'cp'
 AND upa.approval_code = 'accepted'
 AND upa.approval_date IS NOT NULL
WHERE z.use_yn = 'Y'
  AND z.author_accept_yn = 'Y'
  AND p.contract_yn <> 'Y';
```

### 운영 전 체크리스트
1. migration 적용 직후 `contract_yn='Y' AND cp_user_id IS NULL` 건수를 확인한다.
2. 1번 결과가 0이 아닐 경우, 각 작품의 실제 유통 CP를 확인해 수동 보정한다.
3. 유저웹 작품수정에서 `contract_yn='Y' + cp_nickname` 저장이 정상 동작하는지 확인한다.
4. 유료전환 신청(review)과 CMS 승인 샘플을 최소 1건씩 검증한다.
5. partner 목록/검색/필터/상세에서 `cp_user_id` 기준으로 작품 귀속이 맞는지 확인한다.

## 비대상
1. 웹/앱 결제 수수료 공식 개편
2. 플랫폼 서비스 수수료 공식 개편
3. `cp_settlement_rate` 입력 UX 개편
4. 제안/수락 채팅 UX 제거

## 운영 메모
- CP 닉네임은 작품 저장 시점의 식별 입력일 뿐, SSOT는 `cp_user_id`다.
- CP 닉네임 변경은 운영 문의로 통제한다.
- 작가 정산금은 `cp_settlement_rate` 미입력 시 비노출한다.
- 유료전환 신청(`review`)은 작품 row를 잠가 계약 정보 변경과 경쟁하지 않도록 처리한다.
- CP 닉네임 blur validate는 UX용 보조 검증이고, 저장/승인 시 최종 검증을 다시 수행한다.
- CP 승인 판정은 `approval_date` 단독이 아니라 `approval_code='accepted'`를 함께 기준으로 삼는다.
