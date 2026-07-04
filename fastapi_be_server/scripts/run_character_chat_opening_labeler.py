#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import signal
import time
from pathlib import Path
from typing import Any

import httpx


OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
DEFAULT_MODEL = os.getenv("CHARACTER_CHAT_OPENING_LABEL_MODEL", "deepseek/deepseek-v3.2").strip()
REQUEST_TIMEOUT_SECONDS = 180.0
MAX_OUTPUT_TOKENS = 4000


SYSTEM_PROMPT = """당신은 웹소설 원작 기반 캐릭터챗을 위한 opening labeler다.
반드시 유효한 JSON object 하나만 반환한다. 코드블록, 설명, 머리말 금지.
모든 값은 JSON 규칙을 지켜야 한다. enum 후보도 반드시 따옴표가 붙은 문자열 값으로 반환한다.
enum 필드는 후보 문자열과 정확히 일치해야 한다. 괄호 설명, 접미사, 부연 설명을 enum 값 안에 넣지 마라.
부연 설명이 필요하면 enum 필드가 아니라 주변 설명 필드에 넣어라.
문자열 값 안에 큰따옴표를 직접 넣지 마라. 작품 대사/문장을 원문 그대로 인용하지 말고 짧은 요약으로만 적어라.
각 설명 문자열은 한 문장, 80자 이하로 쓴다. 배열 항목은 50자 이하 요약으로 쓴다.
모든 배열은 최대 3개 항목만 반환한다. evidence, dialogue_dos, dialogue_donts는 각각 최대 3개다.
next_beats와 event_injection_rules는 각각 정확히 2개만 반환한다.
safe_response_examples는 반드시 2개 이상을 JSON 배열의 별도 문자열 항목으로 반환한다. 한 문자열 안에 여러 예시를 쉼표로 합치지 마라.

목표
- 1~3화 안의 근거만 사용해 캐릭터챗 첫 진입과 장기 대화 진행에 필요한 재료를 추출한다.
- chat_target은 실제 서비스 유저가 대화할 원작 캐릭터다. user_role은 그 캐릭터와 대화할 실제 서비스 유저의 비원작 역할이다.
- 원작 주인공과 대화하는 것이 기본이다. 중심 조력자/기타를 chat_target으로 고르는 경우에도 identity_resolution과 voice/drive는 반드시 그 chat_target 기준이어야 한다.
- 원작 주인공이 식별 가능하고 voice/scene 근거가 있으면 chat_target은 주인공으로 고른다.
- ready는 target_name_evidence가 direct_name이고 voice_evidence가 dialogue일 때만 가능하다.
- 중심 조력자를 chat_target으로 고르는 것은 주인공보다 그 조력자의 대화 근거가 더 강하고, identity_resolution도 그 조력자 기준으로 쓸 수 있을 때만 허용한다.
- "기타" 인물은 ready chat_target으로 쓰지 않는다. 그럴 때는 needs_review다.
- 유저를 원작 주인공, 주인공의 몸, 주인공의 이름, 원작의 특정 캐릭터로 만들지 마라.
- user_role의 모든 문장은 실제 서비스 유저 관점으로 쓴다. 원작 인물명을 주어로 시작하지 마라.
- 유저를 원작에 이미 등장한 특정 집단/쌍/개체 중 하나로 만들지 마라.
- 사용자가 원작 세계에 자연스럽게 들어갈 수 있는 역할, 캐릭터의 즉시 목적, 압박, 다음 beat를 만든다.
- 캐릭터가 유저 답변을 기다리기만 하지 않고 먼저 움직이게 할 장기 진행 재료를 만든다.
- 원작 1~3화의 세계관/설정/캐릭터성은 보존하되, 대화에서는 안전한 새 사건 변주를 만들 수 있게 한다.
- 근거가 부족하면 ready를 주지 않는다. fallback으로 그럴듯한 캐릭터를 만들지 않는다.
- 인물명이 원문에 직접 나오지 않거나 대사 근거가 없으면 ready가 아니라 needs_review 또는 not_ready다.
- 유저가 어떤 위치에서 장면에 들어가는지 구체적으로 말할 수 없으면 ready가 아니라 needs_review다.
- user_role.role_type이 "불명"이면 readiness.status는 절대 "ready"가 될 수 없다.

금지
- 원문 1~3화 밖의 미래 사건/설정을 추측하지 마라.
- 사용자를 원작의 특정 인물, 연인, 가족, 절친으로 확정하지 마라.
- user_role 안에 "유저는 김검성이다", "유저는 이현정이다", "유저는 주인공이다"처럼 원작 인물명/주인공 신분을 넣지 마라.
- scene_entry_reason을 "채이레가 안유영과 만났다"처럼 원작 인물명 주어로 쓰지 마라. "유저는 약속 장소 근처에 있던 새 지인이다"처럼 써라.
- scene_entry_reason을 "유저는 토끼 부부 중 하나이다"처럼 원작 특정 집단/쌍의 구성원으로 쓰지 마라.
- 일반적인 "무엇을 도와줄까?" 식 greeting 의도를 만들지 마라.
- 장르 클리셰만으로 시스템/등급/세력/목표를 만들지 마라.
- chat_target.display_name을 "주인공", "관리자", "주제", "시스템" 같은 역할명/일반명으로 쓰지 마라.
- 유저에게 전투/잠입/훔치기/살해/각성 같은 핵심 임무를 떠넘기지 마라.
- evidence 배열에는 원문 대사를 그대로 넣지 말고 "주인공 시점과 대사가 반복됨" 같은 요약만 넣어라.

정체성 판정
- identity_resolution은 반드시 chat_target으로 고른 그 인물의 정체성/호칭 규칙이다.
- chat_target.display_name이 "김하연"인데 identity_resolution.current_display_name이 "김검성"처럼 다른 인물을 가리키면 안 된다.
- 회귀: 같은 몸/공개 이름이면 identity_mode는 "regression_same_body".
- 환생: 새 몸/새 삶이면 "reincarnation_new_body".
- 빙의: 숙주 몸에 들어간 경우 "possession_host_body".
- 게임/아바타: 현실 이름과 아바타/게임명 충돌이면 "game_avatar".
- 귀환: 과거 세계/다른 세계에서 돌아온 경우 "returnee".
- 대역/위장/가짜 신분: 다른 인물을 대신 연기하거나 신분을 위장하면 "body_double_or_disguise".

반환 JSON 스키마
{
  "readiness": {
    "status": "ready | needs_review | not_ready",
    "confidence": 0.0,
    "block_reasons": ["문자열"]
  },
  "work_opening": {
    "premise": "1~2문장",
    "opening_hook_type": "회귀|환생|빙의|전이/이세계|귀환|게임/아바타|대역|각성|위기|임무|계약|은퇴|오디션|생존|관계파열|기타",
    "spoiler_boundary": "1~3화 근거 경계"
  },
  "chat_target": {
    "display_name": "가장 대화 대상으로 적절한 인물명",
    "aliases": ["별칭"],
    "role": "주인공|중심 조력자|기타",
    "protagonist_likelihood": 0.0,
    "chat_target_likelihood": 0.0,
    "evidence": ["짧은 근거 요약"]
  },
  "identity_resolution": {
    "identity_mode": "ordinary|regression_same_body|reincarnation_new_body|possession_host_body|game_avatar|returnee|body_double_or_disguise|unknown",
    "current_display_name": "현재 장면/세계 안에서 불러야 하는 이름",
    "pre_transfer_name": "전이/환생/빙의/게임 이전 이름 또는 null",
    "host_or_avatar_name": "숙주/아바타/공개 이름 또는 null",
    "public_opening_name": "첫 인사에서 써도 되는 이름",
    "identity_spoiler_risk": "low|medium|high|unknown",
    "name_use_rule": "캐릭터와 유저가 첫 장면에서 어떤 이름을 써야 하는지"
  },
  "opening_scene": {
    "time": "문자열",
    "place": "문자열",
    "situation": "문자열",
    "immediate_conflict": "문자열",
    "props_or_anchors": ["장소/물건/사건 앵커"],
    "nearby_characters": ["인물명"]
  },
  "user_role": {
    "role_type": "동행자|임시 조력자|목격자|의뢰인|후배/부하|동료|구조 대상|불명",
    "relationship_to_character": "문자열",
    "scene_entry_reason": "유저가 왜 지금 이 장면에 있는지",
    "first_turn_affordance": "유저가 첫 답변에서 할 수 있는 행동/정보/선택",
    "user_knows": ["유저가 알아도 되는 정보"],
    "user_must_not_know": ["초반 스포일러/숨겨진 정체"],
    "allowed_assumptions": ["가능한 가정"],
    "forbidden_assumptions": ["하면 안 되는 가정"]
  },
  "character_drive": {
    "immediate_objective": "지금 당장 캐릭터가 원하는 것",
    "pressure": "압박/위험/제약",
    "secret_or_vulnerability": "숨겨야 하거나 약한 부분",
    "longer_desire": "초반부 큰 욕망"
  },
  "agency_contract": {
    "character_moves_first": true,
    "move_style": "끌고 감|압박함|거래 제안|보호함|심문함|도주 유도|훈련/시험 부여|정보 요구|기타",
    "non_user_dependent_action": "유저가 침묵해도 캐릭터가 다음에 할 행동",
    "decision_character_must_make": "캐릭터가 곧 선택해야 하는 결정",
    "user_influence_boundary": "유저가 영향을 줄 수 있지만 대신 주도하지 않는 범위"
  },
  "progression_engine": {
    "short_term_goal": "첫 5~10턴 목표",
    "mid_term_escalation": "10~30턴 사이 새 사건/압박",
    "long_term_complication": "30턴 이후 투입 가능한 합병증/반전",
    "scene_exit_condition": "다음 국면으로 넘어가는 조건",
    "event_injection_rules": [
      {"when": "정체 조건", "inject": "캐릭터가 먼저 일으키는 사건/행동", "must_not_repeat": "반복 금지 요소"}
    ]
  },
  "user_affordance_contract": {
    "primary_affordances": ["관찰|판단|선택|정보 제공|위험 감지|간단한 행동"],
    "forbidden_agency_load": ["유저에게 떠넘기면 안 되는 주인공급 임무"],
    "safe_response_examples": ["유저가 자연스럽게 할 수 있는 짧은 행동 예시"],
    "bad_response_pressure_to_avoid": ["유저에게 압박하면 안 되는 행동"]
  },
  "canon_safe_expansion": {
    "safe_new_event_pattern": "원작 1~3화의 압박을 변주한 새 사건 패턴",
    "allowed_inventions": ["허용되는 소규모 창작 요소"],
    "forbidden_inventions": ["만들면 안 되는 미래 설정/세력/결말"],
    "must_preserve_facts": ["반드시 지킬 원작 사실"]
  },
  "voice_style": {
    "speech_level": "존대|반말|mixed|unknown",
    "emotional_baseline": "문자열",
    "dialogue_dos": ["말투 지침"],
    "dialogue_donts": ["피해야 할 말투"]
  },
  "relationship_stance": {
    "initial_trust": "낮음|중립|중간|높음|불명",
    "power_distance": "캐릭터 우위|유저 우위|대등|불명",
    "warmth": "차가움|중립|따뜻함|불명",
    "volatility": "낮음|중간|높음|불명"
  },
  "evidence_quality": {
    "target_name_evidence": "direct_name|title_only|role_only|ambiguous",
    "voice_evidence": "dialogue|narration_only|none",
    "scene_anchor_evidence": "direct|inferred|weak",
    "input_truncated": true
  },
  "progression": {
    "opening_greeting_intent": "첫 인사가 달성해야 할 목적",
    "next_beats": [
      {"beat": "다음 전개", "trigger": "유저 반응 조건", "avoid_repeating": "반복 금지 요소"}
    ],
    "anti_loop_rules": ["20~30턴에서 반복을 막는 규칙"]
  }
}
"""


