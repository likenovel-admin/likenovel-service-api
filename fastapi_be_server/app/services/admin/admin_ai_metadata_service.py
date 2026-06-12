import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import settings
from app.exceptions import CustomResponseException
import app.services.ai.recommendation_service as recommendation_service

logger = logging.getLogger("admin_app")

MAX_RETRY_COUNT = 2  # 초기 1회 + 재시도 2회 = 총 3회
MAX_ANALYZE_EPISODES = 10
MAX_ANALYZE_CHARS = 60000
MAX_LLM_OUTPUT_TOKENS = 4096
MIN_REQUIRED_EPISODES = 3
MIN_FIRST_EPISODE_TEXT_COUNT = 1000

ALLOWED_ANALYSIS_STATUS = {"pending", "success", "failed"}
ALLOWED_EXCLUDE_YN = {"Y", "N"}
ALLOWED_HEROINE_WEIGHT = {"high", "mid", "low", "none"}
ALLOWED_PACING = {"fast", "medium", "slow"}
AXIS_ORDER = ("세", "직", "능", "연", "작", "타", "목")
# min은 전 축 0 — 부합 라벨이 없으면 빈 배열이 정답(근접 라벨 강제 매핑 금지)
AXIS_LIMITS: dict[str, tuple[int, int]] = {
    "세": (0, 3),
    "직": (0, 2),
    "능": (0, 4),
    "연": (0, 2),
    "작": (0, 3),
    "타": (0, 3),
    "목": (0, 1),
}

DNA_SYSTEM_PROMPT = """너는 라이크노벨 내부 메타 추출기 LN_AXIS_EXTRACTOR_V1이다.
입력된 정보(작품정보 + 도입부 회차 본문)를 읽고 작품 신호와 설명 메타를 추출한다.
출력은 반드시 JSON 단일 객체만 허용한다. 설명문, 마크다운, 코드블록 금지.

핵심 규칙:
1) 허용 라벨 목록 외 신규 라벨 생성 금지.
1-1) 각 라벨의 의미는 "라벨 정의" 섹션을 참고하여 판단한다. 이름만으로 추측하지 않는다.
1-2) 라벨은 상호배타 장르 분류가 아니라 AI추천구좌와 AI사서에서 작품을 엮는 작품 신호다.
1-2-1) 내부 그룹 키 의미는 다음과 같다. 세=무대, 세계관, 기관, 세력, 반복 배경, 직=직업, 직위, 사회적 역할, 전투 클래스, 능=능력, 시스템 메커니즘, 전투·성장 도구, 연=히로인·관계·애정 구도 신호, 작=작풍·정서·전개감·서사 질감, 타=주인공 상태, 서사 포지션, 핵심 세력과 속성, 목=반복 목표, 메인 루프, 주된 활동.
1-3) 주인공, 핵심 인물, 핵심 세력, 반복 소재, 갈등 축, 주요 배경이 강하게 연결되면 같은 작품에 여러 라벨을 동시에 부여한다.
1-4) 문파, 세력, 공간 라벨은 주인공 소속으로만 한정하지 않는다. 단순 언급이나 스쳐 지나가는 배경만으로는 선택하지 않는다.
1-4-1) 단순 언급, 비유 표현, 지나가는 배경, 1회성 몬스터, 직업, 장소, 농담성 대사만으로는 라벨을 선택하지 않는다.
1-5) 조합 라벨을 새로 만들지 않는다. 예: "아카데미빙의" 대신 "아카데미"와 "빙의"를 각각 선택한다.
1-6) 라벨 배열은 강한 근거 순서로 정렬한다. 제목, 태그, 줄거리, 초반 회차에서 반복되거나 갈등·목표·배경에 직접 연결된 라벨을 앞에 둔다.
1-6-1) 최대 개수를 채우려 하지 않는다. 두 번째 이후 라벨은 제목, 태그, 줄거리, 초반 회차에서 독립 근거가 확인될 때만 선택한다.
1-6-2) 시대 배경 라벨과 기관, 세력, 반복 공간 라벨은 서로 대체하지 않는다. 중세 세계에서 전사 아카데미 입학이 초반 목표라면 중세와 아카데미를 함께 선택한다.
1-7) 근거가 약하면 라벨을 선택하지 않는다. 어떤 그룹이든 부합하는 허용 라벨이 없으면 빈 배열로 둔다. 가장 가까운 라벨로 대체하지 않는다.
1-7-1) 상태창은 스탯, 스킬, 업적을 보여주는 정보 창이고, 시스템은 퀘스트·보상·페널티·상점·레벨업을 집행하는 메커니즘이다. 정보 표시만 있으면 상태창만 선택한다.
1-7-2) 회귀는 과거 특정 시점으로 돌아오는 1회성 또는 제한적 인생 재시작, 무한회귀는 실패 때마다 반복 재시도, 루프는 특정 사건·하루·구간 반복, 빙의는 타인의 몸이나 작품 속 인물 신분, 환생은 새 육체와 생애, 귀환자는 장기 생존 후 원래 세계 복귀, 차원이동은 살아 있는 상태의 세계 이동으로 구분한다.
1-7-3) 아카데미는 특수능력 교육기관, 학원은 현대 학교생활, 청춘, 교우관계, 학교는 물리적 학교 공간 사건이 중심일 때만 선택한다.
1-7-4) 하렘은 복수의 이성 캐릭터가 명확한 애정, 소유욕, 관계 긴장을 보일 때만, 조력자는 단순 도움 제공이 아니라 동등한 파트너십과 반복 동행이 작품 매력일 때만 선택한다.
1-7-5) 직 라벨은 실제 직업, 신분, 역할, 전투 클래스가 직접 확인될 때만 선택한다. 세계를 구하거나 사람을 구하는 목표만으로 소방관, 의사, 경찰 같은 직업을 추정하지 않는다.
1-7-6) 아카데미 입학, 편입, 선발시험, 평가전, 수련, 교사, 교수, 교관 활동이 초반 목표나 반복 사건이면 물리적 캠퍼스 장면이 적어도 아카데미를 선택한다.
1-8) summary의 모든 필드를 빈 값 없이 채운다. null 금지. themes와 taste_tags도 각각 1개 이상.
1-9) heroine이 없는 작품은 heroine_type에 주요 여성 캐릭터를 기재하고, heroine_weight는 "none"으로 설정한다.
2) 출력 JSON 스키마를 정확히 지킨다. axis_* 이름은 저장용 내부 키이며 판단 기준은 작품 신호와 작품 연결 라벨이다.
3) 목표 라벨 그룹(목)은 최대 1개. 라벨 정의를 참고하여 작품의 핵심 목표에 가장 부합하는 라벨을 선택하고, 부합하는 허용 라벨이 없으면 빈 배열로 둔다.
4) 관계와 케미 라벨 그룹(연)은 연애와 케미가 드러날 때만 선택 가능. 없으면 빈 배열 가능.
5) confidence는 0~1 범위 숫자.
6) axis_label_scores는 작품 연결 라벨별 확신도 목록으로 작성하고 각 score는 0~1 범위 숫자다.
7) evidence는 작품 신호를 선택한 회차 근거 중심으로 짧게 작성한다.
8) summary.premise는 핵심 설정이다. 작품을 움직이는 기본 전제, 규칙, 상황을 구체적으로 쓴다.
9) summary.hook은 초반 진입 포인트다. 광고 카피가 아니라 초반 1~3화에서 독자가 다음 화를 누르게 되는 구체적 사건, 위기, 목표, 반전, 보상 약속을 쓴다.
10) summary.hook에 "흥미진진한", "몰입감 있는", "기대되는" 같은 추상 홍보문구, 장르와 라벨 나열, 본문에 없는 기대감 생성을 쓰지 않는다.
11) episode_summary_text는 웹소설 전문 편집자 관점으로 작성한다.
12) episode_summary_text는 분석 대상 각 회차마다 정확히 3문장으로 요약한다.
13) 각 문장은 반드시 "누가, 무엇을, 왜" 구조가 드러나야 한다.
14) 갈등 심화, 전환점, 복선 배치·회수, 관계 변화 같은 서사적 기능을 우선 반영한다.
15) 플롯에 영향 없는 묘사와 감상은 제외한다.
16) 복선 또는 클리프행어가 있으면 해당 회차의 마지막 문장에서 암시한다.
17) 고유명사(인물명, 지명, 스킬명 등)는 원문 그대로 유지한다.
18) summary.protagonist_desc와 summary.episode_summary_text는 존댓말 없이 간결한 서술체(~했다, ~이다)로 작성한다.
18-1) summary.premise(핵심 설정)와 summary.hook(초반 진입 포인트)은 AI 사서 공개 소개에 그대로 쓰이므로 독자에게 말하듯 자연스러운 해요체로 작성한다. "다", "합니다", "입니다" 종결을 쓰지 않는다.
19) episode_summary_text는 줄바꿈 단위로 "<회차번호>화: <3문장 요약>" 형식을 지키고 최대 10화까지만 작성한다.
20) 설명형 메타(summary.protagonist_desc, premise, hook, episode_summary_text)는 한국어로만 작성하고, 고유명사 외 영문 표현을 남발하지 않는다.
21) 설명형 메타는 코드북 라벨 나열이나 복붙이 아니라 서사 정보 중심으로 작성한다.
22) 문자열 값 앞뒤에 불필요한 따옴표와 백틱 문자를 넣지 않는다.
"""

