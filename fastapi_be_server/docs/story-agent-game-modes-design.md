# Story Agent 게임 모드 설계 v1

## 현재 상태
- `이상형월드컵`만 v1 범위로 유지한다.
- `VS게임`은 작품별 비교축 설계가 아직 맞지 않아서 현재는 보류한다.
- `vs_game` 요청이 들어오면 엔진을 진행하지 않고 보류 안내 후 일반 상태로 되돌린다.

## 목적
- `이상형월드컵`과 `VS게임`을 일반 QA나 캐릭터 RP와 분리된 진행자 모드로 설계한다.
- v1 목표는 `진입 계약`, `세션 메모리 구조`, `반복 방지 기준`, `재진입 플로우`를 먼저 고정하는 것이다.
- 브래킷 생성기와 VS 질문 풀은 다음 구현 단계로 둔다.

## 공통 원칙
1. 모델은 캐릭터가 아니라 `진행자(MC)` 역할을 수행한다.
2. `games` 메모리는 `rp`, `analysis` 메모리와 분리한다.
3. 같은 세션 안에서 같은 카테고리의 게임을 다시 시작하면, 이전 매치업/주제는 반복하지 않는다.
4. 유저가 게임을 하다 RP로 돌아가거나, RP를 하다 게임으로 전환해도 각 모드 상태는 보존하고 `active_mode`만 전환한다.

## 이상형월드컵 진입 계약
유저가 `이상형월드컵 하자`라고 하면 바로 후보를 제시하지 않는다.

### 1단계: gender_scope
먼저 아래를 묻는다.
- `남성 버전`
- `여성 버전`
- `섞어서`

예시:
```text
좋아. 이상형월드컵으로 갈게.

1. 남성 버전
2. 여성 버전
3. 섞어서

어느 쪽으로 할래?
```

### 2단계: category
그 다음 기준을 묻는다.
- `연애/호감 기준`
- `데이트 상대로 끌리는 기준`
- `서사적으로 제일 꽂히는 기준`

예시:
```text
좋아. 그럼 기준을 고르자.

1. 연애/호감 기준
2. 데이트 상대로 끌리는 기준
3. 서사적으로 제일 꽂히는 기준

어떤 기준으로 할래?
```

### 3단계: 브래킷 시작
v1에서는 `4강`을 기본으로 하고, 후보가 충분할 때만 `8강`으로 확장한다.

## VS게임 진입 계약
현재는 구현 보류 상태다. 아래 내용은 재개 시 참고용 초안이다.

VS게임은 월드컵과 달리 먼저 `누구를 붙일지` 또는 `무슨 기준으로 붙일지`를 고르게 한다.

### 1단계: gender_scope
- `남성 버전`
- `여성 버전`
- `섞어서`

### 2단계: match_mode
- `누구와 누구를 직접 붙여볼래`
- `파워/지능/매력 같은 기준부터 고를래`

예시:
```text
좋아. VS게임으로 갈게.

1. 남성 버전
2. 여성 버전
3. 섞어서

어느 쪽으로 할래?
```

```text
좋아. 여성 버전 VS게임으로 갈게.

1. 누구와 누구를 직접 붙여볼래
2. 파워/지능/매력 같은 기준부터 고를래

어느 방식으로 갈래?
```

### 3단계: category
`criteria_match`일 때만 기준을 묻는다.
- `파워`
- `지능`
- `매력`
- `멘탈`
- `생존력`
- `연애형`
- `데이트형`
- `성격형`

## 세션 메모리 구조
```json
{
  "active_mode": "ideal_worldcup",
  "rp": {},
  "analysis": {},
  "game_context": {
    "mode": "ideal_worldcup",
    "gender_scope": "female",
    "category": "romance",
    "match_mode": null
  },
  "games": {
    "ideal_worldcup": {
      "female": {
        "romance": {
          "current_candidates": ["엔데온트라", "제이니코드네", "펜데", "주인공"],
          "current_bracket": [["엔데온트라", "제이니코드네"]],
          "current_round": "4강",
          "current_match_index": 0,
          "picks": [],
          "used_pair_keys": ["엔데온트라::제이니코드네"],
          "last_winner": null
        }
      }
    },
    "vs_game": {
      "female": {
        "power": {
          "mode": "criteria_match",
          "question_index": 0,
          "answers": [],
          "used_match_keys": [],
          "used_question_keys": ["power::endeontra_vs_pende"],
          "current_match": ["엔데온트라", "펜데"],
          "criterion": "power",
          "last_result_summary": null
        }
      }
    }
  }
}
```

## 반복 방지 규칙
### 이상형월드컵
- 같은 세션, 같은 `gender_scope`, 같은 `category` 안에서는 이미 나온 `pair_key`를 재사용하지 않는다.
- `pair_key`는 `sort([A, B]).join("::")` 규칙으로 만든다.
- `A vs B`와 `B vs A`는 같은 매치업으로 취급한다.

### VS게임
- 같은 세션, 같은 `gender_scope`, 같은 `category` 안에서는 이미 나온 `question_key` 또는 `match_key`를 재사용하지 않는다.
- `question_key`는 의미 키로 관리한다. 예: `power::endeontra_vs_pende`, `romance::direct_vs_tsun`.

## 재진입 플로우
### 이상형월드컵 다시 시작
```text
1. 이어서 하기
2. 새로 시작하기
3. 다른 기준으로 하기
```

### VS게임 다시 시작
```text
1. 이어서 하기
2. 새로 시작하기
3. 다른 기준으로 하기
```

### 같은 캐릭터와 다시 채팅
```text
1. 이전 대화 이어서 하기
2. 새로 시작하기
3. 다른 캐릭터와 새로하기
```

## v1 구현 범위
1. 요청 계약에 아래 필드를 추가한다.
- `game_mode`
- `game_gender_scope`
- `game_category`
- `game_match_mode`
2. `session_memory_json`에서 `game_context`, `games`를 정규화/직렬화한다.
3. `ideal_worldcup`가 활성화되면 진행자 응답과 브래킷 흐름을 반환한다.
4. `vs_game`은 현재 보류 안내만 반환한다.