READINESS_STATUSES = {"ready", "needs_review", "not_ready"}
OPENING_HOOK_TYPES = {
    "회귀",
    "환생",
    "빙의",
    "전이/이세계",
    "귀환",
    "게임/아바타",
    "대역",
    "각성",
    "위기",
    "임무",
    "계약",
    "은퇴",
    "오디션",
    "생존",
    "관계파열",
    "기타",
}
TRANSFER_HOOK_TYPES = {"회귀", "환생", "빙의", "전이/이세계", "귀환", "게임/아바타", "대역"}
HOOK_IDENTITY_ALLOWED = {
    "회귀": {"regression_same_body", "returnee"},
    "환생": {"reincarnation_new_body"},
    "빙의": {"possession_host_body"},
    "전이/이세계": {
        "ordinary",
        "regression_same_body",
        "reincarnation_new_body",
        "possession_host_body",
        "game_avatar",
        "returnee",
    },
    "귀환": {"ordinary", "returnee"},
    "게임/아바타": {"ordinary", "game_avatar"},
    "대역": {"body_double_or_disguise"},
}
CHAT_TARGET_ROLES = {"주인공", "중심 조력자", "기타"}
USER_ROLE_TYPES = {"동행자", "임시 조력자", "목격자", "의뢰인", "후배/부하", "동료", "구조 대상", "불명"}
IDENTITY_MODES = {
    "ordinary",
    "regression_same_body",
    "reincarnation_new_body",
    "possession_host_body",
    "game_avatar",
    "returnee",
    "body_double_or_disguise",
    "unknown",
}
IDENTITY_SPOILER_RISKS = {"low", "medium", "high", "unknown"}
SPEECH_LEVELS = {"존대", "반말", "mixed", "unknown"}
TRUST_LEVELS = {"낮음", "중립", "중간", "높음", "불명"}
POWER_DISTANCE_LEVELS = {"캐릭터 우위", "유저 우위", "대등", "불명"}
WARMTH_LEVELS = {"차가움", "중립", "따뜻함", "불명"}
VOLATILITY_LEVELS = {"낮음", "중간", "높음", "불명"}
TARGET_NAME_EVIDENCE_TYPES = {"direct_name", "title_only", "role_only", "ambiguous"}
VOICE_EVIDENCE_TYPES = {"dialogue", "narration_only", "none"}
SCENE_ANCHOR_EVIDENCE_TYPES = {"direct", "inferred", "weak"}
ROLE_LABEL_DISPLAY_NAMES = {
    "주인공",
    "당신",
    "너",
    "그",
    "그녀",
    "남자",
    "여자",
    "남성",
    "여성",
    "청년",
    "노인",
    "아이",
    "소년",
    "소녀",
    "관리자",
    "시스템",
    "주제",
    "나레이터",
    "화자",
    "작가",
    "독자",
    "시청자",
    "인물",
    "캐릭터",
    "무명",
    "이름 없음",
}
CONTEXTUAL_ROLE_LABEL_DISPLAY_NAMES = {"플레이어"}
REVIEW_ONLY_SCHEMA_ISSUES = {"ready_hook_identity_mismatch"}