DNA_USER_TEMPLATE = """아래 작품 정보를 분석하여 JSON으로 응답하세요.

작품명: {title}
장르: {genres}
태그: {keywords}
줄거리: {synopsis_text}
회차수: {episode_count}화
연재상태: {status_code}
분석요청 회차수: {n_requested}
실제 분석 회차수: {n_received}

허용 작품 연결 라벨(내부 그룹 키 SSOT JSON):
{allowed_labels_json}

라벨 정의(작품 신호 판정 기준):
{label_definitions_text}

분석 회차 본문:
{episodes_text}

반드시 아래 JSON 스키마로만 응답:
{{
  "summary": {{
    "protagonist_type": "string",
    "protagonist_desc": "string",
    "heroine_type": "string",
    "heroine_weight": "high|mid|low|none",
    "mood": "string",
    "pacing": "fast|medium|slow",
    "premise": "string",
    "hook": "string",
    "episode_summary_text": "string",
    "themes": ["string"],
    "taste_tags": ["string"]
  }},
  "axis_labels": {{
    "세": ["string"],
    "직": ["string"],
    "능": ["string"],
    "연": ["string"],
    "작": ["string"],
    "타": ["string"],
    "목": ["string"]
  }},
  "axis_confidence": {{
    "세": 0.0,
    "직": 0.0,
    "능": 0.0,
    "연": 0.0,
    "작": 0.0,
    "타": 0.0,
    "목": 0.0
  }},
  "axis_label_scores": {{
    "세": [{{"label": "string", "score": 0.0}}],
    "직": [{{"label": "string", "score": 0.0}}],
    "능": [{{"label": "string", "score": 0.0}}],
    "연": [{{"label": "string", "score": 0.0}}],
    "작": [{{"label": "string", "score": 0.0}}],
    "타": [{{"label": "string", "score": 0.0}}],
    "목": [{{"label": "string", "score": 0.0}}]
  }},
  "overall_confidence": 0.0,
  "evidence": {{
    "세": ["string"],
    "직": ["string"],
    "능": ["string"],
    "연": ["string"],
    "작": ["string"],
    "타": ["string"],
    "목": ["string"]
  }}
}}"""

_ALLOWED_LABELS_BY_AXIS_CACHE: dict[str, set[str]] | None = None


def _allowed_labels_candidates() -> list[Path]:
    resolved = Path(__file__).resolve()
    parents = resolved.parents
    app_root = parents[3] if len(parents) > 3 else Path(settings.ROOT_PATH)

    candidates: list[Path] = [
        Path(settings.ROOT_PATH) / "dist" / "ai" / "allowed-labels-by-axis.json",
        app_root / "dist" / "ai" / "allowed-labels-by-axis.json",
    ]
    # 개발/로컬 실행 위치 차이를 흡수하기 위해 상위 경로를 순회하며 docs fallback을 탐색한다.
    for parent in parents:
        candidates.append(parent / "docs" / "ai-codebook" / "allowed-labels-by-axis.json")

    # 중복 경로 제거(순서 유지)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        deduped.append(path)
        seen.add(path)
    return deduped


def _load_allowed_labels_by_axis() -> dict[str, set[str]]:
    global _ALLOWED_LABELS_BY_AXIS_CACHE
    if _ALLOWED_LABELS_BY_AXIS_CACHE is not None:
        return _ALLOWED_LABELS_BY_AXIS_CACHE

    for path in _allowed_labels_candidates():
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig") as fp:
            raw = json.load(fp)
        if not isinstance(raw, dict):
            raise ValueError("allowed-labels-by-axis.json format is invalid")

        loaded: dict[str, set[str]] = {}
        for axis in AXIS_ORDER:
            values = raw.get(axis)
            if not isinstance(values, list):
                raise ValueError(f"allowed-labels-by-axis axis '{axis}' must be list")
            normalized = {
                str(value).strip()
                for value in values
                if isinstance(value, str) and str(value).strip()
            }
            if not normalized:
                raise ValueError(f"allowed-labels-by-axis axis '{axis}' is empty")
            loaded[axis] = normalized
        _ALLOWED_LABELS_BY_AXIS_CACHE = loaded
        return loaded

    raise ValueError("allowed-labels-by-axis.json 파일을 찾을 수 없습니다.")


def _allowed_labels_for_prompt() -> str:
    loaded = _load_allowed_labels_by_axis()
    ordered = {axis: sorted(loaded[axis]) for axis in AXIS_ORDER}
    return json.dumps(ordered, ensure_ascii=False)


def _label_defs_candidates() -> list[Path]:
    resolved = Path(__file__).resolve()
    parents = resolved.parents
    app_root = parents[3] if len(parents) > 3 else Path(settings.ROOT_PATH)

    candidates: list[Path] = [
        Path(settings.ROOT_PATH) / "dist" / "ai" / "label-definitions-by-axis.json",
        app_root / "dist" / "ai" / "label-definitions-by-axis.json",
    ]
    for parent in parents:
        candidates.append(parent / "docs" / "ai-codebook" / "label-definitions-by-axis.json")

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        deduped.append(path)
        seen.add(path)
    return deduped


_LABEL_DEFS_CACHE: str | None = None


def _load_label_definitions() -> str:
    """라벨 정의 JSON을 프롬프트용 텍스트로 변환."""
    global _LABEL_DEFS_CACHE
    if _LABEL_DEFS_CACHE is not None:
        return _LABEL_DEFS_CACHE

    for path in _label_defs_candidates():
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig") as fp:
            raw = json.load(fp)
        lines = []
        for axis, defs in raw.items():
            if isinstance(defs, dict):
                for label, desc in defs.items():
                    lines.append(f"  [{axis}] {label}: {desc}")
        _LABEL_DEFS_CACHE = "\n".join(lines)
        return _LABEL_DEFS_CACHE
    _LABEL_DEFS_CACHE = ""
    return _LABEL_DEFS_CACHE


def _strip_html(content: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", content or "")
    return re.sub(r"\s+", " ", no_tags).strip()


def _safe_text(value: Any, field_name: str, max_length: int, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be string")
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"{field_name} is required")
    if not normalized:
        return None
    return normalized[:max_length]


def _sanitize_korean_narrative_text(
    value: Any,
    field_name: str,
    max_length: int,
    *,
    required: bool = False,
    min_length: int = 0,
) -> str | None:
    text = _safe_text(value, field_name, max_length, required=required)
    if text is None:
        return None

    text = text.strip(" \t\n\r\"'`“”")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if required and not text:
        raise ValueError(f"{field_name} is required")
    if not text:
        return None
    if min_length > 0 and len(text) < min_length:
        if required:
            raise ValueError(f"{field_name} is too short")
        return None

    hangul_count = len(re.findall(r"[가-힣]", text))
    english_count = len(re.findall(r"[A-Za-z]", text))
    if hangul_count == 0:
        if required:
            raise ValueError(f"{field_name} must contain Korean text")
        return None
    if english_count > 0 and english_count >= hangul_count:
        if required:
            raise ValueError(f"{field_name} contains too much English text")
        return None

    return text[:max_length]


def _sanitize_episode_summary_text(value: Any) -> str | None:
    raw = _safe_text(value, "episode_summary_text", 5000)
    if raw is None:
        return None

    lines: list[str] = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        stripped = stripped.strip(" \t\n\r\"'`“”")
        stripped = re.sub(r"[ \t]+", " ", stripped).strip()
        if not re.match(r"^\d+화\s*:", stripped):
            continue
        if not re.search(r"[가-힣]", stripped):
            continue
        lines.append(stripped)

    if not lines:
        return None
    return "\n".join(lines)[:5000]


def _safe_enum(value: Any, field_name: str, allowed: set[str], required: bool = False) -> str | None:
    normalized = _safe_text(value, field_name, 50, required=required)
    if normalized is None:
        return None
    if normalized not in allowed:
        raise ValueError(f"{field_name} must be one of {sorted(allowed)}")
    return normalized


def _safe_confidence(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    try:
        casted = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be number")
    if casted < 0 or casted > 1:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return round(casted, 4)


def _safe_list(value: Any, field_name: str, max_items: int = 15, max_item_length: int = 100) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be list")

    normalized_items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} item must be string")
        stripped = item.strip()
        if not stripped:
            continue
        normalized_items.append(stripped[:max_item_length])
        if len(normalized_items) >= max_items:
            break
    return list(dict.fromkeys(normalized_items))


def _axis_raw_values(payload: dict[str, Any], axis_labels: dict[str, Any], axis: str) -> Any:
    field_map = {
        "세": "worldview_tags",
        "직": "protagonist_job_tags",
        "능": "protagonist_material_tags",
        "연": "axis_romance_tags",
        "작": "axis_style_tags",
        "타": "protagonist_type_tags",
        "목": "protagonist_goal_primary",
    }
    if axis in axis_labels:
        return axis_labels.get(axis)
    field_name = field_map[axis]
    fallback = payload.get(field_name)
    if axis == "목" and fallback is not None and not isinstance(fallback, list):
        return [fallback]
    return fallback


def _safe_axis_labels(
    value: Any,
    axis: str,
    field_name: str,
    allowed_labels: set[str],
    min_items: int,
    max_items: int,
    enforce_minimum: bool,
    drop_unsupported: bool,
) -> list[str]:
    if isinstance(value, str):
        value = [value]
    items = _safe_list(value, field_name, max_items=max_items, max_item_length=50)
    if drop_unsupported:
        items = [item for item in items if item in allowed_labels]
    else:
        for item in items:
            if item not in allowed_labels:
                raise ValueError(f"{field_name} contains unsupported label: {item}")

    # 자동 재분석에서는 축이 비는 경우를 허용한다(해당 축 없음으로 처리).
    if enforce_minimum and axis != "목" and len(items) < min_items:
        return []
    return items


def _flatten_text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.extend(_flatten_text_values(item))
        return parts
    if isinstance(value, dict):
        parts: list[str] = []
        for item in value.values():
            parts.extend(_flatten_text_values(item))
        return parts
    return []


def _payload_evidence_text(payload: dict[str, Any], source_text: str = "") -> str:
    parts = [source_text]
    summary = payload.get("summary")
    if isinstance(summary, dict):
        parts.extend(_flatten_text_values(summary))
    evidence = payload.get("evidence")
    if isinstance(evidence, dict):
        parts.extend(_flatten_text_values(evidence))
    return "\n".join(part for part in parts if part)


def _has_academy_evidence(text: str) -> bool:
    if "아카데미" not in text:
        return False
    return any(
        marker in text
        for marker in (
            "입학",
            "편입",
            "선발시험",
            "평가전",
            "강의",
            "수련",
            "교사",
            "교수",
            "교관",
            "아카데미생",
            "아카데미 학생",
            "아카데미 파티",
            "전사 아카데미",
            "마법 아카데미",
        )
    )


def _has_status_window_evidence(text: str) -> bool:
    negative_markers = ("상태창이나 시스템은 없", "상태창은 없", "상태창 없음")
    if any(marker in text for marker in negative_markers):
        return False
    return any(
        marker in text
        for marker in ("상태창", "스탯", "능력치", "업적", "눈앞 UI", "정보 인터페이스")
    )


def _has_buff_evidence(text: str) -> bool:
    return "버프" in text or ("계약" in text and any(marker in text for marker in ("힘을 얻", "강화", "능력")))


def _has_possession_evidence(text: str) -> bool:
    negative_markers = ("시스템이 빙의", "프로그램이 설치", "빙의한 형태")
    if any(marker in text for marker in negative_markers):
        return False
    return any(
        marker in text
        for marker in (
            "몸에 빙의",
            "몸으로 빙의",
            "몸에 들어",
            "몸으로 들어",
            "빙의해",
            "빙의한",
            "빙의되",
            "빙의한다",
            "소설 속",
            "작품 속",
            "게임 속",
            "타인의 몸",
            "남의 몸",
            "다른 사람의 몸",
        )
    )


def _has_growth_evidence(text: str) -> bool:
    return any(marker in text for marker in ("성장", "데뷔", "훈련", "수련", "레벨업", "퀘스트", "목표"))


def _has_monster_hunter_evidence(text: str) -> bool:
    return any(marker in text for marker in ("괴물사냥꾼", "괴물 사냥", "괴물을 사냥", "몬스터 사냥"))


def _apply_axis_label_evidence_guards(
    axis_labels: dict[str, list[str]],
    allowed_labels: dict[str, set[str]],
    source_text: str = "",
) -> dict[str, list[str]]:
    if not source_text:
        return axis_labels

    guarded = {axis: list(labels) for axis, labels in axis_labels.items()}

    firefighter_markers = ("소방서", "화재", "구급", "119", "구조 출동", "재난 현장", "소방 공무원", "소방대")
    if "소방관" in guarded["직"] and not any(marker in source_text for marker in firefighter_markers):
        guarded["직"] = [label for label in guarded["직"] if label != "소방관"]

    knight_negative_markers = (
        "자신은 기사가 아님",
        "주인공은 기사가 아님",
        "로머 자신은 기사가 아님",
        "주인공의 아버지가 기사",
        "아버지가 기사",
    )
    if "기사" in guarded["직"] and any(marker in source_text for marker in knight_negative_markers):
        guarded["직"] = [label for label in guarded["직"] if label != "기사"]
        if "헌터" in allowed_labels["직"] and "헌터" not in guarded["직"] and _has_monster_hunter_evidence(source_text):
            guarded["직"].append("헌터")

    if "상태창" in guarded["능"] and not _has_status_window_evidence(source_text):
        guarded["능"] = [label for label in guarded["능"] if label != "상태창"]
        if "버프" in allowed_labels["능"] and "버프" not in guarded["능"] and _has_buff_evidence(source_text):
            guarded["능"].append("버프")

    if "빙의" in guarded["타"] and not _has_possession_evidence(source_text):
        guarded["타"] = [label for label in guarded["타"] if label != "빙의"]
        if not guarded["타"] and "성장형" in allowed_labels["타"] and _has_growth_evidence(source_text):
            guarded["타"].append("성장형")

    _, worldview_max_items = AXIS_LIMITS["세"]
    if (
        "아카데미" in allowed_labels["세"]
        and "아카데미" not in guarded["세"]
        and len(guarded["세"]) < worldview_max_items
        and _has_academy_evidence(source_text)
    ):
        guarded["세"].append("아카데미")

    return guarded


def _normalize_axis_label_scores(
    raw_scores: Any,
    axis_labels: dict[str, list[str]],
    axis_confidence: dict[str, float | None],
) -> dict[str, list[dict[str, float]]]:
    if not isinstance(raw_scores, dict):
        raw_scores = {}

    normalized_scores: dict[str, list[dict[str, float]]] = {}
    for axis in AXIS_ORDER:
        labels = axis_labels[axis]
        axis_raw = raw_scores.get(axis)

        parsed: dict[str, float] = {}
        candidates: list[dict[str, Any]] = []
        if isinstance(axis_raw, list):
            candidates = [item for item in axis_raw if isinstance(item, dict)]
        elif isinstance(axis_raw, dict):
            candidates = [{"label": key, "score": value} for key, value in axis_raw.items()]

        for item in candidates:
            label = item.get("label")
            if not isinstance(label, str):
                continue
            key = label.strip()
            if not key or key not in labels:
                continue
            try:
                score = _safe_confidence(item.get("score"), f"axis_label_scores.{axis}.{key}")
            except ValueError:
                continue
            if score is None:
                continue
            parsed[key] = score

        fallback = axis_confidence.get(axis)
        if fallback is None:
            fallback = 0.0
        normalized_scores[axis] = [{"label": label, "score": parsed.get(label, fallback)} for label in labels]

    return normalized_scores


def _build_episode_context(episodes: list[dict[str, Any]]) -> tuple[str, int]:
    chunks: list[str] = []
    total_chars = 0
    used_count = 0
    for episode in episodes:
        episode_no = int(episode.get("episode_no") or 0)
        episode_title = (episode.get("episode_title") or "").strip()
        episode_text = _strip_html(episode.get("episode_content") or "")
        if not episode_text:
            continue

        marker = f"[EP{episode_no:02d}] {episode_title}".strip()
        room = MAX_ANALYZE_CHARS - total_chars
        if room <= len(marker) + 4:
            break
        truncated = episode_text[: room - len(marker) - 4]
        block = f"{marker}\n{truncated}"
        chunks.append(block)
        total_chars += len(block)
        used_count += 1
    return "\n\n".join(chunks), used_count


def _build_axis_labels_from_columns(normalized: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "세": normalized["worldview_tags"],
        "직": normalized["protagonist_job_tags"],
        "능": normalized["protagonist_material_tags"],
        "연": normalized["axis_romance_tags"],
        "작": normalized["axis_style_tags"],
        "타": normalized["protagonist_type_tags"],
        "목": [normalized["protagonist_goal_primary"]] if normalized["protagonist_goal_primary"] else [],
    }


def _normalize_ai_payload(
    payload: dict[str, Any],
    *,
    enforce_axis_minimum: bool,
    enforce_legacy_required: bool,
    drop_unsupported_axis_labels: bool = False,
    source_text: str = "",
) -> dict[str, Any]:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = payload.get("metadata")
    if not isinstance(summary, dict):
        summary = {}

    def pick(key: str) -> Any:
        if key in payload:
            return payload.get(key)
        return summary.get(key)

    allowed = _load_allowed_labels_by_axis()
    raw_axis_labels = payload.get("axis_labels")
    if not isinstance(raw_axis_labels, dict):
        raw_axis_labels = {}

    axis_labels: dict[str, list[str]] = {}
    for axis in AXIS_ORDER:
        min_items, max_items = AXIS_LIMITS[axis]
        axis_labels[axis] = _safe_axis_labels(
            _axis_raw_values(payload, raw_axis_labels, axis),
            axis,
            f"axis_labels.{axis}",
            allowed_labels=allowed[axis],
            min_items=min_items,
            max_items=max_items,
            enforce_minimum=enforce_axis_minimum,
            drop_unsupported=drop_unsupported_axis_labels,
        )

    axis_labels = _apply_axis_label_evidence_guards(
        axis_labels,
        allowed,
        _payload_evidence_text(payload, source_text),
    )

    goal_labels = axis_labels["목"]
    if not goal_labels:
        fallback_goal = _safe_text(pick("protagonist_goal_primary"), "protagonist_goal_primary", 30)
        if fallback_goal and fallback_goal in allowed["목"]:
            goal_labels = [fallback_goal]
        axis_labels["목"] = goal_labels

    axis_confidence = payload.get("axis_confidence")
    if not isinstance(axis_confidence, dict):
        axis_confidence = {}
    axis_confidence_normalized = {
        axis: _safe_confidence(axis_confidence.get(axis), f"axis_confidence.{axis}")
        for axis in AXIS_ORDER
    }
    axis_label_scores = _normalize_axis_label_scores(
        payload.get("axis_label_scores"),
        axis_labels,
        axis_confidence_normalized,
    )

    protagonist_type = _safe_text(pick("protagonist_type"), "protagonist_type", 200)
    if protagonist_type is None and axis_labels["타"]:
        protagonist_type = axis_labels["타"][0]

    taste_tags = _safe_list(pick("taste_tags"), "taste_tags", max_items=30, max_item_length=100)
    if not taste_tags:
        merged = (
            axis_labels["세"]
            + axis_labels["직"]
            + axis_labels["능"]
            + axis_labels["연"]
            + axis_labels["작"]
            + axis_labels["타"]
            + axis_labels["목"]
        )
        taste_tags = list(dict.fromkeys(merged))[:30]

    normalized = {
        "protagonist_type": protagonist_type,
        "protagonist_desc": _sanitize_korean_narrative_text(
            pick("protagonist_desc"),
            "protagonist_desc",
            500,
            min_length=8,
        ),
        "heroine_type": _safe_text(pick("heroine_type"), "heroine_type", 200),
        "heroine_weight": _safe_enum(pick("heroine_weight"), "heroine_weight", ALLOWED_HEROINE_WEIGHT),
        "romance_chemistry_weight": _safe_enum(
            pick("romance_chemistry_weight"),
            "romance_chemistry_weight",
            ALLOWED_HEROINE_WEIGHT,
        ),
        "mood": _safe_text(pick("mood"), "mood", 200),
        "pacing": _safe_enum(pick("pacing"), "pacing", ALLOWED_PACING),
        "premise": _sanitize_korean_narrative_text(
            pick("premise"),
            "premise",
            500,
            min_length=10,
        ),
        "hook": _sanitize_korean_narrative_text(
            pick("hook"),
            "hook",
            300,
            min_length=6,
        ),
        "episode_summary_text": _sanitize_episode_summary_text(pick("episode_summary_text")),
        "themes": _safe_list(pick("themes"), "themes"),
        "similar_famous": [],
        "taste_tags": taste_tags,
        "protagonist_material_tags": axis_labels["능"],
        "worldview_tags": axis_labels["세"],
        "protagonist_type_tags": axis_labels["타"],
        "protagonist_job_tags": axis_labels["직"],
        "axis_style_tags": axis_labels["작"],
        "axis_romance_tags": axis_labels["연"],
        "protagonist_goal_primary": goal_labels[0] if goal_labels else None,
        "goal_confidence": _safe_confidence(
            pick("goal_confidence") if pick("goal_confidence") is not None else axis_confidence_normalized.get("목"),
            "goal_confidence",
        ),
        "overall_confidence": _safe_confidence(pick("overall_confidence"), "overall_confidence"),
        "axis_label_scores": axis_label_scores,
    }

    if normalized["romance_chemistry_weight"] is None:
        normalized["romance_chemistry_weight"] = "mid" if normalized["axis_romance_tags"] else "none"

    if enforce_legacy_required:
        normalized["protagonist_type"] = _safe_text(
            normalized["protagonist_type"], "protagonist_type", 200, required=True
        )
        normalized["protagonist_desc"] = _sanitize_korean_narrative_text(
            normalized["protagonist_desc"],
            "protagonist_desc",
            500,
            required=True,
            min_length=8,
        )
        normalized["heroine_type"] = _safe_text(
            normalized["heroine_type"], "heroine_type", 200, required=True
        )
        normalized["heroine_weight"] = _safe_enum(
            normalized["heroine_weight"], "heroine_weight", ALLOWED_HEROINE_WEIGHT, required=True
        )
        normalized["mood"] = _safe_text(normalized["mood"], "mood", 200, required=True)
        normalized["pacing"] = _safe_enum(
            normalized["pacing"], "pacing", ALLOWED_PACING, required=True
        )
        normalized["premise"] = _sanitize_korean_narrative_text(
            normalized["premise"],
            "premise",
            500,
            required=True,
            min_length=10,
        )
        normalized["hook"] = _sanitize_korean_narrative_text(
            normalized["hook"],
            "hook",
            300,
            required=True,
            min_length=6,
        )
        if not normalized["themes"]:
            raise ValueError("themes requires at least 1 item")

    return normalized


async def _get_product_for_analysis(product_id: int, db: AsyncSession) -> dict[str, Any]:
    query = text(
        """
        SELECT
            p.product_id, p.title, p.status_code, p.count_hit,
            p.price_type, p.author_name AS author_nickname,
            COALESCE(u.role_type, 'normal') AS author_role_type,
            (
                SELECT CONCAT_WS('/', pg.keyword_name, sg.keyword_name)
                FROM tb_standard_keyword pg
                LEFT JOIN tb_standard_keyword sg
                    ON sg.keyword_id = p.sub_genre_id AND sg.use_yn = 'Y'
                WHERE pg.keyword_id = p.primary_genre_id
                  AND pg.use_yn = 'Y'
            ) AS genres,
            (
                SELECT GROUP_CONCAT(DISTINCT sk.keyword_name SEPARATOR ', ')
                FROM tb_mapped_product_keyword mpk
                LEFT JOIN tb_standard_keyword sk ON sk.keyword_id = mpk.keyword_id
                WHERE mpk.product_id = p.product_id
            ) AS keywords,
            p.synopsis_text,
            (
                SELECT e.episode_text_count
                FROM tb_product_episode e
                WHERE e.product_id = p.product_id
                  AND e.episode_no = 1
                  AND e.use_yn = 'Y'
                  AND e.open_yn = 'Y'
                ORDER BY e.episode_id ASC
                LIMIT 1
            ) AS first_episode_text_count,
            (
                SELECT COUNT(*)
                FROM tb_product_episode e
                WHERE e.product_id = p.product_id
                  AND e.use_yn = 'Y'
                  AND e.open_yn = 'Y'
            ) AS episode_count
        FROM tb_product p
        LEFT JOIN tb_user u ON u.user_id = p.user_id
        WHERE p.product_id = :product_id
        LIMIT 1
        """
    )
    result = await db.execute(query, {"product_id": product_id})
    row = result.mappings().one_or_none()
    if not row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="작품 정보를 찾을 수 없습니다.",
        )

    product = dict(row)
    if product.get("author_role_type") == "admin":
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="관리자 작성 작품은 AI 메타 수집 대상이 아닙니다.",
        )
    if not (product.get("author_nickname") or "").strip():
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="작가명이 비어있는 작품은 AI 메타 수집 대상이 아닙니다.",
        )
    if (product.get("first_episode_text_count") or 0) < MIN_FIRST_EPISODE_TEXT_COUNT:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=f"첫 회차 {MIN_FIRST_EPISODE_TEXT_COUNT}자 미만 작품은 AI 메타 수집 대상이 아닙니다.",
        )
    return product