class LabelParseError(ValueError):
    def __init__(self, message: str, raw_text: str):
        super().__init__(message)
        self.raw_text = raw_text


class LabelCallTimeoutError(TimeoutError):
    pass


@contextlib.contextmanager
def wall_clock_timeout(seconds: float):
    if seconds <= 0:
        yield
        return

    def _handle_timeout(_signum, _frame):
        raise LabelCallTimeoutError(f"call exceeded {seconds:.1f}s")

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    signal.signal(signal.SIGALRM, _handle_timeout)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def load_env_file(path: Path) -> list[str]:
    loaded: list[str] = []
    if not path.exists():
        return loaded
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip().strip("'\"")
        if key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def load_input_rows(input_path: Path, *, limit: int, offset: int = 0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_index, line in enumerate(input_path.read_text(encoding="utf-8").splitlines()):
        if line_index < max(offset, 0):
            continue
        if line.strip():
            rows.append(json.loads(line))
        if limit > 0 and len(rows) >= limit:
            break
    return rows


def load_existing_results(output_path: Path) -> dict[str, dict[str, Any]]:
    if not output_path.exists():
        return {}
    latest_by_file: dict[str, dict[str, Any]] = {}
    for line in output_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        file_name = _string(row.get("fileName"))
        if file_name:
            latest_by_file[file_name] = row
    return latest_by_file


def should_skip_existing_result(existing: dict[str, Any] | None, *, retry_failed: bool) -> bool:
    if not existing:
        return False
    if not retry_failed:
        return True
    return existing.get("status") == "ok" and existing.get("schemaPass") is True


def is_openrouter_payment_required(exc: BaseException) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    response = exc.response
    return response is not None and response.status_code == 402


def extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("json object not found")
    parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("json object expected")
    return parsed


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string(value: Any) -> str:
    return str(value or "").strip()


def _nonempty_strings(value: Any) -> list[str]:
    return [item for item in (_string(raw) for raw in _as_list(value)) if item]


def _number_between(value: Any, minimum: float, maximum: float) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return minimum <= float(value) <= maximum


def _append_invalid_enum(issues: list[str], issue: str, value: Any, allowed: set[str]) -> None:
    if _string(value) not in allowed:
        issues.append(issue)


def _normalize_name_for_match(value: Any) -> str:
    return re.sub(r"[\s\"'“”‘’.,!?·ㆍ()\[\]{}<>《》〈〉]", "", _string(value)).lower()


def _names_overlap(left_values: list[Any], right_values: list[Any]) -> bool:
    left_names = [_normalize_name_for_match(value) for value in left_values]
    right_names = [_normalize_name_for_match(value) for value in right_values]
    left_names = [value for value in left_names if value and value != "null"]
    right_names = [value for value in right_names if value and value != "null"]
    if not left_names or not right_names:
        return False
    for left in left_names:
        for right in right_names:
            if left == right or left in right or right in left:
                return True
    return False


def _character_name_candidates(values: list[Any]) -> list[str]:
    names: list[str] = []
    for raw in values:
        raw_name = _string(raw)
        raw_normalized = _normalize_name_for_match(raw_name)
        if len(raw_normalized) >= 3 and raw_normalized not in {"null", "none"}:
            names.append(raw_name)
        name = re.split(r"[\s(/,，:：-]", _string(raw), maxsplit=1)[0].strip()
        normalized = _normalize_name_for_match(name)
        if len(normalized) >= 2 and normalized not in {"null", "none"}:
            names.append(name)
    return list(dict.fromkeys(names))


def _starts_with_canon_character_subject(text: Any, names: list[str]) -> bool:
    value = _string(text)
    if not value:
        return False
    for name in names:
        if not name:
            continue
        if not re.match(rf"^\s*{re.escape(name)}\s*(?:가|이|은|는|로서|으로서)", value):
            continue
        first_clause = re.split(r"[,，.]", value, maxsplit=1)[0]
        if "유저" in first_clause:
            continue
        if re.search(r"(만났|합류|동행|따라왔)", first_clause):
            return True
    return False


def _uses_user_as_canon_group_member(text: Any, names: list[str]) -> bool:
    value = _string(text)
    if not value or "유저" not in value or "중 하나" not in value:
        return False
    if re.search(r"유저는\s*.{0,30}(부부|남매|형제|자매|쌍둥이)\s+중 하나", value):
        return True
    if re.search(
        r"유저는\s*.{0,40}(원작|기존|이미 등장한)\s*.{0,30}(인물|멤버|동료|일행|파티|조|팀|분대|부대|가문)\s+중 하나",
        value,
    ):
        return True
    for name in names:
        normalized_name = _normalize_name_for_match(name)
        if len(normalized_name) < 3:
            continue
        if normalized_name in _normalize_name_for_match(value):
            return True
    return False


def _is_role_label_display_name(value: Any, *, target_name_evidence: str) -> bool:
    normalized = _normalize_name_for_match(value)
    if not normalized:
        return False
    role_labels = {_normalize_name_for_match(label) for label in ROLE_LABEL_DISPLAY_NAMES}
    if normalized in role_labels:
        return True
    contextual_labels = {_normalize_name_for_match(label) for label in CONTEXTUAL_ROLE_LABEL_DISPLAY_NAMES}
    return normalized in contextual_labels and target_name_evidence != "direct_name"


def derive_effective_readiness(
    payload: dict[str, Any],
    *,
    schema_pass: bool | None = None,
    schema_issues: list[str] | None = None,
) -> tuple[str, list[str]]:
    if schema_pass is None or schema_issues is None:
        schema_pass, schema_issues = validate_label_payload(payload)
    readiness = _as_dict(payload.get("readiness"))
    status = _string(readiness.get("status"))
    block_reasons = _nonempty_strings(readiness.get("block_reasons"))
    if status not in READINESS_STATUSES:
        return "not_ready", ["invalid_readiness_status", *schema_issues]
    if status != "ready":
        return status, block_reasons or schema_issues
    if schema_pass:
        return "ready", block_reasons
    if schema_issues and set(schema_issues).issubset(REVIEW_ONLY_SCHEMA_ISSUES):
        return "needs_review", schema_issues
    return "not_ready", schema_issues or ["schema_failed"]


def validate_label_payload(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    readiness = _as_dict(payload.get("readiness"))
    status = _string(readiness.get("status"))
    if status not in READINESS_STATUSES:
        issues.append("invalid_readiness_status")
    if not _number_between(readiness.get("confidence"), 0, 1):
        issues.append("invalid_readiness_confidence")
    if status in {"needs_review", "not_ready"} and not _as_list(readiness.get("block_reasons")):
        issues.append(f"{status}_missing_block_reasons")

    work_opening = _as_dict(payload.get("work_opening"))
    chat_target = _as_dict(payload.get("chat_target"))
    identity_resolution = _as_dict(payload.get("identity_resolution"))
    opening_scene = _as_dict(payload.get("opening_scene"))
    user_role = _as_dict(payload.get("user_role"))
    character_drive = _as_dict(payload.get("character_drive"))
    agency_contract = _as_dict(payload.get("agency_contract"))
    progression_engine = _as_dict(payload.get("progression_engine"))
    user_affordance_contract = _as_dict(payload.get("user_affordance_contract"))
    canon_safe_expansion = _as_dict(payload.get("canon_safe_expansion"))
    voice_style = _as_dict(payload.get("voice_style"))
    relationship_stance = _as_dict(payload.get("relationship_stance"))
    evidence_quality = _as_dict(payload.get("evidence_quality"))
    progression = _as_dict(payload.get("progression"))

    hook_type = _string(work_opening.get("opening_hook_type"))
    _append_invalid_enum(issues, "invalid_opening_hook_type", hook_type, OPENING_HOOK_TYPES)
    _append_invalid_enum(issues, "invalid_chat_target_role", chat_target.get("role"), CHAT_TARGET_ROLES)
    if not _number_between(chat_target.get("protagonist_likelihood"), 0, 1):
        issues.append("invalid_protagonist_likelihood")
    if not _number_between(chat_target.get("chat_target_likelihood"), 0, 1):
        issues.append("invalid_chat_target_likelihood")
    _append_invalid_enum(issues, "invalid_user_role_type", user_role.get("role_type"), USER_ROLE_TYPES)
    _append_invalid_enum(issues, "invalid_identity_mode", identity_resolution.get("identity_mode"), IDENTITY_MODES)
    _append_invalid_enum(
        issues,
        "invalid_identity_spoiler_risk",
        identity_resolution.get("identity_spoiler_risk"),
        IDENTITY_SPOILER_RISKS,
    )
    _append_invalid_enum(issues, "invalid_speech_level", voice_style.get("speech_level"), SPEECH_LEVELS)
    _append_invalid_enum(issues, "invalid_initial_trust", relationship_stance.get("initial_trust"), TRUST_LEVELS)
    _append_invalid_enum(
        issues,
        "invalid_power_distance",
        relationship_stance.get("power_distance"),
        POWER_DISTANCE_LEVELS,
    )
    _append_invalid_enum(issues, "invalid_warmth", relationship_stance.get("warmth"), WARMTH_LEVELS)
    _append_invalid_enum(issues, "invalid_volatility", relationship_stance.get("volatility"), VOLATILITY_LEVELS)
    _append_invalid_enum(
        issues,
        "invalid_target_name_evidence",
        evidence_quality.get("target_name_evidence"),
        TARGET_NAME_EVIDENCE_TYPES,
    )
    _append_invalid_enum(
        issues,
        "invalid_voice_evidence",
        evidence_quality.get("voice_evidence"),
        VOICE_EVIDENCE_TYPES,
    )
    _append_invalid_enum(
        issues,
        "invalid_scene_anchor_evidence",
        evidence_quality.get("scene_anchor_evidence"),
        SCENE_ANCHOR_EVIDENCE_TYPES,
    )
    if not isinstance(evidence_quality.get("input_truncated"), bool):
        issues.append("invalid_input_truncated")

    if status == "ready":
        required_ready_fields = {
            "ready_missing_chat_target": _string(chat_target.get("display_name")),
            "ready_missing_scene": _string(opening_scene.get("situation")),
            "ready_missing_scene_conflict": _string(opening_scene.get("immediate_conflict")),
            "ready_missing_user_role": _string(user_role.get("role_type")),
            "ready_missing_scene_entry_reason": _string(user_role.get("scene_entry_reason")),
            "ready_missing_first_turn_affordance": _string(user_role.get("first_turn_affordance")),
            "ready_missing_objective": _string(character_drive.get("immediate_objective")),
            "ready_missing_voice": _string(voice_style.get("speech_level")),
            "ready_missing_greeting_intent": _string(progression.get("opening_greeting_intent")),
        }
        for issue, value in required_ready_fields.items():
            if not value:
                issues.append(issue)
        if _string(user_role.get("role_type")) == "불명":
            issues.append("ready_user_role_unspecified")
        if _string(voice_style.get("speech_level")) == "unknown":
            issues.append("ready_voice_unknown")
        if _string(chat_target.get("role")) == "기타":
            issues.append("ready_chat_target_role_too_weak")
        target_name_evidence = _string(evidence_quality.get("target_name_evidence"))
        if _is_role_label_display_name(chat_target.get("display_name"), target_name_evidence=target_name_evidence):
            issues.append("ready_display_name_is_role_label")
        for field_name in ("current_display_name", "public_opening_name"):
            if _is_role_label_display_name(
                identity_resolution.get(field_name),
                target_name_evidence=target_name_evidence,
            ):
                issues.append(f"ready_{field_name}_is_role_label")
        if _string(evidence_quality.get("target_name_evidence")) == "ambiguous":
            issues.append("ready_target_name_ambiguous")
        if _string(evidence_quality.get("target_name_evidence")) != "direct_name":
            issues.append("ready_target_name_evidence_not_direct")
        if _string(evidence_quality.get("voice_evidence")) == "none":
            issues.append("ready_voice_evidence_none")
        if _string(evidence_quality.get("voice_evidence")) != "dialogue":
            issues.append("ready_voice_evidence_not_dialogue")
        if _string(evidence_quality.get("scene_anchor_evidence")) == "weak":
            issues.append("ready_scene_anchor_weak")
        target_name_values = [chat_target.get("display_name"), *_as_list(chat_target.get("aliases"))]
        target_name_norms = {
            _normalize_name_for_match(value)
            for value in target_name_values
            if _normalize_name_for_match(value)
        }
        nearby_names = [
            name
            for name in _character_name_candidates(_as_list(opening_scene.get("nearby_characters")))
            if _normalize_name_for_match(name) not in target_name_norms
        ]
        user_role_texts = [
            user_role.get("relationship_to_character"),
            user_role.get("scene_entry_reason"),
            user_role.get("first_turn_affordance"),
        ]
        if any(_starts_with_canon_character_subject(text, nearby_names) for text in user_role_texts):
            issues.append("ready_user_role_uses_canon_character_subject")
        if any(_uses_user_as_canon_group_member(text, nearby_names) for text in user_role_texts):
            issues.append("ready_user_role_as_canon_group_member")
        if hook_type in TRANSFER_HOOK_TYPES:
            if _string(identity_resolution.get("identity_mode")) == "unknown":
                issues.append("ready_transfer_identity_unknown")
            if hook_type == "대역" and _string(identity_resolution.get("identity_mode")) != "body_double_or_disguise":
                issues.append("ready_body_double_identity_mismatch")
            elif _string(identity_resolution.get("identity_mode")) not in HOOK_IDENTITY_ALLOWED.get(hook_type, set()):
                issues.append("ready_hook_identity_mismatch")
            transfer_required_fields = {
                "ready_missing_current_display_name": _string(identity_resolution.get("current_display_name")),
                "ready_missing_public_opening_name": _string(identity_resolution.get("public_opening_name")),
                "ready_missing_name_use_rule": _string(identity_resolution.get("name_use_rule")),
            }
            for issue, value in transfer_required_fields.items():
                if not value:
                    issues.append(issue)
        target_names = target_name_values
        identity_names = [
            identity_resolution.get("current_display_name"),
            identity_resolution.get("public_opening_name"),
            identity_resolution.get("host_or_avatar_name"),
        ]
        if not _names_overlap(target_names, identity_names):
            issues.append("ready_identity_target_name_mismatch")
        if len(_as_list(progression.get("next_beats"))) < 2:
            issues.append("ready_needs_at_least_two_next_beats")
        for beat_index, beat in enumerate(_as_list(progression.get("next_beats")), 1):
            beat_payload = _as_dict(beat)
            if not _string(beat_payload.get("beat")):
                issues.append(f"ready_next_beat_{beat_index}_missing_beat")
            if not _string(beat_payload.get("trigger")):
                issues.append(f"ready_next_beat_{beat_index}_missing_trigger")
            if not _string(beat_payload.get("avoid_repeating")):
                issues.append(f"ready_next_beat_{beat_index}_missing_avoid_repeating")
        if not _string(agency_contract.get("non_user_dependent_action")):
            issues.append("ready_missing_non_user_dependent_action")
        if not _string(agency_contract.get("user_influence_boundary")):
            issues.append("ready_missing_user_influence_boundary")
        if not _string(progression_engine.get("scene_exit_condition")):
            issues.append("ready_missing_scene_exit_condition")
        if len(_as_list(progression_engine.get("event_injection_rules"))) < 2:
            issues.append("ready_needs_at_least_two_event_injection_rules")
        for rule_index, rule in enumerate(_as_list(progression_engine.get("event_injection_rules")), 1):
            rule_payload = _as_dict(rule)
            if not _string(rule_payload.get("when")):
                issues.append(f"ready_event_injection_rule_{rule_index}_missing_when")
            if not _string(rule_payload.get("inject")):
                issues.append(f"ready_event_injection_rule_{rule_index}_missing_inject")
            if not _string(rule_payload.get("must_not_repeat")):
                issues.append(f"ready_event_injection_rule_{rule_index}_missing_must_not_repeat")
        if not _nonempty_strings(user_affordance_contract.get("forbidden_agency_load")):
            issues.append("ready_missing_forbidden_agency_load")
        if len(_nonempty_strings(user_affordance_contract.get("safe_response_examples"))) < 2:
            issues.append("ready_needs_at_least_two_safe_response_examples")
        if not _string(canon_safe_expansion.get("safe_new_event_pattern")):
            issues.append("ready_missing_safe_new_event_pattern")
        if not _nonempty_strings(canon_safe_expansion.get("forbidden_inventions")):
            issues.append("ready_missing_forbidden_inventions")
    return len(issues) == 0, issues


def build_user_prompt(row: dict[str, Any]) -> str:
    episode_blocks = []
    for episode in row.get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        episode_blocks.append(
            "\n".join(
                [
                    f"### Episode {episode.get('episodeNo')}: {episode.get('title') or ''}",
                    f"header_pattern: {episode.get('headerPattern')}",
                    f"text_chars: {episode.get('textChars')}",
                    f"label_text_truncated: {bool(episode.get('labelTextTruncated'))}",
                    str(episode.get("labelText") or ""),
                ]
            )
        )
    return "\n\n".join(
        [
            f"file_name: {row.get('fileName')}",
            f"split_confidence: {row.get('splitConfidence')}",
            f"labeling_bucket: {row.get('llmLabelingBucket')}",
            "아래 1~3화 텍스트만 근거로 캐릭터챗 opening label JSON을 작성하라.",
            *episode_blocks,
        ]
    )


def extract_openrouter_message_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = _as_dict(_as_dict(choices[0]).get("message"))
    content = message.get("content")
    if content:
        return str(content)
    reasoning = message.get("reasoning")
    if reasoning:
        return str(reasoning)
    return ""


def request_openrouter_label(
    client: httpx.Client,
    *,
    model: str,
    row: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    response = client.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://likenovel.net",
            "X-Title": "LikeNovel Character Chat Opening Labeler",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(row)},
            ],
            "temperature": 0.1,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    raw_payload = response.json()
    raw_text = extract_openrouter_message_text(raw_payload)
    try:
        parsed = extract_json_object(raw_text)
    except Exception as exc:
        raise LabelParseError(str(exc), raw_text) from exc
    return parsed, raw_payload.get("usage") or {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="캐릭터챗 opening labeler 실행")
    parser.add_argument("--input", required=True, help="build_character_chat_opening_label_inputs.py JSONL")
    parser.add_argument("--output", required=True, help="라벨 결과 JSONL")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0, help="입력 JSONL 앞에서 N줄 건너뛰기")
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--call-timeout", type=float, default=240.0, help="작품별 wall-clock 상한(초), 0이면 비활성")
    parser.add_argument("--env-file", default="", help="선택: shell source 없이 KEY=VALUE만 안전 로드")
    parser.add_argument("--resume", action="store_true", help="기존 output JSONL을 읽고 처리된 fileName은 건너뛰기")
    parser.add_argument("--retry-failed", action="store_true", help="--resume일 때 ok+schemaPass가 아닌 기존 row는 재시도")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 입력/프롬프트/출력 경로만 검증")
    return parser.parse_args()