async def _get_episodes_for_analysis(product_id: int, db: AsyncSession) -> list[dict[str, Any]]:
    query = text(
        """
        SELECT
            e.episode_no,
            e.episode_title,
            e.episode_content
        FROM tb_product_episode e
        WHERE e.product_id = :product_id
          AND e.use_yn = 'Y'
          AND e.open_yn = 'Y'
        ORDER BY e.episode_no ASC
        LIMIT :max_episode
        """
    )
    result = await db.execute(
        query,
        {
            "product_id": product_id,
            "max_episode": MAX_ANALYZE_EPISODES,
        },
    )
    return [dict(row) for row in result.mappings().all()]


async def _mark_analysis_failed(
    product_id: int,
    analysis_attempt_count: int,
    error_message: str,
    db: AsyncSession,
) -> None:
    failed_query = text(
        """
        INSERT INTO tb_product_ai_metadata (
            product_id, analysis_status, analysis_attempt_count, analysis_error_message, model_version
        ) VALUES (
            :product_id, 'failed', :analysis_attempt_count, :analysis_error_message, :model_version
        )
        ON DUPLICATE KEY UPDATE
            analysis_status = 'failed',
            analysis_attempt_count = VALUES(analysis_attempt_count),
            analysis_error_message = VALUES(analysis_error_message),
            model_version = VALUES(model_version),
            updated_date = NOW()
        """
    )
    await db.execute(
        failed_query,
        {
            "product_id": product_id,
            "analysis_attempt_count": analysis_attempt_count,
            "analysis_error_message": (error_message or "unknown error")[:1000],
            "model_version": settings.ANTHROPIC_MODEL,
        },
    )
    await db.commit()


async def ai_product_metadata_list(
    search_target: str,
    search_word: str,
    analysis_status: str,
    exclude_from_recommend_yn: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
) -> dict[str, Any]:
    page = max(page, 1)
    count_per_page = max(1, min(count_per_page, 100))

    where_clauses = [
        "p.open_yn = 'Y'",
        "COALESCE(u.role_type, 'normal') != 'admin'",
        "COALESCE(TRIM(p.author_name), '') != ''",
        f"""
        EXISTS (
            SELECT 1
            FROM tb_product_episode fe
            WHERE fe.product_id = p.product_id
              AND fe.episode_no = 1
              AND fe.use_yn = 'Y'
              AND fe.open_yn = 'Y'
              AND fe.episode_text_count >= {MIN_FIRST_EPISODE_TEXT_COUNT}
        )
        """,
    ]
    params: dict[str, Any] = {}

    if search_target and search_word:
        if search_target == "product-title":
            where_clauses.append("p.title LIKE :search_word")
            params["search_word"] = f"%{search_word}%"
        elif search_target == "author-name":
            where_clauses.append("p.author_name LIKE :search_word")
            params["search_word"] = f"%{search_word}%"

    if analysis_status and analysis_status != "all":
        if analysis_status == "missing":
            where_clauses.append("m.product_id IS NULL")
        elif analysis_status == "pending":
            where_clauses.append("m.product_id IS NOT NULL AND m.analysis_status = :analysis_status")
            params["analysis_status"] = analysis_status
        elif analysis_status in ALLOWED_ANALYSIS_STATUS:
            where_clauses.append("m.analysis_status = :analysis_status")
            params["analysis_status"] = analysis_status

    if exclude_from_recommend_yn and exclude_from_recommend_yn != "all":
        if exclude_from_recommend_yn in ALLOWED_EXCLUDE_YN:
            where_clauses.append("COALESCE(m.exclude_from_recommend_yn, 'N') = :exclude_from_recommend_yn")
            params["exclude_from_recommend_yn"] = exclude_from_recommend_yn

    where_sql = " AND ".join(where_clauses)
    offset = (page - 1) * count_per_page

    count_query = text(
        f"""
        SELECT COUNT(*) AS total_count
        FROM tb_product p
        LEFT JOIN tb_user u ON u.user_id = p.user_id
        LEFT JOIN tb_product_ai_metadata m ON m.product_id = p.product_id
        WHERE {where_sql}
        """
    )
    count_result = await db.execute(count_query, params)
    total_count = dict(count_result.mappings().one()).get("total_count", 0)

    list_query = text(
        f"""
        SELECT
            p.product_id,
            p.title,
            p.author_name,
            p.price_type,
            COALESCE(m.analysis_status, 'missing') AS analysis_status,
            COALESCE(m.analysis_attempt_count, 0) AS analysis_attempt_count,
            COALESCE(m.exclude_from_recommend_yn, 'N') AS exclude_from_recommend_yn,
            m.analysis_error_message,
            m.analyzed_at,
            m.updated_date
        FROM tb_product p
        LEFT JOIN tb_user u ON u.user_id = p.user_id
        LEFT JOIN tb_product_ai_metadata m ON m.product_id = p.product_id
        WHERE {where_sql}
        ORDER BY p.product_id DESC
        LIMIT :limit OFFSET :offset
        """
    )
    params["limit"] = count_per_page
    params["offset"] = offset
    result = await db.execute(list_query, params)
    rows = [dict(row) for row in result.mappings().all()]

    return {
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "results": rows,
    }