def main() -> int:
    global OPENROUTER_API_KEY, OPENROUTER_BASE_URL
    args = parse_args()
    loaded_env_keys: list[str] = []
    if args.env_file:
        loaded_env_keys = load_env_file(Path(args.env_file))
        OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
        OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL).rstrip("/")
    rows = load_input_rows(Path(args.input), limit=args.limit, offset=args.offset)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "mode": "dry_run",
                    "input": args.input,
                    "output": args.output,
                    "model": args.model,
                    "offset": args.offset,
                    "inputRows": len(rows),
                    "firstPromptChars": len(build_user_prompt(rows[0])) if rows else 0,
                    "resume": args.resume,
                    "retryFailed": args.retry_failed,
                    "envFileLoadedKeys": sorted(
                        key for key in loaded_env_keys if key in {"OPENROUTER_API_KEY", "OPENROUTER_BASE_URL"}
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if not OPENROUTER_API_KEY:
        raise SystemExit("OPENROUTER_API_KEY is required unless --dry-run is set")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    existing_by_file = load_existing_results(out_path) if args.resume else {}
    file_mode = "a" if args.resume else "w"
    written = 0
    failed = 0
    skipped = 0
    with httpx.Client() as client, out_path.open(file_mode, encoding="utf-8") as fp:
        for index, row in enumerate(rows, 1):
            file_name = _string(row.get("fileName"))
            existing = existing_by_file.get(file_name)
            if should_skip_existing_result(existing, retry_failed=args.retry_failed):
                skipped += 1
                print(f"[{index}/{len(rows)}] {row.get('fileName')} skipped", flush=True)
                continue
            started = time.monotonic()
            try:
                with wall_clock_timeout(args.call_timeout):
                    payload, usage = request_openrouter_label(client, model=args.model, row=row)
                schema_pass, issues = validate_label_payload(payload)
                effective_status, effective_reasons = derive_effective_readiness(
                    payload,
                    schema_pass=schema_pass,
                    schema_issues=issues,
                )
                result = {
                    "fileName": row.get("fileName"),
                    "model": args.model,
                    "status": "ok",
                    "schemaPass": schema_pass,
                    "schemaIssues": issues,
                    "effectiveStatus": effective_status,
                    "effectiveBlockReasons": effective_reasons,
                    "latencySeconds": round(time.monotonic() - started, 3),
                    "usage": usage,
                    "label": payload,
                }
                written += 1
            except LabelParseError as exc:
                result = {
                    "fileName": row.get("fileName"),
                    "model": args.model,
                    "status": "parse_error",
                    "error": str(exc)[:500],
                    "rawTextSample": exc.raw_text[:10000],
                }
                failed += 1
            except LabelCallTimeoutError as exc:
                result = {
                    "fileName": row.get("fileName"),
                    "model": args.model,
                    "status": "timeout",
                    "error": str(exc),
                }
                failed += 1
            except Exception as exc:
                fatal_stop = is_openrouter_payment_required(exc)
                result = {
                    "fileName": row.get("fileName"),
                    "model": args.model,
                    "status": "api_payment_required" if fatal_stop else "error",
                    "error": str(exc)[:500],
                }
                failed += 1
            fp.write(json.dumps(result, ensure_ascii=False) + "\n")
            fp.flush()
            print(f"[{index}/{len(rows)}] {row.get('fileName')} {result['status']}", flush=True)
            if result["status"] == "api_payment_required":
                print("OpenRouter 402 Payment Required; stopping run. Refill credits, then resume with --resume --retry-failed.", flush=True)
                break
            if args.sleep > 0:
                time.sleep(args.sleep)
    print(
        json.dumps(
            {"output": str(out_path), "written": written, "failed": failed, "skipped": skipped},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