async def ai_product_metadata_detail(product_id: int, db: AsyncSession) -> dict[str, Any]:
    query = text(
        """
        SELECT
            p.product_id,
            p.title,
            p.author_name,
            p.price_type,
            p.status_code,
            p.synopsis_text,
            m.protagonist_type,
            m.protagonist_desc,
            m.heroine_type,
            m.heroine_weight,
            m.romance_chemistry_weight,
            m.mood,
            m.pacing,
            m.premise,
            m.hook,
            m.episode_summary_text,
            m.protagonist_goal_primary,
            m.goal_confidence,
            m.overall_confidence,
            m.axis_label_scores,
            m.protagonist_material_tags,
            m.worldview_tags,
            m.protagonist_type_tags,
            m.protagonist_job_tags,
            m.axis_style_tags,
            m.axis_romance_tags,
            m.themes,
            m.similar_famous,
            m.taste_tags,
            m.raw_analysis,
            COALESCE(m.analysis_status, 'missing') AS analysis_status,
            COALESCE(m.analysis_attempt_count, 0) AS analysis_attempt_count,
            m.analysis_error_message,
            COALESCE(m.exclude_from_recommend_yn, 'N') AS exclude_from_recommend_yn,
            m.analyzed_at,
            m.updated_date
        FROM tb_product p
        LEFT JOIN tb_product_ai_metadata m ON m.product_id = p.product_id
        WHERE p.product_id = :product_id
        LIMIT 1
        """
    )
    result = await db.execute(query, {"product_id": product_id})
    row = result.mappings().one_or_none()
    if not row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="작품 정보를 찾을 수 없습니다.",
        )

    detail = dict(row)
    for key in (
        "protagonist_material_tags",
        "worldview_tags",
        "protagonist_type_tags",
        "protagonist_job_tags",
        "axis_style_tags",
        "axis_romance_tags",
        "axis_label_scores",
        "themes",
        "similar_famous",
        "taste_tags",
        "raw_analysis",
    ):
        if isinstance(detail.get(key), str):
            try:
                detail[key] = json.loads(detail[key])
            except (json.JSONDecodeError, TypeError):
                pass

    detail["axis_labels"] = {
        "세": detail.get("worldview_tags") or [],
        "직": detail.get("protagonist_job_tags") or [],
        "능": detail.get("protagonist_material_tags") or [],
        "연": detail.get("axis_romance_tags") or [],
        "작": detail.get("axis_style_tags") or [],
        "타": detail.get("protagonist_type_tags") or [],
        "목": [detail["protagonist_goal_primary"]] if detail.get("protagonist_goal_primary") else [],
    }

    return {"data": detail}


async def _get_current_ai_metadata_for_merge(product_id: int, db: AsyncSession) -> dict[str, Any]:
    query = text(
        """
        SELECT
            protagonist_type,
            protagonist_desc,
            heroine_type,
            heroine_weight,
            romance_chemistry_weight,
            mood,
            pacing,
            premise,
            hook,
            episode_summary_text,
            protagonist_goal_primary,
            goal_confidence,
            overall_confidence,
            axis_label_scores,
            protagonist_material_tags,
            worldview_tags,
            protagonist_type_tags,
            protagonist_job_tags,
            axis_style_tags,
            axis_romance_tags,
            themes,
            similar_famous,
            taste_tags
        FROM tb_product_ai_metadata
        WHERE product_id = :product_id
        LIMIT 1
        """
    )
    result = await db.execute(query, {"product_id": product_id})
    row = result.mappings().one_or_none()
    if not row:
        return {}

    current = dict(row)
    for key in (
        "protagonist_material_tags",
        "worldview_tags",
        "protagonist_type_tags",
        "protagonist_job_tags",
        "axis_style_tags",
        "axis_romance_tags",
        "axis_label_scores",
        "themes",
        "similar_famous",
        "taste_tags",
    ):
        if isinstance(current.get(key), str):
            try:
                current[key] = json.loads(current[key])
            except (json.JSONDecodeError, TypeError):
                current[key] = []
    return current


async def put_ai_product_metadata(
    product_id: int,
    req_body,
    db: AsyncSession,
) -> dict[str, Any]:
    await _get_product_for_analysis(product_id, db)

    payload = req_body.model_dump(exclude_unset=True)
    if not payload:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="수정할 데이터가 없습니다.",
        )

    # 부분 업데이트 시 누락 필드는 기존 DB값을 유지해 7축 메타 소실을 방지한다.
    current_values = await _get_current_ai_metadata_for_merge(product_id, db)
    merged_payload = {**current_values, **payload}

    try:
        normalized = _normalize_ai_payload(
            merged_payload,
            enforce_axis_minimum=False,
            enforce_legacy_required=True,
            drop_unsupported_axis_labels=False,
        )
    except ValueError as e:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=str(e),
        )

    query = text(
        """
        INSERT INTO tb_product_ai_metadata (
            product_id,
            protagonist_type, protagonist_desc, heroine_type, heroine_weight, romance_chemistry_weight,
            mood, pacing, premise, hook,
            episode_summary_text,
            protagonist_goal_primary, goal_confidence, overall_confidence, axis_label_scores,
            protagonist_material_tags, worldview_tags, protagonist_type_tags, protagonist_job_tags, axis_style_tags, axis_romance_tags,
            themes, similar_famous, taste_tags,
            analysis_status, analysis_error_message, model_version, analyzed_at
        ) VALUES (
            :product_id,
            :protagonist_type, :protagonist_desc, :heroine_type, :heroine_weight, :romance_chemistry_weight,
            :mood, :pacing, :premise, :hook,
            :episode_summary_text,
            :protagonist_goal_primary, :goal_confidence, :overall_confidence, :axis_label_scores,
            :protagonist_material_tags, :worldview_tags, :protagonist_type_tags, :protagonist_job_tags, :axis_style_tags, :axis_romance_tags,
            :themes, :similar_famous, :taste_tags,
            'success', NULL, 'manual-edit', NOW()
        )
        ON DUPLICATE KEY UPDATE
            protagonist_type = VALUES(protagonist_type),
            protagonist_desc = VALUES(protagonist_desc),
            heroine_type = VALUES(heroine_type),
            heroine_weight = VALUES(heroine_weight),
            romance_chemistry_weight = VALUES(romance_chemistry_weight),
            mood = VALUES(mood),
            pacing = VALUES(pacing),
            premise = VALUES(premise),
            hook = VALUES(hook),
            episode_summary_text = VALUES(episode_summary_text),
            protagonist_goal_primary = VALUES(protagonist_goal_primary),
            goal_confidence = VALUES(goal_confidence),
            overall_confidence = VALUES(overall_confidence),
            axis_label_scores = VALUES(axis_label_scores),
            protagonist_material_tags = VALUES(protagonist_material_tags),
            worldview_tags = VALUES(worldview_tags),
            protagonist_type_tags = VALUES(protagonist_type_tags),
            protagonist_job_tags = VALUES(protagonist_job_tags),
            axis_style_tags = VALUES(axis_style_tags),
            axis_romance_tags = VALUES(axis_romance_tags),
            themes = VALUES(themes),
            similar_famous = VALUES(similar_famous),
            taste_tags = VALUES(taste_tags),
            analysis_status = 'success',
            analysis_error_message = NULL,
            model_version = 'manual-edit',
            analyzed_at = NOW(),
            updated_date = NOW()
        """
    )

    await db.execute(
        query,
        {
            "product_id": product_id,
            "protagonist_type": normalized["protagonist_type"],
            "protagonist_desc": normalized["protagonist_desc"],
            "heroine_type": normalized["heroine_type"],
            "heroine_weight": normalized["heroine_weight"],
            "romance_chemistry_weight": normalized["romance_chemistry_weight"],
            "mood": normalized["mood"],
            "pacing": normalized["pacing"],
            "premise": normalized["premise"],
            "hook": normalized["hook"],
            "episode_summary_text": normalized["episode_summary_text"],
            "protagonist_goal_primary": normalized["protagonist_goal_primary"],
            "goal_confidence": normalized["goal_confidence"],
            "overall_confidence": normalized["overall_confidence"],
            "axis_label_scores": json.dumps(normalized["axis_label_scores"], ensure_ascii=False),
            "protagonist_material_tags": json.dumps(normalized["protagonist_material_tags"], ensure_ascii=False),
            "worldview_tags": json.dumps(normalized["worldview_tags"], ensure_ascii=False),
            "protagonist_type_tags": json.dumps(normalized["protagonist_type_tags"], ensure_ascii=False),
            "protagonist_job_tags": json.dumps(normalized["protagonist_job_tags"], ensure_ascii=False),
            "axis_style_tags": json.dumps(normalized["axis_style_tags"], ensure_ascii=False),
            "axis_romance_tags": json.dumps(normalized["axis_romance_tags"], ensure_ascii=False),
            "themes": json.dumps(normalized["themes"], ensure_ascii=False),
            "similar_famous": json.dumps(normalized["similar_famous"], ensure_ascii=False),
            "taste_tags": json.dumps(normalized["taste_tags"], ensure_ascii=False),
        },
    )
    await db.commit()
    return {"data": {"message": "AI 메타정보가 저장되었습니다."}}


async def put_ai_product_metadata_exclude(
    product_id: int,
    exclude_from_recommend_yn: str,
    db: AsyncSession,
) -> dict[str, Any]:
    if exclude_from_recommend_yn not in ALLOWED_EXCLUDE_YN:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="exclude_from_recommend_yn 값이 올바르지 않습니다.",
        )

    await _get_product_for_analysis(product_id, db)

    query = text(
        """
        INSERT INTO tb_product_ai_metadata (product_id, exclude_from_recommend_yn)
        VALUES (:product_id, :exclude_from_recommend_yn)
        ON DUPLICATE KEY UPDATE
            exclude_from_recommend_yn = VALUES(exclude_from_recommend_yn),
            updated_date = NOW()
        """
    )
    await db.execute(
        query,
        {"product_id": product_id, "exclude_from_recommend_yn": exclude_from_recommend_yn},
    )
    await db.commit()
    return {"data": {"message": "추천 제외 설정이 변경되었습니다."}}


async def reanalyze_ai_product_metadata(product_id: int, db: AsyncSession) -> dict[str, Any]:
    product = await _get_product_for_analysis(product_id, db)

    current_query = text(
        """
        SELECT analysis_attempt_count
        FROM tb_product_ai_metadata
        WHERE product_id = :product_id
        LIMIT 1
        """
    )
    current_result = await db.execute(current_query, {"product_id": product_id})
    current_row = current_result.mappings().one_or_none()
    base_attempt_count = (current_row or {}).get("analysis_attempt_count", 0) or 0

    episodes = await _get_episodes_for_analysis(product_id, db)
    episode_context, used_count = _build_episode_context(episodes)
    if used_count < MIN_REQUIRED_EPISODES:
        failed_attempt_count = base_attempt_count + 1
        await _mark_analysis_failed(
            product_id=product_id,
            analysis_attempt_count=failed_attempt_count,
            error_message=f"insufficient_episodes(<{MIN_REQUIRED_EPISODES})",
            db=db,
        )
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message=f"{MIN_REQUIRED_EPISODES}화 미만 작품은 AI 메타 분석 대상이 아닙니다.",
        )

    user_prompt = DNA_USER_TEMPLATE.format(
        title=product.get("title") or "",
        genres=product.get("genres") or "",
        keywords=product.get("keywords") or "",
        synopsis_text=(product.get("synopsis_text") or "")[:1000],
        episode_count=product.get("episode_count", 0),
        status_code=product.get("status_code") or "",
        n_requested=MAX_ANALYZE_EPISODES,
        n_received=used_count,
        allowed_labels_json=_allowed_labels_for_prompt(),
        label_definitions_text=_load_label_definitions(),
        episodes_text=episode_context,
    )

    last_error = "unknown error"
    for retry_index in range(MAX_RETRY_COUNT + 1):
        attempt_count = base_attempt_count + retry_index + 1
        try:
            raw = await recommendation_service._call_claude(
                DNA_SYSTEM_PROMPT,
                user_prompt,
                max_tokens=MAX_LLM_OUTPUT_TOKENS,
                fail_on_max_tokens=True,
            )
            parsed = recommendation_service._parse_json_from_llm(raw)
            raw_analysis_payload = json.dumps(parsed, ensure_ascii=False)
            normalized = _normalize_ai_payload(
                parsed,
                enforce_axis_minimum=True,
                enforce_legacy_required=True,
                drop_unsupported_axis_labels=True,
                source_text="\n".join(
                    [
                        str(product.get("title") or ""),
                        str(product.get("genres") or ""),
                        str(product.get("keywords") or ""),
                        str(product.get("synopsis_text") or ""),
                        episode_context,
                    ]
                ),
            )

            upsert_query = text(
                """
                INSERT INTO tb_product_ai_metadata (
                    product_id,
                    protagonist_type, protagonist_desc, heroine_type, heroine_weight, romance_chemistry_weight,
                    mood, pacing, premise, hook,
                    episode_summary_text,
                    protagonist_goal_primary, goal_confidence, overall_confidence, axis_label_scores,
                    protagonist_material_tags, worldview_tags, protagonist_type_tags, protagonist_job_tags, axis_style_tags, axis_romance_tags,
                    themes, similar_famous, taste_tags,
                    raw_analysis, analyzed_at, model_version,
                    analysis_status, analysis_attempt_count, analysis_error_message
                ) VALUES (
                    :product_id,
                    :protagonist_type, :protagonist_desc, :heroine_type, :heroine_weight, :romance_chemistry_weight,
                    :mood, :pacing, :premise, :hook,
                    :episode_summary_text,
                    :protagonist_goal_primary, :goal_confidence, :overall_confidence, :axis_label_scores,
                    :protagonist_material_tags, :worldview_tags, :protagonist_type_tags, :protagonist_job_tags, :axis_style_tags, :axis_romance_tags,
                    :themes, :similar_famous, :taste_tags,
                    :raw_analysis, NOW(), :model_version,
                    'success', :analysis_attempt_count, NULL
                )
                ON DUPLICATE KEY UPDATE
                    protagonist_type = VALUES(protagonist_type),
                    protagonist_desc = VALUES(protagonist_desc),
                    heroine_type = VALUES(heroine_type),
                    heroine_weight = VALUES(heroine_weight),
                    romance_chemistry_weight = VALUES(romance_chemistry_weight),
                    mood = VALUES(mood),
                    pacing = VALUES(pacing),
                    premise = VALUES(premise),
                    hook = VALUES(hook),
                    episode_summary_text = VALUES(episode_summary_text),
                    protagonist_goal_primary = VALUES(protagonist_goal_primary),
                    goal_confidence = VALUES(goal_confidence),
                    overall_confidence = VALUES(overall_confidence),
                    axis_label_scores = VALUES(axis_label_scores),
                    protagonist_material_tags = VALUES(protagonist_material_tags),
                    worldview_tags = VALUES(worldview_tags),
                    protagonist_type_tags = VALUES(protagonist_type_tags),
                    protagonist_job_tags = VALUES(protagonist_job_tags),
                    axis_style_tags = VALUES(axis_style_tags),
                    axis_romance_tags = VALUES(axis_romance_tags),
                    themes = VALUES(themes),
                    similar_famous = VALUES(similar_famous),
                    taste_tags = VALUES(taste_tags),
                    raw_analysis = VALUES(raw_analysis),
                    analyzed_at = NOW(),
                    model_version = VALUES(model_version),
                    analysis_status = 'success',
                    analysis_attempt_count = VALUES(analysis_attempt_count),
                    analysis_error_message = NULL,
                    updated_date = NOW()
                """
            )
            await db.execute(
                upsert_query,
                {
                    "product_id": product_id,
                    "protagonist_type": normalized["protagonist_type"],
                    "protagonist_desc": normalized["protagonist_desc"],
                    "heroine_type": normalized["heroine_type"],
                    "heroine_weight": normalized["heroine_weight"],
                    "romance_chemistry_weight": normalized["romance_chemistry_weight"],
                    "mood": normalized["mood"],
                    "pacing": normalized["pacing"],
                    "premise": normalized["premise"],
                    "hook": normalized["hook"],
                    "episode_summary_text": normalized["episode_summary_text"],
                    "protagonist_goal_primary": normalized["protagonist_goal_primary"],
                    "goal_confidence": normalized["goal_confidence"],
                    "overall_confidence": normalized["overall_confidence"],
                    "axis_label_scores": json.dumps(normalized["axis_label_scores"], ensure_ascii=False),
                    "protagonist_material_tags": json.dumps(normalized["protagonist_material_tags"], ensure_ascii=False),
                    "worldview_tags": json.dumps(normalized["worldview_tags"], ensure_ascii=False),
                    "protagonist_type_tags": json.dumps(normalized["protagonist_type_tags"], ensure_ascii=False),
                    "protagonist_job_tags": json.dumps(normalized["protagonist_job_tags"], ensure_ascii=False),
                    "axis_style_tags": json.dumps(normalized["axis_style_tags"], ensure_ascii=False),
                    "axis_romance_tags": json.dumps(normalized["axis_romance_tags"], ensure_ascii=False),
                    "themes": json.dumps(normalized["themes"], ensure_ascii=False),
                    "similar_famous": json.dumps(normalized["similar_famous"], ensure_ascii=False),
                    "taste_tags": json.dumps(normalized["taste_tags"], ensure_ascii=False),
                    "raw_analysis": raw_analysis_payload,
                    "model_version": settings.ANTHROPIC_MODEL,
                    "analysis_attempt_count": attempt_count,
                },
            )
            await db.commit()
            return {
                "data": {
                    "message": "AI 메타 분석이 완료되었습니다.",
                    "analysis_status": "success",
                    "analysis_attempt_count": attempt_count,
                    "axis_labels": _build_axis_labels_from_columns(normalized),
                }
            }
        except Exception as e:
            await db.rollback()
            last_error = str(e)
            logger.warning(
                f"[AI_META_REANALYZE_FAIL] product_id={product_id} "
                f"attempt={retry_index + 1}/{MAX_RETRY_COUNT + 1} error={last_error}"
            )

    failed_attempt_count = base_attempt_count + MAX_RETRY_COUNT + 1
    await _mark_analysis_failed(
        product_id=product_id,
        analysis_attempt_count=failed_attempt_count,
        error_message=last_error,
        db=db,
    )
    raise CustomResponseException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        message="AI 메타 분석에 실패했습니다. 최대 3회 시도 후 중단되었습니다.",
    )
